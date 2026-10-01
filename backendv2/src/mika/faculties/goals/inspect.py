"""Ce que les buts montrent à un opérateur.

- **La fiche d'un but** (type d'objet ``goal``, clé = son numéro) : son
  résumé, ses séances et leurs verdicts, son carnet et les consignes reçues,
  ses épisodes et ce que l'arbitre en a pensé.
- **Buts** : les vivants (actifs, en attente, en pause) et les clos. Les
  projets ont leur menu à eux (``projects``, ADR 0031).
- **Sur la fiche d'une personne** : les buts qui la concernent.

Les vues se lisent ; les formulaires qu'elles posent (``ActionSlot`` : reprogrammer, la priorité, le
plan de travail) passent par les actions d'opérateur (``actions.py``). Les compteurs et l'envie viennent de la tranche (calculés comme
la faculté les calcule) ; l'historique (séances, notes, consignes, effets,
épisodes, clôtures), du journal — la tranche n'en garde que l'essentiel. Un
contenu oublié s'affiche « (oublié) ».
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.goals.actions import (
    PRIORITY_CHOICES,
    TASK_STATUS_FR,
    _plannable,
    _prioritizable,
    _reopenable,
    _reschedulable,
)
from mika.faculties.goals.faculty import (
    GOAL_AMENDED,
    GOALS,
    NOTED,
    OPERATIONS,
    Goal,
    GoalsState,
    budget,
    desire,
    goal_at,
    live,
    params,
    ready_to_undertake,
    status,
)
from mika.faculties.goals.work import next_step_at, why_not_now
from mika.kernel.builtin import SELECTED
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
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
    Table,
    Text,
    Timeline,
    Toolbar,
    When,
    paginate,
)
from mika.vocab.episodes import Kind, goal_target

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
SUMMARY_CLAMP = 280
FORGOTTEN = "(oublié)"
#: les approbations, dans la console
APPROVALS = Ref("local", "/inspecteur/approbations", "ouvrir les approbations")

#: ``project`` : un ancien projet, d'avant les projets à part (ADR 0031), relu au rejeu
KIND_FR = {c.REMINDER: "rappel", c.EXPLORATION: "exploration", c.PROJECT: "ancien projet"}
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
    """Une personne par son nom (le compte, ou ce qu'elle a dit s'appeler) ; sa clé seulement sans nom."""
    if not key:
        return "—"
    return _name(frame, key) or key


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
    p = params(frame.env.params_of("goals", frame.root))
    # l'en-tête se lit en texte : des instants dits en heure locale
    facts: list[tuple[str, Any]] = []
    if g.kind != c.REMINDER:
        facts += [("avancement", _plan_progress(g, p)), ("prochaine séance", _next_words(g, s, frame, ctx))]
    if g.kind == c.EXPLORATION:
        facts.append(("envie", _desire(g, frame.now, frame)))
    facts += [("échéance", ctx.when(g.due) if g.due is not None else "—"), ("pour qui", _person(frame, g.owner))]
    if g.paused_at and g.status not in c.CLOSED_STATUSES:
        facts.append(("en pause depuis", ctx.when(g.paused_at)))
    badges = [Badge(kind, "info"), Badge(authority), _status(g, frame.now)]
    if g.priority != c.NORMAL:
        badges.append(_priority(g))
    return Head(str(g.id), _text(texts, g.title_ref, "(sans titre)"),
                subtitle=f"But n°{g.id} — {kind}, {authority}", badges=tuple(badges), facts=tuple(facts),
                default_tab="resume")


@GOALS.search("goal")
def _search(s: GoalsState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    goals = sorted(s.goals.values(), key=lambda g: -g.id)
    texts = _texts(ctx, (g.title_ref for g in goals))
    wanted = _fold(text.strip())
    number = wanted.lstrip("#")
    out: list[Found] = []
    skip = max(0, ctx.int_param("_offset", 0))
    for g in goals:
        title = _text(texts, g.title_ref, "(sans titre)")
        if number.isdigit():
            if str(g.id) != number:
                continue
        elif wanted and wanted not in _fold(title):
            continue
        if skip:
            skip -= 1
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


def _stuck_recently(s: GoalsState, frame: Frame) -> tuple[int, str]:
    """Ce qu'on lui avait confié et qui a bloqué (ou échoué) depuis un jour."""
    n = sum(1 for g in s.goals.values() if g.authority == c.USER and g.status in (c.STUCK, c.FAILED)
            and frame.now - g.closed_at < DAY)
    return n, "confiés : bloqués ou en échec"


#: une décision de l'arbitre se cherche par lots de tant de sélections, au plus tant de lots par page
SELECTED_SCAN = 200
SELECTED_SCAN_BATCHES = 10
SENSITIVITY_FR = {0: "rien d'autrui", 1: "anodin", 2: "personnel", 3: "confidence"}


LIVE_COLUMNS = (Column("but", "fit", detail=True), Column("titre"), Column("sorte"), Column("autorité", detail=True), Column("statut"),
                Column("envie", hint="une exploration : son envie s'use", detail=True),
                Column("séances", "num", detail=True), Column("prochaine séance", detail=True), Column("échéance"), Column("pour qui"))


@GOALS.inspect("vivants", title="Buts vivants", section="buts", order=10, params=[KIND_PARAM, AUTHORITY_PARAM],
               description="Ce qu'elle se propose de faire ensuite : ses explorations et ses rappels, actifs, en "
                           "attente ou en pause. Ses projets ont leur menu à eux (Projets).")
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
            ("séances dans l'heure", f"{recent} / {p.steps_per_hour}"),
            ("entreprendre d'elle-même", When(ready) if ready > now else "possible"),
            ("dernier blocage sur ce qu'elle avait entrepris", When(s.self_stuck_at) if s.self_stuck_at else "—"),
        ), title="Ce qu'elle a entrepris", columns=2),
        Table(LIVE_COLUMNS, tuple(rows), title="Buts vivants", pager=pager, filters=("sorte", "autorite"),
              empty="aucun but avec ces filtres" if filtered else "aucun but en cours"),
    ]


CLOSED_COLUMNS = (Column("but", "fit", detail=True), Column("titre"), Column("sorte", detail=True), Column("autorité", detail=True), Column("issue"),
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
        ("séances", _steps(g)),
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
            ("prochaine séance", ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—"),
            ("dernière séance", When(g.last_step_at) if g.last_step_at else "—"),
            ("sans verdict d'affilée", g.silent),
            ("« fini » sans preuve", g.unproven),
            ("pannes d'affilée", g.failures),
            ("preuves (outils qui ont produit)", g.evidence),
            ("où elle en est", Text(_text(texts, g.summary_ref), clamp=600)),
        ]
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


@GOALS.inspect("resume", title="Résumé", subject="goal", order=10,
               description="Ce qu'elle s'est proposé, où elle en est et son plan de travail. Les actions (avancer, "
                           "pause, consigne, rouvrir, clore…) sont en haut de la fiche.")
def _summary_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    p = params(frame.env.params_of("goals", frame.root))
    refs = [g.title_ref, g.details_ref, g.summary_ref, g.result_ref, *(t.text_ref for t in g.tasks),
            *(t.note_ref for t in g.tasks)]
    texts = _texts(ctx, refs)
    blocks: list[Block] = [*_state_notes(g, s, frame, ctx, texts)]
    if g.kind == c.REMINDER:
        blocks.append(_reminder_card(g, frame, ctx, texts))
    elif g.kind == c.PROJECT:
        blocks.append(Note("Un ancien projet, d'avant les projets à part (ADR 0031) : il ne fait plus de séance. "
                           "Les projets se mènent désormais dans le menu Projets.", tone="muted"))
    elif g.details_ref:
        blocks.append(Prose(_text(texts, g.details_ref), title="Ce qu'elle cherche"))
    if g.kind != c.REMINDER:
        blocks.append(_cards(g, s, frame, ctx, p))
        if g.summary_ref:
            blocks.append(Prose(_text(texts, g.summary_ref), title="Où elle en est (sa dernière séance)", clamp=900))
        blocks += _plan_blocks(g, s, frame, texts)
    if g.status == c.WAITING:
        blocks.append(_wait_table(g, frame))
    blocks.append(Disclosure("Tout le détail", (_fields(g, s, frame, ctx, texts),)))
    return blocks


PRIORITY_FR = dict(PRIORITY_CHOICES)
PRIORITY_TONE = {c.LOW: "muted", c.NORMAL: "", c.HIGH: "warn", c.URGENT: "danger"}
TASK_TONE = {c.TODO: "", c.DOING: "info", c.TASK_DONE: "ok", c.TASK_BLOCKED: "danger"}
#: l'ordre du plan : ce qui est en cours, à faire, bloqué, puis fait
TASK_ORDER = {c.DOING: 0, c.TODO: 1, c.TASK_BLOCKED: 2, c.TASK_DONE: 3}


def _priority(g: Goal) -> Badge:
    return Badge(f"priorité {PRIORITY_FR.get(g.priority, g.priority)}", PRIORITY_TONE.get(g.priority, ""))


def _plan_progress(g: Goal, p: Any) -> Meter:
    """L'avancement : son plan de travail s'il en a un, sinon ses séances sur son budget."""
    if g.tasks:
        done = sum(1 for t in g.tasks if t.status == c.TASK_DONE)
        blocked = sum(1 for t in g.tasks if t.status == c.TASK_BLOCKED)
        label = f"{done} / {len(g.tasks)} tâches" + (f", {blocked} bloquée(s)" if blocked else "")
        return Meter(done / len(g.tasks), label, "warn" if blocked else "")
    most = budget(g, p)
    return Meter(g.steps / most if most else 0.0, f"{g.steps} / {most} séances")


def _next_words(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext) -> str:
    """La prochaine séance en mots : quand, ou pourquoi pas."""
    why = why_not_now(g, s, frame)
    if not why:
        return "dès que possible"
    nxt = next_step_at(g, s, frame) if status(g, frame.now) in (c.ACTIVE, c.WAITING) else None
    if nxt is not None and nxt > frame.now and why.startswith("pas encore"):
        return f"{ctx.when(nxt)} ({why.split(' : ', 1)[-1]})"
    return why


def _state_notes(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext, texts: Mapping[str, str]) -> list[Block]:
    key = str(g.id)
    if g.paused_at and g.status not in c.CLOSED_STATUSES:
        return [Note("En pause : ni séance, ni rappel, ni usure de l'envie, jusqu'à ce que tu le reprennes "
                     "(« Reprendre », en haut).", tone="warn")]
    if g.status in c.CLOSED_STATUSES:
        how = _text(texts, g.result_ref, "") if g.result_ref else ""
        why = how or "sans résultat écrit"
        more = " « Rouvrir » (en haut) le remet en route, avec quelques séances de plus." if _reopenable(s, frame, key) \
            else ""
        return [Note(f"{STATUS_FR.get(g.status, g.status).capitalize()} le {ctx.when(g.closed_at)} — {why}.{more}",
                     tone=STATUS_TONE.get(g.status, ""))]
    return []


def _reminder_card(g: Goal, frame: Frame, ctx: InspectContext, texts: Mapping[str, str]) -> Fields:
    return Fields((
        ("à rappeler", _text(texts, g.title_ref, "(sans titre)")),
        ("quand", (ctx.when(g.due) if g.due is not None else "—") + (" (urgent : même la nuit)" if g.urgent else "")),
        ("à qui", _who(frame, g.address)),
        ("dit", "oui" if g.delivered else "pas encore"),
        ("tentatives", g.attempts),
        ("prochain essai", When(g.retry_at) if g.retry_at > frame.now else "—"),
    ), title="Le rappel", columns=2)


def _cards(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext, p: Any) -> Grid:
    most = budget(g, p)
    blocked = sum(1 for t in g.tasks if t.status == c.TASK_BLOCKED)
    progress: list[tuple[str, Any]] = [("statut", _status(g, frame.now)), ("priorité", _priority(g)),
                                       ("avancement", _plan_progress(g, p)), ("séances faites", f"{g.steps} sur {most}")]
    if blocked:
        progress.append(("tâches bloquées", Badge(str(blocked), "danger")))
    if g.kind == c.EXPLORATION:
        progress.append(("envie", _desire(g, frame.now, frame)))
    nxt: list[tuple[str, Any]] = [("prochaine séance", _next_words(g, s, frame, ctx)),
                                  ("ce qui la porte", "son envie (elle s'use)"),
                                  ("échéance", _due(g)),
                                  ("dernière séance", When(g.last_step_at) if g.last_step_at else "aucun encore")]
    guards: list[tuple[str, Any]] = [
        ("sans verdict d'affilée", _gauge(g.silent, p.silent_before_blocked, "bloqué")),
        ("pannes d'affilée", _gauge(g.failures, p.failures_before_failed, "en échec")),
        ("« fini » sans preuve", g.unproven),
        ("preuves (outils qui ont produit)", g.evidence),
    ]
    return Grid((Fields(tuple(progress), title="Avancement"), Fields(tuple(nxt), title="Prochaine séance"),
                 Fields(tuple(guards), title="Garde-fous")), columns=3)


def _gauge(n: int, limit: int, then: str) -> Any:
    text = f"{n} / {limit} (au-delà : {then})"
    return Badge(text, "danger" if n and n >= limit - 1 else "warn" if n else "") if n else text


def _plan_blocks(g: Goal, s: GoalsState, frame: Frame, texts: Mapping[str, str]) -> list[Block]:
    key = str(g.id)
    editable = _plannable(s, frame, key)
    rows = []
    for t in sorted(g.tasks, key=lambda t: (TASK_ORDER.get(t.status, 9), t.id)):
        text, note = _text(texts, t.text_ref), _text(texts, t.note_ref, "") if t.note_ref else ""
        detail: tuple[Any, ...] = ()
        if editable:
            detail = (
                Toolbar(tuple(ActionSlot("goals.tache_statut", (("task", str(t.id)), ("status", st)),
                                         title=TASK_STATUS_FR[st], presentation="button")
                              for st in c.TASK_STATUSES if st != t.status), title="Statut"),
                Disclosure("Modifier la tâche", (ActionSlot("goals.tache_modifier", (
                    ("task", str(t.id)), ("text", text), ("note", note)), title="Modifier la tâche", compact=True),)),
                ActionSlot("goals.tache_retirer", (("task", str(t.id)),), title="Retirer la tâche",
                           presentation="button"),
            )
        rows.append(Row((t.id, Text(text, clamp=300), Badge(TASK_STATUS_FR.get(t.status, t.status),
                                                            TASK_TONE.get(t.status, "")),
                         "toi" if t.author == "operator" else "elle", Text(note, clamp=200) if note else "—"),
                        detail=detail, tone="danger" if t.status == c.TASK_BLOCKED else ""))
    done = sum(1 for t in g.tasks if t.status == c.TASK_DONE)
    out: list[Block] = [Table(
        (Column("n°", "fit"), Column("tâche"), Column("statut", "fit"), Column("posée par", "fit"),
         Column("résultat ou blocage")), tuple(rows),
        title=f"Plan de travail ({done} / {len(g.tasks)} faites)" if g.tasks else "Plan de travail",
        empty="aucune tâche écrite : elle avance d'après le cadre. Ajoute des étapes, elle les cochera.",
        caption="Déplie une tâche pour changer son statut, la modifier ou la retirer. Elle lit ce plan à chaque séance "
                "(les tâches que tu poses passent d'abord) et le tient à jour.")]
    if editable:
        out.append(ActionSlot("goals.tache_ajouter", title="Ajouter une tâche", compact=True))
    return out


# ── La fiche : cadre et politique ─────────────────────────────────────────


@GOALS.inspect("politique", title="Cadre et réglages", subject="goal", order=15,
               description="Ce qu'on peut changer de ce but (l'heure d'un rappel, la priorité d'une exploration), puis "
                           "ce qui en découle : son rythme, quand elle s'arrête, pour qui.")
def _policy_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    return [*_edit_blocks(g, s, frame), *_policy_blocks(g, s, frame, ctx)]


def _edit_blocks(g: Goal, s: GoalsState, frame: Frame) -> list[Block]:
    """Le formulaire qui change ce but, pré-rempli de ce qu'il est (selon sa sorte)."""
    key = str(g.id)
    if _reschedulable(s, frame, key):
        return [ActionSlot("goals.reprogrammer", title="Reprogrammer le rappel")]
    if g.kind == c.EXPLORATION and _prioritizable(s, frame, key):
        return [Note("Une exploration qu'elle a entreprise d'elle-même se pilote (pause, consigne, priorité, "
                     "avancer, clore) mais ne se réécrit pas : ni son titre, ni son envie.", "muted"),
                ActionSlot("goals.priorite", title="Sa priorité", compact=True)]
    if g.status in c.CLOSED_STATUSES:
        return [Note("Un but clos ne se modifie plus" + (" : rouvre-le d'abord (en haut)." if _reopenable(
            s, frame, key) else "."), "muted")]
    return []


def _policy_blocks(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    now = frame.now
    p = params(frame.env.params_of("goals", frame.root))
    texts = _texts(ctx, (g.details_ref, *g.instructions))
    most = budget(g, p)
    spacing = p.step_spacing_us
    nxt = next_step_at(g, s, frame) if status(g, now) in (c.ACTIVE, c.WAITING) and g.kind != c.REMINDER else None
    blocks: list[Block] = [Prose(_text(texts, g.details_ref), title="Ce qu'elle cherche")] if g.details_ref else []
    if g.instructions:
        blocks.append(Table((Column("n°", "fit"), Column("consigne")), tuple(
            (i + 1, Text(_text(texts, ref), clamp=400)) for i, ref in enumerate(reversed(g.instructions))),
            title=f"Consignes reçues ({len(g.instructions)}, la plus récente d'abord — elle prime)"))
    blocks += [
        Fields((
            ("ses outils", ", ".join(g.bundles) or "—"),
            ("autorité", f"{AUTHORITY_FR.get(g.authority, g.authority)} — " +
             ("quelqu'un le lui a demandé : elle ne l'abandonne pas d'elle-même" if g.authority == c.USER else
              "elle l'a entrepris d'elle-même : son envie s'use, elle peut l'abandonner")),
        ), title="Ce qui la porte", columns=2),
    ]
    if g.kind == c.EXPLORATION:
        blocks += _rhythm_blocks(g, p, nxt, now, most, spacing)
    blocks += [
        Fields((
            ("pour qui", _person(frame, g.owner)), ("où lui en parler", _who(frame, g.address)),
            ("concerne", ", ".join(_who(frame, a) for a in g.about) or "—"),
            ("sensibilité", SENSITIVITY_FR.get(g.sensitivity, str(g.sensitivity))),
            ("d'où il vient", g.source or "—"),
        ), title="Pour qui, et ce qu'elle peut en dire", columns=2),
        Note("Les réglages communs à tous les buts (espacement, séances par heure, pannes avant échec…) se changent "
             "dans Configuration › Comportement › Buts ; ce but-ci se pilote ici et par les actions en haut de sa "
             "fiche (avancer, pause, consigne, rouvrir, clore).", "muted"),
    ]
    return blocks


def _rhythm_blocks(g: Goal, p: Any, nxt: int | None, now: int, most: int, spacing: int) -> list[Block]:
    return [
        Fields((
            ("prochaine séance", ("dès que possible" if nxt <= now else When(nxt)) if nxt is not None else "—"),
            ("échéance", _due(g)),
            ("séances", f"{g.steps} faites sur {most} au plus" + ("" if g.max_steps else " (valeur par défaut)")),
            ("espacement des séances", f"{spacing // MINUTE} min au moins"),
            ("séances par heure (tous buts)", f"{p.steps_per_hour} au plus"),
            ("attente", f"de {p.wait_min_us // MINUTE} min à {p.wait_max_us // HOUR} h quand elle attend"),
        ), title="Son rythme", columns=2),
        Fields((
            ("sans verdict d'affilée", f"{g.silent} (bloqué à {p.silent_before_blocked})"),
            ("pannes d'affilée", f"{g.failures} (en échec à {p.failures_before_failed})"),
            ("« fini » sans preuve", g.unproven),
            ("séances au plus", most),
        ), title="Quand elle s'arrête", columns=2),
    ]


# ── La fiche : pas ────────────────────────────────────────────────────────


STEP_COLUMNS = (Column("quand", "fit"), Column("verdict"), Column("preuve"), Column("résumé"),
                Column("outils utilisés"), Column("notable", "num"), Column("", "fit"))


@GOALS.inspect("seances", title="Séances", subject="goal", order=20,
               description="Chaque séance de travail : son verdict, sa preuve et son compte rendu.")
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
        Fields((("séances faites", _steps(g)), ("sans verdict d'affilée", g.silent), ("« fini » sans preuve", g.unproven),
                ("preuves", g.evidence)), title="Où il en est", columns=2),
        Table(STEP_COLUMNS, tuple(rows), title="Ses séances", empty="aucune séance rapportée", pager=pager),
    ]
    return blocks


# ── La fiche : carnet ─────────────────────────────────────────────────────


@GOALS.inspect("carnet", title="Carnet", subject="goal", order=30,
               description="Les consignes reçues, les notes qu'elle garde pour la suite, et ce qu'on a fait du but "
                           "(pause, cadre changé, rouvert, tâches, fichiers déposés).")
def _notebook_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    orders, orders_pager = _journal_page(ctx, [GOAL_AMENDED], ("goal", g.id))
    notes, notes_pager = _journal_page(ctx, [NOTED], ("goal", g.id), NOTES_CURSOR)
    done, done_pager = _journal_page(ctx, list(OPERATIONS), ("goal", g.id), OPERATIONS_CURSOR)
    return [
        Timeline(tuple(Entry(e.at, "consigne", _said(e.data.instruction),
                             meta=f"de {_who(frame, e.data.by)}" if e.data.by else "", tone="info",
                             href=Ref("event", str(e.seq), "consigne"))
                       for e in orders), title="Consignes reçues", empty="aucune consigne", pager=orders_pager),
        Timeline(tuple(Entry(e.at, "note", _said(e.data.text), href=Ref("episode", e.correlation, "note"))
                       for e in notes), title="Son carnet", empty="aucune note", pager=notes_pager),
        Timeline(tuple(_operation(e, frame) for e in done), title="Ce qu'on en a fait (et son plan)",
                 empty="rien encore : ni pause, ni cadre changé, ni tâche", pager=done_pager),
    ]


OPERATIONS_CURSOR = "avant_ops"
REFRAMED_FR = (("title", "titre"), ("details", "cadre"), ("clear_details", "cadre effacé"), ("set_owner", "pour qui"),
               ("due", "échéance"), ("clear_due", "échéance retirée"), ("urgent", "urgent"), ("schedule", "agenda"),
               ("max_steps", "séances au plus"), ("approval", "accord requis"), ("priority", "priorité"))


def _reframed_words(d: Any) -> str:
    out = []
    for name, label in REFRAMED_FR:
        value = getattr(d, name, None)
        if value is None or value is False or value == "":
            continue
        if name == "schedule":
            out.append(f"agenda : {value or 'manual'}")
        elif name == "max_steps":
            out.append(f"séances au plus : {value or 'valeur par défaut'}")
        elif name == "priority":
            out.append(f"priorité : {PRIORITY_FR.get(value, value)}")
        elif name == "approval":
            out.append("ce qui sort attend ton accord" if value else "ce qui sort part librement")
        elif name == "urgent":
            out.append("urgent" if value else "plus urgent")
        elif name in ("title", "details"):
            out.append(f"{label} : « {_said(value)[:160]} »")
        else:
            out.append(label)
    if d.approval is False:
        out.append("ce qui sort part librement")
    if d.urgent is False:
        out.append("plus urgent")
    return ", ".join(dict.fromkeys(out)) or "rien"


def _operation(e: Event[Any], frame: Frame) -> Entry:
    d = e.data
    name = e.type.name.rsplit(".", 1)[-1]
    by = f"par {_who(frame, d.by)}" if getattr(d, "by", "") else "par elle"
    if name == "paused":
        return Entry(e.at, "mis en pause", meta=by, tone="warn")
    if name == "resumed":
        return Entry(e.at, "repris", meta=by, tone="ok")
    if name == "reframed":
        return Entry(e.at, "cadre modifié", _reframed_words(d), meta=by, tone="info")
    if name == "reopened":
        return Entry(e.at, f"rouvert (au moins {d.extra} séances de plus)", meta=by, tone="info")
    if name == "nudged":
        return Entry(e.at, "« avancer maintenant »", meta=by)
    if name == "task_added":
        return Entry(e.at, f"tâche {d.task} ajoutée", _said(d.text), meta=by)
    if name == "task_changed":
        what = TASK_STATUS_FR.get(d.status, "modifiée") if d.status else "modifiée"
        text = _said(d.note, "") if d.note is not None else (_said(d.text, "") if d.text is not None else "")
        return Entry(e.at, f"tâche {d.task} : {what}", text, meta=by,
                     tone="ok" if d.status == c.TASK_DONE else "danger" if d.status == c.TASK_BLOCKED else "")
    if name == "task_removed":
        return Entry(e.at, f"tâche {d.task} retirée", meta=by, tone="muted")
    if name == "deposited":
        return Entry(e.at, f"fichier déposé : {d.name}", _said(d.note, "") if d.note is not None else "", meta=by)
    return Entry(e.at, name, meta=by)


# ── La fiche : épisodes ───────────────────────────────────────────────────


def _episode_kind(d: rt.EpisodeStarted) -> str:
    kind = str(d.kind)
    if kind == Kind.STEP:
        return "séance de travail"
    reasons = str(d.reason).split(",")
    if c.REMIND in reasons:
        return "dire le rappel"
    if c.SHARE in reasons:
        return "raconter"
    return kind.lower()


def _started(g: Goal, ctx: InspectContext) -> tuple[list[Event[Any]], Pager]:
    """Une page des épisodes de ce but : ceux qu'il vise (ses séances), et ceux qui
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
               description="Chaque fois qu'elle y a travaillé (ou en a parlé) : le résultat de la séance, et de quoi relire "
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
    return [Table((Column("quand", "fit"), "épisode", Column("vers", detail=True), Column("issue", "fit"), Column("verdict", "fit"),
                   "résultat", Column("Prompt", detail=True), Column("Outils", detail=True), Column("Appels", detail=True), Column("Décision", detail=True)),
                  tuple(rows), title="Ses épisodes", empty="aucun épisode encore", pager=pager,
                  caption="« prompt » : ce qu'elle a vraiment reçu (persona, cadre, carnet, fil) et ce qu'elle a "
                          "répondu ; « outils » : chaque appel et son résultat ; « décision » : pourquoi cette séance-là.")]


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
                  caption="Une ligne par tirage où ce but était parmi les premiers en lice : « choisi » a donné une "
                          "séance de travail (ou un rappel, un récit). La table complète du moment : Décisions › Ses choix.")]


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
