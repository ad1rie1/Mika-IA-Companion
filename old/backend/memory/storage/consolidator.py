import asyncio
import logging
import time as _time
from datetime import date, timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from old.backend.configs.runtime import cfg_float, cfg_int
from old.backend.emotion.types import Emotion
from old.backend.memory.extraction.extractor import MemoryExtractor
from old.backend.memory.storage.vector_store import (
    VectorStore,
    connaissance_metadata,
    souvenir_metadata,
    vector_call,
)
from old.backend.memory.sensibilite import plus_sensible, sensibilite_extraite
from old.backend.memory.themes import PlanExtraction, plan_by_theme, theme_tuning
from old.backend.utils.periodic import PeriodicLoop
from old.backend.utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)

# The retention sweep is bookkeeping on tables measured in days, so once an
# hour is plenty — running it on every 60s tick would be pure query load.
RETENTION_SWEEP_INTERVAL_S = 3600

# Message sources that are module plumbing, not user-facing exchanges.
# La définition vit dans memory/storage/window.py (partagée avec l'indexeur
# épisodique) ; le nom est ré-exporté ici pour les lecteurs existants.
from old.backend.memory.storage.window import INTERNAL_MESSAGE_SOURCES, user_facing_messages  # noqa: E402

# Une tranche d'extraction ne dépasse jamais ce volume : au-delà, la fenêtre
# est découpée par thème, chaque thème restant borné aux frontières de
# messages (voir _extract_and_store et memory/themes.py).
# `_EXTRACTION_MAX_CHARS_DEFAUT` est la valeur DÉCLARÉE ; `EXTRACTION_MAX_CHARS`
# est la variable de module, que des appelants réassignent pour forcer un
# découpage (les tests de découpe du backlog). Les deux sont distinctes pour
# que le site de lecture sache distinguer « personne n'y a touché » (le réglage
# `memory.extraction_max_chars` gouverne) de « quelqu'un l'a écrasée » (son
# écrasement gagne, sinon il n'aurait plus aucun effet).
_EXTRACTION_MAX_CHARS_DEFAUT = 8000
EXTRACTION_MAX_CHARS = _EXTRACTION_MAX_CHARS_DEFAUT

# Plafond de la fenêtre lue par passe. Le checkpoint ne bouge plus quand
# l'extraction est indisponible : sans ce plafond, un backlog resté au-dessus
# serait relu intégralement à chaque tick de 60 s. Le plafond est choisi AVANT
# la lecture des messages, donc l'invariant « la borne d'abord » tient.
MAX_WINDOW_MESSAGES = 400

# Cadence d'extraction (MEM-04 / MEM-10). Une fenêtre partait dès UN message,
# à chaque tick de 60 s : une question persistée avant sa réponse était
# extraite seule, la réponse au tick d'après — la paire coupée en deux appels
# (« chaque extraction doit être autonome » devenait impossible) — et une
# session d'une heure coûtait 60 à 90 appels d'extraction là où cinq
# suffisent. Une fenêtre part quand elle est MÛRE (assez de messages) ou
# CALME (plus rien depuis un moment), et jamais sur une question dont la
# réponse est encore attendue. La passe forcée de l'arrêt ne se soumet qu'à
# la seconde règle.
EXTRACTION_MIN_MESSAGES = 6
EXTRACTION_QUIET_S = 300
# Rattrapage des souvenirs jamais indexés (MEM-07) : la remémoration part
# exclusivement du vectoriel, une ligne sans vecteur est irrécupérable.
REINDEX_INTERVAL_S = 3600
REINDEX_LOOKBACK_H = 48

# Ce que `stop()` accorde à un tick en cours avant de l'annuler (OPS-02). Le
# tick d'une fenêtre à N tranches durait N × 120 s d'appels IA sous le
# verrou, et rien ne le bornait : un SIGKILL systemd tombait alors entre
# `store_extractions` et le checkpoint. Cinq secondes suffisent au cas
# courant — un appel IA en vol, annulé proprement (rien n'est stocké tant que
# le modèle n'a pas répondu) — et le checkpoint par tranche borne le reste.
STOP_GRACE_S = 5.0

# Pending commitments older than this are dropped (see _expire_commitments).
COMMITMENT_MAX_AGE_DAYS = 30

# Memory decay is measured in days; sweeping for it every 60s was pure load.
DECAY_INTERVAL_S = 3600

# L'agrégat émotionnel a le *jour* pour granularité : le recalculer à chaque
# tick de 60 s réécrivait la même ligne quotidienne et la même ligne
# hebdomadaire ~1440 fois par jour et par personne, chacune précédée d'un
# balayage complet d'``EmotionSnapshot`` (``created_at__date`` n'est pas
# indexable, et la table ne porte aucun index). Cinq minutes restent
# invisibles pour ses deux lecteurs — l'onglet Affect d'une fiche personne et
# la tendance hebdomadaire du prompt — et divisent la charge par cinq. Rien
# n'est perdu : la passe recalcule la journée entière, pas un delta.
EMOTION_AGGREGATION_INTERVAL_S = 300

# Écart de valence entre le meilleur et le pire jour au-delà duquel une
# semaine est dite « instable ». 0.4 sépare une semaine régulière d'une
# semaine qui est passée du clairement négatif au clairement positif — la
# tendance d'un jour se mesure à 0.15, mais sur sept jours c'est la
# *dispersion* qui porte l'information, pas le déplacement moyen.
WEEKLY_VOLATILE_SPREAD = 0.4

# Only rows whose decay anchor is at least this old can move by more than the
# write threshold, so the sweep filters on it in SQL instead of reading the
# whole table into RAM. Generous on purpose: a row that turns out not to move
# simply keeps its anchor, and its elapsed time accumulates for the next pass.
DECAY_MIN_AGE = timedelta(hours=1)

# Nombre maximum de candidats confrontés au LLM par connaissance créée. La
# recherche vectorielle en remonte 5, triés par distance croissante : au-delà
# des deux plus proches, la contradiction devient improbable et chaque
# vérification est un appel LLM séquentiel de plus dans un tick de 60 s — sur
# un backend à un créneau, ils entrent en concurrence avec le tour de
# conversation en cours.
MAX_CONTRADICTION_CHECKS = 1

# Ceiling on rows rewritten per pass. Each write also re-indexes into
# ChromaDB (an embedding call), so a first run over a large backlog stays
# bounded instead of stalling the consolidator; the rest is picked up next
# hour, with no loss — the anchor keeps their elapsed time.
DECAY_BATCH = 500

# Plancher de sommeil : l'importance à laquelle un souvenir cesse de décroître
# et sort du rappel spontané, SANS être effacé. Repli si la config est
# illisible ; la vraie valeur vient de `memory.dormant_importance`.
DORMANT_FLOOR = 0.02


# Ce que vaut un souvenir dont l'extraction n'a rien dit. Volontairement au
# milieu du barème et non à 1.0 : un défaut haut fait de « ce qui a compté »
# un synonyme de « ce qui est récent ».
DEFAULT_IMPORTANCE = 0.5


def _nomme_une_personne(entities) -> bool:
    return any(getattr(e, "entity_type", "") == "person" for e in entities or ())


def _extracted_importance(extraction: dict) -> float:
    """L'importance jugée par l'extraction, bornée à [0.05, 1.0].

    Elle était écrite `1.0` en dur pour tout le monde, alors que le retriever
    la promeut en POIDS DE RANG avec pour justification « l'humain rappelle ce
    qui a COMPTÉ, pas seulement ce qui ressemble ». Le mot n'apparaissait pas
    une seule fois dans l'extracteur : le poids ne départageait donc rien à la
    naissance et ne se différenciait qu'en vieillissant — un doublon exact du
    multiplicateur de récence appliqué trois lignes plus haut.

    Plancher à 0.05 : une extraction qui rend 0 ne doit pas naître déjà
    endormie, sinon elle n'aurait pas dû être extraite du tout.
    """
    brut = extraction.get("importance")
    if brut is None:
        return DEFAULT_IMPORTANCE
    try:
        valeur = float(brut)
    except (TypeError, ValueError):
        return DEFAULT_IMPORTANCE
    if valeur != valeur:  # NaN
        return DEFAULT_IMPORTANCE
    return max(0.05, min(1.0, valeur))


def _dormant_floor(min_importance: float) -> float:
    """Plancher où un souvenir s'endort, toujours SOUS le seuil de rappel.

    Le contrat entre les deux valeurs est ce qui fait tenir la mise en sommeil :
    au-dessus de `memory.min_importance` un souvenir remonte tout seul dans le
    prompt ; entre le plancher et ce seuil il est encore en train de sombrer ;
    au plancher il dort. Si un réglage inverse les deux, on force la marge
    plutôt que de rendre le sommeil inatteignable (le souvenir resterait alors
    éternellement dans le rappel, ce qui est l'inverse du but).
    """
    from old.backend.configs.service import config_service

    try:
        plancher = float(config_service.get("memory.dormant_importance"))
    except Exception:
        plancher = DORMANT_FLOOR
    plancher = max(0.0, plancher)
    if plancher >= min_importance:
        plancher = max(0.0, min_importance * 0.2)
    return plancher


class MemoryConsolidator:
    """Background task that periodically processes raw messages into
    structured memories. Like human dreams consolidating short-term
    into long-term memory.

    Every N seconds:
    1. Fetch unprocessed Messages from Django ORM
    2. Send to Claude for extraction (souvenirs + connaissances)
    3. Create ORM records + index in ChromaDB
    4. Apply decay to old souvenirs
    """

    def __init__(
        self,
        extractor: MemoryExtractor,
        vector_store: VectorStore,
        interval_seconds: int | None = None,
    ):
        self.extractor = extractor
        self.vector_store = vector_store
        from old.backend.configs.service import config_service
        self.interval = interval_seconds or config_service.get("memory.consolidation_interval")
        self._last_processed_id: int = 0
        self._tick_count = 0
        self._loop = PeriodicLoop("Consolidator", self._tick, self.interval)
        # Une seule passe à la fois — voir `_consolidate`.
        self._verrou_consolidation = asyncio.Lock()
        # Posé par `stop()` : la passe en cours abandonne ses tranches
        # restantes entre deux appels IA plutôt que d'aller au bout.
        self._arret_demande = False
        # Ce que les checkpoints par tranche de la passe en cours ont déjà
        # écrit (messages, créations) — la ligne finale ne compte que le reste.
        self._pointe_par_tranche = {"messages": 0, "counts": {}}

    def _verrou(self) -> asyncio.Lock:
        """Le verrou d'une passe. Créé à la demande : les tests construisent
        le consolidateur par ``__new__``, sans passer par ``__init__``."""
        verrou = getattr(self, "_verrou_consolidation", None)
        if verrou is None:
            verrou = self._verrou_consolidation = asyncio.Lock()
        return verrou

    async def start(self):
        """Start the consolidation background loop."""
        await self._load_last_processed_id()
        await self._loop.start(self.interval)
        logger.info("Consolidator resumed at last_id=%d", self._last_processed_id)

    async def stop(self):
        """Stop the loop, bounded.

        Un tick en plein milieu d'une extraction n'est pas annulé d'emblée :
        le drapeau d'arrêt lui fait abandonner ses tranches restantes, et la
        tranche en cours finit — stockée *et* pointée, puisque le checkpoint
        est écrit par tranche. Passé ``STOP_GRACE_S``, il est annulé : la
        coupure tombe alors dans un appel IA (rien n'a été stocké, la fenêtre
        reste due) ou, plus rarement, dans le stockage d'une tranche, qui
        sera relue au prochain démarrage et absorbée par le
        dédoublonnage-renforcement. Jamais plus d'une tranche à rejouer, là
        où un arrêt non borné puis tué rejouait la fenêtre entière.
        """
        self._arret_demande = True
        verrou = self._verrou()
        try:
            await asyncio.wait_for(verrou.acquire(), timeout=STOP_GRACE_S)
        except asyncio.TimeoutError as exc:
            degradations.record("consolidator: arret hors delai", exc)
            logger.warning(
                "Consolidation : la passe en cours n'a pas rendu la main en "
                "%.0f s — tick annulé", STOP_GRACE_S,
            )
            await self._loop.stop()
            return
        try:
            await self._loop.stop()
        finally:
            verrou.release()

    async def force_consolidate(self):
        """Run consolidation immediately (e.g. on disconnect/shutdown).

        Forcée : la fenêtre part même petite et même fraîche — à l'arrêt, on
        ne reviendra pas. Une question encore sans réponse reste retenue :
        sa réponse arrivera après le redémarrage (`resume_interrupted_turns`)
        et la paire sera extraite entière.
        """
        logger.info("Force consolidation triggered")
        # La passe finale de l'arrêt va au bout de sa fenêtre — c'est le
        # `wait_for` du lifespan qui la borne, tranche pointée après tranche.
        self._arret_demande = False
        await self._consolidate(force=True)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _tick(self):
        """One scheduled pass. The counter is purely for reading logs."""
        self._tick_count += 1
        logger.info(
            "Consolidation tick #%d (last_id=%d)",
            self._tick_count, self._last_processed_id,
        )
        await self._consolidate()

    async def _load_last_processed_id(self):
        """Resume from last consolidation checkpoint."""
        from old.backend.memory.models import ConsolidationLog

        try:
            last_log = await sync_to_async(
                lambda: ConsolidationLog.objects.order_by("-pk").first()
            )()
            if last_log:
                self._last_processed_id = last_log.last_message_id
        except Exception as exc:
            # The old message here was "No previous consolidation log found",
            # which this handler never meant: `.first()` returns None on an
            # empty table without raising, so reaching this line is a real DB
            # failure — and one that silently restarts consolidation from the
            # beginning of history.
            degradations.record("consolidator: checkpoint read", exc)

    async def _consolidate(self, force: bool = False):
        """Process new messages since last checkpoint — une passe à la fois.

        La boucle périodique et ``force_consolidate`` (appelé à l'arrêt)
        lisaient la même fenêtre quand l'arrêt tombait au milieu d'un tick :
        deux extractions du même verbatim, deux jeux de souvenirs et
        d'engagements jumeaux que le dédoublonnage ne rattrapait qu'à moitié.
        La seconde passe attend la première ; le checkpoint ayant avancé, sa
        fenêtre est vide et elle ne coûte qu'une lecture.
        """
        async with self._verrou():
            await self._passe(force=force)

    async def _passe(self, force: bool = False):
        """Une passe, hors verrou.

        Four steps, each its own method: select the window, turn it into
        memories, checkpoint, then run the periodic maintenance that has to
        happen whether or not anything was said.
        """
        messages, ceiling_id = await self._select_window(force=force)

        if not messages:
            # Advance past internal-only messages so the window doesn't
            # re-scan them forever — et l'ÉCRIRE : avancé en RAM seule, ce
            # plafond était relu à chaque redémarrage (MEM-08).
            if ceiling_id and ceiling_id > self._last_processed_id:
                self._last_processed_id = ceiling_id
                with degraded("consolidator: checkpoint interne"):
                    await self._save_checkpoint(
                        ceiling_id, 0,
                        {"souvenirs": 0, "connaissances": 0, "commitments": 0},
                    )
            logger.info(
                "Consolidation: no new user messages (last_id=%d)",
                self._last_processed_id,
            )
            await self._run_maintenance(regenerate=False)
            return

        logger.info("Consolidating %d new messages (skipped internal)", len(messages))

        counts, extracted_through = await self._extract_and_store(messages)

        if extracted_through is None:
            # Aucun modèle n'a répondu : la fenêtre reste due. Faire avancer le
            # checkpoint ici, c'est décider que rien de cet après-midi ne
            # deviendra jamais un souvenir. L'extracteur a déjà compté la panne.
            logger.warning(
                "Consolidation: extraction indisponible, checkpoint inchangé (last_id=%d)",
                self._last_processed_id,
            )
            await self._run_maintenance(regenerate=False)
            return

        complete = extracted_through >= messages[-1]["id"]
        max_id = (ceiling_id or messages[-1]["id"]) if complete else extracted_through
        if max_id <= self._last_processed_id:
            # Soit les checkpoints par tranche ont déjà tout écrit (la borne
            # finale vaut la dernière pointée), soit la tranche en échec
            # portait le plus petit id de la fenêtre : rien n'est réputé
            # extrait sous le checkpoint courant. Écrire une ligne égale à la
            # précédente ne dirait rien de vrai ; ce qui reste au-dessus sera
            # relu, et ce qui a été écrit est absorbé par le
            # dédoublonnage-renforcement.
            logger.info(
                "Consolidation: checkpoint inchangé par la passe (last_id=%d)",
                self._last_processed_id,
            )
        else:
            deja = self._pointe_par_tranche
            reste = {
                k: counts.get(k, 0) - deja["counts"].get(k, 0)
                for k in ("souvenirs", "connaissances", "commitments")
            }
            await self._save_checkpoint(
                max_id, len(messages) - deja["messages"], reste,
            )
            self._last_processed_id = max_id

        logger.info(
            "Consolidation complete: %d souvenirs, %d connaissances, "
            "%d commitments from %d messages (last_id=%d)",
            counts["souvenirs"], counts["connaissances"], counts["commitments"],
            len(messages), self._last_processed_id,
        )

        if getattr(self, "_arret_demande", False):
            # La maintenance (décroissance, agrégats, régénérations LLM) est
            # du travail de fond qui se refera au prochain tick.
            return
        await self._run_maintenance(regenerate=True)

    # ── Step 1: pick the window ───────────────────────────────────

    #: La cadence d'extraction s'applique ; les tests qui mesurent la
    #: sélection la coupent (attribut d'instance, moteurs construits par
    #: ``__new__``).
    _cadence_extraction: bool = True

    def _borner_la_cadence(
        self, messages: list[dict], ceiling_id: int | None, *, force: bool = False,
        now=None,
    ) -> tuple[list[dict], int | None]:
        """Ce qui part à l'extraction maintenant, et le plafond qui va avec.

        Deux règles, pures et testables :

        1. **Une question sans réponse encore fraîche est retenue**, avec
           tout ce qui la suit : sa réponse est en train d'être écrite, et
           l'extraire seule coupe la paire. Passé le calme, une question
           restée sans réponse est un fait, elle part.
        2. **La fenêtre part mûre ou calme** : au moins
           ``memory.extraction_min_messages`` messages, ou plus rien depuis
           ``memory.extraction_quiet_seconds``. ``force`` (arrêt) ignore
           cette règle-ci, jamais la première.

        Quand des messages sont retenus, le plafond devient le dernier
        message gardé — sinon le checkpoint sauterait par-dessus ce qu'on
        vient de décider de ne pas extraire.
        """
        if not messages:
            return [], ceiling_id
        now = now or timezone.now()
        quiet_s = cfg_int(
            "memory.extraction_quiet_seconds", EXTRACTION_QUIET_S, mini=0, maxi=86400,
        )
        minimum = cfg_int(
            "memory.extraction_min_messages", EXTRACTION_MIN_MESSAGES, mini=1, maxi=200,
        )

        def _age(m) -> float:
            stamp = m.get("created_at")
            if stamp is None:
                return float("inf")
            return (now - stamp).total_seconds()

        kept = list(messages)
        while kept and kept[-1].get("role") == "user" and _age(kept[-1]) < quiet_s:
            kept.pop()
        if not kept:
            logger.debug("Consolidation: une question attend sa réponse — fenêtre retenue")
            return [], None
        if not force and len(kept) < minimum and _age(kept[-1]) < quiet_s:
            logger.debug(
                "Consolidation: fenêtre de %d message(s) ni mûre ni calme — retenue",
                len(kept),
            )
            return [], None
        if len(kept) < len(messages):
            ceiling_id = int(kept[-1]["id"])
        return kept, ceiling_id

    async def _select_window(self, force: bool = False) -> tuple[list[dict], int | None]:
        """Messages to consolidate, and the id ceiling they were read under.

        The ceiling is picked FIRST, then messages are read below it. Reading
        the messages first and taking the max id afterwards would let a turn
        persisted between the two queries be counted by the checkpoint but
        never extracted — that exchange would be skipped forever.

        Elle est aussi bornée à ``MAX_WINDOW_MESSAGES`` : un backlog que
        l'extraction n'a pas pu absorber reste au-dessus du checkpoint, et le
        relire en entier toutes les 60 s coûterait plus que de le rattraper
        tranche par tranche.
        """
        from old.backend.memory.models import Message

        plafond_fenetre = cfg_int(
            "memory.consolidation_max_window_messages", MAX_WINDOW_MESSAGES,
            mini=10, maxi=5000,
        )
        window_ids = await sync_to_async(
            lambda: list(
                Message.objects.filter(id__gt=self._last_processed_id)
                .order_by("id")
                .values_list("id", flat=True)[:plafond_fenetre]
            )
        )()
        if not window_ids:
            return [], None
        ceiling_id = window_ids[-1]

        # Exclusions canoniques partagées avec l'indexeur épisodique
        # (memory/storage/window.py) : plomberie de modules, machinerie
        # is_internal, prompts d'action de la conscience. Les vraies réponses
        # de Mika (role=assistant, is_internal=False) restent incluses.
        messages = await sync_to_async(list)(
            user_facing_messages(
                Message.objects.filter(
                    id__gt=self._last_processed_id, id__lte=ceiling_id,
                )
            )
            .order_by("created_at")
            .values("id", "role", "content", "created_at", "source", "person_id")
        )
        if messages and getattr(self, "_cadence_extraction", True):
            messages, ceiling_id = self._borner_la_cadence(
                messages, ceiling_id, force=force,
            )
        return messages, ceiling_id

    # ── Step 2: turn the window into memories ─────────────────────

    async def _extract_and_store(
        self, messages: list[dict],
    ) -> tuple[dict[str, int], int | None]:
        """Run the extraction LLM over the window and persist what comes back.

        Returns per-type creation counts, and the id under which everything
        has réellement été extrait — ``None`` quand aucune tranche n'a abouti.
        C'est ce second terme qui décide du checkpoint (``_borne_extraite``) :
        une tranche en échec au milieu d'un backlog était jusqu'ici
        indistinguable des autres.

        Une fenêtre qui tient dans ``EXTRACTION_MAX_CHARS`` part telle quelle,
        en un appel, sans lecture vectorielle — le tick ordinaire de 60 s.
        Au-delà (reprise après indisponibilité, grosse journée), elle est
        découpée **par thème** et non plus en tranches linéaires (voir
        ``_planifier``), chaque thème restant borné à la tranche, sur les
        frontières de messages.
        """
        from old.backend.memory.models import Commitment

        # Open commitments ride along so the same call can notice one being
        # honored in the window ("voila la playlist !") — the autonomous half
        # of the commitment lifecycle; the explicit half is the
        # memory_resolve_commitment tool.
        pending_commitments = await sync_to_async(
            lambda: list(
                Commitment.objects.filter(status="pending")
                .order_by("-created_at")
                .values("id", "description")[:10]
            )
        )()

        counts = {"souvenirs": 0, "connaissances": 0, "commitments": 0}
        taille_tranche = (
            EXTRACTION_MAX_CHARS
            if EXTRACTION_MAX_CHARS != _EXTRACTION_MAX_CHARS_DEFAUT
            else cfg_int(
                "memory.extraction_max_chars", _EXTRACTION_MAX_CHARS_DEFAUT,
                mini=500, maxi=100000,
            )
        )
        plan = await self._planifier(messages, taille_tranche)

        self._pointe_par_tranche = {"messages": 0, "counts": {}}
        reussies: list[list[dict]] = []
        en_echec: list[list[dict]] = []
        for rang, batch in enumerate(plan.tranches):
            if getattr(self, "_arret_demande", False):
                # Arrêt demandé entre deux tranches : celles qui restent
                # sont réputées non extraites — la borne s'arrête sous elles,
                # exactement comme après un échec, et rien n'a été stocké.
                logger.info(
                    "Consolidation : arrêt demandé, %d tranche(s) laissée(s) "
                    "à la prochaine passe", len(plan.tranches) - rang,
                )
                en_echec = plan.tranches[rang:]
                break
            # Who Mika was talking to, as memory entities. The extractor names
            # entities from the *content* ("Thomas said…"), which misses the
            # most basic fact about an exchange: whom it was with. A
            # conversation where nobody says their own name produced souvenirs
            # attached to nobody, so PersonProfile never had material and
            # theory-of-mind stayed empty. Résolu PAR TRANCHE : un thème ne
            # réunit pas forcément les mêmes personnes que la fenêtre entière.
            interlocutors = await self._resolve_interlocutors(batch)
            # Et NOMMÉS dans le texte soumis : l'extracteur ne voyait que
            # « User: » / « Assistant: », donc ne pouvait pas nommer
            # l'interlocuteur — 4 connaissances sur 8 « L'utilisateur… » sans
            # entité, invisibles de la fiche et du filtre intime (MEM-02).
            noms = await self._noms_des_interlocuteurs(batch)
            msg_dicts = [
                {
                    "role": m["role"], "content": m["content"],
                    "speaker": noms.get((m.get("person_id") or "").strip(), ""),
                }
                for m in batch
            ]
            extractions = await self.extractor.analyze_messages(
                msg_dicts, pending_commitments=pending_commitments,
            )
            if extractions is None:
                # Le provider est mort : les tranches suivantes échoueraient
                # de même, et chacune coûterait son timeout.
                en_echec = plan.tranches[rang:]
                break
            batch_counts = await self.store_extractions(
                extractions, interlocutors=interlocutors,
                occurred_at=batch[-1].get("created_at"),
                source_message_ids=[m["id"] for m in batch if isinstance(m.get("id"), int)],
            )
            for key, value in batch_counts.items():
                counts[key] = counts.get(key, 0) + value

            # Le curseur n'avance que si l'extraction a RÉELLEMENT abouti.
            #
            # Il ne dépendait que du fait que le LLM avait répondu : quand les
            # quatorze extractions d'une fenêtre tombaient une à une dans le
            # `except` de `store_extractions` — base verrouillée, ou un petit
            # modèle qui rend `"entities": ["Thomas"]` au lieu d'objets — le
            # curseur passait quand même, et ces soixante messages ne
            # redevenaient jamais des souvenirs. La réorganisation nocturne,
            # verrouillée sur le même curseur, ne les repêchait pas non plus.
            #
            # Échec TOTAL = cause systémique, qui aura disparu au prochain
            # passage : on garde la fenêtre. Échec PARTIEL = extractions
            # individuellement malformées, que rejouer ne réparera pas : on
            # avance, sinon la fenêtre devient un poison qui gèle la
            # consolidation pour de bon.
            tentees = batch_counts.get("tentees", 0)
            echouees = batch_counts.get("echouees", 0)
            if tentees and echouees == tentees:
                logger.warning(
                    "Consolidation : les %d extractions de la tranche ont "
                    "toutes échoué — checkpoint gelé, la fenêtre sera relue.",
                    tentees,
                )
                en_echec = plan.tranches[rang:]
                break
            reussies.append(batch)
            await self._pointer_la_tranche(
                reussies, plan.tranches[rang + 1:], batch, counts,
            )

        return counts, self._borne_extraite(reussies, en_echec)

    async def _pointer_la_tranche(
        self, reussies: list[list[dict]], restantes: list[list[dict]],
        batch: list[dict], counts: dict[str, int],
    ) -> None:
        """Checkpoint par tranche (OPS-02) : après chaque tranche stockée, le
        curseur avance jusqu'où ``_borne_extraite`` l'autorise en comptant
        les tranches *pas encore faites* comme non extraites — la même règle
        ensembliste (min des restantes − 1, jamais sous le courant), donc
        toujours ≤ la borne finale de la passe, et un arrêt entre deux
        tranches n'a rien à ré-extraire de ce qui est déjà stocké.

        Best-effort : une écriture ratée laisse le curseur où il était, la
        borne finale de ``_passe`` le rattrape.
        """
        borne = self._borne_extraite(reussies, restantes)
        if borne is None or borne <= int(getattr(self, "_last_processed_id", 0) or 0):
            return
        deja = getattr(self, "_pointe_par_tranche", None) or {"messages": 0, "counts": {}}
        reste = {
            k: counts.get(k, 0) - deja["counts"].get(k, 0)
            for k in ("souvenirs", "connaissances", "commitments")
        }
        try:
            await self._save_checkpoint(borne, len(batch), reste)
        except Exception as exc:
            degradations.record("consolidator: checkpoint par tranche", exc)
            return
        self._last_processed_id = borne
        self._pointe_par_tranche = {
            "messages": deja["messages"] + len(batch),
            "counts": {k: counts.get(k, 0) for k in reste},
        }

    def _borne_extraite(
        self, reussies: list[list[dict]], en_echec: list[list[dict]],
    ) -> int | None:
        """Jusqu'où le checkpoint peut avancer après une passe.

        Les tranches d'un plan par thème ne sont pas contiguës : réussir le
        thème A (messages 1, 3, 5) ne dit rien du message 2. La règle du
        curseur linéaire est donc reformulée en ensembliste :

        - aucune tranche n'a abouti → ``None``, la fenêtre reste due (cause
          systémique, l'ancienne règle) ;
        - toutes ont abouti → le plus grand id de la fenêtre ;
        - sinon → (plus petit id parmi les tranches en échec) − 1 : tout ce
          qui est dessous a été extrait ; ce qui est au-dessus dans une
          tranche réussie sera relu à la passe suivante — rare, sur échec
          partiel seulement, et le dédoublonnage-renforcement de
          ``store_extractions`` en absorbe une partie. Jamais sous le
          checkpoint courant.

        Sur un plan linéaire (tranches contiguës, arrêt à la première en
        échec) la formule rend la borne d'avant — la dernière tranche réussie
        — à un trou d'ids près : les messages internes exclus de la fenêtre
        entre deux tranches n'avaient rien à extraire.
        """
        if not reussies:
            return None
        if not en_echec:
            return max(int(m["id"]) for t in reussies for m in t)
        plancher = int(getattr(self, "_last_processed_id", 0) or 0)
        premier_rate = min(int(m["id"]) for t in en_echec for m in t)
        return max(plancher, premier_rate - 1)

    async def _planifier(
        self, messages: list[dict], taille_tranche: int,
    ) -> PlanExtraction:
        """Les tranches d'extraction d'une fenêtre.

        Sous une tranche : une seule, linéaire, zéro lecture vectorielle — le
        tick ordinaire. Au-delà : par thème, sur les chunks épisodiques de la
        fenêtre (embeddings stockés, jamais ré-encodés). Sans chunk — étage
        épisodique désactivé, store indisponible, indexeur en retard — tout
        part dans la tranche résiduelle, c'est-à-dire l'ancien découpage
        linéaire : la couverture est complète dans tous les cas.
        """
        if not messages:
            return PlanExtraction(tranches=[])
        total = sum(len(m.get("content") or "") for m in messages)
        if total <= taille_tranche:
            return PlanExtraction(tranches=[messages], residuel=len(messages))
        chunks = await self._chunks_de_la_fenetre(messages)
        plan = plan_by_theme(
            messages, chunks, max_chars=taille_tranche, tuning=theme_tuning(),
        )
        logger.info(
            "Consolidation: fenêtre de %d messages (%d car.) découpée en %d "
            "tranche(s) — %d thème(s), %d message(s) en résiduel",
            len(messages), total, len(plan.tranches), plan.themes, plan.residuel,
        )
        return plan

    async def _chunks_de_la_fenetre(self, messages: list[dict]) -> list[dict]:
        """Les chunks épisodiques couvrant la fenêtre, avec leurs embeddings.

        Toute panne rend ``[]`` — et compte : sans chunk le plan retombe en
        linéaire, ce qui est un fonctionnement dégradé, pas une erreur.
        """
        store = getattr(self, "vector_store", None)
        if store is None:
            return []
        ids = [int(m["id"]) for m in messages]
        try:
            rows = await vector_call(store.get_exchanges_for_messages)(
                min(ids), max(ids), include_embeddings=True,
            )
        except Exception as exc:
            degradations.record("consolidator: chunks de la fenetre", exc)
            return []
        # Un store simulé ou un retour d'une autre forme = pas de chunk.
        return rows if isinstance(rows, list) else []

    async def store_extractions(
        self, extractions: list[dict], *, interlocutors: list,
        occurred_at=None, source_message_ids=(),
    ) -> dict[str, int]:
        """Persiste une liste d'extractions (souvenirs, connaissances,
        engagements) — le second temps de ``_extract_and_store``. Public :
        c'est la moitié réutilisable (dédoublonnage-renforcement, contrôles
        de contradiction), que la réorganisation nocturne appelait avant que
        l'extraction par thème ne revienne ici.

        ``occurred_at`` = quand l'épisode a eu lieu. L'instant de l'extraction
        est un artefact du planificateur : la réorg de 3 h datait d'aujourd'hui
        un échange de la veille, et le biais de récence classait alors la copie
        nocturne devant l'originale.
        """
        # `tentees` / `echouees` ne comptent pas des créations mais des
        # TENTATIVES : c'est ce qui permet à l'appelant de distinguer « cette
        # fenêtre ne contenait rien à retenir » (banalités) de « tout ce qu'on
        # a essayé d'écrire a échoué » — deux situations qui rendaient jusqu'ici
        # le même `{0, 0, 0}` et faisaient avancer le curseur dans les deux cas.
        counts = {
            "souvenirs": 0, "connaissances": 0, "commitments": 0,
            "tentees": 0, "echouees": 0,
        }
        handlers = {
            "souvenir": self._store_souvenir,
            "connaissance": self._store_connaissance,
            "commitment": self._store_commitment,
            "commitment_resolved": self._resolve_commitment,
        }

        for extraction in extractions:
            handler = handlers.get(extraction.get("type"))
            if handler is None:
                logger.debug("Unknown extraction type: %s", extraction.get("type"))
                continue
            counts["tentees"] += 1
            try:
                themes, entities = await self._resolve_tags(extraction)
                provenance = ({"source_message_ids": source_message_ids}
                              if extraction.get("type") == "connaissance" else {})
                created = await handler(
                    extraction, themes=themes, entities=entities,
                    interlocutors=interlocutors, occurred_at=occurred_at, **provenance,
                )
                if created:
                    counts[created] += 1
            except Exception as exc:
                # One malformed extraction must not cost the whole window.
                counts["echouees"] += 1
                degradations.record("consolidator: extraction rejetee", exc)
                logger.exception("Failed to process extraction: %s", extraction)

        return counts

    @staticmethod
    async def _resolve_tags(extraction: dict) -> tuple[list, list]:
        """Get-or-create the Themes and Entities an extraction refers to."""
        from old.backend.memory.models import Entity, Theme

        themes = []
        for name in extraction.get("themes", []) or []:
            if not isinstance(name, str) or not name.strip():
                continue
            theme, _ = await sync_to_async(Theme.objects.get_or_create)(
                name=name.lower().strip()
            )
            themes.append(theme)

        entities = []
        for ent in extraction.get("entities", []) or []:
            # Les deux formes sont acceptées. Un petit modèle local rend
            # régulièrement `"entities": ["Thomas"]` là où le gabarit demande
            # `[{"name": "Thomas", "type": "person"}]` ; l'indexation directe
            # `ent["name"]` levait alors `TypeError: string indices must be
            # integers` sur la PREMIÈRE entité de CHAQUE extraction — donc la
            # fenêtre entière était perdue, silencieusement, à chaque tick.
            if isinstance(ent, str):
                nom, genre = ent.strip(), "concept"
            elif isinstance(ent, dict):
                nom = str(ent.get("name") or "").strip()
                genre = ent.get("type") or "concept"
            else:
                continue
            if not nom:
                continue
            # Insensible à la casse : `get_or_create(name=nom)` exact créait
            # « adrien » à côté de « Adrien » (que la couche identité, elle,
            # cherche en `iexact`) — une fiche scindée, et le filtre intime
            # traitant le doublon comme un tiers (MEM-03).
            entity = await sync_to_async(
                lambda: Entity.objects.filter(
                    name__iexact=nom, entity_type=genre,
                ).order_by("pk").first()
            )()
            if entity is None:
                entity, _ = await sync_to_async(Entity.objects.get_or_create)(
                    name=nom, entity_type=genre,
                )
            entities.append(entity)
        return themes, entities

    async def _store_souvenir(
        self, extraction: dict, *, themes: list, entities: list,
        interlocutors: list, occurred_at=None,
    ) -> str | None:
        from old.backend.memory.models import Souvenir

        occurred = occurred_at or timezone.now()
        emotion = _valid_emotion(extraction.get("emotion"))
        importance = _extracted_importance(extraction)
        # La sensibilité suit les personnes réellement liées (interlocuteur
        # compris) : un épisode qui ne concerne personne n'a rien à protéger.
        linked = _merge_entities(entities, interlocutors)
        sensibilite = sensibilite_extraite(
            extraction, a_une_personne=_nomme_une_personne(linked),
        )

        # Le doublon d'abord, comme pour les connaissances. Une tranche relue
        # après un échec partiel, ou le même épisode raconté deux fois,
        # créait deux lignes — « requin projecteur » ×2 en base — que seule
        # la fusion nocturne rapprochait, et à moitié (MEM-05). Un souvenir
        # redit se RENFORCE : il compte davantage, il n'existe pas deux fois.
        existing = await self._find_similar_souvenir(extraction["content"])
        if existing is not None:
            existing.importance = min(1.0, max(existing.importance, importance) + 0.05)
            existing.decayed_at = timezone.now()
            # Redit, un souvenir peut se révéler plus lourd qu'on ne l'avait
            # noté ; il ne devient jamais plus léger.
            existing.sensibilite = plus_sensible(existing.sensibilite, sensibilite)
            await sync_to_async(existing.save)(
                update_fields=["importance", "decayed_at", "sensibilite"],
            )
            if linked:
                await sync_to_async(existing.entities.add)(*linked)
            if themes:
                await sync_to_async(existing.themes.add)(*themes)
            tous_themes = await sync_to_async(
                lambda: [t.name for t in existing.themes.all()]
            )()
            await self._index(
                self.vector_store.add_souvenir, "souvenir", existing.pk,
                souvenir_id=existing.pk,
                content=existing.content,
                metadata=souvenir_metadata(
                    importance=existing.importance,
                    emotion=existing.emotion,
                    occurred_at=existing.occurred_at.isoformat(),
                    themes=tous_themes,
                ),
            )
            logger.info(
                "Souvenir reinforced (importance=%.2f): %s",
                existing.importance, existing.content[:120],
            )
            return None

        souvenir = await sync_to_async(Souvenir.objects.create)(
            content=extraction["content"], emotion=emotion,
            importance=importance, occurred_at=occurred,
            sensibilite=sensibilite,
        )
        if themes:
            await sync_to_async(souvenir.themes.set)(themes)
        # An episode always involves whoever Mika was talking to, whether or
        # not the extractor thought to name them.
        if linked:
            await sync_to_async(souvenir.entities.set)(linked)

        await self._index(
            self.vector_store.add_souvenir, "souvenir", souvenir.pk,
            souvenir_id=souvenir.pk,
            content=extraction["content"],
            metadata=souvenir_metadata(
                importance=importance,
                emotion=emotion,
                occurred_at=occurred.isoformat(),
                themes=[t.name for t in themes],
            ),
        )
        logger.info(
            "Souvenir created: [%s] %s", emotion, extraction["content"][:120],
        )
        return "souvenirs"

    async def _store_connaissance(
        self, extraction: dict, *, themes: list, entities: list,
        interlocutors: list, occurred_at=None, source_message_ids=(),
    ) -> str | None:
        from old.backend.memory.models import Connaissance

        import math
        content = extraction["content"]
        plafonds = {"observed": 0.9, "reported": 0.8, "inferred": 0.6, "uncertain": 0.35}
        nature = extraction.get("epistemic_kind", "reported")
        if nature not in plafonds:
            nature = "reported"
        try:
            confiance = float(extraction.get("confidence", 0.65))
        except (TypeError, ValueError):
            confiance = 0.65
        if not math.isfinite(confiance):
            confiance = 0.65
        confiance = max(0.0, min(plafonds[nature], confiance))
        sources = list(dict.fromkeys(i for i in source_message_ids if isinstance(i, int) and i > 0))[:256]

        # Le doublon d'abord : en régime établi c'est le cas courant (un fait
        # déjà connu re-extrait), et la vérification de contradiction coûte un
        # appel LLM par candidat. Les dépenser avant de découvrir qu'aucune
        # ligne ne sera créée, c'est les dépenser pour rien — les
        # contradictions autour de ce contenu ont déjà été vérifiées quand il
        # a été enregistré la première fois.
        existing = await self._find_similar_connaissance(content)
        if existing:
            # Se rappeler n'est pas vérifier : la confiance n'augmente pas.
            # En revanche, une nouvelle occurrence entretient la disponibilité
            # du souvenir. Rejouer les mêmes messages ne rajeunit pas l'ancre.
            if not sources or set(sources).difference(existing.source_message_ids or []):
                existing.decayed_at = timezone.now()
            existing.source_message_ids = list(dict.fromkeys(
                [*(existing.source_message_ids or []), *sources],
            ))[-256:]
            existing.sensibilite = plus_sensible(
                existing.sensibilite,
                sensibilite_extraite(extraction, a_une_personne=True),
            )
            await sync_to_async(existing.save)()
            await self._index(
                self.vector_store.add_connaissance, "connaissance", existing.pk,
                connaissance_id=existing.pk,
                content=existing.content,
                metadata=connaissance_metadata(
                    confidence=existing.confidence,
                    is_valid=existing.is_valid,
                ),
            )
            logger.info(
                "Connaissance reinforced (confidence=%.2f): %s",
                existing.confidence, existing.content[:120],
            )
            return None

        await self._check_contradictions(content)

        # Un fait qui ne nomme personne concerne, presque toujours, celui qui
        # l'a dit : sans ce lien, « ne travaille pas pour une banque » vivait
        # sans entité — absent de la fiche de la personne, invisible au filtre
        # intime, rendu « (concerne: …) » par un nom que l'extracteur n'avait
        # pas. Seulement quand UN interlocuteur est identifié (MEM-02).
        linked = list(entities)
        if not _nomme_une_personne(linked) and len(interlocutors) == 1:
            linked = _merge_entities(linked, interlocutors)

        connaissance = await sync_to_async(Connaissance.objects.create)(
            content=content, confidence=confiance, is_valid=True,
            epistemic_kind=nature, source_message_ids=sources,
            sensibilite=sensibilite_extraite(
                extraction, a_une_personne=_nomme_une_personne(linked),
            ),
        )
        if themes:
            await sync_to_async(connaissance.themes.set)(themes)
        if linked:
            await sync_to_async(connaissance.entities.set)(linked)

        await self._index(
            self.vector_store.add_connaissance, "connaissance", connaissance.pk,
            connaissance_id=connaissance.pk,
            content=content,
            metadata=connaissance_metadata(
                confidence=connaissance.confidence,
                is_valid=True,
                themes=[t.name for t in themes],
            ),
        )
        logger.info("Connaissance created: %s", content[:120])
        return "connaissances"

    @staticmethod
    async def _store_commitment(
        extraction: dict, *, themes: list, entities: list, interlocutors: list,
        occurred_at=None,
    ) -> str | None:
        from old.backend.memory.models import Commitment, Entity

        # The extractor may omit the target for a generic promise — in that
        # case it was almost certainly made to whoever Mika was talking to,
        # so fall back to the interlocutor rather than filing it against
        # nobody (which is how a commitment becomes unresolvable).
        # Un engagement déjà en attente, redit, n'est pas un second engagement
        # (« Lui envoyer le lien du concert » ×2 en base, MEM-05).
        if await MemoryConsolidator._engagement_deja_pris(extraction["content"]):
            logger.info("Commitment already pending: %s", extraction["content"][:120])
            return None

        target_person = None
        person_name = (extraction.get("person") or "").strip()
        if person_name:
            target_person, _ = await sync_to_async(Entity.objects.get_or_create)(
                name=person_name, entity_type="person",
            )
        elif len(interlocutors) == 1:
            target_person = interlocutors[0]

        await sync_to_async(Commitment.objects.create)(
            description=extraction["content"], person=target_person,
            status="pending",
        )
        logger.info(
            "Commitment created [to=%s]: %s",
            person_name or (target_person.name if target_person else "—"),
            extraction["content"][:120],
        )
        return "commitments"

    @staticmethod
    async def _engagement_deja_pris(description: str, seuil: float = 0.85) -> bool:
        """Un engagement en attente dit la même chose, à peu près ?

        Lexical (``difflib``), pas vectoriel : les engagements ne sont pas
        indexés, et une promesse redite l'est presque mot pour mot.
        """
        import difflib

        from old.backend.memory.models import Commitment

        cible = " ".join(str(description or "").lower().split())
        if not cible:
            return False
        try:
            en_attente = await sync_to_async(
                lambda: list(
                    Commitment.objects.filter(status="pending")
                    .values_list("description", flat=True)[:50]
                )
            )()
        except Exception as exc:
            degradations.record("consolidator: relecture des engagements", exc)
            return False
        for existant in en_attente:
            autre = " ".join(str(existant or "").lower().split())
            if autre == cible or difflib.SequenceMatcher(None, cible, autre).ratio() >= seuil:
                return True
        return False

    @staticmethod
    async def _resolve_commitment(
        extraction: dict, *, themes: list, entities: list, interlocutors: list,
        occurred_at=None,
    ) -> str | None:
        from old.backend.memory.models import Commitment

        resolution = extraction.get("resolution", "honored")
        if resolution not in ("honored", "dropped"):
            resolution = "honored"
        updated = await sync_to_async(
            lambda: Commitment.objects.filter(
                pk=extraction.get("commitment_id"), status="pending",
            ).update(status=resolution, resolved_at=timezone.now())
        )()
        if updated:
            logger.info(
                "Commitment #%s resolved (%s) from conversation",
                extraction.get("commitment_id"), resolution,
            )
        return None

    @staticmethod
    async def _index(fn, kind: str, pk: int, **kwargs) -> None:
        """Push a row into ChromaDB, tolerating failure.

        Indexing is best-effort by design: the ORM record is the source of
        truth, and losing a vector entry costs recall, not the memory itself.
        """
        try:
            await vector_call(fn)(**kwargs)
        except Exception as exc:
            # Compté : la remémoration part exclusivement du vectoriel, donc
            # une ligne non indexée est irrécupérable pour le rappel — et le
            # ledger ne le savait pas (MEM-07). `_reindex_missing` repasse.
            degradations.record("consolidator: indexation chromadb", exc)
            logger.warning("ChromaDB indexing failed for %s #%d", kind, pk)

    # ── Step 3: checkpoint ────────────────────────────────────────

    @staticmethod
    async def _save_checkpoint(
        max_id: int, processed: int, counts: dict[str, int],
    ) -> None:
        """Record the window as done, atomically.

        The transaction protects against a crash between the in-memory
        update and the DB write.
        """
        from old.backend.memory.models import ConsolidationLog

        def _write():
            with transaction.atomic():
                ConsolidationLog.objects.create(
                    messages_processed=processed,
                    souvenirs_created=counts["souvenirs"],
                    connaissances_created=counts["connaissances"],
                    last_message_id=max_id,
                )

        await sync_to_async(_write)()

    # ── Step 4: periodic maintenance ──────────────────────────────

    async def _run_maintenance(self, *, regenerate: bool) -> None:
        """Decay, aggregation, and the two LLM-backed regenerations.

        Runs on both consolidation paths — an install nobody talks to still
        needs its decay and its retention sweep. ``regenerate`` gates the
        narrative and profile passes, which have nothing new to work from
        when no message was consolidated.

        Sleep cycle and project runner have their own dedicated loops (wired
        at lifespan startup), so a long LLM call in either never delays this.
        """
        await self._apply_decay()
        await self._aggregate_emotion_snapshots()
        await self._reindex_missing()

        if not regenerate:
            return

        # Both are best-effort: the memory pipeline is the priority, and a
        # failed narrative must not cost the consolidation that produced it.
        try:
            from old.backend.memory.narrative import narrative_generator
            await narrative_generator.run_if_due()
        except Exception:
            logger.exception("Self-narrative generation failed (non-fatal)")

        try:
            from old.backend.memory.person_profile import person_profile_generator
            await person_profile_generator.run_cycle()
        except Exception:
            logger.exception("Person profile generation failed (non-fatal)")

    @staticmethod
    async def _noms_des_interlocuteurs(messages: list[dict]) -> dict[str, str]:
        """``person_id → prénom`` pour les locuteurs identifiés de la tranche.

        Même chemin que ``_resolve_interlocutors`` (la couche identité), même
        règle : un visiteur non lié n'a pas de nom, il reste « User » dans le
        texte soumis. Ne lève jamais.
        """
        from old.backend.identity.resolver import identity_resolver

        noms: dict[str, str] = {}
        person_ids = {
            (m.get("person_id") or "").strip()
            for m in messages if m.get("role") == "user"
        }
        for person_id in sorted(p for p in person_ids if p):
            try:
                entity = await identity_resolver.entity_for_person(person_id)
            except Exception as exc:
                degradations.record("consolidator: nom d'interlocuteur", exc)
                continue
            if entity is not None and getattr(entity, "name", ""):
                noms[person_id] = str(entity.name)
        return noms

    async def _reindex_missing(self) -> None:
        """Réindexe les souvenirs récents que ChromaDB n'a pas. Horaire.

        Un `upsert` qui a échoué (store indisponible, encodeur en panne) ne
        laissait rien derrière lui qu'une ligne de log : la ligne ORM existait,
        le rappel ne la trouverait jamais. On relit les souvenirs des
        dernières 48 h, on demande au store lesquels il tient, on repousse
        les autres. Ne lève jamais.
        """
        store = getattr(self, "vector_store", None)
        if store is None or not hasattr(store, "souvenir_ids_present"):
            return
        now = _time.monotonic()
        last = getattr(self, "_last_reindex", 0.0)
        if last and (now - last) < REINDEX_INTERVAL_S:
            return
        self._last_reindex = now
        try:
            from old.backend.memory.models import Souvenir

            depuis = timezone.now() - timedelta(hours=REINDEX_LOOKBACK_H)

            def _entrees() -> list[dict]:
                # Tout ce qui touche l'ORM (M2M comprises) reste dans le
                # thread d'exécuteur : lire `themes.all()` depuis la boucle
                # lèverait `SynchronousOnlyOperation` au premier cache manqué.
                return [
                    {
                        "souvenir_id": s.pk,
                        "content": s.content,
                        "metadata": souvenir_metadata(
                            importance=s.importance, emotion=s.emotion,
                            occurred_at=s.occurred_at.isoformat() if s.occurred_at else "",
                            themes=[t.name for t in s.themes.all()],
                        ),
                    }
                    for s in Souvenir.objects.filter(created_at__gte=depuis)
                    .prefetch_related("themes").order_by("pk")[:2000]
                ]

            recents = await sync_to_async(_entrees)()
            if not recents:
                return
            presents = await vector_call(store.souvenir_ids_present)(
                [e["souvenir_id"] for e in recents],
            )
            if not isinstance(presents, (list, tuple, set)):
                return  # store simulé ou réponse d'une autre forme
            presents = set(presents)
            manquants = [e for e in recents if e["souvenir_id"] not in presents]
            if not manquants:
                return
            await vector_call(store.add_souvenirs)(manquants)
            logger.warning(
                "Consolidation: %d souvenir(s) réindexé(s) — ils manquaient au store",
                len(manquants),
            )
        except Exception as exc:
            degradations.record("consolidator: reindexation des manquants", exc)

    @staticmethod
    async def _resolve_interlocutors(messages: list[dict]) -> list:
        """Memory entities for the people Mika exchanged with in this window.

        Goes through the identity layer, so a person only shows up once Mika
        actually knows who they are — authenticated, or a claim she accepted.
        An unidentified visitor contributes nothing here, which is correct:
        their souvenirs stay unattached until she recognizes them, and
        attaching them to a transport handle would just recreate the
        entity-per-socket problem this replaced.
        """
        from old.backend.identity.resolver import identity_resolver

        person_ids = {
            (m.get("person_id") or "").strip()
            for m in messages
            if m.get("role") == "user"
        }
        entities: list = []
        seen: set[int] = set()
        for person_id in sorted(p for p in person_ids if p):
            try:
                entity = await identity_resolver.entity_for_person(person_id)
            except Exception as exc:
                degradations.record("consolidator: interlocutor resolution failed for", exc)
                continue
            if entity is not None and entity.pk not in seen:
                seen.add(entity.pk)
                entities.append(entity)
        return entities

    async def _apply_decay(self):
        """Reduce importance of old souvenirs and confidence of old connaissances.
        Remove those below threshold.

        Throttled to ``DECAY_INTERVAL_S``. Memory decay is measured in days,
        so running it on every 60s tick was 1440 full-table sweeps a day to
        apply changes that only become visible after hours — and it ran on
        the "no new messages" path too, so an install nobody talks to paid
        the full cost forever. Correctness is unaffected: decay is anchored
        on each row's ``decayed_at``, so a longer gap just means a larger
        (still exact) step.
        """
        now = _time.monotonic()
        last = getattr(self, "_last_decay", 0.0)
        if last and (now - last) < cfg_int(
            "memory.decay_interval_s", DECAY_INTERVAL_S, mini=60, maxi=86400,
        ):
            # Commitment expiry is a pair of cheap indexed UPDATEs and is
            # what stops a stale promise being re-asserted in every prompt,
            # so it keeps running on its own cadence.
            await self._expire_commitments()
            await self._sweep_retention()
            return
        self._last_decay = now

        await self._decay_souvenirs()
        await self._decay_connaissances()
        await self._expire_commitments()
        await self._sweep_retention()

    async def _expire_commitments(self):
        """Age out stale promises — the "dropped" half of the lifecycle.

        A commitment past its ``due_at``, or pending for more than
        COMMITMENT_MAX_AGE_DAYS, stops being re-asserted in every prompt
        as "tu lui avais dit que..." — after a month it's not a plan
        anymore, it's guilt. Cheap UPDATEs, safe to run every tick.
        """
        from old.backend.memory.models import Commitment

        now = timezone.now()
        try:
            dropped = await sync_to_async(
                lambda: Commitment.objects.filter(
                    status="pending", due_at__isnull=False, due_at__lt=now,
                ).update(status="dropped", resolved_at=now)
            )()
            cutoff = now - timedelta(days=cfg_int(
                "memory.commitment_max_age_days", COMMITMENT_MAX_AGE_DAYS,
                mini=1, maxi=365,
            ))
            dropped += await sync_to_async(
                lambda: Commitment.objects.filter(
                    status="pending", created_at__lt=cutoff,
                ).update(status="dropped", resolved_at=now)
            )()
            if dropped:
                logger.info("Dropped %d stale commitment(s)", dropped)
        except Exception:
            logger.exception("Commitment expiry failed (non-fatal)")

    async def _sweep_retention(self):
        """Cap the append-only audit tables. Hourly, not every tick.

        Reached from both consolidation paths (with and without new
        messages), so it keeps running on an install nobody talks to — which
        is precisely when ConscienceLog grows fastest relative to content.
        """
        now = _time.monotonic()
        last = getattr(self, "_last_retention_sweep", 0.0)
        if last and (now - last) < cfg_int(
            "memory.retention_sweep_interval_s", RETENTION_SWEEP_INTERVAL_S,
            mini=60, maxi=86400,
        ):
            return
        self._last_retention_sweep = now
        try:
            from old.backend.memory.retention import run_sweep
            await run_sweep()
        except Exception:
            logger.exception("Retention sweep failed (non-fatal)")

    async def _decay_souvenirs(self):
        """Reduce importance of old souvenirs. Remove those below threshold.

        Only rows whose anchor is older than ``DECAY_MIN_AGE`` are read: a
        souvenir touched minutes ago cannot move by more than the write
        threshold, so loading it just to skip it was the bulk of the work.
        The rest of the loop stays row-by-row because each row decays from
        its own anchor, which no bulk UPDATE can express.

        Les ré-indexations, elles, sont regroupées en un seul upsert de fin de
        passe : un encode par ligne coûtait jusqu'à ``DECAY_BATCH`` encodes
        consécutifs, là où SentenceTransformer traite un lot en une fois. La
        ligne ORM reste la source de vérité, donc un lot perdu coûte du rappel
        jusqu'à la passe suivante, jamais le souvenir lui-même.
        """
        from django.db.models import Q
        from old.backend.memory.models import Souvenir

        from old.backend.configs.service import config_service
        decay_rate = config_service.get("memory.decay_rate")
        min_importance = config_service.get("memory.min_importance")
        dormant_floor = _dormant_floor(min_importance)
        now = timezone.now()
        cutoff = now - DECAY_MIN_AGE

        # ``prefetch_related`` obligatoire : le ré-index relit les thèmes en
        # contexte async — sans le cache de prefetch, `.themes.all()` lèverait
        # SynchronousOnlyOperation (et coûterait un aller DB par ligne).
        # Le filtre porte sur le PLANCHER DE SOMMEIL, pas sur le seuil de
        # rappel : un souvenir endormi ne doit plus être relu à chaque passe
        # (il ne bougera plus), mais tout ce qui est encore au-dessus doit
        # continuer à vieillir, y compris entre `dormant_floor` et
        # `min_importance` — c'est la pente sur laquelle il s'endort.
        souvenirs = await sync_to_async(list)(
            Souvenir.objects.filter(importance__gt=dormant_floor)
            .filter(Q(decayed_at__isnull=True) | Q(decayed_at__lt=cutoff))
            .order_by("decayed_at")
            .prefetch_related("themes")[:cfg_int(
                "memory.decay_batch", DECAY_BATCH, mini=10, maxi=10000,
            )]
        )
        if not souvenirs:
            return

        reindex: list[dict] = []
        for souvenir in souvenirs:
            # Use occurred_at (when it happened) not created_at (when it was stored)
            ref_date = souvenir.occurred_at or souvenir.created_at
            # Decay multiplicatively from the CURRENT value since the last pass.
            # Recomputing an absolute rate**age would wipe every conscience
            # boost and inflate freshly-created low-importance souvenirs to ~1.0.
            anchor = souvenir.decayed_at or ref_date
            days_since = max(0.0, (now - anchor).total_seconds() / 86400)
            new_importance = souvenir.importance * (decay_rate ** days_since)
            if new_importance < dormant_floor:
                # ON N'EFFACE PLUS. Un souvenir qui passe sous le seuil
                # s'ENDORT : il descend au plancher, cesse d'y décroître, et
                # sort du rappel spontané (le retriever filtre sur
                # ``memory.min_importance``, au-dessus de ce plancher).
                #
                # Avant, c'était un `DELETE` SQL doublé d'un retrait ChromaDB :
                # « Thomas m'a annoncé qu'il se marie » cessait d'exister au
                # bout de 45 jours si personne n'en reparlait, et la couche
                # *interprétée* — celle qui nourrit la self-narrative et les
                # fiches — avait donc un horizon de six semaines, alors que la
                # transcription brute, elle, est éternelle. L'oubli humain ne
                # fonctionne pas ainsi : on cesse d'y penser tout seul, on
                # reconnaît quand on nous le rappelle. La ligne et son vecteur
                # restent donc en place, retrouvables par une recherche
                # DÉLIBÉRÉE (`memory_search`) et ranimables par un boost de la
                # Conscience.
                if abs(souvenir.importance - dormant_floor) <= 1e-6:
                    continue  # déjà endormi : rien à réécrire
                updated = await sync_to_async(
                    lambda s=souvenir: Souvenir.objects.filter(
                        pk=s.pk, importance=s.importance, decayed_at=s.decayed_at,
                    ).update(importance=dormant_floor, decayed_at=now)
                )()
                if not updated:
                    continue
                souvenir.importance = dormant_floor
                souvenir.decayed_at = now
                reindex.append({
                    "souvenir_id": souvenir.pk,
                    "content": souvenir.content,
                    "metadata": souvenir_metadata(
                        importance=souvenir.importance,
                        emotion=souvenir.emotion,
                        occurred_at=ref_date.isoformat(),
                        themes=[t.name for t in souvenir.themes.all()],
                    ),
                })
                logger.debug("Souvenir #%d endormi (sous le seuil)", souvenir.pk)
            elif abs(new_importance - souvenir.importance) > 0.01:
                # Below that delta we leave the anchor alone so the elapsed
                # time keeps accumulating instead of being silently dropped.
                rounded = round(new_importance, 3)
                updated = await sync_to_async(
                    lambda s=souvenir, v=rounded: Souvenir.objects.filter(
                        pk=s.pk, importance=s.importance, decayed_at=s.decayed_at,
                    ).update(importance=v, decayed_at=now)
                )()
                if not updated:
                    continue
                souvenir.importance = rounded
                souvenir.decayed_at = now
                # Le helper garantit qu'un ré-index ne perd plus `emotion` ni
                # `themes` — un upsert remplace les métadonnées en entier.
                reindex.append({
                    "souvenir_id": souvenir.pk,
                    "content": souvenir.content,
                    "metadata": souvenir_metadata(
                        importance=souvenir.importance,
                        emotion=souvenir.emotion,
                        occurred_at=ref_date.isoformat(),
                        themes=[t.name for t in souvenir.themes.all()],
                    ),
                })

        if reindex:
            try:
                await vector_call(self.vector_store.add_souvenirs)(reindex)
            except Exception as exc:
                degradations.record("consolidator: chromadb update failed for souvenir #", exc)

    async def _decay_connaissances(self):
        """Slowly reduce confidence of old connaissances that haven't been reinforced.

        Unlike souvenirs, connaissances are not deleted — they become 'incertain'
        (low confidence) but stay valid. Only the Conscience can invalidate them.

        Decay rate: ~2% per week after 7 days without reinforcement.
        This is gentler than souvenir decay (0.95^days) because knowledge
        is more durable than episodic memory.

        Decay is measured from ``decayed_at``, not ``updated_at``. The latter
        is ``auto_now``, and Django only refreshes an ``auto_now`` field when
        it is among the columns being written — ``save(update_fields=
        ["confidence"])`` never is. So the anchor never advanced and every
        pass re-subtracted the *entire* elapsed decay: at a 60s tick, a fact
        a month old lost ~0.086 per tick and hit the floor in about ten
        minutes. Measured, not theorised: three simulated passes on a 30-day
        row went 1.0 → 0.914 → 0.828 → 0.742.

        This is the same relative-vs-absolute bug already fixed for
        ``Souvenir.decayed_at``; connaissances were simply never migrated.
        """
        from django.db.models import Q
        from old.backend.memory.models import Connaissance

        now = timezone.now()
        min_confidence = 0.2  # Floor — don't decay below this
        # Nothing reinforced in the last week can have accrued a full week of
        # decay, so the 7-day grace period is expressed in SQL rather than by
        # loading the table and skipping most of it in Python.
        grace_cutoff = now - timedelta(days=7)
        anchor_cutoff = now - DECAY_MIN_AGE

        connaissances = await sync_to_async(list)(
            Connaissance.objects.filter(
                is_valid=True,
                confidence__gt=min_confidence,
                updated_at__lt=grace_cutoff,
            )
            .filter(Q(decayed_at__isnull=True) | Q(decayed_at__lt=anchor_cutoff))
            .order_by("decayed_at")[:cfg_int(
                "memory.decay_batch", DECAY_BATCH, mini=10, maxi=10000,
            )]
        )

        for conn in connaissances:
            # First pass for this row: fall back to updated_at, which is when
            # it was last reinforced — the correct starting point.
            anchor = conn.decayed_at or conn.updated_at
            days_since = max(0.0, (now - anchor).total_seconds() / 86400)

            # Gentle decay: lose ~2% confidence per week since the anchor.
            decay = 0.02 * (days_since / 7)
            new_confidence = max(min_confidence, conn.confidence - decay)

            if abs(new_confidence - conn.confidence) > 0.01:
                conn.confidence = round(new_confidence, 3)
                conn.decayed_at = now
                await sync_to_async(conn.save)(
                    update_fields=["confidence", "decayed_at"])
                logger.debug(
                    "Decayed connaissance #%d confidence to %.2f",
                    conn.pk, conn.confidence,
                )

    # ------------------------------------------------------------------
    # Emotional memory aggregation
    # ------------------------------------------------------------------

    POSITIVE_EMOTIONS = frozenset({
        "happy", "excited", "love", "proud", "grateful",
        "playful", "amused", "hopeful", "relieved",
    })
    NEGATIVE_EMOTIONS = frozenset({
        "sad", "angry", "scared", "disgusted", "frustrated",
        "lonely", "anxious", "bored", "jealous",
    })

    async def _aggregate_emotion_snapshots(self) -> None:
        """Aggregate raw EmotionSnapshots into EmotionalSummary records.

        Groups today's snapshots by person_id, computes weighted emotion
        distribution, dominant emotion, and trend vs yesterday. Then prunes
        old snapshots.

        Étranglée à ``EMOTION_AGGREGATION_INTERVAL_S``, comme la décroissance
        et le balayage de rétention juste à côté : la passe reconstruit la
        journée entière à chaque fois, donc l'espacer ne change que la
        fraîcheur de la ligne — jamais sa valeur. L'élagage des relevés qui la
        termine se mesure en jours et s'en accommode de même.
        """
        from old.backend.memory.models import EmotionalSummary, EmotionSnapshot

        monotonic = _time.monotonic()
        last = getattr(self, "_last_aggregation", 0.0)
        if last and (monotonic - last) < cfg_int(
            "memory.emotion_aggregation_interval_s", EMOTION_AGGREGATION_INTERVAL_S,
            mini=30, maxi=86400,
        ):
            return
        self._last_aggregation = monotonic

        now = timezone.now()
        # Même horloge que l'écrivain et que le lookup ``__date`` (heure
        # locale). Dater depuis l'instant aware donne la date UTC, qui range
        # la journée émotionnelle dans la veille entre minuit et l'aube.
        today = date.today()

        # Get distinct person_ids with snapshots from today (exclude __global__)
        #
        # ``order_by()`` vide avant ``distinct()`` : le modèle déclare un
        # ``Meta.ordering`` sur ``created_at``, que Django ajoute alors au
        # SELECT — la colonne de tri entre dans la clé de dédoublonnage et
        # chaque relevé ressort comme une personne distincte. La boucle
        # ci-dessous, et l'agrégation hebdomadaire qui reçoit la même liste,
        # réécrivaient donc la même ligne quotidienne autant de fois qu'il y
        # avait eu de réponses dans la journée. Même piège qu'à
        # ``GestionSysteme/views/inner.py``.
        person_ids = await sync_to_async(
            lambda: list(
                EmotionSnapshot.objects.filter(
                    created_at__date=today,
                ).exclude(
                    person_id="__global__",
                ).order_by().values_list("person_id", flat=True).distinct()
            )
        )()
        # La même règle que l'écrivain (``save_snapshot``) : un résumé pour
        # ``anon_*`` ou ``conscience_mika`` n'est le profil affectif de
        # personne, et le moteur les rechargeait en RAM trente jours au boot.
        from old.backend.identity.trust import is_identifiable_person

        person_ids = [pid for pid in person_ids if is_identifiable_person(pid)]

        if not person_ids:
            return

        for pid in person_ids:
            snapshots = await sync_to_async(
                lambda p=pid: list(
                    EmotionSnapshot.objects.filter(
                        person_id=p, created_at__date=today,
                    ).values("primary_emotion", "primary_intensity")
                )
            )()
            if not snapshots:
                continue

            # Weighted distribution: sum intensity per emotion
            distribution: dict[str, float] = {}
            for s in snapshots:
                emotion = s["primary_emotion"]
                intensity = s["primary_intensity"]
                distribution[emotion] = distribution.get(emotion, 0.0) + intensity

            total = sum(distribution.values()) or 1.0
            normalized = {k: round(v / total, 3) for k, v in distribution.items()}
            dominant = max(distribution, key=distribution.get)
            dominant_intensity = round(distribution[dominant] / len(snapshots), 2)

            # Compute trend vs yesterday
            trend = await self._compute_emotion_trend(
                pid, normalized, today - timedelta(days=1), period_type="daily",
            )

            await sync_to_async(
                lambda p=pid, d=dominant, di=dominant_intensity, n=normalized, t=trend, sc=len(snapshots): (
                    EmotionalSummary.objects.update_or_create(
                        person_id=p,
                        period_type="daily",
                        period_start=today,
                        defaults={
                            "dominant_emotion": d,
                            "dominant_intensity": di,
                            "emotion_distribution": n,
                            "trend": t,
                            "snapshot_count": sc,
                        },
                    )
                )
            )()

        # The week in progress, rebuilt from the days just refreshed. Must
        # happen before the prune below: it reads daily rows, not snapshots,
        # but keeping the two aggregations adjacent is what stops one being
        # updated without the other.
        await self._aggregate_weekly_summaries(person_ids, today)

        # Prune old snapshots (keep last N days for aggregation overlap)
        from old.backend.configs.service import config_service
        retention_days = config_service.get("emotion.snapshot_retention_days")
        cutoff = now - timedelta(days=retention_days)
        deleted = await sync_to_async(
            lambda: EmotionSnapshot.objects.filter(created_at__lt=cutoff).delete()
        )()
        if deleted and deleted[0]:
            logger.info("Pruned %d old emotion snapshots", deleted[0])

        logger.debug(
            "Emotion aggregation: %d person(s) for %s", len(person_ids), today,
        )

    async def _aggregate_weekly_summaries(self, person_ids, today) -> None:
        """Roll the week in progress up from its daily summaries.

        **Built from the daily rows, not from raw snapshots** — and that is
        forced, not a preference: ``emotion.snapshot_retention_days`` defaults
        to **2**, so by the time a week ends five of its seven days have been
        pruned. Reading raw here would produce a row labelled "semaine" that
        covers the last two days, which is worse than no row at all.

        Refreshed in place on every pass, exactly like the daily row, so the
        current week exists from Monday rather than appearing on Sunday night.
        Driving it off *today's* ``person_ids`` is sufficient: a daily row can
        only have changed for someone who was seen today, and every other
        person's weekly row already covers their whole week.

        Two combining rules worth stating, since neither is recoverable from
        the stored daily fields:

        - the distributions are mixed **weighted by ``snapshot_count``**, so a
          busy Monday outweighs one relevé on a quiet Sunday. Exact mixing
          would need each day's total intensity, which the daily row does not
          keep — this is the faithful stand-in, not the same number.
        - ``dominant_intensity`` is the same weighted mean of the dailies'.
          ``snapshot_count`` alone is exact: it is a sum.
        """
        from old.backend.memory.models import EmotionalSummary

        if not person_ids:
            return

        # Lundi de la semaine ISO en cours — le jour que porte la ligne.
        week_start = today - timedelta(days=today.weekday())

        for pid in person_ids:
            days = await sync_to_async(
                lambda p=pid: list(
                    EmotionalSummary.objects.filter(
                        person_id=p, period_type="daily",
                        period_start__gte=week_start, period_start__lte=today,
                    ).order_by("period_start")
                )
            )()
            if not days:
                continue

            distribution: dict[str, float] = {}
            weight_total = 0.0
            intensity_total = 0.0
            snapshot_total = 0
            for day in days:
                weight = float(day.snapshot_count or 0) or 1.0
                for emotion, share in (day.emotion_distribution or {}).items():
                    distribution[emotion] = (
                        distribution.get(emotion, 0.0) + share * weight
                    )
                intensity_total += (day.dominant_intensity or 0.0) * weight
                weight_total += weight
                snapshot_total += day.snapshot_count or 0

            total = sum(distribution.values()) or 1.0
            normalized = {k: round(v / total, 3) for k, v in distribution.items()}
            dominant = max(distribution, key=distribution.get)
            dominant_intensity = round(intensity_total / (weight_total or 1.0), 2)

            trend = await self._compute_emotion_trend(
                pid, normalized, week_start - timedelta(days=7),
                period_type="weekly",
                sub_ratios=[
                    self._valence(d.emotion_distribution or {}) for d in days
                ],
            )

            await sync_to_async(
                lambda p=pid, ws=week_start, d=dominant, di=dominant_intensity,
                       n=normalized, t=trend, sc=snapshot_total: (
                    EmotionalSummary.objects.update_or_create(
                        person_id=p,
                        period_type="weekly",
                        period_start=ws,
                        defaults={
                            "dominant_emotion": d,
                            "dominant_intensity": di,
                            "emotion_distribution": n,
                            "trend": t,
                            "snapshot_count": sc,
                        },
                    )
                )
            )()

        logger.debug(
            "Weekly emotion rollup: %d person(s) for week of %s",
            len(person_ids), week_start,
        )

    def _valence(self, dist: dict) -> float:
        """Positif moins négatif — l'axe sur lequel une tendance se mesure."""
        pos = sum(dist.get(e, 0) for e in self.POSITIVE_EMOTIONS)
        neg = sum(dist.get(e, 0) for e in self.NEGATIVE_EMOTIONS)
        return pos - neg

    async def _compute_emotion_trend(
        self, person_id: str, dist: dict, previous_start, *,
        period_type: str = "daily", sub_ratios: list[float] | None = None,
    ) -> str:
        """Compare a period's emotional distribution against the one before.

        Returns: 'warming', 'cooling', 'volatile', or 'stable'.

        ``sub_ratios`` carries the valence of each sub-period (the days making
        up a week) and is how volatility is measured for anything longer than
        a day. The daily rule — "more than four distinct emotions plus a small
        valence shift" — is a proxy for choppiness that only holds over a few
        hours: **over a week five distinct emotions is the normal case**, so
        reusing it would have stamped "instable" on nearly every weekly row.
        A week is volatile when its *days* disagree, which is a thing we can
        actually measure.
        """
        from old.backend.memory.models import EmotionalSummary

        try:
            prev = await sync_to_async(EmotionalSummary.objects.get)(
                person_id=person_id, period_type=period_type,
                period_start=previous_start,
            )
            delta = self._valence(dist) - self._valence(prev.emotion_distribution)
        except EmotionalSummary.DoesNotExist:
            # Sans période précédente il n'y a pas de tendance à mesurer —
            # mais un écart entre les jours, lui, reste observable.
            delta = 0.0
            if not sub_ratios:
                return "stable"

        if delta > 0.15:
            return "warming"
        if delta < -0.15:
            return "cooling"
        if sub_ratios is not None:
            spread = max(sub_ratios) - min(sub_ratios) if sub_ratios else 0.0
            return "volatile" if spread > cfg_float(
                "memory.weekly_volatile_spread", WEEKLY_VOLATILE_SPREAD,
                mini=0.0, maxi=2.0,
            ) else "stable"
        if len(dist) > 4 and abs(delta) > 0.05:
            return "volatile"
        return "stable"

    # ------------------------------------------------------------------
    # Contradiction checking
    # ------------------------------------------------------------------

    async def _check_contradictions(self, new_content: str) -> None:
        """Check if new connaissance contradicts existing ones.

        Uses vector search to find semantically related connaissances,
        then validates the closest ones with LLM (at most
        MAX_CONTRADICTION_CHECKS). Invalidates contradicted ones.
        """
        from old.backend.memory.models import Connaissance

        try:
            raw = await vector_call(self.vector_store.search_connaissances)(
                new_content, n=5
            )
            if not raw:
                return

            checked = 0
            for r in raw:
                if checked >= cfg_int(
                    "memory.max_contradiction_checks", MAX_CONTRADICTION_CHECKS,
                    mini=0, maxi=10,
                ):
                    break

                try:
                    pk = int(r["id"])
                    conn = await sync_to_async(Connaissance.objects.get)(
                        pk=pk, is_valid=True
                    )
                except (Connaissance.DoesNotExist, ValueError):
                    continue

                # Skip if very similar (duplicate, not contradiction)
                if r.get("distance") is not None and r["distance"] < 0.15:
                    continue

                checked += 1
                try:
                    still_valid, new_confidence = (
                        await self.extractor.check_connaissance_validity(
                            conn.content, new_content
                        )
                    )
                except Exception:
                    logger.warning(
                        "Validity check failed for connaissance #%d", conn.pk
                    )
                    continue

                if not still_valid:
                    conn.is_valid = False
                    await sync_to_async(conn.save)(update_fields=["is_valid"])
                    try:
                        await vector_call(self.vector_store.add_connaissance)(
                            connaissance_id=conn.pk,
                            content=conn.content,
                            metadata=connaissance_metadata(
                                confidence=conn.confidence,
                                is_valid=False,
                            ),
                        )
                    except Exception:
                        logger.warning(
                            "Failed to update ChromaDB for invalidated connaissance #%d",
                            conn.pk, exc_info=True,
                        )
                    logger.info(
                        "Consolidator invalidated connaissance #%d: %s (contradicted by: %s)",
                        conn.pk, conn.content[:80], new_content[:80],
                    )
                # Seulement a la baisse, comme le bridge : remonter la confiance
                # ici annulerait la decroissance que ce meme consolidateur
                # applique par ailleurs.
                elif new_confidence is not None and conn.confidence - new_confidence > 0.05:
                    conn.confidence = new_confidence
                    conn.decayed_at = timezone.now()
                    await sync_to_async(conn.save)(
                        update_fields=["confidence", "decayed_at"],
                    )
                    await self._index(
                        self.vector_store.add_connaissance, "connaissance", conn.pk,
                        connaissance_id=conn.pk, content=conn.content,
                        metadata=connaissance_metadata(
                            confidence=conn.confidence, is_valid=conn.is_valid,
                        ),
                    )

        except Exception as exc:
            degradations.record("consolidator: contradiction check", exc)

    async def _find_similar_souvenir(self, content: str):
        """Un souvenir quasi identique existe-t-il déjà ? Même distance que
        la fusion nocturne (``memory.reorg_dedup_distance``), pour qu'une
        seule idée de « pareil » vive dans le système. ``None`` sur toute
        panne : douter ne doit pas empêcher d'écrire."""
        from old.backend.memory.models import Souvenir

        try:
            distance_max = cfg_float(
                "memory.reorg_dedup_distance", 0.12, mini=0.0, maxi=0.3,
            )
            results = await vector_call(self.vector_store.search_souvenirs)(
                content, n=1, min_importance=0.0,
            )
        except Exception as exc:
            degradations.record("consolidator: recherche de doublon", exc)
            return None
        # Un store simulé ou un retour d'une autre forme = pas de doublon.
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return None
        premier = results[0]
        distance = premier.get("distance")
        if not isinstance(distance, (int, float)) or distance >= distance_max:
            return None
        try:
            return await sync_to_async(Souvenir.objects.get)(pk=int(premier["id"]))
        except Exception:
            return None

    async def _find_similar_connaissance(self, content: str):
        """Check if a similar connaissance already exists via vector search."""
        from old.backend.memory.models import Connaissance

        results = await vector_call(self.vector_store.search_connaissances)(content, n=1)
        if results and results[0]["distance"] is not None and results[0]["distance"] < 0.15:
            # Very similar — treat as duplicate
            try:
                pk = int(results[0]["id"])
                return await sync_to_async(Connaissance.objects.get)(pk=pk)
            except (Connaissance.DoesNotExist, ValueError):
                pass
        return None


def _valid_emotion(raw) -> str:
    """Le nom canonique de l'émotion d'un souvenir, ou ``neutral``.

    ``Souvenir.emotion`` est un champ texte libre et le modèle est libre
    d'inventer : un nom hors palette pèse une charge nulle au rappel et ne
    peut classer aucun rêve. Une extraction *sans* émotion n'est pas une
    panne — seul un nom inconnu en est une.
    """
    if not raw:
        return Emotion.NEUTRAL.value
    try:
        return Emotion(str(raw).strip().lower()).value
    except ValueError as exc:
        degradations.record("consolidator: emotion de souvenir inconnue", exc)
        return Emotion.NEUTRAL.value


def _merge_entities(extracted: list, interlocutors: list) -> list:
    """Union of extractor-named entities and the people actually present.

    Order matters only for readability; de-duplication is by pk because the
    two sources routinely produce the same row (someone who says their own
    name mid-conversation is both).
    """
    merged = list(extracted)
    seen = {e.pk for e in merged}
    for entity in interlocutors:
        if entity.pk not in seen:
            seen.add(entity.pk)
            merged.append(entity)
    return merged
