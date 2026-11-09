import os
import logging
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.http import HttpResponseForbidden, Http404, FileResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q
from django.apps import apps
from django.utils import timezone

audit_logger = logging.getLogger('toranj.security')

ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.doc', '.docx', '.zip', '.jpg', '.jpeg', '.png', '.mp3'}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _get_model_safe(app_label, model_name):
    """بارگذاری ایمن مدل‌ها بدون ایجاد خطای ImportError"""
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _find_first_model(candidates):
    """جستجوی اولین مدل موجود در بین اپ‌های پروژه"""
    for app_label, model_name in candidates:
        model = _get_model_safe(app_label, model_name)
        if model is not None:
            return model
    return None


def _is_student_user(user):
    """بررسی نقش زبان‌آموز از روی نشست سرور (Server-Side Session)"""
    if not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    if getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'):
        return False
    return True


def student_required(view_func):
    """دکوراتور امنیتی برای کنترل دسترسی نقش زبان‌آموز و جلوگیری از IDOR"""
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if 'user_id' in request.GET or 'student_id' in request.GET:
            audit_logger.warning(
                f"Suspicious query param tampering by user={request.user.pk}"
            )
        if not _is_student_user(request.user) and not request.user.is_superuser:
            audit_logger.warning(
                f"Unauthorized role access attempt to student dashboard by user={request.user.pk}"
            )
            return HttpResponseForbidden("دسترسی غیرمجاز: این بخش ویژه زبان‌آموزان است.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def _get_user_display_name(user):
    """استخراج نام کامل یا شماره موبایل کاربر بدون خطا در مدل کاربری سفارشی"""
    if user is None:
        return 'کاربر'
    full_name = ''
    if hasattr(user, 'get_full_name'):
        try:
            full_name = user.get_full_name().strip()
        except Exception:
            pass
    if not full_name:
        first = getattr(user, 'first_name', '')
        last = getattr(user, 'last_name', '')
        full_name = f"{first} {last}".strip()
    if not full_name:
        full_name = getattr(user, 'full_name', '') or getattr(user, 'phone', '') or getattr(user, 'username', str(user))
    return str(full_name)


def _get_student_profile(user):
    """واکشی پروفایل زبان‌آموز متصل به کاربر احراز هویت‌شده"""
    ProfileModel = _find_first_model([
        ('academics', 'StudentProfile'),
        ('accounts', 'StudentProfile'),
        ('accounts', 'Profile'),
    ])
    if ProfileModel:
        try:
            return ProfileModel.objects.filter(user=user).first()
        except Exception:
            pass
    return None


def _get_academy_student_id(user, profile):
    """دریافت کد زبان‌آموزی واقعی از دیتابیس"""
    for obj in (profile, user):
        if obj is not None:
            for attr in ('student_id', 'academy_id', 'student_code', 'code', 'national_id'):
                val = getattr(obj, attr, None)
                if val:
                    return str(val)
    year_str = user.date_joined.strftime('%Y') if hasattr(user, 'date_joined') and user.date_joined else '2026'
    return f"TRJ-{year_str}-{user.pk:04d}"


def _get_student_enrollments(user, profile):
    """واکشی ثبت‌نام‌ها و دوره‌های مجاز متعلق به زبان‌آموز فعلی"""
    EnrollmentModel = _find_first_model([
        ('courses', 'Enrollment'),
        ('academics', 'Enrollment'),
        ('academics', 'CourseEnrollment'),
    ])
    enrollments = []
    authorized_course_ids = set()

    if EnrollmentModel:
        try:
            field_names = [f.name for f in EnrollmentModel._meta.get_fields()]
            q_filter = Q()
            if 'student' in field_names:
                rel_model = EnrollmentModel._meta.get_field('student').related_model
                if rel_model == user.__class__:
                    q_filter |= Q(student=user)
                elif profile is not None and rel_model == profile.__class__:
                    q_filter |= Q(student=profile)
            if 'user' in field_names:
                q_filter |= Q(user=user)

            if q_filter:
                qs = EnrollmentModel.objects.filter(q_filter).select_related('course')
                for item in qs:
                    course = getattr(item, 'course', None)
                    if course:
                        authorized_course_ids.add(course.pk)
                        status_raw = str(getattr(item, 'status', 'active')).lower()
                        is_completed = getattr(item, 'is_completed', False) or status_raw in ('completed', 'passed', 'finished')
                        progress_val = getattr(item, 'progress', None)
                        teacher_obj = getattr(course, 'teacher', getattr(course, 'instructor', None))
                        teacher_name = _get_user_display_name(teacher_obj) if teacher_obj else 'تعیین‌نشده در سامانه'
                        enrollments.append({
                            'id': item.pk,
                            'course_id': course.pk,
                            'course_title': getattr(course, 'title', getattr(course, 'name', str(course))),
                            'language': getattr(course, 'get_language_display', lambda: getattr(course, 'language', 'عمومی'))(),
                            'level': getattr(course, 'level', 'CEFR'),
                            'term': str(getattr(item, 'term', getattr(course, 'term', 'ترم جاری'))),
                            'teacher_name': teacher_name,
                            'schedule_text': getattr(course, 'schedule', getattr(course, 'class_days', 'طبق تقویم آموزشی')),
                            'status': 'completed' if is_completed else status_raw,
                            'status_label': 'گذرانده‌شده' if is_completed else ('فعال' if status_raw in ('active', 'approved', 'enrolled') else status_raw),
                            'progress': int(progress_val) if isinstance(progress_val, (int, float)) else None,
                            'enrolled_at': getattr(item, 'created_at', getattr(item, 'enrolled_at', None)),
                            'is_active': not is_completed and status_raw in ('active', 'approved', 'enrolled', 'true'),
                            'is_completed': is_completed,
                        })
        except Exception as exc:
            audit_logger.debug(f"Enrollment query notice: {exc}")

    CourseModel = _get_model_safe('courses', 'Course')
    if CourseModel and not enrollments:
        try:
            field_names = [f.name for f in CourseModel._meta.get_fields()]
            if 'students' in field_names:
                for c in CourseModel.objects.filter(students=user):
                    authorized_course_ids.add(c.pk)
                    teacher_obj = getattr(c, 'teacher', getattr(c, 'instructor', None))
                    teacher_name = _get_user_display_name(teacher_obj) if teacher_obj else 'تعیین‌نشده'
                    enrollments.append({
                        'id': c.pk,
                        'course_id': c.pk,
                        'course_title': getattr(c, 'title', getattr(c, 'name', str(c))),
                        'language': getattr(c, 'get_language_display', lambda: getattr(c, 'language', 'عمومی'))(),
                        'level': getattr(c, 'level', 'CEFR'),
                        'term': str(getattr(c, 'term', 'ترم جاری')),
                        'teacher_name': teacher_name,
                        'schedule_text': getattr(c, 'schedule', 'طبق برنامه هفتگی'),
                        'status': 'active',
                        'status_label': 'فعال',
                        'progress': None,
                        'enrolled_at': None,
                        'is_active': True,
                        'is_completed': False,
                    })
        except Exception:
            pass

    return enrollments, authorized_course_ids


def _get_student_attendance(user, profile, authorized_course_ids):
    """واکشی تاریخچه واقعی حضور و غیاب زبان‌آموز"""
    AttendanceModel = _find_first_model([
        ('academics', 'Attendance'),
        ('courses', 'Attendance'),
        ('academics', 'AttendanceRecord'),
    ])
    records = []
    summary = {'total': 0, 'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'percentage': None}

    if AttendanceModel:
        try:
            field_names = [f.name for f in AttendanceModel._meta.get_fields()]
            q_filter = Q()
            if 'student' in field_names:
                rel_model = AttendanceModel._meta.get_field('student').related_model
                if rel_model == user.__class__:
                    q_filter |= Q(student=user)
                elif profile is not None and rel_model == profile.__class__:
                    q_filter |= Q(student=profile)
            if 'user' in field_names:
                q_filter |= Q(user=user)

            if q_filter:
                qs = AttendanceModel.objects.filter(q_filter).order_by('-id')
                for r in qs:
                    status_val = str(getattr(r, 'status', '')).lower()
                    is_present_bool = getattr(r, 'is_present', None)
                    if status_val in ('present', 'حاضر') or is_present_bool is True:
                        norm_status, status_fa = 'present', 'حاضر'
                        summary['present'] += 1
                    elif status_val in ('late', 'تاخیر', 'تأخیر'):
                        norm_status, status_fa = 'late', 'تأخیر'
                        summary['late'] += 1
                    elif status_val in ('excused', 'موجه'):
                        norm_status, status_fa = 'excused', 'غیبت موجه'
                        summary['excused'] += 1
                    else:
                        norm_status, status_fa = 'absent', 'غایب'
                        summary['absent'] += 1

                    summary['total'] += 1
                    course_obj = getattr(r, 'course', getattr(getattr(r, 'session', None), 'course', None))
                    records.append({
                        'id': r.pk,
                        'course_id': getattr(course_obj, 'pk', None),
                        'course_title': getattr(course_obj, 'title', str(course_obj or 'جلسه آموزشی')),
                        'date': getattr(r, 'date', getattr(r, 'session_date', None)),
                        'session_title': getattr(r, 'session_title', str(getattr(r, 'session', 'جلسه کلاسی'))),
                        'status': norm_status,
                        'status_label': status_fa,
                        'note': getattr(r, 'note', ''),
                    })
        except Exception:
            pass

    if summary['total'] > 0:
        effective_present = summary['present'] + (summary['late'] * 0.5) + summary['excused']
        summary['percentage'] = round((effective_present / summary['total']) * 100, 1)

    return records, summary


def _get_student_grades_and_skills(user, profile):
    """واکشی کارنامه و تحلیل ۶ مهارت زبانی (بر اساس رکوردهای واقعی دیتابیس)"""
    GradeModel = _find_first_model([
        ('academics', 'Grade'),
        ('academics', 'Assessment'),
        ('academics', 'ReportCard'),
        ('courses', 'Grade'),
    ])
    SkillModel = _find_first_model([
        ('academics', 'SkillAssessment'),
        ('academics', 'LanguageSkillScore'),
    ])

    grades_list = []
    skill_buckets = {
        'speaking': {'key': 'speaking', 'label_fa': 'مکالمه (Speaking)', 'scores': [], 'feedback': []},
        'listening': {'key': 'listening', 'label_fa': 'مهارت شنیداری (Listening)', 'scores': [], 'feedback': []},
        'grammar': {'key': 'grammar', 'label_fa': 'ساختار و گرامر (Grammar)', 'scores': [], 'feedback': []},
        'vocabulary': {'key': 'vocabulary', 'label_fa': 'دامنه واژگان (Vocabulary)', 'scores': [], 'feedback': []},
        'writing': {'key': 'writing', 'label_fa': 'مهارت نگارش (Writing)', 'scores': [], 'feedback': []},
        'reading': {'key': 'reading', 'label_fa': 'درک مطلب (Reading)', 'scores': [], 'feedback': []},
    }

    for model in filter(None, [GradeModel, SkillModel]):
        try:
            field_names = [f.name for f in model._meta.get_fields()]
            q_filter = Q()
            if 'student' in field_names:
                rel_model = model._meta.get_field('student').related_model
                if rel_model == user.__class__:
                    q_filter |= Q(student=user)
                elif profile is not None and rel_model == profile.__class__:
                    q_filter |= Q(student=profile)
            if 'user' in field_names:
                q_filter |= Q(user=user)

            if not q_filter:
                continue

            for g in model.objects.filter(q_filter).order_by('-id'):
                course_obj = getattr(g, 'course', None)
                score_val = getattr(g, 'score', getattr(g, 'grade', None))
                max_score = getattr(g, 'max_score', 100) or 100
                feedback_txt = getattr(g, 'teacher_feedback', getattr(g, 'feedback', ''))
                term_txt = str(getattr(g, 'term', getattr(course_obj, 'term', 'ترم جاری')))
                grade_type = str(getattr(g, 'assessment_type', 'ارزیابی آموزشی'))

                numeric_score = None
                normalized_100 = None
                if score_val is not None:
                    try:
                        numeric_score = float(score_val)
                        normalized_100 = round((numeric_score / float(max_score)) * 100, 1) if float(max_score) > 0 else numeric_score
                    except (ValueError, TypeError):
                        numeric_score = None

                grades_list.append({
                    'id': g.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or 'ارزیابی عمومی')),
                    'term': term_txt,
                    'title': getattr(g, 'title', grade_type),
                    'score': numeric_score,
                    'max_score': max_score,
                    'normalized_score': normalized_100,
                    'feedback': feedback_txt,
                    'date': getattr(g, 'created_at', None),
                })

                for sk_key in skill_buckets.keys():
                    direct_val = getattr(g, sk_key, getattr(g, f"{sk_key}_score", None))
                    if direct_val is not None:
                        try:
                            skill_buckets[sk_key]['scores'].append(float(direct_val))
                            if feedback_txt:
                                skill_buckets[sk_key]['feedback'].append(feedback_txt)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass

    skills_analytics = []
    has_any_skill_data = False
    strengths, improvements = [], []

    for sk_key, data in skill_buckets.items():
        scores = data['scores']
        if scores:
            has_any_skill_data = True
            avg_score = round(sum(scores) / len(scores), 1)
            if avg_score >= 75:
                strengths.append(data['label_fa'])
            elif avg_score < 60:
                improvements.append(data['label_fa'])
        else:
            avg_score = None

        skills_analytics.append({
            'key': sk_key,
            'label_fa': data['label_fa'],
            'label_en': sk_key.capitalize(),
            'average': avg_score,
            'assessments_count': len(scores),
            'latest_feedback': data['feedback'][0] if data['feedback'] else '',
        })

    valid_grades = [item['normalized_score'] for item in grades_list if item['normalized_score'] is not None]
    gpa = round(sum(valid_grades) / len(valid_grades), 1) if valid_grades else None

    return grades_list, gpa, skills_analytics, has_any_skill_data, strengths, improvements


def _get_assignments_and_exams(user, profile, authorized_course_ids):
    """واکشی تکالیف و آزمون‌ها"""
    AssignmentModel = _find_first_model([('academics', 'Assignment'), ('courses', 'Assignment')])
    SubmissionModel = _find_first_model([('academics', 'AssignmentSubmission'), ('academics', 'Submission')])
    ExamModel = _find_first_model([('academics', 'Exam'), ('courses', 'Exam')])

    assignments, exams = [], []
    now = timezone.now()
    subs_map = {}

    if SubmissionModel:
        try:
            field_names = [f.name for f in SubmissionModel._meta.get_fields()]
            q_sub = Q()
            if 'student' in field_names:
                rel_model = SubmissionModel._meta.get_field('student').related_model
                if rel_model == user.__class__:
                    q_sub |= Q(student=user)
                elif profile is not None and rel_model == profile.__class__:
                    q_sub |= Q(student=profile)
            if 'user' in field_names:
                q_sub |= Q(user=user)
            if q_sub:
                for sub in SubmissionModel.objects.filter(q_sub):
                    a_id = getattr(sub, 'assignment_id', None)
                    if a_id:
                        subs_map[a_id] = sub
        except Exception:
            pass

    if AssignmentModel and authorized_course_ids:
        try:
            for a in AssignmentModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                sub = subs_map.get(a.pk)
                deadline = getattr(a, 'deadline', getattr(a, 'due_date', None))
                is_past = bool(deadline and deadline < now)
                course_obj = getattr(a, 'course', None)
                assignments.append({
                    'id': a.pk,
                    'title': getattr(a, 'title', str(a)),
                    'description': getattr(a, 'description', ''),
                    'course_title': getattr(course_obj, 'title', ''),
                    'deadline': deadline,
                    'is_past_deadline': is_past,
                    'is_submitted': sub is not None,
                    'submission_status': 'ارسال‌شده' if sub else ('مهلت پایان‌یافته' if is_past else 'در انتظار ارسال'),
                    'submitted_answer': getattr(sub, 'answer_text', getattr(sub, 'text', '')) if sub else '',
                    'grade': getattr(sub, 'grade', None) if sub else None,
                    'feedback': getattr(sub, 'feedback', '') if sub else '',
                })
        except Exception:
            pass

    if ExamModel and authorized_course_ids:
        try:
            for ex in ExamModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                ex_date = getattr(ex, 'date', getattr(ex, 'exam_date', None))
                course_obj = getattr(ex, 'course', None)
                is_upcoming = bool(ex_date and ex_date >= now)
                exams.append({
                    'id': ex.pk,
                    'title': getattr(ex, 'title', str(ex)),
                    'course_title': getattr(course_obj, 'title', ''),
                    'date': ex_date,
                    'is_upcoming': is_upcoming,
                    'status_label': 'آزمون پیش‌رو' if is_upcoming else 'برگزارشده',
                    'score': getattr(ex, 'score', None),
                })
        except Exception:
            pass

    return assignments, exams


def _get_sessions_and_resources(authorized_course_ids):
    """واکشی جلسات و منابع آموزشی"""
    SessionModel = _find_first_model([('courses', 'ClassSession'), ('courses', 'Session'), ('academics', 'ClassSession')])
    ResourceModel = _find_first_model([('courses', 'CourseResource'), ('courses', 'Resource')])

    sessions, online_sessions, resources = [], [], []

    if SessionModel and authorized_course_ids:
        try:
            for s in SessionModel.objects.filter(course_id__in=authorized_course_ids).order_by('id'):
                course_obj = getattr(s, 'course', None)
                meeting_url = getattr(s, 'meeting_link', getattr(course_obj, 'meeting_link', ''))
                item = {
                    'id': s.pk,
                    'title': getattr(s, 'title', 'جلسه کلاسی'),
                    'course_title': getattr(course_obj, 'title', ''),
                    'date_time': getattr(s, 'start_time', getattr(s, 'date', '')),
                    'room': getattr(s, 'room', 'حضوری / آنلاین'),
                    'meeting_url': meeting_url,
                    'status': getattr(s, 'status', 'برنامه‌ریزی‌شده'),
                }
                sessions.append(item)
                if meeting_url:
                    online_sessions.append(item)
        except Exception:
            pass

    if ResourceModel and authorized_course_ids:
        try:
            for res in ResourceModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                course_obj = getattr(res, 'course', None)
                file_obj = getattr(res, 'file', None)
                resources.append({
                    'id': res.pk,
                    'title': getattr(res, 'title', str(res)),
                    'description': getattr(res, 'description', ''),
                    'course_title': getattr(course_obj, 'title', ''),
                    'type': str(getattr(res, 'resource_type', 'PDF')).upper(),
                    'has_file': bool(file_obj),
                    'external_url': getattr(res, 'url', ''),
                })
        except Exception:
            pass

    return sessions, online_sessions, resources


def _get_subscription_and_payments(user, profile, enrollments):
    """بررسی وضعیت اشتراک و درخواست‌های پرداخت (تایید دستی مدیریت)"""
    SubModel = _find_first_model([('academics', 'PaymentRequest'), ('academics', 'Subscription'), ('courses', 'Payment')])
    records = []
    if SubModel:
        try:
            field_names = [f.name for f in SubModel._meta.get_fields()]
            q_filter = Q()
            if 'student' in field_names:
                rel_model = SubModel._meta.get_field('student').related_model
                if rel_model == user.__class__:
                    q_filter |= Q(student=user)
                elif profile is not None and rel_model == profile.__class__:
                    q_filter |= Q(student=profile)
            if 'user' in field_names:
                q_filter |= Q(user=user)
            if q_filter:
                for item in SubModel.objects.filter(q_filter).order_by('-id'):
                    status_raw = str(getattr(item, 'status', 'pending')).lower()
                    records.append({
                        'id': item.pk,
                        'title': getattr(item, 'title', 'اشتراک آموزشی'),
                        'status': status_raw,
                        'status_label': 'تأییدشده توسط آموزشگاه' if status_raw in ('approved', 'active') else 'در انتظار بررسی واحد مالی',
                        'reference': getattr(item, 'tracking_code', getattr(item, 'reference_code', '')),
                    })
        except Exception:
            pass

    active_count = sum(1 for e in enrollments if e['is_active'])
    overall_status = 'فعال (تأییدشده توسط آموزشگاه)' if active_count > 0 else 'در انتظار ثبت‌نام / تأیید مدیریت'
    return overall_status, records


def _get_student_notifications(user, enrollments, assignments, exams, grades):
    """واکشی اعلان‌ها"""
    notifications = []
    for a in assignments[:3]:
        if not a['is_submitted'] and not a['is_past_deadline']:
            notifications.append({
                'title': f"تکلیف در انتظار ارسال: {a['title']}",
                'message': f"دوره {a['course_title']}",
                'date': a['deadline'],
                'category': 'تکالیف',
            })
    for ex in exams[:3]:
        if ex['is_upcoming']:
            notifications.append({
                'title': f"آزمون پیش‌رو: {ex['title']}",
                'message': f"دوره {ex['course_title']}",
                'date': ex['date'],
                'category': 'آزمون‌ها',
            })
    return notifications


def _validate_uploaded_file(uploaded_file):
    """بررسی امنیتی پسوند و حجم فایل"""
    if not uploaded_file:
        return True, None
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, f"پسوند فایل ({ext}) مجاز نیست."
    if uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
        return False, "حجم فایل بیش از حد مجاز (۱۰ مگابایت) است."
    uploaded_file.name = os.path.basename(uploaded_file.name)
    return True, None


@login_required
def dashboard_router_view(request):
    """مسیردهی هوشمند بر اساس نقش کاربر (هدایت استاد به پنل استاد و زبان‌آموز به پنل زبان‌آموز)"""
    user = request.user
    role = str(getattr(user, 'role', '')).lower()
    if getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'):
        return redirect('dashboards:teacher_dashboard')
    return redirect('dashboards:student_dashboard')


@student_required
@require_http_methods(["GET", "POST"])
def student_dashboard_view(request):
    """ویوی جامع داشبورد پریمیوم زبان‌آموز"""
    user = request.user
    profile = _get_student_profile(user)
    enrollments, authorized_course_ids = _get_student_enrollments(user, profile)
    student_dash_url = reverse('dashboards:student_dashboard')

    if request.method == 'POST':
        action = request.POST.get('form_action', '').strip()

        if action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()[:50]
            last_name = request.POST.get('last_name', '').strip()[:50]
            email = request.POST.get('email', '').strip()[:120]
            avatar_file = request.FILES.get('avatar')

            is_valid_file, file_err = _validate_uploaded_file(avatar_file)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect(f"{student_dash_url}?tab=profile")

            with transaction.atomic():
                if hasattr(user, 'first_name'):
                    user.first_name = first_name
                if hasattr(user, 'last_name'):
                    user.last_name = last_name
                if email and hasattr(user, 'email'):
                    user.email = email
                user.save()

                if avatar_file and profile is not None:
                    for attr in ('avatar', 'profile_photo', 'photo', 'image'):
                        if hasattr(profile, attr):
                            setattr(profile, attr, avatar_file)
                            profile.save()
                            break

                messages.success(request, "اطلاعات پروفایل با موفقیت بروزرسانی شد.")
            return redirect(f"{student_dash_url}?tab=profile")

        elif action == 'change_password':
            pwd_form = PasswordChangeForm(user=user, data=request.POST)
            if pwd_form.is_valid():
                with transaction.atomic():
                    pwd_form.save()
                    update_session_auth_hash(request, pwd_form.user)
                    messages.success(request, "رمز عبور با موفقیت تغییر یافت.")
            else:
                for err_list in pwd_form.errors.values():
                    for err in err_list:
                        messages.error(request, err)
            return redirect(f"{student_dash_url}?tab=profile")

        elif action == 'submit_assignment':
            assignment_id = request.POST.get('assignment_id')
            answer_text = request.POST.get('answer_text', '').strip()[:5000]
            submission_file = request.FILES.get('submission_file')

            is_valid_file, file_err = _validate_uploaded_file(submission_file)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect(f"{student_dash_url}?tab=assignments")

            AssignmentModel = _find_first_model([('academics', 'Assignment'), ('courses', 'Assignment')])
            SubmissionModel = _find_first_model([('academics', 'AssignmentSubmission'), ('academics', 'Submission')])

            if not AssignmentModel or not SubmissionModel:
                messages.error(request, "ماژول ثبت تکالیف فعال نیست.")
                return redirect(f"{student_dash_url}?tab=assignments")

            assignment_obj = get_object_or_404(AssignmentModel, pk=assignment_id)
            if getattr(assignment_obj, 'course_id', None) not in authorized_course_ids:
                return HttpResponseForbidden("مجوز ارسال تکلیف ندارید.")

            with transaction.atomic():
                sub_fields = [f.name for f in SubmissionModel._meta.get_fields()]
                lookup = {'assignment': assignment_obj}
                if 'student' in sub_fields:
                    rel_m = SubmissionModel._meta.get_field('student').related_model
                    lookup['student'] = user if rel_m == user.__class__ else profile
                elif 'user' in sub_fields:
                    lookup['user'] = user

                defaults = {}
                if 'answer_text' in sub_fields:
                    defaults['answer_text'] = answer_text
                elif 'text' in sub_fields:
                    defaults['text'] = answer_text
                if submission_file and 'file' in sub_fields:
                    defaults['file'] = submission_file

                SubmissionModel.objects.update_or_create(defaults=defaults, **lookup)
                messages.success(request, "پاسخ تکلیف با موفقیت ثبت شد.")
            return redirect(f"{student_dash_url}?tab=assignments")

        elif action == 'submit_payment_claim':
            reference_code = request.POST.get('reference_code', '').strip()[:100]
            course_note = request.POST.get('course_note', '').strip()[:500]
            if not reference_code:
                messages.error(request, "شماره پیگیری را وارد کنید.")
                return redirect(f"{student_dash_url}?tab=subscription")

            SubModel = _find_first_model([('academics', 'PaymentRequest'), ('academics', 'Subscription')])
            with transaction.atomic():
                if SubModel:
                    try:
                        f_names = [f.name for f in SubModel._meta.get_fields()]
                        kwargs = {}
                        if 'user' in f_names:
                            kwargs['user'] = user
                        elif 'student' in f_names:
                            rel_m = SubModel._meta.get_field('student').related_model
                            kwargs['student'] = user if rel_m == user.__class__ else profile
                        if 'status' in f_names:
                            kwargs['status'] = 'pending'
                        if 'tracking_code' in f_names:
                            kwargs['tracking_code'] = reference_code
                        elif 'reference_code' in f_names:
                            kwargs['reference_code'] = reference_code
                        if 'title' in f_names and course_note:
                            kwargs['title'] = course_note
                        SubModel.objects.create(**kwargs)
                    except Exception:
                        pass
                messages.success(request, "درخواست پرداخت با وضعیت «در انتظار بررسی» ثبت شد.")
            return redirect(f"{student_dash_url}?tab=subscription")

    attendance_records, attendance_summary = _get_student_attendance(user, profile, authorized_course_ids)
    grades, gpa, skills_analytics, has_any_skill_data, strengths, improvements = _get_student_grades_and_skills(user, profile)
    assignments, exams = _get_assignments_and_exams(user, profile, authorized_course_ids)
    sessions, online_sessions, resources = _get_sessions_and_resources(authorized_course_ids)
    subscription_status, payment_records = _get_subscription_and_payments(user, profile, enrollments)
    notifications = _get_student_notifications(user, enrollments, assignments, exams, grades)

    active_courses = [e for e in enrollments if e['is_active']]
    completed_courses = [e for e in enrollments if e['is_completed']]
    progress_vals = [e['progress'] for e in enrollments if e['progress'] is not None]
    overall_progress = round(sum(progress_vals) / len(progress_vals), 1) if progress_vals else None

    phone_number = getattr(user, 'phone', getattr(user, 'phone_number', None))
    avatar_url = None
    for obj in (profile, user):
        if obj is not None:
            for attr in ('avatar', 'profile_photo', 'photo', 'image'):
                img_field = getattr(obj, attr, None)
                if img_field and hasattr(img_field, 'url'):
                    try:
                        avatar_url = img_field.url
                        break
                    except Exception:
                        pass

    active_tab = request.GET.get('tab', 'overview').strip()

    context = {
        'active_tab': active_tab,
        'student_full_name': _get_user_display_name(user),
        'academy_student_id': _get_academy_student_id(user, profile),
        'phone_number': phone_number,
        'avatar_url': avatar_url,
        'current_term': active_courses[0]['term'] if active_courses else 'ترم جاری',
        'enrollment_status_label': 'فعال و در حال تحصیل' if active_courses else 'بدون کلاس فعال',
        'enrollments': enrollments,
        'active_courses': active_courses,
        'completed_courses': completed_courses,
        'overall_progress': overall_progress,
        'attendance_records': attendance_records,
        'attendance_summary': attendance_summary,
        'grades': grades,
        'gpa': gpa,
        'skills_analytics': skills_analytics,
        'has_any_skill_data': has_any_skill_data,
        'skill_strengths': strengths,
        'skill_improvements': improvements,
        'assignments': assignments,
        'pending_assignments_count': sum(1 for a in assignments if not a['is_submitted'] and not a['is_past_deadline']),
        'exams': exams,
        'sessions': sessions,
        'online_sessions': online_sessions,
        'resources': resources,
        'subscription_status': subscription_status,
        'payment_records': payment_records,
        'notifications': notifications,
    }
    return render(request, 'dashboards/student_dashboard.html', context)


@student_required
@require_http_methods(["GET"])
def student_course_detail_view(request, course_id):
    """صفحه اختصاصی جزئیات هر دوره برای زبان‌آموز با محافظت IDOR"""
    user = request.user
    profile = _get_student_profile(user)
    enrollments, authorized_course_ids = _get_student_enrollments(user, profile)

    if course_id not in authorized_course_ids and not user.is_superuser:
        return HttpResponseForbidden("شما به این دوره دسترسی ندارید.")

    course_enrollment = next((e for e in enrollments if e['course_id'] == course_id), None)
    if not course_enrollment:
        raise Http404("دوره یافت نشد.")

    attendance_records, _ = _get_student_attendance(user, profile, {course_id})
    grades, _, _, _, _, _ = _get_student_grades_and_skills(user, profile)
    assignments, exams = _get_assignments_and_exams(user, profile, {course_id})
    sessions, online_sessions, resources = _get_sessions_and_resources({course_id})

    context = {
        'student_full_name': _get_user_display_name(user),
        'academy_student_id': _get_academy_student_id(user, profile),
        'course': course_enrollment,
        'course_attendance': [r for r in attendance_records if r['course_id'] == course_id or r['course_id'] is None],
        'course_grades': [g for g in grades if g['course_id'] == course_id],
        'course_assignments': assignments,
        'course_exams': exams,
        'course_sessions': sessions,
        'course_online_sessions': online_sessions,
        'course_resources': resources,
    }
    return render(request, 'dashboards/student_course_detail.html', context)


@student_required
@require_http_methods(["GET"])
def protected_resource_download_view(request, resource_id):
    """دانلود امن منابع آموزشی"""
    user = request.user
    profile = _get_student_profile(user)
    _, authorized_course_ids = _get_student_enrollments(user, profile)

    ResourceModel = _find_first_model([('courses', 'CourseResource'), ('courses', 'Resource')])
    if not ResourceModel:
        raise Http404("منبع آموزشی یافت نشد.")

    resource = get_object_or_404(ResourceModel, pk=resource_id)
    if getattr(resource, 'course_id', None) not in authorized_course_ids and not user.is_superuser:
        return HttpResponseForbidden("مجوز دانلود این فایل را ندارید.")

    file_field = getattr(resource, 'file', None)
    if not file_field:
        raise Http404("فایل ضمیمه وجود ندارد.")

    return FileResponse(file_field.open('rb'), as_attachment=True, filename=os.path.basename(file_field.name))