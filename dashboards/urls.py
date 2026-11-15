from django.urls import path
from . import views
from . import teacher_views
from . import attendance_views
from . import admin_views
from . import supervisor_views

app_name = 'dashboards'

urlpatterns = [
    path('', views.dashboard_router_view, name='dashboard_home'),

    # 1. Student Dashboard Routes
    path('student/', views.student_dashboard_view, name='student_dashboard'),
    path('student/courses/<int:course_id>/', views.student_course_detail_view, name='student_course_detail'),
    path('student/resources/<int:resource_id>/download/', views.protected_resource_download_view, name='resource_download'),

    # 2. Teacher Dashboard Routes
    path('teacher/', teacher_views.teacher_dashboard_view, name='teacher_dashboard'),
    path('teacher/classes/<int:course_id>/', teacher_views.teacher_class_detail_view, name='teacher_class_detail'),
    path('teacher/submissions/<int:submission_id>/download/', teacher_views.protected_submission_download_view, name='submission_download'),
    path('teacher/reports/export/', teacher_views.teacher_report_export_view, name='teacher_report_export'),

    # 3. Admin & Supervisor Dashboard Routes
    path('admin/', admin_views.admin_dashboard_view, name='admin_dashboard'),
    path('supervisor/', supervisor_views.supervisor_dashboard_view, name='supervisor_dashboard'),

    # 4. Two-Stage Attendance System Routes
    path('attendance/student/', attendance_views.student_attendance_hub_view, name='student_attendance_hub'),
    path('attendance/teacher/', attendance_views.teacher_attendance_hub_view, name='teacher_attendance_hub'),
    path('attendance/admin/', attendance_views.admin_attendance_hub_view, name='admin_attendance_hub'),
]
