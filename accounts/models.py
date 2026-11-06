import uuid
import hashlib
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.contrib.auth.hashers import make_password, check_password
from django.core.validators import RegexValidator
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, phone=None, first_name='', last_name='', email=None, password=None, **extra_fields):
        if not phone and email:
            phone = extra_fields.pop('fallback_phone', '09120000000')
        if not phone:
            raise ValueError('وارد کردن شماره موبایل الزامی است.')

        phone = phone.strip()
        email = self.normalize_email(email).lower().strip() if email else None
        if email == '':
            email = None

        extra_fields.setdefault('role', User.Role.STUDENT)
        extra_fields.setdefault('status', User.Status.PENDING)

        user = self.model(
            phone=phone,
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            **extra_fields
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)

        if user.role == User.Role.STUDENT:
            StudentProfile.objects.get_or_create(user=user)
        return user

    def create_superuser(self, phone='09120000000', first_name='مدیر', last_name='ارشد', email=None, password=None, **extra_fields):
        extra_fields['role'] = User.Role.ADMIN
        extra_fields['status'] = User.Status.ACTIVE
        extra_fields['is_staff'] = True
        extra_fields['is_superuser'] = True
        extra_fields['is_phone_verified'] = True
        extra_fields.setdefault('academy_username', 'TRJ-ADMIN')
        return self.create_user(phone=phone, first_name=first_name, last_name=last_name, email=email, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        STUDENT = 'student', 'زبان‌آموز'
        TEACHER = 'teacher', 'استاد'
        SUPERVISOR = 'supervisor', 'سوپروایزر آموزشی'
        ADMIN = 'admin', 'مدیر سامانه'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'فعال و تأیید شده'
        PENDING = 'pending', 'در انتظار تأیید آموزشگاه'
        SUSPENDED = 'suspended', 'مسدود شده'

    phone_validator = RegexValidator(
        regex=r'^09\d{9}$',
        message='شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود (مثال: 09123456789).'
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academy_username = models.CharField(
        'نام کاربری آکادمی',
        max_length=24,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text='شناسه یکتای آکادمی (مثال: TRJ-260001) که پس از تأیید حساب به صورت خودکار تولید می‌شود.'
    )

    first_name = models.CharField('نام', max_length=80)
    last_name = models.CharField('نام خانوادگی', max_length=80)
    phone = models.CharField('شماره موبایل', max_length=11, unique=True, validators=[phone_validator], db_index=True)
    email = models.EmailField('آدرس ایمیل (اختیاری)', unique=True, null=True, blank=True, db_index=True)

    role = models.CharField('نقش کاربری', max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)
    status = models.CharField('وضعیت حساب', max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    is_phone_verified = models.BooleanField('تأیید مالکیت موبایل', default=False)
    require_2fa_every_login = models.BooleanField('الزام 2FA در هر ورود', default=False)
    failed_login_attempts = models.PositiveIntegerField('تلاش‌های ناموفق متوالی', default=0)
    last_failed_login_at = models.DateTimeField('آخرین تلاش ناموفق', null=True, blank=True)
    last_2fa_verified_at = models.DateTimeField('آخرین تأیید 2FA', null=True, blank=True)
    password_changed_at = models.DateTimeField('آخرین تغییر رمز عبور', default=timezone.now)

    accepted_terms = models.BooleanField('پذیرش قوانین و مقررات', default=False)
    approved_at = models.DateTimeField('تاریخ تأیید آموزشگاه', null=True, blank=True)
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_users',
        verbose_name='تأییدکننده'
    )

    is_active = models.BooleanField('حساب فعال', default=True)
    is_staff = models.BooleanField('دسترسی پنل فنی', default=False)

    created_at = models.DateTimeField('تاریخ ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین بروزرسانی', auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = 'کاربر'
        verbose_name_plural = 'کاربران'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=['student', 'teacher', 'supervisor', 'admin']),
                name='valid_user_role_constraint'
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=['active', 'pending', 'suspended']),
                name='valid_user_status_constraint'
            ),
        ]

    def __str__(self):
        ident = self.academy_username or self.phone
        return f"{self.full_name} ({ident} - {self.get_role_display()})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def requires_mandatory_staff_2fa(self) -> bool:
        return self.role in [self.Role.TEACHER, self.Role.SUPERVISOR, self.Role.ADMIN]

    @property
    def has_active_totp(self) -> bool:
        return hasattr(self, 'authenticator') and self.authenticator.is_active

    def get_dashboard_url_name(self):
        role_map = {
            self.Role.STUDENT: 'dashboards:student',
            self.Role.TEACHER: 'dashboards:teacher',
            self.Role.SUPERVISOR: 'dashboards:supervisor',
            self.Role.ADMIN: 'dashboards:admin',
        }
        return role_map.get(self.role, 'dashboards:student')


class IdentitySequence(models.Model):
    year_prefix = models.PositiveSmallIntegerField('پیش‌وند سال (مثال: 26)', unique=True)
    last_value = models.PositiveIntegerField('آخرین شماره صادرشده', default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'شمارنده نام کاربری آکادمی'
        verbose_name_plural = 'شمارنده‌های نام کاربری آکادمی'


class StudentProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_profile',
        verbose_name='کاربر زبان‌آموز'
    )
    avatar_url = models.CharField('تصویر پروفایل (URL)', max_length=300, blank=True, default='')
    bio = models.TextField('درباره زبان‌آموز / هدف یادگیری', blank=True, default='')
    birth_date = models.DateField('تاریخ تولد', null=True, blank=True)
    emergency_phone = models.CharField('شماره تماس اضطراری', max_length=15, blank=True, default='')
    current_level = models.CharField('سطح فعلی زبان', max_length=40, default='تعیین سطح نشده')
    is_enrolled = models.BooleanField('وضعیت ثبت‌نام در دوره', default=False)
    is_paid = models.BooleanField('وضعیت تسویه شهریه', default=False)
    notes = models.TextField('یادداشت پرونده آموزشی', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل زبان‌آموز'
        verbose_name_plural = 'پروفایل‌های زبان‌آموزان'

    def __str__(self):
        return f"پرونده آموزشی: {self.user.full_name} ({self.user.academy_username or 'بدون کد'})"


class Authenticator(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='authenticator',
        verbose_name='کاربر'
    )
    encrypted_secret = models.TextField('کلید مخفی رمزنگاری‌شده')
    is_active = models.BooleanField('فعال‌سازی نهایی شده', default=False)
    verified_at = models.DateTimeField('تاریخ فعال‌سازی', null=True, blank=True)
    last_used_at = models.DateTimeField('آخرین استفاده', null=True, blank=True)
    last_used_counter = models.BigIntegerField('آخرین پنجره زمانی مصرف‌شده (ضد Replay)', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'احراز هویت TOTP'
        verbose_name_plural = 'احراز هویت‌های TOTP'


class OTPChallenge(models.Model):
    class Purpose(models.TextChoices):
        LOGIN_2FA = 'login_2fa', 'ورود دومرحله‌ای'
        PHONE_VERIFY = 'phone_verify', 'تأیید مالکیت شماره موبایل'
        PASSWORD_RESET = 'password_reset', 'بازیابی رمز عبور'
        SENSITIVE_ACTION = 'sensitive_action', 'عملیات حساس امنیتی'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='otp_challenges',
        verbose_name='کاربر'
    )
    destination_phone = models.CharField('شماره مقصد', max_length=15, db_index=True)
    purpose = models.CharField('هدف کد', max_length=30, choices=Purpose.choices, default=Purpose.LOGIN_2FA)
    code_hash = models.CharField('هش کد OTP', max_length=255)
    attempts_count = models.PositiveSmallIntegerField('تعداد تلاش‌های انجام‌شده', default=0)
    max_attempts = models.PositiveSmallIntegerField('حداکثر تلاش مجاز', default=5)
    ip_address = models.GenericIPAddressField('آدرس IP درخواست‌کننده', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField('زمان انقضا', db_index=True)
    consumed_at = models.DateTimeField('زمان مصرف شدن', null=True, blank=True)
    invalidated_at = models.DateTimeField('زمان ابطال', null=True, blank=True)

    class Meta:
        verbose_name = 'چالش OTP پیامکی'
        verbose_name_plural = 'چالش‌های OTP پیامکی'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'purpose', 'created_at']),
            models.Index(fields=['destination_phone', 'created_at']),
        ]

    @property
    def is_usable(self) -> bool:
        now = timezone.now()
        return (
            self.consumed_at is None
            and self.invalidated_at is None
            and self.attempts_count < self.max_attempts
            and now <= self.expires_at
        )

    def set_code(self, raw_code: str):
        self.code_hash = make_password(raw_code)

    def verify_code(self, raw_code: str) -> bool:
        return check_password(raw_code, self.code_hash)


class RecoveryCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recovery_codes'
    )
    code_prefix = models.CharField('پیش‌وند نمایشی', max_length=8)
    code_hash = models.CharField('هش کد بازیابی', max_length=255)
    used_at = models.DateTimeField('تاریخ مصرف', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'کد بازیابی 2FA'
        verbose_name_plural = 'کدهای بازیابی 2FA'
        indexes = [
            models.Index(fields=['user', 'used_at']),
        ]


class TrustedDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trusted_devices'
    )
    token_hash = models.CharField('هش توکن دستگاه', max_length=64, unique=True, db_index=True)
    device_name = models.CharField('نام مرورگر / دستگاه', max_length=180)
    ip_address = models.GenericIPAddressField('آدرس IP', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField('تاریخ انقضا (۳۰ روز)', db_index=True)
    revoked_at = models.DateTimeField('تاریخ لغو اعتبار', null=True, blank=True)

    class Meta:
        verbose_name = 'دستگاه مورد اعتماد'
        verbose_name_plural = 'دستگاه‌های مورد اعتماد'
        ordering = ['-last_used_at']

    @staticmethod
    def hash_raw_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @property
    def is_valid(self) -> bool:
        return (
            self.revoked_at is None
            and self.user.role == User.Role.STUDENT
            and timezone.now() <= self.expires_at
        )


class UserSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tracked_sessions'
    )
    session_key_hash = models.CharField('هش کلید نشست', max_length=64, unique=True, db_index=True)
    ip_address = models.GenericIPAddressField('آدرس IP', null=True, blank=True)
    user_agent = models.CharField('مرورگر و سیستم‌عامل', max_length=255, blank=True)
    is_2fa_verified = models.BooleanField('تأیید دومرحله‌ای انجام شده', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField('زمان انقضا')
    revoked_at = models.DateTimeField('زمان ابطال نشست', null=True, blank=True)

    class Meta:
        verbose_name = 'نشست فعال کاربر'
        verbose_name_plural = 'نشست‌های فعال کاربران'
        ordering = ['-last_seen_at']

    @staticmethod
    def hash_session_key(session_key: str) -> str:
        return hashlib.sha256(session_key.encode('utf-8')).hexdigest()


class SecurityEvent(models.Model):
    class Severity(models.TextChoices):
        INFO = 'info', 'اطلاع‌رسانی'
        WARNING = 'warning', 'هشدار امنیتی'
        CRITICAL = 'critical', 'حساس / بحرانی'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_events'
    )
    event_type = models.CharField('نوع رویداد', max_length=60, db_index=True)
    severity = models.CharField('سطح اهمیت', max_length=15, choices=Severity.choices, default=Severity.INFO)
    ip_address = models.GenericIPAddressField('آدرس IP', null=True, blank=True)
    user_agent = models.CharField('مرورگر', max_length=255, blank=True)
    description = models.CharField('شرح امن رویداد', max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'رویداد امنیتی'
        verbose_name_plural = 'رویدادهای امنیتی'
        ordering = ['-created_at']