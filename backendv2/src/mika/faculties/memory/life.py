"""La vie des autres, et sa parole à elle.

**Un moment repris.** Ce qu'une amie lui avait dit de prévu (« jeudi, mon
entretien chez Ubisoft »), ou ce qui dure dans sa vie (« Moustache est
malade »), est *repris* quand l'une ou l'autre en reparle en mots, une fois le
moment passé (une situation : une fois apprise) : elle lui demande « alors, cet
entretien ? », ou la personne lui raconte d'elle-même « l'entretien s'est bien
passé ». C'est un jugement enregistré (``memory.moment_followed``) — un
radical du moment en commun, son prénom mis à part —, jamais « elle l'avait
sous les yeux » : une initiative partie pour autre chose, qui l'avait en bas de
son état sans en parler, ne l'éteint plus (audit HUM-1). Les mots de la
personne se jugent à leur arrivée (un interprète : sa réponse le sait déjà),
les siens après coup (``memory.follow``, qui relit ce qu'elle a dit).

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

**Quand un moment s'ouvre.** Un moment « jour entier » (« le véto, ce
midi ») a pour instant la fin d'après-midi de ce jour-là ; mais ce que la
personne en raconte **ce jour-là** (« le véto dit insuffisance rénale ») le
reprend déjà — sinon, le lendemain, elle lui demandait comment ça s'était passé
(sonde réelle du 2026-10-03). Un moment qui se fête (un anniversaire) s'ouvre
au début de sa journée, pour l'une comme pour l'autre : ses vœux (« joyeux
anniversaire ! ») le reprennent. Une date qui revient chaque année se juge à
son occurrence de cette année : ses vœux de l'an dernier ne la reprennent pas.

**Comment un moment a tourné.** ``resolution`` l'écrit d'une seule façon,
avec ce qu'elle en attendait et de qui elle l'apprend (ADR 0086) : la
consolidation et la relecture de la nuit le disent pareil.

**Laisser filer.** Une promesse que rien n'a réglée bien après son échéance
s'abandonne (``memory.promises``) : rien ne reste dû pour toujours.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from sqlalchemy import select

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory import tables as tb
from mika.faculties.memory.faculty import (
    MEMORY,
    PROMISE_SUBJECT,
    Keeping,
    MemoryParams,
    MemoryState,
    day_of,
    events_at,
    params,
)
from mika.faculties.memory.tables import batches
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, instant
from mika.kernel.events import Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.state import FrozenDict
from mika.vocab.affect import facets_valence
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.words import fold, stems

#: le début de la fenêtre d'une promesse : la preuve monte depuis là
KEEP_EVIDENCE_START = 2.0
#: des vœux (replié, sans accents) : « joyeux anniv ! », « bon anniversaire », « félicitations », « tous mes vœux »
_WISHES = re.compile(r"\b(?:joyeux|joyeuse|bon|bonne|happy)\s+(?:anniv\w*|fete|birthday|mariage|noel)\b|"
                     r"\bfelicit\w*|\b(?:tous\s+)?mes\s+(?:meilleurs\s+)?voeux\b|\bjoyeux\s+\d+\s+ans\b")
#: les mots d'une tâche, de sa date, du rappel lui-même (des radicaux) : deux tâches ne se ressemblent pas pour
#: avoir le même jour ou le même verbe
_TASK_STEMS = frozenset({"rappel", "penser", "oublie", "noubli", "prendr", "lundi", "mardi", "mercre", "jeudi",
                         "vendre", "samedi", "dimanc", "demain", "matin", "soir", "soiree", "heure", "heures",
                         "aprem", "midi", "rendez"})


def takes_up(moment: str, said: str, names: Iterable[str] = ()) -> bool:
    """Ce qui est dit reprend-il ce moment ? Un radical du moment en commun suffit — « alors, cet entretien ? »
    reprend « son entretien chez Ubisoft » —, les prénoms à part : « Alice » ne dit rien du moment."""
    own = stems(moment) - {st for n in names if n for st in stems(n)}
    return bool(own & stems(said))


def wishes(said: str) -> bool:
    """Des vœux : « joyeux anniversaire ! », « bon anniv », « félicitations »."""
    return bool(_WISHES.search(fold(said)))


def takes_up_moment(ev: c.LifeEvent, moment: str, said: str, names: Iterable[str] = ()) -> bool:
    """Ce qui est dit reprend-il ce moment ? Pour un moment qui se fête, des vœux suffisent (« bon anniv ! »
    n'a pas le radical d'« anniversaire »)."""
    return takes_up(moment, said, names) or (ev.festive and wishes(said))


def same_task(a: str, b: str) -> bool:
    """Deux phrases qui parlent de la même chose à faire (« lui rappeler de prendre rendez-vous chez le
    dentiste » et « prendre rdv chez le dentiste ») : un mot du sujet en commun, hors du rappel, du jour et des
    verbes de tous les jours."""
    return bool((stems(a) - _TASK_STEMS) & (stems(b) - _TASK_STEMS))


def opens_at(ev: c.LifeEvent, frame: Frame, *, theirs: bool) -> int:
    """Depuis quand un moment passé peut être repris en mots. Une situation : depuis qu'elle dure. Un moment qui
    se fête : dès le début de sa journée (ses vœux le reprennent). Un moment « jour entier », par ce que la
    personne en dit : dès le début de sa journée aussi (« le véto dit insuffisance rénale », à 13 h, raconte le
    rendez-vous de midi — sa date, 18 h, n'est qu'une fin d'après-midi de convention). Sinon : son heure."""
    if ev.ongoing:
        return ev.when
    if ev.festive or (theirs and ev.all_day):
        return min(ev.when, day_of(ev.when, frame.env.tz_of(frame.root)))
    return ev.when


def open_moment(ev: c.LifeEvent, now: int, p: MemoryParams, opens: int | None = None) -> bool:
    """Un moment dont on peut encore reparler : ouvert (``opens``, son heure par défaut), passé depuis peu et pas
    encore repris ; une situation en cours, que la personne n'a pas dite finie, pas reprise ces derniers jours."""
    if ev.ongoing:
        if ev.ended_at or not ev.when <= now <= ev.when + round(p.situation_days * DAY):
            return False
        return not ev.followed_at or now - ev.followed_at >= round(p.situation_reask_days * DAY)
    start = ev.when if opens is None else opens
    return not ev.followed_at and start <= now <= ev.when + round(p.event_recent_days * DAY)


def _names(frame: Frame, person: str) -> tuple[str, ...]:
    return (frame.get(identity_c.IDENTITY(person)).name, self_c.name_of(frame.get(self_c.PERSONA)))


def _concerns(frame: Frame, ev: c.LifeEvent, person: str) -> bool:
    """Ce moment est-il de la vie de cette personne ? Une clé notée alors (une adresse, un nom) parle pour elle
    quand elle lui a été reliée depuis — comme pour ``LIFE_EVENTS`` (ADR 0035, 0048)."""
    return any(k == person or (frame.get(identity_c.PERSON(k)) or k) == person for k in ev.about)


# ── Ce que la personne en dit elle-même : jugé à l'arrivée du message ─────


@MEMORY.interpret(rt.PERCEPTION_RECEIVED)
def _told_about(s: MemoryState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """La personne parle elle-même d'un moment de sa vie, une fois passé (« l'entretien s'est super bien passé »)
    : elles en ont reparlé — sa réponse le sait déjà."""
    d = ev.data
    text = d.text.text or ""
    if not d.addressed or not is_identifiable(d.handle) or not text.strip() or not s.events:
        return []
    p = params(frame.env.params_of("memory", frame.root))
    person = frame.get(identity_c.PERSON(d.handle)) or d.handle
    # ce qui se fête n'est « repris » que par ses vœux à elle : « c'est mon anniv aujourd'hui ! » ne le lui souhaite pas
    mine = [e for e in events_at(s, ev.at, frame.env.tz_of(frame.root), p)
            if _concerns(frame, e, person) and e.id < ev.seq and not e.festive
            and open_moment(e, ev.at, p, opens_at(e, frame, theirs=True))]
    store = ports.get("store") if ports else None
    if not mine or store is None:
        return []
    texts = store.content([e.text_ref for e in mine if e.text_ref])
    names = _names(frame, person)
    return [c.MOMENT_FOLLOWED.draft(event=e.id, by=person, thread=e.key, occurrence=e.when,
                                    dedupe_key=f"repris:{e.id}:{ev.seq}")
            for e in sorted(mine, key=lambda e: e.id)
            if takes_up_moment(e, texts.get(e.text_ref) or "", text, names)]


# ── Ce qu'elle en a dit : relu après coup ─────────────────────────────────


@MEMORY.process("memory.follow", wake_on=[rt.UTTERANCE, c.EVENT_NOTED, c.MOMENT_FOLLOWED],
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Follow:
    """Relit ce qu'elle a dit depuis la dernière fois : ce qui reprend un moment de la vie de la personne à qui
    elle parlait (« alors, cet entretien ? ») le dit repris."""

    def __init__(self) -> None:
        #: le dernier message du fil relu (le fil est rejouable : après un redémarrage, on relit, sans doublon)
        self.upto = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("memory", frame.root))
        if not any(open_moment(e, frame.now, p, opens_at(e, frame, theirs=False))
                   for e in events_at(state, frame.now, frame.env.tz_of(frame.root), p)):
            return None
        return frame.now if frame.get(transcript_c.HEAD) > self.upto else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        head = frame.get(transcript_c.HEAD)
        p = params(frame.env.params_of("memory", frame.root))
        events = events_at(state, frame.now, frame.env.tz_of(frame.root), p)
        opens = {e.id: opens_at(e, frame, theirs=False) for e in events}
        moments = [e for e in events if open_moment(e, frame.now, p, opens[e.id])]
        if store is None or not moments:
            self.upto = head
            return
        since = min(opens[e.id] for e in moments)
        t = transcript_c.thread_table()
        rows = store.query_mind(select(t.c.id, t.c.at, t.c.person, t.c.text)
                                .where(t.c.role == "assistant", t.c.id > self.upto, t.c.id <= head, t.c.at >= since)
                                .order_by(t.c.id))
        texts = store.content([e.text_ref for e in moments if e.text_ref])
        drafts: list[Draft[Any]] = []
        done: set[int] = set()
        for seq, at, handle, said in rows:
            person = frame.get(identity_c.PERSON(handle)) or handle
            names = _names(frame, person)
            for e in moments:
                if e.id in done or not _concerns(frame, e, person) or int(seq) < e.id or int(at) < opens[e.id]:
                    continue
                if takes_up_moment(e, texts.get(e.text_ref) or "", str(said or ""), names):
                    done.add(e.id)
                    drafts.append(c.MOMENT_FOLLOWED.draft(event=e.id, thread=e.key, occurrence=e.when,
                                                          dedupe_key=f"repris:{e.id}:{seq}"))
        self.upto = head
        if drafts:
            await ctx.emit(*drafts)


# ── Comment un moment a tourné ────────────────────────────────────────────


def resolution(ev: c.LifeEvent, outcome: str, by: str, sources: Sequence[int], call_id: str) -> Draft[Any]:
    """Comment ce moment a tourné, avec ce qu'elle en attendait et de qui elle en apprend (ADR 0086) — une seule
    façon, pour la consolidation et la relecture de la nuit."""
    return c.RESOLVED.draft(
        event=ev.id, thread=ev.key, outcome=outcome, by=by, likelihood=ev.likelihood, importance=ev.importance,
        surprise=lk.surprise(outcome, ev.likelihood, ev.importance) if outcome != c.UNKNOWN else 0.0,
        nature=lk.nature_of(ev), teller=ev.told_by[0] if ev.told_by else "", shared=ev.shared,
        valence=round(facets_valence(ev.empathy or ev.felt), 3), about=ev.about, sources=tuple(sources),
        call_id=call_id, dedupe_key=f"issue:{ev.key}:{ev.when}")


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


@MEMORY.propose(kinds=[Kind.INITIATIVE], reasons={c.KEEP_PROMISE: (0.0, 12.0)},
                reads=[identity_c.PERSON, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                       presence_c.PRESENT, transcript_c.LAST_FROM])
def _keep(s: MemoryState, frame: Frame) -> list[Candidate]:
    """Une promesse datée, au moment dit : elle la tient d'elle-même. Pas si elles se sont parlé depuis le début
    de la fenêtre (la conversation en était l'occasion), ni après trop d'essais."""
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
        to = frame.get(identity_c.PERSON(pr.to)) or pr.to  # une adresse reliée depuis à quelqu'un parle pour lui
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


def same_day(frame: Frame, a: int | None, b: int | None) -> bool:
    """Le même jour (heure locale) — ou l'un des deux sans date : rien ne les distingue."""
    return a is None or b is None or frame.local(a).date() == frame.local(b).date()


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
        owners = {frame.get(identity_c.PERSON(pr.to)) or pr.to for pr in state.promises.values()}
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
        self.seen = {g.id for g in frame.get(goals_c.LIVE) if g.kind == goals_c.REMINDER}
        reminders = reminders_of(frame, store)
        pending = [pr for pr in state.promises.values() if pr.id not in state.kept]
        if not reminders or not pending or store is None:
            return []
        t = tb.items()
        texts = {int(i): said for chunk in batches(sorted({pr.id for pr in pending}))
                 for i, said in store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(chunk)))}
        return sorted(pr.id for pr in pending if any(
            r.owner == (frame.get(identity_c.PERSON(pr.to)) or pr.to) and r.opened_at >= pr.at and same_task(texts.get(pr.id) or "", r.title)
            and same_day(frame, None if pr.implicit_due else pr.due, r.due) for r in reminders))
