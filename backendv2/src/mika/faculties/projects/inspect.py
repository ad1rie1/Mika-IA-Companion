"""Ce que les projets montrent à un opérateur (ADR 0031).

- **Projets** (menu) : la liste — mode, état, objectifs, prochaine exécution ;
  toutes les exécutions ; toutes les décisions techniques.
- **La fiche d'un projet** (type d'objet ``project``, clé = son numéro) :
  Vue d'ensemble, Objectifs, Exécutions, Décisions techniques, Fichiers,
  Dépôt git, Comportement et outils, Carnet. La fiche **gouverne** : chaque onglet porte
  les formulaires de ce qu'il montre (``ActionSlot``), les actions qui valent
  pour tout le projet sont en tête. Les onglets Fichiers (avec le téléchargement)
  et Dépôt git vivent à part, dans ``inspect_files.py`` et ``inspect_git.py`` :
  ils lisent les aides communes d'ici.
- **Sur la fiche d'une personne** : les projets qui la concernent.

Lecture seule : les compteurs viennent de la tranche, l'histoire (exécutions,
consignes, notes, opérations, effets) du journal, les fichiers et le dépôt git
du port de l'atelier, ce que GitHub dit d'un dépôt distant du port ``repo_host``
(ADR 0183). Un contenu oublié s'affiche « (oublié) ».
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
    _editable,
    _runnable,
    pending_of,
    schedule_words,
)
from mika.faculties.projects.faculty import (
    AMENDED,
    EXTRA_BUNDLES,
    NETWORKED_CAPABILITY,
    NOTED,
    OPERATIONS,
    PROJECTS,
    Decision,
    Objective,
    Project,
    ProjectsState,
    busy,
    in_force,
    live,
    objective_of,
    params,
    project_at,
)
from mika.faculties.projects.rhythm import always, cadence, daily_cap, pick, runs_today
from mika.faculties.projects.work import Why, next_run_at, why_not_now
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
    Entry,
    Fields,
    Found,
    Grid,
    Head,
    InspectContext,
    Meter,
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
    agree,
    paginate,
    plural,
)
from mika.kernel.text import fold
from mika.ports.workshop import argv_lines
from mika.vocab.episodes import Kind, outcome_words, project_target

PAGE = 25
FORGOTTEN = "(oublié)"
SUMMARY_CLAMP = 260
APPROVALS = Ref.approvals("ouvrir les actions à autoriser")

MODE_FR = {c.PERSONA: "elle-même", c.PLAIN: "impersonnel"}
MODE_LONG = dict(MODE_CHOICES)
MODE_TONE = {c.PERSONA: "info", c.PLAIN: "muted"}
STATUS_FR = {c.ACTIVE: "actif", c.PAUSED: "en pause", c.ARCHIVED: "archivé"}
STATUS_TONE = {c.ACTIVE: "ok", c.PAUSED: "warn", c.ARCHIVED: "muted"}
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
AUTHOR_FR = {"operator": "toi", "owner": "qui le lui a confié", "self": "elle"}

STATE_PARAM = Param("etat", "État", kind="select", default="vivants",
                    choices=(("vivants", "actifs et en pause"), (c.ACTIVE, "actifs"), (c.PAUSED, "en pause"),
                             (c.ARCHIVED, "archivés"), ("tous", "tous")))
MODE_PARAM = Param("mode", "Mode", kind="select", choices=tuple(MODE_FR.items()))
#: un projet par son titre (ou un mot de son titre) ou son n° : la liste les nomme, leur n° ne se lit que sur leur fiche
PROJECT_PARAM = Param("projet", "Projet", kind="search", placeholder="un titre ou un n°")
VERDICT_PARAM = Param("verdict", "Verdict", kind="select", choices=tuple(VERDICT_FR.items()))
OBJECTIVE_PARAM = Param("objectifs", "Objectifs", kind="select", default="vivants",
                        choices=(("vivants", "ouverts et bloqués"), (c.DONE, "faits"), (c.DROPPED, "retirés"),
                                 ("tous", "tous")))
#: un objectif est « vivant » tant qu'il est ouvert ou bloqué
LIVING = (c.OPEN, c.BLOCKED)
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
    return identity_c.person_name(frame, key) or key


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


def _tally(p: Project) -> tuple[int, int, int, int]:
    """Ses objectifs comptés une fois : ses ponctuels (hors retirés), ceux qui sont faits, ses constants ouverts, ses
    objectifs bloqués."""
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    return (len(once), sum(1 for o in once if o.status == c.DONE),
            sum(1 for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN),
            sum(1 for o in p.objectives if o.status == c.BLOCKED))


def objectives_progress(p: Project) -> tuple[str, str, str]:
    """L'avancement de ses objectifs, dit ici seulement : la valeur (« 0/2 » : ses ponctuels faits sur tous ; sans
    ponctuel, le nombre de ses constants ouverts ; sans l'un ni l'autre, celui de ses objectifs bloqués ; sans rien,
    « aucun »), la ligne qui la suit, accordée (« ponctuels faits · 1 constant · 1 bloqué »), et son ton (« warn » dès
    qu'un objectif est bloqué). La Stat « Objectifs » de sa vue d'ensemble les porte (la fiche dessinée les lit tels
    quels) et la jauge des listes en fait son libellé et son ton (``_progress``)."""
    once, done, constants, blocked = _tally(p)
    tone = "warn" if blocked else ""
    if once:
        value, parts = f"{done}/{once}", [agree(once, "ponctuel fait", "ponctuels faits")]
        parts += [plural(constants, "constant", "constants")] if constants else []
    elif constants:
        value, parts = str(constants), [agree(constants, "constant", "constants")]
    elif blocked:  # ses seuls objectifs vivants sont des constants bloqués : leur nombre, pas « 0 constant »
        return str(blocked), agree(blocked, "bloqué", "bloqués"), tone
    else:
        return "aucun", "", tone
    parts += [plural(blocked, "bloqué", "bloqués")] if blocked else []
    return value, " · ".join(parts), tone


def _progress(p: Project) -> Meter:
    """L'avancement en jauge (la liste « Ses projets », l'onglet Projets d'une personne) : la part de ses ponctuels
    faits, et ce que ``objectives_progress`` en dit."""
    once, done, _, _ = _tally(p)
    value, line, tone = objectives_progress(p)
    return Meter(done / once if once else 0.0, f"{value} {line}" if line else "aucun objectif", tone)


def tab_counts(p: Project) -> dict[str, int]:
    """Ce que les onglets de sa fiche comptent, par leur nom (``Overview.counts``) : ses objectifs (hors retirés),
    ses exécutions et ses décisions en vigueur — la tuile « Décisions en vigueur » de sa vue d'ensemble dessinée dit
    ce dernier nombre, quand sa vue n'en montre que les dernières."""
    return {"objectifs": sum(1 for o in p.objectives if o.status != c.DROPPED), "executions": p.runs,
            "decisions": in_force(p)}


#: ce qui retient son exécution (``work.why_not_now``), en mots ; ``{waits}`` : « ou une attente se termine »
#: quand une échéance est connue (``WAITS_WORDS``)
WHY_WORDS: dict[Why, str] = {
    Why.ARCHIVED: "il est archivé",
    Why.BUSY: "une exécution est en cours",
    Why.OUTGOING: "une commande, un envoi ou une récupération sont en route : l'atelier les attend",
    Why.PLAN_PROPOSED: "son plan attend la réponse de qui l'a demandé (« Valider le plan », ou en conversation)",
    Why.FRAMING: "sa séance de cadrage attend l'espacement ou le plafond du jour",
    Why.NO_OBJECTIVE: "aucun objectif ouvert : ajoutes-en un",
    Why.ON_DEMAND: "il avance sur demande : « Lancer maintenant »",
    Why.NOTHING_DUE: "rien n'est dû : ses objectifs constants attendent leur cadence{waits}",
    Why.DAY_CAP: "plafond du jour atteint ({cap} exécutions sur 24 h)",
    Why.HOUR_CAP: "plafond atteint : {cap} exécutions par heure, tous projets confondus",
    Why.ASLEEP: "elle dort : en mode « elle-même », elle y travaille éveillée",
    Why.OUT_OF_WINDOW: "hors de sa plage de travail",
    Why.NO_SLOT: "son agenda ne lui donne plus de créneau",
    Why.LATER: "pas encore : son agenda ou l'espacement des exécutions la fixe plus tard",
}
WAITS_WORDS = " ou une attente se termine"
#: les raisons qui se datent : la date de l'exécution, puis ces mots entre parenthèses (la forme de la prochaine
#: séance d'un but, ``goals.inspect.LATER_WORDS``)
LATER_WORDS: dict[Why, str] = {
    Why.LATER: "son agenda ou l'espacement des exécutions la fixe plus tard",
    Why.OUT_OF_WINDOW: "hors de sa plage de travail",
    Why.NOTHING_DUE: "ses objectifs constants attendent leur cadence{waits}",
}


def _cited(why: Why, said: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que les mots d'une raison citent : l'attente, en mots."""
    if why is Why.NOTHING_DUE:
        return {"waits": WAITS_WORDS if said.get("waits") else ""}
    return dict(said)


def _next_words(p: Project, s: ProjectsState, frame: Frame, ctx: InspectContext) -> str:
    """La prochaine exécution en mots, de la forme de la prochaine séance d'un but (``goals.inspect.next_session``) :
    « dès que possible », quand (la date, puis pourquoi pas avant : ``LATER_WORDS``), ou ce qui la retient
    (``WHY_WORDS``). La raison vient de ``work.why_not_now``, en code : rien ne se relit dans une phrase. En pause,
    « à la reprise » : la raison de la pause se dit une fois, dans le bandeau de sa vue d'ensemble (ADR 0176)."""
    if p.status == c.PAUSED:
        return "à la reprise"
    held = why_not_now(p, s, frame)
    if held is None:
        return "dès que possible"
    why, said = held
    at = next_run_at(p, s, frame) if p.status == c.ACTIVE else None
    if why in LATER_WORDS and at is not None and at > frame.now:
        return f"{ctx.when(at)} ({LATER_WORDS[why].format(**_cited(why, said))})"
    return WHY_WORDS[why].format(**_cited(why, said))


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


def window_words(p: Project) -> str:
    """La plage en mots (« les jours ouvrés, de 9 h à 18 h »)."""
    if always(p):
        return "à toute heure"
    days = {c.EVERY_DAY: "tous les jours", c.WEEKDAYS: "les jours ouvrés", c.WEEKEND: "le week-end"}.get(p.days, p.days)
    return f"{days}, de {hhmm(p.start_min)} à {hhmm(p.end_min)}"


def hhmm(minutes: int) -> str:
    h, m = divmod(max(0, min(24 * 60, minutes)), 60)
    return f"{h} h" if not m else f"{h} h {m:02d}"


# ── L'objet « projet » ────────────────────────────────────────────────────


@PROJECTS.subject("project", label="Projet", plural="Projets")
def _head(s: ProjectsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    p = project_at(s, key)
    if p is None:
        return None
    texts = _texts(ctx, (p.title_ref,))
    # la vue d'un objet (ADR 0176, la maquette) : son état à côté de son nom, puis ses faits sur une ligne — son
    # avancement, sa prochaine exécution et son dépôt sont dans sa vue d'ensemble
    badges = [_state(p)]
    if p.priority != c.NORMAL:
        badges.append(_priority(p))
    if busy(s, p.id):
        badges.append(Badge("au travail", "info"))
    facts: list[tuple[str, Any]] = [
        ("mode", MODE_FR.get(p.mode, p.mode)),
        ("", "à elle") if p.authority == c.SELF else ("pour", _person(frame, p.owner) if p.owner else "toi"),
        ("dernière exécution", ctx.when(p.last_run_at) if p.last_run_at else "aucune encore"),
        ("plage", window_words(p)),
    ]
    if p.tried_at > p.last_run_at:  # une tentative depuis, qui n'a pas eu lieu (panne, délai, préemption)
        facts.insert(3, ("dernière tentative", f"{ctx.when(p.tried_at)}, sans suite (crédit rendu)"))
    return Head(str(p.id), _text(texts, p.title_ref, "(sans titre)"), badges=tuple(badges),
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


LIST_COLUMNS = (Column("projet", role="title"), Column("mode", "fit", role="badge"), Column("pour qui"), Column("état", "fit", role="badge"),
                Column("objectifs"), Column("prochaine exécution"), Column("dernière", "fit"),
                Column("où il en est", role="body"),
                Column("priorité", detail=True), Column("plage de travail", detail=True),
                Column("agenda", detail=True), Column("outils", detail=True), Column("dépôt distant", detail=True),
                Column("ce qui sort", detail=True))


def _tools_words(p: Project) -> str:
    extra = [BUNDLE_WORDS.get(b, b) for b in p.bundles if b in EXTRA_BUNDLES]
    return "son atelier" + (", " + ", ".join(extra) if extra else "")


@PROJECTS.inspect("tous", title="Ses projets", section="projets", order=5, params=[STATE_PARAM, MODE_PARAM],
                  badge=_awaiting,
                  description="Suivre ses objectifs, repérer ce qui attend ton accord et ouvrir un espace de travail.")
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
            _priority(p), window_words(p), schedule_words(p.schedule), _tools_words(p), _remote_ref(p),
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
            Stat("Objectifs", open_once, f"{agree(open_once, 'ponctuel ouvert', 'ponctuels ouverts')} · "
                                         f"{plural(constants, 'constant', 'constants')}"),
            Stat("Exécutions (24 h)", today, f"{pm.runs_per_hour} par heure au plus, tous projets confondus"),
            Stat("Attendent ton accord", len(waiting), "pour faire sortir quelque chose",
                 "warn" if waiting else "", APPROVALS),
            Stat("Archivés", sum(1 for p in every if p.status == c.ARCHIVED)),
        )),
        Table(LIST_COLUMNS, tuple(rows), title="Projets", pager=pager, layout="cards",
              empty="aucun projet avec ces filtres" if wanted != "vivants" or mode else
              "aucun projet : « Créer un projet » (en haut) en ouvre un — elle peut aussi en ouvrir d'elle-même.",
              caption="Une exécution vise un objectif : celui que tu demandes, sinon le constant le plus en retard, "
                      "sinon le premier ponctuel ouvert. Un projet en mode « elle-même » ne travaille pas pendant son sommeil ; "
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


_NUMBER = re.compile(r"#?\s*([0-9]{1,12})")


def _projects_named(s: ProjectsState, ctx: InspectContext, asked: str) -> tuple[int, ...]:
    """Les projets que le filtre « Projet » désigne, du plus récent au plus ancien : des chiffres (avec ou sans « # »)
    → ce projet ; sinon, ou s'il n'y a pas de projet sous ce n°, ceux dont le titre contient le texte, sans tenir
    compte des accents ni de la casse (``kernel.text.fold``, comme la recherche de la console). Un titre oublié ne
    se retrouve pas par son texte."""
    number = _NUMBER.fullmatch(asked.strip())
    if number and int(number.group(1)) in s.projects:
        return (int(number.group(1)),)
    wanted = fold(asked.strip())
    projects = sorted(s.projects.values(), key=lambda p: -p.id)
    texts = _texts(ctx, (p.title_ref for p in projects))
    return tuple(p.id for p in projects if (title := texts.get(p.title_ref)) is not None and wanted in fold(title))


def _nothing_named(asked: str) -> Note:
    """Le filtre « Projet » ne désigne aucun projet : la table reste vide, et la page le dit."""
    number = _NUMBER.fullmatch(asked.strip())
    if number:
        return Note(f"Aucun projet ne porte le n° {int(number.group(1))}.", "info")
    return Note(f"Aucun projet ne s'appelle « {asked.strip()[:80]} ».", "info")


@PROJECTS.inspect("toutes_executions", title="Exécutions", section="projets", order=10,
                  params=[PROJECT_PARAM, VERDICT_PARAM],
                  description="Chaque exécution de travail, tous projets confondus : l'objectif visé, le verdict, sa "
                              "preuve, le compte rendu et le commit qu'elle a laissé dans l'atelier.")
def _runs_view(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    asked, verdict = str(ctx.value("projet") or "").strip(), str(ctx.value("verdict") or "")
    chosen = _projects_named(s, ctx, asked) if asked else None
    if chosen == ():
        found, pager = [], Pager(param="avant", size=PAGE)
    elif chosen is not None and (len(chosen) > 1 or verdict):
        found, pager = _both(ctx, chosen, verdict)
    else:
        where = ("project", chosen[0]) if chosen else ("verdict", verdict) if verdict else None
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
    blocks: list[Block] = [_nothing_named(asked)] if chosen == () else []
    if running:
        names = _texts(ctx, (p.title_ref for _, p in running if p is not None))
        blocks.append(Note("En ce moment : " + ", ".join(
            f"« {_text(names, p.title_ref, '(sans titre)')} »" for _, p in running if p is not None) + ".", "info"))
    blocks.append(Table(RUN_COLUMNS, tuple(rows), title="Les exécutions", pager=pager,
                        empty="aucune exécution avec ces filtres" if asked or verdict else "aucune exécution encore"))
    return blocks


#: deux filtres : le journal en filtre un, on lit par lots pour l'autre jusqu'à remplir la page
SCAN, SCAN_BATCHES = 200, 10


def _both(ctx: InspectContext, projects: tuple[int, ...], verdict: str) -> tuple[list[Event[Any]], Pager]:
    """Les comptes rendus de ces projets (avec ce verdict s'il est donné), une page pleine (ou le journal épuisé, ou
    dit) : le journal filtre par le projet quand il n'y en a qu'un, sinon par le verdict ; le reste se trie ici."""
    where = ("project", projects[0]) if len(projects) == 1 else ("verdict", verdict) if verdict else None
    wanted = set(projects)
    cursor = ctx.int_param("avant", 0) or None
    shown: list[Event[Any]] = []
    for _ in range(SCAN_BATCHES):
        batch = ctx.events([c.RUN_REPORTED], SCAN, where=where, before=cursor)
        for e in batch:
            cursor = e.seq
            if e.data.project in wanted and (not verdict or e.data.verdict == verdict):
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
    asked, wanted = str(ctx.value("projet") or "").strip(), str(ctx.value("statut") or c.IN_FORCE)
    chosen = _projects_named(s, ctx, asked) if asked else None
    every = [(p, d) for p in sorted(s.projects.values(), key=lambda p: -p.id) if chosen is None or p.id in chosen
             for d in reversed(p.decisions) if wanted == "toutes" or d.status == wanted]
    page, pager = paginate(every, ctx.pager(size=PAGE, total=len(every)))
    texts = _texts(ctx, [r for p, d in page for r in (p.title_ref, d.title_ref, d.choice_ref, d.reason_ref)])
    rows = [Row((_decisions_ref(p, _text(texts, p.title_ref, "(sans titre)")), f"D{d.id}",
                 Text(_text(texts, d.title_ref), clamp=120), Text(_text(texts, d.choice_ref), clamp=220),
                 _decision_badge(d), AUTHOR_FR.get(d.author, d.author), When(d.at),
                 Text(_text(texts, d.reason_ref), clamp=400)), href=_decisions_ref(p, ""))
            for p, d in page]
    return [*([_nothing_named(asked)] if chosen == () else []),
            Table(DECISION_COLUMNS, tuple(rows), title="Décisions techniques", pager=pager,
                  empty="aucune décision avec ces filtres")]


def _decisions_ref(p: Project, text: str) -> Ref:
    """L'onglet Décisions techniques du projet, toutes montrées (une décision remplacée ou retirée s'y retrouve)."""
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
    # le cadrage (ADR 0145) : à cadrer, puis un plan qui attend sa réponse
    if p.status == c.ACTIVE and p.plan_state == c.TO_FRAME:
        out.append(Note("À cadrer : sa séance de cadrage relira la demande et écrira son plan avant toute autre "
                        "exécution.", "info"))
    elif p.status == c.ACTIVE and p.plan_state == c.PROPOSED:
        out.append(Note("Son plan attend une réponse : « Valider le plan » le lance, « Demander une révision » le lui "
                        "fait reprendre (ou en conversation, avec elle).", "warn"))
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
    if raw is None or got is None or got[1] != NETWORKED_CAPABILITY:
        return ""
    try:
        argv = json.loads(raw).get("argv") or []
    except (ValueError, AttributeError):
        return ""
    return argv_lines([str(a) for a in argv])


#: le libellé du lien vers la file, sous chaque demande qui attend ton accord (la section « À décider » de la vue
#: d'ensemble, le détail d'une ligne du Carnet) : la fiche dessinée compte ces liens pour son bandeau
DECIDE_LABEL = "ton accord"
#: le texte de ce lien : une espace fine insécable dans chaque guillemet, une insécable dans « À valider », pour
#: qu'une colonne étroite (les faits d'un détail du Carnet) passe à la ligne avant le nom de la file, jamais dedans
DECIDE_TEXT = "La décider dans « À valider »"
COMMAND_TITLE = "La commande, entière, un argument par ligne"


def decide_where(proposal: int) -> tuple[str, Ref]:
    """Où se décide une demande : la file « À valider », ouverte sur elle — la fiche d'un projet ne décide plus ses
    demandes sur place (ADR 0177) ; la console rend le lien (ADR 0216)."""
    return DECIDE_LABEL, Ref.approvals(DECIDE_TEXT, "en_attente", demande=str(proposal))


def _approvals(p: Project, s: ProjectsState, frame: Frame, texts: Mapping[str, str]) -> Section | None:
    """Ce qui attend ton accord : chaque demande, ce que c'est, le lien qui la décide dans « À valider »
    (``decide_where`` : la fiche dessinée en tire son bandeau) et la commande telle qu'elle partira (``exact``)."""
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
                                 v.capability, "une commande avec le réseau")),
                             decide_where(v.proposal)), columns=1))
        if argv:
            items.append(Code(argv, title=COMMAND_TITLE))
    return Section(f"À décider ({len(pending)})", tuple(items),
                   description="Ce qu'elle veut faire sortir de la machine : rien ne part sans ton accord. Ce qui est "
                               "montré est ce qui partira ; ses raisons sont ses mots, pas une description de la "
                               "commande.")


PLAN_FR = {c.TO_FRAME: ("à cadrer", "info"), c.PROPOSED: ("plan proposé, il attend une réponse", "warn"),
           c.PLANNED: ("planifié", "ok")}


def _plan_section(p: Project, frame: Frame, texts: Mapping[str, str]) -> Section | None:
    """Ce qu'on lui a demandé, ses mots tels quels, et son plan (ADR 0145) : sa réponse se donne ici quand il
    attend."""
    if p.plan_state == c.UNPLANNED and not p.request_ref and p.status != c.ACTIVE:
        return None
    label, tone = PLAN_FR.get(p.plan_state, ("sans plan", "muted"))
    items: list[Any] = [Fields((("son plan", Badge(label, tone)),
                                ("demandé par", _who(frame, p.asked_by) if p.asked_by else "—"),
                                ("version", str(p.plan_version) if p.plan_version else "aucune encore")), columns=3)]
    if texts.get(p.request_ref):
        items.append(Prose(texts[p.request_ref], title="La demande, ses mots tels quels"))
    if texts.get(p.plan_ref):
        items.append(Prose(texts[p.plan_ref], title="Son plan"))
    if texts.get(p.questions_ref) and p.plan_state == c.PROPOSED:
        items.append(Prose(texts[p.questions_ref], title="Ses questions, avec ce qu'elle recommande"))
    slots = []
    if p.status == c.ACTIVE and p.plan_state == c.PROPOSED:
        slots.append(ActionSlot("projects.plan_valider", (), title="Valider le plan", presentation="button"))
    if p.status == c.ACTIVE and p.plan_state != c.TO_FRAME:
        slots.append(ActionSlot("projects.plan_reviser", (), title="Demander une révision" if p.plan_state
                                else "Lui faire écrire un plan", presentation="button"))
    if slots:
        items.append(Toolbar(tuple(slots), title="Sa réponse"))
    return Section("Le plan", tuple(items), description="Ce qu'on lui a demandé et comment elle s'y prend : ses "
                   "étapes sont ses objectifs, dans l'ordre, chacun avec son critère de fait.")


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
    texts = _texts(ctx, [p.description_ref, p.summary_ref, p.request_ref, p.plan_ref, p.questions_ref,
                         *(o.text_ref for o in p.objectives),
                         *(r for d in decisions for r in (d.title_ref, d.choice_ref)),
                         *(v.summary_ref for v in pending)])
    blocks: list[Block] = [*_state_notes(p, s, frame, ctx)]
    approvals = _approvals(p, s, frame, texts)
    if approvals is not None:
        blocks.append(approvals)
    plan = _plan_section(p, frame, texts)
    if plan is not None:
        blocks.append(plan)
    target = pick(p, frame.now, pm) if p.status == c.ACTIVE else None
    # Une bande de chiffres, puis des tuiles : ce qui se lit d'un coup ; le détail vit dans les onglets (ADR 0176).
    blocks.append(Stats((
        Stat("Objectifs", *objectives_progress(p), href=_link(p, tab="objectifs")),  # valeur, ligne et ton
        Stat("Exécutions", str(p.runs), f"{runs_today(p, frame.now)} sur 24 h (au plus {daily_cap(p, pm)})",
             href=_link(p, tab="executions")),
        Stat("Pannes d'affilée", str(p.failures) if p.failures else "aucune", tone="danger" if p.failures else ""),
        Stat("Dernier commit", Text(p.last_commit[:7], "mono") if p.last_commit else "aucun encore",
             href=_link(p, tab="git")),
    ), title="Où il en est"))
    open_rows = []
    for o in sorted(p.objectives, key=lambda o: (OBJ_ORDER.get((o.kind, o.status), 9), o.id)):
        if o.status == c.DROPPED:
            continue
        open_rows.append(Row((o.id, Text(_text(texts, o.text_ref), clamp=160),
                              Badge(KIND_FR.get(o.kind, o.kind), KIND_TONE.get(o.kind, "")),
                              Badge(OBJ_FR.get(o.status, o.status), OBJ_TONE.get(o.status, "")),
                              _last_words(o, frame.now, pm)), href=_link(p, tab="objectifs")))
    recent = ctx.events([c.RUN_REPORTED], 5, where=("project", p.id))
    blocks.append(Grid((
        Table((Column("n°", "fit"), Column("objectif"), Column("sorte", "fit"), Column("état", "fit"),
               Column("dernier passage")), tuple(open_rows[:6]), title="Ses objectifs",
              empty="aucun objectif : ajoutes-en un (onglet Objectifs)",
              caption="Tous les objectifs, leur cadence et leurs boutons : onglet Objectifs."
              if len(open_rows) > 6 else ""),
        Timeline(tuple(
            Entry(e.at, f"{VERDICT_FR.get(e.data.verdict, e.data.verdict)} — objectif n° {e.data.objective}"
                  if e.data.objective else VERDICT_FR.get(e.data.verdict, e.data.verdict),
                  _said(e.data.summary), tone=VERDICT_TONE.get(e.data.verdict, ""),
                  meta=f"commit {e.data.commit}" if e.data.commit else "", href=Ref("episode", e.correlation, ""))
            for e in recent), title="Dernières exécutions", empty="aucune exécution encore"),
    ), columns=2))
    blocks.append(Grid((
        # son mode et sa plage sont dans les faits de son en-tête ; son dernier commit, dans la bande
        Fields((("quand", _next_words(p, s, frame, ctx)),
                ("sur quoi", Text(f"n° {target.id} · {_text(texts, target.text_ref)}", clamp=80)
                 if target is not None else "—")),
               title="Prochaine exécution"),
        Prose(_text(texts, p.description_ref), title="Le cadre") if p.description_ref
        else Note("Aucun cadre écrit : elle suit le titre, ses objectifs et les consignes. Il se change dans l'onglet "
                  "Comportement et outils.", "muted", title="Le cadre"),
        Fields((("dépôt distant", _remote_ref(p)),
                ("dernier échange", Text(p.remote_line, tone="ok" if p.remote_ok else "danger", clamp=90)
                 if p.remote_line else "aucun"),
                ("l'histoire complète", _link(p, "onglet Dépôt git", "git"))),
               title="Son dépôt"),
    ), columns=3))
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
        return f"{plural(o.runs, 'exécution', 'exécutions')}, la dernière il y a {_ago(now - o.last_run_at)}"
    return "pas encore travaillé"


# ── La fiche : objectifs ──────────────────────────────────────────────────


OBJECTIVE_COLUMNS = (Column("n°", "fit"), Column("objectif"), Column("sorte", "fit"), Column("état", "fit"),
                     Column("rythme"), Column("exécutions", "num"), Column("dernier compte rendu"),
                     Column("posé par", "fit", detail=True))


@PROJECTS.inspect("objectifs", title="Objectifs", subject="project", order=20, params=[OBJECTIVE_PARAM],
                  description="Ce que le projet cherche, ligne par ligne : un objectif ponctuel se coche une fois (avec "
                              "une preuve), un objectif constant revient selon sa cadence. Déplie une ligne pour la "
                              "lancer, la modifier ou changer son statut. Les objectifs ouverts et bloqués d'abord ; "
                              "les faits et les retirés se filtrent.")
def _objectives_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _subject(s, ctx)
    if isinstance(p, Note):
        return [p]
    pm = params(frame.env.params_of("projects", frame.root))
    key = str(p.id)
    editable = _editable(s, frame, key)
    runnable = _runnable(s, frame, key)
    wanted = str(ctx.value("objectifs") or "vivants")
    chosen = sorted((o for o in p.objectives if wanted == "tous" or o.status == wanted
                     or (wanted == "vivants" and o.status in LIVING)),
                    key=lambda o: (OBJ_ORDER.get((o.kind, o.status), 9), o.id))
    page, pager = paginate(chosen, ctx.pager(size=PAGE, total=len(chosen)))  # une page de formulaires, pas mille
    texts = _texts(ctx, [r for o in page for r in (o.text_ref, o.note_ref, o.result_ref)])
    rows = []
    for o in page:
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
        Table(OBJECTIVE_COLUMNS, tuple(rows), title="Ses objectifs", pager=pager,
              empty="aucun objectif : ajoutes-en un ci-dessous" if not p.objectives else "aucun objectif ici (filtre)",
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
        issue = Badge(*outcome_words(outcome, e.data.kind)) if outcome else Badge("en cours", "info")
        duration = f"{max(1, (end.at - e.at) // 1_000_000)} s" if end is not None else "—"
        verdict: Any = Badge(VERDICT_FR.get(report.verdict, report.verdict), VERDICT_TONE.get(report.verdict, "")) \
            if report is not None else "—"
        oid = report.objective if report is not None else (objective_of(e.data.subject) or (0, 0))[1]
        rows.append(Row((
            When(e.at), MODE_FR[c.PERSONA] if e.data.kind == Kind.WORK else MODE_FR[c.PLAIN], _objective_words(p, oid, texts), issue,
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


# ── La fiche : décisions ──────────────────────────────────────────────────


@PROJECTS.inspect("decisions", title="Décisions techniques", subject="project", order=40, params=[DECISION_PARAM],
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
              pager=pager,
              empty="aucune décision avec ce filtre" if wanted != c.IN_FORCE else
              "aucune décision encore : elle en consigne pendant ses exécutions, et toi ici"),
    ]
    if editable:
        out.append(Section("Consigner une décision", (ActionSlot("projects.decision_ajouter",
                                                                 title="Consigner une décision", compact=True),),
                           description="La question tranchée, ce qui est choisi et pourquoi. Pour revenir sur une "
                                       "décision, « Remplacer cette décision » : l'ancienne reste lisible, remplacée."))
    return out


# ── La fiche : comportement et outils ─────────────────────────────────────


#: le fait de « Son rythme » qui dit quand il travaillera la prochaine fois (la fiche dessinée le met en tête)
NEXT_RUN_LABEL = "prochaine exécution"


@PROJECTS.inspect("comportement", title="Comportement et outils", subject="project", order=70,
                  description="Comment elle y travaille : son mode (elle, avec son humeur et ses avis, ou un travail "
                              "impersonnel), son rythme et sa plage de travail, ce qu'elle a le droit de faire sortir, "
                              "et les outils qu'elle a en main.")
def _behaviour_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Le formulaire « Modifier le projet », puis ses réglages en faits — son mode, son rythme (et sa prochaine
    exécution), sa liberté — et ses outils. La fiche dessinée (``app/handmade/subjects/project.py``) montre le
    formulaire et tait ces faits, qu'elle passe en aide de leur réglage ou en une ligne ; ils restent ici pour la
    console en MCP, le repli, et un projet archivé (sans formulaire), qui les montre en lecture."""
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
        Fields((("plage de travail", window_words(p)), ("agenda", schedule_words(p.schedule)),
                # le plafond par défaut se dit toujours : « 0 » dans le formulaire, c'est lui
                ("exécutions par jour", f"{daily_cap(p, pm)} au plus" + (
                    f" (par défaut : {pm.runs_per_day})" if p.runs_per_day else " (par défaut)")),
                ("espacement", f"{pm.run_spacing_us // MINUTE} min au moins"),
                ("par heure, tous projets", f"{pm.runs_per_hour} au plus"),
                ("priorité", PRIORITY_FR.get(p.priority, p.priority)),
                (NEXT_RUN_LABEL, _next_words(p, s, frame, ctx))),
               title="Son rythme"),
        Fields((("ce qui sort de la machine", "attend ton accord" if p.approval else "part sans ton accord"),),
               title="Sa liberté"),
    ), columns=2))
    blocks.append(_tools_section(p, frame, editable))
    return blocks


def _tools_section(p: Project, frame: Frame, editable: bool) -> Section:
    """Ses outils : les lots qu'elle a en main pendant une exécution (ce qu'ils permettent, leurs outils nommés), et
    « Choisir ses outils » (``projects.outils``) tant que le projet se modifie."""
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
                                   else "récupération demandée", "info"),
              "plan_proposed": ("plan écrit, validé d'office" if getattr(d, "approved", False)
                                else "plan proposé, il attend une réponse", "info"),
              "plan_answered": ("plan validé" if getattr(d, "verdict", "") == "approve"
                                else "révision du plan demandée", "ok" if getattr(d, "verdict", "") == "approve"
                                else "warn")}
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
        if e.seq in pending:  # ce qui partira, puis où le décider : la fiche ne décide plus sur place (ADR 0177)
            argv = exact(s, e.seq)
            more += [Code(argv, title=COMMAND_TITLE)] if argv else []
            more.append(Fields((decide_where(e.seq),), columns=1))
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
        note = f" : « {said} »" if (said := resolved.data.said()) else ""
        return Badge("refusé", "muted"), f"par {resolved.data.by or 'un opérateur'}{note}"
    if resolved is not None or not proposal.data.approval:
        return Badge("en cours", "info"), ""
    return Badge("inconnu", "muted"), ""


# ── Sur la fiche d'une personne ───────────────────────────────────────────


def of_person(s: ProjectsState, handles: Iterable[str]) -> list[Project]:
    """Les projets qui regardent cette personne (``handles`` : sa clé et ses moyens de communication) : menés pour
    elle, ou qui la concernent — l'onglet Projets de sa fiche, et son compte dans la barre
    (``PersonOverview.counts``)."""
    keys = set(handles)
    return [p for p in s.projects.values() if p.owner in keys or keys & set(p.about)]


@PROJECTS.inspect("projets", title="Projets", subject="person", order=75,
                  description="Les projets qu'elle mène pour cette personne, ou qui la concernent.")
def _person_tab(s: ProjectsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Cette vue se lit sur la fiche d'une personne.", tone="muted")]
    handles = {person, *frame.get(identity_c.HANDLES(person))}
    concerned = sorted(of_person(s, handles), key=lambda p: (not live(p), -p.id))
    page, pager = paginate(concerned, ctx.pager(size=PAGE, total=len(concerned)))
    texts = _texts(ctx, (p.title_ref for p in page))
    rows = [Row((_link(p, _text(texts, p.title_ref, "(sans titre)")), _mode(p), _state(p), _progress(p),
                 "pour cette personne" if p.owner in handles else "la concerne", When(p.created_at)), href=_link(p))
            for p in page]
    out: list[Block] = []
    if concerned:  # l'oubli efface sa vie (contenus, journal) ; un atelier est un dossier : il faut le dire
        out.append(Note(forget_note(len(concerned)), tone="warn", title="L'oubli et les ateliers"))
    return [*out, Table((Column("projet"), Column("mode", "fit"), Column("état", "fit"), Column("objectifs"),
                         Column("lien", "fit"), Column("ouvert", "fit")), tuple(rows), title="Ses projets",
                        pager=pager, empty="aucun projet pour cette personne ni à son sujet")]


def forget_note(n: int) -> str:
    """Ce que l'oubli d'une personne n'atteint pas (PRJ-9), dit sur sa fiche avant qu'on l'oublie, accordé au nombre de
    ses projets (« ce projet », « ces 3 projets »)."""
    one = n == 1
    these = "ce projet" if one else f"ces {plural(n, 'projet', 'projets')}"
    return (f"Oublier cette personne efface ce que sa vie garde de {these} — titres, comptes rendus, carnets, "
            f"décisions —, pas {'son atelier' if one else 'leurs ateliers'} : les fichiers, l'historique git (dont "
            "les messages de commit restent neutres) et ce qui est déjà parti vers un dépôt distant. "
            f"{'Ouvre-le' if one else 'Ouvre chaque projet'} pour faire le ménage dans son atelier, ou archive-le. "
            "Le stockage des apps de la Forge n'est pas atteint non plus (« Vider le stockage » sur la fiche d'une "
            "app).")
