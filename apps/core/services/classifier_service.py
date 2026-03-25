"""Emergency intent classification via Google Gemini (temporary; replace with custom ML later)."""
import json
import logging
import os
import re
from typing import Tuple

from django.conf import settings

logger = logging.getLogger(__name__)

VALID = {'Medical', 'Police', 'Fire', 'None'}


def classify_emergency_intent(english_text: str) -> Tuple[str, float, str, dict]:
    """
    Returns (category, confidence_0_1, raw_text_or_json, meta).
    category is one of Medical, Police, Fire, None.
    """
    text = (english_text or '').strip()
    if not text:
        return (
            'None',
            0.0,
            'Skipped: no English text (usually because speech-to-text returned nothing).',
            {'skipped': True},
        )

    api_key = getattr(settings, 'GEMINI_API_KEY', None) or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        logger.warning('GEMINI_API_KEY not set; returning None')
        return 'None', 0.0, 'GEMINI_API_KEY not configured', {'error': 'no_api_key'}

    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError('google-generativeai is not installed') from e

    model_name = getattr(settings, 'GEMINI_MODEL', None) or os.environ.get(
        'GEMINI_MODEL', 'gemini-2.0-flash'
    )
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    prompt = f"""You classify short user utterances for an emergency routing system.
Choose exactly ONE category: Medical, Police, Fire, or None.
- Medical: health injury, illness, ambulance, hospital, bleeding, unconscious, etc.
- Police: crime, violence, theft, assault, danger from people, etc.
- Fire: fire, smoke, burning building, explosion fire-related, etc.
- None: not clearly any of the above or general chat.

Return ONLY a compact JSON object with keys:
- "category": one of "Medical", "Police", "Fire", "None"
- "confidence": number between 0 and 1
- "raw_reason": one short phrase

English text to classify:
{text}
"""

    try:
        response = model.generate_content(prompt)
    except Exception as e:
        err = str(e)
        low = err.lower()
        is_quota = (
            '429' in err
            or 'quota' in low
            or 'resource exhausted' in low
            or 'rate limit' in low
        )
        try:
            from google.api_core import exceptions as ge

            if isinstance(e, ge.ResourceExhausted):
                is_quota = True
        except ImportError:
            pass

        if is_quota:
            logger.warning('Gemini quota/rate limit (classification skipped): %s', err[:400])
            return (
                'None',
                0.0,
                'Classification skipped: Gemini quota or rate limit exceeded. Retry later or check billing.',
                {
                    'skipped': True,
                    'error': 'quota_exceeded',
                    'provider': 'gemini',
                    'model': model_name,
                    'detail': err[:1500],
                },
            )

        logger.exception('Gemini generate_content failed: %s', e)
        return (
            'None',
            0.0,
            f'Classification skipped: {err[:600]}',
            {
                'skipped': True,
                'error': 'api_error',
                'provider': 'gemini',
                'model': model_name,
                'detail': err[:1500],
            },
        )

    raw = (response.text or '').strip()

    # Strip ```json fences if present
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw, re.IGNORECASE)
    payload = m.group(1) if m else raw

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # try to find first {...}
        brace = re.search(r'\{[\s\S]*\}', raw)
        if brace:
            try:
                data = json.loads(brace.group(0))
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

    cat = str(data.get('category', 'None')).strip()
    if cat not in VALID:
        # loose match
        low = cat.lower()
        for v in VALID:
            if v.lower() == low:
                cat = v
                break
        else:
            cat = 'None'

    try:
        conf = float(data.get('confidence', 0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    reason = str(data.get('raw_reason', ''))[:500]
    return cat, conf, raw[:2000], {'provider': 'gemini', 'model': model_name, 'raw_reason': reason}
