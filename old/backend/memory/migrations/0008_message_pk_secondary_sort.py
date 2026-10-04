from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('memory', '0007_personprofile_commitment'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='message',
            options={'ordering': ['created_at', 'pk']},
        ),
    ]
