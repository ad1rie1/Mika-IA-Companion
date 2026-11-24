/**
 * Une lecture gardée (`Cached`) : ce qu'une écriture a rendu (`put`, une fiche actualisée) ne se fait pas écraser par une
 * lecture partie avant elle et revenue après — elle était plus vieille ; une invalidation pendant une lecture en vol
 * (le direct) est suivie d'une autre lecture.
 */
import { describe, expect, it } from "vitest";
import { Cached } from "./kit";

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
