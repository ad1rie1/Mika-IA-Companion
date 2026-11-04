/**
 * Le gabarit du paramétrage, celui de la maquette (`maquette/ecrans/parametres.js`) : une ligne par réglage — son nom
 * et son aide à gauche, sa valeur à droite —, des sections titrées, des sous-onglets pour une page longue, et une
 * seule barre d'enregistrement par formulaire, qui flotte en bas dès qu'une valeur change.
 *
 * Un champ porte son nom (`name`, celui du moteur) ; un choix à boutons est un `.seg[data-seg]` (le cadre le règle
 * d'un clic et le dit par « mika:seg ») ; une ligne qui ne vaut que pour un choix porte `data-only="champ:valeur|…"`.
 */
import { $, $$, h } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { changed, type FormValue } from "./words";

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

export { $, $$ };
