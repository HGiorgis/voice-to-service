from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0005_registrationattempt_browser_family_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='antiabusesettings',
            name='oauth_signup_antiabuse_enabled',
            field=models.BooleanField(
                default=True,
                help_text='When on, new Google OAuth accounts use the same registration limits (IP, fingerprint, disposable email, rapid window, device cookie). Existing Google users are unaffected.',
            ),
        ),
    ]
