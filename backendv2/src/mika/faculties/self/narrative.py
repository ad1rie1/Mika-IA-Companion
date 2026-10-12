"""Le récit qu'elle fait d'elle-même (« Je suis quelqu'un qui… »), réécrit par sa propre voix au plus une fois par
jour, quand elle a changé assez — ce qui l'a marquée (importance, émotion — pas l'ordre d'arrivée), mais aussi ce
qu'elle sait d'elle maintenant (ADR 0090) : ses goûts et ses avis qui la définissent, ses changements d'avis, ce qui
la passionne, ses tendances (tenir parole, mener au bout, voir venir), et ce qu'elle a vécu à travers les autres —
en bref, sans dire qui, seulement ce que la personne est pour elle. De ce qui ne peut pas se raconter, seulement ce
que ça lui a fait. Il est montré à tout le monde : jamais un prénom (ADR 0053, 0078). Il suit ses sources : l'une
devenue secrète, il se tait ; remplacée, contestée, ou une personne oubliée, il se réécrit (ADR 0082)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as c
from mika.contracts import social as social_c
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.lines import KNOWN_LINES, passion_lines
from mika.faculties.self.persona import persona_for
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import HOUR
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.faculty import CatchUp, Zone
from mika.kernel.frame import Audience, Frame
from mika.ports.llm import LLMRequest, Message
from mika.vocab import affect as A
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.knowledge import Known, knowns
from mika.vocab.lineage import Lineage, admits, requirement, without_whom
from mika.vocab.people import mentions
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import PUBLIC_FLOOR, Sensitivity


@SELF.reducer(memory_c.REMEMBERED)
def _lived(s: SelfState, e, cx) -> SelfState:
    """Un souvenir de plus ; vécu à travers quelqu'un et dicible en bref, un vécu de plus (ADR 0090)."""
    return replace(s, souvenirs=s.souvenirs + 1, lived=s.lived + (1 if e.data.gist is not None else 0))


@SELF.reducer(memory_c.BELIEVED, memory_c.ATTESTED)
def _said_of_herself(s: SelfState, e, cx) -> SelfState:
    """Ce qu'elle dit d'elle qui la définit, et ses changements d'avis : de quoi la faire changer (ADR 0090)."""
    d = e.data
    if not d.about_self:
        return s
    return replace(s, self_beliefs=s.self_beliefs + (1 if d.durable else 0),
                   changes=s.changes + (1 if d.replaces is not None else 0))


@SELF.reducer(c.NARRATED)
def _narrated(s: SelfState, e, cx) -> SelfState:
    d = e.data
    return replace(s, narrative_ref=d.text.ref or "", narrated_at=e.at, narrated_souvenirs=d.souvenirs,
                   narrative_about=d.about, narrative_sources=d.sources, narrative_stale=False,
                   narrative_masked=False, narrated_self_beliefs=s.self_beliefs, narrated_changes=s.changes,
                   narrated_lived=s.lived, narrated_knows=d.knows, narrated_interests=d.interests)


@SELF.reducer(*memory_c.WITHDRAWING)
def _sources_withdrawn(s: SelfState, e, cx) -> SelfState:
    """Ce qu'elle a écrit à partir de ce qu'elle sait suit ses sources (ADR 0082) : un souvenir devenu secret (ou une
    confidence : un sujet délicat, ADR 0099) fait taire le récit (jusqu'à sa réécriture), le rêve et la version intime
    du journal qui le reprenaient ; remplacé,
    contesté, joint, il fait réécrire le récit — un rêve, une journée écrite, restent ce qu'ils étaient."""
    gone = memory_c.withdrawals(e.type.name, e.data, e.seq)
    if not gone:
        return s
    private = {w.item for w in gone if w.reason in memory_c.PRIVATE_REASONS}
    # joint à la même croyance, une situation finie : ce qu'il disait reste vrai
    every = {w.item for w in gone if w.reason in (*memory_c.PRIVATE_REASONS, memory_c.SUPERSEDED, memory_c.CONTESTED)}
    if set(s.narrative_sources) & every:
        s = replace(s, narrative_stale=True, narrative_masked=s.narrative_masked or bool(set(s.narrative_sources) & private))
    if not private:
        return s

    def touched(lineage) -> bool:
        return lineage is not None and bool(set(lineage.sources) & private)

    dreams = tuple(replace(d, masked=True) if touched(d.lineage) else d for d in s.dreams)
    journals = s.journals
    for day, j in s.journals.items():
        if touched(j.lineage):
            journals = journals.set(day, replace(j, masked=True))
    return replace(s, dreams=dreams, journals=journals)


@SELF.reducer(SUBJECT_FORGOTTEN)
def _forgot_someone(s: SelfState, e, cx) -> SelfState:
    """Oublier une personne d'où vient une part du récit (ce qu'elle a vécu à travers elle) : il se tait, et se
    réécrit sans elle (ADR 0090)."""
    if e.data.subject not in s.narrative_about:
        return s
    return replace(s, narrative_stale=True, narrative_masked=True,
                   narrative_about=tuple(p for p in s.narrative_about if p != e.data.subject))


#: ce qui fait qu'un souvenir a marqué : son importance, et la force de ce qu'il fait ressentir (sa valence)
SALIENCE_EMOTION = 0.3
#: ce qui l'a marquée sans pouvoir se raconter, dit sans qui ni quoi : au plus tant de lignes
FELT_SHOWN = 4
#: les souvenirs relus, au plus (on garde les plus marquants)
NARRATIVE_ROWS = 400
#: ses notes sur elle qui la définissent, ses changements d'avis, ce qu'elle a vécu à travers les autres : au plus
BELIEFS_SHOWN, CHANGES_SHOWN, LIVED_SHOWN = 8, 3, 4
#: ce que le récit peut dire en bref d'un moment vécu à travers quelqu'un, sans dire qui (ADR 0087)
LIVED_CEILING = int(Sensitivity.PERSONAL)


def salience(importance: float | None, emotion: str | None) -> float:
    """Ce qu'un souvenir a marqué : son importance, plus la force de ce qu'il a fait ressentir."""
    e = A.emotion_of(emotion)
    return float(importance or 0.0) + (SALIENCE_EMOTION * abs(A.valence(e)) if e is not None else 0.0)


def material(rows: list[Known], frame: Frame, shown: int) -> tuple[list[Known], list[str]]:
    """Ses souvenirs à elle, choisis par saillance et non par ordre d'arrivée (ADR 0053 ; sonde réelle du
    2026-10-03 : « QUI TU ES DEVENUE » réécrit à partir de « allez j'y vais » la semaine où le chat d'un ami est
    mort) : ceux qui ne concernent personne d'autre, du plus marquant au moins marquant — le récit est montré à tout
    le monde, et ne nomme personne (ADR 0090). Ce qui l'a marquée sans pouvoir se raconter (une confidence, la peine
    de quelqu'un) : seulement ce que ça lui a fait, et si c'était avec quelqu'un qui compte — jamais qui, ni quoi
    (audit du 2026-10-09)."""
    told, closed = [], []
    resolve, presumed = identity_c.resolvers(frame.get)
    for k in rows:
        hers = not k.about and not k.told_by and not k.secret and not k.lineage.internal_only and not k.holder
        if hers:
            told.append(k)
        elif not admits(k.lineage, None, PUBLIC_FLOOR, resolve=resolve, presumed=presumed).ok:
            closed.append(k)
    told = sorted(told, key=lambda k: -salience(k.importance, k.emotion))[:shown]
    groups: dict[tuple[str, bool], list[float]] = {}
    for k in closed:
        e = A.emotion_of(k.emotion)
        if e is None or e is A.Emotion.NEUTRAL:
            continue  # ce qui ne lui a rien fait ressentir ne dit rien d'elle sans son contenu
        dear = any(frame.get(social_c.CLOSENESS(x)) in (social_c.FRIEND, social_c.CLOSE) for x in k.about)
        groups.setdefault((e.value, dear), []).append(salience(k.importance, k.emotion))
    felt = []
    for (name, dear), values in sorted(groups.items(), key=lambda kv: (-max(kv[1]), -len(kv[1]), kv[0]))[:FELT_SHOWN]:
        e = A.emotion_of(name)
        if e is None:
            continue
        whom = phrase("self.narrative.with_dear") if dear else phrase("self.narrative.with_someone")
        line = phrase("self.narrative.felt_often", feeling=A.FR[e], whom=whom) if len(values) > 1 else \
            phrase("self.narrative.felt_once", feeling=A.FR[e], whom=whom)
        felt.append(f"- {line}")
    return told, [f for f in felt if f]


@dataclass
class Material:
    """Ce que verrait son prochain récit (ADR 0090) ; ``about`` : de qui viennent ses vécus (l'oubli l'atteint)."""

    told: list[Known] = field(default_factory=list)
    felt: list[str] = field(default_factory=list)
    beliefs: list[str] = field(default_factory=list)
    changes: list[tuple[str, str]] = field(default_factory=list)
    lived: list[tuple[str, str]] = field(default_factory=list)
    knows: list[str] = field(default_factory=list)
    passions: list[str] = field(default_factory=list)
    about: tuple[str, ...] = ()


def whom(frame: Frame, persons: tuple[str, ...]) -> tuple[int, str]:
    """Ce qu'une personne est pour elle, en mots épicènes — jamais qui (son rang : sa propriétaire d'abord)."""
    keys = [frame.get(identity_c.PERSON(p)) or p for p in persons]
    if any(frame.get(identity_c.IS_OWNER(k)) for k in keys):
        return 0, phrase("self.narrative.who.owner")
    ranks = {frame.get(social_c.CLOSENESS(k)) for k in keys}
    if social_c.CLOSE in ranks:
        return 1, phrase("self.narrative.who.close")
    if social_c.FRIEND in ranks:
        return 2, phrase("self.narrative.who.friend")
    return 3, phrase("self.narrative.who.someone")


def gather(frame: Frame, store: Any, s: SelfState, p: SelfParams, *, floor: Audience = PUBLIC_FLOOR) -> Material:
    """La matière de son récit, devant ``floor`` (tout le monde) : rien qu'une audience quelconque ne pourrait
    entendre, rien qui la nomme ni nomme quelqu'un."""
    since = frame.now - p.narrative_lookback_us
    rows = knowns(store.query_mind(
        f"{memory_c.SELECT_KNOWN} WHERE kind=? AND status='active' AND born_at >= ? ORDER BY id DESC LIMIT ?",
        (memory_c.SOUVENIR, since, NARRATIVE_ROWS)), memory_c.KNOWN_COLUMNS)
    cols = ", ".join(memory_c.KNOWN_COLUMNS)
    lived_rows = store.query_mind(f"SELECT {cols}, gist FROM {memory_c.LIVED_VIEW} WHERE born_at >= ? "
                                  "ORDER BY id DESC LIMIT ?", (since, NARRATIVE_ROWS))
    lived_ids = {int(r[0]) for r in lived_rows}
    told, felt = material([k for k in rows if k.id not in lived_ids], frame, p.narrative_max_souvenirs)
    out = Material(told=told, felt=felt)
    resolve, presumed = identity_c.resolvers(frame.get)
    for k in knowns(store.query_mind(
            f"{memory_c.SELECT_KNOWN} WHERE kind=? AND status='active' AND about_self >= 2 ORDER BY touched_at DESC "
            "LIMIT 40", (memory_c.BELIEF,)), memory_c.KNOWN_COLUMNS):
        if len(out.beliefs) < BELIEFS_SHOWN and not k.secret and k.origin != memory_c.LIED \
                and admits(k.lineage, None, floor, resolve=resolve, presumed=presumed).ok:
            out.beliefs.append(k.text)
    changed = store.query_mind(
        f"SELECT was, was_text, item, text, sensitivity, secret FROM {memory_c.SELF_CHANGES_VIEW} WHERE changed_at > ? "
        "ORDER BY changed_at DESC LIMIT ?", (s.narrated_at, CHANGES_SHOWN))
    for was, was_text, item, text, sensitivity, secret in changed:
        both = Lineage(requirements=(requirement(was, (), int(sensitivity), secret=bool(secret)),
                                     requirement(item, (), int(sensitivity), secret=bool(secret))))
        if was_text and text and admits(both, None, floor).ok:
            out.changes.append((str(was_text), str(text)))
    lived: list[tuple[int, str, str, tuple[str, ...]]] = []
    for row in lived_rows:
        (k,) = knowns([row[:-1]], memory_c.KNOWN_COLUMNS)
        gist = str(row[-1] or "")
        if gist and without_whom(k.lineage, LIVED_CEILING):
            rank, word = whom(frame, k.about)
            lived.append((rank, gist, word, k.about))
    lived = sorted(lived, key=lambda r: r[0])[:LIVED_SHOWN]
    out.lived = [(gist, word) for _rank, gist, word, _about in lived]
    out.about = tuple(sorted({a for *_x, about in lived for a in about}))
    out.knows = [KNOWN_LINES[k]() for k in frame.get(c.KNOWS) if k in KNOWN_LINES]
    views = frame.get(c.INTERESTS)
    refs = {i.key: i.label_ref for i in views if not i.line and i.label_ref}
    texts = store.content(list(refs.values())) if refs else {}
    out.passions = passion_lines(views, {k: texts[r] for k, r in refs.items() if texts.get(r)})
    return out


def changes_since(s: SelfState, frame: Frame, p: SelfParams) -> float:
    """Ce qui a changé depuis son dernier récit (ADR 0090) : ses souvenirs (tant valent un), ce qu'elle a dit d'elle
    qui la définit, ses changements d'avis, ce qu'elle a vécu à travers les autres — et, comptant double, ce qu'elle
    sait d'elle et ce qui la passionne."""
    lived = ((s.souvenirs - s.narrated_souvenirs) / max(1, p.narrative_min_souvenirs)
             + (s.self_beliefs - s.narrated_self_beliefs) + (s.changes - s.narrated_changes)
             + (s.lived - s.narrated_lived))
    if not s.narrated_at:
        return lived  # son premier récit attend qu'elle ait vécu quelque chose : sa persona seule ne se raconte pas
    knows = set(frame.get(c.KNOWS))
    interests = {(i.key, i.level) for i in frame.get(c.INTERESTS)}
    moved = {key for key, _level in interests ^ set(s.narrated_interests)}
    return lived + 2 * len(knows ^ set(s.narrated_knows)) + 2 * len(moved)


def known_names(frame: Frame) -> list[str]:
    """Les noms que son récit ne doit pas porter : ceux de son cercle."""
    return [n for n in (frame.get(identity_c.IDENTITY(k)).name for k in frame.get(social_c.CIRCLE) if k) if n]


def prompt_of(m: Material, previous: str | None) -> str:
    lines = [phrase("self.narrative.previous", previous=previous), ""] if previous else []
    if m.beliefs:
        lines += [phrase("self.narrative.beliefs"), *(f"- {b}" for b in m.beliefs), ""]
    if m.changes:
        lines += [phrase("self.narrative.changes"),
                  *(f"- {phrase('self.narrative.change', was=was, now=now)}" for was, now in m.changes), ""]
    if m.passions or m.knows:
        lines += [phrase("self.narrative.knows"), *(f"- {x}" for x in (*m.passions, *m.knows)), ""]
    if m.lived:
        lines += [phrase("self.narrative.lived_through"),
                  *(f"- {phrase('self.narrative.lived_one', gist=gist, whom=word)}" for gist, word in m.lived), ""]
    if m.felt:
        lines += [phrase("self.narrative.felt"), *m.felt, ""]
    lines += [phrase("self.narrative.lived")] + [f"- {k.text}" for k in m.told]
    return "\n".join(lines)


@SELF.process("self.narrate", wake_on=[memory_c.REMEMBERED, memory_c.BELIEVED, memory_c.ATTESTED, c.INTEREST_BORN,
                                       c.REFLECTED, memory_c.PROMISE_RESOLVED, memory_c.RESOLVED],
              lane="background", catch_up=CatchUp.ONCE, max_quantum_s=6 * 3600)
class Narrate:
    def __init__(self) -> None:
        self.retry_at = 0

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("self", frame.root))
        if state.narrative_stale:
            # un souvenir qu'il reprenait a changé : il se réécrit, sans attendre de nouveaux souvenirs (ADR 0082)
            return max(frame.now, state.narrated_at + p.narrative_stale_after_us, self.retry_at)
        if changes_since(state, frame, p) < p.narrative_min_changes:
            return None
        due = state.narrated_at + p.narrative_every_us if state.narrated_at else frame.now
        return max(frame.now, due, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("self", frame.root))
        self.retry_at = frame.now + HOUR  # si l'appel lève : pas de rafale
        m = gather(frame, store, state, p)
        if not (m.told or m.felt or m.beliefs or m.changes or m.lived):
            self.retry_at = frame.now + p.narrative_every_us  # rien de vécu à raconter : pas un récit de rien
            return
        # ce qu'il disait ne se redonne pas à recopier quand une de ses sources a changé (ADR 0082)
        previous = store.content([state.narrative_ref]).get(state.narrative_ref) \
            if state.narrative_ref and not state.narrative_stale else None
        persona = persona_for(frame, "full")
        doc = frame.get(c.PERSONA)
        nature = phrase("self.narrative.nature_ai") if doc.nature != c.EMBODIED else ""
        request = LLMRequest(role="narrative", call_id=f"{ctx.run_id}#0", persona=persona,
                             system_stable="\n\n".join(x for x in (persona.text, phrase("self.narrative.system"), nature)
                                                       if x),
                             messages=(Message("user", prompt_of(m, previous)),), max_tokens=500, lane="background",
                             priority=4)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if not text:
            return
        if mentions(text, known_names(frame)):
            # il est montré à tout le monde : un prénom de son cercle, et il ne s'écrit pas (elle réessaiera demain)
            self.retry_at = frame.now + p.narrative_every_us
            return
        self.retry_at = 0
        await ctx.emit(c.NARRATED.draft(
            text=Content.of(text[:1200], level=0), souvenirs=state.souvenirs, about=m.about,
            sources=tuple(k.id for k in m.told), knows=tuple(frame.get(c.KNOWS)),
            interests=tuple((i.key, i.level) for i in frame.get(c.INTERESTS)),
            voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash, role="narrative",
                                  model=response.model)))


@SELF.enricher("narrative", episodes=CONVERSATIONAL, deadline_ms=300)
async def _narrative_text(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> str | None:
    store = ports.get("store")
    if store is None or not s.narrative_ref or s.narrative_masked:
        return None  # un de ses souvenirs est devenu secret : il se tait jusqu'à sa réécriture
    return store.content([s.narrative_ref]).get(s.narrative_ref)


@SELF.section("narrative", zone=Zone.STABLE, episodes=CONVERSATIONAL, trim_rank=85,
              title=phrase("self.narrative.title"))
def _narrative(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    return enrich.get("narrative")
