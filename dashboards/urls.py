from django.urls import path
from . import views

app_name = 'dashboards'

urlpatterns = [
    path('', views.dashboard_router_view, name='dashboard_home'),
    path('student/', views.student_dashboard_view, name='student_dashboard'),
    path('student/courses/<int:course_id>/', views.student_course_detail_view, name='student_course_detail'),
    path('student/resources/<int:resource_id>/download/', views.protected_resource_download_view, name='resource_download'),
]