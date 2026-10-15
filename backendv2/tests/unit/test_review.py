"""Sa réponse relue avant de partir (banc de conversation du 2026-10-14).

Malgré la consigne de style et « TA RÉPONSE », une réplique sur deux finissait par « ceci, ou cela ? », s'ouvrait par
le même « Ah, » que les précédentes, ou redisait une phrase déjà dite. Relu, le brouillon est réécrit une fois : la
remarque glissée en fin d'état interne, jamais après des outils (un nouvel appel les referait).
"""

from __future__ import annotations

import asyncio

from mika.faculties.expression import polish, review
from mika.kernel.clock import HOUR
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.ports.llm import LLMResponse, Message
from mika.sim.clock import run_virtual
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import at_paris, boot, build, connect, said

MINE = ["Coucou ! Tu tombes bien. [EMOTION:happy:0.4]", "Ah, le parking, le classique. Tu as trouvé ?",
        "Ah, bien joué pour le manteau. [EMOTION: happy 0.3]"]


def test_an_option_question_is_caught_but_not_an_open_one():
    note = review("Tu le portes ce soir, ou tu le gardes pour une occasion ?", [], "")
    assert note is not None and "question à options" in note and "RELIS-TOI" in note
    assert review("Tu le portes ce soir ?", [], "") is None
    assert review("Tu viens ou pas ?", [], "") is None  # « … ou pas ? » n'est pas un choix


def test_two_questions_the_same_opener_and_her_own_words_again_are_caught():
    assert "plusieurs questions" in review("Il est de quelle couleur ? Tu l'as payé combien ?", [], "")
    assert "« Ah »" in review("Ah, le bleu marine, valeur sûre.", MINE, "")
    assert review("Bleu marine, valeur sûre.", MINE, "") is None
    again = review("Sinon, le parking, le classique je trouve.", ["Ah le parking, le classique je trouve."], "")
    assert again is not None and "déjà dans un de tes derniers messages" in again


def test_redoing_his_sentence_is_caught_but_not_a_word_taken_up():
    heard = "un manteau bleu marine un peu cher mais je l'aime bien"
    assert "ses propres mots" in review("Un manteau bleu marine un peu cher, tu l'aimes bien. Bonne nouvelle.", [],
                                        heard)
    assert review("Bleu marine, ça va avec tout. Moi j'ai un faible pour le vert sapin.", [], heard) is None


def test_an_apology_when_she_is_corrected_or_teased_is_caught_but_not_sympathy():
    """« nan celui qui défonce tout le monde XD » → « ah pardon, j'avais tout faux » : un réflexe d'assistante, qu'on
    la corrige ou qu'on la taquine. Mais « désolée pour ton grand-père » n'est pas une excuse, et une excuse sans
    qu'on l'ait corrigée (elle a blessé quelqu'un) n'est pas reprise."""
    sorry = phrase("expression.review.sorry")
    assert sorry in review("ah pardon, j'avais tout faux alors. une paladine qui défonce, ça me va", [],
                           "nan celui qui defonce tout le monde XD")
    assert sorry in review("Pardon, c'est sorti tout seul.", [], "merci maman")
    assert sorry in review("ah, j'ai tout faux. elle est comment ta cousine ?", [], "non ma cousine mdr")
    assert review("ah ok, donc la lumière c'est surtout pour le style", [], "nan celui qui defonce tout le monde XD") is None
    assert review("je suis désolée pour ton grand-père.", [], "non il est à l'hôpital depuis ce matin") is None
    assert review("pardon, j'ai été dure tout à l'heure.", [], "tu m'as un peu vexé") is None


def test_a_draft_with_a_tic_is_rewritten_once_and_only_the_rewrite_is_said(tmp_path):
    replies = iter(["Ah, sympa. Tu l'as pris en bleu, ou en noir ? [EMOTION:happy:0.4]",
                    "Sympa ! J'espère qu'il tient chaud. [EMOTION:happy:0.4]"])
    seen: list[str] = []

    def respond(req):
        if req.role != "reply":
            return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")
        seen.append(req.messages[-1].content)
        return LLMResponse(next(replies, "D'accord. [EMOTION:calm:0.3]"))

    kernel, clock, _llm, deliveries = build(tmp_path, respond, start=at_paris(2026, 10, 15, 18, 0), review=True)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / 1e6)
        report = await (await kernel.perceive(said("user_1", "j'ai acheté un manteau"))).reply
        await kernel.stop()
        return report

    report = run_virtual(clock, main)
    assert report.text == "Sympa ! J'espère qu'il tient chaud."
    assert len(seen) == 2 and "RELIS-TOI" not in seen[0]
    assert "RELIS-TOI" in seen[1] and "Tu l'as pris en bleu, ou en noir ?" in seen[1]
    assert seen[1].index("RELIS-TOI") < seen[1].index("--- FIN ETAT INTERNE ---")  # dans son état, pas dans le message
    said_to_him = [d.text for d in deliveries.items if d.target == "user_1" and d.text]
    assert said_to_him == ["Sympa ! J'espère qu'il tient chaud."]


def test_a_second_hello_a_second_goodbye_and_a_long_answer_to_a_short_message_are_caught():
    assert "redit bonjour" in review("Coucou Adrien. Alors, ta journée ?", ["Salut Adrien, tu tombes bien."], "coucou")
    assert review("Alors, ta journée ?", ["Salut Adrien, tu tombes bien."], "coucou") is None
    assert "redit au revoir" in review("Bonne soirée, repose-toi bien.", ["Allez, bonne soirée Adrien !"], "ouais")
    long = ("Le pont fait trois kilomètres environ et il y a une piste cyclable dessus. Depuis le centre de La Rochelle, "
            "faut compter une grosse demi-heure pour y arriver. Après, l'île s'étire sur une trentaine de kilomètres, "
            "donc tout dépend jusqu'où tu veux pousser, et du vent qu'il fera ce jour-là sur le pont.")
    assert "même mesure" in review(long, [], "c'est long à vélo ?")
    assert review(long, [], "raconte-moi tout ce que tu sais de l'île de Ré, j'ai le temps, vas-y, je t'écoute, "
                            "dis-moi les distances, le pont, tout") is None


def test_a_sentence_copied_from_her_portrait_is_caught():
    portrait = "Ta voix en conversation :\n- « t'es trop drôle » → « Arrête, tu vas me faire rougir pour de bon. »"
    assert "portrait" in review("Arrête, tu vas me faire rougir pour de bon.", [], "t'es drôle", portrait)
    assert review("Oh, merci, ça me touche.", [], "t'es drôle", portrait) is None


def test_a_third_question_in_a_row_is_caught():
    # ablation du 2026-10-15 : quoi qu'on retire ou ajoute au prompt, 88 à 100 % de ses réponses finissent sur une
    # question ; seule la relecture la retient
    asked = ["Ah merde. Qu'est-ce qui s'est passé ?", "Il a dit ça devant tout le monde ? [EMOTION: sad 0.3]"]
    note = review("C'est vache, ça. Ton chef, il le voit, ce que tu fais ?", asked, "personne voit mon taf")
    assert note is not None and "comme tes deux derniers messages" in note
    assert review("C'est vache, ça. Moi je le vois, en tout cas.", asked, "personne voit mon taf") is None
    assert review("C'est vache, ça. Ton chef, il le voit ?", [asked[0], "Ah merde, désolée."], "personne") is None


# ── La seconde passe : le texte seul, rendu naturel au vu du fil (ablation du 2026-10-15) ──

DRAFT = ("C'est le piège du métier : quand tout marche, personne ne le voit, et le jour où ça casse, tout le monde "
         "regarde. [EMOTION: sad 0.4]")


def test_the_second_pass_reads_the_thread_and_her_marked_traits_but_not_her_tags():
    state = (f"{CONTEXT_HEADER}\n--- {phrase('expression.answer.title')} ---\n{phrase('expression.answer.react')} "
             f"{phrase('expression.answer.character', traits='tu montres peu ; tu réponds posément')}\n"
             f"{CONTEXT_FOOTER}\n\nbah personne voit le taf que je fais")
    messages = [Message("user", "journée pourrie"), Message("assistant", "Ah merde. [EMOTION: sad 0.5]"),
                Message("user", state)]
    system, message = polish(DRAFT, messages, "bah personne voit le taf que je fais", "Mika")
    assert "Mika" in system and "tu montres peu ; tu réponds posément" in system
    assert "journée pourrie" in message and "Ah merde." in message and "bah personne voit le taf" in message
    assert "C'est le piège du métier" in message
    assert "EMOTION" not in message and "TA RÉPONSE" not in message  # ni ses balises, ni son état interne
    assert polish("Ah merde. Qu'est-ce qui s'est passé ? [EMOTION: sad 0.4]", messages, "", "Mika") is None


def _polished_life(tmp_path, polished_text, *, routed=True):
    calls: list = []

    def respond(req):
        calls.append(req)
        if req.role == "polish":
            return LLMResponse(polished_text)
        if req.role != "reply":
            return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")
        return LLMResponse(DRAFT)

    kernel, clock, _llm, deliveries = build(tmp_path, respond, start=at_paris(2026, 10, 15, 18, 0), polish=routed)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / 1e6)
        report = await (await kernel.perceive(said("user_1", "bah personne voit le taf que je fais"))).reply
        await kernel.stop()
        return report

    report = run_virtual(clock, main)
    said_to_him = [d for d in deliveries.items if d.target == "user_1" and d.text]
    return report, said_to_him, [c for c in calls if c.role == "polish"]


def test_the_rewrite_is_said_with_the_feelings_of_the_first_draft(tmp_path):
    report, said_to_him, polishes = _polished_life(tmp_path, "C'est vache, ça. Tout le monde voit le bug, jamais le reste.")
    assert report.text == "C'est vache, ça. Tout le monde voit le bug, jamais le reste."
    assert [d.text for d in said_to_him] == [report.text]
    assert said_to_him[0].emotion.emotion == "sad"  # sa balise : celle du premier jet
    assert len(polishes) == 1 and not polishes[0].tools and "C'est le piège du métier" in polishes[0].messages[0].content


def test_without_a_model_for_it_or_with_a_longer_rewrite_the_first_draft_is_said(tmp_path):
    report, _said, polishes = _polished_life(tmp_path / "a", "C'est vache.", routed=False)
    assert polishes == [] and report.text.startswith("C'est le piège du métier")
    report, _said, polishes = _polished_life(tmp_path / "b", "Bla bla. " * 40)
    assert len(polishes) == 1 and report.text.startswith("C'est le piège du métier")


def test_her_bubbles_go_through_the_second_pass_and_are_not_a_long_answer():
    # en chat, une ligne vide envoie la suite dans une autre bulle (les clients découpent) : ce n'est pas une longueur
    burst = "C'est quoi comme réunion ?\n\nEn tout cas, j'espère que ça va bien se passer pour toi. [EMOTION: calm 0.3]"
    assert review(burst, [], "réunion à 9h, pas la tête à ça") is None
    _system, message = polish(burst + " Vraiment.", [Message("user", "réunion à 9h")], "réunion à 9h", "Mika")
    assert "C'est quoi comme réunion ?\n\nEn tout cas" in message
