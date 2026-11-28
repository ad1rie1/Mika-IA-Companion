"""Ce qu'elle sait, en parlant, des appels qui attendaient un accord, et ce qui la pousse à en dire le résultat
(ADR 0064) — sur le modèle des dessins (ADR 0063).

- La section « CE QUE TES SERVICES T'ONT RENDU » (réponse et initiative, pour la personne en face) : ce qui attend
  encore un accord, et ce qui est revenu — rendu, raté, refusé, expiré. Ce sont ses demandes : la section est à elle ;
  seul ce que le service a répondu (rendu, ou sa raison d'un échec) est cité, une donnée. Ce que son prompt lui a
  montré quand elle a parlé est réputé dit (``mcp:<proposition>`` dans sa provenance). Ses phrases servent aussi aux
  appels de ses apps (``plugins/forge/calls.py``) : une seule maison.
- L'initiative due (``service_answered``) : ce qui est revenu se dit, vers là où la personne est maintenant — comme
  un rappel, ce n'est pas prendre la parole (``agency.OWED``) ; une garde l'annule si c'est déjà dit.
- La section « CE QUE TES SERVICES ONT RENDU À CE TRAVAIL » (ADR 0255), au travail, où personne n'est en face : les
  demandes faites en travaillant sur la même cible (un projet, un but, une tâche) — ce qui attend encore un accord ou
  vient de partir, et les issues que le départ de cet épisode lui a remises (``Request.shown_in``). Même forme : ses
  demandes sont à elle, seul ce que le service a répondu est cité. S'il aboutit, elles sont lues et ne reviennent
  plus ; sinon le travail suivant les relit.
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
    ANSWER_KEPT,
    ANSWERED,
    APPROVED,
    EPISODES,
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
    origin_of,
)
from mika.ports.preprocess import cite, inert
from mika.vocab.access import KEEP_FLOORS
from mika.vocab.days import ago_words
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: au plus tant de demandes dans la section
SHOWN_MAX = 4
#: ce qu'une réponse montre d'elle dans la section : tout ce qu'on en garde (ADR 0163)
SHOWN_CHARS = ANSWER_KEPT
#: ce que la raison d'un échec montre d'elle
WHY_CHARS = 300
#: la force de l'initiative due (au-dessus du seuil d'initiative, sous la barre de réveil : comme un dessin prêt)
EVIDENCE = 12.0
#: les épisodes où elle travaille seule (un pas, une exécution, un réveil, une tâche) : là où un service sert « au
#: travail », et où revient l'issue d'une demande qui en est partie (ADR 0255)
AT_WORK = EPISODES["travail"]
#: au travail, au plus tant de demandes encore en attente sont détaillées ; au-delà, leur nombre est dit
OPEN_SHOWN = 6
#: ce que ses services ont rendu à ce travail est ce sur quoi elle travaille : coupé le premier parmi ses sections,
#: jamais au point de disparaître
WORK_FLOOR = 1200


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


def line(r: Request, texts: Mapping[str, str], what: str = "") -> str:
    """Où en est une demande : ses mots à elle ; ce que le service a répondu, cité en dessous — une donnée, jamais une
    consigne. ``what`` : comment la nommer (par défaut, l'outil et son service)."""
    what = what or phrase("mcp.section.what", tool=inert(r.remote, 80), server=inert(r.server, 40))
    if r.status == WAITING:
        who = (phrase("approvals.section.by_chat") if r.approval == "conversation"
               else phrase("approvals.section.by_operator"))
        return "- " + phrase("approvals.section.waiting", what=what, who=who)
    if r.status == APPROVED:
        return "- " + phrase("approvals.section.sent", what=what)
    said = texts.get(r.text_ref, "")
    if r.status == ANSWERED:
        return "- " + phrase("approvals.section.answered", what=what) + "\n" + (cite(said, SHOWN_CHARS)
                                                                          or phrase("approvals.nothing"))
    if r.status == FAILED:
        if not said.strip():
            return "- " + phrase("approvals.section.failed", what=what)
        return "- " + phrase("approvals.section.failed_said", what=what) + "\n" + cite(said, WHY_CHARS)
    if r.status == EXPIRED:
        return "- " + phrase("approvals.section.expired", what=what)
    return "- " + phrase("approvals.section.refused", what=what)


@MCP.section("services", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
             title=phrase("mcp.section.title"), reads=[identity_c.PERSON, identity_c.HANDLES])
def _section(s: McpState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    reqs = _relevant(s, frame)
    if not reqs:
        return None
    texts = enrich.get("services") or {}
    lines = [line(r, texts) for r in reqs]
    told = tuple(f"{PROVENANCE}{r.proposal}" for r in reqs if r.status in FINAL)
    # ce qu'un service a rendu vaut ce que son serveur en garde (ADR 0128) : le message qui le dit l'emporte
    shown = [r for r in reqs if r.status == ANSWERED]
    return SectionBody(phrase("mcp.section.head") + "\n" + "\n".join(lines),
                       level=int(Sensitivity.PERSONAL), witness=True, provenance=told,
                       floor=max((KEEP_FLOORS.get(r.keep, 0) for r in shown), default=0),
                       unkept=any(r.keep == "rien" for r in shown))


# ── Au travail : ce qui revient là d'où la demande est partie (ADR 0255) ────


def _open(s: McpState, origin: str, now: int) -> list[Request]:
    """Les demandes parties de cette cible qui n'ont pas encore d'issue : celles qui attendent un accord, et celles
    qu'on vient d'accepter, dont la réponse n'est pas revenue (tant que leur délai court : un appel resté sans suite
    ne se dit pas « parti » pour toujours)."""
    return sorted((r for r in s.requests.values() if r.origin == origin
                   and (r.status == WAITING or (r.status == APPROVED and now <= r.expires))), key=lambda r: r.proposal)


def _back(s: McpState, frame: Frame) -> list[Request]:
    """Les issues que le départ de cet épisode lui a remises (``plugins.mcp._work_started``) : exactement celles que
    sa fin marquera lues."""
    ep = frame.episode
    origin = origin_of(ep)
    if ep is None or not origin:
        return []
    return sorted((r for r in s.requests.values() if r.origin == origin and r.shown_in == ep.id
                   and r.status in FINAL and not r.seen), key=lambda r: r.proposal)


@MCP.enricher("work_services", episodes=AT_WORK, deadline_ms=300)
async def _work_texts(s: McpState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    refs = [r.text_ref for r in _back(s, frame) if r.text_ref]
    if store is None or not refs:
        return None
    return store.content(refs)


def _asked(r: Request, now: int) -> str:
    """Une demande faite au travail, et depuis quand : entre deux exécutions, il peut s'être passé des jours."""
    return phrase("mcp.work.what", tool=inert(r.remote, 80), server=inert(r.server, 40), ago=ago_words(now - r.at))


@MCP.section("work_services", zone=Zone.VOLATILE, episodes=AT_WORK, trim_rank=0, floor_chars=WORK_FLOOR,
             title=phrase("mcp.work.title"))
def _work_section(s: McpState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que sont devenues les demandes qu'elle a faites à ses services en travaillant ici : d'abord ce qui n'a pas
    encore d'issue (elle ne le redemande pas), puis les issues remises à cet épisode. Ses demandes sont à elle ; ce
    que le service a répondu est cité dessous, une fois (ADR 0154, 0163) — la section n'est pas citée en bloc."""
    origin = origin_of(frame.episode)
    if not origin:
        return None
    still, back = _open(s, origin, frame.now), _back(s, frame)
    if not still and not back:
        return None
    texts = enrich.get("work_services") or {}
    lines = [line(r, texts, _asked(r, frame.now)) for r in still[-OPEN_SHOWN:]]
    if len(still) > OPEN_SHOWN:
        lines.append("- " + phrase("mcp.work.more", n=len(still) - OPEN_SHOWN))
    lines += [line(r, texts, _asked(r, frame.now)) for r in back]
    # ce qu'un service a rendu vaut ce que son serveur en garde (ADR 0128), comme en conversation
    shown = [r for r in back if r.status == ANSWERED]
    return SectionBody(phrase("mcp.work.head") + "\n" + "\n".join(lines), level=int(Sensitivity.PERSONAL),
                       provenance=tuple(f"{PROVENANCE}{r.proposal}" for r in back),
                       floor=max((KEEP_FLOORS.get(r.keep, 0) for r in shown), default=0),
                       unkept=any(r.keep == "rien" for r in shown))


def _untold(proposal: int) -> Guard:
    """L'épisode ne vaut que tant que ce n'est pas dit (sa réponse l'a emporté : plus rien à faire)."""
    return Guard("réponse d'un service", predicate=lambda view, n=proposal: view.get(c.UNTOLD(n)) is True)


def _address(frame: Frame, r: Request) -> str:
    """Où le dire : là où la personne est maintenant (connectée, sinon joignable), sinon d'où venait la demande."""
    person = frame.get(identity_c.PERSON(r.target)) or r.target
    return identity_c.reach_now(frame, person, handles=frame.get(identity_c.HANDLES(person)) or (r.target,)) or r.target


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
