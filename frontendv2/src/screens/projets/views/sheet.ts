/**
 * Projets (pur) : la barre de titre de l'écran, la grille des projets, la tête d'une fiche et ses onglets, et la « Vue
 * d'ensemble » — une grille de cartes, sans rien d'imbriqué. Les boutons ne paraissent qu'avec le droit servi
 * (`rights`, `create`).
 */
import type { Archived, Instruction, Linked, Listing, NextPass, Objective, Overview, ProjectHead, Sheet } from "../../../api/projects";
import { mikaAvatar } from "../../../mika/face";
import { ofName } from "../../../shared/names";
import { h } from "../../../shell/dom";
import { ico, type IconName } from "../../../shell/icons";
import { forWhom, plural } from "../gestures";
import { bar, empty, logo, OUTSIDE, st, tile } from "../parts";
import { route, SHEET_TABS, sheetRoute, waitingRoute, type Place, type SheetTab } from "../routes";
import { followLists, liveMilestones, ticketList } from "../state";
import { moment, when } from "../time";
import { checksTone, milestoneTone, objectiveTone, progressTone, projectTone, pullTone, waitingIcon } from "../tones";
import type { Ctx } from "./todo";

/** Les couleurs des jalons d'un objectif, pour sa barre ; sans jalon, celle de son état. */
export function milestoneTones(o: Objective): string[] {
  const live = liveMilestones(o);
  return live.length ? live.map((m) => milestoneTone(m)) : [objectiveTone(o.status)];
}

export function reachedCount(o: Objective): number {
  return liveMilestones(o).filter((m) => m.status === "reached").length;
}

/** Le plan d'un projet quand il attend quelque chose (proposé, à cadrer) : sa pastille, avec le mot du serveur. */
function planState(p: ProjectHead): string {
  return p.plan === "proposed" || p.plan === "to_frame" ? st(p.plan === "proposed" && p.waiting ? "you" : "wait", `plan ${p.plan_label}`) : "";
}

/** L'état d'un projet : son statut, et son plan quand il attend quelque chose. */
export function projectState(p: ProjectHead): string {
  return st(projectTone(p.status), p.status_label) + planState(p);
}

/** Les onglets d'une fiche : ceux que le serveur ouvre ; « Listes » seulement pour un projet qui a une liste. */
export function sheetTabs(sheet: Sheet): Array<[SheetTab, string]> {
  if (!sheet.rights.detail) return [["vue", "Vue d'ensemble"]];
  return SHEET_TABS.filter(([k]) => (k !== "listes" || followLists(sheet).length > 0) && (k !== "activite" || sheet.rights.work !== false)).map(([k, l]) => [k, l]);
}

/** La barre de titre hors d'une fiche : « À faire » et « Projets », et « Nouveau projet » si elle peut en confier un. */
export function screenHead(overview: Overview | null, place: Place): string {
  const tab = (href: string, label: string, on: boolean, n: number | null): string => `<a href="${href}"${on ? ' aria-current="page"' : ""}>${label}${n === null ? "" : `<span class="cnt">${n}</span>`}</a>`;
  return `<header class="page-head"><div class="ph-title"><h1>Projets</h1></div><nav class="subtabs" aria-label="Onglets">
      ${tab(route("a-faire"), "À faire", place.kind === "todo", overview ? overview.todo_total : null)}${tab(route("projets"), "Projets", place.kind !== "todo", overview ? overview.projects.length : null)}</nav>
    <div class="ph-actions">${overview?.create?.can ? `<button class="btn sm primary" type="button" data-p2="projectNew">${ico("plus", "sm")}<span class="lbl">Nouveau projet</span></button>` : ""}</div></header>`;
}

/** Pour qui est un projet, et par qui il est mené (`led_by` : son nom à elle, servi avec le détail). */
export function whose(p: Pick<ProjectHead, "mine" | "hers" | "owner_name">, ledBy = ""): string {
  return `${forWhom(p)}${ledBy ? ` · menée par ${ledBy}` : ""}`;
}

/** Son prochain passage, en une ligne : quand (daté par le moteur, jamais estimé), sinon ce que le serveur en dit. */
export function nextWhen(next: NextPass, now: number): string {
  return next.state === "due" && next.at ? moment(next.at, now) : next.state_label;
}

/** Sur quoi portera son prochain passage : sa sorte, et l'objectif s'il en vise un. */
export function nextAbout(next: NextPass): string {
  return [next.sort_label, next.objective?.text ?? ""].filter(Boolean).join(" · ");
}

/** Une consigne en attente : ses mots (ou qu'elle ne s'entend pas d'ici), et qui l'a donnée. */
export function instructionLine(c: Instruction, now: number): string {
  const who = c.author_kind === "you" ? "Ta consigne" : `Consigne ${ofName(c.author)}`;
  return `<p class="p2-consigne">${ico(c.veiled ? "lock" : "pen", "xs")}<span>${h(who)} : ${c.veiled ? h(c.text) : `« ${h(c.text)} »`}</span><time>${h(when(c.at, now))}</time></p>`;
}

/** La tête d'une fiche : le fil d'Ariane, le titre, l'état, pour qui ; à droite, piloter et « Modifier le projet ». */
export function sheetHead(sheet: Sheet, tab: SheetTab, ledBy = ""): string {
  const p = sheet.project;
  const r = sheet.rights;
  const paused = p.status === "paused";
  const settings = tab === "reglages";
  const counts: Record<string, number> = {
    objectifs: (sheet.objectives ?? []).filter((o) => o.status !== "done").length,
    tickets: ticketList(sheet)?.living ?? 0,
  };
  const pilot = r.pilot
    ? `<button class="btn sm" type="button" data-p2="instruct" data-p="${p.id}">${ico("pen", "sm")}<span class="lbl">Donner une consigne</span></button>
       <button class="btn sm" type="button" data-p2="runNow" data-p="${p.id}">${ico("play", "sm")}<span class="lbl">Lancer maintenant</span></button>
       <button class="btn sm" type="button" data-p2="${paused ? "resume" : "pause"}" data-p="${p.id}">${ico(paused ? "play" : "pause", "sm")}<span class="lbl">${paused ? "Reprendre" : "Mettre en pause"}</span></button>`
    : "";
  const frame = r.frame
    ? `<a class="btn sm${settings ? " on" : ""}" href="${settings ? sheetRoute(p.id) : sheetRoute(p.id, "reglages")}"${settings ? ' aria-current="page"' : ""}>${ico("settings", "sm")}<span class="lbl">Modifier le projet</span></a>
       <button class="btn sm icon" type="button" data-p2="projectMenu" data-p="${p.id}" title="Archiver">${ico("more", "sm")}</button>`
    : "";
  return `<header class="page-head p2-fhead"><a class="p2-crumb" href="${route("projets")}" title="Tous les projets">${ico("chev-left", "sm")}<span>Projets</span></a>
      <div class="ph-title"><h1>${h(p.title)}</h1></div>${projectState(p)}
      <span class="p2-who">${h(whose(p, ledBy))}${r.detail ? "" : " · ouvert à toi pour le voir"}</span>
      <div class="ph-actions">${pilot}${frame}</div></header>
    <nav class="p2-tabs" aria-label="Onglets du projet">${sheetTabs(sheet)
      .map(([k, label]) => `<a href="${sheetRoute(p.id, k)}"${tab === k ? ' aria-current="page"' : ""}>${label}${counts[k] ? `<span class="cnt">${counts[k]}</span>` : ""}</a>`)
      .join("")}</nav>`;
}

// ── La grille ────────────────────────────────────────────────────────

/** Une carte : ce que la liste sert (`card`, pour qui lit son détail) — ses objectifs en une barre, ses compteurs, ses liens. */
function card(p: ProjectHead, ctx: Ctx): string {
  const c = p.card ?? null;
  const named = (x: Linked): string => (x.visible ? x.title : "un projet que tu ne vois pas");
  const deps = c ? [...c.reads.map((x) => `dépend de ${named(x)}`), ...c.readers.map((x) => `${named(x)} en dépend`)] : [];
  const last = c?.last_activity || p.last_run;
  return `<a class="p2-pcard" href="${sheetRoute(p.id)}"><div class="p2-pcard-top">${logo(p.id, p.title)}<div class="grow"><h3>${h(p.title)}</h3>
        <span class="p2-who">${h(whose(p, c?.led_by))}${p.detail ? "" : " · à voir seulement"}</span></div>${planState(p) || st(projectTone(p.status), p.status_label)}</div>
      <p class="p2-pcard-ou">${h(p.where || (p.detail ? "Elle n'y a pas encore travaillé." : "Ce projet ne t'est ouvert qu'à voir."))}</p>
      ${c ? `<div class="p2-prog">${bar(c.objectives.states.length ? c.objectives.states.map((s) => progressTone(s.state)) : ["wait"])}<span>${c.objectives.done} / ${plural(c.objectives.total, "objectif", "objectifs")}</span></div>` : ""}
      <div class="p2-counts">${c ? `<span><b>${c.pulls_open}</b>pull requests</span><span><b>${c.tickets_open}</b>tickets ouverts</span>` : ""}<span class="${p.waiting ? "you" : ""}"><b>${p.waiting}</b>à toi</span></div>
      <div class="p2-pcard-foot">${last ? `<span>${ico("clock", "xs")}${h(when(last, ctx.now))}</span>` : ""}${deps.map((x) => `<span>${ico("link", "xs")}${h(x)}</span>`).join("")}</div></a>`;
}

export function gridView(overview: Overview, archived: readonly Archived[], ctx: Ctx): string {
  const old = archived
    .map((a) => `<div class="p2-pcard archive"><div class="p2-pcard-top">${logo(a.id, a.title)}<div class="grow"><h3>${h(a.title)}</h3><span class="p2-who">${a.owner_name ? `de ${h(a.owner_name)}` : "archivé"}</span></div>${st("wait", "archivé")}</div>
        <p class="p2-pcard-ou">Archivé ${h(when(a.archived_at, ctx.now))} : elle n'y travaille plus, rien n'est effacé.</p>
        <div class="p2-pcard-foot"><button class="btn sm" type="button" data-p2="projectRestore" data-p="${a.id}">${ico("archive", "sm")}Désarchiver</button></div></div>`)
    .join("");
  const fresh = overview.create?.can
    ? `<button class="p2-pcard p2-pnew" type="button" data-p2="projectNew">${ico("plus", "lg")}<b>Nouveau projet</b><span>Dis-lui ce que tu veux : elle te propose un plan.</span></button>`
    : "";
  if (!overview.projects.length && !old && !fresh) return empty("flag", "Aucun projet", overview.create?.why || "Aucun projet ne t'est ouvert pour l'instant.");
  return `<div class="fill-scroll" data-scroll="grille"><div class="p2-pgrid">${overview.projects.map((p) => card(p, ctx)).join("")}${old}${fresh}</div></div>`;
}

// ── La Vue d'ensemble ────────────────────────────────────────────────

function cardHead(icon: IconName, title: string, link?: [string, string] | null, moreHtml = ""): string {
  return `<header class="p2-card-h">${ico(icon)}<h3>${h(title)}</h3>${moreHtml}${link ? `<a href="${link[0]}">${h(link[1])}${ico("chev-right", "xs")}</a>` : ""}</header>`;
}

/** La répartition des tickets par étape du parcours, en une barre : les six étapes, comptées et nommées par le serveur (`journey`). */
function ticketStages(list: Listing): string {
  const stages = (list.journey ?? []).map((s, i) => ({ ...s, i }));
  if (!list.total || !stages.length) return '<p class="p2-none">Aucun ticket pour l\'instant.</p>';
  return `<div class="p2-stack">${stages.filter((s) => s.count).map((s) => `<i class="e${s.i % 6}" style="flex:${s.count}" title="${h(s.label)} : ${s.count}"></i>`).join("")}</div>
    <ul class="p2-legend">${stages.map((s) => `<li class="${s.count ? "" : "zero"}"><i class="e${s.i % 6}"></i>${h(s.label)}<b>${s.count}</b></li>`).join("")}</ul>`;
}

export function overviewView(sheet: Sheet, ctx: Ctx): string {
  const p = sheet.project;
  const f = (...x: Array<string | number>): string => sheetRoute(p.id, ...x);
  const mine = sheet.todo.filter((w) => w.mine);
  const theirs = sheet.todo.filter((w) => !w.mine);
  const yours = `<section class="p2-card p2-atoi${mine.length ? "" : " rien"}">${cardHead("inbox", "À toi", mine.length ? [route("a-faire"), "Tout voir"] : null)}
      <div class="p2-big"><b>${mine.length}</b><span>${mine.length > 1 ? "choses t'attendent" : mine.length ? "chose t'attend" : "rien ne t'attend"}</span></div>
      ${mine.slice(0, 3).map((w) => `<a class="p2-mini" href="${waitingRoute(w)}">${tile(waitingIcon(w.kind, w.what), "you")}<span><b>${h(w.about)}</b><small>${h(w.kind_label)} · ${h(when(w.since, ctx.now))}</small></span></a>`).join("")}
      ${mine.length > 3 ? `<a class="p2-more" href="${route("a-faire")}" data-p2="todoFilter" data-c="${p.id}" data-va="1">et ${mine.length - 3} de plus</a>` : ""}
      ${theirs.length ? `<p class="p2-consigne plain">${ico("clock", "xs")}<span>${plural(theirs.length, "chose attend", "choses attendent")} quelqu'un d'autre${theirs[0].waits_for ? ` (${h(theirs[0].waits_for)})` : ""}.</span></p>` : ""}</section>`;
  if (!sheet.rights.detail) {
    return `<div class="fill-scroll" data-scroll="vue-${p.id}"><div class="p2-grid"><div class="p2-gcol"><section class="p2-card p2-ou">${cardHead("lock", "Ouvert à toi pour le voir")}
        <p>${h(p.description || "Tu vois son titre et son état.")}</p><small>Son détail — ses objectifs, ses tickets, son code — demande de le piloter au moins en lecture.</small></section></div><div class="p2-gcol">${yours}</div></div></div>`;
  }
  const objectives = sheet.objectives ?? [];
  const shown = [...objectives.filter((o) => o.status !== "done"), ...objectives.filter((o) => o.status === "done")].slice(0, 4);
  const pulls = objectives.filter((o) => o.pull && o.pull.state === "open");
  const tickets = ticketList(sheet);
  const links = sheet.links;
  const named = (x: { project: number | null; title: string; visible: boolean }, side: string): string => (x.visible && x.project !== null ? `<a href="${f("dependances", `${side}-${x.project}`)}">${h(x.title)}</a>` : "<span>un projet que tu ne vois pas</span>");
  const missions = sheet.missions ?? [];
  const next = sheet.next;
  const commit = sheet.repo?.commit ?? null;
  return `<div class="fill-scroll" data-scroll="vue-${p.id}"><div class="p2-grid"><div class="p2-gcol">
      <section class="p2-card p2-ou"><header class="p2-card-h">${mikaAvatar("sm")}<h3>Où il en est</h3><span class="p2-age">${h(when(p.last_run, ctx.now))}</span></header><p>${h(p.where || "Elle n'y a pas encore travaillé.")}</p>${p.description ? `<small>${h(p.description)}</small>` : ""}</section>
      <div class="p2-gpair"><section class="p2-card">${cardHead("p2-target", "Objectifs", [f("objectifs"), `${objectives.filter((o) => o.status === "done").length} sur ${objectives.length} terminés`])}
        ${shown.length
          ? shown.map((o) => `<a class="p2-mini col" href="${f("objectifs", `o${o.id}`)}"><span class="p2-mini-top"><b>${h(o.text)}</b>${st(objectiveTone(o.status), o.status_label)}</span>
              <span class="p2-prog">${bar(milestoneTones(o))}<span>${liveMilestones(o).length ? `${reachedCount(o)} / ${plural(liveMilestones(o).length, "jalon", "jalons")}` : "pas de jalon"}</span></span></a>`).join("")
          : `<p class="p2-none">Pas encore d'objectif.</p>${sheet.rights.edit ? `<button class="btn sm" type="button" data-p2="goalAdd" data-p="${p.id}">${ico("plus", "sm")}Ajouter un objectif</button>` : ""}`}</section>
      <section class="p2-card">${cardHead("code", "Code", [f("code", "pulls"), "Pull requests"])}
        ${pulls.map((o) => `<a class="p2-mini" href="${f("code", "pulls", o.pull!.number)}">${tile("p2-pr", pullTone(o.pull!.state))}<span><b>${h(o.pull!.title || o.text)}</b><small>n° ${o.pull!.number} · ${h(when(o.pull!.at, ctx.now))}</small></span>${st(o.checks ? checksTone(o.checks.state) : pullTone(o.pull!.state), o.pull!.state_label)}</a>`).join("") || '<p class="p2-none">Aucune pull request ouverte.</p>'}
        ${commit ? `<a class="p2-lastc" href="${f("code", "commits", commit.short)}"${commit.outside ? ` title="${OUTSIDE}"` : ""}>${ico("p2-commit", "sm")}<code>${h(commit.short)}</code><span class="ellipsis">${h(commit.title)}</span>${commit.at ? `<time>${h(when(commit.at, ctx.now))}</time>` : ""}</a>`
          : sheet.repo?.last_commit ? `<a class="p2-lastc" href="${f("code", "commits", sheet.repo.last_commit.slice(0, 7))}">${ico("p2-commit", "sm")}<code>${h(sheet.repo.last_commit.slice(0, 7))}</code><span class="ellipsis">${h(sheet.repo.branch)} · ${h(sheet.repo.flow_label)}</span></a>` : ""}</section></div>
      <div class="p2-gpair"><section class="p2-card">${cardHead("p2-ticket", "Tickets", [f("tickets"), `${tickets?.living ?? 0} ouverts`])}${tickets ? ticketStages(tickets) : '<p class="p2-none">Aucun ticket pour l\'instant.</p>'}</section>
      <section class="p2-card">${cardHead("link", links?.labels?.title || "Dépendances", [f("dependances"), "Le schéma"])}
        ${links && (links.reads.length || links.readers.length)
          ? `<dl class="p2-deps"><div><dt>${h(links.labels?.reads || "Il dépend de")}</dt><dd>${links.reads.map((x) => named(x, "lit")).join("") || "<span>aucun projet</span>"}</dd></div>
              <div><dt>${h(links.labels?.readers || "Dépendent de lui")}</dt><dd>${links.readers.map((x) => named(x, "luPar")).join("") || "<span>aucun projet</span>"}</dd></div></dl>`
          : '<p class="p2-none">Ce projet ne dépend d\'aucun autre, et aucun ne dépend de lui.</p>'}</section></div></div><div class="p2-gcol">${yours}
      <section class="p2-card">${cardHead("clock", "Prochain passage", sheet.rights.work !== false ? [f("activite"), "Activité"] : null)}
        <div class="p2-next"><b>${h(next ? nextWhen(next, ctx.now) : p.status_label)}</b><span>${h((next && nextAbout(next)) || (p.last_run ? `dernier passage ${when(p.last_run, ctx.now)}` : "pas encore de passage"))}</span></div>
        ${sheet.rhythm?.summary ? `<p class="p2-consigne plain">${ico("calendar", "xs")}<span>${h(sheet.rhythm.summary)}</span>${sheet.rights.frame ? `<a href="${f("reglages", "rythme")}">Régler</a>` : ""}</p>` : ""}
        ${(sheet.instructions ?? []).map((c) => instructionLine(c, ctx.now)).join("")}
        ${missions.map((m) => `<a class="p2-mini" href="${f("objectifs", `m${m.id}`)}">${tile("refresh")}<span><b>${h(m.text)}</b><small>${h([m.cadence_label, ...m.on.map((x) => x.label)].filter(Boolean).join(" · "))}</small></span></a>`).join("")}</section>
    </div></div></div>`;
}
