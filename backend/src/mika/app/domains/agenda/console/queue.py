"""Sa part de la file « À valider » (ADR 0177, 0309, 0310) : la source d'une écriture d'agenda qui attend un accord."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from mika.app.domains.domain import QueuePart
from mika.app.handmade.approval_sources import arg
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI
from mika.plugins.agenda import CAPABILITY as AGENDA_WRITE


def sources(ui: UI, args: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Une écriture d'agenda : la fiche de l'agenda ; sa semaine dans Tous les agendas, l'événement ouvert quand il est
    déjà dans la base (une réponse d'invitation, une modification)."""
    calendar = arg(args, "calendar")
    store = ui.kernel.ports.get("agenda")
    cal = store.calendar(calendar) if store is not None and calendar else None
    if cal is None:
        return []
    out = [(f"L'agenda « {cal.name or calendar} »", subject_url("agenda", calendar))]
    uid = arg(args, "uid")
    found = store.find(calendar, uid, arg(args, "original")) if uid else None
    draft = args.get("draft") if isinstance(args.get("draft"), Mapping) else {}
    span = draft.get("span") if isinstance(draft.get("span"), Mapping) else {}
    start = found.span.start if found is not None else int(span.get("start") or 0)
    if start:
        query = {"du": ui.kernel.mind.frame().local(start).date().isoformat()}
        if found is not None:
            query["ev"] = f"{found.id}.{arg(args, 'occurrence')}" if arg(args, "occurrence") else str(found.id)
        out.append(("Dans la semaine", f"{PREFIX}/agendas/tous?" + urlencode(query)))
    return out


QUEUE = QueuePart(sources={AGENDA_WRITE: sources})
