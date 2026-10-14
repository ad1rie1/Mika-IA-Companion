"""La relecture de la nuit (ADR 0085) : ce qu'elle a lu devient ce qu'elle sait, et la nuit confronte ses témoins.

Le jour, elle lit (``rss.read``, ``mcp.consulted`` : un article, le chapeau d'un titre, une page consultée en
travaillant) ; la nuit, une fois sa mémoire triée (``memory.night``), elle les relit **en un seul appel au plus** —
aucun s'il n'y a rien — avec ce qu'elle sait déjà qui y touche, ses avis, et les paires de croyances qu'elle tient de
témoins différents sur une même personne. Le modèle propose ; le code juge, avec les règles du socle :

- ce qu'elle a lu devient une croyance dont le témoin est la source (« rss:Le Monde »), anodine, au plus comme un
  témoin qui rapporte (``read``, 0,7) ; la même chose déjà sue en fait un témoignage de plus ; ce qui contredit ce
  qu'elle croyait est jugé (ADR 0081) — une lecture ne remplace pas ce qu'Alice a dit d'elle-même ;
- ce qui arrive dans le monde (``monde``) devient un moment du monde (ADR 0084), une prévision lue une prévision ;
- ses avis à elle, sur tout — politique et science comprises —, formés ou révisés par ce qu'elle a lu (``avis``,
  ``opinions_from_reading`` par nuit) : changer d'avis se ressent (ADR 0081) ;
- une paire jugée « la même chose » se réunit (``memory.joined`` : la rumeur de Bob devient un témoignage de ce
  qu'Alice a dit, et sa discrétion la ferme) ; « contredit », la plus sûre l'emporte ou elle doute
  (``memory.confronted``). Le modèle ne fait que désigner : rien de ce qu'on lui montre d'une paire ne devient un
  texte (une croyance née d'une lecture qui laisse deviner un secret est écartée).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import self_ as self_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory import tables as tb
from mika.faculties.memory.archive import decode
from mika.faculties.memory.consolidation import Consolidate, resolution
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, over, params
from mika.faculties.memory.knowledge import CONTEST, SUPERSEDE, Testimony, judge
from mika.faculties.memory.recall import addresses_her, items_by_id, names_of, query_of, verdict_of
from mika.faculties.memory.salience import Item, age_words
from mika.kernel.clock import DAY, local_date_of_night
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.ports.llm import LLMRequest, Message, ToolDecl
from mika.ports.sql import json_field
from mika.vocab import timespan
from mika.vocab.episodes import Kind
from mika.vocab.people import clean_tokens, read_source
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import fold, stems

log = logging.getLogger("mika.memory.reread")

TOOL_NAME = "record_readings"
#: au plus tant de croyances déjà sues (et d'avis à elle) montrées au modèle
KNOWN_SHOWN, OPINIONS_SHOWN = 15, 8


# ── Ce que le modèle répond ─────────────────────────────────────────────────


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


_TEXT = AliasChoices("texte", "text", "contenu")


class XLu(_Lenient):
    texte: str = Field(min_length=3, max_length=500, validation_alias=_TEXT,
                       description=phrase("memory.reread.fields.texte"))
    lecture: int = Field(description=phrase("memory.reread.fields.lecture"))
    genre: str | None = Field(default=None, description=phrase("memory.reread.fields.genre"))
    quand: str | None = Field(default=None, description=phrase("memory.extraction.fields.prevision_quand"))
    probabilite: str | float | None = Field(default=None, description=phrase("memory.extraction.fields.probabilite"))
    remplace: int | None = Field(default=None, description=phrase("memory.reread.fields.remplace"))


class XMonde(_Lenient):
    texte: str = Field(min_length=3, max_length=300, validation_alias=_TEXT,
                       description=phrase("memory.extraction.fields.event_text"))
    lecture: int = Field(description=phrase("memory.reread.fields.lecture"))
    quand: str = Field(min_length=4, max_length=40, description=phrase("memory.extraction.fields.date"))
    date_officielle: bool = Field(default=False, description=phrase("memory.extraction.fields.date_officielle"))
    probabilite: str | float | None = Field(default=None, description=phrase("memory.extraction.fields.probabilite"))


class XAvis(_Lenient):
    texte: str = Field(min_length=3, max_length=400, validation_alias=_TEXT,
                       description=phrase("memory.reread.fields.avis"))
    remplace: int | None = Field(default=None, description=phrase("memory.reread.fields.avis_remplace"))
    lectures: list[int] = Field(default_factory=list, description=phrase("memory.reread.fields.lectures"))

    @field_validator("lectures", mode="before")
    @classmethod
    def lenient_ints(cls, v: Any) -> list[int]:
        items = v if isinstance(v, list) else [v]
        return [int(i) for i in items if isinstance(i, int) or (isinstance(i, str) and i.strip().isdigit())]


class XLien(_Lenient):
    paire: int = Field(description=phrase("memory.reread.fields.paire"))
    relation: str = Field(description=phrase("memory.reread.fields.relation"))


class XConstatLu(_Lenient):
    moment: int = Field(validation_alias=AliasChoices("moment", "numero", "numéro", "id"),
                        description=phrase("memory.reread.fields.constat_moment"))
    lecture: int = Field(description=phrase("memory.reread.fields.lecture"))
    issue: str = Field(min_length=2, max_length=40, description=phrase("memory.extraction.fields.constat_issue"))


class Relecture(_Lenient):
    croyances: list[XLu] = Field(default_factory=list)
    moments: list[XMonde] = Field(default_factory=list)
    avis: list[XAvis] = Field(default_factory=list)
    liens: list[XLien] = Field(default_factory=list)
    constats: list[XConstatLu] = Field(default_factory=list)

    @field_validator("croyances", "moments", "avis", "liens", "constats", mode="before")
    @classmethod
    def lenient_list(cls, v: Any) -> list[Any]:
        return v if isinstance(v, list) else []


def parse(raw: Mapping[str, Any]) -> Relecture:
    """Ce que le modèle a répondu, élément par élément : un élément illisible est laissé, jamais tout le reste."""
    out = Relecture()
    for key, model in (("croyances", XLu), ("moments", XMonde), ("avis", XAvis), ("liens", XLien),
                       ("constats", XConstatLu)):
        items = raw.get(key) if isinstance(raw.get(key), list) else []
        kept = []
        for item in items:
            try:
                kept.append(model.model_validate(item))
            except ValidationError:
                continue
        setattr(out, key, kept)
    return out


def tool(name: str) -> ToolDecl:
    return ToolDecl(TOOL_NAME, phrase("memory.reread.tool", name=name), Relecture.model_json_schema())


# ── Ce qu'on lui montre ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Lu:
    """Une lecture : son numéro dans le journal, sa source, son titre et son extrait."""

    seq: int
    source: str
    title: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class Paire:
    """Deux croyances sur la même personne, de témoins différents : l'ancienne d'abord."""

    old: int
    new: int
    old_text: str
    new_text: str
    old_by: tuple[str, ...]
    new_by: tuple[str, ...]


def source_label(source: str) -> str:
    """« rss:Le Monde » → « Le Monde » ; « mcp:web » → « web »."""
    return read_source(source) or source


def readings(store: Any, p: MemoryParams) -> tuple[list[Lu], int]:
    """Ses lectures en attente (les plus anciennes d'abord), et jusqu'où elles vont : une lecture dont le texte a été
    oublié depuis est relue sans rien en garder."""
    t = tb.readings()
    rows = store.query_mind(select(t.c.seq, t.c.source, t.c.title_ref, t.c.excerpt_ref).order_by(t.c.seq)
                            .limit(p.reread_max_readings))
    texts = store.content([r for row in rows for r in row[2:] if r])
    return ([Lu(int(seq), str(source), texts.get(title) or "", texts.get(excerpt) or "")
             for seq, source, title, excerpt in rows if texts.get(title)], max((int(r[0]) for r in rows), default=0))


def _persons(frame: Frame, keys: Sequence[str]) -> set[str]:
    """Qui ces clés désignent : une adresse reliée parle pour la personne, un prénom pour celle qu'il désigne
    présumément (ADR 0075) — de quoi confronter, jamais de quoi dire."""
    out = set()
    for k in keys:
        person = frame.get(identity_c.PERSON(k)) or k
        if person.startswith("name:"):
            person = frame.get(identity_c.PRESUMED(person)) or person
        out.add(person)
    return out


async def pairs(frame: Frame, store: Any, vectors: Any, p: MemoryParams) -> list[Paire]:
    """Les paires à confronter : une croyance née depuis ``confront_days`` sur une personne, et ce qu'elle savait
    déjà d'elle — proche par le sens —, de témoins différents (un même témoin qui se corrige, la relecture du jour
    l'a déjà jugé), pas déjà en doute l'une de l'autre."""
    if vectors is None or p.confront_max_pairs <= 0:
        return []
    t, ct = tb.items(), tb.contests()
    rows = store.query_mind(
        select(t.c.id, t.c.text, t.c.about)
        .where(t.c.kind == c.BELIEF, t.c.status == "active", t.c.about_self == 0, t.c.about != "[]",
               t.c.knowledge_kind == "claim", t.c.born_at >= frame.now - round(p.confront_days * DAY))
        .order_by(t.c.id.desc()).limit(40))
    out: list[Paire] = []
    seen: set[tuple[int, int]] = set()
    for item, text, about in rows:
        mine = _persons(frame, _keys(about))
        hits = await vectors.search(str(text), 8, kinds={c.BELIEF}, document=True)
        others = items_by_id(store, [k for k, sim in hits if k != item and sim >= p.recall_floor])
        for other in others.values():
            pair = (min(item, other.id), max(item, other.id))
            if pair in seen or other.status != "active" or other.about_self or other.knowledge_kind != "claim":
                continue
            if not _persons(frame, other.about) & mine:
                continue
            first, second = _told(store, pair[0]), _told(store, pair[1])
            if first & second or store.query_mind(select(ct.c.item).where(ct.c.item == pair[0],
                                                                           ct.c.other == pair[1])):
                continue
            seen.add(pair)
            texts = {int(i): said for i, said in store.query_mind(select(t.c.id, t.c.text)
                                                                  .where(t.c.id.in_(pair)))}
            out.append(Paire(pair[0], pair[1], str(texts.get(pair[0], "")), str(texts.get(pair[1], "")),
                             tuple(sorted(first)), tuple(sorted(second))))
            if len(out) >= p.confront_max_pairs:
                return out
    return out


#: au plus tant de moments du monde montrés à constater, et tranchés « sans nouvelles », par nuit
WORLD_SHOWN, EXPIRED_MAX = 12, 50


def world_moments(frame: Frame, store: Any, state: MemoryState, p: MemoryParams) -> dict[int, tuple[c.LifeEvent, str]]:
    """Les moments du monde dont elle ne sait pas encore comment ils tournent — à venir, ou passés depuis moins de
    ``resolve_days`` —, avec leur texte : une lecture peut dire qu'ils ont eu lieu, sont annulés ou reportés (ADR
    0086). Le monde n'est la vie de personne : rien de confié."""
    t = tb.life()
    rows = store.query_mind(
        select(t.c.payload)
        .where(t.c.yearly == 0, t.c.ongoing == 0, t.c.when_at >= frame.now - round(p.resolve_days * DAY),
               json_field(t.c.payload, "scope") == c.WORLD, func.coalesce(json_field(t.c.payload, "outcome"), "") == "")
        .order_by(t.c.when_at, t.c.id).limit(WORLD_SHOWN))
    found = {ev.id: ev for ev in (decode(raw) for (raw,) in rows)}
    found.update({ev.id: ev for ev in state.events.values() if ev.scope == c.WORLD and not ev.outcome
                  and not ev.yearly and over(ev) >= frame.now - round(p.resolve_days * DAY)})
    chosen = sorted(found.values(), key=lambda ev: (ev.when, ev.id))[:WORLD_SHOWN]
    texts = store.content([ev.text_ref for ev in chosen if ev.text_ref])
    return {ev.id: (ev, texts[ev.text_ref]) for ev in chosen if texts.get(ev.text_ref)}


def expired(frame: Frame, store: Any, p: MemoryParams) -> list[c.LifeEvent]:
    """Les moments passés depuis plus de ``resolve_grace_days`` sans que personne ne dise comment ils ont tourné :
    elle ne le saura pas (ADR 0086) — sur deux mois au plus, ce qui est plus ancien n'attend plus rien."""
    until = frame.now - round(p.resolve_grace_days * DAY)
    t = tb.life()
    rows = store.query_mind(
        select(t.c.payload)
        .where(t.c.yearly == 0, t.c.ongoing == 0, t.c.when_at < until, t.c.when_at >= until - 60 * DAY,
               func.coalesce(json_field(t.c.payload, "outcome"), "") == "")
        .order_by(t.c.when_at, t.c.id).limit(EXPIRED_MAX))
    return [decode(raw) for (raw,) in rows]


def _keys(raw: Any) -> list[str]:
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(k) for k in got] if isinstance(got, list) else []


def _told(store: Any, item: int) -> set[str]:
    """Qui le lui a dit : les témoins de tous ses témoignages."""
    tt = tb.testimonies()
    return {k for (told,) in store.query_mind(select(tt.c.told_by).where(tt.c.item == item)) for k in _keys(told)}


async def _known(store: Any, vectors: Any, lus: Sequence[Lu], *, mine: bool) -> list[tuple[int, str]]:
    """Ce qu'elle sait déjà qui touche ses lectures (anodin, jamais un secret — le modèle pourrait le recopier), ou
    ses avis à elle (``mine``)."""
    if vectors is None or not lus:
        return []
    found: dict[int, float] = {}
    for lu in lus:
        for k, sim in await vectors.search(f"{lu.title} {lu.excerpt[:300]}", 6, kinds={c.BELIEF}):
            found[k] = max(sim, found.get(k, 0.0))
    items = items_by_id(store, sorted(found))
    chosen = [it for it in items.values() if it.status == "active" and not it.secret and (
        it.durable_self if mine else (not it.about_self and it.sensitivity <= Sensitivity.ANODYNE))]
    chosen.sort(key=lambda it: (-found[it.id], it.id))
    return [(it.id, it.text) for it in chosen[:OPINIONS_SHOWN if mine else KNOWN_SHOWN]]


def render(frame: Frame, lus: Sequence[Lu], known: Sequence[tuple[int, str]], opinions: Sequence[tuple[int, str]],
           paires: Sequence[Paire], names: Mapping[str, str],
           world: Mapping[int, tuple[c.LifeEvent, str]] | None = None) -> str:
    out = [phrase("memory.extraction.render.today", day=x.day_words(frame.local().date()), year=frame.local().year,
                  hour=f"{frame.local():%H}", minute=f"{frame.local():%M}")]
    if lus:
        out += ["", phrase("memory.reread.render.readings")]
        for n, lu in enumerate(lus, start=1):
            out.append(phrase("memory.reread.render.reading", n=n, source=source_label(lu.source), title=lu.title))
            if lu.excerpt.strip():
                out.append(phrase("memory.reread.render.excerpt", excerpt=" ".join(lu.excerpt.split())))
    if known:
        out += ["", phrase("memory.reread.render.known")] + [f"[#{i}] {t}" for i, t in known]
    if opinions:
        out += ["", phrase("memory.reread.render.opinions")] + [f"[#{i}] {t}" for i, t in opinions]
    if world and lus:
        out += ["", phrase("memory.reread.render.world")]
        out += [phrase("memory.reread.render.world_moment", id=i, when=frame.local(ev.when).date().isoformat(),
                       text=text) for i, (ev, text) in world.items()]
    if paires:
        out += ["", phrase("memory.reread.render.pairs")]

        def by(keys: Sequence[str]) -> str:
            return ", ".join(names.get(k, k) for k in keys) or phrase("memory.reread.someone")

        out += [phrase("memory.reread.render.pair", n=n, old=pr.old_text, old_by=by(pr.old_by), new=pr.new_text,
                       new_by=by(pr.new_by)) for n, pr in enumerate(paires, start=1)]
    return "\n".join(out)


# ── Ce qu'elle en garde ─────────────────────────────────────────────────────


def grounded(text: str, lu: Lu) -> bool:
    """Ce que le modèle dit avoir lu là y est : au moins un mot de sujet en commun avec la lecture (un fait sorti de
    nulle part, ou d'une autre ligne du prompt, n'est pas une lecture)."""
    return bool(stems(text) & stems(f"{lu.title} {lu.excerpt}"))


async def drafts_of(rel: Relecture, frame: Frame, state: MemoryState, store: Any, vectors: Any, p: MemoryParams,
                    lus: Sequence[Lu], known: Sequence[tuple[int, str]], opinions: Sequence[tuple[int, str]],
                    paires: Sequence[Paire], night: str, call_id: str,
                    world: Mapping[int, tuple[c.LifeEvent, str]] | None = None) -> list[Draft[Any]]:
    """Ce que la nuit garde de ce que le modèle a proposé, jugé par le code (voir le module)."""
    tz = frame.env.tz_of(frame.root)
    consolidate = Consolidate()
    by_n = dict(enumerate(lus, start=1))
    known_ids, opinion_ids = {i for i, _ in known}, {i for i, _ in opinions}
    # ce qu'on a montré d'une paire ne devient jamais le texte d'une lecture (un secret ne se blanchit pas)
    shown = [t for pr in paires for t in (pr.old_text, pr.new_text)]
    out: list[Draft[Any]] = []
    born = 0
    for b in rel.croyances:
        lu = by_n.get(b.lecture)
        if lu is None or born >= p.reread_max_items or not grounded(b.texte, lu) or x.echoes(b.texte, shown, set()):
            continue
        born += 1
        source, nature = lu.source, "prediction" if fold(b.genre or "").startswith("prev") else "claim"
        twin = await consolidate._twin(store, vectors, b.texte, c.BELIEF, (), p, told_by=(source,),
                                       knowledge_kind=nature, holder=source if nature == "prediction" else None)
        confidence = x.born_confidence(0.7, c.READ, nature)
        if twin is not None:
            out.append(c.ATTESTED.draft(item=twin, told_by=(source,), heard_by=(), source=source, origin=c.READ,
                                        confidence=confidence, sensitivity=int(Sensitivity.ANODYNE),
                                        sources=(lu.seq,), call_id=call_id))
            continue
        target = Consolidate._target_of(store, b.remplace if b.remplace in known_ids else None, nature, None)
        verdict = judge(Consolidate._testimonies(store, target), Testimony(0, (source,), (), 0, False, 0.0,
                                                                          origin=c.READ)) if target else None
        span = timespan.parse(b.quand, tz) if b.quand else None
        predicted = dict(expected=span.point, expected_until=span.end if span.vague else None,
                         expected_precision=span.precision, valid_until=span.end) \
            if nature == "prediction" and span is not None else {}
        out.append(c.BELIEVED.draft(
            text=Content.of(b.texte, level=int(Sensitivity.ANODYNE)), about=(), sensitivity=int(Sensitivity.ANODYNE),
            importance=x.IMPORTANCE[2], confidence=confidence, origin=c.READ, source=source,
            replaces=target if verdict == SUPERSEDE else None, contests=target if verdict == CONTEST else None,
            sources=(lu.seq,), call_id=call_id, told_by=(source,), heard_by=(), knowledge_kind=nature,
            holder=source if nature == "prediction" else None,
            likelihood=lk.likelihood(lk.PREDICTION, b.probabilite, p) if nature == "prediction" else None,
            **predicted))
    noted = [ev for ev in state.events.values() if ev.scope == c.WORLD and ev.text_ref]
    world_texts = store.content([ev.text_ref for ev in noted]) if noted else {}
    for m in rel.moments:
        lu, span = by_n.get(m.lecture), timespan.parse(m.quand, tz)
        if lu is None or span is None or span.end < frame.now or born >= p.reread_max_items \
                or not grounded(m.texte, lu) or x.echoes(m.texte, shown, set()):
            continue
        if any(ev.when <= span.end and span.start <= ev.ends and x.same_moment(m.texte, world_texts.get(ev.text_ref)
                                                                           or "", []) for ev in noted):
            continue  # déjà vu venir
        born += 1
        out.append(c.EVENT_NOTED.draft(
            text=Content.of(m.texte, level=int(Sensitivity.ANODYNE)), when=span.point, about=(),
            all_day=span.all_day, sensitivity=int(Sensitivity.ANODYNE), sources=(lu.seq,), told_by=(lu.source,),
            heard_by=(), call_id=call_id, until=span.end if span.vague else None, precision=span.precision,
            scope=c.WORLD, official=m.date_officielle,
            likelihood=lk.likelihood(lk.OFFICIAL if m.date_officielle else lk.REPORTED, m.probabilite, p)))
    for a in [a for a in rel.avis if not x.echoes(a.texte, shown, set())][:p.opinions_from_reading]:
        if await consolidate._twin(store, vectors, a.texte, c.BELIEF, (), p, knowledge_kind="opinion",
                                   about_self=True) is not None:
            continue  # elle le pense déjà
        target = Consolidate._target_of(store, a.remplace if a.remplace in opinion_ids else None, "opinion", None,
                                        about_self=True)
        out.append(c.BELIEVED.draft(
            text=Content.of(a.texte, level=int(Sensitivity.ANODYNE)), about=(), sensitivity=int(Sensitivity.ANODYNE),
            importance=x.IMPORTANCE[3], confidence=x.born_confidence(0.9, c.OBSERVED, "opinion"), origin=c.OBSERVED,
            sources=tuple(by_n[n].seq for n in a.lectures if n in by_n) or tuple(lu.seq for lu in lus),
            call_id=call_id, about_self=True, durable=True,
            knowledge_kind="opinion", replaces=target))
    joined: list[tuple[int, int]] = []
    supersedes: list[tuple[int, int]] = []
    contests: list[tuple[int, int]] = []
    touched: set[int] = set()
    by_pair = dict(enumerate(paires, start=1))
    for link in rel.liens:
        pr = by_pair.get(link.paire)
        relation = fold(link.relation)
        if pr is None or {pr.old, pr.new} & touched:
            continue
        if relation.startswith(("meme", "same", "identique")):
            joined.append((pr.old, pr.new))  # la plus ancienne garde ; l'autre devient un de ses témoignages
        elif relation.startswith(("contred", "contra")):
            newest = Consolidate._testimonies(store, pr.new)
            said = max(newest, key=lambda t: t.seq) if newest else None
            if said is None:
                continue
            if judge(Consolidate._testimonies(store, pr.old), said) == SUPERSEDE:
                supersedes.append((pr.new, pr.old))
            else:
                contests.append((pr.old, pr.new))
        else:
            continue
        touched |= {pr.old, pr.new}
    done: set[int] = set()
    for k in rel.constats:
        lu, got, outcome = by_n.get(k.lecture), (world or {}).get(k.moment), x.outcome_of(k.issue)
        if lu is None or got is None or outcome is None or got[0].id in done:
            continue
        ev, text = got
        if not x.echoes(text, [f"{lu.title} {lu.excerpt}"], set()):
            continue  # la lecture doit parler de ce moment-là (des mots du sujet en commun)
        done.add(ev.id)
        out.append(resolution(ev, outcome, lu.source, (lu.seq,), call_id))
    if joined:
        # d'autres mots, jugés la même chose : ses témoins comptent, sans parler pour les mots de la gardée
        out.append(c.JOINED.draft(night=night, pairs=tuple(joined), mute=True, dedupe_key=f"confrontee:{night}"))
    if supersedes or contests:
        out.append(c.CONFRONTED.draft(night=night, supersedes=tuple(supersedes), contests=tuple(contests),
                                      dedupe_key=f"confrontation:{night}"))
    return out


# ── La nuit ─────────────────────────────────────────────────────────────────


@MEMORY.process("memory.reread", wake_on=[*body_c.ALL, c.NIGHT_SORTED], lane="night", catch_up=CatchUp.ONCE,
                max_quantum_s=3600)
class Reread:
    """Une relecture par nuit, après le tri de la mémoire : un appel au plus, aucun sans rien à relire."""

    def __init__(self) -> None:
        self.failed: str = ""  # une nuit dont l'appel a échoué : elle réessaiera la suivante

    def _night(self, state: MemoryState, frame: Frame) -> str | None:
        since = frame.get(body_c.ASLEEP_SINCE)
        if not since:
            return None
        night = local_date_of_night(since, frame.env.tz_of(frame.root), 5).isoformat()
        if night in (state.reread_night, self.failed) or state.sorted_night != night:
            return None
        return night

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if self._night(state, frame) is not None else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        night = self._night(state, frame)
        store, vectors = ctx.ports.get("store"), ctx.ports.get("vectors")
        if night is None or store is None:
            return
        p = params(frame.env.params_of("memory", frame.root))
        lus, upto = readings(store, p)
        paires = await pairs(frame, store, vectors, p)
        # ce qui est passé depuis longtemps sans nouvelles : elle ne saura pas (aucun appel)
        gone = [resolution(ev, c.UNKNOWN, "", (), f"{ctx.run_id}#expiré") for ev in expired(frame, store, p)]
        if not lus and not paires:
            await ctx.emit(*gone, c.REREAD.draft(night=night, upto=upto, dedupe_key=f"relecture:{night}"))
            return
        world = world_moments(frame, store, state, p) if lus else {}
        known = await _known(store, vectors, lus, mine=False)
        opinions = await _known(store, vectors, lus, mine=True) if p.opinions_from_reading else []
        her = self_c.name_of(frame.get(self_c.PERSONA))
        tellers = {k for pr in paires for k in (*pr.old_by, *pr.new_by)}
        names = names_of(frame, tellers)
        prompt = render(frame, lus, known, opinions, paires, names, world)
        call_id = f"{ctx.run_id}#0"
        request = LLMRequest(role="extract", call_id=call_id, system_stable=phrase("memory.reread.system", name=her,
                                                                                    opinions=p.opinions_from_reading),
                             messages=(Message("user", prompt),), tools=(tool(her),), max_tokens=x.MAX_OUTPUT_TOKENS,
                             lane="background", priority=3, meta={"night": night})
        try:
            response = await ctx.llm.call(request)
        except Exception as exc:  # noqa: BLE001 — une nuit manquée : la suivante relira
            log.warning("relecture de la nuit %s : %s", night, type(exc).__name__)
            self.failed = night
            if gone:
                await ctx.emit(*gone)
            return
        raw = next((dict(call.args) for call in response.tool_calls if call.name == TOOL_NAME), {})
        rel = parse(raw)
        drafts = gone + await drafts_of(rel, frame, state, store, vectors, p, lus, known, opinions, paires, night,
                                        call_id, world)
        drafts.append(c.REREAD.draft(night=night, upto=upto, readings=len(lus), pairs=len(paires), call_id=call_id,
                                     model=response.model, dedupe_key=f"relecture:{night}"))
        await ctx.emit(*drafts)


# ── Ce qu'elle a appris en lisant ───────────────────────────────────────────

#: au plus tant de lectures retenues montrées
LEARNED_SHOWN = 4
#: quand elle écrit d'elle-même, travaille, ou qu'on lui parle d'elle (« t'as lu des trucs ? ») ; sinon, en réponse,
#: ce qu'elle a lu revient par le rappel, s'il y touche
LEARNED_EPISODES = (Kind.INITIATIVE, Kind.REPLY, Kind.STEP, Kind.WORK)


@dataclass(frozen=True, slots=True)
class Learned:
    item: Item
    source: str
    at: int
    level: int


@MEMORY.enricher("learned", episodes=LEARNED_EPISODES, deadline_ms=500,
                 reads=[identity_c.PERSON, identity_c.PRESUMED, identity_c.IDENTITY, identity_c.HANDLES])
async def _learned(s: MemoryState, frame: Frame, ports: Mapping[str, Any]) -> list[Learned] | None:
    """Ce qu'elle a lu ces derniers jours et retenu (une croyance qui tient d'une lecture), pas encore raconté à qui
    elle s'adresse, et que cette audience peut entendre ; sans personne en face, ce qui est anodin."""
    store, ep, aud = ports.get("store"), frame.episode, frame.audience
    if store is None or ep is None:
        return None
    if ep.kind == Kind.REPLY and not addresses_her(query_of(frame, store)):
        return None  # « salut » ne lui fait pas réciter ses lectures ; « et toi, quoi de neuf ? », si
    p = params(frame.env.params_of("memory", frame.root))
    since = frame.now - round(p.learned_fresh_days * DAY)
    # le dernier témoignage de chaque élément appris d'une lecture, ``told_by`` compris : une fenêtre, jamais une
    # colonne nue à côté d'un ``MAX`` (SQLite y met la ligne du maximum, MariaDB une ligne quelconque)
    tt = tb.testimonies()
    last = (select(tt.c.item, tt.c.told_by, tt.c.at,
                   func.row_number().over(partition_by=tt.c.item, order_by=(tt.c.at.desc(), tt.c.seq.desc()))
                   .label("nth"))
            .where(tt.c.origin == c.READ, tt.c.at >= since).subquery("last"))
    rows = store.query_mind(select(last.c.item, last.c.told_by, last.c.at).where(last.c.nth == 1)
                            .order_by(last.c.at.desc(), last.c.item).limit(40))
    if not rows:
        return None
    read = {int(i): (_keys(told), int(at)) for i, told, at in rows}
    person = frame.get(identity_c.PERSON(ep.target)) if ep.target else None
    told: set[int] = set()
    if person:
        handles = sorted({ep.target, person, *frame.get(identity_c.HANDLES(person))})
        said = tb.told()
        told = {int(i) for (i,) in store.query_mind(
            select(said.c.item).where(said.c.handle.in_(sorted({tb.handle_key(h) for h in handles}))))}
    memo: dict[str, str] = {}
    out: list[Learned] = []
    for item in sorted(items_by_id(store, sorted(read)).values(), key=lambda it: (-it.importance, -read[it.id][1])):
        if item.kind != c.BELIEF or item.status != "active" or item.about_self or item.id in told \
                or (item.valid_until is not None and item.valid_until < frame.now):
            continue
        if person and aud is not None:
            verdict = verdict_of(frame, item, person, aud, memo, store)
            if not verdict.ok:
                continue
            level = verdict.level
        elif item.secret or item.sensitivity > Sensitivity.ANODYNE:
            continue  # personne en face : ce qui est anodin seulement
        else:
            level = item.sensitivity
        tellers, at = read[item.id]
        out.append(Learned(item, next((source_label(k) for k in tellers), ""), at, level))
        if len(out) >= LEARNED_SHOWN:
            break
    return out or None


@MEMORY.section("learned", zone=Zone.VOLATILE, episodes=LEARNED_EPISODES, trim_rank=40,
                title=phrase("memory.learned.title"))
def _learned_section(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« CE QUE TU AS APPRIS EN LISANT » : de quoi dire « j'ai lu que… » — une fois par personne (ce qu'elle en a
    raconté est noté, ``memory_told``)."""
    got: list[Learned] | None = enrich.get("learned")
    if not got:
        return None
    lines = [phrase("memory.learned.line", text=clean_tokens(lr.item.text), source=lr.source,
                    age=age_words(lr.at, frame.now)) for lr in got]
    lines.append(phrase("memory.learned.advice"))
    return SectionBody("\n".join(lines), level=max(lr.level for lr in got),
                       provenance=tuple(f"memory:{lr.item.id}" for lr in got))


__all__ = ["Learned", "Lu", "Paire", "Relecture", "Reread", "drafts_of", "pairs", "parse", "readings", "render",
           "source_label"]
