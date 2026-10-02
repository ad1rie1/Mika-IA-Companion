"""Ce que les projets montrent à un opérateur (ADR 0031).

- **Projets** (menu) : la liste — mode, état, objectifs, prochaine exécution ;
  toutes les exécutions ; toutes les décisions techniques.
- **La fiche d'un projet** (type d'objet ``project``, clé = son numéro) :
  Vue d'ensemble, Objectifs, Exécutions, Décisions, Fichiers, Dépôt git,
  Comportement et outils, Carnet. La fiche **gouverne** : chaque onglet porte
  les formulaires de ce qu'il montre (``ActionSlot``), les actions qui valent
  pour tout le projet sont en tête.
- **Sur la fiche d'une personne** : les projets qui la concernent.

Lecture seule : les compteurs viennent de la tranche, l'histoire (exécutions,
consignes, notes, opérations, effets) du journal, les fichiers et le dépôt git
du port de l'atelier. Un contenu oublié s'affiche « (oublié) ».
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.actions import (
    BUNDLE_WORDS,
    DECISION_STATUS_FR,
    MODE_CHOICES,
    OBJECTIVE_STATUS_FR,
    PRIORITY_CHOICES,
    SCHEDULES,
    _depositable,
    _editable,
    _remote_ready,
    _runnable,
    pending_of,
)
from mika.faculties.projects.faculty import (
    AMENDED,
    EXTRA_BUNDLES,
    NETWORKED,
    NOTED,
    OPERATIONS,
    PROJECTS,
    Decision,
    Objective,
    Project,
    ProjectsState,
    busy,
    cadence,
    daily_cap,
    live,
    params,
    pick,
    project_at,
    runs_today,
    window_words,
)
from mika.faculties.projects.work import next_run_at, why_not_now
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Code,
    Column,
    Disclosure,
    Download,
    Entry,
    Fields,
    Found,
    Grid,
    Head,
    InspectContext,
    Meter,
    Nav,
    NavItem,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Section,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    Toolbar,
    When,
    paginate,
)
from mika.ports.workshop import OutsideWorkshop, argv_lines
from mika.vocab.episodes import Kind, project_target

PAGE = 25
FORGOTTEN = "(oublié)"
SUMMARY_CLAMP = 260
#: ce qu'on montre d'un fichier ouvert, d'un diff (au-delà : coupé, et dit ; le téléchargement donne tout)
FILE_SHOWN = 60_000
DIFF_SHOWN = 40_000
DOWNLOAD_MAX = 20 * 1024 * 1024
APPROVALS = Ref("local", "/inspecteur/approbations", "ouvrir les approbations")

MODE_FR = {c.PERSONA: "Mika", c.PLAIN: "impersonnel"}
MODE_LONG = dict(MODE_CHOICES)
MODE_TONE = {c.PERSONA: "info", c.PLAIN: "muted"}
STATUS_FR = {c.ACTIVE: "actif", c.PAUSED: "en pause", c.ARCHIVED: "archivé"}
STATUS_TONE = {c.ACTIVE: "ok", c.PAUSED: "warn", c.ARCHIVED: "muted"}
AUTHORITY_FR = {c.USER: "confié", c.SELF: "à elle"}
KIND_FR = {c.ONCE: "ponctuel", c.CONSTANT: "constant"}
KIND_TONE = {c.ONCE: "", c.CONSTANT: "info"}
OBJ_FR = {c.OPEN: "ouvert", c.DONE: "fait", c.BLOCKED: "bloqué", c.DROPPED: "retiré"}
OBJ_TONE = {c.OPEN: "", c.DONE: "ok", c.BLOCKED: "danger", c.DROPPED: "muted"}
#: l'ordre des objectifs : ce qui revient, ce qui reste à faire, ce qui bloque, puis ce qui est fait ou retiré
OBJ_ORDER = {(c.CONSTANT, c.OPEN): 0, (c.ONCE, c.OPEN): 1, (c.ONCE, c.BLOCKED): 2, (c.CONSTANT, c.BLOCKED): 2,
             (c.ONCE, c.DONE): 3}
VERDICT_FR = {c.CONTINUE: "continuer", c.DONE: "fait", c.BLOCKED: "bloqué", c.WAIT: "attendre"}
VERDICT_TONE = {c.CONTINUE: "info", c.DONE: "ok", c.BLOCKED: "danger", c.WAIT: "muted"}
DECISION_FR = {c.IN_FORCE: "en vigueur", c.SUPERSEDED: "remplacée", c.WITHDRAWN: "retirée"}
DECISION_TONE = {c.IN_FORCE: "ok", c.SUPERSEDED: "muted", c.WITHDRAWN: "muted"}
PRIORITY_FR = dict(PRIORITY_CHOICES)
PRIORITY_TONE = {c.LOW: "muted", c.NORMAL: "", c.HIGH: "warn", c.URGENT: "danger"}
OUTCOME_FR = {"done": "fait", "abstained": "abstenue", "superseded": "supplantée", "timeout": "délai dépassé",
              "failed": "échec", "preempted": "préemptée", "interrupted": "interrompue", "cancelled": "annulée"}
OUTCOME_TONE = {"done": "ok", "abstained": "muted", "superseded": "warn", "timeout": "danger", "failed": "danger",
                "preempted": "warn", "interrupted": "warn", "cancelled": "muted"}
AUTHOR_FR = {"operator": "toi", "owner": "sa propriétaire", "self": "elle"}

STATE_PARAM = Param("etat", "État", kind="select", default="vivants",
                    choices=(("vivants", "actifs et en pause"), (c.ACTIVE, "actifs"), (c.PAUSED, "en pause"),
                             (c.ARCHIVED, "archivés"), ("tous", "tous")))
MODE_PARAM = Param("mode", "Mode", kind="select", choices=((c.PERSONA, "Mika"), (c.PLAIN, "impersonnel")))
PROJECT_PARAM = Param("projet", "Projet n°", kind="int", lo=1)
VERDICT_PARAM = Param("verdict", "Verdict", kind="select", choices=tuple(VERDICT_FR.items()))
DECISION_PARAM = Param("statut", "Statut", kind="select", default=c.IN_FORCE,
                       choices=((c.IN_FORCE, "en vigueur"), (c.SUPERSEDED, "remplacées"),
                                (c.WITHDRAWN, "retirées"), ("toutes", "toutes")))


# ── Petits outils ─────────────────────────────────────────────────────────


def _texts(ctx: InspectContext, refs: Iterable[str]) -> Mapping[str, str]:
    wanted = sorted({r for r in refs if r})
    if not wanted or ctx.store is None:
        return {}
    return ctx.store.content(wanted)


def _text(texts: Mapping[str, str], ref: str, empty: str = "—") -> str:
    if not ref:
        return empty
    got = texts.get(ref)
    return got if got is not None else FORGOTTEN


def _said(content: Content | None, empty: str = "—") -> str:
    if content is None:
        return empty
    return content.text if content.text is not None else FORGOTTEN


def _who(frame: Frame, key: str | None) -> str:
    if not key:
        return "—"
    return frame.get(identity_c.IDENTITY(key)).name or key


def _person(frame: Frame, key: str | None) -> Ref | str:
    if not key:
        return "toi (l'opérateur)"
    return Ref.subject("person", frame.get(identity_c.PERSON(key)), _who(frame, key))


def _link(p: Project, title: str = "", tab: str = "") -> Ref:
    return Ref.subject("project", str(p.id), title or f"#{p.id}", tab)


def _mode(p: Project) -> Badge:
    return Badge(MODE_FR.get(p.mode, p.mode), MODE_TONE.get(p.mode, ""))


def _state(p: Project) -> Badge:
    return Badge(STATUS_FR.get(p.status, p.status), STATUS_TONE.get(p.status, ""))


def _priority(p: Project) -> Badge:
    return Badge(f"priorité {PRIORITY_FR.get(p.priority, p.priority)}", PRIORITY_TONE.get(p.priority, ""))


def _progress(p: Project) -> Meter:
    """L'avancement : ses objectifs ponctuels faits sur tous, et combien de constants elle entretient."""
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    done = sum(1 for o in once if o.status == c.DONE)
    blocked = sum(1 for o in p.objectives if o.status == c.BLOCKED)
    constants = sum(1 for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN)
    parts = [f"{done} / {len(once)} ponctuel(s)"] if once else []
    if constants:
        parts.append(f"{constants} constant(s)")
    if blocked:
        parts.append(f"{blocked} bloqué(s)")
    return Meter(done / len(once) if once else 0.0, ", ".join(parts) or "aucun objectif", "warn" if blocked else "")


def _next_words(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext) -> str:
    """La prochaine exécution en mots : quand, ou pourquoi pas."""
    why = why_not_now(p, s, frame)
    if not why:
        return "dès que possible"
    at = next_run_at(p, s, frame) if p.status == c.ACTIVE else None
    if at is not None and at > frame.now and why.startswith(("pas encore", "hors de sa plage", "rien n'est dû")):
        return f"{ctx.when(at)} ({why.split(' : ', 1)[0]})"
    return why


def _host(url: str) -> str:
    return urlsplit(url).hostname or url if url else ""


def _remote_ref(p: Project) -> Ref | str:
    if not p.remote:
        return "aucun"
    shown = re.sub(r"\.git$", "", p.remote.split("://", 1)[-1])
    return Ref.url(re.sub(r"\.git$", "", p.remote), f"{shown} ({p.branch})")


def _subject(s: ProjectsState, ctx: InspectContext) -> Project | Note:
    if not ctx.subject:
        return Note("Cette vue se lit sur la fiche d'un projet (Projets → un projet).", tone="muted")
    p = project_at(s, ctx.subject)
    if p is None:
        return Note(f"Aucun projet « {ctx.subject} ».", tone="warn")
    return p


def _page(ctx: InspectContext, types: Sequence[Any], where: tuple[str, Any] | None,
          cursor: str = "avant") -> tuple[list[Event[Any]], Pager]:
    """Une page du journal (``?<curseur>=`` : la suite, plus ancienne)."""
    found = ctx.events(types, PAGE + 1, where=where, before=ctx.int_param(cursor, 0) or None)
    page = found[:PAGE]
    older = ((cursor, str(page[-1].seq)),) if len(found) > PAGE else ()
    return page, Pager(param=cursor, size=PAGE, older=older)


def _size(n: int) -> str:
    return f"{n} o" if n < 1024 else f"{n / 1024:.1f} Ko" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} Mo"


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n[… coupé à {n} caractères …]"


def _ago(us: int) -> str:
    if us < HOUR:
        return f"{max(1, us // MINUTE)} min"
    if us < 2 * DAY:
        return f"{us // HOUR} h"
    return f"{us // DAY} jours"


def _cadence_words(o: Objective, pm: Any) -> str:
    every = cadence(o, pm)
    words = f"tous les {every // DAY} jours" if every >= 2 * DAY and every % DAY == 0 else \
        f"toutes les {max(1, round(every / HOUR))} h"
    return words + ("" if o.cadence_us else " (par défaut)")


# ── L'objet « projet » ────────────────────────────────────────────────────


@PROJECTS.subject("project", label="Projet", plural="Projets")
def _head(s: ProjectsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    p = project_at(s, key)
    if p is None:
        return None
    texts = _texts(ctx, (p.title_ref,))
    whose = "à elle" if p.authority == c.SELF else f"confié · pour {_who(frame, p.owner) if p.owner else 'toi'}"
    badges = [_mode(p), _state(p), Badge(AUTHORITY_FR.get(p.authority, p.authority))]
    if p.priority != c.NORMAL:
        badges.append(_priority(p))
    if busy(s, p.id):
        badges.append(Badge("au travail", "info"))
    facts: list[tuple[str, Any]] = [
        ("objectifs", _progress(p)),
        ("prochaine exécution", _next_words(p, s, frame, ctx)),
        ("dernière exécution", ctx.when(p.last_run_at) if p.last_run_at else "aucune encore"),
        ("dépôt distant", _host(p.remote) or "aucun"),
    ]
    if p.tried_at > p.last_run_at:  # une tentative depuis, qui n'a pas eu lieu (panne, délai, préemption)
        facts.insert(3, ("dernière tentative", f"{ctx.when(p.tried_at)}, sans suite (crédit rendu)"))
    return Head(str(p.id), _text(texts, p.title_ref, "(sans titre)"),
                subtitle=f"Projet n° {p.id} — mode {MODE_FR.get(p.mode, p.mode)}, {whose}", badges=tuple(badges),
                facts=tuple(facts), default_tab="apercu")


@PROJECTS.search("project")
def _search(s: ProjectsState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    projects = sorted(s.projects.values(), key=lambda p: -p.id)
    texts = _texts(ctx, (p.title_ref for p in projects))
    wanted = text.strip().lower()
    number = wanted.lstrip("#")
    out: list[Found] = []
    skip = max(0, ctx.int_param("_offset", 0))
    for p in projects:
        title = _text(texts, p.title_ref, "(sans titre)")
        if number.isdigit():
            if str(p.id) != number:
                continue
        elif wanted and wanted not in title.lower():
            continue
        if skip:
            skip -= 1
            continue
        out.append(Found(str(p.id), title, f"#{p.id} · {MODE_FR.get(p.mode, p.mode)} · "
                                           f"{STATUS_FR.get(p.status, p.status)}"))
        if len(out) >= limit:
            break
    return out


# ── Projets : la liste ────────────────────────────────────────────────────


def _awaiting(s: ProjectsState, frame: Frame) -> tuple[int, str]:
    """Les projets arrêtés sur un accord de l'opérateur."""
    n = sum(1 for p in s.projects.values() if pending_of(frame, p.id))
    return n, "attendent ton accord"


LIST_COLUMNS = (Column("projet"), Column("mode", "fit"), Column("pour qui"), Column("état", "fit"),
                Column("objectifs"), Column("prochaine exécution"), Column("dernière", "fit"),
                Column("où il en est"),
                Column("priorité", detail=True), Column("plage de travail", detail=True),
                Column("agenda", detail=True), Column("outils", detail=True), Column("dépôt distant", detail=True),
                Column("ce qui sort", detail=True))


def _agenda(rule: str) -> str:
    rule = rule or "manual"
    return next((label for value, label in SCHEDULES if value == rule), rule)


def _tools_words(p: Project) -> str:
    extra = [BUNDLE_WORDS.get(b, b) for b in p.bundles if b in EXTRA_BUNDLES]
    return "son atelier" + (", " + ", ".join(extra) if extra else "")


@PROJECTS.inspect("tous", title="Ses projets", section="projets", order=5, params=[STATE_PARAM, MODE_PARAM],
                  badge=_awaiting,
                  description="Ses espaces de travail : chacun a son dossier et son dépôt git, ses objectifs "
                              "(ponctuels ou constants), ses décisions techniques, un mode (elle, ou impersonnel) "
                              "et ses outils. Une ligne ouvre le projet.")
def _list_view(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    now = frame.now
    pm = params(frame.env.params_of("projects", frame.root))
    every = sorted(s.projects.values(), key=lambda p: (p.status == c.ARCHIVED, p.status == c.PAUSED, -p.id))
    wanted, mode = str(ctx.value("etat") or "vivants"), str(ctx.value("mode") or "")
    shown = [p for p in every if (wanted == "tous" or (wanted == "vivants" and live(p)) or p.status == wanted)
             and (not mode or p.mode == mode)]
    page, pager = paginate(shown, ctx.pager(size=PAGE, total=len(shown)))
    texts = _texts(ctx, [r for p in page for r in (p.title_ref, p.summary_ref)])
    waiting = {p.id for p in s.projects.values() if pending_of(frame, p.id)}
    rows = []
    for p in page:
        rows.append(Row((
            _link(p, _text(texts, p.title_ref, "(sans titre)")), _mode(p),
            "elle" if p.authority == c.SELF and not p.owner else _person(frame, p.owner), _state(p), _progress(p),
            _next_words(p, s, frame, ctx), When(p.last_run_at) if p.last_run_at else "—",
            Text(_text(texts, p.summary_ref, "aucune exécution encore"), clamp=160),
            _priority(p), window_words(p), _agenda(p.schedule), _tools_words(p), _remote_ref(p),
            Badge("avec ton accord", "info") if p.approval else Badge("librement", "warn")),
            href=_link(p), tone="warn" if p.id in waiting else "muted" if p.status == c.ARCHIVED else ""))
    alive = [p for p in every if live(p)]
    open_once = sum(1 for p in alive for o in p.objectives if o.kind == c.ONCE and o.status == c.OPEN)
    constants = sum(1 for p in alive for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN)
    today = sum(runs_today(p, now) for p in every)
    return [
        Stats((
            Stat("Actifs", sum(1 for p in every if p.status == c.ACTIVE),
                 f"{sum(1 for p in alive if busy(s, p.id))} au travail en ce moment"),
            Stat("En pause", sum(1 for p in every if p.status == c.PAUSED), "par toi, ou en panne",
                 "warn" if any(p.status == c.PAUSED for p in every) else ""),
            Stat("Objectifs", open_once, f"ponctuels ouverts · {constants} constant(s)"),
            Stat("Exécutions (24 h)", today, f"{pm.runs_per_hour} par heure au plus, tous projets confondus"),
            Stat("Attendent ton accord", len(waiting), "pour faire sortir quelque chose",
                 "warn" if waiting else "", APPROVALS),
            Stat("Archivés", sum(1 for p in every if p.status == c.ARCHIVED)),
        )),
        Table(LIST_COLUMNS, tuple(rows), title="Projets", pager=pager, filters=("etat", "mode"),
              empty="aucun projet avec ces filtres" if wanted != "vivants" or mode else
              "aucun projet : « Créer un projet » (en haut) en ouvre un — elle peut aussi en ouvrir d'elle-même.",
              caption="Une exécution vise un objectif : celui que tu demandes, sinon le constant le plus en retard, "
                      "sinon le premier ponctuel ouvert. Un projet en mode Mika ne travaille pas pendant son sommeil ; "
                      "un projet impersonnel suit seulement sa plage de travail."),
    ]


RUN_COLUMNS = (Column("quand", "fit"), Column("projet"), Column("objectif"), Column("verdict", "fit"),
               Column("preuve", "fit"), Column("compte rendu"), Column("commit", "fit"),
               Column("mode", "fit", detail=True), Column("outils utilisés", detail=True), Column("épisode", detail=True))


def _proof(verdict: str, proven: bool) -> Any:
    if verdict != c.DONE:
        return "—"
    return Badge("prouvé", "ok") if proven else Badge("sans preuve", "danger")


def _commit_ref(p: Project | None, sha: str) -> Any:
    if not sha:
        return "—"
    if p is None:
        return Text(sha, "mono")
    return Ref("subject", f"project/{p.id}", sha, (("onglet", "git"), ("commit", sha)))


def _objective_words(p: Project | None, oid: int, texts: Mapping[str, str]) -> Any:
    if p is None or not oid:
        return "—"
    o = next((x for x in p.objectives if x.id == oid), None)
    if o is None:
        return f"n° {oid}"
    return Text(f"n° {o.id} · {_text(texts, o.text_ref)}", clamp=90)


@PROJECTS.inspect("toutes_executions", title="Exécutions", section="projets", order=10,
                  params=[PROJECT_PARAM, VERDICT_PARAM],
                  description="Chaque exécution de travail, tous projets confondus : l'objectif visé, le verdict, sa "
                              "preuve, le compte rendu et le commit qu'elle a laissé dans l'atelier.")
def _runs_view(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    project, verdict = ctx.value("projet"), str(ctx.value("verdict") or "")
    if project and verdict:
        found, pager = _both(ctx, project, verdict)
    else:
        where = ("project", project) if project else ("verdict", verdict) if verdict else None
        found, pager = _page(ctx, [c.RUN_REPORTED], where)
    texts = _texts(ctx, [r for e in found for p in (s.projects.get(e.data.project),) if p is not None
                         for r in (p.title_ref, *(o.text_ref for o in p.objectives if o.id == e.data.objective))])
    rows = []
    for e in found:
        d = e.data
        p = s.projects.get(d.project)
        rows.append(Row((
            When(e.at), _link(p, _text(texts, p.title_ref, "(sans titre)")) if p is not None else f"#{d.project}",
            _objective_words(p, d.objective, texts),
            Badge(VERDICT_FR.get(d.verdict, d.verdict), VERDICT_TONE.get(d.verdict, "")), _proof(d.verdict, d.proven),
            Text(_said(d.summary), clamp=SUMMARY_CLAMP), _commit_ref(p, d.commit), MODE_FR.get(d.mode, d.mode),
            ", ".join(d.tools) or "—", Ref("episode", e.correlation, "prompt, outils, appels")),
            href=Ref("episode", e.correlation, "")))
    running = [(r, s.projects.get(r.project)) for r in s.running.values() if r.purpose == "run"]
    blocks: list[Block] = []
    if running:
        names = _texts(ctx, (p.title_ref for _, p in running if p is not None))
        blocks.append(Note("En ce moment : " + ", ".join(
            f"« {_text(names, p.title_ref, '(sans titre)')} »" for _, p in running if p is not None) + ".", "info"))
    blocks.append(Table(RUN_COLUMNS, tuple(rows), title="Les exécutions", pager=pager, filters=("projet", "verdict"),
                        empty="aucune exécution avec ces filtres" if project or verdict else "aucune exécution encore"))
    return blocks


#: deux filtres : le journal en filtre un, on lit par lots pour l'autre jusqu'à remplir la page
SCAN, SCAN_BATCHES = 200, 10


def _both(ctx: InspectContext, project: int, verdict: str) -> tuple[list[Event[Any]], Pager]:
    """Les comptes rendus d'un projet avec ce verdict, une page pleine (ou le journal épuisé, ou dit)."""
    cursor = ctx.int_param("avant", 0) or None
    shown: list[Event[Any]] = []
    for _ in range(SCAN_BATCHES):
        batch = ctx.events([c.RUN_REPORTED], SCAN, where=("project", project), before=cursor)
        for e in batch:
            cursor = e.seq
            if e.data.verdict == verdict:
                shown.append(e)
                if len(shown) > PAGE:
                    return shown[:PAGE], Pager(param="avant", size=PAGE, older=(("avant", str(shown[PAGE - 1].seq)),))
        if len(batch) < SCAN:
            return shown, Pager(param="avant", size=PAGE)
    return shown, Pager(param="avant", size=PAGE, older=(("avant", str(cursor)),) if cursor else ())


DECISION_COLUMNS = (Column("projet"), Column("n°", "fit"), Column("la question"), Column("ce qui est choisi"),
                    Column("statut", "fit"), Column("posée par", "fit"), Column("quand", "fit"),
                    Column("pourquoi", detail=True))


@PROJECTS.inspect("toutes_decisions", title="Décisions techniques", section="projets", order=20,
                  params=[PROJECT_PARAM, DECISION_PARAM],
                  description="Ce qui a été tranché dans ses projets, et pourquoi : elle relit les décisions en "
                              "vigueur à chaque exécution et ne rouvre pas un débat sans remplacer la décision.")
def _decisions_view(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    project, wanted = ctx.value("projet"), str(ctx.value("statut") or c.IN_FORCE)
    every = [(p, d) for p in sorted(s.projects.values(), key=lambda p: -p.id) if not project or p.id == project
             for d in reversed(p.decisions) if wanted == "toutes" or d.status == wanted]
    page, pager = paginate(every, ctx.pager(size=PAGE, total=len(every)))
    texts = _texts(ctx, [r for p, d in page for r in (p.title_ref, d.title_ref, d.choice_ref, d.reason_ref)])
    rows = [Row((_decisions_ref(p, _text(texts, p.title_ref, "(sans titre)")), f"D{d.id}",
                 Text(_text(texts, d.title_ref), clamp=120), Text(_text(texts, d.choice_ref), clamp=220),
                 _decision_badge(d), AUTHOR_FR.get(d.author, d.author), When(d.at),
                 Text(_text(texts, d.reason_ref), clamp=400)), href=_decisions_ref(p, ""))
            for p, d in page]
    return [Table(DECISION_COLUMNS, tuple(rows), title="Décisions techniques", pager=pager,
                  filters=("projet", "statut"), empty="aucune décision avec ces filtres")]


def _decisions_ref(p: Project, text: str) -> Ref:
    """L'onglet Décisions du projet, toutes montrées (une décision remplacée ou retirée s'y retrouve)."""
    return Ref("subject", f"project/{p.id}", text, (("onglet", "decisions"), ("statut", "toutes")))


def _decision_badge(d: Decision) -> Badge:
    if d.status == c.SUPERSEDED and d.replaced_by:
        return Badge(f"remplacée par D{d.replaced_by}", "muted")
    return Badge(DECISION_FR.get(d.status, d.status), DECISION_TONE.get(d.status, ""))


# ── La fiche : vue d'ensemble ─────────────────────────────────────────────


def _state_notes(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    out: list[Block] = []
    if p.status == c.ARCHIVED:
        out.append(Note(f"Archivé le {ctx.when(p.archived_at)} : il ne travaille plus. « Restaurer » (en haut) le "
                        "ramène, en pause.", "muted"))
    elif p.status == c.PAUSED:
        why = f" ({p.pause_reason})" if p.pause_reason else ""
        out.append(Note(f"En pause depuis le {ctx.when(p.paused_at)}{why} : aucune exécution jusqu'à ce que tu le "
                        "reprennes (« Reprendre », en haut).", "warn"))
    if p.status != c.ARCHIVED and not any(o.status == c.OPEN for o in p.objectives):
        out.append(Note("Aucun objectif ouvert : il n'a rien à faire. Ajoutes-en un (onglet Objectifs).", "warn"))
    if busy(s, p.id):
        out.append(Note("Elle y travaille en ce moment.", "info"))
    return out


def exact(s: ProjectsState, proposal: int) -> str:
    """Une commande réseau qui attend un accord, telle qu'elle partira : entière, un argument par ligne (vide :
    ce n'en est pas une). L'aperçu complet (avec l'état de l'atelier, épinglé par l'accord) est sur la page
    Approbations."""
    raw = s.awaiting.get(proposal)
    got = s.proposals.get(proposal)
    if raw is None or got is None or got[1] != NETWORKED:
        return ""
    try:
        argv = json.loads(raw).get("argv") or []
    except (ValueError, AttributeError):
        return ""
    return argv_lines([str(a) for a in argv])


def decide_bar(key: str, argv: str) -> list[Any]:
    """Les boutons d'une demande : la commande exacte d'abord (quand c'en est une), puis approuver ou refuser."""
    out: list[Any] = [Code(argv, title="La commande, entière, un argument par ligne")] if argv else []
    out.append(Toolbar((ActionSlot("projects.approuver", (("proposal", key),), title="Approuver",
                                   presentation="button"),
                        ActionSlot("projects.refuser", (("proposal", key),), title="Refuser", presentation="button")),
                       title=f"Décider de la demande n° {key}"))
    return out


def _approvals(p: Project, s: ProjectsState, frame: Frame, texts: Mapping[str, str]) -> Section | None:
    pending = pending_of(frame, p.id)
    if not pending:
        return None
    items: list[Any] = []
    for v in pending:
        key = str(v.proposal)
        argv = exact(s, v.proposal)
        summary = _text(texts, v.summary_ref, "(sans résumé)")
        items.append(Fields(((f"demande n° {key}", Text(summary) if argv else Text(summary, clamp=600)),
                             ("ce que c'est", {f"{c.OWNER}.push": "pousser vers le dépôt distant",
                                               f"{c.OWNER}.pull": "récupérer du dépôt distant"}.get(
                                 v.capability, "une commande avec le réseau"))), columns=1))
        items += decide_bar(key, argv)
    return Section(f"À décider ({len(pending)})", tuple(items),
                   description="Ce qu'elle veut faire sortir de la machine : rien ne part sans ton accord. Ce qui est "
                               "montré est ce qui partira ; ses raisons sont ses mots, pas une description de la "
                               "commande.")


@PROJECTS.inspect("apercu", title="Vue d'ensemble", subject="project", order=10,
                  description="Où en est le projet : ce qui attend ta décision, son avancement, sa prochaine exécution, "
                              "son dépôt, ses objectifs, ses dernières exécutions et ses décisions en vigueur.")
def _overview(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    pm = params(frame.env.params_of("projects", frame.root))
    pending = pending_of(frame, p.id)
    decisions = [d for d in p.decisions if d.status == c.IN_FORCE][-5:]
    texts = _texts(ctx, [p.description_ref, p.summary_ref, *(o.text_ref for o in p.objectives),
                         *(r for d in decisions for r in (d.title_ref, d.choice_ref)),
                         *(v.summary_ref for v in pending)])
    blocks: list[Block] = [*_state_notes(p, s, frame, ctx)]
    approvals = _approvals(p, s, frame, texts)
    if approvals is not None:
        blocks.append(approvals)
    target = pick(p, frame.now, pm) if p.status == c.ACTIVE else None
    blocks.append(Grid((
        Fields((("état", _state(p)), ("objectifs", _progress(p)),
                ("exécutions", f"{p.runs} en tout · {runs_today(p, frame.now)} sur 24 h (au plus {daily_cap(p, pm)})"),
                ("pannes d'affilée", Badge(str(p.failures), "danger") if p.failures else "aucune")),
               title="Où il en est"),
        Fields((("quand", _next_words(p, s, frame, ctx)),
                ("sur quoi", Text(f"n° {target.id} · {_text(texts, target.text_ref)}", clamp=80)
                 if target is not None else "—"),
                ("mode", _mode(p)), ("plage de travail", window_words(p))),
               title="Prochaine exécution"),
        Fields((("dernier commit", _commit_ref(p, p.last_commit) if p.last_commit else "aucun encore"),
                ("dépôt distant", _remote_ref(p)),
                ("dernier échange", Text(p.remote_line, tone="ok" if p.remote_ok else "danger", clamp=90)
                 if p.remote_line else "aucun"),
                ("l'histoire complète", _link(p, "onglet Dépôt git", "git"))),
               title="Son dépôt"),
    ), columns=3))
    blocks.append(Prose(_text(texts, p.description_ref), title="Le cadre") if p.description_ref
                  else Note("Aucun cadre écrit : elle suit le titre, ses objectifs et les consignes.", "muted"))
    if p.status != c.ARCHIVED:
        blocks.append(Fields((("changer son cadre, son mode, son rythme",
                               _link(p, "dans l'onglet Comportement et outils", "comportement")),)))
    open_rows = []
    for o in sorted(p.objectives, key=lambda o: (OBJ_ORDER.get((o.kind, o.status), 9), o.id)):
        if o.status == c.DROPPED:
            continue
        open_rows.append(Row((o.id, Text(_text(texts, o.text_ref), clamp=160),
                              Badge(KIND_FR.get(o.kind, o.kind), KIND_TONE.get(o.kind, "")),
                              Badge(OBJ_FR.get(o.status, o.status), OBJ_TONE.get(o.status, "")),
                              _last_words(o, frame.now, pm)), href=_link(p, tab="objectifs")))
    blocks.append(Table((Column("n°", "fit"), Column("objectif"), Column("sorte", "fit"), Column("état", "fit"),
                         Column("dernier passage")), tuple(open_rows[:8]), title="Ses objectifs",
                        empty="aucun objectif : ajoutes-en un (onglet Objectifs)",
                        caption="Tous les objectifs, leur cadence et leurs boutons : onglet Objectifs."
                        if len(open_rows) > 8 else ""))
    recent = ctx.events([c.RUN_REPORTED], 5, where=("project", p.id))
    blocks.append(Timeline(tuple(
        Entry(e.at, f"{VERDICT_FR.get(e.data.verdict, e.data.verdict)} — objectif n° {e.data.objective}"
              if e.data.objective else VERDICT_FR.get(e.data.verdict, e.data.verdict),
              _said(e.data.summary), tone=VERDICT_TONE.get(e.data.verdict, ""),
              meta=f"commit {e.data.commit}" if e.data.commit else "", href=Ref("episode", e.correlation, ""))
        for e in recent), title="Dernières exécutions", empty="aucune exécution encore"))
    if decisions:
        blocks.append(Table((Column("n°", "fit"), Column("la question"), Column("ce qui est choisi")), tuple(
            Row((f"D{d.id}", Text(_text(texts, d.title_ref), clamp=100), Text(_text(texts, d.choice_ref), clamp=200)),
                href=_link(p, tab="decisions")) for d in reversed(decisions)),
            title="Décisions en vigueur (les dernières)"))
    return blocks


def _last_words(o: Objective, now: int, pm: Any) -> str:
    if o.kind == c.CONSTANT and o.status != c.OPEN:
        return "mis de côté : rouvre-le pour qu'il revienne"
    if o.kind == c.CONSTANT:
        last = f"il y a {_ago(now - o.passed_at)}" if o.passed_at else "jamais encore"
        return f"{last} · revient {_cadence_words(o, pm)}"
    if o.status == c.DONE and o.closed_at:
        return f"fait il y a {_ago(now - o.closed_at)}"
    if o.last_run_at:
        return f"{o.runs} exécution(s), la dernière il y a {_ago(now - o.last_run_at)}"
    return "pas encore travaillé"


# ── La fiche : objectifs ──────────────────────────────────────────────────


OBJECTIVE_COLUMNS = (Column("n°", "fit"), Column("objectif"), Column("sorte", "fit"), Column("état", "fit"),
                     Column("rythme"), Column("exécutions", "num"), Column("dernier compte rendu"),
                     Column("posé par", "fit", detail=True))


@PROJECTS.inspect("objectifs", title="Objectifs", subject="project", order=20,
                  description="Ce que le projet cherche, ligne par ligne : un objectif ponctuel se coche une fois (avec "
                              "une preuve), un objectif constant revient selon sa cadence. Déplie une ligne pour la "
                              "lancer, la modifier ou changer son statut.")
def _objectives_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    pm = params(frame.env.params_of("projects", frame.root))
    key = str(p.id)
    editable = _editable(s, frame, key)
    runnable = _runnable(s, frame, key)
    texts = _texts(ctx, [r for o in p.objectives for r in (o.text_ref, o.note_ref, o.result_ref)])
    rows = []
    for o in sorted(p.objectives, key=lambda o: (OBJ_ORDER.get((o.kind, o.status), 9), o.id)):
        text = _text(texts, o.text_ref)
        detail: list[Any] = []
        if o.result_ref:
            detail.append(Prose(_text(texts, o.result_ref), title="Ce qu'elle en a tiré"))
        if editable:
            moves = [st for st in c.OBJECTIVE_STATUSES if st != o.status and not (o.kind == c.CONSTANT and st == c.DONE)]
            buttons: list[Any] = [ActionSlot("projects.objectif_statut", (("objective", str(o.id)), ("status", st)),
                                             title={c.OPEN: "Rouvrir", c.DONE: "Marquer fait", c.BLOCKED: "Marquer bloqué",
                                                    c.DROPPED: "Retirer"}[st], presentation="button")
                                  for st in moves]
            if runnable and o.status == c.OPEN:
                buttons.insert(0, ActionSlot("projects.lancer_objectif", (("objective", str(o.id)),),
                                             title="Lancer maintenant", presentation="button"))
            detail.append(Toolbar(tuple(buttons), title="Cet objectif"))
            detail.append(Disclosure("Modifier l'objectif", (ActionSlot("projects.objectif_modifier", (
                ("objective", str(o.id)), ("text", texts.get(o.text_ref, "")), ("kind", o.kind),
                ("cadence_hours", str(o.cadence_us // HOUR))), title="Modifier l'objectif", compact=True),)))
        rhythm = _last_words(o, frame.now, pm)
        if o.waiting_until > frame.now:
            rhythm = f"en attente jusqu'à {ctx.when(o.waiting_until)}"
        rows.append(Row((o.id, Text(text, clamp=300), Badge(KIND_FR.get(o.kind, o.kind), KIND_TONE.get(o.kind, "")),
                         Badge(OBJ_FR.get(o.status, o.status), OBJ_TONE.get(o.status, "")), rhythm, o.runs,
                         Text(_text(texts, o.note_ref, "—"), clamp=220), AUTHOR_FR.get(o.author, o.author)),
                        detail=tuple(detail),
                        tone="danger" if o.status == c.BLOCKED else "muted" if o.status == c.DROPPED else ""))
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    out: list[Block] = [
        Stats((Stat("Ponctuels faits", f"{sum(1 for o in once if o.status == c.DONE)} / {len(once)}"),
               Stat("Constants", sum(1 for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN),
                    "ils reviennent selon leur cadence"),
               Stat("Bloqués", sum(1 for o in p.objectives if o.status == c.BLOCKED), "",
                    "danger" if any(o.status == c.BLOCKED for o in p.objectives) else ""))),
        Table(OBJECTIVE_COLUMNS, tuple(rows), title="Ses objectifs",
              empty="aucun objectif : ajoutes-en un ci-dessous",
              caption=f"Une exécution vise un objectif : celui que tu lances, sinon le constant le plus en retard, sinon "
                      f"le premier ponctuel ouvert. Un ponctuel qui n'est pas fait après {pm.once_runs_max} exécutions "
                      f"bloque ; un objectif qui n'a rien conclu {pm.silent_before_blocked} fois de suite aussi."),
    ]
    if editable:
        out.append(Section("Ajouter un objectif", (ActionSlot("projects.objectif_ajouter", title="Ajouter un objectif",
                                                              compact=True),),
                           description="Ponctuel : à faire une fois (« Créer un module RDP »). Constant : à entretenir, "
                                       "il revient selon sa cadence (« Améliorer la sécurité »)."))
    return out


# ── La fiche : exécutions ─────────────────────────────────────────────────


def _started(p: Project, ctx: InspectContext) -> tuple[list[Event[Any]], Pager]:
    """Une page des épisodes de ce projet : ses exécutions (qui le visent) et ses récits (qui portent sur lui)."""
    before = ctx.int_param("avant", 0) or None
    found = ctx.events([rt.EPISODE_STARTED], PAGE + 1, where=("target", project_target(p.id)), before=before)
    page = found[:PAGE]
    older = (("avant", str(page[-1].seq)),) if len(found) > PAGE else ()
    return page, Pager(param="avant", size=PAGE, older=older)


@PROJECTS.inspect("executions", title="Exécutions", subject="project", order=30,
                  description="Chaque exécution de travail : son objectif, son issue, son verdict et sa preuve, le "
                              "commit qu'elle a laissé, sa durée — et de quoi relire le prompt exact, les outils "
                              "appelés, les appels de modèle et la décision.")
def _runs_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    pm = params(frame.env.params_of("projects", frame.root))
    started, pager = _started(p, ctx)
    corrs = [e.correlation for e in started]
    ended = {e.correlation: e for e in ctx.events([rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    reports = {e.correlation: e.data for e in ctx.events([c.RUN_REPORTED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    texts = _texts(ctx, (o.text_ref for o in p.objectives))
    rows = []
    for e in started:
        end = ended.get(e.correlation)
        report = reports.get(e.correlation)
        outcome = str(end.data.outcome) if end is not None else ""
        issue = Badge(OUTCOME_FR.get(outcome, outcome), OUTCOME_TONE.get(outcome, "")) if outcome else \
            Badge("en cours", "info")
        duration = f"{max(1, (end.at - e.at) // 1_000_000)} s" if end is not None else "—"
        verdict: Any = Badge(VERDICT_FR.get(report.verdict, report.verdict), VERDICT_TONE.get(report.verdict, "")) \
            if report is not None else "—"
        oid = report.objective if report is not None else _objective_id(e.data.subject)
        rows.append(Row((
            When(e.at), "Mika" if e.data.kind == Kind.WORK else "impersonnel", _objective_words(p, oid, texts), issue,
            verdict, _proof(report.verdict, report.proven) if report is not None else "—",
            Text(_said(report.summary), clamp=SUMMARY_CLAMP) if report is not None else "—",
            _commit_ref(p, report.commit) if report is not None else "—", duration,
            ", ".join(report.tools) if report is not None and report.tools else "—",
            Ref("episode", e.correlation, "prompt", (("onglet", "prompt"),)),
            Ref("episode", e.correlation, "outils", (("onglet", "outils"),)),
            Ref("episode", e.correlation, "appels", (("onglet", "appels"),)),
            Ref("episode", e.correlation, "décision", (("onglet", "decision"),))),
            href=Ref("episode", e.correlation, ""), tone="danger" if outcome in ("failed", "timeout") else ""))
    return [
        Stats((Stat("Exécutions", p.runs, "en tout (une panne rend son crédit)"),
               Stat("Sur 24 h", f"{runs_today(p, frame.now)} / {daily_cap(p, pm)}", "son plafond du jour"),
               Stat("Pannes d'affilée", p.failures, f"en pause à {pm.failures_before_pause}",
                    "danger" if p.failures else ""),
               Stat("Dernière", When(p.last_run_at) if p.last_run_at else "aucune"))),
        Table((Column("quand", "fit"), Column("mode", "fit"), Column("objectif"), Column("issue", "fit"),
               Column("verdict", "fit"), Column("preuve", "fit"), Column("compte rendu"), Column("commit", "fit"),
               Column("durée", "num"), Column("outils utilisés", detail=True), Column("prompt", detail=True),
               Column("outils", detail=True), Column("appels", detail=True), Column("décision", detail=True)),
              tuple(rows), title="Ses exécutions", pager=pager, empty="aucune exécution encore",
              caption="« prompt » : ce qu'elle a vraiment reçu (le projet, ses objectifs, ses décisions) et ce qu'elle "
                      "a répondu ; « outils » : chaque appel et son résultat ; « décision » : pourquoi à ce moment-là."),
    ]


def _objective_id(subject: str | None) -> int:
    if subject and subject.startswith("objective:"):
        tail = subject.rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else 0
    return 0


# ── La fiche : décisions ──────────────────────────────────────────────────


@PROJECTS.inspect("decisions", title="Décisions", subject="project", order=40, params=[DECISION_PARAM],
                  description="Les décisions techniques du projet : ce qui est choisi, pourquoi, et ce que chaque "
                              "décision remplace. Elle relit celles en vigueur à chaque exécution.")
def _decisions_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    wanted = str(ctx.value("statut") or c.IN_FORCE)
    chosen = [d for d in reversed(p.decisions) if wanted == "toutes" or d.status == wanted]
    page, pager = paginate(chosen, ctx.pager(size=PAGE, total=len(chosen)))
    texts = _texts(ctx, [r for d in page for r in (d.title_ref, d.choice_ref, d.context_ref, d.options_ref,
                                                   d.reason_ref)])
    editable = _editable(s, frame, str(p.id))
    rows = []
    for d in page:
        detail: list[Any] = [Fields((
            ("le contexte", Text(_text(texts, d.context_ref), clamp=800)),
            ("les options envisagées", Text(_text(texts, d.options_ref), clamp=800)),
            ("pourquoi", Text(_text(texts, d.reason_ref), clamp=800)),
            ("remplace", f"D{d.replaces}" if d.replaces else "—"),
            ("pendant l'objectif", f"n° {d.objective}" if d.objective else "—")), columns=1)]
        if editable and d.status != c.SUPERSEDED:
            target = c.WITHDRAWN if d.status == c.IN_FORCE else c.IN_FORCE
            detail.append(Toolbar((ActionSlot("projects.decision_statut", (("decision", str(d.id)), ("status", target)),
                                              title="Retirer" if target == c.WITHDRAWN else "Remettre en vigueur",
                                              presentation="button"),), title="Cette décision"))
        if editable and d.status == c.IN_FORCE:
            detail.append(Disclosure("Remplacer cette décision", (ActionSlot("projects.decision_ajouter", (
                ("title", texts.get(d.title_ref, "")), ("replaces", str(d.id))), title="Remplacer", compact=True),)))
        rows.append(Row((f"D{d.id}", Text(_text(texts, d.title_ref), clamp=140),
                         Text(_text(texts, d.choice_ref), clamp=300), _decision_badge(d),
                         AUTHOR_FR.get(d.author, d.author), When(d.at)), detail=tuple(detail),
                        tone="muted" if d.status != c.IN_FORCE else ""))
    out: list[Block] = [
        Table((Column("n°", "fit"), Column("la question"), Column("ce qui est choisi"), Column("statut", "fit"),
               Column("posée par", "fit"), Column("quand", "fit")), tuple(rows),
              title=f"Ses décisions ({sum(1 for d in p.decisions if d.status == c.IN_FORCE)} en vigueur)",
              pager=pager, filters=("statut",),
              empty="aucune décision avec ce filtre" if wanted != c.IN_FORCE else
              "aucune décision encore : elle en consigne pendant ses exécutions, et toi ici"),
    ]
    if editable:
        out.append(Section("Consigner une décision", (ActionSlot("projects.decision_ajouter",
                                                                 title="Consigner une décision", compact=True),),
                           description="La question tranchée, ce qui est choisi et pourquoi. Pour revenir sur une "
                                       "décision, déplie-la et remplace-la : l'ancienne reste lisible, remplacée."))
    return out


# ── La fiche : fichiers ───────────────────────────────────────────────────


_TREE_LINE = re.compile(r"^(?P<path>.+) \((?P<size>\d+) o\)$")


def _download_link(project: int, path: str) -> Ref:
    return Ref("local", f"/inspecteur/telecharger/project/{project}", "télécharger", (("fichier", path),))


def _folder_ref(p: Project, folder: str, text: str) -> Ref:
    params: tuple[tuple[str, str], ...] = (("onglet", "fichiers"),) + ((("dossier", folder),) if folder else ())
    return Ref("subject", f"project/{p.id}", text, params)


def _file_ref(p: Project, path: str, text: str) -> Ref:
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    params = (("onglet", "fichiers"), *((("dossier", folder),) if folder else ()), ("fichier", path))
    return Ref("subject", f"project/{p.id}", text, params)


def _listing(tree: list[str], folder: str) -> tuple[list[tuple[str, int, int]], list[tuple[str, int]]]:
    """Les sous-dossiers (nom, fichiers, octets) et les fichiers (chemin, octets) directement dans ``folder``."""
    prefix = f"{folder}/" if folder else ""
    dirs: dict[str, list[int]] = {}
    files: list[tuple[str, int]] = []
    for line in tree:
        m = _TREE_LINE.match(line)
        if m is None or not m.group("path").startswith(prefix):
            continue
        rest = m.group("path")[len(prefix):]
        size = int(m.group("size"))
        if "/" in rest:
            name = rest.split("/", 1)[0]
            entry = dirs.setdefault(name, [0, 0])
            entry[0] += 1
            entry[1] += size
        else:
            files.append((m.group("path"), size))
    return [(n, v[0], v[1]) for n, v in sorted(dirs.items())], sorted(files)


@PROJECTS.inspect("fichiers", title="Fichiers", subject="project", order=50,
                  description="Le dossier du projet, à parcourir : un dossier s'ouvre, un fichier se lit ici ou se "
                              "télécharge ; tu peux y déposer un fichier pour elle.")
async def _files_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    port = ctx.ports.get("workshop")
    if port is None:
        return [Note("L'atelier n'est pas disponible ici (aucun port d'atelier).", tone="warn")]
    deposit = [Disclosure("Déposer un fichier dans l'atelier", (
        ActionSlot("projects.deposer", title="Déposer un fichier", compact=True),))] \
        if _depositable(s, frame, str(p.id), ctx.ports) else []
    if not port.exists(p.id):
        return [Note("L'atelier n'est pas encore ouvert : aucune exécution n'y a encore écrit.", tone="muted"), *deposit]
    folder = ctx.param("dossier").strip("/")
    if ".." in folder.split("/"):
        folder = ""
    tree = await port.tree(p.id, folder or ".")
    cut = [line for line in tree if line.startswith("[")]
    tree = [line for line in tree if not line.startswith("[")]
    dirs, files = _listing(tree, folder)
    crumbs = [NavItem("racine", _folder_ref(p, "", "racine"), active=not folder)]
    acc = ""
    for part in [x for x in folder.split("/") if x]:
        acc = f"{acc}/{part}" if acc else part
        crumbs.append(NavItem(part, _folder_ref(p, acc, part), active=acc == folder))
    rows: list[Any] = [Row((_folder_ref(p, f"{folder}/{name}" if folder else name, f"{name}/"),
                            Badge("dossier", "info"), f"{count} fichier(s)", _size(size), ""),
                           href=_folder_ref(p, f"{folder}/{name}" if folder else name, ""))
                       for name, count, size in dirs]
    rows += [Row((_file_ref(p, path, path.rsplit("/", 1)[-1]), Badge("fichier"), "", _size(size),
                  _download_link(p.id, path))) for path, size in files]
    total = sum(int(m.group("size")) for m in (_TREE_LINE.match(x) for x in tree) if m is not None)
    opened = await _opened_file(p, port, ctx.param("fichier"))
    where = f"dans /{folder}" if folder else "dans l'atelier"
    notes = [Note(f"Plus de {len(tree)} fichiers {where} : la liste est coupée — ouvre un sous-dossier pour voir "
                  "la suite.", "warn")] if cut else []
    return [
        *opened,
        Nav(tuple(crumbs), title="Dossier"),
        *notes,
        Table((Column("nom"), Column("sorte", "fit"), Column("contenu", "fit"), Column("taille", "num"),
               Column("télécharger", "fit")), tuple(rows), title=f"/{folder}" if folder else "Le dossier du projet",
              empty="ce dossier est vide",
              caption=f"{len(tree)} fichier(s) {where}, {_size(total)} en tout. Un nom ouvre le fichier ici ; "
                      "« télécharger » le rapatrie tel quel."),
        *deposit,
    ]


async def _opened_file(p: Project, port: Any, path: str) -> list[Block]:
    if not path:
        return []
    try:
        text = await port.read(p.id, path)
    except (OutsideWorkshop, FileNotFoundError, OSError, ValueError) as exc:
        return [Note(f"« {path} » ne s'ouvre pas : {exc}", "warn")]
    if "\x00" in text or text.count("�") > max(8, len(text) // 50):
        return [Note(f"« {path} » n'est pas un texte : télécharge-le.", "muted"),
                Fields((("télécharger", _download_link(p.id, path)),))]
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    lang = "diff" if path.endswith((".diff", ".patch")) else ""
    return [Code(_cut(text, FILE_SHOWN), title=path, lang=lang),
            Fields((("fichier", Text(path, "mono")), ("télécharger", _download_link(p.id, path)),
                    ("fermer", _folder_ref(p, folder, "revenir au dossier"))), columns=3)]


@PROJECTS.download("project")
async def _download(s: ProjectsState, frame: Frame, ctx: InspectContext, key: str, name: str) -> Download | Note:
    """Un fichier de l'atelier, tel quel."""
    p = project_at(s, key)
    port = ctx.ports.get("workshop")
    if p is None or port is None or not port.exists(p.id):
        return Note("Ce fichier n'est pas disponible.", tone="warn")
    try:
        data = await port.read_bytes(p.id, name, DOWNLOAD_MAX + 1)
    except (OutsideWorkshop, FileNotFoundError, OSError, ValueError):
        return Note("Ce fichier n'est pas (ou plus) dans l'atelier.", tone="warn")
    if len(data) > DOWNLOAD_MAX:
        return Note(f"Trop gros pour la console ({DOWNLOAD_MAX // (1024 * 1024)} Mo au plus).", tone="warn")
    return Download(name.rsplit("/", 1)[-1], data)


# ── La fiche : dépôt git ──────────────────────────────────────────────────


@PROJECTS.inspect("git", title="Dépôt git", subject="project", order=60,
                  description="L'histoire du projet : un enregistrement par exécution qui a changé quelque chose, chacun "
                              "lisible en diff ; ce qui n'est pas encore enregistré ; et son dépôt distant (GitHub ou "
                              "un autre hôte), où pousser et d'où récupérer.")
async def _git_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    port = ctx.ports.get("workshop")
    blocks: list[Block] = []
    remote = _remote_section(p, s, frame, ctx)
    if port is None or not port.exists(p.id):
        return [Note("Pas encore de dépôt : il s'ouvre à la première exécution qui écrit (ou au premier dépôt de "
                     "fichier, ou en récupérant le dépôt distant).", "muted"), remote]
    sha = ctx.param("commit")
    if sha:
        shown = await port.show(p.id, sha)
        blocks.append(Section(f"L'enregistrement {sha}", (
            Code(_cut(shown, DIFF_SHOWN), title="Message et changements", lang="diff") if shown
            else Note(f"Aucun enregistrement « {sha} » dans ce dépôt.", "warn"),
            Fields((("fermer", Ref("subject", f"project/{p.id}", "revenir à l'historique", (("onglet", "git"),))),)))))
    count = await port.count(p.id)
    pager = ctx.pager("page_commits", size=PAGE, total=count)
    commits = await port.commits(p.id, pager.size, offset=pager.offset)
    latest = commits[:1] if pager.offset == 0 else await port.commits(p.id, 1)
    diff = await port.diff(p.id)
    changed = len(await port.pending(p.id))
    runs = {e.data.commit: e for e in ctx.events([c.RUN_REPORTED], 1000, where=("project", p.id)) if e.data.commit}
    rows = []
    for k in commits:
        run = runs.get(k.sha)
        rows.append(Row((
            Ref("subject", f"project/{p.id}", k.sha, (("onglet", "git"), ("commit", k.sha))), Text(k.title, clamp=120),
            When(k.at) if k.at else "—", k.author or "—", k.files,
            Text(f"+{k.insertions} −{k.deletions}", "mono"),
            Ref("episode", run.correlation, "exécution") if run is not None else
            ("amorce" if k.title == "atelier ouvert" else "—")),
            href=Ref("subject", f"project/{p.id}", "", (("onglet", "git"), ("commit", k.sha)))))
    blocks += [
        Stats((Stat("Enregistrements", count), Stat("Le dernier", When(latest[0].at) if latest and latest[0].at
                                                     else "—", latest[0].sha if latest else ""),
               Stat("Non enregistré", f"{changed} fichier(s)" if changed else "rien", "",
                    "warn" if changed else ""),
               Stat("Dépôt distant", _host(p.remote) or "aucun", p.branch if p.remote else "",
                    "" if p.remote else "muted"))),
        Disclosure(f"Ce qui n'est pas encore enregistré ({changed} fichier(s))", (
            Code(_cut(diff, DIFF_SHOWN), title="Changements depuis le dernier enregistrement", lang="diff"),),
            open=bool(changed)) if diff.strip() or changed else
        Note("Tout est enregistré : rien de changé depuis le dernier commit.", "muted"),
        Table((Column("commit", "fit"), Column("message"), Column("quand", "fit"), Column("auteur", "fit"),
               Column("fichiers", "num"), Column("lignes", "fit"), Column("exécution", "fit")), tuple(rows),
              title="Historique", pager=pager, empty="aucun enregistrement encore",
              caption="Un commit s'ouvre en diff coloré. Chaque exécution qui change quelque chose laisse un commit, "
                      "qu'on retrouve dans son compte rendu."),
        remote,
    ]
    return blocks


def _remote_section(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext) -> Section:
    key = str(p.id)
    items: list[Any] = [Fields((
        ("adresse", _remote_ref(p)), ("branche", p.branch if p.remote else "—"),
        ("envoi automatique", "après chaque exécution qui enregistre quelque chose" if p.auto_push else "non"),
        ("ce qui part", "avec ton accord" if p.approval else "sans accord (réglé ainsi)"),
        ("dernier échange", Text(p.remote_line, tone="ok" if p.remote_ok else "danger", clamp=300)
         if p.remote_line else "aucun encore"),
        ("quand", When(p.remote_at) if p.remote_at else "—")), columns=2)]
    if _remote_ready(s, frame, key, ctx.ports):
        items.append(Toolbar((ActionSlot("projects.pousser", title="Pousser maintenant", presentation="button"),
                              ActionSlot("projects.recuperer", title="Récupérer", presentation="button")),
                             title="Maintenant"))
    if _editable(s, frame, key):
        items.append(Disclosure("Régler le dépôt distant", (
            ActionSlot("projects.depot_distant", title="Enregistrer le dépôt distant", compact=True),),
            open=not p.remote))
    items.append(Note("Le jeton qui permet de pousser (GitHub ou un autre hôte https) se règle dans Configuration › "
                      "Canaux › Dépôts git : il n'apparaît jamais dans le journal ni dans ce qu'elle lit.", "muted"))
    return Section("Son dépôt distant", tuple(items),
                   description="Pousser envoie ce qui est enregistré ; récupérer avance l'atelier en ligne droite (un "
                               "atelier vierge prend toute l'histoire du dépôt distant).")


# ── La fiche : comportement et outils ─────────────────────────────────────


@PROJECTS.inspect("comportement", title="Comportement et outils", subject="project", order=70,
                  description="Comment elle y travaille : son mode (elle, avec son humeur et ses avis, ou un travail "
                              "impersonnel), son rythme et sa plage de travail, ce qu'elle a le droit de faire sortir, "
                              "et les outils qu'elle a en main.")
def _behaviour_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    pm = params(frame.env.params_of("projects", frame.root))
    key = str(p.id)
    editable = _editable(s, frame, key)
    blocks: list[Block] = []
    if editable:
        blocks.append(ActionSlot("projects.modifier", title="Modifier le projet"))
        if p.authority == c.SELF:
            blocks.insert(0, Note("Un projet qu'elle a ouvert d'elle-même : tu pilotes son mode, son rythme, sa "
                                  "liberté et ses outils, mais ni son titre ni ce qu'elle veut en faire.", "muted"))
    else:
        blocks.append(Note("Un projet archivé ne se modifie plus : restaure-le d'abord (en haut).", "muted"))
    persona = p.mode == c.PERSONA
    blocks.append(Grid((
        Fields((("mode", _mode(p)), ("ce que ça veut dire", Text(MODE_LONG.get(p.mode, p.mode))),
                ("son humeur dans le prompt", "oui, et sa fatigue" if persona else "non"),
                ("ce qu'elle en ressent", "fierté quand un ponctuel aboutit, frustration quand il bloque ; elle le "
                                          "raconte" if persona else "rien : ni émotion, ni estime, ni récit"),
                ("pendant son sommeil", "elle ne travaille pas" if persona else "il travaille quand même (dans sa "
                                                                                "plage)")),
               title="Son mode"),
        Fields((("plage de travail", window_words(p)), ("agenda", _agenda(p.schedule)),
                ("exécutions par jour", f"{daily_cap(p, pm)} au plus" + ("" if p.runs_per_day else " (par défaut)")),
                ("espacement", f"{pm.run_spacing_us // MINUTE} min au moins"),
                ("par heure, tous projets", f"{pm.runs_per_hour} au plus"),
                ("maintenant", _next_words(p, s, frame, ctx))),
               title="Son rythme"),
    ), columns=2))
    blocks.append(_tools_section(p, frame, editable))
    return blocks


def _tools_section(p: Project, frame: Frame, editable: bool) -> Section:
    descriptions: Mapping[str, str] = getattr(frame.env, "bundles", {}) or {}
    tools: Mapping[str, Any] = getattr(frame.env, "tools", {}) or {}
    rows = []
    for bundle in p.bundles:
        names = sorted(name for name, spec in tools.items() if spec.bundle == bundle
                       and (Kind.WORK in spec.episodes or Kind.JOB in spec.episodes))
        rows.append((Text(BUNDLE_WORDS.get(bundle, {"projects": "ses outils de projet", "workshop": "son atelier"}.get(
            bundle, bundle))), Text(descriptions.get(bundle, "—"), clamp=200),
            Text(", ".join(names) or "—", "mono", clamp=300)))
    items: list[Any] = [Table((Column("lot"), Column("ce qu'il permet"), Column("ses outils")), tuple(rows),
                              title="Ce qu'elle a en main pendant une exécution")]
    if editable:
        items.append(Disclosure("Choisir ses outils", (ActionSlot("projects.outils", title="Enregistrer ses outils",
                                                                  compact=True),)))
    return Section("Ses outils", tuple(items), description="Son atelier (lire, écrire, lancer des programmes isolés, "
                                                           "son dépôt git) et ses outils de projet sont toujours là ; "
                                                           "le reste se choisit.")


# ── La fiche : carnet ─────────────────────────────────────────────────────


OPERATIONS_CURSOR = "avant_ops"
NOTES_CURSOR = "avant_notes"
EFFECTS_CURSOR = "avant_effets"


def _operation(e: Event[Any], frame: Frame) -> Entry:
    d = e.data
    name = e.type.name.rsplit(".", 1)[-1]
    by = f"par {_who(frame, d.by)}" if getattr(d, "by", "") else "par elle" if name.startswith(("objective", "decision")) \
        else "automatique"
    titles = {"paused": ("mis en pause", "warn"), "resumed": ("repris", "ok"), "archived": ("archivé", "muted"),
              "restored": ("restauré", "info"), "reframed": ("cadre ou réglages modifiés", "info"),
              "decision_changed": (f"décision D{getattr(d, 'decision', '')} : "
                                   f"{DECISION_STATUS_FR.get(getattr(d, 'status', ''), '')}", ""),
              "deposited": (f"fichier déposé : {getattr(d, 'name', '')}", ""),
              "remote_requested": ("envoi au dépôt distant demandé" if getattr(d, "what", "") == "push"
                                   else "récupération demandée", "info")}
    if name == "nudged":
        title = f"« lancer maintenant » — objectif n° {d.objective}" if d.objective else "« lancer maintenant »"
        return Entry(e.at, title, meta=by)
    if name == "objective_added":
        return Entry(e.at, f"objectif n° {d.objective} ajouté ({KIND_FR.get(d.kind, d.kind)})", _said(d.text), meta=by)
    if name == "objective_changed":
        what = OBJECTIVE_STATUS_FR.get(d.status, "") if d.status else "modifié"
        return Entry(e.at, f"objectif n° {d.objective} : {what}", meta=by,
                     tone="ok" if d.status == c.DONE else "danger" if d.status == c.BLOCKED else "")
    title, tone = titles.get(name, (name, ""))
    text = getattr(d, "reason", "") if name in ("paused", "archived") else ""
    return Entry(e.at, title, text, meta=by, tone=tone)


@PROJECTS.inspect("carnet", title="Carnet", subject="project", order=80,
                  description="Les consignes que tu lui as données, les notes qu'elle garde pour la suite, ce qu'on a "
                              "fait du projet, et ce qu'il a voulu faire sortir de la machine.")
def _notebook_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    orders, orders_pager = _page(ctx, [AMENDED], ("project", p.id))
    notes, notes_pager = _page(ctx, [NOTED], ("project", p.id), NOTES_CURSOR)
    done, done_pager = _page(ctx, list(OPERATIONS), ("project", p.id), OPERATIONS_CURSOR)
    proposed, effects_pager = _page(ctx, [rt.EFFECT_PROPOSED], ("context", project_target(p.id)), EFFECTS_CURSOR)
    pending = {v.proposal for v in pending_of(frame, p.id)}
    outcomes: dict[int, list[Event[Any]]] = {}
    for e in proposed:
        if e.seq not in pending:
            outcomes[e.seq] = ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], 4, where=("proposal", e.seq))
    effect_rows = []
    for e in proposed:
        state, detail = _effect_state(e, e.seq in pending, outcomes.get(e.seq, ()))
        more: list[Any] = [Code(_cut(detail, 4000), title="ce qu'il en est")] if detail else []
        if e.seq in pending:
            more += decide_bar(str(e.seq), exact(s, e.seq))
        effect_rows.append(Row((When(e.at), Text(_said(e.data.summary), clamp=SUMMARY_CLAMP),
                                "requis" if e.data.approval else "non requis", state),
                               tone="warn" if e.seq in pending else "", detail=tuple(more)))
    return [
        Timeline(tuple(Entry(e.at, "consigne", _said(e.data.instruction),
                             meta=f"de {_who(frame, e.data.by)}" if e.data.by else "", tone="info")
                       for e in orders), title="Consignes reçues (la plus récente prime)", empty="aucune consigne",
                 pager=orders_pager),
        Timeline(tuple(Entry(e.at, "note", _said(e.data.text), href=Ref("episode", e.correlation, "note"))
                       for e in notes), title="Son carnet", empty="aucune note", pager=notes_pager),
        Timeline(tuple(_operation(e, frame) for e in done), title="Ce qu'on en a fait",
                 empty="rien encore : ni pause, ni réglage, ni objectif ajouté", pager=done_pager),
        Table((Column("quand", "fit"), Column("ce qu'il voulait faire sortir"), Column("accord", "fit"),
               Column("état", "fit")), tuple(effect_rows), title="Ce qui sort de la machine", pager=effects_pager,
              empty="aucune demande : tout s'est fait dans l'atelier"),
    ]


def _effect_state(proposal: Event[Any], pending: bool, outcomes: Sequence[Event[Any]]) -> tuple[Badge, str]:
    if pending:
        return Badge("attend ton accord", "warn"), ""
    executed = next((o for o in outcomes if o.type.name == rt.EFFECT_EXECUTED.name), None)
    resolved = next((o for o in outcomes if o.type.name == rt.EFFECT_RESOLVED.name), None)
    if executed is not None:
        return (Badge("fait", "ok") if executed.data.ok else Badge("échoué", "danger")), executed.data.result
    if resolved is not None and not resolved.data.approved:
        note = f" : « {resolved.data.note} »" if resolved.data.note else ""
        return Badge("refusé", "muted"), f"par {resolved.data.by or 'un opérateur'}{note}"
    if resolved is not None or not proposal.data.approval:
        return Badge("en cours", "info"), ""
    return Badge("inconnu", "muted"), ""


# ── Sur la fiche d'une personne ───────────────────────────────────────────


@PROJECTS.inspect("projets", title="Projets", subject="person", order=75,
                  description="Les projets qu'elle mène pour cette personne, ou qui la concernent.")
def _person_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Cette vue se lit sur la fiche d'une personne.", tone="muted")]
    handles = {person, *frame.get(identity_c.HANDLES(person))}
    concerned = sorted((p for p in s.projects.values() if p.owner in handles or handles & set(p.about)),
                       key=lambda p: (not live(p), -p.id))
    page, pager = paginate(concerned, ctx.pager(size=PAGE, total=len(concerned)))
    texts = _texts(ctx, (p.title_ref for p in page))
    rows = [Row((_link(p, _text(texts, p.title_ref, "(sans titre)")), _mode(p), _state(p), _progress(p),
                 "pour cette personne" if p.owner in handles else "la concerne", When(p.created_at)), href=_link(p))
            for p in page]
    return [Table((Column("projet"), Column("mode", "fit"), Column("état", "fit"), Column("objectifs"),
                   Column("lien", "fit"), Column("ouvert", "fit")), tuple(rows), title="Ses projets", pager=pager,
                  empty="aucun projet pour cette personne ni à son sujet")]

