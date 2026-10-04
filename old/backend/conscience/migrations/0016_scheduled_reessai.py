# Le délai de réessai d'une action programmée dont la tentative a échoué.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conscience', '0015_estime_de_soi'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduledaction',
            name='reessayer_le',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
