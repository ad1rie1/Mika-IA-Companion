"""Ce que les buts montrent à un opérateur.

- **La fiche d'un but** (type d'objet ``goal``, clé = son numéro) : son
  résumé, ses pas et leurs verdicts, son carnet et les consignes reçues, ce
  qu'il a voulu faire sortir de la machine, ses épisodes, son atelier.
- **Buts** : les vivants (actifs, en attente, en pause) et les clos.
- **Sur la fiche d'une personne** : les buts qui la concernent.

Lecture seule. Les compteurs et l'envie viennent de la tranche (calculés comme
la faculté les calcule) ; l'historique (pas, notes, consignes, effets,
épisodes, clôtures), du journal — la tranche n'en garde que l'essentiel. Un
contenu oublié s'affiche « (oublié) ».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.goals.actions import SCHEDULES
from mika.faculties.goals.faculty import (
    GOAL_AMENDED,
    GOALS,
    NOTED,
    Goal,
    GoalsState,
    desire,
    goal_at,
    live,
    params,
    ready_to_undertake,
    status,
)
from mika.faculties.goals.work import next_step_at
from mika.kernel.builtin import SELECTED
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Code,
    Column,
    Entry,
    Fields,
    Found,
    Head,
    InspectContext,
    Meter,
    Note,
    Pager,
    Param,
    Prose,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    When,
    paginate,
)
from mika.vocab.episodes import Kind, goal_of, goal_target

GOALS_PAGE = 50
#: l'historique d'un but (pas, consignes, notes, effets, épisodes), par page : tout le journal, du plus récent
#: au plus ancien (``?avant=`` : la suite ; le carnet a un second curseur pour ses notes)
HISTORY_PAGE = 25
NOTES_CURSOR = "avant_notes"
#: les buts clos filtrés par autorité : relus par lots jusqu'à remplir la page, au plus tant de lots
CLOSED_SCAN = 200
CLOSED_SCAN_BATCHES = 10
#: les décisions et exécutions relues d'un coup pour dire ce que sont devenus ses effets (au-delà : relues
#: demande par demande)
OUTCOMES_SCANNED = 500
#: les pas relus pour rattacher un enregistrement de l'atelier à son pas
STEPS_MATCHED = 1000
DIFF_SHOWN = 20_000
#: ce qu'on montre du résultat d'un effet (au-delà, coupé et dit)
EFFECT_DETAIL = 4000
#: les enregistrements de l'atelier relus (au-delà, la vue le dit)
LOG_MAX = 500
SUMMARY_CLAMP = 280
FORGOTTEN = "(oublié)"
#: les approbations, dans la console
APPROVALS = Ref("local", "/inspecteur/approbations", "ouvrir les approbations")

KIND_FR = {c.REMINDER: "rappel", c.EXPLORATION: "exploration", c.PROJECT: "projet"}
AUTHORITY_FR = {c.USER: "confié", c.SELF: "à elle"}
STATUS_FR = {c.ACTIVE: "en cours", c.WAITING: "en attente", c.PAUSED: "en pause", c.ACHIEVED: "abouti",
             c.STUCK: "bloqué", c.ABANDONED: "abandonné", c.FAILED: "en échec", c.CANCELLED: "annulé"}
STATUS_TONE = {c.ACTIVE: "ok", c.WAITING: "info", c.PAUSED: "warn", c.ACHIEVED: "ok", c.STUCK: "danger",
               c.ABANDONED: "muted", c.FAILED: "danger", c.CANCELLED: "muted"}
VERDICT_FR = {c.CONTINUE: "continuer", c.DONE: "fini", c.BLOCKED: "bloquée", c.WAIT: "attendre"}
VERDICT_TONE = {c.CONTINUE: "info", c.DONE: "ok", c.BLOCKED: "danger", c.WAIT: "muted"}
OUTCOME_FR = {"done": "fait", "abstained": "abstenue", "superseded": "supplanté", "timeout": "délai dépassé",
              "failed": "échec", "preempted": "préempté", "interrupted": "interrompu", "cancelled": "annulé"}
OUTCOME_TONE = {"done": "ok", "abstained": "muted", "superseded": "warn", "timeout": "danger", "failed": "danger",
                "preempted": "warn", "interrupted": "warn", "cancelled": "muted"}

KIND_PARAM = Param("sorte", "Sorte", kind="select", choices=tuple(KIND_FR.items()))
AUTHORITY_PARAM = Param("autorite", "Autorité", kind="select", choices=tuple(AUTHORITY_FR.items()))


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
    """Le texte d'un contenu relu au journal (``text`` à ``None`` : il a été oublié)."""
    if content is None:
        return empty
    return content.text if content.text is not None else FORGOTTEN


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch))


def _name(frame: Frame, key: str | None) -> str:
    return frame.get(identity_c.IDENTITY(key)).name if key else ""


def _who(frame: Frame, key: str | None) -> str:
    if not key:
        return "—"
    name = _name(frame, key)
    return f"« {name} » ({key})" if name else key


def _person(frame: Frame, key: str | None) -> Ref | str:
    """Un lien vers la fiche de la personne (sa clé de relation)."""
    if not key:
        return "—"
    person = frame.get(identity_c.PERSON(key))
    return Ref.subject("person", person, _who(frame, key))


def _status(g: Goal, now: int) -> Badge:
    st = status(g, now)
    return Badge(STATUS_FR.get(st, st), STATUS_TONE.get(st, ""))


def _desire(g: Goal, now: int, frame: Frame) -> Meter | str:
    if g.kind == c.PROJECT:
        return "engagement (ne s'use pas)"
    if g.kind != c.EXPLORATION or g.status in c.CLOSED_STATUSES:
        return "—"
    value = desire(g, now, params(frame.env.params_of("goals", frame.root)))
    suffix = " (figée : en pause)" if g.paused_at else ""
    return Meter(value, f"{value:.0%}{suffix}", "warn" if value < 0.3 else "")


def _steps(g: Goal) -> str:
    return f"{g.steps} / {g.max_steps}" if g.max_steps else "—"


def _due(g: Goal) -> When | str:
    return When(g.due) if g.due is not None else "—"


def _link(g: Goal, title: str = "") -> Ref:
    return Ref.subject("goal", str(g.id), title or f"#{g.id}")


def _step_badges(verdict: str, proven: bool, frame: Frame, wait_s: int, wait_for: str | None) -> tuple[Badge, Any]:
    shown = VERDICT_FR.get(verdict, verdict)
    if verdict == c.WAIT:
        shown += f" {int(wait_s) // 60} min" + (f", la réponse de {_who(frame, wait_for)}" if wait_for else "")
    proof: Any = "—"
    if verdict == c.DONE:
        proof = Badge("prouvé", "ok") if proven else Badge("sans preuve", "danger")
    return Badge(shown, VERDICT_TONE.get(verdict, "")), proof


def _journal_page(ctx: InspectContext, types: Sequence[Any], where: tuple[str, Any] | None,
                  cursor: str = "avant") -> tuple[list[Event[Any]], Pager]:
    """Une page du journal (``?<curseur>=`` : la suite, plus ancienne), et le curseur de la suivante."""
    found = ctx.events(types, HISTORY_PAGE + 1, where=where, before=ctx.int_param(cursor, 0) or None)
    page = found[:HISTORY_PAGE]
    older = ((cursor, str(page[-1].seq)),) if len(found) > HISTORY_PAGE else ()
    return page, Pager(param=cursor, size=HISTORY_PAGE, older=older)


def _subject_goal(s: GoalsState, ctx: InspectContext) -> Goal | Note:
    """Le but de la fiche, ou une note qui dit pourquoi il n'y en a pas."""
    if not ctx.subject:
        return Note("Cette vue se lit sur la fiche d'un but (Buts → un but).", tone="muted")
    g = goal_at(s, ctx.subject)
    if g is None:
        return Note(f"Aucun but « {ctx.subject} » en mémoire : jamais ouvert, ou clos depuis plus de sept jours "
                    "(le journal le garde).", tone="warn")
    return g


# ── L'objet « but » ───────────────────────────────────────────────────────


@GOALS.subject("goal", label="But", plural="Buts")
def _head(s: GoalsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    g = goal_at(s, key)
    if g is None:
        return None
    texts = _texts(ctx, (g.title_ref,))
    kind, authority = KIND_FR.get(g.kind, g.kind), AUTHORITY_FR.get(g.authority, g.authority)
    # l'en-tête se lit en texte : des instants dits en heure locale
    facts: list[tuple[str, Any]] = [("envie", _desire(g, frame.now, frame)), ("pas", _steps(g)),
                                    ("échéance", ctx.when(g.due) if g.due is not None else "—"),
                                    ("pour qui", _person(frame, g.owner))]
    if g.paused_at and g.status not in c.CLOSED_STATUSES:
        facts.append(("en pause depuis", ctx.when(g.paused_at)))
    return Head(str(g.id), _text(texts, g.title_ref, "(sans titre)"),
                subtitle=f"But n°{g.id} — {kind}, {authority}",
                badges=(Badge(kind, "info"), Badge(authority), _status(g, frame.now)), facts=tuple(facts))


@GOALS.search("goal")
def _search(s: GoalsState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    goals = sorted(s.goals.values(), key=lambda g: -g.id)
    texts = _texts(ctx, (g.title_ref for g in goals))
    wanted = _fold(text.strip())
    number = wanted.lstrip("#")
    out: list[Found] = []
    for g in goals:
        title = _text(texts, g.title_ref, "(sans titre)")
        if number.isdigit():
            if str(g.id) != number:
                continue
        elif wanted and wanted not in _fold(title):
            continue
        st = status(g, frame.now)
        out.append(Found(str(g.id), title, f"#{g.id} · {KIND_FR.get(g.kind, g.kind)} · {STATUS_FR.get(st, st)}"))
        if len(out) >= limit:
            break
    return out


# ── Buts : vivants, clos ──────────────────────────────────────────────────


def _filtered(goals: Iterable[Goal], ctx: InspectContext) -> list[Goal]:
    kind, authority = ctx.value("sorte") or "", ctx.value("autorite") or ""
    return [g for g in goals if (not kind or g.kind == kind) and (not authority or g.authority == authority)]


def _awaiting_approval(s: GoalsState, frame: Frame) -> tuple[int, str]:
    """Les buts vivants arrêtés sur un accord de l'opérateur."""
    waiting = {goal_of(v.context) for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER}
    n = sum(1 for g in s.goals.values() if g.id in waiting and live(g, frame.now))
    return n, "attendent ton accord"


def _stuck_recently(s: GoalsState, frame: Frame) -> tuple[int, str]:
    """Ce qu'on lui avait confié et qui a bloqué (ou échoué) depuis un jour."""
    n = sum(1 for g in s.goals.values() if g.authority == c.USER and g.status in (c.STUCK, c.FAILED)
            and frame.now - g.closed_at < DAY)
    return n, "confiés : bloqués ou en échec"


# ── Buts : les projets ────────────────────────────────────────────────────

#: une décision de l'arbitre se cherche par lots de tant de sélections, au plus tant de lots par page
SELECTED_SCAN = 200
SELECTED_SCAN_BATCHES = 10
STATE_PARAM = Param("etat", "État", kind="select", choices=((c.ACTIVE, "en cours"), (c.WAITING, "en attente"),
                                                              (c.PAUSED, "en pause")))
SENSITIVITY_FR = {0: "rien d'autrui", 1: "anodin", 2: "personnel", 3: "confidence"}


def agenda(rule: str) -> str:
    """Un agenda en mots (« toutes les 2 h ») ; une règle inconnue telle quelle."""
    rule = rule or "manual"
    return next((label for value, label in SCHEDULES if value == rule), rule)


def _progress(g: Goal, p: Any) -> Meter:
    most = g.max_steps or (p.project_steps if g.kind == c.PROJECT else p.exploration_steps)
    return Meter(g.steps / most if most else 0.0, f"{g.steps} / {most}")


def _freedom(g: Goal) -> Badge:
    return Badge("sort avec ton accord", "info") if g.approval else Badge("sort librement", "warn")


def _pending_goals(frame: Frame) -> set[int]:
    return {n for n in (goal_of(v.context) for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER)
            if n is not None}


PROJECT_COLUMNS = (Column("projet"), Column("pour qui"), Column("statut", "fit"), Column("avancement", "fit"),
                   Column("prochain pas", "fit"), Column("échéance", "fit"), Column("agenda"),
                   Column("ce qui sort", hint="un mail, une commande avec le réseau : avec ton accord, ou librement"),
                   Column("consignes", "num"), Column("où elle en est"))


@GOALS.inspect("projets", title="Projets", section="buts", order=5, params=[STATE_PARAM, AUTHORITY_PARAM],
               description="Les projets qu'elle mène : leur état, leur avancement, leur agenda et ce qu'ils ont le "
                           "droit de faire. Une ligne ouvre le projet : son cadre, ses pas, ses décisions, ses "
                           "prompts, son atelier.")
def _projects_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    now = frame.now
    p = params(frame.env.params_of("goals", frame.root))
    projects = sorted((g for g in s.goals.values() if g.kind == c.PROJECT), key=lambda g: -g.id)
    alive = [g for g in projects if live(g, now)]
    closed = [g for g in projects if g.status in c.CLOSED_STATUSES]
    waiting = _pending_goals(frame)
    wanted, authority = str(ctx.value("etat") or ""), str(ctx.value("autorite") or "")
    shown = [g for g in alive if (not wanted or status(g, now) == wanted or (wanted == c.PAUSED and g.paused_at))
             and (not authority or g.authority == authority)]
    page, pager = paginate(shown, ctx.pager(size=GOALS_PAGE, total=len(shown)))
    texts = _texts(ctx, [r for g in (*page, *closed) for r in (g.title_ref, g.summary_ref, g.result_ref) if r])
    rows = []
    for g in page:
        nxt = next_step_at(g, s, frame)
        rows.append(Row((
            _link(g, _text(texts, g.title_ref, "(sans titre)")), _person(frame, g.owner), _status(g, now),
            _progress(g, p), ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—",
            _due(g), agenda(g.schedule), _freedom(g), len(g.instructions),
            Text(_text(texts, g.summary_ref, "pas encore de pas"), clamp=160)),
            href=_link(g), tone="warn" if g.paused_at else "info" if g.id in waiting else ""))
    done = [g for g in closed if g.status == c.ACHIEVED]
    blocks: list[Block] = [
        Stats((Stat("En cours", sum(1 for g in alive if status(g, now) == c.ACTIVE and not g.paused_at)),
               Stat("En attente", sum(1 for g in alive if status(g, now) == c.WAITING), "d'une réponse ou d'un délai"),
               Stat("En pause", sum(1 for g in alive if g.paused_at), "par un opérateur",
                    "warn" if any(g.paused_at for g in alive) else ""),
               Stat("Attendent ton accord", sum(1 for g in alive if g.id in waiting), "pour faire sortir quelque chose",
                    "warn" if any(g.id in waiting for g in alive) else "", APPROVALS),
               Stat("Clos (7 jours)", len(closed), f"{len(done)} abouti(s), {len(closed) - len(done)} arrêté(s)"))),
        Table(PROJECT_COLUMNS, tuple(rows), title="Projets en cours", pager=pager,
              empty="aucun projet avec ces filtres" if wanted or authority else
              "aucun projet en cours : « Confier un projet » en ouvre un",
              caption=f"Un projet avance d'un pas au plus toutes les {p.project_spacing_us // MINUTE} min, "
                      f"{p.steps_per_hour} pas par heure au plus pour tous ses buts (Configuration › Comportement "
                      "› Buts)."),
    ]
    if closed:
        blocks.append(Table((Column("projet"), Column("pour qui"), Column("issue", "fit"), Column("clos", "fit"),
                             Column("pas", "num"), Column("résultat")), tuple(
            Row((_link(g, _text(texts, g.title_ref, "(sans titre)")), _person(frame, g.owner), _status(g, now),
                 When(g.closed_at), g.steps, Text(_text(texts, g.result_ref), clamp=200)), href=_link(g))
            for g in sorted(closed, key=lambda g: -g.closed_at)),
            title="Projets clos ces sept derniers jours",
            caption="Plus anciens : l'onglet Clos (filtre « projet »), lu dans le journal."))
    return blocks


LIVE_COLUMNS = (Column("but", "fit"), Column("titre"), Column("sorte"), Column("autorité"), Column("statut"),
                Column("envie", hint="une exploration : son envie s'use ; un projet : un engagement"),
                Column("pas", "num"), Column("prochain pas"), Column("échéance"), Column("pour qui"))


@GOALS.inspect("vivants", title="Tous les buts vivants", section="buts", order=10, params=[KIND_PARAM, AUTHORITY_PARAM],
               badge=_awaiting_approval, description="Ce qu'elle a en train : actif, en attente, ou en pause.")
def _live_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    now = frame.now
    p = params(frame.env.params_of("goals", frame.root))
    every = sorted((g for g in s.goals.values() if live(g, now)), key=lambda g: -g.id)
    chosen = _filtered(every, ctx)
    page, pager = paginate(chosen, ctx.pager(size=GOALS_PAGE, total=len(chosen)))
    texts = _texts(ctx, (g.title_ref for g in page))
    rows = []
    for g in page:
        nxt = next_step_at(g, s, frame) if g.kind != c.REMINDER else None
        rows.append(Row((
            _link(g), _text(texts, g.title_ref, "(sans titre)"), KIND_FR.get(g.kind, g.kind),
            AUTHORITY_FR.get(g.authority, g.authority), _status(g, now), _desire(g, now, frame), _steps(g),
            ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—", _due(g),
            _person(frame, g.owner)), href=_link(g), tone="warn" if g.paused_at else ""))
    recent = sum(1 for t in s.steps_at if now - t < HOUR)
    ready = ready_to_undertake(s, p)
    filtered = bool(ctx.value("sorte") or ctx.value("autorite"))
    return [
        Fields((
            ("vivants", len(every)),
            ("en pause", sum(1 for g in every if g.paused_at)),
            ("pas dans l'heure", f"{recent} / {p.steps_per_hour}"),
            ("entreprendre d'elle-même", When(ready) if ready > now else "possible"),
            ("dernier blocage sur ce qu'elle avait entrepris", When(s.self_stuck_at) if s.self_stuck_at else "—"),
        ), title="Ce qu'elle a entrepris", columns=2),
        Table(LIVE_COLUMNS, tuple(rows), title="Buts vivants", pager=pager, filters=("sorte", "autorite"),
              empty="aucun but avec ces filtres" if filtered else "aucun but en cours"),
    ]


CLOSED_COLUMNS = (Column("but", "fit"), Column("titre"), Column("sorte"), Column("autorité"), Column("issue"),
                  Column("clos"), Column("raison ou résultat"), Column("pour qui"))


def _closed_page(ctx: InspectContext, kind: str, authority: str) -> tuple[list[Event[Any]], str, bool]:
    """Une page de clôtures : la sorte filtre au journal, l'autorité après coup —
    on lit donc par lots jusqu'à remplir la page. Rend (la page, le curseur de
    la suivante, si la lecture s'est arrêtée au plafond de lots avant de la remplir)."""
    where = ("kind", kind) if kind else None
    size = CLOSED_SCAN if authority else GOALS_PAGE + 1
    cursor = ctx.int_param("avant", 0) or None
    shown: list[Event[Any]] = []
    for _ in range(CLOSED_SCAN_BATCHES):
        batch = ctx.events([c.GOAL_CLOSED], size, where=where, before=cursor)
        for e in batch:
            cursor = e.seq
            if authority and e.data.authority != authority:
                continue
            shown.append(e)
            if len(shown) > GOALS_PAGE:  # un de plus : il y a une suite, qui reprend après le dernier montré
                return shown[:GOALS_PAGE], str(shown[GOALS_PAGE - 1].seq), False
        if len(batch) < size:  # le journal est lu jusqu'au bout
            return shown, "", False
    # le plafond de lecture atteint sans remplir la page : la suite reprend là où la lecture s'est arrêtée
    return shown, str(cursor) if cursor else "", True


@GOALS.inspect("clos", title="Clos", section="buts", order=20, params=[KIND_PARAM, AUTHORITY_PARAM],
               badge=_stuck_recently, description="Ce qu'elle a mené à bout, bloqué, abandonné, ou qu'on a annulé.")
def _closed_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    kind, authority = ctx.value("sorte") or "", ctx.value("autorite") or ""
    found, cursor, stopped = _closed_page(ctx, kind, authority)
    rows = []
    for e in found:
        d = e.data
        kept = s.goals.get(d.goal)
        link = _link(kept) if kept is not None else Ref("event", str(e.seq), f"#{d.goal}")
        result = _said(d.result, "") or d.reason or "—"
        rows.append(Row((
            link, _said(d.title, "(sans titre)"), KIND_FR.get(d.kind, d.kind), AUTHORITY_FR.get(d.authority, d.authority),
            Badge(STATUS_FR.get(d.status, d.status), STATUS_TONE.get(d.status, "")), When(e.at),
            Text(result, clamp=SUMMARY_CLAMP), _person(frame, d.owner)), href=link))
    older = (("avant", cursor),) if cursor else ()
    empty = "aucun but clos avec ces filtres" if (kind or authority) else "aucun but clos"
    caption = (f"Recherche arrêtée après {CLOSED_SCAN * CLOSED_SCAN_BATCHES} clôtures relues sans remplir la page : "
               "« Plus anciens » la reprend là où elle s'est arrêtée.") if stopped else ""
    return [
        Table(CLOSED_COLUMNS, tuple(rows), title="Buts clos", pager=Pager(param="avant", size=GOALS_PAGE, older=older),
              filters=("sorte", "autorite"), empty=empty if not stopped else "rien dans cette tranche du journal",
              caption=caption),
        Note("Un but clos depuis plus de sept jours n'a plus de fiche : son lien mène à l'événement qui l'a clos.",
             tone="muted"),
    ]


# ── La fiche : résumé ─────────────────────────────────────────────────────


def _fields(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext, texts: Mapping[str, str]) -> Fields:
    now = frame.now
    current = status(g, now)
    pairs: list[tuple[str, Any]] = [
        ("titre", _text(texts, g.title_ref, "(sans titre)")),
        ("sorte", KIND_FR.get(g.kind, g.kind)),
        ("autorité", AUTHORITY_FR.get(g.authority, g.authority)),
        ("statut", _status(g, now)),
    ]
    if current == c.ACTIVE and g.status == c.WAITING:
        pairs.append(("statut enregistré", "en attente (l'attente est échue)"))
    if g.details_ref:
        pairs.append(("cadre (confié, elle ne le change pas)", Text(_text(texts, g.details_ref), clamp=600)))
    pairs += [
        ("personne concernée", _person(frame, g.owner)),
        ("où lui parler", _who(frame, g.address)),
        ("concerne", ", ".join(_who(frame, a) for a in g.about) or "—"),
        ("sensibilité", g.sensitivity),
        ("d'où il vient", g.source or "—"),
        ("ouvert", Ref("event", str(g.id), ctx.when(g.opened_at))),
        ("envie", _desire(g, now, frame)),
        ("pas", _steps(g)),
        ("outils", ", ".join(g.bundles) or "—"),
        ("consignes reçues", len(g.instructions)),
    ]
    if g.paused_at:
        pairs.append(("en pause depuis", When(g.paused_at)))
    if g.kind == c.REMINDER:
        pairs += [
            ("échéance", _due(g) if not g.urgent else f"{ctx.when(g.due or 0)} (urgent)"),
            ("dit", "oui" if g.delivered else "pas encore"),
            ("tentatives", g.attempts),
            ("prochain essai", When(g.retry_at) if g.retry_at > now else "—"),
        ]
    else:
        nxt = next_step_at(g, s, frame) if current in (c.ACTIVE, c.WAITING) else None
        pairs += [
            ("prochain pas", ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—"),
            ("dernier pas", When(g.last_step_at) if g.last_step_at else "—"),
            ("sans verdict d'affilée", g.silent),
            ("« fini » sans preuve", g.unproven),
            ("pannes d'affilée", g.failures),
            ("preuves (outils qui ont produit)", g.evidence),
            ("où elle en est", Text(_text(texts, g.summary_ref), clamp=600)),
        ]
        if g.kind == c.PROJECT:
            pairs += [("échéance", _due(g)), ("agenda", g.schedule or "manuel"),
                      ("accord requis pour sortir", "oui" if g.approval else "non")]
    if g.status in c.CLOSED_STATUSES:
        pairs += [
            ("clos", When(g.closed_at)),
            ("résultat", _text(texts, g.result_ref)),
            ("notable", f"{g.notable:.1f}"),
            ("raconté", "oui" if g.shared else f"non ({g.share_attempts} essai(s))"),
        ]
    return Fields(tuple(pairs), title=f"But n°{g.id}", columns=2)


def _wait_table(g: Goal, frame: Frame) -> Table:
    rows = []
    if g.status == c.WAITING:
        whom = f"la réponse de {_who(frame, g.wait_for)}" if g.wait_for else "rien de nominatif (un délai)"
        state = "échue : il reprend" if g.waiting_until <= frame.now else "en cours"
        rows.append((whom, When(g.waiting_since) if g.waiting_since else "—", When(g.waiting_until), state))
    return Table(("elle attend", "depuis", "jusqu'à", "état"), tuple(rows), title="Attente",
                 empty="elle n'attend rien")


@GOALS.inspect("resume", title="Résumé", subject="goal", order=10)
def _summary_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    texts = _texts(ctx, (g.title_ref, g.details_ref, g.summary_ref, g.result_ref))
    blocks: list[Block] = []
    if g.paused_at and g.status not in c.CLOSED_STATUSES:
        blocks.append(Note("En pause : ni pas, ni rappel, ni usure de l'envie, jusqu'à ce qu'un opérateur le "
                           "reprenne.", tone="warn"))
    return [*blocks, _fields(g, s, frame, ctx, texts), _wait_table(g, frame)]


# ── La fiche : cadre et politique ─────────────────────────────────────────


@GOALS.inspect("politique", title="Cadre et politique", subject="goal", order=15,
               description="Ce qui encadre son travail : le cadre confié, les consignes, ce qu'elle a le droit de "
                           "faire, son rythme, quand elle s'arrête, pour qui.")
def _policy_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    now = frame.now
    p = params(frame.env.params_of("goals", frame.root))
    texts = _texts(ctx, (g.details_ref, *g.instructions))
    most = g.max_steps or (p.project_steps if g.kind == c.PROJECT else p.exploration_steps)
    spacing = p.project_spacing_us if g.kind == c.PROJECT else p.step_spacing_us
    nxt = next_step_at(g, s, frame) if status(g, now) in (c.ACTIVE, c.WAITING) and g.kind != c.REMINDER else None
    waiting = g.id in _pending_goals(frame)
    blocks: list[Block] = [
        Prose(_text(texts, g.details_ref), title="Le cadre (elle le lit à chaque pas, ne le change jamais)")
        if g.details_ref else Note("Aucun cadre écrit : elle suit le titre, et les consignes s'il y en a.", "muted"),
    ]
    if g.instructions:
        blocks.append(Table((Column("n°", "fit"), Column("consigne")), tuple(
            (i + 1, Text(_text(texts, ref), clamp=400)) for i, ref in enumerate(reversed(g.instructions))),
            title=f"Consignes reçues ({len(g.instructions)}, la plus récente d'abord — elle prime)"))
    blocks += [
        Fields((
            ("ce qui sort de la machine", _freedom(g)),
            ("un accord attend", Ref("local", "/inspecteur/approbations", "oui : ouvrir les approbations")
             if waiting else "non"),
            ("ses outils", ", ".join(g.bundles) or "ceux de l'atelier"),
            ("autorité", f"{AUTHORITY_FR.get(g.authority, g.authority)} — " +
             ("un opérateur l'a confié : elle le mène même sans envie" if g.authority == c.USER else
              "elle l'a entrepris d'elle-même : son envie s'use, elle peut l'abandonner")),
        ), title="Sa liberté", columns=2),
        Fields((
            ("agenda", f"{agenda(g.schedule)} ({g.schedule or 'manual'})"),
            ("prochain pas", ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—"),
            ("échéance", _due(g)),
            ("pas", f"{g.steps} faits sur {most} au plus" + ("" if g.max_steps else " (valeur par défaut)")),
            ("espacement des pas", f"{spacing // MINUTE} min au moins"),
            ("pas par heure (tous buts)", f"{p.steps_per_hour} au plus"),
            ("attente", f"de {p.wait_min_us // MINUTE} min à {p.wait_max_us // HOUR} h quand elle attend"),
        ), title="Son rythme", columns=2),
        Fields((
            ("sans verdict d'affilée", f"{g.silent} (bloqué à {p.silent_before_blocked})"),
            ("pannes d'affilée", f"{g.failures} (en échec à {p.failures_before_failed})"),
            ("« fini » sans preuve", g.unproven),
            ("pas au plus", most),
        ), title="Quand elle s'arrête", columns=2),
        Fields((
            ("pour qui", _person(frame, g.owner)), ("où lui en parler", _who(frame, g.address)),
            ("concerne", ", ".join(_who(frame, a) for a in g.about) or "—"),
            ("sensibilité", SENSITIVITY_FR.get(g.sensitivity, str(g.sensitivity))),
            ("d'où il vient", g.source or "—"),
        ), title="Pour qui, et ce qu'elle peut en dire", columns=2),
        Note("Les réglages communs à tous les buts (espacement, pas au plus, pannes avant échec…) se changent dans "
             "Configuration › Comportement › Buts ; ce projet-ci se pilote par les actions de sa fiche (pause, "
             "consigne, clore).", "muted"),
    ]
    return blocks


# ── La fiche : pas ────────────────────────────────────────────────────────


STEP_COLUMNS = (Column("quand", "fit"), Column("verdict"), Column("preuve"), Column("résumé"),
                Column("outils utilisés"), Column("notable", "num"), Column("", "fit"))


@GOALS.inspect("pas", title="Pas", subject="goal", order=20)
def _steps_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    rows = []
    found, pager = _journal_page(ctx, [c.STEP_REPORTED], ("goal", g.id))
    for e in found:
        d = e.data
        verdict, proof = _step_badges(str(d.verdict), bool(d.proven), frame, int(d.wait_s), d.wait_for)
        rows.append(Row((When(e.at), verdict, proof, Text(_said(d.summary), clamp=SUMMARY_CLAMP),
                         ", ".join(d.tools) or "—", f"{float(d.notable):.1f}",
                         Ref("episode", e.correlation, "épisode"))))
    blocks: list[Block] = [
        Fields((("pas faits", _steps(g)), ("sans verdict d'affilée", g.silent), ("« fini » sans preuve", g.unproven),
                ("preuves", g.evidence)), title="Où il en est", columns=2),
        Table(STEP_COLUMNS, tuple(rows), title="Ses pas", empty="aucun pas rapporté", pager=pager),
    ]
    return blocks


# ── La fiche : carnet ─────────────────────────────────────────────────────


@GOALS.inspect("carnet", title="Carnet", subject="goal", order=30)
def _notebook_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    orders, orders_pager = _journal_page(ctx, [GOAL_AMENDED], ("goal", g.id))
    notes, notes_pager = _journal_page(ctx, [NOTED], ("goal", g.id), NOTES_CURSOR)
    return [
        Timeline(tuple(Entry(e.at, "consigne", _said(e.data.instruction),
                             meta=f"de {_who(frame, e.data.by)}" if e.data.by else "", tone="info",
                             href=Ref("event", str(e.seq), "consigne"))
                       for e in orders), title="Consignes reçues", empty="aucune consigne", pager=orders_pager),
        Timeline(tuple(Entry(e.at, "note", _said(e.data.text), href=Ref("episode", e.correlation, "note"))
                       for e in notes), title="Son carnet", empty="aucune note", pager=notes_pager),
    ]


# ── La fiche : effets ─────────────────────────────────────────────────────


def _effect_state(proposal: Event[Any], pending: bool, outcomes: Sequence[Event[Any]]) -> tuple[Badge, str]:
    """Ce qu'est devenue une proposition : (état, détail)."""
    if pending:
        return Badge("attend ton accord", "warn"), ""
    executed = next((o for o in outcomes if o.type.name == rt.EFFECT_EXECUTED.name), None)
    resolved = next((o for o in outcomes if o.type.name == rt.EFFECT_RESOLVED.name), None)
    if executed is not None:
        return (Badge("fait", "ok") if executed.data.ok else Badge("échoué", "danger")), executed.data.result
    if resolved is not None and not resolved.data.approved:
        note = f" : « {resolved.data.note} »" if resolved.data.note else ""
        return Badge("refusé", "muted"), f"par {resolved.data.by or 'un opérateur'}{note}"
    if resolved is not None:
        return Badge("approuvé, en cours", "info"), f"par {resolved.data.by or 'un opérateur'}"
    if not proposal.data.approval:
        return Badge("lancé sans accord", "info"), ""
    return Badge("inconnu", "muted"), "aucune décision n'est enregistrée pour cette demande"


def _cut(text: str, n: int) -> str:
    """Un texte borné, qui dit qu'il l'est."""
    return text if len(text) <= n else text[:n] + f"\n[… coupé à {n} caractères …]"


EFFECT_COLUMNS = (Column("proposition", "fit"), Column("quand", "fit"), Column("capacité"), Column("résumé"),
                  Column("accord"), Column("état"))


@GOALS.inspect("effets", title="Effets", subject="goal", order=40)
def _effects_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    pending = {v.proposal for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and goal_of(v.context) == g.id}
    proposed, pager = _journal_page(ctx, [rt.EFFECT_PROPOSED], ("context", goal_target(g.id)))
    wanted = {e.seq for e in proposed}
    outcomes: dict[int, list[Event[Any]]] = {}
    if wanted:
        for e in ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], OUTCOMES_SCANNED):
            if e.data.proposal in wanted:
                outcomes.setdefault(e.data.proposal, []).append(e)
        # une demande plus ancienne que ces décisions : son issue, relue pour elle seule
        for seq in sorted(wanted - outcomes.keys() - pending):
            found = ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], 4, where=("proposal", seq))
            if found:
                outcomes[seq] = found
    rows = []
    for e in proposed:
        state, detail = _effect_state(e, e.seq in pending, outcomes.get(e.seq, ()))
        rows.append(Row((Ref("event", str(e.seq), f"#{e.seq}"), When(e.at), e.data.capability,
                         Text(_said(e.data.summary), clamp=SUMMARY_CLAMP),
                         "requis" if e.data.approval else "non requis", state),
                        tone="warn" if e.seq in pending else "",
                        detail=(Code(_cut(detail, EFFECT_DETAIL), title="ce qu'il en est"),) if detail else ()))
    blocks: list[Block] = []
    if pending:
        blocks.append(Fields(((f"{len(pending)} demande(s) attendent ton accord", APPROVALS),),
                             title="À décider"))
    blocks.append(Table(EFFECT_COLUMNS, tuple(rows), title="Ce qu'il a voulu faire sortir de la machine",
                        empty="aucune demande : tout s'est fait dans l'atelier", pager=pager))
    return blocks


# ── La fiche : épisodes ───────────────────────────────────────────────────


def _episode_kind(d: rt.EpisodeStarted) -> str:
    kind = str(d.kind)
    if kind == Kind.STEP:
        return "pas de travail"
    reasons = str(d.reason).split(",")
    if c.REMIND in reasons:
        return "dire le rappel"
    if c.SHARE in reasons:
        return "raconter"
    return kind.lower()


def _started(g: Goal, ctx: InspectContext) -> tuple[list[Event[Any]], Pager]:
    """Une page des épisodes de ce but : ceux qu'il vise (ses pas), et ceux qui
    portent sur lui en visant quelqu'un (le rappel, le récit). Deux lectures
    fusionnées : chacune rend un de plus que la page, la page prend les plus
    récents de l'union, et la suite reprend après le dernier montré."""
    target = goal_target(g.id)
    before = ctx.int_param("avant", 0) or None
    found = {e.seq: e for field in ("target", "subject")
             for e in ctx.events([rt.EPISODE_STARTED], HISTORY_PAGE + 1, where=(field, target), before=before)}
    ordered = [found[seq] for seq in sorted(found, reverse=True)]
    page = ordered[:HISTORY_PAGE]
    older = (("avant", str(page[-1].seq)),) if len(ordered) > HISTORY_PAGE else ()
    return page, Pager(param="avant", size=HISTORY_PAGE, older=older)


def _outcomes(started: list[Event[Any]], ctx: InspectContext) -> dict[str, str]:
    """L'issue de ces épisodes, par corrélation."""
    corrs = [e.correlation for e in started]
    ended = ctx.events([rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)
    return {e.correlation: str(e.data.outcome) for e in ended}


def _episode_tab(corr: str, tab: str, text: str) -> Ref:
    return Ref("episode", corr, text, (("onglet", tab),))


@GOALS.inspect("episodes", title="Épisodes et prompts", subject="goal", order=50,
               description="Chaque fois qu'elle y a travaillé (ou en a parlé) : le résultat du pas, et de quoi relire "
                           "le prompt exact, les outils appelés, les appels de modèle et la décision.")
def _episodes_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    target = goal_target(g.id)
    started, pager = _started(g, ctx)
    outcomes = _outcomes(started, ctx)
    corrs = [e.correlation for e in started]
    reported = {e.correlation: e.data for e in ctx.events([c.STEP_REPORTED], len(corrs) + 1, correlations=corrs)} \
        if corrs else {}
    rows = []
    for e in started:
        outcome = outcomes.get(e.correlation)
        towards = e.data.target if e.data.target != target else None
        issue = (Badge(OUTCOME_FR.get(outcome, outcome), OUTCOME_TONE.get(outcome, "")) if outcome
                 else Badge("en cours", "info"))
        step = reported.get(e.correlation)
        result: Any = Text(_said(step.summary), clamp=SUMMARY_CLAMP) if step is not None else "—"
        verdict: Any = Badge(VERDICT_FR.get(str(step.verdict), str(step.verdict)),
                             VERDICT_TONE.get(str(step.verdict), "")) if step is not None else "—"
        rows.append(Row((When(e.at), _episode_kind(e.data), _who(frame, towards) if towards else "—", issue,
                         verdict, result, _episode_tab(e.correlation, "prompt", "prompt"),
                         _episode_tab(e.correlation, "outils", "outils"), _episode_tab(e.correlation, "appels", "appels"),
                         _episode_tab(e.correlation, "decision", "décision")),
                        href=Ref("episode", e.correlation, "")))
    return [Table((Column("quand", "fit"), "épisode", "vers", Column("issue", "fit"), Column("verdict", "fit"),
                   "résultat", Column("", "fit"), Column("", "fit"), Column("", "fit"), Column("", "fit")),
                  tuple(rows), title="Ses épisodes", empty="aucun épisode encore", pager=pager,
                  caption="« prompt » : ce qu'elle a vraiment reçu (persona, cadre, carnet, fil) et ce qu'elle a "
                          "répondu ; « outils » : chaque appel et son résultat ; « décision » : pourquoi ce pas-là.")]


# ── La fiche : décisions ──────────────────────────────────────────────────


@GOALS.inspect("decisions", title="Décisions", subject="goal", order=45,
               description="Chaque fois que l'arbitre a pesé ce but : ses preuves (l'envie, l'échéance, l'agenda…), "
                           "son score, et s'il a été choisi.")
def _decisions_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    target = goal_target(g.id)
    before = ctx.int_param("avant", 0) or None
    found: list[tuple[Event[Any], Any]] = []
    cursor, exhausted = before, False
    for _ in range(SELECTED_SCAN_BATCHES):  # lire par lots jusqu'à remplir la page
        batch = ctx.events([SELECTED], SELECTED_SCAN, before=cursor)
        for e in batch:
            mine = next((r for r in e.data.rows if r.target == target), None)
            if mine is not None:
                found.append((e, mine))
                if len(found) > HISTORY_PAGE:
                    break
        if len(found) > HISTORY_PAGE or len(batch) < SELECTED_SCAN:
            exhausted = len(batch) < SELECTED_SCAN
            break
        cursor = batch[-1].seq
    page = found[:HISTORY_PAGE]
    rows = []
    for e, r in page:
        fired = f"{r.kind}:{r.target}" in e.data.fired
        parts = "\n".join(f"{owner} · {reason}  {value:+.2f}" for owner, reason, value in r.parts) or "—"
        detail = (Fields((("preuves", Text(parts, "mono")), ("décalage", f"{r.shift:+.2f}"),
                          ("attente", f"{getattr(r, 'aging', 0.0):+.2f}"),
                          ("seuil", f"{-getattr(r, 'threshold', 0.0):+.2f}"),
                          ("vetos", ", ".join(f"{o} ({why})" for o, why in r.vetoes) or "aucun"),
                          ("choisi ce jour-là", ", ".join(e.data.fired) or "rien")), title="Du signal au score"),)
        rows.append(Row((When(e.at), Badge("choisi", "ok") if fired else Badge("en lice", "muted"),
                         Text(f"{r.score:+.2f}", "num", "ok" if r.score > 0 else ""), f"{r.hazard * 3600:.2f} /h",
                         Badge(", ".join(o for o, _ in r.vetoes), "danger") if r.vetoes else "—",
                         Text(", ".join(f"{reason} {value:+.1f}" for _o, reason, value in r.parts[:3]) or "—", "muted"),
                         Ref("event", str(e.seq), f"n° {e.seq}")), href=Ref("event", str(e.seq), ""), detail=detail,
                        tone="ok" if fired else ""))
    # la suite reprend après la dernière montrée ; un lot épuisé sans remplir la page reprend où la lecture s'est
    # arrêtée (le journal continue plus loin)
    resume = str(page[-1][0].seq) if len(found) > HISTORY_PAGE and page else \
        (str(cursor) if not exhausted and cursor is not None and len(found) <= HISTORY_PAGE else "")
    pager = Pager(param="avant", size=HISTORY_PAGE, older=(("avant", resume),) if resume else ()) \
        if resume or before else None
    return [Table((Column("quand", "fit"), Column("", "fit"), Column("score", "num"), Column("taux", "num"),
                   Column("vetos", "fit"), Column("preuves principales"), Column("sélection", "fit")), tuple(rows),
                  title="Ce que l'arbitre en a pensé", pager=pager,
                  empty="plus rien avant" if before else "l'arbitre ne l'a encore jamais pesé (ou pas dans les "
                                                          "sélections gardées au journal)",
                  caption="Une ligne par tirage où ce but était parmi les premiers en lice : « choisi » a donné un "
                          "pas (ou un rappel, un récit). La table complète du moment : Décisions › Ses choix.")]


# ── La fiche : atelier ────────────────────────────────────────────────────


_TREE_LINE = re.compile(r"^(?P<path>.+) \((?P<size>\d+) o\)$")


def _commit_title(summary: str) -> str:
    """Le titre du commit qu'un pas a laissé (comme l'atelier le forme)."""
    return re.sub(r"\s+", " ", summary).strip()[:72]


@GOALS.inspect("atelier", title="Atelier", subject="goal", order=60)
async def _workshop_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    if "workshop" not in g.bundles:
        return [Note("Ce but n'a pas d'atelier : seuls les projets confiés en ont un (un dossier, des programmes "
                     "isolés).", tone="muted")]
    port = ctx.ports.get("workshop")
    if port is None:
        return [Note("L'atelier n'est pas disponible ici (aucun port d'atelier).", tone="warn")]
    if not port.exists(g.id):
        return [Note("L'atelier n'est pas encore ouvert : aucun pas n'y a encore écrit.", tone="muted")]
    tree = await port.tree(g.id)
    diff = await port.diff(g.id)
    log = await port.log(g.id, LOG_MAX)
    files = []
    for line in tree:
        m = _TREE_LINE.match(line)
        files.append((Text(m.group("path"), "mono"), f"{int(m.group('size'))} o") if m else (Text(line, "muted"), ""))
    steps = ctx.events([c.STEP_REPORTED], STEPS_MATCHED, where=("goal", g.id))
    by_title = {}
    for e in reversed(steps):  # le plus récent l'emporte
        if e.data.summary.text is not None:
            by_title[_commit_title(e.data.summary.text)] = e
    entries = []
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    for line in lines:
        sha, _, title = line.partition(" ")
        step = by_title.get(title)
        if step is not None:
            entries.append(Entry(step.at, title or "(sans message)", meta=sha,
                                 href=Ref("episode", step.correlation, title)))
        else:  # l'enregistrement ne dit pas sa date : sans pas pour la porter, il n'en a pas ici
            entries.append(Entry(0, title or "(sans message)", meta=f"{sha} · sans pas associé"))
    shown = _cut(diff, DIFF_SHOWN)
    return [
        Table((Column("fichier"), Column("taille", "num")), tuple(files), title="Ses fichiers",
              empty="le dossier est vide"),
        Code(shown, title="Changements depuis le dernier pas") if diff.strip()
        else Note("Rien de changé depuis le dernier pas : tout est enregistré.", tone="muted"),
        Timeline(tuple(entries), title="Historique (un enregistrement par pas qui a changé quelque chose)",
                 empty="aucun enregistrement encore"),
        *([Note(f"Seuls les {LOG_MAX} derniers enregistrements sont relus.", tone="muted")]
          if len(lines) >= LOG_MAX else []),
    ]


# ── Sur la fiche d'une personne ───────────────────────────────────────────


PERSON_COLUMNS = (Column("but", "fit"), Column("titre"), Column("sorte"), Column("statut"), Column("lien"),
                  Column("ouvert"))


@GOALS.inspect("buts", title="Buts", subject="person", order=70,
               description="Ce qu'elle a entrepris pour cette personne, ou à son sujet.")
def _person_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Cette vue se lit sur la fiche d'une personne.", tone="muted")]
    handles = {person, *frame.get(identity_c.HANDLES(person))}
    concerned = sorted((g for g in s.goals.values()
                        if g.owner in handles or g.address in handles or handles & set(g.about)),
                       key=lambda g: (not live(g, frame.now), -g.id))
    page, pager = paginate(concerned, ctx.pager(size=GOALS_PAGE, total=len(concerned)))
    texts = _texts(ctx, (g.title_ref for g in page))
    rows = []
    for g in page:
        link = ("pour elle ou lui" if g.owner in handles else "à qui le dire" if g.address in handles
                else "la concerne")
        rows.append(Row((_link(g), _text(texts, g.title_ref, "(sans titre)"), KIND_FR.get(g.kind, g.kind),
                         _status(g, frame.now), link, When(g.opened_at)), href=_link(g)))
    return [Table(PERSON_COLUMNS, tuple(rows), title="Ses buts", pager=pager,
                  empty="rien d'entrepris pour cette personne ni à son sujet")]
