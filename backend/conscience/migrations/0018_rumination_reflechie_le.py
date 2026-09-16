# Le souvenir réflexif d'une pensée digérée n'est écrit qu'une fois.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conscience', '0017_rumination_origine'),
    ]

    operations = [
        migrations.AddField(
            model_name='rumination',
            name='reflechie_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
