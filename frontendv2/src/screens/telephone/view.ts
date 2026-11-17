/**
 * Téléphone : ce qui se montre, sans DOM — ses onglets, les mots d'une proposition de Mika, l'icône d'une appli, le fil
 * (repères de jour, messages, propositions), ce que dit un téléphone d'où rien ne vient, la phrase qui en parle à Mika
 * dans le chat, la position, son plan dessiné et son lien OpenStreetMap, l'état de ses téléphones dans la barre de
 * titre. Le balisage est celui de la maquette (`frontendv2/maquette/ecrans/telephone.js`), sauf son onglet
 * Notifications, qui attend que l'application lise d'autres apps que les messageries, son sélecteur de téléphones, qui
 * attend que chaque message dise le sien (ADR 0190, 0233), et le plan de la position : celui de la Carte
 * (`map/drawn.ts`), le point et sa précision sans les rues ni la rivière, inventées, de la maquette.
 */
import type { Phone, PhoneConversation, PhoneMessage, PhoneOffer, PhonePosition, PhoneThread } from "../../api/phone";
import { drawnScene } from "../../map/drawn";
import type { Scene } from "../../map/scene";
import { mikaAvatar } from "../../mika/face";
import { h, initials, norm } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import type { ScreenTab } from "../../shell/shell";
import { plainHtml } from "../chat/markup";
import { ago, clock, dayWords, personAvatar, remaining, shortWhen } from "../../shared/kit";

/**
 * Les onglets de l'écran. Pas de Notifications tant que l'application ne lit que les messageries : il ne ferait que
 * redire Messages ; une ancienne adresse `#telephone/notifications` retombe sur Messages (ADR 0233).
 */
export const TELEPHONE_TABS: readonly Readonly<ScreenTab>[] = [
  { id: "messages", title: "Messages" },
  { id: "position", title: "Position" },
];

// ── Les mots ─────────────────────────────────────────────────────────

/** Ce qu'est devenue une réponse proposée : [ton de l'étiquette, mots]. */
export const OFFER_WORDS: Record<string, [string, string]> = {
  prepared: ["mika", "préparée"],
  offered: ["warn", "au téléphone — attend ton geste"],
  sent: ["ok", "envoyée"],
  other: ["", "tu as écrit autre chose"],
  copied: ["info", "copiée"],
  ignored: ["", "laissée"],
  failed: ["danger", "échec"],
  expired: ["", "expirée"],
};

export function offerWords(state: string): [string, string] {
  return OFFER_WORDS[state] ?? ["", state];
}

/** Une proposition encore en chemin (préparée, ou au téléphone). */
export function underWay(state: string): boolean {
  return state === "prepared" || state === "offered";
}

/** L'icône d'une appli (la classe de couleur de la feuille commune, une lettre). */
export function appBadge(app: string, appName: string): { cls: string; letter: string } {
  if (app === "whatsapp" || app === "whatsapp_business") return { cls: "whatsapp", letter: "W" };
  if (app === "messages" || app === "samsung_messages" || app === "sms") return { cls: "sms", letter: "M" };
  return { cls: "other", letter: (appName.trim()[0] ?? "?").toUpperCase() };
}

export function appIcon(app: string, appName: string): string {
  const b = appBadge(app, appName);
  return `<span class="app-ico ${b.cls}" title="${h(appName)}">${h(b.letter)}</span>`;
}

/** Le nom court d'un téléphone : « samsung SM-S931B » pour « Android · samsung SM-S931B ». */
export function shortPhone(label: string): string {
  return label.replace(/^Android\s*·\s*/u, "").trim() || label || "Téléphone";
}

/** Ses téléphones qui reçoivent encore. */
export function activePhones(phones: readonly Phone[]): Phone[] {
  return phones.filter((p) => !p.revoked);
}

/**
 * Le téléphone d'où vient ce qu'on lit (« Envoyée par », sous sa position), quand on peut le dire : un seul téléphone
 * a jamais servi à son compte (le serveur ne note pas encore quel téléphone a reçu quoi : un moyen de communication par
 * compte).
 */
export function onlyPhone(phones: readonly Phone[]): Phone | null {
  return phones.length === 1 ? phones[0] : null;
}

/** L'adresse OpenStreetMap d'une position, épinglée, au zoom d'une rue. */
export function osmUrl(lat: number, lon: number, zoom = 17): string {
  const la = lat.toFixed(6);
  const lo = lon.toFixed(6);
  return `https://www.openstreetmap.org/?mlat=${la}&mlon=${lo}#map=${zoom}/${la}/${lo}`;
}

/** « 12 m », « 1,2 km ». */
export function distanceWords(meters: number): string {
  if (!Number.isFinite(meters) || meters <= 0) return "";
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} km`;
}

// ── Les conversations ────────────────────────────────────────────────

export function conversationTitle(c: Pick<PhoneConversation, "title" | "app_name">): string {
  return c.title.trim() || c.app_name || "Conversation";
}

export function matches(c: PhoneConversation, q: string): boolean {
  const needle = norm(q.trim());
  if (!needle) return true;
  return norm(`${conversationTitle(c)} ${c.app_name} ${c.last.text}`).includes(needle);
}

/** Qui a écrit le dernier message, devant son texte : « Toi : », « Julien : » dans un groupe, rien sinon. */
export function snippetOf(c: PhoneConversation): string {
  const who = c.last.own ? "Toi : " : c.group && c.last.sender ? `${c.last.sender.split(/\s+/)[0]} : ` : "";
  return `${who}${c.last.text}`;
}

/**
 * La marque d'une conversation d'après la réponse de Mika qui y compte (`her`) : [ton de l'étiquette, mots], ou rien.
 * En chemin, elle attend ton geste ; partie, copiée ou en échec, c'est une nouvelle ; laissée, remplacée par ce que tu
 * as écrit ou expirée, non.
 */
export function herMark(c: Pick<PhoneConversation, "her">): [string, string] | null {
  const state = c.her?.state ?? "";
  if (underWay(state)) return ["warn", "réponse proposée"];
  if (state === "sent") return ["ok", "Mika a répondu"];
  if (state === "copied") return ["info", "copiée"];
  if (state === "failed") return ["danger", "échec"];
  return null;
}

/**
 * Cette marque dans la liste : ce que fait Mika garde son rose (ADR 0187), plus discret une fois réglé ; un échec se
 * dit en rouge.
 */
function herBadge(c: PhoneConversation): string {
  const mark = herMark(c);
  if (!mark || !c.her) return "";
  const [tone, words] = mark;
  if (tone === "danger") return `<span class="tag danger">${ico("alert")}${h(words)}</span>`;
  if (underWay(c.her.state)) return `<span class="mk">${ico("pen")}${h(words)}</span>`;
  return `<span class="mk quiet">${ico(c.her.state === "copied" ? "copy" : "check")}${h(words)}</span>`;
}

function avatarOf(title: string, group: boolean, size?: "lg"): string {
  if (group) {
    const letters = initials(title.replace(/[^\p{L}\p{N}\s]/gu, " ")) || "?";
    return `<span class="av sq grp${size ? ` ${size}` : ""}" title="${h(title)}">${h(letters)}</span>`;
  }
  return personAvatar(title, size);
}

export function conversationItem(c: PhoneConversation, selected: boolean, now: number): string {
  const title = conversationTitle(c);
  const her = herBadge(c);
  return `<button class="li conv" type="button" data-conv="${h(c.key)}" aria-selected="${selected}">
    <span class="conv-av">${avatarOf(title, c.group)}${appIcon(c.app, c.app_name)}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(title)}</span><time>${h(shortWhen(c.last_at, now))}</time></span>
      <span class="li-snip">${h(snippetOf(c))}</span>
      ${her ? `<span class="li-marks">${her}</span>` : ""}</span></button>`;
}

/** La phrase qui ouvre le chat depuis un fil (« Lui en parler dans le chat ») : elle nomme la conversation, à compléter. */
export function askAboutConversation(c: Pick<PhoneConversation, "title" | "app_name" | "group">): string {
  const app = c.app_name.trim();
  const on = app ? ` ${app}` : "";
  const title = c.title.trim();
  if (!title) return `À propos d'une de mes conversations${on} : `;
  return `À propos de ma conversation${on} avec ${c.group ? "le groupe " : ""}${title} : `;
}

// ── Quand rien ne vient du téléphone ─────────────────────────────────

/** Ce que dit un compte qui n'est pas propriétaire : Mika ne lit pas ses messages, et ce n'est pas un réglage. */
export const NOT_OWNER_NOTE =
  "Mika ne lit les messages du téléphone que pour une de ses propriétaires. Ta position, elle, se voit dans l'onglet Position.";

/** Le pourquoi d'un téléphone d'où rien ne vient, et le lien qui mène où l'on peut quelque chose. */
export interface EmptyPhone {
  text: string;
  href: string;
  icon: IconName;
  label: string;
}

/**
 * Pourquoi aucun message ne vient de son téléphone. La porte du téléphone refuse tout lot d'un compte qui n'est pas
 * propriétaire (`backendv2/src/mika/app/phone.py`) : à lui, la vraie raison et sa position, qui se voit — pas un réglage
 * qui ne peut rien pour lui. `owner` : celui de `GET /api/moi` ; pas encore lu (`undefined`), le conseil d'une
 * propriétaire. `phones` : combien de téléphones son compte a connus.
 */
export function emptyPhone(owner: boolean | undefined, phones: number): EmptyPhone {
  if (owner === false) return { text: NOT_OWNER_NOTE, href: "#telephone/position", icon: "pin", label: "Ta position" };
  return {
    text: phones
      ? "Sur ton téléphone, allume « Lui montrer mes messages » : Mika lira tes conversations WhatsApp et Messages."
      : "Installe Mika sur ton téléphone et connecte-toi : elle lira tes conversations WhatsApp et Messages, si tu le lui permets.",
    href: "#parametres/telephones",
    icon: "settings",
    label: "Tes téléphones",
  };
}

function emptyBlock(icon: IconName, title: string, e: EmptyPhone): string {
  return `<div class="empty">${ico(icon)}<b>${h(title)}</b><p>${h(e.text)}</p>
    <a class="btn sm" href="${h(e.href)}">${ico(e.icon, "sm")}${h(e.label)}</a></div>`;
}

/** L'onglet Messages sans aucune conversation. */
export function emptyMessagesMarkup(owner: boolean | undefined, phones: number): string {
  return `<div class="fill-scroll">${emptyBlock("phone", "Aucun message de ton téléphone", emptyPhone(owner, phones))}</div>`;
}

// ── Le fil ───────────────────────────────────────────────────────────

export type ThreadItem =
  | { kind: "day"; label: string }
  | { kind: "message"; message: PhoneMessage }
  | { kind: "offer"; offer: PhoneOffer };

/** Les messages et ses propositions, dans l'ordre du temps, avec un repère à chaque jour nouveau. */
export function timeline(messages: readonly PhoneMessage[], offers: readonly PhoneOffer[], now: number): ThreadItem[] {
  const all: { at: number; rank: number; item: ThreadItem }[] = [
    ...messages.map((m) => ({ at: m.at, rank: 0, item: { kind: "message", message: m } as ThreadItem })),
    ...offers.map((o) => ({ at: o.at, rank: 1, item: { kind: "offer", offer: o } as ThreadItem })),
  ].sort((a, b) => a.at - b.at || a.rank - b.rank);
  const out: ThreadItem[] = [];
  let day = "";
  for (const { at, item } of all) {
    const label = dayWords(at, now);
    if (label !== day) {
      out.push({ kind: "day", label });
      day = label;
    }
    out.push(item);
  }
  return out;
}

function messageMarkup(m: PhoneMessage, group: boolean): string {
  if (m.own) {
    return `<div class="tmsg me"><div class="bubble">${plainHtml(m.text)}</div><div class="msg-meta">${h(clock(m.at))}</div></div>`;
  }
  const who = m.sender || "?";
  return `<div class="tmsg them">${group ? personAvatar(who, "sm") : ""}<div class="msg-col">${group ? `<span class="tmsg-who">${h(who)}</span>` : ""}
    <div class="bubble">${plainHtml(m.text)}</div><div class="msg-meta">${h(clock(m.at))}</div></div></div>`;
}

/** « expire dans 1 h 52 » ; passée, « échue ». */
function expiry(until: number, now: number): string {
  const left = remaining(until, now);
  return left === "échue" ? left : `expire ${left}`;
}

/** Le titre d'une réponse de Mika dans le fil : proposée tant qu'elle est en chemin, puis partie ou non. */
export function offerTitle(state: string): string {
  if (underWay(state)) return "Réponse proposée par Mika";
  return state === "sent" || state === "copied" ? "Réponse de Mika" : "Réponse de Mika, non partie";
}

/**
 * Une réponse que Mika a proposée, et ce qu'elle est devenue (rien ne se décide d'ici : le geste est au téléphone).
 * Réglée, sa carte garde le rose de Mika, atténué (`settled`) : ce n'est pas une bulle à toi.
 */
export function offerMarkup(o: PhoneOffer, thread: Pick<PhoneThread, "app_name">, title: string, now: number): string {
  const [cls, words] = offerWords(o.state);
  // à côté de l'étiquette, pas dedans : sur un téléphone, l'une et l'autre passent à la ligne sans sortir de la carte
  const when = o.state === "offered" && o.expires ? expiry(o.expires, now) : o.decided_at && !underWay(o.state) ? ago(o.decided_at, now) : "";
  const icon: IconName = o.state === "offered" || o.state === "prepared" ? "phone" : o.state === "sent" ? "check" : o.state === "failed" ? "alert" : "x";
  const help = o.state === "offered"
    ? `<p class="prop-help">Ton téléphone affiche « Répondre à ${h(title)} (${h(thread.app_name)}) ? » avec Envoyer, Écrire autre chose et Ignorer : ton geste vaut accord.</p>`
    : o.state === "prepared" ? `<p class="prop-help">Elle part à ton téléphone, qui te demandera ton geste.</p>` : "";
  return `<div class="prop${underWay(o.state) ? "" : " settled"}"${o.reason ? ` title="${h(o.reason)}"` : ""}>
    <div class="prop-head">${mikaAvatar("xs")}<b>${h(offerTitle(o.state))}</b><span class="muted small">${h(clock(o.at))}</span></div>
    <div class="prop-txt">« ${plainHtml(o.text)} »</div>
    <div class="prop-foot"><span class="tag ${cls}">${ico(icon)}${h(words)}</span>${when ? `<span class="small muted">${h(when)}</span>` : ""}</div>${help}
  </div>`;
}

export function threadMarkup(t: PhoneThread, title: string, now: number): string {
  const items = timeline(t.messages, t.offers, now);
  const body = items
    .map((it) => {
      if (it.kind === "day") return `<div class="day"><span>${h(it.label)}</span></div>`;
      if (it.kind === "offer") return offerMarkup(it.offer, t, title, now);
      return messageMarkup(it.message, t.group);
    })
    .join("");
  const more = t.more ? `<div class="day"><span>Les messages plus anciens ne sont pas montrés ici</span></div>` : "";
  return more + body;
}

/** Ce que dit la saisie coupée : son début seul sur un téléphone (une ligne), la suite sur un écran plus large. */
export const COMPOSER_NOTE = "Répondre d'ici arrive bientôt";
export const COMPOSER_NOTE_MORE =
  "pour l'instant, Mika prépare ses réponses quand tu lui en parles dans le chat, et ton téléphone te demande le geste";

/**
 * La saisie, coupée tant que l'API ne sait pas envoyer depuis le web (ADR 0189) ni préremplir (ADR 0191). Sur un
 * téléphone, elle se réduit à sa note (`telephone.css`) : ni cadre ni boutons qui ne font rien.
 */
export function composerMarkup(title: string): string {
  return `<div class="tel-dock">
    <div class="composer tel-cmp" aria-disabled="true">
      <textarea rows="1" disabled placeholder="Ta réponse à ${h(title)}…" aria-label="Ta réponse"></textarea>
      <div class="cmp-bar"><button class="btn sm mika" type="button" disabled>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>
        <span class="grow"></span>
        <button class="btn sm primary" type="button" disabled>${ico("send", "sm")}<span class="lbl">Envoyer</span></button></div>
    </div>
    <p class="tel-soon small muted">${ico("info", "xs")}<span>${h(COMPOSER_NOTE)}<span class="tel-soon-more"> : ${h(COMPOSER_NOTE_MORE)}</span>.</span></p></div>`;
}

/**
 * L'en-tête d'un fil : la conversation, son appli, ses messages. Il ne nomme pas de téléphone : le serveur ne dit pas
 * lequel a reçu quel message, et la barre de titre dit déjà les tiens (`phoneState`).
 */
export function threadHead(c: PhoneConversation): string {
  const title = conversationTitle(c);
  const parts = [c.group ? `Groupe ${c.app_name}` : c.app_name, `${c.count} message${c.count > 1 ? "s" : ""}`];
  return `<div class="pane-head thread-head"><button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les conversations">${ico("chev-left", "sm")}</button>
    ${avatarOf(title, c.group, "lg")}
    <div class="grow"><h2>${h(title)} ${appIcon(c.app, c.app_name)}</h2><p class="small muted">${h(parts.join(" · "))}</p></div>
    <button class="btn icon ghost sm" type="button" title="Plus" data-more>${ico("more")}</button></div>`;
}

// ── La position ──────────────────────────────────────────────────────

/**
 * Ce que la carte de la position montre, vraie carte ou plan : son point et le cercle de sa précision, rien d'autre ;
 * sans coordonnées, rien. La vraie carte s'ouvre centrée sur elle, au zoom qui montre son cercle (`map/view.ts`).
 */
export function positionScene(coords: { lat: number; lon: number } | null, accuracy: number): Scene {
  return { pins: [], lines: [], here: coords ? { lat: coords.lat, lon: coords.lon, accuracy_m: accuracy } : null };
}

/**
 * Le plan dessiné de la position, quand sa vraie carte ne se dessine pas : le point et le cercle de sa précision, à
 * l'échelle, sur le fond quadrillé du plan de la Carte (`map/drawn.ts`) — un plan, pas une carte : aucune rue, aucune
 * rivière n'y est inventée autour de la vraie position. Sans coordonnées, le plan vide (sa note dit pourquoi).
 */
export function positionPlan(coords: { lat: number; lon: number } | null, accuracy: number, label: string): string {
  const title = coords ? `Plan autour de ${label || "ta position"}` : "Plan vide : le serveur n'a pas les coordonnées de ta position";
  return drawnScene(positionScene(coords, accuracy), { width: 800, height: 560, title, pad: 48 });
}

/**
 * La position : sa carte (`live` : la vraie, servie par ce serveur et dessinée par MapLibre dans `[data-map]` ; si elle
 * se montre, et sa vie, c'est `map/live.ts`), sinon son plan dessiné (`positionPlan`) et sa note ; à côté, ce qu'on en
 * sait.
 */
export function positionMarkup(p: PhonePosition, phone: Phone | null, now: number, live = false): string {
  if (!p.known) {
    return `<div class="fill-scroll"><div class="empty">${ico("pin")}<b>Mika ne sait pas où tu es</b>
      <p>Ton téléphone ne lui a pas donné ta position, ou elle a été effacée. Sur le téléphone, « Lui dire où je suis » est coupé par défaut.</p>
      <a class="btn sm" href="#parametres/telephones">${ico("phone", "sm")}Tes téléphones</a></div></div>`;
  }
  const label = p.label.trim();
  const accuracy = distanceWords(p.accuracy_m);
  const when = p.at ? `${dayWords(p.at, now).toLowerCase()} à ${clock(p.at)}` : "";
  const legend = [accuracy ? `à ${accuracy} près` : "", when].filter(Boolean).join(" · ");
  const coords = p.coords;
  const link = coords
    ? `<a class="btn sm" href="${h(osmUrl(coords.lat, coords.lon))}" target="_blank" rel="noopener">${ico("external", "sm")}Ouvrir dans OpenStreetMap</a>`
    : "";
  return `<div class="split pos-split">
    <section class="pane map-pane">${live
      ? `<div class="map-live" data-map role="region" aria-label="Carte autour de ${h(label || "ta position")}"></div>`
      : positionPlan(coords, p.accuracy_m, label)}<div class="map-legend">${ico("pin", "sm")}<b>${h(label || "Ta position")}</b>${legend ? `<span class="muted">${h(legend)}</span>` : ""}</div>
      ${live ? "" : `<p class="map-note small muted">Un plan dessiné, pas une carte : ${coords ? "le lien ouvre la vraie, sur OpenStreetMap." : "le serveur n'a pas ses coordonnées."}</p>`}</section>
    <aside class="pane"><div class="pane-scroll pos-side">
      <h2 class="section-title">Ta dernière position</h2>
      <dl class="kv"><dt>Lieu</dt><dd><b>${h(label || "—")}</b></dd>
        <dt>Précision</dt><dd>${h(accuracy ? `à ${accuracy} près` : "—")}</dd>
        <dt>Position de</dt><dd>${h(when || "—")}</dd>
        <dt>Coordonnées</dt><dd class="mono">${coords ? h(`${coords.lat.toFixed(6)}, ${coords.lon.toFixed(6)}`) : "—"}</dd>
        ${phone ? `<dt>Envoyée par</dt><dd>${h(phone.label)}, application ouverte</dd>` : ""}</dl>
      ${link ? `<div class="row pos-actions">${link}</div>` : ""}
      <div class="pos-switch">${ico("pin")}<div><b>Lui dire où je suis</b>
        <p class="small muted">Réglé sur le téléphone, coupé par défaut. Il ne donne ta position que quand l'application est ouverte.</p></div></div>
      <p class="small muted">Elle ne regarde où tu es que quand vous vous parlez en tête-à-tête, jamais d'elle-même ; chaque regard laisse une bulle 📍 dans le chat.</p>
    </div></aside></div>`;
}

// ── Les téléphones, dans la barre de titre ───────────────────────────

/**
 * Ce que dit le point d'un téléphone : s'il reçoit les notifications de Mika, même application fermée (`push` : il a
 * donné où le notifier, ADR 0077).
 */
export function pushNote(push: boolean): string {
  return push ? "reçoit les notifications" : "ne reçoit pas les notifications";
}

/** Ce que dit le point de plusieurs téléphones. */
function pushNotes(phones: readonly Phone[]): string {
  const without = phones.filter((p) => !p.push).length;
  if (!without) return `les ${phones.length} reçoivent les notifications`;
  if (without === phones.length) return "aucun ne reçoit les notifications";
  return `${without} sur ${phones.length} ne ${without > 1 ? "reçoivent" : "reçoit"} pas les notifications`;
}

/** « vu il y a 4 min » ; rien pour un téléphone qui n'a jamais servi. */
function seenWords(lastUsed: number, now: number): string {
  const when = ago(lastUsed, now);
  return when ? `vu ${when}` : "";
}

/** L'état de ses téléphones, tel que la barre de titre le dit. */
export interface PhoneState {
  /** « Google Pixel 8 » (un seul actif), « 2 téléphones », « Aucun téléphone ». */
  label: string;
  /** « vu il y a 4 min » : le dernier usage, du plus récent de ses téléphones ; rien s'il n'a jamais servi. */
  seen: string;
  /** Le ton du point : `ok`, tous reçoivent les notifications ; `warn`, pas tous ; `null`, aucun téléphone, pas de point. */
  dot: "ok" | "warn" | null;
  /** Le sens du point, en mots (« ne reçoit pas les notifications »). */
  push: string;
  /** Tout ce qu'il dit, téléphone par téléphone, et où il mène : l'infobulle et le nom que lit un lecteur d'écran. */
  title: string;
}

/** Où mène l'état : Paramètres › Téléphones, qui les détaille, en connecte un ou en révoque un. */
export const PHONES_HREF = "#parametres/telephones";

/**
 * L'état de ses téléphones (les actifs ; un révoqué ne reçoit plus rien) : un état, pas un choix. Le serveur ne dit pas
 * encore quel téléphone a reçu quel message (ADR 0190, *À venir*) : choisir l'un d'eux ne trierait rien (ADR 0233).
 */
export function phoneState(phones: readonly Phone[], now: number): PhoneState {
  const active = activePhones(phones);
  if (!active.length) {
    return { label: "Aucun téléphone", seen: "", dot: null, push: "", title: "Aucun téléphone : en connecter un, dans Paramètres › Téléphones" };
  }
  const seen = seenWords(Math.max(...active.map((p) => p.last_used)), now);
  const dot = active.every((p) => p.push) ? "ok" : "warn";
  const sentence = (p: Phone) => [seenWords(p.last_used, now), pushNote(p.push)].filter(Boolean).join(", ");
  if (active.length === 1) {
    const one = active[0];
    const label = shortPhone(one.label);
    return { label, seen, dot, push: pushNote(one.push), title: `${label}, ${sentence(one)} — Paramètres › Téléphones` };
  }
  const label = `${active.length} téléphones`;
  const each = active.map((p) => `${shortPhone(p.label)} : ${sentence(p)}`).join(" ; ");
  return { label, seen, dot, push: pushNotes(active), title: `${label} — ${each} — Paramètres › Téléphones` };
}

/**
 * L'état dans la barre de titre : un lien vers Paramètres › Téléphones. Le sens du point se lit au survol et par un
 * lecteur d'écran (`title`, `aria-label`) ; quand tous ne reçoivent pas les notifications, aussi en clair sur un grand
 * écran (`tel-push`). Sur un téléphone, le nom et le point restent (`telephone.css`).
 */
export function phoneStateMarkup(s: PhoneState): string {
  const dot = s.dot ? `<span class="dot ${s.dot}" title="${h(s.push)}"></span>` : "";
  const push = s.dot === "warn" ? `<span class="tel-push">${h(s.push)}</span>` : "";
  const seen = s.seen ? `<span class="muted tel-seen">${h(s.seen)}</span>` : "";
  return `<a class="phone-state" href="${PHONES_HREF}" data-tel-state title="${h(s.title)}" aria-label="${h(s.title)}">${ico("phone", "sm")}<b>${h(s.label)}</b>${dot}${push}${seen}</a>`;
}
