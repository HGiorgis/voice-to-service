"""Voice To Service — POST /api/v1/process-audio"""
import logging
import time
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.authentication import APIKeyAuthentication
from apps.api.pipeline_log_utils import append_log, log_api_call, pretty_json
from apps.core.models import SystemSettings
from apps.core.services.audio_utils import extension_from_filename, validate_audio_upload
from apps.core.services.classifier_service import classify_emergency_intent
from apps.core.services.speech_service import transcribe_amharic
from apps.core.services.translate_service import translate_to_english
from apps.voice.models import VoiceProcessingRequest

logger = logging.getLogger(__name__)


def _merge_req_pipeline_metadata(req: VoiceProcessingRequest, patch: Dict[str, Any]) -> None:
    """Preserve async keys (e.g. temp_audio_path) when saving STT/classifier metadata."""
    base = dict(req.pipeline_metadata or {})
    base.update(patch)
    req.pipeline_metadata = base


def _finalize(
    request,
    api_key,
    endpoint: str,
    start: float,
    pipeline_log: List[dict],
    resp_status: int,
    payload: Dict[str, Any],
    record_usage: bool = True,
) -> Tuple[int, Dict[str, Any]]:
    elapsed = time.time() - start
    log_api_call(request, api_key, endpoint, 'POST', resp_status, elapsed)
    if 'pipeline_log' not in payload and pipeline_log:
        payload['pipeline_log'] = pipeline_log
    if api_key and record_usage and resp_status != 429:
        try:
            api_key.record_usage()
        except Exception:
            pass
    return resp_status, payload


def iter_voice_pipeline_events(
    request,
    user,
    api_key,
    endpoint: str,
    audio=None,
    *,
    existing_request: Optional[VoiceProcessingRequest] = None,
    skip_quota_check: bool = False,
    persist_each_log: bool = False,
) -> Iterator[Dict[str, Any]]:
    """
    Yields {'type': 'log', 'entry': {...}} for each pipeline step, then
    {'type': 'final', 'status': int, 'payload': dict}.

    ``existing_request``: pre-created row (e.g. async job); skips ``objects.create``.
    ``skip_quota_check``: set True when quota was checked before enqueue (Celery worker).
    ``persist_each_log``: save ``pipeline_log`` to the DB row after each log line (background jobs).
    """
    start = time.time()
    pipeline_log: List[dict] = []
    req: Optional[VoiceProcessingRequest] = existing_request

    def _flush_pipeline_log() -> None:
        if not persist_each_log or req is None:
            return
        _merge_req_pipeline_metadata(req, {'pipeline_log': [dict(x) for x in pipeline_log]})
        req.save(update_fields=['pipeline_metadata'])

    if not skip_quota_check:
        ok, msg = user.check_voice_daily_limit()
    else:
        ok, msg = True, ''

    if not ok:
        append_log(pipeline_log, 'quota', 'Daily voice limit', 'error', msg)
        st, pl = _finalize(
            request,
            api_key,
            endpoint,
            start,
            pipeline_log,
            429,
            {'error': msg, 'code': 'voice_daily_limit_exceeded', 'pipeline_log': pipeline_log},
            record_usage=False,
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()
        yield {'type': 'final', 'status': st, 'payload': pl}
        return

    if audio is None:
        audio = request.FILES.get('audio') or request.FILES.get('file')
    if not audio:
        append_log(
            pipeline_log,
            'input',
            'Missing file',
            'error',
            'No multipart field "audio" or "file".',
        )
        st, pl = _finalize(
            request,
            api_key,
            endpoint,
            start,
            pipeline_log,
            400,
            {
                'error': 'Missing audio file. Use multipart field "audio" or "file".',
                'code': 'missing_audio',
                'pipeline_log': pipeline_log,
            },
            record_usage=False,
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()
        yield {'type': 'final', 'status': st, 'payload': pl}
        return

    settings_obj = SystemSettings.get_settings()
    allowed = settings_obj.allowed_audio_formats_list()
    if not allowed:
        allowed = ['wav', 'mp3', 'mpeg','webm']

    fname = getattr(audio, 'name', '') or '(upload)'
    ok_val, err, duration = validate_audio_upload(
        audio,
        max_size_mb=float(settings_obj.max_audio_size_mb),
        max_duration_seconds=float(settings_obj.max_audio_duration_seconds),
        allowed_extensions=allowed,
    )
    if not ok_val:
        append_log(
            pipeline_log,
            'validate',
            'Upload validation',
            'error',
            [
                f'File: {fname}',
                f'Allowed: {", ".join(sorted(allowed))}',
                f'Error: {err}',
            ],
        )
        if req is not None:
            req.status = VoiceProcessingRequest.Status.FAILED
            req.error_message = (err or 'invalid_audio')[:2000]
            _merge_req_pipeline_metadata(req, {'pipeline_log': [dict(x) for x in pipeline_log]})
            req.save(update_fields=['status', 'error_message', 'pipeline_metadata'])
        st, pl = _finalize(
            request,
            api_key,
            endpoint,
            start,
            pipeline_log,
            400,
            {'error': err, 'code': 'invalid_audio', 'pipeline_log': pipeline_log},
            record_usage=False,
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()
        yield {'type': 'final', 'status': st, 'payload': pl}
        return

    ext = extension_from_filename(fname)
    size_bytes = getattr(audio, 'size', None)
    if size_bytes is None:
        try:
            audio.seek(0, 2)
            size_bytes = audio.tell()
            audio.seek(0)
        except Exception:
            size_bytes = 0

    append_log(
        pipeline_log,
        'validate',
        'Upload validated',
        'ok',
        [
            f'File name: {fname}',
            f'Extension: .{ext or "?"}',
            f'Duration (detected): {duration:.2f}s' if duration is not None else 'Duration: n/a',
            f'Size: {size_bytes} bytes',
            f'Limits: max {settings_obj.max_audio_duration_seconds}s, {settings_obj.max_audio_size_mb} MB',
        ],
    )
    yield {'type': 'log', 'entry': pipeline_log[-1]}

    if existing_request is not None:
        req.status = VoiceProcessingRequest.Status.PROCESSING
        req.error_message = ''
        md = dict(req.pipeline_metadata or {})
        md['filename'] = fname[:255]
        req.pipeline_metadata = md
        req.audio_duration_seconds = duration
        req.save(
            update_fields=[
                'status',
                'error_message',
                'pipeline_metadata',
                'audio_duration_seconds',
            ]
        )
    else:
        req = VoiceProcessingRequest.objects.create(
            user=user,
            status=VoiceProcessingRequest.Status.PROCESSING,
            audio_duration_seconds=duration,
            pipeline_metadata={'filename': fname[:255]},
        )

    _flush_pipeline_log()

    try:
        audio.seek(0)
        raw_bytes = audio.read()
    except Exception as e:
        req.status = VoiceProcessingRequest.Status.FAILED
        req.error_message = str(e)
        req.save(update_fields=['status', 'error_message'])
        append_log(pipeline_log, 'read', 'Read upload bytes', 'error', str(e))
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()
        st, pl = _finalize(
            request,
            api_key,
            endpoint,
            start,
            pipeline_log,
            500,
            {'error': 'Could not read upload', 'code': 'read_error', 'pipeline_log': pipeline_log},
        )
        yield {'type': 'final', 'status': st, 'payload': pl}
        return

    append_log(
        pipeline_log,
        'read',
        'Audio loaded',
        'ok',
        f'Read {len(raw_bytes)} bytes into memory (request_id={req.id}).',
    )
    yield {'type': 'log', 'entry': pipeline_log[-1]}
    _flush_pipeline_log()

    meta: Dict[str, Any] = {'request_id': str(req.id), 'pipeline_log': pipeline_log}

    try:
        append_log(
            pipeline_log,
            'stt',
            'Google Speech-to-Text',
            'info',
                [
                'Language: am-ET (primary), en-US (alternative)',
                'STT: v2 global (model long, am-ET) then v1 if needed.',
                'Calling recognize() …',
            ],
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        try:
            amharic, stt_conf, stt_meta = transcribe_amharic(
                raw_bytes, ext, duration_seconds=float(duration) if duration is not None else None
            )
        except ValueError as ve:
            req.status = VoiceProcessingRequest.Status.FAILED
            req.error_message = str(ve)
            meta['speech'] = {'error': str(ve)}
            meta['pipeline_log'] = pipeline_log
            _merge_req_pipeline_metadata(req, meta)
            req.save(update_fields=['status', 'error_message', 'pipeline_metadata'])
            append_log(
                pipeline_log,
                'stt',
                'Speech-to-Text · WAV/MP3 format',
                'error',
                [str(ve), 'Fix: 16-bit PCM WAV or MP3 (see Audacity export).'],
            )
            yield {'type': 'log', 'entry': pipeline_log[-1]}
            _flush_pipeline_log()
            st, pl = _finalize(
                request,
                api_key,
                endpoint,
                start,
                pipeline_log,
                400,
                {
                    'error': str(ve),
                    'code': 'invalid_audio_format',
                    'request_id': str(req.id),
                    'warnings': [
                        'Use 16-bit PCM WAV (uncompressed) or MP3. '
                        'In Audacity: Export → WAV → Signed 16-bit PCM.',
                    ],
                    'pipeline_log': pipeline_log,
                },
            )
            yield {'type': 'final', 'status': st, 'payload': pl}
            return

        meta['speech'] = dict(stt_meta)
        if stt_conf is not None:
            meta['speech']['confidence'] = stt_conf

        stt_status = 'warn' if stt_meta.get('empty') or not (amharic or '').strip() else 'ok'
        stt_meta_for_log = {k: v for k, v in stt_meta.items() if k != 'hint'}
        if stt_meta.get('hint'):
            stt_meta_for_log['hint'] = stt_meta['hint']
        stt_lines = [
            f'Transcript: {(amharic or "").strip() or "(empty)"}',
            f'STT confidence: {stt_conf}' if stt_conf is not None else 'STT confidence: n/a',
            'Provider metadata:',
            pretty_json(stt_meta_for_log),
        ]
        if stt_meta.get('stt_attempt', 1) > 1:
            stt_lines.insert(
                1,
                f'Note: STT used attempt {stt_meta.get("stt_attempt")} '
                f'({stt_meta.get("stt_retry", "alternate config")}).',
            )
        append_log(pipeline_log, 'stt', 'Speech-to-Text · result', stt_status, stt_lines)
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        warnings = []
        if stt_meta.get('hint'):
            warnings.append(stt_meta['hint'])
        if stt_meta.get('empty'):
            warnings.append(
                'Speech-to-Text returned no words — English translation and Gemini '
                'classification receive empty input, so category stays "None".'
            )

        append_log(
            pipeline_log,
            'translate',
            'Google Translate (→ English)',
            'info',
            [
                'Input (Amharic / detected):',
                (amharic or '').strip() or '(empty — API skipped)',
            ],
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        english, tr_meta = translate_to_english(amharic)
        meta['translate'] = tr_meta

        tr_status = 'skip' if tr_meta.get('skipped') else 'ok'
        tr_lines = [
            f'Output (English): {(english or "").strip() or "(empty)"}',
            'API metadata:',
            pretty_json(tr_meta),
        ]
        append_log(pipeline_log, 'translate', 'Translation · result', tr_status, tr_lines)
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        if tr_meta.get('skipped'):
            warnings.append('Translation skipped because the transcript was empty.')

        append_log(
            pipeline_log,
            'classify',
            'Gemini · intent classification',
            'info',
            [
                'Input to model (English):',
                (english or '').strip() or '(empty — classifier will skip)',
            ],
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        category, conf, raw_cls, clf_meta = classify_emergency_intent(english)
        meta['classifier'] = clf_meta
        if clf_meta.get('skipped') and not (raw_cls or '').strip():
            raw_cls = 'Classifier skipped: no English text (fix speech-to-text first).'
        elif clf_meta.get('error') == 'no_api_key':
            warnings.append('GEMINI_API_KEY is missing — set it in .env to enable classification.')
        elif clf_meta.get('error') == 'quota_exceeded':
            warnings.append(
                'Gemini classification skipped (quota/rate limit). Speech-to-text and translation still succeeded.'
            )
        elif clf_meta.get('error') == 'api_error':
            warnings.append('Gemini classification failed; speech-to-text and translation are unchanged.')

        clf_status = 'skip' if clf_meta.get('skipped') else ('warn' if clf_meta.get('error') else 'ok')
        clf_lines = [
            f'Category: {category}',
            f'Confidence: {conf}',
            'Raw / reason:',
            (raw_cls or '')[:4000] or '(none)',
            'Classifier metadata:',
            pretty_json(clf_meta),
        ]
        append_log(pipeline_log, 'classify', 'Gemini · result', clf_status, clf_lines)
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        req.amharic_text = amharic
        req.english_text = english
        req.category = category
        req.confidence = conf
        req.raw_classification = raw_cls
        req.status = VoiceProcessingRequest.Status.COMPLETED

        ts = datetime.now(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        append_log(
            pipeline_log,
            'done',
            'Pipeline complete',
            'ok',
            [
                f'Final: category={category}, confidence={conf}',
                f'Timestamp: {ts}',
            ],
        )
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()

        meta['pipeline_log'] = pipeline_log
        _merge_req_pipeline_metadata(req, meta)
        req.save()

        body = {
            'amharic_text': amharic,
            'english_text': english,
            'category': category,
            'confidence': round(conf, 4) if conf is not None else None,
            'raw_classification': raw_cls,
            'timestamp': ts,
            'request_id': str(req.id),
            'pipeline_log': pipeline_log,
        }
        if warnings:
            body['warnings'] = warnings
        st, pl = _finalize(request, api_key, endpoint, start, pipeline_log, 200, body)
        yield {'type': 'final', 'status': st, 'payload': pl}

    except Exception as e:
        logger.exception('process-audio failed: %s', e)
        req.status = VoiceProcessingRequest.Status.FAILED
        req.error_message = str(e)[:2000]
        meta['pipeline_log'] = pipeline_log
        _merge_req_pipeline_metadata(req, meta)
        req.save(update_fields=['status', 'error_message', 'pipeline_metadata'])
        append_log(pipeline_log, 'error', 'Pipeline exception', 'error', str(e))
        yield {'type': 'log', 'entry': pipeline_log[-1]}
        _flush_pipeline_log()
        st, pl = _finalize(
            request,
            api_key,
            endpoint,
            start,
            pipeline_log,
            502,
            {
                'error': 'Voice pipeline failed',
                'detail': str(e),
                'code': 'pipeline_error',
                'request_id': str(req.id),
                'pipeline_log': pipeline_log,
            },
        )
        yield {'type': 'final', 'status': st, 'payload': pl}


def process_voice_request(request, user, api_key, endpoint: str, audio=None) -> Response:
    """
    Shared pipeline for API and dashboard test console.
    `audio`: optional UploadedFile; if None, reads request.FILES audio/file.
    """
    final_status: Optional[int] = None
    final_payload: Optional[Dict[str, Any]] = None
    for ev in iter_voice_pipeline_events(request, user, api_key, endpoint, audio=audio):
        if ev['type'] == 'final':
            final_status = ev['status']
            final_payload = ev['payload']
    if final_status is None or final_payload is None:
        return Response({'error': 'Pipeline did not complete', 'code': 'internal'}, status=500)
    return Response(final_payload, status=final_status)


class ProcessAudioView(APIView):
    """
    Accept multipart audio (wav/mp3), return Amharic text, English text, and emergency category.
    Auth: X-API-Key or Authorization: Bearer <key>
    """

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        endpoint = request.path or '/api/v1/process-audio/'
        return process_voice_request(request, request.user, request.auth, endpoint)
