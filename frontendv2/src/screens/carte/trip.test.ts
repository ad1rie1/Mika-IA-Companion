import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shell/float", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../shell/float")>()),
  toast: vi.fn(),
}));
vi.mock("../../api/carte", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/carte")>()),
  moveStop: vi.fn(),
  fetchTripRoute: vi.fn(() => new Promise(() => undefined)),
}));

import { moveStop, type Trip } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { Cached, CachedMap } from "../../shared/kit";
import { toast } from "../../shell/float";
import { movedTrip } from "./format";
import { TripsTab, type TripHost } from "./trip";

/**
 * Le voyage ouvert, ses gestes et leur relecture (R4-03 de la relecture Android, la même variante ici) : une relecture
 * en panne après des gestes aboutis ne remet pas le voyage d'avant eux ; la relecture d'un geste ne lève pas ce qu'un
 * geste fini après lui montre (la sienne, partie après, fera foi).
 */

const TRIP: Trip = {
  id: "640", title: "Les Alpes", start: "", mode: "voiture", avoid: [], updated: 1, mika: false,
  days: [{ n: 1, date: "", stops: [
    { id: "1", name: "Lille", kind: "", lat: 50.6, lon: 3.06, note: "", by: "toi" },
    { id: "2", name: "Reims", kind: "", lat: 49.2, lon: 4.03, note: "", by: "toi" },
    { id: "3", name: "Dijon", kind: "", lat: 47.3, lon: 5.04, note: "", by: "toi" },
  ] }],
};

function hostFor(fetcher: (id: string) => Promise<Trip>): TripHost {
  return {
    tripCache: new CachedMap<Trip>(fetcher, 10_000),
    trips: new Cached(async () => []),
    minis: { invalidate: () => undefined, dataOf: () => null },
    tripId: () => "640",
    syncTripHead: () => undefined,
    paintLater: () => false,
    paint: () => undefined,
    open: () => true,
    current: () => "voyage",
    say: () => undefined,
    emptyScene: () => undefined,
    fitNext: () => undefined,
  } as unknown as TripHost;
}

/** Laisser passer tout ce qui attendait (les promesses enchaînées des gestes et des lectures). */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const ids = (trip: Trip | null) => (trip?.days ?? []).flatMap((d) => d.stops.map((s) => s.id));

const toasts = () => vi.mocked(toast).mock.calls.map(([text]) => text);

describe("la relecture d'un voyage après ses gestes", () => {
  beforeEach(() => {
    vi.mocked(toast).mockClear();
    vi.mocked(moveStop).mockReset();
  });

  it("une relecture en panne après un geste abouti garde ce qu'il a posé, et le dit", async () => {
    let fail = false;
    const host = hostFor(async () => {
      if (fail) throw new Error("réseau");
      return TRIP;
    });
    await host.tripCache.get("640").load();
    const tab = new TripsTab(host);
    vi.mocked(moveStop).mockResolvedValue({ ok: true, message: "" } as never);
    fail = true;
    tab.moveTo("1", 1, -1);
    await settle();
    await settle();
    // le serveur a déplacé Lille : le voyage d'avant (Lille, Reims, Dijon) serait faux
    expect(ids(tab.tripOf("640"))).toEqual(["2", "3", "1"]);
    expect(toasts().some((t) => t.startsWith("C'est enregistré, mais le voyage ne s'est pas relu"))).toBe(true);
  });

  it("un geste refusé puis une relecture en panne : le dernier voyage lu fait foi", async () => {
    let fail = false;
    const host = hostFor(async () => {
      if (fail) throw new Error("réseau");
      return TRIP;
    });
    await host.tripCache.get("640").load();
    const tab = new TripsTab(host);
    vi.mocked(moveStop).mockRejectedValue(new ApiError(409, "La situation a changé."));
    fail = true;
    tab.moveTo("1", 1, -1);
    await settle();
    await settle();
    expect(ids(tab.tripOf("640"))).toEqual(["1", "2", "3"]);
    expect(toasts().some((t) => t.startsWith("Le voyage ne s'est pas relu"))).toBe(true);
  });

  it("le geste G2 fini avant la relecture de G1 : G1 ne lève rien, la relecture de G2 fait foi", async () => {
    let server = TRIP;
    const pending: Array<() => void> = [];
    const host = hostFor(() => new Promise<Trip>((resolve) => {
      const seen = server;
      pending.push(() => resolve(seen));
    }));
    const first = host.tripCache.get("640").load();
    pending.shift()?.();
    await first;
    const tab = new TripsTab(host);
    vi.mocked(moveStop).mockImplementation(async (_id, stop, day, index) => {
      server = movedTrip(server, stop, day, index);
      return { ok: true, message: "" } as never;
    });
    // G1 : Lille au bout ; sa relecture R1 part et reste en route
    tab.moveTo("1", 1, -1);
    await settle();
    expect(pending.length).toBe(1);
    // G2 : Reims au bout, écrit avant que R1 revienne
    tab.moveTo("2", 1, -1);
    await settle();
    expect(ids(tab.tripOf("640"))).toEqual(["3", "1", "2"]);
    // R1 revient avec Reims, Dijon, Lille : elle ne lève pas ce que G2 montre ; une lecture de plus est partie
    pending.shift()?.();
    await settle();
    expect(ids(tab.tripOf("640"))).toEqual(["3", "1", "2"]);
    expect(pending.length).toBe(1);
    pending.shift()?.();
    await settle();
    expect(ids(tab.tripOf("640"))).toEqual(["3", "1", "2"]);
    expect(ids(host.tripCache.get("640").value)).toEqual(["3", "1", "2"]);
  });
});
