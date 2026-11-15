from datetime import timedelta
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from dashboards import views as student_views
from dashboards import teacher_views
from dashboards import admin_views
from dashboards import supervisor_views
from dashboards import attendance_views
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
        for flag in ('is_verified', 'is_phone_verified', 'is_approved'):
            if hasattr(user, flag):
                setattr(user, flag, True)
        user.save()
        return user

    def _call_view(self, view_func, user=None, method='GET', path='/dashboard/', data=None, **kwargs):
        """فراخوانی مستقیم ویو با سشن و پیام‌های جنگو برای تست دقیق منطق و امنیت ویوها"""
        if method.upper() == 'POST':
            request = self.factory.post(path, data=data or {})
        else:
            request = self.factory.get(path, data=data or {})
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        setattr(request, '_messages', FallbackStorage(request))
        request.user = user if user is not None else AnonymousUser()
        return view_func(request, **kwargs)

    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
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
        for path in ['/', '/news/', '/guest-explore/', '/departments/english/', '/departments/german/', '/departments/french/', '/departments/turkish/']:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Route failed: {path}")

    def test_02_guest_blocked_from_all_private_dashboards(self):
        for view_fn in [
            student_views.dashboard_router_view,
            student_views.student_dashboard_view,
            teacher_views.teacher_dashboard_view,
            supervisor_views.supervisor_dashboard_view,
            admin_views.admin_dashboard_view,
        ]:
            res = self._call_view(view_fn, user=None)
            self.assertEqual(res.status_code, 302)

    def test_03_dashboard_router_redirects_each_role_correctly(self):
        res_stu = self._call_view(student_views.dashboard_router_view, user=self.student1)
        self.assertEqual(res_stu.status_code, 302)
        self.assertIn(reverse('dashboards:student_dashboard'), res_stu['Location'])

        res_tch = self._call_view(student_views.dashboard_router_view, user=self.teacher1)
        self.assertEqual(res_tch.status_code, 302)
        self.assertIn(reverse('dashboards:teacher_dashboard'), res_tch['Location'])

        res_sup = self._call_view(student_views.dashboard_router_view, user=self.supervisor1)
        self.assertEqual(res_sup.status_code, 302)
        self.assertIn(reverse('dashboards:supervisor_dashboard'), res_sup['Location'])

        res_adm = self._call_view(student_views.dashboard_router_view, user=self.admin_user)
        self.assertEqual(res_adm.status_code, 302)
        self.assertIn(reverse('dashboards:admin_dashboard'), res_adm['Location'])

    def test_04_student_dashboard_and_rbac_isolation(self):
        res = self._call_view(student_views.student_dashboard_view, user=self.student1)
        self.assertEqual(res.status_code, 200)
        self.assertIn('اریشاه', res.content.decode('utf-8'))

        self.assertEqual(self._call_view(teacher_views.teacher_dashboard_view, user=self.student1).status_code, 403)
        self.assertEqual(self._call_view(supervisor_views.supervisor_dashboard_view, user=self.student1).status_code, 403)
        self.assertEqual(self._call_view(admin_views.admin_dashboard_view, user=self.student1).status_code, 403)

    def test_05_teacher_dashboard_and_rbac_isolation(self):
        res = self._call_view(teacher_views.teacher_dashboard_view, user=self.teacher1)
        self.assertEqual(res.status_code, 200)
        self.assertIn('رستم', res.content.decode('utf-8'))

        self.assertEqual(self._call_view(student_views.student_dashboard_view, user=self.teacher1).status_code, 403)
        self.assertEqual(self._call_view(supervisor_views.supervisor_dashboard_view, user=self.teacher1).status_code, 403)
        self.assertEqual(self._call_view(admin_views.admin_dashboard_view, user=self.teacher1).status_code, 403)

    def test_06_supervisor_dashboard_and_rbac_isolation(self):
        res = self._call_view(supervisor_views.supervisor_dashboard_view, user=self.supervisor1)
        self.assertEqual(res.status_code, 200)
        self.assertIn('گودرز', res.content.decode('utf-8'))

        self.assertEqual(self._call_view(student_views.student_dashboard_view, user=self.supervisor1).status_code, 403)
        self.assertEqual(self._call_view(teacher_views.teacher_dashboard_view, user=self.supervisor1).status_code, 403)
        self.assertEqual(self._call_view(admin_views.admin_dashboard_view, user=self.supervisor1).status_code, 403)

    def test_07_admin_dashboard_search_filter_and_attendance_search(self):
        res = self._call_view(
            admin_views.admin_dashboard_view,
            user=self.admin_user,
            data={'tab': 'users', 'q': 'اریشاه', 'role': 'student'},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn('اریشاه', res.content.decode('utf-8'))

        post_res = self._call_view(
            admin_views.admin_dashboard_view,
            user=self.admin_user,
            method='POST',
            data={
                'form_action': 'publish_announcement',
                'title': 'آغاز ثبت‌نام ترم جدید',
                'message': 'کلاس‌های ترم جدید از شنبه آغاز می‌شود.',
                'audience': 'STUDENT',
            },
        )
        self.assertEqual(post_res.status_code, 302)
        self.assertTrue(AttendanceNotification.objects.filter(title='آغاز ثبت‌نام ترم جدید').exists())

        att_res = self._call_view(
            attendance_views.admin_attendance_hub_view,
            user=self.admin_user,
            data={'q': 'اریشاه', 'department': 'انگلیسی'},
        )
        self.assertEqual(att_res.status_code, 200)

    def test_08_idor_protection_student_and_teacher(self):
        res_stu = self._call_view(student_views.student_course_detail_view, user=self.student1, course_id=99999)
        self.assertEqual(res_stu.status_code, 403)

        res_tch = self._call_view(teacher_views.teacher_class_detail_view, user=self.teacher1, course_id=88888)
        self.assertEqual(res_tch.status_code, 403)

    def test_09_mass_assignment_protection_on_profile_update(self):
        res = self._call_view(
            student_views.student_dashboard_view,
            user=self.student1,
            method='POST',
            data={
                'form_action': 'update_profile',
                'first_name': 'اریشاه ویرایش',
                'last_name': 'پورانی',
                'is_superuser': 'True',
                'is_staff': 'True',
                'role': 'admin',
            },
        )
        self.assertEqual(res.status_code, 302)
        self.student1.refresh_from_db()
        self.assertEqual(self.student1.first_name, 'اریشاه ویرایش')
        self.assertFalse(self.student1.is_superuser)
        self.assertFalse(self.student1.is_staff)

    def test_10_payment_claim_stays_pending_until_admin_review(self):
        res = self._call_view(
            student_views.student_dashboard_view,
            user=self.student1,
            method='POST',
            data={
                'form_action': 'submit_payment_claim',
                'reference_code': 'TRX-99887766',
                'course_note': 'شهریه انگلیسی',
            },
        )
        self.assertEqual(res.status_code, 302)
        page_res = self._call_view(student_views.student_dashboard_view, user=self.student1, data={'tab': 'subscription'})
        self.assertEqual(page_res.status_code, 200)
        self.assertIn('در انتظار', page_res.content.decode('utf-8'))

    def test_11_two_stage_attendance_request_and_duplicate_prevention(self):
        entry = submit_student_attendance_request(self.student1, self.session_physical.pk)
        self.assertEqual(entry.status, 'PENDING')
        with self.assertRaises(ValidationError):
            submit_student_attendance_request(self.student1, self.session_physical.pk)

    def test_12_online_attendance_code_validation_and_expiration(self):
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
        submit_student_attendance_request(self.student1, self.session_physical.pk)
        with self.assertRaises(PermissionDenied):
            teacher_review_attendance(self.teacher2, self.session_physical.pk, self.student1.pk, 'PRESENT')

        approved_entry = teacher_review_attendance(
            self.teacher1, self.session_physical.pk, self.student1.pk, 'PRESENT', private_note='عالی'
        )
        self.assertEqual(approved_entry.status, 'PRESENT')

    def test_14_auto_finalization_and_immutable_audit_trail(self):
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
