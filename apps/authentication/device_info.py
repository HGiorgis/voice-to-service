"""Lightweight User-Agent / client classification (no extra packages)."""
from __future__ import annotations

import re
from typing import Any, Dict


def _snip(s: str, max_len: int = 180) -> str:
    s = (s or '').strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'


def classify_request(request) -> Dict[str, Any]:
    """
    Return device_class, browser_family, os_family from UA + Client Hints (if any).
    device_class: desktop | mobile | tablet | bot | unknown
    """
    ua = (request.META.get('HTTP_USER_AGENT') or '')[:4000]
    ua_low = ua.lower()

    if not ua.strip():
        return {
            'user_agent': '',
            'device_class': 'unknown',
            'browser_family': '',
            'os_family': '',
        }

    # Bots / scripts
    if any(
        x in ua_low
        for x in (
            'bot',
            'crawl',
            'spider',
            'headless',
            'python-requests',
            'curl/',
            'wget',
            'httpclient',
            'libwww',
        )
    ):
        return {
            'user_agent': ua,
            'device_class': 'bot',
            'browser_family': _guess_browser(ua_low),
            'os_family': _guess_os(ua_low),
        }

    ch_mobile = (request.META.get('HTTP_SEC_CH_UA_MOBILE') or '').strip().strip('?').lower()
    if ch_mobile == '1':
        return {
            'user_agent': ua,
            'device_class': 'mobile',
            'browser_family': _guess_browser(ua_low),
            'os_family': _guess_os(ua_low),
        }

    if 'tablet' in ua_low or 'ipad' in ua_low or re.search(r'\bandroid\b.*\btablet\b', ua_low):
        return {
            'user_agent': ua,
            'device_class': 'tablet',
            'browser_family': _guess_browser(ua_low),
            'os_family': _guess_os(ua_low),
        }

    if 'mobi' in ua_low or 'iphone' in ua_low or 'ipod' in ua_low:
        return {
            'user_agent': ua,
            'device_class': 'mobile',
            'browser_family': _guess_browser(ua_low),
            'os_family': _guess_os(ua_low),
        }

    return {
        'user_agent': ua,
        'device_class': 'desktop',
        'browser_family': _guess_browser(ua_low),
        'os_family': _guess_os(ua_low),
    }


def _guess_browser(ua_low: str) -> str:
    if 'edg/' in ua_low or 'edga/' in ua_low:
        return 'Edge'
    if 'chrome/' in ua_low and 'chromium' not in ua_low:
        return 'Chrome'
    if 'firefox/' in ua_low:
        return 'Firefox'
    if 'safari/' in ua_low and 'chrome' not in ua_low:
        return 'Safari'
    if 'opr/' in ua_low or 'opera' in ua_low:
        return 'Opera'
    return ''


def _guess_os(ua_low: str) -> str:
    if 'windows nt' in ua_low:
        return 'Windows'
    if 'mac os x' in ua_low or 'macintosh' in ua_low:
        return 'macOS'
    if 'android' in ua_low:
        return 'Android'
    if 'iphone' in ua_low or 'ipad' in ua_low or 'ios' in ua_low:
        return 'iOS'
    if 'linux' in ua_low:
        return 'Linux'
    return ''


def fingerprint_preview(raw: str, fingerprint_hash: str) -> str:
    """Short non-secret label for tables (hash prefix + snippet hint)."""
    h = (fingerprint_hash or '')[:12]
    raw_snip = _snip(raw.replace('\n', ' '), 80)
    if h and raw_snip:
        return f'{h}… · {raw_snip}'
    if h:
        return f'{h}…'
    return raw_snip
