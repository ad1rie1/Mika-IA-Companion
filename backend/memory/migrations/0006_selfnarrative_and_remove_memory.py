from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0005_emotionalsummary'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Memory',
        ),
        migrations.CreateModel(
            name='SelfNarrative',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(help_text="First-person paragraph: 'Je suis quelqu'un qui...'")),
                ('key_themes', models.JSONField(default=list)),
                ('key_people', models.JSONField(default=list)),
                ('dominant_mood', models.CharField(blank=True, default='', max_length=30)),
                ('confidence', models.FloatField(default=0.7)),
                ('source_souvenir_count', models.IntegerField(default=0)),
                ('source_connaissance_count', models.IntegerField(default=0)),
                ('last_souvenir_id', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['-created_at'], name='memory_self_created_idx')],
            },
        ),
    ]
