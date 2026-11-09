from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


class ToranjStudentDashboardSecurityTests(TestCase):
    def _create_active_student(self, phone, first_name, last_name):
        user = User.objects.create_user(
            phone=phone,
            password='StrongPassword123!',
            first_name=first_name,
            last_name=last_name,
        )
        user.is_active = True
        if hasattr(user, 'role'):
            user.role = 'student'
        if hasattr(user, 'is_verified'):
            user.is_verified = True
        if hasattr(user, 'is_phone_verified'):
            user.is_phone_verified = True
        user.save()
        return user

    def setUp(self):
        self.client = Client()
        self.student1 = self._create_active_student('09121112233', 'اریشاه', 'پورانی')
        self.student2 = self._create_active_student('09129998877', 'کاربر', 'دوم')

    def test_unauthenticated_access_redirected(self):
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_authenticated_student_dashboard_loads(self):
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اریشاه')

    def test_idor_protection_on_unauthorized_course_detail(self):
        self.client.force_login(self.student1)
        response = self.client.get(reverse('dashboards:student_course_detail', args=[99999]))
        self.assertEqual(response.status_code, 403)

    def test_profile_edit_mass_assignment_protection(self):
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
        self.client.force_login(self.student1)
        response = self.client.post(reverse('dashboards:student_dashboard'), {
            'form_action': 'submit_payment_claim',
            'reference_code': 'TRX-99887766',
            'course_note': 'شهریه انگلیسی',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'در انتظار بررسی')