/**
 * Les petites pièces que Téléphone, Outils et Paramètres partagent : une lecture gardée (`Cached`), ce qu'on montre
 * pendant une lecture ou après un refus, l'avatar d'une personne, les dates en mots, copier un texte, une question
 * de confirmation, la clé d'un envoi. Le reste du DOM, des fenêtres et des toasts vient du cadre (`shell/`).
 */
import { BackendUnreachableError } from "@web/network/api";
import { ApiError } from "../../api/moi";
import { h, hue, initials } from "../../shell/dom";
import { closeModal, openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { clock, shortWhen } from "../chat/markup";

// ── Une lecture gardée ───────────────────────────────────────────────

/**
 * Une ressource de l'API, lue au plus une fois à la fois et gardée `ttl` millisecondes. Une relecture qui échoue
 * garde la valeur d'avant (et dit l'erreur), sauf un 404 : ce qui n'existe plus (supprimé, oublié) ne se montre plus.
 * Une relecture forcée demandée pendant une lecture en cours suit celle-ci (elle a pu partir avant ce qu'on vient
 * d'écrire). `version` ne bouge que si ce qui est lu change : un écran ne se redessine que pour cela.
 */
export class Cached<T> {
  value: T | null = null;
  error: unknown = null;
  version = 0;
  private at = 0;
  private said = "";
  private pending: Promise<T | null> | null = null;
  /** La relecture forcée qui suivra la lecture en cours : une seule, pour toutes les demandes d'ici là. */
  private again: Promise<T | null> | null = null;

  constructor(
    private readonly fetcher: () => Promise<T>,
    private readonly ttl = 15_000,
  ) {}

  /** Lu (ou refusé) au moins une fois. */
  get settled(): boolean {
    return this.value !== null || this.error !== null;
  }

  load(force = false): Promise<T | null> {
    if (this.pending) {
      if (!force) return this.pending;
      this.again ??= this.pending.then(() => {
        this.again = null;
        return this.load(true);
      });
      return this.again;
    }
    if (!force && this.settled && Date.now() - this.at < this.ttl) return Promise.resolve(this.value);
    this.pending = this.fetcher()
      .then((value) => {
        const said = JSON.stringify(value);
        if (said !== this.said || this.error !== null) this.version += 1;
        this.said = said;
        this.value = value;
        this.error = null;
        return value;
      })
      .catch((err: unknown) => {
        const gone = err instanceof ApiError && err.status === 404 && this.value !== null;
        if (this.error === null || gone) this.version += 1;
        this.error = err;
        if (gone) {
          this.value = null;
          this.said = "";
        }
        return this.value;
      })
      .finally(() => {
        this.at = Date.now();
        this.pending = null;
      });
    return this.pending;
  }

  /** La prochaine lecture repartira du serveur. */
  invalidate(): void {
    this.at = 0;
  }
}

/** Des lectures gardées par clé (un fil, une boîte). */
export class CachedMap<T> {
  private readonly items = new Map<string, Cached<T>>();

  constructor(
    private readonly fetcher: (key: string) => Promise<T>,
    private readonly ttl = 15_000,
  ) {}

  get(key: string): Cached<T> {
    let found = this.items.get(key);
    if (!found) {
      found = new Cached(() => this.fetcher(key), this.ttl);
      this.items.set(key, found);
    }
    return found;
  }

  invalidate(key?: string): void {
    if (key === undefined) for (const c of this.items.values()) c.invalidate();
    else this.items.get(key)?.invalidate();
  }
}

// ── Ce qu'on montre en attendant, ou après un refus ──────────────────

/** Ce que dit une erreur, en français : le refus du serveur, ou qu'il ne répond pas. */
export function failureText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof BackendUnreachableError) return "Le serveur de Mika ne répond pas.";
  return "Ça n'a pas abouti.";
}

export function sessionGone(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

export function loadingBlock(text = "Chargement…"): string {
  return `<div class="empty">${ico("refresh")}<p>${h(text)}</p></div>`;
}

/** Une lecture refusée : ce qu'elle dit, et de quoi réessayer (`data-retry`) ou se reconnecter. */
export function errorBlock(err: unknown, what = "Impossible de lire cette page"): string {
  const again = sessionGone(err)
    ? `<button class="btn sm" type="button" data-relogin>${ico("logout", "sm")}Se reconnecter</button>`
    : `<button class="btn sm" type="button" data-retry>${ico("refresh", "sm")}Réessayer</button>`;
  return `<div class="empty">${ico("alert")}<b>${h(what)}</b><p>${h(failureText(err))}</p>${again}</div>`;
}

/** Un refus après un geste : un toast qui le dit. */
export function toastFailure(err: unknown): void {
  toast(failureText(err), { ico: "alert", duration: 4200 });
}

// ── Les personnes ────────────────────────────────────────────────────

export function personAvatar(name: string, size?: "xs" | "sm" | "lg"): string {
  return `<span class="av${size ? ` ${size}` : ""} c${hue(name)}" title="${h(name)}">${h(initials(name))}</span>`;
}

// ── Les dates ────────────────────────────────────────────────────────

const MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
  "novembre", "décembre"];
const WEEKDAYS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];

function dayStart(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function daysBetween(ms: number, now: number): number {
  return Math.round((dayStart(now) - dayStart(ms)) / 86_400_000);
}

/** « 12 octobre », « 2 septembre 2025 ». */
export function dateWords(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const d = new Date(ms);
  const label = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === new Date(now).getFullYear() ? label : `${label} ${d.getFullYear()}`;
}

/** Le repère d'un jour dans un fil : « Aujourd'hui », « Hier », « lundi 2 novembre ». */
export function dayWords(ms: number, now: number): string {
  const days = daysBetween(ms, now);
  if (days <= 0) return "Aujourd'hui";
  if (days === 1) return "Hier";
  return `${WEEKDAYS[new Date(ms).getDay()]} ${dateWords(ms, now)}`;
}

/** Depuis quand : « à l'instant », « il y a 3 min », « il y a 2 h », « hier à 22:10 », « le 12 octobre ». */
export function ago(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const minutes = Math.floor((now - ms) / 60_000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const days = daysBetween(ms, now);
  if (days <= 0) return `il y a ${Math.floor(minutes / 60)} h`;
  if (days === 1) return `hier à ${clock(ms)}`;
  return `le ${dateWords(ms, now)}`;
}

/** Jusqu'à quand, depuis maintenant : « dans 1 h 52 », « dans 4 min », « échue ». */
export function remaining(until: number, now: number): string {
  const minutes = Math.ceil((until - now) / 60_000);
  if (!Number.isFinite(minutes) || minutes <= 0) return "échue";
  if (minutes < 60) return `dans ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `dans ${hours} h ${String(rest).padStart(2, "0")}` : `dans ${hours} h`;
}

export { clock, shortWhen };

// ── Copier, confirmer, la clé d'un envoi ─────────────────────────────

/**
 * Copier un texte. `navigator.clipboard` n'existe qu'en contexte sûr (https, localhost) : ailleurs (le portable par
 * son adresse du réseau), la vieille commande du document.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // refusé : on essaie l'autre chemin
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let done = false;
  try {
    done = document.execCommand("copy");
  } catch {
    done = false;
  }
  area.remove();
  return done;
}

export interface ConfirmOptions {
  title: string;
  /** Du texte simple (échappé ici). */
  text: string;
  ok: string;
  danger?: boolean;
}

/** Une question avant un geste qui ne se défait pas : `true` si on confirme. */
export function confirmModal(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    let answered = false;
    const el = openModal({
      title: opts.title,
      size: "narrow",
      body: `<p>${h(opts.text)}</p>`,
      foot: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn ${opts.danger ? "danger" : "primary"}" type="button" data-ok>${h(opts.ok)}</button>`,
    });
    el.querySelector("[data-ok]")?.addEventListener("click", () => {
      answered = true;
      closeModal();
      resolve(true);
    });
    // fermée autrement (Annuler, Échap, le fond) : non
    const scrim = el.parentElement;
    const watch = new MutationObserver(() => {
      if (!scrim?.isConnected) {
        watch.disconnect();
        if (!answered) resolve(false);
      }
    });
    if (scrim?.parentElement) watch.observe(scrim.parentElement, { childList: true });
  });
}

/**
 * La clé d'un envoi (un double clic ne refait rien). `crypto.randomUUID` n'existe qu'en contexte sûr :
 * `getRandomValues`, partout.
 */
export function newNonce(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
