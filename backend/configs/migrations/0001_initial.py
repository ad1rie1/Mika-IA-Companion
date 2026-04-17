import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ConfigValue",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("key", models.CharField(max_length=200, unique=True)),
                ("value_json", models.JSONField(blank=True, null=True)),
                ("encrypted", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_by", models.CharField(blank=True, default="", max_length=120)),
            ],
            options={
                "ordering": ["key"],
            },
        ),
        migrations.AddIndex(
            model_name="configvalue",
            index=models.Index(fields=["key"], name="configs_con_key_idx"),
        ),
        migrations.CreateModel(
            name="ConfigRecordItem",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("parent_key", models.CharField(max_length=200)),
                ("row_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("payload", models.JSONField(default=dict)),
                ("encrypted_fields", models.JSONField(blank=True, default=list)),
                ("enabled", models.BooleanField(default=True)),
                ("order", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["parent_key", "order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="configrecorditem",
            index=models.Index(fields=["parent_key", "order"], name="configs_con_parent__idx"),
        ),
        migrations.AddIndex(
            model_name="configrecorditem",
            index=models.Index(fields=["row_id"], name="configs_con_row_id_idx"),
        ),
        migrations.CreateModel(
            name="ConfigChangeLog",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                )),
                ("key", models.CharField(max_length=200)),
                ("row_id", models.UUIDField(blank=True, null=True)),
                ("action", models.CharField(max_length=20)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField(blank=True, null=True)),
                ("actor", models.CharField(blank=True, default="", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="configchangelog",
            index=models.Index(fields=["-created_at"], name="configs_con_created_idx"),
        ),
        migrations.AddIndex(
            model_name="configchangelog",
            index=models.Index(fields=["key", "-created_at"], name="configs_con_key_crt_idx"),
        ),
    ]
