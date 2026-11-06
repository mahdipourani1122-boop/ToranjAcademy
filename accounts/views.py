from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View

from .models import (
    User,
    Authenticator,
    OTPChallenge,
    RecoveryCode,
    TrustedDevice,
    UserSession,
    SecurityEvent,
)
from .forms import (
    StudentRegistrationForm,
    ToranjLoginForm,
    TwoFactorVerifyForm,
    TOTPVerifyActivationForm,
    TOTPDisableForm,
    PasswordChangeSecureForm,
    ToranjPasswordResetForm,
    ToranjSetPasswordForm,
)
from .security import (
    get_client_ip,
    get_user_agent,
    is_rate_limited,
    record_rate_limit_hit,
    clear_rate_limit,
    log_security_event,
)
from .services import (
    approve_student_account,
    issue_sms_otp_challenge,
    verify_sms_otp_challenge,
    generate_recovery_codes_for_user,
    consume_recovery_code,
    create_student_trusted_device,
    does_user_require_2fa_on_login,
    revoke_all_user_trusted_devices_and_sessions,
)
from .sms_provider import SMSProviderNotConfiguredError, SMSDeliveryError
from .totp import (
    generate_base32_secret,
    encrypt_totp_secret,
    decrypt_totp_secret,
    verify_totp_code,
    build_otpauth_uri,
)


def _finalize_authenticated_session(request, user: User, remember_me: bool = False):
    """
    مرحله ۵ احراز هویت: ایجاد نشست نهایی پس از تکمیل 2FA، چرخش کلید نشست (Session Rotation)
    و ثبت رکورد نشست در دیتابیس.
    """
    login(request, user, backend='accounts.backends.ToranjAuthenticationBackend')
    request.session.cycle_key()
    request.session['is_2fa_verified'] = True
    request.session.pop('pre_2fa_user_id', None)
    request.session.pop('pre_2fa_remember', None)

    expiry_seconds = 60 * 60 * 24 * 14 if remember_me else 60 * 60 * 8
    request.session.set_expiry(expiry_seconds)

    user.failed_login_attempts = 0
    user.last_2fa_verified_at = timezone.now()
    user.save(update_fields=['failed_login_attempts', 'last_2fa_verified_at', 'updated_at'])

    if not request.session.session_key:
        request.session.save()

    UserSession.objects.update_or_create(
        session_key_hash=UserSession.hash_session_key(request.session.session_key),
        defaults={
            'user': user,
            'ip_address': get_client_ip(request),
            'user_agent': get_user_agent(request),
            'is_2fa_verified': True,
            'expires_at': timezone.now() + timedelta(seconds=expiry_seconds),
            'revoked_at': None,
        }
    )

    log_security_event(
        request,
        event_type='LOGIN_SUCCESS',
        description=f"ورود موفق و تاییدشده به سامانه (نقش: {user.role})",
        user=user
    )


class StudentRegisterView(View):
    template_name = 'accounts/register.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.session.get('is_2fa_verified'):
            return redirect(request.user.get_dashboard_url_name())
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, self.template_name, {'form': StudentRegistrationForm()})

    def post(self, request):
        ip = get_client_ip(request)
        if is_rate_limited('register_ip', ip, max_attempts=6, window_seconds=600):
            form = StudentRegistrationForm()
            form.add_error(None, 'تعداد درخواست‌های ثبت‌نام بیش از حد مجاز است. لطفاً دقایقی دیگر تلاش کنید.')
            return render(request, self.template_name, {'form': form}, status=429)

        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            record_rate_limit_hit('register_ip', ip, window_seconds=600)
            log_security_event(
                request,
                event_type='STUDENT_REGISTERED',
                description='ثبت‌نام اولیه زبان‌آموز (در انتظار تأیید آموزشگاه)',
                user=user
            )

            # قرار دادن کاربر در مرحله تأیید مالکیت موبایل / 2FA اولیه
            request.session['pre_2fa_user_id'] = str(user.id)
            request.session['pre_2fa_remember'] = False
            messages.success(
                request,
                f'{user.first_name} عزیز، حساب شما ایجاد شد. پس از تأیید آموزشگاه، نام کاربری اختصاصی (TRJ-...) به شما اختصاص می‌یابد.'
            )
            return redirect('accounts:verify_2fa')

        return render(request, self.template_name, {'form': form}, status=400)


class UserLoginView(View):
    template_name = 'accounts/login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.session.get('is_2fa_verified'):
            return redirect(request.user.get_dashboard_url_name())
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, self.template_name, {'form': ToranjLoginForm()})

    def post(self, request):
        ip = get_client_ip(request)
        if is_rate_limited('login_ip', ip, max_attempts=5, window_seconds=300):
            form = ToranjLoginForm()
            form.add_error(None, 'تعداد تلاش‌های ناموفق بیش از حد مجاز است. لطفاً ۵ دقیقه دیگر مجدداً تلاش کنید.')
            return render(request, self.template_name, {'form': form}, status=429)

        form = ToranjLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            clear_rate_limit('login_ip', ip)
            remember_me = bool(form.cleaned_data.get('remember_me'))

            # بررسی سیاست 2FA بر اساس نقش و وضعیت دستگاه
            if does_user_require_2fa_on_login(request, user):
                request.session['pre_2fa_user_id'] = str(user.id)
                request.session['pre_2fa_remember'] = remember_me
                request.session['is_2fa_verified'] = False

                # اگر کاربر TOTP فعال ندارد، تلاش برای ارسال کد پیامکی OTP
                if not user.has_active_totp:
                    try:
                        issue_sms_otp_challenge(user, OTPChallenge.Purpose.LOGIN_2FA, request=request)
                        messages.info(request, 'کد تأیید ۶ رقمی به شماره موبایل شما ارسال شد.')
                    except SMSProviderNotConfiguredError as exc:
                        messages.warning(request, str(exc))
                    except (ValidationError, SMSDeliveryError) as exc:
                        msg = exc.messages[0] if hasattr(exc, 'messages') else str(exc)
                        messages.warning(request, msg)

                return redirect('accounts:verify_2fa')

            # فقط برای زبان‌آموز دارای دستگاه مورد اعتماد معتبر ۳۰ روزه و بدون الزام 2FA در هر ورود
            _finalize_authenticated_session(request, user, remember_me=remember_me)
            messages.success(request, f'{user.full_name} عزیز، خوش آمدید.')
            return redirect(user.get_dashboard_url_name())

        # ثبت تلاش ناموفق بدون افشای وجود یا عدم وجود نام کاربری
        record_rate_limit_hit('login_ip', ip, window_seconds=300)
        ident = (request.POST.get('identifier') or '').strip()
        target_user = User.objects.filter(academy_username__iexact=ident).first() or User.objects.filter(phone=ident).first()
        if target_user:
            target_user.failed_login_attempts += 1
            target_user.last_failed_login_at = timezone.now()
            target_user.save(update_fields=['failed_login_attempts', 'last_failed_login_at'])

        log_security_event(
            request,
            event_type='LOGIN_FAILED',
            description='تلاش ناموفق ورود به حساب کاربری',
            user=target_user,
            severity=SecurityEvent.Severity.WARNING
        )
        return render(request, self.template_name, {'form': form}, status=400)


class TwoFactorVerifyView(View):
    """مرحله ۴ احراز هویت: بررسی کد دومرحله‌ای (SMS OTP، اپلیکیشن TOTP یا کد بازیابی)"""
    template_name = 'accounts/verify_2fa.html'

    def _get_pending_user(self, request):
        user_id = request.session.get('pre_2fa_user_id')
        if not user_id:
            return None
        return User.objects.filter(id=user_id, is_active=True).first()

    def get(self, request):
        user = self._get_pending_user(request)
        if not user:
            return redirect('accounts:login')

        default_method = 'totp' if user.has_active_totp else 'otp'
        form = TwoFactorVerifyForm(initial={'method': default_method})
        return render(request, self.template_name, {
            'form': form,
            'pending_user': user,
            'has_totp': user.has_active_totp,
            'is_student': user.role == User.Role.STUDENT,
            'sms_configured': bool(settings.SMS_PROVIDER and settings.SMS_API_KEY),
        })

    def post(self, request):
        user = self._get_pending_user(request)
        if not user:
            return redirect('accounts:login')

        if 'resend_otp' in request.POST:
            try:
                issue_sms_otp_challenge(user, OTPChallenge.Purpose.LOGIN_2FA, request=request)
                messages.success(request, 'کد تأیید ۶ رقمی جدید ارسال شد.')
            except SMSProviderNotConfiguredError as exc:
                messages.error(request, str(exc))
            except (ValidationError, SMSDeliveryError) as exc:
                msg = exc.messages[0] if hasattr(exc, 'messages') else str(exc)
                messages.error(request, msg)
            return redirect('accounts:verify_2fa')

        form = TwoFactorVerifyForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['method']
            code = form.cleaned_data['code'].strip()
            verified = False

            try:
                if method == 'totp' and user.has_active_totp:
                    auth_obj = user.authenticator
                    secret = decrypt_totp_secret(auth_obj.encrypted_secret)
                    ok, matched_counter = verify_totp_code(secret, code, last_used_counter=auth_obj.last_used_counter)
                    if not ok:
                        raise ValidationError('کد اپلیکیشن احراز هویت نامعتبر است.')
                    auth_obj.last_used_at = timezone.now()
                    auth_obj.last_used_counter = matched_counter
                    auth_obj.save(update_fields=['last_used_at', 'last_used_counter'])
                    verified = True

                elif method == 'recovery':
                    if not consume_recovery_code(user, code, request=request):
                        raise ValidationError('کد بازیابی وارد شده نامعتبر است یا قبلاً استفاده شده است.')
                    verified = True

                else:
                    verify_sms_otp_challenge(user, code, OTPChallenge.Purpose.LOGIN_2FA, request=request)
                    verified = True

            except ValidationError as exc:
                form.add_error('code', exc.messages[0])

            if verified:
                remember_me = bool(request.session.get('pre_2fa_remember', False))
                _finalize_authenticated_session(request, user, remember_me=remember_me)
                response = redirect(user.get_dashboard_url_name())

                # ذخیره کوکی دستگاه مورد اعتماد ۳۰ روزه (فقط برای نقش زبان‌آموز)
                if user.role == User.Role.STUDENT and form.cleaned_data.get('trust_device'):
                    _, raw_device_token = create_student_trusted_device(request, user)
                    cookie_name = getattr(settings, 'TRUSTED_DEVICE_COOKIE_NAME', 'toranj_trusted_device')
                    max_age = getattr(settings, 'TRUSTED_DEVICE_MAX_AGE_DAYS', 30) * 86400
                    response.set_cookie(
                        cookie_name,
                        raw_device_token,
                        max_age=max_age,
                        httponly=True,
                        samesite='Lax',
                        secure=not settings.DEBUG,
                    )

                messages.success(request, f'{user.full_name} عزیز، احراز هویت دومرحله‌ای با موفقیت انجام شد.')
                return response

        return render(request, self.template_name, {
            'form': form,
            'pending_user': user,
            'has_totp': user.has_active_totp,
            'is_student': user.role == User.Role.STUDENT,
            'sms_configured': bool(settings.SMS_PROVIDER and settings.SMS_API_KEY),
        }, status=400)


class UserLogoutView(View):
    def post(self, request):
        if request.user.is_authenticated and request.session.session_key:
            key_hash = UserSession.hash_session_key(request.session.session_key)
            UserSession.objects.filter(session_key_hash=key_hash).update(revoked_at=timezone.now())
            log_security_event(request, 'LOGOUT', 'خروج کاربر از حساب کاربری', user=request.user)
        logout(request)
        messages.info(request, 'شما با موفقیت از حساب کاربری خود خارج شدید.')
        return redirect('core:home')


# ==========================================
# صفحات تنظیمات امنیتی حساب (Security Settings UI)
# ==========================================
class SecuritySettingsView(LoginRequiredMixin, View):
    template_name = 'accounts/security/settings.html'

    def get(self, request):
        user = request.user
        unused_recovery_count = RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
        trusted_devices = TrustedDevice.objects.filter(user=user, revoked_at__isnull=True)
        active_sessions = UserSession.objects.filter(user=user, revoked_at__isnull=True)[:10]
        recent_events = SecurityEvent.objects.filter(user=user)[:12]

        return render(request, self.template_name, {
            'has_totp': user.has_active_totp,
            'unused_recovery_count': unused_recovery_count,
            'trusted_devices': trusted_devices,
            'active_sessions': active_sessions,
            'recent_events': recent_events,
        })

    def post(self, request):
        action = request.POST.get('action')
        if action == 'toggle_every_login_2fa' and request.user.role == User.Role.STUDENT:
            request.user.require_2fa_every_login = not request.user.require_2fa_every_login
            request.user.save(update_fields=['require_2fa_every_login', 'updated_at'])
            messages.success(request, 'تنظیمات ورود دومرحله‌ای شما بروزرسانی شد.')
        elif action == 'revoke_session':
            session_id = request.POST.get('session_id')
            UserSession.objects.filter(id=session_id, user=request.user).update(revoked_at=timezone.now())
            messages.info(request, 'نشست انتخاب‌شده باطل شد.')
        return redirect('accounts:security_settings')


class TOTPSetupView(LoginRequiredMixin, View):
    template_name = 'accounts/security/totp_setup.html'

    def get(self, request):
        auth_obj, created = Authenticator.objects.get_or_create(
            user=request.user,
            defaults={'encrypted_secret': encrypt_totp_secret(generate_base32_secret()), 'is_active': False}
        )
        if not auth_obj.is_active and not created:
            # استفاده از کلید در انتظار فعال‌سازی
            secret = decrypt_totp_secret(auth_obj.encrypted_secret)
        elif not auth_obj.is_active:
            secret = decrypt_totp_secret(auth_obj.encrypted_secret)
        else:
            secret = None

        account_label = request.user.academy_username or request.user.phone
        otpauth_uri = build_otpauth_uri(secret, account_label) if secret else None

        return render(request, self.template_name, {
            'is_active': auth_obj.is_active,
            'secret_key': secret,
            'otpauth_uri': otpauth_uri,
            'activate_form': TOTPVerifyActivationForm(),
            'disable_form': TOTPDisableForm(),
        })

    def post(self, request):
        action = request.POST.get('action', 'activate')
        auth_obj = get_object_or_404(Authenticator, user=request.user)

        if action == 'activate':
            form = TOTPVerifyActivationForm(request.POST)
            secret = decrypt_totp_secret(auth_obj.encrypted_secret)
            if form.is_valid():
                ok, counter = verify_totp_code(secret, form.cleaned_data['code'])
                if ok:
                    auth_obj.is_active = True
                    auth_obj.verified_at = timezone.now()
                    auth_obj.last_used_counter = counter
                    auth_obj.save()

                    new_codes = generate_recovery_codes_for_user(request.user, request=request)
                    request.session['newly_generated_recovery_codes'] = new_codes
                    log_security_event(request, 'TOTP_ACTIVATED', 'فعال‌سازی موفق اپلیکیشن TOTP', user=request.user)
                    messages.success(request, 'اپلیکیشن احراز هویت (TOTP) با موفقیت فعال شد. کدهای بازیابی خود را یادداشت کنید.')
                    return redirect('accounts:recovery_codes')
                form.add_error('code', 'کد وارد شده صحیح نیست. لطفاً زمان گوشی خود را بررسی کنید.')

            account_label = request.user.academy_username or request.user.phone
            return render(request, self.template_name, {
                'is_active': False,
                'secret_key': secret,
                'otpauth_uri': build_otpauth_uri(secret, account_label),
                'activate_form': form,
                'disable_form': TOTPDisableForm(),
            }, status=400)

        elif action == 'disable':
            if request.user.role == User.Role.ADMIN:
                messages.error(request, 'بر اساس سیاست امنیتی آکادمی، غیرفعال‌سازی TOTP برای مدیر ارشد مجاز نیست.')
                return redirect('accounts:totp_setup')

            form = TOTPDisableForm(request.POST)
            if form.is_valid() and request.user.check_password(form.cleaned_data['current_password']):
                auth_obj.delete()
                log_security_event(
                    request, 'TOTP_DISABLED', 'غیرفعال‌سازی TOTP پس از تأیید مجدد رمز عبور',
                    user=request.user, severity=SecurityEvent.Severity.WARNING
                )
                messages.warning(request, 'احراز هویت TOTP غیرفعال شد.')
                return redirect('accounts:security_settings')

            messages.error(request, 'رمز عبور فعلی وارد شده صحیح نمی‌باشد.')
            return redirect('accounts:totp_setup')


class RecoveryCodesView(LoginRequiredMixin, View):
    template_name = 'accounts/security/recovery_codes.html'

    def get(self, request):
        fresh_codes = request.session.pop('newly_generated_recovery_codes', None)
        existing_codes = RecoveryCode.objects.filter(user=request.user).order_by('created_at')
        return render(request, self.template_name, {
            'fresh_codes': fresh_codes,
            'existing_codes': existing_codes,
        })

    def post(self, request):
        current_password = request.POST.get('current_password', '')
        if not request.user.check_password(current_password):
            messages.error(request, 'برای تولید مجدد کدهای بازیابی، وارد کردن رمز عبور فعلی الزامی است.')
            return redirect('accounts:recovery_codes')

        fresh_codes = generate_recovery_codes_for_user(request.user, request=request)
        request.session['newly_generated_recovery_codes'] = fresh_codes
        messages.success(request, '۱۰ کد بازیابی یک‌بارمصرف جدید تولید شد و کدهای قبلی باطل شدند.')
        return redirect('accounts:recovery_codes')


class TrustedDevicesView(LoginRequiredMixin, View):
    template_name = 'accounts/security/trusted_devices.html'

    def get(self, request):
        devices = TrustedDevice.objects.filter(user=request.user, revoked_at__isnull=True)
        return render(request, self.template_name, {'devices': devices})

    def post(self, request):
        device_id = request.POST.get('device_id')
        if device_id == 'all':
            TrustedDevice.objects.filter(user=request.user, revoked_at__isnull=True).update(revoked_at=timezone.now())
            messages.info(request, 'تمامی دستگاه‌های مورد اعتماد لغو شدند.')
        else:
            TrustedDevice.objects.filter(id=device_id, user=request.user).update(revoked_at=timezone.now())
            messages.info(request, 'دستگاه انتخاب‌شده از لیست مورد اعتماد حذف شد.')
        return redirect('accounts:trusted_devices')


class SecurePasswordChangeView(LoginRequiredMixin, View):
    template_name = 'accounts/security/password_change.html'

    def get(self, request):
        return render(request, self.template_name, {'form': PasswordChangeSecureForm(request.user)})

    def post(self, request):
        form = PasswordChangeSecureForm(request.user, request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['new_password'])
            request.user.password_changed_at = timezone.now()
            request.user.save(update_fields=['password', 'password_changed_at', 'updated_at'])
            update_session_auth_hash(request, request.user)

            # ابطال خودکار تمامی دستگاه‌های مورد اعتماد و سایر نشست‌ها پس از تغییر رمز
            revoke_all_user_trusted_devices_and_sessions(
                request.user,
                exclude_session_key=request.session.session_key,
                request=request
            )
            log_security_event(
                request, 'PASSWORD_CHANGED', 'تغییر رمز عبور و ابطال دستگاه‌های مورد اعتماد',
                user=request.user, severity=SecurityEvent.Severity.WARNING
            )
            messages.success(request, 'رمز عبور با موفقیت تغییر یافت و تمامی دستگاه‌های مورد اعتماد قبلی لغو شدند.')
            return redirect('accounts:security_settings')
        return render(request, self.template_name, {'form': form}, status=400)


class AdminApproveStudentView(LoginRequiredMixin, View):
    """تأیید حساب زبان‌آموز توسط مدیر و صدور اتمیک نام کاربری آکادمی (TRJ-26XXXX)"""
    def post(self, request, user_id):
        if request.user.role != User.Role.ADMIN or not request.session.get('is_2fa_verified'):
            messages.error(request, 'دسترسی غیرمجاز.')
            return redirect('accounts:login')

        student = get_object_or_404(User, id=user_id, role=User.Role.STUDENT)
        approved_student = approve_student_account(student, approved_by=request.user, request=request)
        messages.success(
            request,
            f'حساب زبان‌آموز «{approved_student.full_name}» تأیید شد و نام کاربری یکتای «{approved_student.academy_username}» صادر گردید.'
        )
        return redirect('dashboards:admin')


class ToranjPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset.html'
    form_class = ToranjPasswordResetForm
    email_template_name = 'accounts/password_reset_email.txt'
    success_url = reverse_lazy('accounts:password_reset_done')

    def post(self, request, *args, **kwargs):
        ip = get_client_ip(request)
        if is_rate_limited('pwd_reset', ip, max_attempts=3, window_seconds=600):
            form = self.get_form()
            form.add_error(None, 'تعداد درخواست‌های بازیابی رمز بیش از حد مجاز است. ۱۰ دقیقه صبر کنید.')
            return self.form_invalid(form)
        record_rate_limit_hit('pwd_reset', ip, window_seconds=600)
        return super().post(request, *args, **kwargs)


class ToranjPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'


class ToranjPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    form_class = ToranjSetPasswordForm
    success_url = reverse_lazy('accounts:password_reset_complete')

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.user:
            revoke_all_user_trusted_devices_and_sessions(self.user, request=self.request)
            log_security_event(
                self.request,
                'PASSWORD_RESET_COMPLETED',
                'بازنشانی رمز عبور از طریق توکن یک‌بارمصرف و ابطال دستگاه‌های قبلی',
                user=self.user,
                severity=SecurityEvent.Severity.WARNING
            )
        return response


class ToranjPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'