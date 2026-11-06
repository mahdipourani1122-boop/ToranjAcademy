import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from courses.models import Course, ClassGroup, ClassSession, Enrollment


class TeacherProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_profile',
        limit_choices_to={'role': 'teacher'},
        verbose_name='استاد'
    )
    avatar_url = models.CharField('آدرس تصویر پروفایل', max_length=300, blank=True, default='')
    specialization = models.CharField('حوزه تخصصی تدریس', max_length=150, default='آموزش زبان انگلیسی')
    education_degree = models.CharField('مدرک تحصیلی و گواهینامه‌ها', max_length=200, blank=True, default='')
    experience_years = models.PositiveSmallIntegerField('سابقه تدریس (سال)', default=1)
    bio = models.TextField('بیوگرافی و متدولوژی تدریس', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"پروفایل استاد: {self.user.full_name}"


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'present', 'حاضر'
        ABSENT = 'absent', 'غایب'
        LATE = 'late', 'تأخیر'
        EXCUSED = 'excused', 'غیبت موجه'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='attendance_records')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        limit_choices_to={'role': 'student'}
    )
    status = models.CharField('وضعیت حضور', max_length=15, choices=Status.choices, default=Status.PRESENT, db_index=True)
    delay_minutes = models.PositiveSmallIntegerField('میزان تأخیر (دقیقه)', default=0)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recorded_attendances'
    )
    note = models.CharField('توضیحات جلسه', max_length=255, blank=True)
    recorded_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'student')


class AcademicAssessment(models.Model):
    class AssessmentType(models.TextChoices):
        ASSIGNMENT = 'assignment', 'تکلیف کلاسی (Assignment)'
        QUIZ = 'quiz', 'کوییز کلاسی (Quiz)'
        MIDTERM = 'midterm', 'آزمون میان‌ترم (Midterm)'
        FINAL = 'final', 'آزمون پایان‌ترم (Final Exam)'
        PLACEMENT = 'placement', 'تعیین سطح (Placement)'

    class SubmissionStatus(models.TextChoices):
        PENDING = 'pending', 'در انتظار تحویل'
        SUBMITTED = 'submitted', 'تحویل داده شده'
        GRADED = 'graded', 'نمره‌دهی شده'
        MISSED = 'missed', 'عدم تحویل / غیبت'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='academic_assessments',
        limit_choices_to={'role': 'student'}
    )
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name='academic_assessments')
    enrollment = models.ForeignKey(Enrollment, on_delete=models.SET_NULL, null=True, blank=True, related_name='assessments')
    semester_label = models.CharField('نیم‌سال آموزشی (ترم)', max_length=40, db_index=True)
    title = models.CharField('عنوان ارزیابی / تکلیف', max_length=180)
    assessment_type = models.CharField('نوع ارزیابی', max_length=20, choices=AssessmentType.choices, default=AssessmentType.ASSIGNMENT)
    submission_status = models.CharField('وضعیت تحویل', max_length=20, choices=SubmissionStatus.choices, default=SubmissionStatus.GRADED)
    score = models.DecimalField('نمره کسب‌شده', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    max_score = models.DecimalField('حداکثر نمره', max_digits=5, decimal_places=2, default=100, validators=[MinValueValidator(1)])
    weight = models.DecimalField('ضریب اهمیت', max_digits=4, decimal_places=2, default=1.0, validators=[MinValueValidator(0.1), MaxValueValidator(10.0)])
    due_date = models.DateField('تاریخ', default=timezone.now)
    evaluated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='evaluated_assessments')
    feedback = models.TextField('بازخورد استاد', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-due_date', '-created_at']

    def clean(self):
        if self.score is not None and self.max_score and self.score > self.max_score:
            raise ValidationError({'score': 'نمره کسب‌شده نمی‌تواند بیشتر از حداکثر نمره باشد.'})

    @property
    def normalized_score_100(self):
        if self.submission_status != self.SubmissionStatus.GRADED or self.score is None or not self.max_score:
            return None
        return round((float(self.score) / float(self.max_score)) * 100.0, 2)


class SkillAssessmentScore(models.Model):
    class Skill(models.TextChoices):
        SPEAKING = 'speaking', 'مکالمه (Speaking)'
        LISTENING = 'listening', 'مهارت شنیداری (Listening)'
        READING = 'reading', 'درک مطلب (Reading)'
        WRITING = 'writing', 'نگارش (Writing)'
        GRAMMAR = 'grammar', 'دستور زبان (Grammar)'
        VOCABULARY = 'vocabulary', 'دایره واژگان (Vocabulary)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(AcademicAssessment, on_delete=models.CASCADE, related_name='skill_scores')
    skill = models.CharField('مهارت زبانی', max_length=20, choices=Skill.choices, db_index=True)
    score = models.DecimalField('نمره مهارت (از ۱۰۰)', max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        unique_together = ('assessment', 'skill')


class TeacherStudentNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teacher_notes', limit_choices_to={'role': 'student'})
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='authored_student_notes')
    class_group = models.ForeignKey(ClassGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_notes')
    note_text = models.TextField('متن یادداشت تحلیلی استاد')
    recommendation = models.TextField('توصیه آموزشی', blank=True)
    is_private_to_staff = models.BooleanField('محرمانه (فقط کادر آموزشی)', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class HistoricalStudentAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='historical_student_grants', limit_choices_to={'role': 'teacher'})
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='historical_teacher_accesses', limit_choices_to={'role': 'student'})
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='issued_historical_grants')
    reason = models.CharField('علت اعطای دسترسی به سوابق', max_length=255)
    expires_at = models.DateTimeField('تاریخ انقضای مجوز', null=True, blank=True)
    is_active = models.BooleanField('فعال', default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('teacher', 'student')

    @property
    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True
