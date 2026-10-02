"""Les processus des buts : en ouvrir d'elle-même, et clore ce qui doit l'être.

**Ouvrir** (éveillée, au plus deux explorations à elle à la fois) :
- une pensée qui insiste — une inquiétude, une peine, une croyance à
  réviser (pas la colère d'une insulte) — encore vive après une demi-heure
  devient une exploration : repenser à ce qu'on lui a confié, y voir plus
  clair sur ce qu'elle croyait, en savoir plus sur ce qu'elle a remarqué ;
- une curiosité qui la tient, en journée, lui fait fouiller un peu du côté
  d'un de ses centres d'intérêt (pas le même avant trois jours) quand elle a
  où chercher (ses flux) ; sans source, elle **rêvasse** autour : une rêverie
  se prouve en l'écrivant, et ne se raconte jamais comme une nouvelle (rien de
  neuf n'est arrivé). Le début de sa journée flotte un peu d'un jour à l'autre
  (une gigue tirée de la date : rejouable).
Le **titre** est le sien (« Repenser à ce qu'Adrien m'a confié ») ; ce qui l'a
fait naître (ses mots à lui, un titre d'article) est gardé à part et **cité**
au travail, jamais donné comme le but. Une exploration n'hérite de sa source
que la **lecture** (ses flux, la caméra) : jamais d'outil qui écrit ou envoie.
Ce qu'elle vient de clore ne se rouvre pas avant un jour (le même sujet :
une inquiétude redite par la même personne n'est pas une nouvelle affaire) ;
après un blocage, elle met six heures à entreprendre autre chose.

**Reprendre** : une attente nominative (« j'attends la réponse d'Adrien »)
se lève dès qu'Adrien écrit — enfin — sans attendre l'échéance.

**Clore** : un rappel dit (abouti) ou qui n'a pas pu l'être (échec) ; un but
à bout de pas, ou qui n'a rien conclu trois pas de suite (bloqué) ; une
exploration dont l'envie s'est usée (abandonnée), ou **devenue un projet**
(annulée, sans émotion : elle continue là-bas) ; un but dont le modèle ne
répond plus (échec, sans reproche). Un but suspendu par un opérateur est
figé : ni reprise d'attente, ni clôture, avant qu'il ne le reprenne.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import rss as rss_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.goals.faculty import (
    AWAITED,
    GOAL_PAUSED,
    GOAL_RESUMED,
    GOALS,
    Goal,
    GoalsState,
    budget,
    desire,
    live,
    params,
    ready_to_undertake,
    subject_key,
    workable,
)
from mika.faculties.goals.tools import closing
from mika.kernel.clock import instant, within_daily_window
from mika.kernel.codec import h64
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard

SEEDING_ORIGINS = frozenset({attention_c.EXCHANGE, attention_c.REVISION, attention_c.SIGNAL})
#: une inquiétude, une peine, un doute, une frustration (quelque chose qui ne marche pas) donnent envie
#: d'y voir clair ; une insulte (la colère, le dégoût), non
SEEDING_EMOTIONS = frozenset({"sad", "anxious", "scared", "confused", "lonely", "melancholic", "thinking",
                              "surprised", "curious", "nostalgic", "frustrated"})
#: une exploration peut devenir un projet à elle (``start_project``) quand elle s'avère plus grosse qu'une envie
EXPLORE_BUNDLES = ("goals", "memory", "projects")
#: ce qu'une exploration peut garder de sa source : la lecture (ses flux, la caméra), et la Forge pour réparer
#: une app (son écriture a son propre sas : une app qui a des secrets ou une promotion ne change qu'avec l'accord
#: d'un opérateur) — jamais un outil qui envoie (un brouillon de mail, les outils d'une app qui appellent ses
#: domaines)
READ_ONLY_SOURCES = frozenset({"rss", "camera", "forge"})
#: où elle peut aller chercher du neuf sur un de ses centres d'intérêt
INTEREST_SOURCES = ("rss",)
ORIGINS = {attention_c.EXCHANGE: c.FROM_EXCHANGE, attention_c.REVISION: c.FROM_REVISION,
           attention_c.SIGNAL: c.FROM_SIGNAL}
WHERE = {"rss": " dans mes flux", "email": " dans mon courrier", "camera": " à la caméra",
         "forge": " dans une de mes apps"}


def _busy(s: GoalsState, g: Goal) -> bool:
    return any(r.goal == g.id and r.purpose == "step" for r in s.running.values())


def _recently_closed(s: GoalsState, source: str, now: int, p: Any) -> bool:
    at = s.closed_sources.get(source)
    return at is not None and now - at < p.no_reopen_us


def _live_sources(s: GoalsState, now: int) -> set[str]:
    live_goals = [g for g in s.goals.values() if live(g, now) and g.source]
    return {g.source for g in live_goals} | {subject_key(g.source, g.about) for g in live_goals}


def _live_self(s: GoalsState, now: int) -> int:
    return sum(1 for g in s.goals.values() if live(g, now) and g.authority == c.SELF)


def jitter_min(frame: Frame, p: Any) -> int:
    """Le flottement du jour (minutes, dans ±``seed_jitter_min``), tiré de la date : le même jour donne toujours le
    même, un rejeu le retrouve."""
    span = p.seed_jitter_min
    if span <= 0:
        return 0
    return int(h64("début de journée", frame.local().date().isoformat()) % (2 * span + 1)) - span


def _day_start(frame: Frame, p: Any) -> int:
    return (p.seed_day_start_min + jitter_min(frame, p)) % (24 * 60)


def _daytime(frame: Frame, p: Any) -> bool:
    t = frame.local()
    return within_daily_window(t.hour * 60 + t.minute, _day_start(frame, p), p.seed_day_end_min)


def _day_opens(frame: Frame, p: Any) -> int | None:
    """L'instant où sa journée d'exploration s'ouvre aujourd'hui, s'il est encore à venir."""
    t = frame.local()
    start = _day_start(frame, p)
    opens = datetime(t.year, t.month, t.day, tzinfo=t.tzinfo) + timedelta(minutes=start)
    at = instant(opens)
    return at if at > frame.now else None


def _sources(frame: Frame) -> tuple[str, ...]:
    """Où elle peut aller chercher du neuf maintenant : ses flux, s'ils ont quelque chose."""
    try:
        headlines = frame.get(rss_c.HEADLINES)
    except KeyError:  # une composition sans flux
        headlines = ()
    return INTEREST_SOURCES if headlines else ()


def _name(frame: Frame, person: str | None) -> str:
    return frame.get(identity_c.IDENTITY(person)).name if person else ""


def explored_title(t: attention_c.ThoughtReading, name: str) -> str:
    """Le titre d'une exploration née d'une pensée : **ses** mots, jamais ceux qu'on lui a dits ou qu'elle a lus
    (ceux-là sont gardés à part, et cités)."""
    if t.origin == attention_c.SIGNAL:
        return "En savoir plus sur ce que j'ai remarqué" + WHERE.get(t.bundle, "")
    if t.origin == attention_c.REVISION:
        return "Y voir plus clair sur ce que je croyais"
    if t.about:
        return f"Repenser à ce que « {name} » m'a confié" if name else "Repenser à ce qu'on m'a confié"
    return "Repenser à ce qui me trotte dans la tête"


@GOALS.process("goals.seed", wake_on=[attention_c.THOUGHT_BORN, attention_c.DWELT, needs_c.FELT, *body_c.ALL,
                                      *c.ALL], lane="background", catch_up=CatchUp.ONCE, max_quantum_s=1800,
               priority=60)
class Seed:
    def _thoughts(self, s: GoalsState, frame: Frame, p: Any) -> list[attention_c.ThoughtReading]:
        busy = _live_sources(s, frame.now)
        return [t for t in frame.get(attention_c.THOUGHTS)
                if t.origin in SEEDING_ORIGINS and t.emotion in SEEDING_EMOTIONS and t.intensity >= p.seed_thought_from
                and not {f"thought:{t.id}", subject_key(f"thought:{t.id}", t.about)} & busy
                and not _recently_closed(s, subject_key(f"thought:{t.id}", t.about), frame.now, p)]

    def _interest(self, s: GoalsState, frame: Frame, p: Any, *, anytime: bool = False) -> str | None:
        if frame.get(needs_c.NEEDS).curiosity < p.seed_curiosity_from:
            return None
        if not anytime and not _daytime(frame, p):
            return None
        busy = _live_sources(s, frame.now)
        options = []
        for i, interest in enumerate(frame.get(self_c.PERSONA).interests):
            source = f"interest:{interest}"
            last = s.explored.get(source, 0)
            if source in busy or (last and frame.now - last < p.interest_rest_us):
                continue
            options.append((last, i, interest))
        return min(options)[2] if options else None

    def next_due(self, s: GoalsState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("goals", frame.root))
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or _live_self(s, frame.now) >= p.live_self_max:
            return None
        times = [t.born_at + p.seed_thought_age_us for t in self._thoughts(s, frame, p)]
        if self._interest(s, frame, p) is not None:
            times.append(frame.now)
        elif self._interest(s, frame, p, anytime=True) is not None and (opens := _day_opens(frame, p)):
            times.append(opens)  # sa journée s'ouvre plus tard : elle s'y mettra à ce moment-là
        if not times:
            return None
        return max(frame.now, min(times), ready_to_undertake(s, p))

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        s: GoalsState = ctx.state
        p = params(frame.env.params_of("goals", frame.root))
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or _live_self(s, frame.now) >= p.live_self_max:
            return
        if frame.now < ready_to_undertake(s, p):
            return  # une chose à la fois, et plus lentement après un échec
        store = ctx.ports.get("store")
        for t in self._thoughts(s, frame, p):
            if frame.now - t.born_at < p.seed_thought_age_us:
                continue
            text = store.content([t.text_ref]).get(t.text_ref) if store is not None and t.text_ref else None
            if not text:
                continue
            source = f"thought:{t.id}"
            bundles = tuple(sorted({*EXPLORE_BUNDLES, *({t.bundle} & READ_ONLY_SOURCES)}))
            owner = t.about[0] if t.about else None
            await ctx.emit(c.GOAL_OPENED.draft(
                kind=c.EXPLORATION, authority=c.SELF,
                title=Content.of(explored_title(t, _name(frame, owner)), level=t.sensitivity),
                details=Content.of(text, level=t.sensitivity), owner=owner, about=t.about, bundles=bundles,
                max_steps=p.exploration_steps, source=source, sensitivity=t.sensitivity,
                desire=round(min(1.0, 0.4 + t.intensity), 4), origin=ORIGINS.get(t.origin, t.origin),
                origin_at=t.born_at, dedupe_key=f"but:{source}"))
            return
        interest = self._interest(s, frame, p)
        if interest is None:
            return
        source = f"interest:{interest}"
        day = frame.local().date().isoformat()
        sources = _sources(frame)
        # avec ses flux, elle va voir ce qu'il y a de neuf ; sans, elle rêvasse (et rien ne se raconte comme une
        # nouvelle : il n'y a rien de nouveau)
        title = f"Fouiller un peu du côté de {lowered(short(interest))}" if sources else \
            f"Rêvasser un peu autour de {lowered(short(interest))}"
        await ctx.emit(c.GOAL_OPENED.draft(
            kind=c.EXPLORATION, authority=c.SELF, title=Content.of(title, level=0),
            details=Content.of(interest, level=0), bundles=tuple(sorted({*EXPLORE_BUNDLES, *sources})),
            max_steps=p.exploration_steps, source=source, sensitivity=0, origin=c.FROM_INTEREST, origin_at=frame.now,
            desire=round(min(1.0, frame.get(needs_c.NEEDS).curiosity), 4), dedupe_key=f"but:{source}:{day}"))


def short(interest: str) -> str:
    """Un centre d'intérêt en quelques mots (la persona les rédige en phrases)."""
    head = re.split(r" \(| — | - |, ", interest.strip(), maxsplit=1)[0].strip()
    return head[:80] or interest[:80]


def lowered(words: str) -> str:
    """« Les jeux rétro » au milieu d'une phrase : « les jeux rétro » (un nom propre garde sa majuscule)."""
    if len(words) > 1 and words[0].isupper() and words[1:2].islower():
        first = words.split(" ", 1)[0]
        if first.lower() in ("le", "la", "les", "l'", "un", "une", "des", "du", "de"):
            return words[0].lower() + words[1:]
    return words


def answered(s: GoalsState, frame: Frame) -> list[Goal]:
    """Les buts en attente nominative dont la personne a écrit depuis."""
    out = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if g.status != c.WAITING or g.paused_at or not g.wait_for or g.waiting_until <= frame.now:
            continue
        handles = frame.get(identity_c.HANDLES(g.wait_for)) or (g.wait_for,)
        if max(frame.get(transcript_c.LAST_FROM(h)) for h in handles) > g.waiting_since:
            out.append(g)
    return out


def closures(s: GoalsState, frame: Frame) -> list[tuple[Goal, str, str]]:
    """Ce qui doit se clore maintenant : (but, statut, raison). Un but suspendu
    est figé : rien ne le clôt (ni l'heure passée, ni l'envie) avant sa reprise."""
    p = params(frame.env.params_of("goals", frame.root))
    now = frame.now
    out: list[tuple[Goal, str, str]] = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if g.kind == c.PROJECT and live(g, now):  # même suspendu : il n'a plus de faculté pour le reprendre
            out.append((g, c.CANCELLED, "les projets ont désormais leur faculté à part (ADR 0031)"))
            continue
        if not workable(g, now):
            continue
        if g.kind == c.EXPLORATION and g.became and not _busy(s, g):  # elle continue là-bas, sans émotion
            out.append((g, c.CANCELLED, f"devenue un projet (n° {g.became})"))
            continue
        if g.kind == c.REMINDER:
            if g.delivered:
                out.append((g, c.ACHIEVED, "rappel dit"))
            elif g.attempts >= p.remind_attempts:
                out.append((g, c.FAILED, f"pas pu le dire ({g.attempts} tentatives)"))
            elif g.due is not None and now - g.due > p.remind_too_late_us:
                out.append((g, c.FAILED, "trop tard pour le dire"))
            continue
        if _busy(s, g):
            continue
        if g.failures >= p.failures_before_failed:
            out.append((g, c.FAILED, "le modèle ne répond pas"))
        elif g.silent >= p.silent_before_blocked:
            out.append((g, c.STUCK, f"{g.silent} séances de suite sans rien conclure"))
        elif g.steps >= budget(g, p):
            out.append((g, c.STUCK, "à bout de séances sans en venir à bout"))
        elif g.kind == c.EXPLORATION and desire(g, now, p) < p.abandon_below:
            out.append((g, c.ABANDONED, "l'envie s'est usée"))
    return out


def _worn_out_at(g: Goal, p: Any) -> int | None:
    """L'instant où l'envie d'une exploration passe sous le seuil d'abandon."""
    if g.kind != c.EXPLORATION or g.desire <= p.abandon_below:
        return None if g.kind != c.EXPLORATION else g.desire_at
    return g.desire_at + math.ceil(p.desire_half_life_us * math.log2(g.desire / p.abandon_below))


@GOALS.process("goals.tend", wake_on=[*c.ALL, GOAL_PAUSED, GOAL_RESUMED, rt.EPISODE_STARTED, rt.EPISODE_ENDED,
                                      rt.UTTERANCE, rt.PERCEPTION_RECEIVED], lane="background",
               catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=40)
class Tend:
    def next_due(self, s: GoalsState, frame: Frame, last_run: int | None) -> int | None:
        if closures(s, frame) or answered(s, frame):
            return frame.now
        p = params(frame.env.params_of("goals", frame.root))
        times = []
        for g in s.goals.values():
            if not workable(g, frame.now):
                continue
            worn = _worn_out_at(g, p)
            if worn is not None:
                times.append(worn)
            if g.kind == c.REMINDER and g.due is not None and not g.delivered:
                times.append(g.due + p.remind_too_late_us + 1)
        return max(frame.now, min(times)) if times else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        released = [AWAITED.draft(goal=g.id, person=g.wait_for or "", dedupe_key=f"attente:{g.id}:{g.waiting_since}")
                    for g in answered(ctx.state, frame)]
        if released:
            await ctx.emit(*released)
            frame = ctx.frame
        todo = closures(ctx.frame.state("goals"), frame)
        if not todo:
            return
        drafts = [closing(ctx, g, status, reason=reason) for g, status, reason in todo]
        drafts = [replace(d, dedupe_key=f"clôture:{d.data.goal}") for d in drafts]
        # un ancien projet se clôt même suspendu ; les autres, tant qu'ils sont actifs ou en attente
        live_now = tuple((g.id, c.LIVE_STATUSES if g.kind == c.PROJECT else (c.ACTIVE, c.WAITING))
                         for g, _, _ in todo)
        await ctx.emit(*drafts, guard=Guard("buts vivants", predicate=lambda view, ids=live_now: all(
            view.get(c.STATUS(i)) in allowed for i, allowed in ids)))
