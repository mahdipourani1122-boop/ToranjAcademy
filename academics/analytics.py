from collections import defaultdict
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
