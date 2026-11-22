"""Ce qu'elle sait d'un contact dans la console (ADR 0298, lot 6), à travers le vrai serveur : la vue d'ensemble de sa
fiche montre les faits qu'elle a tirés de ses derniers messages (d'où ils viennent, leur confiance), l'onglet « Ce
qu'elle en sait » les oublie un à un (un geste audité), l'annuaire dit l'état des portraits face à leurs plafonds, et
leurs réglages sont parmi ceux des plugins."""

from __future__ import annotations

from mika.contracts import runtime as rt
from mika.ports.contacts import TEAMS, Note, Portrait
from tests.protocol.test_console_annuaire import ANNUAIRE, fiche, seed
from tests.protocol.test_console_files import _events
from tests.protocol.test_drawn_fiches import drawn, form_of
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée


def taught(client, live) -> dict[str, int]:
    ids = seed(client, live)
    store = live.kernel.ports["contacts"]
    now = live.kernel.mind.frame().now
    client.portal.call(lambda: store.portrayed(Portrait(ids["gilles"], TEAMS, "equipe", now, now, 12, call_id="r#1"), [
        Note(0, ids["gilles"], TEAMS, "equipe", "Il pilote la migration des centrales vers le VPN.", "role", 0.85,
             "m1", "dans le groupe « Déploiement PDV »", now - 3_600_000_000, now, "r#1"),
        Note(0, ids["gilles"], TEAMS, "equipe", "Il préfère qu'on l'appelle en urgence.", "expectation", 0.6, "m2",
             "en tête-à-tête", now, now, "r#1")]))
    return ids


def test_the_sheet_shows_what_she_understood_and_each_fact_is_forgotten_from_its_tab(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ids = taught(client, live)
    overview = drawn(client, fiche(ids["gilles"]))
    assert "L'idée qu'elle s'en fait" in overview and "Il pilote la migration des centrales vers le VPN." in overview
    assert "lu dans Teams · Équipe · dans le groupe « Déploiement PDV »" in overview and "85 %" in overview
    assert 'class="now-bar confidence"' in overview and f'{fiche(ids["gilles"], "savoir")}#fait-' in overview
    tab = drawn(client, fiche(ids["gilles"], "savoir"))
    assert "Il préfère qu'on l'appelle en urgence." in tab and "Dernier portrait" in tab and "12 messages" in tab
    store = live.kernel.ports["contacts"]
    gone = next(n for n in store.notes(ids["gilles"]) if "urgence" in n.text)
    form = form_of(tab, "contacts.oublier_fait", having=str(gone.id))
    assert form["_sujet"] == [f"contact:{ids['gilles']}"]
    done = client.post("/admin/action/contacts.oublier_fait", data=form, follow_redirects=False)
    assert done.status_code == 303
    assert [n.text for n in store.notes(ids["gilles"])] == ["Il pilote la migration des centrales vers le VPN."]
    assert [(e.data.action, e.data.outcome) for e in _events(client, live, rt.OPERATED)] == [
        ("contacts.oublier_fait", "done")]
    assert "urgence" not in drawn(client, fiche(ids["gilles"], "savoir"))
    # une organisation n'a pas de portrait : l'onglet n'est pas dans sa barre
    assert f'href="{fiche(ids["org"], "savoir")}"' not in drawn(client, fiche(ids["org"]))


def test_the_directory_says_where_portraits_stand_and_where_to_set_them(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    taught(client, live)
    page = drawn(client, ANNUAIRE)
    assert "Portraits : 1 contact sur 20 et 1 appel sur 30 en vingt-quatre heures" in page
    assert 'href="/admin/reglages/comportement-contacts"' in page
    settings = drawn(client, "/admin/reglages/comportement-contacts")
    assert "Relire tout l'historique" in settings and "Contacts par jour" in settings
