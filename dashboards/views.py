import os
import logging
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.http import HttpResponseForbidden, Http404, FileResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q, Avg
from django.apps import apps
from django.utils import timezone

audit_logger = logging.getLogger('toranj.security')

ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.doc', '.docx', '.zip', '.jpg', '.jpeg', '.png', '.mp3'}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _get_model_safe(app_label, model_name):
    """بارگذاری ایمن مدل‌ها بدون ایجاد خطای ImportError در ساختارهای مختلف"""
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
    """دکوراتور امنیتی برای احراز هویت و کنترل دسترسی نقش زبان‌آموز"""
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        # نادیده گرفتن هرگونه user_id یا student_id ارسالی از سمت مرورگر (محافظت در برابر IDOR)
        if 'user_id' in request.GET or 'student_id' in request.GET:
            audit_logger.warning(
                f"Suspicious query param tampering by user={request.user.pk} IP={request.META.get('REMOTE_ADDR')}"
            )
        if not _is_student_user(request.user) and not request.user.is_superuser:
            audit_logger.warning(
                f"Unauthorized role access attempt to student dashboard by user={request.user.pk}"
            )
            return HttpResponseForbidden("دسترسی غیرمجاز: این بخش ویژه زبان‌آموزان است.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


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
    return f"TRJ-{user.date_joined.strftime('%Y')}-{user.pk:04d}"


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
                        teacher_name = (
                            teacher_obj.get_full_name() or teacher_obj.username
                            if hasattr(teacher_obj, 'username') else str(teacher_obj or 'تعیین‌نشده در سامانه')
                        )
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
                            'enrolled_at': getattr(item, 'created_at', getattr(item, 'enrolled_at', getattr(item, 'date_joined', None))),
                            'is_active': not is_completed and status_raw in ('active', 'approved', 'enrolled', 'true'),
                            'is_completed': is_completed,
                        })
        except Exception as exc:
            audit_logger.debug(f"Enrollment query notice: {exc}")

    # بررسی فیلد ManyToMany مستقیم در مدل Course در صورت وجود
    CourseModel = _get_model_safe('courses', 'Course')
    if CourseModel and not enrollments:
        try:
            field_names = [f.name for f in CourseModel._meta.get_fields()]
            if 'students' in field_names:
                for c in CourseModel.objects.filter(students=user):
                    authorized_course_ids.add(c.pk)
                    teacher_obj = getattr(c, 'teacher', getattr(c, 'instructor', None))
                    teacher_name = (
                        teacher_obj.get_full_name() or teacher_obj.username
                        if hasattr(teacher_obj, 'username') else str(teacher_obj or 'تعیین‌نشده')
                    )
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
    summary = {
        'total': 0,
        'present': 0,
        'absent': 0,
        'late': 0,
        'excused': 0,
        'percentage': None,
    }

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
            if 'enrollment__student' in field_names or 'enrollment' in field_names:
                try:
                    q_filter |= Q(enrollment__student=user)
                except Exception:
                    pass

            if q_filter:
                qs = AttendanceModel.objects.filter(q_filter).order_by('-id')
                for r in qs:
                    status_val = str(getattr(r, 'status', '')).lower()
                    is_present_bool = getattr(r, 'is_present', None)
                    if status_val in ('present', 'حاضر') or is_present_bool is True:
                        norm_status = 'present'
                        status_fa = 'حاضر'
                        summary['present'] += 1
                    elif status_val in ('late', 'تاخیر', 'تأخیر'):
                        norm_status = 'late'
                        status_fa = 'تأخیر'
                        summary['late'] += 1
                    elif status_val in ('excused', 'موجه', 'غیبت موجه'):
                        norm_status = 'excused'
                        status_fa = 'غیبت موجه'
                        summary['excused'] += 1
                    else:
                        norm_status = 'absent'
                        status_fa = 'غایب'
                        summary['absent'] += 1

                    summary['total'] += 1
                    course_obj = getattr(r, 'course', getattr(getattr(r, 'session', None), 'course', None))
                    records.append({
                        'id': r.pk,
                        'course_id': getattr(course_obj, 'pk', None),
                        'course_title': getattr(course_obj, 'title', str(course_obj or 'جلسه آموزشی')),
                        'date': getattr(r, 'date', getattr(r, 'session_date', getattr(r, 'created_at', None))),
                        'session_title': getattr(r, 'session_title', str(getattr(r, 'session', 'جلسه کلاسی'))),
                        'status': norm_status,
                        'status_label': status_fa,
                        'note': getattr(r, 'note', getattr(r, 'remarks', '')),
                    })
        except Exception as exc:
            audit_logger.debug(f"Attendance query notice: {exc}")

    if summary['total'] > 0:
        effective_present = summary['present'] + (summary['late'] * 0.5) + summary['excused']
        summary['percentage'] = round((effective_present / summary['total']) * 100, 1)

    return records, summary


def _get_student_grades_and_skills(user, profile):
    """
    واکشی کارنامه و تحلیل ۶ مهارت زبانی:
    Speaking, Listening, Grammar, Vocabulary, Writing, Reading
    صرفاً بر اساس رکوردهای واقعی ثبت‌شده در دیتابیس (بدون هیچ نمره ساختگی).
    """
    GradeModel = _find_first_model([
        ('academics', 'Grade'),
        ('academics', 'Assessment'),
        ('academics', 'ReportCard'),
        ('academics', 'Score'),
        ('courses', 'Grade'),
    ])
    SkillModel = _find_first_model([
        ('academics', 'SkillAssessment'),
        ('academics', 'LanguageSkillScore'),
        ('academics', 'SkillScore'),
    ])

    grades_list = []
    skill_buckets = {
        'speaking': {'key': 'speaking', 'label_fa': 'مکالمه (Speaking)', 'label_en': 'Speaking', 'scores': [], 'feedback': []},
        'listening': {'key': 'listening', 'label_fa': 'مهارت شنیداری (Listening)', 'label_en': 'Listening', 'scores': [], 'feedback': []},
        'grammar': {'key': 'grammar', 'label_fa': 'ساختار و گرامر (Grammar)', 'label_en': 'Grammar', 'scores': [], 'feedback': []},
        'vocabulary': {'key': 'vocabulary', 'label_fa': 'دامنه واژگان (Vocabulary)', 'label_en': 'Vocabulary', 'scores': [], 'feedback': []},
        'writing': {'key': 'writing', 'label_fa': 'مهارت نگارش (Writing)', 'label_en': 'Writing', 'scores': [], 'feedback': []},
        'reading': {'key': 'reading', 'label_fa': 'درک مطلب (Reading)', 'label_en': 'Reading', 'scores': [], 'feedback': []},
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
                score_val = getattr(g, 'score', getattr(g, 'grade', getattr(g, 'total_score', None)))
                max_score = getattr(g, 'max_score', 100) or 100
                feedback_txt = getattr(g, 'teacher_feedback', getattr(g, 'feedback', getattr(g, 'comment', '')))
                term_txt = str(getattr(g, 'term', getattr(course_obj, 'term', 'ترم جاری')))
                grade_type = str(getattr(g, 'assessment_type', getattr(g, 'grade_type', 'ارزیابی آموزشی')))

                if score_val is not None:
                    try:
                        numeric_score = float(score_val)
                        normalized_100 = round((numeric_score / float(max_score)) * 100, 1) if float(max_score) > 0 else numeric_score
                    except (ValueError, TypeError):
                        numeric_score = None
                        normalized_100 = None
                else:
                    numeric_score = None
                    normalized_100 = None

                grades_list.append({
                    'id': g.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or 'ارزیابی عمومی')),
                    'term': term_txt,
                    'title': getattr(g, 'title', grade_type),
                    'type': grade_type,
                    'score': numeric_score,
                    'max_score': max_score,
                    'normalized_score': normalized_100,
                    'feedback': feedback_txt,
                    'date': getattr(g, 'created_at', getattr(g, 'date', None)),
                })

                # بررسی فیلدهای ۶ مهارت زبانی در رکورد واقعی دیتابیس
                for sk_key in skill_buckets.keys():
                    direct_skill_val = getattr(g, sk_key, getattr(g, f"{sk_key}_score", None))
                    if direct_skill_val is not None:
                        try:
                            skill_buckets[sk_key]['scores'].append(float(direct_skill_val))
                            if feedback_txt:
                                skill_buckets[sk_key]['feedback'].append(feedback_txt)
                        except (ValueError, TypeError):
                            pass

                skill_category = str(getattr(g, 'skill', getattr(g, 'skill_type', ''))).lower()
                if skill_category in skill_buckets and normalized_100 is not None:
                    skill_buckets[skill_category]['scores'].append(normalized_100)
                    if feedback_txt:
                        skill_buckets[skill_category]['feedback'].append(feedback_txt)
        except Exception as exc:
            audit_logger.debug(f"Grades/Skills query notice: {exc}")

    # بررسی فیلدهای مهارت در StudentProfile اگر به صورت مستقیم در پروفایل ذخیره شده باشند
    if profile is not None:
        for sk_key in skill_buckets.keys():
            prof_val = getattr(profile, f"{sk_key}_score", getattr(profile, sk_key, None))
            if isinstance(prof_val, (int, float)) and prof_val > 0:
                skill_buckets[sk_key]['scores'].append(float(prof_val))

    skills_analytics = []
    has_any_skill_data = False
    strengths = []
    improvements = []

    for sk_key, data in skill_buckets.items():
        scores = data['scores']
        if scores:
            has_any_skill_data = True
            avg_score = round(sum(scores) / len(scores), 1)
            previous_score = scores[1] if len(scores) > 1 else None
            delta = round(scores[0] - previous_score, 1) if previous_score is not None else None
            if avg_score >= 75:
                strengths.append(data['label_fa'])
            elif avg_score < 60:
                improvements.append(data['label_fa'])
        else:
            avg_score = None
            delta = None

        skills_analytics.append({
            'key': sk_key,
            'label_fa': data['label_fa'],
            'label_en': data['label_en'],
            'average': avg_score,
            'assessments_count': len(scores),
            'delta': delta,
            'latest_feedback': data['feedback'][0] if data['feedback'] else '',
        })

    valid_grade_scores = [item['normalized_score'] for item in grades_list if item['normalized_score'] is not None]
    gpa = round(sum(valid_grade_scores) / len(valid_grade_scores), 1) if valid_grade_scores else None

    return grades_list, gpa, skills_analytics, has_any_skill_data, strengths, improvements


def _get_assignments_and_exams(user, profile, authorized_course_ids):
    """واکشی تکالیف، پاسخ‌های ارسالی زبان‌آموز و آزمون‌ها"""
    AssignmentModel = _find_first_model([
        ('academics', 'Assignment'),
        ('courses', 'Assignment'),
        ('academics', 'Homework'),
    ])
    SubmissionModel = _find_first_model([
        ('academics', 'AssignmentSubmission'),
        ('academics', 'Submission'),
        ('courses', 'Submission'),
    ])
    ExamModel = _find_first_model([
        ('academics', 'Exam'),
        ('courses', 'Exam'),
        ('academics', 'Quiz'),
    ])

    assignments = []
    exams = []
    now = timezone.now()

    submissions_by_assignment = {}
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
                        submissions_by_assignment[a_id] = sub
        except Exception:
            pass

    if AssignmentModel and authorized_course_ids:
        try:
            for a in AssignmentModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                sub = submissions_by_assignment.get(a.pk)
                deadline = getattr(a, 'deadline', getattr(a, 'due_date', None))
                is_past_deadline = bool(deadline and deadline < now)
                course_obj = getattr(a, 'course', None)
                teacher_obj = getattr(course_obj, 'teacher', None)
                assignments.append({
                    'id': a.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'title': getattr(a, 'title', str(a)),
                    'description': getattr(a, 'description', ''),
                    'course_title': getattr(course_obj, 'title', ''),
                    'teacher_name': (
                        teacher_obj.get_full_name() or teacher_obj.username
                        if hasattr(teacher_obj, 'username') else 'استاد دوره'
                    ),
                    'deadline': deadline,
                    'is_past_deadline': is_past_deadline,
                    'is_submitted': sub is not None,
                    'submission_status': 'ارسال‌شده' if sub else ('مهلت پایان‌یافته' if is_past_deadline else 'در انتظار ارسال'),
                    'submitted_answer': getattr(sub, 'answer_text', getattr(sub, 'text', '')) if sub else '',
                    'submitted_file': getattr(sub, 'file', None) if sub else None,
                    'grade': getattr(sub, 'grade', getattr(sub, 'score', None)) if sub else None,
                    'feedback': getattr(sub, 'feedback', getattr(sub, 'teacher_feedback', '')) if sub else '',
                })
        except Exception:
            pass

    if ExamModel and authorized_course_ids:
        try:
            for ex in ExamModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                exam_date = getattr(ex, 'date', getattr(ex, 'exam_date', getattr(ex, 'start_time', None)))
                course_obj = getattr(ex, 'course', None)
                is_upcoming = bool(exam_date and exam_date >= now)
                exams.append({
                    'id': ex.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'title': getattr(ex, 'title', str(ex)),
                    'course_title': getattr(course_obj, 'title', ''),
                    'date': exam_date,
                    'is_upcoming': is_upcoming,
                    'status_label': 'آزمون پیش‌رو' if is_upcoming else 'برگزارشده',
                    'score': getattr(ex, 'score', None),
                    'feedback': getattr(ex, 'feedback', ''),
                })
        except Exception:
            pass

    return assignments, exams


def _get_sessions_and_resources(authorized_course_ids):
    """واکشی جلسات هفتگی، کلاس‌های آنلاین و منابع آموزشی دوره‌های مجاز زبان‌آموز"""
    SessionModel = _find_first_model([
        ('courses', 'ClassSession'),
        ('courses', 'Session'),
        ('academics', 'ClassSession'),
        ('academics', 'Schedule'),
    ])
    ResourceModel = _find_first_model([
        ('courses', 'CourseResource'),
        ('courses', 'Resource'),
        ('courses', 'Material'),
        ('academics', 'EducationalResource'),
    ])

    sessions = []
    online_sessions = []
    resources = []

    if SessionModel and authorized_course_ids:
        try:
            for s in SessionModel.objects.filter(course_id__in=authorized_course_ids).order_by('id'):
                course_obj = getattr(s, 'course', None)
                teacher_obj = getattr(course_obj, 'teacher', None)
                meeting_url = getattr(s, 'meeting_link', getattr(s, 'online_url', getattr(course_obj, 'meeting_link', '')))
                item = {
                    'id': s.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'title': getattr(s, 'title', f"جلسه {getattr(s, 'course', '')}"),
                    'course_title': getattr(course_obj, 'title', ''),
                    'language': getattr(course_obj, 'get_language_display', lambda: getattr(course_obj, 'language', ''))(),
                    'teacher_name': (
                        teacher_obj.get_full_name() or teacher_obj.username
                        if hasattr(teacher_obj, 'username') else 'استاد دوره'
                    ),
                    'date_time': getattr(s, 'start_time', getattr(s, 'date', getattr(s, 'day_of_week', ''))),
                    'room': getattr(s, 'room', getattr(s, 'classroom', 'کلاس حضوری / آنلاین')),
                    'meeting_url': meeting_url,
                    'status': getattr(s, 'status', 'برنامه‌ریزی‌شده'),
                }
                sessions.append(item)
                if meeting_url or getattr(s, 'is_online', False):
                    online_sessions.append(item)
        except Exception:
            pass

    if ResourceModel and authorized_course_ids:
        try:
            for res in ResourceModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                course_obj = getattr(res, 'course', None)
                file_obj = getattr(res, 'file', None)
                ext_link = getattr(res, 'url', getattr(res, 'link', ''))
                res_type = str(getattr(res, 'resource_type', 'PDF / آموزشی')).upper()
                resources.append({
                    'id': res.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'title': getattr(res, 'title', str(res)),
                    'description': getattr(res, 'description', ''),
                    'course_title': getattr(course_obj, 'title', ''),
                    'type': res_type,
                    'has_file': bool(file_obj),
                    'external_url': ext_link,
                    'created_at': getattr(res, 'created_at', None),
                })
        except Exception:
            pass

    return sessions, online_sessions, resources


def _get_subscription_and_payments(user, profile, enrollments):
    """
    واکشی وضعیت اشتراک و بررسی دستی پرداخت‌ها.
    طبق سیاست امنیتی تُرَنج: هیچ پرداختی به صورت خودکار دسترسی را فعال نمی‌کند؛
    فقط مدیریت آموزشگاه پس از بررسی، دسترسی را تایید می‌نماید.
    """
    SubModel = _find_first_model([
        ('academics', 'Subscription'),
        ('accounts', 'Subscription'),
        ('courses', 'Subscription'),
        ('academics', 'PaymentRequest'),
        ('courses', 'Payment'),
    ])
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
                        'title': getattr(item, 'title', str(getattr(item, 'course', 'اشتراک آموزشی'))),
                        'start_date': getattr(item, 'start_date', getattr(item, 'created_at', None)),
                        'end_date': getattr(item, 'end_date', getattr(item, 'expires_at', None)),
                        'status': status_raw,
                        'status_label': (
                            'تأییدشده توسط آموزشگاه' if status_raw in ('approved', 'active', 'verified')
                            else ('در انتظار بررسی واحد مالی' if status_raw == 'pending' else 'منقضی / ردشده')
                        ),
                        'reference': getattr(item, 'tracking_code', getattr(item, 'reference_code', '')),
                    })
        except Exception:
            pass

    active_courses_count = sum(1 for e in enrollments if e['is_active'])
    overall_status = 'فعال (تأییدشده توسط آموزشگاه)' if active_courses_count > 0 else 'در انتظار ثبت‌نام / تأیید مدیریت'
    return overall_status, records


def _get_student_notifications(user, enrollments, assignments, exams, grades):
    """واکشی اعلان‌های واقعی از دیتابیس و رویدادهای واقعی تحصیلی زبان‌آموز"""
    NotifModel = _find_first_model([
        ('dashboards', 'Notification'),
        ('accounts', 'Notification'),
        ('academics', 'Notification'),
        ('core', 'Notification'),
    ])
    notifications = []

    if NotifModel:
        try:
            field_names = [f.name for f in NotifModel._meta.get_fields()]
            q_filter = Q()
            if 'user' in field_names:
                q_filter |= Q(user=user)
            if 'recipient' in field_names:
                q_filter |= Q(recipient=user)
            if 'student' in field_names:
                q_filter |= Q(student=user)
            if q_filter:
                for n in NotifModel.objects.filter(q_filter).order_by('-id')[:15]:
                    notifications.append({
                        'title': getattr(n, 'title', 'اعلان سیستم'),
                        'message': getattr(n, 'message', getattr(n, 'body', str(n))),
                        'date': getattr(n, 'created_at', None),
                        'category': 'سیستمی',
                    })
        except Exception:
            pass

    # افزودن اعلان‌های مبتنی بر رکوردهای واقعی زبان‌آموز
    for a in assignments[:3]:
        if not a['is_submitted'] and not a['is_past_deadline']:
            notifications.append({
                'title': f"تکلیف در انتظار ارسال: {a['title']}",
                'message': f"دوره {a['course_title']} — لطفاً پیش از پایان مهلت، پاسخ خود را ارسال نمایید.",
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

    for g in grades[:3]:
        if g['score'] is not None:
            notifications.append({
                'title': f"ثبت نمره جدید در {g['course_title']}",
                'message': f"ارزیابی «{g['title']}» با نمره {g['score']} از {g['max_score']} ثبت شد.",
                'date': g['date'],
                'category': 'کارنامه',
            })

    return notifications


def _validate_uploaded_file(uploaded_file):
    """بررسی امنیتی پسوند، نام و حجم فایل آپلودی"""
    if not uploaded_file:
        return True, None
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, f"پسوند فایل ({ext}) مجاز نیست. فرمت‌های مجاز: PDF, Word, ZIP, JPG, PNG, MP3"
    if uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
        return False, "حجم فایل انتخاب‌شده بیش از حد مجاز (۱۰ مگابایت) است."
    uploaded_file.name = os.path.basename(uploaded_file.name)
    return True, None


@login_required
def dashboard_router_view(request):
    """مسیردهی هوشمند کاربر به داشبورد مربوط به نقش خود (حفظ عملکرد اساتید و ادمین)"""
    user = request.user
    role = str(getattr(user, 'role', '')).lower()
    if getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'):
        for tpl in ('dashboards/teacher_dashboard.html', 'dashboards/teacher.html'):
            try:
                return render(request, tpl, {'user': user})
            except Exception:
                continue
    return redirect('dashboards:student_dashboard')


@student_required
@require_http_methods(["GET", "POST"])
def student_dashboard_view(request):
    """ویوی جامع داشبورد پریمیوم زبان‌آموز با پشتیبانی از عملیات امن POST"""
    user = request.user
    profile = _get_student_profile(user)
    enrollments, authorized_course_ids = _get_student_enrollments(user, profile)

    # پردازش فرم‌های ارسالی (POST) با محافظت کامل در برابر دستکاری فیلدهای حساس
    if request.method == 'POST':
        action = request.POST.get('form_action', '').strip()

        # ۱. بروزرسانی اطلاعات مجاز پروفایل (نام، نام خانوادگی، ایمیل و تصویر پروفایل)
        if action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()[:50]
            last_name = request.POST.get('last_name', '').strip()[:50]
            email = request.POST.get('email', '').strip()[:120]
            avatar_file = request.FILES.get('avatar')

            is_valid_file, file_err = _validate_uploaded_file(avatar_file)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect('/dashboards/student/?tab=profile')

            with transaction.atomic():
                user.first_name = first_name
                user.last_name = last_name
                if email:
                    user.email = email
                user.save(update_fields=['first_name', 'last_name', 'email'])

                if avatar_file and profile is not None:
                    for field_attr in ('avatar', 'profile_photo', 'photo', 'image'):
                        if hasattr(profile, field_attr):
                            setattr(profile, field_attr, avatar_file)
                            profile.save()
                            break

                audit_logger.info(f"Student profile updated safely by user={user.pk}")
                messages.success(request, "اطلاعات پروفایل شما با موفقیت به‌روزرسانی شد.")
            return redirect('/dashboards/student/?tab=profile')

        # ۲. تغییر رمز عبور زبان‌آموز با حفظ نشست امن
        elif action == 'change_password':
            pwd_form = PasswordChangeForm(user=user, data=request.POST)
            if pwd_form.is_valid():
                with transaction.atomic():
                    pwd_form.save()
                    update_session_auth_hash(request, pwd_form.user)
                    audit_logger.info(f"Password changed successfully by user={user.pk}")
                    messages.success(request, "رمز عبور شما با موفقیت تغییر یافت.")
            else:
                for err_list in pwd_form.errors.values():
                    for err in err_list:
                        messages.error(request, err)
            return redirect('/dashboards/student/?tab=profile')

        # ۳. ارسال پاسخ یا فایل تکلیف (با بررسی عضویت در دوره و مهلت ارسال در سرور)
        elif action == 'submit_assignment':
            assignment_id = request.POST.get('assignment_id')
            answer_text = request.POST.get('answer_text', '').strip()[:5000]
            submission_file = request.FILES.get('submission_file')

            is_valid_file, file_err = _validate_uploaded_file(submission_file)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect('/dashboards/student/?tab=assignments')

            AssignmentModel = _find_first_model([('academics', 'Assignment'), ('courses', 'Assignment')])
            SubmissionModel = _find_first_model([('academics', 'AssignmentSubmission'), ('academics', 'Submission'), ('courses', 'Submission')])

            if not AssignmentModel or not SubmissionModel:
                messages.error(request, "ماژول ثبت تکالیف در حال حاضر برای این دوره فعال نیست.")
                return redirect('/dashboards/student/?tab=assignments')

            assignment_obj = get_object_or_404(AssignmentModel, pk=assignment_id)
            if getattr(assignment_obj, 'course_id', None) not in authorized_course_ids:
                audit_logger.warning(f"IDOR blocked: user={user.pk} tried submitting assignment={assignment_id}")
                return HttpResponseForbidden("شما مجوز ارسال تکلیف برای این دوره را ندارید.")

            deadline = getattr(assignment_obj, 'deadline', getattr(assignment_obj, 'due_date', None))
            if deadline and deadline < timezone.now():
                messages.error(request, "مهلت ارسال این تکلیف به پایان رسیده است.")
                return redirect('/dashboards/student/?tab=assignments')

            with transaction.atomic():
                sub_fields = [f.name for f in SubmissionModel._meta.get_fields()]
                lookup = {'assignment': assignment_obj}
                if 'student' in sub_fields:
                    rel_model = SubmissionModel._meta.get_field('student').related_model
                    lookup['student'] = user if rel_model == user.__class__ else profile
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
                audit_logger.info(f"Assignment {assignment_id} submitted by user={user.pk}")
                messages.success(request, "پاسخ تکلیف شما با موفقیت ثبت شد و در انتظار بررسی استاد است.")
            return redirect('/dashboards/student/?tab=assignments')

        # ۴. ثبت درخواست بررسی فیش پرداخت (بدون فعال‌سازی خودکار اشتراک)
        elif action == 'submit_payment_claim':
            reference_code = request.POST.get('reference_code', '').strip()[:100]
            course_note = request.POST.get('course_note', '').strip()[:500]
            if not reference_code:
                messages.error(request, "لطفاً شماره پیگیری یا مشخصات فیش واریزی را وارد نمایید.")
                return redirect('/dashboards/student/?tab=subscription')

            SubModel = _find_first_model([
                ('academics', 'PaymentRequest'),
                ('academics', 'Subscription'),
                ('courses', 'Payment'),
            ])
            with transaction.atomic():
                if SubModel:
                    try:
                        f_names = [f.name for f in SubModel._meta.get_fields()]
                        create_kwargs = {}
                        if 'user' in f_names:
                            create_kwargs['user'] = user
                        elif 'student' in f_names:
                            rel_m = SubModel._meta.get_field('student').related_model
                            create_kwargs['student'] = user if rel_m == user.__class__ else profile
                        if 'status' in f_names:
                            create_kwargs['status'] = 'pending'  # هرگز به صورت خودکار approved نمی‌شود
                        if 'tracking_code' in f_names:
                            create_kwargs['tracking_code'] = reference_code
                        elif 'reference_code' in f_names:
                            create_kwargs['reference_code'] = reference_code
                        if 'title' in f_names and course_note:
                            create_kwargs['title'] = course_note
                        SubModel.objects.create(**create_kwargs)
                    except Exception as exc:
                        audit_logger.warning(f"Payment claim model save notice: {exc}")

                audit_logger.info(
                    f"Manual payment verification request submitted by user={user.pk} ref={reference_code} (Status=PENDING)"
                )
                messages.success(
                    request,
                    "مشخصات پرداخت شما با وضعیت «در انتظار بررسی واحد آموزش» ثبت شد. پس از تایید دستی توسط مدیریت، دسترسی دوره فعال خواهد شد."
                )
            return redirect('/dashboards/student/?tab=subscription')

    # واکشی تمامی بخش‌ها صرفاً برای زبان‌آموز احراز هویت‌شده
    attendance_records, attendance_summary = _get_student_attendance(user, profile, authorized_course_ids)
    grades, gpa, skills_analytics, has_any_skill_data, strengths, improvements = _get_student_grades_and_skills(user, profile)
    assignments, exams = _get_assignments_and_exams(user, profile, authorized_course_ids)
    sessions, online_sessions, resources = _get_sessions_and_resources(authorized_course_ids)
    subscription_status, payment_records = _get_subscription_and_payments(user, profile, enrollments)
    notifications = _get_student_notifications(user, enrollments, assignments, exams, grades)

    active_courses = [e for e in enrollments if e['is_active']]
    completed_courses = [e for e in enrollments if e['is_completed']]

    # محاسبه میانگین پیشرفت واقعی
    progress_values = [e['progress'] for e in enrollments if e['progress'] is not None]
    overall_progress = round(sum(progress_values) / len(progress_values), 1) if progress_values else None

    # دریافت شماره تماس و تصویر پروفایل واقعی
    phone_number = getattr(user, 'phone_number', getattr(user, 'phone', getattr(profile, 'phone_number', getattr(profile, 'phone', None))))
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
        'student_full_name': user.get_full_name().strip() or user.username,
        'academy_student_id': _get_academy_student_id(user, profile),
        'phone_number': phone_number,
        'avatar_url': avatar_url,
        'current_term': active_courses[0]['term'] if active_courses else 'ثبت‌نشده در ترم جاری',
        'enrollment_status_label': 'فعال و در حال تحصیل' if active_courses else 'بدون کلاس فعال در ترم جاری',
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
    """
    صفحه اختصاصی جزئیات هر دوره برای زبان‌آموز.
    دارای محافظت سخت‌گیرانه IDOR: فقط در صورتی باز می‌شود که زبان‌آموز در آن دوره ثبت‌نام شده باشد.
    """
    user = request.user
    profile = _get_student_profile(user)
    enrollments, authorized_course_ids = _get_student_enrollments(user, profile)

    if course_id not in authorized_course_ids and not user.is_superuser:
        audit_logger.warning(
            f"IDOR blocked: user={user.pk} attempted unauthorized access to course_id={course_id}"
        )
        return HttpResponseForbidden("شما به این دوره آموزشی دسترسی ندارید (نیاز به ثبت‌نام فعال در دوره).")

    course_enrollment = next((e for e in enrollments if e['course_id'] == course_id), None)
    if not course_enrollment:
        raise Http404("دوره مورد نظر یافت نشد.")

    attendance_records, _ = _get_student_attendance(user, profile, {course_id})
    course_attendance = [r for r in attendance_records if r['course_id'] == course_id or r['course_id'] is None]

    grades, _, _, _, _, _ = _get_student_grades_and_skills(user, profile)
    course_grades = [g for g in grades if g['course_id'] == course_id]

    assignments, exams = _get_assignments_and_exams(user, profile, {course_id})
    sessions, online_sessions, resources = _get_sessions_and_resources({course_id})

    context = {
        'student_full_name': user.get_full_name().strip() or user.username,
        'academy_student_id': _get_academy_student_id(user, profile),
        'course': course_enrollment,
        'course_attendance': course_attendance,
        'course_grades': course_grades,
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
    """دانلود امن منابع آموزشی پس از بررسی مجوز ثبت‌نام زبان‌آموز در دوره مربوطه"""
    user = request.user
    profile = _get_student_profile(user)
    _, authorized_course_ids = _get_student_enrollments(user, profile)

    ResourceModel = _find_first_model([
        ('courses', 'CourseResource'),
        ('courses', 'Resource'),
        ('courses', 'Material'),
        ('academics', 'EducationalResource'),
    ])
    if not ResourceModel:
        raise Http404("منبع آموزشی یافت نشد.")

    resource = get_object_or_404(ResourceModel, pk=resource_id)
    course_id = getattr(resource, 'course_id', None)

    if course_id not in authorized_course_ids and not user.is_superuser:
        audit_logger.warning(
            f"Unauthorized resource download blocked: user={user.pk} resource={resource_id}"
        )
        return HttpResponseForbidden("شما مجوز دانلود فایل‌های این دوره را ندارید.")

    file_field = getattr(resource, 'file', None)
    if not file_field:
        raise Http404("فایل ضمیمه برای این منبع ثبت نشده است.")

    audit_logger.info(f"Authorized resource download: user={user.pk} resource={resource_id}")
    return FileResponse(file_field.open('rb'), as_attachment=True, filename=os.path.basename(file_field.name))