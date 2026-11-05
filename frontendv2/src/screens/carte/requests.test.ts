import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Place, Trip, TripRoute } from "../../api/carte";
import { ApiError } from "../../api/moi";
import { movedTrip, removedTrip } from "./format";
import { ADDRESS_LIMIT, AddressBook, alongAfterRoute, GestureQueue, refused, ROUTE_WAIT_MS, TripRoutes, wantsAddress } from "./requests";

function place(name: string): Place {
  return { id: "a:0", name, kind: "address", kind_fr: "", category: "adresse", lat: 45.9, lon: 6.1, town: "Annecy", distance_m: null, along_m: null };
}

const TRIP: Trip = {
  id: "640", title: "Les Alpes", start: "", mode: "voiture", avoid: [], updated: 1,
  days: [
    { n: 1, date: "", stops: [
      { id: "1", name: "Lille", kind: "", lat: 50.637, lon: 3.063, note: "", by: "toi" },
      { id: "2", name: "Reims", kind: "", lat: 49.258, lon: 4.032, note: "", by: "mika" },
      { id: "3", name: "Dijon", kind: "", lat: 47.322, lon: 5.041, note: "", by: "toi" },
    ] },
  ],
};

function route(km: number): TripRoute {
  return { days: [{ n: 1, distance_m: km * 1000, duration_s: 60, legs: [] }], distance_m: km * 1000, duration_s: 60,
    has_toll: false, has_highway: false, has_ferry: false, provider: "essai" };
}

describe("les adresses : une fois par texte, seulement quand le texte en a l'air", () => {
  it("un chiffre, ou cinq caractères ; jamais moins de trois", () => {
    expect(wantsAddress("12")).toBe(false);
    expect(wantsAddress("12 r")).toBe(true);
    expect(wantsAddress("Lyo")).toBe(false); // un nom court : l'index des lieux suffit
    expect(wantsAddress("Rue R")).toBe(true);
    expect(wantsAddress("   ab  ")).toBe(false);
  });

  it("un texte déjà cherché ne se redemande pas (ni la casse ni les espaces n'y comptent), deux demandes n'en font qu'une", async () => {
    const asked: Array<[string, number]> = [];
    const book = new AddressBook(async (q, limit) => {
      asked.push([q, limit]);
      return [place(q)];
    });
    expect(book.peek("12 rue Royale")).toBeNull();
    const [a, b] = await Promise.all([book.lookup("12 rue Royale"), book.lookup("12 rue Royale")]);
    expect(a).toBe(b);
    await book.lookup("  12  RUE royale ");
    expect(asked).toEqual([["12 rue Royale", ADDRESS_LIMIT]]);
    expect(book.peek("12 rue royale")?.[0].name).toBe("12 rue Royale");
  });

  it("un refus (429) se dit à l'appelant et ne se garde pas : le texte se redemandera", async () => {
    let calls = 0;
    const book = new AddressBook(async () => {
      calls += 1;
      if (calls === 1) throw new ApiError(429, "Trop de trajets ou d'adresses demandés d'affilée : attends une minute.");
      return [place("12 rue Royale")];
    });
    await expect(book.lookup("12 rue Royale")).rejects.toMatchObject({ status: 429 });
    expect(book.peek("12 rue Royale")).toBeNull();
    expect(await book.lookup("12 rue Royale")).toHaveLength(1);
    expect(calls).toBe(2);
  });

  it("n'en garde qu'un nombre borné, les plus anciens s'en vont", async () => {
    const book = new AddressBook(async (q) => [place(q)], 2);
    await book.lookup("1 rue A");
    await book.lookup("2 rue B");
    await book.lookup("3 rue C");
    expect(book.peek("1 rue A")).toBeNull();
    expect(book.peek("3 rue C")).not.toBeNull();
  });
});

describe("le trajet d'un voyage : celui de ses arrêts, relu une fois qu'ils ne bougent plus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ouvert : lu de suite, puis gardé tant que ses arrêts ne changent pas (une note, un titre n'y font rien)", async () => {
    const fetcher = vi.fn(async () => route(500));
    const landed = vi.fn();
    const routes = new TripRoutes(fetcher, landed);
    expect(routes.shown(TRIP)).toEqual({ route: null, error: null, pending: true });
    routes.want(TRIP, { soon: true });
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(landed).toHaveBeenCalledWith("640");
    expect(routes.shown(TRIP).route?.distance_m).toBe(500_000);
    const renamed: Trip = { ...TRIP, title: "Autre", updated: 2, days: [{ ...TRIP.days[0], stops: TRIP.days[0].stops.map((s) => ({ ...s, note: "réserver" })) }] };
    routes.want(renamed, { soon: true });
    routes.want(renamed);
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(routes.shown(renamed).route?.distance_m).toBe(500_000);
  });

  it("dix gestes d'affilée : une seule relecture, après le dernier ; d'ici là, le trajet d'avant ne se montre pas", async () => {
    let km = 500;
    const fetcher = vi.fn(async () => route(km));
    const routes = new TripRoutes(fetcher, () => {});
    // onze arrêts : le premier passe au bout, dix fois (jamais revenu à l'ordre du départ)
    const long: Trip = { ...TRIP, days: [{ n: 1, date: "", stops: Array.from({ length: 11 }, (_, i) => ({ ...TRIP.days[0].stops[0], id: `s${i}`, lat: 45 + i / 10 })) }] };
    routes.want(long, { soon: true });
    await vi.runAllTimersAsync();
    let trip = long;
    for (let i = 0; i < 10; i++) {
      trip = movedTrip(trip, trip.days[0].stops[0].id, 1, -1);
      routes.want(trip);
      expect(routes.shown(trip).route).toBeNull(); // ce n'est plus celui de ces arrêts
      expect(routes.shown(trip).pending).toBe(true);
      await vi.advanceTimersByTimeAsync(ROUTE_WAIT_MS - 200);
      routes.want(trip, { soon: true }); // un dessin entre deux gestes n'écourte pas l'attente
    }
    expect(fetcher).toHaveBeenCalledTimes(1);
    km = 620;
    await vi.advanceTimersByTimeAsync(ROUTE_WAIT_MS);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(routes.shown(trip).route?.distance_m).toBe(620_000);
  });

  it("monté puis redescendu : revenu à ses arrêts, rien ne se relit", async () => {
    const fetcher = vi.fn(async () => route(500));
    const routes = new TripRoutes(fetcher, () => {});
    routes.want(TRIP, { soon: true });
    await vi.runAllTimersAsync();
    routes.want(movedTrip(TRIP, "3", 1, 0));
    routes.want(TRIP);
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(routes.shown(TRIP).route).not.toBeNull();
  });

  it("une relecture refusée (429, 503) : le refus, et plus le trajet d'avant à côté", async () => {
    let fail = false;
    const routes = new TripRoutes(async () => {
      if (fail) throw new ApiError(429, "Trop de trajets ou d'adresses demandés d'affilée : attends une minute.");
      return route(500);
    }, () => {});
    routes.want(TRIP, { soon: true });
    await vi.runAllTimersAsync();
    fail = true;
    const moved = movedTrip(TRIP, "1", 1, 2);
    routes.want(moved);
    await vi.runAllTimersAsync();
    const shown = routes.shown(moved);
    expect(shown.route).toBeNull();
    expect(shown.error).toMatchObject({ status: 429 });
    expect(shown.pending).toBe(false);
    fail = false;
    routes.want(moved, { soon: true }); // le même refus : pas de relance d'elle-même
    await vi.runAllTimersAsync();
    expect(routes.shown(moved).error).not.toBeNull();
    routes.want(moved, { force: true }); // « Réessayer »
    await vi.runAllTimersAsync();
    expect(routes.shown(moved).route?.distance_m).toBe(500_000);
  });

  it("sous deux arrêts : pas de trajet, rien ne se demande (A → B, B retiré, ne montre plus A → B)", async () => {
    const fetcher = vi.fn(async () => route(500));
    const routes = new TripRoutes(fetcher, () => {});
    const two = removedTrip(TRIP, "3");
    routes.want(two, { soon: true });
    await vi.runAllTimersAsync();
    expect(routes.shown(two).route).not.toBeNull();
    const one = removedTrip(two, "2");
    routes.want(one);
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(routes.shown(one)).toEqual({ route: null, error: null, pending: false });
    routes.want(two); // revenu à deux : relu (l'ancien n'a pas été gardé)
    await vi.runAllTimersAsync();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("une relecture partie avant un autre geste ne remplace pas celle qui la suit", async () => {
    const answers: Array<(r: TripRoute) => void> = [];
    const routes = new TripRoutes(() => new Promise<TripRoute>((resolve) => answers.push(resolve)), () => {});
    routes.want(TRIP, { soon: true });
    const moved = movedTrip(TRIP, "1", 1, 2);
    routes.want(moved, { soon: true });
    expect(answers).toHaveLength(2);
    answers[1](route(700));
    await vi.runAllTimersAsync();
    answers[0](route(500)); // la plus vieille arrive après
    await vi.runAllTimersAsync();
    expect(routes.shown(moved).route?.distance_m).toBe(700_000);
  });
});

describe("« Sur la route » ne se recherche que si le trajet a changé", () => {
  it("le même trajet : rien ; un de ses lieux ajouté : il prend la clé sans rien demander ; un autre geste : il se recherche", () => {
    const along = { cat: "voir", key: "k1", adopt: false, loading: false };
    expect(alongAfterRoute(along, "k1")).toBe("keep");
    expect(alongAfterRoute({ ...along, cat: "" }, "k2")).toBe("keep"); // fermé
    expect(alongAfterRoute(along, "k2")).toBe("reload");
    expect(alongAfterRoute({ ...along, adopt: true }, "k2")).toBe("adopt");
    expect(alongAfterRoute({ ...along, adopt: true, loading: true }, "k2")).toBe("reload"); // une recherche partie avant
  });
});

describe("les gestes sur un voyage, l'un après l'autre", () => {
  it("chacun attend le précédent ; un refus annule ceux qui attendaient derrière lui", async () => {
    const done: string[] = [];
    const queue = new GestureQueue();
    let release: () => void = () => {};
    const first = queue.run(() => new Promise<void>((resolve) => {
      release = () => {
        done.push("premier");
        resolve();
      };
    }));
    const second = queue.run(async () => {
      done.push("second");
    });
    expect(queue.busy).toBe(true);
    await Promise.resolve();
    expect(done).toEqual([]); // le second attend
    release();
    expect(await first).toBe(true);
    expect(await second).toBe(true);
    expect(done).toEqual(["premier", "second"]);
    expect(queue.busy).toBe(false);

    const refusedOne = queue.run(async () => {
      throw new ApiError(409, "La situation a changé.");
    });
    const after = queue.run(async () => {
      done.push("après le refus");
    });
    await expect(refusedOne).rejects.toMatchObject({ status: 409 });
    expect(await after).toBe(false);
    expect(done).not.toContain("après le refus");
    expect(await queue.run(async () => {
      done.push("un geste neuf");
    })).toBe(true);
    expect(done).toContain("un geste neuf");
  });

  it("un envoi refusé a usé sa clé ; une panne ou un 429, non (on le refait avec la même)", () => {
    expect(refused(new ApiError(409, "Un voyage a 60 arrêts au plus."))).toBe(true);
    expect(refused(new ApiError(400, "Un voyage a un titre."))).toBe(true);
    expect(refused(new ApiError(429, "Trop de demandes."))).toBe(false);
    expect(refused(new ApiError(503, "Le serveur n'a pas pu répondre."))).toBe(false);
    expect(refused(new Error("réseau"))).toBe(false);
  });
});
