from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0002_projectprompthistory'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='monthly_token_budget',
            field=models.IntegerField(default=0),
        ),
    ]
