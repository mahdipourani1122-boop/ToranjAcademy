import os
from pathlib import Path

BASE = Path(r"C:\Users\Com2000\ToranjAcademy")
FILES = {}

# 1. config/settings.py
FILES["config/settings.py"] = """import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-toranj-dev-only-key-do-not-use-in-production-987654'
)
TOTP_ENCRYPTION_KEY = os.environ.get('DJANGO_TOTP_ENCRYPTION_KEY', SECRET_KEY)
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',') if h.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'accounts',
    'dashboards',
    'courses',
    'academics',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.SessionSecurityAnd2FAMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'toranj-security-rate-limit',
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'accounts.backends.ToranjAuthenticationBackend',
    'django.contrib.auth.backends.ModelBackend',
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

SESSION_COOKIE_NAME = 'toranj_sid'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60 * 60 * 8

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

TRUSTED_DEVICE_COOKIE_NAME = 'toranj_trusted_device'
TRUSTED_DEVICE_MAX_AGE_DAYS = 30

SMS_PROVIDER = os.environ.get('SMS_PROVIDER', '').strip().lower()
SMS_API_KEY = os.environ.get('SMS_API_KEY', '').strip()
SMS_SENDER_NUMBER = os.environ.get('SMS_SENDER_NUMBER', '').strip()
SMS_OTP_TEMPLATE = os.environ.get('SMS_OTP_TEMPLATE', 'toranj-otp').strip()
SMS_WEBHOOK_URL = os.environ.get('SMS_WEBHOOK_URL', '').strip()

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboards:redirect'
LOGOUT_REDIRECT_URL = 'core:home'
PASSWORD_RESET_TIMEOUT = 1800

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@toranjacademy.ir')

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
"""

# 2. config/urls.py
FILES["config/urls.py"] = """from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

admin.site.site_header = 'پنل مدیریت جامع آکادمی زبان تُرنج'
admin.site.site_title = 'مدیریت تُرنج | TORANJ LMS'
admin.site.index_title = 'پیشخوان مدیریت کاربران، دوره‌ها، کلاس‌ها و تحلیل آموزشی'

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('', include('core.urls', namespace='core')),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('dashboard/', include('dashboards.urls', namespace='dashboards')),
    path('courses/', include('courses.urls', namespace='courses')),
    path('academics/', include('academics.urls', namespace='academics')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
"""

# 3. academics/analytics.py
FILES["academics/analytics.py"] = """from collections import defaultdict
from accounts.models import User
from courses.models import ClassGroup
from .models import AttendanceRecord, AcademicAssessment, SkillAssessmentScore

SKILL_LABELS = dict(SkillAssessmentScore.Skill.choices)
ALL_SKILL_KEYS = [key for key, _ in SkillAssessmentScore.Skill.choices]


def compute_student_academic_analytics(student: User, semester_filter: str = None) -> dict:
    assessments_qs = AcademicAssessment.objects.filter(student=student).select_related(
        'class_group', 'class_group__course', 'evaluated_by'
    ).prefetch_related('skill_scores').order_by('semester_label', '-due_date')

    all_semesters = sorted(list(set(assessments_qs.values_list('semester_label', flat=True))))

    semester_stats_map = {}
    for sem in all_semesters:
        sem_items = [a for a in assessments_qs if a.semester_label == sem]
        graded_items = [a for a in sem_items if a.normalized_score_100 is not None]
        total_weight = sum(float(a.weight) for a in graded_items)
        if total_weight > 0:
            weighted_sum = sum(a.normalized_score_100 * float(a.weight) for a in graded_items)
            gpa_100 = round(weighted_sum / total_weight, 2)
            gpa_20 = round(gpa_100 / 5.0, 2)
        else:
            gpa_100 = None
            gpa_20 = None

        semester_stats_map[sem] = {
            'semester': sem,
            'gpa_100': gpa_100,
            'gpa_20': gpa_20,
            'assessments_count': len(sem_items),
            'graded_count': len(graded_items),
        }

    semester_history = [semester_stats_map[s] for s in all_semesters]

    graded_semesters = [s for s in semester_history if s['gpa_100'] is not None]
    if len(graded_semesters) >= 2:
        current_sem_gpa = graded_semesters[-1]['gpa_100']
        previous_sem_gpa = graded_semesters[-2]['gpa_100']
        semester_delta = round(current_sem_gpa - previous_sem_gpa, 2)
        comparison_status = (
            'پیشرفت نسبت به ترم قبل' if semester_delta > 0
            else ('افت نسبت به ترم قبل' if semester_delta < 0 else 'ثابت نسبت به ترم قبل')
        )
    elif len(graded_semesters) == 1:
        current_sem_gpa = graded_semesters[0]['gpa_100']
        previous_sem_gpa = None
        semester_delta = None
        comparison_status = 'تنها یک نیم‌سال نمره‌دهی شده ثبت شده است'
    else:
        current_sem_gpa = None
        previous_sem_gpa = None
        semester_delta = None
        comparison_status = 'داده نمره‌دهی برای مقایسه بین ترم‌ها موجود نیست'

    filtered_assessments = (
        [a for a in assessments_qs if a.semester_label == semester_filter]
        if semester_filter else list(assessments_qs)
    )

    graded_filtered = [a for a in filtered_assessments if a.normalized_score_100 is not None]
    total_w = sum(float(a.weight) for a in graded_filtered)
    overall_gpa_100 = round(
        sum(a.normalized_score_100 * float(a.weight) for a in graded_filtered) / total_w, 2
    ) if total_w > 0 else None
    overall_gpa_20 = round(overall_gpa_100 / 5.0, 2) if overall_gpa_100 is not None else None

    assignment_items = [
        a for a in filtered_assessments
        if a.assessment_type == AcademicAssessment.AssessmentType.ASSIGNMENT
    ]
    total_assignments = len(assignment_items)
    completed_assignments = len([
        a for a in assignment_items
        if a.submission_status in [
            AcademicAssessment.SubmissionStatus.SUBMITTED,
            AcademicAssessment.SubmissionStatus.GRADED
        ]
    ])
    assignment_completion_rate = (
        round((completed_assignments / total_assignments) * 100.0, 1)
        if total_assignments > 0 else None
    )

    attendance_qs = AttendanceRecord.objects.filter(student=student)
    if semester_filter:
        class_ids_in_sem = set(a.class_group_id for a in filtered_assessments)
        if class_ids_in_sem:
            attendance_qs = attendance_qs.filter(session__class_group_id__in=class_ids_in_sem)

    total_attendance_records = attendance_qs.count()
    present_count = attendance_qs.filter(status=AttendanceRecord.Status.PRESENT).count()
    late_count = attendance_qs.filter(status=AttendanceRecord.Status.LATE).count()
    absent_count = attendance_qs.filter(status=AttendanceRecord.Status.ABSENT).count()
    excused_count = attendance_qs.filter(status=AttendanceRecord.Status.EXCUSED).count()

    if total_attendance_records > 0:
        attendance_rate = round(((present_count + late_count) / total_attendance_records) * 100.0, 1)
        absence_rate = round(((absent_count + excused_count) / total_attendance_records) * 100.0, 1)
    else:
        attendance_rate = None
        absence_rate = None

    skill_buckets = defaultdict(list)
    for assessment in graded_filtered:
        for sk in assessment.skill_scores.all():
            skill_buckets[sk.skill].append(float(sk.score))

    skills_breakdown = []
    assessed_skills = []
    for sk_key in ALL_SKILL_KEYS:
        scores_list = skill_buckets.get(sk_key, [])
        avg_val = round(sum(scores_list) / len(scores_list), 1) if scores_list else None
        item = {
            'key': sk_key,
            'label': SKILL_LABELS[sk_key],
            'average': avg_val,
            'assessments_count': len(scores_list),
            'has_data': len(scores_list) > 0,
        }
        skills_breakdown.append(item)
        if avg_val is not None:
            assessed_skills.append(item)

    strongest_skills = []
    weakest_skills = []
    if assessed_skills:
        sorted_skills = sorted(assessed_skills, key=lambda x: x['average'], reverse=True)
        strongest_skills = [s for s in sorted_skills if s['average'] >= 75.0][:2]
        weakest_skills = [s for s in sorted(assessed_skills, key=lambda x: x['average']) if s['average'] < 70.0][:2]

    insufficient_data_reasons = []
    if len(graded_filtered) == 0:
        insufficient_data_reasons.append('هیچ آزمون یا تکلیف نمره‌دهی‌شده‌ای برای این زبان‌آموز ثبت نشده است.')
    if len(assessed_skills) == 0:
        insufficient_data_reasons.append('ریزنمره مهارت‌های شش‌گانه (Speaking, Listening, ...) هنوز ثبت نشده است.')
    if total_attendance_records == 0:
        insufficient_data_reasons.append('رکورد حضور و غیاب کلاسی برای این زبان‌آموز ثبت نشده است.')

    has_sufficient_data = len(graded_filtered) > 0 and len(assessed_skills) > 0

    needs_academic_support = False
    support_reasons = []
    if overall_gpa_100 is not None and overall_gpa_100 < 70.0:
        needs_academic_support = True
        support_reasons.append(f'میانگین کل کمتر از حد نصاب ({overall_gpa_100} از ۱۰۰)')
    if attendance_rate is not None and attendance_rate < 75.0:
        needs_academic_support = True
        support_reasons.append(f'نرخ حضور در کلاس کمتر از ۷۵٪ ({attendance_rate}٪)')
    if semester_delta is not None and semester_delta <= -10.0:
        needs_academic_support = True
        support_reasons.append(f'افت محسوس معدل نسبت به نیم‌سال قبل ({semester_delta} واحد)')

    return {
        'all_semesters': all_semesters,
        'selected_semester': semester_filter or '',
        'semester_history': semester_history,
        'overall_gpa_100': overall_gpa_100,
        'overall_gpa_20': overall_gpa_20,
        'current_semester_gpa': current_sem_gpa,
        'previous_semester_gpa': previous_sem_gpa,
        'semester_delta': semester_delta,
        'comparison_status': comparison_status,
        'attendance': {
            'total_sessions_recorded': total_attendance_records,
            'present': present_count,
            'late': late_count,
            'absent': absent_count,
            'excused': excused_count,
            'attendance_rate': attendance_rate,
            'absence_rate': absence_rate,
        },
        'assignments': {
            'total': total_assignments,
            'completed': completed_assignments,
            'completion_rate': assignment_completion_rate,
        },
        'skills_breakdown': skills_breakdown,
        'assessed_skills_count': len(assessed_skills),
        'strongest_skills': strongest_skills,
        'weakest_skills': weakest_skills,
        'assessments_list': filtered_assessments,
        'has_sufficient_data': has_sufficient_data,
        'insufficient_data_reasons': insufficient_data_reasons,
        'needs_academic_support': needs_academic_support,
        'support_reasons': support_reasons,
    }


def compute_class_and_teacher_performance_summary():
    classes = ClassGroup.objects.filter(is_archived=False).select_related('course', 'teacher')
    class_reports = []
    for cls in classes:
        assessments = AcademicAssessment.objects.filter(
            class_group=cls,
            submission_status=AcademicAssessment.SubmissionStatus.GRADED
        )
        scores = [a.normalized_score_100 for a in assessments if a.normalized_score_100 is not None]
        avg_score = round(sum(scores) / len(scores), 1) if scores else None

        att_qs = AttendanceRecord.objects.filter(session__class_group=cls)
        att_total = att_qs.count()
        att_present = att_qs.filter(status__in=['present', 'late']).count()
        att_rate = round((att_present / att_total) * 100.0, 1) if att_total > 0 else None

        class_reports.append({
            'class_group': cls,
            'teacher_name': cls.teacher.full_name if cls.teacher else 'تخصیص نیافته',
            'enrolled_count': cls.approved_enrollments_count,
            'average_score': avg_score,
            'attendance_rate': att_rate,
            'graded_assessments_count': len(scores),
        })
    return class_reports
"""

# 4. academics/ai_advisor.py
FILES["academics/ai_advisor.py"] = """SKILL_PRACTICE_BANK = {
    'speaking': 'شرکت در کارگاه‌های Free Discussion، ضبط روزانه ۲ دقیقه صدای خود درباره موضوعات درس و تمرین Shadowing.',
    'listening': 'گوش دادن فعال به فایل‌های صوتی سطح دوره بدون زیرنویس در مرحله اول و یادداشت کلیدواژه‌ها.',
    'reading': 'تمرین تکنیک‌های Skimming و Scanning روی متون استاندارد و استخراج ۵ ساختار جدید از هر متن.',
    'writing': 'نگارش پاراگراف‌های ساختاریافته و بازنگری خطاهای گرامری بر اساس بازخورد استاد.',
    'grammar': 'مرور ساختارهای گرامری ترم در قالب جملات کاربردی روزمره و حل تمرین‌های تکمیلی جزوه دوره.',
    'vocabulary': 'مرور واژگان به روش تکرار فاصله‌دار (Spaced Repetition) و یادگیری کالوکیشن‌ها.',
}


def generate_grounded_ai_recommendations(analytics_data: dict) -> dict:
    graded_count = len([
        a for a in analytics_data.get('assessments_list', [])
        if a.normalized_score_100 is not None
    ])
    assessed_skills_count = analytics_data.get('assessed_skills_count', 0)

    if graded_count == 0 and assessed_skills_count == 0:
        return {
            'is_ai_generated': True,
            'data_sufficient': False,
            'disclaimer': 'این بخش توسط موتور تحلیل هوشمند تولید می‌شود. به دلیل عدم ثبت نمرات کافی در پرونده، هیچ نتیجه‌گیری یا توصیه‌ای به صورت فرضی صادر نشده است.',
            'strengths': [],
            'areas_needing_improvement': [],
            'suggested_activities': [],
            'next_semester_recommendation': 'پس از ثبت حداقل یک ارزیابی نمره‌دهی‌شده توسط استاد، توصیه‌های شخصی‌سازی‌شده فعال می‌شوند.',
            'evidence_records': [],
        }

    strengths = []
    improvements = []
    activities = []
    evidence_records = []

    for s in analytics_data.get('strongest_skills', []):
        strengths.append(
            f"عملکرد قوی در مهارت «{s['label']}» با میانگین مستند {s['average']} از ۱۰۰ (بر اساس {s['assessments_count']} ارزیابی)."
        )

    for w in analytics_data.get('weakest_skills', []):
        improvements.append(
            f"نیاز به تقویت در مهارت «{w['label']}» با میانگین ثبت‌شده {w['average']} از ۱۰۰ (بر اساس {w['assessments_count']} ارزیابی)."
        )
        practice = SKILL_PRACTICE_BANK.get(w['key'])
        if practice:
            activities.append({
                'skill_label': w['label'],
                'current_average': w['average'],
                'activity': practice,
            })

    gpa = analytics_data.get('overall_gpa_100')
    if gpa is None:
        next_sem = 'در انتظار تکمیل نمرات پایان‌ترم جهت تعیین مسیر ترم آینده.'
    elif gpa >= 85.0:
        next_sem = f"با توجه به معدل کل {gpa} از ۱۰۰، زبان‌آموز آمادگی کامل جهت ارتقا به سطح بالاتر را دارد."
    elif gpa >= 70.0:
        next_sem = f"با کسب معدل {gpa} از ۱۰۰، ارتقا به ترم بعدی به همراه تمرکز بر مهارت‌های زیر ۷۵ توصیه می‌شود."
    else:
        next_sem = f"با توجه به معدل فعلی ({gpa} از ۱۰۰)، شرکت در جلسات تقویتی پیش از ورود به سطح بالاتر پیشنهاد می‌شود."

    for a in analytics_data.get('assessments_list', [])[:5]:
        if a.normalized_score_100 is not None:
            evidence_records.append(f"{a.title} ({a.semester_label}): {a.score} از {a.max_score}")

    return {
        'is_ai_generated': True,
        'data_sufficient': True,
        'disclaimer': 'توجه: موارد زیر پیشنهادهای کمک‌آموزشی هوش مصنوعی بر پایه نمرات ثبت‌شده هستند و جایگزین کارنامه رسمی یا نظر استاد نمی‌باشند.',
        'strengths': strengths,
        'areas_needing_improvement': improvements,
        'suggested_activities': activities,
        'next_semester_recommendation': next_sem,
        'evidence_records': evidence_records,
    }
"""

# 5. Clean UTF-8 Templates
FILES["templates/academics/student_profile.html"] = """{% extends 'dashboards/base_dashboard.html' %}
{% block title %}پروفایل و تحلیل تحصیلی {{ target_student.full_name }} | آکادمی زبان تُرنج{% endblock %}
{% block dashboard_body %}
<section class="toranj-card bg-gradient-to-l from-toranj-navy to-toranj-navyLight text-white !border-0">
    <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
        <div class="flex items-center gap-4">
            <div class="w-16 h-16 rounded-2xl bg-toranj-orange text-toranj-textMain font-extrabold text-2xl flex items-center justify-center shadow-md">
                {{ target_student.first_name|slice:":1" }}
            </div>
            <div>
                <div class="flex flex-wrap items-center gap-2.5">
                    <h2 class="text-[22px] font-extrabold">{{ target_student.full_name }}</h2>
                    <span class="px-3 py-1 rounded-full bg-toranj-orange text-toranj-textMain font-mono font-extrabold text-xs" dir="ltr">
                        {{ target_student.academy_username|default:"TRJ-PENDING" }}
                    </span>
                </div>
                <p class="text-[13px] text-gray-200 mt-1">
                    موبایل: <span dir="ltr">{{ target_student.phone }}</span> • سطح: <strong>{{ student_profile.current_level }}</strong>
                </p>
            </div>
        </div>
        <div class="flex items-center gap-3">
            <a href="{% url 'academics:student_report' target_student.id %}" class="btn-primary-orange px-4 !h-[40px] !text-[13px]">گزارش پیشرفت تحصیلی</a>
        </div>
    </div>
</section>

{% if analytics.insufficient_data_reasons %}
<section class="p-4 rounded-2xl bg-amber-50 border border-toranj-warning/40 text-toranj-textMain text-[13px] space-y-1">
    <p class="font-extrabold text-toranj-warning">اطلاعیه شفافیت داده‌های تحلیلی:</p>
    {% for reason in analytics.insufficient_data_reasons %}
        <p class="mr-4 text-toranj-textMuted">• {{ reason }}</p>
    {% endfor %}
</section>
{% endif %}

<section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    <div class="toranj-card">
        <span class="text-[12px] text-toranj-textMuted font-bold">معدل کل (GPA)</span>
        <p class="text-[24px] font-extrabold text-toranj-navy mt-1">{{ analytics.overall_gpa_100|default:"ثبت نشده" }}</p>
    </div>
    <div class="toranj-card">
        <span class="text-[12px] text-toranj-textMuted font-bold">تغییرات نسبت به ترم قبل</span>
        <p class="text-[20px] font-extrabold text-toranj-success mt-1" dir="ltr">{{ analytics.semester_delta|default:"—" }}</p>
    </div>
    <div class="toranj-card">
        <span class="text-[12px] text-toranj-textMuted font-bold">نرخ حضور در جلسات</span>
        <p class="text-[24px] font-extrabold text-toranj-success mt-1">{% if analytics.attendance.attendance_rate is not None %}{{ analytics.attendance.attendance_rate }}٪{% else %}ثبت نشده{% endif %}</p>
    </div>
    <div class="toranj-card">
        <span class="text-[12px] text-toranj-textMuted font-bold">نرخ تکمیل تکالیف</span>
        <p class="text-[24px] font-extrabold text-toranj-navy mt-1">{% if analytics.assignments.completion_rate is not None %}{{ analytics.assignments.completion_rate }}٪{% else %}ثبت نشده{% endif %}</p>
    </div>
</section>

<section class="toranj-card space-y-4">
    <h3 class="text-[17px] font-extrabold text-toranj-textMain">تحلیل عملکرد ۶ مهارت زبانی (Speaking, Listening, Reading, Writing, Grammar, Vocabulary)</h3>
    <div class="space-y-3">
        {% for sk in analytics.skills_breakdown %}
        <div>
            <div class="flex justify-between text-[13px] mb-1">
                <span class="font-bold">{{ sk.label }}</span>
                <span>{% if sk.has_data %}{{ sk.average }} / ۱۰۰{% else %}ارزیابی ثبت نشده{% endif %}</span>
            </div>
            <div class="w-full h-3 bg-toranj-inputBg border border-toranj-border rounded-full overflow-hidden">
                {% if sk.has_data %}<div class="h-full bg-toranj-navy rounded-full" style="width: {{ sk.average }}%"></div>{% endif %}
            </div>
        </div>
        {% endfor %}
    </div>
</section>

<section class="toranj-card space-y-3">
    <h3 class="text-[16px] font-extrabold text-toranj-navy">پیشنهادهای کمک‌آموزشی هوش مصنوعی (مستند به نمرات)</h3>
    <p class="text-[12px] text-toranj-textMuted">{{ ai_recommendations.disclaimer }}</p>
    <p class="text-[14px] font-semibold text-toranj-textMain">{{ ai_recommendations.next_semester_recommendation }}</p>
</section>

<section class="toranj-card space-y-3">
    <h3 class="text-[16px] font-extrabold text-toranj-textMain">یادداشت‌های آموزشی اساتید</h3>
    {% for note in teacher_notes %}
        <div class="p-3 rounded-xl bg-toranj-inputBg border border-toranj-border text-[13px]">
            <strong>{{ note.author.full_name }}:</strong> {{ note.note_text }}
        </div>
    {% empty %}
        <p class="text-[13px] text-toranj-textMuted">یادداشتی ثبت نشده است.</p>
    {% endfor %}
</section>
{% endblock %}
"""

FILES["templates/academics/teacher_profile.html"] = """{% extends 'dashboards/base_dashboard.html' %}
{% block title %}پروفایل استاد | آکادمی زبان تُرنج{% endblock %}
{% block dashboard_body %}
<section class="toranj-card">
    <h2 class="text-[20px] font-extrabold text-toranj-textMain">استاد {{ target_teacher.full_name }}</h2>
    <p class="text-[13px] text-toranj-textMuted mt-1">تخصص: {{ teacher_profile.specialization }}</p>
</section>
<section class="toranj-card space-y-4">
    <h3 class="text-[17px] font-extrabold">زبان‌آموزان تحت تدریس من</h3>
    {% for item in current_students_analytics %}
        <div class="p-3 rounded-xl border border-toranj-border flex justify-between items-center text-[13px]">
            <span>{{ item.student.full_name }} (معدل: {{ item.summary.overall_gpa_100|default:"—" }})</span>
            <a href="{% url 'academics:student_profile' item.student.id %}" class="btn-primary-navy px-3 !h-[36px] !text-xs">مشاهده پروفایل</a>
        </div>
    {% empty %}
        <p class="text-[13px] text-toranj-textMuted">زبان‌آموزی ثبت نشده است.</p>
    {% endfor %}
</section>
{% endblock %}
"""

FILES["templates/academics/admin_analytics_hub.html"] = """{% extends 'dashboards/base_dashboard.html' %}
{% block title %}مرکز پایش تحلیلی | آکادمی زبان تُرنج{% endblock %}
{% block dashboard_body %}
<section class="toranj-card space-y-4">
    <h2 class="text-[19px] font-extrabold text-toranj-textMain">مرکز پایش تحلیلی زبان‌آموزان و اساتید</h2>
    <p class="text-[13px] text-toranj-textMuted">تعداد زبان‌آموزان نیازمند پشتیبانی: {{ at_risk_count }}</p>
    <div class="space-y-2">
        {% for row in student_rows %}
            <div class="p-3 rounded-xl bg-toranj-inputBg border border-toranj-border flex justify-between items-center text-[13px]">
                <span><strong>{{ row.student.full_name }}</strong> — معدل: {{ row.analytics.overall_gpa_100|default:"—" }}</span>
                <a href="{% url 'academics:student_profile' row.student.id %}" class="px-3 py-1 rounded badge-info font-bold text-xs">مشاهده پرونده</a>
            </div>
        {% endfor %}
    </div>
</section>
{% endblock %}
"""

FILES["templates/academics/student_progress_report.html"] = """{% extends 'dashboards/base_dashboard.html' %}
{% block title %}گزارش پیشرفت تحصیلی | آکادمی زبان تُرنج{% endblock %}
{% block dashboard_body %}
<div class="toranj-card max-w-3xl mx-auto space-y-4">
    <h2 class="text-[20px] font-extrabold text-toranj-navy">گزارش پیشرفت تحصیلی: {{ target_student.full_name }}</h2>
    <p class="text-[14px]">معدل کل: <strong>{{ analytics.overall_gpa_100|default:"ثبت نشده" }}</strong></p>
</div>
{% endblock %}
"""

for rel_path, content in FILES.items():
    full_path = BASE / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"[OK] Updated cleanly: {rel_path}")