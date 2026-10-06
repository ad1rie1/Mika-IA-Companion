"""Sa persona, par ses intentions.

- elle est une IA et le sait : demandé sincèrement, elle ne le cache pas et
  ne se prétend pas humaine — sans en faire un sujet ni une excuse ;
- ses manies sont des manies, pas une signature : de temps en temps, jamais
  deux fois dans la même conversation ; rien n'est « toujours » ;
- un fuseau inconnu est refusé à l'entrée (accepté, il mettait en panne la
  console et la conversation) ; un journal écrit avant cette règle se rejoue.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from pydantic import ValidationError

from mika.contracts import self_ as self_c
from mika.faculties.self import interjections, render
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.codec import canonical_json
from mika.kernel.events import EventRegistry
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script, chat
from tests.fixtures.mika import DOC, at_paris, befriend, boot, build, connect, said
from tests.fixtures.mika import PERSONA_PATH as PATH


def test_she_knows_she_is_an_ai_and_does_not_make_it_a_topic():
    for depth in ("full", "compact"):
        text = render(DOC, depth)
        assert "Tu es une IA" in text and "tu ne prétends pas être humaine" in text
        assert "jamais « en tant qu'IA »" in text and "jamais d'avertissement" in text
        assert "Tu es une personne" not in text  # contrôle : l'ancienne phrase lui faisait nier sa nature


def test_her_quirks_are_occasional_and_nothing_is_always():
    text = render(DOC, "full")
    assert "Tes manies — de temps en temps, jamais deux fois dans la même conversation :" in text
    raw = PATH.read_text(encoding="utf-8").split("\n# Huit curseurs")[0]
    document = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    assert "toujours" not in document.lower()  # une tendance, jamais une obligation
    assert "digression" in DOC.tone and "le reste du temps" in DOC.tone  # elle digresse quand ça l'emballe


@pytest.mark.parametrize("zone", ["Pas/UnFuseau", "", "../etc/passwd", "Europe/", "europe/paris"])
def test_an_unknown_timezone_is_refused(zone):
    with pytest.raises(ValidationError, match="fuseau horaire inconnu"):
        self_c.PersonaDoc(timezone=zone)


def test_a_known_timezone_is_kept_trimmed():
    assert self_c.PersonaDoc(timezone=" America/Montreal ").timezone == "America/Montreal"


def test_a_persona_journaled_before_the_rule_still_replays():
    """Un journal d'avant la validation peut porter un fuseau illisible : le
    rejeu ne casse pas, il retombe sur le fuseau par défaut — et un fuseau
    valide est gardé tel quel."""
    old = {"persona": {**DOC.model_dump(mode="json"), "timezone": "Pas/UnFuseau"}}
    raw = self_c.PERSONA_REVISED.upcast(1, old)
    assert self_c.PersonaRevised.model_validate(raw).persona.timezone == self_c.DEFAULT_ZONE
    kept = self_c.PERSONA_REVISED.upcast(1, {"persona": {**DOC.model_dump(mode="json"),
                                                         "timezone": "Asia/Tokyo"}})
    assert self_c.PersonaRevised.model_validate(kept).persona.timezone == "Asia/Tokyo"
    assert canonical_json(self_c.PersonaRevised.model_validate(kept).persona.temperament) == \
        canonical_json(DOC.temperament)


# ── Sa vie d'IA, ses goûts, sa façon de dire bonjour (ADR 0047, HUM-6 / HUM-9 / HUM-23) ──


FOOD = ("mang", "boi", " bu ", "cuisin", "café", "ramen", "recette", "cookies", "bouffe", "pizza")
#: ce qui dit qu'elle le vit à sa façon d'IA (en théorie, sans y goûter) — ou que c'est un avis
LIVED_HER_WAY = ("théorie", "jamais", "ne mange", "sans en avoir", "fait tester", "fait cuisiner", "c'est non",
                 "contre", "avis", "n'a jamais goûté", "plat préféré")


def test_her_life_is_an_ais_life_and_her_tastes_do_not_move():
    """Sa vie d'IA VTuber est rédigée — ce qu'elle fait à sa façon, ses goûts, ce qui est vrai d'elle — et rendue
    quand elle parle : « t'as mangé quoi ? » deux fois à une semaine d'intervalle trouve la même réponse dans son
    portrait (elle ne mange pas, elle le vit en théorie), « ton plat préféré ? » aussi. Contre-exemple : rien
    dans son portrait ne lui fait cuisiner ni boire pour de vrai (« sa recette de cookies ratée »)."""
    full = render(DOC, "full")
    assert "Ta vie, à ta façon :" in full and "Tes goûts et tes avis" in full and "Ce qui est vrai de toi :" in full
    assert "ramen" in full and "ne mange pas" in full
    assert "d'un jour à l'autre" in full
    assert "ramen" not in render(DOC, "compact")  # sa voix intérieure, ses séances : pas besoin
    entries = [DOC.description, DOC.tone, *DOC.traits, *DOC.quirks, *DOC.interests, *DOC.life, *DOC.tastes,
               *DOC.facts]
    physical = [e for e in entries if any(w in e.lower() for w in FOOD)
                and not any(m in e.lower() for m in LIVED_HER_WAY)]
    assert not physical, f"une vie physique, incompatible avec sa nature : {physical}"
    # une persona sans vie rédigée garde la règle d'avant
    bare = render(self_c.PersonaDoc(name="Zoé"), "full")
    assert "tu n'inventes pas de faits durables" in bare and "Ta vie, à ta façon" not in bare


def test_a_persona_journaled_before_her_life_was_written_still_replays():
    old = {k: v for k, v in DOC.model_dump(mode="json").items() if k not in ("life", "tastes", "facts")}
    doc = self_c.PersonaRevised.model_validate({"persona": old}).persona
    assert doc.life == doc.tastes == doc.facts == () and doc.greetings == DOC.greetings


def test_her_greetings_set_the_tone_of_a_greeting_and_are_never_given_as_lines_to_copy(tmp_path):
    """Ses façons de dire bonjour servaient à rien (HUM-23) : elles donnent maintenant le ton quand elle salue
    quelqu'un qui arrive — des exemples, jamais à recopier. Contre-exemple : ni sa persona stable ni une réponse
    ordinaire ne les montrent (elle les redirait à chaque message)."""
    def script(req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        return LLMResponse("hey ! [EMOTION:happy:0.5]")

    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 19, 0))

    async def main():
        await boot(kernel)
        try:
            await befriend(kernel, "user_1", "friend")
            await connect(kernel, "user_1", "Adrien")
            await asyncio.sleep(HOUR / US)
            await (await kernel.perceive(said("user_1", "ça va ?"))).reply
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    greets = [c for c in llm.calls if c.role == "initiative"]
    replies = [c for c in llm.calls if c.role == "reply"]
    assert greets and replies
    shown = greets[0].messages[-1].content
    assert "TA FAÇON DE DIRE BONJOUR" in shown and "jamais une formule toute faite" in shown
    # jamais une phrase entière : un modèle la recopiait, même marquée « pour le ton seulement » (sonde finale :
    # « Yooo, te revoilà ! » cinq soirs sur six ; sonde du 2026-10-03 : « Heeey ~ alors, raconte-moi tout. » comme
    # message entier, trois initiatives sur dix) — ses petits mots seulement
    assert not any(g in shown for g in DOC.greetings)
    assert all(w in shown for w in interjections(DOC.greetings)) and interjections(DOC.greetings)
    assert not any(DOC.greetings[0] in c.system_stable for c in llm.calls)
    assert DOC.greetings[0] not in replies[-1].messages[-1].content


def test_a_first_greeting_to_someone_she_does_not_know_is_simple_not_a_friends_hello(tmp_path):
    """Ses bonjours d'amie (« te revoilà », « raconte-moi tout ») supposent qu'on se connaît : à quelqu'un qui arrive
    pour la première fois, un bonjour simple (sonde réelle du 2026-10-03 : « Heeey ~ alors, raconte-moi tout » à
    une inconnue). Contre-exemple : une amie a toujours son exemple de ton."""
    def script(req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        return LLMResponse("hey ! [EMOTION:happy:0.5]")

    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 19, 0))

    async def main():
        await boot(kernel)
        try:
            await befriend(kernel, "user_1", "friend")
            await connect(kernel, "user_1", "Adrien")
            await connect(kernel, "user_2", "Inès")
            await asyncio.sleep(HOUR / US)
        finally:
            await kernel.stop()

    run_virtual(clock, main)
    greets = {c.meta.get("target"): c.messages[-1].content for c in llm.calls if c.role == "initiative"}
    assert "user_2" in greets and "user_1" in greets
    assert "un bonjour simple" in greets["user_2"] and not any(g in greets["user_2"] for g in DOC.greetings)
    assert "tes petits mots" in greets["user_1"], "contre-exemple : une amie garde son ton"


# ── Sa nature et son nom viennent de sa persona (ADR 0070) ────────────────

#: ce qui dirait d'elle qu'elle est une machine
NOT_HUMAN = re.compile(r"\b(IA|VTuber|intelligence artificielle|un serveur|ton serveur)\b")
INCARNATE = self_c.PersonaDoc(
    name="Léa Morel", nature=self_c.EMBODIED, description="Graphiste à Lyon, rieuse, un peu tête en l'air.",
    tone="Simple et chaleureuse.", traits=("Curieuse de tout",), life=("Elle travaille dans un petit studio",),
    tastes=("Son plat préféré : le gratin de sa grand-mère",), facts=("Elle a grandi à Annecy",))


def test_an_embodied_persona_is_never_told_she_is_an_ai():
    """Incarnée, elle est elle — avec son nom, sa vie : rien de ce qu'on lui dit d'elle-même ne parle d'IA, de
    VTuber, de serveur. Contre-exemple : la persona livrée reste une IA qui le sait."""
    for depth in ("full", "compact"):
        text = render(INCARNATE, depth)
        assert text.startswith("Tu es Léa Morel.") and "Tu es toi, avec ton histoire" in text, text
        assert not NOT_HUMAN.search(text), NOT_HUMAN.search(text)
        assert "Tu es une IA" in render(DOC, depth)
    assert self_c.PersonaDoc().nature == self_c.AI == DOC.nature


def test_a_persona_journaled_before_her_nature_was_written_still_replays():
    """Un journal d'avant le champ ``nature`` se relit tel quel (v2 comme v1 relevée) : elle reste ce qu'elle
    était, une IA qui le sait — sans upcaster, le champ a un défaut."""
    old = {k: v for k, v in DOC.model_dump(mode="json").items() if k != "nature"}
    registry = EventRegistry([self_c.PERSONA_REVISED])
    _t, v2 = registry.decode(self_c.PERSONA_REVISED.name, 2, json.dumps({"persona": old}))
    _t, v1 = registry.decode(self_c.PERSONA_REVISED.name, 1, json.dumps({"persona": old}))
    for payload in (v2, v1):
        assert payload.persona.nature == self_c.AI and payload.persona == DOC
        assert render(payload.persona) == render(DOC)


def test_an_embodied_persona_named_otherwise_hears_neither_mika_nor_an_ai(tmp_path):
    """Une journée entière, une conversation, sa relecture, sa nuit : aucun appel de modèle — consignes, outils,
    messages — ne lui donne le nom « Mika » ni ne lui dit qu'elle est une IA. Son nom à elle, si."""
    def extract(prompt):
        if "Annecy" not in prompt.split("Les messages :")[-1]:
            return None
        return {"souvenirs": [{"texte": "Adrien m'a parlé de ses vacances à Annecy", "personnes": ["Adrien"]}]}

    script = Script(extract, reply="haha trop bien [EMOTION:happy:0.5]")
    kernel, clock, llm, _ = build(tmp_path, script, start=at_paris(2026, 9, 28, 17, 0))

    async def main():
        await boot(kernel, INCARNATE)
        try:
            await befriend(kernel, "user_1", "friend")
            await connect(kernel, "user_1", "Adrien", operator=True)
            await chat(kernel, "user_1", ["salut Léa !", "je rentre d'Annecy, c'était génial", "on a fait le lac",
                                          "et toi ta journée ?", "bon je file", "bonne soirée"])
            await asyncio.sleep(DAY / US)
        finally:
            await kernel.stop()

    run_virtual(clock, main)

    def said_to_model(req):
        tools = [f"{t.name} {t.description} {json.dumps(t.schema, ensure_ascii=False)}" for t in req.tools]
        return "\n".join([req.system_stable, req.system_volatile, *(m.content for m in req.messages), *tools])

    roles = {c.role for c in llm.calls}
    assert {"reply", "initiative", "extract", "journal", "dream"} <= roles, roles
    for req in llm.calls:
        text = said_to_model(req)
        assert not re.search(r"\bMika\b", text), (req.role, text[:400])
        assert not NOT_HUMAN.search(text), (req.role, NOT_HUMAN.search(text))
    extracts = [c for c in llm.calls if c.role == "extract"]
    assert all("Tu es la mémoire de Léa Morel" in c.system_stable for c in extracts)
    assert any("Léa Morel :" in c.messages[-1].content for c in extracts), "ses répliques sous son nom"


def test_an_embodied_persona_without_a_name_is_refused():
    """Vide, son nom deviendrait celui de la persona livrée : une personne incarnée s'entendrait appeler « Mika »."""
    import pytest  # noqa: PLC0415

    from mika.contracts.self_ import PersonaDoc  # noqa: PLC0415

    with pytest.raises(ValueError):
        PersonaDoc(name="  ", nature="incarnee")
    assert PersonaDoc(name="Léa", nature="incarnee").name == "Léa"
    assert PersonaDoc(name="", nature="ia").nature == "ia", "contre-épreuve : la règle ne touche que l'incarnée"
