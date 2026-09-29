"""L'optimisme pilote enfin quelque chose (il ne pilotait rien) : la couleur de
son repos, le moment où le vide se fait sentir et sa force, le seuil de la
détresse. Vérifié en la laissant vivre, pas en relisant les formules : deux
Mika, l'une sombre, l'autre lumineuse, seules un après-midi entier.

Au milieu du curseur, tout vaut ce qui valait avant (un journal ancien se
rejoue à l'identique)."""

from __future__ import annotations

import asyncio

from mika.contracts import affect as affect_c
from mika.contracts import needs as needs_c
from mika.faculties.affect.params import AffectParams
from mika.faculties.affect.params import derive as affect_derive
from mika.faculties.needs import NeedsParams
from mika.faculties.needs import derive as needs_derive
from mika.faculties.social.faculty import SocialParams
from mika.faculties.social.faculty import derive as social_derive
from mika.kernel.clock import HOUR, US
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.temperament import Temperament
from tests.fixtures.mika import AFTERNOON, DOC, boot, build, said


def _alone(tmp_path, optimism: float) -> tuple[list[tuple[int, float]], float]:
    """Un dernier mot, puis six heures seule et éveillée : quand le vide vient, et la valence de son humeur."""
    doc = DOC.model_copy(update={"temperament": DOC.temperament.model_copy(update={"optimism": optimism})})
    kernel, clock, _llm, _out = build(tmp_path, lambda req: LLMResponse("[SILENCE]"), start=AFTERNOON)

    async def main():
        await boot(kernel, doc)
        try:
            start = kernel.mind.clock.now()
            got = await kernel.perceive(said("user_1", "à plus tard !"))  # un dernier mot, puis personne
            await got.reply
            await asyncio.sleep(6 * HOUR / US)
            felt = [(e.at - start, e.data.intensity) for e in
                    (kernel.mind.decode(s) for s in kernel.mind.store.read(types={needs_c.FELT.name}))]
            mood = kernel.mind.frame().get(affect_c.MOOD)
            return felt, mood.position[0]
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_the_middle_changes_nothing():
    t = Temperament()
    assert affect_derive(t).rest_valence == 0.0 == AffectParams().rest_valence
    assert needs_derive(t).idle_before_empty_us == NeedsParams().idle_before_empty_us == 2 * HOUR
    assert needs_derive(t).empty_intensity == NeedsParams().empty_intensity
    assert social_derive(t) == SocialParams()


def test_an_optimist_rests_brighter_feels_the_void_later_and_lighter(tmp_path):
    dark_felt, dark_valence = _alone(tmp_path / "sombre", 0.1)
    bright_felt, bright_valence = _alone(tmp_path / "lumineuse", 0.9)
    assert dark_felt and bright_felt  # l'une et l'autre finissent par ressentir le vide
    assert dark_felt[0][0] < bright_felt[0][0]  # la pessimiste le sent plus tôt…
    assert dark_felt[0][1] > bright_felt[0][1]  # … et plus fort
    assert len(dark_felt) >= len(bright_felt)
    assert bright_valence > dark_valence  # au repos, le même après-midi n'a pas la même couleur


def test_a_pessimist_reaches_for_comfort_sooner():
    dark = social_derive(Temperament(optimism=0.1)).distress_valence
    bright = social_derive(Temperament(optimism=0.9)).distress_valence
    assert dark > -0.35 > bright  # sombre : une humeur moins basse suffit à la faire chercher du réconfort
