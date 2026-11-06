import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify


class CourseCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('عنوان دسته‌بندی', max_length=100, unique=True)
    slug = models.SlugField('شناسه یکتا', max_length=120, unique=True, allow_unicode=True)
    description = models.TextField('توضیحات', blank=True)
    icon = models.CharField('آیکون Lucide', max_length=50, default='book-open')
    is_active = models.BooleanField('فعال', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'دسته‌بندی دوره'
        verbose_name_plural = 'دسته‌بندی‌های دوره'
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class Classroom(models.Model):
    class RoomType(models.TextChoices):
        PHYSICAL = 'physical', 'کلاس فیزیکی (حضوری)'
        ONLINE = 'online', 'اتاق مجازی (آنلاین)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('نام کلاس / اتاق', max_length=100, unique=True)
    room_type = models.CharField('نوع فضا', max_length=20, choices=RoomType.choices, default=RoomType.PHYSICAL)
    capacity = models.PositiveIntegerField('ظرفیت استاندارد', default=15)
    location_or_link = models.CharField('موقعیت یا لینک پایه', max_length=255, blank=True)
    is_active = models.BooleanField('فعال', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'فضای آموزشی (کلاس)'
        verbose_name_plural = 'فضاهای آموزشی (کلاس‌ها)'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_room_type_display()})"


class CourseQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_deleted=False)

    def published(self):
        return self.filter(
            is_deleted=False,
            publication_status=Course.PublicationStatus.PUBLISHED
        )


class Course(models.Model):
    class AgeGroup(models.TextChoices):
        KIDS = 'kids', 'کودکان (Children)'
        TEENS = 'teens', 'نوجوانان (Teenagers)'
        ADULTS = 'adults', 'بزرگسالان (Adults)'
        ALL = 'all', 'تمامی رده‌های سنی'

    class LanguageLevel(models.TextChoices):
        BEGINNER = 'beginner', 'Beginner (مبتدی)'
        ELEMENTARY = 'elementary', 'Elementary (مقدماتی)'
        PRE_INTERMEDIATE = 'pre_intermediate', 'Pre-Intermediate (پیش‌متوسط)'
        INTERMEDIATE = 'intermediate', 'Intermediate (متوسط)'
        UPPER_INTERMEDIATE = 'upper_intermediate', 'Upper-Intermediate (فرامتوسط)'
        ADVANCED = 'advanced', 'Advanced (پیشرفته)'

    class CourseType(models.TextChoices):
        GROUP = 'group', 'گروهی'
        PRIVATE = 'private', 'خصوصی'

    class CourseFormat(models.TextChoices):
        ONLINE = 'online', 'آنلاین'
        IN_PERSON = 'in_person', 'حضوری'
        HYBRID = 'hybrid', 'ترکیبی (حضوری و آنلاین)'

    class EnrollmentStatus(models.TextChoices):
        OPEN = 'open', 'ثبت‌نام باز'
        CLOSED = 'closed', 'ثبت‌نام بسته'
        FULL = 'full', 'تکمیل ظرفیت'

    class PublicationStatus(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PUBLISHED = 'published', 'منتشر شده'
        ARCHIVED = 'archived', 'آرشیو شده'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField('عنوان دوره', max_length=180, db_index=True)
    slug = models.SlugField('شناسه آدرس', max_length=200, unique=True, allow_unicode=True)
    description = models.TextField('توضیحات کامل دوره')
    cover_image = models.CharField(
        'آدرس تصویر کاور (اختیاری)',
        max_length=300,
        blank=True,
        help_text='آدرس تصویر یا خالی بگذارید تا از طرح گرافیکی استاندارد ترنج استفاده شود.'
    )
    category = models.ForeignKey(
        CourseCategory,
        on_delete=models.PROTECT,
        related_name='courses',
        verbose_name='دسته‌بندی'
    )
    age_group = models.CharField('رده سنی', max_length=20, choices=AgeGroup.choices, default=AgeGroup.ADULTS)
    language_level = models.CharField('سطح زبان', max_length=30, choices=LanguageLevel.choices, default=LanguageLevel.INTERMEDIATE)
    learning_objectives = models.TextField('اهداف آموزشی دوره', help_text='اهداف یادگیری را وارد کنید.')

    course_type = models.CharField('نوع دوره', max_length=20, choices=CourseType.choices, default=CourseType.GROUP)
    course_format = models.CharField('شیوه برگزاری', max_length=20, choices=CourseFormat.choices, default=CourseFormat.IN_PERSON)

    tuition_fee = models.PositiveBigIntegerField('شهریه دوره (تومان)', default=0)
    duration_weeks = models.PositiveIntegerField('طول دوره (هفته)', default=8)
    sessions_count = models.PositiveIntegerField('تعداد جلسات', default=16)
    max_capacity = models.PositiveIntegerField('حداکثر ظرفیت استاندارد', default=15)
    min_capacity = models.PositiveIntegerField('حداقل ظرفیت تشکیل', default=5)

    enrollment_status = models.CharField(
        'وضعیت ثبت‌نام',
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.OPEN,
        db_index=True
    )
    publication_status = models.CharField(
        'وضعیت انتشار',
        max_length=20,
        choices=PublicationStatus.choices,
        default=PublicationStatus.DRAFT,
        db_index=True
    )

    # فیلدهای حذف نرم (Soft Delete) جهت جلوگیری از پاک شدن سوابق آموزشی
    is_deleted = models.BooleanField('حذف نرم', default=False, db_index=True)
    deleted_at = models.DateTimeField('تاریخ حذف', null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_courses'
    )
    created_at = models.DateTimeField('تاریخ ایجاد', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)

    objects = CourseQuerySet.as_manager()

    class Meta:
        verbose_name = 'دوره آموزشی'
        verbose_name_plural = 'دوره‌های آموزشی'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_capacity__gte=models.F('min_capacity')),
                name='course_max_gte_min_capacity'
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_language_level_display()})"

    def clean(self):
        if self.max_capacity < self.min_capacity:
            raise ValidationError({'max_capacity': 'حداکثر ظرفیت نمی‌تواند کمتر از حداقل ظرفیت باشد.'})
        if self.sessions_count < 1:
            raise ValidationError({'sessions_count': 'تعداد جلسات باید حداقل ۱ جلسه باشد.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title, allow_unicode=True) or 'course'
            self.slug = f"{base_slug}-{str(self.id)[:6]}"
        super().save(*args, **kwargs)

    @property
    def is_enrollable(self):
        return (
            not self.is_deleted
            and self.publication_status == self.PublicationStatus.PUBLISHED
            and self.enrollment_status == self.EnrollmentStatus.OPEN
        )


class ClassGroup(models.Model):
    class ClassFormat(models.TextChoices):
        ONLINE = 'online', 'آنلاین'
        IN_PERSON = 'in_person', 'حضوری'

    class EnrollmentStatus(models.TextChoices):
        OPEN = 'open', 'باز برای ثبت‌نام'
        CLOSED = 'closed', 'بسته شده'
        FULL = 'full', 'تکمیل ظرفیت'

    class ClassStatus(models.TextChoices):
        PLANNED = 'planned', 'برنامه‌ریزی شده'
        ACTIVE = 'active', 'در حال برگزاری'
        COMPLETED = 'completed', 'پایان یافته'
        CANCELLED = 'cancelled', 'لغو شده'

    DAY_CHOICES = [
        ('sat', 'شنبه'),
        ('sun', 'یکشنبه'),
        ('mon', 'دوشنبه'),
        ('tue', 'سه‌شنبه'),
        ('wed', 'چهارشنبه'),
        ('thu', 'پنجشنبه'),
        ('fri', 'جمعه'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField('نام گروه کلاسی', max_length=150, help_text='مثال: گروه الف - ترم پاییز')
    code = models.CharField('کد کلاس', max_length=40, unique=True, db_index=True)
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name='classes',
        verbose_name='دوره مربوطه'
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_classes',
        limit_choices_to={'role': 'teacher'},
        verbose_name='استاد تخصیص‌یافته'
    )
    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scheduled_classes',
        verbose_name='کلاس فیزیکی / اتاق'
    )

    start_date = models.DateField('تاریخ شروع')
    end_date = models.DateField('تاریخ پایان')
    days_of_week = models.CharField(
        'روزهای برگزاری در هفته',
        max_length=60,
        help_text='کد روزها جداشده با ویرگول؛ مثال: sat,mon'
    )
    start_time = models.TimeField('ساعت شروع')
    end_time = models.TimeField('ساعت پایان')
    timezone_name = models.CharField('منطقه زمانی', max_length=50, default='Asia/Tehran')

    max_capacity = models.PositiveIntegerField('حداکثر ظرفیت کلاس', default=15)
    enrollment_status = models.CharField(
        'وضعیت ثبت‌نام کلاس',
        max_length=20,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.OPEN
    )
    class_format = models.CharField('شیوه برگزاری', max_length=20, choices=ClassFormat.choices, default=ClassFormat.IN_PERSON)
    location_or_link = models.CharField('محل تشکیل یا لینک کلاس آنلاین', max_length=255)
    status = models.CharField(
        'وضعیت اجرایی کلاس',
        max_length=20,
        choices=ClassStatus.choices,
        default=ClassStatus.PLANNED,
        db_index=True
    )

    is_archived = models.BooleanField('آرشیو شده', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'گروه کلاسی'
        verbose_name_plural = 'گروه‌های کلاسی'
        ordering = ['start_date', 'start_time']

    def __str__(self):
        return f"{self.course.title} — {self.name} ({self.code})"

    @property
    def days_list(self):
        return [d.strip().lower() for d in self.days_of_week.split(',') if d.strip()]

    @property
    def days_display(self):
        day_map = dict(self.DAY_CHOICES)
        return '، '.join([day_map.get(d, d) for d in self.days_list])

    @property
    def schedule_summary(self):
        return f"{self.days_display} • {self.start_time.strftime('%H:%M')} تا {self.end_time.strftime('%H:%M')}"

    @property
    def approved_enrollments_count(self):
        return self.enrollments.filter(status='approved').count()

    @property
    def remaining_capacity(self):
        return max(0, self.max_capacity - self.approved_enrollments_count)

    def refresh_capacity_status(self):
        """بروزرسانی خودکار وضعیت تکمیل ظرفیت بر اساس تعداد ثبت‌نام‌های تاییدشده"""
        if self.approved_enrollments_count >= self.max_capacity:
            if self.enrollment_status != self.EnrollmentStatus.FULL:
                self.enrollment_status = self.EnrollmentStatus.FULL
                self.save(update_fields=['enrollment_status', 'updated_at'])
        elif self.enrollment_status == self.EnrollmentStatus.FULL:
            self.enrollment_status = self.EnrollmentStatus.OPEN
            self.save(update_fields=['enrollment_status', 'updated_at'])

    def clean(self):
        from .services import check_teacher_schedule_conflict, check_classroom_schedule_conflict

        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'تاریخ پایان کلاس نمی‌تواند قبل از تاریخ شروع باشد.'})

        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'ساعت پایان کلاس باید بعد از ساعت شروع باشد.'})

        if not self.days_list:
            raise ValidationError({'days_of_week': 'حداقل یک روز هفته باید برای برگزاری کلاس انتخاب شود.'})

        if self.teacher and self.teacher.role != 'teacher':
            raise ValidationError({'teacher': 'کاربر انتخاب‌شده باید دارای نقش «استاد» باشد.'})

        # بررسی تداخل زمانی استاد در سمت سرور
        if self.teacher and self.status in [self.ClassStatus.PLANNED, self.ClassStatus.ACTIVE]:
            conflict = check_teacher_schedule_conflict(
                teacher=self.teacher,
                start_date=self.start_date,
                end_date=self.end_date,
                days_list=self.days_list,
                start_time=self.start_time,
                end_time=self.end_time,
                exclude_class_id=self.id
            )
            if conflict:
                raise ValidationError(
                    f"تداخل زمانی استاد: استاد «{self.teacher.full_name}» در این زمان در کلاس «{conflict.name} ({conflict.code})» برنامه فعال دارد."
                )

        # بررسی تداخل زمانی اتاق فیزیکی در سمت سرور
        if (
            self.classroom
            and self.classroom.room_type == Classroom.RoomType.PHYSICAL
            and self.status in [self.ClassStatus.PLANNED, self.ClassStatus.ACTIVE]
        ):
            room_conflict = check_classroom_schedule_conflict(
                classroom=self.classroom,
                start_date=self.start_date,
                end_date=self.end_date,
                days_list=self.days_list,
                start_time=self.start_time,
                end_time=self.end_time,
                exclude_class_id=self.id
            )
            if room_conflict:
                raise ValidationError(
                    f"تداخل کلاس فیزیکی: اتاق «{self.classroom.name}» در این ساعت برای کلاس «{room_conflict.name}» رزرو شده است."
                )


class ClassSession(models.Model):
    class SessionStatus(models.TextChoices):
        SCHEDULED = 'scheduled', 'برنامه‌ریزی شده'
        HELD = 'held', 'برگزار شده'
        CANCELLED = 'cancelled', 'لغو شده'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name='sessions')
    session_number = models.PositiveIntegerField('شماره جلسه')
    session_date = models.DateField('تاریخ جلسه')
    start_time = models.TimeField('ساعت شروع')
    end_time = models.TimeField('ساعت پایان')
    topic = models.CharField('موضوع جلسه', max_length=200, blank=True)
    status = models.CharField('وضعیت', max_length=20, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED)

    class Meta:
        verbose_name = 'جلسه کلاسی'
        verbose_name_plural = 'جلسات کلاسی'
        ordering = ['session_date', 'start_time']
        unique_together = ('class_group', 'session_number')


class TeacherAssignment(models.Model):
    """ثبت تاریخچه تخصیص و تغییر اساتید هر کلاس"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, related_name='teacher_assignments')
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teaching_history')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='assigned_teachers_log'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.CharField('توضیحات تخصیص', max_length=255, blank=True)

    class Meta:
        verbose_name = 'سابقه تخصیص استاد'
        verbose_name_plural = 'سوابق تخصیص اساتید'
        ordering = ['-assigned_at']


class Enrollment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید'
        APPROVED = 'approved', 'تأیید شده (عضو کلاس)'
        REJECTED = 'rejected', 'رد شده'
        CANCELLED = 'cancelled', 'لغو شده'
        COMPLETED = 'completed', 'پایان دوره'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'پرداخت نشده'
        PARTIALLY_PAID = 'partially_paid', 'پرداخت اقساطی / ناقص'
        PAID = 'paid', 'تسویه شده'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='enrollments',
        limit_choices_to={'role': 'student'},
        verbose_name='زبان‌آموز'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name='enrollments',
        verbose_name='دوره'
    )
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.PROTECT,
        related_name='enrollments',
        verbose_name='گروه کلاسی'
    )
    status = models.CharField(
        'وضعیت ثبت‌نام',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    # قانون فاز ۴: تایید ثبت‌نام به هیچ وجه وضعیت پرداخت را خودکار Paid نمی‌کند
    payment_status = models.CharField(
        'وضعیت مالی شهریه',
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        db_index=True
    )

    requested_at = models.DateTimeField('تاریخ ثبت درخواست', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین تغییر', auto_now=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_enrollments',
        verbose_name='بررسی‌کننده'
    )
    reviewed_at = models.DateTimeField('تاریخ بررسی', null=True, blank=True)
    decision_note = models.TextField('یادداشت بررسی / علت رد یا انتقال', blank=True)
    enrolled_by_admin = models.BooleanField('ثبت دستی توسط مدیر', default=False)

    class Meta:
        verbose_name = 'ثبت‌نام زبان‌آموز'
        verbose_name_plural = 'ثبت‌نام‌های زبان‌آموزان'
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['class_group', 'status']),
        ]

    def __str__(self):
        return f"{self.student.full_name} -> {self.class_group.name} ({self.get_status_display()})"