"""Les pages de détail de la console, dessinées (ADR 0121) : un épisode et ses sept onglets, un événement,
« pourquoi n'a-t-elle pas répondu ? », la recherche. Chacune s'ouvre dessinée, son HTML est valide, ses données y
sont ; demandée en tableau, elle revient aux blocs de la console."""

from __future__ import annotations

from mika.contracts import runtime as rt
from mika.ports.llm import LLMResponse
from tests.protocol.test_console_operator import converse
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def latest(client, live, kind):
    store = live.kernel.mind.store
    return client.portal.call(lambda: store.latest([kind.name], 1))[0]


def test_an_episode_is_drawn_tab_by_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client, "coucou, tu fais quoi ce soir ?")
    base = f"/inspecteur/episode/{latest(client, live, rt.UTTERANCE).correlation}"
    shapes = {"resume": "Ce qui l'a déclenché", "deroule": "Ce qui s'est passé, dans l'ordre", "dit": "Ses paroles",
              "prompt": "Ce qui a décidé du prompt", "outils": "aucun outil", "appels": 'class="now-page episode"',
              "decision": "Ce qui l'a lancé"}
    pages = {}
    for tab, shape in shapes.items():
        pages[tab] = drawn(client, f"{base}?onglet={tab}")
        assert 'class="now-page episode"' in pages[tab] and shape in pages[tab], tab
        assert "/static/handmade/episode.css" in pages[tab], tab
    # le résumé : son issue, le message qui l'a déclenché, ce qu'elle a dit, ses chiffres
    assert "coucou, tu fais quoi ce soir ?" in pages["resume"] and "Ce qu'elle a dit" in pages["resume"]
    assert "Appels de modèle" in pages["resume"] and "/inspecteur/parole/" in pages["resume"]
    # le déroulé : chaque événement sur le fil, avec son lien et, pour une parole, son « pourquoi »
    assert 'class="now-feed episode-feed"' in pages["deroule"] and "/inspecteur/evenement/" in pages["deroule"]
    # le prompt : ses sections dépliables, le contexte complet ouvert, sa réponse pas à pas, « Rejouer avec… »
    prompt = pages["prompt"]
    assert "Le contexte complet, tel qu'envoyé au modèle" in prompt and "QUI TU AS EN FACE" in prompt
    assert "Sa réponse, pas à pas" in prompt and "Le modèle principal" in prompt and "Rejouer avec" in prompt
    # au repli, les blocs de la console
    table = drawn(client, f"{base}?onglet=deroule&vue_x=table")
    assert "now-page episode" not in table and "Déroulé" in table


def test_an_event_is_drawn_with_its_text_its_path_and_what_it_started(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client, "tu as vu la pluie ?")
    asked = latest(client, live, rt.PERCEPTION_RECEIVED)
    page = drawn(client, f"/inspecteur/evenement/{asked.seq}")
    assert 'class="now-page evenement"' in page and "/static/handmade/episode.css" in page
    assert "tu as vu la pluie ?" in page and "Son parcours dans la machine" in page
    assert "Ce qu'il a déclenché" in page and "/inspecteur/episode/" in page and "Ses données brutes" in page
    said = drawn(client, f"/inspecteur/evenement/{latest(client, live, rt.UTTERANCE).seq}")
    assert "Pourquoi a-t-elle dit ça ? →" in said and 'class="mine"' in said
    blocks = drawn(client, f"/inspecteur/evenement/{asked.seq}?vue_x=table")
    assert "now-page evenement" not in blocks and "Données (techniques)" in blocks


def test_a_message_left_unanswered_says_why_drawn(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)

    async def silent(req):
        backend.calls.append(req)
        return LLMResponse("[EMOTION:sad:0.4]")  # rien d'autre que la balise : elle s'abstient

    backend.complete = silent
    converse(client, "tu m'en veux ?")
    asked = latest(client, live, rt.PERCEPTION_RECEIVED)
    page = drawn(client, f"/inspecteur/parole/{asked.seq}")
    assert 'class="now-page parole silence"' in page and "tu m'en veux ?" in page
    assert "Pourquoi elle n'a pas répondu" in page and "Un silence choisi" in page
    assert "Comment ça s'est réglé" in page and "Ce qu'elle avait sous les yeux" in page
    blocks = drawn(client, f"/inspecteur/parole/{asked.seq}?vue_x=table")
    assert "now-page parole" not in blocks and "Un silence choisi" in blocks


def test_search_is_drawn_one_card_per_kind_of_result(world):  # noqa: F811
    client, _live, _ = world
    bootstrap(client)
    converse(client, "salut")
    page = drawn(client, "/inspecteur/recherche?q=adrien")
    assert 'class="now-page recherche"' in page and 'class="now-card search-group"' in page
    assert "/inspecteur/fiche/person/" in page
    pages = drawn(client, "/inspecteur/recherche?q=humeur")
    assert "Pages de la console" in pages
    everything = drawn(client, "/inspecteur/recherche")  # sans rien tapé : tout, sorte par sorte
    assert 'class="now-page recherche"' in everything and "/inspecteur/fiche/person/" in everything
    blocks = drawn(client, "/inspecteur/recherche?q=adrien&vue_x=table")
    assert "now-page recherche" not in blocks and "/inspecteur/fiche/person/" in blocks
