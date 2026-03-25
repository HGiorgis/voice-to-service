#!/usr/bin/env python3
"""
Minimal STT check using the same code as the Django app (transcribe_amharic).

Prerequisites:
  - pip install -r requirements.txt (google-cloud-speech, mutagen, django, python-dotenv, ...)
  - GOOGLE_APPLICATION_CREDENTIALS (file path) or GOOGLE_APPLICATION_CREDENTIALS_B64 in .env

Usage (from the voice-to-service folder):
  python scripts/stt_smoke_test.py path/to/audio.mp3
  python scripts/stt_smoke_test.py path/to/audio.wav

Loads voice-to-service/.env before reading any variables.

For STT v2, set GOOGLE_CLOUD_PROJECT in .env (or project_id in the service account JSON).
Default: GOOGLE_CLOUD_STT_V2_LOCATION=global, models long then chirp_2 (see .env.example).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_and_path() -> None:
    """Run first: sys.path + .env + fix relative credential paths."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    env_file = ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        pass

    if str(ROOT / "apps") not in sys.path:
        sys.path.insert(0, str(ROOT / "apps"))
    from core.gcp_credentials import install_gcp_credentials_from_env

    install_gcp_credentials_from_env(project_root=ROOT)

    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") or ""
    creds = raw.strip().strip('"').strip("'")
    if not creds:
        return
    p = Path(creds).expanduser()
    if p.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(p.resolve())
        return
    alt = (ROOT / creds).resolve()
    if alt.is_file():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(alt)
        return


def _bootstrap_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    # Must run before os.environ.get(...) for DEBUG, GOOGLE_APPLICATION_CREDENTIALS, etc.
    _load_env_and_path()

    audio_path = Path(sys.argv[1]).expanduser().resolve()
    if not audio_path.is_file():
        print(f"Not a file: {audio_path}", file=sys.stderr)
        return 2

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print(
            "Warning: No GCP credentials (set GOOGLE_APPLICATION_CREDENTIALS or "
            "GOOGLE_APPLICATION_CREDENTIALS_B64 in .env).",
            file=sys.stderr,
        )
    _bootstrap_django()

    from apps.core.services.speech_service import transcribe_amharic

    ext = audio_path.suffix.lower().lstrip(".") or "mp3"
    if ext == "mpeg":
        ext = "mp3"

    raw = audio_path.read_bytes()
    text, confidence, meta = transcribe_amharic(raw, ext, duration_seconds=None)

    print("\n========== TRANSCRIPT ==========")
    print((text or "").strip() or "(empty)")
    print("========== CONFIDENCE ==========")
    print(confidence if confidence is not None else "n/a")
    print("========== META ================")
    print(json.dumps(meta, indent=2, ensure_ascii=False, default=str))
    print("================================\n")

    return 0 if (text or "").strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
