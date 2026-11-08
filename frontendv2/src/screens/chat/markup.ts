/**
 * Le balisage du chat, dans la forme de la maquette (`frontendv2/maquette/ecrans/chat.js`), tiré de l'état
 * que tiennent les modules purs du client web (`@web/ui/chatSync`, `approvals`, `toolActivity`, `strands`…).
 * Des fonctions pures qui rendent du HTML : tout texte venu du serveur passe par `h()`, sauf la réponse pro,
 * que `renderProMarkdown` échappe en entier avant de poser ses propres balises.
 */
import type { HistoryAttachment } from "@web/types";
import { parseBlocks, parseInline } from "@web/ui/inlineMarkup";
import { renderProMarkdown } from "@web/ui/proMarkdown";
import { noteLine } from "@web/ui/messageNotes";
import {
  ASLEEP_NOTE,
  asleepNoteShown,
  consoleHref,
  timeMarkers,
  whyLink,
  type StoredMessage,
} from "@web/ui/chatSync";
import {
  argsPreview,
  cardSummary,
  durationLabel,
  isRunning,
  outcomeLabel,
  placeCards,
  runningLabel,
  type WorkCard,
  type WorkStep,
} from "@web/ui/toolActivity";
import {
  acceptRefusal,
  cardControls,
  expiryLabel,
  isExpired,
  type ApprovalsState,
} from "@web/ui/approvals";
import { strandLabel, type StrandInfo } from "@web/ui/strands";
import type { ApprovalCard, SentFile, ToolUse } from "@web/types";
import { h } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { replyHash } from "../teams/format";

// ── Petites formes ────────────────────────────────────────────────────

/** « 14:05 ». */
export function clock(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return "";
  return new Date(ts).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

const WEEKDAYS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function dayStart(ms: number): number {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** Quand, en court, comme une liste de messagerie : « 13:31 », « hier », « lun. », « 28 oct. ». */
export function shortWhen(ms: number, now: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const days = Math.round((dayStart(now) - dayStart(ms)) / 86_400_000);
  if (days <= 0) return clock(ms);
  if (days === 1) return "hier";
  const d = new Date(ms);
  if (days < 7) return WEEKDAYS[d.getDay()];
  const label = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === new Date(now).getFullYear() ? label : `${label} ${d.getFullYear()}`;
}

/** « aujourd'hui 14:05 », « hier 21:41 », « lun. 08:12 », « 28 oct. 13:31 ». */
export function dayAndClock(ms: number, now: number): string {
  const day = shortWhen(ms, now);
  if (!day) return "";
  const time = clock(ms);
  return day === time ? `aujourd'hui ${time}` : `${day} ${time}`;
}

/** « 212 Ko », « 1,8 Mo ». */
export function sizeLabel(bytes: number | undefined): string {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  return `${(bytes / (1024 * 1024)).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo`;
}

/** Le texte d'une personne : échappé, ses retours à la ligne gardés. */
export function plainHtml(text: string): string {
  return h(text).replace(/\n/g, "<br>");
}

/**
 * Une de ses réponses ordinaires : blocs de code, code en ligne et gras (`@web/ui/inlineMarkup`), le reste
 * échappé. Le même découpage que `renderInline` du client web, rendu en HTML.
 */
export function inlineHtml(text: string): string {
  let out = "";
  for (const block of parseBlocks(text)) {
    if (block.kind === "code") {
      out += `<pre class="chat-code"><code>${h(block.text)}</code></pre>`;
      continue;
    }
    const body = block.text.replace(/^\n+/, "").replace(/\n+$/, "");
    for (const seg of parseInline(body)) {
      if (seg.kind === "text") out += plainHtml(seg.text);
      else if (seg.kind === "bold") out += `<strong>${h(seg.text)}</strong>`;
      else out += `<code>${h(seg.text)}</code>`;
    }
  }
  return out;
}

/**
 * Ce que la personne a tapé dans un message : celui qu'elle vient d'envoyer le sait (`matchText`) ; un message relu au
 * serveur a ses pièces à part, leurs noms repliés en `texte [a.png, b.pdf]` par `chatSync.withAttachments`, qu'on
 * retire tels quels (ADR 0215). Un message sans pièce connue se lit tel quel, même s'il finit par des crochets.
 */
export function typedText(msg: Pick<StoredMessage, "text" | "matchText" | "attachments">): string {
  if (msg.matchText !== undefined) return msg.matchText;
  const label = (msg.attachments ?? []).map((a) => a.name).join(", ");
  if (!label) return msg.text;
  const suffix = `[${label}]`;
  if (msg.text === suffix) return "";
  return msg.text.endsWith(` ${suffix}`) ? msg.text.slice(0, -suffix.length - 1) : msg.text;
}

// ── Les pièces du fil ─────────────────────────────────────────────────

export interface ThreadView {
  /** Les messages du fil montré, dans l'ordre. */
  messages: StoredMessage[];
  /** Ses cartes de travail de ce fil (mode pro). */
  cards: readonly WorkCard[];
  operator: boolean;
  pro: boolean;
  /** Combien de bulles montrer d'une réponse qui s'écrit encore. */
  shown: (msg: StoredMessage, total: number) => number;
  /** Ses bulles, d'une réponse (`@web/ui/bubbles.splitBubbles`). */
  split: (text: string) => string[];
  typing: boolean;
  openWork: ReadonlySet<string>;
  verdictErrors: ReadonlyMap<number, string>;
  /** Le haut du fil avec elle : d'autres messages au serveur (`more`), en train de venir (`loading`), ou rien de plus (ADR 0215). */
  older: "none" | "more" | "loading";
  now: number;
  /** L'adresse du moteur, pour ses fichiers et la console. */
  api: string;
  /** Une recherche dans la conversation : seulement ce qui la contient (sans accents ni casse). */
  filter?: (msg: StoredMessage) => boolean;
  /**
   * Ses cartes miniatures (ADR 0196 : un voyage, ce qu'elle a cherché, une carte qu'elle montre), sous ses bulles,
   * qui s'ouvrent dans l'écran Carte (`map/cards.ts::miniCard`) ; aucune : rien.
   */
  mapCards?: (msg: StoredMessage) => string;
  /** Le message que la palette vient de montrer (sa `messageKey`) : surligné un instant. */
  found?: string;
}

/**
 * La clé d'un message dans le fil montré (`data-msg`) : son identifiant, sinon son heure (un message pas encore
 * accusé). La palette y mène.
 */
export function messageKey(msg: StoredMessage): string {
  return typeof msg.id === "number" ? String(msg.id) : `t${msg.ts}`;
}

/** Les attributs qui désignent un message dans le fil : sa clé, et sa marque s'il vient d'être trouvé. */
function msgAttrs(msg: StoredMessage, found: string | undefined): { key: string; found: string } {
  const key = messageKey(msg);
  return { key: ` data-msg="${h(key)}"`, found: found !== undefined && found === key ? " found" : "" };
}

function sysNote(text: string, side: "me" | "her", href?: string, icon: "info" | "alert" | "moon-z" = "info"): string {
  const link = href ? ` <a href="${h(href)}" target="_blank" rel="noopener">ouvrir la console</a>` : "";
  return `<div class="msg-sys ${side}">${ico(icon, "xs")}<span>${h(text)}${link}</span></div>`;
}

function userStatus(msg: StoredMessage, answered: boolean): string {
  if (msg.status === "pending") return ` · ${ico("clock", "xs")} en attente d'envoi`;
  if (msg.status === "failed") return ` · ${ico("x", "xs")} ${h(msg.reason ? `refusé — ${msg.reason}` : "refusé")}`;
  return answered ? ` · ${ico("checks", "xs")} lu` : ` · ${ico("check", "xs")} envoyé`;
}

function userFiles(pieces: readonly HistoryAttachment[]): string {
  return pieces
    .map((a) => `<div class="msg-file">${ico(a.kind === "image" ? "image" : "file")}<b>${h(a.name)}</b></div>`)
    .join("");
}

export function userMessage(msg: StoredMessage, answered: boolean, view: Pick<ThreadView, "api" | "operator" | "found">): string {
  const text = typedText(msg);
  const bubble = text.trim() ? `<div class="bubble">${plainHtml(text)}</div>` : "";
  const failed = msg.status === "failed";
  const meta = `<div class="msg-meta${failed ? " ko" : ""}"${msg.reason ? ` title="${h(msg.reason)}"` : ""}>${h(clock(msg.ts))}${userStatus(msg, answered)}</div>`;
  const at = msgAttrs(msg, view.found);
  let out = `<div class="msg me${msg.status === "pending" ? " pending" : ""}${failed ? " failed" : ""}${at.found}"${at.key}>${userFiles(msg.attachments ?? [])}${bubble}${meta}</div>`;
  if (msg.note) out += sysNote(msg.note, "me", undefined, "alert");
  if (msg.replyNote) {
    const href = view.operator ? consoleHref(msg.replyHref) : undefined;
    out += sysNote(msg.replyNote, "me", href ? `${view.api}${href}` : undefined, "alert");
  }
  return out;
}

/** Un fichier qu'elle a envoyé : une image en vignette, un autre fichier en lien ; retiré, son nom barré d'un mot. */
export function sentFile(file: SentFile, api: string): string {
  if (file.available === false) {
    return `<div class="msg-file gone">${ico("file")}<b>${h(file.name)}</b><span class="muted">plus disponible</span></div>`;
  }
  const href = `${api}${file.url}`;
  const size = sizeLabel(file.size);
  if (file.kind === "image") {
    return `<a class="msg-file img" href="${h(href)}" target="_blank" rel="noopener"><img src="${h(href)}" alt="${h(file.name)}" loading="lazy">
      <span class="mf-cap">${h(file.name)}${size ? ` · ${h(size)}` : ""}</span></a>`;
  }
  return `<a class="msg-file" href="${h(href)}" download="${h(file.name)}" target="_blank" rel="noopener">${ico("file")}<b>${h(file.name)}</b>${size ? `<span class="muted">${h(size)}</span>` : ""}${ico("download", "sm")}</a>`;
}

function verdictButtons(msg: StoredMessage, id: number, api: string, operator: boolean): string {
  if (!operator) return "";
  const why = whyLink(msg);
  const whyHtml = why ? `<a class="why" href="${h(api + why.href)}" target="_blank" rel="noopener" title="L'explication dans la console">${h(why.label)}</a>` : "";
  const up = msg.verdict === "ok";
  const down = msg.verdict === "ko";
  return `<span class="verdict${msg.verdict ? " set" : ""}">
    <button type="button" class="${up ? "on" : ""}" title="${up ? "Bonne réponse — un clic retire ton avis" : "Bonne réponse"}" aria-pressed="${up}" data-verdict="ok" data-mid="${id}">${ico("thumb-up", "xs")}</button>
    <button type="button" class="${down ? "on" : ""}" title="${down ? "Pas la bonne réponse — un clic retire ton avis" : "Elle aurait dû dire autre chose"}" aria-pressed="${down}" data-verdict="ko" data-mid="${id}">${ico("thumb-down", "xs")}</button>
    ${whyHtml}</span>`;
}

function locationNote(msg: StoredMessage): string {
  return (msg.notes ?? [])
    .map((n) => `<span class="msg-note" role="note">${ico("pin", "xs")}${h(noteLine(n, msg.ts).replace(/^📍\s*/, ""))}</span>`)
    .join("");
}

export function mikaMessage(msg: StoredMessage, view: ThreadView, carded: boolean): string {
  const pro = msg.mode === "pro";
  const parts = pro ? [msg.text] : view.split(msg.text);
  const shown = parts.length < 2 ? parts.length : view.shown(msg, parts.length);
  const complete = shown >= parts.length;
  const bubbles = pro
    ? `<div class="bubble md">${renderProMarkdown(msg.text)}</div>`
    : parts
        .slice(0, shown)
        .map((p) => `<div class="bubble${msg.inner ? " inner" : ""}">${inlineHtml(p)}</div>`)
        .join("");
  const files = complete ? (msg.files ?? []).map((f) => sentFile(f, view.api)).join("") : "";
  const maps = complete && view.mapCards ? view.mapCards(msg) : "";
  const judged = complete && !msg.inner && typeof msg.id === "number" ? verdictButtons(msg, msg.id, view.api, view.operator) : "";
  const label = [clock(msg.ts), ...(pro ? ["mode pro"] : []), ...(msg.inner ? ["pensée à voix haute"] : [])].join(" · ");
  let out = "";
  // une réponse pro relue sans sa carte en direct (qui ne survit pas à un rechargement) : ses outils, repliés
  if (pro && !carded && msg.tools?.length) out += historyTools(msg.tools);
  const at = msgAttrs(msg, view.found);
  out += `<div class="msg ${pro ? "pro" : "her"}${at.found}"${at.key}>${mikaAvatar("sm")}<div class="msg-col">${locationNote(msg)}${bubbles}${files}${maps}
    <div class="msg-meta">${h(label)}${judged}</div></div></div>`;
  if (view.operator && msg.verdictNote) out += sysNote(`Ce qu'elle aurait dû dire : ${msg.verdictNote}`, "her");
  const error = typeof msg.id === "number" ? view.verdictErrors.get(msg.id) : undefined;
  if (error) out += sysNote(error, "her", undefined, "alert");
  return out;
}

const STEP_ICON: Record<"ok" | "failed" | "stopped", IconName> = { ok: "check", failed: "x", stopped: "minus" };
const STEP_CLASS: Record<"running" | "ok" | "failed" | "stopped", string> = { running: "run", ok: "ok", failed: "ko", stopped: "stop" };

function stepMarkup(step: WorkStep): string {
  if (step.kind === "note") return `<li class="note"><span class="st">${ico("pen", "xs")}</span><span class="note-text">${h(step.text)}</span></li>`;
  if (step.kind === "end") return `<li class="end"><span class="st">${ico("alert", "xs")}</span><span class="note-text">${h(outcomeLabel(step.outcome))}</span></li>`;
  const st = step.status === "running" ? '<i class="spin"></i>' : ico(STEP_ICON[step.status], "xs");
  const result = step.status === "running" ? "" : step.result;
  return `<li class="${STEP_CLASS[step.status]}"><span class="st">${st}</span><code>${h(step.name)}</code><span class="arg" title="${h(step.args)}">${h(argsPreview(step.args))}</span>
    <span class="d">${step.durationMs !== null ? h(durationLabel(step.durationMs)) : ""}</span>${result ? `<pre>${h(result)}</pre>` : ""}</li>`;
}

/** Sa carte de travail (ADR 0116) : ouverte tant qu'elle travaille, repliée sur son résumé ensuite. */
export function workCard(card: WorkCard, collapsed: boolean, open: boolean): string {
  const running = isRunning(card) && !collapsed;
  const summary = running ? runningLabel(card) : cardSummary(card);
  const isOpen = running || open;
  return `<details class="tools-card${running ? " live" : ""}" data-work="${h(card.key)}"${isOpen ? " open" : ""}>
    <summary>${ico("terminal", "sm")}<b>Son travail</b><span class="muted">${h(summary)}</span>${ico("chev-down", "sm")}</summary>
    ${card.steps.length ? `<ol>${card.steps.map(stepMarkup).join("")}</ol>` : ""}</details>`;
}

/** Les outils d'une réponse pro relue : leurs noms et s'ils ont réussi, sans plus (l'historique n'en garde pas plus). */
export function historyTools(tools: readonly ToolUse[]): string {
  const failed = tools.filter((t) => !t.ok).length;
  const summary = `${tools.length} outil${tools.length > 1 ? "s" : ""}${failed ? ` · ${failed} échec${failed > 1 ? "s" : ""}` : ""}`;
  return `<details class="tools-card"><summary>${ico("terminal", "sm")}<b>Son travail</b><span class="muted">${h(summary)}</span>${ico("chev-down", "sm")}</summary>
    <ol>${tools.map((t) => `<li class="${t.ok ? "ok" : "ko"}"><span class="st">${ico(t.ok ? "check" : "x", "xs")}</span><code>${h(t.name)}</code><span class="arg"></span><span class="d"></span></li>`).join("")}</ol></details>`;
}

/** Le fil montré : repères de temps, bulles, notes de la machine, cartes de travail, « Mika écrit… ». */
export function threadMarkup(view: ThreadView): string {
  const all = view.messages;
  const shownMessages = view.filter ? all.filter(view.filter) : all;
  const out: string[] = [];
  if (view.older !== "none") {
    const loading = view.older === "loading";
    out.push(`<div class="chat-older"><button class="btn xs ghost" type="button" data-older${loading ? " disabled" : ""}>${ico("history", "xs")}${loading ? "Chargement…" : "Messages plus anciens"}</button></div>`);
  }
  // ses cartes de travail : repliées au-dessus de leur réponse, après le message de la personne, ou en bas
  const before = new Map<number, string[]>();
  const after = new Map<number, string[]>();
  const end: string[] = [];
  const cards = new Map(view.cards.map((c) => [c.key, c]));
  if (!view.filter) {
    for (const place of placeCards(all, view.cards)) {
      const card = cards.get(place.key);
      if (!card) continue;
      const html = workCard(card, place.collapsed, view.openWork.has(card.key));
      if (place.where === "end") end.push(html);
      else {
        const at = place.where === "before" ? before : after;
        at.set(place.index, [...(at.get(place.index) ?? []), html]);
      }
    }
  }
  const markers = timeMarkers(all, view.now);
  // le dernier de ses messages : ce qui le précède, elle l'a lu
  let lastHers = -1;
  all.forEach((m, i) => {
    if (m.sender === "vtuber" && !m.inner) lastHers = i;
  });
  all.forEach((msg, index) => {
    if (view.filter && !view.filter(msg)) return;
    const marker = view.filter ? null : markers[index];
    if (marker) out.push(`<div class="day"><span>${h(marker.label)}</span></div>`);
    out.push(...(before.get(index) ?? []));
    if (msg.sender === "user") out.push(userMessage(msg, index < lastHers, view));
    else out.push(mikaMessage(msg, view, before.has(index)));
    if (!msg.replyNote && msg.sender === "user" && asleepNoteShown(all, index)) {
      out.push(sysNote(ASLEEP_NOTE, "me", undefined, "moon-z"));
    }
    out.push(...(after.get(index) ?? []));
  });
  out.push(...end);
  if (view.filter && !shownMessages.length) {
    out.push(`<div class="empty">${ico("search")}<b>Rien dans ces messages</b><p>La recherche ne porte que sur les messages chargés ici.</p></div>`);
  }
  if (!all.length && view.pro) {
    out.push(`<div class="empty">${ico("threads")}<b>Un fil à part</b><p>Mika n'y relit que ce qui s'y dit. Demande-lui un travail ; /aide pour les commandes.</p></div>`);
  }
  out.push(`<div class="msg her typing-row" data-typing${view.typing ? "" : " hidden"}>${mikaAvatar("sm")}<div class="bubble typing" aria-label="Mika écrit…"><i></i><i></i><i></i></div></div>`);
  return out.join("");
}

// ── Les cartes d'accord ───────────────────────────────────────────────

export interface ApprovalNote {
  text: string;
  ok: boolean;
}

function approvalCard(state: ApprovalsState, card: ApprovalCard, now: number, open: boolean): string {
  const controls = cardControls(state, card, now);
  const refusal = acceptRefusal(card, now);
  const expiry = isExpired(card, now) ? "" : expiryLabel(card, now);
  const meta = [
    "Mika demande ton accord",
    ...(expiry ? [`<span class="ap-exp">${h(expiry)}</span>`] : []),
    ...(controls.sending ? ["envoyé…"] : []),
  ].join(" · ");
  const refusalLine = refusal ? `<span class="ap-meta ap-ko">${h(refusal)}</span>` : "";
  return `<div class="approval${refusal ? " blocked" : ""}" data-card="${card.id}">
    <div class="ap-line">${ico("shield")}<div class="ap-main"><b>${h(card.title)}</b><span class="ap-meta">${meta}</span>${refusalLine}</div>
      <button class="btn sm" type="button" data-ap="refuse" data-id="${card.id}"${controls.refuse ? "" : " disabled"}>Refuser</button>
      <button class="btn sm primary" type="button" data-ap="accept" data-id="${card.id}"${controls.accept ? "" : " disabled"}${refusal ? ` title="${h(refusal)}"` : ""}>${ico("check", "sm")}Accepter</button></div>
    <details class="ap-more" data-ap-more="${card.id}"${open ? " open" : ""}><summary>${ico("chev-right", "xs")}Voir exactement ce qui partira</summary>
      <pre class="ap-raw">${h(card.text || "(rien à montrer)")}</pre>
      <p class="ap-help">Seuls ces boutons décident : un « oui » tapé dans la conversation ne vaut pas accord.</p></details></div>`;
}

/**
 * Ce qu'une carte veut faire, relevé dans la trame brute (`capability`, `draft` : `protocole-chat.md` § 4) — le
 * validateur partagé ne le garde pas.
 */
export interface CardKind {
  capability: string;
  draft: string;
}

/** Où se décide une carte qui part ailleurs : l'adresse de son brouillon, le nom de l'écran, son icône. */
export interface Elsewhere {
  href: string;
  where: "Mail" | "Teams";
  icon: "mail" | "teams";
}

/**
 * Les cartes qui se décident là où elles partiront (ADR 0191) : un mail de sa boîte, une réponse Teams. Le lien
 * ouvre le brouillon même (`#mail/messages/brouillon/<id>`, `#teams/brouillons/<id>`, où Teams le surligne) ; une
 * réponse Teams sans brouillon nommé, la liste « Ses brouillons ».
 */
export function elsewhere(kind: CardKind | undefined): Elsewhere | null {
  if (!kind) return null;
  if (kind.capability === "email.send" && kind.draft) {
    return { href: `#mail/messages/brouillon/${encodeURIComponent(kind.draft)}`, where: "Mail", icon: "mail" };
  }
  if (kind.capability === "teams.send") {
    return { href: kind.draft ? replyHash(kind.draft) : "#teams/brouillons", where: "Teams", icon: "teams" };
  }
  return null;
}

/** Les sortes des cartes d'une trame `approvals`, par identifiant (ce qui n'est pas lisible est ignoré). */
export function cardKinds(items: unknown): Map<number, CardKind> {
  const out = new Map<number, CardKind>();
  if (!Array.isArray(items)) return out;
  for (const raw of items) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    if (typeof r.id !== "number" || typeof r.capability !== "string") continue;
    out.set(r.id, { capability: r.capability, draft: typeof r.draft === "string" ? r.draft : "" });
  }
  return out;
}

/**
 * Une carte qui se décide ailleurs : un lien, jamais ses boutons. Une ligne compacte — ce qu'elle a préparé (deux
 * lignes au plus, le reste en infobulle), où cela se décide, « Ouvrir » sur la même ligne, même sur un téléphone.
 */
function linkCard(card: ApprovalCard, to: Elsewhere): string {
  return `<div class="approval link" data-card="${card.id}">
    <div class="ap-line">${ico(to.icon)}<div class="ap-main"><b title="${h(card.title)}">${h(card.title)}</b><span class="ap-meta">À relire et décider dans ${h(to.where)}</span></div>
      <a class="btn sm primary" href="${h(to.href)}" aria-label="Ouvrir dans ${h(to.where)}">${ico("chev-right", "sm")}Ouvrir<span class="lbl"> dans ${h(to.where)}</span></a></div></div>`;
}

/**
 * Sur un téléphone, deux cartes-liens ou plus se replient sous une ligne (« 2 brouillons à relire · Mail · Teams »),
 * qui les déplie : sinon elles mangent le fil. Posée juste avant la première ; la feuille (app.css) ne la montre que
 * sous 760 px, et y cache les cartes-liens qui la suivent tant qu'elle est repliée. Sur un grand écran, rien ne change.
 */
function linksSummary(targets: readonly Elsewhere[], open: boolean): string {
  const places = [...new Set(targets.map((t) => t.where))];
  const n = targets.length;
  return `<button class="ap-links" type="button" data-ap-links aria-expanded="${open}">${ico("pen", "sm")}<b>${n} brouillons à relire</b><span class="ap-meta">${h(places.join(" · "))}</span>${ico(open ? "chev-down" : "chev-right", "sm")}</button>`;
}

/** La bande des cartes, au-dessus du champ : seules ses cartes décident. */
export function approvalsMarkup(
  state: ApprovalsState,
  now: number,
  opts: {
    note: ApprovalNote | null;
    auto: boolean;
    open: ReadonlySet<number>;
    kinds?: ReadonlyMap<number, CardKind>;
    /** Sur un téléphone, les cartes-liens dépliées sous leur ligne (`linksSummary`). */
    linksOpen?: boolean;
  },
): string {
  const out: string[] = [];
  if (opts.note) {
    out.push(`<div class="approval done${opts.note.ok ? "" : " ko"}" role="status">${ico(opts.note.ok ? "check" : "info")}<span>${h(opts.note.text)}</span></div>`);
  }
  if (state.cards.length && !state.connected) {
    out.push(`<div class="ap-offline">${ico("wifi", "sm")}<span>Hors ligne — tu pourras décider à la reconnexion.</span></div>`);
  }
  if (state.cards.length && opts.auto) {
    out.push(`<div class="ap-offline auto">${ico("bolt", "sm")}<span>« Tout accepter » est allumé : chaque carte acceptable part acceptée.</span></div>`);
  }
  const targets = state.cards.map((card) => elsewhere(opts.kinds?.get(card.id)));
  const links = targets.filter((t): t is Elsewhere => t !== null);
  let summarized = links.length < 2;
  state.cards.forEach((card, i) => {
    const to = targets[i];
    if (to && !summarized) {
      out.push(linksSummary(links, opts.linksOpen === true));
      summarized = true;
    }
    out.push(to ? linkCard(card, to) : approvalCard(state, card, now, opts.open.has(card.id)));
  });
  return out.join("");
}

// ── Le champ ──────────────────────────────────────────────────────────

export interface ComposerView {
  pro: boolean;
  operator: boolean;
  auto: boolean;
}

/** L'invite du champ : en mode pro, assez courte pour tenir sur une ligne d'un téléphone. */
export function composerPlaceholder(pro: boolean): string {
  return pro ? "Une tâche pour Mika… (/ : commandes)" : "Écrire à Mika…";
}

export function composerMarkup(view: ComposerView, maxLength: number, accept: string): string {
  return `<div class="composer${view.pro ? " pro" : ""}" data-composer>
    <div class="cmp-attach" data-attach hidden></div>
    <textarea data-chat-input rows="1" maxlength="${maxLength}" aria-label="Ton message" placeholder="${h(composerPlaceholder(view.pro))}"></textarea>
    <div class="cmp-bar">
      <button class="btn icon ghost sm" type="button" data-cmp="joindre" title="Joindre des fichiers (5 au plus, 5 Mo chacun)">${ico("clip")}</button>
      <button class="btn icon ghost sm" type="button" data-cmp="emoji" title="Emojis">${ico("smile")}</button>
      ${view.pro ? `<button class="btn ghost sm" type="button" data-cmp="commandes" title="Commandes du fil">/<span class="lbl"> commandes</span></button>` : ""}
      <span class="grow"></span>
      <span class="cmp-count tiny muted" data-counter hidden></span>
      ${view.operator ? `<button class="pill-toggle" type="button" data-cmp="accord"></button>
      <button class="pill-toggle pro${view.pro ? " on" : ""}" type="button" data-cmp="pro" aria-pressed="${view.pro}" title="Mode pro : sans son caractère, outils en direct, fils de travail">${ico("terminal", "sm")}<span>Pro</span></button>` : ""}
      <button class="btn primary sm" type="button" data-cmp="envoyer">${ico("send", "sm")}<span class="lbl">Envoyer</span></button>
      <input type="file" multiple hidden data-file accept="${h(accept)}">
    </div></div>`;
}

/**
 * Le bouton « Accords » : un par un, ou tout accepter (ADR 0170). Il garde un mot sur un téléphone, où la barre du
 * champ cache les libellés (`.lbl`) : un écran tactile ne montre pas `title`, et un bouclier seul ne dit pas qu'il
 * commande « Tout accepter ».
 */
export function accordToggle(auto: boolean): { html: string; title: string } {
  return auto
    ? {
        html: `${ico("bolt", "sm")}<span>Tout accepter</span>`,
        title: "Tout accepter : chaque carte acceptable part acceptée, une à la fois (pour cet onglet). Cliquer pour revenir à « un par un ».",
      }
    : {
        html: `${ico("shield", "sm")}<span class="lbl">Accords : un par un</span><span class="lbl-short">Un par un</span>`,
        title: "Chaque appel extérieur attend ta carte d'accord. Cliquer pour tout accepter (cet onglet seulement).",
      };
}

export interface PendingAttachment {
  name: string;
  type: string;
  size: number;
  data: string;
}

export function attachmentsMarkup(pending: readonly PendingAttachment[], notices: readonly string[]): string {
  const chips = pending
    .map(
      (a, i) => `<span class="chip">${ico(a.type.startsWith("image/") ? "image" : "file", "xs")}${h(a.name)}<span class="muted">${h(sizeLabel(a.size))}</span>
        <button type="button" title="Retirer" data-unattach="${i}">${ico("x", "xs")}</button></span>`,
    )
    .join("");
  const notes = notices.map((n) => `<span class="cmp-notice">${ico("alert", "xs")}${h(n)}</span>`).join("");
  return chips + notes;
}

// ── Les fils de travail (mode pro) ────────────────────────────────────

export function strandItem(s: StrandInfo, active: string, unread: boolean, now: number): string {
  return `<button class="li${s.id === active ? " on" : ""}${unread ? " unread" : ""}" type="button" data-fil="${h(s.id)}"${s.id === active ? ' aria-current="true"' : ""}>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(strandLabel(s))}</span><time>${h(shortWhen(s.lastAt, now))}</time></span>
    <span class="li-snip">${h(s.description || "Sans description")}</span></span></button>`;
}

export function strandsPane(
  all: readonly StrandInfo[],
  active: string,
  opts: { showArchived: boolean; unread: ReadonlySet<string>; now: number },
): string {
  const live = all.filter((s) => !s.archived || s.id === active);
  const archived = all.filter((s) => s.archived && s.id !== active);
  const item = (s: StrandInfo) => strandItem(s, active, opts.unread.has(s.id), opts.now);
  return `<div class="pane-head"><h2>Fils de travail</h2><span class="cnt">${live.length}</span><span class="grow"></span>
      <button class="btn sm" type="button" data-cmd="nouveau" title="Ouvrir un fil neuf (/clear) : l'actuel reste dans la liste">${ico("plus", "sm")}Nouveau</button></div>
    <div class="pane-scroll">${live.map(item).join("")}
      ${archived.length ? `<button class="group-label as-btn" type="button" data-archives aria-expanded="${opts.showArchived}">${ico(opts.showArchived ? "chev-down" : "chev-right", "xs")}Archivés<span class="cnt">${archived.length}</span></button>
      ${opts.showArchived ? archived.map(item).join("") : ""}` : ""}</div>
    <div class="pane-foot small muted">Le fil avec Mika est caché en mode pro ; il revient quand tu l'éteins.</div>`;
}

export function strandHead(info: StrandInfo, note: string): string {
  return `<button class="btn sm icon ghost mobile-back" type="button" data-fils-mobile title="Les fils">${ico("threads", "sm")}</button>
    <div class="grow"><h2>${h(strandLabel(info))}${info.archived ? ' <span class="tag">archivé</span>' : ""}</h2>
      <p class="small muted ellipsis">${h(info.description || "Ajoute une petite description : c'est tout le contexte du fil.")}</p>
      ${note ? `<p class="small strand-note" role="status">${h(note)}</p>` : ""}</div>
    <button class="btn icon ghost sm" type="button" data-cmd="renommer" title="Titre et description">${ico("pen", "sm")}</button>
    <button class="btn icon ghost sm" type="button" data-cmd="${info.archived ? "desarchiver" : "archiver"}" title="${info.archived ? "Sortir le fil des archives" : "Archiver le fil"}">${ico("archive", "sm")}</button>`;
}

// ── Les fichiers échangés ─────────────────────────────────────────────

function saveLink(url: string, name: string, api: string): string {
  return `<a class="btn xs" href="${h(api + url)}" download="${h(name)}" target="_blank" rel="noopener">${ico("download", "xs")}Enregistrer</a>`;
}

/**
 * Tous les fichiers du fil chargé : les siens et les tiens se téléchargent (ADR 0215 : ta propre copie, tant qu'elle
 * est gardée). Une pièce sans adresse (pas encore lue, ou d'avant qu'elles se gardent) n'offre rien.
 */
export function filesTable(messages: readonly StoredMessage[], api: string, now: number): string {
  const rows: string[] = [];
  for (const m of [...messages].reverse()) {
    const when = dayAndClock(m.ts, now);
    if (m.sender === "vtuber") {
      for (const f of m.files ?? []) {
        const action = f.available === false ? '<span class="muted">plus disponible</span>' : saveLink(f.url, f.name, api);
        rows.push(`<tr><td>${ico(f.kind === "image" ? "image" : "file", "sm")} ${h(f.name)}</td><td>Mika</td><td>${h(when)}</td><td class="actions">${action}</td></tr>`);
      }
    } else {
      for (const a of m.attachments ?? []) {
        const action = a.available === false ? '<span class="muted">plus disponible</span>' : a.url ? saveLink(a.url, a.name, api) : "";
        rows.push(`<tr><td>${ico(a.kind === "image" ? "image" : "file", "sm")} ${h(a.name)}</td><td>toi</td><td>${h(when)}</td><td class="actions">${action}</td></tr>`);
      }
    }
  }
  if (!rows.length) {
    return `<div class="empty">${ico("clip")}<b>Aucun fichier dans ces messages</b><p>Ce que vous vous êtes envoyé se télécharge d'ici, tant que c'est gardé.</p></div>`;
  }
  return `<table class="tbl"><thead><tr><th>Fichier</th><th>De</th><th>Quand</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}
