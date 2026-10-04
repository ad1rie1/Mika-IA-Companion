# L'origine d'une pensée, portée par un champ plutôt que déduite de sa forme.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conscience', '0016_scheduled_reessai'),
    ]

    operations = [
        migrations.AddField(
            model_name='rumination',
            name='origine',
            field=models.CharField(
                blank=True,
                choices=[
                    ('observation', 'Observation'),
                    ('audit', 'Audit'),
                    ('manque', 'Manque'),
                    ('revision', 'Revision'),
                    ('blocage', 'Blocage'),
                ],
                default='',
                max_length=20,
            ),
        ),
    ]
