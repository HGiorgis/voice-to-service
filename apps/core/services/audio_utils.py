"""Validate uploaded audio: size, extension, duration (WAV / MP3)."""
import io
import wave
from typing import Optional, Tuple

from mutagen.mp3 import MP3


def extension_from_filename(name: str) -> str:
    if not name or '.' not in name:
        return ''
    return name.rsplit('.', 1)[-1].strip().lower()


def get_audio_duration_seconds(file_obj, ext: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Return (duration_seconds, error_message).
    duration None if could not determine (caller may reject unknown).
    """
    ext = (ext or '').lower().lstrip('.')
    try:
        file_obj.seek(0)
    except Exception:
        pass

    if ext == 'wav':
        try:
            raw = file_obj.read()
            file_obj.seek(0)
            with wave.open(io.BytesIO(raw), 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if not rate:
                    return None, 'Invalid WAV: missing sample rate'
                return frames / float(rate), None
        except Exception as e:
            return None, f'Could not read WAV duration: {e}'

    # Browser MediaRecorder — not MP3; duration unknown without ffprobe
    if ext == 'webm':
        return None, None

    if ext in ('mp3', 'mpeg'):
        try:
            raw = file_obj.read()
            file_obj.seek(0)
            audio = MP3(io.BytesIO(raw))
            if audio.info and audio.info.length:
                return float(audio.info.length), None
            return None, 'Could not read MP3 duration'
        except Exception as e:
            return None, f'Could not read MP3 duration: {e}'

    return None, f'Unsupported format for duration check: {ext}'


def validate_audio_upload(
    uploaded_file,
    *,
    max_size_mb: float,
    max_duration_seconds: float,
    allowed_extensions: list,
) -> Tuple[bool, Optional[str], Optional[float]]:
    """
    Returns (ok, error_message, duration_seconds).
    """
    name = getattr(uploaded_file, 'name', '') or ''
    ext = extension_from_filename(name)
    allowed = {a.lower().lstrip('.') for a in (allowed_extensions or [])}
    if ext not in allowed:
        return False, f'Invalid file type .{ext or "?"}. Allowed: {", ".join(sorted(allowed))}', None

    size = getattr(uploaded_file, 'size', None)
    if size is None:
        try:
            uploaded_file.seek(0, 2)
            size = uploaded_file.tell()
            uploaded_file.seek(0)
        except Exception:
            size = 0
    max_bytes = float(max_size_mb) * 1024 * 1024
    if size > max_bytes:
        return False, f'File too large (max {max_size_mb} MB)', None

    duration, err = get_audio_duration_seconds(uploaded_file, ext)
    if err:
        return False, err, None

    max_dur = float(max_duration_seconds)
    # Browser MediaRecorder → webm; duration often unknown without ffprobe — allow if size ok.
    if ext == 'webm':
        if duration is None:
            return True, None, None
        if duration > max_dur:
            return False, f'Audio too long ({duration:.1f}s). Maximum allowed is {max_dur:g}s', duration
        if duration < 0.3:
            return False, 'Audio too short (minimum ~0.3s)', duration
        return True, None, duration

    if duration is None:
        return False, 'Could not determine audio duration', None
    if duration > max_dur:
        return False, f'Audio too long ({duration:.1f}s). Maximum allowed is {max_dur:g}s', duration
    if duration < 0.3:
        return False, 'Audio too short (minimum ~0.3s)', duration

    return True, None, duration
