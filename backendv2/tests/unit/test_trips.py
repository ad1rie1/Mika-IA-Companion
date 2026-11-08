"""Les voyages et la carte, par leurs intentions (ADR 0194, 0195, 0196).

- un voyage est à la personne qui l'a créé : ce qu'on en fait depuis l'écran Carte passe par les actions de la
  console, en son nom, qui refusent ce qui n'est pas à elle et ce qui dépasse les bornes ; ses arrêts sont rangés par
  jour, puis dans l'ordre du jour ; l'identifiant d'un voyage, d'un arrêt, est le ``seq`` de sa création ;
- ses textes sont des contenus personnels, la personne pour sujet ;
- ses outils : en tête-à-tête, avec quelqu'un qui a un compte — jamais en salon, ni à un inconnu, ni dans une
  initiative ; ils cherchent dans l'index (rien ne sort), une adresse, un trajet, et chaque regard s'écrit et se voit
  (``look:``) ; « ici » est un regard sur sa position (la bulle 📍 suit), que les droits de ``location_where``
  gouvernent ; un nom d'OpenStreetMap est rendu inerte ;
- elle crée et change un voyage quand on le lui demande (rose : ``by`` = elle, ``trip:``), jamais celui d'une autre ;
  elle montre une carte (``map:``) ;
- les notes de ses messages disent ce qu'elle a fait et ce qu'elles ouvrent (``ref``) ; oublier la personne efface
  ses voyages, ses regards et leurs notes ;
- le journal rejoué redonne le même état.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import get_args

import pytest

from mika.adapters.web import protocol
from mika.app.composition import policies
from mika.app.mindport import KernelPort
from mika.app.moi import form
from mika.contracts import location as location_c
from mika.contracts import runtime as rt
from mika.contracts import trips as c
from mika.contracts.entry import MessageNote
from mika.faculties.identity import audience_for
from mika.kernel.codec import digest
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins import location as location_p
from mika.plugins.trips import TRIPS, geo
from mika.plugins.trips import tools as trips_tools
from mika.plugins.trips.actions import moves
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.ports.maps import (
    AVOIDS,
    MODES,
    ROUTE_POINTS_MAX,
    RouteLeg,
    RouteResult,
    decode_polyline6,
    encode_polyline6,
)
from mika.runtime.operations import perform
from mika.runtime.pipeline import EpisodeRequest
from mika.sim.clock import run_virtual
from mika.vocab.circadian import day_fr
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.fake_maps import CHEVRERIE, HORIZON, TALLOIRES, FakeMaps
from tests.fixtures.mika import boot, build, connect, said
from tests.unit.test_shares import call, journal

ADRIEN, BEA = "user_1", "user_2"
PERSONAL = int(Sensitivity.PERSONAL)


def quiet(req: LLMRequest) -> LLMResponse:
    return LLMResponse("D'accord.")


def live(tmp_path, scenario, *, respond=quiet, maps: FakeMaps | None = None):
    ports = {"maps": maps} if maps is not None else {}
    kernel, clock, llm, deliveries = build(tmp_path, respond, arbitration=ArbitrationPolicy(), ports=ports)

    async def main():
        await boot(kernel)
        try:
            await connect(kernel, ADRIEN, "Adrien", operator=True)
            await connect(kernel, BEA, "Béa")
            return await scenario(kernel, deliveries)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def act(kernel, key: str, *, by: str = ADRIEN, fixed=None, **values):
    return await perform(kernel, key, form(fixed, **values), by=by)


async def trip_with_stops(kernel, *stops: tuple[str, float, float, int], by: str = ADRIEN) -> tuple[str, list[str]]:
    made = await act(kernel, "trips.creer", by=by, title="Le lac", start="2027-05-01", mode="voiture", avoid=[])
    trip = str(made.seqs[0])
    ids = []
    for name, lat, lon, day in stops:
        got = await act(kernel, "trips.ajouter_arret", by=by, fixed={"trip": trip}, name=name, lat=lat, lon=lon,
                        kind="", day=day, index=-1, note="")
        ids.append(str(got.seqs[0]))
    return trip, ids


def state(kernel):
    return kernel.mind.frame().state(c.OWNER)


# ── ce que l'écran Carte fait d'un voyage : les actions ──


def test_a_trip_is_hers_and_its_stops_are_ranged_by_day(tmp_path):
    async def scenario(kernel, deliveries):
        made = await act(kernel, "trips.creer", title="  Les Alpes  en cinq jours ", start="2027-04-03",
                         mode="voiture", avoid=["peages", "ferries"])
        trip = str(made.seqs[0])
        stop = {"fixed": {"trip": trip}, "kind": "", "note": ""}
        annecy = await act(kernel, "trips.ajouter_arret", **{**stop, "kind": "Ville"}, name="Annecy", lat=45.8992,
                           lon=6.1294, day=1, index=-1)
        lac = await act(kernel, "trips.ajouter_arret", **{**stop, "note": "Se baigner"}, name="Talloires",
                        lat=45.8406, lon=6.2128, day=2, index=-1)
        first = await act(kernel, "trips.ajouter_arret", **stop, name="Sévrier", lat=45.864, lon=6.141, day=1, index=0)
        moved = await act(kernel, "trips.deplacer_arret", fixed={"trip": trip, "stop": str(annecy.seqs[0])}, day=2,
                          index=0)
        noted = await act(kernel, "trips.noter_arret", fixed={"trip": trip, "stop": str(first.seqs[0])},
                          note="Le marché du dimanche")
        changed = await act(kernel, "trips.modifier", fixed={"trip": trip}, mode="velo", start="")
        return made, trip, (annecy, lac, first), (moved, noted, changed), state(kernel), \
            journal(kernel, c.CREATED, c.STOP_ADDED, c.STOP_NOTED)

    made, trip, (annecy, lac, first), done, s, events = live(tmp_path, scenario)
    assert made.ok and all(x.ok for x in (annecy, lac, first, *done)), [x.message for x in done]
    t = s.trips[trip]
    created = events[0]
    assert trip == str(created.seq) and t.person == ADRIEN and t.by == ADRIEN and not t.mika_touched
    assert created.data.title.text == "Les Alpes en cinq jours" and created.data.avoid == ("peages", "ferries")
    assert t.mode == "velo" and t.start == "" and t.avoid == ("peages", "ferries")  # « start » vidé, le reste gardé
    # le jour 1 : Sévrier (inséré en tête) ; le jour 2 : Annecy (déplacé en tête), puis Talloires
    assert [(x.id, x.day) for x in t.stops] == [(str(first.seqs[0]), 1), (str(annecy.seqs[0]), 2),
                                                (str(lac.seqs[0]), 2)]
    added = {e.seq: e.data for e in events if e.type.name == c.STOP_ADDED.name}
    assert added[annecy.seqs[0]].coords.text == "45.899200,6.129400" and added[annecy.seqs[0]].kind.text == "Ville"
    assert all(d.name.level == d.coords.level == PERSONAL for d in added.values())
    assert [e.data.note.text for e in events if e.type.name == c.STOP_NOTED.name] == ["Le marché du dimanche"]
    assert all(e.data.by == ADRIEN for e in events) and t.stamp == done[2].seqs[0]


def test_the_actions_refuse_what_is_not_hers_and_what_goes_beyond(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "TRIPS_MAX", 2)
    monkeypatch.setattr(c, "STOPS_MAX", 1)

    async def scenario(kernel, deliveries):
        trip, [stop] = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1))
        out = {
            "béa modifie": await act(kernel, "trips.modifier", by=BEA, fixed={"trip": trip}, title="À moi"),
            "béa retire": await act(kernel, "trips.retirer_arret", by=BEA, fixed={"trip": trip, "stop": stop}),
            "béa supprime": await act(kernel, "trips.supprimer", by=BEA, fixed={"trip": trip}),
            "date": await act(kernel, "trips.creer", title="Été", start="03/04/2027", mode="voiture", avoid=[]),
            "évite": await act(kernel, "trips.creer", title="Été", start="", mode="voiture", avoid=["metro"]),
            "mode": await act(kernel, "trips.creer", title="Été", start="", mode="avion", avoid=[]),
            "titre vide": await act(kernel, "trips.modifier", fixed={"trip": trip}, title="   "),
            "arrêt inconnu": await act(kernel, "trips.deplacer_arret", fixed={"trip": trip, "stop": "999"}, day=1,
                                       index=0),
            "trop d'arrêts": await act(kernel, "trips.ajouter_arret", fixed={"trip": trip}, name="Lyon", lat=45.76,
                                       lon=4.83, kind="", day=1, index=-1, note=""),
            "hors de la Terre": await act(kernel, "trips.ajouter_arret", fixed={"trip": trip}, name="Ailleurs",
                                          lat=95, lon=0, kind="", day=1, index=-1, note=""),
            "mauvais ordre": await act(kernel, "trips.ordonner_jour", fixed={"trip": trip}, day=1, order=["999"]),
        }
        second = await act(kernel, "trips.creer", title="Deux", start="", mode="pied", avoid=[])
        out["trop de voyages"] = await act(kernel, "trips.creer", title="Trois", start="", mode="pied", avoid=[])
        return out, second, state(kernel), trip

    out, second, s, trip = live(tmp_path, scenario)
    assert second.ok and len(s.trips) == 2 and s.trips[trip].stops[0].day == 1
    assert all(not got.ok for got in out.values()), {k: v.message for k, v in out.items() if v.ok}
    for theirs in ("béa modifie", "béa retire", "béa supprime"):
        assert out[theirs].message == "Ce voyage n'existe pas."  # l'API en fait un 404
    assert "start" in out["date"].errors and "avoid" in out["évite"].errors and "mode" in out["mode"].errors
    assert "title" in out["titre vide"].errors and "order" in out["mauvais ordre"].errors
    assert "1 arrêts au plus" in out["trop d'arrêts"].message and "2 voyages au plus" in out["trop de voyages"].message
    assert out["hors de la Terre"].errors  # la borne du formulaire


def test_an_operator_removes_a_trip_from_its_person_s_fiche_and_does_nothing_else(tmp_path):
    """La console (ADR 0204) : un opérateur supprime un voyage depuis la fiche de sa personne (``subject``) — ni hors de
    cette fiche, ni rien d'autre que le supprimer (le voyage se prépare à deux) ; une personne qui n'est pas opératrice,
    jamais ; chaque geste audité, celui qui supprime au nom de l'opérateur, sur la personne."""

    async def on(kernel, key: str, *, by: str, subject: str, fixed, **values):
        return await perform(kernel, key, form(fixed, **values), by=by, subject=subject)

    async def scenario(kernel, deliveries):
        theirs, [stop] = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1), by=BEA)
        mine, _ = await trip_with_stops(kernel)
        out = {
            "hors de sa fiche": await on(kernel, "trips.supprimer", by=ADRIEN, subject="", fixed={"trip": theirs}),
            "sur une autre fiche": await on(kernel, "trips.supprimer", by=ADRIEN, subject=ADRIEN,
                                            fixed={"trip": theirs}),
            "le modifier": await on(kernel, "trips.modifier", by=ADRIEN, subject=BEA, fixed={"trip": theirs},
                                    title="À moi"),
            "retirer un arrêt": await on(kernel, "trips.retirer_arret", by=ADRIEN, subject=BEA,
                                         fixed={"trip": theirs, "stop": stop}),
            "béa, sur la fiche d'adrien": await on(kernel, "trips.supprimer", by=BEA, subject=ADRIEN,
                                                   fixed={"trip": mine}),
        }
        kept = {trip: len(t.stops) for trip, t in state(kernel).trips.items()}
        done = await on(kernel, "trips.supprimer", by=ADRIEN, subject=BEA, fixed={"trip": theirs})
        return out, kept, done, state(kernel), journal(kernel, c.REMOVED, rt.OPERATED), theirs, mine

    out, kept, done, s, events, theirs, mine = live(tmp_path, scenario)
    assert all(not got.ok and got.message == "Ce voyage n'existe pas." for got in out.values()), \
        {k: v.message for k, v in out.items()}
    assert kept == {theirs: 1, mine: 0}  # rien n'a bougé
    assert done.ok and done.message == "Voyage supprimé." and set(s.trips) == {mine}
    [removed] = [e for e in events if e.type.name == c.REMOVED.name]
    assert (removed.data.trip, removed.data.person, removed.data.by) == (theirs, BEA, ADRIEN)
    audits = [e.data for e in events if e.type.name == rt.OPERATED.name]
    # chaque essai audité, les refus aussi ; la suppression, sur la personne, avec ce qu'elle a écrit
    assert [(a.by, a.subject, a.outcome) for a in audits if a.action == "trips.supprimer"] == \
        [(ADRIEN, "", "refused"), (ADRIEN, ADRIEN, "refused"), (BEA, ADRIEN, "refused"), (ADRIEN, BEA, "done")]
    assert audits[-1].seqs == (removed.seq,)
    assert [a.outcome for a in audits if a.action in ("trips.modifier", "trips.retirer_arret")] == ["refused"] * 2


def test_reordering_a_day_moves_each_stop_once_and_lands_on_the_order(tmp_path):
    assert moves(["a", "b", "c", "d"], ["a", "c", "b", "d"]) == [("c", 1)]
    assert moves(["a", "b", "c"], ["a", "b", "c"]) == []
    assert moves(["a", "b", "c", "d"], ["d", "c", "b", "a"]) == [("d", 0), ("c", 1), ("b", 2)]

    async def scenario(kernel, deliveries):
        trip, ids = await trip_with_stops(kernel, ("A", 45.0, 6.0, 1), ("B", 45.1, 6.1, 1), ("C", 45.2, 6.2, 1),
                                          ("D", 45.3, 6.3, 1), ("E", 45.4, 6.4, 2))
        a, b, cc, d, e = ids
        got = await act(kernel, "trips.ordonner_jour", fixed={"trip": trip}, day=1, order=[a, cc, b, d])
        again = await act(kernel, "trips.ordonner_jour", fixed={"trip": trip}, day=1, order=[a, cc, b, d])
        return got, again, [x.id for x in state(kernel).trips[trip].stops], ids, journal(kernel, c.STOP_MOVED)

    got, again, order, (a, b, cc, d, e), moved = live(tmp_path, scenario)
    assert got.ok and order == [a, cc, b, d, e] and [m.data.stop for m in moved] == [cc]
    assert again.ok and again.message == "Déjà dans cet ordre." and len(moved) == 1


# ── à qui ses outils servent ──


def test_her_map_tools_only_one_to_one_with_someone_who_has_an_account(tmp_path):
    async def scenario(kernel, deliveries):
        await connect(kernel, "web_inconnu", "Zoé", authenticated=False)
        frame = kernel.mind.frame()
        private = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=ADRIEN))
        hers = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=BEA))
        room = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target=ADRIEN, room="salon"))
        stranger = audience_for(frame, EpisodeRequest(kind=Kind.REPLY, target="web_inconnu"))
        pols = policies()
        offered = {name: {tool: tool in kernel.runner._tools(pols[kind], kind, aud)
                          for tool in ("places_search", "trip_create", "map_show")}
                   for name, kind, aud in (("propriétaire", Kind.REPLY, private), ("une amie", Kind.REPLY, hers),
                                           ("initiative", Kind.INITIATIVE, private), ("salon", Kind.REPLY, room),
                                           ("inconnu", Kind.REPLY, stranger))}
        in_room = await call(kernel, "trip_list", ADRIEN, audience=room)
        to_stranger = await call(kernel, "places_search", "web_inconnu", audience=stranger, text="Annecy")
        return offered, in_room, to_stranger

    offered, in_room, to_stranger = live(tmp_path, scenario, maps=FakeMaps())
    every = {"places_search": True, "trip_create": True, "map_show": True}
    never = dict.fromkeys(every, False)
    assert offered == {"propriétaire": every, "une amie": every, "initiative": never, "salon": never,
                       "inconnu": never}
    for refused in (in_room, to_stranger):
        assert not refused.ok and refused.content == phrase("trips.tools.not_here") and refused.attach == ()


def test_without_a_map_she_does_not_offer_to_search_but_keeps_your_trips(tmp_path):
    async def scenario(kernel, deliveries):
        private = audience_for(kernel.mind.frame(), EpisodeRequest(kind=Kind.REPLY, target=ADRIEN))
        offered = kernel.runner._tools(policies()[Kind.REPLY], Kind.REPLY, private)
        return {tool: tool in offered for tool in ("places_search", "route_plan", "trip_list", "trip_create")}

    assert live(tmp_path, scenario) == {"places_search": False, "route_plan": False, "trip_list": True,
                                        "trip_create": True}


# ── chercher, regarder ──


def test_she_searches_the_index_and_each_look_is_kept_and_seen(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        near = await call(kernel, "places_search", ADRIEN, category="dormir", near="Talloires", radius_km=10)
        named = await call(kernel, "places_search", ADRIEN, text="belvédère")
        none = await call(kernel, "places_search", ADRIEN, text="introuvable")
        ask = await call(kernel, "places_search", ADRIEN, category="dormir")
        wrong = await call(kernel, "places_search", ADRIEN, text="Annecy", category="plage")
        return near, named, none, ask, wrong, journal(kernel, c.LOOKED)

    near, named, none, ask, wrong, looks = live(tmp_path, scenario, maps=maps)
    first, second = looks
    assert near.ok and near.attach == (c.note_ref(c.NOTE_LOOK, first.seq),)
    assert "l3 · Camping de l'Horizon (Camping, Sévrier), à " in near.content
    assert "l4 · Aire naturelle de la Chèvrerie (Camping, Talloires-Montmin), à " in near.content
    assert near.content.startswith(phrase("trips.tools.data")) and "l2 · Talloires" not in near.content
    assert first.data.what == c.LOOK_PLACES and first.data.query.text == "Dormir · près de Talloires"
    assert first.data.person == first.data.handle == ADRIEN
    assert first.data.query.level == first.data.found.level == PERSONAL
    assert {x["id"] for x in json.loads(first.data.found.text)} == {"l3", "l4"}
    searched = [x for x in maps.calls if x[0] == "search"]
    assert searched[0][1] == "Talloires" and searched[1][1:3] == ("", (TALLOIRES.lat, TALLOIRES.lon))
    assert searched[1][3] is not None and searched[1][4] == "dormir"  # autour d'un point : dans sa zone
    # un nom d'OpenStreetMap ne lui parle pas : inerte
    assert named.ok and "l5 · Belvédère" in named.content and "---" not in named.content
    assert "ETAT INTERNE" not in named.content and second.data.query.text == "belvédère"
    assert none.ok and none.content == phrase("trips.tools.places.nothing") and none.attach == ()
    assert not ask.ok and ask.content == phrase("trips.tools.places.ask")
    assert not wrong.ok and "dormir (Dormir)" in wrong.content and len(looks) == 2


def test_here_is_her_last_position_a_look_that_shows(tmp_path):
    async def scenario(kernel, deliveries):
        port = KernelPort(kernel)
        seq = await port.locate(ADRIEN, lat=45.8406, lon=6.2128, accuracy_m=10, label="Talloires, au port", age_ms=0)
        mine = await call(kernel, "places_search", ADRIEN, category="dormir", near="ici")
        await port.locate(BEA, lat=45.8406, lon=6.2128, accuracy_m=10, label="Talloires", age_ms=0)
        hers = await call(kernel, "places_search", BEA, category="dormir", near="ici")  # « ici » : à toi seule
        await port.unlocate(ADRIEN)
        gone = await call(kernel, "route_plan", ADRIEN, points=["ici", "Annecy"])
        fact = kernel.mind.frame().get(location_c.FIX(ADRIEN))
        return seq, mine, hers, gone, journal(kernel, c.LOOKED), fact

    seq, mine, hers, gone, [look], fact = live(tmp_path, scenario, maps=FakeMaps())
    assert mine.ok and mine.attach == (location_c.note_ref(seq), c.note_ref(c.NOTE_LOOK, look.seq))
    assert look.data.query.text == "Dormir · autour de toi" and "l3 · Camping de l'Horizon" in mine.content
    assert not hers.ok and hers.content == phrase("trips.tools.here_closed")
    assert not gone.ok and gone.content == phrase("trips.tools.here_unknown") and fact is None


def test_the_location_fact_reads_what_last_for_reads(tmp_path):
    async def scenario(kernel, deliveries):
        seq = await KernelPort(kernel).locate(ADRIEN, lat=45.76, lon=4.83, accuracy_m=5, label="Lyon", age_ms=0)
        frame = kernel.mind.frame()
        fix = location_p.last_for(frame.state(location_c.OWNER), frame, ADRIEN)
        return seq, fix, frame.get(location_c.FIX(ADRIEN)), frame.get(location_c.FIX(BEA))

    seq, fix, read, none = live(tmp_path, scenario)
    assert read == location_c.FixReading(seq, fix.coords_ref, fix.label_ref, fix.fixed_at) and none is None


def test_a_route_takes_ids_coordinates_and_names_and_is_seen(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        await call(kernel, "places_search", ADRIEN, category="dormir", near="Talloires")  # un autre épisode : l3, l4
        route = await call(kernel, "route_plan", ADRIEN, points=["l3", "45.8406,6.2128", "Annecy"], mode="velo",
                           avoid=["peages"])
        unknown = await call(kernel, "route_plan", ADRIEN, points=["l999", "Annecy"])
        maps.fail = "Le serveur d'itinéraires ne répond pas."
        failed = await call(kernel, "route_plan", ADRIEN, points=["l3", "Annecy"])
        maps.fail, maps.routing_on = "", False
        off = await call(kernel, "route_plan", ADRIEN, points=["l3", "Annecy"])
        return route, unknown, failed, off, journal(kernel, c.LOOKED)

    route, unknown, failed, off, looks = live(tmp_path, scenario, maps=maps)
    seen = looks[-1]
    assert route.ok and route.attach == (c.note_ref(c.NOTE_LOOK, seen.seq),) and len(looks) == 2
    assert "Camping de l'Horizon → 45.84060, 6.21280 → Annecy : " in route.content and "à vélo" in route.content
    assert "Camping de l'Horizon → 45.84060, 6.21280 : " in route.content  # ses tronçons
    assert "Par : " in route.content and "Prendre la D909 vers Talloires" in route.content
    found = json.loads(seen.data.found.text)
    assert seen.data.what == c.LOOK_ROUTE and found["mode"] == "velo" and len(found["points"]) == 3
    assert found["avoid"] == ["peages"]  # ce qu'elle a évité se garde : l'écran le redit tel quel
    assert found["points"][0]["name"] == HORIZON.name and len(decode_polyline6(found["shape"])) >= 3
    [(_, points, mode, avoid)] = [x for x in maps.calls if x[0] == "route"][:1]
    assert points[0] == (HORIZON.lat, HORIZON.lon) and mode == "velo" and avoid == frozenset({"peages"})
    assert not unknown.ok and unknown.content == phrase("trips.tools.unknown_id", id="l999")
    assert not failed.ok and "ne répond pas" in failed.content
    assert not off.ok and off.content == phrase("trips.tools.no_routing")


def test_an_address_is_looked_for_only_when_addresses_are_plugged(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        found = await call(kernel, "address_search", ADRIEN, text="Place de la Concorde Paris")
        maps.addresses_on = False
        off = await call(kernel, "address_search", ADRIEN, text="Place de la Concorde Paris")
        return found, off, journal(kernel, c.LOOKED)

    found, off, [look] = live(tmp_path, scenario, maps=maps)
    assert found.ok and "a:1 · Place de la Concorde 75008 Paris (Adresse, Paris)" in found.content
    assert look.data.query.text == "Place de la Concorde Paris" and found.attach == (c.note_ref(c.NOTE_LOOK, look.seq),)
    assert not off.ok and off.content == phrase("trips.tools.no_addresses")
    assert [x[0] for x in maps.calls] == ["addresses"]  # seul le texte cherché est parti


# ── ses voyages ──


def test_she_prepares_a_trip_when_asked_and_what_she_adds_is_hers(tmp_path):
    async def scenario(kernel, deliveries):
        await call(kernel, "places_search", ADRIEN, category="dormir", near="Talloires")
        made = await call(kernel, "trip_create", ADRIEN, title="Le lac d'Annecy", start="2027-05-01",
                          stops=[{"place": "l3", "day": 1, "note": "au calme"}, {"place": "Talloires", "day": 2}])
        trip = c.note_of(made.attach[-1])[1]
        horizon, talloires = [x.id for x in state(kernel).trips[trip].stops]
        edited = await call(kernel, "trip_edit", ADRIEN, trip=trip, title="Le lac", avoid=["autoroutes"],
                            add=[{"place": "l4", "day": 2, "index": 0}], remove=[horizon],
                            move=[{"stop": talloires, "day": 1}])
        written = len(journal(kernel, *c.ALL))
        wrong = await call(kernel, "trip_edit", ADRIEN, trip=trip, remove=["12345"], add=[{"place": "l4"}])
        bad = await call(kernel, "trip_create", ADRIEN, title="Été", start="1er mai")
        theirs = await call(kernel, "trip_edit", BEA, trip=trip, title="À moi")
        listed = await call(kernel, "trip_list", BEA)
        untouched = len(journal(kernel, *c.ALL)) == written  # un refus n'écrit rien, pas même à moitié
        return made, trip, edited, wrong, bad, theirs, listed, state(kernel), untouched

    made, trip, edited, wrong, bad, theirs, listed, s, untouched = live(tmp_path, scenario, maps=FakeMaps())
    assert untouched
    t = s.trips[trip]
    assert made.ok and made.attach == (c.note_ref(c.NOTE_TRIP, trip),)
    assert made.content == phrase("trips.tools.create.done", id=trip, title="Le lac d'Annecy",
                                  stops=phrase("trips.tools.stops_many", n=2))
    assert t.by == c.BY_HER and t.mika_touched and t.person == ADRIEN and t.avoid == ("autoroutes",)
    assert edited.ok and edited.attach == (c.note_ref(c.NOTE_TRIP, trip),) and "Le lac" in edited.content
    assert "retiré : Camping de l'Horizon" in edited.content and "ajouté : Aire naturelle" in edited.content
    # Talloires au jour 1 ; la Chèvrerie au jour 2, ajoutée par elle
    assert [(x.day, x.by) for x in t.stops] == [(1, c.BY_HER), (2, c.BY_HER)] and len(t.stops) == 2
    assert not wrong.ok and phrase("trips.tools.unknown_stop", stop="12345") in wrong.content and len(t.stops) == 2
    assert not bad.ok and bad.content == phrase("trips.tools.bad_date")
    assert not theirs.ok and theirs.content == phrase("trips.tools.unknown_trip", trip=trip)
    assert listed.ok and listed.content == phrase("trips.tools.list.none")


def test_she_rereads_a_trip_day_by_day_with_its_legs(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        trip, ids = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1), ("Talloires", 45.8406, 6.2128, 1),
                                          ("Lyon", 45.764, 4.8357, 3))
        await act(kernel, "trips.noter_arret", fixed={"trip": trip, "stop": ids[1]}, note="Se baigner")
        await call(kernel, "places_search", ADRIEN, text="Chèvrerie")
        await call(kernel, "trip_edit", ADRIEN, trip=trip, add=[{"place": "l4", "day": 1}])
        read = await call(kernel, "trip_read", ADRIEN, trip=trip)
        listed = await call(kernel, "trip_list", ADRIEN)
        maps.routing_on = False
        plain = await call(kernel, "trip_read", ADRIEN, trip=trip)
        return trip, ids, read, listed, plain

    trip, ids, read, listed, plain = live(tmp_path, scenario, maps=maps)
    assert read.ok and f"Voyage {trip} · « Le lac » : " in read.content
    assert f"Jour 1 ({day_fr(date(2027, 5, 1))}) :" in read.content and phrase("trips.tools.read.empty_day") in read.content
    assert f"[{ids[1]}] Talloires" in read.content and "note : « Se baigner »" in read.content
    assert "Aire naturelle de la Chèvrerie · Camping · ajouté par toi" in read.content
    assert "depuis l'arrêt d'avant" in read.content and phrase("trips.tools.read.no_routing") not in read.content
    assert listed.ok and f"{trip} · « Le lac » : 3 jours, 4 arrêts, départ le samedi 1er mai, en voiture" in listed.content
    assert plain.ok and phrase("trips.tools.read.no_routing") in plain.content


def test_she_finds_what_lies_along_a_trip(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        trip, _ = await trip_with_stops(kernel, ("Camping de l'Horizon", HORIZON.lat, HORIZON.lon, 1),
                                        ("Talloires", TALLOIRES.lat, TALLOIRES.lon, 1))
        along = await call(kernel, "trip_suggest", ADRIEN, trip=trip, category="voir")
        maps.routing_on = False
        straight = await call(kernel, "trip_suggest", ADRIEN, trip=trip, category="voir", day=1)
        short = await call(kernel, "trip_suggest", ADRIEN, trip=trip, category="voir", day=2)
        return along, straight, short, journal(kernel, c.LOOKED)

    along, straight, short, looks = live(tmp_path, scenario, maps=maps)
    assert along.ok and "l5 · Belvédère" in along.content and "du trajet, après" in along.content
    assert "---" not in along.content and looks[0].data.query.text == "À voir · le long de « Le lac »"
    assert along.attach == (c.note_ref(c.NOTE_LOOK, looks[0].seq),)
    assert straight.ok and phrase("trips.tools.suggest.straight") in straight.content
    assert not short.ok and short.content == phrase("trips.tools.suggest.short")
    assert [x[0] for x in maps.calls].count("along") == 2


def test_she_shows_a_map_in_her_message(tmp_path):
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        trip, _ = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1), ("Talloires", 45.8406, 6.2128, 2))
        await call(kernel, "places_search", ADRIEN, category="dormir", near="Talloires")
        shown = await call(kernel, "map_show", ADRIEN, title="Deux campings", places=["l3", "l4"], route=True)
        of_trip = await call(kernel, "map_show", ADRIEN, title="Notre voyage", trip=trip)
        maps.routing_on = False
        flat = await call(kernel, "map_show", ADRIEN, title="Sans tracé", places=["l3", "l4"], route=True)
        empty = await call(kernel, "map_show", ADRIEN, title="Rien")
        return trip, shown, of_trip, flat, empty, journal(kernel, c.SHOWN)

    trip, shown, of_trip, flat, empty, maps_shown = live(tmp_path, scenario, maps=maps)
    first, second, third = maps_shown
    assert shown.ok and shown.attach == (c.note_ref(c.NOTE_MAP, first.seq),)
    assert first.data.route and json.loads(first.data.line.text)["distance_m"] > 0
    assert [p["name"] for p in json.loads(first.data.places.text)] == [HORIZON.name, CHEVRERIE.name]
    assert first.data.title.level == first.data.places.level == PERSONAL
    assert of_trip.ok and second.data.trip == trip and len(json.loads(second.data.places.text)) == 2
    assert flat.ok and third.data.line is None and phrase("trips.tools.show.no_line") in flat.content
    assert not empty.ok and empty.content == phrase("trips.tools.show.empty")


# ── les notes de ses messages, l'oubli, le rejeu ──


def test_her_notes_say_what_she_did_and_what_they_open(tmp_path):
    async def scenario(kernel, deliveries):
        port = KernelPort(kernel)
        trip, _ = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1))
        looked = await call(kernel, "places_search", ADRIEN, text="Talloires")
        shown = await call(kernel, "map_show", ADRIEN, title="Le lac", places=["l2"])
        refs = [c.note_ref(c.NOTE_TRIP, trip), looked.attach[0], shown.attach[0], c.note_ref(c.NOTE_TRIP, 999_999),
                c.note_ref(c.NOTE_LOOK, int(trip)), "look:abc", "trip:"]
        before = port.notes(refs)
        await act(kernel, "trips.supprimer", fixed={"trip": trip})
        after = port.notes(refs[:1])
        return trip, looked, shown, before, after, state(kernel)

    trip, looked, shown, before, after, s = live(tmp_path, scenario, maps=FakeMaps())
    gone_trip = c.note_ref(c.NOTE_TRIP, 999_999)
    by = {n.id: n for n in before}
    assert set(by) == {c.note_ref(c.NOTE_TRIP, trip), looked.attach[0], shown.attach[0], gone_trip}
    assert by[c.note_ref(c.NOTE_TRIP, trip)] == MessageNote(c.note_ref(c.NOTE_TRIP, trip), c.NOTE_TRIP, "Le lac",
                                                            by[c.note_ref(c.NOTE_TRIP, trip)].at, ref=trip)
    assert by[looked.attach[0]].kind == c.NOTE_LOOK and by[looked.attach[0]].text == "Talloires"
    assert by[looked.attach[0]].ref == c.note_of(looked.attach[0])[1]
    assert by[shown.attach[0]].kind == c.NOTE_MAP and by[shown.attach[0]].text == "Le lac"
    assert by[gone_trip].text == "" and by[gone_trip].ref == ""  # rien à ouvrir
    # ce qu'en voit un client : ``ref`` quand il y a quelque chose à ouvrir, sinon rien
    assert protocol.note_item(by[looked.attach[0]]) == {"kind": "look", "text": "Talloires",
                                                         "at": by[looked.attach[0]].at,
                                                         "ref": c.note_of(looked.attach[0])[1]}
    assert "ref" not in protocol.note_item(by[gone_trip])
    assert "ref" not in protocol.note_item(MessageNote("location:3", "location", "Lyon", 5))
    # le voyage supprimé : sa note se vide
    assert [(n.text, n.ref) for n in after] == [("", "")] and trip not in s.trips


def test_forgetting_the_person_erases_her_trips_her_looks_and_their_notes(tmp_path):
    async def scenario(kernel, deliveries):
        port = KernelPort(kernel)
        trip, _ = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1))
        theirs, _ = await trip_with_stops(kernel, ("Lyon", 45.764, 4.8357, 1), by=BEA)
        looked = await call(kernel, "places_search", ADRIEN, text="Talloires")
        shown = await call(kernel, "map_show", ADRIEN, title="Le lac", places=["l2"])
        refs = [c.note_ref(c.NOTE_TRIP, trip), looked.attach[0], shown.attach[0]]
        before = port.notes(refs)
        await kernel.mind.forget(ADRIEN)
        return (trip, theirs, before, port.notes(refs), state(kernel), journal(kernel, c.CREATED, c.LOOKED, c.SHOWN),
                await call(kernel, "route_plan", ADRIEN, points=["l2", "Annecy"]))

    trip, theirs, before, after, s, events, again = live(tmp_path, scenario, maps=FakeMaps())
    assert [n.text for n in before] == ["Le lac", "Talloires", "Le lac"]
    assert [(n.text, n.ref) for n in after] == [("", "")] * 3  # elle a fait ces gestes : sans plus dire quoi
    assert trip not in s.trips and theirs in s.trips and ADRIEN not in s.looks
    mine = [e for e in events if e.data.person == ADRIEN]
    assert mine and all(getattr(e.data, f).text is None for e in mine for f in e.type.content_fields
                        if getattr(e.data, f) is not None)
    assert [e.data.title.text for e in events if e.data.person == BEA] == ["Le lac"]
    assert not again.ok and again.content == phrase("trips.tools.unknown_id", id="l2")  # ses regards sont partis


def test_her_message_carries_a_little_map_of_what_she_looked_for(tmp_path):
    asked = "tu me trouves un camping près de Talloires ?"

    def looking(req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return LLMResponse("D'accord.")
        if not any(m.role == "tool" for m in req.messages) and any(asked in (m.content or "") for m in req.messages):
            return LLMResponse("", (ToolCall("c1", "places_search", {"category": "dormir", "near": "Talloires"}),),
                               stop="tool_use")
        return LLMResponse("Le Camping de l'Horizon, à Sévrier ! [EMOTION:happy:0.5]")

    async def scenario(kernel, deliveries):
        report = await (await kernel.perceive(said(ADRIEN, asked))).reply
        await asyncio.sleep(1)
        [utterance] = [e for e in journal(kernel, rt.UTTERANCE) if e.data.attachments]
        delivered = [d for d in deliveries.items if d.target == ADRIEN and d.text][-1]
        return report, utterance, delivered, KernelPort(kernel).notes(utterance.data.attachments), \
            journal(kernel, c.LOOKED)

    report, utterance, delivered, notes, [look] = live(tmp_path, scenario, respond=looking, maps=FakeMaps())
    ref = c.note_ref(c.NOTE_LOOK, look.seq)
    assert report.outcome.value == "done" and utterance.data.attachments == (ref,)
    assert delivered.attachments == (ref,)
    assert protocol.speech(delivered, notes=notes)["notes"] == [
        {"kind": "look", "text": "Dormir · près de Talloires", "at": look.at // 1000, "ref": str(look.seq)}]
    assert protocol.speech(delivered)["attachments"] == []  # ce n'est pas un fichier


def test_the_journal_replayed_gives_the_same_trips_and_a_snapshot_keeps_them(tmp_path):
    async def scenario(kernel, deliveries):
        trip, ids = await trip_with_stops(kernel, ("A", 45.0, 6.0, 1), ("B", 45.1, 6.1, 2), ("C", 45.2, 6.2, 1))
        await act(kernel, "trips.deplacer_arret", fixed={"trip": trip, "stop": ids[2]}, day=2, index=0)
        await act(kernel, "trips.retirer_arret", fixed={"trip": trip, "stop": ids[0]})
        await call(kernel, "places_search", ADRIEN, text="Annecy")
        live_state = state(kernel)
        await kernel.mind.rebuild([TRIPS.name])
        # l'instantané d'une tranche se relit tel quel (sinon elle se reconstruirait depuis la genèse à chaque
        # démarrage, sans rien dire)
        adapter = kernel.mind.registry.slice_adapter(TRIPS.name)
        kept = adapter.validate_python(json.loads(json.dumps(adapter.dump_python(live_state, mode="json"))))
        return digest(live_state), digest(state(kernel)), kept == live_state, live_state.looks

    before, after, snapshot, looks = live(tmp_path, scenario, maps=FakeMaps())
    assert before == after and snapshot and looks


# ── sans un mot : la géométrie ──


def test_the_geometry_of_a_trip():
    assert geo.parse_coords(" 45.764043 , 4.835659 ") == (45.764043, 4.835659)
    for bad in ("45.7", "91,0", "0,181", "a,b", "45,7,1", ""):
        assert geo.parse_coords(bad) is None, bad
    assert geo.coords_text(45.7640434, 4.8356591) == "45.764043,4.835659"
    assert geo.km_text(812) == "810 m" and geo.km_text(5_840) == "5,8 km" and geo.km_text(152_300) == "152 km"
    assert geo.duration_text(25 * 60) == "25 min" and geo.duration_text(65 * 60) == "1 h 05"
    assert geo.duration_text(7 * 3600) == "7 h"
    line = [(45.0 + i / 1000, 6.0) for i in range(1000)]
    thin = geo.thin(line, 10)
    assert len(thin) == 10 and thin[0] == line[0] and thin[-1] == line[-1]
    west, south, east, north = geo.box((45.0, 6.0), 10_000)
    assert south < 45.0 < north and west < 6.0 < east and 0.08 < north - 45.0 < 0.1
    assert 390_000 < geo.distance_m((48.8566, 2.3522), (45.764, 4.8357)) < 395_000


def test_a_long_trip_is_routed_in_pieces_that_join(tmp_path):
    maps = FakeMaps()
    points = [(45.0 + i / 100, 6.0) for i in range(2 * ROUTE_POINTS_MAX + 5)]
    route = asyncio.run(geo.chain(maps, points, mode="pied", avoid=frozenset()))
    asked = [x[1] for x in maps.calls if x[0] == "route"]
    assert [len(x) for x in asked] == [ROUTE_POINTS_MAX, ROUTE_POINTS_MAX, 7]
    assert asked[1][0] == asked[0][-1] and asked[2][0] == asked[1][-1]  # chaque morceau repart du dernier point
    assert len(route.legs) == len(points) - 1 and route.distance_m == sum(x.distance_m for x in route.legs)
    with pytest.raises(ValueError):
        asyncio.run(geo.chain(maps, points[:1], mode="pied", avoid=frozenset()))


def test_her_tools_speak_the_modes_and_avoids_of_the_port():
    assert get_args(trips_tools.Mode) == MODES and get_args(trips_tools.Avoid) == AVOIDS


def test_here_read_for_a_route_that_fails_still_shows_its_bubble(tmp_path):
    """« Ici » lu, ses coordonnées parties vers le serveur d'itinéraires : même quand le trajet échoue, son message
    emporte la bulle 📍 — s'en servir est un regard (ADR 0195)."""
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        seq = await KernelPort(kernel).locate(ADRIEN, lat=45.8406, lon=6.2128, accuracy_m=10, label="Talloires",
                                              age_ms=0)
        maps.fail = "Le serveur d'itinéraires est très demandé."
        failed = await call(kernel, "route_plan", ADRIEN, points=["ici", "Annecy"])
        return seq, failed

    seq, failed = live(tmp_path, scenario, maps=maps)
    assert not failed.ok and "très demandé" in failed.content
    assert failed.attach == (location_c.note_ref(seq),)


def test_a_trip_shown_on_a_map_is_traced_as_it_travels(tmp_path):
    """Un voyage à pied, sans péage, montré dans son message : son tracé se calcule à pied, sans péage — comme le
    voyage se fait ; un mode demandé l'emporte."""
    maps = FakeMaps()

    async def scenario(kernel, deliveries):
        trip, _ = await trip_with_stops(kernel, ("Annecy", 45.8992, 6.1294, 1), ("Talloires", 45.8406, 6.2128, 1))
        await act(kernel, "trips.modifier", fixed={"trip": trip}, title="Le lac", start="2027-05-01", mode="pied",
                  avoid=["peages"])
        await call(kernel, "map_show", ADRIEN, title="À pied", trip=trip, route=True)
        await call(kernel, "map_show", ADRIEN, title="En vélo", trip=trip, route=True, mode="velo")
        return [x for x in maps.calls if x[0] == "route"], journal(kernel, c.SHOWN)

    routes, (walked, biked) = live(tmp_path, scenario, maps=maps)
    assert [(mode, avoid) for _, _pts, mode, avoid in routes] == [("pied", frozenset({"peages"})),
                                                                  ("velo", frozenset({"peages"}))]
    assert (walked.data.mode, biked.data.mode) == ("pied", "velo")


def test_her_tools_refuse_a_start_date_of_an_unreasonable_year(tmp_path):
    async def scenario(kernel, deliveries):
        return await call(kernel, "trip_create", ADRIEN, title="Un jour", start="9999-12-31")

    got = live(tmp_path, scenario, maps=FakeMaps())
    assert not got.ok and got.content == phrase("trips.tools.bad_date")


async def test_a_long_route_shape_is_decoded_outside_the_event_loop(monkeypatch):
    """Un long voyage fait des centaines de milliers de points : décodés dans un fil à part, ils ne figent ni le chat
    ni les autres requêtes ; un tracé court reste sur place."""
    threaded: list[str] = []
    real = asyncio.to_thread

    async def to_thread(fn, *args, **kwargs):
        threaded.append(fn.__name__)
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(geo.asyncio, "to_thread", to_thread)
    long_shape = encode_polyline6([(45.0 + i * 1e-4, 6.0 + i * 1e-4) for i in range(6_000)])
    short = RouteResult(10, 10, (RouteLeg(10, 10, encode_polyline6([(45.0, 6.0), (45.1, 6.1)])),))
    long = RouteResult(10, 10, (RouteLeg(10, 10, long_shape),))
    assert len(await geo.line_of_async(short)) == 2 and threaded == []
    assert len(await geo.line_of_async(long)) == 6_000 and threaded == ["line_of"]
