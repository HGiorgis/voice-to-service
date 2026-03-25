"""
Materialize Google Cloud service-account credentials for Application Default Credentials.

Production: set ``GOOGLE_APPLICATION_CREDENTIALS_B64`` to the Base64 encoding of the
full JSON key file (see ``scripts/encode_gcp_credentials_b64.py``). This module writes
a short-lived file and sets ``GOOGLE_APPLICATION_CREDENTIALS`` so ``google-cloud-*``
libraries work unchanged.

**Common mistake:** Pasting the raw JSON into ``GOOGLE_APPLICATION_CREDENTIALS``.
That variable must be a **file path** unless it is detected as JSON below (we then
write a temp file automatically).
"""
from __future__ import annotations

import atexit
import base64
import binascii
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_credentials_temp_path: Optional[str] = None


def _try_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _validate_sa_dict(data: Any) -> bool:
    if not isinstance(data, dict):
        logger.warning('Service account JSON must be an object')
        return False
    if data.get('type') != 'service_account':
        logger.warning(
            'Credentials JSON type is %r — expected service_account',
            data.get('type'),
        )
    return True


def _materialize_json_to_tempfile(data: dict) -> str:
    fd, path = tempfile.mkstemp(prefix='gcp-sa-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        _try_unlink(path)
        raise
    return path


def install_gcp_credentials_from_env(*, project_root: Optional[Path] = None) -> None:
    """
    - ``GOOGLE_APPLICATION_CREDENTIALS_B64``: decode → temp JSON → set env path.
    - ``GOOGLE_APPLICATION_CREDENTIALS`` if value **starts with ``{``**:
      treat as inline JSON (not a path) → temp file → set env path.
    - Else ``GOOGLE_APPLICATION_CREDENTIALS``: resolve as filesystem path
      (relative paths against *project_root*).
    """
    global _credentials_temp_path

    b64 = (os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_B64') or '').strip()
    if b64:
        if _credentials_temp_path and os.path.isfile(_credentials_temp_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = _credentials_temp_path
            return

        if 'base64,' in b64:
            b64 = b64.split('base64,', 1)[-1].strip()
        b64 = ''.join(b64.split())

        try:
            raw = base64.standard_b64decode(b64)
        except (binascii.Error, ValueError) as e:
            logger.warning('GOOGLE_APPLICATION_CREDENTIALS_B64 is not valid Base64: %s', e)
            return

        try:
            text = raw.decode('utf-8')
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning('GOOGLE_APPLICATION_CREDENTIALS_B64 decodes but is not JSON: %s', e)
            return

        if not _validate_sa_dict(data):
            return

        path = _materialize_json_to_tempfile(data)
        _credentials_temp_path = path
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = path
        atexit.register(_try_unlink, path)
        logger.debug('GCP credentials materialized from GOOGLE_APPLICATION_CREDENTIALS_B64')
        return

    raw_path = (os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or '').strip().strip('"').strip("'")
    if not raw_path:
        return

    # Paste mistake: full JSON in GOOGLE_APPLICATION_CREDENTIALS instead of a path.
    if raw_path.lstrip().startswith('{'):
        try:
            data = json.loads(raw_path)
        except json.JSONDecodeError as e:
            logger.warning(
                'GOOGLE_APPLICATION_CREDENTIALS looks like JSON but is invalid (%s). '
                'Use a file path, or GOOGLE_APPLICATION_CREDENTIALS_B64.',
                e,
            )
            return
        if isinstance(data, dict) and _validate_sa_dict(data):
            if _credentials_temp_path and os.path.isfile(_credentials_temp_path):
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = _credentials_temp_path
                return
            path = _materialize_json_to_tempfile(data)
            _credentials_temp_path = path
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = path
            atexit.register(_try_unlink, path)
            logger.warning(
                'GOOGLE_APPLICATION_CREDENTIALS contained raw JSON, not a path. '
                'Prefer a file path or GOOGLE_APPLICATION_CREDENTIALS_B64 for production.'
            )
        else:
            logger.warning(
                'GOOGLE_APPLICATION_CREDENTIALS starts with { but is not a valid service account object.'
            )
        return

    p = Path(raw_path).expanduser()
    if p.is_file():
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(p.resolve())
        return
    if project_root is not None:
        alt = (project_root / raw_path).resolve()
        if alt.is_file():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(alt)
