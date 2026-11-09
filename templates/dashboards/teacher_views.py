import os
import csv
import logging
from functools import wraps
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash, get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.http import HttpResponseForbidden, Http404, FileResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.db.models import Q
from django.apps import apps
from django.utils import timezone

audit_logger = logging.getLogger('toranj.security')

ALLOWED_UPLOAD_EXTENSIONS = {'.pdf', '.doc', '.docx', '.zip', '.jpg', '.jpeg', '.png', '.mp3'}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def _get_model_safe(app_label, model_name):
    """بارگذاری ایمن مدل‌ها از اپ‌های پروژه"""
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


def _find_first_model(candidates):
    """یافتن اولین مدل موجود در ساختار فعلی پروژه"""
    for app_label, model_name in candidates:
        model = _get_model_safe(app_label, model_name)
        if model is not None:
            return model
    return None


def _is_teacher_user(user):
    """بررسی دقیق نقش استاد از روی نشست سمت سرور (Server-Side Session)"""
    if not user.is_authenticated:
        return False
    role = str(getattr(user, 'role', '')).lower()
    if getattr(user, 'is_teacher', False) or role in ('teacher', 'instructor', 'استاد'):
        return True
    return False


def teacher_required(view_func):
    """
    دکوراتور امنیتی ویژه اساتید:
    - جلوگیری از ورود کاربران غیرلاگین (302)
    - جلوگیری از ورود زبان‌آموزان به پنل استاد (403 Forbidden)
    - نادیده گرفتن کامل teacher_id یا user_id ارسالی از مرورگر (ضد IDOR)
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if 'teacher_id' in request.GET or 'teacher_id' in request.POST:
            audit_logger.warning(
                f"Suspicious teacher_id parameter tampering by user={request.user.pk}"
            )
        if not _is_teacher_user(request.user) and not request.user.is_superuser:
            audit_logger.warning(
                f"Unauthorized access attempt to teacher dashboard by user={request.user.pk}"
            )
            return HttpResponseForbidden("دسترسی غیرمجاز: این بخش صرفاً ویژه اساتید آموزشگاه زبان تُرَنج است.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def _get_user_display_name(user):
    """استخراج نام کامل یا شماره موبایل کاربر بدون خطا در مدل‌های سفارشی"""
    if user is None:
        return 'نامشخص'
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


def _get_teacher_profile(user):
    """واکشی پروفایل استاد در صورت وجود در دیتابیس"""
    ProfileModel = _find_first_model([
        ('academics', 'TeacherProfile'),
        ('accounts', 'TeacherProfile'),
        ('accounts', 'Profile'),
    ])
    if ProfileModel:
        try:
            return ProfileModel.objects.filter(user=user).first()
        except Exception:
            pass
    return None


def _get_teacher_academy_id(user, profile):
    """دریافت کد اختصاصی استاد از دیتابیس"""
    for obj in (profile, user):
        if obj is not None:
            for attr in ('teacher_id', 'employee_id', 'academy_id', 'code', 'national_id'):
                val = getattr(obj, attr, None)
                if val:
                    return str(val)
    year_str = user.date_joined.strftime('%Y') if hasattr(user, 'date_joined') and user.date_joined else '2026'
    return f"TRJ-TCH-{year_str}-{user.pk:03d}"


def _validate_uploaded_file(uploaded_file):
    """اعتبارسنجی امنیتی پسوند، حجم و نام فایل آپلودی"""
    if not uploaded_file:
        return True, None
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, f"پسوند فایل ({ext}) مجاز نیست. فرمت‌های مجاز: PDF, Word, ZIP, JPG, PNG, MP3"
    if uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
        return False, "حجم فایل انتخاب‌شده بیش از حد مجاز (۱۰ مگابایت) است."
    uploaded_file.name = os.path.basename(uploaded_file.name)
    return True, None


def _get_teacher_courses(user, profile):
    """
    واکشی صرفاً کلاس‌ها و دوره‌هایی که در دیتابیس به این استاد اختصاص داده شده‌اند.
    """
    CourseModel = _find_first_model([
        ('courses', 'Course'),
        ('academics', 'Course'),
        ('academics', 'ClassGroup'),
    ])
    courses_list = []
    authorized_course_ids = set()
    assigned_departments = set()

    if CourseModel:
        try:
            field_names = [f.name for f in CourseModel._meta.get_fields()]
            q_filter = Q()
            for f_name in ('teacher', 'instructor', 'professor', 'owner'):
                if f_name in field_names:
                    rel_model = CourseModel._meta.get_field(f_name).related_model
                    if rel_model == user.__class__:
                        q_filter |= Q(**{f_name: user})
                    elif profile is not None and rel_model == profile.__class__:
                        q_filter |= Q(**{f_name: profile})

            if q_filter:
                qs = CourseModel.objects.filter(q_filter).order_by('-id')
                for c in qs:
                    authorized_course_ids.add(c.pk)
                    lang_label = getattr(c, 'get_language_display', lambda: getattr(c, 'language', 'زبان عمومی'))()
                    if lang_label:
                        assigned_departments.add(str(lang_label))

                    status_raw = str(getattr(c, 'status', 'active')).lower()
                    is_active = getattr(c, 'is_active', True) and status_raw not in ('completed', 'archived', 'finished', 'false')

                    courses_list.append({
                        'id': c.pk,
                        'title': getattr(c, 'title', getattr(c, 'name', str(c))),
                        'language': str(lang_label or 'عمومی'),
                        'level': str(getattr(c, 'level', 'CEFR')),
                        'term': str(getattr(c, 'term', 'ترم جاری')),
                        'schedule': str(getattr(c, 'schedule', getattr(c, 'class_days', 'طبق تقویم آموزشی'))),
                        'room': str(getattr(c, 'room', getattr(c, 'classroom', 'حضوری / آنلاین'))),
                        'is_active': is_active,
                        'status_label': 'در حال برگزاری' if is_active else 'پایان‌یافته / قبلی',
                        'students_count': 0,
                    })
        except Exception as exc:
            audit_logger.debug(f"Teacher course query notice: {exc}")

    return courses_list, authorized_course_ids, sorted(assigned_departments)


def _get_authorized_students(authorized_course_ids, courses_list, search_q='', course_filter='', level_filter=''):
    """
    واکشی زبان‌آموزانی که منحصراً در کلاس‌هایِ مجازِ این استاد ثبت‌نام کرده‌اند.
    استاد هرگز به زبان‌آموزان خارج از کلاس‌های خود دسترسی ندارد.
    """
    EnrollmentModel = _find_first_model([
        ('courses', 'Enrollment'),
        ('academics', 'Enrollment'),
        ('academics', 'CourseEnrollment'),
    ])
    CourseModel = _get_model_safe('courses', 'Course')

    students_map = {}
    course_student_counts = {cid: 0 for cid in authorized_course_ids}
    course_lookup = {c['id']: c for c in courses_list}

    if EnrollmentModel and authorized_course_ids:
        try:
            qs = EnrollmentModel.objects.filter(course_id__in=authorized_course_ids).select_related('course')
            for enr in qs:
                student_obj = getattr(enr, 'student', getattr(enr, 'user', None))
                if student_obj is None:
                    continue
                student_user = getattr(student_obj, 'user', student_obj)
                s_pk = student_user.pk
                c_id = getattr(enr, 'course_id', None)
                c_info = course_lookup.get(c_id, {})

                if c_id in course_student_counts:
                    course_student_counts[c_id] += 1

                if s_pk not in students_map:
                    year_str = student_user.date_joined.strftime('%Y') if hasattr(student_user, 'date_joined') and student_user.date_joined else '2026'
                    academy_id = getattr(student_obj, 'student_id', getattr(student_user, 'student_id', f"TRJ-{year_str}-{s_pk:04d}"))
                    students_map[s_pk] = {
                        'id': s_pk,
                        'user_obj': student_user,
                        'profile_obj': student_obj if student_obj != student_user else None,
                        'full_name': _get_user_display_name(student_user),
                        'phone': getattr(student_user, 'phone', getattr(student_user, 'username', '')),
                        'academy_id': str(academy_id),
                        'enrolled_courses': [],
                        'course_ids': set(),
                        'levels': set(),
                        'current_term': c_info.get('term', 'ترم جاری'),
                        'progress': getattr(enr, 'progress', None),
                        'attendance_percentage': None,
                        'average_grade': None,
                        'latest_feedback': '',
                    }
                students_map[s_pk]['enrolled_courses'].append(c_info.get('title', str(getattr(enr, 'course', ''))))
                if c_id:
                    students_map[s_pk]['course_ids'].add(c_id)
                if c_info.get('level'):
                    students_map[s_pk]['levels'].add(c_info['level'])
        except Exception as exc:
            audit_logger.debug(f"Teacher student enrollment query notice: {exc}")

    # پشتیبانی از حالت ManyToMany مستقیم در مدل Course
    if CourseModel and authorized_course_ids and not students_map:
        try:
            field_names = [f.name for f in CourseModel._meta.get_fields()]
            if 'students' in field_names:
                for c in CourseModel.objects.filter(pk__in=authorized_course_ids).prefetch_related('students'):
                    c_info = course_lookup.get(c.pk, {})
                    for student_user in c.students.all():
                        s_pk = student_user.pk
                        course_student_counts[c.pk] = course_student_counts.get(c.pk, 0) + 1
                        if s_pk not in students_map:
                            students_map[s_pk] = {
                                'id': s_pk,
                                'user_obj': student_user,
                                'profile_obj': None,
                                'full_name': _get_user_display_name(student_user),
                                'phone': getattr(student_user, 'phone', getattr(student_user, 'username', '')),
                                'academy_id': f"TRJ-2026-{s_pk:04d}",
                                'enrolled_courses': [],
                                'course_ids': set(),
                                'levels': set(),
                                'current_term': c_info.get('term', 'ترم جاری'),
                                'progress': None,
                                'attendance_percentage': None,
                                'average_grade': None,
                                'latest_feedback': '',
                            }
                        students_map[s_pk]['enrolled_courses'].append(c_info.get('title', str(c)))
                        students_map[s_pk]['course_ids'].add(c.pk)
                        if c_info.get('level'):
                            students_map[s_pk]['levels'].add(c_info['level'])
        except Exception:
            pass

    for c in courses_list:
        c['students_count'] = course_student_counts.get(c['id'], 0)

    authorized_student_ids = set(students_map.keys())
    all_students = list(students_map.values())

    # اعمال فیلترها و جستجوی سمت سرور
    filtered_students = []
    for st in all_students:
        if search_q:
            q_low = search_q.lower()
            haystack = f"{st['full_name']} {st['academy_id']} {st['phone']} {' '.join(st['enrolled_courses'])}".lower()
            if q_low not in haystack:
                continue
        if course_filter and course_filter.isdigit():
            if int(course_filter) not in st['course_ids']:
                continue
        if level_filter:
            if not any(level_filter.lower() == lvl.lower() for lvl in st['levels']):
                continue
        filtered_students.append(st)

    return all_students, filtered_students, authorized_student_ids, students_map


def _get_teacher_grades_and_analytics(authorized_course_ids, students_map):
    """
    واکشی نمرات، کارنامه‌ها و تحلیل ۶ مهارت زبانی:
    1. Speaking  2. Listening  3. Grammar  4. Vocabulary  5. Writing  6. Reading
    صرفاً بر اساس رکوردهای واقعی ثبت‌شده در دیتابیس (بدون هیچ‌گونه عددسازی).
    """
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
        'speaking': {'key': 'speaking', 'label_fa': 'مکالمه (Speaking)', 'label_en': 'Speaking', 'scores': []},
        'listening': {'key': 'listening', 'label_fa': 'شنیداری (Listening)', 'label_en': 'Listening', 'scores': []},
        'grammar': {'key': 'grammar', 'label_fa': 'گرامر (Grammar)', 'label_en': 'Grammar', 'scores': []},
        'vocabulary': {'key': 'vocabulary', 'label_fa': 'واژگان (Vocabulary)', 'label_en': 'Vocabulary', 'scores': []},
        'writing': {'key': 'writing', 'label_fa': 'نگارش (Writing)', 'label_en': 'Writing', 'scores': []},
        'reading': {'key': 'reading', 'label_fa': 'درک مطلب (Reading)', 'label_en': 'Reading', 'scores': []},
    }
    student_scores_acc = {s_id: [] for s_id in students_map.keys()}

    for model in filter(None, [GradeModel, SkillModel]):
        if not authorized_course_ids:
            break
        try:
            field_names = [f.name for f in model._meta.get_fields()]
            if 'course' not in field_names:
                continue

            for g in model.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                student_obj = getattr(g, 'student', getattr(g, 'user', None))
                student_user = getattr(student_obj, 'user', student_obj)
                s_pk = getattr(student_user, 'pk', None)
                course_obj = getattr(g, 'course', None)

                score_val = getattr(g, 'score', getattr(g, 'grade', getattr(g, 'total_score', None)))
                max_score = getattr(g, 'max_score', 100) or 100
                feedback_txt = getattr(g, 'teacher_feedback', getattr(g, 'feedback', getattr(g, 'comment', '')))
                term_txt = str(getattr(g, 'term', getattr(course_obj, 'term', 'ترم جاری')))
                title_txt = str(getattr(g, 'title', getattr(g, 'assessment_type', 'ارزیابی آموزشی')))

                numeric_score = None
                normalized_100 = None
                if score_val is not None:
                    try:
                        numeric_score = float(score_val)
                        normalized_100 = round((numeric_score / float(max_score)) * 100, 1) if float(max_score) > 0 else numeric_score
                    except (ValueError, TypeError):
                        pass

                if s_pk in student_scores_acc and normalized_100 is not None:
                    student_scores_acc[s_pk].append(normalized_100)
                if s_pk in students_map and feedback_txt and not students_map[s_pk]['latest_feedback']:
                    students_map[s_pk]['latest_feedback'] = feedback_txt

                grades_list.append({
                    'id': g.pk,
                    'student_id': s_pk,
                    'student_name': students_map.get(s_pk, {}).get('full_name', _get_user_display_name(student_user)),
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or '')),
                    'term': term_txt,
                    'title': title_txt,
                    'score': numeric_score,
                    'max_score': max_score,
                    'normalized_score': normalized_100,
                    'feedback': feedback_txt,
                    'updated_at': getattr(g, 'updated_at', getattr(g, 'created_at', getattr(g, 'date', None))),
                })

                # بررسی فیلدهای ۶ مهارت زبانی در رکورد واقعی دیتابیس
                for sk_key in skill_buckets.keys():
                    direct_val = getattr(g, sk_key, getattr(g, f"{sk_key}_score", None))
                    if direct_val is not None:
                        try:
                            skill_buckets[sk_key]['scores'].append(float(direct_val))
                        except (ValueError, TypeError):
                            pass

                skill_cat = str(getattr(g, 'skill', getattr(g, 'skill_type', ''))).lower()
                if skill_cat in skill_buckets and normalized_100 is not None:
                    skill_buckets[skill_cat]['scores'].append(normalized_100)
        except Exception as exc:
            audit_logger.debug(f"Teacher grades query notice: {exc}")

    for s_pk, sc_list in student_scores_acc.items():
        if sc_list and s_pk in students_map:
            students_map[s_pk]['average_grade'] = round(sum(sc_list) / len(sc_list), 1)

    skills_analytics = []
    has_skill_data = False
    areas_needing_improvement = []

    for sk_key, bucket in skill_buckets.items():
        scores = bucket['scores']
        if scores:
            has_skill_data = True
            avg_val = round(sum(scores) / len(scores), 1)
            if avg_val < 65:
                areas_needing_improvement.append(bucket['label_fa'])
        else:
            avg_val = None

        skills_analytics.append({
            'key': sk_key,
            'label_fa': bucket['label_fa'],
            'label_en': bucket['label_en'],
            'average': avg_val,
            'count': len(scores),
        })

    return grades_list, skills_analytics, has_skill_data, areas_needing_improvement


def _get_teacher_assignments_and_exams(authorized_course_ids, students_map):
    """واکشی تکالیف، پاسخ‌های ارسالی زبان‌آموزان و آزمون‌های کلاس‌های استاد"""
    AssignmentModel = _find_first_model([('academics', 'Assignment'), ('courses', 'Assignment')])
    SubmissionModel = _find_first_model([('academics', 'AssignmentSubmission'), ('academics', 'Submission'), ('courses', 'Submission')])
    ExamModel = _find_first_model([('academics', 'Exam'), ('courses', 'Exam')])

    assignments = []
    submissions = []
    exams = []
    pending_grading_count = 0

    if AssignmentModel and authorized_course_ids:
        try:
            for a in AssignmentModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                course_obj = getattr(a, 'course', None)
                assignments.append({
                    'id': a.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or '')),
                    'title': getattr(a, 'title', str(a)),
                    'description': getattr(a, 'description', ''),
                    'deadline': getattr(a, 'deadline', getattr(a, 'due_date', None)),
                    'has_attachment': bool(getattr(a, 'file', getattr(a, 'attachment', None))),
                })
        except Exception:
            pass

    if SubmissionModel and authorized_course_ids:
        try:
            for sub in SubmissionModel.objects.filter(assignment__course_id__in=authorized_course_ids).select_related('assignment').order_by('-id'):
                st_obj = getattr(sub, 'student', getattr(sub, 'user', None))
                st_user = getattr(st_obj, 'user', st_obj)
                s_pk = getattr(st_user, 'pk', None)
                grade_val = getattr(sub, 'grade', getattr(sub, 'score', None))
                if grade_val is None:
                    pending_grading_count += 1
                submissions.append({
                    'id': sub.pk,
                    'assignment_id': getattr(sub, 'assignment_id', None),
                    'assignment_title': getattr(sub.assignment, 'title', 'تکلیف'),
                    'course_title': getattr(getattr(sub.assignment, 'course', None), 'title', ''),
                    'student_id': s_pk,
                    'student_name': students_map.get(s_pk, {}).get('full_name', _get_user_display_name(st_user)),
                    'answer_text': getattr(sub, 'answer_text', getattr(sub, 'text', '')),
                    'has_file': bool(getattr(sub, 'file', None)),
                    'grade': grade_val,
                    'feedback': getattr(sub, 'feedback', getattr(sub, 'teacher_feedback', '')),
                    'submitted_at': getattr(sub, 'created_at', getattr(sub, 'submitted_at', None)),
                })
        except Exception:
            pass

    if ExamModel and authorized_course_ids:
        try:
            now = timezone.now()
            for ex in ExamModel.objects.filter(course_id__in=authorized_course_ids).order_by('-id'):
                course_obj = getattr(ex, 'course', None)
                ex_date = getattr(ex, 'date', getattr(ex, 'exam_date', getattr(ex, 'start_time', None)))
                is_upcoming = bool(ex_date and ex_date >= now)
                exams.append({
                    'id': ex.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or '')),
                    'title': getattr(ex, 'title', str(ex)),
                    'description': getattr(ex, 'description', ''),
                    'date': ex_date,
                    'max_score': getattr(ex, 'max_score', 100),
                    'is_upcoming': is_upcoming,
                    'status_label': 'در پیش‌رو' if is_upcoming else 'برگزارشده',
                })
        except Exception:
            pass

    return assignments, submissions, pending_grading_count, exams


def _get_teacher_attendance_and_schedule(authorized_course_ids, students_map):
    """واکشی حضور و غیاب و برنامه هفتگی جلسات کلاس‌های استاد"""
    AttendanceModel = _find_first_model([
        ('academics', 'Attendance'),
        ('courses', 'Attendance'),
        ('academics', 'AttendanceRecord'),
    ])
    SessionModel = _find_first_model([
        ('courses', 'ClassSession'),
        ('courses', 'Session'),
        ('academics', 'ClassSession'),
        ('academics', 'Schedule'),
    ])

    attendance_records = []
    attendance_stats = {'total': 0, 'present': 0, 'absent': 0, 'late': 0, 'excused': 0, 'rate': None}
    student_att_totals = {s_id: {'total': 0, 'present': 0} for s_id in students_map.keys()}
    sessions = []

    if AttendanceModel and authorized_course_ids:
        try:
            field_names = [f.name for f in AttendanceModel._meta.get_fields()]
            q_att = Q()
            if 'course' in field_names:
                q_att |= Q(course_id__in=authorized_course_ids)
            elif 'session' in field_names:
                q_att |= Q(session__course_id__in=authorized_course_ids)

            if q_att:
                for r in AttendanceModel.objects.filter(q_att).order_by('-id'):
                    st_obj = getattr(r, 'student', getattr(r, 'user', None))
                    st_user = getattr(st_obj, 'user', st_obj)
                    s_pk = getattr(st_user, 'pk', None)
                    course_obj = getattr(r, 'course', getattr(getattr(r, 'session', None), 'course', None))

                    status_val = str(getattr(r, 'status', '')).lower()
                    is_pres = getattr(r, 'is_present', None)
                    if status_val in ('present', 'حاضر') or is_pres is True:
                        norm_st, label_fa = 'present', 'حاضر'
                        attendance_stats['present'] += 1
                        if s_pk in student_att_totals:
                            student_att_totals[s_pk]['present'] += 1
                    elif status_val in ('late', 'تاخیر', 'تأخیر'):
                        norm_st, label_fa = 'late', 'تأخیر'
                        attendance_stats['late'] += 1
                        if s_pk in student_att_totals:
                            student_att_totals[s_pk]['present'] += 0.5
                    elif status_val in ('excused', 'موجه'):
                        norm_st, label_fa = 'excused', 'غیبت موجه'
                        attendance_stats['excused'] += 1
                        if s_pk in student_att_totals:
                            student_att_totals[s_pk]['present'] += 1
                    else:
                        norm_st, label_fa = 'absent', 'غایب'
                        attendance_stats['absent'] += 1

                    attendance_stats['total'] += 1
                    if s_pk in student_att_totals:
                        student_att_totals[s_pk]['total'] += 1

                    attendance_records.append({
                        'id': r.pk,
                        'student_id': s_pk,
                        'student_name': students_map.get(s_pk, {}).get('full_name', _get_user_display_name(st_user)),
                        'course_id': getattr(course_obj, 'pk', None),
                        'course_title': getattr(course_obj, 'title', str(course_obj or '')),
                        'session_title': getattr(r, 'session_title', str(getattr(r, 'session', 'جلسه کلاسی'))),
                        'date': getattr(r, 'date', getattr(r, 'session_date', getattr(r, 'created_at', None))),
                        'status': norm_st,
                        'status_label': label_fa,
                        'note': getattr(r, 'note', getattr(r, 'remarks', '')),
                    })
        except Exception:
            pass

    if attendance_stats['total'] > 0:
        eff = attendance_stats['present'] + (attendance_stats['late'] * 0.5) + attendance_stats['excused']
        attendance_stats['rate'] = round((eff / attendance_stats['total']) * 100, 1)

    for s_pk, counts in student_att_totals.items():
        if counts['total'] > 0 and s_pk in students_map:
            students_map[s_pk]['attendance_percentage'] = round((counts['present'] / counts['total']) * 100, 1)

    if SessionModel and authorized_course_ids:
        try:
            for s in SessionModel.objects.filter(course_id__in=authorized_course_ids).order_by('id'):
                course_obj = getattr(s, 'course', None)
                sessions.append({
                    'id': s.pk,
                    'course_id': getattr(course_obj, 'pk', None),
                    'course_title': getattr(course_obj, 'title', str(course_obj or '')),
                    'language': getattr(course_obj, 'get_language_display', lambda: getattr(course_obj, 'language', ''))(),
                    'level': getattr(course_obj, 'level', 'CEFR'),
                    'title': getattr(s, 'title', 'جلسه آموزشی'),
                    'date_time': getattr(s, 'start_time', getattr(s, 'date', getattr(s, 'day_of_week', ''))),
                    'room': getattr(s, 'room', getattr(s, 'classroom', 'کلاس حضوری / آنلاین')),
                    'meeting_url': getattr(s, 'meeting_link', getattr(s, 'online_url', '')),
                    'status': getattr(s, 'status', 'برنامه‌ریزی‌شده'),
                })
        except Exception:
            pass

    return attendance_records, attendance_stats, sessions


@teacher_required
@require_http_methods(["GET", "POST"])
def teacher_dashboard_view(request):
    """
    ویوی جامع داشبورد پریمیوم اساتید آموزشگاه زبان تُرَنج.
    شامل کنترل دسترسی سخت‌گیرانه سمت سرور و جلوگیری از هرگونه دسترسی خارج از کلاس‌های مجاز استاد.
    """
    user = request.user
    profile = _get_teacher_profile(user)
    courses_list, authorized_course_ids, assigned_departments = _get_teacher_courses(user, profile)

    search_q = request.GET.get('q', '').strip()
    course_filter = request.GET.get('course', '').strip()
    level_filter = request.GET.get('level', '').strip()

    all_students, filtered_students, authorized_student_ids, students_map = _get_authorized_students(
        authorized_course_ids, courses_list, search_q, course_filter, level_filter
    )

    # پردازش عملیات ثبت و ویرایش توسط استاد (POST)
    if request.method == 'POST':
        action = request.POST.get('form_action', '').strip()
        dashboard_url = reverse('dashboards:teacher_dashboard')

        # ۱. ثبت یا ویرایش نمره و بازخورد زبان‌آموز
        if action == 'record_grade':
            course_id_raw = request.POST.get('course_id', '')
            student_id_raw = request.POST.get('student_id', '')
            title = request.POST.get('title', 'ارزیابی آموزشی').strip()[:120]
            score_raw = request.POST.get('score', '').strip()
            max_score_raw = request.POST.get('max_score', '100').strip()
            feedback = request.POST.get('feedback', '').strip()[:2000]
            skill_type = request.POST.get('skill_type', '').strip().lower()

            if not course_id_raw.isdigit() or not student_id_raw.isdigit():
                messages.error(request, "لطفاً کلاس و زبان‌آموز معتبر را انتخاب نمایید.")
                return redirect(f"{dashboard_url}?tab=grades")

            c_id = int(course_id_raw)
            s_id = int(student_id_raw)

            if c_id not in authorized_course_ids or s_id not in authorized_student_ids:
                audit_logger.warning(
                    f"IDOR blocked in record_grade: teacher={user.pk} tried grading student={s_id} in course={c_id}"
                )
                return HttpResponseForbidden("خطای امنیتی: شما مجوز ثبت نمره برای این زبان‌آموز یا دوره را ندارید.")

            try:
                score_val = float(score_raw)
                max_score_val = float(max_score_raw) if max_score_raw else 100.0
                if score_val < 0 or score_val > max_score_val or max_score_val <= 0:
                    raise ValueError("Invalid score range")
            except ValueError:
                messages.error(request, "نمره واردشده نامعتبر است. لطفاً عددی بین ۰ تا سقف نمره وارد کنید.")
                return redirect(f"{dashboard_url}?tab=grades")

            GradeModel = _find_first_model([
                ('academics', 'Grade'),
                ('academics', 'Assessment'),
                ('academics', 'ReportCard'),
                ('courses', 'Grade'),
            ])
            with transaction.atomic():
                if GradeModel:
                    try:
                        f_names = [f.name for f in GradeModel._meta.get_fields()]
                        st_info = students_map[s_id]
                        kwargs = {'course_id': c_id}
                        if 'student' in f_names:
                            rel_m = GradeModel._meta.get_field('student').related_model
                            kwargs['student'] = st_info['user_obj'] if rel_m == user.__class__ else (st_info['profile_obj'] or st_info['user_obj'])
                        elif 'user' in f_names:
                            kwargs['user'] = st_info['user_obj']
                        if 'title' in f_names:
                            kwargs['title'] = title
                        elif 'assessment_type' in f_names:
                            kwargs['assessment_type'] = title
                        if 'score' in f_names:
                            kwargs['score'] = score_val
                        elif 'grade' in f_names:
                            kwargs['grade'] = score_val
                        if 'max_score' in f_names:
                            kwargs['max_score'] = max_score_val
                        if 'teacher_feedback' in f_names:
                            kwargs['teacher_feedback'] = feedback
                        elif 'feedback' in f_names:
                            kwargs['feedback'] = feedback
                        if 'skill' in f_names and skill_type:
                            kwargs['skill'] = skill_type
                        elif skill_type and f"{skill_type}_score" in f_names:
                            kwargs[f"{skill_type}_score"] = score_val
                        if 'recorded_by' in f_names:
                            kwargs['recorded_by'] = user
                        elif 'teacher' in f_names:
                            kwargs['teacher'] = user
                        GradeModel.objects.create(**kwargs)
                    except Exception as exc:
                        audit_logger.warning(f"Grade save notice: {exc}")

                audit_logger.info(
                    f"AUDIT: Grade recorded by teacher={user.pk} for student={s_id} course={c_id} score={score_val}/{max_score_val} at {timezone.now().isoformat()}"
                )
                messages.success(request, "نمره و بازخورد آموزشی با موفقیت ثبت و در کارنامه زبان‌آموز اعمال شد.")
            return redirect(f"{dashboard_url}?tab=grades")

        # ۲. ایجاد تکلیف جدید برای کلاس‌های مجاز استاد
        elif action == 'create_assignment':
            course_id_raw = request.POST.get('course_id', '')
            title = request.POST.get('title', '').strip()[:150]
            description = request.POST.get('description', '').strip()[:3000]
            deadline_raw = request.POST.get('deadline', '').strip()
            attachment = request.FILES.get('attachment')

            if not course_id_raw.isdigit() or int(course_id_raw) not in authorized_course_ids:
                audit_logger.warning(f"IDOR blocked in create_assignment by teacher={user.pk}")
                return HttpResponseForbidden("شما مجوز تعریف تکلیف برای این کلاس را ندارید.")

            if not title:
                messages.error(request, "لطفاً عنوان تکلیف را وارد نمایید.")
                return redirect(f"{dashboard_url}?tab=assignments")

            is_valid_file, file_err = _validate_uploaded_file(attachment)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect(f"{dashboard_url}?tab=assignments")

            AssignmentModel = _find_first_model([('academics', 'Assignment'), ('courses', 'Assignment')])
            with transaction.atomic():
                if AssignmentModel:
                    try:
                        f_names = [f.name for f in AssignmentModel._meta.get_fields()]
                        kwargs = {'course_id': int(course_id_raw), 'title': title}
                        if 'description' in f_names:
                            kwargs['description'] = description
                        if deadline_raw:
                            if 'deadline' in f_names:
                                kwargs['deadline'] = deadline_raw
                            elif 'due_date' in f_names:
                                kwargs['due_date'] = deadline_raw
                        if attachment:
                            if 'file' in f_names:
                                kwargs['file'] = attachment
                            elif 'attachment' in f_names:
                                kwargs['attachment'] = attachment
                        if 'teacher' in f_names:
                            kwargs['teacher'] = user
                        AssignmentModel.objects.create(**kwargs)
                    except Exception as exc:
                        audit_logger.warning(f"Assignment create notice: {exc}")

                audit_logger.info(f"AUDIT: Assignment '{title}' created by teacher={user.pk} for course={course_id_raw}")
                messages.success(request, "تکلیف جدید با موفقیت برای کلاس تعریف شد.")
            return redirect(f"{dashboard_url}?tab=assignments")

        # ۳. نمره‌دهی به تکلیف ارسال‌شده توسط زبان‌آموز
        elif action == 'grade_submission':
            submission_id_raw = request.POST.get('submission_id', '')
            grade_raw = request.POST.get('grade', '').strip()
            feedback = request.POST.get('feedback', '').strip()[:2000]

            SubmissionModel = _find_first_model([
                ('academics', 'AssignmentSubmission'),
                ('academics', 'Submission'),
                ('courses', 'Submission'),
            ])
            if not SubmissionModel or not submission_id_raw.isdigit():
                messages.error(request, "پاسخ تکلیف مورد نظر یافت نشد.")
                return redirect(f"{dashboard_url}?tab=assignments")

            sub_obj = get_object_or_404(SubmissionModel, pk=int(submission_id_raw))
            course_id = getattr(getattr(sub_obj, 'assignment', None), 'course_id', None)
            if course_id not in authorized_course_ids:
                audit_logger.warning(f"IDOR blocked in grade_submission by teacher={user.pk}")
                return HttpResponseForbidden("شما مجوز نمره‌دهی به این تکلیف را ندارید.")

            try:
                grade_val = float(grade_raw)
            except ValueError:
                messages.error(request, "نمره واردشده معتبر نیست.")
                return redirect(f"{dashboard_url}?tab=assignments")

            with transaction.atomic():
                if hasattr(sub_obj, 'grade'):
                    sub_obj.grade = grade_val
                elif hasattr(sub_obj, 'score'):
                    sub_obj.score = grade_val
                if hasattr(sub_obj, 'feedback'):
                    sub_obj.feedback = feedback
                elif hasattr(sub_obj, 'teacher_feedback'):
                    sub_obj.teacher_feedback = feedback
                sub_obj.save()

                audit_logger.info(f"AUDIT: Submission {sub_obj.pk} graded by teacher={user.pk} score={grade_val}")
                messages.success(request, "نمره و بازخورد تکلیف زبان‌آموز با موفقیت ثبت شد.")
            return redirect(f"{dashboard_url}?tab=assignments")

        # ۴. تعریف و زمان‌بندی آزمون جدید
        elif action == 'create_exam':
            course_id_raw = request.POST.get('course_id', '')
            title = request.POST.get('title', '').strip()[:150]
            exam_date = request.POST.get('exam_date', '').strip()
            max_score_raw = request.POST.get('max_score', '100').strip()
            description = request.POST.get('description', '').strip()[:2000]

            if not course_id_raw.isdigit() or int(course_id_raw) not in authorized_course_ids:
                return HttpResponseForbidden("شما مجوز ثبت آزمون برای این دوره را ندارید.")

            if not title:
                messages.error(request, "لطفاً عنوان آزمون را وارد نمایید.")
                return redirect(f"{dashboard_url}?tab=exams")

            ExamModel = _find_first_model([('academics', 'Exam'), ('courses', 'Exam')])
            with transaction.atomic():
                if ExamModel:
                    try:
                        f_names = [f.name for f in ExamModel._meta.get_fields()]
                        kwargs = {'course_id': int(course_id_raw), 'title': title}
                        if 'description' in f_names:
                            kwargs['description'] = description
                        if exam_date:
                            if 'date' in f_names:
                                kwargs['date'] = exam_date
                            elif 'exam_date' in f_names:
                                kwargs['exam_date'] = exam_date
                        if 'max_score' in f_names and max_score_raw.isdigit():
                            kwargs['max_score'] = int(max_score_raw)
                        ExamModel.objects.create(**kwargs)
                    except Exception as exc:
                        audit_logger.warning(f"Exam create notice: {exc}")

                audit_logger.info(f"AUDIT: Exam '{title}' scheduled by teacher={user.pk} for course={course_id_raw}")
                messages.success(request, "آزمون جدید با موفقیت در تقویم دوره ثبت شد.")
            return redirect(f"{dashboard_url}?tab=exams")

        # ۵. ثبت یا اصلاح حضور و غیاب زبان‌آموز (با جلوگیری از ثبت تکراری در یک جلسه)
        elif action == 'record_attendance':
            course_id_raw = request.POST.get('course_id', '')
            student_id_raw = request.POST.get('student_id', '')
            session_title = request.POST.get('session_title', 'جلسه کلاسی').strip()[:100]
            session_date = request.POST.get('session_date', '').strip() or timezone.now().strftime('%Y-%m-%d')
            att_status = request.POST.get('status', 'present').strip().lower()
            note = request.POST.get('note', '').strip()[:500]

            if not course_id_raw.isdigit() or not student_id_raw.isdigit():
                messages.error(request, "انتخاب کلاس و زبان‌آموز الزامی است.")
                return redirect(f"{dashboard_url}?tab=attendance")

            c_id = int(course_id_raw)
            s_id = int(student_id_raw)

            if c_id not in authorized_course_ids or s_id not in authorized_student_ids:
                audit_logger.warning(
                    f"IDOR blocked in record_attendance: teacher={user.pk} student={s_id} course={c_id}"
                )
                return HttpResponseForbidden("شما مجوز ثبت حضور و غیاب برای این زبان‌آموز را ندارید.")

            if att_status not in ('present', 'absent', 'late', 'excused'):
                att_status = 'present'

            AttendanceModel = _find_first_model([
                ('academics', 'Attendance'),
                ('courses', 'Attendance'),
                ('academics', 'AttendanceRecord'),
            ])
            with transaction.atomic():
                if AttendanceModel:
                    try:
                        f_names = [f.name for f in AttendanceModel._meta.get_fields()]
                        st_info = students_map[s_id]
                        lookup = {}
                        if 'course' in f_names:
                            lookup['course_id'] = c_id
                        if 'student' in f_names:
                            rel_m = AttendanceModel._meta.get_field('student').related_model
                            lookup['student'] = st_info['user_obj'] if rel_m == user.__class__ else (st_info['profile_obj'] or st_info['user_obj'])
                        elif 'user' in f_names:
                            lookup['user'] = st_info['user_obj']
                        if 'date' in f_names:
                            lookup['date'] = session_date
                        elif 'session_date' in f_names:
                            lookup['session_date'] = session_date
                        if 'session_title' in f_names:
                            lookup['session_title'] = session_title

                        defaults = {}
                        if 'status' in f_names:
                            defaults['status'] = att_status
                        if 'is_present' in f_names:
                            defaults['is_present'] = (att_status == 'present')
                        if 'note' in f_names:
                            defaults['note'] = note
                        if 'recorded_by' in f_names:
                            defaults['recorded_by'] = user

                        AttendanceModel.objects.update_or_create(defaults=defaults, **lookup)
                    except Exception as exc:
                        audit_logger.warning(f"Attendance record save notice: {exc}")

                audit_logger.info(
                    f"AUDIT: Attendance ({att_status}) recorded by teacher={user.pk} for student={s_id} course={c_id} date={session_date}"
                )
                messages.success(request, "وضعیت حضور و غیاب زبان‌آموز بدون تکرار با موفقیت ثبت شد.")
            return redirect(f"{dashboard_url}?tab=attendance")

        # ۶. بروزرسانی اطلاعات مجاز پروفایل استاد (بدون اجازه تغییر نقش یا کد استاد)
        elif action == 'update_profile':
            first_name = request.POST.get('first_name', '').strip()[:50]
            last_name = request.POST.get('last_name', '').strip()[:50]
            bio = request.POST.get('bio', '').strip()[:1500]
            avatar_file = request.FILES.get('avatar')

            is_valid_file, file_err = _validate_uploaded_file(avatar_file)
            if not is_valid_file:
                messages.error(request, file_err)
                return redirect(f"{dashboard_url}?tab=profile")

            with transaction.atomic():
                if hasattr(user, 'first_name'):
                    user.first_name = first_name
                if hasattr(user, 'last_name'):
                    user.last_name = last_name
                if hasattr(user, 'bio') and bio:
                    user.bio = bio
                user.save()

                if profile is not None:
                    if bio:
                        for b_attr in ('bio', 'qualifications', 'about'):
                            if hasattr(profile, b_attr):
                                setattr(profile, b_attr, bio)
                    if avatar_file:
                        for img_attr in ('avatar', 'profile_photo', 'photo', 'image'):
                            if hasattr(profile, img_attr):
                                setattr(profile, img_attr, avatar_file)
                                break
                    profile.save()

                audit_logger.info(f"AUDIT: Teacher profile updated safely by teacher={user.pk}")
                messages.success(request, "اطلاعات پروفایل استاد با موفقیت بروزرسانی شد.")
            return redirect(f"{dashboard_url}?tab=profile")

        # ۷. تغییر رمز عبور استاد
        elif action == 'change_password':
            pwd_form = PasswordChangeForm(user=user, data=request.POST)
            if pwd_form.is_valid():
                with transaction.atomic():
                    pwd_form.save()
                    update_session_auth_hash(request, pwd_form.user)
                    audit_logger.info(f"AUDIT: Teacher password updated by teacher={user.pk}")
                    messages.success(request, "رمز عبور شما با موفقیت تغییر یافت.")
            else:
                for err_list in pwd_form.errors.values():
                    for err in err_list:
                        messages.error(request, err)
            return redirect(f"{dashboard_url}?tab=profile")

    # واکشی داده‌های تحلیلی، نمرات، تکالیف، آزمون‌ها و حضور و غیاب
    grades_list, skills_analytics, has_skill_data, areas_needing_improvement = _get_teacher_grades_and_analytics(
        authorized_course_ids, students_map
    )
    assignments, submissions, pending_grading_count, exams = _get_teacher_assignments_and_exams(
        authorized_course_ids, students_map
    )
    attendance_records, attendance_stats, sessions = _get_teacher_attendance_and_schedule(
        authorized_course_ids, students_map
    )

    active_courses = [c for c in courses_list if c['is_active']]
    previous_courses = [c for c in courses_list if not c['is_active']]

    # محاسبه شاخص‌های گزارش مدیریتی استاد بر اساس داده‌های واقعی
    valid_scores = [g['normalized_score'] for g in grades_list if g['normalized_score'] is not None]
    overall_class_average = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else None

    # اعلان‌های واقعی استاد
    notifications = []
    if pending_grading_count > 0:
        notifications.append({
            'category': 'تصحیح تکالیف',
            'title': f"{pending_grading_count} تکلیف ارسال‌شده در انتظار نمره‌دهی شماست",
            'message': 'از بخش مدیریت تکالیف می‌توانید فایل‌های زبان‌آموزان را بررسی و نمره‌دهی کنید.',
        })
    for ex in exams[:3]:
        if ex['is_upcoming']:
            notifications.append({
                'category': 'آزمون پیش‌رو',
                'title': f"آزمون «{ex['title']}» برای دوره {ex['course_title']}",
                'message': f"زمان برگزاری: {ex['date'] or 'طبق تقویم آموزشی'}",
            })
    for s in sessions[:3]:
        notifications.append({
            'category': 'برنامه کلاسی',
            'title': f"جلسه {s['title']} — {s['course_title']}",
            'message': f"زمان: {s['date_time']} • محل: {s['room']}",
        })

    avatar_url = None
    for obj in (profile, user):
        if obj is not None:
            for attr in ('avatar', 'profile_photo', 'photo', 'image'):
                img_f = getattr(obj, attr, None)
                if img_f and hasattr(img_f, 'url'):
                    try:
                        avatar_url = img_f.url
                        break
                    except Exception:
                        pass

    qualifications = getattr(profile, 'qualifications', getattr(profile, 'bio', getattr(user, 'bio', 'مدرس تخصصی زبان‌های بین‌المللی در آموزشگاه زبان تُرَنج')))

    context = {
        'active_tab': request.GET.get('tab', 'overview').strip(),
        'teacher_full_name': _get_user_display_name(user),
        'teacher_id': _get_teacher_academy_id(user, profile),
        'teacher_phone': getattr(user, 'phone', getattr(user, 'username', '')),
        'avatar_url': avatar_url,
        'qualifications': qualifications,
        'assigned_departments': assigned_departments or ['تعیین‌نشده در ترم جاری'],
        'courses_list': courses_list,
        'active_courses': active_courses,
        'previous_courses': previous_courses,
        'all_students': all_students,
        'filtered_students': filtered_students,
        'total_students_count': len(all_students),
        'search_q': search_q,
        'course_filter': course_filter,
        'level_filter': level_filter,
        'grades_list': grades_list,
        'overall_class_average': overall_class_average,
        'skills_analytics': skills_analytics,
        'has_skill_data': has_skill_data,
        'areas_needing_improvement': areas_needing_improvement,
        'assignments': assignments,
        'submissions': submissions,
        'pending_grading_count': pending_grading_count,
        'exams': exams,
        'attendance_records': attendance_records,
        'attendance_stats': attendance_stats,
        'sessions': sessions,
        'notifications': notifications,
    }
    return render(request, 'dashboards/teacher_dashboard.html', context)


@teacher_required
@require_http_methods(["GET"])
def teacher_class_detail_view(request, course_id):
    """
    صفحه اختصاصی مدیریت یک کلاس توسط استاد.
    دارای محافظت کامل IDOR: اگر کلاس متعلق به استاد نباشد، خطای 403 برمی‌گرداند.
    """
    user = request.user
    profile = _get_teacher_profile(user)
    courses_list, authorized_course_ids, _ = _get_teacher_courses(user, profile)

    if course_id not in authorized_course_ids and not user.is_superuser:
        audit_logger.warning(
            f"IDOR blocked: teacher={user.pk} attempted unauthorized access to class course_id={course_id}"
        )
        return HttpResponseForbidden("دسترسی غیرمجاز: این کلاس به شما اختصاص داده نشده است.")

    course_info = next((c for c in courses_list if c['id'] == course_id), None)
    if not course_info:
        raise Http404("کلاس مورد نظر یافت نشد.")

    _, class_students, _, students_map = _get_authorized_students(
        {course_id}, [course_info], course_filter=str(course_id)
    )
    grades_list, _, _, _ = _get_teacher_grades_and_analytics({course_id}, students_map)
    assignments, submissions, _, exams = _get_teacher_assignments_and_exams({course_id}, students_map)
    attendance_records, attendance_stats, sessions = _get_teacher_attendance_and_schedule({course_id}, students_map)

    context = {
        'teacher_full_name': _get_user_display_name(user),
        'teacher_id': _get_teacher_academy_id(user, profile),
        'course': course_info,
        'class_students': class_students,
        'class_grades': grades_list,
        'class_assignments': assignments,
        'class_submissions': submissions,
        'class_exams': exams,
        'class_attendance': attendance_records,
        'attendance_stats': attendance_stats,
        'class_sessions': sessions,
    }
    return render(request, 'dashboards/teacher_class_detail.html', context)


@teacher_required
@require_http_methods(["GET"])
def protected_submission_download_view(request, submission_id):
    """دانلود امن فایل تکلیف زبان‌آموز پس از بررسی مالکیت کلاس توسط استاد"""
    user = request.user
    profile = _get_teacher_profile(user)
    _, authorized_course_ids, _ = _get_teacher_courses(user, profile)

    SubmissionModel = _find_first_model([
        ('academics', 'AssignmentSubmission'),
        ('academics', 'Submission'),
        ('courses', 'Submission'),
    ])
    if not SubmissionModel:
        raise Http404("تکلیف مورد نظر یافت نشد.")

    submission = get_object_or_404(SubmissionModel, pk=submission_id)
    course_id = getattr(getattr(submission, 'assignment', None), 'course_id', None)

    if course_id not in authorized_course_ids and not user.is_superuser:
        audit_logger.warning(
            f"Unauthorized submission download blocked: teacher={user.pk} submission={submission_id}"
        )
        return HttpResponseForbidden("شما مجوز دانلود فایل‌های این کلاس را ندارید.")

    file_field = getattr(submission, 'file', None)
    if not file_field:
        raise Http404("فایلی برای این پاسخ ثبت نشده است.")

    audit_logger.info(f"AUDIT: Teacher {user.pk} downloaded submission {submission_id}")
    return FileResponse(file_field.open('rb'), as_attachment=True, filename=os.path.basename(file_field.name))


@teacher_required
@require_http_methods(["GET"])
def teacher_report_export_view(request):
    """
    خروجی اکسل / CSV استاندارد (UTF-8 with BOM برای نمایش صحیح حروف فارسی در Excel)
    از گزارش عملکرد زبان‌آموزان، نمرات و حضور و غیاب کلاس‌های مجاز استاد.
    """
    user = request.user
    profile = _get_teacher_profile(user)
    courses_list, authorized_course_ids, _ = _get_teacher_courses(user, profile)
    all_students, _, _, students_map = _get_authorized_students(authorized_course_ids, courses_list)
    _get_teacher_grades_and_analytics(authorized_course_ids, students_map)
    _get_teacher_attendance_and_schedule(authorized_course_ids, students_map)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="toranj_teacher_academic_report.csv"'
    response.write('\ufeff')  # UTF-8 BOM برای باز شدن مستقیم فارسی در Microsoft Excel

    writer = csv.writer(response)
    writer.writerow([
        'نام و نام خانوادگی زبان‌آموز',
        'کد زبان‌آموزی',
        'شماره تماس',
        'دوره‌های ثبت‌نام‌شده',
        'ترم جاری',
        'میانگین نمرات (از ۱۰۰)',
        'درصد حضور در کلاس',
        'آخرین بازخورد استاد',
    ])

    for st in all_students:
        writer.writerow([
            st['full_name'],
            st['academy_id'],
            st['phone'],
            ' | '.join(st['enrolled_courses']),
            st['current_term'],
            st['average_grade'] if st['average_grade'] is not None else 'ثبت‌نشده',
            f"{st['attendance_percentage']}%" if st['attendance_percentage'] is not None else 'ثبت‌نشده',
            st['latest_feedback'] or '—',
        ])

    audit_logger.info(f"AUDIT: Teacher {user.pk} exported academic report CSV")
    return response