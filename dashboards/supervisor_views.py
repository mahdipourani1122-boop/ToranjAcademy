from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.http import HttpResponseForbidden
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Count

from .models import AttendanceSession, AttendanceEntry, AttendanceAuditLog
from .attendance_service import is_admin_user, get_user_display, finalize_expired_sessions

User = get_user_model()


def is_supervisor_user(user):
    if not user or not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    return bool(is_admin_user(user) or getattr(user, 'is_supervisor', False) or role in ('supervisor', 'observer', 'ناظر'))


@login_required
@require_http_methods(["GET"])
def supervisor_dashboard_view(request):
    """داشبورد ناظر آموزشی با کوئری بهینه‌شده (بدون N+1) برای پشتیبانی از صدها زبان‌آموز و کلاس"""
    if not is_supervisor_user(request.user):
        return HttpResponseForbidden("دسترسی غیرمجاز: این بخش ویژه ناظران آموزشی و مدیریت است.")

    finalize_expired_sessions()
    dept_filter = request.GET.get('department', '').strip()

    sessions_qs = AttendanceSession.objects.select_related('teacher').order_by('-start_time')
    if dept_filter:
        sessions_qs = sessions_qs.filter(department__icontains=dept_filter)

    # رفع کامل مشکل N+1 با استفاده از annotate در یک کوئری واحد
    teachers_qs = (
        User.objects.filter(Q(role='teacher') | Q(is_teacher=True))
        .annotate(
            sessions_cnt=Count('teaching_attendance_sessions', distinct=True),
            pending_cnt=Count(
                'teaching_attendance_sessions__entries',
                filter=Q(teaching_attendance_sessions__entries__status='PENDING'),
                distinct=True,
            ),
            approved_cnt=Count(
                'teaching_attendance_sessions__entries',
                filter=Q(teaching_attendance_sessions__entries__status__in=('PRESENT', 'LATE')),
                distinct=True,
            ),
        )
        .distinct()
    )

    teacher_metrics = [
        {
            'name': get_user_display(t),
            'phone': getattr(t, 'phone', ''),
            'sessions_count': t.sessions_cnt,
            'pending_approvals': t.pending_cnt,
            'approved_records': t.approved_cnt,
        }
        for t in teachers_qs
    ]

    all_entries = AttendanceEntry.objects.all()
    stats = {
        'monitored_sessions': sessions_qs.count(),
        'active_teachers': len(teacher_metrics),
        'total_students': User.objects.filter(role='student').count(),
        'pending_requests': all_entries.filter(status='PENDING').count(),
        'present_records': all_entries.filter(status='PRESENT').count(),
        'absent_records': all_entries.filter(status='ABSENT').count(),
    }

    context = {
        'active_tab': request.GET.get('tab', 'overview').strip(),
        'supervisor_name': get_user_display(request.user),
        'stats': stats,
        'sessions': sessions_qs[:40],
        'teacher_metrics': teacher_metrics,
        'recent_audits': AttendanceAuditLog.objects.select_related('session', 'student', 'actor')[:25],
        'dept_filter': dept_filter,
    }
    return render(request, 'dashboards/supervisor_dashboard.html', context)
