"""Ce qui la passionne (ADR 0089) : ses centres d'intérêt vivent.

Ceux de sa persona ne disparaissent jamais : ils s'avivent quand elle les explore ou que ses flux en parlent, et
s'endorment quand rien ne les nourrit. D'autres naissent de ce qu'elle vit — ce qu'elle lit, ce qu'elle trouve en
explorant, ce qu'on lui raconte et qu'elle médite : ce sont des pistes, et la nuit, quand assez de pistes neuves
reviennent sur plusieurs jours, elle se demande (le modèle juge, le code borne) si un sujet est en train de la
passionner. Un seul par nuit, pas plus d'un par semaine, trois vécus au plus ; un sujet qui nommerait quelqu'un, ou
qui ne se dirait pas à tout le monde, ne naît pas. Un intérêt vécu qui s'éteint s'en va ; l'oubli d'une personne
emporte les pistes et les intérêts nés d'elle. Une confidence n'est jamais une piste.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import rss as rss_c
from mika.contracts import self_ as c
from mika.contracts import social as social_c
from mika.faculties.self.faculty import SELF, SelfState, day_of, lived_day_of
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.records import Interest, Lead
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message, ToolDecl
from mika.vocab import interests as v
from mika.vocab.people import mentions
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

log = logging.getLogger(__name__)

#: les pistes gardées au plus
LEADS_KEPT = 40
#: les sortes de pistes
TALK, READING, FOUND = "talk", "reading", "found"
#: la source d'une exploration née d'un centre d'intérêt (``goals``), et celle d'un intérêt vécu
INTEREST_SOURCE = "interest:"
LIVED_PREFIX = "lived:"
#: ce qu'un sujet né peut faire de mots, de caractères ; ce qu'elle en dit
SUBJECT_WORDS, SUBJECT_CHARS, DETAIL_CHARS = 8, 60, 240
TOOL_NAME = "record_interests"


# ── La vivacité ───────────────────────────────────────────────────────────


def glow(i: Interest, now: int, p: SelfParams) -> float:
    """Sa vivacité maintenant : elle retombe vers son plancher (celui de la persona : jamais rien), de moitié en une
    demi-vie."""
    floor = p.persona_floor if i.origin == v.PERSONA else 0.0
    return floor + (i.glow - floor) * 0.5 ** (max(0, now - i.glow_at) / p.interest_half_life_us)


def level(value: float, p: SelfParams) -> str:
    return v.VIVID if value >= p.vivid_from else (v.ASLEEP if value < p.asleep_below else v.PRESENT)


def alive(i: Interest, now: int, p: SelfParams) -> bool:
    """Un intérêt de sa persona l'est toujours ; un intérêt vécu, tant qu'il ne s'est pas éteint."""
    return i.origin == v.PERSONA or glow(i, now, p) >= p.lived_drop_below


def _feed(s: SelfState, key: str, amount: float, at: int, p: SelfParams) -> SelfState:
    i = s.interests.get(key)
    if i is None or amount <= 0:
        return s
    fed = replace(i, glow=round(min(1.0, glow(i, at, p) + amount), 6), glow_at=at, fed_at=at, feeds=i.feeds + 1)
    return replace(s, interests=s.interests.set(key, fed))


def _lead(s: SelfState, lead: Lead) -> SelfState:
    if lead.sensitivity >= Sensitivity.CONFIDENCE or not lead.ref:
        return s  # une confidence n'est jamais une piste
    if lead.key and any(other.key == lead.key for other in s.leads):
        return s  # le même article relu (une page qui ne charge pas, rouverte) : une piste, pas quatre
    return replace(s, leads=(*s.leads, lead)[-LEADS_KEPT:])


def key_of_source(source: str) -> str | None:
    """La clé d'intérêt d'une exploration (``interest:<ligne>``, ``interest:lived:<nuit>``)."""
    return source[len(INTEREST_SOURCE):] if source.startswith(INTEREST_SOURCE) else None


# ── Ce qui les nourrit ────────────────────────────────────────────────────


@SELF.reducer(c.PERSONA_REVISED)
def _persona_interests(s: SelfState, e, cx) -> SelfState:
    """Les centres d'intérêt de sa persona : un nouveau s'allume, un retiré par l'opératrice s'en va ; les autres
    gardent ce qu'elle en a vécu."""
    p = params(cx.params)
    lines = tuple(dict.fromkeys(e.data.persona.interests))
    interests = FrozenDict((k, i) for k, i in s.interests.items() if i.origin != v.PERSONA or k in lines)
    for line in lines:
        if line not in interests:
            interests = interests.set(line, Interest(line, v.PERSONA, line=line, born_at=e.at, glow=p.persona_glow,
                                                     glow_at=e.at))
    return replace(s, interests=interests)


@SELF.reducer(goals_c.GOAL_CLOSED)
def _explored(s: SelfState, e, cx) -> SelfState:
    """Explorer un centre d'intérêt l'avive (une rêverie aussi : elle y a pensé) ; ce qu'elle y a trouvé, ce qu'elle
    a médité de ce qu'on lui a raconté, deviennent des pistes."""
    d, p = e.data, params(cx.params)
    if d.status != goals_c.ACHIEVED:
        return s
    key = key_of_source(d.source)
    if key is not None:
        s = _feed(s, key, p.explored_feed, e.at, p)
    if d.result is None or not d.result.ref:
        return s
    kind = TALK if d.source.startswith("talk:") else (FOUND if key is not None or d.kind == goals_c.EXPLORATION
                                                     else None)
    if kind is None:
        return s
    return _lead(s, Lead(e.seq, e.at, kind, d.result.ref, tuple(d.about or ((d.owner,) if d.owner else ())),
                         int(d.sensitivity), key=f"goal:{d.goal}"))


@SELF.reducer(rss_c.NOTICED, reads=[body_c.RHYTHM])
def _noticed(s: SelfState, e, cx) -> SelfState:
    """Ce qu'elle remarque dans ses flux nourrit les intérêts qu'il touche — un peu, et pas plus que tant par
    journée : quarante titres sur le même sujet ne font pas une passion."""
    p = params(cx.params)
    day = day_of(cx, e.at)
    for key in e.data.touches:
        i = s.interests.get(key)
        if i is None:
            continue
        so_far = i.touched if i.touched_day == day else 0.0
        amount = max(0.0, min(p.touch_feed, p.touch_daily_cap - so_far))
        s = _feed(s, key, amount, e.at, p)
        if key in s.interests:
            fed = s.interests[key]
            s = replace(s, interests=s.interests.set(key, replace(fed, touched_day=day,
                                                                   touched=round(so_far + amount, 6))))
    return s


@SELF.reducer(rss_c.READ)
def _read(s: SelfState, e, cx) -> SelfState:
    """Un article qu'elle a ouvert est une piste (un titre survolé, non)."""
    d = e.data
    if d.depth == "headline" or not d.title.ref:
        return s
    return _lead(s, Lead(e.seq, e.at, READING, d.title.ref, key=f"{d.source}|{d.ref}" if d.ref else ""))


@SELF.reducer(c.INTEREST_BORN)
def _born(s: SelfState, e, cx) -> SelfState:
    p, d = params(cx.params), e.data
    key = f"{LIVED_PREFIX}{d.night}"
    born = Interest(key, v.LIVED, label_ref=d.label.ref or "", detail_ref=d.detail.ref or "" if d.detail else "",
                    about=tuple(d.about), born_at=e.at, glow=p.born_glow, glow_at=e.at, fed_at=e.at)
    return replace(s, interests=s.interests.set(key, born), last_birth_at=e.at)


@SELF.reducer(c.REFLECTED)
def _reflected(s: SelfState, e, cx) -> SelfState:
    """La nuit a relu ses pistes : celles rattachées nourrissent leur intérêt et s'en vont ; un intérêt vécu éteint
    s'en va ; les pistes trop vieilles aussi."""
    p, d = params(cx.params), e.data
    waiting = {lead.seq for lead in s.leads}
    used: set[int] = set()
    for seq, key in d.attached:
        if seq in waiting and seq not in used:
            s = _feed(s, key, p.lead_feed, e.at, p)  # une piste ne nourrit qu'une fois : rattachée, elle s'en va
            used.add(seq)
    leads = tuple(lead for lead in s.leads if lead.seq not in used and lead.at >= e.at - p.lead_keep_us)
    interests = FrozenDict((k, i) for k, i in s.interests.items() if alive(i, e.at, p))
    return replace(s, leads=leads, interests=interests, reflected_night=d.night,
                   reflected_upto=max(s.reflected_upto, d.upto))


@SELF.reducer(SUBJECT_FORGOTTEN)
def _forgotten(s: SelfState, e, cx) -> SelfState:
    """Oublier quelqu'un emporte les pistes venues de lui, et les intérêts nés d'elles."""
    person = e.data.subject
    return replace(s, leads=tuple(lead for lead in s.leads if person not in lead.about),
                   interests=FrozenDict((k, i) for k, i in s.interests.items() if person not in i.about))


@SELF.fact(c.INTERESTS)
def _interests(s: SelfState, cx) -> tuple[v.InterestView, ...]:
    p = params(cx.params)
    live = [(glow(i, cx.now, p), i) for i in s.interests.values() if alive(i, cx.now, p)]
    return tuple(v.InterestView(i.key, i.origin, level(g, p), i.line, i.label_ref, i.detail_ref, i.about, i.born_at)
                 for g, i in sorted(live, key=lambda gi: (-gi[0], gi[1].key)))


# ── La nuit, ce qui est en train de la passionner ─────────────────────────


class XRattache(BaseModel):
    model_config = ConfigDict(extra="ignore")
    piste: int
    interet: int


class XNaissance(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sujet: str = Field(description=phrase("self.reflect.fields.sujet"))
    detail: str = Field(default="", description=phrase("self.reflect.fields.detail"))
    preuves: list[int] = Field(default_factory=list, description=phrase("self.reflect.fields.preuves"))
    dicible: bool = Field(default=False, description=phrase("self.reflect.fields.dicible"))

    @field_validator("preuves", mode="before")
    @classmethod
    def lenient(cls, value: Any) -> list[int]:
        items = value if isinstance(value, list) else []
        return [int(x) for x in items if isinstance(x, int) or (isinstance(x, str) and x.strip().isdigit())]


class Reflet(BaseModel):
    rattachements: list[XRattache] = Field(default_factory=list,
                                           description=phrase("self.reflect.fields.rattachements"))
    naissances: list[XNaissance] = Field(default_factory=list, description=phrase("self.reflect.fields.naissances"))


def parse(raw: Mapping[str, Any]) -> Reflet:
    """Ce que le modèle a répondu, élément par élément : un élément illisible est laissé, jamais le reste."""
    out = Reflet()
    for name, model in (("rattachements", XRattache), ("naissances", XNaissance)):
        items = raw.get(name) if isinstance(raw.get(name), list) else []
        kept = []
        for item in items:
            try:
                kept.append(model.model_validate(item))
            except (ValidationError, TypeError, ValueError):
                continue
        setattr(out, name, kept)
    return out


def fresh_leads(s: SelfState) -> list[Lead]:
    return [lead for lead in s.leads if lead.seq > s.reflected_upto]


def ripe(s: SelfState, frame: Frame, p: SelfParams) -> bool:
    """Assez de pistes neuves, sur assez de journées, pour qu'un sujet ait pu revenir."""
    leads = fresh_leads(s)
    return len(leads) >= p.birth_min_leads and \
        len({lived_day_of(frame, lead.at) for lead in leads}) >= p.birth_min_days


def known_names(frame: Frame, leads: Sequence[Lead]) -> list[str]:
    """Les noms qu'un sujet ne doit pas porter : ceux de son cercle et de qui viennent les pistes."""
    keys = {*frame.get(social_c.CIRCLE), *(a for lead in leads for a in lead.about)}
    return [n for n in (frame.get(identity_c.IDENTITY(k)).name for k in keys if k) if n]


def refusal(b: XNaissance, frame: Frame, p: SelfParams, shown: Mapping[int, Lead], labels: Sequence[str],
            names: Sequence[str]) -> str:
    """Pourquoi le code refuse cette naissance (un code, gardé au journal technique) — vide : il l'accepte. Un sujet
    court, dicible à tous, qui ne nomme personne, qui n'est pas déjà un de ses intérêts, avec des preuves sur assez de
    journées."""
    subject = " ".join(b.sujet.split()).strip(" .")
    evidence = {shown[n] for n in b.preuves if n in shown}
    if not b.dicible:
        return "indicible"
    if not subject or len(subject) > SUBJECT_CHARS or len(subject.split()) > SUBJECT_WORDS:
        return "sujet-trop-long"
    if mentions(subject, names) or mentions(b.detail, names):
        return "nomme-quelqu-un"
    if any(v.same_topic(subject, label) for label in labels):
        return "deja-un-interet"
    if len(evidence) < 2 or len({lived_day_of(frame, lead.at) for lead in evidence}) < p.birth_min_days:
        return "preuves-insuffisantes"
    return ""


def accepted(births: Sequence[XNaissance], s: SelfState, frame: Frame, p: SelfParams, shown: Mapping[int, Lead],
             labels: Sequence[str], refused: list[str] | None = None) -> tuple[XNaissance, tuple[Lead, ...]] | None:
    """La naissance que le code accepte, s'il en accepte une : pas plus d'une par semaine ni plus de tant d'intérêts
    vécus, et la première que ``refusal`` laisse passer. ``refused`` : pourquoi les autres ne sont pas nées."""
    reasons = refused if refused is not None else []
    if births and s.last_birth_at and frame.now - s.last_birth_at < p.birth_every_us:
        reasons.append("trop-tot")
        return None
    if births and sum(1 for i in s.interests.values() if i.origin == v.LIVED and alive(i, frame.now, p)) \
            >= p.lived_max:
        reasons.append("assez-de-vecus")
        return None
    names = known_names(frame, list(shown.values()))
    for b in births:
        why = refusal(b, frame, p, shown, labels, names)
        if why:
            reasons.append(why)
            continue
        evidence = tuple(dict.fromkeys(shown[n] for n in b.preuves if n in shown))
        return b.model_copy(update={"sujet": " ".join(b.sujet.split()).strip(" .")}), evidence
    return None


#: les sortes de pistes, dites à la réflexion
KINDS = {TALK: lambda: phrase("self.reflect.kinds.talk"), READING: lambda: phrase("self.reflect.kinds.reading"),
         FOUND: lambda: phrase("self.reflect.kinds.found")}


def tool() -> ToolDecl:
    return ToolDecl(TOOL_NAME, phrase("self.reflect.tool"), Reflet.model_json_schema())


@SELF.process("self.reflect", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Reflect:
    """Une réflexion par nuit au plus, et aucune sans assez de pistes neuves sur assez de journées."""

    def __init__(self) -> None:
        self.failed = ""  # une nuit dont l'appel a échoué : la suivante réessaiera

    def _night(self, state: SelfState, frame: Frame) -> str | None:
        since = frame.get(body_c.ASLEEP_SINCE)
        if not since:
            return None
        night = lived_day_of(frame, since)
        if night in (state.reflected_night, self.failed):
            return None
        return night if ripe(state, frame, params(frame.env.params_of("self", frame.root))) else None

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if self._night(state, frame) is not None else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        night = self._night(state, frame)
        store = ctx.ports.get("store")
        if night is None or store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("self", frame.root))
        # assez de pistes neuves la font réfléchir ; elle relit alors toutes celles qui ne se sont encore rattachées à
        # rien : un sujet qui revient sur plusieurs semaines peut naître aussi
        leads = list(state.leads)
        views = list(frame.get(c.INTERESTS))
        texts = store.content([r for r in (*(lead.ref for lead in leads), *(i.label_ref for i in views)) if r])
        shown = {n: lead for n, lead in enumerate((ld for ld in leads if texts.get(ld.ref)), start=1)}
        labels = [i.line and v.subject_of(i.line) or texts.get(i.label_ref) or "" for i in views]
        numbered = dict(enumerate(views, start=1))
        lines = [phrase("self.reflect.interest", n=n, subject=labels[n - 1]) for n in numbered if labels[n - 1]]
        lines += [phrase("self.reflect.lead", n=n, day=lived_day_of(frame, lead.at), kind=KINDS[lead.kind](),
                         text=texts[lead.ref][:400])
                  for n, lead in shown.items() if lead.kind in KINDS]
        call_id = f"{ctx.run_id}#0"
        her = c.name_of(frame.get(c.PERSONA))
        span = phrase("self.reflect.span_days", days=p.birth_min_days) if p.birth_min_days > 1 else ""
        request = LLMRequest(role="extract", call_id=call_id,
                             system_stable=phrase("self.reflect.system", name=her, span=span),
                             messages=(Message("user", "\n".join(lines)),), tools=(tool(),), max_tokens=1500,
                             lane="background", priority=4, meta={"night": night})
        try:
            response = await ctx.llm.call(request)
        except Exception as exc:  # noqa: BLE001 — une nuit manquée : la suivante réfléchira
            log.warning("réflexion de la nuit %s : %s", night, type(exc).__name__)
            self.failed = night
            return
        raw = next((dict(call.args) for call in response.tool_calls if call.name == TOOL_NAME), {})
        reflet = parse(raw)
        attached = tuple(dict.fromkeys((shown[r.piste].seq, numbered[r.interet].key) for r in reflet.rattachements
                                       if r.piste in shown and r.interet in numbered))
        upto = max((lead.seq for lead in leads), default=state.reflected_upto)
        drafts: list[Any] = []
        refused: list[str] = []
        got = accepted(reflet.naissances, state, frame, p, shown, [label for label in labels if label], refused)
        # ce que le code a refusé, et pourquoi (jamais le sujet proposé : il pouvait nommer quelqu'un)
        log.info("réflexion de la nuit %s : %d piste(s), %d rattachée(s), %d naissance(s) proposée(s), %s",
                 night, len(shown), len(attached), len(reflet.naissances),
                 "une retenue" if got else ("refusées : " + ", ".join(refused) if refused else "aucune"))
        if got is not None:
            birth, evidence = got
            drafts.append(c.INTEREST_BORN.draft(
                night=night, label=Content.of(birth.sujet, level=int(Sensitivity.ANODYNE)),
                detail=Content.of(birth.detail[:DETAIL_CHARS], level=int(Sensitivity.ANODYNE))
                if birth.detail.strip() else None,
                about=tuple(sorted({a for lead in evidence for a in lead.about})),
                evidence=tuple(lead.seq for lead in evidence), dedupe_key=f"intérêt-né:{night}"))
        drafts.append(c.REFLECTED.draft(night=night, upto=upto, attached=attached, call_id=call_id,
                                        model=response.model, dedupe_key=f"réflexion:{night}"))
        await ctx.emit(*drafts)
