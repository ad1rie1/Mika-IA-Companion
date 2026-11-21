/**
 * Trois vues d'une fiche (pur) : **Dépendances** (le schéma — le projet au centre, ce dont il dépend d'un côté, ce qui
 * dépend de lui de l'autre —, le panneau d'un lien : depuis quand, pourquoi, ce qu'il donne, le commit que montre la
 * vue, les demandes dans les deux sens, « Lui demander quelque chose » ; « Ajouter une dépendance », où le mot du lien se
 * saisit ; le volet Demandes), **Listes** (une liste en colonnes par statut, ou en tableau : seulement dans un projet
 * qui en a ; ajouter un élément, changer à qui il est) et **Modifier le projet** (ses réglages en sections, dont les
 * champs sont ceux que le serveur décrit ; un champ qu'elle ne peut pas changer se montre verrouillé, avec sa raison).
 * Un projet lié ne dit son nom que si la personne le voit elle-même.
 */
import type { Demand, EntryPage, Gives, Linked, Links, Listing, Overview, Reader, Reading, Settings, Sheet } from "../../../api/projects";
import { h } from "../../../shell/dom";
import { ico, type IconName } from "../../../shell/icons";
import { forWhom, GIVEN, givenCount, linkCandidates, plural, type Values } from "../gestures";
import { banner, empty, F, form, head, hint, linked, logo, nothing, OUTSIDE, props, refusal, sc, served, st, subbar, tile, trio, type Trio } from "../parts";
import { sheetRoute } from "../routes";
import { chosen, fieldErrorsAt, followLists, refusalAt, ticketList } from "../state";
import { moment, shortDate, when } from "../time";
import { askTone, projectTone } from "../tones";
import { projectState } from "./sheet";
import { waitingBlock, type Ctx, type Got } from "./todo";

// ── Dépendances ──────────────────────────────────────────────────────

/** Les quatre choses qu'un lien donne, en mots. */
const GIVEN_WORDS: Record<(typeof GIVEN)[number], [string, string]> = {
  see: ["le voir", "le minimum : son nom, son état, où il en est"],
  detail: ["son détail", "ses objectifs, ses tickets, son activité"],
  files: ["ses fichiers", "le dépôt, en lecture"],
  docs: ["sa documentation", "ses pages, en lecture"],
};

type Side = "lit" | "luPar";
type Link = (Reading | Reader) & { side: Side };

const hidden = "un projet que tu ne vois pas";
const linkKey = (x: Link, i: number): string => `${x.side}-${x.project ?? `x${i}`}`;

function gives(g: Gives): string {
  return `<span class="p2-gives">${GIVEN.map((k) => `<span class="${g[k] ? "oui" : "non"}">${ico(g[k] ? "check" : "x", "xs")}${GIVEN_WORDS[k][0]}</span>`).join("")}</span>`;
}

/** Les demandes d'un lien (celles du projet, et les tickets qu'elle a ouverts chez lui). */
const asksOf = (x: Link): Demand[] => x.asks ?? [];

/** Toutes les demandes de la fiche, les plus récentes d'abord : envoyées, reçues, et ses tickets à elle chez un projet lu. */
export function allDemands(links: Links): Demand[] {
  const yours = links.reads.flatMap((r) => (r.asks ?? []).filter((a) => a.from === "you"));
  return [...links.asks, ...(links.received ?? []), ...yours].sort((a, b) => b.at - a.at);
}

/** La clé d'une demande dans son adresse : son sens, l'autre projet, son numéro là où elle vit. */
export function demandKey(a: Demand, i: number): string {
  return `${a.direction === "received" ? "recue" : a.from === "you" ? "toi" : "envoyee"}-${a.project ?? "x"}-${a.number || `i${i}`}`;
}

/** Le nom de l'autre projet d'une demande : celui du lien du même numéro (une demande ne le redit pas), si elle le voit. */
function projectName(sheet: Sheet, overview: Overview | null, project: number | null): string {
  if (project === null) return hidden;
  const l = sheet.links;
  const found = [...(l?.reads ?? []), ...(l?.readers ?? []), ...(l?.candidates ?? [])].find((x) => x.project === project && x.visible)?.title ?? overview?.projects.find((p) => p.id === project)?.title;
  return found ? `« ${found} »` : hidden;
}

const demandTitle = (a: Demand): string => a.title || (a.veiled ? "Une demande que tu ne lis pas" : `Demande n° ${a.number}`);
const demandSense = (a: Demand): string => (a.direction === "received" ? "reçue" : a.from === "you" ? "ouverte par toi" : "envoyée");
const demandState = (a: Demand): string => st(askTone(a.status), a.step_label || a.status_label, a.status_label);

function node(sheet: Sheet, overview: Overview | null, x: Link, key: string, on: boolean, ctx: Ctx): string {
  const other = x.visible && x.project !== null ? overview?.projects.find((p) => p.id === x.project) : undefined;
  const asks = asksOf(x).length;
  const reading = x.side === "lit" ? (x as Reading) : null;
  const commit = reading?.commit ?? null;
  return `<a class="p2-sch-node ${x.side}" href="${sheetRoute(sheet.project.id, "dependances", key)}" aria-selected="${on}"><span class="p2-sch-top">${logo(x.project, x.visible ? x.title : "?")}<span class="p2-sch-t"><b>${h(x.visible ? x.title : hidden)}</b><small>${other ? h(forWhom(other)) : ""}</small></span>${other ? st(projectTone(other.status), other.status_label) : ""}${reading?.suspended ? st("fail", "suspendu") : ""}</span>
      ${x.why ? `<span class="p2-sch-why">${h(x.why)}</span>` : ""}
      ${gives(x.gives)}
      <span class="p2-sch-foot">${commit ? `${ico("p2-commit", "xs")}<code>${h(commit.short)}</code><span>${h(when(commit.at, ctx.now))}</span>` : `${ico("send", "xs")}<span>${h(x.gives.ask_label)}</span>`}<em>${asks ? plural(asks, "demande", "demandes") : "aucune demande"}</em></span>
      <span class="p2-sch-fleche" aria-hidden="true"><em>${x.side === "lit" ? "lu par lui" : "le lit"}</em></span></a>`;
}

function linkPanel(sheet: Sheet, overview: Overview | null, x: Link, ctx: Ctx): string {
  const id = sheet.project.id;
  const links = sheet.links!;
  const other = x.visible && x.project !== null ? overview?.projects.find((p) => p.id === x.project) : undefined;
  const reading = x.side === "lit" ? (x as Reading) : null;
  const all = allDemands(links);
  const asks = asksOf(x);
  const d = `data-p="${id}" data-c="${x.project ?? ""}"`;
  const mine = links.can && x.visible && x.project !== null && !!reading;
  const commit = reading?.commit ?? null;
  const here = reading?.ask_here;
  return sc(null, `<div class="p2-side-h">${logo(x.project, x.visible ? x.title : "?")}<span><b>${h(x.visible ? x.title : hidden)}</b><small>${x.side === "lit" ? `« ${h(sheet.project.title)} » le lit` : `il lit « ${h(sheet.project.title)} »`}${x.since ? ` · depuis le ${h(shortDate(x.since))}` : ""}</small></span>${other ? st(projectTone(other.status), other.status_label) : ""}</div>
      ${refusal(refusalAt(ctx.ui, `link:${id}`))}${reading?.suspended ? banner("fail", "alert", "Ce lien est suspendu : il ne donne rien pour l'instant.") : ""}${x.visible ? "" : hint("Tu ne vois pas ce projet : ce que le lien donne se dit, quel projet, non. Un tel lien reste tel quel.", "lock")}
      ${x.why ? `<p class="p2-sc-text">${h(x.why)}</p>` : ""}${mine ? `<button class="p2-more" type="button" data-p2="linkWhy" ${d}>${ico("pen", "xs")}${x.why ? "Changer ce mot" : "Dire pourquoi il le lit"}</button>` : ""}`)
    + sc(x.side === "lit" ? "Ce que le lien lui donne" : "Ce qu'il lui donne", `<ul class="p2-dons lecture">${GIVEN.map((k) => `<li class="${x.gives[k] ? "oui" : "non"}">${ico(x.gives[k] ? "check" : "x", "xs")}<span><b>${GIVEN_WORDS[k][0][0].toUpperCase() + GIVEN_WORDS[k][0].slice(1)}</b><small>${GIVEN_WORDS[k][1]}</small></span></li>`).join("")}</ul>
        ${hint("Ce qu'un lien donne vient des lignes d'accès du projet lu : cela se lit ici, sans s'y régler.")}`)
    + sc("Le commit que montre la vue", commit && x.project !== null ? `<a class="p2-lastc" href="${sheetRoute(x.project, "code", "commits", commit.short)}"><code>${h(commit.short)}</code><span class="ellipsis">${h(commit.title)}</span><time>${h(when(commit.at, ctx.now))}</time></a>${commit.outside ? `<p class="p2-sc-text">${st("out", OUTSIDE)}</p>` : ""}` : "")
    + sc("Ses demandes", `<p class="p2-sc-text">${h(x.gives.ask_label)}</p>${mine ? `<label class="p2-check"><input type="checkbox" data-p2-change="linkDirect" ${d}${reading?.direct ? " checked" : ""}><span><b>Ses demandes y entrent directement</b><small>sinon, chacune est proposée à son propriétaire</small></span></label>` : ""}`)
    + sc("Les demandes entre les deux", (asks.map((a) => linked(sheetRoute(id, "dependances", "demandes", demandKey(a, all.indexOf(a))), a.direction === "received" ? "download" : "upload", askTone(a.status), demandTitle(a), `${demandSense(a)} · ${h(when(a.at, ctx.now))}`, demandState(a))).join("") || '<p class="p2-none">Aucune demande entre ces deux projets.</p>')
      + (here?.can ? `<div class="p2-decide"><button class="btn" type="button" data-p2="askHere" ${d}>${ico("send", "sm")}Lui demander quelque chose</button></div>` : here?.why ? hint(here.why, "lock") : ""), `<span class="cnt">${asks.length}</span>`)
    + sc("Gérer", `<div class="p2-decide">${x.visible && x.project !== null ? `<a class="btn" href="${sheetRoute(x.project)}">${ico("external", "sm")}Ouvrir « ${h(x.title)} »</a>` : ""}${mine ? `<button class="btn danger" type="button" data-p2="linkRemove" ${d}>${ico("trash", "sm")}Retirer la dépendance</button>` : ""}</div>`, "", "bas");
}

/** Le corps du panneau « Ajouter une dépendance » : les projets qu'elle peut lui faire lire, ce que chaque lien donnerait, et son mot. */
export function linkDrawerBody(sheet: Sheet, errors: Record<string, string> = {}): string {
  const options = linkCandidates(sheet.links!);
  if (!options.length) return nothing("link", "Aucun projet à lui faire lire", "Il lit déjà ceux qu'il peut lire, ou tu n'en vois pas d'autre.");
  return `<fieldset class="p2-cards"><legend>Le projet dont il dépendra</legend><div>${options
    .map((c, i) => `<label><input type="radio" name="project" value="${c.project}"${i ? "" : " checked"}><span><b>${h(c.title)}</b><small>${c.gives.see ? `donnerait : ${GIVEN.filter((k) => c.gives[k]).map((k) => GIVEN_WORDS[k][0]).join(", ")}` : "ne donnerait rien pour l'instant"} · ${h(c.gives.ask_label)}</small></span></label>`)
    .join("")}</div></fieldset>${F.text("why", "Pourquoi", "", { hint: "Par exemple : pour citer ses commandes sans les inventer", help: "Le mot du lien : pourquoi ce projet lit l'autre. Il se lit sur le schéma.", error: errors.why })}
    ${hint("Ce que le lien donne — le voir, son détail, ses fichiers, sa documentation — vient des lignes d'accès du projet lu : cela ne se choisit pas ici.")}`;
}

/** Le corps du panneau « Lui demander quelque chose » : un ticket qu'elle ouvre elle-même chez le projet lu. */
export function askDrawerBody(born: string, errors: Record<string, string> = {}): string {
  return `${F.text("title", "Ce que tu lui demandes", "", { required: true, hint: "Par exemple : exposer la liste des hôtes en JSON", error: errors.title })}
    ${F.long("text", "Pourquoi, et pour quand", "", { rows: 4, error: errors.text })}
    ${hint(born === "proposed" ? "Le ticket naîtra proposé : le propriétaire de ce projet l'accepte ou l'écarte." : "Le ticket s'ouvre chez ce projet : elle le lira à son prochain passage.")}`;
}

function schema(sheet: Sheet, overview: Overview | null, rest: string[], ctx: Ctx): string {
  const id = sheet.project.id;
  const links = sheet.links!;
  const all: Link[] = [...links.reads.map((x): Link => ({ ...x, side: "lit" })), ...links.readers.map((x): Link => ({ ...x, side: "luPar" }))];
  const keys = all.map(linkKey);
  const at = keys.indexOf(rest[0] ?? "");
  const pick = at >= 0 ? all[at] : ctx.mobile ? null : (all[0] ?? null);
  const add = links.can ? `<button class="btn primary" type="button" data-p2="linkAdd" data-p="${id}">${ico("plus", "sm")}Ajouter une dépendance</button>` : "";
  const column = (title: string, sub: string, side: Side): string => {
    const mine = all.map((x, i) => [x, keys[i]] as const).filter(([x]) => x.side === side);
    const asked = side === "lit" ? links.plan_asks.map((x: Linked) => `<p class="p2-none box">${ico("p2-plan", "xs")} Son plan demande à lire ${x.visible ? `« ${h(x.title)} »` : hidden}.</p>`).join("") : "";
    return `<div class="p2-sch-col ${side}"><h3>${h(title)}<span class="cnt">${mine.length}</span></h3><p>${sub}</p>${mine.map(([x, k]) => node(sheet, overview, x, k, x === pick, ctx)).join("") || `<p class="p2-none box">${side === "lit" ? "Il ne dépend d'aucun autre projet." : "Aucun projet ne dépend de lui."}</p>`}${asked}</div>`;
  };
  const p = sheet.project;
  const body = `<div class="p2-schzone"><div class="p2-schema">
        ${column(links.labels?.reads || "Il dépend de", "les projets qu'il lit", "lit")}
        <div class="p2-sch-centre">${logo(p.id, p.title)}<b>${h(p.title)}</b>${projectState(p)}<small>${h(p.description || p.where)}</small>
          <dl><div><dt>${(sheet.objectives ?? []).filter((o) => o.status !== "done").length}</dt><dd>objectifs en cours</dd></div><div><dt>${ticketList(sheet)?.living ?? 0}</dt><dd>tickets ouverts</dd></div><div><dt>${links.asks.length}</dt><dd>demandes envoyées</dd></div></dl></div>
        ${column(links.labels?.readers || "Dépendent de lui", "les projets qui le lisent", "luPar")}</div>
      ${hint("Une flèche va du projet lu vers celui qui le lit. Choisis un projet pour voir ce que le lien donne.")}</div>`;
  if (ctx.mobile && pick && rest[0]) {
    return trio({ list: "", open: true, back: [sheetRoute(id, "dependances"), "Le schéma"], panes: [["", "Le lien"]], active: "", link: () => sheetRoute(id, "dependances", rest[0]), scroll: "lien", body: `<div class="p2-flat">${linkPanel(sheet, overview, pick, ctx)}</div>` });
  }
  return trio({
    panes: [["", "Schéma"]], active: "", link: () => sheetRoute(id, "dependances"), plain: true, scroll: `schema-${id}`, body, infos: ctx.ui.infos,
    side: ctx.mobile ? "" : pick ? linkPanel(sheet, overview, pick, ctx)
      : sc("Aucune dépendance", `${refusal(refusalAt(ctx.ui, `link:${id}`))}<p class="p2-sc-text">Un projet qui dépend d'un autre peut le voir, lire ses fichiers et sa documentation, et lui demander quelque chose.</p>${add ? `<div class="p2-decide">${add}</div>` : ""}`),
  });
}

/** Une demande : son sens, son étape (celle du parcours, et sa précision), où son ticket se lit. Son texte vit dans son ticket. */
function askDetail(sheet: Sheet, overview: Overview | null, a: Demand, key: string, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const tone = askTone(a.status);
  const received = a.direction === "received";
  const where = projectName(sheet, overview, a.project);
  // où vit le ticket : dans ce projet pour une demande reçue, chez l'autre pour une demande envoyée
  const home = received ? id : a.project;
  const open = a.number && home !== null && (received || a.visible) ? `<div class="p2-acts"><a class="btn" href="${sheetRoute(home, "tickets", a.number)}">Ouvrir le ticket ${received ? `#${a.number}` : `chez ${h(where)}`}${ico("chev-right", "sm")}</a></div>` : hint("Tu ne vois pas le projet où vit ce ticket : il ne se lit pas d'ici.", "lock");
  const lede = received ? `${where[0].toUpperCase() + where.slice(1)} a demandé quelque chose à ce projet : ici, c'est le ticket n° ${a.number}.`
    : a.from === "you" ? `Tu as ouvert ce ticket toi-même chez ${where} : c'est le tien, pas une demande de « ${sheet.project.title} ».`
    : `Ce projet a demandé quelque chose à ${where} : là-bas, c'est le ticket n° ${a.number}, et c'est là que son texte et son fil se lisent.`;
  const side: Side = received ? "luPar" : "lit";
  return {
    scroll: `dem-${key}`, panes: [["", "La demande"]], active: "", link: () => sheetRoute(id, "dependances", "demandes", key),
    head: head({ tileHtml: tile(received ? "download" : "upload", tone), over: received ? "Demande reçue" : a.from === "you" ? "Ton ticket chez lui" : "Demande envoyée", title: demandTitle(a),
      metaHtml: `${demandState(a)}<span>${received ? "de" : "à"} ${h(where)}</span><span>${h(when(a.at, ctx.now))}</span>` }),
    body: `<p class="p2-lede">${h(lede)}</p>${a.veiled ? hint("Son titre ne se lit pas d'ici : il se lit là où vit le ticket, par qui peut le lire.", "lock") : ""}${open}`,
    side: sc("En bref", props([["Sens", `${demandSense(a)} : ${received ? `${h(where)} demande à ce projet` : `${a.from === "you" ? "tu demandes" : "ce projet demande"} à ${h(where)}`}`], ["Étape", demandState(a)], a.step_label && a.status_label !== a.step_label ? ["Précision", h(a.status_label)] : null,
        ["Depuis", h(moment(a.at, ctx.now))], a.closed_at ? ["Close", h(moment(a.closed_at, ctx.now))] : null]))
      + sc("Le lien", a.project !== null && a.visible ? linked(sheetRoute(id, "dependances", `${side}-${a.project}`), "link", "", where.replace(/^« | »$/g, ""), received ? "il lit ce projet" : "ce projet le lit") : "")
      + sc("Le projet", a.visible && a.project !== null ? linked(sheetRoute(a.project), "flag", "", where.replace(/^« | »$/g, ""), received ? "le projet qui demande" : "le projet à qui elle est adressée") : ""),
  };
}

function asksView(sheet: Sheet, overview: Overview | null, rest: string[], ctx: Ctx): string {
  const id = sheet.project.id;
  const links = sheet.links!;
  const items = allDemands(links);
  const keys = items.map(demandKey);
  const at = keys.indexOf(rest[0] ?? "");
  const a = at >= 0 ? items[at] : ctx.mobile ? null : (items[0] ?? null);
  const key = a ? keys[items.indexOf(a)] : "";
  const askable = links.reads.some((r) => r.ask_here?.can);
  const list = `<div class="p2-tools"><h2 class="grow">Demandes entre projets</h2>${askable ? `<button class="btn primary" type="button" data-p2="askHere" data-p="${id}">${ico("send", "sm")}<span>Nouvelle demande</span></button>` : ""}</div>
      <div class="pane-scroll" data-scroll="demandes">${items.length
        ? items.map((x, i) => `<a class="li p2-row" href="${sheetRoute(id, "dependances", "demandes", keys[i])}" aria-selected="${x === a}">${tile(x.direction === "received" ? "download" : "upload", askTone(x.status))}<span class="li-main"><span class="li-title">${h(demandTitle(x))}</span>
            <span class="p2-row-sub">${demandState(x)}<span class="ellipsis">${x.direction === "received" ? "de" : "à"} ${h(projectName(sheet, overview, x.project))}</span><time>${h(when(x.at, ctx.now))}</time></span></span></a>`).join("")
        : empty("send", "Aucune demande", "Ni reçue, ni envoyée.")}</div>`;
  return trio({ list, open: !!rest[0] && !!a, back: [sheetRoute(id, "dependances", "demandes"), "Demandes"], infos: ctx.ui.infos,
    ...(a ? askDetail(sheet, overview, a, key, ctx) : { empty: empty("send", "Aucune demande", "Ce qu'un projet demande à un autre s'ouvre ici, avec son étape.") }) });
}

export function dependenciesView(sheet: Sheet, overview: Overview | null, rest: string[], ctx: Ctx): string {
  const id = sheet.project.id;
  const links = sheet.links;
  if (!links) return empty("link", "Dépendances", "Ce projet ne dit rien de ses liens.");
  const asks = rest[0] === "demandes";
  const bar = subbar([[sheetRoute(id, "dependances"), "Schéma", links.reads.length + links.readers.length], [sheetRoute(id, "dependances", "demandes"), "Demandes", allDemands(links).length]], asks ? 1 : 0,
    links.can ? `<button class="btn sm" type="button" data-p2="linkAdd" data-p="${id}">${ico("plus", "sm")}<span class="lbl">Ajouter une dépendance</span></button>` : "");
  return `${bar}<div class="p2-under">${asks ? asksView(sheet, overview, rest.slice(1), ctx) : schema(sheet, overview, rest[0] === "schema" ? rest.slice(1) : rest, ctx)}</div>`;
}

// ── Listes ───────────────────────────────────────────────────────────

/** La couleur d'un statut d'une liste : ouvert (en attente), clos (fait). */
const statusTone = (list: Listing, code: string): string => (list.closed.some((s) => s.code === code) ? "done" : list.open[0]?.code === code ? "wait" : "work");

export function listsView(sheet: Sheet, rest: string[], page: Got<EntryPage>, ctx: Ctx): string {
  const id = sheet.project.id;
  const lists = followLists(sheet);
  const list = lists.find((l) => l.name === rest[0]) ?? lists[0];
  if (!list) return empty("p2-board", "Pas de liste", "Ce projet ne suit aucune liste.");
  const items = page.value?.items ?? [];
  const pill = (e: EntryPage["items"][number]): string => sheet.rights.status
    ? `<button class="p2-st ${statusTone(list, e.status)} p2-stbtn" type="button" data-p2="itemStatus" data-p="${id}" data-l="${h(list.name)}" data-c="${h(e.key)}" title="Changer le statut">${h(e.status_label)}${ico("chev-down", "xs")}</button>`
    : st(statusTone(list, e.status) as "wait", e.status_label);
  // à qui il est : un bouton quand la liste dit qu'elle peut le changer (`can.assign`), sinon ses mots seuls
  const who = (e: EntryPage["items"][number]): string => list.can?.assign && !e.veiled
    ? `<button class="p2-charge" type="button" data-p2="itemAssign" data-p="${id}" data-l="${h(list.name)}" data-c="${h(e.key)}" title="À la charge de ${h(e.actor_label)} — changer">${h(e.actor_label)}${ico("chev-down", "xs")}</button>`
    : `<span class="p2-charge fixe">${h(e.actor_label)}</span>`;
  const body = !page.value
    ? waitingBlock(page)
    : ctx.ui.listView === "table"
      ? `<div class="fill-scroll" data-scroll="suivi-t"><div class="p2-tablefull">${refusal(refusalAt(ctx.ui, `list:${id}`))}<table class="tbl p2-suivi-t"><thead><tr><th>Nom</th><th>Statut</th><th>À la charge de</th><th>Notes</th><th>Depuis</th></tr></thead><tbody>
          ${items.map((e) => `<tr><td><b>${h(e.title || e.veiled_label)}</b><small>${h(e.key)}</small></td><td>${pill(e)}</td><td>${who(e)}</td><td class="p2-td-note">${e.notes ? plural(e.notes, "note", "notes") : ""}</td><td class="nowrap muted">${h(when(e.updated_at || e.at, ctx.now))}</td></tr>`).join("")}</tbody></table></div></div>`
      : `<div class="p2-board" data-scroll="suivi-b">${[...list.open, ...list.closed].map((s) => {
          const mine = items.filter((e) => e.status === s.code);
          return `<section class="p2-col"><header><i class="${statusTone(list, s.code)}"></i><b>${h(s.label)}</b><span class="cnt">${list.counts[s.code] ?? mine.length}</span></header><div class="p2-col-in">${mine
            .map((e) => `<article class="p2-kcard${e.yours ? " atoi" : ""}"><b>${h(e.title || e.veiled_label)}</b><small>${h(e.key)}</small>${e.notes ? `<p>${plural(e.notes, "note", "notes")} dans son fil</p>` : ""}<footer>${who(e)}<time>${h(when(e.updated_at || e.at, ctx.now))}</time>${pill(e)}</footer></article>`)
            .join("") || '<p class="p2-none">Rien ici.</p>'}</div></section>`;
        }).join("")}</div>${refusal(refusalAt(ctx.ui, `list:${id}`))}`;
  const bar = subbar(lists.map((l): [string, string, number] => [sheetRoute(id, "listes", l.name), l.title, l.total]), lists.indexOf(list),
    `<span class="p2-sync wide">${list.living} en cours sur ${list.total}</span><div class="seg p2-viewseg"><button type="button" data-p2="listView" data-c="columns" aria-pressed="${ctx.ui.listView === "columns"}">${ico("p2-board", "sm")}Colonnes</button><button type="button" data-p2="listView" data-c="table" aria-pressed="${ctx.ui.listView === "table"}">${ico("p2-table", "sm")}Tableau</button></div>
      ${list.can?.add ? `<button class="btn sm primary" type="button" data-p2="itemAdd" data-p="${id}" data-l="${h(list.name)}">${ico("plus", "sm")}<span class="lbl">Ajouter</span></button>` : ""}`);
  return `${bar}<div class="p2-under">${body}</div>`;
}

/** Le corps du panneau « Ajouter à une liste » : son nom, son statut et à qui il est (ceux que la liste sert), un texte. */
export function itemDrawerBody(list: Listing, errors: Record<string, string> = {}): string {
  const statuses = [...list.open, ...list.closed].map((x) => [x.code, x.label] as const);
  const actors = (list.actors ?? []).map((x) => [x.code, x.label] as const);
  return `${F.text("title", "Nom", "", { required: true, error: errors.title })}
    ${F.two(statuses.length ? F.select("status", "Statut", statuses[0][0], statuses, { error: errors.status }) : "", actors.length ? F.select("actor", "À la charge de", list.actor, actors, { error: errors.actor }) : "")}
    ${F.long("text", "Ce qu'il faut en savoir", "", { rows: 3, error: errors.text })}`;
}

// ── Modifier le projet ───────────────────────────────────────────────

const SECTION_ICON: Record<string, IconName> = { general: "flag", rythme: "clock", accords: "shield-check", depot: "code", outils: "tools" };

export function settingsView(sheet: Sheet, got: Got<Settings>, rest: string[], typed: Values, ctx: Ctx): string {
  const p = sheet.project;
  const f = (...x: string[]): string => sheetRoute(p.id, "reglages", ...x);
  const s = got.value;
  if (!s) return waitingBlock(got, "Impossible de lire ses réglages");
  const section = s.sections.find((x) => x.name === rest[0]) ?? s.sections[0];
  if (!section) return empty("settings", "Rien à régler", s.why || "Ce projet n'a pas de réglage ouvert d'ici.");
  const key = `settings:${p.id}:${section.name}`;
  const list = `<div class="pane-head"><h2>Ce qui se règle</h2></div><div class="pane-scroll" data-scroll="reglages">${s.sections
    .map((x) => `<a class="li p2-row" href="${f(x.name)}" aria-selected="${x === section}"${x.can === false && x.why ? ` title="${h(x.why)}"` : ""}>${tile(SECTION_ICON[x.name] ?? "settings")}<span class="li-main"><span class="li-title">${h(x.title)}</span><span class="p2-row-sub">${s.can && x.can === false ? ico("lock", "xs") : ""}<span class="ellipsis">${h(x.summary)}</span></span></span></a>`)
    .join("")}</div>`;
  const values: Values = { ...Object.fromEntries(section.fields.map((x) => [x.name, x.value])), ...typed };
  const body = section.fields.length
    ? form({ name: "settings", key, data: { p: p.id, s: section.name }, title: section.title, sub: section.summary, cancel: sheetRoute(p.id), error: refusalAt(ctx.ui, key),
        // rien ne s'enregistre d'ici : son cadre n'est pas à elle, ou aucun champ de cette section ne se change (la raison est celle du serveur)
        locked: !s.can ? s.why || "Tu ne peux pas changer son cadre." : section.can === false ? section.why || "Aucun réglage de cette section ne se change d'ici." : "",
        bodyHtml: section.fields.map((x) => served(x.name === "title" && !s.renamable ? { ...x, can: false, why: x.why || "Un projet qu'elle a ouvert d'elle-même ne se renomme pas." } : x, values, fieldErrorsAt(ctx.ui, key), !s.can)).join("") })
    : nothing(SECTION_ICON[section.name] ?? "settings", section.title, section.summary || "Rien à régler ici.");
  const paused = p.status === "paused";
  return trio({
    list, open: !!rest[0], back: [f(), "Modifier le projet"], panes: [[section.name, section.title]], active: section.name, link: (k) => f(k), scroll: `reglages-${p.id}-${section.name}`, body, infos: ctx.ui.infos,
    head: head({ tileHtml: tile("settings"), over: "Modifier le projet", title: p.title, metaHtml: `${projectState(p)}<span>${h(forWhom(p))}</span>`, rightHtml: `<a class="btn" href="${sheetRoute(p.id)}">${ico("x", "sm")}Fermer</a>` }),
    side: sc("En bref", props(s.sections.map((x): [string, string] => [h(x.title), h(x.summary)])))
      + sc("Le projet", `${refusal(refusalAt(ctx.ui, `project:${p.id}`))}<div class="p2-decide">${sheet.rights.pilot ? `<button class="btn" type="button" data-p2="${paused ? "resume" : "pause"}" data-p="${p.id}">${ico(paused ? "play" : "pause", "sm")}${paused ? "Reprendre le projet" : "Mettre en pause"}</button>` : ""}
          ${s.archive.can ? `<button class="btn" type="button" data-p2="projectArchive" data-p="${p.id}">${ico("archive", "sm")}Archiver le projet</button>` : ""}</div>
          ${hint(s.archive.can ? "Archivé, un projet ne travaille plus et ne te demande plus rien ; rien n'est effacé, et il se désarchive depuis la grille des projets." : s.archive.why, s.archive.can ? "info" : "lock")}`, "", "bas"),
  });
}

/** Combien de choses un lien donne, en mots (« 3 choses données sur 4 »). */
export function givenWords(g: Gives): string {
  return `${givenCount(g)} choses données sur ${GIVEN.length}`;
}
