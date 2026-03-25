Drop sample audio here for integration tests, or use env vars:

  STT_TEST_AUDIO=C:\path\to\one\file.mp3     (single file)
  STT_TEST_AUDIO_DIR=C:\path\to\folder      (all .mp3 / .wav / .mpeg in folder)

Default scan location when those are unset: this directory (tests/fixtures/audio).

Integration tests require Google Cloud credentials (e.g. GOOGLE_APPLICATION_CREDENTIALS).
