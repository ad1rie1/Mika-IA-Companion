import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0006_selfnarrative_and_remove_memory'),
    ]

    operations = [
        migrations.CreateModel(
            name='PersonProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('summary', models.TextField(blank=True, default='', help_text="Third-person paragraph: 'X est quelqu'un qui...'")),
                ('closeness', models.CharField(choices=[('stranger', 'Stranger'), ('acquaintance', 'Acquaintance'), ('friend', 'Friend'), ('close', 'Close')], default='stranger', max_length=20)),
                ('preferred_tone', models.CharField(choices=[('direct', 'Direct'), ('gentle', 'Gentle'), ('playful', 'Playful'), ('formal', 'Formal'), ('unknown', 'Unknown')], default='unknown', max_length=20)),
                ('topics_of_interest', models.JSONField(default=list)),
                ('sensitive_topics', models.JSONField(default=list)),
                ('interaction_count', models.IntegerField(default=0)),
                ('last_interaction_at', models.DateTimeField(blank=True, null=True)),
                ('last_souvenir_id', models.IntegerField(default=0)),
                ('confidence', models.FloatField(default=0.5)),
                ('generated_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('entity', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to='memory.entity')),
            ],
            options={
                'ordering': ['-last_interaction_at'],
                'indexes': [
                    models.Index(fields=['-last_interaction_at'], name='memory_pers_last_in_e391a7_idx'),
                    models.Index(fields=['-generated_at'], name='memory_pers_generat_5a8c14_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='Commitment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('description', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('honored', 'Honored'), ('dropped', 'Dropped')], default='pending', max_length=20)),
                ('due_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('person', models.ForeignKey(blank=True, limit_choices_to={'entity_type': 'person'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commitments_to_me', to='memory.entity')),
                ('source_souvenir', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commitments', to='memory.souvenir')),
            ],
            options={
                'ordering': ['status', '-created_at'],
                'indexes': [
                    models.Index(fields=['status', '-created_at'], name='memory_comm_status_01c2e8_idx'),
                    models.Index(fields=['person', 'status'], name='memory_comm_person__f1de45_idx'),
                ],
            },
        ),
    ]
