"""Shared helpers for voice pipeline logging (sync API + streaming test UI)."""
import json
from datetime import datetime, timezone as dt_timezone


def log_api_call(request, api_key, endpoint, method, status_code, response_time_sec):
    if not api_key:
        return
    ip = request.META.get('REMOTE_ADDR') or '0.0.0.0'
    try:
        from apps.authentication.models import APIKeyLog

        APIKeyLog.objects.create(
            api_key_id=api_key.id,
            endpoint=endpoint or '/api/v1/process-audio/',
            method=method or 'POST',
            status_code=status_code,
            ip_address=ip,
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:500],
            response_time=response_time_sec,
        )
    except Exception:
        pass


def log_ts():
    return datetime.now(dt_timezone.utc).strftime('%H:%M:%S')


def append_log(pipeline_log, step, label, status, lines):
    """status: ok | warn | error | skip | info"""
    if lines is None:
        lines = []
    elif isinstance(lines, str):
        lines = [lines]
    else:
        lines = [str(x) for x in lines]
    entry = {
        't': log_ts(),
        'step': step,
        'label': label,
        'status': status,
        'lines': lines,
    }
    pipeline_log.append(entry)
    return entry


def pretty_json(obj, max_len=6000):
    try:
        s = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except TypeError:
        s = str(obj)
    if len(s) > max_len:
        return s[: max_len - 20] + '\n… [truncated]'
    return s
