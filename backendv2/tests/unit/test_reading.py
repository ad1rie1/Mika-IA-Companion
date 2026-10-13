"""Le modèle lit la personne ; ses émotions ont des facettes (ADR 0093).

Aucun code de Mika ne devine une émotion dans des mots : en français le ton fait tout (« t'es con » d'une proche qui
rit n'est pas celui d'un inconnu), et seule une lecture du message, du lien et de l'échange en juge. Le modèle qui lui
répond le déclare, dans une balise que la personne ne voit pas ; le code range ce qu'il a déclaré. Le banc
``tools/banc_lecture`` mesure ce jugement sur un vrai modèle ; ici, les tests jouent le modèle (``tests.fixtures.reading``)
et vérifient ce que Mika fait de ce qu'il a lu.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from mika.contracts import affect as affect_c
from mika.contracts import expression as expression_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.affect import physics as ph
from mika.faculties.affect.params import AffectParams
from mika.faculties.expression import emotion_view, parse
from mika.faculties.memory import extraction as x
from mika.kernel.clock import MINUTE, US
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import affect as A
from mika.vocab import reading
from mika.vocab.affect import Declared, Emotion, felt_pad, parse_tag
from mika.vocab.reading import Reading
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said
from tests.fixtures.reading import Reads

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


# ── La balise ─────────────────────────────────────────────────────────────


def test_what_she_read_never_reaches_the_person():
    text, notes = parse("Oh non, je suis là. [EMOTION: sad 0.6, love 0.3] "
                        "[EN_FACE: sad 0.8 | geste : excuses | grave : rupture]", "Mika")
    assert text == "Oh non, je suis là."
    assert Reading.decode(notes[expression_c.READING_ANNOTATION]) == \
        Reading((("sad", 0.8),), reading.APOLOGIZED, reading.BREAKUP)
    assert Declared.decode(notes[expression_c.EMOTION_ANNOTATION]).all == (("sad", 0.6), ("love", 0.3))


def test_no_tag_reads_nothing_and_nothing_reads_calm():
    _t, notes = parse("d'accord [EMOTION: happy 0.4]", "Mika")
    assert expression_c.READING_ANNOTATION not in notes  # rien déclaré : rien ne se lit
    _t, notes = parse("d'accord [EN_FACE: rien]", "Mika")
    assert Reading.decode(notes[expression_c.READING_ANNOTATION]) == Reading()  # « rien » : une lecture, calme
    text, notes = parse("bon [EN_FACE: happy 0.3] et [EN FACE : sad 0.7]", "Mika")
    assert "EN" not in text and Reading.decode(notes[expression_c.READING_ANNOTATION]).felt == (("sad", 0.7),)


@pytest.mark.parametrize(("label", "kind"), [
    ("excuses", reading.APOLOGIZED), ("des excuses sincères", reading.APOLOGIZED), ("un grand merci", reading.THANKED),
    ("compliment", reading.COMPLIMENTED), ("blessant", reading.INSULTED), ("des mots méchants", reading.INSULTED),
    ("décevant", reading.DISAPPOINTED), ("un oubli qui compte", reading.DISAPPOINTED),
    ("de la froideur", reading.DISAPPOINTED), ("un rejet", reading.DISAPPOINTED), ("désolée", reading.APOLOGIZED),
    ("aucun", ""), ("rien", "")])
def test_the_gesture_is_the_models_label(label, kind):
    assert reading.gesture_of(label) == kind


@pytest.mark.parametrize(("label", "kind"), [
    ("deuil", reading.MOURNING), ("maladie", reading.ILLNESS), ("un accident", reading.ILLNESS),
    ("rupture", reading.BREAKUP), ("travail", reading.JOB_LOSS), ("détresse", reading.DISTRESS),
    ("aucun", ""), ("non", ""), ("une chose très dure", reading.OTHER)])
def test_the_grave_event_is_the_models_label(label, kind):
    assert reading.grave_of(label) == kind


@pytest.mark.parametrize(("tag", "expected"), [
    ("[EMOTION:happy:0.6]", (("happy", 0.6),)),  # la forme d'avant
    ("[EMOTION: sad 0.6, anxious 0.3]", (("sad", 0.6), ("anxious", 0.3))),
    ("[EMOTION: triste 0.5]", (("sad", 0.5),)),  # un nom français : rangé
    ("**[EMOTION: love 0.8, grateful 0.4]**", (("love", 0.8), ("grateful", 0.4))),
    ("[EMOTION: neutral 0.4]", (("neutral", 0.4),)),  # le calme reste une déclaration
    ("[EMOTION:sad:0.4] puis [EMOTION: happy 0.7, amused 0.3]", (("happy", 0.7), ("amused", 0.3))),  # la dernière
])
def test_her_own_tag_has_facets(tag, expected):
    declared = parse_tag(f"bon {tag}").declared
    assert declared is not None and declared.all == expected
    assert Declared.decode(declared.encode()).all == expected


def test_what_was_declared_before_still_decodes():
    assert Declared.decode("sad:0.600") == Declared(Emotion.SAD, 0.6)
    assert Declared.decode("sad:0.600,anxious:0.300").facets == (("sad", 0.6), ("anxious", 0.3))


def test_a_reading_weighs_with_its_intensity():
    heavy, light = felt_pad((("sad", 0.8),)), felt_pad((("sad", 0.2),))
    assert heavy[0] < light[0] < 0  # « triste 0,8 » pèse plus que « triste 0,2 »
    assert felt_pad(()) == (0.0, 0.3)  # rien : calme
    assert felt_pad((("angry", 0.8),))[1] > felt_pad((("sad", 0.8),))[1]  # la colère agite, la peine non


# ── Ce qu'elle en fait ────────────────────────────────────────────────────


def live(tmp_path, reads: dict[str, str], scenario, *, mine: str = "[EMOTION: happy 0.4]", tag: bool = True,
         start=at_paris(2026, 9, 28, 14, 0)):
    """Un noyau dont le modèle lit chaque message comme ``reads`` le dit (``tag`` faux : il oublie sa balise)."""
    table = Reads(reads)

    def script(req):
        if req.role in ("extract", "profile", "compact", "narrative"):
            return LLMResponse("{}")
        if req.role in ("murmur", "journal", "dream"):
            return LLMResponse("hmm")
        if req.role == "reply" and "bonne nuit" in req.messages[-1].content:
            return LLMResponse("[SILENCE]")
        return LLMResponse(f"d'accord {mine}{table.tag(req) if req.role == 'reply' and tag else ''}")

    kernel, clock, llm, _ = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def say(kernel, handle, *texts):
    for text in texts:
        await (await kernel.perceive(said(handle, text))).reply
        await asyncio.sleep(2 * MINUTE / US)


def events(kernel, name):
    return [kernel.mind.decode(e).data for e in kernel.mind.store.read() if e.type == name]


def test_the_same_words_read_by_the_model_differ_with_the_bond(tmp_path):
    """« t'es con » : une taquinerie de Léa qui rit, une insulte d'un inconnu. Le code ne lit aucun mot : la même
    phrase, deux lectures du modèle, deux suites — l'estime ne bouge que pour l'inconnu."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Léa")
        await connect(kernel, "user_9", "Inconnu")
        await say(kernel, "user_1", "t'es con 😂")
        teased = kernel.mind.frame().get(self_c.ESTEEM)
        await say(kernel, "user_9", "t'es con")
        return teased, kernel.mind.frame().get(self_c.ESTEEM), events(kernel, self_c.TOUCHED.name)

    teased, insulted, touched = live(tmp_path, {"t'es con 😂": "amused 0.6, love 0.3",
                                                "t'es con": "angry 0.5 | geste : blessant"}, scenario)
    assert [(t.handle, t.kind) for t in touched] == [("user_9", self_c.INSULTED)]
    assert abs(teased - 0.5) < 1e-6 and insulted < teased


def test_sad_because_of_her_cools_the_relation_sad_with_her_brings_closer(tmp_path):
    """Triste *à cause* d'une amie (le modèle lit une déception : son anniversaire oublié) ou triste *avec* elle (le
    modèle la lit triste) : la même balise de Mika, deux suites (ADR 0107). La déception refroidit la relation, sans
    attachement, et lui coûte un peu d'estime ; la peine partagée la rapproche."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Inès")
        await say(kernel, "user_1", "ah zut, j'ai complètement oublié ton anniversaire", "bref, on s'en fiche")
        frame = kernel.mind.frame()
        return frame.get(affect_c.STANCE("user_1")), frame.get(self_c.ESTEEM), \
            [t.kind for t in events(kernel, self_c.TOUCHED.name)]

    sad = "[EMOTION: sad 0.6]"
    let_down, esteem, touched = live(tmp_path / "decue", {"anniversaire": "rien | geste : décevant",
                                                          "s'en fiche": "rien | geste : décevant"}, scenario, mine=sad)
    shared, untouched, none = live(tmp_path / "avec", {"anniversaire": "sad 0.7", "s'en fiche": "sad 0.6"},
                                   scenario, mine=sad)
    assert let_down.regard < 0 and let_down.bond == 0  # déçue : ni tendresse ni attachement
    assert shared.regard > 0 and shared.bond > 0  # triste avec elle : ça rapproche
    assert touched == [self_c.DISAPPOINTED] * 2 and none == []
    assert esteem < untouched == 0.5


def test_a_grave_event_read_by_the_model_worries_her_and_weighs_on_the_days(tmp_path):
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await say(kernel, "user_1", "mon père est mort cette nuit")
        frame = kernel.mind.frame()
        return events(kernel, others_c.READ.name), frame.get(memory_c.HARD_TIMES("user_1")), \
            dict(kernel.mind.root.slices["others"].concerns.items())

    reads, hard, concerns = live(tmp_path, {"mon père est mort cette nuit": "sad 0.9 | grave : deuil"}, scenario)
    (read,) = reads
    assert read.grave and read.grave_kind == reading.MOURNING and read.concern
    assert read.felt == (("sad", 0.9),) and read.valence < -0.5 and not read.cues
    assert hard > 0 and "user_1" in concerns


def test_without_its_reading_nothing_is_read(tmp_path):
    """Le modèle n'a rien déclaré (sa balise oubliée) : aucune lecture — pas une lecture neutre inventée."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await (await kernel.perceive(said("user_1", "je suis épuisée, j'en peux plus"))).reply
        return events(kernel, others_c.READ.name), events(kernel, self_c.TOUCHED.name)

    reads, touched = live(tmp_path, {}, scenario, mine="[EMOTION: sad 0.5]", tag=False)
    assert reads == [] and touched == []


def test_contagion_takes_the_persons_own_facet(tmp_path):
    """Une amie furieuse contre son patron lui laisse un peu de colère — pas de l'anxiété (une contagion réduite à
    joie, peine ou tension, avant)."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Alice")
        await say(kernel, "user_1", "mon patron m'a encore humiliée devant tout le monde")
        return events(kernel, others_c.READ.name)

    (read,) = live(tmp_path, {"mon patron m'a encore humiliée devant tout le monde": "angry 0.8, sad 0.3"},
                   scenario)
    assert read.contagion > 0 and read.contagion_emotion == "angry"


def test_a_farewell_is_recognised_on_arrival_even_when_she_stays_silent(tmp_path):
    """« Bonne nuit » : un au revoir (sa forme, pas une émotion), reconnu à l'arrivée du message — la conversation se
    clôt même si elle ne répond rien."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await say(kernel, "user_1", "tu fais quoi ?")
        await say(kernel, "user_1", "bon, bonne nuit")
        exchanges = kernel.mind.root.slices["attention"].exchanges
        return events(kernel, others_c.FAREWELL.name), exchanges.get("user_1")

    farewells, exchange = live(tmp_path, {}, scenario)
    assert [f.person for f in farewells] == ["user_1"]
    assert exchange is not None and exchange.closing


def test_a_worried_facet_of_her_own_reply_makes_her_worry(tmp_path):
    """« Ma grand-mère est partie ce matin » : le modèle n'y lit rien de lourd, mais elle y répond avec tendresse et
    une tristesse forte (« love 0,7, sad 0,65 ») — la tristesse n'est pas sa facette la plus forte, elle s'inquiète
    quand même."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Alice")
        await say(kernel, "user_1", "ma grand-mère est partie ce matin")
        return dict(kernel.mind.root.slices["others"].concerns.items())

    concerns = live(tmp_path, {}, scenario, mine="[EMOTION: love 0.7, sad 0.65]")
    assert "user_1" in concerns


def test_her_sad_reply_to_a_heavy_first_message_is_not_a_new_worry(tmp_path):
    """Le premier message d'une amie dont elle ne connaît pas encore le ton, lourd de lui-même : sa peine en lui
    répondant ne dit rien de plus que lui (le modèle n'y lit rien de grave) — l'inquiétude se décide sur sa lecture,
    pas sur sa propre tristesse (S19 : Bea, qui râle toujours, n'était plus relancée pour rien)."""
    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.CLOSE)
        await connect(kernel, "user_1", "Bea")
        await say(kernel, "user_1", "j'en ai marre, je suis épuisée")
        return dict(kernel.mind.root.slices["others"].concerns.items())

    heavy = {"j'en ai marre, je suis épuisée": "frustrated 0.5, sad 0.4"}
    assert "user_1" not in live(tmp_path / "lourd", heavy, scenario, mine="[EMOTION: sad 0.6]")
    grave = {"j'en ai marre, je suis épuisée": "frustrated 0.5, sad 0.4 | grave : détresse"}
    assert "user_1" in live(tmp_path / "grave", grave, scenario, mine="[EMOTION: sad 0.6]")


def test_she_feels_all_her_facets():
    """Ses facettes visent ensemble : « triste et en colère » n'est ni la tristesse seule ni la colère seule ; une
    seule facette vise exactement ce que visait une balise d'avant."""
    base = (0.1, 0.1, 0.0)
    sad = ph.blend(base, (("sad", 0.6),))
    both = ph.blend(base, (("sad", 0.6), ("angry", 0.3)))
    assert sad == pytest.approx(A.lerp(base, A.ANCHORS[Emotion.SAD], 0.6))
    assert both != pytest.approx(sad) and both[1] > sad[1]  # la colère agite


def test_her_mood_and_her_stance_follow_all_her_facets():
    """L'humeur et la posture visent toutes ses facettes (``mood_target_of``, ``stance_target_of``) : « triste 0,6,
    en colère 0,4 » ne vise pas où vise « triste 0,6 » seule ; une seule facette, là où visait la balise d'avant."""
    p = AffectParams()
    mood = ph.Mood(ph.Osc((0.1, 0.1, 0.0), ph.ZERO, 0))
    stance = ph.Stance(ph.Osc((0.1, 0.1, 0.0), ph.ZERO, 0))
    alone, mixed = Declared(Emotion.SAD, 0.6), Declared.of((("sad", 0.6), ("angry", 0.4)))
    assert ph.mood_target_of(mood, alone, p) == pytest.approx(ph.mood_target(mood, Emotion.SAD, 0.6, p))
    assert ph.mood_target_of(mood, mixed, p) != pytest.approx(ph.mood_target_of(mood, alone, p))
    assert ph.stance_target_of(stance, mixed) != pytest.approx(ph.stance_target_of(stance, alone))


def test_her_face_shows_her_declared_ambivalence():
    face = affect_c.Face(Emotion.HAPPY, 0.3, ((Emotion.HAPPY, 0.3), (Emotion.PLAYFUL, 0.2)), (Emotion.HAPPY, 0.3),
                         (Emotion.HAPPY, 0.3))
    frame = NS(get=lambda key: "user_1" if key.name == "identity.person" else face)
    view = emotion_view(frame, "user_1", Declared.of((("sad", 0.6), ("love", 0.3))))
    assert view.emotion == "sad" and view.blend == (("sad", 0.6), ("love", 0.3))


def test_a_painful_date_is_heavy_by_what_is_felt_and_a_death_never_festive():
    """Une date annuelle que la personne vit douloureusement (son ressenti, jugé par la relecture) pèse, même sans
    deuil (« l'anniversaire de leur séparation ») ; un moment qui parle d'une mort (un fait, pas une émotion) ne se
    fête jamais, ressenti oublié ou non ; un anniversaire, si."""
    split = x.XEvenement(texte="l'anniversaire de leur séparation", quand="2026-11-02", chaque_annee=True,
                         ressenti={"sad": 0.7})
    death = x.XEvenement(texte="l'anniversaire de la mort de son père", quand="2026-11-02", chaque_annee=True)
    birthday = x.XEvenement(texte="son anniversaire de 30 ans", quand="2026-11-02", chaque_annee=True)
    assert x.moment_importance(split) >= x.IMPORTANCE[4] and not x.festive(split)
    assert x.moment_importance(death) >= x.IMPORTANCE[4] and not x.festive(death)
    assert x.festive(birthday) and x.moment_importance(birthday) < x.IMPORTANCE[4]


# ── Aucun mot ne devine une émotion ───────────────────────────────────────

#: des mots d'humeur ou d'insulte qu'une liste aurait cherchés dans un message (repliés au besoin) : aucun ne doit
#: paraître dans une chaîne du code de Mika (ses phrases vivent dans ``persona/voix.yaml`` ; les noms que le modèle
#: écrit se rangent dans ``vocab``)
LEXICON = ("triste", "déprim", "deprim", "j'en ai marre", "ras le bol", "connard", "connasse", "ta gueule",
           "insupportable", "trop bien", "génial", "genial", "youpi", "putain")


#: des listes de mots qui ne devinent aucune émotion : ce que chacune fait
NOT_GUESSING = {
    "faculties/identity/detection.py": "« je suis triste » n'est pas un prénom : des états écartés des noms",
    "faculties/identity/corroboration.py": "des mots vides, écartés avant de comparer deux récits",
    "faculties/memory/recall.py": "des politesses (« bonne nuit », « génial ») qui ne désignent rien à rappeler",
}


def _strings(path: Path) -> list[tuple[int, str]]:
    """Les chaînes du code, sauf les docstrings et ce qu'on dit d'un réglage à la console (``Knob``, ``Field``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("Knob", "Field"):
            skip |= {id(sub) for sub in ast.walk(n)}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def test_nothing_in_her_code_guesses_an_emotion_from_words():
    """Les lectures des mots sont parties (``others/tone.py``, ``self/worth.py``) et ne reviennent pas : aucune chaîne
    du code de ses facultés, de ses plugins ou du runtime ne cherche un mot d'humeur ou d'insulte. Le simulateur, qui
    joue le modèle, en a le droit."""
    assert not (SRC / "faculties" / "others" / "tone.py").exists()
    assert not (SRC / "faculties" / "self" / "worth.py").exists()
    found = []
    for root in ("faculties", "plugins", "runtime", "app"):
        for path in sorted((SRC / root).rglob("*.py")):
            if str(path.relative_to(SRC)) in NOT_GUESSING:
                continue
            for line, text in _strings(path):
                low = text.lower()
                found += [f"{path.relative_to(SRC)}:{line} « {w} »" for w in LEXICON if w in low]
    assert found == []


def test_the_guard_sees_a_lexicon(tmp_path):
    """La garde n'est pas vide : elle voit une liste de mots dans une chaîne, pas dans l'aide d'un réglage ; et ses
    exceptions nomment des fichiers qui existent."""
    code = tmp_path / "lexique.py"
    code.write_text('HEAVY = ("triste", "marre")\nK = Knob(help="une amie triste")\n', encoding="utf-8")
    assert [t for _l, t in _strings(code)] == ["triste", "marre"]
    assert all((SRC / rel).is_file() for rel in NOT_GUESSING)


