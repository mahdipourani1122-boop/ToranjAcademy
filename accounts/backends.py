from django.contrib.auth.backends import ModelBackend
from django.db.models import Q
from .models import User


class ToranjAuthenticationBackend(ModelBackend):
    """
    احراز هویت امن با نام کاربری آکادمی (TRJ-26XXXX)، شماره موبایل یا ایمیل.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or kwargs.get('identifier') or '').strip()
        if not identifier or not password:
            return None

        user = User.objects.filter(
            Q(academy_username__iexact=identifier)
            | Q(phone=identifier)
            | Q(email__iexact=identifier)
        ).first()

        if not user:
            # اجرای هش فرضی جهت جلوگیری از حملات زمان‌سنجی (Timing Attack)
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None