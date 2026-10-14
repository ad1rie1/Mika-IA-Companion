import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { AnimationStateMachine } from "../AnimationStateMachine";
import type { ClipLibrary, LoadedClip } from "../ClipLibrary";
import { sampleCurve } from "../atelierClip";
import { CARRY_HOLD, DESK_POSES, DeskChoreography, type DeskInput, type DeskPlayer } from "./DeskChoreography";

/** What lies on her desk for her hands (the room's objects, taken out of its joined meshes). */
export interface DeskProps {
  mug: THREE.Object3D | null;
  pen: THREE.Object3D | null;
  mouse: THREE.Object3D | null;
}

/** Desk poses cross-fade like the Unity pose layer (0.45 s). */
const DESK_FADE = 0.45;
/** The centre of the mouse, toward the fingers from the palm (m). */
const MOUSE_UNDER_PALM = 0.025;
/** The palm higher than this above the mouse: the hand has left it (m). */
const MOUSE_LET_GO = 0.08;

const _m = new THREE.Matrix4();
const _v = new THREE.Vector3();
const _w = new THREE.Vector3();
const _q = new THREE.Quaternion();
const _s = new THREE.Vector3();

interface Carried {
  obj: THREE.Object3D;
  hand: THREE.Object3D;
  /** The object in the hand's frame, as the hand took it. */
  local: THREE.Matrix4;
  /** Where it lay (its parent's frame): it goes back there. */
  restPos: THREE.Vector3;
  restRot: THREE.Quaternion;
}

/**
 * Her desk, played on the web body: the choreography (DeskChoreography.ts)
 * picks the workshop clip and moves the chair; this plays the clips on the
 * state machine's posture slot, reads their time and curves back, and moves
 * what her hands touch — the mug and the pen follow the hand that took them
 * (the Hold curve: in hand above 0.25; above 0.5, the pen slides into her
 * writing grip, between thumb and index, the point toward the page), and go
 * back exactly where they lay; the mouse follows her palm while she uses it.
 * The Unity client's `BodyActivity` (desk part), on three.js.
 */
export class DeskStage implements DeskPlayer {
  readonly choreography: DeskChoreography;
  private props: DeskProps = { mug: null, pen: null, mouse: null };
  private carried: Carried | null = null;
  private penAxis = new THREE.Vector3(0, 0, 1);
  private mouseAxis = new THREE.Vector3(0, 0, 1);
  private mouseHeld = false;
  private mouseT = 0;
  private mouseY = 0;
  private mouseTop = 0;

  constructor(
    private readonly machine: AnimationStateMachine,
    private readonly library: ClipLibrary,
    private readonly vrm: VRM,
    random: () => number = Math.random
  ) {
    this.choreography = new DeskChoreography(this, random);
  }

  /** The desk's clips are loaded (at least her resting hands and the pull to the desk). */
  get ready(): boolean {
    return this.has("lap") && this.has("pull_in") && this.has("push_out");
  }

  setProps(props: DeskProps): void {
    this.props = props;
    if (props.pen) this.penAxis = longAxis(props.pen, false);
    if (props.mouse) {
      this.mouseAxis = longAxis(props.mouse, true);
      this.mouseY = props.mouse.position.y;
      this.mouseTop = new THREE.Box3().setFromObject(props.mouse).max.y;
    }
  }

  update(now: number, input: Omit<DeskInput, "mug" | "pen" | "mouse">): void {
    this.choreography.update(now, {
      ...input,
      mug: this.props.mug !== null,
      pen: this.props.pen !== null,
      mouse: this.props.mouse !== null,
    });
  }

  /** She is no longer seated at her desk: what she held goes back, the rest is forgotten. */
  leave(): void {
    this.release();
    this.mouseHeld = false;
    this.choreography.reset();
  }

  // ── DeskPlayer: the clips, on the state machine ───────────────────

  private clip(pose: string): LoadedClip | null {
    const name = DESK_POSES[pose];
    return name ? this.library.get(name) : null;
  }

  has(pose: string): boolean {
    return this.clip(pose) !== null;
  }

  play(pose: string, restart: boolean): void {
    const clip = this.clip(pose);
    if (!clip) return;
    this.machine.setPosture(clip, DESK_FADE, { once: clip.meta.loop === false, restart });
  }

  private state(pose: string): { clip: LoadedClip; time: number; settled: boolean } | null {
    const st = this.machine.postureState;
    const clip = this.clip(pose);
    return st && clip && st.clip === clip ? st : null;
  }

  settled(pose: string): boolean {
    return this.state(pose)?.settled ?? false;
  }

  progress(pose: string): number | null {
    const st = this.state(pose);
    if (!st) return null;
    const d = st.clip.clip.duration;
    return d > 0 ? st.time / d : 1;
  }

  seconds(pose: string): number {
    return this.clip(pose)?.clip.duration ?? 3;
  }

  curve(pose: string, name: string): number {
    const st = this.state(pose);
    return st ? sampleCurve(st.clip.curves, name, st.time) : 0;
  }

  // ── after the body is posed: what her hands move ─────────────────

  /** Once the VRM's bones are this frame's (after vrm.update). */
  lateUpdate(dt: number): void {
    this.carry();
    this.followMouse(dt);
  }

  private bone(name: VRMHumanBoneName): THREE.Object3D | null {
    const b = this.vrm.humanoid?.getRawBoneNode(name) ?? null;
    b?.updateWorldMatrix(true, false);
    return b;
  }

  private carry(): void {
    const c = this.choreography.carry();
    const obj = c ? this.props[c.object] : null;
    if (this.carried && (!c || c.hold < CARRY_HOLD || obj !== this.carried.obj)) this.release();
    if (!this.carried && c && obj && c.hold >= CARRY_HOLD) {
      const hand = this.bone(c.hand === "left" ? "leftHand" : "rightHand");
      if (hand) this.grasp(obj, hand);
    }
    const held = this.carried;
    if (!held || !c) return;
    // Where the hand holds it, as it took it…
    _m.multiplyMatrices(held.hand.matrixWorld, held.local);
    const pos = new THREE.Vector3();
    const rot = new THREE.Quaternion();
    _m.decompose(pos, rot, _s);
    // …and, writing, slid into her grip.
    if (c.object === "pen" && c.hand === "right" && c.hold > 0.5) {
      const grip = this.writingGrip(rot);
      if (grip) {
        const k = Math.min(1, (c.hold - 0.5) / 0.5);
        pos.lerp(grip.pos, k);
        rot.slerp(grip.rot, k);
      }
    }
    setWorld(held.obj, pos, rot);
  }

  private grasp(obj: THREE.Object3D, hand: THREE.Object3D): void {
    obj.updateWorldMatrix(true, false);
    this.carried = {
      obj,
      hand,
      local: hand.matrixWorld.clone().invert().multiply(obj.matrixWorld),
      restPos: obj.position.clone(),
      restRot: obj.quaternion.clone(),
    };
  }

  /** Laid back where the hand took it (the gesture brings it there: the millimetres are wiped). */
  private release(): void {
    const c = this.carried;
    this.carried = null;
    if (!c) return;
    c.obj.position.copy(c.restPos);
    c.obj.quaternion.copy(c.restRot);
  }

  /**
   * The pen held to write (as in the workshop, atelier_desk.stylus): its
   * centre 2 cm from the grip (between thumb and index) toward the page,
   * its axis toward the paper, halfway between the forearm and the vertical.
   */
  private writingGrip(held: THREE.Quaternion): { pos: THREE.Vector3; rot: THREE.Quaternion } | null {
    const wrist = this.bone("rightHand");
    const index = this.bone("rightIndexDistal");
    const thumb = this.bone("rightThumbDistal");
    if (!wrist || !index || !thumb) return null;
    const grip = index.getWorldPosition(new THREE.Vector3()).add(thumb.getWorldPosition(_v)).multiplyScalar(0.5);
    const dir = grip
      .clone()
      .sub(wrist.getWorldPosition(_w))
      .normalize()
      .multiplyScalar(0.4)
      .add(new THREE.Vector3(0, -0.6, 0))
      .normalize();
    const axis = this.penAxis.clone().applyQuaternion(held);
    const want = axis.dot(dir.clone().negate()) >= 0 ? dir.clone().negate() : dir;
    const rot = new THREE.Quaternion().setFromUnitVectors(axis, want).multiply(held);
    return { pos: grip.addScaledVector(dir, 0.02), rot };
  }

  /**
   * The mouse under her palm (desk_mouse): while the hand uses it, its
   * centre follows the point under the palm (a little toward the fingers)
   * and its long axis the fingers. Its resting place is that very point at
   * the moment the hand takes it (build_desk.py): no jump. The choreography
   * lets it go only where the hand took it, so it stays at its place.
   */
  private followMouse(dt: number): void {
    const mouse = this.props.mouse;
    if (!mouse || !this.choreography.mouseInUse) {
      this.mouseHeld = false;
      return;
    }
    const hand = this.bone("rightHand");
    const knuckles = this.bone("rightMiddleProximal");
    if (!hand || !knuckles) return;
    if (!this.mouseHeld) {
      this.mouseHeld = true;
      this.mouseT = 0;
      this.choreography.noteMouseTaken();
    }
    const h = hand.getWorldPosition(new THREE.Vector3());
    const k3 = knuckles.getWorldPosition(new THREE.Vector3());
    const palm = h.clone().lerp(k3, 0.6);
    if (palm.y - this.mouseTop > MOUSE_LET_GO) return;
    const fingers = k3.sub(h).setY(0);
    if (fingers.lengthSq() < 1e-8) return;
    fingers.normalize();
    const target = palm.setY(0).addScaledVector(fingers, MOUSE_UNDER_PALM);
    mouse.updateWorldMatrix(true, false);
    const center = mouse.getWorldPosition(_v).setY(0);
    // Turned so its long axis runs along the fingers (the nearer of its two ways).
    const axisNow = this.mouseAxis.clone().applyQuaternion(mouse.getWorldQuaternion(_q)).setY(0);
    let turn = 0;
    if (axisNow.lengthSq() > 1e-8) {
      axisNow.normalize();
      turn = Math.atan2(axisNow.z * fingers.x - axisNow.x * fingers.z, axisNow.x * fingers.x + axisNow.z * fingers.z);
      if (turn > Math.PI / 2) turn -= Math.PI;
      if (turn < -Math.PI / 2) turn += Math.PI;
    }
    // The hand settles on it: a quarter second to reach the palm, then it follows.
    this.mouseT += dt;
    const k = this.mouseT < 0.25 ? 1 - Math.exp(-dt * 12) : 1;
    const worldPos = mouse.getWorldPosition(new THREE.Vector3());
    worldPos.x += (target.x - center.x) * k;
    worldPos.z += (target.z - center.z) * k;
    const worldRot = mouse.getWorldQuaternion(new THREE.Quaternion());
    const rot = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), turn * k).multiply(worldRot);
    setWorld(mouse, worldPos, rot);
    // Its height never changes: it slides on the desk.
    mouse.position.y = this.mouseY;
  }
}

/** Put an object at a world pose, whatever its parent. */
function setWorld(obj: THREE.Object3D, pos: THREE.Vector3, rot: THREE.Quaternion): void {
  const parent = obj.parent;
  if (parent) {
    parent.updateWorldMatrix(true, false);
    _m.multiplyMatrices(parent.matrixWorld.clone().invert(), new THREE.Matrix4().compose(pos, rot, obj.getWorldScale(_s)));
    _m.decompose(obj.position, obj.quaternion, _s);
  } else {
    obj.position.copy(pos);
    obj.quaternion.copy(rot);
  }
}

/** An object's long axis in its own frame: toward its vertex farthest from its centre (flat: in its horizontal plane). */
function longAxis(obj: THREE.Object3D, flat: boolean): THREE.Vector3 {
  let best = 0;
  const far = new THREE.Vector3(0, 0, 1);
  obj.updateWorldMatrix(true, true);
  const toLocal = obj.matrixWorld.clone().invert();
  obj.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const pos = mesh.geometry.getAttribute("position");
    const index = mesh.geometry.index;
    const toObj = toLocal.clone().multiply(mesh.matrixWorld);
    const n = index ? index.count : pos.count;
    for (let i = 0; i < n; i++) {
      _v.fromBufferAttribute(pos, index ? index.getX(i) : i).applyMatrix4(toObj);
      if (flat) _v.y = 0;
      const d = _v.lengthSq();
      if (d > best) {
        best = d;
        far.copy(_v);
      }
    }
  });
  return best > 1e-8 ? far.normalize() : far;
}
