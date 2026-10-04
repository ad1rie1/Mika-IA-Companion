from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('modules', '0007_add_uploadedfile'),
    ]

    operations = [
        migrations.CreateModel(
            name='ModuleState',
            fields=[
                ('name', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(default=True, help_text='Whether the module should be started at boot.')),
                ('installed_tables', models.JSONField(blank=True, default=list, help_text='List of db_table names created by schema_editor for unmanaged models owned by this module. Used for diffing on boot and for safe drop on uninstall.')),
                ('schema_version', models.IntegerField(default=1)),
                ('installed_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
