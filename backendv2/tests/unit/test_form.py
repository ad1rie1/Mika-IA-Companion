"""La forme n'a qu'une maison : l'autrice du flux (ADR 0140).

- la consigne de style ne dit plus la forme (longueur, registre, émojis, mise en forme) : le rôle, la discipline, le
  protocole seulement ;
- sans seconde passe, les codes de l'autrice du chat entrent dans le premier jet (« COMMENT TU ÉCRIS ICI »), et la
  mesure d'une réponse courte se rappelle ;
- avec une seconde passe, le premier jet n'en reçoit rien : l'autrice lit ses codes et met en forme.
"""

from __future__ import annotations

from mika.faculties.expression import style
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import CHARACTER, befriend, boot, build, said

CODES = phrase("expression.author.defaults.message.codes")
FORM_WORDS = ("émoji", "une à trois phrases", "voix haute", "pas de listes", "registre de la personne")


def test_the_style_keeps_the_protocol_and_the_discipline_and_leaves_the_form_to_the_author():
    text = style().lower()
    assert not any(w in text for w in FORM_WORDS), [w for w in FORM_WORDS if w in text]
    assert "[emotion: …]" in text and "[silence]" in text and "une seule à la fois" in text
    assert "pas à un guichet" in text
    # toute la forme est dans les codes de l'autrice livrée « Message »
    codes = CODES.lower()
    assert "émoji" in codes and "pas de listes" in codes and "registre de la personne" in codes
    assert "quelques mots" in codes and "écriture inclusive" in codes


def _respond(req: LLMRequest) -> LLMResponse:
    if req.role == "character":
        return LLMResponse(CHARACTER)
    if req.role == "polish":
        return LLMResponse("Mika : ok [EMOTION:happy:0.3]\nL'autre : cool")
    return LLMResponse("d'accord, je note tout ça pour la suite [EMOTION:neutral:0.3]")


def _prompts(tmp_path, *, polish: bool):  # type: ignore[no-untyped-def]
    kernel, clock, llm, _out = build(tmp_path, _respond, polish=polish)

    async def main():  # type: ignore[no-untyped-def]
        await boot(kernel)
        try:
            await befriend(kernel, "user_1")
            await (await kernel.perceive(said("user_1", "coucou"))).reply
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    reply = [c for c in llm.calls if c.role == "reply"][-1]
    polished = [c for c in llm.calls if c.role == "polish"]
    return reply.system_stable, reply.messages[-1].content, polished


def test_without_a_second_pass_the_authors_codes_enter_the_first_draft(tmp_path):
    stable, last, polished = _prompts(tmp_path, polish=False)
    assert not polished
    assert phrase("expression.form.title") in stable and CODES in stable
    assert phrase("expression.answer.short") in last  # « coucou » : réponds court, à la même mesure


def test_with_a_second_pass_the_first_draft_hears_nothing_of_the_form(tmp_path):
    stable, last, polished = _prompts(tmp_path, polish=True)
    assert polished, "la seconde passe a tourné"
    assert phrase("expression.form.title") not in stable and CODES not in stable
    assert phrase("expression.answer.short") not in last
    assert CODES in polished[-1].system_stable  # c'est l'autrice qui lit ses codes
