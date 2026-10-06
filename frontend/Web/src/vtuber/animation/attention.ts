import type { EmotionName, SleepPhase, VoicePersona } from "../../types";
import type { GazeAngles } from "./gazeMath";

/**
 * Where Mika's attention is — the decision layer behind the eyes and the
 * head. Pure: no three.js, no DOM, an injectable random source, and time
 * only ever enters through `dt`, so every branch below is testable frame
 * by frame.
 *
 * The model is conversational gaze as the literature describes it (Kendon
 * 1967, Argyle & Cook 1976): a listener keeps her eyes on the speaker most
 * of the time; a speaker looks away at the START of an utterance (planning
 * what to say) and comes back toward the end; someone retrieving a thought
 * looks up and to the side, with brief check-ins; embarrassment, sadness
 * and anxiety avert downward, love and gratitude barely avert at all. And
 * a person murmuring to herself does not look at you.
 *
 * Every gaze *change* here is a step, never an ease: eye movements are
 * saccades — ballistic jumps followed by a fixation — and an eye that slides
 * to its target reads as drunk. The head, which really does move slowly,
 * eases in its own overlay. `shift` reports the size of the jump decided
 * this frame so the blink controller can do what eyelids do on a large
 * gaze shift (~a third of them carry a blink).
 *
 * Angles are semantic (`GazeAngles`): pitch > 0 down, yaw > 0 her left.
 */
export type AttentionState =
  | "contact" // eyes on the viewer
  | "avert" // a short look-away, then back
  | "wander" // alone with her thoughts: looking around the room
  | "walking" // crossing the room: eyes on the way, a glance now and then
  | "thinking" // a reply is being composed: absorbed, up-and-to-the-side
  | "absorbed" // busy in her room (drawing, looking outside): eyes on it
  | "inner" // murmuring to herself: not to you
  | "away" // the viewer is out of reach (behind her): forward gaze
  | "asleep";

export interface AttentionInput {
  speaking: boolean;
  /** A message was accepted and nothing answered it yet. */
  replyPending: boolean;
  /** The person in front of her is typing right now. */
  listening: boolean;
  persona?: VoicePersona;
  emotion: EmotionName;
  intensity: number;
  sleepPhase: SleepPhase;
  /** The viewer sits within what a head turn can reach (false = behind
   * her, or no camera at all). Gates the contact term only — a thought
   * still averts relative to her forward when nobody is in front. */
  reachable: boolean;
  /** Angular distance to the viewer (rad): sizes the jump when contact
   * toggles, for the blink coupling. */
  viewerAngle: number;
  /** Crossing the room: she looks where she goes. */
  walking?: boolean;
  /** What she is busy with in her room (activity.ts), null = nothing. */
  focus?: AttentionFocus | null;
}

/** Something she is doing (activity.ts): where her eyes rest on it, and
 * how much of the viewer is left in them. */
export interface AttentionFocus {
  gaze: GazeAngles;
  contact: number;
}

export interface GazeIntent {
  state: AttentionState;
  /** Share of the viewer direction in the eye target, 0…1. */
  contact: number;
  /** Added to the gaze — an aversion, a thinking pose, the inner murmur. */
  offset: GazeAngles;
  /** Current fixation jitter, stepped at saccade cadence. */
  saccade: GazeAngles;
  /** Saccadic jump decided THIS frame (rad); 0 when the eyes held still. */
  shift: number;
}

/** Per-emotion aversion tendency: `p` multiplies the baseline probability,
 * `dir` is the preferred direction (absent = a random human default). */
export interface AversionProfile {
  p: number;
  dir?: GazeAngles;
}

export const AVERSION_PROFILE: Partial<Record<EmotionName, AversionProfile>> = {
  // Shame and low mood avert DOWN — the strongest, most legible cue.
  embarrassed: { p: 2.2, dir: { pitch: 0.18, yaw: -0.16 } },
  anxious: { p: 1.8, dir: { pitch: 0.12, yaw: 0.14 } },
  scared: { p: 1.4, dir: { pitch: 0.1, yaw: 0.18 } },
  sad: { p: 1.6, dir: { pitch: 0.2, yaw: 0.0 } },
  lonely: { p: 1.6, dir: { pitch: 0.18, yaw: -0.05 } },
  melancholic: { p: 1.5, dir: { pitch: 0.16, yaw: -0.1 } },
  jealous: { p: 1.4, dir: { pitch: 0.06, yaw: -0.2 } },
  disgusted: { p: 1.2, dir: { pitch: 0.04, yaw: -0.18 } },
  // Retrieval and reverie go UP and to the side.
  thinking: { p: 1.8, dir: { pitch: -0.16, yaw: 0.18 } },
  confused: { p: 1.5, dir: { pitch: -0.1, yaw: -0.14 } },
  dreamy: { p: 1.5, dir: { pitch: -0.18, yaw: 0.04 } },
  nostalgic: { p: 1.4, dir: { pitch: -0.12, yaw: 0.12 } },
  hopeful: { p: 0.9, dir: { pitch: -0.12, yaw: 0.06 } },
  frustrated: { p: 1.1, dir: { pitch: -0.08, yaw: 0.16 } },
  bored: { p: 1.7, dir: { pitch: -0.04, yaw: 0.22 } },
  proud: { p: 0.7, dir: { pitch: -0.1, yaw: 0.1 } },
  // Held gaze: the attachment emotions, and the ones that stare.
  love: { p: 0.35 },
  grateful: { p: 0.5 },
  determined: { p: 0.4 },
  angry: { p: 0.6 },
  curious: { p: 0.8 },
  surprised: { p: 0.3 },
};

/** Saccades: smaller and rarer for a focused gaze, larger and busier for
 * an alarmed one. */
export const FOCUSED_EMOTIONS: ReadonlySet<EmotionName> = new Set<EmotionName>([
  "love", "grateful", "proud", "determined",
]);
export const RESTLESS_EMOTIONS: ReadonlySet<EmotionName> = new Set<EmotionName>([
  "scared", "anxious", "surprised", "excited",
]);

// ── Timings (seconds) and magnitudes (radians) ──────────────────────
export const AVERSION_INTERVAL: [number, number] = [3.5, 8];
export const AVERSION_DURATION: [number, number] = [0.7, 2.0];
export const AVERSION_P_IDLE = 0.4;
export const AVERSION_P_SPEAKING = 0.55;
export const AVERSION_P_LISTENING = 0.18;
/** Planning gaze at the start of an utterance. */
export const ONSET_AVERSION_P = 0.45;
export const ONSET_AVERSION_DURATION: [number, number] = [0.9, 1.6];
export const PLANNING_OFFSET: GazeAngles = { pitch: -0.12, yaw: 0.16 };
export const THINKING_CONTACT = 0.15;
export const THINKING_OFFSET: GazeAngles = { pitch: -0.14, yaw: 0.2 };
export const THINKING_CHECKIN_INTERVAL: [number, number] = [2.5, 5];
export const THINKING_CHECKIN_DURATION: [number, number] = [0.5, 0.9];
/** A reply that never comes stops being "thought about" after this. */
export const THINKING_MAX_S = 90;
export const INNER_CONTACT = 0.1;
export const INNER_OFFSET: GazeAngles = { pitch: 0.14, yaw: 0.12 };
export const SACCADE_INTERVAL: [number, number] = [1.8, 4.5];
/** In contact the eyes scan the face (eyes ↔ mouth, 1–4°); off the viewer
 * they wander wider. */
export const SACCADE_AMPLITUDE_CONTACT: [number, number] = [0.02, 0.07];
export const SACCADE_AMPLITUDE_FREE: [number, number] = [0.04, 0.1];

/**
 * Left alone, a person does not stare at the spot where someone was. After
 * a while with nobody speaking or typing, her attention drifts to the room
 * — the door, the bed, her hands, the floor, the light from the window, the
 * middle distance — in long looks, with glances back at the viewer between
 * them. Any sign of the person (typing, a message, her own reply) brings
 * the eyes straight back: being noticed is the point.
 */
export const WALKING_OFFSET: GazeAngles = { pitch: 0.16, yaw: 0 };
export const WANDER_AFTER_S = 25;
export const WANDER_P = 0.75;
export const WANDER_DURATION: [number, number] = [2.5, 7];
export const WANDER_INTERVAL: [number, number] = [2, 6];
/** Points of interest in her semantic gaze frame (pitch > 0 down, yaw > 0
 * her left), laid out after the room (Environment.ts). */
export const WANDER_POINTS: GazeAngles[] = [
  { pitch: 0.04, yaw: 0.55 }, // the door, front-left
  { pitch: 0.24, yaw: -0.5 }, // the bed, front-right
  { pitch: 0.34, yaw: 0.08 }, // the floor in front of her
  { pitch: 0.3, yaw: -0.14 }, // her hands
  { pitch: -0.12, yaw: -0.72 }, // the light from the window
  { pitch: -0.2, yaw: 0.32 }, // up and away — daydreaming
  { pitch: 0.02, yaw: -0.38 }, // the plant by the bed
];

/**
 * Busy with something (drawing, looking outside), she does not wander: her
 * eyes are on what she does. A sign of the person — typing, a message, her
 * own reply — interrupts her like anyone absorbed: she looks up at once,
 * and goes back to it this long after the exchange has gone quiet.
 */
export const ABSORBED_RETURN_S = 2.5;

const AVERSION_DIRS: GazeAngles[] = [
  { pitch: 0.14, yaw: 0.16 },
  { pitch: 0.14, yaw: -0.16 },
  { pitch: -0.12, yaw: 0.18 },
  { pitch: -0.12, yaw: -0.18 },
  { pitch: 0.02, yaw: 0.22 },
  { pitch: 0.02, yaw: -0.22 },
];

export class AttentionDirector {
  private readonly random: () => number;

  private state: AttentionState = "contact";
  private contact = 1;
  private readonly offset: GazeAngles = { pitch: 0, yaw: 0 };
  private readonly saccade: GazeAngles = { pitch: 0, yaw: 0 };

  private aversionTimer = 0;
  private nextAversionAt: number;
  private aversionRemaining = 0;

  private saccadeTimer = 0;
  private nextSaccadeAt: number;

  private thinkingElapsed = 0;
  private thinkingSide: 1 | -1 = 1;
  private checkinTimer = 0;
  private nextCheckinAt: number;
  private checkinRemaining = 0;

  private innerSide: 1 | -1 = 1;

  private wasSpeaking = false;
  private wasPending = false;
  /** Seconds with nobody to attend to (no speech, no typing, no reply). */
  private idleFor = 0;
  private wandering = false;

  /** Reused across frames — read it during the frame, never keep it. */
  private readonly out: GazeIntent = {
    state: "contact",
    contact: 1,
    offset: { pitch: 0, yaw: 0 },
    saccade: { pitch: 0, yaw: 0 },
    shift: 0,
  };

  constructor(random: () => number = Math.random) {
    this.random = random;
    this.nextAversionAt = this.sample(AVERSION_INTERVAL);
    this.nextSaccadeAt = this.sample(SACCADE_INTERVAL);
    this.nextCheckinAt = this.sample(THINKING_CHECKIN_INTERVAL);
  }

  get currentState(): AttentionState {
    return this.state;
  }

  update(dt: number, input: AttentionInput): GazeIntent {
    const prevContact = this.contact;
    const prevPitch = this.offset.pitch;
    const prevYaw = this.offset.yaw;

    const speakingStarted = input.speaking && !this.wasSpeaking;
    const pendingStarted = input.replyPending && !this.wasPending;
    this.wasSpeaking = input.speaking;
    this.wasPending = input.replyPending;

    if (input.sleepPhase !== "awake") {
      this.state = "asleep";
      this.contact = 0;
      this.offset.pitch = this.offset.yaw = 0;
      this.saccade.pitch = this.saccade.yaw = 0;
      this.aversionRemaining = 0;
      this.checkinRemaining = 0;
      this.thinkingElapsed = 0;
      return this.emit(0);
    }

    if (pendingStarted) {
      this.thinkingElapsed = 0;
      this.thinkingSide = this.random() < 0.5 ? -1 : 1;
      this.checkinTimer = 0;
      this.nextCheckinAt = this.sample(THINKING_CHECKIN_INTERVAL);
      this.checkinRemaining = 0;
    }
    this.thinkingElapsed = input.replyPending ? this.thinkingElapsed + dt : 0;
    const engaged = input.speaking || input.replyPending || input.listening;
    this.idleFor = engaged ? 0 : this.idleFor + dt;
    if (engaged && this.wandering) {
      // Someone is there again: the look-away ends now, not when it was
      // due to — and the next aversion is a normal conversational one.
      this.wandering = false;
      this.aversionRemaining = 0;
      this.offset.pitch = this.offset.yaw = 0;
      this.aversionTimer = 0;
      this.nextAversionAt = this.sample(AVERSION_INTERVAL);
    }

    // Absorbed in what she does once the exchange has gone quiet a moment —
    // it replaces wandering around the room, never a conversation.
    const focus =
      input.focus && !engaged && this.idleFor >= ABSORBED_RETURN_S ? input.focus : null;

    let mode: AttentionState;
    if (input.walking) {
      mode = "walking";
    } else if (input.persona === "inner" && input.speaking) {
      mode = "inner";
    } else if (
      input.replyPending &&
      !input.speaking &&
      this.thinkingElapsed <= THINKING_MAX_S
    ) {
      // A message pending while she is still voicing the previous reply
      // does not pull her gaze away: one finishes one's sentence first.
      mode = "thinking";
    } else if (focus) {
      mode = "absorbed";
    } else {
      mode = "contact";
    }

    if (mode === "walking") {
      // Eyes a few steps ahead on the floor; aversions make no sense here.
      this.aversionRemaining = 0;
      this.wandering = false;
      this.contact = input.speaking ? 0.35 : 0;
      this.offset.pitch = WALKING_OFFSET.pitch;
      this.offset.yaw = 0;
    } else if (mode === "inner") {
      if (this.state !== "inner") this.innerSide = this.random() < 0.5 ? -1 : 1;
      this.aversionRemaining = 0;
      this.contact = INNER_CONTACT;
      this.offset.pitch = INNER_OFFSET.pitch;
      this.offset.yaw = INNER_OFFSET.yaw * this.innerSide;
    } else if (mode === "thinking") {
      this.aversionRemaining = 0;
      if (this.checkinRemaining > 0) {
        // A glance back at you between two stretches of absorption.
        this.checkinRemaining -= dt;
        this.contact = 1;
        this.offset.pitch = this.offset.yaw = 0;
      } else {
        this.checkinTimer += dt;
        if (this.checkinTimer >= this.nextCheckinAt) {
          this.checkinTimer = 0;
          this.nextCheckinAt = this.sample(THINKING_CHECKIN_INTERVAL);
          this.checkinRemaining = this.sample(THINKING_CHECKIN_DURATION);
          this.contact = 1;
          this.offset.pitch = this.offset.yaw = 0;
        } else {
          this.contact = THINKING_CONTACT;
          this.offset.pitch = THINKING_OFFSET.pitch;
          this.offset.yaw = THINKING_OFFSET.yaw * this.thinkingSide;
        }
      }
    } else if (mode === "absorbed" && focus) {
      // Eyes on what she does, the viewer barely in them: no conversational
      // aversion, no look around the room.
      this.aversionRemaining = 0;
      this.wandering = false;
      this.contact = focus.contact;
      this.offset.pitch = focus.gaze.pitch;
      this.offset.yaw = focus.gaze.yaw;
    } else {
      if (this.state === "thinking" || this.state === "inner" || this.state === "absorbed") {
        // Coming back to you: restart the aversion clock so the return
        // is not immediately followed by a look-away.
        this.aversionTimer = 0;
        this.nextAversionAt = this.sample(AVERSION_INTERVAL);
      }
      if (
        speakingStarted &&
        this.aversionRemaining <= 0 &&
        this.random() < ONSET_AVERSION_P
      ) {
        // Planning gaze: the look-away that opens an utterance.
        this.aversionRemaining = this.sample(ONSET_AVERSION_DURATION);
        const side = this.random() < 0.5 ? -1 : 1;
        this.offset.pitch = PLANNING_OFFSET.pitch;
        this.offset.yaw = PLANNING_OFFSET.yaw * side;
      }
      const alone = this.idleFor >= WANDER_AFTER_S;
      if (this.aversionRemaining > 0) {
        this.aversionRemaining -= dt;
        if (this.aversionRemaining <= 0) {
          this.aversionRemaining = 0;
          this.wandering = false;
          this.offset.pitch = this.offset.yaw = 0;
          this.aversionTimer = 0;
          this.nextAversionAt = alone
            ? this.sample(WANDER_INTERVAL)
            : this.sample(AVERSION_INTERVAL) * this.intervalScale(input);
        }
      } else if (alone) {
        this.offset.pitch = this.offset.yaw = 0;
        this.aversionTimer += dt;
        if (this.aversionTimer >= this.nextAversionAt) {
          this.aversionTimer = 0;
          this.nextAversionAt = this.sample(WANDER_INTERVAL);
          if (this.random() < WANDER_P) {
            this.wandering = true;
            this.aversionRemaining = this.sample(WANDER_DURATION);
            const point =
              WANDER_POINTS[Math.min(WANDER_POINTS.length - 1, Math.floor(this.random() * WANDER_POINTS.length))];
            this.offset.pitch = point.pitch;
            this.offset.yaw = point.yaw;
          }
        }
      } else {
        this.offset.pitch = this.offset.yaw = 0;
        this.aversionTimer += dt;
        if (this.aversionTimer >= this.nextAversionAt) {
          this.aversionTimer = 0;
          this.nextAversionAt = this.sample(AVERSION_INTERVAL) * this.intervalScale(input);
          const profile = AVERSION_PROFILE[input.emotion];
          const p = this.baseAversionP(input) * (profile?.p ?? 1);
          if (this.random() < p) {
            this.aversionRemaining = this.sample(AVERSION_DURATION);
            const dir =
              profile?.dir ??
              AVERSION_DIRS[Math.min(AVERSION_DIRS.length - 1, Math.floor(this.random() * AVERSION_DIRS.length))];
            this.offset.pitch = dir.pitch;
            this.offset.yaw = dir.yaw;
          }
        }
      }
      // Wandering looks at the room itself (relative to her forward), not
      // at a point beside the viewer.
      this.contact = this.wandering ? 0 : 1;
      mode = this.wandering ? "wander" : this.aversionRemaining > 0 ? "avert" : "contact";
    }

    if (!input.reachable) {
      // Nobody in front of her that the head could turn to: the contact
      // term is meaningless. A thought or a murmur keeps its offset — those
      // are relative to her forward, not to a viewer.
      this.contact = 0;
      if (mode === "contact" || mode === "avert") mode = "away";
    }

    const saccadeJump = this.updateSaccade(dt, input, mode);
    this.state = mode;

    const offsetJump = Math.hypot(this.offset.pitch - prevPitch, this.offset.yaw - prevYaw);
    const contactJump =
      Math.abs(this.contact - prevContact) * Math.min(Math.abs(input.viewerAngle), 0.5);
    return this.emit(offsetJump + contactJump + saccadeJump);
  }

  private emit(shift: number): GazeIntent {
    const o = this.out;
    o.state = this.state;
    o.contact = this.contact;
    o.offset.pitch = this.offset.pitch;
    o.offset.yaw = this.offset.yaw;
    o.saccade.pitch = this.saccade.pitch;
    o.saccade.yaw = this.saccade.yaw;
    o.shift = shift;
    return o;
  }

  private baseAversionP(input: AttentionInput): number {
    if (input.listening) return AVERSION_P_LISTENING;
    if (input.speaking) return AVERSION_P_SPEAKING;
    return AVERSION_P_IDLE;
  }

  private intervalScale(input: AttentionInput): number {
    if (input.listening) return 1.8;
    if (input.speaking) return 0.8;
    return 1;
  }

  /** Returns the amplitude of the jump when a saccade fires, else 0. */
  private updateSaccade(dt: number, input: AttentionInput, mode: AttentionState): number {
    this.saccadeTimer += dt;
    if (this.saccadeTimer < this.nextSaccadeAt) return 0;
    this.saccadeTimer = 0;

    const focused = FOCUSED_EMOTIONS.has(input.emotion);
    const restless = RESTLESS_EMOTIONS.has(input.emotion);
    let amp = this.sample(
      mode === "contact" ? SACCADE_AMPLITUDE_CONTACT : SACCADE_AMPLITUDE_FREE
    );
    if (focused) amp *= 0.5;
    if (restless) amp *= 1.4;
    if (input.listening) amp *= 0.6;

    const angle = this.random() * Math.PI * 2;
    const pitch = Math.sin(angle) * amp;
    const yaw = Math.cos(angle) * amp;
    const jump = Math.hypot(pitch - this.saccade.pitch, yaw - this.saccade.yaw);
    this.saccade.pitch = pitch;
    this.saccade.yaw = yaw;

    let interval = this.sample(SACCADE_INTERVAL);
    if (focused) interval *= 1.4;
    if (restless) interval *= 0.55;
    if (input.listening) interval *= 1.5;
    this.nextSaccadeAt = interval;
    return jump;
  }

  private sample(range: [number, number]): number {
    return range[0] + this.random() * Math.max(0, range[1] - range[0]);
  }
}
