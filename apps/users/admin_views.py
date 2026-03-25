import json
import subprocess
import re
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Avg, Q
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from apps.users.models import User
from apps.voice.models import VoiceProcessingRequest
from apps.authentication.models import (
    APIKey,
    APIKeyLog,
    AntiAbuseSettings,
    BlockedIPAddress,
    RegistrationAttempt,
)
from apps.core.models import SystemSettings


def _safe_uint(val, default, minimum=1):
    """Parse a non-negative int; on error return *default*. Clamp to *minimum*."""
    try:
        return max(minimum, int(val))
    except (TypeError, ValueError):
        return default


def _safe_uint_min0(val, default):
    """Like _safe_uint with minimum 0 (for “0 = disabled” tunables)."""
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return default


@staff_member_required
def admin_dashboard(request):
    """Admin dashboard — Voice To Service metrics."""
    total_users = User.objects.count()
    active_today = User.objects.filter(last_login__date=timezone.now().date()).count()
    today = timezone.now().date()

    total_voice = VoiceProcessingRequest.objects.count()
    voice_today = VoiceProcessingRequest.objects.filter(created_at__date=today).count()
    completed = VoiceProcessingRequest.objects.filter(status=VoiceProcessingRequest.Status.COMPLETED).count()
    failed = VoiceProcessingRequest.objects.filter(status=VoiceProcessingRequest.Status.FAILED).count()

    recent_voice = VoiceProcessingRequest.objects.select_related('user').order_by('-created_at')[:15]

    total_api_calls = APIKeyLog.objects.count()
    api_calls_today = APIKeyLog.objects.filter(timestamp__date=today).count()
    active_keys = APIKey.objects.filter(is_active=True).count()

    context = {
        'total_users': total_users,
        'active_today': active_today,
        'total_voice': total_voice,
        'voice_today': voice_today,
        'voice_completed': completed,
        'voice_failed': failed,
        'recent_voice': recent_voice,
        'total_api_calls': total_api_calls,
        'api_calls_today': api_calls_today,
        'active_keys': active_keys,
    }
    return render(request, 'admin/dashboard.html', context)


@staff_member_required
def voice_request_list(request):
    """List voice processing requests."""
    status_filter = request.GET.get('status', 'all')
    category_filter = request.GET.get('category', 'all')

    qs = VoiceProcessingRequest.objects.select_related('user').order_by('-created_at')
    if status_filter != 'all':
        qs = qs.filter(status=status_filter)
    if category_filter != 'all':
        qs = qs.filter(category__iexact=category_filter)

    context = {
        'requests': qs,
        'status_filter': status_filter,
        'category_filter': category_filter,
    }
    return render(request, 'admin/voice_list.html', context)


@staff_member_required
def voice_request_detail(request, request_id):
    """Read-only detail for one voice request."""
    vr = get_object_or_404(VoiceProcessingRequest, id=request_id)
    meta_json = None
    if vr.pipeline_metadata:
        meta_json = json.dumps(vr.pipeline_metadata, indent=2, ensure_ascii=False)
    return render(request, 'admin/voice_detail.html', {'vr': vr, 'meta_json': meta_json})


@staff_member_required
def user_list(request):
    """List all users."""
    users = User.objects.annotate(
        voice_count=Count('voice_requests'),
        api_calls=Count('api_key__logs'),
    ).order_by('-date_joined')
    return render(request, 'admin/users.html', {'users': users})


@staff_member_required
def revoke_user_key(request, user_id):
    if request.method == 'POST':
        user = get_object_or_404(User, id=user_id)
        APIKey.objects.filter(user=user).delete()
        messages.success(request, f'API key for {user.username} revoked successfully')
    return redirect('admin:user-detail', user_id=user_id)


@staff_member_required
def user_detail(request, user_id):
    target_user = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        try:
            target_user.daily_request_limit = int(
                request.POST.get('daily_limit', target_user.daily_request_limit) or 1000
            )
        except (TypeError, ValueError):
            target_user.daily_request_limit = 1000
        try:
            target_user.monthly_request_limit = int(
                request.POST.get('monthly_limit', target_user.monthly_request_limit) or 30000
            )
        except (TypeError, ValueError):
            target_user.monthly_request_limit = 30000
        try:
            target_user.daily_voice_limit = max(
                0,
                int(request.POST.get('daily_voice_limit', target_user.daily_voice_limit) or 3),
            )
        except (TypeError, ValueError):
            target_user.daily_voice_limit = 3
        target_user.is_active = request.POST.get('is_active') == 'on'
        target_user.is_verified = request.POST.get('is_verified') == 'on'
        target_user.save()
        messages.success(request, 'User updated successfully')
        return redirect('admin:user-detail', user_id=target_user.id)

    voice_requests = VoiceProcessingRequest.objects.filter(user=target_user).order_by('-created_at')[:40]
    api_key = None
    api_logs = []
    try:
        api_key = target_user.api_key
        api_logs = APIKeyLog.objects.filter(api_key=api_key).order_by('-timestamp')[:50]
    except APIKey.DoesNotExist:
        pass

    context = {
        'target_user': target_user,
        'voice_requests': voice_requests,
        'api_key': api_key,
        'api_logs': api_logs,
    }
    return render(request, 'admin/user_detail.html', context)


@staff_member_required
def admin_settings(request):
    settings_obj = SystemSettings.get_settings()

    if request.method == 'POST':
        form_type = request.POST.get('form_type', '')
        apply_to_all = request.POST.get('apply_to_all') == 'on'

        if form_type == 'rate_limits':
            try:
                settings_obj.default_daily_limit = int(
                    request.POST.get('default_daily_limit', settings_obj.default_daily_limit) or 10000
                )
                settings_obj.default_monthly_limit = int(
                    request.POST.get('default_monthly_limit', settings_obj.default_monthly_limit) or 300000
                )
                settings_obj.default_daily_voice_limit = max(
                    0,
                    int(
                        request.POST.get(
                            'default_daily_voice_limit',
                            settings_obj.default_daily_voice_limit,
                        )
                        or 3
                    ),
                )
            except (TypeError, ValueError):
                pass
            settings_obj.save()
            if apply_to_all:
                User.objects.update(
                    daily_request_limit=settings_obj.default_daily_limit,
                    monthly_request_limit=settings_obj.default_monthly_limit,
                    daily_voice_limit=settings_obj.default_daily_voice_limit,
                )
            messages.success(
                request,
                'Rate limits saved.' + (' Applied to all users.' if apply_to_all else ''),
            )

        elif form_type == 'api_settings':
            try:
                settings_obj.key_expiry_days = int(
                    request.POST.get('key_expiry_days', settings_obj.key_expiry_days) or 365
                )
            except (TypeError, ValueError):
                pass
            settings_obj.require_approval_new_keys = (
                request.POST.get('require_approval_new_keys') == 'on'
            )
            settings_obj.save()
            messages.success(request, 'API settings saved.')

        elif form_type == 'voice_settings':
            try:
                settings_obj.max_audio_duration_seconds = float(
                    request.POST.get(
                        'max_audio_duration_seconds',
                        settings_obj.max_audio_duration_seconds,
                    )
                    or 20
                )
                settings_obj.max_audio_size_mb = float(
                    request.POST.get('max_audio_size_mb', settings_obj.max_audio_size_mb) or 10
                )
            except (TypeError, ValueError):
                pass
            settings_obj.allowed_audio_formats = (
                request.POST.get('allowed_audio_formats', settings_obj.allowed_audio_formats)
                or 'wav,mp3,mpeg,webm'
            ).strip()
            settings_obj.save()
            messages.success(request, 'Voice / audio settings saved.')

        elif form_type == 'anti_abuse':
            ab = AntiAbuseSettings.get_settings()
            ab.master_enable = request.POST.get('ab_master_enable') == 'on'
            ab.enforce_admin_block = request.POST.get('ab_enforce_admin_block') == 'on'
            ab.block_disposable_email = request.POST.get('ab_block_disposable_email') == 'on'
            ab.require_gmail_domain_for_password_signup = (
                request.POST.get('ab_require_gmail_domain') == 'on'
            )
            ab.oauth_signup_antiabuse_enabled = (
                request.POST.get('ab_oauth_signup_antiabuse') == 'on'
            )
            ab.block_same_ip_registration = request.POST.get('ab_block_same_ip') == 'on'
            ab.same_ip_lookback_hours = _safe_uint(
                request.POST.get('ab_same_ip_lookback_hours'), ab.same_ip_lookback_hours, 1
            )
            ab.max_accounts_per_ip_in_lookback = _safe_uint_min0(
                request.POST.get('ab_max_accounts_per_ip'),
                ab.max_accounts_per_ip_in_lookback,
            )
            ab.block_same_fingerprint = request.POST.get('ab_block_same_fingerprint') == 'on'
            ab.fingerprint_lookback_hours = _safe_uint(
                request.POST.get('ab_fingerprint_lookback_hours'),
                ab.fingerprint_lookback_hours,
                1,
            )
            ab.block_rapid_registration_window = (
                request.POST.get('ab_block_rapid_window') == 'on'
            )
            ab.rapid_registration_window_minutes = _safe_uint(
                request.POST.get('ab_rapid_window_minutes'),
                ab.rapid_registration_window_minutes,
                1,
            )
            ab.max_registrations_per_ip_in_rapid_window = _safe_uint(
                request.POST.get('ab_max_reg_ip_rapid'),
                ab.max_registrations_per_ip_in_rapid_window,
                1,
            )
            ab.max_registrations_per_fingerprint_in_rapid_window = _safe_uint(
                request.POST.get('ab_max_reg_fp_rapid'),
                ab.max_registrations_per_fingerprint_in_rapid_window,
                1,
            )
            ab.device_tracker_cookie_enabled = (
                request.POST.get('ab_device_cookie') == 'on'
            )
            ab.device_tracker_cookie_max_age_days = _safe_uint(
                request.POST.get('ab_device_cookie_days'),
                ab.device_tracker_cookie_max_age_days,
                1,
            )
            ab.auto_block_ip_on_burst = request.POST.get('ab_auto_block_burst') == 'on'
            ab.suspicious_burst_registration_count = _safe_uint(
                request.POST.get('ab_burst_count'),
                ab.suspicious_burst_registration_count,
                2,
            )
            ab.suspicious_burst_window_minutes = _safe_uint(
                request.POST.get('ab_burst_window_minutes'),
                ab.suspicious_burst_window_minutes,
                1,
            )
            ab.auto_blocked_ip_duration_days = _safe_uint(
                request.POST.get('ab_auto_block_days'),
                ab.auto_blocked_ip_duration_days,
                1,
            )
            ab.save()
            messages.success(request, 'Anti-abuse / registration settings saved.')

        elif form_type == 'security':
            try:
                settings_obj.session_timeout_minutes = int(
                    request.POST.get('session_timeout', settings_obj.session_timeout_minutes) or 30
                )
            except (TypeError, ValueError):
                pass
            settings_obj.force_2fa_admin = request.POST.get('force_2fa') == 'on'
            settings_obj.ip_whitelist_enabled = request.POST.get('ip_whitelist') == 'on'
            settings_obj.save()
            messages.success(request, 'Security settings saved.')

        return redirect('admin:settings')

    today = timezone.now().date()
    total_api_calls = APIKeyLog.objects.count()
    unique_users = APIKeyLog.objects.values('api_key__user').distinct().count()
    avg_response = APIKeyLog.objects.aggregate(Avg('response_time'))['response_time__avg'] or 0

    context = {
        'settings': settings_obj,
        'antiabuse': AntiAbuseSettings.get_settings(),
        'total_api_calls': total_api_calls,
        'unique_users': unique_users,
        'avg_response': avg_response,
    }
    return render(request, 'admin/settings.html', context)


@staff_member_required
def security_monitor(request):
    """Staff dashboard: registration / abuse telemetry (passwords are never stored)."""
    try:
        days = int(request.GET.get('days') or '7')
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    since = timezone.now() - timedelta(days=days)

    outcome_filter = (request.GET.get('outcome') or '').strip()
    ip_q = (request.GET.get('ip') or '').strip()[:45]
    device_q = (request.GET.get('device') or '').strip()

    # Mid-flow password signup (OTP emailed) is not an abuse signal until verified / logged in.
    base = RegistrationAttempt.for_abuse_monitor().filter(created_at__gte=since)
    qs = base.select_related('user').order_by('-created_at')
    _outcomes_abuse = {
        c.value
        for c in RegistrationAttempt.Outcome
        if c.value != RegistrationAttempt.Outcome.PENDING_VERIFICATION
    }
    if outcome_filter == RegistrationAttempt.Outcome.PENDING_VERIFICATION:
        outcome_filter = ''
    if outcome_filter in _outcomes_abuse:
        qs = qs.filter(outcome=outcome_filter)
    if ip_q:
        qs = qs.filter(ip_address__icontains=ip_q)
    if device_q:
        qs = qs.filter(device_class=device_q)

    stats = base.aggregate(
        total=Count('id'),
        blocked=Count('id', filter=Q(outcome=RegistrationAttempt.Outcome.BLOCKED)),
        success=Count('id', filter=Q(outcome=RegistrationAttempt.Outcome.SUCCESS)),
        failed_val=Count(
            'id', filter=Q(outcome=RegistrationAttempt.Outcome.FAILED_VALIDATION)
        ),
    )
    unique_ips = base.values('ip_address').distinct().count()

    top_ips = list(
        base.values('ip_address')
        .annotate(n=Count('id'))
        .order_by('-n')[:30]
    )
    top_prints = list(
        base.exclude(fingerprint_hash='')
        .values('fingerprint_hash')
        .annotate(n=Count('id'))
        .order_by('-n')[:20]
    )

    now = timezone.now()
    blocked_ips = list(
        BlockedIPAddress.objects.filter(is_active=True)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by('-created_at')[:40]
    )

    paginator = Paginator(qs, 35)
    page = paginator.get_page(request.GET.get('page') or 1)

    return render(
        request,
        'admin/security_monitor.html',
        {
            'page_obj': page,
            'stats': stats,
            'unique_ips': unique_ips,
            'days': days,
            'top_ips': top_ips,
            'top_prints': top_prints,
            'blocked_ips': blocked_ips,
            'outcome_filter': outcome_filter,
            'ip_q': ip_q,
            'device_q': device_q,
            'outcome_choices': [
                c
                for c in RegistrationAttempt.Outcome.choices
                if c[0] != RegistrationAttempt.Outcome.PENDING_VERIFICATION
            ],
        },
    )


TERMINAL_BLOCKED = re.compile(
    r'(\brm\s+-[rf]+\s+/|\b:\(\)\s*\{|>\s*/dev/sd|mkfs\.|dd\s+if=|\bchmod\s+[0-7]+\s+/|/etc/shadow|/etc/passwd\s*$)',
    re.IGNORECASE,
)
TERMINAL_TIMEOUT = 30


@staff_member_required
def terminal_view(request):
    processing = VoiceProcessingRequest.objects.filter(
        status=VoiceProcessingRequest.Status.PROCESSING
    ).count()
    return render(request, 'admin/terminal.html', {'pending_count': processing})


@staff_member_required
@require_http_methods(['POST'])
def terminal_run_command(request):
    cmd = (request.POST.get('command') or request.body.decode('utf-8', errors='ignore')).strip()
    if not cmd:
        return JsonResponse({'ok': False, 'stdout': '', 'stderr': 'No command provided.', 'returncode': -1})
    if TERMINAL_BLOCKED.search(cmd):
        return JsonResponse({'ok': False, 'stdout': '', 'stderr': 'Command not allowed for security.', 'returncode': -1})
    try:
        result = subprocess.run(
            ['sh', '-c', cmd],
            capture_output=True,
            text=True,
            timeout=TERMINAL_TIMEOUT,
            cwd='/app',
        )
        return JsonResponse({
            'ok': result.returncode == 0,
            'stdout': result.stdout or '',
            'stderr': result.stderr or '',
            'returncode': result.returncode,
        })
    except subprocess.TimeoutExpired:
        return JsonResponse({
            'ok': False,
            'stdout': '',
            'stderr': f'Command timed out after {TERMINAL_TIMEOUT}s.',
            'returncode': -1,
        })
    except Exception as e:
        return JsonResponse({
            'ok': False,
            'stdout': '',
            'stderr': str(e),
            'returncode': -1,
        })
