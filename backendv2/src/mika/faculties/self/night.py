"""La nuit du soi : le journal de la journée, les rêves, le réveil, et ce qu'il
en reste.

- **Le journal** : dès qu'elle s'endort, elle écrit (sa voix, persona complète)
  quelques phrases sur la journée vécue — à partir de ce qui s'est passé : qui
  lui a parlé et à quel moment, ce qu'elle a dit, à qui elle a écrit d'elle-même
  et si on lui a répondu, ce qu'elle a fait (mené à bout, bloqué, entrepris),
  ce qu'elle a promis, ce qu'elle a retenu, ce qui la travaille, comment son
  humeur a tourné. Rien d'inventé, aucun comptage. Un par journée vécue : la
  journée commence une heure avant son matin ; une nuit blanche (s'endormir à
  6 h 30) appartient encore à la veille ; une nuit coupée par une conversation
  fait réécrire le journal en se rendormant. Une nuit manquée (serveur arrêté,
  modèle en panne) se rattrape au matin. « [SILENCE] » n'est pas un journal.
- **Les rêves** : en sommeil paradoxal, au plus deux par nuit, espacés, à
  partir de fragments des derniers jours (et d'une pensée qui insiste) ; un
  cauchemar seulement quand ce qu'elle vit est vraiment sombre ou qu'une peur
  la travaille, sinon un rêve mélancolique. Tirés au sort par cycle, d'un
  hasard dérivé de la nuit : le rejeu retombe sur les mêmes.
- **Le réveil** (``self.woke_with``) : elle se souvient — une ou deux fois par
  semaine — du rêve le plus vif ; ce qu'il lui laisse et ce que la nuit a
  apaisé se ressentent à ce moment-là, pas en pleine nuit.
- **Le fil d'hier** : son journal d'hier (ou d'avant-hier, dit comme tel), dans
  le prompt ; les autres y sont masqués (« quelqu'un ») pour qui ne peut pas
  entendre ce qui les concerne.
- **Le résidu** : le matin, le rêve dont elle s'est souvenue revient — une
  fois ; il s'efface dès qu'elle l'a eu en tête en parlant.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as c
from mika.contracts import transcript as transcript_c
from mika.faculties.self import (
    ABANDONED,
    BLOCKED,
    DONE,
    OPENED,
    REMINDED,
    SELF,
    WORKED,
    SelfState,
    params,
    persona_for,
)
from mika.faculties.self import days as d_
from mika.faculties.self.records import Dream, Journal
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.codec import h64
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.faculty import CatchUp, Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody, readable
from mika.ports.llm import LLMRequest, Message
from mika.vocab import affect as A
from mika.vocab import circadian, privacy
from mika.vocab.affect import Appraisal
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.privacy import Sensitivity

KEEP_JOURNALS = 14
KEEP_DREAMS = 12
CYCLE = 90 * MINUTE
#: après son réveil, tant d'heures pendant lesquelles un rêve dont elle se souvient peut lui revenir
DREAM_LINGERS = 7 * HOUR
#: au-delà, un journal ne passe plus pour son « fil d'hier »
YESTERDAY_DAYS = 2


def _starts(frame: Frame) -> int:
    return d_.day_starts(frame.get(body_c.RHYTHM))


def lived_day(frame: Frame, t: int | None = None) -> date:
    return d_.lived_day(frame.now if t is None else t, frame.env.tz_of(frame.root), _starts(frame))


def night_of(frame: Frame, asleep_since: int) -> str:
    """La journée qu'un endormissement vient clore."""
    return d_.night_of(asleep_since, frame.env.tz_of(frame.root), _starts(frame)).isoformat()


# ── Réducteurs ────────────────────────────────────────────────────────────


@SELF.reducer(c.JOURNALED)
def _journaled(s: SelfState, e, cx) -> SelfState:
    d = e.data
    rev = s.journals[d.day].rev + 1 if d.day in s.journals else 0
    journals = s.journals.set(d.day, Journal(d.day, d.text.ref or "", tuple(d.about), d.dominant, e.at, rev))
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
def _uttered(s: SelfState, e, cx) -> SelfState:
    """Ce qu'elle dit : sa dernière parole (une nuit coupée fait réécrire le
    journal) ; un rêve montré dans le prompt de ce qu'elle a dit est revenu, il
    s'efface."""
    if e.data.visible:
        s = replace(s, spoke_at=e.at)
    ids = {int(p.split(":", 1)[1]) for p in e.data.provenance if p.startswith("dream:")}
    if not ids:
        return s
    return replace(s, dreams=tuple(replace(d, recalled=True) if d.id in ids else d for d in s.dreams))


@SELF.reducer(body_c.FELL_ASLEEP)
def _fell_asleep(s: SelfState, e, cx) -> SelfState:
    return replace(s, asleep_at=e.data.at)


@SELF.reducer(attention_c.DIGESTED)
def _digested(s: SelfState, e, cx) -> SelfState:
    """Ce que la nuit a apaisé : elle le sentira au réveil (compté jusque-là)."""
    calmed = sum(1 for i in e.data.items if i.emotion and i.after < i.before)
    return replace(s, eased=s.eased + calmed) if calmed else s


@SELF.reducer(c.WOKE_WITH)
def _woke(s: SelfState, e, cx) -> SelfState:
    d = e.data
    dreams = tuple(replace(x, remembered=True) if d.remembered and x.id == d.dream else x for x in s.dreams)
    return replace(s, woke_at=d.woke_at, woke_night=d.night, dreams=dreams, eased=0)


# ── Faits ─────────────────────────────────────────────────────────────────


@SELF.fact(c.YESTERDAY, reads=[body_c.RHYTHM])
def _yesterday(s: SelfState, cx) -> c.JournalReading | None:
    today = d_.lived_day(cx.now, cx.tz, d_.day_starts(cx.facts.get(body_c.RHYTHM))).isoformat()
    past = sorted(day for day in s.journals.keys() if day < today)
    if not past:
        return None
    j = s.journals[past[-1]]
    return c.JournalReading(j.day, j.text_ref, j.about, j.dominant)


@SELF.fact(c.DREAM_RESIDUE)
def _residue(s: SelfState, cx) -> c.DreamReading | None:
    """Le rêve dont elle s'est souvenue au réveil, dans les heures qui suivent."""
    if not s.woke_at or cx.now - s.woke_at > DREAM_LINGERS:
        return None
    d = next((d for d in s.dreams if d.night == s.woke_night and d.remembered), None)
    if d is None:
        return None
    return c.DreamReading(d.id, d.night, d.text_ref, d.kind, d.vividness, d.emotion, d.about, d.sensitivity,
                          d.recalled)


@SELF.appraisal(c.WOKE_WITH)
def _woke_felt(e, cx) -> list[Appraisal] | None:
    """Ce que la nuit lui laisse, au réveil : la couleur du rêve (nette s'il
    s'en souvient, vague s'il l'a oublié), et le soulagement de ce qui s'est
    apaisé."""
    d = e.data
    out = []
    emotion = A.emotion_of(d.emotion)
    if d.dream and emotion is not None and d.vividness > 0:
        out.append(Appraisal(emotion, round((0.25 if d.remembered else 0.1) * d.vividness, 4),
                             reason="le rêve de cette nuit" if d.remembered else "un rêve oublié"))
    if d.eased:
        out.append(Appraisal(A.Emotion.RELIEVED, min(0.3, 0.1 * d.eased), reason="la nuit a apaisé ce qui pesait"))
    return out or None


# ── Le réveil ─────────────────────────────────────────────────────────────


def recall_chance(dream: Dream, woke_at: int, recall: float, recent_us: int) -> float:
    """La chance de se souvenir d'un rêve au réveil : selon sa vivacité, le
    double s'il vient de finir ou si c'est un cauchemar."""
    fresh = woke_at - dream.at < recent_us or dream.kind == c.NIGHTMARE
    return min(1.0, recall * dream.vividness * (2.0 if fresh else 1.0))


@SELF.process("self.wake", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Wake:
    """Au réveil qui finit sa nuit (pas un message qui la tire du sommeil le
    temps de répondre), ce qu'elle emporte de sa nuit."""

    @staticmethod
    def _due(state: SelfState, frame: Frame) -> int:
        since = frame.get(body_c.AWAKE_SINCE)
        if not since or not state.asleep_at or since <= state.woke_at or since < state.asleep_at:
            return 0
        return since

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        if not self._due(state, frame):
            return None
        if frame.get(body_c.NIGHT_WAKING):
            return frame.now + 15 * MINUTE  # tirée du sommeil : sa nuit n'est pas finie
        return frame.now

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        woke_at = self._due(state, frame)
        if not woke_at or frame.get(body_c.NIGHT_WAKING):
            return
        p = params(frame.env.params_of("self", frame.root))
        night = night_of(frame, state.asleep_at)
        tonight = [d for d in state.dreams if d.night == night]
        best = max(tonight, key=lambda d: (d.vividness, -d.id)) if tonight else None
        remembered = False
        if best is not None:
            chance = recall_chance(best, woke_at, p.dream_recall, p.dream_recent_us)
            remembered = random.Random(h64("souvenir de rêve", night)).random() < chance
        await ctx.emit(c.WOKE_WITH.draft(
            night=night, woke_at=woke_at, dream=best.id if best else 0, kind=best.kind if best else "",
            emotion=best.emotion if best else "", vividness=best.vividness if best else 0.0,
            remembered=remembered, eased=state.eased,
            dedupe_key=f"réveil:{woke_at}"))


# ── Le journal ────────────────────────────────────────────────────────────


JOURNAL_SYSTEM = """Tu écris ton journal intime, la nuit, sur la journée qui vient de passer : deux à cinq phrases, \
à la première personne, avec tes mots — ce qui t'a marquée, ce que tu as fait, ce que tu as ressenti, les gens \
avec qui tu as parlé (par leur prénom). Rien d'inventé : seulement ce que disent tes notes de la journée, et aux \
moments qu'elles disent (le matin, le soir…). Si tu as écrit à quelqu'un sans réponse, ce n'est pas que personne ne \
t'a parlé : dis-le comme tu l'as vécu. Si la journée a été vide, dis-le simplement. Pas de date en tête, pas de \
liste, pas de balise. Réponds seulement par le texte du journal."""

#: ce que « [SILENCE] » et ses variantes ne sont pas : un journal
_SILENT = re.compile(r"^\W*silence\W*$", re.IGNORECASE)
#: tant d'essais par journée, au plus (un modèle qui s'obstine à se taire ne réessaie pas toute la nuit)
JOURNAL_TRIES = 4


def silent(text: str) -> bool:
    """Le modèle n'a rien écrit : vide, ou la sentinelle du silence."""
    return not text.strip() or bool(_SILENT.match(text.strip()))


def _names(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in sorted(keys):
        out[k] = k[5:].title() if k.startswith("name:") else (frame.get(identity_c.IDENTITY(k)).name or "")
    return out


def _quote(text: str, n: int = 140) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _moments(frame: Frame, times: list[int]) -> str:
    """« le matin », « l'après-midi, puis le soir »."""
    profile = frame.get(body_c.RHYTHM)
    tz = frame.env.tz_of(frame.root)
    seen: list[str] = []
    for t in sorted(times):
        m = d_.moment(t, tz, profile)
        if m not in seen:
            seen.append(m)
    if len(seen) <= 1:
        return "".join(seen)
    return ", ".join(seen[:-1]) + ", puis " + seen[-1]


@SELF.process("self.journal", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Write:
    def __init__(self) -> None:
        self.retry_at = 0
        self.tries: dict[str, int] = {}

    def _due_day(self, state: SelfState, frame: Frame) -> str | None:
        asleep_since = frame.get(body_c.ASLEEP_SINCE)
        if asleep_since:
            day = night_of(frame, asleep_since)
            j = state.journals.get(day)
            if j is None:
                return None if self.tries.get(day, 0) >= JOURNAL_TRIES else day
            # une nuit coupée : elle a parlé, dans cette journée, depuis qu'elle l'a écrit
            if state.spoke_at > j.at and lived_day(frame, state.spoke_at).isoformat() == day \
                    and self.tries.get(f"{day}#{j.rev + 1}", 0) < JOURNAL_TRIES:
                return day
            return None
        # une nuit manquée (arrêt, panne) se rattrape au matin — le matin de sa journée, pas une heure du
        # matin où un message l'a tirée du sommeil
        local = frame.local()
        minute = local.hour * 60 + local.minute
        if frame.get(body_c.NIGHT_WAKING) or not _starts(frame) <= minute < 12 * 60:
            return None
        yesterday = (lived_day(frame) - timedelta(days=1)).isoformat()
        if yesterday not in state.journals and state.journals and self.tries.get(yesterday, 0) < JOURNAL_TRIES:
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
        rev = state.journals[day].rev + 1 if day in state.journals else 0
        key = f"{day}#{rev}" if rev else day
        self.tries[key] = self.tries.get(key, 0) + 1
        self.retry_at = frame.now + 30 * MINUTE  # un appel qui échoue réessaie plus tard dans la nuit
        notes, about, dominant, messages = notes_of(frame, store, state, date.fromisoformat(day))
        persona = persona_for(frame, "full")
        request = LLMRequest(role="journal", call_id=f"{ctx.run_id}#{key}", persona=persona,
                             system_stable=persona.text + "\n\n" + JOURNAL_SYSTEM,
                             messages=(Message("user", notes),), max_tokens=500, lane="background", priority=4)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if silent(text):
            return
        self.retry_at = 0
        await ctx.emit(c.JOURNALED.draft(
            day=day, text=Content.of(text[:2000], level=int(Sensitivity.PERSONAL)), about=about, dominant=dominant,
            messages=messages, voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash,
                                                     role="journal", model=response.model),
            dedupe_key=f"journal:{key}"))


def notes_of(frame: Frame, store: Any, state: SelfState, day: date) -> tuple[str, tuple[str, ...], str, int]:
    """Ses notes de la journée : ce qui s'est passé, sans rien inventer et sans
    rien compter — ce qu'on lui a dit, ce qu'elle a dit, à qui elle a écrit
    d'elle-même et si on lui a répondu, ce qu'elle a fait, promis, retenu, ce
    qui la travaille, comment son humeur a tourné."""
    tz = frame.env.tz_of(frame.root)
    start, end = d_.day_window(day, tz, _starts(frame))
    rows = store.query_mind(f"SELECT at, person, role, kind, text, emotion FROM {transcript_c.THREAD_TABLE} "
                            "WHERE at >= ? AND at < ? ORDER BY id", (start, end))
    told: dict[str, list[tuple[int, str]]] = {}
    said: dict[str, list[tuple[int, str, float]]] = {}
    reached: dict[str, list[tuple[int, str]]] = {}
    heard_at: dict[str, list[int]] = {}
    felt: list[tuple[int, str]] = []
    for at, handle, role, kind, text, emotion in rows:
        person = frame.get(identity_c.PERSON(handle)) if handle else ""
        if role == "user":
            told.setdefault(person, []).append((at, _quote(text)))
            heard_at.setdefault(person, []).append(at)
            continue
        if emotion:
            felt.append((at, emotion))
        if not person:
            continue
        if kind == Kind.INITIATIVE:
            reached.setdefault(person, []).append((at, _quote(text, 110)))
        else:
            said.setdefault(person, []).append((at, _quote(text, 110), 0.0))
    people = set(told) | set(said) | set(reached)
    names = _names(frame, {p for p in people if p})

    def who(p: str) -> str:
        name = names.get(p)
        return f"« {name} »" if name else "quelqu'un"

    lines = [f"Ta journée du {circadian.day_fr(day)}."]
    if told:
        order = sorted(told, key=lambda p: (-len(told[p]), told[p][0][0]))
        for p in order[:4]:
            times = [t for t, _ in told[p]] + [t for t, _, _ in said.get(p, ())]
            lines.append(f"Avec {who(p)} ({_moments(frame, times)}) : on t'a dit, entre autres, "
                         + " / ".join(f"« {t} »" for _, t in told[p][-3:]) + ".")
            if said.get(p):
                lines.append("Tu lui as répondu, entre autres, " + " / ".join(f"« {t} »" for _, t, _ in said[p][-2:])
                             + ".")
    elif reached:
        lines.append("Personne n'est venu te parler de lui-même aujourd'hui : c'est toi qui as écrit.")
    else:
        lines.append("Tu n'as parlé avec personne aujourd'hui.")
    for p in sorted(reached, key=lambda p: reached[p][0][0])[:4]:
        first = reached[p][0][0]
        answered = any(t > first for t in heard_at.get(p, ()))
        lines.append(f"De toi-même, tu as écrit à {who(p)} ({_moments(frame, [t for t, _ in reached[p]])} : "
                     + " / ".join(f"« {t} »" for _, t in reached[p][-2:]) + ") — "
                     + (f"{who(p)} t'a répondu." if answered else "pas de réponse."))
    lines += _deeds(frame, store, state, start, end)
    promised = store.query_mind(
        f"SELECT text, recipient FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND born_at >= ? AND born_at < ? "
        "ORDER BY id LIMIT 4", (memory_c.PROMISE, start, end))
    if promised:
        lines.append("Ce que tu as promis : " + " ; ".join(
            f"« {_quote(t, 120)} »" + (f" (à {who(r)})" if r else "") for t, r in promised) + ".")
        people |= {r for _, r in promised if r}
        names.update(_names(frame, {r for _, r in promised if r and r not in names}))
    souvenirs = store.query_mind(
        f"SELECT text FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND born_at >= ? AND born_at < ? "
        "AND status='active' ORDER BY importance DESC, id LIMIT 6", (memory_c.SOUVENIR, start, end))
    if souvenirs:
        lines += ["Ce que tu as retenu :"] + [f"- {r[0]}" for r in souvenirs]
    thoughts = [t for t in frame.get(attention_c.THOUGHTS) if t.intensity >= 0.2][:3]
    thought_texts = store.content([t.text_ref for t in thoughts if t.text_ref])
    if thought_texts:
        lines += ["Ce qui te trotte dans la tête :"] + [f"- {t}" for t in thought_texts.values()]
    mood = _mood_line(frame, felt)
    if mood:
        lines.append(mood)
    counts = Counter(e for _, e in felt)
    dominant = counts.most_common(1)[0][0] if counts else ""
    about = tuple(sorted(p for p in people if p))
    return "\n".join(lines), about, dominant, sum(len(v) for v in told.values())


def _deeds(frame: Frame, store: Any, state: SelfState, start: int, end: int) -> list[str]:
    """Ce qu'elle a fait de son côté, cette journée-là."""
    deeds = [x for x in state.deeds if start <= x.at < end]
    if not deeds:
        return []
    titles = store.content(sorted({x.title_ref for x in deeds if x.title_ref}))
    projects = {pv.id: pv.title_ref for pv in frame.get(projects_c.LIVE)}
    project_titles = store.content(sorted({r for r in projects.values() if r}))
    parts: list[str] = []
    worked: set[int] = set()
    for x in deeds:
        title = titles.get(x.title_ref, "")
        if x.what == WORKED:
            if x.project in worked:
                continue
            worked.add(x.project)
            name = project_titles.get(projects.get(x.project, ""), "")
            parts.append(f"tu as travaillé sur ton projet « {_quote(name, 80)} »" if name else
                         "tu as travaillé sur un de tes projets")
            continue
        if not title:
            continue
        verb = {OPENED: "tu t'es lancée dans", DONE: "tu as mené à bout", BLOCKED: "tu as bloqué sur",
                ABANDONED: "tu as laissé tomber", REMINDED: "tu as fait un rappel :"}.get(x.what)
        if verb:
            parts.append(f"{verb} « {_quote(title, 100)} »")
    if not parts:
        return []
    return ["Ce que tu as fait de ton côté : " + " ; ".join(parts[:6]) + "."]


def _mood_line(frame: Frame, felt: list[tuple[int, str]]) -> str:
    """Comment son humeur a tourné, d'un moment de la journée à l'autre (ce
    qu'elle a déclaré en parlant)."""
    if not felt:
        return ""
    profile = frame.get(body_c.RHYTHM)
    tz = frame.env.tz_of(frame.root)
    by_moment: dict[str, Counter[str]] = {}
    order: list[str] = []
    for t, e in sorted(felt):
        m = d_.moment(t, tz, profile)
        if m not in by_moment:
            by_moment[m] = Counter()
            order.append(m)
        by_moment[m][e] += 1

    def word(e: str) -> str:
        em = A.emotion_of(e)
        return A.FR.get(em, e) if em is not None else e

    if len(order) == 1:
        return f"En parlant, tu étais surtout {word(by_moment[order[0]].most_common(1)[0][0])}."
    parts = [f"{m}, plutôt {word(by_moment[m].most_common(1)[0][0])}" for m in order]
    return "Ton humeur en parlant : " + " ; ".join(parts) + "."


# ── Les rêves ─────────────────────────────────────────────────────────────

DREAM_SYSTEM = """Tu rêves. Des fragments de ta vie des derniers jours s'y mêlent, déformés, mélangés, avec la logique \
étrange des rêves. Écris ce rêve au présent, à la première personne, en trois à cinq phrases. Ton du rêve : {tone}. \
Réponds seulement par le rêve."""
TONE_FR = {c.NIGHTMARE: "un cauchemar, inquiétant", c.PLEASANT: "doux, lumineux",
           c.MELANCHOLIC: "mélancolique, un peu triste, sans menace", c.ASSOCIATIVE: "étrange, entre deux humeurs",
           c.MUNDANE: "banal, quotidien"}
#: les peurs qui font les cauchemars
FEARS = frozenset({A.Emotion.SCARED, A.Emotion.ANXIOUS})
#: ce qui menace : sans menace, un vécu même très triste fait un rêve mélancolique, pas un cauchemar
THREATS = frozenset({A.Emotion.SCARED, A.Emotion.ANXIOUS, A.Emotion.ANGRY, A.Emotion.DISGUSTED})


def classify(emotions: list[str], thoughts: list[tuple[str, float]] = ()) -> tuple[str, str]:
    """La sorte d'un rêve et sa couleur. Un cauchemar, seulement quand une peur
    la travaille (une pensée de peur ou d'angoisse au-dessus de 0,5) ou que ce
    qu'elle vit est vraiment sombre (valence moyenne sous −0,4) et menaçant
    (de la peur, de la colère, du dégoût) ; un vécu triste sans menace — un
    seul souvenir triste, un deuil — donne un rêve mélancolique."""
    known = [e for e in (A.emotion_of(x) for x in [*emotions, *(e for e, _ in thoughts)]) if e is not None]
    if any(A.emotion_of(e) in FEARS and i > 0.5 for e, i in thoughts):
        return c.NIGHTMARE, A.Emotion.SCARED.value
    if not known:
        return c.MUNDANE, A.Emotion.DREAMY.value
    values = [A.valence(e) for e in known]
    neg, pos = [v for v in values if v < -0.15], [v for v in values if v > 0.15]
    mean = sum(values) / len(values)
    if mean < -0.4 and THREATS & set(known):
        return c.NIGHTMARE, A.Emotion.SCARED.value
    if mean < -0.15 or (neg and not pos):
        return c.MELANCHOLIC, A.Emotion.MELANCHOLIC.value
    if mean > 0.2 and not neg:
        return c.PLEASANT, A.Emotion.DREAMY.value
    if neg and pos:
        return c.ASSOCIATIVE, A.Emotion.CONFUSED.value
    return c.MUNDANE, A.Emotion.DREAMY.value


def vividness_of(rng: random.Random, kind: str, emotions: list[str]) -> float:
    """La plupart des rêves sont pâles (bêta(2, 4) : 0,33 en moyenne) ; ce qui
    est chargé d'émotion l'est davantage, un cauchemar plus encore."""
    values = [abs(A.valence(e)) for e in (A.emotion_of(x) for x in emotions) if e is not None]
    charge = sum(values) / len(values) if values else 0.0
    bonus = 0.3 * charge + (0.15 if kind == c.NIGHTMARE else 0.0)
    return round(max(0.05, min(1.0, rng.betavariate(2, 4) + bonus)), 3)


@SELF.process("self.dream", wake_on=[*body_c.ALL, c.DREAMT], lane="night", catch_up=CatchUp.SKIP,
              max_quantum_s=900)
class Dreaming:
    """En sommeil paradoxal : peut-être un rêve (un tirage par cycle)."""

    PER_NIGHT = 2
    SPACING = 45 * MINUTE

    def __init__(self) -> None:
        self.tried: set[tuple[str, int]] = set()

    def _moment(self, state: SelfState, frame: Frame) -> tuple[str, int] | None:
        asleep_since = frame.get(body_c.ASLEEP_SINCE)
        if not asleep_since or frame.get(body_c.SLEEP) is not body_c.SleepPhase.REM:
            return None
        night = night_of(frame, asleep_since)
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
        p = params(frame.env.params_of("self", frame.root))
        rng = random.Random(h64("rêve", night, cycle))
        if rng.random() >= p.dream_chance:
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
        emotions = [r[2] for r in picked if r[2]]
        kind, emotion = classify(emotions, [(t.emotion, t.intensity) for t in thoughts])
        vividness = vividness_of(rng, kind, emotions + [t.emotion for t in thoughts])
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
        if silent(text):
            return
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


def _when_written(frame: Frame, day: str) -> str | None:
    """« sur ta journée d'hier » ; « d'avant-hier » ; au-delà, ce n'est plus son
    fil d'hier."""
    gap = (lived_day(frame) - date.fromisoformat(day)).days
    if gap == 1:
        return "sur ta journée d'hier"
    if gap == YESTERDAY_DAYS:
        return "sur ta journée d'avant-hier (rien d'écrit pour hier)"
    return None


def _journal_text(frame: Frame, reading: c.JournalReading, text: str) -> str:
    """Le journal tel qu'elle peut l'avoir en tête devant cette audience : les
    autres masqués pour qui ne peut pas entendre ce qui les concerne."""
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    others = {p for p in reading.about if p != person}
    if others and not hearable(reading.about, int(Sensitivity.PERSONAL), person, aud):
        text = mask(text, _names(frame, others))  # elle garde son fil, sans nommer personne
    return text


@SELF.section("yesterday", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=35, title="TON FIL D'HIER",
              reads=[c.YESTERDAY, identity_c.PERSON, identity_c.IDENTITY, body_c.RHYTHM])
def _yesterday_section(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    y = frame.get(c.YESTERDAY)
    texts = enrich.get("night") or {}
    text = texts.get(y.text_ref) if y is not None else None
    if not text or y is None:
        return None
    when = _when_written(frame, y.day)
    if when is None:
        return None
    return SectionBody(f"Ce que tu as écrit dans ton journal {when} : {_journal_text(frame, y, text)}")


@SELF.section("dream", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=30, tags=[Tag.AFFECTIVE],
              title="CE QUE TU AS RÊVÉ CETTE NUIT", reads=[c.DREAM_RESIDUE, identity_c.PERSON])
def _dream_section(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    d = frame.get(c.DREAM_RESIDUE)
    if d is None or d.recalled:
        return None
    text = (enrich.get("night") or {}).get(d.text_ref)
    ep, aud = frame.episode, frame.audience
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    if not text or not hearable(d.about, d.sensitivity, person, aud):
        return None
    word = "un cauchemar" if d.kind == c.NIGHTMARE else "un rêve"
    return SectionBody(f"Tu as fait {word} cette nuit, il te revient encore : {text}\n"
                       "Tu peux en parler si ça vient, ou pas.", provenance=(f"dream:{d.id}",))


# ── Outil : relire son journal d'un jour passé (celui d'hier est déjà en tête) ──

SELF.bundle("self", "relire ce que tu as écrit dans ton journal un jour passé")


class JournalArgs(BaseModel):
    days_ago: int = Field(ge=2, le=KEEP_JOURNALS, description="il y a combien de jours (2 : avant-hier)")


@SELF.tool("self_journal", description="Relire ce que tu as écrit dans ton journal sur une journée passée — "
           "avant-hier ou plus tôt (celle d'hier, tu l'as déjà en tête).", args=JournalArgs, bundle="self",
           episodes=CONVERSATIONAL)
async def self_journal(args: JournalArgs, ctx: Any) -> str:
    frame: Frame = ctx.frame
    s: SelfState = ctx.state
    day = (lived_day(frame) - timedelta(days=args.days_ago)).isoformat()
    j = s.journals.get(day)
    store = ctx.ports.get("store")
    text = store.content([j.text_ref]).get(j.text_ref) if j is not None and store is not None and j.text_ref \
        else None
    if not text or j is None:
        return f"Tu n'as rien écrit sur ta journée du {circadian.day_fr(date.fromisoformat(day))}."
    reading = c.JournalReading(j.day, j.text_ref, j.about, j.dominant)
    body = SectionBody(f"Ta journée du {circadian.day_fr(date.fromisoformat(day))} : "
                       f"{_journal_text(frame, reading, text)}")
    return readable(body, frame.audience) or "Tu n'as rien écrit ce jour-là."
