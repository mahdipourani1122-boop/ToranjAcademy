from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q
from django.apps import apps

from .models import (
    AttendanceSession,
    AttendanceEntry,
    AttendanceAuditLog,
    AttendanceNotification,
)
from .attendance_service import is_admin_user, get_user_display, finalize_expired_sessions

User = get_user_model()


def _find_first_model(candidates):
    for app_label, model_name in candidates:
        try:
            model = apps.get_model(app_label, model_name)
            if model is not None:
                return model
        except LookupError:
            continue
    return None


@login_required
@require_http_methods(["GET", "POST"])
def admin_dashboard_view(request):
    if not is_admin_user(request.user):
        return HttpResponseForbidden("دسترسی محدود به مدیریت کل آموزشگاه زبان تُرَنج است.")

    finalize_expired_sessions()
    user = request.user

    if request.method == 'POST':
        action = request.POST.get('form_action', '').strip()

        if action == 'review_payment':
            payment_id = request.POST.get('payment_id', '')
            decision = request.POST.get('decision', 'approved').lower()
            SubModel = _find_first_model([
                ('academics', 'PaymentRequest'),
                ('academics', 'Subscription'),
                ('courses', 'Payment'),
            ])
            if SubModel and payment_id.isdigit():
                with transaction.atomic():
                    obj = get_object_or_404(SubModel, pk=int(payment_id))
                    if hasattr(obj, 'status'):
                        obj.status = 'approved' if decision == 'approved' else 'rejected'
                        obj.save()
                    messages.success(request, "وضعیت پرداخت زبان‌آموز با موفقیت توسط مدیریت بروزرسانی شد.")
            return redirect('/dashboard/admin/?tab=payments')

        elif action == 'publish_announcement':
            title = request.POST.get('title', '').strip()[:150]
            message_txt = request.POST.get('message', '').strip()[:2000]
            audience = request.POST.get('audience', 'STUDENT').upper()
            if title and message_txt:
                AttendanceNotification.objects.create(
                    recipient=None,
                    audience_role=audience if audience in ('STUDENT', 'TEACHER', 'ADMIN') else 'STUDENT',
                    title=title,
                    message=message_txt,
                )
                messages.success(request, "اطلاعیه رسمی با موفقیت در سامانه منتشر شد.")
            return redirect('/dashboard/admin/?tab=news')

    search_q = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()

    users_qs = User.objects.all().order_by('-id')
    if search_q:
        users_qs = users_qs.filter(
            Q(first_name__icontains=search_q)
            | Q(last_name__icontains=search_q)
            | Q(phone__icontains=search_q)
        )
    if role_filter:
        users_qs = users_qs.filter(role=role_filter)

    total_students = User.objects.filter(role='student').count()
    total_teachers = User.objects.filter(Q(role='teacher') | Q(is_teacher=True)).distinct().count()
    total_supervisors = User.objects.filter(role='supervisor').count()
    total_admins = User.objects.filter(Q(is_superuser=True) | Q(is_staff=True) | Q(role='admin')).distinct().count()

    courses_list = []
    CourseModel = _find_first_model([('courses', 'Course'), ('academics', 'Course')])
    if CourseModel:
        try:
            for c in CourseModel.objects.all().order_by('-id')[:50]:
                courses_list.append({
                    'id': c.pk,
                    'title': getattr(c, 'title', getattr(c, 'name', str(c))),
                    'language': str(getattr(c, 'get_language_display', lambda: getattr(c, 'language', 'عمومی'))()),
                    'level': str(getattr(c, 'level', 'CEFR')),
                    'teacher': str(getattr(c, 'teacher', 'تعیین‌نشده')),
                    'is_active': getattr(c, 'is_active', True),
                })
        except Exception:
            pass

    total_enrollments = 0
    EnrollmentModel = _find_first_model([('courses', 'Enrollment'), ('academics', 'Enrollment')])
    if EnrollmentModel:
        try:
            total_enrollments = EnrollmentModel.objects.count()
        except Exception:
            pass

    payment_requests = []
    SubModel = _find_first_model([('academics', 'PaymentRequest'), ('academics', 'Subscription'), ('courses', 'Payment')])
    if SubModel:
        try:
            for p in SubModel.objects.all().order_by('-id')[:40]:
                st_obj = getattr(p, 'student', getattr(p, 'user', None))
                payment_requests.append({
                    'id': p.pk,
                    'student_name': get_user_display(getattr(st_obj, 'user', st_obj)),
                    'title': getattr(p, 'title', 'شهریه دوره آموزشی'),
                    'reference': getattr(p, 'tracking_code', getattr(p, 'reference_code', '—')),
                    'status': str(getattr(p, 'status', 'pending')).lower(),
                })
        except Exception:
            pass

    att_entries = AttendanceEntry.objects.all()
    attendance_overview = {
        'sessions_count': AttendanceSession.objects.count(),
        'pending_count': att_entries.filter(status='PENDING').count(),
        'present_count': att_entries.filter(status='PRESENT').count(),
        'late_count': att_entries.filter(status='LATE').count(),
        'absent_count': att_entries.filter(status='ABSENT').count(),
    }

    recent_audits = AttendanceAuditLog.objects.select_related('session', 'student', 'actor')[:30]
    announcements = AttendanceNotification.objects.filter(recipient__isnull=True)[:20]

    context = {
        'active_tab': request.GET.get('tab', 'overview').strip(),
        'admin_name': get_user_display(user),
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_supervisors': total_supervisors,
        'total_admins': total_admins,
        'total_courses': len(courses_list),
        'total_enrollments': total_enrollments,
        'courses_list': courses_list,
        'users_list': users_qs[:60],
        'search_q': search_q,
        'role_filter': role_filter,
        'payment_requests': payment_requests,
        'pending_payments_count': sum(1 for p in payment_requests if p['status'] == 'pending'),
        'attendance_overview': attendance_overview,
        'recent_audits': recent_audits,
        'announcements': announcements,
    }
    return render(request, 'dashboards/admin_dashboard.html', context)
