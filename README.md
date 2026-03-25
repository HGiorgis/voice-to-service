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

Prerequisites: `.env` at the project root (copy from `.env.example`). For Postgres or hosted DB, set `DATABASE_URL`. For the full voice pipeline, set `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GEMINI_API_KEY` (paths inside the container must match a **mounted** credentials file, or bake only non-secret config into the image).

**Recommended (Compose):**

```bash
cd voice-to-service
cp .env.example .env
# Edit .env — at minimum SECRET_KEY, DATABASE_URL, GCP, Gemini, OAuth if used
docker compose up -d --build
```

- **Image:** `python:3.11-slim`, installs `requirements-docker.txt`, runs `collectstatic` at build, starts with `migrate` → `create_default_admin` → **Daphne** on port 8000.
- **Compose** bind-mounts the project for development and persists `media` / `staticfiles` in named volumes.
- Default URL: [http://localhost:8000](http://localhost:8000).

**Single container (no Compose):**

```bash
docker build -t voice-to-service .
docker run --rm -p 8000:8000 --env-file .env \
  -v "%cd%/media:/app/media" voice-to-service
```

(On Linux/macOS, replace the media volume with `$(pwd)/media:/app/media`.)

If another ERAS service already uses port 8000, change the host port in `docker-compose.yml` (e.g. `"8001:8000"`).

## License

Use freely for portfolio or product work; configure your own GCP/Gemini billing and keys.
