/**
 * Paramètres › Agendas (ADR 0309, lot 6 ; la maquette validée `maquette/ecrans/agenda-parametres.js`) : ses comptes
 * d'agenda — son agenda du système, ceux qu'elle branche —, ce qu'on lui partage et l'agenda de Mika ; la fiche d'un
 * compte (le compte, ses agendas, leurs partages) ; « Brancher un agenda » avec un parcours par sorte : un agenda de ce
 * serveur, Google (l'adresse de retour collée, ou le retour direct), Outlook.com / Microsoft 365 (un code, sa fin
 * poussée par le direct), CalDAV (essayé, puis choisi), un abonnement iCal. Les données : `protocole-moi.md` § 13.
 *
 * Adresses : `#parametres/agendas`, `#parametres/agendas/<compte>`, `#parametres/agendas/brancher[/<sorte>[/<compte>]]`
 * (le compte : se reconnecter, ou un parcours repris). Un réglage d'agenda (son nom, sa couleur, « Dans l'Agenda »,
 * « Mika te le rappelle ») part tout de suite ; le nom d'un compte, son serveur, par la barre d'enregistrement.
 */
import type { AgendaAccount, AgendaCalendar, Accounts, TriedCalendar } from "../../api/agenda";
import {
  disconnectAccount,
  googleFinish,
  googleStart,
  microsoftStart,
  newCalendar,
  removeAccount,
  saveAccount,
  saveCalendar,
  syncAccount,
  tryCaldav,
} from "../../api/agenda";
import { mikaAvatar } from "../../mika/face";
import { $, $$, h } from "../../shell/dom";
import { closeModal, openMenu, openModal, toast } from "../../shell/float";
import { ico, type IconName } from "../../shell/icons";
import { ago, confirmModal, failureText, newNonce, toastFailure } from "../../shared/kit";
import * as store from "../../shared/store";
import { hiddenHere, setShown } from "../agenda/display";
import { colorOf, mikaReminderWords, MIKA_REMINDERS, PALETTE, rightsSummary, withShownNames } from "../agenda/model";
import { backLink, password, row, section, showRefusal, subTabs, text } from "./form";
import type { Host, Page } from "./page";
import type { FormValue } from "./words";

const TAB = "#parametres/agendas";
const KINDS: Record<string, { long: string; icon: IconName; help: string }> = {
  systeme: { long: "Agenda du système", icon: "server", help: "Sur ce serveur : rien ne sort d'ici. Chaque personne qui a un compte a déjà « Mon agenda »." },
  google: { long: "Google Agenda", icon: "globe", help: "Se connecter à Google, puis coller l'adresse de retour." },
  microsoft: { long: "Outlook.com / Microsoft 365", icon: "key", help: "Un code à entrer chez Microsoft, comme pour une boîte Outlook." },
  caldav: { long: "CalDAV", icon: "server", help: "Une adresse, un identifiant, un mot de passe d'application. Outlook pro par DavMail, iCloud, Nextcloud, Fastmail." },
  ical: { long: "Abonnement iCal", icon: "link", help: "Une adresse .ics, en lecture seule : jours fériés, adresse secrète d'un agenda." },
};
const ORDER = ["systeme", "google", "microsoft", "caldav", "ical"] as const;

/** Où en est un parcours « Brancher » (il survit aux dessins, pas à un autre parcours). */
interface Flow {
  key: string;
  kind: string;
  account: string;
  step: number;
  url: string;
  direct: boolean;
  code: string;
  until: number;
  service: string;
  tried: TriedCalendar[];
  values: { url: string; username: string; password: string; label: string; address: string; name: string; color: string; reminder: string };
  error: string;
  synced: boolean;
}

let flow: Flow | null = null;
/** Le corps de la page, déjà écouté (`after` vient après chaque dessin : une seule fois par corps). */
const listened = new WeakSet<HTMLElement>();

function accounts(): Accounts | null {
  return store.agendaAccounts.value;
}

function accountOf(key: string): AgendaAccount | undefined {
  return accounts()?.accounts.find((a) => a.key === key);
}

function kindLong(a: AgendaAccount): string {
  return KINDS[a.kind]?.long ?? a.kind_label;
}

function kindIcon(kind: string): string {
  return `<span class="acc-ico ag-acc-ico s-${h(kind)}">${ico(KINDS[kind]?.icon ?? "agenda")}</span>`;
}

/** Ce que Mika fait d'un agenda, en une ligne (son tableau, lu à part). */
function summaryOf(c: AgendaCalendar): string {
  const t = store.agendaRights.get(c.key).value;
  return t ? rightsSummary(t, store.me.value?.person ?? "", c.shares ?? [], c.writable) : "";
}

function swatch(color: string, cls = ""): string {
  return `<span class="ag-sw${cls ? ` ${cls}` : ""}" style="--c:var(--ag-${h(color)})"></span>`;
}

/** L'état d'un compte en mots : `[ton, mots]`. */
function stateOf(a: AgendaAccount): [string, string] {
  if (a.system) return ["ok", "à jour"];
  if (!a.enabled) return ["", "décoché"];
  if ((a.kind === "google" || a.kind === "microsoft") && a.signin?.state !== "connectee") return ["warn", "à connecter"];
  if (a.error) return ["warn", "en panne"];
  if (!a.synced_at) return ["", "pas encore synchronisé"];
  return ["ok", a.kind === "ical" ? "relu" : "synchronisé"];
}

function syncWords(a: AgendaAccount, now: number): string {
  if (a.system) return "Toujours à jour : il est sur ce serveur.";
  if (!a.synced_at) return a.tried_at ? `Dernier essai ${ago(a.tried_at, now)}` : "Pas encore synchronisé.";
  return `${a.kind === "ical" ? "Relu" : "Synchronisé"} ${ago(a.synced_at, now)}.`;
}

function needsSignin(a: AgendaAccount): boolean {
  return (a.kind === "google" || a.kind === "microsoft") && a.signin?.state !== "connectee";
}

// ── la liste ─────────────────────────────────────────────────────────

function accountCard(a: AgendaAccount, now: number): string {
  const [tone, words] = stateOf(a);
  const calChips = a.calendars.map((c) => `<span class="ag-acc-cal${c.hidden ? " off" : ""}" title="${c.hidden ? "Pas dans l'Agenda : Mika ne s'en sert pas" : "Dans l'Agenda"}">${swatch(colorOf(c))}${h(c.name)}${c.hidden ? " <i>masqué</i>" : ""}${c.reminder !== "non" ? `<span class="ag-acc-r" title="Mika te le rappelle">${ico("bell", "xs")}${h(mikaReminderWords(c.reminder))}</span>` : ""}</span>`).join("");
  const err = a.error && !a.system ? `<p class="small warn-txt ag-acc-err">${ico("alert", "xs")}${h(a.error)}</p>` : `<p class="small muted">${h(syncWords(a, now))}</p>`;
  const first = a.calendars.find((c) => !c.hidden && c.can.rights);
  return `<div class="acc-card ag-acc">${kindIcon(a.kind)}
    <div class="grow"><div class="row wrap"><b>${h(a.label)}</b>${a.address ? `<span class="muted ellipsis ag-acc-adr">${h(a.address)}</span>` : ""}</div>
      <div class="row wrap acc-tags"><span class="tag ${tone}">${h(words)}</span><span class="tag">${h(kindLong(a))}</span><span class="tag accent">à toi</span></div>
      ${calChips ? `<div class="ag-acc-cals">${calChips}</div>` : ""}
      ${err}
      ${first ? `<p class="small ag-acc-mika">${ico("sparkle", "xs")}<span>${h(summaryOf(first) || `Ce que Mika fait de « ${first.name} » se règle dans son tableau`)}${a.calendars.filter((c) => !c.hidden).length > 1 ? ` (« ${h(first.name)} »)` : ""} · <a href="#outils/droits/${encodeURIComponent(`ag:${first.key}`)}">Ses droits</a></span></p>` : ""}</div>
    ${needsSignin(a) ? `<a class="btn sm primary" href="${TAB}/brancher/${a.kind}/${encodeURIComponent(a.key)}">${ico("key", "sm")}${a.signin?.state === "a_faire" && !a.synced_at ? "Se connecter" : "Se reconnecter"}</a>` : ""}
    <a class="btn sm" href="${TAB}/${encodeURIComponent(a.key)}">Régler</a>
    <button class="btn sm icon ghost" type="button" data-act="ag-cptmenu" data-account="${h(a.key)}" title="Plus" aria-label="Plus pour « ${h(a.label)} »">${ico("more", "sm")}</button></div>`;
}

function listView(now: number): string {
  const acc = accounts();
  const cals = store.agendaCalendars.value?.calendars ?? [];
  const shared = withShownNames(cals.filter((c) => c.group === "shared"));
  const zone = store.agendaCalendars.value?.zone ?? "";
  const off = hiddenHere();
  const sharedCards = shared.map((c) => `<div class="acc-card">${swatch(colorOf(c), "lg")}<div class="grow"><div class="row"><b>${h(c.name)}</b><span class="tag">${h(c.level === "lire" ? "lire" : c.level === "preparer" ? "lire et préparer" : "s'en servir")}</span></div>
      <p class="small muted">${h(c.owner_name || "Son propriétaire")} te l'a ouvert. Tu le vois dans l'Agenda${c.level === "servir" ? " et tu t'en sers" : " ; tu n'y changes rien"}.</p></div>
    <a class="btn sm" href="#agenda/semaine">Ouvrir</a><label class="row small ag-vis"><span class="switch"><input type="checkbox" data-agvis="${h(c.key)}"${off.has(c.key) ? "" : " checked"}><i></i></span>Dans l'Agenda</label></div>`).join("");
  return `<div class="set-page">
    <p class="lede">Tes agendas, d'où qu'ils viennent : celui de ce serveur, Google, Outlook, un serveur CalDAV, un abonnement. Tu les vois tous dans l'Agenda ; Mika s'en sert selon ce que tu règles ici et dans Outils › Droits. Un compte n'est qu'à toi, sauf si tu partages ses agendas.</p>
    <h2 class="section-title">Tes comptes <span class="cnt">${acc?.accounts.length ?? 0}</span></h2>
    <div class="acc-cards">${(acc?.accounts ?? []).map((a) => accountCard(a, now)).join("")}</div>
    ${shared.length ? `<h2 class="section-title shared-title">Partagé avec toi <span class="cnt">${shared.length}</span></h2><div class="acc-cards">${sharedCards}</div>` : ""}
    <h2 class="section-title shared-title">L'agenda de Mika</h2>
    <div class="acc-cards"><div class="acc-card ag-mika-card">${mikaAvatar("lg")}<div class="grow"><b>L'agenda de Mika</b>
      <p class="small text-2">Ce qu'elle t'a promis pour une date, et ce qu'elle retient de ta vie à venir, montrés comme un agenda, en lecture seule. Rien n'y est recopié : c'est sa mémoire. On le corrige en le lui disant.</p>
      <p class="small muted">Elle ne te montre que ce qui te concerne : ce que d'autres lui confient n'y paraît jamais.</p></div>
      <label class="row small ag-vis"><span class="switch"><input type="checkbox" data-agvis="mika"${off.has("mika") ? "" : " checked"}><i></i></span>Dans l'Agenda</label></div></div>
    <section class="set-sec"><div class="set-sec-head"><h2>Pour tous tes agendas</h2></div><div class="set-grid two">
      ${row("Fuseau horaire", "Celui de ce serveur : l'Agenda s'y lit, et ce que tu écris s'y dit, sauf un autre choisi pour un événement.", `<span class="tag">${h(zone || "—")}</span>`)}
      ${row("Ce qui se synchronise", "Les 90 derniers jours et l'année qui vient.", '<span class="tag">90 jours derrière · 1 an devant</span>')}
      ${acc?.max !== null && acc?.max !== undefined ? row("Combien de comptes", "Ceux que tu branches, en plus de ton agenda du système.", `<span class="tag">${acc.max} au plus</span>`) : ""}
    </div></section>
  </div>`;
}

// ── la fiche d'un compte ─────────────────────────────────────────────

function connection(a: AgendaAccount): string {
  if (a.system) return row("Connexion", "Rien à brancher : il est sur ce serveur.", '<span class="tag ok">sur ce serveur</span><span class="small muted">rien ne sort d\'ici</span>');
  if (a.kind === "google" || a.kind === "microsoft") {
    const signed = a.signin?.state === "connectee";
    const who = a.kind === "google" ? "Compte Google" : "Compte Microsoft";
    const help = a.kind === "google" ? "Par l'application Google de ce serveur (OAuth 2), réglée par l'opérateur." : "Par un code à entrer chez Microsoft, avec l'application Microsoft de ce serveur.";
    return row(who, help, `<span class="tag ${signed ? "ok" : "warn"}">${signed ? "connecté" : a.signin?.state === "en_attente" ? "en attente" : "à connecter"}</span>
      <a class="btn xs${signed ? "" : " primary"}" href="${TAB}/brancher/${a.kind}/${encodeURIComponent(a.key)}">${signed ? "Se reconnecter" : `${ico("key", "xs")}Se connecter`}</a>
      ${signed ? `<button class="btn xs ghost danger" type="button" data-act="ag-deco" data-account="${h(a.key)}">Déconnecter</button>` : ""}`);
  }
  if (a.kind === "ical") {
    return row("Adresse .ics", "Lue telle quelle, en lecture seule. Une adresse secrète donne à lire tout l'agenda : elle ne se relit pas ici.", text("url", "", `class="mono" placeholder="${a.url_set ? "gardée — laisse vide pour ne pas la changer" : "https://…/basic.ics"}"`));
  }
  return row("Adresse du serveur", "", text("url", a.url, 'class="mono"'))
    + row("Identifiant", "", text("username", a.username))
    + row("Mot de passe d'application", "Scellé : il ne se relit plus. Le serveur ou l'identifiant changent : redonne-le.", `${password("password", a.secrets.password)}<button class="btn xs" type="button" data-act="ag-essai" data-account="${h(a.key)}">${ico("refresh", "xs")}Essayer</button>`);
}

function reminderSelect(c: AgendaCalendar): string {
  const def = c.reminder_set ? "" : ` (${mikaReminderWords(c.reminder)})`;
  return `<select class="sm-select ag-mika-sel" data-agrapp="${h(c.key)}" aria-label="Mika te le rappelle"><option value=""${c.reminder_set ? "" : " selected"}>Par défaut${h(def)}</option>${MIKA_REMINDERS.map(([k, l]) => `<option value="${k}"${c.reminder_set === k ? " selected" : ""}>${h(l)}</option>`).join("")}</select>`;
}

function calendarsTable(a: AgendaAccount): string {
  const rows = a.calendars.map((c) => `<tr><td><button class="ag-swbtn" type="button" data-act="ag-couleur" data-calendar="${h(c.key)}" title="Changer la couleur" aria-label="La couleur de « ${h(c.name)} »">${swatch(colorOf(c))}${ico("chev-down", "xs")}</button></td>
      <td><input value="${h(c.name)}" class="ag-nom-in" data-agnom="${h(c.key)}" aria-label="Le nom de l'agenda" maxlength="200">${c.primary ? ' <span class="tag">par défaut</span>' : ""}${c.provider_name ? `<div class="tiny muted">chez son fournisseur : ${h(c.provider_name)}</div>` : ""}</td>
      <td><span class="switch"><input type="checkbox" data-agmasque="${h(c.key)}"${c.hidden ? "" : " checked"} aria-label="Dans l'Agenda"><i></i></span></td>
      <td>${reminderSelect(c)}</td>
      <td><span class="tag">${c.writable ? "lire et écrire" : "lire seulement"}</span></td>
      <td class="small">${c.can.rights ? `${h(summaryOf(c))}${summaryOf(c) ? " · " : ""}<a href="#outils/droits/${encodeURIComponent(`ag:${c.key}`)}">Ses droits</a>` : ""}${c.hidden ? ' <span class="muted">· Pas dans l\'Agenda : Mika ne s\'en sert pas.</span>' : ""}</td></tr>`).join("");
  const create = a.system
    ? `<a class="btn xs" href="${TAB}/brancher/systeme">${ico("plus", "xs")}Créer un agenda</a>`
    : `${a.kind === "ical" ? "" : `<button class="btn xs" type="button" data-act="ag-sync" data-account="${h(a.key)}">${ico("refresh", "xs")}Chercher d'autres agendas sur ce compte</button>`}${a.abilities.calendars ? `<button class="btn xs" type="button" data-act="ag-nouvel" data-account="${h(a.key)}">${ico("plus", "xs")}Créer un agenda</button>` : ""}`;
  return `<div class="set-row full" data-ignore><div class="tbl-wrap"><table class="tbl ag-tbl"><thead><tr><th>Couleur</th><th>Agenda</th><th>Dans l'Agenda</th><th>Mika te le rappelle</th><th>On peut</th><th>Ce que Mika en fait</th></tr></thead><tbody>
    ${rows || '<tr><td colspan="6" class="muted small">Pas encore d\'agenda : la synchronisation les apporte.</td></tr>'}</tbody></table></div>
    <div class="row tbl-help">${create}<span class="small muted">Un agenda masqué reste branché : il ne s'affiche plus, et Mika ne s'en sert plus. Renommer un agenda branché ne change son nom qu'ici.</span></div></div>`;
}

function sharesOf(a: AgendaAccount): string {
  const provider = a.kind === "google" ? "Google" : a.kind === "microsoft" ? "Microsoft" : a.kind === "caldav" ? "le serveur CalDAV" : "";
  const list = a.calendars.filter((c) => !c.hidden).map((c) => `<div class="ag-part">${swatch(colorOf(c))}<b>${h(c.name)}</b>
      <span class="grow row wrap">${(c.shares ?? []).length ? (c.shares ?? []).map((s) => `<span class="chip">${h(s.name)} · ${h(s.level === "lire" ? "lire" : s.level === "preparer" ? "lire et préparer" : "s'en servir")}</span>`).join("") : '<span class="small muted">Personne</span>'}</span>
      ${c.can.share ? `<a class="btn xs" href="#agenda/partager/${encodeURIComponent(c.key)}">${ico("user-plus", "xs")}Partager…</a>` : ""}</div>`).join("");
  return `<div class="set-row full">${provider ? `<div class="info-line small">${ico("info", "sm")}<span>Un agenda se partage ici, dans Mika, avec une personne qui a un compte : elle le voit dans son Agenda de Mika. Ça ne change rien chez ${h(provider)}, et un partage fait chez ${h(provider)} ne se voit pas ici.</span></div>` : ""}
    <div class="ag-part-list">${list || '<div class="ag-part"><span class="small muted">Aucun agenda à partager.</span></div>'}</div></div>`;
}

function accountView(a: AgendaAccount, host: Host, now: number): string {
  const active = host.sub(`agenda:${a.key}`, "compte");
  const [tone, words] = stateOf(a);
  const tabs = subTabs(`agenda:${a.key}`, [["compte", "Le compte"], ["agendas", `Ses agendas (${a.calendars.length})`], ["partage", "Partage"]], active);
  const err = a.error && !a.system
    ? `<div class="ag-err">${ico("alert", "sm")}<span><b>${h(a.error)}</b><small>${h(syncWords(a, now))}</small></span>${needsSignin(a) ? `<a class="btn sm primary" href="${TAB}/brancher/${a.kind}/${encodeURIComponent(a.key)}">${ico("key", "sm")}Se reconnecter</a>` : ""}</div>`
    : `<p class="small muted ag-sync">${ico("refresh", "xs")}${h(syncWords(a, now))}</p>`;
  const compte = row("Nom", "Comme tu l'appelles, et comme elle l'appelle.", text("label", a.label, a.system ? "" : 'maxlength="200"'))
    + row("À qui", "Un compte est à toi : ses outils ne voient que les agendas de qui est en face.", '<span class="tag accent">à toi</span>')
    + connection(a)
    + row("Synchronisation", a.kind === "ical" ? "Un abonnement se relit à son rythme." : a.system ? "" : "Elle relit ce qui a changé de lui-même ; une modification part tout de suite.", `<span class="small text-2">${h(syncWords(a, now))}</span>${a.system ? "" : `<button class="btn xs" type="button" data-act="ag-sync" data-account="${h(a.key)}">${ico("refresh", "xs")}Synchroniser</button>`}`)
    + (a.system ? "" : row("Retirer ce compte", "Ses agendas disparaissent de ton Agenda et de ce que Mika voit ; rien n'est effacé chez le fournisseur.", `<button class="btn sm danger" type="button" data-act="ag-retirer" data-account="${h(a.key)}">${ico("trash", "sm")}Retirer</button>`));
  return `<form class="set-page" data-form data-agfiche="${h(a.key)}">
    ${backLink(TAB, "Agendas")}
    <div class="fiche-head">${kindIcon(a.kind)}<div class="grow"><h2>${h(a.label)}</h2><p class="muted">${h([a.address, kindLong(a)].filter(Boolean).join(" · "))}</p></div>
      <span class="tag ${tone}">${h(words)}</span><span class="tag accent">à toi</span></div>
    ${err}
    ${tabs}
    ${section("Le compte", compte, { sub: "compte", hidden: active !== "compte" })}
    ${section("Ses agendas", calendarsTable(a), { sub: "agendas", hidden: active !== "agendas", single: true })}
    ${section("Partage", sharesOf(a), { sub: "partage", hidden: active !== "partage", single: true })}
  </form>`;
}

// ── brancher un agenda ───────────────────────────────────────────────

function flowFor(kind: string, account: string): Flow {
  const key = `${kind}/${account}`;
  if (flow?.key === key) return flow;
  const a = account ? accountOf(account) : undefined;
  const signedIn = a?.signin?.state === "connectee";
  flow = {
    key, kind, account, step: account && signedIn ? 3 : 1, url: "", direct: false, code: "", until: 0, service: "", tried: [],
    values: { url: "", username: "", password: "", label: a?.label ?? "", address: a?.address ?? "", name: "", color: "sarcelle", reminder: "30" },
    error: "", synced: false,
  };
  return flow;
}

function steps(list: readonly (readonly [string, string])[], at: number): string {
  return `<ol class="ag-steps">${list.map(([title, body], i) => {
    const n = i + 1;
    const st = at > n ? "fait" : at === n ? "actif" : "avenir";
    return `<li class="ag-step ${st}"><span class="ag-step-n">${st === "fait" ? ico("check", "sm") : n}</span><div class="ag-step-body"><h3>${h(title)}${st === "fait" ? `<button class="linkish" type="button" data-act="ag-etape" data-step="${n}">Modifier</button>` : ""}</h3>${st === "avenir" ? `<div class="ag-step-avenir">${body}</div>` : body}</div></li>`;
  }).join("")}</ol>`;
}

function palette(selected: string): string {
  return `<div class="ag-swatches inline">${PALETTE.map((k) => `<button type="button" class="ag-swatch${k === selected ? " on" : ""}" style="--c:var(--ag-${k})" data-act="ag-pal" data-color="${k}" title="${k}" aria-label="${k}"></button>`).join("")}</div>`;
}

/** Les agendas d'un compte qu'on vient de brancher : « Dans l'Agenda », un par un (la synchronisation les apporte). */
function chosen(account: string): string {
  const a = accountOf(account);
  const cals = a?.calendars ?? [];
  if (!cals.length) return `<p class="small text-2"><span class="ag-attente"><i class="spin"></i>Synchronisation…</span> Ses agendas arrivent ici dès qu'ils sont lus.</p>`;
  return `<p class="small text-2">${h(a?.address || a?.label || "")} · ${cals.length} agenda${cals.length > 1 ? "s" : ""} trouvé${cals.length > 1 ? "s" : ""}. Ceux que tu décoches restent branchés, sans s'afficher : Mika ne s'en sert pas.</p>
    <div class="ag-found">${cals.map((c) => `<label class="ag-found-row"><input type="checkbox" data-agmasque="${h(c.key)}"${c.hidden ? "" : " checked"}>${swatch(colorOf(c))}<b>${h(c.name)}</b><span class="small muted">${c.writable ? "" : "lecture seule"}</span></label>`).join("")}</div>
    <div class="row wrap"><a class="btn primary" href="${TAB}/${encodeURIComponent(account)}">${ico("check", "sm")}Terminé</a><span class="small muted">Mika s'en sert selon son tableau, que tu règles ensuite dans Outils › Droits.</span></div>`;
}

function parcours(f: Flow, acc: Accounts): string {
  const v = f.values;
  const err = f.error ? `<p class="small ag-acc-err warn-txt">${ico("alert", "xs")}${h(f.error)}</p>` : "";
  if (f.kind === "systeme") {
    return steps([["Un agenda de ce serveur", `<p class="small text-2">Chaque personne qui a un compte a déjà « Mon agenda ». Crée-en d'autres pour ranger ta vie (« Sport », « Maison »…). Il vit sur ce serveur : rien ne sort d'ici, et tu le partages avec qui a un compte.</p>
      <div class="set-grid">${row("Nom", "", `<input data-agf="name" placeholder="Sport" value="${h(v.name)}" maxlength="200">`)}${row("Couleur", "", palette(v.color))}
        ${row("Mika te le rappelle", "Le réglage de départ de ses événements.", `<select data-agf="reminder">${MIKA_REMINDERS.map(([k, l]) => `<option value="${k}"${k === v.reminder ? " selected" : ""}>${h(l)}</option>`).join("")}</select>`)}</div>${err}
      <div class="row wrap"><button class="btn primary" type="button" data-act="ag-systeme">${ico("check", "sm")}Créer l'agenda</button><span class="small muted">Il sera à toi. Mika s'en sert selon son tableau, que tu règles ensuite dans Outils › Droits.</span></div>`]], 1);
  }
  if (f.kind === "google") {
    const one = !acc.google.app
      ? `<div class="ag-err warn">${ico("alert", "sm")}<span><b>L'application Google de ce serveur n'est pas réglée : demande-le à qui s'occupe d'elle.</b><small>Sans elle, Google refuse de te connecter. Elle se règle dans la console, Échanges › Agendas, la roue (un client « Application de bureau » d'un projet Google Cloud).</small></span></div>
        <p class="small text-2">En attendant, tu peux t'abonner à l'adresse secrète iCal de ton agenda Google : en lecture seule. <a href="${TAB}/brancher/ical">Un abonnement iCal</a></p>`
      : `<p class="small text-2">Une page Google s'ouvre dans un nouvel onglet : choisis ton compte, puis accepte que Mika lise et modifie tes agendas.</p>
        <div class="row wrap"><button class="btn primary" type="button" data-act="ag-google">${ico("globe", "sm")}Se connecter à Google</button><span class="small muted">Avec l'application Google de ce serveur, réglée par l'opérateur.</span></div>${f.step === 1 ? err : ""}`;
    const two = f.direct
      ? `<p class="small text-2">Google revient tout seul vers ce serveur : finis sur sa page, puis reviens ici. <span class="ag-attente"><i class="spin"></i>En attente…</span></p>${f.url ? `<p class="small"><a href="${h(f.url)}" target="_blank" rel="noopener noreferrer">Rouvrir la page de Google</a></p>` : ""}`
      : `<p class="small text-2">Après ton accord, Google te renvoie vers une adresse qui commence par <code>http://127.0.0.1</code>. La page ne s'ouvre pas, c'est normal : son adresse porte le code qui prouve ton accord. Copie-la dans la barre d'adresse, et colle-la ici.</p>
        <div class="ag-faux"><div class="ag-faux-barre">${ico("lock", "xs")}<span class="mono">http://127.0.0.1/?state=…&amp;<b>code=4/0Aan…</b>&amp;scope=…calendar</span></div><div class="ag-faux-page">${ico("alert")}<b>Ce site est inaccessible</b><span>127.0.0.1 n'autorise pas la connexion.</span></div></div>
        <div class="row"><input class="grow mono" data-agf="colle" placeholder="http://127.0.0.1/?state=…&amp;code=…" aria-label="L'adresse de la page qui n'a pas pu s'ouvrir"><button class="btn primary" type="button" data-act="ag-coller">Valider</button></div>
        ${f.url ? `<p class="small muted">La page de Google ne s'est pas ouverte ? <a href="${h(f.url)}" target="_blank" rel="noopener noreferrer">L'ouvrir</a>. Si ce serveur a une adresse en https, Google y revient tout seul et cette étape disparaît.</p>` : ""}${f.step === 2 ? err : ""}`;
    return steps([["Se connecter à Google", one], [f.direct ? "Finir chez Google" : "Colle ici l'adresse de la page qui n'a pas pu s'ouvrir", two], ["Choisis tes agendas", f.account ? chosen(f.account) : ""]], f.step);
  }
  if (f.kind === "microsoft") {
    const one = !acc.microsoft_app
      ? `<div class="ag-err warn">${ico("alert", "sm")}<span><b>L'application Microsoft de ce serveur n'est pas réglée : demande-le à qui s'occupe d'elle.</b><small>Un Outlook pro passe aussi par <a href="${TAB}/brancher/caldav">CalDAV avec DavMail</a>.</small></span></div>`
      : `<p class="small text-2">Outlook.com, Hotmail, Live, ou un compte Microsoft 365. Un compte pro dépend de l'accord de son organisation : si elle le refuse, passe par <a href="${TAB}/brancher/caldav">CalDAV avec DavMail</a>.</p>
        <div class="row wrap"><input data-agf="address" placeholder="prenom.nom@outlook.fr" value="${h(v.address)}" class="grow" aria-label="Ton adresse Microsoft"${f.account ? " disabled" : ""}><button class="btn primary" type="button" data-act="ag-code">${ico("key", "sm")}Obtenir un code</button></div>${f.step === 1 ? err : ""}`;
    const two = f.code
      ? `<div class="device ag-device">${ico("key")}<div><b>Ouvre <a href="${h(f.url || "https://microsoft.com/devicelogin")}" target="_blank" rel="noopener noreferrer">${h((f.url || "https://microsoft.com/devicelogin").replace(/^https?:\/\//, ""))}</a> et entre ce code</b><div class="code">${h(f.code)}</div>
          <span class="small muted">${f.until ? `Valable jusqu'à ${h(new Date(f.until).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }))}. ` : ""}Mika se connecte dès que c'est fait : rien à coller ici.</span></div><span class="ag-attente"><i class="spin"></i>En attente…</span></div>${f.step === 2 ? err : ""}`
      : "<p class=\"small text-2\">Le code s'affiche ici.</p>";
    return steps([["Ton compte Microsoft", one], ["Entre le code chez Microsoft", two], ["Choisis tes agendas", f.account ? chosen(f.account) : ""]], f.step);
  }
  if (f.kind === "caldav") {
    const services = acc.services;
    const svc = services.find((s) => s.key === f.service) ?? services[0];
    const seg = services.length ? `<div class="row wrap ag-services"><span class="small text-2">Une aide pour :</span><div class="seg" data-seg="agservice">${services.map((s) => `<button type="button" data-v="${h(s.key)}" aria-pressed="${s.key === svc?.key}">${h(s.name)}</button>`).join("")}</div></div>
      ${svc ? `<div class="info-line small">${ico("info", "sm")}<span><b>${h(svc.name)}</b> · ${h(svc.help)}</span></div>` : ""}` : "";
    const one = `${seg}<div class="set-grid">${row("Adresse du serveur", "", `<input class="mono" data-agf="url" placeholder="${h(svc?.url ?? "https://…")}" value="${h(v.url)}">`)}
        ${row("Identifiant", "", `<input data-agf="username" placeholder="ton identifiant" value="${h(v.username)}" autocomplete="off">`)}
        ${row("Mot de passe d'application", "Pas celui de ton compte : un mot de passe fait pour une application.", `<input type="password" data-agf="password" value="${h(v.password)}" autocomplete="new-password">`)}</div>${f.step === 1 ? err : ""}
      <div class="row"><button class="btn primary" type="button" data-act="ag-essayer">${ico("refresh", "sm")}Essayer</button></div>`;
    const two = f.step < 2 ? '<p class="small text-2">Les agendas que le serveur propose s\'affichent ici, une fois la connexion essayée.</p>' : `<p class="ag-ok">${ico("check", "sm")}Connexion réussie : ${f.tried.length} agenda${f.tried.length > 1 ? "s" : ""} trouvé${f.tried.length > 1 ? "s" : ""}.</p>
      <div class="ag-found">${f.tried.map((c) => `<div class="ag-found-row">${swatch(colorOf({ key: c.local, color: "", provider_color: c.color, kind: "caldav" }))}<b>${h(c.name || c.local)}</b><span class="small muted">${c.writable ? "" : "lecture seule"}${c.primary ? " · principal" : ""}</span></div>`).join("")}</div>
      <div class="set-grid">${row("Nom", "Comme tu l'appelles, et comme elle l'appelle.", `<input data-agf="label" value="${h(v.label || svc?.name || "CalDAV")}" maxlength="200">`)}</div>${f.step === 2 ? err : ""}
      <div class="row wrap"><button class="btn primary" type="button" data-act="ag-brancher-caldav">${ico("check", "sm")}Brancher</button><span class="small muted">Il sera à toi. Tu choisis ensuite ceux de ses agendas que tu vois, dans sa fiche.</span></div>`;
    return steps([["Le serveur", one], ["Les agendas trouvés", two]], f.step);
  }
  return steps([["L'adresse de l'abonnement", `<p class="small text-2">Une adresse .ics : les jours fériés, le calendrier d'un club, ou l'adresse secrète d'un agenda Google ou Outlook. <b>Lecture seule</b> : ni toi ni Mika n'y écrivez.</p>
    <div class="set-grid">${row("Adresse .ics", "Une adresse secrète donne à lire tout l'agenda : garde-la pour toi.", `<input class="mono" data-agf="url" placeholder="https://…/basic.ics" value="${h(v.url)}">`)}
      ${row("Nom", "", `<input data-agf="label" value="${h(v.label)}" placeholder="Jours fériés" maxlength="200">`)}</div>${err}
    <div class="row wrap"><button class="btn primary" type="button" data-act="ag-ical">${ico("check", "sm")}S'abonner</button><span class="small muted">Il se relit aussitôt, puis à son rythme. Sa couleur se choisit ensuite, dans sa fiche.</span></div>`]], 1);
}

function brancherView(kind: string | null, account: string): string {
  const acc = accounts();
  if (!acc) return "";
  const f = kind ? flowFor(kind, account) : null;
  const providers = ORDER.map((k) => `<a class="provider${k === kind ? " on" : ""}" href="${TAB}/brancher/${k}">${ico(KINDS[k].icon, "lg")}<b>${h(KINDS[k].long)}</b><span>${h(KINDS[k].help)}</span></a>`).join("");
  return `<div class="set-page ag-brancher">
    ${backLink(TAB, "Agendas")}
    <div class="fiche-head"><div><h2>${account ? "Reconnecter un agenda" : "Brancher un agenda"}</h2><p class="muted">Il sera à toi. Tu choisis ceux de ses agendas que tu vois ; ce que Mika en fait se règle ensuite dans Outils › Droits.</p></div></div>
    ${account ? "" : `<div class="providers ag-providers">${providers}</div>`}
    ${f ? `<div class="ag-parcours">${parcours(f, acc)}</div>` : '<p class="small muted">Choisis d\'où vient ton agenda.</p>'}
  </div>`;
}

// ── la page ──────────────────────────────────────────────────────────

function parse(item: string | null): { kind: "list" | "fiche" | "brancher"; account: string; sort: string | null } {
  const parts = (item ?? "").split("/").filter(Boolean);
  if (!parts.length) return { kind: "list", account: "", sort: null };
  if (parts[0] === "brancher") {
    const sort = ORDER.includes(parts[1] as (typeof ORDER)[number]) ? parts[1] : null;
    return { kind: "brancher", account: parts[2] ?? "", sort };
  }
  return { kind: "fiche", account: parts[0], sort: null };
}

/** Le direct a relu les comptes : un parcours qui attendait une connexion avance. */
function advance(host: Host): void {
  const f = flow;
  if (!f || !f.account) return;
  const a = accountOf(f.account);
  if (!a) return;
  if ((f.kind === "google" || f.kind === "microsoft") && f.step === 2 && a.signin?.state === "connectee") {
    f.step = 3;
    f.error = "";
    if (!f.synced) {
      f.synced = true;
      // la connexion faite : son adresse retrouvée, il se synchronise (`…/account/sync`)
      void syncAccount(f.account).catch(() => undefined).then(() => host.reload(store.agendaAccounts, store.agendaCalendars));
    }
  }
  if (f.kind === "microsoft" && f.step === 2 && a.signin?.error) f.error = a.signin.error;
}

async function act(name: string, el: HTMLElement, item: string | null, host: Host): Promise<void> {
  const account = el.dataset.account ?? "";
  const route = parse(item);
  const f = flow;
  const reload = () => host.reload(store.agendaAccounts, store.agendaCalendars);
  const value = (n: string) => ($<HTMLInputElement>(`[data-agf="${n}"]`, el.closest(".set-page") ?? document)?.value ?? "").trim();
  try {
    if (name === "ag-cptmenu") {
      const a = accountOf(account);
      if (!a) return;
      openMenu(el, [
        ...(a.system ? [] : [{ label: "Synchroniser maintenant", icon: "refresh" as IconName, action: () => void act("ag-sync", el, item, host) }]),
        { label: "Régler", icon: "settings", action: () => host.go(`${TAB}/${encodeURIComponent(a.key)}`) },
        ...(a.calendars.some((c) => c.can.rights) ? [{ label: "Ses droits", icon: "shield" as IconName, action: () => host.go(`#outils/droits/${encodeURIComponent(`ag:${a.calendars.find((c) => c.can.rights)!.key}`)}`) }] : []),
        ...(a.system ? [] : ["sep" as const, { label: "Retirer ce compte", icon: "trash" as IconName, danger: true, action: () => void act("ag-retirer", el, item, host) }]),
      ]);
      return;
    }
    if (name === "ag-sync") {
      const done = await syncAccount(account);
      toast(done.message || "Synchronisation demandée.", { ico: "refresh" });
      void reload();
      return;
    }
    if (name === "ag-retirer") {
      const a = accountOf(account);
      if (!a) return;
      const sure = await confirmModal({ title: "Retirer ce compte", text: `Retirer « ${a.label} »${a.address ? ` (${a.address})` : ""} ? Ses agendas disparaissent de ton Agenda et de ce que Mika voit. Rien n'est effacé chez le fournisseur ; ses partages dans Mika s'arrêtent.`, ok: "Retirer", danger: true });
      if (!sure) return;
      const done = await removeAccount(account);
      toast(done.message, { ico: "trash" });
      host.go(TAB);
      void reload();
      return;
    }
    if (name === "ag-deco") {
      const sure = await confirmModal({ title: "Déconnecter ce compte", text: "Sa connexion est retirée (chez Google aussi) et oubliée. Le compte reste, à reconnecter ; ses agendas ne se relisent plus en attendant.", ok: "Déconnecter", danger: true });
      if (!sure) return;
      const done = await disconnectAccount(account);
      toast(done.message, { ico: "logout" });
      void reload();
      return;
    }
    if (name === "ag-essai") {
      const form = el.closest<HTMLElement>("[data-form]");
      const url = (form && $<HTMLInputElement>('[name="url"]', form)?.value.trim()) || "";
      const user = (form && $<HTMLInputElement>('[name="username"]', form)?.value.trim()) || "";
      const pass = (form && $<HTMLInputElement>('[name="password"]', form)?.value) || "";
      const got = await tryCaldav(url, user, pass, account);
      toast(got.ok ? `Connexion réussie : ${got.message}` : got.message, { ico: got.ok ? "check" : "alert", duration: 5000 });
      return;
    }
    if (name === "ag-couleur") {
      const key = el.dataset.calendar ?? "";
      const menu = openMenu(el, [{ header: "Couleur" }, { html: `<div class="ag-swatches">${PALETTE.map((k) => `<button type="button" class="ag-swatch" style="--c:var(--ag-${k})" data-agcoul="${k}" title="${k}" aria-label="${k}"></button>`).join("")}</div>` }], { align: "left" });
      menu.addEventListener("click", (e) => {
        const b = (e.target as Element).closest<HTMLElement>("[data-agcoul]");
        if (!b) return;
        menu.remove();
        void saveCalendar(key, { color: b.dataset.agcoul ?? "" }).then(() => reload(), toastFailure);
      });
      return;
    }
    if (name === "ag-nouvel") {
      const el2 = openModal({
        title: "Créer un agenda",
        size: "narrow",
        body: `<label class="field"><span>Son nom</span><input data-agnouveau maxlength="200" placeholder="Sport"></label><p class="small muted">Il se crée chez le fournisseur de ce compte.</p>`,
        foot: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>Créer</button>',
      });
      el2.querySelector("[data-ok]")?.addEventListener("click", () => {
        const n = el2.querySelector<HTMLInputElement>("[data-agnouveau]")?.value.trim() ?? "";
        if (!n) return;
        closeModal();
        void newCalendar(n, account, newNonce()).then((d) => {
          toast(d.message, { ico: "check" });
          void reload();
        }, toastFailure);
      });
      return;
    }
    if (name === "ag-etape" && f) {
      f.step = Number(el.dataset.step) || 1;
      f.error = "";
      host.repaint();
      return;
    }
    if (name === "ag-pal" && f) {
      f.values.color = el.dataset.color ?? f.values.color;
      for (const x of $$<HTMLElement>(".ag-swatches.inline .ag-swatch", el.closest(".set-page") ?? document)) x.classList.toggle("on", x === el);
      return;
    }
    if (!f) return;
    f.error = "";
    if (name === "ag-systeme") {
      f.values.name = value("name");
      f.values.reminder = ($<HTMLSelectElement>('[data-agf="reminder"]')?.value ?? "30");
      if (!f.values.name) {
        f.error = "Donne-lui un nom.";
        host.repaint();
        return;
      }
      const made = await newCalendar(f.values.name, "", newNonce());
      const key = made.made?.calendar;
      if (key) await saveCalendar(key, { color: f.values.color, reminder: f.values.reminder as "30" });
      toast(made.message, { ico: "check" });
      flow = null;
      host.go(TAB);
      void reload();
      return;
    }
    if (name === "ag-google") {
      if (!f.account) {
        const saved = await saveAccount("google", "", { label: "Google" }, newNonce());
        f.account = saved.account;
        f.key = `google/${f.account}`;
      }
      const got = await googleStart(f.account);
      f.url = got.url;
      f.direct = got.direct;
      f.step = 2;
      window.open(got.url, "_blank", "noopener");
      host.repaint();
      void reload();
      return;
    }
    if (name === "ag-coller") {
      const text2 = value("colle");
      if (!text2) {
        f.error = "Colle l'adresse de la page qui n'a pas pu s'ouvrir.";
        host.repaint();
        return;
      }
      const done = await googleFinish(f.account, text2);
      toast(done.message, { ico: "check" });
      f.step = 3;
      f.synced = true;
      await reload();
      return;
    }
    if (name === "ag-code") {
      f.values.address = value("address") || f.values.address;
      if (!f.account) {
        const saved = await saveAccount("microsoft", "", { label: f.values.address ? f.values.address.split("@")[0] : "Outlook", address: f.values.address }, newNonce());
        f.account = saved.account;
        f.key = `microsoft/${f.account}`;
      }
      const got = await microsoftStart(f.account);
      f.code = got.code;
      f.url = got.url;
      f.until = got.until;
      f.step = got.state === "connectee" ? 3 : 2;
      if (got.error) f.error = got.error;
      host.repaint();
      void reload();
      return;
    }
    if (name === "ag-essayer") {
      f.values.url = value("url");
      f.values.username = value("username");
      f.values.password = ($<HTMLInputElement>('[data-agf="password"]')?.value ?? "");
      const got = await tryCaldav(f.values.url, f.values.username, f.values.password);
      if (!got.ok) {
        f.error = got.message;
        host.repaint();
        return;
      }
      f.tried = got.calendars;
      f.step = 2;
      host.repaint();
      return;
    }
    if (name === "ag-brancher-caldav") {
      f.values.label = value("label") || f.values.label;
      const saved = await saveAccount("caldav", "", { label: f.values.label, url: f.values.url, username: f.values.username, password: f.values.password }, newNonce());
      toast(saved.message, { ico: "check" });
      flow = null;
      host.setSub(`agenda:${saved.account}`, "agendas");
      host.go(`${TAB}/${encodeURIComponent(saved.account)}`);
      void reload();
      return;
    }
    if (name === "ag-ical") {
      f.values.url = value("url");
      f.values.label = value("label");
      const saved = await saveAccount("ical", "", { label: f.values.label || "Abonnement", url: f.values.url }, newNonce());
      toast(saved.message, { ico: "check" });
      flow = null;
      host.setSub(`agenda:${saved.account}`, "agendas");
      host.go(`${TAB}/${encodeURIComponent(saved.account)}`);
      void reload();
      return;
    }
  } catch (err) {
    if (f && route.kind === "brancher") {
      f.error = failureText(err);
      host.repaint();
    } else toastFailure(err);
  }
}

export const agendasPage: Page = {
  id: "agendas",
  needs: () => [store.agendaAccounts, store.agendaCalendars],
  // ce que Mika fait de chacun, en une ligne : son tableau, une fois ses agendas lus
  extras: () => [store.me, ...(store.agendaCalendars.value?.calendars ?? []).filter((c) => c.level === "proprietaire" && c.can.rights && !c.hidden).map((c) => store.agendaRights.get(c.key))],
  view: (item, host) => {
    const r = parse(item);
    const now = Date.now();
    if (r.kind === "brancher") {
      advance(host);
      return brancherView(r.sort, r.account);
    }
    if (r.kind === "fiche") {
      const a = accountOf(r.account);
      if (!a) return `<div class="set-page">${backLink(TAB, "Agendas")}<div class="empty">${ico("agenda")}<b>Ce compte n'existe plus</b><p>Il a été retiré, ou il n'est pas à toi.</p></div></div>`;
      return accountView(a, host, now);
    }
    return listView(now);
  },
  actions: (item) => {
    const r = parse(item);
    if (r.kind === "brancher") return "";
    if (r.kind === "fiche") {
      const a = accountOf(r.account);
      return a && !a.system ? `<button class="btn" type="button" data-act="ag-sync" data-account="${h(a.key)}">${ico("refresh", "sm")}<span class="lbl">Synchroniser</span></button>` : "";
    }
    return `<a class="btn primary" href="${TAB}/brancher">${ico("plus", "sm")}<span class="lbl">Brancher un agenda</span></a>`;
  },
  act: (name, el, item, host) => void act(name, el, item, host),
  save: async (form, changes, _values, item, host) => {
    const r = parse(item);
    const a = accountOf(r.account);
    if (!a) return true;
    const out: Record<string, string> = {};
    for (const k of ["label", "url", "username", "password"]) {
      const v = changes[k] as FormValue | undefined;
      if (typeof v === "string" && (v || k === "label")) out[k] = v.trim();
    }
    // le serveur CalDAV ou l'identifiant changent : son mot de passe se redonne avec eux (le serveur le dit, 400)
    try {
      const done = await saveAccount(a.kind, a.key, out);
      toast(done.message, { ico: "check" });
      void host.reload(store.agendaAccounts, store.agendaCalendars);
      return true;
    } catch (err) {
      showRefusal(form, err);
      return false;
    }
  },
  after: (root, _item, host) => {
    if (listened.has(root)) return;
    listened.add(root);
    const reload = () => host.reload(store.agendaAccounts, store.agendaCalendars);
    // les réglages d'un agenda partent tout de suite (le nom, quand on quitte son champ)
    root.addEventListener("change", (e) => {
      const t = e.target as HTMLElement;
      const vis = t.closest<HTMLInputElement>("[data-agvis]");
      if (vis) {
        setShown(vis.dataset.agvis ?? "", vis.checked);
        toast(vis.checked ? "Il s'affiche dans ton Agenda." : "Il ne s'affiche plus dans ton Agenda (ce navigateur).", { ico: vis.checked ? "eye" : "eye-off" });
        return;
      }
      const masque = t.closest<HTMLInputElement>("[data-agmasque]");
      if (masque) {
        void saveCalendar(masque.dataset.agmasque ?? "", { hidden: !masque.checked }).then(() => {
          toast(masque.checked ? "Dans l'Agenda : Mika s'en sert de nouveau." : "Masqué : il ne s'affiche plus, et Mika ne s'en sert plus.", { ico: masque.checked ? "eye" : "eye-off" });
          void reload();
        }, toastFailure);
        return;
      }
      const rapp = t.closest<HTMLSelectElement>("[data-agrapp]");
      if (rapp) {
        void saveCalendar(rapp.dataset.agrapp ?? "", { reminder: rapp.value as "" }).then(() => {
          toast(rapp.value === "non" ? "Elle ne te rappellera pas ses rendez-vous." : "Rappel réglé.", { mika: true, ico: "bell" });
          void reload();
        }, toastFailure);
        return;
      }
      const nom = t.closest<HTMLInputElement>("[data-agnom]");
      if (nom) {
        void saveCalendar(nom.dataset.agnom ?? "", { name: nom.value.trim() }).then((d) => {
          toast(d.message, { ico: "check" });
          void reload();
        }, toastFailure);
      }
    });
    root.addEventListener("mika:seg", (e) => {
      const d = (e as CustomEvent<{ name?: string; value?: string }>).detail;
      if (d.name !== "agservice" || !flow) return;
      flow.service = d.value ?? "";
      const page = root.querySelector(".set-page");
      flow.values.url = ($<HTMLInputElement>('[data-agf="url"]', page ?? root)?.value ?? "").trim();
      flow.values.username = ($<HTMLInputElement>('[data-agf="username"]', page ?? root)?.value ?? "").trim();
      host.repaint();
    });
  },
  search: () => [
    { group: "Paramètres", title: "Agendas", sub: "tes comptes d'agenda", icon: "agenda", route: TAB },
    { group: "Paramètres", title: "Brancher un agenda", sub: "Google, Outlook, CalDAV, iCal, ce serveur", icon: "plus", route: `${TAB}/brancher` },
    ...(accounts()?.accounts ?? []).map((a) => ({ group: "Paramètres", title: `Compte d'agenda « ${a.label} »`, sub: a.address || kindLong(a), icon: "agenda" as IconName, route: `${TAB}/${encodeURIComponent(a.key)}` })),
  ],
};

