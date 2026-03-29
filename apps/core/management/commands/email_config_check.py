"""
Print what Django actually sees for email (masked) + raw env lengths.

Use on Render: Shell → run from project root:
  python manage.py email_config_check
  python manage.py email_config_check --connection-test

If BREVO_API_KEY is set, the app uses Brevo's HTTPS API. Otherwise mail goes to the console.
"""
import argparse
import os

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Show email settings (masked) and optional Brevo API check — for Render/local debugging.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--connection-test',
            action='store_true',
            help='Brevo API: GET /v3/account (no email sent)',
        )
        parser.add_argument(
            '--smtp-test',
            action='store_true',
            help=argparse.SUPPRESS,  # deprecated alias
        )

    def handle(self, *args, **options):
        run_test = options['connection_test'] or options.get('smtp_test')
        self.stdout.write('=== Django settings (what send_mail uses) ===\n')
        for name in (
            'EMAIL_BACKEND',
            'EMAIL_TIMEOUT',
            'DEFAULT_FROM_EMAIL',
            'DEFAULT_FROM_NAME',
        ):
            self.stdout.write(f'  {name}: {getattr(settings, name, "—")}')

        bk = getattr(settings, 'BREVO_API_KEY', '') or ''
        self.stdout.write(f'  BREVO_API_KEY: len={len(bk)}')

        self.stdout.write('\n=== Raw OS environment (variable present?) ===\n')
        for key in (
            'EMAIL_BACKEND',
            'BREVO_API_KEY',
            'DEFAULT_FROM_EMAIL',
            'DEFAULT_FROM_NAME',
            'EMAIL_TIMEOUT',
            'DEBUG',
            'RENDER',
        ):
            raw = os.environ.get(key)
            if raw is None:
                self.stdout.write(f'  {key}: <not set>')
            else:
                self.stdout.write(f'  {key}: len={len(raw)}')

        backend = getattr(settings, 'EMAIL_BACKEND', '') or ''
        if 'brevo_api_backend' in backend:
            if not bk.strip():
                self.stderr.write(
                    self.style.ERROR(
                        '\n[!] Brevo API backend selected but BREVO_API_KEY is empty.\n'
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        '\n[i] Using Brevo HTTPS API — verify DEFAULT_FROM_EMAIL is a verified sender in Brevo.\n'
                    )
                )
        elif getattr(settings, 'EMAIL_BACKEND', '').endswith('console.EmailBackend'):
            self.stderr.write(
                self.style.WARNING(
                    '\n[!] Console email backend — no real mail. Set BREVO_API_KEY (and redeploy) for production.\n'
                )
            )

        if run_test:
            self._run_connection_test(backend, bk)

    def _run_connection_test(self, backend: str, brevo_key: str) -> None:
        if 'brevo_api_backend' in backend:
            self.stdout.write('\n=== Brevo API test (GET /v3/account) ===\n')
            if not brevo_key.strip():
                self.stderr.write(self.style.ERROR('  No BREVO_API_KEY — skip.'))
                return
            try:
                r = requests.get(
                    'https://api.brevo.com/v3/account',
                    headers={'accept': 'application/json', 'api-key': brevo_key.strip()},
                    timeout=15,
                )
                if r.status_code < 400:
                    self.stdout.write(self.style.SUCCESS(f'  OK (HTTP {r.status_code})'))
                else:
                    self.stderr.write(
                        self.style.ERROR(f'  FAILED HTTP {r.status_code}: {(r.text or "")[:400]}')
                    )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f'  FAILED: {type(exc).__name__}: {exc}'))
            return

        self.stdout.write(
            '\n[i] Connection test is for Brevo API. '
            'Set BREVO_API_KEY and apps.authentication.brevo_api_backend.BrevoApiEmailBackend (default when key is set).\n'
        )
