import csv
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import (
    AttendancePolicy,
    AttendanceSession,
    AttendanceEntry,
    AttendanceAuditLog,
    AttendanceNotification,
)
from .attendance_service import (
    get_user_display,
    is_admin_user,
    is_teacher_user,
    get_enrolled_student_users_for_course,
    submit_student_attendance_request,
    teacher_review_attendance,
    admin_override_attendance,
    finalize_expired_sessions,
)


def _get_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _get_student_course_ids(user):
    course_ids = set()
    for app_label, model_name in [('courses', 'Enrollment'), ('academics', 'Enrollment'), ('academics', 'CourseEnrollment')]:
        try:
            EnrollmentModel = apps.get_model(app_label, model_name)
            for enr in EnrollmentModel.objects.filter(student__pk=user.pk):
                if getattr(enr, 'course_id', None):
                    course_ids.add(enr.course_id)
        except Exception:
            pass
    try:
        CourseModel = apps.get_model('courses', 'Course')
        for c in CourseModel.objects.filter(students=user):
            course_ids.add(c.pk)
    except Exception:
        pass
    for cid in AttendanceEntry.objects.filter(student=user).values_list('session__course_id', flat=True):
        course_ids.add(cid)
    return course_ids


def _get_teacher_courses_meta(user):
    courses_meta = []
    course_ids = set()
    try:
        CourseModel = apps.get_model('courses', 'Course')
        for c in CourseModel.objects.all():
            t_obj = getattr(c, 'teacher', getattr(c, 'instructor', None))
            t_user = getattr(t_obj, 'user', t_obj)
            if (t_user and t_user.pk == user.pk) or is_admin_user(user):
                course_ids.add(c.pk)
                courses_meta.append({
                    'id': c.pk,
                    'title': getattr(c, 'title', getattr(c, 'name', str(c))),
                    'department': str(getattr(c, 'get_language_display', lambda: getattr(c, 'language', 'عمومی'))()),
                    'term': str(getattr(c, 'term', 'ترم جاری')),
                })
    except Exception:
        pass
    for s in AttendanceSession.objects.filter(teacher=user):
        if s.course_id not in course_ids:
            course_ids.add(s.course_id)
            courses_meta.append({
                'id': s.course_id,
                'title': s.course_title,
                'department': s.department,
                'term': s.term,
            })
    return courses_meta, course_ids


@login_required
@require_http_methods(["GET", "POST"])
def student_attendance_hub_view(request):
    """
    پنل دومرحله‌ای حضور و غیاب ویژه زبان‌آموز:
    - مشاهده جلسات، ارسال درخواست حضور (STAGE 1) با کد جلسه آنلاین
    - مشاهده وضعیت‌های PENDING, PRESENT, LATE, REJECTED, ABSENT, EXCUSED
    - عدم امکان دستکاری مستقیم وضعیت رسمی حضور
    """
    if is_teacher_user(request.user) and not request.user.is_superuser:
        return HttpResponseForbidden("این بخش ویژه زبان‌آموزان است.")

    finalize_expired_sessions()
    user = request.user
    ip = _get_client_ip(request)

    if request.method == 'POST':
        action = request.POST.get('form_action', '')
        if action == 'request_attendance':
            session_id = request.POST.get('session_id', '')
            submitted_code = request.POST.get('attendance_code', '')
            student_note = request.POST.get('student_note', '')
            try:
                submit_student_attendance_request(
                    student_user=user,
                    session_id=int(session_id),
                    submitted_code=submitted_code,
                    student_note=student_note,
                    ip_address=ip,
                )
                messages.success(
                    request,
                    "درخواست حضور شما با موفقیت ثبت شد (وضعیت: در انتظار تایید نهایی استاد)."
                )
            except (ValidationError, PermissionDenied) as exc:
                msg = exc.message if hasattr(exc, 'message') else str(exc.messages[0] if hasattr(exc, 'messages') else exc)
                messages.error(request, msg)
            except Exception:
                messages.error(request, "امکان ثبت درخواست برای این جلسه وجود ندارد.")
            return redirect('dashboards:student_attendance_hub')

    course_ids = _get_student_course_ids(user)
    sessions = AttendanceSession.objects.filter(course_id__in=course_ids).order_by('-start_time')
    entries_by_session = {
        e.session_id: e for e in AttendanceEntry.objects.filter(student=user).select_related('session', 'reviewed_by')
    }

    session_rows = []
    stats = {'total': 0, 'present': 0, 'late': 0, 'pending': 0, 'rejected': 0, 'absent': 0, 'excused': 0, 'percentage': None}

    for s in sessions:
        entry = entries_by_session.get(s.pk)
        win_status = s.get_computed_window_status()
        current_status = entry.status if entry else win_status

        if entry:
            stats['total'] += 1
            if entry.status == 'PRESENT':
                stats['present'] += 1
            elif entry.status == 'LATE':
                stats['late'] += 1
            elif entry.status == 'PENDING':
                stats['pending'] += 1
            elif entry.status == 'REJECTED':
                stats['rejected'] += 1
            elif entry.status == 'ABSENT':
                stats['absent'] += 1
            elif entry.status == 'EXCUSED':
                stats['excused'] += 1

        can_request = (
            s.is_request_window_open()
            and (entry is None or entry.status in ('NOT_OPEN', 'REJECTED'))
        )
        session_rows.append({
            'session': s,
            'entry': entry,
            'window_status': win_status,
            'display_status': current_status,
            'can_request': can_request,
            'requires_code': s.requires_attendance_code,
        })

    finalized_total = stats['present'] + stats['late'] + stats['absent'] + stats['rejected'] + stats['excused']
    if finalized_total > 0:
        eff = stats['present'] + (stats['late'] * 0.5) + stats['excused']
        stats['percentage'] = round((eff / finalized_total) * 100, 1)

    notifications = AttendanceNotification.objects.filter(recipient=user, audience_role='STUDENT')[:15]

    return render(request, 'dashboards/attendance_student.html', {
        'student_name': get_user_display(user),
        'session_rows': session_rows,
        'stats': stats,
        'notifications': notifications,
    })


@login_required
@require_http_methods(["GET", "POST"])
def teacher_attendance_hub_view(request):
    """
    پنل دومرحله‌ای مدیریت حضور و غیاب ویژه استاد:
    - ایجاد جلسه حضوری یا آنلاین و تولید کد امنیتی منقضی‌شونده
    - مشاهده درخواست‌های PENDING زبان‌آموزان به همراه زمان دقیق ثبت
    - تایید نهایی (PRESENT)، ثبت تأخیر (LATE)، رد درخواست (REJECTED) یا ثبت دستی
    - تایید گروهی (Bulk Approval) با انتخاب و تایید صریح استاد
    """
    if not is_teacher_user(request.user) and not is_admin_user(request.user):
        return HttpResponseForbidden("دسترسی غیرمجاز: این بخش ویژه اساتید است.")

    finalize_expired_sessions()
    user = request.user
    ip = _get_client_ip(request)
    courses_meta, authorized_course_ids = _get_teacher_courses_meta(user)

    if request.method == 'POST':
        action = request.POST.get('form_action', '')

        if action == 'create_session':
            course_id_raw = request.POST.get('course_id', '')
            title = request.POST.get('title', 'جلسه آموزشی').strip()[:140]
            mode = request.POST.get('mode', 'PHYSICAL').upper()
            course_title_input = request.POST.get('course_title', '').strip()
            generate_code_now = request.POST.get('generate_code') == 'on'

            if not course_id_raw.isdigit() or (int(course_id_raw) not in authorized_course_ids and not is_admin_user(user)):
                return HttpResponseForbidden("شما مجوز ایجاد جلسه برای این دوره را ندارید.")

            c_id = int(course_id_raw)
            c_meta = next((c for c in courses_meta if c['id'] == c_id), {'title': course_title_input or f'دوره #{c_id}', 'department': 'عمومی', 'term': 'ترم جاری'})

            session = AttendanceSession.objects.create(
                course_id=c_id,
                course_title=c_meta['title'],
                department=c_meta['department'],
                term=c_meta['term'],
                teacher=user,
                title=title or 'جلسه آموزشی',
                mode='ONLINE' if mode == 'ONLINE' else 'PHYSICAL',
                status='OPEN',
            )
            if session.mode == 'ONLINE' and (generate_code_now or session.requires_attendance_code):
                code = session.generate_secure_code()
                messages.success(request, f"جلسه آنلاین ایجاد شد. کد امنیتی حضور زبان‌آموزان: {code}")
            else:
                messages.success(request, "جلسه حضور و غیاب با موفقیت ایجاد و پنجره ثبت درخواست باز شد.")
            return redirect(f"{reverse('dashboards:teacher_attendance_hub')}?session_id={session.pk}")

        elif action == 'regenerate_code':
            session_id = int(request.POST.get('session_id', '0'))
            session = get_object_or_404(AttendanceSession, pk=session_id)
            if session.teacher_id != user.pk and not is_admin_user(user):
                return HttpResponseForbidden("عدم دسترسی به این جلسه.")
            code = session.generate_secure_code()
            messages.success(request, f"کد امنیتی جدید با موفقیت تولید شد: {code}")
            return redirect(f"{reverse('dashboards:teacher_attendance_hub')}?session_id={session.pk}")

        elif action == 'decide_single':
            session_id = int(request.POST.get('session_id', '0'))
            student_id = int(request.POST.get('student_id', '0'))
            decision = request.POST.get('decision', 'PRESENT')
            reason = request.POST.get('reason', '')
            private_note = request.POST.get('private_note', '')
            try:
                teacher_review_attendance(
                    teacher_user=user,
                    session_id=session_id,
                    student_id=student_id,
                    decision=decision,
                    reason=reason,
                    private_note=private_note,
                    ip_address=ip,
                )
                messages.success(request, "تصمیم نهایی استاد برای زبان‌آموز ثبت و در تاریخچه ممیزی ذخیره شد.")
            except (ValidationError, PermissionDenied) as exc:
                msg = exc.message if hasattr(exc, 'message') else str(exc)
                messages.error(request, msg)
            return redirect(f"{reverse('dashboards:teacher_attendance_hub')}?session_id={session_id}")

        elif action == 'bulk_approve':
            session_id = int(request.POST.get('session_id', '0'))
            confirmed = request.POST.get('confirm_bulk') == 'yes'
            selected_student_ids = request.POST.getlist('student_ids')

            if not confirmed or not selected_student_ids:
                messages.error(request, "برای تایید گروهی، انتخاب زبان‌آموزان و تایید صریح استاد الزامی است.")
                return redirect(f"{reverse('dashboards:teacher_attendance_hub')}?session_id={session_id}")

            approved_cnt = 0
            for sid in selected_student_ids:
                if sid.isdigit():
                    try:
                        teacher_review_attendance(
                            teacher_user=user,
                            session_id=session_id,
                            student_id=int(sid),
                            decision='PRESENT',
                            reason='تایید گروهی توسط استاد جلسه',
                            ip_address=ip,
                        )
                        approved_cnt += 1
                    except Exception:
                        continue
            messages.success(request, f"تایید نهایی حضور برای {approved_cnt} زبان‌آموز انتخاب‌شده انجام گردید.")
            return redirect(f"{reverse('dashboards:teacher_attendance_hub')}?session_id={session_id}")

    sessions = AttendanceSession.objects.filter(teacher=user).order_by('-start_time')
    selected_session_id = request.GET.get('session_id')
    selected_session = (
        sessions.filter(pk=int(selected_session_id)).first()
        if selected_session_id and selected_session_id.isdigit()
        else sessions.first()
    )

    roster = []
    session_counts = {'enrolled': 0, 'pending': 0, 'present': 0, 'late': 0, 'rejected': 0, 'absent': 0}

    if selected_session:
        enrolled_users = get_enrolled_student_users_for_course(selected_session.course_id)
        entries_map = {
            e.student_id: e for e in AttendanceEntry.objects.filter(session=selected_session).select_related('student', 'reviewed_by')
        }
        all_student_ids = {u.pk for u in enrolled_users} | set(entries_map.keys())
        User = get_user_model()
        students_qs = User.objects.filter(pk__in=all_student_ids)

        for stu in students_qs:
            entry = entries_map.get(stu.pk)
            st_code = entry.status if entry else 'NOT_SUBMITTED'
            session_counts['enrolled'] += 1
            if st_code == 'PENDING':
                session_counts['pending'] += 1
            elif st_code == 'PRESENT':
                session_counts['present'] += 1
            elif st_code == 'LATE':
                session_counts['late'] += 1
            elif st_code == 'REJECTED':
                session_counts['rejected'] += 1
            elif st_code == 'ABSENT':
                session_counts['absent'] += 1

            roster.append({
                'student': stu,
                'student_name': get_user_display(stu),
                'student_phone': getattr(stu, 'phone', getattr(stu, 'username', '')),
                'academy_id': f"TRJ-{stu.pk:04d}",
                'entry': entry,
                'status': st_code,
            })

    today = timezone.localdate()
    return render(request, 'dashboards/attendance_teacher.html', {
        'teacher_name': get_user_display(user),
        'courses_meta': courses_meta,
        'sessions': sessions,
        'today_sessions_count': sessions.filter(session_date=today).count(),
        'selected_session': selected_session,
        'roster': roster,
        'session_counts': session_counts,
        'notifications': AttendanceNotification.objects.filter(recipient=user, audience_role='TEACHER')[:10],
    })


@login_required
@require_http_methods(["GET", "POST"])
def admin_attendance_hub_view(request):
    """
    پنل جامع نظارت، تنظیمات سیاست‌ها و بازنویسی مدیریتی حضور و غیاب ویژه مدیریت آموزشگاه (Admin):
    - تنظیم سیاست‌های آموزشگاه و مهلت تایید استاد (AttendancePolicy)
    - نظارت سراسری بر تمام کلاس‌ها، اساتید، دپارتمان‌ها و درخواست‌های معوق
    - بازنویسی تصمیم استاد (Admin Override) با الزام ثبت دلیل در لاگ تغییرناپذیر
    - خروجی کامل گزارش‌های تحلیلی به فرمت Excel / CSV و چاپی PDF
    """
    if not is_admin_user(request.user):
        return HttpResponseForbidden("دسترسی محدود به مدیریت آموزشگاه زبان تُرَنج است.")

    finalize_expired_sessions()
    user = request.user
    ip = _get_client_ip(request)
    policy = AttendancePolicy.get_effective_policy()

    if request.method == 'POST':
        action = request.POST.get('form_action', '')

        if action == 'update_policy':
            policy.open_before_minutes = int(request.POST.get('open_before_minutes', 15) or 15)
            policy.close_after_minutes = int(request.POST.get('close_after_minutes', 45) or 45)
            policy.late_threshold_minutes = int(request.POST.get('late_threshold_minutes', 15) or 15)
            policy.teacher_approval_deadline_hours = int(request.POST.get('teacher_approval_deadline_hours', 24) or 24)
            policy.require_online_code = request.POST.get('require_online_code') == 'on'
            policy.allow_late_requests = request.POST.get('allow_late_requests') == 'on'
            policy.allow_teacher_edit_after_approval = request.POST.get('allow_teacher_edit_after_approval') == 'on'
            policy.rejection_policy = request.POST.get('rejection_policy', 'ABSENT')
            policy.updated_by = user
            policy.save()
            messages.success(request, "تنظیمات و سیاست‌های حضور و غیاب آموزشگاه با موفقیت ذخیره شد.")
            return redirect('dashboards:admin_attendance_hub')

        elif action == 'admin_override':
            session_id = int(request.POST.get('session_id', '0'))
            student_id = int(request.POST.get('student_id', '0'))
            new_status = request.POST.get('new_status', 'PRESENT')
            mandatory_reason = request.POST.get('mandatory_reason', '')
            try:
                admin_override_attendance(
                    admin_user=user,
                    session_id=session_id,
                    student_id=student_id,
                    new_status=new_status,
                    mandatory_reason=mandatory_reason,
                    ip_address=ip,
                )
                messages.success(request, "بازنویسی مدیریتی وضعیت حضور با موفقیت انجام و در سجل ممیزی ثبت شد.")
            except (ValidationError, PermissionDenied) as exc:
                msg = exc.message if hasattr(exc, 'message') else str(exc)
                messages.error(request, msg)
            return redirect('dashboards:admin_attendance_hub')

        elif action == 'reopen_session':
            session_id = int(request.POST.get('session_id', '0'))
            reason = request.POST.get('reason', '').strip()
            if len(reason) < 3:
                messages.error(request, "ثبت دلیل برای بازگشایی مجدد جلسه الزامی است.")
                return redirect('dashboards:admin_attendance_hub')
            session = get_object_or_404(AttendanceSession, pk=session_id)
            prev = session.status
            session.status = 'OPEN'
            session.is_finalized = False
            session.window_closes_at = timezone.now() + timezone.timedelta(minutes=45)
            session.teacher_approval_deadline = timezone.now() + timezone.timedelta(hours=policy.teacher_approval_deadline_hours)
            session.save()
            AttendanceAuditLog.objects.create(
                session=session,
                actor=user,
                actor_role='admin',
                action='ADMIN_REOPEN_SESSION',
                previous_status=prev,
                new_status='OPEN',
                reason=reason,
                ip_address=ip,
            )
            messages.success(request, f"جلسه «{session.title}» با موفقیت بازگشایی شد.")
            return redirect('dashboards:admin_attendance_hub')

    # فیلترهای گزارش مدیریتی
    dept_filter = request.GET.get('department', '').strip()
    status_filter = request.GET.get('status', '').strip()
    search_q = request.GET.get('q', '').strip()

    entries_qs = AttendanceEntry.objects.select_related('session', 'student', 'reviewed_by').order_by('-updated_at')
    if dept_filter:
        entries_qs = entries_qs.filter(session__department__icontains=dept_filter)
    if status_filter:
        entries_qs = entries_qs.filter(status=status_filter)
    if search_q:
        entries_qs = entries_qs.filter(
            models.Q(session__course_title__icontains=search_q)
            | models.Q(student__first_name__icontains=search_q)
            | models.Q(student__last_name__icontains=search_q)
        )

    # خروجی اکسل / CSV
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="toranj_attendance_master_report.csv"'
        response.write('\ufeff')
        writer = csv.writer(response)
        writer.writerow(['دوره', 'دپارتمان', 'عنوان جلسه', 'نوع کلاس', 'زبان‌آموز', 'وضعیت', 'زمان درخواست', 'بررسی‌کننده', 'زمان تایید', 'دلیل/یادداشت'])
        for e in entries_qs[:1000]:
            writer.writerow([
                e.session.course_title,
                e.session.department,
                e.session.title,
                e.session.get_mode_display(),
                get_user_display(e.student),
                e.status_label_fa,
                e.requested_at.strftime('%Y-%m-%d %H:%M') if e.requested_at else '—',
                get_user_display(e.reviewed_by) if e.reviewed_by else '—',
                e.reviewed_at.strftime('%Y-%m-%d %H:%M') if e.reviewed_at else '—',
                e.admin_override_reason or e.rejection_reason or '—',
            ])
        return response

    all_entries = AttendanceEntry.objects.all()
    global_stats = {
        'sessions_total': AttendanceSession.objects.count(),
        'pending': all_entries.filter(status='PENDING').count(),
        'present': all_entries.filter(status='PRESENT').count(),
        'late': all_entries.filter(status='LATE').count(),
        'absent': all_entries.filter(status='ABSENT').count(),
        'excused': all_entries.filter(status='EXCUSED').count(),
        'rejected': all_entries.filter(status='REJECTED').count(),
    }

    return render(request, 'dashboards/attendance_admin.html', {
        'policy': policy,
        'global_stats': global_stats,
        'entries': entries_qs[:100],
        'sessions': AttendanceSession.objects.select_related('teacher').order_by('-start_time')[:50],
        'audit_logs': AttendanceAuditLog.objects.select_related('session', 'student', 'actor')[:50],
        'admin_alerts': AttendanceNotification.objects.filter(audience_role='ADMIN')[:15],
        'dept_filter': dept_filter,
        'status_filter': status_filter,
        'search_q': search_q,
    })