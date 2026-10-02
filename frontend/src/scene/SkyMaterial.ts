import * as THREE from "three";
import { MOON_DIR, type DaylightState } from "./Daylight";

/**
 * The sky seen through Mika's window. Drawn on a card behind the window
 * opening, but computed from the *view direction* (fragment − camera), so
 * it behaves like a real sky at infinity: orbiting the camera changes
 * which part of it the window frames, instead of sliding a picture.
 *
 * Gradient + sun glow/disc + crescent moon + twinkling stars + a two-layer
 * city skyline whose windows light up in the evening. Everything is driven
 * by a DaylightState (see Daylight.ts); `uTime` only animates the twinkle.
 * Output is linear HDR (the composer's OutputPass tone-maps it), so the
 * moon and the sun disc can exceed 1 and bloom.
 */

const vertexShader = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`;

const fragmentShader = /* glsl */ `
  uniform vec3 uZenith;
  uniform vec3 uHorizon;
  uniform vec3 uBuildings;
  uniform vec3 uSunDir;
  uniform vec3 uSunColor;
  uniform vec3 uMoonDir;
  uniform float uSunGlow;
  uniform float uStars;
  uniform float uMoon;
  uniform float uCity;
  uniform float uTime;
  varying vec3 vWorld;

  float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
  }
  float hash21(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
  }

  // One skyline layer. Returns 1 inside a building, writes the lit-window
  // amount into 'lit'.
  float skyline(float az, float e, float freq, float seed, float base, float amp, out float lit) {
    float bx = az * freq + seed;
    float id = floor(bx);
    float r = hash11(id * 1.73 + seed);
    float top = base + amp * (0.25 + 0.75 * r * r);
    // a few rooftops get a thin antenna/step
    float step2 = step(0.82, hash11(id * 3.1 + seed)) * step(abs(fract(bx) - 0.5), 0.12) * amp * 0.35;
    float inside = step(e, top + step2);
    // windows: a grid inside the facade, some lit warm
    vec2 g = vec2(fract(bx) * 7.0, (e - base) * 140.0);
    vec2 cell = floor(g);
    vec2 f = fract(g);
    float win = step(0.25, f.x) * step(f.x, 0.75) * step(0.3, f.y) * step(f.y, 0.75);
    float on = step(0.66, hash21(cell + id * 13.0 + seed));
    float margin = step(0.6, cell.x) * step(cell.x, 6.0) * step(e, top - 0.006);
    lit = inside * win * on * margin;
    return inside;
  }

  void main() {
    vec3 dir = normalize(vWorld - cameraPosition);
    float e = dir.y;
    float az = atan(dir.z, -dir.x); // 0 = straight out of the window

    // gradient
    float t = smoothstep(-0.05, 0.6, e);
    vec3 col = mix(uHorizon, uZenith, pow(t, 0.75));

    // sun: wide glow, tight halo, disc
    float sd = max(dot(dir, uSunDir), 0.0);
    col += uSunColor * uSunGlow * (0.12 * pow(sd, 6.0) + 0.3 * pow(sd, 48.0));
    col += uSunColor * uSunGlow * 2.2 * smoothstep(0.9990, 0.9995, sd) * step(-0.02, uSunDir.y);

    // stars (cells in azimuth/elevation), fading toward the horizon glow
    vec2 sp = vec2(az * 70.0, e * 70.0);
    vec2 cell = floor(sp);
    float h = hash21(cell);
    vec2 off = vec2(hash21(cell + 7.1), hash21(cell + 3.7)) - 0.5;
    float d = length(fract(sp) - 0.5 - off * 0.6);
    float star = step(0.94, h) * smoothstep(0.13, 0.0, d);
    float tw = 0.6 + 0.4 * sin(uTime * (1.3 + h * 3.0) + h * 40.0);
    col += vec3(0.9, 0.93, 1.0) * star * tw * uStars * smoothstep(0.04, 0.22, e) * (0.7 + 1.6 * fract(h * 13.0));

    // crescent moon + halo
    float md = dot(dir, uMoonDir);
    float disc = smoothstep(0.99935, 0.9996, md);
    vec3 shifted = normalize(uMoonDir + vec3(0.012, 0.016, -0.008));
    float bite = smoothstep(0.99935, 0.9996, dot(dir, shifted));
    float mdp = max(md, 0.0);
    col += vec3(1.0, 0.95, 0.82) * uMoon * (disc * (1.0 - 0.93 * bite) * 2.6 + pow(mdp, 600.0) * 0.4 + pow(mdp, 40.0) * 0.06);

    // skyline: far hazy layer, then the near one
    float litFar;
    float inFar = skyline(az, e, 34.0, 11.0, -0.01, 0.045, litFar);
    vec3 farCol = mix(uBuildings, uHorizon, 0.5);
    col = mix(col, farCol, inFar);
    col += vec3(1.0, 0.78, 0.45) * litFar * uCity * 0.9;
    float litNear;
    float inNear = skyline(az, e, 15.0, 3.0, -0.03, 0.085, litNear);
    col = mix(col, uBuildings, inNear);
    col += vec3(1.0, 0.8, 0.5) * litNear * uCity * 1.4;

    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

export type SkyMaterial = THREE.ShaderMaterial & {
  uniforms: {
    uZenith: THREE.IUniform<THREE.Color>;
    uHorizon: THREE.IUniform<THREE.Color>;
    uBuildings: THREE.IUniform<THREE.Color>;
    uSunDir: THREE.IUniform<THREE.Vector3>;
    uSunColor: THREE.IUniform<THREE.Color>;
    uMoonDir: THREE.IUniform<THREE.Vector3>;
    uSunGlow: THREE.IUniform<number>;
    uStars: THREE.IUniform<number>;
    uMoon: THREE.IUniform<number>;
    uCity: THREE.IUniform<number>;
    uTime: THREE.IUniform<number>;
  };
};

export function createSkyMaterial(): SkyMaterial {
  const mat = new THREE.ShaderMaterial({
    name: "WindowSky",
    vertexShader,
    fragmentShader,
    uniforms: {
      uZenith: { value: new THREE.Color(0x070a1f) },
      uHorizon: { value: new THREE.Color(0x1b2150) },
      uBuildings: { value: new THREE.Color(0x0a0c20) },
      uSunDir: { value: new THREE.Vector3(-1, -0.3, 0).normalize() },
      uSunColor: { value: new THREE.Color(0xffc890) },
      uMoonDir: { value: MOON_DIR.clone() },
      uSunGlow: { value: 0 },
      uStars: { value: 1 },
      uMoon: { value: 1 },
      uCity: { value: 1 },
      uTime: { value: 0 },
    },
    depthWrite: true,
    fog: false,
  });
  return mat as SkyMaterial;
}

/** Push a daylight state into the sky uniforms. */
export function applyDaylightToSky(mat: SkyMaterial, d: DaylightState): void {
  const u = mat.uniforms;
  u.uZenith.value.copy(d.zenith);
  u.uHorizon.value.copy(d.horizon);
  u.uBuildings.value.copy(d.buildings);
  u.uSunDir.value.copy(d.sunDir);
  // the sun disc takes the horizon's warmth near sunset, white at noon
  u.uSunColor.value.setRGB(1, 0.92, 0.78).lerp(d.horizon, 0.35);
  u.uSunGlow.value = d.sunGlow;
  u.uStars.value = d.stars;
  u.uMoon.value = d.moon;
  u.uCity.value = d.city;
}
