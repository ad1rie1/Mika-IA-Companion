"""Modèles du module RSS — les flux suivis et les articles relevés.

Deux ajouts de fond par rapport à la version d'origine, qui ne stockait que
le strict nécessaire à la déduplication :

- **``published_at`` est une vraie date.** ``published`` restait la chaîne
  brute du flux (« Tue, 22 Jul 2026 08:12:00 +0200 »), donc inutilisable pour
  trier : la liste était ordonnée par heure de *relevé*, ce qui met un article
  d'il y a trois jours découvert ce matin devant celui publié il y a une heure.
  La chaîne est conservée à côté, parce qu'elle est ce que le flux affirme.
- **L'échec d'un flux est stocké.** Un flux mort se contentait d'une ligne de
  log : sur la page, il ressemblait exactement à un flux calme. ``last_error``
  / ``error_count`` rendent la panne lisible là où on la cherche.
"""

from django.db import models


class RSSFeed(models.Model):
    """Un flux RSS/Atom suivi."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=500, unique=True)
    category = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Regroupement libre (Tech, Actu, Science…).",
    )
    is_active = models.BooleanField(default=True)

    # Ce que ce flux a le droit de déclencher. Un flux à fort volume peut
    # rester lu sur la page sans réveiller la conscience à chaque titre.
    emit_events = models.BooleanField(
        default=True,
        help_text="Émettre un événement (donc réveiller la conscience) par nouvel article.",
    )
    keywords = models.CharField(
        max_length=500, blank=True, default="",
        help_text="Mots-clés séparés par des virgules. Renseignés, seuls les "
                  "articles qui en contiennent sont signalés (tous restent stockés).",
    )

    # Relevé conditionnel : renvoyés tels quels au serveur au coup suivant,
    # qui répond 304 si rien n'a bougé. La plupart des flux publics limitent
    # le débit ; ne pas les utiliser, c'est retélécharger le même mégaoctet
    # toutes les dix minutes pour rien.
    etag = models.CharField(max_length=200, blank=True, default="")
    http_last_modified = models.CharField(max_length=100, blank=True, default="")

    last_polled = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    # Échecs *consécutifs* : remis à zéro par le premier relevé réussi. Ce qui
    # intéresse est « ce flux est cassé maintenant », pas son total historique.
    error_count = models.PositiveIntegerField(default=0)
    # Total ingéré depuis toujours — les articles sont élagués, donc compter
    # les lignes restantes sous-estime durablement un flux actif.
    entries_total = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "modules"
        ordering = ["category", "name"]

    def __str__(self):
        return f"{self.name} ({self.url[:50]})"

    @property
    def is_healthy(self) -> bool:
        return not self.error_count

    @property
    def keyword_list(self) -> list[str]:
        return [k.strip().lower() for k in (self.keywords or "").split(",") if k.strip()]


class RSSEntry(models.Model):
    """Un article relevé — sert à la déduplication et à la consultation."""

    feed = models.ForeignKey(RSSFeed, on_delete=models.CASCADE, related_name="entries")
    entry_hash = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=500)
    link = models.URLField(max_length=500, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    author = models.CharField(max_length=200, blank=True, default="")
    # Chaîne brute du flux, conservée telle quelle : c'est ce que la source
    # affirme, y compris quand elle est illisible.
    published = models.CharField(max_length=100, blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    seen_at = models.DateTimeField(auto_now_add=True)

    is_read = models.BooleanField(default=False)
    # A déclenché un mot-clé : ce qui a réellement été signalé à Mika, par
    # opposition au bruit de fond auquel elle est abonnée.
    is_notable = models.BooleanField(default=False)

    class Meta:
        app_label = "modules"
        ordering = ["-published_at", "-seen_at"]
        unique_together = [("feed", "entry_hash")]
        indexes = [
            models.Index(fields=["is_read"], name="modules_rss_is_read_idx"),
            models.Index(fields=["-seen_at"], name="modules_rss_seen_at_idx"),
        ]

    def __str__(self):
        return self.title[:80]

    @property
    def dated(self):
        """La date à afficher : celle du flux, sinon celle du relevé."""
        return self.published_at or self.seen_at
