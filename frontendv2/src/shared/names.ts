/**
 * Les noms que plusieurs écrans écrivent de la même façon (Mail, Teams) : « de Léa », « d'Adrien ». Pur, sans DOM.
 */

/** « de Léa », « d'Adrien », « d'Hélène » : l'élision devant une voyelle ou un h muet (accents ignorés) ; vide pour
 *  un nom vide. */
export function ofName(name: string): string {
  const n = String(name || "").trim();
  if (!n) return "";
  const first = n.normalize("NFD").replace(/\p{M}/gu, "")[0]?.toLowerCase() ?? "";
  return "aeiouyh".includes(first) ? `d'${n}` : `de ${n}`;
}
