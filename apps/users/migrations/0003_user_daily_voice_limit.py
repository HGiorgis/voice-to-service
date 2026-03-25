# Generated manually for Voice To Service

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_alter_user_options_user_daily_request_limit_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='daily_voice_limit',
            field=models.IntegerField(default=3),
        ),
    ]
