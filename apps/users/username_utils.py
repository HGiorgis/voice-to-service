"""Derive unique usernames from email local parts (password signup + Google OAuth)."""
import re
import secrets

from django.contrib.auth import get_user_model

User = get_user_model()

# Leave room for "-NNN" suffix (4 chars) under AbstractUser.username max_length=150
_MAX_BASE_LEN = 146


def _sanitize_local_part(local: str) -> str:
    s = (local or '').strip().lower()
    s = re.sub(r'[^\w.-]+', '_', s, flags=re.ASCII)
    s = re.sub(r'_+', '_', s).strip('._-')
    if not s:
        return 'user'
    return s[:_MAX_BASE_LEN]


def allocate_username_from_email(email: str) -> str:
    """
    Use the part before @ as username; on conflict append -XXX (3 random digits).
    """
    email = (email or '').strip()
    if '@' not in email:
        base = 'user'
    else:
        local = email.split('@', 1)[0]
        base = _sanitize_local_part(local)
    base = base[:_MAX_BASE_LEN]
    if not User.objects.filter(username__iexact=User.normalize_username(base)).exists():
        return User.normalize_username(base)
    for _ in range(80):
        suffix = f'-{secrets.randbelow(1000):03d}'
        candidate = (base[: _MAX_BASE_LEN - len(suffix)] + suffix)[:150]
        cand_norm = User.normalize_username(candidate)
        if not User.objects.filter(username__iexact=cand_norm).exists():
            return cand_norm
    # Extremely unlikely: fall back to longer random tail
    tail = secrets.token_hex(4)
    candidate = (base[: 150 - 1 - len(tail)] + '-' + tail)[:150]
    return User.normalize_username(candidate)
