"""La vie des autres : leurs moments, repris, et le temps d'un moment.

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

Ses promesses — les tenir au moment dit, les laisser filer — sont dans ``promises.py`` ; ce qui dit que deux phrases
parlent de la même chose à faire (``same_task``) ou du même jour (``same_day``) est ici, que les moments et les
promesses partagent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory.faculty import (
    MEMORY,
    MemoryParams,
    MemoryState,
    day_of,
    events_at,
    params,
)
from mika.kernel.clock import DAY
from mika.kernel.events import Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.affect import facets_valence
from mika.vocab.people import is_identifiable
from mika.vocab.words import fold, stems

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


def same_day(frame: Frame, a: int | None, b: int | None) -> bool:
    """Le même jour (heure locale) — ou l'un des deux sans date : rien ne les distingue."""
    return a is None or b is None or frame.local(a).date() == frame.local(b).date()


def _names(frame: Frame, person: str) -> tuple[str, ...]:
    return (frame.get(identity_c.IDENTITY(person)).name, self_c.name_of(frame.get(self_c.PERSONA)))


def _concerns(frame: Frame, ev: c.LifeEvent, person: str) -> bool:
    """Ce moment est-il de la vie de cette personne ? Une clé notée alors (une adresse, un nom) parle pour elle
    quand elle lui a été reliée depuis — comme pour ``LIFE_EVENTS`` (ADR 0035, 0048)."""
    resolve, _ = identity_c.resolvers(frame.get)
    return any(k == person or resolve(k) == person for k in ev.about)


# ── Ce que la personne en dit elle-même : jugé à l'arrivée du message ─────


@MEMORY.interpret(rt.PERCEPTION_RECEIVED)
def _told_about(s: MemoryState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """La personne parle elle-même d'un moment de sa vie, une fois passé (« l'entretien s'est super bien passé »)
    : elles en ont reparlé — sa réponse le sait déjà."""
    resolve, _ = identity_c.resolvers(frame.get)
    d = ev.data
    text = d.text.text or ""
    if not d.addressed or not is_identifiable(d.handle) or not text.strip() or not s.events:
        return []
    p = params(frame.env.params_of("memory", frame.root))
    person = resolve(d.handle)
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
        resolve, _ = identity_c.resolvers(frame.get)
        for seq, at, handle, said in rows:
            person = resolve(handle)
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
