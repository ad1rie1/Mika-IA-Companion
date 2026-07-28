import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRM, VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

export class VTuberModel {
  public vrm: VRM | null = null;
  public model: THREE.Group | null = null;

  private loader: GLTFLoader;
  private scene: THREE.Scene;

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

          VRMUtils.removeUnnecessaryJoints(gltf.scene);
          VRMUtils.removeUnnecessaryVertices(gltf.scene);

          // Enable shadows
          gltf.scene.traverse((obj) => {
            if ((obj as THREE.Mesh).isMesh) {
              obj.castShadow = true;
              obj.receiveShadow = true;
            }
          });

          // Position in room
          vrm.scene.position.set(0, 0, -0.5);
          vrm.scene.rotation.y = Math.PI; // Face camera

          this.applyRestPose(vrm);

          this.scene.add(vrm.scene);
          this.vrm = vrm;
          this.model = gltf.scene;

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

  /** VRM files ship in T-pose (arms straight out — the rigging reference
   * pose). Nothing re-poses the arms at runtime, so without this the
   * avatar stands in the bind pose forever. Normalized rig convention
   * (verified empirically on this rig): character faces -Z, left arm
   * along -X, so positive Z rotation lowers the left arm. */
  private applyRestPose(vrm: VRM) {
    const humanoid = vrm.humanoid;
    if (!humanoid) return;

    const set = (bone: Parameters<typeof humanoid.getNormalizedBoneNode>[0], z: number) => {
      const node = humanoid.getNormalizedBoneNode(bone);
      if (node) node.rotation.z = z;
    };

    // ~66° down from horizontal: relaxed A-pose, arms along the body.
    set("leftUpperArm", 1.15);
    set("rightUpperArm", -1.15);
    // Slight elbow follow-through so the arms don't look rigid.
    set("leftLowerArm", 0.1);
    set("rightLowerArm", -0.1);
  }

  update(delta: number) {
    if (this.vrm) {
      this.vrm.update(delta);
    }
  }
}
