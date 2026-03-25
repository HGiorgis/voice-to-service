"""Expire incomplete email-verification signups."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.users.models import User

SESSION_PENDING_VERIFY = 'vts_pending_verification_user_id'


def purge_expired_unverified_users(request=None) -> int:
    """
    Delete users who never completed email verification by the configured deadline.
    Returns how many rows were deleted. Clears stale pending session if needed.
    """
    hours = int(getattr(settings, 'UNVERIFIED_SIGNUP_EXPIRE_HOURS', 48) or 48)
    hours = max(1, min(hours, 720))
    cutoff = timezone.now() - timedelta(hours=hours)
    qs = User.objects.filter(
        is_verified=False,
        is_active=False,
        date_joined__lt=cutoff,
        is_superuser=False,
    )
    stale_ids = {str(pk) for pk in qs.values_list('pk', flat=True)}
    n, _ = qs.delete()
    if request and stale_ids:
        sid = request.session.get(SESSION_PENDING_VERIFY)
        if sid and str(sid) in stale_ids:
            request.session.pop(SESSION_PENDING_VERIFY, None)
    return n
