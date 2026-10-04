from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0020_emotionsnapshot_declared"),
    ]

    operations = [
        migrations.AddField(
            model_name="souvenir",
            name="sensibilite",
            field=models.CharField(
                choices=[("anodin", "Anodin"), ("personnel", "Personnel"),
                         ("confidence", "Confidence")],
                default="personnel",
                help_text=(
                    "Ce que cette ligne pese si elle concerne quelqu'un d'autre "
                    "que l'interlocuteur : anodin / personnel / confidence. "
                    "Notee par l'extracteur ; une ligne dont on ne sait rien "
                    "est personnelle, jamais anodine."
                ),
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="connaissance",
            name="sensibilite",
            field=models.CharField(
                choices=[("anodin", "Anodin"), ("personnel", "Personnel"),
                         ("confidence", "Confidence")],
                default="personnel",
                help_text="Meme echelle que Souvenir.sensibilite.",
                max_length=12,
            ),
        ),
    ]
