#!/usr/bin/env python3
"""
Encode a Google Cloud service account JSON key for use in production .env.

Reads the file (e.g. key/your-project-xxxxx.json), outputs Base64 for:

  GOOGLE_APPLICATION_CREDENTIALS_B64

Usage (from voice-to-service directory):

  python scripts/encode_gcp_credentials_b64.py path/to/service-account.json

Or default search key/*.json if exactly one file exists:

  python scripts/encode_gcp_credentials_b64.py

Paste the printed line into .env. You can comment out GOOGLE_APPLICATION_CREDENTIALS
when using the B64 variable.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _default_key_file() -> Path | None:
    key_dir = ROOT / 'key'
    if not key_dir.is_dir():
        return None
    json_files = sorted(key_dir.glob('*.json'))
    if len(json_files) == 1:
        return json_files[0]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'json_file',
        nargs='?',
        help='Path to service account .json (default: single key/*.json if unambiguous)',
    )
    args = parser.parse_args()

    path: Path | None
    if args.json_file:
        path = Path(args.json_file).expanduser().resolve()
    else:
        path = _default_key_file()
        if path is None:
            print(
                'Pass the JSON path explicitly, or place exactly one *.json under ./key/',
                file=sys.stderr,
            )
            return 2

    if not path.is_file():
        print(f'Not a file: {path}', file=sys.stderr)
        return 2

    raw = path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode('ascii')

    print('# Add to .env (single line; keep secret):')
    print(f'GOOGLE_APPLICATION_CREDENTIALS_B64={b64}')
    print()
    print('# Optional: disable file path when using B64')
    print('# GOOGLE_APPLICATION_CREDENTIALS=')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
