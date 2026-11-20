/**
 * Carte : ce que disent les sources d'un lieu ou d'un événement, et comment on les cite (ADR 0259 ;
 * `protocole-moi.md` § 10, « Ce qu'un client montre avec ») — sans DOM ni réseau. Une note Google en étoiles et en
 * chiffres, une photo (toujours servie par ce serveur, refaite depuis sa référence), un lien vers le dehors (http ou
 * https seulement, ouvert à côté sans dire d'où l'on vient), un numéro à appeler, un texte en paragraphes, une date de
 * lecture en mots, la ligne de couverture d'une liste. Tout texte venu du dehors (un avis, un nom, une description, un
 * crédit) passe par `h()`.
 */
import { photoUrl, type Coverage, type Photo } from "../../api/carte";
import { h } from "../../shell/dom";
import { dateWords, daysBetween } from "../../shared/kit";

// ── Les liens vers le dehors ─────────────────────────────────────────

/** Un nom de domaine sans protocole (« magmatic.fr », « www.lille.fr/agenda ») : OpenStreetMap en a. */
const BARE_DOMAIN = /^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#].*)?$/i;

/**
 * Une adresse du dehors qu'on peut lier : http ou https seulement — ni `javascript:`, ni `data:`, ni un chemin de ce
 * serveur. Un domaine sans protocole (un site d'OpenStreetMap) devient https. Sinon : vide, et le texte reste du texte.
 */
export function safeHref(url: string | null | undefined): string {
  let text = String(url ?? "").trim();
  if (!text || /\s/.test(text)) return "";
  if (!/^[a-z][a-z0-9+.-]*:/i.test(text)) {
    if (!BARE_DOMAIN.test(text)) return "";
    text = `https://${text}`;
  }
  try {
    const u = new URL(text);
    return (u.protocol === "http:" || u.protocol === "https:") && u.hostname ? u.href : "";
  } catch {
    return "";
  }
}

/** Un lien vers le dehors (un nouvel onglet, sans référent) ; sans adresse sûre : le texte seul, échappé. */
export function outLink(url: string | null | undefined, text: string, cls = ""): string {
  const href = safeHref(url);
  if (!href) return h(text);
  return `<a${cls ? ` class="${cls}"` : ""} href="${h(href)}" target="_blank" rel="noopener noreferrer nofollow">${h(text)}</a>`;
}

/** Un numéro à appeler : `tel:` de ses chiffres (le « + » du début gardé), sinon vide. */
export function telHref(phone: string | null | undefined): string {
  const text = String(phone ?? "").trim();
  const digits = text.replace(/[^\d]/g, "");
  if (digits.length < 3 || digits.length > 20) return "";
  return `tel:${text.startsWith("+") ? "+" : ""}${digits}`;
}

/** Le site d'un lieu en court, pour un bouton ou une ligne : « magmatic.fr ». */
export function siteLabel(url: string): string {
  const href = safeHref(url);
  if (!href) return "";
  return new URL(href).hostname.replace(/^www\./, "");
}

// ── Les textes ───────────────────────────────────────────────────────

/** Un texte en paragraphes (un avis, une description) : une ligne, un paragraphe ; tout échappé. */
export function paragraphs(text: string | null | undefined, cls = ""): string {
  return String(text ?? "")
    .split(/\n+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => `<p${cls ? ` class="${cls}"` : ""}>${h(p)}</p>`)
    .join("");
}

// ── Les notes ────────────────────────────────────────────────────────

/** Une note sur 5, à la française : « 4,8 », « 4 ». */
export function ratingWords(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "";
  return (Math.round(n * 10) / 10).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
}

/** Un nombre, ses milliers séparés d'un espace insécable (comme `map/words.ts::km`) : « 15 235 ». */
export function grouped(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, "\u00a0");
}

/** « 15 235 avis », « 1 avis ». */
export function countWords(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "";
  return `${grouped(n)} avis`;
}

/** Des étoiles (pleines, à moitié, vides) : un dessin, et sa note pour un lecteur d'écran. */
export function stars(n: number | null | undefined, size = ""): string {
  if (typeof n !== "number" || !Number.isFinite(n)) return "";
  const v = Math.max(0, Math.min(5, n));
  const marks = [1, 2, 3, 4, 5].map((i) => `<i class="${v >= i - 0.25 ? "on" : v >= i - 0.75 ? "half" : ""}"></i>`).join("");
  return `<span class="stars${size ? ` ${size}` : ""}" role="img" aria-label="${h(`${ratingWords(v)} sur 5`)}">${marks}</span>`;
}

/** La note d'une ligne de liste : « ★ 4,8 (15 235) ». */
export function ratingInline(rating: number | null | undefined, count: number | null | undefined): string {
  if (typeof rating !== "number" || !Number.isFinite(rating)) return "";
  const n = typeof count === "number" && count >= 0 ? ` <span class="muted">(${h(grouped(count))})</span>` : "";
  return `<span class="g-mini">${stars(rating, "xs")} ${h(ratingWords(rating))}${n}</span>`;
}

// ── Les dates de lecture ─────────────────────────────────────────────

function clockOf(ms: number): string {
  return new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

/** Quand une source a été lue : « aujourd'hui à 22:00 », « hier à 09:10 », « le 18 novembre ». */
export function readWhen(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const days = daysBetween(ms, now);
  if (days <= 0) return `aujourd'hui à ${clockOf(ms)}`;
  if (days === 1) return `hier à ${clockOf(ms)}`;
  return `le ${dateWords(ms, now)}`;
}

/** « 16 novembre » d'une date `AAAA-MM-JJ` (l'extrait d'OpenStreetMap) ; illisible : vide. */
export function isoWords(iso: string, now: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "";
  return dateWords(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12).getTime(), now);
}

/**
 * La ligne de couverture d'une liste : sa `note` quand elle en a une (telle quelle : « pas encore toutes lues… »,
 * « lue en partie… »), sinon quand la source a été lue (`what` : « Notes Google Maps lues »). Rien de prêt : vide.
 */
export function coverageLine(c: Coverage | null | undefined, what: string, now: number): string {
  if (!c) return "";
  if (c.note.trim()) return c.note.trim();
  if (!c.ready || !(c.oldest > 0)) return "";
  return `${what} ${readWhen(c.oldest, now)}`;
}

// ── Les photos ───────────────────────────────────────────────────────

const SOURCE_LABELS: Record<string, string> = { google: "Google Maps", datatourisme: "Office de tourisme" };

/** D'où vient une photo, en mots : « Google Maps », « Office de tourisme ». */
export function photoSource(p: Pick<Photo, "source">): string {
  return SOURCE_LABELS[p.source] ?? "Photo";
}

/**
 * Une image d'une photo relayée : son adresse refaite depuis sa référence (jamais une autre), posée tout de suite si
 * elle s'est déjà montrée (`seen` : le navigateur la garde), sinon en attente (`data-src`) qu'elle paraisse —
 * `photos.ts` la charge alors : une photo de Google coûte un appel compté la première fois. Une référence fausse : rien.
 */
export function photoImg(ref: string, alt: string, seen: (ref: string) => boolean, cls = ""): string {
  const url = photoUrl(ref);
  if (!url) return "";
  const where = seen(ref) ? `src="${h(url)}"` : `data-src="${h(url)}"`;
  return `<img${cls ? ` class="${cls}"` : ""} ${where} data-ref="${h(ref)}" alt="${h(alt)}" decoding="async" referrerpolicy="no-referrer">`;
}

/** Ce qu'on cite d'une photo : son auteur (lié), sa licence (une photo de l'office de tourisme), d'où elle vient. */
export function photoCredit(p: Photo): string {
  const who = p.credit.trim() ? `Photo : ${outLink(p.credit_url, p.credit.trim())}` : "";
  return [who, p.licence.trim() ? h(p.licence.trim()) : "", h(photoSource(p))].filter(Boolean).join(" · ");
}

/** Les photos qu'on peut montrer (une référence de ce serveur), dans l'ordre : l'office de tourisme, puis Google. */
export function shownPhotos(...lists: ReadonlyArray<readonly Photo[] | null | undefined>): Photo[] {
  const out: Photo[] = [];
  const known = new Set<string>();
  for (const list of lists) {
    for (const p of list ?? []) {
      if (!p || !photoUrl(p.ref) || known.has(p.ref)) continue;
      known.add(p.ref);
      out.push(p);
    }
  }
  return out;
}
