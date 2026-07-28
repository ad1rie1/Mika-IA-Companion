import { VRM } from "@pixiv/three-vrm";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { HandAnimator, HandShapeName } from "./HandAnimator";

export type SleepPhase = "awake" | "light_sleep" | "rem" | "deep_sleep";

type Axis = "x" | "y" | "z";
type Pose = Partial<Record<VRMHumanBoneName, Partial<Record<Axis, number>>>>;

/**
 * Procedural idle animation: chains natural resting poses (hands behind
 * back, hand on hip, arms folded low, shoulder shrug...) with damped-
 * spring transitions, plus a continuous micro-sway so Mika never looks
 * frozen.
 *
 * What makes the motion read as human rather than robotic:
 *   - damped springs per channel (slight overshoot + settle), not a
 *     constant-rate exponential lerp
 *   - proximal→distal stagger: on a pose change the shoulders move
 *     first, then upper arms, forearms, and finally the hands trail in
 *     (follow-through)
 *   - near-body poses transition VIA the rest pose, so the hands swing
 *     around the torso instead of sweeping straight through it
 *   - each pose carries a hand shape forwarded to the HandAnimator
 *
 * Bone ownership (to coexist with the other animators):
 *   - owns: shoulders, arms, hands, spine.y/.z, hips.y/.z, and
 *     upperLegs.y/.z (counter-rotated against the hips so the feet stay
 *     planted — hips is the root bone and there is no foot IK)
 *   - never touches: spine.x (breathing, AnimationMixer), neck.x
 *     (sleep tilt, AnimationMixer), head (EmotionController), eyes
 *     (GazeController), fingers (HandAnimator), expressions.
 *
 * All pose values are DELTAS on top of the rest A-pose, in the
 * normalized rig space. Verified empirically on this rig: the character
 * faces -Z with the left arm along -X, so positive Z lowers the LEFT
 * arm and negative Z lowers the RIGHT. On the X axis, NEGATIVE swings a
 * hanging arm FORWARD and positive swings it backward — the previous
 * comment claimed the opposite, which is why "hands-behind-back" used
 * to render as hands clasped in front of the pelvis (and, with the old
 * deeper fold, inside it).
 */

// Rest A-pose — must match VTuberModel.applyRestPose.
const BASE_POSE: Pose = {
  leftUpperArm: { z: 1.15 },
  rightUpperArm: { z: -1.15 },
  leftLowerArm: { z: 0.1 },
  rightLowerArm: { z: -0.1 },
};

// Every bone+axis this animator writes each frame. Axes not listed here
// are left alone (e.g. spine.x belongs to the breathing animation).
const OWNED: Partial<Record<VRMHumanBoneName, Axis[]>> = {
  leftShoulder: ["x", "y", "z"],
  rightShoulder: ["x", "y", "z"],
  leftUpperArm: ["x", "y", "z"],
  rightUpperArm: ["x", "y", "z"],
  leftLowerArm: ["x", "y", "z"],
  rightLowerArm: ["x", "y", "z"],
  leftHand: ["x", "y", "z"],
  rightHand: ["x", "y", "z"],
  spine: ["y", "z"],
  hips: ["y", "z"],
  // y/z only: neck.x is the sleep doze tilt owned by AnimationMixer.
  neck: ["y", "z"],
};

// Spring parameters per bone. omega = stiffness (rad/s of the settle),
// zeta = damping (< 1 gives a touch of overshoot — follow-through).
// The torso is critically damped: overshoot on the spine reads drunk.
interface SpringParams {
  omega: number;
  zeta: number;
  delay: number; // seconds after a pose change before this bone reacts
}

const SPRING_BY_BONE: Partial<Record<VRMHumanBoneName, SpringParams>> = {
  spine: { omega: 3.2, zeta: 1.0, delay: 0 },
  hips: { omega: 3.0, zeta: 1.0, delay: 0 },
  neck: { omega: 3.5, zeta: 1.0, delay: 0.05 },
  leftShoulder: { omega: 4.5, zeta: 0.95, delay: 0 },
  rightShoulder: { omega: 4.5, zeta: 0.95, delay: 0 },
  leftUpperArm: { omega: 4.2, zeta: 0.88, delay: 0.07 },
  rightUpperArm: { omega: 4.2, zeta: 0.88, delay: 0.07 },
  leftLowerArm: { omega: 4.6, zeta: 0.85, delay: 0.17 },
  rightLowerArm: { omega: 4.6, zeta: 0.85, delay: 0.17 },
  leftHand: { omega: 5.0, zeta: 0.8, delay: 0.28 },
  rightHand: { omega: 5.0, zeta: 0.8, delay: 0.28 },
};

const DEFAULT_SPRING: SpringParams = { omega: 4.0, zeta: 0.9, delay: 0 };

// Time spent passing through the rest pose when both endpoints of a
// transition put hands near the torso (folded → on-hip etc.). Long
// enough for the arms to actually swing out before folding back in.
const VIA_REST_SECONDS = 0.5;

/** Cheap organic noise: three incommensurate sines summed. Reads as
 * drift, not as a metronome — the period never visibly repeats. */
function noise(t: number, seed: number): number {
  return (
    (Math.sin(t * 0.37 + seed * 1.7) +
      Math.sin(t * 0.91 + seed * 3.1) * 0.5 +
      Math.sin(t * 1.53 + seed * 5.3) * 0.25) /
    1.75
  );
}

// Axes eligible for fidget micro-adjustments while holding a pose, with
// their max amplitude (radians). Small on purpose: a fidget is a weight
// shift or elbow tweak, not a new pose.
const FIDGET_POOL: Array<[string, number]> = [
  ["leftUpperArm.z", 0.05],
  ["rightUpperArm.z", 0.05],
  ["leftLowerArm.z", 0.06],
  ["rightLowerArm.z", 0.06],
  ["leftHand.y", 0.08],
  ["rightHand.y", 0.08],
  ["spine.y", 0.035],
  ["spine.z", 0.02],
  ["hips.y", 0.035],
  ["leftShoulder.z", 0.03],
  ["rightShoulder.z", 0.03],
];

interface IdlePose {
  name: string;
  weight: number; // relative pick probability
  pose: Pose;
  // Hands end up close to the torso: transitions from/to another
  // near-body pose must route via the rest pose to avoid sweeping the
  // hands straight through the body.
  nearBody?: boolean;
  hands: [HandShapeName, HandShapeName]; // [left, right]
}

// Pose deltas are deliberately on the shallow side: with no collision
// detection, a deep fold is what sends a hand through a hip or the
// belly. Elbows are biased forward/outward (upperArm x > 0 or slight
// abduction) so folded forearms pass IN FRONT of the torso, not inside.
const IDLE_POSES: IdlePose[] = [
  {
    name: "rest",
    weight: 3,
    hands: ["relaxed", "relaxed"],
    pose: {},
  },
  {
    name: "hands-behind-back",
    weight: 1,
    nearBody: true,
    hands: ["clasp", "clasp"],
    pose: {
      leftShoulder: { z: 0.05 },
      rightShoulder: { z: -0.05 },
      // Exact front/back mirror of the empirically-proven front clasp
      // (X and Y rotation signs flip under a frontal-plane mirror, Z is
      // unchanged), slightly shallower since the body bulges more at
      // the back. If the hands still clip the skirt, reduce lowerArm.x
      // toward 0.55 before touching anything else.
      leftUpperArm: { x: 0.28, z: 0.1 },
      rightUpperArm: { x: 0.28, z: -0.1 },
      leftLowerArm: { x: 0.65, y: -0.35 },
      rightLowerArm: { x: 0.65, y: 0.35 },
      leftHand: { y: -0.2 },
      rightHand: { y: 0.2 },
      spine: { z: -0.015 },
    },
  },
  {
    // The accidental front-clasp (born from the inverted x sign) reads
    // as a natural demure idle for this character — kept on purpose.
    // Values are the screenshot-proven clasp (x:-0.3/-0.72, y:±0.4 —
    // hands met at the midline) backed off ~10% so the fingertips
    // touch without the palms interpenetrating.
    name: "hands-clasped-front",
    weight: 2,
    nearBody: true,
    hands: ["clasp", "clasp"],
    pose: {
      leftUpperArm: { x: -0.26, z: 0.08 },
      rightUpperArm: { x: -0.26, z: -0.08 },
      leftLowerArm: { x: -0.66, y: 0.34 },
      rightLowerArm: { x: -0.66, y: -0.34 },
      leftHand: { y: 0.18 },
      rightHand: { y: -0.18 },
    },
  },
  {
    name: "hand-on-hip-left",
    weight: 2,
    nearBody: true,
    hands: ["open", "relaxed"],
    pose: {
      // Slightly shallower fold than a true hand-ON-hip: the palm hovers
      // at the hip crest, which reads the same from camera distance and
      // never intersects the hip/skirt geometry.
      leftUpperArm: { z: -0.28, x: 0.04 },
      leftLowerArm: { z: 0.88, y: -0.12 },
      leftHand: { y: -0.18, x: 0.1 },
      hips: { y: 0.06 },
      spine: { z: 0.03, y: -0.04 },
    },
  },
  {
    name: "hand-on-hip-right",
    weight: 2,
    nearBody: true,
    hands: ["relaxed", "open"],
    pose: {
      rightUpperArm: { z: 0.28, x: 0.04 },
      rightLowerArm: { z: -0.88, y: 0.12 },
      rightHand: { y: 0.18, x: 0.1 },
      hips: { y: -0.06 },
      spine: { z: -0.03, y: 0.04 },
    },
  },
  {
    name: "arms-folded-low",
    weight: 2,
    nearBody: true,
    hands: ["tucked", "tucked"],
    pose: {
      // Elbows swung well forward (NEGATIVE x on this rig) so the
      // crossed forearms sit in front of the belly instead of inside it.
      leftUpperArm: { x: -0.32, z: -0.06 },
      rightUpperArm: { x: -0.32, z: 0.06 },
      leftLowerArm: { z: 0.88, x: -0.18 },
      rightLowerArm: { z: -0.88, x: -0.18 },
      leftHand: { x: 0.12 },
      rightHand: { x: 0.12 },
    },
  },
  {
    name: "weight-shift",
    weight: 2,
    hands: ["relaxed", "relaxed"],
    pose: {
      hips: { z: 0.03, y: 0.08 },
      spine: { z: -0.05, y: -0.05 },
      leftUpperArm: { z: 0.06 },
      rightUpperArm: { z: 0.04 },
    },
  },
  {
    name: "shoulder-shrug-stretch",
    weight: 1,
    hands: ["relaxed", "relaxed"],
    pose: {
      leftShoulder: { z: -0.12 },
      rightShoulder: { z: 0.12 },
      leftUpperArm: { z: 0.12 },
      rightUpperArm: { z: -0.12 },
      spine: { y: 0.03 },
    },
  },
];

const REST_POSE = IDLE_POSES[0];

function pickPose(exclude: string): IdlePose {
  const candidates = IDLE_POSES.filter((p) => p.name !== exclude);
  const total = candidates.reduce((s, p) => s + p.weight, 0);
  let r = Math.random() * total;
  for (const p of candidates) {
    r -= p.weight;
    if (r <= 0) return p;
  }
  return candidates[candidates.length - 1];
}

interface SpringState {
  pos: number;
  vel: number;
}

export class IdleAnimator {
  private vrm: VRM | null = null;
  private hands: HandAnimator | null = null;
  private sleepPhase: SleepPhase = "awake";
  private isSpeaking = false;

  private time = 0;
  private poseTimer = 0;
  private nextPoseAt = 4 + Math.random() * 4; // first change comes early
  private currentPose: IdlePose = REST_POSE;
  private prevPose: IdlePose = REST_POSE;
  private transitionAt = -10; // time of the last pose commit

  // Via-rest waypoint: when set, we are currently heading to rest and
  // will commit this pose once the waypoint time has elapsed.
  private pendingPose: IdlePose | null = null;
  private pendingAt = 0;

  // Debug: when set, the scheduler is paused and this pose is held.
  private forcedPose: IdlePose | null = null;

  // One damped spring per "bone.axis" channel.
  private springs = new Map<string, SpringState>();

  // Fidget: small random re-adjustments fired every few seconds while
  // HOLDING a pose — this is what keeps a held pose from reading as a
  // wax statue. Values feed the spring targets, so they settle in with
  // the same natural motion as pose changes.
  private fidget = new Map<string, number>();
  private fidgetTimer = 0;
  private nextFidgetAt = 2 + Math.random() * 3;

  // 0..1 factor easing sway/poses out when falling asleep.
  private awakeFactor = 1;

  setVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  /** Attach the finger animator; pose changes forward a hand shape. */
  attachHands(hands: HandAnimator): void {
    this.hands = hands;
    hands.setPoseShape(...this.currentPose.hands);
  }

  setSleepPhase(phase: SleepPhase): void {
    this.sleepPhase = phase;
  }

  setSpeaking(speaking: boolean): void {
    this.isSpeaking = speaking;
  }

  /** Debug (Alt+P in main.ts): pin the next pose in the list so every
   * pose can be visually checked on the live model in seconds. */
  cyclePose(): string {
    const idx = IDLE_POSES.findIndex(
      (p) => p.name === (this.forcedPose?.name ?? "")
    );
    const next = IDLE_POSES[(idx + 1) % IDLE_POSES.length];
    this.forcedPose = next;
    this.pendingPose = null;
    this.commitPose(next);
    return next.name;
  }

  /** Debug (Alt+O): release the pinned pose, resume auto-scheduling. */
  releasePose(): void {
    this.forcedPose = null;
    this.poseTimer = 0;
  }

  update(delta: number): void {
    const humanoid = this.vrm?.humanoid;
    if (!humanoid) return;

    // A background-tab lag spike must not explode the springs; motion
    // just takes a few extra frames to catch up instead.
    const dt = Math.min(delta, 0.08);
    this.time += dt;

    const awakeTarget = this.sleepPhase === "awake" ? 1 : 0;
    this.awakeFactor += (awakeTarget - this.awakeFactor) * Math.min(1, dt * 1.2);

    // --- Pose + fidget scheduling (paused while asleep) ---
    if (this.sleepPhase === "awake") {
      this.schedulePoses(dt);

      this.fidgetTimer += dt;
      if (this.fidgetTimer >= this.nextFidgetAt) {
        this.fidgetTimer = 0;
        this.nextFidgetAt = 2 + Math.random() * 4;
        this.fireFidget();
      }
    }

    // --- Spring every owned axis toward base + pose delta + fidget ---
    // Final hips rotation this frame, captured for the leg counter-pivot.
    let hipsY = 0;
    let hipsZ = 0;

    for (const [bone, axes] of Object.entries(OWNED) as [
      VRMHumanBoneName,
      Axis[]
    ][]) {
      const node = humanoid.getNormalizedBoneNode(bone);
      if (!node) continue;

      const params = SPRING_BY_BONE[bone] ?? DEFAULT_SPRING;
      // Proximal→distal stagger: until this bone's delay has elapsed
      // since the pose commit, it keeps chasing the PREVIOUS pose. The
      // shoulders lead, the hands trail — follow-through, not lockstep.
      const activePose =
        this.time - this.transitionAt >= params.delay
          ? this.currentPose.pose
          : this.prevPose.pose;

      for (const axis of axes) {
        const key = `${bone}.${axis}`;
        const target =
          ((activePose[bone]?.[axis] ?? 0) + (this.fidget.get(key) ?? 0)) *
          this.awakeFactor;

        let s = this.springs.get(key);
        if (!s) {
          s = { pos: 0, vel: 0 };
          this.springs.set(key, s);
        }
        s.vel +=
          (params.omega * params.omega * (target - s.pos) -
            2 * params.zeta * params.omega * s.vel) *
          dt;
        s.pos += s.vel * dt;

        const value =
          (BASE_POSE[bone]?.[axis] ?? 0) + s.pos + this.sway(bone, axis);
        node.rotation[axis] = value;

        if (bone === "hips") {
          if (axis === "y") hipsY = value;
          else if (axis === "z") hipsZ = value;
        }
      }
    }

    // Counter-rotate the thighs by the hips' yaw/tilt: hips is the ROOT
    // humanoid bone, so rotating it alone pivots the legs too and the
    // feet visibly skate on the floor (there is no foot IK). With the
    // counter-pivot, a weight shift reads as the pelvis moving over
    // PLANTED feet — actual contrapposto instead of a skeleton twist.
    const leftLeg = humanoid.getNormalizedBoneNode("leftUpperLeg");
    const rightLeg = humanoid.getNormalizedBoneNode("rightUpperLeg");
    if (leftLeg) {
      leftLeg.rotation.y = -hipsY;
      leftLeg.rotation.z = -hipsZ;
    }
    if (rightLeg) {
      rightLeg.rotation.y = -hipsY;
      rightLeg.rotation.z = -hipsZ;
    }
  }

  /** Pose picking, via-rest waypoint handling, and hand-shape fan-out. */
  private schedulePoses(dt: number): void {
    if (this.forcedPose) return; // debug pin: hold the pose


    // Commit a pending pose once the via-rest leg has been travelled.
    if (this.pendingPose && this.time >= this.pendingAt) {
      this.commitPose(this.pendingPose);
      this.pendingPose = null;
      return;
    }

    this.poseTimer += dt;
    if (this.poseTimer < this.nextPoseAt || this.pendingPose) return;

    this.poseTimer = 0;
    // Livelier cadence while talking, calmer when just idling.
    this.nextPoseAt = this.isSpeaking
      ? 5 + Math.random() * 4
      : 7 + Math.random() * 6;

    const next = pickPose(this.currentPose.name);

    // Both endpoints near the torso → the straight-line sweep between
    // them passes through the body. Route via rest: arms drop to the
    // sides first, then fold into the new pose.
    if (this.currentPose.nearBody && next.nearBody) {
      this.commitPose(REST_POSE);
      this.pendingPose = next;
      this.pendingAt = this.time + VIA_REST_SECONDS;
      // Hands prep early — fingers reshape while the arms travel.
      this.hands?.setPoseShape(...next.hands);
    } else {
      this.commitPose(next);
    }
  }

  private commitPose(pose: IdlePose): void {
    this.prevPose = this.currentPose;
    this.currentPose = pose;
    this.transitionAt = this.time;
    this.fidget.clear(); // new pose supersedes pending adjustments
    this.hands?.setPoseShape(...pose.hands);
  }

  /** Pick 2-3 random axes and nudge them: a weight shift, an elbow
   * tweak, a shoulder settle. Half the time an old nudge also relaxes
   * back, so fidgets don't accumulate into a drifted pose. */
  private fireFidget(): void {
    const count = 2 + Math.floor(Math.random() * 2);
    for (let i = 0; i < count; i++) {
      const [key, amp] = FIDGET_POOL[
        Math.floor(Math.random() * FIDGET_POOL.length)
      ];
      this.fidget.set(key, (Math.random() * 2 - 1) * amp);
    }
    for (const key of this.fidget.keys()) {
      if (Math.random() < 0.5) this.fidget.delete(key);
    }
  }

  /** Continuous low-amplitude organic motion so a held pose never reads
   * as a freeze frame: torso breathes and drifts, head subtly turns and
   * tilts (neck y/z only — neck.x is the sleep tilt), arms float, and
   * the wrists carry a faint independent drift. While speaking, the
   * arms get noise-driven gesture motion (never a metronomic sine). */
  private sway(bone: VRMHumanBoneName, axis: Axis): number {
    const t = this.time;
    const a = this.awakeFactor;
    let v = 0;

    if (bone === "spine" && axis === "y") v = noise(t, 1) * 0.028;
    else if (bone === "spine" && axis === "z") v = noise(t, 2) * 0.014;
    else if (bone === "hips" && axis === "y") v = noise(t, 3) * 0.016;
    else if (bone === "hips" && axis === "z") v = noise(t, 4) * 0.008;
    else if (bone === "neck" && axis === "y") v = noise(t * 0.7, 5) * 0.06;
    else if (bone === "neck" && axis === "z") v = noise(t * 0.6, 6) * 0.025;
    else if (bone === "leftShoulder" && axis === "z") v = noise(t, 7) * 0.012;
    else if (bone === "rightShoulder" && axis === "z") v = noise(t, 8) * 0.012;
    else if (bone === "leftUpperArm" && axis === "z") v = noise(t, 9) * 0.015;
    else if (bone === "rightUpperArm" && axis === "z")
      v = noise(t, 10) * 0.015;
    // Wrists float a little on their own — dead-still hands at the end
    // of moving arms is one of the strongest "it's a rig" tells.
    else if (bone === "leftHand" && axis === "y") v = noise(t * 0.8, 11) * 0.02;
    else if (bone === "rightHand" && axis === "y")
      v = noise(t * 0.8, 12) * 0.02;
    else if (bone === "leftHand" && axis === "z") v = noise(t * 0.9, 13) * 0.015;
    else if (bone === "rightHand" && axis === "z")
      v = noise(t * 0.9, 14) * 0.015;

    if (this.isSpeaking) {
      // Conversational gesturing: organic noise, per-arm seeds, slightly
      // different rates so the arms never sync up like a metronome.
      if (bone === "leftUpperArm" && axis === "x")
        v += noise(t * 1.8, 15) * 0.05;
      else if (bone === "rightUpperArm" && axis === "x")
        v += noise(t * 1.7, 16) * 0.05;
      else if (bone === "leftLowerArm" && axis === "z")
        v += noise(t * 1.6, 17) * 0.04;
      else if (bone === "rightLowerArm" && axis === "z")
        v += noise(t * 1.5, 18) * 0.04;
    }

    return v * a;
  }
}
