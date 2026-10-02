"""Lire l'autre, par les cas de l'audit (ADR 0035).

- la mort, la maladie, une rupture, une perte de travail, des mots de détresse
  se lisent lourds — et inquiètent venant d'une amie, même si elle râle
  toujours ; « putain c'est trop bien !! » est joyeux ; « je suis fatiguée,
  bonne nuit » n'est pas lourd ; pleurer devant un beau film non plus ;
- quand elle répond elle-même triste, anxieuse ou effrayée à une amie, c'est
  qu'elle s'inquiète : elle prendra de ses nouvelles (pas chez quelqu'un dont
  c'est le ton habituel) ;
- un « ok » ne la rassure pas ; un vrai message plus léger, si ;
- la contagion : le ton du moment d'une proche la colore un peu, celui d'une
  inconnue pas du tout ; c'est plafonné, et jamais un mot du message.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.others.faculty import OthersParams, _read_felt
from mika.faculties.others.tone import measure
from mika.kernel.clock import HOUR, MINUTE, US
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.affect import Emotion
from tests.fixtures.mika import at_paris, befriend, boot, build, said

P = OthersParams()
LIGHT = ["haha trop bien", "super journée, trop cool", "j'ai hâte de te raconter haha", "trop bien ce film !",
         "génial, merci !", "haha j'adore", "c'était trop cool", "super, à demain !", "trop bien haha",
         "incroyable, j'adore"]
GRUMPY = ["j'en ai marre, je suis épuisée", "encore une journée nulle, j'en ai marre", "je suis épuisée, ras le bol",
          "tout est nul, marre", "j'en peux plus, épuisée et triste"] * 2


# ── Le ton : ce que les mots disent vraiment ──────────────────────────────


@pytest.mark.parametrize("text", ["je veux mourir", "ma mère est décédée ce matin", "j'ai un cancer",
                                  "je me suis fait virer", "il m'a quittée hier soir",
                                  "mon père est à l'hôpital depuis ce matin"])
def test_grave_events_read_heavy(text):
    tone = measure(text)
    assert tone.grave and tone.valence <= -0.7, (text, tone)


@pytest.mark.parametrize("text,lo,hi", [
    ("je suis fatiguée, bonne nuit", -0.1, 0.1),  # fatiguée au moment de dormir : rien de lourd
    ("putain c'est trop bien !!", 0.3, 1.0),  # un juron qui intensifie la joie
    ("ce film m'a fait pleurer tellement il était beau", -0.25, 1.0),  # des larmes heureuses
    ("j'étais morte de rire hier", 0.1, 1.0),  # « morte de rire » n'est pas un deuil
    ("j'en ai marre, je suis épuisée", -1.0, -0.5),  # contrôle : ça, c'est lourd
])
def test_what_is_not_heavy_is_not_read_heavy(text, lo, hi):
    tone = measure(text)
    assert lo <= tone.valence <= hi and not tone.grave, (text, tone)


@pytest.mark.parametrize("text", ["c'est mort pour ce soir, désolée", "mon téléphone est mort", "le projet est mort",
                                  "je vais mourir de chaud", "j'ai hâte d'en finir avec ce dossier",
                                  "ma mère va me tuer", "le suicide de Werther, quel livre",
                                  "j'ai eu un petit accident de café sur mon clavier", "rupture de stock de croissants"])
def test_everyday_hyperboles_are_not_grave_events(text):
    """Une batterie morte ou « mourir de chaud » n'inquiètent personne : pas de prise de nouvelles pour ça."""
    assert not measure(text).grave, text


@pytest.mark.parametrize("text", ["mon chat est mort cette nuit", "mon grand-père vient de mourir",
                                  "j'ai envie d'en finir", "j'ai eu un accident de voiture"])
def test_the_same_words_said_of_a_life_are_grave(text):
    """Contrôle : les mêmes mots, quand ils disent une vie, se lisent graves."""
    assert measure(text).grave, text


# ── De bout en bout ───────────────────────────────────────────────────────


class Script:
    """Sa réponse : une émotion déclarée par personne (par défaut, contente)."""

    def __init__(self):
        self.tags: dict[str, str] = {}

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact", "narrative"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens")
        return LLMResponse(f"d'accord {self.tags.get(req.meta.get('target'), '[EMOTION:happy:0.4]')}")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 11, 0)):
    script = Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def chat(kernel, handle, texts, gap=60):
    for text in texts:
        p = await kernel.perceive(said(handle, text, channel="telegram"))
        await p.reply
        await asyncio.sleep(gap)


def reads(kernel):
    mind = kernel.mind
    return [mind.decode(e).data for e in mind.store.read() if e.type == others_c.READ.name]


def check_ins(kernel, handle):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == rt.EPISODE_STARTED.name
            and mind.decode(e).data.kind == "INITIATIVE" and mind.decode(e).data.target == handle
            and others_c.CHECK_IN in mind.decode(e).data.reason]


def test_a_grave_event_worries_her_even_from_a_friend_who_always_complains(tmp_path):
    """Avant : le même message lourd, venant de quelqu'un qui râle toujours, ne
    l'inquiétait pas — même « ma mère est décédée ». Un deuil n'est pas une
    plainte de plus."""
    async def scenario(kernel, script):
        await befriend(kernel, "tg_6", social_c.FRIEND)
        await chat(kernel, "tg_6", GRUMPY)
        await chat(kernel, "tg_6", ["j'en ai marre, je suis épuisée"])
        habitual = reads(kernel)[-1]
        await chat(kernel, "tg_6", ["ma mère est décédée ce matin"])
        return habitual, reads(kernel)[-1]

    habitual, grief = run(tmp_path, scenario)
    assert not habitual.concern  # contrôle : sa plainte habituelle n'inquiète pas
    assert grief.concern and grief.grave


def test_her_own_worried_reply_makes_her_check_in_later(tmp_path):
    """« Ma grand-mère est partie ce matin » : les mots ne disent rien de lourd,
    mais elle y répond triste. Elle s'inquiète : quelques heures plus tard, elle
    prend de ses nouvelles. Contrôle : chez une amie qui râle toujours, sa
    peine pour elle ne dit rien de neuf."""
    async def scenario(kernel, script):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        await befriend(kernel, "tg_6", social_c.FRIEND)
        await chat(kernel, "tg_1", LIGHT[:8])
        await chat(kernel, "tg_6", GRUMPY[:8])
        script.tags = {"tg_1": "[EMOTION:sad:0.8]", "tg_6": "[EMOTION:sad:0.8]"}
        await chat(kernel, "tg_1", ["ma grand-mère est partie ce matin"])
        await chat(kernel, "tg_6", ["ma grand-mère est partie ce matin"])
        concerns = dict(kernel.mind.root.slices["others"].concerns.items())
        script.tags = {}
        await asyncio.sleep(10 * HOUR / US)
        return concerns, check_ins(kernel, "tg_1"), check_ins(kernel, "tg_6")

    concerns, to_alice, to_bea = run(tmp_path, scenario)
    assert "tg_1" in concerns and "tg_6" not in concerns
    assert len(to_alice) == 1 and not to_bea


def test_an_ok_does_not_reassure_her_a_real_lighter_message_does(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        await chat(kernel, "tg_1", LIGHT)
        await chat(kernel, "tg_1", ["j'en ai marre, je suis épuisée"])
        worried = "tg_1" in kernel.mind.root.slices["others"].concerns
        await chat(kernel, "tg_1", ["ok"])
        after_ok = "tg_1" in kernel.mind.root.slices["others"].concerns
        await chat(kernel, "tg_1", ["ça va mieux, merci d'avoir pensé à moi !"])
        return worried, after_ok, "tg_1" in kernel.mind.root.slices["others"].concerns

    worried, after_ok, after_better = run(tmp_path, scenario)
    assert worried and after_ok  # un « ok » ne dit pas qu'elle va mieux
    assert not after_better


def test_the_mood_of_a_close_friend_is_contagious_a_strangers_is_not(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        await chat(kernel, "tg_1", LIGHT, gap=30)  # dix messages joyeux en cinq minutes
        await chat(kernel, "tg_9", LIGHT[:3], gap=30)
        return reads(kernel)

    got = run(tmp_path, scenario)
    friend = [r for r in got if r.handle == "tg_1"]
    stranger = [r for r in got if r.handle == "tg_9"]
    assert all(r.contagion == 0.0 for r in stranger)  # on ne s'allège pas avec une inconnue
    caught = [r for r in friend if r.contagion > 0]
    assert caught and all(r.contagion_emotion == Emotion.HAPPY.value for r in caught)
    assert sum(r.contagion for r in friend) <= P.contagion_cap + 1e-9  # plafonnée sur la fenêtre
    assert all(r.contagion <= P.contagion_gain + 1e-9 for r in friend)  # chaque message, un peu


def test_contagion_is_felt_without_a_word_of_the_message():
    """Ce qu'elle ressent d'une lecture : une émotion et un nombre, jamais un mot."""
    data = SimpleNamespace(surprise=0.0, concern=False, contagion=0.1, contagion_emotion=Emotion.ANXIOUS.value)
    felt = _read_felt(SimpleNamespace(data=data), SimpleNamespace(params=P))
    assert [(a.emotion, a.intensity, a.reason, a.relational) for a in felt] == [
        (Emotion.ANXIOUS, 0.1, "contagion", True)]
    assert _read_felt(SimpleNamespace(data=SimpleNamespace(surprise=0.0, concern=False, contagion=0.0,
                                                           contagion_emotion="")),
                      SimpleNamespace(params=P)) == []


def test_contagion_window_resets(tmp_path):
    """Une fois la fenêtre passée, une nouvelle conversation joyeuse la colore à nouveau."""
    async def scenario(kernel, script):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        await chat(kernel, "tg_1", LIGHT, gap=30)
        first = sum(r.contagion for r in reads(kernel))
        await asyncio.sleep(2 * P.contagion_window_us / US + MINUTE / US)
        await chat(kernel, "tg_1", LIGHT[:2], gap=30)
        return first, [r.contagion for r in reads(kernel)][-2:]

    first, later = run(tmp_path, scenario)
    assert first > 0 and later[0] > 0
