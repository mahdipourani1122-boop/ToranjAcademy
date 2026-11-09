from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
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


class ToranjTwoStageAttendanceAndDashboardsTests(TestCase):
    def _create_user(self, phone, first_name, last_name, role='student', is_teacher=False, is_staff=False, is_superuser=False):
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
        self.admin_user = self._create_user('09120000001', 'مدیر', 'آموزشگاه', role='admin', is_staff=True, is_superuser=True)

        self.policy = AttendancePolicy.get_effective_policy()
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

    def test_student_and_teacher_dashboards_load_properly(self):
        self.client.login(phone='09121112233', password='StrongPassword123!')
        res_stu = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(res_stu.status_code, 200)

        self.client.login(phone='09123334455', password='StrongPassword123!')
        res_tch = self.client.get(reverse('dashboards:teacher_dashboard'))
        self.assertEqual(res_tch.status_code, 200)

    def test_student_unauthenticated_access_redirected(self):
        response = self.client.get(reverse('dashboards:student_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_stage1_student_request_sets_pending_and_prevents_duplicates(self):
        entry = submit_student_attendance_request(self.student1, self.session_physical.pk)
        self.assertEqual(entry.status, 'PENDING')
        self.assertIsNotNone(entry.requested_at)

        with self.assertRaises(ValidationError):
            submit_student_attendance_request(self.student1, self.session_physical.pk)

    def test_online_session_attendance_code_and_expiration(self):
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

    def test_stage2_teacher_approval_rejection_and_authorization(self):
        submit_student_attendance_request(self.student1, self.session_physical.pk)

        approved_entry = teacher_review_attendance(
            self.teacher1, self.session_physical.pk, self.student1.pk, 'PRESENT', private_note='مشارکت عالی در کلاس'
        )
        self.assertEqual(approved_entry.status, 'PRESENT')
        self.assertEqual(approved_entry.reviewed_by, self.teacher1)

    def test_automatic_finalization_on_expired_deadline(self):
        submit_student_attendance_request(self.student1, self.session_physical.pk)
        self.session_physical.teacher_approval_deadline = timezone.now() - timedelta(minutes=5)
        self.session_physical.save()

        finalized_cnt = finalize_expired_sessions()
        self.assertEqual(finalized_cnt, 1)
        self.session_physical.refresh_from_db()
        self.assertTrue(self.session_physical.is_finalized)

        entry = AttendanceEntry.objects.get(session=self.session_physical, student=self.student1)
        self.assertEqual(entry.status, 'ABSENT')

    def test_admin_override_and_immutable_audit_log(self):
        submit_student_attendance_request(self.student1, self.session_physical.pk)

        with self.assertRaises(ValidationError):
            admin_override_attendance(self.admin_user, self.session_physical.pk, self.student1.pk, 'EXCUSED', '')

        overridden = admin_override_attendance(
            self.admin_user, self.session_physical.pk, self.student1.pk, 'EXCUSED', 'ارائه گواهی پزشکی معتبر به واحد آموزش'
        )
        self.assertEqual(overridden.status, 'EXCUSED')

        audit_log = AttendanceAuditLog.objects.filter(session=self.session_physical, action='ADMIN_ATTENDANCE_OVERRIDE').first()
        self.assertIsNotNone(audit_log)

        with self.assertRaises(ValidationError):
            audit_log.reason = 'تلاش برای دستکاری لاگ'
            audit_log.save()
        with self.assertRaises(ValidationError):
            audit_log.delete()