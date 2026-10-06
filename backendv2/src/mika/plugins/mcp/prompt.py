"""Ce qu'elle sait, en parlant, des appels qui attendaient un accord, et ce qui la pousse à en dire le résultat
(ADR 0064) — sur le modèle des dessins (ADR 0063).

- La section « CE QUE TES SERVICES T'ONT RENDU » (réponse et initiative, pour la personne en face) : ce qui attend
  encore un accord, et ce qui est revenu — rendu (cité : une donnée), raté, refusé, expiré. Ce que son prompt lui a
  montré quand elle a parlé est réputé dit (``mcp:<proposition>`` dans sa provenance).
- L'initiative due (``service_answered``) : ce qui est revenu se dit, vers là où la personne est maintenant — comme
  un rappel, ce n'est pas prendre la parole (``agency.OWED``) ; une garde l'annule si c'est déjà dit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import mcp as c
from mika.contracts import presence as presence_c
from mika.kernel.arbitration import Candidate
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.mcp import (
    ANSWERED,
    EXPIRED,
    FAILED,
    FINAL,
    MCP,
    PROVENANCE,
    REFUSED,
    TOO_LATE,
    WAITING,
    McpState,
    Request,
    label,
)
from mika.ports.preprocess import cite, inert
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: au plus tant de demandes dans la section
SHOWN_MAX = 4
#: ce qu'une réponse montre d'elle dans la section
SHOWN_CHARS = 2000
#: la force de l'initiative due (au-dessus du seuil d'initiative, sous la barre de réveil : comme un dessin prêt)
EVIDENCE = 12.0


def _handles(frame: Frame) -> tuple[str, ...]:
    ep = frame.episode
    if ep is None or not ep.target:
        return ()
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    return tuple(frame.get(identity_c.HANDLES(person)) or (ep.target,))


def _relevant(s: McpState, frame: Frame) -> list[Request]:
    handles = set(_handles(frame))
    if not handles:
        return []
    out = [r for r in s.requests.values() if r.target in handles
           and (r.status == WAITING or (r.status in FINAL and not r.told and frame.now - r.done_at <= TOO_LATE))]
    return sorted(out, key=lambda r: r.proposal)[-SHOWN_MAX:]


@MCP.enricher("services", episodes=CONVERSATIONAL, deadline_ms=300)
async def _texts(s: McpState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    refs = [r.text_ref for r in _relevant(s, frame) if r.text_ref]
    if store is None or not refs:
        return None
    return store.content(refs)


def line(r: Request, texts: Mapping[str, str]) -> str:
    what = phrase("mcp.section.what", tool=inert(r.remote, 80), server=inert(r.server, 40))
    if r.status == WAITING:
        who = phrase("mcp.section.by_chat") if r.approval == "conversation" else phrase("mcp.section.by_operator")
        return "- " + phrase("mcp.section.waiting", what=what, who=who)
    if r.status == ANSWERED:
        said = texts.get(r.text_ref, "")
        return ("- " + phrase("mcp.section.answered", what=what) + "\n"
                + (cite(said, SHOWN_CHARS) or phrase("mcp.tools.nothing")) + "\n" + phrase("mcp.section.say_it"))
    if r.status == FAILED:
        said = inert(texts.get(r.text_ref, ""), 300)
        return "- " + phrase("mcp.section.failed", what=what, why=phrase("mcp.section.why", said=said) if said else "")
    if r.status == EXPIRED:
        return "- " + phrase("mcp.section.expired", what=what)
    return "- " + phrase("mcp.section.refused", what=what)


@MCP.section("services", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
             title=phrase("mcp.section.title"), untrusted=True, reads=[identity_c.PERSON, identity_c.HANDLES])
def _section(s: McpState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    reqs = _relevant(s, frame)
    if not reqs:
        return None
    texts = enrich.get("services") or {}
    lines = [line(r, texts) for r in reqs]
    told = tuple(f"{PROVENANCE}{r.proposal}" for r in reqs if r.status in FINAL)
    return SectionBody(phrase("mcp.section.head") + "\n" + "\n".join(lines),
                       level=int(Sensitivity.PERSONAL), witness=True, provenance=told)


def _untold(proposal: int) -> Guard:
    """L'épisode ne vaut que tant que ce n'est pas dit (sa réponse l'a emporté : plus rien à faire)."""
    return Guard("réponse d'un service", predicate=lambda view, n=proposal: view.get(c.UNTOLD(n)) is True)


def _address(frame: Frame, r: Request) -> str:
    """Où le dire : là où la personne est maintenant (connectée, sinon joignable), sinon d'où venait la demande."""
    person = frame.get(identity_c.PERSON(r.target)) or r.target
    handles = frame.get(identity_c.HANDLES(person)) or (r.target,)
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else r.target


@MCP.propose(kinds=[Kind.INITIATIVE], reasons={c.ANSWERED_REASON: (0.0, 17.0)},
             reads=[c.UNTOLD, identity_c.PERSON, identity_c.HANDLES, identity_c.REACHABLE, presence_c.PRESENT])
def _owed(s: McpState, frame: Frame) -> list[Candidate]:
    out = []
    for r in sorted(s.requests.values(), key=lambda r: (r.done_at, r.proposal)):
        if r.status not in FINAL or r.told or not r.target or frame.now - r.done_at > TOO_LATE:
            continue
        address = _address(frame, r)
        if r.status == ANSWERED:
            brief = phrase("mcp.brief.answered", server=label(r.server))
        elif r.status == FAILED:
            brief = phrase("mcp.brief.failed", server=label(r.server))
        elif r.status == EXPIRED:
            brief = phrase("mcp.brief.expired", server=label(r.server))
        else:
            assert r.status == REFUSED
            brief = phrase("mcp.brief.refused", server=label(r.server))
        out.append(Candidate(
            Kind.INITIATIVE, address, c.ANSWERED_REASON, EVIDENCE, resources=frozenset({floor(address)}),
            guards=(_untold(r.proposal),),
            args=FrozenDict({"brief:mcp": brief, "subject": f"mcp:{r.proposal}"})))
    return out
