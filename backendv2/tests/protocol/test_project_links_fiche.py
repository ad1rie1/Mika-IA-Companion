"""Les liens de lecture d'un projet sur sa fiche (ADR 0257), à travers le vrai serveur : dans l'onglet « Liens »
(ADR 0281), « Ce qu'il lit » avec « Choisir ce qu'il lit » à côté (une case par projet qu'il peut lire), puis « Qui
le lit » — et ce qu'ils disent, vides."""

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
    assert "Il dépend de" in empty and "sans jamais y écrire" in empty
    assert "il ne lit aucun projet" in empty and "aucun projet ne le lit" in empty
    # « Choisir ce qu'il lit », à côté : une case par projet qu'il peut lire, nommé par son numéro et son titre
    chooser = empty.split('action="/admin/action/projects.liens"', 1)[1].split("</form>", 1)[0]
    assert "Choisir ce qu'il lit" in chooser and f'name="lit_{produit}"' in chooser
    assert f"n° {produit} — Le produit" in chooser and "Enregistrer ce qu'il lit" in chooser
    assert f'name="lit_{connaitre}"' not in chooser  # jamais lui-même
    got = client.portal.call(lambda: perform(kernel, "projects.liens", {
        "_champs": [f"lit_{produit}"], f"lit_{produit}": ["on"]}, by="user_1", subject=str(connaitre), nonce="l1"))
    assert got.ok, got
    reader = _links(client, connaitre)
    reads = reader.split("Dépendent de lui", 1)[0]
    assert f"n° {produit} — Le produit" in reads and "ses comptes rendus" in reads  # ce que le lien donne
    assert f'href="/admin/fiche/project/{produit}' in reads and "il ne lit aucun projet" not in reader
    assert "aucun projet ne le lit" in reader
    # sur la fiche du projet lu : « Qui le lit » ; lui-même ne lit rien, et ne peut pas lire son lecteur (une boucle)
    read = _links(client, produit)
    who = read.split("Dépendent de lui", 1)[1]
    assert f"n° {connaitre} — Faire connaître" in who and "il ne lit aucun projet" in read
    assert "projects.liens" not in read  # rien à cocher : pas de formulaire vide
