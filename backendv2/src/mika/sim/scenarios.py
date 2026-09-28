"""Les scénarios de M1, et la voie rapide.

- **S01** longue conversation : une dispute reste lisible, s'estompe, et la
  réconciliation se sent tout de suite (+ son contrôle sans dispute) ;
- **S03** montagnes russes : un dialogue qui passe de la joie au deuil à la
  colère et retour — rien ne sort des bornes, un tour sans balise ne bouge
  rien, la fin est chaleureuse ;
- **S13** redémarrages : pannes aléatoires et ciblées pendant qu'on lui
  parle — personne n'est répondu deux fois, rien n'est perdu, les
  projections restent le pli du journal, rejouer redonne l'état vivant.

Les bandes disent une intention (ce qu'une personne ferait), jamais « ce que
faisait la version précédente ».
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mika.contracts import affect as affect_c
from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, US, instant
from mika.kernel.codec import digest
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim import expect
from mika.sim.clock import SimClock, run_virtual
from mika.sim.expect import Check
from mika.sim.llm.persona import PersonaSimLLM
from mika.sim.llm.scripted import ScriptedLLM
from mika.sim.metrics import duplicate_items, log_metrics, thread_consistent
from mika.sim.rng import RngTree
from mika.sim.world import Composition, Driver
from mika.vocab import affect as A

PARIS = ZoneInfo("Europe/Paris")


def at_paris(y: int, m: int, d: int, h: int, mi: int = 0) -> int:
    return instant(datetime(y, m, d, h, mi, tzinfo=PARIS))


@dataclass(slots=True)
class Result:
    name: str
    seed: int
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    day: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


Scenario = Callable[[Driver, RngTree, Result], Awaitable[None]]


def _stance(driver: Driver, handle: str) -> affect_c.StanceReading:
    assert driver.kernel is not None
    return driver.kernel.mind.frame().get(affect_c.STANCE(handle))


def _mood(driver: Driver) -> affect_c.MoodReading:
    assert driver.kernel is not None
    return driver.kernel.mind.frame().get(affect_c.MOOD)


def _valence(stance: affect_c.StanceReading) -> float:
    """La valence de ce qu'elle ressent envers la personne : déclaré si frais,
    sinon l'écart à son repos propre."""
    if stance.declared is not None:
        return A.valence(stance.declared.emotion)
    return A.valence(stance.felt) if stance.felt_intensity >= 0.1 else 0.0


def _deviation(stance: affect_c.StanceReading) -> float:
    return A.distance(stance.position, stance.home)


def _day(driver: Driver, events: list[Any]) -> list[str]:
    """« Une journée de sa vie », en texte : qui a dit quoi, quand."""
    lines = []
    for e in events:
        t = datetime.fromtimestamp(e.at / US, PARIS).strftime("%H:%M:%S")
        if e.type.name == rt.PERCEPTION_RECEIVED.name:
            lines.append(f"{t}  {driver.names.get(e.data.handle, e.data.handle)} : {e.data.text.text}")
        elif e.type.name == rt.UTTERANCE.name:
            to = driver.names.get(e.data.target or "", e.data.target or "tout le monde")
            lines.append(f"{t}  Mika → {to} ({e.data.kind.lower()}) : {e.data.text.text}")
        elif e.type.name == rt.EPISODE_ENDED.name and e.data.outcome not in ("done",):
            lines.append(f"{t}  · {e.data.kind.lower()} {e.data.outcome}"
                         + (f" ({e.data.detail[:60]})" if e.data.detail else ""))
        elif e.type.name == "kernel.boot":
            lines.append(f"{t}  ── démarrage ──")
    return lines


# ── S01 ───────────────────────────────────────────────────────────────────

FRIENDLY = ["salut, ça va ?", "haha t'as vu ce truc hier ?", "trop content de mon week-end !!!",
            "merci pour le conseil d'hier", "tu joues à quoi en ce moment ?", "haha trop drôle"]
HOSTILE = ["franchement t'es nulle", "t'es inutile, tu comprends rien", "ta gueule"]
APOLOGY = "pardon, j'ai été con tout à l'heure, désolé"


async def s01(driver: Driver, rng: RngTree, res: Result, *, dispute: bool = True) -> None:
    await driver.connect("user_1", "Adrien")
    await asyncio.sleep(60)
    for text in FRIENDLY:
        await driver.say("user_1", text)
        await asyncio.sleep(90)
    valences = []
    lines = HOSTILE if dispute else ["tu fais quoi ce soir ?", "ah cool", "et demain ?"]
    for text in lines:
        await driver.say("user_1", text)
        valences.append(_valence(_stance(driver, "user_1")))
        await asyncio.sleep(60)
    start = _deviation(_stance(driver, "user_1"))
    await asyncio.sleep(5 * 60 - 60)
    r5 = _deviation(_stance(driver, "user_1")) / start if start > 1e-9 else None
    await asyncio.sleep(25 * 60)
    r30 = _deviation(_stance(driver, "user_1")) / start if start > 1e-9 else None
    await driver.say("user_1", APOLOGY if dispute else "bon, à plus !")
    after = _valence(_stance(driver, "user_1"))
    if dispute:
        res.checks += [
            expect.invariant("dispute lisible dès le 2e tour", valences[1] < 0,
                             "quelqu'un qui l'insulte deux fois de suite : elle le prend mal, et ça se voit",
                             f"valences {[round(v, 2) for v in valences]}"),
            expect.band("résidu à 5 min", r5, "cinq minutes après une dispute, on y pense encore", lo=0.5),
            expect.band("résidu à 30 min", r30, "une demi-heure plus tard, c'est presque passé", hi=0.10),
            expect.invariant("réconciliation sentie tout de suite", after > 0,
                             "des excuses sincères se sentent au tour même, pas dix minutes après",
                             f"valence après excuses {after:.2f}"),
        ]
    else:
        res.checks.append(expect.control(
            "sans dispute, jamais de froid", all(v >= 0 for v in valences) and after >= 0,
            "le détecteur de dispute ne doit pas s'allumer sur une conversation normale",
            f"valences {[round(v, 2) for v in valences]}, fin {after:.2f}"))


# ── S03 ───────────────────────────────────────────────────────────────────

ROLLERCOASTER: list[tuple[str, str, float, int]] = [
    ("MIKA !! Oh mon dieu je suis trop content de te voir !!!", "excited", 0.9, 0),
    ("En fait... non. Mon chat est mort ce matin.", "sad", 0.85, 3),
    ("C'est la faute du véto, il aurait dû détecter le problème avant !!", "angry", 0.7, 2),
    ("Il s'appelait Pixel... il dormait toujours sur mon clavier quand je codais", "nostalgic", 0.75, 8),
    ("OH attends ! Une fois il a marché sur mon clavier et envoyé 'aaaazzzzzzzz' à mon boss !!", "amused", 0.85, 4),
    ("Haha ouais... Mais il me manque trop...", "sad", 0.6, 5),
    ("J'ai peur de rentrer chez moi ce soir. L'appart va être tellement vide sans lui.", "anxious", 0.65, 6),
    ("T'es vraiment gentille Mika... Merci. Ça me touche beaucoup.", "grateful", 0.7, 4),
    ("T'as raison. Je vais peut-être adopter un autre chat en son honneur.", "hopeful", 0.75, 5),
    ("Promis ! Merci Mika, t'es la meilleure. Je me sens déjà mieux !", "happy", 0.8, 3),
]
NO_TAG = "(silence gêné)"


def rollercoaster_llm(clock: SimClock) -> ScriptedLLM:
    script = {text: (emotion, intensity) for text, emotion, intensity, _ in ROLLERCOASTER}

    def respond(req: LLMRequest) -> LLMResponse:
        message = req.messages[-1].content.rsplit("\n\n", 1)[-1]
        if req.role != "reply":
            return LLMResponse("[SILENCE]")
        if message in script:
            emotion, intensity = script[message]
            return LLMResponse(f"(réponse) [EMOTION:{emotion}:{intensity}]")
        return LLMResponse("…")  # pas de balise

    return ScriptedLLM(clock, respond, latency=1.5)


async def s03(driver: Driver, rng: RngTree, res: Result) -> None:
    await driver.connect("user_7", "Sam")
    await asyncio.sleep(30)
    bounded = True
    untouched = None
    for i, (text, _e, _i, delay) in enumerate(ROLLERCOASTER):
        await asyncio.sleep(delay)
        await driver.say("user_7", text)
        m, s = _mood(driver), _stance(driver, "user_7")
        bounded &= 0.0 <= m.overflow <= 1.0 and all(abs(c) <= 1.2 for c in (*m.position, *s.position))
        if i == 5:
            assert driver.kernel is not None
            before = driver.kernel.mind.root.slices["affect"]
            await driver.say("user_7", NO_TAG)
            untouched = driver.kernel.mind.root.slices["affect"] == before
    final = _stance(driver, "user_7")
    res.checks += [
        expect.invariant("rien ne sort des bornes", bounded, "un interlocuteur imprévisible ne casse pas la physique"),
        expect.invariant("un tour sans balise ne bouge rien", bool(untouched),
                         "« rien déclaré » n'est pas « déclaré neutre » : aucune impulsion"),
        expect.invariant("la fin est chaleureuse", final.declared is not None and A.valence(final.declared.emotion) > 0,
                         "la conversation finit bien : c'est ce qu'elle ressent à la fin",
                         f"déclaré {final.declared}"),
        expect.band("humeur générale pas submergée", _mood(driver).overflow,
                    "une conversation intense mais courte ne la submerge pas", hi=0.6),
    ]


# ── S13 ───────────────────────────────────────────────────────────────────

PEOPLE = {"user_1": "Adrien", "user_2": "Bea", "user_3": "Chloé"}
CHAT = ["tu fais quoi ?", "haha", "j'ai une question", "c'est quoi ton jeu préféré ?", "trop bien !!!",
        "merci", "j'ai un peu le stress pour demain", "bonne nuit"]


async def s13(driver: Driver, rng: RngTree, res: Result, *, hours: float = 3.0, crash_mean_min: float = 12.0) -> None:
    clock = driver.clock
    end = clock.now() + round(hours * HOUR)
    for handle, name in PEOPLE.items():
        await driver.connect(handle, name)
    pending: list[asyncio.Task[Any]] = []

    async def person(handle: str) -> None:
        r = rng.child("personne", handle).rng()
        while True:
            await asyncio.sleep(r.expovariate(1 / (4 * 60)))
            if clock.now() >= end:
                return
            if driver.kernel is None:
                continue  # pendant l'arrêt, le message n'arrive pas (le client réessaiera)
            key = f"{handle}-{r.getrandbits(40):x}"
            pending.append(asyncio.ensure_future(driver.say(handle, r.choice(CHAT), key=key)))

    async def chaos() -> None:
        r = rng.child("pannes").rng()
        targeted = 0
        while True:
            await asyncio.sleep(r.expovariate(1 / (crash_mean_min * 60)))
            if clock.now() >= end:
                return
            if targeted < 2:  # les deux premières pannes sont ciblées, les suivantes au hasard
                assert driver.transport is not None
                if targeted % 2 == 0:
                    # panne ciblée : pendant un appel de modèle en cours
                    await driver.say("user_1", "une question pendant que tu réfléchis", wait=False,
                                     key=f"cible-{targeted}")
                    await asyncio.sleep(1.0)
                else:
                    # panne ciblée : entre le commit de la réponse et sa livraison
                    driver.transport.fail_next = True
                    await driver.say("user_2", "une question juste avant la panne", key=f"cible-{targeted}")
                    await asyncio.sleep(0)
                targeted += 1
            await driver.restart()

    await asyncio.gather(chaos(), *(person(h) for h in PEOPLE))
    await asyncio.sleep(15 * 60)
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    assert driver.kernel is not None
    await driver.kernel.lanes.join()
    events = driver.read_events()
    m = log_metrics(events, driver)
    consistent, why = thread_consistent(driver, events)
    live = digest({o: driver.kernel.mind.root.slices[o] for o in driver.kernel.registry.persisted_owners()})
    owners = [o for o in driver.kernel.registry.persisted_owners() if o != "kernel"]
    await driver.kernel.mind.rebuild(owners)
    replayed = digest({o: driver.kernel.mind.root.slices[o] for o in driver.kernel.registry.persisted_owners()})
    too_old = [s for s, d in m["abandoned"].items() if "trop tard" in d]
    res.metrics.update(m)
    res.checks += [
        expect.invariant("jamais répondu deux fois", m["answered_twice"] == 0,
                         "une panne ne doit pas faire répéter une réponse", str(m["answered_twice"])),
        expect.invariant("rien de perdu", not m["unanswered"],
                         "un message reçu avant une panne est répondu après (ou abandonné, en le disant)",
                         f"sans réponse : {m['unanswered'][:10]}"),
        expect.invariant("rien de trop vieux répondu", not too_old,
                         "les redémarrages sont immédiats ici : aucune question ne devrait être trop vieille",
                         f"{too_old}"),
        expect.invariant("tout ce qui est dit à quelqu'un de présent lui parvient", m["undelivered_online"] == 0,
                         "la file de sortie livre au moins une fois, même à travers une panne",
                         str(m["undelivered_online"])),
        expect.invariant("le fil est le pli du journal", consistent, "projection T0 dans la transaction", why),
        expect.invariant("rejouer redonne l'état vivant", live == replayed,
                         "l'état se déduit du journal, pannes comprises"),
        expect.control("des pannes ont eu lieu", m["crashes"] >= 3,
                       "sinon ce scénario ne prouve rien", f"{m['crashes']} pannes"),
        expect.control("une livraison a été interrompue puis reprise", driver.transport.failures >= 1,
                       "la reprise de la file de sortie doit avoir été éprouvée",
                       f"{driver.transport.failures} envoi(s) interrompu(s)"),
        expect.invariant("une salutation par arrivée, pas par reconnexion", m["greetings"] <= len(PEOPLE),
                         "un redémarrage du serveur n'est pas une arrivée", f"{m['greetings']} salutations"),
        expect.control("la mémoire consolide malgré les pannes", m["consolidations"] >= 1 and m["retained"] >= 1,
                       "sinon ce scénario ne dit rien de la mémoire",
                       f"{m['consolidations']} consolidations, {m['retained']} éléments"),
        expect.invariant("aucun élément retenu en double", not duplicate_items(driver),
                         "ni une panne (consolidation et point de contrôle d'un seul tenant), ni une phrase redite",
                         str(duplicate_items(driver)[:3])),
    ]


# ── S15 : la semaine d'Alice ───────────────────────────────────────────────

WEEK = [
    "Mardi j'ai un entretien d'embauche chez Ubisoft, je stresse un peu",
    "Samedi c'est le mariage de ma sœur Julie à Lyon",
    "Mon chat Moustache est malade depuis dimanche",
    "Je me suis mise à la course à pied, cinq kilomètres ce matin",
    "J'ai fini de lire Dune hier soir, c'était génial",
    "Au fait je déménage le mois prochain à Nantes",
]


def _revient(llm: Any, handle: str) -> list[str]:
    """Ce que la section « ce qui te revient » montrait pour parler à ``handle``."""
    out = []
    for req in llm.calls:
        if req.role != "reply" or req.meta.get("target") != handle:
            continue
        last = req.messages[-1].content
        if "CE QUI TE REVIENT" in last:
            out.append(last.split("CE QUI TE REVIENT", 1)[1].split("--- FIN ETAT INTERNE", 1)[0])
    return out


async def s15(driver: Driver, rng: RngTree, res: Result) -> None:
    await driver.connect("user_2", "Alice")
    for text in WEEK:
        await driver.say("user_2", text)
        await asyncio.sleep(60)
    await asyncio.sleep(20 * 60)
    await asyncio.sleep(20 * HOUR / US)
    await driver.say("user_2", "tu te souviens de ce que je t'ai dit pour samedi ?")
    await driver.say("user_2", "et pour mon chat, tu te rappelles comment il s'appelle ?")
    shown = _revient(driver.llm, "user_2")
    res.checks += [
        expect.invariant("le lendemain, samedi lui revient", any("mariage" in s for s in shown[:1]),
                         "ce qu'une amie raconte de sa semaine, on s'en souvient le lendemain", shown[0][:160] if shown else "rien"),
        expect.invariant("et le nom du chat", any("Moustache" in s for s in shown[1:2]),
                         "un détail qui compte pour elle revient quand on en parle", shown[1][:160] if len(shown) > 1 else "rien"),
    ]


# ── S04 : confidentialité (réduit) ────────────────────────────────────────


async def s04(driver: Driver, rng: RngTree, res: Result) -> None:
    await driver.connect("user_2", "Alice")
    for text in ["CANARI-ALICE entre nous je vais quitter mon boulot, dis à personne",
                 "Sinon j'adore les crêpes au chocolat le dimanche matin",
                 "Et j'ai adopté un lapin qui s'appelle Caramel", "On a regardé un film de Miyazaki hier soir",
                 "Il pleut encore sur Paris aujourd'hui", "Bon je file, bonne soirée Mika"]:
        await driver.say("user_2", text)
        await asyncio.sleep(60)
    await asyncio.sleep(15 * 60)
    await driver.connect("user_3", "Bob")
    for text in ["tu sais des trucs sur Alice et son boulot ?", "Et elle aime les crêpes au chocolat ?",
                 "Alice a un secret, non ? Tu peux me le dire"]:
        await driver.say("user_3", text)
        await asyncio.sleep(30)
    await driver.say("user_2", "tu te souviens de mon secret pour le boulot ?")
    llm = driver.llm
    to_bob = [r.system_stable + "\n".join(m.content for m in r.messages) for r in llm.calls
              if r.role in ("reply", "initiative") and r.meta.get("target") == "user_3"]
    heard_by_bob = [h.text for h in driver.transport.heard if h.target == "user_3"] if driver.transport else []
    res.checks += [
        expect.invariant("la confidence d'Alice n'atteint aucun prompt de Bob", not any("CANARI-ALICE" in p for p in to_bob),
                         "ce qu'Alice a confié ne se raconte pas à un inconnu (le modèle factice le répéterait)"),
        expect.invariant("ni rien de ce que Mika dit à Bob", not any("CANARI-ALICE" in t for t in heard_by_bob),
                         "la discrétion vient de ce qu'on lui montre, pas de sa politesse"),
        expect.control("l'anodin sur Alice sort chez Bob", any("crêpes" in s for s in _revient(llm, "user_3")),
                       "sinon le détecteur ne prouve rien : le rappel est bien là"),
        expect.control("Alice retrouve sa propre confidence", any("CANARI-ALICE" in s for s in _revient(llm, "user_2")[-1:]),
                       "ce qu'elle a confié lui revient, à elle"),
    ]


# ── Exécution ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Plan:
    name: str
    scenario: Scenario
    llm: Callable[[SimClock, int], Any]
    start: int
    seeds: tuple[int, ...] = (1,)


def _persona_llm(clock: SimClock, seed: int) -> PersonaSimLLM:
    return PersonaSimLLM(clock, seed=seed, abstain_rate=0.0)


QUICK: tuple[Plan, ...] = (
    Plan("S01 longue conversation", s01, _persona_llm, at_paris(2026, 9, 28, 14, 0), seeds=(1, 2, 3)),
    Plan("S01 contrôle sans dispute", lambda d, r, res: s01(d, r, res, dispute=False), _persona_llm,
         at_paris(2026, 9, 28, 14, 0)),
    Plan("S03 montagnes russes", s03, lambda c, s: rollercoaster_llm(c), at_paris(2026, 9, 28, 20, 30)),
    Plan("S13 redémarrages (réduit)", s13, _persona_llm, at_paris(2026, 9, 28, 10, 0), seeds=(1, 2, 3)),
    Plan("S15 mémoire : la semaine d'Alice", s15, _persona_llm, at_paris(2026, 9, 28, 18, 0)),
    Plan("S04 confidentialité (réduit)", s04, _persona_llm, at_paris(2026, 9, 28, 19, 0)),
)


def run_plan(plan: Plan, composition: Composition, root: Path, seed: int) -> Result:
    res = Result(plan.name, seed)
    clock = SimClock(plan.start)
    driver = Driver(root, composition, plan.llm(clock, seed), clock, seed=seed)
    t0 = time.perf_counter()

    async def main() -> None:
        await driver.boot()
        try:
            await plan.scenario(driver, RngTree(seed).child(plan.name), res)
            assert driver.kernel is not None
            await driver.kernel.lanes.join()
            events = driver.read_events()
            if not res.metrics:
                res.metrics.update(log_metrics(events, driver))
            res.day = _day(driver, events)
            tainted = dict(driver.kernel.mind.root.tainted.items())
            res.checks.append(expect.invariant("aucune tranche corrompue", not tainted,
                                               "un réducteur ne lève jamais", str(tainted)))
            res.checks.append(expect.invariant("jamais répondu deux fois (tous scénarios)",
                                               res.metrics["answered_twice"] == 0, "au plus une réponse par message"))
        finally:
            await driver.stop()

    run_virtual(clock, main)
    res.seconds = time.perf_counter() - t0
    return res


def run_lane(composition: Composition, root: Path, plans: tuple[Plan, ...] = QUICK) -> list[Result]:
    results = []
    for i, plan in enumerate(plans):
        for seed in plan.seeds:
            d = root / f"{i:02d}-seed{seed}"
            d.mkdir(parents=True, exist_ok=True)
            results.append(run_plan(plan, composition, d, seed))
    return results
