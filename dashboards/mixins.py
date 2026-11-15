from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect


class RoleRequiredMixin(LoginRequiredMixin):
    """
    گارد امنیتی سمت سرور برای کنترل دسترسی مبتنی بر نقش (RBAC) و الزام تکمیل 2FA.
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.session.get('is_2fa_verified', False):
            messages.error(request, 'برای ورود به پنل کاربری، تکمیل احراز هویت دومرحله‌ای الزامی است.')
            return redirect('accounts:verify_2fa')

        if not request.user.is_active or request.user.status == 'suspended':
            messages.error(request, 'حساب کاربری شما مسدود یا غیرفعال است.')
            return redirect('accounts:login')

        if self.allowed_roles and request.user.role not in self.allowed_roles:
            messages.warning(
                request,
                'دسترسی غیرمجاز: شما مجوز ورود به پنل آن نقش کاربری را ندارید.'
            )
            return redirect(request.user.get_dashboard_url_name())

        return super().dispatch(request, *args, **kwargs)