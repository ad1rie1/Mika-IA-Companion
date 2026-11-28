"""Trois jours d'une tsundere (ADR 0100) : tendre en dedans, piquante en dehors — surtout avec qui elle aime.

Profil : masque 90 %, défense « attaquer », réactivité 70 %, empathie 70 %, fragilité 70 %, attachement à sa
propriétaire 80 %, expressivité 40 %. Les journées sont celles de ``tests/fixtures/temperament_life.py`` ; chaque
mesure se compare à la même vie au milieu partout.
"""

from __future__ import annotations

import pytest

from mika.vocab.phrasebook import phrase
from tests.fixtures.temperament_life import assert_her_temperament_everywhere, live, neutral, profile

pytestmark = pytest.mark.slow  # trois jours de vie, deux fois


@pytest.fixture(scope="module")
def lives(tmp_path_factory):  # type: ignore[no-untyped-def]
    return live(tmp_path_factory.mktemp("tsundere"), profile("tsundere")), neutral(tmp_path_factory.mktemp("neutre"))


def test_her_temperament_reaches_every_voice(lives):  # type: ignore[no-untyped-def]
    """Ses répliques, ses initiatives, ses séances de travail, son journal, ses rêves, son récit : partout sa
    persona porte son tempérament, mesures comprises."""
    her, middle = lives
    assert_her_temperament_everywhere(her)
    mask = phrase("self.temperament.trait.mask.high")
    assert f"{phrase('self.temperament.name.mask')} : 90 % — {mask[0].lower()}{mask[1:]}" in her.block
    assert phrase("self.temperament.trait.defense.attack") in her.block
    assert her.block != middle.block


def test_a_compliment_from_her_owner_and_her_face_bites(lives):  # type: ignore[no-untyped-def]
    """Adrien lui dit qu'il tient à elle ; touchée (le modèle la dit tendre), son visage pique (frustrée) au lieu de
    la tendresse que montre la Mika du milieu."""
    her, middle = lives
    assert her.m["face_compliment"][0] == "frustrated"
    assert middle.m["face_compliment"][0] == "love"


def test_she_hides_her_tenderness_from_the_one_she_loves(lives):  # type: ignore[no-untyped-def]
    """La même joie envers sa propriétaire se voit beaucoup moins sur son visage."""
    her, middle = lives
    assert her.m["face_warm"][1] < 0.5 * middle.m["face_warm"][1]


def test_her_owner_counts_more_and_others_reach_her(lives):  # type: ignore[no-untyped-def]
    """Sa propriétaire compte davantage ; le deuil d'une amie la touche au moins autant qu'au milieu ; une réplique
    sèche lui laisse un remords."""
    her, middle = lives
    assert her.m["weight_owner"] > middle.m["weight_owner"]
    assert her.m["grief_moved"] >= middle.m["grief_moved"]
    assert her.m["remorse_bob"] >= 1


def test_time_passes_nights_and_an_apology(lives):  # type: ignore[no-untyped-def]
    """Trois nuits : un journal chacune, des rêves, un récit ; la blessure d'Alice s'estompe avec les jours, et ses
    excuses réchauffent encore la relation."""
    her, _middle = lives
    assert her.m["journals"] >= 2 and her.m["dreams"] >= 1 and her.m["narratives"] >= 1
    assert her.m["regard_alice"] < 0  # blessée : la relation refroidit (jamais de tendresse)
    assert abs(her.m["regard_alice_before_apology"]) < abs(her.m["regard_alice"])
    assert her.m["regard_alice_after_apology"] > her.m["regard_alice_before_apology"]
