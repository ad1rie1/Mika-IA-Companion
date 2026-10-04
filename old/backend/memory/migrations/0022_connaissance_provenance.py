from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("memory", "0021_sensibilite")]
    operations = [
        migrations.AlterField("connaissance", "confidence", models.FloatField(default=0.65)),
        migrations.AddField("connaissance", "epistemic_kind", models.CharField(
            max_length=12, default="unknown", choices=[("unknown", "Origine inconnue"), ("reported", "Rapporté"),
                ("observed", "Observé"), ("inferred", "Déduit"), ("uncertain", "Supposé")])),
        migrations.AddField("connaissance", "source_message_ids", models.JSONField(default=list, blank=True)),
    ]
