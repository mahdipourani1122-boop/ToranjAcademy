from django.test import TestCase
from django.urls import reverse
from accounts.models import User


class Phase3DashboardSystemTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email='student@toranj.ir', first_name='زبان‌آموز', last_name='تست',
            phone='09121111111', password='StrongPassword123!', role=User.Role.STUDENT
        )
        self.teacher = User.objects.create_user(
            email='teacher@toranj.ir', first_name='استاد', last_name='تست',
            phone='09122222222', password='StrongPassword123!', role=User.Role.TEACHER
        )
        self.supervisor = User.objects.create_user(
            email='supervisor@toranj.ir', first_name='سوپروایزر', last_name='تست',
            phone='09123333333', password='StrongPassword123!', role=User.Role.SUPERVISOR
        )
        self.admin = User.objects.create_superuser(
            email='admin@toranj.ir', first_name='مدیر', last_name='ارشد',
            phone='09124444444', password='StrongPassword123!'
        )

    def test_each_role_renders_its_own_dashboard_correctly(self):
        """بررسی باز شدن صحیح داشبورد هر ۴ نقش کاربری"""
        role_routes = [
            (self.student, 'dashboards:student', 'خلاصه پروفایل زبان‌آموز'),
            (self.teacher, 'dashboards:teacher', 'پنل ثبت حضور و غیاب جلسه'),
            (self.supervisor, 'dashboards:supervisor', 'صف تأییدیه‌های آموزشی و نظارتی'),
            (self.admin, 'dashboards:admin', 'مدیریت کاربران و تخصیص نقش‌ها'),
        ]
        for user, url_name, expected_text in role_routes:
            self.client.force_login(user)
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, expected_text)

    def test_only_admin_can_update_user_roles(self):
        """تست امنیتی: زبان‌آموز نمی‌تواند نقش کاربری را تغییر دهد، اما مدیر کل می‌تواند"""
        update_url = reverse('dashboards:update_user_role', args=[self.student.id])

        # تلاش غیرمجاز توسط زبان‌آموز
        self.client.force_login(self.student)
        res = self.client.post(update_url, {'role': User.Role.ADMIN, 'status': User.Status.ACTIVE})
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.STUDENT)

        # تغییر مجاز توسط مدیر کل (ارتقای زبان‌آموز به استاد)
        self.client.force_login(self.admin)
        res = self.client.post(update_url, {'role': User.Role.TEACHER, 'status': User.Status.ACTIVE})
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, User.Role.TEACHER)