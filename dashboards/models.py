import secrets
import string
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class AttendancePolicy(models.Model):
    """
    تنظیمات قوانین حضور و غیاب (سطح کل آموزشگاه یا اختصاصی هر دوره).
    اولویت: تنظیمات جلسه (Session) > تنظیمات دوره (Course) > تنظیمات پیش‌فرض آموزشگاه (Academy Default).
    """
    REJECTION_POLICY_CHOICES = [
        ('REJECTED', 'ثبت به عنوان درخواست ردشده (REJECTED)'),
        ('ABSENT', 'تبدیل خودکار به غیبت رسمی (ABSENT)'),
    ]
    UNRESOLVED_POLICY_CHOICES = [
        ('ABSENT', 'ثبت غیبت خودکار و ارسال هشدار به مدیریت'),
        ('KEEP_PENDING_ALERT', 'نگهداری برای بررسی مدیر و ارسال هشدار فوری'),
    ]

    title = models.CharField(max_length=120, default='سیاست پیش‌فرض آموزشگاه تُرَنج')
    is_academy_default = models.BooleanField(default=False, db_index=True)
    course_id = models.PositiveIntegerField(null=True, blank=True, db_index=True, help_text='شناسه دوره در صورت اختصاصی بودن قانون')

    # تنظیمات زمان‌بندی (بر حسب دقیقه)
    open_before_minutes = models.PositiveIntegerField(default=15, help_text='باز شدن پنجره ثبت حضور (دقیقه قبل از شروع)')
    close_after_minutes = models.PositiveIntegerField(default=45, help_text='بسته شدن پنجره درخواست زبان‌آموز (دقیقه پس از شروع)')
    late_threshold_minutes = models.PositiveIntegerField(default=15, help_text='آستانه ثبت تأخیر (دقیقه پس از شروع کلاس)')
    teacher_approval_deadline_hours = models.PositiveIntegerField(default=24, help_text='مهلت تایید نهایی استاد (ساعت پس از شروع جلسه)')

    # قوانین کلاس‌های حضوری و آنلاین
    allow_late_requests = models.BooleanField(default=True)
    require_online_code = models.BooleanField(default=True, help_text='الزام کد امنیتی جلسه در کلاس‌های آنلاین')
    online_code_expiry_minutes = models.PositiveIntegerField(default=30)
    physical_allow_student_request = models.BooleanField(default=True)
    online_allow_student_request = models.BooleanField(default=True)

    # سیاست‌های نهایی‌سازی و ویرایش
    rejection_policy = models.CharField(max_length=20, choices=REJECTION_POLICY_CHOICES, default='ABSENT')
    auto_finalize_unsubmitted_to_absent = models.BooleanField(default=True)
    unresolved_pending_policy = models.CharField(max_length=25, choices=UNRESOLVED_POLICY_CHOICES, default='ABSENT')
    allow_teacher_edit_after_approval = models.BooleanField(default=False)
    require_admin_approval_for_post_edit = models.BooleanField(default=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_attendance_policies'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'سیاست حضور و غیاب'
        verbose_name_plural = 'سیاست‌های حضور و غیاب'
        ordering = ['-is_academy_default', '-id']

    def __str__(self):
        scope = 'پیش‌فرض کل آموزشگاه' if self.is_academy_default else f'اختصاصی دوره #{self.course_id}'
        return f"{self.title} ({scope})"

    @classmethod
    def get_effective_policy(cls, course_id=None):
        if course_id:
            course_policy = cls.objects.filter(course_id=course_id).first()
            if course_policy:
                return course_policy
        default_policy = cls.objects.filter(is_academy_default=True).first()
        if not default_policy:
            default_policy = cls.objects.create(
                title='سیاست استاندارد حضور و غیاب آموزشگاه زبان تُرَنج',
                is_academy_default=True,
            )
        return default_policy


class AttendanceSession(models.Model):
    """جلسه حضور و غیاب (پشتیبانی از کلاس‌های حضوری و آنلاین به همراه قوانین اختصاصی جلسه)"""
    MODE_CHOICES = [
        ('PHYSICAL', 'کلاس حضوری (Physical)'),
        ('ONLINE', 'کلاس آنلاین (Online)'),
    ]
    SESSION_STATUS_CHOICES = [
        ('SCHEDULED', 'برنامه‌ریزی‌شده (NOT_OPEN)'),
        ('OPEN', 'پنجره ثبت درخواست باز (OPEN)'),
        ('CLOSED', 'پنجره درخواست بسته — منتظر تایید استاد'),
        ('FINALIZED', 'نهایی‌شده (FINALIZED)'),
        ('CANCELLED', 'لغوشده (CANCELLED)'),
    ]

    course_id = models.PositiveIntegerField(db_index=True)
    course_title = models.CharField(max_length=200)
    department = models.CharField(max_length=80, default='عمومی', db_index=True)
    term = models.CharField(max_length=80, default='ترم جاری', db_index=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teaching_attendance_sessions'
    )

    title = models.CharField(max_length=150, default='جلسه آموزشی')
    mode = models.CharField(max_length=15, choices=MODE_CHOICES, default='PHYSICAL', db_index=True)
    session_date = models.DateField(default=timezone.localdate, db_index=True)
    start_time = models.DateTimeField(default=timezone.now, db_index=True)
    end_time = models.DateTimeField(null=True, blank=True)

    # بازنویسی تنظیمات در سطح جلسه (Session-Level Precedence Overrides)
    window_opens_at = models.DateTimeField(null=True, blank=True)
    window_closes_at = models.DateTimeField(null=True, blank=True)
    teacher_approval_deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    require_code_override = models.BooleanField(null=True, blank=True)
    allow_late_override = models.BooleanField(null=True, blank=True)

    # کد امنیتی منقضی‌شونده برای جلسات آنلاین
    attendance_code = models.CharField(max_length=12, blank=True, default='')
    code_expires_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=SESSION_STATUS_CHOICES, default='SCHEDULED', db_index=True)
    is_finalized = models.BooleanField(default=False, db_index=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'جلسه حضور و غیاب'
        verbose_name_plural = 'جلسات حضور و غیاب'
        ordering = ['-start_time', '-id']
        indexes = [
            models.Index(fields=['course_id', 'session_date']),
            models.Index(fields=['teacher', 'status']),
        ]

    def __str__(self):
        return f"{self.course_title} — {self.title} ({self.session_date})"

    def get_policy(self):
        return AttendancePolicy.get_effective_policy(self.course_id)

    def save(self, *args, **kwargs):
        policy = self.get_policy()
        if not self.end_time:
            self.end_time = self.start_time + timedelta(minutes=90)
        if not self.window_opens_at:
            self.window_opens_at = self.start_time - timedelta(minutes=policy.open_before_minutes)
        if not self.window_closes_at:
            self.window_closes_at = self.start_time + timedelta(minutes=policy.close_after_minutes)
        if not self.teacher_approval_deadline:
            self.teacher_approval_deadline = self.start_time + timedelta(hours=policy.teacher_approval_deadline_hours)
        super().save(*args, **kwargs)

    @property
    def requires_attendance_code(self):
        if self.mode != 'ONLINE':
            return False
        if self.require_code_override is not None:
            return self.require_code_override
        return self.get_policy().require_online_code

    @property
    def allows_late_requests(self):
        if self.allow_late_override is not None:
            return self.allow_late_override
        return self.get_policy().allow_late_requests

    def generate_secure_code(self, expiry_minutes=None):
        """تولید کد امنیتی تصادفی با انقضای خودکار مخصوص همین جلسه"""
        policy = self.get_policy()
        minutes = expiry_minutes or policy.online_code_expiry_minutes or 30
        alphabet = string.ascii_uppercase + string.digits
        self.attendance_code = ''.join(secrets.choice(alphabet) for _ in range(6))
        self.code_expires_at = timezone.now() + timedelta(minutes=int(minutes))
        self.save(update_fields=['attendance_code', 'code_expires_at'])
        return self.attendance_code

    def is_request_window_open(self, now=None):
        now = now or timezone.now()
        if self.status == 'CANCELLED' or self.is_finalized:
            return False
        if self.status == 'OPEN':
            return now <= self.window_closes_at
        return self.window_opens_at <= now <= self.window_closes_at

    def get_computed_window_status(self, now=None):
        now = now or timezone.now()
        if self.status == 'CANCELLED':
            return 'CANCELLED'
        if self.is_finalized or self.status == 'FINALIZED':
            return 'FINALIZED'
        if now < self.window_opens_at and self.status != 'OPEN':
            return 'NOT_OPEN'
        if self.is_request_window_open(now):
            return 'OPEN'
        return 'CLOSED'


class AttendanceEntry(models.Model):
    """
    رکورد دومرحله‌ای حضور و غیاب هر زبان‌آموز در هر جلسه:
    مرحله ۱: ثبت درخواست توسط زبان‌آموز (PENDING)
    مرحله ۲: تایید یا رد نهایی توسط استاد یا مدیریت (PRESENT, LATE, REJECTED, ABSENT, EXCUSED, CANCELLED)
    """
    STATUS_CHOICES = [
        ('NOT_OPEN', 'پنجره باز نشده (NOT_OPEN)'),
        ('PENDING', 'در انتظار تایید استاد (PENDING_TEACHER_APPROVAL)'),
        ('PRESENT', 'حاضر — تاییدشده توسط استاد (PRESENT)'),
        ('LATE', 'حاضر با تأخیر (LATE)'),
        ('REJECTED', 'درخواست ردشده (REJECTED)'),
        ('ABSENT', 'غایب (ABSENT)'),
        ('EXCUSED', 'غیبت موجه (EXCUSED)'),
        ('CANCELLED', 'جلسه لغوشده (CANCELLED)'),
    ]
    METHOD_CHOICES = [
        ('STUDENT_PHYSICAL', 'درخواست زبان‌آموز (کلاس حضوری)'),
        ('STUDENT_ONLINE', 'درخواست زبان‌آموز (کلاس آنلاین)'),
        ('TEACHER_MANUAL', 'ثبت دستی توسط استاد'),
        ('ADMIN_OVERRIDE', 'ثبت / بازنویسی توسط مدیریت آموزشگاه'),
        ('SYSTEM_AUTO', 'نهایی‌سازی خودکار سیستم'),
    ]

    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='entries')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='two_stage_attendance_entries'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    attendance_method = models.CharField(max_length=25, choices=METHOD_CHOICES, default='STUDENT_PHYSICAL')

    # اطلاعات مرحله ۱ (درخواست زبان‌آموز)
    requested_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_code = models.CharField(max_length=15, blank=True, default='')
    is_late_request = models.BooleanField(default=False)
    student_note = models.CharField(max_length=300, blank=True, default='')

    # اطلاعات مرحله ۲ (بررسی و تصمیم نهایی استاد / مدیریت)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_attendance_entries'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default='')
    teacher_private_note = models.TextField(blank=True, default='', help_text='یادداشت خصوصی استاد یا آموزش')
    admin_override_reason = models.CharField(max_length=500, blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'رکورد حضور و غیاب دومرحله‌ای'
        verbose_name_plural = 'رکوردهای حضور و غیاب دومرحله‌ای'
        ordering = ['-requested_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['session', 'student'], name='unique_session_student_attendance')
        ]
        indexes = [
            models.Index(fields=['session', 'status']),
            models.Index(fields=['student', 'status']),
        ]

    def __str__(self):
        return f"{self.student} — {self.session.title} [{self.status}]"

    @property
    def status_label_fa(self):
        labels = {
            'NOT_OPEN': 'هنوز باز نشده',
            'PENDING': 'در انتظار تایید استاد',
            'PRESENT': 'حاضر (تایید نهایی)',
            'LATE': 'حاضر با تأخیر',
            'REJECTED': 'درخواست ردشده',
            'ABSENT': 'غایب',
            'EXCUSED': 'غیبت موجه',
            'CANCELLED': 'جلسه لغوشده',
        }
        return labels.get(self.status, self.status)


class AttendanceAuditLog(models.Model):
    """
    سجل ممیزی امنیتی و غیرقابل ویرایش (Immutable Audit Trail).
    هیچ رکوردی در این جدول پس از ایجاد قابل ویرایش یا حذف از رابط کاربری نیست.
    """
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name='audit_logs')
    entry = models.ForeignKey(AttendanceEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_attendance_audits'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='performed_attendance_audits'
    )
    actor_role = models.CharField(max_length=30, default='system')
    action = models.CharField(max_length=60, db_index=True)
    previous_status = models.CharField(max_length=30, blank=True, default='')
    new_status = models.CharField(max_length=30, blank=True, default='')
    reason = models.TextField(blank=True, default='')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'لاگ امنیتی حضور و غیاب'
        verbose_name_plural = 'لاگ‌های امنیتی حضور و غیاب'
        ordering = ['-created_at', '-id']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("رکوردهای ممیزی امنیتی (Audit Logs) غیرقابل تغییر و ویرایش هستند.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("حذف لاگ‌های ممیزی امنیتی مجاز نیست.")


class AttendanceNotification(models.Model):
    """اعلان‌های هدفمند حضور و غیاب برای زبان‌آموز، استاد و مدیریت"""
    AUDIENCE_CHOICES = [
        ('STUDENT', 'زبان‌آموز'),
        ('TEACHER', 'استاد'),
        ('ADMIN', 'مدیریت آموزشگاه'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name='attendance_notifications'
    )
    audience_role = models.CharField(max_length=15, choices=AUDIENCE_CHOICES, default='STUDENT', db_index=True)
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField(max_length=160)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']