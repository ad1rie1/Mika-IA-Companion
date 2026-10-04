"""Le module RSS gagne de quoi être lisible.

- ``RSSFeed`` retient l'état de son dernier relevé (succès, erreur, échecs
  consécutifs) et ses en-têtes de relevé conditionnel. Un flux mort était
  jusqu'ici indiscernable d'un flux calme.
- ``RSSEntry`` gagne une vraie date (``published_at``) : ``published`` reste
  la chaîne brute du flux, inutilisable pour trier — la liste était donc
  ordonnée par heure de découverte.
- ``is_read`` / ``is_notable`` : ce qui reste à voir, et ce qui a été signalé.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0010_forgelog_forgerecord"),
    ]

    operations = [
        # ── RSSFeed ────────────────────────────────────────────────
        migrations.AddField(
            model_name="rssfeed",
            name="category",
            field=models.CharField(
                blank=True, default="", max_length=100,
                help_text="Regroupement libre (Tech, Actu, Science…).",
            ),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="emit_events",
            field=models.BooleanField(
                default=True,
                help_text="Émettre un événement (donc réveiller la conscience) par nouvel article.",
            ),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="keywords",
            field=models.CharField(
                blank=True, default="", max_length=500,
                help_text="Mots-clés séparés par des virgules. Renseignés, seuls les "
                          "articles qui en contiennent sont signalés (tous restent stockés).",
            ),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="etag",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="http_last_modified",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="last_success_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="last_error",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="last_error_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="error_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="rssfeed",
            name="entries_total",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="rssfeed",
            options={"ordering": ["category", "name"]},
        ),

        # ── RSSEntry ───────────────────────────────────────────────
        migrations.AddField(
            model_name="rssentry",
            name="published_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rssentry",
            name="is_read",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="rssentry",
            name="is_notable",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="rssentry",
            name="summary",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterModelOptions(
            name="rssentry",
            options={"ordering": ["-published_at", "-seen_at"]},
        ),
        migrations.AddIndex(
            model_name="rssentry",
            index=models.Index(fields=["is_read"], name="modules_rss_is_read_idx"),
        ),
        migrations.AddIndex(
            model_name="rssentry",
            index=models.Index(fields=["-seen_at"], name="modules_rss_seen_at_idx"),
        ),
    ]
