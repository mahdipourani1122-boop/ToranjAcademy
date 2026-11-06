from datetime import date, time
from django.test import TestCase
from django.urls import reverse
from accounts.models import User
from courses.models import CourseCategory, Course, ClassGroup, ClassSession, Enrollment
from .models import (
    AttendanceRecord,
    AcademicAssessment,
    SkillAssessmentScore,
    TeacherStudentNote,
    HistoricalStudentAccess,
)
from .analytics import compute_student_academic_analytics
from .ai_advisor import generate_grounded_ai_recommendations


class UnifiedProfilesAndAcademicAnalyticsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            phone='09120000100', first_name='مدیر', last_name='کل', password='StrongPassword123!'
        )
        self.teacher_assigned = User.objects.create_user(
            phone='09120000101', first_name='استاد', last_name='مربوطه',
            password='StrongPassword123!', role=User.Role.TEACHER, status=User.Status.ACTIVE
        )
        self.student1 = User.objects.create_user(
            phone='09120000103', first_name='زبان‌آموز', last_name='اول',
            password='StrongPassword123!', role=User.Role.STUDENT, status=User.Status.ACTIVE,
            academy_username='TRJ-260101'
        )
        self.student2 = User.objects.create_user(
            phone='09120000104', first_name='زبان‌آموز', last_name='دوم',
            password='StrongPassword123!', role=User.Role.STUDENT, status=User.Status.ACTIVE,
            academy_username='TRJ-260102'
        )

        self.cat = CourseCategory.objects.create(name='بزرگسالان', slug='adults-test')
        self.course = Course.objects.create(
            title='Intermediate B1', slug='int-b1-test', description='desc',
            category=self.cat, learning_objectives='obj',
            publication_status=Course.PublicationStatus.PUBLISHED,
            enrollment_status=Course.EnrollmentStatus.OPEN,
        )
        self.class_group = ClassGroup.objects.create(
            course=self.course, name='گروه الف', code='CLS-101',
            teacher=self.teacher_assigned,
            start_date=date(2026, 10, 1), end_date=date(2026, 12, 1),
            days_of_week='sat,mon', start_time=time(18, 0), end_time=time(19, 30),
            max_capacity=15, location_or_link='Room 1', status=ClassGroup.ClassStatus.ACTIVE
        )
        self.enrollment1 = Enrollment.objects.create(
            student=self.student1, course=self.course, class_group=self.class_group,
            status=Enrollment.Status.APPROVED
        )

    def _login_2fa(self, user):
        self.client.force_login(user, backend='accounts.backends.ToranjAuthenticationBackend')
        s = self.client.session
        s['is_2fa_verified'] = True
        s.save()

    def test_1_student_can_only_view_own_profile_and_idor_is_blocked(self):
        self._login_2fa(self.student1)
        own_res = self.client.get(reverse('academics:student_profile', args=[self.student1.id]))
        self.assertEqual(own_res.status_code, 200)

        other_res = self.client.get(reverse('academics:student_profile', args=[self.student2.id]))
        self.assertEqual(other_res.status_code, 403)

    def test_2_teacher_can_only_access_authorized_students_and_historical_grants(self):
        self._login_2fa(self.teacher_assigned)
        ok_res = self.client.get(reverse('academics:student_profile', args=[self.student1.id]))
        self.assertEqual(ok_res.status_code, 200)

        denied_res = self.client.get(reverse('academics:student_profile', args=[self.student2.id]))
        self.assertEqual(denied_res.status_code, 403)

        HistoricalStudentAccess.objects.create(
            teacher=self.teacher_assigned, student=self.student2,
            granted_by=self.admin, reason='بررسی پرونده ترم قبل', is_active=True
        )
        granted_res = self.client.get(reverse('academics:student_profile', args=[self.student2.id]))
        self.assertEqual(granted_res.status_code, 200)

    def test_3_private_teacher_notes_are_hidden_from_student(self):
        TeacherStudentNote.objects.create(
            student=self.student1, author=self.teacher_assigned, class_group=self.class_group,
            note_text='یادداشت محرمانه مخصوص کادر آموزش', is_private_to_staff=True
        )
        self._login_2fa(self.student1)
        res = self.client.get(reverse('academics:student_profile', args=[self.student1.id]))
        self.assertNotContains(res, 'یادداشت محرمانه مخصوص کادر آموزش')

    def test_4_gpa_semester_comparison_skill_averages_and_attendance_calculations(self):
        a1 = AcademicAssessment.objects.create(
            student=self.student1, class_group=self.class_group, semester_label='1405-1',
            title='Midterm 1', assessment_type='midterm', submission_status='graded',
            score=80, max_score=100, weight=1.0
        )
        SkillAssessmentScore.objects.create(assessment=a1, skill='speaking', score=85)
        SkillAssessmentScore.objects.create(assessment=a1, skill='writing', score=62)

        a2 = AcademicAssessment.objects.create(
            student=self.student1, class_group=self.class_group, semester_label='1405-2',
            title='Final 2', assessment_type='final', submission_status='graded',
            score=90, max_score=100, weight=1.0
        )
        SkillAssessmentScore.objects.create(assessment=a2, skill='speaking', score=95)

        s1 = ClassSession.objects.create(
            class_group=self.class_group, session_number=1,
            session_date=date(2026, 10, 3), start_time=time(18, 0), end_time=time(19, 30)
        )
        s2 = ClassSession.objects.create(
            class_group=self.class_group, session_number=2,
            session_date=date(2026, 10, 5), start_time=time(18, 0), end_time=time(19, 30)
        )
        AttendanceRecord.objects.create(session=s1, student=self.student1, status='present')
        AttendanceRecord.objects.create(session=s2, student=self.student1, status='absent')

        analytics = compute_student_academic_analytics(self.student1)
        self.assertEqual(analytics['overall_gpa_100'], 85.0)
        self.assertEqual(analytics['semester_delta'], 10.0)
        self.assertEqual(analytics['attendance']['attendance_rate'], 50.0)

        speaking_stat = next(s for s in analytics['skills_breakdown'] if s['key'] == 'speaking')
        writing_stat = next(s for s in analytics['skills_breakdown'] if s['key'] == 'writing')
        listening_stat = next(s for s in analytics['skills_breakdown'] if s['key'] == 'listening')

        self.assertEqual(speaking_stat['average'], 90.0)
        self.assertEqual(writing_stat['average'], 62.0)
        self.assertIsNone(listening_stat['average'])

    def test_5_missing_assessment_data_never_invents_weaknesses_or_grades(self):
        analytics = compute_student_academic_analytics(self.student2)
        self.assertIsNone(analytics['overall_gpa_100'])
        self.assertEqual(analytics['strongest_skills'], [])
        self.assertEqual(analytics['weakest_skills'], [])
        self.assertFalse(analytics['has_sufficient_data'])

        ai_rec = generate_grounded_ai_recommendations(analytics)
        self.assertFalse(ai_rec['data_sufficient'])

    def test_6_admin_permissions_and_analytics_hub(self):
        self._login_2fa(self.student1)
        res_st = self.client.get(reverse('academics:admin_hub'))
        self.assertNotEqual(res_st.status_code, 200)

        self._login_2fa(self.admin)
        res_adm = self.client.get(reverse('academics:admin_hub'))
        self.assertEqual(res_adm.status_code, 200)
