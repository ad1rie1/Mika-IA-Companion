from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0009_rename_memory_comm_status_01c2e8_idx_memory_comm_status_780cba_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='attachments_meta',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
