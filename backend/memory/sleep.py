"""Sleep cycle — Mika's night-time mental work.

While the main consolidator runs throughout the day doing bookkeeping
(extraction, decay, aggregation), this module runs only during the
night phase (when Mika has earned her rest) and does *creative*,
*narrative*, and *healing* work that the reactive consolidator cannot:

  1. LIGHT SLEEP — write a first-person `DailyJournal` covering the
     day's arc. Recovers the causal thread between isolated Souvenirs.

  2. REM — generate `Dream` narratives by mixing 2-3 souvenirs of
     unrelated themes + optionally a rumination. High-vividness
     dreams become mentionable next morning.

  3. DEEP SLEEP — *digest* old, unresolved ruminations. Faster decay,
     forced emotional mutation toward a more peaceful neighbor, and
     the heaviest ones get converted into reflective Souvenirs — the
     "insight" you wake up with after a night's worry.

Design choices:
  - Owns a dedicated background loop (started from ASGI lifespan,
    cadence ``memory.sleep_check_interval``) that calls ``run_if_due()``.
    Decoupled from the consolidator since 2026-04 so a long LLM call here
    never delays memory consolidation.
  - Double-gated: night phase AND idle. The REST drive no longer forbids
    sleeping, it only brings the night forward when she is tired.
  - Budget-capped: 1 journal (retried at most
    ``JOURNAL_MAX_ATTEMPTS_PER_NIGHT`` times if the call fails) + up to
    2 dreams + optional digestion summary.
  - Fail-soft: every phase wrapped in try/except. A crashed sleep phase
    never corrupts the main consolidator.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
# `time` above is datetime.time (a class) — import the clock explicitly.
from time import monotonic

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone as tz

from ai.router import AIRole, UnconfiguredRoleError, ai_router
from configs.runtime import cfg_float, cfg_int
from utils.parsing import strip_markdown_json
from utils.periodic import PeriodicLoop
from utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────
#
# Les constantes de ce bloc portant une clé ``memory.*`` sont réglables depuis
# le tableau de bord ; ce qui reste écrit ici est le REPLI, servi quand le
# registre est hors d'atteinte (import avant `migrate`, base verrouillée,
# collecte des tests). Un repli vaut exactement le ``default`` déclaré.

# Sleep phase gates
NIGHT_START_HOUR = 23       # phase gate opens at 23h
NIGHT_END_HOUR = 6          # closes at 6h
# Le sommeil profond (digestion, réorganisation) n'ouvre qu'en fin de nuit —
# une heure nominale, reculée quand le matin du profil est plus précoce
# (`_deep_sleep_window`).
DEEP_SLEEP_START_HOUR = 3
IDLE_SECONDS_THRESHOLD = 900  # 15 min without interaction
#: Délai pendant lequel un réveil tient, même si personne n'a rien dit.
#:
#: Assez long pour qu'un tour complet aboutisse — l'appel IA est borné à 120 s
#: par `ai.call_timeout_seconds` — sans être une insomnie : passé ce délai,
#: l'inactivité reprend la main et elle se rendort.
ENDOGENOUS_WAKE_GRACE_SECONDS = 180
# REST n'INTERDIT plus de dormir, il AVANCE l'heure du coucher. Le gate
# exigeait `rest_tension >= 0.5` : REST ne croît que par événement d'activité
# et décroît pendant les 900 s d'idle que le gate impose d'abord, si bien
# qu'une soirée calme (conversation jusqu'à 20h30, coucher à 23h) laissait la
# tension à ~0.01 — nuit blanche, aucun journal, aucun rêve, aucune digestion,
# et l'avatar les yeux ouverts. Une fatigue pleine ouvre donc la nuit UNE
# heure plus tôt. Deux heures couchaient un adulte à 21 h après une soirée
# de conversation — et REST était alors compté par réponse, saturé en un
# quart d'heure ; maintenant qu'il mesure le temps d'activité (cinq heures
# denses pour saturer), une heure d'avance à fatigue pleine est ce qu'une
# grosse journée fait à un humain.
EARLY_NIGHT_MAX_ADVANCE_HOURS = 1

# Each sleeping tick relieves the REST drive by this `satisfy()` amount —
# sleep is what rest tension is FOR. With REST's decay_on_satisfy (0.3),
# 0.1 ≈ 3%/tick: tension melts over the first couple of hours of sleep,
# so morning-Mika wakes with real energy instead of yesterday's fatigue.
# La tension qui fond ne peut plus la réveiller : elle n'ouvre que l'heure
# d'entrée, et `_night_start_hour` revient à l'heure nominale une fois endormie.
SLEEP_REST_RECOVERY = 0.1

# Journal (light sleep)
# `_write_journal_if_due` ne marque la nuit comme faite que sur ses chemins de
# succès : un timeout LLM, un JSON illisible ou un rôle IA non configuré la
# laisse intacte. Sans espacement, la boucle dédiée (60 s) rejouerait la phase
# à chaque tick de 23h à 6h — ~420 tentatives par nuit, et deux transitions de
# phase par minute côté frontend, exactement le clignotement que le settle en
# DEEP_SLEEP existe pour éviter. Même idiome que DREAM_ATTEMPT_INTERVAL_S.
JOURNAL_ATTEMPT_INTERVAL_S = 30 * 60
JOURNAL_MAX_ATTEMPTS_PER_NIGHT = 3

# Dream generation
# `_DREAM_PROBABILITY_DEFAUT` est la valeur DÉCLARÉE ; `DREAM_PROBABILITY` est
# la variable de module que le point de dev `/api/dev/sleep/dream` réassigne à
# 1.0 le temps de forcer un rêve (communication/debug_views.py, hors de cette
# zone). Les deux sont distinctes pour que `_maybe_dream` puisse comparer la
# variable à sa valeur déclarée et savoir si quelqu'un l'a écrasée : intacte,
# le réglage `memory.dream_probability` gouverne ; réassignée, l'écrasement
# gagne — sinon forcer un rêve n'aurait plus aucun effet.
_DREAM_PROBABILITY_DEFAUT = 0.6      # per-check chance of producing a dream
DREAM_PROBABILITY = _DREAM_PROBABILITY_DEFAUT
MAX_DREAMS_PER_NIGHT = 2
DREAM_MIN_SOUVENIRS = 2              # need at least this many souvenirs to dream
# Real REM episodes are ~90 min apart. Beyond realism, this keeps the sleep
# loop from re-entering REM on every 60s tick, which would make the avatar
# flicker between phases all night.
DREAM_ATTEMPT_INTERVAL_S = 45 * 60

# Deep sleep
DIGESTION_MIN_AGE_MINUTES = 120      # ruminations older than this get digested
DIGESTION_DECAY_MULTIPLIER = 3.0     # vs ~5% normal decay
DIGESTION_TO_SOUVENIR_THRESHOLD = 0.4  # intensity above which digested ruminations
                                       # become reflective souvenirs

# LLM — repli du module quand le registre n'est pas lisible. Réglable via
# `memory.sleep_llm_timeout` : à 45 s le budget expirait sous les 76-219 s
# qu'un modèle local met à répondre, donc journal et rêves ne se terminaient
# jamais sur une installation par défaut.
SLEEP_LLM_TIMEOUT = 120


# ── Emotion drift map for deep-sleep digestion ───────────────────

# More aggressive than the waking rumination drift: sleep actively
# heals, it doesn't just erode. Negative emotions shift toward peaceful
# or resolved neighbors; positive ones soften into nostalgic warmth.
DIGESTION_DRIFT: dict[str, str] = {
    "frustrated": "relieved",
    "angry": "thinking",
    "anxious": "relieved",
    "scared": "relieved",
    "sad": "melancholic",
    "jealous": "thoughtful" if False else "melancholic",  # fallback
    "lonely": "nostalgic",
    "embarrassed": "relieved",
    "excited": "nostalgic",
    "happy": "grateful",
    "proud": "grateful",
    "hopeful": "relieved",
    "curious": "thinking",
    "surprised": "thinking",
}


# ── Prompts ──────────────────────────────────────────────────────

JOURNAL_PROMPT_TEMPLATE = """\
ROLE: Tu rediges le journal intime d'aujourd'hui pour {name}, a la premiere \
personne. C'est son recap de journee avant de dormir — ce qui s'est passe, \
ce qu'elle a ressenti, ce qui reste en suspens.

STYLE: une ou deux phrases au maximum par idee. Decontracte, introspectif. \
Fluide — pas une liste a puces. Connecte les evenements quand ca a du sens \
("... ce qui m'a fait penser a...", "... du coup ensuite..."). Si la journee \
a ete calme, dis-le simplement, ne brode pas.

NE PAS:
- Enumerer les souvenirs un par un comme un rapport
- Inventer des details qui ne sont pas dans les materiaux
- Commencer par "Cher journal"

SOUVENIRS DE LA JOURNEE (chronologique):
{souvenirs}

PERSONNES CROISSEES: {persons}
HUMEUR DOMINANTE: {dominant_mood}
CE QUI RESTE NON-DIGERE: {ruminations}

Retourne UNIQUEMENT du JSON:
{{
  "narrative": "Aujourd'hui... (2-4 phrases, premiere personne)",
  "dominant_emotion": "emotion parmi les 29",
  "word_count": 42
}}
"""


DREAM_PROMPT_TEMPLATE = """\
ROLE: Tu generes UN reve bref pour {name}, qui dort. Un reve n'est pas un \
resume — c'est une scene onirique, parfois absurde, qui mixe des fragments \
de sa vie recente de maniere inattendue. Court, imagé, un peu decousu comme \
un vrai reve dont on se souvient au reveil.

FORMAT: 2 a 4 phrases maximum. Premiere personne. Pas de "j'ai reve que" — \
raconte directement la scene. Tu peux melanger les themes, inventer des \
associations visuelles libres. Les elements fournis doivent APPARAITRE mais \
peuvent etre transformes (un objet devient une personne, un lieu devient \
abstrait, etc).

TYPE DE REVE DEMANDE: {dream_type_hint}
  - associative: creatif, theme mixe, curieux
  - pleasant: chaleureux, doux
  - nightmare: anxieux, pas tragique — juste inconfortable
  - mundane: banal, presque oubliable

FRAGMENTS DE VIE A MIXER:
{fragments}

PREOCCUPATION EN TOILE DE FOND (peut apparaitre ou non): {rumination}

Retourne UNIQUEMENT du JSON:
{{
  "content": "Je marchais dans... (2-4 phrases, scene onirique)",
  "emotion": "emotion parmi les 29 qui tinte le reve",
  "vividness": 0.0 a 1.0
}}
"""


# ── Main orchestrator ────────────────────────────────────────────


class SleepPhase:
    """Current macro state of the sleep cycle. String constants instead of
    Enum to keep the frontend payload plain JSON."""
    AWAKE = "awake"
    LIGHT_SLEEP = "light_sleep"   # writing the daily journal
    REM = "rem"                   # dreaming
    DEEP_SLEEP = "deep_sleep"     # digesting ruminations


def _emotion_canonique(brut: object) -> str:
    """Ramène l'émotion d'un rêve dans les 29, ou rend la chaîne vide.

    ``Dream.emotion`` est un ``CharField`` libre et la valeur venait telle
    quelle du modèle : observé en conditions réelles, un rêve persisté avec
    ``serenity`` — hors des 29, donc sans ``--emo-serenity`` côté avatar, sans
    entrée dans ``formatting.EMOTION_FR`` (le dashboard affiche le mot brut,
    en anglais) et refusé par le garde ``isEmotionName`` du frontend. Un nom
    inventé n'est pas une nuance : on préfère ne rien teinter, ce que tous les
    lecteurs savent déjà faire, à teindre avec une couleur qui n'existe pas.
    """
    from emotion.types import Emotion

    nom = (str(brut or "")).strip().lower()
    if not nom:
        return ""
    if nom in {e.value for e in Emotion}:
        return nom
    # Pas de `degradations.record` ici : le registre compte des échecs
    # avalés dans un `except`, et ceci est un refus de validation — rien n'a
    # échoué, un nom hors nomenclature a simplement été écarté.
    logger.info("Sleep: emotion de reve hors des 29, ignoree: %r", nom)
    return ""


class SleepCycle:
    """Singleton. Drives Mika's night-time mental work."""

    def __init__(self) -> None:
        self._last_journal_date: date | None = None
        # Tentatives de journal pour la nuit en cours — un échec ne marque pas
        # `_last_journal_date`, ce sont ces deux compteurs qui espacent puis
        # arrêtent les reprises.
        self._journal_attempts_night: date | None = None
        self._journal_attempts: int = 0
        self._last_journal_attempt: float = 0.0  # monotonic()
        self._dreams_this_night: int = 0
        self._last_dream_night: date | None = None
        self._last_dream_attempt: float = 0.0  # monotonic()
        self._last_digestion_night: date | None = None
        self._last_reorg_night: date | None = None
        # Night for which Mika already fell asleep — entry/stay hysteresis:
        # the REST gate governs falling asleep, not staying asleep (sleep
        # drains REST, and draining it must not bounce her awake).
        self._asleep_night: date | None = None
        # Dernier réveil demandé (`monotonic()`), ou 0.0 si jamais.
        #
        # La porte d'endormissement ne lit que l'inactivité, et l'inactivité ne
        # compte que ce que les *autres* font : un acte de la conscience ne
        # touche pas `_last_activity`, à dessein. La nuit, une initiative la
        # réveillait donc pour un tick, puis la porte la rendormait 60 s plus
        # tard — pendant qu'elle parlait. Et `pipeline/voice.py` refuse la
        # parole en sommeil : le message s'affichait, muet, prononcé par
        # quelqu'un que l'écran montrait endormi.
        self._dernier_reveil: float = 0.0
        # Diffusions de réveil détachées, tenues pour ne pas être collectées
        # en vol (même motif que `ConscienceEngine._fastpath_tasks`).
        self._wake_tasks: set[asyncio.Task] = set()
        # Current phase — observable by the frontend via the inner_state
        # broadcast. Transitions trigger an inner_state push so the UI
        # can dim the scene, close the VTuber's eyes, etc.
        self._phase: str = SleepPhase.AWAKE
        # Dedicated background loop (since 2026-04): previously piggy-backed
        # on the consolidator's tick budget, now independent so a long LLM
        # call here never delays memory consolidation.
        self._loop = PeriodicLoop("Sleep cycle", self.run_if_due, interval=60)

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dedicated sleep-check loop. Idempotent."""
        from configs.service import config_service
        await self._loop.start(
            interval=int(
                config_service.get("memory.sleep_check_interval", default=60)
            ),
        )

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        await self._loop.stop()

    # ── Public entry point ────────────────────────────────────────

    @property
    def phase(self) -> str:
        return self._phase

    def note_interaction(self) -> None:
        """Quelqu'un lui parle : elle se réveille tout de suite.

        La phase est posée SYNCHRONIQUEMENT, pas via `_set_phase` : la frame
        `speech` du tour en cours lit `sleep_cycle.phase` en plein milieu, et
        un await la ferait lire `deep_sleep` pendant que le TTS parle.
        `_asleep_night` est effacé pour que l'hystérésis d'entrée ne la
        rendorme pas au tick suivant sans repasser par les 15 min d'inactivité.
        Idempotente, ne lève jamais — elle est appelée sur le chemin chaud,
        éventuellement depuis un thread sans boucle.
        """
        # Horodaté avant le court-circuit : la grâce compte depuis le *dernier*
        # réveil demandé, y compris quand elle était déjà éveillée. Sans quoi
        # deux actes rapprochés verraient le second repartir sur la grâce du
        # premier, presque écoulée.
        self._dernier_reveil = monotonic()
        if self._phase == SleepPhase.AWAKE and self._asleep_night is None:
            return
        self._phase = SleepPhase.AWAKE
        self._asleep_night = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._announce_awake())
        self._wake_tasks.add(task)
        task.add_done_callback(self._wake_tasks.discard)

    async def _announce_awake(self) -> None:
        with degraded("sommeil: diffusion du reveil"):
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()

    async def _set_phase(self, new_phase: str) -> None:
        """Update the observable phase + push an inner_state update to the UI.

        Never raises — a broadcast failure should never block the cycle.
        """
        if self._phase == new_phase:
            return
        old = self._phase
        self._phase = new_phase
        logger.info("Sleep phase: %s -> %s", old, new_phase)
        try:
            from pipeline.broadcast import broadcast_inner_state_update
            await broadcast_inner_state_update()
        except Exception as exc:
            degradations.record("sleep: sleep phase broadcast", exc)

    async def run_if_due(self) -> None:
        """Invoked by the dedicated sleep loop.

        No-op unless both gates (night phase + idle) pass — the night's own
        start hour being brought forward by fatigue. Each phase is
        independently guarded so a single corrupted phase never blocks the
        others.
        """
        if not self._is_enabled():
            await self._set_phase(SleepPhase.AWAKE)
            return

        now_dt = datetime.now()
        current_night = self._night_of(now_dt)
        already_asleep = self._asleep_night == current_night

        if not self._is_night(now_dt, self._night_start_hour(already_asleep)):
            # Crossing midnight: reset the per-night counters.
            self._maybe_reset_counters(now_dt.date())
            await self._set_phase(SleepPhase.AWAKE)
            return

        if not await self._is_eligible_to_sleep():
            # Night hours but she's active — she's up late, not asleep.
            await self._set_phase(SleepPhase.AWAKE)
            return
        self._asleep_night = current_night

        # A phase is entered only when it has real work to do. Announcing
        # LIGHT_SLEEP then REM on every tick regardless would make the
        # frontend replay its 1.2-1.8s eye/lighting transitions twice a
        # minute all night long.

        # Phase 1: light sleep — write the day's journal (once per date)
        try:
            if self._journal_attempts_night != current_night:
                self._journal_attempts_night = current_night
                self._journal_attempts = 0
                self._last_journal_attempt = 0.0
            if self._last_journal_date != current_night and self._journal_is_due():
                # Compté et daté AVANT la transition de phase : une tentative
                # qui échoue ne doit pas coûter un aller-retour LIGHT_SLEEP →
                # DEEP_SLEEP à chaque tick.
                self._journal_attempts += 1
                self._last_journal_attempt = monotonic()
                await self._set_phase(SleepPhase.LIGHT_SLEEP)
                await self._write_journal_if_due(current_night)
        except Exception:
            logger.exception("Sleep: journal phase failed (non-fatal)")

        # Phase 2: REM — maybe dream (probabilistic, capped)
        try:
            if self._last_dream_night != current_night:
                self._dreams_this_night = 0
                self._last_dream_night = current_night
                self._last_dream_attempt = 0.0
            max_reves = cfg_int(
                "memory.dream_max_per_night", MAX_DREAMS_PER_NIGHT, mini=0, maxi=10,
            )
            if self._dreams_this_night < max_reves and self._rem_is_due():
                self._last_dream_attempt = monotonic()
                await self._set_phase(SleepPhase.REM)
                await self._maybe_dream(current_night)
        except Exception:
            logger.exception("Sleep: dream phase failed (non-fatal)")

        # Phase 3: deep sleep — digest ruminations (fin de nuit, once per night)
        profond = self._en_sommeil_profond(now_dt)
        try:
            if profond:
                if self._last_digestion_night != current_night:
                    await self._set_phase(SleepPhase.DEEP_SLEEP)
                    await self._digest_ruminations()
                    self._last_digestion_night = current_night
        except Exception:
            logger.exception("Sleep: digestion phase failed (non-fatal)")

        # Phase 4: réorganisation — dédoublonner les souvenirs de la journée
        # (fin de nuit, une fois par nuit, après la digestion). L'extraction
        # par thème qui vivait ici a rejoint le consolidateur
        # (memory/themes.py) : la nuit ne relit plus le verbatim. Même profil
        # d'isolement que les autres phases : un échec ne coûte que sa nuit.
        try:
            if profond:
                if self._last_reorg_night != current_night:
                    await self._set_phase(SleepPhase.DEEP_SLEEP)
                    from memory.reorg import nightly_reorg
                    stats = await nightly_reorg.run(current_night)
                    self._last_reorg_night = current_night
                    logger.info(
                        "Sleep: reorg (%s) — %d fusion(s) de souvenirs",
                        current_night, int((stats or {}).get("merges", 0) or 0),
                    )
        except Exception:
            logger.exception("Sleep: reorg phase failed (non-fatal)")

        # Cycle finished for this tick — between active phases Mika is
        # "asleep but idle", so she settles into DEEP_SLEEP (the most dormant
        # state) and stays there. AWAKE is restored by the next tick when the
        # night gate re-evaluates to false.
        await self._set_phase(SleepPhase.DEEP_SLEEP)

        # Sleeping is what actually relieves the REST drive. Without this,
        # rest tension only had its tiny natural decay and Mika woke up as
        # tired as she fell asleep, dragging energy_level() down all day.
        try:
            from drives.engine import drive_engine
            from drives.state import DriveKind
            drive_engine.satisfy(DriveKind.REST, SLEEP_REST_RECOVERY)
        except Exception as exc:
            degradations.record("sleep: sleep rest recovery", exc)

    # ── Gates ────────────────────────────────────────────────────

    @staticmethod
    def _is_enabled() -> bool:
        return bool(getattr(settings, "SLEEP_CYCLE_ENABLED", True))

    def _journal_is_due(self) -> bool:
        """Espace, puis abandonne, les reprises d'un journal qui a échoué.

        Le drapeau `_last_journal_date` n'avance que sur succès : sans ce
        garde, une seule cause d'échec (timeout, JSON illisible,
        rôle IA non configuré) suffit à relancer l'appel LLM toutes les
        60 s jusqu'au matin. Au-delà de JOURNAL_MAX_ATTEMPTS_PER_NIGHT on
        renonce jusqu'à la nuit suivante — un modèle qui a échoué trois
        fois de suite ne réussira pas la quatrième.
        """
        max_tentatives = cfg_int(
            "memory.journal_max_attempts_per_night", JOURNAL_MAX_ATTEMPTS_PER_NIGHT,
            mini=1, maxi=20,
        )
        if self._journal_attempts >= max_tentatives:
            return False
        if not self._last_journal_attempt:
            return True
        espacement = cfg_int(
            "memory.journal_attempt_interval_s", JOURNAL_ATTEMPT_INTERVAL_S,
            mini=60, maxi=21600,
        )
        return (monotonic() - self._last_journal_attempt) >= espacement

    @staticmethod
    def _llm_timeout() -> int:
        """Budget d'un appel nocturne. Une lecture de config peut précéder
        une base joignable — même prudence que `load_temperament`."""
        try:
            from configs.service import config_service
            return int(
                config_service.get("memory.sleep_llm_timeout", default=SLEEP_LLM_TIMEOUT)
            )
        except Exception as exc:
            degradations.record("sommeil: budget LLM illisible", exc)
            return SLEEP_LLM_TIMEOUT

    def _rem_is_due(self) -> bool:
        """Space REM episodes out instead of retrying on every tick."""
        if not self._last_dream_attempt:
            return True
        espacement = cfg_int(
            "memory.dream_attempt_interval_s", DREAM_ATTEMPT_INTERVAL_S,
            mini=60, maxi=21600,
        )
        return (monotonic() - self._last_dream_attempt) >= espacement

    # Les deux bornes de la nuit DÉRIVENT du profil circadien, comme les
    # fenêtres de salutation de la conscience, et pour la même raison : les
    # clés `memory.sleep_night_*` cohabitaient avec `personality.circadian.*`
    # — deux sources de vérité pour « quand commence sa nuit », et un
    # personnage configuré nocturne dormait aux heures d'un autre. Les clés
    # sont supprimées, pas doublées ; les bornes de lecture ([12, 23] et
    # [0, 12]) restent des gardes du lecteur, et les constantes historiques
    # (23 h / 6 h — identiques aux défauts du profil) le repli d'un profil
    # illisible.

    @staticmethod
    def _night_end_hour() -> int:
        """La nuit se ferme quand SON matin commence (phase MORNING)."""
        try:
            from config.personality import personality
            from emotion.circadian import CircadianPhase

            h = int(personality.circadian_profile.phase_hours.get(
                CircadianPhase.MORNING, NIGHT_END_HOUR,
            ))
        except Exception as exc:
            degradations.record("sommeil: heure de matin du profil", exc)
            h = NIGHT_END_HOUR
        return max(0, min(12, h))

    @staticmethod
    def _deep_sleep_window() -> tuple[int, int]:
        """[début, fin) du sommeil profond, en heures.

        La fin est SON matin (`_night_end_hour`). Le début était écrit « 3 »
        en dur alors que le matin est un champ du tableau de bord borné à
        [0, 12] : un personnage dont le matin commence à 3 h ou avant avait une
        fenêtre vide — ni digestion ni réorganisation, jamais, sans qu'aucun
        écran ne le dise. Le début recule donc d'une heure devant un matin
        précoce, plancher minuit ; à matin nul la fenêtre reste vide, et
        `_en_sommeil_profond` le compte.
        """
        fin = SleepCycle._night_end_hour()
        debut = max(0, min(DEEP_SLEEP_START_HOUR, fin - 1))
        return debut, fin

    @staticmethod
    def _en_sommeil_profond(now: datetime) -> bool:
        """L'heure est-elle dans la fenêtre de sommeil profond ?"""
        debut, fin = SleepCycle._deep_sleep_window()
        try:
            if debut >= fin:
                raise ValueError(
                    f"fenêtre de sommeil profond vide (matin du profil à {fin} h)"
                )
        except ValueError as exc:
            # Levée puis rattrapée sur place : le registre des dégradations ne
            # compte que des exceptions, et une fenêtre vide EST une panne
            # silencieuse — la nuit passe, rien ne se digère, rien ne le dit.
            degradations.record("sommeil: fenetre de sommeil profond vide", exc)
            return False
        return debut <= now.hour < fin

    @staticmethod
    def _nominal_night_start_hour() -> int:
        """La nuit s'ouvre quand SA phase NIGHT commence — avant l'avance
        par la fatigue (`_night_start_hour`)."""
        try:
            from config.personality import personality
            from emotion.circadian import CircadianPhase

            h = int(personality.circadian_profile.phase_hours.get(
                CircadianPhase.NIGHT, NIGHT_START_HOUR,
            ))
        except Exception as exc:
            degradations.record("sommeil: heure de nuit du profil", exc)
            h = NIGHT_START_HOUR
        return max(12, min(23, h))

    @staticmethod
    def _is_night(now: datetime, start_hour: int | None = None) -> bool:
        """Night phase wraps across midnight: [start_hour, 06h).

        ``start_hour`` non fourni = l'heure nominale configurée. Lue dans le
        corps et non en défaut d'argument : un défaut est évalué à l'import,
        donc avant que la base soit joignable, et ne changerait plus jamais.
        """
        if start_hour is None:
            start_hour = SleepCycle._nominal_night_start_hour()
        h = now.hour
        return h >= start_hour or h < SleepCycle._night_end_hour()

    def _night_start_hour(self, already_asleep: bool) -> int:
        """L'heure à laquelle la nuit s'ouvre ce soir, avancée par la fatigue.

        Une fois endormie, l'heure nominale reprend : la tension REST retombe
        pendant le sommeil (c'est ce à quoi il sert), donc une heure calculée
        sur elle refermerait le gate et la réveillerait vers 22h.
        """
        nominale = self._nominal_night_start_hour()
        avance_max = cfg_int(
            "memory.sleep_early_night_max_advance_hours",
            EARLY_NIGHT_MAX_ADVANCE_HOURS, mini=0, maxi=6,
        )
        if already_asleep:
            return nominale - avance_max

        try:
            from drives.engine import drive_engine
            from drives.state import DriveKind
            drive_engine.update()
            tension = drive_engine.states[DriveKind.REST].tension
        except Exception as exc:
            # Fail-ouvert : une tension illisible coûte le coucher anticipé,
            # jamais la nuit elle-même.
            degradations.record("sommeil: tension REST illisible", exc)
            tension = 0.0

        avance = avance_max * max(0.0, min(1.0, tension))
        return nominale - int(round(avance))

    @staticmethod
    def _night_of(now: datetime) -> date:
        """A dream at 03h on the 18th belongs to the night *of* the 17th."""
        if now.hour < SleepCycle._night_end_hour():
            return (now - timedelta(days=1)).date()
        return now.date()

    async def _is_eligible_to_sleep(self) -> bool:
        """Inactivité, plus une grâce après tout réveil.

        L'heure d'entrée, elle, est modulée par la fatigue
        (`_night_start_hour`).

        Méthode d'instance et non plus statique : la grâce est un état, et
        c'est le seul moyen de distinguer « personne ne lui a parlé depuis
        15 min » — vrai en permanence la nuit — de « elle vient de se
        réveiller pour faire quelque chose ». `get_idle_seconds()` ne peut pas
        répondre à la seconde question : il ne mesure que ce que les autres
        font, et un acte endogène le laisse volontairement intact.
        """
        grace = cfg_int(
            "memory.sleep_endogenous_wake_grace_seconds",
            ENDOGENOUS_WAKE_GRACE_SECONDS, mini=0, maxi=3600,
        )
        if self._dernier_reveil and (monotonic() - self._dernier_reveil) < grace:
            return False

        try:
            from conscience.engine import conscience_engine
            idle_seconds = conscience_engine.get_idle_seconds()
        except Exception as exc:
            degradations.record("sommeil: temps d'inactivite illisible", exc)
            idle_seconds = 0.0

        return idle_seconds >= cfg_int(
            "memory.sleep_idle_seconds_threshold", IDLE_SECONDS_THRESHOLD,
            mini=60, maxi=21600,
        )

    def _maybe_reset_counters(self, today: date) -> None:
        """Outside night window — reset per-night state once per day."""
        if self._last_dream_night is not None and self._last_dream_night != today:
            self._dreams_this_night = 0

    # ── Phase 1: Light sleep — daily journal ─────────────────────

    async def _write_journal_if_due(self, current_night: date) -> None:
        """Produce one DailyJournal per calendar date (the *day* that just ended).

        The "day covered" is the date of the evening (so sleeping at 23h
        on the 17th produces a journal dated 2026-04-17). If a journal
        already exists for that day, refresh it in place — a longer
        evening of consolidation can genuinely enrich it.
        """
        from memory.models import DailyJournal

        day_covered = current_night  # night_of(17→18) covers day 17

        if self._last_journal_date == day_covered:
            return  # Already wrote it this cycle — avoid LLM spam

        material = await self._gather_journal_material(day_covered)
        if material is None:
            logger.debug("Sleep: no material for journal of %s", day_covered)
            return
        if material["souvenir_count"] == 0:
            # Empty day — write a minimal journal so we don't re-enter
            await sync_to_async(DailyJournal.objects.update_or_create)(
                date=day_covered,
                defaults={
                    "narrative": "Journee calme, rien de marquant a retenir.",
                    "key_moments": [],
                    "dominant_emotion": material.get("dominant_emotion", "") or "",
                    "persons_interacted": [],
                    "unresolved_at_sleep": material.get("ruminations", []),
                    "word_count": 8,
                },
            )
            self._last_journal_date = day_covered
            return

        result = await self._call_journal_llm(material)
        if result is None:
            return

        await sync_to_async(DailyJournal.objects.update_or_create)(
            date=day_covered,
            defaults={
                "narrative": result["narrative"],
                "key_moments": material["key_moment_ids"],
                "dominant_emotion": result.get("dominant_emotion", "") or "",
                "persons_interacted": material["persons"],
                "unresolved_at_sleep": material.get("ruminations", []),
                "word_count": int(result.get("word_count", 0)),
            },
        )
        self._last_journal_date = day_covered
        logger.info(
            "Sleep: wrote journal for %s (%d moments, %s)",
            day_covered, len(material["key_moment_ids"]),
            result.get("dominant_emotion") or "—",
        )

    @staticmethod
    async def _gather_journal_material(day: date) -> dict | None:
        """Pull the day's souvenirs + persons + ruminations."""
        from memory.models import Souvenir

        try:
            souvenirs = await sync_to_async(
                lambda: list(
                    Souvenir.objects
                    .filter(occurred_at__date=day)
                    .order_by("-importance", "occurred_at")
                    .prefetch_related("entities")[:12]
                )
            )()
        except Exception as exc:
            # Sans matériau, pas de journal — et le bloc `--- TON FIL D'HIER ---`
            # reste vide toute la journée suivante.
            degradations.record("sommeil: souvenirs du jour illisibles", exc)
            return None

        if not souvenirs:
            return {"souvenir_count": 0, "ruminations": []}

        persons_set: set[str] = set()
        for s in souvenirs:
            for e in s.entities.all():
                if e.entity_type == "person":
                    persons_set.add(e.name)

        # Collect active ruminations at sleep time
        rumination_snapshots: list[dict] = []
        try:
            from conscience.models import Rumination
            ruminations = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active")
                    .order_by("-intensity")[:5]
                )
            )()
            for r in ruminations:
                rumination_snapshots.append({
                    "summary": r.summary[:200],
                    "emotion": r.emotion or "",
                    "intensity": round(r.intensity, 3),
                })
        except Exception as exc:
            degradations.record("sommeil: ruminations du journal illisibles", exc)

        # Dominant emotion = mode of the souvenirs' emotions
        emotions = [s.emotion for s in souvenirs if s.emotion]
        dominant_emotion = ""
        if emotions:
            from collections import Counter
            dominant_emotion = Counter(emotions).most_common(1)[0][0]

        return {
            "souvenir_count": len(souvenirs),
            "souvenirs_serialized": [
                {
                    "time": s.occurred_at.strftime("%H:%M"),
                    "content": s.content,
                    "emotion": s.emotion,
                    "importance": round(s.importance, 2),
                }
                for s in souvenirs
            ],
            "key_moment_ids": [s.pk for s in souvenirs[:5]],
            "persons": sorted(persons_set),
            "dominant_emotion": dominant_emotion,
            "ruminations": rumination_snapshots,
        }

    async def _call_journal_llm(self, material: dict) -> dict | None:
        """Ask the LLM to synthesize today's narrative."""
        from config.personality import personality

        souvenirs_block = "\n".join(
            f"- {s['time']} [{s['emotion']}] {s['content']}"
            for s in material["souvenirs_serialized"]
        )
        ruminations_block = "aucune" if not material["ruminations"] else "; ".join(
            f"{r['summary'][:80]} ({r['emotion']})" for r in material["ruminations"]
        )

        user_prompt = JOURNAL_PROMPT_TEMPLATE.format(
            name=personality.name,
            souvenirs=souvenirs_block,
            persons=", ".join(material["persons"]) or "personne en particulier",
            dominant_mood=material.get("dominant_emotion") or "pas de tendance marquee",
            ruminations=ruminations_block,
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu rediges un journal intime nocturne.",
                    user_prompt=user_prompt,
                ),
                timeout=self._llm_timeout(),
            )
        except asyncio.TimeoutError as exc:
            logger.warning("Sleep: journal LLM timed out")
            degradations.record("sommeil: journal, appel LLM expire", exc)
            return None
        except UnconfiguredRoleError as exc:
            logger.warning("Sleep: journal ignoré — IA non configurée: %s", exc)
            # Un rôle non associé n'est pas un incident : c'est une nuit
            # mentale morte à l'installation, indéfiniment et sans signal.
            degradations.record("sommeil: journal, IA non configuree", exc)
            return None
        except Exception as exc:
            logger.exception("Sleep: journal LLM failed")
            degradations.record("sommeil: journal, appel LLM en echec", exc)
            return None

        if not raw or not raw.strip():
            return None
        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError as exc:
            logger.warning("Sleep: journal JSON parse failed: %.200s", raw)
            # Une seule occasion par nuit : sans journal ecrit, le bloc
            # `--- TON FIL D'HIER ---` reste vide toute la journee suivante.
            degradations.record("sleep: JSON du journal illisible", exc)
            return None

        narrative = (data.get("narrative") or "").strip()
        if not narrative:
            return None
        return {
            "narrative": narrative[:2000],
            "dominant_emotion": (data.get("dominant_emotion") or "").strip()[:30],
            "word_count": len(narrative.split()),
        }

    # ── Phase 2: REM — dream generation ──────────────────────────

    async def _maybe_dream(self, current_night: date) -> None:
        """Produce a Dream with given probability, respecting the nightly cap."""
        # Un écrasement du global (point de dev « forcer un rêve ») gagne sur
        # le réglage ; sans écrasement, c'est le réglage qui gouverne.
        probabilite = (
            DREAM_PROBABILITY
            if DREAM_PROBABILITY != _DREAM_PROBABILITY_DEFAUT
            else cfg_float(
                "memory.dream_probability", _DREAM_PROBABILITY_DEFAUT,
                mini=0.0, maxi=1.0,
            )
        )
        if random.random() >= probabilite:
            return

        fragments = await self._gather_dream_fragments()
        if len(fragments["souvenirs"]) < DREAM_MIN_SOUVENIRS:
            return

        dream_type = self._pick_dream_type(fragments)
        result = await self._call_dream_llm(fragments, dream_type)
        if result is None:
            return

        await self._persist_dream(
            current_night=current_night,
            fragments=fragments,
            dream_type=dream_type,
            content=result["content"],
            emotion=result["emotion"],
            vividness=result["vividness"],
        )
        self._dreams_this_night += 1
        logger.info(
            "Sleep: dream generated (type=%s, vividness=%.2f, emotion=%s)",
            dream_type, result["vividness"], result["emotion"],
        )

    @staticmethod
    async def _gather_dream_fragments() -> dict:
        """Pick 2-3 recent souvenirs of diverse themes + optionally a rumination."""
        from memory.models import Souvenir

        # Pool: top importance from the last 7 days. We intentionally
        # bias toward interesting memories rather than purely recent.
        cutoff = tz.now() - timedelta(days=7)
        recent = await sync_to_async(
            lambda: list(
                Souvenir.objects
                .filter(occurred_at__gte=cutoff)
                .order_by("-importance")[:20]
                .prefetch_related("themes")
            )
        )()

        if not recent:
            return {"souvenirs": [], "rumination": None}

        # Cross-theme bias: try to pick souvenirs with *different* themes.
        # Simple greedy: keep picking a random souvenir whose primary
        # theme hasn't been used yet, fall back to pure random after.
        chosen: list = []
        used_themes: set[str] = set()
        pool = list(recent)
        random.shuffle(pool)
        for s in pool:
            themes = [t.name for t in s.themes.all()]
            primary = themes[0] if themes else ""
            if chosen and primary and primary in used_themes:
                continue
            chosen.append(s)
            if primary:
                used_themes.add(primary)
            if len(chosen) >= 3:
                break
        # If we only got one via diversity filter, relax
        while len(chosen) < min(3, len(pool)) and len(chosen) < DREAM_MIN_SOUVENIRS:
            remainder = [s for s in pool if s not in chosen]
            if not remainder:
                break
            chosen.append(remainder[0])

        # Optionally pick one active rumination
        rumination_obj = None
        try:
            from conscience.models import Rumination
            rumination_obj = await sync_to_async(
                lambda: Rumination.objects
                .filter(status="active", intensity__gte=0.3)
                .order_by("-intensity")
                .first()
            )()
        except Exception:
            rumination_obj = None

        return {"souvenirs": chosen, "rumination": rumination_obj}

    @staticmethod
    def _pick_dream_type(fragments: dict) -> str:
        """Classify the dream based on source emotions + rumination tone."""
        negative = {"sad", "angry", "scared", "disgusted", "frustrated",
                    "lonely", "anxious", "jealous", "embarrassed"}
        positive = {"happy", "excited", "love", "proud", "grateful",
                    "playful", "amused", "hopeful", "relieved"}

        emotions = [s.emotion for s in fragments["souvenirs"] if s.emotion]
        r = fragments.get("rumination")
        if r and r.emotion:
            emotions.append(r.emotion)
            if r.intensity >= 0.6 and r.emotion in negative:
                return "nightmare"

        if not emotions:
            return "mundane"
        neg_count = sum(1 for e in emotions if e in negative)
        pos_count = sum(1 for e in emotions if e in positive)
        if neg_count > pos_count * 1.5:
            return "nightmare"
        if pos_count > neg_count * 1.5:
            return "pleasant"
        # Default — mix of everything = associative or mundane at random
        return "associative" if random.random() > 0.2 else "mundane"

    async def _call_dream_llm(self, fragments: dict, dream_type: str) -> dict | None:
        """Call the LLM to spin the fragments into a dream narrative."""
        from config.personality import personality

        if not fragments["souvenirs"]:
            return None

        frag_lines = []
        for s in fragments["souvenirs"]:
            themes = ", ".join(t.name for t in s.themes.all())
            frag_lines.append(
                f"- [{s.emotion or 'neutre'}] {s.content[:160]}"
                + (f" (themes: {themes})" if themes else "")
            )
        fragments_block = "\n".join(frag_lines)

        r = fragments.get("rumination")
        rumination_line = "aucune" if not r else f"{r.summary[:140]} ({r.emotion or 'neutre'})"

        user_prompt = DREAM_PROMPT_TEMPLATE.format(
            name=personality.name,
            dream_type_hint=dream_type,
            fragments=fragments_block,
            rumination=rumination_line,
        )

        try:
            raw = await asyncio.wait_for(
                ai_router.complete(
                    role=AIRole.MEMORY_EXTRACTION,
                    system_prompt="Tu generes un reve nocturne bref.",
                    user_prompt=user_prompt,
                ),
                timeout=self._llm_timeout(),
            )
        except asyncio.TimeoutError as exc:
            logger.warning("Sleep: dream LLM timed out")
            degradations.record("sommeil: reve, appel LLM expire", exc)
            return None
        except UnconfiguredRoleError as exc:
            logger.warning("Sleep: rêve ignoré — IA non configurée: %s", exc)
            degradations.record("sommeil: reve, IA non configuree", exc)
            return None
        except Exception as exc:
            logger.exception("Sleep: dream LLM failed")
            degradations.record("sommeil: reve, appel LLM en echec", exc)
            return None

        if not raw or not raw.strip():
            return None
        try:
            data = json.loads(strip_markdown_json(raw.strip()))
        except json.JSONDecodeError as exc:
            logger.warning("Sleep: dream JSON parse failed: %.200s", raw)
            degradations.record("sleep: JSON du reve illisible", exc)
            return None

        content = (data.get("content") or "").strip()
        if not content:
            return None
        return {
            "content": content[:800],
            "emotion": _emotion_canonique(data.get("emotion")),
            "vividness": max(0.0, min(1.0, float(data.get("vividness", 0.5)))),
        }

    @staticmethod
    async def _persist_dream(
        *,
        current_night: date,
        fragments: dict,
        dream_type: str,
        content: str,
        emotion: str,
        vividness: float,
    ) -> None:
        from memory.models import Dream

        dream = await sync_to_async(Dream.objects.create)(
            night_of=current_night,
            content=content,
            dream_type=dream_type,
            vividness=vividness,
            emotion=emotion,
            source_rumination=fragments.get("rumination"),
        )
        # M2M attach
        if fragments["souvenirs"]:
            await sync_to_async(
                lambda: dream.source_souvenirs.set(fragments["souvenirs"])
            )()

    # ── Phase 3: Deep sleep — rumination digestion ───────────────

    async def _digest_ruminations(self) -> int:
        """Accelerate decay + mutate emotions of old active ruminations.

        This is the "healing" phase: thoughts that kept Mika up are
        resolved in sleep the way a human wakes up with a clearer head.
        The most intense ones get converted into reflective Souvenirs.

        Returns the number of ruminations processed.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return 0

        age_min = cfg_int(
            "memory.digestion_min_age_minutes", DIGESTION_MIN_AGE_MINUTES,
            mini=5, maxi=1440,
        )
        seuil_souvenir = cfg_float(
            "memory.digestion_to_souvenir_threshold", DIGESTION_TO_SOUVENIR_THRESHOLD,
            mini=0.0, maxi=1.0,
        )
        cutoff = tz.now() - timedelta(minutes=age_min)
        try:
            aging = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active", created_at__lte=cutoff)[:30]
                )
            )()
        except Exception as exc:
            # Un lot illisible rendait 0, exactement comme « rien à digérer » :
            # la phase de guérison pouvait échouer toutes les nuits sans qu'un
            # seul compteur ne bouge.
            degradations.record("sommeil: ruminations a digerer illisibles", exc)
            return 0

        if not aging:
            return 0

        from memory.manager import memory_manager

        def _digerer_ligne(pk: int) -> tuple[float, str, bool] | None:
            """Relit la ligne et applique la digestion sur ses valeurs fraîches.

            La boucle de décision de la conscience écrit `status`/`intensity`
            sur les mêmes lignes toutes les 30 s, et la digestion await entre
            chaque écriture (dont un embedding ChromaDB) : rejouer un `status`
            lu au début de la passe ressuscitait en `active` — ou pire figeait
            en `faded` — une rumination résolue entre-temps. Lecture et
            écriture tiennent donc dans un seul callable synchrone, que
            `sync_to_async(thread_sensitive=True)` sérialise sur le même thread
            d'exécuteur que les bulk_update de la conscience.
            """
            row = Rumination.objects.filter(pk=pk).first()
            if row is None or row.status != "active":
                return None

            avant = row.intensity
            row.intensity *= (1.0 - 0.05 * DIGESTION_DECAY_MULTIPLIER)
            derive = DIGESTION_DRIFT.get(row.emotion)
            if derive and derive != row.emotion:
                row.emotion = derive
            if row.intensity < 0.15:
                row.status = "faded"
            # Le souvenir réflexif, UNE fois par pensée — marqué à la
            # tentative, dans la même écriture, pour qu'une pensée encore
            # active la nuit suivante ne le redonne pas.
            a_reflechir = avant >= seuil_souvenir and row.reflechie_le is None
            champs = ["intensity", "emotion", "status"]
            if a_reflechir:
                row.reflechie_le = tz.now()
                champs.append("reflechie_le")
            row.save(update_fields=champs)
            return avant, row.emotion, a_reflechir

        processed = 0
        for r in aging:
            try:
                frais = await sync_to_async(_digerer_ligne)(r.pk)
            except Exception as exc:
                degradations.record("sommeil: ecriture de la digestion", exc)
                continue
            if frais is None:
                continue
            processed += 1

            # Les lourdes deviennent un souvenir réflexif — après l'écriture,
            # pour que l'aller-retour ChromaDB soit hors de la fenêtre de course.
            old_intensity, emotion, a_reflechir = frais
            if a_reflechir:
                try:
                    # Passe par le manager, qui cree *et* indexe dans ChromaDB.
                    # C'est l'insight avec lequel on se reveille : ecrit
                    # seulement en base, il n'atteindrait jamais un prompt,
                    # la remémoration partant exclusivement du vectoriel.
                    souvenir = await memory_manager.create_souvenir(
                        content=(
                            f"Apres y avoir repense cette nuit: {r.summary[:200]}"
                        ),
                        emotion=emotion or "thinking",
                        importance=min(0.85, old_intensity + 0.1),
                    )
                    if souvenir:
                        logger.debug(
                            "Sleep: digested rumination #%s -> reflective souvenir #%s",
                            r.pk, souvenir.pk,
                        )
                except Exception as exc:
                    degradations.record("sommeil: creation du souvenir reflexif", exc)

        logger.info("Sleep: digested %d rumination(s) in deep sleep", processed)
        return processed


# Module-level singleton, matching the pattern used by narrative_generator
# and person_profile_generator.
sleep_cycle = SleepCycle()
