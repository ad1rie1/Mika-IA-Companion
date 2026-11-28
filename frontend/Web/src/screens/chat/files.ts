/**
 * Les fichiers du chat, en pur (ADR 0312) : la sorte d'un fichier (la règle du serveur, `app/me/chat.py::sorte_of`,
 * pour ce que le fil montre avant que le serveur ne l'ait classé), sa marque et son libellé, pourquoi il ne se
 * télécharge plus, et ce que la visionneuse lit de ses octets — un texte borné, un CSV en lignes, un PDF reconnu à son
 * en-tête ; et la tuile d'un fichier, en HTML. Rien ici ne touche au DOM ni au réseau.
 */
import type { FileReason, FileSort } from "../../api/chat";
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";

const TABLE_MIMES = new Set(["text/csv", "text/tab-separated-values"]);
const TABLE_EXTS = new Set(["csv", "tsv"]);
const TEXT_MIMES = new Set(["application/json", "application/xml", "application/x-yaml", "application/yaml"]);
const TEXT_EXTS = new Set(["txt", "md", "markdown", "log", "json", "yaml", "yml", "xml", "ini", "toml"]);
const MARKDOWN_EXTS = new Set(["md", "markdown"]);

/** L'extension d'un nom, en minuscules (`""` : aucune). */
export function extOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toLowerCase() : "";
}

function baseMime(mime: string | undefined): string {
  return (mime ?? "").split(";", 1)[0].trim().toLowerCase();
}

/** La sorte d'un fichier : par sa sorte gardée (`image`), sa sorte MIME, puis son extension. */
export function sortOf(name: string, mime?: string, kind?: string): FileSort {
  const base = baseMime(mime);
  const ext = extOf(name);
  if (kind === "image" || base.startsWith("image/")) return "image";
  if (base === "application/pdf" || ext === "pdf") return "pdf";
  if (TABLE_MIMES.has(base) || TABLE_EXTS.has(ext)) return "tableau";
  if (base.startsWith("text/") || TEXT_MIMES.has(base) || TEXT_EXTS.has(ext)) return "texte";
  return "autre";
}

/** Un texte qui se lit rendu (Markdown), plutôt qu'en source. */
export function isMarkdown(name: string, mime?: string): boolean {
  return baseMime(mime) === "text/markdown" || MARKDOWN_EXTS.has(extOf(name));
}

/** La marque d'une tuile : « PDF », « CSV », sinon l'extension (quatre lettres au plus), sinon rien. */
export function badgeOf(name: string, sorte: FileSort): string {
  if (sorte === "pdf") return "PDF";
  if (sorte === "tableau") return "CSV";
  return extOf(name).toUpperCase().slice(0, 4);
}

/** Ce qu'est un fichier, en mots courts : « image JPEG », « PDF », « Markdown », « texte », « fichier XLSX ». */
export function typeLabel(name: string, sorte: FileSort, mime?: string): string {
  const ext = extOf(name).toUpperCase();
  if (sorte === "image") return ext ? `image ${ext === "JPG" ? "JPEG" : ext}` : "image";
  if (sorte === "pdf") return "PDF";
  if (sorte === "tableau") return ext === "TSV" ? "TSV" : "CSV";
  if (sorte === "texte") return isMarkdown(name, mime) ? "Markdown" : ext === "JSON" ? "JSON" : "texte";
  if (baseMime(mime).startsWith("audio/")) return ext ? `son ${ext}` : "son";
  return ext ? `fichier ${ext}` : "fichier";
}

/**
 * Ce que le fil ne sait pas encore d'une pièce (son adresse) : la visionneuse la demande au serveur. Le serveur, lui,
 * ne le dit jamais.
 */
export const NOT_YET = "not-yet";

/** Pourquoi il ne se télécharge plus, en mots. */
export function reasonWords(reason: FileReason | string | undefined): string {
  switch (reason) {
    case "retention":
      return "trop vieux";
    case "budget":
      return "la place manquait";
    case "operator":
      return "retiré par une opératrice";
    case "missing":
      return "introuvable";
    case "unkept":
      return "pas gardé";
    case NOT_YET:
      return "pas encore arrivé";
    default:
      return "plus disponible";
  }
}

/** Ce que la visionneuse montre d'un texte, au plus (en caractères) : au-delà, il est coupé, et elle le dit. */
export const TEXT_MAX_CHARS = 400_000;
/** … et en lignes, avec leurs numéros. */
export const TEXT_MAX_LINES = 5_000;
/** Les lignes d'un CSV en tableau, au plus. */
export const CSV_MAX_ROWS = 500;

export interface TextPreview {
  text: string;
  lines: string[];
  truncated: boolean;
}

/** Un texte tel que la visionneuse le montre : décodé en UTF-8 (un octet illisible devient �), borné. */
export function textPreview(bytes: Uint8Array): TextPreview {
  const all = new TextDecoder("utf-8", { fatal: false }).decode(bytes).replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  let text = all.length > TEXT_MAX_CHARS ? all.slice(0, TEXT_MAX_CHARS) : all;
  let lines = text.split("\n");
  let truncated = text.length < all.length;
  if (lines.length > TEXT_MAX_LINES) {
    lines = lines.slice(0, TEXT_MAX_LINES);
    text = lines.join("\n");
    truncated = true;
  }
  return { text, lines, truncated };
}

export interface CsvTable {
  rows: string[][];
  /** Le séparateur lu : `;`, `,` ou une tabulation. */
  separator: string;
  columns: number;
  truncated: boolean;
}

/** Le séparateur d'un CSV : celui qui revient le plus dans sa première ligne (hors guillemets). */
export function csvSeparator(text: string): string {
  const first = text.split("\n", 1)[0] ?? "";
  let quoted = false;
  const seen: Record<string, number> = { ";": 0, ",": 0, "\t": 0 };
  for (const ch of first) {
    if (ch === '"') quoted = !quoted;
    else if (!quoted && ch in seen) seen[ch] += 1;
  }
  const best = (Object.entries(seen) as Array<[string, number]>).sort((a, b) => b[1] - a[1])[0];
  return best && best[1] > 0 ? best[0] : ",";
}

/** Un CSV en lignes (guillemets doublés, retours à la ligne entre guillemets), `CSV_MAX_ROWS` au plus. */
export function parseCsv(text: string, maxRows = CSV_MAX_ROWS): CsvTable {
  const separator = csvSeparator(text);
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let truncated = false;
  // une ligne vide ne fait pas de rangée
  const pushRow = (): void => {
    row.push(cell);
    cell = "";
    if (!(row.length === 1 && row[0] === "")) rows.push(row);
    row = [];
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === "") quoted = true;
    else if (ch === separator) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      pushRow();
      if (rows.length >= maxRows) {
        truncated = text.slice(i + 1).trim() !== "";
        break;
      }
    } else if (ch !== "\r") cell += ch;
  }
  if (rows.length < maxRows && (cell !== "" || row.length)) pushRow();
  const columns = rows.reduce((n, r) => Math.max(n, r.length), 0);
  return { rows, separator, columns, truncated };
}

/** Un PDF se reconnaît à son en-tête (`%PDF-`) : un fichier nommé « .pdf » qui n'en est pas un ne s'ouvre pas en PDF. */
export function looksLikePdf(bytes: Uint8Array): boolean {
  const head = [0x25, 0x50, 0x44, 0x46, 0x2d]; // %PDF-
  // l'en-tête peut suivre quelques octets (une marque d'ordre, un saut de ligne) : les 1 024 premiers, comme les lecteurs
  const limit = Math.min(bytes.length - head.length, 1024);
  for (let i = 0; i <= limit; i++) {
    if (head.every((b, j) => bytes[i + j] === b)) return true;
  }
  return false;
}

/** La clé de la copie que ce navigateur garde d'une pièce qu'on vient d'envoyer (son message, sa place). */
export function localKey(cid: string, index: number): string {
  return `local:${cid}:${index}`;
}

/** La tuile d'un fichier : sa vignette d'image (à lire par `blobs.ts`), sinon sa marque sur un carré de couleur. */
export function tile(f: { name: string; sorte: FileSort; src?: string; available: boolean }, size = ""): string {
  const cls = `fx-tile${size ? ` ${size}` : ""}`;
  if (f.sorte === "image" && f.src && f.available) {
    return `<span class="${cls} img" data-thumb><img data-file="${h(f.src)}" alt=""></span>`;
  }
  if (f.sorte === "image") return `<span class="${cls} k-image">${ico("image", "sm")}</span>`;
  const badge = badgeOf(f.name, f.sorte);
  return `<span class="${cls} k-${f.sorte}">${badge ? h(badge) : ico("file", "sm")}</span>`;
}
