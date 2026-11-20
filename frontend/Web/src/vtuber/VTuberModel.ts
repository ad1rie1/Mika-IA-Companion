import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { isVRM0 } from "./vrmVersion";

/**
 * Where her model is looked for, in order (ADR 0252): the one you put there
 * yourself (`public/models/default.vrm`, never versioned — a bought model
 * can't be redistributed), then the free one the repository ships
 * (`public/models/mika-libre.vrm`).
 */
export const MODEL_URLS = ["/models/default.vrm", "/models/mika-libre.vrm"] as const;

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

  /** The first of `urls` that loads; rejects with the last error if none does. */
  async loadFirst(urls: readonly string[]): Promise<VRM> {
    let last: unknown = new Error("no model URL");
    for (const url of urls) {
      try {
        return await this.load(url);
      } catch (err) {
        last = err;
        console.info(`No VRM model at ${url}`);
      }
    }
    throw last;
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
