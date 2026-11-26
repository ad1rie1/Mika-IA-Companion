"""Piloter un projet de vive voix.

En conversation, ``project_steer`` : un objectif de plus, une consigne, s'y mettre maintenant, la pause, la reprise —
jamais son cadre —, et la réponse à son plan (le lancer, ou le lui faire reprendre — ADR 0145 ; lancé par le
propriétaire du projet, ce que le plan demandait à lire se pose avec lui — ADR 0257). Il n'est offert qu'à
qui une ligne d'accès laisse changer un projet vivant (``access.steering``, ``fits``) : en modification, le geste
s'écrit aussitôt, au nom de la personne ; sur l'accord du propriétaire, la demande est gardée
(``projects.steer_asked``, son texte effaçable) et proposée dans la console (la capacité ``projects.steer``, son
aperçu), et l'effet qui suit l'accord écrit le geste (ADR 0133).

Il lit les aides des outils (``tools.py`` : qui parle, ses mots tels quels, les textes gardés, qui s'occupe d'elle) ;
``tools.py`` ne l'importe pas.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import links
from mika.faculties.projects.access import steering
from mika.faculties.projects.faculty import (
    AMENDED,
    APPROVE,
    LINKS_SET,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVES_KEPT,
    PAUSED,
    PLAN_ANSWERED,
    PROJECTS,
    RESUMED,
    REVISE,
    STEER_ASKED,
    STEER_CAPABILITY,
    Objective,
    Project,
    ProjectsState,
    SteerAsk,
    busy,
    live,
    living,
    nudged,
    objective_at,
    outgoing,
    params,
    subjects_of,
    written,
)
from mika.faculties.projects.inspect_common import unchanged
from mika.faculties.projects.rhythm import pick
from mika.faculties.projects.tools import (
    attributed,
    caretaker,
    contents_of,
    named_projects,
    refused_lines,
    speaker,
    still_open,
    their_words,
)
from mika.kernel.clock import HOUR
from mika.kernel.codec import canonical_json
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.kernel.operate import Preview
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import hearable
from mika.vocab.words import stems

# ── En conversation : piloter un projet ───────────────────────────────────


STEER = "project_steer"
ADD, INSTRUCT, NOW, PAUSE, RESUME = "add", "instruct", "now", "pause", "resume"
#: répondre à son plan (ADR 0145) : le lancer, ou le lui faire reprendre
PLAN_VERDICTS = (APPROVE, REVISE)
#: un projet qu'on pilote encore (archivé, il ne fait plus rien)
STEERABLE = (c.ACTIVE, c.PAUSED)
#: les projets, les objectifs qu'elle énumère quand elle ne sait pas duquel il s'agit
LISTED = 12
#: la raison d'une pause demandée en conversation (qui l'a demandée : ``by``, que la console nomme)
PAUSED_IN_TALK = "mis en pause en conversation"


class SteerArgs(BaseModel):
    project: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.steer.project"))
    what: Literal["add", "instruct", "now", "pause", "resume", "approve", "revise"] = Field(
        description=phrase("projects.tools.steer.what"))
    text: str = Field(default="", max_length=2000, description=phrase("projects.tools.steer.text"))
    kind: Literal["once", "constant"] = Field(default="once", description=phrase("projects.tools.steer.kind"))
    cadence_hours: int = Field(default=0, ge=0, le=24 * 30, description=phrase("projects.tools.steer.cadence_hours"))
    objective: str = Field(default="", max_length=200, description=phrase("projects.tools.steer.objective"))


def steerable(p: Project, audience: Any, frame: Any = None) -> str:
    """Ce que qui est en face peut faire de ce projet en le pilotant, en réponse (ADR 0133, ``STEERS``) — un projet
    vivant, que ses lignes d'accès lui laissent voir et piloter (``close`` : qui est proche d'elle)."""
    return steering(p, audience, Kind.REPLY, frame) if live(p) else c.STEER_NO


def may_steer(audience: Any, kind: str, frame: Any = None) -> bool:
    """Seulement devant qui une ligne d'accès laisse changer un de ses projets vivants (ADR 0133) : sur l'accord du
    propriétaire ou en modification — la lecture seule n'y change rien.

    Jamais dans un salon ni avec une inconnue ; sans ce qu'elle vit (une console qui juge hors de sa vie), non."""
    if frame is None:
        return False
    s: ProjectsState = frame.state("projects")
    return any(steering(p, audience, kind, frame) in c.CHANGES for p in s.projects.values() if live(p))


def _which(said: str, rows: list[tuple[int, str]]) -> int | None:
    """Le numéro dont il s'agit : dit tel quel (« 3 », « n° 3 »), sinon le seul qu'il y a, sinon celui qui a le
    plus de mots en commun avec ce qu'elle en dit — s'il est seul dans ce cas (sinon rien : elle demande lequel)."""
    raw = said.strip().lower().removeprefix("n°").removeprefix("#").strip()
    if raw.isdigit():
        return int(raw) if any(i == int(raw) for i, _ in rows) else None
    if len(rows) == 1:
        return rows[0][0]
    said_stems = stems(said)
    scored = [(len(said_stems & stems(text)), i) for i, text in rows]
    best = max((n for n, _ in scored), default=0)
    top = [i for n, i in scored if n == best]
    return top[0] if best and len(top) == 1 else None


def _listed(rows: list[tuple[int, str]], empty: str) -> str:
    """Les projets (ou les objectifs) parmi lesquels elle n'a pas su choisir, un par ligne."""
    return "\n".join(phrase("projects.tools.steer.item", id=i, text=text or empty) for i, text in rows[:LISTED])


async def _steered(ctx: Any, draft: Draft[Any], guard: Guard, *more: Draft[Any]) -> Any:
    """Écrire un geste sous sa garde (et ce qui s'écrit avec lui, ``more``) ; ``None`` quand c'est elle qui a cédé (le
    projet a changé entre-temps)."""
    try:
        return await ctx.emit(draft, *more, guard=guard)
    except Superseded:
        if guard.predicate is not None and guard.predicate(ctx.mind.frame().view):
            raise  # c'est la garde de la conversation qui a cédé
        return None


def _changed() -> ToolResult:
    """La réponse d'un geste quand le projet a changé sous elle (une garde a cédé) : rien n'a changé."""
    return ToolResult(ok=False, content=phrase("projects.tools.steer.changed"))


@PROJECTS.tool(STEER, acts=True, description=phrase("projects.tools.steer.description"),
               label=phrase("projects.tools.steer.label"), args=SteerArgs, bundle="projects",
               episodes=[Kind.REPLY], max_calls_per_episode=2, fits=may_steer,
               rule="seulement en privé, sur un projet vivant que les lignes d'accès laissent piloter à la personne en "
                    "face ; sur ton accord, la demande attend")
async def project_steer(args: SteerArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    who = speaker(frame)
    aud = frame.audience
    if who is None or aud is None:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.not_owner", who=caretaker(frame)))
    person = who[1]
    s: ProjectsState = frame.state("projects")
    # ceux que ses lignes d'accès lui laissent piloter et dont le détail peut s'entendre ici (la règle de « TES
    # PROJETS ») : on ne pilote pas à l'aveugle
    mine = [p for p in sorted(s.projects.values(), key=lambda x: x.id) if steerable(p, aud, frame) in c.CHANGES
            and hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok)]
    if not mine:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.none"))
    texts = contents_of(ctx, [p.title_ref for p in mine])
    rows = [(p.id, texts.get(p.title_ref, "")) for p in mine]
    pid = _which(args.project, rows)
    if pid is None:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.which_project", listed=_listed(
            rows, phrase("projects.tools.steer.untitled"))))
    p = s.projects[pid]
    title = phrase("projects.tools.steer.quoted", text=texts[p.title_ref]) if texts.get(p.title_ref) else \
        phrase("projects.tools.steer.numbered", id=p.id)
    if args.what in PLAN_VERDICTS:
        return await _answer_plan(args, ctx, p, person, title)
    if steerable(p, aud, frame) == c.STEER_ASK:
        return await _ask_steer(args, ctx, p, person, title)
    if args.what == NOW:
        return await _steer_now(args, ctx, s, p, person, title)
    if args.what == PAUSE:
        if p.status == c.PAUSED:
            return phrase("projects.tools.steer.already_paused", title=title)
        draft = PAUSED.draft(project=p.id, reason=PAUSED_IN_TALK, by=person, owner=p.owner, about=p.about)
        if await _steered(ctx, draft, unchanged(p.id, (c.ACTIVE,))) is None:
            return _changed()
        return phrase("projects.tools.steer.paused", title=title)
    if args.what == RESUME:
        if p.status == c.ACTIVE:
            return phrase("projects.tools.steer.not_paused", title=title)
        draft = RESUMED.draft(project=p.id, by=person, owner=p.owner, about=p.about)
        if await _steered(ctx, draft, unchanged(p.id, (c.PAUSED,))) is None:
            return _changed()
        return phrase("projects.tools.steer.resumed", title=title)
    text = args.text.strip()
    if not text:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.no_objective") if args.what == ADD
                          else phrase("projects.tools.steer.no_instruction"))
    if args.what == INSTRUCT:
        said = their_words(ctx)  # ses mots à elle ou lui, tels quels, à côté de ce qu'elle en a retenu (ADR 0145)
        draft = AMENDED.draft(project=p.id, instruction=Content.of(text, level=p.sensitivity), by=person,
                              words=Content.of(said, level=p.sensitivity) if said else None,
                              owner=p.owner, about=p.about, read_about=p.read_about)
        if await _steered(ctx, draft, unchanged(p.id, STEERABLE)) is None:
            return _changed()
        return phrase("projects.tools.steer.instructed", title=title)
    if len(text) > 500:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.too_long"))
    if living(p) >= OBJECTIVES_KEPT:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.full", title=title, count=OBJECTIVES_KEPT))
    number = p.objective_seq + 1
    commit = await _steered(ctx, OBJECTIVE_ADDED.draft(
        project=p.id, objective=number, text=Content.of(text, level=written(p)), kind=args.kind,
        cadence_us=args.cadence_hours * HOUR if args.kind == c.CONSTANT else 0, author="owner", by=person,
        owner=p.owner, about=p.about, read_about=p.read_about), unchanged(p.id, STEERABLE))
    if commit is None:
        return _changed()
    number = attributed(ctx, p.id, commit, "text", "objectives", number)
    kind = phrase("projects.tools.objective_add.constant") if args.kind == c.CONSTANT else \
        phrase("projects.tools.objective_add.once")
    return phrase("projects.tools.steer.added", id=number, title=title, kind=kind)


async def _answer_plan(args: SteerArgs, ctx: Any, p: Project, person: str, title: str) -> Any:
    """Sa réponse à un plan (ADR 0145) — seulement qui l'a demandé, ou qui s'occupe d'elle : le lancer (un plan qui
    attend), ou le lui faire reprendre (ses mots, tels quels, deviennent une consigne de la séance qui le reprend).
    Lancé par le propriétaire du projet, ce que le plan demandait à lire se pose avec lui (ADR 0257) ; par quelqu'un
    d'autre, le lien ne se pose pas, et la réponse le dit."""
    frame: Frame = ctx.frame
    if person != p.asked_by and not frame.get(identity_c.IS_OWNER(person)):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.plan_not_theirs", title=title))
    if args.what == APPROVE and p.plan_state != c.PROPOSED:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.plan_none", title=title))
    if args.what == REVISE and p.plan_state == c.TO_FRAME:  # une séance de cadrage est déjà due
        return ToolResult(ok=False, content=phrase("projects.tools.steer.plan_none", title=title))
    said = their_words(ctx) or args.text.strip()
    if args.what == REVISE and not said:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.no_instruction"))
    draft = PLAN_ANSWERED.draft(project=p.id, verdict=args.what, words=Content.of(said, level=p.sensitivity)
                                if said else None, by=person, owner=p.owner, about=p.about,
                                read_about=p.read_about)
    s: ProjectsState = frame.state("projects")
    linking = links.approved(s, p, person, links.world_of(frame)) if args.what == APPROVE else links.Approved()
    link = (LINKS_SET.draft(project=p.id, reads=linking.reads, by=person, owner=p.owner, about=p.about,
                            read_about=p.read_about),) if linking.added else ()
    if await _steered(ctx, draft, unchanged(p.id, (c.ACTIVE,)), *link) is None:
        return _changed()
    if args.what == APPROVE:
        return phrase("projects.tools.steer.plan_approve", title=title) + _linked_words(ctx, s, linking)
    return phrase("projects.tools.steer.plan_revise", title=title)


def _linked_words(ctx: Any, s: ProjectsState, linking: links.Approved) -> str:
    """Ce que sont devenus, à la validation, les projets que son plan demandait à lire (ADR 0257) : liés ; pas liés,
    parce que qui valide n'est pas le propriétaire du projet ; ou refusés, chacun avec sa raison."""
    if linking.denied:
        return phrase("projects.tools.steer.plan_not_linked")
    said = phrase("projects.tools.steer.plan_linked", projects=named_projects(ctx, s, linking.added)) \
        if linking.added else ""
    if linking.refused:
        said += phrase("projects.tools.steer.plan_link_refused", refused=refused_lines(linking.refused))
    return said


async def _steer_now(args: SteerArgs, ctx: Any, s: ProjectsState, p: Project, person: str, title: str) -> Any:
    """« Mets-toi sur ton projet maintenant » : comme « Lancer maintenant » dans la console — sous les plafonds,
    jamais pendant son sommeil en mode Mika."""
    frame: Frame = ctx.frame
    if p.status != c.ACTIVE:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.now_paused", title=title))
    o: Objective | None = None
    if args.objective.strip():
        opened = [x for x in p.objectives if x.status == c.OPEN]
        if not opened:
            return ToolResult(ok=False, content=phrase("projects.tools.steer.no_open", title=title))
        texts = contents_of(ctx, [x.text_ref for x in opened])
        rows = [(x.id, texts.get(x.text_ref, "")) for x in opened]
        oid = _which(args.objective, rows)
        if oid is None:
            return ToolResult(ok=False, content=phrase("projects.tools.steer.which_objective", listed=_listed(
                rows, phrase("projects.tools.steer.forgotten"))))
        o = objective_at(p, oid)
    if busy(s, p.id):
        return phrase("projects.tools.steer.busy", title=title)
    if nudged(p) and (o is None or p.nudged_objective == o.id):
        return phrase("projects.tools.steer.already_asked", title=title)
    if outgoing(p, frame.now):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.outgoing"))
    pm = params(frame.env.params_of("projects", frame.root))
    if o is None and pick(p, frame.now, pm) is None \
            and not any(x.status == c.OPEN and x.kind == c.CONSTANT for x in p.objectives):
        return ToolResult(ok=False, content=phrase("projects.tools.steer.nothing_open", title=title))
    guard = unchanged(p.id, (c.ACTIVE,)) if o is None else unchanged(p.id, (c.ACTIVE,)) & still_open(p.id, o.id)
    draft = NUDGED.draft(project=p.id, objective=o.id if o is not None else 0, by=person, owner=p.owner,
                         about=p.about)
    if await _steered(ctx, draft, guard) is None:
        return _changed()
    on = phrase("projects.tools.steer.on_objective", id=o.id) if o is not None else ""
    return phrase("projects.tools.steer.asked", title=title, on=on)


# ── Piloter sur ton accord (ADR 0133) ─────────────────────────────────────


def asks_words(what: str, text: str) -> str:
    """Ce qu'une demande de pilotage ferait, en mots (la carte d'accord, son aperçu)."""
    if what == ADD:
        return phrase("projects.tools.steer.asks.add", text=text[:300])
    if what == INSTRUCT:
        return phrase("projects.tools.steer.asks.instruct", text=text[:300])
    if what == NOW:
        return phrase("projects.tools.steer.asks.now")
    if what == PAUSE:
        return phrase("projects.tools.steer.asks.pause")
    return phrase("projects.tools.steer.asks.resume")


async def _ask_steer(args: SteerArgs, ctx: Any, p: Project, person: str, title: str) -> Any:
    """Sur l'accord du propriétaire : la demande est gardée (son texte, un contenu effaçable) puis proposée
    (``projects.steer``, dans la console) ; son geste s'écrit quand tu l'acceptes."""
    frame: Frame = ctx.frame
    text = args.text.strip()
    if args.what in (ADD, INSTRUCT) and not text:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.no_objective") if args.what == ADD
                          else phrase("projects.tools.steer.no_instruction"))
    if args.what == ADD and len(text) > 500:
        return ToolResult(ok=False, content=phrase("projects.tools.steer.too_long"))
    objective = 0
    if args.what == NOW and args.objective.strip():
        opened = [x for x in p.objectives if x.status == c.OPEN]
        texts = contents_of(ctx, [x.text_ref for x in opened])
        rows = [(x.id, texts.get(x.text_ref, "")) for x in opened]
        found = _which(args.objective, rows) if rows else None
        if found is None:
            return ToolResult(ok=False, content=phrase("projects.tools.steer.which_objective", listed=_listed(
                rows, phrase("projects.tools.steer.forgotten"))) if rows else
                phrase("projects.tools.steer.no_open", title=title))
        objective = found
    request = f"{ctx.episode_id}:{ctx.call_key or ctx.call_id}"
    await ctx.emit(STEER_ASKED.draft(
        project=p.id, request=request, what=args.what, text=Content.of(text, level=written(p)) if text else None,
        kind=args.kind, cadence_us=args.cadence_hours * HOUR if args.kind == c.CONSTANT else 0, objective=objective,
        by=person, owner=p.owner, about=p.about, read_about=p.read_about))
    # jamais toi en face (ta demande s'applique aussitôt, ``access.steering``) : la console décide
    payload: dict[str, Any] = {"project": p.id, "asked": request}
    what = asks_words(args.what, text)
    summary = phrase("projects.tools.steer.request", who=identity_c.person_name(frame, person) or person,
                     title=title, what=what)
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=STEER_CAPABILITY, owner=PROJECTS.name, context=project_target(p.id), approval=True,
        args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(summary[:400], level=written(p)), about=subjects_of(p, person)))
    return phrase("projects.tools.steer.waits", title=title, who=caretaker(frame))


def _steer_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview:
    """Exactement ce qui changerait : le projet, qui le demande, le geste et son texte ; bloqué si le projet n'est
    plus vivant ou si la demande s'est perdue (son texte oublié)."""
    frame_of, store = ports.get("frame"), ports.get("store")
    s: ProjectsState | None = frame_of().state("projects") if frame_of is not None else None
    asked = str(args.get("asked") or "")
    a = s.steers.get(asked) if s is not None else None
    p = s.projects.get(a.project) if s is not None and a is not None else None
    refs = [r for r in ((a.text_ref if a else ""), (p.title_ref if p else "")) if r]
    texts = store.content(refs) if store is not None and refs else {}
    text = texts.get(a.text_ref, "") if a is not None and a.text_ref else ""
    title = texts.get(p.title_ref, "") if p is not None else ""
    what = asks_words(a.what, text) if a is not None else ""
    by = a.by if a is not None else ""
    name = identity_c.person_name(frame_of(), by) if frame_of is not None and by else ""
    shown = phrase("projects.tools.steer.preview", title=title or str(args.get("project") or ""),
                   who=name or by, what=what)
    digest = hashlib.sha256(canonical_json({"asked": asked, "what": a.what if a else "", "text": text}).encode()
                            ).hexdigest()[:32]
    blocked = ""
    if a is None or p is None or (a.what in (ADD, INSTRUCT) and not text):
        blocked = phrase("projects.tools.steer.preview_lost")
    elif p.status not in STEERABLE:
        blocked = phrase("projects.tools.steer.preview_closed")
    return Preview(shown, digest, blocked)


@PROJECTS.capability(STEER_CAPABILITY,
                     description="Piloter un projet sur ton accord : son geste s'écrit une fois accepté.",
                     preview=_steer_preview)
async def _steer_capability(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    """Rien ne sort de la machine : l'accord suffit, le geste s'écrit après (``_steer_accepted``)."""
    return True, "accepté"


def accepted(p: Project, a: SteerAsk, text: str) -> list[Any]:
    """Le geste d'une demande acceptée, s'il vaut encore (le projet a pu changer entre-temps) ; son texte oublié
    entre-temps, rien."""
    who: dict[str, Any] = {"by": a.by, "owner": p.owner, "about": p.about}
    if a.what == PAUSE:
        return [PAUSED.draft(project=p.id, reason=PAUSED_IN_TALK, **who)] if p.status == c.ACTIVE else []
    if a.what == RESUME:
        return [RESUMED.draft(project=p.id, **who)] if p.status == c.PAUSED else []
    if a.what == NOW:
        if p.status != c.ACTIVE:
            return []
        o = objective_at(p, a.objective) if a.objective else None
        return [NUDGED.draft(project=p.id, objective=o.id if o is not None and o.status == c.OPEN else 0, **who)]
    if not text:
        return []
    if a.what == INSTRUCT:
        return [AMENDED.draft(project=p.id, instruction=Content.of(text, level=p.sensitivity), read_about=p.read_about,
                              **who)]
    if a.what == ADD and living(p) < OBJECTIVES_KEPT:
        return [OBJECTIVE_ADDED.draft(project=p.id, objective=p.objective_seq + 1,
                                      text=Content.of(text, level=written(p)), kind=a.kind, cadence_us=a.cadence_us,
                                      author="owner", read_about=p.read_about, **who)]
    return []


@PROJECTS.effect(rt.EFFECT_EXECUTED)
async def _steer_accepted(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une demande de pilotage acceptée : son geste s'écrit, au nom de qui l'a demandée."""
    frame_of, store = ports.get("frame"), ports.get("store")
    if frame_of is None or not ev.data.ok:
        return None
    s: ProjectsState = frame_of().state("projects")
    asked = s.steer_proposals.get(ev.data.proposal)
    a = s.steers.get(asked) if asked else None
    p = s.projects.get(a.project) if a is not None else None
    if a is None or p is None or p.status not in STEERABLE:
        return None
    text = (store.content([a.text_ref]).get(a.text_ref) or "") if a.text_ref and store is not None else ""
    return accepted(p, a, text)
