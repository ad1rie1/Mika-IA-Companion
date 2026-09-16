"""MemoryBridge — the Conscience's R/W interface to long-term memory.

Delegates all operations to memory_manager — single entry point,
uniform guarantees (vector indexing, logging, error handling).
"""

from __future__ import annotations

import asyncio
import logging

from configs.runtime import cfg_float, cfg_int
from conscience.types import InterpretedSignal
from utils.degradation import degradations, degraded

logger = logging.getLogger(__name__)

#: Le manque se mesure au RYTHME propre de chaque relation, jamais à un
#: seuil global : trois jours de silence inquiètent pour un ami quotidien et
#: ne veulent rien dire pour un ami mensuel. Le rythme est la médiane des
#: écarts entre les jours où la personne a écrit (90 j d'historique) ; une
#: relation trop récente pour avoir un rythme retombe sur le défaut de sa
#: closeness — l'ancien seuil unique devient le repli, plus le juge.
#: Constantes au niveau module : replis des clés `conscience.recontact_*`.

#: Le silence « manque » quand il dépasse ce multiple du rythme du lien.
RECONTACT_FACTEUR = 1.5
#: Multiple supplémentaire quand ELLE a parlé en dernier : on ne double-texte
#: pas quelqu'un qui n'a pas répondu — on re-tente après un vrai moment.
RECONTACT_RELANCE_FACTEUR = 3.0
#: Rythme de repli d'un ami / d'un proche sans historique suffisant (jours).
RECONTACT_RYTHME_AMI_JOURS = 7
RECONTACT_RYTHME_PROCHE_JOURS = 3

#: Bornes du rythme mesuré — des gardes de lecteur, pas des réglages : un
#: rythme sous un jour ferait « manquer » chaque nuit, au-delà d'un mois la
#: médiane ne mesure plus une habitude.
_RYTHME_MIN_JOURS = 1.0
_RYTHME_MAX_JOURS = 30.0
_RYTHME_HISTORIQUE_JOURS = 90
#: Jours actifs minimum pour qu'une médiane veuille dire quelque chose.
_RYTHME_JOURS_ACTIFS_MIN = 3
#: Part de la chaleur de l'ancre affective dans la priorité (voir
#: ``_chaleur_pour``).
_CHALEUR_POIDS = 0.5
#: Fiches examinées par passage. Une relance est une pensée pour quelqu'un,
#: pas un publipostage.
_RECONTACT_PROFILS_MAX = 10


def _rythme_naturel(
    jours_actifs, closeness: str, *, ami_jours: float, proche_jours: float,
) -> float:
    """Le rythme du lien, en jours — médiane des écarts entre jours actifs.

    Pure, pour être mesurable seule. Moins de ``_RYTHME_JOURS_ACTIFS_MIN``
    jours actifs → le repli de la closeness : deux messages ne font pas une
    habitude. Bornée dans les deux cas — le repli aussi, car il vient de la
    configuration.
    """
    import statistics

    repli = float(proche_jours if closeness == "close" else ami_jours)
    jours = sorted(set(jours_actifs or ()))
    if len(jours) < _RYTHME_JOURS_ACTIFS_MIN:
        return max(_RYTHME_MIN_JOURS, min(_RYTHME_MAX_JOURS, repli))
    ecarts = [(b - a).days for a, b in zip(jours, jours[1:])]
    rythme = float(statistics.median(ecarts))
    return max(_RYTHME_MIN_JOURS, min(_RYTHME_MAX_JOURS, rythme))


class MemoryBridge:
    """Read/write interface from the Conscience to long-term memory.

    All operations go through memory_manager — no direct ORM access.
    """

    # ── Read ─────────────────────────────────────────────────────

    async def recall_for_context(
        self, queries: list[str], person_id: str = "", *, channel: str = "",
        interne: bool = False,
    ) -> str:
        """Retrieve relevant memories for a list of query strings.

        **La porte de divulgation s'applique ici aussi** (MEM-09). Ce rappel
        alimentait ``--- TES SOUVENIRS ---`` d'un acte spontané SANS
        ``person_id``, donc avec les confidences de tout le monde, puis
        ``_appeler_le_modele`` écrasait le contexte que ``gather_context``
        avait correctement filtré. Un inconnu présent quand SOCIAL débordait
        recevait les souvenirs d'Alice.

        - ``interne=True`` : un pas de chantier, une réflexion que personne
          n'entend — sa mémoire entière.
        - ``person_id`` identifiable : la certitude d'identité et le canal
          décident, exactement comme pour un tour de conversation.
        - ni l'un ni l'autre (un acte pour « qui regarde ») : fermé — on ne
          récite pas les confidences des autres devant une pièce dont on ne
          sait pas qui l'occupe.

        Multi-requêtes : chaque résumé d'observation interroge la mémoire
        séparément et les pages fusionnent par pertinence — la concaténation
        (« q1 q2 q3 » en une seule recherche) produisait un embedding moyen
        qui ne ressemblait à aucune des trois questions. Les résumés
        d'observations SONT le plan de rappel de la conscience : c'est
        pourquoi les tours de conscience ne passent pas par la passe de
        préparation LLM du pipeline.

        Returns formatted context string or empty.
        """
        from memory.manager import memory_manager

        if not queries:
            return ""

        disclose_others = await self._peut_divulguer(
            person_id, channel=channel, interne=interne,
        )
        try:
            return await memory_manager.get_memory_context_multi(
                queries[:3], person_id=person_id, disclose_others=disclose_others,
            )
        except Exception:
            logger.exception("MemoryBridge: recall_for_context failed")
            return ""

    @staticmethod
    async def _peut_divulguer(person_id: str, *, channel: str, interne: bool) -> bool:
        """Fermé par défaut : ne pas savoir à qui on parle n'ouvre rien."""
        if interne:
            return True
        from identity.trust import is_identifiable_person

        if not person_id or not is_identifiable_person(person_id):
            return False
        try:
            from identity.resolver import identity_resolver

            ctx = await identity_resolver.resolve_context(
                person_id, channel=channel or "", authenticated=False, is_public=False,
            )
            return bool(ctx.may_disclose)
        except Exception as exc:
            degradations.record("conscience: divulgation du rappel", exc)
            return False

    # Poids de l'évidence épisodique dans who_is_concerned : un échange
    # récent pèse un peu plus qu'une mention en mémoire curée.
    _EXCHANGE_WEIGHT = 1.2

    async def _merge_exchange_evidence(
        self, signal_text: str, names_scores: dict, n: int,
    ) -> None:
        """Ajoute aux scores les personnes dont les échanges bruts récents
        parlent du sujet. Mutation en place, jamais d'exception."""
        from identity.resolver import identity_resolver
        from identity.trust import is_internal_person

        try:
            from memory.episodic import api as episodic_api

            hits = await episodic_api.search_exchanges(signal_text, n=n)
        except Exception as exc:
            degradations.record("conscience: evidence episodique", exc)
            return

        entity_cache: dict = {}
        for h in hits:
            handle = h.handle
            if not handle or is_internal_person(handle):
                continue
            if handle not in entity_cache:
                try:
                    entity_cache[handle] = await identity_resolver.entity_for_person(handle)
                except Exception:
                    entity_cache[handle] = None
            entity = entity_cache[handle]
            if entity is None:
                # Visiteur non lié : aucun nom vers qui router.
                continue
            distance = h.distance if h.distance is not None else 0.5
            relevance = max(0.0, 1.0 - distance) * self._EXCHANGE_WEIGHT
            if relevance > 0:
                names_scores[entity.name] = names_scores.get(entity.name, 0.0) + relevance

    async def get_important_souvenirs(
        self, min_importance: float = 0.5, limit: int = 5
    ) -> list:
        """Get recent important souvenirs."""
        from memory.manager import memory_manager
        return await memory_manager.get_important_souvenirs(min_importance, limit)

    async def who_is_concerned(self, signal_text: str, n: int = 5) -> list[dict]:
        """Who does this signal concern, ranked, with reachable handles.

        Concern-based routing grounded in what conversation has taught:
        1. semantic search souvenirs + connaissances for the signal's topic
        2. collect the *person* entities those memories reference (relevance-weighted)
        3. resolve each name → identity → handles (durable identity layer)
        4. keep only the reachable ones (consumers connected now; modules are
           reachable whenever a durable handle exists — external API is push-capable)

        Ce que ce quatrieme point suppose — qu'un handle module durable a
        toujours son entree de presence — est rendu vrai au demarrage par
        ``identity_resolver.restore_module_presence()`` : sans elle la
        livraison, elle, ne voyait que la presence en RAM et abandonnait
        silencieusement le message compose pour un contact qui n'avait pas
        ecrit depuis le boot.

        Returns ``[{"name", "score", "handles": [...]}]`` sorted by score, or [].
        The inclusive (interest) vs exclusive (attribution) decision is left to the
        caller — this returns the candidate field, not the final pick.
        """
        from asgiref.sync import sync_to_async

        from communication.presence import presence_registry
        from identity.resolver import identity_resolver
        from memory.manager import memory_manager

        if not signal_text.strip():
            return []

        souvenirs = await memory_manager.search_related_souvenirs(signal_text, n=n)
        connaissances = await memory_manager.search_related_connaissances(signal_text, n=n)

        names_scores = await sync_to_async(self._person_entities_from_matches)(
            souvenirs, connaissances
        )

        # 2bis. Évidence épisodique : un échange brut récent sur le sujet est
        # une preuve plus fraîche qu'une vieille mention dans un souvenir —
        # et elle existe le jour même, avant toute extraction. Le handle du
        # chunk remonte à l'entité via la couche identité, jamais par nom.
        await self._merge_exchange_evidence(signal_text, names_scores, n)

        if not names_scores:
            return []

        handle_map = await identity_resolver.handles_for_entity_names(
            list(names_scores)
        )

        results = []
        for name, score in names_scores.items():
            reachable = [
                h for h in handle_map.get(name, [])
                if h["kind"] == "module"  # external API: reachable any time
                or presence_registry.resolve_on(h["person_id"], h["channel"])
            ]
            if reachable:
                results.append(
                    {"name": name, "score": round(score, 3), "handles": reachable}
                )

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    async def who_misses_contact(self, n: int = 1) -> list[dict]:
        """QUI lui manque — au rythme du lien, pas à un seuil global.

        Troisième maillon de la chaîne du destinataire (mémoire → présents →
        manque). Amis et proches seulement (``PersonProfile.closeness``) —
        « reprendre des nouvelles » suppose une relation, pas une fiche.
        ``n`` vaut 1 par défaut : quand on a envie de parler, on pense à
        quelqu'un, pas à une liste.

        Trois règles, chacune contre une façon d'être inhumaine :

        * **le silence se mesure au rythme du lien** (``_rythme_naturel``) —
          la médiane des écarts entre les jours où la personne écrit. Un ami
          quotidien manque au bout de deux jours, un ami mensuel jamais avant
          des semaines. Le seuil unique était l'arbitraire que ceci remplace ;
        * **elle ne double-texte pas** : si son dernier message à cette
          personne est resté sans réponse, il faut ``recontact_relance_facteur``
          fois plus de silence avant de la re-proposer — on re-tente après un
          vrai moment, on ne harcèle pas ;
        * **elle pense d'abord à ceux qu'elle aime** : priorité = (silence ÷
          rythme) × poids de closeness × chaleur de l'ancre affective
          (``_chaleur_pour``) — le fond chaud attire, la rancune fait reculer.

        La date du dernier échange se lit sur ``Message`` via les handles de
        la couche identité, jamais sur ``PersonProfile.last_interaction_at`` :
        celui-ci n'est écrit qu'à la régénération de la fiche (gated ≥24 h),
        et « sans nouvelles depuis 12 jours » à propos de quelqu'un qui a
        écrit hier est exactement le genre de faux qui rend le personnage
        bête. Coût : trois requêtes bornées, sur le chemin d'un acte — jamais
        dans la boucle de décision, qui n'a donc pas besoin de cache RAM.

        Même contrat de retour que ``who_is_concerned`` (nom + handles
        joignables + ``note``). Ne lève jamais : rend ``[]``.
        """
        from asgiref.sync import sync_to_async

        from communication.presence import presence_registry
        from identity.resolver import identity_resolver

        facteur = cfg_float(
            "conscience.recontact_facteur", RECONTACT_FACTEUR, mini=0.1,
        )
        relance = cfg_float(
            "conscience.recontact_relance_facteur", RECONTACT_RELANCE_FACTEUR,
            mini=1.0,
        )
        ami_jours = cfg_int(
            "conscience.recontact_rythme_ami_jours",
            RECONTACT_RYTHME_AMI_JOURS, mini=1,
        )
        proche_jours = cfg_int(
            "conscience.recontact_rythme_proche_jours",
            RECONTACT_RYTHME_PROCHE_JOURS, mini=1,
        )

        def _profils() -> list[tuple[str, str]]:
            from memory.models import PersonProfile

            return list(
                PersonProfile.objects.filter(
                    closeness__in=[
                        PersonProfile.Closeness.FRIEND,
                        PersonProfile.Closeness.CLOSE,
                    ],
                )
                .select_related("entity")
                .values_list("entity__name", "closeness")[:_RECONTACT_PROFILS_MAX]
            )

        try:
            profils = await sync_to_async(_profils)()
        except Exception as exc:
            degradations.record("conscience: profils a recontacter", exc)
            return []
        if not profils:
            return []

        try:
            handle_map = await identity_resolver.handles_for_entity_names(
                [nom for nom, _ in profils]
            )
        except Exception as exc:
            degradations.record("conscience: handles a recontacter", exc)
            return []

        tous_pids = [
            h["person_id"]
            for handles in handle_map.values()
            for h in handles
        ]
        if not tous_pids:
            return []

        def _traces() -> tuple[dict, dict, list]:
            """Dernier mot reçu, dernier mot envoyé, jours actifs — 3 requêtes.

            ``exclude(is_internal=True)`` sur les trois : le brief interne
            d'un acte adressé à Alice est persisté ``role="user"`` sous SON
            person_id — sans l'exclusion, le ping de Mika compterait comme un
            mot reçu d'Alice (le silence se mesurerait depuis sa propre
            relance, la note mentirait) et ses briefs feraient des « jours
            actifs » dans le rythme du lien. Côté sortant, la réplique de
            repli d'un tour échoué est aussi ``is_internal`` : un message
            jamais vraiment dit ne vaut pas une relance.
            """
            from datetime import timedelta

            from django.db.models import Max
            from django.db.models.functions import TruncDate
            from django.utils import timezone as tz

            from memory.models import Message

            entrants = {
                ligne["person_id"]: ligne["dernier"]
                for ligne in Message.objects.filter(
                    person_id__in=tous_pids, role="user",
                ).exclude(is_internal=True)
                .values("person_id").annotate(dernier=Max("created_at"))
            }
            sortants = {
                ligne["person_id"]: ligne["dernier"]
                for ligne in Message.objects.filter(
                    person_id__in=tous_pids, role="assistant",
                ).exclude(is_internal=True)
                .values("person_id").annotate(dernier=Max("created_at"))
            }
            cutoff = tz.now() - timedelta(days=_RYTHME_HISTORIQUE_JOURS)
            jours = list(
                Message.objects.filter(
                    person_id__in=tous_pids, role="user",
                    created_at__gte=cutoff,
                )
                .exclude(is_internal=True)
                .annotate(jour=TruncDate("created_at"))
                .values_list("person_id", "jour")
                .distinct()
            )
            return entrants, sortants, jours

        try:
            entrants, sortants, jours_par_pid = await sync_to_async(_traces)()
        except Exception as exc:
            degradations.record("conscience: traces d'echange par handle", exc)
            return []

        from django.utils import timezone as tz

        maintenant = tz.now()
        results: list[dict] = []
        hors_d_atteinte: list[tuple[float, str, int]] = []
        for nom, closeness in profils:
            handles = handle_map.get(nom, [])
            pids = {h["person_id"] for h in handles}
            recus = [entrants[p] for p in pids if p in entrants]
            if not recus:
                # Jamais un mot reçu : il n'y a rien à « reprendre ».
                continue
            dernier_recu = max(recus)
            silence_j = (maintenant - dernier_recu).total_seconds() / 86400.0

            rythme = _rythme_naturel(
                [jour for pid, jour in jours_par_pid if pid in pids],
                closeness, ami_jours=ami_jours, proche_jours=proche_jours,
            )
            if silence_j < rythme * facteur:
                continue

            envoyes = [sortants[p] for p in pids if p in sortants]
            dernier_envoye = max(envoyes) if envoyes else None
            if dernier_envoye is not None and dernier_envoye > dernier_recu:
                attente_j = (maintenant - dernier_envoye).total_seconds() / 86400.0
                if attente_j < rythme * facteur * relance:
                    continue

            poids = 1.5 if closeness == "close" else 1.0
            reachable = [
                h for h in handles
                if h["kind"] == "module"
                or presence_registry.resolve_on(h["person_id"], h["channel"])
            ]
            if not reachable:
                # Le manque sans destinataire ne s'évapore plus : il devient
                # une pensée (« j'aimerais avoir des nouvelles de… ») qu'elle
                # pourra dire à qui EST là — le plus fort seulement, après la
                # boucle.
                hors_d_atteinte.append(
                    ((silence_j / rythme) * poids, nom, int(silence_j))
                )
                continue
            chaleur = await self._chaleur_pour([h["person_id"] for h in reachable])
            results.append({
                "name": nom,
                "score": round((silence_j / rythme) * poids * chaleur, 3),
                "handles": reachable,
                "note": (
                    f"sans nouvelles depuis {int(silence_j)} jour(s) — "
                    f"d'habitude vous vous parlez tous les {rythme:.0f} jour(s)"
                ),
            })

        if hors_d_atteinte:
            _, nom, jours = max(hors_d_atteinte)
            with degraded("conscience: pensee pour un absent"):
                await self._penser_a_l_absent(nom, jours)

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[: max(1, n)]

    #: Intensité de la pensée pour un absent. Volontairement SOUS la porte de
    #: graine (0.40) : penser à quelqu'un d'injoignable ne doit pas ouvrir un
    #: chantier — il n'y a rien à y faire — seulement colorer le prompt
    #: (plancher d'affichage 0.2) et pouvoir se dire à qui est là.
    _PENSEE_ABSENT_INTENSITE = 0.3

    #: Ce que coûte une croyance qui s'effondre : la secousse (surprise) et
    #: le résidu (une pensée confuse — « je croyais que… »). Constantes, pas
    #: des clés : même famille que les ancres PAD, la physique du personnage.
    _REVISION_SURPRISE = 0.35
    _REVISION_PENSEE_INTENSITE = 0.3

    async def _ressentir_la_revision(self, contenu: str) -> None:
        """Une croyance invalidée se ressent et se re-raconte. Ne lève jamais.

        Deux moitiés, comme chez l'humain : la **secousse** — une impulsion
        `surprised` sur son propre oscillateur — puis le **résidu** — une
        rumination `confused` (« Je croyais que… — apparemment non ») qui
        vivra sa demi-vie, teintera l'humeur, pourra se dire à qui est là et
        sera digérée la nuit. Sous la porte de graine : réviser une croyance
        est un fait accompli, pas un chantier à ouvrir. Dédupliquée sur
        l'extrait : la même révision ne se rumine pas en double.
        """
        from asgiref.sync import sync_to_async

        with degraded("conscience: surprise d'une revision"):
            from emotion.engine import emotion_engine
            from emotion.types import Emotion, EmotionData

            emotion_engine.process_emotion(
                EmotionData(Emotion.SURPRISED, self._REVISION_SURPRISE),
                "conscience_mika",
            )

        extrait = str(contenu or "").strip()[:80]
        if not extrait:
            return

        def _ecrire() -> None:
            from conscience.models import Rumination

            if Rumination.objects.filter(
                status="active", summary__contains=extrait[:40],
            ).exists():
                return
            Rumination.objects.create(
                summary=(
                    f"Je croyais que « {extrait} » — "
                    "apparemment ce n'est plus vrai."
                ),
                themes=[],
                intensity=self._REVISION_PENSEE_INTENSITE,
                emotion="confused",
                status="active",
                origine=Rumination.Origine.REVISION,
            )

        with degraded("conscience: pensee d'une revision"):
            await sync_to_async(_ecrire, thread_sensitive=True)()

    async def _penser_a_l_absent(self, nom: str, jours: int) -> bool:
        """« J'aimerais bien avoir des nouvelles de X » — une rumination.

        Dédupliquée sur le nom : une pensée active qui le mentionne déjà
        suffit, et sa demi-vie (6 h) fait qu'elle ne revient au mieux qu'une
        fois par demi-journée. Émotion `nostalgic` — le manque d'un absent,
        pas la solitude (`lonely` parlerait d'elle).
        """
        from asgiref.sync import sync_to_async

        from conscience.models import Rumination

        def _ecrire() -> bool:
            if Rumination.objects.filter(
                status="active", summary__contains=nom,
            ).exists():
                return False
            Rumination.objects.create(
                summary=(
                    f"J'aimerais bien avoir des nouvelles de {nom} — "
                    f"ça fait {jours} jour(s)."
                ),
                themes=[nom],
                intensity=self._PENSEE_ABSENT_INTENSITE,
                emotion="nostalgic",
                status="active",
                origine=Rumination.Origine.MANQUE,
            )
            return True

        return await sync_to_async(_ecrire, thread_sensitive=True)()

    async def who_comforts(self, n: int = 1) -> list[dict]:
        """Vers qui aller quand ça ne va pas — le réconfort, pas le manque.

        La régulation émotionnelle humaine est massivement sociale : en
        détresse, on cherche le proche *auprès de qui on se sent bien* — pas
        celui qui manque depuis longtemps. Donc AUCUNE des portes du manque
        (ni rythme, ni silence minimal, ni anti-double-texte) : avoir parlé à
        quelqu'un hier n'empêche pas d'aller vers lui ce soir quand ça va
        mal. Le classement est le lien × la chaleur de l'ancre affective —
        littéralement « je me sens bien avec toi ».

        Même contrat de retour que ``who_is_concerned``. Ne lève jamais.
        L'appelant ne consulte ceci que sur détresse soutenue, et le backoff
        des relances ignorées borne déjà la fréquence des actes.
        """
        from asgiref.sync import sync_to_async

        from communication.presence import presence_registry
        from identity.resolver import identity_resolver

        def _profils() -> list[tuple[str, str]]:
            from memory.models import PersonProfile

            return list(
                PersonProfile.objects.filter(
                    closeness__in=[
                        PersonProfile.Closeness.FRIEND,
                        PersonProfile.Closeness.CLOSE,
                    ],
                )
                .select_related("entity")
                .values_list("entity__name", "closeness")[:_RECONTACT_PROFILS_MAX]
            )

        try:
            profils = await sync_to_async(_profils)()
            if not profils:
                return []
            handle_map = await identity_resolver.handles_for_entity_names(
                [nom for nom, _ in profils]
            )
        except Exception as exc:
            degradations.record("conscience: profils de reconfort", exc)
            return []

        results: list[dict] = []
        for nom, closeness in profils:
            handles = handle_map.get(nom, [])
            reachable = [
                h for h in handles
                if h["kind"] == "module"
                or presence_registry.resolve_on(h["person_id"], h["channel"])
            ]
            if not reachable:
                continue
            poids = 1.5 if closeness == "close" else 1.0
            chaleur = await self._chaleur_pour(
                [h["person_id"] for h in reachable]
            )
            results.append({
                "name": nom,
                "score": round(poids * chaleur, 3),
                "handles": reachable,
                "note": (
                    "tu ne te sens pas bien — c'est quelqu'un auprès de qui "
                    "tu te sens bien"
                ),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[: max(1, n)]

    async def _chaleur_pour(self, person_ids: list[str]) -> float:
        """1 + la chaleur du fond affectif vers cette personne, en [1, 1.5].

        L'ancre de ``PersonMood`` est le fond que les conversations ont
        installé (et que le temps guérit) : sa composante plaisir positive
        dit « penser à elle fait du bien ». Une ancre froide ou absente vaut
        1.0 — la rancune ne *supprime* pas le manque, elle cesse seulement de
        l'amplifier. ``ensure_person_loaded`` d'abord : lire ``person_moods``
        à froid est le bug documenté de la fiche affect.
        """
        try:
            from emotion.engine import emotion_engine

            meilleur = 0.0
            for pid in person_ids[:3]:
                await emotion_engine.ensure_person_loaded(pid)
                mood = emotion_engine.person_moods.get(pid)
                ancre = getattr(mood, "anchor", None)
                if ancre:
                    meilleur = max(meilleur, float(ancre[0]))
            return 1.0 + _CHALEUR_POIDS * max(0.0, min(1.0, meilleur))
        except Exception as exc:
            degradations.record("conscience: chaleur du manque", exc)
            return 1.0

    @staticmethod
    def _person_entities_from_matches(
        souvenirs: list[dict], connaissances: list[dict]
    ) -> dict[str, float]:
        """Aggregate person-entity names from matched memories, relevance-weighted."""
        from memory.models import Connaissance, Souvenir

        scores: dict[str, float] = {}

        def accumulate(matches, model):
            # Une seule requete par modele, pas une par resultat : `n` est un
            # parametre d'appel qui peut grandir, et un `prefetch_related` sur
            # un `get()` unitaire ajoute un aller-retour au lieu d'en
            # economiser. Les pk disparus sont simplement absents du filtre.
            relevances: dict[int, float] = {}
            for r in matches:
                try:
                    pk = int(r["id"])
                except (KeyError, ValueError, TypeError):
                    continue
                distance = r.get("distance")
                relevance = max(0.0, 1.0 - distance) if distance is not None else 0.5
                relevances[pk] = relevances.get(pk, 0.0) + relevance

            if not relevances:
                return

            for obj in model.objects.filter(
                pk__in=list(relevances)
            ).prefetch_related("entities"):
                relevance = relevances[obj.pk]
                for entity in obj.entities.all():
                    if entity.entity_type == "person":
                        scores[entity.name] = scores.get(entity.name, 0.0) + relevance

        accumulate(souvenirs, Souvenir)
        accumulate(connaissances, Connaissance)
        return scores

    # ── Write: Create ────────────────────────────────────────────

    async def create_souvenir_from_signal(self, signal: InterpretedSignal):
        """Create a Souvenir from an interpreted signal."""
        from memory.manager import memory_manager

        return await memory_manager.create_souvenir(
            content=signal.summary,
            emotion=signal.emotional_reaction or "neutral",
            importance=signal.pertinence,
        )

    #: Importance d'un travail mené au bout. Modeste et au-dessus du défaut
    #: d'extraction (0.5) : finir quelque chose qu'on a soi-même entrepris
    #: marque plus qu'un fait moyen, moins qu'un moment fort de conversation.
    _COMPLETED_WORK_IMPORTANCE = 0.55

    async def remember_completed_work(
        self, titre: str, essence: str = "", notable: float | None = None,
    ):
        """Un chantier abouti devient un souvenir à la première personne.

        C'est la moitié mémoire de « aller au bout » : sans elle, un travail
        terminé n'existait que dans sa ligne ``Travail`` — invisible du
        rappel, du récit de soi et des fiches. ``proud`` parce que c'est
        l'émotion que la diffusion d'un travail fini déclare déjà
        (``_peut_etre_dire_le_travail``) : une seule vérité émotionnelle pour
        un même événement.
        """
        from memory.manager import memory_manager

        titre = str(titre or "").strip()
        if not titre:
            return None
        contenu = f"J'ai mené au bout quelque chose que j'avais entrepris : {titre}."
        essence = str(essence or "").strip()
        if essence:
            contenu += f" {essence}"
        # L'importance suit ce que le verdict a jugé notable : à 0,55 fixe,
        # « [France Info] titre » commenté passait devant les vraies
        # conversations (0,44) dans le rappel (MEM-11 / DEF-13).
        if notable is None:
            importance = self._COMPLETED_WORK_IMPORTANCE
        else:
            importance = 0.25 + 0.4 * max(0.0, min(1.0, float(notable)))
        return await memory_manager.create_souvenir(
            content=contenu[:600],
            emotion="proud",
            importance=importance,
        )

    # ── Write: Modify Importance ─────────────────────────────────

    async def boost_related_souvenirs(
        self, themes: list[str], boost: float = 0.1
    ) -> int:
        """Boost importance of souvenirs linked to given themes."""
        from memory.manager import memory_manager
        return await memory_manager.boost_souvenirs_by_themes(themes, boost)

    # ── Write: Connaissances ─────────────────────────────────────

    # Budget par appel de validation, et non par lot. `check_connaissance_validity`
    # porte deja `EXTRACTION_TIMEOUT` (45 s), taille pour le consolidateur ; la
    # boucle de decision, elle, valide jusqu'a cinq candidats en serie et le fait
    # `_decision_lock` tenu. Au budget du consolidateur, une seule observation
    # pouvait retenir le verrou pres de quatre minutes, pendant lesquelles tous
    # les cycles suivants — fast-path haute pertinence compris — retombent sur le
    # `return` silencieux de `_decide()`. Un appelant qui borne plus court que la
    # borne routee (`ai.call_timeout_seconds`) gagne toujours.
    _VALIDITY_TIMEOUT_S = 15

    async def check_contradictions(self, new_info: str) -> list[dict]:
        """Check if new information contradicts existing connaissances.

        Uses vector search to find only RELEVANT connaissances (max 5),
        then validates each with an LLM call, bornee a `_VALIDITY_TIMEOUT_S`.

        Returns list of {connaissance_id, content, still_valid, new_confidence}.
        """
        from memory.extraction import MemoryExtractor
        from memory.manager import memory_manager

        results = []
        extractor = MemoryExtractor()

        try:
            candidates = []
            raw = await memory_manager.search_related_connaissances(new_info, n=5)
            for r in raw:
                try:
                    pk = int(r["id"])
                except (ValueError, KeyError):
                    continue
                conn = await memory_manager.get_valid_connaissance(pk)
                if conn:
                    candidates.append(conn)

            if not candidates:
                return results

            budget = cfg_int(
                "conscience.validity_timeout_seconds",
                self._VALIDITY_TIMEOUT_S, mini=1,
            )
            for conn in candidates:
                try:
                    still_valid, new_confidence = await asyncio.wait_for(
                        extractor.check_connaissance_validity(
                            conn.content, new_info
                        ),
                        timeout=budget,
                    )
                except asyncio.TimeoutError as exc:
                    degradations.record(
                        "conscience: validation de connaissance expiree", exc
                    )
                    logger.warning(
                        "Validity check timed out after %ds for connaissance #%d",
                        budget, conn.pk,
                    )
                    continue
                except Exception as exc:
                    degradations.record("conscience: validation de connaissance", exc)
                    logger.warning(
                        "Validity check failed for connaissance #%d", conn.pk
                    )
                    continue

                if not still_valid:
                    await memory_manager.invalidate_connaissance(
                        conn.pk, reason=f"Contradicted by: {new_info[:100]}"
                    )
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": False,
                        "new_confidence": new_confidence,
                    })
                    # Cesser de croire coûte quelque chose. L'invalidation
                    # était un UPDATE silencieux : elle pouvait affirmer une
                    # chose lundi, son contraire mardi, sans jamais habiter la
                    # transition — le « tell » logiciel le plus visible en
                    # conversation.
                    await self._ressentir_la_revision(conn.content)
                # Seulement a la baisse : un controle qui ne contredit rien
                # n'est pas une reconfirmation, et le modele recopie volontiers
                # la valeur haute de l'exemple. Une remontee effacerait la
                # decroissance lente (`_decay_connaissances`) et les baisses
                # decidees ailleurs, sans laisser de trace dans les resultats.
                # La hausse deliberee, elle, passe par
                # `memory_manager.reinforce_connaissance`.
                elif new_confidence is not None and new_confidence < conn.confidence:
                    await memory_manager.update_connaissance_confidence(
                        conn.pk, new_confidence
                    )
                    results.append({
                        "connaissance_id": conn.pk,
                        "content": conn.content,
                        "still_valid": True,
                        "new_confidence": new_confidence,
                    })

        except Exception:
            logger.exception("check_contradictions failed")

        return results
