"""Sa réponse relue avant de partir (banc de conversation du 2026-10-14).

Malgré la consigne de style et « TA RÉPONSE », une réplique sur deux finissait par « ceci, ou cela ? », s'ouvrait par
le même « Ah, » que les précédentes, ou redisait une phrase déjà dite. Relu, le brouillon est réécrit une fois : la
remarque glissée en fin d'état interne, jamais après des outils (un nouvel appel les referait).
"""

from __future__ import annotations

import asyncio

from mika.faculties.expression import polish, review
from mika.kernel.clock import HOUR
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER, ChatPrompt, ChatTurn, label
from mika.ports.llm import LLMResponse, Message, PersonaRender
from mika.runtime.pipeline import EpisodeRequest
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


# ── La seconde passe : une autrice écrit la suite du fil à partir du premier jet (ADR 0114) ──

DRAFT = ("C'est le piège du métier : quand tout marche, personne ne le voit, et le jour où ça casse, tout le monde "
         "regarde. [EMOTION: sad 0.4]")
PERSONA = PersonaRender(text="Tu es Mika. Tu lis beaucoup.", hash="h", depth="full", name="Mika",
                        reference="Léa : Coucouuu\nMoi : salut")


def test_the_author_reads_her_portrait_the_thread_and_the_draft_but_not_her_tags_nor_her_state():
    state = (f"{CONTEXT_HEADER}\n--- {phrase('social.about.title')} ---\nAdrien adore plaisanter, sauf au boulot.\n\n"
             f"--- {phrase('expression.answer.title')} ---\n{phrase('expression.answer.react')}\n"
             f"{CONTEXT_FOOTER}\n\nbah personne voit le taf que je fais")
    messages = [Message("user", "journée pourrie"), Message("assistant", "Ah merde.\n\nRaconte. [EMOTION: sad 0.5]"),
                Message("user", state)]
    system, message, keep = polish(DRAFT, messages, "bah personne voit le taf que je fais", PERSONA)
    assert "Tu es Mika. Tu lis beaucoup." in system and "Léa : Coucouuu" in system  # son portrait, le registre
    # qui est l'autre (sa fiche) : l'autrice écrit aussi ses réponses à venir ; le reste de son état ne passe pas
    assert "Adrien adore plaisanter, sauf au boulot." in system and "Réagis d'abord" not in system
    assert "Mika : Ah merde.\nMika : Raconte." in message  # une ligne par bulle, comme un fil de SMS
    assert "journée pourrie" in message and "bah personne voit le taf" in message
    assert "C'est le piège du métier" in message
    assert "EMOTION" not in message and "TA RÉPONSE" not in message  # ni ses balises, ni son état interne
    # l'autrice écrit aussi la réponse de l'autre : seuls ses messages à elle partent, une bulle chacun
    assert keep("Mika : c'est vache.\nMika : bon : tout le monde voit le bug\nL'autre : ouais") == \
        "c'est vache.\n\nbon : tout le monde voit le bug"
    assert keep("Mika : et julien qui dit rien Mika : c'est ça qui m'énerverait L'autre : grave") == \
        "et julien qui dit rien\n\nc'est ça qui m'énerverait"
    assert polish("[EMOTION: sad 0.4]", messages, "", PERSONA) is None
    # sans fil de référence, rien n'en est dit
    bare = PersonaRender(text="Tu es Mika.", hash="h", depth="full", name="Mika")
    assert "fil_de_reference" not in polish(DRAFT, messages, "", bare)[0]


def _as_sent(prompt: ChatPrompt) -> list[Message]:
    """Les messages tels que le composeur les envoie (repères compris)."""
    return [Message(m["role"], m["content"]) for m in prompt.chat_messages()]


def test_the_author_reads_when_each_message_came():
    """Sans les repères du fil, trois jours se lisaient comme une seule conversation : au « coucou » du matin,
    l'autrice pouvait reprendre la blague de la veille."""
    history = (ChatTurn("user", "t'as vu le match ?", mark="mardi 21h10"),
               ChatTurn("assistant", "Non, raconte !"),
               ChatTurn("user", "on a perdu 3-0", mark="plus tard, vers 23h"),
               ChatTurn("assistant", "Aïe.\n\nBonne nuit quand même", mark="le surlendemain, jeudi 19h06 — c'est toi "
                                                                       "qui lui as écrit"))
    now = label(ChatTurn("user", "", mark="le lendemain, vendredi 8h02")) + "coucou"
    _system, message, _keep = polish("Coucou ! Bien dormi ?", _as_sent(ChatPrompt("s", "--- QUI ---\nAdrien",
                                                                                  history, now)), "coucou", PERSONA)
    assert ("[mardi 21h10]\nL'autre : t'as vu le match ?\nMika : Non, raconte !\n"
            "[plus tard, vers 23h]\nL'autre : on a perdu 3-0\n"
            "[le surlendemain, jeudi 19h06 — c'est toi qui lui as écrit]\nMika : Aïe.\nMika : Bonne nuit quand même\n"
            "[le lendemain, vendredi 8h02]\nL'autre : coucou\nMika (brouillon) : Coucou ! Bien dormi ?") in message
    # seize messages du fil, leurs repères en plus : un repère seul (avant un des siens) ne compte pas pour un message
    turns = tuple(ChatTurn("assistant" if i % 2 else "user", f"message {i}", mark=f"jour {i}") for i in range(30))
    _system, message, _keep = polish("Bah rien.", _as_sent(ChatPrompt("s", "", turns, "et alors")), "et alors",
                                     PERSONA)
    lines = message.split("\n")
    assert "[jour 14]" in lines and "Mika : message 15" in lines and "[jour 13]" not in lines


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


def _authored_trace(tmp_path, polished_text):
    def respond(req):
        if req.role == "polish":
            return LLMResponse(polished_text)
        if req.role != "reply":
            return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")
        return LLMResponse(DRAFT)

    kernel, clock, _llm, _out = build(tmp_path, respond, start=at_paris(2026, 10, 15, 18, 0), polish=True)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / 1e6)
        report = await (await kernel.perceive(said("user_1", "bah personne voit le taf que je fais"))).reply
        await kernel.traces.flush()
        trace = kernel.traces.get(report.id)
        await kernel.stop()
        return trace

    return run_virtual(clock, main)


def test_the_trace_keeps_what_the_author_read_and_wrote_kept_or_not(tmp_path):
    """« Pourquoi a-t-elle dit ça ? » montre la réponse principale, puis le contexte et la réponse de l'autrice : la
    trace les garde, et dit pourquoi le premier jet est parti quand elle est écartée."""
    kept = _authored_trace(tmp_path / "a", "C'est vache, ça. Tout le monde voit le bug, jamais le reste.")
    author = kept["naturel"]
    assert DRAFT.startswith(author["premier_jet"][:20]) and kept["reply"] == DRAFT  # le texte brut, balises comprises
    assert author["systeme"] and "bah personne voit le taf que je fais" in author["message"]
    assert author["reponse"] == "C'est vache, ça. Tout le monde voit le bug, jamais le reste."
    assert "ecartee" not in author
    dropped = _authored_trace(tmp_path / "b", "Bla bla. " * 80)["naturel"]
    assert dropped["ecartee"] == "plus longue que le premier jet" and dropped["reponse"].startswith("Bla bla.")


def test_without_a_model_for_it_or_with_a_longer_rewrite_the_first_draft_is_said(tmp_path):
    report, _said, polishes = _polished_life(tmp_path / "a", "C'est vache.", routed=False)
    assert polishes == [] and report.text.startswith("C'est le piège du métier")
    report, _said, polishes = _polished_life(tmp_path / "b", "Bla bla. " * 80)
    assert len(polishes) == 1 and report.text.startswith("C'est le piège du métier")


def test_with_the_author_there_is_no_review_and_what_she_starts_herself_is_authored_too(tmp_path):
    """L'autrice récrit derrière : la relecture ne coûte plus un appel. Et un message qu'elle lance d'elle-même passe
    aussi par elle (2026-10-16, sur le PC : de petits SMS, puis un pavé de journaliste qu'elle lançait seule) — sans
    sa consigne (« personne ne vient de t'écrire… ») comme ligne du fil."""
    calls: list = []

    def respond(req):
        calls.append(req)
        if req.role == "polish":
            return LLMResponse("Mika : j'ai lu un truc sur la marche 👀\nL'autre : quoi")
        if req.role == "initiative":
            # sans chiffre : une récriture qui perdrait un nombre du premier jet serait écartée (audit du 2026-10-26, L8)
            return LLMResponse("Je suis allée lire une étude sur la marche, avec des malades suivis. [EMOTION:happy:0.4]")
        if req.role != "reply":
            return LLMResponse("{}" if req.role in ("extract", "profile") else "[SILENCE]")
        return LLMResponse("Ah, sympa. Tu l'as pris en bleu, ou en noir ? [EMOTION:happy:0.4]")

    kernel, clock, _llm, deliveries = build(tmp_path, respond, start=at_paris(2026, 10, 15, 18, 0),
                                            polish=True, review=True)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(2 * HOUR / 1e6)
        await (await kernel.perceive(said("user_1", "j'ai acheté un manteau"))).reply
        started = await kernel.lanes.submit(EpisodeRequest(kind="INITIATIVE", target="user_1", reason="share"))
        await kernel.stop()
        return started

    started = run_virtual(clock, main)
    assert not [c for c in calls if c.call_id.endswith("#relu")]  # sa réponse à options : pas de relecture
    assert [str(c.role) for c in calls].count("reply") == 1
    assert started.text == "j'ai lu un truc sur la marche 👀"
    authored = [c for c in calls if c.role == "polish"][-1].messages[0].content
    assert "Mika (brouillon) : Je suis allée lire une étude" in authored and "Personne ne vient" not in authored


def test_her_bubbles_go_through_the_second_pass_and_are_not_a_long_answer():
    # en chat, une ligne vide envoie la suite dans une autre bulle (les clients découpent) : ce n'est pas une longueur
    burst = "C'est quoi comme réunion ?\n\nEn tout cas, j'espère que ça va bien se passer pour toi. [EMOTION: calm 0.3]"
    assert review(burst, [], "réunion à 9h, pas la tête à ça") is None
    _system, message, _keep = polish(burst + " Vraiment.", [Message("user", "réunion à 9h")], "réunion à 9h", PERSONA)
    assert "Mika (brouillon) : C'est quoi comme réunion ? / En tout cas" in message
