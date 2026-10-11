"""Chaque chemin de la matrice de personnalité, vécu par le vrai noyau (ADR 0100).

``test_temperament_matrix.py`` vérifie ce que chaque curseur dérive. Ici, chaque chemin est suivi de bout en bout :
la persona porte un tempérament, la configuration journalise les paramètres qu'il dérive, et la vie de Mika s'en
ressent. Chaque test fait vivre la même scène sous deux ou trois tempéraments contrastés (le curseur en bas, au
milieu, en haut, ou un archétype), et compare ce qui s'observe :

- ce que les mêmes mots font à son humeur, à sa posture, à ce qu'une relation installe ;
- son visage, ce qui la pousse à parler, ses pensées, son estime, son énergie ;
- ce qui se dit au modèle ;
- les paramètres réellement en vigueur, faculté par faculté.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mika.app.cli import _with_settings, profile_command
from mika.app.composition import faculties
from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import needs as needs_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.affect import overflow_evidence
from mika.kernel import forms
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Origin
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import affect as A
from mika.vocab import temperament as T
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import AFTERNOON, DOC, at_paris, befriend, boot, build, connect, said


class Voice:
    """Le modèle factice : il répond avec la balise d'émotion et la lecture de la personne qu'on lui dicte (un texte
    qui change à chaque fois : une redite ne part pas), et garde ce qu'on lui a montré."""

    def __init__(self) -> None:
        self.tag = ""
        self.their = ""
        self.n = 0
        self.prompts: list[str] = []

    def __call__(self, req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return LLMResponse("[SILENCE]")
        self.n += 1
        self.prompts.append(req.system_stable + "\n".join(m.content for m in req.messages))
        return LLMResponse(f"réponse numéro {self.n} {self.tag} {self.their}".strip())


def live(tmp: Path, temperament: T.Temperament, scenario, *, start: int = AFTERNOON):  # type: ignore[no-untyped-def]
    voice = Voice()
    kernel, clock, _llm, _out = build(tmp, voice, start=start)
    doc = DOC.model_copy(update={"temperament": temperament})

    async def main():  # type: ignore[no-untyped-def]
        await boot(kernel, doc)
        try:
            return await scenario(kernel, voice)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def each(tmp_path: Path, temperaments: dict[str, T.Temperament], scenario, **kw) -> dict:  # type: ignore[no-untyped-def]
    """La même scène sous chaque tempérament, chacune dans sa propre vie."""
    out = {}
    for name, t in temperaments.items():
        d = tmp_path / name
        d.mkdir(parents=True)
        out[name] = live(d, t, scenario, **kw)
    return out


def extremes(slider: str) -> dict[str, T.Temperament]:
    """Le curseur au plus bas et au plus haut que la console permet, et au milieu."""
    return {"bas": T.Temperament(**{slider: T.LOWEST}), "milieu": T.Temperament(),
            "haut": T.Temperament(**{slider: T.HIGHEST})}


def profile(key: str) -> T.Temperament:
    return T.apply_profile(T.Temperament(), key)


async def say(kernel, voice: Voice, handle: str, tag: str = "", their: str = "", text: str = "") -> None:  # type: ignore[no-untyped-def]
    voice.tag, voice.their = tag, their
    p = await kernel.perceive(said(handle, text or f"message {voice.n + 1} de {handle}"))
    await p.reply


async def wait(seconds: float) -> None:
    await asyncio.sleep(seconds)


def fact(kernel, key):  # type: ignore[no-untyped-def]
    return kernel.mind.frame().get(key)


def in_force(kernel, owner: str):  # type: ignore[no-untyped-def]
    """Les paramètres journalisés en vigueur pour cette faculté."""
    frame = kernel.mind.frame()
    return frame.env.params_of(owner, frame.root)


# ── la persona jusqu'aux paramètres en vigueur ────────────────────────────


def test_a_profile_reaches_every_faculty_through_the_journal(tmp_path):
    """Une persona « anxieuse » : chaque faculté qui dérive du tempérament a, en vigueur, exactement ce que ce
    tempérament dérive — le chemin persona → configuration → journal est branché partout."""
    t = profile("anxieuse")

    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        return {f.name: forms.flatten(in_force(kernel, f.name)) for f in faculties()
                if f.derive is not None and f.params is not None}

    got = live(tmp_path, t, scenario)
    for fac in faculties():
        if fac.derive is not None and fac.params is not None:
            assert got[fac.name] == forms.flatten(fac.derive(t, None)), fac.name


# ── ce qu'elle ressent ────────────────────────────────────────────────────


def test_negativity_the_same_sorrow_weighs_more_and_the_same_joy_less(tmp_path):
    def scene(tag):  # type: ignore[no-untyped-def]
        async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
            await befriend(kernel, "user_1")
            for _ in range(3):
                await say(kernel, voice, "user_1", tag)
                await wait(60)
            m = fact(kernel, affect_c.MOOD)
            return A.distance(m.position, m.home)
        return scenario

    sad = each(tmp_path / "triste", extremes("negativity"), scene("[EMOTION:sad:0.6]"))
    happy = each(tmp_path / "joie", extremes("negativity"), scene("[EMOTION:happy:0.6]"))
    assert sad["haut"] > sad["milieu"] > sad["bas"]
    assert happy["bas"] > happy["milieu"] > happy["haut"]


# ── ce qu'elle montre ─────────────────────────────────────────────────────


def test_expressiveness_shows_on_her_face(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await say(kernel, voice, "user_1", "[EMOTION:sad:0.6]")
        return fact(kernel, affect_c.FACE("user_1")).intensity

    got = each(tmp_path, {"kuudere": profile("kuudere"), "neutre": T.Temperament(), "solaire": profile("solaire")},
               scenario)
    assert got["kuudere"] < got["neutre"] < got["solaire"]


def test_what_she_is_told_of_herself(tmp_path):
    """Une tsundere avec une précision : le modèle lit son masque, sa défense, sa précision, en mots ; au milieu
    partout, rien ne s'en dit."""
    tsundere = profile("tsundere").model_copy(update={"notes": {"reactivity": "tu t'énerves quand on t'appelle poulet"}})

    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await say(kernel, voice, "user_1")
        return voice.prompts[-1]

    got = each(tmp_path, {"tsundere": tsundere, "neutre": T.Temperament()}, scenario)
    title = phrase("self.temperament.title")
    assert title in got["tsundere"] and title not in got["neutre"]
    for line in (phrase("self.temperament.trait.mask.high"), phrase("self.temperament.trait.defense.attack"),
                 phrase("self.temperament.precisely", note="tu t'énerves quand on t'appelle poulet")):
        assert line in got["tsundere"]


# ── ce qu'elle fait de ses émotions ───────────────────────────────────────


def test_impulsivity_lets_the_same_feeling_push_her_to_speak_and_sooner_again(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1", "close")
        for _ in range(4):
            await say(kernel, voice, "user_1", "[EMOTION:sad:0.8]")
            await wait(60)
        return (overflow_evidence(fact(kernel, affect_c.MOOD), in_force(kernel, "affect")),
                in_force(kernel, "agency").refractory_us)

    got = each(tmp_path, extremes("impulsivity"), scenario)
    assert got["haut"][0] > got["milieu"][0] >= got["bas"][0] and got["haut"][0] > 0
    assert got["haut"][1] < got["milieu"][1] < got["bas"][1]


def test_introspection_turns_a_lighter_thought_into_a_reflection(tmp_path):
    """Une amie confie quelque chose qui la peine : l'introspective en fait une réflexion (la laisse mûrir, puis y
    repense) ; celle qui passe vite à autre chose, non."""
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await say(kernel, voice, "user_1", "[EMOTION:sad:0.6]", text="mon frère part vivre à l'étranger")
        await wait(3 * HOUR / US * US / US)
        events = [e for e in kernel.mind.store.read() if e.type == "goals.opened"]
        return len(events)

    got = each(tmp_path, {"bas": T.Temperament(introspection=T.LOWEST),
                          "haut": T.Temperament(introspection=T.HIGHEST)}, scenario)
    assert got["haut"] >= 1 and got["bas"] == 0, got


# ── les autres ────────────────────────────────────────────────────────────


def test_empathy_sadness_shared_brings_her_closer(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        for _ in range(4):
            await say(kernel, voice, "user_1", "[EMOTION:sad:0.7]", "[EN_FACE: sad 0.8]")
            await wait(120)
        return fact(kernel, affect_c.REGARD("user_1"))

    got = each(tmp_path, extremes("empathy"), scenario)
    assert got["haut"] > got["milieu"] > got["bas"]


def test_shyness_a_stranger_fills_her_less(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await wait(3 * HOUR / US * US / US)
        for _ in range(3):
            await say(kernel, voice, "user_9", "[EMOTION:curious:0.4]")
            await wait(60)
        return fact(kernel, needs_c.NEEDS).social

    got = each(tmp_path, extremes("shyness"), scenario)
    assert got["haut"] > got["milieu"] > got["bas"]


def test_attachment_and_stability_what_a_relation_installs(tmp_path):
    async def warm_then_harsh(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        for _ in range(5):
            await say(kernel, voice, "user_1", "[EMOTION:love:0.8]")
            await wait(120)
        bond, before = fact(kernel, affect_c.BOND("user_1")), fact(kernel, affect_c.REGARD("user_1"))
        await say(kernel, voice, "user_1", "[EMOTION:angry:0.8]")
        return bond, before - fact(kernel, affect_c.REGARD("user_1"))

    attach = each(tmp_path / "attachement", extremes("attachment"), warm_then_harsh)
    assert attach["haut"][0] > attach["milieu"][0] > attach["bas"][0]
    stable = each(tmp_path / "stabilite", extremes("stability"), warm_then_harsh)
    assert stable["bas"][1] > stable["milieu"][1] > stable["haut"][1] > 0


async def _expect(kernel, kind: str, draft) -> None:  # type: ignore[no-untyped-def]
    await kernel.mind.append([draft], emitter="attention", correlation=f"test:{kind}", origin=Origin.PROCESS)


def test_abandonment_a_message_left_unanswered_weighs_more(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await _expect(kernel, "missed", attention_c.EXPECTATION_MISSED.draft(
            kind=attention_c.REPLY, person="user_1", since=AFTERNOON - HOUR))
        m = fact(kernel, affect_c.MOOD)
        return A.distance(m.position, m.home), fact(kernel, affect_c.STANCE("user_1")).felt_intensity

    got = each(tmp_path, extremes("abandonment"), scenario)
    assert got["haut"][0] > got["milieu"][0] > got["bas"][0]
    assert got["haut"][1] > got["bas"][1]


def test_contagion_walled_off_a_return_leaves_her_unmoved(tmp_path):
    """Cloisonnée, ou de marbre : le retour d'une amie ne l'ébranle pas ; au milieu, il la réjouit."""
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await _expect(kernel, "met", attention_c.EXPECTATION_MET.draft(
            kind=attention_c.RETURN, person="user_1", since=AFTERNOON - 4 * DAY, absence=4.0))
        m = fact(kernel, affect_c.MOOD)
        return A.distance(m.position, m.home)

    got = each(tmp_path, {"cloisonnee": T.Temperament(contagion=T.LOWEST), "de_marbre": profile("de_marbre"),
                          "milieu": T.Temperament()}, scenario)
    assert got["cloisonnee"] < 0.5 * got["milieu"] and got["de_marbre"] < 0.5 * got["milieu"]


def test_trust_and_grudge_how_long_she_holds_it_against_someone(tmp_path):
    """Une inconnue la blesse cinq fois : la méfiante en garde une méfiance plancher, la rancunière lui en veut
    encore une semaine après ; la confiante et celle qui pardonne, beaucoup moins."""
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        for _ in range(5):
            await say(kernel, voice, "user_9", "[EMOTION:angry:0.8]", "[EN_FACE: angry 0.7 | geste : blessant]")
            await wait(60)
        await wait(7 * DAY / US * US / US)
        return fact(kernel, affect_c.HOSTILITY("user_9"))

    trust = each(tmp_path / "confiance", {"mefiante": T.Temperament(trust=T.LOWEST),
                                          "confiante": T.Temperament(trust=T.HIGHEST)}, scenario)
    assert trust["mefiante"] > trust["confiante"]
    grudge = each(tmp_path / "rancune", {"pardonne": T.Temperament(grudge=T.LOWEST),
                                         "rancuniere": profile("rancuniere")}, scenario)
    assert grudge["rancuniere"] > grudge["pardonne"]


def test_devotion_her_owner_counts_more_and_never_less_than_a_close_friend(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Alice")
        return fact(kernel, social_c.WEIGHT("user_1")), fact(kernel, social_c.WEIGHT("user_2"))

    got = each(tmp_path, extremes("devotion"), scenario)
    assert got["haut"][0] > got["milieu"][0] > got["bas"][0] > 1.0
    assert {other for _owner, other in got.values()} == {1.0}


# ── elle-même ─────────────────────────────────────────────────────────────


def test_self_regard_fragility_and_admiration_her_esteem(tmp_path):
    async def rest(kernel, voice):  # type: ignore[no-untyped-def]
        return fact(kernel, self_c.ESTEEM)

    regard = each(tmp_path / "base", extremes("self_regard"), rest)
    assert regard["haut"] > regard["milieu"] == 0.5 > regard["bas"]

    def gesture(their):  # type: ignore[no-untyped-def]
        async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
            await befriend(kernel, "user_1")
            before = fact(kernel, self_c.ESTEEM)
            await say(kernel, voice, "user_1", "[EMOTION:sad:0.4]", their)
            return fact(kernel, self_c.ESTEEM) - before
        return scenario

    hurt = each(tmp_path / "fragile", extremes("fragility"), gesture("[EN_FACE: angry 0.6 | geste : blessant]"))
    assert hurt["haut"] < hurt["milieu"] < hurt["bas"] < 0
    praised = each(tmp_path / "admiration", extremes("admiration"), gesture("[EN_FACE: happy 0.6 | geste : merci]"))
    assert praised["haut"] > praised["milieu"] > praised["bas"] > 0


def test_scruples_a_sharp_reply_leaves_remorse_or_not(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await say(kernel, voice, "user_1", "[EMOTION:angry:0.6]")
        await wait(30 * MINUTE / US * US / US)
        return [e for e in kernel.mind.store.read() if e.type == "attention.thought_born"
                and kernel.mind.decode(e).data.origin == attention_c.REMORSE]

    got = each(tmp_path, {"sans": T.Temperament(scruples=T.LOWEST), "scrupuleuse": T.Temperament(scruples=T.HIGHEST)},
               scenario)
    assert got["scrupuleuse"] and not got["sans"]


def test_anxiety_what_weighs_on_her_comes_back_more_often(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await say(kernel, voice, "user_1", "[EMOTION:sad:0.8]", text="j'ai perdu mon travail ce matin")
        await wait(4 * HOUR / US * US / US)
        return sum(1 for e in kernel.mind.store.read() if e.type == "attention.dwelt")

    got = each(tmp_path, extremes("anxiety"), scenario)
    assert got["haut"] > got["milieu"] > got["bas"], got


# ── son corps ─────────────────────────────────────────────────────────────


def test_energy_fatigue_comes_later_for_the_tireless(tmp_path):
    async def scenario(kernel, voice):  # type: ignore[no-untyped-def]
        return fact(kernel, body_c.ENERGY), in_force(kernel, "body").tired_below

    got = each(tmp_path, extremes("energy"), scenario, start=at_paris(2026, 9, 28, 22, 30))
    assert got["haut"][0] > got["milieu"][0] > got["bas"][0]
    assert got["haut"][1] < got["milieu"][1] < got["bas"][1]


# ── appliquer un profil ───────────────────────────────────────────────────


def test_the_command_line_applies_a_profile_and_keeps_her_particulars(tmp_path):
    """« mika profil anxieuse » : sa persona prend le profil (son chronotype et ses précisions gardés), et la
    commande sans nom le reconnaît."""
    async def run(nom):  # type: ignore[no-untyped-def]
        return await _with_settings(tmp_path, lambda settings, _store: profile_command(
            settings, argparse.Namespace(nom=nom)))

    assert asyncio.run(run(None))["le_sien"] == "reflechie"
    assert asyncio.run(run("anxieuse"))["appliqué"] == "anxieuse"
    assert asyncio.run(run(None))["le_sien"] == "anxieuse"
