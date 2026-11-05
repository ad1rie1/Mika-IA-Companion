/**
 * Téléphone : ce qui se montre, sans DOM — les mots d'une proposition de Mika, l'icône d'une appli, le fil (repères
 * de jour, messages, propositions), les conversations rangées par appli, la position et son lien OpenStreetMap. Le
 * balisage est celui de la maquette (`frontendv2/maquette/ecrans/telephone.js`).
 */
import type { MapInfo, Phone, PhoneConversation, PhoneMessage, PhoneOffer, PhonePosition, PhoneThread } from "../../api/phone";
import { infoKey } from "../../map/info";
import { covers } from "../../map/mapgeo";
import { mikaAvatar } from "../../mika/face";
import { h, initials, norm } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { plainHtml } from "../chat/markup";
import { ago, clock, dayWords, personAvatar, remaining, shortWhen } from "../parametres/kit";

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

export function appIcon(app: string, appName: string, large = false): string {
  const b = appBadge(app, appName);
  return `<span class="app-ico ${b.cls}${large ? " lg" : ""}" title="${h(appName)}">${h(b.letter)}</span>`;
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
 * Le téléphone d'où viennent ses messages, quand on peut le dire : un seul téléphone a jamais servi à son compte
 * (le serveur ne note pas encore quel téléphone a reçu quoi : un moyen de communication par compte).
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

/** Ses conversations rangées par appli, dans l'ordre où elles arrivent (la plus récente d'abord). */
export function byApp(items: readonly PhoneConversation[]): { app: string; name: string; items: PhoneConversation[] }[] {
  const out: { app: string; name: string; items: PhoneConversation[] }[] = [];
  for (const c of items) {
    const name = c.app_name || c.app;
    let group = out.find((g) => g.name === name);
    if (!group) {
      group = { app: c.app, name, items: [] };
      out.push(group);
    }
    group.items.push(c);
  }
  return out;
}

/** L'étiquette d'une conversation dans « Notifications » : sa réponse en chemin, ta réponse, ou reçue. */
export function conversationTag(c: PhoneConversation): [string, string] {
  if (c.her) return c.her.state === "offered" ? ["warn", "réponse proposée"] : offerWords(c.her.state);
  if (c.last.own) return ["ok", "répondu par toi"];
  return ["", "reçue"];
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
  const her = c.her && underWay(c.her.state) ? `<span class="mk">${ico("pen")}réponse proposée</span>` : "";
  return `<button class="li conv" type="button" data-conv="${h(c.key)}" aria-selected="${selected}">
    <span class="conv-av">${avatarOf(title, c.group)}${appIcon(c.app, c.app_name)}</span>
    <span class="li-main"><span class="li-top"><span class="li-title">${h(title)}</span><time>${h(shortWhen(c.last_at, now))}</time></span>
      <span class="li-snip">${h(snippetOf(c))}</span>
      ${her ? `<span class="li-marks">${her}</span>` : ""}</span></button>`;
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

/** Une réponse que Mika a proposée, et ce qu'elle est devenue (rien ne se décide d'ici : le geste est au téléphone). */
export function offerMarkup(o: PhoneOffer, thread: Pick<PhoneThread, "app_name">, title: string, now: number): string {
  const [cls, words] = offerWords(o.state);
  const extra = o.state === "offered" && o.expires ? ` · expire ${remaining(o.expires, now)}` : o.decided_at && !underWay(o.state) ? ` · ${ago(o.decided_at, now)}` : "";
  const icon: IconName = o.state === "offered" || o.state === "prepared" ? "phone" : o.state === "sent" ? "check" : o.state === "failed" ? "alert" : "x";
  const help = o.state === "offered"
    ? `<p class="prop-help">Ton téléphone affiche « Répondre à ${h(title)} (${h(thread.app_name)}) ? » avec Envoyer, Écrire autre chose et Ignorer : ton geste vaut accord.</p>`
    : o.state === "prepared" ? `<p class="prop-help">Elle part à ton téléphone, qui te demandera ton geste.</p>` : "";
  return `<div class="prop"${o.reason ? ` title="${h(o.reason)}"` : ""}>
    <div class="prop-head">${mikaAvatar("xs")}<b>Réponse proposée par Mika</b><span class="muted small">${h(clock(o.at))}</span></div>
    <div class="prop-txt">« ${plainHtml(o.text)} »</div>
    <div class="prop-foot"><span class="tag ${cls}">${ico(icon)}${h(words + extra)}</span></div>${help}
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

export const COMPOSER_NOTE =
  "Répondre d'ici arrive bientôt : pour l'instant, Mika prépare ses réponses quand tu lui en parles dans le chat, et ton téléphone te demande le geste.";

/** La saisie, coupée tant que l'API ne sait pas envoyer depuis le web (ADR 0189) ni préremplir (ADR 0191). */
export function composerMarkup(title: string): string {
  return `<div class="tel-dock">
    <div class="composer tel-cmp" aria-disabled="true">
      <textarea rows="1" disabled placeholder="Ta réponse à ${h(title)}…" aria-label="Ta réponse"></textarea>
      <div class="cmp-bar"><button class="btn sm mika" type="button" disabled>${ico("sparkle", "sm")}<span class="lbl">Préremplir avec Mika</span></button>
        <span class="grow"></span>
        <button class="btn sm primary" type="button" disabled>${ico("send", "sm")}<span class="lbl">Envoyer</span></button></div>
    </div>
    <p class="tel-soon small muted">${ico("info", "xs")}${h(COMPOSER_NOTE)}</p></div>`;
}

export function threadHead(c: PhoneConversation, phone: Phone | null): string {
  const title = conversationTitle(c);
  const parts = [c.group ? `Groupe ${c.app_name}` : c.app_name, `${c.count} message${c.count > 1 ? "s" : ""}`];
  const where = phone ? ` · ${ico("phone", "xs")} ${h(shortPhone(phone.label))}` : "";
  return `<div class="pane-head thread-head"><button class="btn sm icon ghost mobile-back" type="button" data-retour title="Les conversations">${ico("chev-left", "sm")}</button>
    ${avatarOf(title, c.group, "lg")}
    <div class="grow"><h2>${h(title)} ${appIcon(c.app, c.app_name)}</h2><p class="small muted">${h(parts.join(" · "))}${where}</p></div>
    <button class="btn icon ghost sm" type="button" title="Plus" data-more>${ico("more")}</button></div>`;
}

// ── Notifications ────────────────────────────────────────────────────

/** `top` : du HTML posé en tête de la page (la note du sélecteur de téléphones). */
export function notificationsMarkup(items: readonly PhoneConversation[], now: number, top = ""): string {
  const note = `${top}<div class="mika-note info-note">${ico("info")}<div class="mn-body"><div class="mn-title">Ce que ton téléphone lui montre</div>
    <span class="small">Aujourd'hui, l'application ne lui montre que tes messageries : WhatsApp, WhatsApp Business et Messages, si « Lui montrer mes messages » est allumé sur le téléphone. Les autres apps (un colis, un rendez-vous), choisies une à une, arrivent bientôt (ADR 0190). <a href="#parametres/telephones">Tes téléphones</a></span></div></div>`;
  if (!items.length) {
    return `<div class="fill-scroll"><div class="page-pad notifs">${note}
      <div class="empty">${ico("bell")}<b>Rien de ton téléphone</b><p>Aucun message lu sur ton téléphone pour l'instant.</p></div></div></div>`;
  }
  const groups = byApp(items)
    .map((g) => {
      const rows = g.items
        .map((c) => {
          const [cls, words] = conversationTag(c);
          return `<a href="#telephone/messages/${encodeURIComponent(c.key)}" class="notif">${appIcon(c.app, c.app_name, true)}
            <span class="notif-main"><span class="li-top"><b>${h(conversationTitle(c))}</b><span class="muted small">${h(g.name)}${c.group ? " · groupe" : ""} · ${c.count} message${c.count > 1 ? "s" : ""}</span><time>${h(shortWhen(c.last_at, now))}</time></span>
              <span class="notif-txt">${h(snippetOf(c))}</span></span>
            <span class="tag ${cls}">${h(words)}</span></a>`;
        })
        .join("");
      return `<div class="day"><span>${h(g.name)} · ${g.items.length} conversation${g.items.length > 1 ? "s" : ""}</span></div>${rows}`;
    })
    .join("");
  return `<div class="fill-scroll"><div class="page-pad notifs">${note}<div class="notif-list">${groups}</div></div></div>`;
}

// ── La position ──────────────────────────────────────────────────────

/** Un plan dessiné, le même partout (aucune tuile chargée du dehors) : la position au centre, sa précision autour. */
export function mapMarkup(accuracy: number, label: string): string {
  // la position sur la grande rue, comme dans la maquette ; la rivière et les parcs plus loin
  const x = 400;
  const y = 190;
  const r = Math.max(16, Math.min(230, (accuracy || 6) * 2.8));
  const blocks: [number, number, number, number][] = [
    [90, 70, 150, 100], [280, 60, 120, 90], [440, 50, 140, 100], [640, 60, 110, 80], [90, 240, 130, 60],
    [470, 250, 140, 70], [300, 420, 140, 90], [640, 420, 120, 100], [380, 240, 70, 60], [650, 240, 110, 50],
  ];
  return `<svg class="map" viewBox="0 0 800 560" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Plan dessiné autour de ${h(label || "ta position")}">
    <rect class="m-bg" width="800" height="560"/>
    <path class="m-park" d="M40 390 L210 360 L240 480 L60 530 Z"/><path class="m-park" d="M600 20 L760 0 L780 110 L640 130 Z"/>
    <path class="m-water" d="M0 360 C 120 320, 180 390, 260 360 S 380 290, 470 320 S 640 395, 800 345"/>
    ${blocks.map(([bx, by, w, hh]) => `<rect class="m-block" x="${bx}" y="${by}" width="${w}" height="${hh}" rx="6"/>`).join("")}
    <path class="m-road big" d="M0 205 L800 175"/><path class="m-road" d="M255 0 L330 560"/><path class="m-road" d="M600 0 L565 560"/>
    <path class="m-road" d="M0 490 L800 450"/><path class="m-road big" d="M120 560 C 260 430, 420 360, 800 395"/>
    <circle class="m-acc" cx="${x}" cy="${y}" r="${r.toFixed(1)}"/><circle class="m-pulse" cx="${x}" cy="${y}" r="12" style="transform-origin:${x}px ${y}px"/><circle class="m-dot" cx="${x}" cy="${y}" r="8"/>
  </svg>`;
}

/**
 * La vraie carte se montre-t-elle ? Elle couvre la position, et elle ne s'est pas déjà refusée ici pour cette carte du
 * serveur (`failed` : la clé de celle qui n'a pas pu se dessiner — pas de WebGL, MapLibre absent, ses tuiles en échec de
 * suite). Sinon, le plan dessiné et sa note, sans réessayer à chaque dessin ; une autre carte servie se réessaie.
 */
export function liveWanted(info: MapInfo | null, at: { lat: number; lon: number } | null, failed: string | null): boolean {
  return !!at && covers(info, at.lat, at.lon) && failed !== infoKey(info);
}

/** Ce que l'onglet fait de sa carte à ce dessin : le plan, la monter, la garder, ou reposer son style (une autre
 *  carte du serveur, relue pendant qu'elle était ouverte). `liveKey` : la carte servie qu'elle dessine (`null` : aucune). */
export type MapStep = "plan" | "mount" | "keep" | "restyle";

export function mapStep(liveKey: string | null, wanted: boolean, key: string): MapStep {
  if (!wanted) return "plan";
  if (liveKey === null) return "mount";
  return liveKey === key ? "keep" : "restyle";
}

/**
 * La position : sa carte (`live` : la vraie, servie par ce serveur et dessinée par MapLibre dans `[data-map]`), sinon
 * le plan dessiné et sa note ; à côté, ce qu'on en sait.
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
      : mapMarkup(p.accuracy_m, label)}<div class="map-legend">${ico("pin", "sm")}<b>${h(label || "Ta position")}</b>${legend ? `<span class="muted">${h(legend)}</span>` : ""}</div>
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

export function phoneSwitch(phones: readonly Phone[], chosen: number | null, now: number): string {
  const active = activePhones(phones);
  const one = chosen === null ? null : active.find((p) => p.id === chosen) ?? null;
  if (one) {
    const seen = one.last_used ? `vu ${ago(one.last_used, now)}` : "";
    return `<button class="phone-switch" type="button" data-tel-switch title="Changer de téléphone">${ico("phone", "sm")}<b>${h(shortPhone(one.label))}</b>
      <span class="dot ${one.push ? "ok" : "warn"}"></span>${seen ? `<span class="muted">${h(seen)}</span>` : ""}${ico("chev-down", "sm")}</button>`;
  }
  const label = active.length ? "Tous tes téléphones" : "Aucun téléphone";
  return `<button class="phone-switch" type="button" data-tel-switch title="Changer de téléphone">${ico("phone", "sm")}<b>${label}</b>
    ${active.length ? `<span class="muted">${active.length}</span>` : ""}${ico("chev-down", "sm")}</button>`;
}

export const SWITCH_NOTE =
  "Le serveur ne dit pas encore quel téléphone a reçu quel message : tu vois ceux de tous tes téléphones.";
