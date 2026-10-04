from django.db import migrations, models


class Migration(migrations.Migration):
    """Ancre de décroissance en temps réel pour les ruminations.

    Les lignes existantes gardent `decayed_at = NULL`, ce que
    `Rumination.decay_anchor` lit comme `created_at` : leur âge réel est donc
    facturé d'un coup au premier passage, ce qui est le comportement voulu
    (elles auraient dû vieillir depuis leur création).
    """

    dependencies = [
        ("conscience", "0006_rename_conscience__status_8a2f11_idx_conscience__status_187012_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="rumination",
            name="decayed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
