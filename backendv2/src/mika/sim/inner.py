"""Les scénarios de M4 : sa vie intérieure.

- **S06** la journée vide : quelqu'un est là, connecté, mais ne dit rien de
  la journée. Elle prend la parole d'elle-même, un peu, étalé ; jamais la
  nuit ; elle s'ennuie ou se sent seule une partie de l'après-midi, sans
  jamais sombrer ; elle dort.
- **S07** une semaine type : trois personnes à leurs rythmes. Elle dort
  chaque nuit, ne parle jamais en dormant, ne dépasse jamais son budget
  d'initiatives, n'écrit jamais deux fois de suite à quelqu'un qui ne
  répond pas, ses pensées s'éteignent, elle ne s'enfonce jamais.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.sim import expect
from mika.sim.lane import PARIS, Plan, Result, at_paris, persona_llm
from mika.sim.rng import RngTree
from mika.sim.world import Driver
from mika.vocab import affect as A

DISTRESS_VALENCE, DISTRESS_INTENSITY = -0.35, 0.5


def _local(t: int) -> datetime:
    return datetime.fromtimestamp(t / US, PARIS)


async def until(driver: Driver, t: int) -> None:
    now = driver.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


def _sleep_spans(events: list[Any], end: int) -> list[tuple[int, int]]:
    spans, start = [], None
    for e in events:
        if e.type.name == body_c.FELL_ASLEEP.name:
            start = e.data.at
        elif e.type.name == body_c.WOKE.name and start is not None:
            spans.append((start, e.data.at))
            start = None
        elif e.type.name == rt.PERCEPTION_RECEIVED.name and start is not None and e.data.addressed:
            spans.append((start, e.at))  # réveillée par un message
            start = None
    if start is not None:
        spans.append((start, end))
    return spans


def _asleep_at(spans: list[tuple[int, int]], t: int) -> bool:
    return any(a <= t < b for a, b in spans)


def _initiatives(events: list[Any]) -> list[Any]:
    return [e for e in events if e.type.name == rt.UTTERANCE.name and e.data.kind == "INITIATIVE"]


async def _sample_mood(driver: Driver, until_t: int, every: int, out: list[tuple[int, Any]]) -> None:
    while driver.clock.now() < until_t:
        assert driver.kernel is not None
        out.append((driver.clock.now(), driver.kernel.mind.frame().get(affect_c.MOOD)))
        await asyncio.sleep(every / US)


def _distressed(m: affect_c.MoodReading) -> bool:
    return A.valence(m.felt) <= DISTRESS_VALENCE and m.felt_intensity >= DISTRESS_INTENSITY


# ── S06 : la journée vide ─────────────────────────────────────────────────


async def s06(driver: Driver, rng: RngTree, res: Result) -> None:
    await until(driver, at_paris(2026, 9, 28, 8, 0))
    await driver.connect("user_2", "Alice")  # là toute la journée, sans un mot
    end = at_paris(2026, 9, 29, 8, 0)
    samples: list[tuple[int, Any]] = []
    await _sample_mood(driver, end, 10 * MINUTE, samples)
    events = driver.read_events()
    said = [e for e in _initiatives(events) if "greeting" not in _reason_of(events, e)]
    spans = _sleep_spans(events, end)
    times = [e.at for e in said]
    gaps = [(b - a) / MINUTE for a, b in zip(times, times[1:], strict=False)]
    afternoon = [m for t, m in samples if 13 <= _local(t).hour < 18]
    empty = [m for m in afternoon if m.felt in (A.Emotion.BORED, A.Emotion.LONELY, A.Emotion.MELANCHOLIC)
             and m.felt_intensity >= 0.1]
    night = [t for t in times if _local(t).hour < 7 or _asleep_at(spans, t)]
    explored = [e for e in events if e.type.name == "goals.opened" and e.data.authority == "self"
                and 8 <= _local(e.at).hour < 22]
    res.metrics.update({"initiatives": len(said), "gaps_min": [round(g) for g in gaps],
                        "sleep": [(_local(a).strftime("%H:%M"), _local(b).strftime("%H:%M")) for a, b in spans],
                        "empty_afternoon": round(len(empty) / max(1, len(afternoon)), 2)})
    res.checks += [
        expect.band("quelques initiatives dans la journée", len(said),
                    "seule avec quelqu'un qui se tait, elle finit par parler — un peu", lo=1, hi=5),
        expect.invariant("étalées", all(g >= 60 for g in gaps),
                         "pas deux prises de parole à moins d'une heure quand personne ne répond",
                         f"écarts {[round(g) for g in gaps]} min"),
        expect.invariant("jamais la nuit ni en dormant", not night,
                         "elle ne parle pas en dormant", f"{[_local(t).strftime('%H:%M') for t in night]}"),
        expect.band("de l'ennui ou de la solitude l'après-midi", len(empty) / max(1, len(afternoon)),
                    "une journée vide se ressent", lo=0.2),
        expect.invariant("jamais de détresse", not any(_distressed(m) for _, m in samples),
                         "une journée vide n'est pas un drame"),
        expect.control("elle a dormi", any((b - a) >= 6 * HOUR for a, b in spans),
                       "la nuit, elle dort au moins six heures", f"{res.metrics['sleep']}"),
        expect.control("une activité pour elle-même", bool(explored),
                       "une journée vide, elle finit par s'occuper de ce qui l'intéresse",
                       f"{[e.data.title.text for e in explored]}"),
    ]


def _reason_of(events: list[Any], utterance: Any) -> str:
    started = [e for e in events if e.type.name == rt.EPISODE_STARTED.name and e.correlation == utterance.correlation]
    return started[0].data.reason if started else ""


# ── S07 : une semaine type ────────────────────────────────────────────────

ALICE = ["coucou Mika !", "j'ai eu une journée chargée au travail", "ce soir je me fais une soupe",
         "tu as fait quoi de beau aujourd'hui ?", "bon, bonne nuit !"]
BOB = ["salut", "je mange vite fait, t'as passé une bonne matinée ?", "allez, je retourne bosser"]
CHLOE = ["hello Mika", "tu connais un bon livre à me conseiller ?", "merci, je note !", "à bientôt"]


async def s07(driver: Driver, rng: RngTree, res: Result) -> None:
    r = rng.child("semaine").rng()
    driver.names.update({"tg_5": "Alice", "user_3": "Bob", "user_4": "Chloé"})
    day0 = at_paris(2026, 9, 28, 0, 0)
    samples: list[tuple[int, Any]] = []
    sampler = asyncio.ensure_future(_sample_mood(driver, day0 + 7 * DAY, 20 * MINUTE, samples))
    for d in range(7):
        weekday = d < 5
        if weekday:  # Bob, à midi, en semaine, sur l'application
            await until(driver, day0 + d * DAY + 12 * HOUR + r.randrange(0, 30) * MINUTE)
            await driver.connect("user_3", "Bob")
            for text in BOB:
                await driver.say("user_3", text)
                await asyncio.sleep(90)
            await driver.disconnect("user_3")
        if d % 3 == 1:  # Chloé, un après-midi sur trois
            await until(driver, day0 + d * DAY + 15 * HOUR + r.randrange(0, 60) * MINUTE)
            await driver.connect("user_4", "Chloé")
            for text in CHLOE:
                await driver.say("user_4", text)
                await asyncio.sleep(120)
            await driver.disconnect("user_4")
        if d not in (3, 4):  # Alice, tous les soirs par message — sauf jeudi et vendredi
            await until(driver, day0 + d * DAY + 20 * HOUR + r.randrange(0, 90) * MINUTE)
            for text in ALICE:
                await driver.say("tg_5", text)
                await asyncio.sleep(120)
    await until(driver, day0 + 7 * DAY)
    await sampler
    assert driver.kernel is not None
    end = driver.clock.now()
    events = driver.read_events()
    spans = _sleep_spans(events, end)
    said = _initiatives(events)
    per_day: dict[str, int] = {}
    for e in said:
        key = _local(e.at).strftime("%a")
        per_day[key] = per_day.get(key, 0) + 1
    asleep_speaking = [e for e in said if _asleep_at(spans, e.at)]
    double = _double_texts(events)
    nights = [(a, b) for a, b in spans if (b - a) >= 5 * HOUR]
    thoughts = [e for e in events if e.type.name == "attention.thought_born"]
    alive_old = [t for t in driver.kernel.mind.frame().get(attention_c.THOUGHTS) if end - t.born_at > 3 * DAY]
    res.metrics.update({"initiatives_par_jour": per_day, "nuits": len(nights), "pensées": len(thoughts),
                        "sommeil": [(_local(a).strftime("%a %H:%M"), round((b - a) / HOUR, 1)) for a, b in nights]})
    res.checks += [
        expect.invariant("elle dort chaque nuit", len(nights) >= 6,
                         "six nuits d'au moins cinq heures sur sept jours", f"{res.metrics['sommeil']}"),
        expect.invariant("elle ne parle jamais en dormant", not asleep_speaking,
                         "une initiative pendant son sommeil serait un robot", f"{len(asleep_speaking)}"),
        expect.invariant("jamais plus de cinq initiatives par jour", all(n <= 5 for n in per_day.values()),
                         "le plafond quotidien est une politique", f"{per_day}"),
        expect.invariant("jamais deux fois de suite sans réponse", not double,
                         "elle n'écrit pas deux fois à quelqu'un qui n'a pas répondu", f"{double[:3]}"),
        expect.invariant("ses pensées s'éteignent", not alive_old,
                         "une pensée de plus de trois jours ne trotte plus", f"{len(alive_old)}"),
        expect.invariant("elle ne s'enfonce jamais", not any(_distressed(m) for _, m in samples),
                         "une semaine ordinaire ne la met jamais en détresse"),
        expect.control("quand Alice se tait, elle prend de ses nouvelles", any(
            e.data.target == "tg_5" and _local(e.at).strftime("%a") in ("Thu", "Fri", "Sat") for e in said),
            "deux soirs sans son message habituel : elle s'en rend compte", f"{[(e.data.target, _local(e.at).strftime('%a %H:%M')) for e in said]}"),
    ]


def _double_texts(events: list[Any]) -> list[tuple[str, str]]:
    """Deux initiatives de suite vers la même personne, sans message d'elle entre les deux."""
    last: dict[str, str] = {}
    out = []
    for e in events:
        if e.type.name == rt.PERCEPTION_RECEIVED.name:
            last[e.data.handle] = "elle"
        elif e.type.name == rt.UTTERANCE.name and e.data.kind == "INITIATIVE" and e.data.target:
            if last.get(e.data.target) == "mika":
                out.append((e.data.target, _local(e.at).strftime("%a %H:%M")))
            last[e.data.target] = "mika"
    return out





# ── S08 : la nuit ─────────────────────────────────────────────────────────

GENTLE = ["coucou Mika", "ma journée s'est bien passée", "je regarde un film ce soir", "bonne nuit !"]
SAD = ["ça va pas trop ce soir", "je me suis disputée avec ma mère", "j'ai l'impression d'être nulle en tout",
       "je sais pas quoi faire"]


async def _chat(driver: Driver, handle: str, lines: list[str], gap_s: float = 90) -> None:
    for text in lines:
        await driver.say(handle, text)
        await asyncio.sleep(gap_s)


async def s08(driver: Driver, rng: RngTree, res: Result) -> None:
    llm: Any = driver.llm
    driver.names.update({"user_2": "Alice", "tg_5": "Bob"})
    day0 = at_paris(2026, 9, 28, 0, 0)
    # lundi : une soirée calme
    await until(driver, day0 + 18 * HOUR)
    await driver.connect("user_2", "Alice")
    await _chat(driver, "user_2", GENTLE)
    await driver.disconnect("user_2")
    # mardi : Bob le soir, puis le serveur redémarre à 22 h 50
    await until(driver, day0 + DAY + 20 * HOUR)
    await _chat(driver, "tg_5", GENTLE)
    await until(driver, day0 + DAY + 22 * HOUR + 50 * MINUTE)
    await driver.restart()
    # mercredi : une conversation jusqu'à 1 h 30
    await until(driver, day0 + 2 * DAY + 23 * HOUR)
    await driver.connect("user_2", "Alice")
    while driver.clock.now() < day0 + 3 * DAY + HOUR + 30 * MINUTE:
        await driver.say("user_2", "et sinon, tu penses à quoi là ?")
        await asyncio.sleep(10 * 60)
    await driver.disconnect("user_2")
    # jeudi : Bob le soir ; la première écriture du journal échouera
    await until(driver, day0 + 3 * DAY + 19 * HOUR)
    await _chat(driver, "tg_5", GENTLE)
    llm.fail["journal"] = 1
    # vendredi : une soirée triste avec Alice
    await until(driver, day0 + 4 * DAY + 21 * HOUR)
    await driver.connect("user_2", "Alice")
    await _chat(driver, "user_2", SAD, gap_s=120)
    await driver.disconnect("user_2")
    # samedi matin : elle revient
    await until(driver, day0 + 5 * DAY + 9 * HOUR)
    await driver.connect("user_2", "Alice")
    await driver.say("user_2", "bonjour Mika, bien dormi ?")
    await until(driver, day0 + 5 * DAY + 12 * HOUR)
    events = driver.read_events()
    end = driver.clock.now()
    spans = _sleep_spans(events, end)
    journals = [e for e in events if e.type.name == "self.journaled"]
    days: dict[str, int] = {}
    for e in journals:
        days[e.data.day] = days.get(e.data.day, 0) + 1
    expected = [f"2026-09-{d}" for d in (28, 29, 30)] + ["2026-10-01", "2026-10-02"]
    wednesday = [e for e in journals if e.data.day == "2026-09-30"]
    premature = [(e.data.day, _local(e.at).strftime("%a %H:%M")) for e in journals
                 if _local(e.at).date().isoformat() == e.data.day and _local(e.at).hour < 12]
    dreams: dict[str, int] = {}
    for e in events:
        if e.type.name == "self.dreamt":
            dreams[e.data.night] = dreams.get(e.data.night, 0) + 1
    digested = [e for e in events if e.type.name == "attention.digested"]
    friday = [i for e in digested if e.data.night == "2026-10-02" for i in e.data.items]
    reflective = [e for e in events if e.type.name == "memory.remembered" and "repensé cette nuit" in (e.data.text.text or "")]
    asleep_speaking = [e for e in _initiatives(events) if _asleep_at(spans, e.at)]
    morning = [r for r in llm.calls if r.role == "reply" and r.meta.get("target") == "user_2"
               and "bien dormi" in r.messages[-1].content]
    shown = morning[-1].messages[-1].content if morning else ""
    res.metrics.update({"journaux": days, "rêves": dreams, "digestions": len(digested),
                        "sommeil": [(_local(a).strftime("%a %H:%M"), round((b - a) / HOUR, 1)) for a, b in spans]})
    res.checks += [
        expect.invariant("un journal par journée vécue", all(days.get(d) == 1 for d in expected),
                         "chaque nuit, un journal — soirée calme, redémarrage, nuit courte ou panne",
                         f"{days}"),
        expect.invariant("une nuit qui commence après minuit appartient encore à la veille",
                         bool(wednesday) and _local(wednesday[0].at).day == 1 and 1 <= _local(wednesday[0].at).hour < 5,
                         "la conversation jusqu'à 1 h 30 : le journal du mercredi s'écrit dans la nuit de jeudi",
                         f"{[_local(e.at).strftime('%a %H:%M') for e in wednesday]}"),
        expect.invariant("jamais un journal avant que sa journée soit vécue", not premature,
                         "on écrit sa journée le soir, pas au petit matin du jour même", f"{premature}"),
        expect.invariant("au plus deux rêves par nuit", all(n <= 2 for n in dreams.values()), "des rêves, pas un film",
                         f"{dreams}"),
        expect.control("elle rêve", sum(dreams.values()) >= 1, "sinon ce scénario ne dit rien des rêves", f"{dreams}"),
        expect.invariant("elle ne parle jamais en dormant", not asleep_speaking, "la nuit, elle dort",
                         f"{len(asleep_speaking)}"),
        expect.invariant("la soirée triste se digère", bool(friday) and all(i.after < i.before for i in friday),
                         "une nuit allège ce qui pesait", f"{[(i.before, i.after, i.emotion) for i in friday]}"),
        expect.control("et laisse un souvenir de réflexion", bool(reflective),
                       "ce qui pesait encore la nuit devient « après y avoir repensé »", f"{len(reflective)}"),
        expect.invariant("le lendemain, son fil d'hier est là", "TON FIL D'HIER" in shown,
                         "elle sait ce qu'elle a vécu la veille", shown[:120]),
    ]


INNER: tuple[Plan, ...] = (
    Plan("S06 la journée vide", s06, persona_llm, at_paris(2026, 9, 28, 7, 30)),
    Plan("S07 une semaine type", s07, persona_llm, at_paris(2026, 9, 28, 0, 30), seeds=(1, 2)),
    Plan("S08 la nuit", s08, persona_llm, at_paris(2026, 9, 28, 9, 0)),
)
