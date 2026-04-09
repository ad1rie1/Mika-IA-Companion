import { VRM } from "@pixiv/three-vrm";

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

  // Audio-driven state
  private analyser: AnalyserNode | null = null;
  private dataArray: Uint8Array<ArrayBuffer> | null = null;
  private isAudioDriven = false;

  // Text-driven fallback state
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

  /** Start audio-driven lip sync with a Web Audio analyser node */
  startAudioDriven(analyser: AnalyserNode) {
    this.analyser = analyser;
    this.dataArray = new Uint8Array(analyser.frequencyBinCount);
    this.isAudioDriven = true;
    this.isTextDriven = false;
    this.speaking = true;
  }

  /** Start text-driven lip sync (fallback when no audio stream available) */
  startTextDriven(text: string, durationMs: number) {
    this.phonemeFrames = this.textToPhonemes(text, durationMs);
    this.frameIndex = 0;
    this.frameTimer = 0;
    this.isTextDriven = true;
    this.isAudioDriven = false;
    this.speaking = true;
  }

  stop() {
    this.speaking = false;
    this.isAudioDriven = false;
    this.isTextDriven = false;
    this.analyser = null;
    this.dataArray = null;
    this.phonemeFrames = [];
  }

  update(delta: number) {
    if (!this.vrm?.expressionManager) return;

    let targetAa = 0;
    let targetIh = 0;
    let targetOu = 0;
    let targetEe = 0;

    if (this.speaking) {
      if (this.isAudioDriven && this.analyser && this.dataArray) {
        // Audio-driven: analyze frequency data for mouth shapes
        this.analyser.getByteFrequencyData(this.dataArray);
        const result = this.analyzeFrequencies(this.dataArray);
        targetAa = result.aa;
        targetIh = result.ih;
        targetOu = result.ou;
        targetEe = result.ee;
      } else if (this.isTextDriven && this.phonemeFrames.length > 0) {
        // Text-driven fallback
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

  /** Analyze frequency bins to map to mouth shapes */
  private analyzeFrequencies(data: Uint8Array<ArrayBuffer>): Record<MouthShape, number> {
    const len = data.length;

    // Split frequency range into bands
    const lowEnd = Math.floor(len * 0.1);
    const midLow = Math.floor(len * 0.25);
    const midHigh = Math.floor(len * 0.5);

    let lowEnergy = 0;
    let midEnergy = 0;
    let highEnergy = 0;

    for (let i = 0; i < lowEnd; i++) lowEnergy += data[i];
    for (let i = lowEnd; i < midLow; i++) midEnergy += data[i];
    for (let i = midLow; i < midHigh; i++) highEnergy += data[i];

    lowEnergy /= lowEnd * 255;
    midEnergy /= (midLow - lowEnd) * 255;
    highEnergy /= (midHigh - midLow) * 255;

    return {
      aa: Math.min(1, lowEnergy * 2.5),
      ou: Math.min(1, lowEnergy * 1.5),
      ih: Math.min(1, midEnergy * 2.0),
      ee: Math.min(1, highEnergy * 2.0),
    };
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
