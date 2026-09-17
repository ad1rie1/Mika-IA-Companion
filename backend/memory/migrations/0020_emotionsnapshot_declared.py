from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("memory", "0019_entity_lower_index_episodic_bigint"),
    ]

    operations = [
        migrations.AddField(
            model_name="emotionsnapshot",
            name="declared",
            field=models.BooleanField(default=True),
        ),
    ]
