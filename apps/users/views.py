import json
import math
import uuid

from django.core.files.base import ContentFile

from apps.core.voice_temp_storage import get_voice_temp_storage
from django.http import HttpResponseNotAllowed, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.conf import settings
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash

# Django 6+: login(..., backend=...) must be a dotted path string, not a class.
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import models
from django.db.models.functions import TruncDate
from django.db.models import Count

from apps.authentication.email_verification import (
    codes_match,
    issue_new_code,
    send_verification_email,
)
from .forms import (
    ChangePasswordForm,
    CustomAuthenticationForm,
    CustomUserCreationForm,
    PendingSignupChangeEmailForm,
    PendingSignupChangeUsernameForm,
    UserProfileForm,
    VerifyEmailForm,
    registration_invalid_toast_message,
)
from apps.users.pending_cleanup import (
    SESSION_PENDING_VERIFY,
    purge_expired_unverified_users,
)
from apps.authentication.device_info import classify_request
from apps.authentication.antiabuse import (
    attach_device_cookie,
    check_registration_allowed,
    get_client_ip,
    hash_fingerprint,
    log_registration_attempt,
    maybe_auto_block_ip_after_burst,
    persist_device_id_on_user,
    user_visible_registration_block_message,
)
from apps.authentication.models import APIKey, APIKeyLog, AntiAbuseSettings, RegistrationAttempt
from apps.core.models import SystemSettings
from apps.core.services.audio_utils import extension_from_filename, validate_audio_upload
from apps.voice.models import VoiceProcessingRequest
from apps.voice.tasks import run_voice_pipeline_task
from datetime import timedelta


def _get_pending_verification_user(request):
    uid = request.session.get(SESSION_PENDING_VERIFY)
    if not uid:
        return None
    User = get_user_model()
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        request.session.pop(SESSION_PENDING_VERIFY, None)
        return None
    if user.is_active and user.is_verified:
        request.session.pop(SESSION_PENDING_VERIFY, None)
        return None
    return user



def _verify_flow_timing(user):
    """Cooldowns and caps for resend / change-email on the verify page."""
    gap = int(getattr(settings, 'EMAIL_VERIFICATION_RESEND_SECONDS', 60))
    send_max = int(getattr(settings, 'EMAIL_VERIFICATION_SEND_MAX', 5))
    cd_email = int(getattr(settings, 'PENDING_SIGNUP_EMAIL_CHANGE_COOLDOWN_SECONDS', 120))
    now = timezone.now()
    resend_in = 0
    sent_at = user.email_verification_sent_at
    elapsed_since_send = None
    if sent_at:
        elapsed_since_send = (now - sent_at).total_seconds()
        if elapsed_since_send < gap:
            resend_in = max(0, int(math.ceil(gap - elapsed_since_send)))
    sends_done = int(user.email_verification_send_count or 0)
    gap_ok = sent_at is None or (
        elapsed_since_send is not None and elapsed_since_send >= gap
    )
    can_resend = sends_done < send_max and gap_ok
    email_change_in = 0
    changed_at = user.pending_signup_email_changed_at
    if changed_at:
        el = (now - changed_at).total_seconds()
        if el < cd_email:
            email_change_in = max(0, int(math.ceil(cd_email - el)))
    return {
        'resend_cooldown_seconds': resend_in,
        'can_resend_code': can_resend,
        'verification_sends_done': sends_done,
        'verification_sends_remaining': max(0, send_max - sends_done),
        'email_change_cooldown_seconds': email_change_in,
        'can_change_email_now': email_change_in == 0,
    }


def landing_page_view(request):
    """Public landing page at / ."""
    return render(request, 'landing.html')


@require_http_methods(['POST'])
def oauth_google_start(request):
    """
    Store client fingerprint in session before redirecting to Google.
    Used so new Google sign-ups go through the same anti-abuse checks as password registration.
    """
    fp = (request.POST.get('client_fingerprint') or '')[:2000]
    request.session['vts_oauth_client_fingerprint'] = fp
    return redirect('social:begin', backend='google-oauth2')


def _google_oauth_configured():
    return bool(
        getattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID', '')
        and getattr(settings, 'GOOGLE_OAUTH2_CLIENT_SECRET', '')
    )


def register_view(request):
    """User registration"""
    if request.user.is_authenticated:
        return redirect('admin:dashboard' if request.user.is_staff else 'user:dashboard')

    purge_expired_unverified_users(request)

    google_on = _google_oauth_configured()
    ctx = {'form': CustomUserCreationForm(), 'google_oauth_enabled': google_on}

    if request.method == 'POST':
        fp_raw = request.POST.get('client_fingerprint', '')
        posted_email = (request.POST.get('email') or '').strip()
        posted_username = (request.POST.get('username') or '').strip()[:150]
        ip = get_client_ip(request)
        fph = hash_fingerprint(fp_raw)
        ci = classify_request(request)

        block_msg, _burst = check_registration_allowed(
            request,
            email=posted_email,
            client_fingerprint=fp_raw,
        )
        if block_msg:
            log_registration_attempt(
                ip=ip,
                fingerprint_hash=fph,
                email=posted_email,
                email_input=posted_email,
                username=posted_username,
                raw_fingerprint=fp_raw,
                user_agent=ci['user_agent'],
                device_class=ci['device_class'],
                browser_family=ci['browser_family'],
                os_family=ci['os_family'],
                outcome=RegistrationAttempt.Outcome.BLOCKED,
                detail=block_msg[:500],
            )
            maybe_auto_block_ip_after_burst(ip)
            messages.error(request, user_visible_registration_block_message(block_msg))
            ctx['form'] = CustomUserCreationForm(request.POST)
            return render(request, 'auth/register.html', ctx)

        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.registration_ip = ip
            user.registration_fingerprint_hash = fph
            user.is_active = False
            user.is_verified = False
            user.email_verification_send_count = 0
            user.signup_username_edit_used = False
            user.pending_signup_email_changed_at = None
            user.save()
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
            persist_device_id_on_user(user, request)
            code = issue_new_code(user)
            try:
                send_verification_email(user=user, code=code)
                user.email_verification_send_count = 1
                user.save(update_fields=['email_verification_send_count'])
            except Exception:
                messages.error(
                    request,
                    'Your account was created but we could not send the verification email. '
                    'Check EMAIL_* settings, then use “Resend code” on the next page.',
                )
            log_registration_attempt(
                ip=ip,
                fingerprint_hash=fph,
                email=user.email,
                email_input=user.email,
                username=user.username,
                outcome=RegistrationAttempt.Outcome.PENDING_VERIFICATION,
                detail='password_signup_otp_sent',
                user=user,
            )
            request.session[SESSION_PENDING_VERIFY] = str(user.pk)
            messages.success(
                request,
                'Check your email for a 6-digit code, then enter it below with your name.',
            )
            response = redirect('auth:verify-email')
            attach_device_cookie(response, user)
            return response
        messages.error(request, registration_invalid_toast_message(form))
        log_registration_attempt(
            ip=ip,
            fingerprint_hash=fph,
            email=posted_email,
            email_input=posted_email,
            username=posted_username,
            raw_fingerprint=fp_raw,
            user_agent=ci['user_agent'],
            device_class=ci['device_class'],
            browser_family=ci['browser_family'],
            os_family=ci['os_family'],
            outcome=RegistrationAttempt.Outcome.FAILED_VALIDATION,
            detail=str(form.errors)[:500],
        )
        ctx['form'] = form
    return render(request, 'auth/register.html', ctx)


def verify_email_view(request):
    """Finish password registration: OTP + first/last name."""
    purge_expired_unverified_users(request)
    user = _get_pending_verification_user(request)
    if not user:
        messages.error(
            request,
            'Verification session expired or is not needed. Register or sign in.',
        )
        return redirect('auth:register')

    google_on = _google_oauth_configured()
    if request.method == 'POST':
        form = VerifyEmailForm(request.POST)
        if form.is_valid():
            exp = user.email_verification_expires_at
            if not exp or exp < timezone.now():
                messages.error(request, 'This code has expired. Request a new code.')
            elif not codes_match(user, form.cleaned_data['code']):
                messages.error(request, 'Invalid verification code.')
            else:
                fp_raw = (request.POST.get('client_fingerprint') or '')[:2000]
                fph = hash_fingerprint(fp_raw)
                ip = get_client_ip(request)
                ci = classify_request(request)
                user.first_name = form.cleaned_data['first_name'].strip()
                user.last_name = form.cleaned_data['last_name'].strip()
                user.is_active = True
                user.is_verified = True
                user.email_verified_at = timezone.now()
                user.email_verification_code_hash = ''
                user.email_verification_sent_at = None
                user.email_verification_expires_at = None
                if fph and not (user.registration_fingerprint_hash or '').strip():
                    user.registration_fingerprint_hash = fph
                user.email_verification_send_count = 0
                user.pending_signup_email_changed_at = None
                user.save()
                log_registration_attempt(
                    ip=ip,
                    fingerprint_hash=fph,
                    email=user.email,
                    email_input=user.email,
                    username=user.username,
                    raw_fingerprint=fp_raw,
                    user_agent=ci['user_agent'],
                    device_class=ci['device_class'],
                    browser_family=ci['browser_family'],
                    os_family=ci['os_family'],
                    outcome=RegistrationAttempt.Outcome.SUCCESS,
                    detail='password_signup_verified',
                    user=user,
                )
                request.session.pop(SESSION_PENDING_VERIFY, None)
                login(request, user, backend=MODEL_BACKEND)
                messages.success(request, 'Email verified. Welcome to Voice To Service.')
                response = redirect('user:dashboard')
                attach_device_cookie(response, user)
                return response
    else:
        form = VerifyEmailForm()

    timing = _verify_flow_timing(user)
    send_max = int(getattr(settings, 'EMAIL_VERIFICATION_SEND_MAX', 5))
    resend_gap = int(getattr(settings, 'EMAIL_VERIFICATION_RESEND_SECONDS', 60))
    ctx = {
        'form': form,
        'verify_email': user.email,
        'google_oauth_enabled': google_on,
        'verify_timing': timing,
        'verification_send_max': send_max,
        'resend_gap_seconds': resend_gap,
        'change_email_form': PendingSignupChangeEmailForm(current_user=user),
        'change_username_form': PendingSignupChangeUsernameForm(current_user=user),
        'can_change_username': not user.signup_username_edit_used,
    }
    return render(request, 'auth/verify_email.html', ctx)


@require_http_methods(['POST'])
def resend_verification_email_view(request):
    purge_expired_unverified_users(request)
    user = _get_pending_verification_user(request)
    if not user:
        messages.error(request, 'No pending verification. Register again.')
        return redirect('auth:register')
    send_max = int(getattr(settings, 'EMAIL_VERIFICATION_SEND_MAX', 5))
    timing = _verify_flow_timing(user)
    if user.email_verification_send_count >= send_max:
        messages.error(
            request,
            f'You have used all {send_max} verification emails for this sign-up. '
            'Change your email below if the address was wrong, or start over from registration.',
        )
        return redirect('auth:verify-email')
    if not timing['can_resend_code']:
        messages.warning(
            request,
            f'Please wait {timing["resend_cooldown_seconds"]} seconds before requesting another code.',
        )
        return redirect('auth:verify-email')
    code = issue_new_code(user)
    try:
        send_verification_email(user=user, code=code)
        user.email_verification_send_count += 1
        user.save(update_fields=['email_verification_send_count'])
        messages.success(request, 'A new verification code was sent to your email.')
    except Exception:
        messages.error(
            request,
            'Could not send email. Confirm EMAIL_HOST / EMAIL_HOST_USER / password in your environment.',
        )
    return redirect('auth:verify-email')


@require_http_methods(['POST'])
def verify_change_email_view(request):
    purge_expired_unverified_users(request)
    user = _get_pending_verification_user(request)
    if not user:
        messages.error(request, 'No pending verification. Register again.')
        return redirect('auth:register')
    timing = _verify_flow_timing(user)
    if not timing['can_change_email_now']:
        messages.warning(
            request,
            'You can change your email again in '
            f'{timing["email_change_cooldown_seconds"]} seconds.',
        )
        return redirect('auth:verify-email')

    form = PendingSignupChangeEmailForm(request.POST, current_user=user)
    if not form.is_valid():
        err = '; '.join(str(e) for e in form.errors.get('email', [])) or 'Check the email address.'
        messages.error(request, err)
        return redirect('auth:verify-email')

    new_email = form.cleaned_data['email'].strip()
    fp_raw = (request.POST.get('client_fingerprint') or '')[:2000]
    block_msg, _burst = check_registration_allowed(
        request,
        email=new_email,
        client_fingerprint=fp_raw,
        apply_velocity_and_device_checks=False,
    )
    if block_msg:
        messages.error(request, user_visible_registration_block_message(block_msg))
        return redirect('auth:verify-email')

    user.email = new_email
    user.pending_signup_email_changed_at = timezone.now()
    user.email_verification_send_count = 0
    user.save(
        update_fields=['email', 'pending_signup_email_changed_at', 'email_verification_send_count']
    )
    code = issue_new_code(user)
    try:
        send_verification_email(user=user, code=code)
        user.email_verification_send_count = 1
        user.save(update_fields=['email_verification_send_count'])
        messages.success(request, 'Email updated. We sent a new verification code.')
    except Exception:
        messages.error(
            request,
            'Email saved but we could not send mail. Check EMAIL_* settings and use Resend.',
        )
    return redirect('auth:verify-email')


@require_http_methods(['POST'])
def verify_change_username_view(request):
    purge_expired_unverified_users(request)
    user = _get_pending_verification_user(request)
    if not user:
        messages.error(request, 'No pending verification. Register again.')
        return redirect('auth:register')
    if user.signup_username_edit_used:
        messages.error(request, 'You can only change your username once on this page.')
        return redirect('auth:verify-email')

    form = PendingSignupChangeUsernameForm(request.POST, current_user=user)
    if not form.is_valid():
        err = '; '.join(str(e) for e in form.errors.get('username', [])) or 'Check the username.'
        messages.error(request, err)
        return redirect('auth:verify-email')

    user.username = form.cleaned_data['username']
    user.signup_username_edit_used = True
    user.save(update_fields=['username', 'signup_username_edit_used'])
    messages.success(request, 'Username updated. Use it to sign in after you verify.')
    return redirect('auth:verify-email')


def login_view(request):
    """User login"""
    if request.user.is_authenticated:
        return redirect('admin:dashboard' if request.user.is_staff else 'user:dashboard')
    google_on = _google_oauth_configured()
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                cfg = AntiAbuseSettings.get_settings()
                if cfg.enforce_admin_block and getattr(user, 'is_blocked', False):
                    messages.error(
                        request,
                        (getattr(user, 'blocked_reason', None) or 'Your account has been suspended.')[
                            :2000
                        ],
                    )
                    return render(
                        request,
                        'auth/login.html',
                        {'form': CustomAuthenticationForm(), 'google_oauth_enabled': google_on},
                    )
                login(request, user, backend=MODEL_BACKEND)
                messages.success(request, f'Welcome back, {username}!')

                if user.is_staff:
                    return redirect('admin:dashboard')
                return redirect('user:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = CustomAuthenticationForm()

    return render(
        request,
        'auth/login.html',
        {'form': form, 'google_oauth_enabled': google_on},
    )

@login_required
def logout_view(request):
    """User logout"""
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('auth:login')

@login_required
def dashboard_view(request):
    """User dashboard"""
    try:
        api_key = request.user.api_key
    except APIKey.DoesNotExist:
        api_key = None
    
    # Get recent API usage
    recent_logs = []
    if api_key:
        recent_logs = APIKeyLog.objects.filter(
            api_key=api_key
        ).order_by('-timestamp')[:10]
    
    # Calculate usage stats
    today = timezone.now().date()
    month_start = timezone.now().replace(day=1)
    
    total_calls = APIKeyLog.objects.filter(api_key=api_key).count() if api_key else 0
    today_calls = APIKeyLog.objects.filter(
        api_key=api_key,
        timestamp__date=today
    ).count() if api_key else 0
    
    month_calls = APIKeyLog.objects.filter(
        api_key=api_key,
        timestamp__gte=month_start
    ).count() if api_key else 0
    
    stats = {
        'total_calls': total_calls,
        'calls_today': today_calls,
        'calls_this_month': month_calls,
        'daily_limit': request.user.daily_request_limit,
        'monthly_limit': request.user.monthly_request_limit,
        'last_used': api_key.last_used_at if api_key else None,
        'expires_in': (api_key.expires_at - timezone.now()).days if api_key and api_key.expires_at else None,
    }
    
    new_api_key = request.session.pop('new_api_key', None)
    voice_today = request.user.voice_requests_today_count()
    voice_limit = request.user.daily_voice_limit
    context = {
        'api_key': api_key,
        'recent_logs': recent_logs,
        'stats': stats,
        'new_api_key': new_api_key,
        'voice_today': voice_today,
        'voice_limit': voice_limit,
    }
    return render(request, 'user/dashboard.html', context)

@login_required
def profile_view(request):
    """User profile settings"""
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('user:profile')
    else:
        form = UserProfileForm(instance=request.user)
    
    active_section = request.GET.get('section', 'account')
    return render(request, 'user/profile.html', {'form': form, 'active_section': active_section})

@login_required
def change_password(request):
    """Change password: GET redirects to profile#password; POST processes then redirects."""
    if request.method != 'POST':
        return redirect(reverse('user:profile') + '?section=password')
    form = ChangePasswordForm(request.POST)
    if form.is_valid():
        user = request.user
        if user.check_password(form.cleaned_data['current_password']):
            user.set_password(form.cleaned_data['new_password'])
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully.')
        else:
            messages.error(request, 'Current password is incorrect.')
    else:
        messages.error(request, 'Please fix the errors below.')
    return redirect(reverse('user:profile') + '?section=password')

@login_required
def usage_view(request):
    """API usage statistics with chart data"""
    try:
        api_key = request.user.api_key
    except APIKey.DoesNotExist:
        messages.warning(request, 'Generate an API key first')
        return redirect('user:dashboard')

    # Use api_key_id so we always match the key for this user (logs from API + test page)
    logs = APIKeyLog.objects.filter(api_key_id=api_key.id).order_by('-timestamp')
    total_calls = logs.count()
    success_calls = logs.filter(status_code__in=[200, 201]).count()
    failed_calls = total_calls - success_calls
    avg_response = 0
    if total_calls > 0:
        avg_response = logs.aggregate(models.Avg('response_time'))['response_time__avg'] or 0

    # Chart: last 14 days daily request counts (group by day)
    start_date = timezone.now().date() - timedelta(days=14)
    daily_qs = (
        logs.filter(timestamp__date__gte=start_date)
        .annotate(day=TruncDate('timestamp'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    day_counts = {}
    for row in daily_qs:
        day_val = row['day']
        key = day_val.isoformat() if hasattr(day_val, 'isoformat') else str(day_val)
        day_counts[key] = int(row['count'])
    chart_labels = []
    chart_values = []
    for i in range(14):
        d = start_date + timedelta(days=i)
        chart_labels.append(d.strftime('%b %d'))
        chart_values.append(day_counts.get(d.isoformat(), 0))

    today = timezone.now().date()
    month_start = timezone.now().replace(day=1)
    calls_today = logs.filter(timestamp__date=today).count()
    calls_this_month = logs.filter(timestamp__gte=month_start).count()

    context = {
        'logs': list(logs[:100]),
        'total_calls': total_calls,
        'success_calls': success_calls,
        'failed_calls': failed_calls,
        'avg_response': round(avg_response, 2),
        'chart_labels': chart_labels,
        'chart_values': chart_values,
        'chart_labels_json': json.dumps(chart_labels),
        'chart_values_json': json.dumps(chart_values),
        'daily_limit': request.user.daily_request_limit,
        'monthly_limit': request.user.monthly_request_limit,
        'calls_today': calls_today,
        'calls_this_month': calls_this_month,
        'voice_today': request.user.voice_requests_today_count(),
        'voice_limit': request.user.daily_voice_limit,
    }
    return render(request, 'user/usage.html', context)

@login_required
def generate_api_key(request):
    """Generate new API key - show full key once in dashboard modal"""
    APIKey.objects.filter(user=request.user).delete()
    settings_obj = SystemSettings.get_settings()
    expires_at = timezone.now() + timedelta(days=settings_obj.key_expiry_days)
    api_key = APIKey.objects.create(
        user=request.user,
        name=f"API Key for {request.user.email}",
        expires_at=expires_at,
    )
    request.session['new_api_key'] = api_key.key
    messages.success(request, 'API key created. Copy it below — you won’t see it again.')
    return redirect('user:dashboard')

@login_required
def revoke_api_key(request):
    """Revoke current API key"""
    if request.method == 'POST':
        APIKey.objects.filter(user=request.user).delete()
        messages.success(request, 'API key revoked successfully')
    return redirect('user:dashboard')


@login_required
def test_voice_view(request):
    """Upload audio and run the same pipeline as POST /api/v1/process-audio (uses your API key server-side)."""
    try:
        api_key = request.user.api_key
    except APIKey.DoesNotExist:
        api_key = None
    if not api_key:
        messages.warning(request, 'Generate an API key first to use the test console.')
        return redirect('user:dashboard')

    result = None
    if request.method == 'POST':
        try:
            from apps.api.views.voice_views import process_voice_request

            audio = request.FILES.get('audio') or request.FILES.get('file')
            resp = process_voice_request(
                request, request.user, api_key, '/user/test/', audio=audio
            )
            data = getattr(resp, 'data', None) or {}
            sc = getattr(resp, 'status_code', 500)
            if sc == 200:
                result = data
                messages.success(request, 'Audio processed successfully.')
            else:
                err = data.get('error') or data.get('detail') or str(data)
                messages.error(request, err)
                # Keep full API payload so the test page can show pipeline_log + details
                result = {**data, 'error': data.get('error') or err, 'code': data.get('code')}
        except Exception as e:
            messages.error(request, f'Processing failed: {e}')
            result = {'error': str(e)}

    settings_obj = SystemSettings.get_settings()
    max_srv = float(settings_obj.max_audio_duration_seconds)
    zero_uuid = uuid.UUID(int=0)
    context = {
        'api_key': api_key,
        'test_result': result,
        'max_audio_seconds': settings_obj.max_audio_duration_seconds,
        'max_audio_mb': settings_obj.max_audio_size_mb,
        'max_record_seconds': min(420.0, max_srv),
        'voice_today': request.user.voice_requests_today_count(),
        'voice_limit': request.user.daily_voice_limit,
        'test_job_start_url': reverse('user:test_job_start'),
        'test_job_status_url_template': reverse(
            'user:test_job_status', kwargs={'job_id': zero_uuid}
        ),
        'test_job_status_placeholder': str(zero_uuid),
    }
    return render(request, 'user/test.html', context)


@login_required
@require_POST
def test_voice_job_start(request):
    """Accept audio, store temporarily, enqueue Celery pipeline; returns JSON for polling."""
    try:
        api_key = request.user.api_key
    except APIKey.DoesNotExist:
        return JsonResponse(
            {'error': 'Generate an API key first to use the test console.', 'code': 'no_api_key'},
            status=403,
        )

    ok, msg = request.user.check_voice_daily_limit()
    if not ok:
        return JsonResponse({'error': msg, 'code': 'voice_daily_limit_exceeded'}, status=429)

    audio = request.FILES.get('audio') or request.FILES.get('file')
    if not audio:
        return JsonResponse(
            {'error': 'Missing audio file. Use field "audio" or "file".', 'code': 'missing_audio'},
            status=400,
        )

    settings_obj = SystemSettings.get_settings()
    allowed = settings_obj.allowed_audio_formats_list()
    if not allowed:
        allowed = ['wav', 'mp3', 'mpeg', 'webm']

    fname = getattr(audio, 'name', '') or 'upload'
    ok_val, err, duration = validate_audio_upload(
        audio,
        max_size_mb=float(settings_obj.max_audio_size_mb),
        max_duration_seconds=float(settings_obj.max_audio_duration_seconds),
        allowed_extensions=allowed,
    )
    if not ok_val:
        return JsonResponse({'error': err, 'code': 'invalid_audio'}, status=400)

    try:
        audio.seek(0)
        raw_bytes = audio.read()
    except Exception as e:
        return JsonResponse({'error': str(e), 'code': 'read_error'}, status=400)

    ext = extension_from_filename(fname) or 'bin'
    vreq = VoiceProcessingRequest.objects.create(
        user=request.user,
        status=VoiceProcessingRequest.Status.PROCESSING,
        audio_duration_seconds=duration,
        pipeline_metadata={'filename': fname[:255]},
    )
    temp_name = f'{vreq.id}.{ext}'
    storage = get_voice_temp_storage()
    try:
        storage.save(temp_name, ContentFile(raw_bytes))
    except Exception as e:
        vreq.delete()
        return JsonResponse(
            {'error': f'Could not store upload: {e}', 'code': 'storage_error'},
            status=500,
        )

    md = dict(vreq.pipeline_metadata or {})
    md['temp_audio_path'] = temp_name
    vreq.pipeline_metadata = md
    try:
        vreq.save(update_fields=['pipeline_metadata'])
    except Exception as e:
        try:
            storage.delete(temp_name)
        except Exception:
            pass
        vreq.delete()
        return JsonResponse(
            {'error': f'Could not save job metadata: {e}', 'code': 'db_error'},
            status=500,
        )

    try:
        run_voice_pipeline_task.delay(str(vreq.id))
    except Exception as e:
        try:
            storage.delete(temp_name)
        except Exception:
            pass
        vreq.status = VoiceProcessingRequest.Status.FAILED
        vreq.error_message = f'Task enqueue failed: {e}'[:2000]
        vreq.pipeline_metadata = {k: v for k, v in md.items() if k != 'temp_audio_path'}
        vreq.save(update_fields=['status', 'error_message', 'pipeline_metadata'])
        return JsonResponse(
            {'error': 'Could not queue background job. Is the broker/worker running?', 'code': 'enqueue_error'},
            status=503,
        )
    return JsonResponse(
        {
            'request_id': str(vreq.id),
            'status': vreq.status,
            'message': 'Job queued. Poll status for pipeline progress and results.',
        },
        status=202,
    )


@login_required
@require_GET
def test_voice_job_status(request, job_id):
    """JSON status for a voice job owned by the current user (refresh-safe)."""
    try:
        vreq = VoiceProcessingRequest.objects.get(pk=job_id, user=request.user)
    except VoiceProcessingRequest.DoesNotExist:
        return JsonResponse({'error': 'Job not found.', 'code': 'not_found'}, status=404)

    md = dict(vreq.pipeline_metadata or {})
    pl = md.get('pipeline_log')
    if not isinstance(pl, list):
        pl = []

    body = {
        'request_id': str(vreq.id),
        'status': vreq.status,
        'pipeline_log': pl,
        'error_message': (vreq.error_message or '').strip(),
    }
    if vreq.status == VoiceProcessingRequest.Status.COMPLETED:
        body.update(
            {
                'amharic_text': vreq.amharic_text,
                'english_text': vreq.english_text,
                'category': vreq.category,
                'confidence': round(vreq.confidence, 4) if vreq.confidence is not None else None,
                'raw_classification': vreq.raw_classification,
            }
        )
    elif vreq.status == VoiceProcessingRequest.Status.FAILED and vreq.error_message:
        body['error'] = vreq.error_message

    return JsonResponse(body)


@login_required
def test_voice_stream_view(request):
    """
    Same pipeline as test_voice_view but streams NDJSON lines:
    {"type":"log","entry":{...}} and final {"type":"final","status":200,"payload":{...}}.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    try:
        api_key = request.user.api_key
    except APIKey.DoesNotExist:
        api_key = None

    def ndjson_line(obj):
        return json.dumps(obj, ensure_ascii=False, default=str) + '\n'

    if not api_key:

        def denied():
            yield ndjson_line(
                {
                    'type': 'final',
                    'status': 403,
                    'payload': {
                        'error': 'Generate an API key first to use the test console.',
                        'code': 'no_api_key',
                    },
                }
            )

        resp = StreamingHttpResponse(denied(), content_type='application/x-ndjson; charset=utf-8')
        resp['Cache-Control'] = 'no-cache, no-store'
        resp['X-Accel-Buffering'] = 'no'
        return resp

    audio = request.FILES.get('audio') or request.FILES.get('file')

    def event_stream():
        from apps.api.views.voice_views import iter_voice_pipeline_events

        for ev in iter_voice_pipeline_events(
            request,
            request.user,
            api_key,
            '/user/test/stream/',
            audio=audio,
        ):
            yield ndjson_line(ev)

    response = StreamingHttpResponse(
        event_stream(),
        content_type='application/x-ndjson; charset=utf-8',
    )
    response['Cache-Control'] = 'no-cache, no-store'
    response['X-Accel-Buffering'] = 'no'
    return response
