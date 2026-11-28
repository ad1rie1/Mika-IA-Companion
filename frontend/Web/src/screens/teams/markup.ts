/**
 * Le rendu de Teams, celui de la maquette (`frontend/Web/maquette/ecrans/teams.js`), nourri par l'API par personne :
 * la liste des discussions, le fil à la Teams, ses réponses en carte, le champ, le panneau d'informations et
 * « Ses brouillons ». Pur : des chaînes HTML, tout texte venu d'ailleurs échappé.
 */
import { h, initials } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { workLine, type Work } from "../../mika/work";
import { TEAMS_LIMITS, teamsImageUrl, type Conversation, type Reply, type TeamsAccount, type TeamsImage, type TeamsMessage, type TeamsQuote, type Thread } from "../../api/teams";
import { pageHtml } from "../projets/docmd";
import { correctButton, countSpan, markToFill } from "../../shared/compose";
import { clock, dayAndClock, shortWhen } from "../../shared/dates";
import { caps, levelTag, type Caps } from "../../shared/levels";
import { ofName } from "../../shared/names";
import { avatar, firstName } from "../../shared/people";
import {
  ago,
  authorLabel,
  awaits,
  cardState,
  fromHer,
  fromYou,
  kindLabel,
  messageHtml,
  modeLabel,
  modeTitle,
  ownAccount,
  reactionsHtml,
  replyState,
  retouched,
  sentUnder,
  threadCards,
  threadMarks,
  type AccountWho,
  type OwnBubble,
} from "./format";

export type Filter = "tout" | "elle" | "mentions";

/** Ce que l'API dit d'une discussion : sa réponse d'elle en chemin (les non-lus et les mentions de toute la
 *  discussion ne sont pas captés). */
export const FILTERS: readonly (readonly [Filter, string])[] = [
  ["tout", "Tout"],
  ["elle", "Ses réponses"],
];

/** Ce qu'il faut d'une discussion pour son rond : son nom, sa sorte, sa clé, et sa photo (ADR 0300). */
export type ConvFace = Pick<Conversation, "title" | "kind" | "key" | "photo">;

/** Le rond d'une discussion : la personne d'un tête-à-tête (sa photo de Teams quand le serveur en a une, sinon ses
 *  initiales), un carré pour un groupe (son image n'est pas captée), l'agenda pour une réunion. */
export function convAvatar(c: ConvFace, size = ""): string {
  if (c.kind === "dm" || c.kind === "other") return avatar(c.title || "?", size, c.title || c.key, c.photo);
  const inner = c.kind === "meeting" ? ico("calendar", "sm") : h(initials(c.title.replace(/[^\p{L}\p{N}\s]/gu, "")) || "#");
  return `<span class="av sq grp${size ? ` ${size}` : ""}" title="${h(c.title)}">${inner}</span>`;
}

/** Ce que dit une ligne d'une réponse d'elle en chemin ; `decides` : tu décides sur son compte. */
function herMark(state: string, decides: boolean): string {
  const label = state === "attend" ? awaits(decides) : state === "pose" ? "posée dans Teams" : state === "en_file" || state === "approuve" ? "en file" : "brouillon de Mika";
  return `<span class="mk">${ico("pen")}${h(label)}</span>`;
}

/** Une discussion de la liste ; `account` : son compte (son nom quand il y en a plusieurs, et qui y est « Toi »). */
export function conversationRow(c: Conversation, selected: string, now: number, many: boolean, account: (AccountWho & Pick<TeamsAccount, "name">) | null): string {
  const last = c.last;
  // dans un tête-à-tête, l'autre n'a pas besoin d'être nommé ; la personne du compte, si (« Toi », ou son nom sur un
  // compte qu'on te partage)
  const who = last ? (last.own ? `${firstName(authorLabel(last, account))} : ` : c.kind !== "dm" ? `${firstName(last.author)} : ` : "") : "";
  const marks = [
    many ? `<span class="box-mark">${ico("teams", "xs")}${h(account?.name ?? c.account)}</span>` : "",
    c.her ? herMark(c.her.state, caps(account?.level ?? "lire").decide) : "",
    last?.mentions_me ? '<span class="badge soft" title="On t\'a mentionné">@</span>' : "",
  ].join("");
  return `<button class="li tm-li" type="button" data-disc="${h(c.key)}" aria-selected="${c.key === selected}">
    <span class="tm-av">${convAvatar(c)}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(c.title || "(sans titre)")}</span>${c.kind === "meeting" ? `<span class="tag">${ico("calendar", "xs")}réunion</span>` : ""}<time>${h(shortWhen(c.last_at, now))}</time></span>
      <span class="li-snip">${h(who + (last?.text ?? ""))}</span>
      ${marks ? `<span class="li-marks">${marks}</span>` : ""}</span></button>`;
}

export function listHead(filter: Filter, searching: boolean, q: string): string {
  if (searching) {
    return `<label class="search grow">${ico("search", "sm")}<input type="search" data-tq placeholder="Chercher une discussion" value="${h(q)}" aria-label="Chercher une discussion" maxlength="${TEAMS_LIMITS.search}"></label>
      <button class="btn icon ghost sm" type="button" title="Fermer la recherche" data-chercher>${ico("x", "sm")}</button>`;
  }
  return `<div class="seg" role="group" aria-label="Filtrer">${FILTERS.map(([k, l]) => `<button type="button" data-filtre="${k}" aria-pressed="${filter === k}">${h(l)}</button>`).join("")}</div>
    <span class="grow"></span><button class="btn icon ghost sm" type="button" title="Chercher une discussion" data-chercher>${ico("search", "sm")}</button>`;
}

export interface ThreadView {
  now: number;
  selfName: string;
  caps: Caps;
  owner: string;
  /** Le compte de la discussion : qui y est « Toi » (le tien), ou la personne d'un compte qu'on te partage ; `null`
   *  (pas encore lu) : personne n'y est « Toi ». */
  account: AccountWho | null;
  /** La réponse qu'on retouche ici (son identifiant). */
  editing: string;
  /** Ce que tu as écrit et qui n'est pas (encore) dans le fil : en file, en cours d'envoi, posé, ou pas parti
   *  (`ownBubbles`). */
  pending: readonly OwnBubble[];
}

/** La citation d'un message (ADR 0305), comme Teams la montre dans la bulle : l'auteur, l'heure, l'extrait ; elle mène
 *  au message cité quand il est dans le fil (`ref`). */
export function quoteCard(q: TeamsQuote, now: number): string {
  const inner = `<span class="tm-quote-head"><b>${h(q.author || "Quelqu'un")}</b>${q.at ? `<time>${h(dayAndClock(q.at, now))}</time>` : ""}</span><span class="tm-quote-text">${h(q.preview)}</span>`;
  return q.ref
    ? `<button type="button" class="tm-quote" data-tm-goto="${h(q.ref)}" title="Aller au message cité">${inner}</button>`
    : `<div class="tm-quote">${inner}</div>`;
}

/** Les discussions où un message part cité (ADR 0305, `QUOTE_KINDS` du serveur) : ni un canal (une réponse y est un
 *  fil), ni une réunion. */
const CITABLE = new Set(["dm", "group"]);

function message(m: TeamsMessage, mark: { day: string; suite: boolean }, v: ThreadView, replies: readonly Reply[], citable = false): string {
  const day = mark.day ? `<div class="day"><span>${h(mark.day)}</span></div>` : "";
  const name = authorLabel(m, v.account);
  // à droite seulement ce que tu as écrit, sur un compte à toi : sur un compte qu'on te partage, c'est son propriétaire
  const me = fromYou(m, v.account);
  const suite = mark.suite;
  // « Citer », comme la barre que Teams montre au survol d'un message (ADR 0305) : là où tu peux écrire
  const tools = v.caps.write && citable ? `<div class="tm-tools"><button class="btn icon ghost xs" type="button" data-tm-quote="${h(m.ref)}" title="Citer" aria-label="Citer ce message">${ico("quote", "sm")}</button></div>` : "";
  return `${day}<div class="tm-msg${me ? " me" : ""}${suite ? " suite" : ""}${m.mentions_me ? " mention" : ""}" data-ref="${h(m.ref)}">
    ${me || suite ? '<span class="tm-gut"></span>' : avatar(name, "sm", m.author_id || name, m.photo)}
    <div class="tm-body">${tools}${suite ? "" : `<div class="tm-meta"><b>${h(name)}</b><time title="${h(dayAndClock(m.at, v.now))}">${h(clock(m.at))}</time></div>`}
      ${m.quote ? quoteCard(m.quote, v.now) : ""}
      ${shownText(m) ? `<div class="tm-txt">${messageHtml(shownText(m), v.selfName, m.mentions_me)}</div>` : ""}
      ${images(m)}
      ${fromHer(m, replies) ? `<div class="by-mika">${ico("sparkle")}rédigé avec Mika</div>` : ""}
      ${reactionsHtml(m, v.account)}</div></div>`;
}

/** Les « [image] » du texte (ou « [image : ce que Mika y a vu] ») : l'image elle-même les remplace quand on l'a. */
const IMAGE_MARK = /\s*\[image(?: : [^\]\n]*)?\]/g;

function shownText(m: TeamsMessage): string {
  return m.images?.length ? m.text.replace(IMAGE_MARK, "").trim() : m.text;
}

/** Les images d'un message dans l'ordre où il les montre. */
export function imagesInOrder(m: TeamsMessage): TeamsImage[] {
  return [...(m.images ?? [])].sort((a, b) => a.position - b.position);
}

/** Ce que Mika voit sur une image, en une ligne courte (son texte de remplacement) : sans Markdown, coupé. */
function altOf(seen: string): string {
  const flat = seen.replace(/[*_`#>|]+/g, " ").replace(/\s+/g, " ").trim();
  return flat ? (flat.length > 240 ? `${flat.slice(0, 239)}…` : flat) : "image";
}

/** Ce que Mika voit sur une image, rendu (Markdown échappé : titres, listes, tableaux), sur toute la largeur. */
function seenBlock(seen: string, label: string): string {
  return `<section class="tm-seen"><div class="tm-seen-head">${ico("sparkle", "xs")}${h(label)}</div><div class="p2-md tm-seen-md">${pageHtml(seen)}</div></section>`;
}

/**
 * Ses images (ADR 0258), dans l'ordre du message : chacune s'ouvre en grand ici (`data-tm-img`) ; puis ce que Mika
 * voit sur chacune, sous elles, sur toute la largeur du message.
 */
function images(m: TeamsMessage): string {
  const all = imagesInOrder(m);
  if (!all.length) return "";
  const shown = all.map((i, n) => `<figure class="tm-img"><button class="tm-img-open" type="button" data-tm-img="${n}" data-tm-ref="${h(m.ref)}" title="Voir en grand"><img src="${h(teamsImageUrl(m.ref, i.id))}" alt="${h(altOf(i.seen))}" loading="lazy"></button></figure>`);
  const seen = all.map((i, n) => (i.seen.trim()
    ? seenBlock(i.seen, all.length > 1 ? `Ce que Mika voit sur l'image ${n + 1}` : "Ce que Mika y voit") : ""));
  return `<div class="tm-imgs">${shown.join("")}</div>${seen.join("")}`;
}

/** La visionneuse d'une image d'un message : en grand, « précédente » et « suivante » s'il en a plusieurs, et ce que
 *  Mika y voit. */
export function imageViewer(m: TeamsMessage, index: number): string {
  const all = imagesInOrder(m);
  if (!all.length) return `<div class="empty">${ico("image")}<p>Aucune image.</p></div>`;
  const n = ((index % all.length) + all.length) % all.length;
  const i = all[n];
  const nav = all.length > 1
    ? `<button class="btn icon vw-prev" type="button" data-vw="-1" title="Image précédente (←)" aria-label="Image précédente">${ico("chev-left")}</button>
       <button class="btn icon vw-next" type="button" data-vw="1" title="Image suivante (→)" aria-label="Image suivante">${ico("chev-right")}</button>` : "";
  return `<div class="viewer" data-viewer="${n}">
    <div class="vw-img"><img src="${h(teamsImageUrl(m.ref, i.id))}" alt="${h(altOf(i.seen))}">${nav}</div>
    ${i.seen.trim() ? `<div class="tm-vw-seen">${seenBlock(i.seen, "Ce que Mika y voit")}</div>` : ""}
    ${all.length > 1 ? `<p class="small muted tm-vw-count">${n + 1} / ${all.length}</p>` : ""}</div>`;
}

function pendingMessage(p: OwnBubble, v: ThreadView): string {
  // pas parti : son texte se reprend dans le champ, pour le renvoyer
  const again = p.failed && p.id && v.caps.write
    ? ` <button class="linkish" type="button" data-tm="reecrire" data-pending="${h(p.id)}">Le réécrire</button>`
    : "";
  return `<div class="tm-msg me pending${p.failed ? " failed" : ""}"${p.id ? ` data-own="${h(p.id)}"` : ""}><span class="tm-gut"></span>
    <div class="tm-body"><div class="tm-meta"><b>Toi</b><time title="${h(dayAndClock(p.at, v.now))}">${h(clock(p.at))}</time></div><div class="tm-txt">${h(p.text).replace(/\n/g, "<br>")}</div>
      <div class="tm-pending-note">${ico(p.failed ? "alert" : p.sent ? "check" : "clock", "xs")}<span>${h(p.note)}</span>${again}</div></div></div>`;
}

/** Sa réponse, quand on a répondu autrement dans la discussion (ADR 0199) : elle ne partira pas, et la carte le dit. */
function answeredCard(r: Reply): string {
  const text = r.preview?.text ?? r.body;
  return `<div class="tm-draft done" data-reply-card="${h(r.id)}">
    <div class="tm-draft-head">${mikaAvatar("xs")}<b>Mika avait préparé une réponse</b><span class="tag">refusée</span><span class="muted small">${h(clock(r.decided_at || r.at))}</span></div>
    ${text ? `<p class="tm-draft-text">« ${markToFill(h(text)).replace(/\n/g, "<br>")} »</p>` : ""}
    <p class="tm-draft-why">${ico("check", "xs")}<span>Répondu autrement, dans la discussion : elle ne partira pas.</span></p></div>`;
}

/** Une réponse d'elle en chemin, dans sa conversation. */
export function replyCard(r: Reply, v: ThreadView): string {
  if (r.answered) return answeredCard(r);
  // sur un compte qu'on te partage, ce qui part part sous le nom de sa personne, et son propriétaire décide
  const [tone, label] = cardState(r, sentUnder(v.account), v.caps.decide);
  const waiting = r.state === "attend";
  const text = r.preview?.text ?? r.body;
  const blocked = r.preview?.blocked || (waiting && r.to_fill ? "il reste des passages à compléter" : "");
  const editing = v.editing === r.id && waiting && v.caps.decide;
  const actions = waiting && v.caps.decide
    ? editing
      ? `<textarea rows="3" data-rep-texte aria-label="Ta version" maxlength="${TEAMS_LIMITS.body}">${h(r.body)}</textarea>
        <div class="row"><span class="small muted">Sans signature : elle est ajoutée.</span><span class="grow"></span><button class="btn xs ghost" type="button" data-rep="annuler">Annuler</button>
          <button class="btn xs primary" type="button" data-rep="enregistrer">${ico("check", "xs")}Enregistrer ta version</button></div>`
      : `<div class="row wrap"><span class="grow"></span><button class="btn xs ghost danger" type="button" data-rep="refuser">Refuser</button>
          ${r.in_reply_to ? `<button class="btn xs" type="button" data-rep="reprendre">${ico("refresh", "xs")}Lui demander de la reprendre</button>` : ""}
          <button class="btn xs" type="button" data-rep="retoucher">${ico("pen", "xs")}Retoucher</button>
          <button class="btn xs primary" type="button" data-rep="envoyer"${blocked || !r.preview ? " disabled" : ""}>${ico("send", "xs")}Envoyer d'ici</button></div>`
    : waiting
      ? `<p class="small muted">C'est ${h(v.owner || "le propriétaire du compte")} qui décide de ce qui part de ce compte.</p>`
      : "";
  return `<div class="tm-draft" data-reply-card="${h(r.id)}">
    <div class="tm-draft-head">${mikaAvatar("xs")}<b>Mika a préparé une réponse</b>${label ? `<span class="tag ${tone}">${h(label)}</span>` : ""}<span class="muted small">${h(clock(r.at))}</span></div>
    ${editing ? "" : `<p class="tm-draft-text">« ${markToFill(h(text)).replace(/\n/g, "<br>")} »</p>`}
    ${blocked && waiting ? `<div class="rd-block">${ico("alert", "sm")}Elle ne peut pas partir telle quelle : ${h(blocked)}. Retouche-la.</div>` : ""}
    ${actions}</div>`;
}

export function threadBody(t: Thread, older: readonly TeamsMessage[], v: ThreadView, loadingOlder: boolean, olderMore = false): string {
  const messages = [...older, ...t.messages];
  const marks = threadMarks(messages, v.now);
  const more = (older.length ? olderMore : t.more)
    ? `<div class="tm-more"><button class="btn xs ghost" type="button" data-plus-ancien${loadingOlder ? " disabled" : ""}>${ico("history", "xs")}${loadingOlder ? "Chargement…" : "Plus ancien"}</button></div>`
    : messages.length
      ? '<div class="tm-sys tm-start">Le début de ce que l\'extension a vu de cette discussion</div>'
      : "";
  const cards = threadCards(t.replies, messages.length ? messages[messages.length - 1].at : 0).map((r) => replyCard(r, v)).join("");
  const body = messages.length
    ? messages.map((m, i) => message(m, marks[i], v, t.replies, CITABLE.has(t.kind))).join("")
    : `<div class="empty tm-empty">${ico("teams")}<b>Rien encore</b><p>L'extension n'a rien vu passer dans cette discussion.</p></div>`;
  return `${more}${body}${v.pending.map((p) => pendingMessage(p, v)).join("")}${cards}`;
}

export interface ThreadHead {
  conv: ConvFace;
  sub: string;
  infoOpen: boolean;
}

export function threadHead(t: ThreadHead): string {
  return `<button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les discussions">${ico("chev-left", "sm")}</button><span class="tm-av">${convAvatar(t.conv)}</span>
    <div class="grow"><h2 class="ellipsis">${h(t.conv.title || "(sans titre)")}</h2><p class="small muted ellipsis">${h(t.sub)}</p></div>
    <button class="btn icon ghost sm${t.infoOpen ? " on" : ""}" type="button" data-info title="Informations">${ico("info", "sm")}</button>`;
}

export interface DockView {
  title: string;
  caps: Caps;
  owner: string;
  level: string;
  /** Elle prépare une réponse demandée. */
  asked: boolean;
  /** Où elle en est, en direct (ADR 0306) : l'étape et son chrono, sur une ligne ; `null` : rien en cours. */
  work?: Work | null;
  /** Une réponse d'elle est en chemin ici. */
  underWay: boolean;
  /** Le dernier message reçu (à quoi « Préremplir » répond). */
  canPrefill: boolean;
  /** Pourquoi elle n'y prépare rien (Teams coupé, ce compte décoché) : « Préremplir » le dit, éteint. */
  prefillOff?: string;
  /** « Corriger » marche (un modèle est donné au rôle `correct`, ADR 0307) ; sinon éteint, il dit pourquoi. */
  correct?: boolean;
  /** L'extension ne s'est pas manifestée depuis longtemps (ou jamais). */
  quiet: string;
  sending: boolean;
  /** Le message que tu cites (ADR 0305), au-dessus du champ : son auteur, son heure, un extrait ; `null` : aucun. */
  quoting?: { author: string; at: number; preview: string } | null;
  now?: number;
}

/** Où elle en est ici (ADR 0306) : sa ligne seule, que l'écran repeint dans sa case (`data-tm-work`) à chaque étape
 *  sans redessiner le champ ; un moteur qui ne le dit pas : « elle s'y met », sans chrono. */
export function dockWork(v: Pick<DockView, "asked" | "work" | "underWay" | "now">): string {
  if (v.underWay) return "";
  if (v.work) return workLine(v.work, v.now ?? Date.now(), "tm-asked");
  return v.asked ? `<div class="tm-asked">${mikaAvatar("xs")}<span>Elle s'y met… sa réponse arrivera ici, dans la discussion.</span></div>` : "";
}

export function dock(v: DockView): string {
  const asked = `<div class="tm-work" data-tm-work role="status">${dockWork(v)}</div>`;
  const quiet = v.quiet ? `<div class="tm-quiet">${ico("plug", "xs")}<span>${h(v.quiet)}</span></div>` : "";
  if (!v.caps.write) {
    const text = v.level === "preparer"
      ? `Ce compte t'est partagé en lecture et préparation : Mika peut t'y préparer une réponse, que ${v.owner || "son propriétaire"} approuve.`
      : `Ce compte t'est partagé en lecture : tu lis ses discussions, sans y écrire.`;
    return `${asked}<div class="tm-readonly">${ico("lock", "sm")}<span>${h(text)}</span>${v.caps.prepare ? `<button class="btn sm mika" type="button" data-tm="preremplir"${v.canPrefill && !v.underWay ? "" : ` disabled${v.prefillOff ? ` title="${h(v.prefillOff)}"` : ""}`}>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>` : ""}</div>`;
  }
  // la citation en cours, comme Teams la pose au-dessus du champ : un × l'enlève
  const quoting = v.quoting ? `<div class="tm-quoting"><div class="tm-quote"><span class="tm-quote-head"><b>${h(v.quoting.author || "Quelqu'un")}</b>${v.quoting.at ? `<time>${h(dayAndClock(v.quoting.at, v.now ?? Date.now()))}</time>` : ""}</span><span class="tm-quote-text">${h(v.quoting.preview)}</span></div><button class="btn icon ghost xs" type="button" data-tm="sans-citation" title="Ne plus citer" aria-label="Ne plus citer">${ico("x", "sm")}</button></div>` : "";
  return `${asked}${quiet}<div class="composer tm-cmp">${quoting}
    <textarea rows="2" data-tm-input placeholder="${v.title.trim() ? `Répondre dans « ${h(v.title.trim())} »…` : "Répondre…"}" aria-label="Ton message" maxlength="${TEAMS_LIMITS.body}"></textarea>
    <div class="cmp-bar"><button class="btn icon ghost sm" type="button" data-tm="emoji" title="Emojis">${ico("smile")}</button>
      <button class="btn sm mika" type="button" data-tm="preremplir"${v.canPrefill ? "" : ` disabled title="${h(v.prefillOff || "Aucun message reçu à quoi répondre")}"`}>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>${correctButton('data-tm="corriger"', !!v.correct)}
      <span class="grow"></span>${countSpan("", TEAMS_LIMITS.body)}<span class="small muted cmp-hint">${ico("external", "xs")}partira par l'extension, dans Teams, en ton nom</span>
      <button class="btn sm primary" type="button" data-tm="envoyer"${v.sending ? " disabled" : ""}>${ico("send", "sm")}<span class="lbl">Envoyer</span></button></div></div>`;
}

export interface InfoView {
  conv: Pick<Conversation, "title" | "kind" | "key" | "messages">;
  /** Ton nom (le rond de « Toi »). */
  selfName: string;
  /** `photo` : celle de Teams (ADR 0300), vide sans photo. */
  people: readonly { name: string; key: string; own: boolean; count: number; photo?: string }[];
  account: TeamsAccount | null;
  replies: readonly Reply[];
  now: number;
}

/** Un participant vu : « Toi » sur un compte à toi (le rond à ton nom) ; la personne d'un compte qu'on te partage, à
 *  son nom ; les autres, à leur nom. */
function participant(p: InfoView["people"][number], v: InfoView): string {
  const label = authorLabel({ own: p.own, author: p.name }, v.account);
  const yours = p.own && ownAccount(v.account);
  const face = yours ? v.selfName || label : label;
  return `<li>${avatar(face, "sm", yours ? v.selfName || p.key : p.key, p.photo)}<div><b>${h(label)}</b><small>${p.count} message${p.count > 1 ? "s" : ""} dans ce qui est chargé</small></div></li>`;
}

export function infoPane(v: InfoView): string {
  const a = v.account;
  const level = a ? levelTag(a.level) : "";
  const states = v.replies.reduce<Record<string, number>>((acc, r) => {
    const label = replyState(r, caps(a?.level ?? "lire").decide)[1].split(" · ")[0];
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  // en lecture seule, l'API ne dit rien de ses réponses (ADR 0188) : on n'en sait rien, ce n'est pas qu'il n'y en a pas
  const hers = a && !caps(a.level).prepare
    ? `<p class="small muted">Ses réponses sur ce compte sont l'affaire ${h(ofName(a.owner_name) || "de son propriétaire")}.</p>`
    : Object.keys(states).length
      ? `<p class="small text-2">${Object.entries(states).map(([k, n]) => `${n} ${h(k)}`).join(" · ")}</p>`
      : '<p class="small muted">Elle n\'a rien préparé dans cette discussion.</p>';
  return `<div class="pane-head"><h2>Informations</h2><span class="grow"></span>
      <button class="btn icon ghost sm" type="button" data-info title="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll tm-info-body">
      <h4>Participants vus <span class="cnt">${v.people.length}</span></h4>
      ${v.people.length ? `<ul class="tm-people">${v.people.map((p) => participant(p, v)).join("")}</ul>` : '<p class="small muted">Personne encore.</p>'}
      <h4>La discussion</h4>
      <p class="small text-2">${h(kindLabel(v.conv.kind))} · ${v.conv.messages} message${v.conv.messages > 1 ? "s" : ""} vus par l'extension</p>
      ${a ? `<h4>Le compte</h4>
      <p class="small text-2">${h(a.name)}${a.self_name ? ` · ${h(a.self_name)} dans Teams` : ""}${level ? ` · partagé avec toi par ${h(a.owner_name)} (${h(level)})` : ""}</p>
      <p class="small text-2">${ico("plug", "xs")} Extension : ${a.last_batch ? `dernier lot ${h(ago(a.last_batch, v.now))}` : "jamais branchée"}${a.extension_key ? ` · clé ${h(a.extension_key.hint)}…` : ""}</p>` : ""}
      <h4>Ses réponses ici</h4>
      ${hers}
    </div>`;
}

// ── Ses brouillons ───────────────────────────────────────────────────

export interface RepliesView {
  now: number;
  convs: ReadonlyMap<string, Conversation>;
  decide: (r: Reply) => boolean;
  /** La réponse qu'une route désigne (`#teams/brouillons/<id>`) : surlignée. */
  focus?: string;
}

/** « Ses brouillons » : un tableau ; sur un téléphone (sous 760 px), une carte par réponse — sa discussion et son
 *  état, ce qu'elle a écrit, puis quand et le geste (« Comment ça part » s'y efface). */
export function repliesTable(items: readonly Reply[], v: RepliesView): string {
  const lede = `<p class="lede">Ce que Mika a préparé ou envoyé dans Teams à ta place, et ce que c'est devenu. Tu relis et tu décides ici. Comment ça part se règle par personne ou par discussion : brouillon posé dans Teams (c'est toi qui l'envoies), ton accord, ou seule.</p>`;
  if (!items.length) {
    return `<div class="fill-scroll"><div class="page-pad">${lede}<div class="empty tm-empty">${ico("pen")}<b>Rien encore</b><p>Quand elle prépare une réponse dans une de tes discussions, elle arrive ici.</p></div></div></div>`;
  }
  const rows = items
    .map((r) => {
      const c = v.convs.get(r.conversation);
      const conv = { title: r.title || c?.title || "(discussion)", kind: c?.kind ?? "dm", key: r.conversation, photo: c?.photo };
      const [tone, label] = replyState(r, v.decide(r));
      const shown = r.state === "parti" && r.sent_text ? r.sent_text : r.preview?.text ?? r.body;
      const notes = [
        r.asked ? "demandée" : "d'elle-même",
        r.note ? `note : « ${r.note} »` : "",
        r.state === "parti" && retouched(r) && r.sent_text && r.body ? `elle avait écrit « ${r.body} »` : "",
      ].filter(Boolean);
      // répondu autrement : plus rien à décider, même avant que le moteur ne l'ait refusée (ADR 0199)
      const decide = r.state === "attend" && !r.answered && v.decide(r);
      const blocked = !!(r.preview?.blocked || r.to_fill);
      const focus = v.focus === r.id ? ' class="focus" aria-current="true"' : "";
      return `<tr data-reply-row="${h(r.id)}"${focus}><td class="tm-r-conv"><a href="#teams/discussions/${h(encodeURIComponent(r.conversation))}" class="row">${convAvatar(conv)}<b>${h(conv.title)}</b></a></td>
        <td class="tm-r-text">« ${markToFill(h(shown))} »<div class="tiny muted">${h(notes.join(" · "))}</div></td>
        <td class="small tm-r-mode" title="${h(modeTitle(r.mode))}">${h(modeLabel(r.mode))}</td>
        <td class="tm-r-state"><span class="tag ${tone}">${h(label)}</span></td><td class="small nowrap tm-r-when">${h(dayAndClock(r.at, v.now))}</td>
        <td class="actions">${decide ? `<button class="btn xs primary" type="button" data-rep="envoyer" data-id="${h(r.id)}"${blocked || !r.preview ? " disabled" : ""}>Envoyer d'ici</button>
          <button class="btn xs icon ghost" type="button" data-rep="plus" data-id="${h(r.id)}" title="Retoucher, refuser…">${ico("more", "xs")}</button>` : ""}</td></tr>`;
    })
    .join("");
  return `<div class="fill-scroll"><div class="page-pad">${lede}
    <table class="tbl tm-replies"><thead><tr><th>Discussion</th><th>Ce qu'elle a écrit</th><th>Comment ça part</th><th>Où ça en est</th><th>Quand</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

/** La pastille de l'extension (en haut à droite) : ce que le serveur sait d'elle — si elle est là, son dernier lot. */
export function extensionChip(a: TeamsAccount | null, now: number): string {
  if (!a) return "";
  // la pastille dit si elle est là (son dernier signe de vie) ; le texte, quand elle a poussé du neuf
  const seen = Math.max(a.last_seen || 0, a.last_batch || 0);
  const age = seen ? now - seen : Infinity;
  const dot = !seen ? "" : age < 15 * 60_000 ? "ok" : age < 24 * 3600_000 ? "warn" : "danger";
  return `<span class="ext-chip" title="Ce que le serveur sait de l'extension « Mika · Teams » de ce compte : son dernier signe de vie (la pastille), son dernier lot">${ico("plug", "sm")}<span class="dot ${dot}"></span><b>Extension</b><span class="muted">${a.last_batch ? `dernier lot ${h(ago(a.last_batch, now))}` : "jamais branchée"}</span></span>`;
}

export function capsOf(a: Pick<TeamsAccount, "level"> | null | undefined): Caps {
  return caps(a?.level ?? "lire");
}
