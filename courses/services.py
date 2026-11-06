from datetime import timedelta
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import CourseCategory, Course, ClassGroup, ClassSession, TeacherAssignment, Enrollment

WEEKDAY_MAP = {
    5: 'sat',  # Saturday
    6: 'sun',  # Sunday
    0: 'mon',  # Monday
    1: 'tue',  # Tuesday
    2: 'wed',  # Wednesday
    3: 'thu',  # Thursday
    4: 'fri',  # Friday
}


def ensure_default_categories():
    """ایجاد خودکار ۶ دسته‌بندی استاندارد آکادمی ترنج در صورت خالی بودن جدول"""
    defaults = [
        ('زبان انگلیسی کودکان', 'kids-english', 'smile'),
        ('زبان انگلیسی نوجوانان', 'teens-english', 'book-open'),
        ('زبان انگلیسی بزرگسالان', 'adults-english', 'graduation-cap'),
        ('مکالمه آزاد (Conversation)', 'conversation', 'message-square'),
        ('آمادگی آزمون IELTS', 'ielts-prep', 'file-check-2'),
        ('دوره‌های فشرده (Intensive)', 'intensive-english', 'zap'),
    ]
    for name, slug, icon in defaults:
        CourseCategory.objects.get_or_create(slug=slug, defaults={'name': name, 'icon': icon})


def schedules_overlap(start_date_a, end_date_a, days_a, start_time_a, end_time_a,
                      start_date_b, end_date_b, days_b, start_time_b, end_time_b) -> bool:
    """بررسی دقیق هم‌پوشانی بازه تاریخی، روزهای هفته و بازه ساعتی دو کلاس"""
    if not (start_date_a <= end_date_b and start_date_b <= end_date_a):
        return False
    common_days = set(days_a) & set(days_b)
    if not common_days:
        return False
    return (start_time_a < end_time_b) and (start_time_b < end_time_a)


def check_teacher_schedule_conflict(teacher, start_date, end_date, days_list, start_time, end_time, exclude_class_id=None):
    qs = ClassGroup.objects.filter(
        teacher=teacher,
        is_archived=False,
        status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]
    )
    if exclude_class_id:
        qs = qs.exclude(id=exclude_class_id)

    for other in qs:
        if schedules_overlap(
            start_date, end_date, days_list, start_time, end_time,
            other.start_date, other.end_date, other.days_list, other.start_time, other.end_time
        ):
            return other
    return None


def check_classroom_schedule_conflict(classroom, start_date, end_date, days_list, start_time, end_time, exclude_class_id=None):
    qs = ClassGroup.objects.filter(
        classroom=classroom,
        is_archived=False,
        status__in=[ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]
    )
    if exclude_class_id:
        qs = qs.exclude(id=exclude_class_id)

    for other in qs:
        if schedules_overlap(
            start_date, end_date, days_list, start_time, end_time,
            other.start_date, other.end_date, other.days_list, other.start_time, other.end_time
        ):
            return other
    return None


def check_student_schedule_conflict(student, target_class: ClassGroup, exclude_enrollment_id=None):
    """بررسی تداخل زمانی کلاس انتخابی با سایر کلاس‌های تاییدشده یا در انتظار زبان‌آموز"""
    active_enrollments = Enrollment.objects.filter(
        student=student,
        status__in=[Enrollment.Status.APPROVED, Enrollment.Status.PENDING]
    ).select_related('class_group')

    if exclude_enrollment_id:
        active_enrollments = active_enrollments.exclude(id=exclude_enrollment_id)

    for enrollment in active_enrollments:
        other = enrollment.class_group
        if other.status not in [ClassGroup.ClassStatus.PLANNED, ClassGroup.ClassStatus.ACTIVE]:
            continue
        if schedules_overlap(
            target_class.start_date, target_class.end_date, target_class.days_list,
            target_class.start_time, target_class.end_time,
            other.start_date, other.end_date, other.days_list,
            other.start_time, other.end_time
        ):
            return other
    return None


def generate_recurring_sessions_for_class(class_group: ClassGroup):
    """تولید خودکار جلسات هفتگی کلاس بین تاریخ شروع و پایان بر اساس روزهای انتخابی"""
    class_group.sessions.filter(status=ClassSession.SessionStatus.SCHEDULED).delete()
    current_date = class_group.start_date
    session_num = class_group.sessions.count() + 1
    max_sessions = class_group.course.sessions_count or 40
    target_days = set(class_group.days_list)

    sessions_to_create = []
    while current_date <= class_group.end_date and session_num <= max_sessions:
        day_code = WEEKDAY_MAP.get(current_date.weekday())
        if day_code in target_days:
            sessions_to_create.append(
                ClassSession(
                    class_group=class_group,
                    session_number=session_num,
                    session_date=current_date,
                    start_time=class_group.start_time,
                    end_time=class_group.end_time,
                    topic=f"جلسه {session_num} — {class_group.course.title}",
                )
            )
            session_num += 1
        current_date += timedelta(days=1)

    if sessions_to_create:
        ClassSession.objects.bulk_create(sessions_to_create)


@transaction.atomic
def assign_teacher_to_class(class_group: ClassGroup, teacher, assigned_by, notes=''):
    """تخصیص امن استاد به کلاس پس از بررسی تداخل زمانی و ثبت لاگ تاریخچه"""
    if teacher and teacher.role != 'teacher':
        raise ValidationError('فقط کاربران دارای نقش «استاد» قابل تخصیص به کلاس هستند.')

    if teacher:
        conflict = check_teacher_schedule_conflict(
            teacher=teacher,
            start_date=class_group.start_date,
            end_date=class_group.end_date,
            days_list=class_group.days_list,
            start_time=class_group.start_time,
            end_time=class_group.end_time,
            exclude_class_id=class_group.id
        )
        if conflict:
            raise ValidationError(
                f"تداخل برنامه استاد: «{teacher.full_name}» در همین ساعت کلاس «{conflict.name}» را دارد."
            )

    class_group.teacher = teacher
    class_group.save(update_fields=['teacher', 'updated_at'])

    TeacherAssignment.objects.filter(class_group=class_group, is_active=True).update(is_active=False)
    if teacher:
        TeacherAssignment.objects.create(
            class_group=class_group,
            teacher=teacher,
            assigned_by=assigned_by,
            is_active=True,
            notes=notes or 'تخصیص توسط مدیریت'
        )
    return class_group


@transaction.atomic
def submit_student_enrollment_request(student, class_group_id, by_admin=False, admin_user=None, auto_approve=False):
    """ثبت درخواست ثبت‌نام با بررسی کامل ظرفیت، وضعیت انتشار، عدم تکرار و عدم تداخل زمانی"""
    if student.role != 'student':
        raise ValidationError('فقط کاربران با نقش زبان‌آموز می‌توانند در کلاس ثبت‌نام شوند.')

    class_group = ClassGroup.objects.select_for_update().select_related('course').get(id=class_group_id)
    course = class_group.course

    if course.is_deleted or course.publication_status != Course.PublicationStatus.PUBLISHED:
        raise ValidationError('این دوره در حال حاضر منتشر نشده و امکان ثبت‌نام در آن وجود ندارد.')

    if course.enrollment_status != Course.EnrollmentStatus.OPEN and not by_admin:
        raise ValidationError('ثبت‌نام برای این دوره بسته شده است.')

    if class_group.is_archived or class_group.status in [ClassGroup.ClassStatus.CANCELLED, ClassGroup.ClassStatus.COMPLETED]:
        raise ValidationError('این گروه کلاسی فعال نیست.')

    if class_group.enrollment_status != ClassGroup.EnrollmentStatus.OPEN and not by_admin:
        raise ValidationError('ظرفیت این گروه کلاسی تکمیل شده یا ثبت‌نام آن بسته است.')

    # جلوگیری از ثبت‌نام تکراری فعال در همان کلاس
    if Enrollment.objects.filter(
        student=student,
        class_group=class_group,
        status__in=[Enrollment.Status.PENDING, Enrollment.Status.APPROVED]
    ).exists():
        raise ValidationError('شما قبلاً در این گروه کلاسی درخواست فعال یا ثبت‌نام تاییدشده دارید.')

    # بررسی ظرفیت کلاس
    if class_group.approved_enrollments_count >= class_group.max_capacity:
        class_group.refresh_capacity_status()
        raise ValidationError('ظرفیت این گروه کلاسی تکمیل شده است.')

    # بررسی تداخل زمانی زبان‌آموز
    conflict_class = check_student_schedule_conflict(student, class_group)
    if conflict_class:
        raise ValidationError(
            f"تداخل زمانی: برنامه این کلاس با کلاس «{conflict_class.name} ({conflict_class.schedule_summary})» شما تداخل دارد."
        )

    initial_status = Enrollment.Status.APPROVED if (by_admin and auto_approve) else Enrollment.Status.PENDING

    enrollment = Enrollment.objects.create(
        student=student,
        course=course,
        class_group=class_group,
        status=initial_status,
        payment_status=Enrollment.PaymentStatus.UNPAID,
        enrolled_by_admin=by_admin,
        reviewed_by=admin_user if (by_admin and auto_approve) else None,
        reviewed_at=timezone.now() if (by_admin and auto_approve) else None,
        decision_note='ثبت‌نام مستقیم توسط مدیر سامانه' if by_admin else ''
    )

    if initial_status == Enrollment.Status.APPROVED:
        class_group.refresh_capacity_status()

    return enrollment


@transaction.atomic
def review_enrollment_request(enrollment_id, reviewer, action: str, note: str = ''):
    """تایید یا رد درخواست ثبت‌نام توسط مدیر با قفل رکورد و ثبت کامل لاگ بررسی‌کننده"""
    enrollment = Enrollment.objects.select_for_update().select_related('class_group', 'student').get(id=enrollment_id)
    class_group = ClassGroup.objects.select_for_update().get(id=enrollment.class_group_id)

    if action == 'approve':
        if enrollment.status == Enrollment.Status.APPROVED:
            return enrollment

        if class_group.approved_enrollments_count >= class_group.max_capacity:
            class_group.refresh_capacity_status()
            raise ValidationError('ظرفیت این کلاس تکمیل شده و امکان تایید درخواست جدید وجود ندارد.')

        conflict_class = check_student_schedule_conflict(
            enrollment.student, class_group, exclude_enrollment_id=enrollment.id
        )
        if conflict_class:
            raise ValidationError(
                f"تداخل زمانی زبان‌آموز با کلاس «{conflict_class.name}». امکان تایید همزمان وجود ندارد."
            )

        enrollment.status = Enrollment.Status.APPROVED
        enrollment.reviewed_by = reviewer
        enrollment.reviewed_at = timezone.now()
        enrollment.decision_note = note or 'تأیید شده توسط مدیریت آموزش'
        # وضعیت مالی به صورت خودکار تغییر نمی‌کند (مطابق الزام فاز ۴)
        enrollment.save()
        class_group.refresh_capacity_status()

    elif action == 'reject':
        enrollment.status = Enrollment.Status.REJECTED
        enrollment.reviewed_by = reviewer
        enrollment.reviewed_at = timezone.now()
        enrollment.decision_note = note or 'عدم تایید توسط مدیریت آموزش'
        enrollment.save()
        class_group.refresh_capacity_status()

    elif action == 'cancel':
        enrollment.status = Enrollment.Status.CANCELLED
        enrollment.reviewed_by = reviewer
        enrollment.reviewed_at = timezone.now()
        enrollment.decision_note = note or 'لغو ثبت‌نام'
        enrollment.save()
        class_group.refresh_capacity_status()

    else:
        raise ValidationError('عملیات نامعتبر است.')

    return enrollment


@transaction.atomic
def transfer_student_enrollment(enrollment_id, new_class_group_id, admin_user, note=''):
    """انتقال امن زبان‌آموز از یک گروه کلاسی به گروه دیگر با حفظ تاریخچه"""
    old_enrollment = Enrollment.objects.select_for_update().select_related('class_group', 'student').get(id=enrollment_id)
    new_class = ClassGroup.objects.select_for_update().select_related('course').get(id=new_class_group_id)

    if new_class.approved_enrollments_count >= new_class.max_capacity:
        raise ValidationError('ظرفیت کلاس مقصد تکمیل است.')

    conflict = check_student_schedule_conflict(
        old_enrollment.student, new_class, exclude_enrollment_id=old_enrollment.id
    )
    if conflict:
        raise ValidationError(f"کلاس مقصد با کلاس «{conflict.name}» زبان‌آموز تداخل زمانی دارد.")

    old_class = old_enrollment.class_group
    old_enrollment.status = Enrollment.Status.CANCELLED
    old_enrollment.reviewed_by = admin_user
    old_enrollment.reviewed_at = timezone.now()
    old_enrollment.decision_note = f"انتقال به کلاس {new_class.code}. {note}".strip()
    old_enrollment.save()
    old_class.refresh_capacity_status()

    new_enrollment = Enrollment.objects.create(
        student=old_enrollment.student,
        course=new_class.course,
        class_group=new_class,
        status=Enrollment.Status.APPROVED,
        payment_status=old_enrollment.payment_status,
        enrolled_by_admin=True,
        reviewed_by=admin_user,
        reviewed_at=timezone.now(),
        decision_note=f"منتقل‌شده از کلاس {old_class.code}. {note}".strip()
    )
    new_class.refresh_capacity_status()
    return new_enrollment