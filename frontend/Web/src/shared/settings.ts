/**
 * Le gabarit du paramétrage, celui de la maquette (`maquette/ecrans/parametres.js`) : une ligne par réglage — son nom
 * et son aide à gauche, sa valeur à droite —, des sections titrées, des sous-onglets pour une page longue, et une
 * seule barre d'enregistrement par formulaire, qui flotte en bas dès qu'une valeur change.
 *
 * Un champ porte son nom (`name`, celui du moteur) ; un choix à boutons est un `.seg[data-seg]` (le cadre le règle
 * d'un clic et le dit par « mika:seg ») ; une ligne qui ne vaut que pour un choix porte `data-only="champ:valeur|…"`.
 *
 * Chaque page de réglages vit dans le dossier de l'écran de son domaine (`screens/mail/settings.ts`,
 * `screens/teams/settings.ts`…) ; l'écran Paramètres (`screens/parametres/index.ts`) les montre et leur sert
 * d'hôte. Ici, ce dont toutes ont besoin : les pièces d'une page, lire un formulaire, dire un refus, la barre
 * d'enregistrement, ce qu'une page et son hôte se doivent (`Page`, `Host`), les valeurs d'un formulaire et ce
 * qui en a changé.
 */
import { ApiError } from "../api/moi";
import { $, $$, h } from "../shell/dom";
import { toast } from "../shell/float";
import { ico } from "../shell/icons";
import type { PaletteEntry } from "../shell/palette";
import type { Shell } from "../shell/shell";
import { failureText, type Cached, type CachedMap } from "./kit";

// ── Les pièces ───────────────────────────────────────────────────────

export interface RowOptions {
  cls?: string;
  /** `champ:valeur|valeur` : la ligne ne se montre que pour ce choix. */
  only?: string;
}

/** Une ligne : `label` et `help` en texte simple, `value` en HTML. */
export function row(label: string, help: string, value: string, opts: RowOptions = {}): string {
  const only = opts.only ? ` data-only="${h(opts.only)}"` : "";
  return `<div class="set-row${opts.cls ? ` ${opts.cls}` : ""}"${only}><div class="set-label">${label ? `<b>${h(label)}</b>` : ""}${help ? `<p>${h(help)}</p>` : ""}</div><div class="set-value">${value}</div></div>`;
}

export function text(name: string, value: string, attrs = ""): string {
  return `<input name="${h(name)}" value="${h(value)}"${attrs ? ` ${attrs}` : ""}>`;
}

export function password(name: string, kept: boolean, attrs = ""): string {
  const hint = kept ? "gardé — laisse vide pour ne pas le changer" : "";
  return `<input type="password" name="${h(name)}" value="" autocomplete="new-password" placeholder="${h(hint)}"${attrs ? ` ${attrs}` : ""}>`;
}

export function number(name: string, value: number, attrs = ""): string {
  return `<input type="number" name="${h(name)}" value="${h(value)}"${attrs ? ` ${attrs}` : ""}>`;
}

export function area(name: string, value: string, rows = 2, attrs = ""): string {
  return `<textarea name="${h(name)}" rows="${rows}"${attrs ? ` ${attrs}` : ""}>${h(value)}</textarea>`;
}

export function toggle(name: string, on: boolean, attrs = ""): string {
  return `<label class="switch"><input type="checkbox" name="${h(name)}"${on ? " checked" : ""}${attrs ? ` ${attrs}` : ""}><i></i></label>`;
}

export function select(name: string, choices: readonly (readonly [string, string])[], value: string, attrs = ""): string {
  const known = choices.some(([k]) => k === value);
  const options = [...(known || !value ? [] : [[value, value] as const]), ...choices]
    .map(([k, l]) => `<option value="${h(k)}"${k === value ? " selected" : ""}>${h(l)}</option>`)
    .join("");
  return `<select name="${h(name)}"${attrs ? ` ${attrs}` : ""}>${options}</select>`;
}

export function seg(name: string, choices: readonly (readonly [string, string])[], active: string): string {
  return `<div class="seg" role="group" data-seg="${h(name)}">${choices
    .map(([k, l]) => `<button type="button" data-v="${h(k)}" aria-pressed="${k === active}">${h(l)}</button>`)
    .join("")}</div>`;
}

export interface SectionOptions {
  /** Le sous-onglet qui la montre. */
  sub?: string;
  hidden?: boolean;
  aside?: string;
  /** Une seule colonne (un tableau, une liste). */
  single?: boolean;
}

export function section(title: string, body: string, opts: SectionOptions = {}): string {
  return `<section class="set-sec"${opts.sub ? ` data-sous="${h(opts.sub)}"` : ""}${opts.hidden ? " hidden" : ""}>
    <div class="set-sec-head"><h2>${h(title)}</h2>${opts.aside ? `<div class="ph-actions">${opts.aside}</div>` : ""}</div>
    <div class="set-grid${opts.single ? "" : " two"}">${body}</div></section>`;
}

export function subTabs(page: string, list: readonly (readonly [string, string])[], active: string): string {
  return `<nav class="sub-seg" data-souspage="${h(page)}">${list
    .map(([k, l]) => `<button type="button" data-sousv="${h(k)}" aria-pressed="${k === active}">${h(l)}</button>`)
    .join("")}</nav>`;
}

export function backLink(href: string, label: string): string {
  return `<a class="back-link" href="${h(href)}">${ico("chev-left", "sm")}${h(label)}</a>`;
}

// ── Lire un formulaire ───────────────────────────────────────────────

/**
 * Ses valeurs : un texte, un nombre (un champ `type=number`), une case (vrai ou faux), un choix à boutons ; des cases
 * du même nom avec une valeur (`folders`) donnent la liste de celles qui sont cochées.
 */
export function readForm(root: ParentNode): Record<string, FormValue> {
  const out: Record<string, FormValue> = {};
  const groups = new Map<string, HTMLInputElement[]>();
  for (const el of $$<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input[name], select[name], textarea[name]", root)) {
    if (el.closest("[data-ignore]")) continue;
    if (el instanceof HTMLInputElement && el.type === "checkbox" && el.hasAttribute("value")) {
      const list = groups.get(el.name) ?? [];
      list.push(el);
      groups.set(el.name, list);
      continue;
    }
    if (el instanceof HTMLInputElement && el.type === "checkbox") out[el.name] = el.checked;
    else if (el instanceof HTMLInputElement && el.type === "number") out[el.name] = el.value === "" ? 0 : Number(el.value);
    else out[el.name] = el.value;
  }
  for (const [name, list] of groups) out[name] = list.filter((x) => x.checked).map((x) => x.value);
  for (const s of $$<HTMLElement>(".seg[data-seg]", root)) {
    if (s.closest("[data-ignore]")) continue;
    const on = s.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (on && s.dataset.seg) out[s.dataset.seg] = on.dataset.v ?? "";
  }
  return out;
}

/** Les lignes `data-only` : montrées pour le choix qu'elles nomment seulement. */
export function applyOnly(root: ParentNode): void {
  const values = readForm(root);
  for (const el of $$<HTMLElement>("[data-only]", root)) {
    const [field, wanted] = (el.dataset.only ?? "").split(":");
    el.hidden = !(wanted ?? "").split("|").includes(String(values[field] ?? ""));
  }
}

/** Les messages d'un refus, sous leurs champs ; le premier sous-onglet qui en porte un s'ouvre. Ce qui n'a pas de
 *  champ montré (absent, ou sur une ligne qui ne vaut que pour un autre choix) revient à dire à part. */
export function showFieldErrors(root: HTMLElement, errors: Record<string, string>): string[] {
  for (const old of $$(".set-err", root)) old.remove();
  const unplaced: string[] = [];
  let firstSub: string | null = null;
  for (const [name, message] of Object.entries(errors)) {
    const field = root.querySelector<HTMLElement>(`[name="${CSS.escape(name)}"], [data-seg="${CSS.escape(name)}"]`);
    const place = field?.closest<HTMLElement>(".set-value, .field");
    if (!place || place.closest<HTMLElement>("[data-only]")?.hidden) {
      const label = field?.closest(".set-row")?.querySelector(".set-label b")?.textContent?.trim();
      unplaced.push(`${label || name} : ${message}`);
      continue;
    }
    place.insertAdjacentHTML("beforeend", `<p class="set-err">${ico("alert", "xs")}${h(message)}</p>`);
    firstSub ??= place.closest<HTMLElement>("[data-sous]")?.dataset.sous ?? null;
  }
  if (firstSub) root.querySelector<HTMLElement>(`[data-sousv="${CSS.escape(firstSub)}"]`)?.click();
  return unplaced;
}

/** Un refus du moteur après un envoi, la seule façon de le dire : ses champs (`fields`) sous les leurs, et ce qui n'a
 *  pas trouvé sa place (un champ que ce formulaire ne montre pas, comme `secret_headers` au branchement d'un service)
 *  dit par `say` — rien de plus quand tout est placé ; un refus sans champs, dit tel quel. `say` : le toast d'alerte
 *  par défaut, ou la ligne d'erreur d'une fenêtre qui reste ouverte. */
export function showRefusal(root: HTMLElement, err: unknown, say: (text: string) => void = alertToast): void {
  if (err instanceof ApiError && Object.keys(err.fields).length) {
    const rest = showFieldErrors(root, fieldErrors(err.fields));
    if (rest.length) say(rest.join(" ; "));
  } else say(failureText(err));
}

function alertToast(text: string): void {
  toast(text, { ico: "alert", duration: 4200 });
}

export function clearFieldErrors(root: ParentNode): void {
  for (const old of $$(".set-err", root)) old.remove();
}

// ── La barre d'enregistrement ────────────────────────────────────────

export interface SaveHandlers {
  /** Enregistrer ce qui a changé ; `true` : c'est fait (la barre s'en va). */
  save: (form: HTMLElement, changes: Record<string, FormValue>, values: Record<string, FormValue>) => Promise<boolean>;
  /** Revenir aux valeurs d'avant (redessiner la page). */
  reset: (form: HTMLElement) => void;
}

/**
 * Une seule barre pour la page : elle suit le formulaire qu'on modifie, compare ses valeurs à celles du départ, et
 * s'en va quand on quitte l'écran (ce qui n'est pas enregistré est perdu, comme dans la maquette).
 */
export class SaveBar {
  private el: HTMLElement | null = null;
  private form: HTMLElement | null = null;
  private readonly initial = new WeakMap<HTMLElement, Record<string, FormValue>>();
  private busy = false;

  constructor(private readonly handlers: SaveHandlers) {
    addEventListener("hashchange", () => this.hide());
  }

  /** Un formulaire fraîchement dessiné : ses valeurs de départ. */
  track(form: HTMLElement): void {
    this.initial.set(form, readForm(form));
    applyOnly(form);
    if (this.form && !this.form.isConnected) this.hide();
  }

  /** Une valeur a bougé dans ce formulaire. */
  touched(form: HTMLElement): void {
    applyOnly(form);
    const start = this.initial.get(form);
    if (!start) return;
    if (Object.keys(changed(start, readForm(form))).length) this.show(form);
    else if (this.form === form) this.hide();
  }

  changes(form: HTMLElement): Record<string, FormValue> {
    return changed(this.initial.get(form) ?? {}, readForm(form));
  }

  /** Ce formulaire, encore à l'écran, a des modifications non enregistrées. */
  unsaved(form: HTMLElement): boolean {
    return form.isConnected && this.initial.has(form) && Object.keys(this.changes(form)).length > 0;
  }

  /**
   * Une saisie en cours sous `root`, qu'un nouveau dessin effacerait. Pas pendant un enregistrement : la page se
   * redessine alors depuis ce qui vient d'être gardé.
   */
  holds(root: ParentNode): boolean {
    return !this.busy && $$<HTMLElement>("[data-form]", root).some((f) => this.unsaved(f));
  }

  hide(): void {
    this.el?.classList.remove("on");
    this.form = null;
  }

  /** Enregistrer ce formulaire ; `true` : c'est fait (ou il n'y avait rien à enregistrer), `false` : refusé ou déjà en
   *  cours. */
  async submit(form: HTMLElement): Promise<boolean> {
    if (this.busy) return false;
    const changes = this.changes(form);
    if (!Object.keys(changes).length) {
      this.hide();
      return true;
    }
    this.busy = true;
    this.bar().querySelectorAll<HTMLButtonElement>("button").forEach((b) => (b.disabled = true));
    try {
      const done = await this.handlers.save(form, changes, readForm(form));
      if (done) this.hide();
      return done;
    } finally {
      this.busy = false;
      this.bar().querySelectorAll<HTMLButtonElement>("button").forEach((b) => (b.disabled = false));
    }
  }

  private show(form: HTMLElement): void {
    this.form = form;
    this.bar().classList.add("on");
  }

  private bar(): HTMLElement {
    if (this.el) return this.el;
    const el = document.createElement("div");
    el.className = "savebar";
    el.setAttribute("role", "region");
    el.setAttribute("aria-label", "Modifications non enregistrées");
    el.innerHTML = `<span>Modifications non enregistrées</span>
      <button class="btn sm" type="button" data-sb="annuler">Annuler</button>
      <button class="btn sm primary" type="button" data-sb="enregistrer">Enregistrer</button>`;
    el.addEventListener("click", (e) => {
      const b = (e.target as Element).closest<HTMLElement>("[data-sb]");
      const form = this.form;
      if (!b || !form) return;
      if (b.dataset.sb === "enregistrer") void this.submit(form);
      else {
        this.hide();
        this.handlers.reset(form);
      }
    });
    document.body.appendChild(el);
    this.el = el;
    return el;
  }
}

/**
 * Un geste qui agit sur ce qui est enregistré (tester une boîte ou un service, connecter une boîte à Microsoft) : les
 * modifications non enregistrées de ce formulaire d'abord — sinon il partirait avec les anciennes valeurs, et la
 * page redessinée effacerait les nouvelles. `false` : l'enregistrement est refusé (dit sous les champs), le geste ne
 * part pas.
 */
export async function savedFirst(form: HTMLElement | null, bar: SaveBar): Promise<boolean> {
  if (!form || !bar.unsaved(form)) return true;
  return bar.submit(form);
}

/** Le formulaire où un évènement est arrivé (`[data-form]`), s'il y en a un. */
export function formOf(target: EventTarget | null): HTMLElement | null {
  return (target as Element | null)?.closest?.<HTMLElement>("[data-form]") ?? null;
}

// ── Une page et son hôte ─────────────────────────────────────────────

/**
 * Ce qu'une page de réglages (un onglet de Paramètres) donne à l'écran qui la montre : ce qu'il faut lire avant de
 * la montrer, ce qui peut arriver après, son dessin, ses actions de barre de titre, ses gestes (`data-act`),
 * l'enregistrement de ses formulaires. L'écran (`screens/parametres/index.ts`) s'occupe du reste : lire, redessiner,
 * la barre d'enregistrement, les sous-onglets.
 */
export interface Host {
  shell: Shell;
  bar: SaveBar;
  /** Le sous-onglet choisi d'une page (`fallback` tant qu'on n'en a pas choisi). */
  sub(page: string, fallback: string): string;
  setSub(page: string, value: string): void;
  /** Redessiner la page ouverte, depuis ce qui est lu. */
  repaint(): void;
  /** Relire ces ressources (ou toutes celles de la page), puis redessiner. */
  reload(...caches: (Cached<unknown> | CachedMap<unknown>)[]): Promise<void>;
  go(hash: string): void;
}

export interface Page {
  id: string;
  /** Ce qu'il faut avoir lu pour la dessiner. */
  needs(item: string | null): Cached<unknown>[];
  /** Ce qui l'enrichit quand ça arrive (elle se redessine alors). */
  extras?(item: string | null): Cached<unknown>[];
  view(item: string | null, host: Host): string;
  actions?(item: string | null, host: Host): string;
  act?(name: string, el: HTMLElement, item: string | null, host: Host): void;
  save?(form: HTMLElement, changes: Record<string, FormValue>, values: Record<string, FormValue>, item: string | null, host: Host): Promise<boolean>;
  /** Après chaque dessin (ses formulaires y sont déjà suivis). */
  after?(root: HTMLElement, item: string | null, host: Host): void;
  search?(): PaletteEntry[];
}

// ── Les formulaires ──────────────────────────────────────────────────

export type FormValue = string | number | boolean | string[];

/** Ce qui a changé d'un formulaire : les champs dont la valeur n'est plus celle de départ. */
export function changed(before: Record<string, FormValue>, after: Record<string, FormValue>): Record<string, FormValue> {
  const out: Record<string, FormValue> = {};
  for (const [k, v] of Object.entries(after)) {
    if (JSON.stringify(v) !== JSON.stringify(before[k])) out[k] = v;
  }
  return out;
}

/** Les messages d'un formulaire refusé, par champ : la dernière partie du chemin (`accounts.pro.imap_port` → `imap_port`). */
export function fieldErrors(fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, message] of Object.entries(fields)) {
    const name = path.split(".").pop() || path;
    out[name] = out[name] ? `${out[name]} ; ${message}` : message;
  }
  return out;
}

export { $, $$ };
