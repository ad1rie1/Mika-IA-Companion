"""Ce que les buts montrent à un opérateur : la liste, et chaque but en détail.

Lecture seule. Les compteurs et l'envie viennent de la tranche (calculés comme
la faculté les calcule) ; l'historique des pas et les épisodes, du journal —
la tranche n'en garde que le dernier résumé. Un contenu oublié s'affiche
comme tel.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.goals.faculty import GOALS, Goal, GoalsState, desire, params, ready_to_undertake, status
from mika.faculties.goals.work import next_step_at
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, Event
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Ref, Table
from mika.vocab.episodes import Kind, goal_of, goal_target

GOALS_SHOWN = 200
STEPS_SHOWN = 100
EPISODES_SHOWN = 100
EFFECTS_SHOWN = 100
FORGOTTEN = "(oublié)"

KIND_FR = {c.REMINDER: "rappel", c.EXPLORATION: "exploration", c.PROJECT: "projet"}
AUTHORITY_FR = {c.USER: "confié", c.SELF: "à elle"}
STATUS_FR = {c.ACTIVE: "en cours", c.WAITING: "en attente", c.ACHIEVED: "abouti", c.STUCK: "bloqué",
             c.ABANDONED: "abandonné", c.FAILED: "en échec", c.CANCELLED: "annulé"}
VERDICT_FR = {c.CONTINUE: "continuer", c.DONE: "fini", c.BLOCKED: "bloquée", c.WAIT: "attendre"}
OUTCOME_FR = {"done": "fait", "abstained": "abstenue", "superseded": "supplanté", "timeout": "délai dépassé",
              "failed": "échec", "preempted": "préempté", "interrupted": "interrompu", "cancelled": "annulé"}
LIVE_FILTER, CLOSED_FILTER = "vivants", "clos"


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


def _who(frame: Frame, key: str | None) -> str:
    if not key:
        return "—"
    name = frame.get(identity_c.IDENTITY(key)).name
    return f"« {name} » ({key})" if name else key


def _desire(g: Goal, now: int, frame: Frame) -> str:
    if g.kind == c.PROJECT:
        return "engagement (ne s'use pas)"
    if g.kind != c.EXPLORATION or g.status in c.CLOSED_STATUSES:
        return "—"
    p = params(frame.env.params_of("goals", frame.root))
    return f"{desire(g, now, p):.0%}"


def _steps(g: Goal) -> str:
    return f"{g.steps} / {g.max_steps}" if g.max_steps else "—"


def _due(g: Goal, ctx: InspectContext) -> str:
    if g.due is None:
        return "—"
    return ctx.when(g.due) + (" (urgent)" if g.urgent else "")


def _link(g: Goal) -> Ref:
    return Ref("view", "goals/but", f"#{g.id}", (("goal", str(g.id)),))


def _selected(status_now: str, wanted: str) -> bool:
    if not wanted:
        return True
    if wanted == LIVE_FILTER:
        return status_now in (c.ACTIVE, c.WAITING)
    if wanted == CLOSED_FILTER:
        return status_now in c.CLOSED_STATUSES
    return status_now == wanted


def _status_filter(raw: str) -> str | None:
    """La valeur canonique du filtre (code ou libellé), ``None`` si inconnue."""
    value = raw.strip().lower()
    if value in ("", LIVE_FILTER, CLOSED_FILTER) or value in STATUS_FR:
        return value
    return next((code for code, label in STATUS_FR.items() if label == value), None)


@GOALS.inspect("buts", title="Buts", params=[("status", "statut")])
def _goals_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    now = frame.now
    p = params(frame.env.params_of("goals", frame.root))
    blocks: list[Block] = []
    wanted = _status_filter(ctx.param("status"))
    if wanted is None:
        choices = ", ".join([LIVE_FILTER, CLOSED_FILTER, *STATUS_FR.values()])
        blocks.append(Note(f"Statut inconnu : « {ctx.param('status')} ». Valeurs possibles : {choices}. "
                           "Tous les buts sont affichés.", tone="ko"))
        wanted = ""
    goals = sorted(s.goals.values(), key=lambda g: (status(g, now) in c.CLOSED_STATUSES, -g.id))
    chosen = [g for g in goals if _selected(status(g, now), wanted)]
    texts = _texts(ctx, (g.title_ref for g in chosen[:GOALS_SHOWN]))
    rows = tuple(
        (_link(g), _text(texts, g.title_ref, "(sans titre)"), AUTHORITY_FR.get(g.authority, g.authority),
         KIND_FR.get(g.kind, g.kind), STATUS_FR.get(status(g, now), status(g, now)), _desire(g, now, frame),
         _steps(g), _due(g, ctx), ", ".join(g.bundles) or "—", ctx.when(g.opened_at))
        for g in chosen[:GOALS_SHOWN])
    live = sum(1 for g in goals if status(g, now) in (c.ACTIVE, c.WAITING))
    recent = sum(1 for t in s.steps_at if now - t < HOUR)
    ready = ready_to_undertake(s, p)
    blocks += [
        Fields((
            ("vivants", live),
            ("clos gardés en mémoire", len(goals) - live),
            ("pas dans l'heure", f"{recent} / {p.steps_per_hour}"),
            ("délai avant d'entreprendre d'elle-même", f"jusqu'à {ctx.when(ready)}" if ready > now else "écoulé"),
            ("dernier blocage sur ce qu'elle avait entrepris", ctx.when(s.self_stuck_at) if s.self_stuck_at else "—"),
        ), title="Ce qu'elle a entrepris"),
        Table(("but", "titre", "autorité", "sorte", "statut", "envie", "pas", "échéance", "outils", "ouvert le"),
              rows, title="Buts", empty="aucun but" if not wanted else "aucun but avec ce statut"),
    ]
    if len(chosen) > GOALS_SHOWN:
        blocks.append(Note(f"{len(chosen) - GOALS_SHOWN} buts de plus ne sont pas affichés.", tone="mut"))
    return blocks


# ── Un but ────────────────────────────────────────────────────────────────


def _said(content: Content) -> str:
    """Le texte d'un contenu relu au journal (``text`` à ``None`` : il a été oublié)."""
    return content.text if content.text is not None else FORGOTTEN


def _steps_table(g: Goal, frame: Frame, ctx: InspectContext) -> Table:
    rows = []
    for e in ctx.events([c.STEP_REPORTED], STEPS_SHOWN, where=("goal", g.id)):
        d = e.data
        verdict = str(d.verdict)
        shown = VERDICT_FR.get(verdict, verdict)
        if verdict == c.DONE:
            shown += " (prouvé)" if d.proven else " (sans preuve)"
        if verdict == c.WAIT:
            whom = d.wait_for
            shown += f" {int(d.wait_s) // 60} min" + (f", la réponse de {_who(frame, whom)}" if whom else "")
        rows.append((ctx.when(e.at), shown, _said(d.summary), ", ".join(d.tools) or "—", f"{float(d.notable):.1f}",
                     Ref("episode", e.correlation, "épisode")))
    return Table(("quand", "verdict", "résumé", "outils utilisés", "notable", ""), tuple(rows),
                 title="Ses pas", empty="aucun pas rapporté")


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


def _episodes_table(g: Goal, frame: Frame, ctx: InspectContext) -> Table:
    target = goal_target(g.id)
    started = _started(g, ctx)
    outcomes = _outcomes(started, ctx)
    rows = []
    for e in started:
        outcome = outcomes.get(e.correlation)
        towards = e.data.target if e.data.target != target else None
        rows.append((ctx.when(e.at), _episode_kind(e.data), _who(frame, towards) if towards else "—",
                     OUTCOME_FR.get(outcome, outcome) if outcome else "en cours",
                     Ref("episode", e.correlation, "voir l'épisode")))
    return Table(("quand", "épisode", "vers", "issue", ""), tuple(rows), title="Ses épisodes",
                 empty="aucun épisode encore")


def _effects_table(g: Goal, frame: Frame, ctx: InspectContext) -> Table:
    pending = [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and goal_of(v.context) == g.id]
    pending = pending[-EFFECTS_SHOWN:]
    texts = _texts(ctx, (v.summary_ref for v in pending))
    rows: list[tuple[Any, ...]] = [
        (f"#{v.proposal}", v.capability, _text(texts, v.summary_ref), f"attend un accord depuis {ctx.when(v.at)}")
        for v in pending]
    rows += [("—", "—", line, "historique") for line in reversed(g.effects)]
    return Table(("proposition", "capacité", "résumé", "état"), tuple(rows), title="Ce qui sort de la machine",
                 empty="aucune demande")


def _fields(g: Goal, s: GoalsState, frame: Frame, ctx: InspectContext, texts: Mapping[str, str]) -> Fields:
    now = frame.now
    current = status(g, now)
    pairs: list[tuple[str, Any]] = [
        ("titre", _text(texts, g.title_ref, "(sans titre)")),
        ("sorte", KIND_FR.get(g.kind, g.kind)),
        ("autorité", AUTHORITY_FR.get(g.authority, g.authority)),
        ("statut", STATUS_FR.get(current, current)),
    ]
    if current != g.status:
        pairs.append(("statut enregistré", f"{STATUS_FR.get(g.status, g.status)} (l'attente est échue)"))
    if g.details_ref:
        pairs.append(("cadre (confié, elle ne le change pas)", _text(texts, g.details_ref)))
    pairs += [
        ("personne concernée", _who(frame, g.owner)),
        ("où lui parler", _who(frame, g.address)),
        ("concerne", ", ".join(_who(frame, a) for a in g.about) or "—"),
        ("sensibilité", g.sensitivity),
        ("d'où il vient", g.source or "—"),
        ("ouvert le", Ref("event", str(g.id), ctx.when(g.opened_at))),
        ("envie", _desire(g, now, frame) + (f" (au départ {g.desire:.0%})" if g.kind == c.EXPLORATION else "")),
        ("pas", _steps(g)),
        ("outils", ", ".join(g.bundles) or "—"),
    ]
    if g.kind == c.REMINDER:
        pairs += [
            ("échéance", _due(g, ctx)),
            ("dit", "oui" if g.delivered else "pas encore"),
            ("tentatives", g.attempts),
            ("prochain essai", ctx.when(g.retry_at) if g.retry_at > now else "—"),
        ]
    else:
        nxt = next_step_at(g, s, frame) if current in (c.ACTIVE, c.WAITING) else None
        pairs += [
            ("prochain pas", ("dès que possible" if nxt <= now else ctx.when(nxt)) if nxt is not None else "—"),
            ("dernier pas", ctx.when(g.last_step_at) if g.last_step_at else "—"),
            ("sans verdict d'affilée", g.silent),
            ("« fini » sans preuve", g.unproven),
            ("pannes d'affilée", g.failures),
            ("preuves (outils qui ont produit)", g.evidence),
            ("où elle en est", _text(texts, g.summary_ref)),
        ]
        if g.kind == c.PROJECT:
            pairs += [("agenda", g.schedule or "manuel"), ("accord requis pour sortir", "oui" if g.approval else "non")]
    if g.status in c.CLOSED_STATUSES:
        pairs += [
            ("clos le", ctx.when(g.closed_at)),
            ("résultat", _text(texts, g.result_ref)),
            ("notable", f"{g.notable:.1f}"),
            ("raconté", "oui" if g.shared else f"non ({g.share_attempts} essai(s))"),
        ]
    pairs.append(("tous les buts", Ref("view", "goals/buts", "retour à la liste")))
    return Fields(tuple(pairs), title=f"But n°{g.id}")


def _wait_table(g: Goal, frame: Frame, ctx: InspectContext) -> Table:
    rows = []
    if g.status == c.WAITING:
        whom = f"la réponse de {_who(frame, g.wait_for)}" if g.wait_for else "rien de nominatif (un délai)"
        state = "échue : il reprend" if g.waiting_until <= frame.now else "en cours"
        rows.append((whom, ctx.when(g.waiting_since) if g.waiting_since else "—", ctx.when(g.waiting_until), state))
    return Table(("elle attend", "depuis", "jusqu'à", "état"), tuple(rows), title="Attente",
                 empty="elle n'attend rien")


@GOALS.inspect("but", title="But", params=[("goal", "numéro du but")])
def _goal_view(s: GoalsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    raw = ctx.param("goal").lstrip("#")
    if not raw:
        return [Note("Indique un but : ?goal=<numéro> (voir la vue « Buts »).", tone="mut")]
    if not raw.isdigit():
        return [Note(f"« {raw} » n'est pas un numéro de but.", tone="ko")]
    g = s.goals.get(int(raw))
    if g is None:
        return [Note(f"Aucun but n°{raw} en mémoire : jamais ouvert, ou clos depuis plus de sept jours.", tone="ko")]
    texts = _texts(ctx, (g.title_ref, g.details_ref, g.summary_ref, g.result_ref, *g.notes))
    notes = tuple((_text(texts, r),) for r in reversed(g.notes))
    return [
        _fields(g, s, frame, ctx, texts),
        _wait_table(g, frame, ctx),
        _steps_table(g, frame, ctx),
        Table(("note",), notes, title="Son carnet", empty="aucune note"),
        _effects_table(g, frame, ctx),
        _episodes_table(g, frame, ctx),
    ]

