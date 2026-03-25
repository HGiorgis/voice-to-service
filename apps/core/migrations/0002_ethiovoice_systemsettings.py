# Voice To Service: replace KYC image fields with voice/audio settings

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_settings_and_submitted_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='default_daily_voice_limit',
            field=models.IntegerField(
                default=3,
                help_text='Max Voice To Service audio processes per user per calendar day',
            ),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='max_audio_duration_seconds',
            field=models.FloatField(
                default=20.0,
                help_text='Reject uploads longer than this (seconds)',
            ),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='max_audio_size_mb',
            field=models.FloatField(default=10.0),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='allowed_audio_formats',
            field=models.CharField(
                default='wav,mp3,mpeg',
                help_text='Comma-separated extensions (no dots)',
                max_length=128,
            ),
        ),
        migrations.AlterField(
            model_name='systemsettings',
            name='default_daily_limit',
            field=models.IntegerField(default=10000),
        ),
        migrations.AlterField(
            model_name='systemsettings',
            name='default_monthly_limit',
            field=models.IntegerField(default=300000),
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='approve_threshold',
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='reject_threshold',
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='auto_approve_high_confidence',
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='max_image_size_mb',
        ),
        migrations.RemoveField(
            model_name='systemsettings',
            name='allowed_image_formats',
        ),
    ]
