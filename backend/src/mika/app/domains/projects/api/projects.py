"""Ses projets, pour qui est connecté (ADR 0282, 0286) : ceux qu'elle voit, ce qui l'y attend (« À faire »), la fiche d'un
projet, son registre (tickets, listes de suivi), ses liens ; et ses gestes — répondre à un plan, ouvrir un ticket,
noter, trancher un ticket ou un point d'arrêt, changer un statut, donner un accord, piloter, poser ce qu'il lit.

**Ses routes, pas ses droits.** Ce qu'elle a d'un projet (``reach`` : la plus serrée de ce que ses lignes d'accès lui
donnent et de ce que la conversation lui en dirait), les refus de ses routes, dans leur ordre, et qui a écrit, en mots
(``author_fields``), sont dans ``reach.py`` — la base de toute l'API des projets ; les règles elles-mêmes, dans le
moteur. Ici : les routes, ce qu'elles rendent, et les mots de la fiche.

Un élément du registre se lit par ``tracker.veiled`` (son niveau, le ticket proposé venu d'ailleurs) ; un projet lié
ne dit son titre que si elle le voit elle-même, et ce que le lien donne vient de ``links``. « À faire » est
``todo.for_person``, filtré par ce qu'elle a de chaque projet : une attente y est comptée pour qui peut la régler
(``todo.awaits``), et celle qu'elle ne peut pas régler ici dit pourquoi — le refus même que sa route rendrait, dans
le même ordre (``_refusal``, qui compose ceux de ``reach.py``).

Chaque geste passe par l'action que la console déclare pour lui (``Call.act`` : en son nom, journalisée,
dédoublonnée, auditée ``moi.projects.<action>``), après la garde que l'outil de conversation applique au même
geste : piloter sur accord ou en modification (``project_item``, ``project_steer``), trancher pour le propriétaire
du projet ou qui s'occupe d'elle (``tracker.settles``), répondre à un plan pour qui l'a demandé, poser un lien pour
son propriétaire (``links.may_link``). Un accord se donne par ``runtime.decisions.decide``, sur le condensé lu.
Un opérateur n'a ici que les droits de la personne qu'il est. Le contrat, route par route : ``docs/protocole-moi.md``,
§ 11.
"""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from starlette.routing import Route

from mika.app.domains.projects.api.reach import (
    AT_CONSOLE,
    BY_HER,
    BY_OTHER,
    LINE_SHOWN,
    LINK_LABELS,
    MERGE_GESTURE,
    MERGE_ROUTE,
    NEEDS_EDIT,
    NOT_DECIDER,
    NOT_LINKER,
    NOT_PLAN_ASKER,
    NOT_READ_YET,
    NOT_SETTLER,
    NOT_STEERED,
    ONLY_SEEN,
    PLAN_MOVED,
    SEEN_NEEDED,
    TEXT_SHOWN,
    UNREADABLE,
    Reach,
    Scene,
    answers_plan,
    author_fields,
    decides,
    edit_refusal,
    frame_refusal,
    merge_refusal,
    milestone_can,
    must_steer,
    objective_can,
    opened_project,
    outside_text,
    person_name,
    reaches,
    reads_files,
    scene,
    store_of,
    texts_of,
    writing_projects,
)
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing, person_of
from mika.app.me.common import millis, snippet
from mika.contracts import forge as forge_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects import (
    actions,
    asks,
    glance,
    inspect_todo,
    issues,
    links,
    milestones,
    pulls,
    rhythm,
    tickets,
    todo,
    tracker,
    triggers,
    work,
)
from mika.faculties.projects.actions import NOT_KEEPER
from mika.faculties.projects.faculty import (
    AMENDED,
    ISSUE_CAPABILITIES,
    NETWORKED_CAPABILITY,
    PULL_REQUEST_CAPABILITY,
    STEER_CAPABILITY,
    Item,
    Listing,
    Objective,
    Project,
    awaiting,
    board_ticket,
    by_pulls,
    handed_over,
    milestones_of,
    objective_at,
    objective_tickets,
    readers_of,
    repo_page,
    ticket_held,
    tie_of,
    written,
    written_on,
)
from mika.faculties.projects.inspect import pull_words, window_words
from mika.faculties.projects.inspect_milestones import CHECK_WORDS
from mika.faculties.projects.inspect_milestones import STATE_FR as MILESTONE_FR
from mika.faculties.projects.inspect_reviews import REVIEW_WORDS
from mika.faculties.projects.inspect_tracker import (
    ACTOR_CHOICES,
    BORN_PROPOSED,
    JOURNEY_STATES,
    JOURNEY_WORDS,
    KIND_WORDS,
    NOTE_WORDS,
    PRIORITY_WORDS,
)
from mika.faculties.projects.inspect_words import CHECKS_FR, OBJ_FR, PULL_FR, STATUS_FR
from mika.faculties.projects.triggers import trigger_words
from mika.kernel.clock import HOUR
from mika.ports.workshop import PULL_OPEN
from mika.runtime import decisions
from mika.runtime.operations import audit
from mika.vocab.access import CHANGES, STEER_ASK, STEER_EDIT, STEER_NO, STEER_WORDS
from mika.vocab.episodes import project_of

#: où vivent ses routes
PATH = "/projets"
#: une page d'éléments, et sa borne
PAGE, PAGE_MAX = 25, 100
#: ce qu'une fiche montre au plus : ses objectifs ponctuels (les ouverts d'abord), ses attentes, ses accords
OBJECTIVES_SHOWN, WAITING_SHOWN, APPROVALS_SHOWN = 40, 60, 20
#: les projets nommés au plus dans chaque liste d'un envoi de liens (``links.LINKS_MAX`` borne ensuite ce qu'il lit)
LINKS_SENT = 12

# ── Ses mots, pour qui regarde son projet ─────────────────────────────────

PLAN_WORDS = {c.UNPLANNED: "sans plan", c.TO_FRAME: "à cadrer", c.PROPOSED: "attend une réponse", c.PLANNED: "validé"}
HAND_WORDS = {c.ACTOR_OWNER: "au propriétaire", c.ACTOR_SELF: "à elle"}
ACTOR_WORDS = {c.ACTOR_SELF: "elle", c.ACTOR_OWNER: "le propriétaire", c.ACTOR_PERSON: "une personne"}
FLOW_WORDS = {c.FLOW_DIRECT: "direct", c.FLOW_PR: "par pull request"}
VEIL_WORDS = {tracker.PROPOSED_VEIL: "proposé par un autre : il se lit quand son propriétaire l'a accepté",
              tracker.LEVEL_VEIL: "d'un niveau que tu n'entends pas ici"}
#: où se fait un geste : ici (une route de cette API), dans la console (rien ici ne le fait), chez l'hôte du dépôt
HERE, CONSOLE, HOST = "ici", "console", "hote"
APPROVAL_GESTURE = "Lire et décider"
#: qui donne un accord, quand aucun prénom ne se sait
KEEPER_WORDS = "qui s'occupe d'elle"

# ── Ce que l'écran attendait encore (ADR 0293) : ses mots ─────────────────

#: un texte écrit à un niveau qu'elle n'entend pas ici (ADR 0292) : il ne se sert pas, et la ligne le dit
TEXT_VEILED = "Un texte d'un niveau que tu n'entends pas ici."
#: un ticket qui ne passe pas par une pull request
SKIPS_PULL = "Ce ticket ne passe pas par une pull request : il saute ces deux étapes."
ISSUE_WORDS = {"open": "ouverte", "closed": "fermée"}
#: où en est un objectif ponctuel, sur la carte d'un projet : fait, en cours (au moins une exécution), à venir, bloqué
PROGRESS_WORDS = {"done": "fait", "doing": "en cours", "todo": "à venir", "blocked": "bloqué"}
#: son prochain passage : daté, en cours, ou pourquoi rien n'est en vue
NEXT_WORDS = {"due": "son prochain passage est daté", "running": "une exécution est en cours",
              "paused": "en pause : rien ne part", "on_demand": "sur demande : il ne part que quand on le lance",
              "idle": "rien de prévu pour l'instant"}
COMING_WORDS = {work.COMING_FRAME: "sa séance de cadrage", work.COMING_REVIEW: "une relecture indépendante",
                work.COMING_RUN: "du travail sur un objectif"}
#: ce qui peut déclencher une mission, sorte par sorte (``triggers.SORTS``)
TRIGGER_SORTS = {triggers.PROJECT: "un projet dont il dépend", triggers.APP: "une de ses apps",
                 triggers.ITEM: "une de ses listes", triggers.WAKE: "un réveil"}
#: les façons de vérifier un jalon (``c.CHECKS``) : ce que chacune veut dire, et ce qu'il faut saisir pour elle
CHECK_HELP = {c.CHECK_PROSE: "Elle dit l'avoir atteint, et comment.",
              c.CHECK_COMMAND: "Elle lance cette commande dans l'atelier, sans réseau, quand elle dit le jalon atteint.",
              c.CHECK_OWNER: "Elle le dit prêt, puis tu le valides ou tu le refuses.",
              c.CHECK_ITEM: "Atteint quand cet élément de son registre a ce statut."}
CHECK_FIELDS = {
    c.CHECK_COMMAND: (("command", "Sa commande", "Telle qu'on la taperait : « pytest -q tests »."),),
    c.CHECK_ITEM: (("item_list", "Liste de l'élément", "« tickets », ou une de ses listes de suivi."),
                   ("item", "Élément", "Sa clé, ou le numéro du ticket."),
                   ("item_status", "Statut attendu", "Un des statuts de cette liste."))}
#: où part ce qui attend un accord
WHERE_ISSUES, WHERE_PULL = "chez l'hôte du dépôt, dans ses issues", "chez l'hôte du dépôt, en pull request"
WHERE_REMOTE, WHERE_NETWORK = "vers son dépôt distant", "sur le réseau, depuis son atelier"
WHERE_PROJECT, WHERE_ELSEWHERE = "dans ce projet", "hors de la machine"
#: ses consignes en attente, ses demandes et ses passages rendus au plus
INSTRUCTIONS_SHOWN, ASKS_SHOWN = 8, 20
WHY_UNREAD = "Ce mot se dit d'un projet que tu vois et que ce projet lit : « why_for », son numéro."


# ── « À faire » ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Awaited:
    """Une attente telle que l'API la rend : l'entrée du moteur, ce qu'elle a du projet, si c'est elle qu'on attend,
    si elle peut la régler ici — et sinon pourquoi (``why``)."""

    entry: todo.Waiting
    reach: Reach
    mine: bool
    can: bool
    veil: str
    why: str = ""


def _item_of(p: Project, w: todo.Waiting) -> Item | None:
    if w.kind == todo.TICKET:
        return board_ticket(p, w.number)
    return tracker.held(p.board, w.what, w.key) if w.kind == todo.ITEM else None


#: ce qu'un ticket attend et qui se tranche ici (``ticket/trancher``) ; fusionner se fait chez l'hôte, débloquer
#: son objectif dans la console
SETTLED_HERE = (todo.ACCEPT, todo.DISMISSAL, todo.VALIDATION)


def _refusal(sc: Scene, r: Reach, w: todo.Waiting) -> str:
    """Pourquoi elle ne peut pas régler cette attente par une route d'ici (vide : elle le peut). C'est le refus même
    que la route rendrait, dit d'avance et dans le même ordre, ou l'endroit où le geste se fait : rien qu'elle
    n'apprendrait pas en essayant."""
    if not r.detail:
        return ONLY_SEEN
    if w.kind == todo.APPROVAL:
        return "" if decides(sc, r, w.number) else NOT_DECIDER
    if w.kind == todo.TICKET and w.what == todo.MERGE:
        return merge_refusal(r, todo.objective_of(r.p, w), sc.frame.now)  # son geste, ici (ADR 0288)
    if w.kind == todo.BLOCKED or (w.kind == todo.TICKET and w.what == todo.STUCK):
        return edit_refusal(r)  # un objectif bloqué se rouvre ici (ADR 0290) : qui le pilote en modification
    if w.kind == todo.TICKET and w.what not in (todo.QUESTION, *SETTLED_HERE):
        return AT_CONSOLE
    if r.steer not in CHANGES:
        return NOT_STEERED
    if w.kind == todo.PLAN:
        return "" if answers_plan(sc, r) else NOT_PLAN_ASKER
    if w.kind in (todo.NEED, todo.STALLED, todo.REVIEW, todo.ITEM):
        return "" if r.steer == STEER_EDIT else NEEDS_EDIT
    if w.kind == todo.CHECKPOINT or (w.kind == todo.TICKET and w.what in SETTLED_HERE):
        return "" if r.reader.settles else NOT_SETTLER
    return "" if w.kind == todo.TICKET else AT_CONSOLE  # la question d'un ticket : qui le pilote y répond


def awaited(sc: Scene, mine: Mapping[int, Reach]) -> list[Awaited]:
    """Ce qui attend dans ses projets, tel qu'elle peut le voir, dans l'ordre du moteur (``todo.for_person`` : une
    attente est à qui peut la régler). Un projet qu'elle ne fait que voir ne dit que ce qui est à sa charge. Ce
    qu'elle ne peut pas régler ici dit pourquoi."""
    found = todo.everywhere(sc.s, todo.pending_in(sc.frame))
    out: list[Awaited] = []
    for seen in todo.for_person(sc.s, sc.world, sc.person, found):
        w = seen.entry
        r = mine.get(w.project)
        if r is None or (not r.detail and not (w.kind == todo.ITEM and w.person == sc.person)):
            continue
        item = _item_of(r.p, w)
        veil = tracker.veiled(r.reader, item) if item is not None else ""
        why = _refusal(sc, r, w) or (UNREADABLE if veil else "")
        # une carte d'accord adressée à quelqu'un (``runtime.DECIDER``) n'attend que lui : le moteur ne le lit pas
        # dans le fait des effets en attente, la garde de la route, si
        hers = seen.mine and (w.kind != todo.APPROVAL or not why)
        out.append(Awaited(w, r, hers, not why, veil, why))
    return out


def _gesture(a: Awaited) -> dict[str, Any]:
    """Le geste qui règle une attente : la route d'ici (``route``, sous ``/projets/<id>/``) et ce qu'elle sait déjà
    (``args``), ou bien où il se fait (la console, l'hôte du dépôt — avec l'adresse de la pull request, ``url``)."""
    w = a.entry
    route, args, label = "", {}, inspect_todo.GESTURES.get(w.kind, "")
    if w.kind == todo.APPROVAL:
        route, args, label = "accord", {"proposal": w.number}, APPROVAL_GESTURE
    elif w.kind == todo.PLAN:
        route = "plan"
    elif w.kind in (todo.NEED, todo.REVIEW):
        route, args = "piloter", {"what": "instruct"}
    elif w.kind == todo.STALLED:
        route, args = "piloter", {"what": "resume"}
    elif w.kind == todo.CHECKPOINT:
        route, args = "jalon", {"objective": w.objective, "milestone": w.number}
    elif w.kind == todo.ITEM:
        route, args = "element/statut", {"list": w.what, "item": w.key}
    elif w.kind == todo.BLOCKED and w.objective:  # le rouvrir, ici (ADR 0290)
        route, args = "objectif/statut", {"objective": w.objective, "status": c.OPEN}
    elif w.kind == todo.TICKET and w.what == todo.STUCK and (held := todo.objective_of(a.reach.p, w)) is not None:
        route, args, label = "objectif/statut", {"objective": held.id, "status": c.OPEN}, \
            inspect_todo.TICKET_GESTURES.get(w.what, "")
    elif w.kind == todo.TICKET:
        label = inspect_todo.TICKET_GESTURES.get(w.what, "")
        if w.what == todo.QUESTION:
            route, args = "element/noter", {"list": c.TICKETS, "item": f"#{w.number}"}
        elif w.what in (todo.ACCEPT, todo.DISMISSAL, todo.VALIDATION):
            given = dict(w.gesture.args)
            route = "ticket/trancher"
            args = {"item": f"#{w.number}", "verdict": given.get("verdict", ""), "plan": int(given.get("plan") or 0)}
    # une pull request prête : la fusionner est son geste, ici (ADR 0288) — en nommant son numéro, et le commit lu
    # (``head``, que rend ``GET …/code/pull``). Sa page chez l'hôte reste dite : composée du dépôt du projet et de
    # son numéro comme la console le fait (``pulls.pull_url`` : jamais une adresse reprise d'un texte de l'hôte) ;
    # rien pour un ticket qu'elle ne lit pas
    merging = w.gesture.where == todo.HOST
    o = todo.objective_of(a.reach.p, w) if merging and not a.veil else None
    if merging and o is not None and o.pull:
        route, args, label = MERGE_ROUTE, {"number": o.pull}, MERGE_GESTURE
    where = HERE if route else HOST if merging else CONSOLE
    return {"route": route, "args": args, "label": label, "where": where,
            "url": pulls.pull_url(a.reach.p, o) if o is not None else ""}


def _awaited_json(sc: Scene, a: Awaited, texts: Mapping[str, str]) -> dict[str, Any]:
    w, p = a.entry, a.reach.p
    if a.veil:  # ni son titre ni sa clé : seulement qu'il attend
        about = f"#{w.number} — {inspect_todo.TICKET_WORDS.get(w.what, '')}" if w.kind == todo.TICKET else \
            f"Un élément de la liste « {w.what} »"
    else:
        about = inspect_todo.about(w, texts)
    item = _item_of(p, w)
    outside = item is not None and c.from_outside(item.author)
    return {"project": p.id, "project_title": texts.get(p.title_ref, ""), "kind": w.kind,
            "kind_label": inspect_todo.KIND_WORDS.get(w.kind, w.kind), "what": w.what,
            "about": snippet(about, 400), "since": millis(w.since), "mine": a.mine, "can": a.can, "why": a.why,
            "waits_for": _waits_for(sc, p, w), "objective": w.objective, "number": w.number,
            "key": "" if a.veil else w.key, "veiled": a.veil, "outside": outside, "gesture": _gesture(a)}


def _waits_for(sc: Scene, p: Project, w: todo.Waiting) -> str:
    """Qui cette attente attend, en mots (``todo.awaits``) : la personne nommée ; pour un accord, qui s'occupe d'elle,
    par son prénom — sa voix les nomme à tous (``identity.keepers``) ; vide : le propriétaire du projet."""
    if w.kind not in todo.KEEPER_ONLY:
        return person_name(sc, w.person)
    names = [n for n in dict.fromkeys(person_name(sc, o) for o in sc.frame.get(identity_c.OWNERS) or ()) if n][:3]
    return " ou ".join(names) or KEEPER_WORDS


def _awaited_refs(found: Iterable[Awaited]) -> list[str]:
    return [ref for a in found for ref in (a.reach.p.title_ref, "" if a.veil else a.entry.ref)]


def count(call: Call) -> int:
    """Pour la barre du haut : ce qui l'attend, elle, dans ses projets."""
    sc = scene(call)
    return sum(1 for a in awaited(sc, reaches(sc)) if a.mine)


# ── Ses projets ───────────────────────────────────────────────────────────


def _rights(sc: Scene, r: Reach) -> dict[str, Any]:
    """Ce qu'elle peut faire de ce projet par les routes d'ici : chaque case est la garde de sa route."""
    changes = r.steer in CHANGES
    return {"steer": r.steer, "steer_label": STEER_WORDS.get(r.steer, r.steer), "detail": r.detail,
            "ticket": changes, "ticket_born": "proposed" if r.steer == STEER_ASK else "open" if changes else "",
            "note": changes, "status": r.steer == STEER_EDIT, "settle": r.settles,
            "plan": answers_plan(sc, r), "pilot": r.steer == STEER_EDIT,
            "links": r.detail and links.may_link(r.p, sc.person, sc.world), "approve": r.detail and sc.keeper,
            "files": reads_files(sc, r), "merge": changes and r.reader.settles,
            # ADR 0290 : son cadre (ses réglages, ses outils, son dépôt, l'archiver) ; ses objectifs, ses jalons,
            # ses tickets et ses décisions ; écrire chez l'hôte sur une pull request ; lire son activité
            "frame": not frame_refusal(r), "edit": not edit_refusal(r),
            "pull_write": r.steer == STEER_EDIT and r.reader.settles,
            "work": r.detail and written(r.p) <= r.reader.level}


def _head(sc: Scene, r: Reach, texts: Mapping[str, str], waiting: int) -> dict[str, Any]:
    p = r.p
    owner = links.owner_of(p)
    return {"id": p.id, "title": texts.get(p.title_ref, ""), "status": p.status,
            "status_label": STATUS_FR.get(p.status, p.status), "mine": r.own, "hers": not owner,
            "owner_name": "" if r.own else person_name(sc, owner), "steer": r.steer,
            "steer_label": STEER_WORDS.get(r.steer, r.steer), "detail": r.detail,
            "where": snippet(texts.get(p.summary_ref, ""), LINE_SHOWN) if r.detail else "",
            "last_run": millis(p.last_run_at) if r.detail else 0,
            "plan": p.plan_state if r.detail else "", "plan_label": PLAN_WORDS.get(p.plan_state, "") if r.detail else "",
            "waiting": waiting}


def _progress(p: Project) -> dict[str, Any]:
    """Où en sont ses objectifs ponctuels, dans l'ordre du plan (``glance.progress``, ADR 0297) : faits, en cours,
    à venir, bloqués — de quoi dessiner la barre de sa carte sans lire sa fiche."""
    states = glance.progress(p)
    counts = {k: sum(1 for _, state in states if state == k) for k in PROGRESS_WORDS}
    return {"total": len(states), **counts,
            "states": [{"id": oid, "state": state, "state_label": PROGRESS_WORDS[state]} for oid, state in states]}


def _card(sc: Scene, r: Reach, mine: Mapping[int, Reach], texts: Mapping[str, str]) -> dict[str, Any] | None:
    """De quoi remplir la carte d'un projet sans lire sa fiche (ADR 0293) — pour qui lit son détail, rien sinon : la
    progression de ses objectifs, ses pull requests et ses tickets ouverts, ce dont il dépend et ce qui dépend de
    lui (un projet lié n'est nommé que si elle le voit), par qui il est mené, sa dernière activité."""
    if not r.detail:
        return None
    p = r.p
    return {"objectives": _progress(p),
            "pulls_open": sum(1 for o in p.objectives if o.pull_state == PULL_OPEN) if by_pulls(p) else 0,
            "tickets_open": tracker.open_tickets(p.board),
            "reads": [_linked(sc, mine, target, texts) for target in p.reads],
            "readers": [_linked(sc, mine, reader.id, texts) for reader in readers_of(sc.s, p.id)],
            "led_by": self_c.name_of(sc.frame.get(self_c.PERSONA)), "last_activity": millis(glance.last_activity(p))}


def _paged(call: Call) -> tuple[int, int]:
    return call.number("page", 1, 1, 10_000), call.number("size", PAGE, 1, PAGE_MAX)


async def overview(call: Call) -> dict[str, Any]:
    """``GET …/projets`` : ses projets, et ce qui l'y attend (« À faire », sa première page)."""
    sc = scene(call)
    mine = reaches(sc)
    found = awaited(sc, mine)
    hers = [a for a in found if a.mine]
    per: dict[int, int] = {}
    for a in hers:
        per[a.entry.project] = per.get(a.entry.project, 0) + 1
    size = call.number("size", PAGE, 1, PAGE_MAX)
    texts = texts_of(call, [*(ref for r in mine.values() for ref in (r.p.title_ref, r.p.summary_ref)),
                          *_awaited_refs(hers[:size])])
    ordered = sorted(mine.values(), key=lambda r: (-per.get(r.p.id, 0), -r.p.last_run_at, r.p.id))
    return {"projects": [{**_head(sc, r, texts, per.get(r.p.id, 0)), "card": _card(sc, r, mine, texts)}
                         for r in ordered],
            "todo": [_awaited_json(sc, a, texts) for a in hers[:size]], "todo_total": len(hers),
            # lui confier un projet (ADR 0290) : qui s'occupe d'elle, comme en conversation
            "create": {"can": sc.keeper, "why": "" if sc.keeper else NOT_KEEPER}}


async def to_do(call: Call) -> dict[str, Any]:
    """``GET …/projets/a-faire`` : « À faire » pour tous ses projets, page par page, dans l'ordre où s'en occuper."""
    sc = scene(call)
    hers = [a for a in awaited(sc, reaches(sc)) if a.mine]
    page, size = _paged(call)
    shown = hers[(page - 1) * size: page * size]
    texts = texts_of(call, _awaited_refs(shown))
    return {"total": len(hers), "page": page, "size": size, "items": [_awaited_json(sc, a, texts) for a in shown]}


# ── La fiche d'un projet ──────────────────────────────────────────────────


def _cadence(o: Objective) -> str:
    return glance.cadence_words(o)


def objective_refs(o: Objective, *, files: bool = False) -> list[str]:
    refs = [o.text_ref, o.done_when_ref, o.need_ref, o.note_ref, o.result_ref, o.routine_ref, o.pull_said_ref,
            o.checks_said_ref, o.review_ref, *o.review_refused[-1:]]
    for m in milestones_of(o):
        refs += [m.text_ref, m.how_ref, m.proof_ref, m.reason_ref, *((m.command_ref,) if files else ())]
    return refs


def _mission_json(o: Objective, texts: Mapping[str, str]) -> dict[str, Any]:
    return {"id": o.id, "text": texts.get(o.text_ref, ""), "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status), "cadence_hours": o.cadence_us // HOUR,
            "cadence_label": _cadence(o), "on": [{"key": k, "label": trigger_words(k)} for k in o.on],
            "only_on_event": o.only_on_event, "last_run": millis(o.last_run_at), "passes": o.passes,
            "each_pass": texts.get(o.routine_ref, "")[:TEXT_SHOWN], "need": texts.get(o.need_ref, "")[:TEXT_SHOWN]}


def milestone_json(o: Objective, texts: Mapping[str, str], *, files: bool = False) -> list[dict[str, Any]]:
    """Ses jalons. ``started`` : elle s'y est mise (``milestones.begun``). Ce qui le lie à un élément de son registre
    (``item_list``, ``item``, ``item_status``) se dit ; sa commande, seulement à qui lit ses fichiers (``files`` :
    elle nomme des chemins, ADR 0292)."""
    waits = awaiting(o)
    begun = milestones.begun(o)
    return [{"id": m.id, "text": texts.get(m.text_ref, ""), "check": m.check,
             "started": m.id in begun, "item_list": m.item_list, "item": m.item_key, "item_status": m.item_status,
             "item_status_label": tracker.status_words(m.item_list, m.item_status) if m.item_status else "",
             "command": shlex.join(milestones.decoded(texts.get(m.command_ref)))[:TEXT_SHOWN]
             if files and m.command_ref else "",
             "check_label": CHECK_WORDS.get(m.check, m.check), "status": m.status,
             "status_label": MILESTONE_FR.get(m.status, m.status), "ready": waits is not None and waits.id == m.id,
             "ready_at": millis(m.ready_at), "reached_at": millis(m.reached_at), "refused_at": millis(m.refused_at),
             "how": texts.get(m.how_ref, "")[:TEXT_SHOWN], "proof": outside_text(texts.get(m.proof_ref, ""), 2000),
             "reason": texts.get(m.reason_ref, "")[:TEXT_SHOWN], "commit": m.commit[:12]}
            for m in milestones_of(o)]


def _ticket_brief(r: Reach, item: Item, texts: Mapping[str, str]) -> dict[str, Any]:
    """Un ticket en une ligne, tel qu'elle peut le lire : ses faits toujours (son numéro, son étape fine, son étape
    du parcours), son titre seulement s'il se lit (``tracker.veiled``)."""
    veil = tracker.veiled(r.reader, item)
    step = tickets.step_of(item.status, tickets.through_pull(item, by_pulls(r.p)))
    return {"number": item.number, "handle": f"#{item.number}", "title": "" if veil else texts.get(item.title_ref, ""),
            "veiled": veil, "veiled_label": VEIL_WORDS.get(veil, ""), "status": item.status,
            "status_label": tracker.status_words(c.TICKETS, item.status), "step": step,
            "step_label": JOURNEY_WORDS.get(step, ""), "open": not item.closed}


def _objective_json(p: Project, o: Objective, texts: Mapping[str, str], *, files: bool = False) -> dict[str, Any]:
    pull = None
    if o.pull_state or o.pull or o.pull_proposal:
        pull = {"number": o.pull, "title": pulls.title_of(o), "url": pulls.pull_url(p, o), "state": o.pull_state,
                "state_label": PULL_FR.get(o.pull_state, o.pull_state), "words": pull_words(o),
                "changes_asked": o.pull_changes, "conflicts": o.pull_conflicts, "at": millis(o.pull_at),
                "awaits_accord": o.pull_proposal, "said": outside_text(texts.get(o.pull_said_ref, ""))}
    checks = None
    if o.checks_sha:
        checks = {"state": o.checks, "state_label": CHECKS_FR.get(o.checks, ""), "sha": o.checks_sha[:12],
                  "at": millis(o.checks_at), "said": outside_text(texts.get(o.checks_said_ref, ""))}
    review = None
    if o.review_at:
        review = {"ok": o.review_ok, "label": REVIEW_WORDS[o.review_ok], "at": millis(o.review_at),
                  "text": texts.get(o.review_ref, "")[:TEXT_SHOWN], "refused": len(o.review_refused),
                  "handed_over": handed_over(o),
                  "last_refusal": texts.get(o.review_refused[-1], "")[:TEXT_SHOWN] if o.review_refused else ""}
    return {"id": o.id, "text": texts.get(o.text_ref, ""), "status": o.status,
            "status_label": OBJ_FR.get(o.status, o.status), "done_when": texts.get(o.done_when_ref, "")[:TEXT_SHOWN],
            "ticket": o.ticket, "need": texts.get(o.need_ref, "")[:TEXT_SHOWN],
            "note": texts.get(o.note_ref, "")[:TEXT_SHOWN], "result": texts.get(o.result_ref, "")[:TEXT_SHOWN],
            "runs": o.runs, "last_run": millis(o.last_run_at), "closed_at": millis(o.closed_at),
            "milestones": milestone_json(o, texts, files=files), "branch": o.branch, "pull": pull,
            "checks": checks, "review": review}


def _statuses(name: str, codes: Iterable[str]) -> list[dict[str, str]]:
    return [{"code": code, "label": tracker.status_words(name, code)} for code in codes]


def _coded(words: Mapping[str, str], codes: Iterable[str]) -> list[dict[str, str]]:
    return [{"code": code, "label": words.get(code, code)} for code in codes]


def _edit_only(r: Reach) -> str:
    """Pourquoi elle ne fait pas un geste réservé à qui le pilote en modification (vide : elle le peut) — le refus
    de ``must_steer(r, edit=True)``, dit d'avance."""
    return "" if r.steer == STEER_EDIT else NOT_STEERED if r.steer not in CHANGES else NEEDS_EDIT


def _steps_counted(p: Project) -> list[dict[str, Any]]:
    """Ses tickets comptés par étape du parcours en six (ADR 0293 ; ``glance.steps``, ADR 0297)."""
    return [{"code": step, "label": JOURNEY_WORDS[step], "count": n} for step, n in glance.steps(p).items()]


def _lists_json(r: Reach, texts: Mapping[str, str]) -> list[dict[str, Any]]:
    """Ses listes. Celle des tickets dit aussi ce qu'il faut pour en ouvrir un : ses sortes et ses priorités, le code
    et ses mots (ceux de la console), et celles qu'un ticket reçoit quand rien n'est dit ; et ses tickets comptés par
    étape du parcours (``journey``). Une liste de suivi dit ce qu'elle peut y faire (``can`` : y ajouter un élément,
    changer à qui il est) et à qui un élément peut être (``actors``)."""
    p, out, why = r.p, [], _edit_only(r)
    for lst in tracker.listings(p.board):
        counts = {status: n for name, status, n in p.board.counts if name == lst.name and n}
        tickets_list = lst.name == c.TICKETS
        can = not why and not tickets_list
        out.append({"name": lst.name, "title": tracker.list_title(lst, texts), "tickets": tickets_list,
                    "journey": _steps_counted(p) if tickets_list else [],
                    "actors": [] if tickets_list else _coded(dict(ACTOR_CHOICES), (c.ACTOR_SELF, c.ACTOR_OWNER)),
                    "can": {"add": can, "assign": can, "why": "" if tickets_list else why},
                    "open": _statuses(lst.name, lst.open), "closed": _statuses(lst.name, lst.closed),
                    "counts": counts, "total": sum(counts.values()), "living": tracker.living(p.board, lst),
                    "actor": lst.actor, "actor_label": ACTOR_WORDS.get(lst.actor, lst.actor),
                    "kinds": _coded(KIND_WORDS, c.TICKET_KINDS) if tickets_list else [],
                    "kind_default": c.TASK if tickets_list else "",
                    "priorities": _coded(PRIORITY_WORDS, c.PRIORITIES) if tickets_list else [],
                    "priority_default": c.NORMAL if tickets_list else ""})
    return out


def _gives(grant: links.Grant) -> dict[str, Any]:
    """Ce qu'un lien donne maintenant, tel que ``links`` le lit dans les lignes d'accès du projet lu."""
    return {"see": grant.see, "detail": grant.detail, "files": grant.view, "docs": grant.documentation,
            "ask": grant.ask,
            "ask_label": STEER_WORDS.get(grant.ask, "") if grant.ask != STEER_NO else ""}


def _linked(sc: Scene, mine: Mapping[int, Reach], project: int, texts: Mapping[str, str]) -> dict[str, Any]:
    """Un projet lié, tel qu'elle peut le voir : son numéro et son titre seulement si elle le voit elle-même."""
    r = mine.get(project)
    return {"project": project, "title": texts.get(r.p.title_ref, ""), "visible": True} if r is not None else \
        {"project": None, "title": "", "visible": False}


def _commit_brief(k: Any, her: str) -> dict[str, Any]:
    """Un commit en une ligne : son empreinte, son message, son instant, qui l'a signé (elle, ou quelqu'un d'autre :
    un commit venu du dépôt distant, dont le message et l'auteur sont des textes d'ailleurs)."""
    return {"sha": k.sha, "short": k.sha[:7], "title": k.title[:400], "at": millis(k.at),
            "author_kind": BY_HER if k.local else BY_OTHER, "author": her if k.local else k.author[:80],
            "outside": not k.local, "branch": k.branch}


async def _commit_at(sc: Scene, p: Project, sha: str = "") -> dict[str, Any] | None:
    """Un commit du dépôt de l'atelier de ce projet — ``sha``, ou le dernier — lu par le port ; ``None`` : pas de
    dépôt, ou un commit inconnu. À ne servir qu'à qui lit le détail de ce projet (ses commits en titres)."""
    port = sc.call.port("workshop")
    if port is None or not port.exists(p.id):
        return None
    if sha:
        found = await port.change(p.id, sha)
        k = found.commit if found is not None else None
    else:
        history = await port.history(p.id, n=1)
        k = history.commits[0] if history is not None and history.commits else None
    return _commit_brief(k, self_c.name_of(sc.frame.get(self_c.PERSONA))) if k is not None else None


def _ask_here(tr: Reach | None) -> dict[str, Any]:
    """« Lui demander quelque chose » (ADR 0293) : peut-elle ouvrir un ticket chez ce projet lié, avec les droits
    qu'elle a sur lui — la garde de ``POST …/projets/<project>/ticket``, dite d'avance ? Un projet qu'elle ne voit
    pas : non, sans un mot de lui."""
    if tr is None:
        return {"can": False, "why": "", "born": "", "project": None, "route": ""}
    can = tr.steer in CHANGES
    return {"can": can, "why": "" if can else NOT_STEERED if tr.detail else ONLY_SEEN,
            "born": "proposed" if tr.steer == STEER_ASK else "open" if can else "", "project": tr.p.id,
            "route": "ticket" if can else ""}


def _demand(sc: Scene, mine: Mapping[int, Reach], names: Mapping[str, str], home: Reach | None, item: Item | None,
            other: int, *,
            direction: str, sender: str, number: int = 0, status: str = "", at: int = 0, closed_at: int = 0,
            title: str = "") -> dict[str, Any]:
    """Une demande entre deux projets (ADR 0271), telle qu'elle peut la lire : ``other`` — l'autre projet, nommé
    seulement si elle le voit ; ``home`` — ce qu'elle a du projet où vit le ticket ; son titre seulement si elle lit
    ce ticket là-bas (``tracker.veiled``) ; son étape fine et son étape du parcours."""
    status = item.status if item is not None else status
    flow = home is not None and by_pulls(home.p)
    step = tickets.step_of(status, tickets.through_pull(item, flow) if item is not None else flow)
    veil = (tracker.veiled(home.reader, item) if item is not None else "") if home is not None and home.detail \
        else tracker.LEVEL_VEIL
    return {**_linked(sc, mine, other, names), "direction": direction, "from": sender,
            "number": (item.number if item is not None else number) if home is not None else 0,
            "title": "" if veil else title, "veiled": bool(veil), "status": status,
            "status_label": tracker.status_words(c.TICKETS, status), "step": step,
            "step_label": JOURNEY_WORDS.get(step, ""), "at": millis(item.at if item is not None else at),
            "closed_at": millis(item.closed_at if item is not None else closed_at)}


def _sent(sc: Scene, r: Reach, mine: Mapping[int, Reach], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """Ses demandes aux projets qu'il lit (``Project.asks``), les plus récentes d'abord : le ticket se relit chez le
    projet visé, pour qui lit son détail."""
    out = []
    for a in sorted(r.p.asks, key=lambda a: -a.at)[:ASKS_SHOWN]:
        home = mine.get(a.target)
        e = tracker.entry(store_of(sc.call), a.target, c.TICKETS, a.key) if home is not None and home.detail else None
        out.append(_demand(sc, mine, names, home, e.item if e is not None else None, a.target, direction="sent",
                           sender="project", number=a.number, status=a.status, at=a.at, closed_at=a.closed_at,
                           title=e.title if e is not None else ""))
    return out


def _yours(sc: Scene, mine: Mapping[int, Reach], names: Mapping[str, str], target: int) -> list[dict[str, Any]]:
    """Les tickets qu'elle a ouverts elle-même chez un projet lié, parmi ceux que son état garde : ce que « Lui
    demander quelque chose » a donné, à côté des demandes du projet."""
    home = mine.get(target)
    if home is None or not home.detail:
        return []
    found = [x for x in home.p.board.items if x.list_name == c.TICKETS and x.number
             and x.author in (c.BY_PERSON, c.BY_OPERATOR) and x.by and person_of(sc.frame, x.by) == sc.person]
    texts = texts_of(sc.call, [x.title_ref for x in found])
    return [_demand(sc, mine, names, home, x, target, direction="sent", sender="you",
                    title=texts.get(x.title_ref, ""))
            for x in sorted(found, key=lambda x: -x.at)[:ASKS_SHOWN]]


def _received(sc: Scene, r: Reach, mine: Mapping[int, Reach], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """Les demandes que d'autres projets lui ont adressées, parmi les tickets que son état garde (les ouverts, les
    derniers touchés), les plus récentes d'abord."""
    found = asks.received(r.p)
    texts = texts_of(sc.call, [x.title_ref for x in found])
    return [_demand(sc, mine, names, r, x, c.asking_project(x.author), direction="received", sender="project",
                    title=texts.get(x.title_ref, "")) for x in sorted(found, key=lambda x: -x.at)[:ASKS_SHOWN]]


async def _links_json(sc: Scene, r: Reach, mine: Mapping[int, Reach]) -> dict[str, Any]:
    """Ses dépendances. Par lien (ADR 0293) : depuis quand (``since``), le mot de son propriétaire (``why`` — un
    texte du projet lecteur : il se lit avec le détail de ce projet-là, et seulement si elle voit aussi le projet
    lu), le commit que montre la vue de l'atelier (``commit`` : pour qui lit le détail du projet lu), les demandes
    entre les deux (``asks``) et si elle peut lui demander quelque chose (``ask_here``)."""
    p = r.p
    readings = links.readings(sc.s, p, sc.world)
    readers = links.readers(sc.s, p, sc.world)
    may = links.may_link(p, sc.person, sc.world)
    # ceux qu'elle peut lui faire lire : ceux qu'il peut se mettre à lire (``links.candidates``) et qu'elle voit
    offered = [t for t in links.candidates(sc.s, p, sc.world) if t.id in mine] if may else []
    ties = {reader.id: tie_of(reader, p.id) for reader, _ in readers}
    texts = texts_of(sc.call, [*(x.p.title_ref for x in mine.values()), *(t.why_ref for t in p.ties),
                             *(t.why_ref for t in ties.values())])
    sent, received = _sent(sc, r, mine, texts), _received(sc, r, mine, texts)
    reads = []
    for x in readings:
        tr, tie = mine.get(x.id), tie_of(p, x.id)
        shown = tr is not None and tr.detail and x.grant.view and x.project is not None
        reads.append({
            **_linked(sc, mine, x.id, texts), "suspended": x.suspended, "gives": _gives(x.grant),
            "direct": x.id in p.direct, "since": millis(tie.since),
            "why": texts.get(tie.why_ref, "")[:LINE_SHOWN] if tr is not None else "",
            "commit": await _commit_at(sc, x.project, x.project.base_commit) if shown and x.project.base_commit
            else None,
            "asks": [a for a in sent if a["project"] == x.id] + _yours(sc, mine, texts, x.id),
            "ask_here": _ask_here(tr)})
    return {
        "reads": reads,
        "plan_asks": [_linked(sc, mine, t, texts) for t in p.plan_reads if t not in p.reads],
        "readers": [{**_linked(sc, mine, reader.id, texts), "gives": _gives(grant),
                     "since": millis(ties[reader.id].since),
                     "why": texts.get(ties[reader.id].why_ref, "")[:LINE_SHOWN]
                     if (rr := mine.get(reader.id)) is not None and rr.detail else "",
                     "asks": [a for a in received if a["project"] == reader.id]} for reader, grant in readers],
        "asks": sent, "received": received,
        "can": may,
        "candidates": [{**_linked(sc, mine, t.id, texts), "gives": _gives(links.grant(p, t, sc.world))}
                       for t in offered],
        "labels": LINK_LABELS}


def _repo_json(r: Reach) -> dict[str, Any]:
    p = r.p
    return {"has_remote": bool(p.remote), "remote": p.remote if r.own else "", "branch": p.branch, "flow": p.flow,
            "flow_label": FLOW_WORDS.get(p.flow, p.flow), "auto_push": p.auto_push, "last_commit": p.last_commit[:12],
            "remote_ok": p.remote_ok, "remote_at": millis(p.remote_at), "remote_line": outside_text(p.remote_line, 400)}


def _next_json(sc: Scene, r: Reach, texts: Mapping[str, str]) -> dict[str, Any]:
    """Son prochain passage (``work.coming``) : quand, ce que ce sera, sur quel objectif — ou pourquoi rien n'est en
    vue. Rien n'est estimé : ``at`` vaut 0 tant que le moteur ne le date pas."""
    p = r.p
    coming = work.coming(p, sc.s, sc.frame)
    o = objective_at(p, coming.objective) if coming.objective else None
    state = glance.next_state(p, sc.s, coming)
    return {"at": millis(coming.at), "state": state, "state_label": NEXT_WORDS[state], "sort": coming.sort,
            "sort_label": COMING_WORDS.get(coming.sort, ""),
            "objective": {"id": o.id, "text": texts.get(o.text_ref, ""), "kind": o.kind} if o is not None else None}


def _instructions(sc: Scene, r: Reach) -> list[dict[str, Any]]:
    """Ses consignes en attente : celles données depuis le départ de sa dernière exécution — elle les lira à la
    suivante. Relues du journal ; chacune à son niveau (ADR 0292), qui l'a donnée selon la règle des noms."""
    p, mind = r.p, sc.call.kernel.mind
    found = [mind.decode(x) for x in mind.store.latest([AMENDED.name], INSTRUCTIONS_SHOWN, where=("project", p.id))]
    waiting = [e for e in found if e.at > p.last_run_at]
    heard = {e.seq: int(e.data.instruction.level or 0) <= r.reader.level for e in waiting}
    texts = texts_of(sc.call, [e.data.instruction.ref or "" for e in waiting if heard[e.seq]])
    return [{"seq": e.seq, "at": millis(e.at), "veiled": not heard[e.seq],
             "text": texts.get(e.data.instruction.ref or "", "")[:TEXT_SHOWN] if heard[e.seq] else TEXT_VEILED,
             **author_fields(sc, {}, c.BY_PERSON, e.data.by, written(p))} for e in waiting]


def _triggers_json(sc: Scene, r: Reach, mine: Mapping[int, Reach], texts: Mapping[str, str]) -> list[dict[str, Any]]:
    """Ce qui peut déclencher une mission de ce projet (ADR 0265), avec ses mots : les projets dont il dépend — ceux
    qu'elle voit —, ses apps, ses listes, et ceux que ses missions ont déjà ; les réveils de l'instance, pour qui
    s'occupe d'elle seulement (comme les services branchés, ADR 0292)."""
    p = r.p
    keys = [key for target in p.reads for key in (triggers.commit_key(target), triggers.done_key(target))]
    keys += [triggers.app_key(a.name) for a in sc.frame.get(forge_c.APPS) or () if a.project == p.id]
    keys += [triggers.item_key(lst.name) for lst in tracker.listings(p.board)]
    wake = sc.call.port("wakeup")
    if sc.keeper and wake is not None:
        keys += [triggers.wake_key(ep.name) for ep in wake.endpoints()]
    keys += [key for o in p.objectives if o.kind == c.CONSTANT and o.status != c.DROPPED for key in o.on]
    out = []
    for key in dict.fromkeys(keys):
        t = triggers.read(key)
        if t is None or (t.sort == triggers.PROJECT and t.project not in mine):
            continue  # un projet lu qu'elle ne voit pas ne se nomme pas, même par son numéro
        seen = mine.get(t.project) if t.sort == triggers.PROJECT else None
        out.append({"key": key, "label": trigger_words(key), "sort": t.sort,
                    "sort_label": TRIGGER_SORTS.get(t.sort, t.sort), "project": t.project or None,
                    "title": texts.get(seen.p.title_ref, "") if seen is not None else ""})
    return out


def _forms_json(sc: Scene, r: Reach, mine: Mapping[int, Reach], texts: Mapping[str, str]) -> dict[str, Any]:
    """De quoi remplir les formulaires d'un objectif et d'un jalon (ADR 0293) : ce qui peut déclencher une mission,
    et les façons de vérifier un jalon — leurs mots, et ce qu'il faut saisir pour chacune."""
    why = edit_refusal(r)
    return {"can": not why, "why": why, "triggers": _triggers_json(sc, r, mine, texts),
            "triggers_max": triggers.TRIGGERS_MAX,
            "checks": [{"code": check, "label": CHECK_WORDS[check], "help": CHECK_HELP[check],
                        "fields": [{"name": name, "label": label, "help": said, "required": True}
                                   for name, label, said in CHECK_FIELDS.get(check, ())]} for check in c.CHECKS]}


def _with_can(r: Reach, o: Objective, shown: dict[str, Any]) -> dict[str, Any]:
    """Un objectif et ses jalons, chacun avec ce qu'elle peut en faire ici (ADR 0290)."""
    alive = {m.id: m for m in milestones_of(o)}
    return {**shown, "can": objective_can(r, o),
            "milestones": [{**m, "can": milestone_can(r, alive[m["id"]])} for m in shown["milestones"]]}


async def fiche(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>`` : où il en est — ce qui l'attend, ses missions, ses objectifs et leurs jalons, son
    plan —, ses listes, ses liens, son dépôt en bref. Qui ne fait que le voir n'en reçoit que l'en-tête."""
    sc, r = opened_project(call, detail=False)
    p = r.p
    mine = reaches(sc)
    found = [a for a in awaited(sc, mine) if a.entry.project == p.id][:WAITING_SHOWN]
    once = sorted((o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED),
                  key=lambda o: (o.status not in (c.OPEN, c.BLOCKED), -o.id))[:OBJECTIVES_SHOWN]
    constants = [o for o in p.objectives if o.kind == c.CONSTANT and o.status != c.DROPPED]
    refs = [p.title_ref, p.summary_ref, p.description_ref, *_awaited_refs(found)]
    files = r.detail and reads_files(sc, r)
    held = {o.id: objective_tickets(p, o) for o in once} if r.detail else {}
    if r.detail:
        refs += [p.plan_ref, p.questions_ref, *(lst.title_ref for lst in p.board.lists),
                 *(ref for o in (*once, *constants) for ref in objective_refs(o, files=files)),
                 *(x.title_ref for found_ in held.values() for x in found_),
                 *(x.p.title_ref for x in mine.values())]
    texts = texts_of(call, refs)
    head = _head(sc, r, texts, sum(1 for a in found if a.mine))
    out: dict[str, Any] = {"project": {**head, "description": texts.get(p.description_ref, "")[:TEXT_SHOWN]},
                           "rights": _rights(sc, r), "todo": [_awaited_json(sc, a, texts) for a in found]}
    if not r.detail:
        return out
    out.update({
        "missions": [{**_mission_json(o, texts), "can": objective_can(r, o)} for o in constants],
        "objectives": [_with_can(r, o, {**_objective_json(p, o, texts, files=files),
                                        "tickets": [_ticket_brief(r, x, texts) for x in held[o.id]]})
                       for o in once],
        # ADR 0293 : son prochain passage, son rythme en une phrase, ses consignes en attente, et de quoi remplir
        # les formulaires d'un objectif et d'un jalon
        "next": _next_json(sc, r, texts),
        "rhythm": {"schedule": rhythm.schedule_words(p.schedule), "window": window_words(p),
                   "summary": f"{rhythm.schedule_words(p.schedule)} · {window_words(p)}"},
        "instructions": _instructions(sc, r), "forms": _forms_json(sc, r, mine, texts),
        "plan": {"state": p.plan_state, "state_label": PLAN_WORDS.get(p.plan_state, p.plan_state),
                 "text": texts.get(p.plan_ref, "")[:TEXT_SHOWN], "questions": texts.get(p.questions_ref, "")[:TEXT_SHOWN],
                 "at": millis(p.plan_at), "version": p.plan_version, "asked_by": person_name(sc, p.asked_by)},
        "lists": _lists_json(r, texts), "links": await _links_json(sc, r, mine),
        # son dernier commit, avec son message et son instant : le détail donne les titres de ses commits (ADR 0288)
        "repo": {**_repo_json(r), "commit": await _commit_at(sc, p)}})
    return out


# ── Son registre : tickets et listes de suivi ─────────────────────────────


def _listing(r: Reach, raw: str) -> Listing:
    name = tracker.named_list(raw or c.TICKETS)
    lst = tracker.listing(r.p.board, name) if name is not None else None
    if lst is None:
        raise missing()
    return lst


def _journey_json(p: Project, item: Item) -> dict[str, Any]:
    """Le parcours d'un ticket en six étapes (``tickets.journey``, ADR 0293) : chacune avec son état ; celle où il
    est, et à côté son étape fine et ses mots (``fine``), sa précision ; les étapes qu'il saute s'il ne passe pas par
    une pull request ; comment il a fini."""
    j = tickets.journey(item, by_pulls(p))
    return {"steps": [{"code": step, "label": JOURNEY_WORDS[step], "state": state,
                       "state_label": JOURNEY_STATES[state]} for step, state in j.steps],
            "current": j.current, "current_label": JOURNEY_WORDS.get(j.current, ""), "fine": item.status,
            "fine_label": tracker.status_words(c.TICKETS, item.status), "through_pull": j.through_pull,
            "skips": [] if j.through_pull else list(tickets.CODE_STEPS),
            "skips_label": "" if j.through_pull else SKIPS_PULL, "ended": j.ended,
            "ended_label": tracker.status_words(c.TICKETS, j.ended) if j.ended else ""}


def _entry_json(sc: Scene, r: Reach, e: tracker.Entry, titles: Mapping[int, str], *,
                full: bool = False) -> dict[str, Any]:
    """Un élément tel qu'elle peut le lire : ses faits toujours ; son titre, son texte et sa référence seulement si
    son niveau et son étape le lui laissent lire (``tracker.veiled``). Qui l'a ouvert se dit par sa sorte ; par son
    nom, seulement si elle lit l'élément et a le droit de le savoir (``author_fields``)."""
    item = e.item
    veil = tracker.veiled(r.reader, item)
    ticket = item.list_name == c.TICKETS
    hand = tickets.hand(item) if ticket and not item.closed else ""
    out: dict[str, Any] = {
        "list": item.list_name, "handle": tracker.handle(item) if not veil or ticket else "", "number": item.number,
        "key": "" if veil else item.key, "title": "" if veil else e.title, "veiled": veil,
        "veiled_label": VEIL_WORDS.get(veil, ""), "status": item.status,
        "status_label": tracker.status_words(item.list_name, item.status), "open": not item.closed if ticket else
        item.status not in _listing(r, item.list_name).closed, "hand": hand, "hand_label": HAND_WORDS.get(hand, ""),
        "yours": hand == c.ACTOR_OWNER and r.settles, "kind": item.kind, "kind_label": KIND_WORDS.get(item.kind, ""),
        "priority": item.priority, "priority_label": PRIORITY_WORDS.get(item.priority, ""), "actor": item.actor,
        "actor_label": person_name(sc, item.person) if item.actor == c.ACTOR_PERSON else ACTOR_WORDS.get(item.actor, ""),
        **author_fields(sc, titles, item.author, item.by, written_on(r.p, item), veiled=bool(veil)),
        "outside": c.from_outside(item.author), "objective": item.objective, "notes": item.notes, "at": millis(item.at), "updated_at": millis(item.updated_at),
        "plan": item.plan_seq, "issue": item.issue, "pull": item.pull_number,
        # ADR 0293 : son étape du parcours en six (vide : écarté, ou pas un ticket), ce que l'hôte dit de son issue
        "step": (step := tickets.step_of(item.status, tickets.through_pull(item, by_pulls(r.p))) if ticket else ""),
        "step_label": JOURNEY_WORDS.get(step, ""), "issue_state": item.issue_state if item.issue else "",
        "issue_state_label": ISSUE_WORDS.get(item.issue_state, "") if item.issue else ""}
    if full:
        out.update({"body": "" if veil else e.body[:TEXT_SHOWN], "link": "" if veil else e.link,
                    "journey": _journey_json(r.p, item) if ticket else None})
    return out


async def elements(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/elements`` : une page d'une de ses listes (``list`` ; par défaut ses tickets), les
    derniers touchés d'abord. Une recherche ne compare que ce qu'elle peut lire."""
    sc, r = opened_project(call)
    lst = _listing(r, call.arg("list", limit=40))
    state, status = call.arg("state", limit=10), call.arg("status", limit=tracker.STATUS_MAX)
    if state not in ("", "open", "closed"):
        raise Denied(400, "« state » : open, closed, ou rien.", {"state": "open, closed, ou rien"})
    if status and status not in (*lst.open, *lst.closed):
        raise Denied(400, "Ce n'est pas un statut de cette liste.", {"status": tracker.statuses_said(lst)})
    statuses = (status,) if status else lst.open if state == "open" else lst.closed if state == "closed" else ()
    page, size = _paged(call)
    query = {"statuses": statuses, "search": call.arg("q", limit=120), "reader": r.reader}
    found = tracker.page(store_of(call), r.p.id, lst.name, limit=size, offset=(page - 1) * size, **query)
    titles = writing_projects(sc, (e.item.author for e in found))
    return {"list": lst.name, "total": tracker.total(store_of(call), r.p.id, lst.name, **query), "page": page,
            "size": size, "items": [_entry_json(sc, r, e, titles) for e in found]}


def found_element(sc: Scene, r: Reach, *, readable: bool = True) -> tuple[Listing, tracker.Entry]:
    """L'élément que nomme la requête (``list``, ``item`` : un ticket par ``#n``, un élément par sa clé) ;
    ``readable`` : un élément qu'elle ne peut pas lire se refuse (403)."""
    call = sc.call
    lst = _listing(r, call.arg("list", limit=40))
    e = tracker.find(store_of(call), r.p.id, lst.name, call.arg("item", limit=tracker.KEY_MAX + 1))
    if e is None:
        raise missing()
    if readable and tracker.veiled(r.reader, e.item):
        raise Denied(403, UNREADABLE)
    return lst, e


async def element(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/element`` : un élément, son fil, et pour un ticket son plan et ce qu'elle peut en faire.
    Un élément qu'elle ne peut pas lire ne rend que ses faits."""
    sc, r = opened_project(call)
    lst, e = found_element(sc, r, readable=False)
    item = e.item
    veil = tracker.veiled(r.reader, item)
    notes = [] if veil else tracker.thread(store_of(call), r.p.id, lst.name, item.key)
    titles = writing_projects(sc, (item.author, *(n.author for n in notes)))
    out = _entry_json(sc, r, e, titles, full=True)
    level = written_on(r.p, item)
    out["thread"] = [{"seq": n.seq, "at": millis(n.at), **author_fields(sc, titles, n.author, n.by, level),
                      "kind": n.kind, "kind_label": NOTE_WORDS.get(n.kind, n.kind), "text": n.text[:TEXT_SHOWN],
                      "outside": c.from_outside(n.author)} for n in notes]
    ticket = lst.name == c.TICKETS
    plan = tracker.note_text(store_of(call), item.plan_seq) if ticket and item.plan_seq and not veil else ""
    out["plan_text"] = plan[:TEXT_SHOWN]
    out["small"] = item.small
    # ce qui lui est lié (ADR 0293) : l'objectif qui le tient, et sa pull request avec son titre et son état
    held = objective_at(r.p, item.objective) if ticket and item.objective else None
    if held is not None:
        texts = texts_of(call, [] if veil else [held.text_ref, held.pull_said_ref, held.checks_said_ref])
        shown = _objective_json(r.p, held, texts)
        out["linked"] = {"objective": {"id": held.id, "text": shown["text"], "status": held.status,
                                       "status_label": shown["status_label"]},
                         "pull": shown["pull"], "checks": shown["checks"]}
    else:
        out["linked"] = {"objective": None, "pull": None, "checks": None}
    stage, live_ticket = item.status, ticket and not veil
    out["can"] = {
        "note": r.steer in CHANGES and not veil,
        "status": r.steer == STEER_EDIT and not ticket and not veil,
        "assign": r.steer == STEER_EDIT and not ticket and not veil,
        "accept": live_ticket and r.settles and stage == c.STAGE_PROPOSED,
        "dismiss": live_ticket and r.settles and stage in c.STAGES_OPEN,
        "dismiss_needs_reason": not item.dismissal_at,
        "validate": live_ticket and r.settles and stage == c.STAGE_VALIDATION,
        "refuse": live_ticket and r.settles and stage == c.STAGE_VALIDATION,
        # ADR 0290 : le modifier (qui pilote en modification), le fermer comme traité, le rouvrir (qui tranche)
        "modify": live_ticket and r.steer == STEER_EDIT,
        "close": live_ticket and r.settles and stage in c.STAGES_OPEN and stage != c.STAGE_PROPOSED,
        "reopen": live_ticket and r.settles and stage in c.STAGES_CLOSED}
    out["statuses"] = [] if ticket else _statuses(lst.name, (*lst.open, *lst.closed))
    return out


#: les événements d'un ticket relus pour son histoire, au plus
HISTORY_READ = 2000


async def history(call: Call) -> dict[str, Any]:
    """``GET …/projets/<id>/element/historique`` : l'histoire des étapes d'un ticket — quand il est passé par
    chacune, par qui —, rejouée de son journal par les règles de l'état (``tracker.passages``). Des faits, aucun
    texte : un ticket qu'elle ne peut pas lire la rend aussi, sans un nom."""
    sc, r = opened_project(call)
    call.data.setdefault("list", c.TICKETS)
    lst, e = found_element(sc, r, readable=False)
    if lst.name != c.TICKETS:
        raise Denied(400, "Seul un ticket a un parcours.", {"list": "tickets"})
    item, mind = e.item, call.kernel.mind
    raw = mind.store.latest([t.name for t in tracker.MOVES], HISTORY_READ, where=("key", item.key))
    events = [d for d in (mind.decode(x) for x in reversed(raw))
              if d.data.project == r.p.id and d.data.list_name == c.TICKETS]
    veil = bool(tracker.veiled(r.reader, item))
    found = tracker.passages(events)
    titles = writing_projects(sc, (x.author for x in found))
    level, flow = written_on(r.p, item), by_pulls(r.p)
    return {"item": tracker.handle(item), "cut": len(raw) >= HISTORY_READ,
            "items": [{"seq": x.seq, "at": millis(x.at), "status": x.stage,
                       "status_label": tracker.status_words(c.TICKETS, x.stage), "was": x.was,
                       "was_label": tracker.status_words(c.TICKETS, x.was) if x.was else "",
                       "step": (step := tickets.step_of(x.stage, flow)), "step_label": JOURNEY_WORDS.get(step, ""),
                       **author_fields(sc, titles, x.author, x.by, level, veiled=veil),
                       "outside": c.from_outside(x.author)} for x in found]}


# ── Ses gestes ────────────────────────────────────────────────────────────


def subject_key(r: Reach) -> str:
    return str(r.p.id)


async def answer_plan(call: Call) -> dict[str, Any]:
    """``POST …/plan`` : valider son plan, ou lui demander de le reprendre (``project_steer``, approve / revise)."""
    sc, r = opened_project(call)
    must_steer(r)
    if not answers_plan(sc, r):
        raise Denied(403, NOT_PLAN_ASKER)
    verdict = call.arg("verdict", limit=20)
    if verdict == "approve":
        return done(await call.act("projects.plan_valider", form(), subject=subject_key(r)))
    if verdict != "revise":
        raise Denied(400, "« verdict » : approve ou revise.", {"verdict": "approve ou revise"})
    return done(await call.act("projects.plan_reviser", form(words=call.arg("words", limit=2000)), subject=subject_key(r)))


async def open_ticket(call: Call) -> dict[str, Any]:
    """``POST …/ticket`` : ouvrir un ticket. Qui ne pilote que sur accord le voit naître « proposé »."""
    sc, r = opened_project(call)
    must_steer(r)
    proposed = r.steer == STEER_ASK
    title = call.arg("title", limit=tracker.TITLE_MAX)
    got = await call.act("projects.ticket_ouvrir", form(
        fixed={"born": BORN_PROPOSED} if proposed else None, title=title,
        text=call.arg("text", limit=tracker.TEXT_MAX), kind=call.arg("kind", c.TASK, limit=20),
        priority=call.arg("priority", c.NORMAL, limit=20)), subject=subject_key(r))
    out = done(got)
    e = tracker.entry(store_of(call), r.p.id, c.TICKETS, tracker.key_of("", title))
    return {**out, "number": e.item.number if e is not None else 0, "proposed": proposed}


async def note(call: Call) -> dict[str, Any]:
    """``POST …/element/noter`` : une note dans le fil d'un élément — ce qui répond à sa question."""
    sc, r = opened_project(call)
    must_steer(r)
    lst, e = found_element(sc, r)
    return done(await call.act("projects.element_noter", form(
        fixed={"list_name": lst.name, "item": tracker.handle(e.item)}, text=call.arg("text", limit=tracker.NOTE_MAX)),
        subject=subject_key(r)))


async def set_status(call: Call) -> dict[str, Any]:
    """``POST …/element/statut`` : le statut d'un élément d'une liste de suivi — en modification seulement."""
    sc, r = opened_project(call)
    must_steer(r, edit=True)
    lst, e = found_element(sc, r)
    return done(await call.act("projects.element_statut", form(
        fixed={"list_name": lst.name, "item": tracker.handle(e.item)},
        status=call.arg("status", limit=tracker.STATUS_MAX), note=call.arg("note", limit=tracker.NOTE_MAX)),
        subject=subject_key(r)))


async def add_item(call: Call) -> dict[str, Any]:
    """``POST …/element/ajouter`` : un élément de plus dans une liste de suivi (pas un ticket : il s'ouvre par
    ``…/ticket``) — en modification seulement, comme changer un statut."""
    sc, r = opened_project(call)
    must_steer(r, edit=True)
    lst = _listing(r, call.arg("list", limit=40))
    title = call.arg("title", limit=tracker.TITLE_MAX)
    key = call.arg("key", limit=tracker.KEY_MAX)
    got = done(await call.act("projects.element_ajouter", form(
        list_name=lst.name, title=title, key=key, text=call.arg("text", limit=tracker.TEXT_MAX),
        status=call.arg("status", limit=tracker.STATUS_MAX), actor=call.arg("actor", limit=10),
        link=call.arg("link", limit=tracker.LINK_MAX)), subject=subject_key(r)))
    return {**got, "list": lst.name, "key": tracker.key_of(key, title)}


async def assign_item(call: Call) -> dict[str, Any]:
    """``POST …/element/confier`` : à qui est un élément d'une liste de suivi — à elle (``self``), ou au
    propriétaire du projet (``owner``). En modification seulement ; la main sur un ticket se déduit de son étape."""
    sc, r = opened_project(call)
    must_steer(r, edit=True)
    lst, e = found_element(sc, r)
    return done(await call.act("projects.element_confier", form(
        fixed={"list_name": lst.name, "item": tracker.handle(e.item)}, actor=call.arg("actor", limit=10)),
        subject=subject_key(r)))


#: ce qu'on tranche d'un ticket ici — ce que ``project_item`` laisse trancher en conversation, et depuis l'ADR 0290
#: le fermer comme traité (``done``) et le rouvrir (``reopen``), que l'action de la console faisait seule
VERDICTS = ("accept", "dismiss", "validate", "refuse", "done", "reopen")


async def settle_ticket(call: Call) -> dict[str, Any]:
    """``POST …/ticket/trancher`` : accepter un ticket proposé, l'écarter (ou confirmer qu'elle l'écarte), valider
    son plan — en nommant le plan lu (ADR 0272) — ou le refuser. Le propriétaire du projet, ou qui s'occupe d'elle."""
    sc, r = opened_project(call)
    must_steer(r)
    if not r.reader.settles:
        raise Denied(403, NOT_SETTLER)
    verdict = call.arg("verdict", limit=20)
    if verdict not in VERDICTS:
        raise Denied(400, "« verdict » : accept, dismiss, validate, refuse, done ou reopen.",
                     {"verdict": ", ".join(VERDICTS)})
    call.data.setdefault("list", c.TICKETS)
    lst, e = found_element(sc, r)
    if lst.name != c.TICKETS:
        raise Denied(400, "Seul un ticket se tranche.", {"list": "tickets"})
    plan = call.number("plan", 0, 0)
    if verdict == "validate":
        if not plan:
            raise Denied(400, "Nomme le plan que tu as lu : « plan », son numéro.", {"plan": "valeur requise"})
        if e.item.plan_seq and plan != e.item.plan_seq:  # dit d'avance : l'action le revérifie au moment d'écrire
            raise Denied(409, PLAN_MOVED.format(number=e.item.number))
    return done(await call.act("projects.ticket_trancher", form(
        fixed={"item": tracker.handle(e.item), "plan": str(plan)}, verdict=verdict,
        reason=call.arg("reason", limit=tracker.NOTE_MAX)), subject=subject_key(r)))


async def settle_milestone(call: Call) -> dict[str, Any]:
    """``POST …/jalon`` : valider ou refuser, avec sa raison, un point d'arrêt qu'elle a dit prêt."""
    sc, r = opened_project(call)
    must_steer(r)
    if not r.reader.settles:
        raise Denied(403, NOT_SETTLER)
    verdict = call.arg("verdict", limit=20)
    if verdict not in ("validate", "refuse"):
        raise Denied(400, "« verdict » : validate ou refuse.", {"verdict": "validate ou refuse"})
    return done(await call.act("projects.jalon_trancher", form(
        fixed={"objective": str(call.number("objective", 0, 0)), "milestone": str(call.number("milestone", 0, 0))},
        verdict=verdict, reason=call.arg("reason", limit=1000)), subject=subject_key(r)))


#: ce qu'on demande à un projet qu'on pilote (``project_steer``) : une consigne, s'y mettre, la pause, la reprise
PILOT = {"instruct": "projects.consigne", "now": "projects.lancer", "pause": "projects.pause",
         "resume": "projects.reprendre"}


async def pilot(call: Call) -> dict[str, Any]:
    """``POST …/piloter`` : une consigne, « vas-y maintenant », la pause, la reprise — pour qui le pilote en
    modification. Sur accord, la demande se fait dans le chat : elle la propose à qui s'occupe d'elle."""
    sc, r = opened_project(call)
    must_steer(r, edit=True)
    what = call.arg("what", limit=20)
    if what not in PILOT:
        raise Denied(400, "« what » : instruct, now, pause ou resume.", {"what": ", ".join(PILOT)})
    objective = call.number("objective", 0, 0)
    if what == "instruct":
        values = form(instruction=call.arg("text", limit=2000))
    elif what == "now" and objective:
        if objective_at(r.p, objective) is None:
            raise missing()
        return done(await call.act("projects.lancer_objectif", form(fixed={"objective": str(objective)}),
                                   subject=subject_key(r)))
    else:
        values = form()
    return done(await call.act(PILOT[what], values, subject=subject_key(r)))


#: ce qu'un envoi de liens nomme : les projets à se mettre à lire, ceux à ne plus lire, et parmi ceux qu'il lit, ceux
#: où ses demandes entrent désormais directement, ou plus
LINK_FIELDS = ("add", "remove", "direct_on", "direct_off")
#: l'ancienne forme (toute la liste) : refusée en mots, jamais lue comme « rien à changer »
LINK_FIELDS_BEFORE = ("reads", "direct")
LINKS_WHOLE = ("« reads » et « direct » ne s'envoient plus : nomme ce qui change — « add », « remove », "
               "« direct_on », « direct_off ».")
LINKS_EMPTY = "Dis ce qui change : « add », « remove », « direct_on », « direct_off », ou « why » (le mot d'un lien)."
LINKS_BOTH = "Un même projet ne peut pas être à la fois ajouté et retiré : {projects}."
LINKS_REFUSED = "Ce projet ne peut pas lire : {projects}."
LINKS_SAVED = "Ce qu'il lit est enregistré : sa prochaine exécution l'aura sous les yeux."


def _ids(call: Call, name: str) -> list[int]:
    raw = call.data.get(name, [])
    if not isinstance(raw, list) or len(raw) > LINKS_SENT or \
            not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in raw):
        raise Denied(400, f"« {name} » : une liste de numéros de projets ({LINKS_SENT} au plus).",
                     {name: "une liste de numéros de projets"})
    return list(dict.fromkeys(raw))


async def set_links(call: Call) -> dict[str, Any]:
    """``POST …/liens`` : ce qui change dans ce que ce projet lit — des projets à se mettre à lire (``add``), à ne
    plus lire (``remove``), et pour ceux qu'il lit, que ses demandes y entrent directement (``direct_on``) ou plus
    (``direct_off``). Son propriétaire seulement. Elle ne nomme que des projets qu'elle voit : **un lien vers un projet
    qu'elle ne voit pas reste tel quel**, et le nommer se refuse comme un projet inconnu — la même réponse, qu'il le
    lise ou non. Les règles (qui peut être lu, la boucle, la borne, le mode direct) restent celles de ``links`` et de
    l'action de console."""
    sc, r = opened_project(call)
    p = r.p
    if not links.may_link(p, sc.person, sc.world):
        raise Denied(403, NOT_LINKER)
    if any(name in call.data for name in LINK_FIELDS_BEFORE):
        raise Denied(400, LINKS_WHOLE, {name: "remplacé" for name in LINK_FIELDS_BEFORE if name in call.data})
    add, remove, on, off = (_ids(call, name) for name in LINK_FIELDS)
    # le mot de son propriétaire sur un lien (ADR 0293) : pourquoi ce projet lit celui-là (``why_for`` ; sans lui,
    # le seul projet ajouté)
    why = " ".join(call.arg("why", limit=actions.LINK_WHY_MAX).split())
    why_for = call.number("why_for", 0, 0) or (add[0] if why and len(add) == 1 else 0)
    if not (add or remove or on or off or why):
        raise Denied(400, LINKS_EMPTY)
    both = [t for t in add if t in remove] + [t for t in on if t in off]
    if both:
        raise Denied(400, LINKS_BOTH.format(projects=actions.numbered(dict.fromkeys(both))))
    mine = reaches(sc)
    offered = {t.id for t in links.candidates(sc.s, p, sc.world)}
    sent = dict(zip(LINK_FIELDS, (add, remove, on, off), strict=True))
    # inconnu, pas partagé, en boucle, ou pas à elle de le nommer (elle ne le voit pas) : une seule réponse
    refused = {t for ids in sent.values() for t in ids if t not in mine}
    refused |= {t for t in add if t not in p.reads and t not in offered}
    if refused:
        raise Denied(400, LINKS_REFUSED.format(projects=actions.numbered(sorted(refused))),
                     {name: "projet refusé" for name, ids in sent.items() if refused.intersection(ids)})
    reads = (set(p.reads) | set(add)) - set(remove)
    if why and (why_for not in mine or why_for not in reads):  # un projet qu'elle ne voit pas : la même réponse
        raise Denied(400, WHY_UNREAD, {"why_for": "projet non lu"})
    unread = [t for t in on if t not in p.reads or t not in reads]  # le mode direct se règle sur un lien déjà posé
    if unread:
        raise Denied(400, NOT_READ_YET.format(projects=actions.numbered(unread)), {"direct_on": "projet non lu"})
    direct = (set(p.direct) | set(on)) - set(off)
    # l'action de console prend tout l'état : celui de maintenant, où seuls les liens nommés bougent
    knobs = {actions.link_knob(t.id): t.id in reads for t, _ in actions.link_options(sc.s, sc.frame, p)}
    knobs.update({actions.direct_knob(t): t in direct for t in p.reads})
    said = {"why": why, "why_for": str(why_for)} if why else None
    got = done(await call.act("projects.liens", form(fixed=said, **knobs), subject=subject_key(r)))
    # ses mots à elle : ceux de l'action nomment par leur numéro tous les projets lus, même ceux qu'elle ne voit pas
    return {**got, "message": LINKS_SAVED}


# ── Les accords ───────────────────────────────────────────────────────────


def _pending(sc: Scene, r: Reach) -> list[Any]:
    return [v for v in todo.pending_in(sc.frame) if project_of(v.context) == r.p.id]


def _number(raw: Any) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else 0


def _concerns(sc: Scene, r: Reach, v: Any, pending: Any) -> dict[str, Any]:
    """Ce qu'un accord en attente concerne, et où cela part (ADR 0293) : lu dans les numéros que porte la
    proposition (un ticket, un objectif) et dans l'état — le ticket et son issue, l'objectif et sa pull request,
    leur page chez l'hôte composée ici. Qui l'a demandé, quand c'est une personne ; ``why`` : ses mots à elle, quand
    le moteur les garde à part (une demande de pilotage) — ailleurs la raison est dans le résumé."""
    p = r.p
    args = rt.proposal_args(pending.args_json) if pending is not None else {}
    page = repo_page(p)
    item, o, where, url, why = None, None, WHERE_ELSEWHERE, "", ""
    asked = author_fields(sc, {}, c.BY_SELF, "", written(p))
    if v.capability in ISSUE_CAPABILITIES:
        number = _number(args.get("ticket"))
        item = board_ticket(p, number)
        where = WHERE_ISSUES
        url = issues.issue_page(p, item.issue) if page and item is not None and item.issue else \
            f"{page}/issues" if page else ""
        move = next((m for m in p.issue_moves if m.proposal == v.proposal), None)
        if move is not None and move.author and move.author != c.BY_SELF:
            asked = author_fields(sc, {}, move.author, move.by, written(p))
    elif v.capability == PULL_REQUEST_CAPABILITY:
        o = objective_at(p, _number(args.get("objective")))
        item = ticket_held(p, o)
        where, url = WHERE_PULL, (pulls.pull_url(p, o) if o is not None else "") or (f"{page}/pulls" if page else "")
    elif v.capability == NETWORKED_CAPABILITY:
        where = WHERE_NETWORK
    elif v.capability == STEER_CAPABILITY:
        ask = sc.s.steers.get(sc.s.steer_proposals.get(v.proposal, ""))
        where = WHERE_PROJECT
        if ask is not None:
            o = objective_at(p, ask.objective) if ask.objective else None
            asked = author_fields(sc, {}, c.BY_PERSON, ask.by, written(p))
            why = texts_of(sc.call, [ask.text_ref]).get(ask.text_ref, "")[:TEXT_SHOWN]
    elif v.capability.startswith(f"{c.OWNER}."):
        where, url = WHERE_REMOTE, page
    texts = texts_of(sc.call, [item.title_ref] if item is not None else [])
    return {"concerns": {"objective": o.id if o is not None else 0,
                         "ticket": _ticket_brief(r, item, texts) if item is not None else None,
                         "issue": item.issue if item is not None else 0,
                         "pull": o.pull if o is not None else 0},
            "where": where, "where_url": url, "why": why,
            "asked_by_kind": asked["author_kind"], "asked_by": asked["author"]}


async def approvals(call: Call) -> dict[str, Any]:
    """``GET …/projets/accords`` : ce qui attend son accord dans ses projets, chacun avec exactement ce qui
    partirait et son condensé (``digest``), à renvoyer pour l'accepter tel qu'elle l'a lu."""
    sc = scene(call)
    mine = reaches(sc)
    only = call.number("project", 0, 0)
    effects = sc.frame.state("runtime").effects
    waiting = [(v, mine[pid]) for v in todo.pending_in(sc.frame)
               if (pid := project_of(v.context)) in mine and (not only or pid == only)]
    waiting = [(v, r) for v, r in waiting if decides(sc, r, v.proposal)][:APPROVALS_SHOWN]
    texts = texts_of(call, [ref for v, r in waiting for ref in (v.summary_ref, r.p.title_ref)])
    items = []
    for v, r in waiting:
        pending = effects.get(v.proposal)
        shown = await decisions.preview(call.kernel.mind, call.kernel.ports, pending.capability, pending.args_json) \
            if pending is not None else None
        summary = texts.get(v.summary_ref, "")
        items.append({"id": v.proposal, "project": r.p.id, "project_title": texts.get(r.p.title_ref, ""),
                      "capability": v.capability,
                      "label": inspect_todo.CAPABILITY_WORDS.get(v.capability, inspect_todo.OTHER_CAPABILITY),
                      "summary": summary[:400], "text": (shown.text if shown is not None else summary)[:TEXT_SHOWN],
                      "digest": shown.digest if shown is not None else "",
                      "blocked": shown.blocked if shown is not None else "", "at": millis(v.at),
                      **_concerns(sc, r, v, pending)})
    return {"items": items}


async def approve(call: Call) -> dict[str, Any]:
    """``POST …/accord`` : accepter ou refuser ce qui attend un accord dans ce projet, sur le condensé de ce qu'elle
    a lu (``seen``) : ce qui partirait a changé depuis, rien ne part (409)."""
    sc, r = opened_project(call)
    proposal = call.number("proposal", 0, 0)
    if not any(v.proposal == proposal for v in _pending(sc, r)):
        raise missing()
    if not decides(sc, r, proposal):
        raise Denied(403, NOT_DECIDER)
    decision = call.arg("decision", limit=20)
    if decision not in ("accept", "refuse"):
        raise Denied(400, "« decision » : accept ou refuse.", {"decision": "accept ou refuse"})
    seen = call.arg("seen", limit=100)
    if decision == "accept" and not seen:
        raise Denied(400, SEEN_NEEDED, {"seen": "valeur requise"})
    note_said = call.arg("note", limit=500)

    async def decide() -> dict[str, Any]:
        got = await decisions.decide(call.kernel.mind, call.kernel.ports, proposal, decision == "accept",
                                     by=call.me.handle, note=note_said, seen=seen)
        if got.status == decisions.UNKNOWN:
            raise missing()
        if got.status in (decisions.CHANGED, decisions.BLOCKED):
            raise Denied(409, got.message)
        await audit(call.kernel, "moi.projet_accord", by=call.me.handle, subject_kind="project", subject=subject_key(r))
        return {"ok": True, "status": got.status, "deduped": False,
                "message": "Accord donné." if got.status == decisions.APPROVED else "Refusé : rien ne partira."}

    return await call.once(decide)


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    one = PATH + "/{project:int}"
    return [r(PATH, overview), r(PATH + "/a-faire", to_do), r(PATH + "/accords", approvals),
            r(one, fiche), r(one + "/elements", elements), r(one + "/element", element),
            r(one + "/element/historique", history), r(one + "/element/ajouter", add_item, write=True),
            r(one + "/element/confier", assign_item, write=True),
            r(one + "/plan", answer_plan, write=True), r(one + "/ticket", open_ticket, write=True),
            r(one + "/ticket/trancher", settle_ticket, write=True), r(one + "/element/noter", note, write=True),
            r(one + "/element/statut", set_status, write=True), r(one + "/jalon", settle_milestone, write=True),
            r(one + "/piloter", pilot, write=True), r(one + "/liens", set_links, write=True),
            r(one + "/accord", approve, write=True)]
