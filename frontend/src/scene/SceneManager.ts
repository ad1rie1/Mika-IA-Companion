import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

// Bloom tuning. The scene is rendered linear/HDR into the composer, so the
// threshold is in scene radiance: lamps, bulbs, neon, LED strips and the
// moon are authored above it (≥ ~1.3), lit surfaces — Mika's MToon skin and
// clothes under the room lights included — stay below it and never glow.
const BLOOM_STRENGTH = 0.55;
const BLOOM_RADIUS = 0.55;
const BLOOM_THRESHOLD = 1.0;

export class SceneManager {
  public scene: THREE.Scene;
  public camera: THREE.PerspectiveCamera;
  public renderer: THREE.WebGLRenderer;
  public clock: THREE.Clock;
  /** Render → bloom → output (tone mapping + sRGB, applied once, here). */
  public composer: EffectComposer;
  public bloomPass: UnrealBloomPass;

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
    const pixelRatio = Math.min(window.devicePixelRatio, 2);
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.setPixelRatio(pixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    // Tone mapping is read by the OutputPass at the end of the composer:
    // renders into the composer's targets stay linear, so it is applied
    // exactly once.
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

    // Post-processing. The composer's own target is multisampled (the
    // canvas `antialias` no longer applies once we render off-screen) and
    // half-float, so emissives can exceed 1 and feed the bloom.
    const size = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    const target = new THREE.WebGLRenderTarget(size.x, size.y, {
      type: THREE.HalfFloatType,
      samples: 4,
    });
    target.texture.name = "SceneManager.composer";
    this.composer = new EffectComposer(this.renderer, target);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    // UnrealBloomPass already blurs from half resolution down a mip chain.
    this.bloomPass = new UnrealBloomPass(
      new THREE.Vector2(container.clientWidth, container.clientHeight),
      BLOOM_STRENGTH,
      BLOOM_RADIUS,
      BLOOM_THRESHOLD
    );
    this.composer.addPass(this.bloomPass);
    this.composer.addPass(new OutputPass());
    this.resizeComposer(container.clientWidth, container.clientHeight, pixelRatio);

    // Resize
    window.addEventListener("resize", () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(w, h);
      this.resizeComposer(w, h, this.renderer.getPixelRatio());
    });

    // Start loop
    this.animate();
  }

  onUpdate(callback: (delta: number) => void) {
    this.callbacks.push(callback);
  }

  /** Composer targets follow the drawing buffer; the bloom chain is sized
   * in CSS pixels (it starts at half of that) — on a HiDPI screen a
   * device-pixel bloom costs 4x for a blur nobody can tell apart. */
  private resizeComposer(w: number, h: number, pixelRatio: number) {
    this.composer.setPixelRatio(pixelRatio);
    this.composer.setSize(w, h);
    this.bloomPass.setSize(w, h);
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
    this.composer.render(delta);
  };
}
