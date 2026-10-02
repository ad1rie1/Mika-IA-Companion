"""La balise déclarée et la prosodie : ce que le modèle écrit, ce qu'on en garde.

Les entrées sont des sorties réelles de modèles (l'audit des prompts en a
passé une cinquantaine au parseur) : ce qui en sort doit être **prêt à
livrer** — à la voix du frontend, au chat, à Telegram, au fil relu.
"""

from __future__ import annotations

import pytest

from mika.faculties.expression import parse
from mika.vocab import affect as A
from mika.vocab.affect import Declared, Emotion, emotion_named, parse_tag, partitive, strip_prosody


@pytest.mark.parametrize("text, clean, declared", [
    ("Coucou [EMOTION:happy:0.8]", "Coucou", ("happy", 0.8)),
    ("Coucou [EMOTION:happy]", "Coucou", ("happy", 0.5)),  # sans intensité : « net »
    ("ok [emotion: Sad : 0,6]", "ok", ("sad", 0.6)),  # casse, espaces, virgule
    ("trop fort [EMOTION:angry:4]", "trop fort", ("angry", 0.4)),  # une échelle sur 10
    ("Grave ! [EMOTION:excited:8]", "Grave !", ("excited", 0.8)),
    ("Ouais. [EMOTION:happy:60]", "Ouais.", ("happy", 0.6)),  # sur 100
    ("Ouais ouais. [EMOTION:happy:60%]", "Ouais ouais.", ("happy", 0.6)),
    ("Coucou ! [PLAYFUL:0.8]", "Coucou !", ("playful", 0.8)),  # forme abrégée des modèles
    ("hmm [LAUGH] [sad]", "hmm [LAUGH]", ("sad", 0.5)),  # la prosodie reste pour la voix
    ("a [curious] b [EMOTION:happy:0.4]", "a b", ("happy", 0.4)),  # un indice en minuscules est une balise
    ("[PAUSE:300] voilà", "[PAUSE:300] voilà", None),  # un jeton de voix n'est pas une émotion
    ("rien du tout", "rien du tout", None),
    # P3 : débris de markdown autour de la balise
    ("Trop bien ! **[EMOTION:excited:0.8]**", "Trop bien !", ("excited", 0.8)),
    ("Hmm, je sais pas trop. *[EMOTION:thinking:0.4]*", "Hmm, je sais pas trop.", ("thinking", 0.4)),
    ("Bref !\n`[EMOTION:playful:0.6]`", "Bref !", ("playful", 0.6)),
    ("Coucou ! [[EMOTION:happy:0.6]]", "Coucou !", ("happy", 0.6)),
    # P4 : variantes
    ("Trop cool. [EMOTION:happy:0.7.]", "Trop cool.", ("happy", 0.7)),
    ("Ah bon ? [EMOTION:surprised, 0.6]", "Ah bon ?", ("surprised", 0.6)),
    ("Ah bon ? [EMOTION=surprised:0.6]", "Ah bon ?", ("surprised", 0.6)),
    ("Bonne nuit ! (EMOTION:happy:0.5)", "Bonne nuit !", ("happy", 0.5)),
    ("Bonne nuit ! {EMOTION:happy:0.5}", "Bonne nuit !", ("happy", 0.5)),
    ("Coucou ! [EMOTION:happy:0.6", "Coucou !", ("happy", 0.6)),  # non fermée
    ("Coucou !\nÉmotion : happy (0.6)", "Coucou !", ("happy", 0.6)),  # en toutes lettres
    # P5 : la dernière balise gagne (c'est ce qu'elle ressent en finissant d'écrire)
    ("Haha trop drôle [EMOTION:amused:0.8] mais bon… [EMOTION:sad:0.3]", "Haha trop drôle mais bon…", ("sad", 0.3)),
    # P6 : noms français, intensifs
    ("Oh… [EMOTION:triste:0.6]", "Oh…", ("sad", 0.6)),
    ("Hehe [EMOTION:very_happy:0.9]", "Hehe", ("happy", 0.9)),
    ("Grr [EMOTION:en colère:0.7]", "Grr", ("angry", 0.7)),
    ("OK. [EMOTION:HAPPY:0.5]", "OK.", ("happy", 0.5)),
])
def test_parse_tag(text, clean, declared):
    tag = parse_tag(text)
    assert tag.text == clean
    if declared is None:
        assert tag.declared is None
    else:
        assert tag.declared == Declared(Emotion(declared[0]), declared[1])


@pytest.mark.parametrize("text, clean", [
    # P7 : un mot entre crochets n'est pas forcément une balise
    ("J'ai lancé [Curious] le jeu indé, trop bien [EMOTION:happy:0.6]", "J'ai lancé [Curious] le jeu indé, trop bien"),
    ("Regarde [curious](https://example.org) ! [EMOTION:excited:0.6]", "Regarde [curious](https://example.org) !"),
    # P8 / EDG-19 : la prosodie dans la grammaire exacte du frontend
    ("Attends… [PAUSE:500ms] non rien.", "Attends… [PAUSE:500] non rien."),
    ("Attends… [PAUSE 500] non rien.", "Attends… [PAUSE:500] non rien."),
    ("Attends… [PAUSE: 500] non.", "Attends… [PAUSE:500] non."),
    ("Euh [pause:1.5s] bon.", "Euh [PAUSE:1500] bon."),
    ("[SIGHS] Bon.", "[SIGH] Bon."),
    ("[soupir] Bon. [RIRE]", "[SIGH] Bon. [LAUGH]"),
    ("[laugh] trop drôle", "[LAUGH] trop drôle"),
    ("[LAUGH:0.5] trop drôle", "[LAUGH] trop drôle"),
    ("[breathes] ok", "[BREATH] ok"),
    # tout autre jeton en capitales est retiré, et ce qui reste d'une balise mal formée
    ("[WHISPERS] psst [SMILES] fin", "psst fin"),
    ("bon [EMOTION ?] ok", "bon ok"),
    # P9 : didascalies, préfixe, guillemets, raisonnement
    ("*rit* T'es bête !", "[LAUGH] T'es bête !"),
    ("*soupire* bon d'accord", "[SIGH] bon d'accord"),
    ("(sourit) Coucou !", "Coucou !"),
    ("*hausse les épaules* Bof.", "Bof."),
    ("Mika : Coucou Adrien !", "Coucou Adrien !"),
    ("**Mika**: Coucou !", "Coucou !"),
    ("« Coucou Adrien ! »", "Coucou Adrien !"),
    ('"Coucou Adrien !"', "Coucou Adrien !"),
    ("<thinking>Il a l'air triste.</thinking>Oh… ça va ?", "Oh… ça va ?"),
    ("Bon , ok .", "Bon, ok."),
    # les émojis : sa parole est lue à voix haute (une synthèse lit « visage souriant ») et le style les interdit
    ("Trop bien 😄", "Trop bien"),
    ("Bisous Chloé ! 😊", "Bisous Chloé !"),
    ("J'adore ❤️ ça", "J'adore ça"),
    ("Ok 👍🏽 vas-y", "Ok vas-y"),
    ("Tu vas déchirer jeudi ! 💪\nÀ ce soir !", "Tu vas déchirer jeudi !\nÀ ce soir !"),
])
def test_the_text_is_ready_to_deliver(text, clean):
    assert parse_tag(text).text == clean


@pytest.mark.parametrize("text", [
    "Tu as vu *vraiment* tout le film ?",  # une emphase n'est pas une didascalie
    "(voir pièce jointe) merci",  # une vraie parenthèse reste
    "Alors :\n- un\n- deux",
    "J'ai mis [x] la case",
    "Je dirais « non » franchement.",  # des guillemets au milieu, pas englobants
    "« ça » … → là, 3 °C, 50 %, ½ et Œuvre",  # ni la ponctuation française, ni les symboles ordinaires
])
def test_ordinary_text_is_left_alone(text):
    """Contre-exemples : le nettoyage ne mange jamais du texte légitime."""
    assert parse_tag(text).text == text


@pytest.mark.parametrize("text, kept", [
    ("[SILENCE]", "[SILENCE]"),
    ("[silence]", "[SILENCE]"),
    ("**[SILENCE]**", "[SILENCE]"),
    ("« [SILENCE] »", "[SILENCE]"),
    ("[SILENCE] [EMOTION:neutral:0.2]", "[SILENCE]"),
    ("Bon, je vais rien dire. [SILENCE]", "Bon, je vais rien dire. [SILENCE]"),
    ("(silence)", "(silence)"),
])
def test_silence_is_never_damaged(text, kept):
    """Le silence est reconnu ailleurs : le nettoyage le garde (et le rend plus
    lisible quand il le peut), jamais ne l'efface."""
    assert parse_tag(text).text == kept


def test_cleaning_is_stable():
    """Relu, un texte nettoyé ne change plus, et ne garde jamais une balise."""
    for text in ["Trop bien ! **[EMOTION:excited:0.8]**", "*rit* « Coucou ! » [PAUSE 500] [EMOTION:happy:60%]",
                 "Mika : [SOUPIR] bon [EMOTION:triste:0.6"]:
        once = parse_tag(text).text
        assert parse_tag(once).text == once and "EMOTION" not in once.upper()


def test_unknown_name_is_reported_not_declared():
    tag = parse_tag("[EMOTION:hangry:0.9] bon")
    assert tag.declared is None and tag.unknown == "hangry" and tag.text == "bon"


def test_expression_parse_profits_from_it():
    """La faculté ``expression`` appelle ``parse_tag`` : sa sortie est déjà prête."""
    text, annotations = parse("Mika : « Trop bien ! » **[EMOTION:excited:8]**")
    assert text == "Trop bien !" and annotations == {"emotion": "excited:0.800"}


def test_names_in_french_and_synonyms():
    assert emotion_named("triste") is Emotion.SAD
    assert emotion_named("Pleine d'espoir") is Emotion.HOPEFUL
    assert emotion_named("un peu inquiète") is Emotion.ANXIOUS
    assert emotion_named("joyful") is Emotion.HAPPY
    assert emotion_named("rire") is None and emotion_named("PAUSE") is None  # des jetons de voix, pas des émotions
    assert A.emotion_of("triste") is None  # le nom canonique reste strict


def test_every_emotion_has_a_noun():
    assert {e for e in Emotion} == set(A.NOUN)
    assert partitive(Emotion.ANGRY) == "de colère" and partitive(Emotion.AMUSED) == "d'amusement"


def test_declared_round_trips_through_its_encoding():
    d = Declared(Emotion.MELANCHOLIC, 0.35)
    assert Declared.decode(d.encode()) == d
    assert Declared.decode("nope:0.3") is None and Declared.decode(None) is None and Declared.decode("sad:nan") is None


def test_strip_prosody_keeps_french_punctuation():
    assert strip_prosody("Ah... [PAUSE:500] ouais ! [SIGH] Désolée ; bon.") == "Ah... ouais ! Désolée ; bon."
    # un texte ancien, jamais normalisé : ses variantes ne passent pas non plus
    assert strip_prosody("Ah [PAUSE: 500] [soupir] ouais [SIGHS]") == "Ah ouais"
    assert strip_prosody("bon [SILENCE]") == "bon [SILENCE]"


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
