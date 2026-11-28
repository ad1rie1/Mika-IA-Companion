import { afterEach, describe, expect, it, vi } from "vitest";
import { Ages, AGES_MS } from "./ages";

describe("les âges avancent d'eux-mêmes, sans rien relire (ADR 0308)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("toutes les 30 s, chaque écran abonné repeint ses âges ; désabonné, plus rien", () => {
    vi.useFakeTimers();
    const ages = new Ages(() => true);
    const paint = vi.fn();
    const off = ages.onTick(paint);
    vi.advanceTimersByTime(AGES_MS - 1);
    expect(paint).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(paint).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2 * AGES_MS);
    expect(paint).toHaveBeenCalledTimes(3);
    off();
    vi.advanceTimersByTime(AGES_MS);
    expect(paint).toHaveBeenCalledTimes(3);
    expect(AGES_MS).toBeLessThanOrEqual(30_000);
  });

  it("une seule minuterie, quel que soit le nombre d'écrans", () => {
    vi.useFakeTimers();
    const ages = new Ages(() => true);
    const a = vi.fn();
    const b = vi.fn();
    ages.onTick(a);
    ages.onTick(b);
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(AGES_MS);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("l'onglet caché ne repeint rien ; un écran qui lève ne fait pas taire les suivants", () => {
    vi.useFakeTimers();
    let shown = false;
    const ages = new Ages(() => shown);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const after = vi.fn();
    ages.onTick(() => {
      throw new Error("en panne");
    });
    ages.onTick(after);
    vi.advanceTimersByTime(AGES_MS);
    expect(after).not.toHaveBeenCalled();
    shown = true;
    vi.advanceTimersByTime(AGES_MS);
    expect(after).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
