"""Sa part de la file « À valider » (ADR 0177, 0310) : les courriers à envoyer, la source d'une demande d'envoi (son
brouillon, sa boîte), et le mot du canal quand une demande le pose en contexte."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from mika.app.domains.domain import QueuePart
from mika.app.domains.mail.console.subject import DRAFT
from mika.app.handmade.approval_sources import arg
from mika.contracts import email as email_c
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, QueueTab


def sources(ui: UI, args: Mapping[str, Any]) -> list[tuple[str, str]]:
    """La source d'un mail à envoyer : son brouillon, puis sa boîte."""
    out: list[tuple[str, str]] = []
    if draft := arg(args, "draft"):
        out.append(("Le brouillon", subject_url(DRAFT, draft)))
    if account := arg(args, "account"):
        out.append((f"La boîte « {account} »", f"{PREFIX}/courrier/reception?" + urlencode({"compte": account})))
    return out


QUEUE = QueuePart(
    tabs=(QueueTab("courriers", "Courriers à envoyer", capabilities=(email_c.SEND,), order=10,
         description="Les mails qu'elle voudrait envoyer : ce qui partira, tel quel, après ton accord.",
         empty="Aucun mail n'attend ton accord.",
         hint="Ses mails, prêts à partir"),),
    covers=("courrier/brouillons",),
    sources={email_c.SEND: sources},
    channels={email_c.OWNER: "courrier"},
)
