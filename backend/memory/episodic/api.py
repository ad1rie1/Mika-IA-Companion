"""APIs de rappel de l'étage épisodique — la surface du planificateur.

Deux gestes :

- :func:`search_exchanges` — le vecteur **localise** dans les échanges bruts,
  avec résolution par personne *au moment de la requête* via la couche
  identité (jamais d'égalité de nom, jamais de réindexation au binding).
- :func:`fetch_verbatim` / :func:`expand_hit` — le SQL **cite** : les messages
  exacts autour d'un hit. Sémantique pour trouver, verbatim pour citer —
  aucun résumé entre les deux.

Tout échec dégrade en résultat vide (`degradations.record`) : le rappel
épisodique est une amélioration, jamais une dépendance du tour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from asgiref.sync import sync_to_async

from memory.storage.vector_store import vector_call
from memory.storage.window import user_facing_messages
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Bonus de distance pour un hit confirmé par le filtre plein-texte : un chunk
# qui contient le nom propre EST plus pertinent que l'embedding seul ne le dit.
_CONTAINS_BONUS = 0.05


@dataclass(frozen=True)
class ExchangeHit:
    chunk_id: str
    content: str
    handle: str
    conversation_id: int
    first_message_id: int
    last_message_id: int
    ts: float
    distance: float | None


def _store():
    from memory.manager import memory_manager

    return memory_manager.vector_store


def _hit_from_raw(raw: dict) -> ExchangeHit | None:
    meta = raw.get("metadata") or {}
    try:
        return ExchangeHit(
            chunk_id=str(raw.get("id")),
            content=raw.get("content") or "",
            handle=str(meta.get("handle") or ""),
            conversation_id=int(meta.get("conversation_id") or 0),
            first_message_id=int(meta.get("first_message_id") or 0),
            last_message_id=int(meta.get("last_message_id") or 0),
            ts=float(meta.get("ts") or 0.0),
            distance=raw.get("distance"),
        )
    except (TypeError, ValueError):
        return None


async def resolve_person_handles(person: str) -> list[str]:
    """Nom d'entité ou handle brut → tous les handles de l'identité.

    1. Nom d'entité (« Thomas ») → `handles_for_entity_names`.
    2. Handle transport (`web_…`, `tg_…`) → `handles_for_person` élargit à
       toute l'identité (une question posée sur Telegram retrouve les
       échanges web de la même personne).
    3. Sinon : le littéral — un visiteur non lié matche quand même ses
       propres chunks.
    """
    from identity.resolver import identity_resolver

    person = (person or "").strip()
    if not person:
        return []
    try:
        by_name = await identity_resolver.handles_for_entity_names([person])
        handles = [
            h["person_id"]
            for handle_list in by_name.values()
            for h in handle_list
            if h.get("person_id")
        ]
        if handles:
            return sorted(set(handles))
        own = await identity_resolver.handles_for_person(person)
        handles = [h["person_id"] for h in own if h.get("person_id")]
        if handles:
            return sorted(set(handles))
    except Exception as exc:
        degradations.record("episodic: resolution personne", exc)
    return [person]


async def search_exchanges(
    query: str,
    *,
    person: str | None = None,
    handles: list[str] | None = None,
    n: int = 6,
    since: datetime | None = None,
    until: datetime | None = None,
    proper_nouns: list[str] | None = None,
) -> list[ExchangeHit]:
    """Recherche sémantique dans les échanges bruts (étage 1).

    ``person`` (nom OU handle) est résolu en handles via la couche identité ;
    ``handles`` court-circuite la résolution quand l'appelant les a déjà.
    ``proper_nouns`` ajoute des passes `contains` (hybride minimal — MiniLM
    sert mal les noms propres), fusionnées par chunk avec bonus.
    """
    store = _store()
    if store is None or not (query or "").strip():
        return []
    if handles is None and person:
        handles = await resolve_person_handles(person)

    kwargs = {
        "n": n,
        "handles": handles or None,
        "since_ts": since.timestamp() if since else None,
        "until_ts": until.timestamp() if until else None,
    }
    try:
        raw = await vector_call(store.search_exchanges)(query, **kwargs)
    except Exception as exc:
        degradations.record("episodic: recherche echanges", exc)
        return []

    merged: dict[str, ExchangeHit] = {}
    for r in raw:
        hit = _hit_from_raw(r)
        if hit:
            merged[hit.chunk_id] = hit

    for noun in (proper_nouns or [])[:2]:
        try:
            extra = await vector_call(store.search_exchanges)(
                query, contains=noun, **kwargs,
            )
        except Exception as exc:
            degradations.record("episodic: recherche contains", exc)
            continue
        for r in extra:
            hit = _hit_from_raw(r)
            if hit is None:
                continue
            import dataclasses as _dc
            bonus = (
                max(0.0, hit.distance - _CONTAINS_BONUS)
                if hit.distance is not None else None
            )
            boosted = _dc.replace(hit, distance=bonus)
            prev = merged.get(hit.chunk_id)
            if prev is None or (
                boosted.distance is not None
                and (prev.distance is None or boosted.distance < prev.distance)
            ):
                merged[hit.chunk_id] = boosted

    hits = sorted(
        merged.values(),
        key=lambda h: h.distance if h.distance is not None else 1.0,
    )
    return hits[:n]


async def fetch_verbatim(message_id: int, radius: int = 3) -> dict:
    """Les messages exacts autour de ``message_id`` — le second temps.

    Renvoie ``{"conversation_id": int | None, "messages": [{id, role,
    content, person_id, created_at}, …]}`` ordonné. Ne lève jamais.
    """

    def _fetch() -> dict:
        from memory.models import Message

        anchor = Message.objects.filter(pk=message_id).first()
        if anchor is None:
            return {"conversation_id": None, "messages": []}
        base = user_facing_messages(
            Message.objects.filter(conversation_id=anchor.conversation_id)
        )
        before = list(
            base.filter(pk__lt=anchor.pk).order_by("-pk")[:radius]
        )[::-1]
        after = list(base.filter(pk__gt=anchor.pk).order_by("pk")[:radius])
        middle = [] if anchor.is_internal else [anchor]
        return {
            "conversation_id": anchor.conversation_id,
            "messages": [
                {
                    "id": m.pk,
                    "role": m.role,
                    "content": m.content,
                    "person_id": m.person_id,
                    "created_at": m.created_at,
                }
                for m in before + middle + after
            ],
        }

    try:
        return await sync_to_async(_fetch)()
    except Exception as exc:
        degradations.record("episodic: fetch verbatim", exc)
        return {"conversation_id": None, "messages": []}


async def expand_hit(hit: ExchangeHit, radius: int = 2) -> dict:
    """Le chunk déplié : ses messages ``first..last`` + ``radius`` voisins."""

    def _fetch() -> dict:
        from memory.models import Message

        base = user_facing_messages(
            Message.objects.filter(conversation_id=hit.conversation_id)
        )
        core = list(
            base.filter(
                pk__gte=hit.first_message_id, pk__lte=hit.last_message_id,
            ).order_by("pk")
        )
        before = list(
            base.filter(pk__lt=hit.first_message_id).order_by("-pk")[:radius]
        )[::-1]
        after = list(
            base.filter(pk__gt=hit.last_message_id).order_by("pk")[:radius]
        )
        return {
            "conversation_id": hit.conversation_id,
            "messages": [
                {
                    "id": m.pk,
                    "role": m.role,
                    "content": m.content,
                    "person_id": m.person_id,
                    "created_at": m.created_at,
                }
                for m in before + core + after
            ],
        }

    try:
        return await sync_to_async(_fetch)()
    except Exception as exc:
        degradations.record("episodic: expand hit", exc)
        return {"conversation_id": None, "messages": []}
