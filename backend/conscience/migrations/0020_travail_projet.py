from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("conscience", "0019_conscience_log_index"), ("projects", "0005_project_progress")]
    operations = [
        migrations.AlterField("scheduledaction", "status", models.CharField(max_length=20, default="pending", choices=[("pending", "Pending"), ("executed", "Executed"), ("uncertain", "Uncertain"), ("cancelled", "Cancelled"), ("failed", "Failed")])),
        migrations.AddField("travail", "projet", models.ForeignKey(
            "projects.Project", null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name="intentions")),
        migrations.AlterField("travail", "statut", models.CharField(max_length=15, default="en_cours",
            choices=[("en_cours", "En Cours"), ("transfere", "Transfere"), ("aboutie", "Aboutie"),
                     ("bloquee", "Bloquee"), ("abandonnee", "Abandonnee")])),
    ]
