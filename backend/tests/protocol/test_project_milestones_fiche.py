"""Les jalons d'un objectif sur la fiche d'un projet (ADR 0273, 0297), à travers le vrai serveur : la ligne d'un
objectif dit où il en est, ses jalons se lisent en étapes avec leur vérification et ce qu'elle en a dit, un point
d'arrêt qui attend se tranche sur place, « Ajouter un jalon » ouvre son formulaire dans le contenu ; la liste de
passage d'une mission se lit dans son détail et se règle par « Modifier la mission »."""

from __future__ import annotations

import re

from mika.contracts import projects as c
from mika.faculties.projects import milestones
from mika.faculties.projects.faculty import milestone_at, objective_at
from mika.runtime.operations import perform
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée
from tests.unit.test_projects import row_form


def _objective(client, pid: int, n: int) -> str:
    page = drawn(client, f"/admin/fiche/project/{pid}?onglet=objectifs&objectif={n}")
    assert 'data-tab="project/objectifs"' in page
    return page.split('data-tab="project/objectifs"', 1)[1]


def _row(page: str) -> str:
    """La ligne de l'objectif choisi, dans la liste."""
    return re.search(r'<a class="pj-orow[^"]*" href="[^"]*" aria-current="true".*?</a>', page, re.S).group(0)


def _marks(page: str) -> str:
    return page.split('id="obj-jalons"', 1)[1].split("</section>", 1)[0]


def test_an_objective_shows_its_milestones_and_a_breakpoint_is_settled_on_its_line(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Le site", "Refaire la page Tarifs")

    def act(name: str, nonce: str, fixed: dict[str, str], **fields: str):
        """Une action de la ligne d'un objectif, telle que la fiche l'envoie (ses champs cachés à part)."""
        got = client.portal.call(lambda: perform(kernel, f"projects.{name}", row_form(fixed, **fields), by="user_1",
                                                 subject=str(pid), nonce=nonce))
        assert got.ok, got

    act("jalon_ajouter", "j1", {"objective": "1"}, text="La page est relue", check="owner")
    act("jalon_ajouter", "j2", {"objective": "1"}, text="Les tests passent", check="command", command="pytest -q")
    page = _objective(client, pid, 1)
    marks = _marks(page)
    assert '<span class="num">0/2</span>' in _row(page)
    assert "La page est relue" in marks and "Vérifié par un point d'arrêt" in marks and "à faire" in marks
    assert "Les tests passent" in marks and "Vérifié par une commande · <code>pytest -q</code>" in marks
    # « Ajouter un jalon » ouvre son formulaire dans le contenu ; rien à trancher encore
    assert 'href="#obj-jalon"' in marks and 'action="/admin/action/projects.jalon_ajouter"' in page
    assert "projects.jalon_trancher" not in page
    # elle le dit prêt : la ligne dit qu'il attend, avec comment elle l'a rempli, et se tranche sur place
    p = kernel.mind.frame().state("projects").projects[pid]
    o = objective_at(p, 1)
    append(client, kernel, [milestones.changing(p, o.id, milestone_at(o, 1), level=1, inherited=(), ready=True,
                                                how="Voir tarifs.html.", commit="c0ffee0123456789")], "projects")
    page = _objective(client, pid, 1)
    marks = _marks(page)
    assert 'class="pj-orow atoi"' in page and "prêt · à valider" in marks
    assert "Voir tarifs.html." in marks and "commit <code>c0ffee0</code>" in marks
    assert "Valider le jalon" in marks and "Refuser le point d'arrêt n° 1" in marks and "projects.jalon_trancher" in marks
    act("jalon_trancher", "t1", {"objective": "1", "milestone": "1"}, verdict="validate")
    page = _objective(client, pid, 1)
    assert '<span class="num">1/2</span>' in _row(page) and "atteint" in _marks(page)
    assert "projects.jalon_trancher" not in page
    # une mission : sa liste de passage se règle par « Modifier la mission », et se lit dans son détail
    constant = next(x for x in p.objectives if x.kind == c.CONSTANT)
    act("objectif_modifier", "c1", {"objective": str(constant.id)}, text="Garder les tests verts", kind="constant",
        cadence_hours="24", routine="Lancer les tests\nNoter ce qui casse")
    page = _objective(client, pid, constant.id)
    assert "À chaque passage" in page and "Lancer les tests" in page
    assert 'name="routine"' in page and "projects.jalon_ajouter" not in page
