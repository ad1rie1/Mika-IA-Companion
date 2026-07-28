import type { EmotionName } from "../types";

type EmotionCategory = "neutral" | "positive" | "negative" | "complex";

const EMOTION_META: Record<
  EmotionName,
  { label: string; emoji: string; category: EmotionCategory }
> = {
  neutral: { label: "Neutre", emoji: "😐", category: "neutral" },
  // Positive
  happy: { label: "Contente", emoji: "😊", category: "positive" },
  excited: { label: "Excitée !", emoji: "🤩", category: "positive" },
  love: { label: "Amoureuse", emoji: "🥰", category: "positive" },
  proud: { label: "Fière", emoji: "😌", category: "positive" },
  grateful: { label: "Reconnaissante", emoji: "🙏", category: "positive" },
  playful: { label: "Joueuse", emoji: "😜", category: "positive" },
  amused: { label: "Amusée", emoji: "😄", category: "positive" },
  hopeful: { label: "Pleine d'espoir", emoji: "🌱", category: "positive" },
  relieved: { label: "Soulagée", emoji: "😮‍💨", category: "positive" },
  // Negative
  sad: { label: "Triste", emoji: "😢", category: "negative" },
  angry: { label: "En colère", emoji: "😠", category: "negative" },
  scared: { label: "Effrayée", emoji: "😨", category: "negative" },
  disgusted: { label: "Dégoûtée", emoji: "🤢", category: "negative" },
  frustrated: { label: "Frustrée", emoji: "😤", category: "negative" },
  lonely: { label: "Seule", emoji: "🌧️", category: "negative" },
  anxious: { label: "Anxieuse", emoji: "😰", category: "negative" },
  bored: { label: "S'ennuie...", emoji: "🥱", category: "negative" },
  jealous: { label: "Jalouse", emoji: "😒", category: "negative" },
  // Complex
  surprised: { label: "Surprise !", emoji: "😲", category: "complex" },
  thinking: { label: "Réfléchit...", emoji: "🤔", category: "complex" },
  confused: { label: "Confuse", emoji: "😵‍💫", category: "complex" },
  embarrassed: { label: "Gênée", emoji: "😳", category: "complex" },
  nostalgic: { label: "Nostalgique", emoji: "🍂", category: "complex" },
  dreamy: { label: "Rêveuse", emoji: "💭", category: "complex" },
  determined: { label: "Déterminée", emoji: "💪", category: "complex" },
  mischievous: { label: "Malicieuse", emoji: "😏", category: "complex" },
  curious: { label: "Curieuse", emoji: "🧐", category: "complex" },
  melancholic: { label: "Mélancolique", emoji: "🌫️", category: "complex" },
};

export class EmotionDisplay {
  private el: HTMLElement;

  constructor() {
    this.el = document.getElementById("emotion-display")!;
  }

  setEmotion(emotion: EmotionName, intensity?: number) {
    const meta = EMOTION_META[emotion] ?? EMOTION_META.neutral;
    let text = `${meta.emoji} ${meta.label}`;
    if (intensity !== undefined && intensity < 1.0) {
      text += ` (${Math.round(intensity * 100)}%)`;
    }
    this.el.textContent = text;
    this.el.dataset.category = meta.category;
  }
}
