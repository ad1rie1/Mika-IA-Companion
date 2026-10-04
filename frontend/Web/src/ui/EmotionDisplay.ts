import type { EmotionName } from "../types";
import { EMOTION_META, emotionFr } from "../types";

export class EmotionDisplay {
  private el: HTMLElement;

  constructor() {
    this.el = document.getElementById("emotion-display")!;
  }

  setEmotion(emotion: EmotionName, intensity?: number) {
    const meta = EMOTION_META[emotion] ?? EMOTION_META.neutral;
    let text = `${meta.emoji} ${emotionFr(emotion)}`;
    if (intensity !== undefined && intensity < 1.0) {
      text += ` (${Math.round(intensity * 100)}%)`;
    }
    this.el.textContent = text;
    this.el.dataset.category = meta.category;
  }
}
