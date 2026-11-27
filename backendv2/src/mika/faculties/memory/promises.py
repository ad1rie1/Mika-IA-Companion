"""Ses promesses : les tenir au moment dit, et les laisser filer.

**Tenir parole.** Une promesse datée (« je te demanderai jeudi à 20 h comment
ça s'est passé ») se tient au moment dit : un peu avant l'heure dite (dans la
journée, pour un jour sans heure), l'envie monte et elle le fait d'elle-même.
C'est **dû** (``agency.OWED``) : ni budget, ni retenue, ni rancune. Dite, la
promesse est tenue (``memory.promises`` la règle) ; un silence choisi, une
panne sont des essais, bornés ; une promesse sans date ne déclenche rien. Si
elles se sont parlé depuis le début de la fenêtre, la conversation était
l'occasion : elle ne revient pas dessus d'elle-même (le prompt le lui montrait).
Un jour sans heure (« je te le rappelle mercredi ») est dû **toute cette
journée-là** en conversation, jusqu'au soir : quelqu'un qu'elle ne voit qu'à
19 h l'entend quand même (ADR 0052).

**Laisser filer.** Une promesse que rien n'a réglée bien après son échéance
s'abandonne (``memory.promises``) : rien ne reste dû pour toujours. Un rappel
programmé ensuite pour la même chose la porte désormais : un rappel demandé
existe une fois et une seule.

Ce module dit quand une promesse se tient (``keep_window``, ``due_now``, ``due_today``, ``kept_too_early``), la tient
d'elle-même (le proposant ``keep_promise``) et la règle (le processus ``memory.promises``, les rappels programmés
``reminders_of``). Le rappel (``recall.py``), son outil (``tools.py``) et ce que le code garde d'une relecture
(``kept.py``) les lisent d'ici ; ce qui dit que deux phrases parlent de la même chose à faire, ou du même jour
(``same_task``, ``same_day``), est à la vie des autres (``life.py``), qui les partage avec les moments.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import select

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.faculty import (
    MEMORY,
    PROMISE_SUBJECT,
    Keeping,
    MemoryParams,
    MemoryState,
    day_of,
    params,
)
from mika.faculties.memory.life import same_day, same_task
from mika.faculties.memory.tables import batches
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, instant
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase

#: le début de la fenêtre d'une promesse : la preuve monte depuis là
KEEP_EVIDENCE_START = 2.0


# ── Tenir parole au moment dit ────────────────────────────────────────────


def keep_window(pr: c.PendingPromise, frame: Frame, p: MemoryParams) -> tuple[int, int, int] | None:
    """(début, preuve pleine à partir de, fin) de la fenêtre où tenir une promesse datée ; ``None`` sans date.
    À une heure dite : un peu avant, jusqu'à un peu après ; un jour sans heure : dans la journée — l'envie monte
    dès le matin, pleine à mi-chemin de son échéance du soir, et la fenêtre reste ouverte jusqu'au soir (quelqu'un
    qu'elle ne voit qu'à 21 h l'entend quand même)."""
    if pr.due is None or pr.implicit_due:
        return None
    if pr.all_day:
        tz = frame.env.tz_of(frame.root)
        day = frame.local(pr.due).date()
        start = instant(datetime.combine(day, time(p.promise_day_start_min // 60 % 24, p.promise_day_start_min % 60),
                                         tzinfo=tz))
        full = max(start + 1, (start + pr.due) // 2)
    else:
        start, full = pr.due - p.promise_lead_us, pr.due
    return min(start, pr.due), max(full, start + 1), pr.due + p.keep_late_us


def due_now(pr: c.PendingPromise, frame: Frame, p: MemoryParams) -> bool:
    """En conversation, est-ce le moment de la tenir ? Dans sa fenêtre ; un jour sans heure, **toute cette
    journée-là** jusqu'au soir — dès le matin, quand on se parle (« au fait, c'est aujourd'hui, le dentiste ! »)."""
    window = keep_window(pr, frame, p)
    if window is None or pr.due is None:
        return False
    start, _full, end = window
    if pr.all_day:
        start = min(start, day_of(pr.due, frame.env.tz_of(frame.root)))
    return start <= frame.now <= end


def kept_too_early(pr: c.PendingPromise, at: int, frame: Frame) -> bool:
    """Une promesse datée ne se tient pas avant son jour : la veille au soir, « demain, je te le rappelle comme
    promis » n'est pas la tenir (sonde réelle du 2026-10-03 : réglée mardi, le rappel du mercredi n'est jamais
    venu). Sans date, elle se tient quand elle se tient."""
    if pr.due is None or pr.implicit_due:
        return False
    return frame.local(at).date() < frame.local(pr.due).date()


def due_today(pr: c.PendingPromise, frame: Frame) -> bool:
    """Une promesse datée dont le jour est venu (ou passé) ; pas une promesse vague, ni celle de demain."""
    return pr.due is not None and not pr.implicit_due and not kept_too_early(pr, frame.now, frame)


@MEMORY.propose(kinds=[Kind.INITIATIVE], reasons={c.KEEP_PROMISE: (0.0, 12.0)},
                reads=[identity_c.PERSON, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                       presence_c.PRESENT, transcript_c.LAST_FROM])
def _keep(s: MemoryState, frame: Frame) -> list[Candidate]:
    """Une promesse datée, au moment dit : elle la tient d'elle-même. Pas si elles se sont parlé depuis le début
    de la fenêtre (la conversation en était l'occasion), ni après trop d'essais."""
    resolve, _ = identity_c.resolvers(frame.get)
    p = params(frame.env.params_of("memory", frame.root))
    now = frame.now
    out: list[Candidate] = []
    for pr in sorted(s.promises.values(), key=lambda pr: (pr.due or 0, pr.id)):
        window = keep_window(pr, frame, p)
        if window is None or pr.id in s.kept or not pr.to:
            continue
        start, full, end = window
        tries = s.tries.get(pr.id) or Keeping()
        if not start <= now <= end or tries.retry_at > now or tries.attempts >= p.keep_attempts:
            continue
        to = resolve(pr.to)  # une adresse reliée depuis à quelqu'un parle pour lui
        if identity_c.last_heard(frame, to) >= max(start, pr.at):
            continue  # elles se sont parlé depuis : c'était l'occasion, le prompt le lui montrait
        address = identity_c.reach_now(frame, to)
        if address is None:
            continue
        ramp = min(1.0, max(0.0, (now - start) / (full - start)))
        evidence = KEEP_EVIDENCE_START + (p.keep_evidence - KEEP_EVIDENCE_START) * ramp
        name = frame.get(identity_c.IDENTITY(to)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else phrase("memory.keep.someone")
        when = phrase("memory.keep.today") if pr.all_day else phrase("memory.keep.now")
        brief = phrase("memory.keep.brief", who=who, when=when, id=pr.id)
        out.append(Candidate(Kind.INITIATIVE, address, c.KEEP_PROMISE, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(identity_c.heard_since_guard(frame, to),),
                             args=FrozenDict({"brief:memory": brief, "subject": f"{PROMISE_SUBJECT}{pr.id}"})))
    return out


# ── Laisser filer ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Reminder:
    """Un rappel programmé (un but ``goals`` vivant, de la sorte ``reminder``) : à qui, quoi, pour quand."""

    id: int
    owner: str
    title: str
    due: int | None
    opened_at: int


def reminders_of(frame: Frame, store: Any) -> list[Reminder]:
    """Les rappels programmés en cours (``goals.LIVE``), avec leur texte."""
    live = [g for g in frame.get(goals_c.LIVE) if g.kind == goals_c.REMINDER and g.owner and g.title_ref]
    if not live or store is None:
        return []
    texts = store.content([g.title_ref for g in live])
    return [Reminder(g.id, g.owner, texts.get(g.title_ref) or "", g.due, g.opened_at) for g in live
            if texts.get(g.title_ref)]


@MEMORY.process("memory.promises", wake_on=[c.PROMISE_NOTICED, c.PROMISE_RESOLVED, rt.UTTERANCE,
                                             goals_c.GOAL_OPENED],
                catch_up=CatchUp.ONCE, max_quantum_s=3600)
class LetGo:
    """Une promesse qu'elle vient de tenir en le disant (l'initiative qui la tenait a parlé) est réglée : tenue.
    Une promesse ni tenue ni abandonnée s'abandonne quelques jours après son
    échéance : elle y a repensé (l'attention le lui a rappelé), puis elle laisse filer. Un rappel programmé
    ensuite pour la même chose (« à 9 h, stp » : l'outil ``goal_remind``) la porte désormais : la promesse lui
    laisse la place (un rappel demandé existe une fois et une seule)."""

    def __init__(self) -> None:
        #: les rappels programmés déjà confrontés aux promesses
        self.seen: set[int] = set()

    def _due(self, state: MemoryState, p: MemoryParams) -> list[tuple[int, int]]:
        grace = round(p.promise_drop_days * DAY)
        return sorted((pr.due + grace, pr.id) for pr in state.promises.values() if pr.due is not None)

    def _fresh_reminders(self, state: MemoryState, frame: Frame) -> bool:
        resolve, _ = identity_c.resolvers(frame.get)
        owners = {resolve(pr.to) for pr in state.promises.values()}
        return any(g.kind == goals_c.REMINDER and g.owner in owners and g.id not in self.seen
                   for g in frame.get(goals_c.LIVE))

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if any(k in state.promises for k in state.kept) or self._fresh_reminders(state, frame):
            return frame.now
        due = self._due(state, params(frame.env.params_of("memory", frame.root)))
        return max(frame.now, due[0][0]) if due else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        p = params(frame.env.params_of("memory", frame.root))
        kept = [k for k in state.kept if k in state.promises]
        drafts = [c.PROMISE_RESOLVED.draft(promise=pid, status=c.HONORED, by=c.KEPT_BY,
                                           dedupe_key=f"promesse-tenue:{pid}") for pid in kept]
        drafts += [c.PROMISE_RESOLVED.draft(promise=pid, status=c.DROPPED, by=c.EXPIRED_BY,
                                            dedupe_key=f"promesse-abandonnée:{pid}")
                   for at, pid in self._due(state, p) if at <= frame.now and pid not in kept]
        done = {d.data.promise for d in drafts}
        drafts += [c.PROMISE_RESOLVED.draft(promise=pid, status=c.DROPPED, by=c.REMINDER_BY,
                                            dedupe_key=f"promesse-rappel:{pid}")
                   for pid in self._carried(ctx.ports.get("store"), state, frame) if pid not in done]
        if drafts:
            await ctx.emit(*drafts)

    def _carried(self, store: Any, state: MemoryState, frame: Frame) -> list[int]:
        """Les promesses qu'un rappel programmé après elles porte désormais : la même chose, pour la même
        personne, le même jour."""
        resolve, _ = identity_c.resolvers(frame.get)
        self.seen = {g.id for g in frame.get(goals_c.LIVE) if g.kind == goals_c.REMINDER}
        reminders = reminders_of(frame, store)
        pending = [pr for pr in state.promises.values() if pr.id not in state.kept]
        if not reminders or not pending or store is None:
            return []
        t = tb.items()
        texts = {int(i): said for chunk in batches(sorted({pr.id for pr in pending}))
                 for i, said in store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(chunk)))}
        return sorted(pr.id for pr in pending if any(
            r.owner == resolve(pr.to) and r.opened_at >= pr.at and same_task(texts.get(pr.id) or "", r.title)
            and same_day(frame, None if pr.implicit_due else pr.due, r.due) for r in reminders))
