import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { createDaylightState, daylightAt, hourOf, MOON_DIR, sunDirection } from "../Daylight";

/** Distance between two daylight states, colours + scalars. */
function gap(a: number, b: number): number {
  const s = daylightAt(a);
  const t = daylightAt(b);
  const dc = (x: THREE.Color, y: THREE.Color) =>
    Math.abs(x.r - y.r) + Math.abs(x.g - y.g) + Math.abs(x.b - y.b);
  return (
    dc(s.zenith, t.zenith) +
    dc(s.horizon, t.horizon) +
    dc(s.light, t.light) +
    Math.abs(s.lightIntensity - t.lightIntensity) +
    Math.abs(s.stars - t.stars) +
    Math.abs(s.city - t.city)
  );
}

describe("daylightAt", () => {
  it("is continuous: no jump on the hour, anywhere in the day", () => {
    // The old window switched colour in five hard steps; one minute apart
    // must now always look (nearly) the same.
    for (let h = 0; h < 24; h += 0.25) {
      expect(gap(h, h + 1 / 60)).toBeLessThan(0.15);
    }
  });

  it("wraps around midnight", () => {
    expect(gap(23.99, 0.0)).toBeLessThan(0.02);
    expect(gap(24.5, 0.5)).toBe(0);
    expect(gap(-1, 23)).toBe(0);
  });

  it("has stars and a moon at night, none at noon", () => {
    const night = daylightAt(1);
    const noon = daylightAt(12);
    expect(night.stars).toBeGreaterThan(0.9);
    expect(night.moon).toBeGreaterThan(0.9);
    expect(noon.stars).toBe(0);
    expect(noon.moon).toBe(0);
    expect(noon.lightIntensity).toBeGreaterThan(night.lightIntensity);
    expect(noon.day).toBe(1);
    expect(night.day).toBe(0);
  });

  it("gives a warm horizon at sunset and a blue sky at noon", () => {
    const sunset = daylightAt(19.4);
    expect(sunset.horizon.r).toBeGreaterThan(sunset.horizon.b);
    const noon = daylightAt(12);
    expect(noon.zenith.b).toBeGreaterThan(noon.zenith.r);
  });

  it("lights the city windows in the evening, not in the afternoon", () => {
    expect(daylightAt(21).city).toBeGreaterThan(0.8);
    expect(daylightAt(14).city).toBe(0);
  });

  it("reuses the output state", () => {
    const out = createDaylightState();
    expect(daylightAt(8, out)).toBe(out);
  });
});

describe("sunDirection", () => {
  it("sets straight out of the window (-X) at the horizon", () => {
    const d = sunDirection(19.6);
    expect(d.x).toBeLessThan(-0.9);
    expect(Math.abs(d.y)).toBeLessThan(0.05);
  });

  it("is high at noon and below the horizon at night", () => {
    expect(sunDirection(13).y).toBeGreaterThan(0.7);
    expect(sunDirection(1).y).toBeLessThan(0);
    expect(sunDirection(13).length()).toBeCloseTo(1, 5);
  });

  it("is just above the window's horizon an hour before sunset", () => {
    const d = sunDirection(18.8);
    expect(d.y).toBeGreaterThan(0.05);
    expect(d.y).toBeLessThan(0.4);
    expect(d.x).toBeLessThan(-0.8);
  });
});

describe("helpers", () => {
  it("hourOf is fractional", () => {
    expect(hourOf(new Date(2026, 0, 1, 19, 30, 0))).toBeCloseTo(19.5, 6);
  });

  it("the moon looks out of the window", () => {
    expect(MOON_DIR.x).toBeLessThan(-0.8);
    expect(MOON_DIR.y).toBeGreaterThan(0);
  });
});
