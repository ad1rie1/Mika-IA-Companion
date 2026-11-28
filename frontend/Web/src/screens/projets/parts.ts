/**
 * Projets, les morceaux que les vues partagent (pur) : la structure et les classes de la maquette validée
 * (`maquette/ecrans/projets2.js`) — pastilles d'état, tuiles, barres en segments, les trois zones (la liste, le
 * contenu en volets, le panneau latéral), les sections du panneau, les lignes liées, l'en-tête d'un détail, les
 * champs d'un formulaire (dans la zone de contenu, ou dans un panneau qui s'ouvre), un texte venu d'ailleurs.
 * Tout texte passe par `h` ; ce qui est déjà du HTML le dit dans son nom (`…Html`) ou sa doc.
 */
import type { Checks, Field, OutsideText, Pull, Review, TicketLine } from "../../api/projects";
import { mikaAvatar } from "../../mika/face";
import { personAvatar } from "../../shared/kit";
import { h } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { fieldShown, safeLink, type Values } from "./gestures";
import { inline } from "./md";
import { sheetRoute } from "./routes";
import { when } from "./time";
import { checksTone, pullTone, ticketTone, type Tone } from "./tones";

/** Une pastille d'état : la couleur d'un état, les mots du serveur ; `out` : venu d'ailleurs. */
export function st(tone: Tone | "out" | "", label: string, title = ""): string {
  return `<span class="p2-st ${tone}"${title ? ` title="${h(title)}"` : ""}>${tone === "out" ? ico("external", "xs") : ""}${h(label)}</span>`;
}

/** La marque d'un texte venu d'ailleurs. */
export const OUTSIDE = "venu d'ailleurs";

export function tile(icon: IconName, tone = ""): string {
  return `<span class="p2-tile ${tone}">${ico(icon)}</span>`;
}

export function empty(icon: IconName, title: string, text: string, moreHtml = ""): string {
  return `<div class="empty">${ico(icon)}<b>${h(title)}</b><p>${h(text)}</p>${moreHtml}</div>`;
}

export function nothing(icon: IconName, title: string, text: string, moreHtml = ""): string {
  return `<div class="p2-nothing">${ico(icon)}<b>${h(title)}</b><p>${h(text)}</p>${moreHtml}</div>`;
}

/** Une barre en segments : un segment par chose, à la couleur de son état. */
export function bar(tones: readonly string[]): string {
  const done = tones.filter((x) => x === "done").length;
  return `<span class="p2-seg" role="img" aria-label="${done} sur ${tones.length}">${tones.map((x) => `<i class="${x}"></i>`).join("")}</span>`;
}

/** Le logo d'un projet : sa première lettre, sur une teinte stable. */
export function logo(id: number | null, title: string): string {
  return `<span class="p2-logo c${(id ?? 0) % 8}">${h((title || "?")[0].toUpperCase())}</span>`;
}

/**
 * Un texte venu d'ailleurs (une issue d'un inconnu, un commentaire de l'hôte, la fin d'un journal, la sortie d'une
 * commande) : cité tel quel dans sa présentation à lui — un liseré hachuré, jamais une bulle —, échappé, sans lien ni
 * balisage. `mono` : une sortie, en chasse fixe.
 */
export function outside(source: string, text: string, mono = false): string {
  return `<figure class="p2-out"><figcaption>${ico("external", "xs")}Venu d'ailleurs · ${h(source)}<span>cité tel quel</span></figcaption>
    ${mono ? `<pre>${h(text)}</pre>` : `<blockquote>${h(text)}</blockquote>`}</figure>`;
}

/** Ce que dit un objet `{"text", "outside": true}` du serveur (ou `null`) : `""` s'il n'y a rien. */
export function outsideText(said: OutsideText | null | undefined, source: string, mono = true): string {
  return said && said.text ? outside(source, said.text, mono) : "";
}

/** Qui a écrit : son avatar (elle, toi, une autre personne, quelqu'un du dehors). */
export function authorAvatar(kind: string, author: string, me: string, size: "xs" | "sm" = "xs"): string {
  if (kind === "self") return mikaAvatar(size);
  if (kind === "you") return personAvatar(me || "toi", size);
  if (kind === "person") return personAvatar(author, size);
  return `<span class="av ${size} p2-av-out" title="${h(author)}">${ico(kind === "project" ? "flag" : "user", "xs")}</span>`;
}

/** Une bulle d'un fil : elle (rose), toi (indigo), quelqu'un d'autre. `textHtml` est déjà échappé. */
export function bubble(side: "elle" | "moi" | "autre", who: string, at: number, now: number, textHtml: string, avatarHtml = ""): string {
  return `<div class="p2-bub ${side}">${side === "moi" ? "" : avatarHtml}<div><span class="p2-bub-who">${h(who)}${at ? ` · ${when(at, now)}` : ""}</span><p>${textHtml}</p></div></div>`;
}

export function event(icon: IconName, text: string, at: number, now: number): string {
  return `<div class="p2-evt">${ico(icon, "xs")}<span>${h(text)}${at ? ` · ${when(at, now)}` : ""}</span></div>`;
}

export function banner(tone: string, icon: IconName, text: string, moreHtml = ""): string {
  return `<p class="p2-banner ${tone}">${ico(icon, "sm")}<span>${h(text)}</span>${moreHtml}</p>`;
}

/** Un refus du serveur, dit sur place avec ses mots. */
export function refusal(text: string): string {
  return text ? `<p class="p2-banner fail" role="alert">${ico("alert", "sm")}<span>${h(text)}</span></p>` : "";
}

export function hint(text: string, icon: IconName = "info"): string {
  return text ? `<p class="p2-hint">${ico(icon, "xs")}${h(text)}</p>` : "";
}

// ── Les trois zones ──────────────────────────────────────────────────

export type Pane = [key: string, label: string, count?: number | string | null];

export interface Trio {
  /** La liste (du HTML) ; `null` : deux zones seulement. */
  list?: string | null;
  /** L'en-tête du détail. */
  head?: string;
  /** Les volets du contenu, celui qui est ouvert, et l'adresse de chacun. */
  panes?: Pane[];
  active?: string;
  link?: (key: string) => string;
  /** Le volet ouvert ; `plain` : sans marge (un diagramme, un schéma, un fil). */
  body?: string;
  plain?: boolean;
  /** Ce qui reste en bas du contenu (de quoi écrire une note). */
  foot?: string;
  /** Le panneau latéral ; sur un téléphone, le volet « Infos ». */
  side?: string;
  /** Sur un téléphone : le détail est ouvert (sinon la liste), et où revenir. */
  open?: boolean;
  back?: [href: string, label: string];
  cls?: string;
  scroll?: string;
  /** Ce qui va à droite des volets. */
  tools?: string;
  /** À la place du détail, quand rien n'est choisi. */
  empty?: string;
  /** Le volet « Infos » est ouvert (téléphone). */
  infos?: boolean;
}

export function trio(o: Trio): string {
  const panes = o.panes ?? [];
  const infos = !!o.infos && !!o.side;
  const link = o.link ?? (() => "");
  const nav = panes.length
    ? `<nav class="p2-volets${panes.length > 1 ? "" : " seul"}" aria-label="Volets">${panes
        .map(([k, label, n]) => `<a href="${link(k)}" data-p2="volet" data-va="1"${k === o.active && !infos ? ' aria-current="page"' : ""}>${h(label)}${n !== null && n !== undefined ? `<span class="cnt">${h(n)}</span>` : ""}</a>`)
        .join("")}
      ${o.side ? `<button type="button" class="p2-v-infos" data-p2="infos"${infos ? ' aria-current="page"' : ""}>Infos</button>` : ""}${o.tools ? `<span class="p2-volets-side">${o.tools}</span>` : ""}</nav>`
    : "";
  const scroll = h(o.scroll ?? "detail");
  const detail =
    o.empty ??
    `${o.back ? `<a class="p2-back mobile-back" href="${o.back[0]}">${ico("chev-left", "sm")}${h(o.back[1])}</a>` : ""}${o.head ?? ""}
      <div class="p2-dz${infos ? " infos" : ""}${o.side ? "" : " sans-cote"}"><div class="p2-main">${nav}<div class="pane-scroll p2-vbody" data-scroll="${scroll}">${o.plain ? (o.body ?? "") : `<article class="p2-c">${o.body ?? ""}</article>`}</div>${o.foot ?? ""}</div>
        ${o.side ? `<aside class="p2-side pane-scroll" data-scroll="${scroll}-cote" aria-label="Infos">${o.side}</aside>` : ""}</div>`;
  const hasList = o.list !== null && o.list !== undefined;
  return `<div class="split p2-split${hasList ? "" : " sans-liste"}${o.open ? " lire" : ""}${o.cls ? ` ${o.cls}` : ""}">
      ${hasList ? `<section class="pane p2-list">${o.list}</section>` : ""}<section class="pane p2-detail">${detail}</section></div>`;
}

/** Une section du panneau latéral : des filets, jamais un cadre dans un cadre. Sans corps : rien. */
export function sc(title: string | null, bodyHtml: string, moreHtml = "", cls = ""): string {
  return bodyHtml ? `<section class="p2-sc${cls ? ` ${cls}` : ""}">${title ? `<h3>${h(title)}${moreHtml}</h3>` : ""}${bodyHtml}</section>` : "";
}

/** Des propriétés : le nom (du texte), la valeur (du HTML). */
export function props(rows: Array<[string, string] | null | false>): string {
  const shown = rows.filter((r): r is [string, string] => !!r);
  return shown.length ? `<dl class="p2-props">${shown.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>` : "";
}

/** Une chose liée, avec son état. `subHtml` et `stateHtml` sont du HTML. */
export function linked(href: string, icon: IconName, tone: string, title: string, subHtml = "", stateHtml = ""): string {
  const inner = `${tile(icon, tone)}<span><b>${h(title)}</b>${subHtml ? `<small>${subHtml}</small>` : ""}</span>${stateHtml || (href ? ico("chev-right", "sm") : "")}`;
  return href ? `<a class="p2-lie" href="${href}">${inner}</a>` : `<span class="p2-lie">${inner}</span>`;
}

/** Un ticket lié, en une ligne (sur un objectif, un accord) : son titre s'il se lit, son étape avec les mots du serveur. */
export function ticketLine(project: number, t: TicketLine): string {
  const tone = ticketTone({ status: t.status, open: t.open, yours: false });
  return linked(sheetRoute(project, "tickets", t.number), "p2-ticket", tone, t.title || t.veiled_label || `Ticket ${t.handle}`, h(t.handle), st(tone, t.status_label));
}

/** Une pull request liée, avec son titre et son statut : son état, sa CI, sa relecture ; et sa page chez l'hôte. */
export function pullCard(project: number, pull: Pull | null, checks: Checks | null, review: Review | null, now: number): string {
  if (!pull) return "";
  const tone = pullTone(pull.state);
  const dots = `<span class="p2-dots">${checks ? `<span title="${h(checks.state_label)}"><i class="${checksTone(checks.state)}"></i>CI</span>` : ""}${review ? `<span title="${h(review.label)}"><i class="${review.ok ? "done" : "wait"}"></i>${h(review.label)}</span>` : ""}</span>`;
  const url = safeLink(pull.url);
  return `<a class="p2-lie haut" href="${sheetRoute(project, "code", "pulls", pull.number)}">${tile(pull.state === "merged" ? "p2-merge" : "p2-pr", tone)}<span><b>${h(pull.title || `Pull request n° ${pull.number}`)}</b>
      <small>n° ${pull.number}${pull.words ? ` · ${h(pull.words)}` : ""}${pull.at ? ` · ${h(when(pull.at, now))}` : ""}</small><span class="p2-lie-etat">${st(tone, pull.state_label)}${pull.conflicts ? st("fail", "en conflit") : ""}${pull.changes_asked ? st("fail", "changements demandés") : ""}${pull.state === "open" ? dots : ""}</span></span></a>
    ${url ? `<a class="p2-more" href="${h(url)}" target="_blank" rel="noopener noreferrer">${ico("external", "xs")}Voir chez l'hôte</a>` : ""}`;
}

export interface Head {
  tileHtml?: string;
  /** Au-dessus du titre (du texte). */
  over?: string;
  num?: string;
  title: string;
  metaHtml?: string;
  rightHtml?: string;
}

export function head(o: Head): string {
  return `<header class="p2-dh">${o.tileHtml ?? ""}<div class="p2-dh-main">${o.over ? `<span class="p2-over">${h(o.over)}</span>` : ""}<h2>${o.num ? `<span class="p2-num">${h(o.num)}</span>` : ""}${h(o.title)}</h2>
    ${o.metaHtml ? `<div class="p2-meta">${o.metaHtml}</div>` : ""}</div>${o.rightHtml ? `<div class="p2-dh-side">${o.rightHtml}</div>` : ""}</header>`;
}

/** Des sous-onglets (Activité, Dépendances, Listes) : une rangée de pastilles, et ce qui va à droite. */
export function subbar(tabs: Array<[href: string, label: string, count?: number | string | null]>, active: number, rightHtml = ""): string {
  return `<div class="p2-subbar"><nav class="p2-sub" aria-label="Sous-onglets">${tabs
    .map(([href, label, n], i) => `<a href="${href}"${i === active ? ' aria-current="page"' : ""}>${h(label)}${n !== null && n !== undefined ? `<span class="cnt">${h(n)}</span>` : ""}</a>`)
    .join("")}</nav>${rightHtml ? `<div class="p2-subbar-side">${rightHtml}</div>` : ""}</div>`;
}

/** Les filtres en pastilles : celle qui est pressée, et le compte de chacune. */
export function filters(act: string, items: Array<[code: string, label: string, count?: number | string | null]>, pressed: string, cls = ""): string {
  return `<div class="p2-filters${cls ? ` ${cls}` : ""}">${items
    .map(([code, label, n]) => `<button type="button" data-p2="${act}" data-c="${h(code)}" aria-pressed="${code === pressed}">${h(label)}${n !== null && n !== undefined ? `<span class="cnt">${h(n)}</span>` : ""}</button>`)
    .join("")}</div>`;
}

/** Les éléments d'une liste, sous le repère de leur jour (« Aujourd'hui », « Hier », « lundi 2 novembre »). */
export function byDay<T>(items: readonly T[], at: (x: T) => number, day: (ms: number) => string, row: (x: T) => string): string {
  let last = "";
  return items
    .map((x) => {
      const d = day(at(x));
      const mark = d !== last ? `<div class="p2-day">${h(d)}</div>` : "";
      last = d;
      return mark + row(x);
    })
    .join("");
}

// ── Les formulaires ──────────────────────────────────────────────────

export interface FieldOpts {
  hint?: string;
  required?: boolean;
  type?: string;
  help?: string;
  rows?: number;
  mono?: boolean;
  /** Ce que le serveur a refusé de ce champ. */
  error?: string;
}

function under(o: FieldOpts): string {
  return `${o.help ? `<small>${h(o.help)}</small>` : ""}${o.error ? `<small class="p2-field-err">${h(o.error)}</small>` : ""}`;
}

export const F = {
  text: (name: string, label: string, value: unknown, o: FieldOpts = {}): string =>
    `<label class="field"><span>${h(label)}</span><input name="${h(name)}" value="${h(value ?? "")}"${o.hint ? ` placeholder="${h(o.hint)}"` : ""}${o.required ? " required" : ""}${o.type ? ` type="${o.type}"` : ""}${o.error ? ' class="p2-manque"' : ""}>${under(o)}</label>`,
  long: (name: string, label: string, value: unknown, o: FieldOpts = {}): string =>
    `<label class="field"><span>${h(label)}</span><textarea name="${h(name)}" rows="${o.rows ?? 4}"${o.hint ? ` placeholder="${h(o.hint)}"` : ""}${o.required ? " required" : ""} class="${o.mono ? "p2-mono" : ""}${o.error ? " p2-manque" : ""}">${h(value ?? "")}</textarea>${under(o)}</label>`,
  select: (name: string, label: string, value: unknown, options: ReadonlyArray<readonly [string, string]>, o: FieldOpts = {}): string =>
    `<label class="field"><span>${h(label)}</span><select name="${h(name)}">${options
      .map(([k, l]) => `<option value="${h(k)}"${String(k) === String(value ?? "") ? " selected" : ""}>${h(l)}</option>`)
      .join("")}</select>${under(o)}</label>`,
  cards: (name: string, label: string, value: unknown, options: ReadonlyArray<readonly [string, string, string?]>, o: FieldOpts = {}): string =>
    `<fieldset class="p2-cards"><legend>${h(label)}</legend><div>${options
      .map(([k, l, sub]) => `<label><input type="radio" name="${h(name)}" value="${h(k)}"${String(k) === String(value ?? "") ? " checked" : ""}><span><b>${h(l)}</b>${sub ? `<small>${h(sub)}</small>` : ""}</span></label>`)
      .join("")}</div>${under(o)}</fieldset>`,
  check: (name: string, label: string, on: boolean, sub = "", value = ""): string =>
    `<label class="p2-check"><input type="checkbox" name="${h(name)}"${value ? ` value="${h(value)}"` : ""}${on ? " checked" : ""}><span><b>${h(label)}</b>${sub ? `<small>${h(sub)}</small>` : ""}</span></label>`,
  group: (label: string, bodyHtml: string, help = ""): string => `<fieldset class="p2-group"><legend>${h(label)}</legend>${help ? `<p>${h(help)}</p>` : ""}${bodyHtml}</fieldset>`,
  two: (...fields: string[]): string => `<div class="p2-two">${fields.join("")}</div>`,
};

/**
 * Un champ décrit par le serveur (`fields` : les champs des actions de la console) : son libellé, son aide et ses choix
 * sont les siens. Un champ qui ne sert que pour certaines valeurs d'un autre (`only`) se cache tant qu'elles n'y sont
 * pas (`data-only`, relu à chaque saisie). **Un champ qu'elle ne peut pas changer** (`can: false` : la garde de
 * l'enregistrement, dite d'avance) se montre verrouillé — sa valeur se lit, rien ne s'y saisit — avec la raison du
 * serveur (`why`) ; `lockedAll` : tout le formulaire l'est.
 */
export function served(f: Field, values: Values, errors: Record<string, string> = {}, lockedAll = false): string {
  const o: FieldOpts = { help: f.help, required: f.required, error: errors[f.name] };
  const value = f.name in values ? values[f.name] : f.value;
  const choices = (f.choices ?? []).map((c) => [c.code, c.label] as const);
  let out: string;
  if (f.kind === "bool") out = F.check(f.name, f.label, value === true, f.help) + (o.error ? `<small class="p2-field-err">${h(o.error)}</small>` : "");
  else if (Array.isArray(f.value)) {
    const on = new Set(([] as unknown[]).concat(value ?? []).map(String));
    out = F.group(f.label, `<div class="p2-checks-grid">${choices.map(([k, l]) => F.check(f.name, l, on.has(k), "", k)).join("")}</div>${o.error ? `<small class="p2-field-err">${h(o.error)}</small>` : ""}`, f.help);
  } else if (choices.length) out = choices.length <= 4 && f.kind !== "select" ? F.cards(f.name, f.label, value, choices, o) : F.select(f.name, f.label, value, f.required ? choices : [["", "—"] as const, ...choices.filter(([k]) => k !== "")], o);
  else if (f.kind === "textarea") out = F.long(f.name, f.label, value, { ...o, rows: 4 });
  else if (f.kind === "int") out = `<label class="field"><span>${h(f.label)}</span><input name="${h(f.name)}" type="number" value="${h(value ?? "")}"${f.min !== null && f.min !== undefined ? ` min="${f.min}"` : ""}${f.max !== null && f.max !== undefined ? ` max="${f.max}"` : ""}${o.error ? ' class="p2-manque"' : ""}>${under(o)}</label>`;
  else out = F.text(f.name, f.label, value, o);
  const only = f.only?.length ? ` data-only="${h(JSON.stringify(f.only))}"${fieldShown(f, values) ? "" : " hidden"}` : "";
  const locked = lockedAll || f.can === false;
  if (!locked) return `<div class="p2-served"${only}>${out}</div>`;
  const why = f.can === false && f.why ? `<p class="p2-verrou">${ico("lock", "xs")}<span>${h(f.why)}</span></p>` : "";
  return `<div class="p2-served verrou"${only}>${out.replace(/<(input|select|textarea)\b/g, "<$1 disabled")}${why}</div>`;
}

export interface FormOpts {
  /** Le nom de sa suite (`forms[name]`). */
  name: string;
  /** Ce qui l'identifie d'un dessin à l'autre : ce qui est saisi y reste. */
  key: string;
  data?: Record<string, string | number>;
  title: string;
  sub?: string;
  bodyHtml: string;
  cancel: string;
  submit?: string;
  /** Un refus du serveur, dit dans le formulaire. */
  error?: string;
  /** Elle ne peut pas l'envoyer : pas de bouton, et pourquoi (les mots du serveur). */
  locked?: string;
}

function dataset(d: Record<string, string | number> | undefined): string {
  return Object.entries(d ?? {})
    .map(([k, v]) => `data-${k}="${h(v)}"`)
    .join(" ");
}

/** Un formulaire dans la zone de contenu : on ne perd pas où l'on était. */
export function form(o: FormOpts): string {
  return `<form class="p2-form" data-p2-form="${h(o.name)}" data-form-key="${h(o.key)}" ${dataset(o.data)}><header class="p2-form-h"><h3>${h(o.title)}</h3>${o.sub ? `<p>${h(o.sub)}</p>` : ""}</header>${refusal(o.error ?? "")}${o.bodyHtml}
    <footer class="p2-form-foot">${o.locked ? hint(o.locked, "lock") : ""}<a class="btn" href="${o.cancel}">${o.locked ? "Fermer" : "Annuler"}</a>${o.locked ? "" : `<button class="btn primary" type="submit">${ico("check", "sm")}${h(o.submit ?? "Enregistrer")}</button>`}</footer></form>`;
}

export interface DrawerOpts {
  name: string;
  key: string;
  data?: Record<string, string | number>;
  title: string;
  sub?: string;
  bodyHtml: string;
  submit?: string;
  error?: string;
}

/** Un panneau qui s'ouvre à droite, pour un ajout. */
export function drawer(o: DrawerOpts): string {
  return `<div class="p2-drawer-scrim" data-p2="drawerClose"></div><aside class="p2-drawer" role="dialog" aria-label="${h(o.title)}"><header><div><h2>${h(o.title)}</h2>${o.sub ? `<p>${h(o.sub)}</p>` : ""}</div>
      <button class="btn icon ghost" type="button" data-p2="drawerClose" title="Fermer">${ico("x")}</button></header>
      <form data-p2-form="${h(o.name)}" data-form-key="${h(o.key)}" ${dataset(o.data)}><div class="p2-drawer-body">${refusal(o.error ?? "")}${o.bodyHtml}</div>
        <footer><button class="btn" type="button" data-p2="drawerClose">${o.submit === "" ? "Fermer" : "Annuler"}</button>${o.submit === "" ? "" : `<button class="btn primary" type="submit">${h(o.submit ?? "Enregistrer")}</button>`}</footer></form></aside>`;
}

/** Un plan à lire : son texte (Markdown léger), et ses questions s'il en pose. */
export function planBlock(titleHtml: string, bodyHtml: string, yours: boolean, noteHtml = ""): string {
  return `<section class="p2-plan${yours ? " you" : ""}"><header>${ico("p2-plan")}${titleHtml}</header><div class="p2-md court">${bodyHtml}</div>${noteHtml}</section>`;
}

/** Du `code` dans une ligne de texte (échappée d'abord). */
export function code(text: string): string {
  return inline(text);
}
