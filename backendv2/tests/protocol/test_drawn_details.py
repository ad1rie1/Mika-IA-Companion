"""Les pages de détail de la console, dessinées (ADR 0121) : un épisode et ses sept onglets, un événement,
« pourquoi n'a-t-elle pas répondu ? », la recherche. Chacune s'ouvre dessinée, son HTML est valide, ses données y
sont ; demandée en tableau, elle revient aux blocs de la console."""

from __future__ import annotations

import re
import time

from sqlalchemy import select

from mika.adapters.llm.gateway import LLMTrace
from mika.app.console import ENRICHER_LABELS
from mika.contracts import runtime as rt
from mika.inspector.pages import episode_drawn
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.ports.journal import JournalOutbox
from mika.ports.llm import LLMResponse
from mika.vocab.privacy import LEVEL_WORDS
from tests.protocol.test_console_diagnostics import stop
from tests.protocol.test_console_operator import converse
from tests.protocol.test_console_workflows import tab_count
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def latest(client, live, kind):
    store = live.kernel.mind.store
    return client.portal.call(lambda: store.latest([kind.name], 1))[0]


def tile(page: str, label: str) -> str:
    """Le chiffre d'une tuile du Résumé d'un épisode."""
    got = re.search(rf'<span class="person-tile-label">{label}</span><span class="person-tile-value now-num">([^<]+)<',
                    page)
    assert got is not None, label
    return got.group(1)


def tile_sub(page: str, label: str) -> str:
    """La sous-ligne d'une tuile d'un épisode (ce que dit son chiffre)."""
    got = re.search(rf'<span class="person-tile-label">{label}</span><span class="person-tile-value now-num">[^<]+'
                    r'</span><span class="person-tile-sub">([^<]*)<', page)
    assert got is not None, label
    return got.group(1)


def _episode(client, kernel, corr: str, *, tools=(), trace=None) -> None:
    """Un épisode au journal : une réponse, une parole qui nomme ``tools`` ; sa trace, ``trace``, gardée s'il y en a
    une. L'appelant a arrêté l'ordonnanceur (``stop``) : rien d'autre ne s'y ajoute."""
    voice = VoiceProvenance(call_id=f"{corr}#0", persona_hash="fictive", role="reply", model="fake")

    async def seed():
        await kernel.mind.append([
            rt.EPISODE_STARTED.draft(kind="REPLY", target="user_1"),
            rt.UTTERANCE.draft(kind="REPLY", target="user_1", voice=voice, text=Content.of("Je regarde."),
                               tools=tuple(rt.ToolOutcome(name=n, ok=ok) for n, ok in tools)),
            rt.EPISODE_ENDED.draft(kind="REPLY", outcome="done", target="user_1")],
            emitter="runtime", origin=Origin.GENESIS, correlation=corr)
        if trace is not None:
            kernel.traces.record(corr, kernel.mind.clock.now(), "REPLY", "user_1", trace)
            await kernel.traces.flush()

    client.portal.call(seed)


def test_the_tools_tab_counts_the_calls_it_shows_from_the_trace_or_else_from_her_speeches(world):  # noqa: F811
    """La pastille d'Outils est le chiffre de la tuile « Outils appelés » : les appels de la trace gardée (pas ceux que
    nomment ses paroles), sinon, sans trace, les outils nommés sur ses paroles ; la sous-ligne dit d'où vient le
    compte, et l'onglet montre ce qu'il compte."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    calls = [{"name": "web_search", "ok": True, "args": "{}", "result": "trois liens"},
             {"name": "memory_recall", "ok": True, "args": "{}", "result": "un souvenir"},
             {"name": "email_read", "ok": False, "args": "{}", "result": "refusé"}]
    _episode(client, kernel, "tools-traced", tools=(("web_search", True),), trace={"tool_calls": calls,
                                                                                   "outcome": "done"})
    resume = drawn(client, "/inspecteur/episode/tools-traced")
    assert tile(resume, "Outils appelés") == "3" and tab_count(resume, "outils") == "3"
    assert tile_sub(resume, "Outils appelés") == "d'après la trace"
    shown = drawn(client, "/inspecteur/episode/tools-traced?onglet=outils")
    assert tab_count(shown, "outils") == "3" and all(c["name"] in shown for c in calls)

    _episode(client, kernel, "tools-said", tools=(("web_search", True), ("email_read", False)))
    resume = drawn(client, "/inspecteur/episode/tools-said")
    assert tile(resume, "Outils appelés") == "2" and tab_count(resume, "outils") == "2"
    assert tile_sub(resume, "Outils appelés") == "nommés sur ses paroles"
    shown = drawn(client, "/inspecteur/episode/tools-said?onglet=outils")
    assert tab_count(shown, "outils") == "2" and "web_search" in shown and "email_read" in shown

    # ni trace ni outil nommé : pas de pastille, la tuile dit « — »
    _episode(client, kernel, "tools-none")
    resume = drawn(client, "/inspecteur/episode/tools-none")
    assert tile(resume, "Outils appelés") == "—" and tab_count(resume, "outils") is None
    assert tile_sub(resume, "Outils appelés") == "trace non gardée"


def test_beyond_the_calls_it_reads_an_episode_says_its_sums_cover_only_the_first(world, monkeypatch):  # noqa: F811
    """Le nombre d'appels de modèle est celui du registre (la pastille, les deux tuiles) ; leurs sommes (coût,
    jetons, durée, échecs) portent sur les ``CALLS_COUNTED`` premiers : au-delà, la tuile du Résumé et l'onglet
    Appels de modèle le disent, et en deçà ils se taisent."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    _episode(client, kernel, "many-calls")
    now = kernel.mind.clock.now()

    async def seed():
        for i in range(3):
            live.calls.record(LLMTrace(
                at=now + i, role="reply", backend="claude", model="claude-haiku-5-5", lane="fg", priority=0,
                latency_us=1_000_000, wait_us=0, input_tokens=1000, output_tokens=100, outcome="ok",
                call_id=f"many-calls#{i}", cost_usd=0.01, correlation="many-calls"))
        await live.calls.flush()

    client.portal.call(seed)
    url = "/inspecteur/episode/many-calls"
    resume, shown = drawn(client, url), drawn(client, f"{url}?onglet=appels")
    assert tile(resume, "Appels de modèle") == "3" == tab_count(resume, "appels") == tile(shown, "Appels")
    assert "premiers" not in tile_sub(resume, "Appels de modèle") and "premiers appels" not in shown

    monkeypatch.setattr(episode_drawn, "CALLS_COUNTED", 2)
    resume, shown = drawn(client, url), drawn(client, f"{url}?onglet=appels")
    # le nombre reste celui du registre, partout le même
    assert tile(resume, "Appels de modèle") == "3" == tab_count(resume, "appels") == tile(shown, "Appels")
    # le coût de la tuile, et les sommes de l'onglet, disent sur combien ils portent
    assert tile_sub(resume, "Appels de modèle").endswith("pour les 2 premiers")
    assert "Échecs, jetons, coût et durée : les 2 premiers appels sur 3." in shown


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
    # ses onglets disent leur compte, celui que dit le Résumé : ses paroles, ses événements, ses appels de modèle ;
    # Outils (elle n'en a appelé aucun) n'a pas de pastille, ni Résumé, Prompt et Décision, qui ne comptent rien
    resume = pages["resume"]
    assert int(tile(resume, "Paroles produites")) >= 1 and int(tile(resume, "Événements")) >= 3
    for slug, label in (("dit", "Paroles produites"), ("deroule", "Événements"), ("appels", "Appels de modèle")):
        said = tile(resume, label)
        assert tab_count(resume, slug) == (None if said == "0" else said), slug
    for slug in ("resume", "outils", "prompt", "decision"):
        assert tab_count(resume, slug) is None, slug
    # chaque onglet porte la même barre, et son compte est celui qu'il montre (« n au total »)
    assert f"{tab_count(pages['deroule'], 'deroule')} au total" in pages["deroule"]
    assert f"{tab_count(pages['dit'], 'dit')} au total" in pages["dit"]
    # le grand encart du Résumé dit son issue et son détail, sans redire l'en-tête (sa sorte, à qui, quand)
    hero = resume.split('class="now-card episode-hero', 1)[1].split("</section>", 1)[0]
    assert "Son issue" in hero and 'class="episode-outcome"' in hero
    assert "Résultat de l’épisode" not in hero and "vers " not in hero and "réponse" not in hero
    assert not re.search(r"\d{2}/\d{2}/\d{4}", hero)
    # « Ce qu'elle a dit » compte ses paroles accordées : toutes montrées, « 1 parole. », jamais « Les 1 dernières »
    said = resume.split('id="episode-said"', 1)[1].split("</header>", 1)[0]
    assert f"<p>{tile(resume, 'Paroles produites')} parole" in said and "dernières" not in said
    # le déroulé : chaque événement sur le fil, avec son lien et, pour une parole, son « pourquoi »
    assert 'class="now-feed episode-feed"' in pages["deroule"] and "/inspecteur/evenement/" in pages["deroule"]
    # le prompt : ses sections dépliables, le contexte complet ouvert, sa réponse pas à pas, « Rejouer avec… »
    prompt = pages["prompt"]
    assert "Le contexte complet, tel qu'envoyé au modèle" in prompt and "QUI TU AS EN FACE" in prompt
    assert "Sa réponse, pas à pas" in prompt and "Le modèle principal" in prompt and "Rejouer avec" in prompt
    # ce qui a décidé du prompt, en mots : le message auquel elle répond en lien, ce qu'elle pouvait dire d'autrui,
    # ce qu'elle a rassemblé par ses libellés, l'issue de l'étiquette (« a parlé ») ; l'empreinte du préfixe repliée
    decided = prompt.split('id="episode-decided"', 1)[1].split('id="episode-offered"', 1)[0]
    assert "perception:" not in decided and "their_last_words" not in decided and "own_words" not in decided
    assert re.search(r'/inspecteur/evenement/\d+">message n° \d+</a>', decided)
    assert ENRICHER_LABELS["thread"] in decided and "Détails techniques" in decided
    assert "a parlé" in decided and "terminé" not in decided
    assert re.search(r"<dt>ce qu'elle pouvait dire d'autrui</dt><dd>(" + "|".join(LEVEL_WORDS.values()) + ")</dd>",
                     decided)
    # ses blocs, au repli, disent les mêmes faits par la même fonction (``journal.prompt_facts``)
    blocks = drawn(client, f"{base}?onglet=prompt&vue_x=table")
    assert "now-page episode" not in blocks and "their_last_words" not in blocks and "terminé" not in blocks
    assert re.search(r'/inspecteur/evenement/\d+">message n° \d+</a>', blocks)
    assert ENRICHER_LABELS["thread"] in blocks and "empreinte du préfixe" in blocks and "outils offerts" in blocks
    # « En bref » d'une réponse ne redit pas le message que montre « Ce qui l'a lancé »
    brief = pages["decision"].split('id="episode-what"', 1)[1].split("</section>", 1)[0]
    assert "déclencheur" not in brief and "en réponse à" not in brief and "message n°" in pages["decision"]
    # son repli, sans carte, dit le message en lien ; son déclencheur (``perception:<n>``, ce message) s'y tait
    decided = drawn(client, f"{base}?onglet=decision&vue_x=table")
    assert "now-page episode" not in decided and "<dt>en réponse à</dt>" in decided
    assert "<dt>déclencheur</dt>" not in decided and "perception:" not in decided
    # au repli, les blocs de la console
    table = drawn(client, f"{base}?onglet=deroule&vue_x=table")
    assert "now-page episode" not in table and "Déroulé" in table



def test_a_resumed_reply_says_so_on_its_decision_tab(world):  # noqa: F811
    """Une réponse reprise (``reprise:<n>`` : après un arrêt, une réponse supplantée, son réveil) : la carte « Ce qui
    l'a lancé » montre le message ; « En bref » dit qu'elle a été reprise ; le repli, le message en lien et son
    déclencheur en mots."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)

    async def seed():
        asked = await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web",
                                                                       text=Content.of("tu es revenue ?"))],
                                         emitter="runtime", origin=Origin.EXTERNAL, correlation="resumed-question")
        seq = asked.seqs[0]
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind="REPLY", target="user_1", trigger=f"reprise:{seq}",
                                                           reply_to=seq),
                                  rt.EPISODE_ENDED.draft(kind="REPLY", outcome="done", target="user_1", reply_to=seq)],
                                 emitter="runtime", origin=Origin.GENESIS, correlation="resumed-reply")
        return seq

    seq = client.portal.call(seed)
    page = drawn(client, "/inspecteur/episode/resumed-reply?onglet=decision")
    assert "tu es revenue ?" in page and f'/inspecteur/evenement/{seq}">message n° {seq}</a>' in page
    brief = page.split('id="episode-what"', 1)[1].split("</section>", 1)[0]
    assert "<dt>déclencheur</dt>" in brief and "repris après une interruption" in brief
    assert "en réponse à" not in brief and "message n°" not in brief and "reprise:" not in brief
    blocks = drawn(client, "/inspecteur/episode/resumed-reply?onglet=decision&vue_x=table")
    assert "now-page episode" not in blocks and "<dt>en réponse à</dt>" in blocks and "<dt>déclencheur</dt>" in blocks
    assert f"message n° {seq}, repris après une interruption" in blocks and "reprise:" not in blocks

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


def test_an_event_shows_its_departures_and_a_stuck_one_is_handled_from_it(world):  # noqa: F811
    """Sur la page d'un événement, où l'on arrive depuis le Journal ou une fiche, rien ne disait que sa parole n'était
    jamais partie (audit du 2026-11-05, C8-06). « Ses départs » dit chacune de ses lignes de la file de sortie (l'effet
    en mots, à qui, l'état, les essais, la dernière erreur) ; un départ à traiter porte Relancer / Marquer comme vu,
    qui reviennent à cette page ; un départ parti dit « parti ». Le repli le dit en tableau."""
    client, live, _ = world
    bootstrap(client)
    converse(client, "tu as vu la pluie ?")
    said = latest(client, live, rt.UTTERANCE)
    store = live.kernel.mind.store
    def rows():
        return client.portal.call(lambda: store.query_mind(select(JournalOutbox.key, JournalOutbox.status)
                                                           .where(JournalOutbox.seq == said.seq)))

    for _ in range(100):  # la livraison se clôt juste après la trame « speech »
        if [st for _k, st in rows()] == ["done"]:
            break
        time.sleep(0.02)
    assert [st for _k, st in rows()] == ["done"]
    page = drawn(client, f"/inspecteur/evenement/{said.seq}")
    gone = page[page.index('id="event-departures"'):page.index('id="event-path"')]
    assert "Ses départs" in gone and "Ses messages" in gone and "à adrien" in gone and ">parti<" in gone
    assert "Relancer" not in gone and "Marquer comme vu" not in gone
    key = rows()[0][0]
    client.portal.call(store.mark_outbox, key, "failed", "TimeoutError()")
    page = drawn(client, f"/inspecteur/evenement/{said.seq}")
    gone = page[page.index('id="event-departures"'):page.index('id="event-path"')]
    assert "échoué" in gone and "délai dépassé" in gone and "TimeoutError" not in gone
    assert "Ce message n'est pas parti." in gone and ">Relancer</button>" in gone and "Marquer comme vu" in gone
    assert f'name="cle" value="{key}"' in gone and f'name="_retour" value="/inspecteur/evenement/{said.seq}"' in gone
    token = re.search(r'name="csrf" value="([^"]+)"', gone)
    assert token and token.group(1) == client.cookies.get("csrftoken")
    back = client.post("/inspecteur/systeme/sorties", data={"csrf": token.group(1), "cle": key, "faire": "relancer",
                                                             "_retour": f"/inspecteur/evenement/{said.seq}"},
                       follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"].startswith(f"/inspecteur/evenement/{said.seq}?flash=")
    landed = drawn(client, back.headers["location"])
    assert "Relancé" in landed and "Ses départs" in landed
    # au repli, en tableau
    client.portal.call(store.mark_outbox, key, "failed", "TimeoutError()")
    blocks = drawn(client, f"/inspecteur/evenement/{said.seq}?vue_x=table")
    assert "now-page evenement" not in blocks and "Ses départs" in blocks and "échoué" in blocks
    assert "Ce message n'est pas parti." in blocks and "délai dépassé" in blocks
    # un événement sans départ n'en dit rien
    asked = latest(client, live, rt.PERCEPTION_RECEIVED)
    assert "Ses départs" not in drawn(client, f"/inspecteur/evenement/{asked.seq}")


def _head_facts(page: str) -> str:
    """La ligne de faits de l'en-tête d'une page."""
    got = re.search(r'<div class="head-facts">(.*?)</div>', page, re.S)
    assert got is not None
    return got.group(1)


def test_an_event_says_its_landmarks_on_the_line_of_facts_and_its_fields_and_origin_in_words(world):  # noqa: F811
    """La page d'un message : ses repères (quand, émis par, son origine en mots, son épisode) sur la ligne de faits de
    l'en-tête, pas en puces ; son numéro dans le fil d'Ariane seulement ; son type et l'état du journal qu'il a lu dans
    « Son parcours dans la machine » ; ses champs de contenu en mots, dessinée comme au repli."""
    client, live, _ = world
    bootstrap(client)
    converse(client, "tu as vu la pluie ?")
    asked = latest(client, live, rt.PERCEPTION_RECEIVED)
    page = drawn(client, f"/inspecteur/evenement/{asked.seq}")
    facts = _head_facts(page)
    assert "origine</span>de l'extérieur" in facts and "émis par" in facts and "quand" in facts
    assert "origine : " not in page and "external" not in facts and "now-chips" not in page
    assert "<h1>Message ou signal reçu</h1>" in page and f"<title>Message ou signal reçu · n° {asked.seq}" in page
    assert page.count(f"n° {asked.seq}<") == 1  # le fil d'Ariane, seulement
    path = page[page.index('id="event-path"'):page.index('id="event-who"')]
    assert "<code>perception.received</code>" in path and "état lu" in path and "lu sur la tête" not in page
    assert f'/inspecteur/evenement/{asked.basis}">jusqu\'au n° {asked.basis}</a>' in path
    assert "<code>perception.received</code>" not in page[page.index('id="event-who"'):]
    blocks = drawn(client, f"/inspecteur/evenement/{asked.seq}?vue_x=table")
    assert "origine</span>de l'extérieur" in _head_facts(blocks) and "<h1>Message ou signal reçu</h1>" in blocks
    assert "le texte : présent" in blocks and "text : présent" not in blocks and "lu sur la tête" not in blocks
    assert f"jusqu'au n° {asked.basis}" in blocks and "Son parcours dans la machine" in blocks
    # un texte qui n'est pas une parole : titré en mots, « le résumé », jamais « summary » ; d'un processus
    stop(client, live.kernel)

    async def seed():
        return await live.kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="mail.send", owner="mail", args_json="{}", summary=Content.of("Écrire à Léa pour samedi."))],
            emitter="runtime", origin=Origin.PROCESS, correlation="effect-words")

    proposed = client.portal.call(seed).seqs[0]
    effect = drawn(client, f"/inspecteur/evenement/{proposed}")
    assert '<p class="now-eyebrow">le résumé</p>' in effect and ">summary<" not in effect
    assert "Écrire à Léa pour samedi." in effect and "origine</span>un processus" in _head_facts(effect)
    assert "Pourquoi a-t-elle dit ça ?" not in effect


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
