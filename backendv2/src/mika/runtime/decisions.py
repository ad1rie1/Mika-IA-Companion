"""Décider d'un effet en attente : l'approuver ou le refuser — un seul chemin,
que la page Approbations, l'API du frontend et les fiches d'une faculté
(``Done.decide``) empruntent tous.

**Ce qui est approuvé est ce qui a été lu.** Une capacité peut montrer
exactement ce qui partirait (``CapabilitySpec.preview``) ; décider, c'est
approuver cet aperçu-là : son condensé est épinglé dans ``effect.resolved``
(``_apercu``). Si ce qui partirait a changé depuis qu'on l'a lu (un brouillon
retouché entre-temps), la décision est refusée (« relis-le ») ; sans condensé
lu (l'API), c'est celui de la proposition qui vaut. Rien ici ne nomme une
faculté.
"""

from __future__ import annotations

import inspect as pyinspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mika.contracts import runtime as rt
from mika.kernel.events import Draft, Origin
from mika.kernel.guards import Guard, Superseded
from mika.kernel.operate import Preview
from mika.runtime.boundary import Failed, acall, call

if TYPE_CHECKING:
    from mika.runtime.mind import Mind

APPROVED, REJECTED, UNKNOWN, CHANGED, BLOCKED = "approved", "rejected", "unknown", "changed", "blocked"
#: la clé des arguments d'une proposition qui porte le condensé de ce qui a été montré
SEEN_KEY = "_apercu"
MESSAGES = {
    UNKNOWN: "Action inconnue ou déjà décidée.",
    CHANGED: "Ce qui partirait a changé depuis que tu l'as lu : relis-le avant de décider.",
}


@dataclass(frozen=True, slots=True)
class Resolution:
    status: str
    draft: Draft[Any] | None = None
    message: str = ""


def _args(args_json: str) -> dict[str, Any]:
    try:
        data = json.loads(args_json or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def preview(mind: Mind, ports: Mapping[str, Any], capability: str, args_json: str) -> Preview | None:
    """Ce qu'un effet ferait s'il partait maintenant (``None`` : la capacité ne le dit pas)."""
    spec = mind.registry.capabilities.get(capability)
    if spec is None or spec.preview is None:
        return None
    got: Any = call(spec.preview, _args(args_json), ports, label=f"aperçu {capability}")
    if not isinstance(got, Failed) and pyinspect.isawaitable(got):
        pending = got
        got = await acall(lambda: pending, label=f"aperçu {capability}")
    return got if isinstance(got, Preview) else None


async def prepare(mind: Mind, ports: Mapping[str, Any], proposal: int, approved: bool, *, by: str,
                  note: str = "", seen: str = "", owner: str | None = None) -> Resolution:
    """L'événement de décision à journaliser, ou pourquoi il n'y en a pas."""
    pending = mind.frame().state("runtime").effects.get(proposal)
    if pending is None or (owner is not None and pending.owner != owner):
        return Resolution(UNKNOWN, message=MESSAGES[UNKNOWN])
    args_json = pending.args_json
    if approved:
        shown = await preview(mind, ports, pending.capability, args_json)
        if shown is not None:
            if shown.blocked:
                return Resolution(BLOCKED, message=f"Ça ne peut pas partir tel quel : {shown.blocked}.")
            args = _args(args_json)
            wanted = seen or str(args.get(SEEN_KEY) or "")
            if wanted and wanted != shown.digest:
                return Resolution(CHANGED, message=MESSAGES[CHANGED])
            args[SEEN_KEY] = shown.digest
            args_json = json.dumps(args, ensure_ascii=False, sort_keys=True)
    draft = rt.EFFECT_RESOLVED.draft(
        proposal=proposal, approved=approved, note=note[:500], by=by, capability=pending.capability,
        owner=pending.owner, args_json=args_json, context=pending.context, dedupe_key=f"décision:{proposal}")
    return Resolution(APPROVED if approved else REJECTED, draft)


def still_pending(proposal: int) -> Guard:
    def check(view: Any) -> bool:
        return any(e.proposal == proposal for e in view.get(rt.PENDING_EFFECTS))

    return Guard("en attente", predicate=check)


async def decide(mind: Mind, ports: Mapping[str, Any], proposal: int, approved: bool, *, by: str, note: str = "",
                 seen: str = "", owner: str | None = None) -> Resolution:
    """Décide et journalise ; une seule décision par proposition (la seconde est « inconnue »)."""
    got = await prepare(mind, ports, proposal, approved, by=by, note=note, seen=seen, owner=owner)
    if got.draft is None:
        return got
    try:
        commit = await mind.append([got.draft], emitter=rt.OWNER, correlation=f"décision:{proposal}",
                                   origin=Origin.EXTERNAL, guard=still_pending(proposal))
    except Superseded:
        return Resolution(UNKNOWN, message=MESSAGES[UNKNOWN])  # une autre décision est passée avant
    if commit.deduped:
        return Resolution(UNKNOWN, message=MESSAGES[UNKNOWN])  # la même décision, déjà prise
    return got
