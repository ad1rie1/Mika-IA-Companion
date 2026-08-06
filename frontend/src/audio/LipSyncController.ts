import { VRM } from "@pixiv/three-vrm";
import type { SpeechPlanSegment } from "../types";

// Cadence par défaut de l'estimation texte, en ms par caractère prononcé.
const DEFAULT_MS_PER_CHAR = 60;

// Vowel patterns for French text-based lip sync fallback
const VOWELS = /[aeiouyàâéèêëïîôùûüœæ]/gi;
const OPEN_VOWELS = /[aoàâôœ]/gi;
const CLOSED_VOWELS = /[iuyïîüû]/gi;

// VRM blend shapes used for mouth: aa (open), ih (half), ou (round), ee (wide)
type MouthShape = "aa" | "ih" | "ou" | "ee";

interface PhonemeFrame {
  shape: MouthShape;
  weight: number;
  duration: number; // ms
}

export class LipSyncController {
  private vrm: VRM | null = null;

  // Estimation texte : la Web Speech API ne donne aucun accès à son flux
  // audio, la bouche est donc pilotée depuis le texte prononcé.
  private phonemeFrames: PhonemeFrame[] = [];
  private frameIndex = 0;
  private frameTimer = 0;
  private isTextDriven = false;

  // Smooth output
  private currentMouth: Record<MouthShape, number> = {
    aa: 0,
    ih: 0,
    ou: 0,
    ee: 0,
  };
  private smoothSpeed = 12.0;

  private speaking = false;

  setVRM(vrm: VRM) {
    this.vrm = vrm;
  }

  /** Start text-driven lip sync (the only path: no audio stream is available) */
  startTextDriven(text: string, durationMs: number) {
    this.beginFrames(this.textToPhonemes(text, durationMs));
  }

  /**
   * Idem, mais à partir du découpage que le TTS va réellement jouer
   * (TTSService.lipSyncPlan) : chaque silence réservé par un token de
   * prosodie devient une frame bouche fermée de sa durée exacte, et seuls
   * les caractères prononcés se voient attribuer du temps de parole.
   */
  startFromPlan(plan: SpeechPlanSegment[], msPerChar = DEFAULT_MS_PER_CHAR) {
    const frames: PhonemeFrame[] = [];
    for (const segment of plan) {
      if (segment.type === "silence") {
        frames.push({ shape: "aa", weight: 0, duration: segment.ms });
      } else {
        frames.push(
          ...this.textToPhonemes(segment.text, segment.text.length * msPerChar)
        );
      }
    }
    this.beginFrames(frames);
  }

  private beginFrames(frames: PhonemeFrame[]) {
    this.phonemeFrames = frames;
    this.frameIndex = 0;
    this.frameTimer = 0;
    this.isTextDriven = true;
    this.speaking = true;
  }

  stop() {
    this.speaking = false;
    this.isTextDriven = false;
    this.phonemeFrames = [];
  }

  update(delta: number) {
    if (!this.vrm?.expressionManager) return;

    let targetAa = 0;
    let targetIh = 0;
    let targetOu = 0;
    let targetEe = 0;

    if (this.speaking) {
      if (this.isTextDriven && this.phonemeFrames.length > 0) {
        // Text-driven estimation
        this.frameTimer += delta * 1000;
        while (
          this.frameIndex < this.phonemeFrames.length &&
          this.frameTimer >= this.phonemeFrames[this.frameIndex].duration
        ) {
          this.frameTimer -= this.phonemeFrames[this.frameIndex].duration;
          this.frameIndex++;
        }

        if (this.frameIndex < this.phonemeFrames.length) {
          const frame = this.phonemeFrames[this.frameIndex];
          if (frame.shape === "aa") targetAa = frame.weight;
          else if (frame.shape === "ih") targetIh = frame.weight;
          else if (frame.shape === "ou") targetOu = frame.weight;
          else if (frame.shape === "ee") targetEe = frame.weight;
        } else {
          this.speaking = false;
        }
      }
    }

    // Smooth lerp to targets
    const lerpFactor = Math.min(1, delta * this.smoothSpeed);
    this.currentMouth.aa += (targetAa - this.currentMouth.aa) * lerpFactor;
    this.currentMouth.ih += (targetIh - this.currentMouth.ih) * lerpFactor;
    this.currentMouth.ou += (targetOu - this.currentMouth.ou) * lerpFactor;
    this.currentMouth.ee += (targetEe - this.currentMouth.ee) * lerpFactor;

    // Apply to VRM — use "aa" as main mouth open, blend others
    const mouthOpen =
      this.currentMouth.aa * 0.5 +
      this.currentMouth.ih * 0.3 +
      this.currentMouth.ou * 0.4 +
      this.currentMouth.ee * 0.2;

    this.vrm.expressionManager.setValue("aa", Math.min(1, mouthOpen));
    this.vrm.expressionManager.setValue("oh", Math.min(1, this.currentMouth.ou * 0.5));
    this.vrm.expressionManager.setValue("ih", Math.min(1, this.currentMouth.ih * 0.3));
    this.vrm.expressionManager.setValue("ee", Math.min(1, this.currentMouth.ee * 0.3));
  }

  /** Convert French text to approximate phoneme frames for lip sync */
  private textToPhonemes(text: string, totalDurationMs: number): PhonemeFrame[] {
    const frames: PhonemeFrame[] = [];
    const chars = text.replace(/\s+/g, " ").split("");
    if (chars.length === 0) return frames;

    const msPerChar = totalDurationMs / chars.length;

    for (const char of chars) {
      const lower = char.toLowerCase();

      if (/[aoàâô]/.test(lower)) {
        frames.push({ shape: "aa", weight: 0.7 + Math.random() * 0.3, duration: msPerChar });
      } else if (/[eéèêë]/.test(lower)) {
        frames.push({ shape: "ee", weight: 0.5 + Math.random() * 0.3, duration: msPerChar });
      } else if (/[iïî]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.5 + Math.random() * 0.3, duration: msPerChar });
      } else if (/[uùûüoy]/.test(lower)) {
        frames.push({ shape: "ou", weight: 0.6 + Math.random() * 0.3, duration: msPerChar });
      } else if (/[mbp]/.test(lower)) {
        // Bilabial — mouth closes briefly
        frames.push({ shape: "aa", weight: 0.05, duration: msPerChar });
      } else if (/[fv]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.3, duration: msPerChar });
      } else if (/[sz]/.test(lower)) {
        frames.push({ shape: "ee", weight: 0.35, duration: msPerChar });
      } else if (/[td]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.25, duration: msPerChar });
      } else if (/[kg]/.test(lower)) {
        frames.push({ shape: "aa", weight: 0.3, duration: msPerChar });
      } else if (/[lr]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.2, duration: msPerChar });
      } else if (lower === " ") {
        // Brief pause on spaces
        frames.push({ shape: "aa", weight: 0.02, duration: msPerChar * 0.5 });
      } else {
        // Other consonants or punctuation
        frames.push({ shape: "aa", weight: 0.15, duration: msPerChar });
      }
    }

    return frames;
  }

  isSpeaking(): boolean {
    return this.speaking;
  }
}
