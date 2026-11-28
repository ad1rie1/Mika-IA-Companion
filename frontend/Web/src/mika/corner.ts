/**
 * Mika : un seul élément (`#mika-corner`), sa VRM ou son portrait, logé par l'écran — comme `coin` dans
 * maquette.js. Chez lui, c'est le rond de la pastille du haut (son visage, `mini`) ; un écran peut lui offrir
 * une scène plus grande en posant un `[data-mika-scene]` dans son corps (la colonne du chat : `large`).
 *
 * Un écran qui redessine son corps la gare d'abord (`park`), puis la reloge (`lodge`) : la scène qui
 * l'accueillait va disparaître, l'élément — et le contexte WebGL de sa VRM — survivent.
 */
import { $ } from "../shell/dom";
import { isDark, onTheme } from "../shell/theme";
import { availablePortraits, getManifest, portraitUrl, setCurrentPortrait } from "./face";
import { framePortrait, portraitOf } from "./portraits";
import type { MikaStore } from "./store";
import { AURAS, faceOf, type Face } from "./view";

export type CornerSize = "mini" | "large";

export class MikaCorner {
  readonly el: HTMLElement;
  readonly stage: HTMLElement;
  readonly canvas: HTMLCanvasElement;
  readonly live: HTMLElement;
  private readonly home: HTMLElement;
  private readonly img: HTMLImageElement;
  private readonly blink: HTMLImageElement;
  private scene: HTMLElement | null = null;
  private face: Face = { portrait: "neutral", aura: "neutre", asleep: false };
  private readonly sizeListeners = new Set<(size: CornerSize) => void>();
  private readonly faceListeners = new Set<(face: Face) => void>();

  constructor(store: MikaStore) {
    this.el = $("#mika-corner")!;
    this.home = this.el.parentElement!;
    this.stage = $("#mc-stage")!;
    this.canvas = $<HTMLCanvasElement>("#mc-canvas")!;
    this.live = $("#mc-live")!;
    this.img = $<HTMLImageElement>("#mc-portrait")!;
    this.blink = $<HTMLImageElement>("#mc-blink")!;
    this.img.addEventListener("error", () => {
      this.img.hidden = true;
    });
    this.img.addEventListener("load", () => {
      this.img.hidden = false;
    });
    store.subscribe((snap) => {
      const face = faceOf(snap.state, snap.typing, availablePortraits());
      const changed = face.portrait !== this.face.portrait || face.aura !== this.face.aura || face.asleep !== this.face.asleep;
      this.face = face;
      setCurrentPortrait(face.portrait);
      if (changed) {
        this.frame();
        for (const fn of this.faceListeners) fn(face);
      }
      const dots = $("#mc-typing");
      if (dots) dots.hidden = !snap.typing;
    });
    onTheme(() => this.frame());
    addEventListener("resize", () => {
      this.lodge(this.scene);
    });
    new ResizeObserver(() => this.frame()).observe(this.stage);
    this.blinks();
  }

  get size(): CornerSize {
    return this.el.dataset.size === "large" ? "large" : "mini";
  }

  get currentFace(): Face {
    return this.face;
  }

  onSize(fn: (size: CornerSize) => void): void {
    this.sizeListeners.add(fn);
  }

  onFace(fn: (face: Face) => void): void {
    this.faceListeners.add(fn);
    fn(this.face);
  }

  /** Retirée de la page le temps qu'un écran redessine son corps. */
  park(): void {
    if (this.el.parentElement && this.el.parentElement !== this.home) this.el.remove();
  }

  /** Dans la scène que l'écran offre, si elle se voit ; chez elle, dans la pastille, sinon. */
  lodge(scene: Element | null | undefined): void {
    this.scene = scene instanceof HTMLElement && document.contains(scene) ? scene : null;
    const visible = !!this.scene && this.scene.offsetParent !== null;
    const target = visible ? this.scene! : this.home;
    if (this.el.parentElement !== target) target.prepend(this.el);
    const size: CornerSize = visible ? "large" : "mini";
    const changed = this.el.dataset.size !== size;
    this.el.dataset.size = size;
    document.body.classList.toggle("mika-en-grand", visible);
    this.frame();
    if (changed) for (const fn of this.sizeListeners) fn(size);
  }

  /** Le portrait : le visage à 36 % de la hauteur, le clignement posé pile sur les yeux ; l'aura de l'humeur. */
  frame(): void {
    const aura = AURAS[this.face.aura];
    this.el.style.setProperty("--mood", aura[isDark() ? 1 : 0]);
    const manifest = getManifest();
    const p = portraitOf(manifest, this.face.portrait);
    const W = this.stage.clientWidth;
    const H = this.stage.clientHeight;
    if (!manifest || !p || !W || !H) return;
    const { image, blink } = framePortrait({ width: W, height: H }, this.size === "mini", p, manifest);
    const src = portraitUrl(p.file);
    if (this.img.getAttribute("src") !== src) this.img.setAttribute("src", src);
    Object.assign(this.img.style, {
      height: `${image.height}px`,
      left: `${image.left}px`,
      top: `${image.top}px`,
      transform: "none",
    });
    if (blink && p.blink) {
      const bsrc = portraitUrl(p.blink.file);
      if (this.blink.getAttribute("src") !== bsrc) this.blink.setAttribute("src", bsrc);
      Object.assign(this.blink.style, {
        height: `${blink.height}px`,
        width: `${blink.width}px`,
        left: `${blink.left}px`,
        top: `${blink.top}px`,
        transform: "none",
      });
      this.blink.dataset.ready = "1";
    } else {
      this.blink.dataset.ready = "";
      this.blink.hidden = true;
    }
  }

  /** Ses clignements, le temps que la VRM ne la porte pas : 130 ms, toutes les 2,6 à 6,2 s. */
  private blinks(): void {
    const once = () => {
      const vrm = this.el.classList.contains("vrm-on");
      if (this.blink.dataset.ready === "1" && !this.face.asleep && !vrm && !document.hidden) {
        this.blink.hidden = false;
        window.setTimeout(() => {
          this.blink.hidden = true;
        }, 130);
      }
      window.setTimeout(once, 2600 + Math.random() * 3600);
    };
    window.setTimeout(once, 1800);
  }

  /** Ce que la VRM, une fois chargée, montre à la place du portrait. */
  vrmReady(on: boolean): void {
    this.el.classList.toggle("vrm-on", on);
    this.canvas.hidden = !on;
  }
}
