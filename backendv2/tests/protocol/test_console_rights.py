"""Qui peut quoi dans la console (ADR 0133), le parcours d'un opérateur : la page « Droits » lit chaque type de règles
par personne et par ressource ; l'onglet « Accès » d'un projet se dessine, et son tableau s'enregistre d'un envoi."""

from __future__ import annotations

from functools import partial

from mika.contracts import projects as c
from mika.faculties.projects.tools import opened
from mika.kernel.events import Origin
from mika.vocab.access import OWNER
from tests.protocol.test_console_mcp import html_of, submit
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

PAGE = "/inspecteur/reglages/droits"


def test_the_rights_page_and_a_projects_access_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    created = client.portal.call(partial(live.kernel.mind.append, [opened(
        title="Le site", description="", authority=c.USER, mode=c.PERSONA, owner=None, address=None, about=(),
        level=0, source="operator")], emitter="projects", correlation="genese", origin=Origin.GENESIS))
    pid = created.seqs[-1]
    page = html_of(client.get(PAGE))
    for part in ("Qui peut quoi", "Vie interne", "Apps de la Forge", "Services MCP", "Projets", "Canaux",
                 "Le projet « Le site »", "détail des accès", "<code>memory_search</code>", "Ce que le code fixe"):
        assert part in page, part
    assert "Droits exacts" not in page  # sans qui ni canal choisis, pas de droits exacts
    home = html_of(client.get("/inspecteur"))
    assert 'href="/inspecteur/reglages/droits"' in home and "/inspecteur/outils/droits" not in home  # menu Réglages
    # les droits exacts : toi par le chat web — jamais réglé : toi, tout, par sa ligne
    mine = html_of(client.get(PAGE, params={"qui": "toi", "canal": "web:prive"}))
    assert "Droits exacts" in mine and "piloter projet : modification" in mine and "ligne 1" in mine
    assert "memory_search" in mine and "lit : seule" in mine
    # un autre compte : il l'entend selon sa confidentialité, en lecture seule ; dans un salon, pas plus
    other = html_of(client.get(PAGE, params={"qui": "compte", "canal": "web:prive"}))
    assert "piloter projet : lecture seule" in other and "comportement par défaut" in other
    assert "piloter projet : lecture seule" in html_of(client.get(PAGE, params={"qui": "compte", "canal": "web:salon"}))
    # le détail des accès d'un projet : son tableau, « Modifier » vers sa fiche, « Retour »
    shown = html_of(client.get(PAGE, params={"detail": f"project:{pid}"}))
    assert "Le projet « Le site »" in shown and "Comportement par défaut" in shown and "← Retour" in shown
    assert f'href="/inspecteur/fiche/project/{pid}?onglet=acces"' in shown and "Modifier" in shown
    # l'onglet « Accès » du projet, dessiné, sa ligne d'avant réglage cochée comme elle vaut ; ajouter : une ligne
    # fermée, enregistrée (le navigateur envoie ce qui est coché, le test le dit)
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    assert "Accès au projet" in tab and "+ Ajouter un accès" in tab and "Jamais réglés" in tab
    assert 'name="qui.1|proprietaire" checked' in tab and 'name="canal.2|interne" checked' in tab
    assert 'name="fichiers.1" checked' in tab and "Par où" in tab
    shown = {"qui.1|proprietaire": "on", "toujours.1": "on", "voir.1": "on", "piloter.1": "modification",
             "fichiers.1": "on", "lecture.1": "seule", "action.1": "seule", "tous.1": "on",
             "canal.2|interne": "on", "voir.2": "on", "piloter.2": "modification", "fichiers.2": "on",
             "lecture.2": "seule", "action.2": "seule", "tous.2": "on",
             "defaut_piloter": "non", "defaut_lecture": "non", "defaut_action": "non"}
    added = submit(client, tab, "projects.acces", faire="ajouter", **shown)
    assert added.status_code == 200 and "Ligne 3 ajoutée, fermée" in html_of(added)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (*c.UNSET, c.ProjectAccess(who=(OWNER,))) and view.default_access == c.CLOSED
    # retirer la première : restent elle seule, et la ligne fermée
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    closed_row = {"qui.3|proprietaire": "on", "toujours.3": "on", "piloter.3": "non", "lecture.3": "non",
                  "action.3": "non", "tous.3": "on"}
    removed = submit(client, tab, "projects.acces", faire="retirer:1", **shown, **closed_row)
    assert "Ligne 1 retirée." in html_of(removed)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (c.UNSET[1], c.ProjectAccess(who=(OWNER,)))
    # la page le lit aussitôt : pour toi, plus rien (la ligne fermée) ; elle seule garde tout — chaque case le dit,
    # avec les deux lignes qui en décident (la ressource, le canal)
    after = html_of(client.get(PAGE, params={"qui": "toi", "canal": "web:prive"}))
    assert "le voir : non · piloter projet : aucun pilotage · ses fichiers : non — ligne 2" in after
    alone = html_of(client.get(PAGE, params={"qui": "seule", "canal": "interne"}))
    assert "le voir : oui · piloter projet : modification · ses fichiers : oui — ligne 1" in alone
