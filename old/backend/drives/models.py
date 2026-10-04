"""La seule table des pulsions : un instantané par pulsion, écrasé sur place.

Les tensions étaient purement en RAM, présenté comme un choix ("on ne se
réveille pas avec la tension exacte de la veille"). Ce n'en était pas un : le
gate d'entrée du cycle de sommeil lisait REST, donc tout redémarrage du soir
remettait la fatigue à zéro et supprimait la nuit mentale entière. Et à
l'échelle des semaines, SOCIAL ne peut rien dire d'une absence si l'horodatage
du dernier échange disparaît au boot.

Le temps d'arrêt n'est pas restitué tel quel : `restore_state()` repose les
horodatages puis laisse `update()` rejouer l'écoulement, donc REST retombe et
les pulsions positives montent comme si le processus n'avait jamais coupé.
"""
from __future__ import annotations

from django.db import models


class DriveSnapshot(models.Model):
    """Dernière tension connue d'une pulsion."""

    kind = models.CharField(max_length=32, unique=True)
    tension = models.FloatField(default=0.0)
    last_satisfied = models.DateTimeField(null=True, blank=True)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "instantané de pulsion"
        verbose_name_plural = "instantanés de pulsions"

    def __str__(self) -> str:
        return f"{self.kind}={self.tension:.2f}"
