"""Réglages › Canaux (ADR 0134), le parcours d'un opérateur : chaque canal a son tableau, né de son minimum vital ;
celui d'une boîte de courrier dit ce qu'elle prépare d'elle-même et comment ça part (ADR 0132), et le courrier le
suit, rejournalisé ; une ligne illisible est refusée ; « Revenir au minimum vital » retire le tableau."""

from __future__ import annotations

import html

from mika.vocab.canals import CanalRule, Canals
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/reglages/canaux"
POST = "/inspecteur/reglages/canaux/regler"


def send(client, cle: str, faire: str = "", **fields: str) -> str:
    r = client.post(POST, data={"csrf": client.cookies.get("csrftoken"), "cle": cle, "faire": faire, **fields})
    assert r.status_code == 200, r.status_code
    return html.unescape(r.text)


def test_an_operator_rules_a_canal_and_her_mail_follows(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    page = html.unescape(client.get(PAGE).text)
    for part in ("Par où ça lui arrive", "Chat web", "Courrier", "Elle seule", "minimum vital", "Comportement par défaut"):
        assert part in page, part
    assert 'href="/inspecteur/reglages/canaux"' in html.unescape(client.get("/inspecteur").text)  # dans le menu
    assert client.portal.call(live.settings.canals) == Canals()
    # ajouter une ligne au courrier : tout le monde, toujours, fermée — à régler
    assert "Ligne 2 ajoutée, fermée" in send(client, "courrier", "ajouter", **{
        "ligne.1": "1", "qui.1|tous": "on", "toujours.1": "on", "repondre.1": "accord", "defaut_repondre": "non"})
    got = client.portal.call(live.settings.canals).tables["courrier"]
    assert [(a.who, a.canal, a.prepare, a.reply) for a in got.lines] == [
        ((("tous",)), ("courrier",), False, "accord"), (("tous",), ("courrier",), False, "non")]
    # régler : une adresse d'abord (rien), puis tout le monde (préparer, seule) ; monter la seconde : l'ordre décide
    rows = {"ligne.1": "1", "qui.1|adresse:@shop.fr": "on", "toujours.1": "on", "repondre.1": "non",
            "ligne.2": "2", "qui.2|tous": "on", "toujours.2": "on", "preparer.2": "on", "repondre.2": "seule",
            "defaut_repondre": "accord"}
    assert "Ligne 2 montée" in send(client, "courrier", "monter:2", **rows)
    got = client.portal.call(live.settings.canals).tables["courrier"]
    assert got.lines == (CanalRule(who=("tous",), canal=("courrier",), prepare=True, reply="seule"),
                         CanalRule(who=("adresse:@shop.fr",), canal=("courrier",), reply="non"))
    assert got.default.reply == "accord"
    # rejournalisé : le courrier et Teams lisent les tableaux en paramètre
    for owner in ("email", "teams"):
        assert client.portal.call(live.kernel.mind.registry.params_of, owner, live.kernel.mind.root).canaux == \
            client.portal.call(live.settings.canals)
    # une ligne illisible : refusée, rien ne change
    refused = send(client, "courrier", **{"ligne.1": "1", "toujours.1": "on", "defaut_repondre": "accord"})
    assert "Ligne 1 : coche qui" in refused and client.portal.call(live.settings.canals).tables["courrier"] == got
    # elle seule : une ligne sans personne, par le seul canal « elle seule »
    assert "enregistrés" in send(client, "interne", **{"ligne.1": "1", "lecture.1": "seule", "action.1": "non",
                                                       "repondre.1": "seule", "garde.1": "perso",
                                                       "projets.1": "modification", "fichiers.1": "on"})
    alone = client.portal.call(live.settings.canals).tables["interne"].lines[0]
    assert (alone.who, alone.canal, alone.read, alone.act) == ((), ("interne",), "seule", "non")
    # revenir au minimum vital
    assert "minimum vital" in send(client, "courrier", "remettre")
    assert "courrier" not in client.portal.call(live.settings.canals).tables
    # sans jeton de formulaire : rien
    client.post(POST, data={"csrf": "faux", "cle": "interne", "faire": "remettre"})
    assert "interne" in client.portal.call(live.settings.canals).tables
