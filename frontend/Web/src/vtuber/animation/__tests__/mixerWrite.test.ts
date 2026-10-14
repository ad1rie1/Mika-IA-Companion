import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { forceMixerWrite } from "../mixerWrite";

/** A node reset to rest every frame, then animated — as AnimationSystem does with the normalized pose. */
function frames(force: boolean, clip: THREE.AnimationClip, once = false): number[] {
  const node = new THREE.Object3D();
  node.name = "hips";
  const mixer = new THREE.AnimationMixer(node);
  const action = mixer.clipAction(clip);
  if (once) {
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
  }
  action.play();
  const seen: number[] = [];
  for (let i = 0; i < 40; i++) {
    node.position.set(0, 0.78, 0); // the rest pose
    if (force) forceMixerWrite(mixer);
    mixer.update(1 / 30);
    seen.push(node.position.y);
  }
  return seen;
}

// The hips of a seated workshop clip: still, at 0.57 m.
const still = new THREE.AnimationClip("assise", 1, [new THREE.VectorKeyframeTrack("hips.position", [0, 1], [0, 0.57, 0, 0, 0.57, 0])]);
// A one-shot that sits down and then holds its last frame.
const sitDown = new THREE.AnimationClip("s'asseoir", 0.5, [new THREE.VectorKeyframeTrack("hips.position", [0, 0.5], [0, 0.78, 0, 0, 0.57, 0])]);

describe("le mélangeur réécrit chaque os à chaque image", () => {
  it("sans cela, un os immobile retombait au repos (le clignotement assise / debout)", () => {
    expect(frames(false, still)).toContain(0.78);
  });

  it("un os immobile garde la valeur du clip, image après image", () => {
    for (const y of frames(true, still)) expect(y).toBeCloseTo(0.57, 6);
  });

  it("un geste tenu sur sa dernière image la garde aussi", () => {
    const seen = frames(true, sitDown, true);
    for (const y of seen.slice(20)) expect(y).toBeCloseTo(0.57, 6);
  });
});
