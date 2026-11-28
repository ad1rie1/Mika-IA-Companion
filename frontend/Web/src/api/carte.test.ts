import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addStop,
  bboxText,
  createTrip,
  eventsParams,
  fetchCarte,
  fetchEvent,
  fetchOnRoute,
  fetchPlace,
  fetchRoute,
  listEvents,
  listPlaces,
  moveStop,
  noteStop,
  photoUrl,
  placesParams,
  pointsText,
  refreshPlace,
  removeStop,
  searchAddresses,
  searchPlaces,
  tripGpxUrl,
} from "./carte";
import { ApiError } from "./moi";

const API = "http://localhost:8001";

interface Call {
  url: string;
  init: RequestInit;
}

let calls: Call[] = [];
let answer: { status: number; body: unknown } = { status: 200, body: {} };

beforeEach(() => {
  calls = [];
  answer = { status: 200, body: {} };
  vi.stubGlobal("document", { cookie: "csrftoken=le-jeton" });
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "Content-Type": "application/json" } });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("l'API de la carte (protocole-moi.md § 10)", () => {
  it("lit ce qui est branché, en GET, avec la session et jamais depuis le cache", async () => {
    answer.body = { places: { ready: true, count: 3, built: 1 }, addresses: { ready: false }, routing: { ready: false, provider: "", modes: [], avoid: [] }, categories: [] };
    const got = await fetchCarte();
    expect(got.places.count).toBe(3);
    expect(calls[0].url).toBe(`${API}/api/moi/carte`);
    expect(calls[0].init).toMatchObject({ credentials: "include", cache: "no-store" });
    expect(calls[0].init.method).toBeUndefined();
  });

  it("cherche dans l'index : le texte, la catégorie, près d'un point ou dans une zone", async () => {
    answer.body = { places: [{ id: "l3", name: "Camping de l'Horizon" }] };
    const got = await searchPlaces({ q: " camping ", cat: "dormir", near: { lat: 45.9, lon: 6.1 }, limit: 20 });
    expect(got[0].id).toBe("l3");
    expect(calls[0].url).toBe(`${API}/api/moi/carte/lieux?q=camping&cat=dormir&near=45.900000%2C6.100000&limit=20`);
    await searchPlaces({ cat: "manger", bbox: [6.06, 45.76, 6.3, 45.93] });
    expect(calls[1].url).toBe(`${API}/api/moi/carte/lieux?cat=manger&bbox=6.06000%2C45.76000%2C6.30000%2C45.93000`);
    expect(bboxText([6.06, 45.76, 6.3, 45.93])).toBe("6.06000,45.76000,6.30000,45.93000");
  });

  it("une adresse : seul le texte part (jamais la position)", async () => {
    answer.body = { places: [] };
    await searchAddresses("12 rue Royale Annecy");
    expect(calls[0].url).toBe(`${API}/api/moi/carte/adresses?q=12+rue+Royale+Annecy&limit=5`);
    expect(calls[0].url).not.toMatch(/near|lat|lon/);
  });

  it("un itinéraire : ses points, son mode, ce qu'il évite", async () => {
    answer.body = { distance_m: 1, duration_s: 1, legs: [], has_toll: false, has_highway: false, has_ferry: false, provider: "x" };
    await fetchRoute([{ lat: 50.637, lon: 3.063 }, { lat: 45.899, lon: 6.129 }], "voiture", ["peages", "autoroutes"]);
    expect(calls[0].url).toBe(`${API}/api/moi/carte/itineraire?points=50.637000%2C3.063000%3B45.899000%2C6.129000&mode=voiture&avoid=peages%2Cautoroutes`);
    expect(pointsText([{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }])).toBe("1.000000,2.000000;3.000000,4.000000");
  });

  it("ce qui n'est pas branché : le 503 du serveur, en mots", async () => {
    answer = { status: 503, body: { error: "Les itinéraires ne sont pas encore prêts sur ce serveur." } };
    const failed = await fetchRoute([{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }], "voiture").catch((e: unknown) => e);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).status).toBe(503);
    expect((failed as ApiError).message).toBe("Les itinéraires ne sont pas encore prêts sur ce serveur.");
  });

  it("écrit en POST JSON, avec le jeton CSRF et une clé d'envoi", async () => {
    answer.body = { ok: true, message: "Voyage créé.", id: "640" };
    const got = await createTrip({ title: "Les Alpes", start: "2027-04-03", mode: "voiture", avoid: [] }, "cle-1");
    expect(got.id).toBe("640");
    expect(calls[0].url).toBe(`${API}/api/moi/voyages`);
    expect(calls[0].init.method).toBe("POST");
    expect((calls[0].init.headers as Record<string, string>)["X-CSRFToken"]).toBe("le-jeton");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ title: "Les Alpes", start: "2027-04-03", mode: "voiture", avoid: [], nonce: "cle-1" });
  });

  it("les arrêts : ajouter, déplacer (jour et place), retirer", async () => {
    answer.body = { ok: true, message: "ok", id: "650" };
    await addStop("640", { name: "Annecy", lat: 45.9, lon: 6.13, day: 2, index: -1 }, "k");
    expect(calls[0].url).toBe(`${API}/api/moi/voyages/640/arrets`);
    expect(JSON.parse(String(calls[0].init.body))).toMatchObject({ name: "Annecy", day: 2, index: -1 });
    await moveStop("640", "650", 3, 0, "k2");
    expect(calls[1].url).toBe(`${API}/api/moi/voyages/640/arrets/650`);
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ day: 3, index: 0, nonce: "k2" });
    await removeStop("640", "650");
    expect(calls[2].url).toBe(`${API}/api/moi/voyages/640/arrets/650/retirer`);
  });

  it("noter un arrêt : sa note seule, avec sa clé d'envoi ; vide, elle s'efface (F3-14)", async () => {
    answer.body = { ok: true, message: "Note changée." };
    await noteStop("640", "650", "Réserver avant le 15", "cle-note");
    expect(calls[0].url).toBe(`${API}/api/moi/voyages/640/arrets/650`);
    expect(calls[0].init.method).toBe("POST");
    expect((calls[0].init.headers as Record<string, string>)["X-CSRFToken"]).toBe("le-jeton");
    // ni `day` ni `index` : le moteur ne le déplace pas (`stop_change`, app/domains/maps/api.py)
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ note: "Réserver avant le 15", nonce: "cle-note" });
    await noteStop("640", "650", "", "cle-vide");
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ note: "", nonce: "cle-vide" });
  });

  it("le long du trajet d'un voyage, et son GPX sur le serveur", async () => {
    answer.body = { places: [], route: false };
    await fetchOnRoute("640", { cat: "voir", day: 0, corridor: 10_000 });
    expect(calls[0].url).toBe(`${API}/api/moi/voyages/640/sur-la-route?cat=voir&day=0&corridor=10000`);
    expect(tripGpxUrl("640")).toBe(`${API}/api/moi/voyages/640/gpx`);
  });
});

describe("les fiches, les événements et les photos (protocole-moi.md § 10, ADR 0259)", () => {
  it("une liste filtrée et rangée : ouvert, ce qu'il offre, sa cuisine, une note minimale, l'ordre", async () => {
    answer.body = { places: [{ id: "l22871", name: "Magmatic", rating: 4.8, reviews: 15235 }],
      reviews: { ready: true, cells: 1, loaded: 1, oldest: 1795155120000, note: "" } };
    const got = await listPlaces({ cat: "manger", near: { lat: 50.6371, lon: 3.0638 }, sort: "rating", features: ["terrasse", "vegan"],
      open: true, minRating: 4, cuisine: " italienne " });
    expect(got.places[0].rating).toBe(4.8);
    expect(got.reviews?.oldest).toBe(1795155120000);
    expect(got.here).toBeNull();
    expect(calls[0].url).toBe(`${API}/api/moi/carte/lieux?cat=manger&near=50.637100%2C3.063800&open_now=1&features=terrasse%2Cvegan&cuisine=italienne&min_rating=4&sort=rating`);
  });

  it("rien de ce qui ne dit rien : ni filtre vide, ni note 0, ni l'ordre par défaut", () => {
    expect(placesParams({ q: "pizza", features: [], open: false, minRating: 0, sort: "distance", cuisine: "" })).toBe("?q=pizza");
    expect(placesParams({ q: "x", minRating: null })).toBe("?q=x");
    expect(placesParams({ q: "x", minRating: 7 })).toBe("?q=x&min_rating=5");
  });

  it("« Autour de moi » : near=ici (le serveur prend la position du téléphone) ; here=1 seulement avec ses coordonnées", async () => {
    answer.body = { places: [], here: { lat: 50.6365, lon: 3.0635, label: "rue Nationale, Lille", at: 1 } };
    const got = await listPlaces({ cat: "manger", near: "ici", here: true });
    expect(calls[0].url).toBe(`${API}/api/moi/carte/lieux?cat=manger&near=ici`);
    expect(got.here?.label).toBe("rue Nationale, Lille");
    expect(placesParams({ near: { lat: 1, lon: 2 }, here: true })).toBe("?near=1.000000%2C2.000000&here=1");
    // un point de la carte qu'on regarde n'est pas toi
    expect(placesParams({ near: { lat: 1, lon: 2 } })).toBe("?near=1.000000%2C2.000000");
    expect(placesParams({ bbox: [1, 2, 3, 4], here: true })).not.toContain("here");
  });

  it("near=ici sans position : le 409 du serveur, en mots, avec son champ", async () => {
    answer = { status: 409, body: { error: "Ta position n'est pas connue ici : ton téléphone ne l'a pas donnée.", fields: { near: "ta position n'est pas connue" } } };
    const failed = await listPlaces({ near: "ici" }).catch((e: unknown) => e);
    expect(failed).toBeInstanceOf(ApiError);
    expect((failed as ApiError).status).toBe(409);
    expect((failed as ApiError).message).toBe("Ta position n'est pas connue ici : ton téléphone ne l'a pas donnée.");
    expect((failed as ApiError).fields).toEqual({ near: "ta position n'est pas connue" });
  });

  it("un paramètre refusé : le 400 et ce que chaque champ demande", async () => {
    answer = { status: 400, body: { error: "« min_rating » : une note de 0 à 5.", fields: { min_rating: "de 0 à 5" } } };
    const failed = (await searchPlaces({ q: "x", minRating: 4 }).catch((e: unknown) => e)) as ApiError;
    expect(failed.message).toBe("« min_rating » : une note de 0 à 5.");
    expect(failed.fields.min_rating).toBe("de 0 à 5");
  });

  it("la fiche d'un lieu, en GET ; son identifiant encodé", async () => {
    answer.body = { place: { id: "l22871" }, osm: null, tourism: null, reviews: null, events: [] };
    await fetchPlace("n4021153781");
    expect(calls[0].url).toBe(`${API}/api/moi/carte/lieu/n4021153781`);
    expect(calls[0].init.method).toBeUndefined();
    await fetchPlace("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10");
    expect(calls[1].url).toBe(`${API}/api/moi/carte/lieu/t%3A6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10`);
  });

  it("« Actualiser » : un POST avec le jeton CSRF ; ce qui n'a pas pu se relire, le 503 en mots", async () => {
    answer.body = { ok: true, message: "Fiche relue.", place: { id: "l22871" }, osm: null, tourism: null, reviews: null, events: [] };
    const got = await refreshPlace("n4021153781");
    expect(got.message).toBe("Fiche relue.");
    expect(calls[0].url).toBe(`${API}/api/moi/carte/lieu/n4021153781/actualiser`);
    expect(calls[0].init.method).toBe("POST");
    expect((calls[0].init.headers as Record<string, string>)["X-CSRFToken"]).toBe("le-jeton");
    answer = { status: 503, body: { error: "Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00." } };
    const failed = (await refreshPlace("n4021153781").catch((e: unknown) => e)) as ApiError;
    expect(failed.status).toBe(503);
    expect(failed.message).toBe("Le quota du mois de Google (fiches avec avis) est atteint : il revient le 1er décembre à 09:00.");
  });

  it("les événements : autour de moi ou d'un point (son rayon), une zone, des dates, des thèmes, gratuits", async () => {
    answer.body = { events: [{ id: "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name: "Éclats du rire !" }],
      coverage: { ready: true, cells: 11, loaded: 3, oldest: 1, note: "Cette zone n'est lue qu'en partie (cases lues : 3 sur 11)." } };
    const got = await listEvents({ near: "ici", start: "2026-11-21", end: "2026-11-22", themes: ["concerts", "fetes"], free: true, limit: 50 });
    expect(got.events).toHaveLength(1);
    expect(got.coverage?.loaded).toBe(3);
    expect(calls[0].url).toBe(`${API}/api/moi/carte/evenements?near=ici&start=2026-11-21&end=2026-11-22&themes=concerts%2Cfetes&free=1&limit=50`);
    expect(eventsParams({ near: { lat: 50.6365, lon: 3.0635 }, radius: 12_000 })).toBe("?near=50.636500%2C3.063500&radius=12000");
    // une zone n'a pas de rayon
    expect(eventsParams({ bbox: [3, 50, 3.2, 50.7], radius: 12_000 })).toBe("?bbox=3.00000%2C50.00000%2C3.20000%2C50.70000");
    expect(eventsParams({ q: "  jazz ", themes: [], free: false })).toBe("?q=jazz");
  });

  it("la fiche d'un événement, en GET", async () => {
    answer.body = { event: { id: "e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f" }, photos: [] };
    await fetchEvent("e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f");
    expect(calls[0].url).toBe(`${API}/api/moi/carte/evenement/e%3A9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f`);
  });

  it("une photo ne vient que de ce serveur : son adresse refaite de sa référence, une autre forme n'en a pas", () => {
    expect(photoUrl("p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02")).toBe(`${API}/api/moi/carte/photo/p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02`);
    expect(photoUrl("https://lh3.googleusercontent.com/x.jpg")).toBeNull();
    expect(photoUrl("p:../../auth/logout")).toBeNull();
    expect(photoUrl("p:3F1C9A0E5B7D2C4E6F8A1B3C5D7E9F02")).toBeNull();
    expect(photoUrl("")).toBeNull();
  });
});
