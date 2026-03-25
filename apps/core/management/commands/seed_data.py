"""
Load small sample data for local demos.

  python manage.py seed_data              # ensure demo user exists (get_or_create)
  python manage.py seed_data --clear      # wipe almost everything except superuser accounts, then seed

With ``--clear``:
  Removes all voice jobs, API keys/logs, registration attempts, **all blocked IPs**,
  non-superuser users (and their social-auth rows), Django sessions, and Django
  admin history (``LogEntry``).
  **Superusers** are kept; their block/suspicious flags, registration telemetry,
  and API usage counters are cleared.

Preserves: superuser accounts (cleared of flags/telemetry above), ``SystemSettings``,
``AntiAbuseSettings`` singletons (configuration is not reset).

Optional env overrides:
  SAMPLE_USER_USERNAME   (default: demo_user)
  SAMPLE_USER_EMAIL      (default: demo@voice-to-service.local)
  SAMPLE_USER_PASSWORD   (default: demo12345)
"""
from __future__ import annotations

import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import (
    APIKey,
    APIKeyLog,
    BlockedIPAddress,
    RegistrationAttempt,
)
from apps.core.models import SystemSettings
from apps.voice.models import VoiceProcessingRequest


def _reset_superuser_auxiliary_fields() -> None:
    """Clear blocks, abuse flags, signup telemetry, and usage stats on surviving admins."""
    User = get_user_model()
    User.objects.filter(is_superuser=True).update(
        is_blocked=False,
        blocked_reason='',
        blocked_at=None,
        suspicious_registration_flag=False,
        registration_ip='',
        registration_fingerprint_hash='',
        registration_device_id=None,
        total_api_calls=0,
        last_api_call=None,
    )


def _clear_all_except_superusers() -> int:
    """Remove all app and security-audit rows except superuser accounts. Returns deleted user count."""
    try:
        from django.contrib.admin.models import LogEntry
    except Exception:  # pragma: no cover
        LogEntry = None
    try:
        from django.contrib.sessions.models import Session
    except Exception:  # pragma: no cover
        Session = None
    try:
        from social_django.models import UserSocialAuth
    except Exception:  # pragma: no cover
        UserSocialAuth = None

    VoiceProcessingRequest.objects.all().delete()
    APIKeyLog.objects.all().delete()
    APIKey.objects.all().delete()
    RegistrationAttempt.objects.all().delete()
    BlockedIPAddress.objects.all().delete()

    if LogEntry is not None:
        LogEntry.objects.all().delete()
    if Session is not None:
        Session.objects.all().delete()

    if UserSocialAuth is not None:
        UserSocialAuth.objects.exclude(user__is_superuser=True).delete()

    User = get_user_model()
    qs = User.objects.filter(is_superuser=False)
    n = qs.count()
    qs.delete()
    _reset_superuser_auxiliary_fields()
    return n


def _seed_demo_user(*, no_api_key: bool):
    User = get_user_model()
    username = os.environ.get('SAMPLE_USER_USERNAME', 'demo_user').strip() or 'demo_user'
    email = os.environ.get('SAMPLE_USER_EMAIL', 'demo@voice-to-service.local').strip()
    password = os.environ.get('SAMPLE_USER_PASSWORD', 'demo12345')

    defaults = {
        'email': email,
        'first_name': 'Demo',
        'last_name': 'Listener',
        'company_name': 'Voice To Service QA',
        'phone': '+251911000000',
        'is_active': True,
        'is_verified': True,
        'is_staff': False,
        'is_superuser': False,
    }

    user, created = User.objects.get_or_create(username=username, defaults=defaults)

    user.email = email
    user.first_name = defaults['first_name']
    user.last_name = defaults['last_name']
    user.company_name = defaults['company_name']
    user.phone = defaults['phone']
    user.is_active = True
    user.is_verified = True
    user.is_staff = False
    user.is_superuser = False
    user.email_verification_code_hash = ''
    user.email_verification_sent_at = None
    user.email_verification_expires_at = None
    user.email_verified_at = timezone.now()
    user.set_password(password)

    s = SystemSettings.get_settings()
    user.daily_request_limit = s.default_daily_limit
    user.monthly_request_limit = s.default_monthly_limit
    user.daily_voice_limit = s.default_daily_voice_limit
    user.registration_ip = ''
    user.registration_fingerprint_hash = ''
    user.suspicious_registration_flag = False
    user.signup_username_edit_used = False
    user.email_verification_send_count = 0
    user.pending_signup_email_changed_at = None

    user.save()

    raw_key = None
    if not no_api_key:
        APIKey.objects.filter(user=user).delete()
        expires = timezone.now() + timedelta(days=s.key_expiry_days)
        key = APIKey.objects.create(
            user=user,
            name=f'Seeded key for {username}',
            expires_at=expires,
        )
        raw_key = key.key

    return user, created, raw_key


class Command(BaseCommand):
    help = (
        'Seed one demo user (and optional API key). '
        'Use --clear to wipe all user/app/security state except superuser accounts.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete voice jobs, API logs/keys, all blocked IPs, registration attempts, '
            'sessions, admin log entries, non-superuser users and their social links; '
            'clear block/suspicious/telemetry/usage fields on superusers; then seed.',
        )
        parser.add_argument(
            '--no-api-key',
            action='store_true',
            help='Do not create a fresh API key for the demo user.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if not User.objects.filter(is_superuser=True).exists():
            self.stdout.write(
                self.style.WARNING(
                    'No superuser found. Create one first (createsuperuser or create_default_admin).'
                )
            )

        if options['clear']:
            self.stdout.write(
                self.style.WARNING(
                    'Clearing Voice To Service data (superuser accounts preserved; blocks/flags/sessions wiped)...'
                )
            )
            n_users = _clear_all_except_superusers()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Removed {n_users} non-superuser account(s); cleared blocks, logs, sessions, and related rows.'
                )
            )

        user, created, raw_key = _seed_demo_user(no_api_key=options['no_api_key'])

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(
                f'{action} demo user:\n'
                f'  Username:  {user.username}\n'
                f'  Email:     {user.email}\n'
                f'  Password:  SAMPLE_USER_PASSWORD env or default "demo12345"\n'
                f'  Name:      {user.first_name} {user.last_name}\n'
                f'  Company:   {user.company_name}\n'
                f'  Phone:     {user.phone}\n'
                f'  Limits:    daily API {user.daily_request_limit}, voice/day {user.daily_voice_limit}'
            )
        )
        if raw_key:
            self.stdout.write(
                self.style.WARNING(
                    '\nAPI key (copy now; stored hashed in DB — not shown again):\n' + raw_key + '\n'
                )
            )
        elif options['no_api_key']:
            self.stdout.write('API key: skipped (--no-api-key).')
