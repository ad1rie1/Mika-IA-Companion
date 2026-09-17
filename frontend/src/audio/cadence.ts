// Cadence par défaut de l'estimation texte, en ms par caractère prononcé.
export const DEFAULT_MS_PER_CHAR = 60;

/**
 * La cadence suit le débit réel de l'énoncé (multiplicateur d'émotion ×
 * persona, celui que TTSService applique à `utterance.rate`). À 60 ms/car
 * fixes, une réponse excitée (débit 1,15) laissait la bouche bouger après
 * la fin de la voix, et une réponse blasée (0,8) la fermait alors qu'il
 * restait un cinquième de l'audio.
 *
 * Partagée entre le lip-sync (son estimation) et la file TTS (son échéance
 * par énoncé) : deux arithmétiques se seraient désynchronisées.
 */
export function msPerCharForRate(rate: number): number {
  const r =
    Number.isFinite(rate) && rate > 0 ? Math.max(0.5, Math.min(2, rate)) : 1;
  return DEFAULT_MS_PER_CHAR / r;
}
