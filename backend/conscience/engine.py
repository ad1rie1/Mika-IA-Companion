"""ConscienceEngine — Mika's waking brain.

Sits above modules. Observes all events, interprets them, maintains
memory, and decides when to speak or act. Tightly coupled to memory
with full R/W access.

Lifecycle (managed by ASGI lifespan):
  1. initialize()   — start decision loop
  2. observe(event)  — called by event bus for every module event
  3. _decide()       — periodic evaluation (every 30s, PeriodicLoop)
  4. shutdown()      — stop everything
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db.models import F

from ai.budget import tools_prompt_chars
from configs.runtime import cfg_float, cfg_int
from conscience.interpreter import SignalInterpreter
from conscience.memory_bridge import MemoryBridge
from conscience.trousse import (
    DEFAULT_TUNING as DEFAULT_TROUSSE_TUNING,
    TrousseTuning,
    preparer,
    resume_capacites,
)
from conscience.scoring import (
    SLEEP_PENALTY,
    SLEEP_WAKE_PERTINENCE,
    SLEEP_WAKE_SCHEDULED_PRIORITY,
    SUPPRESS_RELEASE_IDLE_SECONDS,
    ScoringTuning,
    compute_decision_score,
)
from conscience.conduite import (
    Conduite,
    decider_diffusion,
    ConduiteTuning,
    TravailEnCours,
    choisir_conduite,
    est_essouffle,
    facturer_envie,
    recolter_graines,
)
from conscience.verdict import (
    CONSIGNE_VERDICT,
    EtatVerdict,
    VerdictTuning,
    depouiller_verdict,
)
from conscience.murmure import murmurer
from conscience.murmure_reglage import tuning as murmure_tuning
from conscience.types import DecisionContext, InterpretedSignal
from conscience.vecu import (
    PULSION_FORTE,
    PULSION_GATE,
    VecuTuning,
    cible_de_derive,
    composer_declencheurs,
    declencheurs_actifs,
    phrase_de_rejeu,
)
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from modules.types import ModuleEvent, ModuleNotification
from utils.degradation import degradations, degraded
from utils.tool_trace import journal_outils
from utils.periodic import PeriodicLoop

logger = logging.getLogger(__name__)

# ── Portes de pertinence ──────────────────────────────────────────────
#
# Elles vivent au niveau module, et pas en attribut de classe comme leurs
# aînées : la garde AST de `test_config_rapatriement` résout un repli
# `ast.Name` en attribut **du module**, et ignore silencieusement un
# `self._X`. Un repli en attribut de classe n'est donc jamais confronté au
# défaut déclaré — exactement la divergence que la garde existe pour
# empêcher.
#
# Toutes se lisaient en dur, et toutes étaient hors d'atteinte : le chemin
# heuristique de l'interpréteur ne produit au mieux que 0.55 (RSS apparié),
# le reste étant à 0.40 et moins. Une promotion à 0.5, un boost à 0.7 et un
# fast-path à 0.85 ne pouvaient donc être franchis que par `email.received`,
# seul signal payant un appel LLM. Sur une installation sans compte mail —
# celle par défaut — six mécanismes ne se déclenchaient jamais.

#: Pertinence à partir de laquelle une observation périmée devient une pensée.
PROMOTION_PERTINENCE = 0.45
#: Au-delà, on ne promeut plus : une pensée de plus ne se pense pas mieux.
#:
#: Descendre la porte sans ce plafond installe une pression permanente sur le
#: Facteur 10 (jusqu'à +0.30) et annule la moitié du gain de désaturation.
PROMOTION_ACTIVES_MAX = 6
#: Pertinence à partir de laquelle un signal ravive les souvenirs de ses thèmes.
BOOST_PERTINENCE = 0.50
#: Pertinence à partir de laquelle on vérifie qu'un signal ne contredit rien.
#:
#: Volontairement **laissée en haut** alors que tout le reste descend : cette
#: branche coûte jusqu'à cinq appels IA, et seuls `chat` et `telegram` la
#: visent. La déclarer sans la bouger la rend réglable sans la banaliser.
CONTRADICTION_PERTINENCE = 0.80
#: Pertinence minimale pour qu'une observation pèse dans l'urgence accumulée.
URGENCY_OBSERVATION_GATE = 0.3
#: Poids d'une observation dans cette somme.
URGENCY_PER_OBSERVATION = 0.5
#: Pas maximum d'un chantier avant qu'il soit clos d'office. Un travail sans
#: terme n'est pas un travail.
_TRAVAIL_PAS_MAX = 5
#: Observations et actions programmées effectivement montrées au modèle.
#:
#: Ce sont les bornes qui rendent le marquage honnête possible : jusqu'ici le
#: prompt en montrait 5 et 3 pendant que l'acte en clôturait 20 et 10.
_BRIEF_OBSERVATIONS_MAX = 5
_BRIEF_ACTIONS_MAX = 3
#: Sujets retenus parmi ceux que les modules proposent. Petit : c'est une
#: curiosité, pas un inventaire — et chacun concourt aux trois places.
_GRAINES_MODULES_MAX = 3
#: Cycles sautés d'affilée avant que la boucle compte un échec. Un acte tient
#: le verrou jusqu'à ~135 s, soit quatre cycles : en sauter trois est normal.
_CYCLES_SAUTES_MAX = 6
#: Tentatives d'une action programmée avant abandon.
_SCHEDULED_TENTATIVES_MAX = 3


@dataclass(frozen=True)
class ActionBrief:
    """Le prompt d'un acte, ET ce qu'il a réellement mis sous les yeux.

    Les deux vont ensemble : c'est tout l'objet de cette classe. Le prompt
    montrait cinq observations et trois actions programmées, et l'acte en
    clôturait vingt et dix — au seul motif que l'appel n'avait pas planté. Sept
    intentions qu'elle s'était données disparaissaient à chaque acte,
    estampillées faites, pendant que le journal annonçait « Executed 10
    scheduled action(s) ».

    Rendre le texte seul rendait cette divergence indétectable : rien, dans une
    chaîne de caractères, ne dit ce qu'elle contient.
    """

    texte: str
    observations: tuple = ()
    actions: tuple = ()


@dataclass(frozen=True)
class ActeResultat:
    """Ce qu'un acte a produit. Remplace un booléen qui disait trop peu.

    **Piège à ne pas rouvrir** : l'appelant testait `if spoke:` sur le retour.
    Un dataclass est toujours vrai, donc rendre un objet sans corriger le test
    ferait journaliser « act » sur un acte qui a échoué — ce qui gonflerait
    `acts_today`, compterait comme un acte ignoré faute de réponse possible, et
    trois pannes suffiraient à brider la conscience pour la journée. La
    véracité se lit sur `dit`, jamais sur l'objet.
    """

    dit: str = ""
    person_id: str = ""
    outils: str = ""
    outils_reussis: int = 0
    trousse: tuple = ()
    ai_failed: bool = False
#: Somme d'intensités valant une pression de rumination pleine (1.0).
#:
#: La somme était comparée à 1.0 : deux pensées à 0.5 saturaient déjà le
#: Facteur 10. Avec une promotion plus ouverte, la saturation deviendrait
#: l'état normal et le facteur cesserait d'informer.
RUMINATION_PRESSION_PLEINE = 2.5


class ConscienceEngine:
    """Singleton. Mika's waking consciousness.

    Short-term buffer: recent Observations (in DB, queried on sliding window).
    Long-term memory: R/W via MemoryBridge.
    """

    def __init__(self):
        self.interpreter = SignalInterpreter()
        self.memory = MemoryBridge()

        # State
        # Même primitive que les cinq autres boucles de fond : elle horodate
        # le dernier tick réussi et compte ses échecs, ce qu'une boucle
        # maison écrite ici ne faisait pas — une conscience muette depuis
        # trois jours ressemblait exactement à une conscience sans rien à dire.
        self._loop = PeriodicLoop("Conscience", self._decide, interval=30)
        self._decision_lock = asyncio.Lock()
        # Detached high-pertinence decision cycles, held so they aren't GC'd.
        self._fastpath_tasks: set[asyncio.Task] = set()
        self._last_activity: float = time.time()
        # Dernier versement d'une teinte de rumination dans l'humeur globale,
        # par étiquette émotionnelle. En RAM : perdre l'espacement au
        # redémarrage ne coûte qu'un versement de plus.
        self._rumination_bleed_at: dict[str, float] = {}
        self._last_action_time: float = 0.0
        self._greeted_periods: set[str] = set()
        self._greeted_date: object = None  # date of last greeting reset
        # Tentative greeting state from the last scoring pass, committed by
        # _commit_greeting() only when the decision is "act".
        self._pending_greeted: tuple[set[str], object] | None = None
        #: La salutation que le dernier scoring vient de déclencher, ou None.
        self._salutation_en_attente: str | None = None
        self._initialized = False
        self._consecutive_waits: int = 0
        # Horodatages monotones des balayages d'entretien etrangles (voir
        # _CLEANUP_INTERVAL_S). En RAM : perdre la cadence au redemarrage ne
        # coute qu'un passage supplementaire.
        self._last_cleanup: float = 0.0
        self._last_stale_sweep: float = 0.0
        self._last_drive_save: float = 0.0

        # Config (loaded from settings on initialize)
        self._decision_interval: int = 30
        self._cooldown_seconds: int = 300
        self._threshold: float = 0.5

    # ── Lifecycle ─────────────────────────────────────────────────

    async def initialize(self) -> None:
        if self._initialized:
            return

        from configs.service import config_service
        self._decision_interval = config_service.get("conscience.decision_interval")
        self._cooldown_seconds = config_service.get("conscience.cooldown_seconds")
        self._threshold = config_service.get("conscience.act_threshold")

        # Hot-reload: update live parameters when the user edits them in
        # the dashboard. Decision interval requires a loop restart so we
        # flag it; threshold + cooldown take effect on the next tick.
        config_service.on_change("conscience.act_threshold",
                                 lambda k, v: setattr(self, "_threshold", v))
        config_service.on_change("conscience.cooldown_seconds",
                                 lambda k, v: setattr(self, "_cooldown_seconds", v))

        # Restore cooldown from last "act" decision log (survives restarts)
        await self._restore_cooldown()
        await self._restaurer_inactivite()
        await self._reprendre_travaux()

        # Les pulsions se rechargent ici parce que la conscience est déjà leur
        # horloge — c'est elle qui appelle `update()`, et rien d'autre ne tick
        # le DriveEngine. Ajouter une boucle dédiée pour ça n'apprendrait rien
        # à personne.
        await drive_engine.restore_state()

        # Subscribe to the event bus rather than being installed into it by
        # ModuleManager.set_conscience(). The conscience is the thing that
        # wants to see every signal; the emitter should not have to know that.
        #
        # AWAIT at observer priority reproduces the previous ordering exactly:
        # she interprets and files her Observation before any module reacts,
        # and downstream code reads that row. The expensive part — deciding
        # whether to *act* on it — is already spawned inside observe().
        from pipeline.signals import TURN_COMPLETED
        from utils.eventbus import PRIORITY_OBSERVER, DeliveryMode, event_bus
        event_bus.subscribe(
            self.observe,
            name="conscience",
            mode=DeliveryMode.AWAIT,
            priority=PRIORITY_OBSERVER,
        )

        # Second, separate subscription: the post-action audit. It was an
        # inline call at the tail of process_message, so the pipeline had to
        # know that a rumination is what follows an emotionally marked reply.
        #
        # Deliberately not folded into observe(): a turn Mika just spoke is
        # not a signal about the world, and interpreting her own reply as an
        # external stimulus would cost an LLM call and file an Observation
        # every single turn. The internal `_turn.*` namespace is invisible
        # to the wildcard `observe` subscription for exactly that reason.
        event_bus.subscribe(
            self._audit_completed_turn,
            name="conscience.audit",
            pattern=TURN_COMPLETED,
            # Detached: it writes a Rumination and has nothing the turn is
            # waiting on. Awaiting it added DB work to every reply.
            mode=DeliveryMode.SPAWN,
        )

        await self._loop.start(interval=self._decision_interval)
        self._initialized = True

        logger.info(
            "Conscience initialized (interval=%ds, cooldown=%ds, threshold=%.1f)",
            self._decision_interval,
            self._cooldown_seconds,
            self._threshold,
        )

    async def _restore_cooldown(self) -> None:
        """Restore _last_action_time from the most recent 'act' ConscienceLog.

        This ensures the cooldown survives process restarts — without it,
        the conscience would act immediately after every restart.
        """
        from conscience.models import ConscienceLog

        try:
            last_act = await sync_to_async(
                lambda: ConscienceLog.objects.filter(decision="act")
                .order_by("-created_at")
                .first()
            )()
            if last_act:
                self._last_action_time = last_act.created_at.timestamp()
                elapsed = time.time() - self._last_action_time
                if elapsed < self._cooldown_seconds:
                    logger.info(
                        "Conscience cooldown restored: %ds remaining",
                        int(self._cooldown_seconds - elapsed),
                    )
                else:
                    logger.debug("Last conscience action was %ds ago (cooldown expired)", int(elapsed))
        except Exception as exc:
            degradations.record("conscience: could not restore cooldown", exc)

    async def shutdown(self) -> None:
        # Detach before cancelling the loop: an event arriving mid-shutdown
        # would otherwise be interpreted by an engine that is on its way out.
        from utils.eventbus import event_bus
        event_bus.unsubscribe("conscience")
        event_bus.unsubscribe("conscience.audit")

        await self._loop.stop()
        await drive_engine.save_state()

        self._initialized = False
        logger.info("Conscience shut down")

    # ── 1. OBSERVE ────────────────────────────────────────────────

    async def observe(self, event: ModuleEvent) -> None:
        """Receive a module event, interpret it, store it.

        Called by the event bus (ModuleManager.emit_event callback).
        If the signal is important enough, immediately creates a souvenir.
        Emotional reactions from interpreted signals feed into the EmotionEngine
        so the VTuber actually *feels* what she observes.
        """
        signal = await self.interpreter.interpret(event)
        observation = await self._store_observation(event, signal)

        # Feed emotional reaction into the EmotionEngine
        if signal.emotional_reaction and signal.emotional_intensity > 0.1:
            self._feed_emotion(signal)

        # Immediate memory action for high-pertinence signals
        if signal.should_remember and signal.pertinence > 0.5:
            souvenir = await self.memory.create_souvenir_from_signal(signal)
            if souvenir and observation:
                observation.souvenir = souvenir
                await sync_to_async(observation.save)(update_fields=["souvenir"])

        # Track activity for idle detection
        if event.event_type in ("chat.message", "telegram.message"):
            self.note_activity()
            # L'assouvissement de SOCIAL/CURIOSITY par un message n'est plus
            # décidé ici : c'est une politique des pulsions, déclarée dans
            # drives/apps.py sur `_turn.completed`, donc valable pour tout
            # canal d'entrée et non pour les seuls noms d'événements listés
            # ci-dessus.
        else:
            # External signal (email, RSS, schedule) — feeds curiosity
            # proportionally to pertinence.
            drive_engine.on_observation(signal.pertinence)

        logger.debug(
            "Observed: %s/%s → %s (p=%.1f)",
            event.source_module, event.event_type,
            signal.category, signal.pertinence,
        )

        # Fast-path: critical signals trigger an immediate decision cycle.
        # Scheduled, not awaited: observe() is called from inside
        # ModuleManager.emit_event, which the email/RSS pollers await. Running
        # the decision inline blocked the emitting module's loop for the two
        # LLM calls (_act's recipient selection + the full pipeline) that a
        # pertinent signal triggers.
        # Même barre que le veto de sommeil du scoring, et **une seule clé**
        # pour les deux : la faire diverger produirait une conscience qui se
        # réveille pour un signal qu'elle refusera ensuite de traiter.
        # `>=` et non `>` : `scoring.py` compare la même clé avec `>=`, si bien
        # qu'une pertinence pile sur la barre réveillait la décision sans que
        # le fast-path la déclenche, et inversement selon le chemin emprunté.
        if signal.pertinence >= cfg_float(
            "conscience.sleep_wake_pertinence", SLEEP_WAKE_PERTINENCE,
        ):
            logger.info(
                "High-pertinence signal (%.2f), triggering immediate decision",
                signal.pertinence,
            )
            self._spawn_decision()

    @staticmethod
    def _feed_emotion(signal: InterpretedSignal) -> None:
        """Inject an interpreted signal's emotional reaction into the EmotionEngine.

        Uses person_id "conscience_mika" — the VTuber feeling something
        from her own observation, not from a conversation partner.
        """
        from emotion.types import Emotion, EmotionData

        try:
            emotion = Emotion(signal.emotional_reaction)
        except ValueError:
            logger.debug(
                "Unknown emotion from signal: %s", signal.emotional_reaction
            )
            return

        data = EmotionData(emotion=emotion, intensity=signal.emotional_intensity)
        emotion_engine.process_emotion(data, "conscience_mika")
        logger.debug(
            "Fed emotion %s:%.2f from observation into EmotionEngine",
            emotion.value, signal.emotional_intensity,
        )

    async def _store_observation(self, event, signal):
        """Persist an observation to DB."""
        from conscience.models import Observation

        try:
            # Les themes produits par l'interpretation n'ont pas de champ
            # dedie : ils sont fusionnes dans raw_data, seul endroit ou
            # _memory_maintenance et _promote_stale_to_ruminations vont les
            # relire. Aucun emetteur d'evenement ne pose de cle "themes",
            # donc sans cette fusion les deux lectures renvoient toujours [].
            raw_data = dict(event.data or {})
            raw_data["themes"] = signal.themes
            # Les entités nommées par l'interprétation mouraient à la
            # frontière (produites, jamais persistées) alors qu'elles sont
            # exactement ce qu'un rappel dirigé ou un routage par personne
            # peut exploiter plus tard.
            raw_data["entities"] = [str(e) for e in (signal.entities or []) if e]

            return await sync_to_async(Observation.objects.create)(
                source=event.source_module,
                event_type=event.event_type,
                raw_data=raw_data,
                summary=signal.summary,
                category=signal.category,
                pertinence=signal.pertinence,
                emotional_reaction=signal.emotional_reaction,
                emotional_intensity=signal.emotional_intensity,
            )
        except Exception:
            logger.exception("Failed to store observation")
            return None

    # ── 2. DECISION LOOP ──────────────────────────────────────────

    async def _decide(self) -> None:
        """Core decision: evaluate accumulated signals, maintain memory, maybe act.

        Protected by _decision_lock to prevent concurrent decisions from
        the periodic loop and high-pertinence fast-path racing.
        Note: locked() check is safe in asyncio (single-threaded event loop,
        no preemption between check and acquire within the same coroutine step).
        """
        if self._decision_lock.locked():
            # Un `return` nu laissait `PeriodicLoop` marquer le tick en succès :
            # « conscience figée sur un appel qui ne rend pas la main » et
            # « conscience en bonne santé » étaient rigoureusement
            # indiscernables sur les deux écrans faits pour les distinguer.
            #
            # Sauter une fois est normal — un acte tient le verrou jusqu'à
            # ~135 s, soit quatre cycles. En sauter beaucoup d'affilée ne l'est
            # pas, et la seule façon de le faire savoir à une boucle que
            # personne ne supervise est de la laisser compter un échec.
            self._cycles_sautes += 1
            plafond = cfg_int(
                "conscience.cycles_sautes_max", _CYCLES_SAUTES_MAX, mini=1,
            )
            logger.debug(
                "Decision already in progress, skipping (%d d'affilée)",
                self._cycles_sautes,
            )
            if self._cycles_sautes >= plafond:
                raise RuntimeError(
                    f"décision bloquée : {self._cycles_sautes} cycles sautés "
                    "d'affilée — le verrou n'a pas été rendu"
                )
            return
        self._cycles_sautes = 0

        async with self._decision_lock:
            await self._decide_inner()

    def _spawn_decision(self) -> None:
        """Run a decision cycle detached from the caller's await chain.

        A strong reference is kept until completion: a bare create_task can be
        garbage-collected mid-flight, and exceptions in a dropped task vanish
        silently.
        """
        task = asyncio.create_task(self._decide())
        self._fastpath_tasks.add(task)
        task.add_done_callback(self._fastpath_tasks.discard)
        task.add_done_callback(self._log_fastpath_result)

    @staticmethod
    def _log_fastpath_result(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Fast-path decision failed: %r", exc, exc_info=exc)

    async def _decide_inner(self) -> None:
        """Inner decision logic (caller must hold _decision_lock)."""
        resultat = ActeResultat()
        ctx = await self._build_context()

        # Memory maintenance (runs every cycle, even without acting)
        memory_actions = await self._memory_maintenance(ctx)

        # Compute decision score
        score, reason = self._compute_score(ctx)

        # Quelle conduite tenir. L'ordre est conservateur et le reste :
        # PARLER l'emporte dès que le score franchit le seuil, exactement comme
        # avant — ce lot ne peut pas la rendre plus bavarde, seulement moins
        # muette. POURSUIVRE et OUVRIR vivent dans l'espace qui s'appelait
        # « wait », c'est-à-dire là où il ne se passait rien.
        #
        # Rien n'est lu ni ouvert pendant qu'elle dort : un chantier est une
        # activité de veille, et le veto de sommeil du scoring a déjà tranché.
        travaux: list = []
        graines: list = []
        if ctx.sleep_phase == "awake":
            from django.utils import timezone as tz
            maintenant = tz.now()
            travaux, semees = await self._travaux_en_cours(maintenant)
            graines = self._recolter(ctx, semees)
        else:
            maintenant = None

        conduite = choisir_conduite(
            score=score,
            seuil=self._threshold,
            travaux=travaux,
            graines=graines,
            maintenant=maintenant,
            # Le veto est déjà dans le score : 0.0 en cooldown, 0.0 endormie.
            # Le répéter ici ferait deux politiques pour une même règle.
            peut_parler=True,
            peut_travailler=ctx.sleep_phase == "awake",
            tuning=self._conduite_tuning(),
        )

        # Determine decision outcome — inchangé mot pour mot pour PARLER.
        if conduite.conduite is Conduite.PARLER:
            decision = "act"
        elif conduite.conduite is Conduite.OUVRIR:
            decision = "ouvrir"
        elif conduite.conduite is Conduite.POURSUIVRE:
            decision = "poursuivre"
        elif not ctx.pending_observations:
            decision = "skip"
        else:
            decision = "wait"

        # Update consecutive wait counter. An "act" only clears the
        # accumulated pressure once it has actually been delivered — see below.
        if decision == "wait":
            self._consecutive_waits += 1
        elif decision == "skip":
            self._consecutive_waits = 0

        if decision == "act":
            # Se réveiller pour de bon avant de parler. `_act` appelle
            # `process_message` en direct et non `perceive()`, seul appelant de
            # `note_interaction()` : elle restait donc officiellement en
            # `deep_sleep` pendant son propre acte — avatar yeux fermés, et
            # `pipeline/voice.py` refusant la parole. Le message s'affichait en
            # silence.
            #
            # `note_interaction()` et **jamais** `note_activity()` : le premier
            # dit « elle est éveillée », le second « quelqu'un s'est
            # manifesté ». Les confondre ferait retomber son inactivité à zéro
            # à chacune de ses initiatives, ce qui supprimerait le Facteur 4 et
            # rendrait le silence invisible à sa propre mesure.
            with degraded("conscience: reveil du cycle de sommeil"):
                from memory.sleep import sleep_cycle
                sleep_cycle.note_interaction()

            # On l'entend décider. Les deux bornes de cette position sont
            # chargées, et l'inverser casse quelque chose des deux côtés :
            #
            # — APRÈS `note_interaction()`, qui pose la phase à AWAKE de façon
            #   *synchrone*. Une ligne plus haut, la garde de sommeil du
            #   murmure lirait `deep_sleep` et se tairait chaque nuit — soit
            #   exactement les cycles où une pensée à voix haute rend la nuit
            #   habitée plutôt que muette.
            # — AVANT `_act`, qui contient `_select_recipient` : au point
            #   d'appel, aucun destinataire n'existe encore dans la portée. Le
            #   piège du `person_id` — qui basculerait la persona en SPEAKING,
            #   donc en note vocale sur Telegram — devient structurellement
            #   impossible plutôt que garanti par vigilance.
            #
            # ATTENDU et non détaché : l'ordre EST le propos. Une tâche
            # détachée courrait contre l'appel de `_act` sur le même sémaphore
            # de provider (un seul créneau par défaut sur Ollama), et le
            # murmure sortirait après la phrase qu'il devait précéder, de façon
            # non déterministe. Le coût est borné à 12 s par le `wait_for` de
            # `generate_inner_thought`, contre une branche qui tient déjà
            # `_decision_lock` jusqu'à ~135 s — et il n'est payé que dans cette
            # branche, jamais aux 2 880 tours quotidiens.
            intention = self._intention_de_lacte(ctx)
            with degraded("conscience: murmure avant l'acte"):
                await murmurer(
                    intention,
                    mood=ctx.global_mood,
                    mode_professionnel=await self._mode_professionnel(intention),
                    tuning=murmure_tuning(),
                )

            # `resultat.dit` et **jamais** `if resultat:` — un dataclass est
            # toujours vrai. Tester l'objet ferait journaliser « act » sur un
            # acte échoué, ce qui gonflerait `acts_today` et, ne pouvant
            # recevoir aucune réponse, compterait comme un acte ignoré : trois
            # pannes suffiraient à brider la conscience pour la journée.
            resultat = await self._act(ctx, reason)
            if resultat.dit:
                # The greeting is spent only now that Mika really speaks.
                self._commit_greeting()
                self._consecutive_waits = 0
            else:
                # L'appel IA a echoue : rien n'a ete dit, donc rien n'est
                # committe. Journalise "failed" plutot que "act", sans quoi
                # un acte jamais delivre gonfle acts_today et, ne pouvant
                # recevoir aucune reponse, compte comme un acte ignore — trois
                # pannes suffisaient alors a brider la Conscience (scoring.py)
                # pour le reste de la journee.
                decision = "failed"
        else:
            if decision == "ouvrir" and not await self._ouvrir_travail(
                conduite.cible
            ):
                decision = "wait"
            elif decision == "poursuivre":
                cible = getattr(conduite.cible, "identifiant", conduite.cible)
                if not await self._faire_un_pas(cible):
                    decision = "wait"
            # Sur les TROIS conduites non parlantes, et non plus seulement sur
            # « skip » et « wait » : la péremption des observations entraîne
            # leur promotion en pensées et la décroissance des ruminations. Ne
            # l'appeler que sur deux branches ferait sauter tout ce ménage à
            # chaque cycle qui ouvre ou poursuit un chantier — c'est-à-dire
            # précisément aux cycles où elle a le plus de matière.
            await self._mark_stale_observations()

        # Log the decision — written after the act, whose outcome is part of
        # what the cycle decided (and what _introspect / _restore_cooldown read).
        await self._log_decision(
            ctx, decision, reason, score, memory_actions,
            conduite=conduite.conduite.value, resultat=resultat,
        )

        # Periodic cleanup of old observations
        await self._cleanup_old_observations()

        # Instantané des pulsions, étranglé. Sauver au seul `shutdown()` ne
        # couvrirait pas un `kill -9`, qui est exactement le cas où la fatigue
        # de la soirée disparaissait avec la nuit qu'elle devait déclencher.
        await self._save_drives_if_due()

    _DRIVE_SAVE_INTERVAL_S = 300

    async def _save_drives_if_due(self) -> None:
        now = time.time()
        intervalle = cfg_int(
            "conscience.drive_save_interval_seconds", self._DRIVE_SAVE_INTERVAL_S,
        )
        if self._last_drive_save and (now - self._last_drive_save) < intervalle:
            return
        self._last_drive_save = now
        await drive_engine.save_state()

    async def _introspect(self) -> tuple[int, int]:
        """Query recent ConscienceLogs for self-awareness.

        Returns:
            (acts_today, consecutive_ignored_acts)
        """
        from conscience.models import ConscienceLog, Observation
        from conscience.read import debut_du_jour_local
        from datetime import timedelta

        today_start = debut_du_jour_local()
        # Lu ici, hors du thread d'exécuteur, et une seule fois : les deux
        # usages ci-dessous doivent parler de la même fenêtre, sinon un acte
        # peut être « répondu » pour la sélection des réponses et « ignoré »
        # pour le comptage.
        fenetre = timedelta(minutes=self._ignored_reply_window_minutes())

        def _query() -> tuple[int, int]:
            # One round-trip for the whole introspection. This runs on every
            # decision cycle (30s by default, forever, whether or not anyone
            # is talking), and the old shape was 2 queries plus one
            # `.exists()` per recent act — each its own sync_to_async thread
            # hop — to answer a question about at most 5 rows.
            acts_today = ConscienceLog.objects.filter(
                decision="act", created_at__gte=today_start,
            ).count()

            recent_act_times = list(
                ConscienceLog.objects.filter(decision="act")
                .order_by("-created_at")
                .values_list("created_at", flat=True)[:5]
            )
            if not recent_act_times:
                return acts_today, 0

            # Fetch every user reply since the oldest act in the window once,
            # then answer "was this act followed by a reply within 10 min?"
            # in Python. The window is bounded by definition — 5 acts.
            oldest = recent_act_times[-1]
            newest_window_end = recent_act_times[0] + fenetre
            replies = list(
                Observation.objects.filter(
                    event_type__in=("chat.message", "telegram.message"),
                    created_at__gt=oldest,
                    created_at__lte=newest_window_end,
                ).values_list("created_at", flat=True)
            )

            consecutive_ignored = 0
            for act_time in recent_act_times:
                deadline = act_time + fenetre
                if any(act_time < reply <= deadline for reply in replies):
                    break
                consecutive_ignored += 1
            return acts_today, consecutive_ignored

        try:
            return await sync_to_async(_query)()
        except Exception as exc:
            degradations.record("conscience: introspection", exc)
            return 0, 0

    # ── Réglages rapatriés ────────────────────────────────────────
    #
    # Les constantes de module restent en repli (une base injoignable ne doit
    # pas changer le comportement), et ces accesseurs sont le **bord** où la
    # configuration est lue : `conscience/scoring.py` reste une fonction pure,
    # sans registre ni base, et reçoit ses valeurs déjà résolues.

    #: Cycles consécutifs sautés parce que le verrou de décision était pris,
    #: et dernière annonce d'un travail terminé.
    #:
    #: Attributs de CLASSE et non d'instance : les tests construisent le moteur
    #: par `__new__` pour éviter d'ouvrir des boucles, donc `__init__` ne tourne
    #: pas. Un état lu sur `self` mais posé seulement dans `__init__` fait
    #: tomber ces chemins sur un `AttributeError` — et en production, la même
    #: forme casse dès qu'un singleton est reconstruit autrement.
    _cycles_sautes: int = 0
    _derniere_diffusion_travail = None

    #: Fenêtre des observations « en attente ». Trois lectures s'y accordent :
    #: ce que le scoring voit, ce que le balayage périme, et la borne haute de
    #: la promotion en rumination. Une seule clé, donc.
    _PENDING_WINDOW_MIN: int = 30
    #: Délai au-delà duquel une initiative sans réponse compte comme ignorée.
    _IGNORED_REPLY_WINDOW_MIN: int = 10
    #: Âge des observations closes avant purge.
    _OBSERVATION_RETENTION_H: int = 48

    def _pending_window_minutes(self) -> int:
        return cfg_int(
            "conscience.pending_window_minutes", self._PENDING_WINDOW_MIN, mini=1,
        )

    def _ignored_reply_window_minutes(self) -> int:
        return cfg_int(
            "conscience.ignored_reply_window_minutes",
            self._IGNORED_REPLY_WINDOW_MIN, mini=1,
        )

    def _scoring_tuning(self) -> ScoringTuning:
        """Les onze facteurs, lus dans la configuration, résolus **ici**.

        `compute_decision_score` ne connaît ni le registre ni la base : elle
        reçoit une `ScoringTuning` déjà remplie. C'est ce qui laisse aux tests
        unitaires du scoring leur valeur — ils mesurent la calibration
        déclarée, pas ce que contient la base de la machine qui les exécute.
        """
        d = ScoringTuning()  # les défauts *sont* les replis
        f = lambda cle, repli: cfg_float(f"conscience.{cle}", repli)  # noqa: E731
        i = lambda cle, repli: cfg_int(f"conscience.{cle}", repli)    # noqa: E731
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
            morning_start=i("greeting.morning_start", d.morning_start),
            morning_end=i("greeting.morning_end", d.morning_end),
            evening_start=i("greeting.evening_start", d.evening_start),
            evening_end=i("greeting.evening_end", d.evening_end),
            night_start=i("greeting.night_start", d.night_start),
        )

    def _vecu_tuning(self) -> VecuTuning:
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
        s = self._scoring_tuning()
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

    #: Ce qu'un motif donne comme intention, à l'infinitif. Sept entrées pour
    #: sept motifs — pas un gabarit par situation.
    _INTENTION_PAR_MOTIF: dict[str, str] = {
        "matin": "dire bonjour",
        "soir": "dire un mot sur la soirée",
        "nuit": "faire remarquer qu'il est tard",
        "inactivite": "relancer la conversation",
        "humeur": "dire ce que je ressens",
        "pulsion": "aller voir quelque chose de nouveau",
        "rumination": "reparler de ce qui me trotte dans la tête",
    }

    def _intention_de_lacte(self, ctx: DecisionContext) -> str:
        """Ce qu'elle s'apprête à faire, en une phrase, pour le murmure.

        **Jamais construite sur `reason`**, et c'est la contrainte qui décide
        de la forme. La sixième garde du murmure compare l'intention normalisée
        d'un tour à l'autre pour ne pas répéter la même pensée ; or `reason` et
        `ctx.drive_summary` embarquent des flottants (« curiosity:0.87 ») qui
        bougent à chaque cycle. S'appuyer dessus dépenserait le quota du jour
        en huit variantes d'une seule et même pensée.

        Un membre d'énumération, lui, ne dérive pas. La préférence va donc au
        plus concret : une action programmée nomme son objet, une observation
        porte son résumé, et à défaut le motif dominant donne un infinitif.

        Rendre `""` est une sortie valide : la garde « pas d'intention » du
        murmure coupe alors avant toute dépense.
        """
        try:
            if ctx.scheduled_actions:
                prompt = getattr(ctx.scheduled_actions[0], "prompt", "")
                if prompt:
                    return str(prompt)[:160]

            if ctx.pending_observations:
                meilleure = max(
                    ctx.pending_observations,
                    key=lambda o: getattr(o, "pertinence", 0.0),
                )
                resume = getattr(meilleure, "summary", "")
                if resume:
                    return f"réagir à : {str(resume)[:140]}"

            declencheurs = self._declencheurs(ctx)
            if declencheurs:
                motif = getattr(declencheurs[0].motif, "value", "")
                return self._INTENTION_PAR_MOTIF.get(motif, "")
            return ""
        except Exception as exc:
            degradations.record("conscience: intention de l'acte", exc)
            return ""

    async def _mode_professionnel(self, intention: str) -> bool:
        """Cet acte tombe-t-il dans le cadre d'un projet en mode professionnel ?

        Le trou que ceci referme : `gather_context` calcule bien
        `project_suppresses_emotion`, mais **saute la détection pour les
        `person_id` internes** — et `conscience_mika` en est un. Un acte
        spontané n'était donc jamais reconnu comme professionnel, et le murmure
        marmonnait affectivement au milieu d'un projet dont toute la raison
        d'être est qu'elle n'en fait rien de tel.

        La détection se fait sur l'**intention**, pas sur un message : c'est le
        seul texte que la conscience produise avant d'agir, et il décrit
        précisément ce qu'elle s'apprête à faire. Il est déjà calculé pour le
        murmure, donc rien n'est fait deux fois.

        Une requête par acte — jamais par tick, et jamais quand l'intention est
        vide. Fail-open : sans réponse, on suppose qu'elle n'est pas au travail,
        parce que se taire par erreur est plus coûteux que murmurer de trop.
        """
        if not intention:
            return False
        try:
            from projects.detection import (
                detect_project_for_message,
                load_project_for_prompt,
            )

            match = await detect_project_for_message(intention)
            if not match:
                return False
            data = await load_project_for_prompt(match.project_id)
            return bool(data) and data.get("emotion_policy") == "off"
        except Exception as exc:
            degradations.record("conscience: mode professionnel", exc)
            return False

    def _declencheurs(self, ctx: DecisionContext) -> list:
        """Les motifs actifs de ce cycle, dans l'ordre où ils se disent.

        Extrait de `_composer_vecu` parce que deux appelants en ont besoin :
        la phrase du prompt, et l'intention du murmure. Les recalculer
        séparément les ferait diverger — elle murmurerait une intention que le
        prompt ne mentionne pas.
        """
        from emotion.state import EMOTION_PROMPT_FR

        ligne = ctx.rumination_lignes[0] if ctx.rumination_lignes else {}
        pulsion = drive_engine.pulsion_saillante()
        return declencheurs_actifs(
            salutation=self._salutation_en_attente,
            idle_seconds=ctx.idle_seconds,
            # Le libellé français vit dans la couche d'émotion, jamais dans
            # `GestionSysteme.formatting` : là-bas `bored` vaut « s'ennuie »,
            # un verbe, qui donnerait « tu es vraiment s'ennuie » — et ce
            # serait le sens de dépendance inversé.
            humeur=EMOTION_PROMPT_FR.get(ctx.global_mood, ""),
            humeur_intensite=ctx.global_intensity,
            rumination_pression=ctx.rumination_pressure,
            rumination_resume=str(ligne.get("summary", ""))[:160],
            pulsion=pulsion.value if pulsion else "",
            pulsion_tension=(
                drive_engine.states[pulsion].tension if pulsion else 0.0
            ),
            tuning=self._vecu_tuning(),
        )

    # ── Les chantiers ─────────────────────────────────────────────

    def _conduite_tuning(self) -> ConduiteTuning:
        """Les seuils de la conduite, résolus **ici** — `conduite.py` est pur."""
        d = ConduiteTuning()
        f = lambda cle, repli: cfg_float(f"conscience.{cle}", repli)  # noqa: E731
        i = lambda cle, repli: cfg_int(f"conscience.{cle}", repli)    # noqa: E731
        return ConduiteTuning(
            graine_obs_pertinence=f(
                "travail.graine_obs_pertinence", d.graine_obs_pertinence),
            graine_pensee_intensite=f(
                "travail.graine_pensee_intensite", d.graine_pensee_intensite),
            graine_pulsion_tension=f(
                "travail.graine_pulsion_tension", d.graine_pulsion_tension),
            graines_max=i("travail.graines_max", d.graines_max),
            envie_demi_vie_s=f("travail.envie_demi_vie_s", d.envie_demi_vie_s),
            envie_plancher_abandon=f(
                "travail.envie_plancher_abandon", d.envie_plancher_abandon),
            envie_poursuite_min=f(
                "travail.envie_poursuite_min", d.envie_poursuite_min),
            ouverture_envie_min=f(
                "travail.ouverture_envie_min", d.ouverture_envie_min),
            travaux_actifs_max=i(
                "travail.travaux_actifs_max", d.travaux_actifs_max),
            pas_intervalle_min_s=f(
                "travail.pas_intervalle_min_s", d.pas_intervalle_min_s),
            diffusion_notable_min=f(
                "travail.diffusion_notable_min", d.diffusion_notable_min),
            diffusion_intervalle_min_s=f(
                "travail.diffusion_intervalle_min_s",
                d.diffusion_intervalle_min_s),
        )

    async def _travaux_en_cours(self, maintenant) -> tuple[list, set]:
        """Les chantiers vivants, et les amorces déjà semées.

        Le second élément est la clé de déduplication `(origine, reference)` :
        sans elle, une `Observation` reste « en attente » trente minutes et
        rouvrirait le même chantier à chaque cycle — trois places saturées en
        quatre-vingt-dix secondes.

        L'abandon des essoufflés se fait **dans le même callable synchrone**
        que la lecture. `sync_to_async(thread_sensitive=True)` sérialise sur un
        seul thread d'exécuteur : lire, boucler en RAM puis réécrire laisserait
        un autre écrivain s'intercaler entre les deux — le piège exact
        documenté sur `_decay_ruminations`.
        """
        from conscience.models import Travail

        t = self._conduite_tuning()

        def _passe() -> tuple[list, set]:
            vivants: list[TravailEnCours] = []
            semees: set[tuple[str, str]] = set()
            a_abandonner: list = []
            a_reveiller: list = []
            for row in Travail.objects.filter(statut=Travail.Statut.EN_COURS):
                # Une attente échue cesse d'en être une — ICI, parce que
                # c'est la seule relecture périodique des chantiers. Une
                # échéance absente (ligne d'avant la migration, verdict
                # tronqué) se relève aussi : un drapeau sans échéance est le
                # cul-de-sac exact que `reprendre_le` existe pour fermer.
                if row.en_attente_de_reponse and (
                    row.reprendre_le is None or row.reprendre_le <= maintenant
                ):
                    row.en_attente_de_reponse = False
                    row.reprendre_le = None
                    a_reveiller.append(row)
                vue = TravailEnCours(
                    identifiant=row.pk,
                    titre=row.titre,
                    envie=row.envie,
                    ancre_envie=row.ancre,
                    dernier_pas_le=row.dernier_pas_le,
                    pas_effectues=row.pas_effectues,
                    pas_max=row.pas_max,
                    en_attente_de_reponse=row.en_attente_de_reponse,
                    themes=tuple(row.themes or ()),
                )
                if est_essouffle(vue, maintenant, t):
                    row.statut = Travail.Statut.ABANDONNEE
                    a_abandonner.append(row)
                    continue
                vivants.append(vue)
                semees.add((row.origine, str(row.reference)))
            if a_abandonner:
                Travail.objects.bulk_update(a_abandonner, ["statut"])
            if a_reveiller:
                Travail.objects.bulk_update(
                    a_reveiller, ["en_attente_de_reponse", "reprendre_le"],
                )
            return vivants, semees

        try:
            return await sync_to_async(_passe, thread_sensitive=True)()
        except Exception as exc:
            degradations.record("conscience: lecture des travaux", exc)
            return [], set()

    def _recolter(self, ctx: DecisionContext, semees: set) -> list:
        """Les amorces que l'état courant contient, moins celles déjà semées.

        La déduplication passe **avant** `choisir_conduite` et non après : une
        amorce déjà transformée en chantier n'est plus une amorce, et la
        laisser concourir ferait choisir OUVRIR sur un objet qui existe déjà.
        """
        try:
            pulsion = drive_engine.pulsion_saillante()
            pulsions = (
                [(pulsion.value, drive_engine.states[pulsion].tension)]
                if pulsion else []
            )
            graines = recolter_graines(
                observations=ctx.pending_observations,
                pensees=ctx.rumination_lignes,
                pulsions=pulsions,
                tuning=self._conduite_tuning(),
            )
            graines = list(graines) + self._graines_des_modules(pulsion, pulsions)
            return [
                g for g in graines
                if (g.origine, str(g.reference)) not in semees
            ]
        except Exception as exc:
            degradations.record("conscience: recolte des graines", exc)
            return []

    def _graines_des_modules(self, pulsion, pulsions: list) -> list:
        """Ce que le monde propose, quand la curiosité a de quoi s'en saisir.

        C'est la moitié manquante de H1. `recolter_graines` savait déjà tirer
        une amorce d'une pulsion, mais son intitulé ne pouvait être qu'une
        formule générique — « aller voir quelque chose de nouveau » — parce que
        rien ne lui disait ce qu'il y avait à voir. Une envie sans objet ne
        peut ouvrir aucun chantier ; elle ne peut que se redire.

        Les modules répondent **de mémoire** (`propose_sujets`), donc ceci
        coûte zéro requête, et n'est demandé que lorsque la curiosité franchit
        déjà sa porte : pas d'appétit, pas de sollicitation.

        `reference` porte le nom du module et le sujet, ce qui suffit à la
        déduplication : le même titre RSS ne rouvre pas de chantier tant que le
        premier vit.

        Les deux pulsions **fécondes** sollicitent (`PULSIONS_FECONDES`), pas
        la seule curiosité : l'expression veut produire quelque chose, et la
        forge — qui propose « réparer mon application » — est exactement une
        offre pour elle. SOCIAL et REST restent muets, comme dans la récolte.
        """
        from conscience.conduite import PULSIONS_FECONDES, Graine

        if pulsion is None or getattr(pulsion, "value", "") not in PULSIONS_FECONDES:
            return []
        tension = pulsions[0][1] if pulsions else 0.0
        if tension < self._conduite_tuning().graine_pulsion_tension:
            return []

        try:
            from modules.manager import module_manager

            sujets = module_manager.collect_sujets()
        except Exception as exc:
            degradations.record("conscience: sujets proposes par les modules", exc)
            return []

        plafond = cfg_int(
            "conscience.travail.graines_modules_max", _GRAINES_MODULES_MAX, mini=0,
        )
        return [
            Graine(
                origine="pulsion",
                reference=f"{nom}:{sujet[:60]}",
                intitule=sujet,
                poids=tension,
                # Le module qui propose un sujet est celui dont le chantier
                # aura besoin pour le traiter : figé ici, il survit à la
                # retombée de la pulsion après le premier pas.
                modules=(nom,),
            )
            for nom, sujet in sujets[:plafond]
        ]

    async def _ouvrir_travail(self, graine) -> bool:
        """Poser un chantier en base. Aucun pas n'est fait ici."""
        from conscience.models import Travail
        from django.utils import timezone as tz

        try:
            await sync_to_async(Travail.objects.create)(
                titre=graine.intitule[:200],
                origine=graine.origine,
                reference=str(graine.reference)[:100],
                themes=list(graine.themes),
                # La trousse du chantier, figée à l'ouverture : c'est elle que
                # chaque pas rechargera, indépendamment de la tension de
                # pulsion du moment (que le premier pas réussi fait retomber).
                modules=[str(m) for m in (getattr(graine, "modules", ()) or ())],
                envie=max(0.0, min(1.0, graine.poids)),
                ancre_envie=tz.now(),
                pas_max=cfg_int("conscience.travail.pas_max", _TRAVAIL_PAS_MAX,
                                mini=1),
            )
            logger.info("Travail ouvert [%s]: %s", graine.origine, graine.intitule[:80])
            return True
        except Exception as exc:
            degradations.record("conscience: ouverture d'un travail", exc)
            return False

    def _composer_vecu(self, ctx: DecisionContext) -> str:
        """Ce qui la pousse à parler, dit en une phrase — tous les motifs.

        Remplace une chaîne de quatre `elif` sur des sous-chaînes de `reason` :
        un cycle qui cumulait salutation ET débordement d'humeur n'en gardait
        qu'un, et l'inactivité comme les pulsions faisaient monter le score
        sans qu'aucune phrase ne les nomme.

        Ne lève jamais : on est sur le chemin de l'acte, dans une boucle que
        personne ne supervise.
        """
        try:
            return composer_declencheurs(self._declencheurs(ctx))
        except Exception as exc:
            degradations.record("conscience: composition du vecu", exc)
            return ""

    async def _build_context(self) -> DecisionContext:
        """Gather all context needed for a decision."""
        from conscience.models import Observation


        now = time.time()

        # Pending observations (not acted upon, inside the pending window)
        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=self._pending_window_minutes())
        pending = await sync_to_async(
            lambda: list(
                Observation.objects.filter(
                    status="pending",
                    created_at__gte=cutoff,
                ).order_by("-pertinence")[:20]
            )
        )()

        # `Observation` n'a PAS de champ `themes` — celui du modèle appartient
        # à `Rumination`. `recolter_graines` les lit en
        # `getattr(obs, "themes", ())` et rendrait un tuple vide *en silence*
        # pour toute amorce venue du dehors : un chantier ouvert sur une news
        # naîtrait sans aucun thème, donc sans prise pour la mémoire. On les
        # hydrate depuis `raw_data`, où l'interpréteur les a écrits.
        for obs in pending:
            try:
                obs.themes = obs.raw_data.get("themes", []) or []
            except Exception as exc:
                degradations.record("conscience: themes d'une observation", exc)
                obs.themes = []

        # Emotional state
        glob = emotion_engine.global_mood
        idle = now - self._last_activity

        # Compute aggregate scores
        pertinences = [o.pertinence for o in pending]
        max_p = max(pertinences) if pertinences else 0.0
        # La porte était en dur à 0.3, soit exactement la pertinence d'un
        # message de chat : la comparaison étant stricte, un chat pesait
        # rigoureusement zéro dans l'urgence accumulée. `interpreter.py` le
        # documente déjà ; la clé rend le réglage possible sans toucher au code.
        porte_urgence = cfg_float(
            "conscience.factor.urgency_observation_gate", URGENCY_OBSERVATION_GATE,
        )
        poids_urgence = cfg_float(
            "conscience.factor.urgency_per_observation", URGENCY_PER_OBSERVATION,
        )
        weighted = sum(p * poids_urgence for p in pertinences if p > porte_urgence)

        # Poll due scheduled actions
        scheduled = await self._poll_scheduled_actions()

        # Introspection: query own recent behavior
        acts_today, consecutive_ignored_acts = await self._introspect()

        # Cooldown check: use in-memory timestamp (faster, no DB query, no race)
        now_ts = time.time()
        in_cooldown = (
            self._last_action_time > 0
            and (now_ts - self._last_action_time)
            < self._effective_cooldown(consecutive_ignored_acts)
        )

        # Drives: intrinsic motivation pressure
        drive_bonus, drive_summary = drive_engine.conscience_contribution()
        drive_rest_penalty = drive_engine.rest_penalty()

        # Rumination: persistent unresolved thoughts
        rum_pressure, rum_count, rum_lignes = await self._rumination_snapshot()

        # Energy: combines circadian phase with REST drive. Tired Mika
        # speaks less spontaneously (see scoring Factor 11).
        energy = drive_engine.energy_level()

        # Import local : memory.sleep importe conscience.engine en différé.
        sleep_phase = "awake"
        try:
            from memory.sleep import sleep_cycle
            sleep_phase = sleep_cycle.phase
        except Exception as exc:
            degradations.record("conscience: phase de sommeil illisible", exc)

        return DecisionContext(
            pending_observations=pending,
            global_mood=glob.emotion.value,
            global_intensity=glob.intensity,
            idle_seconds=idle,
            in_cooldown=in_cooldown,
            max_pertinence=max_p,
            weighted_urgency=min(1.0, weighted),
            scheduled_actions=scheduled,
            consecutive_waits=self._consecutive_waits,
            acts_today=acts_today,
            consecutive_ignored_acts=consecutive_ignored_acts,
            drive_bonus=drive_bonus,
            drive_summary=drive_summary,
            drive_rest_penalty=drive_rest_penalty,
            rumination_pressure=rum_pressure,
            rumination_count=rum_count,
            rumination_lignes=rum_lignes,
            energy=energy,
            sleep_phase=sleep_phase,
        )

    async def _rumination_snapshot(self) -> tuple[float, int, list[dict]]:
        """Pression des pensées actives, leur nombre, et les pensées elles-mêmes.

        Renvoie ``(pression_bornée_01, nombre, lignes)``. Tolérant : si le
        modèle n'est pas encore migré, ``(0.0, 0, [])``.

        Les lignes sont rendues **dès maintenant**, alors qu'aucun appelant ne
        les lit encore : c'est la même requête, le troisième élément ne coûte
        rien, et le lot qui branchera le contenu des ruminations sur le choix
        du sujet n'aura pas à revenir réécrire cette fonction — la classe de
        collision que la revue a le plus souvent relevée.

        La pression n'est plus la somme brute comparée à 1.0 : deux pensées à
        0.5 saturaient le Facteur 10, et une promotion plus ouverte aurait fait
        de la saturation l'état permanent.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return 0.0, 0, []

        try:
            lignes = await sync_to_async(
                lambda: list(
                    Rumination.objects
                    .filter(status="active")
                    .order_by("-intensity")
                    .values("id", "summary", "themes", "intensity", "emotion")[:20]
                )
            )()
        except Exception as exc:
            # Table may not exist yet (migration pending) — silencieux, mais
            # compté : sans ça le Facteur 10 du scoring tombe a 0.0 et une
            # panne totale ressemble a "elle n'a rien qui lui trotte en tete".
            degradations.record("conscience: rumination pressure snapshot", exc)
            return 0.0, 0, []

        if not lignes:
            return 0.0, 0, []
        total = sum(ligne["intensity"] for ligne in lignes)
        pleine = cfg_float(
            "conscience.rumination_pressure_full", RUMINATION_PRESSION_PLEINE,
            mini=0.01,
        )
        return min(1.0, total / pleine), len(lignes), lignes

    async def _resolve_ruminations_after_act(self) -> None:
        """When Mika speaks up, every active rumination loses half its charge.

        The relief is *unconditional*, not matched against what she actually
        said: the model here is "she got it off her chest", and the act of
        breaking her own silence is what does it, whatever the subject.
        Anything falling below 0.1 afterwards is marked resolved.

        The docstring used to promise theme-matching against the response
        text, and the signature carried a ``response_text`` nothing ever
        read — describing a behaviour the code has never had.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return

        try:
            active = await sync_to_async(
                lambda: list(Rumination.objects.filter(status="active")[:20])
            )()
        except Exception as exc:
            degradations.record("conscience: ruminations to relieve", exc)
            return

        for r in active:
            r.intensity *= 0.5
            if r.intensity < 0.1:
                r.status = "resolved"

        # Une seule ecriture pour le lot : ce sont deux champs scalaires
        # calcules en memoire, sans logique par ligne. Vingt save() separes,
        # c'etaient vingt sync_to_async serialises sur l'unique thread
        # d'executeur partage avec les autres boucles de fond.
        try:
            await sync_to_async(Rumination.objects.bulk_update)(
                active, ["intensity", "status"], batch_size=50,
            )
        except Exception as exc:
            degradations.record("conscience: rumination relief write", exc)

    # Emotional drift map for aging ruminations. A thought doesn't stay
    # the same shape forever — frustration that lingers becomes anxiety,
    # an unresolved excitement fades into melancholy, etc. Keyed by the
    # initial emotion, value is the label the rumination drifts toward
    # once it's been "turning over" long enough (cycle count threshold).
    _RUMINATION_DRIFT: dict[str, str] = {
        "frustrated": "anxious",
        "angry": "melancholic",
        "excited": "nostalgic",
        "happy": "nostalgic",
        "grateful": "nostalgic",
        "sad": "melancholic",
        "scared": "anxious",
        "jealous": "sad",
        "hopeful": "anxious",
        "curious": "confused",
        "surprised": "thinking",
        "embarrassed": "anxious",
        "lonely": "melancholic",
    }
    # Repli si la config est illisible — une base injoignable ne doit pas
    # rendre les pensées immortelles NI les tuer en deux minutes.
    _RUMINATION_HALF_LIFE_H: float = 6.0
    _RUMINATION_DRIFT_H: float = 1.0
    # En deçà, on ne réécrit pas la ligne : le temps s'accumule sur
    # `decayed_at` au lieu d'être perdu (cf. la décroissance des souvenirs).
    _RUMINATION_WRITE_DELTA: float = 0.005
    # Une pensée teinte l'humeur, elle ne la matraque pas. Sans cette borne,
    # une rumination qui vit désormais des heures enverrait une impulsion
    # toutes les 30 s dans l'humeur globale — l'ancienne cadence n'était
    # tolérable que parce que la pensée mourait en 22 minutes.
    _RUMINATION_BLEED_INTERVAL_S: float = 600.0
    #: Part de l'intensité d'une pensée effectivement versée dans l'humeur.
    #: Elle teinte, elle n'impose pas.
    _RUMINATION_BLEED_INTENSITY: float = 0.15

    #: Plafond de l'espacement, quoi qu'il arrive : au-delà d'une demi-journée
    #: sans un mot, se taire davantage n'est plus de la retenue, c'est une
    #: panne. Le frein dur (`acts_today >= 5`) reste la borne du jour.
    _COOLDOWN_MAX_S: float = 6 * 3600.0

    def _effective_cooldown(self, consecutive_ignored: int) -> float:
        """Le silence qu'elle s'impose avant de relancer, allongé à chaque fois.

        Les trois plafonds du scoring — inactivité +0.30, « on m'ignore » −0.30,
        pulsions +0.50 — somment exactement au seuil (0.50), comparé avec
        ``>=`` : l'égalité agit. Aucune quantité de messages sans réponse ne
        pouvait donc la faire taire, et comme le cooldown était constant, elle
        dépensait ses cinq initiatives quotidiennes en vingt minutes avant que
        le frein dur ne tombe — puis se taisait vingt-trois heures. Les deux
        moitiés sont fausses : la rafale colle, le silence qui suit est mort.

        Une personne qui n'obtient pas de réponse attend plus longtemps la fois
        suivante. C'est tout ce que fait ce facteur, et il suffit à étaler les
        mêmes cinq tentatives sur la journée.
        """
        base = float(self._cooldown_seconds)
        if consecutive_ignored <= 0:
            return base
        from configs.service import config_service

        try:
            facteur = float(config_service.get("conscience.ignored_backoff_factor"))
        except Exception:
            facteur = 2.5
        facteur = max(1.0, facteur)
        plafond = cfg_float(
            "conscience.cooldown_max_seconds", self._COOLDOWN_MAX_S, mini=1.0,
        )
        return min(plafond, base * (facteur ** consecutive_ignored))

    def _rumination_tuning(self) -> tuple[float, float]:
        """(demi-vie en heures, délai de dérive en heures), depuis la config."""
        from configs.service import config_service

        def _f(key: str, defaut: float) -> float:
            try:
                valeur = float(config_service.get(key))
                return valeur if valeur > 0 else defaut
            except Exception:
                return defaut

        return (
            _f("conscience.rumination_half_life_hours", self._RUMINATION_HALF_LIFE_H),
            _f("conscience.rumination_drift_hours", self._RUMINATION_DRIFT_H),
        )

    async def _decay_ruminations(self) -> None:
        """Fait vieillir les pensées en cours, en TEMPS RÉEL.

        Une pensée s'estompe parce que des heures passent, pas parce qu'une
        boucle a tourné. L'ancienne formule (`*= 0.95` à chaque cycle de 30 s)
        liait la durée de vie d'une rumination à la cadence de la boucle : une
        pensée « persistante » mourait en 22 minutes, et la moitié de ses
        lecteurs — la digestion nocturne à 120 minutes d'âge, le journal du
        soir, le fragment de rêve — ne pouvait structurellement jamais la voir.
        La demi-vie est maintenant une durée (`conscience.rumination_half_life_hours`,
        6 h par défaut) : une contrariété du soir est encore là au coucher, et
        c'est bien la nuit qui la digère.

        Dérive émotionnelle : au bout de `rumination_drift_hours`, une pensée
        change de forme — la frustration devient de l'inquiétude. Elle aussi se
        compte en heures.

        **Lecture, calcul et écriture tiennent dans un seul appel synchrone.**
        `sync_to_async(thread_sensitive=True)` les sérialise donc sur le même
        thread d'exécuteur que la digestion du sommeil : un `status` lu avant
        elle ne peut plus être réécrit après, ce qui ressuscitait en `active`
        une pensée que la nuit venait de faner.
        """
        try:
            from conscience.models import Rumination
        except ImportError:
            return

        demi_vie_h, derive_h = self._rumination_tuning()

        def _passe() -> list[tuple[str, float]]:
            """Vieillit le lot et rend ce qui doit teinter l'humeur."""
            from django.utils import timezone as tz

            maintenant = tz.now()
            lot = list(Rumination.objects.filter(status="active")[:30])
            if not lot:
                return []

            a_ecrire: list = []
            derives: list = []
            saignees: list[tuple[str, float]] = []

            for r in lot:
                ancre = r.decayed_at or r.created_at
                heures = max(0.0, (maintenant - ancre).total_seconds() / 3600.0)
                nouvelle = r.intensity * (0.5 ** (heures / demi_vie_h))

                # Sous le seuil d'écriture on ne touche à rien : `decayed_at`
                # reste en arrière et le temps écoulé s'accumule au lieu d'être
                # perdu. C'est ce qui rend la décroissance indépendante de la
                # cadence de la boucle qui l'applique.
                if r.intensity - nouvelle > self._RUMINATION_WRITE_DELTA:
                    r.intensity = round(nouvelle, 4)
                    r.decayed_at = maintenant
                    if r.intensity < 0.1:
                        r.status = "faded"
                    a_ecrire.append(r)

                if r.emotion and r.status == "active":
                    age_h = (maintenant - r.created_at).total_seconds() / 3600.0
                    cible = self._RUMINATION_DRIFT.get(r.emotion)
                    if cible and cible != r.emotion and age_h >= derive_h:
                        logger.debug(
                            "Rumination #%s drift: %s -> %s", r.pk, r.emotion, cible,
                        )
                        r.emotion = cible
                        derives.append(r)
                    if r.intensity > 0.3:
                        saignees.append((r.emotion, r.intensity))

            if a_ecrire:
                Rumination.objects.bulk_update(
                    a_ecrire, ["intensity", "status", "decayed_at"], batch_size=50,
                )
            if derives:
                Rumination.objects.bulk_update(derives, ["emotion"], batch_size=50)
            return saignees

        try:
            saignees = await sync_to_async(_passe)()
        except Exception as exc:
            degradations.record("conscience: ruminations to decay", exc)
            return

        self._bleed_ruminations(saignees)

    def _bleed_ruminations(self, saignees: list[tuple[str, float]]) -> None:
        """Laisse les pensées en cours teinter l'humeur globale — par à-coups.

        Une pensée colore l'humeur, elle ne la matraque pas. Tant qu'une
        rumination mourait en 22 minutes, saigner à chaque cycle de 30 s était
        auto-limité ; maintenant qu'elle vit des heures, la même cadence
        clouerait l'humeur globale sur l'émotion de la rumination pour la
        soirée entière. On espace donc à un versement par ``_RUMINATION_BLEED_INTERVAL_S``.
        """
        if not saignees:
            return
        from emotion.types import Emotion, EmotionData

        espacement = cfg_float(
            "conscience.rumination_bleed_interval_seconds",
            self._RUMINATION_BLEED_INTERVAL_S, mini=0.0,
        )
        part = cfg_float(
            "conscience.rumination_bleed_intensity",
            self._RUMINATION_BLEED_INTENSITY, mini=0.0, maxi=1.0,
        )
        maintenant = time.monotonic()
        for etiquette, intensite in saignees:
            dernier = self._rumination_bleed_at.get(etiquette, 0.0)
            if maintenant - dernier < espacement:
                continue
            try:
                emo = Emotion(etiquette)
            except ValueError:
                continue  # étiquette inconnue sur une vieille ligne
            try:
                emotion_engine.process_emotion(
                    EmotionData(emotion=emo, intensity=intensite * part),
                    "conscience_mika",
                )
                self._rumination_bleed_at[etiquette] = maintenant
            except Exception as exc:
                degradations.record("conscience: rumination emotional bleed", exc)


    async def _promote_stale_to_ruminations(self) -> None:
        """Convert recent skipped/stale pertinent observations into ruminations.

        Called from _mark_stale_observations when observations age out.
        An observation with pertinence >= 0.5 that was never acted upon
        becomes a Rumination — Mika keeps thinking about it.
        """
        try:
            from conscience.models import Observation, Rumination
        except ImportError:
            return

        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=self._pending_window_minutes())
        window_start = tz.now() - timedelta(hours=2)

        porte = cfg_float(
            "conscience.promotion.rumination_pertinence", PROMOTION_PERTINENCE,
        )
        actives_max = cfg_int(
            "conscience.promotion.rumination_actives_max", PROMOTION_ACTIVES_MAX,
            mini=1,
        )

        # Garde de volume, dans le **même** callable synchrone que la sélection
        # qui suit : une pensée de plus n'est pas une pensée mieux pensée, et
        # sans plafond l'ouverture de la porte installerait une pression
        # permanente sur le Facteur 10.
        try:
            deja_actives = await sync_to_async(
                lambda: Rumination.objects.filter(status="active").count()
            )()
        except Exception as exc:
            degradations.record("conscience: comptage des ruminations actives", exc)
            return
        if deja_actives >= actives_max:
            return

        try:
            pertinent_stale = await sync_to_async(
                lambda: list(
                    Observation.objects.filter(
                        status="skipped",
                        pertinence__gte=porte,
                        created_at__gte=window_start,
                        created_at__lt=cutoff,
                    ).exclude(
                        id__in=Rumination.objects.filter(
                            observation__isnull=False
                        ).values_list("observation_id", flat=True)
                    )[:5]
                )
            )()
        except Exception as exc:
            degradations.record("conscience: stale observations to promote", exc)
            return

        for obs in pertinent_stale:
            try:
                await sync_to_async(Rumination.objects.create)(
                    summary=obs.summary,
                    themes=obs.raw_data.get("themes", []),
                    intensity=min(1.0, obs.pertinence),
                    emotion=obs.emotional_reaction or "",
                    observation=obs,
                    status="active",
                )
                logger.debug(
                    "Promoted observation %d to rumination (p=%.2f)",
                    obs.id, obs.pertinence,
                )
            except Exception as exc:
                degradations.record("conscience: rumination creation", exc)

    async def _poll_scheduled_actions(self) -> list:
        """Query scheduled actions that are due (scheduled_at <= now)."""
        from conscience.models import ScheduledAction
        from django.utils import timezone as tz

        try:
            return await sync_to_async(
                lambda: list(
                    ScheduledAction.objects.filter(
                        status="pending",
                        scheduled_at__lte=tz.now(),
                    ).order_by("scheduled_at")[:10]
                )
            )()
        except Exception as exc:
            degradations.record("conscience: poll scheduled actions", exc)
            return []

    async def _get_upcoming_actions(self, limit: int = 5) -> list[tuple]:
        """Get future pending actions (not yet due). Returns [(action, minutes_until), ...]."""
        from conscience.models import ScheduledAction
        from django.utils import timezone as tz

        now = tz.now()
        try:
            actions = await sync_to_async(
                lambda: list(
                    ScheduledAction.objects.filter(
                        status="pending",
                        scheduled_at__gt=now,
                    ).order_by("scheduled_at")[:limit]
                )
            )()
            return [(a, int((a.scheduled_at - now).total_seconds() / 60)) for a in actions]
        except Exception as exc:
            degradations.record("conscience: upcoming scheduled actions", exc)
            return []

    def _compute_score(self, ctx: DecisionContext) -> tuple[float, str]:
        """Unified scoring. Delegates to conscience.scoring for testability.

        The greeting state computed here is only *tentative*: scoring marks a
        period as greeted, but the greeting is worth 0.35 against a 0.5
        threshold, so committing it right away would burn the day's greeting
        on a cycle that decided to stay silent. ``_commit_greeting()`` is
        called by the caller once the decision is actually "act".
        """
        score, reason, periods, date = compute_decision_score(
            ctx, self._greeted_periods, self._greeted_date,
            self._scoring_tuning(),
        )
        self._pending_greeted = (periods, date)
        # Quelle salutation vient d'être déclenchée — DÉDUITE, pas transportée.
        #
        # `check_time_trigger` n'ajoute qu'une période par appel, et vide
        # l'ensemble d'abord quand le jour change : la différence avec l'état
        # courant est donc un singleton, ou vide. Le déduire ici évite de faire
        # remonter l'information par le retour de `compute_decision_score` —
        # une sous-classe de `str` portant un attribut, que quatre tests
        # patchent avec une chaîne nue et que toute opération de chaîne
        # perdrait en silence. `scoring.py` reste intouchée, donc pure.
        #
        # Écrit INCONDITIONNELLEMENT : sans le `None` du cas courant, un cycle
        # sans salutation hériterait de celle du précédent et elle dirait
        # bonjour à 15 h.
        nouvelles = periods if date != self._greeted_date else (
            periods - self._greeted_periods
        )
        self._salutation_en_attente = next(iter(nouvelles), None)
        return score, reason

    def _commit_greeting(self) -> None:
        """Persist the tentative greeting state produced by the last scoring."""
        pending = getattr(self, "_pending_greeted", None)
        if pending is not None:
            self._greeted_periods, self._greeted_date = pending
            self._pending_greeted = None

    # ── 3. MEMORY MAINTENANCE ─────────────────────────────────────

    # Marque posee dans raw_data une fois l'observation passee par la
    # maintenance. Observation n'a pas de champ dedie, et raw_data porte
    # deja les themes de l'interpretation (voir _store_observation) : la
    # meme convention evite une migration pour un drapeau interne.
    _MAINTENANCE_FLAG = "maintenance_done"

    async def _memory_maintenance(self, ctx: DecisionContext) -> list[str]:
        """Modify memory based on accumulated observations.

        Runs every decision cycle — the Conscience can reshape memory
        even without speaking.

        Une observation n'est maintenue **qu'une fois**. Elle reste
        `pending` jusqu'a un acte ou sa peremption (30 min), et
        `_build_context` la reselectionne a chaque cycle : sans cette
        marque, un signal pertinent repayait a chaque tour une recherche
        vectorielle plus jusqu'a cinq appels IA de validation — soit une
        soixantaine de fois a l'intervalle par defaut, en serie et
        `_decision_lock` tenu, ce qui court-circuitait aussi bien les
        ticks periodiques que le fast-path haute pertinence. Le boost
        d'importance, lui, se cumulait a chaque passage.
        """
        actions = []

        for obs in ctx.pending_observations:
            if obs.raw_data.get(self._MAINTENANCE_FLAG):
                continue

            # Marquee avant le travail, pas apres : la marque dit "cette
            # observation est passee par la maintenance", pas "la
            # maintenance a reussi". La poser apres laisserait une panne
            # transitoire rejouer exactement la boucle qu'on supprime ici.
            await self._mark_maintained(obs)

            # Boost related souvenirs for pertinent signals
            if obs.pertinence >= cfg_float(
                "conscience.maintenance.boost_pertinence", BOOST_PERTINENCE,
            ):
                themes = obs.raw_data.get("themes", [])
                if themes:
                    count = await self.memory.boost_related_souvenirs(themes, 0.1)
                    if count:
                        actions.append(f"boosted {count} souvenirs (themes: {themes})")

            # Check contradictions for high-pertinence communication signals
            if obs.pertinence >= cfg_float(
                "conscience.maintenance.contradiction_pertinence",
                CONTRADICTION_PERTINENCE,
            ) and obs.category == "communication":
                contradictions = await self.memory.check_contradictions(obs.summary)
                for c in contradictions:
                    if not c["still_valid"]:
                        actions.append(
                            f"invalidated connaissance #{c['connaissance_id']}"
                        )

        return actions

    async def _mark_maintained(self, obs) -> None:
        """Poser durablement la marque de maintenance sur une observation.

        En base, pas en RAM : les observations sont relues a chaque cycle
        et un redemarrage relancerait sinon la meme maintenance. Si
        l'ecriture echoue, la marque n'existe pas et l'observation
        repassera au cycle suivant — degradation comptee, pas de blocage.
        """
        try:
            obs.raw_data[self._MAINTENANCE_FLAG] = True
            await sync_to_async(obs.save)(update_fields=["raw_data"])
        except Exception as exc:
            degradations.record("conscience: mark observation maintained", exc)

    # Meme decalage d'echelle que la purge, en plus court : le seuil est a 30
    # minutes et le seul lecteur du statut "skipped" est la promotion en
    # rumination, qui lit une fenetre de 2h. Une granularite de 5 minutes ne
    # change donc rien d'observable — le scoring, lui, ne voit jamais ces
    # lignes, `_build_context` bornant sa selection aux 30 dernieres minutes.
    _STALE_SWEEP_INTERVAL_S = 300
    _STALE_SWEEP_BATCH = 1000

    async def _mark_stale_observations(self) -> None:
        """Mark pending observations older than 30 min as skipped.

        Pertinent stale observations are promoted to Ruminations — Mika
        keeps thinking about them even after the short-term buffer empties.

        L'UPDATE est etrangle a `_STALE_SWEEP_INTERVAL_S` et borne a
        `_STALE_SWEEP_BATCH` lignes ; la promotion et la decroissance des
        ruminations, elles, restent a chaque cycle (5% par cycle est leur
        definition).
        """
        from conscience.models import Observation
        from django.utils import timezone as tz
        from datetime import timedelta

        now = time.monotonic()
        cadence = cfg_int(
            "conscience.stale_sweep_interval_seconds",
            self._STALE_SWEEP_INTERVAL_S, mini=1,
        )
        if (not self._last_stale_sweep
                or (now - self._last_stale_sweep) >= cadence):
            self._last_stale_sweep = now
            cutoff = tz.now() - timedelta(minutes=self._pending_window_minutes())

            def _perimer() -> int:
                ids = list(
                    Observation.objects.filter(
                        status="pending",
                        created_at__lt=cutoff,
                    ).values_list("pk", flat=True)[:self._STALE_SWEEP_BATCH]
                )
                if not ids:
                    return 0
                return Observation.objects.filter(pk__in=ids).update(
                    status="skipped")

            try:
                count = await sync_to_async(_perimer)()
                if count:
                    logger.debug("Marked %d stale observations as skipped", count)
                if count >= self._STALE_SWEEP_BATCH:
                    self._last_stale_sweep = 0.0
            except Exception as exc:
                degradations.record("conscience: mark stale observations", exc)

        # Promote pertinent skipped observations to ruminations.
        await self._promote_stale_to_ruminations()
        # Decay existing ruminations over each cycle.
        await self._decay_ruminations()

    # Cadence et taille de lot de la purge. La donnee visee a 48h, le cycle de
    # decision tourne toutes les 30s : un passage par heure suffit, sur la
    # forme deja retenue par `_apply_decay` du consolidateur. Le lot borne la
    # transaction d'ecriture — `Rumination.observation` est une FK SET_NULL,
    # donc chaque suppression traine ses UPDATE, et sur SQLite un ecrivain
    # bloque tous les lecteurs le temps de la transaction.
    _CLEANUP_INTERVAL_S = 3600
    _CLEANUP_BATCH = 1000

    async def _cleanup_old_observations(self) -> None:
        """Delete observations older than 48h that are no longer pending.

        Etranglee a `_CLEANUP_INTERVAL_S` et bornee a `_CLEANUP_BATCH` lignes
        par passage. Rien n'est perdu : ce qui deborde du lot reste eligible,
        et un lot plein reprogramme le passage suivant au cycle d'apres plutot
        que dans une heure — sans quoi un pic (premier polling RSS, module
        forge bavard) mettrait des heures a se resorber.
        """
        from conscience.models import Observation
        from django.utils import timezone as tz
        from datetime import timedelta

        now = time.monotonic()
        cadence = cfg_int(
            "conscience.cleanup_interval_seconds", self._CLEANUP_INTERVAL_S, mini=1,
        )
        if self._last_cleanup and (now - self._last_cleanup) < cadence:
            return
        self._last_cleanup = now

        cutoff = tz.now() - timedelta(hours=cfg_int(
            "conscience.observation_retention_hours",
            self._OBSERVATION_RETENTION_H, mini=1,
        ))
        # `status__in` plutot que `exclude(status="pending")` : l'index
        # ["status", "-created_at"] a sa colonne de tete filtree par `!=`
        # dans la seconde forme, donc inexploitable — c'etait un balayage
        # complet de la table a chaque passage. La liste est derivee des
        # choix du modele, pour ne pas oublier un statut ajoute plus tard.
        closed = [s for s in Observation.Status.values
                  if s != Observation.Status.PENDING]

        def _purger() -> int:
            # Suppression par liste de pk (motif de memory/retention.py) :
            # `.delete()` sur un queryset tranche n'est pas portable, et cela
            # garde l'instruction bornee.
            ids = list(
                Observation.objects.filter(
                    status__in=closed,
                    created_at__lt=cutoff,
                ).values_list("pk", flat=True)[:self._CLEANUP_BATCH]
            )
            if not ids:
                return 0
            # .delete() returns (total, {model: count}) tuple
            return Observation.objects.filter(pk__in=ids).delete()[0]

        try:
            count = await sync_to_async(_purger)()
        except Exception as exc:
            degradations.record("conscience: observation cleanup", exc)
            return

        if count:
            logger.info("Cleaned up %d old observations", count)
        if count >= self._CLEANUP_BATCH:
            self._last_cleanup = 0.0

    # ── 4. ACT ────────────────────────────────────────────────────

    def _verdict_tuning(self) -> VerdictTuning:
        """Les deux bornes de délai. Les quatre bornes de recopie ne sont pas
        déclarées : ce sont des gardes d'un lecteur face à une sortie hostile,
        même famille que la taille maximale d'un source forgé."""
        d = VerdictTuning()
        return VerdictTuning(
            delai_defaut_s=cfg_float(
                "conscience.verdict.delai_defaut_s", d.delai_defaut_s),
            delai_max_s=cfg_float(
                "conscience.verdict.delai_max_s", d.delai_max_s),
        )

    async def _build_work_prompt(self, row) -> str:
        """Le prompt d'un pas de chantier.

        Délibérément **distinct** de `_build_action_prompt`, qui répond à une
        autre question : « pourquoi je prends la parole maintenant ». Ici la
        question est « où j'en suis et quel est le pas suivant ». Réutiliser
        l'autre ferait arriver dans un travail silencieux les salutations,
        l'auto-évaluation des relances ignorées et l'injonction à être brève —
        c'est-à-dire tout ce qui n'a de sens que devant quelqu'un.
        """
        parts = [
            f"Tu avances sur quelque chose que tu as décidé de faire : "
            f"« {row.titre} ».",
        ]
        if row.themes:
            parts.append("Thèmes : " + ", ".join(str(t) for t in row.themes[:6]) + ".")
        if row.pas_effectues:
            parts.append(
                f"Tu en es au pas {row.pas_effectues + 1} sur {row.pas_max}."
            )
        if row.resultat:
            # Sa mémoire du chantier. Nettoyée de la prosodie, que le
            # processeur n'applique qu'au texte destiné à une voix : sans ça,
            # les `[SIGH]` d'un pas précédent reviendraient dans le prompt du
            # suivant et finiraient dans les souvenirs.
            from emotion.types import strip_prosody
            parts.append("Ce que tu as déjà fait :\n" + strip_prosody(row.resultat)[-1200:])
        parts.append(
            "Fais UN pas, un seul — le plus utile maintenant. Tu peux te "
            "servir de tes outils. Personne ne te lit : c'est un travail, pas "
            "une conversation."
        )
        parts.append(CONSIGNE_VERDICT)
        return "\n\n".join(parts)

    async def _faire_un_pas(self, identifiant) -> bool:
        """Faire avancer un chantier d'un pas. Rend True si le pas a eu lieu.

        Muet par défaut : un pas ne diffuse ni ne persiste. Quatre travaux à
        cinq pas feraient vingt monologues par jour, et ceux-là passeraient
        **hors** du frein quotidien des initiatives — le compteur qui existe
        précisément pour qu'elle ne devienne pas envahissante.
        """
        from conscience.models import Travail
        from django.utils import timezone as tz

        maintenant = tz.now()

        def _prendre():
            """Marquer le pas AVANT l'appel, et sous condition.

            `filter(dernier_pas_le=…)` fait de la prise un test-and-set : deux
            cycles concurrents ne peuvent pas partir sur le même chantier. Et
            le compteur monte **à la prise**, pas au succès — sinon un pas qui
            tue le process serait rejoué indéfiniment au redémarrage, ce que
            `resume_interrupted_turns` a déjà appris à ses dépens.
            """
            pris = Travail.objects.filter(
                pk=identifiant, statut=Travail.Statut.EN_COURS,
            ).update(
                pas_effectues=F("pas_effectues") + 1,
                dernier_pas_le=maintenant,
            )
            if not pris:
                return None
            return Travail.objects.filter(pk=identifiant).first()

        try:
            row = await sync_to_async(_prendre, thread_sensitive=True)()
        except Exception as exc:
            degradations.record("conscience: prise d'un pas", exc)
            return False
        if row is None:
            return False

        prompt = await self._build_work_prompt(row)
        trousse = self._preparer_trousse_travail(row)

        try:
            output, bilan, reussites = await self._appeler_le_modele(
                prompt,
                person_id="conscience_mika",
                modules=list(trousse.modules),
                metadata={"travail": identifiant, "titre": row.titre},
                broadcast=False,
                persist=False,
            )
        except Exception as exc:
            degradations.record("conscience: pas de travail", exc)
            return False

        if output.ai_failed:
            # Le pas n'a pas eu lieu : on rend son crédit. Sans ça, sur une
            # installation dont le rôle n'est pas mappé — et le dépôt démarre
            # non configuré exprès — cinq `UnconfiguredRoleError` consommeraient
            # les cinq pas, et elle serait frustrée d'un travail jamais tenté.
            await self._rendre_le_pas(identifiant)
            return False

        dit, verdict = depouiller_verdict(output.text, self._verdict_tuning())
        await self._appliquer_verdict(identifiant, verdict, dit, bilan)
        await self._peut_etre_dire_le_travail(verdict, dit, row.titre)
        drive_engine.on_act(had_tools=reussites > 0, word_count=len(dit.split()))
        logger.info(
            "Pas de travail #%s [%s] outils=%s : %s",
            identifiant, verdict.etat.value, bilan or "aucun", dit[:80],
        )
        return True

    def _preparer_trousse_travail(self, row):
        """La trousse d'un pas : le socle, plus ce que LE CHANTIER demande.

        ``row.modules`` — figé à l'ouverture depuis la graine — passe en
        demande explicite, le rang le plus fort après le socle. C'est ce qui
        garantit qu'un chantier garde ses mains toute sa vie : la version
        précédente ne dérivait la trousse que des pulsions *du moment*, or le
        premier pas réussi assouvit la curiosité (``on_act``, −0.5), si bien
        que le pas suivant partait sans les outils qui avaient ouvert le
        chantier. L'élargissement par pulsion reste, en plus, jamais à la
        place.
        """
        return preparer(
            sources=(),
            drives=drive_engine.states,
            demandes=tuple(str(m) for m in (row.modules or ())),
            poids=self._poids_module,
            disponibles=self._modules_enregistres(),
            tuning=self._trousse_tuning(),
        )

    async def _peut_etre_dire_le_travail(self, verdict, dit: str, titre: str) -> None:
        """Un chantier mené au bout mérite-t-il d'être dit ? Par défaut, non.

        Un pas est muet — sans quoi quatre travaux à cinq pas font vingt
        monologues par jour, hors du frein quotidien des initiatives. Mais un
        travail *terminé* et jamais mentionné reste invisible : elle aurait
        passé la journée à faire des choses dont personne n'entend parler.

        `decider_diffusion` porte les deux gardes — notabilité, et un silence
        minimal entre deux annonces — et c'est le seul producteur de son
        entrée : « avoir mené quelque chose au bout » est ce qui vaut la peine
        d'être dit.
        """
        from django.utils import timezone as tz

        if verdict.etat is not EtatVerdict.FINI or not dit:
            return

        maintenant = tz.now()
        decision = decider_diffusion(
            Conduite.POURSUIVRE,
            resultat_notable=1.0,
            derniere_diffusion_le=self._derniere_diffusion_travail,
            maintenant=maintenant,
            tuning=self._conduite_tuning(),
        )
        if not decision.diffuser:
            logger.debug("Travail fini, non diffusé : %s", decision.motif)
            return

        self._derniere_diffusion_travail = maintenant
        with degraded("conscience: diffusion d'un travail fini"):
            from emotion.types import Emotion, EmotionData
            from pipeline.broadcast import broadcast_to_websocket
            from pipeline.processor import SpeechOutput

            await broadcast_to_websocket(
                SpeechOutput(
                    text=dit,
                    emotion_data=EmotionData(Emotion.PROUD, 0.4),
                    emotion_name="proud",
                    emotion_intensity=0.4,
                    emotion_state={},
                    tool_calls=[],
                ),
                source="conscience",
            )

    async def _rendre_le_pas(self, identifiant) -> None:
        """Rendre le crédit d'un pas qui n'a pas eu lieu."""
        from conscience.models import Travail

        with degraded("conscience: restitution d'un pas"):
            await sync_to_async(
                lambda: Travail.objects.filter(pk=identifiant).update(
                    pas_effectues=F("pas_effectues") - 1,
                ),
                thread_sensitive=True,
            )()

    async def _appliquer_verdict(self, identifiant, verdict, dit, bilan) -> None:
        """Écrire ce que le pas a produit — **un seul callable synchrone**.

        Lire, décider en RAM puis réécrire laisserait un autre écrivain
        s'intercaler : `sync_to_async(thread_sensitive=True)` sérialise tout
        sur un thread unique, et c'est le piège documenté sur
        `_decay_ruminations`, où la digestion nocturne se faisait écraser.

        Un verdict illisible n'est pas une erreur, c'est un état : il se
        compte, et au bout de quelques-uns le chantier se bloque plutôt que de
        tourner indéfiniment sans jamais savoir où il en est.

        Un chantier qui ABOUTIT laisse un souvenir — hors du callable
        synchrone, parce que la création passe par le vector store. Sans lui,
        elle passait ses journées à mener des choses au bout dont il ne
        restait rien : ni dans le rappel, ni dans le récit de soi, ni dans ce
        qu'elle peut répondre à « tu as fait quoi aujourd'hui ? ».
        """
        from conscience.models import Rumination, Travail
        from django.utils import timezone as tz

        t = self._conduite_tuning()
        maintenant = tz.now()

        def _ecrire() -> dict | None:
            row = Travail.objects.filter(pk=identifiant).first()
            if row is None:
                return None

            journal = (row.resultat + "\n\n" + dit).strip() if dit else row.resultat
            row.resultat = journal[-6000:]

            if verdict.etat is EtatVerdict.FINI:
                row.statut = Travail.Statut.ABOUTIE
            elif verdict.etat is EtatVerdict.BLOQUE:
                row.statut = Travail.Statut.BLOQUEE
                row.raison_blocage = verdict.motif_blocage[:500]
            elif verdict.etat is EtatVerdict.ATTENDRE:
                # Le drapeau et son échéance sont les deux moitiés d'un même
                # geste (le motif de l'envie et son ancre) : le drapeau seul
                # était un cul-de-sac — posé ici, relevé par personne,
                # « attendre » signifiait « se faner jusqu'à l'abandon » et
                # `delai_s`, soigneusement borné par le lecteur, n'avait
                # aucun consommateur. `is not None` et non `or` : 0 s est un
                # délai légal (« tout de suite »), pas une absence.
                from datetime import timedelta
                delai = (
                    verdict.delai_s if verdict.delai_s is not None else 300.0
                )
                row.en_attente_de_reponse = True
                row.reprendre_le = maintenant + timedelta(seconds=delai)
            elif verdict.etat is EtatVerdict.ILLISIBLE:
                # Compté sur le journal plutôt que dans un champ : le lot ne
                # gagne pas une colonne pour un compteur qu'un seul endroit
                # lit. Trois passes sans verdict lisible et le chantier se
                # bloque — un travail qui ne sait jamais dire où il en est ne
                # peut pas se terminer.
                if row.resultat.count("[verdict illisible]") >= 2:
                    row.statut = Travail.Statut.BLOQUEE
                    row.raison_blocage = "aucun verdict lisible après trois pas"
                else:
                    row.resultat = (row.resultat + "\n[verdict illisible]")[-6000:]

            if row.statut == Travail.Statut.EN_COURS and row.pas_effectues >= row.pas_max:
                row.statut = Travail.Statut.BLOQUEE
                row.raison_blocage = "nombre de pas épuisé"

            # Envie et ancre dans le MÊME `update_fields` : écrire la valeur
            # sans avancer l'ancre re-facturerait le même temps au tour
            # suivant, l'ancre sans la valeur effacerait la décroissance. Les
            # deux moitiés du même geste ne doivent pas pouvoir se séparer —
            # c'est ce qui est arrivé à `Connaissance`, ancrée sur un
            # `auto_now` que Django ne rafraîchit pas sous `update_fields`.
            vue = TravailEnCours(
                identifiant=row.pk, titre=row.titre, envie=row.envie,
                ancre_envie=row.ancre,
            )
            row.envie, row.ancre_envie = facturer_envie(vue, maintenant, t)
            row.save(update_fields=[
                "resultat", "statut", "raison_blocage", "en_attente_de_reponse",
                "reprendre_le", "envie", "ancre_envie", "updated_at",
            ])

            # Un chantier né d'une pensée et mené au bout résout la pensée.
            # C'est la boucle du regret refermée par l'autre côté : elle
            # n'oublie pas parce que le temps passe, elle oublie parce qu'elle
            # a fait la chose.
            if (
                row.statut == Travail.Statut.ABOUTIE
                and row.origine == Travail.Origine.PENSEE
                and str(row.reference).isdigit()
            ):
                Rumination.objects.filter(
                    pk=int(row.reference), status="active",
                ).update(status="resolved")

            if row.statut == Travail.Statut.ABOUTIE:
                return {"titre": row.titre}
            return None

        aboutie = None
        with degraded("conscience: application d'un verdict"):
            aboutie = await sync_to_async(_ecrire, thread_sensitive=True)()

        if aboutie:
            # `verdict.resume` d'abord : c'est la phrase que le bloc demande
            # (« ce que tu viens de faire »). `dit` en repli, borné — le pas
            # entier n'est pas un souvenir, c'est un journal. `getattr` comme
            # `_pending_greeted` : les tests construisent le moteur par
            # `__new__`, donc sans pont mémoire.
            essence = (verdict.resume or dit or "").strip()[:300]
            bridge = getattr(self, "memory", None)
            if bridge is not None:
                with degraded("conscience: souvenir d'un travail abouti"):
                    await bridge.remember_completed_work(
                        aboutie["titre"], essence,
                    )

    #: Plafond de l'inactivité restaurée au démarrage. Au-delà, la mesure ne
    #: dit plus rien d'utile : trois jours ou trois mois de silence produisent
    #: le même facteur, déjà à son plafond.
    _INACTIVITE_RESTAUREE_MAX_S = 72 * 3600

    async def _restaurer_inactivite(self) -> None:
        """Retrouver depuis quand personne ne lui a parlé, après un redémarrage.

        `_last_activity` repartait de `time.time()` à la construction : au boot,
        elle croyait qu'on venait de lui parler. Or les pulsions, elles,
        **rejouent le temps écoulé** depuis leur instantané — si bien que SOCIAL
        se souvenait de trois jours d'absence pendant que le Facteur 4 lisait
        zéro. Deux mesures du même silence qui se contredisaient pendant toute
        l'heure suivant chaque démarrage, et rien ne le signalait.

        On lit le dernier message d'une **vraie personne** : ni ses propres
        répliques, ni la tuyauterie interne. `ConscienceLog` serait le pire
        choix possible — il date ses propres monologues, donc elle conclurait
        que le silence vient d'être rompu par elle-même.
        """
        from identity.trust import is_internal_person
        from memory.models import Message

        def _dernier() -> float | None:
            for msg in (
                Message.objects
                .filter(role="user")
                .exclude(is_internal=True)
                .order_by("-id")[:20]
            ):
                if not is_internal_person(msg.person_id):
                    return msg.created_at.timestamp()
            return None

        with degraded("conscience: restauration de l'inactivite"):
            horodatage = await sync_to_async(_dernier, thread_sensitive=True)()
            if horodatage is None:
                return
            plafond = cfg_int(
                "conscience.inactivite_restauree_max_seconds",
                self._INACTIVITE_RESTAUREE_MAX_S, mini=0,
            )
            self._last_activity = max(horodatage, time.time() - plafond)
            logger.info(
                "Inactivité restaurée : %d s depuis le dernier message",
                int(self.get_idle_seconds()),
            )

    async def _reprendre_travaux(self) -> None:
        """Au démarrage, refermer les pas que l'arrêt a coupés en vol.

        Un pas est marqué **à la prise**, donc un process tué au milieu laisse
        un chantier dont le compteur a monté sans qu'aucun verdict ne soit
        écrit. On ne le rejoue pas : on le laisse simplement redevenir
        éligible. Rendre le crédit ici rouvrirait la boucle de plantage que
        `resume_interrupted_turns` a appris à éviter — un pas qui tue le
        process deux fois doit finir par coûter ses pas, pas les regagner.
        """
        from conscience.models import Travail

        def _passe() -> int:
            return Travail.objects.filter(
                statut=Travail.Statut.EN_COURS,
                pas_effectues__gte=F("pas_max"),
            ).update(
                statut=Travail.Statut.BLOQUEE,
                raison_blocage="pas épuisés — interrompu au redémarrage",
            )

        with degraded("conscience: reprise des travaux"):
            n = await sync_to_async(_passe, thread_sensitive=True)()
            if n:
                logger.info("Reprise: %d chantier(s) clos au redémarrage", n)

    async def _appeler_le_modele(
        self,
        prompt: str,
        *,
        person_id: str,
        modules: list[str],
        memory_context: str = "",
        metadata: dict | None = None,
        broadcast: bool = True,
        persist: bool = True,
    ):
        """Un tour de modèle, avec sa trousse et son carnet d'outils.

        Extrait de `_act` sans changer un octet de son comportement : deux
        chemins en ont désormais besoin — la parole et le pas de travail — et
        les laisser diverger ferait deux façons de monter un contexte, dont
        une seule recevrait les correctifs. C'est exactement ce qui était
        arrivé à la recopie champ à champ du contexte, où `identity_context`
        et `journal_context` manquaient à l'appel.

        Rend `(output, bilan_outils, outils_reussis)`.
        """
        import dataclasses as _dc

        from modules.manager import module_manager
        from pipeline.context import gather_context
        from pipeline.perception import Perception
        from pipeline.processor import process_message

        # La memoire n'est demandee ici que si le rappel sur les observations
        # n'a rien donne : sinon `memory_context` ecrase le champ juste en
        # dessous, et l'embedding + la requete ChromaDB seraient payes pour rien.
        base_context = await gather_context(
            prompt, person_id,
            include_tools=False,
            include_memory=not memory_context,
        )

        tools = module_manager.get_tools_for_modules(modules) if modules else []
        tool_names = [t.name for t in tools]

        # ``replace`` plutôt qu'une recopie champ à champ : la transcription
        # manuelle avait déjà dérivé — ``identity_context`` et
        # ``journal_context`` manquaient à l'appel, si bien qu'un tour spontané
        # adressé à une vraie personne partait sans le bloc « QUI TU AS EN
        # FACE » alors que ``person_context`` (que ce bloc qualifie) passait,
        # lui. Un champ ajouté demain suit tout seul.
        context = _dc.replace(
            base_context,
            memory_context=memory_context or base_context.memory_context,
            tools=tools,
            tool_names=tool_names,
        )

        perception = Perception.from_internal_trigger(
            prompt,
            source="conscience",
            person_id=person_id,
            metadata=metadata or {},
        )

        # Le carnet couvre l'appel entier, boucle d'outils comprise :
        # `output.tool_calls` ne rend que des NOMS, jamais une issue.
        with journal_outils() as carnet:
            output = await process_message(
                perception,
                context=context,
                emit_event=False,
                broadcast=broadcast,
                persist=persist,
            )
            return output, carnet.resume(), carnet.reussites

    async def _act(self, ctx: DecisionContext, reason: str) -> ActeResultat:
        """Generate a spontaneous response using accumulated context.

        Builds an INTERNAL_TRIGGER Perception and hands it to the pipeline
        processor directly (context is pre-assembled with relevant-module
        tools, so we bypass the router's dispatch logic here — the intent
        is already "Mika acts, no event to loop back").

        Returns True only if something was actually said: the caller commits
        the day's greeting and the decision log from that answer."""
        from conscience.models import Observation, ScheduledAction
        from modules.manager import module_manager
        from pipeline.context import gather_context
        from pipeline.perception import Perception
        from pipeline.processor import process_message

        self._last_action_time = time.time()

        # Recall relevant memories
        queries = [o.summary for o in ctx.pending_observations if o.pertinence > 0.3]
        memory_context = await self.memory.recall_for_context(queries)

        # Determine which modules are relevant based on observation sources
        trousse = self._preparer_trousse(ctx)
        relevant_modules = list(trousse.modules)

        # Deux blocs, et non plus un catalogue unique. `collect_capabilities_summary()`
        # énumérait tout ce qui tourne pendant que la trousse était vide : le
        # modèle, à qui on annonce des capacités qu'on ne lui donne pas,
        # *raconte* l'action au lieu de la faire — et le journal comme les
        # souvenirs se remplissent de choses qu'elle croit avoir faites.
        brief = await self._build_action_prompt(
            ctx,
            vecu=self._composer_vecu(ctx),
            en_main=trousse.bloc_en_main(),
            a_demander=resume_capacites(
                trousse,
                module_manager.collect_capabilities(),
                disponibles=self._modules_enregistres(),
            ),
        )
        prompt = brief.texte

        # Decide WHOM to address (pass 1). If a concerned, reachable person is
        # chosen, the response is composed with THEIR context and delivered to
        # them; otherwise it stays Mika's internal/broadcast voice.
        target = await self._select_recipient(ctx)
        person_id = target or "conscience_mika"

        try:
            output, bilan_outils, outils_reussis = await self._appeler_le_modele(
                prompt,
                person_id=person_id,
                modules=relevant_modules,
                memory_context=memory_context,
                metadata={"reason": reason, "relevant_modules": relevant_modules},
            )

            if output.ai_failed:
                # The AI call failed (unconfigured role, quota, timeout...):
                # nothing was actually said. Leave observations pending and
                # scheduled actions unexecuted so they retry after cooldown,
                # and don't satisfy drives with a phantom act.
                logger.warning(
                    "Conscience act aborted [%s]: AI call failed — will retry "
                    "after cooldown", reason,
                )
                return ActeResultat(
                    person_id=person_id, trousse=tuple(relevant_modules),
                    ai_failed=True,
                )

            # On ne clôt QUE ce qui a été mis sous les yeux du modèle.
            #
            # Le prompt en montrait cinq et l'acte en clôturait vingt : le
            # surplus était estampillé « traité » par une réponse qui ne le
            # mentionnait même pas, et devenait du même coup inéligible à la
            # promotion en pensée, qui ne relit que les observations
            # « écartées ». Le reste demeure en attente : il vieillira, sera
            # écarté, et pourra alors devenir une rumination — ce qui est
            # exactement ce qu'on veut d'un signal pertinent qu'elle n'a pas
            # traité.
            if brief.observations:
                montrees = list(brief.observations)
                for obs in montrees:
                    obs.status = "acted"
                    obs.action_response = output.text[:200]
                await sync_to_async(Observation.objects.bulk_update)(
                    montrees, ["status", "action_response"], batch_size=50,
                )

            # Même règle pour les rendez-vous qu'elle s'était donnés. Dix
            # étaient marqués « exécutés » au seul motif que l'appel n'avait pas
            # planté, alors que trois seulement figuraient dans le prompt : sept
            # intentions disparaissaient à chaque acte, et le journal annonçait
            # « Executed 10 scheduled action(s) ».
            if brief.actions:
                from django.utils import timezone as tz
                now_tz = tz.now()
                montrees_actions = list(brief.actions)
                for action in montrees_actions:
                    action.status = ScheduledAction.Status.EXECUTED
                    action.executed_at = now_tz
                    action.tentatives = (action.tentatives or 0) + 1
                    action.resultat = output.text[:500]
                await sync_to_async(ScheduledAction.objects.bulk_update)(
                    montrees_actions,
                    ["status", "executed_at", "tentatives", "resultat"],
                    batch_size=50,
                )
                logger.info(
                    "Exécuté %d action(s) programmée(s) sur %d dues",
                    len(montrees_actions), len(ctx.scheduled_actions),
                )

            if bilan_outils:
                logger.info("Conscience tool calls: %s", bilan_outils)

            # `had_tools` se lit désormais sur les RÉUSSITES et non sur le fait
            # qu'un nom d'outil soit passé : `output.tool_calls` est une liste
            # de chaînes que la boucle remplit avant même de savoir ce que le
            # handler a rendu. Trois outils qui plantent assouvissaient donc la
            # curiosité exactement comme trois qui aboutissent — la pulsion la
            # plus difficile à satisfaire du moteur était la plus facile à
            # tromper.
            drive_engine.on_act(
                had_tools=outils_reussis > 0,
                word_count=len(output.text.split()),
            )

            # Speaking at all fades every active rumination by half.
            await self._resolve_ruminations_after_act()

            logger.info(
                "Conscience acted [%s] (modules=%s, outils=%s): %s",
                reason, relevant_modules, bilan_outils or "aucun",
                output.text[:80],
            )
            return ActeResultat(
                dit=output.text,
                person_id=person_id,
                outils=bilan_outils,
                outils_reussis=outils_reussis,
                trousse=tuple(relevant_modules),
            )

        except Exception:
            logger.exception("Conscience act failed")
            # Là encore, seulement ce qui a été montré : une observation que le
            # modèle n'a jamais vue n'a pas « échoué », elle n'a pas été tentée.
            montrees = list(brief.observations)
            if montrees:
                for obs in montrees:
                    obs.status = "failed"
                try:
                    await sync_to_async(Observation.objects.bulk_update)(
                        montrees, ["status"], batch_size=50,
                    )
                except Exception:
                    logger.warning(
                        "Could not mark %d observation(s) as failed",
                        len(montrees), exc_info=True,
                    )
            # Les rendez-vous montrés comptent une tentative, sans être clos :
            # un échec de notre côté ne doit pas leur coûter leur existence,
            # mais une action qui échoue indéfiniment doit finir par céder.
            if brief.actions:
                with degraded("conscience: tentative d'action programmee"):
                    await self._compter_tentative(list(brief.actions))
            return ActeResultat(person_id=person_id, ai_failed=True)

    async def _compter_tentative(self, actions: list) -> None:
        """Une tentative de plus, et l'abandon au-delà du plafond."""
        from conscience.models import ScheduledAction

        plafond = cfg_int(
            "conscience.scheduled.tentatives_max", _SCHEDULED_TENTATIVES_MAX,
            mini=1,
        )

        def _ecrire() -> None:
            for action in actions:
                action.tentatives = (action.tentatives or 0) + 1
                if action.tentatives >= plafond:
                    action.status = ScheduledAction.Status.FAILED
                    action.raison_echec = (
                        f"abandonnée après {action.tentatives} tentatives"
                    )
            ScheduledAction.objects.bulk_update(
                actions, ["tentatives", "status", "raison_echec"], batch_size=50,
            )

        await sync_to_async(_ecrire, thread_sensitive=True)()

    # Budget de la passe 1, alignee sur les 15 s de l'interpreteur : meme role
    # (SIGNAL_INTERPRETATION), meme travail — classer un signal court — et le
    # meme cadre, une boucle sans superviseur. La borne routee
    # (`ai.call_timeout_seconds`, 120 s) est celle d'un tour de conversation :
    # la depenser ici immobilise `_decision_lock` pour quatre cycles avant
    # meme que `_act` n'ait commence a composer sa reponse. Ne rien dire a
    # personne est un resultat valide, donc l'expiration se replie sur le
    # broadcast interne plutot que d'annuler l'acte.
    _RECIPIENT_TIMEOUT_S = 15

    async def _select_recipient(self, ctx: DecisionContext) -> str | None:
        """Pass 1 of proactive speech: pick whom to address, or no one.

        Routing is memory-grounded (``who_is_concerned``) then confirmed by Mika
        via a ``[TO:person_id]`` tag. The candidate prompt is privacy-safe — only
        names + channels, never another person's private memory content.
        Returns a reachable ``person_id`` or None (keep it internal/broadcast).

        Le signal se lit sur les observations, PUIS sur les ruminations : les
        cinq déclencheurs endogènes — inactivité, salutation, humeur, pulsion,
        rumination — ne créent aucune Observation, si bien que la sélection
        rendait ``None`` avant même de chercher. C'était le miroir exact du
        défaut B1 de la trousse : au moment précis où SOCIAL déborde (« envie
        de parler à quelqu'un »), elle était structurellement incapable de
        choisir un quelqu'un.

        Et quand la mémoire ne désigne personne, les personnes **présentes**
        restent des candidates : saluer celui qui est là plutôt que parler
        dans le vide est ce qu'une personne fait. Le dernier mot reste au
        modèle (``[TO:none]`` est une réponse valide), et le backoff des
        relances ignorées borne déjà la fréquence.
        """
        from conscience.recipients import parse_to_tag

        signal = " ".join(
            o.summary for o in ctx.pending_observations if o.pertinence > 0.3
        ).strip()
        if not signal:
            lignes = getattr(ctx, "rumination_lignes", None) or []
            signal = " ".join(
                str(ligne.get("summary", ""))[:160]
                for ligne in lignes[:3]
                if ligne.get("summary")
            ).strip()

        candidates = (
            await self.memory.who_is_concerned(signal, n=5) if signal else []
        )
        if not candidates:
            candidates = self._candidats_presents()
        if not candidates:
            return None

        lines: list[str] = []
        allowed: list[str] = []
        for c in candidates[:5]:
            handles = c.get("handles") or []
            if not handles:
                continue
            pid = handles[0]["person_id"]
            channel = handles[0]["channel"]
            allowed.append(pid)
            lines.append(f"  [{pid}] {c['name']} ({channel})")

        if not allowed:
            return None

        prompt = (
            "Un evenement te concerne. Voici les personnes joignables qu'il "
            "pourrait interesser :\n"
            + "\n".join(lines)
            + "\n\nVeux-tu en parler a quelqu'un ? Reponds UNIQUEMENT par "
            "[TO:person_id] avec un id de la liste, ou [TO:none] si tu preferes "
            "ne rien dire a personne pour l'instant."
        )

        budget = cfg_int(
            "conscience.recipient_timeout_seconds", self._RECIPIENT_TIMEOUT_S, mini=1,
        )
        try:
            from ai.client import ai_client
            from ai.router import AIRole

            raw = await asyncio.wait_for(
                ai_client.complete(
                    system_prompt="Tu choisis a qui t'adresser. Reponds uniquement avec un tag [TO:...].",
                    user_prompt=prompt,
                    role=AIRole.SIGNAL_INTERPRETATION,
                ),
                timeout=budget,
            )
        except asyncio.TimeoutError as exc:
            degradations.record("conscience: choix du destinataire expire", exc)
            logger.warning(
                "Recipient selection timed out after %ds; staying internal",
                budget,
            )
            return None
        except Exception as exc:
            degradations.record("conscience: choix du destinataire", exc)
            logger.exception("Recipient selection failed; staying internal")
            return None

        target = parse_to_tag(raw, allowed)
        logger.info(
            "Conscience recipient selection: target=%s (candidates=%s)",
            target, allowed,
        )
        return target

    #: Personnes présentes proposées au choix du destinataire. Petit : c'est
    #: une salutation possible, pas un annuaire.
    _PRESENTS_MAX = 5

    def _candidats_presents(self) -> list[dict]:
        """Les personnes identifiables joignables MAINTENANT, forme candidate.

        Même contrat de retour que ``who_is_concerned`` (nom + handles), pour
        que la passe de confirmation n'ait pas deux formes à lire. Uniquement
        les personnes identifiables : un socket ``anon_*`` reste couvert par
        le broadcast global, et la tuyauterie interne n'est pas quelqu'un.

        Ne lève jamais — chemin d'un acte, boucle sans superviseur.
        """
        from communication.presence import presence_registry
        from identity.trust import is_identifiable_person

        candidats: list[dict] = []
        vus: set[str] = set()
        try:
            for inter in presence_registry.reachable():
                pid = inter.person_id
                if pid in vus or not is_identifiable_person(pid):
                    continue
                vus.add(pid)
                candidats.append({
                    "name": inter.display_name or pid,
                    "score": 0.0,
                    "handles": [{
                        "person_id": pid,
                        "channel": inter.channel,
                        "kind": inter.kind,
                    }],
                })
                if len(candidats) >= self._PRESENTS_MAX:
                    break
        except Exception as exc:
            degradations.record("conscience: candidats presents", exc)
            return []
        return candidats

    def _modules_enregistres(self) -> list[str]:
        """Qui EXISTE, et non qui tourne.

        La distinction est le correctif B2 : `tools_for` jetait sans un mot un
        nom qu'aucun module ne porte — et `Observation.source` vaut
        « frontend » ou « telegram », qui ne sont des modules ni l'un ni
        l'autre. En passant la liste des enregistrés, un nom non servi devient
        visible (`Trousse.inconnus`) au lieu de disparaître.

        Lu en mémoire (`registry.all_registered()`) et non via `list_all()`,
        qui interroge `ModuleState` en base : ceci s'exécute à chaque acte.
        """
        from modules.manager import module_manager

        try:
            return [m.name for m in module_manager.registry.all_registered()]
        except Exception as exc:
            # Sans cette liste, `preparer` accepte tout et le correctif B2
            # s'éteint à moitié — mieux vaut la trousse dégradée que pas
            # d'acte du tout, mais ça se compte.
            degradations.record("conscience: inventaire des modules", exc)
            return []

    def _trousse_tuning(self) -> TrousseTuning:
        """Le réglage de la trousse, résolu **ici** — `trousse.py` reste pur."""
        d = TrousseTuning()
        return TrousseTuning(
            plafond_caracteres=cfg_int(
                "conscience.trousse.plafond_caracteres", d.plafond_caracteres,
                mini=0,
            ),
            porte_pulsion=cfg_float(
                "conscience.trousse.porte_pulsion", d.porte_pulsion,
            ),
        )

    def _poids_module(self, nom: str) -> int:
        """Le poids en caractères de déclaration d'un module."""
        from modules.manager import module_manager

        try:
            return tools_prompt_chars(module_manager.get_tools_for_modules([nom]))
        except Exception as exc:
            degradations.record("conscience: poids d'un module", exc)
            # Compté comme cher plutôt que gratuit : un poids inconnu qui
            # vaudrait 0 ferait entrer n'importe quoi sous le plafond.
            return DEFAULT_TROUSSE_TUNING.plafond_caracteres

    def _preparer_trousse(self, ctx: DecisionContext):
        """Quels outils accompagnent CET acte.

        Remplace `_pick_relevant_modules`, qui dérivait la trousse des seules
        `obs.source` : les déclencheurs qui font la vie du personnage —
        inactivité, salutation, débordement d'humeur, pulsions, ruminations —
        ne créent aucune Observation, si bien que le seul cas où elle agissait
        d'elle-même était aussi le seul où elle n'avait aucune main.

        Les actions programmées dues passent leurs ``modules`` en demandes
        explicites — le rang que ``souhaits`` réserve à « une intention déjà
        formée ». Ce paramètre existait depuis le premier jour de la trousse
        et n'avait AUCUN appelant : « vérifie tes emails demain matin »
        partait sans l'outil email, le prompt lui interdisait de raconter, et
        le rendez-vous était marqué honoré quand même.
        """
        from modules.manager import module_manager

        demandes = [
            str(nom)
            for action in ctx.scheduled_actions
            for nom in (getattr(action, "modules", None) or ())
        ]
        trousse = preparer(
            sources=[obs.source for obs in ctx.pending_observations],
            drives=drive_engine.states,
            demandes=demandes,
            poids=self._poids_module,
            disponibles=self._modules_enregistres(),
            tuning=self._trousse_tuning(),
        )
        if trousse.inconnus:
            logger.warning(
                "Trousse: %d nom(s) sans module servant: %s",
                len(trousse.inconnus), list(trousse.inconnus),
            )
        return trousse

    async def _build_action_prompt(
        self,
        ctx: DecisionContext,
        *,
        en_main: str = "",
        a_demander: str = "",
        vecu: str = "",
    ) -> ActionBrief:
        """Construire le prompt de ce qui est propre a CETTE decision.

        Volontairement muet sur l'humeur, les pulsions, les ruminations et le
        contexte memoire : le `ConversationContext` monte par `_act()` porte
        deja les quatre dans le prompt systeme
        (`--- TON ETAT EMOTIONNEL ACTUEL ---` contient l'humeur globale suivie
        de `drive_engine.get_context()`, `--- CE QUI TE TROTTE DANS LA TETE ---`
        les memes trois ruminations, et la memoire est ajoutee brute en fin de
        prompt). Les redire ici envoyait plusieurs centaines de tokens en
        double a chaque acte — le chemin le plus cher du moteur, repaye a
        chaque tour de la boucle d'outils.

        Ce qui reste est ce que rien d'autre ne sait : les actions programmees
        dues, les observations, la raison du declenchement, l'auto-evaluation
        et les actions futures.

        `en_main` et `a_demander` remplacent l'ancien `capabilities_summary`,
        et la separation est le correctif : un seul bloc enumerait TOUT ce qui
        tourne sous « ce que tu peux faire », pendant que la trousse etait le
        plus souvent vide. Un modele a qui on annonce des capacites qu'on ne
        lui donne pas raconte l'action au lieu de la faire — et le journal, les
        souvenirs et la fiche de la personne se remplissent de choses qu'elle
        croit avoir faites. Ce qui est en main est appelable ; ce qui est
        ailleurs se dit a voix haute, faute d'outil pour l'ouvrir.
        """
        import json as _json

        parts = []

        # Les deux bornes sont retenues, pas seulement appliquées : l'acte ne
        # doit clore que ce qui a été mis sous les yeux du modèle.
        actions_max = cfg_int(
            "conscience.brief.actions_max", _BRIEF_ACTIONS_MAX, mini=0)
        observations_max = cfg_int(
            "conscience.brief.observations_max", _BRIEF_OBSERVATIONS_MAX, mini=0)
        actions_montrees = tuple(ctx.scheduled_actions[:actions_max])
        observations_montrees = tuple(ctx.pending_observations[:observations_max])

        # Scheduled actions due (highest priority — these are self-assigned tasks)
        if actions_montrees:
            action_lines = []
            for act in actions_montrees:
                action_lines.append(f"- {act.prompt[:200]}")
                if act.context_data:
                    action_lines.append(
                        f"  Contexte: {_json.dumps(act.context_data, ensure_ascii=False)[:200]}"
                    )
            parts.append(
                "Actions que tu avais programmees et qui sont maintenant dues:\n"
                + "\n".join(action_lines)
                + "\nExecute ces actions dans ta reponse."
            )

        # What you've observed
        if observations_montrees:
            obs_lines = []
            for obs in observations_montrees:
                obs_lines.append(f"- [{obs.source}] {obs.summary} (pertinence: {obs.pertinence:.1f})")
            parts.append(
                "Ce que tu as observe recemment:\n" + "\n".join(obs_lines)
            )

        # Idle time
        idle_minutes = int(ctx.idle_seconds / 60)
        if idle_minutes > 2:
            parts.append(f"Personne ne t'a parle depuis {idle_minutes} minutes.")

        # Ce qui la pousse à parler, TOUS les motifs à la fois.
        #
        # Remplace quatre `elif` sur des sous-chaînes de `reason` : la chaîne
        # n'en gardait qu'un, alors qu'un cycle cumule couramment salutation et
        # débordement d'humeur ; et l'inactivité comme les pulsions faisaient
        # monter le score sans qu'aucune phrase ne les nomme. La lecture de
        # `reason` disparaît d'ici — c'est une chaîne de diagnostic, pas une
        # source de vérité sur l'état.
        if vecu:
            parts.append(vecu)

        # Self-awareness
        if ctx.acts_today > 0:
            parts.append(f"Tu as deja pris la parole {ctx.acts_today} fois aujourd'hui.")
        if ctx.consecutive_ignored_acts >= 2:
            parts.append(
                f"Tes {ctx.consecutive_ignored_acts} dernieres interventions "
                "n'ont recu aucune reponse. Sois plus discrete ou change d'approche."
            )

        # Ce qui est réellement appelable maintenant…
        if en_main:
            parts.append(en_main)
        # …et ce qui existe ailleurs, qu'elle ne peut que mentionner.
        if a_demander:
            parts.append(a_demander)

        # Upcoming scheduled actions (so Claude knows what's already planned)
        upcoming = await self._get_upcoming_actions()
        if upcoming:
            upcoming_lines = [f"- Dans {mins}min: {a.prompt[:80]}" for a, mins in upcoming]
            parts.append(
                "Tu as deja programme ces actions futures:\n"
                + "\n".join(upcoming_lines)
            )

        # Instructions
        parts.append(
            "\nExprime-toi naturellement et spontanement, "
            "en accord avec ce que tu observes et ressens. "
            "Sois breve (1-3 phrases max). "
            "Tu peux utiliser tes outils si la situation le demande."
        )

        return ActionBrief(
            texte="\n\n".join(parts),
            observations=observations_montrees,
            actions=actions_montrees,
        )

    # ── Decision Logging ──────────────────────────────────────────

    def _cooldown_restant(self, ctx: DecisionContext) -> int | None:
        """Secondes de silence qu'il lui reste à tenir, ou None hors cooldown.

        Le motif disait « cooldown » sans jamais dire *combien de temps* — et
        comme le délai se multiplie par 2,5 à chaque relance ignorée jusqu'à
        six heures, c'est précisément le nombre qu'on vient chercher quand on
        se demande pourquoi elle s'est tue.
        """
        if not ctx.in_cooldown or not self._last_action_time:
            return None
        reste = self._effective_cooldown(ctx.consecutive_ignored_acts) - (
            time.time() - self._last_action_time
        )
        return max(0, int(reste))

    async def _log_decision(
        self,
        ctx: DecisionContext,
        decision: str,
        reason: str,
        score: float,
        memory_actions: list[str],
        conduite: str = "",
        resultat: ActeResultat | None = None,
    ) -> None:
        from conscience.models import ConscienceLog

        r = resultat or ActeResultat()
        try:
            await sync_to_async(ConscienceLog.objects.create)(
                observations_count=len(ctx.pending_observations),
                max_pertinence=ctx.max_pertinence,
                global_mood=ctx.global_mood,
                global_intensity=ctx.global_intensity,
                idle_seconds=int(ctx.idle_seconds),
                decision=decision,
                # Le score n'est plus interpolé dans le motif : il a sa
                # colonne. `reason` redevient ce qu'il prétend être — une
                # phrase de diagnostic — au lieu de transporter en douce le
                # seul nombre que la moitié des lecteurs cherchaient.
                reason=reason[:200],
                memory_actions=memory_actions,
                trousse=list(r.trousse),
                conduite=conduite,
                score=score,
                cooldown_restant_s=self._cooldown_restant(ctx),
                acts_today=ctx.acts_today,
                consecutive_ignored=ctx.consecutive_ignored_acts,
                energie=ctx.energy,
                sleep_phase=ctx.sleep_phase,
                person_id=r.person_id,
                texte=r.dit[:2000],
                outils=r.outils[:300],
            )
        except Exception as exc:
            degradations.record("conscience: log decision", exc)

        if decision != "skip":
            logger.info(
                "Conscience decision: %s (score=%.2f, reason=%s, obs=%d, memory_actions=%d)",
                decision, score, reason,
                len(ctx.pending_observations), len(memory_actions),
            )

    # ── Context for modules ───────────────────────────────────────

    def get_idle_seconds(self) -> float:
        return time.time() - self._last_activity

    def note_activity(self, person_id: str | None = None) -> None:
        """Quelqu'un vient de se manifester. Appelable sur le chemin chaud.

        Le réveil ne peut pas être l'effet de bord d'une réponse réussie :
        `_last_activity` n'était écrit qu'à l'émission de `chat.message`, donc
        après l'appel IA et seulement s'il aboutissait — pendant tout le tour
        elle restait officiellement inactive, et un tour en échec ne la
        réveillait jamais.

        `is_internal_person` et non `is_identifiable_person` : un socket
        `anon_*` est bien quelqu'un qui parle.
        """
        from identity.trust import is_internal_person

        if person_id is not None and is_internal_person(person_id):
            return
        self._last_activity = time.time()

    # ── Post-action self-audit ────────────────────────────────────

    # Emotions that trigger a post-action micro-rumination. Strong
    # expressions — positive or negative — are the ones that leave a
    # trace: after saying something bold or anxious, a human replays it
    # mentally. Neutral mid-range responses don't need an audit.
    # `_AUDIT_EMOTIONS` a été supprimée : neuf gabarits littéraux pour
    # vingt-neuf émotions, donc vingt tours ne se rejouaient jamais.
    # `vecu.cible_de_derive` + `vecu.phrase_de_rejeu` les couvrent toutes en
    # dérivant registre et cible de l'ancre PAD déjà déclarée.

    #: Barre au-dessous de laquelle une réponse ne se rejoue pas mentalement,
    #: puis la rampe qui en tire l'intensité de la micro-rumination. Replis :
    #: les mêmes valeurs qu'avant le rapatriement en configuration.
    _AUDIT_MIN_INTENSITY: float = 0.55
    _AUDIT_BASE_INTENSITY: float = 0.2
    _AUDIT_SLOPE: float = 0.5
    _AUDIT_MAX_INTENSITY: float = 0.45

    async def _audit_completed_turn(self, event) -> None:
        """Bus adapter for ``post_action_audit``.

        Holds the one piece of policy the pipeline used to hold on the
        conscience's behalf: a project in professional mode produces no
        lingering self-doubt about a work email. That is a statement about
        ruminations, so it belongs to the conscience, not to the processor.
        """
        data = event.data
        if data.get("project_suppresses_emotion"):
            return
        await self.post_action_audit(
            response_text=data.get("text", ""),
            emotion_name=data.get("emotion_name", ""),
            intensity=data.get("emotion_intensity", 0.0),
            person_id=data.get("person_id", ""),
        )

    async def post_action_audit(
        self,
        response_text: str,
        emotion_name: str,
        intensity: float,
        person_id: str,
    ) -> None:
        """After Mika speaks, maybe create a micro-rumination capturing
        self-evaluation of what she just said.

        Fires only for emotionally marked responses (in _AUDIT_EMOTIONS)
        with intensity >= 0.55. Creates a low-intensity Rumination that
        will decay over the next few cycles — a brief "did I say that
        right?" beat. Cheap, heuristic, no LLM call.

        Skipped for internal-trigger speech (conscience already acted,
        would cause a feedback loop of self-ruminations).
        """
        seuil = cfg_float(
            "conscience.audit.min_intensity", self._AUDIT_MIN_INTENSITY,
            mini=0.0, maxi=1.0,
        )
        if intensity < seuil:
            return
        if person_id == "conscience_mika":
            return
        # Les 29 émotions, pas neuf. La table de gabarits en couvrait neuf, si
        # bien qu'un tour `melancholic` à 0.9 ne se rejouait JAMAIS pendant
        # qu'un tour `proud` à 0.56 se rejouait toujours avec la même phrase.
        # La cible et le registre se dérivent maintenant de l'ancre PAD que
        # `emotion/pad.py` déclare déjà.
        #
        # `Emotion(...)` sous garde : `emotion_name` vient du bus, donc d'une
        # sortie de modèle, et un nom inventé ne doit pas tuer le tour.
        from emotion.types import Emotion

        try:
            emotion = Emotion(emotion_name)
        except ValueError:
            return

        tuning = self._vecu_tuning()
        cible = cible_de_derive(emotion, tuning)
        if cible is Emotion.NEUTRAL:
            # Un tour trop tiède pour laisser une trace : ne rien écrire est la
            # bonne réponse, pas écrire une rumination neutre.
            return

        excerpt = response_text.strip()[:80].replace("\n", " ")
        if not excerpt:
            return
        summary = phrase_de_rejeu(emotion, excerpt, tuning=tuning)
        if not summary:
            return
        rumination_emotion = cible.value
        # Intensity starts modest — a normal person doesn't obsess, just
        # replays once or twice. Scales with how emotional the reply was.
        rumination_intensity = round(min(
            cfg_float("conscience.audit.max_intensity",
                      self._AUDIT_MAX_INTENSITY, mini=0.0, maxi=1.0),
            cfg_float("conscience.audit.base_intensity",
                      self._AUDIT_BASE_INTENSITY, mini=0.0, maxi=1.0)
            + (intensity - seuil) * cfg_float(
                "conscience.audit.slope", self._AUDIT_SLOPE, mini=0.0),
        ), 3)

        try:
            from conscience.models import Rumination
        except ImportError:
            return

        try:
            await sync_to_async(Rumination.objects.create)(
                summary=summary,
                themes=[],
                intensity=rumination_intensity,
                emotion=rumination_emotion,
                observation=None,
                status="active",
            )
            logger.debug(
                "Post-action audit created rumination (%s, %.2f): %s",
                rumination_emotion, rumination_intensity, excerpt[:40],
            )
        except Exception as exc:
            degradations.record("conscience: post-action audit", exc)


# Singleton
conscience_engine = ConscienceEngine()
