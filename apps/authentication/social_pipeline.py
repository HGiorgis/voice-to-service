"""social-auth-app-django pipeline steps for Google sign-in."""
from django.utils import timezone
from social_core.exceptions import AuthForbidden

from apps.authentication.antiabuse import (
    PUBLIC_REGISTRATION_DENIED_MESSAGE,
    check_registration_allowed,
    get_client_ip,
    hash_fingerprint,
    log_registration_attempt,
    maybe_auto_block_ip_after_burst,
    persist_device_id_on_user,
)
from apps.authentication.device_info import classify_request
from apps.authentication.models import AntiAbuseSettings, RegistrationAttempt
from apps.core.models import SystemSettings


def reject_blocked_user(strategy, backend, user=None, *args, **kwargs):
    if user is not None and getattr(user, 'is_blocked', False):
        msg = (getattr(user, 'blocked_reason', None) or '').strip()
        if not msg:
            msg = 'This account has been suspended.'
        raise AuthForbidden(backend, msg)
    return {}


def enforce_oauth_registration_rules(strategy, details, backend, user=None, *args, **kwargs):
    """
    After create_user, before associate_user: apply anti-abuse to *new* Google sign-ups
    (same checks as password flow, except Gmail-only applies to password only).
    """
    if user is None or not kwargs.get('is_new'):
        return {}
    cfg = AntiAbuseSettings.get_settings()
    if not cfg.master_enable or not cfg.oauth_signup_antiabuse_enabled:
        return {}

    req = strategy.request
    fp_raw = (req.session.get('vts_oauth_client_fingerprint') or '')[:2000]
    email = (user.email or '').strip()
    if not email:
        email = ((details or {}).get('email') or '').strip()

    block_internal, _burst = check_registration_allowed(
        req,
        email=email,
        client_fingerprint=fp_raw,
        password_signup=False,
    )
    ip = get_client_ip(req)
    fph = hash_fingerprint(fp_raw)
    ci = classify_request(req)

    if block_internal:
        req.session.pop('vts_oauth_client_fingerprint', None)
        user.delete()
        log_registration_attempt(
            ip=ip,
            fingerprint_hash=fph,
            email=email,
            email_input=email,
            username_input='',
            raw_fingerprint=fp_raw,
            user_agent=ci['user_agent'],
            device_class=ci['device_class'],
            browser_family=ci['browser_family'],
            os_family=ci['os_family'],
            outcome=RegistrationAttempt.Outcome.BLOCKED,
            detail=f'oauth_signup {block_internal}'[:500],
        )
        maybe_auto_block_ip_after_burst(ip)
        raise AuthForbidden(backend, PUBLIC_REGISTRATION_DENIED_MESSAGE)
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


def finalize_new_oauth_registration(strategy, backend, user=None, *args, **kwargs):
    """Clear session fingerprint; stamp device + audit log for successful new Google signups."""
    req = strategy.request
    fp_raw = (req.session.pop('vts_oauth_client_fingerprint', None) or '')[:2000]
    if user is None or not kwargs.get('is_new'):
        return {}

    email = (user.email or '').strip()
    fph = hash_fingerprint(fp_raw)
    ip = get_client_ip(req)
    ci = classify_request(req)

    if fph and not (user.registration_fingerprint_hash or '').strip():
        user.registration_fingerprint_hash = fph
        user.save(update_fields=['registration_fingerprint_hash'])

    persist_device_id_on_user(user, req)
    log_registration_attempt(
        ip=ip,
        fingerprint_hash=fph,
        email=email,
        email_input=email,
        username_input=(user.username or '')[:150],
        raw_fingerprint=fp_raw,
        user_agent=ci['user_agent'],
        device_class=ci['device_class'],
        browser_family=ci['browser_family'],
        os_family=ci['os_family'],
        outcome=RegistrationAttempt.Outcome.SUCCESS,
        detail='google_oauth_signup',
        user=user,
    )
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
