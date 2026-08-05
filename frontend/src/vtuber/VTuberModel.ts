import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { isVRM0 } from "./vrmVersion";

export class VTuberModel {
  public vrm: VRM | null = null;

  private loader: GLTFLoader;
  private scene: THREE.Scene;
  // AvatarRoot: the ONLY object whose world transform places Mika in the
  // room. The VRM lives at the root's local origin, so v2 locomotion
  // moves/rotates this group while clips keep animating in model-local
  // space — and the camera can follow it.
  private root: THREE.Group | null = null;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
    this.loader = new GLTFLoader();
    this.loader.register((parser) => new VRMLoaderPlugin(parser));
  }

  async load(url: string): Promise<VRM> {
    return new Promise((resolve, reject) => {
      this.loader.load(
        url,
        (gltf) => {
          const vrm = gltf.userData.vrm as VRM;
          if (!vrm) {
            reject(new Error("No VRM data found in file"));
            return;
          }

          VRMUtils.combineSkeletons(gltf.scene);
          VRMUtils.removeUnnecessaryVertices(gltf.scene);

          // Enable shadows
          gltf.scene.traverse((obj) => {
            if ((obj as THREE.Mesh).isMesh) {
              obj.castShadow = true;
              obj.receiveShadow = true;
            }
          });

          // Position in room via the AvatarRoot. The Y-π turn is the
          // VRM0 face-the-camera flip — condition included, exactly like
          // VRMUtils.rotateVRM0: a VRM 1.0 already faces the camera and
          // must keep the identity rotation, or it plays every clip
          // correctly while standing with its back to the viewer.
          this.root = new THREE.Group();
          this.root.name = "AvatarRoot";
          this.root.position.set(0, 0, -0.5);
          this.root.rotation.y = isVRM0(vrm) ? Math.PI : 0;
          this.root.add(vrm.scene);
          this.scene.add(this.root);
          this.vrm = vrm;

          console.log("VRM model loaded successfully");
          resolve(vrm);
        },
        (progress) => {
          const pct = (progress.loaded / progress.total) * 100;
          console.log(`Loading VRM: ${pct.toFixed(1)}%`);
        },
        (error) => {
          reject(error);
        }
      );
    });
  }

  /** The avatar's placement group — camera follow target, and the v2
   * locomotion driver's write target. Null until load() succeeds. */
  getRoot(): THREE.Object3D | null {
    return this.root;
  }

  update(delta: number) {
    if (this.vrm) {
      this.vrm.update(delta);
    }
  }
}
