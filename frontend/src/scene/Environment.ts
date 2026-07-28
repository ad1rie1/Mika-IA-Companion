import * as THREE from "three";
import type {
  AnchorId,
  EnvironmentAnchor,
  SleepPhase,
} from "../types";

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

// Room bounds. Mika stands at (0, 0, -0.5) — the room is centered on her
// so the orbit camera (maxDistance 3.4) always stays inside the walls.
const ROOM = {
  minX: -4,
  maxX: 4,
  minZ: -4.5,
  maxZ: 3.5,
  height: 3.2,
  centerZ: -0.5,
};

interface TrackedLight {
  light: THREE.Light;
  baseIntensity: number;
}

interface TrackedEmissive {
  mat: THREE.MeshStandardMaterial;
  base: number;
}

interface TwinkleBulb {
  mat: THREE.MeshStandardMaterial;
  base: number;
  phase: number;
}

/** Small helper: procedural canvas texture (no external assets needed). */
function makeTexture(
  size: number,
  draw: (ctx: CanvasRenderingContext2D, s: number) => void,
  repeatX = 1,
  repeatY = 1
): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  draw(ctx, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(repeatX, repeatY);
  tex.anisotropy = 4;
  return tex;
}

export class Environment {
  public group: THREE.Group;
  private scene: THREE.Scene;

  private trackedLights: TrackedLight[] = [];
  private trackedEmissives: TrackedEmissive[] = [];
  private twinkles: TwinkleBulb[] = [];
  private ledMaterials: THREE.MeshStandardMaterial[] = [];
  private ledLights: THREE.PointLight[] = [];

  private sleepPhase: SleepPhase = "awake";
  private currentMultiplier = 1.0;
  private targetMultiplier = 1.0;
  private currentBgColor = new THREE.Color(PHASE_BG_COLOR.awake);
  private targetBgColor = new THREE.Color(PHASE_BG_COLOR.awake);

  private windowMat!: THREE.MeshStandardMaterial;
  private windowLight!: TrackedLight;
  private monitorMatScreen!: THREE.MeshStandardMaterial;
  private monitorBase = 0.55;

  private dust!: THREE.Points;
  private dustPhase!: Float32Array;
  private dustMat!: THREE.PointsMaterial;

  private time = 0;
  private daylightTimer = 0;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
    this.group = new THREE.Group();
    scene.add(this.group);

    this.createRoom();
    this.createWindow();
    this.createDeskZone();
    this.createBedZone();
    this.createShelvesAndDecor();
    this.createFairyLights();
    this.createLedStrips();
    this.createDust();
    this.createLighting(scene);
    this.refreshDaylight();
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
   * the locomotion work. Coordinates for the future table (from the
   * furniture constants below):
   *   bed_lie:      position [-3.35, 0.42, 1.3] (mattress top), pose "lie"
   *   desk_sit:     position [-1.4, 0, -3.3] (chair in front of desk), pose "sit"
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
      for (const tl of this.trackedLights) {
        tl.light.intensity = tl.baseIntensity * this.currentMultiplier;
      }
      for (const te of this.trackedEmissives) {
        te.mat.emissiveIntensity = te.base * this.currentMultiplier;
      }
      if ("environmentIntensity" in this.scene) {
        (this.scene as any).environmentIntensity =
          ENV_INTENSITY_BASE * this.currentMultiplier;
      }
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
    const ledColor = new THREE.Color().setHSL(hue, 0.7, 0.6);
    for (const mat of this.ledMaterials) {
      mat.emissive.copy(ledColor);
      mat.emissiveIntensity = 1.1 * m;
    }
    for (const l of this.ledLights) l.color.copy(ledColor);

    // Monitor: faint screen flicker, like content changing.
    this.monitorMatScreen.emissiveIntensity =
      this.monitorBase *
      (1 + 0.06 * Math.sin(this.time * 13.0) + 0.04 * Math.sin(this.time * 7.3)) *
      m;

    // Fairy lights twinkle independently.
    for (const b of this.twinkles) {
      b.mat.emissiveIntensity =
        b.base * (0.55 + 0.45 * Math.sin(this.time * 2.2 + b.phase)) * m;
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

    // Window light follows the real time of day (checked once a minute).
    this.daylightTimer += delta;
    if (this.daylightTimer > 60) {
      this.daylightTimer = 0;
      this.refreshDaylight();
    }
  }

  private track(light: THREE.Light): void {
    this.trackedLights.push({ light, baseIntensity: light.intensity });
  }

  private trackEmissive(mat: THREE.MeshStandardMaterial): void {
    this.trackedEmissives.push({ mat, base: mat.emissiveIntensity });
  }

  // ---------------------------------------------------------------- room

  private createRoom() {
    const cz = ROOM.centerZ;
    const width = ROOM.maxX - ROOM.minX;
    const depth = ROOM.maxZ - ROOM.minZ;
    const h = ROOM.height;

    // Floor — procedural wood planks.
    const floorTex = makeTexture(
      512,
      (ctx, s) => {
        ctx.fillStyle = "#79573a";
        ctx.fillRect(0, 0, s, s);
        const plank = s / 8;
        for (let row = 0; row < 8; row++) {
          const shade = 0.85 + Math.random() * 0.3;
          ctx.fillStyle = `rgb(${Math.round(121 * shade)}, ${Math.round(
            87 * shade
          )}, ${Math.round(58 * shade)})`;
          ctx.fillRect(0, row * plank, s, plank);
          // grain streaks
          ctx.strokeStyle = "rgba(60, 40, 22, 0.25)";
          ctx.lineWidth = 1;
          for (let g = 0; g < 6; g++) {
            const y = row * plank + Math.random() * plank;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.bezierCurveTo(s * 0.3, y + 3, s * 0.6, y - 3, s, y);
            ctx.stroke();
          }
          // seam between planks
          ctx.fillStyle = "rgba(30, 20, 10, 0.55)";
          ctx.fillRect(0, row * plank, s, 2);
          // one vertical joint per row, staggered
          const joint = ((row * 137) % s + s * 0.2) % s;
          ctx.fillRect(joint, row * plank, 2, plank);
        }
      },
      3,
      3
    );
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(width, depth),
      new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.75, metalness: 0.05 })
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.z = cz;
    floor.receiveShadow = true;
    this.group.add(floor);

    // Walls — soft indigo with subtle noise + darker top gradient.
    const wallTex = makeTexture(256, (ctx, s) => {
      ctx.fillStyle = "#31315a";
      ctx.fillRect(0, 0, s, s);
      for (let i = 0; i < 900; i++) {
        const l = Math.random();
        ctx.fillStyle = l > 0.5 ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.03)";
        ctx.fillRect(Math.random() * s, Math.random() * s, 1.5, 1.5);
      }
      const grad = ctx.createLinearGradient(0, 0, 0, s);
      grad.addColorStop(0, "rgba(0,0,20,0.25)");
      grad.addColorStop(0.35, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, s, s);
    });
    const wallMat = new THREE.MeshStandardMaterial({ map: wallTex, roughness: 0.92 });

    const mkWall = (w: number, x: number, z: number, ry: number) => {
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(w, h), wallMat);
      wall.position.set(x, h / 2, z);
      wall.rotation.y = ry;
      wall.receiveShadow = true;
      this.group.add(wall);
    };
    mkWall(width, 0, ROOM.minZ, 0); // back
    mkWall(width, 0, ROOM.maxZ, Math.PI); // front
    mkWall(depth, ROOM.minX, cz, Math.PI / 2); // left
    mkWall(depth, ROOM.maxX, cz, -Math.PI / 2); // right

    // Baseboards (plinthes) along each wall.
    const baseMat = new THREE.MeshStandardMaterial({ color: 0x22223e, roughness: 0.8 });
    const mkBase = (w: number, x: number, z: number, ry: number) => {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, 0.12, 0.03), baseMat);
      b.position.set(x, 0.06, z);
      b.rotation.y = ry;
      this.group.add(b);
    };
    mkBase(width, 0, ROOM.minZ + 0.015, 0);
    mkBase(width, 0, ROOM.maxZ - 0.015, Math.PI);
    mkBase(depth, ROOM.minX + 0.015, cz, Math.PI / 2);
    mkBase(depth, ROOM.maxX - 0.015, cz, -Math.PI / 2);

    // Ceiling
    const ceiling = new THREE.Mesh(
      new THREE.PlaneGeometry(width, depth),
      new THREE.MeshStandardMaterial({ color: 0x1e1e3a, roughness: 1 })
    );
    ceiling.position.set(0, h, cz);
    ceiling.rotation.x = Math.PI / 2;
    this.group.add(ceiling);

    // Round rug under Mika — procedural pattern.
    const rugTex = makeTexture(512, (ctx, s) => {
      const c = s / 2;
      ctx.fillStyle = "#3d2a63";
      ctx.fillRect(0, 0, s, s);
      const rings: [number, string][] = [
        [0.98, "#2e1f4d"],
        [0.88, "#4a3579"],
        [0.7, "#3d2a63"],
        [0.45, "#54408a"],
        [0.25, "#6a55a8"],
      ];
      for (const [r, col] of rings) {
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.arc(c, c, c * r, 0, Math.PI * 2);
        ctx.fill();
      }
      // little stitch dots on the outer ring
      ctx.fillStyle = "rgba(255,255,255,0.12)";
      for (let i = 0; i < 40; i++) {
        const a = (i / 40) * Math.PI * 2;
        ctx.beginPath();
        ctx.arc(c + Math.cos(a) * c * 0.8, c + Math.sin(a) * c * 0.8, 3, 0, Math.PI * 2);
        ctx.fill();
      }
    });
    const carpet = new THREE.Mesh(
      new THREE.CircleGeometry(1.5, 48),
      new THREE.MeshStandardMaterial({ map: rugTex, roughness: 1, transparent: false })
    );
    carpet.rotation.x = -Math.PI / 2;
    carpet.position.set(0, 0.005, -0.5);
    carpet.receiveShadow = true;
    this.group.add(carpet);

    // Soft fake contact shadow right under Mika's feet.
    const aoTex = makeTexture(128, (ctx, s) => {
      const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      g.addColorStop(0, "rgba(0,0,0,0.5)");
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, s, s);
    });
    aoTex.colorSpace = THREE.NoColorSpace;
    const ao = new THREE.Mesh(
      new THREE.CircleGeometry(0.55, 32),
      new THREE.MeshBasicMaterial({ map: aoTex, transparent: true, depthWrite: false })
    );
    ao.rotation.x = -Math.PI / 2;
    ao.position.set(0, 0.012, -0.5);
    this.group.add(ao);

    // Door on the front wall (visible when orbiting behind Mika).
    const doorMat = new THREE.MeshStandardMaterial({ color: 0x241f38, roughness: 0.6 });
    const door = new THREE.Mesh(new THREE.BoxGeometry(0.95, 2.1, 0.06), doorMat);
    door.position.set(1.8, 1.05, ROOM.maxZ - 0.04);
    this.group.add(door);
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x191530, roughness: 0.7 });
    const doorFrame = new THREE.Mesh(new THREE.BoxGeometry(1.1, 2.2, 0.04), frameMat);
    doorFrame.position.set(1.8, 1.1, ROOM.maxZ - 0.02);
    this.group.add(doorFrame);
    const handle = new THREE.Mesh(
      new THREE.SphereGeometry(0.035, 12, 8),
      new THREE.MeshStandardMaterial({ color: 0xd4af6a, roughness: 0.3, metalness: 0.8 })
    );
    handle.position.set(1.42, 1.02, ROOM.maxZ - 0.1);
    this.group.add(handle);
  }

  // -------------------------------------------------------------- window

  private createWindow() {
    // Window on the left wall — its glow follows the real time of day.
    const x = ROOM.minX + 0.02;
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x1b1733, roughness: 0.6 });

    const frame = new THREE.Mesh(new THREE.BoxGeometry(0.08, 1.25, 1.55), frameMat);
    frame.position.set(x, 1.75, -1.2);
    this.group.add(frame);

    this.windowMat = new THREE.MeshStandardMaterial({
      color: 0x0a0f2e,
      emissive: 0x4a5fa8,
      emissiveIntensity: 0.9,
      roughness: 1,
    });
    const pane = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.1), this.windowMat);
    pane.position.set(x + 0.05, 1.75, -1.2);
    pane.rotation.y = Math.PI / 2;
    this.group.add(pane);

    // Cross bars
    const barMat = new THREE.MeshStandardMaterial({ color: 0x1b1733, roughness: 0.6 });
    const vBar = new THREE.Mesh(new THREE.BoxGeometry(0.03, 1.12, 0.04), barMat);
    vBar.position.set(x + 0.06, 1.75, -1.2);
    this.group.add(vBar);
    const hBar = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.04, 1.42), barMat);
    hBar.position.set(x + 0.06, 1.75, -1.2);
    this.group.add(hBar);

    // Curtains on both sides.
    const curtainMat = new THREE.MeshStandardMaterial({ color: 0x503a72, roughness: 1 });
    for (const dz of [-0.95, 0.95]) {
      const curtain = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.7, 0.34), curtainMat);
      curtain.position.set(x + 0.08, 1.55, -1.2 + dz);
      this.group.add(curtain);
    }

    // The light the window casts into the room (intensity set by daylight).
    const light = new THREE.PointLight(0x4a5fa8, 0.8, 8, 1.6);
    light.position.set(ROOM.minX + 0.6, 1.8, -1.2);
    this.scene.add(light);
    this.windowLight = { light, baseIntensity: light.intensity };
    this.trackedLights.push(this.windowLight);
  }

  /** Window glow + cast light follow the real local hour. */
  private refreshDaylight(): void {
    const hour = new Date().getHours();
    let color: number;
    let intensity: number;
    if (hour >= 6 && hour < 8) {
      color = 0xffc9a0; // dawn
      intensity = 1.1;
    } else if (hour >= 8 && hour < 17) {
      color = 0xbfd9ff; // daylight
      intensity = 1.5;
    } else if (hour >= 17 && hour < 20) {
      color = 0xff9c66; // sunset
      intensity = 1.3;
    } else if (hour >= 20 && hour < 23) {
      color = 0x4a5fa8; // evening
      intensity = 0.8;
    } else {
      color = 0x27336b; // deep night / moonlight
      intensity = 0.5;
    }
    this.windowMat.emissive.setHex(color);
    this.windowLight.light.color.setHex(color);
    this.windowLight.baseIntensity = intensity;
    this.windowLight.light.intensity = intensity * this.currentMultiplier;
  }

  // ---------------------------------------------------------- desk zone

  private createDeskZone() {
    const deskZ = ROOM.minZ + 0.5; // against the back wall
    const deskMat = new THREE.MeshStandardMaterial({ color: 0x4a3728, roughness: 0.55 });

    const deskTop = new THREE.Mesh(new THREE.BoxGeometry(1.9, 0.06, 0.8), deskMat);
    deskTop.position.set(-1.4, 0.75, deskZ);
    deskTop.castShadow = true;
    deskTop.receiveShadow = true;
    this.group.add(deskTop);

    const legGeo = new THREE.BoxGeometry(0.05, 0.75, 0.05);
    for (const [dx, dz] of [[-0.88, -0.35], [0.88, -0.35], [-0.88, 0.35], [0.88, 0.35]]) {
      const leg = new THREE.Mesh(legGeo, deskMat);
      leg.position.set(-1.4 + dx, 0.375, deskZ + dz);
      this.group.add(leg);
    }

    // Monitor
    const monitorMat = new THREE.MeshStandardMaterial({ color: 0x111118, roughness: 0.35 });
    const monitor = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.5, 0.04), monitorMat);
    monitor.position.set(-1.4, 1.28, deskZ - 0.25);
    monitor.castShadow = true;
    this.group.add(monitor);

    this.monitorMatScreen = new THREE.MeshStandardMaterial({
      color: 0x0a0a18,
      emissive: 0x6366f1,
      emissiveIntensity: this.monitorBase,
    });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.77, 0.42), this.monitorMatScreen);
    screen.position.set(-1.4, 1.28, deskZ - 0.227);
    this.group.add(screen);

    const stand = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.28, 0.06), monitorMat);
    stand.position.set(-1.4, 0.9, deskZ - 0.25);
    this.group.add(stand);

    // Keyboard + mug
    const keyboard = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.02, 0.16),
      new THREE.MeshStandardMaterial({ color: 0x232338, roughness: 0.5 })
    );
    keyboard.position.set(-1.4, 0.79, deskZ + 0.12);
    this.group.add(keyboard);

    const mug = new THREE.Mesh(
      new THREE.CylinderGeometry(0.045, 0.04, 0.1, 12),
      new THREE.MeshStandardMaterial({ color: 0xe08bb0, roughness: 0.4 })
    );
    mug.position.set(-0.85, 0.83, deskZ + 0.1);
    this.group.add(mug);

    // Desk lamp (arm + warm emissive head)
    const lampMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3a, roughness: 0.4 });
    const lampBase = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.03, 12), lampMat);
    lampBase.position.set(-2.05, 0.795, deskZ - 0.15);
    this.group.add(lampBase);
    const lampArm = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.45, 8), lampMat);
    lampArm.position.set(-2.02, 1.0, deskZ - 0.12);
    lampArm.rotation.z = -0.25;
    this.group.add(lampArm);
    const lampHeadMat = new THREE.MeshStandardMaterial({
      color: 0x2a2a3a,
      emissive: 0xffb066,
      emissiveIntensity: 1.2,
      roughness: 0.4,
    });
    const lampHead = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 10), lampHeadMat);
    lampHead.position.set(-1.94, 1.22, deskZ - 0.09);
    this.group.add(lampHead);
    this.trackEmissive(lampHeadMat);

    // Gaming chair
    const chairMat = new THREE.MeshStandardMaterial({ color: 0x1a1a24, roughness: 0.5 });
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.09, 0.5), chairMat);
    seat.position.set(-1.4, 0.45, deskZ + 0.75);
    seat.castShadow = true;
    this.group.add(seat);
    const backrest = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.65, 0.09), chairMat);
    backrest.position.set(-1.4, 0.8, deskZ + 0.98);
    backrest.rotation.x = 0.08;
    backrest.castShadow = true;
    this.group.add(backrest);
    const accent = new THREE.Mesh(
      new THREE.BoxGeometry(0.52, 0.08, 0.1),
      new THREE.MeshStandardMaterial({ color: 0xff6b9d, roughness: 0.5 })
    );
    accent.position.set(-1.4, 1.1, deskZ + 0.99);
    accent.rotation.x = 0.08;
    this.group.add(accent);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.35, 10), chairMat);
    pole.position.set(-1.4, 0.25, deskZ + 0.75);
    this.group.add(pole);
    const chairFoot = new THREE.Mesh(new THREE.CylinderGeometry(0.24, 0.26, 0.04, 16), chairMat);
    chairFoot.position.set(-1.4, 0.05, deskZ + 0.75);
    this.group.add(chairFoot);
  }

  // ----------------------------------------------------------- bed zone

  private createBedZone() {
    // Bed along the left wall, toward the front of the room.
    const bx = -3.35;
    const bz = 1.3;

    const frameMat = new THREE.MeshStandardMaterial({ color: 0x3a2a20, roughness: 0.7 });
    const frame = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.22, 2.15), frameMat);
    frame.position.set(bx, 0.15, bz);
    frame.castShadow = true;
    this.group.add(frame);

    const headboard = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.6, 0.07), frameMat);
    headboard.position.set(bx, 0.45, bz - 1.07);
    this.group.add(headboard);

    const mattress = new THREE.Mesh(
      new THREE.BoxGeometry(1.05, 0.16, 2.0),
      new THREE.MeshStandardMaterial({ color: 0xd8d2e8, roughness: 0.95 })
    );
    mattress.position.set(bx, 0.34, bz);
    mattress.castShadow = true;
    this.group.add(mattress);

    const blanket = new THREE.Mesh(
      new THREE.BoxGeometry(1.07, 0.07, 1.25),
      new THREE.MeshStandardMaterial({ color: 0x7a5fb0, roughness: 1 })
    );
    blanket.position.set(bx, 0.44, bz + 0.35);
    this.group.add(blanket);

    const pillow = new THREE.Mesh(
      new THREE.BoxGeometry(0.55, 0.09, 0.32),
      new THREE.MeshStandardMaterial({ color: 0xf0e9f7, roughness: 1 })
    );
    pillow.position.set(bx, 0.46, bz - 0.75);
    pillow.rotation.z = 0.02;
    this.group.add(pillow);

    // Bedside table + tiny warm lamp.
    const tableMat = new THREE.MeshStandardMaterial({ color: 0x3a2a20, roughness: 0.7 });
    const table = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.45, 0.4), tableMat);
    table.position.set(-3.6, 0.225, 2.75);
    this.group.add(table);
    const lampShadeMat = new THREE.MeshStandardMaterial({
      color: 0xffe3b8,
      emissive: 0xffc98a,
      emissiveIntensity: 0.9,
      roughness: 1,
    });
    const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 0.12, 12), lampShadeMat);
    shade.position.set(-3.6, 0.56, 2.75);
    this.group.add(shade);
    this.trackEmissive(lampShadeMat);

    const bedLight = new THREE.PointLight(0xffc98a, 0.7, 3.5, 1.8);
    bedLight.position.set(-3.55, 0.7, 2.7);
    this.scene.add(bedLight);
    this.track(bedLight);
  }

  // ------------------------------------------------- shelves and decor

  private createShelvesAndDecor() {
    // Bookshelf against the right wall.
    const shelfMat = new THREE.MeshStandardMaterial({ color: 0x5c4033, roughness: 0.7 });
    const sx = ROOM.maxX - 0.22;
    for (let i = 0; i < 3; i++) {
      const shelf = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.04, 1.5), shelfMat);
      shelf.position.set(sx, 1.0 + i * 0.55, -2.2);
      shelf.castShadow = true;
      this.group.add(shelf);

      const bookColors = [0xe74c3c, 0x3498db, 0x2ecc71, 0xf39c12, 0x9b59b6, 0xe08bb0];
      let z = -2.85;
      for (let j = 0; j < 6; j++) {
        const bookHeight = 0.16 + Math.random() * 0.1;
        const thickness = 0.05 + Math.random() * 0.03;
        const book = new THREE.Mesh(
          new THREE.BoxGeometry(0.2, bookHeight, thickness),
          new THREE.MeshStandardMaterial({
            color: bookColors[(i * 2 + j) % bookColors.length],
            roughness: 0.8,
          })
        );
        book.position.set(sx, 1.0 + i * 0.55 + bookHeight / 2 + 0.02, z);
        book.rotation.y = (Math.random() - 0.5) * 0.1;
        book.castShadow = true;
        this.group.add(book);
        z += thickness + 0.025;
      }
    }

    // Posters — procedural artwork on the back wall + right wall.
    const posterMoon = makeTexture(256, (ctx, s) => {
      const g = ctx.createLinearGradient(0, 0, 0, s);
      g.addColorStop(0, "#2b2050");
      g.addColorStop(1, "#7a4a8c");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, s, s);
      ctx.fillStyle = "#ffe9c9";
      ctx.beginPath();
      ctx.arc(s * 0.62, s * 0.32, s * 0.14, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      for (let i = 0; i < 30; i++) {
        ctx.fillRect(Math.random() * s, Math.random() * s * 0.7, 2, 2);
      }
      ctx.strokeStyle = "#f5eef8";
      ctx.lineWidth = 8;
      ctx.strokeRect(4, 4, s - 8, s - 8);
    });
    const poster1 = new THREE.Mesh(
      new THREE.PlaneGeometry(0.65, 0.85),
      new THREE.MeshStandardMaterial({ map: posterMoon, roughness: 0.9 })
    );
    poster1.position.set(0.6, 2.15, ROOM.minZ + 0.01);
    this.group.add(poster1);

    const posterPeaks = makeTexture(256, (ctx, s) => {
      const g = ctx.createLinearGradient(0, 0, 0, s);
      g.addColorStop(0, "#1c3a5e");
      g.addColorStop(1, "#4ecdc4");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, s, s);
      ctx.fillStyle = "#12233d";
      ctx.beginPath();
      ctx.moveTo(0, s);
      ctx.lineTo(s * 0.35, s * 0.4);
      ctx.lineTo(s * 0.6, s);
      ctx.fill();
      ctx.fillStyle = "#0d1a2e";
      ctx.beginPath();
      ctx.moveTo(s * 0.4, s);
      ctx.lineTo(s * 0.75, s * 0.5);
      ctx.lineTo(s, s);
      ctx.fill();
      ctx.strokeStyle = "#eef5f8";
      ctx.lineWidth = 8;
      ctx.strokeRect(4, 4, s - 8, s - 8);
    });
    const poster2 = new THREE.Mesh(
      new THREE.PlaneGeometry(0.6, 0.6),
      new THREE.MeshStandardMaterial({ map: posterPeaks, roughness: 0.9 })
    );
    poster2.position.set(ROOM.maxX - 0.01, 2.0, 0.6);
    poster2.rotation.y = -Math.PI / 2;
    this.group.add(poster2);

    // Wall shelf with trinkets, back wall right side.
    const trinketShelf = new THREE.Mesh(
      new THREE.BoxGeometry(1.0, 0.04, 0.22),
      new THREE.MeshStandardMaterial({ color: 0x5c4033, roughness: 0.7 })
    );
    trinketShelf.position.set(1.9, 1.75, ROOM.minZ + 0.14);
    this.group.add(trinketShelf);

    // trinkets: tiny star, cube, frame
    const star = new THREE.Mesh(
      new THREE.OctahedronGeometry(0.06),
      new THREE.MeshStandardMaterial({
        color: 0xffd77a,
        emissive: 0xffd77a,
        emissiveIntensity: 0.4,
        roughness: 0.4,
      })
    );
    star.position.set(1.55, 1.84, ROOM.minZ + 0.14);
    this.group.add(star);
    this.trackEmissive(star.material as THREE.MeshStandardMaterial);

    const cube = new THREE.Mesh(
      new THREE.BoxGeometry(0.09, 0.09, 0.09),
      new THREE.MeshStandardMaterial({ color: 0x4ecdc4, roughness: 0.5 })
    );
    cube.position.set(1.95, 1.82, ROOM.minZ + 0.14);
    cube.rotation.y = 0.5;
    this.group.add(cube);

    const photoFrame = new THREE.Mesh(
      new THREE.BoxGeometry(0.14, 0.18, 0.015),
      new THREE.MeshStandardMaterial({ color: 0xd8c9a8, roughness: 0.6 })
    );
    photoFrame.position.set(2.3, 1.86, ROOM.minZ + 0.15);
    photoFrame.rotation.x = -0.12;
    this.group.add(photoFrame);

    // Plants: a big one near the bookshelf, a small one near the door.
    this.createPlant(3.4, ROOM.minZ + 0.55, 1.0);
    this.createPlant(-3.4, 3.0, 0.7);
  }

  private createPlant(x: number, z: number, scale: number) {
    const potMat = new THREE.MeshStandardMaterial({ color: 0xc4703b, roughness: 0.8 });
    const pot = new THREE.Mesh(
      new THREE.CylinderGeometry(0.16 * scale, 0.12 * scale, 0.26 * scale, 12),
      potMat
    );
    pot.position.set(x, 0.13 * scale, z);
    pot.castShadow = true;
    this.group.add(pot);

    const trunk = new THREE.Mesh(
      new THREE.CylinderGeometry(0.025 * scale, 0.035 * scale, 0.5 * scale, 8),
      new THREE.MeshStandardMaterial({ color: 0x5a4028, roughness: 0.9 })
    );
    trunk.position.set(x, 0.5 * scale, z);
    this.group.add(trunk);

    const leafMat = new THREE.MeshStandardMaterial({ color: 0x2f9e56, roughness: 0.9 });
    const clusters: [number, number, number, number][] = [
      [0, 0.85, 0, 0.22],
      [0.14, 0.72, 0.05, 0.15],
      [-0.13, 0.75, -0.06, 0.16],
      [0.02, 0.68, 0.13, 0.13],
    ];
    for (const [dx, dy, dz, r] of clusters) {
      const leaves = new THREE.Mesh(new THREE.SphereGeometry(r * scale, 10, 8), leafMat);
      leaves.position.set(x + dx * scale, dy * scale, z + dz * scale);
      leaves.castShadow = true;
      this.group.add(leaves);
    }
  }

  // -------------------------------------------------------- fairy lights

  private createFairyLights() {
    // A sagging string of twinkling bulbs across the back wall.
    const bulbColors = [0xfff2cc, 0xffb0d0, 0xa8b4ff];
    const n = 22;
    const y0 = 2.75;
    const sag = 0.28;
    const x0 = -3.6;
    const x1 = 3.6;

    // the wire
    const wirePts: THREE.Vector3[] = [];
    for (let i = 0; i <= 40; i++) {
      const t = i / 40;
      wirePts.push(
        new THREE.Vector3(
          x0 + (x1 - x0) * t,
          y0 - Math.sin(Math.PI * t) * sag,
          ROOM.minZ + 0.08
        )
      );
    }
    const wire = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(wirePts),
      new THREE.LineBasicMaterial({ color: 0x333348 })
    );
    this.group.add(wire);

    const bulbGeo = new THREE.SphereGeometry(0.025, 8, 6);
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5) / n;
      const mat = new THREE.MeshStandardMaterial({
        color: 0x222230,
        emissive: bulbColors[i % bulbColors.length],
        emissiveIntensity: 1.4,
        roughness: 0.5,
      });
      const bulb = new THREE.Mesh(bulbGeo, mat);
      bulb.position.set(
        x0 + (x1 - x0) * t,
        y0 - Math.sin(Math.PI * t) * sag - 0.04,
        ROOM.minZ + 0.08
      );
      this.group.add(bulb);
      this.twinkles.push({ mat, base: 1.4, phase: i * 1.37 });
    }
  }

  // ---------------------------------------------------------- LED strips

  private createLedStrips() {
    const y = ROOM.height - 0.08;
    const mk = (w: number, d: number, x: number, z: number) => {
      const mat = new THREE.MeshStandardMaterial({
        color: 0x111120,
        emissive: 0x6366f1,
        emissiveIntensity: 1.1,
      });
      const strip = new THREE.Mesh(new THREE.BoxGeometry(w, 0.025, d), mat);
      strip.position.set(x, y, z);
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
    this.dustMat = new THREE.PointsMaterial({
      color: 0xbcbcdc,
      size: 0.016,
      transparent: true,
      opacity: 0.3,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });
    this.dust = new THREE.Points(geo, this.dustMat);
    this.group.add(this.dust);
  }

  // ------------------------------------------------------------ lighting

  private createLighting(scene: THREE.Scene) {
    // Soft sky/ground fill.
    const hemi = new THREE.HemisphereLight(0x8890c8, 0x40311f, 0.45);
    scene.add(hemi);
    this.track(hemi);

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

    // Ceiling lamp above Mika.
    const cordMat = new THREE.MeshStandardMaterial({ color: 0x22223a, roughness: 0.8 });
    const cord = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.4, 6), cordMat);
    cord.position.set(0, ROOM.height - 0.2, -0.5);
    this.group.add(cord);
    const shadeMat = new THREE.MeshStandardMaterial({
      color: 0x2e2e4a,
      emissive: 0xffe6c8,
      emissiveIntensity: 0.5,
      roughness: 0.7,
      side: THREE.DoubleSide,
    });
    const lampShade = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.16, 16, 1, true), shadeMat);
    lampShade.position.set(0, ROOM.height - 0.44, -0.5);
    this.group.add(lampShade);
    this.trackEmissive(shadeMat);

    const ceilingLight = new THREE.PointLight(0xffe6c8, 0.6, 9, 1.6);
    ceilingLight.position.set(0, ROOM.height - 0.55, -0.5);
    scene.add(ceilingLight);
    this.track(ceilingLight);

    // Warm desk lamp pool.
    const deskLight = new THREE.PointLight(0xffb066, 0.8, 3.5, 1.8);
    deskLight.position.set(-1.9, 1.35, ROOM.minZ + 0.55);
    scene.add(deskLight);
    this.track(deskLight);

    // Monitor glow.
    const monitorGlow = new THREE.PointLight(0x6366f1, 0.5, 2.5, 1.8);
    monitorGlow.position.set(-1.4, 1.25, ROOM.minZ + 0.6);
    scene.add(monitorGlow);
    this.track(monitorGlow);
  }
}
