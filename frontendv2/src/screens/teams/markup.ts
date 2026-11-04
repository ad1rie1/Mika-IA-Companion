/**
 * Le rendu de Teams, celui de la maquette (`frontendv2/maquette/ecrans/teams.js`), nourri par l'API par personne :
 * la liste des discussions, le fil à la Teams, ses réponses en carte, le champ, le panneau d'informations et
 * « Ses brouillons ». Pur : des chaînes HTML, tout texte venu d'ailleurs échappé.
 */
import { h, initials } from "../../shell/dom";
import { ico } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { clock, dayAndClock, shortWhen } from "../chat/markup";
import { TEAMS_LIMITS, type Conversation, type Reply, type TeamsAccount, type TeamsMessage, type Thread } from "../../api/teams";
import { ago, avatar, caps, firstName, levelTag, markToFill, type Caps } from "../mail/format";
import { countSpan } from "../mail/markup";
import { cardState, fromHer, kindLabel, messageHtml, modeLabel, modeTitle, replyState, retouched, threadMarks, UNDER_WAY, type OwnBubble } from "./format";

export type Filter = "tout" | "elle" | "mentions";

/** Ce que l'API dit d'une discussion : sa réponse d'elle en chemin (les non-lus et les mentions de toute la
 *  discussion ne sont pas captés). */
export const FILTERS: readonly (readonly [Filter, string])[] = [
  ["tout", "Tout"],
  ["elle", "Ses réponses"],
];

/** Le rond d'une discussion : la personne d'un tête-à-tête, un carré pour un groupe, l'agenda pour une réunion. */
export function convAvatar(c: Pick<Conversation, "title" | "kind" | "key">, size = ""): string {
  if (c.kind === "dm" || c.kind === "other") return avatar(c.title || "?", size, c.title || c.key);
  const inner = c.kind === "meeting" ? ico("calendar", "sm") : h(initials(c.title.replace(/[^\p{L}\p{N}\s]/gu, "")) || "#");
  return `<span class="av sq grp${size ? ` ${size}` : ""}" title="${h(c.title)}">${inner}</span>`;
}

/** Ce que dit une ligne d'une réponse d'elle en chemin. */
function herMark(state: string): string {
  const label = state === "attend" ? "attend ton accord" : state === "pose" ? "posée dans Teams" : state === "en_file" || state === "approuve" ? "en file" : "brouillon de Mika";
  return `<span class="mk">${ico("pen")}${h(label)}</span>`;
}

export function conversationRow(c: Conversation, selected: string, now: number, many: boolean, accountName: string): string {
  const last = c.last;
  const who = last ? (last.own ? "Toi : " : c.kind !== "dm" ? `${firstName(last.author)} : ` : "") : "";
  const marks = [
    many ? `<span class="box-mark">${ico("teams", "xs")}${h(accountName)}</span>` : "",
    c.her ? herMark(c.her.state) : "",
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
  /** La réponse qu'on retouche ici (son identifiant). */
  editing: string;
  /** Ce que tu as écrit et qui n'est pas (encore) dans le fil : en file, en cours d'envoi, posé, ou pas parti
   *  (`ownBubbles`). */
  pending: readonly OwnBubble[];
}

function message(m: TeamsMessage, mark: { day: string; suite: boolean }, v: ThreadView, replies: readonly Reply[]): string {
  const day = mark.day ? `<div class="day"><span>${h(mark.day)}</span></div>` : "";
  const name = m.own ? "Toi" : m.author || "?";
  const suite = mark.suite;
  return `${day}<div class="tm-msg${m.own ? " me" : ""}${suite ? " suite" : ""}${m.mentions_me ? " mention" : ""}">
    ${m.own || suite ? '<span class="tm-gut"></span>' : avatar(name, "sm", m.author_id || name)}
    <div class="tm-body">${suite ? "" : `<div class="tm-meta"><b>${h(name)}</b><time title="${h(dayAndClock(m.at, v.now))}">${h(clock(m.at))}</time></div>`}
      ${m.text ? `<div class="tm-txt">${messageHtml(m.text, v.selfName, m.mentions_me)}</div>` : ""}
      ${fromHer(m, replies) ? `<div class="by-mika">${ico("sparkle")}rédigé avec Mika</div>` : ""}</div></div>`;
}

function pendingMessage(p: OwnBubble, v: ThreadView): string {
  // pas parti : son texte se reprend dans le champ, pour le renvoyer
  const again = p.failed && p.id && v.caps.write
    ? ` <button class="linkish" type="button" data-tm="reecrire" data-pending="${h(p.id)}">Le réécrire</button>`
    : "";
  return `<div class="tm-msg me pending${p.failed ? " failed" : ""}"${p.id ? ` data-own="${h(p.id)}"` : ""}><span class="tm-gut"></span>
    <div class="tm-body"><div class="tm-meta"><b>Toi</b><time title="${h(dayAndClock(p.at, v.now))}">${h(clock(p.at))}</time></div><div class="tm-txt">${h(p.text).replace(/\n/g, "<br>")}</div>
      <div class="tm-pending-note">${ico(p.failed ? "alert" : "clock", "xs")}<span>${h(p.note)}</span>${again}</div></div></div>`;
}

/** Une réponse d'elle en chemin, dans sa conversation. */
export function replyCard(r: Reply, v: ThreadView): string {
  const [tone, label] = cardState(r);
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
  const cards = t.replies.filter((r) => UNDER_WAY.has(r.state)).map((r) => replyCard(r, v)).join("");
  const body = messages.length
    ? messages.map((m, i) => message(m, marks[i], v, t.replies)).join("")
    : `<div class="empty tm-empty">${ico("teams")}<b>Rien encore</b><p>L'extension n'a rien vu passer dans cette discussion.</p></div>`;
  return `${more}${body}${v.pending.map((p) => pendingMessage(p, v)).join("")}${cards}`;
}

export interface ThreadHead {
  conv: Pick<Conversation, "title" | "kind" | "key">;
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
  /** Une réponse d'elle est en chemin ici. */
  underWay: boolean;
  /** Le dernier message reçu (à quoi « Préremplir » répond). */
  canPrefill: boolean;
  /** Pourquoi elle n'y prépare rien (Teams coupé, ce compte décoché) : « Préremplir » le dit, éteint. */
  prefillOff?: string;
  /** L'extension ne s'est pas manifestée depuis longtemps (ou jamais). */
  quiet: string;
  sending: boolean;
}

export function dock(v: DockView): string {
  const asked = v.asked && !v.underWay ? `<div class="tm-asked">${mikaAvatar("xs")}<span>Elle s'y met… sa réponse arrivera ici, dans la discussion.</span></div>` : "";
  const quiet = v.quiet ? `<div class="tm-quiet">${ico("plug", "xs")}<span>${h(v.quiet)}</span></div>` : "";
  if (!v.caps.write) {
    const text = v.level === "preparer"
      ? `Ce compte t'est partagé en lecture et préparation : Mika peut t'y préparer une réponse, que ${v.owner || "son propriétaire"} approuve.`
      : `Ce compte t'est partagé en lecture : tu lis ses discussions, sans y écrire.`;
    return `${asked}<div class="tm-readonly">${ico("lock", "sm")}<span>${h(text)}</span>${v.caps.prepare ? `<button class="btn sm mika" type="button" data-tm="preremplir"${v.canPrefill && !v.underWay ? "" : ` disabled${v.prefillOff ? ` title="${h(v.prefillOff)}"` : ""}`}>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>` : ""}</div>`;
  }
  return `${asked}${quiet}<div class="composer tm-cmp">
    <textarea rows="2" data-tm-input placeholder="Répondre dans « ${h(v.title)} »…" aria-label="Ton message" maxlength="${TEAMS_LIMITS.body}"></textarea>
    <div class="cmp-bar"><button class="btn icon ghost sm" type="button" data-tm="emoji" title="Emojis">${ico("smile")}</button>
      <button class="btn sm mika" type="button" data-tm="preremplir"${v.canPrefill ? "" : ` disabled title="${h(v.prefillOff || "Aucun message reçu à quoi répondre")}"`}>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>
      <span class="grow"></span>${countSpan("", TEAMS_LIMITS.body)}<span class="small muted cmp-hint">${ico("external", "xs")}partira par l'extension, dans Teams, en ton nom</span>
      <button class="btn sm primary" type="button" data-tm="envoyer"${v.sending ? " disabled" : ""}>${ico("send", "sm")}<span class="lbl">Envoyer</span></button></div></div>`;
}

export interface InfoView {
  conv: Pick<Conversation, "title" | "kind" | "key" | "messages">;
  /** Ton nom (le rond de « Toi »). */
  selfName: string;
  people: readonly { name: string; key: string; own: boolean; count: number }[];
  account: TeamsAccount | null;
  replies: readonly Reply[];
  now: number;
}

export function infoPane(v: InfoView): string {
  const a = v.account;
  const level = a ? levelTag(a.level) : "";
  const states = v.replies.reduce<Record<string, number>>((acc, r) => {
    const label = replyState(r)[1].split(" · ")[0];
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {});
  return `<div class="pane-head"><h2>Informations</h2><span class="grow"></span>
      <button class="btn icon ghost sm" type="button" data-info title="Fermer">${ico("x", "sm")}</button></div>
    <div class="pane-scroll tm-info-body">
      <h4>Participants vus <span class="cnt">${v.people.length}</span></h4>
      ${v.people.length ? `<ul class="tm-people">${v.people.map((p) => `<li>${avatar(p.own ? v.selfName || "Toi" : p.name, "sm", p.own ? v.selfName || p.key : p.key)}<div><b>${h(p.own ? "Toi" : p.name)}</b><small>${p.count} message${p.count > 1 ? "s" : ""} dans ce qui est chargé</small></div></li>`).join("")}</ul>` : '<p class="small muted">Personne encore.</p>'}
      <h4>La discussion</h4>
      <p class="small text-2">${h(kindLabel(v.conv.kind))} · ${v.conv.messages} message${v.conv.messages > 1 ? "s" : ""} vus par l'extension</p>
      ${a ? `<h4>Le compte</h4>
      <p class="small text-2">${h(a.name)}${a.self_name ? ` · ${h(a.self_name)} dans Teams` : ""}${level ? ` · partagé avec toi par ${h(a.owner_name)} (${h(level)})` : ""}</p>
      <p class="small text-2">${ico("plug", "xs")} Extension : ${a.last_batch ? `dernier lot ${h(ago(a.last_batch, v.now))}` : "jamais branchée"}${a.extension_key ? ` · clé ${h(a.extension_key.hint)}…` : ""}</p>` : ""}
      <h4>Ses réponses ici</h4>
      ${Object.keys(states).length ? `<p class="small text-2">${Object.entries(states).map(([k, n]) => `${n} ${h(k)}`).join(" · ")}</p>` : '<p class="small muted">Elle n\'a rien préparé dans cette discussion.</p>'}
    </div>`;
}

// ── Ses brouillons ───────────────────────────────────────────────────

export interface RepliesView {
  now: number;
  convs: ReadonlyMap<string, Conversation>;
  decide: (r: Reply) => boolean;
}

export function repliesTable(items: readonly Reply[], v: RepliesView): string {
  const lede = `<p class="lede">Ce que Mika a préparé ou envoyé dans Teams à ta place, et ce que c'est devenu. Tu relis et tu décides ici. Comment ça part se règle par personne ou par discussion : brouillon posé dans Teams (c'est toi qui l'envoies), ton accord, ou seule.</p>`;
  if (!items.length) {
    return `<div class="fill-scroll"><div class="page-pad">${lede}<div class="empty tm-empty">${ico("pen")}<b>Rien encore</b><p>Quand elle prépare une réponse dans une de tes discussions, elle arrive ici.</p></div></div></div>`;
  }
  const rows = items
    .map((r) => {
      const c = v.convs.get(r.conversation);
      const conv = { title: r.title || c?.title || "(discussion)", kind: c?.kind ?? "dm", key: r.conversation };
      const [tone, label] = replyState(r);
      const shown = r.state === "parti" && r.sent_text ? r.sent_text : r.preview?.text ?? r.body;
      const notes = [
        r.asked ? "demandée" : "d'elle-même",
        r.note ? `note : « ${r.note} »` : "",
        r.state === "parti" && retouched(r) && r.sent_text && r.body ? `elle avait écrit « ${r.body} »` : "",
      ].filter(Boolean);
      const decide = r.state === "attend" && v.decide(r);
      const blocked = !!(r.preview?.blocked || r.to_fill);
      return `<tr data-reply-row="${h(r.id)}"><td><a href="#teams/discussions/${h(encodeURIComponent(r.conversation))}" class="row">${convAvatar(conv)}<b>${h(conv.title)}</b></a></td>
        <td>« ${markToFill(h(shown))} »<div class="tiny muted">${h(notes.join(" · "))}</div></td>
        <td class="small" title="${h(modeTitle(r.mode))}">${h(modeLabel(r.mode))}</td>
        <td><span class="tag ${tone}">${h(label)}</span></td><td class="small nowrap">${h(dayAndClock(r.at, v.now))}</td>
        <td class="actions">${decide ? `<button class="btn xs primary" type="button" data-rep="envoyer" data-id="${h(r.id)}"${blocked || !r.preview ? " disabled" : ""}>Envoyer d'ici</button>
          <button class="btn xs icon ghost" type="button" data-rep="plus" data-id="${h(r.id)}" title="Retoucher, refuser…">${ico("more", "xs")}</button>` : ""}</td></tr>`;
    })
    .join("");
  return `<div class="fill-scroll"><div class="page-pad">${lede}
    <table class="tbl"><thead><tr><th>Discussion</th><th>Ce qu'elle a écrit</th><th>Comment ça part</th><th>Où ça en est</th><th>Quand</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
}

/** La pastille de l'extension (en haut à droite) : ce que le serveur sait d'elle, son dernier lot. */
export function extensionChip(a: TeamsAccount | null, now: number): string {
  if (!a) return "";
  const age = a.last_batch ? now - a.last_batch : Infinity;
  const dot = !a.last_batch ? "" : age < 15 * 60_000 ? "ok" : age < 24 * 3600_000 ? "warn" : "danger";
  return `<span class="ext-chip" title="Ce que le serveur sait de l'extension « Mika · Teams » de ce compte : son dernier lot">${ico("plug", "sm")}<span class="dot ${dot}"></span><b>Extension</b><span class="muted">${a.last_batch ? `dernier lot ${h(ago(a.last_batch, now))}` : "jamais branchée"}</span></span>`;
}

export function capsOf(a: Pick<TeamsAccount, "level"> | null | undefined): Caps {
  return caps(a?.level ?? "lire");
}
