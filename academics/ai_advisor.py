SKILL_PRACTICE_BANK = {
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
