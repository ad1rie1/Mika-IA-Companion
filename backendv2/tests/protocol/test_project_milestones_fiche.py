"""Les jalons d'un objectif sur la fiche d'un projet (ADR 0273), à travers le vrai serveur : la ligne d'un objectif
dit où il en est, ses jalons se lisent un par ligne avec leur vérification et ce qu'elle en a dit, un point d'arrêt
qui attend se tranche sur place, « Ajouter un jalon » est à côté de « Modifier l'objectif » — qui reste le premier
panneau de la ligne et règle la liste de passage d'un constant."""

from __future__ import annotations

from mika.contracts import projects as c
from mika.faculties.projects import milestones
from mika.faculties.projects.faculty import milestone_at, objective_at
from mika.runtime.operations import perform
from tests.protocol.test_console_workflows import append
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée
from tests.unit.test_projects import row_form


def _objectives(client, pid: int) -> str:
    page = drawn(client, f"/admin/fiche/project/{pid}?onglet=objectifs")
    assert 'data-tab="project/objectifs"' in page
    return page


def _entry(page: str, n: int) -> str:
    return page.split(f"Objectif n° {n} : ", 1)[1].split("</li>", 1)[0]


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
    entry = _entry(_objectives(client, pid), 1)
    assert "jalons 0/2" in entry
    assert "Jalon n° 1 · à faire" in entry and "La page est relue — vérifié par toi (un point d'arrêt)" in entry
    assert "Les tests passent — vérifié par la commande : pytest -q" in entry
    # « Modifier l'objectif » reste le premier panneau ; « Ajouter un jalon » vient après, rien à trancher encore
    assert entry.index("projects.objectif_modifier") < entry.index("projects.jalon_ajouter")
    assert "projects.jalon_trancher" not in entry
    # elle le dit prêt : la ligne dit qu'il t'attend, avec comment elle l'a rempli, et se tranche sur place
    p = kernel.mind.frame().state("projects").projects[pid]
    o = objective_at(p, 1)
    append(client, kernel, [milestones.changing(p, o.id, milestone_at(o, 1), level=1, inherited=(), ready=True,
                                                how="Voir tarifs.html.", commit="c0ffee0123456789")], "projects")
    entry = _entry(_objectives(client, pid), 1)
    assert "un point d'arrêt t'attend" in entry and "Jalon n° 1 · t'attend" in entry
    assert "Voir tarifs.html." in entry and "commit c0ffee012345" in entry
    assert "Valider ou refuser le point d'arrêt n° 1" in entry and "projects.jalon_trancher" in entry
    act("jalon_trancher", "t1", {"objective": "1", "milestone": "1"}, verdict="validate")
    entry = _entry(_objectives(client, pid), 1)
    assert "jalons 1/2" in entry and "Jalon n° 1 · atteint" in entry and "projects.jalon_trancher" not in entry
    # un constant : sa liste de passage se règle par « Modifier l'objectif », et se lit sur sa ligne
    constant = next(x for x in p.objectives if x.kind == c.CONSTANT)
    act("objectif_modifier", "c1", {"objective": str(constant.id)}, text="Garder les tests verts", kind="constant",
        cadence_hours="24", routine="Lancer les tests\nNoter ce qui casse")
    entry = _entry(_objectives(client, pid), constant.id)
    assert "À chaque passage" in entry and "Lancer les tests" in entry
    assert 'name="routine"' in entry and "projects.jalon_ajouter" not in entry
