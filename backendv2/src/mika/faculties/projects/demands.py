"""Demander à un autre projet (ADR 0271) : son outil en exécution, et ce que son exécution lit de ses demandes.

Les règles sont pures et ailleurs (``asks.py``) ; ici, ce qui agit et ce qui se lit :

- **``project_ask``** : pendant une exécution, ouvrir un ticket chez un projet que le sien lit. Le droit se relit dans
  le lien à chaque appel (``links.readings``) ; le ticket naît proposé, ou non lu en mode direct (``asks.mode``) ; il
  s'écrit au niveau le plus haut des deux projets et porte, pour l'oubli seulement, les personnes du demandeur
  (``tracker.adding``). Sa clé — le demandeur et l'empreinte de son titre — fait qu'une même demande ne s'empile
  pas.
- **Ce qu'elle en lit** (``lines`` ; la section ``project_asks`` de ``prompt.py``) : ses demandes en quelques lignes
  bornées, celles fermées depuis son dernier passage d'abord, avec la note de leur fermeture. Le titre d'un ticket et
  cette note se relisent dans la projection du projet visé — seulement tant que le lien donne encore son détail
  (``asks.reads``) : le droit de lire repris, il ne reste qu'une ligne qui dit qu'elle existe.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.faculties.projects import asks, links, tracker
from mika.faculties.projects.faculty import (
    ASKS_OPEN_MAX,
    PROJECTS,
    TICKETS_OPEN_MAX,
    Ask,
    Objective,
    Project,
    ProjectsState,
    subjects_of,
    written,
)
from mika.faculties.projects.tool_common import RUNS, gone_reply, running_project
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.text import clipped
from mika.vocab.days import ago_words
from mika.vocab.phrasebook import family, phrase

ASK = "project_ask"
#: ce qu'une demande dit : ce qui est demandé ; son critère et son pourquoi, chacun (caractères)
TEXT_MAX, PART_MAX = 2500, 600


class AskArgs(BaseModel):
    project: int = Field(ge=1, description=phrase("projects.tools.ask.arg.project"))
    title: str = Field(min_length=3, max_length=tracker.TITLE_MAX, description=phrase("projects.tools.ask.arg.title"))
    text: str = Field(min_length=1, max_length=TEXT_MAX, description=phrase("projects.tools.ask.arg.text"))
    done_when: str = Field(min_length=1, max_length=PART_MAX, description=phrase("projects.tools.ask.arg.done_when"))
    why: str = Field(min_length=1, max_length=PART_MAX, description=phrase("projects.tools.ask.arg.why"))
    kind: Literal["", "bug", "task", "idea", "question"] = Field(
        default="", description=phrase("projects.tools.ask.arg.kind"))
    priority: Literal["", "low", "normal", "high", "urgent"] = Field(
        default="", description=phrase("projects.tools.ask.arg.priority"))


def key_of(asker: int, title: str) -> str:
    """La clé du ticket qu'ouvre une demande : le demandeur, puis l'empreinte de son titre (``tracker.key_of``) — la
    même demande du même projet retombe sur la même clé, que le registre dédoublonne ; deux projets qui demandent la
    même chose ouvrent deux tickets."""
    return f"p{asker}-{tracker.key_of('', title)}"


def _no(content: str) -> ToolResult:
    return ToolResult(ok=False, content=content)


def _refused(why: str, p: Project, target: int) -> str:
    """Le refus d'une demande, en une phrase (``asks.refusal``)."""
    if why == asks.UNREAD:
        read = phrase("projects.tools.ask.read", projects=", ".join(f"n° {i}" for i in p.reads)) if p.reads else \
            phrase("projects.tools.ask.none_read")
        return phrase("projects.tools.ask.refused.unread", id=target, read=read)
    if why == asks.NO_RIGHT:
        return phrase("projects.tools.ask.refused.no_right", id=target)
    if why == asks.PER_RUN:
        return phrase("projects.tools.ask.refused.per_run")
    if why == asks.PER_LINK:
        return phrase("projects.tools.ask.refused.per_link", id=target, count=ASKS_OPEN_MAX)
    if why == asks.FULL:
        return phrase("projects.tools.ask.refused.full", id=target)
    return phrase("projects.tools.ask.refused.suspended", id=target)


def _twice(p: Project, target: int, key: str) -> str:
    """Cette demande a déjà été faite : où elle en est, si le demandeur la suit encore."""
    ask = next((a for a in p.asks if a.target == target and a.key == key), None)
    if ask is None:
        return phrase("projects.tools.ask.twice_bare", id=target)
    return phrase("projects.tools.ask.twice", number=ask.number, id=target,
                  state=family("projects.asks.states")[asks.state(ask.status)])


@PROJECTS.tool(ASK, acts=True, description=phrase("projects.tools.ask.description"),
               label=phrase("projects.tools.ask.label"), args=AskArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=8)
async def project_ask(args: AskArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, o = got
    s: ProjectsState = ctx.frame.state("projects")
    # le droit se relit dans le lien, à chaque appel : un droit repris depuis le départ de l'exécution ne demande rien
    reading = next((r for r in links.readings(s, p, links.world_of(ctx.frame)) if r.id == args.project), None)
    why = asks.refusal(p, reading, ctx.episode_id)
    t = reading.project if reading is not None else None
    if not why and t is not None and tracker.open_tickets(t.board) >= TICKETS_OPEN_MAX:
        why = asks.FULL
    if why or reading is None or t is None:
        return _no(_refused(why or asks.SUSPENDED, p, args.project))
    key = key_of(p.id, args.title)
    if tracker.entry(ctx.ports.get("store"), t.id, c.TICKETS, key) is not None:
        return _no(_twice(p, t.id, key))
    direct = asks.mode(p, t, reading.grant) == asks.DIRECT
    body = phrase("projects.asks.body", text=args.text.strip(), done_when=args.done_when.strip(),
                  why=args.why.strip())
    commit = await ctx.emit(tracker.adding(
        t, c.TICKETS, key, args.title, text=body, kind=args.kind or c.TASK, priority=args.priority or c.NORMAL,
        proposed=not direct, author=c.item_author(p.id), origin=o.id if o is not None else 0, level=written(p),
        inherited=subjects_of(p)))
    after: ProjectsState = ctx.frame.state("projects")
    if not any(e.type.name == tracker.ITEM_ADDED.name for e in commit.events):
        return _no(_twice(after.projects[p.id], t.id, key))
    item = tracker.held(after.projects[t.id].board, c.TICKETS, key)
    number = item.number if item is not None else 0
    return phrase("projects.tools.ask.done.direct", number=number, id=t.id) if direct else \
        phrase("projects.tools.ask.done.proposed", number=number, id=t.id)


# ── Ce que l'exécution en lit ─────────────────────────────────────────────

#: ses demandes tiennent en quelques lignes : celles qu'on montre, ce qu'on cite d'un titre et d'une note de fermeture
SHOWN = 8
TITLE_SHOWN, NOTE_SHOWN = 100, 240


def _order(p: Project, since: int) -> list[Ask]:
    """Ses demandes dans l'ordre où elle les lit : celles fermées depuis son dernier passage, puis celles qui sont
    encore ouvertes, puis les autres — les plus récentes d'abord dans chaque groupe."""
    fresh = [a for a in p.asks if a.closed_at > since]
    waiting = [a for a in p.asks if asks.opened(a)]
    old = [a for a in p.asks if not asks.opened(a) and a.closed_at <= since]
    return [*reversed(fresh), *reversed(waiting), *reversed(old)]


def _line(frame: Frame, store: Any, ask: Ask, target: Objective | None, since: int) -> str:
    """Une demande dont le lien donne encore le détail : son ticket, son titre cité, où elle en est, et la note de
    sa fermeture."""
    e = tracker.entry(store, ask.target, c.TICKETS, ask.key)
    note = clipped(" ".join(tracker.note_text(store, ask.note_seq).split()), NOTE_SHOWN)
    return phrase(
        "projects.asks.line", fresh=phrase("projects.asks.fresh") if ask.closed_at > since else "",
        number=ask.number, id=ask.target,
        title=clipped(e.title if e is not None else "", TITLE_SHOWN) or phrase("projects.tracker.forgotten"),
        state=family("projects.asks.states")[asks.state(ask.status)], ago=ago_words(max(0, frame.now - ask.at)),
        mine=phrase("projects.asks.mine") if target is not None and ask.objective == target.id else "",
        note=phrase("projects.asks.note", text=note) if note else "")


def lines(s: ProjectsState, frame: Frame, store: Any, p: Project, target: Objective | None, since: int,
          world: links.World) -> tuple[list[str], tuple[int, ...]]:
    """Ce que lit l'exécution de ses demandes (``SHOWN`` lignes au plus), et les projets dont une ligne dit le
    détail. Une demande à un projet dont le lien ne donne plus le détail ne dit que son existence, une ligne par
    projet. ``since`` : son dernier passage — ce qui s'est fermé depuis vient d'abord."""
    readable: dict[int, bool] = {}
    out: list[str] = []
    hidden: list[int] = []
    wanted = _order(p, since)
    for ask in wanted[:SHOWN]:
        if ask.target not in readable:
            readable[ask.target] = asks.reads(s, p, ask.target, world)
        if readable[ask.target]:
            out.append("- " + _line(frame, store, ask, target, since))
        elif ask.target not in hidden:
            hidden.append(ask.target)
            out.append("- " + phrase("projects.asks.hidden", id=ask.target))
    if len(wanted) > SHOWN:
        out.append(phrase("projects.asks.more", count=len(wanted) - SHOWN))
    return out, tuple(pid for pid, ok in readable.items() if ok)
