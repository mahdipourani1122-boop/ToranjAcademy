from django.urls import path
from .views import (
    MyAcademicProfileRedirectView,
    StudentUnifiedProfileView,
    RecordStudentAssessmentView,
    RecordStudentNoteView,
    RecordStudentAttendanceQuickView,
    StudentProgressReportView,
    TeacherUnifiedProfileView,
    AdminAcademicAnalyticsHubView,
)

app_name = 'academics'

urlpatterns = [
    path('me/', MyAcademicProfileRedirectView.as_view(), name='my_profile'),
    path('students/<uuid:student_id>/profile/', StudentUnifiedProfileView.as_view(), name='student_profile'),
    path('students/<uuid:student_id>/assessments/add/', RecordStudentAssessmentView.as_view(), name='add_assessment'),
    path('students/<uuid:student_id>/notes/add/', RecordStudentNoteView.as_view(), name='add_note'),
    path('students/<uuid:student_id>/attendance/add/', RecordStudentAttendanceQuickView.as_view(), name='add_attendance'),
    path('students/<uuid:student_id>/report/', StudentProgressReportView.as_view(), name='student_report'),
    path('teachers/<uuid:teacher_id>/profile/', TeacherUnifiedProfileView.as_view(), name='teacher_profile'),
    path('admin/hub/', AdminAcademicAnalyticsHubView.as_view(), name='admin_hub'),
]
