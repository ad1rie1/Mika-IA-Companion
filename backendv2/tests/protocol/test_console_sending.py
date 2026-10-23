"""« Envoyer à ta place » dans la console (ADR 0132), le parcours d'un opérateur : la page dessinée (ses règles, la
règle par défaut), ajouter, régler, monter et retirer une règle ; chaque envoi enregistré puis rejournalisé dans les
paramètres du courrier et de Teams ; une règle illisible refusée sans rien changer."""

from __future__ import annotations

import html

from mika.vocab.sending import TEAMS, Sending, SendRule
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE, POST = "/inspecteur/envoi", "/inspecteur/envoi/regler"


def send(client, faire: str = "", **fields: str):
    r = client.post(POST, data={"csrf": client.cookies.get("csrftoken"), "faire": faire, **fields})
    assert r.status_code == 200, r.text[:1000]
    return html.unescape(r.text)


def test_an_operator_writes_her_sending_rules_and_she_follows_them(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.portal.call(live.settings.save_sending, Sending())
    page = html.unescape(client.get(PAGE).text)
    assert "Envoyer à ta place" in page and "Comportement par défaut" in page and "+ Ajouter une règle" in page
    assert 'href="/inspecteur/envoi"' in html.unescape(client.get("/inspecteur").text)  # dans le menu
    # ajouter : une règle ouverte (le courrier, tout le monde, elle prépare, ton accord), à régler
    assert "Règle 1 ajoutée" in send(client, "ajouter", defaut_send="accord")
    (added,) = client.portal.call(live.settings.sending).rules
    assert added == SendRule(canal="courrier", prepare=True, send="accord")
    # régler deux règles d'un envoi, puis monter la seconde : l'ordre décide
    done = send(client, "monter:2", **{"canal.1": "courrier", "prepare.1": "on", "send.1": "accord",
                                       "canal.2": TEAMS, "dest.2": "RH", "send.2": "seule",
                                       "defaut_prepare": "on", "defaut_send": "seule"})
    assert "Règle 2 montée" in done
    got = client.portal.call(live.settings.sending)
    assert got.rules == (SendRule(canal=TEAMS, dest="rh", send="seule"), added)
    assert got.default == SendRule(prepare=True, send="seule")
    # rejournalisées : le courrier et Teams les suivent
    for owner in ("email", "teams"):
        assert live.kernel.mind.registry.params_of(owner, live.kernel.mind.root).sending == got
    # une règle illisible : refusée, rien ne change
    refused = send(client, **{"canal.1": "sms", "defaut_send": "accord"})
    assert "Règle 1 illisible" in refused and client.portal.call(live.settings.sending) == got
    # retirer
    assert "Règle 1 retirée" in send(client, "retirer:1", **{"canal.1": TEAMS, "dest.1": "rh", "send.1": "seule",
                                                             "canal.2": "courrier", "prepare.2": "on",
                                                             "send.2": "accord", "defaut_send": "seule"})
    assert client.portal.call(live.settings.sending).rules == (added,)
    # sans jeton de formulaire : rien
    client.post(POST, data={"csrf": "faux", "faire": "ajouter"})
    assert client.portal.call(live.settings.sending).rules == (added,)
