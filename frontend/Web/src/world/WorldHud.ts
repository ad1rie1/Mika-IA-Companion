import * as THREE from "three";
import { forActor, forObject, forSelf, type ActionOption } from "./actionMenu";
import type { Request, Result } from "./protocol.g";
import type { Focus, WorldStage } from "./WorldStage";
import type { LinkState, WorldSession } from "./WorldSession";
import "./world.css";

export interface WorldHudDeps {
  session: WorldSession;
  stage: WorldStage;
  canvas: HTMLCanvasElement;
  camera: THREE.Camera;
  /** Où monter l'interface (le conteneur de l'application). */
  parent: HTMLElement;
}

/** Un clic qui a bougé de plus (px) est un glissé de la caméra, pas un clic. */
const CLICK_SLOP_PX = 6;
const CLICK_MAX_MS = 500;
/** Le temps de voir venir un double-clic (il recadre la caméra) avant d'ouvrir le menu. */
const DOUBLE_CLICK_MS = 260;
const TOAST_MS = 4500;
/** Le survol se mesure au plus à cette cadence (ms) : viser toute la pièce a un coût. */
const HOVER_EVERY_MS = 90;

/**
 * L'interface du monde, par-dessus la scène : ce que l'on vise et ce qu'on
 * peut en faire (le menu d'actions), les refus du noyau, les demandes de
 * Mika, l'état de la connexion au monde. Le jumeau du `WorldHud` d'Unity,
 * adapté à la souris : survoler montre le nom et le geste par défaut, un clic
 * (ou un clic droit) ouvre le menu, un clic droit dans le vide propose ce
 * qu'on peut faire de soi-même. La conversation, elle, reste celle du client
 * web (ChatOverlay). L'interface ne parle jamais au noyau elle-même : tout
 * passe par la session, et rien ne change à l'écran avant que le noyau l'ait
 * dit (le refus revient en phrase, telle quelle).
 */
export class WorldHud {
  private readonly root: HTMLDivElement;
  private readonly top: HTMLDivElement;
  private readonly status: HTMLDivElement;
  private readonly tag: HTMLDivElement;
  private readonly menu: HTMLDivElement;
  private readonly requestBox: HTMLDivElement;
  private readonly requestText: HTMLDivElement;
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private pending: Request | null = null;
  private statusTimer: number | null = null;
  private hoverAt = 0;
  private hoverTimer: number | null = null;
  private down: { x: number; y: number; at: number } | null = null;
  private clickTimer: number | null = null;
  private lastMove: { x: number; y: number } | null = null;

  constructor(private readonly deps: WorldHudDeps) {
    this.root = el("div");
    this.root.id = "world-hud";
    this.top = el("div", "world-top", this.root);
    this.status = el("div", "world-status", this.top);
    this.requestBox = el("div", "world-request", this.top);
    this.requestText = el("div", "world-request-text", this.requestBox);
    const buttons = el("div", "world-request-buttons", this.requestBox);
    button("Refuser", buttons, () => this.answer(false));
    button("Accepter", buttons, () => this.answer(true)).classList.add("primary");
    this.requestBox.hidden = true;
    this.tag = el("div", "world-tag", this.root);
    this.tag.hidden = true;
    this.menu = el("div", "world-menu", this.root);
    this.menu.hidden = true;
    deps.parent.appendChild(this.root);

    const { session } = deps;
    session.on("state", (s) => this.showStatus(s));
    this.showStatus(session.state);
    session.mirror.on("requestOpened", (r) => this.onRequest(r));
    session.mirror.on("requestClosed", (c) => {
      if (this.pending?.id === c.request) this.hideRequest();
    });
    session.mirror.on("reset", () => {
      // Un instantané peut porter une demande qui attend encore (un écran qui arrive).
      const me = session.actor;
      const waiting = [...session.mirror.requests.values()].find((r) => r.to_actor === me);
      if (waiting) this.onRequest(waiting);
      else if (this.pending && !session.mirror.requests.has(this.pending.id)) this.hideRequest();
    });
    this.wirePointer();
  }

  // ── l'état du monde ───────────────────────────────────────────────

  private showStatus(state: LinkState): void {
    if (this.statusTimer !== null) window.clearTimeout(this.statusTimer);
    this.statusTimer = null;
    const text: Record<LinkState, string> = {
      online: "Monde : en ligne",
      connecting: "Monde : connexion…",
      greeting: "Monde : présentation…",
      refused: "Monde : connexion refusée",
      offline: "Monde : hors ligne",
    };
    this.status.textContent = text[state];
    this.status.className = `world-status ${
      state === "online" ? "ok" : state === "refused" || state === "offline" ? "bad" : "warn"
    }`;
    // En ligne, l'état s'efface : il ne reparaît que s'il y a quelque chose à dire.
    if (state === "online") this.statusTimer = window.setTimeout(() => this.status.classList.add("faded"), 2500);
  }

  /** Une phrase brève en haut de l'écran (un refus du noyau, un rappel). */
  toast(message: string): void {
    if (!message) return;
    const t = el("div", "world-toast");
    t.textContent = message;
    this.top.appendChild(t);
    window.setTimeout(() => t.remove(), TOAST_MS);
  }

  // ── viser, agir ───────────────────────────────────────────────────

  private wirePointer(): void {
    const canvas = this.deps.canvas;
    canvas.addEventListener("pointermove", (e) => {
      this.lastMove = { x: e.clientX, y: e.clientY };
      this.scheduleHover();
    });
    canvas.addEventListener("pointerleave", () => {
      this.lastMove = null;
      this.showTag(null, 0, 0);
    });
    canvas.addEventListener("pointerdown", (e) => {
      this.closeMenu();
      if (e.button === 0) this.down = { x: e.clientX, y: e.clientY, at: performance.now() };
    });
    canvas.addEventListener("pointerup", (e) => {
      const d = this.down;
      this.down = null;
      if (e.button !== 0 || !d) return;
      const moved = Math.hypot(e.clientX - d.x, e.clientY - d.y);
      if (moved > CLICK_SLOP_PX || performance.now() - d.at > CLICK_MAX_MS) return;
      const at = { x: e.clientX, y: e.clientY };
      if (this.clickTimer !== null) window.clearTimeout(this.clickTimer);
      this.clickTimer = window.setTimeout(() => {
        this.clickTimer = null;
        this.openAt(at.x, at.y, false);
      }, DOUBLE_CLICK_MS);
    });
    canvas.addEventListener("dblclick", () => {
      if (this.clickTimer !== null) window.clearTimeout(this.clickTimer);
      this.clickTimer = null;
    });
    canvas.addEventListener("contextmenu", (e) => {
      // OrbitControls empêche déjà le menu du navigateur sur la scène.
      e.preventDefault();
      this.openAt(e.clientX, e.clientY, true);
    });
    document.addEventListener("pointerdown", (e) => {
      if (!this.menu.hidden && !this.menu.contains(e.target as Node) && e.target !== canvas) this.closeMenu();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeMenu();
    });
  }

  private scheduleHover(): void {
    if (this.hoverTimer !== null) return;
    const wait = Math.max(0, HOVER_EVERY_MS - (performance.now() - this.hoverAt));
    this.hoverTimer = window.setTimeout(() => {
      this.hoverTimer = null;
      this.hoverAt = performance.now();
      const at = this.lastMove;
      if (!at || this.down || !this.menu.hidden) {
        this.showTag(null, 0, 0);
        return;
      }
      const focus = this.focusAt(at.x, at.y);
      this.showTag(focus, at.x, at.y);
    }, wait);
  }

  private focusAt(x: number, y: number): Focus | null {
    const rect = this.deps.canvas.getBoundingClientRect();
    this.pointer.set(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.deps.camera);
    return this.deps.stage.pick(this.raycaster);
  }

  private optionsFor(focus: Focus | null): ActionOption[] {
    const { session } = this.deps;
    const mirror = session.mirror;
    if (!mirror.ready) return [];
    if (!focus) return forSelf(mirror, session.actor);
    return focus.kind === "object" ? forObject(mirror, session.actor, focus.id) : forActor(mirror, session.actor, focus.id);
  }

  private showTag(focus: Focus | null, x: number, y: number): void {
    const options = focus ? this.optionsFor(focus) : [];
    const canvas = this.deps.canvas;
    if (!focus || options.length === 0) {
      this.tag.hidden = true;
      canvas.style.cursor = "";
      return;
    }
    const primary = options.find((o) => o.primary) ?? options[0];
    this.tag.replaceChildren(document.createTextNode(focus.label));
    const hint = el("small", undefined, this.tag);
    hint.textContent = `clic · ${primary.label}${options.length > 1 ? " et plus" : ""}`;
    const rect = this.deps.parent.getBoundingClientRect();
    this.tag.style.left = `${x - rect.left}px`;
    this.tag.style.top = `${y - rect.top}px`;
    this.tag.hidden = false;
    canvas.style.cursor = "pointer";
  }

  private openAt(x: number, y: number, allowSelf: boolean): void {
    const focus = this.focusAt(x, y);
    if (!focus && !allowSelf) return;
    const options = this.optionsFor(focus);
    if (options.length === 0) return;
    this.showTag(null, 0, 0);
    this.menu.replaceChildren();
    const title = el("div", "world-menu-title", this.menu);
    title.textContent = focus ? focus.label : "Toi";
    for (const option of options) {
      const b = button(option.label, this.menu, () => {
        this.closeMenu();
        void this.execute(option);
      });
      if (option.primary) b.classList.add("primary");
    }
    const rect = this.deps.parent.getBoundingClientRect();
    this.menu.hidden = false;
    const w = this.menu.offsetWidth;
    const h = this.menu.offsetHeight;
    this.menu.style.left = `${Math.min(Math.max(8, x - rect.left), rect.width - w - 8)}px`;
    this.menu.style.top = `${Math.min(Math.max(8, y - rect.top), rect.height - h - 8)}px`;
    (this.menu.querySelector("button") as HTMLButtonElement | null)?.focus({ preventScroll: true });
  }

  private closeMenu(): void {
    this.menu.hidden = true;
  }

  /** Envoie la commande d'une option ; un refus du noyau revient en phrase. */
  async execute(option: ActionOption): Promise<Result> {
    const { session } = this.deps;
    const command = option.command.type === "act" ? { ...option.command, expect: session.mirror.seq } : option.command;
    const result = await session.command(command);
    if (result.status === "refused") this.toast(result.message || `Refusé (${result.code ?? "inconnu"})`);
    return result;
  }

  // ── les demandes de Mika ──────────────────────────────────────────

  private onRequest(r: Request): void {
    const { session } = this.deps;
    if (r.to_actor !== session.actor) return;
    this.pending = r;
    const stage = this.deps.stage;
    const who = stage.labelOf("actor", r.from_actor);
    const what = r.object ? stage.labelOf("object", r.object) : "";
    const where = r.place ? (session.mirror.world?.place(r.place)?.label ?? r.place) : "";
    const text: Record<string, string> = {
      offer: `${who} te tend ${what}.`,
      ask: `${who} te demande ${what}.`,
      hug: `${who} voudrait un câlin.`,
      high_five: `${who} lève la main : tope là ?`,
      hold_hand: `${who} te tend la main.`,
      invite: `${who} t'invite à la rejoindre (${where}).`,
    };
    this.requestText.textContent = text[r.kind] ?? `${who} te demande quelque chose.`;
    this.requestBox.hidden = false;
  }

  private async answer(accept: boolean): Promise<void> {
    const r = this.pending;
    this.hideRequest();
    if (!r) return;
    const result = await this.deps.session.command({ type: "answer", request: r.id, accept });
    if (result.status === "refused") this.toast(result.message || "Réponse refusée.");
  }

  private hideRequest(): void {
    this.pending = null;
    this.requestBox.hidden = true;
  }
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, parent?: HTMLElement): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  parent?.appendChild(e);
  return e;
}

function button(label: string, parent: HTMLElement, onClick: () => void): HTMLButtonElement {
  const b = el("button", "world-button", parent);
  b.type = "button";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}
