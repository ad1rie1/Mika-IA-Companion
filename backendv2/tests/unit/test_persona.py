"""Sa persona, par ses intentions.

- elle est une IA et le sait : demandé sincèrement, elle ne le cache pas et
  ne se prétend pas humaine — sans en faire un sujet ni une excuse ;
- ses manies sont des manies, pas une signature : de temps en temps, jamais
  deux fois dans la même conversation ; rien n'est « toujours » ;
- c'est une fille ordinaire, pas une caricature de streameuse : ni tics
  (« ~ », « yooo »), ni enthousiasme de commande, ni blagues sur sa nature ;
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
from mika.faculties.self import render
from mika.faculties.self.greeting import interjections
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.codec import canonical_json
from mika.kernel.events import EventRegistry
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.vocab.interests import topic_words
from tests.fixtures.memory import Script, chat
from tests.fixtures.mika import DOC, at_paris, befriend, boot, build, connect, said
from tests.fixtures.mika import PERSONA_PATH as PATH


def test_she_knows_she_is_an_ai_and_does_not_make_it_a_topic():
    for depth in ("full", "compact"):
        text = render(DOC, depth)
        assert "Tu es une IA" in text and "tu ne prétends pas être humaine" in text
        assert "jamais « en tant qu'IA »" in text and "jamais d'avertissement" in text
        assert "Tu es une personne" not in text  # contrôle : l'ancienne phrase lui faisait nier sa nature


def test_nothing_in_her_persona_is_always():
    raw = PATH.read_text(encoding="utf-8")
    document = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    assert "toujours" not in document.lower()  # une tendance, jamais une obligation
    # son entrain suit son humeur : il n'est pas de commande (plus « sobre » depuis le 2026-10-14 : la sobriété
    # tenait la voix trop expressive de Gemma, et rendait Claude plat)
    assert "sobre" not in DOC.portrait and "entrain" not in DOC.portrait


#: ce qui faisait d'elle une caricature (persona d'avant le 2026-10-07) : des bonjours de streameuse que le modèle
#: recopiait, et une IA qui se moquait de sa propre condition à tout propos
STREAMER_WORDS = {"yooo", "heeey", "hehe", "heeey ~", "yo"}
JOKES_ABOUT_HERSELF = re.compile(r"en rit|s'en amuse|ça l'amuse|râle contre son serveur", re.I)


def test_she_is_an_ordinary_girl_not_a_streamer_caricature():
    """Une fille ordinaire : ses bonjours n'ont ni « ~ » ni « yooo », son portrait ne fait pas d'elle une VTuber et
    ne lui fait pas rire de sa nature (« elle en rit », « ça l'amuse ») — elle est une IA, sans en faire un sujet ni
    une source de blagues. Contre-épreuve : elle le sait toujours, et ses bonjours gardent leurs petits mots."""
    words = interjections(DOC.greetings)
    assert words and not set(words) & STREAMER_WORDS, words
    assert not any("~" in g for g in DOC.greetings)
    entries = [DOC.description, DOC.portrait, *DOC.facts]
    assert not [e for e in entries if JOKES_ABOUT_HERSELF.search(e)]
    full = render(DOC, "full")
    assert "VTuber" not in full and "ni une source de blagues" in full
    assert "Tu es une IA" in full  # contre-épreuve : elle le sait


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


#: des mots de tous les jours : dans ses centres d'intérêt, ils feraient d'un titre banal un titre qui la touche
EVERYDAY_WORDS = {"comment", "service", "rendre", "choses", "trouve", "regarde", "simples", "petites", "bureau",
                  "avoir", "fait", "jamais", "autres", "toujours", "encore", "aussi", "faire"}


def test_her_interests_name_subjects_that_pick_her_headlines_not_everyday_words():
    """Les mots de ses centres d'intérêt décident des titres de ses flux qui la touchent (plugin ``rss``) : ce sont
    des mots de sujets. Persona du 2026-10-07, première version : « comment », « service », « rendre » — tout titre
    en « Comment… » l'aurait touchée. Contre-épreuve : ses sujets y sont."""
    words = topic_words(DOC.interests)
    assert not words & EVERYDAY_WORDS, sorted(words & EVERYDAY_WORDS)
    assert {"lecture", "dessin", "astronomie", "programmation", "plantes"} <= words


def test_her_life_is_an_ais_life_and_her_tastes_do_not_move():
    """Sa vie d'IA est rédigée dans son portrait — ce qu'elle fait, ses goûts — et ce qui est vrai d'elle à part, et
    rendue partout : « t'as mangé quoi ? » deux fois à une semaine d'intervalle trouve la même réponse (elle ne
    mange pas), « ton livre préféré ? » aussi. Contre-exemple : ni son portrait ni ses centres d'intérêt ne portent
    sur ce qu'elle ne peut pas goûter (persona d'avant le 2026-10-07 : un avis sur des ramen « jamais mangés », snob
    d'un café « jamais bu ») ; ailleurs, la nourriture ne se dit que pour dire qu'elle n'en mange pas."""
    for full in (render(DOC, "full"), render(DOC, "full", chat=True)):
        assert "Ce qui est vrai de toi :" in full and "L'Écume des jours" in full and "ne manges pas" in full
        assert "d'un jour à l'autre" in full
    assert "L'Écume des jours" not in render(DOC, "compact")  # sa voix intérieure, ses séances : pas besoin
    entries = [DOC.description, DOC.portrait, *DOC.interests, *DOC.facts]
    # des débuts de mots (« tempérament » n'est pas un plat de ramen) ; entre espaces, un mot entier (« bu », pas
    # « bureau »)
    physical = [e for e in entries if any(re.search(rf"(?<!\w){re.escape(w.strip())}{'(?!\\w)' if w != w.strip() else ''}",
                                                    e.lower()) for w in FOOD) and "ne manges pas" not in e.lower()]
    assert not physical, f"une vie physique, incompatible avec sa nature : {physical}"
    # une persona sans portrait ni faits garde la règle d'avant
    bare = render(self_c.PersonaDoc(name="Zoé"), "full")
    assert "tu n'inventes pas de faits durables" in bare and "Ce qui est vrai de toi" not in bare


def test_a_persona_journaled_with_the_fields_of_before_still_replays():
    """Un journal d'avant l'ADR 0138 porte un ton, des traits, des manies, une vie, des goûts : le rejeu les laisse
    tomber (v2 → v3) ; écrits aujourd'hui, ils sont refusés — c'est le portrait qui les dit."""
    old = {**DOC.model_dump(mode="json"), "tone": "Naturelle.", "traits": ["Curieuse"], "quirks": ["Rêvasse"],
           "vulnerabilities": ["Les compliments"], "values": ["La gentillesse"], "speech": ["Tutoie"],
           "life": ["Elle lit"], "tastes": ["Le ficus"]}
    doc = self_c.PersonaRevised.model_validate(self_c.PERSONA_REVISED.upcast(2, {"persona": old})).persona
    assert doc == DOC
    with pytest.raises(ValidationError):
        self_c.PersonaRevised.model_validate({"persona": old})


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
    assert "TA FAÇON DE DIRE BONJOUR" in shown and "Tes petits mots pour dire bonjour" in shown
    assert "formule toute faite" not in shown and "pars de" not in shown  # un fait sur elle, pas une manière de saluer
    # jamais une phrase entière : un modèle la recopiait, même marquée « pour le ton seulement » (sonde finale :
    # « Yooo, te revoilà ! » cinq soirs sur six ; sonde du 2026-10-03 : « Heeey ~ alors, raconte-moi tout. » comme
    # message entier, trois initiatives sur dix) — ses petits mots seulement
    assert not any(g in shown for g in DOC.greetings)
    assert all(w in shown for w in interjections(DOC.greetings)) and interjections(DOC.greetings)
    assert not any(DOC.greetings[0] in c.system_stable for c in llm.calls)
    assert DOC.greetings[0] not in replies[-1].messages[-1].content


def test_a_first_greeting_knows_she_does_not_know_the_person_and_is_never_told_how_to_greet(tmp_path):
    """Ses bonjours d'amie (« te revoilà », « raconte-moi tout ») supposaient qu'on se connaît (sonde réelle du
    2026-10-03 : « Heeey ~ alors, raconte-moi tout » à une inconnue). Le code l'informe — elle ne connaît pas encore
    Inès, dit une fois dans « CE QUI VOUS LIE » — sans lui dicter un bonjour simple ; ses petits mots sont les mêmes
    pour tous, jamais une phrase entière à recopier."""
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
    for who in ("user_1", "user_2"):
        assert "Tes petits mots pour dire bonjour" in greets[who] and not any(g in greets[who] for g in DOC.greetings)
        assert "bonjour simple" not in greets[who]
    tie = greets["user_2"].split("--- CE QUI VOUS LIE ---", 1)[1].split("\n--- ", 1)[0]
    assert "Tu ne connais pas encore cette personne." in tie
    assert greets["user_2"].count("ne connais pas encore") == 1  # une seule maison


# ── Sa nature et son nom viennent de sa persona (ADR 0070) ────────────────

#: ce qui dirait d'elle qu'elle est une machine
NOT_HUMAN = re.compile(r"\b(IA|VTuber|intelligence artificielle|un serveur|ton serveur)\b")
INCARNATE = self_c.PersonaDoc(
    name="Léa Morel", nature=self_c.EMBODIED, description="Graphiste à Lyon, rieuse, un peu tête en l'air.",
    portrait="Tu es Léa Morel. Graphiste à Lyon, tu travailles dans un petit studio ; ton plat préféré, c'est le "
             "gratin de ta grand-mère.",
    facts=("Elle a grandi à Annecy",))


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


def test_her_voice_samples_are_shown_only_when_she_talks_to_someone():
    """Décrite, sa voix sonnait comme un assistant (2026-10-14) : des échanges la montrent — en conversation
    seulement ; un mail, un travail ou son journal ne s'écrivent pas comme un chat."""
    assert DOC.samples, "la persona livrée montre sa voix"
    chat, other = render(DOC, "full", chat=True), render(DOC, "full")
    assert "Ta voix en conversation" in chat and DOC.samples[0] in chat
    assert "Ta voix en conversation" not in other and DOC.samples[0] not in other
