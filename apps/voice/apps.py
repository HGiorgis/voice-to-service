from django.apps import AppConfig


class VoiceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.voice'
    label = 'voice'
    verbose_name = 'Voice To Service'
