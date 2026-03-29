#!/usr/bin/env python3
"""
Send one test email through the same configuration the app uses (Brevo API or console).

Prerequisites:
  - Run from the ``voice-to-service`` directory (or any CWD; paths are resolved from this file).
  - ``.env`` with ``BREVO_API_KEY`` and ``DEFAULT_FROM_EMAIL`` as in production (see ``.env.example`` and ``docs/email-brevo-render.md``).

Usage:
  python scripts/send_test_email.py recipient@example.com
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(ROOT / "apps") not in sys.path:
        sys.path.insert(0, str(ROOT / "apps"))

    env_file = ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        pass


def _from_email_header() -> str:
    from django.conf import settings

    raw = (getattr(settings, "DEFAULT_FROM_EMAIL", None) or "").strip()
    name = (getattr(settings, "DEFAULT_FROM_NAME", None) or "").strip()
    if name and raw and "<" not in raw:
        return f"{name} <{raw}>"
    return raw or "noreply@localhost"


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python scripts/send_test_email.py recipient@example.com\n")
        return 2

    to_addr = (sys.argv[1] or "").strip()
    if "@" not in to_addr:
        sys.stderr.write("Invalid recipient — expected an email address.\n")
        return 2

    _load_env()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    from django.conf import settings
    from django.core.mail import send_mail

    from_email = _from_email_header()
    subject = "Voice To Service — email test"
    body = (
        "This is a test message from scripts/send_test_email.py\n\n"
        "If you received this, Django email settings (Brevo API or console) are working.\n"
    )

    backend = getattr(settings, "EMAIL_BACKEND", "")
    brevo = (getattr(settings, "BREVO_API_KEY", "") or "").strip()
    timeout = getattr(settings, "EMAIL_TIMEOUT", None)

    print("Sending test email (same stack as the running app)...")
    print(f"  EMAIL_BACKEND: {backend}")
    print(f"  BREVO_API_KEY: {'set' if brevo else '(empty — console if no explicit backend)'}")
    print(f"  EMAIL_TIMEOUT: {timeout}s")
    print(f"  From:          {from_email}")
    print(f"  To:            {to_addr}")

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[to_addr],
            fail_silently=False,
        )
    except Exception as exc:
        sys.stderr.write(f"\n[fail] Could not send: {type(exc).__name__}: {exc}\n")
        sys.stderr.write(
            "\nCheck docs/email-brevo-render.md (verified sender + BREVO_API_KEY).\n"
        )
        return 1

    print("\n[ok] Message accepted by the mail backend. Check the inbox (and spam).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
