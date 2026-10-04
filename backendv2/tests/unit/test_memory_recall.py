"""Ce qui lui revient, et comment elle révise ce qu'elle croit.

- Le rappel cherche ses souvenirs à part des extraits d'échanges : mille
  échanges des autres n'étouffent pas ce qu'elle sait d'Alice ;
- une politesse (« ah d'accord ») ne réveille rien ;
- « vos échanges passés » ne répète pas le fil qu'elle a sous les yeux, et dit
  qui parlait dans un salon ;
- un salon se relit d'un seul tenant, ce qui ne lui était pas adressé n'y
  compte que s'il nomme quelqu'un qu'elle connaît ;
- Lyon, puis Nantes, puis Lyon : c'est Lyon qu'elle croit ; une même
  personne qui répète ne rend pas une croyance plus sûre.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from mika.app import composition
from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.faculties.memory.consolidation import same_words
from mika.kernel.clock import DAY, US
from mika.sim.clock import run_virtual
from mika.vocab.people import clean_tokens
from tests.fixtures.memory import SIX, Script, chat, kept, section, seq_of, token
from tests.fixtures.mika import DOC, at_paris, boot, build, connect, said

REVIENT = "CE QUI TE REVIENT"
EXCHANGES = "VOS ÉCHANGES PASSÉS"


def test_other_peoples_exchanges_do_not_crowd_out_her_memories(tmp_path):
    """Bob a posé dix fois la même question qu'Alice va poser : ses échanges
    ressemblent plus au message d'Alice que ce qu'elle sait d'Alice. Les
    souvenirs se cherchent à part : ce qu'elle sait d'Alice revient."""

    def extract(prompt):
        if "CANARI-E1" not in prompt.split("Les messages :")[-1]:
            return None
        return {"croyances": [{"texte": "Alice a un entretien chez Ubisoft mardi (CANARI-E1)",
                               "personnes": [token(prompt, "Alice")], "sensibilite": "personnel"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await composition.configure(kernel, DOC, {"memory": {"recall_k": 5}})
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["CANARI-E1 mardi j'ai un entretien chez Ubisoft", *SIX[1:]])
        await chat(kernel, "user_3", ["tu te souviens de mon entretien ?"] * 10, gap_s=30)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_2", ["tu te souviens de mon entretien ?"])
        await kernel.stop()

    run_virtual(clock, main)
    reply = script.replies("user_2")[-1]
    assert "CANARI-E1" in section(reply, REVIENT)
    assert "Ce que tu sais (tes notes) :" in section(reply, REVIENT)
    assert "(on te l'a dit)" not in reply, "le texte dit déjà « m'a dit » : pas de jargon en plus"


def test_a_polite_word_brings_nothing_back(tmp_path):
    """« Ah d'accord », « bonne nuit » : on ne repense pas à sa vie à chaque
    politesse — même quand un souvenir en a les mots (« Alice m'a souhaité une
    bonne nuit, toute contente de son déménagement » ressemble à « bonne nuit ! » ;
    « Alice m'a souhaité une bonne nuit » tout court, une banalité, ne se garde
    plus du tout : ADR 0055)."""

    def extract(prompt):
        if "Nantes" not in prompt:
            return None
        return {"croyances": [{"texte": "Alice m'a dit : Au fait je déménage le mois prochain à Nantes",
                               "personnes": [token(prompt, "Alice")], "sensibilite": "personnel"}],
                "souvenirs": [{"texte": "Alice m'a souhaité une bonne nuit, toute contente de son déménagement",
                               "personnes": [token(prompt, "Alice")], "sensibilite": "anodin"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["Au fait je déménage le mois prochain à Nantes", "bonne nuit Mika", *SIX[2:]])
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_2", ["ah d'accord", "bonne nuit !", "tu te souviens où je déménage ?"])
        await kernel.stop()

    run_virtual(clock, main)
    agreed, night, asked = script.replies("user_2")[-3:]
    assert section(agreed, REVIENT) == "" and section(night, REVIENT) == ""
    assert "Nantes" in section(asked, REVIENT), "contrôle : une vraie question, si"


def test_recall_follows_the_conversation_and_stays_on_its_subject(tmp_path):
    """« Et tu crois qu'il va guérir vite ? » ne nomme rien : c'est la
    conversation (« je suis chez le vétérinaire avec Moustache ») qui dit de
    quoi on parle — ce qu'elle sait de Moustache revient. Ce qui ne touche le
    sujet que de loin (le chien de la voisine) ne revient pas : sous le seuil,
    rien ne remonte au hasard."""
    cat, dog = "Moustache, le chat d'Alice, a une peur bleue du vétérinaire", "Alice a promené le chien de sa voisine"

    def extract(prompt):
        if "peur bleue" not in prompt.split("Les messages :")[1]:
            return None
        alice = token(prompt, "Alice")
        return {"croyances": [{"texte": cat, "personnes": [alice], "sensibilite": "anodin"},
                              {"texte": f"{dog} au parc", "personnes": [alice], "sensibilite": "anodin"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["Moustache a une peur bleue du vétérinaire",
                                      "j'ai promené le chien de ma voisine au parc", *SIX[2:]])
        await asyncio.sleep(15 * 60)
        await asyncio.sleep(DAY / US)
        await chat(kernel, "user_2", ["je suis chez le vétérinaire avec Moustache", "et tu crois qu'il va guérir vite ?"])
        await kernel.stop()

    run_virtual(clock, main)
    at_vet, after = (section(r, REVIENT) for r in script.replies("user_2")[-2:])
    assert cat in at_vet and cat in after, "la question se comprend avec ce qui précède"
    assert dog not in at_vet and dog not in after, "un rappel au hasard"


def test_past_exchanges_do_not_repeat_the_thread_she_sees(tmp_path):
    """Ce qu'Alice a dit il y a vingt minutes est encore dans le fil : elle le
    voit déjà, « vos échanges passés » ne le recopie pas. Quand le fil montré
    est court, le même échange revient — cette fois il n'est plus sous ses yeux."""

    def run(window):
        script = Script()
        kernel, clock, _, _out = build(tmp_path / str(window), script)

        async def main():
            await boot(kernel)
            if window:
                await composition.configure(kernel, DOC, {"transcript": {"window": window}})
            await connect(kernel, "user_2", "Alice")
            await chat(kernel, "user_2", ["Mon chat Moustache a vomi sur le canapé",
                                          "Sinon je regarde un film de Miyazaki", "Le Voyage de Chihiro, mon préféré"],
                       gap_s=40)
            await asyncio.sleep(15 * 60)
            await chat(kernel, "user_2", ["tu crois que Moustache est malade, il a vomi sur le canapé ?"])
            await kernel.stop()

        run_virtual(clock, main)
        return section(script.replies("user_2")[-1], EXCHANGES)

    assert "Moustache" not in run(0), "le fil le montre déjà"
    assert "Moustache a vomi" in run(5), "contrôle : hors du fil montré, l'échange revient"


def test_a_burst_is_kept_whole_and_its_real_question_comes_back(tmp_path):
    """« salut », « t'as vu le match hier soir contre Lyon ? », « allo ? » : une seule réponse règle les trois
    (le tour, ADR 0040). L'échange gardé ne se réduisait qu'au dernier — « allo ? » —, et la vraie question
    n'existait plus nulle part : ni le rappel ni la recherche ne la retrouvaient."""
    script = Script(reply="Oui je l'ai vu, quel match !")
    kernel, clock, _, _out = build(tmp_path, script, latency=lambda r: 8.0 if r.role == "reply" else 0.5)

    async def main():
        await boot(kernel)
        await composition.configure(kernel, DOC, {"transcript": {"window": 2}})
        await connect(kernel, "user_2", "Alice")
        waits = []
        for text in ("salut", "t'as vu le match hier soir contre Lyon ?", "allo ?"):
            waits.append((await kernel.perceive(said("user_2", text))).reply)
            await asyncio.sleep(1)
        for w in waits:
            if w is not None:
                await w
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["il pleut chez moi", "j'ai mangé des pâtes", "tu fais quoi ce soir ?"])
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_2", ["au fait, tu te souviens du match contre Lyon ?"])
        rows = kernel.mind.store.query_mind(f"SELECT question, user_text FROM {memory_c.CHUNKS_TABLE} ORDER BY id")
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    burst = [(q, text) for q, text in rows if "allo" in text]
    assert len(burst) == 1, rows  # une réponse, un échange
    question, text = burst[0]
    assert text.index("salut") < text.index("match hier soir contre Lyon") < text.index("allo"), text
    assert question < max(q for q, _ in rows)  # sa question est le premier message du tour
    shown = section(script.replies("user_2")[-1], EXCHANGES)
    assert "match hier soir contre Lyon" in shown, shown


def test_in_a_room_each_past_exchange_names_who_spoke(tmp_path):
    room = {"room": "ext_chat_-9", "channel": "external"}
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await composition.configure(kernel, DOC, {"transcript": {"window": 5}})
        await chat(kernel, "ext_1", ["Mika, Moustache le chat de Léa a vomi ce matin"], display_name="Tom", **room)
        for text in ("Mika tu joues à quoi ?", "Mika t'as vu le match ?", "Mika il pleut chez toi ?"):
            await chat(kernel, "ext_3", [text], gap_s=30, display_name="Zoé", **room)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "ext_2", ["Mika, tu sais si Moustache a vomi encore ?"], display_name="Léa", **room)
        await kernel.stop()

    run_virtual(clock, main)
    shown = section(script.replies("ext_2")[-1], EXCHANGES)
    assert "Tom : « Mika, Moustache le chat de Léa a vomi" in shown, shown
    assert "Léa : « Mika, Moustache" not in shown


def test_a_room_is_one_conversation_and_asides_count_only_when_they_name_someone(tmp_path):
    room = {"room": "ext_chat_-3", "channel": "external"}
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await chat(kernel, "ext_1", ["Mika, je pars au Japon en avril"], display_name="Tom", **room)
        await chat(kernel, "ext_2", ["je mange une pomme"], display_name="Léa", addressed=False, **room)
        await chat(kernel, "ext_3", ["Tom tu me ramènes un kimono ?"], display_name="Zoé", addressed=False, **room)
        await chat(kernel, "ext_2", ["Mika tu connais Kyoto ?", *SIX[2:]], display_name="Léa", **room)
        await asyncio.sleep(15 * 60)
        await kernel.stop()

    run_virtual(clock, main)
    rooms = [x for x in script.extracts() if "Un salon de groupe" in x]
    assert rooms and not any("Conversation privée" in x for x in script.extracts()), "jamais découpé par adresse"
    text = rooms[0]
    assert "Tom [P1]" in text and "Léa [P2]" in text and "Zoé [P3]" in text
    assert "je mange une pomme" not in text, "entre eux, et personne qu'elle connaisse"
    assert re.search(r"Zoé \[P3\] \(entre eux\) : Tom tu me ramènes un kimono", text), "entre eux, mais sur Tom"


def test_lyon_then_nantes_then_lyon_means_lyon(tmp_path):
    plan = ["Lyon", "Nantes", "Lyon"]

    def extract(prompt):
        known = dict((city, int(i)) for i, city in re.findall(r"^\[#(\d+)\] Alice habite à (\w+)$",
                                                               prompt.split("Les messages :")[0], re.M))
        city = plan.pop(0) if plan else None
        if city is None:
            return None
        old = [i for c, i in known.items() if c != city]
        return {"croyances": [{"texte": f"Alice habite à {city}", "personnes": [token(prompt, "Alice")],
                               "sensibilite": "anodin", "remplace": old[0] if old else None}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        for city in ("Lyon", "Nantes", "Lyon"):
            await chat(kernel, "user_2", [f"J'habite à {city} maintenant", *SIX[1:]], gap_s=30)
            await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    active = [r["text"] for r in rows if r["kind"] == "belief" and r["status"] == "active"]
    assert active == ["Alice habite à Lyon"], rows


def test_restating_a_belief_while_pointing_at_itself_is_not_a_revision(tmp_path):
    """Le modèle redit « Alice habite à Lyon » en désignant cette même croyance comme remplacée : ce n'est pas
    changer d'avis — aucune pensée « Je croyais que… — apparemment ce n'est plus vrai » (sonde réelle du
    2026-10-02, où elle « révisait » trois fois une croyance par elle-même). Contre-exemple : Lyon puis Nantes,
    oui."""
    def extract(prompt):
        head, _, body = prompt.partition("Les messages :")
        known = dict((city, int(i)) for i, city in re.findall(r"^\[#(\d+)\] Alice habite à (\w+)$", head, re.M))
        said_ = re.findall(r"J'habite à (\w+)", body)
        if not said_:
            return None
        city = said_[-1]
        old = list(known.values())
        return {"croyances": [{"texte": f"Alice habite à {city}", "personnes": [token(prompt, "Alice")],
                               "sensibilite": "anodin", "remplace": old[0] if old else None}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        revisions = []
        for city in ("Lyon", "Lyon", "Nantes"):
            await chat(kernel, "user_2", [f"J'habite à {city}", *SIX[1:]], gap_s=30)
            await asyncio.sleep(15 * 60)
            revisions.append(len([t for t in kernel.mind.frame().get(attention_c.THOUGHTS)
                                  if t.origin == attention_c.REVISION]))
        await kernel.stop()
        return revisions

    assert run_virtual(clock, main) == [0, 0, 1]


def test_the_same_informant_repeating_does_not_make_it_surer(tmp_path):
    """Alice le dit, Carol le confirme (plus sûr), puis Carol le redit : ce
    n'est pas une troisième source."""
    fact = "Samedi c'est le mariage de Julie, la sœur d'Alice (CANARI-J1)"

    def extract(prompt):
        body = prompt.split("Les messages :")[-1]
        if "CANARI-J1" not in body:
            return None
        who = re.search(r"Conversation privée avec (\w+) (\[P\d+\])", prompt)
        return {"croyances": [{"texte": fact, "personnes": ["Alice"], "source": who.group(2),
                               "sensibilite": "anodin", "confiance": 0.7, "messages": seq_of(body, "CANARI-J1")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_4", "Carol")
        for handle in ("user_2", "user_4", "user_4"):
            await chat(kernel, handle, ["CANARI-J1 samedi c'est le mariage de Julie, la sœur d'Alice", *SIX[1:]])
            await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    beliefs = [r for r in rows if r["kind"] == "belief"]
    assert len(beliefs) == 1
    assert abs(beliefs[0]["confidence"] - 0.8) < 1e-9, "Carol a corroboré une fois ; se répéter n'ajoute rien"
    assert beliefs[0]["informants"] == ["user_2", "user_4"]


@pytest.mark.parametrize("a, b, same", [
    ("Alice habite à Lyon", "alice habite a Lyon.", True),
    ("Adrien a un entretien jeudi", "Adrien a un entretien jeudi !", True),
    ("Alice habite à Lyon", "Alice n'habite pas à Lyon", False),  # une négation n'est pas un détail
    ("Alice habite à Lyon", "Alice habite à Nantes", False),
    ("", "Alice habite à Lyon", False),
])
def test_a_belief_said_again_word_for_word_is_the_same_belief(a, b, same):
    assert same_words(a, b) is same


@pytest.mark.parametrize("cite", ["mika", "alice"])
def test_what_she_said_about_someone_is_not_something_she_learned(tmp_path, cite):
    """Ce qu'elle a dit elle-même d'autrui n'est pas ce qu'on lui a appris : la sonde réelle l'a vue inventer
    « il ne m'a rien dit » devant Chloé, puis l'extraction en faire une croyance sur Adrien. Contre-exemple : ce
    qu'Alice a dit d'elle-même se retient."""
    def extract(prompt):
        body = prompt.split("Les messages :")[-1]
        if "CANARI-U1" not in body:
            return None
        cited = seq_of(body, "CANARI-M1" if cite == "mika" else "CANARI-U1")
        return {"croyances": [{"texte": "Alice déménage à Lyon (CANARI-B1)", "personnes": [token(prompt, "Alice")],
                               "sensibilite": "anodin", "messages": cited}]}

    script = Script(extract, reply="CANARI-M1 ah, je crois qu'elle déménage à Lyon [EMOTION:curious:0.3]")
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["CANARI-U1 je déménage à Lyon le mois prochain", *SIX[1:]], gap_s=30)
        await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    stored = [r for r in run_virtual(clock, main) if "CANARI-B1" in r["text"]]
    assert bool(stored) is (cite == "alice")
    assert clean_tokens("J'ai discuté avec Chloé [P1] : elle dessine") == "J'ai discuté avec Chloé : elle dessine"


def test_she_remembers_by_the_time_it_was_said(tmp_path):
    """« tu te souviens de ce que je t'ai dit lundi matin ? » ne contient aucun mot du souvenir : elle le
    retrouve par le temps (sonde réelle du 2026-10-02 : elle ne retrouvait pas l'entretien annoncé lundi matin).
    Contre-exemple : la même question sur mardi soir rend ce qui s'est dit mardi soir, pas lundi matin."""
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script, start=at_paris(2026, 10, 5, 8, 30))

    async def main():
        await boot(kernel)
        await composition.configure(kernel, DOC, {"transcript": {"window": 2}})  # lundi n'est plus dans le fil
        await connect(kernel, "user_2", "Adrien")
        await chat(kernel, "user_2", ["CANARI-T1 j'ai un entretien chez Ubisoft jeudi à 14h", *SIX[1:3]], gap_s=60)
        await asyncio.sleep((at_paris(2026, 10, 6, 20, 0) - clock.now()) / US)
        await chat(kernel, "user_2", ["CANARI-T2 mon chat a vomi sur le canapé ce soir", *SIX[3:5]], gap_s=60)
        await asyncio.sleep((at_paris(2026, 10, 11, 15, 0) - clock.now()) / US)
        await chat(kernel, "user_2", ["tu te souviens de ce que je t'ai dit lundi matin ?"])
        monday = section(script.replies("user_2")[-1], EXCHANGES)
        await chat(kernel, "user_2", ["et ce que je t'ai raconté mardi soir ?"])
        tuesday = section(script.replies("user_2")[-1], EXCHANGES)
        await kernel.stop()
        return monday, tuesday

    monday, tuesday = run_virtual(clock, main)
    assert "CANARI-T1" in monday and "CANARI-T2" not in monday, monday
    assert "CANARI-T2" in tuesday, tuesday


def test_the_moment_she_is_asked_about_is_quoted_even_when_still_in_the_thread(tmp_path):
    """Toute la semaine est encore dans le fil montré : « ce que je t'ai dit lundi matin ? » cite quand même ce
    qu'Adrien a dit lundi matin, à son nom (sonde réelle du 2026-10-03 : noyée dans soixante-sept messages, elle lui
    a prêté son propre rêve). Contre-exemple : sans date, ce que le fil montre déjà ne se répète pas."""
    script = Script()
    kernel, clock, _, _out = build(tmp_path, script, start=at_paris(2026, 10, 5, 8, 30))

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Adrien")
        await chat(kernel, "user_2", ["CANARI-T1 j'ai un entretien chez Ubisoft jeudi à 14h", *SIX[1:3]], gap_s=60)
        await asyncio.sleep((at_paris(2026, 10, 6, 20, 0) - clock.now()) / US)
        await chat(kernel, "user_2", ["CANARI-T2 mon chat a vomi sur le canapé ce soir", *SIX[3:5]], gap_s=60)
        await asyncio.sleep((at_paris(2026, 10, 11, 15, 0) - clock.now()) / US)
        await chat(kernel, "user_2", ["tu te souviens de ce que je t'ai dit lundi matin ?"])
        reply = script.replies("user_2")[-1]
        monday = section(reply, EXCHANGES)
        await chat(kernel, "user_2", ["tu te souviens de mon entretien chez Ubisoft ?"])
        plain = section(script.replies("user_2")[-1], EXCHANGES)
        await kernel.stop()
        return reply, monday, plain

    reply, monday, plain = run_virtual(clock, main)
    assert "CANARI-T1" in reply.replace(monday, ""), "le test suppose lundi encore dans le fil"
    assert "Adrien : « CANARI-T1" in monday and "CANARI-T2" not in monday, monday
    assert "CANARI-T1" not in plain, plain
