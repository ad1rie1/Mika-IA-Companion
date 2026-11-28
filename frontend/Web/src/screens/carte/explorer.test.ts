/**
 * Le contrôleur d'Explorer contre une API simulée et un cadre factice : « Actualiser » montre le message du serveur tel
 * quel, relit la fiche après un 503 (ce qui a pu se relire est gardé) mais pas après un 429, et sa nouvelle note passe
 * dans la ligne de la liste (la distance de la ligne gardée) ; une réponse en retard ne remplace pas la recherche d'après ;
 * « Autour de moi » refusé (409) cherche dans la zone et le dit ; la relecture après le préchargement ne part qu'une
 * fois ; les lieux d'un regard gardent leur note ; le retour d'une fiche ouverte depuis un événement y ramène.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPlace, listPlaces, refreshPlace, type CarteInfo, type Place, type PlaceFiche, type PlacesResult, type Regard } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { toast } from "../../shell/float";
import { Cached, CachedMap } from "../../shared/kit";
import { ExplorerTab, type ExplorerHost } from "./explorer";

vi.mock("../../api/carte", async (orig) => ({ ...(await orig<typeof import("../../api/carte")>()), fetchPlace: vi.fn(), listPlaces: vi.fn(), refreshPlace: vi.fn() }));
vi.mock("../../shell/float", async (orig) => ({ ...(await orig<typeof import("../../shell/float")>()), toast: vi.fn(), openMenu: vi.fn() }));

const INFO: CarteInfo = {
  places: { ready: true, count: 35725, built: 1 }, addresses: { ready: false },
  routing: { ready: true, provider: "Valhalla", modes: ["voiture"], avoid: [] }, categories: [{ id: "manger", label: "Manger" }],
};

function magmatic(extra: Partial<Place> = {}): Place {
  return { id: "l22871", name: "Magmatic", kind: "restaurant", kind_fr: "Restaurant", category: "manger", lat: 50.63712, lon: 3.06455,
    town: "Lille", distance_m: 240, along_m: null, osm: "n4021153781", rating: 4.7, reviews: 1200, price: "€€", ...extra };
}

function fiche(p: Place): PlaceFiche {
  return { place: { ...p, distance_m: null }, osm: null, tourism: null, reviews: null, events: [] };
}

const REGARD: Regard = { kind: "look", title: "Manger · Vieux-Lille", what: "lieux", route: null, trip: "", at: 1,
  places: [{ id: "l22871", name: "Magmatic", kind: "restaurant", kind_fr: "Restaurant", category: "manger", lat: 50.63712, lon: 3.06455,
    town: "Lille", distance_m: null, along_m: null, osm: "n4021153781", rating: 4.8, reviews: 15235, price: "€€", cuisine: "Pizza" },
  { id: "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", name: "Le Lys", kind: "restaurant", kind_fr: "Restaurant", category: "manger",
    lat: 50.64, lon: 3.06, town: "Lille", distance_m: null, along_m: null }] };

interface Internals {
  q: string;
  search(refit?: boolean, reread?: boolean): Promise<void>;
  refresh(): Promise<void>;
  explorerHtml(): string;
}

function frame(over: Partial<Record<string, unknown>> = {}) {
  const went: string[] = [];
  const host = {
    shell: { go: (hash: string) => went.push(hash) },
    hooks: { ask: () => undefined },
    carte: new Cached(async () => INFO),
    trips: new Cached(async () => []),
    position: new Cached(async () => ({ known: true, coords: { lat: 50.6371, lon: 3.0638 }, label: "Lille", accuracy_m: 10, at: 1 })),
    tripCache: new CachedMap(async () => { throw new Error("pas de voyage"); }),
    regards: new CachedMap(async () => REGARD),
    addressBook: { peek: () => null, lookup: async () => [] },
    minis: {},
    body: () => null,
    open: () => true,
    current: () => "explorer",
    paint: () => undefined,
    here: () => ({ lat: 50.6371, lon: 3.0638, label: "Lille" }),
    fitNext: () => undefined,
    pane: () => "",
    view: () => ({ frame: () => [3.05, 50.63, 3.08, 50.64] }),
    scene: () => ({ pins: [], lines: [] }),
    dropItem: () => undefined,
    routeTo: () => undefined,
    addPlace: async () => ({ ok: true, error: null }),
    newTripModal: () => undefined,
    ...over,
  };
  return { host: host as unknown as ExplorerHost, went };
}

/** Un onglet qui a cherché « pizza » autour de toi, et rend cette liste. */
async function searched(found: PlacesResult, over: Partial<Record<string, unknown>> = {}) {
  vi.mocked(listPlaces).mockResolvedValueOnce(found);
  const { host, went } = frame(over);
  const tab = new ExplorerTab(host);
  await host.position.load();
  tab.loaded();
  const inner = tab as unknown as Internals;
  inner.q = "pizza";
  await inner.search();
  return { tab, inner, host, went };
}

beforeEach(() => {
  vi.stubGlobal("window", globalThis);
  vi.mocked(listPlaces).mockReset();
  vi.mocked(fetchPlace).mockReset();
  vi.mocked(refreshPlace).mockReset();
  vi.mocked(toast).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("« Actualiser » (R2-W07, R2-W11)", () => {
  it("la nouvelle note passe dans la ligne de la liste, sa distance gardée ; le message du serveur se dit tel quel", async () => {
    const { tab, inner } = await searched({ places: [magmatic()], reviews: null, here: null });
    vi.mocked(fetchPlace).mockResolvedValue(fiche(magmatic()));
    tab.applyItem("lieu-n4021153781");
    await vi.waitFor(() => expect(fetchPlace).toHaveBeenCalledTimes(1));
    vi.mocked(refreshPlace).mockResolvedValueOnce({ ok: true, message: "Relue il y a 4 min : elle est à jour.", ...fiche(magmatic({ rating: 4.8, reviews: 1260 })) });
    await inner.refresh();
    expect(toast).toHaveBeenCalledWith("Relue il y a 4 min : elle est à jour.", expect.anything());
    expect(tab.places).toHaveLength(1);
    expect(tab.places[0]).toMatchObject({ rating: 4.8, reviews: 1260, distance_m: 240 });
  });

  it("un 503 : ce qui n'a pas pu se relire se dit, et la fiche se relit une fois ; un 429 n'a rien tenté : rien ne se relit", async () => {
    const { tab, inner } = await searched({ places: [magmatic()], reviews: null, here: null });
    vi.mocked(fetchPlace).mockResolvedValue(fiche(magmatic()));
    tab.applyItem("lieu-n4021153781");
    await vi.waitFor(() => expect(fetchPlace).toHaveBeenCalledTimes(1));
    vi.mocked(refreshPlace).mockRejectedValueOnce(new ApiError(503, "le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05."));
    await inner.refresh();
    expect(fetchPlace).toHaveBeenCalledTimes(2);
    expect(inner.explorerHtml()).toContain("il revient à 14:05.");
    vi.mocked(refreshPlace).mockRejectedValueOnce(new ApiError(429, "Trop de fiches actualisées d'affilée : attends une minute."));
    await inner.refresh();
    expect(fetchPlace).toHaveBeenCalledTimes(2);
    expect(inner.explorerHtml()).toContain("attends une minute.");
  });
});

describe("la recherche (R2-W11)", () => {
  it("la réponse en retard d'une première recherche ne remplace pas la seconde", async () => {
    const { tab, inner } = await searched({ places: [magmatic()], reviews: null, here: null });
    let late!: (v: PlacesResult) => void;
    vi.mocked(listPlaces)
      .mockImplementationOnce(() => new Promise((resolve) => { late = resolve; }))
      .mockResolvedValueOnce({ places: [magmatic({ id: "l2", name: "Tigermilk" })], reviews: null, here: null });
    const first = inner.search(false);
    await vi.waitFor(() => expect(listPlaces).toHaveBeenCalledTimes(2));
    await inner.search(false);
    late({ places: [magmatic({ id: "l3", name: "En retard" })], reviews: null, here: null });
    await first;
    expect(tab.places.map((p) => p.name)).toEqual(["Tigermilk"]);
  });

  it("« Autour de moi » refusé (409) : le message du serveur, et la recherche se fait dans la zone", async () => {
    const refused = new ApiError(409, "Ta position n'est pas connue ici : ton téléphone ne l'a pas donnée.", { near: "ta position" });
    vi.mocked(listPlaces).mockRejectedValueOnce(refused).mockResolvedValueOnce({ places: [magmatic()], reviews: null, here: null });
    const { host } = frame();
    const tab = new ExplorerTab(host);
    await host.position.load();
    tab.loaded();
    const inner = tab as unknown as Internals;
    inner.q = "pizza";
    await inner.search();
    expect(vi.mocked(listPlaces).mock.calls.map((c) => [c[0].near ?? null, c[0].bbox ?? null])).toEqual([["ici", null], [null, [3.05, 50.63, 3.08, 50.64]]]);
    expect(tab.places.map((p) => p.name)).toEqual(["Magmatic"]);
    expect(inner.explorerHtml()).toContain("Elle cherche dans la zone de la carte.");
  });

  it("après « Autour de moi », la liste se relit une fois quand les notes de la case arrivent — jamais en boucle", async () => {
    vi.useFakeTimers();
    const partial = { ready: true, cells: 9, loaded: 3, oldest: 0, note: "" };
    vi.mocked(listPlaces).mockResolvedValue({ places: [magmatic()], reviews: partial, here: null });
    const { host } = frame();
    const tab = new ExplorerTab(host);
    await host.position.load();
    tab.loaded();
    const inner = tab as unknown as Internals;
    inner.q = "pizza";
    await inner.search();
    expect(listPlaces).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(6000);
    expect(listPlaces).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(listPlaces).toHaveBeenCalledTimes(2);
  });
});

describe("un regard de Mika", () => {
  it("ses lieux gardent leur note (R2-W08), et un lieu des données touristiques rouvre sa fiche (R2-M01)", async () => {
    const { host, went } = frame();
    const tab = new ExplorerTab(host);
    await host.regards.get("840").load();
    tab.applyItem("regard-840");
    const html = (tab as unknown as Internals).explorerHtml();
    expect(html).toContain("4,8");
    expect(html).toContain("Google Maps");
    tab.pinClicked("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10");
    expect(went).toEqual(["#carte/explorer/lieu-t%3A6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10"]);
  });
});

describe("le retour d'une fiche (R2-W06)", () => {
  it("ouverte depuis un événement, elle y ramène — pas à un regard d'avant sans rapport", async () => {
    const { host } = frame();
    const tab = new ExplorerTab(host);
    await host.regards.get("840").load();
    tab.applyItem("regard-840");
    vi.mocked(fetchPlace).mockResolvedValue(fiche(magmatic({ id: "l9", osm: "w84451082", name: "Maison natale de Charles de Gaulle" })));
    tab.applyItem("lieu-w84451082", { href: "#carte/evenements/e%3A9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f", label: "Retour à l'événement" });
    const html = (tab as unknown as Internals).explorerHtml();
    expect(html).toContain('href="#carte/evenements/e%3A9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f" data-fiche-back');
    expect(html).toContain("Retour à l&#39;événement");
    expect(html).not.toContain("Ce que Mika a cherché");
  });
});
