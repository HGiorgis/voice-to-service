# Generated manually for Voice To Service

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VoiceProcessingRequest',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('processing', 'Processing'),
                            ('completed', 'Completed'),
                            ('failed', 'Failed'),
                        ],
                        db_index=True,
                        default='processing',
                        max_length=20,
                    ),
                ),
                ('amharic_text', models.TextField(blank=True)),
                ('english_text', models.TextField(blank=True)),
                (
                    'category',
                    models.CharField(blank=True, db_index=True, max_length=32),
                ),
                ('confidence', models.FloatField(blank=True, null=True)),
                ('raw_classification', models.TextField(blank=True)),
                ('error_message', models.TextField(blank=True)),
                (
                    'audio_duration_seconds',
                    models.FloatField(blank=True, null=True),
                ),
                ('pipeline_metadata', models.JSONField(blank=True, default=dict)),
                (
                    'created_at',
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='voice_requests',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='voiceprocessingrequest',
            index=models.Index(
                fields=['user', '-created_at'],
                name='voice_voicep_user_id_7b8c9d_idx',
            ),
        ),
    ]
