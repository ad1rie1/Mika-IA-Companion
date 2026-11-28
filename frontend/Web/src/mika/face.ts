/**
 * Son visage en avatar rond (la pastille quand la VRM est en grand, son nom sur un téléphone, ses bulles du
 * chat, la carte « Ce qu'elle fait ») : le portrait de son humeur, centré d'après le manifeste.
 */
import { h } from "../shell/dom";
import { avatarBase, avatarFrame, portraitOf, type PortraitManifest } from "./portraits";

let manifest: PortraitManifest | null = null;
let currentKey = "neutral";

export function setManifest(m: PortraitManifest | null): void {
  manifest = m;
}

export function getManifest(): PortraitManifest | null {
  return manifest;
}

export function availablePortraits(): ReadonlySet<string> | null {
  return manifest ? new Set(Object.keys(manifest.portraits)) : null;
}

/** L'humeur que montrent ses avatars (le coin la règle à chaque changement). */
export function setCurrentPortrait(key: string): void {
  currentKey = key;
}

export function currentPortrait(): string {
  return currentKey;
}

export function portraitUrl(file: string): string {
  return `${avatarBase()}${encodeURIComponent(file)}`;
}

export type AvatarSize = "xs" | "sm" | "lg" | "xl";
export type Presence = "on" | "away" | "busy";

/** `<span class="av sm mika">` avec son visage ; sans portraits, le rond garde sa couleur. */
export function mikaAvatar(size?: AvatarSize, presence?: Presence, key: string = currentKey): string {
  const cls = `av${size ? ` ${size}` : ""} mika`;
  const pres = presence ? `<i class="pres ${presence}"></i>` : "";
  const p = portraitOf(manifest, key);
  const img =
    p && manifest
      ? `<img src="${h(portraitUrl(p.file))}" alt="" draggable="false" style="${avatarFrame(p, manifest)}">`
      : "";
  return `<span class="${cls}" title="Mika">${img}${pres}</span>`;
}
