import { VRM } from "@pixiv/three-vrm";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import type { EmotionName, HandShapeName, SleepPhase } from "../../types";

/**
 * Full finger articulation for both hands (30 VRM humanoid bones).
 *
 * The Mixamo retarget STRIPS finger tracks (mixamoRetarget.ts), so this
 * animator keeps exclusive ownership of the finger bones — its absolute
 * writes never fight the clip mixer. Fingers are the one place where
 * procedural beats Mixamo: emotion-reactive curl, ripples, sleep shapes.
 *
 * What it layers, per finger:
 *   1. base shape        — from the current clip's manifest `hands` entry
 *   2. emotion offset    — tense curl when angry, open + lively when excited
 *   3. organic noise     — slow per-finger drift so hands never freeze
 *   4. ripple events     — a little→index curl wave every few seconds,
 *                          the classic human finger fidget
 *   5. spring smoothing  — per-finger, staggered (index leads, little
 *                          trails) so shape changes cascade naturally
 *
 * Sign conventions follow the empirically-verified rig convention
 * (left arm along -X, so left-hand curl is +Z, right-hand curl is -Z;
 * thumbs curl around ±Y). If a different model bends fingers backward,
 * flip CURL_SIGN / THUMB_SIGN.
 */

type Side = "left" | "right";
const SIDES: Side[] = ["left", "right"];

const CURL_SIGN: Record<Side, number> = { left: 1, right: -1 };
const THUMB_SIGN: Record<Side, number> = { left: 1, right: -1 };

// Fingers animated through the 3-joint curl chain.
const FINGERS = ["index", "middle", "ring", "little"] as const;
type Finger = (typeof FINGERS)[number];

// Literal-typed capitalization map: keeps the template-literal bone
// names below checkable against VRMHumanBoneName at compile time (a
// typo in a generated name becomes a tsc error, not a silent no-op).
const FINGER_CAP = {
  index: "Index",
  middle: "Middle",
  ring: "Ring",
  little: "Little",
} as const;

// Max flexion per joint (radians) at curl = 1. A relaxed hand sits
// around curl 0.3; nothing in this file drives curl past ~0.8.
const PROXIMAL_MAX = 1.05;
const INTERMEDIATE_MAX = 1.25;
const DISTAL_MAX = 0.65;

// Natural resting gradient: the index stays straighter, the little
// finger folds deeper. A hand with uniform curl reads as a mannequin.
const FINGER_GRADIENT: Record<Finger, number> = {
  index: 0.78,
  middle: 0.95,
  ring: 1.08,
  little: 1.18,
};

// Per-finger spring stagger (s) on shape changes: index leads, little
// trails — the cascade is what makes a grip/release read as organic.
const FINGER_DELAY: Record<Finger, number> = {
  index: 0,
  middle: 0.05,
  ring: 0.1,
  little: 0.15,
};

// Finger spread (abduction) on the proximal joints, rotation around Y.
// Direction per finger: index fans toward the thumb side, little away.
const SPREAD_DIR: Record<Finger, number> = {
  index: 1,
  middle: 0.25,
  ring: -0.35,
  little: -1,
};
const SPREAD_MAX = 0.12;

interface HandShape {
  curl: number; // 0 = straight, 1 = fist
  spread: number; // 0 = fingers together, 1 = fanned
  thumbCurl: number;
}

const SHAPES: Record<HandShapeName, HandShape> = {
  // Neutral standing hand: fingers gently curled, thumb soft.
  relaxed: { curl: 0.28, spread: 0.15, thumbCurl: 0.25 },
  // Hand planted on a hip: fingers extended and fanned over the crest.
  open: { curl: 0.1, spread: 0.7, thumbCurl: 0.15 },
  // Arms folded: fingers wrap the opposite forearm.
  tucked: { curl: 0.5, spread: 0.0, thumbCurl: 0.4 },
  // Deep sleep / drowsy: heavy, half-closed.
  loose: { curl: 0.38, spread: 0.05, thumbCurl: 0.3 },
  // Hands clasped: half-holding the other hand.
  clasp: { curl: 0.42, spread: 0.0, thumbCurl: 0.35 },
};

// How emotions shade the hands. curl is an offset on the shape's curl,
// speed multiplies spring stiffness, micro multiplies noise amplitude.
// Scaled by emotion intensity before applying.
interface HandMood {
  curl: number;
  speed: number;
  micro: number;
}

const EMOTION_HAND: Partial<Record<EmotionName, HandMood>> = {
  angry: { curl: 0.24, speed: 1.6, micro: 1.3 },
  frustrated: { curl: 0.18, speed: 1.4, micro: 1.3 },
  scared: { curl: 0.18, speed: 1.5, micro: 1.5 },
  anxious: { curl: 0.1, speed: 1.2, micro: 1.7 },
  determined: { curl: 0.12, speed: 1.3, micro: 0.9 },
  jealous: { curl: 0.12, speed: 1.2, micro: 1.1 },
  excited: { curl: -0.06, speed: 1.5, micro: 1.7 },
  happy: { curl: -0.04, speed: 1.2, micro: 1.2 },
  playful: { curl: -0.04, speed: 1.3, micro: 1.5 },
  surprised: { curl: -0.08, speed: 1.6, micro: 1.2 },
  sad: { curl: 0.04, speed: 0.7, micro: 0.55 },
  lonely: { curl: 0.04, speed: 0.7, micro: 0.55 },
  melancholic: { curl: 0.04, speed: 0.75, micro: 0.6 },
  bored: { curl: 0.02, speed: 0.8, micro: 0.8 },
  dreamy: { curl: 0.02, speed: 0.7, micro: 0.5 },
  relieved: { curl: 0.0, speed: 0.85, micro: 0.7 },
};

const NEUTRAL_MOOD: HandMood = { curl: 0, speed: 1, micro: 1 };

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

interface FingerSpring {
  pos: number; // current curl value
  vel: number;
}

export class HandAnimator {
  private vrm: VRM | null = null;
  private sleepPhase: SleepPhase = "awake";
  private isSpeaking = false;

  private time = 0;

  private shapeTarget: Record<Side, HandShapeName> = {
    left: "relaxed",
    right: "relaxed",
  };
  // Stamped on shape change so the per-finger stagger delays apply from
  // the moment of the change, not from t=0.
  private shapeChangedAt: Record<Side, number> = { left: -10, right: -10 };
  private prevShape: Record<Side, HandShapeName> = {
    left: "relaxed",
    right: "relaxed",
  };

  private mood: HandMood = { ...NEUTRAL_MOOD };

  // One spring per (side, finger) on the curl scalar; thumbs get their
  // own; spread is a single eased value per side.
  private springs = new Map<string, FingerSpring>();
  private spreadCurrent: Record<Side, number> = { left: 0.15, right: 0.15 };

  // Finger ripple: a transient curl wave travelling little → index.
  private rippleAt = 0;
  private nextRippleIn = 5 + Math.random() * 6;

  setVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setSleepPhase(phase: SleepPhase): void {
    this.sleepPhase = phase;
  }

  setSpeaking(speaking: boolean): void {
    this.isSpeaking = speaking;
  }

  /** Called by the state machine when the base clip changes (manifest
   * `hands` metadata). */
  setPoseShape(left: HandShapeName, right: HandShapeName): void {
    if (left !== this.shapeTarget.left) {
      this.prevShape.left = this.shapeTarget.left;
      this.shapeTarget.left = left;
      this.shapeChangedAt.left = this.time;
    }
    if (right !== this.shapeTarget.right) {
      this.prevShape.right = this.shapeTarget.right;
      this.shapeTarget.right = right;
      this.shapeChangedAt.right = this.time;
    }
  }

  setEmotion(emotion: EmotionName, intensity: number): void {
    const m = EMOTION_HAND[emotion] ?? NEUTRAL_MOOD;
    const s = Math.max(0, Math.min(1, intensity));
    this.mood = {
      curl: m.curl * s,
      speed: 1 + (m.speed - 1) * s,
      micro: 1 + (m.micro - 1) * s,
    };
  }

  update(delta: number): void {
    const humanoid = this.vrm?.humanoid;
    if (!humanoid) return;

    // Clamp: a background-tab lag spike shouldn't explode the springs.
    const dt = Math.min(delta, 0.08);
    this.time += dt;

    const asleep = this.sleepPhase !== "awake";

    // --- Ripple scheduling (awake only) ---
    if (!asleep) {
      if (this.time - this.rippleAt > this.nextRippleIn) {
        this.rippleAt = this.time;
        this.nextRippleIn = this.isSpeaking
          ? 3 + Math.random() * 4
          : 7 + Math.random() * 8;
      }
    }

    const microAmp =
      (asleep ? 0.006 : 0.035 * this.mood.micro) *
      (this.isSpeaking ? 1.5 : 1);

    for (const side of SIDES) {
      const shape = asleep
        ? SHAPES.loose
        : SHAPES[this.shapeTarget[side]];
      const prevShape = SHAPES[this.prevShape[side]];
      const changedAt = this.shapeChangedAt[side];

      // Spread eases as one value per hand (slow, no spring needed).
      const spreadEase = Math.min(1, dt * 2.5);
      this.spreadCurrent[side] +=
        (shape.spread - this.spreadCurrent[side]) * spreadEase;

      for (let fi = 0; fi < FINGERS.length; fi++) {
        const finger = FINGERS[fi];
        // Stagger: until this finger's delay has elapsed, it keeps
        // chasing the previous shape — the change cascades index→little.
        const active =
          this.time - changedAt >= FINGER_DELAY[finger] ? shape : prevShape;

        let targetCurl =
          active.curl * FINGER_GRADIENT[finger] + this.mood.curl;

        // Organic drift, one seed per (side, finger).
        const seed = (side === "left" ? 20 : 40) + fi * 3.7;
        targetCurl += noise(this.time * 0.4, seed) * microAmp;

        // Ripple wave little → index.
        const rippleOffset = (FINGERS.length - 1 - fi) * 0.07;
        const u = (this.time - this.rippleAt - rippleOffset) / 0.35;
        if (u > 0 && u < 1 && !asleep) {
          targetCurl += Math.sin(Math.PI * u) * 0.1;
        }

        targetCurl = Math.max(0, Math.min(0.85, targetCurl));

        const curl = this.stepSpring(
          `${side}.${finger}`,
          targetCurl,
          dt,
          asleep ? 3 : 9 * this.mood.speed,
          0.85
        );

        this.applyFinger(side, finger, curl);
      }

      // Thumb: own spring, gentler motion (its noise reads as twitchy
      // fast, so quarter amplitude).
      const thumbSeed = side === "left" ? 61 : 67;
      let thumbTarget =
        (asleep ? SHAPES.loose : shape).thumbCurl +
        this.mood.curl * 0.6 +
        noise(this.time * 0.3, thumbSeed) * microAmp * 0.25;
      thumbTarget = Math.max(0, Math.min(0.8, thumbTarget));
      const thumbCurl = this.stepSpring(
        `${side}.thumb`,
        thumbTarget,
        dt,
        asleep ? 3 : 7 * this.mood.speed,
        0.9
      );
      this.applyThumb(side, thumbCurl);
    }
  }

  /** Semi-implicit damped spring on one scalar channel. */
  private stepSpring(
    key: string,
    target: number,
    dt: number,
    omega: number,
    zeta: number
  ): number {
    let s = this.springs.get(key);
    if (!s) {
      s = { pos: target, vel: 0 };
      this.springs.set(key, s);
    }
    // Substepped: this explicit-damping semi-implicit integrator is only
    // stable for omega*dt < 2*(sqrt(zeta^2+1)-zeta) (≈0.93 at zeta 0.85).
    // Agitated emotions push omega to ~14, so at the 0.08s frame clamp a
    // single step diverges (fingers spin, then NaN). 0.02s substeps keep
    // omega*dt ≤ 0.29 in the worst case — unconditionally safe here.
    let remaining = dt;
    while (remaining > 1e-6) {
      const h = Math.min(remaining, 0.02);
      s.vel +=
        (omega * omega * (target - s.pos) - 2 * zeta * omega * s.vel) * h;
      s.pos += s.vel * h;
      remaining -= h;
    }
    return s.pos;
  }

  private bone(name: VRMHumanBoneName) {
    return this.vrm!.humanoid!.getNormalizedBoneNode(name);
  }

  private applyFinger(side: Side, finger: Finger, curl: number): void {
    const sign = CURL_SIGN[side];
    const cap = FINGER_CAP[finger];

    const proximal = this.bone(`${side}${cap}Proximal`);
    const intermediate = this.bone(`${side}${cap}Intermediate`);
    const distal = this.bone(`${side}${cap}Distal`);

    if (proximal) {
      proximal.rotation.z = sign * curl * PROXIMAL_MAX;
      // Spread lives on the proximal joint only. Sign mirrors the curl
      // convention (rig is X-mirrored vs the VRM1 standard).
      proximal.rotation.y =
        -sign * SPREAD_DIR[finger] * this.spreadCurrent[side] * SPREAD_MAX;
    }
    if (intermediate) intermediate.rotation.z = sign * curl * INTERMEDIATE_MAX;
    if (distal) distal.rotation.z = sign * curl * DISTAL_MAX;
  }

  private applyThumb(side: Side, curl: number): void {
    const sign = THUMB_SIGN[side];

    const metacarpal = this.bone(`${side}ThumbMetacarpal`);
    const proximal = this.bone(`${side}ThumbProximal`);
    const distal = this.bone(`${side}ThumbDistal`);

    // Thumb flexes around Y in this rig's normalized space. A small
    // constant on the metacarpal keeps the thumb resting against the
    // index side instead of sticking out at the bind angle.
    if (metacarpal) metacarpal.rotation.y = sign * (0.12 + curl * 0.35);
    if (proximal) proximal.rotation.y = sign * curl * 0.5;
    if (distal) distal.rotation.y = sign * curl * 0.55;
  }
}
