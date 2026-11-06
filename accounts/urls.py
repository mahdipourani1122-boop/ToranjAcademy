from django.urls import path
from .views import (
    StudentRegisterView,
    UserLoginView,
    TwoFactorVerifyView,
    UserLogoutView,
    SecuritySettingsView,
    TOTPSetupView,
    RecoveryCodesView,
    TrustedDevicesView,
    SecurePasswordChangeView,
    AdminApproveStudentView,
    ToranjPasswordResetView,
    ToranjPasswordResetDoneView,
    ToranjPasswordResetConfirmView,
    ToranjPasswordResetCompleteView,
)

app_name = 'accounts'

urlpatterns = [
    path('register/', StudentRegisterView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('verify-2fa/', TwoFactorVerifyView.as_view(), name='verify_2fa'),
    path('logout/', UserLogoutView.as_view(), name='logout'),

    # صفحات مدیریت امنیت حساب کاربری
    path('security/', SecuritySettingsView.as_view(), name='security_settings'),
    path('security/totp/', TOTPSetupView.as_view(), name='totp_setup'),
    path('security/recovery-codes/', RecoveryCodesView.as_view(), name='recovery_codes'),
    path('security/trusted-devices/', TrustedDevicesView.as_view(), name='trusted_devices'),
    path('security/password-change/', SecurePasswordChangeView.as_view(), name='password_change'),

    # تأیید زبان‌آموز و صدور کد TRJ توسط ادمین
    path('admin/approve-student/<uuid:user_id>/', AdminApproveStudentView.as_view(), name='approve_student'),

    # بازیابی رمز عبور با توکن زمان‌دار یک‌بارمصرف
    path('password-reset/', ToranjPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', ToranjPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', ToranjPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/complete/', ToranjPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]