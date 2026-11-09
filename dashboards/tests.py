from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


class ToranjStudentDashboardSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.student1 = User.objects.create_user(
            phone='09121112233',
            password='StrongPassword123!',
            first_name='اریشاه',
            last_name='پورانی',
        )
        self.student2 = User.objects.create_user(
            phone='09129998877',
            password='StrongPassword123!',
            first_name='کاربر',
            last_name='دوم',
        )

    def test_unauthenticated_access_redirected(self):
        """بررسی ممانعت از ورود کاربران لاگین‌نکرده به داشبورد زبان‌آموز"""
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_authenticated_student_dashboard_loads(self):
        """بررسی بارگذاری صحیح داشبورد برای زبان‌آموز واقعی و نمایش نام واقعی"""
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اریشاه')

    def test_idor_protection_on_unauthorized_course_detail(self):
        """بررسی محافظت IDOR در صورت تلاش برای دسترسی به دوره غیرمجاز"""
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_course_detail', args=[99999]))
        self.assertEqual(response.status_code, 403)

    def test_profile_edit_mass_assignment_protection(self):
        """بررسی اینکه زبان‌آموز نتواند با ارسال پارامترهای اضافی نقش یا دسترسی ادمین بگیرد"""
        self.client.force_login(self.student1)
        response = self.client.post(reverse('dashboards:student_dashboard'), {
            'form_action': 'update_profile',
            'first_name': 'اریشاه ویرایش‌شده',
            'last_name': 'پورانی',
            'is_superuser': 'True',
            'is_staff': 'True',
            'role': 'admin',
        })
        self.assertEqual(response.status_code, 302)
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.first_name, 'اریشاه ویرایش‌شده')
        self.assertFalse(self.student1.is_superuser)
        self.assertFalse(self.student1.is_staff)

    def test_payment_claim_does_not_auto_grant_access(self):
        """بررسی اینکه ثبت فیش پرداخت به صورت خودکار دسترسی پولی ایجاد نمی‌کند"""
        self.client.force_login(self.student1)
        response = self.client.post(reverse('dashboards:student_dashboard'), {
            'form_action': 'submit_payment_claim',
            'reference_code': 'TRX-99887766',
            'course_note': 'شهریه انگلیسی',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'در انتظار بررسی')