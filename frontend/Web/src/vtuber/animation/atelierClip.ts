import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import { isVRM0 } from "../vrmVersion";
import { STRIPPED_VRM_BONES, type RetargetReport } from "./mixamoRetarget";

/**
 * The Unity client's animations, on the web.
 *
 * Every body clip of the Unity client comes out of the Blender animation
 * workshop (`frontend/Web/assets-src/blender/atelier_*.py`), fitted on HER
 * skeleton — the same Perula model as public/models/default.vrm — and
 * checked against the real furniture: feet planted on their soles, hands
 * kept out of the body, loops closed, seated hips at the chair's height,
 * the walk made symmetric. The workshop writes each one as
 * `frontend/Unity/ArtSource/atelier/motions/<name>.json.gz` (bones only,
 * no mesh), which Unity's `AtelierImporter` turns into humanoid clips —
 * and which this module turns into clips on the VRM's normalized bones.
 *
 * The format: `bones` (VRM humanoid names), `rest` (each bone's world
 * position `p` and rotation `q` = [w, x, y, z] in the workshop's T-pose,
 * Blender space: Z up, facing −Y) and `frames` (per frame: the hips world
 * position, then each bone's world rotation [w, x, y, z]).
 *
 * The math is the Mixamo retarget's (mixamoRetarget.ts): a normalized
 * bone has the identity as rest world rotation, so its local rotation is
 * its world change from the T-pose, relative to its parent's —
 *
 *     D(b) = M · q_now(b) · q_rest(b)⁻¹ · M⁻¹,   local(b) = D(parent)⁻¹ · D(b)
 *
 * where M takes the workshop's frame (up, left, ahead, measured on its
 * T-pose like Unity's `AtelierImporter.Space`) to the VRM 1.0 one (Y up,
 * +X left, facing +Z), conjugated by Ry(π) for a VRM 0.x rig as every clip.
 */

export interface AtelierMotion {
  name: string;
  fps: number;
  loop: boolean;
  /** The clip travels (a walk): the locomotion carries the body, the clip is played in place. */
  travel: boolean;
  note?: string;
  bones: string[];
  rest: Record<string, { p: [number, number, number]; q: [number, number, number, number] }>;
  frames: number[][];
  /** A gesture's own curves (the chair it rolls, an object held) — Unity reads them; the web does not yet. */
  curves?: Record<string, number[]>;
}

/** What a workshop clip measures, for whoever plays it. */
export interface AtelierMeasures {
  /** Ground speed of a travelling clip (m/s), before it was made in place. */
  speed?: number;
  /** Mean height of the hips over the clip (m): seated, where the seat must put them. */
  hipsHeight: number;
}

/** Bones the web's own controllers own: the fingers (HandAnimator) and the eyes (GazeController). */
const OWNED_ELSEWHERE: ReadonlySet<string> = new Set<string>([...STRIPPED_VRM_BONES, "leftEye", "rightEye"]);

/** The workshop's names that differ from three-vrm's (Unity's humanoid thumb chain). */
const VRM_NAME: Readonly<Record<string, string>> = {
  leftThumbProximal: "leftThumbMetacarpal",
  leftThumbIntermediate: "leftThumbProximal",
  rightThumbProximal: "rightThumbMetacarpal",
  rightThumbIntermediate: "rightThumbProximal",
};

/** Is this manifest URL a workshop motion (rather than a Mixamo FBX)? */
export function isAtelierUrl(url: string): boolean {
  return /\.json(\.gz)?$/i.test(url);
}

/** Fetch a workshop motion; gunzip it unless the server already did (Content-Encoding). */
export async function fetchAtelierMotion(url: string): Promise<AtelierMotion> {
  const res = await fetch(encodeURI(url));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  let text: string;
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return JSON.parse(text) as AtelierMotion;
}

/** The world change of each bone from the T-pose, per frame, in the VRM 1.0 frame. */
export interface AtelierDeltas {
  times: number[];
  /** Hips world position per frame (x, y, z), meters, VRM 1.0 frame. */
  hips: Float32Array;
  /** Per bone, the world rotation change per frame (x, y, z, w). */
  rotations: Map<string, Float32Array>;
  /** The hips' rest height (m). */
  restHipsHeight: number;
}

const _e = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
const _q = new THREE.Quaternion();
const _rest = new THREE.Quaternion();
const _v = new THREE.Vector3();

/**
 * The rotation that takes the workshop's T-pose frame — up (hips → head),
 * left (right hand → left hand), ahead (foot → toes), orthonormalized in
 * that order — to the VRM 1.0 one (+Y, +X, +Z).
 */
export function workshopFrame(rest: AtelierMotion["rest"]): THREE.Quaternion {
  const p = (b: string) => {
    const r = rest[b];
    if (!r) throw new Error(`rest pose without « ${b} »`);
    return new THREE.Vector3(...r.p);
  };
  const up = _e[0].copy(p("head")).sub(p("hips")).normalize();
  const left = _e[1].copy(p("leftHand")).sub(p("rightHand"));
  left.addScaledVector(up, -left.dot(up)).normalize();
  const ahead = _e[2].copy(p("leftToes")).sub(p("leftFoot"));
  ahead.addScaledVector(up, -ahead.dot(up)).addScaledVector(left, -ahead.dot(left)).normalize();
  // Workshop → VRM: the workshop basis (up, left, ahead) maps onto (Y, X, Z).
  const workshop = new THREE.Matrix4().makeBasis(up, left, ahead);
  const vrm = new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 1, 0), new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 1));
  const m = vrm.multiply(workshop.transpose());
  if (m.determinant() < 0) throw new Error("the workshop's T-pose is mirrored relative to the VRM's");
  return new THREE.Quaternion().setFromRotationMatrix(m);
}

/** Decode a workshop motion into world changes from the T-pose (pure: no VRM involved). */
export function atelierDeltas(motion: AtelierMotion): AtelierDeltas {
  const m = workshopFrame(motion.rest);
  const mInv = m.clone().invert();
  const n = motion.frames.length;
  const times = Array.from({ length: n }, (_, i) => i / motion.fps);
  const hips = new Float32Array(n * 3);
  const rotations = new Map<string, Float32Array>();
  const restInverse = motion.bones.map((b) => {
    const q = motion.rest[b]?.q ?? [1, 0, 0, 0];
    return new THREE.Quaternion(q[1], q[2], q[3], q[0]).invert();
  });
  for (const b of motion.bones) rotations.set(b, new Float32Array(n * 4));
  for (let i = 0; i < n; i++) {
    const row = motion.frames[i];
    _v.set(row[0], row[1], row[2]).applyQuaternion(m);
    hips.set([_v.x, _v.y, _v.z], 3 * i);
    for (let j = 0; j < motion.bones.length; j++) {
      const k = 3 + 4 * j;
      // M · q_now · q_rest⁻¹ · M⁻¹
      _q.set(row[k + 1], row[k + 2], row[k + 3], row[k]).multiply(restInverse[j]);
      _q.premultiply(m).multiply(mInv).normalize();
      rotations.get(motion.bones[j])!.set([_q.x, _q.y, _q.z, _q.w], 4 * i);
    }
  }
  const restHips = _v.set(...(motion.rest.hips?.p ?? [0, 0, 0])).applyQuaternion(m);
  return { times, hips, rotations, restHipsHeight: restHips.y };
}

export interface AtelierRetarget {
  clip: THREE.AnimationClip;
  report: RetargetReport;
  measures: AtelierMeasures;
}

/**
 * A workshop motion as an AnimationClip on the VRM's normalized bones.
 * A travelling clip (the walk) is made in place: the drift of its hips
 * from the first frame to the last is taken out (the sway stays), and its
 * ground speed is kept in `measures.speed` so the walk cycle can be played
 * at the pace the body really moves.
 */
export function retargetAtelierClip(motion: AtelierMotion, vrm: VRM, clipName: string): AtelierRetarget {
  const humanoid = vrm.humanoid;
  if (!humanoid) throw new Error(`${clipName}: VRM has no humanoid`);
  if (motion.frames.length < 2) throw new Error(`${clipName}: fewer than two frames`);
  const d = atelierDeltas(motion);
  const n = d.times.length;
  const flip = isVRM0(vrm);

  // Each workshop bone, on the rig; its parent is the nearest ancestor the
  // workshop animates too (a VRM upperChest it does not know keeps its rest).
  const nodes = new Map<string, THREE.Object3D>();
  const dropped: string[] = [];
  for (const b of motion.bones) {
    const node = humanoid.getNormalizedBoneNode((VRM_NAME[b] ?? b) as VRMHumanBoneName);
    if (node) nodes.set(b, node);
    else dropped.push(b);
  }
  const boneOf = new Map<THREE.Object3D, string>([...nodes].map(([b, node]) => [node, b]));
  const parentOf = (node: THREE.Object3D): string | null => {
    for (let p = node.parent; p; p = p.parent) {
      const b = boneOf.get(p);
      if (b) return b;
    }
    return null;
  };

  const tracks: THREE.KeyframeTrack[] = [];
  let stripped = 0;
  const parentQ = new THREE.Quaternion();
  for (const [b, node] of nodes) {
    if (OWNED_ELSEWHERE.has(VRM_NAME[b] ?? b)) {
      stripped++;
      continue;
    }
    const own = d.rotations.get(b)!;
    const parent = parentOf(node);
    const parentRotations = parent ? d.rotations.get(parent)! : null;
    const values = new Float32Array(n * 4);
    for (let i = 0; i < n; i++) {
      _q.fromArray(own, 4 * i);
      if (parentRotations) _q.premultiply(parentQ.fromArray(parentRotations, 4 * i).invert());
      values.set([flip ? -_q.x : _q.x, _q.y, flip ? -_q.z : _q.z, _q.w], 4 * i);
    }
    tracks.push(new THREE.QuaternionKeyframeTrack(`${node.name}.quaternion`, d.times, Array.from(values)));
  }

  // The hips: the same body, the VRM's own rest height (1 for her model).
  const restHips = humanoid.normalizedRestPose.hips?.position;
  const scale = restHips && d.restHipsHeight > 1e-6 ? Math.abs(restHips[1]) / d.restHipsHeight : 1;
  const duration = d.times[n - 1];
  const drift = { x: d.hips[3 * (n - 1)] - d.hips[0], z: d.hips[3 * (n - 1) + 2] - d.hips[2] };
  const hipsNode = nodes.get("hips");
  let height = 0;
  if (hipsNode) {
    const values = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const k = motion.travel ? i / (n - 1) : 0;
      let x = (d.hips[3 * i] - drift.x * k) * scale;
      const y = d.hips[3 * i + 1] * scale;
      let z = (d.hips[3 * i + 2] - drift.z * k) * scale;
      if (flip) {
        x = -x;
        z = -z;
      }
      values.set([x, y, z], 3 * i);
      height += y / n;
    }
    tracks.push(new THREE.VectorKeyframeTrack(`${hipsNode.name}.position`, d.times, Array.from(values)));
  }
  if (tracks.length === 0) throw new Error(`${clipName}: no retargetable tracks`);

  const measures: AtelierMeasures = { hipsHeight: height };
  if (motion.travel && duration > 0) measures.speed = (Math.hypot(drift.x, drift.z) * scale) / duration;
  const report: RetargetReport = {
    clipName,
    sourceClipName: motion.name,
    duration,
    mappedTracks: tracks.length,
    strippedFingerTracks: stripped,
    droppedTracks: dropped,
    hipsPositionScale: scale,
    hipsScaleSuspicious: scale < 0.5 || scale > 2,
  };
  return { clip: new THREE.AnimationClip(clipName, duration, tracks), report, measures };
}
