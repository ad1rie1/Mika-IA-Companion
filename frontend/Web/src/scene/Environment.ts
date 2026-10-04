import * as THREE from "three";
import type {
  AnchorId,
  EnvironmentAnchor,
  SleepPhase,
} from "../types";
import { ROOM, type LightAnchorName, type RoomParts } from "./RoomParts";
import { buildProceduralRoom } from "./ProceduralRoom";
import { loadRoomModel, ROOM_URL } from "./RoomModel";
import { createDaylightState, daylightAt, hourOf } from "./Daylight";
import { applyDaylightToSky, createSkyMaterial, type SkyMaterial } from "./SkyMaterial";

// Per-phase multipliers applied to all ambient / directional / accent
// light intensities. Deep sleep = almost dark blue room.
const PHASE_LIGHT_MULTIPLIER: Record<SleepPhase, number> = {
  awake: 1.0,
  light_sleep: 0.55,
  rem: 0.4,
  deep_sleep: 0.22,
};

// Night tint applied to the scene background when asleep. RGB in THREE.
const PHASE_BG_COLOR: Record<SleepPhase, number> = {
  awake: 0x1a1a2e, // the scene's default
  light_sleep: 0x131230,
  rem: 0x0f0e28,
  deep_sleep: 0x08081b,
};

const LIGHT_EASE_DURATION = 1.8; // seconds
const ENV_INTENSITY_BASE = 0.3; // scene.environment contribution when awake

// Hemisphere fill: a little more of it in daytime, when the window floods
// the room (the room lamps stay the same).
const HEMI_BASE = 0.45;
const HEMI_DAY_BOOST = 0.22;

// Outside light (window glow, sun/moon spot, floor patch) follows the hour,
// not Mika's sleep: drawing the curtains is not what falling asleep does,
// and a dark room with moonlight on the floor is exactly the sleeping look.
const SUN_SPOT_SCALE = 2.6;
const DAYLIGHT_REFRESH_S = 10;
const WHITE = new THREE.Color(0xffffff);

// Glow levels are above the bloom threshold (SceneManager) on purpose:
// bulbs and strips are what should bloom, nothing else.
const FAIRY_BULB_INTENSITY = 2.4;
const LED_INTENSITY = 1.7;

// Default light positions (the procedural room); the GLB overrides them
// with its LightAnchor_* empties so the light sits in the lamp it models.
const DEFAULT_ANCHORS: Record<LightAnchorName, THREE.Vector3> = {
  DeskLamp: new THREE.Vector3(-1.9, 1.15, -4.0),
  BedLamp: new THREE.Vector3(-3.6, 0.75, 2.7),
  Ceiling: new THREE.Vector3(0, 2.3, -0.5),
  Monitor: new THREE.Vector3(-1.4, 1.25, -3.9),
  Window: new THREE.Vector3(ROOM.minX + 0.6, 1.8, -1.2),
};

interface TrackedLight {
  light: THREE.Light;
  baseIntensity: number;
}

interface TrackedEmissive {
  mat: THREE.MeshStandardMaterial;
  base: number;
}

interface FairyString {
  mesh: THREE.InstancedMesh;
  colors: THREE.Color[];
  phases: number[];
}

export class Environment {
  public group: THREE.Group;
  /** Resolves once a room is in the scene: the authored GLB, or the
   * procedural fallback when it could not be loaded. Never rejects. */
  public readonly ready: Promise<"glb" | "procedural">;

  private scene: THREE.Scene;

  private trackedLights: TrackedLight[] = [];
  private trackedEmissives: TrackedEmissive[] = [];
  private fairyStrings: FairyString[] = [];
  private ledMaterials: THREE.MeshStandardMaterial[] = [];
  private ledLights: THREE.PointLight[] = [];
  private namedLights: Partial<Record<LightAnchorName, THREE.Light>> = {};

  private sleepPhase: SleepPhase = "awake";
  private currentMultiplier = 1.0;
  private targetMultiplier = 1.0;
  private currentBgColor = new THREE.Color(PHASE_BG_COLOR.awake);
  private targetBgColor = new THREE.Color(PHASE_BG_COLOR.awake);

  // Outside light
  private skyMat: SkyMaterial;
  private daylight = createDaylightState();
  private windowLight!: THREE.PointLight;
  private sunSpot!: THREE.SpotLight;
  private floorPatch!: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  private hemi!: TrackedLight;

  // Room-bound animated surfaces (filled when the room arrives)
  private monitorScreen: THREE.MeshStandardMaterial | null = null;
  private monitorBase = 0.55;
  private clockHands: RoomParts["clockHands"] = null;
  private clockTimer = 1;

  private dust!: THREE.Points;
  private dustPhase!: Float32Array;
  private dustMat!: THREE.PointsMaterial;

  private time = 0;
  private daylightTimer = 0;
  private tmpColor = new THREE.Color();

  constructor(scene: THREE.Scene) {
    this.scene = scene;
    this.group = new THREE.Group();
    this.group.name = "Environment";
    scene.add(this.group);

    this.skyMat = createSkyMaterial();
    this.createLighting(scene);
    this.createOutsideLight(scene);
    this.createFairyLights();
    this.createLedStrips();
    this.createDust();
    this.refreshDaylight();

    // The room itself loads in the background: lights, sky and fairy
    // lights are already up, the furniture appears when the GLB is parsed.
    this.ready = this.loadRoom();
  }

  /** Drive scene lights + background color from Mika's sleep phase. */
  setSleepPhase(phase: SleepPhase): void {
    if (this.sleepPhase === phase) return;
    this.sleepPhase = phase;
    this.targetMultiplier = PHASE_LIGHT_MULTIPLIER[phase];
    this.targetBgColor = new THREE.Color(PHASE_BG_COLOR[phase]);
  }

  /**
   * v2 locomotion seam: named walk-to targets tied to the furniture this
   * class positions. Returns undefined until the anchor table ships with
   * the locomotion work. Coordinates for the future table (room.glb):
   *   bed_lie:      position [-3.35, 0.42, 1.3] (mattress top; the pillow is
   *                 at the +Z end, by the bedside table), pose "lie"
   *   desk_sit:     position [-1.4, 0, -3.3] (the "DeskChair" origin), pose "sit"
   *   window_stand: position [2.5, 0, -3.8], pose "stand"
   */
  getAnchor(_id: AnchorId): EnvironmentAnchor | undefined {
    return undefined;
  }

  /** Called by the main update loop. Eases lights + bg, animates the room. */
  update(delta: number): void {
    this.time += delta;
    const rate = Math.min(1, (delta / LIGHT_EASE_DURATION) * 4);
    const m = this.currentMultiplier;

    const diff = this.targetMultiplier - m;
    if (Math.abs(diff) > 0.001) {
      this.currentMultiplier += diff * rate;
      this.applyMultiplier();
    }

    // Ease background color toward target
    if (!this.currentBgColor.equals(this.targetBgColor)) {
      this.currentBgColor.lerp(this.targetBgColor, rate);
      if (this.scene.background instanceof THREE.Color) {
        this.scene.background.copy(this.currentBgColor);
      }
      if (this.scene.fog && this.scene.fog instanceof THREE.Fog) {
        this.scene.fog.color.copy(this.currentBgColor);
      }
    }

    // LED strips: slow indigo <-> violet hue drift.
    const hue = 0.68 + 0.08 * Math.sin(this.time * 0.15);
    const ledColor = this.tmpColor.setHSL(hue, 0.7, 0.6);
    for (const mat of this.ledMaterials) {
      mat.emissive.copy(ledColor);
      mat.emissiveIntensity = LED_INTENSITY * m;
    }
    for (const l of this.ledLights) l.color.copy(ledColor);

    // Monitor: faint screen flicker, like content changing.
    if (this.monitorScreen) {
      this.monitorScreen.emissiveIntensity =
        this.monitorBase *
        (1 + 0.06 * Math.sin(this.time * 13.0) + 0.04 * Math.sin(this.time * 7.3)) *
        m;
    }

    // Fairy lights twinkle independently (one instanced draw per string).
    for (const s of this.fairyStrings) {
      for (let i = 0; i < s.colors.length; i++) {
        const k = FAIRY_BULB_INTENSITY * (0.55 + 0.45 * Math.sin(this.time * 2.2 + s.phases[i])) * m;
        s.mesh.setColorAt(i, this.tmpColor.copy(s.colors[i]).multiplyScalar(k));
      }
      if (s.mesh.instanceColor) s.mesh.instanceColor.needsUpdate = true;
    }

    // Dust motes drift upward with a lazy sideways wobble.
    const pos = this.dust.geometry.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      const phase = this.dustPhase[i];
      let y = pos.getY(i) + delta * 0.03;
      if (y > 2.9) y = 0.25;
      pos.setY(i, y);
      pos.setX(i, pos.getX(i) + Math.sin(this.time * 0.4 + phase) * delta * 0.02);
    }
    pos.needsUpdate = true;
    this.dustMat.opacity = 0.3 * m;

    // Sky: twinkle every frame, colours with the real hour.
    this.skyMat.uniforms.uTime.value = this.time;
    this.daylightTimer += delta;
    if (this.daylightTimer > DAYLIGHT_REFRESH_S) {
      this.daylightTimer = 0;
      this.refreshDaylight();
    }

    // Wall clock shows the real time.
    this.clockTimer += delta;
    if (this.clockHands && this.clockTimer > 0.5) {
      this.clockTimer = 0;
      const now = new Date();
      const min = now.getMinutes() + now.getSeconds() / 60;
      const hr = (now.getHours() % 12) + min / 60;
      // hands face +Z: clockwise seen from the room is negative about Z
      this.clockHands.hour.rotation.z = -(hr / 12) * Math.PI * 2;
      this.clockHands.minute.rotation.z = -(min / 60) * Math.PI * 2;
    }
  }

  private track(light: THREE.Light): TrackedLight {
    const t = { light, baseIntensity: light.intensity };
    this.trackedLights.push(t);
    return t;
  }

  private applyMultiplier(): void {
    const m = this.currentMultiplier;
    for (const tl of this.trackedLights) {
      tl.light.intensity = tl.baseIntensity * m;
    }
    for (const te of this.trackedEmissives) {
      te.mat.emissiveIntensity = te.base * m;
    }
    if ("environmentIntensity" in this.scene) {
      (this.scene as any).environmentIntensity = ENV_INTENSITY_BASE * m;
    }
  }

  // ---------------------------------------------------------------- room

  private async loadRoom(): Promise<"glb" | "procedural"> {
    try {
      const parts = await loadRoomModel(ROOM_URL);
      this.adoptRoom(parts);
      return "glb";
    } catch (err) {
      console.warn("[Environment] room.glb unavailable, using the procedural room:", err);
      this.adoptRoom(buildProceduralRoom());
      return "procedural";
    }
  }

  private adoptRoom(parts: RoomParts): void {
    this.group.add(parts.root);
    if (parts.windowSky) {
      parts.windowSky.material = this.skyMat;
      parts.windowSky.castShadow = false;
      parts.windowSky.receiveShadow = false;
    }
    this.monitorScreen = parts.monitorScreen;
    if (this.monitorScreen) this.monitorBase = this.monitorScreen.emissiveIntensity;
    for (const mat of parts.emissives) {
      this.trackedEmissives.push({ mat, base: mat.emissiveIntensity });
    }
    for (const [name, p] of Object.entries(parts.lightAnchors)) {
      const light = this.namedLights[name as LightAnchorName];
      if (light && p) light.position.copy(p);
    }
    this.clockHands = parts.clockHands;
    this.clockTimer = 1;
    this.applyMultiplier();
  }

  // ------------------------------------------------------- outside light

  private createOutsideLight(scene: THREE.Scene) {
    // The glow the window throws into the room (colour/intensity by hour).
    this.windowLight = new THREE.PointLight(0x4a5fa8, 0.8, 8, 1.6);
    this.windowLight.position.copy(DEFAULT_ANCHORS.Window);
    scene.add(this.windowLight);
    this.namedLights.Window = this.windowLight;

    // Sun/moon beam through the window, down onto the floor. Placed outside
    // the left wall: the wall's inner face looks away from it and stays
    // unlit, the floor, sill and reveal catch it.
    this.sunSpot = new THREE.SpotLight(0xffffff, 1, 11, 0.42, 0.85, 1.2);
    this.sunSpot.position.set(ROOM.minX - 2.2, 3.7, -1.2);
    this.sunSpot.target.position.set(-1.6, 0, -1.2);
    scene.add(this.sunSpot);
    scene.add(this.sunSpot.target);

    // The window's shape laid on the floor where the beam lands: four
    // soft panes split by the mullions (additive, so it only brightens).
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, 128, 128);
    ctx.filter = "blur(5px)";
    ctx.fillStyle = "#fff";
    const pad = 14;
    const gap = 6;
    const half = (128 - 2 * pad - gap) / 2;
    for (const px of [pad, pad + half + gap]) {
      for (const py of [pad, pad + half + gap]) ctx.fillRect(px, py, half, half);
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const patchMat = new THREE.MeshBasicMaterial({
      map: tex,
      color: 0xffffff,
      transparent: true,
      opacity: 0.2,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    // Beam ~40° high through a 1.1 m tall opening: lands 1.3 m long, 1.4 m wide.
    this.floorPatch = new THREE.Mesh(new THREE.PlaneGeometry(1.35, 1.4), patchMat);
    this.floorPatch.rotation.x = -Math.PI / 2;
    this.floorPatch.position.set(-1.95, 0.021, -1.2);
    this.floorPatch.renderOrder = 2;
    this.floorPatch.name = "WindowLightPatch";
    this.group.add(this.floorPatch);
  }

  /** Window glow, sky, sun/moon beam and floor patch follow the real hour,
   * interpolated continuously (see Daylight.ts). */
  private refreshDaylight(): void {
    const d = daylightAt(hourOf(new Date()), this.daylight);
    applyDaylightToSky(this.skyMat, d);

    this.windowLight.color.copy(d.light);
    this.windowLight.intensity = d.lightIntensity;

    this.sunSpot.color.copy(d.light);
    this.sunSpot.intensity = d.lightIntensity * SUN_SPOT_SCALE * (0.35 + 0.65 * d.day + 0.3 * d.moon);

    // moonlight is dim but white-ish on a floor; the window colour alone
    // (deep blue at night) would vanish
    this.floorPatch.material.color.copy(d.light).lerp(WHITE, 0.45);
    this.floorPatch.material.opacity = d.patch;

    this.hemi.baseIntensity = HEMI_BASE + HEMI_DAY_BOOST * d.day;
    this.hemi.light.intensity = this.hemi.baseIntensity * this.currentMultiplier;
  }

  // -------------------------------------------------------- fairy lights

  /** A sagging string of twinkling bulbs: wire + one instanced bulb mesh. */
  private addFairyString(
    from: THREE.Vector3,
    to: THREE.Vector3,
    sag: number,
    bulbs: number,
    palette: number[],
    seed: number
  ) {
    const along = (t: number) =>
      new THREE.Vector3().lerpVectors(from, to, t).setY(
        from.y + (to.y - from.y) * t - Math.sin(Math.PI * t) * sag
      );
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= 40; i++) pts.push(along(i / 40));
    const wire = new THREE.Mesh(
      new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 80, 0.0025, 4, false),
      new THREE.MeshStandardMaterial({ color: 0x2a2a38, roughness: 0.6 })
    );
    wire.name = "FairyWire";
    this.group.add(wire);

    const mesh = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.022, 10, 8),
      new THREE.MeshBasicMaterial({ color: 0xffffff }),
      bulbs
    );
    mesh.name = "FairyBulbs";
    const colors: THREE.Color[] = [];
    const phases: number[] = [];
    const m = new THREE.Matrix4();
    for (let i = 0; i < bulbs; i++) {
      const p = along((i + 0.5) / bulbs);
      p.y -= 0.035; // bulbs hang under the wire
      m.makeTranslation(p.x, p.y, p.z);
      mesh.setMatrixAt(i, m);
      const c = new THREE.Color(palette[i % palette.length]);
      colors.push(c);
      phases.push(i * 1.37 + seed);
      mesh.setColorAt(i, c);
    }
    mesh.instanceMatrix.needsUpdate = true;
    this.group.add(mesh);
    this.fairyStrings.push({ mesh, colors, phases });
  }

  private createFairyLights() {
    const warm = [0xfff2cc, 0xffb0d0, 0xa8b4ff];
    // Across the back wall, above the desk, poster and shelves.
    this.addFairyString(
      new THREE.Vector3(-3.6, 2.75, ROOM.minZ + 0.08),
      new THREE.Vector3(3.6, 2.75, ROOM.minZ + 0.08),
      0.28,
      22,
      warm,
      0
    );
    // Over the bed, along the left wall.
    this.addFairyString(
      new THREE.Vector3(ROOM.minX + 0.07, 2.1, 0.3),
      new THREE.Vector3(ROOM.minX + 0.07, 2.1, 2.3),
      0.16,
      12,
      [0xffd9a8, 0xffb0d0],
      5.3
    );
  }

  // ---------------------------------------------------------- LED strips

  private createLedStrips() {
    const y = ROOM.height - 0.08;
    const mk = (w: number, d: number, x: number, z: number) => {
      const mat = new THREE.MeshStandardMaterial({
        color: 0x111120,
        emissive: 0x6366f1,
        emissiveIntensity: LED_INTENSITY,
      });
      const strip = new THREE.Mesh(new THREE.BoxGeometry(w, 0.025, d), mat);
      strip.position.set(x, y, z);
      strip.name = "LedStrip";
      this.group.add(strip);
      this.ledMaterials.push(mat);
    };
    const width = ROOM.maxX - ROOM.minX - 0.2;
    const depth = ROOM.maxZ - ROOM.minZ - 0.2;
    mk(width, 0.025, 0, ROOM.minZ + 0.06); // back
    mk(width, 0.025, 0, ROOM.maxZ - 0.06); // front
    mk(0.025, depth, ROOM.minX + 0.06, ROOM.centerZ); // left
    mk(0.025, depth, ROOM.maxX - 0.06, ROOM.centerZ); // right

    // Two soft colored lights emulating the strips' glow.
    for (const z of [ROOM.minZ + 0.4, ROOM.maxZ - 0.4]) {
      const led = new THREE.PointLight(0x6366f1, 0.6, 7, 1.6);
      led.position.set(0, ROOM.height - 0.3, z);
      this.scene.add(led);
      this.track(led);
      this.ledLights.push(led);
    }
  }

  // --------------------------------------------------------------- dust

  private createDust() {
    const count = 110;
    const positions = new Float32Array(count * 3);
    this.dustPhase = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = -2.8 + Math.random() * 5.6;
      positions[i * 3 + 1] = 0.25 + Math.random() * 2.6;
      positions[i * 3 + 2] = -3.6 + Math.random() * 6.2;
      this.dustPhase[i] = Math.random() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    // Soft round sprite: bare GL points are squares, and a mote drifting
    // close to the camera showed as a hard white tile.
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 32;
    const ctx = canvas.getContext("2d")!;
    const g = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.4, "rgba(255,255,255,0.45)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 32, 32);
    const sprite = new THREE.CanvasTexture(canvas);
    this.dustMat = new THREE.PointsMaterial({
      map: sprite,
      color: 0xbcbcdc,
      size: 0.02,
      transparent: true,
      opacity: 0.3,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.dust = new THREE.Points(geo, this.dustMat);
    this.dust.name = "Dust";
    this.group.add(this.dust);
  }

  // ------------------------------------------------------------ lighting

  private createLighting(scene: THREE.Scene) {
    // Soft sky/ground fill (a little stronger by day, see refreshDaylight).
    const hemi = new THREE.HemisphereLight(0x8890c8, 0x40311f, HEMI_BASE);
    scene.add(hemi);
    this.hemi = this.track(hemi);

    // Low warm ambient so shadows never crush to black.
    const ambient = new THREE.AmbientLight(0xffeedd, 0.25);
    scene.add(ambient);
    this.track(ambient);

    // Key light: warm, from the front-right, casts the main shadow.
    const key = new THREE.DirectionalLight(0xfff1e0, 0.75);
    key.position.set(2.4, 3.2, 2.2);
    key.target.position.set(0, 1.0, -0.5);
    key.castShadow = true;
    key.shadow.mapSize.width = 2048;
    key.shadow.mapSize.height = 2048;
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 12;
    key.shadow.camera.left = -4.5;
    key.shadow.camera.right = 4.5;
    key.shadow.camera.top = 4.5;
    key.shadow.camera.bottom = -4.5;
    key.shadow.bias = -0.0004;
    // thin double-sided cloth (curtains, duvet, hoodie) would otherwise acne
    key.shadow.normalBias = 0.02;
    scene.add(key);
    scene.add(key.target);
    this.track(key);

    // Cool rim from behind-left, separates Mika from the back wall.
    const rim = new THREE.DirectionalLight(0x8a9cff, 0.3);
    rim.position.set(-2.0, 2.4, -3.0);
    rim.target.position.set(0, 1.2, -0.5);
    scene.add(rim);
    scene.add(rim.target);
    this.track(rim);

    // Lamp lights — positions replaced by the GLB's LightAnchor_* empties.
    const ceilingLight = new THREE.PointLight(0xffe6c8, 0.6, 9, 1.6);
    ceilingLight.position.copy(DEFAULT_ANCHORS.Ceiling);
    scene.add(ceilingLight);
    this.track(ceilingLight);
    this.namedLights.Ceiling = ceilingLight;

    const deskLight = new THREE.PointLight(0xffb066, 0.8, 3.5, 1.8);
    deskLight.position.copy(DEFAULT_ANCHORS.DeskLamp);
    scene.add(deskLight);
    this.track(deskLight);
    this.namedLights.DeskLamp = deskLight;

    const monitorGlow = new THREE.PointLight(0x6366f1, 0.5, 2.5, 1.8);
    monitorGlow.position.copy(DEFAULT_ANCHORS.Monitor);
    scene.add(monitorGlow);
    this.track(monitorGlow);
    this.namedLights.Monitor = monitorGlow;

    const bedLight = new THREE.PointLight(0xffc98a, 0.7, 3.5, 1.8);
    bedLight.position.copy(DEFAULT_ANCHORS.BedLamp);
    scene.add(bedLight);
    this.track(bedLight);
    this.namedLights.BedLamp = bedLight;
  }
}
