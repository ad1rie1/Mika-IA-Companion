import type { EmotionName } from "../vtuber/EmotionController";

const EMOTION_LABELS: Record<EmotionName, string> = {
  neutral: "Neutre",
  // Positive
  happy: "Contente",
  excited: "Excitee !",
  love: "Amoureuse",
  proud: "Fiere",
  grateful: "Reconnaissante",
  playful: "Joueuse",
  amused: "Amusee",
  hopeful: "Pleine d'espoir",
  relieved: "Soulagee",
  // Negative
  sad: "Triste",
  angry: "En colere",
  scared: "Effrayee",
  disgusted: "Degoutee",
  frustrated: "Frustree",
  lonely: "Seule",
  anxious: "Anxieuse",
  bored: "S'ennuie...",
  jealous: "Jalouse",
  // Complex
  surprised: "Surprise !",
  thinking: "Reflechit...",
  confused: "Confuse",
  embarrassed: "Genee",
  nostalgic: "Nostalgique",
  dreamy: "Reveuse",
  determined: "Determinee",
  mischievous: "Malicieuse",
  curious: "Curieuse",
  melancholic: "Melancolique",
};

export class EmotionDisplay {
  private el: HTMLElement;

  constructor() {
    this.el = document.getElementById("emotion-display")!;
  }

  setEmotion(emotion: EmotionName, intensity?: number) {
    const label = EMOTION_LABELS[emotion] || emotion;
    if (intensity !== undefined && intensity < 1.0) {
      const pct = Math.round(intensity * 100);
      this.el.textContent = `${label} (${pct}%)`;
    } else {
      this.el.textContent = label;
    }
  }
}
