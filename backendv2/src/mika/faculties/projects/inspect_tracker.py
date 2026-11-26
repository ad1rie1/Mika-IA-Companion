"""Les onglets « Tickets » et « Suivi » de la fiche d'un projet (ADR 0268), et leurs actions : le registre lu dans sa
projection (``tracker.py``) — un tableau, un filtre par statut, le fil d'un élément ouvert —, et ce que l'opérateur y
fait : créer ou régler une liste, ajouter un élément, ouvrir un ticket, le modifier (son titre, son détail, sa sorte,
sa priorité — ADR 0290), changer un statut, noter, accepter, écarter, fermer ou rouvrir un ticket. Le parcours d'un ticket (ADR 0270) y ajoute le nécessaire : son étape et à qui est la
main sur sa ligne, valider ou refuser son plan, confirmer qu'elle l'écarte, et le réglage de la validation et de la
borne des petits tickets. Le reflet en issues (ADR 0275) y ajoute, lui aussi, le nécessaire : sur un ticket, son issue
et son lien, « Publier » et « Publier cette note » — une demande, dont l'aperçu attend dans « À valider » — ; et le
réglage du reflet à côté de celui de la validation. En table d'exploitation, dessinée bloc par bloc comme l'onglet
Fichiers. Les aides communes de la fiche viennent de ``inspect.py`` et de ``actions.py``."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import issues, tickets, tracker
from mika.faculties.projects.actions import PRIORITY_CHOICES, can_edit, refuse_reserved
from mika.faculties.projects.faculty import (
    ISSUE_ASKED,
    LISTS_MAX,
    MILESTONE_ADDED,
    MOVE_NOTE,
    MOVE_PUBLISH,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    PROJECTS,
    PROTECTED_MAX,
    REFRAMED,
    SMALL_FILES,
    SMALL_FILES_MAX,
    SMALL_LINES,
    SMALL_LINES_MAX,
    TICKETS_OPEN_MAX,
    Item,
    Listing,
    Project,
    ProjectsState,
    issue_move,
    project_at,
    reflected,
)
from mika.faculties.projects.inspect_common import (
    LIVE,
    acting_person,
    subject_project,
    target_project,
    unchanged,
)
from mika.faculties.projects.inspect_issues import CANNOT, ISSUE_FR, PUBLISH_HELP
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Ref,
    Row,
    Table,
    When,
    plural,
)
from mika.kernel.operate import ActionContext, Done, Refused

KIND_WORDS = {c.BUG: "défaut", c.TASK: "tâche", c.IDEA: "idée", c.QUESTION: "question"}
KIND_CHOICES = tuple(KIND_WORDS.items())
PRIORITY_WORDS = dict(PRIORITY_CHOICES)
ACTOR_CHOICES = ((c.ACTOR_SELF, "elle"), (c.ACTOR_OWNER, "le propriétaire du projet"))
STAGE_TONES = {c.STAGE_PROPOSED: "warn", c.STAGE_UNREAD: "info", c.STAGE_ANALYSIS: "info",
               c.STAGE_DECISION: "warn", c.STAGE_VALIDATION: "warn", c.STAGE_WORKING: "info",
               c.STAGE_PR_PENDING: "info", c.STAGE_PR_READY: "warn", c.STAGE_TREATED: "ok",
               c.STAGE_DISMISSED: "muted"}
VERDICTS = (("accept", "accepter (un ticket proposé)"), ("validate", "valider son plan (ta consigne, si tu en as une)"),
            ("refuse", "refuser son plan, avec ton commentaire"),
            ("dismiss", "écarter, avec sa raison (ou confirmer qu'elle l'écarte)"),
            ("done", "fermer comme traité"), ("reopen", "rouvrir"))
REVIEW_CHOICES = ((c.REVIEW_ALWAYS, "toujours"), (c.REVIEW_LARGE, "seulement pour ce qui n'est pas petit"))
ISSUES_CHOICES = ((c.ISSUES_NEVER, "jamais"), (c.ISSUES_ASK, "sur ton accord, ticket par ticket"),
                  (c.ISSUES_ALWAYS, "toujours (la synchronisation)"))
NOTE_WORDS = {tracker.NOTE: "note", tracker.CHANGE: "changement", c.NOTE_QUESTION: "sa question",
              c.NOTE_PLAN: "son plan"}
#: le parcours d'un ticket en six étapes (ADR 0293 ; ``tickets.journey``), en mots, et l'état d'une étape
JOURNEY_WORDS = {tickets.STEP_UNREAD: "Non lu", tickets.STEP_ANALYSIS: "En analyse",
                 tickets.STEP_VALIDATION: "Validation", tickets.STEP_PULL: "Pull request",
                 tickets.STEP_MERGE: "Fusion", tickets.STEP_TREATED: "Traité"}
JOURNEY_STATES = {tickets.PASSED: "passée", tickets.CURRENT: "en cours", tickets.AHEAD: "à venir",
                  tickets.SKIPPED: "sautée"}


# ── Ses mots, dans la console ─────────────────────────────────────────────


def shown_author(frame: Frame, author: str, by: str = "") -> str:
    """Qui a écrit, tel que la console le dit (elle, un projet, une personne par son nom, l'opérateur)."""
    if author == c.BY_SELF:
        return "elle"
    if author == c.BY_HOST:
        return "quelqu'un chez l'hôte"
    if author.startswith(f"{c.BY_PROJECT}:"):
        return f"le projet n° {author.partition(':')[2]}"
    name = identity_c.person_name(frame, by) if by and by not in (c.BY_PERSON, c.BY_OPERATOR) else ""
    return name or ("l'opérateur" if author == c.BY_OPERATOR else "quelqu'un")


def shown_changer(frame: Frame, by: str) -> str:
    """Qui a fait un changement, tel qu'un élément le garde (``tracker.writer``)."""
    return shown_author(frame, by if by in (c.BY_SELF, c.BY_HOST) or by.startswith(f"{c.BY_PROJECT}:") else c.BY_PERSON, by)


def shown_actor(frame: Frame, item: Item) -> str:
    if item.actor == c.ACTOR_OWNER:
        return "le propriétaire"
    if item.actor == c.ACTOR_PERSON:
        return identity_c.person_name(frame, item.person) or "quelqu'un"
    return "elle"


def shown_hand(item: Item) -> str:
    """À qui est la main sur un ticket (ADR 0270) : son étape le dit."""
    who = tickets.hand(item)
    return "le propriétaire" if who == c.ACTOR_OWNER else "elle" if who == c.ACTOR_SELF else "—"


def _status(lst: Listing, status: str) -> Badge:
    words = tracker.status_words(lst.name, status)
    if lst.name == c.TICKETS:
        return Badge(words, STAGE_TONES.get(status, ""))
    return Badge(words, "muted" if status in lst.closed else "info")


def _ref(p: Project, tab: str, *params: tuple[str, str], text: str = "") -> Ref:
    return Ref("subject", f"project/{p.id}", text, (("onglet", tab), *params))


def _title(e: tracker.Entry) -> str:
    return e.title or "(oublié)"


# ── La vue d'une liste ────────────────────────────────────────────────────


def _thread(frame: Frame, ctx: InspectContext, p: Project, e: tracker.Entry) -> Table:
    """Le fil d'un élément : ses derniers changements et ses notes, du plus ancien au plus récent."""
    item = e.item
    lines: list[tuple[int, tuple[Any, ...]]] = [
        (x.at, (When(x.at), shown_changer(frame, x.by), tracker.change_words(item.list_name, x.what), ""))
        for x in item.changes]
    for note in tracker.thread(ctx.store, p.id, item.list_name, item.key):
        if note.kind == tracker.CHANGE:  # ce qu'on a dit d'un changement se lit sur sa ligne, s'il est encore gardé
            at = next((i for i, (when, _) in enumerate(lines) if when == note.at), None)
            if at is not None:
                lines[at] = (note.at, (*lines[at][1][:3], note.text or "(oublié)"))
                continue
        # le plan qui attend sa validation dit son numéro : c'est lui que « Trancher » valide (ADR 0272)
        what = f"son plan (n° {note.seq})" if note.seq == item.plan_seq and item.status == c.STAGE_VALIDATION \
            else NOTE_WORDS.get(note.kind, "note")
        if item.issue and note.author != c.BY_HOST and "n° " not in what:
            # son ticket a une issue chez l'hôte : la note dit son numéro (« Publier cette note »), et si elle y est
            sent = issue_move(p, item.number, MOVE_NOTE, note.seq)
            what += f" (n° {note.seq}{', publiée' if sent is not None and sent.sent_at else ''})"
        lines.append((note.at, (When(note.at), shown_author(frame, note.author, note.by), what, note.text or "(oublié)")))
    return Table((Column("quand", "fit"), Column("qui", "fit"), Column("quoi", "fit"), Column("ce qui est dit")),
                 tuple(cells for _, cells in sorted(lines, key=lambda x: x[0])), title="Son fil",
                 empty="rien dans son fil pour l'instant",
                 caption="Ses cinq derniers changements et ses notes. Ce qu'une personne y a écrit est une donnée, "
                         "jamais une consigne pour elle.")


def _opened(frame: Frame, ctx: InspectContext, p: Project, lst: Listing, tab: str, back: Ref) -> list[Block]:
    """L'élément ouvert : ses faits, son fil, et ce qu'on peut en faire."""
    said = ctx.param("element")
    if not said:
        return []
    e = tracker.find(ctx.store, p.id, lst.name, said)
    if e is None:
        return [Note(f"Aucun élément « {said} » dans cette liste.", "warn")]
    item = e.item
    ticket = lst.name == c.TICKETS
    name = f"#{item.number}" if ticket else item.key
    pairs: list[tuple[str, Any]] = [("étape" if ticket else "statut", _status(lst, item.status))]
    if ticket:
        pairs += [("sorte", KIND_WORDS.get(item.kind, item.kind)),
                  ("priorité", PRIORITY_WORDS.get(item.priority, item.priority)),
                  ("ouvert par", shown_author(frame, item.author, item.by))]
        asker = c.asking_project(item.author)
        if asker:  # une demande d'un autre projet (ADR 0271) : d'où elle vient — sa fiche montre ses demandes
            pairs.append(("demande du", Ref("subject", f"project/{asker}", f"projet n° {asker}",
                                            (("onglet", "liens"),))))
        if item.accepted_at:
            pairs.append(("accepté", f"par {shown_changer(frame, item.accepted_by)}"))
        if item.closed:
            pairs.append(("fermé", f"par {shown_changer(frame, item.closed_by)}"))
        if item.validated_at:
            pairs.append(("plan validé", f"par {shown_changer(frame, item.validated_by)}"
                          + (" (pris comme petit)" if item.small else "")))
        if item.dismissal_at and not item.closed:
            pairs.append(("elle propose", "de l'écarter : confirme (écarter), ou réponds-lui dans son fil"))
        if item.stuck:
            pairs.append(("son objectif", Badge("bloque", "warn")))
    pairs += [("la main à", shown_hand(item) if ticket else shown_actor(frame, item)), ("ajouté", When(item.at)),
              ("touché", When(item.updated_at))]
    if item.objective:
        pairs.append(("objectif", _ref(p, "objectifs", text=f"n° {item.objective}")))
    if e.link:
        pairs.append(("référence", e.link))
    if ticket and item.issue:  # son reflet chez l'hôte (ADR 0275) : le lien est composé ici, du dépôt et du numéro
        pairs.append(("son issue", f"n° {item.issue}, {ISSUE_FR.get(item.issue_state, item.issue_state)}"))
        if url := issues.issue_page(p, item.issue):
            pairs.append(("chez l'hôte", Ref.url(url, url)))
    pairs += [("texte", e.body or "—"), ("fermer", back)]
    initial = (("list_name", lst.name), ("item", name))
    acts: list[Block] = [Disclosure("Répondre à sa question, ou écrire une note dans son fil" if ticket else
                                    "Écrire une note dans son fil", (
        ActionSlot("projects.element_noter", initial, title="Noter", compact=True),))]
    if ticket:
        verdict = {c.STAGE_PROPOSED: "accept", c.STAGE_VALIDATION: "validate"}.get(
            item.status, "dismiss" if item.dismissal_at else "reopen" if item.closed else "done")
        acts.append(Disclosure("Valider ou refuser son plan, accepter, écarter, fermer ou rouvrir ce ticket", (
            # le plan qu'on a sous les yeux part avec le formulaire : réécrit entre-temps, il ne se valide pas
            ActionSlot("projects.ticket_trancher", (("item", name), ("verdict", verdict),
                                                    ("plan", str(item.plan_seq))), title="Trancher", compact=True),)))
        acts += _issue_acts(p, item, name)
    else:
        acts.append(Disclosure("Changer son statut", (
            ActionSlot("projects.element_statut", (*initial, ("status", tracker.status_words(lst.name, item.status))),
                       title="Changer le statut", compact=True),)))
    return [Fields(tuple(pairs), title=f"{name} — {_title(e)}", columns=3), _thread(frame, ctx, p, e), *acts]


def _issue_acts(p: Project, item: Item, name: str) -> list[Block]:
    """Ce qu'on fait partir d'un ticket chez l'hôte (ADR 0275) : le publier — une fois —, puis publier une note de
    son fil, une par une. Chaque geste est une demande : ce qui partira exactement attend dans « À valider »."""
    if not reflected(p):
        return []
    help_ = PUBLISH_HELP.get(p.issues, "")
    if item.issue:
        return [Disclosure("Publier une note de son fil chez l'hôte", (
            Note("Une note à la fois, par son numéro (dans son fil). Elle part du compte du jeton : ton nom n'y "
                 "figure que si c'est ta note ; une note d'elle part sous son nom à elle. " + help_, "muted"),
            ActionSlot("projects.note_publier", (("item", name),), title="Publier cette note", compact=True)))]
    if issues.unpublishable(item):
        return []
    waiting = issue_move(p, item.number, MOVE_PUBLISH)
    if waiting is not None and (waiting.proposal or waiting.sent_at):
        return [Note("Sa publication en issue est demandée : elle attend dans « À valider », ou vient de partir.",
                     "info")]
    return [Disclosure("Publier ce ticket en issue chez l'hôte", (
        Note("Son titre et son texte partent, une seule fois ; son fil reste ici. " + help_, "muted"),
        ActionSlot("projects.ticket_publier", (("item", name),), title="Publier", compact=True)))]


def _list_blocks(frame: Frame, ctx: InspectContext, p: Project, lst: Listing, tab: str) -> list[Block]:
    """Une liste : son filtre par statut, l'élément ouvert, puis son tableau paginé."""
    b = p.board
    base = (("liste", lst.name),) if tab == "suivi" else ()
    wanted = ctx.param("statut")
    known = tuple(dict.fromkeys((*lst.open, *lst.closed, *(st for name, st, _ in b.counts if name == lst.name))))
    chosen = (wanted,) if wanted in known else ()
    here = (*base, *((("statut", wanted),) if chosen else ()))
    nav = Nav((NavItem("tous", _ref(p, tab, *base, text="tous"), tracker.count(b, lst.name), not chosen),
               *(NavItem(tracker.status_words(lst.name, st), _ref(p, tab, *base, ("statut", st)),
                         tracker.count(b, lst.name, st), chosen == (st,)) for st in known)),
              title="Étape" if lst.name == c.TICKETS else "Statut")
    pager = ctx.pager(size=tracker.PAGE, total=tracker.total(ctx.store, p.id, lst.name, statuses=chosen))
    found = tracker.page(ctx.store, p.id, lst.name, statuses=chosen, limit=pager.size, offset=pager.offset)
    ticket = lst.name == c.TICKETS
    rows = []
    for e in found:
        item = e.item
        name = f"#{item.number}" if ticket else item.key
        link = _ref(p, tab, *here, ("element", name), text=_title(e))
        cells = (name, link, _status(lst, item.status), shown_hand(item), KIND_WORDS.get(item.kind, item.kind),
                 PRIORITY_WORDS.get(item.priority, item.priority), shown_author(frame, item.author, item.by),
                 When(item.updated_at)) if ticket else \
            (name, link, _status(lst, item.status), shown_actor(frame, item), When(item.updated_at))
        rows.append(Row(cells, href=_ref(p, tab, *here, ("element", name))))
    columns = (Column("n°", "fit"), Column("titre"), Column("étape", "fit"), Column("la main à", "fit"),
               Column("sorte", "fit"),
               Column("priorité", "fit"), Column("ouvert par", "fit"), Column("touché", "fit")) if ticket else \
        (Column("clé", "fit"), Column("titre"), Column("statut", "fit"), Column("la main à", "fit"),
         Column("touché", "fit"))
    table = Table(columns, tuple(rows), empty="aucun élément", pager=pager, link_label="Ouvrir son fil",
                  caption=f"{plural(tracker.count(b, lst.name), 'élément', 'éléments')} en tout, les derniers touchés "
                          "d'abord. Un titre ouvre l'élément et son fil.")
    return [nav, *_opened(frame, ctx, p, lst, tab, _ref(p, tab, *here, text="revenir à la liste")), table]


@PROJECTS.inspect("tickets", title="Tickets", subject="project", order=22,
                  description="Ce qu'on signale ou demande à ce projet : ses tickets, leur étape (déduite de ce qui "
                              "s'est passé) et à qui est la main, le fil de chacun ; en ouvrir un, répondre à sa "
                              "question, valider ou refuser son plan, l'accepter, l'écarter.")
def _tickets_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = subject_project(s, ctx)
    if isinstance(p, Note):
        return [p]
    # leur réglage (qui valide un plan, la borne d'un petit ticket, la publication en issues) est dans « Cadre »
    # (ADR 0281) : ici, ce qu'on fait d'un ticket
    opening: list[Block] = [
        Disclosure("Ouvrir un ticket", (
            ActionSlot("projects.ticket_ouvrir", title="Ouvrir un ticket", compact=True),)),
        Fields((("la validation des plans, les petits tickets, la publication en issues",
                 _ref(p, "comportement", text="Les régler dans Administration")),), columns=1),
    ] if can_edit(s, frame, str(p.id)) else []
    return [*_list_blocks(frame, ctx, p, tracker.TICKET_LIST, "tickets"), *opening]


@PROJECTS.inspect("suivi", title="Listes", subject="project", order=60,
                  description="Ses listes de suivi (des entreprises à contacter, des articles à relire) : leurs "
                              "éléments par statut, le fil de chacun ; créer ou régler une liste, ajouter un élément.")
def _follow_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = subject_project(s, ctx)
    if isinstance(p, Note):
        return [p]
    lists = p.board.lists
    editable = can_edit(s, frame, str(p.id))
    wanted = ctx.param("liste")
    lst = next((x for x in lists if x.name == wanted), lists[0] if lists else None)
    setting = (("name", lst.name), ("open", "\n".join(lst.open)), ("closed", "\n".join(lst.closed)),
               ("actor", lst.actor)) if lst is not None else ()
    forms: list[Block] = [
        Disclosure("Ajouter un élément", (ActionSlot(
            "projects.element_ajouter", (("list_name", lst.name),) if lst is not None else (),
            title="Ajouter un élément", compact=True),)),
        Disclosure("Créer ou régler une liste", (ActionSlot(
            "projects.liste_regler", setting, title="Créer ou régler une liste", compact=True),)),
    ] if editable else []
    if lst is None:
        return [Note("Ce projet n'a pas encore de liste de suivi : elle en ouvre une avec son premier ajout "
                     "(items_add), ou tu en crées une ici.", "muted"), *forms[1:]]
    texts = ctx.store.content([x.title_ref for x in lists if x.title_ref]) if any(x.title_ref for x in lists) else {}
    nav = Nav(tuple(NavItem(texts.get(x.title_ref, "") or x.name, _ref(p, "suivi", ("liste", x.name)),
                            tracker.living(p.board, x), x.name == lst.name) for x in lists), title="Liste")
    return [nav, *_list_blocks(frame, ctx, p, lst, "suivi"), *forms]


# ── Ce que l'opérateur y fait ─────────────────────────────────────────────


def _listing(p: Project, raw: str) -> Listing:
    name = tracker.named_list(raw)
    lst = tracker.listing(p.board, name) if name is not None else None
    if lst is None:
        raise Refused(f"Ce projet n'a pas de liste « {raw[:40]} ».", {"list_name": "une liste du projet"})
    return lst


def target_entry(p: Project, ctx: ActionContext, lst: Listing, said: str) -> tracker.Entry:
    e = tracker.find(ctx.store, p.id, lst.name, said)
    if e is None:
        raise Refused(f"Aucun élément « {said[:60]} » dans la liste « {lst.name} ».", {"item": "un élément de la liste"})
    return e


def _labels(text: str) -> list[str]:
    """Des statuts saisis un par ligne (ou séparés par des virgules)."""
    return [x.strip() for x in re.split(r"[\n,;]+", text or "") if x.strip()]


class ListSetArgs(BaseModel):
    name: Annotated[str, Knob(label="Nom de la liste", advanced=False, order=1,
                              help="Des minuscules, des chiffres, des tirets (« entreprises ») : c'est le nom que "
                                   "nomment ses outils et un déclencheur item:<liste>. Un nom déjà pris règle cette "
                                   "liste.")] = Field(min_length=1, max_length=40)
    title: Annotated[str, Knob(label="Titre", advanced=False, order=2,
                               help="« Entreprises à contacter ». Vide : son titre ne change pas.")
                     ] = Field(default="", max_length=tracker.TITLE_MAX)
    open: Annotated[str, Knob(label="Statuts ouverts", widget="textarea", advanced=False, order=3,
                              help="Un par ligne, dans l'ordre. Vide : à faire, en cours (et fait, écarté pour les "
                                   "clos).")] = Field(default="", max_length=400)
    closed: Annotated[str, Knob(label="Statuts clos", widget="textarea", advanced=False, order=4,
                                help="Un par ligne : un élément dans un de ces statuts n'est plus à faire.")
                      ] = Field(default="", max_length=400)
    actor: Annotated[str, Knob(label="Qui agit par défaut", choices=ACTOR_CHOICES, advanced=False, order=5)
                     ] = c.ACTOR_SELF


@PROJECTS.action("liste_regler", title="Créer ou régler une liste", args=ListSetArgs, emits=[tracker.LIST_SET],
                 subject="project", order=60, available=can_edit, inline=True,
                 description="Une liste de suivi de plus, ou ses statuts et qui agit par défaut. Les éléments déjà là "
                             "gardent leur statut.")
def _list_set(s: ProjectsState, frame: Frame, args: ListSetArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    name = tracker.named_list(args.name)
    if name is None:
        raise Refused("Ce nom ne s'écrit pas ainsi.", {"name": "des minuscules, des chiffres, des tirets"})
    if name == c.TICKETS:
        raise Refused("La liste des tickets ne se règle pas : un ticket n'a pas de statut posé à la main.",
                      {"name": "un autre nom"})
    if tracker.listing(p.board, name) is None and len(p.board.lists) >= LISTS_MAX - 1:
        raise Refused(f"Ce projet a déjà ses {LISTS_MAX} listes.")
    opened, closed = _labels(args.open), _labels(args.closed)
    for field, given in (("open", opened), ("closed", closed)):
        bad = [x for x in given if tracker.status_label(x) is None]
        if bad:
            raise Refused("Un statut ne s'écrit pas ainsi.",
                          {field: f"« {bad[0][:30]} » : des lettres, des chiffres, des espaces ; "
                                  f"{tracker.STATUS_MAX} caractères au plus"})
    if closed and not opened:
        raise Refused("Il faut au moins un statut ouvert.", {"open": "valeur requise"})
    if len(set(opened) | set(closed)) > tracker.STATUSES_MAX:
        raise Refused(f"Une liste a {tracker.STATUSES_MAX} statuts au plus.", {"open": "trop de statuts"})
    if args.actor not in (c.ACTOR_SELF, c.ACTOR_OWNER):
        raise Refused("Qui agit : elle, ou le propriétaire du projet.", {"actor": "valeur inconnue"})
    draft = tracker.list_setting(p, name, title=args.title, opened=opened, closed=closed, actor=args.actor,
                                 author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message=f"Liste « {name} » enregistrée.", guard=unchanged(p.id, LIVE))


class ItemAddArgs(BaseModel):
    list_name: Annotated[str, Knob(label="Liste", advanced=False, order=1, help="Le nom d'une liste de suivi.")
                         ] = Field(min_length=1, max_length=40)
    title: Annotated[str, Knob(label="Titre", advanced=False, order=2)] = Field(min_length=1,
                                                                               max_length=tracker.TITLE_MAX)
    key: Annotated[str, Knob(label="Clé", advanced=False, order=3,
                             help="Courte et stable (« acme ») : la même clé ne s'ajoute pas deux fois. Vide : "
                                  "déduite du titre.")] = Field(default="", max_length=tracker.KEY_MAX)
    text: Annotated[str, Knob(label="Texte", widget="textarea", advanced=False, order=4)
                    ] = Field(default="", max_length=tracker.TEXT_MAX)
    status: Annotated[str, Knob(label="Statut", advanced=False, order=5, help="Vide : le premier de la liste.")
                      ] = Field(default="", max_length=tracker.STATUS_MAX)
    actor: Annotated[str, Knob(label="Qui a la main", choices=(("", "le réglage de la liste"), *ACTOR_CHOICES),
                               advanced=False, order=6)] = ""
    link: Annotated[str, Knob(label="Référence", advanced=False, order=7, help="Une adresse, un numéro.")
                    ] = Field(default="", max_length=tracker.LINK_MAX)


@PROJECTS.action("element_ajouter", title="Ajouter un élément", args=ItemAddArgs, emits=[tracker.ITEM_ADDED],
                 subject="project", order=61, available=can_edit, inline=True,
                 description="Un élément de plus dans une liste de suivi ; une clé déjà là est refusée.")
def _item_add(s: ProjectsState, frame: Frame, args: ItemAddArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    lst = _listing(p, args.list_name)
    if lst.name == c.TICKETS:
        raise Refused("Un ticket s'ouvre par « Ouvrir un ticket ».", {"list_name": "une liste de suivi"})
    if not args.title.strip():
        raise Refused("Le titre est vide.", {"title": "valeur requise"})
    status = tracker.read_status(lst, args.status) if args.status.strip() else lst.open[0]
    if status is None:
        raise Refused("Ce n'est pas un statut de cette liste.", {"status": tracker.statuses_said(lst)})
    key = tracker.key_of(args.key, args.title)
    if tracker.entry(ctx.store, p.id, lst.name, key) is not None:
        raise Refused("Cet élément est déjà dans la liste.", {"key": "déjà là"})
    actor, person = (args.actor, "") if args.actor in (c.ACTOR_SELF, c.ACTOR_OWNER) else (lst.actor, lst.person)
    draft = tracker.adding(p, lst.name, key, args.title, text=args.text, status=status, actor=actor, person=person,
                           link=args.link, author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message=f"Élément ajouté à « {lst.name} ».", guard=unchanged(p.id, LIVE))


class TicketArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", advanced=False, order=1)] = Field(min_length=1,
                                                                               max_length=tracker.TITLE_MAX)
    text: Annotated[str, Knob(label="Détail", widget="textarea", advanced=False, order=2)
                    ] = Field(default="", max_length=tracker.TEXT_MAX)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False, order=3)] = c.TASK
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, advanced=False, order=4)] = c.NORMAL
    #: comment il naît — vide : ouvert ; ``BORN_PROPOSED`` : proposé, il attend que le propriétaire l'accepte. Jamais
    #: saisi : l'API par personne le pose pour qui ne pilote le projet que sur accord (ADR 0282), comme le fait
    #: ``project_item`` en conversation
    born: Annotated[str, Knob(label="Comment il naît", widget="hidden")] = Field(default="", max_length=12)


#: un ticket qui naît proposé (``TicketArgs.born``)
BORN_PROPOSED = "proposed"


@PROJECTS.action("ticket_ouvrir", title="Ouvrir un ticket", args=TicketArgs, emits=[tracker.ITEM_ADDED],
                 subject="project", order=62, available=can_edit, inline=True,
                 description="Ce que tu signales ou demandes à ce projet : elle le verra à son prochain passage.")
def _ticket_open(s: ProjectsState, frame: Frame, args: TicketArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if not args.title.strip():
        raise Refused("Le titre est vide.", {"title": "valeur requise"})
    if args.kind not in c.TICKET_KINDS or args.priority not in c.PRIORITIES:
        raise Refused("Sorte ou priorité inconnue.")
    if tracker.open_tickets(p.board) >= TICKETS_OPEN_MAX:
        raise Refused(f"Ce projet a déjà {TICKETS_OPEN_MAX} tickets ouverts : fermes-en avant d'en ouvrir d'autres.")
    key = tracker.key_of("", args.title)
    same = tracker.entry(ctx.store, p.id, c.TICKETS, key)
    if same is not None:
        raise Refused(f"Ce ticket existe déjà : #{same.item.number}.", {"title": "déjà ouvert"})
    if args.born not in ("", BORN_PROPOSED):
        raise Refused("Un ticket naît ouvert ou proposé.", {"born": "valeur inconnue"})
    proposed = args.born == BORN_PROPOSED
    draft = tracker.adding(p, c.TICKETS, key, args.title, text=args.text, kind=args.kind, priority=args.priority,
                           proposed=proposed, author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message="Ticket proposé : le propriétaire du projet l'accepte ou l'écarte."
                if proposed else "Ticket ouvert.", guard=unchanged(p.id, LIVE))


class TicketEditArgs(BaseModel):
    item: Annotated[str, Knob(label="Ticket", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    title: Annotated[str, Knob(label="Titre", advanced=False, order=1)] = Field(min_length=1,
                                                                               max_length=tracker.TITLE_MAX)
    text: Annotated[str, Knob(label="Détail", widget="textarea", advanced=False, order=2)
                    ] = Field(default="", max_length=tracker.TEXT_MAX)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False, order=3)] = c.TASK
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, advanced=False, order=4)] = c.NORMAL


@PROJECTS.action("ticket_modifier", title="Modifier un ticket", args=TicketEditArgs, emits=[tracker.ITEM_CHANGED],
                 subject="project", order=68, available=can_edit, inline=True,
                 description="Le titre, le détail, la sorte et la priorité d'un ticket. Son étape ne change pas.")
def _ticket_edit(s: ProjectsState, frame: Frame, args: TicketEditArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, tracker.TICKET_LIST, args.item)
    item = e.item
    title, text = args.title.strip(), args.text.strip()
    if not title:
        raise Refused("Le titre est vide.", {"title": "valeur requise"})
    if args.kind not in c.TICKET_KINDS or args.priority not in c.PRIORITIES:
        raise Refused("Sorte ou priorité inconnue.")
    changes: dict[str, Any] = {}
    if title != e.title.strip():
        changes["title"] = title
    if text and text != e.body.strip():
        changes["text"] = text
    if args.kind != item.kind:
        changes["kind"] = args.kind
    if args.priority != item.priority:
        changes["priority"] = args.priority
    if not changes:
        raise Refused("Rien n'a changé.")
    draft = tracker.changing(p, item, author=c.BY_OPERATOR, by=acting_person(frame, ctx), **changes)
    return Done(drafts=(draft,), message=f"Ticket #{item.number} modifié.", guard=unchanged(p.id, LIVE))


class ItemStatusArgs(BaseModel):
    list_name: Annotated[str, Knob(label="Liste", widget="hidden")] = Field(min_length=1, max_length=40)
    item: Annotated[str, Knob(label="Élément", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    status: Annotated[str, Knob(label="Statut", advanced=False, order=1, help="Un des statuts de la liste.")
                      ] = Field(min_length=1, max_length=tracker.STATUS_MAX)
    note: Annotated[str, Knob(label="Ce que tu en dis", widget="textarea", advanced=False, order=2,
                              help="Facultatif : gardé dans son fil.")] = Field(default="", max_length=tracker.NOTE_MAX)


@PROJECTS.action("element_statut", title="Changer le statut", args=ItemStatusArgs, emits=[tracker.ITEM_CHANGED],
                 subject="project", order=63, available=can_edit, inline=True,
                 description="Le statut d'un élément d'une liste de suivi, posé à la main.")
def _item_status(s: ProjectsState, frame: Frame, args: ItemStatusArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    lst = _listing(p, args.list_name)
    if lst.name == c.TICKETS:
        raise Refused("Un ticket n'a pas de statut posé à la main : accepte-le, écarte-le ou ferme-le.")
    e = target_entry(p, ctx, lst, args.item)
    status = tracker.read_status(lst, args.status)
    if status is None:
        raise Refused("Ce n'est pas un statut de cette liste.", {"status": tracker.statuses_said(lst)})
    draft = tracker.changing(p, e.item, author=c.BY_OPERATOR, by=acting_person(frame, ctx), status=status, note=args.note)
    if tracker.changes_nothing(draft, e.item):
        raise Refused("L'élément a déjà ce statut.")
    return Done(drafts=(draft,), message=f"{e.item.key} : {tracker.status_words(lst.name, status)}.",
                guard=unchanged(p.id, LIVE))


class ItemActorArgs(BaseModel):
    list_name: Annotated[str, Knob(label="Liste", widget="hidden")] = Field(min_length=1, max_length=40)
    item: Annotated[str, Knob(label="Élément", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    actor: Annotated[str, Knob(label="Qui a la main", choices=ACTOR_CHOICES, advanced=False, order=1)] = c.ACTOR_SELF


@PROJECTS.action("element_confier", title="Changer à qui il est", args=ItemActorArgs, emits=[tracker.ITEM_CHANGED],
                 subject="project", order=63, available=can_edit, inline=True,
                 description="À qui est un élément d'une liste de suivi : à elle, ou au propriétaire du projet.")
def _item_actor(s: ProjectsState, frame: Frame, args: ItemActorArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    lst = _listing(p, args.list_name)
    if lst.name == c.TICKETS:
        raise Refused("La main sur un ticket se déduit de son étape : elle ne se pose pas.")
    if args.actor not in (c.ACTOR_SELF, c.ACTOR_OWNER):
        raise Refused("Qui a la main : elle, ou le propriétaire du projet.", {"actor": "valeur inconnue"})
    e = target_entry(p, ctx, lst, args.item)
    if (e.item.actor, e.item.person) == (args.actor, ""):
        raise Refused("Cet élément est déjà à " + ("elle." if args.actor == c.ACTOR_SELF else "son propriétaire."))
    draft = tracker.changing(p, e.item, author=c.BY_OPERATOR, by=acting_person(frame, ctx), actor=args.actor)
    return Done(drafts=(draft,), message=f"{e.item.key} : à " + dict(ACTOR_CHOICES)[args.actor] + ".",
                guard=unchanged(p.id, LIVE))


class ItemNoteArgs(BaseModel):
    list_name: Annotated[str, Knob(label="Liste", widget="hidden")] = Field(min_length=1, max_length=40)
    item: Annotated[str, Knob(label="Élément", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    text: Annotated[str, Knob(label="Note", widget="textarea", advanced=False, order=1,
                              help="Elle la lira dans le fil de l'élément : une donnée, pas une consigne.")
                    ] = Field(min_length=1, max_length=tracker.NOTE_MAX)


@PROJECTS.action("element_noter", title="Noter", args=ItemNoteArgs, emits=[tracker.ITEM_NOTED], subject="project",
                 order=64, available=can_edit, inline=True, description="Une note dans le fil d'un élément.")
def _item_note(s: ProjectsState, frame: Frame, args: ItemNoteArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, _listing(p, args.list_name), args.item)
    if not args.text.strip():
        raise Refused("La note est vide.", {"text": "valeur requise"})
    draft = tracker.noting(p, e.item, args.text, author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message="Note ajoutée à son fil.", guard=unchanged(p.id, LIVE))


class PublishArgs(BaseModel):
    item: Annotated[str, Knob(label="Ticket", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)


def _asked(p: Project, item: Item, what: str, note: int = 0) -> None:
    if not reflected(p):
        raise Refused("Ce projet ne reflète pas ses tickets en issues (son réglage, ou pas de dépôt distant).")
    waiting = issue_move(p, item.number, what, note)
    if waiting is not None and (waiting.proposal or waiting.sent_at):
        raise Refused("C'est déjà demandé : regarde dans « À valider »." if waiting.proposal else
                      "C'est déjà parti chez l'hôte.")


@PROJECTS.action("ticket_publier", title="Publier un ticket en issue", args=PublishArgs, emits=[ISSUE_ASKED],
                 subject="project", order=67, available=can_edit, inline=True,
                 description="Demander la publication d'un ticket en issue chez l'hôte du dépôt distant : son titre "
                             "et son texte, une seule fois. Ce qui partira attend ton accord dans « À valider ».")
def _ticket_publish(s: ProjectsState, frame: Frame, args: PublishArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, tracker.TICKET_LIST, args.item)
    _asked(p, e.item, MOVE_PUBLISH)
    why = issues.refusal(p, e.item, None, 0) or ("" if e.title.strip() else "forgotten")
    if why:
        raise Refused(f"Le ticket #{e.item.number} ne se publie pas : {CANNOT[why]}.")
    draft = issues.asking(p, e.item, author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message=f"Publication du ticket #{e.item.number} demandée : son aperçu est dans "
                                         "« À valider ».", guard=unchanged(p.id, LIVE))


class NotePublishArgs(BaseModel):
    item: Annotated[str, Knob(label="Ticket", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    note: Annotated[int, Knob(label="Note n°", advanced=False, order=1,
                              help="Le numéro de la note, tel que son fil le dit. Une seule note part.")
                    ] = Field(ge=1)


@PROJECTS.action("note_publier", title="Publier une note chez l'hôte", args=NotePublishArgs, emits=[ISSUE_ASKED],
                 subject="project", order=68, available=can_edit, inline=True,
                 description="Demander la publication d'une note du fil d'un ticket en commentaire de son issue : "
                             "cette note-là, et rien d'autre de son fil. Ce qui partira attend dans « À valider ».")
def _note_publish(s: ProjectsState, frame: Frame, args: NotePublishArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, tracker.TICKET_LIST, args.item)
    _asked(p, e.item, MOVE_NOTE, args.note)
    note = tracker.note_at(ctx.store, p.id, c.TICKETS, e.item.key, args.note)
    if why := issues.refusal(p, e.item, note, args.note):
        raise Refused(f"Cette note du ticket #{e.item.number} ne se publie pas : {CANNOT[why]}.",
                      {"note": "une note de son fil"})
    draft = issues.asking(p, e.item, note=args.note, author=c.BY_OPERATOR, by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message=f"Publication de la note n° {args.note} demandée : son aperçu est dans "
                                         "« À valider ».", guard=unchanged(p.id, LIVE))


class SettleArgs(BaseModel):
    item: Annotated[str, Knob(label="Ticket", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    verdict: Annotated[str, Knob(label="Ce que tu en fais", choices=VERDICTS, advanced=False, order=1)] = "accept"
    reason: Annotated[str, Knob(label="Ta raison, ou ta consigne", widget="textarea", advanced=False, order=2,
                                help="Demandée pour écarter (sauf si elle le propose déjà) et pour refuser un plan ; "
                                     "pour valider un plan, elle devient la consigne de son objectif. Gardée dans son "
                                     "fil.")
                      ] = Field(default="", max_length=tracker.NOTE_MAX)
    #: le plan lu sur la fiche (la note qui le porte) : valider ne vaut que si c'est encore celui du ticket (ADR 0272)
    plan: Annotated[int, Knob(label="Plan lu", widget="hidden")] = Field(default=0, ge=0)


@PROJECTS.action("ticket_trancher", title="Trancher un ticket", args=SettleArgs,
                 emits=[tracker.ITEM_CHANGED, OBJECTIVE_ADDED, OBJECTIVE_CHANGED, MILESTONE_ADDED],
                 subject="project", order=65, available=can_edit, inline=True,
                 description="Accepter un ticket proposé, valider ou refuser son plan, l'écarter avec sa raison (ou "
                             "confirmer qu'elle l'écarte), le fermer comme traité, ou le rouvrir.")
def _settle(s: ProjectsState, frame: Frame, args: SettleArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, tracker.TICKET_LIST, args.item)
    item = e.item
    fields: dict[str, Any]
    by = acting_person(frame, ctx)
    if args.verdict == "validate":  # son plan devient un objectif, ta consigne avec lui (ADR 0270)
        plan = tracker.note_text(ctx.store, item.plan_seq)
        why = tracker.validation_refusal(p, item, plan)
        if why:
            raise Refused({"forgotten": f"Le plan du ticket #{item.number} ne se lit plus (il a été oublié).",
                           "full": "Ce projet a déjà trop d'objectifs ouverts."}.get(
                               why, f"Le ticket #{item.number} n'a pas de plan qui attend d'être validé."))
        if args.plan != item.plan_seq:  # réécrit depuis qu'on l'a lu, ou validé sans l'avoir sous les yeux
            raise Refused(f"Le plan du ticket #{item.number} n'est pas celui que tu as lu : c'est maintenant le "
                          f"n° {item.plan_seq}. Relis-le dans son fil, puis valide-le.", {"plan": "plan changé"})
        drafts = tracker.validating(p, item, plan, author=c.BY_OPERATOR, by=by, comment=args.reason)
        free = tracker.free_number(p, item)  # l'objectif qui naît prend un numéro encore libre au moment d'écrire
        return Done(drafts=tuple(drafts), message=f"Plan du ticket #{item.number} validé : un objectif le porte.",
                    guard=unchanged(p.id, LIVE) & free if free is not None else unchanged(p.id, LIVE))
    if args.verdict == "refuse":
        if item.status != c.STAGE_VALIDATION:
            raise Refused(f"Le ticket #{item.number} n'a pas de plan qui attend d'être validé.")
        if not args.reason.strip():
            raise Refused("Un plan ne se refuse pas sans dire pourquoi.", {"reason": "valeur requise"})
        fields, said = {"refused": True}, "repasse en analyse : son plan est refusé"
    elif args.verdict == "accept":
        if item.status != c.STAGE_PROPOSED:
            raise Refused(f"Le ticket #{item.number} n'attend pas d'être accepté.")
        fields, said = {"accepted": True}, "accepté"
    elif args.verdict == "dismiss":
        if item.status not in c.STAGES_OPEN:
            raise Refused(f"Le ticket #{item.number} est déjà fermé.")
        if not args.reason.strip() and not item.dismissal_at:  # elle a déjà dit pourquoi : tu confirmes
            raise Refused("Un ticket ne s'écarte pas sans dire pourquoi.", {"reason": "valeur requise"})
        fields, said = {"closed": c.DROPPED}, "écarté"
    elif args.verdict == "done":
        if item.status not in c.STAGES_OPEN or item.status == c.STAGE_PROPOSED:
            raise Refused(f"Le ticket #{item.number} n'est pas ouvert : accepte-le ou rouvre-le d'abord.")
        fields, said = {"closed": c.DONE}, "fermé comme traité"
    elif args.verdict == "reopen":
        if item.status not in c.STAGES_CLOSED:
            raise Refused(f"Le ticket #{item.number} n'est pas fermé.")
        fields, said = {"closed": ""}, "rouvert"
    else:
        raise Refused("Verdict inconnu.", {"verdict": "accepter, valider, refuser, écarter, fermer ou rouvrir"})
    draft = tracker.changing(p, item, author=c.BY_OPERATOR, by=by, note=args.reason, **fields)
    return Done(drafts=(draft,), message=f"Ticket #{item.number} {said}.", guard=unchanged(p.id, LIVE))


class ReviewArgs(BaseModel):
    ticket_review: Annotated[str, Knob(
        label="Valider le plan d'un ticket", choices=REVIEW_CHOICES, advanced=False, order=1,
        help="Toujours : chaque plan attend ta validation. Sinon, un ticket qu'elle juge petit part sans attendre, "
             "son plan quand même écrit dans le fil — et la borne ci-dessous est vérifiée sur ce qu'elle "
             "enregistre.")] = c.REVIEW_ALWAYS
    small_files: Annotated[int, Knob(label="Un petit ticket : fichiers changés au plus", advanced=False, order=2,
                                     lo=1, hi=SMALL_FILES_MAX)] = Field(default=SMALL_FILES, ge=1, le=SMALL_FILES_MAX)
    small_lines: Annotated[int, Knob(label="Un petit ticket : lignes changées au plus", advanced=False, order=3,
                                     lo=1, hi=SMALL_LINES_MAX)] = Field(default=SMALL_LINES, ge=1, le=SMALL_LINES_MAX)
    protected: Annotated[str, Knob(
        label="Fichiers protégés", widget="textarea", advanced=False, order=4,
        help="Un motif par ligne (« deploy/ », « *.sql », « src/auth.py ») : y toucher n'est jamais petit. Les "
             "fichiers de dépendances (pyproject.toml, package.json, les verrous…) le sont d'office.")
                   ] = Field(default="", max_length=2000)
    issues: Annotated[str, Knob(
        label="Publier ses tickets en issues", choices=ISSUES_CHOICES, advanced=False, order=5,
        help="Chez l'hôte de son dépôt distant (GitHub). Jamais : rien n'y part, et ses issues n'entrent pas. Sur "
             "ton accord : une publication se demande, son aperçu attend dans « À valider » ; une issue ouverte "
             "là-bas entre comme un ticket proposé. Toujours : les tickets que tu ouvres se publient d'eux-mêmes — "
             "ceux qu'elle ouvre, ceux qui nomment quelqu'un et ce qui porte plus que le projet attendent toujours "
             "ton accord. Son fil ne part jamais.")
                ] = c.ISSUES_ASK


def _review_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    if p is None:
        return {}
    b = tickets.bounds(p)
    return {"ticket_review": p.ticket_review, "small_files": b.files, "small_lines": b.lines,
            "protected": "\n".join(p.protected), "issues": p.issues}


@PROJECTS.action("tickets_regler", title="Régler la validation des tickets", args=ReviewArgs, emits=[REFRAMED],
                 subject="project", order=66, available=can_edit, initial=_review_initial, inline=True,
                 description="Quand le plan d'un ticket attend ta validation, la borne d'un petit ticket (ADR "
                             "0270), et quand ses tickets se publient en issues chez l'hôte (ADR 0275).")
def _review_set(s: ProjectsState, frame: Frame, args: ReviewArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if args.ticket_review not in c.REVIEWS:
        raise Refused("Réglage inconnu.", {"ticket_review": "toujours, ou seulement pour ce qui n'est pas petit"})
    if args.issues not in c.ISSUES:
        raise Refused("Réglage inconnu.", {"issues": "jamais, sur ton accord, ou toujours"})
    protected = tuple(dict.fromkeys(x.strip() for x in args.protected.splitlines() if x.strip()))
    if len(protected) > PROTECTED_MAX:
        raise Refused(f"{PROTECTED_MAX} motifs de fichiers protégés au plus.", {"protected": "trop de lignes"})
    b = tickets.bounds(p)
    if (args.ticket_review, args.small_files, args.small_lines, protected, args.issues) == \
            (p.ticket_review, b.files, b.lines, p.protected, p.issues):
        raise Refused("Rien n'a changé.")
    if args.issues != p.issues:  # publier chez l'hôte : à qui s'occupe d'elle seulement (ADR 0292)
        refuse_reserved(frame, ctx, "projects.tickets_regler", ("issues",))
    return Done(drafts=(REFRAMED.draft(project=p.id, ticket_review=args.ticket_review, small_files=args.small_files,
                                       small_lines=args.small_lines, protected=protected, issues=args.issues,
                                       by=ctx.by, owner=p.owner, about=p.about, read_about=p.read_about),),
                message="Validation des tickets réglée.", guard=unchanged(p.id, LIVE))
