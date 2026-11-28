/**
 * Le diagramme de l'onglet Objectifs (pur) : une ligne par objectif et par mission, et sous chacun, en retrait, une
 * ligne par jalon ; les noms à gauche, les barres à droite, et dans le panneau latéral ce qu'on a choisi, avec ses
 * gestes. Deux modes : « Avancement » (les barres partent du même bord) et « Dans le temps » (un axe en jours ou en
 * semaines, un trait pour aujourd'hui, une flèche d'un objectif à celui qui en dépend). Les calculs : `diagram.ts`.
 */
import type { Diagram, DiagramMilestone, DiagramObjective, Sheet } from "../../../api/projects";
import { h } from "../../../shell/dom";
import { ico } from "../../../shell/icons";
import { arrowPath, goalSegments, milestonePart, milestoneTone, pickZoom, rows, timeLayout, type Row, type TimeLayout } from "../diagram";
import { plural } from "../gestures";
import { empty, hint, linked, props, sc, st, tile, trio } from "../parts";
import { sheetRoute } from "../routes";
import { findGoal, type Goal } from "../state";
import { axisDay, clock, moment, shortDate, when } from "../time";
import { milestoneIcon, objectiveTone } from "../tones";
import { checkpointButtons, goalSide, modeSwitch, proofBlock, verified } from "./objectives";
import type { Ctx } from "./todo";

const runsWord = (n: number): string => plural(Math.max(1, n), "exécution", "exécutions");
const keyOf = (o: DiagramObjective): string => `${o.kind === "constant" ? "m" : "o"}${o.id}`;

/** Le mot au bout de la barre d'un jalon : quand il a été atteint, ce qu'il attend, ce qu'il a pris ; sinon son état servi. */
function milestoneWord(m: DiagramMilestone): string {
  if (m.status === "reached") return m.reached_at ? `atteint le ${shortDate(m.reached_at)}` : m.status_label;
  if (m.ready) return "attend ta validation";
  return m.started_at ? runsWord(m.runs) : m.status_label;
}

function goalWord(o: DiagramObjective): string {
  const base = o.milestones_total ? `${o.reached} / ${plural(o.milestones_total, "jalon atteint", "jalons atteints")}` : o.status === "done" && o.closed_at ? `${o.status_label} le ${shortDate(o.closed_at)}` : o.status_label;
  return `${base}${o.runs ? ` · ${runsWord(o.runs)}` : ""}`;
}

function name(project: number, r: Row, mode: string, pick: { o: DiagramObjective | null; m: DiagramMilestone | null }): [href: string, on: boolean, html: string] {
  const f = (...x: Array<string | number>): string => sheetRoute(project, "objectifs", "diagramme", mode, ...x);
  if (r.sort === "milestone") {
    return [f(keyOf(r.o), r.m.id), pick.o === r.o && pick.m === r.m, `<i class="p2-g-pt ${milestoneTone(r.m)}"></i><span class="p2-g-t">${h(r.m.text)}</span>`];
  }
  if (r.sort === "mission") {
    return [f(keyOf(r.o)), pick.o === r.o, `<span class="p2-g-pli"></span>${tile("refresh", "work")}<span class="p2-g-t"><b>${h(r.o.text)}</b><small>mission · ${h(r.o.status_label)}</small></span>`];
  }
  return [f(keyOf(r.o)), pick.o === r.o && !pick.m,
    `<span class="p2-g-pli" role="button" data-p2="ganttFold" data-c="${r.o.id}" title="${r.folded ? "Déplier ses jalons" : "Replier ses jalons"}">${r.o.milestones.length ? ico(r.folded ? "chev-right" : "chev-down", "xs") : ""}</span>
      ${tile("p2-target", objectiveTone(r.o.status))}<span class="p2-g-t"><b>${h(r.o.text)}</b><small>n° ${r.o.id} · ${h(r.o.status_label)}</small></span>`];
}

/** « Avancement » : la part faite, et un mot au bout. */
function progress(r: Row, ctx: Ctx): string {
  if (r.sort === "milestone") {
    const tone = milestoneTone(r.m);
    const part = milestonePart(r.m);
    return `<span class="p2-g-av${part ? "" : " vide"}"><i class="${tone}${r.m.ready ? " hache" : ""}" style="width:${part * 100}%"></i></span><span class="p2-g-mot ${r.m.ready ? "you" : ""}">${r.m.ready ? `${ico("p2-stop", "xs")}à toi · ` : ""}${h(milestoneWord(r.m))}</span>`;
  }
  if (r.sort === "mission") {
    const n = Math.min(12, r.o.passes.length || Math.min(12, r.o.runs));
    return `<span class="p2-g-av mission">${Array.from({ length: n }, () => "<i></i>").join("")}</span><span class="p2-g-mot">${plural(r.o.runs, "passage", "passages")}${r.o.last_run ? ` · le dernier ${h(when(r.o.last_run, ctx.now))}` : ""}</span>`;
  }
  return `<span class="p2-g-av obj">${goalSegments(r.o).map((s) => `<i class="${s.tone}${s.tone === "you" ? " hache" : ""}" style="width:${s.part * 100}%"></i>`).join("")}</span><span class="p2-g-mot">${h(goalWord(r.o))}</span>`;
}

/** « Dans le temps » : les barres d'une ligne, et son mot — posé après sa barre, retenu au bord quand elle a défilé. */
function track(r: Row, i: number, t: TimeLayout): string {
  const tr = t.tracks[i];
  const title = r.sort === "milestone" ? `${r.m.text} — ${milestoneWord(r.m)}` : r.o.text;
  const bars = tr.bars.map((b) => `<span class="p2-g-b ${b.cls}" style="left:${b.left}px;width:${b.width}px" title="${h(/fantome/.test(b.cls) ? `${title} — pas commencé : sans date` : title)}"></span>`).join("");
  if (r.sort === "mission") {
    return `<span class="p2-g-fil" style="left:0;width:${tr.line ?? 0}px"></span>${(tr.passes ?? []).map((p) => `<i class="p2-g-pass" style="left:${p.x}px" title="Passage du ${shortDate(p.at)} à ${clock(p.at)}"></i>`).join("")}
      <span class="p2-g-mot" style="margin-left:${tr.label}px">${plural(r.o.runs, "passage", "passages")}</span>`;
  }
  const word = r.sort === "milestone" ? milestoneWord(r.m) : r.o.status === "done" && r.o.closed_at ? `${r.o.status_label} le ${shortDate(r.o.closed_at)}` : "";
  const you = r.sort === "milestone" && r.m.ready;
  return bars + (tr.label >= 0 && word ? `<span class="p2-g-mot ${you ? "you" : ""}" style="margin-left:${tr.label}px">${h(word)}</span>` : "");
}

function axis(t: TimeLayout, zoom: "days" | "weeks"): string {
  const last = t.days.length - 1;
  const marks = t.days
    .map((day, i) => {
      const a = axisDay(day.at);
      if (zoom === "weeks") return a.monday ? `<span class="sem" style="left:${day.x}px">sem. du ${a.n} ${a.month}</span>` : "";
      // resserré, l'axe ne nomme qu'un jour sur deux : aujourd'hui et le premier toujours
      if (t.day < 84 && i !== last && i !== 0 && i % 2) return "";
      return `<span class="${i === last ? "auj" : ""}${a.weekend ? " we" : ""}" style="left:${day.x}px;width:${t.day}px"><b>${a.n}</b>${t.day < 84 ? "" : a.day}${a.n === 1 || i === 0 ? ` <em>${a.month}</em>` : ""}</span>`;
    })
    .join("");
  return `${marks}<span class="suite" style="left:${t.today + 14}px">à suivre · sans date</span>`;
}

function layers(t: TimeLayout, height: number): { under: string; over: string } {
  const under = `<svg class="p2-g-fond" width="${t.width}" height="${height}" aria-hidden="true">${t.days
    .map((day) => {
      const a = axisDay(day.at);
      return `${a.weekend ? `<rect class="we" x="${day.x}" y="0" width="${Math.max(0, Math.min(t.day, t.today - day.x))}" height="${height}"/>` : ""}<line class="${a.monday ? "lundi" : ""}" x1="${day.x + 0.5}" y1="0" x2="${day.x + 0.5}" y2="${height}"/>`;
    })
    .join("")}<rect class="suite" x="${t.today}" y="0" width="${Math.max(0, t.width - t.today)}" height="${height}"/></svg>`;
  const arrows = t.arrows.map((a) => { const p = arrowPath(a); return `<path d="${p.line}"/><path class="tete" d="${p.head}"/>`; }).join("");
  return { under, over: `<svg class="p2-g-sur" width="${t.width}" height="${height}" aria-hidden="true">${arrows}<line class="auj" x1="${t.today + 0.5}" y1="0" x2="${t.today + 0.5}" y2="${height}"/></svg>` };
}

/** Le panneau de ce qu'on a choisi : un objectif, un jalon, une mission, avec ses gestes (ceux de la fiche). */
function panel(sheet: Sheet, d: Diagram, pick: { o: DiagramObjective | null; m: DiagramMilestone | null }, mode: string, ctx: Ctx): string {
  const id = sheet.project.id;
  if (!pick.o) {
    return sc("Rien à montrer", `<p class="p2-sc-text">Ce projet n'a pas encore d'objectif.</p>${sheet.rights.edit ? `<div class="p2-decide"><button class="btn primary" type="button" data-p2="goalAdd" data-p="${id}">${ico("plus", "sm")}Ajouter un objectif</button></div>` : ""}`);
  }
  const o = pick.o;
  const g: Goal | null = findGoal(sheet, keyOf(o));
  const tone = objectiveTone(o.status);
  if (pick.m) {
    const m = pick.m;
    const mt = milestoneTone(m);
    const full = g && !g.mission ? g.o.milestones.find((x) => x.id === m.id) : undefined;
    const dset = `data-p="${id}" data-o="${o.id}" data-c="${m.id}"`;
    const manage = (full?.can?.modify ? `<button class="btn" type="button" data-p2="milestoneEdit" ${dset}>${ico("pen", "sm")}Modifier le jalon</button>` : "") + (full?.can?.drop ? `<button class="btn danger" type="button" data-p2="milestoneDrop" ${dset}>${ico("trash", "sm")}Retirer le jalon</button>` : "");
    return sc(null, `<div class="p2-side-h">${tile(milestoneIcon(mt), mt)}<span><b>${h(m.text)}</b><small>jalon de l'objectif n° ${o.id}</small></span>${st(mt, m.status_label)}</div>
        ${m.ready && sheet.rights.settle ? `<div class="p2-decide">${checkpointButtons(id, o.id, m.id, "lg")}</div>${hint("Un point d'arrêt : elle attend que tu le valides pour continuer.")}` : ""}`)
      + sc("Comment on le vérifie", `<p class="p2-sc-text">${full ? verified(full, id) : `Vérifié par ${h(m.check_label)}`}</p>${full ? proofBlock(full) : ""}`)
      + sc("Dans le temps", props([["Elle s'y est mise", m.started_at ? `le ${shortDate(m.started_at)} à ${clock(m.started_at)}` : '<span class="muted">pas encore : sans date</span>'],
        m.status === "reached" && m.reached_at ? ["Atteint", `le ${shortDate(m.reached_at)} à ${clock(m.reached_at)}`] : m.ready && m.ready_at ? ["Prêt depuis", h(moment(m.ready_at, ctx.now))] : null, m.started_at ? ["Elle y a passé", runsWord(m.runs)] : null]))
      + sc("Son objectif", linked(sheetRoute(id, "objectifs", "diagramme", mode, keyOf(o)), "p2-target", tone, o.text, `objectif n° ${o.id}`, st(tone, o.status_label)))
      + (manage ? sc("Gérer", `<div class="p2-decide">${manage}</div>`, "", "bas") : "");
  }
  const mission = o.kind === "constant";
  const f = (...x: string[]): string => sheetRoute(id, "objectifs", keyOf(o), ...x);
  const before = !mission && o.after ? d.objectives.find((x) => x.id === o.after) : undefined;
  return sc(null, `<div class="p2-side-h">${tile(mission ? "refresh" : "p2-target", mission ? "work" : tone)}<span><b>${h(o.text)}</b><small>${mission ? "mission" : `objectif n° ${o.id}`}</small></span>${st(mission ? "work" : tone, o.status_label)}</div>
      <div class="p2-decide row"><a class="btn" href="${f()}">${ico("expand", "sm")}L'ouvrir</a>${g?.o.can?.modify ? `<a class="btn" href="${f("modifier")}">${ico("pen", "sm")}Modifier</a>` : ""}</div>
      ${g && !g.mission && g.o.can?.milestone ? `<div class="p2-decide"><button class="btn" type="button" data-p2="milestoneAdd" data-p="${id}" data-o="${o.id}">${ico("plus", "sm")}Ajouter un jalon</button></div>` : ""}`)
    + (before ? sc("Il dépend de", linked(sheetRoute(id, "objectifs", "diagramme", mode, keyOf(before)), "p2-target", objectiveTone(before.status), before.text, `objectif n° ${before.id} : sa suite attend qu'il soit fini`, st(objectiveTone(before.status), before.status_label))) : "")
    + (g ? goalSide(sheet, g, ctx) : "");
}

export function diagramView(sheet: Sheet, d: Diagram, rest: string[], ctx: Ctx): string {
  const id = sheet.project.id;
  const mode = rest[0] === "temps" ? "temps" : "avancement";
  const o = d.objectives.find((x) => keyOf(x) === rest[1]) ?? (ctx.mobile ? null : (d.objectives.find((x) => x.kind !== "constant" && x.status !== "done") ?? d.objectives[0] ?? null));
  const pick = { o, m: o && o.kind !== "constant" && rest[2] ? (o.milestones.find((m) => String(m.id) === rest[2]) ?? null) : null };
  const { rows: list, height } = rows(d, ctx.ui.folded);
  const zoom = ctx.ui.zoom ?? pickZoom(d, ctx.ui.trackWidth);
  const t = mode === "temps" ? timeLayout(d, list, { zoom, width: ctx.ui.trackWidth }) : null;
  const f = (...x: string[]): string => sheetRoute(id, "objectifs", "diagramme", ...x);
  const after = rest.slice(1).filter(Boolean);
  const lines = list
    .map((r, i) => {
      const [href, on, html] = name(id, r, mode, pick);
      return `<a class="p2-g-row ${r.sort === "goal" ? "obj" : r.sort === "milestone" ? "jalon" : "mission"}" href="${href}" data-p2="ganttPick" data-va="1" aria-selected="${on}" style="height:${r.height}px"><span class="p2-g-nom">${html}</span><span class="p2-g-piste">${t ? track(r, i, t) : progress(r, ctx)}</span></a>`;
    })
    .join("");
  const legend = `<span class="p2-g-leg">${([["done", "atteint"], ["work", "en cours"], ["you", "à toi"], ["fail", "bloqué"], ["wait", "à venir"]] as const).map(([k, l]) => `<span><i class="${k}"></i>${l}</span>`).join("")}${t ? '<span><i class="fantome"></i>pas commencé, sans date</span>' : ""}</span>`;
  const top = `<div class="pane-head p2-g-bar">${modeSwitch(id, "diagramme")}<div class="seg p2-mode"><a href="${f("avancement", ...after)}" aria-pressed="${mode === "avancement"}">Avancement</a><a href="${f("temps", ...after)}" aria-pressed="${mode === "temps"}">Dans le temps</a></div>
      ${t ? `<div class="seg"><button type="button" data-p2="ganttZoom" data-c="days" aria-pressed="${zoom === "days"}">Jours</button><button type="button" data-p2="ganttZoom" data-c="weeks" aria-pressed="${zoom === "weeks"}">Semaines</button></div>` : ""}
      ${legend}<span class="grow"></span>${sheet.rights.edit ? `<button class="btn primary" type="button" data-p2="goalAdd" data-p="${id}">${ico("plus", "sm")}<span class="lbl">Ajouter un objectif</span></button>` : ""}</div>`;
  const lay = t ? layers(t, height) : null;
  const body = !list.length
    ? empty("p2-target", "Pas encore d'objectif", "Le diagramme se dessine dès le premier objectif.")
    : `<div class="p2-gantt ${mode}" data-p2-gantt="${t ? t.today : ""}"><div class="p2-g-in"${t ? ` style="--gw:${t.width}px"` : ""}>
          <div class="p2-g-head"><span class="p2-g-nom">Objectifs, jalons et missions</span><span class="p2-g-piste p2-g-axe">${t ? axis(t, zoom) : '<span class="av">la part faite</span><span class="av mot">où il en est</span>'}</span></div>
          <div class="p2-g-rows" style="height:${height}px">${lay ? `<div class="p2-g-calque">${lay.under}</div>` : ""}${lines}${lay ? `<div class="p2-g-calque dessus">${lay.over}</div>` : ""}</div></div></div>${d.cut ? hint("Trop d'exécutions pour tout relire : les dates les plus anciennes peuvent manquer.") : ""}`;
  return trio({ cls: "p2-diag", head: top, panes: [["", "Diagramme"]], active: "", link: () => f(mode, ...after), plain: true, scroll: `diagramme-${id}`, body, side: panel(sheet, d, pick, mode, ctx), infos: ctx.ui.infos });
}
