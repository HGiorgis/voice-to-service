"""Celery tasks for voice pipeline (test console background jobs)."""
import logging
from types import SimpleNamespace

from celery import shared_task
from apps.core.voice_temp_storage import get_voice_temp_storage, normalize_temp_audio_name
from django.core.files.uploadedfile import SimpleUploadedFile

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True)
def run_voice_pipeline_task(self, voice_request_id: str) -> None:
    from apps.api.views.voice_views import iter_voice_pipeline_events
    from apps.authentication.models import APIKey
    from apps.core.services.audio_utils import extension_from_filename
    from apps.voice.models import VoiceProcessingRequest

    req = VoiceProcessingRequest.objects.select_related('user').get(pk=voice_request_id)
    user = req.user
    try:
        api_key = user.api_key
    except APIKey.DoesNotExist:
        api_key = None

    if not api_key:
        req.status = VoiceProcessingRequest.Status.FAILED
        req.error_message = 'No API key configured for this user.'
        req.save(update_fields=['status', 'error_message'])
        return

    md = dict(req.pipeline_metadata or {})
    rel = normalize_temp_audio_name(md.get('temp_audio_path') or '')
    if not rel:
        req.status = VoiceProcessingRequest.Status.FAILED
        req.error_message = 'Missing temp audio path for background job.'
        req.save(update_fields=['status', 'error_message'])
        return

    storage = get_voice_temp_storage()
    final_status = None
    final_payload = None

    try:
        try:
            with storage.open(rel, 'rb') as fh:
                raw = fh.read()
        except Exception as e:
            logger.exception('Could not read temp audio %s', rel)
            req.status = VoiceProcessingRequest.Status.FAILED
            req.error_message = str(e)[:2000]
            req.save(update_fields=['status', 'error_message'])
            return

        fname = md.get('filename') or 'audio.webm'
        ext = extension_from_filename(fname) or 'webm'
        ctype = 'audio/webm' if ext == 'webm' else 'audio/mpeg'
        if ext in ('wav',):
            ctype = 'audio/wav'
        audio = SimpleUploadedFile(fname, raw, content_type=ctype)

        fake_request = SimpleNamespace(
            META={'REMOTE_ADDR': '127.0.0.1', 'HTTP_USER_AGENT': 'Celery/VoicePipeline'},
            FILES={},
        )

        req.amharic_text = ''
        req.english_text = ''
        req.category = ''
        req.confidence = None
        req.raw_classification = ''
        req.save(
            update_fields=[
                'amharic_text',
                'english_text',
                'category',
                'confidence',
                'raw_classification',
            ]
        )

        gen = iter_voice_pipeline_events(
            fake_request,
            user,
            api_key,
            '/celery/voice/',
            audio=audio,
            existing_request=req,
            skip_quota_check=True,
            persist_each_log=True,
        )

        for ev in gen:
            if ev['type'] == 'final':
                final_status = ev['status']
                final_payload = ev['payload']
    finally:
        try:
            storage.delete(rel)
        except Exception as ex:
            logger.debug('Temp audio delete skipped: %s', ex)

    req.refresh_from_db()
    if req.status == VoiceProcessingRequest.Status.PROCESSING:
        req.status = VoiceProcessingRequest.Status.FAILED
        pl = final_payload or {}
        em = pl.get('error') or pl.get('detail') or 'Pipeline ended without completion.'
        req.error_message = str(em)[:2000]
        req.save(update_fields=['status', 'error_message'])

    req.refresh_from_db()
    m2 = dict(req.pipeline_metadata or {})
    m2.pop('temp_audio_path', None)
    req.pipeline_metadata = m2
    req.save(update_fields=['pipeline_metadata'])

    if final_status and final_status >= 400:
        logger.warning(
            'Voice pipeline job %s finished with HTTP %s', voice_request_id, final_status
        )
