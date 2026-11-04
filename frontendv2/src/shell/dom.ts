/** Les petites aides du cadre, comme celles de la maquette (`M.h`, `M.on`, `M.norm`…). */

/** Échappe tout ce qu'un navigateur lirait comme du HTML : tout texte venu d'ailleurs passe par là. */
export function h(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c] ?? c);
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function $<T extends Element = HTMLElement>(sel: string, root: ParentNode = document): T | null {
  return root.querySelector<T>(sel);
}

export function $$<T extends Element = HTMLElement>(sel: string, root: ParentNode = document): T[] {
  return Array.from(root.querySelectorAll<T>(sel));
}

/** Sans accents ni casse : ce que la palette compare. */
export function norm(text: string): string {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/** Un écouteur délégué : `fn` reçoit l'élément de `root` qui correspond à `sel`. */
export function on<E extends Event = Event>(
  root: Element | Document,
  sel: string,
  type: string,
  fn: (event: E, target: HTMLElement) => void,
): void {
  root.addEventListener(type, (event) => {
    const target = (event.target as Element | null)?.closest?.(sel) as HTMLElement | null;
    if (target && root.contains(target)) fn(event as E, target);
  });
}

/** Les initiales d'un nom : « Adrien Moreau » → « AM ». */
export function initials(name: string): string {
  const words = String(name || "")
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2);
  return words.map((w) => w[0].toUpperCase()).join("") || "?";
}

/** Une teinte d'avatar stable (0 à 7) pour un nom. */
export function hue(name: string): number {
  let x = 0;
  for (const ch of String(name)) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
  return x % 8;
}

export const MOBILE_QUERY = "(max-width: 760px)";

export function isMobile(): boolean {
  return matchMedia(MOBILE_QUERY).matches;
}
