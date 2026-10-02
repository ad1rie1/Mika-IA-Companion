"""Elle s'entend se répéter : une même ouverture, une même formule, un bonjour redit à quelqu'un qu'elle vient de
saluer. La consigne de style ne suffit pas — un vrai modèle a ouvert quatre réponses sur cinq par « Adrien… Je
t'entends dire que… » (sonde du 2026-10-02) : elle se relit, et le prompt le lui dit."""

from __future__ import annotations

import asyncio

from mika.faculties.expression import repeats
from mika.kernel.clock import HOUR, MINUTE
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said

M = MINUTE

SAME_OPENING = [
    "Adrien… Je sais que tu viens de finir ton entretien, et je voulais juste être là pour toi",
    "Adrien… Je t'entends dire que ce n'était pas fou",
    "Je comprends tout à fait. Tu n'as pas à en parler si tu n'en as pas envie",
    "Adrien… Je t'entends dire ça, et ça me fait quelque chose, vraiment.",
]


def test_the_same_opening_is_heard():
    found = repeats([(i * M, t) for i, t in enumerate(SAME_OPENING)], 10 * M)
    assert found and "« Adrien… Je »" in found[0]


def test_the_same_formula_is_heard():
    said_ = [(0, "haha oui, tu vas tout déchirer jeudi"), (M, "franchement tu vas tout déchirer"),
             (2 * M, "t'inquiète, tu vas tout déchirer, je le sens")]
    assert any("tu vas tout déchirer" in f for f in repeats(said_, 3 * M))


def test_an_ordinary_conversation_is_not_flagged():
    """Contre-exemple : des messages variés ne déclenchent rien."""
    said_ = [(0, "Salut ! ça va ?"), (M, "Haha trop bien"), (2 * M, "Ah oui je vois"), (3 * M, "Pas mal ton idée")]
    assert repeats(said_, 4 * M) == []


def test_saying_hello_twice_is_heard_but_not_the_next_day():
    assert repeats([(0, "Salut Adrien ! Ça te dirait de papoter ?")], 5 * M)
    assert repeats([(0, "Salut Adrien !")], 20 * HOUR) == [], "le lendemain, on se redit bonjour"


def test_the_reply_prompt_tells_her_she_repeats_herself(tmp_path):
    """Un modèle qui ouvre toujours pareil : à la troisième réponse, le prompt le lui fait remarquer ; à la
    première, rien (contre-exemple)."""
    def respond(req):
        if req.role in ("extract", "profile"):
            return LLMResponse("{}")
        return LLMResponse("Adrien… Je t'entends dire ça. [EMOTION:thinking:0.4]")

    kernel, clock, llm, _ = build(tmp_path, respond, start=at_paris(2026, 9, 28, 15, 0))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / 1e6)
        for text in ("ça va pas fort", "j'ai raté mon examen", "je sais pas quoi faire"):
            await (await kernel.perceive(said("user_1", text))).reply
            await asyncio.sleep(90)
        await kernel.stop()

    run_virtual(clock, main)
    prompts = [c.messages[-1].content for c in llm.calls if c.role == "reply"]
    assert "CE QUE TU TE RÉPÈTES" not in prompts[0]
    assert "CE QUE TU TE RÉPÈTES" in prompts[-1] and "« Adrien… Je »" in prompts[-1]


def test_three_long_messages_in_a_row_are_heard():
    long = "Oh wow, " + "c'est vraiment une super nouvelle et je suis tellement contente pour toi, " * 6
    assert any("longs" in f for f in repeats([(0, long), (M, long + " encore"), (2 * M, long + " et puis")], 3 * M))
    # contre-exemple : un long message entre deux courts
    assert not any("longs" in f for f in repeats([(0, "ah ok"), (M, long), (2 * M, "haha")], 3 * M))


def test_the_same_way_of_coming_to_someone_is_heard_across_conversations():
    """« Yooo, Adrien ! » en tête de chaque initiative, un soir après l'autre (sonde finale : six fois) : entre deux,
    une conversation entière — seul le relevé de ses initiatives le voit. Contre-exemple : des façons variées."""
    same = ["Yooo, Adrien ! Te voilà ~", "Yooo, Adrien ! Contente de te voir", "Yooo, Adrien ! Te revoilà"]
    found = repeats([(0, "ah ok"), (M, "haha")], 2 * M, same)
    assert any("Yooo, Adrien" in f and "quand c'est toi qui viens" in f for f in found)
    varied = ["Yooo, Adrien !", "Hey toi, ça va ?", "Coucou Adrien"]
    assert not any("quand c'est toi qui viens" in f for f in repeats([(0, "ah ok")], M, varied))
    # deux sur trois, même séparées (sonde : « Yooo, te revoilà », « Hey Adrien », « Yooo, te revoilà »)
    apart = ["Yooo, te revoilà !", "Hey Adrien ~", "Yooo, te revoilà ~"]
    assert any("« Yooo, te »" in f for f in repeats([(0, "ah ok")], M, apart))
