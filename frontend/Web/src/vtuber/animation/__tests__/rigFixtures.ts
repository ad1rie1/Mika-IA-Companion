import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";

/**
 * Synthetic normalized rigs for the geometry tests. `forward` is the
 * direction the rig faces in its own frame: +Z for a VRM 1.0, −Z for a
 * VRM 0.x — the fact every sign in the animation layer derives from.
 */
export interface RigFixture {
  vrm: VRM;
  scene: THREE.Object3D;
  nodes: Map<string, THREE.Object3D>;
  sign: 1 | -1;
}

export function makeRig(metaVersion: "0" | "1"): RigFixture {
  const sign: 1 | -1 = metaVersion === "0" ? -1 : 1;
  const nodes = new Map<string, THREE.Object3D>();
  const node = (name: string) => {
    const n = new THREE.Object3D();
    n.name = `Normalized_${name}`;
    nodes.set(name, n);
    return n;
  };
  const scene = new THREE.Object3D();
  const root = new THREE.Object3D();
  scene.add(root);
  const hips = node("hips");
  hips.position.set(0, 0.9, 0);
  root.add(hips);
  const spine = node("spine");
  spine.position.set(0, 0.2, 0);
  hips.add(spine);
  const neck = node("neck");
  neck.position.set(0, 0.4, 0);
  spine.add(neck);
  const head = node("head");
  head.position.set(0, 0.1, 0);
  neck.add(head);
  const leftEye = node("leftEye");
  leftEye.position.set(0.03, 0.06, sign * 0.05);
  head.add(leftEye);
  const rightEye = node("rightEye");
  rightEye.position.set(-0.03, 0.06, sign * 0.05);
  head.add(rightEye);
  for (const name of ["leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm"]) {
    spine.add(node(name));
  }
  scene.updateMatrixWorld(true);

  const vrm = {
    meta: { metaVersion },
    scene,
    humanoid: {
      normalizedHumanBonesRoot: root,
      getNormalizedBoneNode: (name: string) => nodes.get(name) ?? null,
      resetNormalizedPose: () => {
        for (const n of nodes.values()) n.quaternion.identity();
      },
    },
  } as unknown as VRM;
  return { vrm, scene, nodes, sign };
}

/** World-space direction a node's forward axis points at. */
export function worldForward(node: THREE.Object3D, sign: 1 | -1): THREE.Vector3 {
  node.updateWorldMatrix(true, false);
  const q = new THREE.Quaternion();
  node.getWorldQuaternion(q);
  return new THREE.Vector3(0, 0, sign).applyQuaternion(q).normalize();
}

/** World-space direction from a node to a point. */
export function worldDirectionTo(node: THREE.Object3D, point: THREE.Vector3): THREE.Vector3 {
  node.updateWorldMatrix(true, false);
  const p = new THREE.Vector3();
  node.getWorldPosition(p);
  return point.clone().sub(p).normalize();
}
