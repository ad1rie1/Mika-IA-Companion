import asyncio
import logging
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from asgiref.sync import sync_to_async
from django.utils import timezone

from old.backend.configs.runtime import cfg_float, cfg_int
from old.backend.identity.divulgation import TOUT, Divulgation, Niveau
from old.backend.memory import sensibilite
from old.backend.memory.storage.vector_store import VectorStore, vector_call
from old.backend.utils.degradation import degradations

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
        from old.backend.emotion import pad
        from old.backend.emotion.types import Emotion

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
        from old.backend.emotion import pad
        from old.backend.emotion.types import Emotion

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


# ── Anti-répétition du rappel ────────────────────────────────────────────
#
# Les deux voies non-lexicales sont déterministes (`order_by("-importance")`)
# et le biais ×1.5 « moins d'une heure » rend collant le souvenir né pendant la
# conversation en cours. Sans mémo entre les tours, « ça me rappelle… » se
# répète mot pour mot, ce que la saillance devait précisément éviter.

#: Nombre de tours pendant lesquels un souvenir servi reste connu.
#: Réglable via ``memory.recall_memo_turns`` ; repli quand le registre est
#: hors d'atteinte.
RECALL_MEMO_TURNS = 3
#: Plafond LRU du mémo — un rappel ne doit pas devenir une fuite mémoire.
RECALL_MEMO_MAX_PERSONS = 32
#: Voie directe : on DÉMOTE, on n'exclut pas. À la même question posée deux
#: fois, une mémoire qui ne rend plus rien est pire que la répétition.
#: Réglable via ``memory.recall_repeat_penalty``.
RECALL_REPEAT_PENALTY = 0.45


def _memo_turns() -> int:
    return cfg_int("memory.recall_memo_turns", RECALL_MEMO_TURNS, mini=1, maxi=20)


def _repeat_penalty() -> float:
    return cfg_float(
        "memory.recall_repeat_penalty", RECALL_REPEAT_PENALTY, mini=0.0, maxi=1.0,
    )


class MemoryRetriever:
    """Retrieves relevant memories for a given query and formats them
    as a context block for the Claude system prompt.

    Supports:
    - person_id boosting: memories involving the current person rank higher
    - recency bias: recent memories are boosted over old ones
    """

    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        # Mémo RAM des pks servis récemment, par personne. L'objet vit aussi
        # longtemps que memory_manager, donc l'état survit aux tours.
        self._servis: "OrderedDict[str, deque]" = OrderedDict()

    def _deja_servis(self, person_id: str) -> set:
        """Les pks servis à cette personne sur les derniers tours."""
        seaux = self._servis.get(person_id or "")
        if not seaux:
            return set()
        return set().union(*(pks for _rid, pks in seaux))

    def _penalites_repetition(self, person_id: str) -> dict:
        """pk → facteur de démotion, GRADUÉ par l'ancienneté du service.

        Le mémo appliquait 0.45 à tout le monde indifféremment : à cinq
        candidats pour cinq places, l'ordre restait rigoureusement le même et
        le bloc mémoire sortait identique quarante tours de suite. Une remise
        au même rang n'est pas une anti-répétition.

        Ce qu'on veut est ce que fait un humain : ce qu'il vient de dire, il ne
        le redit pas tout de suite ; ce qu'il a dit il y a un moment peut
        revenir. La pénalité s'atténue donc avec la distance en tours, ce qui
        fait effectivement TOURNER la sélection dès qu'il y a plus de candidats
        que de places.
        """
        seaux = self._servis.get(person_id or "")
        if not seaux:
            return {}
        penalite = _repeat_penalty()
        profondeur = _memo_turns()
        penalites: dict = {}
        dernier = len(seaux) - 1
        for rang, (_rid, pks) in enumerate(seaux):
            recul = dernier - rang          # 0 = le tour qui vient de passer
            facteur = penalite + (1.0 - penalite) * (
                recul / max(1, profondeur)
            )
            for pk in pks:
                # Servi plusieurs fois : c'est le service le plus RÉCENT qui
                # compte, donc la pénalité la plus forte.
                penalites[pk] = min(penalites.get(pk, 1.0), facteur)
        return penalites

    def _noter_servis(self, person_id: str, pks: set) -> None:
        """Enregistre ce qui vient d'être servi, en un seau par *tour*.

        Un tour réel lance deux rappels (spéculatif puis dirigé, cf.
        ``pipeline/context.py``) : les fusionner sur le ``request_id`` évite
        qu'un seul tour consomme deux seaux et vide le mémo aussitôt.
        """
        if not pks:
            return
        try:
            from old.backend.pipeline.tracing import get_request_id
            rid = get_request_id()
        except Exception:
            rid = "-"

        cle = person_id or ""
        seaux = self._servis.get(cle)
        if seaux is None:
            # `maxlen` est figé à la création du tampon : une personne déjà
            # mémorisée garde son ancienne profondeur jusqu'au redémarrage.
            # C'est ce que dit `restart_required` sur le réglage.
            seaux = deque(maxlen=_memo_turns())
            self._servis[cle] = seaux
        if seaux and rid != "-" and seaux[-1][0] == rid:
            seaux[-1][1].update(pks)
        else:
            seaux.append((rid, set(pks)))

        self._servis.move_to_end(cle)
        while len(self._servis) > RECALL_MEMO_MAX_PERSONS:
            self._servis.popitem(last=False)

    async def retrieve(
        self, query: str, person_id: str = "", divulgation: Divulgation = TOUT,
    ) -> str:
        """Retrieve and format relevant memories for a user message."""
        return await self.retrieve_multi(
            [query], person_id=person_id, divulgation=divulgation,
        )

    async def retrieve_multi(
        self,
        queries: list[str],
        person_id: str = "",
        extra_exchanges: list | None = None,
        salience_boost: float = 0.0,
        divulgation: Divulgation = TOUT,
    ) -> str:
        """Rappel multi-requêtes — le chemin unique du bloc mémoire.

        ``divulgation`` est le niveau du tour (``identity.divulgation``,
        calculé une fois au bord) : ce qui concerne un tiers et pèse plus
        que le niveau est retiré, ce qui pèse moins mais n'est pas anodin
        est rendu **tagué** pour que Mika arbitre. Ce qui la concerne seule,
        ou concerne l'interlocuteur, passe sans tag. Le défaut ``TOUT`` est
        sa mémoire entière — un appelant interne.

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
        from old.backend.configs.service import config_service

        queries = [q.strip() for q in (queries or []) if q and q.strip()]
        if not queries:
            return ""

        min_importance = config_service.get("memory.min_importance")
        # Les comptes de rappel SUIVENT la place réellement disponible.
        #
        # Ils étaient figés (5 souvenirs, 10 connaissances) à des valeurs
        # choisies pour un petit modèle local. Derrière une fenêtre de 256k,
        # `_budget_cap()` accorde ~25 000 caractères au bloc mémoire et le
        # rappel en remplissait ~2 000 : on lui donnait la place de se souvenir
        # et elle ne s'en servait pas. Le plancher reste la valeur configurée —
        # on n'AMPUTE jamais un réglage explicite, on ne fait que l'étendre
        # quand la fenêtre le permet.
        n_souvenirs, n_connaissances = self._comptes_adaptes()

        # On récupère plus large que nécessaire pour laisser le re-ranking par
        # saillance PROMOUVOIR un souvenir marquant mais lexicalement moins
        # proche : sans vivier élargi, re-classer ne ferait que réordonner du
        # déjà-similaire. `vector_call` sort l'encode CPU du thread ORM partagé.
        fetch_multiplier = self._fetch_multiplier()
        # ``return_exceptions`` : une requête qui échoue (Chroma qui tousse
        # sur UNE des formulations du plan de préparation) ne doit pas
        # emporter tout le rappel du tour — ``_merge_pages`` saute la page
        # et la compte, les autres formulations servent quand même.
        souvenir_pages, connaissance_pages = await asyncio.gather(
            asyncio.gather(*[
                vector_call(self.vector_store.search_souvenirs)(
                    q, n=n_souvenirs * fetch_multiplier, min_importance=min_importance,
                )
                for q in queries
            ], return_exceptions=True),
            asyncio.gather(*[
                vector_call(self.vector_store.search_connaissances)(
                    q, n=n_connaissances,
                )
                for q in queries
            ], return_exceptions=True),
        )
        souvenirs_raw = self._merge_pages(souvenir_pages)
        connaissances_raw = self._merge_pages(connaissance_pages)

        # Voie épisodique — la première requête est le message lui-même.
        # ``extra_exchanges`` vient du plan de préparation (intents
        # `echanges_passes`, rappel inter-personnes permis) ; la voie chaude
        # reste restreinte à l'identité de l'interlocuteur.
        exchanges = await self._episodic_lane(
            queries[0], person_id, divulgation=divulgation,
        )
        # Les échanges du plan sont du verbatim aussi, et le rappel
        # inter-personnes y est permis : le verbatim d'autrui est la forme la
        # plus lourde, il ne sort qu'au niveau ``confidence``, tout ou rien.
        if extra_exchanges and divulgation.niveau is Niveau.CONFIDENCE:
            seen = {h.chunk_id for h in exchanges}
            exchanges = exchanges + [
                h for h in extra_exchanges if h.chunk_id not in seen
            ]

        if not souvenirs_raw and not connaissances_raw and not exchanges:
            return ""

        # Le boost personne compare des NOMS d'entités — résoudre le handle en
        # nom via la couche identité est ce qui le fait enfin tirer (l'égalité
        # handle/nom ne matchait jamais : `web_6f3e22ccb0ae` n'est le nom de
        # personne). Il sert aussi de laissez-passer au filtre intime : les
        # souvenirs de l'interlocuteur lui-même ne sont pas « ceux d'autrui ».
        boost_name = await self._person_boost_name(person_id)

        # Enrich with ORM data
        souvenirs = await self._enrich_souvenirs(
            souvenirs_raw, boost_name=boost_name, divulgation=divulgation,
        )
        connaissances = await self._enrich_connaissances(
            connaissances_raw, boost_name=boost_name, divulgation=divulgation,
        )

        # L'humeur courante est lue sans effet de bord (pas de création
        # d'oscillateur).
        mood_pad = self._mood_pad_for(person_id)
        weights = self._salience_weights(boost=salience_boost)
        memo = self._deja_servis(person_id)
        souvenirs = self._rerank_souvenirs(
            souvenirs, boost_name, mood_pad=mood_pad, weights=weights,
            demote_pks=self._penalites_repetition(person_id),
        )

        # Take top N after reranking
        souvenirs = souvenirs[:n_souvenirs]

        # Rappels non-lexicaux — ce que fait l'humain que le cosinus ne fait pas :
        #  · association « ça me rappelle… », ancrée sur les thèmes des hits ;
        #  · intrusion d'un souvenir intense (opt-in), seulement si le tour est
        #    DÉJÀ chargé — jamais à froid.
        # Ces deux voies-là sont exclues DUREMENT sur le mémo : leur raison
        # d'être est de ne pas se répéter.
        exclude_pks = {s["id"] for s in souvenirs if s.get("id")} | memo
        associations = await self._associative_expansion(
            souvenirs, exclude_pks,
            boost_name=boost_name, divulgation=divulgation,
        )
        exclude_pks |= {a["id"] for a in associations if a.get("id")}
        intrusions = await self._importance_intrusion(
            exclude_pks, salience_boost,
            boost_name=boost_name, divulgation=divulgation,
        )
        self._noter_servis(person_id, {
            s["id"] for s in (souvenirs + associations + intrusions) if s.get("id")
        })

        return self._format_context(
            connaissances, souvenirs, exchanges=exchanges,
            associations=associations, intrusions=intrusions,
            max_chars=self._budget_cap(),
        )

    #: Un rappel plus large reste un rappel : au-delà, ce n'est plus se
    #: souvenir, c'est réciter un dossier. Les plafonds valent donc pour une
    #: fenêtre de 1 M aussi bien que de 256 k.
    MAX_SOUVENIRS = 15
    MAX_CONNAISSANCES = 25
    MAX_EXCHANGES = 10
    #: Caractères de budget mémoire par souvenir supplémentaire accordé.
    CHARS_PAR_SOUVENIR = 1800

    def _comptes_adaptes(self) -> tuple[int, int]:
        """(souvenirs, connaissances) — les réglages, étendus par la place."""
        from old.backend.configs.service import config_service

        try:
            base_s = int(config_service.get("memory.retrieval_souvenirs"))
            base_c = int(config_service.get("memory.retrieval_connaissances"))
        except Exception:
            base_s, base_c = 5, 10

        try:
            marge = self._budget_cap() - self.MAX_CONTEXT_CHARS
            if marge <= 0:
                return base_s, base_c
            extra = int(marge / self.CHARS_PAR_SOUVENIR)
        except Exception as exc:
            degradations.record("rappel: comptes adaptes au budget", exc)
            return base_s, base_c

        return (
            min(self.MAX_SOUVENIRS, max(base_s, base_s + extra)),
            min(self.MAX_CONNAISSANCES, max(base_c, base_c + extra)),
        )

    def _budget_cap(self) -> int:
        """Plafond du bloc mémoire : la part L5 du budget, plancher 4000.

        Sans ``context_window`` déclaré sur le modèle de conversation, le
        budget vaut None et le plancher historique reste seul maître.
        """
        try:
            from old.backend.ai.budget import budget_for
            from old.backend.ai.router import AIRole

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
        from old.backend.configs.service import config_service

        try:
            return max(1, int(config_service.get("memory.retrieval_fetch_multiplier")))
        except Exception:
            return 3

    def _salience_weights(self, boost: float = 0.0) -> "_SalienceWeights":
        """Poids de saillance depuis la config (défauts prudents). ``boost``
        ∈ [0,1] (plan de préparation) monte émotion/humeur pour un tour chargé.
        """
        from old.backend.configs.service import config_service

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
            from old.backend.emotion.engine import emotion_engine
            from old.backend.identity.trust import is_internal_person

            if is_internal_person(person_id):
                return None
            mood = emotion_engine.person_mood(person_id)
            return mood.dynamic.position if mood is not None else None
        except Exception as exc:
            degradations.record("prompt: humeur pour saillance", exc)
            return None

    @staticmethod
    def _merge_pages(pages) -> list[dict]:
        """Fusionne des pages ChromaDB par id, en gardant la distance min."""
        merged: dict[str, dict] = {}
        for page in pages:
            if isinstance(page, BaseException):
                # Relevée pour être rattrapée sur place : le registre des
                # dégradations ne se nourrit que d'un `except` (un test AST
                # l'impose), et une page en échec EST une panne à compter,
                # pas une ligne de progression. Même famille d'exception que
                # ce que `gather(return_exceptions=True)` peut rendre.
                try:
                    raise page
                except BaseException as exc:
                    degradations.record("retriever: page vectorielle", exc)
                continue
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

    async def _episodic_lane(
        self, query: str, person_id: str, *, divulgation: Divulgation = TOUT,
    ):
        """Échanges bruts de la même identité que l'interlocuteur.

        Tout ou rien, sur la **fiche** de l'interlocuteur
        (``divulgation.fiche_ouverte`` = ``may_disclose``, inchangé) : c'est
        SON verbatim, la forme la plus lourde de sa propre histoire. Sous le
        seuil (salon public, compte non corroboré) la voie se ferme
        entièrement. Elle cherchait « l'identité de l'interlocuteur »,
        c'est-à-dire TOUS ses handles : dans un groupe Telegram, les DM du
        compte revenaient mot pour mot devant l'audience. Le verbatim est ce
        qui s'est dit en tête à tête, et l'audience est précisément ce que la
        porte mesure.
        """
        from old.backend.identity.trust import is_internal_person

        if not person_id or is_internal_person(person_id) or not divulgation.fiche_ouverte:
            return []
        try:
            from old.backend.configs.service import config_service
            n_exchanges = int(config_service.get("memory.retrieval_exchanges"))
        except Exception:
            n_exchanges = 3
        # Même règle que les souvenirs : le verbatim du jour est ce qui rend
        # « tu te souviens de ce que je t'ai dit ce matin ? » possible, et une
        # fenêtre large peut en porter davantage.
        try:
            marge = self._budget_cap() - self.MAX_CONTEXT_CHARS
            if marge > 0:
                n_exchanges = min(
                    self.MAX_EXCHANGES,
                    max(n_exchanges, n_exchanges + int(marge / self.CHARS_PAR_SOUVENIR)),
                )
        except Exception as exc:
            degradations.record("rappel: echanges adaptes au budget", exc)
        if n_exchanges <= 0:
            return []
        try:
            from old.backend.identity.resolver import identity_resolver
            from old.backend.memory.episodic import api as episodic_api

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
            from old.backend.identity.resolver import identity_resolver

            entity = await identity_resolver.entity_for_person(person_id)
            return entity.name if entity is not None else ""
        except Exception as exc:
            degradations.record("prompt: resolution boost personne", exc)
            return ""

    def _rerank_souvenirs(
        self, souvenirs: list[dict], boost_name: str, *,
        mood_pad=None, weights: "_SalienceWeights | None" = None,
        demote_pks: "set | dict | None" = None,
    ) -> list[dict]:
        """Classe les souvenirs par pertinence × récence × personne × SAILLANCE.

        La saillance (importance, charge émotionnelle, congruence d'humeur)
        fait enfin remonter « ce qui a compté » et pas seulement « ce qui
        ressemble » — l'humain rappelle par la charge, pas par la distance.

        Fonction **pure** : ``mood_pad`` (humeur PAD courante), ``weights`` et
        ``demote_pks`` (mémo anti-répétition) sont injectés, donc testable
        sans ``emotion_engine`` ni config. ``boost_name`` est un *nom
        d'entité* (résolu via la couche identité), pas un handle. ``_score``
        n'est qu'une clé de tri : plus de plafond à 1.0, qui saturait et
        effaçait précisément les écarts de saillance.
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

            # Déjà servi il y a peu : il recule, il ne disparaît pas — et il
            # recule d'autant plus que c'était récent.
            if demote_pks:
                sid = s.get("id")
                if isinstance(demote_pks, dict):
                    score *= demote_pks.get(sid, 1.0)
                elif sid in demote_pks:
                    # Voie ensembliste, sans graduation : `_rerank_souvenirs`
                    # est PURE par contrat (aucune lecture de config), donc
                    # elle applique la constante. Le chemin vivant passe par
                    # le dict gradué de `_penalites_repetition`, lui réglable.
                    score *= RECALL_REPEAT_PENALTY

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
    async def _load_by_pk(queryset, pks: list[int], *, soi_nom: str = "") -> dict | None:
        """Charge en UNE requete les lignes demandees, avec leurs M2M et leur
        qualification face a l'interlocuteur (``read.charger_qualifiees``).

        Retourne ``{pk: (ligne, themes, entities, qualification)}``, ou
        ``None`` si le chargement lui-meme a echoue (base verrouillee, table
        absente) — le cas ou l'appelant doit replier *toute* la page sur
        ChromaDB, a distinguer d'une ligne simplement absente du resultat.
        """
        from old.backend.memory import read

        if not pks:
            return {}
        try:
            return await sync_to_async(read.charger_qualifiees)(
                queryset, pks, soi_nom=soi_nom,
            )
        except Exception as exc:
            degradations.record("rappel: chargement ORM des lignes", exc)
            return None

    @staticmethod
    def _admis(qualification, divulgation: Divulgation) -> bool:
        return sensibilite.admissible(qualification, divulgation)

    async def _enrich_souvenirs(
        self, raw_results: list[dict], *, boost_name: str = "",
        divulgation: Divulgation = TOUT,
    ) -> list[dict]:
        """Load full Souvenir data from ORM.

        Une seule requete pour toute la page ChromaDB, dans un seul saut
        ``sync_to_async``. Ligne par ligne, cela coutait cinq requetes et trois
        sauts de thread par souvenir — serialises sur l'unique executeur
        partage avec les six boucles de fond — soit une centaine de requetes
        par tour de conversation avant meme l'appel LLM.
        """
        from old.backend.memory.models import Souvenir

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        # Le seul filtre est celui de la frontière intime, ligne par ligne :
        # un souvenir qui implique une AUTRE personne et pèse plus que le
        # niveau du tour n'a pas à remonter ; en dessous, il sort tagué.
        # Une ligne absente du chargement n'existe plus — elle évince son
        # vecteur ; une ligne retirée par le niveau est bien vivante.
        loaded = await self._load_by_pk(Souvenir.objects.all(), pks, soi_nom=boost_name)
        brut_permis = divulgation.niveau is Niveau.CONFIDENCE
        if loaded is None and not brut_permis:
            # Le repli ChromaDB sert la page BRUTE, et le filtre intime ne vit
            # que dans la requête ORM qui vient d'échouer : une base verrouillée
            # ouvrait la porte que la divulgation ferme. Le rappel se tait
            # plutôt que de raconter la mémoire des autres.
            return []

        # L'ordre ChromaDB est l'ordre de pertinence : on le reconstitue en
        # Python plutot que de le demander a la base.
        enriched = []
        orphelins: list[int] = []
        for r in raw_results:
            pk = self._pk_of(r)
            if loaded is not None and pk is not None:
                row = loaded.get(pk)
                if row is None:
                    # Effacee (fusion nocturne) : le repli ChromaDB la
                    # resservirait indefiniment, importance figee, et l'oubli
                    # decide deviendrait inoubliable.
                    orphelins.append(pk)
                    continue

                souvenir, themes, entities, qualif = row
                if not self._admis(qualif, divulgation):
                    continue

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
                    "tag": sensibilite.tag(qualif),
                })
                continue

            # Chargement en echec, ou identifiant inexploitable : repli ChromaDB.
            # Une ligne dont on ne peut pas vérifier de qui elle parle ne sort
            # que si le tour peut tout porter — même règle que ``memory_search``.
            if not brut_permis:
                continue
            meta = r.get("metadata", {})
            enriched.append({
                "id": pk,
                "content": r["content"],
                "emotion": meta.get("emotion", "neutral"),
                "importance": meta.get("importance", 0.5),
                "occurred_at": None,
                "themes": [],
                "entities": [],
                "relevance": 0.5,
            })

        await self._evincer_orphelins(orphelins)
        return enriched

    #: Une desynchro massive ne doit pas transformer un rappel en campagne de
    #: suppression ChromaDB au milieu d'un tour.
    MAX_ORPHAN_EVICTIONS = 10

    async def _evincer_orphelins(self, pks: list[int]) -> None:
        """Retire de ChromaDB les entrees dont la ligne ORM a disparu."""
        if not pks or self.vector_store is None:
            return
        for pk in pks[:self.MAX_ORPHAN_EVICTIONS]:
            logger.warning(
                "Souvenir #%d present dans ChromaDB mais absent de la base — "
                "entree orpheline retiree", pk,
            )
            try:
                await vector_call(self.vector_store.remove_souvenir)(pk)
            except Exception as exc:
                degradations.record("rappel: retrait souvenir fantome", exc)

    # ── Rappels non-lexicaux — ce que le cosinus ne trouvera jamais ──────

    @staticmethod
    def _linked_souvenir_dict(charge: tuple) -> dict:
        """Ligne chargée ``(souvenir, thèmes, entités, qualification)`` → dict
        au format attendu par _format_context."""
        souvenir, _themes, _entities, qualif = charge
        return {
            "id": souvenir.pk,
            "content": souvenir.content,
            "emotion": souvenir.emotion or "neutral",
            "occurred_at": souvenir.occurred_at,
            "importance": souvenir.importance,
            "tag": sensibilite.tag(qualif),
        }

    #: Les voies non-lexicales filtrent en Python après chargement (la
    #: sensibilité effective et le témoignage se lisent ligne par ligne) :
    #: elles chargent ce multiple de ce qu'elles rendent.
    _SURPLUS_FILTRE = 4

    async def _lignes_admises(
        self, queryset, pks: list[int], *, boost_name: str,
        divulgation: Divulgation, n: int,
    ) -> list[dict]:
        """Les ``n`` premières lignes de ``pks`` (dans cet ordre) que le
        niveau du tour admet, au format de ``_format_context``."""
        loaded = await self._load_by_pk(queryset, pks, soi_nom=boost_name)
        if not loaded:
            return []
        out: list[dict] = []
        for pk in pks:
            charge = loaded.get(pk)
            if charge is None or not self._admis(charge[3], divulgation):
                continue
            out.append(self._linked_souvenir_dict(charge))
            if len(out) >= n:
                break
        return out

    async def _associative_expansion(
        self, souvenirs: list[dict], exclude_pks: set, *,
        boost_name: str = "", divulgation: Divulgation = TOUT,
    ) -> list[dict]:
        """« Ça me rappelle… » — souvenirs liés par thème/entité aux meilleurs
        hits déjà retenus. **Ancré** sur ce qui est déjà pertinent (donc pas
        hors-sujet), borné en nombre, et filtré par importance (on ne dredge
        pas de la trivia parce qu'elle partage un thème). Sûr → actif par défaut.
        """
        from old.backend.configs.service import config_service

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

        def _candidats() -> list[int]:
            from django.db.models import Q

            from old.backend.memory.models import Souvenir

            q = Q()
            if themes:
                q |= Q(themes__name__in=themes)
            if entities:
                q |= Q(entities__name__in=entities)
            return list(
                Souvenir.objects.filter(q)
                .filter(importance__gte=min_imp)
                .exclude(pk__in=exclude_pks)
                .distinct()
                .order_by("-importance")
                .values_list("pk", flat=True)[: max_n * self._SURPLUS_FILTRE]
            )

        try:
            from old.backend.memory.models import Souvenir

            pks = await sync_to_async(_candidats)()
            return await self._lignes_admises(
                Souvenir.objects.all(), pks, boost_name=boost_name,
                divulgation=divulgation, n=max_n,
            )
        except Exception as exc:
            degradations.record("prompt: expansion associative", exc)
            return []

    async def _importance_intrusion(
        self, exclude_pks: set, salience_boost: float, *,
        boost_name: str = "", divulgation: Divulgation = TOUT,
    ) -> list[dict]:
        """Le souvenir intense qui S'IMPOSE, même hors-sujet — l'intrusion.

        Risqué (bruit potentiel à chaque tour) donc **opt-in** (défaut OFF), et
        **gated sur la charge émotionnelle DU TOUR** : une mémoire ne surgit pas
        à froid, elle surgit quand on est déjà remué. Chevauche volontairement
        peu la rumination (qui, elle, porte l'irrésolu, pas l'important brut).
        """
        from old.backend.configs.service import config_service

        try:
            if not bool(config_service.get("memory.intrusion_enabled")):
                return []
            threshold = float(config_service.get("memory.intrusion_charge_threshold"))
            min_imp = float(config_service.get("memory.intrusion_min_importance"))
        except Exception:
            return []
        if salience_boost < threshold:
            return []

        def _candidats() -> list[int]:
            from old.backend.memory.models import Souvenir

            return list(
                Souvenir.objects.filter(importance__gte=min_imp)
                .exclude(pk__in=exclude_pks)
                .order_by("-importance")
                .values_list("pk", flat=True)[:5]
            )

        try:
            from old.backend.memory.models import Souvenir

            pks = await sync_to_async(_candidats)()
            rows = await self._lignes_admises(
                Souvenir.objects.all(), pks, boost_name=boost_name,
                divulgation=divulgation, n=len(pks),
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
            return [best]
        except Exception as exc:
            degradations.record("prompt: intrusion importance", exc)
            return []

    async def _enrich_connaissances(
        self, raw_results: list[dict], *, boost_name: str = "",
        divulgation: Divulgation = TOUT,
    ) -> list[dict]:
        """Load full Connaissance data from ORM.

        Meme regroupement que pour les souvenirs (cf. `_enrich_souvenirs`),
        et même frontière intime : « Alice attend un enfant » est une
        connaissance, et ``(concerne: Alice)`` la rendait devant n'importe quel
        handle non lié pendant que les souvenirs, eux, étaient déjà filtrés.
        """
        from old.backend.memory.models import Connaissance

        pks = [pk for pk in (self._pk_of(r) for r in raw_results) if pk is not None]
        # `is_valid=True` en ceinture-bretelles : ChromaDB filtre sur sa propre
        # metadonnee, donc une ligne invalidee entre l'indexation et cette
        # lecture doit disparaitre du bloc, pas etre servie.
        base = Connaissance.objects.filter(is_valid=True)
        loaded = await self._load_by_pk(base, pks, soi_nom=boost_name)
        if loaded is None:
            # Chargement en échec : le repli ChromaDB servirait la page brute,
            # sans `is_valid` ni le filtre intime — les deux ne vivent que dans
            # la requête qui vient d'échouer. Rien de vérifié, rien de servi.
            return []

        enriched = []
        for r in raw_results:
            pk = self._pk_of(r)
            if pk is not None:
                row = loaded.get(pk)
                if row is None:
                    # Invalidee ou effacee : le repli ChromaDB la reservirait
                    # telle quelle, ce qui annulerait le filtre ci-dessus.
                    continue
                conn, themes, entities, qualif = row
                if not self._admis(qualif, divulgation):
                    continue
                enriched.append({
                    "content": conn.content,
                    "confidence": conn.confidence,
                    "epistemic_kind": conn.epistemic_kind,
                    "source_message_ids": conn.source_message_ids,
                    "themes": themes,
                    "entities": entities,
                    "tag": sensibilite.tag(qualif),
                })
                continue

            # Identifiant inexploitable : repli ChromaDB, comme le faisait
            # chaque ligne quand la requete etait posee ligne par ligne —
            # sauf quand on ne peut pas tout porter : de qui parle-t-elle ?
            if divulgation.niveau is not Niveau.CONFIDENCE:
                continue
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
        return f"  - ({time_str}){emotion_str} {s['content'][:300]}{s.get('tag', '')}"

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
        entete = "--- TES SOUVENIRS ---"
        lines: list[str] = []
        current_len = len(entete)

        def _section(titre: str, entrees, rendu) -> None:
            # L'entête n'est posé qu'APRÈS le corps : « [Quelque chose te
            # revient] » suivi de rien est, sur petit modèle, une invitation à
            # inventer le souvenir manquant. Sa longueur est réservée d'avance,
            # sinon la section dépasserait le plafond de la taille du titre.
            nonlocal current_len
            reserve = current_len + len(titre)
            corps: list[str] = []
            for e in entrees or ():
                ligne = rendu(e)
                if reserve + len(ligne) > cap:
                    break
                corps.append(ligne)
                reserve += len(ligne)
            if not corps:
                return
            lines.append(titre)
            lines.extend(corps)
            current_len = reserve

        def _connaissance_line(c: dict) -> str:
            conf_label = self._confidence_label(c["confidence"])
            entities_str = ""
            if c["entities"]:
                entities_str = f" (concerne: {', '.join(c['entities'])})"
            # Truncate individual content to avoid one memory dominating
            content = c["content"][:300]
            origine = {"reported": "rapporté", "observed": "observé", "inferred": "déduit", "uncertain": "supposé"}.get(c.get("epistemic_kind"), "")
            provenance = f" (source : {origine})" if origine else ""
            return f"  - {content}{entities_str} [{conf_label}]{c.get('tag', '')}{provenance}"

        def _exchange_line(h) -> str:
            when = "?"
            if getattr(h, "ts", 0):
                when = self._time_ago(
                    datetime.fromtimestamp(h.ts, tz=dt_timezone.utc)
                )
            content = (h.content or "").replace("\n", " / ")[:300]
            return f"  - ({when}) {content}"

        _section("\n[Ce que tu sais]", connaissances, _connaissance_line)
        _section("\n[Tes souvenirs vecus]", souvenirs, self._souvenir_line)
        # « Ça me rappelle… » : lié par thème, pas par similarité lexicale.
        _section("\n[Ça t'évoque aussi]", associations, self._souvenir_line)
        # Verbatim de l'étage épisodique — ce qui s'est réellement dit,
        # trouvable le jour même, avant toute extraction.
        _section("\n[Echanges recents (mot pour mot)]", exchanges, _exchange_line)
        # Le souvenir qui s'impose — cadré comme tel pour que le modèle sache
        # que c'est une résurgence, pas une réponse à la question.
        _section("\n[Quelque chose te revient]", intrusions, self._souvenir_line)

        if not lines:
            # Un bloc réduit à son entête est le même défaut, un cran au-dessus.
            return ""
        return "\n".join([entete, *lines, "\n--- FIN SOUVENIRS ---"])

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
