/**
 * Ce qui flotte au-dessus des écrans : les toasts, la fenêtre, les menus. Les mêmes que la maquette
 * (`M.toast`, `M.modal`, `M.menu`), avec les mêmes classes.
 */
import { $, h, on } from "./dom";
import { ico, type IconName } from "./icons";

// ── Les toasts ───────────────────────────────────────────────────────

export interface ToastOptions {
  /** Ce que fait Mika : l'icône en rose. */
  mika?: boolean;
  ico?: IconName;
  /** Millisecondes. */
  duration?: number;
}

export function toast(text: string, opts: ToastOptions = {}): void {
  const root = $("#toasts");
  if (!root) return;
  const el = document.createElement("div");
  el.className = `toast${opts.mika ? " mika" : ""}`;
  el.innerHTML = `${ico(opts.ico ?? (opts.mika ? "sparkle" : "check"))}<span>${h(text)}</span>`;
  root.appendChild(el);
  window.setTimeout(() => {
    el.classList.add("out");
    window.setTimeout(() => el.remove(), 250);
  }, opts.duration ?? 2600);
}

// ── La fenêtre ───────────────────────────────────────────────────────

export interface ModalOptions {
  title: string;
  /** Du HTML déjà échappé. */
  body: string;
  foot?: string;
  size?: "wide" | "narrow";
  head?: string;
}

export function openModal(opts: ModalOptions): HTMLElement {
  closeModal();
  const root = $("#modal-root");
  const scrim = document.createElement("div");
  scrim.className = "modal-scrim";
  scrim.innerHTML = `<div class="modal${opts.size ? ` ${opts.size}` : ""}" role="dialog" aria-modal="true" aria-label="${h(opts.title)}">
    <div class="modal-head"><h2>${h(opts.title)}</h2><div class="ph-actions">${opts.head ?? ""}
      <button class="btn icon ghost sm" type="button" data-close title="Fermer">${ico("x")}</button></div></div>
    <div class="modal-body">${opts.body}</div>${opts.foot ? `<div class="modal-foot">${opts.foot}</div>` : ""}</div>`;
  scrim.addEventListener("mousedown", (e) => {
    if (e.target === scrim) closeModal();
  });
  on(scrim, "[data-close]", "click", () => closeModal());
  root?.appendChild(scrim);
  const first = scrim.querySelector<HTMLElement>("input, textarea, select");
  if (first) window.setTimeout(() => first.focus(), 30);
  return scrim.firstElementChild as HTMLElement;
}

export function closeModal(): void {
  const root = $("#modal-root");
  if (root) root.innerHTML = "";
}

export function modalOpen(): boolean {
  return !!$("#modal-root")?.children.length;
}

// ── Les menus ────────────────────────────────────────────────────────

export type MenuItem =
  | "sep"
  | { header: string }
  | { html: string }
  | {
      label: string;
      icon?: IconName;
      danger?: boolean;
      checked?: boolean;
      kbd?: string;
      action?: () => void;
    };

let menuEl: HTMLElement | null = null;

function closeIfOutside(e: MouseEvent): void {
  if (menuEl && !menuEl.contains(e.target as Node)) closeMenu();
}

export function openMenu(anchor: HTMLElement, items: MenuItem[], opts: { align?: "left" | "right" } = {}): HTMLElement {
  closeMenu();
  const el = document.createElement("div");
  el.className = "menu";
  el.setAttribute("role", "menu");
  el.innerHTML = items
    .map((it, i) => {
      if (it === "sep") return '<div class="msep"></div>';
      if ("header" in it) return `<div class="mh">${h(it.header)}</div>`;
      if ("html" in it) return it.html;
      const checked = it.checked !== undefined ? ` aria-checked="${it.checked}"` : "";
      return `<button class="mi${it.danger ? " danger" : ""}" type="button" role="menuitem" data-i="${i}"${checked}>
        ${it.icon ? ico(it.icon) : ""}<span>${h(it.label)}</span>${it.kbd ? `<kbd class="kbd">${h(it.kbd)}</kbd>` : ""}</button>`;
    })
    .join("");
  document.body.appendChild(el);
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth;
  const hgt = el.offsetHeight;
  let left = opts.align === "left" ? r.left : r.right - w;
  left = Math.max(8, Math.min(left, innerWidth - w - 8));
  let top = r.bottom + 6;
  if (top + hgt > innerHeight - 8) top = Math.max(8, r.top - hgt - 6);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
  on(el, ".mi", "click", (_e, b) => {
    const it = items[Number(b.dataset.i)];
    closeMenu();
    if (it && it !== "sep" && "label" in it) it.action?.();
  });
  menuEl = el;
  window.setTimeout(() => document.addEventListener("mousedown", closeIfOutside), 0);
  return el;
}

export function closeMenu(): void {
  if (menuEl) {
    menuEl.remove();
    menuEl = null;
  }
  document.removeEventListener("mousedown", closeIfOutside);
}
