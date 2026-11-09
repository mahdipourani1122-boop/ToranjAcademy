import logging
from datetime import timedelta
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AttendancePolicy,
    AttendanceSession,
    AttendanceEntry,
    AttendanceAuditLog,
    AttendanceNotification,
)

audit_logger = logging.getLogger('toranj.security')


def get_user_display(user):
    if not user:
        return 'نامشخص'
    if hasattr(user, 'get_full_name') and user.get_full_name().strip():
        return user.get_full_name().strip()
    full = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    return full or str(getattr(user, 'phone', getattr(user, 'username', user.pk)))


def is_admin_user(user):
    if not user or not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    return bool(user.is_superuser or user.is_staff or role in ('admin', 'manager', 'staff', 'مدیر'))


def is_teacher_user(user):
    if not user or not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    return bool(getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'))


def get_enrolled_student_users_for_course(course_id):
    """واکشی لیست کاربران زبان‌آموز مجاز در یک دوره مشخص از جداول واقعی دیتابیس"""
    User = get_user_model()
    student_ids = set()

    for app_label, model_name in [('courses', 'Enrollment'), ('academics', 'Enrollment'), ('academics', 'CourseEnrollment')]:
        try:
            EnrollmentModel = apps.get_model(app_label, model_name)
            for enr in EnrollmentModel.objects.filter(course_id=course_id):
                st = getattr(enr, 'student', getattr(enr, 'user', None))
                st_user = getattr(st, 'user', st)
                if st_user and hasattr(st_user, 'pk'):
                    student_ids.add(st_user.pk)
        except LookupError:
            continue
        except Exception:
            pass

    try:
        CourseModel = apps.get_model('courses', 'Course')
        course = CourseModel.objects.filter(pk=course_id).first()
        if course and hasattr(course, 'students'):
            for u in course.students.all():
                student_ids.add(u.pk)
    except Exception:
        pass

    return list(User.objects.filter(pk__in=student_ids))


def is_student_enrolled_in_course(user, course_id):
    """بررسی سمت سرور برای اطمینان از ثبت‌نام زبان‌آموز در دوره مربوط به جلسه"""
    enrolled_users = get_enrolled_student_users_for_course(course_id)
    if any(u.pk == user.pk for u in enrolled_users):
        return True
    # در صورتی که رکورد قبلی در همان جلسه توسط استاد برای زبان‌آموز باز شده باشد
    return AttendanceEntry.objects.filter(session__course_id=course_id, student=user).exists()


def _sync_legacy_attendance_model(entry):
    """همگام‌سازی خودکار با مدل حضور و غیاب قبلی پروژه برای حفظ یکپارچگی کامل"""
    for app_label, model_name in [('academics', 'Attendance'), ('courses', 'Attendance')]:
        try:
            LegacyModel = apps.get_model(app_label, model_name)
            f_names = [f.name for f in LegacyModel._meta.get_fields()]
            lookup = {}
            if 'course' in f_names:
                lookup['course_id'] = entry.session.course_id
            if 'student' in f_names:
                rel_m = LegacyModel._meta.get_field('student').related_model
                if rel_m == entry.student.__class__:
                    lookup['student'] = entry.student
            elif 'user' in f_names:
                lookup['user'] = entry.student
            if 'date' in f_names:
                lookup['date'] = entry.session.session_date
            if 'session_title' in f_names:
                lookup['session_title'] = entry.session.title

            if lookup and ('student' in lookup or 'user' in lookup):
                defaults = {}
                status_map = {
                    'PRESENT': 'present',
                    'LATE': 'late',
                    'EXCUSED': 'excused',
                    'ABSENT': 'absent',
                    'REJECTED': 'absent',
                }
                mapped_st = status_map.get(entry.status, 'absent')
                if 'status' in f_names:
                    defaults['status'] = mapped_st
                if 'is_present' in f_names:
                    defaults['is_present'] = (entry.status in ('PRESENT', 'LATE'))
                if 'note' in f_names:
                    defaults['note'] = entry.rejection_reason or entry.teacher_private_note
                LegacyModel.objects.update_or_create(defaults=defaults, **lookup)
                break
        except Exception:
            continue


def _notify(recipient, audience_role, session, title, message):
    AttendanceNotification.objects.create(
        recipient=recipient,
        audience_role=audience_role,
        session=session,
        title=title,
        message=message,
    )


@transaction.atomic
def submit_student_attendance_request(student_user, session_id, submitted_code='', student_note='', ip_address=None):
    """
    مرحله ۱ (STAGE 1): ثبت درخواست حضور توسط زبان‌آموز.
    وضعیت همواره PENDING می‌شود و زبان‌آموز هرگز نمی‌تواند حضور خود را مستقیماً PRESENT کند.
    """
    session = AttendanceSession.objects.select_for_update().get(pk=session_id)
    now = timezone.now()
    policy = session.get_policy()

    if not is_student_enrolled_in_course(student_user, session.course_id):
        raise PermissionDenied("شما در این دوره آموزشی ثبت‌نام نشده‌اید.")

    if session.status == 'CANCELLED':
        raise ValidationError("این جلسه آموزشی لغو شده است.")

    if session.is_finalized or session.status == 'FINALIZED':
        raise ValidationError("لیست حضور و غیاب این جلسه نهایی و بسته شده است.")

    if session.mode == 'PHYSICAL' and not policy.physical_allow_student_request:
        raise ValidationError("در کلاس‌های حضوری این دوره، حضور و غیاب مستقیماً توسط استاد ثبت می‌شود.")
    if session.mode == 'ONLINE' and not policy.online_allow_student_request:
        raise ValidationError("ثبت درخواست آنلاین برای این دوره غیرفعال است.")

    if now < session.window_opens_at and session.status != 'OPEN':
        raise ValidationError("پنجره زمانی ثبت حضور برای این جلسه هنوز باز نشده است.")

    if now > session.window_closes_at:
        raise ValidationError("مهلت زمانی ارسال درخواست حضور برای این جلسه به پایان رسیده است.")

    is_late = now > (session.start_time + timedelta(minutes=policy.late_threshold_minutes))
    if is_late and not session.allows_late_requests:
        raise ValidationError("با توجه به گذشت زمان مجاز، ارسال درخواست حضور با تأخیر در این کلاس مجاز نیست.")

    # بررسی کد امنیتی جلسه برای کلاس‌های آنلاین
    if session.requires_attendance_code:
        clean_code = (submitted_code or '').strip().upper()
        if not session.attendance_code:
            raise ValidationError("کد امنیتی جلسه هنوز توسط استاد فعال نشده است.")
        if session.code_expires_at and now > session.code_expires_at:
            raise ValidationError("کد امنیتی این جلسه منقضی شده است.")
        if clean_code != session.attendance_code.upper():
            raise ValidationError("کد حضور واردشده نامعتبر است.")

    existing = AttendanceEntry.objects.select_for_update().filter(session=session, student=student_user).first()
    if existing and existing.status in ('PENDING', 'PRESENT', 'LATE', 'EXCUSED'):
        raise ValidationError("درخواست حضور شما برای این جلسه قبلاً ثبت شده است.")

    prev_status = existing.status if existing else 'NONE'
    method = 'STUDENT_ONLINE' if session.mode == 'ONLINE' else 'STUDENT_PHYSICAL'

    entry, _ = AttendanceEntry.objects.update_or_create(
        session=session,
        student=student_user,
        defaults={
            'status': 'PENDING',
            'attendance_method': method,
            'requested_at': now,
            'submitted_code': (submitted_code or '').strip().upper()[:15],
            'is_late_request': is_late,
            'student_note': (student_note or '').strip()[:300],
        }
    )

    AttendanceAuditLog.objects.create(
        session=session,
        entry=entry,
        student=student_user,
        actor=student_user,
        actor_role='student',
        action='STUDENT_REQUEST_SUBMITTED',
        previous_status=prev_status,
        new_status='PENDING',
        reason='ثبت درخواست حضور مرحله اول توسط زبان‌آموز',
        ip_address=ip_address,
    )

    _notify(
        student_user, 'STUDENT', session,
        f"ثبت درخواست حضور — {session.title}",
        f"درخواست حضور شما برای درس «{session.course_title}» ثبت شد و در انتظار تایید استاد است."
    )
    _notify(
        session.teacher, 'TEACHER', session,
        f"درخواست حضور جدید: {get_user_display(student_user)}",
        f"زبان‌آموز {get_user_display(student_user)} برای جلسه «{session.title}» درخواست حضور ارسال کرد."
    )
    return entry


@transaction.atomic
def teacher_review_attendance(
    teacher_user, session_id, student_id, decision, reason='', private_note='', ip_address=None
):
    """
    مرحله ۲ (STAGE 2): بررسی، تایید نهایی، رد یا ثبت دستی حضور توسط استادِ مجاز جلسه.
    decision: 'PRESENT' | 'LATE' | 'REJECTED' | 'ABSENT' | 'EXCUSED'
    """
    session = AttendanceSession.objects.select_for_update().get(pk=session_id)
    if session.teacher_id != teacher_user.pk and not is_admin_user(teacher_user):
        raise PermissionDenied("خطای امنیتی: شما استاد اختصاصی این جلسه نیستید.")

    if not is_student_enrolled_in_course(
        get_user_model().objects.get(pk=student_id), session.course_id
    ):
        raise PermissionDenied("این زبان‌آموز در کلاس انتخابی ثبت‌نام نشده است.")

    policy = session.get_policy()
    now = timezone.now()

    if session.is_finalized and not is_admin_user(teacher_user):
        raise ValidationError("مهلت تایید استاد به پایان رسیده و جلسه نهایی شده است. برای تغییر با آموزش هماهنگ کنید.")

    User = get_user_model()
    student_user = User.objects.get(pk=student_id)
    entry = AttendanceEntry.objects.select_for_update().filter(session=session, student=student_user).first()

    if entry and entry.status in ('PRESENT', 'LATE') and not policy.allow_teacher_edit_after_approval and not is_admin_user(teacher_user):
        if policy.require_admin_approval_for_post_edit:
            raise ValidationError("طبق قوانین آموزشگاه، تغییر وضعیت حضور پس از تایید نهایی نیازمند مجوز مدیریت است.")

    decision = decision.upper().strip()
    if decision not in ('PRESENT', 'LATE', 'REJECTED', 'ABSENT', 'EXCUSED'):
        raise ValidationError("وضعیت انتخاب‌شده نامعتبر است.")

    if decision == 'REJECTED' and policy.rejection_policy == 'ABSENT':
        effective_status = 'ABSENT'
    else:
        effective_status = decision

    prev_status = entry.status if entry else 'NONE'
    is_manual = entry is None or entry.requested_at is None

    if entry is None:
        entry = AttendanceEntry(
            session=session,
            student=student_user,
            attendance_method='TEACHER_MANUAL',
            requested_at=now,
        )

    entry.status = effective_status
    if is_manual:
        entry.attendance_method = 'TEACHER_MANUAL'
    entry.reviewed_by = teacher_user
    entry.reviewed_at = now
    if reason:
        entry.rejection_reason = reason.strip()[:500]
    if private_note:
        entry.teacher_private_note = private_note.strip()[:1000]
    entry.save()

    _sync_legacy_attendance_model(entry)

    AttendanceAuditLog.objects.create(
        session=session,
        entry=entry,
        student=student_user,
        actor=teacher_user,
        actor_role='teacher',
        action='TEACHER_FINAL_DECISION' if not is_manual else 'TEACHER_MANUAL_RECORD',
        previous_status=prev_status,
        new_status=effective_status,
        reason=reason or private_note or f"تصمیم نهایی استاد: {effective_status}",
        ip_address=ip_address,
    )

    status_msg_map = {
        'PRESENT': 'حضور شما در جلسه توسط استاد تایید نهایی شد (حاضر).',
        'LATE': 'حضور شما با ثبت تأخیر توسط استاد تایید شد.',
        'REJECTED': f"درخواست حضور شما توسط استاد رد شد. {reason}",
        'ABSENT': f"وضعیت شما برای این جلسه «غایب» ثبت شد. {reason}",
        'EXCUSED': 'غیبت شما برای این جلسه «موجه» ثبت گردید.',
    }
    _notify(
        student_user, 'STUDENT', session,
        f"نتیجه حضور و غیاب — {session.title}",
        status_msg_map.get(effective_status, 'وضعیت حضور و غیاب شما بروزرسانی شد.')
    )
    return entry


@transaction.atomic
def admin_override_attendance(admin_user, session_id, student_id, new_status, mandatory_reason, ip_address=None):
    """
    بازنویسی وضعیت حضور و غیاب توسط مدیریت آموزشگاه همراه با دلیل اجباری و ثبت در لاگ تغییرناپذیر.
    """
    if not is_admin_user(admin_user):
        raise PermissionDenied("فقط مدیریت آموزشگاه مجاز به بازنویسی مدیریتی حضور و غیاب است.")

    clean_reason = (mandatory_reason or '').strip()
    if len(clean_reason) < 3:
        raise ValidationError("ثبت دلیل مدیریتی برای تغییر یا بازنویسی وضعیت حضور و غیاب الزامی است.")

    new_status = new_status.upper().strip()
    if new_status not in ('PRESENT', 'LATE', 'REJECTED', 'ABSENT', 'EXCUSED', 'PENDING', 'CANCELLED'):
        raise ValidationError("وضعیت انتخابی نامعتبر است.")

    session = AttendanceSession.objects.select_for_update().get(pk=session_id)
    User = get_user_model()
    student_user = User.objects.get(pk=student_id)

    entry = AttendanceEntry.objects.select_for_update().filter(session=session, student=student_user).first()
    prev_status = entry.status if entry else 'NONE'

    if entry is None:
        entry = AttendanceEntry(
            session=session,
            student=student_user,
            requested_at=timezone.now(),
        )

    entry.status = new_status
    entry.attendance_method = 'ADMIN_OVERRIDE'
    entry.reviewed_by = admin_user
    entry.reviewed_at = timezone.now()
    entry.admin_override_reason = clean_reason[:500]
    entry.save()

    _sync_legacy_attendance_model(entry)

    AttendanceAuditLog.objects.create(
        session=session,
        entry=entry,
        student=student_user,
        actor=admin_user,
        actor_role='admin',
        action='ADMIN_ATTENDANCE_OVERRIDE',
        previous_status=prev_status,
        new_status=new_status,
        reason=clean_reason,
        ip_address=ip_address,
    )

    _notify(
        student_user, 'STUDENT', session,
        f"بروزرسانی مدیریتی حضور و غیاب — {session.title}",
        f"وضعیت حضور شما در جلسه «{session.title}» توسط آموزش به «{entry.status_label_fa}» تغییر یافت. توضیح: {clean_reason}"
    )
    return entry


def finalize_expired_sessions(now=None):
    """
    فرآیند خودکار، ایمن و ضدتکرار (Idempotent) برای نهایی‌سازی جلساتی که مهلت تایید استاد آن‌ها گذشته است.
    - درخواست‌های PRESENT به قوت خود باقی می‌مانند.
    - زبان‌آموزانی که درخواست نفرستاده‌اند طبق سیاست آموزشگاه ABSENT می‌شوند.
    - درخواست‌های PENDING هرگز به صورت بلاتکلیف رها نمی‌شوند و به مدیریت گزارش می‌شوند.
    """
    now = now or timezone.now()
    expired_sessions = AttendanceSession.objects.filter(
        is_finalized=False,
        teacher_approval_deadline__lte=now,
    ).exclude(status='CANCELLED')

    finalized_count = 0
    for s_obj in expired_sessions:
        with transaction.atomic():
            session = AttendanceSession.objects.select_for_update().get(pk=s_obj.pk)
            if session.is_finalized:
                continue

            policy = session.get_policy()
            enrolled_students = get_enrolled_student_users_for_course(session.course_id)
            existing_entries = {
                e.student_id: e for e in AttendanceEntry.objects.select_for_update().filter(session=session)
            }

            unresolved_pending_count = 0
            for stu in enrolled_students:
                entry = existing_entries.get(stu.pk)
                if entry is None:
                    if policy.auto_finalize_unsubmitted_to_absent:
                        new_entry = AttendanceEntry.objects.create(
                            session=session,
                            student=stu,
                            status='ABSENT',
                            attendance_method='SYSTEM_AUTO',
                            reviewed_at=now,
                            rejection_reason='عدم ثبت درخواست حضور در بازه مجاز (ثبت غیبت خودکار)',
                        )
                        _sync_legacy_attendance_model(new_entry)
                        AttendanceAuditLog.objects.create(
                            session=session,
                            entry=new_entry,
                            student=stu,
                            actor=None,
                            actor_role='system',
                            action='AUTO_FINALIZE_UNSUBMITTED_ABSENT',
                            previous_status='NONE',
                            new_status='ABSENT',
                            reason='پایان مهلت تایید استاد و عدم ارسال درخواست حضور توسط زبان‌آموز',
                        )
                        _notify(
                            stu, 'STUDENT', session,
                            f"ثبت غیبت خودکار — {session.title}",
                            f"به دلیل عدم ثبت حضور در جلسه «{session.title}»، وضعیت شما غایب ثبت شد."
                        )
                elif entry.status == 'PENDING':
                    unresolved_pending_count += 1
                    if policy.unresolved_pending_policy == 'ABSENT':
                        prev = entry.status
                        entry.status = 'ABSENT'
                        entry.attendance_method = 'SYSTEM_AUTO'
                        entry.reviewed_at = now
                        entry.rejection_reason = 'پایان مهلت بررسی استاد — تعیین تکلیف خودکار طبق سیاست آموزشگاه'
                        entry.save()
                        _sync_legacy_attendance_model(entry)
                        AttendanceAuditLog.objects.create(
                            session=session,
                            entry=entry,
                            student=stu,
                            actor=None,
                            actor_role='system',
                            action='AUTO_FINALIZE_EXPIRED_PENDING',
                            previous_status=prev,
                            new_status='ABSENT',
                            reason='عدم بررسی توسط استاد در مهلت مقرر و اعمال سیاست خودکار آموزشگاه',
                        )

            session.is_finalized = True
            session.status = 'FINALIZED'
            session.finalized_at = now
            session.save(update_fields=['is_finalized', 'status', 'finalized_at'])
            finalized_count += 1

            if unresolved_pending_count > 0:
                _notify(
                    None, 'ADMIN', session,
                    f"هشدار مدیریتی: انقضای مهلت تایید استاد در جلسه «{session.title}»",
                    f"مهلت تایید حضور و غیاب کلاس «{session.course_title}» به پایان رسید در حالی که {unresolved_pending_count} درخواست توسط استاد بررسی نشده بود."
                )
                _notify(
                    session.teacher, 'TEACHER', session,
                    f"انقضای مهلت تایید حضور و غیاب — {session.title}",
                    f"مهلت بررسی درخواست‌های حضور جلسه «{session.title}» به پایان رسید و جلسه به صورت سیستمی نهایی شد."
                )

    return finalized_count