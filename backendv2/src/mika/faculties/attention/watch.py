"""La veille de l'attention : écrire les pensées nées, constater les attentes
comblées ou déçues, remarquer qui lui manque, y repenser par moments.

Les textes des pensées ne sont jamais inventés : ce qu'on lui a dit, entre
guillemets, ce qu'elle croyait et ce qu'elle croit maintenant, le nom de
quelqu'un qui lui manque.
"""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import attention as c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.attention.faculty import (
    ATTENTION,
    RELATIONAL,
    AttentionState,
    Heard,
    Pending,
    habituation,
    params,
)
from mika.kernel.clock import HOUR, local_date_of_night, next_local
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.affect import Emotion
from mika.vocab.days import when_fr
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import elided, stems

EXCERPT = 160


def _clip(text: str, n: int = EXCERPT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _name(frame: Frame, person: str) -> str:
    return frame.get(identity_c.IDENTITY(person)).name or "quelqu'un"


def ripe(q: Pending, frame: Frame, p: Any) -> int:
    """Quand une pensée en attente peut naître : tout de suite, sauf celle d'un échange — quand la personne n'a plus
    rien écrit depuis ``exchange_settle_us`` (la pensée naît de ce qui a le plus marqué, pas du premier message)."""
    if q.origin != c.EXCHANGE or not q.person:
        return q.at
    return max(q.at, _last_from(frame, q.person)) + p.exchange_settle_us


def _last_from(frame: Frame, person: str) -> int:
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    return max(frame.get(transcript_c.LAST_FROM(h)) for h in handles)


def met(state: AttentionState, frame: Frame) -> list[str]:
    """Les attentes comblées — et les réponses venues en retard (``late:…``),
    qui comptent encore tant qu'elles arrivent dans trois fois le délai attendu :
    elle n'est plus ignorée. Plus tard, la personne écrit, mais ce n'est plus
    une réponse. Une promesse ne se comble pas quand la personne écrit : quand
    elle est tenue (``memory``)."""
    out = [k for k, x in state.expectations.items()
           if x.kind in (c.REPLY, c.RETURN) and _last_from(frame, x.person) > x.since]
    out += [f"late:{person}" for person, late in state.late.items()
            if late.since < _last_from(frame, person) <= late.until]
    return out


def here(frame: Frame) -> dict[str, int]:
    """Les personnes connectées en ce moment (devant un écran), et depuis quand
    sans interruption."""
    out: dict[str, int] = {}
    for h in frame.get(presence_c.PRESENT):
        person, since = frame.get(identity_c.PERSON(h)) or h, frame.get(presence_c.SINCE(h))
        if since is not None:
            out[person] = min(since, out.get(person, since))
    return out


def left_hanging(state: AttentionState, p: Any, present: dict[str, int]) -> list[tuple[int, str]]:
    """Les questions qu'elle a posées et qui attendent encore leur réponse, sans
    qu'elle l'ait encore ressenti : (quand ça se ressentira, personne). Seulement
    envers quelqu'un qui est resté là depuis, sans répondre : une conversation
    que l'autre a quittée (on se reparlera demain), quelqu'un qui revient le
    lendemain, un message lu quand on y pense, ne laissent pas de question en
    suspens."""
    return sorted((ex.last_out + p.question_unanswered_us, person) for person, ex in state.exchanges.items()
                  if ex.unanswered and ex.asked and not ex.owed and not ex.felt and not ex.initiatives
                  and present.get(person, ex.last_out + 1) <= ex.last_out)


#: une amie ne « revient » pas le jour même où elle est passée : son heure habituelle se cherche après ce délai
_EXPECTED_AFTER_US = 12 * HOUR


def expected_back(frame: Frame, person: str, p: Any) -> int | None:
    """Quand une amie ou une proche qui écrit presque chaque jour, à peu près à la même heure, passera sans doute :
    son heure habituelle, le jour d'après son dernier message. ``None`` pour qui n'a pas ce rythme-là."""
    if not is_identifiable(person) or frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
        return None
    ct = frame.get(social_c.CONTACT(person))
    if not ct.last_in or not ct.measured or ct.rhythm_days > p.alone_daily_rhythm_days:
        return None
    hours = frame.get(others_c.HOURS(person))
    if not hours.learned or hours.usual is None:
        return None
    return next_local(ct.last_in + _EXPECTED_AFTER_US, hours.usual, 0, frame.env.tz_of(frame.root))


def alone_due(state: AttentionState, p: Any, frame: Frame | None = None) -> int | None:
    """Quand la prochaine pensée de solitude viendra : un jour sans que
    personne ne lui écrive, puis une de plus par jour de silence ; ``None``
    tant que personne ne lui a jamais écrit. Une amie qui passe presque chaque
    jour à la même heure, on l'attend : pas avant cette heure-là, plus une marge
    (c'est quand elle ne vient pas qu'on se sent seule)."""
    if not state.last_contact or p.alone_after_us <= 0:
        return None
    due = max(state.last_contact, state.alone_at) + p.alone_after_us
    if frame is None:
        return due
    expected = [t for person in sorted(state.exchanges) if (t := expected_back(frame, person, p)) is not None]
    if expected:
        due = max(due, min(expected) + p.alone_margin_us)
    return due


@ATTENTION.process("attention.watch", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, rt.EPISODE_STARTED,
                                               memory_c.BELIEVED, memory_c.PROMISE_NOTICED,
                                               memory_c.PROMISE_RESOLVED, goals_c.GOAL_CLOSED,
                                               projects_c.OBJECTIVE_CLOSED, others_c.READ,
                                               *c.ALL, *body_c.ALL, *presence_c.ALL],
                   wake_on_shapes=[c.Signal],
                   lane="background", catch_up=CatchUp.ONCE, max_quantum_s=1800, priority=30)
class Watch:
    def __init__(self) -> None:
        self.missing_at = 0

    def next_due(self, state: AttentionState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("attention", frame.root))
        if state.signals or met(state, frame) or any(ripe(q, frame, p) <= frame.now for q in state.pending):
            return frame.now
        times = [x.deadline for x in state.expectations.values() if x.deadline is not None]
        times += [ripe(q, frame, p) for q in state.pending]
        if frame.get(body_c.SLEEP) is body_c.SleepPhase.AWAKE:
            thoughts = frame.get(c.THOUGHTS)
            if thoughts and thoughts[0].intensity >= p.dwell_from:
                times.append(state.dwelt_at + p.dwell_every_us)
            times.append(self.missing_at + p.missing_check_us)
            alone = alone_due(state, p, frame)
            if alone is not None:
                times.append(alone)
            times += [t for t, _person in left_hanging(state, p, here(frame))[:1]]
        return max(frame.now, min(times)) if times else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: AttentionState = ctx.state
        p = params(frame.env.params_of("attention", frame.root))
        store = ctx.ports.get("store")
        drafts: list[Draft[Any]] = []
        for q in [q for q in state.pending if ripe(q, frame, p) <= frame.now][:6]:
            drafts.append(self._thought(q, frame, store))
        drafts += self._signals(state, frame, store, p)
        met_keys = set(met(state, frame))
        for person, late in sorted(state.late.items()):
            if f"late:{person}" in met_keys:
                drafts.append(c.EXPECTATION_MET.draft(kind=c.REPLY, person=person, since=late.since,
                                                      dedupe_key=f"attente:tardive:{person}:{late.since}"))
        for key, x in sorted(state.expectations.items()):
            mark = f"attente:{x.kind}:{x.person}:{x.since}" + (f":{x.ref}" if x.ref is not None else "")
            if key in met_keys:
                drafts.append(c.EXPECTATION_MET.draft(kind=x.kind, person=x.person, since=x.since, ref=x.ref,
                                                      dedupe_key=mark))
            elif x.deadline is not None and x.deadline <= frame.now:
                drafts.append(c.EXPECTATION_MISSED.draft(kind=x.kind, person=x.person, since=x.since, ref=x.ref,
                                                         dedupe_key=mark))
        awake = frame.get(body_c.SLEEP) is body_c.SleepPhase.AWAKE
        if awake and frame.now - self.missing_at >= p.missing_check_us:
            self.missing_at = frame.now
            drafts += self._missing(state, frame, p)
        alone = alone_due(state, p, frame)
        if awake and alone is not None and alone <= frame.now:
            drafts.append(self._alone(state, frame, p))
        if awake:
            pending = {q.person for q in state.pending if q.origin == c.UNANSWERED}
            for due, person in left_hanging(state, p, here(frame)):
                if due <= frame.now and person not in pending:
                    drafts.append(self._hanging(state, frame, person, p))
        thoughts = frame.get(c.THOUGHTS)
        if awake and thoughts and thoughts[0].intensity >= p.dwell_from \
                and frame.now - state.dwelt_at >= p.dwell_every_us:
            t = thoughts[0]
            drafts.append(c.DWELT.draft(thought=t.id, emotion=t.emotion, intensity=t.intensity, origin=t.origin))
        if drafts:
            await ctx.emit(*drafts)

    def _thought(self, q: Pending, frame: Frame, store: Any) -> Draft[Any]:
        mark = f"pensée:{q.origin}:{q.source}"
        if q.origin == c.PROMISE:
            return self._broken_promise(q, frame, store, mark)
        if q.origin == c.BLOCKED:
            title = store.content([q.ref]).get(q.ref) if store is not None and q.ref else None
            text = f"Je bloque sur : {_clip(title, 200)}" if title else "Je bloque sur quelque chose."
            return c.THOUGHT_BORN.draft(text=Content.of(text, level=q.sensitivity), emotion=q.emotion,
                                        intensity=q.intensity, origin=q.origin, about=q.about,
                                        sensitivity=q.sensitivity, source=q.source, dedupe_key=mark)
        if q.origin == c.REVISION:
            texts = {}
            if store is not None:
                rows = store.query_mind(f"SELECT id, text, about, sensitivity FROM {memory_c.ITEMS_TABLE} "
                                        "WHERE id IN (?, ?)", (q.extra or -1, q.source))
                texts = {int(i): (t, a, int(sv)) for i, t, a, sv in rows}
            old, new = texts.get(q.extra or -1), texts.get(q.source)
            text = (f"Je croyais que « {_clip(old[0], 120)} » — apparemment ce n'est plus vrai : "
                    f"« {_clip(new[0], 120)} »") if old and new else "Je dois réviser quelque chose que je croyais."
            about: tuple[str, ...] = tuple(sorted(set(_about(old) + _about(new)))) if old and new else ()
            sens = max((x[2] for x in (old, new) if x), default=int(Sensitivity.PERSONAL))
            return c.THOUGHT_BORN.draft(text=Content.of(text, level=sens), emotion=q.emotion, intensity=q.intensity,
                                        origin=q.origin, about=about, sensitivity=sens, source=q.source,
                                        dedupe_key=mark)
        who = _name(frame, q.person) if q.person else "quelqu'un"
        if q.origin == c.REMORSE:
            # être dure avec quelqu'un se regrette ; ça la concerne, sans rien dire de ce qui a été dit
            sens = int(Sensitivity.PERSONAL)
            return c.THOUGHT_BORN.draft(text=Content.of(f"J'ai été dure avec {who}.", level=sens),
                                        emotion=q.emotion, intensity=q.intensity, origin=q.origin,
                                        about=(q.person,) if q.person else (), sensitivity=sens, source=q.source,
                                        dedupe_key=mark)
        if q.origin == c.UNANSWERED:
            # être ignorée se ressent ; ce n'est pas une confidence, mais ça concerne la personne
            sens = int(Sensitivity.PERSONAL)
            return c.THOUGHT_BORN.draft(text=Content.of(f"{who} ne m'a pas répondu.", level=sens),
                                        emotion=q.emotion, intensity=q.intensity, origin=q.origin,
                                        about=(q.person,) if q.person else (), sensitivity=sens, source=q.source,
                                        dedupe_key=mark)
        said = ""
        if store is not None:
            rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (q.source,))
            said = str(rows[0][0]) if rows else ""
        if q.origin == c.CONCERN:
            text = (f"{who} n'avait pas l'air comme d'habitude : « {_clip(said)} »" if said else
                    f"{who} n'avait pas l'air comme d'habitude.")
        else:
            text = f"{who} m'a dit : « {_clip(said)} »" if said else f"Un échange avec {who} m'a marquée."
        sens = int(Sensitivity.ANODYNE if q.public else Sensitivity.PERSONAL)
        return c.THOUGHT_BORN.draft(text=Content.of(text, level=sens), emotion=q.emotion, intensity=q.intensity,
                                    origin=q.origin, about=(q.person,) if q.person else (), sensitivity=sens,
                                    source=q.source, dedupe_key=mark)

    def _broken_promise(self, q: Pending, frame: Frame, store: Any, mark: str) -> Draft[Any]:
        """« J'avais promis à Alice… » : le texte de la promesse, jamais inventé ;
        sa sensibilité, celle de la promesse."""
        rows = store.query_mind(f"SELECT text, sensitivity FROM {memory_c.ITEMS_TABLE} WHERE id=?", (q.source,)) \
            if store is not None else []
        who = _name(frame, q.person) if q.person else "quelqu'un"
        sens = max(int(Sensitivity.ANODYNE), int(rows[0][1])) if rows else int(Sensitivity.PERSONAL)
        text = (f"J'avais promis à {who} : « {_clip(str(rows[0][0]), 200)} » — et je ne l'ai pas fait à temps."
                if rows else f"J'avais promis quelque chose à {who}, et je ne l'ai pas fait à temps.")
        return c.THOUGHT_BORN.draft(text=Content.of(text, level=sens), emotion=q.emotion, intensity=q.intensity,
                                    origin=q.origin, about=(q.person,) if q.person else (), sensitivity=sens,
                                    source=q.source, dedupe_key=mark)

    def _signals(self, state: AttentionState, frame: Frame, store: Any, p: Any) -> list[Draft[Any]]:
        """Remarquer ce que les sources signalent : l'émotion dosée par source,
        l'habituation ; ce qui est assez pertinent devient une pensée."""
        out: list[Draft[Any]] = []
        extra: list[Heard] = []
        batch = state.signals[:10]
        texts = store.content([x.summary_ref for x in batch if x.summary_ref]) if store is not None else {}
        for x in batch:
            weight, room = habituation(state, x.source, x.kind, frame.now, p, tuple(extra))
            intensity = round(min(x.intensity * weight, room), 4) if x.emotion else 0.0
            out.append(c.NOTICED.draft(signal=x.seq, source=x.source, kind=x.kind, weight=round(weight, 4),
                                       emotion=x.emotion, intensity=intensity, dedupe_key=f"remarqué:{x.seq}"))
            extra.append(Heard(frame.now, x.source, x.kind, intensity))
            text = texts.get(x.summary_ref)
            if text and x.pertinence * weight >= p.signal_thought_from:
                level = x.sensitivity
                out.append(c.THOUGHT_BORN.draft(
                    text=Content.of(_clip(text, 240), level=level), emotion=x.emotion or Emotion.CURIOUS.value,
                    intensity=round(min(p.signal_thought_max, x.pertinence * weight * p.signal_thought_factor), 3),
                    origin=c.SIGNAL, about=x.about, sensitivity=level, source=x.seq, bundle=x.bundle,
                    dedupe_key=f"pensée:signal:{x.seq}"))
        return out

    def _missing(self, state: AttentionState, frame: Frame, p: Any) -> list[Draft[Any]]:
        """Une amie qui manque et qu'elle ne peut pas joindre : une pensée
        (joignable, elle lui écrirait — c'est ``social``)."""
        present = set(frame.get(presence_c.PRESENT))
        already = {a for t in state.thoughts.values() if t.origin == c.MISSING for a in t.about}
        out: list[Draft[Any]] = []
        for person, _ratio in frame.get(social_c.MISSED):
            if person in already:
                continue
            handles = frame.get(identity_c.HANDLES(person))
            if frame.get(identity_c.REACHABLE(person)) or any(h in present for h in handles):
                continue
            text = f"J'aimerais bien avoir des nouvelles {elided(_name(frame, person), 'de')}."
            out.append(c.THOUGHT_BORN.draft(
                text=Content.of(text, level=int(Sensitivity.ANODYNE)), emotion=Emotion.NOSTALGIC.value,
                intensity=p.missing_intensity, origin=c.MISSING, about=(person,),
                sensitivity=int(Sensitivity.ANODYNE), source=None,
                dedupe_key=f"manque:{person}:{frame.get(social_c.CONTACT(person)).last_in}"))
            break  # un manque à la fois
        return out


    def _hanging(self, state: AttentionState, frame: Frame, person: str, p: Any) -> Draft[Any]:
        """Sa question est restée sans réponse : elle le ressent, un peu (sans
        lui réécrire pour autant)."""
        ex = state.exchanges[person]
        sens = int(Sensitivity.PERSONAL)
        return c.THOUGHT_BORN.draft(
            text=Content.of(f"{_name(frame, person)} n'a pas répondu à ma question.", level=sens),
            emotion=Emotion.SAD.value, intensity=round(p.unanswered_intensity * 0.8, 3), origin=c.UNANSWERED,
            about=(person,), sensitivity=sens, source=None, dedupe_key=f"question:{person}:{ex.last_out}")

    def _alone(self, state: AttentionState, frame: Frame, p: Any) -> Draft[Any]:
        """Personne ne lui a écrit depuis plus d'un jour : une pensée de solitude,
        une par jour de silence (le texte dit depuis quand, en jours du calendrier)."""
        when = when_fr(state.last_contact, frame.now, frame.env.tz_of(frame.root))
        since = when[len("il y a "):] if when.startswith("il y a ") else when.removeprefix("dans ")
        sens = int(Sensitivity.ANODYNE)
        return c.THOUGHT_BORN.draft(text=Content.of(f"Personne ne m'a parlé depuis {since}.", level=sens),
                                    emotion=Emotion.LONELY.value, intensity=p.alone_intensity, origin=c.ALONE,
                                    about=(), sensitivity=sens, source=None,
                                    dedupe_key=f"seule:{state.last_contact}:{max(state.alone_at, state.last_contact)}")


def _about(row: tuple[Any, ...] | None) -> tuple[str, ...]:
    return tuple(json.loads(row[1] or "[]")) if row else ()


# ── Ce que la personne écrit recoupe ce qui la concerne ───────────────────


@ATTENTION.interpret(rt.PERCEPTION_RECEIVED)
def _touches(state: AttentionState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Ce qu'elle vient d'écrire recoupe-t-il le sujet d'une inquiétude, d'un
    échange qui a marqué, la concernant ? (des mots qui portent un sujet en
    commun, son nom mis à part) — « ok », « oui » ne recoupent rien."""
    d = ev.data
    if not d.addressed or not is_identifiable(d.handle) or not d.text.text:
        return []
    person = frame.get(identity_c.PERSON(d.handle))
    thoughts = [t for t in frame.get(c.THOUGHTS) if t.origin in RELATIONAL and person in t.about and t.text_ref]
    store = ports.get("store") if ports else None
    if not thoughts or store is None:
        return []
    texts = store.content([t.text_ref for t in thoughts])
    said = stems(d.text.text) - stems(_name(frame, person))
    hit = tuple(t.id for t in thoughts if said & stems(_subject(texts.get(t.text_ref) or "")))
    return [c.TOUCHED.draft(person=person, thoughts=hit)] if hit else []


def _subject(text: str) -> str:
    """Le sujet d'une pensée née d'un message : ses mots à elle, entre guillemets
    — pas le gabarit autour (« … n'avait pas l'air comme d'habitude »), qu'un
    « comme d'habitude » recouperait sans rien dire du sujet."""
    if "«" not in text or "»" not in text:
        return ""
    return text.split("«", 1)[1].rsplit("»", 1)[0]


# ── La nuit ───────────────────────────────────────────────────────────────

#: Ce que devient une couleur après une nuit (les autres restent ce qu'elles sont).
DRIFT = {
    "frustrated": "relieved", "anxious": "relieved", "scared": "relieved", "angry": "thinking",
    "disgusted": "thinking", "jealous": "thinking", "sad": "melancholic", "lonely": "melancholic",
}


@ATTENTION.process("attention.digest", wake_on=[*body_c.ALL], lane="night", catch_up=CatchUp.ONCE,
                   max_quantum_s=3600)
class Digest:
    """Une fois par nuit, après trois heures de sommeil : les pensées de la
    veille s'allègent des deux tiers ; leur couleur se calme."""

    def _night(self, state: AttentionState, frame: Frame) -> str | None:
        since = frame.get(body_c.ASLEEP_SINCE)
        if not since:
            return None
        night = local_date_of_night(since, frame.env.tz_of(frame.root), 5).isoformat()
        return None if night == state.digested_night else night

    def next_due(self, state: AttentionState, frame: Frame, last_run: int | None) -> int | None:
        if self._night(state, frame) is None:
            return None
        p = params(frame.env.params_of("attention", frame.root))
        return max(frame.now, frame.get(body_c.ASLEEP_SINCE) + p.digest_after_sleep_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: AttentionState = ctx.state
        night = self._night(state, frame)
        if night is None:
            return
        p = params(frame.env.params_of("attention", frame.root))
        items = []
        for t in frame.get(c.THOUGHTS):
            if frame.now - t.born_at < p.digest_min_age_us:
                continue  # trop récente pour être digérée cette nuit
            items.append(c.DigestedThought(
                thought=t.id, before=t.intensity, after=round(t.intensity * p.digest_factor, 4),
                emotion=DRIFT.get(t.emotion, t.emotion), reflective=t.intensity >= p.reflective_from,
                text_ref=t.text_ref, about=t.about, sensitivity=t.sensitivity))
        await ctx.emit(c.DIGESTED.draft(night=night, items=tuple(items), dedupe_key=f"digestion:{night}"))
