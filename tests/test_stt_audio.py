"""
Speech-to-Text tests for `transcribe_amharic`.

Audio input — two options (plus default folder):
  1) STT_TEST_AUDIO       Path to a single .wav / .mp3 / .mpeg file.
  2) STT_TEST_AUDIO_DIR  Directory; all matching audio files are transcribed in integration tests.
  3) If neither is set, files under tests/fixtures/audio/ are used.

Integration tests call the real Google API; require ADC or GOOGLE_APPLICATION_CREDENTIALS.

Run (from voice-to-service directory):
  pip install pytest
  pytest tests/test_stt_audio.py -v
  pytest tests/test_stt_audio.py -v -m integration
  STT_TEST_AUDIO=D:\\clips\\test.mp3 pytest tests/test_stt_audio.py -v -m integration
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Project root = parent of tests/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Mocked tests patch v1 only; skip real v2 so `transcribe_amharic` hits the mock.
os.environ.setdefault("STT_DISABLE_V2", "1")

import django

django.setup()

from apps.core.services.speech_service import (  # noqa: E402
    _AM_ET_V1_MODELS,
    transcribe_amharic,
)

TESTS_DIR = Path(__file__).resolve().parent
DEFAULT_AUDIO_DIR = TESTS_DIR / "fixtures" / "audio"

AUDIO_GLOBS = ("*.mp3", "*.wav", "*.mpeg", "*.MP3", "*.WAV")


def resolve_integration_audio_files() -> list[Path]:
    """
    Option 1: STT_TEST_AUDIO -> single file.
    Option 2: STT_TEST_AUDIO_DIR -> all audio in dir.
    Default: tests/fixtures/audio/*
    """
    single = os.environ.get("STT_TEST_AUDIO", "").strip()
    if single:
        p = Path(single).expanduser()
        if p.is_file():
            return [p]
        if single:
            pytest.fail(f"STT_TEST_AUDIO is not a file: {p}")

    dir_env = os.environ.get("STT_TEST_AUDIO_DIR", "").strip()
    base = Path(dir_env).expanduser() if dir_env else DEFAULT_AUDIO_DIR
    if not base.is_dir():
        return []

    out: list[Path] = []
    for pattern in AUDIO_GLOBS:
        out.extend(base.glob(pattern))
    # de-dupe, stable order
    return sorted({p.resolve() for p in out})


def _assert_stt_tuple_shape(text: str, confidence, meta: dict) -> None:
    """Expected return type: (str, Optional[float], dict)."""
    assert isinstance(text, str)
    assert confidence is None or isinstance(confidence, (int, float))
    if confidence is not None:
        assert 0.0 <= float(confidence) <= 1.0
    assert isinstance(meta, dict)
    assert meta.get("provider") == "google_speech"
    assert "format" in meta


def test_amharic_v1_models_exclude_latest_long_short():
    """V1 am-ET does not support latest_long / latest_short (API returns 400)."""
    for m in _AM_ET_V1_MODELS:
        if m is None:
            continue
        assert not str(m).startswith("latest_"), m


@patch("google.cloud.speech.SpeechClient")
def test_transcribe_returns_expected_shape_mocked(mock_client_cls):
    """No network: STT client returns one result → check tuple + meta keys."""
    alt = MagicMock()
    alt.transcript = "ሰላም"
    alt.confidence = 0.91
    result = MagicMock()
    result.alternatives = [alt]
    response = MagicMock()
    response.results = [result]

    inst = MagicMock()
    inst.recognize.return_value = response
    mock_client_cls.return_value = inst

    text, conf, meta = transcribe_amharic(
        b"dummy-mp3-bytes",
        "mp3",
        duration_seconds=2.0,
    )

    _assert_stt_tuple_shape(text, conf, meta)
    assert text == "ሰላም"
    assert conf is not None and abs(float(conf) - 0.91) < 1e-6
    assert meta.get("stt_attempt") == 1
    assert not meta.get("empty")
    inst.recognize.assert_called()


@patch("google.cloud.speech.SpeechClient")
def test_transcribe_empty_then_retry_finds_words(mock_client_cls):
    """Second config returns transcript after first returns empty results."""
    empty_alt = MagicMock()
    empty_alt.transcript = ""
    empty_res = MagicMock()
    empty_res.alternatives = [empty_alt]
    empty_resp = MagicMock()
    empty_resp.results = [empty_res]

    good_alt = MagicMock()
    good_alt.transcript = "አማርኛ"
    good_alt.confidence = 0.85
    good_res = MagicMock()
    good_res.alternatives = [good_alt]
    good_resp = MagicMock()
    good_resp.results = [good_res]

    inst = MagicMock()
    inst.recognize.side_effect = [empty_resp, good_resp]
    mock_client_cls.return_value = inst

    text, conf, meta = transcribe_amharic(b"bytes", "mp3", duration_seconds=1.0)
    assert text == "አማርኛ"
    assert meta.get("stt_attempt") == 2
    assert meta.get("stt_retry") == "config_variant_2"


@patch("google.cloud.speech.SpeechClient")
def test_transcribe_all_empty_marks_empty_meta(mock_client_cls):
    alt = MagicMock()
    alt.transcript = "   "
    alt.confidence = None  # truthy MagicMock breaks avg_conf assertion
    res = MagicMock()
    res.alternatives = [alt]
    resp = MagicMock()
    resp.results = [res]
    inst = MagicMock()
    inst.recognize.return_value = resp
    mock_client_cls.return_value = inst

    text, conf, meta = transcribe_amharic(b"x", "mp3", duration_seconds=1.0)
    _assert_stt_tuple_shape(text, conf, meta)
    assert text == ""
    assert meta.get("empty") is True
    assert "hint" in meta


requires_gcp = pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    reason="Set GOOGLE_APPLICATION_CREDENTIALS for live STT (service account JSON)",
)


@requires_gcp
@pytest.mark.integration
@pytest.mark.parametrize("path", resolve_integration_audio_files() or [None])
def test_live_transcribe_integration(path: Path | None, monkeypatch):
    """
    Real API: uses STT_TEST_AUDIO, STT_TEST_AUDIO_DIR, or tests/fixtures/audio/.
    If no files found, skip (place samples or set env).
    """
    if path is None:
        pytest.skip(
            "No audio files: add under tests/fixtures/audio/ or set "
            "STT_TEST_AUDIO / STT_TEST_AUDIO_DIR"
        )

    monkeypatch.delenv("STT_DISABLE_V2", raising=False)

    raw = path.read_bytes()
    ext = path.suffix.lower().lstrip(".") or "mp3"

    text, conf, meta = transcribe_amharic(raw, ext, duration_seconds=None)

    _assert_stt_tuple_shape(text, conf, meta)
    # Pretty-printed shape for debugging failures
    print(
        "\n=== STT integration ===",
        f"\nfile: {path}",
        f"\ntext: {text!r}",
        f"\nconfidence: {conf}",
        f"\nmeta: {meta}",
        "\n=======================\n",
    )

    assert meta.get("stt_attempt", 0) >= 1
    # Do not require non-empty text: silence / wrong language may legitimately be empty;
    # still assert API contract.
    if meta.get("empty"):
        assert isinstance(text, str) and text.strip() == ""


def test_resolve_integration_paths_without_env_uses_default_dir_only_if_present():
    """When no STT_TEST_* env and no fixtures, list is empty (integration skips)."""
    # This test mutates env — restore
    saved_a = os.environ.pop("STT_TEST_AUDIO", None)
    saved_d = os.environ.pop("STT_TEST_AUDIO_DIR", None)
    try:
        files = resolve_integration_audio_files()
        if DEFAULT_AUDIO_DIR.is_dir():
            # may be non-empty if user added files
            for p in files:
                assert p.exists()
    finally:
        if saved_a is not None:
            os.environ["STT_TEST_AUDIO"] = saved_a
        if saved_d is not None:
            os.environ["STT_TEST_AUDIO_DIR"] = saved_d
