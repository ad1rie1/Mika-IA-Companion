/**
 * Carte : la fiche d'un lieu et celle d'un événement, leur bande de photos et la visionneuse — sans DOM ni réseau
 * (ADR 0259 ; `protocole-moi.md` § 10). La forme est celle de la maquette de l'app Android
 * (`frontend/Android/maquette/ecrans/carte-avis.js`), posée dans la colonne de gauche de l'écran Carte, la carte à
 * droite ; les notes et les avis viennent de Google Maps (pas de répartition ni de sous-notes : Google n'en donne pas).
 *
 * Chaque source se nomme là où elle parle, avec ce qu'il faut citer : « Google Maps » et son lien, l'auteur (lié) et la
 * date de chaque avis, le crédit de chaque photo ; « © les contributeurs d'OpenStreetMap » sous les infos pratiques ;
 * l'office de tourisme, son auteur, sa date et sa licence sous ce qu'il en dit. Tout texte venu du dehors passe par
 * `h()` ; un lien ne mène qu'en http ou https (`sources.ts`).
 */
import { PLACE_REF, type EventFiche, type EventItem, type Fact, type Photo, type Place, type PlaceFiche, type ReviewsPart } from "../../api/carte";
import { drawnScene } from "../../map/drawn";
import type { Scene } from "../../map/scene";
import { km, placeWhat } from "../../map/words";
import { h } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { failureText } from "../../shared/kit";
import {
  countWords,
  isoWords,
  outLink,
  paragraphs,
  photoCredit,
  photoImg,
  photoSource,
  ratingWords,
  readWhen,
  safeHref,
  shownPhotos,
  siteLabel,
  stars,
  telHref,
} from "./sources";

// ── Ce qui sert aux deux fiches ──────────────────────────────────────

/** Où revenir d'une fiche : la liste d'où elle s'est ouverte. */
export interface FicheBack {
  href: string;
  label: string;
}

function backLink(b: FicheBack): string {
  return `<div class="fiche-top"><a class="btn sm ghost" href="${h(b.href)}" data-fiche-back>${ico("chev-left", "sm")}${h(b.label)}</a></div>`;
}

/** Des faits d'une source, en lignes « libellé : valeur » (un lien quand la valeur est une adresse sûre ou un numéro). */
export function factRows(facts: readonly Fact[]): string {
  return facts
    .filter((f) => f && f.label?.trim() && f.value?.trim())
    .map((f) => `<dt>${h(f.label)}</dt><dd>${factValue(f)}</dd>`)
    .join("");
}

function factValue(f: Fact): string {
  const value = f.value.trim();
  if (/t[ée]l[ée]phone|portable|fax/i.test(f.label)) {
    const tel = telHref(value);
    return tel ? `<a href="${h(tel)}">${h(value)}</a>` : h(value);
  }
  if (/^https?:\/\//i.test(value)) return outLink(value, siteLabel(value) || value);
  return h(value);
}

/** La ligne d'une source, en petit, sous ce qu'elle dit. */
function sourceLine(parts: readonly string[]): string {
  const shown = parts.filter(Boolean);
  return shown.length ? `<p class="src-line">${ico("info", "xs")}<span>${shown.join(" · ")}</span></p>` : "";
}

/** La tuile du plan, en tête de la bande : le lieu et toi, dessinés ; un clic recadre la carte sur lui. */
function planTile(scene: Scene, title: string, dist: string): string {
  const plan = drawnScene(scene, { width: 200, height: 150, title, pad: 34 });
  return `<button class="ph ph-plan" type="button" data-plan title="Recadrer la carte sur ce lieu">${plan}<span class="ph-src">${ico("map", "xs")}Plan</span>${
    dist ? `<span class="ph-credit">${h(dist)}</span>` : ""}</button>`;
}

/**
 * La bande du haut d'une fiche : le plan d'abord, puis les photos (chacune avec sa source et son crédit, lié) ; une
 * photo touchée s'ouvre dans la visionneuse (`data-photo` : sa place dans `photos`). Sans photo, le plan seul. Les
 * photos se chargent quand elles paraissent dans la bande (`data-photo-scroll`, `photos.ts`).
 */
export function photoBand(o: { scene: Scene; title: string; dist: string; photos: readonly Photo[]; seen: (ref: string) => boolean }): string {
  const plan = planTile(o.scene, o.title, o.dist);
  if (!o.photos.length) return `<div class="ph-band solo">${plan}</div>`;
  const items = o.photos.map((p, i) => {
    const alt = p.caption.trim() || `Photo ${i + 1}${p.credit ? `, de ${p.credit}` : ""}`;
    return `<figure class="ph">
      <button class="ph-open" type="button" data-photo="${i}" aria-label="${h(`Voir en grand : ${alt}`)}">${photoImg(p.ref, alt, o.seen)}<span class="ph-fallback">${ico("image")}</span></button>
      <span class="ph-src ${h(p.source)}">${h(photoSource(p))}</span>
      ${p.credit.trim() ? `<figcaption class="ph-credit">${outLink(p.credit_url, p.credit.trim())}</figcaption>` : ""}</figure>`;
  }).join("");
  const count = `<span class="ph-count">${ico("image", "xs")}${o.photos.length} photo${o.photos.length > 1 ? "s" : ""}</span>`;
  return `<div class="ph-wrap"><div class="ph-band" data-photo-scroll>${plan}${items}</div>${count}</div>`;
}

/**
 * La visionneuse : une photo en grand, sa légende, son auteur (lié), sa licence et d'où elle vient, sa place dans la
 * série ; « précédente » et « suivante » (les flèches du clavier aussi).
 */
export function viewerMarkup(photos: readonly Photo[], index: number): string {
  if (!photos.length) return `<div class="empty">${ico("image")}<p>Aucune photo.</p></div>`;
  const i = ((index % photos.length) + photos.length) % photos.length;
  const p = photos[i];
  const alt = p.caption.trim() || `Photo ${i + 1}`;
  const nav = photos.length > 1
    ? `<button class="btn icon vw-prev" type="button" data-vw="-1" title="Photo précédente (←)" aria-label="Photo précédente">${ico("chev-left")}</button>
       <button class="btn icon vw-next" type="button" data-vw="1" title="Photo suivante (→)" aria-label="Photo suivante">${ico("chev-right")}</button>` : "";
  const why = p.source === "google"
    ? "Publiée sur Google Maps, gardée sur ce serveur le temps du cache."
    : "De l'office de tourisme, par DATAtourisme : son crédit et sa licence se montrent toujours.";
  return `<div class="viewer" data-viewer="${i}">
    <div class="vw-img">${photoImg(p.ref, alt, () => true)}${nav}</div>
    <div class="vw-meta">${p.caption.trim() ? `<p class="vw-caption">${h(p.caption.trim())}</p>` : ""}
      <p class="small">${photoCredit(p)}</p>
      <p class="small muted">${h(why)}${photos.length > 1 ? ` · ${i + 1} / ${photos.length}` : ""}</p></div></div>`;
}

// ── La fiche d'un lieu ───────────────────────────────────────────────

export interface PlaceFicheView {
  /** Sa ligne (celle de la liste en attendant la fiche, puis celle de la fiche). */
  place: Place | null;
  fiche: PlaceFiche | null;
  loading: boolean;
  /** Le refus de sa lecture (rien : lue, ou pas encore). */
  error: unknown;
  /** Il n'est plus là (404 : l'index a changé, ou ce lieu n'existe pas). */
  gone: boolean;
  /** « Actualiser » est en cours. */
  refreshing: boolean;
  /** Ce qui n'a pas pu se relire, en mots (un 503, un 429) ; vide : rien. */
  refreshNote: string;
  back: FicheBack;
  /** Mika te l'a proposé (un de ses regards). */
  mika: boolean;
  /** Ta position, si on la connaît (le plan la montre). */
  here: { lat: number; lon: number } | null;
  /** Les photos déjà montrées (le navigateur les garde : posées sans attendre). */
  seen: (ref: string) => boolean;
  now: number;
}

/** Ouvert ou fermé : son étiquette, à la couleur de ce qu'elle dit. */
function openTag(p: Place): string {
  if (!p.open_text?.trim()) return "";
  const cls = p.open_state === "open" ? "ok" : p.open_state === "closed" ? "danger" : "warn";
  return `<span class="tag ${cls}">${ico("clock", "xs")}${h(p.open_text.trim())}</span>`;
}

/** Les étiquettes d'un lieu : ouvert ou fermé, sa cuisine, son prix, sa note. */
export function placeTags(p: Place, r: ReviewsPart | null): string {
  const rating = r?.found && typeof r.rating === "number" ? r.rating : p.rating;
  const price = r?.found && r.price ? r.price : p.price;
  const tags = [
    openTag(p),
    p.cuisine?.trim() ? `<span class="tag">${h(p.cuisine.trim())}</span>` : "",
    price?.trim() ? `<span class="tag">${h(price.trim())}</span>` : "",
    typeof rating === "number" ? `<span class="tag g-tag">${stars(rating, "xs")}${h(ratingWords(rating))}</span>` : "",
  ].filter(Boolean);
  return tags.length ? `<div class="row wrap fiche-tags">${tags.join("")}</div>` : "";
}

/** Le numéro et le site d'un lieu : d'OpenStreetMap d'abord, sinon de l'office de tourisme. */
export function placeContacts(f: PlaceFiche | null): { phone: string; site: string } {
  const contacts = f?.tourism?.contacts ?? [];
  const phone = f?.osm?.phone?.trim() || contacts.find((c) => /t[ée]l[ée]phone/i.test(c.label))?.value.trim() || "";
  const site = safeHref(f?.osm?.website) || safeHref(contacts.find((c) => /site|web/i.test(c.label))?.value) || "";
  return { phone, site };
}

function placeActions(f: PlaceFiche | null): string {
  const { phone, site } = placeContacts(f);
  const tel = telHref(phone);
  return `<div class="row wrap fiche-acts">
      <button class="btn sm primary" type="button" data-go-route>${ico("map", "sm")}Itinéraire</button>
      <button class="btn sm" type="button" data-add-trip>${ico("plus", "sm")}Ajouter au voyage</button>
      ${tel ? `<a class="btn sm" href="${h(tel)}" title="${h(phone)}">${ico("phone", "sm")}Appeler</a>` : ""}
      ${site ? `<a class="btn sm" href="${h(site)}" target="_blank" rel="noopener noreferrer nofollow" title="${h(siteLabel(site))}">${ico("globe", "sm")}Site</a>` : ""}
      <button class="btn sm mika" type="button" data-ask-place>${ico("chat", "sm")}En parler à Mika</button></div>`;
}

function refreshButton(v: Pick<PlaceFicheView, "refreshing">, label = "Actualiser"): string {
  return `<button class="btn sm" type="button" data-refresh${v.refreshing ? " disabled" : ""} title="Relire tout de suite la fiche chez Google et à l'office de tourisme">${ico("refresh", "sm")}${h(v.refreshing ? "Actualisation…" : label)}</button>`;
}

function refreshSaid(v: Pick<PlaceFicheView, "refreshNote">): string {
  return v.refreshNote ? `<p class="small cs-warn fiche-warn" role="status">${ico("alert", "xs")}${h(v.refreshNote)}</p>` : "";
}

/**
 * Le bloc « Google Maps » : la note, le nombre d'avis, le prix et sa fourchette, le résumé, ce que Google ajoute à la
 * fiche, les avis (chacun avec son auteur, son lien et sa date en mots), « Voir sur Google Maps », la date du cache et
 * « Actualiser ». `found` faux : ce qu'en dit sa `note` (rien trouvé, ou pourquoi on n'a pas pu chercher).
 */
export function googleBlock(r: ReviewsPart, v: Pick<PlaceFicheView, "refreshing" | "refreshNote" | "now">): string {
  const label = r.source_label?.trim() || "Google Maps";
  const link = r.found ? outLink(r.url, "Voir sur Google Maps", "g-link") : "";
  const head = `<div class="g-head"><span class="g-logo">${h(label)}</span><span class="grow"></span>${link.startsWith("<a") ? link : ""}</div>`;
  const cached = r.cached > 0 ? `Lu ${readWhen(r.cached, v.now)} · gardé sur ce serveur` : "";
  const foot = `<div class="g-foot">${ico("history", "xs")}<span class="grow">${h(cached)}</span>${refreshButton(v)}</div>`;
  const note = r.note.trim() ? `<p class="small muted g-note">${h(r.note.trim())}</p>` : "";
  if (!r.found) {
    return `<section class="fiche-sec g-sec none" aria-label="${h(label)}">${head}
      <p class="small">${h(r.note.trim() || "Google n'a rien de ce lieu.")}</p>${foot}${refreshSaid(v)}</section>`;
  }
  const price = [r.price, r.price_range].map((x) => x?.trim()).filter(Boolean).join(" · ");
  const score = typeof r.rating === "number"
    ? `<div class="g-score"><b>${h(ratingWords(r.rating))}</b>${stars(r.rating)}${r.count !== null ? `<span class="muted">${h(countWords(r.count))}</span>` : ""}${
      price ? `<span class="tag">${h(price)}</span>` : ""}</div>`
    : price ? `<div class="g-score"><span class="tag">${h(price)}</span></div>` : "";
  const summary = r.summary.trim() ? `<p class="g-summary">${h(r.summary.trim())}</p>` : "";
  const facts = factRows(r.facts);
  const reviews = r.reviews.map((x) => {
    const who = x.author.trim() ? outLink(x.author_url, x.author.trim(), "g-author") : "Un visiteur";
    return `<article class="g-review"><div class="g-r-head">${stars(x.rating, "xs")}<span class="g-r-who">${who}</span>${
      x.relative.trim() ? `<span class="muted">· ${h(x.relative.trim())}</span>` : ""}</div>
      <div class="g-r-text">${paragraphs(x.text)}</div></article>`;
  }).join("");
  return `<section class="fiche-sec g-sec" aria-label="${h(label)}">${head}${score}${summary}
    ${facts ? `<dl class="kv g-facts">${facts}</dl>` : ""}
    ${reviews ? `<h3 class="fiche-h">Les avis les plus récents <span class="cnt">${r.reviews.length}</span></h3>${reviews}` : ""}
    ${note}${foot}${refreshSaid(v)}</section>`;
}

/** Les infos pratiques d'OpenStreetMap (l'index de ce serveur), sous leur source. */
export function osmBlock(f: PlaceFiche, now: number): string {
  const o = f.osm;
  if (!o) return "";
  const labels = new Set(o.facts.map((x) => x.label.toLowerCase()));
  const rows: Fact[] = [
    ...(o.address.trim() && !labels.has("adresse") ? [{ label: "Adresse", value: o.address }] : []),
    ...o.facts,
    ...(o.phone.trim() && !labels.has("téléphone") ? [{ label: "Téléphone", value: o.phone }] : []),
    ...(safeHref(o.website) && !labels.has("site") ? [{ label: "Site", value: safeHref(o.website) }] : []),
    ...(o.email.trim() && !labels.has("courriel") ? [{ label: "Courriel", value: o.email }] : []),
  ];
  const body = factRows(rows);
  if (!body) return "";
  const extract = isoWords(o.extract, now);
  return `<section class="fiche-sec"><h3 class="fiche-h">Infos pratiques</h3><dl class="kv">${body}</dl>
    ${sourceLine([outLink(o.licence_url, o.attribution || "© les contributeurs d'OpenStreetMap"),
      extract ? h(`extrait du ${extract}, dans l'index de ce serveur`) : "", outLink(o.url, "Corriger sur OpenStreetMap")])}</section>`;
}

/** Ce qu'en dit l'office de tourisme (DATAtourisme) : la description, les labels, les tarifs, les contacts, et qui l'a écrit. */
export function tourismBlock(f: PlaceFiche): string {
  const t = f.tourism;
  if (!t) return "";
  const labels = t.labels.filter((l) => l?.trim()).map((l) => `<span class="tag ok">${ico("shield-check", "xs")}${h(l.trim())}</span>`).join("");
  const rows = factRows([...(t.prices.trim() ? [{ label: "Tarifs", value: t.prices }] : []), ...t.contacts]);
  const desc = paragraphs(t.description, "fiche-desc");
  if (!desc && !labels && !rows) return "";
  return `<section class="fiche-sec"><h3 class="fiche-h">Ce qu'en dit l'office de tourisme</h3>${desc}
    ${labels ? `<div class="row wrap fiche-labels">${labels}</div>` : ""}${rows ? `<dl class="kv">${rows}</dl>` : ""}
    ${sourceLine([h(t.attribution || "DATAtourisme"), outLink(t.licence_url, t.licence || "Licence Ouverte"), outLink(t.url, "Sa fiche")])}</section>`;
}

/** La ligne d'un événement tout près (dans une fiche de lieu) : elle ouvre sa fiche dans l'onglet Événements. */
export function nearEvent(e: EventItem): string {
  const sub = [e.when_text, typeof e.distance_m === "number" ? km(e.distance_m) : "", e.free ? "gratuit" : e.price].filter((x) => x?.trim()).join(" · ");
  return `<a class="li place ev-near" href="#carte/evenements/${encodeURIComponent(e.id)}"><span class="pl-dot">${ico("calendar", "xs")}</span>
    <span class="li-main"><span class="li-title">${h(e.name || "—")}</span>${sub ? `<span class="li-snip">${h(sub)}</span>` : ""}</span></a>`;
}

/** Le plan d'une fiche : le lieu (choisi), et toi si on sait où tu es. */
function ficheScene(lat: number | null | undefined, lon: number | null | undefined, here: { lat: number; lon: number } | null, mika: boolean): Scene {
  const pins = typeof lat === "number" && typeof lon === "number" ? [{ id: "fiche", lat, lon, selected: true, mika }] : [];
  return { pins, lines: [], here: here && pins.length ? { lat: here.lat, lon: here.lon } : null };
}

/** La fiche d'un lieu, dans la colonne de gauche (la carte, à droite, le montre). */
export function placeFicheMarkup(v: PlaceFicheView): string {
  const f = v.fiche;
  const p = f?.place ?? v.place;
  const top = backLink(v.back);
  if (!p) {
    const body = v.gone
      ? `<div class="empty carte-failed">${ico("alert")}<b>Ce lieu n'est plus là</b><p>L'index des lieux a changé depuis, ou ce lieu n'existe pas.</p></div>`
      : v.error ? `<div class="empty carte-failed">${ico("alert")}<b>La fiche ne se lit pas</b><p>${h(failureText(v.error))}</p>
          <button class="btn sm" type="button" data-fiche-retry>${ico("refresh", "sm")}Réessayer</button></div>`
      : `<div class="empty">${ico("refresh")}<p>Lecture de la fiche…</p></div>`;
    return `<div class="fiche">${top}<div class="pane-scroll fiche-scroll">${body}</div></div>`;
  }
  const dist = typeof p.distance_m === "number" ? `à ${km(p.distance_m)}` : "";
  const sub = [placeWhat(p), dist].filter(Boolean).join(" · ");
  const photos = shownPhotos(f?.tourism?.photos, f?.reviews?.photos);
  const band = photoBand({ scene: ficheScene(p.lat, p.lon, v.here, v.mika), title: `Où est ${p.name || "ce lieu"}`, dist, photos, seen: v.seen });
  let sources = "";
  if (f) {
    const google = f.reviews ? googleBlock(f.reviews, v)
      : `<p class="small muted fiche-none">${ico("info", "xs")}Pas de note ni d'avis Google Maps pour ce lieu.</p>`;
    const events = f.events.length ? `<section class="fiche-sec"><h3 class="fiche-h">Bientôt, tout près <span class="cnt">${f.events.length}</span></h3>
      <div class="ev-near-list">${f.events.map(nearEvent).join("")}</div></section>` : "";
    // sans bloc Google, « Actualiser » relit tout de même l'office de tourisme
    const refresh = f.reviews ? "" : `<div class="fiche-end">${refreshButton(v, "Actualiser la fiche")}${refreshSaid(v)}</div>`;
    sources = google + osmBlock(f, v.now) + tourismBlock(f) + events + refresh;
  } else if (v.gone) {
    sources = `<p class="small cs-warn">${ico("alert", "xs")}Ce lieu n'est plus dans l'index des lieux : sa fiche ne se lit plus.</p>`;
  } else if (v.error) {
    sources = `<div class="fiche-end"><p class="small cs-warn">${ico("alert", "xs")}${h(failureText(v.error))}</p>
      <button class="btn sm" type="button" data-fiche-retry>${ico("refresh", "sm")}Réessayer</button></div>`;
  } else if (v.loading) {
    sources = `<p class="small muted fiche-loading">${ico("refresh", "xs")} Lecture de la fiche…</p>`;
  }
  return `<div class="fiche${v.mika ? " by-mika" : ""}" data-place-fiche>${top}
    <div class="pane-scroll fiche-scroll">
      <header class="fc-head"><h2>${h(p.name || "—")}</h2>${sub ? `<span class="muted small">${h(sub)}</span>` : ""}
        ${v.mika ? `<span class="stop-mika">${ico("sparkle", "xs")}Mika te l'a proposé</span>` : ""}</header>
      ${band}${placeTags(p, f?.reviews ?? null)}${placeActions(f)}${sources}
    </div></div>`;
}

// ── La fiche d'un événement ──────────────────────────────────────────

export interface EventFicheView {
  /** Sa ligne (celle de la liste en attendant la fiche). */
  event: EventItem | null;
  fiche: EventFiche | null;
  loading: boolean;
  error: unknown;
  gone: boolean;
  back: FicheBack;
  /** Mika l'a trouvé pour toi (un de ses regards). */
  mika: boolean;
  /** Les libellés des thèmes (`concerts` → « Concerts »). */
  themes: ReadonlyMap<string, string>;
  here: { lat: number; lon: number } | null;
  seen: (ref: string) => boolean;
}

/** Ses thèmes, en mots : « Concerts, Spectacles ». */
export function themeWords(e: Pick<EventItem, "themes">, themes: ReadonlyMap<string, string>): string {
  return (e.themes ?? []).map((t) => themes.get(t) ?? "").filter(Boolean).join(", ");
}

/** Son prix en court : « Gratuit », ses tarifs, ou rien. */
export function priceWords(e: Pick<EventItem, "free" | "price">): string {
  if (e.free === true) return e.price?.trim() && !/^gratuit$/i.test(e.price.trim()) ? `Gratuit · ${e.price.trim()}` : "Gratuit";
  return e.price?.trim() ?? "";
}

/** La fiche d'un événement : quand, où, combien, le programme, ses dates, les contacts, et qui l'a écrite. */
export function eventFicheMarkup(v: EventFicheView): string {
  const f = v.fiche;
  const e = f?.event ?? v.event;
  const top = backLink(v.back);
  if (!e) {
    const body = v.gone
      ? `<div class="empty carte-failed">${ico("alert")}<b>Cet événement n'est plus là</b><p>Il est passé, ou l'office de tourisme l'a retiré.</p></div>`
      : v.error ? `<div class="empty carte-failed">${ico("alert")}<b>La fiche ne se lit pas</b><p>${h(failureText(v.error))}</p>
          <button class="btn sm" type="button" data-fiche-retry>${ico("refresh", "sm")}Réessayer</button></div>`
      : `<div class="empty">${ico("refresh")}<p>Lecture de la fiche…</p></div>`;
    return `<div class="fiche">${top}<div class="pane-scroll fiche-scroll">${body}</div></div>`;
  }
  const town = f?.town?.trim() ?? "";
  const sub = [themeWords(e, v.themes), town].filter(Boolean).join(" · ");
  const dist = typeof (v.event?.distance_m ?? e.distance_m) === "number" ? `à ${km((v.event?.distance_m ?? e.distance_m) as number)}` : "";
  const band = photoBand({ scene: ficheScene(e.lat, e.lon, v.here, v.mika), title: `Où se tient ${e.name || "cet événement"}`, dist,
    photos: shownPhotos(f?.photos), seen: v.seen });
  const price = priceWords(e);
  const tags = [
    e.when_text.trim() ? `<span class="tag accent">${ico("calendar", "xs")}${h(e.when_text.trim())}</span>` : "",
    price ? `<span class="tag${e.free ? " ok" : ""}">${h(price)}</span>` : "",
    dist ? `<span class="tag">${h(dist)}</span>` : "",
  ].filter(Boolean).join("");
  const acts = `<div class="row wrap fiche-acts">
      <button class="btn sm primary" type="button" data-ev-route${typeof e.lat === "number" ? "" : " disabled"}>${ico("map", "sm")}Itinéraire</button>
      <button class="btn sm" type="button" data-ev-trip${typeof e.lat === "number" ? "" : " disabled"}>${ico("plus", "sm")}Ajouter au voyage</button>
      <button class="btn sm mika" type="button" data-ev-ask>${ico("chat", "sm")}En parler à Mika</button></div>`;
  let more = "";
  if (f) {
    const desc = paragraphs(f.description, "fiche-desc");
    const dates = f.dates.filter((d) => d.text?.trim()).map((d) => `<li>${h(d.text.trim())}</li>`).join("");
    const venue = f.venue.trim()
      ? PLACE_REF.test(f.venue_place)
        ? `<a href="#carte/explorer/lieu-${encodeURIComponent(f.venue_place)}">${h(f.venue.trim())}</a>` : h(f.venue.trim())
      : "";
    const where = [f.address.trim(), f.address.includes(town) ? "" : town].filter(Boolean).join(", ");
    const rows = (venue ? `<dt>Lieu</dt><dd>${venue}</dd>` : "")
      + factRows([...(where ? [{ label: "Adresse", value: where }] : []), ...(f.prices.trim() ? [{ label: "Tarifs", value: f.prices }] : []), ...f.contacts]);
    more = `${desc ? `<section class="fiche-sec"><h3 class="fiche-h">Le programme</h3>${desc}</section>` : ""}
      ${dates ? `<section class="fiche-sec"><h3 class="fiche-h">Ses dates</h3><ul class="ev-dates">${dates}</ul>${
        f.more_dates > 0 ? `<p class="small muted">${h(`Et ${f.more_dates} autre${f.more_dates > 1 ? "s" : ""} date${f.more_dates > 1 ? "s" : ""}.`)}</p>` : ""}</section>` : ""}
      ${rows ? `<section class="fiche-sec"><h3 class="fiche-h">Pratique</h3><dl class="kv">${rows}</dl></section>` : ""}
      ${sourceLine([h(f.attribution || "DATAtourisme"), outLink(f.licence_url, f.licence || "Licence Ouverte"), outLink(f.url, "Sa fiche"),
        f.merged > 1 ? h(`${f.merged} fiches de l'office réunies`) : ""])}`;
  } else if (v.gone) {
    more = `<p class="small cs-warn">${ico("alert", "xs")}Cet événement n'est plus là : sa fiche ne se lit plus.</p>`;
  } else if (v.error) {
    more = `<div class="fiche-end"><p class="small cs-warn">${ico("alert", "xs")}${h(failureText(v.error))}</p>
      <button class="btn sm" type="button" data-fiche-retry>${ico("refresh", "sm")}Réessayer</button></div>`;
  } else if (v.loading) {
    more = `<p class="small muted fiche-loading">${ico("refresh", "xs")} Lecture de la fiche…</p>`;
  }
  return `<div class="fiche${v.mika ? " by-mika" : ""}" data-event-fiche>${top}
    <div class="pane-scroll fiche-scroll">
      <header class="fc-head"><h2>${h(e.name || "—")}</h2>${sub ? `<span class="muted small">${h(sub)}</span>` : ""}
        ${e.place.trim() ? `<span class="small">${ico("pin", "xs")}${h(e.place.trim())}</span>` : ""}
        ${v.mika ? `<span class="stop-mika">${ico("sparkle", "xs")}Mika l'a trouvé pour toi</span>` : ""}</header>
      ${band}${tags ? `<div class="row wrap fiche-tags">${tags}</div>` : ""}${acts}${more}
    </div></div>`;
}
