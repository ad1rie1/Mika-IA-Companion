/**
 * Le contrôleur des Événements contre une API simulée et un cadre factice : une fiche n'est « trouvée par Mika » (en rose,
 * retour à son regard) que si l'événement est dans ce regard — passé par un autre onglet, un autre événement n'y est pas ;
 * une fiche ouverte depuis la fiche d'un lieu y ramène.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchEvent, listEvents, type CarteInfo, type EventFiche, type EventItem, type Regard } from "../../api/carte";
import { Cached, CachedMap } from "../../shared/kit";
import { ficheIsHers } from "./agenda";
import { EventsTab, type EventsHost } from "./events";

vi.mock("../../api/carte", async (orig) => ({ ...(await orig<typeof import("../../api/carte")>()), fetchEvent: vi.fn(), listEvents: vi.fn() }));

const INFO: CarteInfo = {
  places: { ready: true, count: 1, built: 1 }, addresses: { ready: false },
  routing: { ready: false, provider: "", modes: [], avoid: [] }, categories: [], themes: [{ id: "spectacles", label: "Spectacles" }],
};

const HERS = "e:9a03e72c-35c0-3b1d-8e4f-6a2b0c1d3e5f";
const OTHER = "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41";

function event(id: string, name: string): EventItem {
  return { id, name, start: "2026-11-21T19:00+01:00", end: "2026-11-21T22:00+01:00", when_text: "sam. 21 nov. · 19:00–22:00",
    place: "L'Aéronef, Lille", lat: 50.636554, lon: 3.074244, distance_m: null, themes: ["spectacles"], free: false, price: "", photo: "" };
}

function fiche(e: EventItem): EventFiche {
  return { event: e, description: "", dates: [], more_dates: 0, prices: "", contacts: [], address: "", town: "Lille", venue: "",
    venue_place: "", author: "Hello Lille", updated: "2026-10-02", url: "", photos: [], merged: 1,
    attribution: "DATAtourisme · Hello Lille, mis à jour le 2 octobre 2026", licence: "Licence Ouverte 2.0", licence_url: "" };
}

const REGARD: Regard = { kind: "look", title: "Ce week-end", what: "evenements", places: [], route: null, trip: "", at: 1,
  events: [{ id: HERS, name: "Fiat lux !", start: "2026-11-21T10:00+01:00", end: "", when_text: "", place: "Lille", lat: 50.646, lon: 3.059 }] };

function frame(): EventsHost {
  const host = {
    shell: { go: () => undefined },
    hooks: { ask: () => undefined },
    carte: new Cached(async () => INFO),
    trips: new Cached(async () => []),
    position: new Cached(async () => ({ known: false })),
    tripCache: new CachedMap(async () => { throw new Error("pas de voyage"); }),
    regards: new CachedMap(async () => REGARD),
    addressBook: {},
    minis: {},
    body: () => null,
    open: () => true,
    current: () => "evenements",
    paint: () => undefined,
    here: () => null,
    fitNext: () => undefined,
    pane: () => "",
    view: () => null,
    scene: () => ({ pins: [], lines: [] }),
    dropItem: () => undefined,
    routeTo: () => undefined,
    addPlace: async () => ({ ok: true, error: null }),
    newTripModal: () => undefined,
  };
  return host as unknown as EventsHost;
}

beforeEach(() => {
  vi.stubGlobal("window", globalThis);
  vi.mocked(fetchEvent).mockReset();
  vi.mocked(listEvents).mockReset();
});

afterEach(() => vi.unstubAllGlobals());

describe("une fiche d'événement et le regard de Mika (R2-W05)", () => {
  it("un événement de son regard est le sien ; un autre, ouvert depuis un autre onglet, non", async () => {
    expect(ficheIsHers({ events: [event(HERS, "Fiat lux !")] }, HERS)).toBe(true);
    expect(ficheIsHers({ events: [event(HERS, "Fiat lux !")] }, OTHER)).toBe(false);
    expect(ficheIsHers(null, HERS)).toBe(false);
    const host = frame();
    const tab = new EventsTab(host);
    await host.regards.get("840").load();
    vi.mocked(fetchEvent).mockImplementation(async (id) => fiche(event(id, id === HERS ? "Fiat lux !" : "Éclats du rire !")));
    tab.applyItem("regard-840");
    tab.applyItem(HERS);
    await vi.waitFor(() => expect(fetchEvent).toHaveBeenCalledTimes(1));
    const hers = tab.eventsHtml();
    expect(hers).toContain("Mika l'a trouvé pour toi");
    expect(hers).toContain('href="#carte/evenements/regard-840" data-fiche-back');
    // passée par Explorer, la fiche d'un lieu, puis « Bientôt, tout près » : un événement qui n'est pas le sien
    tab.applyItem(OTHER);
    await vi.waitFor(() => expect(fetchEvent).toHaveBeenCalledTimes(2));
    const other = tab.eventsHtml();
    expect(other).not.toContain("Mika l'a trouvé pour toi");
    expect(other).not.toContain("regard-840");
    expect(other).not.toContain("fiche by-mika");
  });
});

describe("le retour d'une fiche d'événement (R2-W06)", () => {
  it("ouverte depuis la fiche d'un lieu, elle y ramène", async () => {
    const host = frame();
    const tab = new EventsTab(host);
    vi.mocked(fetchEvent).mockResolvedValue(fiche(event(OTHER, "Éclats du rire !")));
    tab.applyItem(OTHER, { href: "#carte/explorer/lieu-w84451082", label: "Retour au lieu" });
    const html = tab.eventsHtml();
    expect(html).toContain('href="#carte/explorer/lieu-w84451082" data-fiche-back');
    expect(html).toContain("Retour au lieu");
  });
});
