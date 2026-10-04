"""Memory tools — Mika's active recall, exposed on the module bus.

Until now, long-term memory was push-only: `gather_context()` decided
what she recalls, and she could not dig further. These tools give her
agency over her own memory during a conversation:

  - memory_search           semantic search (souvenirs + connaissances)
  - memory_recent_souvenirs what marked her recently
  - memory_read_journal     reread her daily journals ("qu'a-t-on fait mardi ?")
  - memory_list_commitments her open promises
  - memory_resolve_commitment close a promise (tenu / abandonné)

Thin adapter over ``memory_manager`` + the ORM, same pattern as
``files/module.py``: SYSTEM module, no own models, no config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from old.backend.configs.runtime import cfg_int
from old.backend.modules.base import BaseModule
from old.backend.modules.types import ModuleTool, ToolParameter, ToolParameterType
from old.backend.memory import read
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)

# Ceilings so a tool answer never blows up the conversation budget.
# Réglables (``memory.tools_*``) ; ce qui reste ici est le repli.
MAX_SEARCH_RESULTS = 8
MAX_JOURNALS = 7

REFUS_JOURNAL = (
    "Tu n'es pas assez sure de qui tu as en face pour relire ton journal a "
    "voix haute : il raconte tes journees et les gens que tu as croises."
)
REFUS_ENGAGEMENTS = (
    "Tu ne sais pas assez qui tu as en face pour parler de tes engagements : "
    "ils concernent d'autres personnes."
)
REFUS_RECHERCHE = (
    "Tu ne sais pas assez qui tu as en face pour fouiller ce que d'autres "
    "t'ont confie. Reste sur ce que tu sais de general."
)


@dataclass(frozen=True)
class _Perimetre:
    """Ce que le tour en cours a le droit de sortir de la memoire.

    ``divulgation`` est la porte binaire de la FICHE de l'interlocuteur
    (journal, engagements — ``may_disclose``) ; ``niveau`` est le niveau
    gradué sur AUTRUI (``identity.divulgation``), le meme que celui du
    bloc ``--- TES SOUVENIRS ---`` du tour.
    """

    interne: bool
    divulgation: bool
    entity_id: int | None
    niveau: object = None  # identity.divulgation.Divulgation

    def __post_init__(self):
        if self.niveau is None:
            from old.backend.identity.divulgation import FERME, TOUT

            object.__setattr__(self, "niveau", TOUT if self.interne else FERME)


async def _perimetre() -> _Perimetre:
    """Qui appelle l'outil, et jusqu'ou peut-il lire.

    Les outils memoire sont exposes a *toutes* les conversations, alors que
    le bloc prompt equivalent passe par ``may_disclose_private_context``.
    Sans cette porte, un inconnu obtient par l'outil la fiche que le prompt
    lui refuse — meme defaut que celui deja corrige dans ``files/service.py``.

    Un ``person_id`` interne (conscience, projets, boucle de fond) n'a
    personne en face : acces complet. Une panne de la couche identite ferme
    la porte plutot que de l'ouvrir — c'est une porte.
    """
    from old.backend.identity.trust import is_internal_person
    from old.backend.pipeline.tracing import current_person_id

    person_id = current_person_id()
    if is_internal_person(person_id):
        return _Perimetre(True, True, None)
    try:
        from old.backend.identity.resolver import identity_resolver
        from old.backend.pipeline.context_blocks import divulgation_du_tour

        ctx = await identity_resolver.resolve_context(person_id)
        return _Perimetre(
            False, bool(ctx.may_disclose), ctx.entity_id,
            niveau=await divulgation_du_tour(ctx),
        )
    except Exception as exc:
        degradations.record("outils memoire: perimetre", exc)
        return _Perimetre(False, False, None)


def _pk_of(row) -> int | None:
    """Le pk ORM d'une ligne ChromaDB (``id`` textuel) ou d'une ligne ORM."""
    brut = row.get("id") if isinstance(row, dict) else getattr(row, "pk", None)
    try:
        return int(brut)
    except (TypeError, ValueError):
        return None


async def _selon_le_niveau(rows: list, model, perimetre: _Perimetre) -> list:
    """Applique le niveau du tour ligne par ligne, comme le rappel du prompt.

    Rend ``[(ligne, tag)]`` : une ligne qui concerne un tiers et pese plus
    que le niveau est ecartee ; en dessous mais pas anodine, elle sort avec
    son tag d'arbitrage. Une ligne dont le pk est illisible est ecartee elle
    aussi : on ne peut pas verifier de qui elle parle. Un appelant interne
    garde tout, sans tag.
    """
    if not rows:
        return []
    if perimetre.interne:
        return [(r, "") for r in rows]
    from old.backend.memory import sensibilite

    pks = [_pk_of(r) for r in rows]
    try:
        qualifs = await read.qualifications(
            model, pks, entity_id=perimetre.entity_id,
        )
    except Exception as exc:
        degradations.record("outils memoire: filtrage tiers", exc)
        return []
    out = []
    for r, pk in zip(rows, pks):
        if pk is None or pk not in qualifs:
            continue
        q = qualifs[pk]
        if not sensibilite.admissible(q, perimetre.niveau):
            continue
        out.append((r, sensibilite.tag(q)))
    return out


class MemoryToolsModule(BaseModule):
    """MCP adapter around memory_manager + memory models."""

    SYSTEM = True

    #: Cadence du rafraîchissement des sujets offerts (voir `propose_sujets`).
    #: Une connaissance ne s'érode qu'à l'heure : recompter plus souvent ne
    #: mesurerait que le même état.
    CRON_INTERVAL = 1800

    #: Bande de confiance d'une connaissance « à vérifier ». Sous 0.25 elle
    #: est presque morte (le doute n'a plus d'objet), au-dessus de 0.55 elle
    #: se porte bien — entre les deux vit exactement le « je crois savoir,
    #: mais est-ce encore vrai ? » qui fait une curiosité épistémique.
    _DOUTE_CONFIANCE_MIN = 0.25
    _DOUTE_CONFIANCE_MAX = 0.55
    #: Sujets offerts au plus. Une curiosité, pas un inventaire — même règle
    #: que la récolte des graines.
    _SUJETS_MAX = 2

    def __init__(self) -> None:
        super().__init__("memory_tools")
        # Instantané pour la boucle de décision. Tenu en RAM et rafraîchi par
        # le cron, jamais lu en base au moment de proposer : `propose_sujets`
        # est appelé depuis le cycle de décision (2 880 tours/jour), où toute
        # requête ORM depuis une coroutine lève `SynchronousOnlyOperation` —
        # même motif que les compteurs RSS et email.
        self._sujets: list[str] = []

    async def instantiate(self) -> None:
        from asgiref.sync import sync_to_async

        # Sans ça, le réservoir n'existe qu'après le premier tick de cron,
        # soit trente minutes de « rien à proposer » à chaque redémarrage.
        await sync_to_async(self._rafraichir_sujets)()

    async def shutdown(self) -> None:
        return None

    async def worker_cron(self) -> None:
        from asgiref.sync import sync_to_async

        await sync_to_async(self._rafraichir_sujets)()

    def _rafraichir_sujets(self) -> None:
        """Recompte ce que sa mémoire offre à sa curiosité. Sous `sync_to_async`.

        Une **connaissance érodée** — la confiance a décru sans qu'elle soit
        invalidée — est un doute qui a un objet : « je croyais savoir X,
        est-ce encore vrai ? ». C'est le sujet de chantier le plus honnête
        que la mémoire puisse offrir : le vérifier se fait avec les outils
        du socle (`memory_search`) et, curiosité aidant, `rss`.

        Un échec garde le dernier réservoir connu plutôt que de le vider :
        perdre les sujets parce qu'un recompte a raté rendrait la panne
        indiscernable d'une mémoire sereine. Compté au registre.
        """
        from old.backend.memory.models import Connaissance

        try:
            douteuses = list(
                Connaissance.objects.filter(
                    is_valid=True,
                    confidence__gte=self._DOUTE_CONFIANCE_MIN,
                    confidence__lte=self._DOUTE_CONFIANCE_MAX,
                )
                # Les plus hautes de la bande d'abord : le doute qui compte
                # est celui d'une croyance encore à moitié tenue, pas d'une
                # ligne déjà presque morte. (`Connaissance` n'a pas
                # d'importance propre — la confiance EST sa mesure.)
                .order_by("-confidence", "-updated_at")
                .values_list("content", flat=True)[: self._SUJETS_MAX]
            )
            self._sujets = [
                f"vérifier si c'est toujours vrai : « {contenu[:90]} »"
                for contenu in douteuses
                if str(contenu or "").strip()
            ]
        except Exception as exc:
            degradations.record("memory.module._rafraichir_sujets", exc)
            self.logger.debug("rafraichissement des sujets memoire rate",
                              exc_info=True)

    def propose_sujets(self) -> list[str]:
        """Ses doutes, comme sujets de chantier — lecture RAM pure.

        Même contrat que RSS, email et forge : appelable depuis la boucle de
        décision sans une requête. Le chantier ouvert emporte `memory_tools`
        via `Graine.modules` — déjà au socle, la demande est inoffensive."""
        return list(self._sujets)

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="memory_search",
                description=(
                    "Cherche dans ta memoire long-terme (souvenirs vecus et "
                    "connaissances factuelles) par similarite semantique. "
                    "Utilise-le quand on te demande si tu te souviens de "
                    "quelque chose, ou pour verifier un fait avant de repondre."
                ),
                parameters=[
                    ToolParameter("query", ToolParameterType.STRING, "Ce que tu cherches (question ou mots-cles)"),
                    ToolParameter(
                        "kind", ToolParameterType.STRING,
                        "Type de memoire: 'all' (defaut), 'souvenirs' ou 'connaissances'",
                        required=False, default="all",
                        enum=["all", "souvenirs", "connaissances"],
                    ),
                ],
                handler=self._search,
            ),
            ModuleTool(
                name="memory_recent_souvenirs",
                description=(
                    "Liste tes souvenirs recents les plus importants "
                    "(ce qui t'a marquee ces derniers temps)."
                ),
                parameters=[
                    ToolParameter(
                        "limit", ToolParameterType.INTEGER,
                        "Nombre de souvenirs (defaut 5, max 10)",
                        required=False, default=5,
                    ),
                ],
                handler=self._recent_souvenirs,
            ),
            ModuleTool(
                name="memory_read_journal",
                description=(
                    "Relis ton journal quotidien (ecrit chaque nuit pendant ton "
                    "sommeil leger). Sans date: les derniers jours. Avec date "
                    "(YYYY-MM-DD): ce jour precis. Utile pour 'qu'est-ce qu'on "
                    "a fait hier / la semaine derniere ?'"
                ),
                parameters=[
                    ToolParameter(
                        "date", ToolParameterType.STRING,
                        "Date precise YYYY-MM-DD (optionnel)",
                        required=False, default="",
                    ),
                    ToolParameter(
                        "limit", ToolParameterType.INTEGER,
                        "Nombre de journaux si pas de date (defaut 3, max 7)",
                        required=False, default=3,
                    ),
                ],
                handler=self._read_journal,
            ),
            ModuleTool(
                name="memory_list_commitments",
                description=(
                    "Liste les engagements que tu as pris ('je te ferai...', "
                    "'promis je...'). Par defaut seulement ceux encore en attente."
                ),
                parameters=[
                    ToolParameter(
                        "include_resolved", ToolParameterType.BOOLEAN,
                        "Inclure aussi les engagements deja tenus/abandonnes",
                        required=False, default=False,
                    ),
                ],
                handler=self._list_commitments,
            ),
            ModuleTool(
                name="memory_resolve_commitment",
                description=(
                    "Marque un de tes engagements comme tenu ('honored') ou "
                    "abandonne ('dropped'). Utilise-le des que tu viens de "
                    "faire ce que tu avais promis, ou si l'engagement n'a "
                    "plus de sens."
                ),
                parameters=[
                    ToolParameter("commitment_id", ToolParameterType.INTEGER, "ID de l'engagement (via memory_list_commitments)"),
                    ToolParameter(
                        "status", ToolParameterType.STRING,
                        "'honored' (tenu) ou 'dropped' (abandonne)",
                        required=False, default="honored",
                        enum=["honored", "dropped"],
                    ),
                ],
                handler=self._resolve_commitment,
            ),
        ]

    # ── Handlers ──────────────────────────────────────────────────

    @staticmethod
    async def _search(params: dict) -> dict:
        from old.backend.memory.manager import memory_manager

        query = (params.get("query") or "").strip()
        if not query:
            return {"error": "query vide"}
        kind = (params.get("kind") or "all").strip().lower()

        plafond = cfg_int(
            "memory.tools_max_search_results", MAX_SEARCH_RESULTS, mini=1, maxi=50,
        )
        souvenirs: list[dict] = []
        connaissances: list[dict] = []
        if kind in ("all", "souvenirs"):
            # 0 : une recherche délibérée retrouve aussi les souvenirs
            # endormis (importance 0,02) — la doctrine « l'oubli déplace,
            # il ne détruit pas » était fausse pour cet outil.
            souvenirs = await memory_manager.search_related_souvenirs(
                query, n=plafond, min_importance=0.0,
            )
        if kind in ("all", "connaissances"):
            connaissances = await memory_manager.search_related_connaissances(
                query, n=plafond
            )

        from old.backend.memory.models import Connaissance, Souvenir

        perimetre = await _perimetre()
        retenus_s = await _selon_le_niveau(souvenirs, Souvenir, perimetre)
        retenues_c = await _selon_le_niveau(connaissances, Connaissance, perimetre)
        ecarte = len(retenus_s) < len(souvenirs) or len(retenues_c) < len(connaissances)
        if ecarte and not retenus_s and not retenues_c:
            return {"message": REFUS_RECHERCHE}

        def _fmt(row: dict, tag: str) -> dict:
            meta = row.get("metadata") or {}
            out = {"content": row.get("content", "") + tag}
            if meta.get("emotion"):
                out["emotion"] = meta["emotion"]
            if meta.get("occurred_at"):
                out["date"] = str(meta["occurred_at"])[:10]
            return out

        if not retenus_s and not retenues_c:
            return {"message": "Rien trouve dans ta memoire pour cette recherche."}
        return {
            "souvenirs": [_fmt(r, tag) for r, tag in retenus_s],
            "connaissances": [_fmt(r, tag) for r, tag in retenues_c],
        }

    @staticmethod
    async def _recent_souvenirs(params: dict) -> dict:
        from old.backend.memory.manager import memory_manager

        limit = max(1, min(10, int(params.get("limit") or 5)))
        rows = await memory_manager.get_important_souvenirs(
            min_importance=0.3, limit=limit
        )
        from old.backend.memory.models import Souvenir

        perimetre = await _perimetre()
        retenus = await _selon_le_niveau(rows, Souvenir, perimetre)
        if rows and not retenus:
            return {"message": REFUS_RECHERCHE}
        if not retenus:
            return {"message": "Aucun souvenir marquant recemment."}
        return {
            "souvenirs": [
                {
                    "content": s.content + tag,
                    "emotion": s.emotion,
                    "date": s.occurred_at.date().isoformat() if s.occurred_at else "",
                    "importance": round(s.importance, 2),
                }
                for s, tag in retenus
            ]
        }

    @staticmethod
    async def _read_journal(params: dict) -> dict:
        from asgiref.sync import sync_to_async
        from old.backend.memory.models import DailyJournal

        # Un journal nomme les gens croises dans la journee : il est du
        # meme cote de la porte que la fiche d'une personne.
        perimetre = await _perimetre()
        if not perimetre.interne and not perimetre.divulgation:
            return {"message": REFUS_JOURNAL}

        date_str = (params.get("date") or "").strip()
        max_journaux = cfg_int(
            "memory.tools_max_journals", MAX_JOURNALS, mini=1, maxi=50,
        )

        def _fetch() -> list[DailyJournal]:
            qs = DailyJournal.objects.order_by("-date")
            if date_str:
                return list(qs.filter(date=date_str)[:1])
            limit = max(1, min(max_journaux, int(params.get("limit") or 3)))
            return list(qs[:limit])

        try:
            journals = await sync_to_async(_fetch)()
        except Exception:
            logger.exception("memory_read_journal fetch failed")
            return {"error": "Lecture du journal impossible."}

        if not journals:
            return {
                "message": (
                    f"Pas de journal pour {date_str}." if date_str
                    else "Aucun journal ecrit pour le moment."
                )
            }
        return {
            "journaux": [
                {
                    "date": j.date.isoformat(),
                    "recit": j.narrative,
                    "emotion_dominante": j.dominant_emotion,
                    "personnes": j.persons_interacted,
                }
                for j in journals
            ]
        }

    @staticmethod
    async def _list_commitments(params: dict) -> dict:
        from asgiref.sync import sync_to_async
        from old.backend.memory.models import Commitment

        include_resolved = bool(params.get("include_resolved"))

        perimetre = await _perimetre()
        if not perimetre.interne and not perimetre.divulgation:
            return {"message": REFUS_ENGAGEMENTS}

        def _fetch():
            from django.db.models import Q

            qs = Commitment.objects.select_related("person").order_by("-created_at")
            if not include_resolved:
                qs = qs.filter(status="pending")
            if not perimetre.interne:
                # Ce que la personne en face peut legitimement s'entendre
                # dire — exactement ce que le bloc prompt lui montre deja.
                qs = qs.filter(
                    Q(person__isnull=True) | Q(person_id=perimetre.entity_id)
                )
            return list(qs[:15])

        rows = await sync_to_async(_fetch)()
        if not rows:
            return {"message": "Aucun engagement en attente. Tu es a jour !"}
        return {
            "engagements": [
                {
                    "id": c.pk,
                    "description": c.description,
                    "envers": c.person.name if c.person else "",
                    "statut": c.status,
                    "depuis": c.created_at.date().isoformat(),
                }
                for c in rows
            ]
        }

    @staticmethod
    async def _resolve_commitment(params: dict) -> dict:
        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from old.backend.memory.models import Commitment

        try:
            commitment_id = int(params.get("commitment_id"))
        except (TypeError, ValueError):
            return {"error": "commitment_id manquant ou invalide"}
        status = (params.get("status") or "honored").strip().lower()
        if status not in ("honored", "dropped"):
            return {"error": "status doit etre 'honored' ou 'dropped'"}

        perimetre = await _perimetre()
        if not perimetre.interne and not perimetre.divulgation:
            return {"message": REFUS_ENGAGEMENTS}

        def _resolve() -> int:
            from django.db.models import Q

            qs = Commitment.objects.filter(pk=commitment_id, status="pending")
            if not perimetre.interne:
                # Hors perimetre, la reponse doit etre celle d'un id
                # inexistant : confirmer la ligne serait deja une fuite.
                qs = qs.filter(
                    Q(person__isnull=True) | Q(person_id=perimetre.entity_id)
                )
            return qs.update(status=status, resolved_at=timezone.now())

        updated = await sync_to_async(_resolve)()
        if not updated:
            return {"error": f"Engagement #{commitment_id} introuvable ou deja resolu."}
        label = "tenu" if status == "honored" else "abandonne"
        return {"success": True, "message": f"Engagement #{commitment_id} marque {label}."}
