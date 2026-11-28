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
    "Vie intérieure › Émotions": ("/admin/vie/humeur", "Humeur"),
    "Vie intérieure › Pulsions": ("/admin/vie/needs", "Besoins"),
    "Vie intérieure › Ruminations": ("/admin/pensees/pensees", "Pensées"),
    "Vie intérieure › Chantiers": ("/admin/buts/vivants", "Buts"),
    "Vie intérieure › Rythme": ("/admin/vie/rythme", "Sommeil et rythme"),
    "Mémoire › Souvenirs": ("/admin/memoire/souvenirs", "Souvenirs"),
    "Mémoire › Connaissances": ("/admin/memoire/croyances", "Croyances"),
    "Mémoire › Messages": ("/admin/fil/conversations", "Par personne"),
    "Mémoire › Journaux et rêves": ("/admin/pensees/nuits", "Journal et rêves"),
    "Mémoire › Récit de soi": ("/admin/vie/soi", "Estime et récit"),
    "Mémoire › Thèmes et entités": ("/admin/memoire/souvenirs", "Souvenirs"),
    "Social › Identités": ("/admin/identites/annuaire", "Moyens de communication"),
    "Social › Revendications": ("/admin/approbations/identites", "Identités à confirmer"),
    "Social › Personnes": ("/admin/personnes/personnes", "Personnes"),
    "Social › Engagements": ("/admin/memoire/promesses", "Promesses"),
    "Social › Politique": ("/admin/identites/politique", "Règles de divulgation"),
    "Conscience › Observations": ("/admin/pensees/remarque", "Ce qu'elle remarque"),
    "Conscience › Décisions": ("/admin/decisions/selections", "Ses choix"),
    "Conscience › Planification": ("/admin/decisions/echeances", "Échéances"),
    "Conscience › Initiatives": ("/admin/decisions/initiatives", "Initiatives"),
    "Projets": ("/admin/projets", "Créer un projet"),
    "Projets › Actions en attente": ("/admin/approbations", "Tout ce qui attend"),
    "Modules › Email": ("/admin/courrier/reception", "Réception"),
    "Modules › Email (brouillons)": ("/admin/courrier/brouillons", "Ses brouillons"),
    "Modules › Email (envoyés)": ("/admin/courrier/envoyes", "Envoyés"),
    "Modules › Email (comptes)": ("/admin/courrier/comptes", "Ses boîtes"),
    "Modules › RSS": ("/admin/sens/flux", "Flux RSS"),
    "Modules › Caméra": ("/admin/sens/camera", "Caméra"),
    "Modules › Forge": ("/admin/apps", "Apps forgées"),
    "Réglages › IA (fournisseurs, modèles, rôles)": ("/admin/reglages/modeles", "Fournisseurs"),
    "Réglages › Personnalité": ("/admin/reglages/personnalite", "Personnage"),
    "Réglages › Tempérament": ("/admin/reglages/temperament", "Ce que pilote chaque curseur"),
    "Réglages › Réglages internes": ("/admin/reglages/parametres", "Les facultés"),
    "Réglages › Canaux": ("/admin/reglages/canaux", "Par où ça lui arrive"),
    "Réglages › Comptes": ("/admin/reglages/comptes", "Comptes"),
    "Système › Santé": ("/admin/systeme/sante", "Santé"),
    "Système › Quotas et cache": ("/admin/systeme/appels", "Appels et coûts"),
    "Système › Consolidation": ("/admin/memoire/consolidation", "Consolidation"),
    "Système › Journal de configuration": ("/admin/reglages/journal", "Journal des modifications"),
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
    fiche = client.get("/admin/fiche/person/user_1", follow_redirects=True)
    page = html.unescape(fiche.text)
    assert fiche.status_code == 200
    tabs = client.portal.call(lambda: [v.owner for v in live.kernel.registry.inspectors if v.subject == "person"])
    assert len(set(tabs)) >= 6  # au moins six propriétaires y contribuent
    for title in ("Synthèse", "Moyens de communication", "Lien", "Échanges", "Mémoire", "Affect", "Buts", "Pensées"):
        assert title in page, title
