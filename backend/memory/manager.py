import logging

from asgiref.sync import sync_to_async
from django.conf import settings
from utils.degradation import degradations

logger = logging.getLogger(__name__)


class MemoryUnavailable(RuntimeError):
    """La mémoire longue ne peut pas exister — le démarrage est refusé.

    Type propre plutôt que ``RuntimeError`` nu : le lifespan ASGI laisse
    remonter, et un exploitant qui lit la trace doit voir *ce qui* a refusé,
    pas une erreur générique au milieu du démarrage.
    """


class MemoryManager:
    """Orchestrates short-term (in-memory), vector (ChromaDB), and
    structured (Django ORM) memory systems."""

    def __init__(self):
        from configs.service import config_service
        self.short_term: list[dict] = []
        self.max_short_term = config_service.get("memory.short_term_limit")
        config_service.on_change(
            "memory.short_term_limit",
            lambda k, v: setattr(self, "max_short_term", v),
        )
        self.conversation = None
        self._initialized = False
        # Lu par la couche prompt : sans ça, une mémoire longue en panne est
        # indistinguable de « rien à dire », donc Mika simule l'amnésie au
        # lieu de pouvoir dire qu'elle ne peut pas y accéder. Dit « le dernier
        # rappel tenté a échoué », pas « les deux voies sont mortes ».
        self.recall_unavailable = False
        # Résumé roulant du fil (compaction) — chargé à la réhydratation,
        # réécrit par fold_into_summary. "" tant qu'aucune passe n'a tourné.
        self.conversation_summary = ""
        # A restart within this window reattaches to the conversation in
        # progress instead of opening a new one, so an exchange interrupted
        # by a restart stays one exchange.
        self.resume_window_minutes = 120

        # Contextual memory components (initialized async)
        self.vector_store = None
        self.extractor = None
        self.consolidator = None
        self.retriever = None
        # Indexeur épisodique (étage 1) — vit et meurt avec le vector store.
        self.episodic = None
        # Compacteur du fil — indépendant de chromadb (LLM + ORM seulement).
        self.compactor = None

    @staticmethod
    def _refuser_ou_degrader(raison: str, cause: Exception) -> None:
        """Refuse le démarrage quand la mémoire longue ne peut pas exister.

        Sans mémoire longue il n'y a plus ni souvenir, ni connaissance, ni
        engagement, ni self-narrative, ni fiche de personne, ni réorganisation
        nocturne — pour toute la durée du processus, puisque ``_initialized``
        était posé quand même et qu'aucune reprise n'est prévue. Côté
        conversation l'aveu était honnête (« je ne retrouve pas ») ; côté
        exploitant il n'y avait qu'une ligne de log, et l'installation
        paraissait tourner normalement pendant qu'elle perdait sa journée.

        Une Mika sans mémoire longue n'est pas une Mika dégradée, c'est une
        autre : mieux vaut ne pas démarrer que démarrer amnésique sans le dire.
        Le repli explicite reste possible via ``MEMORY_REQUIRE_VECTOR_STORE=0``
        dans ``.env`` — dans ``.env`` et non dans le tableau de bord, parce
        qu'un processus qui refuse de démarrer ne peut pas servir la page qui
        contiendrait le réglage.
        """
        if not getattr(settings, "MEMORY_REQUIRE_VECTOR_STORE", True):
            logger.warning(
                "Mémoire longue indisponible (%s) — démarrage en mode basique, "
                "explicitement autorisé par MEMORY_REQUIRE_VECTOR_STORE=0.",
                raison,
            )
            return
        raise MemoryUnavailable(
            f"Démarrage refusé : {raison}.\n"
            "Sans magasin vectoriel, Mika démarre sans souvenirs, sans "
            "connaissances, sans engagements et sans fiches de personnes, "
            "définitivement jusqu'au prochain redémarrage.\n"
            "À vérifier : le dossier CHROMA_PERSIST_DIR est-il lisible et "
            "non corrompu ? le modèle EMBEDDING_MODEL est-il téléchargé ? "
            "chromadb est-il installé (pip install -r backend/requirements.txt) ?\n"
            "Pour démarrer quand même en mémoire basique, poser "
            "MEMORY_REQUIRE_VECTOR_STORE=0 dans .env."
        ) from cause

    async def initialize(self):
        """Initialize all memory subsystems."""
        if self._initialized:
            return

        await self._resume_or_open_conversation()
        await self._rehydrate_short_term()

        # Initialize contextual memory (requires chromadb, not yet compatible with Python 3.14+)
        try:
            import chromadb  # noqa: F401 — test import before loading subsystems

            from memory.extraction import MemoryExtractor
            from memory.retrieval import MemoryRetriever
            from memory.storage import MemoryConsolidator, VectorStore

            self.vector_store = VectorStore()
            self.extractor = MemoryExtractor()
            self.retriever = MemoryRetriever(self.vector_store)
            self.consolidator = MemoryConsolidator(self.extractor, self.vector_store)
            await self.consolidator.start()

            # Étage épisodique : les échanges bruts, trouvables le jour même.
            # Dans le même try que le reste — sans chromadb il n'existe pas.
            from configs.service import config_service
            from memory.episodic import EpisodicIndexer
            if config_service.get("memory.episodic_enabled"):
                self.episodic = EpisodicIndexer(self.vector_store)
                await self.episodic.start()

            logger.info("Contextual memory system initialized")
        except ImportError as exc:
            import sys
            if sys.version_info >= (3, 14):
                raison = (
                    f"chromadb ne s'importe pas sous Python {sys.version.split()[0]}"
                )
            else:
                raison = "chromadb n'est pas installé"
            degradations.record("memoire: vector store indisponible", exc)
            self._refuser_ou_degrader(raison, exc)
        except Exception as exc:
            degradations.record("memoire: vector store indisponible", exc)
            self._refuser_ou_degrader(
                f"le magasin vectoriel n'a pas démarré ({exc})", exc,
            )

        # Compaction du fil — hors du try chromadb : elle n'a besoin que de
        # l'ORM et du rôle COMPACTION (non mappé = no-op à chaque tick).
        try:
            from memory.compaction import ConversationCompactor
            self.compactor = ConversationCompactor()
            await self.compactor.start()
        except Exception:
            logger.exception("Failed to start conversation compactor")

        self._initialized = True

    # ── Startup: continuity across restarts ──────────────────────

    async def _resume_or_open_conversation(self) -> None:
        """Reattach to the conversation in progress, or start a new one.

        Always creating a fresh Conversation split one continuous exchange
        across a row per boot, so nothing downstream could tell "we were in
        the middle of talking" from "this is a new session".
        """
        from datetime import timedelta

        from django.utils import timezone

        from memory.models import Conversation, Message

        cutoff = timezone.now() - timedelta(minutes=self.resume_window_minutes)

        def _find_recent():
            last = Message.objects.order_by("-pk").first()
            if last is None or last.created_at < cutoff:
                return None
            return Conversation.objects.filter(pk=last.conversation_id).first()

        existing = await sync_to_async(_find_recent)()
        if existing is not None:
            self.conversation = existing
            logger.info(
                "Memory resumed conversation_id=%d (activity within %dmin)",
                existing.pk, self.resume_window_minutes,
            )
            return

        self.conversation = await Conversation.objects.acreate()
        logger.info("Memory initialized, conversation_id=%d", self.conversation.pk)

    async def _rehydrate_short_term(self) -> None:
        """Reload the tail of the conversation into the RAM buffer.

        ``get_conversation_context()`` is the only history the LLM sees. It
        was never populated from the DB, so a restart mid-chat was total
        conversational amnesia — "et le deuxième alors ?" landed on nothing —
        even though the rows were sitting right there, and even though her
        *mood* toward the person was correctly restored from snapshots.
        Internal scaffolding is skipped: it was never part of the dialogue.
        """
        from memory.models import Message

        if not self.conversation:
            return

        def _load():
            from memory.models import ConversationSummary

            summary_row = (
                ConversationSummary.objects.filter(conversation=self.conversation)
                .first()
            )
            floor_id = summary_row.last_message_id if summary_row else 0
            rows = list(
                Message.objects.filter(
                    conversation=self.conversation, pk__gt=floor_id,
                )
                # Machinery, whichever side it sits on: the scaffolding prompt
                # of an internal trigger, and the fallback text a failed turn
                # returned. Neither was said by anyone, so neither belongs in
                # the history the model is handed after a restart.
                .exclude(is_internal=True)
                .order_by("-pk")
                # `person_id` voyage avec la ligne : le tampon est partage par
                # tout le monde (« quelqu'un dans une piece entend ce qui s'y
                # dit »), donc savoir qui a dit quoi est la seule chose qui
                # permette au prompt d'arbitrer. Sans lui, apres un
                # redemarrage comme avant, tout le monde redevient « User: ».
                # `id` rend l'entree repliable par la compaction.
                .values("id", "role", "content", "person_id")[: self.max_short_term]
            )
            rows.reverse()
            return rows, (summary_row.content if summary_row else "")

        try:
            self.short_term, self.conversation_summary = await sync_to_async(_load)()
        except Exception:
            logger.exception("Short-term rehydration failed — starting empty")
            self.short_term = []
            self.conversation_summary = ""
            return

        if self.short_term:
            logger.info(
                "Short-term memory rehydrated: %d messages", len(self.short_term)
            )

    async def add_message(
        self,
        role: str,
        content: str,
        source: str = "frontend",
        person_id: str = "",
        attachments_meta: list[dict] | None = None,
        is_internal: bool = False,
        awaiting_reply: bool = False,
    ) -> int | None:
        """Add to short-term memory and persist via ORM.

        Returns the persisted ``Message.pk``, or ``None`` when nothing was
        written (memory not initialized yet, or the insert failed). That id
        is the frontend's synchronisation cursor: ``Message`` rows are
        append-only with a monotonic pk, so "everything after N" is the
        whole catch-up query a reconnecting client needs. Returning it here
        rather than re-querying afterwards keeps the answer exact under the
        six background loops writing concurrently.

        ``attachments_meta`` is stored alongside the Message so retrieval
        and the consolidator can see what non-text parts came with the
        conversation turn (images, audio, files — descriptors only, not
        bytes; raw bytes live in the media store via pipeline.media).

        An ``is_internal`` message is stored but kept **out of the RAM
        buffer**, which is what ``_rehydrate_short_term`` already does after
        a restart. The two disagreed: the same conversation showed Mika a
        greeting brief before a restart and not after. It matters more now
        that a failed turn persists its fallback — a run of timeouts would
        otherwise fill the history the model reads with sentences she never
        said, and invite her to say them again.
        """
        ram_entry = None
        if not is_internal:
            # `person_id` etait recu puis jete : le tampon ne gardait que le
            # role, donc le prompt rendait chaque tour « User: » sans pouvoir
            # dire lequel venait de qui. Il est conserve tel quel (un handle,
            # pas un nom) — la traduction en libelle lisible appartient a la
            # couche identite, pas a la memoire.
            ram_entry = {"role": role, "content": content, "person_id": person_id}
            self.short_term.append(ram_entry)
            if len(self.short_term) > self.max_short_term:
                self.short_term = self.short_term[-self.max_short_term :]

        logger.debug(
            "Memory add_message: role=%s source=%s person=%s short_term=%d content=%.60s",
            role, source, person_id, len(self.short_term), content,
        )

        if self._initialized and self.conversation:
            try:
                from memory.models import Message

                row = await Message.objects.acreate(
                    conversation=self.conversation,
                    role=role,
                    content=content,
                    source=source,
                    person_id=person_id,
                    attachments_meta=attachments_meta or [],
                    is_internal=is_internal,
                    awaiting_reply=awaiting_reply,
                )
                # L'id rend l'entrée « repliable » par la compaction (une
                # entrée sans id — écriture ratée, mémoire non initialisée —
                # n'est simplement jamais repliée, ce qui est sûr).
                if ram_entry is not None:
                    ram_entry["id"] = row.pk
                return row.pk
            except Exception:
                logger.exception("Failed to persist message to DB")
        return None

    def get_conversation_context(self) -> list[dict]:
        """Get short-term conversation history for Claude."""
        return list(self.short_term)

    def get_conversation_summary(self) -> str:
        """Résumé roulant du fil (compaction), "" si aucun."""
        return self.conversation_summary

    async def fold_into_summary(self, new_summary: str, last_id: int) -> bool:
        """Applique une passe de compaction : upsert du résumé, puis trim.

        Le trim du buffer ne se fait **qu'après** l'écriture réussie du
        résumé — dans l'autre ordre, une écriture ratée perdrait le verbatim
        des deux côtés. Les entrées sans id (jamais persistées) survivent
        toujours. Appelé uniquement par le compactor.
        """
        if not new_summary or not self.conversation:
            return False
        from memory.models import ConversationSummary

        def _upsert():
            folded = sum(
                1 for m in self.short_term
                if isinstance(m.get("id"), int) and m["id"] <= last_id
            )
            obj, _created = ConversationSummary.objects.update_or_create(
                conversation=self.conversation,
                defaults={"content": new_summary, "last_message_id": last_id},
            )
            ConversationSummary.objects.filter(pk=obj.pk).update(
                folded_count=obj.folded_count + folded,
            )

        try:
            await sync_to_async(_upsert)()
        except Exception:
            logger.exception("fold_into_summary: écriture du résumé échouée")
            return False

        self.conversation_summary = new_summary
        self.short_term = [
            m for m in self.short_term
            if not (isinstance(m.get("id"), int) and m["id"] <= last_id)
        ]
        return True

    async def get_memory_context(
        self, query: str, person_id: str = "", disclose_others: bool = True,
    ) -> str:
        """Retrieve relevant long-term memories formatted for the system prompt.

        If person_id is provided, results are boosted for memories
        related to that person (but not exclusively filtered — Mika
        should still recall general knowledge).
        """
        if not self.retriever:
            self.recall_unavailable = True
            return ""
        try:
            bloc = await self.retriever.retrieve(
                query, person_id=person_id, disclose_others=disclose_others,
            )
        except Exception as exc:
            degradations.record("rappel memoire simple", exc)
            logger.exception("Memory retrieval error")
            self.recall_unavailable = True
            return ""
        self.recall_unavailable = False
        return bloc

    async def get_memory_context_multi(
        self,
        queries: list[str],
        person_id: str = "",
        extra_exchanges: list | None = None,
        salience_boost: float = 0.0,
        disclose_others: bool = True,
    ) -> str:
        """Rappel multi-requêtes (plan de préparation, observations de la
        conscience) — un seul bloc formaté, fusion par pertinence.

        ``salience_boost`` (charge émotionnelle du tour, plan de préparation)
        monte les poids émotion/humeur du re-ranking pour ce tour."""
        if not self.retriever:
            self.recall_unavailable = True
            return ""
        try:
            bloc = await self.retriever.retrieve_multi(
                queries, person_id=person_id, extra_exchanges=extra_exchanges,
                salience_boost=salience_boost, disclose_others=disclose_others,
            )
        except Exception as exc:
            degradations.record("rappel memoire multi", exc)
            logger.exception("Memory multi-retrieval error")
            self.recall_unavailable = True
            return ""
        self.recall_unavailable = False
        return bloc

    # ── Souvenir operations (used by Conscience) ───────────────────

    async def create_souvenir(
        self, content: str, emotion: str = "neutral", importance: float = 1.0
    ):
        """Create a Souvenir and index it in ChromaDB.

        Returns the created Souvenir or None on failure.
        """
        from memory.models import Souvenir
        from django.utils import timezone

        try:
            souvenir = await sync_to_async(Souvenir.objects.create)(
                content=content,
                emotion=emotion,
                importance=importance,
                occurred_at=timezone.now(),
            )

            if self.vector_store:
                from memory.storage.vector_store import souvenir_metadata, vector_call
                await vector_call(self.vector_store.add_souvenir)(
                    souvenir_id=souvenir.pk,
                    content=souvenir.content,
                    # occurred_at inclus : les souvenirs créés ici (conscience,
                    # digestion nocturne) étaient invisibles à tout futur
                    # filtre temporel sur les métadonnées.
                    metadata=souvenir_metadata(
                        importance=souvenir.importance,
                        emotion=souvenir.emotion,
                        occurred_at=souvenir.occurred_at.isoformat(),
                    ),
                )

            logger.info(
                "Created souvenir #%d (importance=%.1f)",
                souvenir.pk, souvenir.importance,
            )
            return souvenir
        except Exception:
            logger.exception("Failed to create souvenir")
            return None

    async def boost_souvenir(self, souvenir_id: int, boost: float) -> None:
        """Increase a souvenir's importance. Capped at 1.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            souvenir.importance = min(1.0, souvenir.importance + boost)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
        except Exception:
            logger.warning("boost_souvenir failed for #%d", souvenir_id, exc_info=True)
            return
        await self.reindex_souvenirs([souvenir_id])

    async def reduce_souvenir(self, souvenir_id: int, reduction: float) -> None:
        """Decrease a souvenir's importance. Floored at 0.0."""
        from memory.models import Souvenir

        try:
            souvenir = await sync_to_async(Souvenir.objects.get)(pk=souvenir_id)
            souvenir.importance = max(0.0, souvenir.importance - reduction)
            await sync_to_async(souvenir.save)(update_fields=["importance"])
        except Exception:
            logger.warning("reduce_souvenir failed for #%d", souvenir_id, exc_info=True)
            return
        await self.reindex_souvenirs([souvenir_id])

    async def reindex_souvenirs(self, pks) -> None:
        """Réaligne les métadonnées ChromaDB de ces souvenirs sur la ligne ORM.

        L'``importance`` est une métadonnée ChromaDB ET le filtre du rappel
        (``search_souvenirs(min_importance=…)``). Un écrivain qui ne touche
        que la ligne ORM laisse le vecteur à l'ancienne valeur : un souvenir
        endormi (0.02) que la Conscience vient de ranimer restait invisible au
        rappel spontané — précisément ce que le boost promettait. Seule la
        passe de décroissance ré-indexait ; tout écrivain d'importance passe
        désormais ici (boost, réduction, boost par thème, fusion nocturne).

        Pourquoi ré-indexer plutôt que retirer le pré-filtre ChromaDB et
        filtrer côté ORM : l'oubli n'efface plus, donc les lignes endormies
        deviennent la majorité d'un magasin ancien, et sans pré-filtre elles
        rempliraient la page de candidats (n × multiplicateur) que le rappel
        n'aurait plus qu'à jeter — un rappel qui s'amincit avec l'âge de
        l'installation. C'est la métadonnée qui doit suivre, pas le filtre
        qui doit tomber.

        Best-effort : la ligne ORM reste la vérité ; un ré-index perdu coûte
        du rappel jusqu'à la prochaine passe de décroissance, jamais le
        souvenir.
        """
        from memory.models import Souvenir
        from memory.storage.vector_store import souvenir_metadata, vector_call

        pks = [pk for pk in (pks or ()) if pk is not None]
        if not pks or not self.vector_store:
            return

        def _lire() -> list[dict]:
            rows = Souvenir.objects.filter(pk__in=pks).prefetch_related("themes")
            return [
                {
                    "souvenir_id": s.pk,
                    "content": s.content,
                    "metadata": souvenir_metadata(
                        importance=s.importance,
                        emotion=s.emotion,
                        occurred_at=(s.occurred_at or s.created_at).isoformat(),
                        themes=[t.name for t in s.themes.all()],
                    ),
                }
                for s in rows
            ]

        try:
            entries = await sync_to_async(_lire)()
            if entries:
                await vector_call(self.vector_store.add_souvenirs)(entries)
        except Exception as exc:
            degradations.record("memoire: reindex apres ecriture d'importance", exc)

    async def boost_souvenirs_by_themes(
        self, themes: list[str], boost: float = 0.1
    ) -> int:
        """Boost importance of souvenirs linked to given themes.

        Returns the number of souvenirs affected.

        Selection et ecritures tiennent dans un **seul** aller-retour de
        thread : `sync_to_async` est `thread_sensitive` par defaut, donc un
        appel par ligne faisait jusqu'a 21 passages serialises sur l'unique
        executeur que se partagent les six boucles de fond et tout le
        chemin WebSocket. Le SQL emis est le meme, ligne par ligne.
        """
        from memory.models import Souvenir

        if not themes:
            return 0

        def _booster() -> list[int]:
            souvenirs = list(
                Souvenir.objects.filter(
                    themes__name__in=themes,
                    importance__lt=1.0,
                ).distinct()[:20]
            )
            for s in souvenirs:
                s.importance = min(1.0, s.importance + boost)
                s.save(update_fields=["importance"])
            return [s.pk for s in souvenirs]

        try:
            pks = await sync_to_async(_booster)()
            count = len(pks)
            await self.reindex_souvenirs(pks)

            if count:
                logger.info(
                    "Boosted %d souvenirs by %.2f (themes: %s)",
                    count, boost, themes,
                )
            return count
        except Exception:
            logger.warning("boost_souvenirs_by_themes failed", exc_info=True)
            return 0

    async def get_important_souvenirs(
        self, min_importance: float = 0.5, limit: int = 5
    ) -> list:
        """Get recent important souvenirs."""
        from memory.models import Souvenir

        try:
            return await sync_to_async(
                lambda: list(
                    Souvenir.objects.filter(importance__gte=min_importance)
                    .order_by("-created_at")[:limit]
                )
            )()
        except Exception as exc:
            degradations.record("memory.manager.get_important_souvenirs", exc)
            logger.debug("get_important_souvenirs failed", exc_info=True)
            return []

    # ── Connaissance operations (used by Conscience) ─────────────

    async def create_connaissance(
        self, content: str, confidence: float = 1.0
    ):
        """Cree une Connaissance et l'indexe dans ChromaDB.

        Pendant de `create_souvenir`. La remémoration (retriever du prompt,
        outil `memory_search`) part exclusivement du vectoriel : une ligne
        ecrite en base sans indexation est definitivement irrecuperable.

        Retourne la Connaissance creee ou None en cas d'echec.
        """
        from memory.models import Connaissance

        try:
            connaissance = await sync_to_async(Connaissance.objects.create)(
                content=content,
                confidence=confidence,
                is_valid=True,
            )

            if self.vector_store:
                # `search_connaissances` filtre sur `is_valid` cote ChromaDB :
                # sans cette metadonnee la ligne ne serait jamais servie.
                from memory.storage.vector_store import connaissance_metadata
                await sync_to_async(self.vector_store.add_connaissance)(
                    connaissance_id=connaissance.pk,
                    content=connaissance.content,
                    metadata=connaissance_metadata(
                        confidence=connaissance.confidence,
                        is_valid=True,
                    ),
                )

            logger.info(
                "Created connaissance #%d (confidence=%.1f)",
                connaissance.pk, connaissance.confidence,
            )
            return connaissance
        except Exception:
            logger.exception("Failed to create connaissance")
            return None

    async def invalidate_connaissance(
        self, connaissance_id: int, reason: str = ""
    ) -> None:
        """Mark a knowledge fact as invalid."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.is_valid = False
            await sync_to_async(conn.save)(update_fields=["is_valid"])
            # Le filtrage de validite de la recherche semantique se fait sur la
            # metadonnee ChromaDB (`where={"is_valid": True}`), pas sur la ligne
            # ORM : sans reindexation la connaissance continuerait d'etre servie
            # au prompt a chaque tour. Meme geste que le consolidateur.
            if self.vector_store:
                from memory.storage.vector_store import connaissance_metadata, vector_call
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
                        connaissance_id, exc_info=True,
                    )
            logger.info(
                "Invalidated connaissance #%d: %s (reason: %s)",
                connaissance_id, conn.content[:60], reason,
            )
        except Exception:
            logger.warning(
                "invalidate_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def reinforce_connaissance(
        self, connaissance_id: int, boost: float = 0.1
    ) -> None:
        """Increase confidence of a knowledge fact."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.confidence = min(1.0, conn.confidence + boost)
            await sync_to_async(conn.save)(update_fields=["confidence"])
        except Exception:
            logger.warning(
                "reinforce_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def update_connaissance_confidence(
        self, connaissance_id: int, confidence: float
    ) -> None:
        """Set the confidence of a connaissance to a specific value."""
        from memory.models import Connaissance

        try:
            conn = await sync_to_async(Connaissance.objects.get)(pk=connaissance_id)
            conn.confidence = max(0.0, min(1.0, confidence))
            await sync_to_async(conn.save)(update_fields=["confidence"])
        except Exception:
            logger.warning(
                "update_connaissance_confidence failed for #%d",
                connaissance_id, exc_info=True,
            )

    async def get_valid_connaissance(self, connaissance_id: int):
        """Get a valid Connaissance by ID, or None if not found/invalid."""
        from memory.models import Connaissance

        try:
            return await sync_to_async(Connaissance.objects.get)(
                pk=connaissance_id, is_valid=True
            )
        except Connaissance.DoesNotExist:
            return None
        except Exception as exc:
            degradations.record("memory.manager.get_valid_connaissance", exc)
            logger.debug(
                "get_valid_connaissance failed for #%d",
                connaissance_id, exc_info=True,
            )
            return None

    async def search_related_connaissances(
        self, text: str, n: int = 5
    ) -> list[dict]:
        """Semantic search for connaissances related to text via ChromaDB."""
        if not self.vector_store:
            return []
        from memory.storage.vector_store import vector_call
        try:
            raw = await vector_call(self.vector_store.search_connaissances)(text, n=n)
            return await self._keep_valid_connaissances(raw)
        except Exception as exc:
            degradations.record("memory.manager.search_related_connaissances", exc)
            logger.debug("search_related_connaissances failed", exc_info=True)
            return []

    async def _keep_valid_connaissances(self, rows: list[dict]) -> list[dict]:
        """Ecarte les lignes dont l'ORM dit qu'elles ne sont plus valides.

        ChromaDB filtre sur sa propre metadonnee : une connaissance invalidee
        avant que l'invalidation ne reindexe (ou dont la reindexation a echoue)
        y reste marquee valide pour toujours, et le contenu brut du vecteur est
        servi tel quel a `memory_search` comme a `who_is_concerned`. Une seule
        requete groupee, l'ordre de pertinence est preserve.
        """
        from memory.models import Connaissance

        if not rows:
            return rows

        pks = []
        for r in rows:
            try:
                pks.append(int(r["id"]))
            except (ValueError, KeyError, TypeError):
                continue
        if not pks:
            return rows

        valid_pks = await sync_to_async(
            lambda: list(
                Connaissance.objects.filter(pk__in=pks, is_valid=True)
                .values_list("pk", flat=True)
            )
        )()
        valid = {str(pk) for pk in valid_pks}
        return [r for r in rows if str(r.get("id")) in valid]

    async def search_related_souvenirs(self, text: str, n: int = 5) -> list[dict]:
        """Semantic search for souvenirs related to text via ChromaDB."""
        if not self.vector_store:
            return []
        from memory.storage.vector_store import vector_call
        try:
            return await vector_call(self.vector_store.search_souvenirs)(text, n=n)
        except Exception as exc:
            degradations.record("memory.manager.search_related_souvenirs", exc)
            logger.debug("search_related_souvenirs failed", exc_info=True)
            return []

    def clear_short_term(self):
        self.short_term.clear()

    async def shutdown(self):
        """Graceful shutdown: force final consolidation and stop background tasks."""
        if self.compactor:
            try:
                await self.compactor.stop()
            except Exception:
                logger.exception("Error stopping conversation compactor")
        if self.episodic:
            try:
                await self.episodic.stop()
            except Exception:
                logger.exception("Error stopping episodic indexer")
        if self.consolidator:
            try:
                # La boucle AVANT la passe finale : `stop()` attend un tick en
                # cours au lieu de l'annuler, et la passe forcée ne trouve
                # alors que ce qui est arrivé depuis — jamais la fenêtre que le
                # tick était en train d'extraire.
                await self.consolidator.stop()
                await self.consolidator.force_consolidate()
                logger.info("Memory consolidator shut down cleanly")
            except Exception:
                logger.exception("Error during memory shutdown")


memory_manager = MemoryManager()
