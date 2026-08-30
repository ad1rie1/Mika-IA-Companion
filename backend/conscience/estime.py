"""L'estime de soi — la variable lente entre le tempérament et l'humeur.

Le dossier psychologique la nommait en horizon : être ignorée n'était qu'un
compteur comportemental (le backoff), réussir remontait l'humeur mais jamais
la confiance en soi. Or l'humain tient une **valeur propre** qui bouge
lentement, encaisse les événements par petits coups, et colore l'audace comme
l'auto-critique — ni un trait (le tempérament ne bouge pas), ni un état
(l'humeur vit en minutes) : des *jours*.

Trois propriétés, chacune contre une dérive connue :

* **Elle rappelle vers le neutre** (0.5, demi-vie 72 h — la même échelle que
  la guérison des ancres affectives) : ni gloire ni abattement ne sont des
  états permanents, et un mois sans événement la ramène à l'équilibre.
* **Les coups sont petits et bornés** ([0.05, 0.95]) : un seul échec ne
  fabrique pas une dépression, un seul succès pas une grandiloquence — c'est
  l'accumulation qui compte, comme chez l'humain.
* **Elle ne touche JAMAIS le score de décision** : l'invariant des plafonds
  (idle + drives − ignorée = seuil) est calibré et testé ; l'estime colore ce
  qu'elle se dit (prompt, état cognitif) et combien elle se rejoue (l'audit
  post-acte), pas si elle a le droit de parler.

Lecture/écriture dans **un seul callable synchrone** (le piège documenté sur
`_decay_ruminations`), ancre avancée à l'écriture seulement (l'idiome
`decayed_at`). Persistée : l'estime de soi est précisément ce qui doit
survivre à un redémarrage — perdre trois jours de confiance avec un reboot
serait le contraire de sa définition. Constantes de la famille des ancres
PAD : la physique du personnage, pas des clés de configuration.
"""

from __future__ import annotations

import logging
from datetime import datetime

from asgiref.sync import sync_to_async

from utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Le point d'équilibre, et les bornes dures.
BASELINE = 0.5
PLANCHER = 0.05
PLAFOND = 0.95
#: Demi-vie du retour au neutre, en heures — l'échelle de la guérison des
#: ancres affectives (3 jours) : la confiance et le doute s'estompent au
#: même rythme que la rancune.
DEMI_VIE_H = 72.0

#: Les coups. Petits : c'est l'accumulation qui fait l'estime.
COUP_TRAVAIL_ABOUTI = 0.05
COUP_TRAVAIL_BLOQUE = -0.04
COUP_INITIATIVE_IGNOREE = -0.03
#: Quelqu'un répond après une série d'initiatives ignorées : le soulagement
#: de « je compte encore » vaut un peu plus que le coup d'une relance de plus.
COUP_SERIE_ROMPUE = 0.04


# ── La physique, pure ─────────────────────────────────────────────────────


def valeur_courante(
    valeur: float, ancre: datetime | None, maintenant: datetime,
) -> float:
    """La valeur À CET INSTANT — rappel exponentiel vers le neutre.

    Même idiome que ``conduite.envie_courante`` : lire ne facture rien,
    l'ancre n'avance qu'à l'écriture. Ne lève jamais — une ancre malformée
    vaut « pas de temps écoulé ».
    """
    try:
        valeur = float(valeur)
    except (TypeError, ValueError):
        return BASELINE
    if ancre is None or maintenant is None:
        return _borner(valeur)
    try:
        heures = (maintenant - ancre).total_seconds() / 3600.0
    except (TypeError, AttributeError, OverflowError):
        return _borner(valeur)
    if heures <= 0:
        return _borner(valeur)
    part = 0.5 ** (heures / DEMI_VIE_H)
    return _borner(BASELINE + (valeur - BASELINE) * part)


def _borner(valeur: float) -> float:
    return max(PLANCHER, min(PLAFOND, valeur))


# ── Lecture et coups ──────────────────────────────────────────────────────


async def lire() -> float:
    """La valeur courante, décrue à la lecture, sans écriture.

    Ne lève jamais : une base injoignable rend le neutre — « je ne sais pas
    où j'en suis » ne doit ni doper ni abattre.
    """
    from django.utils import timezone as tz

    def _lecture() -> float:
        from conscience.models import EstimeDeSoi

        row = EstimeDeSoi.objects.first()
        if row is None:
            return BASELINE
        return valeur_courante(row.valeur, row.ancre or row.updated_at, tz.now())

    try:
        return await sync_to_async(_lecture)()
    except Exception as exc:
        degradations.record("conscience: lecture de l'estime", exc)
        return BASELINE


async def ressentir(coup: float, raison: str = "") -> float:
    """Encaisser un coup — décroissance facturée puis coup appliqué, valeur
    et ancre écrites ensemble. Rend la nouvelle valeur ; ne lève jamais.
    """
    from django.utils import timezone as tz

    def _ecrire() -> float:
        from conscience.models import EstimeDeSoi

        maintenant = tz.now()
        row = EstimeDeSoi.objects.first()
        if row is None:
            row = EstimeDeSoi(valeur=BASELINE, ancre=maintenant)
        courante = valeur_courante(row.valeur, row.ancre, maintenant)
        row.valeur = _borner(courante + float(coup))
        row.ancre = maintenant
        row.save()
        return row.valeur

    try:
        nouvelle = await sync_to_async(_ecrire, thread_sensitive=True)()
        logger.debug("Estime de soi %+0.3f (%s) → %.3f", coup, raison, nouvelle)
        return nouvelle
    except Exception as exc:
        degradations.record("conscience: coup d'estime", exc)
        return BASELINE


#: Sous ce niveau, le doute se dit ; au-dessus du haut, l'assurance aussi.
#: Entre les deux, l'estime est silencieuse — l'équilibre n'a pas besoin de
#: se raconter.
SEUIL_DOUTE = 0.35
SEUIL_ASSURANCE = 0.7


def ligne_de_prompt(valeur: float) -> str:
    """Ce que l'état cognitif en dit — un sentiment, jamais un nombre."""
    if valeur <= SEUIL_DOUTE:
        return (
            "Ces derniers temps, tu doutes un peu de toi — plusieurs choses "
            "n'ont pas marché comme tu voulais. Ça te rend plus prudente, "
            "pas muette."
        )
    if valeur >= SEUIL_ASSURANCE:
        return (
            "Tu te sens plutôt sûre de toi ces temps-ci — ce que tu "
            "entreprends aboutit."
        )
    return ""
