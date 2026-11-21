"""Le registre d'un projet sur sa fiche (ADR 0268), à travers le vrai serveur : les onglets « Tickets » et « Suivi »
se dessinent, un ticket ouvert montre son fil et ses gestes, une liste se filtre par statut, et chaque formulaire
part de l'élément qu'il vise (sa liste, sa clé : des valeurs fixes)."""

from __future__ import annotations

import html

from mika.runtime.operations import perform
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée


def _tab(client, pid: int, name: str, more: str = "") -> str:
    page = drawn(client, f"/admin/fiche/project/{pid}?onglet={name}{more}")
    assert f'data-tab="project/{name}"' in page
    return html.unescape(page)


def test_the_fiche_draws_the_tickets_and_the_follow_up_lists_with_their_forms(world):  # noqa: F811
    client, live, _ = world
    kernel = _life(client, live)
    pid = _create(client, kernel, "Le site", "Écrire la page")

    def do(action: str, nonce: str, fixed: dict[str, str] | None = None, **values: str):
        posted = {"_champs": list(values), **{k: [v] for k, v in values.items()}}
        if fixed:
            posted |= {"_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}
        got = client.portal.call(lambda: perform(kernel, f"projects.{action}", posted, by="user_1",
                                                 subject=str(pid), nonce=nonce))
        assert got.ok, got

    empty = _tab(client, pid, "suivi")
    assert "pas encore de liste de suivi" in empty and 'action="/admin/action/projects.liste_regler"' in empty
    do("ticket_ouvrir", "t1", title="Le pied de page est vide", kind="bug", priority="high")
    do("element_noter", "n1", {"list_name": "tickets", "item": "1"}, text="À voir avec le design.")
    do("liste_regler", "l1", name="articles", title="Articles à relire", open="à relire", closed="publié")
    do("element_ajouter", "e1", list_name="articles", title="La page Tarifs", key="tarifs")
    do("element_ajouter", "e2", list_name="articles", title="La page Contact", key="contact", status="publié")

    tickets = _tab(client, pid, "tickets")
    assert "Le pied de page est vide" in tickets and "non lu" in tickets and "défaut" in tickets
    assert 'action="/admin/action/projects.ticket_ouvrir"' in tickets
    opened = _tab(client, pid, "tickets", "&element=%231")
    assert "Son fil" in opened and "À voir avec le design." in opened
    settle = opened.split('action="/admin/action/projects.ticket_trancher"', 1)[1].split("</form>", 1)[0]
    assert 'name="_fixes" value="item"' in settle and 'name="item" value="#1"' in settle  # le ticket qu'il vise

    suivi = _tab(client, pid, "suivi")
    assert "Articles à relire" in suivi and "La page Tarifs" in suivi and "La page Contact" in suivi
    published = _tab(client, pid, "suivi", "&liste=articles&statut=publié")
    assert "La page Contact" in published and "La page Tarifs" not in published
    one = _tab(client, pid, "suivi", "&liste=articles&element=tarifs")
    status = one.split('action="/admin/action/projects.element_statut"', 1)[1].split("</form>", 1)[0]
    assert 'name="list_name" value="articles"' in status and 'name="item" value="tarifs"' in status
    regulate = one.split('action="/admin/action/projects.liste_regler"', 1)[1].split("</form>", 1)[0]
    assert "à relire" in regulate and "publié" in regulate  # régler une liste repart de ce qu'elle est
