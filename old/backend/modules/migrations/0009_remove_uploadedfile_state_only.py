"""State-only migration: drop UploadedFile from the ``modules`` app state.

The UploadedFile model has moved to the ``files`` app. The physical
table is kept (``modules_uploadedfile``) — only Django's migration
bookkeeping is updated. The matching migration in files/0001_initial
re-creates the model state there without touching the DB either.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('modules', '0008_modulestate'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.DeleteModel(name='UploadedFile'),
            ],
        ),
    ]
