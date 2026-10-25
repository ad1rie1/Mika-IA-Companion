"""Chaque chose qu'un opérateur cherche a sa place dans la console.

La liste est la correspondance du plan de la console. Chaque adresse doit
s'ouvrir sans échec et dire ce qu'elle montre ; une destination qui disparaît
fait tomber la ligne qui la cherchait. Ce qu'elle ne tient pas (thèmes et
entités : elle n'en extrait pas) renvoie à la mémoire disponible.
"""

from __future__ import annotations

import html

import pytest

from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

#: ce qu'on cherche → (adresse, un mot que la page doit contenir)
PARITY: dict[str, tuple[str, str]] = {
    "Vie intérieure › Émotions": ("/inspecteur/vie/humeur", "Humeur"),
    "Vie intérieure › Pulsions": ("/inspecteur/vie/needs", "Besoins"),
    "Vie intérieure › Ruminations": ("/inspecteur/pensees/pensees", "Pensées"),
    "Vie intérieure › Chantiers": ("/inspecteur/buts/vivants", "Buts"),
    "Vie intérieure › Rythme": ("/inspecteur/vie/rythme", "Sommeil et rythme"),
    "Mémoire › Souvenirs": ("/inspecteur/memoire/souvenirs", "Souvenirs"),
    "Mémoire › Connaissances": ("/inspecteur/memoire/croyances", "Croyances"),
    "Mémoire › Messages": ("/inspecteur/fil/messages", "Fil"),
    "Mémoire › Journaux et rêves": ("/inspecteur/pensees/nuits", "Journal et rêves"),
    "Mémoire › Récit de soi": ("/inspecteur/vie/soi", "Estime et récit"),
    "Mémoire › Thèmes et entités": ("/inspecteur/memoire/souvenirs", "Souvenirs"),
    "Social › Identités": ("/inspecteur/identites/annuaire", "Moyens de communication"),
    "Social › Revendications": ("/inspecteur/identites/revendications", "Identités à confirmer"),
    "Social › Personnes": ("/inspecteur/personnes/personnes", "Personnes"),
    "Social › Engagements": ("/inspecteur/memoire/promesses", "Promesses"),
    "Social › Politique": ("/inspecteur/identites/politique", "Règles de divulgation"),
    "Conscience › Observations": ("/inspecteur/pensees/remarque", "Ce qu'elle remarque"),
    "Conscience › Décisions": ("/inspecteur/decisions/selections", "Ses choix"),
    "Conscience › Planification": ("/inspecteur/decisions/echeances", "Échéances"),
    "Conscience › Initiatives": ("/inspecteur/decisions/initiatives", "Initiatives"),
    "Projets": ("/inspecteur/projets", "Créer un projet"),
    "Projets › Actions en attente": ("/inspecteur/approbations", "Actions à autoriser"),
    "Modules › Email": ("/inspecteur/courrier/reception", "Réception"),
    "Modules › Email (brouillons)": ("/inspecteur/courrier/brouillons", "Brouillons"),
    "Modules › Email (envoyés)": ("/inspecteur/courrier/envoyes", "Envoyés"),
    "Modules › Email (contacts)": ("/inspecteur/courrier/contacts", "Contacts"),
    "Modules › Email (comptes)": ("/inspecteur/courrier/comptes", "Boîtes aux lettres"),
    "Modules › RSS": ("/inspecteur/sens/flux", "Flux RSS"),
    "Modules › Caméra": ("/inspecteur/sens/camera", "Caméra"),
    "Modules › Forge": ("/inspecteur/apps", "Apps forgées"),
    "Réglages › IA (fournisseurs, modèles, rôles)": ("/inspecteur/reglages/modeles", "Fournisseurs"),
    "Réglages › Personnalité": ("/inspecteur/reglages/personnalite", "Personnage"),
    "Réglages › Tempérament": ("/inspecteur/reglages/temperament", "Ce que pilote chaque curseur"),
    "Réglages › Réglages internes": ("/inspecteur/reglages/parametres", "Les facultés"),
    "Réglages › Canaux": ("/inspecteur/reglages/canaux", "Par où ça lui arrive"),
    "Réglages › Comptes": ("/inspecteur/reglages/comptes", "Comptes"),
    "Système › Santé": ("/inspecteur/systeme/sante", "Santé"),
    "Système › Quotas et cache": ("/inspecteur/systeme/appels", "Appels et coûts"),
    "Système › Consolidation": ("/inspecteur/memoire/consolidation", "Consolidation"),
    "Système › Journal de configuration": ("/inspecteur/reglages/journal", "Journal des modifications"),
}


@pytest.fixture
def lived(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "salut, moi c'est Adrien", "client_msg_id": "p1"})
        recv_until(ws, "speech")
    return client, live


@pytest.mark.parametrize("screen", sorted(PARITY))
def test_every_screen_has_its_place(lived, screen):
    client, _ = lived
    url, word = PARITY[screen]
    r = client.get(url, follow_redirects=True)
    page = html.unescape(r.text)
    assert r.status_code == 200, (screen, url, r.status_code)
    assert "Cette vue a échoué" not in page, (screen, url)
    assert word in page, (screen, url, word)


def test_the_person_fiche_gathers_everything(lived):
    """Une personne se lit sur une seule fiche, qui réunit
    identité, lien, fil, mémoire, affect, buts, pensées — sans que la console
    nomme une seule faculté."""
    client, live = lived
    person = client.portal.call(lambda: sorted(live.kernel.registry.subjects))
    assert {"person", "handle", "goal", "mail", "app"} <= set(person)
    fiche = client.get("/inspecteur/fiche/person/user_1", follow_redirects=True)
    page = html.unescape(fiche.text)
    assert fiche.status_code == 200
    tabs = client.portal.call(lambda: [v.owner for v in live.kernel.registry.inspectors if v.subject == "person"])
    assert len(set(tabs)) >= 6  # au moins six propriétaires y contribuent
    for title in ("Synthèse", "Moyens de communication", "Lien", "Échanges", "Mémoire", "Affect", "Buts", "Pensées"):
        assert title in page, title
