"""Les réglages de la conscience, résolus au bord.

Les constantes de module restent en repli (une base injoignable ne doit
pas changer le comportement), et ces accesseurs sont le **bord** où la
configuration est lue : `conscience/scoring.py`, `vecu.py`, `trousse.py`
restent des modules purs, sans registre ni base, et reçoivent leurs valeurs
déjà résolues.

Sortis de ``engine.py`` avec le reste (voir ``travaux.py`` pour la règle du
découpage) : des fonctions de module, sans état, dont le moteur garde un
délégué du même nom pour celles que des tests ou ``travaux.py`` appellent.
Les replis sont des **noms de module** et non des attributs de classe : la
garde AST de ``test_config_rapatriement`` résout un repli ``ast.Name`` en
attribut du module appelant et ignore un ``self._X`` — ici, chaque repli est
donc confronté au défaut déclaré.
"""

from __future__ import annotations

from old.backend.configs.runtime import cfg_float, cfg_int, cfg_list
from old.backend.conscience.scoring import ScoringTuning
from old.backend.conscience.trousse import CURIOSITE, SOCIAL, SOCLE, TrousseTuning
from old.backend.conscience.vecu import PULSION_FORTE, PULSION_GATE, VecuTuning
from old.backend.utils.degradation import degradations

#: Fenêtre des observations « en attente ». Trois lectures s'y accordent :
#: ce que le scoring voit, ce que le balayage périme, et la borne haute de
#: la promotion en rumination. Une seule clé, donc.
_PENDING_WINDOW_MIN: int = 30
#: Délai au-delà duquel une initiative sans réponse compte comme ignorée,
#: et son multiplicateur quand l'acte est parti sur Telegram.
_IGNORED_REPLY_WINDOW_MIN: int = 20
_IGNORED_TELEGRAM_FACTOR: float = 3.0

#: Durées des fenêtres de salutation, en heures. Politique du LECTEUR,
#: pas du personnage : le profil circadien dit quand SON matin commence,
#: ces constantes disent combien de temps un bonjour reste un bonjour.
#: Les valeurs reproduisent les fenêtres historiques (7–10 = 3 h,
#: 18–20 = 2 h).
_SALUT_MATIN_DUREE_H = 3
_SALUT_SOIR_DUREE_H = 2

# Repli si la config est illisible — une base injoignable ne doit pas
# rendre les pensées immortelles NI les tuer en deux minutes.
_RUMINATION_HALF_LIFE_H: float = 6.0
_RUMINATION_DRIFT_H: float = 1.0


def pending_window_minutes() -> int:
    return cfg_int(
        "conscience.pending_window_minutes", _PENDING_WINDOW_MIN, mini=1,
    )


def ignored_reply_window_minutes() -> int:
    return cfg_int(
        "conscience.ignored_reply_window_minutes",
        _IGNORED_REPLY_WINDOW_MIN, mini=1,
    )


def scoring_tuning() -> ScoringTuning:
    """Les onze facteurs, lus dans la configuration, résolus **ici**.

    `compute_decision_score` ne connaît ni le registre ni la base : elle
    reçoit une `ScoringTuning` déjà remplie. C'est ce qui laisse aux tests
    unitaires du scoring leur valeur — ils mesurent la calibration
    déclarée, pas ce que contient la base de la machine qui les exécute.
    """
    d = ScoringTuning()  # les défauts *sont* les replis
    f = lambda cle, repli: cfg_float(f"conscience.{cle}", repli)  # noqa: E731
    i = lambda cle, repli: cfg_int(f"conscience.{cle}", repli)    # noqa: E731
    fenetres = fenetres_de_salutation()
    return ScoringTuning(
        sleep_wake_pertinence=f("sleep_wake_pertinence", d.sleep_wake_pertinence),
        sleep_wake_scheduled_priority=f(
            "sleep_wake_scheduled_priority", d.sleep_wake_scheduled_priority),
        sleep_penalty=f("sleep_penalty", d.sleep_penalty),
        pertinence_gate=f("factor.pertinence_gate", d.pertinence_gate),
        pertinence_weight=f("factor.pertinence_weight", d.pertinence_weight),
        urgency_gate=f("factor.urgency_gate", d.urgency_gate),
        urgency_weight=f("factor.urgency_weight", d.urgency_weight),
        urgency_cap=f("factor.urgency_cap", d.urgency_cap),
        mood_gate=f("factor.mood_gate", d.mood_gate),
        mood_bonus=f("factor.mood_bonus", d.mood_bonus),
        idle_gate_minutes=i("factor.idle_gate_minutes", d.idle_gate_minutes),
        # Une rampe nulle ferait une division par zéro sur le chemin de la
        # boucle de fond : hors bornes, `cfg_int` rend le repli plutôt que
        # de propager l'exception.
        idle_ramp_minutes=cfg_int(
            "conscience.factor.idle_ramp_minutes", d.idle_ramp_minutes, mini=1,
        ),
        idle_cap=f("factor.idle_cap", d.idle_cap),
        greeting_bonus=f("factor.greeting_bonus", d.greeting_bonus),
        scheduled_weight=f("factor.scheduled_weight", d.scheduled_weight),
        pressure_min_waits=i("factor.pressure_min_waits", d.pressure_min_waits),
        pressure_per_wait=f("factor.pressure_per_wait", d.pressure_per_wait),
        pressure_cap=f("factor.pressure_cap", d.pressure_cap),
        ignored_min_acts=i("factor.ignored_min_acts", d.ignored_min_acts),
        ignored_per_act=f("factor.ignored_per_act", d.ignored_per_act),
        ignored_cap=f("factor.ignored_cap", d.ignored_cap),
        drives_floor=f("factor.drives_floor", d.drives_floor),
        drives_cap=f("factor.drives_cap", d.drives_cap),
        drives_deadband=f("factor.drives_deadband", d.drives_deadband),
        rumination_gate=f("factor.rumination_gate", d.rumination_gate),
        rumination_weight=f("factor.rumination_weight", d.rumination_weight),
        rumination_cap=f("factor.rumination_cap", d.rumination_cap),
        fatigue_gate=f("factor.fatigue_gate", d.fatigue_gate),
        fatigue_slope=f("factor.fatigue_slope", d.fatigue_slope),
        fatigue_cap=f("factor.fatigue_cap", d.fatigue_cap),
        daily_acts_cap=i("daily_acts_cap", d.daily_acts_cap),
        suppress_after_ignored=i(
            "suppress_after_ignored", d.suppress_after_ignored),
        suppressed_score=f("suppressed_score", d.suppressed_score),
        suppress_release_idle_seconds=f(
            "suppress_release_idle_seconds", d.suppress_release_idle_seconds),
        morning_start=fenetres[0],
        morning_end=fenetres[1],
        evening_start=fenetres[2],
        evening_end=fenetres[3],
        night_start=fenetres[4],
    )


def fenetres_de_salutation() -> tuple[int, int, int, int, int]:
    """Les fenêtres de salutation, DÉRIVÉES du profil circadien.

    Les cinq clés `conscience.greeting.*` sont supprimées, pas doublées :
    elles cohabitaient avec `personality.circadian.*` — deux sources de
    vérité pour « quand commence son matin », et un personnage configuré
    nocturne saluait « le matin » à 7 h en dormant. Le profil est le
    personnage ; la salutation le suit. `(matin, fin_matin, soir,
    fin_soir, nuit)` — une fin peut dépasser 24 sans danger,
    `check_time_trigger` compare des heures ∈ [0, 23].

    Ne lève jamais : profil illisible → les fenêtres historiques
    (défauts de `ScoringTuning`).
    """
    d = ScoringTuning()
    try:
        from old.backend.config.personality import personality
        from old.backend.emotion.circadian import CircadianPhase

        heures = personality.circadian_profile.phase_hours
        matin = int(heures.get(CircadianPhase.MORNING, d.morning_start))
        soir = int(heures.get(CircadianPhase.EVENING, d.evening_start))
        nuit = int(heures.get(CircadianPhase.NIGHT, d.night_start))
        return (
            matin, matin + _SALUT_MATIN_DUREE_H,
            soir, soir + _SALUT_SOIR_DUREE_H,
            nuit,
        )
    except Exception as exc:
        degradations.record("conscience: fenetres de salutation", exc)
        return (
            d.morning_start, d.morning_end,
            d.evening_start, d.evening_end,
            d.night_start,
        )


def vecu_tuning() -> VecuTuning:
    """Les seuils de ce qu'elle se raconte.

    Trois des quatre portes sont **dérivées** de la `ScoringTuning` déjà
    résolue, jamais relues sous une clé à elles : il ne peut donc pas
    exister de configuration où le prompt annonce un débordement d'humeur
    que le score n'a pas compté, ni l'inverse. Deux clés pour un même
    réglage est, dans ce dépôt, LE bug — c'est ce qui a coûté le pont
    `env_fallback`.

    Seule la porte de pulsion est propre au récit : le score pondère les
    quatre pulsions ensemble (facteur 9), là où une phrase ne peut nommer
    que celle qui domine.
    """
    s = scoring_tuning()
    d = VecuTuning()
    return VecuTuning(
        inactivite_gate_minutes=s.idle_gate_minutes,
        humeur_gate=s.mood_gate,
        rumination_gate=s.rumination_gate,
        pulsion_gate=cfg_float(
            "conscience.vecu.porte_pulsion", PULSION_GATE),
        pulsion_forte=cfg_float(
            "conscience.vecu.pulsion_forte", PULSION_FORTE),
        valence_marquee=d.valence_marquee,
        eveil_marque=d.eveil_marque,
        dominance_marquee=d.dominance_marquee,
    )


def trousse_tuning() -> TrousseTuning:
    """Le réglage de la trousse, résolu **ici** — `trousse.py` reste pur.

    Les trois listes se lisent enfin : leurs clés étaient déclarées au
    registre (éditables au dashboard) et lues par personne — un réglage
    que l'opérateur modifiait sans effet, la forme exacte du bug
    `env_fallback`.
    """
    d = TrousseTuning()
    return TrousseTuning(
        plafond_caracteres=cfg_int(
            "conscience.trousse.plafond_caracteres", d.plafond_caracteres,
            mini=0,
        ),
        porte_pulsion=cfg_float(
            "conscience.trousse.porte_pulsion", d.porte_pulsion,
        ),
        socle=tuple(cfg_list("conscience.trousse.socle", SOCLE)),
        curiosite=tuple(cfg_list("conscience.trousse.curiosite", CURIOSITE)),
        social=tuple(cfg_list("conscience.trousse.social", SOCIAL)),
    )


def rumination_tuning() -> tuple[float, float]:
    """(demi-vie en heures, délai de dérive en heures), depuis la config."""
    from old.backend.configs.service import config_service

    def _f(key: str, defaut: float) -> float:
        try:
            valeur = float(config_service.get(key))
            return valeur if valeur > 0 else defaut
        except Exception:
            return defaut

    return (
        _f("conscience.rumination_half_life_hours", _RUMINATION_HALF_LIFE_H),
        _f("conscience.rumination_drift_hours", _RUMINATION_DRIFT_H),
    )
