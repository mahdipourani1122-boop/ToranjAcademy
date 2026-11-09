from django.urls import path
from . import views

app_name = 'dashboards'

urlpatterns = [
    path('', views.dashboard_router_view, name='dashboard_home'),
    path('student/', views.student_dashboard_view, name='student_dashboard'),
    path('student/courses/<int:course_id>/', views.student_course_detail_view, name='student_course_detail'),
    path('student/resources/<int:resource_id>/download/', views.protected_resource_download_view, name='resource_download'),
]from django.urls import path
from . import views
from . import teacher_views

app_name = 'dashboards'

urlpatterns = [
    path('', views.dashboard_router_view, name='dashboard_home'),

    # مسیرهای داشبورد زبان‌آموز (کاملاً حفظ‌شده)
    path('student/', views.student_dashboard_view, name='student_dashboard'),
    path('student/courses/<int:course_id>/', views.student_course_detail_view, name='student_course_detail'),
    path('student/resources/<int:resource_id>/download/', views.protected_resource_download_view, name='resource_download'),

    # مسیرهای داشبورد پریمیوم اساتید
    path('teacher/', teacher_views.teacher_dashboard_view, name='teacher_dashboard'),
    path('teacher/classes/<int:course_id>/', teacher_views.teacher_class_detail_view, name='teacher_class_detail'),
    path('teacher/submissions/<int:submission_id>/download/', teacher_views.protected_submission_download_view, name='submission_download'),
    path('teacher/reports/export/', teacher_views.teacher_report_export_view, name='teacher_report_export'),
]