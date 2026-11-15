from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from dashboards.models import (
    AttendancePolicy,
    AttendanceSession,
    AttendanceEntry,
    AttendanceAuditLog,
    AttendanceNotification,
)
from dashboards.attendance_service import (
    submit_student_attendance_request,
    teacher_review_attendance,
    admin_override_attendance,
    finalize_expired_sessions,
)

User = get_user_model()


class ToranjPhase2ComprehensiveQATests(TestCase):
    def _create_user(self, phone, first_name, last_name, role='student', is_teacher=False, is_supervisor=False, is_staff=False, is_superuser=False):
        user = User.objects.create_user(
            phone=phone,
            password='StrongPassword123!',
            first_name=first_name,
            last_name=last_name,
        )
        user.is_active = True
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        if hasattr(user, 'role'):
            user.role = role
        if hasattr(user, 'is_teacher'):
            user.is_teacher = is_teacher
        if hasattr(user, 'is_supervisor'):
            user.is_supervisor = is_supervisor
        if hasattr(user, 'is_verified'):
            user.is_verified = True
        if hasattr(user, 'is_phone_verified'):
            user.is_phone_verified = True
        user.save()
        return user

    def setUp(self):
        self.client = Client()
        self.student1 = self._create_user('09121112233', 'اریشاه', 'پورانی', role='student')
        self.student2 = self._create_user('09129998877', 'سهراب', 'راد', role='student')
        self.teacher1 = self._create_user('09123334455', 'رستم', 'دستان', role='teacher', is_teacher=True)
        self.teacher2 = self._create_user('09127776655', 'زال', 'زر', role='teacher', is_teacher=True)
        self.supervisor1 = self._create_user('09125556677', 'گودرز', 'کشواد', role='supervisor', is_supervisor=True)
        self.admin_user = self._create_user('09120000001', 'مدیر', 'آموزشگاه', role='admin', is_staff=True, is_superuser=True)

        self.policy = AttendancePolicy.get_effective_policy()
        self.policy.unresolved_pending_policy = 'ABSENT'
        self.policy.save()

        self.session_physical = AttendanceSession.objects.create(
            course_id=101,
            course_title='انگلیسی پیشرفته C1',
            department='انگلیسی',
            term='پاییز ۱۴۰۵',
            teacher=self.teacher1,
            title='جلسه اول — حضوری',
            mode='PHYSICAL',
            status='OPEN',
        )
        AttendanceEntry.objects.create(
            session=self.session_physical,
            student=self.student1,
            status='NOT_OPEN',
        )

    def test_01_public_and_navigation_routes_load(self):
        """تست بارگذاری صفحه اصلی، اخبار، پورتال مهمان و هر ۴ دپارتمان زبان"""
        for path in ['/', '/news/', '/guest-explore/', '/departments/english/', '/departments/german/', '/departments/french/', '/departments/turkish/']:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Route failed: {path}")

    def test_02_guest_blocked_from_all_private_dashboards(self):
        """تست عدم دسترسی کاربر مهمان به تمامی داشبوردها و هدایت به صفحه ورود"""
        protected_names = [
            'dashboards:dashboard_home',
            'dashboards:student_dashboard',
            'dashboards:teacher_dashboard',
            'dashboards:supervisor_dashboard',
            'dashboards:admin_dashboard',
            'dashboards:student_attendance_hub',
            'dashboards:teacher_attendance_hub',
            'dashboards:admin_attendance_hub',
        ]
        for name in protected_names:
            res = self.client.get(reverse(name))
            self.assertEqual(res.status_code, 302, f"Unauthenticated access not redirected for {name}")

    def test_03_dashboard_router_redirects_each_role_correctly(self):
        """تست مسیریاب هوشمند (/dashboard/) برای هر ۴ نقش کاربری"""
        self.client.force_login(self.student1)
        self.assertRedirects(self.client.get(reverse('dashboards:dashboard_home')), reverse('dashboards:student_dashboard'))

        self.client.force_login(self.teacher1)
        self.assertRedirects(self.client.get(reverse('dashboards:dashboard_home')), reverse('dashboards:teacher_dashboard'))

        self.client.force_login(self.supervisor1)
        self.assertRedirects(self.client.get(reverse('dashboards:dashboard_home')), reverse('dashboards:supervisor_dashboard'))

        self.client.force_login(self.admin_user)
        self.assertRedirects(self.client.get(reverse('dashboards:dashboard_home')), reverse('dashboards:admin_dashboard'))

    def test_04_student_dashboard_and_rbac_isolation(self):
        """تست بارگذاری کامل داشبورد زبان‌آموز (200 OK) و مسدودسازی ورود زبان‌آموز به پنل‌های دیگر (403)"""
        self.client.force_login(self.student1)
        res = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'اریشاه')

        self.assertEqual(self.client.get(reverse('dashboards:teacher_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:supervisor_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:admin_dashboard')).status_code, 403)

    def test_05_teacher_dashboard_and_rbac_isolation(self):
        """تست بارگذاری کامل داشبورد استاد (200 OK) و مسدودسازی ورود استاد به پنل زبان‌آموز یا مدیر (403)"""
        self.client.force_login(self.teacher1)
        res = self.client.get(reverse('dashboards:teacher_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'رستم')

        self.assertEqual(self.client.get(reverse('dashboards:student_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:supervisor_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:admin_dashboard')).status_code, 403)

    def test_06_supervisor_dashboard_and_rbac_isolation(self):
        """تست بارگذاری داشبورد ناظر آموزشی و مسدودسازی ورود به پنل زبان‌آموز، استاد و ادمین"""
        self.client.force_login(self.supervisor1)
        res = self.client.get(reverse('dashboards:supervisor_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'گودرز')

        self.assertEqual(self.client.get(reverse('dashboards:student_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:teacher_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dashboards:admin_dashboard')).status_code, 403)

    def test_07_admin_dashboard_search_filter_and_attendance_search(self):
        """تست داشبورد مدیریت کل، جست‌وجوی کاربران، انتشار اطلاعیه و جست‌وجوی ممیزی بدون خطای NameError"""
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse('dashboards:admin_dashboard') + '?tab=users&q=اریشاه&role=student')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'اریشاه')

        post_res = self.client.post(reverse('dashboards:admin_dashboard'), {
            'form_action': 'publish_announcement',
            'title': 'آغاز ثبت‌نام ترم جدید',
            'message': 'کلاس‌های ترم جدید از شنبه آغاز می‌شود.',
            'audience': 'STUDENT',
        }, follow=True)
        self.assertEqual(post_res.status_code, 200)
        self.assertTrue(AttendanceNotification.objects.filter(title='آغاز ثبت‌نام ترم جدید').exists())

        att_search_res = self.client.get(reverse('dashboards:admin_attendance_hub') + '?q=اریشاه&department=انگلیسی')
        self.assertEqual(att_search_res.status_code, 200)

    def test_08_idor_protection_student_and_teacher(self):
        """تست محافظت در برابر IDOR برای دوره‌ها و کلاس‌های غیرمجاز"""
        self.client.force_login(self.student1)
        self.assertEqual(self.client.get(reverse('dashboards:student_course_detail', args=[99999])).status_code, 403)

        self.client.force_login(self.teacher1)
        self.assertEqual(self.client.get(reverse('dashboards:teacher_class_detail', args=[88888])).status_code, 403)

    def test_09_mass_assignment_protection_on_profile_update(self):
        """تست جلوگیری از ارتقای غیرمجاز سطح دسترسی در ویرایش پروفایل"""
        self.client.force_login(self.student1)
        res = self.client.post(reverse('dashboards:student_dashboard'), {
            'form_action': 'update_profile',
            'first_name': 'اریشاه ویرایش',
            'last_name': 'پورانی',
            'is_superuser': 'True',
            'is_staff': 'True',
            'role': 'admin',
        })
        self.assertEqual(res.status_code, 302)
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.first_name, 'اریشاه ویرایش')
        self.assertFalse(self.student1.is_superuser)
        self.assertFalse(self.student1.is_staff)

    def test_10_payment_claim_stays_pending_until_admin_review(self):
        """تست عدم فعال‌سازی خودکار پرداخت زبان‌آموز پیش از تایید مدیریت"""
        self.client.force_login(self.student1)
        res = self.client.post(reverse('dashboards:student_dashboard'), {
            'form_action': 'submit_payment_claim',
            'reference_code': 'TRX-99887766',
            'course_note': 'شهریه انگلیسی',
        }, follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'در انتظار بررسی')

    def test_11_two_stage_attendance_request_and_duplicate_prevention(self):
        """تست مرحله ۱ حضور و غیاب و جلوگیری از ارسال درخواست تکراری"""
        entry = submit_student_attendance_request(self.student1, self.session_physical.pk)
        self.assertEqual(entry.status, 'PENDING')
        with self.assertRaises(ValidationError):
            submit_student_attendance_request(self.student1, self.session_physical.pk)

    def test_12_online_attendance_code_validation_and_expiration(self):
        """تست کد امنیتی جلسه آنلاین و انقضای خودکار آن"""
        online_session = AttendanceSession.objects.create(
            course_id=101,
            course_title='آلمانی گوته B2',
            teacher=self.teacher1,
            title='جلسه آنلاین',
            mode='ONLINE',
            status='OPEN',
        )
        AttendanceEntry.objects.create(session=online_session, student=self.student1, status='NOT_OPEN')
        code = online_session.generate_secure_code(expiry_minutes=15)

        with self.assertRaises(ValidationError):
            submit_student_attendance_request(self.student1, online_session.pk, submitted_code='WRONG1')

        entry = submit_student_attendance_request(self.student1, online_session.pk, submitted_code=code)
        self.assertEqual(entry.status, 'PENDING')

        online_session.code_expires_at = timezone.now() - timedelta(minutes=1)
        online_session.save()
        entry.status = 'NOT_OPEN'
        entry.save()
        with self.assertRaises(ValidationError):
            submit_student_attendance_request(self.student1, online_session.pk, submitted_code=code)

    def test_13_stage2_teacher_approval_and_unauthorized_teacher_blocked(self):
        """تست مرحله ۲ تایید استاد و جلوگیری از تایید توسط استاد غیرمرتبط"""
        submit_student_attendance_request(self.student1, self.session_physical.pk)
        with self.assertRaises(PermissionDenied):
            teacher_review_attendance(self.teacher2, self.session_physical.pk, self.student1.pk, 'PRESENT')

        approved_entry = teacher_review_attendance(
            self.teacher1, self.session_physical.pk, self.student1.pk, 'PRESENT', private_note='عالی'
        )
        self.assertEqual(approved_entry.status, 'PRESENT')

    def test_14_auto_finalization_and_immutable_audit_trail(self):
        """تست نهایی‌سازی خودکار پس از انقضای مهلت استاد و غیرقابل تغییر بودن لاگ ممیزی"""
        submit_student_attendance_request(self.student1, self.session_physical.pk)
        self.session_physical.teacher_approval_deadline = timezone.now() - timedelta(minutes=5)
        self.session_physical.save()

        finalized_cnt = finalize_expired_sessions()
        self.assertEqual(finalized_cnt, 1)
        entry = AttendanceEntry.objects.get(session=self.session_physical, student=self.student1)
        self.assertEqual(entry.status, 'ABSENT')

        overridden = admin_override_attendance(
            self.admin_user, self.session_physical.pk, self.student1.pk, 'EXCUSED', 'گواهی پزشکی معتبر'
        )
        self.assertEqual(overridden.status, 'EXCUSED')

        audit_log = AttendanceAuditLog.objects.filter(session=self.session_physical, action='ADMIN_ATTENDANCE_OVERRIDE').first()
        self.assertIsNotNone(audit_log)
        with self.assertRaises(ValidationError):
            audit_log.reason = 'دستکاری'
            audit_log.save()
        with self.assertRaises(ValidationError):
            audit_log.delete()
