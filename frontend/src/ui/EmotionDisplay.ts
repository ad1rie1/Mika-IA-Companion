import type { EmotionName } from "../vtuber/EmotionController";

const EMOTION_LABELS: Record<EmotionName, string> = {
  neutral: "Neutre",
  happy: "Contente",
  sad: "Triste",
  angry: "En colere",
  surprised: "Surprise !",
  thinking: "Reflechit...",
  love: "Amoureuse",
};

export class EmotionDisplay {
  private el: HTMLElement;

  constructor() {
    this.el = document.getElementById("emotion-display")!;
  }

  setEmotion(emotion: EmotionName) {
    this.el.textContent = EMOTION_LABELS[emotion] || emotion;
  }
}
