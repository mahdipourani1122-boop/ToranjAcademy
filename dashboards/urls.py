from django.urls import path
from .views import (
    DashboardRedirectView,
    StudentDashboardView,
    TeacherDashboardView,
    SupervisorDashboardView,
    AdminDashboardView,
    AdminUpdateUserRoleView,
)

app_name = 'dashboards'

urlpatterns = [
    path('', DashboardRedirectView.as_view(), name='redirect'),
    path('student/', StudentDashboardView.as_view(), name='student'),
    path('student', StudentDashboardView.as_view()),
    path('teacher/', TeacherDashboardView.as_view(), name='teacher'),
    path('teacher', TeacherDashboardView.as_view()),
    path('supervisor/', SupervisorDashboardView.as_view(), name='supervisor'),
    path('supervisor', SupervisorDashboardView.as_view()),
    path('admin/', AdminDashboardView.as_view(), name='admin'),
    path('admin', AdminDashboardView.as_view()),
    # عملیات امن تغییر نقش کاربران توسط مدیر کل
    path('admin/users/<uuid:user_id>/update-role/', AdminUpdateUserRoleView.as_view(), name='update_user_role'),
]