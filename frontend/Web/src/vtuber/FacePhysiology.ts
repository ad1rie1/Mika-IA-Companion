import type { VRM } from "@pixiv/three-vrm";
import type { EmotionName } from "../types";
import { rawName, registerRawMorphs } from "./faceRig";

/**
 * What the face does that is NOT an expression: blood, tears, pupils.
 *
 * An expression is a muscle — it arrives in a fraction of a second and
 * leaves almost as fast. These are physiology, and they run on their own,
 * slower clocks, which is precisely what makes them read as real:
 *
 *   - blush: blood takes a second or two to come to the cheeks and much
 *     longer to leave — an embarrassment stays on the face after the
 *     expression has moved on;
 *   - tears: they WELL UP. A sustained sadness first makes the eyes
 *     glisten, then, if it lasts and is strong, a tear forms — never on
 *     the first frame of a mildly sad sentence (the model's `Sad1` group
 *     drew a tear at any sadness intensity). Strong laughter and being
 *     deeply moved can bring them too; they dry slowly;
 *   - pupils: they widen with interest, affection and fear, narrow with
 *     anger and disgust — small, slow, and read without being noticed.
 *
 * Driven from the same (emotion, intensity) the face receives. Writes only
 * its own `raw:` morphs, disjoint from every other face layer.
 */

const BLUSH: Partial<Record<EmotionName, number>> = {
  embarrassed: 0.95,
  love: 0.75,
  excited: 0.3,
  amused: 0.3,
  angry: 0.35,
  grateful: 0.25,
  playful: 0.2,
  proud: 0.15,
  jealous: 0.2,
  frustrated: 0.18,
  dreamy: 0.2,
  happy: 0.12,
  hopeful: 0.1,
};

/** How strongly each emotion pushes toward tears (sorrow, or being moved). */
const TEARS: Partial<Record<EmotionName, number>> = {
  sad: 1,
  lonely: 0.9,
  melancholic: 0.75,
  nostalgic: 0.45,
  anxious: 0.3,
  scared: 0.35,
  frustrated: 0.2,
  grateful: 0.45,
  relieved: 0.35,
  love: 0.3,
};
/** Below this (weight × intensity) nothing wells up. */
const TEAR_THRESHOLD = 0.45;
/** Laughing until it brings tears only happens near the top of the scale. */
const LAUGH_TEAR_FROM = 0.82;
/** Load decay (1/s): sets both how fast tears build and how slowly they dry. */
const TEAR_DECAY = 0.08;
const WATERY_RANGE: [number, number] = [0.15, 1.2];
const TEAR_RANGE: [number, number] = [1.2, 3.2];

/** Pupil size: > 0 dilates, < 0 constricts. */
const PUPIL: Partial<Record<EmotionName, number>> = {
  love: 0.6,
  scared: 0.7,
  excited: 0.5,
  surprised: 0.5,
  curious: 0.45,
  dreamy: 0.3,
  hopeful: 0.25,
  happy: 0.2,
  thinking: 0.15,
  angry: -0.5,
  disgusted: -0.5,
  frustrated: -0.3,
  bored: -0.2,
};

const BLUSH_RISE_S = 1.6;
const BLUSH_FALL_S = 9;
const PUPIL_WIDEN_S = 0.9;
const PUPIL_NARROW_S = 0.45;

export const PHYSIOLOGY_MORPHS = [
  "FaceRed",
  "EyeWatery",
  "Tear",
  "EyeDilationLeft",
  "EyeDilationRight",
  "EyeConstrictLeft",
  "EyeConstrictRight",
] as const;

function smoothstep(lo: number, hi: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - lo) / (hi - lo)));
  return t * t * (3 - 2 * t);
}

/** Exponential approach with separate rise and fall time constants. */
function approach(current: number, target: number, dt: number, riseS: number, fallS: number): number {
  const tau = target > current ? riseS : fallS;
  return current + (target - current) * (1 - Math.exp(-dt / tau));
}

export interface PhysiologyState {
  blush: number;
  watery: number;
  tear: number;
  pupil: number;
}

/** Pure core, testable without a VRM: advance the state by dt. */
export function stepPhysiology(
  state: PhysiologyState & { load: number },
  emotion: EmotionName,
  intensity: number,
  dt: number
): void {
  const i = Math.max(0, Math.min(1, intensity));

  const blushTarget = (BLUSH[emotion] ?? 0) * smoothstep(0.2, 0.9, i);
  state.blush = approach(state.blush, blushTarget, dt, BLUSH_RISE_S, BLUSH_FALL_S);

  let drive = Math.max(0, (TEARS[emotion] ?? 0) * i - TEAR_THRESHOLD);
  if (emotion === "amused" || emotion === "playful") {
    drive = Math.max(drive, (i - LAUGH_TEAR_FROM) * 2.5);
  }
  state.load = Math.max(0, state.load + (drive - TEAR_DECAY * state.load) * dt);
  state.watery = smoothstep(WATERY_RANGE[0], WATERY_RANGE[1], state.load);
  state.tear = smoothstep(TEAR_RANGE[0], TEAR_RANGE[1], state.load) * 0.9;

  const pupilTarget = (PUPIL[emotion] ?? 0) * i;
  state.pupil = approach(
    state.pupil,
    pupilTarget,
    dt,
    pupilTarget > state.pupil ? PUPIL_WIDEN_S : PUPIL_NARROW_S,
    pupilTarget > state.pupil ? PUPIL_WIDEN_S : PUPIL_NARROW_S
  );
}

export class FacePhysiology {
  private vrm: VRM | null = null;
  private available = new Set<string>();
  readonly state = { blush: 0, watery: 0, tear: 0, pupil: 0, load: 0 };
  private emotion: EmotionName = "neutral";
  private intensity = 0;

  setVRM(vrm: VRM): void {
    this.vrm = vrm;
    this.available = registerRawMorphs(vrm, PHYSIOLOGY_MORPHS);
  }

  setEmotion(emotion: EmotionName, intensity: number): void {
    this.emotion = emotion;
    this.intensity = intensity;
  }

  update(dt: number): void {
    stepPhysiology(this.state, this.emotion, this.intensity, dt);
    const manager = this.vrm?.expressionManager;
    if (!manager) return;
    const set = (morph: string, v: number) => {
      if (this.available.has(morph)) manager.setValue(rawName(morph), Math.max(0, Math.min(1, v)));
    };
    const s = this.state;
    set("FaceRed", s.blush);
    set("EyeWatery", s.watery * 0.8);
    set("Tear", s.tear);
    const dilate = Math.max(0, s.pupil);
    const narrow = Math.max(0, -s.pupil);
    set("EyeDilationLeft", dilate * 0.6);
    set("EyeDilationRight", dilate * 0.6);
    set("EyeConstrictLeft", narrow * 0.6);
    set("EyeConstrictRight", narrow * 0.6);
  }
}
