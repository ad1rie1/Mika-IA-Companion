from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('conscience', '0004_rumination'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='observation',
            name='conscience__created_3d4b82_idx',
        ),
        migrations.RemoveField(
            model_name='observation',
            name='acted_upon',
        ),
        migrations.AlterModelOptions(
            name='observation',
            options={'ordering': ['-created_at', '-pk']},
        ),
    ]
