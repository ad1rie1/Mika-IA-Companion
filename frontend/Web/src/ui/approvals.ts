/**
 * Les cartes d'accord — ce qui attend la décision de la personne à qui Mika
 * parle (backendv2, ADR 0064 ; `docs/protocole-chat.md` §3 et §4).
 *
 * Elle a demandé à appeler un outil d'un service extérieur, et l'appel attend
 * l'accord de la personne. Seul le bouton compte : un « oui » tapé dans le
 * chat n'est jamais un accord, et la trame de décision porte l'empreinte de
 * ce qui était affiché — le serveur refuse un accord sur autre chose.
 *
 * Fonctions pures, à part du DOM comme `chatSync.ts` : la validation d'une
 * trame venue du serveur, la trame de décision, les libellés français, et
 * l'état de la bande (cartes, décisions parties, connexion) que ChatOverlay
 * ne fait que peindre.
 */

import type {
  ApprovalCard,
  ApprovalDecision,
  ApprovalFrame,
  ConnectionEvent,
} from "../types";

/** Au-delà, une liste est tronquée : une bande d'accords n'est pas un fil. */
export const MAX_CARDS = 50;
/** Les bornes du serveur (`app/mindport.py::approval_cards`). */
export const MAX_TITLE_CHARS = 400;
export const MAX_TEXT_CHARS = 4000;
export const MAX_BLOCKED_CHARS = 400;
/** Une empreinte : hexadécimal minuscule, vide permis (rien n'a pu être montré). */
const DIGEST = /^[0-9a-f]{0,128}$/;
const MAX_STATUS_CHARS = 32;
/** Le rafraîchissement des échéances (« expire dans 4 min »). */
export const REFRESH_MS = 30_000;

/** Le titre d'une carte qui n'en porte pas (le même que le serveur). */
export const DEFAULT_TITLE = "Une demande d'accord";
/**
 * Un texte plus long que ce qu'on montre ne peut pas être accepté : on
 * n'accepte pas ce qu'on n'a pas pu lire en entier. La carte devient
 * « bloquée » de ce côté-ci — seul le refus reste possible.
 */
export const TEXT_TOO_LONG =
  "trop long pour être montré en entier ici — on ne l'accepte pas sans l'avoir lu";
export const UNSHOWN =
  "Ce qui partirait ne peut pas être montré : seul le refus est possible.";
export const EXPIRED = "Expirée : on ne peut plus l'accepter.";

/** `""` pour une valeur absente, `null` pour une valeur du mauvais type. */
function optionalString(value: unknown): string | null {
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : null;
}

/** Coupe à `max` caractères, en le disant (« … »). */
function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * Une carte telle que la trame la porte, validée — ou `null` si elle ne vaut
 * rien : identifiant qui n'est pas un entier > 0, champ du mauvais type,
 * empreinte qui n'est pas de l'hexadécimal, échéance qui n'est ni un nombre ni
 * `null`. L'empreinte est gardée telle quelle : c'est elle qui repart.
 */
export function approvalCard(raw: unknown): ApprovalCard | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  const id = r.id;
  if (typeof id !== "number" || !Number.isSafeInteger(id) || id <= 0) return null;
  const title = optionalString(r.title);
  const text = optionalString(r.text);
  const digest = optionalString(r.digest);
  const blocked = optionalString(r.blocked);
  if (title === null || text === null || digest === null || blocked === null) return null;
  if (!DIGEST.test(digest)) return null;
  let expires_at: number | null = null;
  if (r.expires_at !== undefined && r.expires_at !== null) {
    if (typeof r.expires_at !== "number" || !Number.isFinite(r.expires_at) || r.expires_at <= 0) {
      return null;
    }
    expires_at = r.expires_at;
  }
  let shownText = text;
  let shownBlocked = clip(blocked.trim(), MAX_BLOCKED_CHARS);
  if (text.length > MAX_TEXT_CHARS) {
    shownText = `${text.slice(0, MAX_TEXT_CHARS)}\n…`;
    if (!shownBlocked) shownBlocked = TEXT_TOO_LONG;
  }
  return {
    id,
    title: clip(title.trim(), MAX_TITLE_CHARS) || DEFAULT_TITLE,
    text: shownText,
    digest,
    blocked: shownBlocked,
    expires_at,
  };
}

/**
 * La liste d'une trame `approvals`, validée : les cartes invalides sont
 * écartées, un identifiant répété ne compte qu'une fois (la première), et
 * tout ce qui n'est pas un tableau vaut une liste vide.
 */
export function approvalCards(items: unknown): ApprovalCard[] {
  if (!Array.isArray(items)) return [];
  const seen = new Set<number>();
  const cards: ApprovalCard[] = [];
  for (const item of items) {
    const card = approvalCard(item);
    if (!card || seen.has(card.id)) continue;
    seen.add(card.id);
    cards.push(card);
    if (cards.length >= MAX_CARDS) break;
  }
  return cards;
}

/** Deux cartes identiques champ à champ : la vue affichée peut être gardée. */
export function sameCard(a: ApprovalCard, b: ApprovalCard): boolean {
  return (
    a.id === b.id &&
    a.title === b.title &&
    a.text === b.text &&
    a.digest === b.digest &&
    a.blocked === b.blocked &&
    a.expires_at === b.expires_at
  );
}

/** La trame de décision, avec l'empreinte de la carte **affichée**. */
export function approvalFrame(card: ApprovalCard, decision: ApprovalDecision): ApprovalFrame {
  return { type: "approval", id: card.id, decision, digest: card.digest };
}

export function isExpired(card: ApprovalCard, nowMs: number): boolean {
  return card.expires_at !== null && nowMs >= card.expires_at;
}

/**
 * Pourquoi « Accepter » est impossible, en une phrase française — `""` quand
 * il l'est. Bloquée par le serveur, rien de montrable (pas de texte ou pas
 * d'empreinte : le serveur refuserait un accord sans empreinte), ou expirée.
 */
export function acceptRefusal(card: ApprovalCard, nowMs: number): string {
  if (card.blocked) return `Ne peut pas partir tel quel — ${card.blocked}`;
  if (!card.text || !card.digest) return UNSHOWN;
  if (isExpired(card, nowMs)) return EXPIRED;
  return "";
}

export function canAccept(card: ApprovalCard, nowMs: number): boolean {
  return acceptRefusal(card, nowMs) === "";
}

/**
 * L'échéance en mots : « expire dans 4 min », « expire dans 1 h 30 »,
 * « expirée » ; `""` pour une carte sans échéance. Les minutes sont
 * arrondies au-dessus : à 3 min 10 s, il reste bien « 4 min » entamées.
 */
export function expiryLabel(card: ApprovalCard, nowMs: number): string {
  if (card.expires_at === null) return "";
  const remaining = card.expires_at - nowMs;
  if (remaining <= 0) return "expirée";
  if (remaining < 60_000) return "expire dans moins d'une minute";
  const minutes = Math.ceil(remaining / 60_000);
  if (minutes < 60) return `expire dans ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest ? `expire dans ${hours} h ${String(rest).padStart(2, "0")}` : `expire dans ${hours} h`;
  }
  const days = Math.floor(hours / 24);
  return `expire dans ${days} jour${days > 1 ? "s" : ""}`;
}

/**
 * Dans combien de temps repeindre les échéances : toutes les 30 s, plus tôt
 * si une carte expire avant (son bouton « Accepter » doit s'éteindre à
 * l'heure). `null` : aucune échéance à venir, aucun minuteur à armer.
 */
export function nextRefreshDelay(cards: readonly ApprovalCard[], nowMs: number): number | null {
  let soonest = Infinity;
  for (const card of cards) {
    if (card.expires_at !== null && card.expires_at > nowMs) {
      soonest = Math.min(soonest, card.expires_at - nowMs);
    }
  }
  if (soonest === Infinity) return null;
  // une marge : repeindre *après* l'échéance, pas une milliseconde avant
  return Math.min(REFRESH_MS, soonest + 20);
}

// ── Le sort d'une décision ──────────────────────────────────────────

const RESULT_MESSAGES: Record<string, string> = {
  approved: "Accepté — l'appel peut partir.",
  rejected: "Refusé — rien ne partira.",
  unknown: "Cette demande n'attend plus rien (déjà décidée, ou inconnue).",
  changed: "Ce qui partirait a changé — relis la carte avant de décider.",
  blocked: "Cette demande ne peut pas partir telle quelle.",
  expired: "Trop tard : cette demande a expiré.",
  forbidden: "Ce n'est pas à toi de décider de cette demande.",
};

/** Ce qui est dit pour un statut inconnu : un refus, jamais un succès. */
export const UNEXPECTED_RESULT =
  "Décision non prise en compte (réponse inattendue du serveur).";

/** Le sort d'une décision, en français. */
export function resultMessage(status: unknown): string {
  // `hasOwnProperty` : « toString » ou « constructor » ne sont pas des statuts
  return (typeof status === "string" &&
      Object.prototype.hasOwnProperty.call(RESULT_MESSAGES, status))
    ? RESULT_MESSAGES[status]
    : UNEXPECTED_RESULT;
}

/** La décision a été prise en compte (acceptée ou refusée), quelle qu'elle soit. */
export function isDecisionTaken(status: unknown): boolean {
  return status === "approved" || status === "rejected";
}

/** Une trame `approval_result` lisible — ou `null`. */
export function approvalResult(raw: unknown): { id: number; status: string } | null {
  if (!raw || typeof raw !== "object") return null;
  const { id, status } = raw as { id?: unknown; status?: unknown };
  if (typeof id !== "number" || !Number.isSafeInteger(id) || id <= 0) return null;
  if (typeof status !== "string" || !status || status.length > MAX_STATUS_CHARS) return null;
  return { id, status };
}

// ── L'état de la bande ──────────────────────────────────────────────

export interface ApprovalsState {
  /** La dernière liste reçue, exactement. */
  readonly cards: readonly ApprovalCard[];
  /** Les cartes dont la décision est partie sans réponse encore (« envoyé… »). */
  readonly sent: readonly number[];
  /** Une décision ne part que sur une connexion ouverte — jamais mise en file. */
  readonly connected: boolean;
}

export const EMPTY_APPROVALS: ApprovalsState = { cards: [], sent: [], connected: false };

/**
 * La connexion change d'état.
 *
 * - Ouverte : on repart d'une liste **vide**. À l'ouverture, le serveur
 *   n'envoie `approvals` que s'il y a au moins une carte ; garder celles
 *   d'avant la coupure montrerait des demandes déjà décidées ailleurs, ou
 *   expirées, que rien ne viendrait effacer.
 * - Refusée (4401) : il n'y aura pas de prochaine connexion, plus rien ne
 *   peut être décidé ici.
 * - Coupée : les cartes restent visibles, boutons éteints ; une décision
 *   partie sans réponse n'en aura pas sur ce socket-là.
 */
export function withConnection(
  state: ApprovalsState,
  status: ConnectionEvent["status"],
): ApprovalsState {
  if (status === "connected") return { cards: [], sent: [], connected: true };
  if (status === "unauthorized") return { cards: [], sent: [], connected: false };
  return { cards: state.cards, sent: [], connected: false };
}

/** Une trame `approvals` : la liste entière, appliquée telle quelle. */
export function withApprovals(state: ApprovalsState, items: unknown): ApprovalsState {
  return { ...state, cards: approvalCards(items), sent: [] };
}

/** Une décision est partie pour cette carte. */
export function withDecisionSent(state: ApprovalsState, id: number): ApprovalsState {
  return state.sent.includes(id) ? state : { ...state, sent: [...state.sent, id] };
}

/** Le serveur a répondu sur cette carte (la liste à jour suit). */
export function withResult(state: ApprovalsState, id: number): ApprovalsState {
  return { ...state, sent: state.sent.filter((x) => x !== id) };
}

export interface CardControls {
  accept: boolean;
  refuse: boolean;
  /** Une décision est partie : « envoyé… », les deux boutons éteints. */
  sending: boolean;
}

/** Ce que les boutons d'une carte permettent, maintenant. */
export function cardControls(
  state: ApprovalsState,
  card: ApprovalCard,
  nowMs: number,
): CardControls {
  const sending = state.sent.includes(card.id);
  const open = state.connected && !sending;
  return { accept: open && canAccept(card, nowMs), refuse: open, sending };
}

/**
 * La trame à envoyer pour ce clic — ou `null` si les boutons ne le
 * permettent pas (le clic d'un bouton que le minuteur n'avait pas encore
 * éteint, une carte qui n'est plus dans la liste).
 */
export function decisionFrame(
  state: ApprovalsState,
  id: number,
  decision: ApprovalDecision,
  nowMs: number,
): ApprovalFrame | null {
  const card = state.cards.find((c) => c.id === id);
  if (!card) return null;
  const controls = cardControls(state, card, nowMs);
  const allowed = decision === "accept" ? controls.accept : controls.refuse;
  return allowed ? approvalFrame(card, decision) : null;
}
