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

PAGE = "/inspecteur/outils/droits"


def test_the_rights_page_and_a_projects_access_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    created = client.portal.call(partial(live.kernel.mind.append, [opened(
        title="Le site", description="", authority=c.USER, mode=c.PERSONA, owner=None, address=None, about=(),
        level=0, source="operator")], emitter="projects", correlation="genese", origin=Origin.GENESIS))
    pid = created.seqs[-1]
    page = html_of(client.get(PAGE))
    for part in ("Par personne", "Toi, quand elle te répond", "Par ressource", "Le projet « Le site »",
                 "Ce qu'elle envoie à ta place", "Tes règles d'outils", "Ce que le code fixe"):
        assert part in page, part
    assert "le piloter : seule" in page and "ligne 1" in page  # jamais réglé : toi, tout, par sa ligne
    assert 'href="/inspecteur/outils/droits"' in html_of(client.get("/inspecteur"))  # dans le menu
    # un autre compte : il l'entend selon sa confidentialité, sans le piloter
    other = html_of(client.get(PAGE, params={"qui": "comptes"}))
    assert "le piloter : non" in other and "comportement par défaut" in other
    # l'onglet « Accès » du projet, dessiné, sa ligne d'avant réglage cochée comme elle vaut ; ajouter : une ligne
    # fermée, enregistrée (le navigateur envoie ce qui est coché, le test le dit)
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    assert "Accès au projet" in tab and "+ Ajouter un accès" in tab and "Jamais réglés" in tab
    assert 'name="qui.1|proprietaire" checked' in tab and 'name="qui.1|travail" checked' in tab
    shown = {"qui.1|proprietaire": "on", "qui.1|travail": "on", "toujours.1": "on", "voir.1": "on",
             "piloter.1": "seule", "lecture.1": "seule", "action.1": "seule", "tous.1": "on",
             "defaut_piloter": "non", "defaut_lecture": "non", "defaut_action": "non"}
    added = submit(client, tab, "projects.acces", faire="ajouter", **shown)
    assert added.status_code == 200 and "Ligne 2 ajoutée, fermée" in html_of(added)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (*c.UNSET, c.ProjectAccess(who=(OWNER,))) and view.default_access == c.CLOSED
    # retirer la première : reste la ligne fermée
    tab = html_of(client.get(f"/inspecteur/fiche/project/{pid}", params={"onglet": "acces"}))
    closed_row = {"qui.2|proprietaire": "on", "toujours.2": "on", "piloter.2": "non", "lecture.2": "non",
                  "action.2": "non", "tous.2": "on"}
    removed = submit(client, tab, "projects.acces", faire="retirer:1", **shown, **closed_row)
    assert "Ligne 1 retirée." in html_of(removed)
    view = next(v for v in live.kernel.mind.frame().get(c.LIVE) if v.id == pid)
    assert view.access == (c.ProjectAccess(who=(OWNER,)),)
    # la page le lit aussitôt : pour toi, plus rien — ce qui est fermé se compte, sans se lister
    after = html_of(client.get(PAGE))
    assert "le piloter : seule" not in after and "fermé ici" in after
