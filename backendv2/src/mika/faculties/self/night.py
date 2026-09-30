"""La nuit du soi : le journal de la journée, les rêves, et ce qu'il en reste.

- **Le journal** : dès qu'elle s'endort, elle écrit (sa voix, persona complète)
  quelques phrases sur la journée vécue — à partir de ce qui s'est passé
  (qui lui a parlé, ce qu'elle a retenu, ce qui la travaille), rien d'inventé.
  Un par journée vécue : une heure du matin appartient encore à la veille.
  Une nuit manquée (serveur arrêté, modèle en panne) se rattrape au matin.
- **Les rêves** : en sommeil paradoxal, au plus deux par nuit, espacés, à
  partir de fragments des derniers jours (et d'une pensée qui insiste) ; un
  cauchemar quand ce qu'elle vit est sombre. Tirés au sort par cycle, d'un
  hasard dérivé de la nuit : le rejeu retombe sur les mêmes.
- **Le fil d'hier** : son journal d'hier, dans le prompt ; les autres y sont
  masqués (« quelqu'un ») pour qui ne peut pas entendre ce qui les concerne.
- **Le résidu** : le matin, un rêve vif revient — une fois ; il s'efface
  dès qu'elle l'a eu en tête en parlant.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as c
from mika.contracts import transcript as transcript_c
from mika.faculties.self import SELF, NoArgs, SelfState, persona_for
from mika.faculties.self.records import Dream, Journal
from mika.kernel.clock import DAY, MINUTE, instant, local_date_of_night
from mika.kernel.codec import h64
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.faculty import CatchUp, Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody, readable
from mika.ports.llm import LLMRequest, Message
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.affect import Appraisal
from mika.vocab.episodes import CONVERSATIONAL, Tag
from mika.vocab.privacy import Sensitivity

KEEP_JOURNALS = 14
KEEP_DREAMS = 12
DAY_STARTS = 5
CYCLE = 90 * MINUTE


def lived_day(t: int, tz: Any) -> date:
    return local_date_of_night(t, tz, DAY_STARTS)


def day_window(day: date, tz: Any) -> tuple[int, int]:
    start = datetime.combine(day, time(DAY_STARTS), tzinfo=tz)
    return instant(start), instant(start + timedelta(days=1))


# ── Réducteurs ────────────────────────────────────────────────────────────


@SELF.reducer(c.JOURNALED)
def _journaled(s: SelfState, e, cx) -> SelfState:
    d = e.data
    journals = s.journals.set(d.day, Journal(d.day, d.text.ref or "", tuple(d.about), d.dominant, e.at))
    if len(journals) > KEEP_JOURNALS:
        journals = type(journals)(sorted(journals.items())[-KEEP_JOURNALS:])
    return replace(s, journals=journals)


@SELF.reducer(c.DREAMT)
def _dreamt(s: SelfState, e, cx) -> SelfState:
    d = e.data
    dream = Dream(e.seq, d.night, d.text.ref or "", d.kind, d.vividness, d.emotion, tuple(d.about), d.sensitivity,
                  e.at)
    return replace(s, dreams=(*s.dreams, dream)[-KEEP_DREAMS:])


@SELF.reducer(rt.UTTERANCE)
def _remembered_dream(s: SelfState, e, cx) -> SelfState:
    """Un rêve montré dans le prompt de ce qu'elle a dit : il est revenu, il s'efface."""
    ids = {int(p.split(":", 1)[1]) for p in e.data.provenance if p.startswith("dream:")}
    if not ids:
        return s
    return replace(s, dreams=tuple(replace(d, recalled=True) if d.id in ids else d for d in s.dreams))


# ── Faits ─────────────────────────────────────────────────────────────────


@SELF.fact(c.YESTERDAY)
def _yesterday(s: SelfState, cx) -> c.JournalReading | None:
    today = lived_day(cx.now, cx.tz).isoformat()
    past = sorted(day for day in s.journals.keys() if day < today)
    if not past:
        return None
    j = s.journals[past[-1]]
    return c.JournalReading(j.day, j.text_ref, j.about, j.dominant)


@SELF.fact(c.DREAM_RESIDUE)
def _residue(s: SelfState, cx) -> c.DreamReading | None:
    night = (lived_day(cx.now, cx.tz) - timedelta(days=1)).isoformat()
    dreams = sorted((d for d in s.dreams if d.night == night), key=lambda d: (-d.vividness, d.id))
    if not dreams:
        return None
    d = dreams[0]
    return c.DreamReading(d.id, d.night, d.text_ref, d.kind, d.vividness, d.emotion, d.about, d.sensitivity,
                          d.recalled)


@SELF.appraisal(c.DREAMT)
def _dream_felt(e, cx) -> Appraisal | None:
    """Un cauchemar laisse une trace au réveil ; un beau rêve aussi."""
    emotion = A.emotion_of(e.data.emotion)
    if emotion is None:
        return None
    return Appraisal(emotion, 0.3 * e.data.vividness, reason="rêve")


# ── Le journal ────────────────────────────────────────────────────────────


JOURNAL_SYSTEM = """Tu écris ton journal intime, la nuit, sur la journée qui vient de passer : deux à cinq phrases, \
à la première personne, avec tes mots — ce qui t'a marquée, ce que tu as ressenti, les gens à qui tu as parlé (par \
leur prénom). Rien d'inventé : seulement ce que disent tes notes de la journée. Si elle a été vide, dis-le \
simplement. Réponds seulement par le texte du journal."""


def _names(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in sorted(keys):
        out[k] = k[5:].title() if k.startswith("name:") else (frame.get(identity_c.IDENTITY(k)).name or "")
    return out


@SELF.process("self.journal", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Write:
    def __init__(self) -> None:
        self.retry_at = 0

    def _due_day(self, state: SelfState, frame: Frame) -> str | None:
        tz = frame.env.tz_of(frame.root)
        asleep_since = frame.get(body_c.ASLEEP_SINCE)
        if asleep_since:
            day = lived_day(asleep_since, tz).isoformat()
            return None if day in state.journals else day
        # une nuit manquée (arrêt, panne) se rattrape au matin
        now = frame.local()
        yesterday = (lived_day(frame.now, tz) - timedelta(days=1)).isoformat()
        if now.hour < 12 and yesterday not in state.journals and state.journals:
            return yesterday
        return None

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        if self._due_day(state, frame) is None:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        store = ctx.ports.get("store")
        day = self._due_day(state, frame)
        if day is None or store is None or ctx.llm is None:
            return
        self.retry_at = frame.now + 30 * MINUTE  # un appel qui échoue réessaie plus tard dans la nuit
        notes, about, dominant, messages = self._notes(frame, store, date.fromisoformat(day))
        persona = persona_for(frame, "full")
        request = LLMRequest(role="journal", call_id=f"{ctx.run_id}#{day}", persona=persona,
                             system_stable=persona.text + "\n\n" + JOURNAL_SYSTEM,
                             messages=(Message("user", notes),), max_tokens=500, lane="background", priority=4)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if not text:
            return
        self.retry_at = 0
        await ctx.emit(c.JOURNALED.draft(
            day=day, text=Content.of(text[:2000], level=int(Sensitivity.PERSONAL)), about=about, dominant=dominant,
            messages=messages, voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash,
                                                     role="journal", model=response.model),
            dedupe_key=f"journal:{day}"))

    def _notes(self, frame: Frame, store: Any, day: date) -> tuple[str, tuple[str, ...], str, int]:
        tz = frame.env.tz_of(frame.root)
        start, end = day_window(day, tz)
        rows = store.query_mind(f"SELECT person, role, text, emotion, room FROM {transcript_c.THREAD_TABLE} "
                                "WHERE at >= ? AND at < ? ORDER BY id", (start, end))
        persons: Counter[str] = Counter()
        said: dict[str, list[str]] = {}
        emotions: Counter[str] = Counter()
        for handle, role, text, emotion, _room in rows:
            if role == "user":
                person = frame.get(identity_c.PERSON(handle))
                persons[person] += 1
                said.setdefault(person, []).append(" ".join(str(text).split())[:140])
            elif emotion:
                emotions[emotion] += 1
        souvenirs = store.query_mind(
            f"SELECT text FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND born_at >= ? AND born_at < ? "
            "AND status='active' ORDER BY importance DESC, id LIMIT 12", (memory_c.SOUVENIR, start, end))
        thoughts = [t for t in frame.get(attention_c.THOUGHTS) if t.intensity >= 0.2][:3]
        thought_texts = store.content([t.text_ref for t in thoughts if t.text_ref])
        names = _names(frame, set(persons))
        lines = [f"Journée du {day.isoformat()}."]
        if persons:
            lines.append("On t'a parlé : " + ", ".join(
                f"{names.get(p) or 'quelqu’un'} ({n} message{'s' if n > 1 else ''})" for p, n in persons.most_common()))
            for p, _n in persons.most_common(4):
                lines.append(f"Ce que {names.get(p) or 'quelqu’un'} t'a dit, entre autres : "
                             + " / ".join(f"« {t} »" for t in said[p][-3:]))
        else:
            lines.append("Personne ne t'a parlé aujourd'hui.")
        if souvenirs:
            lines += ["Ce que tu as retenu :"] + [f"- {r[0]}" for r in souvenirs]
        if thought_texts:
            lines += ["Ce qui te trotte dans la tête :"] + [f"- {t}" for t in thought_texts.values()]
        dominant = emotions.most_common(1)[0][0] if emotions else ""
        if dominant:
            lines.append(f"Ce que tu as le plus ressenti en parlant : {A.FR.get(A.emotion_of(dominant), dominant)}.")
        about = tuple(sorted(p for p in persons if p))
        return "\n".join(lines), about, dominant, sum(persons.values())


# ── Les rêves ─────────────────────────────────────────────────────────────

DREAM_SYSTEM = """Tu rêves. Des fragments de ta vie des derniers jours s'y mêlent, déformés, mélangés, avec la logique \
étrange des rêves. Écris ce rêve au présent, à la première personne, en trois à cinq phrases. Ton du rêve : {tone}. \
Réponds seulement par le rêve."""
TONE_FR = {c.NIGHTMARE: "un cauchemar, inquiétant", c.PLEASANT: "doux, lumineux",
           c.ASSOCIATIVE: "étrange, entre deux humeurs", c.MUNDANE: "banal, quotidien"}
VIVIDNESS = {c.NIGHTMARE: 0.8, c.PLEASANT: 0.7, c.ASSOCIATIVE: 0.6, c.MUNDANE: 0.4}


def classify(emotions: list[str]) -> tuple[str, str]:
    values = [A.valence(e) for e in (A.emotion_of(x) for x in emotions) if e is not None]
    if not values:
        return c.MUNDANE, A.Emotion.DREAMY.value
    neg, pos = [v for v in values if v < -0.15], [v for v in values if v > 0.15]
    mean = sum(values) / len(values)
    if mean < -0.2 or (neg and not pos and len(neg) >= 1 and min(neg) < -0.5):
        return c.NIGHTMARE, A.Emotion.SCARED.value
    if mean > 0.2 and not neg:
        return c.PLEASANT, A.Emotion.DREAMY.value
    if neg and pos:
        return c.ASSOCIATIVE, A.Emotion.CONFUSED.value
    return c.MUNDANE, A.Emotion.DREAMY.value


@SELF.process("self.dream", wake_on=[*body_c.ALL, c.DREAMT], lane="night", catch_up=CatchUp.SKIP,
              max_quantum_s=900)
class Dreaming:
    """En sommeil paradoxal : peut-être un rêve (un tirage par cycle)."""

    PROBABILITY = 0.6
    PER_NIGHT = 2
    SPACING = 45 * MINUTE

    def __init__(self) -> None:
        self.tried: set[tuple[str, int]] = set()

    def _moment(self, state: SelfState, frame: Frame) -> tuple[str, int] | None:
        asleep_since = frame.get(body_c.ASLEEP_SINCE)
        if not asleep_since or frame.get(body_c.SLEEP) is not body_c.SleepPhase.REM:
            return None
        night = lived_day(asleep_since, frame.env.tz_of(frame.root)).isoformat()
        tonight = [d for d in state.dreams if d.night == night]
        if len(tonight) >= self.PER_NIGHT or (tonight and frame.now - tonight[-1].at < self.SPACING):
            return None
        cycle = (frame.now - asleep_since) // CYCLE
        if (night, cycle) in self.tried:
            return None
        return night, cycle

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        if not frame.get(body_c.ASLEEP_SINCE):
            return None
        return frame.now if self._moment(state, frame) else frame.now + 15 * MINUTE

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        moment = self._moment(ctx.state, frame)
        store = ctx.ports.get("store")
        if moment is None or store is None or ctx.llm is None:
            return
        self.tried.add(moment)
        night, cycle = moment
        rng = random.Random(h64("rêve", night, cycle))
        if rng.random() >= self.PROBABILITY:
            return
        rows = store.query_mind(
            f"SELECT id, text, emotion, about, sensitivity FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND "
            "status='active' AND born_at >= ? ORDER BY importance DESC, id DESC LIMIT 8",
            (memory_c.SOUVENIR, frame.now - 3 * DAY))
        picked = rng.sample(rows, k=min(3, len(rows))) if rows else []
        thoughts = [t for t in frame.get(attention_c.THOUGHTS) if t.intensity >= 0.3][:1]
        texts = store.content([t.text_ref for t in thoughts if t.text_ref])
        if not picked and not texts:
            return  # rien à rêver
        emotions = [r[2] for r in picked if r[2]] + [t.emotion for t in thoughts]
        kind, emotion = classify(emotions)
        about: set[str] = {a for t in thoughts for a in t.about}
        sensitivity = max([int(r[4]) for r in picked] + [t.sensitivity for t in thoughts] + [1])
        for r in picked:
            about |= set(_about(r[3]))
        fragments = [f"- {r[1]}" for r in picked] + [f"- (ce qui te travaille) {t}" for t in texts.values()]
        persona = persona_for(frame, "full")
        request = LLMRequest(role="dream", call_id=f"{ctx.run_id}#{night}:{cycle}", persona=persona,
                             system_stable=persona.text + "\n\n" + DREAM_SYSTEM.format(tone=TONE_FR[kind]),
                             messages=(Message("user", "Fragments :\n" + "\n".join(fragments)),), max_tokens=400,
                             lane="background", priority=5)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if not text:
            return
        vividness = round(max(0.1, min(1.0, VIVIDNESS[kind] + rng.uniform(-0.1, 0.1))), 3)
        await ctx.emit(c.DREAMT.draft(
            night=night, text=Content.of(text[:2000], level=sensitivity), kind=kind, vividness=vividness,
            emotion=emotion, about=tuple(sorted(about)), sensitivity=sensitivity,
            sources=tuple(int(r[0]) for r in picked),
            voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash, role="dream",
                                  model=response.model),
            dedupe_key=f"rêve:{night}:{cycle}"))


def _about(raw: str | None) -> list[str]:
    return list(json.loads(raw or "[]"))


# ── Ce qui en reste dans le prompt ────────────────────────────────────────


def hearable(about: tuple[str, ...], sensitivity: int, interlocutor: str | None, aud: Audience | None) -> bool:
    """Les règles de la mémoire (``vocab.privacy.hearable``)."""
    if aud is None:
        return not about and sensitivity <= Sensitivity.ANODYNE
    return privacy.hearable(about, sensitivity, interlocutor, aud.level, aud.witness_level, aud.private_ok)


def mask(text: str, names: Mapping[str, str]) -> str:
    """Les prénoms des autres remplacés par « quelqu'un »."""
    for name in sorted({n for n in names.values() if n}, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", "quelqu'un", text, flags=re.IGNORECASE)
    return text


@SELF.enricher("night", episodes=CONVERSATIONAL, deadline_ms=400)
async def _night_texts(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    if store is None:
        return None
    refs = []
    y = frame.get(c.YESTERDAY)
    if y is not None:
        refs.append(y.text_ref)
    d = frame.get(c.DREAM_RESIDUE)
    if d is not None:
        refs.append(d.text_ref)
    return store.content([r for r in refs if r]) if refs else None


@SELF.section("yesterday", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=35, title="TON FIL D'HIER",
              reads=[c.YESTERDAY, identity_c.PERSON, identity_c.IDENTITY])
def _yesterday_section(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    y = frame.get(c.YESTERDAY)
    texts = enrich.get("night") or {}
    text = texts.get(y.text_ref) if y is not None else None
    if not text:
        return None
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    others = {p for p in y.about if p != person}
    if others and not hearable(y.about, int(Sensitivity.PERSONAL), person, aud):
        text = mask(text, _names(frame, others))  # elle garde son fil, sans nommer personne
    return SectionBody(f"Ce que tu as écrit dans ton journal hier soir : {text}")


@SELF.section("dream", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=30, tags=[Tag.AFFECTIVE],
              title="CE QUE TU AS RÊVÉ CETTE NUIT", reads=[c.DREAM_RESIDUE, identity_c.PERSON])
def _dream_section(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    d = frame.get(c.DREAM_RESIDUE)
    hour = frame.local().hour
    if d is None or d.recalled or d.vividness < 0.6 or not 5 <= hour < 14:
        return None
    text = (enrich.get("night") or {}).get(d.text_ref)
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if not text or not hearable(d.about, d.sensitivity, person, aud):
        return None
    word = "un cauchemar" if d.kind == c.NIGHTMARE else "un rêve"
    return SectionBody(f"Tu as fait {word} cette nuit, il te revient encore : {text}\n"
                       "Tu peux en parler si ça vient, ou pas.", provenance=(f"dream:{d.id}",))



@SELF.tool("self_yesterday", description="Relire ton fil d'hier : le journal que tu as écrit cette nuit.",
           args=NoArgs, bundle="self", episodes=CONVERSATIONAL)
async def self_yesterday(args: NoArgs, ctx: Any) -> str:
    enrich = {"night": await _night_texts(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_yesterday_section(ctx.state, ctx.frame, enrich), ctx.frame.audience) or \
        "Tu n'as rien écrit pour hier."


@SELF.tool("self_dream", description="Te rappeler le rêve de cette nuit (le matin seulement, tant qu'il est vif).",
           args=NoArgs, bundle="self", episodes=CONVERSATIONAL)
async def self_dream(args: NoArgs, ctx: Any) -> str:
    enrich = {"night": await _night_texts(ctx.state, ctx.frame, ctx.ports) or {}}
    return readable(_dream_section(ctx.state, ctx.frame, enrich), ctx.frame.audience) or \
        "Tu ne te souviens d'aucun rêve."
