"""Ce qui déclenche un objectif, sur la fiche d'un projet (ADR 0265), à travers le vrai serveur : la ligne d'un
constant dit ce qui le déclenche, « Ajouter un objectif » et « Modifier l'objectif » ont « Déclenché par » (un
déclencheur par ligne) et « Sur événement seulement », et le formulaire de modification repart de ce qui est posé."""

from __future__ import annotations

import html
import re

from mika.runtime.operations import perform
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée


def _objectives(client, pid: int) -> str:
    # son ancienne adresse mène à « Où il en est », ouvert sur « Missions et objectifs » (ADR 0281)
    page = drawn(client, f"/admin/fiche/project/{pid}?onglet=objectifs")
    assert 'data-tab="project/objectifs"' in page
    return html.unescape(page).split('data-tab="project/objectifs"', 1)[1]


def _field(form: str, name: str) -> str:
    """Le champ ``name`` d'un formulaire : sa balise et ce qu'elle contient."""
    found = re.search(rf'<(textarea|input)[^>]*name="{name}"[^>]*>(?:(.*?)</textarea>)?', form, re.S)
    assert found is not None, name
    return found.group(0)


def test_an_objectives_line_says_what_fires_it_and_its_forms_set_it(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    produit = _create(client, kernel, "Le produit", "Écrire le module")
    site = _create(client, kernel, "Le site", "Écrire la page")
    page = _objectives(client, site)
    add = page.split('action="/admin/action/projects.objectif_ajouter"', 1)[1].split("</form>", 1)[0]
    assert "Déclenché par" in add and "Sur événement seulement" in add and "project:<n>:commit" in add
    assert 'name="on"' in add and 'name="only_on_event"' in add
    for nonce, fields in (("l1", {f"lit_{produit}": ["on"], "_champs": [f"lit_{produit}"]}),):
        got = client.portal.call(lambda f=fields, n=nonce: perform(kernel, "projects.liens", f, by="user_1",
                                                                  subject=str(site), nonce=n))
        assert got.ok, got
    got = client.portal.call(lambda: perform(kernel, "projects.objectif_ajouter", {
        "_champs": ["text", "kind", "cadence_hours", "on", "only_on_event"], "text": ["Relire la cohérence"],
        "kind": ["constant"], "cadence_hours": ["0"], "on": [f"project:{produit}:commit\nwake:deploy"],
        "only_on_event": ["on"]}, by="user_1", subject=str(site), nonce="o1"))
    assert got.ok, got
    page = _objectives(client, site)
    entry = page.split("Relire la cohérence", 1)[1].split("</li>", 1)[0]
    assert "sans cadence" in entry  # son rythme : il ne passe que sur événement
    assert f"déclenché par la base du projet n° {produit} qui avance, le réveil par API « deploy »" in entry
    # « Modifier l'objectif » repart de ce qui est posé : un déclencheur par ligne, la case cochée
    edit = entry.split('action="/admin/action/projects.objectif_modifier"', 1)[1].split("</form>", 1)[0]
    on = _field(edit, "on")
    assert f"project:{produit}:commit\nwake:deploy" in on, on
    assert "checked" in _field(edit, "only_on_event")
