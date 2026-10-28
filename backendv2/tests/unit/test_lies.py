"""Elle peut mentir, et ça lui pèse (ADR 0076) — par ses intentions.

- « Alice compte partir ? » — « Aucune idée, honnêtement. » : elle botte en touche par un mensonge, qu'elle marque ;
  la marque ne part jamais (même coupée, même si elle dit ce qu'elle cache) ;
- ça lui pèse : une pensée gênée (« J'ai menti à Bob »), qui la touche, sans la pousser à lui réécrire ;
- elle s'en souvient, étiqueté mensonge : ce qu'on lui a demandé et ce qu'elle a répondu de faux — jamais ce
  qu'elle cachait —, devant Bob seulement, et sans que ça se devine ailleurs ;
- la relecture sait que cette réplique ne dit pas le vrai.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import _birth_felt
from mika.faculties.expression import parse
from mika.faculties.memory import consolidation as cons
from mika.faculties.memory.extraction import Conversation, Line, Speaker, render
from mika.faculties.memory.lies import false_part
from mika.kernel.clock import HOUR, US
from mika.kernel.events import Content
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script as MemoryScript
from tests.fixtures.memory import chat as memory_chat
from tests.fixtures.memory import section
from tests.fixtures.mika import at_paris, befriend, boot, build, connect
from tests.unit.test_knowledge_coherence import FRAME
from tests.unit.test_life_of_others import Script, chat, events, run, started

ASKED = "Alice compte partir de sa boîte ?"
REVIENT = "CE QUI TE REVIENT"
LIE = "Aucune idée, honnêtement. Tu lui as demandé ? [MENSONGE: aucune idée] [EMOTION:embarrassed:0.3]"


# ── la marque ─────────────────────────────────────────────────────────────


def test_the_mark_never_leaves_and_only_the_false_passage_is_kept():
    text, ann = parse(LIE, "Mika")
    assert text == "Aucune idée, honnêtement. Tu lui as demandé ?"
    assert false_part(text, ann[expression_c.LIE_ANNOTATION]) == "Aucune idée, honnêtement."
    assert ann[expression_c.EMOTION_ANNOTATION].startswith("embarrassed")
    # une marque coupée, qui dit ce qu'elle cache : rien n'en part, rien n'en est gardé
    text, ann = parse("Franchement je sais pas. [EMOTION:thinking:0.3] [MENSONGE: elle cherche chez Ubisoft", "Mika")
    assert text == "Franchement je sais pas." and "Ubisoft" not in repr(ann)
    assert parse("Non, rien de spécial [mensonge] [EMOTION:neutral:0.2]", "Mika")[0] == "Non, rien de spécial"
    assert expression_c.LIE_ANNOTATION not in parse("Salut ! [EMOTION:happy:0.5]", "Mika")[1]



def test_a_mark_on_what_she_said_before_designates_nothing_in_this_reply():
    """ADR 0108 : au tour suivant, sans trace de sa recherche dans le fil, elle a cru avoir inventé sa réponse
    précédente et l'a marquée mensonge — dans une réponse qui, elle, disait vrai (les prévisions de Météo-France).
    Une marque qui cite une phrase absente de cette réponse ne désigne rien : aucun mensonge n'est retenu.
    Contre-exemple : la même phrase, dite dans cette réponse, est bien le passage faux."""
    previous = "J'ai regardé les prévisions pour demain, mercredi 14 octobre à Paris."
    reply = ("Je dois te corriger : mon message précédent était inventé. Je n'avais rien regardé. Demain, mercredi, il "
             f"fera environ 11 degrés vers 8 heures. [MENSONGE: {previous}] [EMOTION:embarrassed:0.5]")
    text, ann = parse(reply, "Mika")
    assert "MENSONGE" not in text and expression_c.LIE_ANNOTATION not in ann
    text, ann = parse(f"{previous} Il fera beau. [MENSONGE: {previous}] [EMOTION:embarrassed:0.3]", "Mika")
    assert false_part(text, ann[expression_c.LIE_ANNOTATION]) == previous
    # une marque sans phrase (« j'ai menti ici ») désigne toute la réponse
    text, ann = parse("Non, rien de spécial. [mensonge] [EMOTION:neutral:0.2]", "Mika")
    assert false_part(text, ann[expression_c.LIE_ANNOTATION]) == text

def test_lying_weighs_on_her_mood():
    thought = SimpleNamespace(data=attention_c.ThoughtBorn(text=Content.of("J'ai menti à Bob."), emotion="embarrassed",
                                                           intensity=0.45, origin=attention_c.LIE, about=("ext_1",)))
    felt = _birth_felt(thought, SimpleNamespace(params=None))
    assert felt is not None and felt.emotion.value == "embarrassed" and felt.intensity > 0


# ── de bout en bout ───────────────────────────────────────────────────────


def test_she_lies_to_deflect_feels_it_and_remembers_it_as_a_lie(tmp_path):
    script = Script(reply=lambda m: LIE if "partir" in m else None)

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", [ASKED], channel="external", display_name="Bob")
        await asyncio.sleep(6 * HOUR / US)
        store = kernel.mind.store
        said = [e for e in events(kernel, rt.UTTERANCE.name) if e.data.target == "ext_1"]
        born = [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.LIE]
        kept = [e for e in events(kernel, memory_c.REMEMBERED.name) if e.data.lie]
        texts = store.content([e.data.text.ref for e in (*said, *born, *kept)])
        return said, born, kept, texts, started(kernel, attention_c.THOUGHT)

    said, born, kept, texts, insisted = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    assert len(said) == 1 and texts[said[0].data.text.ref] == "Aucune idée, honnêtement. Tu lui as demandé ?"
    assert said[0].data.annotation(expression_c.LIE_ANNOTATION) is not None
    # ça lui pèse
    assert len(born) == 1 and born[0].data.about == ("ext_1",) and texts[born[0].data.text.ref] == "J'ai menti à Bob."
    assert insisted == [], "une gêne qu'elle porte, pas une raison de lui réécrire"
    # elle s'en souvient, étiqueté mensonge : la question et sa réponse fausse, rien de ce qu'elle cachait
    assert len(kept) == 1
    d = kept[0].data
    assert d.secret and d.about == ("ext_1",) and d.told_by == () and d.emotion == "embarrassed"
    assert texts[d.text.ref] == (f"Bob m'a demandé : « {ASKED} » — je lui ai menti en répondant : "
                                 "« Aucune idée, honnêtement ».")


# ── devant qui il ressort ─────────────────────────────────────────────────


def test_a_lie_comes_back_before_the_person_only_and_is_never_guessed_elsewhere(tmp_path):
    """Bob redemande : elle se souvient de lui avoir menti (pour ne pas se contredire, ou avouer). Carol, une proche,
    parle de Bob : rien ne revient, pas même une ligne vague (« Bob t'a confié… » serait faux, et le trahirait)."""
    script = MemoryScript(reply=lambda m: LIE if "partir" in m and "vraiment" not in m else None)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_3", "Bob")
        await connect(kernel, "user_4", "Carol")
        await befriend(kernel, "user_3", "close")
        await befriend(kernel, "user_4", "close")
        await memory_chat(kernel, "user_3", [ASKED])
        await asyncio.sleep(HOUR / US)
        await memory_chat(kernel, "user_3", ["tu sais vraiment rien, pour Alice, partir de sa boîte ?"])
        await memory_chat(kernel, "user_4", ["Bob m'a parlé d'Alice, il voulait savoir si elle compte partir"])
        await kernel.stop()

    run_virtual(clock, main)
    to_bob = section(script.replies("user_3")[-1], REVIENT)
    assert "je lui ai menti en répondant : « Aucune idée, honnêtement »" in to_bob
    assert "J'ai menti à Bob." in script.replies("user_3")[-1], "et ça lui pèse, devant lui"
    to_carol = "\n".join(script.prompts("user_4"))
    assert "ai menti" not in to_carol and "Bob t'a confié" not in to_carol


def test_a_lie_thought_mulled_over_at_night_stays_a_secret():
    """« Après y avoir repensé cette nuit : J'ai menti à Bob » reste à Bob, comme la pensée."""
    import json

    from mika.faculties.memory.night import _disclosure

    thought = SimpleNamespace(seq=40, type=attention_c.THOUGHT_BORN.name, data=json.dumps(
        {"origin": attention_c.LIE, "about": ["user_3"], "sensitivity": 2, "source": 39, "sources": []}))

    class Store:
        def query_mind(self, sql, args=()):
            return []

        def get_events(self, seqs):
            return [thought] if list(seqs) == [40] else []

    rules, _internal = _disclosure(FRAME, Store(), 40)
    assert any(r.secret and r.about == ("user_3",) for r in rules)


# ── la relecture ──────────────────────────────────────────────────────────


def test_the_extraction_knows_her_lied_line_is_not_true():
    class Store:
        def get_events(self, seqs):
            return [SimpleNamespace(seq=11, type=rt.UTTERANCE.name,
                                    data='{"annotations": [["emotion", "embarrassed:0.300"], ["lie", "0:25"]]}'),
                    SimpleNamespace(seq=12, type=rt.UTTERANCE.name, data='{"annotations": []}')]

    lines = (Line(10, FRAME.now, "Bob [P1]", ASKED, "ext_1"), Line(11, FRAME.now, "Mika", "Aucune idée, honnêtement."),
             Line(12, FRAME.now, "Mika", "Tu lui as demandé ?"))
    conv = cons._her_lines(Store(), Conversation("private:ext_1", (Speaker("P1", "ext_1", "Bob"),), lines))
    assert [ln.lie for ln in conv.lines] == [False, True, False]
    text = render(conv, now=FRAME.local(), beliefs=(), promises=())
    assert "Mika : Aucune idée, honnêtement. (un mensonge)" in text and "demandé ? (un mensonge)" not in text
