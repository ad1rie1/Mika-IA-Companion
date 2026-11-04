/**
 * Ses portraits pré-rendus d'Android (ADR 0065), lus là où ils sont : `frontend/Android/app/src/main/assets/
 * avatar/`, servi sous `/ext/avatar/` (ou `VITE_MIKA_AVATAR_URL`). Le manifeste dit, pour chaque humeur, le
 * centre du visage (une fraction de l'image) et le rectangle du clignement. Pur, sauf `loadManifest`.
 *
 * Le cadrage est celui de la maquette (`coin.cadrer` et `M.av` de maquette.js) : le visage seul dans un rond,
 * ou le buste dans une carte, le visage à 36 % de la hauteur, le clignement posé pile sur les yeux.
 */

export interface Blink {
  file: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Portrait {
  file: string;
  /** Le centre du visage, en fraction de la largeur et de la hauteur. */
  face: [number, number];
  blink: Blink | null;
}

export interface PortraitManifest {
  width: number;
  height: number;
  portraits: Record<string, Portrait>;
}

const FILE = /^[\w.-]+\.webp$/;

function fraction(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1 ? v : null;
}

function pixels(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v < 100_000 ? v : null;
}

/** Le manifeste validé, ou `null`. Une entrée illisible est écartée seule ; un clignement illisible, aussi. */
export function parseManifest(raw: unknown): PortraitManifest | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const width = pixels(r.width);
  const height = pixels(r.height);
  if (!width || !height || !r.portraits || typeof r.portraits !== "object") return null;
  const portraits: Record<string, Portrait> = {};
  for (const [key, value] of Object.entries(r.portraits as Record<string, unknown>)) {
    if (!/^[a-z_]+$/.test(key) || !value || typeof value !== "object") continue;
    const p = value as Record<string, unknown>;
    const file = typeof p.file === "string" && FILE.test(p.file) ? p.file : null;
    const face = Array.isArray(p.face) ? [fraction(p.face[0]), fraction(p.face[1])] : [null, null];
    if (!file || face[0] === null || face[1] === null) continue;
    let blink: Blink | null = null;
    const b = p.blink as Record<string, unknown> | undefined;
    if (b && typeof b === "object" && typeof b.file === "string" && FILE.test(b.file)) {
      const [x, y, w, h] = [pixels(b.x), pixels(b.y), pixels(b.w), pixels(b.h)];
      if (x !== null && y !== null && w && h) blink = { file: b.file, x, y, w, h };
    }
    portraits[key] = { file, face: [face[0], face[1]], blink };
  }
  return Object.keys(portraits).length ? { width, height, portraits } : null;
}

/** Le portrait d'une humeur, sinon le neutre, sinon rien. */
export function portraitOf(manifest: PortraitManifest | null, key: string): Portrait | null {
  if (!manifest) return null;
  return manifest.portraits[key] ?? manifest.portraits.neutral ?? null;
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Le portrait dans sa scène, en pixels : `mini`, son visage seul dans le rond de la pastille (l'image à
 * 5,4 fois la hauteur, le visage au centre) ; sinon son buste (2,05 fois, le visage à 36 % de la hauteur).
 */
export function framePortrait(
  stage: { width: number; height: number },
  mini: boolean,
  portrait: Portrait,
  size: { width: number; height: number },
): { image: Box; blink: Box | null } {
  const H = stage.height;
  const imgH = mini ? H * 5.4 : H * 2.05;
  const s = imgH / size.height;
  const imgW = size.width * s;
  const left = stage.width / 2 - portrait.face[0] * imgW;
  const top = H * (mini ? 0.5 : 0.36) - portrait.face[1] * imgH;
  const b = portrait.blink;
  return {
    image: { left, top, width: imgW, height: imgH },
    blink: b ? { left: left + b.x * s, top: top + b.y * s, width: b.w * s, height: b.h * s } : null,
  };
}

/**
 * Son visage au centre d'un avatar rond (`M.av('mika')`) : l'image à 330 % de la largeur du rond, en
 * pourcentages, pour un style en ligne.
 */
export function avatarFrame(portrait: Portrait, size: { width: number; height: number }): string {
  const W = 330;
  const left = 50 - portrait.face[0] * W;
  const top = 50 - portrait.face[1] * W * (size.height / size.width);
  return `width:${W}%;left:${left.toFixed(1)}%;top:${top.toFixed(1)}%`;
}

/** Le dossier des portraits : `/ext/avatar/`, ou celui que la construction a reçu. */
export function avatarBase(): string {
  const env = import.meta.env.VITE_MIKA_AVATAR_URL;
  const base = typeof env === "string" && env.trim() ? env.trim() : "/ext/avatar/";
  return base.endsWith("/") ? base : `${base}/`;
}

export async function loadManifest(base: string = avatarBase()): Promise<PortraitManifest | null> {
  try {
    const resp = await fetch(`${base}manifest.json`);
    if (!resp.ok) return null;
    return parseManifest(await resp.json());
  } catch {
    // pas de portraits sur cette machine : son rond reste à sa couleur
    return null;
  }
}
