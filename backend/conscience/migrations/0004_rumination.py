import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conscience', '0003_scheduledaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='Rumination',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('summary', models.TextField()),
                ('themes', models.JSONField(default=list)),
                ('emotion', models.CharField(blank=True, default='', max_length=30)),
                ('intensity', models.FloatField(default=0.5)),
                ('status', models.CharField(choices=[('active', 'Active'), ('resolved', 'Resolved'), ('faded', 'Faded')], default='active', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('observation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ruminations', to='conscience.observation')),
            ],
            options={
                'ordering': ['-intensity', '-created_at'],
                'indexes': [models.Index(fields=['status', '-intensity'], name='conscience__status_8a2f11_idx')],
            },
        ),
    ]
