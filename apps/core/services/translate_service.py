"""Google Cloud Translation (Amharic → English)."""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def translate_to_english(text: str) -> Tuple[str, dict]:
    """Returns (english_text, meta)."""
    if not (text or '').strip():
        return '', {'provider': 'google_translate', 'skipped': True}

    try:
        from google.cloud import translate_v2 as translate
    except ImportError as e:
        raise RuntimeError('google-cloud-translate is not installed') from e

    client = translate.Client()
    result = client.translate(text, target_language='en')
    translated = (result.get('translatedText') or '').strip()
    meta = {
        'provider': 'google_translate',
        'detected_source_language': result.get('detectedSourceLanguage'),
    }
    return translated, meta
