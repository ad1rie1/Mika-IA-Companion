import * as THREE from "three";

/**
 * What the sky outside Mika's window looks like at a given local hour, and
 * how much of it comes into the room. Pure: no scene, no DOM — the sky
 * shader, the window lights and the floor light patch all read one state.
 *
 * The old version switched between five colours on the hour; here every
 * value is interpolated between keyframes with a smoothstep, so 18:59 and
 * 19:01 are the same evening and the light drifts while you watch.
 *
 * The window is on the room's left wall and looks toward -X ("west"): the
 * sun sets in it, it rises behind the room.
 */

export interface DaylightState {
  /** Sky colour straight up and at the horizon (linear working space). */
  zenith: THREE.Color;
  horizon: THREE.Color;
  /** Colour of the distant buildings' silhouettes. */
  buildings: THREE.Color;
  /** Colour + intensity of the light the window throws into the room. */
  light: THREE.Color;
  lightIntensity: number;
  /** Sun direction (unit, world) and how much of its glow is drawn. */
  sunDir: THREE.Vector3;
  sunGlow: number;
  /** 0..1 amounts drawn by the sky shader. */
  stars: number;
  moon: number;
  /** Lit windows in the skyline. */
  city: number;
  /** Opacity of the window-shaped light patch on the floor. */
  patch: number;
  /** 0 at night, 1 in full daylight — extra fill for the room. */
  day: number;
}

interface Key {
  h: number;
  zenith: number;
  horizon: number;
  buildings: number;
  light: number;
  intensity: number;
  sunGlow: number;
  stars: number;
  moon: number;
  city: number;
  patch: number;
  day: number;
}

// prettier-ignore
const KEYS: Key[] = [
  { h: 0,     zenith: 0x070a1f, horizon: 0x1b2150, buildings: 0x0a0c20, light: 0x2a3670, intensity: 0.5,  sunGlow: 0,    stars: 1,    moon: 1,    city: 0.8,  patch: 0.16, day: 0 },
  { h: 4.5,   zenith: 0x070a1f, horizon: 0x1b2150, buildings: 0x0a0c20, light: 0x2a3670, intensity: 0.5,  sunGlow: 0,    stars: 1,    moon: 1,    city: 0.35, patch: 0.16, day: 0 },
  { h: 5.6,   zenith: 0x141c45, horizon: 0x4f3d70, buildings: 0x15142e, light: 0x3c4282, intensity: 0.6,  sunGlow: 0.15, stars: 0.55, moon: 0.6,  city: 0.45, patch: 0.08, day: 0.1 },
  { h: 6.6,   zenith: 0x3a4f8f, horizon: 0xffb08a, buildings: 0x3b3552, light: 0xffc9a0, intensity: 1.1,  sunGlow: 0.55, stars: 0.08, moon: 0.1,  city: 0.25, patch: 0.14, day: 0.45 },
  { h: 8.0,   zenith: 0x4f86d0, horizon: 0xdcd0c8, buildings: 0x76809e, light: 0xd8e4ff, intensity: 1.35, sunGlow: 0.3,  stars: 0,    moon: 0,    city: 0,    patch: 0.22, day: 0.85 },
  { h: 12.0,  zenith: 0x3d7fd6, horizon: 0x9cc4ec, buildings: 0x7d89a6, light: 0xbfd9ff, intensity: 1.5,  sunGlow: 0.2,  stars: 0,    moon: 0,    city: 0,    patch: 0.3,  day: 1 },
  { h: 16.5,  zenith: 0x4a80cc, horizon: 0xd8c8b0, buildings: 0x777b98, light: 0xffe6c4, intensity: 1.45, sunGlow: 0.45, stars: 0,    moon: 0,    city: 0,    patch: 0.34, day: 0.95 },
  { h: 18.4,  zenith: 0x4a5fa8, horizon: 0xffb070, buildings: 0x5a4a6a, light: 0xffb070, intensity: 1.4,  sunGlow: 1,    stars: 0,    moon: 0,    city: 0.1,  patch: 0.4,  day: 0.75 },
  { h: 19.4,  zenith: 0x2e2f6e, horizon: 0xff7a52, buildings: 0x2a2040, light: 0xff8c5a, intensity: 1.2,  sunGlow: 1,    stars: 0.05, moon: 0.1,  city: 0.45, patch: 0.32, day: 0.45 },
  { h: 20.4,  zenith: 0x141a48, horizon: 0x6a4a8a, buildings: 0x15132e, light: 0x5a5fb0, intensity: 0.8,  sunGlow: 0.15, stars: 0.5,  moon: 0.7,  city: 0.9,  patch: 0.1,  day: 0.12 },
  { h: 21.8,  zenith: 0x080b22, horizon: 0x1f2456, buildings: 0x0b0d22, light: 0x2c3874, intensity: 0.55, sunGlow: 0,    stars: 1,    moon: 1,    city: 1,    patch: 0.16, day: 0 },
  { h: 24,    zenith: 0x070a1f, horizon: 0x1b2150, buildings: 0x0a0c20, light: 0x2a3670, intensity: 0.5,  sunGlow: 0,    stars: 1,    moon: 1,    city: 0.8,  patch: 0.16, day: 0 },
];

/** Fixed night-sky position of the moon: out of the window, a little up. */
export const MOON_DIR = new THREE.Vector3(-0.92, 0.24, -0.3).normalize();

const SUNRISE = 6.5;
const SUNSET = 19.6;

export function createDaylightState(): DaylightState {
  return {
    zenith: new THREE.Color(),
    horizon: new THREE.Color(),
    buildings: new THREE.Color(),
    light: new THREE.Color(),
    lightIntensity: 0,
    sunDir: new THREE.Vector3(),
    sunGlow: 0,
    stars: 0,
    moon: 0,
    city: 0,
    patch: 0,
    day: 0,
  };
}

/** Fractional local hour of a Date, e.g. 19.5 for 19:30. */
export function hourOf(date: Date): number {
  return date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
}

const ca = new THREE.Color();
const cb = new THREE.Color();

function mixHex(out: THREE.Color, a: number, b: number, t: number): void {
  ca.setHex(a);
  cb.setHex(b);
  out.copy(ca).lerp(cb, t);
}

/**
 * Sun direction for an hour: rises behind the room (+X), crosses the
 * southern sky (-Z), sets straight out of the window (-X) at SUNSET.
 */
export function sunDirection(hour: number, out = new THREE.Vector3()): THREE.Vector3 {
  const u = (hour - SUNRISE) / (SUNSET - SUNRISE); // 0 at sunrise, 1 at sunset
  const a = Math.PI * u;
  // Elevation peaks at noon; below the horizon at night (clamped so the
  // glow simply sinks rather than circling under the floor).
  const el = Math.max(-0.35, Math.sin(Math.PI * u)) * 1.05;
  const hx = Math.cos(a);
  const hz = -0.55 * Math.sin(Math.max(0, Math.min(Math.PI, a))) - 0.15;
  const len = Math.hypot(hx, hz) || 1;
  const c = Math.cos(el);
  return out.set((hx / len) * c, Math.sin(el), (hz / len) * c).normalize();
}

/** Daylight at a fractional local hour [0, 24). */
export function daylightAt(hour: number, out: DaylightState = createDaylightState()): DaylightState {
  const h = ((hour % 24) + 24) % 24;
  let i = 0;
  while (i < KEYS.length - 2 && KEYS[i + 1].h <= h) i++;
  const k0 = KEYS[i];
  const k1 = KEYS[i + 1];
  const raw = (h - k0.h) / (k1.h - k0.h);
  const t = raw * raw * (3 - 2 * raw); // smoothstep between keyframes
  const lerp = (a: number, b: number) => a + (b - a) * t;

  mixHex(out.zenith, k0.zenith, k1.zenith, t);
  mixHex(out.horizon, k0.horizon, k1.horizon, t);
  mixHex(out.buildings, k0.buildings, k1.buildings, t);
  mixHex(out.light, k0.light, k1.light, t);
  out.lightIntensity = lerp(k0.intensity, k1.intensity);
  out.sunGlow = lerp(k0.sunGlow, k1.sunGlow);
  out.stars = lerp(k0.stars, k1.stars);
  out.moon = lerp(k0.moon, k1.moon);
  out.city = lerp(k0.city, k1.city);
  out.patch = lerp(k0.patch, k1.patch);
  out.day = lerp(k0.day, k1.day);
  sunDirection(h, out.sunDir);
  return out;
}
