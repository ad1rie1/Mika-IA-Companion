"""Ce que les projets disent à la sauvegarde (ADR 0260, 0262, 0277, 0310)."""

from __future__ import annotations

from mika.adapters.workshop import REVIEWS_DIRNAME, VIEWS_DIRNAME

#: jamais archivés, sous ses ateliers : les vues des ateliers lus (ADR 0260, 0262) — la copie du dernier commit d'un
#: autre atelier, que l'archive porte déjà avec son dépôt, et qui se repose seule à l'exécution suivante ; et la
#: copie de commit qu'une relecture indépendante lit (ADR 0277), jetable par nature
UNSAVED = (f"ateliers/{VIEWS_DIRNAME}", f"ateliers/{REVIEWS_DIRNAME}")
