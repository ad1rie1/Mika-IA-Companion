import { describe, expect, it } from "vitest";
import { dayAndClock, shortWhen } from "./dates";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

describe("les heures et les jours en court", () => {
  it("shortWhen : l'heure aujourd'hui, « hier », le jour de la semaine, puis la date", () => {
    expect(shortWhen(at(4, 13, 31), NOW)).toBe("13:31");
    expect(shortWhen(at(3, 21, 41), NOW)).toBe("hier");
    expect(shortWhen(at(2, 9, 0), NOW)).toBe("lun.");
    expect(shortWhen(at(28 - 31, 9, 0), NOW)).toBe("28 oct.");
    expect(shortWhen(new Date(2025, 0, 2).getTime(), NOW)).toBe("2 janv. 2025");
    expect(shortWhen(0, NOW)).toBe("");
    expect(dayAndClock(at(4, 14, 5), NOW)).toBe("aujourd'hui 14:05");
    expect(dayAndClock(at(3, 21, 41), NOW)).toBe("hier 21:41");
  });
});
