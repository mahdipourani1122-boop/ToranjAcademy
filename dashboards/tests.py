from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.apps import apps

User = get_user_model()


class ToranjDashboardsSecurityAndFunctionalTests(TestCase):
    def _create_user(self, phone, first_name, last_name, role='student', is_teacher=False):
        user = User.objects.create_user(
            phone=phone,
            password='StrongPassword123!',
            first_name=first_name,
            last_name=last_name,
        )
        user.is_active = True
        if hasattr(user, 'role'):
            user.role = role
        if hasattr(user, 'is_teacher'):
            user.is_teacher = is_teacher
        if hasattr(user, 'is_verified'):
            user.is_verified = True
        if hasattr(user, 'is_phone_verified'):
            user.is_phone_verified = True
        user.save()
        return user

    def setUp(self):
        self.client = Client()
        self.student1 = self._create_user('09121112233', 'اریشاه', 'پورانی', role='student', is_teacher=False)
        self.student2 = self._create_user('09129998877', 'سهراب', 'راد', role='student', is_teacher=False)
        self.teacher1 = self._create_user('09123334455', 'رستم', 'دستان', role='teacher', is_teacher=True)
        self.teacher2 = self._create_user('09127776655', 'زال', 'زر', role='teacher', is_teacher=True)

    # --- تست‌های داشبورد زبان‌آموز (حفظ کامل عملکرد قبلی) ---
    def test_unauthenticated_student_access_redirected(self):
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_authenticated_student_dashboard_loads(self):
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اریشاه')

    def test_student_idor_protection_on_unauthorized_course(self):
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_course_detail', args=[99999]))
        self.assertEqual(response.status_code, 403)

    # --- تست‌های داشبورد پریمیوم استاد ---
    def test_unauthenticated_teacher_access_redirected(self):
        response = self.client.get(reverse('dashboards:teacher_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_student_blocked_from_teacher_dashboard(self):
        """زبان‌آموز نباید بتواند وارد داشبورد استاد شود (403 Forbidden)"""
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:teacher_dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_authenticated_teacher_dashboard_loads(self):
        """بارگذاری صحیح داشبورد برای استاد مجاز و نمایش نام استاد"""
        self.client.force_login(self.teacher1)
        response = self.client.get(reverse('dashboards:teacher_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'رستم')

    def test_teacher_idor_protection_on_unassigned_class(self):
        """استاد نباید بتواند به کلاس‌هایی که به او اختصاص نیافته دسترسی پیدا کند (403)"""
        self.client.force_login(self.teacher1)
        response = self.client.get(reverse('dashboards:teacher_class_detail', args=[88888]))
        self.assertEqual(response.status_code, 403)

    def test_teacher_blocked_from_grading_unauthorized_student(self):
        """جلوگیری از ثبت نمره برای دوره یا زبان‌آموز خارج از کلاس‌های استاد"""
        self.client.force_login(self.teacher1)
        response = self.client.post(reverse('dashboards:teacher_dashboard'), {
            'form_action': 'record_grade',
            'course_id': '99999',
            'student_id': str(self.student2.pk),
            'title': 'آزمون غیرمجاز',
            'score': '95',
        })
        self.assertEqual(response.status_code, 403)

    def test_teacher_profile_edit_mass_assignment_protection(self):
        """استاد می‌تواند نام خود را ویرایش کند اما نمی‌تواند دسترسی سوپریوزر بگیرد"""
        self.client.force_login(self.teacher1)
        response = self.client.post(reverse('dashboards:teacher_dashboard'), {
            'form_action': 'update_profile',
            'first_name': 'رستم ویرایش‌شده',
            'last_name': 'دستان',
            'is_superuser': 'True',
            'is_staff': 'True',
        })
        self.assertEqual(response.status_code, 302)
        self.teacher1.refresh_from_db()
        self.assertEqual(self.teacher1.first_name, 'رستم ویرایش‌شده')
        self.assertFalse(self.teacher1.is_superuser)

    def test_teacher_csv_report_export_works(self):
        """بررسی دریافت خروجی اکسل/CSV گزارش آموزشی توسط استاد"""
        self.client.force_login(self.teacher1)
        response = self.client.get(reverse('dashboards:teacher_report_export'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])