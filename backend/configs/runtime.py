"""Lectures typées d'un réglage, sur le chemin chaud.

``config_service.get`` est le bon point d'entrée, mais il ne promet rien sur le
*type* de ce qu'il rend : une valeur écrite à la main en base, une clé encore
non déclarée, un défaut de schéma laissé à ``None`` — chacun de ces cas remonte
tel quel jusqu'à l'appelant, qui fait alors une multiplication sur ``None`` au
milieu d'un tour de conversation.

Ces accesseurs existent pour que le rapatriement d'une constante en
configuration ne change **que** l'origine de la valeur, jamais la robustesse du
site d'appel : la constante d'origine reste dans le module et devient le repli.
Un réglage illisible, hors bornes ou d'un type inattendu rend ce repli — la
valeur avec laquelle le code tournait avant d'être configurable — plutôt que de
propager une exception dans une boucle de fond que personne ne surveille.

Le repli n'est donc pas un second défaut déclaré (l'erreur que ``env_fallback``
a coûté cher à nettoyer) : il vaut *exactement* le ``default`` du ``ConfigItem``
correspondant, et un test le vérifie clé par clé. Il ne sert que lorsque le
registre lui-même est hors d'atteinte — import avant ``migrate``, base
verrouillée, collecte des tests.
"""
from __future__ import annotations

import logging
from typing import Any, Sequence

from utils.degradation import degradations

logger = logging.getLogger(__name__)


def _brut(key: str, fallback: Any) -> Any:
    from configs.service import config_service

    try:
        valeur = config_service.get(key, default=fallback)
    except Exception as exc:  # registre absent, base illisible, clé inconnue
        degradations.record(f"configs.runtime[{key}]", exc)
        return fallback
    return fallback if valeur is None else valeur


def cfg_int(key: str, fallback: int, *, mini: int | None = None,
            maxi: int | None = None) -> int:
    """Entier, borné. Une valeur illisible ou hors bornes rend le repli."""
    valeur = _brut(key, fallback)
    try:
        sortie = int(valeur)
    except (TypeError, ValueError):
        return fallback
    if mini is not None and sortie < mini:
        return fallback
    if maxi is not None and sortie > maxi:
        return fallback
    return sortie


def cfg_float(key: str, fallback: float, *, mini: float | None = None,
              maxi: float | None = None) -> float:
    valeur = _brut(key, fallback)
    try:
        sortie = float(valeur)
    except (TypeError, ValueError):
        return fallback
    if sortie != sortie:  # NaN — jamais un réglage, toujours un accident
        return fallback
    if mini is not None and sortie < mini:
        return fallback
    if maxi is not None and sortie > maxi:
        return fallback
    return sortie


def cfg_bool(key: str, fallback: bool) -> bool:
    valeur = _brut(key, fallback)
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float)):
        return bool(valeur)
    if isinstance(valeur, str):
        return valeur.strip().lower() in ("1", "true", "yes", "on", "oui")
    return fallback


def cfg_str(key: str, fallback: str) -> str:
    valeur = _brut(key, fallback)
    if not isinstance(valeur, str):
        return fallback
    return valeur


def cfg_list(key: str, fallback: Sequence[str]) -> list[str]:
    """Liste de chaînes. Une liste vide déclarée est une réponse, pas un repli."""
    valeur = _brut(key, fallback)
    if isinstance(valeur, str):
        return [v.strip() for v in valeur.split(",") if v.strip()]
    if isinstance(valeur, (list, tuple)):
        return [str(v) for v in valeur]
    return list(fallback)
