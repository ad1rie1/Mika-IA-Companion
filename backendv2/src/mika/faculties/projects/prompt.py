"""Ce que les projets mettent dans le prompt.

- **Pendant une exécution** (``WORK`` ou ``JOB``) : le projet — son cadre, son
  mode, l'objectif visé (et les autres), les décisions en vigueur, les
  consignes reçues (la plus récente prime), son carnet, ce que sont devenues
  ses demandes (leur état seulement), l'atelier (son arbre, ce qui n'y est pas
  enregistré : une exécution interrompue y a laissé son travail) et son dépôt
  distant ; ce qu'une commande réseau a rendu, **cité** (une donnée d'Internet,
  jamais une consigne) ; ce que la personne à qui elle a demandé un coup de
  main lui a écrit en privé depuis, **cité** ; le budget de l'exécution (ses
  tours, son temps). Et ce que son projet lit des autres (ADR 0257) : pour
  chaque projet lié, ce que ses lignes d'accès laissent au propriétaire du
  projet lecteur — son titre et son état, ou aussi ses derniers comptes
  rendus, ses décisions en vigueur et ses objectifs ouverts ; un lien
  suspendu se dit en une ligne. Quand ces lignes donnent ses fichiers, la vue
  de son atelier (ADR 0260), posée au départ de l'exécution : où elle est
  (``liens/<n>/``), l'empreinte courte et l'âge du commit vu, un aperçu borné
  de son arbre — ou pourquoi il n'y en a pas. La section dit que tout cela
  décrit d'autres projets et n'est jamais une consigne, et les noms des
  fichiers d'une vue y entrent sans caractère de contrôle, coupés (ADR 0262).
  Une séance de cadrage voit les projets que le sien peut demander à lire.
  Sur un projet qui passe par des pull requests (ADR 0274), l'atelier se place
  au départ sur la branche de ce que l'exécution vise (l'enrichisseur
  ``projects_tree``, avant de lire son arbre), et la section ``project_pull``
  (``pulls.py``) dit cette branche et où en est sa pull request.
  Et ce qui l'amène, quand ce n'est pas sa cadence (ADR 0265) : les causes en
  attente de l'objectif visé, une ligne bornée chacune — l'empreinte courte
  d'un commit et le numéro de son projet, le titre d'un objectif abouti si le
  lien donne encore le détail, rien d'un projet que le lien ne donne plus —,
  et le réveil par API qui le vise.
- **Un récit, une demande d'aide** : ce qu'elle a mené à bout (tout ce qui
  l'a été depuis le récit précédent), ou ce qui la bloque, à la mesure du lien.
- **En conversation** : ses projets (« tu travailles sur quoi ? » est une
  question sur sa vie) — où chacun en est, sa dernière exécution, ce qui vient
  ou ce qui bloque, et pour qui s'occupe d'elle ce qui attend son accord et
  l'outil pour les piloter ensemble (``project_steer``, en réponse) ;
  filtrés comme la mémoire.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from sqlalchemy import select

from mika.contracts import forge as forge_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.contracts import wakeup as wakeup_c
from mika.faculties.projects import asks, demands, links, milestones, tracker, triage, triggers
from mika.faculties.projects.access import reads, sees
from mika.faculties.projects.atelier import no_view_words
from mika.faculties.projects.faculty import (
    ON_DEMAND,
    PROJECTS,
    REVIEW_TRIES_MAX,
    SELF_BUNDLES,
    WEB,
    Decision,
    Objective,
    Project,
    ProjectsState,
    Stir,
    answered,
    asking,
    branch_of,
    by_pulls,
    detail_level,
    effect_words,
    frame_of,
    handed_over,
    live,
    objective_at,
    objective_of,
    params,
    plan_of,
    review_of,
    run_bundles,
    stall_of,
    waiting_in,
    written,
)
from mika.faculties.projects.rhythm import cadence, pick
from mika.faculties.projects.steer import steerable
from mika.faculties.projects.tools import RUNS, caretaker, triggers_said
from mika.faculties.projects.work import unplanned_stall, untold
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.text import clipped
from mika.ports.errors import describe_error
from mika.ports.workshop import UNREADABLE, view_entry, view_place
from mika.vocab.days import ago_words
from mika.vocab.episodes import CONVERSATIONAL, Kind, project_of
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import hearable

SHOWN = 4
INSTRUCTIONS_SHOWN = 3
#: les décisions en vigueur montrées pendant une exécution (les plus récentes)
DECISIONS_SHOWN = 12
TREE_SHOWN = 60
PENDING_SHOWN = 20
#: les objectifs qu'un récit nomme (les plus récents) ; ceux d'avant sont comptés
TOLD_SHOWN = 8
#: ce qu'une demande d'aide cite de chacun des avis des relectures qui ont rendu la main (ADR 0276)
REVIEW_CLIP = 1200
#: les points d'arrêt d'un projet qu'une conversation montre à qui les tranche, et ce qu'elle en cite (ADR 0273)
BREAKPOINTS_SHOWN, BREAKPOINT_CLIP = 2, 300


def episode_project(s: ProjectsState, frame: Frame) -> tuple[Project, Objective | None] | None:
    ep = frame.episode
    if ep is None:
        return None
    if review_of(ep.attrs.get("subject")) is not None:
        # une relecture indépendante (ADR 0276) ne lit rien de ce qu'une exécution lit de son projet — ni comptes
        # rendus, ni carnet, ni consignes, ni mémoire de travail : ses seules sections sont dans ``review.py``
        return None
    pid = project_of(ep.target)
    got = objective_of(ep.attrs.get("subject"))
    if pid is None and got is not None:
        pid = got[0]
    if pid is None:
        pid = stall_of(ep.attrs.get("subject"))
    if pid is None:
        pid = plan_of(ep.attrs.get("subject"))
    p = s.projects.get(pid) if pid is not None else None
    if p is None:
        return None
    o = next((x for x in p.objectives if got is not None and got[0] == p.id and x.id == got[1]), None)
    return p, o


def _refs(p: Project, target: Objective | None = None) -> list[str]:
    """Les textes qu'une exécution lit de son projet ; de l'objectif qu'elle vise, sa mémoire à lui en plus (ADR
    0253)."""
    objectives = [r for o in p.objectives for r in (o.text_ref, o.note_ref, o.result_ref, o.need_ref, o.done_when_ref,
                                                     o.pass_ref, o.brief_ref)]
    # sa mémoire à lui, ses jalons et leurs preuves, ou sa liste de passage (ADR 0273)
    # … et ce que l'hôte dit de sa pull request, quand elle lui est revenue (ADR 0274)
    # … et les constats de la relecture qui l'a rouvert (ADR 0276)
    own = [*(ref for *_, ref in target.reports), *target.notes, *milestones.refs(target), target.pull_said_ref,
           target.checks_said_ref, target.review_ref] \
        if target is not None else []
    decisions = [r for d in p.decisions for r in (d.title_ref, d.choice_ref, d.reason_ref, d.context_ref)]
    deposits = [note for _, _, note in p.deposits]
    refusals = [note for _, note in p.refusals]
    reports = [ref for *_, ref in p.reports]
    said = [words for _, words in p.said]
    return [r for r in (p.title_ref, p.description_ref, p.summary_ref, p.request_ref, p.plan_ref, p.questions_ref,
                        p.plan_answer_ref, *p.notes, *p.instructions, *said, *objectives, *decisions, *deposits, *refusals, *reports,
                        *own)
            if r]


def _talk_refs(p: Project) -> list[str]:
    """Ce qu'une conversation peut dire d'un projet : son titre, son dernier compte rendu, ce qui vient — et son plan
    tant qu'il attend une réponse (ADR 0145)."""
    opened = [o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED)][:3]
    plan = (p.plan_ref, p.questions_ref) if p.plan_state == c.PROPOSED else ()
    # ses points d'arrêt qui attendent le propriétaire : le jalon, et comment elle dit l'avoir rempli (ADR 0273)
    held = [r for _, m in waiting_in(p)[:BREAKPOINTS_SHOWN] for r in (m.text_ref, m.how_ref)]
    # les avis des relectures qui lui ont rendu la main (ADR 0276)
    reviews = [r for o in opened if handed_over(o) for r in o.review_refused]
    return [r for r in (p.title_ref, p.summary_ref, *plan, *(o.text_ref for o in opened),
                        *(o.need_ref for o in opened), *held, *reviews) if r]


#: ce qu'une exécution lit d'un projet que le sien lit (ADR 0257) : ses derniers comptes rendus, chacun coupé ; ses
#: décisions en vigueur et ses objectifs ouverts, au plus tant de chaque, la ligne coupée ; en séance de cadrage, les
#: projets qu'il peut demander à lire, au plus tant
LINK_REPORTS, LINK_REPORT_CLIP = 2, 500
LINK_LISTED, LINK_LINE_CLIP = 5, 240
READABLE_SHOWN = 12


def _read_reports(t: Project) -> tuple[tuple[int, int, str, str], ...]:
    return t.reports[-LINK_REPORTS:]


def _read_decisions(t: Project) -> list[Decision]:
    return [d for d in t.decisions if d.status == c.IN_FORCE][-LINK_LISTED:]


def _read_objectives(t: Project) -> list[Objective]:
    return [o for o in t.objectives if o.status in (c.OPEN, c.BLOCKED)][:LINK_LISTED]


def _link_refs(s: ProjectsState, frame: Frame, p: Project) -> list[str]:
    """Les textes qu'une exécution lit des projets que le sien lit (ADR 0257) — ce que chaque lien donne, pas plus :
    le titre de ce qu'il voit, le détail de ce qu'il peut lire. Tant que son plan se prépare ou attend, le titre
    des projets qu'il peut demander à lire."""
    world = links.world_of(frame)
    refs: list[str] = []
    for r in links.readings(s, p, world):
        t = r.project
        if t is None or r.suspended:
            continue
        refs.append(t.title_ref)
        if r.grant.detail:
            refs += [ref for *_, ref in _read_reports(t)]
            refs += [ref for d in _read_decisions(t) for ref in (d.title_ref, d.choice_ref, d.reason_ref)]
            refs += [o.text_ref for o in _read_objectives(t)]
    if p.plan_state in (c.TO_FRAME, c.PROPOSED):
        refs += [t.title_ref for t in links.askable(s, p, world)[:READABLE_SHOWN]]
    return [r for r in refs if r]


@PROJECTS.enricher("projects", episodes=[*RUNS, *CONVERSATIONAL], deadline_ms=1500,
                   reads=[identity_c.PERSON, identity_c.IS_OWNER])
async def _texts(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    if store is None:
        return None
    ep = frame.episode
    chosen: list[Project] = []
    got = episode_project(s, frame)
    if got is not None:
        chosen.append(got[0])
    if ep is not None and ep.kind in CONVERSATIONAL:
        person = frame.get(identity_c.PERSON(ep.target)) if ep.target else None
        chosen += [p for p in _talked(s, person) if p not in chosen]
    refs = [r for p in chosen for r in (_refs(p, got[1]) if got is not None and p is got[0] else _talk_refs(p))]
    if got is not None:  # ce que son projet lit des autres, et ce que son plan demande à lire (ADR 0257)
        refs += _link_refs(s, frame, got[0])
        refs += _stir_refs(s, frame, got[0], got[1])  # le titre des objectifs aboutis qui l'amènent (ADR 0265)
    return {"texts": store.content(refs) if refs else {}}


@PROJECTS.enricher("projects_tree", episodes=RUNS, deadline_ms=8000)
async def _tree(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """L'arbre de l'atelier et ce qui n'y est pas enregistré — à part : un atelier illisible (un lien cassé, un
    git qui ne répond pas) ne doit jamais rendre l'exécution aveugle à son projet.

    Sur un projet qui passe par des pull requests (ADR 0274), c'est ici, au départ de l'exécution et avant de lire
    l'arbre, que l'atelier se place sur la branche de ce qu'elle vise : créée depuis la base la première fois,
    retrouvée ensuite, un travail interrompu rangé sur la sienne. Une séance de cadrage n'écrit pas : elle ne déplace
    rien. Si l'atelier n'a pas pu s'y placer, le prompt le dit, et ``report_run`` n'enregistrera rien."""
    got = episode_project(s, frame)
    atelier = ports.get("workshop")
    if got is None or atelier is None or not atelier.exists(got[0].id):
        return None
    pid = got[0].id
    out: dict[str, Any] = {}
    ep = frame.episode
    if by_pulls(got[0]) and frame_of(ep.attrs.get("subject") if ep is not None else None) != pid:
        try:
            placed = await atelier.work_on(pid, branch_of(got[1]), stow=phrase("projects.commit.stowed"))
            out["branch"] = {"name": placed.branch, "created": placed.created, "base": placed.base,
                             "ahead": placed.ahead, "stowed": placed.stowed, "stowed_on": placed.stowed_on,
                             "why": placed.why}
        except (OSError, ValueError) as exc:
            out["branch"] = {"name": "", "why": str(exc)[:200]}
    try:
        out["tree"] = await atelier.tree(pid)
    except (OSError, ValueError) as exc:
        out["tree_error"] = str(exc)[:200]
    try:
        out["pending"] = await atelier.pending(pid)
    except (OSError, ValueError):
        out["pending"] = []
    return out


#: l'aperçu de l'arbre d'une vue : ses premières entrées, les plus proches de sa racine ; le reste se liste
VIEW_TREE_SHOWN = 30


@PROJECTS.enricher("projects_views", episodes=RUNS, deadline_ms=8000, reads=[identity_c.IS_OWNER])
async def _views(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Les vues des ateliers que son projet lit (ADR 0260), posées au départ de l'exécution — c'est ici que la tête
    de chaque projet lu est relue, et la vue reposée si elle a bougé : pour chaque projet dont les lignes d'accès lui
    donnent les fichiers, le commit vu, sa date et le début de son arbre, ou pourquoi il n'y a pas de vue. Une vue
    qu'il n'a plus le droit de lire est supprimée. À part des autres enrichisseurs : une vue lente à poser, ou un
    dépôt illisible, ne rend pas l'exécution aveugle à son projet."""
    got = episode_project(s, frame)
    atelier = ports.get("workshop")
    if got is None or atelier is None or not got[0].reads:
        return None
    p = got[0]
    granted = links.views(s, p, links.world_of(frame))
    await atelier.drop_views(p.id, keep=granted)

    async def seen(target: int) -> dict[str, Any]:
        try:
            view = await atelier.view(p.id, target, fresh=True)
            tree = await atelier.view_tree(p.id, target) if view.sha else []
        except (OSError, ValueError):
            return {"sha": "", "at": 0, "why": UNREADABLE, "tree": []}
        return {"sha": view.sha, "at": view.at, "why": view.why, "tree": tree[:VIEW_TREE_SHOWN + 1]}

    # Demandées ensemble (l'atelier n'en pose qu'une à la fois par lecteur) : chacune est dite périmée avant qu'une
    # pose lente ne prenne toute l'échéance. Coupée, aucune ne garde son commit d'avant, pas même celles dont le tour
    # n'est pas venu : ses outils la reposeront à la tête courante (ADR 0262).
    found = await asyncio.gather(*(seen(target) for target in granted))
    # par numéro de projet lu, en texte : ce que garde la trace de l'épisode
    return {"views": {str(target): view for target, view in zip(granted, found, strict=True)}}


@PROJECTS.enricher("projects_apps", episodes=RUNS, deadline_ms=1500, reads=[forge_c.APPS])
async def _app_problems(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce qui n'a pas marché pour ses apps hors de leurs appels — une vue invalide dans la console (ADR 0161) : la
    Forge le garde jusqu'à leur version suivante."""
    got = episode_project(s, frame)
    forge = ports.get("forge")
    problems = getattr(forge, "problems", None)
    if got is None or not callable(problems):
        return None
    mine = [a.name for a in frame.get(forge_c.APPS) or () if a.project == got[0].id]
    found = {name: list(seen) for name in mine if (seen := problems(name))}
    return {"problems": found} if found else None


#: ce qu'on cite de sa réponse : ses premiers messages privés depuis la demande, chacun coupé
ANSWER_LINES, ANSWER_CLIP = 10, 400


@PROJECTS.enricher("projects_answer", episodes=RUNS, deadline_ms=1500, reads=[identity_c.HANDLES])
async def _answer(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce que la personne à qui elle a demandé un coup de main lui a écrit depuis, en privé : ses messages à elle
    seule (pas un salon, pas le fil d'une autre), après la demande."""
    store = ports.get("store")
    got = episode_project(s, frame)
    o = got[1] if got is not None else None
    if store is None or o is None or not o.asked_to or not answered(o):
        return None
    handles = list(frame.get(identity_c.HANDLES(o.asked_to)) or (o.asked_to,))
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.text).where(t.c.person.in_(handles), t.c.role == "user", t.c.room.is_(None),
                                                   t.c.at > o.asked_at).order_by(t.c.id).limit(ANSWER_LINES))
    lines = [clipped(str(text), ANSWER_CLIP) for (text,) in rows if str(text or "").strip()]
    return {"lines": lines} if lines else None


#: « TON REGISTRE » (ADR 0268) tient en dix lignes : trois de comptes, puis ce qui a bougé et ses plus anciens
#: éléments ouverts, chacun sous son en-tête ; une ligne est coupée
ITEMS_LINES = 10
ITEMS_LISTS, ITEMS_MOVED, ITEMS_OLDEST = 3, 3, 2
ITEM_LINE_CLIP = 220


@PROJECTS.enricher("projects_items", episodes=RUNS, deadline_ms=1500,
                   reads=[identity_c.IDENTITY, identity_c.OWNERS])
async def _items(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Le registre du projet, pour l'exécution qui vise un objectif (ADR 0268) : ce qu'un autre qu'elle a touché
    depuis son dernier passage, et ses éléments ouverts les plus anciens — lus dans la projection, une ligne
    chacun ; les comptes, eux, sont dans l'état."""
    store = ports.get("store")
    got = episode_project(s, frame)
    if store is None or got is None or got[1] is None or not got[0].board.counts:
        return None
    p, target = got
    ep = frame.episode
    run = s.running.get(ep.id) if ep is not None else None
    # son dernier passage : celui d'avant cette exécution, qu'elle a déjà rendu sien à son départ
    since = run.previous_objective if run is not None and run.objective == target.id else target.last_run_at
    titles = [x.title_ref for x in p.board.lists if x.title_ref]
    moved = tracker.moved(store, p.id, since, ITEMS_MOVED)
    oldest = tracker.oldest_open(store, p.id, p.board, ITEMS_OLDEST)
    # un ticket encore proposé n'y dit qu'une ligne, sans titre ni texte (``tracker.RUN``, ADR 0272) ; le niveau de
    # la section est celui de ce qu'elle cite : un élément peut être d'un niveau plus haut que ce qu'écrit le projet
    return {"moved": [tracker.line(frame, e, tracker.RUN) for e in moved],
            "oldest": [tracker.line(frame, e, tracker.RUN) for e in oldest],
            "titles": store.content(titles) if titles else {},
            "level": max([0, *(e.item.level for e in (*moved, *oldest) if not tracker.veiled(tracker.RUN, e.item))])}


@PROJECTS.enricher("projects_asks", episodes=RUNS, deadline_ms=1500, reads=[identity_c.IS_OWNER])
async def _asks(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Les demandes de son projet aux projets qu'il lit (ADR 0271), pour l'exécution qui vise un objectif : où
    chacune en est, celles fermées depuis son dernier passage d'abord. Le titre d'un ticket et la note de sa
    fermeture se relisent dans la projection du projet visé, seulement tant que le lien donne encore son détail —
    c'est ici que ce droit est relu."""
    store = ports.get("store")
    got = episode_project(s, frame)
    if store is None or got is None or got[1] is None or not got[0].asks:
        return None
    p, target = got
    ep = frame.episode
    run = s.running.get(ep.id) if ep is not None else None
    # son dernier passage : celui d'avant cette exécution, qu'elle a déjà rendu sien à son départ
    since = run.previous_objective if run is not None and run.objective == target.id else target.last_run_at
    said, seen = demands.lines(s, frame, store, p, target, since, links.world_of(frame))
    return {"lines": said, "seen": list(seen)}


@PROJECTS.enricher("projects_tickets", episodes=RUNS, deadline_ms=1500,
                   reads=[identity_c.IDENTITY, identity_c.OWNERS])
async def _tickets(s: ProjectsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Les tickets du projet, pour l'exécution qu'ils regardent (ADR 0270), lus dans la projection : le passage qui
    traite les tickets (son objectif attend ``item:tickets``) voit ceux qui sont entre ses mains, par priorité ;
    l'exécution d'un objectif né d'un ticket voit le sien, et son plan."""
    store = ports.get("store")
    got = episode_project(s, frame)
    if store is None or got is None or got[1] is None:
        return None
    p, target = got
    if target.ticket:
        e = tracker.ticket(store, p.id, target.ticket)
        return {"own": True, "lines": triage.own_lines(frame, store, p, e), "level": e.item.level} \
            if e is not None else None
    if triggers.item_key(c.TICKETS) not in target.on or not tracker.open_tickets(p.board):
        return None
    lines, level = triage.triage_lines(frame, store, p)
    return {"own": False, "lines": lines, "level": level}


def _recent(s: ProjectsState) -> list[Project]:
    return sorted((p for p in s.projects.values() if live(p)), key=lambda p: p.id)


def _awaits(p: Project, person: str | None) -> bool:
    """Ce projet attend-il cette personne : son plan, qu'elle a demandé ; un besoin ou un blocage qu'elle lui a dit ?"""
    if not person:
        return False
    if p.plan_state == c.PROPOSED and person in (p.asked_by, p.plan_asked_to):
        return True
    if person == p.owner and waiting_in(p):  # un point d'arrêt attend sa validation (ADR 0273)
        return True
    return any(o.asked_to == person and (o.status == c.BLOCKED or (o.status == c.OPEN and o.need_ref))
               for o in p.objectives)


def _talked(s: ProjectsState, person: str | None) -> list[Project]:
    """Les projets dont une conversation peut parler (au plus ``SHOWN * 2``) : ceux qui attendent la personne
    d'abord, puis les plus récents — le projet dont elle attend la réponse n'est jamais celui qui manque (ADR
    0161)."""
    lives = _recent(s)
    first = [p for p in lives if _awaits(p, person)]
    return [*first, *(p for p in reversed(lives) if p.id not in {x.id for x in first})][:SHOWN * 2]


def _who(frame: Frame, key: str | None) -> str:
    name = identity_c.person_name(frame, key or "")
    return f"« {name} »" if name else phrase("expression.person.someone")


def _objective_line(o: Objective, texts: Mapping[str, str], pm: Any, now: int) -> str:
    text = texts.get(o.text_ref, phrase("projects.objective.forgotten"))
    status = family("projects.objective.status").get(o.status, o.status)
    if o.kind == c.CONSTANT and o.status != c.OPEN:
        state = phrase("projects.objective.aside", status=status)
    elif o.kind == c.CONSTANT:
        # jamais passé : sa cadence l'amènera — ou tout de suite, s'il le dit (ADR 0280)
        last = phrase("projects.objective.last_pass", ago=ago_words(now - o.passed_at)) if o.passed_at else \
            phrase("projects.objective.never_at_once") if o.at_once else phrase("projects.objective.never")
        # sans cadence, il ne passe que sur événement (ADR 0265)
        state = phrase("projects.objective.on_event", last=last) if o.only_on_event else \
            phrase("projects.objective.constant", every=_every(cadence(o, pm)), last=last)
    else:
        state = phrase("projects.objective.once", status=status)
    line = "- " + phrase("projects.objective.line", id=o.id, state=state, text=text)
    if o.status == c.OPEN:  # ce qui le déclenche, en plus de sa cadence
        line += triggers_said(o.on, o.only_on_event)
    if o.status == c.DONE and texts.get(o.result_ref):  # ce qu'il a donné : la suite s'appuie dessus (ADR 0145)
        line += phrase("projects.objective.result", result=clipped(texts[o.result_ref], 240))
    return line


def _every(us: int) -> str:
    return phrase("timespan.ago.days", n=us // DAY) if us >= 2 * DAY and us % DAY == 0 else \
        phrase("timespan.ago.hours", n=max(1, round(us / HOUR)))


def _decision_line(d: Decision, texts: Mapping[str, str]) -> str:
    why = texts.get(d.reason_ref, "") if d.reason_ref else ""
    forgotten = phrase("projects.decision.forgotten")
    return "- " + phrase("projects.decision.line", id=d.id, title=texts.get(d.title_ref, forgotten),
                         choice=texts.get(d.choice_ref, forgotten)) + \
        (phrase("projects.decision.because", why=why) if why else "")


def missing_tools(p: Project) -> str:
    """Ce que ce projet n'a pas en main parmi ce qui fabrique et observe (la Forge, ses apps, ses flux, sa
    mémoire) : à elle, elle peut se le donner (``project_equip``) ; confié, elle le demande (``needs_you``) — une
    exécution ne devine pas les outils qui lui manquent (ADR 0104)."""
    have = run_bundles(p)
    absent = [b for b in (*SELF_BUNDLES, WEB) if b not in have]
    if not absent:
        return ""
    words = family("projects.bundle_words")
    listed = ", ".join(words[b.removeprefix("mcp.")] for b in absent)
    if p.authority == c.SELF:
        return phrase("projects.run.missing_own", tools=listed)
    return phrase("projects.run.missing_confided", tools=listed)


def app_lines(p: Project, frame: Frame, problems: Mapping[str, list[str]] | None = None) -> list[str]:
    """Ses apps qui vivent dans ce projet (ADR 0104) : leur état, et ce qui attend quelqu'un — une exécution voit ce
    qu'elle a fabriqué, au lieu de le redécouvrir par forge_list ; ``problems`` : ce qui n'a pas marché hors de leurs
    appels (une vue invalide dans la console, ADR 0161)."""
    mine = [a for a in frame.get(forge_c.APPS) or () if a.project == p.id]
    if not mine:
        return []
    out = [phrase("projects.run.apps")]
    for a in mine:
        if a.held:
            state = phrase("projects.run.app.held")
        elif a.broken:
            state = phrase("projects.run.app.broken", error=a.broken[:160])
        elif a.broken_services:
            state = phrase("projects.run.app.service_broken", error=forge_c.failure(a)[:160])
        elif a.pending:
            state = phrase("projects.run.app.pending")
        elif a.refused:
            state = phrase("projects.run.app.refused")
        elif not a.enabled:
            state = phrase("projects.run.app.stopped")
        elif a.ticked_at:
            state = phrase("projects.run.app.ticked", ago=ago_words(frame.now - a.ticked_at))
        else:
            state = phrase("projects.run.app.waiting")
        line = phrase("projects.run.app.line", title=a.title, app=a.name, version=a.version, state=state)
        if a.services:
            line += phrase("projects.run.app.services", services=", ".join(a.services))
        if seen := (problems or {}).get(a.name):
            line += phrase("projects.run.app.problems", problems=" ; ".join(x[:200] for x in seen[-2:]))
        out.append("- " + line)
    return [*out, phrase("projects.run.apps_tell"),
            phrase("projects.run.apps_clock", zone=str(frame.env.tz_of(frame.root)))]


def run_rules(pm: Any) -> str:
    """Comment se conclut une exécution, et ce qu'elle a de tours et de temps (dits, pas devinés)."""
    return phrase("projects.run.rules", minutes=max(1, pm.run_programs_us // MINUTE))


@PROJECTS.section("project", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=90, title=phrase("projects.run.title"),
                  reads=[forge_c.APPS, identity_c.IS_OWNER])
def _run_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = episode_project(s, frame)
    if got is None:
        return None
    p, target = got
    data = enrich.get("projects") or {}
    texts: Mapping[str, str] = data.get("texts") or {}
    pm = params(frame.env.params_of("projects", frame.root))
    who = phrase("projects.run.own") if p.authority == c.SELF else \
        phrase("projects.run.confided", who=_who(frame, p.address or p.owner))
    # le mode de cette exécution : celui du projet, ou celui d'un réveil par API qui le lance (ADR 0068)
    mode = c.PLAIN if frame.episode is not None and frame.episode.kind == Kind.JOB else c.PERSONA
    lines = [phrase("projects.run.head", id=p.id, title=texts.get(p.title_ref, phrase("projects.run.no_title")),
                    who=who), family("projects.run.mode")[mode]]
    if p.request_ref and texts.get(p.request_ref):  # ses mots, tels quels : ce qu'il faut viser (ADR 0145)
        lines.append(phrase("projects.run.request", who=_who(frame, p.asked_by), text=texts[p.request_ref]))
    if p.description_ref and texts.get(p.description_ref):
        lines.append(phrase("projects.run.own_aim", text=texts[p.description_ref]) if p.authority == c.SELF
                     else phrase("projects.run.confided_frame", text=texts[p.description_ref]))
    if p.plan_state == c.TO_FRAME and frame_of(frame.episode.attrs.get("subject") if frame.episode else None) == p.id:
        # les projets qu'il peut demander à lire : leur titre se dit au niveau de leur projet (ADR 0257)
        readable = links.askable(s, p, links.world_of(frame))[:READABLE_SHOWN]
        return SectionBody("\n".join([*lines, *_frame_lines(p, texts, frame, pm, readable)]),
                           level=max([p.sensitivity, *(t.sensitivity for t in readable)]),
                           provenance=(f"project:{p.id}",))
    if p.plan_ref and texts.get(p.plan_ref):
        lines.append(phrase("projects.run.plan", plan=texts[p.plan_ref]))
        lines += _answer_lines(p, texts, frame)
    if target is not None:
        lines.append(phrase("projects.run.target") + "\n" + _objective_line(target, texts, pm, frame.now))
        if target.done_when_ref and texts.get(target.done_when_ref):
            lines.append(phrase("projects.run.done_when", criterion=texts[target.done_when_ref]))
        if target.brief_ref and texts.get(target.brief_ref):  # le commentaire de qui a validé son plan (ADR 0270)
            lines.append(phrase("projects.run.ticket_brief", brief=texts[target.brief_ref]))
        # où elle en est (ADR 0273) : ses jalons, leur état, la preuve des atteints, celui qui vient
        lines += milestones.lines(target, texts, caretaker(frame))
        if target.kind == c.CONSTANT:
            lines.append(phrase("projects.run.constant"))
            lines += milestones.routine_lines(target, texts)  # ce que chaque passage doit faire
        if target.note_ref and texts.get(target.note_ref):
            lines.append(phrase("projects.run.note", note=texts[target.note_ref]))
        lines += _own_memory(target, texts, frame.now)
        if target.need_ref and texts.get(target.need_ref):
            # sa réponse est arrivée : elle l'a sous les yeux, elle n'a ni à l'attendre ni à la redemander
            reply = phrase("projects.run.reply") if (enrich.get("projects_answer") or {}).get("lines") else \
                phrase("projects.run.steered") if target.steered_at else ""
            lines.append(phrase("projects.run.awaited", need=texts[target.need_ref], reply=reply))
    others = [o for o in p.objectives if target is None or o.id != target.id]
    if others:
        # une exécution sans objectif visé (un réveil par API, ADR 0068) les voit tous
        heading = phrase("projects.run.others") if target is not None else phrase("projects.run.all")
        lines.append(heading + "\n" + "\n".join(
            _objective_line(o, texts, pm, frame.now) for o in others if o.status != c.DROPPED))
    decisions = [d for d in p.decisions if d.status == c.IN_FORCE][-DECISIONS_SHOWN:]
    if decisions:
        lines.append(phrase("projects.run.decisions") + "\n"
                     + "\n".join(_decision_line(d, texts) for d in decisions))
    if instructions := _instruction_lines(p, texts):
        lines.append(phrase("projects.run.instructions") + "\n" + "\n".join(instructions))
    # sa mémoire de travail (ADR 0145, 0253) : l'objectif visé a montré les siens plus haut ; ici, ceux du reste du
    # projet, le plus récent en dernier — cinq lignes en tout, les siennes d'abord
    room = max(1, REPORTS_SHOWN - (len(_earlier(target, texts)) if target is not None else 0))
    reports = [(at, oid, verdict, texts[ref]) for at, oid, verdict, ref in p.reports
               if texts.get(ref) and (target is None or oid != target.id)][-room:]
    if reports:
        verdicts = family("projects.run.verdicts")
        heading = phrase("projects.run.reports") if target is None else phrase("projects.run.other_reports")
        lines.append(heading + "\n" + "\n".join(
            "- " + phrase("projects.run.report_line", ago=ago_words(frame.now - at), objective=oid,
                          verdict=verdicts.get(verdict, verdict), summary=clipped(summary, REPORT_CLIP))
            for at, oid, verdict, summary in reports))
    elif p.summary_ref and texts.get(p.summary_ref) and (target is None or p.summary_ref != target.note_ref):
        lines.append(phrase("projects.run.summary", summary=texts[p.summary_ref]))
    mine = set(target.notes) if target is not None else set()
    kept = sum(1 for r in mine if texts.get(r))
    notes = [texts[r] for r in p.notes if texts.get(r) and r not in mine][-max(1, min(NOTES_SHOWN, NOTES_TOTAL - kept)):]
    if notes:
        lines.append(phrase("projects.run.notebook") + "\n" + "\n".join(f"- {n}" for n in notes))
    if p.deposits:
        lines.append(phrase("projects.run.deposits") + "\n" + "\n".join(
            "- " + phrase("projects.run.deposit", name=name, size=size)
            + (f" — {texts[note]}" if note and texts.get(note) else "")
            for name, size, note in p.deposits[-3:]))
    if p.effects:  # leur état seulement : ce que le réseau a rendu est cité à part
        refused = {f"#{n}": texts.get(ref) for n, ref in p.refusals}
        lines.append(phrase("projects.run.effects") + "\n" + "\n".join(
            f"- {e}" + (phrase("projects.run.refused_why", why=why[:200]) if (why := refused.get(e.split(' ', 1)[0]))
                        else "")
            for e in p.effects[-3:]))
    if p.remote:
        lines.append(phrase("projects.run.remote_auto", remote=p.remote, branch=p.branch) if p.auto_push else
                     phrase("projects.run.remote_manual", remote=p.remote, branch=p.branch))
    if "workshop" in p.bundles:
        lines += _atelier_lines(enrich.get("projects_tree") or {})
    if apps := app_lines(p, frame, (enrich.get("projects_apps") or {}).get("problems")):
        lines.append("\n".join(apps))
    if missing := missing_tools(p):
        lines.append(missing)
    lines.append(phrase("projects.run.method"))
    lines.append(run_rules(pm))
    return SectionBody("\n".join(lines), level=p.sensitivity, provenance=(f"project:{p.id}",))


#: ce qu'on cite d'un compte rendu dans sa mémoire de travail (caractères) : du reste du projet, et de l'objectif
#: visé (son dernier est entier, sur la ligne « où tu en étais »)
REPORT_CLIP = 500
OWN_REPORT_CLIP = 800
#: les comptes rendus qu'une exécution relit en tout : ceux d'avant de l'objectif visé, complétés par ceux du reste
#: du projet ; ses notes : celles de l'objectif visé, puis au plus trois du reste du carnet, cinq en tout (ADR 0253)
REPORTS_SHOWN = 5
NOTES_SHOWN = 3
NOTES_TOTAL = 5


def _earlier(target: Objective, texts: Mapping[str, str]) -> list[tuple[int, str, str]]:
    """Les comptes rendus d'avant de l'objectif visé : les siens, moins le dernier, que la ligne « où tu en étais »
    cite déjà en entier."""
    return [(at, verdict, texts[ref]) for at, verdict, ref in target.reports
            if texts.get(ref) and ref != target.note_ref]


def _own_memory(target: Objective, texts: Mapping[str, str], now: int) -> list[str]:
    """Ce que l'objectif visé garde de lui-même (ADR 0253) : ses comptes rendus d'avant et ses notes. Il les retrouve
    quel que soit le travail fait depuis sur les autres objectifs du projet."""
    lines = []
    earlier = _earlier(target, texts)
    if earlier:
        verdicts = family("projects.run.verdicts")
        lines.append(phrase("projects.run.own_reports") + "\n" + "\n".join(
            "- " + phrase("projects.run.own_report_line", ago=ago_words(now - at),
                          verdict=verdicts.get(verdict, verdict), summary=clipped(summary, OWN_REPORT_CLIP))
            for at, verdict, summary in earlier))
    notes = [texts[r] for r in target.notes if texts.get(r)]
    if notes:
        lines.append(phrase("projects.run.own_notebook") + "\n" + "\n".join(f"- {n}" for n in notes))
    return lines


def _answer_lines(p: Project, texts: Mapping[str, str], frame: Frame) -> list[str]:
    """Les questions de son plan, avec ce qu'elle recommandait et la réponse qu'elles ont eue — ensemble : « oui pour
    la 1 » ne veut rien dire sans la 1 (ADR 0161). Validé sans un mot, ses recommandations valent."""
    questions = texts.get(p.questions_ref, "") if p.questions_ref else ""
    if not questions or p.plan_state not in (c.PLANNED, c.TO_FRAME):
        return []
    answer = texts.get(p.plan_answer_ref, "") if p.plan_answer_ref else ""
    if answer:
        said = [phrase("projects.run.plan_answer", who=_who(frame, p.asked_by), words=answer)]
    else:  # à reprendre, la réponse est la demande de révision (ses consignes) ; validé sans un mot, elles valent
        said = [] if p.plan_state == c.TO_FRAME else [phrase("projects.run.plan_silent")]
    return [phrase("projects.run.plan_questions", questions=questions), *said]


def _instruction_lines(p: Project, texts: Mapping[str, str]) -> list[str]:
    """Ses dernières consignes, chacune avec les mots de la personne quand elle les a dits de vive voix (ADR 0145)."""
    said = dict(p.said)
    out = []
    for ref in [r for r in p.instructions if texts.get(r)][-INSTRUCTIONS_SHOWN:]:
        line = f"- {texts[ref]}"
        words = texts.get(said.get(ref, ""), "")
        if words and words.strip() != texts[ref].strip():
            line += "\n  " + phrase("projects.run.their_words", words=clipped(words, 600))
        out.append(line)
    return out


def _named(t: Project, texts: Mapping[str, str]) -> str:
    """Un autre projet, nommé : son numéro et son titre."""
    return phrase("projects.links.named", id=t.id, title=texts.get(t.title_ref) or phrase("projects.run.no_title"))


def _frame_lines(p: Project, texts: Mapping[str, str], frame: Frame, pm: Any,
                 readable: tuple[Project, ...] = ()) -> list[str]:
    """Sa séance de cadrage (ADR 0145) : ses idées de départ, ce qu'on lui a dit depuis, son plan d'avant s'il est à
    reprendre, les projets que celui-ci peut demander à lire (``readable``, ADR 0257), et comment écrire un plan
    qui tient."""
    lines = []
    ideas = [o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED)]
    if ideas:
        lines.append(phrase("projects.frame.ideas") + "\n" + "\n".join(
            _objective_line(o, texts, pm, frame.now) for o in ideas))
    done = [o for o in p.objectives if o.status == c.DONE]
    if done:
        lines.append(phrase("projects.frame.done") + "\n" + "\n".join(
            _objective_line(o, texts, pm, frame.now) for o in done[-6:]))
    if instructions := _instruction_lines(p, texts):
        lines.append(phrase("projects.run.instructions") + "\n" + "\n".join(instructions))
    if p.plan_ref and texts.get(p.plan_ref):  # à reprendre : la personne a demandé une révision
        lines.append(phrase("projects.frame.previous", plan=texts[p.plan_ref]))
        lines += _answer_lines(p, texts, frame)
    if apps := app_lines(p, frame):
        lines.append("\n".join(apps))
    if missing := missing_tools(p):
        lines.append(missing)
    if readable:
        lines.append(phrase("projects.frame.readable") + "\n" + "\n".join(f"- {_named(t, texts)}" for t in readable))
    lines.append(phrase("projects.frame.rules", asked=phrase("projects.frame.asked") if p.asked_by
                        else phrase("projects.frame.alone")))
    return lines


def _atelier_lines(tree: Mapping[str, Any]) -> list[str]:
    files = tree.get("tree")
    if files is None:
        why = tree.get("tree_error")
        return [phrase("projects.run.tree_unreadable_why", why=why) if why else phrase("projects.run.tree_unreadable")]
    out = [phrase("projects.run.tree") + "\n"
           + ("\n".join(f"- {f}" for f in files[:TREE_SHOWN]) if files else f"- {phrase('projects.run.tree_empty')}")]
    pending = tree.get("pending") or []
    if pending:
        out.append(phrase("projects.run.pending", files=", ".join(pending[:PENDING_SHOWN])
                          + (" …" if len(pending) > PENDING_SHOWN else "")))
    return out


#: ce que son projet lit des autres est ce sur quoi il s'appuie : coupé avant son propre cadre, jamais au point de
#: disparaître
LINKS_FLOOR = 600


def _view_lines(t: Project, view: Mapping[str, Any] | None, now: int) -> list[str]:
    """La vue de l'atelier d'un projet lu (ADR 0260) : où elle est, le commit vu et son âge, puis le début de son
    arbre ; sans vue, pourquoi. ``None`` : elle n'a pas été posée au départ (un dépôt lent) — ses outils la poseront."""
    place = view_place(t.id) + "/"
    if view is None:
        return ["  " + phrase("projects.links.view.later", path=place)]
    if not view.get("sha"):
        return ["  " + phrase("projects.links.view.absent", why=no_view_words(str(view.get("why") or "")))]
    at = int(view.get("at") or 0)
    out = ["  " + phrase("projects.links.view.open", path=place, sha=str(view["sha"])[:7],
                         age=phrase("projects.links.view.age", ago=ago_words(now - at)) if at else "")]
    # le nom d'un fichier d'un autre projet est une donnée : sans caractère de contrôle, et coupé (ADR 0262)
    entries = [view_entry(str(f)) for f in view.get("tree") or ()]
    if not entries:
        return [*out, "  - " + phrase("projects.links.view.empty")]
    out += [f"  - {entry}" for entry in entries[:VIEW_TREE_SHOWN]]
    if len(entries) > VIEW_TREE_SHOWN:  # l'enrichisseur en garde une de plus, pour le savoir
        out.append("  - " + phrase("projects.links.view.more", path=place))
    return out


def _link_lines(t: Project, grant: links.Grant, texts: Mapping[str, str], pm: Any, now: int,
                view: Mapping[str, Any] | None = None, ask: str = "") -> list[str]:
    """Un projet lu, selon ce que son lien donne (ADR 0257). Le voir : son titre et son état. Le lire : la date de
    sa dernière exécution, ses derniers comptes rendus, ses décisions en vigueur, ses objectifs ouverts. Ses
    fichiers : la vue de son atelier (``view`` : ce que l'enrichisseur en a posé, ADR 0260). Lui adresser une
    demande (``ask`` : comment elle naîtrait, ``asks.mode`` — ADR 0271)."""
    done = sum(1 for o in t.objectives if o.kind == c.ONCE and o.status == c.DONE)
    total = sum(1 for o in t.objectives if o.kind == c.ONCE and o.status != c.DROPPED)
    state = family("projects.links.states").get(t.status, t.status)
    if total:
        state += phrase("projects.links.progress", done=done, total=total)
    out = ["- " + phrase("projects.links.line", project=_named(t, texts), state=state)]
    if ask:
        out.append("  " + (phrase("projects.links.ask.direct") if ask == asks.DIRECT else
                           phrase("projects.links.ask.proposed")))
    if grant.detail:
        out += _detail_lines(t, texts, pm, now)
    elif not grant.view:
        out.append("  " + phrase("projects.links.title_only"))
    if grant.view:
        out += _view_lines(t, view, now)
    return out


def _detail_lines(t: Project, texts: Mapping[str, str], pm: Any, now: int) -> list[str]:
    """Ce qu'un lien donne à lire d'un projet : sa dernière exécution, ses derniers comptes rendus, ses décisions en
    vigueur, ses objectifs ouverts."""
    out = ["  " + (phrase("projects.links.last_run", ago=ago_words(now - t.last_run_at)) if t.last_run_at
                   else phrase("projects.links.never_run"))]
    reports = [(at, verdict, texts[ref]) for at, _, verdict, ref in _read_reports(t) if texts.get(ref)]
    if reports:
        verdicts = family("projects.run.verdicts")
        out.append("  " + phrase("projects.links.reports"))
        out += ["  - " + phrase("projects.links.report_line", ago=ago_words(now - at),
                               verdict=verdicts.get(verdict, verdict), summary=clipped(summary, LINK_REPORT_CLIP))
                for at, verdict, summary in reports]
    in_force = sum(1 for d in t.decisions if d.status == c.IN_FORCE)
    if in_force:
        out.append("  " + phrase("projects.links.decisions"))
        out += ["  " + clipped(_decision_line(d, texts), LINK_LINE_CLIP) for d in _read_decisions(t)]
        if in_force > LINK_LISTED:
            out.append("  - " + phrase("projects.links.more", count=in_force - LINK_LISTED))
    living = sum(1 for o in t.objectives if o.status in (c.OPEN, c.BLOCKED))
    if living:
        out.append("  " + phrase("projects.links.objectives"))
        out += ["  " + clipped(_objective_line(o, texts, pm, now), LINK_LINE_CLIP) for o in _read_objectives(t)]
        if living > LINK_LISTED:
            out.append("  - " + phrase("projects.links.more", count=living - LINK_LISTED))
    return out


@PROJECTS.section("project_links", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=60, floor_chars=LINKS_FLOOR,
                  title=phrase("projects.links.title"), reads=[identity_c.IS_OWNER])
def _links_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que son projet lit des autres (ADR 0257), relu à chaque exécution dans leurs lignes d'accès : un droit
    retiré coupe ce qu'il donnait, un projet qui n'est plus visible suspend le lien — dit en une ligne. Son niveau
    est celui de ce qu'elle y lit : ce qu'écrivent les projets dont elle lit le détail ou les fichiers (les noms des
    fichiers d'une vue en sont, ADR 0260)."""
    got = episode_project(s, frame)
    if got is None or not got[0].reads:
        return None
    p = got[0]
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    pm = params(frame.env.params_of("projects", frame.root))
    views: Mapping[str, Mapping[str, Any]] = (enrich.get("projects_views") or {}).get("views") or {}
    lines = [phrase("projects.links.head"), phrase("projects.links.foreign")]
    level, seen = 0, []
    for r in links.readings(s, p, links.world_of(frame)):
        t = r.project
        if t is None or r.suspended:
            lines.append("- " + phrase("projects.links.suspended", id=r.id))
            continue
        lines += _link_lines(t, r.grant, texts, pm, frame.now, views.get(str(t.id)), asks.mode(p, t, r.grant))
        level = max(level, written(t) if r.grant.detail or r.grant.view else t.sensitivity)
        seen.append(f"project:{t.id}")
    return SectionBody("\n".join(lines), level=level, provenance=tuple(seen))


#: ce qui amène une exécution tient en quelques lignes : coupé tard, jamais au point de disparaître ; une ligne par
#: cause, coupée
STIRS_FLOOR = 400
STIR_LINE_CLIP = 240


def _causes(s: ProjectsState, frame: Frame, target: Objective | None) -> tuple[tuple[Stir, ...], int]:
    """Ce qui a déclenché l'objectif visé (ADR 0265) : les causes que l'exécution a prises à son départ
    (``Run.stirred``) — sinon celles qu'il a encore, tant qu'aucune exécution n'est partie —, et combien sont tombées
    de la liste."""
    if target is None:
        return (), 0
    ep = frame.episode
    run = s.running.get(ep.id) if ep is not None else None
    if run is not None and run.purpose == "run" and run.objective == target.id:
        return run.stirred, run.stirred_more
    return target.stirred, target.stirred_more


def _stir_source(s: ProjectsState, frame: Frame, p: Project, cause: Stir) -> tuple[int, Project | None]:
    """Le projet d'où vient une cause, et lui-même si le lien donne **encore** son détail (ADR 0265) : ce qu'on dit
    d'une cause se relit au moment de la dire — un droit repris depuis qu'elle est arrivée la tait."""
    t = triggers.read(cause.key)
    if t is None or t.sort != triggers.PROJECT:
        return 0, None
    reading = next((r for r in links.readings(s, p, links.world_of(frame)) if r.id == t.project), None)
    return t.project, reading.project if reading is not None and reading.grant.detail else None


def _stir_done(source: Project | None, cause: Stir) -> Objective | None:
    """L'objectif abouti que nomme une cause, dans le projet d'où elle vient."""
    return objective_at(source, cause.detail) if source is not None else None


def _stir_refs(s: ProjectsState, frame: Frame, p: Project, target: Objective | None) -> list[str]:
    """Les titres des objectifs aboutis que nomment les causes de l'objectif visé — seulement ceux que le lien donne."""
    refs = []
    for cause in _causes(s, frame, target)[0]:
        t = triggers.read(cause.key)
        if t is not None and t.sort == triggers.PROJECT and t.name == triggers.DONE:
            done = _stir_done(_stir_source(s, frame, p, cause)[1], cause)
            if done is not None and done.text_ref:
                refs.append(done.text_ref)
    return refs


def _stir_line(s: ProjectsState, frame: Frame, p: Project, cause: Stir, texts: Mapping[str, str]) -> tuple[str, Project | None, bool]:
    """Une cause en une ligne, le projet d'où elle vient quand on en dit le détail, et si elle cite un titre venu de
    lui. Une base qui a avancé (ADR 0280) : l'empreinte courte du commit où elle est arrivée et le numéro du projet. Un objectif abouti : son titre, si le lien donne
    encore le détail. Un projet que le lien ne donne plus : son numéro, rien d'autre."""
    ago = ago_words(max(0, frame.now - cause.at))
    asked = triggers.asked(cause.key)
    if asked:  # une demande fermée (ADR 0271) : son ticket, si le lien donne encore le détail du projet visé
        if not asks.reads(s, p, asked, links.world_of(frame)):
            return phrase("projects.stirs.unread", ago=ago, id=asked), None, False
        return phrase("projects.stirs.ask", ago=ago, item=cause.detail, id=asked), s.projects.get(asked), False
    t = triggers.read(cause.key)
    if t is None:
        return phrase("projects.stirs.other", ago=ago), None, False
    if t.sort == triggers.APP:
        said = phrase("projects.stirs.app_broken", ago=ago, name=t.name) if cause.detail == forge_c.APP_BROKEN else \
            phrase("projects.stirs.app_queued", ago=ago, name=t.name) if cause.detail == forge_c.APP_QUEUED else \
            phrase("projects.stirs.app", ago=ago, name=t.name)
        return said, None, False
    if t.sort == triggers.ITEM:  # ce qui a bougé dans une de ses listes (ADR 0268) : un numéro ou une clé, pas un titre
        return phrase("projects.stirs.item", ago=ago, name=t.name, item=cause.detail), None, False
    if t.sort != triggers.PROJECT:
        return phrase("projects.stirs.other", ago=ago), None, False
    number, source = _stir_source(s, frame, p, cause)
    if source is None:
        return phrase("projects.stirs.unread", ago=ago, id=number), None, False
    if t.name == triggers.COMMIT:
        return phrase("projects.stirs.commit", ago=ago, id=number, sha=cause.detail[:7]), source, False
    done = _stir_done(source, cause)
    title = texts.get(done.text_ref, "") if done is not None else ""
    if not title:
        return phrase("projects.stirs.done", ago=ago, id=number), source, False
    return phrase("projects.stirs.done_titled", ago=ago, id=number, objective=done.id, title=title), source, True


@PROJECTS.section("project_stirs", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=85, floor_chars=STIRS_FLOOR,
                  title=phrase("projects.stirs.title"), reads=[identity_c.IS_OWNER])
def _stirs_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qui amène cette exécution, quand ce n'est pas la cadence de l'objectif (ADR 0265) : ses causes en attente,
    de la plus ancienne à la plus récente, une ligne bornée chacune ; et le réveil par API qui le vise. Son niveau
    est celui de ce qu'elle y lit : ce qu'écrivent les projets dont une cause dit le détail."""
    got = episode_project(s, frame)
    ep = frame.episode
    if got is None or got[1] is None or ep is None:
        return None
    p, target = got
    causes, more = _causes(s, frame, target)
    woken = wakeup_c.call_of(ep.attrs.get("subject")) is not None
    if not causes and not woken:
        return None
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    lines = [phrase("projects.stirs.woken")] if woken else []
    seen: dict[int, Project] = {}
    cited = False
    if causes:
        lines.append(phrase("projects.stirs.head"))
        if more:
            lines.append("- " + phrase("projects.stirs.more", count=more))
        for cause in causes:
            said, source, titled = _stir_line(s, frame, p, cause, texts)
            lines.append("- " + clipped(said, STIR_LINE_CLIP))
            cited = cited or titled
            if source is not None:
                seen[source.id] = source
    if cited:  # le titre d'un objectif d'un autre projet est une donnée, comme ce que montre « CE QUE CE PROJET LIT »
        lines.append(phrase("projects.stirs.foreign"))
    if seen:
        lines.append(phrase("projects.stirs.see_links"))
    return SectionBody("\n".join(lines), level=max([p.sensitivity, *(written(t) for t in seen.values())]),
                       provenance=(f"project:{p.id}", *(f"project:{n}" for n in seen)))


#: son registre tient en dix lignes : coupé tard, jamais au point de disparaître
ITEMS_FLOOR = 500


@PROJECTS.section("project_items", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=70, untrusted=True,
                  floor_chars=ITEMS_FLOOR, title=phrase("projects.items.title"))
def _items_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Le registre du projet, pour l'exécution qui vise un objectif (ADR 0268) : les comptes de ses listes, puis ce
    qu'un autre qu'elle a touché depuis son dernier passage, puis ses éléments ouverts les plus anciens — dix
    lignes au plus, chacune coupée. Un titre écrit par une personne y est cité : une donnée, jamais une consigne
    (la section est déclarée non sûre, comme la réponse à une demande d'aide)."""
    got = episode_project(s, frame)
    if got is None or got[1] is None or not got[0].board.counts:
        return None
    p = got[0]
    found: Mapping[str, Any] = enrich.get("projects_items") or {}
    titles: Mapping[str, str] = found.get("titles") or {}
    counted = [lst for lst in tracker.listings(p.board) if tracker.count(p.board, lst.name)]
    lines = [tracker.counts_line(p.board, lst, tracker.list_title(lst, titles)) for lst in counted[:ITEMS_LISTS]]
    if len(counted) > ITEMS_LISTS:  # la dernière ligne des comptes dit ce qu'on ne montre pas
        lines[-1] = phrase("projects.items.more_lists", count=len(counted) - ITEMS_LISTS + 1)
    for head, entries in ((phrase("projects.items.moved"), list(found.get("moved") or ())[:ITEMS_MOVED]),
                          (phrase("projects.items.oldest"), list(found.get("oldest") or ())[:ITEMS_OLDEST])):
        if entries:
            lines.append(head)
            lines += [f"- {said}" for said in entries]
    body = "\n".join(clipped(x, ITEM_LINE_CLIP) for x in lines[:ITEMS_LINES])
    return SectionBody(body, level=max(written(p), int(found.get("level") or 0)), provenance=(f"project:{p.id}",))


#: ses tickets sont ce sur quoi le passage travaille : coupés tard, jamais au point de disparaître ; une ligne est
#: coupée
TICKETS_FLOOR = 900
TICKET_LINE_CLIP = 420


@PROJECTS.section("project_tickets", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=75, untrusted=True,
                  floor_chars=TICKETS_FLOOR, title=phrase("projects.tickets.title"))
def _tickets_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Les tickets que regarde cette exécution (ADR 0270) : pour le passage qui les traite, ceux qui sont entre ses
    mains, par priorité — leur étape, ce qui est attendu d'elle, le dernier mot du fil —, bornés ; pour l'objectif
    né d'un ticket, le sien et son plan. Ce qu'une personne y a écrit est cité : une donnée, jamais une consigne
    (la section est déclarée non sûre)."""
    got = episode_project(s, frame)
    found: Mapping[str, Any] = enrich.get("projects_tickets") or {}
    lines = [clipped(x, triage.PLAN_SHOWN + 200 if found.get("own") else TICKET_LINE_CLIP)
             for x in found.get("lines") or ()]
    if got is None or got[1] is None or not lines:
        return None
    p = got[0]
    head = phrase("projects.tickets.head.own") if found.get("own") else phrase("projects.tickets.head.triage")
    return SectionBody("\n".join([head, *lines]), level=max(written(p), int(found.get("level") or 0)),
                       provenance=(f"project:{p.id}",))


#: ses demandes aux autres projets tiennent en quelques lignes : coupées tard, jamais au point de disparaître ; une
#: ligne est coupée
ASKS_FLOOR = 500
ASK_LINE_CLIP = 520


@PROJECTS.section("project_asks", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=72, untrusted=True,
                  floor_chars=ASKS_FLOOR, title=phrase("projects.asks.title"))
def _asks_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Les demandes que son projet a adressées aux projets qu'il lit (ADR 0271), pour l'exécution qui vise un
    objectif : en attente d'accord, acceptée, en cours, traitée, écartée avec sa raison — celles fermées depuis son
    dernier passage d'abord, bornées. Une demande à un projet dont le lien ne donne plus le détail ne dit que son
    existence. Le titre d'un ticket et la note de sa fermeture sont cités : une donnée, jamais une consigne (la
    section est déclarée non sûre). Son niveau est celui de ce qu'elle y lit : ce qu'écrivent les projets visés."""
    got = episode_project(s, frame)
    found: Mapping[str, Any] = enrich.get("projects_asks") or {}
    lines = [clipped(x, ASK_LINE_CLIP) for x in found.get("lines") or ()]
    if got is None or got[1] is None or not lines:
        return None
    p = got[0]
    seen = [s.projects[t] for t in found.get("seen") or () if t in s.projects]
    return SectionBody("\n".join([phrase("projects.asks.head"), *lines]),
                       level=max([written(p), *(written(t) for t in seen)]),
                       provenance=(f"project:{p.id}", *(f"project:{t.id}" for t in seen)))


#: ce que sa dernière commande réseau a rendu est ce sur quoi elle travaille : coupé en premier (venu d'Internet),
#: jamais au point de disparaître
NETWORK_FLOOR = 600


@PROJECTS.section("project_network", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=0, untrusted=True,
                  floor_chars=NETWORK_FLOOR, title=phrase("projects.network.title"))
def _network_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """La sortie de sa dernière commande réseau : une donnée venue d'Internet, citée, coupée en premier — jusqu'à
    son plancher (c'est ce sur quoi elle travaille)."""
    got = episode_project(s, frame)
    if got is None or not got[0].network_out:
        return None
    p = got[0]
    return SectionBody(phrase("projects.network.head", ago=ago_words(frame.now - p.network_out_at)) + f"\n{p.network_out}",
                       level=0, provenance=(f"project:{p.id}",))


#: sa réponse est ce qui débloque l'objectif : citée (ses mots, une donnée), coupée tôt, jamais au point de disparaître
ANSWER_FLOOR = 500


@PROJECTS.section("project_answer", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=5, untrusted=True,
                  floor_chars=ANSWER_FLOOR, title=phrase("projects.answer.title"), reads=[identity_c.IDENTITY])
def _answer_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que la personne à qui elle a demandé un coup de main lui a écrit depuis, en privé : cité, pour que
    l'exécution reparte avec la réponse sous les yeux plutôt que de deviner ou de redemander."""
    got = episode_project(s, frame)
    lines = (enrich.get("projects_answer") or {}).get("lines") or []
    if got is None or got[1] is None or not lines:
        return None
    p, o = got
    body = (phrase("projects.answer.head", who=_who(frame, o.asked_to), ago=ago_words(frame.now - o.asked_at)) + "\n"
            + "\n".join(f"- {line}" for line in lines))
    return SectionBody(body, level=written(p), provenance=(f"project:{p.id}",))


@PROJECTS.section("project_share", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=90,
                  title=phrase("projects.share.title"), reads=[forge_c.APPS, identity_c.IS_OWNER])
def _share_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle a mené à bout dans un projet depuis son dernier récit — à la mesure du lien avec qui l'écoute ;
    ou, quand elle a besoin de qui le lui a confié, ce qui la bloque ; ou un projet à elle que des pannes ont
    arrêté (ADR 0143)."""
    ep = frame.episode
    stalled = s.projects.get(stall_of(ep.attrs.get("subject"))) if ep is not None else None
    if stalled is not None:
        return _stall_body(stalled, frame, enrich)
    planned = s.projects.get(plan_of(ep.attrs.get("subject"))) if ep is not None else None
    if planned is not None:
        return _plan_body(planned, frame, enrich)
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    p = s.projects.get(got[0]) if got is not None else None
    o = next((x for x in p.objectives if x.id == got[1]), None) if p is not None and got is not None else None
    if p is None or o is None:
        return None
    store = (enrich.get("projects") or {}).get("texts") or {}
    title, objective = store.get(p.title_ref), store.get(o.text_ref)
    args = ep.attrs.get("args") if ep is not None else None
    share = str(args.get("share", social_c.MENTION)) if args else social_c.MENTION
    need = asking(o)  # le sujet le dit, pas les raisons de la ligne (un récit peut y côtoyer une demande)
    aud = frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if aud is None or not hearable(p.about, written(p), person, aud.level, aud.witness_level, aud.private_ok) \
            or (share == social_c.MENTION and not need) or not title:
        return SectionBody(phrase("projects.share.something"), level=0)
    level = written(p) if any(a != person for a in p.about) else 0
    if need:
        wanted = store.get(o.need_ref, "") or store.get(o.result_ref, "")
        state = phrase("projects.share.blocked") if o.status == c.BLOCKED else phrase("projects.share.waiting")
        body = phrase("projects.share.need_head", title=title, objective=objective or "…", state=state)
        opinions = [store.get(r, "") for r in o.review_refused] if handed_over(o) else []
        if any(opinions):
            # deux relectures indépendantes l'ont refusé : la main est à cette personne, avec les deux avis, cités
            # comme le dire d'autres exécutions (ADR 0276)
            body += "\n" + phrase("projects.share.reviews") + "".join(
                "\n" + phrase("projects.share.review", n=i, said=clipped(x, REVIEW_CLIP))
                for i, x in enumerate(opinions, start=1) if x)
        elif o.review_due and o.review_tries >= REVIEW_TRIES_MAX:
            body += "\n" + phrase("projects.share.review_silent")
        elif wanted:
            body += "\n" + phrase("projects.share.need", need=wanted)
        return SectionBody(body, level=level, title=phrase("projects.share.need_title"),
                           provenance=(f"project:{p.id}",))
    pm = params(frame.env.params_of("projects", frame.root))
    told = [x for x in untold(p, frame.now, pm) if x.id != o.id] + [o]
    if len(told) > 1:  # un point : tout ce qu'elle a mené à bout depuis le précédent, le plus récent en dernier
        lines = [phrase("projects.share.many", title=title)]
        if len(told) > TOLD_SHOWN:
            lines.append("- " + phrase("projects.share.more", count=len(told) - TOLD_SHOWN))
        for x in told[-TOLD_SHOWN:]:
            result = store.get(_result_ref(x), "")
            line = f"- {store.get(x.text_ref) or phrase('projects.share.an_objective')}"
            if share == social_c.FULL and result:
                line += "\n  " + phrase("projects.share.drawn_item", result=result)
            elif result:
                line += phrase("projects.share.in_short", first=result.split(". ")[0].strip())
            lines.append(line)
        if where := _apps_where(p, frame):
            lines.append(where)
        return SectionBody("\n".join(lines), level=level, provenance=(f"project:{p.id}",))
    result = store.get(_result_ref(o), "")
    body = phrase("projects.share.one", title=title, objective=objective or phrase("projects.share.an_objective"))
    if share == social_c.FULL and result:
        body += "\n" + phrase("projects.share.drawn", result=result)
    elif result:
        body += phrase("projects.share.in_short", first=result.split(". ")[0].strip())
    if where := _apps_where(p, frame):
        body += "\n" + where
    return SectionBody(body, level=level, provenance=(f"project:{p.id}",))


def _apps_where(p: Project, frame: Frame) -> str:
    """Où voir ce que ses apps montrent (ADR 0145) : seulement celles qui ont des vues et qui marchent ; à qui
    s'occupe d'elle, le lien de leurs vues dans la console ; à une autre, la console ne lui est pas ouverte (ADR
    0161)."""
    shown = [a for a in frame.get(forge_c.APPS) or () if a.project == p.id and a.title and a.views
             and not forge_c.failure(a)]
    if not shown:
        return ""
    aud = frame.audience
    if aud is not None and aud.owner:
        return phrase("projects.share.apps", apps=", ".join(
            phrase("projects.share.app_link", title=a.title, app=quote(a.name, safe="")) for a in shown))
    return phrase("projects.share.apps_closed", apps=", ".join(f"« {a.title} »" for a in shown))


def _stall_body(p: Project, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody:
    """Son projet s'est arrêté : combien de pannes, leur cause telle que la machine la dit, et ce qu'il attend (qu'on
    le relance) — rien de ce qu'il contient : un titre suffit à le reconnaître."""
    ep, aud = frame.episode, frame.audience
    title = ((enrich.get("projects") or {}).get("texts") or {}).get(p.title_ref)
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if aud is None or not title or not hearable(p.about, written(p), person, aud.level, aud.witness_level,
                                                aud.private_ok):
        return SectionBody(phrase("projects.share.something"), level=0)
    if unplanned_stall(p, params(frame.env.params_of("projects", frame.root))):  # pas la machine : son cadrage
        return SectionBody(phrase("projects.share.unframed", title=title, n=p.frame_silent),
                           level=written(p) if any(a != person for a in p.about) else 0,
                           title=phrase("projects.share.stalled_title"), provenance=(f"project:{p.id}",))
    body = phrase("projects.share.stalled", title=title, n=p.failures)
    if p.last_failure:
        body += "\n" + phrase("projects.share.stalled_cause", cause=describe_error(p.last_failure))
    level = written(p) if any(a != person for a in p.about) else 0
    return SectionBody(body, level=level, title=phrase("projects.share.stalled_title"),
                       provenance=(f"project:{p.id}",))


def _result_ref(o: Objective) -> str:
    """Ce qu'un récit dit d'un objectif : le résultat d'un ponctuel, le compte rendu du dernier passage d'un
    constant (ADR 0145)."""
    return o.pass_ref if o.kind == c.CONSTANT else o.result_ref


def _plan_body(p: Project, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody:
    """Son plan, à dire à qui a demandé le projet (ADR 0145) : ce qu'elle va faire, ses étapes, et ses questions avec
    ce qu'elle recommande quand il attend une réponse — tout ce qu'il faut pour qu'un « vas-y » suffise."""
    ep, aud = frame.episode, frame.audience
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    title, plan = texts.get(p.title_ref), texts.get(p.plan_ref)
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if aud is None or not title or not plan or not hearable(p.about, written(p), person, aud.level,
                                                             aud.witness_level, aud.private_ok):
        return SectionBody(phrase("projects.share.something"), level=0)
    steps = sorted((o for o in p.objectives if o.status in (c.OPEN, c.BLOCKED) and o.rank), key=lambda o: o.rank)
    body = [phrase("projects.share.plan_head", title=title), plan]
    if steps:
        body.append(phrase("projects.share.plan_steps") + "\n" + "\n".join(
            f"{o.rank}. {texts.get(o.text_ref, '…')}" for o in steps))
    questions = texts.get(p.questions_ref, "") if p.plan_state == c.PROPOSED else ""
    if questions:
        body.append(phrase("projects.share.plan_questions") + "\n" + questions)
    if p.plan_state == c.PROPOSED and person and (asked := _asked_to_read(p, frame, person)):
        body.append(phrase("projects.share.plan_reads", projects=", ".join(_named(t, texts) for t in asked)))
    level = written(p) if any(a != person for a in p.about) else 0
    return SectionBody("\n".join(body), level=level, title=phrase("projects.share.plan_title"),
                       provenance=(f"project:{p.id}",))


def _asked_to_read(p: Project, frame: Frame, person: str) -> list[Project]:
    """Ce que son plan demande à lire et qui n'est pas encore lié (ADR 0257), tel qu'on peut le nommer à
    ``person`` : seulement les projets qu'il peut encore lire, et qu'elle peut voir elle aussi."""
    s: ProjectsState = frame.state("projects")
    nameable = {t.id: t for t in links.candidates(s, p, links.world_of(frame), seen_by=person)}
    return [nameable[t] for t in p.plan_reads if t in nameable]


def _next_words(p: Project, texts: Mapping[str, str], now: int, pm: Any) -> str:
    """Ce qui vient (l'objectif de la prochaine exécution) ou ce qui bloque, en une ligne."""
    blocked = next((o for o in p.objectives if o.status == c.BLOCKED), None)
    if blocked is not None and texts.get(blocked.text_ref):
        return phrase("projects.live.blocked", text=texts[blocked.text_ref])
    waiting = next((o for o in p.objectives if o.status == c.OPEN and o.need_ref), None)
    if waiting is not None and texts.get(waiting.need_ref):
        return phrase("projects.live.needs", need=texts[waiting.need_ref])
    nxt = pick(p, now, pm) or next((o for o in p.objectives if o.status == c.OPEN), None)
    if nxt is not None and texts.get(nxt.text_ref):
        return phrase("projects.live.next", text=texts[nxt.text_ref])
    return ""


def _awaiting(frame: Frame, p: Project, person: str) -> str:
    """Ce qui attend l'accord de la personne qui lui parle (elle s'occupe d'elle), pour ce projet."""
    pending = [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and project_of(v.context) == p.id]
    if not pending:
        return ""
    words = sorted({effect_words(v.capability, phrase("projects.effect.request")) for v in pending})
    return phrase("projects.live.awaiting", who=_who(frame, person), what=", ".join(words))


@PROJECTS.section("projects", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=44,
                  title=phrase("projects.live.title"),
                  reads=[identity_c.PERSON, identity_c.IS_OWNER, rt.PENDING_EFFECTS])
def _live_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts: Mapping[str, str] = (enrich.get("projects") or {}).get("texts") or {}
    ep, aud = frame.episode, frame.audience
    if aud is None:
        return None
    pm = params(frame.env.params_of("projects", frame.root))
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    owner = bool(person) and aud.owner  # l'adresse qui parle, là où elle parle (jamais un groupe public)
    lines, level, witness, steering, answering, settling = [], 0, False, False, False, False
    kind = ep.kind if ep is not None else ""
    for p in _talked(s, person):
        title = texts.get(p.title_ref)
        # ses lignes d'accès disent à qui elle en parle (ADR 0133) ; sa confidentialité, ce qu'elle en dit
        if not title or not sees(p, aud, kind, frame) or \
                not hearable(p.about, p.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        whose = phrase("projects.live.own") if p.authority == c.SELF else \
            phrase("projects.live.for", who=_who(frame, p.address or p.owner))
        how = "" if p.mode == c.PERSONA else phrase("projects.live.plain")
        done = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status == c.DONE)
        total = sum(1 for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED)
        progress = phrase("projects.live.progress", done=done, total=total) if total else \
            phrase("projects.live.maintain")
        state = phrase("projects.live.paused") if p.status == c.PAUSED else progress
        if p.status == c.ACTIVE and p.plan_state == c.TO_FRAME:
            state = phrase("projects.live.framing")
        elif p.status == c.ACTIVE and p.plan_state == c.PROPOSED:
            state = phrase("projects.live.proposed")
        if p.schedule == ON_DEMAND and p.status == c.ACTIVE:
            state += phrase("projects.live.on_demand")
        line = "- " + phrase("projects.live.line", title=title, whose=whose, how=how, state=state)
        # le détail (son dernier compte rendu, ce qui vient) : à qui le pilote, au moins en lecture seule (ADR 0133) —
        # et il est au moins personnel : seulement à qui peut l'entendre
        if reads(p, aud, kind, frame) and hearable(p.about, detail_level(p), person, aud.level, aud.witness_level,
                                                   aud.private_ok):
            if p.last_run_at:
                summary = texts.get(p.summary_ref, "")
                since = ago_words(frame.now - p.last_run_at)
                line += "\n  " + (phrase("projects.live.last_run_summary", ago=since, summary=summary[:300]) if summary
                                   else phrase("projects.live.last_run", ago=since))
            nxt = _next_words(p, texts, frame.now, pm)
            if nxt:
                line += f"\n  {nxt}"
            if p.plan_state == c.PROPOSED and texts.get(p.plan_ref):  # son plan, tant qu'il attend (ADR 0145)
                line += "\n  " + phrase("projects.live.plan", plan=clipped(texts[p.plan_ref], 700))
                if texts.get(p.questions_ref):
                    line += "\n  " + phrase("projects.live.questions", questions=clipped(texts[p.questions_ref], 700))
                answering = answering or person == p.asked_by or bool(frame.get(identity_c.IS_OWNER(person)))
            if person and tracker.settles(frame, p, person):
                # un point d'arrêt attend sa validation (ADR 0273) : le jalon, comment elle dit l'avoir rempli, et
                # le commit de l'atelier à ce moment-là
                for o, m in waiting_in(p)[:BREAKPOINTS_SHOWN]:
                    forgotten = phrase("projects.milestones.forgotten")
                    line += "\n  " + phrase(
                        "projects.live.breakpoint", objective=o.id, id=m.id,
                        text=clipped(texts.get(m.text_ref) or forgotten, BREAKPOINT_CLIP),
                        how=clipped(texts.get(m.how_ref) or forgotten, BREAKPOINT_CLIP),
                        commit=phrase("projects.live.breakpoint_commit", sha=m.commit[:12]) if m.commit else "")
                    settling = True
            if any(a != person for a in p.about):
                level = max(level, detail_level(p))
            steering = steering or steerable(p, aud, frame) in c.CHANGES
        waiting = _awaiting(frame, p, person) if owner and person else ""
        if waiting:
            line += f"\n  {waiting}"
        lines.append(line)
        if any(a != person for a in p.about):
            level = max(level, p.sensitivity)
            witness = witness or person in p.about
        if len(lines) >= SHOWN:
            break
    if not lines:
        return None
    # une ligne, seulement en réponse à qui s'occupe d'elle et quand elle voit un projet qu'ils pilotent ensemble :
    # « ajoute une page contact », « mets-le en pause » se font avec l'outil — sinon le projet ne l'entend jamais
    if steering and ep is not None and ep.kind == Kind.REPLY:  # l'outil ne sert qu'en réponse
        lines.append(phrase("projects.live.steer"))
        if answering:  # un plan attend sa réponse : un « vas-y » le lance, une remarque le fait reprendre
            lines.append(phrase("projects.live.plan_steer"))
        if settling:  # un point d'arrêt attend : sa validation le dit atteint, son refus le lui rend avec sa raison
            lines.append(phrase("projects.live.breakpoint_steer"))
    return SectionBody("\n".join(lines), level=level, witness=witness)


def _reviewing(frame: Frame) -> bool:
    """Cette exécution est-elle une relecture indépendante (ADR 0276) ? Elle se conclut par son verdict."""
    ep = frame.episode
    return ep is not None and review_of(ep.attrs.get("subject")) is not None


def _framing(frame: Frame) -> bool:
    """Cette exécution est-elle une séance de cadrage (ADR 0145) ? Elle se conclut par son plan, pas par un verdict."""
    ep = frame.episode
    return ep is not None and frame_of(ep.attrs.get("subject")) is not None


def work_brief(frame: Frame, req: Any) -> str:
    return phrase("projects.frame.brief") if _framing(frame) else phrase("projects.run.brief")


def job_brief(frame: Frame, req: Any) -> str:
    if _reviewing(frame):
        return phrase("projects.review.brief")
    return phrase("projects.frame.job_brief") if _framing(frame) else phrase("projects.run.job_brief")
