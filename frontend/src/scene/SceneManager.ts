import * as THREE from "three";

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
    this.scene.fog = new THREE.Fog(0x1a1a2e, 8, 15);

    // Camera
    this.camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      0.1,
      100
    );
    this.camera.position.set(0, 1.4, 3);
    this.camera.lookAt(0, 1, 0);

    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
    });
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    container.prepend(this.renderer.domElement);

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
    const delta = this.clock.getDelta();
    for (const cb of this.callbacks) {
      cb(delta);
    }
    this.renderer.render(this.scene, this.camera);
  };
}
