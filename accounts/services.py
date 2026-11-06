import secrets
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import (
    User,
    IdentitySequence,
    StudentProfile,
    OTPChallenge,
    RecoveryCode,
    TrustedDevice,
    UserSession,
    SecurityEvent,
)
from .security import (
    get_client_ip,
    get_user_agent,
    log_security_event,
)
from .sms_provider import send_sms_otp_via_provider

# حالت آزمایشی تا زمان خرید پنل پیامک (کد ثابت: 123456)
DEV_FIXED_OTP_CODE = '123456'
# اگر بخواهی صفحه 2FA به کل رد شود و مستقیم وارد داشبورد شوی، این مقدار را True کن:
BYPASS_2FA_COMPLETELY = False


@transaction.atomic
def generate_atomic_academy_username(year_two_digits: int = None) -> str:
    """تولید اتمیک نام کاربری آکادمی با فرمت TRJ-260001"""
    if year_two_digits is None:
        year_two_digits = timezone.now().year % 100

    seq, _ = IdentitySequence.objects.select_for_update().get_or_create(
        year_prefix=year_two_digits,
        defaults={'last_value': 0}
    )

    while True:
        seq.last_value += 1
        candidate = f"TRJ-{year_two_digits:02d}{seq.last_value:04d}"
        if not User.objects.filter(academy_username=candidate).exists():
            seq.save(update_fields=['last_value', 'updated_at'])
            return candidate


@transaction.atomic
def approve_student_account(student: User, approved_by: User, request=None) -> User:
    """تأیید حساب زبان‌آموز توسط مدیریت و تخصیص خودکار کد TRJ-26XXXX"""
    locked_student = User.objects.select_for_update().get(id=student.id)
    if locked_student.role != User.Role.STUDENT:
        raise ValidationError('این عملیات فقط برای حساب‌های زبان‌آموز مجاز است.')

    if not locked_student.academy_username:
        locked_student.academy_username = generate_atomic_academy_username()

    locked_student.status = User.Status.ACTIVE
    locked_student.is_active = True
    locked_student.approved_at = timezone.now()
    locked_student.approved_by = approved_by
    locked_student.save(update_fields=['academy_username', 'status', 'is_active', 'approved_at', 'approved_by', 'updated_at'])

    StudentProfile.objects.get_or_create(user=locked_student)

    log_security_event(
        request,
        event_type='STUDENT_APPROVED',
        description=f"تأیید حساب زبان‌آموز و تخصیص کد {locked_student.academy_username}",
        user=locked_student,
        severity=SecurityEvent.Severity.INFO
    )
    return locked_student


@transaction.atomic
def issue_sms_otp_challenge(user: User, purpose: str, request=None, send_via_provider: bool = True):
    """
    صدور کد OTP.
    تا زمانی که سرویس پیامک خریداری نشده، کد ثابت 123456 بدون محدودیت صادر می‌شود.
    """
    ip = get_client_ip(request)
    phone = user.phone
    sms_configured = bool(getattr(settings, 'SMS_PROVIDER', '') and getattr(settings, 'SMS_API_KEY', ''))

    # ابطال کدهای قبلی
    OTPChallenge.objects.filter(
        user=user,
        purpose=purpose,
        consumed_at__isnull=True,
        invalidated_at__isnull=True
    ).update(invalidated_at=timezone.now())

    # اگر سرویس پیامک هنوز تنظیم نشده، کد را 123456 قرار بده
    if not sms_configured:
        raw_code = DEV_FIXED_OTP_CODE
    else:
        raw_code = f"{secrets.randbelow(900000) + 100000:06d}"

    challenge = OTPChallenge(
        user=user,
        destination_phone=phone,
        purpose=purpose,
        ip_address=ip,
        expires_at=timezone.now() + timedelta(minutes=30),
    )
    challenge.set_code(raw_code)
    challenge.save()

    if send_via_provider and sms_configured:
        send_sms_otp_via_provider(phone=phone, otp_code=raw_code)

    return challenge, raw_code


@transaction.atomic
def verify_sms_otp_challenge(user: User, raw_code: str, purpose: str, request=None) -> bool:
    """
    بررسی کد ۶ رقمی OTP.
    در حالت بدون سرویس پیامک، کد 123456 همیشه به صورت مستقیم پذیرفته می‌شود.
    """
    entered_code = (raw_code or '').strip()
    sms_configured = bool(getattr(settings, 'SMS_PROVIDER', '') and getattr(settings, 'SMS_API_KEY', ''))

    # پذیرش مستقیم کد 123456 تا زمان خرید سرویس پیامک
    if not sms_configured and entered_code == DEV_FIXED_OTP_CODE:
        OTPChallenge.objects.filter(
            user=user,
            purpose=purpose,
            consumed_at__isnull=True
        ).update(consumed_at=timezone.now())

        if not user.is_phone_verified:
            user.is_phone_verified = True
            user.save(update_fields=['is_phone_verified', 'updated_at'])

        log_security_event(
            request,
            event_type='OTP_VERIFIED_DEV',
            description=f"تأیید موفق با کد آزمایشی 123456 ({purpose})",
            user=user
        )
        return True

    challenge = (
        OTPChallenge.objects.select_for_update()
        .filter(user=user, purpose=purpose)
        .order_by('-created_at')
        .first()
    )

    if not challenge or not challenge.is_usable:
        raise ValidationError('کد وارد شده نامعتبر یا منقضی شده است.')

    if not challenge.verify_code(entered_code):
        challenge.attempts_count += 1
        if challenge.attempts_count >= challenge.max_attempts:
            challenge.invalidated_at = timezone.now()
        challenge.save(update_fields=['attempts_count', 'invalidated_at'])
        raise ValidationError('کد وارد شده نامعتبر یا منقضی شده است.')

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=['consumed_at'])

    if not user.is_phone_verified:
        user.is_phone_verified = True
        user.save(update_fields=['is_phone_verified', 'updated_at'])

    return True


@transaction.atomic
def generate_recovery_codes_for_user(user: User, count: int = 10, request=None) -> list[str]:
    RecoveryCode.objects.filter(user=user).delete()
    plaintext_codes = []
    alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'

    for _ in range(count):
        part1 = ''.join(secrets.choice(alphabet) for _ in range(4))
        part2 = ''.join(secrets.choice(alphabet) for _ in range(4))
        raw_code = f"TRJ-{part1}-{part2}"
        plaintext_codes.append(raw_code)
        RecoveryCode.objects.create(
            user=user,
            code_prefix=raw_code[:8],
            code_hash=make_password(raw_code.upper())
        )
    return plaintext_codes


@transaction.atomic
def consume_recovery_code(user: User, raw_code: str, request=None) -> bool:
    normalized = raw_code.strip().upper()
    unused_codes = RecoveryCode.objects.select_for_update().filter(user=user, used_at__isnull=True)
    for rc in unused_codes:
        if check_password(normalized, rc.code_hash):
            rc.used_at = timezone.now()
            rc.save(update_fields=['used_at'])
            return True
    return False


def check_student_trusted_device(request, user: User) -> bool:
    if user.role != User.Role.STUDENT or not request:
        return False

    cookie_name = getattr(settings, 'TRUSTED_DEVICE_COOKIE_NAME', 'toranj_trusted_device')
    raw_token = request.COOKIES.get(cookie_name)
    if not raw_token:
        return False

    token_hash = TrustedDevice.hash_raw_token(raw_token)
    device = TrustedDevice.objects.filter(user=user, token_hash=token_hash, revoked_at__isnull=True).first()
    if not device or not device.is_valid:
        return False

    device.last_used_at = timezone.now()
    device.save(update_fields=['last_used_at'])
    return True


def create_student_trusted_device(request, user: User) -> tuple[TrustedDevice, str]:
    if user.role != User.Role.STUDENT:
        raise ValidationError('قابلیت دستگاه مورد اعتماد فقط برای زبان‌آموزان مجاز است.')

    raw_token = secrets.token_urlsafe(32)
    token_hash = TrustedDevice.hash_raw_token(raw_token)
    days = getattr(settings, 'TRUSTED_DEVICE_MAX_AGE_DAYS', 30)

    device = TrustedDevice.objects.create(
        user=user,
        token_hash=token_hash,
        device_name=get_user_agent(request) or 'مرورگر وب',
        ip_address=get_client_ip(request),
        expires_at=timezone.now() + timedelta(days=days),
    )
    return device, raw_token


def does_user_require_2fa_on_login(request, user: User) -> bool:
    if BYPASS_2FA_COMPLETELY:
        return False
    if user.requires_mandatory_staff_2fa:
        return True
    if user.require_2fa_every_login:
        return True
    if user.last_2fa_verified_at is None:
        return True
    if user.failed_login_attempts >= 3:
        return True
    if not check_student_trusted_device(request, user):
        return True
    return False


def revoke_all_user_trusted_devices_and_sessions(user: User, exclude_session_key: str = None, request=None):
    TrustedDevice.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    sessions_qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if exclude_session_key:
        sessions_qs = sessions_qs.exclude(session_key_hash=UserSession.hash_session_key(exclude_session_key))
    sessions_qs.update(revoked_at=timezone.now())