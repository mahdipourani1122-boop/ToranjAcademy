from pathlib import Path
from django.conf import settings
from django.db.models import Q
from django.shortcuts import render
from django.views.generic import TemplateView
from accounts.models import User
from accounts.forms import ToranjLoginForm
from accounts.views import UserLoginView
from courses.models import Course, CourseCategory, ClassGroup


LANGUAGE_DEPARTMENTS = {
    'english': {
        'slug': 'english',
        'en_name': 'English',
        'fa_name': 'زبان انگلیسی',
        'flag_emoji': '🇬🇧',
        'flag_code': 'GB',
        'country_label': 'United Kingdom (UK Standard)',
        'tagline': 'آموزش جامع زبان انگلیسی با استاندارد کمبریج و CEFR بریتانیا',
        'description': 'دپارتمان زبان انگلیسی آکادمی تُرنج با پوشش سطوح A1 تا C2، دوره‌های مکالمه‌محور بزرگسالان، نوجوانان و کودکان و کارگاه‌های تخصصی آمادگی IELTS را با اساتید مجرب برگزار می‌کند.',
        'levels': [
            {'code': 'A1 - Beginner', 'title': 'مبتدی (Starter / Beginner)', 'desc': 'ساختارهای پایه، مکالمات روزمره اولیه و تلفظ صحیح استاندارد بریتانیایی.'},
            {'code': 'A2 - Elementary', 'title': 'مقدماتی (Elementary)', 'desc': 'گسترش دامنه واژگان کاربردی، زمان‌های اصلی گرامری و درک متون کوتاه.'},
            {'code': 'B1 - Intermediate', 'title': 'متوسط (Pre-Intermediate & Intermediate)', 'desc': 'مکالمه روان در موقعیت‌های کاری، تحصیلی و سفر به همراه نگارش ساختاریافته.'},
            {'code': 'B2 - Upper-Intermediate', 'title': 'فرامتوسط (Upper-Intermediate)', 'desc': 'بحث‌های تحلیلی، درک فیلم و سخنرانی‌های دانشگاهی و نگارش مقالات استاندارد.'},
            {'code': 'C1/C2 - Advanced & IELTS', 'title': 'پیشرفته و آمادگی آزمون IELTS', 'desc': 'تسلط حرفه‌ای بر هر ۴ مهارت و تکنیک‌های کسب نمره ۷.۵+ در آزمون آیلتس.'},
        ],
        'search_keywords': ['انگلیسی', 'english', 'ielts', 'آیلتس', 'مکالمه', 'conversation', 'b1', 'b2'],
        'template_name': 'core/languages/english.html',
    },
    'german': {
        'slug': 'german',
        'en_name': 'Deutsch',
        'fa_name': 'زبان آلمانی',
        'flag_emoji': '🇩🇪',
        'flag_code': 'DE',
        'country_label': 'Germany (Goethe & ÖSD Standard)',
        'tagline': 'مسیر تخصصی مهاجرت تحصیلی، کاری و آزمون‌های سفارت آلمان',
        'description': 'دپارتمان زبان آلمانی تُرنج بر اساس سرفصل‌های رسمی انستیتو گوته (Goethe-Institut) و آزمون‌های ÖSD و TestDaF طراحی شده و زبان‌آموزان را از سطح پایه A1 تا سطح پیشرفته C1 آماده می‌سازد.',
        'levels': [
            {'code': 'Start Deutsch A1', 'title': 'سطح پایه A1.1 و A1.2', 'desc': 'مبانی ساختار جمله در آلمانی، جنسیت اسامی، مکالمات روزمره و آمادگی آزمون A1 سفارت.'},
            {'code': 'Goethe-Zertifikat A2', 'title': 'سطح مقدماتی A2.1 و A2.2', 'desc': 'گسترش ارتباطات روزمره، گرامر کاربردی و درک متون و پیام‌های رسمی.'},
            {'code': 'Zertifikat Deutsch B1', 'title': 'سطح مستقل B1', 'desc': 'مکالمه مستقل در محیط کار و زندگی در آلمان و قبولی در آزمون رسمی B1 گوته/ÖSD.'},
            {'code': 'Goethe-Zertifikat B2', 'title': 'سطح پیشرفته کاری و تحصیلی B2', 'desc': 'شرط اصلی پذیرش کاری، کالج و کادر درمان در آلمان با تمرکز بر مکاتبات رسمی و تخصصی.'},
            {'code': 'TestDaF / C1 Hochschule', 'title': 'سطح دانشگاهی C1', 'desc': 'آمادگی ورود مستقیم به دانشگاه‌های آلمان و نگارش علمی به زبان آلمانی.'},
        ],
        'search_keywords': ['آلمانی', 'german', 'deutsch', 'گوته', 'goethe', 'testdaf'],
        'template_name': 'core/languages/german.html',
    },
    'french': {
        'slug': 'french',
        'en_name': 'Français',
        'fa_name': 'زبان فرانسوی',
        'flag_emoji': '🇫🇷',
        'flag_code': 'FR',
        'country_label': 'France (DELF / DALF & TCF Standard)',
        'tagline': 'آموزش اصیل زبان فرانسه ویژه مکالمه، تحصیل در فرانسه و مهاجرت به کانادا',
        'description': 'دپارتمان زبان فرانسوی آکادمی تُرنج با تمرکز بر آواشناسی دقیق فرانسوی، مکالمه روان و آمادگی آزمون‌های بین‌المللی DELF، DALF، TCF و TEF مسیر یادگیری شما را هدفمند می‌کند.',
        'levels': [
            {'code': 'DELF A1', 'title': 'سطح آغازین A1 (Découverte)', 'desc': 'آواشناسی و تلفظ صحیح فرانسوی، معرفی خود و تعاملات پایه روزمره.'},
            {'code': 'DELF A2', 'title': 'سطح مقدماتی A2 (Survie)', 'desc': 'مکالمه در موقعیت‌های سفر، خرید و زندگی شهری به همراه زمان‌های گذشته و آینده.'},
            {'code': 'DELF B1', 'title': 'سطح مستقل B1 (Seuil)', 'desc': 'بیان دیدگاه‌ها، روایت رویدادها و درک برنامه‌های رادیویی و تلویزیونی فرانسه.'},
            {'code': 'DELF B2 / TCF', 'title': 'سطح پیشرفته B2 (Avancé)', 'desc': 'کسب حد نصاب پذیرش دانشگاه‌های فرانسه و امتیاز زبان فرانسوی مهاجرت کانادا (TEF/TCF).'},
            {'code': 'DALF C1', 'title': 'سطح تسلط حرفه‌ای C1', 'desc': 'تسلط کامل بر متون ادبی، آکادمیک و سخنرانی حرفه‌ای به زبان فرانسه.'},
        ],
        'search_keywords': ['فرانسوی', 'فرانسه', 'french', 'francais', 'français', 'delf', 'tcf'],
        'template_name': 'core/languages/french.html',
    },
    'turkish': {
        'slug': 'turkish',
        'en_name': 'Türkçe',
        'fa_name': 'زبان ترکی استانبولی',
        'flag_emoji': '🇹🇷',
        'flag_code': 'TR',
        'country_label': 'Turkey (TÖMER Standard)',
        'tagline': 'مکالمه کاربردی، بازرگانی و آمادگی آزمون TÖMER دانشگاه‌های ترکیه',
        'description': 'دپارتمان زبان ترکی استانبولی تُرنج بر اساس متد استاندارد دانشگاه آنکارا (Yeni Hitit / İstanbul) برای اهداف مکالمه روزمره، تجارت، زندگی و تحصیل در دانشگاه‌های ترکیه طراحی شده است.',
        'levels': [
            {'code': 'Temel A1', 'title': 'سطح پایه A1', 'desc': 'الفبای لاتین ترکی، هماهنگی اصوات، پسوندها و مکالمات ضروری سفر و زندگی.'},
            {'code': 'Temel A2', 'title': 'سطح مقدماتی A2', 'desc': 'زمان‌های فعلی، گذشته و آینده و برقراری ارتباط روان در محیط‌های اجتماعی ترکیه.'},
            {'code': 'Orta B1', 'title': 'سطح متوسط B1', 'desc': 'مکالمه درباره موضوعات کاری، خبری و فرهنگی بدون نیاز به مترجم.'},
            {'code': 'Orta B2', 'title': 'سطح فرامتوسط B2', 'desc': 'مذاکرات کاری و تجاری، درک سریال‌ها و اخبار ترکیه و نگارش رسمی.'},
            {'code': 'Yüksek C1 (TÖMER)', 'title': 'سطح پیشرفته و دیپلم TÖMER C1', 'desc': 'اخذ مدرک رسمی تومر جهت ورود به رشته‌های پزشکی، مهندسی و تحصیلات تکمیلی در ترکیه.'},
        ],
        'search_keywords': ['ترکی', 'استانبولی', 'turkish', 'turkce', 'türkçe', 'تومر', 'tomer', 'tömer'],
        'template_name': 'core/languages/turkish.html',
    },
}


def _ensure_subtemplates_and_static_dirs():
    """ایجاد خودکار پوشه static/images و قالب‌های صفحات فرعي در صورت عدم وجود"""
    base_dir = Path(settings.BASE_DIR)
    (base_dir / 'static' / 'images').mkdir(parents=True, exist_ok=True)
    lang_dir = base_dir / 'templates' / 'core' / 'languages'
    lang_dir.mkdir(parents=True, exist_ok=True)

    lang_html = """{% extends 'base.html' %}
{% block title %}دپارتمان {{ dept.fa_name }} ({{ dept.en_name }}) | آکادمی زبان تُرنج{% endblock %}
{% block content %}
<section class="bg-toranj-navy text-white py-12 lg:py-16 border-b border-white/10">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex flex-wrap items-center justify-between gap-4 mb-6 text-[13px] text-gray-300">
            <a href="{% url 'core:home' %}" class="inline-flex items-center gap-1.5 hover:text-toranj-orange font-bold">
                <i data-lucide="arrow-right" class="w-4 h-4"></i>
                <span>بازگشت به صفحه اصلی آکادمی تُرنج</span>
            </a>
            <div class="flex flex-wrap gap-2">
                {% for d in all_departments %}
                    <a href="/languages/{{ d.slug }}/" class="px-3 py-1 rounded-lg border {% if d.slug == dept.slug %}bg-toranj-orange text-toranj-textMain border-toranj-orange font-extrabold{% else %}border-white/15 hover:bg-white/10{% endif %}">
                        <span>{{ d.flag_emoji }} {{ d.fa_name }}</span>
                    </a>
                {% endfor %}
            </div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
            <div class="lg:col-span-8 space-y-4">
                <div class="inline-flex items-center gap-2.5 px-3.5 py-1.5 rounded-full bg-white/10 border border-white/15 text-[13px] font-bold">
                    <span class="text-2xl">{{ dept.flag_emoji }}</span>
                    <span dir="ltr">{{ dept.en_name }} • {{ dept.country_label }}</span>
                </div>
                <h1 class="text-[28px] sm:text-[38px] font-black leading-tight">دپارتمان تخصصی {{ dept.fa_name }} ({{ dept.en_name }})</h1>
                <p class="text-[16px] text-toranj-orange font-bold">{{ dept.tagline }}</p>
                <p class="text-[14px] sm:text-[15px] text-gray-200 leading-relaxed max-w-3xl">{{ dept.description }}</p>
                <div class="pt-3 flex flex-wrap gap-3">
                    <a href="{% url 'accounts:register' %}" class="btn-primary-orange px-6">ثبت‌نام و تعیین سطح {{ dept.fa_name }}</a>
                    <a href="#dept-courses" class="px-5 h-[46px] rounded-xl bg-white/10 hover:bg-white/15 border border-white/20 font-bold text-[13px] inline-flex items-center">مشاهده دوره‌های موجود</a>
                </div>
            </div>
            <div class="lg:col-span-4">
                <div class="p-6 rounded-3xl bg-white/5 border border-white/15 text-center space-y-3">
                    <div class="text-6xl">{{ dept.flag_emoji }}</div>
                    <h2 class="text-[22px] font-black text-white" dir="ltr">{{ dept.en_name }}</h2>
                    <p class="text-[14px] font-bold text-toranj-orange">{{ dept.fa_name }}</p>
                </div>
            </div>
        </div>
    </div>
</section>
<section class="py-12 lg:py-16 bg-toranj-bg">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-10">
        <div>
            <h2 class="text-[22px] sm:text-[26px] font-black text-toranj-textMain">سطوح آموزشی استاندارد {{ dept.fa_name }}</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mt-6">
                {% for lvl in dept.levels %}
                <div class="toranj-card space-y-2">
                    <span class="px-2.5 py-1 rounded-lg bg-toranj-navy text-toranj-orange font-mono text-[12px] font-extrabold inline-block" dir="ltr">{{ lvl.code }}</span>
                    <h3 class="text-[16px] font-extrabold text-toranj-textMain pt-1">{{ lvl.title }}</h3>
                    <p class="text-[13px] text-toranj-textMuted leading-relaxed">{{ lvl.desc }}</p>
                </div>
                {% endfor %}
            </div>
        </div>
        <div id="dept-courses" class="space-y-4">
            <h2 class="text-[22px] font-black text-toranj-textMain">دوره‌های فعال {{ dept.fa_name }} در پایگاه داده</h2>
            {% if department_courses %}
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {% for course in department_courses %}
                    <article class="toranj-card flex flex-col justify-between space-y-4">
                        <div>
                            <h3 class="text-[18px] font-extrabold text-toranj-textMain">{{ course.title }}</h3>
                            <p class="text-[13px] text-toranj-textMuted mt-1">{{ course.description }}</p>
                        </div>
                        <div class="pt-3 border-t border-toranj-border flex items-center justify-between">
                            <span class="font-bold text-toranj-navy">{{ course.tuition_fee }} تومان</span>
                            <a href="{% url 'courses:catalog' %}?q={{ course.title|urlencode }}" class="btn-primary-orange px-4 !h-[38px] !text-[12px]">مشاهده و ثبت‌نام</a>
                        </div>
                    </article>
                    {% endfor %}
                </div>
            {% else %}
                <div class="toranj-card text-center py-8 space-y-3">
                    <p class="text-[15px] font-extrabold text-toranj-textMain">در حال حاضر دوره منتشرشده‌ای برای «{{ dept.fa_name }}» در دیتابیس ثبت نشده است.</p>
                    <a href="{% url 'accounts:register' %}" class="btn-primary-orange px-6">ثبت‌نام اولیه زبان‌آموز</a>
                </div>
            {% endif %}
        </div>
    </div>
</section>
{% endblock %}"""

    for key in ['english', 'german', 'french', 'turkish']:
        (lang_dir / f'{key}.html').write_text(lang_html, encoding='utf-8')

    guest_file = base_dir / 'templates' / 'core' / 'guest_explore.html'
    guest_file.write_text("""{% extends 'base.html' %}
{% block title %}گشت‌وگذار مهمان | آکادمی زبان تُرنج{% endblock %}
{% block content %}
<section class="py-12 lg:py-16 bg-toranj-bg">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 space-y-8">
        <div class="toranj-card bg-toranj-navy text-white flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div>
                <span class="px-3 py-1 rounded-full bg-white/10 text-toranj-orange text-[12px] font-bold">حالت بازدیدکننده مهمان (Guest Mode)</span>
                <h1 class="text-[24px] sm:text-[30px] font-black mt-2">آشنایی با دپارتمان‌ها و دوره‌های آکادمی زبان تُرنج</h1>
                <p class="text-[13px] text-gray-300 mt-1">شما بدون نیاز به ثبت‌نام در حال مشاهده بخش‌های عمومی هستید. برای ثبت‌نام در کلاس یا مشاهده کارنامه، وارد حساب زبان‌آموز شوید.</p>
            </div>
            <div class="flex gap-3 shrink-0">
                <a href="{% url 'accounts:register' %}" class="btn-primary-orange px-5">ثبت‌نام زبان‌آموز</a>
                <a href="{% url 'core:student_portal_login' %}" class="px-4 py-2.5 rounded-xl border border-white/25 text-white font-bold text-[13px] flex items-center">ورود دانشجو</a>
            </div>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {% for lang in languages %}
            <a href="/languages/{{ lang.slug }}/" class="toranj-card toranj-card-hover flex items-center justify-between">
                <div>
                    <h2 class="text-[16px] font-extrabold text-toranj-textMain">{{ lang.fa_name }}</h2>
                    <span class="text-[12px] text-toranj-textMuted" dir="ltr">{{ lang.en_name }}</span>
                </div>
                <span class="text-3xl">{{ lang.flag_emoji }}</span>
            </a>
            {% endfor %}
        </div>
    </div>
</section>
{% endblock %}""", encoding='utf-8')

    role_login_file = base_dir / 'templates' / 'accounts' / 'role_login.html'
    role_login_file.write_text("""{% extends 'accounts/base_auth.html' %}
{% block title %}{{ portal.title }} | آکادمی زبان تُرنج{% endblock %}
{% block auth_content %}
<div class="text-center mb-6">
    <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-toranj-navy/10 text-toranj-navy text-[12px] font-extrabold mb-3">
        <span>{{ portal.badge }}</span>
    </span>
    <h1 class="text-[22px] sm:text-[24px] font-extrabold text-toranj-textMain">{{ portal.title }}</h1>
    <p class="text-[13px] text-toranj-textMuted mt-1">{{ portal.subtitle }}</p>
</div>
{% if form.non_field_errors %}
    <div class="mb-4 p-3.5 rounded-xl bg-toranj-error/10 border border-toranj-error/30 text-toranj-error text-[13px]">
        {% for error in form.non_field_errors %}<p>{{ error }}</p>{% endfor %}
    </div>
{% endif %}
<form method="post" class="auth-form space-y-4" novalidate>
    {% csrf_token %}
    <div>
        <label class="block text-[13px] font-bold text-toranj-textMain mb-1.5">{{ form.identifier.label }}</label>
        {{ form.identifier }}
    </div>
    <div>
        <label class="block text-[13px] font-bold text-toranj-textMain mb-1.5">رمز عبور</label>
        {{ form.password }}
    </div>
    <button type="submit" class="w-full btn-primary-orange">ورود امن به پنل</button>
</form>
<div class="mt-6 pt-4 border-t border-toranj-border text-center text-[13px] text-toranj-textMuted">
    {% if portal.allow_registration %}
        زبان‌آموز جدید هستید؟ <a href="{% url 'accounts:register' %}" class="font-extrabold text-toranj-navy hover:text-toranj-orange">ثبت‌نام زبان‌آموز جدید</a>
    {% else %}
        حساب کاربری اساتید صرفاً توسط مدیریت آکادمی زبان تُرنج صادر می‌شود.
    {% endif %}
</div>
{% endblock %}""", encoding='utf-8')


try:
    _ensure_subtemplates_and_static_dirs()
except Exception:
    pass


class HomePageView(TemplateView):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        published_courses = Course.objects.filter(
            publication_status='published', is_deleted=False
        ).select_related('category').prefetch_related('classes')[:6]
        categories = CourseCategory.objects.filter(is_active=True)
        teachers = User.objects.filter(role=User.Role.TEACHER, is_active=True)[:6]

        context['languages'] = list(LANGUAGE_DEPARTMENTS.values())
        context['featured_courses'] = published_courses
        context['categories'] = categories
        context['teachers'] = teachers
        return context


class LanguageDepartmentLandingView(TemplateView):
    language_key = 'english'

    def get_template_names(self):
        _ensure_subtemplates_and_static_dirs()
        dept = LANGUAGE_DEPARTMENTS[self.language_key]
        return [dept['template_name']]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dept = LANGUAGE_DEPARTMENTS[self.language_key]
        context['dept'] = dept
        context['all_departments'] = list(LANGUAGE_DEPARTMENTS.values())

        q_filter = Q()
        for kw in dept['search_keywords']:
            q_filter |= Q(title__icontains=kw) | Q(description__icontains=kw) | Q(category__name__icontains=kw)

        courses_qs = Course.objects.filter(
            publication_status='published', is_deleted=False
        ).filter(q_filter).select_related('category').distinct()
        context['department_courses'] = courses_qs
        return context


class GuestExploreView(TemplateView):
    template_name = 'core/guest_explore.html'

    def get_context_data(self, **kwargs):
        _ensure_subtemplates_and_static_dirs()
        context = super().get_context_data(**kwargs)
        context['languages'] = list(LANGUAGE_DEPARTMENTS.values())
        context['published_courses'] = Course.objects.filter(
            publication_status='published', is_deleted=False
        ).select_related('category')[:12]
        context['teachers'] = User.objects.filter(role=User.Role.TEACHER, is_active=True)[:8]
        return context


class RolePortalLoginView(UserLoginView):
    portal_type = 'student'
    template_name = 'accounts/role_login.html'

    def get_portal_meta(self):
        meta_map = {
            'student': {
                'title': 'ورود دانشجویان به سامانه تُرنج',
                'subtitle': 'با کد کاربری آکادمی (TRJ-26XXXX) یا شماره موبایل تأییدشده وارد شوید',
                'badge': 'پرتال زبان‌آموزان (Student Portal)',
                'allowed_roles': [User.Role.STUDENT],
                'allow_registration': True,
            },
            'teacher': {
                'title': 'ورود اساتید آکادمی زبان تُرنج',
                'subtitle': 'ویژه اساتید رسمی دارای حساب کاربری صادرشده توسط آموزشگاه',
                'badge': 'پرتال اساتید (Teacher Portal)',
                'allowed_roles': [User.Role.TEACHER],
                'allow_registration': False,
            },
            'management': {
                'title': 'ورود کادر نظارت و مدیریت تُرنج',
                'subtitle': 'ویژه مدیران و سوپروایزرهای آموزشی',
                'badge': 'پرتال مدیریت (Management Portal)',
                'allowed_roles': [User.Role.ADMIN, User.Role.SUPERVISOR],
                'allow_registration': False,
            },
        }
        return meta_map.get(self.portal_type, meta_map['student'])

    def get(self, request):
        _ensure_subtemplates_and_static_dirs()
        return render(request, self.template_name, {
            'form': ToranjLoginForm(),
            'portal': self.get_portal_meta(),
            'portal_type': self.portal_type,
        })

    def post(self, request):
        _ensure_subtemplates_and_static_dirs()
        portal_meta = self.get_portal_meta()
        form = ToranjLoginForm(request=request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.role not in portal_meta['allowed_roles']:
                form.add_error(
                    None,
                    f"دسترسی غیرمجاز: این درگاه فقط مخصوص «{portal_meta['badge']}» است."
                )
                return render(request, self.template_name, {
                    'form': form,
                    'portal': portal_meta,
                    'portal_type': self.portal_type,
                }, status=403)
        return super().post(request)