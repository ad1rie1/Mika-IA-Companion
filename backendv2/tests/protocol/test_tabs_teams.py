"""Relations & échanges › Teams, chaque onglet dans sa forme (``app/handmade/tabs/teams.py``, ADR 0177), à travers le
vrai serveur : ses conversations comme une messagerie (leur dernier message), ses réponses qui attendent ton accord
d'abord, en face du message auquel elles répondent ; l'extension, ses chiffres et comment la brancher."""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from mika.contracts import runtime as rt
from mika.contracts import teams as teams_c
from mika.kernel.events import Content
from mika.ports.teams import Draft as TeamsDraft
from tests.protocol.test_drawn_fiches import form_of
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
    page = drawn(client, "/admin/teams/conversations")
    assert 'data-tab="teams/conversations"' in page and "L'extension n'a encore rien apporté" in page
    steps = _between(page, 'class="teams-steps"', "</ol>")
    assert steps.index("L'installer") < steps.index("Lui donner sa clé") < steps.index("Ouvrir Teams")
    assert 'href="/admin/teams/parametres"' in steps  # ses comptes : Teams › Paramètres (ADR 0206)
    extension = drawn(client, "/admin/teams/extension")
    assert extension.count('class="person-tab-note warn"') == 1 and "La brancher" in extension
    assert "aucune réponse préparée" in drawn(client, "/admin/teams/reponses")


def test_conversations_read_like_a_messenger(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    page = drawn(client, "/admin/teams/conversations")
    conv = _between(page, 'class="teams-inbox"', "</ul>")
    assert "Alice" in conv and "tête-à-tête" in conv and 'class="teams-mark dm"' in conv
    assert "On se voit à 14 h ?" in _between(conv, 'class="teams-last"', "</p>")  # son dernier message
    assert f'href="/admin/fiche/conversation_teams/{DM.replace(":", "%3A").replace("@", "%40")}"' in conv
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
    page = drawn(client, "/admin/teams/reponses")
    pending = _between(page, 'class="teams-pending"', "Ce qu'elles sont devenues")
    assert pending.index("On se voit à 14 h ?") < pending.index("Oui, 14 h me va.")  # le message, puis sa réponse
    assert f'href="/admin/fiche/reponse_teams/{draft.id}">Examiner et décider' in pending
    assert page.index("Attendent ton accord") < page.index("Ce qu'elles sont devenues")
    # en pied, comment elles partent : le tableau de Teams dans Réglages › Canaux, celui du seul compte (ADR 0134 :
    # « Envoyer à ta place » y est fondu, sa page n'existe plus)
    about = _between(page, 'class="person-tab-note teams-about"', "</p>")
    assert 'href="/admin/reglages/canaux?canal=teams%3Aprincipal"' in about and "Réglages › Canaux" in about
    assert "/admin/envoi" not in page and "Envoyer à ta place" not in page
    extension = drawn(client, "/admin/teams/extension")
    band = _between(extension, 'class="person-tiles teams-band"', "</section>")
    # les chiffres d'un compte mènent aux onglets de ce compte (ADR 0186)
    assert "Réponses à décider" in band and 'href="/admin/teams/reponses?compte=principal"' in band
    assert "Adrien" in _between(extension, "Ce compte Teams", "</section>")
    assert 'class="person-tab-note warn"' not in extension  # branchée : pas de bandeau
    # son compte et sa clé côte à côte (ADR 0206) : sa voix et sa signature mènent à ce compte dans Teams › Paramètres,
    # qui ramène à son extension une fois enregistré
    voice = _between(extension, "Sa voix, sa signature", "</dd>")
    edit = voice.split('href="', 1)[1].split('"', 1)[0]
    assert ">Modifier ce compte<" in voice and edit.startswith("/admin/teams/parametres?") and "cle=principal" in edit
    account = drawn(client, edit)
    assert re.search(r"<h1>Compte « [^<]+ »</h1>", account), _between(account, "<h1", "</h1>")
    assert 'name="_retour" value="/admin/teams/extension?compte=principal"' in account


# ── une réponse dont le compte n'est plus réglé ──

#: le badge de l'onglet Réponses, dans la barre d'onglets de Teams
REPLIES_TAB = re.compile(r'<a class="tab[^"]*" href="/admin/teams/reponses"[^>]*>Réponses(?:<span class="count"'
                         r'[^>]*>(\d+)</span>)?</a>')


def retired_reply(client, live) -> str:
    """Une réponse qui attend ton accord sur un compte qui n'est plus réglé (« ancien ») : ``drop_account`` a emporté
    son brouillon, sa proposition reste au journal jusqu'à son échéance (le réducteur lit son compte)."""
    emit(client, live, "runtime", [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Bob dans Teams"), context="teams",
        approval=True, args_json=json.dumps({"draft": "brouillon-ancien", "conversation": "19:ancien@thread.v2",
                                             "message": "ancien:m1", "mode": "validation", "account": "ancien"}))])
    return "brouillon-ancien"


def replies_badge(page: str) -> str:
    found = REPLIES_TAB.search(page)
    assert found is not None, "pas d'onglet Réponses"
    return found.group(1) or ""


def test_a_reply_waiting_on_a_retired_account_is_listed_where_its_badge_counts_it(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    draft = retired_reply(client, live)
    page = drawn(client, "/admin/teams/reponses")
    assert replies_badge(page) == "1"
    # sous « Tout le monde », elle est dans la file, nommée par ce qui lui reste : un compte retiré, une réponse
    # disparue — et sa ligne mène à sa fiche
    pending = _between(page, 'class="teams-pending"', "Ce qu'elles sont devenues")
    assert "un compte retiré" in pending and "cette réponse n'existe plus" in pending
    assert "en réponse à rien" not in pending
    assert f'href="/admin/fiche/reponse_teams/{draft}">Examiner et décider' in pending
    # le seul compte réglé ne réduit pas la liste ; son lien du pied, lui, reste le tableau de ce compte (K8-L2)
    about = _between(page, 'class="person-tab-note teams-about"', "</p>")
    assert 'href="/admin/reglages/canaux?canal=teams%3Aprincipal"' in about
    # un compte choisi : les siennes seulement
    chosen = drawn(client, "/admin/teams/reponses?compte=principal")
    assert f"/admin/fiche/reponse_teams/{draft}" not in chosen and "un compte retiré" not in chosen
    # sous « Les comptes de » toi : les tiens, pas celles d'un compte qui n'est plus réglé
    assert f"/admin/fiche/reponse_teams/{draft}" not in drawn(client, "/admin/teams/reponses?qui=toi")


def test_a_vanished_reply_still_waiting_is_refused_on_its_fiche(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    draft = retired_reply(client, live)
    fiche = drawn(client, f"/admin/fiche/reponse_teams/{draft}")
    assert "Cette réponse n'existe plus : elle ne partira pas." in fiche and "attend ton accord" in fiche
    assert "/admin/action/teams.refuser" in fiche
    refused = client.post("/admin/action/teams.refuser",
                          data={**form_of(fiche, "teams.refuser"), "note": "ce compte est fermé"},
                          follow_redirects=False)
    assert refused.status_code == 303
    decided = drawn(client, f"/admin/fiche/reponse_teams/{draft}")
    assert "refusée" in decided and "/admin/action/teams.refuser" not in decided
    page = drawn(client, "/admin/teams/reponses")
    assert replies_badge(page) == ""  # plus rien n'attend ton accord
    assert "Aucune réponse n'attend ton accord." in page
    done = _between(page, 'class="teams-done"', "</ul>")
    assert "refusée" in done and f"/admin/fiche/reponse_teams/{draft}" in done


def test_a_waiting_reply_that_names_no_draft_is_decided_in_the_queue(world):  # noqa: F811
    """Une proposition qui ne nomme aucun brouillon (celle de l'aperçu de la console) n'a pas de fiche : sa ligne mène
    à « À valider › Réponses Teams », où elle se décide — jamais à une fiche sans clé."""
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    emit(client, live, "runtime", [rt.EFFECT_PROPOSED.draft(
        capability="teams.send", owner="teams", summary=Content.of("Répondre à Léa dans Teams"), context="teams",
        approval=True, args_json=json.dumps({"conversation": "19:projet", "text": "Je regarde ça demain matin."}))])
    page = drawn(client, "/admin/teams/reponses")
    pending = _between(page, 'class="teams-pending"', "Ce qu'elles sont devenues")
    assert 'href="/admin/approbations/teams">Examiner et décider' in pending
    assert 'href="/admin/fiche/reponse_teams/"' not in page


def test_asking_her_for_a_reply_bears_one_name(world):  # noqa: F811
    """« Lui demander une réponse » : le nom de l'action, que la carte de la fiche porte déjà — son formulaire y est
    sans le repli de la vue ni son titre, pour ne pas dire deux fois le même nom l'un sous l'autre."""
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    page = drawn(client, f"/admin/fiche/conversation_teams/{quote(DM, safe='')}")
    ask = _between(page, 'aria-labelledby="teams-ask"', "</section>")
    assert 'action="/admin/action/teams.rediger"' in ask
    assert ask.count("Lui demander une réponse") == 2  # la carte, son bouton
    assert "<summary" not in ask and "<h3>" not in ask and "préparer une réponse" not in ask


def test_the_questions_of_a_conversation_are_counted_in_words(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    plugged(client, live)
    emit(client, live, "teams", [teams_c.NOTICED.draft(
        source="teams", kind="message", summary=Content.of(f"Alice demande {n}"), pertinence=0.5,
        message=f"principal:question-{n}", conversation=DM, author="Alice", author_id="8:orgid:a", where="dm",
        needs_reply=True, account="principal") for n in (1, 2)])
    page = drawn(client, "/admin/teams/conversations")
    conv = _between(page, 'class="teams-inbox"', "</ul>")
    assert "2 questions" in conv and "question(s)" not in page  # accordé, comme partout (kernel.inspect.plural)
