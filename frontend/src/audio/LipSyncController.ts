import { VRM } from "@pixiv/three-vrm";
import type { SpeechPlanSegment } from "../types";

// Cadence par défaut de l'estimation texte, en ms par caractère prononcé.
export const DEFAULT_MS_PER_CHAR = 60;

/**
 * La cadence suit le débit réel de l'énoncé (multiplicateur d'émotion ×
 * persona, celui que TTSService applique à `utterance.rate`). À 60 ms/car
 * fixes, une réponse excitée (débit 1,15) laissait la bouche bouger après
 * la fin de la voix, et une réponse blasée (0,8) la fermait alors qu'il
 * restait un cinquième de l'audio.
 */
export function msPerCharForRate(rate: number): number {
  const r =
    Number.isFinite(rate) && rate > 0 ? Math.max(0.5, Math.min(2, rate)) : 1;
  return DEFAULT_MS_PER_CHAR / r;
}

// VRM blend shapes used for mouth: aa (open), ih (half), ou (round), ee (wide)
type MouthShape = "aa" | "ih" | "ou" | "ee";

interface PhonemeFrame {
  shape: MouthShape;
  weight: number;
  duration: number; // ms
  /** Index, dans le texte complet de la réponse, du caractère que cette
   * frame articule ; −1 pour un silence ou un plan sans position. */
  charOffset: number;
}

const collapsedLength = (text: string) => text.replace(/\s+/g, " ").length;

export class LipSyncController {
  private vrm: VRM | null = null;

  // Estimation texte : la Web Speech API ne donne aucun accès à son flux
  // audio, la bouche est donc pilotée depuis le texte prononcé — recalée
  // par `seekToChar` à chaque frontière de mot que la synthèse annonce.
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
    const msPerChar = durationMs / Math.max(1, collapsedLength(text));
    this.beginFrames(this.textToPhonemes(text, msPerChar, -1));
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
        frames.push({ shape: "aa", weight: 0, duration: segment.ms, charOffset: -1 });
      } else {
        frames.push(...this.textToPhonemes(segment.text, msPerChar, segment.start ?? -1));
      }
    }
    this.beginFrames(frames);
  }

  /**
   * Recale le curseur sur le caractère que la synthèse est en train de
   * prononcer — `utterance.onstart` (le son commence vraiment, pas la mise
   * en file) et `onboundary` (chaque mot, là où le navigateur le donne).
   * L'estimation continue de courir entre deux recalages ; elle ne peut
   * plus dériver de toute la latence de synthèse ni finir avant la voix.
   * Renvoie false si le plan n'a aucune frame voisée.
   */
  seekToChar(charIndex: number): boolean {
    const frames = this.phonemeFrames;
    if (frames.length === 0) return false;
    let target = -1;
    for (let i = 0; i < frames.length; i++) {
      const offset = frames[i].charOffset;
      if (offset < 0) continue;
      if (offset >= charIndex) {
        target = i;
        break;
      }
    }
    if (target < 0) {
      // Au-delà du dernier caractère voisé (ponctuation finale) : se poser
      // sur la dernière frame voisée plutôt que de ne rien faire.
      for (let i = frames.length - 1; i >= 0; i--) {
        if (frames[i].charOffset >= 0) {
          target = i;
          break;
        }
      }
      if (target < 0) return false;
    }
    this.frameIndex = target;
    this.frameTimer = 0;
    this.isTextDriven = true;
    this.speaking = true;
    return true;
  }

  /** Caractère de la frame courante (−1 hors plan) — tests et debug. */
  get currentCharOffset(): number {
    const frame = this.phonemeFrames[this.frameIndex];
    return frame ? frame.charOffset : -1;
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

  /**
   * Convert French text to approximate phoneme frames for lip sync. Les
   * blancs consécutifs se replient en une seule frame courte, mais chaque
   * frame garde l'index d'ORIGINE de son caractère : c'est lui que les
   * frontières de mot de la synthèse désignent.
   */
  private textToPhonemes(
    text: string,
    msPerChar: number,
    start: number
  ): PhonemeFrame[] {
    const frames: PhonemeFrame[] = [];
    let inSpace = false;

    for (let i = 0; i < text.length; i++) {
      const lower = text[i].toLowerCase();
      const charOffset = start >= 0 ? start + i : -1;

      if (/\s/.test(lower)) {
        if (inSpace) continue;
        inSpace = true;
        // Brief pause on spaces
        frames.push({ shape: "aa", weight: 0.02, duration: msPerChar * 0.5, charOffset });
        continue;
      }
      inSpace = false;

      if (/[aoàâô]/.test(lower)) {
        frames.push({ shape: "aa", weight: 0.7 + Math.random() * 0.3, duration: msPerChar, charOffset });
      } else if (/[eéèêë]/.test(lower)) {
        frames.push({ shape: "ee", weight: 0.5 + Math.random() * 0.3, duration: msPerChar, charOffset });
      } else if (/[iïî]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.5 + Math.random() * 0.3, duration: msPerChar, charOffset });
      } else if (/[uùûüoy]/.test(lower)) {
        frames.push({ shape: "ou", weight: 0.6 + Math.random() * 0.3, duration: msPerChar, charOffset });
      } else if (/[mbp]/.test(lower)) {
        // Bilabial — mouth closes briefly
        frames.push({ shape: "aa", weight: 0.05, duration: msPerChar, charOffset });
      } else if (/[fv]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.3, duration: msPerChar, charOffset });
      } else if (/[sz]/.test(lower)) {
        frames.push({ shape: "ee", weight: 0.35, duration: msPerChar, charOffset });
      } else if (/[td]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.25, duration: msPerChar, charOffset });
      } else if (/[kg]/.test(lower)) {
        frames.push({ shape: "aa", weight: 0.3, duration: msPerChar, charOffset });
      } else if (/[lr]/.test(lower)) {
        frames.push({ shape: "ih", weight: 0.2, duration: msPerChar, charOffset });
      } else {
        // Other consonants or punctuation
        frames.push({ shape: "aa", weight: 0.15, duration: msPerChar, charOffset });
      }
    }

    return frames;
  }

  isSpeaking(): boolean {
    return this.speaking;
  }
}
