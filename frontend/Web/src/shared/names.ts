/**
 * Les noms que plusieurs écrans écrivent de la même façon : « de Léa », « d'Adrien ». Pur, sans DOM.
 */

/** « de Léa », « d'Adrien », « d'Hélène », « d'Œdipe » : le nom rogné ; l'élision devant une voyelle ou un h (accents
 *  ignorés) et devant les ligatures « œ » et « æ », majuscules comprises ; vide pour un nom vide. */
export function ofName(name: string): string {
  const n = String(name || "").trim();
  if (!n) return "";
  // NFD sépare les accents de leur lettre, pas les ligatures : « œ » et « æ » se nomment à part
  return /^[aeiouyhœæ]/iu.test(n.normalize("NFD").replace(/\p{M}/gu, "")) ? `d'${n}` : `de ${n}`;
}
