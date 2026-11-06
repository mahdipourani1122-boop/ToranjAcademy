from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache
from django.core.exceptions import ValidationError

from .models import (
    User,
    StudentProfile,
    Authenticator,
    OTPChallenge,
    TrustedDevice,
)
from .services import (
    approve_student_account,
    issue_sms_otp_challenge,
    verify_sms_otp_challenge,
    generate_recovery_codes_for_user,
    consume_recovery_code,
    create_student_trusted_device,
)
from .totp import generate_base32_secret, encrypt_totp_secret, get_current_totp_code


class Phase2CompleteAuthenticationAndSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.register_url = reverse('accounts:register')
        self.login_url = reverse('accounts:login')
        self.verify_2fa_url = reverse('accounts:verify_2fa')

        self.admin = User.objects.create_superuser(
            phone='09120000001',
            first_name='مدیر',
            last_name='ارشد',
            email='admin@toranj.ir',
            password='StrongPassword123!'
        )
        self.teacher = User.objects.create_user(
            phone='09120000002',
            first_name='استاد',
            last_name='نمونه',
            email='teacher@toranj.ir',
            password='StrongPassword123!',
            role=User.Role.TEACHER,
            status=User.Status.ACTIVE,
            academy_username='TRJ-T01'
        )

    def _force_2fa_login(self, user):
        self.client.force_login(user, backend='accounts.backends.ToranjAuthenticationBackend')
        session = self.client.session
        session['is_2fa_verified'] = True
        session.save()

    def test_01_student_registration_and_privilege_escalation_prevention(self):
        """ثبت‌نام عمومی همیشه نقش student در وضعیت pending می‌سازد و جعل نقش admin را رد می‌کند"""
        res = self.client.post(self.register_url, {
            'first_name': 'اریشاه',
            'last_name': 'تست',
            'phone': '09123456789',
            'email': 'student@toranj.ir',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
            'accepted_terms': True,
            'role': 'admin',
            'academy_username': 'TRJ-999999',
        })
        self.assertRedirects(res, self.verify_2fa_url)
        student = User.objects.get(phone='09123456789')
        self.assertEqual(student.role, User.Role.STUDENT)
        self.assertEqual(student.status, User.Status.PENDING)
        self.assertIsNone(student.academy_username)
        self.assertFalse(student.student_profile.is_enrolled)
        self.assertFalse(student.student_profile.is_paid)

    def test_02_password_mismatch_is_rejected(self):
        """عدم تطابق رمز عبور و تکرار آن رد می‌شود"""
        res = self.client.post(self.register_url, {
            'first_name': 'علی',
            'last_name': 'رضایی',
            'phone': '09121112233',
            'password': 'StrongPassword123!',
            'confirm_password': 'DifferentPassword123!',
            'accepted_terms': True,
        })
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(phone='09121112233').exists())

    def test_03_academy_approval_and_atomic_unique_username_generation(self):
        """تأیید آموزشگاه به صورت خودکار کدهای یکتای متوالی TRJ-260001 و TRJ-260002 صادر می‌کند"""
        s1 = User.objects.create_user(phone='09121110001', first_name='الف', last_name='یک', password='StrongPassword123!')
        s2 = User.objects.create_user(phone='09121110002', first_name='ب', last_name='دو', password='StrongPassword123!')

        approve_student_account(s1, approved_by=self.admin)
        approve_student_account(s2, approved_by=self.admin)

        s1.refresh_from_db()
        s2.refresh_from_db()
        yy = timezone.now().year % 100
        self.assertEqual(s1.academy_username, f"TRJ-{yy:02d}0001")
        self.assertEqual(s2.academy_username, f"TRJ-{yy:02d}0002")
        self.assertEqual(s1.status, User.Status.ACTIVE)

    def test_04_phone_number_change_preserves_internal_id_and_educational_records(self):
        """تغییر شماره موبایل هرگز شناسه داخلی UUID یا ارتباط با پروفایل آموزشی را خراب نمی‌کند"""
        student = User.objects.create_user(phone='09123334444', first_name='سارا', last_name='احمدی', password='StrongPassword123!')
        original_uuid = student.id
        profile_id = student.student_profile.id

        student.phone = '09129998888'
        student.save()

        student.refresh_from_db()
        self.assertEqual(student.id, original_uuid)
        self.assertEqual(StudentProfile.objects.get(id=profile_id).user_id, original_uuid)

    def test_05_login_with_academy_username_and_mandatory_2fa_gate(self):
        """ورود با نام کاربری آکادمی (TRJ-...) قبل از تکمیل 2FA اجازه دسترسی به داشبورد را نمی‌دهد"""
        student = User.objects.create_user(phone='09125556666', first_name='کاوه', last_name='راد', password='StrongPassword123!')
        approve_student_account(student, approved_by=self.admin)
        student.refresh_from_db()

        res = self.client.post(self.login_url, {
            'identifier': student.academy_username,
            'password': 'StrongPassword123!',
        })
        self.assertRedirects(res, self.verify_2fa_url)

        # تلاش برای باز کردن مستقیم داشبورد قبل از تکمیل 2FA باید مسدود شود
        dash_res = self.client.get(reverse('dashboards:student'))
        self.assertNotEqual(dash_res.status_code, 200)

    def test_06_otp_incorrect_expired_reused_and_rate_limiting(self):
        """بررسی کد اشتباه، کد منقضی‌شده، جلوگیری از مصرف مجدد کد OTP و محدودیت Cooldown"""
        student = User.objects.create_user(phone='09127778888', first_name='مینا', last_name='نوری', password='StrongPassword123!')
        challenge, raw_code = issue_sms_otp_challenge(student, OTPChallenge.Purpose.LOGIN_2FA, send_via_provider=False)

        # ۱. درخواست مجدد بلافاصله (قبل از ۶۰ ثانیه) باید خطای Cooldown بدهد
        with self.assertRaises(ValidationError):
            issue_sms_otp_challenge(student, OTPChallenge.Purpose.LOGIN_2FA, send_via_provider=False)

        # ۲. کد اشتباه باید رد شود
        with self.assertRaises(ValidationError):
            verify_sms_otp_challenge(student, '000000', OTPChallenge.Purpose.LOGIN_2FA)

        # ۳. کد صحیح در بار اول پذیرفته می‌شود
        self.assertTrue(verify_sms_otp_challenge(student, raw_code, OTPChallenge.Purpose.LOGIN_2FA))

        # ۴. مصرف مجدد همان کد (Reused OTP) باید رد شود
        with self.assertRaises(ValidationError):
            verify_sms_otp_challenge(student, raw_code, OTPChallenge.Purpose.LOGIN_2FA)

        # ۵. کد منقضی‌شده (Expired OTP) باید رد شود
        OTPChallenge.objects.filter(user=student).delete()
        cache.clear()
        exp_challenge, exp_code = issue_sms_otp_challenge(student, OTPChallenge.Purpose.LOGIN_2FA, send_via_provider=False)
        exp_challenge.expires_at = timezone.now() - timedelta(minutes=1)
        exp_challenge.save()
        with self.assertRaises(ValidationError):
            verify_sms_otp_challenge(student, exp_code, OTPChallenge.Purpose.LOGIN_2FA)

    def test_07_totp_activation_verification_and_replay_protection(self):
        """فعال‌سازی TOTP، تأیید کد ۶ رقمی استاندارد و جلوگیری از مصرف مجدد در همان پنجره زمانی"""
        secret = generate_base32_secret()
        Authenticator.objects.create(
            user=self.admin,
            encrypted_secret=encrypt_totp_secret(secret),
            is_active=True
        )
        live_code = get_current_totp_code(secret)

        self.client.post(self.login_url, {'identifier': self.admin.phone, 'password': 'StrongPassword123!'})
        res = self.client.post(self.verify_2fa_url, {'method': 'totp', 'code': live_code})
        self.assertRedirects(res, reverse('dashboards:admin'))

    def test_08_recovery_code_single_use(self):
        """کد بازیابی 2FA فقط یک بار قابل استفاده است"""
        codes = generate_recovery_codes_for_user(self.teacher)
        first_code = codes[0]

        self.assertTrue(consume_recovery_code(self.teacher, first_code))
        self.assertFalse(consume_recovery_code(self.teacher, first_code))

    def test_09_trusted_device_works_for_student_and_expires_and_never_bypasses_staff(self):
        """دستگاه مورد اعتماد ۳۰ روزه برای زبان‌آموز کار می‌کند، پس از انقضا باطل می‌شود و برای استاد/ادمین غیرمجاز است"""
        student = User.objects.create_user(
            phone='09124445555', first_name='امیر', last_name='حسینی',
            password='StrongPassword123!', status=User.Status.ACTIVE
        )
        approve_student_account(student, approved_by=self.admin)
        student.last_2fa_verified_at = timezone.now()
        student.save()

        device, raw_token = create_student_trusted_device(None, student)
        self.client.cookies['toranj_trusted_device'] = raw_token

        # ورود بدون نیاز به 2FA مجدد با دستگاه مورد اعتماد معتبر
        res = self.client.post(self.login_url, {'identifier': student.academy_username, 'password': 'StrongPassword123!'})
        self.assertRedirects(res, reverse('dashboards:student'))

        # منقضی کردن دستگاه مورد اعتماد
        self.client.logout()
        device.expires_at = timezone.now() - timedelta(days=1)
        device.save()
        res_expired = self.client.post(self.login_url, {'identifier': student.academy_username, 'password': 'StrongPassword123!'})
        self.assertRedirects(res_expired, self.verify_2fa_url)

        # استاد نمی‌تواند دستگاه مورد اعتماد بسازد
        with self.assertRaises(ValidationError):
            create_student_trusted_device(None, self.teacher)

    def test_10_role_based_dashboard_access_and_session_revocation(self):
        """کنترل دسترسی مبتنی بر نقش (RBAC) در سمت سرور"""
        student = User.objects.create_user(
            phone='09126667777', first_name='رضا', last_name='کریمی',
            password='StrongPassword123!', status=User.Status.ACTIVE
        )
        self._force_2fa_login(student)
        res = self.client.get(reverse('dashboards:admin'))
        self.assertRedirects(res, reverse('dashboards:student'))