/**
 * Où elle en est d'une réponse qu'elle prépare (ADR 0306) : la ligne au-dessus de la saisie, dans Teams et dans Mail.
 * Une seule ligne — l'étape (elle s'y met, elle réfléchit, tel outil tourne) et son chrono, qui court entre deux
 * étapes (`tickWork`). Le moteur la dit dans `work` (`backendv2/docs/protocole-moi.md`) et pousse chaque étape qui
 * commence (`mail.work`, `teams.work`, ADR 0308) : l'écran relit alors `work` ; rien n'en est gardé.
 */
import { h } from "../shell/dom";
import { mikaAvatar } from "./face";

export type WorkStep = "waiting" | "thinking" | "tool";

export interface Work {
  /** `waiting` : demandée, pas encore commencée ; `thinking` : elle réfléchit ; `tool` : un de ses outils tourne. */
  step: WorkStep;
  /** Le libellé de l'outil (`tool`) ; vide sinon. */
  label: string;
  /** Le début de l'étape (ms). */
  since: number;
  /** Le début du travail (ms ; pour `waiting`, la demande). */
  started: number;
}

/** L'étape en mots : « Elle s'y met… », « Réflexion en cours… », « Relire une de tes conversations Teams… ». */
export function workText(w: Work): string {
  if (w.step === "tool") return `${(w.label || "Un de ses outils").replace(/[.…]+$/, "")}…`;
  if (w.step === "thinking") return "Réflexion en cours…";
  return "Elle s'y met…";
}

/** Un chrono : « 0:07 », « 1:30 », « 1:02:05 » (jamais négatif : une horloge un peu en avance donne 0:00). */
export function elapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const ss = String(s).padStart(2, "0");
  return hours ? `${hours}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** La ligne : son visage (ou `lead`, là où il est déjà à côté), l'étape et son chrono. `cls` : la classe de l'écran
 *  (`tm-asked`, `rd-asked`). À poser dans une case qui reste (`role="status"`) et qu'on remplit à chaque étape :
 *  l'étape se dit quand elle change, le chrono n'est pas lu à chaque seconde. */
export function workLine(w: Work, now: number, cls: string, lead: string = mikaAvatar("xs")): string {
  return `<div class="${cls} work-line">${lead}<span class="work-step">${h(workText(w))}</span><span class="work-clock" aria-hidden="true" data-work-since="${Math.trunc(w.since)}">${elapsed(now - w.since)}</span></div>`;
}

let ticker = 0;

/** Fait courir chaque chrono affiché, une fois par seconde, tant qu'il y en a un à l'écran ; s'arrête seul. Un
 *  affichage d'ici, sans rien relire : le seul `setInterval` des écrans (`tools/timers.test.ts`). */
export function tickWork(): void {
  if (ticker) return;
  ticker = window.setInterval(() => {
    const shown = document.querySelectorAll<HTMLElement>("[data-work-since]");
    if (!shown.length) {
      window.clearInterval(ticker);
      ticker = 0;
      return;
    }
    const now = Date.now();
    shown.forEach((el) => {
      el.textContent = elapsed(now - Number(el.dataset.workSince));
    });
  }, 1000);
}
