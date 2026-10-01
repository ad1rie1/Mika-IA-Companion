"""Les scénarios de M6 : ce qu'elle entreprend.

- **S09** une exploration : une inquiétude de sa propriétaire devient un but ;
  elle y avance seule, le mène à bout avec une preuve, en est fière, son
  estime monte — et elle le lui raconte quand il revient ;
- **S10** un but bloqué : elle prétend avoir fini sans rien faire — aucune
  fierté ; à bout de pas, elle bloque (frustration, estime en baisse, « Je
  bloque sur… ») et ne rouvre pas la même chose sous 24 h ;
- **S11** des rappels pendant son sommeil : l'ordinaire attend son réveil,
  l'urgent la réveille à l'heure puis elle se rendort ; un rappel que le
  modèle ne peut pas dire est retenté trois fois au plus, espacé ;
- **S16** un projet confié : elle écrit et teste un programme dans son
  atelier (isolé), un commit par pas, et le raconte à qui le lui a confié.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from typing import Any

from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.sim import expect
from mika.sim.inner import _asleep_at, _sleep_spans, until
from mika.sim.lane import PARIS, Plan, Result, at_paris, persona_llm
from mika.sim.rng import RngTree
from mika.sim.world import Driver


def _local(t: int) -> datetime:
    return datetime.fromtimestamp(t / US, PARIS)


def _of(events: list[Any], name: str) -> list[Any]:
    return [e for e in events if e.type.name == name]


def _steps_asleep(events: list[Any], end: int) -> list[str]:
    spans = _sleep_spans(events, end)
    return [_local(e.at).strftime("%a %H:%M") for e in _of(events, rt.EPISODE_STARTED.name)
            if e.data.kind == "STEP" and _asleep_at(spans, e.at)]


def _never_delivered(driver: Driver, events: list[Any]) -> list[str]:
    assert driver.transport is not None
    steps = {e.id for e in _of(events, rt.UTTERANCE.name) if e.data.kind == "STEP"}
    return [h.key for h in driver.transport.heard if h.key in steps]


def _shares(driver: Driver) -> list[tuple[str, str]]:
    return [(c.meta.get("target"), c.messages[-1].content) for c in driver.llm.calls  # type: ignore[attr-defined]
            if c.role == "initiative" and "MENÉ À BOUT" in c.messages[-1].content]


# ── S09 : une exploration ─────────────────────────────────────────────────


async def s09(driver: Driver, rng: RngTree, res: Result) -> None:
    driver.operators.add("user_1")
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 9 * HOUR)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", "j'ai peur, je stresse pour mon oral de demain")
    await driver.say("user_1", "bon, j'y vais, à ce soir")
    await driver.disconnect("user_1")
    assert driver.kernel is not None
    esteem_before = driver.kernel.mind.frame().get(self_c.ESTEEM)
    await until(driver, day0 + 13 * HOUR)
    esteem_after = driver.kernel.mind.frame().get(self_c.ESTEEM)
    await until(driver, day0 + 19 * HOUR)
    await driver.connect("user_1", "Adrien")  # il revient le soir
    await until(driver, day0 + 20 * HOUR)
    events = driver.read_events()
    thoughts = _of(events, "attention.thought_born")
    opened = [e for e in _of(events, goals_c.GOAL_OPENED.name) if e.data.source.startswith("thought:")]
    reports = [e for e in _of(events, goals_c.STEP_REPORTED.name) if opened and e.data.goal == opened[0].seq]
    closed = [e for e in _of(events, goals_c.GOAL_CLOSED.name) if opened and e.data.goal == opened[0].seq]
    shares = _shares(driver)
    to_him = [(who, text) for who, text in shares if who == "user_1"]
    said = [e for e in _of(events, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE" and e.data.target == "user_1"
            and _local(e.at).hour >= 19]
    res.metrics.update({"buts": [(e.data.kind, e.data.title.text) for e in _of(events, goals_c.GOAL_OPENED.name)],
                        "estime": [round(esteem_before, 3), round(esteem_after, 3)],
                        "récits": [who for who, _ in shares]})
    res.checks += [
        expect.control("une inquiétude devient un but", bool(thoughts) and bool(opened),
                       "ce qui la travaille, elle cherche à y voir clair", f"{res.metrics['buts']}"),
        expect.invariant("mené à bout avec une preuve", bool(closed) and closed[0].data.status == goals_c.ACHIEVED
                         and any(r.data.proven and r.data.tools for r in reports),
                         "« fini » ne se croit qu'avec un outil qui a produit quelque chose",
                         f"{[(r.data.verdict, r.data.tools) for r in reports]}"),
        expect.band("son estime monte", esteem_after - esteem_before, "mener quelque chose à bout redonne confiance",
                    lo=0.02),
        expect.invariant("raconté à qui ça concerne, quand il revient", bool(to_him) and bool(said)
                         and "Ce que tu en as tiré" in to_him[0][1],
                         "sa propriétaire, concernée : elle lui raconte tout, à son retour", f"{len(to_him)}"),
        expect.invariant("une séance n'est livrée à personne", not _never_delivered(driver, events),
                         "elle travaille pour elle seule"),
        expect.invariant("elle ne travaille pas en dormant", not _steps_asleep(events, driver.clock.now()),
                         "la nuit, elle dort", f"{_steps_asleep(events, driver.clock.now())}"),
    ]


# ── S10 : un but bloqué ───────────────────────────────────────────────────


async def s10(driver: Driver, rng: RngTree, res: Result) -> None:
    llm: Any = driver.llm
    llm.step_mode = "liar"
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 10 * HOUR)
    await driver.connect("user_2", "Bea")
    await driver.say("user_2", "j'angoisse pour l'opération de mon chat demain")
    await driver.disconnect("user_2")
    assert driver.kernel is not None
    before = driver.kernel.mind.frame().get(self_c.ESTEEM)
    await until(driver, day0 + 16 * HOUR)
    after = driver.kernel.mind.frame().get(self_c.ESTEEM)
    await until(driver, day0 + 19 * HOUR + 30 * MINUTE)
    await driver.connect("user_2", "Bea")  # elle revient, toujours inquiète
    await driver.say("user_2", "j'angoisse toujours pour mon chat, l'opération c'est demain matin")
    await driver.disconnect("user_2")
    await until(driver, day0 + DAY + 16 * HOUR)
    events = driver.read_events()
    reports = _of(events, goals_c.STEP_REPORTED.name)
    closed = _of(events, goals_c.GOAL_CLOSED.name)
    from_thought = [c for c in closed if c.data.source.startswith("thought:")]
    opened = _of(events, goals_c.GOAL_OPENED.name)
    blocked = [e for e in _of(events, "attention.thought_born") if e.data.origin == "blocked"]
    about_bea = [o for o in opened if "user_2" in o.data.about]
    first_block = next((c.at for c in closed if c.data.status == goals_c.STUCK), None)
    next_start = next((o.at for o in opened if first_block and o.at > first_block and o.data.authority == "self"),
                      None)
    pause_h = (next_start - first_block) / HOUR if first_block and next_start else None
    restated = [e for e in _of(events, "attention.thought_born") if "toujours" in (e.data.text.text or "")]
    res.metrics.update({"verdicts": [(r.data.verdict, r.data.proven) for r in reports],
                        "clos": [(c.data.status, c.data.reason) for c in closed],
                        "estime": [round(before, 3), round(after, 3)]})
    res.checks += [
        expect.invariant("« fini » sans preuve : aucune fierté",
                         not [c for c in closed if c.data.status == goals_c.ACHIEVED],
                         "dire qu'on a fini n'est pas avoir fini", f"{res.metrics['clos']}"),
        expect.control("elle prétendait avoir fini", any(v == "done" and not p for v, p in res.metrics["verdicts"]),
                       "sinon ce scénario ne dit rien", f"{res.metrics['verdicts']}"),
        expect.invariant("à bout de séances, elle bloque", bool(from_thought) and from_thought[0].data.status == goals_c.STUCK,
                         "un but qui n'avance pas finit par bloquer", f"{res.metrics['clos']}"),
        expect.band("son estime baisse", before - after, "bloquer lui coûte un peu", lo=0.01),
        expect.band("découragée, elle met du temps à se relancer", pause_h,
                    "après un échec, on n'entreprend pas aussitôt autre chose (heures)", lo=3.0),
        expect.invariant("« Je bloque sur… » lui reste en tête", bool(blocked) and all(
            "Je bloque sur" in (b.data.text.text or "") and b.data.emotion == "frustrated" for b in blocked),
            "la frustration a un objet", f"{[b.data.text.text for b in blocked]}"),
        expect.invariant("pas de réouverture sous 24 h", len(about_bea) == 1,
                         "l'inquiétude de Bea, redite le soir même, n'est pas une nouvelle affaire",
                         f"{[o.data.title.text for o in about_bea]}"),
        expect.control("elle l'a bien redite", bool(restated), "sinon la réouverture n'a pas été tentée"),
    ]


# ── S11 : des rappels pendant son sommeil ─────────────────────────────────


async def s11(driver: Driver, rng: RngTree, res: Result) -> None:
    llm: Any = driver.llm
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 21 * HOUR)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", "rappelle-moi à 3h de sortir le linge")
    await driver.say("user_1", "rappelle-moi à 3h30 de prendre mon médicament, c'est urgent")
    await driver.disconnect("user_1")
    await until(driver, day0 + DAY + 14 * HOUR)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", "rappelle-moi dans 20 minutes de rappeler Paul")
    llm.fail["initiative"] = 10  # le modèle ne répond plus pour prendre la parole
    await until(driver, day0 + DAY + 16 * HOUR)
    llm.fail["initiative"] = 0
    events = driver.read_events()
    said = {("linge" if "linge" in (e.data.text.text or "") else "médicament"): e.at
            for e in _of(events, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE"
            and "rappel" in (e.data.text.text or "")}
    wakes = [e.data.at for e in _of(events, body_c.WOKE.name) if _local(e.data.at).hour >= 5]
    sleeps = [e.data.at for e in _of(events, body_c.FELL_ASLEEP.name)]
    urgent = _local(said["médicament"]) if "médicament" in said else None
    tries = [e.at for e in _of(events, rt.EPISODE_STARTED.name) if e.data.kind == "INITIATIVE"
             and goals_c.REMIND in e.data.reason.split(",") and _local(e.at).day == 29 and _local(e.at).hour >= 14]
    gaps = [round((b - a) / MINUTE) for a, b in zip(tries, tries[1:], strict=False)]
    failed = [c for c in _of(events, goals_c.GOAL_CLOSED.name) if c.data.status == goals_c.FAILED]
    res.metrics.update({"rappels": {k: _local(v).strftime("%a %H:%M") for k, v in said.items()},
                        "réveils": [_local(t).strftime("%a %H:%M") for t in wakes],
                        "tentatives": [_local(t).strftime("%H:%M") for t in tries]})
    res.checks += [
        expect.invariant("l'urgent la réveille à l'heure", urgent is not None and urgent.hour == 3
                         and 30 <= urgent.minute < 45, "« c'est urgent » : même à 3 h 30", f"{res.metrics['rappels']}"),
        expect.invariant("puis elle se rendort", "médicament" in said and any(t > said["médicament"] for t in sleeps),
                         "réveillée pour ça, elle retourne dormir"),
        expect.invariant("l'ordinaire attend son réveil", "linge" in said and bool(wakes) and said["linge"] > wakes[0],
                         "sortir le linge ne vaut pas de la réveiller (ni de réveiller la personne)",
                         f"{res.metrics['rappels']}, réveil {res.metrics['réveils']}"),
        expect.invariant("en panne : trois tentatives au plus, espacées", len(tries) <= 3
                         and all(g >= 5 for g in gaps), "on n'insiste pas en boucle quand ça ne passe pas",
                         f"{res.metrics['tentatives']}"),
        expect.control("elle a bien essayé, puis renoncé", len(tries) == 3 and bool(failed),
                       "sinon la panne n'a rien éprouvé", f"{res.metrics['tentatives']}"),
    ]


# ── S16 : un projet confié ────────────────────────────────────────────────

CONFIDE = ("je te confie un projet : Un script de bonjour. Écrire bonjour.py avec une fonction bonjour(nom), "
           "et la tester.")


async def s16(driver: Driver, rng: RngTree, res: Result) -> None:
    driver.operators.add("user_1")
    day0 = at_paris(2026, 9, 28, 0, 0)
    await until(driver, day0 + 15 * HOUR)
    await driver.connect("user_1", "Adrien")
    await driver.say("user_1", CONFIDE)
    await until(driver, day0 + 17 * HOUR)
    events = driver.read_events()
    projects = [e for e in _of(events, goals_c.GOAL_OPENED.name) if e.data.kind == goals_c.PROJECT]
    closed = [e for e in _of(events, goals_c.GOAL_CLOSED.name) if projects and e.data.goal == projects[0].seq]
    ran = [m.content for c in driver.llm.calls if c.role == "step"  # type: ignore[attr-defined]
           for m in c.messages if m.role == "tool" and "python3" in m.content]
    isolated = shutil.which("bwrap") is not None
    log = ""
    if projects:
        folder = driver.root / "ateliers" / f"but-{projects[0].seq}"
        if (folder / ".git").exists():
            log = subprocess.run(["git", "-C", str(folder), "log", "--format=%s"], capture_output=True,
                                 text=True, check=False).stdout
    res.metrics.update({"projets": len(projects), "commits": log.splitlines(), "isolé": isolated})
    res.checks += [
        expect.invariant("un projet confié par sa propriétaire", len(projects) == 1
                         and projects[0].data.authority == goals_c.USER, "elle accepte le cadre qu'on lui confie"),
        expect.invariant("écrit et testé dans l'atelier", not isolated or (
            bool(closed) and closed[0].data.status == goals_c.ACHIEVED and any("code 0" in r for r in ran)),
            "le test a réellement tourné, isolé, avant qu'elle ne dise fini", f"{ran[-1:] if ran else ran}"),
        expect.invariant("un commit par séance qui a changé quelque chose", not isolated or (
            len(log.splitlines()) == 2 and log.splitlines()[-1] == "atelier ouvert"),
            "l'amorce, puis le travail", f"{log.splitlines()}"),
        expect.invariant("et elle le raconte à qui le lui a confié", not isolated or any(
            who == "user_1" for who, _ in _shares(driver)), "un travail confié se rend"),
    ]


GOALS: tuple[Plan, ...] = (
    Plan("S09 une exploration", s09, persona_llm, at_paris(2026, 9, 28, 8, 0)),
    Plan("S10 un but bloqué", s10, persona_llm, at_paris(2026, 9, 28, 9, 0)),
    Plan("S11 rappels pendant son sommeil", s11, persona_llm, at_paris(2026, 9, 28, 20, 0)),
    Plan("S16 un projet confié", s16, persona_llm, at_paris(2026, 9, 28, 14, 0)),
)
