"""social-auth-app-django pipeline steps for Google sign-in."""
from django.utils import timezone
from social_core.exceptions import AuthForbidden

from apps.authentication.antiabuse import get_client_ip
from apps.core.models import SystemSettings


def reject_blocked_user(strategy, backend, user=None, *args, **kwargs):
    if user is not None and getattr(user, 'is_blocked', False):
        raise AuthForbidden(backend, 'This account has been suspended.')
    return {}


def set_google_identity(strategy, details, backend, user=None, *args, **kwargs):
    """Trust Google-verified email; stamp profile fields."""
    if user is None:
        return {}
    uid = (kwargs.get('uid') or '')[:255]
    update_fields = []
    if uid and not (getattr(user, 'google_sub', None) or '').strip():
        user.google_sub = uid
        update_fields.append('google_sub')
    user.is_verified = True
    update_fields.append('is_verified')
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        update_fields.append('email_verified_at')
    email = (details or {}).get('email')
    if email and not (user.email or '').strip():
        user.email = email
        update_fields.append('email')
    if update_fields:
        user.save(update_fields=list(set(update_fields)))
    return {}


def set_registration_ip_social(strategy, backend, user=None, *args, **kwargs):
    if user is None:
        return {}
    req = strategy.request
    ip = get_client_ip(req)
    if ip and not (user.registration_ip or '').strip():
        user.registration_ip = ip
        user.save(update_fields=['registration_ip'])
    return {}


def apply_default_limits(strategy, backend, user=None, *args, **kwargs):
    """New Google users get the same limits as password registration."""
    if user is None or not kwargs.get('is_new'):
        return {}
    try:
        s = SystemSettings.get_settings()
        user.daily_request_limit = s.default_daily_limit
        user.monthly_request_limit = s.default_monthly_limit
        user.daily_voice_limit = s.default_daily_voice_limit
        user.save(
            update_fields=[
                'daily_request_limit',
                'monthly_request_limit',
                'daily_voice_limit',
            ]
        )
    except Exception:
        pass
    return {}
