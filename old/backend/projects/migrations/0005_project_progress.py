from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0004_project_test_command_alter_project_resource_paths")]
    operations = [
        migrations.AddField("project", "stalled_runs", models.PositiveIntegerField(default=0)),
        migrations.AddField("project", "retry_after", models.DateTimeField(null=True, blank=True)),
        migrations.AddField("project", "pause_reason", models.CharField(max_length=300, blank=True, default="")),
        migrations.AddField("project", "progress_signature", models.CharField(max_length=64, blank=True, default="")),
    ]
