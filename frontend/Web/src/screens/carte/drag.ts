/**
 * Carte › un voyage : glisser un arrêt par sa poignée — la cible sous le pointeur (le jour, l'arrêt avant lequel il
 * tombe), son indice à l'écran, le suivi du pointeur sur le document. Tant qu'il glisse, l'écran ne se redessine pas
 * (`drag`, que le dessin du cadre consulte) ; tombé, il passe aux gestes de Voyages (`trip.ts`, par `DragHost`).
 */
import type { Trip } from "../../api/carte";
import { $, $$ } from "../../shell/dom";
import { dropIndex } from "./format";

/** Ce que le glisser demande au cadre, et par lui à Voyages. */
export interface DragHost {
  body(): HTMLElement | null;
  paint(): void;
  /** Un dessin a été demandé pendant qu'on glissait : fait quand l'arrêt tombe. */
  paintLater(): boolean;
  /** Le voyage ouvert tel qu'on le montre. */
  shownTrip(): Trip | null;
  /** L'arrêt tombé : déplacé à ce jour, à cet indice (un geste de Voyages). */
  moveTo(stop: string, day: number, index: number): void;
}

export class StopDrag {
  /** L'arrêt qu'on glisse, son pointeur et où il tomberait : le dessin attend qu'il tombe. */
  drag: { stop: string; pointer: number; target: { day: number; before: string | null } | null } | null = null;

  constructor(private readonly host: DragHost) {}

  /** Le jour et l'arrêt avant lequel tomberait l'arrêt glissé, sous le pointeur. */
  private dropTarget(x: number, y: number): { day: number; before: string | null } | null {
    const body = this.host.body();
    const under = document.elementFromPoint(x, y) as HTMLElement | null;
    const li = under?.closest<HTMLElement>("li.stop");
    if (li && body?.contains(li)) {
      const r = li.getBoundingClientRect();
      const day = Number(li.dataset.day);
      if (y < r.top + r.height / 2) return { day, before: li.dataset.stop ?? null };
      const next = li.nextElementSibling?.matches("li.leg") ? li.nextElementSibling.nextElementSibling : li.nextElementSibling;
      return { day, before: (next as HTMLElement | null)?.dataset?.stop ?? null };
    }
    const box = under?.closest<HTMLElement>("[data-day-box]");
    if (box && body?.contains(box)) return { day: Number(box.dataset.dayBox), before: null };
    return null;
  }

  private showDrop(target: { day: number; before: string | null } | null): void {
    const body = this.host.body();
    if (!body) return;
    for (const el of $$<HTMLElement>(".drop-before, .drop-end", body)) el.classList.remove("drop-before", "drop-end");
    if (!target) return;
    if (target.before) $<HTMLElement>(`li.stop[data-stop="${CSS.escape(target.before)}"]`, body)?.classList.add("drop-before");
    else $<HTMLElement>(`[data-day-list="${target.day}"]`, body)?.classList.add("drop-end");
  }

  /**
   * Glisser une poignée : suivi sur le document (le geste ne se perd pas si la poignée quitte la page), et l'écran ne
   * se redessine pas tant que l'arrêt n'est pas tombé (`paint` attend).
   */
  private startDrag(e: PointerEvent, grip: HTMLElement): void {
    const stop = grip.dataset.grip ?? "";
    if (!stop || e.button !== 0 || this.drag) return;
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    this.drag = { stop, pointer: e.pointerId, target: null };
    grip.closest("li.stop")?.classList.add("dragging");
    const move = (ev: PointerEvent) => {
      if (!this.drag || ev.pointerId !== this.drag.pointer) return;
      this.drag.target = this.dropTarget(ev.clientX, ev.clientY);
      this.showDrop(this.drag.target);
    };
    const end = (ev: PointerEvent) => {
      if (this.drag && ev.pointerId !== this.drag.pointer) return;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
      const drag = this.drag;
      this.drag = null;
      this.showDrop(null);
      const body = this.host.body();
      if (body) for (const el of $$<HTMLElement>("li.stop.dragging", body)) el.classList.remove("dragging");
      const trip = this.host.shownTrip();
      if (drag && ev.type === "pointerup" && drag.target && trip && drag.target.before !== drag.stop) {
        this.host.moveTo(drag.stop, drag.target.day, dropIndex(trip, drag.stop, drag.target.day, drag.target.before));
      } else if (this.host.paintLater()) {
        this.host.paint();
      }
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  }

  mount(section: HTMLElement): void {
    section.addEventListener("pointerdown", (e) => {
      const grip = (e.target as Element | null)?.closest?.("[data-grip]") as HTMLElement | null;
      if (grip && section.contains(grip)) this.startDrag(e, grip);
    });
  }
}
