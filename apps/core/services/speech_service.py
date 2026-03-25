"""Google Cloud Speech-to-Text (Amharic-first; English fallback for testing)."""
import io
import json
import logging
import os
import wave
from pathlib import Path
from typing import Tuple, Optional, Dict, Any, List, Sequence

logger = logging.getLogger(__name__)

# Speech-to-Text **v1**: am-ET only supports `default` and `command_and_search` (not latest_long / latest_short).
# See: https://cloud.google.com/speech-to-text/docs/v1/speech-to-text-supported-languages
_AM_ET_V1_MODELS: Sequence[Optional[str]] = ('default', 'command_and_search', None)


def _gcp_project_id() -> Optional[str]:
    pid = (os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('GCLOUD_PROJECT') or '').strip()
    if pid:
        return pid
    creds_path = (os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or '').strip().strip('"').strip("'")
    if not creds_path:
        return None
    p = Path(creds_path).expanduser()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return (data.get('project_id') or '').strip() or None
    except (OSError, json.JSONDecodeError):
        return None


def _v2_response_has_words(response) -> bool:
    for res in response.results or []:
        for alt in res.alternatives or []:
            if (alt.transcript or '').strip():
                return True
    return False


def _v2_response_to_text(response) -> Tuple[str, Optional[float]]:
    parts: List[str] = []
    confidences: List[float] = []
    for res in response.results or []:
        if not res.alternatives:
            continue
        alt = res.alternatives[0]
        t = (alt.transcript or '').strip()
        if t:
            parts.append(alt.transcript.strip())
        if alt.confidence:
            confidences.append(float(alt.confidence))
    text = ' '.join(parts).strip()
    avg = sum(confidences) / len(confidences) if confidences else None
    return text, avg


def _stt_v2_models_to_try(location: str) -> Sequence[str]:
    """
    ``GOOGLE_CLOUD_STT_V2_MODELS`` (comma-separated) wins if set.

    At ``locations/global``, Chirp models are not available — default is ``long`` only.
    Regional locations (e.g. ``us-central1``) can use ``long`` then ``chirp_2`` as fallback.
    """
    raw = (os.environ.get('GOOGLE_CLOUD_STT_V2_MODELS') or '').strip()
    if raw:
        return tuple(m.strip() for m in raw.split(',') if m.strip())

    primary = (os.environ.get('GOOGLE_CLOUD_STT_V2_MODEL') or 'long').strip()
    if location.strip().lower() == 'global':
        return (primary,)

    if primary == 'chirp_2':
        return ('chirp_2', 'long')
    return (primary, 'chirp_2')


def _speech_v2_client_for_location(location: str):
    """Global → default host; otherwise ``{location}-speech.googleapis.com``."""
    from google.cloud.speech_v2 import SpeechClient

    loc = location.strip()
    if loc.lower() == 'global':
        return SpeechClient(), loc
    from google.api_core.client_options import ClientOptions

    host = f'{loc}-speech.googleapis.com'
    return SpeechClient(client_options=ClientOptions(api_endpoint=host)), loc


def _try_stt_v2(
    audio_bytes: bytes,
    meta: Dict[str, Any],
    *,
    stereo: bool,
) -> Tuple[str, Optional[float]]:
    """
    Speech-to-Text **v2** using the same style as BatchRecognize in Cloud Console:
    ``locations/global/recognizers/_``, ``model=long``, ``language_codes=[\"am-ET\"]``,
    auto-detected decoding. Uploads use sync ``recognize()`` with inline ``content`` (shorter clips).

    For long / GCS-only jobs, use ``batch_recognize`` separately with the same RecognitionConfig.
    """
    if os.environ.get('STT_DISABLE_V2', '').lower() in ('1', 'true', 'yes'):
        meta['stt_v2'] = 'skipped_env_STT_DISABLE_V2'
        return '', None

    try:
        from google.cloud.speech_v2 import SpeechClient
        from google.cloud.speech_v2.types import cloud_speech
    except ImportError as e:
        meta['stt_v2'] = f'skipped_import_{e}'
        return '', None

    project = _gcp_project_id()
    if not project:
        meta['stt_v2'] = 'skipped_no_project_id_set_GOOGLE_CLOUD_PROJECT_or_service_account_json'
        return '', None

    location = (os.environ.get('GOOGLE_CLOUD_STT_V2_LOCATION') or 'global').strip()
    client, loc_normalized = _speech_v2_client_for_location(location)
    recognizer = SpeechClient.recognizer_path(project, loc_normalized, '_')
    meta['stt_v2_location'] = loc_normalized
    meta['stt_v2_recognizer'] = recognizer

    def _features(*, separate_stereo: bool) -> cloud_speech.RecognitionFeatures:
        # Implicit global recognizer + model `long` does not support automatic_punctuation (400).
        sep = cloud_speech.RecognitionFeatures.MultiChannelMode.SEPARATE_RECOGNITION_PER_CHANNEL
        if separate_stereo and stereo:
            return cloud_speech.RecognitionFeatures(
                enable_word_time_offsets=True,
                multi_channel_mode=sep,
            )
        return cloud_speech.RecognitionFeatures(
            enable_word_time_offsets=True,
        )

    configs: List[Any] = []
    for model in _stt_v2_models_to_try(loc_normalized):
        configs.append(
            cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=['am-ET'],
                model=model,
                features=_features(separate_stereo=False),
            )
        )
        if stereo:
            configs.append(
                cloud_speech.RecognitionConfig(
                    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                    language_codes=['am-ET'],
                    model=model,
                    features=_features(separate_stereo=True),
                )
            )

    last_err: Optional[BaseException] = None
    for i, cfg in enumerate(configs):
        request = cloud_speech.RecognizeRequest(
            recognizer=recognizer,
            config=cfg,
            content=audio_bytes,
        )
        try:
            response = client.recognize(request=request)
            meta['stt_v2_attempt'] = i + 1
            meta['stt_v2_model'] = cfg.model
            mc = getattr(cfg.features, 'multi_channel_mode', None)
            sep = cloud_speech.RecognitionFeatures.MultiChannelMode.SEPARATE_RECOGNITION_PER_CHANNEL
            meta['stt_v2_multichannel'] = (
                'separate_per_channel' if mc == sep else 'default_first_channel_only'
            )

            if _v2_response_has_words(response):
                text, conf = _v2_response_to_text(response)
                if text.strip():
                    meta['stt_api'] = 'v2'
                    meta['alternatives'] = len(response.results or [])
                    return text, conf
        except Exception as e:
            last_err = e
            logger.warning('STT v2 attempt %s failed: %s', i + 1, e)
            meta.setdefault('stt_v2_errors', []).append(str(e)[:400])

    meta['stt_v2'] = 'empty_or_failed'
    if last_err is not None:
        meta['stt_v2_last_error'] = str(last_err)[:500]
    return '', None


def _inspect_wav(audio_bytes: bytes) -> Dict[str, Any]:
    """Read WAV header; ensure settings Google STT v1 expects for LINEAR16."""
    info: Dict[str, Any] = {}
    try:
        with wave.open(io.BytesIO(audio_bytes), 'rb') as wf:
            info['rate'] = wf.getframerate()
            info['channels'] = wf.getnchannels()
            info['sampwidth'] = wf.getsampwidth()
            info['comptype'] = wf.getcomptype()
            info['frames'] = wf.getnframes()
    except Exception as e:
        raise ValueError(
            'Invalid WAV file (could not read header). Try exporting as WAV or use MP3.'
        ) from e

    if info['comptype'] != 'NONE':
        raise ValueError(
            f'WAV uses compression (“{info["comptype"]}”). '
            'Export as uncompressed PCM (Audacity: WAV, signed 16-bit PCM) or upload MP3.'
        )
    if info['sampwidth'] != 2:
        raise ValueError(
            f'WAV is {info["sampwidth"] * 8}-bit; Google STT needs 16-bit PCM. '
            'Re-export as 16-bit PCM WAV or use MP3.'
        )
    if info['channels'] > 2:
        raise ValueError('Too many audio channels; use mono or stereo WAV/MP3.')
    return info


def _mp3_probe(audio_bytes: bytes) -> Dict[str, Any]:
    """Duration + channel count for MP3 (matches Console: stereo 44100 is common)."""
    out: Dict[str, Any] = {'length': None, 'channels': None}
    try:
        from mutagen.mp3 import MP3

        audio = MP3(io.BytesIO(audio_bytes))
        info = audio.info
        if info is not None:
            if getattr(info, 'length', None):
                out['length'] = float(info.length)
            ch = getattr(info, 'channels', None)
            if ch is not None:
                out['channels'] = int(ch)
    except Exception as e:
        logger.debug('MP3 probe failed: %s', e)
    return out


def _build_mp3_configs(
    speech,
    *,
    channel_count: Optional[int],
    models: Sequence[Optional[str]] = _AM_ET_V1_MODELS,
) -> List:
    """RecognitionConfig list for am-ET on STT v1 (default / command_and_search only)."""
    enc = speech.RecognitionConfig.AudioEncoding.MP3
    base_kw = dict(
        encoding=enc,
        language_code='am-ET',
        alternative_language_codes=['en-US'],
        enable_automatic_punctuation=True,
    )
    configs = []

    def add(model: Optional[str], with_channels: bool):
        kw = dict(base_kw)
        if model:
            kw['model'] = model
        if with_channels and channel_count in (1, 2):
            kw['audio_channel_count'] = channel_count
        configs.append(speech.RecognitionConfig(**kw))

    for m in models:
        add(m, False)
        if channel_count in (1, 2):
            add(m, True)
    return configs


def _build_wav_configs(
    speech,
    wav_info: Dict[str, Any],
    models: Sequence[Optional[str]] = _AM_ET_V1_MODELS,
) -> List:
    enc = speech.RecognitionConfig.AudioEncoding.LINEAR16
    ch = wav_info['channels']
    rate = wav_info['rate']
    configs = []
    base_kw = dict(
        encoding=enc,
        sample_rate_hertz=rate,
        language_code='am-ET',
        alternative_language_codes=['en-US'],
        enable_automatic_punctuation=True,
    )
    for m in models:
        kw = dict(base_kw)
        if m:
            kw['model'] = m
        configs.append(speech.RecognitionConfig(**kw))
        if ch in (1, 2):
            kw_ch = dict(kw)
            kw_ch['audio_channel_count'] = ch
            configs.append(speech.RecognitionConfig(**kw_ch))
    return configs


def transcribe_amharic(
    audio_bytes: bytes,
    ext: str,
    duration_seconds: Optional[float] = None,
) -> Tuple[str, Optional[float], dict]:
    """
    Returns (transcript, confidence_0_1_or_none, meta_dict).

    Order: **STT v2 (Chirp)** first — matches Cloud Console behavior for am-ET; then **v1** fallback.
    Set ``STT_DISABLE_V2=1`` to force v1 only. Set ``GOOGLE_CLOUD_STT_V2_LOCATION`` (default ``us-central1``).
    """
    try:
        from google.cloud import speech
    except ImportError as e:
        raise RuntimeError('google-cloud-speech is not installed') from e

    ext = (ext or '').lower().lstrip('.')
    meta: dict = {'provider': 'google_speech', 'format': ext or 'unknown'}

    dur = duration_seconds
    mp3_probe: Dict[str, Any] = {}
    wav_info: Optional[Dict[str, Any]] = None
    ch: Optional[int] = None

    if ext in ('mp3', 'mpeg', 'webm'):
        if dur is None:
            mp3_probe = _mp3_probe(audio_bytes)
            dur = mp3_probe.get('length')
        ch = mp3_probe.get('channels') if mp3_probe else _mp3_probe(audio_bytes).get('channels')
    else:
        wav_info = _inspect_wav(audio_bytes)
        if dur is None and wav_info.get('rate') and wav_info.get('frames') is not None:
            try:
                dur = wav_info['frames'] / float(wav_info['rate'])
            except Exception:
                pass
        ch = wav_info.get('channels')

    if dur is not None:
        meta['duration_seconds'] = dur
    if ch is not None:
        if ext in ('mp3', 'mpeg', 'webm'):
            meta['mp3_channels'] = ch
        else:
            meta['wav'] = {
                'sample_rate_hz': wav_info['rate'],
                'channels': wav_info['channels'],
            }

    stereo = ch == 2
    meta['stt_model_preference'] = (
        'v2 (global: long only; regional: long then chirp_2) then v1 am-ET'
    )

    v2_text, v2_conf = _try_stt_v2(audio_bytes, meta, stereo=stereo)
    if (v2_text or '').strip():
        return v2_text.strip(), v2_conf, meta

    meta['stt_api'] = meta.get('stt_api') or 'v1'
    meta['stt_models_tried'] = [m or '(unset)' for m in _AM_ET_V1_MODELS]

    client = speech.SpeechClient()
    if ext in ('mp3', 'mpeg', 'webm'):
        configs_to_try = _build_mp3_configs(speech, channel_count=ch)
    else:
        configs_to_try = _build_wav_configs(speech, wav_info)

    audio = speech.RecognitionAudio(content=audio_bytes)

    def _response_has_words(resp) -> bool:
        if not resp.results:
            return False
        for res in resp.results:
            if not res.alternatives:
                continue
            if (res.alternatives[0].transcript or '').strip():
                return True
        return False

    response = None
    last_err = None
    last_empty_response = None
    for i, cfg in enumerate(configs_to_try):
        try:
            resp = client.recognize(config=cfg, audio=audio)
            meta['stt_attempt'] = i + 1
            if i > 0:
                meta['stt_retry'] = f'config_variant_{i + 1}'
            if _response_has_words(resp):
                response = resp
                break
            last_empty_response = resp
            logger.info(
                'Speech v1 recognize attempt %s returned no words; trying next config if any',
                i + 1,
            )
        except Exception as e:
            last_err = e
            logger.warning('Speech v1 recognize attempt %s failed: %s', i + 1, e)

    if response is None:
        if last_empty_response is not None:
            response = last_empty_response
        else:
            logger.exception('Google Speech v1 recognize failed after retries: %s', last_err)
            meta['error'] = str(last_err)[:500] if last_err else 'unknown'
            raise last_err

    if not response.results:
        meta['empty'] = True
        meta['hint'] = (
            'No words from v1 after v2. Confirm GOOGLE_CLOUD_PROJECT, global STT v2, '
            'Speech-to-Text API enabled, and audio is clear Amharic.'
        )
        return '', None, meta

    parts = []
    confidences = []
    for res in response.results:
        if not res.alternatives:
            continue
        alt = res.alternatives[0]
        parts.append(alt.transcript)
        if alt.confidence:
            confidences.append(alt.confidence)

    text = ' '.join(parts).strip()
    avg_conf = sum(confidences) / len(confidences) if confidences else None
    meta['alternatives'] = len(response.results)
    if not text:
        meta['empty'] = True
        meta['hint'] = (
            'API returned empty transcript on v1. v2 was tried first; check stt_v2_* in metadata.'
        )
    return text, avg_conf, meta
