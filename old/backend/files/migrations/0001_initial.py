"""State-only migration: declare UploadedFile inside the ``files`` app.

Paired with modules.0009_remove_uploadedfile_state_only. The table
``modules_uploadedfile`` already exists (created by modules.0007) and
is NOT recreated — only Django's model state is updated so future
migrations are generated against the ``files`` app.
"""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('modules', '0009_remove_uploadedfile_state_only'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='UploadedFile',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('file_id', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                        ('original_name', models.CharField(max_length=255)),
                        ('media_type', models.CharField(max_length=100)),
                        ('category', models.CharField(max_length=20)),
                        ('file_size', models.PositiveIntegerField(help_text='Taille décodée en octets')),
                        ('disk_path', models.CharField(help_text='Chemin absolu sur le disque', max_length=500)),
                        ('person_id', models.CharField(default='anonymous', max_length=100)),
                        ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                        ('is_deleted', models.BooleanField(default=False)),
                    ],
                    options={
                        'db_table': 'modules_uploadedfile',
                        'ordering': ['-uploaded_at'],
                    },
                ),
            ],
        ),
    ]
