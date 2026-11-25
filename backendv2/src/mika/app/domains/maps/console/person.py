"""La part de la carte dans la fiche d'une personne (ADR 0310) : Voyages, Sa position, le GPX d'un voyage.

**Voyages** (ADR 0195, 0204) : ses voyages, du plus récemment changé — chacun son
titre, comment on s'y déplace, s'il a été préparé avec elle, son départ, ce qu'il évite ; ses arrêts jour par jour,
repliés (ce qu'elle y a ajouté se dit, sous son nom) ; son GPX ; « Supprimer » (l'action ``trips.supprimer``,
confirmée, auditée), le seul geste de la console sur un voyage : il se prépare à deux.

Lu par ``plugins/trips/inspect.py::read`` (la tranche du plugin, ses textes au magasin), comme la vue du plugin, qui
reste la source de la console en MCP et du repli ; les formulaires sont ceux que la console prépare (``Forms.of``),
la personne de la fiche pour objet. Le GPX se sert ici (``gpx``, opérateurs seulement) : le même document que l'écran
Carte donne à la personne (``app/domains/maps/api.py::gpx_document``), dans la même borne, celle du compte de
l'opérateur.

**Sa position** (ADR 0119, 0123) : sa dernière position, téléphone par téléphone, et son journal — les mêmes
morceaux que Ses sens › Localisation (``app/domains/senses/console/tabs.py``), restreints à cette personne.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from markupsafe import Markup
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.web.gate import SlidingWindow
from mika.app.domains.domain import PersonPart
from mika.app.domains.maps.api import gpx_document, gpx_response
from mika.app.domains.senses.console.tabs import fix_of, said_of, slice_of
from mika.app.handmade import Look
from mika.app.handmade.person.common import Who, _slice
from mika.app.me import ROUTES_BUSY, spend
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, Forms, env, secure
from mika.kernel.clock import DAY
from mika.kernel.inspect import ActionSlot
from mika.plugins.location.inspect import by_person
from mika.plugins.trips import TRIPS, TripsState, trips_of
from mika.plugins.trips.inspect import REMOVE, TripSeen, avoid_words, day_words, mode_words, read

#: où la console sert le GPX d'un voyage : ``/admin/voyages/<id>/gpx``
GPX = f"{PREFIX}/voyages"
GONE = "Ce voyage n'existe plus : supprimé, ou sa personne oubliée."


def gpx_url(trip: str) -> str:
    return f"{GPX}/{quote(trip, safe='')}/gpx"


def _state(look: Look) -> TripsState | None:
    try:
        return look.frame.state(TRIPS.name)
    except KeyError:  # le plugin n'est pas composé ici
        return None


def _count(n: int, none: str, one: str, many: str) -> str:
    return none if n == 0 else one if n == 1 else f"{n} {many}"


def _removals(ui: UI, key: str, trips: Sequence[TripSeen], query: Mapping[str, str],
              forms: Any) -> dict[str, dict[str, Any]]:
    """Le formulaire « Supprimer » de chaque voyage, préparé par la console comme ceux de ses blocs : son jeton, son
    retour, la personne de la fiche pour objet (``_sujet`` : ce que ``trips.supprimer`` exige d'un opérateur). Sans
    formulaires (un rendu hors d'une page), aucun."""
    if not isinstance(forms, Forms) or not trips:
        return {}
    slots = render.blocks([ActionSlot(REMOVE, initial=(("trip", t.id),)) for t in trips], ui.env(), query)
    prepared = forms.of(slots, key)
    return {str(x["initial"]["trip"]): prepared[x["slot"]] for x in slots if x["slot"] in prepared}


def voyages(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
            forms: Mapping[str, Any] | None = None) -> Markup | None:
    """La fiche d'une personne › Voyages : chacun, ses arrêts jour par jour, son GPX, « Supprimer »."""
    look = Look.of(ui, DAY)
    s = _state(look)
    if s is None:
        return None
    trips = read(s, look.frame.get, look.texts, key)
    name, her = look.name(key), ui.her_name()
    removal = _removals(ui, key, trips, query, forms)
    shown = []
    for t in trips:
        stops = _count(t.stops, "aucun arrêt", "un arrêt", "arrêts")
        form = removal.get(t.id)
        if form is not None:
            form = {**form, "title": "Supprimer", "button": "Supprimer",
                    "confirm": f"Supprimer « {t.title} » ({stops}) ? {name} ne le retrouvera plus.",
                    # le dernier supprimé, l'onglet n'a plus lieu d'être : la fiche s'ouvre sur sa vue d'ensemble
                    **({"back": subject_url("person", key)} if len(trips) == 1 else {})}
        shown.append({
            "id": t.id, "title": t.title, "mode": mode_words(t.mode), "with_her": t.with_her,
            "start": day_words(t.start), "avoid": avoid_words(t.avoid), "stops": stops,
            "days": _count(len(t.days), "aucun jour", "un jour", "jours"), "changed": look.ago(t.updated),
            "created": look.ago(t.created), "journal": f"{PREFIX}/evenement/{t.id}",
            # un GPX sans arrêt n'aurait rien à suivre
            "gpx": gpx_url(t.id) if t.stops else "", "remove": form,
            "itinerary": [{"n": d.n, "date": day_words(d.date),
                           "stops": [{"name": x.name, "kind": x.kind, "note": x.note, "coords": x.coords,
                                      "hers": x.hers} for x in d.stops]} for d in t.days]})
    return Markup(env.get_template("handmade/person/tabs/voyages.html").render(trips=shown, name=name, her=her))


class _Busy(Exception):
    """Le compte de l'opérateur a demandé assez de trajets pour la minute (``OUTBOUND``)."""


async def gpx(ui: UI, request: Request, outbound: SlidingWindow) -> Response:
    """Le GPX d'un voyage, pour un opérateur (ADR 0204) : ses arrêts, et le tracé quand les itinéraires le calculent.
    Le tracé use la borne de son compte, celle de l'écran Carte (``outbound`` : ``MeApi.outbound``) — 429 au-delà, le
    serveur d'itinéraires public est à tous. Un voyage qui n'est plus là : 404."""
    who = ui.operator(request)
    if who is None:  # sa session s'est fermée depuis que ``ui.guarded`` l'a vue : rien ne part
        return secure(RedirectResponse(f"{PREFIX}/connexion", status_code=303))
    look = Look.of(ui, DAY)
    s = _state(look)
    trip = s.trips.get(str(request.path_params["trip"])) if s is not None else None
    if trip is None:
        return secure(PlainTextResponse(GONE, status_code=404))

    def counted() -> None:
        if not spend(outbound, who):
            raise _Busy

    try:
        body = await gpx_document(ui.kernel.ports.get("maps"), trip, look.texts, counted)
    except _Busy:
        return secure(PlainTextResponse(ROUTES_BUSY, status_code=429))
    return secure(gpx_response(trip, body))


def position_tab(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """La fiche d'une personne › Sa position : sa dernière position, téléphone par téléphone, et son journal."""
    look = Look.of(ui, DAY)
    s = slice_of(look, "location")
    if s is None:
        return None
    fixes = by_person(s).get(key, [])
    texts = look.texts([r for f in fixes for r in (f.coords_ref, f.label_ref)])
    said = said_of(look, query, key, subject_url("person", key, "position"))
    return Markup(env.get_template("handmade/person/tabs/position.html").render(
        fixes=[fix_of(look, f, texts) for f in fixes], said=said, name=look.name(key)))


def count(look: Look, who: Who) -> int:
    """Le compte de l'onglet Voyages (``PersonOverview.counts``) : ses voyages."""
    return len(trips_of(_slice(look, TRIPS.name), look.frame.get, who.person))


def routes(ui: UI, outbound: SlidingWindow) -> list[Route]:
    """Sa route sous la fiche d'une personne : le GPX d'un voyage, dans la borne que la fiche reçoit et lui passe
    (``outbound`` : celle de l'écran Carte, ou une à la console seule aux mêmes nombres, ``PersonOverview.routes``)."""

    async def served(request: Request) -> Response:
        return await gpx(ui, request, outbound)

    # le GPX d'un voyage, depuis son onglet (ADR 0204)
    return [Route(GPX + "/{trip:int}/gpx", ui.guarded(served), methods=["GET"])]


#: sa part de la fiche d'une personne (ADR 0310)
PERSON_PART = PersonPart(
    # où son téléphone dit qu'elle est (seulement s'il en a dit quelque chose) ;
    # ses voyages (seulement si elle en a) : leurs arrêts jour par jour, leur GPX, « Supprimer » (ADR 0204)
    tabs={"voyages": voyages, "position": position_tab}, formed=("voyages",), counts={"voyages": count},
    routes=routes)
