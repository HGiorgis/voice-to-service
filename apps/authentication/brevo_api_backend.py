"""
Django email backend: Brevo (Sendinblue) Transactional Email API over HTTPS.

Uses ``POST https://api.brevo.com/v3/smtp/email`` — no SMTP ports (25/587/465), so it works
when outbound SMTP is blocked; only HTTPS (443) is required.

Set ``BREVO_API_KEY`` in the environment (Brevo → SMTP & API → API keys → create v3 key).
The sender address must be verified in Brevo (same as SMTP).
"""
from __future__ import annotations

import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import EmailMessage

logger = logging.getLogger(__name__)

BREVO_SEND_URL = 'https://api.brevo.com/v3/smtp/email'


class BrevoApiEmailBackend(BaseEmailBackend):
    """Send mail via Brevo REST API (not SMTP)."""

    def __init__(self, fail_silently: bool = False, **kwargs) -> None:
        super().__init__(fail_silently=fail_silently)
        self.timeout = int(
            kwargs.pop('timeout', None) or getattr(settings, 'EMAIL_TIMEOUT', 15) or 15
        )
        # Ignore kwargs meant for SMTP backends (get_connection passes them through).
        kwargs.clear()
        self.api_key = (getattr(settings, 'BREVO_API_KEY', None) or '').strip()
        if not self.api_key:
            raise ValueError('BREVO_API_KEY is empty — set it in the environment.')

    def send_messages(self, email_messages: list[EmailMessage]) -> int:
        if not email_messages:
            return 0
        sent = 0
        for message in email_messages:
            try:
                self._post_message(message)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception('Brevo API send failed (fail_silently=True)')
        return sent

    def _post_message(self, message: EmailMessage) -> None:
        from_header = message.from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
        name, addr = parseaddr(from_header)
        if not addr:
            addr = (from_header or '').strip()
        if not name:
            name = (getattr(settings, 'DEFAULT_FROM_NAME', None) or 'Voice To Service').strip()

        to_payload = []
        for raw in message.to:
            _, em = parseaddr(raw)
            to_payload.append({'email': em or raw.strip()})

        if not to_payload:
            raise ValueError('Email message has no recipients in "to".')

        text_body = message.body or ''
        html_body = None
        for content, ctype in getattr(message, 'alternatives', None) or []:
            if ctype == 'text/html':
                html_body = content
                break

        payload: dict = {
            'sender': {'name': name, 'email': addr},
            'to': to_payload,
            'subject': message.subject or '',
            'textContent': text_body,
        }
        if html_body:
            payload['htmlContent'] = html_body

        resp = requests.post(
            BREVO_SEND_URL,
            headers={
                'accept': 'application/json',
                'api-key': self.api_key,
                'content-type': 'application/json',
            },
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            detail = (resp.text or '')[:800]
            logger.error('Brevo API error %s: %s', resp.status_code, detail)
            raise RuntimeError(f'Brevo API HTTP {resp.status_code}: {detail}')
