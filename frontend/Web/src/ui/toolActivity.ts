/**
 * La carte de travail d'une réponse pro (ADR 0116) : ses outils en direct,
 * pendant qu'elle travaille, comme dans Claude Code.
 *
 * Le serveur envoie une trame `tool` à chaque pas — un outil part (`start`),
 * il a fini (`end`), ce qu'elle écrit entre deux appels (`note`), l'épisode est
 * fini (`done`). Ces trames ne sont jamais gardées par le serveur ni dans
 * l'historique : la carte vit **en mémoire seulement** et ne survit pas à un
 * rechargement (l'historique montre alors la ligne des `tools`).
 *
 * Fonctions pures, à part du DOM comme `chatSync.ts` et `approvals.ts` : la
 * validation d'une trame, la fusion par `reply_to` et `episode`, les libellés
 * français (« 4 outils · 3,2 s »), et où poser chaque carte dans le fil.
 * ChatOverlay ne fait que peindre. Arguments et résultats restent du texte
 * brut : rien ici ne les interprète, et la carte les pose en `textContent`.
 */

import type { ToolMessage, ToolUse } from "../types";

/** Au-delà, la plus ancienne carte est oubliée : ce ne sont que des traces du moment. */
export const MAX_CARDS = 20;
/** Les pas d'une carte, bornés : une boucle d'outils emballée ne remplit pas l'onglet. */
export const MAX_STEPS = 200;
/** Le serveur borne arguments et résultats à ~2 000 caractères ; on garde de la marge. */
export const MAX_DETAIL_CHARS = 4000;
const MAX_NAME_CHARS = 200;
const MAX_ID_CHARS = 200;
const MAX_NOTE_CHARS = 2000;
const MAX_OUTCOME_CHARS = 64;
/** Les outils d'une ligne d'historique (une réponse n'en appelle pas des centaines). */
export const MAX_TOOL_USES = 100;

/** Une trame `tool` validée : chaque champ du bon type, ou un défaut sûr. */
export type ToolFrame =
  | ToolFrameBase & { phase: "start"; callId: string; name: string; args: string }
  | ToolFrameBase & {
      phase: "end";
      callId: string;
      name: string;
      args: string;
      ok: boolean;
      result: string;
      durationMs: number | null;
    }
  | ToolFrameBase & { phase: "note"; text: string }
  | ToolFrameBase & { phase: "done"; outcome: string };

interface ToolFrameBase {
  episode: string;
  replyTo: number | null;
  /** Millisecondes Unix ; `null` si la trame ne la portait pas. */
  at: number | null;
}

/** `running` : parti ; `ok` / `failed` : fini ; `stopped` : l'épisode a fini sans que l'outil ne dise sa fin. */
export type ToolStatus = "running" | "ok" | "failed" | "stopped";

export interface ToolStep {
  kind: "tool";
  /** `épisode|call_id` : unique dans la carte. */
  key: string;
  name: string;
  args: string;
  status: ToolStatus;
  result: string;
  durationMs: number | null;
  /** Le `at` de son départ, pour une durée que la trame de fin ne dirait pas. */
  startedAt: number | null;
}

export interface NoteStep {
  kind: "note";
  key: string;
  text: string;
}

/** Un épisode fini autrement que par sa réponse (supplanté, échec, délai…). */
export interface EndStep {
  kind: "end";
  key: string;
  outcome: string;
}

export type WorkStep = ToolStep | NoteStep | EndStep;

export interface WorkCard {
  /** `r:<reply_to>`, ou `e:<episode>` quand la trame ne dit pas à quoi elle répond. */
  key: string;
  replyTo: number | null;
  steps: WorkStep[];
  /** Les épisodes vus, et leur issue (`null` : en cours). Copié à chaque trame, jamais muté. */
  episodes: Record<string, string | null>;
  /** Le `at` de la première trame, de la dernière, et du dernier `done`. */
  startedAt: number | null;
  lastAt: number | null;
  endedAt: number | null;
  /** Sa réponse pro est arrivée (`speech` au même `user_message_id`) : la carte se replie. */
  answered: boolean;
  /** L'`id` de cette réponse, quand elle en a un : la carte se pose juste au-dessus. */
  answerId: number | null;
}

/** Une chaîne non vide coupée à `max`, ou `fallback`. */
function text(value: unknown, max: number, fallback = ""): string {
  return typeof value === "string" ? value.slice(0, max) : fallback;
}

/**
 * Une trame telle que le serveur l'envoie, validée — ou `null` si elle ne
 * vaut rien : pas une trame `tool`, phase inconnue, épisode absent, `reply_to`
 * qui n'est ni un entier > 0 ni `null`, outil sans `call_id`, note vide.
 */
export function toolFrame(raw: unknown): ToolFrame | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Partial<Record<keyof ToolMessage, unknown>>;
  if (r.type !== "tool") return null;
  const episode = text(r.episode, MAX_ID_CHARS);
  if (!episode) return null;
  let replyTo: number | null = null;
  if (r.reply_to !== undefined && r.reply_to !== null) {
    if (typeof r.reply_to !== "number" || !Number.isSafeInteger(r.reply_to) || r.reply_to <= 0) {
      return null;
    }
    replyTo = r.reply_to;
  }
  const at = typeof r.at === "number" && Number.isFinite(r.at) && r.at > 0 ? r.at : null;
  const base = { episode, replyTo, at };
  switch (r.phase) {
    case "start":
    case "end": {
      const callId = text(r.call_id, MAX_ID_CHARS);
      if (!callId) return null;
      const name = text(r.name, MAX_NAME_CHARS).trim() || "outil";
      const args = text(r.args, MAX_DETAIL_CHARS);
      if (r.phase === "start") return { ...base, phase: "start", callId, name, args };
      const duration = r.duration_ms;
      return {
        ...base,
        phase: "end",
        callId,
        name,
        args,
        ok: r.ok === true,
        result: text(r.result, MAX_DETAIL_CHARS),
        durationMs:
          typeof duration === "number" && Number.isFinite(duration) && duration >= 0 ? duration : null,
      };
    }
    case "note": {
      const note = text(r.text, MAX_NOTE_CHARS).trim();
      return note ? { ...base, phase: "note", text: note } : null;
    }
    case "done":
      return { ...base, phase: "done", outcome: text(r.outcome, MAX_OUTCOME_CHARS).trim() || "done" };
    default:
      return null;
  }
}

/** La carte d'une trame : par `reply_to`, ou par épisode quand il manque. */
export function cardKey(frame: Pick<ToolFrame, "replyTo" | "episode">): string {
  return frame.replyTo !== null ? `r:${frame.replyTo}` : `e:${frame.episode}`;
}

function laterOf(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.max(a, b);
}

/**
 * Fusionne une trame dans les cartes, sans rien muter : une carte neuve à la
 * première trame d'un `reply_to` (en bas de la liste), sinon la sienne mise à
 * jour. Dans une carte, un outil se reconnaît à son épisode et son `call_id` ;
 * un `end` sans `start` crée sa ligne. Un `done` arrête ce qui tournait encore
 * dans son épisode ; un nouvel épisode pour le même `reply_to` (après une
 * réponse supplantée) relance la même carte.
 */
export function withToolFrame(cards: readonly WorkCard[], frame: ToolFrame): WorkCard[] {
  const key = cardKey(frame);
  const index = cards.findIndex((c) => c.key === key);
  const old: WorkCard =
    index >= 0
      ? cards[index]
      : {
          key,
          replyTo: frame.replyTo,
          steps: [],
          episodes: {},
          startedAt: frame.at,
          lastAt: frame.at,
          endedAt: null,
          answered: false,
          answerId: null,
        };
  const card: WorkCard = {
    ...old,
    steps: [...old.steps],
    episodes: { ...old.episodes },
    startedAt: old.startedAt ?? frame.at,
    lastAt: laterOf(old.lastAt, frame.at),
  };
  if (!(frame.episode in card.episodes)) card.episodes[frame.episode] = null;
  applyFrame(card, frame);
  if (card.steps.length > MAX_STEPS) card.steps = card.steps.slice(-MAX_STEPS);

  if (index >= 0) {
    const next = [...cards];
    next[index] = card;
    return next;
  }
  const next = [...cards, card];
  return next.length > MAX_CARDS ? next.slice(-MAX_CARDS) : next;
}

/** Le pas d'une trame, sur une carte déjà copiée (et à elle seule). */
function applyFrame(card: WorkCard, frame: ToolFrame): void {
  const steps = card.steps;
  switch (frame.phase) {
    case "start": {
      const key = `${frame.episode}|${frame.callId}`;
      const at = steps.findIndex((s) => s.kind === "tool" && s.key === key);
      if (at >= 0) {
        // un départ redit (ou arrivé après sa fin) : il complète, sans défaire la fin
        const step = steps[at] as ToolStep;
        steps[at] = { ...step, name: frame.name, args: step.args || frame.args, startedAt: step.startedAt ?? frame.at };
      } else {
        steps.push({
          kind: "tool",
          key,
          name: frame.name,
          args: frame.args,
          status: "running",
          result: "",
          durationMs: null,
          startedAt: frame.at,
        });
      }
      return;
    }
    case "end": {
      const key = `${frame.episode}|${frame.callId}`;
      const at = steps.findIndex((s) => s.kind === "tool" && s.key === key);
      const before = at >= 0 ? (steps[at] as ToolStep) : null;
      const measured =
        before?.startedAt != null && frame.at !== null ? Math.max(0, frame.at - before.startedAt) : null;
      const step: ToolStep = {
        kind: "tool",
        key,
        name: frame.name,
        args: frame.args || before?.args || "",
        status: frame.ok ? "ok" : "failed",
        result: frame.result,
        durationMs: frame.durationMs ?? measured,
        startedAt: before?.startedAt ?? null,
      };
      if (at >= 0) steps[at] = step;
      else steps.push(step);
      return;
    }
    case "note":
      steps.push({ kind: "note", key: `${frame.episode}|n${steps.length}`, text: frame.text });
      return;
    case "done": {
      card.episodes[frame.episode] = frame.outcome;
      card.endedAt = laterOf(card.endedAt, frame.at);
      // plus rien ne tourne dans cet épisode
      for (let i = 0; i < steps.length; i++) {
        const s = steps[i];
        if (s.kind === "tool" && s.status === "running" && s.key.startsWith(`${frame.episode}|`)) {
          steps[i] = { ...s, status: "stopped" };
        }
      }
      if (frame.outcome !== "done") {
        steps.push({ kind: "end", key: `${frame.episode}|end`, outcome: frame.outcome });
      }
      return;
    }
  }
}

/**
 * Sa réponse pro est arrivée : la carte de ce message se replie, juste
 * au-dessus de la bulle (`messageId`). Sans `user_message_id`, c'est la
 * dernière carte sans `reply_to` encore sans réponse. Rien à replier : les
 * mêmes cartes.
 */
export function withAnswer(
  cards: readonly WorkCard[],
  userMessageId: number | null,
  messageId: number | null
): readonly WorkCard[] {
  let index = -1;
  if (userMessageId !== null) {
    index = cards.findIndex((c) => c.key === `r:${userMessageId}`);
  } else {
    for (let i = cards.length - 1; i >= 0; i--) {
      if (cards[i].replyTo === null && !cards[i].answered) {
        index = i;
        break;
      }
    }
  }
  if (index < 0) return cards;
  const next = [...cards];
  next[index] = { ...cards[index], answered: true, answerId: messageId };
  return next;
}

/** Un épisode de la carte travaille-t-il encore ? */
export function isRunning(card: WorkCard): boolean {
  return Object.values(card.episodes).some((outcome) => outcome === null);
}

export function toolSteps(card: WorkCard): ToolStep[] {
  return card.steps.filter((s): s is ToolStep => s.kind === "tool");
}

/** « 182 ms », « 3,2 s », « 42 s », « 2 min 05 s ». */
export function durationLabel(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 10) return `${s.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
  if (s < 60) return `${Math.round(s)} s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)} min ${String(whole % 60).padStart(2, "0")} s`;
}

function count(n: number, one: string, many: string): string {
  return n === 0 ? `aucun ${one}` : `${n} ${n > 1 ? many : one}`;
}

/** Le temps qu'a duré le travail, de la première trame au dernier `done` (ou à la dernière trame). */
export function cardDurationMs(card: WorkCard): number | null {
  const end = card.endedAt ?? card.lastAt;
  if (card.startedAt === null || end === null || end < card.startedAt) return null;
  return end - card.startedAt;
}

/** Le résumé d'une carte repliée : « 4 outils · 3,2 s », les échecs dits s'il y en a. */
export function cardSummary(card: WorkCard): string {
  const tools = toolSteps(card);
  const parts = [count(tools.length, "outil", "outils")];
  const failed = tools.filter((t) => t.status === "failed").length;
  if (failed) parts.push(count(failed, "échec", "échecs"));
  const ms = cardDurationMs(card);
  if (ms !== null) parts.push(durationLabel(ms));
  return parts.join(" · ");
}

/** Ce que dit l'en-tête d'une carte qui travaille encore. */
export function runningLabel(card: WorkCard): string {
  const n = toolSteps(card).length;
  return n ? `Au travail… · ${count(n, "outil", "outils")}` : "Au travail…";
}

const OUTCOMES: Record<string, string> = {
  failed: "le travail a échoué",
  timeout: "délai dépassé",
  abstained: "elle a choisi de ne pas répondre",
  superseded: "remplacé par une nouvelle réponse",
  preempted: "interrompu par un message plus récent",
  cancelled: "annulé",
  interrupted: "interrompu",
};

/** L'issue d'un épisode fini autrement que par sa réponse, en français (`""` pour `done`). */
export function outcomeLabel(outcome: string): string {
  if (!outcome || outcome === "done") return "";
  return OUTCOMES[outcome] ?? `fini : ${outcome}`;
}

/**
 * Un aperçu court des arguments, sur la ligne de l'outil : les valeurs d'un
 * objet JSON (« anniversaire de Léa »), `clé=valeur` s'il y en a plusieurs ;
 * sinon le texte tel quel, sur une ligne. Toujours du texte brut.
 */
export function argsPreview(args: string, max = 60): string {
  let preview = args;
  try {
    const parsed: unknown = JSON.parse(args);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const entries = Object.entries(parsed as Record<string, unknown>);
      const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v) ?? "");
      preview =
        entries.length === 1
          ? show(entries[0][1])
          : entries.map(([k, v]) => `${k}=${show(v)}`).join(", ");
    } else if (typeof parsed === "string") {
      preview = parsed;
    }
  } catch {
    // pas du JSON (ou coupé par la borne du serveur) : le texte tel quel
  }
  const line = preview.replace(/\s+/g, " ").trim();
  return line.length > max ? `${line.slice(0, max - 1)}…` : line;
}

/**
 * Les outils d'une ligne d'historique, validés : un nom non vide, `ok` vrai
 * seulement s'il l'est vraiment. Ce qui n'est pas un tableau vaut une liste vide.
 */
export function toolUses(raw: unknown): ToolUse[] {
  if (!Array.isArray(raw)) return [];
  const out: ToolUse[] = [];
  for (const item of raw as Array<Partial<ToolUse> | null>) {
    if (!item || typeof item !== "object") continue;
    const name = text(item.name, MAX_NAME_CHARS).trim();
    if (!name) continue;
    out.push({ name, ok: item.ok === true });
    if (out.length >= MAX_TOOL_USES) break;
  }
  return out;
}

export function sameToolUses(a: readonly ToolUse[] | undefined, b: readonly ToolUse[] | undefined): boolean {
  const x = a ?? [];
  const y = b ?? [];
  return x.length === y.length && x.every((t, i) => t.name === y[i].name && t.ok === y[i].ok);
}

/** La ligne discrète sous une réponse pro relue : « outils : email_search ✓ · email_read ✗ » (`""` sans outil). */
export function toolsLine(tools: readonly ToolUse[] | undefined): string {
  if (!tools?.length) return "";
  return `outils : ${tools.map((t) => `${t.name} ${t.ok ? "✓" : "✗"}`).join(" · ")}`;
}

// ── Où poser les cartes dans le fil ───────────────────────────────────

/** Ce qu'il faut d'un message du fil pour y placer une carte. */
export interface Placeable {
  id?: number;
  sender: "user" | "vtuber";
  inner?: boolean;
  mode?: "pro";
}

/**
 * Où peindre une carte : juste **avant** une bulle (sa réponse : la carte est
 * repliée), juste **après** le message de la personne (elle travaille encore,
 * ou n'a rien dit), ou en **bas** du fil (le message de la personne n'a pas
 * encore son identifiant — il ne le reçoit qu'avec la réponse).
 */
export type Placement =
  | { key: string; where: "before" | "after"; index: number; collapsed: boolean }
  | { key: string; where: "end"; index: -1; collapsed: boolean };

/**
 * Place chaque carte, dans l'ordre des cartes :
 *  1. sa réponse est arrivée avec un identifiant présent dans le fil → avant
 *     elle, repliée ;
 *  2. le message de la personne est dans le fil → avant la réponse pro qui le
 *     suit (repliée : arrivée par un rattrapage), sinon juste après lui ;
 *  3. sinon, en bas.
 */
export function placeCards(history: readonly Placeable[], cards: readonly WorkCard[]): Placement[] {
  return cards.map((card): Placement => {
    if (card.answerId !== null) {
      const index = history.findIndex((m) => m.id === card.answerId);
      if (index >= 0) return { key: card.key, where: "before", index, collapsed: true };
    }
    if (card.replyTo !== null) {
      const asked = history.findIndex((m) => m.sender === "user" && m.id === card.replyTo);
      if (asked >= 0) {
        for (let i = asked + 1; i < history.length; i++) {
          const m = history[i];
          if (m.sender !== "vtuber" || m.inner) continue;
          if (card.answered || m.mode === "pro") {
            return { key: card.key, where: "before", index: i, collapsed: true };
          }
          break;
        }
        return { key: card.key, where: "after", index: asked, collapsed: false };
      }
    }
    return { key: card.key, where: "end", index: -1, collapsed: false };
  });
}
