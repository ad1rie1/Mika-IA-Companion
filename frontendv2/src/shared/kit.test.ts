/**
 * Une lecture gardée (`Cached`) : ce qu'une écriture a rendu (`put`, une fiche actualisée) ne se fait pas écraser par une
 * lecture partie avant elle et revenue après — elle était plus vieille ; une invalidation pendant une lecture en vol
 * (le direct) est suivie d'une autre lecture.
 * Et les dates en mots : depuis quand, jusqu'à quand, quel jour (`ago`, `remaining`, `dayWords`, `dateWords`).
 */
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/moi";
import { ago, Cached, dateWords, dayWords, remaining } from "./kit";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

describe("une lecture gardée et une écriture (R2-W09)", () => {
  it("une lecture partie avant un put, revenue après, ne l'écrase pas", async () => {
    let answer!: (v: string) => void;
    const c = new Cached<string>(() => new Promise((resolve) => { answer = resolve; }), 60_000);
    const pending = c.load(true);
    c.put("actualisée");
    answer("lue avant");
    expect(await pending).toBe("actualisée");
    expect(c.value).toBe("actualisée");
  });

  it("invalidée pendant une lecture (le direct, ADR 0308) : la lecture demandée ensuite la suit, une seule fois", async () => {
    let n = 0;
    const answers: Array<() => void> = [];
    const c = new Cached<string>(() => new Promise((resolve) => {
      const k = ++n;
      answers.push(() => resolve(`lue ${k}`));
    }), 60_000);
    const first = c.load();
    c.invalidate(); // ce qui a changé a pu partir après elle
    const next = c.load();
    const again = c.load();
    expect(n).toBe(1);
    answers.shift()!();
    expect(await first).toBe("lue 1");
    await Promise.resolve();
    expect(n).toBe(2);
    answers.shift()!();
    expect(await next).toBe("lue 2");
    expect(await again).toBe("lue 2");
    // à jour : la suivante sert ce qu'elle a, sans relire
    expect(await c.load()).toBe("lue 2");
    expect(n).toBe(2);
  });

  it("invalidée pendant une lecture que personne ne redemande : la prochaine repart du serveur", async () => {
    let n = 0;
    const c = new Cached<string>(async () => `lue ${++n}`, 60_000);
    const first = c.load();
    c.invalidate();
    await first;
    expect(await c.load()).toBe("lue 2");
  });

  it("une lecture partie après le put fait foi, comme avant", async () => {
    let n = 0;
    const c = new Cached<string>(async () => `lue ${++n}`, 60_000);
    c.put("actualisée");
    expect(await c.load(true)).toBe("lue 1");
    expect(c.value).toBe("lue 1");
  });
});

describe("les dates et la lecture gardée", () => {
  it("dit depuis quand, jusqu'à quand, et quel jour", () => {
    expect(ago(at(4, 14, 57), NOW)).toBe("il y a 3 min");
    expect(ago(at(4, 12, 0), NOW)).toBe("il y a 3 h");
    expect(ago(at(3, 22, 10), NOW)).toBe("hier à 22:10");
    expect(ago(at(1, 9, 0), NOW)).toBe("le 1 novembre");
    expect(ago(0, NOW)).toBe("");
    expect(remaining(at(4, 16, 52), NOW)).toBe("dans 1 h 52");
    expect(remaining(at(4, 15, 4), NOW)).toBe("dans 4 min");
    expect(remaining(at(4, 14, 0), NOW)).toBe("échue");
    expect(dayWords(at(2, 9, 0), NOW)).toBe("lundi 2 novembre");
    expect(dateWords(new Date(2025, 8, 2).getTime(), NOW)).toBe("2 septembre 2025");
  });

  it("ne relit qu'une fois à la fois, garde la valeur, et ne change de version que si elle change", async () => {
    let calls = 0;
    let value = { n: 1 };
    const c = new Cached(async () => {
      calls += 1;
      return value;
    }, 60_000);
    await Promise.all([c.load(), c.load()]);
    expect(calls).toBe(1);
    const v1 = c.version;
    await c.load(true);
    expect(c.version).toBe(v1);
    value = { n: 2 };
    await c.load(true);
    expect(c.version).toBe(v1 + 1);
    expect(c.value).toEqual({ n: 2 });
    const failing = new Cached<{ n: number }>(async () => {
      throw new Error("non");
    });
    await failing.load();
    expect(failing.settled).toBe(true);
    expect(failing.value).toBeNull();
  });

  it("une relecture forcée pendant une lecture en cours la suit : ce qu'on vient d'écrire se lit", async () => {
    let calls = 0;
    const c = new Cached(async () => ({ n: ++calls }), 60_000);
    const before = c.load(); // partie avant l'écriture
    const after = c.load(true); // demandée après l'écriture : une autre lecture, qui suit
    const again = c.load(true);
    expect(await before).toEqual({ n: 1 });
    expect(await after).toEqual({ n: 2 });
    expect(await again).toEqual({ n: 2 }); // une seule relecture pour les deux
    expect(calls).toBe(2);
    expect(c.value).toEqual({ n: 2 });
  });

  it("une relecture refusée garde la valeur d'avant, sauf un 404 : ce qui n'existe plus ne se montre plus", async () => {
    let fail: ApiError | null = null;
    const c = new Cached(async () => {
      if (fail) throw fail;
      return { n: 1 };
    }, 60_000);
    await c.load();
    fail = new ApiError(503, "Les itinéraires ne sont pas réglés.");
    await c.load(true);
    expect(c.value).toEqual({ n: 1 });
    expect(c.error).toBe(fail);
    const v = c.version;
    fail = new ApiError(404, "Introuvable.");
    await c.load(true);
    expect(c.value).toBeNull();
    expect(c.version).toBe(v + 1);
    fail = null;
    await c.load(true);
    expect(c.value).toEqual({ n: 1 });
    expect(c.error).toBeNull();
  });
});
