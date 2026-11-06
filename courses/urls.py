from django.urls import path
from .views import (
    PublicCourseCatalogView,
    AdminCourseCreateView,
    AdminCourseUpdateView,
    AdminCourseStatusActionView,
    AdminClassCreateView,
    AdminClassUpdateView,
    AdminAssignTeacherView,
    ClassRosterView,
    StudentSubmitEnrollmentView,
    StudentCancelEnrollmentView,
    AdminEnrollmentReviewView,
    AdminManualEnrollView,
    AdminTransferEnrollmentView,
)

app_name = 'courses'

urlpatterns = [
    # کاتالوگ عمومی و جستجوی دوره‌ها
    path('', PublicCourseCatalogView.as_view(), name='catalog'),

    # مدیریت دوره‌ها (Admin)
    path('manage/create/', AdminCourseCreateView.as_view(), name='course_create'),
    path('manage/<uuid:course_id>/edit/', AdminCourseUpdateView.as_view(), name='course_edit'),
    path('manage/<uuid:course_id>/status/', AdminCourseStatusActionView.as_view(), name='course_status'),

    # مدیریت کلاس‌ها و تخصیص اساتید (Admin)
    path('classes/create/', AdminClassCreateView.as_view(), name='class_create'),
    path('classes/<uuid:class_id>/edit/', AdminClassUpdateView.as_view(), name='class_edit'),
    path('classes/<uuid:class_id>/assign-teacher/', AdminAssignTeacherView.as_view(), name='assign_teacher'),
    path('classes/<uuid:class_id>/roster/', ClassRosterView.as_view(), name='class_roster'),

    # گردش‌کار ثبت‌نام زبان‌آموز و بررسی مدیریت
    path('classes/<uuid:class_id>/enroll/', StudentSubmitEnrollmentView.as_view(), name='student_enroll'),
    path('enrollments/<uuid:enrollment_id>/cancel/', StudentCancelEnrollmentView.as_view(), name='student_cancel_enrollment'),
    path('enrollments/<uuid:enrollment_id>/review/', AdminEnrollmentReviewView.as_view(), name='enrollment_review'),
    path('enrollments/manual-enroll/', AdminManualEnrollView.as_view(), name='manual_enroll'),
    path('enrollments/<uuid:enrollment_id>/transfer/', AdminTransferEnrollmentView.as_view(), name='enrollment_transfer'),
]