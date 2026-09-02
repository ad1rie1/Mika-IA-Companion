from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0017_conversationsummary'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='transport_meta',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
