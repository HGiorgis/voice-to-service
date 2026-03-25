import uuid
from django.conf import settings
from django.db import models


class VoiceProcessingRequest(models.Model):
    """Log of each voice intelligence API call (Amharic STT → EN → classification)."""

    class Status(models.TextChoices):
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='voice_requests',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
        db_index=True,
    )
    amharic_text = models.TextField(blank=True)
    english_text = models.TextField(blank=True)
    category = models.CharField(max_length=32, blank=True, db_index=True)
    confidence = models.FloatField(null=True, blank=True)
    raw_classification = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    audio_duration_seconds = models.FloatField(null=True, blank=True)
    pipeline_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f'{self.user_id} @ {self.created_at:%Y-%m-%d} ({self.status})'
