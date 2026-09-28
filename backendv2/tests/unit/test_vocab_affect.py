"""La balise déclarée et la prosodie : ce que le modèle écrit, ce qu'on en garde."""

from __future__ import annotations

import pytest

from mika.vocab import affect as A
from mika.vocab.affect import Declared, Emotion, parse_tag, strip_prosody


@pytest.mark.parametrize("text, clean, declared", [
    ("Coucou [EMOTION:happy:0.8]", "Coucou", ("happy", 0.8)),
    ("Coucou [EMOTION:happy]", "Coucou", ("happy", 0.7)),  # sans intensité : 0,7
    ("ok [emotion: Sad : 0,6]", "ok", ("sad", 0.6)),  # casse, espaces, virgule
    ("trop fort [EMOTION:angry:4]", "trop fort", ("angry", 1.0)),  # bornée
    ("Coucou ! [PLAYFUL:0.8]", "Coucou !", ("playful", 0.8)),  # forme abrégée des modèles
    ("hmm [LAUGH] [sad]", "hmm [LAUGH]", ("sad", 0.7)),  # la prosodie reste pour la voix
    ("a [curious] b [EMOTION:happy:0.4]", "a b", ("happy", 0.4)),  # la forme complète l'emporte
    ("[PAUSE:300] voilà", "[PAUSE:300] voilà", None),  # un jeton de voix n'est pas une émotion
    ("rien du tout", "rien du tout", None),
])
def test_parse_tag(text, clean, declared):
    tag = parse_tag(text)
    assert tag.text == clean
    if declared is None:
        assert tag.declared is None
    else:
        assert tag.declared == Declared(Emotion(declared[0]), declared[1])


def test_unknown_name_is_reported_not_declared():
    tag = parse_tag("[EMOTION:hangry:0.9] bon")
    assert tag.declared is None and tag.unknown == "hangry" and tag.text == "bon"


def test_declared_round_trips_through_its_encoding():
    d = Declared(Emotion.MELANCHOLIC, 0.35)
    assert Declared.decode(d.encode()) == d
    assert Declared.decode("nope:0.3") is None and Declared.decode(None) is None and Declared.decode("sad:nan") is None


def test_strip_prosody_keeps_french_punctuation():
    assert strip_prosody("Ah... [PAUSE:500] ouais ! [SIGH] Désolée ; bon.") == "Ah... ouais ! Désolée ; bon."


def test_felt_names_the_step_from_rest_not_the_absolute_position():
    """Depuis un repos positif, un petit pas vers la tristesse se lit
    « triste », alors que la position absolue reste positive."""
    home = A.add(A.to_pad(Emotion.HAPPY, 0.15), A.to_pad(Emotion.PLAYFUL, 0.35))
    step = A.lerp(home, A.ANCHORS[Emotion.SAD], 0.2)
    assert A.valence(A.label(step)[0]) > 0  # l'absolu dit encore la teinte du jour
    assert A.felt(step, home)[0] is Emotion.SAD
    assert A.felt(home, home) == (Emotion.NEUTRAL, 0.0)


def test_a_pure_position_is_not_ambivalent_a_torn_one_is():
    """La deuxième couleur ne vient que de ce que la dominante n'explique pas :
    nulle sur une position pure, elle monte quand la position s'en écarte."""
    assert len(A.blend(A.to_pad(Emotion.GRATEFUL, 0.8))) == 1
    torn = A.lerp(A.to_pad(Emotion.SAD, 0.8), A.to_pad(Emotion.ANGRY, 0.8), 0.35)
    parts = A.blend(torn)
    assert [e for e, _ in parts] == [Emotion.SAD, Emotion.ANGRY] and A.is_ambivalent(parts)
    near = A.lerp(A.to_pad(Emotion.SAD, 0.8), A.to_pad(Emotion.ANGRY, 0.8), 0.2)
    assert A.blend(near)[1][1] < parts[1][1]
