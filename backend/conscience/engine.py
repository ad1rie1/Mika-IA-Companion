"""ConscienceEngine — Mika's waking brain.

Sits above modules. Observes all events, interprets them, maintains
memory, and decides when to speak or act. Tightly coupled to memory
with full R/W access.

Lifecycle (managed by ASGI lifespan):
  1. initialize()   — start decision loop
  2. observe(event)  — called by event bus for every module event
  3. _decide()       — periodic evaluation (every 30s, PeriodicLoop)
  4. shutdown()      — stop everything

**Ce fichier est le moteur, pas le cerveau entier.** Il garde la boucle, le
contexte de décision, le score, le journal, le cycle de vie — et un délégué
d'une ligne pour chaque méthode qui vit ailleurs. Le reste est découpé sur
le modèle de ``travaux.py`` (des fonctions de module prenant le moteur,
jamais une classe collaboratrice, parce que les tests construisent le
moteur par ``__new__`` et patchent SES méthodes) :

- ``perception.py``   — observer : interpréter, habituer, colorer, ranger ;
- ``entretien.py``    — la maintenance mémoire, la péremption, la purge ;
- ``ruminations.py``  — les pensées : naissance, pression, saignée, relief ;
- ``affects.py``      — l'ennui, la solitude, la détresse, l'estime, l'espoir ;
- ``acte.py``         — prendre la parole : trousse, prompt, destinataire ;
- ``intention.py``    — ce qu'elle s'apprête à faire, et pourquoi ;
- ``agenda.py``       — les ``ScheduledAction`` dues, à venir, retentées ;
- ``introspection.py``— ce qu'elle relit de sa trace, au cycle et au boot ;
- ``reglages.py``     — les accesseurs ``*_tuning`` et fenêtres, résolus au bord ;
- ``travaux.py``      — le monde des chantiers.

L'état que ces fonctions mutent reste ICI, sur le moteur : en instance
(posé dans ``__init__``) ou en attribut de classe quand il est lu sur des
moteurs construits par ``__new__``.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

from asgiref.sync import sync_to_async

from configs.runtime import cfg_float, cfg_int
from conscience import (
    acte,
    affects,
    agenda,
    entretien,
    intention,
    introspection,
    perception,
    reglages,
    ruminations,
    travaux,
)
from conscience.acte import ActeResultat
from conscience.conduite import Conduite, ConduiteTuning, choisir_conduite
from conscience.interpreter import SignalInterpreter
from conscience.memory_bridge import MemoryBridge
from conscience import murmure as _murmure
from conscience.murmure import murmurer
from conscience.murmure_reglage import tuning as murmure_tuning
from conscience.scoring import ScoringTuning, compute_decision_score
from conscience.trousse import TrousseTuning
from conscience.types import DecisionContext, InterpretedSignal
from conscience.vecu import VecuTuning
from conscience.verdict import VerdictTuning
from drives.engine import drive_engine
from emotion.engine import emotion_engine
from modules.types import ModuleEvent
from utils.degradation import degradations, degraded
from utils.periodic import PeriodicLoop

logger = logging.getLogger(__name__)

#: Pertinence minimale pour qu'une observation pèse dans l'urgence accumulée.
#: Au niveau module, comme les autres portes (voir ``ruminations.py``) : la
#: garde AST de `test_config_rapatriement` ignore un repli ``self._X``.
URGENCY_OBSERVATION_GATE = 0.3
#: Poids d'une observation dans cette somme.
URGENCY_PER_OBSERVATION = 0.5
#: Cycles sautés d'affilée avant que la boucle compte un échec. Un acte tient
#: le verrou jusqu'à ~135 s, soit quatre cycles : en sauter trois est normal.
_CYCLES_SAUTES_MAX = 6
#: Temps laissé aux décisions détachées (fast-path) pour se terminer à
#: l'arrêt, une fois annulées. Borné : une tâche coincée dans un thread
#: d'exécuteur ne rend pas la main sur `cancel()`, et l'arrêt ASGI ne doit
#: pas l'attendre indéfiniment — le dépassement se compte, il ne bloque pas.
_FASTPATH_ARRET_TIMEOUT_S = 5.0


def _intensite_de_debordement(glob) -> float:
    """Intensité que les portes (débordement d'humeur, détresse) comparent.

    Préfère ``overflow_intensity`` quand l'objet la porte et qu'elle est un
    nombre — les doubles de test construisent parfois une humeur minimale —
    et retombe sur ``intensity`` sinon, l'ancienne lecture.
    """
    valeur = getattr(glob, "overflow_intensity", None)
    if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
        return float(valeur)
    return float(getattr(glob, "intensity", 0.0) or 0.0)


def _humeur_ressentie(glob) -> str:
    """Le nom que les portes et le prompt de décision donnent à l'humeur.

    ``felt_emotion`` — l'écart au repos — quand l'objet la porte : la
    position absolue nommait la teinte de l'heure (« amusée » à 14 h) quoi
    que la vie intérieure y ajoute, si bien que la détresse
    (``affects.suivre_la_detresse`` lit la valence de ce nom) ne se
    déclenchait que par cinq tours ``angry 0.9`` d'un utilisateur, jamais
    par elle-même. Retombe sur ``emotion`` (doubles de test).
    """
    ressentie = getattr(glob, "felt_emotion", None)
    valeur = getattr(ressentie, "value", None)
    if isinstance(valeur, str):
        return valeur
    return getattr(getattr(glob, "emotion", None), "value", "") or ""


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
        # entretien._CLEANUP_INTERVAL_S). En RAM : perdre la cadence au
        # redemarrage ne coute qu'un passage supplementaire.
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
        self._arret_demande = False

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
        await introspection.restore_cooldown(self)
        await self._restaurer_inactivite()
        await self._restaurer_salutations()
        await self._reprendre_travaux()

        # Le compteur d'initiatives ignorées « déjà vues » repart de l'état
        # réel : à zéro, `affects.suivre_l_estime_sociale` lisait au premier
        # cycle « 2 ignorées, j'en connaissais 0 » et prenait un coup
        # d'estime pour des silences déjà encaissés avant le redémarrage.
        with degraded("conscience: restauration des ignorees vues"):
            _, self._ignores_vus = await self._introspect()

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

    #: L'arrêt est demandé : plus aucune décision détachée ne se lance.
    #: Attribut de classe — les tests construisent le moteur par `__new__`.
    _arret_demande: bool = False

    async def shutdown(self) -> None:
        # Detach before cancelling the loop: an event arriving mid-shutdown
        # would otherwise be interpreted by an engine that is on its way out.
        self._arret_demande = True
        from utils.eventbus import event_bus
        event_bus.unsubscribe("conscience")
        event_bus.unsubscribe("conscience.audit")

        await self._loop.stop()
        # Les décisions détachées AVANT l'instantané des pulsions : une
        # fast-path en vol pouvait faire `_act` → `process_message` → des
        # écritures après `emotion_engine._save_state` et la passe finale de
        # la mémoire, sur un processus déjà en train de s'éteindre.
        await self._moissonner_les_fastpaths()
        await drive_engine.save_state()

        self._initialized = False
        logger.info("Conscience shut down")

    async def _moissonner_les_fastpaths(self) -> None:
        """Annule les décisions détachées encore en vol et les attend, borné.

        `shutdown()` désabonnait et stoppait la boucle sans jamais toucher à
        `_fastpath_tasks` : une décision spawnée par un signal pertinent
        continuait de tourner pendant que le reste s'éteignait. Le dépassement
        est compté plutôt qu'attendu — une tâche bloquée dans un thread
        d'exécuteur ne se laisse pas annuler.
        """
        en_vol = [t for t in self._fastpath_tasks if not t.done()]
        if not en_vol:
            return
        for tache in en_vol:
            tache.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*en_vol, return_exceptions=True),
                timeout=_FASTPATH_ARRET_TIMEOUT_S,
            )
        except asyncio.TimeoutError as exc:
            degradations.record(
                "conscience: fast-path non moissonnee a l'arret", exc,
                level=logging.WARNING,
            )
        else:
            logger.debug("Fast-path decisions harvested: %d", len(en_vol))

    # ── 1. OBSERVE — délégués vers `conscience/perception.py` ─────

    async def observe(self, event: ModuleEvent) -> None:
        """Délégué — voir `perception.observe`."""
        return await perception.observe(self, event)

    def _habituer(self, source: str, event_type: str, pertinence: float) -> float:
        """Délégué — voir `perception.habituer`."""
        return perception.habituer(self, source, event_type, pertinence)

    def _doser_l_affect(self, source: str, intensite: float) -> float:
        """Délégué — voir `perception.doser_l_affect`."""
        return perception.doser_l_affect(self, source, intensite)

    def _colorer_par_l_humeur(self, pertinence: float, reaction: str) -> float:
        """Délégué — voir `perception.colorer_par_l_humeur`."""
        return perception.colorer_par_l_humeur(pertinence, reaction)

    @staticmethod
    def _feed_emotion(signal: InterpretedSignal) -> None:
        """Délégué — voir `perception.feed_emotion`."""
        return perception.feed_emotion(signal)

    async def _store_observation(self, event, signal):
        """Délégué — voir `perception.store_observation`."""
        return await perception.store_observation(event, signal)

    # ── 2. DECISION LOOP ──────────────────────────────────────────

    async def _decide(self, *, compter_les_sauts: bool = True) -> None:
        """Core decision: evaluate accumulated signals, maintain memory, maybe act.

        Protected by _decision_lock to prevent concurrent decisions from
        the periodic loop and high-pertinence fast-path racing.
        Note: locked() check is safe in asyncio (single-threaded event loop,
        no preemption between check and acquire within the same coroutine step).

        ``compter_les_sauts`` : seul le tick PÉRIODIQUE compte un cycle sauté.
        Le fast-path entrait ici aussi, et cinq mails à p ≥ 0,85 reçus
        pendant un acte (verrou tenu ~135 s) plus le tick suivant faisaient
        six sauts « d'affilée » — un `RuntimeError` compté comme panne de
        boucle alors que rien n'était bloqué.
        """
        if self._decision_lock.locked():
            if not compter_les_sauts:
                logger.debug("Decision already in progress, fast-path dropped")
                return
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

        Rien ne part plus une fois l'arrêt demandé : `observe()` peut encore
        être en vol quand `shutdown()` se désabonne, et une décision lancée à
        cet instant survivrait à la moisson des fast-paths.
        """
        if self._arret_demande:
            logger.debug("Fast-path decision dropped: shutdown in progress")
            return
        task = asyncio.create_task(self._decide(compter_les_sauts=False))
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

        # La détresse se mesure en durée : le suivi doit tourner même les
        # cycles muets, sinon « depuis un quart d'heure » n'existe jamais.
        self._suivre_la_detresse(ctx)
        # Et l'estime encaisse les changements du social : ignorée / répondu.
        await self._suivre_l_estime_sociale(ctx)

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
        travaux_en_cours: list = []
        graines: list = []
        if ctx.sleep_phase == "awake":
            from django.utils import timezone as tz
            maintenant = tz.now()
            travaux_en_cours, semees = await self._travaux_en_cours(maintenant)
            graines = self._recolter(ctx, semees)
        else:
            maintenant = None

        conduite = choisir_conduite(
            score=score,
            seuil=self._threshold,
            travaux=travaux_en_cours,
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

        if decision == "act" and not self._quelquun_est_joignable():
            # Personne, nulle part : ni navigateur, ni handle module joignable.
            # Vérifié ICI, avant `note_interaction()` et le murmure — sinon un
            # rendez-vous prioritaire à 3 h la réveillait pour de bon, la
            # faisait murmurer, et `_act` découvrait ensuite qu'il n'y avait
            # personne. `_act` garde sa propre garde pour le cas où quelqu'un
            # est joignable mais que la sélection ne retient personne.
            self._last_action_time = time.time()
            self._tirer_gigue_cooldown()
            resultat = ActeResultat(sans_audience=True)
            decision = "sans_audience"
            logger.info(
                "Conscience act withheld [%s]: personne de joignable", reason,
            )
        elif decision == "act":
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
            intention_ = self._intention_de_lacte(ctx)
            with degraded("conscience: murmure avant l'acte"):
                await murmurer(
                    intention_,
                    mood=ctx.global_mood,
                    mode_professionnel=await self._mode_professionnel(intention_),
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
            elif resultat.sans_audience:
                # Rien tenté : ni un acte (elle n'a pas parlé) ni une panne.
                # La salutation n'est pas dépensée — elle la dira quand
                # quelqu'un sera là.
                decision = "sans_audience"
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
                if not self._budget_de_pas_disponible():
                    # Un pas est une boucle d'outils complète et muette :
                    # trois chantiers à un pas par quart d'heure faisaient
                    # jusqu'à douze appels par heure, le vrai poste de coût
                    # de la vie intérieure, invisible jusqu'au verdict. Le
                    # chantier attend, rien n'est perdu.
                    logger.debug("Pas de chantier différé : budget horaire épuisé")
                    decision = "wait"
                elif not await self._faire_un_pas(cible):
                    decision = "wait"
            # Sur les TROIS conduites non parlantes, et non plus seulement sur
            # « skip » et « wait » : la péremption des observations entraîne
            # leur promotion en pensées et la décroissance des ruminations. Ne
            # l'appeler que sur deux branches ferait sauter tout ce ménage à
            # chaque cycle qui ouvre ou poursuit un chantier — c'est-à-dire
            # précisément aux cycles où elle a le plus de matière.
            await self._mark_stale_observations()
            # Le vide prolongé a une couleur. `bored` fait partie des 29
            # émotions et rien ne le produisait : une après-midi sans rien
            # laissait l'humeur là où le matin l'avait posée.
            await self._peut_etre_s_ennuyer(ctx, travaux_en_cours)
            # Et ce qui vient en a une aussi : un rendez-vous proche ou un
            # chantier presque au bout glissent vers l'espoir — le futur
            # cesse d'être un calendrier sans affect.
            await self._peut_etre_esperer(ctx, travaux_en_cours)

        # Log the decision — written after the act, whose outcome is part of
        # what the cycle decided (and what _introspect / restore_cooldown read).
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

    # ── Les affects de la vie intérieure — `conscience/affects.py` ─
    #
    # L'état que ces fonctions espacent ou mesurent vit ICI, en attribut de
    # CLASSE : les tests construisent le moteur par `__new__` (voir
    # `_cycles_sautes`), et un état posé seulement dans `__init__` tomberait
    # sur un `AttributeError`.

    #: Horodatage monotone du dernier glissement d'ennui.
    _dernier_ennui: float = 0.0
    #: Mémo du manque de quelqu'un, vérifié au plus toutes les 30 min.
    _manque_verifie_le: float = 0.0
    _manque_present: bool = False
    #: Depuis quand l'humeur est sombre (monotone ; 0 = elle ne l'est pas).
    _detresse_depuis: float = 0.0
    #: Dernier compte d'initiatives ignorées jugé — pour ne prendre le coup
    #: d'estime qu'au CHANGEMENT, jamais en boucle.
    _ignores_vus: int = 0
    #: Horodatage monotone du dernier glissement d'espoir.
    _dernier_espoir: float = 0.0

    async def _peut_etre_s_ennuyer(
        self, ctx: DecisionContext, travaux: list,
    ) -> None:
        """Délégué — voir `affects.peut_etre_s_ennuyer`."""
        return await affects.peut_etre_s_ennuyer(self, ctx, travaux)

    def _suivre_la_detresse(self, ctx: DecisionContext) -> None:
        """Délégué — voir `affects.suivre_la_detresse`."""
        return affects.suivre_la_detresse(self, ctx)

    def _detresse_soutenue(self) -> bool:
        """Délégué — voir `affects.detresse_soutenue`."""
        return affects.detresse_soutenue(self)

    async def _suivre_l_estime_sociale(self, ctx: DecisionContext) -> None:
        """Délégué — voir `affects.suivre_l_estime_sociale`."""
        return await affects.suivre_l_estime_sociale(self, ctx)

    async def _peut_etre_esperer(self, ctx: DecisionContext, travaux: list) -> None:
        """Délégué — voir `affects.peut_etre_esperer`."""
        return await affects.peut_etre_esperer(self, ctx, travaux)

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
        """Délégué — voir `introspection.introspect`."""
        return await introspection.introspect(self)

    # ── Réglages — `conscience/reglages.py` ───────────────────────

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
    #: La salutation déclenchée par le dernier scoring. Attribut de classe
    #: pour la même raison que ses voisins : lue par `_declencheurs` — donc
    #: par l'intention du murmure et le vécu — sur des moteurs construits par
    #: `__new__`, où l'`AttributeError` était avalé par le `degraded` de
    #: l'appelant et rendait l'intention vide EN SILENCE.
    _salutation_en_attente: str | None = None

    def _scoring_tuning(self) -> ScoringTuning:
        """Délégué — voir `reglages.scoring_tuning`."""
        return reglages.scoring_tuning()

    def _fenetres_de_salutation(self) -> tuple[int, int, int, int, int]:
        """Délégué — voir `reglages.fenetres_de_salutation`."""
        return reglages.fenetres_de_salutation()

    def _trousse_tuning(self) -> TrousseTuning:
        """Délégué — voir `reglages.trousse_tuning`."""
        return reglages.trousse_tuning()

    def _vecu_tuning(self) -> VecuTuning:
        """Délégué — voir `reglages.vecu_tuning`."""
        return reglages.vecu_tuning()

    # ── L'intention — `conscience/intention.py` ───────────────────

    def _intention_de_lacte(self, ctx: DecisionContext) -> str:
        """Délégué — voir `intention.intention_de_lacte`."""
        return intention.intention_de_lacte(self, ctx)

    async def _mode_professionnel(self, intention_: str) -> bool:
        """Délégué — voir `intention.mode_professionnel`."""
        return await intention.mode_professionnel(intention_)

    def _declencheurs(self, ctx: DecisionContext) -> list:
        """Délégué — voir `intention.declencheurs`."""
        return intention.declencheurs(self, ctx)

    def _composer_vecu(self, ctx: DecisionContext) -> str:
        """Délégué — voir `intention.composer_vecu`."""
        return intention.composer_vecu(self, ctx)

    # ── Les chantiers — `conscience/travaux.py` ───────────────────

    def _conduite_tuning(self) -> ConduiteTuning:
        """Délégué — le monde des chantiers vit dans `conscience/travaux.py`."""
        return travaux.conduite_tuning()

    async def _travaux_en_cours(self, maintenant) -> tuple[list, set]:
        """Délégué — voir `travaux.travaux_en_cours`."""
        return await travaux.travaux_en_cours(maintenant)

    def _recolter(self, ctx: DecisionContext, semees: set) -> list:
        """Délégué — voir `travaux.recolter`."""
        return travaux.recolter(ctx, semees)

    def _graines_des_modules(self, pulsion, pulsions: list, semees=frozenset()) -> list:
        """Délégué — voir `travaux.graines_des_modules`."""
        return travaux.graines_des_modules(pulsion, pulsions, semees)

    async def _ouvrir_travail(self, graine) -> bool:
        """Délégué — voir `travaux.ouvrir_travail`."""
        return await travaux.ouvrir_travail(graine)

    # ── Le contexte de décision ───────────────────────────────────

    async def _build_context(self) -> DecisionContext:
        """Gather all context needed for a decision."""
        from conscience.models import Observation


        now = time.time()

        # Pending observations (not acted upon, inside the pending window)
        from django.utils import timezone as tz
        from datetime import timedelta

        cutoff = tz.now() - timedelta(minutes=reglages.pending_window_minutes())
        pending = await sync_to_async(
            lambda: list(
                Observation.objects.filter(
                    status="pending",
                    created_at__gte=cutoff,
                ).order_by("-pertinence")[:20]
            )
        )()

        # `themes` est un champ depuis la migration conscience/0013 ; les
        # lignes d'avant n'ont que la convention `raw_data["themes"]`.
        # L'hydratation aligne les deux : après elle, tout lecteur voit le
        # champ rempli, y compris `recolter_graines` qui le lit par `getattr`.
        for obs in pending:
            obs.themes = entretien.themes_de(obs)

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
            global_mood=_humeur_ressentie(glob),
            # Intensité *de débordement*, normalisée sur l'ancre la plus
            # proche (``GlobalMood.overflow_intensity``) : l'intensité brute
            # rapporte la norme à celle d'``excited`` (1,245), si bien que
            # ``sad`` à fond lisait 0,73, ``frustrated`` 0,65 — sous la porte
            # 0,7 du facteur 3 et sous le plancher 0,55 de la détresse. Les
            # deux portes n'étaient franchissables que par l'excitation.
            global_intensity=_intensite_de_debordement(glob),
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

    # ── Les pensées — `conscience/ruminations.py` ─────────────────

    #: Horodatage monotone du dernier balayage « retour d'un absent ».
    #: Attribut de classe — moteurs construits par `__new__`.
    _dernier_retour_scan: float = 0.0

    async def _rumination_snapshot(self) -> tuple[float, int, list[dict]]:
        """Délégué — voir `ruminations.rumination_snapshot`."""
        return await ruminations.rumination_snapshot()

    async def _resolve_ruminations_after_act(self) -> None:
        """Délégué — voir `ruminations.resolve_ruminations_after_act`."""
        return await ruminations.resolve_ruminations_after_act()

    async def _decay_ruminations(self) -> None:
        """Délégué — voir `ruminations.decay_ruminations`."""
        return await ruminations.decay_ruminations(self)

    def _bleed_ruminations(self, saignees: list[tuple[str, float]]) -> None:
        """Délégué — voir `ruminations.bleed_ruminations`."""
        return ruminations.bleed_ruminations(self, saignees)

    async def _promote_stale_to_ruminations(self) -> None:
        """Délégué — voir `ruminations.promote_stale_to_ruminations`."""
        return await ruminations.promote_stale_to_ruminations()

    async def _le_retour_d_un_absent(self) -> None:
        """Délégué — voir `ruminations.le_retour_d_un_absent`."""
        return await ruminations.le_retour_d_un_absent(self)

    # ── Le cooldown ───────────────────────────────────────────────

    #: Plafond de l'espacement, quoi qu'il arrive : au-delà d'une demi-journée
    #: sans un mot, se taire davantage n'est plus de la retenue, c'est une
    #: panne. Le frein dur (`acts_today >= 5`) reste la borne du jour.
    _COOLDOWN_MAX_S: float = 6 * 3600.0
    #: Amplitude de la gigue du cooldown (± cette fraction). Un métronome se
    #: remarque : à cadence exacte, ses relances tombent aux mêmes minutes et
    #: la signature mécanique perce. Repli de `conscience.cooldown_jitter`.
    _COOLDOWN_JITTER: float = 0.15
    #: Le tirage courant, fait UNE fois par acte (`_tirer_gigue_cooldown`) et
    #: non à chaque lecture : `_cooldown_restant` doit afficher un compte qui
    #: descend, pas un nombre qui tremble. Attribut de classe — les tests
    #: construisent le moteur par `__new__`, et 1.0 reproduit l'exactitude
    #: historique.
    _gigue_cooldown: float = 1.0

    def _tirer_gigue_cooldown(self) -> None:
        """Tire la gigue de CE silence-ci. Appelé à l'acte, jamais ailleurs."""
        j = cfg_float(
            "conscience.cooldown_jitter", self._COOLDOWN_JITTER,
            mini=0.0, maxi=0.5,
        )
        self._gigue_cooldown = random.uniform(1.0 - j, 1.0 + j) if j > 0 else 1.0

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
        # La gigue multiplie AVANT le plafond : « jamais plus de six heures »
        # est une promesse, pas une moyenne.
        gigue = getattr(self, "_gigue_cooldown", 1.0)
        base = float(self._cooldown_seconds)
        if consecutive_ignored <= 0:
            return base * gigue
        from configs.service import config_service

        try:
            facteur = float(config_service.get("conscience.ignored_backoff_factor"))
        except Exception:
            facteur = 2.5
        facteur = max(1.0, facteur)
        plafond = cfg_float(
            "conscience.cooldown_max_seconds", self._COOLDOWN_MAX_S, mini=1.0,
        )
        return min(plafond, base * (facteur ** consecutive_ignored) * gigue)

    # ── L'agenda — `conscience/agenda.py` ─────────────────────────

    async def _poll_scheduled_actions(self) -> list:
        """Délégué — voir `agenda.poll_scheduled_actions`."""
        return await agenda.poll_scheduled_actions()

    async def _get_upcoming_actions(self, limit: int = 5) -> list[tuple]:
        """Délégué — voir `agenda.get_upcoming_actions`."""
        return await agenda.get_upcoming_actions(limit)

    async def _compter_tentative(self, actions: list) -> None:
        """Délégué — voir `agenda.compter_tentative`."""
        return await agenda.compter_tentative(actions)

    # ── Le score ──────────────────────────────────────────────────

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

    # ── 3. MEMORY MAINTENANCE — `conscience/entretien.py` ─────────

    async def _memory_maintenance(self, ctx: DecisionContext) -> list[str]:
        """Délégué — voir `entretien.memory_maintenance`."""
        return await entretien.memory_maintenance(self, ctx)

    async def _mark_stale_observations(self) -> None:
        """Délégué — voir `entretien.mark_stale_observations`."""
        return await entretien.mark_stale_observations(self)

    async def _cleanup_old_observations(self) -> None:
        """Délégué — voir `entretien.cleanup_old_observations`."""
        return await entretien.cleanup_old_observations(self)

    # ── 4. ACT ────────────────────────────────────────────────────

    def _verdict_tuning(self) -> VerdictTuning:
        """Délégué — voir `travaux.verdict_tuning`."""
        return travaux.verdict_tuning()

    async def _build_work_prompt(self, row) -> str:
        """Délégué — voir `travaux.build_work_prompt`."""
        return await travaux.build_work_prompt(row)

    #: Budget horaire des pas de chantier, tous chantiers confondus
    #: (`conscience.travail.pas_par_heure_max`). Mémo RAM des pas faits,
    #: posé par `getattr` — moteurs construits par `__new__`.
    _PAS_PAR_HEURE_MAX = 4
    _PAS_FENETRE_S = 3600.0

    def _pas_recents(self) -> list[float]:
        memo = getattr(self, "_pas_faits", None)
        if memo is None:
            memo = []
            self._pas_faits = memo
        maintenant = time.monotonic()
        memo[:] = [t for t in memo if maintenant - t < self._PAS_FENETRE_S]
        return memo

    def _budget_de_pas_disponible(self) -> bool:
        """Reste-t-il un pas dans l'heure ? Ne lève jamais (défaut : oui)."""
        try:
            plafond = cfg_int(
                "conscience.travail.pas_par_heure_max", self._PAS_PAR_HEURE_MAX,
                mini=0,
            )
            return len(self._pas_recents()) < plafond
        except Exception as exc:
            degradations.record("conscience: budget de pas", exc)
            return True

    async def _faire_un_pas(self, identifiant) -> bool:
        """Délégué — voir `travaux.faire_un_pas`, qui orchestre à travers la
        surface du moteur pour que les patchs de test continuent de porter."""
        fait = await travaux.faire_un_pas(self, identifiant)
        if fait:
            with degraded("conscience: compte des pas"):
                self._pas_recents().append(time.monotonic())
        return fait

    def _preparer_trousse_travail(self, row):
        """Délégué — voir `travaux.preparer_trousse_travail`."""
        return travaux.preparer_trousse_travail(self, row)

    async def _peut_etre_dire_le_travail(
        self, verdict, dit: str, titre: str, themes=(),
    ) -> None:
        """Délégué — voir `travaux.peut_etre_dire_le_travail`."""
        return await travaux.peut_etre_dire_le_travail(
            self, verdict, dit, titre, themes,
        )

    async def _rendre_le_pas(self, identifiant) -> None:
        """Délégué — voir `travaux.rendre_le_pas`."""
        return await travaux.rendre_le_pas(identifiant)

    async def _appliquer_verdict(self, identifiant, verdict, dit, bilan) -> None:
        """Délégué — voir `travaux.appliquer_verdict`."""
        return await travaux.appliquer_verdict(self, identifiant, verdict, dit, bilan)

    # ── Au réveil — `conscience/introspection.py` ─────────────────

    async def _restaurer_inactivite(self) -> None:
        """Délégué — voir `introspection.restaurer_inactivite`."""
        return await introspection.restaurer_inactivite(self)

    async def _restaurer_salutations(self) -> None:
        """Délégué — voir `introspection.restaurer_salutations`."""
        return await introspection.restaurer_salutations(self)

    async def _reprendre_travaux(self) -> None:
        """Délégué — voir `travaux.reprendre_travaux`."""
        return await travaux.reprendre_travaux()

    # ── L'acte — `conscience/acte.py` ─────────────────────────────

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
        ressentir: bool = True,
    ):
        """Délégué — voir `acte.appeler_le_modele`. Le seul chemin vers
        `process_message`, partagé par la parole et le pas de travail."""
        return await acte.appeler_le_modele(
            prompt,
            person_id=person_id,
            modules=modules,
            memory_context=memory_context,
            metadata=metadata,
            broadcast=broadcast,
            persist=persist,
            ressentir=ressentir,
        )

    def _quelquun_est_joignable(self) -> bool:
        """Délégué — voir `acte.quelquun_est_joignable`."""
        return acte.quelquun_est_joignable(self)

    @staticmethod
    def _audience_presente() -> bool:
        """Quelqu'un est-il là pour entendre un acte sans destinataire ?

        Même lecture que le murmure (un navigateur connecté ; Telegram ne
        compte pas, un acte sans destinataire ne part pas en push). Crochet
        du moteur pour que les tests qui le font agir sans présence
        enregistrée puissent dire « on l'entend » sans toucher au murmure.
        """
        return _murmure._audience_presente()

    async def _act(self, ctx: DecisionContext, reason: str) -> ActeResultat:
        """Délégué — voir `acte.act`."""
        return await acte.act(self, ctx, reason)

    async def _select_recipient(self, ctx: DecisionContext) -> str | None:
        """Délégué — voir `acte.select_recipient`."""
        return await acte.select_recipient(self, ctx)

    def _modules_enregistres(self) -> list[str]:
        """Délégué — voir `acte.modules_enregistres`."""
        return acte.modules_enregistres()

    def _poids_module(self, nom: str) -> int:
        """Délégué — voir `acte.poids_module`."""
        return acte.poids_module(nom)

    def _preparer_trousse(self, ctx: DecisionContext):
        """Délégué — voir `acte.preparer_trousse`."""
        return acte.preparer_trousse(self, ctx)

    async def _build_action_prompt(
        self,
        ctx: DecisionContext,
        *,
        en_main: str = "",
        a_demander: str = "",
        vecu: str = "",
    ):
        """Délégué — voir `acte.build_action_prompt`. `en_main` et
        `a_demander` sont keyword-only : les inverser à l'appel donnerait un
        prompt qui promet ce qu'il fournit et fournit ce qu'il promet, à
        l'envers."""
        return await acte.build_action_prompt(
            self, ctx, en_main=en_main, a_demander=a_demander, vecu=vecu,
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

    # ── Post-action self-audit — `conscience/ruminations.py` ──────

    def _audit_trop_recent(self, person_id: str) -> bool:
        """Délégué — voir `ruminations.audit_trop_recent`."""
        return ruminations.audit_trop_recent(self, person_id)

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
        """Délégué — voir `ruminations.post_action_audit`."""
        return await ruminations.post_action_audit(
            self, response_text, emotion_name, intensity, person_id,
        )


# Singleton
conscience_engine = ConscienceEngine()
