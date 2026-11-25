/**
 * Ce qu'un niveau de partage ouvre (ADR 0188), le même pour une boîte de Mail et un compte Teams : la sienne, s'en
 * servir, préparer, lire. Pur.
 */

export interface Caps {
  /** La sienne : la régler, décider des brouillons de Mika. */
  own: boolean;
  /** « Préremplir avec Mika » (ses brouillons attendent alors l'accord du propriétaire). */
  prepare: boolean;
  /** Écrire, répondre, transférer, ranger. */
  write: boolean;
  /** Décider de ses brouillons : le propriétaire seulement. */
  decide: boolean;
}

/** Ce qu'un niveau ouvre : la sienne, tout ; `servir`, comme elle sauf décider ; `preparer`, préremplir ; `lire`, lire. */
export function caps(level: string): Caps {
  const own = level === "proprietaire";
  const write = own || level === "servir";
  return { own, write, prepare: write || level === "preparer", decide: own };
}

/** L'étiquette courte d'un partage (« lecture »…) ; vide pour la sienne. */
export function levelTag(level: string): string {
  return ({ lire: "lecture", preparer: "préparer", servir: "s'en servir" } as Record<string, string>)[level] ?? "";
}
