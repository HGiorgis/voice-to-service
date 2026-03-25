# Fix: key_preview is set to key[:8]+'...' (11 chars) but was max_length=8

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0002_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apikey',
            name='key_preview',
            field=models.CharField(editable=False, max_length=16),
        ),
    ]
