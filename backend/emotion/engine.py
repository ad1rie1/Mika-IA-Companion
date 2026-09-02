import asyncio
import dataclasses
import logging
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings

from configs.runtime import cfg_float, cfg_int
from emotion import dynamics, pad
from emotion.dynamics import OscillatorParams, OscillatorState
from emotion.pad import Vec3
from emotion.types import Emotion, EmotionData
from emotion.state import (
    REST_TOLERANCE,
    TEMPERAMENT_PREFIX,
    EmotionHistoryEntry,
    GlobalMood,
    MessageEmotion,
    PersonMood,
    Temperament,
    load_temperament,
)
from identity.trust import is_identifiable_person, is_internal_person
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Physics tick period (seconds) used by the decay loop.
_TICK_DT = 1.0
# Maximum sub-step size for stable integration. Semi-implicit Euler is only
# stable when dt · ω₀ < ~π; for our parameter range, 0.5s is always safe.
_MAX_SUBSTEP_DT = 0.5
# Past this much simulated time, the sub-step is coarsened: relaxation over
# an hour is 720 steps at 5s, and dt · ω₀ ≈ 0.006 stays far from the stability
# limit. The window before it stays fine-grained so a normal tick is exact.
_FINE_WINDOW_S = 60.0
_COARSE_SUBSTEP_DT = 5.0
# ── Réglages rapatriés en configuration ──────────────────────────────
#
# Les constantes qui suivent restent déclarées ici et gardent leur valeur :
# elles sont le REPLI de la clé ``emotion.*`` correspondante (section Émotion
# du dashboard), servi quand le registre est hors d'atteinte — import avant
# ``migrate``, base verrouillée, collecte des tests. Le défaut déclaré dans
# ``emotion/config_schema.py`` vaut exactement la constante, donc une
# installation neuve se comporte à l'identique ; ce qui change, c'est
# seulement l'origine de la valeur. Voir ``configs/runtime.py``.
#
# Ce qui n'est PAS configurable, et ne doit pas le devenir : les pas
# d'intégration (`_MAX_SUBSTEP_DT`, `_FINE_WINDOW_S`, `_COARSE_SUBSTEP_DT`).
# Ce ne sont pas des réglages mais la condition de stabilité du schéma d'Euler
# semi-implicite — un curseur y règle la justesse du calcul, pas le caractère.

# Upper bound on the total time advanced in a single _apply_decay call.
# Invisible while the time constant was ~7s (the old 30s cap was already four
# time constants); with a τ counted in minutes it froze the state of a machine
# that had hibernated, so the bound is an hour of catch-up.
_MAX_ADVANCE_SECONDS = 3600.0
# Probability per tick that the global mood receives a tiny stochastic
# nudge. Without this, a well-rested idle Mika sits exactly on her home
# point — humans don't. Small nudges produce barely-perceptible drift
# ("why am I a bit off today") that the oscillator then metabolizes
# normally. Scoped to the global mood only; per-person moods are always
# reactive, never spontaneous.
# A nudge now lives for τ — minutes, not seconds — so at the old cadence they
# compounded into a visible random walk. Rarer and smaller, same drift.
_SPONTANEOUS_NUDGE_PROBABILITY: float = 0.004
# Max magnitude of a spontaneous nudge (in PAD units).
_SPONTANEOUS_NUDGE_MAX: float = 0.05

# Constante de temps du retour au repos, aux deux bouts du curseur « vitesse
# de récupération » (interpolation géométrique). Un tour dure 30-120 s : avec
# le réglage précédent l'état revenait au repos en ~27 s, donc l'émotion d'un
# tour avait disparu avant le tour suivant et tout ce qui lit la position —
# prompt, relevé, fiche affect, gestes — lisait le repos. Cible au défaut
# (recovery_speed 0.5) : ~11,6 min, dans une plage de 4 min à 30 min.
PERSON_TAU_FAST = 240.0
PERSON_TAU_SLOW = 1800.0
GLOBAL_TAU_FACTOR = 2.0
# Part de la distance restante qu'une impulsion parcourt d'un coup.
RATCHET_BASE = 1.0
RATCHET_MAX = 0.75
RATCHET_GLOBAL = 0.45
# Résonance de tempérament : une impulsion alignée sur le fond du personnage
# (l'ancre PAD de `default_mood`) est amplifiée — gain × (1 + k·cos), cos
# retenu seulement s'il est positif. AMPLIFICATION SEULEMENT, jamais
# d'armure : atténuer les impulsions contraires rendrait un fond heureux
# structurellement intouchable par la tristesse, alors que « résister » est
# déjà ce que `recovery_speed` et le point de repos expriment. C'est la
# propriété que `test_melancholic_resonates_with_sadness` nommait en restant
# volontairement rouge : mélancolique et défaut ne différaient que par
# `intensity_base`, le fond n'entrait dans la physique que par le point de
# repos — sous 1 % par tour à τ = 1059 s.
RESONANCE_STRENGTH = 0.45
# Modulation du gain global par l'intensité déclarée : gain_effectif =
# gain_base × (PLANCHER + PENTE × intensité), plafonné. À 0.2 d'intensité une
# émotion effleure l'humeur générale, à 1.0 elle la traverse. Un gain fixe
# rendait « tu te sens contente, comme d'habitude » lisible dans le prompt
# pendant qu'on lui écrivait « je pleure ».
# Le facteur reste RELATIF au gain du tempérament : `global_bleed` promet « à
# 0 elle compartimente entièrement », et un plafond absolu aurait fait passer
# une émotion forte par-dessus ce curseur. Un tempérament stoïque module donc
# dans sa propre échelle, sans jamais en sortir.
GLOBAL_GAIN_FLOOR = 0.4
GLOBAL_GAIN_SLOPE = 1.6
GLOBAL_GAIN_MAX_FACTOR = 2.0
GLOBAL_RATCHET_MAX = 0.5

# Part de l'humeur par défaut dans le point de repos commun : home =
# default_mood × ce poids + teinte circadienne. C'était un littéral nu au
# milieu de ``_home_vector``, alors que c'est exactement le curseur qui décide
# de la place du personnage dans son propre repos.
HOME_DEFAULT_MOOD_WEIGHT = 0.15

# Ancrage personnel : part du point de repos d'une personne qui vient de ce
# qu'elle a déjà provoqué, contre le repos circadien commun.
PERSON_ANCHOR_WEIGHT = 0.6
ANCHOR_MAX_NORM = 0.7
ANCHOR_ALPHA = 0.15
ANCHOR_SAMPLE = 20
# Demi-vie de la GUÉRISON d'une stance : le temps qu'il faut, sans plus aucun
# échange, pour que l'ancre ait parcouru la moitié du chemin vers le repos
# commun. Deux écrivains la déplaçaient — un relevé, une réhydratation — et
# aucun ne la ramenait jamais vers le neutre : une brouille de quarante tours
# installait un repos `frustrated` mesuré identique après 1 h, 6 h et 24 h de
# silence complet. Une rancune humaine s'émousse toute seule ; il faut juste
# que ce soit LENT devant une conversation (α = 0.15 par tour), sans quoi
# l'attachement ne se construirait jamais. Trois jours : une brouille du lundi
# est encore lisible le mercredi, oubliée la semaine suivante.
ANCHOR_HEAL_HALF_LIFE_S = 3 * 86400.0

# « Bien ancrée » : une stance construite, pas déclenchée une fois.
ANCHORED_MIN_NORM = 0.4
ANCHORED_MIN_IMPULSES = 2
ANCHORED_WINDOW_S = 900.0


@dataclass(frozen=True)
class TurnEmotionView:
    """Ce qu'un tour porte comme émotion, côté sortie.

    La balise ``[EMOTION:]`` est la vérité du tour : c'est ce que le modèle a
    choisi en écrivant sa réponse. L'oscillateur, lui, dit où en est la
    relation — utile, mais ce n'est pas ce qui vient d'être dit.
    """
    emotion: str
    intensity: float
    blend: list[tuple[str, float]]
    state: dict
    declared: bool


def _heal_half_life_seconds() -> float:
    """Demi-vie de la guérison d'une stance, en secondes.

    Le réglage est exposé en JOURS — c'est l'unité dans laquelle on raisonne
    (« une brouille du lundi est-elle encore là mercredi ? »), pas en secondes
    où la valeur par défaut s'écrit 259 200. La conversion vit ici, une fois,
    plutôt qu'à chacun des deux sites de lecture.
    """
    return cfg_float(
        "emotion.anchor_heal_half_life_days",
        ANCHOR_HEAL_HALF_LIFE_S / 86400.0,
        mini=1e-6,
    ) * 86400.0


def _clamp_anchor(vector: Vec3) -> Vec3:
    limite = cfg_float(
        "emotion.anchor_max_norm", ANCHOR_MAX_NORM, mini=0.0,
    )
    magnitude = pad.norm(vector)
    if magnitude <= limite:
        return vector
    return pad.scale(vector, limite / magnitude)


class EmotionEngine:
    """Central emotion orchestrator, PAD-dimensional + damped oscillator.

    Three layers:
    1. Per-person mood  (person_moods)  — one oscillator per person
    2. Global mood       (global_mood)   — one oscillator for overall state
    3. Message emotion   (computed)      — blend of person + global per message

    Persistence strategy (two-tier, backwards-compatible schema):
    - EmotionSnapshot  : (label, intensity) pairs, retained for
                         EMOTION_SNAPSHOT_RETENTION_DAYS. Restored lossy
                         via label_to_pad().
    - EmotionalSummary : daily aggregates built by the consolidator, used
                         as fallback when snapshots were pruned.
    """

    _SNAPSHOT_DECAY_DAYS: int = 2
    _SUMMARY_DECAY_DAYS: int = 30
    # Idle cleanup: remove persons untouched for this long with no emotion.
    _IDLE_EVICTION_SECONDS: int = 3600

    def __init__(self):
        self.person_moods: dict[str, PersonMood] = {}
        self.global_mood = GlobalMood()
        self.temperament = Temperament()
        self._person_params = OscillatorParams()
        self._global_params = OscillatorParams()
        self._decay_task: asyncio.Task | None = None
        self._initialized = False
        self._last_snapshot_time: dict[str, float] = {}
        self._snapshot_interval: int = 30
        # Protects the snapshot-interval check. Without it, two concurrent
        # process_message() calls for the same person_id could both read
        # the old timestamp, both see "enough time has passed", and both
        # insert a snapshot. Cheap lock, always contended briefly only.
        self._snapshot_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self):
        """Load temperament from personality, restore state, start decay loop."""
        if self._initialized:
            return

        from config.personality import personality
        self.temperament = personality.temperament
        self._recompute_params()

        from configs.service import config_service
        self._snapshot_interval = config_service.get("emotion.snapshot_interval")
        self._SNAPSHOT_DECAY_DAYS = config_service.get("emotion.snapshot_retention_days")
        config_service.on_change(
            "emotion.snapshot_interval",
            lambda k, v: setattr(self, "_snapshot_interval", v),
        )
        # Le tempérament est déclaré ``hot_reload`` : les cinq curseurs se
        # règlent en regardant l'humeur qu'ils gouvernent bouger, ce qui n'a
        # aucun sens si la valeur n'est relue qu'au démarrage. Recharger le
        # tempérament ne suffit pas — ``_recompute_params`` en dérive la masse,
        # la raideur et l'amortissement de l'oscillateur, et c'est cela que la
        # boucle lit à chaque pas.
        config_service.on_change(
            TEMPERAMENT_PREFIX, lambda k, v: self._reload_temperament(k),
        )

        restored = await self._restore_state()

        self._decay_task = asyncio.create_task(self._decay_loop())
        self._initialized = True
        logger.info(
            "EmotionEngine initialized (temperament: volatility=%.1f, "
            "intensity_base=%.1f, recovery=%.1f, default_mood=%s, bleed=%.1f)"
            "%s",
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
            " [restored from snapshot]" if restored else "",
        )

    async def shutdown(self):
        """Stop the decay loop, then save emotional state.

        In that order: the decay loop evicts idle persons, and `_save_state`
        awaits once per person — saving while it runs is iterating a dict
        somebody else is writing.
        """
        if self._decay_task:
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass

        await self._save_state()
        logger.info("EmotionEngine shut down (state saved)")

    def _reload_temperament(self, key: str) -> None:
        """Re-read the temperament after a dashboard edit and re-derive params."""
        self.temperament = load_temperament()
        self._recompute_params()
        logger.info(
            "Temperament reloaded after %s changed (volatility=%.2f, "
            "intensity_base=%.2f, recovery=%.2f, default_mood=%s, bleed=%.2f)",
            key,
            self.temperament.volatility,
            self.temperament.intensity_base,
            self.temperament.recovery_speed,
            self.temperament.default_mood.value,
            self.temperament.global_bleed,
        )

    def _recompute_params(self) -> None:
        """Derive OscillatorParams from the current temperament.

        Scaling choices:
        - `recovery_speed` fixes the time constant τ, geometrically between
          PERSON_TAU_SLOW and PERSON_TAU_FAST. It used to set the *stiffness*,
          which moves the oscillation frequency and nothing else: the decay
          envelope was c/2m, a function of `volatility` alone, so the cursor
          labelled "vitesse de récupération" changed no recovery at all
          (measured identical to five decimals across its whole range).
        - `damping = 2m/τ` is what makes that envelope exactly exp(-t/τ).
        - `volatility` keeps the mass, the damping ratio, and the size of the
          ratchet an impulse applies.
        """
        t = self.temperament
        volatility = max(0.05, min(1.0, t.volatility))
        recovery = max(0.05, min(1.0, t.recovery_speed))
        mass = max(0.25, min(4.0, 1.0 / volatility))

        tau_fast = cfg_float("emotion.person_tau_fast", PERSON_TAU_FAST, mini=1e-3)
        tau_slow = cfg_float("emotion.person_tau_slow", PERSON_TAU_SLOW, mini=1e-3)
        tau = tau_slow * (tau_fast / tau_slow) ** ((recovery - 0.05) / 0.95)
        zeta = 1.0 - 0.35 * volatility
        omega0 = 1.0 / (zeta * tau)

        self._person_params = OscillatorParams(
            mass=mass,
            stiffness=mass * omega0 * omega0,
            damping=2.0 * mass / tau,
            impulse_gain=min(
                cfg_float("emotion.ratchet_max", RATCHET_MAX, mini=0.0),
                cfg_float("emotion.ratchet_base", RATCHET_BASE, mini=0.0)
                * max(0.1, t.intensity_base) * (0.5 + 0.5 * volatility),
            ),
        )

        # Global mood is lazier: heavier mass, twice the time constant. The
        # bleed is applied *once*, here — Factor 3 of conscience/scoring.py
        # reads this same intensity at a 0.7 threshold, so anyone lowering this
        # gain is turning that factor off. No floor either: the cursor promises
        # "à 0 elle compartimente entièrement".
        global_mass = mass * 1.5
        global_tau = tau * cfg_float(
            "emotion.global_tau_factor", GLOBAL_TAU_FACTOR, mini=1e-3,
        )
        global_omega0 = 1.0 / (0.9 * global_tau)
        bleed = max(0.0, t.global_bleed)
        # Le plafond du gain global est lu ICI et dans
        # ``_global_impulse_params`` : il y était écrit deux fois, dont une en
        # littéral nu (``min(0.5, …)``). Deux plafonds pour une seule garde,
        # c'est deux plafonds qui divergent au premier réglage — les deux
        # sites lisent donc la même clé.
        plafond_global = self._global_ratchet_max()
        self._global_params = OscillatorParams(
            mass=global_mass,
            stiffness=global_mass * global_omega0 * global_omega0,
            damping=2.0 * global_mass / global_tau,
            impulse_gain=(
                0.0 if bleed <= 0.0
                else min(
                    plafond_global,
                    cfg_float("emotion.ratchet_global", RATCHET_GLOBAL, mini=0.0)
                    * bleed,
                )
            ),
        )

    @staticmethod
    def _global_ratchet_max() -> float:
        """Le plafond du gain d'impulsion vers l'humeur de fond, une fois."""
        return cfg_float(
            "emotion.global_ratchet_max", GLOBAL_RATCHET_MAX, mini=0.0,
        )

    # ------------------------------------------------------------------
    # State persistence (lossy label-level snapshots, no DB migration)
    # ------------------------------------------------------------------

    async def _save_state(self):
        """Persist current state as (label, intensity) snapshots per person + global."""
        from asgiref.sync import sync_to_async
        from memory.manager import memory_manager
        from memory.models import EmotionSnapshot

        conversation = memory_manager.conversation
        if not conversation:
            return

        try:
            g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation,
                person_id="__global__",
                primary_emotion=g_label.value,
                primary_intensity=g_intensity,
                global_emotion=g_label.value,
                global_intensity=g_intensity,
            )

            for pid, mood in list(self.person_moods.items()):
                p_label, p_intensity = pad.pad_to_label(mood.dynamic.position)
                await sync_to_async(EmotionSnapshot.objects.create)(
                    conversation=conversation,
                    person_id=pid,
                    primary_emotion=p_label.value,
                    primary_intensity=p_intensity,
                    global_emotion=g_label.value,
                    global_intensity=g_intensity,
                )

            logger.info(
                "Saved emotion state: global=%s(%.2f), %d person mood(s)",
                g_label.value, g_intensity, len(self.person_moods),
            )
        except Exception:
            logger.exception("Failed to save emotion state")

    async def _restore_state(self) -> bool:
        """Restore state from snapshots (+summary fallback). Lossy reconstruction.

        Chaque relevé est d'abord VIEILLI par l'oscillateur lui-même
        (``_aged_position``) du temps écoulé depuis son écriture : l'état
        restauré est celui que la boucle aurait atteint si le processus
        n'avait pas cessé, vitesse nulle, et non le relevé tel quel.
        """
        from asgiref.sync import sync_to_async
        from django.db.models import Max
        from memory.models import EmotionSnapshot

        max_age_seconds = self._SNAPSHOT_DECAY_DAYS * 86400

        try:
            now_ts = time.time()

            latest_ids = await sync_to_async(
                lambda: list(
                    EmotionSnapshot.objects
                    .values("person_id")
                    .annotate(latest_id=Max("id"))
                    .values_list("latest_id", flat=True)
                )
            )()

            persons_from_snapshots: set[str] = set()
            restored_persons = 0
            home = self._home_vector()

            if latest_ids:
                snapshots = await sync_to_async(
                    lambda: list(EmotionSnapshot.objects.filter(id__in=latest_ids))
                )()

                for snap in snapshots:
                    elapsed = now_ts - snap.created_at.timestamp()
                    # Un relevé plus vieux que la rétention ne dit plus rien
                    # de la position (il devrait d'ailleurs être purgé) :
                    # on laisse ``_restore_from_summaries`` remplir, comme
                    # avant, plutôt que d'inscrire la personne dans
                    # l'ensemble d'exclusion.
                    if elapsed > max_age_seconds:
                        continue

                    try:
                        label = Emotion(snap.primary_emotion)
                    except ValueError:
                        label = self.temperament.default_mood

                    cible = pad.label_to_pad(label, snap.primary_intensity)

                    if snap.person_id == "__global__":
                        self.global_mood.dynamic.position = self._aged_position(
                            cible, home, elapsed, self._global_params,
                        )
                        self.global_mood.dynamic.velocity = pad.zero()
                    else:
                        # L'ensemble sert a NE PAS ecraser depuis un resume ce
                        # qu'un releve vient de charger : n'y inscrire que ce
                        # qui est effectivement charge.
                        persons_from_snapshots.add(snap.person_id)
                        mood = PersonMood(person_id=snap.person_id)
                        # Sans ancre à ce stade (``ensure_person_loaded`` la
                        # comble à la première lecture) : le repos est le
                        # repos commun, et le relevé y est ramené selon
                        # l'enveloppe de l'oscillateur.
                        mood.dynamic.position = self._aged_position(
                            cible, home, elapsed, self._person_params,
                        )
                        self.person_moods[snap.person_id] = mood
                        restored_persons += 1

            summary_restored = await self._restore_from_summaries(
                exclude_persons=persons_from_snapshots
            )
            restored_persons += summary_restored

            if (
                restored_persons == 0
                and pad.distance(self.global_mood.dynamic.position, home) < 0.05
            ):
                return False

            g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)
            logger.info(
                "Restored emotion state: global=%s(%.2f), %d person(s) "
                "[snapshots: %d, summaries: %d]",
                g_label.value, g_intensity,
                restored_persons,
                restored_persons - summary_restored,
                summary_restored,
            )
            return True

        except Exception:
            logger.exception("Failed to restore emotion state")
            return False

    async def _restore_from_summaries(self, exclude_persons: set[str]) -> int:
        """Seed person moods from EmotionalSummary for persons not already loaded."""
        from asgiref.sync import sync_to_async
        from memory.models import EmotionalSummary

        try:
            # Au-delà du seuil, une ligne ne produit plus aucune humeur : la
            # borne appartient au WHERE, pas à une boucle Python qui aurait
            # d'abord fait grouper tout l'historique de la table.
            cutoff = date.today() - timedelta(days=self._summary_decay_days())

            # Une seule requête, servie par l'index (person_id, -period_start) :
            # les lignes arrivent groupées par personne, la plus récente en
            # tête, donc la première rencontrée est celle qu'on veut. La version
            # groupée redemandait ces mêmes colonnes personne par personne —
            # 1 + N allers-retours sérialisés sur le thread partagé de
            # sync_to_async, pendant que le lifespan ASGI démarre le reste.
            rows = await sync_to_async(
                lambda: list(
                    EmotionalSummary.objects
                    .filter(period_type="daily", period_start__gt=cutoff)
                    .exclude(person_id__in=exclude_persons)
                    .order_by("person_id", "-period_start")
                    .values(
                        "person_id",
                        "period_start",
                        "dominant_emotion",
                        "dominant_intensity",
                    )
                )
            )()

            restored = 0
            seen: set[str] = set()
            for row in rows:
                pid = row["person_id"]
                if pid in seen:
                    continue
                seen.add(pid)

                result = self._faded_mood(
                    row["period_start"],
                    row["dominant_emotion"],
                    row["dominant_intensity"],
                )
                if result is None:
                    continue

                label, intensity = result
                mood = PersonMood(person_id=pid)
                mood.dynamic.position = pad.label_to_pad(label, intensity)
                self.person_moods[pid] = mood
                restored += 1

            return restored

        except Exception as exc:
            degradations.record("emotion.engine._restore_from_summaries", exc)
            logger.debug("Failed to restore from summaries", exc_info=True)
            return 0

    def _summary_decay_days(self) -> int:
        """Horizon d'exploitation d'un ``EmotionalSummary``, en jours.

        L'attribut de classe reste le repli. ``_SNAPSHOT_DECAY_DAYS``, lui,
        est déjà chargé une fois à l'``initialize()`` : c'est une rétention
        de table, pas un curseur qu'on essaie en regardant l'humeur bouger.
        """
        return cfg_int(
            "emotion.summary_retention_days", self._SUMMARY_DECAY_DAYS, mini=1,
        )

    def _faded_mood(
        self,
        period_start: date,
        dominant_emotion: str,
        dominant_intensity: float,
    ) -> tuple[Emotion, float] | None:
        """Return (emotion, intensity) faded by the age of a daily summary row.

        La seule formulation du seuil ``_SUMMARY_DECAY_DAYS`` : la restauration
        au démarrage et le chargement paresseux par personne lisent la même
        règle, et ne peuvent donc plus en garder deux versions.
        """
        # Lu une fois : le seuil et le ratio doivent parler du même horizon,
        # y compris si le réglage change entre les deux lignes.
        horizon = self._summary_decay_days()
        age_days = (date.today() - period_start).days
        if age_days >= horizon:
            return None

        time_factor = max(0.0, 1.0 - age_days / horizon)
        intensity = dominant_intensity * time_factor

        if intensity < 0.05:
            return None

        try:
            emotion = Emotion(dominant_emotion)
        except ValueError:
            return None

        return emotion, intensity

    async def _mood_from_summary(self, person_id: str) -> tuple[Emotion, float] | None:
        """Return (emotion, intensity) seeded from the most recent EmotionalSummary."""
        from asgiref.sync import sync_to_async
        from memory.models import EmotionalSummary

        try:
            summary = await sync_to_async(
                lambda: EmotionalSummary.objects
                .filter(person_id=person_id, period_type="daily")
                .order_by("-period_start")
                .first()
            )()

            if not summary:
                return None

            return self._faded_mood(
                summary.period_start,
                summary.dominant_emotion,
                summary.dominant_intensity,
            )

        except Exception as exc:
            degradations.record("emotion.engine._mood_from_summary", exc)
            logger.debug(
                "Failed to load EmotionalSummary for %s", person_id, exc_info=True
            )
            return None

    @staticmethod
    def _tau_of(params: OscillatorParams) -> float:
        """Constante de temps du retour au repos, en secondes.

        ``_recompute_params`` pose ``damping = 2m/τ`` précisément pour que
        l'enveloppe de retour soit exp(−t/τ) ; on la relit ici plutôt que de
        la recalculer depuis le tempérament, pour que la restauration et la
        boucle physique parlent de la même constante.
        """
        return 2.0 * params.mass / max(1e-9, params.damping)

    def _person_tau(self) -> float:
        return self._tau_of(self._person_params)

    def _global_tau(self) -> float:
        """L'humeur de fond est deux fois plus paresseuse."""
        return self._tau_of(self._global_params)

    #: Au-delà de tant de constantes de temps, un relevé ne dit plus rien de
    #: la position : c'est le repos (exp(−10) < 5 · 10⁻⁵, oscillation comprise).
    _AGED_HORIZON_TAUS = 10.0

    @classmethod
    def _aged_position(
        cls, cible: Vec3, home: Vec3, elapsed: float, params: OscillatorParams,
    ) -> Vec3:
        """Où l'oscillateur en serait, parti de ``cible`` il y a ``elapsed`` s.

        On fait tourner l'oscillateur lui-même — le même ``_advance`` que la
        boucle, depuis la position du relevé au repos (vitesse nulle) — et
        non une droite sur deux jours : à τ ≈ 11,6 min, un relevé ``angry
        0.8`` vieux d'une heure vaut le repos, alors que la droite en gardait
        98 %. Mesuré : l'oscillateur vivant lisait ``hopeful 0.11`` une heure
        après la colère, la réhydratation rendait ``angry 0.73`` — et encore
        ``angry 0.56`` douze heures plus tard. Une éviction (une heure
        d'inactivité, au repos) suivie d'une reconnexion ressuscitait donc
        une émotion déjà digérée ; même chose au redémarrage sans relevé
        d'arrêt.

        Intégrer plutôt qu'appliquer exp(−t/τ) : l'humeur de fond est
        sous-amortie (ζ = 0,9) et garde à 1 h 17 % de l'écart là où
        l'enveloppe seule en prédit 7 %. « Ce que l'oscillateur vivant
        lirait » est la seule définition qui ne dérive pas.

        Le relevé est pris pour la position qu'il porte, sans lui appliquer
        le cliquet : une ligne d'arrêt (``_save_state``) EST une position, et
        une ligne de tour porte la balise déclarée quelques minutes plus tôt
        — ce que ``DECLARED_WINDOW_S`` tient de toute façon pour actuel sur
        cette durée. Seule la partie non encore digérée du relevé est
        restaurée ; le reste est le repos.
        """
        horizon = cls._AGED_HORIZON_TAUS * cls._tau_of(params)
        elapsed = max(0.0, elapsed)
        if elapsed >= horizon:
            return home
        etat = OscillatorState(position=cible)
        cls._advance(etat, home, params, elapsed, max_advance=horizon)
        return etat.position

    async def _backfill_anchor(self, mood: "PersonMood") -> None:
        """Recalcule l'ancre d'une humeur restaurée sans elle.

        Une seule requête, une seule fois par personne et par processus : au
        retour, ``mood.anchor`` n'est plus ``None`` (même si les relevés ne
        donnent rien, on pose le repos circadien courant plutôt que de
        rejouer la requête à chaque tour).
        """
        try:
            from asgiref.sync import sync_to_async
            from memory.models import EmotionSnapshot

            echantillon = cfg_int(
                "emotion.anchor_sample", ANCHOR_SAMPLE, mini=1,
            )
            snaps = await sync_to_async(
                lambda: list(
                    EmotionSnapshot.objects
                    .filter(person_id=mood.person_id)
                    .order_by("-created_at")[:echantillon]
                )
            )()
            ancre = self._anchor_from_snapshots(snaps) if snaps else None
            mood.anchor = ancre if ancre is not None else self._home_vector()
        except Exception as exc:
            degradations.record("emotion.engine._backfill_anchor", exc)
            mood.anchor = self._home_vector()

    async def ensure_person_loaded(self, person_id: str) -> None:
        """Hydrate a person's mood from DB if they are not currently in RAM.

        La question « est-ce une vraie personne ? » a un seul domicile,
        ``identity/trust.py`` : la redire ici l'avait déjà fait diverger
        (``conscience_mika``, ``""`` et tout le préfixe ``anon_*`` passaient
        au travers). Un handle éphémère est un uuid frappé quelques secondes
        plus tôt : il ne peut par construction porter ni relevé ni résumé, et
        chaque socket anonyme payait deux requêtes garanties vides.
        """
        if not is_identifiable_person(person_id):
            return
        existante = self.person_moods.get(person_id)
        if existante is not None:
            # `_restore_state` et `_restore_from_summaries` repeuplent
            # `person_moods` au démarrage SANS jamais écrire d'ancre, et cette
            # fonction est la seule à savoir la recalculer. Un simple « déjà en
            # RAM » la rendait donc irrécupérable pour toute la durée du
            # processus : ce qui distingue un ami d'un troll était remis à zéro
            # par le moindre redémarrage. On repasse une fois pour combler
            # l'ancre manquante — jamais pour réécrire la position, qui est
            # vivante.
            if existante.anchor is None:
                await self._backfill_anchor(existante)
            return

        now_ts = time.time()

        try:
            from asgiref.sync import sync_to_async
            from memory.models import EmotionSnapshot

            # Same query, same (person_id, -created_at) index: the newest row
            # still gives the position, the tail gives the personal anchor.
            echantillon = cfg_int(
                "emotion.anchor_sample", ANCHOR_SAMPLE, mini=1,
            )
            snaps = await sync_to_async(
                lambda: list(
                    EmotionSnapshot.objects
                    .filter(person_id=person_id)
                    .order_by("-created_at")[:echantillon]
                )
            )()

            snap = snaps[0] if snaps else None
            if snap:
                # Dès qu'un relevé existe, c'est lui qui répond — jamais le
                # résumé quotidien, plus vieux et plus grossier. Retomber sur
                # le résumé quand le relevé a « trop vieilli » ressuscitait
                # l'émotion dominante de la veille pour quelqu'un dont
                # l'oscillateur s'était justement apaisé.
                elapsed = max(0.0, now_ts - snap.created_at.timestamp())
                mood = PersonMood(person_id=person_id)
                mood.anchor = self._anchor_from_snapshots(snaps)
                home = self._person_home(mood)
                try:
                    label = Emotion(snap.primary_emotion)
                except ValueError:
                    label = None
                if label is None:
                    mood.dynamic.position = home
                else:
                    mood.dynamic.position = self._aged_position(
                        pad.label_to_pad(label, snap.primary_intensity),
                        home, elapsed, self._person_params,
                    )
                self.person_moods[person_id] = mood
                logger.debug(
                    "Lazy-loaded mood for %s: %s from snapshot ~%dh ago "
                    "(aged to %s)",
                    person_id, snap.primary_emotion, int(elapsed / 3600),
                    pad.pad_to_label(mood.dynamic.position)[0].value,
                )
                return

            result = await self._mood_from_summary(person_id)
            if result is not None:
                label, intensity = result
                mood = PersonMood(person_id=person_id)
                mood.dynamic.position = pad.label_to_pad(label, intensity)
                self.person_moods[person_id] = mood
                logger.debug(
                    "Lazy-loaded mood for %s: %s(%.2f) from EmotionalSummary",
                    person_id, label.value, intensity,
                )

        except Exception as exc:
            degradations.record("emotion.engine.ensure_person_loaded", exc)
            logger.debug(
                "Failed to lazy-load mood for %s", person_id, exc_info=True
            )

    # ------------------------------------------------------------------
    # Periodic snapshots (for emotional memory)
    # ------------------------------------------------------------------

    async def save_snapshot(
        self, person_id: str, declared: EmotionData | None = None,
    ) -> None:
        """Save a snapshot if enough time has passed since the last one.

        `declared` is what the turn's [EMOTION:] tag said, when there was one;
        that is what gets persisted, since it is what she meant by the reply
        the snapshot is supposed to remember.

        The throttle is stamped on the *write*, not on the attempt: stamping
        first meant one message closed the next 30 seconds, and a failed write
        closed them for nothing. The lock now covers the write too, so
        snapshots for one person serialise — they are rare by construction.
        """
        async with self._snapshot_lock:
            now = time.time()
            last = self._last_snapshot_time.get(person_id, 0)
            if now - last < self._snapshot_interval:
                return
            if await self._save_person_snapshot(person_id, declared):
                self._last_snapshot_time[person_id] = time.time()

    # Ancien nom, gardé le temps que le processor bascule sur `save_snapshot`.
    async def _maybe_save_snapshot(self, person_id: str) -> None:
        await self.save_snapshot(person_id)

    async def _save_person_snapshot(
        self, person_id: str, declared: EmotionData | None = None,
    ) -> bool:
        """Persist a single EmotionSnapshot for one person + current global mood.

        Returns whether a row was actually written.
        """
        from asgiref.sync import sync_to_async
        from memory.manager import memory_manager
        from memory.models import EmotionSnapshot

        conversation = memory_manager.conversation
        if not conversation:
            return False

        person = self._get_person_mood(person_id)
        if declared is not None:
            p_label, p_intensity = declared.emotion, declared.intensity
        else:
            p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
        # The background mood is never what a turn declared: it stays read off
        # the global oscillator.
        g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)

        try:
            await sync_to_async(EmotionSnapshot.objects.create)(
                conversation=conversation,
                person_id=person_id,
                primary_emotion=p_label.value,
                primary_intensity=p_intensity,
                global_emotion=g_label.value,
                global_intensity=g_intensity,
            )
        except Exception as exc:
            degradations.record("emotion.engine._save_person_snapshot", exc)
            logger.debug("Failed to save snapshot for %s", person_id, exc_info=True)
            return False

        self._note_anchor(person, pad.label_to_pad(p_label, p_intensity))
        return True

    def _note_anchor(self, mood: PersonMood, position: Vec3) -> None:
        """Fold a written snapshot into this person's own resting point.

        Fed from what was *persisted*, so the anchor and the record tell the
        same story — the tag when a turn declared one.
        """
        # Pas de premier relevé « à 100 % » : une ancre naît AU REPOS COMMUN
        # et le premier relevé s'y fond à α comme tous les suivants. Sinon un
        # seul ``[EMOTION:angry:0.8]`` envers un inconnu posait l'ancre au
        # plafond (0,7) — « légèrement en colère » une heure plus tard,
        # encore teintée après trois jours de silence, trois tours chaleureux
        # pour la retourner — ce que le contrat de ``PersonMood.anchor``
        # (« jamais une lecture instantanée ») interdit précisément.
        alpha = cfg_float("emotion.anchor_alpha", ANCHOR_ALPHA, mini=0.0, maxi=1.0)
        courante = mood.anchor if mood.anchor is not None else self._home_vector()
        mood.anchor = _clamp_anchor(pad.add(
            pad.scale(courante, 1.0 - alpha),
            pad.scale(position, alpha),
        ))

    def _anchor_from_snapshots(self, rows) -> Vec3 | None:
        """Recency-weighted mean of what a person has already provoked.

        Le résultat est ensuite VIEILLI du temps écoulé depuis le relevé le
        plus récent, avec la même demi-vie que ``_heal_anchor``. Sans cela,
        l'éviction rouvrait la porte que la guérison venait de fermer : une
        humeur inactive sort de la RAM au bout d'une heure, et la
        réhydratation reconstruisait l'ancre à partir de vingt vieilles
        déclarations — ramenant intacte, des semaines plus tard, une stance
        que le temps avait justement effacée.
        """
        try:
            total = 0.0
            lignes_valides = 0
            accumulated = pad.zero()
            for index, row in enumerate(rows):
                try:
                    label = Emotion(row.primary_emotion)
                except ValueError:
                    continue
                lignes_valides += 1
                weight = float(len(rows) - index)
                accumulated = pad.add(
                    accumulated,
                    pad.scale(pad.label_to_pad(label, row.primary_intensity), weight),
                )
                total += weight

            if total <= 0.0:
                return None
            moyenne = pad.scale(accumulated, 1.0 / total)
            home = self._home_vector()

            # Même poids qu'une suite de relevés fondus un à un à α depuis le
            # repos (``_note_anchor``) : après n relevés il reste (1−α)ⁿ de
            # repos dans l'ancre. Une seule ligne pèse donc α, pas 1 — la
            # moyenne pondérée seule rendait à la réhydratation le défaut
            # que ``_note_anchor`` vient de perdre : une ligne, une ancre au
            # plafond.
            alpha = cfg_float(
                "emotion.anchor_alpha", ANCHOR_ALPHA, mini=0.0, maxi=1.0,
            )
            part_releves = 1.0 - (1.0 - alpha) ** lignes_valides
            ancre = _clamp_anchor(pad.add(
                pad.scale(home, 1.0 - part_releves),
                pad.scale(moyenne, part_releves),
            ))

            # `getattr` : une ligne peut ne pas porter de date (relevé
            # partiel, substitut de test). Sans horodatage on ne vieillit
            # simplement pas — jamais on ne perd l'ancre pour autant.
            dates = [
                d for d in (getattr(r, "created_at", None) for r in rows)
                if d is not None and hasattr(d, "timestamp")
            ]
            recent = max(dates, default=None)
            if recent is not None:
                age = max(0.0, time.time() - recent.timestamp())
                part = 1.0 - 0.5 ** (age / _heal_half_life_seconds())
                if part > 0.0:
                    ancre = _clamp_anchor(pad.add(
                        pad.scale(ancre, 1.0 - part), pad.scale(home, part),
                    ))
            return ancre
        except Exception as exc:
            degradations.record("emotion.engine._anchor_from_snapshots", exc)
            return None

    # ------------------------------------------------------------------
    # Person mood management
    # ------------------------------------------------------------------

    def _get_person_mood(self, person_id: str) -> PersonMood:
        """Get or create mood state for a person. New persons start at origin."""
        if person_id not in self.person_moods:
            self.person_moods[person_id] = PersonMood(person_id=person_id)
        return self.person_moods[person_id]

    def _home_vector(self) -> Vec3:
        """Home position for all oscillators.

        Combines two contributions:
          - `default_mood` heavily dimmed (magnitude 0.15) — the character's
            stable baseline personality
          - `circadian phase bias` (magnitude ~0.35 per circadian.py) — a
            time-of-day tint that nudges the baseline toward hopeful/playful/
            relieved/dreamy through the day

        Both are small so that emotional impulses still dominate the
        short-term dynamics — but the persistent pull gives Mika a felt
        "daily rhythm" without the character losing its identity.
        """
        from emotion import circadian

        base = pad.label_to_pad(
            self.temperament.default_mood,
            cfg_float("emotion.home_default_mood_weight", HOME_DEFAULT_MOOD_WEIGHT,
                      mini=0.0),
        )

        try:
            from config.personality import personality
            profile = personality.circadian_profile
        except Exception as exc:
            degradations.record("emotion.engine._home_vector", exc)
            profile = None

        state = circadian.current_state(profile=profile)
        # ``phase_bias`` reste une fonction PURE : c'est ici, au site d'appel,
        # que la configuration est lue, et l'amplitude lui est passée. Faire
        # lire la base à ``emotion/circadian.py`` aurait rendu impur un module
        # dont toute la testabilité tient à ce qu'il ne l'est pas.
        bias = circadian.phase_bias(
            state.phase,
            profile=profile,
            magnitude=circadian.configured_bias_magnitude(),
        )

        return pad.add(base, bias)

    @staticmethod
    def _heal_anchor(mood: PersonMood, home: Vec3, dt: float) -> None:
        """Rapproche lentement la stance envers quelqu'un du repos commun.

        Le seul mouvement de l'ancre venait des relevés — donc de nouvelles
        déclarations. Sans échange, elle ne bougeait pas d'un pouce : une
        stance négative installée un soir était encore là mot pour mot le
        lendemain, et seule une vingtaine de tours chaleureux pouvait la
        défaire. Le temps compte aussi, et beaucoup plus lentement que les
        mots — c'est ce rapport qui donne à la fois de la rancune et du pardon.
        """
        if mood.anchor is None or dt <= 0.0:
            return
        part = 1.0 - 0.5 ** (dt / _heal_half_life_seconds())
        if part <= 0.0:
            return
        mood.anchor = _clamp_anchor(pad.add(
            pad.scale(mood.anchor, 1.0 - part),
            pad.scale(home, part),
        ))

    def _person_home(self, mood: PersonMood, base: Vec3 | None = None) -> Vec3:
        """Resting point of one person's oscillator.

        A stance has to come back *somewhere*, and coming back to the same
        circadian point for everybody made "envers cette personne" the same
        hourly boilerplate for a friend, a troll and a stranger. The anchor is
        a smoothed trace of what this person has already provoked.

        The loop closes (anchor ← snapshots ← position ← home ← anchor) and
        that is safe on purpose: its fixed point is `base` itself, since an
        anchor equal to the circadian home reproduces exactly that home. No
        runaway is possible.
        """
        if base is None:
            base = self._home_vector()
        if mood.anchor is None:
            return base
        poids = cfg_float(
            "emotion.person_anchor_weight", PERSON_ANCHOR_WEIGHT,
            mini=0.0, maxi=1.0,
        )
        return pad.add(
            pad.scale(mood.anchor, poids),
            pad.scale(base, 1.0 - poids),
        )

    # ------------------------------------------------------------------
    # Core: process a new emotion from Claude
    # ------------------------------------------------------------------

    def _global_impulse_params(self, intensity: float) -> OscillatorParams:
        """Les paramètres du global pour CETTE impulsion-ci.

        Identiques à ``_global_params`` sauf le gain, qui suit l'intensité
        déclarée : à 1.0 une émotion pleine traverse presque autant que sur
        l'oscillateur de la personne, à 0.2 elle ne fait qu'effleurer. Le
        plafond reste la garde contre un tempérament très perméable.
        """
        base = self._global_params
        if base.impulse_gain <= 0.0:
            return base
        force = max(0.0, min(1.0, intensity))
        # INVARIANT : plancher + pente == facteur maximal (0.4 + 1.6 = 2.0).
        # Les trois sont réglables séparément parce qu'ils décrivent trois
        # choses (le seuil d'effleurement, la sensibilité, le plafond), mais
        # les désaccorder fait mordre le plafond avant l'intensité 1.0 — ou le
        # rend inatteignable, ce qui revient à le supprimer.
        gain = min(
            self._global_ratchet_max(),
            base.impulse_gain * cfg_float(
                "emotion.global_gain_max_factor", GLOBAL_GAIN_MAX_FACTOR, mini=0.0,
            ),
            base.impulse_gain * (
                cfg_float("emotion.global_gain_floor", GLOBAL_GAIN_FLOOR, mini=0.0)
                + cfg_float("emotion.global_gain_slope", GLOBAL_GAIN_SLOPE, mini=0.0)
                * force
            ),
        )
        return dataclasses.replace(base, impulse_gain=gain)

    def _person_impulse_params(self, target: Vec3) -> OscillatorParams:
        """Le gain de CETTE impulsion, accordé au fond du tempérament.

        cos entre la cible déclarée et l'ancre de ``default_mood`` : une
        mélancolique vibre plus fort à la tristesse, une explosive à
        l'exaltation. Retenu **seulement positif** — voir la note de
        ``RESONANCE_STRENGTH`` : la résistance au contraire existe déjà
        (rappel + point de repos), la redoubler ici blinderait le personnage.

        Un ``default_mood`` neutre a une ancre nulle : cos indéfini, gain
        inchangé — un tempérament sans fond marqué ne résonne avec rien, ce
        qui est la définition du stoïque. Le plafond est 1.0, l'invariant du
        cliquet lui-même, et non ``ratchet_max`` : celui-ci borne ce qu'un
        *tempérament* peut se déclarer, pas ce qu'un événement qui tombe
        juste dans son grain peut lui faire.
        """
        base = self._person_params
        k = cfg_float("emotion.resonance_strength", RESONANCE_STRENGTH, mini=0.0)
        if k <= 0.0 or base.impulse_gain <= 0.0:
            return base
        ancre = pad.label_to_pad(self.temperament.default_mood, 1.0)
        n_ancre, n_cible = pad.norm(ancre), pad.norm(target)
        if n_ancre <= 1e-9 or n_cible <= 1e-9:
            return base
        cos = pad.dot(ancre, target) / (n_ancre * n_cible)
        if cos <= 0.0:
            return base
        gain = min(1.0, base.impulse_gain * (1.0 + k * cos))
        return dataclasses.replace(base, impulse_gain=gain)

    def _feel_for_herself(self, emotion_data: EmotionData) -> None:
        """Une impulsion de sa propre vie intérieure, sur l'humeur de fond.

        L'ennui, la solitude, un chantier bloqué ou abouti, l'espoir, la
        surprise d'une croyance révisée arrivent sous ``conscience_mika`` :
        ce n'est pas une stance envers quelqu'un qui *déteint* sur le fond,
        c'est le fond lui-même qui bouge. Or elles passaient par le chemin de
        la diffusion, taillé pour l'autre cas — cible ``ancre × intensité``
        et gain global 0,135 × (0,4 + 1,6·I). Une impulsion ``bored 0.25``
        visait donc un point de norme 0,17, c'est-à-dire surtout le neutre,
        avec un gain de 0,11, et τ_global (23 min) en effaçait 73 % avant la
        suivante, une demi-heure plus tard. Mesuré : huit ``bored 0.25``
        demi-horaires laissaient l'humeur de fond ``hopeful 0.07`` ; un
        chantier bloqué (``frustrated 0.35``) déplaçait la valence de −0,04.
        Rien de la vie intérieure n'atteignait jamais
        ``--- TON ETAT EMOTIONNEL ACTUEL ---``.

        Ici l'intensité dose le PAS et non la cible : la position avance de
        ``gain × I`` vers l'ancre PLEINE de l'émotion, ``gain`` étant celui
        de la personne — résonance du tempérament comprise, comme pour
        n'importe quelle stance. Depuis le repos, c'est exactement le premier
        pas qu'une personne provoquerait (``gain × I × ancre``) ; ce qui
        change, c'est la direction, toujours celle de l'émotion nommée et
        jamais celle de l'origine, et l'asymptote, l'ancre pleine. Un pas
        « léger » (``anxious 0.1`` à l'échec d'un tour) reste léger : 5 % du
        chemin. Mesuré à repos fixe : ``frustrated 0.35`` parcourt 18 % du
        chemin vers son ancre (5 % avant) et fait −0,11 de valence ; huit
        ``bored 0.25`` demi-horaires laissent ``nostalgic`` — arousal
        négatif, 20 % du chemin vers l'ennui, plus « comme d'habitude » —
        et non ``bored`` : à 30 min d'espacement contre τ_global = 23 min,
        l'accumulation plafonne à ~1,4 impulsion, et ce sont les constantes
        de la conscience (``conscience.ennui.intensite`` 0,25, espacement
        30 min) ou ``emotion.global_tau_factor`` qui décident si l'ennui
        finit par se *nommer* ; à 0,4 il se nomme.

        Le gain est borné à 1 AVANT d'être dosé : ``apply_impulse`` le borne
        de toute façon, donc c'est bien la part du gain effectif qu'on veut,
        pas la part d'un gain hors d'échelle (une configuration aberrante
        ferait sinon sauter la position sur l'ancre pleine à I = 0,1).
        Réservé aux identifiants internes (``identity.trust.is_internal_person``) :
        pas un chiffre de la diffusion personne → fond ne bouge.
        """
        ancre = pad.label_to_pad(emotion_data.emotion, 1.0)
        force = max(0.0, min(1.0, emotion_data.intensity))
        if force <= 0.0 or pad.norm(ancre) <= 1e-9:
            return
        base = self._person_impulse_params(ancre)
        params = dataclasses.replace(
            base, impulse_gain=max(0.0, min(1.0, base.impulse_gain)) * force,
        )
        self.global_mood.dynamic.impulse_toward(ancre, params)

    def process_emotion(
        self, emotion_data: EmotionData, person_id: str
    ) -> PersonMood:
        """Apply a new emotion as a ratchet toward its PAD anchor.

        Successive impulses of the same sign escalate (each covers a share of
        what is left to the target), an opposing one brings the position back
        toward the other side, and the spring governs how long any of it stays
        readable.
        """
        self._recompute_params()  # in case temperament changed at runtime

        now = time.time()
        person = self._get_person_mood(person_id)

        target = pad.label_to_pad(emotion_data.emotion, emotion_data.intensity)
        person.dynamic.impulse_toward(target, self._person_impulse_params(target))
        # Ce qu'elle vient de dire éprouver, gardé tel quel à côté de la
        # position. Le prompt du tour suivant le relit plutôt que de demander
        # à `pad_to_label` de renommer un vecteur mélangé.
        person.last_declared = (emotion_data.emotion, emotion_data.intensity)
        person.last_declared_at = now

        # Propagate into the global mood. The bleed reduces the *gain*, once —
        # reducing the target as well capped the global mood around 0.30, well
        # under the 0.7 that Factor 3 of conscience/scoring.py tests, so that
        # factor could never fire.
        #
        # Le gain est modulé par l'INTENSITÉ déclarée : une contrariété passe
        # au travers, une détresse traverse. À gain fixe (0.135 au défaut),
        # `--- TON ETAT EMOTIONNEL ACTUEL ---` — le dernier bloc affectif avant
        # la mémoire, donc en zone de récence maximale — annonçait encore « ton
        # humeur générale est contente, comme d'habitude » au sixième tour d'une
        # conversation où quelqu'un finit par écrire « je pleure, j'en peux
        # plus ». Le bloc censé porter son ressenti était le plus lent de tous
        # à bouger, exactement là où le modèle le lit le plus fort.
        if is_internal_person(person_id):
            self._feel_for_herself(emotion_data)
        elif self.temperament.global_bleed > 0:
            self.global_mood.dynamic.impulse_toward(
                target, self._global_impulse_params(emotion_data.intensity),
            )

        person.last_interaction = now
        person.last_update = now
        self.global_mood.last_update = now

        person.history.append(EmotionHistoryEntry(
            timestamp=now,
            emotion=emotion_data.emotion,
            intensity=emotion_data.intensity,
            source="impulse",
        ))

        logger.debug(
            "Emotion [%s]: impulse toward %s(%.2f)",
            person_id, emotion_data.emotion.value, emotion_data.intensity,
        )

        return person

    # ------------------------------------------------------------------
    # Compute message emotion (blend of person + global)
    # ------------------------------------------------------------------

    def compute_message_emotion(self, person_id: str) -> MessageEmotion:
        """Compute the final emotion for a message by blending PAD positions.

        Weights: 60% person position + 40% global position in PAD space.
        The blend is a weighted mean of the two 3D vectors, then projected
        back onto the top-2 nearest anchors so the output can express
        ambivalence (e.g. "mostly grateful, a touch nostalgic").
        """
        person = self._get_person_mood(person_id)
        default = self.temperament.default_mood

        p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
        g_label, g_intensity = pad.pad_to_label(self.global_mood.dynamic.position)

        blended = pad.add(
            pad.scale(person.dynamic.position, 0.6),
            pad.scale(self.global_mood.dynamic.position, 0.4),
        )
        final_label, final_intensity = pad.pad_to_label(blended)
        blend_components = pad.pad_to_blend(blended, top_k=2)

        # If the blended vector is essentially zero, expose the default mood
        # as a weak background so the frontend doesn't get stuck on neutral.
        if final_intensity < 0.05:
            final_label = default
            final_intensity = 0.1
            if not blend_components:
                blend_components = [(default, 0.1)]

        return MessageEmotion(
            emotion=final_label,
            intensity=round(final_intensity, 2),
            person_emotion=p_label if p_intensity > 0.05 else default,
            person_intensity=round(p_intensity, 2),
            global_emotion=g_label if g_intensity > 0.05 else default,
            global_intensity=round(g_intensity, 2),
            blend=tuple(blend_components),
        )

    async def turn_emotion_view(
        self, person_id: str, declared: EmotionData | None,
    ) -> TurnEmotionView:
        """What the frame answering this turn should carry.

        Called after `process_emotion`, so the oscillator already holds the
        turn. When the reply declared a tag, that tag wins: it is what she
        chose while writing, where the oscillator only says how the relation
        stands. The blend is read on the projected position so the frame's
        `emotion` and its `blend[0]` can never disagree — the frontend's
        ambivalence gate reads exactly that pair.

        Never raises: a turn goes out with an emotion, or with the fallback.
        """
        try:
            return self._build_turn_view(person_id, declared)
        except Exception as exc:
            degradations.record("emotion: vue du tour", exc)
        return self._plain_turn_view(declared)

    def _build_turn_view(
        self, person_id: str, declared: EmotionData | None,
    ) -> TurnEmotionView:
        mood = self._get_person_mood(person_id)
        projected = dynamics.peak_projection(
            mood.dynamic.position,
            mood.dynamic.velocity,
            self._person_home(mood),
            self._person_params,
        )
        blend = [(e.value, w) for e, w in pad.pad_to_blend(projected, top_k=2)]
        state = self.get_state_dict(person_id)

        if declared is not None:
            name = declared.emotion.value
            if not blend or blend[0][0] != name:
                blend = [(name, declared.intensity), *blend][:2]
            return TurnEmotionView(
                emotion=name,
                intensity=declared.intensity,
                blend=blend,
                state=state,
                declared=True,
            )

        current = self.compute_message_emotion(person_id)
        if not blend:
            blend = [(e.value, w) for e, w in current.blend]
        return TurnEmotionView(
            emotion=current.emotion.value,
            intensity=current.intensity,
            blend=blend,
            state=state,
            declared=False,
        )

    def _plain_turn_view(self, declared: EmotionData | None) -> TurnEmotionView:
        """Fallback view — reads nothing, so it cannot fail in turn."""
        if declared is not None:
            name, intensity = declared.emotion.value, declared.intensity
        else:
            name, intensity = self.temperament.default_mood.value, 0.0
        return TurnEmotionView(
            emotion=name,
            intensity=intensity,
            blend=[(name, intensity)],
            state={},
            declared=declared is not None,
        )

    # ------------------------------------------------------------------
    # System prompt context
    # ------------------------------------------------------------------

    def get_global_mood_context(self) -> str:
        """French description of Mika's *standalone* emotional state.

        This is about Mika alone, independent of the interlocutor. The
        per-person affective stance belongs to `get_person_affect_context()`
        and is injected in the `person_context` block, not here.
        """
        default = self.temperament.default_mood
        return self.global_mood.to_prompt_description(
            default, home=self._home_vector(),
        )

    def get_person_affect_context(self, person_id: str) -> str:
        """French description of how Mika feels *toward this specific person*.

        Covers both the current PersonMood (live PAD oscillator) and the
        "ancrage" marker when the stance was built rather than triggered
        once. Returned as a block ready to be concatenated into the
        person_context section.

        Returns "" when the state is effectively neutral — absence is
        more useful than boilerplate ("pas de sentiment particulier")
        for every unfamiliar person. The caller's context block stays
        empty in that case, which keeps the prompt lean.
        """
        person = self._get_person_mood(person_id)
        # The "or a fresh impulse" clause read the velocity, to catch an
        # impulse not yet integrated. An impulse now moves the position
        # itself, so there is nothing left in flight to catch.
        #
        # Une déclaration fraîche parle en revanche pour elle-même : un tour
        # qui vient de dire « [EMOTION:thinking:0.4] » a un ressenti, même si
        # le vecteur correspondant est court. Se taire dans ce cas, c'est
        # perdre précisément ce dont on est sûr.
        if person.fresh_declaration() is None and self._at_rest_toward(person):
            return ""

        lines: list[str] = [person.to_prompt_description()]

        if self._is_anchored(person):
            lines.append(
                "Cette emotion envers cette personne est bien ancree, "
                "elle ne va pas s'estomper facilement."
            )

        return "\n".join(lines)

    def _at_rest_toward(self, mood: PersonMood) -> bool:
        """Rien à dire de cette stance : jamais provoquée, ou revenue au repos.

        Deux cas, et l'un ne se déduit pas de l'autre :

        - **jamais rien provoqué** — ni impulsion dans ce processus, ni ancre
          restaurée d'un relevé (le contrat de ``PersonMood.anchor`` :
          ``None`` tant qu'elle n'a rien provoqué). Une lecture crée
          l'oscillateur à l'origine et la boucle le laisse rejoindre le
          repos : la norme brute franchissait 0,1 en route et chaque inconnu
          recevait « tu te sens légèrement joueuse » — la teinte circadienne,
          pas un sentiment ;
        - **revenue au repos** — l'écart au repos PROPRE de la personne
          (``_person_home``) est sous ``REST_TOLERANCE``. Mesuré depuis
          l'origine, ce repos (norme 0,14 à 0,50) se lisait comme une
          stance permanente envers tout le monde.
        """
        if not mood.history and mood.anchor is None:
            return True
        return pad.distance(
            mood.dynamic.position, self._person_home(mood),
        ) < REST_TOLERANCE

    def _is_anchored(self, mood: PersonMood) -> bool:
        """Whether a stance was built by several agreeing turns, not just one."""
        position = mood.dynamic.position
        if pad.norm(position) < cfg_float(
            "emotion.anchored_min_norm", ANCHORED_MIN_NORM, mini=0.0,
        ):
            return False

        cutoff = time.time() - cfg_float(
            "emotion.anchored_window_seconds", ANCHORED_WINDOW_S, mini=0.0,
        )
        agreeing = 0
        for entry in mood.history:
            if entry.timestamp < cutoff:
                continue
            if pad.dot(pad.EMOTION_ANCHORS[entry.emotion], position) > 0:
                agreeing += 1

        return agreeing >= cfg_int(
            "emotion.anchored_min_impulses", ANCHORED_MIN_IMPULSES, mini=1,
        )

    # ------------------------------------------------------------------
    # State dict for WebSocket
    # ------------------------------------------------------------------

    def get_state_dict(self, person_id: str) -> dict:
        """Get full emotional state for WebSocket broadcast."""
        person = self._get_person_mood(person_id)
        msg = self.compute_message_emotion(person_id)

        return {
            "person": person.to_dict(),
            "global": self.global_mood.to_dict(),
            "message": msg.to_dict(),
        }

    # ------------------------------------------------------------------
    # Decay loop — pure physics integration
    # ------------------------------------------------------------------

    async def _decay_loop(self):
        """Background loop: advance all oscillators every second."""
        while True:
            try:
                await asyncio.sleep(_TICK_DT)
                self._apply_decay()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Emotion decay loop error")

    @staticmethod
    def _advance(
        dynamic,
        home: Vec3,
        params: OscillatorParams,
        total_dt: float,
        max_advance: float | None = None,
    ) -> None:
        """Advance an oscillator by total_dt seconds in stable sub-steps.

        ``max_advance`` est lu UNE fois par passe par ``_apply_decay`` et
        passé ici : la passe traverse toutes les personnes en RAM, et le
        plafond doit valoir la même chose pour toutes celles d'un même tick.
        ``None`` = lire le réglage (appel isolé, tests).
        """
        if max_advance is None:
            max_advance = cfg_float(
                "emotion.max_advance_seconds", _MAX_ADVANCE_SECONDS, mini=0.0,
            )
        remaining = min(total_dt, max_advance)
        fine = _FINE_WINDOW_S
        while remaining > 1e-6:
            substep = _MAX_SUBSTEP_DT if fine > 0.0 else _COARSE_SUBSTEP_DT
            step_dt = min(substep, remaining)
            dynamic.step(home, params, step_dt)
            remaining -= step_dt
            fine -= step_dt

    def _apply_decay(self):
        """Step the physics forward. Sub-divides into stable chunks."""
        now = time.time()
        home = self._home_vector()
        # Un seul plafond et un seul seuil d'éviction pour toute la passe.
        plafond = cfg_float(
            "emotion.max_advance_seconds", _MAX_ADVANCE_SECONDS, mini=0.0,
        )
        eviction = cfg_int(
            "emotion.idle_eviction_seconds", self._IDLE_EVICTION_SECONDS, mini=1,
        )

        # Step person moods
        expired_persons = []
        for pid, person in self.person_moods.items():
            dt = max(0.0, now - person.last_update)
            if dt <= 0.0:
                continue

            self._heal_anchor(person, home, dt)
            person_home = self._person_home(person, home)
            self._advance(
                person.dynamic, person_home, self._person_params, dt,
                max_advance=plafond,
            )
            person.last_update = now

            if (
                now - person.last_interaction > eviction
                and pad.distance(person.dynamic.position, person_home) < 0.05
            ):
                expired_persons.append(pid)

        if expired_persons:
            try:
                self._evict_persons(expired_persons)
            except Exception as exc:
                degradations.record("emotion.engine._apply_decay", exc)

        # Step global mood
        dt = max(0.0, now - self.global_mood.last_update)
        if dt > 0.0:
            self._advance(
                self.global_mood.dynamic, home, self._global_params, dt,
                max_advance=plafond,
            )
            self.global_mood.last_update = now

        # Spontaneous mood drift: tiny random nudge so the global mood
        # doesn't sit perfectly on its home point when nothing is happening.
        # Scaled by:
        #   - stillness  (only nudge when close to rest — real impulses
        #                 still dominate when something is happening)
        #   - volatility (stoic personas barely drift, explosive ones do
        #                 — matches temperament personality)
        volatility_scale = max(0.0, self.temperament.volatility)
        probabilite = cfg_float(
            "emotion.spontaneous_nudge_probability",
            _SPONTANEOUS_NUDGE_PROBABILITY, mini=0.0, maxi=1.0,
        )
        if volatility_scale > 0.25 and random.random() < probabilite:
            distance = pad.distance(self.global_mood.dynamic.position, home)
            stillness = max(0.0, 1.0 - distance * 3.0)  # 0 when far, 1 when at home
            if stillness > 0.2:
                magnitude = (
                    cfg_float(
                        "emotion.spontaneous_nudge_max",
                        _SPONTANEOUS_NUDGE_MAX, mini=0.0,
                    )
                    * stillness
                    * volatility_scale
                    * random.random()
                )
                nudge: Vec3 = (
                    random.uniform(-1.0, 1.0) * magnitude,
                    random.uniform(-1.0, 1.0) * magnitude,
                    random.uniform(-1.0, 1.0) * magnitude,
                )
                self.global_mood.dynamic.position = pad.clamp_component(
                    pad.add(self.global_mood.dynamic.position, nudge),
                    limit=1.0,
                )

    def _evict_persons(self, person_ids: list[str]) -> None:
        """Sortir de la RAM les humeurs inactives — sauf celles encore lues.

        ``last_interaction`` ne date que le dernier *message*, jamais une
        lecture : quelqu'un qui laisse son onglet ouvert sans plus parler
        franchit le seuil d'inactivité alors qu'``emotion_sync`` lit son
        humeur toutes les quelques secondes. L'évincer là est doublement
        faux — la lecture suivante recrée l'oscillateur à l'origine (chute
        d'intensité visible à l'écran, une fois par heure de silence), et
        ``ensure_person_loaded`` redevenant un no-op, le ``EmotionSnapshot``
        qui portait le sentiment accumulé n'est plus jamais relu.

        Seules les connexions vivantes protègent : un handle de module
        (Telegram) est joignable à vie, l'oscillateur associé ne l'est pas.
        """
        from communication.presence import presence_registry
        from emotion.sync import emotion_sync

        connectes = {
            i.person_id for i in presence_registry.reachable() if i.is_consumer
        }
        for pid in person_ids:
            if pid in connectes:
                continue
            del self.person_moods[pid]
            # Deux caches indexés par person_id survivaient à l'oscillateur
            # qu'ils décrivent : ``_last_snapshot_time`` n'était purgé nulle
            # part, et ``emotion_sync._hydrated`` marque « déjà hydratée »
            # une personne dont l'humeur vient de quitter la RAM — la
            # prochaine lecture sauterait l'hydratation et repartirait de
            # l'origine.
            self._last_snapshot_time.pop(pid, None)
            emotion_sync.forget(pid)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_analytics(self) -> dict:
        """Compute emotion analytics across all persons."""
        all_entries = []
        for person in self.person_moods.values():
            all_entries.extend(person.history)

        if not all_entries:
            return {
                "total_interactions": 0,
                "distribution": {},
                "dominant_emotion": self.temperament.default_mood.value,
                "persons_tracked": 0,
            }

        distribution: dict[str, float] = {}
        for entry in all_entries:
            key = entry.emotion.value
            distribution[key] = distribution.get(key, 0.0) + entry.intensity

        total = sum(distribution.values()) or 1.0
        distribution = {k: round(v / total, 3) for k, v in distribution.items()}
        dominant = max(distribution, key=distribution.get)

        return {
            "total_interactions": len(all_entries),
            "distribution": distribution,
            "dominant_emotion": dominant,
            "persons_tracked": len(self.person_moods),
        }


# Module-level singleton
emotion_engine = EmotionEngine()
