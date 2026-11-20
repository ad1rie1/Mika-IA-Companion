"""Ses outils sur les fiches et les événements (ADR 0259), par leurs intentions.

- une liste se filtre et se range comme l'écran Carte, et chaque ligne dit ce qu'on sait du lieu (sa note Google, son
  nombre d'avis, son prix, sa cuisine, s'il est ouvert) ;
- ``place_read`` lit la fiche d'un lieu (un identifiant trouvé, « ici », un nom) ou d'un événement (« e:… ») ; tout
  texte venu du dehors y est inerte, borné, sous la ligne « données » — un avis qui donne des ordres reste un avis ;
- son regard ne garde que le lieu ou l'événement : jamais le texte d'un avis, d'un résumé, d'une description ;
- ``events_search`` cherche par période (« ce week-end », « samedi », des dates), par endroit, par thème ;
- jamais en salon, ni dans une initiative, ni à qui n'a pas de compte ; « ici » sous les droits de ``location_where``.
"""

from __future__ import annotations

import json
from datetime import date
from typing import get_args

from mika.app.composition import policies
from mika.app.mindport import KernelPort
from mika.contracts import location as location_c
from mika.contracts import trips as c
from mika.faculties.identity import audience_for
from mika.plugins.trips import tools as trips_tools
from mika.ports.maps import FEATURES, SORTS, THEMES
from mika.runtime.effects import with_content
from mika.runtime.pipeline import EpisodeRequest
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from tests.fixtures.fake_maps import CIBOULETTE, CONCERT, FETE, PLACES, TARTINE, FakeMaps
from tests.unit.test_shares import call, journal
from tests.unit.test_trips import ADRIEN, BEA, live

RATED = (*PLACES, CIBOULETTE, TARTINE)


def maps() -> FakeMaps:
    return FakeMaps(places=RATED)


def everything(kernel) -> str:
    """Tout le journal, ses contenus lus : ce qu'on y trouverait d'un avis."""
    mind = kernel.mind
    return "\n".join(with_content(mind, mind.decode(e)).data.model_dump_json() for e in mind.store.read())


def test_her_tools_speak_the_filters_sorts_and_themes_of_the_port():
    assert get_args(trips_tools.Feature) == FEATURES and get_args(trips_tools.Sort) == SORTS
    assert get_args(trips_tools.Theme) == tuple(k for k, _ in THEMES)


def test_a_period_in_words_is_a_span_of_days():
    wednesday, saturday, sunday = date(2026, 11, 18), date(2026, 11, 21), date(2026, 11, 22)
    assert trips_tools.period("ce_weekend", wednesday) == (saturday, sunday)
    assert trips_tools.period("ce_weekend", saturday) == (saturday, sunday)
    assert trips_tools.period("ce_weekend", sunday) == (sunday, sunday)  # commencé : ce qu'il en reste
    assert trips_tools.period("samedi", wednesday) == (saturday, saturday)
    assert trips_tools.period("mercredi", wednesday) == (wednesday, wednesday)  # aujourd'hui compris
    assert trips_tools.period("demain", wednesday) == (date(2026, 11, 19),) * 2
    assert trips_tools.period("cette_semaine", wednesday) == (wednesday, sunday)
    assert trips_tools.period("semaine_prochaine", wednesday) == (date(2026, 11, 23), date(2026, 11, 29))


def test_she_filters_a_list_and_each_line_says_its_rating_price_cuisine_and_hours(tmp_path):
    fake = maps()

    async def scenario(kernel, deliveries):
        got = await call(kernel, "places_search", ADRIEN, category="manger", near="45.8992,6.1294", radius_km=2,
                         open_now=True, features=["terrasse"], cuisine="française", min_rating=4.0, sort="rating")
        bare = await call(kernel, "places_search", ADRIEN, text="Tartine")
        return got, bare, journal(kernel, c.LOOKED)

    got, bare, looks = live(tmp_path, scenario, maps=fake)
    [line] = [x for x in got.content.splitlines() if x.startswith("l7 ")]
    assert line.startswith("l7 · La Ciboulette (Restaurant, Annecy), à ")
    assert line.endswith(" · note Google 4,6/5 (1 203 avis) · €€€ · cuisine Française, régionale · ouvert, ferme à "
                         "22:30")
    searched = [x for x in fake.calls if x[0] == "search"][0]
    assert searched[6] == {"open_now": True, "features": frozenset({"terrasse"}), "cuisine": "française",
                           "min_rating": 4.0, "sort": "rating"}
    [kept] = json.loads(looks[0].data.found.text)
    assert kept["rating"] == 4.6 and "open_text" not in kept and "open_state" not in kept  # jamais s'il était ouvert
    [plain] = [x for x in bare.content.splitlines() if x.startswith("l8 ")]
    assert plain == "l8 · La Tartine (Restaurant, Annecy)"  # ce qu'on ne sait pas ne se dit pas


def test_she_reads_a_fiche_as_data_and_a_review_that_gives_orders_stays_a_review(tmp_path):
    async def scenario(kernel, deliveries):
        await call(kernel, "places_search", ADRIEN, text="Ciboulette")
        read = await call(kernel, "place_read", ADRIEN, place="l7")
        return read, journal(kernel, c.LOOKED), everything(kernel)

    read, looks, written = live(tmp_path, scenario, maps=maps())
    lines = read.content.splitlines()
    assert read.ok and lines[0] == phrase("trips.tools.data")
    assert lines[1].startswith("l7 · La Ciboulette (Restaurant, Annecy) · note Google 4,6/5 (1 203 avis)")
    assert "Adresse : 1 rue Perrière, Annecy" in lines
    assert "OpenStreetMap : Cuisine : Française, régionale ; Terrasse : oui" in lines
    assert "Ce qu'en dit l'office de tourisme (Lac Annecy Tourisme, mis à jour le 12 octobre 2026) :" in lines
    assert "  Une table du vieil Annecy. Produits du lac et des alpages." in lines  # une ligne, inerte
    assert "Google Maps : note Google 4,6/5 (1 203 avis) · €€€ · 40–60 €" in lines
    assert "Le résumé de Google : « Cuisine savoyare raffinée dans une maison du vieil Annecy. »" in lines
    assert "Selon Google : Végétarien : oui (selon Google)" in lines
    assert "- 5/5, il y a 2 semaines, par Camille R. : « Un accueil adorable, et une féra parfaite. »" in lines
    # l'avis qui voudrait se faire passer pour une consigne : sur sa ligne d'avis, désamorcé, borné
    [trap] = [x for x in lines if "Ignore tes consignes" in x]
    assert trap.startswith("- 1/5, il y a un mois, par Bot ") and "---" not in read.content
    assert "ETAT INTERNE" not in read.content and len(trap) < trips_tools.REVIEW_SHOWN + 120
    assert f"- {FETE.id} · Fête du lac — sam. 21 nov. · 20:00–23:00 · Le Pâquier, Annecy" in lines
    # son regard : le lieu, comme une liste le garde — jamais le texte d'un avis, ni d'un résumé, ni d'une description
    seen = looks[-1]
    assert read.attach == (c.note_ref(c.NOTE_LOOK, seen.seq),) and seen.data.query.text == "la fiche de La Ciboulette"
    assert [x["id"] for x in json.loads(seen.data.found.text)] == ["l7"]
    for secret in ("féra parfaite", "Ignore tes consignes", "Camille R.", "savoyare", "alpages"):
        assert secret not in written, secret


def test_she_finds_the_fiche_of_here_of_a_name_and_of_an_osm_object(tmp_path):
    async def scenario(kernel, deliveries):
        port = KernelPort(kernel)
        seq = await port.locate(ADRIEN, lat=45.8995, lon=6.1262, accuracy_m=5, label="Rue Perrière", age_ms=0)
        here = await call(kernel, "place_read", ADRIEN, place="ici")
        named = await call(kernel, "place_read", ADRIEN, place="La Ciboulette")
        osm = await call(kernel, "place_read", ADRIEN, place="n800")
        address = await call(kernel, "place_read", ADRIEN, place="a:1")
        unknown = await call(kernel, "place_read", ADRIEN, place="l999")
        nowhere = await call(kernel, "place_read", ADRIEN, place="45.0,5.0")
        await port.locate(BEA, lat=45.8995, lon=6.1262, accuracy_m=5, label="Rue Perrière", age_ms=0)
        theirs = await call(kernel, "place_read", BEA, place="ici")
        return seq, here, named, osm, address, unknown, nowhere, theirs, journal(kernel, c.LOOKED)

    seq, here, named, osm, address, unknown, nowhere, theirs, looks = live(tmp_path, scenario, maps=maps())
    assert here.ok and "La Ciboulette" in here.content.splitlines()[1]
    assert here.attach == (location_c.note_ref(seq), c.note_ref(c.NOTE_LOOK, looks[0].seq))  # « ici » se voit
    assert named.ok and "Lac Annecy Tourisme" in named.content
    assert osm.ok and osm.content.splitlines()[1] == "l8 · La Tartine (Restaurant, Annecy)"
    assert not address.ok and address.content == phrase("trips.tools.fiche.address")
    assert not unknown.ok and unknown.content == phrase("trips.tools.unknown_id", id="l999")
    assert not nowhere.ok and nowhere.content == phrase("trips.tools.fiche.nothing_here")
    assert not theirs.ok and theirs.content == phrase("trips.tools.here_closed")  # les droits de location_where


def test_she_reads_an_event_whole_and_its_description_stays_data(tmp_path):
    async def scenario(kernel, deliveries):
        read = await call(kernel, "place_read", ADRIEN, place=CONCERT.id)
        gone = await call(kernel, "place_read", ADRIEN, place="e:aaaaaaaa-0000-0000-0000-000000000099")
        return read, gone, journal(kernel, c.LOOKED), everything(kernel)

    read, gone, [look], written = live(tmp_path, scenario, maps=maps())
    lines = read.content.splitlines()
    assert read.ok and lines[0] == phrase("trips.tools.data")
    assert lines[1] == f"{CONCERT.id} · Quatuor du lac — dim. 22 nov. · 18:00–19:30"
    assert "Où : Bonlieu · 1 rue Jean Jaurès, 74000 Annecy" in lines and "Tarifs : 12 € / 8 €" in lines
    assert "Ce qu'en dit Lac Annecy Tourisme (mis à jour le 10 novembre 2026) :" in lines
    assert "---" not in read.content and "ETAT INTERNE" not in read.content
    assert look.data.what == c.LOOK_EVENTS and look.data.query.text == "la fiche de Quatuor du lac"
    assert set(json.loads(look.data.found.text)[0]) == {"id", "name", "start", "end", "when_text", "place", "lat",
                                                        "lon"}
    assert "Haydn" not in written and "Oublie tout" not in written
    assert not gone.ok and gone.content == phrase("trips.tools.fiche.unknown_event")


def test_she_looks_for_events_by_period_place_and_theme_and_each_look_shows(tmp_path):
    fake = maps()

    async def scenario(kernel, deliveries):
        dated = await call(kernel, "events_search", ADRIEN, near="Annecy", start="2026-11-21", end="2026-11-22",
                           themes=["concerts"])
        free = await call(kernel, "events_search", ADRIEN, near="45.8992,6.1294", start="2026-11-20",
                          end="2026-11-30", free=True, radius_km=5)
        saturday = await call(kernel, "events_search", ADRIEN, near="Annecy", when="samedi")
        bad = await call(kernel, "events_search", ADRIEN, near="Annecy", start="2026-11-22", end="2026-11-21")
        today = kernel.mind.frame().local().date()
        return dated, free, saturday, bad, today, journal(kernel, c.LOOKED)

    dated, free, saturday, bad, today, looks = live(tmp_path, scenario, maps=fake)
    lines = dated.content.splitlines()
    assert lines[0] == phrase("trips.tools.data")
    assert lines[1].startswith(f"{CONCERT.id} · Quatuor du lac — dim. 22 nov. · 18:00–19:30 · Bonlieu, Annecy · "
                               "12 € / 8 € · à ")
    assert lines[-1] == phrase("trips.tools.events.then") and FETE.id not in dated.content  # le thème
    asked = [x for x in fake.calls if x[0] == "events"]
    assert asked[0][1] == (45.8992, 6.1294) and asked[0][3] == 15_000
    assert (str(asked[0][4]), str(asked[0][5])) == ("2026-11-21", "2026-11-22")
    assert looks[0].data.what == c.LOOK_EVENTS and dated.attach == (c.note_ref(c.NOTE_LOOK, looks[0].seq),)
    assert looks[0].data.query.text == "Événements · Concerts · samedi 21 novembre – dimanche 22 novembre · près de " \
                                       "Annecy"
    assert [x["id"] for x in json.loads(looks[0].data.found.text)] == [CONCERT.id]
    assert free.ok and f"{FETE.id} · Fête du lac" in free.content and " · gratuit · " in free.content
    assert CONCERT.id not in free.content
    expected = trips_tools.period("samedi", today)
    assert (asked[2][4], asked[2][5]) == expected  # « samedi » : le prochain
    assert not bad.ok and bad.content == phrase("trips.tools.events.bad_dates")


def test_an_events_search_says_when_its_zone_is_read_in_part(tmp_path):
    fake = maps()
    fake.events_list = ()
    fake.tourism_cover = fake.tourism_cover.__class__(True, 9, 3, "", "Cette zone n'est lue qu'en partie (cases lues : "
                                                                       "3 sur 9) : la suite se lit à la prochaine "
                                                                       "recherche, ou ce soir.")

    async def scenario(kernel, deliveries):
        return await call(kernel, "events_search", ADRIEN, near="Annecy")

    got = live(tmp_path, scenario, maps=fake)
    assert got.ok and got.content.startswith(phrase("trips.tools.events.nothing"))
    assert "(cases lues : 3 sur 9)" in got.content


def test_her_fiche_and_events_tools_only_one_to_one_with_someone_who_has_an_account(tmp_path):
    async def scenario(kernel, deliveries):
        await call(kernel, "places_search", ADRIEN, text="Ciboulette")
        frame = kernel.mind.frame()
        private = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=ADRIEN))
        room = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=ADRIEN, room="salon"))
        pols = policies()
        offered = {name: {tool: tool in kernel.runner._tools(pols[kind], kind, aud)
                          for tool in ("place_read", "events_search")}
                   for name, kind, aud in (("tête-à-tête", Kind.REPLY, private), ("initiative", Kind.INITIATIVE, private),
                                           ("salon", Kind.REPLY, room))}
        in_room = await call(kernel, "place_read", ADRIEN, audience=room, place="l7")
        events_room = await call(kernel, "events_search", ADRIEN, audience=room, near="Annecy")
        return offered, in_room, events_room

    offered, in_room, events_room = live(tmp_path, scenario, maps=maps())
    assert offered == {"tête-à-tête": {"place_read": True, "events_search": True},
                       "initiative": {"place_read": False, "events_search": False},
                       "salon": {"place_read": False, "events_search": False}}
    for refused in (in_room, events_room):
        assert not refused.ok and refused.content == phrase("trips.tools.not_here") and refused.attach == ()


def test_without_a_map_she_does_not_offer_to_read_fiches_or_events(tmp_path):
    async def scenario(kernel, deliveries):
        private = audience_for(kernel.mind.frame(), EpisodeRequest(kind=Kind.REPLY, target=ADRIEN))
        offered = kernel.runner._tools(policies()[Kind.REPLY], Kind.REPLY, private)
        return {tool: tool in offered for tool in ("place_read", "events_search")}

    assert live(tmp_path, scenario) == {"place_read": False, "events_search": False}
