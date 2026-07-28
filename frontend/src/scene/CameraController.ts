import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// The camera is ALWAYS centered on Mika: orbit + zoom only, no panning.
// FALLBACK_TARGET covers the placeholder path (no VRM → no avatar root);
// once main.ts calls setFollowTarget the camera tracks the avatar root,
// so v2 locomotion gets a following camera for free.
const FALLBACK_TARGET = new THREE.Vector3(0, 1.15, -0.5);
const DEFAULT_FOLLOW_OFFSET = new THREE.Vector3(0, 1.15, 0);
const DEFAULT_POSITION = new THREE.Vector3(0, 1.35, 2.1);
const RESET_DURATION = 0.7; // seconds (double-click re-framing)

export class CameraController {
  public controls: OrbitControls;

  private camera: THREE.PerspectiveCamera;
  private resetAlpha = 1; // 1 = no reset animation in progress
  private resetFrom = new THREE.Vector3();
  private followTarget: THREE.Object3D | null = null;
  private followOffset = DEFAULT_FOLLOW_OFFSET.clone();
  private tmpTarget = new THREE.Vector3();

  constructor(camera: THREE.PerspectiveCamera, domElement: HTMLCanvasElement) {
    this.camera = camera;
    this.controls = new OrbitControls(camera, domElement);

    this.controls.target.copy(FALLBACK_TARGET);
    this.controls.enablePan = false;
    this.controls.screenSpacePanning = false;

    // Distance kept inside the room walls (closest wall is 4m from Mika).
    this.controls.minDistance = 1.1;
    this.controls.maxDistance = 3.4;
    this.controls.minPolarAngle = Math.PI / 8; // don't fly above the ceiling
    this.controls.maxPolarAngle = Math.PI / 1.95; // don't dip below the floor

    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.rotateSpeed = 0.85;
    this.controls.zoomSpeed = 0.9;

    // Every button orbits — pan is not reachable by any input.
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.ROTATE,
    };
    this.controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_ROTATE,
    };

    camera.position.copy(DEFAULT_POSITION);
    this.controls.update();

    domElement.addEventListener("dblclick", () => this.startReset());
  }

  /** Pin the orbit target onto an object (the avatar root). The offset
   * lifts the pivot from the feet to the chest/face area. */
  setFollowTarget(target: THREE.Object3D, offset?: THREE.Vector3): void {
    this.followTarget = target;
    if (offset) this.followOffset.copy(offset);
  }

  /** Smoothly re-frame Mika from wherever the camera currently is. */
  private startReset(): void {
    this.resetFrom.copy(this.camera.position);
    this.resetAlpha = 0;
  }

  update(delta = 1 / 60): void {
    if (this.resetAlpha < 1) {
      this.resetAlpha = Math.min(1, this.resetAlpha + delta / RESET_DURATION);
      const a = this.resetAlpha;
      const t = a * a * (3 - 2 * a); // smoothstep ease
      this.camera.position.lerpVectors(this.resetFrom, DEFAULT_POSITION, t);
    }
    // The target can never drift: re-pin it every frame (on the avatar
    // root when set, else on the legacy constant).
    if (this.followTarget) {
      this.followTarget.getWorldPosition(this.tmpTarget).add(this.followOffset);
      this.controls.target.copy(this.tmpTarget);
    } else {
      this.controls.target.copy(FALLBACK_TARGET);
    }
    this.controls.update();
  }
}
