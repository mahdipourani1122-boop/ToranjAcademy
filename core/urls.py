from django.urls import path
from .views import (
    HomePageView,
    LanguageDepartmentLandingView,
    GuestExploreView,
    RolePortalLoginView,
)

app_name = 'core'

urlpatterns = [
    path('', HomePageView.as_view(), name='home'),
    # چهار صفحه اختصاصی دپارتمان‌های زبان
    path('languages/english/', LanguageDepartmentLandingView.as_view(language_key='english'), name='language_english'),
    path('languages/german/', LanguageDepartmentLandingView.as_view(language_key='german'), name='language_german'),
    path('languages/french/', LanguageDepartmentLandingView.as_view(language_key='french'), name='language_french'),
    path('languages/turkish/', LanguageDepartmentLandingView.as_view(language_key='turkish'), name='language_turkish'),
    # مسیر گشت‌وگذار مهمان و درگاه‌های ورود تفکیک‌شده (دانشجو / استاد / مدیریت)
    path('explore/', GuestExploreView.as_view(), name='guest_explore'),
    path('portal/student/login/', RolePortalLoginView.as_view(portal_type='student'), name='student_portal_login'),
    path('portal/teacher/login/', RolePortalLoginView.as_view(portal_type='teacher'), name='teacher_portal_login'),
    path('portal/management/login/', RolePortalLoginView.as_view(portal_type='management'), name='management_portal_login'),
]