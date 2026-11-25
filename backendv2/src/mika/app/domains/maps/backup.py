"""Ce que la carte dit à la sauvegarde (ADR 0193, 0310)."""

from __future__ import annotations

from mika.adapters.maps.quota import QUOTAS_FILE

#: jamais archivé : la carte de sa position (ADR 0193) — quelques Go qui se réextraient
UNSAVED = ("cartes",)
#: gardés quand même : les compteurs des services de la carte (quelques Ko, R3-08) — ce qui empêche la facture de
#: Google ; une machine neuve ne repart pas d'un mois à zéro. Restaurés seulement là où il n'y en a pas : ceux du
#: dossier, en service, sont plus récents que l'archive
SAVED = (QUOTAS_FILE,)
