"""Disposable email domains: primary lists from data/*.conf (allowlist overrides blocklist)."""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import FrozenSet

from django.conf import settings

_lock = threading.Lock()
_allowlist: FrozenSet[str] | None = None
_blocklist: FrozenSet[str] | None = None


def _data_dir() -> Path:
    return Path(settings.BASE_DIR) / 'data'


def _read_domain_lines(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    out: set[str] = set()
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return frozenset()
    for line in raw.splitlines():
        line = line.strip().lower()
        if not line or line.startswith('#'):
            continue
        out.add(line)
    return frozenset(out)


def _load_lists() -> None:
    global _allowlist, _blocklist
    with _lock:
        if _allowlist is not None and _blocklist is not None:
            return
        d = _data_dir()
        _allowlist = _read_domain_lines(d / 'allowlist.conf')
        _blocklist = _read_domain_lines(d / 'disposable_email_blocklist.conf')


def reload_disposable_lists() -> None:
    """Call after replacing data files at runtime (tests / admin action)."""
    global _allowlist, _blocklist
    with _lock:
        _allowlist = None
        _blocklist = None
    _load_lists()


def email_domain(email: str) -> str:
    if not email or '@' not in email:
        return ''
    return email.rsplit('@', 1)[-1].strip().lower()


def is_disposable_domain(domain: str) -> bool:
    d = (domain or '').strip().lower()
    if not d:
        return False
    _load_lists()
    assert _allowlist is not None and _blocklist is not None
    if d in _allowlist:
        return False
    if d in _blocklist:
        return True
    for root in _blocklist:
        if d.endswith('.' + root):
            return True
    if re.match(r'^mail\d*\.', d) and 'temp' in d:
        return True
    return False


def is_gmail_domain(domain: str) -> bool:
    d = (domain or '').lower()
    return d in ('gmail.com', 'googlemail.com')
