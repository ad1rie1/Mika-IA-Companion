import * as THREE from "three";

export type SleepPhase = "awake" | "light_sleep" | "rem" | "deep_sleep";

// Per-phase multipliers applied to all ambient / directional / accent
// light intensities. Deep sleep = almost dark blue room.
const PHASE_LIGHT_MULTIPLIER: Record<SleepPhase, number> = {
  awake: 1.0,
  light_sleep: 0.55,
  rem: 0.40,
  deep_sleep: 0.22,
};

// Night tint applied to the scene background when asleep. RGB in THREE.
const PHASE_BG_COLOR: Record<SleepPhase, number> = {
  awake: 0x1a1a2e,       // the scene's default
  light_sleep: 0x131230,
  rem: 0x0f0e28,
  deep_sleep: 0x08081b,
};

const LIGHT_EASE_DURATION = 1.8; // seconds

interface TrackedLight {
  light: THREE.Light;
  baseIntensity: number;
}

export class Environment {
  public group: THREE.Group;
  private scene: THREE.Scene;
  private trackedLights: TrackedLight[] = [];
  private sleepPhase: SleepPhase = "awake";
  private currentMultiplier = 1.0;
  private targetMultiplier = 1.0;
  private currentBgColor = new THREE.Color(PHASE_BG_COLOR.awake);
  private targetBgColor = new THREE.Color(PHASE_BG_COLOR.awake);

  constructor(scene: THREE.Scene) {
    this.scene = scene;
    this.group = new THREE.Group();
    scene.add(this.group);

    this.createRoom();
    this.createFurniture();
    this.createLighting(scene);
  }

  /** Drive scene lights + background color from Mika's sleep phase. */
  setSleepPhase(phase: SleepPhase): void {
    if (this.sleepPhase === phase) return;
    this.sleepPhase = phase;
    this.targetMultiplier = PHASE_LIGHT_MULTIPLIER[phase];
    this.targetBgColor = new THREE.Color(PHASE_BG_COLOR[phase]);
  }

  /** Called by the main update loop. Eases lights + bg toward targets. */
  update(delta: number): void {
    const rate = Math.min(1, delta / LIGHT_EASE_DURATION * 4);
    const diff = this.targetMultiplier - this.currentMultiplier;
    if (Math.abs(diff) > 0.001) {
      this.currentMultiplier += diff * rate;
      for (const tl of this.trackedLights) {
        tl.light.intensity = tl.baseIntensity * this.currentMultiplier;
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
  }

  private track(light: THREE.Light): void {
    this.trackedLights.push({ light, baseIntensity: light.intensity });
  }

  private createRoom() {
    // Floor - warm wood color
    const floorGeo = new THREE.PlaneGeometry(6, 6);
    const floorMat = new THREE.MeshStandardMaterial({
      color: 0x8b6914,
      roughness: 0.8,
      metalness: 0.1,
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    this.group.add(floor);

    // Back wall
    const wallMat = new THREE.MeshStandardMaterial({
      color: 0x2d2d4e,
      roughness: 0.9,
    });
    const backWall = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.5), wallMat);
    backWall.position.set(0, 1.75, -3);
    backWall.receiveShadow = true;
    this.group.add(backWall);

    // Left wall
    const leftWall = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.5), wallMat);
    leftWall.position.set(-3, 1.75, 0);
    leftWall.rotation.y = Math.PI / 2;
    leftWall.receiveShadow = true;
    this.group.add(leftWall);

    // Right wall
    const rightWall = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.5), wallMat);
    rightWall.position.set(3, 1.75, 0);
    rightWall.rotation.y = -Math.PI / 2;
    rightWall.receiveShadow = true;
    this.group.add(rightWall);

    // Ceiling
    const ceiling = new THREE.Mesh(
      new THREE.PlaneGeometry(6, 6),
      new THREE.MeshStandardMaterial({ color: 0x1e1e3a, roughness: 1 })
    );
    ceiling.position.y = 3.5;
    ceiling.rotation.x = Math.PI / 2;
    this.group.add(ceiling);
  }

  private createFurniture() {
    // Desk
    const deskMat = new THREE.MeshStandardMaterial({
      color: 0x4a3728,
      roughness: 0.6,
    });
    const deskTop = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.06, 0.8), deskMat);
    deskTop.position.set(-1.2, 0.75, -2.5);
    deskTop.castShadow = true;
    this.group.add(deskTop);

    // Desk legs
    const legGeo = new THREE.BoxGeometry(0.05, 0.75, 0.05);
    const legPositions = [
      [-2.05, 0.375, -2.85],
      [-0.35, 0.375, -2.85],
      [-2.05, 0.375, -2.15],
      [-0.35, 0.375, -2.15],
    ];
    for (const [x, y, z] of legPositions) {
      const leg = new THREE.Mesh(legGeo, deskMat);
      leg.position.set(x, y, z);
      this.group.add(leg);
    }

    // Monitor
    const monitorMat = new THREE.MeshStandardMaterial({
      color: 0x111111,
      roughness: 0.3,
    });
    const monitor = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.5, 0.04), monitorMat);
    monitor.position.set(-1.2, 1.25, -2.7);
    monitor.castShadow = true;
    this.group.add(monitor);

    // Monitor screen (emissive)
    const screenMat = new THREE.MeshStandardMaterial({
      color: 0x6366f1,
      emissive: 0x6366f1,
      emissiveIntensity: 0.3,
    });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.72, 0.42), screenMat);
    screen.position.set(-1.2, 1.25, -2.677);
    this.group.add(screen);

    // Monitor stand
    const stand = new THREE.Mesh(
      new THREE.BoxGeometry(0.06, 0.25, 0.06),
      monitorMat
    );
    stand.position.set(-1.2, 0.9, -2.7);
    this.group.add(stand);

    // Bookshelf on right wall
    const shelfMat = new THREE.MeshStandardMaterial({
      color: 0x5c4033,
      roughness: 0.7,
    });
    for (let i = 0; i < 3; i++) {
      const shelf = new THREE.Mesh(
        new THREE.BoxGeometry(1.2, 0.04, 0.3),
        shelfMat
      );
      shelf.position.set(2.3, 1.0 + i * 0.6, -2.5);
      shelf.castShadow = true;
      this.group.add(shelf);

      // Books on shelf
      const bookColors = [0xe74c3c, 0x3498db, 0x2ecc71, 0xf39c12, 0x9b59b6];
      for (let j = 0; j < 4; j++) {
        const bookHeight = 0.15 + Math.random() * 0.1;
        const book = new THREE.Mesh(
          new THREE.BoxGeometry(0.06, bookHeight, 0.2),
          new THREE.MeshStandardMaterial({
            color: bookColors[j % bookColors.length],
            roughness: 0.8,
          })
        );
        book.position.set(
          1.9 + j * 0.2,
          1.0 + i * 0.6 + bookHeight / 2 + 0.02,
          -2.5
        );
        book.castShadow = true;
        this.group.add(book);
      }
    }

    // Carpet
    const carpet = new THREE.Mesh(
      new THREE.CircleGeometry(1.2, 32),
      new THREE.MeshStandardMaterial({
        color: 0x4a2d7a,
        roughness: 1,
      })
    );
    carpet.rotation.x = -Math.PI / 2;
    carpet.position.set(0, 0.005, -0.5);
    this.group.add(carpet);

    // Small plant pot
    const potMat = new THREE.MeshStandardMaterial({
      color: 0xc4703b,
      roughness: 0.8,
    });
    const pot = new THREE.Mesh(
      new THREE.CylinderGeometry(0.08, 0.06, 0.12, 8),
      potMat
    );
    pot.position.set(2.0, 0.81, -2.5);
    this.group.add(pot);

    // Plant leaves (simple sphere)
    const leaves = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 8, 6),
      new THREE.MeshStandardMaterial({ color: 0x27ae60, roughness: 0.9 })
    );
    leaves.position.set(2.0, 1.0, -2.5);
    this.group.add(leaves);

    // Gaming chair (simplified)
    const chairMat = new THREE.MeshStandardMaterial({
      color: 0x1a1a1a,
      roughness: 0.5,
    });
    // Seat
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.08, 0.5), chairMat);
    seat.position.set(-1.2, 0.45, -1.8);
    this.group.add(seat);
    // Backrest
    const backrest = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.08), chairMat);
    backrest.position.set(-1.2, 0.75, -2.02);
    this.group.add(backrest);

    // Wall poster (on back wall)
    const poster = new THREE.Mesh(
      new THREE.PlaneGeometry(0.6, 0.8),
      new THREE.MeshStandardMaterial({
        color: 0xff6b9d,
        emissive: 0xff6b9d,
        emissiveIntensity: 0.1,
      })
    );
    poster.position.set(1.0, 2.0, -2.99);
    this.group.add(poster);

    // LED strip on ceiling edge (emissive line)
    const ledGeo = new THREE.BoxGeometry(6, 0.02, 0.02);
    const ledMat = new THREE.MeshStandardMaterial({
      color: 0x6366f1,
      emissive: 0x6366f1,
      emissiveIntensity: 0.8,
    });
    const ledStrip = new THREE.Mesh(ledGeo, ledMat);
    ledStrip.position.set(0, 3.48, -2.99);
    this.group.add(ledStrip);
  }

  private createLighting(scene: THREE.Scene) {
    // Ambient light - soft and warm
    const ambient = new THREE.AmbientLight(0xffeedd, 0.3);
    scene.add(ambient);
    this.track(ambient);

    // Main directional light
    const dirLight = new THREE.DirectionalLight(0xfff5e6, 0.6);
    dirLight.position.set(2, 3, 1);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 1024;
    dirLight.shadow.mapSize.height = 1024;
    dirLight.shadow.camera.near = 0.1;
    dirLight.shadow.camera.far = 10;
    scene.add(dirLight);
    this.track(dirLight);

    // Purple accent light (from LED strip)
    const purpleLight = new THREE.PointLight(0x6366f1, 0.5, 6);
    purpleLight.position.set(0, 3.2, -2.5);
    scene.add(purpleLight);
    this.track(purpleLight);

    // Warm desk lamp light
    const deskLight = new THREE.PointLight(0xffaa44, 0.4, 3);
    deskLight.position.set(-1.2, 1.5, -2.3);
    deskLight.castShadow = true;
    scene.add(deskLight);
    this.track(deskLight);

    // Monitor glow
    const monitorGlow = new THREE.PointLight(0x6366f1, 0.2, 2);
    monitorGlow.position.set(-1.2, 1.25, -2.5);
    scene.add(monitorGlow);
    this.track(monitorGlow);
  }
}
