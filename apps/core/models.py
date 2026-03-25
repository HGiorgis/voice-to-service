from django.db import models


class SystemSettings(models.Model):
    """Singleton-style system settings (one row). Admin can update."""

    # Rate limits (defaults for new users — general API / logging)
    default_daily_limit = models.IntegerField(default=10000)
    default_monthly_limit = models.IntegerField(default=300000)
    # Voice-specific defaults
    default_daily_voice_limit = models.IntegerField(
        default=3,
        help_text='Max Voice To Service audio processes per user per calendar day',
    )
    # API key
    key_expiry_days = models.IntegerField(default=365)
    require_approval_new_keys = models.BooleanField(default=False)
    # Audio / Voice To Service
    max_audio_duration_seconds = models.FloatField(
        default=20.0,
        help_text='Reject uploads longer than this (seconds)',
    )
    max_audio_size_mb = models.FloatField(default=10.0)
    allowed_audio_formats = models.CharField(
        max_length=128,
        default='wav,mp3,mpeg,webm',
        help_text='Comma-separated extensions (no dots)',
    )
    # Security
    session_timeout_minutes = models.IntegerField(default=30)
    force_2fa_admin = models.BooleanField(default=False)
    ip_whitelist_enabled = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'System settings'
        verbose_name_plural = 'System settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={})
        return obj

    def allowed_audio_formats_list(self):
        """
        Parsed extensions for validation. ``webm`` is always included so browser
        recordings work even if the DB row predates WebM support.
        """
        parts = [
            x.strip().lower().lstrip('.')
            for x in (self.allowed_audio_formats or '').split(',')
            if x.strip()
        ]
        if not parts:
            parts = ['wav', 'mp3', 'mpeg', 'webm']
        elif 'webm' not in parts:
            parts = list(parts) + ['webm']
        return parts
