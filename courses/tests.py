from datetime import date, time
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from accounts.models import User
from .models import CourseCategory, Course, ClassGroup, Enrollment
from .services import (
    assign_teacher_to_class,
    submit_student_enrollment_request,
    review_enrollment_request,
)


class Phase4CourseClassEnrollmentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email='admin@toranj.ir', first_name='مدیر', last_name='کل',
            phone='09120000001', password='StrongPassword123!'
        )
        self.teacher1 = User.objects.create_user(
            email='t1@toranj.ir', first_name='استاد', last_name='اول',
            phone='09120000002', password='StrongPassword123!', role=User.Role.TEACHER
        )
        self.teacher2 = User.objects.create_user(
            email='t2@toranj.ir', first_name='استاد', last_name='دوم',
            phone='09120000003', password='StrongPassword123!', role=User.Role.TEACHER
        )
        self.student1 = User.objects.create_user(
            email='s1@toranj.ir', first_name='زبان‌آموز', last_name='یک',
            phone='09120000004', password='StrongPassword123!', role=User.Role.STUDENT
        )
        self.student2 = User.objects.create_user(
            email='s2@toranj.ir', first_name='زبان‌آموز', last_name='دو',
            phone='09120000005', password='StrongPassword123!', role=User.Role.STUDENT
        )

        self.category = CourseCategory.objects.create(name='بزرگسالان', slug='adults')
        self.course = Course.objects.create(
            title='دوره جامع Intermediate B1',
            slug='intermediate-b1',
            description='توضیحات دوره',
            category=self.category,
            age_group=Course.AgeGroup.ADULTS,
            language_level=Course.LanguageLevel.INTERMEDIATE,
            learning_objectives='مکالمه روان',
            tuition_fee=3500000,
            duration_weeks=8,
            sessions_count=16,
            max_capacity=2,
            min_capacity=1,
            enrollment_status=Course.EnrollmentStatus.OPEN,
            publication_status=Course.PublicationStatus.PUBLISHED,
        )

        self.class_a = ClassGroup.objects.create(
            course=self.course,
            name='گروه الف',
            code='TRJ-B1-A',
            teacher=self.teacher1,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 12, 30),
            days_of_week='sat,mon',
            start_time=time(18, 0),
            end_time=time(19, 30),
            max_capacity=1,
            location_or_link='کلاس ۱۰۱',
            status=ClassGroup.ClassStatus.ACTIVE,
        )

    def test_1_teacher_schedule_conflict_is_blocked_on_server(self):
        """تست ۱: جلوگیری از تخصیص یک استاد به دو کلاس هم‌زمان"""
        conflicting_class = ClassGroup(
            course=self.course,
            name='گروه تداخلی استاد',
            code='TRJ-B1-CONFLICT',
            teacher=self.teacher1,
            start_date=date(2026, 11, 15),
            end_date=date(2026, 12, 15),
            days_of_week='mon,wed',  # دوشنبه مشترک است
            start_time=time(18, 30),  # هم‌پوشانی ساعتی با 18:00 تا 19:30
            end_time=time(20, 0),
            max_capacity=10,
            location_or_link='کلاس ۱۰۲',
            status=ClassGroup.ClassStatus.PLANNED,
        )
        with self.assertRaises(ValidationError):
            conflicting_class.full_clean()

    def test_2_unpublished_course_rejects_student_enrollment(self):
        """تست ۲: جلوگیری از ثبت‌نام در دوره‌های منتشرنشده (پیش‌نویس)"""
        self.course.publication_status = Course.PublicationStatus.DRAFT
        self.course.save()
        with self.assertRaises(ValidationError):
            submit_student_enrollment_request(self.student1, self.class_a.id)

    def test_3_duplicate_active_enrollment_is_prevented(self):
        """تست ۳: جلوگیری از ارسال درخواست تکراری برای یک کلاس واحد"""
        submit_student_enrollment_request(self.student1, self.class_a.id)
        with self.assertRaises(ValidationError):
            submit_student_enrollment_request(self.student1, self.class_a.id)

    def test_4_approval_records_reviewer_and_does_not_auto_mark_paid(self):
        """تست ۴: تایید ثبت‌نام اطلاعات تاییدکننده را ثبت می‌کند اما وضعیت مالی را خودکار تسویه نمی‌کند"""
        enrollment = submit_student_enrollment_request(self.student1, self.class_a.id)
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING)

        approved = review_enrollment_request(enrollment.id, reviewer=self.admin, action='approve')
        self.assertEqual(approved.status, Enrollment.Status.APPROVED)
        self.assertEqual(approved.reviewed_by, self.admin)
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(approved.payment_status, Enrollment.PaymentStatus.UNPAID)

    def test_5_class_capacity_is_strictly_enforced(self):
        """تست ۵: جلوگیری از رد شدن سقف ظرفیت کلاس (ظرفیت کلاس الف = ۱ نفر)"""
        e1 = submit_student_enrollment_request(self.student1, self.class_a.id)
        e2 = submit_student_enrollment_request(self.student2, self.class_a.id)

        review_enrollment_request(e1.id, reviewer=self.admin, action='approve')
        # تلاش برای تایید نفر دوم در کلاسی که ظرفیتش ۱ است باید خطا بدهد
        with self.assertRaises(ValidationError):
            review_enrollment_request(e2.id, reviewer=self.admin, action='approve')

    def test_6_student_schedule_conflict_is_blocked(self):
        """تست ۶: جلوگیری از ثبت‌نام زبان‌آموز در دو کلاس دارای تداخل زمانی"""
        submit_student_enrollment_request(self.student1, self.class_a.id)

        overlapping_class = ClassGroup.objects.create(
            course=self.course,
            name='گروه موازی',
            code='TRJ-B1-B',
            teacher=self.teacher2,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 12, 30),
            days_of_week='sat,wed',  # شنبه مشترک است
            start_time=time(18, 30),
            end_time=time(20, 0),
            max_capacity=10,
            location_or_link='کلاس ۱۰۳',
            status=ClassGroup.ClassStatus.ACTIVE,
        )
        with self.assertRaises(ValidationError):
            submit_student_enrollment_request(self.student1, overlapping_class.id)

    def test_7_teacher_cannot_view_unassigned_class_roster(self):
        """تست ۷: استاد ۲ اجازه مشاهده لیست زبان‌آموزان کلاسِ استاد ۱ را ندارد"""
        self.client.force_login(self.teacher2)
        res = self.client.get(reverse('courses:class_roster', args=[self.class_a.id]))
        self.assertRedirects(res, reverse('dashboards:teacher'))

    def test_8_student_cannot_access_admin_course_creation(self):
        """تست ۸: زبان‌آموز نمی‌تواند وارد مسیر ساخت دوره یا تایید ثبت‌نام شود"""
        self.client.force_login(self.student1)
        res = self.client.get(reverse('courses:course_create'))
        self.assertRedirects(res, reverse('dashboards:student'))