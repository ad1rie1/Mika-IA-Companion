import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export class SceneManager {
  public scene: THREE.Scene;
  public camera: THREE.PerspectiveCamera;
  public renderer: THREE.WebGLRenderer;
  public clock: THREE.Clock;

  private callbacks: ((delta: number) => void)[] = [];

  constructor(container: HTMLElement) {
    this.clock = new THREE.Clock();

    // Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a2e);
    // Fog starts past the far walls (room is 8x8) so it only softens
    // the corners, never washes out the character.
    this.scene.fog = new THREE.Fog(0x1a1a2e, 10, 22);

    // Camera
    this.camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      0.1,
      100
    );
    this.camera.position.set(0, 1.35, 2.1);
    this.camera.lookAt(0, 1.15, -0.5);

    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    container.prepend(this.renderer.domElement);

    // Image-based environment lighting: gives PBR materials subtle
    // reflections/fill without any external HDR asset. Kept faint —
    // the room's own lights stay the visual authority (and Environment
    // scales environmentIntensity with the sleep phase).
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    (this.scene as any).environmentIntensity = 0.3;
    pmrem.dispose();

    // Resize
    window.addEventListener("resize", () => {
      this.camera.aspect = container.clientWidth / container.clientHeight;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(container.clientWidth, container.clientHeight);
    });

    // Start loop
    this.animate();
  }

  onUpdate(callback: (delta: number) => void) {
    this.callbacks.push(callback);
  }

  private animate = () => {
    requestAnimationFrame(this.animate);
    // Clamped at the source: after a background-tab restore getDelta()
    // returns seconds, which would make the animation mixer teleport the
    // pose in one frame and feed the VRM spring bones (16 groups) an
    // impulse big enough to diverge. Motion just catches up over a few
    // frames instead.
    const delta = Math.min(this.clock.getDelta(), 1 / 20);
    for (const cb of this.callbacks) {
      cb(delta);
    }
    this.renderer.render(this.scene, this.camera);
  };
}
