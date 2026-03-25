"""Local storage for ephemeral voice pipeline uploads.

``default_storage`` may be S3/B2; ``save()`` calls ``exists()`` (HeadObject), which can
return 403 if the key policy or credential scope disallows it. Worker and web process
both read these files from a shared directory under ``MEDIA_ROOT``.
"""
import inspect
import os
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage

_voice_temp_storage: FileSystemStorage | None = None


def get_voice_temp_storage() -> FileSystemStorage:
    global _voice_temp_storage
    if _voice_temp_storage is None:
        root = getattr(settings, 'VOICE_TEMP_STORAGE_ROOT', None)
        root = Path(root) if root is not None else (Path(settings.MEDIA_ROOT) / 'voice_temp')
        root.mkdir(parents=True, exist_ok=True)

        kwargs: dict = {'location': str(root.resolve())}
        sig = inspect.signature(FileSystemStorage.__init__)
        if 'allow_overwrite' in sig.parameters:
            kwargs['allow_overwrite'] = True
        elif 'file_overwrite' in sig.parameters:
            kwargs['file_overwrite'] = True

        _voice_temp_storage = FileSystemStorage(**kwargs)
    return _voice_temp_storage


def normalize_temp_audio_name(stored: str) -> str:
    """Support legacy values like ``voice_temp/<uuid>.ext``."""
    if not stored:
        return stored
    return os.path.basename(stored.replace('\\', '/'))
