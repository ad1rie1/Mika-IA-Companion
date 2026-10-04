// Single source of truth for the 29 emotions, matching backend
// emotion/types.py::Emotion. Never re-declare EmotionName elsewhere.
export const EMOTION_NAMES = [
  "neutral",
  // Positive
  "happy",
  "excited",
  "love",
  "proud",
  "grateful",
  "playful",
  "amused",
  "hopeful",
  "relieved",
  // Negative
  "sad",
  "angry",
  "scared",
  "disgusted",
  "frustrated",
  "lonely",
  "anxious",
  "bored",
  "jealous",
  // Complex
  "surprised",
  "thinking",
  "confused",
  "embarrassed",
  "nostalgic",
  "dreamy",
  "determined",
  "mischievous",
  "curious",
  "melancholic",
] as const;

export type EmotionName = (typeof EMOTION_NAMES)[number];

const EMOTION_SET: ReadonlySet<string> = new Set(EMOTION_NAMES);

export function isEmotionName(value: unknown): value is EmotionName {
  return typeof value === "string" && EMOTION_SET.has(value);
}

export type EmotionCategory = "neutral" | "positive" | "negative" | "complex";

export interface EmotionMeta {
  label: string;
  emoji: string;
  category: EmotionCategory;
}

/**
 * Libellés d'affichage des 29 émotions — pendant frontend de
 * ``GestionSysteme/formatting.py::EMOTION_FR``.
 *
 * Le nom stocké reste l'anglais : c'est la valeur de ``emotion/types.py``,
 * celle que le modèle produit dans sa balise ``[EMOTION:...]`` et celle qui
 * circule sur le WebSocket. Elle ne peut donc pas être traduite à la source,
 * seulement au rendu — et à un seul endroit, ici, sinon chaque nouvelle vue
 * refait le choix au hasard. Le type ``Record<EmotionName, …>`` garantit que
 * la table couvre exactement les 29 valeurs.
 */
export const EMOTION_META: Record<EmotionName, EmotionMeta> = {
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

/**
 * ``curious`` → ``Curieuse``. Un nom hors des 29 est rendu tel quel.
 *
 * Comme ``formatting.emotion_fr`` côté backend, un nom inconnu n'est **pas**
 * replié sur ``neutral`` : afficher la valeur brute dit « cette émotion n'est
 * pas dans la liste » plutôt que de mentir. La chaîne renvoyée peut donc venir
 * du serveur telle quelle — les appelants qui composent du HTML l'échappent.
 */
export function emotionFr(name: string): string {
  const key = (name || "").trim().toLowerCase();
  return isEmotionName(key) ? EMOTION_META[key].label : name;
}
