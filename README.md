# Voice To Service — Voice Intelligence & Classification API

Django microservice that turns **Amharic audio** into structured data:

1. **Speech-to-text** (Google Cloud, `am-ET`)
2. **Translation** to English (Google Cloud Translation)
3. **Intent classification** — `Medical` | `Police` | `Fire` | `None` (Google Gemini, swappable later)

**Main endpoint:** `POST /api/v1/process-audio/` (multipart, field `audio` — WAV/MP3)

**Auth:** `X-API-Key: <key>` or `Authorization: Bearer <key>`

**Limits (configurable):**

- Per-user **daily voice cap** (default **3** requests/day)
- **Max duration** per file (default **20s**) and **max size** (default **10 MB**)

## Quick start

```bash
cd voice-to-service
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env     # set SECRET_KEY, DATABASE_URL, GOOGLE_APPLICATION_CREDENTIALS, GEMINI_API_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Register a user → generate API key from the dashboard → call `process-audio` or use **Test audio** in the sidebar.

## Environment variables

See `.env.example`. Required for full pipeline:

- `GOOGLE_APPLICATION_CREDENTIALS` — path to GCP service account JSON (Speech + Translation enabled)
- `GEMINI_API_KEY` — Gemini API key for classification

## Project layout

- `apps/voice/` — `VoiceProcessingRequest` log model
- `apps/api/` — REST API + API key auth
- `apps/core/services/` — `speech_service`, `translate_service`, `classifier_service`, `audio_utils`
- `templates/` — purple “Web3” themed UI (`static/css/voice-to-service-theme.css`)

## Docker

```bash
docker build -t voice-to-service .
docker run -p 8000:8000 --env-file .env voice-to-service
```

## License

Use freely for portfolio or product work; configure your own GCP/Gemini billing and keys.
