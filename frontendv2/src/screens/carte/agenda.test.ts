import { describe, expect, it } from "vitest";
import type { CarteInfo, EventItem, Place } from "../../api/carte";
import { ApiError } from "../../api/moi";
import {
  askAboutEvent,
  dayHeading,
  eventDays,
  eventsLegend,
  eventsMarkup,
  eventTripDay,
  whenInDay,
  whenRange,
  type EventsView,
} from "./agenda";
import { cuisineChoices, ficheId, focusSelector, lieuItem, lieuOf } from "./format";
import { explorerMarkup, filtersMarkup, filtersOn, NO_FILTERS, placeItem, type ExplorerView } from "./view";

/** Le vendredi 20 novembre 2026, 23:00 (heure locale). */
const NOW = new Date(2026, 10, 20, 23, 0).getTime();
const never = () => false;

const INFO: CarteInfo = {
  places: { ready: true, count: 35725, built: 1 }, addresses: { ready: true },
  routing: { ready: true, provider: "FOSSGIS (Valhalla)", modes: ["voiture"], avoid: [] },
  categories: [{ id: "manger", label: "Manger" }, { id: "dormir", label: "Dormir" }],
  tourism: { ready: true, places: 262, events: 190, synced: 0 },
  features: [{ id: "terrasse", label: "Terrasse" }, { id: "vegetarien", label: "Végétarien" }, { id: "vegan", label: "Vegan" }, { id: "accessible", label: "Accessible" }],
  sorts: [{ id: "distance", label: "Les plus proches" }, { id: "rating", label: "Les mieux notés" }],
  themes: [{ id: "concerts", label: "Concerts" }, { id: "spectacles", label: "Spectacles" }, { id: "expositions", label: "Expositions" }, { id: "marches", label: "Marchés" }],
};

function ev(extra: Partial<EventItem> = {}): EventItem {
  return { id: "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name: "Éclats du rire !", start: "2026-11-21T19:00:00+01:00", end: "2026-11-21T22:00:00+01:00",
    when_text: "sam. 21 nov. · 19:00–22:00", place: "L'Aéronef, Lille", lat: 50.636554, lon: 3.074244, distance_m: 780, themes: ["spectacles"],
    free: false, price: "12/8€ - Gratuit moins de 18 ans", photo: "", ...extra };
}

const MARCHE = ev({ id: "e:9e2c421b-3db0-4c6e-8f1a-2b3c4d5e6f70", name: "Marché du Vieux-Lille", start: "2026-11-22T07:00:00+01:00",
  when_text: "07:00–14:00 · jusqu'au 31 déc.", place: "Place du Concert, Lille", themes: ["marches"], free: null, price: "" });
const JAZZ = ev({ id: "e:75f845e6-1dc0-4a1b-9c2d-3e4f5a6b7c8d", name: "ÇA JAZZ !", start: "2026-11-21T13:30:00+01:00",
  when_text: "sam., dim. · 13:30–18:00", place: "Maison Folie Hospice d’Havré, Tourcoing", themes: ["concerts"], free: true, price: "gratuit", distance_m: 11_800 });

function events(extra: Partial<EventsView> = {}): EventsView {
  return { info: INFO, q: "", when: "week", dates: { start: "", end: "" }, themes: [], free: false, where: "moi", events: [JAZZ, ev(), MARCHE],
    coverage: { ready: true, cells: 11, loaded: 3, oldest: 1, note: "Cette zone n'est lue qu'en partie (cases lues : 3 sur 11) : la suite se lit à la prochaine recherche, ou ce soir." },
    error: "", loading: false, searched: true, sel: null, hint: "", regard: null, fiche: "", seen: never, now: NOW, map: "", ...extra };
}

describe("Événements : quand", () => {
  it("aujourd'hui, ce week-end, cette semaine (jusqu'au dimanche), des dates remises dans l'ordre", () => {
    // le vendredi 20 novembre 2026
    expect(whenRange("today", NOW)).toEqual({ start: "2026-11-20", end: "2026-11-20" });
    expect(whenRange("weekend", NOW)).toEqual({ start: "2026-11-21", end: "2026-11-22" });
    expect(whenRange("week", NOW)).toEqual({ start: "2026-11-20", end: "2026-11-22" });
    expect(whenRange("dates", NOW, { start: "2026-12-05", end: "2026-12-01" })).toEqual({ start: "2026-12-01", end: "2026-12-05" });
    expect(whenRange("dates", NOW, { start: "2026-12-05", end: "" })).toEqual({ start: "2026-12-05", end: "2026-12-05" });
    expect(whenRange("dates", NOW, { start: "n'importe", end: "quoi" })).toEqual({ start: "2026-11-20", end: "2026-11-26" });
  });

  it("un samedi, le week-end est lui et demain ; un dimanche, lui seul, et la semaine est celle qui vient", () => {
    const saturday = new Date(2026, 10, 21, 10).getTime();
    const sunday = new Date(2026, 10, 22, 10).getTime();
    expect(whenRange("weekend", saturday)).toEqual({ start: "2026-11-21", end: "2026-11-22" });
    expect(whenRange("weekend", sunday)).toEqual({ start: "2026-11-22", end: "2026-11-22" });
    expect(whenRange("week", sunday)).toEqual({ start: "2026-11-22", end: "2026-11-29" });
  });
});

describe("Événements : les jours", () => {
  it("groupés par jour, les jours dans l'ordre, chacun dans l'ordre du serveur", () => {
    const groups = eventDays([JAZZ, ev(), MARCHE], NOW);
    expect(groups.map((g) => g.day)).toEqual(["2026-11-21", "2026-11-22"]);
    expect(groups[0].events.map((e) => e.name)).toEqual(["ÇA JAZZ !", "Éclats du rire !"]);
    expect(groups[0].title).toBe("Demain · samedi 21 novembre");
    expect(groups[1].title).toBe("Dimanche 22 novembre");
    // une date illisible : à la fin
    expect(eventDays([ev({ start: "bientôt" }), ev()], NOW).map((g) => g.day)).toEqual(["2026-11-21", ""]);
  });

  it("la tête d'un jour ; son quand sans le jour qu'elle dit déjà", () => {
    expect(dayHeading("2026-11-20", NOW)).toBe("Aujourd'hui · vendredi 20 novembre");
    expect(dayHeading("2026-12-01", NOW)).toBe("Mardi 1er décembre");
    expect(dayHeading("2027-01-04", NOW)).toBe("Lundi 4 janvier 2027");
    expect(whenInDay(ev())).toBe("19:00–22:00");
    expect(whenInDay(MARCHE)).toBe("07:00–14:00 · jusqu'au 31 déc.");
  });

  it("le jour d'un voyage où il tombe ; hors du voyage ou sans date, le dernier jour", () => {
    expect(eventTripDay({ start: "2026-11-20", days: 3 }, ev())).toBe(2);
    expect(eventTripDay({ start: "2026-11-20", days: 1 }, ev())).toBe(-1);
    expect(eventTripDay({ start: "", days: 3 }, ev())).toBe(-1);
    expect(eventTripDay({ start: "2026-11-22", days: 3 }, ev())).toBe(-1);
  });

  it("la phrase pour Mika", () => {
    expect(askAboutEvent(ev())).toBe("Tu as vu « Éclats du rire ! » (sam. 21 nov. · 19:00–22:00, L'Aéronef, Lille) ? ");
  });
});

describe("Événements : l'onglet", () => {
  it("quand, quoi (les thèmes du serveur, gratuit), où ; la couverture ; la liste par jour, ses prix et ses distances", () => {
    const html = eventsMarkup(events({ themes: ["concerts"], free: true }));
    expect(html).toContain('placeholder="Un concert, un marché, une fête…"');
    expect(html).toContain('class="cat on" data-when="week" aria-pressed="true">Cette semaine');
    expect(html).toContain('data-when="weekend"');
    expect(html).toContain('class="cat on" data-theme="concerts" aria-pressed="true">Concerts');
    expect(html).toContain('data-theme="marches"');
    expect(html).toContain('class="cat on" data-free="1" aria-pressed="true">Gratuit');
    expect(html).toContain('aria-pressed="true" data-ev-where="moi"');
    expect(html).toContain("Cette zone n&#39;est lue qu&#39;en partie (cases lues : 3 sur 11)");
    expect(html.indexOf("Demain · samedi 21 novembre")).toBeLessThan(html.indexOf("Dimanche 22 novembre"));
    expect(html).toContain("Concerts · sam., dim. · 13:30–18:00 · Maison Folie Hospice d’Havré, Tourcoing");
    expect(html).toContain("Gratuit"); // ÇA JAZZ !
    expect(html).toContain("12 km");
    expect(html).toContain("Spectacles · 19:00–22:00 · L&#39;Aéronef, Lille");
    expect(html).toContain("12/8€ - Gratuit moins de 18 ans");
    expect(html).toContain('data-ev="e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41"');
    expect(html).toContain("DATAtourisme (Licence Ouverte)");
    expect(html).not.toContain("data-ev-start"); // pas de dates à choisir
  });

  it("« Des dates… » : deux champs ; un nom du dehors reste du texte", () => {
    const html = eventsMarkup(events({ when: "dates", dates: { start: "2026-12-01", end: "2026-12-05" },
      events: [ev({ name: "<script>alert(1)</script>", place: '<img src=x onerror="alert(2)">' })] }));
    expect(html).toContain('data-ev-start value="2026-12-01"');
    expect(html).toContain('data-ev-end value="2026-12-05"');
    expect(html).not.toContain("<script>");
    expect(html).not.toContain('onerror="');
  });

  it("rien, une panne, pas encore cherché, ce que Mika a trouvé (en rose), la fiche à la place de la liste", () => {
    expect(eventsMarkup(events({ events: [] }))).toContain("Rien de prévu autour de toi à ces dates.");
    expect(eventsMarkup(events({ error: "Trop de fiches et d'événements demandés d'affilée : attends une minute." })))
      .toContain("Trop de fiches et d&#39;événements demandés d&#39;affilée : attends une minute.");
    expect(eventsMarkup(events({ searched: false, events: [] }))).toContain("Ce qui se passe autour");
    const hers = eventsMarkup(events({ regard: { title: "Concerts ce week-end" }, coverage: null }));
    expect(hers).toContain("Concerts ce week-end");
    expect(hers).toContain("repéré par Mika");
    expect(hers).toContain("by-mika");
    expect(hers).not.toContain("data-evq"); // ce qu'elle a trouvé, sans la recherche
    expect(hers).toContain('href="#carte/evenements"');
    const gone = eventsMarkup(events({ regard: null, regardError: new ApiError(404, "Introuvable."), regardGone: true }));
    expect(gone).toContain("Ce que Mika avait trouvé n&#39;est plus là");
    const fiche = eventsMarkup(events({ fiche: '<div class="fiche">la fiche</div>' }));
    expect(fiche).toContain("la fiche");
    expect(fiche).not.toContain("data-evq");
  });

  it("la légende de la carte", () => {
    expect(eventsLegend({ events: [ev()], where: "moi", regard: null, searched: true })).toContain("1 événement · autour de ta position");
    expect(eventsLegend({ events: [], where: "moi", regard: null, searched: false })).toBe("");
  });
});

function place(extra: Partial<Place> = {}): Place {
  return { id: "l22871", name: "Magmatic", kind: "restaurant", kind_fr: "Restaurant", category: "manger", lat: 50.63712, lon: 3.06455, town: "Lille",
    distance_m: 240, along_m: null, ...extra };
}

function explorer(extra: Partial<ExplorerView> = {}): ExplorerView {
  return { info: INFO, q: "", cat: "manger", where: "moi", places: [place({ osm: "n4021153781", open_state: "open", open_text: "Ouvert · ferme à 22:30",
    cuisine: "Pizza", rating: 4.8, reviews: 15235, price: "€€", photo: "p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02" }), place({ id: "l22918", name: "Le Coq Hardi", cuisine: "Régionale" })],
  addresses: [], error: "", addrError: "", loading: false, searched: true, sel: null, regard: null, hint: "", map: "",
  filters: NO_FILTERS, coverage: { ready: true, cells: 1, loaded: 1, oldest: new Date(2026, 10, 20, 22, 0).getTime(), note: "" }, seen: never, now: NOW, ...extra };
}

describe("Explorer : la liste notée et ses filtres", () => {
  it("chaque ligne : la note et le nombre d'avis, le prix, la cuisine, ouvert ou fermé, une vignette quand il a une photo", () => {
    const html = explorerMarkup(explorer());
    expect(html).toContain("4,8");
    expect(html).toContain("(15\u00a0235)");
    expect(html).toContain("€€ · Pizza");
    expect(html).toContain('<span class="li-snip ok-txt">Ouvert · ferme à 22:30</span>');
    expect(html).toContain('class="pl-thumb"');
    expect(html).toContain('data-src="http://localhost:8001/api/moi/carte/photo/p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02"');
    // sans note ni photo : son rond, ce qu'il est et sa cuisine
    expect(html).toContain("Restaurant · Lille · Régionale");
    const closed = placeItem(place({ open_state: "closed", open_text: "Fermé · ouvre à 19:00" }), "l1", { on: false, mika: false, where: "moi" });
    expect(closed).toContain('<span class="li-snip ko-txt">Fermé · ouvre à 19:00</span>');
  });

  it("au-dessus de la liste, quand les notes ont été lues, ou ce que le serveur en dit", () => {
    expect(explorerMarkup(explorer())).toContain("Notes Google Maps lues aujourd&#39;hui à 22:00");
    const partial = explorerMarkup(explorer({ coverage: { ready: true, cells: 1, loaded: 0, oldest: 0,
      note: "Les notes de cet endroit ne sont pas encore toutes lues : elles le seront au préchargement ou ce soir." } }));
    expect(partial).toContain("ne sont pas encore toutes lues");
  });

  it("les filtres sous la recherche : ouvert maintenant, ceux du serveur, « 4 et plus », la cuisine ; l'ordre", () => {
    const html = explorerMarkup(explorer({ filters: { open: true, features: ["vegan"], minRating: 4, sort: "rating", cuisine: "Pizza" } }));
    expect(html).toContain('class="cat flt on" data-flt="open" aria-pressed="true"');
    expect(html).toContain('data-flt="f:terrasse" aria-pressed="false">Terrasse');
    expect(html).toContain('class="cat flt on" data-flt="f:vegan" aria-pressed="true">Vegan');
    expect(html).toContain('class="cat flt on" data-flt="rating" aria-pressed="true"');
    expect(html).toContain("4 et plus");
    expect(html).toContain('<option value="Pizza" selected>Pizza</option>');
    expect(html).toContain("Les mieux notés");
    expect(filtersOn({ ...NO_FILTERS })).toBe(false);
    expect(filtersOn({ ...NO_FILTERS, features: ["vegan"] })).toBe(true);
    // rien à filtrer tant qu'on ne cherche rien ; ni dans ce que Mika a cherché
    expect(explorerMarkup(explorer({ cat: "", q: "" }))).not.toContain("data-flt");
    expect(explorerMarkup(explorer({ regard: { title: "x", route: false, links: [] } }))).not.toContain("data-flt");
    expect(explorerMarkup(explorer({ places: [], filters: { ...NO_FILTERS, open: true } }))).toContain("avec ces filtres");
    expect(filtersMarkup({ info: { ...INFO, features: [] }, places: [], filters: NO_FILTERS })).not.toContain("data-cuisine");
  });

  it("les cuisines proposées : celles de la liste, les plus fréquentes d'abord, et celle choisie", () => {
    expect(cuisineChoices([{ cuisine: "Italienne, pizza" }, { cuisine: "pizza" }, { cuisine: "" }, {}])).toEqual(["Pizza", "Italienne"]);
    expect(cuisineChoices([{ cuisine: "Pizza" }], "Japonaise")).toEqual(["Japonaise", "Pizza"]);
  });

  it("la fiche ouverte remplace la recherche et la liste", () => {
    const html = explorerMarkup(explorer({ fiche: '<div class="fiche">la fiche</div>' }));
    expect(html).toContain("la fiche");
    expect(html).not.toContain("data-q");
  });

  it("la fiche dans la route : son objet d'OpenStreetMap d'abord ; une adresse n'en a pas", () => {
    expect(ficheId({ id: "l22871", osm: "n4021153781" })).toBe("n4021153781");
    expect(ficheId({ id: "l22871" })).toBe("l22871");
    expect(ficheId({ id: "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10" })).toBe("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10");
    expect(ficheId({ id: "a:1" })).toBeNull();
    expect(ficheId({ id: "" })).toBeNull();
    expect(lieuItem("n4021153781")).toBe("lieu-n4021153781");
    expect(lieuOf("lieu-n4021153781")).toBe("n4021153781");
    expect(lieuOf("lieu-t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10")).toBe("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10");
    expect(lieuOf("lieu-../../x")).toBeNull();
    expect(lieuOf("regard-36")).toBeNull();
    expect(lieuOf(null)).toBeNull();
  });

  it("la main reste sur un filtre, un thème, un événement d'un dessin à l'autre", () => {
    expect(focusSelector({ flt: "f:vegan" })).toBe('[data-flt="f:vegan"]');
    expect(focusSelector({ theme: "concerts" })).toBe('[data-theme="concerts"]');
    expect(focusSelector({ evq: "" })).toBe("[data-evq]");
    expect(focusSelector({ evWhere: "moi" })).toBe('[data-ev-where="moi"]');
    expect(focusSelector({ refresh: "" })).toBe("[data-refresh]");
  });
});
