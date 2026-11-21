/**
 * Une lecture gardée (`Cached`) : ce qu'une écriture a rendu (`put`, une fiche actualisée) ne se fait pas écraser par une
 * lecture partie avant elle et revenue après — elle était plus vieille.
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

  it("une lecture partie après le put fait foi, comme avant", async () => {
    let n = 0;
    const c = new Cached<string>(async () => `lue ${++n}`, 60_000);
    c.put("actualisée");
    expect(await c.load(true)).toBe("lue 1");
    expect(c.value).toBe("lue 1");
  });
});
