import { describe, expect, it } from "vitest";
import type { CarteInfo, Place, Trip, TripRoute } from "../../api/carte";
import { encodePolyline6 } from "../../map/polyline";
import {
  alongPlace,
  askAboutPlace,
  askAboutRoute,
  askAboutTrip,
  dayTitle,
  dropIndex,
  fileName,
  focusSelector,
  movedTrip,
  movedWords,
  noopMove,
  orderedStops,
  removedTrip,
  routableStops,
  routeGpx,
  stepMove,
  tripLines,
  tripRouteKey,
} from "./format";
import {
  explorerMarkup,
  itiKey,
  itineraryMarkup,
  mapPane,
  selectedPlace,
  typedPoint,
  tripEditorMarkup,
  tripsMarkup,
  type ExplorerView,
  type ItineraryView,
  type TripView,
} from "./view";

const NOW = new Date(2026, 10, 5, 14, 0).getTime();

const INFO: CarteInfo = {
  places: { ready: true, count: 120_000, built: 1 },
  addresses: { ready: true },
  routing: { ready: true, provider: "Valhalla (essai)", modes: ["voiture", "velo", "pied"], avoid: ["peages", "autoroutes", "ferries"] },
  categories: [{ id: "manger", label: "Manger" }, { id: "dormir", label: "Dormir" }, { id: "voir", label: "À voir" }],
};

function place(extra: Partial<Place> = {}): Place {
  return { id: "l3", name: "Camping de l'Horizon", kind: "camp_site", kind_fr: "Camping", category: "dormir", lat: 45.856, lon: 6.169,
    town: "Sévrier", distance_m: 5830, along_m: null, ...extra };
}

const TRIP: Trip = {
  id: "640", title: "Les Alpes en cinq jours", start: "2027-04-03", mode: "voiture", avoid: [], updated: 1, mika: true,
  days: [
    { n: 1, date: "2027-04-03", stops: [
      { id: "1", name: "Lille", kind: "Ta position", lat: 50.637, lon: 3.063, note: "", by: "toi" },
      { id: "2", name: "Reims", kind: "À voir", lat: 49.258, lon: 4.032, note: "le portail de l'ange", by: "mika" },
      { id: "3", name: "Dijon", kind: "Dormir", lat: 47.322, lon: 5.041, note: "", by: "toi" },
    ] },
    { n: 2, date: "2027-04-04", stops: [
      { id: "4", name: "Bourg-en-Bresse", kind: "", lat: 46.21, lon: 5.23, note: "", by: "mika" },
      { id: "5", name: "Annecy", kind: "", lat: 45.899, lon: 6.129, note: "", by: "toi" },
    ] },
  ],
};

const ROUTE: TripRoute = {
  days: [
    { n: 1, distance_m: 502_000, duration_s: 17_400, legs: [
      { from: "1", to: "2", distance_m: 207_000, duration_s: 8100, shape: encodePolyline6([[50.637, 3.063], [49.258, 4.032]]), steps: [] },
      { from: "2", to: "3", distance_m: 295_000, duration_s: 9300, shape: encodePolyline6([[49.258, 4.032], [47.322, 5.041]]), steps: [] },
    ] },
    { n: 2, distance_m: 268_000, duration_s: 10_200, legs: [
      { from: "3", to: "4", distance_m: 152_000, duration_s: 6000, shape: encodePolyline6([[47.322, 5.041], [46.21, 5.23]]), steps: [] },
      { from: "4", to: "5", distance_m: 116_000, duration_s: 4200, shape: encodePolyline6([[46.21, 5.23], [45.899, 6.129]]), steps: [] },
    ] },
  ],
  distance_m: 770_000, duration_s: 27_600, has_toll: true, has_highway: true, has_ferry: false, provider: "Valhalla (essai)",
};

describe("les arrêts d'un voyage", () => {
  it("se numérotent d'un bout à l'autre, et le titre d'un jour va de son premier à son dernier", () => {
    expect(orderedStops(TRIP).map((o) => [o.stop.id, o.day, o.n])).toEqual([["1", 1, 1], ["2", 1, 2], ["3", 1, 3], ["4", 2, 4], ["5", 2, 5]]);
    expect(dayTitle(TRIP.days[0].stops)).toBe("Lille → Dijon");
    expect(dayTitle([TRIP.days[0].stops[0]])).toBe("Lille");
  });

  it("glisser : la place parmi les autres arrêts du jour, comme l'API la lit", () => {
    expect(dropIndex(TRIP, "3", 1, "1")).toBe(0); // Dijon avant Lille
    expect(dropIndex(TRIP, "1", 1, "3")).toBe(1); // Lille avant Dijon : parmi Reims, Dijon
    expect(dropIndex(TRIP, "2", 2, null)).toBe(-1); // à la fin du jour 2
    const moved = movedTrip(TRIP, "1", 1, 1);
    expect(moved.days[0].stops.map((s) => s.id)).toEqual(["2", "1", "3"]);
    const across = movedTrip(TRIP, "5", 3, -1);
    expect(across.days.map((d) => d.stops.map((s) => s.id))).toEqual([["1", "2", "3"], ["4"], ["5"]]);
    const emptied = movedTrip({ ...TRIP, days: [TRIP.days[0], { n: 2, date: "", stops: [TRIP.days[1].stops[0]] }] }, "4", 1, -1);
    expect(emptied.days).toHaveLength(1); // un jour vidé à la fin disparaît
  });

  it("au clavier : une place plus haut ou plus bas, d'un jour à l'autre au bord", () => {
    expect(stepMove(TRIP, "2", -1)).toEqual([1, 0]);
    expect(stepMove(TRIP, "3", 1)).toEqual([2, 0]); // le dernier du jour 1 passe en tête du jour 2
    expect(stepMove(TRIP, "4", -1)).toEqual([1, -1]); // le premier du jour 2 passe à la fin du jour 1
    expect(stepMove(TRIP, "1", -1)).toBeNull();
    expect(stepMove(TRIP, "inconnu", 1)).toBeNull();
  });

  it("un lieu croisé le long du trajet s'ajoute avant l'arrêt qu'on atteint après lui", () => {
    expect(alongPlace(TRIP, ROUTE, 100_000)).toEqual([1, 1]); // entre Lille et Reims
    expect(alongPlace(TRIP, ROUTE, 600_000)).toEqual([2, 0]); // entre Dijon et Bourg
    expect(alongPlace(TRIP, ROUTE, 900_000)).toEqual([2, -1]); // après l'arrivée
    expect(alongPlace(TRIP, null, 50_000)).toEqual([1, 1]); // sans itinéraires : à vol d'oiseau
    expect(alongPlace(TRIP, ROUTE, null)).toEqual([2, -1]);
  });

  it("le tracé d'un voyage : ses tronçons calculés", () => {
    expect(tripLines(ROUTE)).toHaveLength(4);
    expect(tripLines(null)).toEqual([]);
  });

  it("une poignée lâchée où elle était (un tremblement) ne change rien : rien ne part", () => {
    expect(noopMove(TRIP, "2", 1, dropIndex(TRIP, "2", 1, "3"))).toBe(true); // Reims, devant Dijon : sa place
    expect(noopMove(TRIP, "2", 1, 1)).toBe(true);
    expect(noopMove(TRIP, "3", 1, -1)).toBe(true); // déjà le dernier du jour
    expect(noopMove(TRIP, "2", 1, 0)).toBe(false);
    expect(noopMove(TRIP, "3", 2, 0)).toBe(false); // au jour suivant
    expect(noopMove(TRIP, "5", 3, -1)).toBe(false); // un jour de plus
    expect(noopMove(TRIP, "inconnu", 1, 0)).toBe(true);
  });

  it("un arrêt retiré se montre de suite ; un déplacement au clavier se dit à un lecteur d'écran", () => {
    const without = removedTrip(TRIP, "4");
    expect(without.days.map((d) => d.stops.map((s) => s.id))).toEqual([["1", "2", "3"], ["5"]]);
    expect(removedTrip(without, "5").days).toHaveLength(1); // le dernier jour vidé s'en va
    expect(movedWords(TRIP, "2")).toBe("Reims : jour 1, arrêt 2 sur 3.");
    expect(movedWords(movedTrip(TRIP, "3", 2, 0), "3")).toBe("Dijon : jour 2, arrêt 1 sur 3.");
    expect(movedWords(TRIP, "inconnu")).toBe("");
  });

  it("le trajet dépend de l'ordre des arrêts, de leurs jours, du mode et de ce qu'il évite — pas d'une note ni du titre", () => {
    const key = tripRouteKey(TRIP);
    expect(tripRouteKey({ ...TRIP, title: "Autre", updated: 9 })).toBe(key);
    expect(tripRouteKey({ ...TRIP, days: TRIP.days.map((d) => ({ ...d, stops: d.stops.map((s) => ({ ...s, note: "réserver" })) })) })).toBe(key);
    expect(tripRouteKey(movedTrip(TRIP, "1", 1, 1))).not.toBe(key);
    expect(tripRouteKey(movedTrip(TRIP, "3", 2, 0))).not.toBe(key); // même ordre, un autre jour : ses tronçons changent de jour
    expect(tripRouteKey({ ...TRIP, mode: "velo" })).not.toBe(key);
    expect(tripRouteKey({ ...TRIP, avoid: ["peages"] })).not.toBe(key);
    expect(tripRouteKey({ ...TRIP, avoid: ["peages", "ferries"] })).toBe(tripRouteKey({ ...TRIP, avoid: ["ferries", "peages"] }));
    expect(routableStops(TRIP)).toBe(5);
    expect(routableStops({ ...TRIP, days: [{ n: 1, date: "", stops: [{ ...TRIP.days[0].stops[0], lat: null, lon: null }] }] })).toBe(0);
  });
});

describe("la main d'un dessin à l'autre", () => {
  it("le contrôle qui l'avait se retrouve par ses attributs (une catégorie, une poignée, un champ, une case)", () => {
    expect(focusSelector({ cat: "dormir" })).toBe('[data-cat="dormir"]');
    expect(focusSelector({ grip: "642" })).toBe('[data-grip="642"]');
    expect(focusSelector({ pt: "0" })).toBe('[data-pt="0"]');
    expect(focusSelector({ itiSwap: "" })).toBe("[data-iti-swap]");
    expect(focusSelector({ avoid: "peages" })).toBe('[data-avoid="peages"]');
    expect(focusSelector({ onroute: 'a"b\\c' })).toBe('[data-onroute="a\\"b\\\\c"]');
    expect(focusSelector({ stop: "3" })).toBeNull(); // pas un contrôle
    expect(focusSelector({})).toBeNull();
  });
});

describe("pour Mika", () => {
  it("les phrases préremplies du chat", () => {
    expect(askAboutPlace(place())).toBe("Tu connais « Camping de l'Horizon » (Camping, Sévrier) ? ");
    expect(askAboutTrip(TRIP)).toBe("Tu peux m'aider à préparer notre voyage « Les Alpes en cinq jours » ? ");
    expect(askAboutRoute(["Lille", "Annecy"], { distance_m: 751_000, duration_s: 25_500 }, "voiture"))
      .toBe("Regarde ce trajet : Lille → Annecy (7 h 05, 751 km en voiture). ");
  });
});

describe("le GPX d'un itinéraire", () => {
  it("ses points en route, son tracé en trace, ses noms échappés", () => {
    const gpx = routeGpx("Lille → <Annecy>", [{ name: "Lille", lat: 50.637, lon: 3.063 }, { name: "A & B", lat: 45.899, lon: 6.129 }],
      [[50.637, 3.063], [48, 4.5], [45.899, 6.129]]);
    expect(gpx).toContain('<gpx version="1.1"');
    expect(gpx).toContain("<name>Lille → &lt;Annecy&gt;</name>");
    expect(gpx).toContain('<rtept lat="45.899000" lon="6.129000"><name>A &amp; B</name></rtept>');
    expect(gpx.match(/<trkpt /g)).toHaveLength(3);
    expect(routeGpx("x", [], [])).not.toContain("<trk>");
    expect(fileName("Lille → Annecy", "gpx")).toBe("Lille-Annecy.gpx");
    expect(fileName("", "gpx")).toBe("itineraire.gpx");
  });
});

function explorer(extra: Partial<ExplorerView> = {}): ExplorerView {
  return { info: INFO, q: "camping", cat: "dormir", where: "moi", places: [place(), place({ id: "l4", name: "La Chèvrerie <" })], addresses: [],
    error: "", addrError: "", loading: false, searched: true, sel: null, regard: null, hint: "", map: "", ...extra };
}

describe("Explorer", () => {
  it("la recherche, les catégories du serveur, où chercher ; les lieux, échappés, et leur distance", () => {
    const html = explorerMarkup(explorer());
    expect(html).toContain('placeholder="Un lieu, une adresse, un restaurant…"');
    expect(html).toContain('<button type="button" class="cat on" data-cat="dormir" aria-pressed="true">Dormir</button>');
    expect(html).toContain('aria-pressed="true" data-where="moi"');
    expect(html).toContain("Autour de moi");
    expect(html).toContain("Dans cette zone");
    expect(html).toContain("Dormir · camping");
    expect(html).toContain("index local, rien ne sort");
    expect(html).toContain("La Chèvrerie &lt;");
    expect(html).toContain("5,8 km");
    expect(html).not.toContain("data-place-card"); // rien de choisi
  });

  it("la fiche d'un lieu : itinéraire jusqu'ici, ajouter au voyage, en parler à Mika", () => {
    const v = explorer({ sel: "l3" });
    expect(selectedPlace(v)?.name).toBe("Camping de l'Horizon");
    const html = explorerMarkup(v);
    expect(html).toContain("data-place-card");
    expect(html).toContain("Itinéraire jusqu'ici");
    expect(html).toContain("Ajouter au voyage");
    expect(html).toContain("En parler à Mika");
    expect(html).toContain("à 5,8 km de toi");
  });

  it("sans index : le message du serveur, et les adresses restent", () => {
    const html = explorerMarkup(explorer({ places: [], error: "La recherche de lieux n'est pas encore prête sur ce serveur.",
      addresses: [place({ id: "a:1", name: "12 Rue Royale 74000 Annecy", category: "adresse", kind_fr: "" })] }));
    expect(html).toContain("La recherche de lieux n&#39;est pas encore prête sur ce serveur.");
    expect(html).toContain("12 Rue Royale 74000 Annecy");
    expect(html).toContain("Géoplateforme (IGN), seul le texte part");
  });

  it("ce que Mika a cherché : ses lieux en rose, « Mika te l'a proposé »", () => {
    const html = explorerMarkup(explorer({ regard: { title: "Dormir · près de Talloires", route: false, links: [] } }));
    expect(html).toContain("Ce que Mika a cherché");
    expect(html).toContain('class="li place by-mika"');
    expect(html).toContain("Mika te l'a proposé");
  });
});

function iti(extra: Partial<ItineraryView> = {}): ItineraryView {
  return {
    points: [{ query: "Ma position · rue Nationale, Lille", name: "Ma position", lat: 50.637, lon: 3.063 }, { query: "Annecy", name: "Annecy", lat: 45.899, lon: 6.129 }],
    mode: "voiture", avoid: [], route: null, stale: false, error: "", loading: false, suggestFor: null, suggestions: [], regard: null, now: NOW, map: "", ...extra,
  };
}

describe("Itinéraire", () => {
  it("ses points (A, B), son mode, ce qu'il évite ; la durée, la distance, les consignes, d'où il vient", () => {
    const route = { distance_m: 751_000, duration_s: 25_500, has_toll: true, has_highway: true, has_ferry: false, provider: "FOSSGIS (Valhalla)",
      legs: [{ distance_m: 751_000, duration_s: 25_500, shape: "", steps: [{ text: "Prendre l'A1 vers <Paris>", distance_m: 46_000, duration_s: 1500 }] }] };
    const html = itineraryMarkup(iti({ route }));
    expect(html).toContain('<span class="iti-dot a">A</span>');
    expect(html).toContain('<span class="iti-dot b">B</span>');
    expect(html).toContain('aria-pressed="true" data-mode="voiture">Voiture</button>');
    expect(html).toContain("Éviter les péages");
    expect(html).toContain("<b>7 h 05</b><span>751 km</span>");
    expect(html).toContain("en voiture, avec péages");
    expect(html).toContain("arrivée vers");
    expect(html).toContain("Prendre l&#39;A1 vers &lt;Paris&gt;");
    expect(html).toContain("En faire un voyage");
    expect(html).toContain("GPX");
    expect(html).toContain("Envoyer à Mika");
    expect(html).toContain("Calculé par FOSSGIS (Valhalla), relayé par ce serveur");
  });

  it("sans itinéraires : le message du serveur", () => {
    const html = itineraryMarkup(iti({ error: "Les itinéraires ne sont pas encore prêts sur ce serveur." }));
    expect(html).toContain("Les itinéraires ne sont pas encore prêts sur ce serveur.");
    expect(html).not.toContain("En faire un voyage");
  });

  it("un point retapé : le trajet d'avant est passé — ni consignes, ni GPX, ni « En faire un voyage » avant de le choisir", () => {
    const route = { distance_m: 751_000, duration_s: 25_500, has_toll: false, has_highway: true, has_ferry: false, provider: "FOSSGIS (Valhalla)",
      legs: [{ distance_m: 751_000, duration_s: 25_500, shape: "", steps: [{ text: "Prendre l'A1", distance_m: 46_000, duration_s: 1500 }] }] };
    const points = [{ query: "Lille", name: "Lille", lat: 50.637, lon: 3.063 }, { query: "Anne", name: "", lat: null, lon: null }];
    expect(typedPoint(points)).toBe(true);
    expect(typedPoint([points[0], { query: "", name: "", lat: null, lon: null }])).toBe(false); // une étape vide n'attend rien
    const fresh = itineraryMarkup(iti({ route }));
    expect(fresh).toContain("Prendre l&#39;A1");
    expect(fresh).not.toMatch(/data-iti-trip disabled|data-iti-gpx disabled/);
    const stale = itineraryMarkup(iti({ route, stale: true, points: [...iti().points.slice(0, 1), points[1], iti().points[1]] }));
    expect(stale).toContain('class="iti-res stale"');
    expect(stale).toContain("data-iti-trip disabled");
    expect(stale).toContain("data-iti-gpx disabled");
    expect(stale).not.toContain("Prendre l&#39;A1");
    expect(stale).toContain("Choisis chaque point dans ses propositions");
  });

  it("ce qui fait un itinéraire : ses points choisis, son mode, ce qu'il évite en voiture", () => {
    const pts = iti().points;
    const key = itiKey(pts, "voiture", ["peages"]);
    expect(itiKey(pts, "voiture", ["peages"])).toBe(key);
    expect(itiKey([...pts].reverse(), "voiture", ["peages"])).not.toBe(key);
    expect(itiKey(pts, "voiture", [])).not.toBe(key);
    expect(itiKey(pts, "velo", ["peages"])).toBe(itiKey(pts, "velo", [])); // à vélo, rien à éviter
    expect(itiKey([pts[0], { query: "", name: "", lat: null, lon: null }, pts[1]], "voiture", ["peages"])).toBe(key);
  });

  it("le trajet de Mika, tel qu'elle l'a gardé : son résumé, et de quoi en faire un voyage ou le recalculer", () => {
    const html = itineraryMarkup(iti({ regard: { title: "Lille → Annecy", distance_m: 751_000, duration_s: 25_500 } }));
    expect(html).toContain('class="iti-res mika"');
    expect(html).toContain("Ce que Mika a calculé : Lille → Annecy");
    expect(html).toContain("751 km");
    expect(html).toContain("data-iti-trip");
    expect(html).toContain("data-iti-gpx");
    expect(html).toContain("data-iti-compute");
    expect(html).not.toContain("Consignes");
  });

  it("des adresses refusées (trop demandées) : les propositions le disent", () => {
    const html = itineraryMarkup(iti({ suggestFor: 1, suggestions: [{ label: "Annecy", sub: "Ville" }],
      suggestNote: "Trop de trajets ou d'adresses demandés d'affilée : attends une minute." }));
    expect(html).toContain('data-pick="1:0"');
    expect(html).toContain("Adresses : Trop de trajets ou d&#39;adresses demandés d&#39;affilée : attends une minute.");
    const alone = itineraryMarkup(iti({ suggestFor: 1, suggestions: [], suggestNote: "Les adresses ne sont pas branchées." }));
    expect(alone).toContain("Adresses : Les adresses ne sont pas branchées.");
    expect(alone).not.toContain('role="listbox"');
  });

  it("à vélo, les options de la voiture ne se cochent pas", () => {
    const html = itineraryMarkup(iti({ mode: "velo" }));
    expect(html).toContain('data-avoid="peages" disabled');
    expect(html).toContain("À vélo, le trajet évite d&#39;office péages et autoroutes.");
  });
});

function tripView(extra: Partial<TripView> = {}): TripView {
  return { trip: TRIP, route: ROUTE, routeError: "", onRoute: { cat: "", places: [], error: "", loading: false, routed: true }, info: INFO, now: NOW, map: "", ...extra };
}

describe("Voyages", () => {
  it("la liste : chaque voyage en carte (sa miniature, ses dates, ses étiquettes), et « Nouveau voyage »", () => {
    const html = tripsMarkup([{ id: "640", title: "Les Alpes en cinq jours", start: "2027-04-03", mode: "voiture", avoid: [], days: 5, stops: 12, updated: 1, mika: true },
      { id: "700", title: "La Bretagne", start: "2026-08-02", mode: "voiture", avoid: [], days: 8, stops: 9, updated: 1, mika: false }], () => null, NOW);
    expect(html).toContain('href="#carte/voyages/640"');
    expect(html).toContain('data-mini="voyages|trip:640"');
    expect(html).toContain("du sam. 3 au mer. 7 avril 2027");
    expect(html).toContain("préparé avec Mika");
    expect(html).toContain('class="trip-card passe"');
    expect(html).toContain("Nouveau voyage");
    expect(html).toContain("ou demande-le à Mika dans le chat");
  });

  it("l'éditeur : jour par jour, les tronçons, ses arrêts en rose et retirables, glisser pour réordonner", () => {
    const html = tripEditorMarkup(tripView());
    expect(html).toContain("Jour 1 · Lille → Dijon");
    expect(html).toContain("sam. 3 avril 2027 · 502 km · 4 h 50");
    expect(html).toContain("2 h 15 · 207 km"); // le tronçon qui arrive à Reims
    expect(html).toContain('class="stop by-mika" data-stop="2" data-day="1"');
    expect(html).toContain("ajouté par Mika : « le portail de l&#39;ange »");
    expect(html).toContain('data-retirer="2"');
    expect(html).toContain('data-grip="1"');
    expect(html).toContain("Glisser pour changer l'ordre");
    expect(html).toContain("770 km");
    expect(html).toContain("préparé avec Mika");
    expect(html).toContain("Sur la route");
    expect(html).toContain("Ajouter un jour");
  });

  it("sans itinéraires : le message du serveur, les arrêts restent", () => {
    const html = tripEditorMarkup(tripView({ route: null, routeError: "Les itinéraires ne sont pas encore prêts sur ce serveur." }));
    expect(html).toContain("Les itinéraires ne sont pas encore prêts sur ce serveur.");
    expect(html).toContain("Jour 2 · Bourg-en-Bresse → Annecy");
    expect(html).not.toContain('class="leg"');
  });

  it("ses arrêts changés : le trajet d'avant ne se montre pas, il se calcule", () => {
    const html = tripEditorMarkup(tripView({ route: null, routePending: true }));
    expect(html).toContain("Le trajet se calcule…");
    expect(html).not.toContain('class="leg"');
    expect(html).not.toContain("770 km");
    expect(tripEditorMarkup(tripView({ route: null, routePending: true, routeError: "Trop de demandes." }))).not.toContain("Le trajet se calcule");
  });

  it("la miniature d'un voyage de la liste se demande avec sa carte (son dernier changement)", () => {
    const seen: Array<[string, number]> = [];
    tripsMarkup([{ id: "640", title: "Les Alpes", start: "", mode: "voiture", avoid: [], days: 1, stops: 2, updated: 77, mika: false }],
      (t) => {
        seen.push([t.id, t.updated]);
        return null;
      }, NOW);
    expect(seen).toEqual([["640", 77]]);
  });

  it("un lieu du trajet qui s'ajoute : son bouton attend (un double clic ne l'ajoute qu'une fois)", () => {
    const onRoute = { cat: "voir", places: [place({ along_m: 600_000 }), place({ id: "l9", along_m: 100_000 })], error: "", loading: false, routed: true, sending: 0 };
    const html = tripEditorMarkup(tripView({ onRoute }));
    expect(html).toContain('data-add-along="0" disabled');
    expect(html).not.toContain('data-add-along="1" disabled');
  });

  it("sur la route : les lieux du trajet, à ajouter", () => {
    const html = tripEditorMarkup(tripView({ onRoute: { cat: "voir", places: [place({ name: "Monastère royal de Brou", kind_fr: "Monument", distance_m: 2500, along_m: 600_000 })], error: "", loading: false, routed: true } }));
    expect(html).toContain('class="cat on" data-onroute="voir"');
    expect(html).toContain("Monastère royal de Brou");
    expect(html).toContain("à 2,5 km de la route");
    expect(html).toContain('data-add-along="0"');
  });
});

describe("le cadre de la carte", () => {
  it("la vraie carte se pose dans son cadre ; sinon le plan dessiné dit pourquoi", () => {
    expect(mapPane({ live: true, scene: { pins: [], lines: [] }, title: "Carte", why: "" })).toContain("data-carte-map");
    const drawn = mapPane({ live: false, scene: { pins: [{ id: "a", lat: 45.9, lon: 6.1, label: "1" }], lines: [] }, title: "Carte", why: "aucune carte n'est réglée." });
    expect(drawn).not.toContain("data-carte-map");
    expect(drawn).toContain("drawn-map");
    expect(drawn).toContain("Un plan dessiné, pas une carte : aucune carte n&#39;est réglée.");
  });
});
