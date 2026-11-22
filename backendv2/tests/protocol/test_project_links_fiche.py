"""Les liens de lecture d'un projet sur sa fiche (ADR 0257), à travers le vrai serveur : l'onglet Dépendances (ADR
0281, 0297), son schéma — « Il dépend de », lui au centre, « Dépendent de lui » —, « Ajouter une dépendance » (un
formulaire par projet qu'il peut lire, ce qui ne change pas posé) — et ce qu'ils disent, vides."""

from __future__ import annotations

from mika.runtime.operations import perform
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée


def _links(client, pid: int) -> str:
    page = drawn(client, f"/admin/fiche/project/{pid}?onglet=liens")  # ses liens ont leur onglet (ADR 0281)
    return page.split('data-tab="project/liens"', 1)[1]


def test_a_projects_fiche_shows_what_it_reads_and_who_reads_it(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    produit = _create(client, kernel, "Le produit", "Écrire le module")
    connaitre = _create(client, kernel, "Faire connaître", "Écrire un article")
    empty = _links(client, connaitre)
    assert "Il dépend de" in empty and "Dépendent de lui" in empty
    assert "Il ne lit aucun projet." in empty and "Aucun projet ne dépend de lui." in empty
    # « Ajouter une dépendance » : un formulaire par projet qu'il peut lire, nommé par son titre ; jamais lui-même
    adding = drawn(client, f"/admin/fiche/project/{connaitre}?onglet=liens&ajouter=1")
    forms = [f.split("</form>", 1)[0] for f in adding.split('action="/admin/action/projects.liens"')[1:]]
    assert len(forms) == 1 and f'name="lit_{produit}" value="on"' in forms[0]
    assert f'name="why_for" value="{produit}"' in forms[0] and "Le produit" in adding
    assert f'name="lit_{connaitre}"' not in adding
    got = client.portal.call(lambda: perform(kernel, "projects.liens", {
        "_champs": [f"lit_{produit}"], f"lit_{produit}": ["on"]}, by="user_1", subject=str(connaitre), nonce="l1"))
    assert got.ok, got
    reader = _links(client, connaitre)
    reads = reader.split('class="pj-center"', 1)[0]
    assert "Le produit" in reads and "son détail" in reads  # ce que le lien donne
    assert f"lien={produit}" in reads and "Il ne lit aucun projet." not in reader
    assert "Aucun projet ne dépend de lui." in reader
    # sur la fiche du projet lu : qui le lit ; lui-même ne lit rien, et ne peut pas lire son lecteur (une boucle)
    read = _links(client, produit)
    who = read.split("Dépendent de lui", 1)[1]
    assert "Faire connaître" in who and "Il ne lit aucun projet." in read
    assert "Ajouter une dépendance" not in read  # rien à lire de plus : pas de formulaire vide
