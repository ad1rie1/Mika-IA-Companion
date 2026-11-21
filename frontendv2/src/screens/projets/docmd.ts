/**
 * Le rendu d'une page de documentation, en lecture (pur) : titres, listes imbriquées, cases à cocher, liens, images,
 * code, citations, tableaux — le Markdown de la maquette (`maquette/ecrans/projets2-doc.js`, `PJ2.md`).
 *
 * Une page est écrite par des personnes, par Mika et par des outils : **rien de ce qu'elle contient ne s'exécute ni
 * ne fait charger une ressource d'ailleurs.** Tout le texte est échappé avant d'être mis en forme (une balise écrite
 * dans la page s'affiche telle quelle) ; une image n'est chargée que si elle est de l'espace de documentation du
 * projet (`images/<nom>`, résolue par `image` vers l'API) — toute autre adresse se dit, sans être chargée ; un lien
 * ne s'ouvre que vers une autre page de l'espace (`link`) ou vers une adresse http(s), dans un nouvel onglet, sans
 * référent. Aucun attribut ne reçoit de texte non échappé.
 */
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";

export interface Heading {
  level: number;
  text: string;
  id: string;
}

export interface MdOptions {
  /** L'adresse d'une image de l'espace, par son nom ; `null` : elle n'y est pas. Sans résolveur : aucune image. */
  image?: (name: string) => string | null;
  /** La route d'un lien vers une autre page de l'espace ; `null` : sans cible. */
  link?: (href: string) => string | null;
  /** S'il est donné, reçoit les titres de la page (le sommaire) ; chacun reçoit un identifiant. */
  headings?: Heading[];
  /** Le préfixe des identifiants de titres. */
  idPrefix?: string;
}

const SPACE_IMAGE = /^(?:\.\/)?images\/([A-Za-z0-9][A-Za-z0-9._-]*)$/;

/** Le nom d'une image de l'espace, depuis l'adresse qu'une page écrit (`images/<nom>`) ; vide : elle vient d'ailleurs. */
export function spaceImage(src: string): string {
  return SPACE_IMAGE.exec(src.trim())?.[1] ?? "";
}

/** Une ligne de texte : code, images, liens, gras, italique, barré. Chaque morceau fabriqué est mis de côté pendant
 *  que le reste se met en forme : rien ne s'écrit dans une balise déjà posée. */
function inline(source: string, o: MdOptions): string {
  const kept: string[] = [];
  const keep = (html: string): string => {
    kept.push(html);
    return `\u0001${kept.length - 1}\u0001`;
  };
  // les caractères de contrôle d'une page ne sont pas ceux de ce rendu
  let x = source.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
  x = x.replace(/`([^`]+)`/g, (_m, code: string) => keep(`<code>${h(code)}</code>`));
  x = x.replace(/\\([\\*_{}[\]()#+\-.!|<>~])/g, (_m, c: string) => keep(h(c)));
  x = h(x);
  x = x.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;(.*?)&quot;)?\)/g, (_m, alt: string, src: string, caption: string | undefined) => {
    const said = caption || (/^[\d.]+$/.test(alt) ? "" : alt);
    const name = spaceImage(plain(src));
    const url = name && o.image ? o.image(name) : null;
    if (url) return keep(`<img src="${h(url)}" alt="${said}" title="${said}" loading="lazy" referrerpolicy="no-referrer">`);
    return keep(`<span class="p2-md-noimg">${ico("image", "sm")}${name ? "image introuvable" : "image d'ailleurs, non chargée"} : ${src}</span>`);
  });
  x = x.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;.*?&quot;)?\)/g, (_m, text: string, href: string) => {
    const raw = plain(href);
    if (/^https?:\/\//i.test(raw)) return `${keep(`<a href="${href}" target="_blank" rel="noopener noreferrer">`)}${text}${keep("</a>")}`;
    const to = o.link ? o.link(raw) : null;
    return to ? `${keep(`<a href="${h(to)}">`)}${text}${keep("</a>")}` : `${keep(`<span class="p2-md-nolink" title="Lien sans cible : ${href}">`)}${text}${keep("</span>")}`;
  });
  x = x
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^\w])_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>");
  // les morceaux mis de côté reviennent ; un morceau peut en contenir un autre (du code dans le texte d'un lien)
  for (let pass = 0; pass < 3 && x.includes("\u0001"); pass += 1) x = x.replace(/\u0001(\d+)\u0001/g, (_m, i: string) => kept[Number(i)] ?? "");
  return x.replace(/\u0001/g, "");
}

/** Le texte d'avant `h` : pour juger une adresse, jamais pour l'écrire. */
function plain(text: string): string {
  return text.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

const cells = (line: string): string[] => line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;

/** Une liste et ses sous-listes : un élément plus en retrait que le premier ouvre une liste dans l'élément d'avant. */
function list(lines: string[], start: number, o: MdOptions, depth: number): [html: string, next: number] {
  const first = ITEM.exec(lines[start]) as RegExpExecArray;
  const base = first[1].length;
  const ordered = /\d/.test(first[2]);
  const items: { text: string; sub: string }[] = [];
  let i = start;
  while (i < lines.length) {
    const m = ITEM.exec(lines[i]);
    if (!m) {
      if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
        items[items.length - 1].text += ` ${lines[i].trim()}`;
        i += 1;
        continue;
      }
      const next = lines[i + 1] !== undefined ? ITEM.exec(lines[i + 1]) : null;
      if (!lines[i].trim() && next && next[1].length >= base && items.length) {
        i += 1;
        continue;
      }
      break;
    }
    if (m[1].length < base) break;
    if (m[1].length > base + 1 && items.length && depth < 8) {
      const [sub, next] = list(lines, i, o, depth + 1);
      items[items.length - 1].sub += sub;
      i = next;
      continue;
    }
    if (/\d/.test(m[2]) !== ordered) break;
    items.push({ text: m[3], sub: "" });
    i += 1;
  }
  const html = items
    .map(({ text, sub }) => {
      const task = /^\[( |x|X)\]\s+(.*)$/.exec(text);
      return task ? `<li class="tache${task[1] === " " ? "" : " faite"}"><i>${task[1] === " " ? "" : ico("check", "xs")}</i><span>${inline(task[2], o)}${sub}</span></li>` : `<li>${inline(text, o)}${sub}</li>`;
    })
    .join("");
  const tag = ordered ? "ol" : "ul";
  return [`<${tag}>${html}</${tag}>`, i];
}

const isBlock = (line: string): boolean => /^(#{1,4}\s|```|>|\||\s*([-*+]|\d+[.)])\s)/.test(line);

function blocks(source: string, o: MdOptions, depth: number): string {
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const buf: string[] = [];
      const lang = line.slice(3).trim();
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i += 1;
      out.push(`<pre${lang ? ` data-lang="${h(lang)}"` : ""}><code>${h(buf.join("\n"))}</code></pre>`);
      continue;
    }
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const title = /^(#{1,4})\s+(.*)$/.exec(line);
    if (title) {
      const level = title[1].length;
      const id = o.headings ? `${o.idPrefix ?? "p2-t"}${o.headings.length}` : "";
      o.headings?.push({ level, text: title[2].replace(/[`*_\\]/g, ""), id });
      out.push(`<h${level}${id ? ` id="${h(id)}"` : ""}>${inline(title[2], o)}</h${level}>`);
      i += 1;
      continue;
    }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push("<hr>");
      i += 1;
      continue;
    }
    if (/^>/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^>/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${depth < 6 ? blocks(buf.join("\n"), o, depth + 1) : h(buf.join(" "))}</blockquote>`);
      continue;
    }
    if (/^\|.*\|\s*$/.test(line) && /^\|?\s*:?-{2,}/.test(lines[i + 1] ?? "")) {
      const head = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && /^\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<div class="p2-md-table"><table><thead><tr>${head.map((c) => `<th>${inline(c, o)}</th>`).join("")}</tr></thead><tbody>${rows
        .map((r) => `<tr>${r.map((c) => `<td>${inline(c, o)}</td>`).join("")}</tr>`)
        .join("")}</tbody></table></div>`);
      continue;
    }
    if (ITEM.test(line)) {
      const [html, next] = list(lines, i, o, 0);
      out.push(html);
      i = next;
      continue;
    }
    const buf = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlock(lines[i])) buf.push(lines[i++]);
    out.push(`<p>${inline(buf.join(" ").replace(/\\$/, ""), o)}</p>`);
  }
  return out.join("");
}

/** Le HTML d'une page : sûr à poser tel quel (voir l'en-tête de ce module). */
export function pageHtml(source: string, o: MdOptions = {}): string {
  return blocks(source, o, 0);
}

/** Les titres d'un Markdown, hors de ses blocs de code : le sommaire pendant qu'on écrit. */
export function headingsOf(source: string): { level: number; text: string }[] {
  let fenced = false;
  const out: { level: number; text: string }[] = [];
  for (const line of String(source ?? "").split("\n")) {
    if (/^```/.test(line)) fenced = !fenced;
    const m = fenced ? null : /^(#{1,4})\s+(.*)$/.exec(line);
    if (m) out.push({ level: m[1].length, text: m[2].replace(/[`*_\\]/g, "") });
  }
  return out;
}
