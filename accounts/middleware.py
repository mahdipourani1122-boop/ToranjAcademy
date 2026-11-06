from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from .models import UserSession


class SessionSecurityAnd2FAMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            session_key = request.session.session_key
            if session_key:
                key_hash = UserSession.hash_session_key(session_key)
                tracked = UserSession.objects.filter(session_key_hash=key_hash).first()
                if tracked and tracked.revoked_at is not None:
                    logout(request)
                    return redirect('accounts:login')
                elif tracked:
                    tracked.last_seen_at = timezone.now()
                    tracked.save(update_fields=['last_seen_at'])

            # ممانعت قطعی از دسترسی به داشبوردها پیش از تکمیل 2FA
            if request.path.startswith('/dashboard/'):
                if not request.session.get('is_2fa_verified', False):
                    logout(request)
                    return redirect(reverse('accounts:login'))

        return self.get_response(request)