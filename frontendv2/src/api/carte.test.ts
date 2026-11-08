import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addStop,
  bboxText,
  createTrip,
  fetchCarte,
  fetchOnRoute,
  fetchRoute,
  moveStop,
  pointsText,
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

  it("le long du trajet d'un voyage, et son GPX sur le serveur", async () => {
    answer.body = { places: [], route: false };
    await fetchOnRoute("640", { cat: "voir", day: 0, corridor: 10_000 });
    expect(calls[0].url).toBe(`${API}/api/moi/voyages/640/sur-la-route?cat=voir&day=0&corridor=10000`);
    expect(tripGpxUrl("640")).toBe(`${API}/api/moi/voyages/640/gpx`);
  });
});
