import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// The camera is ALWAYS centered on Mika: orbit + zoom only, no panning.
// FALLBACK_TARGET covers the placeholder path (no VRM → no avatar root);
// once main.ts calls setFollowTarget the camera tracks that object.
const FALLBACK_TARGET = new THREE.Vector3(0, 1.15, -0.5);
const DEFAULT_FOLLOW_OFFSET = new THREE.Vector3(0, 1.15, 0);
/** Where a double-click puts the camera, relative to the pivot. */
const RESET_OFFSET = new THREE.Vector3(0, 0.2, 2.6);
const DEFAULT_POSITION = FALLBACK_TARGET.clone().add(RESET_OFFSET);
const RESET_DURATION = 0.7; // seconds (double-click re-framing)

/**
 * Time constant of the pivot's follow (s). She now walks around her room:
 * the pivot rides her head, smoothed so a walking bob does not shake the
 * whole picture.
 */
const FOLLOW_TAU = 0.3;

/** The camera stays inside the room (walls, floor, ceiling), with a margin
 * — following her to the door must not carry it through the front wall. */
const CAMERA_BOUNDS = { minX: -3.75, maxX: 3.75, minY: 0.3, maxY: 2.95, minZ: -4.25, maxZ: 3.25 };

export class CameraController {
  public controls: OrbitControls;

  private camera: THREE.PerspectiveCamera;
  private resetAlpha = 1; // 1 = no reset animation in progress
  private resetFrom = new THREE.Vector3();
  private followTarget: THREE.Object3D | null = null;
  private followOffset = DEFAULT_FOLLOW_OFFSET.clone();
  private tmpTarget = new THREE.Vector3();
  /** Smoothed pivot, and last frame's — the camera is carried by their
   * difference, so a walk keeps the angle and distance the user chose. */
  private pivot = new THREE.Vector3();
  private lastPivot = new THREE.Vector3();
  private hasPivot = false;
  private tmpDelta = new THREE.Vector3();
  private resetTo = new THREE.Vector3();

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

  /** Pin the orbit target onto an object (the avatar's head, or root).
   * The offset lifts the pivot from the object's origin. */
  setFollowTarget(target: THREE.Object3D, offset?: THREE.Vector3): void {
    this.followTarget = target;
    this.followOffset.copy(offset ?? DEFAULT_FOLLOW_OFFSET);
    // A new target is a re-pin, not a move: the camera is not carried by
    // the jump between the old pivot and the new one.
    this.hasPivot = false;
  }

  /** Smoothly re-frame Mika from wherever the camera currently is. */
  private startReset(): void {
    this.resetFrom.copy(this.camera.position);
    this.resetAlpha = 0;
  }

  update(delta = 1 / 60): void {
    // The target can never drift: re-pinned every frame (on the followed
    // object when set, else on the legacy constant), smoothed.
    if (this.followTarget) {
      this.followTarget.getWorldPosition(this.tmpTarget).add(this.followOffset);
    } else {
      this.tmpTarget.copy(FALLBACK_TARGET);
    }
    if (!this.hasPivot) {
      this.pivot.copy(this.tmpTarget);
      this.lastPivot.copy(this.pivot);
      this.hasPivot = true;
    } else {
      this.pivot.lerp(this.tmpTarget, 1 - Math.exp(-delta / FOLLOW_TAU));
    }
    // Carry the camera with her: same angle, same distance, new place.
    this.tmpDelta.subVectors(this.pivot, this.lastPivot);
    this.camera.position.add(this.tmpDelta);
    this.lastPivot.copy(this.pivot);

    if (this.resetAlpha < 1) {
      this.resetAlpha = Math.min(1, this.resetAlpha + delta / RESET_DURATION);
      const a = this.resetAlpha;
      const t = a * a * (3 - 2 * a); // smoothstep ease
      this.resetTo.copy(this.pivot).add(RESET_OFFSET);
      clampToRoom(this.resetTo);
      this.camera.position.lerpVectors(this.resetFrom, this.resetTo, t);
    }

    this.controls.target.copy(this.pivot);
    clampToRoom(this.camera.position);
    this.controls.update();
  }
}

function clampToRoom(p: THREE.Vector3): void {
  const b = CAMERA_BOUNDS;
  p.set(
    Math.max(b.minX, Math.min(b.maxX, p.x)),
    Math.max(b.minY, Math.min(b.maxY, p.y)),
    Math.max(b.minZ, Math.min(b.maxZ, p.z))
  );
}
