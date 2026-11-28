/**
 * Les personnes, dans Mail, Teams, Contacts et l'Agenda : leur rond (ses initiales, ou la photo de son profil Teams),
 * leur prénom, le nom qu'on montre, des adresses lues dans un en-tête ou tapées. Sans DOM : tout se teste.
 */
import { h, hue, initials } from "../shell/dom";
import type { Person } from "../api/mail";
import { teamsPhotoUrl } from "../api/teams";

/** Le prénom : « Adrien Moreau » → « Adrien ». */
export function firstName(full: string): string {
  return String(full || "").trim().split(/\s+/)[0] ?? "";
}

/** Un rond d'initiales, d'une teinte stable : `<span class="av sm c3">CD</span>`. Avec `photo` (l'adresse que l'API
 *  donne d'une photo de profil Teams, ADR 0300 : `teamsPhotoUrl`), la photo par-dessus ; ses initiales restent dessous,
 *  le temps qu'elle arrive, ou si elle ne vient pas. */
export function avatar(name: string, size = "", key = name, photo = ""): string {
  const label = String(name || key || "?");
  const src = teamsPhotoUrl(photo);
  const img = src ? `<img src="${h(src)}" alt="" loading="lazy" decoding="async">` : "";
  return `<span class="av${size ? ` ${size}` : ""} c${hue(key || label)}${src ? " photo" : ""}" title="${h(label)}">${h(initials(label.replace(/[^\p{L}\p{N}\s._-]/gu, "")) || "?")}${img}</span>`;
}

/** Le nom à montrer d'une personne : son nom, sinon son adresse. */
export function personName(p: Person): string {
  return p.name || p.address;
}

/** Les destinataires d'un en-tête : « A <a@x>, "B, C" <b@x>, c@x » ; une entrée sans @ est écartée. */
export function parseAddresses(field: string): Person[] {
  const out: Person[] = [];
  let part = "";
  let quoted = false;
  let angle = false;
  const flush = () => {
    const raw = part.trim();
    part = "";
    if (!raw) return;
    const m = /^(.*?)<([^<>]+)>\s*$/.exec(raw);
    const address = (m ? m[2] : raw).trim();
    if (!address.includes("@")) return;
    let name = m ? m[1].trim() : "";
    if (name.startsWith('"') && name.endsWith('"') && name.length >= 2) name = name.slice(1, -1).replace(/\\(.)/g, "$1");
    out.push({ name, address: address.toLowerCase() });
  };
  for (let i = 0; i < field.length; i++) {
    const c = field[i];
    if (c === "\\" && quoted) {
      part += c + (field[i + 1] ?? "");
      i++;
      continue;
    }
    if (c === '"') quoted = !quoted;
    else if (c === "<" && !quoted) angle = true;
    else if (c === ">" && !quoted) angle = false;
    if ((c === "," || c === ";") && !quoted && !angle) flush();
    else part += c;
  }
  flush();
  return out;
}
