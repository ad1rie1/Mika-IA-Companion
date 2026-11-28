"""Son caractère, écrit par le modèle d'après sa matrice (ADR 0139).

- au démarrage d'une vie, le processus ``self.character`` l'écrit une fois, et sa persona le porte partout ;
- il se réécrit quand le tempérament change, jamais autrement ;
- ce qui n'est pas un caractère (une balise, un refus, du vide) ne s'écrit pas, et rien ne le remplace ;
- le modèle qui l'écrit lit ses traits mesurés ; celui qui parle, le texte seul.
"""

from __future__ import annotations

import asyncio

from mika.contracts import self_ as self_c
from mika.faculties.self.character import written
from mika.faculties.self.faculty import SELF
from mika.kernel.events import Origin, VoiceProvenance
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab import temperament as T
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import DOC, befriend, boot, build, said

CHARACTER = "Tu prends le temps avant de répondre, et tu repenses longuement à ce qui t'a marquée."
OTHER = "Tu réagis au quart de tour, et tu le montres : un mot te fait bondir, rire ou t'indigner."


class Writer:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls: list[LLMRequest] = []

    def __call__(self, req: LLMRequest) -> LLMResponse:
        if req.role == "character":
            self.calls.append(req)
            return LLMResponse(self.texts.pop(0) if self.texts else "")
        return LLMResponse("ok [EMOTION:happy:0.3]")


def _live(tmp_path, writer: Writer, scenario):  # type: ignore[no-untyped-def]
    kernel, clock, llm, _out = build(tmp_path, writer)

    async def main():  # type: ignore[no-untyped-def]
        await boot(kernel)
        try:
            await asyncio.sleep(1)
            return await scenario(kernel, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def test_her_character_is_written_once_at_the_start_and_enters_every_persona(tmp_path):
    writer = Writer([CHARACTER])

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        frame = kernel.mind.frame()
        return frame.get(self_c.CHARACTER), [c for c in llm.calls if c.role == "reply"][-1]

    got, reply = _live(tmp_path, writer, scenario)
    assert got == CHARACTER and len(writer.calls) == 1
    assert phrase("self.character.frame", text=CHARACTER) in reply.system_stable
    # ce que lit celui qui l'écrit : ses traits mesurés, chacun avec sa phrase ; celui qui parle : jamais une mesure
    shown = "\n".join(m.content for m in writer.calls[0].messages)
    assert phrase("self.temperament.name.introspection") + " : 50 %" in shown
    assert phrase("self.temperament.name.introspection") + " :" not in reply.system_stable
    assert " % — " not in reply.system_stable and phrase("self.temperament.family.feel") not in reply.system_stable


def test_it_is_rewritten_when_her_temperament_changes_and_never_otherwise(tmp_path):
    writer = Writer([CHARACTER, OTHER])

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        before = kernel.mind.frame().get(self_c.CHARACTER)
        # la même persona enregistrée de nouveau : rien à réécrire
        await kernel.mind.append([self_c.PERSONA_REVISED.draft(persona=DOC)], emitter="self",
                                 correlation="persona:1", origin=Origin.EXTERNAL)
        await asyncio.sleep(1)
        same = kernel.mind.frame().get(self_c.CHARACTER)
        nervous = DOC.model_copy(update={"temperament": T.apply_profile(T.Temperament(), "nerveuse")})
        await kernel.mind.append([self_c.PERSONA_REVISED.draft(persona=nervous)], emitter="self",
                                 correlation="persona:2", origin=Origin.EXTERNAL)
        pending = kernel.mind.frame().get(self_c.CHARACTER)  # l'ancien texte ne vaut pas pour le nouveau tempérament
        await asyncio.sleep(1)
        return before, same, pending, kernel.mind.frame().get(self_c.CHARACTER)

    before, same, pending, after = _live(tmp_path, writer, scenario)
    assert before == same == CHARACTER and pending == "" and after == OTHER
    assert len(writer.calls) == 2


def test_what_is_not_a_character_is_not_written_and_nothing_replaces_it(tmp_path):
    writer = Writer(["[SILENCE]", "{}", ""])

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        await befriend(kernel, "user_1")
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        return kernel.mind.frame().get(self_c.CHARACTER), [c for c in llm.calls if c.role == "reply"][-1]

    got, reply = _live(tmp_path, writer, scenario)
    assert got == "" and "Ton caractère" not in reply.system_stable and "%" not in reply.system_stable
    assert phrase("self.temperament.name.introspection") not in reply.system_stable


def test_a_model_that_never_writes_one_is_asked_less_and_less_often(tmp_path):
    """Un modèle qui ne rend rien d'utilisable n'est pas rappelé chaque minute : une minute, deux, quatre, huit…
    (cinq appels en seize minutes, pas dix-sept) ; un tempérament qui change remet le compte à zéro."""
    writer = Writer([])  # toujours vide : jamais un caractère

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        await asyncio.sleep(16 * 60)
        before = len(writer.calls)
        nervous = DOC.model_copy(update={"temperament": T.apply_profile(T.Temperament(), "nerveuse")})
        await kernel.mind.append([self_c.PERSONA_REVISED.draft(persona=nervous)], emitter="self",
                                 correlation="persona:2", origin=Origin.EXTERNAL)
        await asyncio.sleep(1)
        return before, len(writer.calls)

    before, after = _live(tmp_path, writer, scenario)
    assert before == 5 and after == 6  # 0, 1, 3, 7, 15 min ; puis tout de suite pour le nouveau tempérament


def _kept(text: str):  # type: ignore[no-untyped-def]
    """Un caractère gardé avant que l'écriture ne retire les balises (« … [EMOTION:happy:0.7] »), pour la persona
    courante : ce que porte un journal d'avant la correction."""
    async def keep(kernel):  # type: ignore[no-untyped-def]
        basis = self_c.character_basis(kernel.mind.frame().state("self").persona)
        await kernel.mind.append([self_c.CHARACTER_WRITTEN.draft(
            text=text, basis=basis, voice=VoiceProvenance(call_id="old#0", persona_hash="", role="character",
                                                          model="old"))], emitter="self", correlation="character:old")
    return keep


def test_a_character_kept_with_its_tag_is_shown_and_given_without_it(tmp_path):
    """Un caractère déjà gardé avec sa balise ne se réécrit pas tant que sa persona ne change pas : il se relit sans
    elle, dans le fait que lisent sa persona et la console — sans appel au modèle."""
    writer = Writer([])

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        await _kept(f"{CHARACTER} [EMOTION:happy:0.7]")(kernel)
        asked = len(writer.calls)
        await befriend(kernel, "user_1")
        await (await kernel.perceive(said("user_1", "coucou"))).reply
        await asyncio.sleep(3600)
        reply = [c for c in llm.calls if c.role == "reply"][-1]
        return kernel.mind.frame().get(self_c.CHARACTER), reply, len(writer.calls) - asked

    got, reply, asked_again = _live(tmp_path, writer, scenario)
    assert got == CHARACTER and asked_again == 0
    assert phrase("self.character.frame", text=CHARACTER) in reply.system_stable
    assert "[EMOTION:happy:0.7]" not in reply.system_stable


def test_a_kept_tag_that_was_all_of_it_is_not_a_character_and_is_written_again(tmp_path):
    """Le texte du faux modèle de test_views_in_french : sans sa balise, il reste « Oh, bonne nouvelle ! », qui n'est
    pas un caractère — il ne vaut rien, et le processus en écrit un."""
    writer = Writer(["", CHARACTER])

    async def scenario(kernel, llm):  # type: ignore[no-untyped-def]
        await _kept("Oh, bonne nouvelle ! [EMOTION:happy:0.7]")(kernel)
        kept = kernel.mind.frame().get(self_c.CHARACTER)
        await asyncio.sleep(3600)
        return kept, kernel.mind.frame().get(self_c.CHARACTER)

    kept, after = _live(tmp_path, writer, scenario)
    assert kept == "" and after == CHARACTER and len(writer.calls) == 2


def test_written_keeps_prose_only():
    assert written(f"  {CHARACTER}\n\n[EMOTION: happy 0.3]") == CHARACTER
    # au bout de sa dernière phrase, aussi : il entre dans sa persona partout, et la console le montrait avec sa
    # balise (« Oh, bonne nouvelle ! [EMOTION:happy:0.7] », test_views_in_french, rouge depuis l'ADR 0139)
    assert written(f"{CHARACTER} [EMOTION: happy 0.3]") == CHARACTER
    assert written("[SILENCE]") == written("{}") == written("") == written(None) == written("Non.") == ""
    assert len(written("x" * 5000)) == 2000


def test_the_slice_whose_reducer_reads_the_character_again_is_rebuilt() -> None:
    """Un instantané d'avant le nettoyage des balises garde le caractère tel quel : il ne vaut plus un rejeu complet
    du même journal, et la tranche se reconstruit depuis la genèse."""
    assert SELF.state_version >= 14
