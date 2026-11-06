from django.core.cache import cache
from .models import SecurityEvent


def get_client_ip(request) -> str:
    if not request:
        return '127.0.0.1'
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def get_user_agent(request) -> str:
    if not request:
        return ''
    return request.META.get('HTTP_USER_AGENT', '')[:250]


def is_rate_limited(scope: str, identifier: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
    key = f"toranj_rl_{scope}_{identifier}"
    attempts = cache.get(key, 0)
    return attempts >= max_attempts


def record_rate_limit_hit(scope: str, identifier: str, window_seconds: int = 300) -> int:
    key = f"toranj_rl_{scope}_{identifier}"
    attempts = cache.get(key, 0) + 1
    cache.set(key, attempts, timeout=window_seconds)
    return attempts


def clear_rate_limit(scope: str, identifier: str):
    cache.delete(f"toranj_rl_{scope}_{identifier}")


def log_security_event(request, event_type: str, description: str, user=None, severity=SecurityEvent.Severity.INFO):
    """ثبت امن رویدادها در دیتابیس؛ هرگز رمز، OTP یا توکن را در description قرار ندهید."""
    SecurityEvent.objects.create(
        user=user,
        event_type=event_type,
        severity=severity,
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        description=description[:255]
    )