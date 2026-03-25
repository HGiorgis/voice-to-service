"""Registration abuse checks + device cookie (server-side)."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from typing import Optional, Tuple

from django.conf import settings
from django.core import signing
from django.db.models import Q
from django.utils import timezone

from apps.authentication.disposable_email import (
    email_domain,
    is_disposable_domain,
    is_gmail_domain,
)
from apps.authentication.models import (
    AntiAbuseSettings,
    BlockedIPAddress,
    RegistrationAttempt,
)

logger = logging.getLogger(__name__)

# Shown to end users for blocked signups (web, OAuth). Staff-facing detail stays in logs / RegistrationAttempt.
PUBLIC_REGISTRATION_DENIED_MESSAGE = (
    'Registration cannot be completed. If you already have an account, please sign in.'
)

DEVICE_COOKIE_NAME = getattr(settings, 'VTS_DEVICE_COOKIE_NAME', 'vts_did')
DEVICE_SIGN_SALT = 'vts-device-cookie-v1'


def get_client_ip(request) -> str:
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()[:45]
    return (request.META.get('REMOTE_ADDR') or '')[:45]


def hash_fingerprint(raw: str) -> str:
    s = (raw or '').strip()[:2000]
    return hashlib.sha256(s.encode('utf-8', errors='ignore')).hexdigest()


def _fp_hash_or_empty(raw: str) -> str:
    if not (raw or '').strip():
        return ''
    return hash_fingerprint(raw)


def is_ip_explicitly_blocked(ip: str) -> Optional[str]:
    if not ip:
        return None
    now = timezone.now()
    qs = BlockedIPAddress.objects.filter(ip_address=ip, is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    row = qs.order_by('-created_at').first()
    if not row:
        return None
    return row.reason or 'This network address is not allowed to register.'


def _maybe_expire_block(row: BlockedIPAddress) -> bool:
    now = timezone.now()
    if row.expires_at and row.expires_at <= now:
        row.is_active = False
        row.save(update_fields=['is_active'])
        return False
    return True


def check_registration_allowed(
    request,
    *,
    email: str,
    client_fingerprint: str,
    password_signup: bool = True,
) -> Tuple[Optional[str], bool]:
    """
    Returns (internal_reason_for_staff_logs_or_None, should_flag_ip_for_auto_block).
    Never use the first value as user-visible copy; use PUBLIC_REGISTRATION_DENIED_MESSAGE.
    """
    cfg = AntiAbuseSettings.get_settings()
    if not cfg.master_enable:
        return None, False

    ip = get_client_ip(request)
    fph = _fp_hash_or_empty(client_fingerprint)

    blocked_msg = is_ip_explicitly_blocked(ip)
    if blocked_msg:
        return blocked_msg, False

    dom = email_domain(email)

    if cfg.block_disposable_email and dom and is_disposable_domain(dom):
        return ('blocked: disposable email domain', True)

    if (
        password_signup
        and cfg.require_gmail_domain_for_password_signup
        and dom
        and not is_gmail_domain(dom)
    ):
        return ('blocked: password signup gmail-only rule', False)

    if cfg.device_tracker_cookie_enabled:
        raw_cookie = request.COOKIES.get(DEVICE_COOKIE_NAME)
        if raw_cookie:
            try:
                did = uuid.UUID(signing.Signer(salt=DEVICE_SIGN_SALT).unsign(raw_cookie))
            except (signing.BadSignature, ValueError, TypeError):
                did = None
            if did:
                from apps.users.models import User

                if User.objects.filter(registration_device_id=did).exists():
                    return ('blocked: device cookie already linked to an account', False)

    from apps.users.models import User

    now = timezone.now()

    if cfg.block_same_ip_registration and ip:
        since = now - timedelta(hours=cfg.same_ip_lookback_hours)
        max_ip = cfg.max_accounts_per_ip_in_lookback
        if max_ip > 0:
            n = User.objects.filter(registration_ip=ip, date_joined__gte=since).count()
            if n >= max_ip:
                return ('blocked: max accounts per IP in lookback', True)

    if cfg.block_same_fingerprint and fph:
        since = now - timedelta(hours=cfg.fingerprint_lookback_hours)
        n = User.objects.filter(
            registration_fingerprint_hash=fph,
            date_joined__gte=since,
        ).count()
        if n >= 1:
            return ('blocked: fingerprint reuse in lookback', True)

    if cfg.block_rapid_registration_window:
        rw = now - timedelta(minutes=cfg.rapid_registration_window_minutes)
        if ip:
            attempts_ip = RegistrationAttempt.objects.filter(
                ip_address=ip,
                created_at__gte=rw,
                outcome=RegistrationAttempt.Outcome.SUCCESS,
            ).count()
            if attempts_ip >= cfg.max_registrations_per_ip_in_rapid_window:
                return ('blocked: rapid signup limit (IP)', True)
        if fph:
            attempts_fp = RegistrationAttempt.objects.filter(
                fingerprint_hash=fph,
                created_at__gte=rw,
                outcome=RegistrationAttempt.Outcome.SUCCESS,
            ).count()
            if attempts_fp >= cfg.max_registrations_per_fingerprint_in_rapid_window:
                return ('blocked: rapid signup limit (fingerprint)', True)

    return None, False


def log_registration_attempt(
    *,
    ip: str,
    fingerprint_hash: str,
    email: str,
    outcome: str,
    detail: str = '',
    username: str = '',
    email_input: str = '',
    raw_fingerprint: str = '',
    fingerprint_preview: str = '',
    user_agent: str = '',
    device_class: str = '',
    browser_family: str = '',
    os_family: str = '',
    user=None,
) -> None:
    from apps.authentication.device_info import fingerprint_preview as make_preview

    ow = outcome if isinstance(outcome, str) else getattr(outcome, 'value', str(outcome))
    em = (email_input or email or '').strip()[:254]
    prev = (fingerprint_preview or make_preview(raw_fingerprint, fingerprint_hash))[:220]
    RegistrationAttempt.objects.create(
        ip_address=ip or '0.0.0.0',
        fingerprint_hash=fingerprint_hash or '',
        fingerprint_preview=prev,
        email_domain=email_domain(em or email),
        email_input=em,
        username_input=(username or '')[:150],
        user_agent=user_agent or '',
        device_class=(device_class or '')[:32],
        browser_family=(browser_family or '')[:64],
        os_family=(os_family or '')[:64],
        outcome=ow,
        detail=(detail or '')[:500],
        user=user if user is not None else None,
    )


def maybe_auto_block_ip_after_burst(ip: str) -> None:
    if not ip:
        return
    cfg = AntiAbuseSettings.get_settings()
    if not cfg.master_enable or not cfg.auto_block_ip_on_burst:
        return
    now = timezone.now()
    since = now - timedelta(minutes=cfg.suspicious_burst_window_minutes)
    n = RegistrationAttempt.objects.filter(
        ip_address=ip,
        created_at__gte=since,
    ).count()
    if n < cfg.suspicious_burst_registration_count:
        return
    if BlockedIPAddress.objects.filter(
        ip_address=ip, is_active=True, blocked_automatically=True
    ).exists():
        return
    expires = now + timedelta(days=cfg.auto_blocked_ip_duration_days)
    BlockedIPAddress.objects.create(
        ip_address=ip,
        reason='Automatic block: repeated registration attempts from this address.',
        expires_at=expires,
        blocked_automatically=True,
        is_active=True,
    )
    logger.warning('Auto-blocked IP %s until %s', ip, expires)


def attach_device_cookie(response, user) -> None:
    cfg = AntiAbuseSettings.get_settings()
    if not cfg.device_tracker_cookie_enabled:
        return
    if user.registration_device_id:
        token = str(user.registration_device_id)
    else:
        token = str(uuid.uuid4())
    signed = signing.Signer(salt=DEVICE_SIGN_SALT).sign(token)
    max_age = 86400 * max(1, int(cfg.device_tracker_cookie_max_age_days))
    response.set_cookie(
        DEVICE_COOKIE_NAME,
        signed,
        max_age=max_age,
        httponly=True,
        samesite='Lax',
        secure=getattr(settings, 'SESSION_COOKIE_SECURE', False),
    )


def persist_device_id_on_user(user, request) -> None:
    """Assign registration_device_id from cookie or new UUID after successful signup."""
    cfg = AntiAbuseSettings.get_settings()
    if not cfg.device_tracker_cookie_enabled:
        return
    raw = request.COOKIES.get(DEVICE_COOKIE_NAME)
    uid = None
    if raw:
        try:
            uid = uuid.UUID(signing.Signer(salt=DEVICE_SIGN_SALT).unsign(raw))
        except (signing.BadSignature, ValueError, TypeError):
            uid = None
    if uid is None:
        uid = uuid.uuid4()
    if user.registration_device_id != uid:
        user.registration_device_id = uid
        user.save(update_fields=['registration_device_id'])
