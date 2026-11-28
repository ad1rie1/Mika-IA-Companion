"""Le registre d'un projet (ADR 0268), pour elle : ses outils.

- **En exécution** : ``items_add`` (ajouter des éléments, une liste de suivi naît avec son premier ajout),
  ``items_change`` (changer un statut, fermer un ticket), ``items_note`` (noter dans le fil d'un élément),
  ``items_list`` (lire les listes, une page, un élément et son fil). Elle lit tout ce qui est accepté (``RUN``) ; un
  ticket encore proposé n'est pas à elle.
- **En conversation** : ``project_items`` (lire) et ``project_item`` (ouvrir un ticket, changer un statut, noter,
  accepter ou écarter un ticket proposé, valider ou refuser son plan, ADR 0270), pour qui les lignes d'accès du projet
  le permettent (ADR 0133) ; ce qui s'y dit est ce que la personne en face entend du projet (ADR 0272).
- **Les aides de ses outils**, que les jalons lisent aussi (``milestones_tools.py``) : la liste et l'élément qu'un outil
  désigne (``found_entry``), le projet dont il s'agit parmi ceux qu'on peut désigner ici (``chosen_project``).

Le registre lui-même — ses règles, ses événements, ses réducteurs, sa projection, ses mots, et qui le lit
(``Reader``, ``may_read``, ``hears``, ``reader_of``, ``settles``) — est dans ``tracker.py`` ; ses phrases dans la
voix (``projects.tools.items``, ``projects.tools.board``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.faculties.projects import tickets
from mika.faculties.projects.access import reads
from mika.faculties.projects.faculty import (
    LISTS_MAX,
    PROJECTS,
    TICKETS_OPEN_MAX,
    Board,
    Listing,
    Project,
    ProjectsState,
    live,
)
from mika.faculties.projects.inspect_common import unchanged
from mika.faculties.projects.steer import STEERABLE, may_steer, steerable
from mika.faculties.projects.tool_common import (
    RUNS,
    caretaker,
    changed_reply,
    choices_listed,
    contents_of,
    emit_gesture,
    gone_reply,
    running_project,
    speaker,
    which_one,
)
from mika.faculties.projects.tracker import (
    ITEM_ADDED,
    KEY_MAX,
    LINK_MAX,
    NOTE_MAX,
    PER_CALL,
    RUN,
    STATUS_MAX,
    TEXT_MAX,
    TITLE_MAX,
    TITLE_SHOWN,
    Entry,
    Reader,
    adding,
    changes_nothing,
    changing,
    detail,
    entry,
    find,
    free_number,
    handle,
    hears,
    held,
    key_of,
    line,
    list_setting,
    listed,
    listing,
    may_read,
    named_list,
    not_validated,
    note_text,
    noting,
    open_tickets,
    overview,
    read_status,
    reader_of,
    settles,
    status_words,
    statuses_said,
    validating,
    validation_refusal,
)
from mika.kernel.events import Draft
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.text import clipped
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase

# ── Les outils d'une exécution ────────────────────────────────────────────

ADD, CHANGE_TOOL, NOTE_TOOL, LIST = "items_add", "items_change", "items_note", "items_list"
#: ses outils du registre : tenir le projet, pas regarder quelque chose de réel (``tools.BOOKKEEPING``)
TOOLS = (ADD, CHANGE_TOOL, NOTE_TOOL, LIST)


def _store(ctx: Any) -> Any:
    return ctx.ports.get("store")


def _titles(ctx: Any, board: Board) -> Mapping[str, str]:
    return contents_of(ctx, [lst.title_ref for lst in board.lists])


def _no(content: str) -> ToolResult:
    """Le refus d'un outil : rien n'a été écrit."""
    return ToolResult(ok=False, content=content)


def _actor_of(said: str, lst: Listing) -> tuple[str, str]:
    """Qui agit, tel qu'un outil d'exécution le dit (``self``, ``owner``) ; rien de dit : le défaut de la liste."""
    if said in (c.ACTOR_SELF, c.ACTOR_OWNER):
        return said, ""
    return lst.actor, lst.person


class ItemArg(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX, description=phrase("projects.tools.items.arg.title"))
    key: str = Field(default="", max_length=KEY_MAX, description=phrase("projects.tools.items.arg.key"))
    text: str = Field(default="", max_length=TEXT_MAX, description=phrase("projects.tools.items.arg.text"))
    status: str = Field(default="", max_length=STATUS_MAX, description=phrase("projects.tools.items.arg.status"))
    who: Literal["", "self", "owner"] = Field(default="", description=phrase("projects.tools.items.arg.who"))
    link: str = Field(default="", max_length=LINK_MAX, description=phrase("projects.tools.items.arg.link"))
    kind: Literal["", "bug", "task", "idea", "question"] = Field(
        default="", description=phrase("projects.tools.items.arg.kind"))
    priority: Literal["", "low", "normal", "high", "urgent"] = Field(
        default="", description=phrase("projects.tools.items.arg.priority"))


class AddArgs(BaseModel):
    list_name: str = Field(min_length=1, max_length=40, description=phrase("projects.tools.items.arg.list_name"))
    list_title: str = Field(default="", max_length=TITLE_MAX,
                            description=phrase("projects.tools.items.add.list_title"))
    items: list[ItemArg] = Field(min_length=1, max_length=PER_CALL,
                                 description=phrase("projects.tools.items.add.items"))


@PROJECTS.tool(ADD, acts=True, description=phrase("projects.tools.items.add.description"),
               label=phrase("projects.tools.items.add.label"), args=AddArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=6)
async def items_add(args: AddArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    name = named_list(args.list_name)
    if name is None:
        return _no(phrase("projects.tools.items.bad_list", name=args.list_name[:40]))
    b = p.board
    lst = listing(b, name)
    drafts: list[Draft[Any]] = []
    if lst is None:  # une liste de suivi naît avec son premier ajout, aux statuts par défaut
        if len(b.lists) >= LISTS_MAX - 1:
            return _no(phrase("projects.tools.items.lists_full", count=LISTS_MAX))
        lst = Listing(name)
        drafts.append(list_setting(p, name, title=args.list_title))
    ticket = name == c.TICKETS
    room = TICKETS_OPEN_MAX - open_tickets(b) if ticket else PER_CALL
    wanted: dict[str, str] = {}
    twice: list[str] = []
    for it in args.items:
        key = key_of(it.key, it.title)
        status = ""
        if not ticket:
            status = (read_status(lst, it.status) if it.status.strip() else lst.open[0]) or ""
            if not status:
                return _no(phrase("projects.tools.items.bad_status", status=it.status[:STATUS_MAX], name=name,
                                statuses=statuses_said(lst)))
        if key in wanted:
            twice.append(clipped(it.title, TITLE_SHOWN))
            continue
        if len(wanted) >= room:
            return _no(phrase("projects.tools.items.tickets_full", count=TICKETS_OPEN_MAX))
        actor, person = _actor_of(it.who, lst)
        wanted[key] = clipped(it.title, TITLE_SHOWN)
        drafts.append(adding(p, name, key, it.title, text=it.text, status=status, actor=actor, person=person,
                             link=it.link, kind=it.kind, priority=it.priority or c.NORMAL))
    commit = await ctx.emit(*drafts)
    fresh = {e.data.key for e in commit.events if e.type.name == ITEM_ADDED.name}
    after: Board = ctx.frame.state("projects").projects[p.id].board
    done = []
    for key, title in wanted.items():
        if key in fresh:
            item = held(after, name, key)
            done.append(phrase("projects.tools.items.add.one", handle=handle(item) if item is not None else key,
                               title=title))
    dups = twice + [title for key, title in wanted.items() if key not in fresh]
    said = phrase("projects.tools.items.add.done", count=len(done), name=name, added="\n".join(done)) if done else \
        phrase("projects.tools.items.add.none", name=name)
    if dups:
        said += "\n" + phrase("projects.tools.items.add.duplicates", count=len(dups),
                              titles="\n".join(f"- « {t} »" for t in dups))
    return said if done else _no(said)


class ChangeArgs(BaseModel):
    list_name: str = Field(min_length=1, max_length=40, description=phrase("projects.tools.items.arg.list_name"))
    item: str = Field(min_length=1, max_length=KEY_MAX + 1, description=phrase("projects.tools.items.arg.item"))
    status: str = Field(default="", max_length=STATUS_MAX, description=phrase("projects.tools.items.change.status"))
    close: Literal["", "done"] = Field(default="", description=phrase("projects.tools.items.change.close"))
    title: str = Field(default="", max_length=TITLE_MAX, description=phrase("projects.tools.items.arg.title"))
    text: str = Field(default="", max_length=TEXT_MAX, description=phrase("projects.tools.items.arg.text"))
    who: Literal["", "self", "owner"] = Field(default="", description=phrase("projects.tools.items.arg.who"))
    link: str = Field(default="", max_length=LINK_MAX, description=phrase("projects.tools.items.arg.link"))
    kind: Literal["", "bug", "task", "idea", "question"] = Field(
        default="", description=phrase("projects.tools.items.arg.kind"))
    priority: Literal["", "low", "normal", "high", "urgent"] = Field(
        default="", description=phrase("projects.tools.items.arg.priority"))
    objective: int = Field(default=-1, ge=-1, description=phrase("projects.tools.items.change.objective"))
    note: str = Field(default="", max_length=NOTE_MAX, description=phrase("projects.tools.items.change.note"))


def found_entry(ctx: Any, p: Project, raw_list: str, said: str) -> tuple[Listing, Entry] | ToolResult:
    """La liste et l'élément qu'un outil désigne, ou son refus."""
    name = named_list(raw_list)
    lst = listing(p.board, name) if name is not None else None
    if lst is None:
        return _no(phrase("projects.tools.items.no_list", name=raw_list[:40]))
    e = find(_store(ctx), p.id, lst.name, said)
    if e is None:
        return _no(phrase("projects.tools.items.unknown", item=said[:KEY_MAX], name=lst.name))
    return lst, e


async def _written(ctx: Any, p: Project, e: Entry, draft: Draft[Any]) -> Entry | ToolResult:
    """Écrire un changement, puis relire l'élément ; un refus quand il a changé sous elle entre-temps."""
    await ctx.emit(draft)
    after = entry(_store(ctx), p.id, e.item.list_name, e.item.key)
    if after is None or after == e:  # la projection n'a rien changé : ce n'était plus le statut qu'elle voyait
        return _no(phrase("projects.tools.items.moved"))
    return after


@PROJECTS.tool(CHANGE_TOOL, acts=True, description=phrase("projects.tools.items.change.description"),
               label=phrase("projects.tools.items.change.label"), args=ChangeArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=25)
async def items_change(args: ChangeArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    found = found_entry(ctx, p, args.list_name, args.item)
    if isinstance(found, ToolResult):
        return found
    lst, e = found
    status: str | None = None
    closed: str | None = None
    if lst.name == c.TICKETS:
        if args.status.strip():  # un ticket n'a pas de statut posé à la main ; l'écarter revient au propriétaire
            return _no(phrase("projects.tools.items.ticket_status"))
        if e.item.status == c.STAGE_PROPOSED:
            # pas encore accepté : il n'est pas à elle — elle ne le ferme pas, ne le réécrit pas (ADR 0272)
            return _no(phrase("projects.tools.tickets.proposed", number=e.item.number, who=caretaker(ctx.frame)))
        if args.close and (tickets.waits(e.item) or e.item.status in (c.STAGE_WORKING, c.STAGE_PR_PENDING,
                                                                       c.STAGE_PR_READY)):
            # il attend le propriétaire, ou son objectif le fermera en aboutissant (ADR 0270) : pas à la main
            return _no(phrase("projects.tools.tickets.not_now", number=e.item.number,
                              stage=status_words(c.TICKETS, e.item.status)))
        closed = c.DONE if args.close else None
    else:
        if args.close:
            return _no(phrase("projects.tools.items.close_ticket_only", statuses=statuses_said(lst)))
        if args.status.strip():
            status = read_status(lst, args.status)
            if status is None:
                return _no(phrase("projects.tools.items.bad_status", status=args.status[:STATUS_MAX], name=lst.name,
                                statuses=statuses_said(lst)))
    draft = changing(p, e.item, status=status, closed=closed, title=args.title, text=args.text, link=args.link,
                     actor=args.who or None, objective=args.objective if args.objective >= 0 else None,
                     kind=args.kind or None, priority=args.priority or None, note=args.note)
    if changes_nothing(draft, e.item):
        return _no(phrase("projects.tools.items.nothing"))
    after = await _written(ctx, p, e, draft)
    if isinstance(after, ToolResult):
        return after
    return phrase("projects.tools.items.change.done", line=line(ctx.frame, after, RUN))


class NoteArgs(BaseModel):
    list_name: str = Field(min_length=1, max_length=40, description=phrase("projects.tools.items.arg.list_name"))
    item: str = Field(min_length=1, max_length=KEY_MAX + 1, description=phrase("projects.tools.items.arg.item"))
    text: str = Field(min_length=1, max_length=NOTE_MAX, description=phrase("projects.tools.items.note.text"))


@PROJECTS.tool(NOTE_TOOL, acts=True, description=phrase("projects.tools.items.note.description"),
               label=phrase("projects.tools.items.note.label"), args=NoteArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=12)
async def items_note(args: NoteArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    found = found_entry(ctx, p, args.list_name, args.item)
    if isinstance(found, ToolResult):
        return found
    _, e = found
    if not args.text.strip():
        return _no(phrase("projects.tools.items.nothing"))
    await ctx.emit(noting(p, e.item, args.text))
    return phrase("projects.tools.items.note.done", handle=handle(e.item))


class ListArgs(BaseModel):
    list_name: str = Field(default="", max_length=40, description=phrase("projects.tools.items.list.list_name"))
    item: str = Field(default="", max_length=KEY_MAX + 1, description=phrase("projects.tools.items.list.item"))
    status: str = Field(default="", max_length=STATUS_MAX, description=phrase("projects.tools.items.list.status"))
    who: Literal["", "self", "owner", "person"] = Field(
        default="", description=phrase("projects.tools.items.list.who"))
    search: str = Field(default="", max_length=120, description=phrase("projects.tools.items.list.search"))
    page: int = Field(default=1, ge=1, le=500, description=phrase("projects.tools.items.list.page"))


def _read(frame: Frame, store: Any, p: Project, texts: Mapping[str, str], raw_list: str, item: str, status: str,
          who: str, search: str, number: int, reader: Reader) -> str | ToolResult:
    """Lire le registre d'un projet : toutes ses listes, une page d'une liste, ou un élément et son fil — ce que
    ``reader`` peut en lire (ADR 0272)."""
    if not raw_list.strip():
        return overview(p.board, texts)
    name = named_list(raw_list)
    lst = listing(p.board, name) if name is not None else None
    if lst is None:
        return _no(phrase("projects.tools.items.no_list", name=raw_list[:40]))
    if item.strip():
        e = find(store, p.id, lst.name, item)
        if e is None:
            return _no(phrase("projects.tools.items.unknown", item=item[:KEY_MAX], name=lst.name))
        return detail(frame, store, p.id, e, reader)
    chosen = ""
    if status.strip():
        chosen = read_status(lst, status) or ""
        if not chosen:
            return _no(phrase("projects.tools.items.bad_status", status=status[:STATUS_MAX], name=lst.name,
                            statuses=statuses_said(lst)))
    return listed(frame, store, p, lst, status=chosen, actor=who, search=search, number=number, texts=texts,
                  reader=reader)


@PROJECTS.tool(LIST, description=phrase("projects.tools.items.list.description"),
               label=phrase("projects.tools.items.list.label"), args=ListArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=12)
async def items_list(args: ListArgs, ctx: Any) -> Any:
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, _ = got
    return _read(ctx.frame, _store(ctx), p, _titles(ctx, p.board), args.list_name, args.item, args.status,
                 args.who, args.search, args.page, RUN)


# ── En conversation ───────────────────────────────────────────────────────

READ, WRITE = "project_items", "project_item"
TICKET, NOTE_ON, ACCEPT, DISMISS = "ticket", "note", "accept", "dismiss"
#: le plan d'un ticket, validé ou refusé par le propriétaire (ADR 0270)
VALIDATE, REFUSE = "validate", "refuse"


def chosen_project(ctx: Any, said: str, mine: list[Project]) -> tuple[Project, str] | ToolResult:
    """Le projet dont il s'agit parmi ceux qu'on peut désigner ici, et son titre cité ; sinon lesquels."""
    texts = contents_of(ctx, [p.title_ref for p in mine])
    rows = [(p.id, texts.get(p.title_ref, "")) for p in mine]
    pid = which_one(said, rows)
    if pid is None:
        return _no(phrase("projects.tools.steer.which_project",
                        listed=choices_listed(rows, phrase("projects.tools.steer.untitled"))))
    p = next(x for x in mine if x.id == pid)
    title = phrase("projects.tools.steer.quoted", text=texts[p.title_ref]) if texts.get(p.title_ref) else \
        phrase("projects.tools.steer.numbered", id=p.id)
    return p, title


class ReadArgs(BaseModel):
    project: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.steer.project"))
    list_name: str = Field(default="", max_length=40, description=phrase("projects.tools.items.list.list_name"))
    item: str = Field(default="", max_length=KEY_MAX + 1, description=phrase("projects.tools.items.list.item"))
    status: str = Field(default="", max_length=STATUS_MAX, description=phrase("projects.tools.items.list.status"))
    search: str = Field(default="", max_length=120, description=phrase("projects.tools.items.list.search"))
    page: int = Field(default=1, ge=1, le=500, description=phrase("projects.tools.items.list.page"))


@PROJECTS.tool(READ, description=phrase("projects.tools.board.read.description"),
               label=phrase("projects.tools.board.read.label"), args=ReadArgs, bundle="projects",
               episodes=[Kind.REPLY], max_calls_per_episode=4, fits=may_read,
               rule="seulement devant qui les lignes d'accès d'un projet vivant laissent lire son détail")
async def project_items(args: ReadArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    who = speaker(frame)
    aud = frame.audience
    if who is None or aud is None:
        return _no(phrase("projects.tools.board.none"))
    s: ProjectsState = frame.state("projects")
    mine = [p for p in sorted(s.projects.values(), key=lambda x: x.id)
            if live(p) and reads(p, aud, Kind.REPLY, frame) and hears(p, who[1], aud)]
    if not mine:
        return _no(phrase("projects.tools.board.none"))
    got = chosen_project(ctx, args.project, mine)
    if isinstance(got, ToolResult):
        return got
    p, title = got
    read = _read(frame, _store(ctx), p, _titles(ctx, p.board), args.list_name, args.item, args.status, "",
                 args.search, args.page, reader_of(frame, p, who[1], aud))
    if isinstance(read, ToolResult):
        return read
    return phrase("projects.tools.board.read.head", title=title) + "\n" + read


class WriteArgs(BaseModel):
    project: str = Field(min_length=1, max_length=200, description=phrase("projects.tools.steer.project"))
    what: Literal["ticket", "status", "note", "accept", "dismiss", "validate", "refuse"] = Field(
        description=phrase("projects.tools.board.write.what"))
    list_name: str = Field(default=c.TICKETS, max_length=40,
                           description=phrase("projects.tools.items.arg.list_name"))
    item: str = Field(default="", max_length=KEY_MAX + 1, description=phrase("projects.tools.items.arg.item"))
    title: str = Field(default="", max_length=TITLE_MAX, description=phrase("projects.tools.board.write.title"))
    text: str = Field(default="", max_length=TEXT_MAX, description=phrase("projects.tools.board.write.text"))
    kind: Literal["bug", "task", "idea", "question"] = Field(
        default="task", description=phrase("projects.tools.items.arg.kind"))
    priority: Literal["low", "normal", "high", "urgent"] = Field(
        default="normal", description=phrase("projects.tools.items.arg.priority"))
    status: str = Field(default="", max_length=STATUS_MAX, description=phrase("projects.tools.items.change.status"))
    plan: int = Field(default=0, ge=0, description=phrase("projects.tools.board.write.plan"))


@PROJECTS.tool(WRITE, acts=True, description=phrase("projects.tools.board.write.description"),
               label=phrase("projects.tools.board.write.label"), args=WriteArgs, bundle="projects",
               episodes=[Kind.REPLY], max_calls_per_episode=3, fits=may_steer,
               rule="seulement en privé, sur un projet vivant que les lignes d'accès laissent piloter à la personne en "
                    "face ; sur ton accord, son ticket naît proposé")
async def project_item(args: WriteArgs, ctx: Any) -> Any:
    frame: Frame = ctx.frame
    who = speaker(frame)
    aud = frame.audience
    if who is None or aud is None:
        return _no(phrase("projects.tools.steer.not_owner", who=caretaker(frame)))
    person = who[1]
    s: ProjectsState = frame.state("projects")
    mine = [p for p in sorted(s.projects.values(), key=lambda x: x.id)
            if steerable(p, aud, frame) in c.CHANGES and hears(p, person, aud)]
    if not mine:
        return _no(phrase("projects.tools.steer.none"))
    got = chosen_project(ctx, args.project, mine)
    if isinstance(got, ToolResult):
        return got
    p, title = got
    level = steerable(p, aud, frame)
    if args.what == TICKET:
        return await _open_ticket(args, ctx, p, person, title, proposed=level == c.STEER_ASK)
    found = found_entry(ctx, p, args.list_name, args.item)
    if isinstance(found, ToolResult):
        return found
    lst, e = found
    if args.what == NOTE_ON:
        if not args.text.strip():
            return _no(phrase("projects.tools.board.write.no_text"))
        if await emit_gesture(ctx, noting(p, e.item, args.text, author=c.BY_PERSON, by=person),
                          unchanged(p.id, STEERABLE)) is None:
            return changed_reply()
        return phrase("projects.tools.board.write.noted", handle=handle(e.item), title=title)
    if args.what in (ACCEPT, DISMISS, VALIDATE, REFUSE):
        return await _settle(args, ctx, p, e, person, title)
    # changer le statut d'un élément d'une liste de suivi : en modification seulement
    if level != c.STEER_EDIT:
        return _no(phrase("projects.tools.board.write.needs_edit", title=title, who=caretaker(frame)))
    if lst.name == c.TICKETS:
        return _no(phrase("projects.tools.board.write.ticket_status"))
    status = read_status(lst, args.status)
    if status is None:
        return _no(phrase("projects.tools.items.bad_status", status=args.status[:STATUS_MAX], name=lst.name,
                        statuses=statuses_said(lst)))
    draft = changing(p, e.item, author=c.BY_PERSON, by=person, status=status, note=args.text)
    if changes_nothing(draft, e.item):
        return _no(phrase("projects.tools.items.nothing"))
    if await emit_gesture(ctx, draft, unchanged(p.id, STEERABLE)) is None:
        return changed_reply()
    after = entry(_store(ctx), p.id, lst.name, e.item.key)
    if after is None or after == e:
        return _no(phrase("projects.tools.items.moved"))
    return phrase("projects.tools.board.write.changed", title=title,
                  line=line(frame, after, reader_of(frame, p, person, aud)))


async def _open_ticket(args: WriteArgs, ctx: Any, p: Project, person: str, title: str, *, proposed: bool) -> Any:
    """Ouvrir un ticket de vive voix : en modification il est ouvert, sur l'accord du propriétaire il naît proposé.
    Sans clé donnée, la sienne se déduit de son titre : le même ticket redemandé est un doublon, dit avec son
    numéro."""
    if not args.title.strip():
        return _no(phrase("projects.tools.board.write.no_title"))
    if open_tickets(p.board) >= TICKETS_OPEN_MAX:
        return _no(phrase("projects.tools.items.tickets_full", count=TICKETS_OPEN_MAX))
    key = key_of("", args.title)
    draft = adding(p, c.TICKETS, key, args.title, text=args.text, kind=args.kind, priority=args.priority,
                   proposed=proposed, author=c.BY_PERSON, by=person)
    commit = await emit_gesture(ctx, draft, unchanged(p.id, STEERABLE))
    if commit is None:
        return changed_reply()
    e = entry(_store(ctx), p.id, c.TICKETS, key)
    number = e.item.number if e is not None else 0
    if not commit.events:
        return _no(phrase("projects.tools.board.write.duplicate", number=number, title=title))
    if proposed:
        return phrase("projects.tools.board.write.proposed", number=number, title=title, who=caretaker(ctx.frame))
    return phrase("projects.tools.board.write.opened", number=number, title=title)


async def _settle(args: WriteArgs, ctx: Any, p: Project, e: Entry, person: str, title: str) -> Any:
    """Accepter un ticket proposé, écarter un ticket ouvert avec sa raison (la sienne suffit quand c'est elle qui
    propose de l'écarter), valider ou refuser son plan (ADR 0270) — le propriétaire seulement."""
    frame: Frame = ctx.frame
    item = e.item
    if item.list_name != c.TICKETS:
        return _no(phrase("projects.tools.board.write.tickets_only"))
    if not settles(frame, p, person):
        return _no(phrase("projects.tools.board.write.not_theirs", title=title, who=caretaker(frame)))
    if args.what == VALIDATE:
        return await _validate(args, ctx, p, e, person, title)
    if args.what == ACCEPT:
        if item.status != c.STAGE_PROPOSED:
            return _no(phrase("projects.tools.board.write.not_proposed", number=item.number))
        draft = changing(p, item, author=c.BY_PERSON, by=person, accepted=True, note=args.text)
        said = phrase("projects.tools.board.write.accepted", number=item.number, title=title)
    elif args.what == REFUSE:
        if item.status != c.STAGE_VALIDATION:
            return _no(phrase("projects.tickets.refused.no_plan", number=item.number))
        if not args.text.strip():
            return _no(phrase("projects.tools.board.write.no_comment"))
        draft = changing(p, item, author=c.BY_PERSON, by=person, refused=True, note=args.text)
        said = phrase("projects.tools.board.write.refused", number=item.number, title=title)
    else:
        if item.status not in c.STAGES_OPEN:
            return _no(phrase("projects.tools.board.write.already_closed", number=item.number))
        if not args.text.strip() and not item.dismissal_at:  # elle a déjà dit pourquoi : il confirme
            return _no(phrase("projects.tools.board.write.no_reason"))
        draft = changing(p, item, author=c.BY_PERSON, by=person, closed=c.DROPPED, note=args.text)
        said = phrase("projects.tools.board.write.dismissed", number=item.number, title=title)
    if await emit_gesture(ctx, draft, unchanged(p.id, STEERABLE)) is None:
        return changed_reply()
    return said


async def _validate(args: WriteArgs, ctx: Any, p: Project, e: Entry, person: str, title: str) -> Any:
    """Valider le plan d'un ticket (ADR 0270), tel qu'on l'a lu (ADR 0272) : la validation nomme le plan — s'il a
    changé depuis, ou si elle n'en nomme aucun, elle ne vaut pas, et le plan d'aujourd'hui est montré avec son
    numéro. L'objectif qui naît prend le numéro suivant du projet, sous ``free_number`` : si un autre ajout le lui a
    pris entre-temps, elle relit le projet et recommence, une fois."""
    for again in (False, True):
        item = e.item
        plan = note_text(_store(ctx), item.plan_seq)
        why = validation_refusal(p, item, plan)
        if why:
            return _no(not_validated(why, item.number))
        if args.plan != item.plan_seq:
            return _no(phrase("projects.tools.board.write.plan_changed", number=item.number, seq=item.plan_seq,
                              plan=clipped(plan, NOTE_MAX)))
        draft, *more = validating(p, item, plan, author=c.BY_PERSON, by=person, comment=args.text)
        guard, alive = free_number(p, item), unchanged(p.id, STEERABLE)
        if await emit_gesture(ctx, draft, alive & guard if guard is not None else alive, *more) is not None:
            break
        fresh = ctx.mind.frame().state("projects").projects.get(p.id)
        seen = entry(_store(ctx), p.id, c.TICKETS, item.key)
        if again or fresh is None or not live(fresh) or seen is None:
            return changed_reply()
        p, e = fresh, seen
    after = entry(_store(ctx), p.id, c.TICKETS, e.item.key)
    if after is None or not after.item.validated_at:  # le plan a changé sous elle : la validation n'a pas valu
        return changed_reply()
    return phrase("projects.tools.board.write.validated", number=e.item.number, title=title)
