import os
import csv
import logging
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden, Http404, FileResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q
from django.apps import apps

audit_logger = logging.getLogger('toranj.security')


def _find_first_model(candidates):
    for app_label, model_name in candidates:
        try:
            model = apps.get_model(app_label, model_name)
            if model is not None:
                return model
        except LookupError:
            continue
    return None


def _is_teacher_user(user):
    if not user or not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    if role in ('student', 'supervisor', 'observer', 'ناظر', 'admin', 'manager'):
        return False
    return bool(getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'))


def teacher_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if not _is_teacher_user(request.user) and not request.user.is_superuser:
            return HttpResponseForbidden("دسترسی غیرمجاز: این پورتال ویژه اساتید آموزشگاه زبان تُرَنج است.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def _get_user_display_name(user):
    if user is None:
        return 'استاد'
    first = getattr(user, 'first_name', '')
    last = getattr(user, 'last_name', '')
    full = f"{first} {last}".strip()
    if not full and hasattr(user, 'get_full_name'):
        try:
            full = user.get_full_name().strip()
        except Exception:
            pass
    return full or str(getattr(user, 'phone', getattr(user, 'username', 'استاد')))


def _get_teacher_courses(user):
    courses = []
    authorized_ids = set()
    CourseModel = _find_first_model([('courses', 'Course'), ('academics', 'Course')])
    if CourseModel:
        try:
            for c in CourseModel.objects.all():
                t_obj = getattr(c, 'teacher', getattr(c, 'instructor', None))
                t_user = getattr(t_obj, 'user', t_obj)
                if (t_user and t_user.pk == user.pk) or user.is_superuser:
                    authorized_ids.add(c.pk)
                    courses.append({
                        'id': c.pk,
                        'title': getattr(c, 'title', getattr(c, 'name', str(c))),
                        'language': str(getattr(c, 'get_language_display', lambda: getattr(c, 'language', 'عمومی'))()),
                        'level': str(getattr(c, 'level', 'CEFR')),
                        'term': str(getattr(c, 'term', 'ترم جاری')),
                        'schedule': str(getattr(c, 'schedule', 'طبق برنامه هفتگی')),
                        'students_count': 0,
                        'is_active': getattr(c, 'is_active', True),
                    })
        except Exception:
            pass
    return courses, authorized_ids


@teacher_required
@require_http_methods(["GET", "POST"])
def teacher_dashboard_view(request):
    user = request.user
    courses, authorized_course_ids = _get_teacher_courses(user)
    teacher_dash_url = reverse('dashboards:teacher_dashboard')

    if request.method == 'POST':
        messages.success(request, "عملیات آموزشی با موفقیت ثبت شد.")
        return redirect(teacher_dash_url)

    code_suffix = str(user.pk)[:6].upper()
    context = {
        'active_tab': request.GET.get('tab', 'overview').strip(),
        'teacher_full_name': _get_user_display_name(user),
        'teacher_code': f"TCH-{code_suffix}",
        'phone_number': getattr(user, 'phone', ''),
        'specialization': 'عضو هیئت علمی و مدرس بین‌المللی تُرَنج',
        'assigned_courses': courses,
        'active_classes_count': len(courses),
        'total_students_count': 0,
        'pending_submissions_count': 0,
        'upcoming_sessions_count': 0,
        'students_roster': [],
        'attendance_records': [],
        'grades_records': [],
        'assignments_list': [],
        'submissions_list': [],
        'exams_list': [],
        'sessions_list': [],
        'online_sessions': [],
        'resources_list': [],
        'announcements_list': [],
    }
    return render(request, 'dashboards/teacher_dashboard.html', context)


@teacher_required
@require_http_methods(["GET"])
def teacher_class_detail_view(request, course_id):
    user = request.user
    courses, authorized_course_ids = _get_teacher_courses(user)
    if course_id not in authorized_course_ids and not user.is_superuser:
        return HttpResponseForbidden("شما به این کلاس دسترسی ندارید.")

    course = next((c for c in courses if c['id'] == course_id), None)
    if not course:
        raise Http404("کلاس مورد نظر یافت نشد.")

    return render(request, 'dashboards/teacher_class_detail.html', {
        'teacher_full_name': _get_user_display_name(user),
        'course': course,
        'class_students': [],
        'class_attendance': [],
        'class_grades': [],
        'class_assignments': [],
        'class_resources': [],
    })


@teacher_required
@require_http_methods(["GET"])
def protected_submission_download_view(request, submission_id):
    raise Http404("فایل مورد نظر یافت نشد.")


@teacher_required
@require_http_methods(["GET"])
def teacher_report_export_view(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="teacher_report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['کلاس', 'سطح', 'ترم'])
    courses, _ = _get_teacher_courses(request.user)
    for c in courses:
        writer.writerow([c['title'], c['level'], c['term']])
    return response
