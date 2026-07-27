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

from modules.base import BaseModule
from modules.types import ModuleTool, ToolParameter, ToolParameterType

logger = logging.getLogger(__name__)

# Ceilings so a tool answer never blows up the conversation budget.
MAX_SEARCH_RESULTS = 8
MAX_JOURNALS = 7


class MemoryToolsModule(BaseModule):
    """MCP adapter around memory_manager + memory models."""

    SYSTEM = True

    def __init__(self) -> None:
        super().__init__("memory_tools")

    async def instantiate(self) -> None:
        # The memory engine is initialized by the ASGI lifespan; the
        # tool facade has no state of its own.
        return None

    async def shutdown(self) -> None:
        return None

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
        from memory.manager import memory_manager

        query = (params.get("query") or "").strip()
        if not query:
            return {"error": "query vide"}
        kind = (params.get("kind") or "all").strip().lower()

        souvenirs: list[dict] = []
        connaissances: list[dict] = []
        if kind in ("all", "souvenirs"):
            souvenirs = await memory_manager.search_related_souvenirs(
                query, n=MAX_SEARCH_RESULTS
            )
        if kind in ("all", "connaissances"):
            connaissances = await memory_manager.search_related_connaissances(
                query, n=MAX_SEARCH_RESULTS
            )

        def _fmt(row: dict) -> dict:
            meta = row.get("metadata") or {}
            out = {"content": row.get("content", "")}
            if meta.get("emotion"):
                out["emotion"] = meta["emotion"]
            if meta.get("occurred_at"):
                out["date"] = str(meta["occurred_at"])[:10]
            return out

        if not souvenirs and not connaissances:
            return {"message": "Rien trouve dans ta memoire pour cette recherche."}
        return {
            "souvenirs": [_fmt(r) for r in souvenirs],
            "connaissances": [_fmt(r) for r in connaissances],
        }

    @staticmethod
    async def _recent_souvenirs(params: dict) -> dict:
        from memory.manager import memory_manager

        limit = max(1, min(10, int(params.get("limit") or 5)))
        rows = await memory_manager.get_important_souvenirs(
            min_importance=0.3, limit=limit
        )
        if not rows:
            return {"message": "Aucun souvenir marquant recemment."}
        return {
            "souvenirs": [
                {
                    "content": s.content,
                    "emotion": s.emotion,
                    "date": s.occurred_at.date().isoformat() if s.occurred_at else "",
                    "importance": round(s.importance, 2),
                }
                for s in rows
            ]
        }

    @staticmethod
    async def _read_journal(params: dict) -> dict:
        from asgiref.sync import sync_to_async
        from memory.models import DailyJournal

        date_str = (params.get("date") or "").strip()

        def _fetch() -> list[DailyJournal]:
            qs = DailyJournal.objects.order_by("-date")
            if date_str:
                return list(qs.filter(date=date_str)[:1])
            limit = max(1, min(MAX_JOURNALS, int(params.get("limit") or 3)))
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
        from memory.models import Commitment

        include_resolved = bool(params.get("include_resolved"))

        def _fetch():
            qs = Commitment.objects.select_related("person").order_by("-created_at")
            if not include_resolved:
                qs = qs.filter(status="pending")
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
        from memory.models import Commitment

        try:
            commitment_id = int(params.get("commitment_id"))
        except (TypeError, ValueError):
            return {"error": "commitment_id manquant ou invalide"}
        status = (params.get("status") or "honored").strip().lower()
        if status not in ("honored", "dropped"):
            return {"error": "status doit etre 'honored' ou 'dropped'"}

        def _resolve() -> int:
            return Commitment.objects.filter(
                pk=commitment_id, status="pending"
            ).update(status=status, resolved_at=timezone.now())

        updated = await sync_to_async(_resolve)()
        if not updated:
            return {"error": f"Engagement #{commitment_id} introuvable ou deja resolu."}
        label = "tenu" if status == "honored" else "abandonne"
        return {"success": True, "message": f"Engagement #{commitment_id} marque {label}."}
