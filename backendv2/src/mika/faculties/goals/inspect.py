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
from mika.kernel.clock import DAY, HOUR
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
    Ref,
    Row,
    Table,
    Text,
    Timeline,
    When,
    paginate,
)
from mika.vocab.episodes import Kind, goal_of, goal_target

GOALS_PAGE = 50
STEPS_SHOWN = 100
NOTES_SHOWN = 100
EPISODES_SHOWN = 100
EFFECTS_SHOWN = 50
#: les décisions et exécutions relues pour dire ce que sont devenus ses effets
OUTCOMES_SCANNED = 500
TREE_SHOWN = 200
DIFF_SHOWN = 20_000
LOG_SHOWN = 30
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


LIVE_COLUMNS = (Column("but", "fit"), Column("titre"), Column("sorte"), Column("autorité"), Column("statut"),
                Column("envie", hint="une exploration : son envie s'use ; un projet : un engagement"),
                Column("pas", "num"), Column("prochain pas"), Column("échéance"), Column("pour qui"))


@GOALS.inspect("vivants", title="Vivants", section="buts", order=10, params=[KIND_PARAM, AUTHORITY_PARAM],
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


@GOALS.inspect("clos", title="Clos", section="buts", order=20, params=[KIND_PARAM, AUTHORITY_PARAM],
               badge=_stuck_recently, description="Ce qu'elle a mené à bout, bloqué, abandonné, ou qu'on a annulé.")
def _closed_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    kind, authority = ctx.value("sorte") or "", ctx.value("autorite") or ""
    before = ctx.int_param("avant", 0) or None
    found = ctx.events([c.GOAL_CLOSED], GOALS_PAGE, where=("kind", kind) if kind else None, before=before)
    rows = []
    for e in found:
        d = e.data
        if authority and d.authority != authority:
            continue
        kept = s.goals.get(d.goal)
        link = _link(kept) if kept is not None else Ref("event", str(e.seq), f"#{d.goal}")
        result = _said(d.result, "") or d.reason or "—"
        rows.append(Row((
            link, _said(d.title, "(sans titre)"), KIND_FR.get(d.kind, d.kind), AUTHORITY_FR.get(d.authority, d.authority),
            Badge(STATUS_FR.get(d.status, d.status), STATUS_TONE.get(d.status, "")), When(e.at),
            Text(result, clamp=SUMMARY_CLAMP), _person(frame, d.owner)), href=link))
    older = (("avant", str(found[-1].seq)),) if len(found) >= GOALS_PAGE else ()
    empty = "aucun but clos avec ces filtres" if (kind or authority) else "aucun but clos"
    return [
        Table(CLOSED_COLUMNS, tuple(rows), title="Buts clos", pager=Pager(param="avant", older=older),
              filters=("sorte", "autorite"), empty=empty),
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


# ── La fiche : pas ────────────────────────────────────────────────────────


STEP_COLUMNS = (Column("quand", "fit"), Column("verdict"), Column("preuve"), Column("résumé"),
                Column("outils utilisés"), Column("notable", "num"), Column("", "fit"))


@GOALS.inspect("pas", title="Pas", subject="goal", order=20)
def _steps_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    rows = []
    found = ctx.events([c.STEP_REPORTED], STEPS_SHOWN, where=("goal", g.id))
    for e in found:
        d = e.data
        verdict, proof = _step_badges(str(d.verdict), bool(d.proven), frame, int(d.wait_s), d.wait_for)
        rows.append(Row((When(e.at), verdict, proof, Text(_said(d.summary), clamp=SUMMARY_CLAMP),
                         ", ".join(d.tools) or "—", f"{float(d.notable):.1f}",
                         Ref("episode", e.correlation, "épisode"))))
    blocks: list[Block] = [
        Fields((("pas faits", _steps(g)), ("sans verdict d'affilée", g.silent), ("« fini » sans preuve", g.unproven),
                ("preuves", g.evidence)), title="Où il en est", columns=2),
        Table(STEP_COLUMNS, tuple(rows), title="Ses pas", empty="aucun pas rapporté"),
    ]
    if len(found) >= STEPS_SHOWN:
        blocks.append(Note(f"Seuls les {STEPS_SHOWN} derniers pas sont montrés.", tone="muted"))
    return blocks


# ── La fiche : carnet ─────────────────────────────────────────────────────


@GOALS.inspect("carnet", title="Carnet", subject="goal", order=30)
def _notebook_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    notes = ctx.events([NOTED], NOTES_SHOWN, where=("goal", g.id))
    orders = ctx.events([GOAL_AMENDED], NOTES_SHOWN, where=("goal", g.id))
    return [
        Timeline(tuple(Entry(e.at, "consigne", _said(e.data.instruction),
                             meta=f"de {_who(frame, e.data.by)}" if e.data.by else "", tone="info",
                             href=Ref("event", str(e.seq), "consigne"))
                       for e in orders), title="Consignes reçues", empty="aucune consigne"),
        Timeline(tuple(Entry(e.at, "note", _said(e.data.text), href=Ref("episode", e.correlation, "note"))
                       for e in notes), title="Son carnet", empty="aucune note"),
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
    return Badge("inconnu", "muted"), "sa décision est trop ancienne pour être relue ici"


EFFECT_COLUMNS = (Column("proposition", "fit"), Column("quand", "fit"), Column("capacité"), Column("résumé"),
                  Column("accord"), Column("état"))


@GOALS.inspect("effets", title="Effets", subject="goal", order=40)
def _effects_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    pending = {v.proposal for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and goal_of(v.context) == g.id}
    proposed = ctx.events([rt.EFFECT_PROPOSED], EFFECTS_SHOWN, where=("context", goal_target(g.id)))
    wanted = {e.seq for e in proposed}
    outcomes: dict[int, list[Event[Any]]] = {}
    if wanted:
        for e in ctx.events([rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED], OUTCOMES_SCANNED):
            if e.data.proposal in wanted:
                outcomes.setdefault(e.data.proposal, []).append(e)
    rows = []
    for e in proposed:
        state, detail = _effect_state(e, e.seq in pending, outcomes.get(e.seq, ()))
        rows.append(Row((Ref("event", str(e.seq), f"#{e.seq}"), When(e.at), e.data.capability,
                         Text(_said(e.data.summary), clamp=SUMMARY_CLAMP),
                         "requis" if e.data.approval else "non requis", state),
                        tone="warn" if e.seq in pending else "",
                        detail=(Code(detail[:4000], title="ce qu'il en est"),) if detail else ()))
    blocks: list[Block] = []
    if pending:
        blocks.append(Fields(((f"{len(pending)} demande(s) attendent ton accord", APPROVALS),),
                             title="À décider"))
    blocks.append(Table(EFFECT_COLUMNS, tuple(rows), title="Ce qu'il a voulu faire sortir de la machine",
                        empty="aucune demande : tout s'est fait dans l'atelier"))
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


def _started(g: Goal, ctx: InspectContext) -> list[Event[Any]]:
    """Les derniers épisodes de ce but : ceux qu'il vise (ses pas), et ceux
    qui portent sur lui en visant quelqu'un (le rappel, le récit)."""
    target = goal_target(g.id)
    found = {e.seq: e for field in ("target", "subject")
             for e in ctx.events([rt.EPISODE_STARTED], EPISODES_SHOWN, where=(field, target))}
    return [found[seq] for seq in sorted(found, reverse=True)[:EPISODES_SHOWN]]


def _outcomes(started: list[Event[Any]], ctx: InspectContext) -> dict[str, str]:
    """L'issue de ces épisodes, par corrélation."""
    corrs = [e.correlation for e in started]
    ended = ctx.events([rt.EPISODE_ENDED], len(corrs) + 1, correlations=corrs)
    return {e.correlation: str(e.data.outcome) for e in ended}


@GOALS.inspect("episodes", title="Épisodes", subject="goal", order=50)
def _episodes_tab(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    g = _subject_goal(s, ctx)
    if isinstance(g, Note):
        return [g]
    target = goal_target(g.id)
    started = _started(g, ctx)
    outcomes = _outcomes(started, ctx)
    rows = []
    for e in started:
        outcome = outcomes.get(e.correlation)
        towards = e.data.target if e.data.target != target else None
        issue = (Badge(OUTCOME_FR.get(outcome, outcome), OUTCOME_TONE.get(outcome, "")) if outcome
                 else Badge("en cours", "info"))
        rows.append(Row((When(e.at), _episode_kind(e.data), _who(frame, towards) if towards else "—", issue,
                         Ref("episode", e.correlation, "voir l'épisode")), href=Ref("episode", e.correlation, "")))
    return [Table(("quand", "épisode", "vers", "issue", ""), tuple(rows), title="Ses épisodes",
                  empty="aucun épisode encore")]


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
    log = await port.log(g.id, LOG_SHOWN)
    files = []
    for line in tree[:TREE_SHOWN]:
        m = _TREE_LINE.match(line)
        files.append((Text(m.group("path"), "mono"), f"{int(m.group('size'))} o") if m else (Text(line, "muted"), ""))
    steps = ctx.events([c.STEP_REPORTED], STEPS_SHOWN, where=("goal", g.id))
    by_title = {}
    for e in reversed(steps):  # le plus récent l'emporte
        if e.data.summary.text is not None:
            by_title[_commit_title(e.data.summary.text)] = e
    entries = []
    for line in log.splitlines():
        sha, _, title = line.strip().partition(" ")
        if not sha:
            continue
        step = by_title.get(title)
        entries.append(Entry(step.at if step is not None else 0, title or "(sans message)", meta=sha,
                             href=Ref("episode", step.correlation, title) if step is not None else None))
    shown = diff if len(diff) <= DIFF_SHOWN else diff[:DIFF_SHOWN] + f"\n[… coupé à {DIFF_SHOWN} caractères …]"
    return [
        Table((Column("fichier"), Column("taille", "num")), tuple(files), title="Ses fichiers",
              empty="le dossier est vide"),
        Code(shown, title="Changements depuis le dernier pas") if diff.strip()
        else Note("Rien de changé depuis le dernier pas : tout est enregistré.", tone="muted"),
        Timeline(tuple(entries), title="Historique (un enregistrement par pas qui a changé quelque chose)",
                 empty="aucun enregistrement encore"),
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
