"""Ce qu'on montre au modèle d'une conversation : ce que sa relecture voit.

Avec les messages, la relecture voit ce qu'elle sait déjà et qui touche cette conversation (``known_beliefs``, au
plus ``KNOWN_SHOWN``), ses promesses en cours, et de ses personnes : les situations en cours ou finies depuis peu, les
moments à venir, ceux passés depuis peu dont elle ne sait pas comment ils ont tourné, et les prévisions passées
qu'on n'a pas encore constatées (``Forecast``). Chacun vient avec son numéro, par lequel la relecture le désigne
(une situation que la personne dit finie, un moment reporté). Ni ce qu'un autre a confié au-delà de l'anodin, ni,
dans un salon, plus que ce que le salon peut entendre. Tout cela est facultatif : divisé par deux tant que l'appel
ne tient pas (``Shown.shrunk``, ``extract_request``) ; les messages, eux, ne le sont jamais. La même vue
(``shown_of``) sert à ses conversations (``consolidation.py``) et à celles qu'on lui montre d'un téléphone
(``relayed.py``, sans ses promesses : elle n'y a rien promis).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import func, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory import tables as tb
from mika.faculties.memory.archive import for_people
from mika.faculties.memory.conversation import Conversation, render
from mika.faculties.memory.faculty import MemoryParams, MemoryState, over
from mika.faculties.memory.speakers import People, scope_of
from mika.faculties.memory.tables import batches, handle_key, keys_of
from mika.kernel.clock import DAY
from mika.kernel.frame import Frame
from mika.ports.llm import LLMRequest, Message
from mika.ports.llm_budget import halved
from mika.vocab.affect import facets
from mika.vocab.circadian import day_fr
from mika.vocab.people import fold
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD

#: les croyances déjà connues montrées au modèle, au plus
KNOWN_SHOWN = 8


@dataclass(frozen=True, slots=True)
class Shown:
    """Ce que la relecture d'une conversation voit de ce qu'elle sait déjà — facultatif : divisé par deux tant que la
    requête ne tient pas (``shrunk`` ; les messages, eux, ne le sont jamais) —, et ce que désignent ses numéros."""

    known: list[tuple[int, str]]
    promises: list[tuple[int, str, str]]
    situations: list[tuple[int, str, str]]
    moments: list[tuple[int, str, str]]
    ended: list[tuple[int, str, str]]
    passed: list[tuple[int, str, str]]
    upcoming: dict[int, c.LifeEvent]
    gone: dict[int, c.LifeEvent]
    past: dict[int, c.LifeEvent]
    foreseen: dict[int, Forecast]

    @property
    def empty(self) -> bool:
        return not (self.known or self.promises or self.situations or self.moments or self.ended or self.passed)

    def shrunk(self, times: int) -> Shown:
        return replace(self, known=halved(self.known, times), promises=halved(self.promises, times),
                       situations=halved(self.situations, times), moments=halved(self.moments, times),
                       ended=halved(self.ended, times), passed=halved(self.passed, times))


async def shown_of(frame: Frame, store: Any, state: MemoryState, vectors: Any, conv: Conversation,
                   people: People, directory: dict[str, tuple[str, ...]], p: MemoryParams, *,
                   promises: bool = True) -> Shown:
    """Ce que la relecture d'une conversation voit de ce qu'elle sait déjà (``Shown``) — la même pour ses
    conversations et pour celles qu'on lui montre (``memory.relayed``, ``promises=False`` : elle n'y a rien promis)."""
    labels = {speaker.person: speaker.label for speaker in conv.speakers}
    moments, upcoming = _moments(frame, store, state, conv, labels)
    ended, gone = _ended_situations(frame, store, state, conv, p, labels)
    passed, past, foreseen = _behind(frame, store, state, conv, p, labels)
    return Shown(known=await known_beliefs(store, vectors, conv, people, directory),
                 promises=_promises(frame, store, state, conv) if promises else [],
                 situations=_situations(frame, store, state, conv, labels), moments=moments, ended=ended,
                 passed=passed, upcoming=upcoming, gone=gone, past=past, foreseen=foreseen)


def prompt_of(conv: Conversation, frame: Frame, state: MemoryState, shown: Shown) -> str:
    """Le message de la relecture : la conversation, et ce qu'elle en sait déjà (``conversation.render``)."""
    labels = {speaker.person: speaker.label for speaker in conv.speakers}
    return render(conv, now=frame.local(), beliefs=shown.known,
                  promises=[(i, _whom(frame, state, i, labels.get(to, to)), t) for i, to, t in shown.promises],
                  situations=shown.situations, moments=shown.moments, ended=shown.ended, passed=shown.passed)


def extract_request(conv: Conversation, frame: Frame, state: MemoryState, shown: Shown, times: int, *, system: str,
                    her: str, call_id: str, priority: int) -> tuple[LLMRequest, bool]:
    """L'appel de la relecture, avec ce qu'elle sait déjà divisé par deux ``times`` fois (``fit_by_halving``) ; et
    s'il reste de quoi diviser."""
    cut = shown.shrunk(times)
    return LLMRequest(role="extract", call_id=call_id, system_stable=system,
                      messages=(Message("user", prompt_of(conv, frame, state, cut)),), tools=(x.tool(her),),
                      max_tokens=x.MAX_OUTPUT_TOKENS, lane="background", priority=priority,
                      meta={"conversation": conv.key}), not cut.empty


async def known_beliefs(store: Any, vectors: Any, conv: Conversation, people: People,
                        directory: dict[str, tuple[str, ...]]) -> list[tuple[int, str]]:
    """Ce qu'elle sait déjà et qui touche cette conversation : ses
    personnes, ou quelqu'un qu'on y nomme — jamais ce que d'autres ont
    confié au-delà de l'anodin (le modèle pourrait le recopier ici). Pour
    un salon, seulement l'anodin : ce qu'Alice a confié en privé, recopié
    dans ce que le salon a « entendu », ferait de chacun un témoin."""
    text = " ".join(ln.text for ln in conv.lines)[-2000:]
    if vectors is None or not text.strip():
        return []
    hits = await vectors.search(text, KNOWN_SHOWN * 2, kinds={c.BELIEF})
    if not hits:
        return []
    ids = [k for k, _ in hits]
    t, tt = tb.items(), tb.testimonies()
    found = store.query_mind(select(t.c.id, t.c.text, t.c.about, t.c.told_by, t.c.sensitivity, t.c.secret)
                             .where(t.c.id.in_(ids), t.c.status == c.ACTIVE_STATUS))
    persons = set(conv.persons)
    named = {k for w in set(WORD.findall(fold(text))) for k in directory.get(w, ())
             if len(directory.get(w, ())) == 1}
    order = {k: n for n, k in enumerate(ids)}
    # qui l'a dit, témoignage par témoignage (ADR 0080) : ce que les personnes d'ici en ont dit elles-mêmes se
    # montre, même quand un autre l'avait confié avant
    tellers_of: dict[int, list[set[str]]] = {}
    for item, told, speaks in store.query_mind(select(tt.c.item, tt.c.told_by, tt.c.speaks)
                                               .where(tt.c.item.in_(ids)).order_by(tt.c.item, tt.c.seq)):
        if speaks:
            tellers_of.setdefault(int(item), []).append(set(keys_of(told)))
    out = []
    for i, t, about, told_by, sens, secret in sorted(found, key=lambda r: order[int(r[0])]):
        concerns = set(keys_of(about))
        anodyne = int(sens) <= Sensitivity.ANODYNE and not secret
        told_here = any(bool(tellers) and tellers <= persons
                        for tellers in tellers_of.get(int(i), [set(keys_of(told_by))]))
        if not (anodyne or (told_here and not conv.room)):
            continue
        # une mention faite dans cette conversation-ci (« ma collègue Alice ») la touche aussi : sans elle, un
        # « garde-le pour toi » dit après coup ne pouvait plus viser sa croyance (ADR 0075)
        mentioned = {k for k in concerns if scope_of(k) == people.scope}
        if concerns and not concerns & (persons | named | mentioned):
            continue
        out.append((int(i), t))
    return out[:KNOWN_SHOWN]


def _promises(frame: Frame, store: Any, state: MemoryState,
              conv: Conversation) -> list[tuple[int, str, str]]:
    """Les promesses en cours envers les personnes de cette conversation
    (des clés de personne : toutes leurs adresses comptent — une adresse
    reliée depuis à quelqu'un parle pour lui). Comme les situations et les
    moments : dans un salon, seulement ce que le salon peut entendre —
    l'anodin, ou ce qu'elle a promis dans ce salon même ; une promesse
    faite en privé, recopiée par le modèle dans ce que le salon a
    « entendu », ferait de chacun un témoin."""
    persons = set(conv.persons)
    pending = [(pr, frame.get(identity_c.PERSON(pr.to)) or pr.to) for pr in state.promises.values()]
    pending = [(pr, to) for pr, to in pending if to in persons]
    if not pending:
        return []
    ids = sorted({pr.id for pr, _ in pending})
    t = tb.items()
    rows = [r for chunk in batches(ids) for r in store.query_mind(
        select(t.c.id, t.c.text, t.c.sensitivity, t.c.sources).where(t.c.id.in_(chunk)).order_by(t.c.id))]
    texts = {int(i): t for i, t, _s, _m in rows}
    if conv.room:
        heard = {int(i) for i, _t, sens, sources in rows
                 if int(sens) <= Sensitivity.ANODYNE or _said_in(store, keys_of(sources), conv.room)}
        texts = {i: t for i, t in texts.items() if i in heard}
    return [(pr.id, to, texts.get(pr.id, "")) for pr, to in pending if texts.get(pr.id)]


def _said_in(store: Any, sources: Sequence[str], room: str) -> bool:
    """Tous ces messages ont été dits dans ce salon (et il y en a)."""
    ids = sorted({int(m) for m in sources if str(m).lstrip("-").isdigit()})
    if not ids:
        return False
    thread = transcript_c.thread_table()
    here = sum(int(store.query_mind(select(func.count()).select_from(thread)
                                    .where(thread.c.id.in_(chunk), thread.c.room == handle_key(room)))[0][0])
               for chunk in batches(ids))
    return here == len(ids)


def _situations(frame: Frame, store: Any, state: MemoryState, conv: Conversation,
                labels: dict[str, str]) -> list[tuple[int, str, str]]:
    """Les situations en cours des personnes de cette conversation (numéro, qui, texte) : la relecture peut dire
    lesquelles la personne dit finies. Comme les croyances connues, jamais ce qu'un autre a confié au-delà de
    l'anodin, et dans un salon l'anodin seulement (le modèle pourrait le recopier ici)."""
    persons = set(conv.persons)
    live: list[tuple[c.LifeEvent, str]] = []
    archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
    for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
        if not ev.ongoing or ev.ended_at or not ev.text_ref or ev.when > frame.now:
            continue
        whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
        if whom is None:
            continue
        tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
        anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
        if not (anodyne or (tellers <= persons and not conv.room)):
            continue
        live.append((ev, whom))
    if not live:
        return []
    texts = store.content([ev.text_ref for ev, _ in live])
    return [(ev.id, labels.get(whom, whom), phrase("memory.extraction.render.situation",
             since=frame.local(ev.when).date().isoformat(), text=texts[ev.text_ref]))
            for ev, whom in live if texts.get(ev.text_ref)]


def _moments(frame: Frame, store: Any, state: MemoryState, conv: Conversation,
             labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
    """Les moments à venir des personnes de cette conversation (numéro, qui, « le jour : texte ») : la relecture
    peut dire lequel un nouveau remplace — reporté, avancé, précisé (ADR 0076). Sans eux, « finalement mon
    entretien est reporté à lundi » notait un second entretien à côté du premier, et l'ancien, resté non secret,
    trahissait ce que le nouveau gardait (sonde réelle du 2026-10-09). Les mêmes règles que les situations :
    jamais ce qu'un autre a confié au-delà de l'anodin, et dans un salon l'anodin seulement."""
    persons = set(conv.persons)
    archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
    live: dict[int, tuple[c.LifeEvent, str]] = {}
    for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
        if ev.ongoing or ev.yearly or not ev.text_ref or over(ev) < frame.now or ev.outcome:
            continue  # passé : il est parmi les moments à constater (ADR 0086)
        whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
        if whom is None:
            continue
        tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
        anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
        if anodyne or (tellers <= persons and not conv.room):
            live[ev.id] = (ev, whom)
    if not live:
        return [], {}
    texts = store.content([ev.text_ref for ev, _ in live.values()])
    shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.moment",
                                               when=frame.local(ev.when).date().isoformat(),
                                               text=texts[ev.text_ref]))
             for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
    return shown, {i: ev for i, (ev, _w) in live.items()}


def _ended_situations(frame: Frame, store: Any, state: MemoryState, conv: Conversation, p: MemoryParams,
                      labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
    """Les situations des personnes de cette conversation finies depuis moins de ``recurrence_days`` (numéro, qui,
    « du … au … : texte ») : la relecture peut dire laquelle revient (« il est de nouveau malade »), et la
    reprise garde son fil (ADR 0079). Sans elles, la relecture ne voyait plus une situation finie : à la rechute
    du chat de Carol, elle n'a noté qu'un souvenir, et Mika ne suivait plus rien (sonde réelle du 2026-10-09).
    Les mêmes règles que les situations en cours : jamais ce qu'un autre a confié au-delà de l'anodin, et dans
    un salon l'anodin seulement."""
    persons = set(conv.persons)
    archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
    latest: dict[int, c.LifeEvent] = {}
    for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
        latest[ev.thread or ev.id] = ev  # d'un fil, la dernière fois seulement
    live: dict[int, tuple[c.LifeEvent, str]] = {}
    for ev in latest.values():
        if not (ev.ongoing and ev.ended_at and ev.text_ref) or frame.now - ev.ended_at > p.recurrence_days * DAY:
            continue
        whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
        if whom is None:
            continue
        tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
        anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
        if anodyne or (tellers <= persons and not conv.room):
            live[ev.id] = (ev, whom)
    if not live:
        return [], {}
    texts = store.content([ev.text_ref for ev, _ in live.values()])
    shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.ended_situation",
                                               since=frame.local(ev.when).date().isoformat(),
                                               ended=frame.local(ev.ended_at).date().isoformat(),
                                               text=texts[ev.text_ref]))
             for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
    return shown, {i: ev for i, (ev, _w) in live.items()}


def _passed(frame: Frame, store: Any, state: MemoryState, conv: Conversation, p: MemoryParams,
            labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
    """Les moments des personnes de cette conversation passés depuis moins de ``resolve_days``, dont elle ne sait
    pas comment ils ont tourné (numéro, qui, « le jour : texte ») : si la personne le dit, la relecture le constate
    (ADR 0086). Les mêmes règles que les moments à venir : jamais ce qu'un autre a confié au-delà de l'anodin, et
    dans un salon l'anodin seulement."""
    persons = set(conv.persons)
    archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
    since = frame.now - round(p.resolve_days * DAY)
    live: dict[int, tuple[c.LifeEvent, str]] = {}
    for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
        if ev.ongoing or ev.yearly or ev.outcome or not ev.text_ref or not since <= over(ev) < frame.now:
            continue
        whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
        if whom is None:
            continue
        tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
        anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
        if anodyne or (tellers <= persons and not conv.room):
            live[ev.id] = (ev, whom)
    if not live:
        return [], {}
    texts = store.content([ev.text_ref for ev, _ in live.values()])
    shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.moment",
                                               when=frame.local(ev.when).date().isoformat(),
                                               text=texts[ev.text_ref]))
             for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
    return shown, {i: ev for i, (ev, _w) in live.items()}


def _behind(frame: Frame, store: Any, state: MemoryState, conv: Conversation, p: MemoryParams,
            labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent],
                                              dict[int, Forecast]]:
    """Ce qui est passé sans qu'elle sache comment ça a tourné, montré à la relecture : les moments, puis les
    prévisions (ADR 0086, 0099)."""
    passed, past = _passed(frame, store, state, conv, p, labels)
    forecasts, foreseen = _forecasts(frame, store, conv, p, labels)
    return [*passed, *forecasts], past, foreseen


def _forecasts(frame: Frame, store: Any, conv: Conversation, p: MemoryParams,
               labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, Forecast]]:
    """Les prévisions des personnes de cette conversation (« Léa pense qu'elle sera prise ») dont l'échéance est
    passée depuis moins de ``resolve_days`` et qu'on n'a pas encore constatées : montrées avec les moments passés,
    pour que la relecture dise si elles se sont réalisées (ADR 0099). Les mêmes règles de discrétion que les
    moments : dans un salon, l'anodin seulement ; jamais ce qu'un autre a confié au-delà."""
    persons = set(conv.persons)
    since = frame.now - round(p.resolve_days * DAY)
    t = tb.items()
    ends = func.coalesce(t.c.until, t.c.due)
    rows = store.query_mind(
        select(t.c.id, t.c.text, t.c.about, t.c.holder, t.c.told_by, t.c.likelihood, t.c.importance, t.c.due,
               t.c.until, t.c.sensitivity, t.c.secret, t.c.felt, t.c.empathy)
        .where(t.c.kind == c.BELIEF, t.c.knowledge_kind == "prediction", t.c.status == c.ACTIVE_STATUS,
               t.c.due.is_not(None), ends < frame.now, ends >= since).order_by(t.c.id))
    shown: list[tuple[int, str, str]] = []
    found: dict[int, Forecast] = {}
    for (item, text, about, holder, told_by, likely, importance, due, until, sens, secret, felt,
         empathy) in rows:
        concerned = {frame.get(identity_c.PERSON(k)) or k for k in (*keys_of(about), *([holder] if holder else []))}
        whom = next((k for k in sorted(concerned) if k in persons), None)
        if whom is None or not text:
            continue
        tellers = {frame.get(identity_c.PERSON(t)) or t for t in keys_of(told_by)}
        if not (int(sens) <= Sensitivity.ANODYNE and not secret) and (conv.room or not tellers <= persons):
            continue
        found[int(item)] = Forecast(int(item), keys_of(about), holder or "", likely, float(importance or 0.5),
                                    tuple(concerned), _facets_of(empathy) or _facets_of(felt))
        shown.append((int(item), labels.get(whom, whom), phrase(
            "memory.extraction.render.forecast", when=frame.local(int(until or due)).date().isoformat(),
            text=str(text))))
    return shown, found


@dataclass(frozen=True, slots=True)
class Forecast:
    """Une prévision passée qu'on n'a pas encore constatée (ADR 0099) : l'élément, qui elle concerne, qui la portait
    (vide : la sienne), ce qu'elle en attendait, ce qu'elle compte, qui peut la constater, comment on l'attendait."""

    item: int
    about: tuple[str, ...]
    holder: str
    likelihood: float | None
    importance: float
    concerned: tuple[str, ...]
    felt: tuple[tuple[str, float], ...]


def _facets_of(raw: Any) -> tuple[tuple[str, float], ...]:
    """Des facettes gardées en JSON (« [["sad", 0.6]] ») ; illisibles : aucune."""
    try:
        return facets(json.loads(raw or "[]"))
    except (TypeError, ValueError):
        return ()


def _whom(frame: Frame, state: MemoryState, promise: int, label: str) -> str:
    """À qui, et pour quand (une promesse datée) : le modèle voit qu'elle n'est due que ce jour-là."""
    pr = state.promises.get(promise)
    if pr is None or pr.due is None or pr.implicit_due:
        return label
    due = frame.local(pr.due)
    if pr.all_day:
        return phrase("memory.extraction.due_day", label=label, day=day_fr(due.date()))
    return phrase("memory.extraction.due_time", label=label, day=day_fr(due.date()), time=f"{due:%H:%M}")
