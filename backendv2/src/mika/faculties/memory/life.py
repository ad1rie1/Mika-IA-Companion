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
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import MEMORY, PROMISE_SUBJECT, Keeping, MemoryParams, MemoryState, params
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, instant
from mika.kernel.events import Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable
from mika.vocab.words import stems

#: le début de la fenêtre d'une promesse : la preuve monte depuis là
KEEP_EVIDENCE_START = 2.0


def takes_up(moment: str, said: str, names: Iterable[str] = ()) -> bool:
    """Ce qui est dit reprend-il ce moment ? Un radical du moment en commun suffit — « alors, cet entretien ? »
    reprend « son entretien chez Ubisoft » —, les prénoms à part : « Alice » ne dit rien du moment."""
    own = stems(moment) - {st for n in names if n for st in stems(n)}
    return bool(own & stems(said))


def open_moment(ev: c.LifeEvent, now: int, p: MemoryParams) -> bool:
    """Un moment dont on peut encore reparler : passé depuis peu et pas encore repris ; une situation en cours,
    pas reprise ces derniers jours."""
    if ev.ongoing:
        if not ev.when <= now <= ev.when + round(p.situation_days * DAY):
            return False
        return not ev.followed_at or now - ev.followed_at >= round(p.situation_reask_days * DAY)
    return not ev.followed_at and ev.when <= now <= ev.when + round(p.event_recent_days * DAY)


def _names(frame: Frame, person: str) -> tuple[str, ...]:
    return (frame.get(identity_c.IDENTITY(person)).name, "Mika")


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
    mine = [e for e in s.events.values() if person in e.about and e.id < ev.seq and open_moment(e, ev.at, p)]
    store = ports.get("store") if ports else None
    if not mine or store is None:
        return []
    texts = store.content([e.text_ref for e in mine if e.text_ref])
    names = _names(frame, person)
    return [c.MOMENT_FOLLOWED.draft(event=e.id, by=person, dedupe_key=f"repris:{e.id}:{ev.seq}")
            for e in sorted(mine, key=lambda e: e.id) if takes_up(texts.get(e.text_ref) or "", text, names)]


# ── Ce qu'elle en a dit : relu après coup ─────────────────────────────────


@MEMORY.process("memory.follow", wake_on=[rt.UTTERANCE, c.EVENT_NOTED, c.MOMENT_FOLLOWED], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Follow:
    """Relit ce qu'elle a dit depuis la dernière fois : ce qui reprend un moment de la vie de la personne à qui
    elle parlait (« alors, cet entretien ? ») le dit repris."""

    def __init__(self) -> None:
        #: le dernier message du fil relu (le fil est rejouable : après un redémarrage, on relit, sans doublon)
        self.upto = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("memory", frame.root))
        if not any(open_moment(e, frame.now, p) for e in state.events.values()):
            return None
        return frame.now if frame.get(transcript_c.HEAD) > self.upto else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        head = frame.get(transcript_c.HEAD)
        p = params(frame.env.params_of("memory", frame.root))
        moments = [e for e in state.events.values() if open_moment(e, frame.now, p)]
        if store is None or not moments:
            self.upto = head
            return
        since = min(e.when for e in moments)
        rows = store.query_mind(f"SELECT id, at, person, text FROM {transcript_c.THREAD_TABLE} WHERE role='assistant' "
                                "AND id>? AND id<=? AND at>=? ORDER BY id", (self.upto, head, since))
        texts = store.content([e.text_ref for e in moments if e.text_ref])
        drafts: list[Draft[Any]] = []
        done: set[int] = set()
        for seq, at, handle, said in rows:
            person = frame.get(identity_c.PERSON(handle)) or handle
            names = _names(frame, person)
            for e in moments:
                if e.id in done or person not in e.about or int(seq) < e.id or int(at) < e.when:
                    continue
                if takes_up(texts.get(e.text_ref) or "", str(said or ""), names):
                    done.add(e.id)
                    drafts.append(c.MOMENT_FOLLOWED.draft(event=e.id, dedupe_key=f"repris:{e.id}:{seq}"))
        self.upto = head
        if drafts:
            await ctx.emit(*drafts)


# ── Tenir parole au moment dit ────────────────────────────────────────────


def keep_window(pr: c.PendingPromise, frame: Frame, p: MemoryParams) -> tuple[int, int, int] | None:
    """(début, preuve pleine à partir de, fin) de la fenêtre où tenir une promesse datée ; ``None`` sans date.
    À une heure dite : un peu avant, jusqu'à un peu après ; un jour sans heure : dans la journée."""
    if pr.due is None or pr.implicit_due:
        return None
    if pr.all_day:
        tz = frame.env.tz_of(frame.root)
        day = frame.local(pr.due).date()
        start = instant(datetime.combine(day, time(p.promise_day_start_min // 60 % 24, p.promise_day_start_min % 60),
                                         tzinfo=tz))
        full = max(start + 1, pr.due - p.promise_lead_us)
    else:
        start, full = pr.due - p.promise_lead_us, pr.due
    return min(start, pr.due), max(full, start + 1), pr.due + p.keep_late_us


def _address(frame: Frame, person: str) -> str | None:
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def _last_from(frame: Frame, person: str) -> int:
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    return max(frame.get(transcript_c.LAST_FROM(h)) for h in handles)


@MEMORY.propose(kinds=[Kind.INITIATIVE], reasons={c.KEEP_PROMISE: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       transcript_c.LAST_FROM])
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
        if _last_from(frame, pr.to) >= max(start, pr.at):
            continue  # elles se sont parlé depuis : c'était l'occasion, le prompt le lui montrait
        address = _address(frame, pr.to)
        if address is None:
            continue
        ramp = min(1.0, max(0.0, (now - start) / (full - start)))
        evidence = KEEP_EVIDENCE_START + (p.keep_evidence - KEEP_EVIDENCE_START) * ramp
        name = frame.get(identity_c.IDENTITY(pr.to)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        when = "aujourd'hui" if pr.all_day else "maintenant"
        brief = (f"Tu avais promis à {who} quelque chose pour {when} — c'est dans « CE QUE TU LUI AS PROMIS » "
                 f"(n° {pr.id}) : c'est le moment de le faire. Fais-le simplement, comme quelqu'un qui tient parole.")
        handles = frame.get(identity_c.HANDLES(pr.to)) or (pr.to,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        out.append(Candidate(Kind.INITIATIVE, address, c.KEEP_PROMISE, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:memory": brief, "subject": f"{PROMISE_SUBJECT}{pr.id}"})))
    return out
