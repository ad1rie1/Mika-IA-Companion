import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class CameraController {
  public controls: OrbitControls;

  constructor(camera: THREE.PerspectiveCamera, domElement: HTMLCanvasElement) {
    this.controls = new OrbitControls(camera, domElement);

    // Target: VTuber chest height
    this.controls.target.set(0, 1.0, 0);

    // Limits
    this.controls.minDistance = 1.5;
    this.controls.maxDistance = 5;
    this.controls.minPolarAngle = Math.PI / 6; // Don't go below floor
    this.controls.maxPolarAngle = Math.PI / 2.2; // Don't go above ceiling

    // Smooth
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;

    // Pan limits (stay in room)
    this.controls.enablePan = true;
    this.controls.panSpeed = 0.5;

    // Touch support
    this.controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_PAN,
    };

    this.controls.update();
  }

  update() {
    this.controls.update();
  }
}
