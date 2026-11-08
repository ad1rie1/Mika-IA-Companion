"""Relations & échanges › Teams, chaque onglet dans sa forme (``app/handmade/tabs/teams.py``, ADR 0177), à travers le
vrai serveur : ses conversations comme une messagerie (leur dernier message), ses réponses qui attendent ton accord
d'abord, en face du message auquel elles répondent ; l'extension, ses chiffres et comment la brancher."""

from __future__ import annotations

import json
import re

from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.ports.teams import Draft as TeamsDraft
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_people import emit
from tests.protocol.test_teams_web import DM, batch, headers, new_key
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def _between(page: str, start: str, end: str) -> str:
    return page.split(start, 1)[1].split(end, 1)[0]


def plugged(client, live) -> None:
    key = new_key(client, live)
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(key)).status_code == 202


def test_without_the_extension_each_tab_says_how_to_plug_it(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    page = drawn(client, "/inspecteur/teams/conversations")
    assert 'data-tab="teams/conversations"' in page and "L'extension n'a encore rien apporté" in page
    steps = _between(page, 'class="teams-steps"', "</ol>")
    assert steps.index("L'installer") < steps.index("Lui donner sa clé") < steps.index("Ouvrir Teams")
    assert 'href="/inspecteur/teams/parametres"' in steps  # ses comptes : Teams › Paramètres (ADR 0206)
    extension = drawn(client, "/inspecteur/teams/extension")
    assert extension.count('class="person-tab-note warn"') == 1 and "La brancher" in extension
    assert "aucune réponse préparée" in drawn(client, "/inspecteur/teams/reponses")


def test_conversations_read_like_a_messenger(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    page = drawn(client, "/inspecteur/teams/conversations")
    conv = _between(page, 'class="teams-inbox"', "</ul>")
    assert "Alice" in conv and "tête-à-tête" in conv and 'class="teams-mark dm"' in conv
    assert "On se voit à 14 h ?" in _between(conv, 'class="teams-last"', "</p>")  # son dernier message
    assert f'href="/inspecteur/fiche/conversation_teams/{DM.replace(":", "%3A").replace("@", "%40")}"' in conv
    assert 'href="?vue_pg1=table"' in page  # la bascule « Tableau » du plugin


def test_replies_waiting_for_you_come_first_facing_the_message(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    store = live.kernel.ports["teams"]
    [message] = client.portal.call(store.thread, "principal", DM, 10)
    draft = client.portal.call(store.save_draft, TeamsDraft(id="", conversation=DM, body="Oui, 14 h me va.",
                                                            reply_to=message.ref))
    emit(client, live, "runtime", [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Alice dans Teams"), context="teams",
        approval=True, args_json=json.dumps({"draft": draft.id, "conversation": DM, "message": message.ref,
                                             "mode": "validation"}))])
    page = drawn(client, "/inspecteur/teams/reponses")
    pending = _between(page, 'class="teams-pending"', "Ce qu'elles sont devenues")
    assert pending.index("On se voit à 14 h ?") < pending.index("Oui, 14 h me va.")  # le message, puis sa réponse
    assert f'href="/inspecteur/fiche/reponse_teams/{draft.id}">Examiner et décider' in pending
    assert page.index("Attendent ton accord") < page.index("Ce qu'elles sont devenues")
    assert 'href="/inspecteur/envoi"' in page  # « Envoyer à ta place », dit par le plugin, avec son lien
    extension = drawn(client, "/inspecteur/teams/extension")
    band = _between(extension, 'class="person-tiles teams-band"', "</section>")
    # les chiffres d'un compte mènent aux onglets de ce compte (ADR 0186)
    assert "Réponses à décider" in band and 'href="/inspecteur/teams/reponses?compte=principal"' in band
    assert "Adrien" in _between(extension, "Ce compte Teams", "</section>")
    assert 'class="person-tab-note warn"' not in extension  # branchée : pas de bandeau
    # son compte et sa clé côte à côte (ADR 0206) : sa voix et sa signature mènent à ce compte dans Teams › Paramètres,
    # qui ramène à son extension une fois enregistré
    voice = _between(extension, "Sa voix, sa signature", "</dd>")
    edit = voice.split('href="', 1)[1].split('"', 1)[0]
    assert ">Modifier ce compte<" in voice and edit.startswith("/inspecteur/teams/parametres?") and "cle=principal" in edit
    account = drawn(client, edit)
    assert re.search(r"<h1>Compte « [^<]+ »</h1>", account), _between(account, "<h1", "</h1>")
    assert 'name="_retour" value="/inspecteur/teams/extension?compte=principal"' in account
