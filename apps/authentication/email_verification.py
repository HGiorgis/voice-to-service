"""Email OTP for password registration (Google OAuth skips this)."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def _pepper() -> str:
    return getattr(settings, 'SECRET_KEY', '') or 'dev'


def hash_email_code(user_id, code: str) -> str:
    raw = f'{_pepper()}:{user_id}:{(code or "").strip()}'.encode('utf-8', errors='ignore')
    return hashlib.sha256(raw).hexdigest()


def codes_match(user, submitted: str) -> bool:
    if not getattr(user, 'email_verification_code_hash', None) or not (submitted or '').strip():
        return False
    expect = hash_email_code(user.pk, submitted)
    return secrets.compare_digest(user.email_verification_code_hash, expect)


def issue_new_code(user) -> str:
    """Persist a fresh 6-digit code and expiry; returns plaintext code for email only."""
    code = f'{secrets.randbelow(1_000_000):06d}'
    mins = int(getattr(settings, 'EMAIL_VERIFICATION_EXPIRE_MINUTES', 15))
    now = timezone.now()
    user.email_verification_code_hash = hash_email_code(user.pk, code)
    user.email_verification_sent_at = now
    user.email_verification_expires_at = now + timedelta(minutes=max(5, mins))
    user.save(
        update_fields=[
            'email_verification_code_hash',
            'email_verification_sent_at',
            'email_verification_expires_at',
        ]
    )
    return code


def _format_from_email() -> str:
    """
    Inbox-friendly From: show product name, not only the SMTP username.
    Accepts DEFAULT_FROM_EMAIL as 'addr@x.com' or 'Name <addr@x.com>'.
    """
    raw = (getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'noreply@localhost').strip()
    name = (getattr(settings, 'DEFAULT_FROM_NAME', None) or 'Voice To Service').strip()
    if '<' in raw and '>' in raw:
        return raw
    return f'{name} <{raw}>'


def send_verification_email(*, user, code: str) -> None:
    product = (getattr(settings, 'DEFAULT_FROM_NAME', None) or 'Voice To Service').strip()
    subject = f'{product} — Your verification code'
    verify_path = reverse('auth:verify-email')
    base = getattr(settings, 'FRONTEND_URL', 'http://localhost:8000').rstrip('/')
    verify_url = f'{base}{verify_path}'

    context = {
        'code': code,
        'user_email': user.email,
        'verify_url': verify_url,
        'brand_name': product,
        'expire_minutes': int(getattr(settings, 'EMAIL_VERIFICATION_EXPIRE_MINUTES', 15)),
    }
    body_text = (
        f'{product}\n'
        f'Your verification code is: {code}\n\n'
        f'Open the verification page and enter the code with your name:\n'
        f'{verify_url}\n\n'
        f'This code expires in {context["expire_minutes"]} minutes.\n'
        f'If you did not sign up, ignore this email.\n'
    )
    html_body = render_to_string('email/email_verification.html', context)

    from_email = _format_from_email()
    timeout = getattr(settings, 'EMAIL_TIMEOUT', None)
    connection = get_connection(fail_silently=False, timeout=timeout)
    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=from_email,
        to=[user.email],
        connection=connection,
    )
    msg.attach_alternative(html_body, 'text/html')
    try:
        msg.send(fail_silently=False)
    except OSError as exc:
        # Errno 101 "Network is unreachable", timeouts, etc. — fail fast; do not block ASGI long.
        logger.warning(
            'Verification email SMTP/network error for %s (%s): %s',
            user.email,
            type(exc).__name__,
            exc,
        )
        raise
    except Exception:
        logger.exception('Failed to send verification email to %s', user.email)
        raise
