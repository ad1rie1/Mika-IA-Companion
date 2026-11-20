/**
 * Carte : les photos dans la page — elles se chargent quand elles paraissent, et s'ouvrent dans la visionneuse.
 *
 * Une photo de Google coûte un appel compté la première fois que le serveur la relève (`protocole-moi.md` § 10) : une
 * image ne se demande que quand elle entre dans ce qui se voit de sa bande ou de sa liste (`img[data-src]`, posées par
 * `sources.ts::photoImg`), jamais les dix d'une fiche d'un coup. Une photo déjà montrée se pose tout de suite au dessin
 * suivant (`seen` : le navigateur la garde un jour, `private, max-age=86400`), sans clignoter.
 */
import { $, $$, on } from "../../shell/dom";
import { openModal } from "../../shell/float";
import type { Photo } from "../../api/carte";
import { viewerMarkup } from "./fiche";

/** Les photos déjà montrées dans cette page (leur référence). */
const shown = new Set<string>();

/** Cette photo s'est déjà montrée : elle se pose sans attendre. */
export function photoSeen(ref: string): boolean {
  return shown.has(ref);
}

let observers: IntersectionObserver[] = [];

function load(img: HTMLImageElement): void {
  const src = img.dataset.src;
  if (!src) return;
  delete img.dataset.src;
  img.src = src;
}

/** Ses images, une fois arrivées (ou en échec : la place garde son icône). */
function watch(img: HTMLImageElement): void {
  const ref = img.dataset.ref ?? "";
  const done = () => {
    if (ref) shown.add(ref);
    img.closest(".ph, .pl-thumb")?.classList.add("loaded");
  };
  if (img.complete && img.naturalWidth > 0) done();
  else {
    img.addEventListener("load", done, { once: true });
    img.addEventListener("error", () => img.closest(".ph, .pl-thumb")?.classList.add("broken"), { once: true });
  }
}

/**
 * Après un dessin : chaque image en attente se charge quand elle paraît (dans sa bande, ou à l'écran), avec un peu
 * d'avance (la suivante d'une bande). Les observateurs du dessin d'avant s'en vont.
 */
export function attachPhotos(root: HTMLElement): void {
  for (const o of observers) o.disconnect();
  observers = [];
  for (const img of $$<HTMLImageElement>("img[data-ref]", root)) watch(img);
  const waiting = $$<HTMLImageElement>("img[data-src]", root);
  if (!waiting.length) return;
  if (typeof IntersectionObserver === "undefined") {
    waiting.forEach(load);
    return;
  }
  const byRoot = new Map<Element | null, HTMLImageElement[]>();
  for (const img of waiting) {
    // une bande se défile de côté : elle est sa racine ; ailleurs, la page (une image cachée par ce qui la fait défiler
    // n'y paraît pas : l'intersection tient compte de chaque cadre qui la rogne)
    const scroller = img.closest("[data-photo-scroll]");
    const list = byRoot.get(scroller);
    if (list) list.push(img);
    else byRoot.set(scroller, [img]);
  }
  for (const [scroller, imgs] of byRoot) {
    const band = scroller?.hasAttribute("data-photo-scroll");
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        io.unobserve(e.target);
        load(e.target as HTMLImageElement);
      }
    }, { root: scroller, rootMargin: band ? "0px 120px 0px 120px" : "200px 0px 200px 0px" });
    imgs.forEach((img) => io.observe(img));
    observers.push(io);
  }
}

/**
 * La visionneuse : une photo en grand, sa légende, son auteur, sa licence, d'où elle vient ; « précédente » et
 * « suivante », les flèches du clavier aussi. Échap la ferme (le cadre).
 */
export function openViewer(photos: readonly Photo[], index: number): void {
  if (!photos.length) return;
  let at = index;
  const el = openModal({ title: "Photos", size: "wide", body: viewerMarkup(photos, at) });
  el.classList.add("viewer-modal");
  const body = $<HTMLElement>(".modal-body", el);
  const show = (delta: number) => {
    at = (at + delta + photos.length) % photos.length;
    if (body) body.innerHTML = viewerMarkup(photos, at);
    for (const img of $$<HTMLImageElement>("img[data-ref]", el)) watch(img);
  };
  for (const img of $$<HTMLImageElement>("img[data-ref]", el)) watch(img);
  on(el, "[data-vw]", "click", (_e, b) => show(Number(b.dataset.vw) < 0 ? -1 : 1));
  el.tabIndex = -1;
  el.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") show(-1);
    else if (e.key === "ArrowRight") show(1);
  });
  window.setTimeout(() => el.focus(), 30);
}
