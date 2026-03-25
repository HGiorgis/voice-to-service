from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_antiabuse_and_blocking'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='email_verification_code_hash',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='user',
            name='email_verification_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='email_verification_sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
