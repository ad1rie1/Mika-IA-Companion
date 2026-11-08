"""Les voyages d'une personne dans la console (ADR 0204 ; audit du 2026-11-05, C9-01) : à travers le vrai serveur, sur
une carte jouée en mémoire (``tests/fixtures/fake_maps.py``).

- la fiche d'une personne a un onglet « Voyages », seulement si elle en a : chaque voyage, son départ, comment on s'y
  déplace, ce qu'il évite, ses arrêts jour par jour (ce qu'elle y a ajouté, sous son nom), son GPX ;
- un opérateur l'y supprime (confirmé, audité) : la personne ne le retrouve plus (``/api/moi/voyages``) ; le dernier
  parti, l'onglet aussi ;
- le GPX se sert aux opérateurs seulement, et plus une fois le voyage supprimé ; son tracé use la borne des trajets
  de l'écran Carte, sur le compte de l'opérateur (429 au-delà).
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from mika.app.moi import OUTBOUND, ROUTES_BUSY
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import trips as c
from mika.kernel.events import Content
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_drawn_fiches import drawn, form_of
from tests.protocol.test_moi_carte import CARTE, LAC, VOYAGES, new_trip, plugged, stop
from tests.protocol.test_moi_mail import append, journal, login, second_person
from tests.protocol.test_web import world  # noqa: F401 — fixture partagée

ADRIEN = "user_1"
GPX = {"g": "http://www.topografix.com/GPX/1/1"}


def fiche(person: str, tab: str = "") -> str:
    return f"/inspecteur/fiche/person/{person}" + (f"?onglet={tab}" if tab else "")


def _trip(page: str, trip: str) -> str:
    """L'entrée d'un voyage dans l'onglet (jusqu'à la suivante)."""
    return page.split(f'id="voyage-{trip}"', 1)[1].split('<li id="voyage-', 1)[0]


def test_her_trips_are_on_her_fiche_and_an_operator_removes_one(world):  # noqa: F811
    client, live, maps = plugged(world)
    her = self_c.name_of(live.kernel.mind.frame().get(self_c.PERSONA))
    lea = second_person(client, live)
    login(client, "lea")
    alpes = new_trip(client, "Les Alpes", avoid=["peages", "ferries"])
    stop(client, alpes, "Annecy", 45.8992, 6.1294, kind="Ville")
    stop(client, alpes, "Talloires", 45.8406, 6.2128, day=2, note="Se baigner au lever du jour")
    append(client, live, [c.STOP_ADDED.draft(trip=alpes, person=lea, by=c.BY_HER, day=2,
                                             name=Content.of("Monastère royal de Brou", level=2),
                                             coords=Content.of("46.199000,5.240000", level=2),
                                             note=Content.of("ça vaut le détour", level=2))], emitter=c.OWNER)
    lyon = new_trip(client, "Week-end à Lyon", start="", mode="velo")
    login(client, "adrien")

    # une personne sans voyage n'a pas l'onglet ; elle, si
    assert "onglet=voyages" not in drawn(client, fiche(ADRIEN))
    assert f'href="{fiche(lea, "voyages")}"' in drawn(client, fiche(lea))
    page = drawn(client, fiche(lea, "voyages"))
    assert page.index(f'id="voyage-{lyon}"') < page.index(f'id="voyage-{alpes}"')  # le plus récemment changé d'abord
    trip = _trip(page, alpes)
    for said in ("Les Alpes", "en voiture", "péages, ferries", "sam. 3 avr. 2027", "2 jours", "3 arrêts",
                 f"préparé avec {her}", "Jour 1 · sam. 3 avr. 2027", "Jour 2 · dim. 4 avr. 2027", "Annecy", "Ville",
                 "45.899200,6.129400", "Se baigner au lever du jour", "Monastère royal de Brou", "ça vaut le détour",
                 f"/inspecteur/evenement/{alpes}"):
        assert said in trip, said
    assert trip.count(f"ajouté par {her}") == 1  # le sien seulement
    assert trip.index("Annecy") < trip.index("Talloires") < trip.index("Monastère royal de Brou")
    other = _trip(page, lyon)
    assert "à vélo" in other and "sans date" in other and "évite</span> rien" in other and "aucun arrêt" in other
    assert "/gpx" not in other and "Ses arrêts, jour par jour" not in other  # rien à suivre, rien à déplier
    # pas d'édition : le seul geste de la console sur un voyage est de le supprimer
    assert not re.search(r'action="/inspecteur/action/trips\.(?!supprimer")', page)
    # le repli (et ce que lit la console en MCP) : la vue du plugin, ses arrêts au détail, son « Supprimer »
    raw = client.get(fiche(lea, "voyages") + "&vue_pg1=table")
    assert raw.status_code == 200
    ConsoleHTML(raw.text).check()
    plain = html.unescape(raw.text)
    assert "Ses voyages" in plain and "Monastère royal de Brou" in plain and "Cette vue a échoué" not in plain
    assert 'class="now-page person-tab"' not in plain  # bien les blocs, pas le dessin
    assert form_of(plain, "trips.supprimer", having=alpes)["_sujet"] == [lea]
    assert not re.search(r'action="/inspecteur/action/trips\.(?!supprimer")', plain)

    # le GPX, servi par la console : ses arrêts dans l'ordre, et son tracé
    gpx = client.get(f"/inspecteur/voyages/{alpes}/gpx")
    assert f'href="/inspecteur/voyages/{alpes}/gpx"' in trip
    assert gpx.status_code == 200 and gpx.headers["content-type"].startswith("application/gpx+xml")
    assert gpx.headers["content-disposition"] == f'attachment; filename="voyage-{alpes}.gpx"'
    root = ET.fromstring(gpx.content)
    assert [w.findtext("g:name", namespaces=GPX) for w in root.findall("g:rte/g:rtept", GPX)] == \
        ["Annecy", "Talloires", "Monastère royal de Brou"]
    assert root.findtext("g:metadata/g:name", namespaces=GPX) == "Les Alpes" and root.findall("g:trk", GPX)

    # « Supprimer » : le formulaire de la console, sur la personne de la fiche, confirmé
    sent = form_of(page, "trips.supprimer", having=alpes)
    assert sent["trip"] == [alpes] and sent["_sujet"] == [lea]
    assert "Supprimer « Les Alpes » (3 arrêts) ? Léa Martin ne le retrouvera plus." in trip  # data-confirm
    done = client.post("/inspecteur/action/trips.supprimer", data=sent, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith(fiche(lea, "voyages"))
    after = drawn(client, done.headers["location"])
    assert "Voyage supprimé." in after and f'id="voyage-{alpes}"' not in after and f'id="voyage-{lyon}"' in after
    [removed] = journal(live, c.REMOVED)
    assert (removed.data.trip, removed.data.person, removed.data.by) == (alpes, lea, ADRIEN)
    audit = [e.data for e in journal(live, rt.OPERATED) if e.data.action == "trips.supprimer"]
    assert [(a.by, a.subject, a.outcome, a.seqs) for a in audit] == [(ADRIEN, lea, "done", (removed.seq,))]
    assert client.get(f"/inspecteur/voyages/{alpes}/gpx").status_code == 404

    # elle ne le retrouve plus
    login(client, "lea")
    assert [t["id"] for t in client.get(VOYAGES).json()["trips"]] == [lyon]
    assert client.get(f"{VOYAGES}/{alpes}").status_code == 404
    # la console reste aux opérateurs : son GPX aussi
    refused = client.get(f"/inspecteur/voyages/{lyon}/gpx", follow_redirects=False)
    assert refused.status_code == 303 and refused.headers["location"] == "/inspecteur/connexion"


def test_the_last_trip_removed_the_fiche_opens_on_its_overview(world):  # noqa: F811
    client, live, _ = plugged(world)
    lea = second_person(client, live)
    login(client, "lea")
    only = new_trip(client, "Les Alpes")
    login(client, "adrien")
    page = drawn(client, fiche(lea, "voyages"))
    sent = form_of(page, "trips.supprimer", having=only)
    assert sent["_retour"] == [fiche(lea)]  # l'onglet n'aura plus lieu d'être
    done = client.post("/inspecteur/action/trips.supprimer", data=sent, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith(fiche(lea) + "?flash=")
    after = drawn(client, done.headers["location"])
    assert "Voyage supprimé." in after and "onglet=voyages" not in after
    login(client, "lea")
    assert client.get(VOYAGES).json() == {"trips": []}


def test_the_gpx_of_the_console_counts_in_the_operator_s_carte_budget(world):  # noqa: F811
    """Le tracé d'un GPX tiré de la console part vers le serveur d'itinéraires public, qui est à tous : il use la borne
    des trajets de l'écran Carte (``OUTBOUND``), sur le compte de l'opérateur, et rien ne part au-delà (429, dit en
    mots : le lien n'est pas un téléchargement qui échouerait en silence). Ce qui ne demande pas de tracé ne compte
    pas ; la borne d'une autre personne reste à elle (audit du 2026-11-05, relecture de L06b)."""
    client, live, maps = plugged(world)
    lea = second_person(client, live)
    login(client, "lea")
    alpes = new_trip(client, "Les Alpes")
    stop(client, alpes, "Annecy", 45.8992, 6.1294)
    stop(client, alpes, "Talloires", 45.8406, 6.2128)
    lyon = new_trip(client, "Week-end à Lyon")
    stop(client, lyon, "Fourvière", 45.7623, 4.8228)
    login(client, "adrien")
    link = re.search(rf'<a [^>]*href="/inspecteur/voyages/{alpes}/gpx"[^>]*>', drawn(client, fiche(lea, "voyages")))
    assert link is not None and " download" not in link.group(0)

    def routed() -> int:
        return sum(1 for call in maps.calls if call[0] == "route")

    served = [client.get(f"/inspecteur/voyages/{alpes}/gpx").status_code for _ in range(OUTBOUND[0])]
    assert served == [200] * OUTBOUND[0] and routed() >= OUTBOUND[0]
    asked = routed()
    refused = client.get(f"/inspecteur/voyages/{alpes}/gpx")
    assert (refused.status_code, refused.text) == (429, ROUTES_BUSY)
    assert routed() == asked  # rien n'est parti
    # la même borne que son écran Carte : celle de son compte
    assert client.get(CARTE + f"/itineraire?points={LAC}").status_code == 429
    assert routed() == asked
    # un seul arrêt, pas de tracé à demander : rien ne compte, le GPX reste servi
    assert client.get(f"/inspecteur/voyages/{lyon}/gpx").status_code == 200
    # la borne est par compte : celle de Léa reste entière
    login(client, "lea")
    assert client.get(f"{VOYAGES}/{alpes}/gpx").status_code == 200
    assert routed() > asked
