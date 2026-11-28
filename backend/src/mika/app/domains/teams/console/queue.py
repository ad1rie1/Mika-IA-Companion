"""Sa part de la file « À valider » (ADR 0177, 0310) : les réponses Teams, la source d'une demande d'envoi (la réponse
préparée, sa conversation), et le mot du canal quand une demande le pose en contexte."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.app.domains.domain import QueuePart
from mika.app.domains.teams.console.subject import CONVERSATION, REPLY
from mika.app.handmade.approval_sources import arg
from mika.contracts import teams as teams_c
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, QueueTab
from mika.ports.teams import DEFAULT_ACCOUNT as DEFAULT_TEAMS_ACCOUNT
from mika.ports.teams import conversation_key


def sources(ui: UI, args: Mapping[str, Any]) -> list[tuple[str, str]]:
    """La source d'une réponse Teams : la réponse préparée, puis sa conversation."""
    out: list[tuple[str, str]] = []
    if draft := arg(args, "draft"):
        out.append(("La réponse préparée", subject_url(REPLY, draft)))
    if conversation := arg(args, "conversation"):
        key = conversation_key(arg(args, "account") or DEFAULT_TEAMS_ACCOUNT, conversation)
        out.append(("La conversation Teams", subject_url(CONVERSATION, key)))
    return out


QUEUE = QueuePart(
    tabs=(QueueTab("teams", "Réponses Teams", capabilities=(teams_c.SEND,), order=20,
         description="Ses réponses dans Teams, à ta place : ce qui sera posé, après ton accord.",
         empty="Aucune réponse Teams n'attend ton accord.",
         hint="Ce qu'elle poserait dans Teams"),),
    covers=("teams/reponses",),
    sources={teams_c.SEND: sources},
    channels={teams_c.OWNER: "Teams"},
)
