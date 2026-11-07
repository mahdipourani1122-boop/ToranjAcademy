from django.shortcuts import render
from django.http import Http404
from django.apps import apps
from django.contrib.auth import get_user_model

DEPARTMENTS_DATA = {
    'english': {
        'slug': 'english',
        'name_short': 'زبان انگلیسی',
        'title_fa': 'دپارتمان زبان انگلیسی',
        'title_en': 'British & International Academic English',
        'flag_emoji': '🇬🇧',
        'code_label': 'UK • A1–C2',
        'exam_focus': 'IELTS • Cambridge • Academic English',
        'image': 'https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?auto=format&fit=crop&w=1000&q=80',
        'short_desc': 'آموزش آکادمیک و بین‌المللی زبان انگلیسی با تمرکز بر مهارت‌های چهارگانه، مکالمه پیشرفته و آمادگی آزمون‌های IELTS و کمبریج.',
        'hero_heading': 'تسلط آکادمیک و بین‌المللی بر زبان انگلیسی 🇬🇧',
        'full_intro': 'دپارتمان زبان انگلیسی آموزشگاه تُرَنج با تکیه بر استانداردهای آموزشی بریتانیا و چارچوب CEFR، زبان‌آموزان را از سطح پایه تا تسلط کامل آکادمیک و حرفه‌ای همراهی می‌کند.',
        'levels': ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'],
        'methodology': 'بهره‌گیری از متد Communicative و Task-Based Learning با تمرکز بر لهجه استاندارد، نگارش آکادمیک و شبیه‌سازی آزمون‌های بین‌المللی.',
        'benefits': [
            'آمادگی کامل برای آزمون‌های بین‌المللی IELTS و مدارک کمبریج',
            'تقویت مهارت Speaking و مکالمه روان در محیط‌های علمی و کاری',
            'پیگیری دقیق نمرات و پیشرفت زبان‌آموز در پورتال اختصاصی تُرَنج',
        ],
        'cefr_details': [
            {'code': 'A1', 'title_en': 'Beginner', 'title_fa': 'مبتدی پایه', 'desc': 'آشنایی با ساختارهای پایه، معرفی خود و مکالمات روزمره ساده.'},
            {'code': 'A2', 'title_en': 'Elementary', 'title_fa': 'مقدماتی', 'desc': 'برقراری ارتباط در موقعیت‌های روزمره، خرید، سفر و توصیف محیط.'},
            {'code': 'B1', 'title_en': 'Intermediate', 'title_fa': 'متوسط', 'desc': 'ورود به مرحله استقلال زبانی، بیان تجربیات، اهداف و نگارش متون منسجم.'},
            {'code': 'B2', 'title_en': 'Upper-Intermediate', 'title_fa': 'فرامتوسط', 'desc': 'درک متون پیچیده، بحث‌های تخصصی و مکالمه روان بدون مکث طولانی.'},
            {'code': 'C1', 'title_en': 'Advanced', 'title_fa': 'پیشرفته آکادمیک', 'desc': 'تسلط بالا برای تحصیل در دانشگاه‌های بین‌المللی و محیط‌های حرفه‌ای.'},
            {'code': 'C2', 'title_en': 'Mastery', 'title_fa': 'تسلط کامل', 'desc': 'بالاترین سطح استاندارد جهانی معادل گویشوران تحصیل‌کرده زبان انگلیسی.'},
        ],
        'faqs': [
            {'q': 'منابع آموزشی دپارتمان انگلیسی بر چه استانداردی است؟', 'a': 'سرفصل‌ها بر اساس استاندارد British و بین‌المللی منطبق بر CEFR طراحی شده‌اند.'},
            {'q': 'آیا کلاس‌های آمادگی آیلتس هم برگزار می‌شود؟', 'a': 'بله، پس از تعیین سطح و رسیدن به سطح B1/B2 می‌توانید وارد دوره‌های تخصصی IELTS شوید.'},
        ],
    },
    'german': {
        'slug': 'german',
        'name_short': 'زبان آلمانی',
        'title_fa': 'دپارتمان زبان آلمانی',
        'title_en': 'German Department • Goethe & TestDaF',
        'flag_emoji': '🇩🇪',
        'code_label': 'DE • A1–C1',
        'exam_focus': 'Goethe-Zertifikat • ÖSD • TestDaF',
        'image': 'https://images.unsplash.com/photo-1467269204594-9661b134dd2b?auto=format&fit=crop&w=1000&q=80',
        'short_desc': 'برنامه‌ریزی دقیق و ساختارمند ویژه متقاضیان تحصیل، کار و مهاجرت به آلمان، اتریش و سوئیس با تمرکز بر آزمون‌های گوته و ÖSD.',
        'hero_heading': 'آموزش دقیق و ساختارمند زبان آلمانی 🇩🇪',
        'full_intro': 'دپارتمان آلمانی تُرَنج با ساختاری منظم و گام‌به‌گام، زبان‌آموزان را برای کسب مدارک رسمی سفارت (Goethe، ÖSD و TestDaF) و زندگی تحصیلی و کاری در کشورهای آلمانی‌زبان آماده می‌سازد.',
        'levels': ['A1', 'A2', 'B1', 'B2', 'C1'],
        'methodology': 'آموزش سیستماتیک گرامر و واژگان کاربردی همراه با تمرین مستمر ماک‌های امتحانی گوته (Lesen, Hören, Schreiben, Sprechen).',
        'benefits': [
            'پوشش کامل سرفصل‌های آزمون‌های Goethe و ÖSD از سطح A1 تا C1',
            'آموزش ساختارمند گرامر آلمانی به زبان ساده و کاربردی',
            'شبیه‌سازی بخش شفاهی (Sprechen) و نگارش نامه‌های رسمی و آکادمیک',
        ],
        'cefr_details': [
            {'code': 'A1', 'title_en': 'Start Deutsch 1', 'title_fa': 'سطح پایه A1', 'desc': 'شروع یادگیری آلمانی، جمله‌سازی پایه و مکالمات اولیه روزمره.'},
            {'code': 'A2', 'title_en': 'Goethe-Zertifikat A2', 'title_fa': 'سطح مقدماتی A2', 'desc': 'گسترش دایره واژگان و درک مکالمات روزمره و محیط کار.'},
            {'code': 'B1', 'title_en': 'Zertifikat Deutsch B1', 'title_fa': 'سطح متوسط B1', 'desc': 'سطح کلیدی مورد نیاز برای بسیاری از ویزاهای کاری، آوسبیلدونگ و پیوست.'},
            {'code': 'B2', 'title_en': 'Goethe / ÖSD B2', 'title_fa': 'سطح فرامتوسط B2', 'desc': 'مکالمه تخصصی و پیش‌نیاز اصلی ورود به کالج‌ها و محیط‌های حرفه‌ای آلمان.'},
            {'code': 'C1', 'title_en': 'Hochschulzugang C1', 'title_fa': 'سطح پیشرفته دانشگاهی C1', 'desc': 'تسلط آکادمیک برای تحصیل مستقیم در دانشگاه‌های آلمان و اتریش.'},
        ],
        'faqs': [
            {'q': 'برای مهاجرت تحصیلی یا کاری به چه سطحی از آلمانی نیاز است؟', 'a': 'بسته به رشته و نوع ویزا، معمولاً سطح B1 یا B2 (و برای برخی رشته‌های دانشگاهی C1) مورد نیاز است.'},
        ],
    },
    'french': {
        'slug': 'french',
        'name_short': 'زبان فرانسوی',
        'title_fa': 'دپارتمان زبان فرانسوی',
        'title_en': 'French Department • DELF / DALF & TCF',
        'flag_emoji': '🇫🇷',
        'code_label': 'FR • A1–C1',
        'exam_focus': 'DELF • DALF • TCF / TEF',
        'image': 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?auto=format&fit=crop&w=1000&q=80',
        'short_desc': 'یادگیری اصولی زبان فرانسوی با تلفظ استاندارد، درک فرهنگی و آمادگی آزمون‌های بین‌المللی DELF، DALF و TCF.',
        'hero_heading': 'ظرافت زبانی و تسلط آکادمیک در دپارتمان فرانسوی 🇫🇷',
        'full_intro': 'در دپارتمان زبان فرانسوی آموزشگاه تُرَنج، زیبایی و ساختار دقیق زبان فرانسه با متدهای روز اروپا آموزش داده می‌شود تا زبان‌آموزان برای تحصیل در فرانسه، کانادا و سوئیس یا مطالعه ادبیات و هنر آماده شوند.',
        'levels': ['A1', 'A2', 'B1', 'B2', 'C1'],
        'methodology': 'تمرکز ویژه بر آواشناسی (Phonétique)، درک شنیداری سریع و نگارش ساختارمند فرانسوی مطابق استانداردهای DELF/DALF.',
        'benefits': [
            'آمادگی هدفمند برای آزمون‌های DELF، DALF، TCF و TEF',
            'آموزش دقیق قواعد تلفظ و گفتار روان فرانسوی از سطح A1',
            'مناسب برای متقاضیان تحصیل در دانشگاه‌های فرانسه و مهاجرت به کانادا',
        ],
        'cefr_details': [
            {'code': 'A1', 'title_en': 'DELF A1', 'title_fa': 'سطح پایه A1', 'desc': 'آشنایی با آواها، تلفظ صحیح و مکالمات مقدماتی روزمره.'},
            {'code': 'A2', 'title_en': 'DELF A2', 'title_fa': 'سطح مقدماتی A2', 'desc': 'توانایی بیان نیازهای روزمره و درک متون کوتاه فرانسوی.'},
            {'code': 'B1', 'title_en': 'DELF B1', 'title_fa': 'سطح متوسط B1', 'desc': 'بیان دیدگاه‌ها، روایت رویدادها و مکالمه مستقل در سفر و کار.'},
            {'code': 'B2', 'title_en': 'DELF B2', 'title_fa': 'سطح فرامتوسط B2', 'desc': 'سطح استاندارد پذیرش در دانشگاه‌های فرانسه و استدلال حرفه‌ای.'},
            {'code': 'C1', 'title_en': 'DALF C1', 'title_fa': 'سطح پیشرفته C1', 'desc': 'تسلط کامل بر متون آکادمیک، ادبی و سخنرانی حرفه‌ای.'},
        ],
        'faqs': [
            {'q': 'آیا دوره‌ها برای آزمون TCF و مهاجرت کانادا نیز مناسب است؟', 'a': 'بله، تمامی مهارت‌های چهارگانه مورد نیاز آزمون‌های TCF، TEF و DELF پوشش داده می‌شوند.'},
        ],
    },
    'turkish': {
        'slug': 'turkish',
        'name_short': 'ترکی استانبولی',
        'title_fa': 'دپارتمان ترکی استانبولی',
        'title_en': 'Istanbul Turkish • TÖMER Standard',
        'flag_emoji': '🇹🇷',
        'code_label': 'TR • A1–C1',
        'exam_focus': 'Istanbul Turkish • TÖMER & YÖS',
        'image': 'https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?auto=format&fit=crop&w=1000&q=80',
        'short_desc': 'آموزش کاربردی و معیار زبان ترکی استانبولی ویژه مکالمه روزمره، تجارت، زندگی و دریافت مدرک معتبر TÖMER دانشگاه‌های ترکیه.',
        'hero_heading': 'مکالمه روان و تسلط کاربردی بر ترکی استانبولی 🇹🇷',
        'full_intro': 'دپارتمان ترکی استانبولی آموزشگاه تُرَنج بر پایه استاندارد دانشگاه استانبول (مجموعه آموزشی İstanbul) طراحی شده و زبان‌آموزان را برای مکالمه روان، محیط‌های تجاری و آزمون بین‌المللی TÖMER آماده می‌کند.',
        'levels': ['A1', 'A2', 'B1', 'B2', 'C1'],
        'methodology': 'تدریس بر اساس سیستم آموزشی دانشگاه استانبول با تمرکز بر لهجه معیار استانبولی، اصطلاحات روزمره و مهارت‌های آزمون تومر.',
        'benefits': [
            'تمرکز کامل بر لهجه معیار ترکی استانبولی (Istanbul Turkish)',
            'آمادگی کامل جهت کسب مدرک TÖMER برای پذیرش دانشگاه‌های ترکیه',
            'پیشرفت سریع در مکالمات روزمره، سفر و مذاکرات کاری',
        ],
        'cefr_details': [
            {'code': 'A1', 'title_en': 'Temel A1', 'title_fa': 'سطح پایه A1', 'desc': 'الفبا، قواعد هماهنگی مصوت‌ها و مکالمات ضروری روزمره در استانبول.'},
            {'code': 'A2', 'title_en': 'Temel A2', 'title_fa': 'سطح مقدماتی A2', 'desc': 'گسترش جمله‌سازی در زمان‌های مختلف و ارتباط راحت در سفر و خرید.'},
            {'code': 'B1', 'title_en': 'Orta B1', 'title_fa': 'سطح متوسط B1', 'desc': 'مکالمه روان درباره موضوعات اجتماعی، کاری و درک رسانه‌های ترکی.'},
            {'code': 'B2', 'title_en': 'Orta B2', 'title_fa': 'سطح فرامتوسط B2', 'desc': 'سطح مورد نیاز اکثر دانشگاه‌های ترکیه و ارتباطات رسمی و تجاری.'},
            {'code': 'C1', 'title_en': 'İleri C1', 'title_fa': 'سطح پیشرفته TÖMER C1', 'desc': 'تسلط کامل آکادمیک و دریافت بالاترین سطح مدرک رسمی TÖMER.'},
        ],
        'faqs': [
            {'q': 'چه منبعی در دپارتمان ترکی استانبولی تدریس می‌شود؟', 'a': 'سری کتاب‌های استاندارد دانشگاه استانبول (Yeni İstanbul) به همراه منابع تکمیلی آزمون TÖMER.'},
        ],
    },
}


def _get_real_courses(language_slug=None):
    """واکشی ایمن دوره‌های واقعی از دیتابیس بدون تولید داده ساختگی"""
    courses_list = []
    try:
        CourseModel = apps.get_model('courses', 'Course')
        qs = CourseModel.objects.all()
        if hasattr(CourseModel, 'is_active'):
            qs = qs.filter(is_active=True)

        for c in qs[:12]:
            title = getattr(c, 'title', getattr(c, 'name', str(c)))
            desc = getattr(c, 'description', '')
            level = getattr(c, 'level', '')
            lang = str(getattr(c, 'language', '')).lower()

            if language_slug:
                lang_keywords = {
                    'english': ['en', 'eng', 'english', 'انگلیسی'],
                    'german': ['de', 'ger', 'german', 'آلمانی'],
                    'french': ['fr', 'fre', 'french', 'فرانسوی', 'فرانسه'],
                    'turkish': ['tr', 'tur', 'turkish', 'ترکی'],
                }.get(language_slug, [])
                combined_text = f"{title} {lang}".lower()
                if not any(k in combined_text for k in lang_keywords):
                    continue

            courses_list.append({
                'title': title,
                'description': desc,
                'level': level,
                'language_label': getattr(c, 'get_language_display', lambda: lang)() if lang else 'دوره آموزشی',
            })
    except Exception:
        pass
    return courses_list


def _get_real_teachers():
    """واکشی ایمن اساتید واقعی ثبت‌شده در دیتابیس"""
    teachers_list = []
    try:
        User = get_user_model()
        qs = User.objects.all()
        for u in qs:
            role = str(getattr(u, 'role', '')).lower()
            is_teacher = getattr(u, 'is_teacher', False) or role in ['teacher', 'instructor', 'استاد']
            if is_teacher:
                full_name = u.get_full_name().strip() if hasattr(u, 'get_full_name') else ''
                teachers_list.append({
                    'display_name': full_name or u.username,
                    'role_label': 'عضو هیئت علمی و مدرس تُرَنج',
                })
    except Exception:
        pass
    return teachers_list[:8]


def _get_real_stats(courses_count, teachers_count):
    """محاسبه آمار واقعی از دیتابیس"""
    students_count = 0
    try:
        StudentProfile = apps.get_model('academics', 'StudentProfile')
        students_count = StudentProfile.objects.count()
    except Exception:
        pass

    return {
        'has_real_stats': True,
        'departments_count': 4,
        'courses_count': courses_count,
        'teachers_count': teachers_count,
        'students_count': students_count,
    }


def home_view(request):
    featured_courses = _get_real_courses()
    teachers = _get_real_teachers()
    stats = _get_real_stats(len(featured_courses), len(teachers))

    context = {
        'departments': list(DEPARTMENTS_DATA.values()),
        'featured_courses': featured_courses,
        'teachers': teachers,
        'stats': stats,
    }
    return render(request, 'core/home.html', context)


def department_detail_view(request, slug):
    dept = DEPARTMENTS_DATA.get(slug.lower())
    if not dept:
        raise Http404("دپارتمان مورد نظر یافت نشد.")

    department_courses = _get_real_courses(language_slug=slug.lower())
    teachers = _get_real_teachers()

    context = {
        'dept': dept,
        'department_courses': department_courses,
        'teachers': teachers,
    }
    return render(request, 'core/department_detail.html', context)


# نام‌های جایگزین برای حفظ سازگاری کامل با URLهای قبلی پروژه
home = home_view
index = home_view
language_landing = department_detail_view