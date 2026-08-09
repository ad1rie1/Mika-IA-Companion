import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from memory.storage.vector_store import VectorStore, vector_call
from utils.degradation import degradations

logger = logging.getLogger(__name__)


# ── Saillance du rappel — l'humain se souvient par la charge, pas la distance ─
#
# L'ancien classement était pertinence lexicale × récence × personne. L'humain,
# lui, rappelle d'abord ce qui l'a *marqué* : l'importance et la charge
# émotionnelle. Ces deux champs existaient déjà sur le souvenir mais ne
# servaient qu'à *filtrer* (min_importance), jamais à *classer*. On les promeut
# en poids, plus une congruence d'humeur douce (rappel humeur-congruent).
#
# Tout est PUR et injecté (humeur + poids en paramètres) : testable sans
# emotion_engine ni config, et applicable partout (conversation, conscience).

@dataclass(frozen=True)
class _SalienceWeights:
    importance: float = 0.6
    emotion: float = 0.6
    mood: float = 0.3
    # Amortissement de la congruence quand l'humeur est négative : sinon
    # « triste → souvenirs tristes → plus triste » double la rumination.
    mood_negative_damp: float = 0.5


def _emotional_charge(emotion: str) -> float:
    """Charge émotionnelle d'un souvenir ∈ [0,1] : la norme de son ancre PAD,
    normalisée. 0 pour ``neutral`` / inconnu — l'anodin ne surnage pas."""
    try:
        from emotion import pad
        from emotion.types import Emotion

        anchor = pad.EMOTION_ANCHORS.get(Emotion(emotion))
        if not anchor:
            return 0.0
        return min(1.0, pad.norm(anchor) / pad._MAX_ANCHOR_NORM)
    except Exception:
        return 0.0


def _mood_congruence(mood_pad, emotion: str) -> float:
    """Congruence ∈ [0,1] entre l'humeur courante (PAD) et l'émotion d'un
    souvenir — cosinus des vecteurs PAD ramené en [0,1]. Renvoie 0.5 (neutre,
    sans effet) dès que l'humeur ou l'émotion est neutre/inconnue."""
    try:
        from emotion import pad
        from emotion.types import Emotion

        anchor = pad.EMOTION_ANCHORS.get(Emotion(emotion))
        if not anchor or mood_pad is None:
            return 0.5
        nm, na = pad.norm(mood_pad), pad.norm(anchor)
        if nm < 1e-6 or na < 1e-6:
            return 0.5
        cos = pad.dot(mood_pad, anchor) / (nm * na)   # ∈ [-1, 1]
        return (cos + 1.0) / 2.0                        # → [0, 1]
    except Exception:
        return 0.5


class MemoryRetriever:
    """Retrieves relevant memories for a given query and formats them
    as a context block for the Claude system prompt.

    Supports:
    - person_id boosting: memories involving the current person rank higher
    - recency bias: recent memories are boosted over old ones
    """

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    async def retrieve(self, query: str, person_id: str = "") -> str:
        """Retrieve and format relevant memories for a user message."""
        return await self.retrieve_multi([query], person_id=person_id)

    async def retrieve_multi(
        self,
        queries: list[str],
        person_id: str = "",
        extra_exchanges: list | None = None,
        salience_boost: float = 0.0,
    ) -> str:
        """Rappel multi-requêtes — le chemin unique du bloc mémoire.

        1. Chaque requête interroge ChromaDB (souvenirs + connaissances,
           en parallèle) ; les pages sont fusionnées par id, distance min.
        2. Voie épisodique : les échanges bruts de la *même identité* que
           l'interlocuteur (politique de confidentialité — le verbatim
           d'autrui ne passe pas par le filtre éditorial de la nuit, il ne
           sort donc que pour son propre auteur ; le rappel inter-personnes
           reste réservé aux consommateurs internes via memory.episodic.api).
        3. Enrichissement ORM, re-ranking par SAILLANCE (récence + personne +
           importance + charge émotionnelle + congruence d'humeur), format.

        ``salience_boost`` ∈ [0,1] (plan de préparation) monte les poids
        émotion/humeur quand le tour est émotionnellement chargé.

        La passe de préparation (plan de rappels) et la conscience (résumés
        d'observations) fournissent plusieurs requêtes ; le tour simple en
        fournit une.
        """
        from configs.service import config_service

        queries = [q.strip() for q in (queries or []) if q and q.strip()]
        if not queries:
            return ""

        n_souvenirs = config_service.get("memory.retrieval_souvenirs")
        n_connaissances = config_service.get("memory.retrieval_connaissances")
        min_importance = config_service.get("memory.min_importance")

        # On récupère plus large que nécessaire pour laisser le re-ranking par
        # saillance PROMOUVOIR un souvenir marquant mais lexicalement moins
        # proche : sans vivier élargi, re-classer ne ferait que réordonner du
        # déjà-similaire. `vector_call` sort l'encode CPU du thread ORM partagé.
        fetch_multiplier = self._fetch_multiplier()
        souvenir_pages, connaissance_pages = await asyncio.gather(
            asyncio.gather(*[
                vector_call(self.vector_store.search_souvenirs)(
                    q, n=n_souvenirs * fetch_multiplier, min_importance=min_importance,
                )
                for q in queries
            ]),
            asyncio.gather(*[
                vector_call(self.vector_store.search_connaissances)(
                    q, n=n_connaissances,
                )
                for q in queries
            ]),
        )
        souvenirs_raw = self._merge_pages(souvenir_pages)
        connaissances_raw = self._merge_pages(connaissance_pages)

        # Voie épisodique — la première requête est le message lui-même.
        # ``extra_exchanges`` vient du plan de préparation (intents
        # `echanges_passes`, rappel inter-personnes permis) ; la voie chaude
        # reste restreinte à l'identité de l'interlocuteur.
        exchanges = await self._episodic_lane(queries[0], person_id)
        if extra_exchanges:
            seen = {h.chunk_id for h in exchanges}
            exchanges = exchanges + [
                h for h in extra_exchanges if h.chunk_id not in seen
            ]

        if not souvenirs_raw and not connaissances_raw and not exchanges:
            return ""

        # Enrich with ORM data
        souvenirs = await self._enrich_souvenirs(souvenirs_raw)
        connaissances = await self._enrich_connaissances(connaissances_raw)

        # Re-ranking par saillance. Le boost personne compare des NOMS
        # d'entités — résoudre le handle en nom via la couche identité est ce
        # qui le fait enfin tirer (l'égalité handle/nom ne matchait jamais :
        # `web_6f3e22ccb0ae` n'est le nom de personne). L'humeur courante est
        # lue sans effet de bord (pas de création d'oscillateur).
        boost_name = await self._person_boost_name(person_id)
        mood_pad = self._mood_pad_for(person_id)
        weights = self._salience_weights(boost=salience_boost)
        souvenirs = self._rerank_souvenirs(
            souvenirs, boost_name, mood_pad=mood_pad, weights=weights,
        )

        # Take top N after reranking
        souvenirs = souvenirs[:n_souvenirs]

        # Rappels non-lexicaux — ce que fait l'humain que le cosinus ne fait pas :
        #  · association « ça me rappelle… », ancrée sur les thèmes des hits ;
        #  · intrusion d'un souvenir intense (opt-in), seulement si le tour est
        #    DÉJÀ chargé — jamais à froid.
        exclude_pks = {s["id"] for s in souvenirs if s.get("id")}
        associations = await self._associative_expansion(souvenirs, exclude_pks)
        exclude_pks |= {a["id"] for a in associations if a.get("id")}
        intrusions = await self._importance_intrusion(exclude_pks, salience_boost)

        return self._format_context(
            connaissances, souvenirs, exchanges=exchanges,
            associations=associations, intrusions=intrusions,
            max_chars=self._budget_cap(),
        )

    def _budget_cap(self) -> int:
        """Plafond du bloc mémoire : la part L5 du budget, plancher 4000.

        Sans ``context_window`` déclaré sur le modèle de conversation, le
        budget vaut None et le plancher historique reste seul maître.
        """
        try:
            from ai.budget import budget_for
            from ai.router import AIRole

            budget = budget_for(AIRole.CONVERSATION)
            if budget is not None:
                return budget.l5_chars(floor=self.MAX_CONTEXT_CHARS)
        except Exception as exc:
            degradations.record("prompt: budget memoire", exc)
        return self.MAX_CONTEXT_CHARS

    @staticmethod
    def _fetch_multiplier() -> int:
        """Combien de candidats récupérer par requête, avant re-ranking.

        Plus large que le nombre rendu, pour que la saillance puisse promouvoir
        un souvenir marquant mais moins proche lexicalement. Défaut 3.
        """
        from configs.service import config_service

        try:
            return max(1, int(config_service.get("memory.retrieval_fetch_multiplier")))
        except Exception:
            return 3

    def _salience_weights(self, boost: float = 0.0) -> "_SalienceWeights":
        """Poids de saillance depuis la config (défauts prudents). ``boost``
        ∈ [0,1] (plan de préparation) monte émotion/humeur pour un tour chargé.
        """
        from configs.service import config_service

        def _f(key: str, default: float) -> float:
            try:
                return float(config_service.get(key))
            except Exception:
                return default

        b = max(0.0, min(1.0, boost))
        return _SalienceWeights(
            importance=_f("memory.salience_importance_weight", 0.6),
            emotion=_f("memory.salience_emotion_weight", 0.6) * (1 + b),
            mood=_f("memory.salience_mood_weight", 0.3) * (1 + b),
        )

    @staticmethod
    def _mood_pad_for(person_id: str):
        """Humeur PAD courante de l'interlocuteur, ou ``None`` — lu SANS effet
        de bord (``dict.get`` : ne crée pas d'oscillateur pour un id qu'on ne
        fait que consulter). Jamais fatal : sans humeur, pas de congruence."""
        if not person_id:
            return None
        try:
            from emotion.engine import emotion_engine
            from identity.trust import is_internal_person

            if is_internal_person(person_id):
                return None
            mood = emotion_engine.person_moods.get(person_id)
            return mood.dynamic.position if mood is not None else None
        except Exception as exc:
            degradations.record("prompt: humeur pour saillance", exc)
            return None

    @staticmethod
    def _merge_pages(pages) -> list[dict]:
        """Fusionne des pages ChromaDB par id, en gardant la distance min."""
        merged: dict[str, dict] = {}
        for page in pages:
            for r in page or []:
                rid = str(r.get("id"))
                prev = merged.get(rid)
                if prev is None:
                    merged[rid] = r
                    continue
                d_new, d_old = r.get("distance"), prev.get("distance")
                if d_new is not None and (d_old is None or d_new < d_old):
                    merged[rid] = r
        return sorted(
            merged.values(),
            key=lambda r: r["distance"] if r.get("distance") is not None else 1.0,
        )

    async def _episodic_lane(self, query: str, person_id: str):
        """Échanges bruts de la même identité que l'interlocuteur."""
        from identity.trust import is_internal_person

        if not person_id or is_internal_person(person_id):
            return []
        try:
            from configs.service import config_service
            n_exchanges = int(config_service.get("memory.retrieval_exchanges"))
        except Exception:
            n_exchanges = 3
        if n_exchanges <= 0:
            return []
        try:
            from identity.resolver import identity_resolver
            from memory.episodic import api as episodic_api

            own = await identity_resolver.handles_for_person(person_id)
            handles = sorted({
                h["person_id"] for h in own if h.get("person_id")
            }) or [person_id]
            return await episodic_api.search_exchanges(
                query, handles=handles, n=n_exchanges,
            )
        except Exception as exc:
            degradations.record("prompt: echanges recents", exc)
            return []

    async def _person_boost_name(self, person_id: str) -> str:
        """Nom d'entité de l'interlocuteur, "" si non lié."""
        if not person_id:
            return ""
        try:
            from identity.resolver import identity_resolver

            entity = await identity_resolver.entity_for_person(person_id)
            return entity.name if entity is not None else ""
        except Exception as exc:
            degradations.record("prompt: resolution boost personne", exc)
            return ""

    def _rerank_souvenirs(
        self, souvenirs: list[dict], boost_name: str, *,
        mood_pad=None, weights: "_SalienceWeights | None" = None,
    ) -> list[dict]:
        """Classe les souvenirs par pertinence × récence × personne × SAILLANCE.

        La saillance (importance, charge émotionnelle, congruence d'humeur)
        fait enfin remonter « ce qui a compté » et pas seulement « ce qui
        ressemble » — l'humain rappelle par la charge, pas par la distance.

        Fonction **pure** : ``mood_pad`` (humeur PAD courante) et ``weights``
        sont injectés, donc testable sans ``emotion_engine`` ni config.
        ``boost_name`` est un *nom d'entité* (résolu via la couche identité),
        pas un handle. ``_score`` n'est qu'une clé de tri : plus de plafond à
        1.0, qui saturait et effaçait précisément les écarts de saillance.
        """
        w = weights or _SalienceWeights()
        now = timezone.now()

        for s in souvenirs:
            score = s.get("relevance", 0.5)

            # Récence (inchangé) — multiplicatif.
            occurred = s.get("occurred_at")
            if occurred:
                age_hours = (now - occurred).total_seconds() / 3600
                if age_hours < 1:
                    score *= 1.5
                elif age_hours < 24:
                    score *= 1.3
                elif age_hours < 168:
                    score *= 1.1

            # Personne (inchangé) — égalité EXACTE de nom (pas de "john"⊂"johnathan").
            if boost_name:
                bl = boost_name.lower()
                for entity in s.get("entities", []):
                    if entity.lower() == bl:
                        score *= 1.4
                        break

            # Importance : de simple filtre à POIDS de rang.
            importance = max(0.0, min(1.0, float(s.get("importance") or 0.0)))
            score *= (1 + w.importance * importance)

            # Charge émotionnelle : mémoire flashbulb (le marquant surnage).
            score *= (1 + w.emotion * _emotional_charge(s.get("emotion") or "neutral"))

            # Congruence d'humeur : douce, amortie en humeur négative (anti-spirale).
            if mood_pad is not None:
                w_mood = w.mood
                if mood_pad[0] < 0:
                    w_mood *= w.mood_negative_damp
                cong = _mood_congruence(mood_pad, s.get("emotion") or "neutral")
                score *= (1 + w_mood * (cong - 0.5) * 2)

            s["_score"] = score

        souvenirs.sort(key=lambda s: s.get("_score", 0), reverse=True)
        return souvenirs

    @staticmethod
    def _pk_of(raw: dict) -> int | None:
        """Identifiant ChromaDB -> pk ORM, ou None si la ligne n'en porte pas."""
        try:
            return int(raw["id"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    async def _load_by_pk(queryset, pks: list[int]) -> dict | None:
        """Charge en UNE requete les lignes demandees, avec leurs M2M.

        Retourne ``{pk: (ligne, themes, entities)}``, ou ``None`` si le
        chargement lui-meme a echoue (base verrouillee, table absente) — le
        cas ou l'appelant doit replier *toute* la page sur ChromaDB, a
        distinguer d'une ligne simplement absente du resultat.

        Les M2M se lisent via ``.all()``, la seule forme qui consomme le cache
        de ``prefetch_related`` : ``values_list()`` rechaine le queryset
        (``_result_cache`` remis a None) et refait la requete, ce qui rendait
        le prefetch purement decoratif.
        """
        if not pks:
            return {}

        def _charger() -> dict:
            rows = queryset.filter(pk__in=pks).prefetch_related("themes", "entities")
            return {
                row.pk: (
                    row,
                    [t.name for t in row.themes.all()],
                    [e.name for e in row.entities.all()],
                )
                for row in rows
            }

        try:
            return await sync_to_async(_charger)()
        except Exception:
            return None

    async def _enrich_souvenirs(self, raw_results: list[dict]) -> list[dict]:
        """Load full Souvenir data from ORM.

        Une seule requete pour toute la page ChromaDB, dans un seul saut
        ``sync_to_async``. Ligne par ligne, cela coutait cinq requetes et trois
        sauts de thread par souvenir — serialises sur l'unique executeur
        partage avec les six boucles de fond — soit une centaine de requetes
        par tour de conversation avant meme l'appel LLM.
        """
        from memory.models import Souvenir

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        loaded = await self._load_by_pk(Souvenir.objects.all(), pks)

        # L'ordre ChromaDB est l'ordre de pertinence : on le reconstitue en
        # Python plutot que de le demander a la base.
        enriched = []
        for r in raw_results:
            row = loaded.get(self._pk_of(r)) if loaded is not None else None
            if row is None:
                # Fallback: use ChromaDB data only
                meta = r.get("metadata", {})
                enriched.append({
                    "id": self._pk_of(r),
                    "content": r["content"],
                    "emotion": meta.get("emotion", "neutral"),
                    "importance": meta.get("importance", 0.5),
                    "occurred_at": None,
                    "themes": [],
                    "entities": [],
                    "relevance": 0.5,
                })
                continue

            souvenir, themes, entities = row

            # Compute base relevance from vector distance (lower = more relevant)
            distance = r.get("distance")
            relevance = max(0, 1.0 - (distance or 0.5)) if distance is not None else 0.5

            enriched.append({
                "id": souvenir.pk,
                "content": souvenir.content,
                "emotion": souvenir.emotion,
                "importance": souvenir.importance,
                "occurred_at": souvenir.occurred_at,
                "themes": themes,
                "entities": entities,
                "relevance": relevance,
            })
        return enriched

    # ── Rappels non-lexicaux — ce que le cosinus ne trouvera jamais ──────

    @staticmethod
    def _linked_souvenir_dict(row: dict) -> dict:
        """Ligne ``.values()`` → dict au format attendu par _format_context."""
        return {
            "id": row["id"],
            "content": row["content"],
            "emotion": row.get("emotion", "neutral"),
            "occurred_at": row.get("occurred_at"),
            "importance": row.get("importance", 0.0),
        }

    async def _associative_expansion(
        self, souvenirs: list[dict], exclude_pks: set,
    ) -> list[dict]:
        """« Ça me rappelle… » — souvenirs liés par thème/entité aux meilleurs
        hits déjà retenus. **Ancré** sur ce qui est déjà pertinent (donc pas
        hors-sujet), borné en nombre, et filtré par importance (on ne dredge
        pas de la trivia parce qu'elle partage un thème). Sûr → actif par défaut.
        """
        from configs.service import config_service

        try:
            if not bool(config_service.get("memory.assoc_expansion_enabled")):
                return []
            max_n = int(config_service.get("memory.assoc_expansion_max"))
            min_imp = float(config_service.get("memory.assoc_min_importance"))
        except Exception:
            max_n, min_imp = 1, 0.5
        if max_n <= 0 or not souvenirs:
            return []

        themes: set = set()
        entities: set = set()
        for s in souvenirs[:3]:  # ancré sur les meilleurs hits seulement
            themes.update(s.get("themes") or [])
            entities.update(s.get("entities") or [])
        if not themes and not entities:
            return []

        def _query() -> list[dict]:
            from django.db.models import Q

            from memory.models import Souvenir

            q = Q()
            if themes:
                q |= Q(themes__name__in=themes)
            if entities:
                q |= Q(entities__name__in=entities)
            rows = list(
                Souvenir.objects.filter(q)
                .filter(importance__gte=min_imp)
                .exclude(pk__in=exclude_pks)
                .distinct()
                .order_by("-importance")
                .values("id", "content", "emotion", "occurred_at", "importance")[:max_n]
            )
            return [self._linked_souvenir_dict(r) for r in rows]

        try:
            return await sync_to_async(_query)()
        except Exception as exc:
            degradations.record("prompt: expansion associative", exc)
            return []

    async def _importance_intrusion(
        self, exclude_pks: set, salience_boost: float,
    ) -> list[dict]:
        """Le souvenir intense qui S'IMPOSE, même hors-sujet — l'intrusion.

        Risqué (bruit potentiel à chaque tour) donc **opt-in** (défaut OFF), et
        **gated sur la charge émotionnelle DU TOUR** : une mémoire ne surgit pas
        à froid, elle surgit quand on est déjà remué. Chevauche volontairement
        peu la rumination (qui, elle, porte l'irrésolu, pas l'important brut).
        """
        from configs.service import config_service

        try:
            if not bool(config_service.get("memory.intrusion_enabled")):
                return []
            threshold = float(config_service.get("memory.intrusion_charge_threshold"))
            min_imp = float(config_service.get("memory.intrusion_min_importance"))
        except Exception:
            return []
        if salience_boost < threshold:
            return []

        def _query() -> list[dict]:
            from memory.models import Souvenir

            rows = list(
                Souvenir.objects.filter(importance__gte=min_imp)
                .exclude(pk__in=exclude_pks)
                .order_by("-importance")
                .values("id", "content", "emotion", "occurred_at", "importance")[:5]
            )
            if not rows:
                return []
            # Parmi les plus importants, le plus « brûlant » : importance ×
            # (1 + charge émotionnelle).
            best = max(
                rows,
                key=lambda r: r["importance"]
                * (1 + _emotional_charge(r.get("emotion") or "neutral")),
            )
            return [self._linked_souvenir_dict(best)]

        try:
            return await sync_to_async(_query)()
        except Exception as exc:
            degradations.record("prompt: intrusion importance", exc)
            return []

    async def _enrich_connaissances(self, raw_results: list[dict]) -> list[dict]:
        """Load full Connaissance data from ORM.

        Meme regroupement que pour les souvenirs (cf. `_enrich_souvenirs`).
        """
        from memory.models import Connaissance

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        # `is_valid=True` en ceinture-bretelles : ChromaDB filtre sur sa propre
        # metadonnee, donc une ligne invalidee entre l'indexation et cette
        # lecture doit disparaitre du bloc, pas etre servie.
        loaded = await self._load_by_pk(Connaissance.objects.filter(is_valid=True), pks)

        enriched = []
        for r in raw_results:
            pk = self._pk_of(r)
            if loaded is not None and pk is not None:
                row = loaded.get(pk)
                if row is None:
                    # Invalidee ou effacee : le repli ChromaDB la reservirait
                    # telle quelle, ce qui annulerait le filtre ci-dessus.
                    continue
                conn, themes, entities = row
                enriched.append({
                    "content": conn.content,
                    "confidence": conn.confidence,
                    "themes": themes,
                    "entities": entities,
                })
                continue

            # Chargement en echec, ou identifiant inexploitable : repli
            # ChromaDB, comme le faisait chaque ligne quand la requete etait
            # posee ligne par ligne.
            enriched.append({
                "content": r["content"],
                "confidence": r.get("metadata", {}).get("confidence", 0.5),
                "themes": [],
                "entities": [],
            })
        return enriched

    # Max characters for the entire memory context block injected into the prompt.
    # Prevents memory from dominating the system prompt context window.
    MAX_CONTEXT_CHARS = 4000

    def _souvenir_line(self, s: dict) -> str:
        """Une ligne de souvenir rendue — format unique partagé par les trois
        provenances (rappel direct, association, intrusion)."""
        time_str = self._time_ago(s["occurred_at"]) if s.get("occurred_at") else "?"
        emotion = s.get("emotion", "neutral")
        emotion_str = f" [{emotion}]" if emotion != "neutral" else ""
        return f"  - ({time_str}){emotion_str} {s['content'][:300]}"

    def _format_context(
        self,
        connaissances: list[dict],
        souvenirs: list[dict],
        exchanges: list | None = None,
        associations: list | None = None,
        intrusions: list | None = None,
        max_chars: int | None = None,
    ) -> str:
        """Format memories as a readable text block for the system prompt.

        Truncates individual entries and caps total size to ``max_chars``
        (défaut : le plancher historique MAX_CONTEXT_CHARS ; le budget de
        contexte du modèle déclaré peut l'élever, jamais l'abaisser).
        """
        cap = max_chars if max_chars and max_chars > 0 else self.MAX_CONTEXT_CHARS
        lines = ["--- TES SOUVENIRS ---"]
        current_len = len(lines[0])

        if connaissances:
            lines.append("\n[Ce que tu sais]")
            current_len += len(lines[-1])
            for c in connaissances:
                conf_label = self._confidence_label(c["confidence"])
                entities_str = ""
                if c["entities"]:
                    entities_str = f" (concerne: {', '.join(c['entities'])})"
                # Truncate individual content to avoid one memory dominating
                content = c["content"][:300]
                line = f"  - {content}{entities_str} [{conf_label}]"
                if current_len + len(line) > cap:
                    break
                lines.append(line)
                current_len += len(line)

        if souvenirs:
            lines.append("\n[Tes souvenirs vecus]")
            current_len += len(lines[-1])
            for s in souvenirs:
                line = self._souvenir_line(s)
                if current_len + len(line) > cap:
                    break
                lines.append(line)
                current_len += len(line)

        if associations:
            # « Ça me rappelle… » : lié par thème, pas par similarité lexicale.
            lines.append("\n[Ça t'évoque aussi]")
            current_len += len(lines[-1])
            for s in associations:
                line = self._souvenir_line(s)
                if current_len + len(line) > cap:
                    break
                lines.append(line)
                current_len += len(line)

        if exchanges:
            # Verbatim de l'étage épisodique — ce qui s'est réellement dit,
            # trouvable le jour même, avant toute extraction.
            lines.append("\n[Echanges recents (mot pour mot)]")
            current_len += len(lines[-1])
            for h in exchanges:
                when = "?"
                if getattr(h, "ts", 0):
                    when = self._time_ago(
                        datetime.fromtimestamp(h.ts, tz=dt_timezone.utc)
                    )
                content = (h.content or "").replace("\n", " / ")[:300]
                line = f"  - ({when}) {content}"
                if current_len + len(line) > cap:
                    break
                lines.append(line)
                current_len += len(line)

        if intrusions:
            # Le souvenir qui s'impose — cadré comme tel pour que le modèle
            # sache que c'est une résurgence, pas une réponse à la question.
            lines.append("\n[Quelque chose te revient]")
            current_len += len(lines[-1])
            for s in intrusions:
                line = self._souvenir_line(s)
                if current_len + len(line) > cap:
                    break
                lines.append(line)
                current_len += len(line)

        lines.append("\n--- FIN SOUVENIRS ---")
        return "\n".join(lines)

    # L'historique emotionnel avec une personne ne se lit plus ici. Il vivait
    # en double : `context._fetch_person_context` pose deja la meme question a
    # `read.recent_daily_summaries`, mais *derriere* la porte de divulgation
    # (`may_disclose_private_context`). Cette copie-ci s'ecrivait dans
    # `memory_context`, un bloc toujours injecte : dans un salon public, la
    # stance affective seule sortait par la porte gardee pendant que le climat
    # relationnel entrait par celle-ci. Le retriever revient a sa question
    # propre : souvenirs + connaissances.

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        if confidence >= 0.8:
            return "certain"
        if confidence >= 0.5:
            return "probable"
        return "incertain"

    @staticmethod
    def _time_ago(dt) -> str:
        if dt is None:
            return "?"
        now = timezone.now()
        delta = now - dt
        if delta < timedelta(hours=1):
            return "il y a quelques minutes"
        if delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"il y a {hours}h"
        days = delta.days
        if days == 1:
            return "hier"
        if days < 7:
            return f"il y a {days} jours"
        if days < 30:
            weeks = days // 7
            return f"il y a {weeks} semaine{'s' if weeks > 1 else ''}"
        months = days // 30
        return f"il y a {months} mois"
