/**
 * Projets, les couleurs d'état (pur) : les mêmes partout, comme dans la maquette — à toi (`you`, ambre), elle y
 * travaille (`work`, bleu), fait ou fusionné (`done`, vert), en échec ou refusé (`fail`, rouge), en attente (`wait`,
 * gris-bleu). Seule la couleur se choisit ici, depuis les codes du serveur : les mots sont les siens (`…_label`), et
 * « à toi » ne se dit que de ce qu'il dit attendre la personne (`yours`, `mine`, `ready`).
 */
import type { IconName } from "../../shell/icons";

export type Tone = "you" | "work" | "done" | "fail" | "wait";

export function projectTone(status: string): Tone {
  return status === "active" ? "work" : "wait";
}

export function objectiveTone(status: string): Tone {
  return status === "done" ? "done" : status === "blocked" ? "fail" : "work";
}

/** Un objectif sur la carte d'un projet (`card.objectives.states`) : fait, en cours, à venir, bloqué. */
export function progressTone(state: string): Tone {
  return state === "done" ? "done" : state === "blocked" ? "fail" : state === "doing" ? "work" : "wait";
}

/** Un jalon : atteint, retiré, prêt (à toi), refusé, commencé (`started` : elle s'y est mise), sinon à faire. */
export function milestoneTone(m: { status: string; ready: boolean; refused_at?: number; started?: boolean }): Tone {
  if (m.status === "reached") return "done";
  if (m.status === "dropped") return "wait";
  if (m.ready) return "you";
  if (m.refused_at) return "fail";
  return m.started ? "work" : "wait";
}

export function ticketTone(t: { status: string; open: boolean; yours: boolean }): Tone {
  if (t.status === "treated") return "done";
  if (!t.open) return "wait";
  if (t.yours) return "you";
  return t.status === "unread" || t.status === "proposed" ? "wait" : "work";
}

export function pullTone(state: string): Tone {
  return state === "merged" ? "done" : state === "ready" ? "you" : state === "open" ? "work" : "wait";
}

export function checksTone(state: string): Tone {
  return state === "passed" ? "done" : state === "failed" ? "fail" : state === "pending" ? "work" : "wait";
}

/** Le verdict d'une exécution : continuer (bleu), terminé (vert), bloqué (rouge), elle attend quelqu'un (ambre). */
export function runTone(r: { running: boolean; verdict: string; outcome?: string }): Tone {
  if (r.running) return "work";
  if (r.verdict === "done") return "done";
  if (r.verdict === "blocked") return "fail";
  if (r.verdict === "wait") return "you";
  return r.verdict === "continue" ? "work" : "wait";
}

export function askTone(status: string): Tone {
  return status === "treated" || status === "done" ? "done" : status === "dismissed" || status === "refused" ? "fail" : status === "proposed" || status === "unread" ? "wait" : "work";
}

/** L'icône d'une attente d'« À faire », d'après sa sorte (et ce qu'un ticket attend). */
export function waitingIcon(kind: string, what = ""): IconName {
  if (kind === "approval") return "shield-check";
  if (kind === "plan") return "p2-plan";
  if (kind === "need") return "p2-question";
  if (kind === "ticket") return what === "merge" ? "p2-merge" : what === "question" ? "p2-question" : what === "validation" ? "p2-plan" : "p2-ticket";
  if (kind === "checkpoint") return "p2-stop";
  if (kind === "item") return "p2-board";
  if (kind === "review") return "eye";
  return "alert";
}

/** L'icône d'un jalon, d'après sa couleur. */
export function milestoneIcon(tone: Tone): IconName {
  return tone === "done" ? "check" : tone === "you" ? "p2-stop" : tone === "work" ? "play" : tone === "fail" ? "x" : "minus";
}
