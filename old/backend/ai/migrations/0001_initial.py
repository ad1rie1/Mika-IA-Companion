from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AIQuotaUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(db_index=True, max_length=40)),
                ('project_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('date', models.DateField(db_index=True)),
                ('provider', models.CharField(default='', max_length=20)),
                ('model', models.CharField(default='', max_length=80)),
                ('call_count', models.IntegerField(default=0)),
                ('tokens_in', models.BigIntegerField(default=0)),
                ('tokens_out', models.BigIntegerField(default=0)),
                ('cost_usd', models.FloatField(default=0.0)),
                ('last_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'indexes': [
                    models.Index(fields=['date', 'role'], name='ai_aiquotau_date_role_idx'),
                    models.Index(fields=['date', 'project_id'], name='ai_aiquotau_date_proj_idx'),
                ],
                'unique_together': {('role', 'project_id', 'date', 'provider', 'model')},
            },
        ),
    ]
