"""Drive state — pure dataclasses, no Django dependency.

Kept pure so the core logic is testable without a DB / event loop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from math import log1p


class DriveKind(str, Enum):
    """The four intrinsic drives.

    CURIOSITY  : need to learn, discover, ask questions about the world/person
    SOCIAL     : need for connection, being acknowledged, hearing back
    EXPRESSION : need to share thoughts, opinions, jokes that pop up
    REST       : need for silence, low-stimulation recovery
    """
    CURIOSITY = "curiosity"
    SOCIAL = "social"
    EXPRESSION = "expression"
    REST = "rest"


@dataclass
class DriveParams:
    """Per-drive parameters (clamped to sensible ranges)."""
    growth_rate: float = 0.02         # tension added per second when unsatisfied
    decay_on_satisfy: float = 0.5      # fraction of tension removed when assouvi
    weight: float = 0.25               # contribution to conscience score at tension=1.0
    satisfy_threshold: float = 0.4     # below this, drive doesn't contribute
    # Croissance en temps logarithmique, opt-in : `growth_horizon = 0` garde
    # la croissance linéaire d'origine.
    growth_tau: float = 0.0            # secondes ; échelle du début de courbe
    growth_horizon: float = 0.0        # secondes pour atteindre 1.0


def log_growth(elapsed: float, tau: float, horizon: float) -> float:
    """Tension bâtie par le seul écoulement du temps, dans [0, 1].

    Une échelle linéaire ne peut pas décrire une absence : à 0.0010/s SOCIAL
    saturait en 16 min 40, donc une heure, un jour et trois semaines rendaient
    la même phrase de prompt et le même facteur de scoring. En log-temps, la
    première demi-heure compte encore et l'écart entre une heure et trois
    semaines reste lisible.
    """
    if elapsed <= 0 or tau <= 0 or horizon <= 0:
        return 0.0
    return min(1.0, log1p(elapsed / tau) / log1p(horizon / tau))


# Default per-kind parameters. Calibrated so that a drive devient notable
# (~0.5) apres une dizaine de minutes d'inactivite et ne pousse fortement
# (~0.9) qu'au bout de 20 a 25 minutes.
#
# Les taux precedents (0.0030 / 0.0025 / 0.0020) saturaient les trois
# pulsions positives en 8 min 20 au plus tard, cycle de decision tournant
# toutes les 30 s : leur somme restait donc collee a +0.90, le facteur 9
# valait la constante +0.50, et le bloc de prompt repetait indefiniment les
# trois memes phrases en « fortement » sans rien apprendre au modele.
DEFAULT_PARAMS: dict[DriveKind, DriveParams] = {
    # CURIOSITY et EXPRESSION passent en log-temps pour la même raison que
    # SOCIAL avant elles : en linéaire, 0.0008/s saturait la curiosité en
    # 20 min 50 et 0.0007/s l'expression en 23 min 49. Or leurs poids
    # (0.30 + 0.25 = 0.55) dépassent à eux seuls le plafond du Facteur 9
    # (+0.50) : passé la demi-heure, ce facteur valait donc la constante
    # +0.50 quoi qu'il arrive, et ni une heure ni trois jours de silence ne
    # changeaient plus rien au score. Le plafond n'est pas touché — il reste
    # dans l'invariant qui le fait sommer au seuil d'action ; c'est la courbe
    # qui cesse de s'y écraser en vingt minutes.
    # Courbe obtenue (curiosité) : 10 min 0.30, 21 min 0.42, 1 h 0.58, 12 h 1.0.
    DriveKind.CURIOSITY: DriveParams(
        growth_rate=0.0,
        decay_on_satisfy=0.6,
        weight=0.30,
        satisfy_threshold=0.35,
        growth_tau=120.0,
        growth_horizon=12 * 3600.0,
    ),
    # SOCIAL est la seule pulsion qui parle d'*absence*, donc la seule dont
    # l'échelle de temps doit dépasser le quart d'heure : le linéaire la
    # saturait en 16 min 40, après quoi une heure et trois semaines rendaient
    # la même ligne de prompt. Courbe obtenue : 1 h 0.28, 1 j 0.63, 1 sem
    # 0.84, 3 sem 0.96. Le seuil descend à 0.25 pour qu'elle redevienne
    # visible après ~45 min et non après ~3 h.
    DriveKind.SOCIAL: DriveParams(
        growth_rate=0.0,
        decay_on_satisfy=0.7,
        weight=0.35,
        satisfy_threshold=0.25,
        growth_tau=300.0,
        growth_horizon=30 * 86400.0,
    ),
    # Courbe obtenue (expression) : 10 min 0.28, 24 min 0.42, 1 h 0.59, 9 h 1.0.
    # Horizon plus court que la curiosité : l'envie de dire quelque chose se
    # constitue dans la journée, pas sur trois semaines comme une absence.
    DriveKind.EXPRESSION: DriveParams(
        growth_rate=0.0,
        decay_on_satisfy=0.8,
        weight=0.25,
        satisfy_threshold=0.45,
        growth_tau=180.0,
        growth_horizon=9 * 3600.0,
    ),
    DriveKind.REST: DriveParams(
        # Rest drive grows only when Mika has been very active recently.
        # It is handled specially — see DriveEngine._rest_step (time spent active).
        growth_rate=0.0,
        decay_on_satisfy=0.3,
        weight=0.20,
        satisfy_threshold=0.50,
    ),
}


#: Tension minimale pour qu'une pulsion soit déclarée dominante.
DOMINANT_MIN_TENSION = 0.2


def params_for(kind: DriveKind) -> DriveParams:
    """Les paramètres EFFECTIFS d'une pulsion : la table ci-dessus, recouverte
    par la configuration (section « Pulsions » du dashboard).

    La table reste le repli, champ par champ, et les défauts déclarés dans
    ``drives/config_schema.py`` lui sont identiques — une installation neuve
    calcule donc exactement les mêmes tensions.

    Un seul accesseur parce que ``DEFAULT_PARAMS[kind]`` était relu à chaque
    appel dans cinq fonctions différentes : sans point de passage unique, il
    aurait fallu recouvrir la table cinq fois, et les cinq auraient divergé.

    Les deux champs de croissance logarithmique ne sont relus que pour les
    pulsions qui en déclarent une (``growth_horizon`` non nul dans la table).
    Ailleurs la clé n'existe pas, et une clé inconnue n'est pas mise en cache
    par ``config_service`` : ce serait une requête par appel, sur un chemin
    appelé à chaque tour.

    L'import est local : ce module est documenté « pure dataclasses, no Django
    dependency » et doit rester importable sans registre d'applications.
    """
    from configs.runtime import cfg_float

    base = DEFAULT_PARAMS[kind]
    prefixe = f"drives.{kind.value}."

    tau, horizon = base.growth_tau, base.growth_horizon
    if base.growth_horizon:
        tau = cfg_float(prefixe + "growth_tau", base.growth_tau, mini=0.0)
        # Exposé en JOURS : c'est l'unité dans laquelle « une absence de trois
        # semaines » se pense, pas 2 592 000 s.
        horizon = cfg_float(
            prefixe + "growth_horizon_days",
            base.growth_horizon / 86400.0,
            mini=0.0,
        ) * 86400.0

    return DriveParams(
        growth_rate=cfg_float(
            prefixe + "growth_rate", base.growth_rate, mini=0.0),
        decay_on_satisfy=cfg_float(
            prefixe + "decay_on_satisfy", base.decay_on_satisfy,
            mini=0.0, maxi=1.0),
        weight=cfg_float(
            prefixe + "weight", base.weight, mini=0.0, maxi=1.0),
        satisfy_threshold=cfg_float(
            prefixe + "satisfy_threshold", base.satisfy_threshold,
            mini=0.0, maxi=1.0),
        growth_tau=tau,
        growth_horizon=horizon,
    )


@dataclass
class DriveState:
    """One drive's current tension + bookkeeping."""
    kind: DriveKind
    tension: float = 0.0
    last_update: float = field(default_factory=time.time)
    last_satisfied: float = field(default_factory=time.time)

    def clamp(self) -> None:
        self.tension = max(0.0, min(1.0, self.tension))


def dominant_drive(states: dict[DriveKind, DriveState]) -> DriveState | None:
    """Return the drive with the highest tension, or None if all are quiet."""
    if not states:
        return None
    from configs.runtime import cfg_float

    winner = max(states.values(), key=lambda s: s.tension)
    if winner.tension < cfg_float(
        "drives.dominant_min_tension", DOMINANT_MIN_TENSION, mini=0.0, maxi=1.0,
    ):
        return None
    return winner


# `drive_prompt_description` et `_describe_drive` ont été supprimées ici.
#
# Quatre pulsions × trois adverbes = douze phrases pour toute la vie
# intérieure, et le bloc de prompt répétait indéfiniment les trois mêmes en
# « fortement » — le palier haut s'ouvrait à 0.75, que les pulsions positives
# atteignaient en vingt minutes. `drives/phrasing.py` les remplace par 112
# variantes réparties sur quatre paliers, avec un tirage qui amortit les
# répétitions. Le point d'entrée reste `DriveEngine.get_context()`.
#
# Elles ne laissent pas de repli : une fonction gardée « au cas où » aurait
# figé ici une seconde vérité sur ce que ressent Mika, ce que ce module tout
# entier existe pour éviter.
