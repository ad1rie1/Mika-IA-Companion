/**
 * « À faire » (pur) : à gauche ce qui attend la personne dans tous ses projets, groupé par projet ; au centre ce qu'il
 * faut lire pour décider ; à droite la décision. Le geste est celui du serveur (`gesture`) : ses boutons ne paraissent
 * que s'il le dit faisable ici (`can`), sinon sa raison (`why`) se lit telle quelle.
 */
import type { Approval, EntryDetail, Overview, Sheet, Waiting } from "../../../api/projects";
import { errorBlock, loadingBlock } from "../../../shared/kit";
import { h } from "../../../shell/dom";
import { ico } from "../../../shell/icons";
import { gesturePlace, gestureRead, safeLink } from "../gestures";
import { markdown } from "../md";
import { authorAvatar, bubble, empty, F, filters, head, hint, linked, OUTSIDE, outside, planBlock, props, pullCard, refusal, sc, st, ticketLine, tile, trio, type Trio } from "../parts";
import { route, sheetRoute, waitingHome, waitingKey, waitingRoute } from "../routes";
import { chosenWaiting, refusalAt, todoGroups, type UiState } from "../state";
import { moment, when } from "../time";
import { objectiveTone, waitingIcon } from "../tones";

/** Une lecture en cours, aboutie ou refusée. */
export interface Got<T> {
  value: T | null;
  error: unknown;
}

export function waitingBlock<T>(got: Got<T>, what = "Impossible de lire cette page"): string {
  return got.error && !got.value ? errorBlock(got.error, what) : loadingBlock();
}

export interface Ctx {
  now: number;
  mobile: boolean;
  ui: UiState;
  /** Le nom de la personne connectée, pour son avatar. */
  me: string;
}

export interface TodoData {
  overview: Overview;
  /** Toutes les attentes chargées (la première page, puis la suite). */
  todo: Waiting[];
  /** Ce que le geste de l'attente choisie demande de lire. */
  sheet: Got<Sheet>;
  approvals: Got<{ items: Approval[] }>;
  element: Got<EntryDetail>;
}

const NOTHING = (): string => empty("check", "Rien ne t'attend", "Tout ce qui demandait ta main est réglé.");

/** Les boutons d'un geste : `data-p2="todo"` porte l'action ; ce qui se saisit (une raison) se demande après. */
function button(action: string, label: string, primary: boolean, w: Waiting, ask = "", icon: "check" | "x" | "send" = primary ? "check" : "x"): string {
  return `<button class="btn lg${primary ? " primary" : ""}" type="button" data-p2="todo" data-p="${w.project}" data-k="${h(waitingKey(w))}" data-c="${h(action)}"${ask ? ` data-ask="${h(ask)}"` : ""}>${ico(icon, "sm")}${h(label)}</button>`;
}

function thread(e: EntryDetail, ctx: Ctx): string {
  return `<div class="p2-thread">${e.thread
    .map((n) => (n.outside ? outside(`${n.author} · ${when(n.at, ctx.now)}`, n.text) : bubble(n.author_kind === "you" ? "moi" : n.author_kind === "self" ? "elle" : "autre", n.author_kind === "you" ? "Toi" : n.author, n.at, ctx.now, h(n.text), authorAvatar(n.author_kind, n.author, ctx.me, "sm"))))
    .join("")}</div>`;
}

/** Ce qu'il faut lire, et les boutons de la décision, pour l'attente choisie. */
function reading(w: Waiting, d: TodoData, ctx: Ctx): { body: string; decide: string; word: string; lied: string } {
  const read = gestureRead(w);
  const place = gesturePlace(w);
  const here = place === "here";
  let body = `<p class="p2-lede">${h(w.about)}</p>`;
  let decide = "";
  let word = "";
  let lied = "";
  if (read.kind === "approval") {
    const a = d.approvals.value?.items.find((x) => x.id === read.id);
    if (!d.approvals.value) body = waitingBlock(d.approvals);
    else if (!a) body = `<p class="p2-lede">${h(w.about)}</p>${hint("Cet accord n'attend plus : il a été décidé, ou ce qui partait a changé.")}`;
    else {
      const page = safeLink(a.where_url);
      const fact = (name: string, valueHtml: string): string => (valueHtml ? `<div><dt>${name}</dt><dd>${valueHtml}</dd></div>` : "");
      body = `<section class="p2-sent"><h3>Ce qui partirait, mot pour mot</h3><p>${h(a.text)}</p></section><dl class="p2-facts">${fact("Ce que c'est", h(a.label))}
        ${fact("Où", a.where ? `${h(a.where)}${page ? ` · <a href="${h(page)}" target="_blank" rel="noopener noreferrer">sa page chez l'hôte${ico("external", "xs")}</a>` : ""}` : "")}${fact("Pourquoi", h(a.why ?? ""))}${fact("En bref", h(a.summary))}
        ${fact("Demandé", `${a.asked_by ? `par ${h(a.asked_by)} · ` : ""}${h(moment(a.at, ctx.now))}`)}</dl>${a.blocked ? refusal(a.blocked) : ""}`;
      const c = a.concerns;
      lied = (c?.ticket ? ticketLine(w.project, c.ticket) : "")
        + (c?.issue ? linked(sheetRoute(w.project, "code", "issues", c.issue), "p2-issue", "wait", `Issue n° ${c.issue}`, "chez l'hôte du dépôt") : "")
        + (c?.pull ? linked(sheetRoute(w.project, "code", "pulls", c.pull), "p2-pr", "", `Pull request n° ${c.pull}`, "chez l'hôte du dépôt") : "")
        + (c?.objective ? linked(sheetRoute(w.project, "objectifs", `o${c.objective}`), "p2-target", "", `Objectif n° ${c.objective}`, "celui qu'il concerne") : "");
      if (here) decide = button("accept", "Accorder", true, w) + button("refuse", "Refuser", false, w);
      word = "Rien ne part sans ton accord.";
    }
  } else if (read.kind === "plan") {
    const plan = d.sheet.value?.plan;
    if (!d.sheet.value) body = waitingBlock(d.sheet);
    else if (plan) {
      body = planBlock(`<b>Son plan</b>${st(plan.state === "proposed" ? "you" : "wait", plan.state_label)}`, markdown(plan.text), plan.state === "proposed") + (plan.questions ? `<h3 class="p2-h3">Ses questions</h3><div class="p2-md court">${markdown(plan.questions)}</div>` : "");
      if (here) decide = button("approve", "Valider le plan", true, w) + button("revise", "Demander une révision", false, w, "Ce qu'elle doit reprendre");
      word = "Validé, elle s'y met à son prochain passage. Sinon, elle le reprend avec ce que tu lui dis.";
    }
    lied = linked(sheetRoute(w.project), "flag", "", w.project_title, "le projet");
  } else if (read.kind === "milestone") {
    const o = d.sheet.value?.objectives?.find((x) => x.id === read.objective);
    const m = o?.milestones.find((x) => x.id === read.milestone);
    if (!d.sheet.value) body = waitingBlock(d.sheet);
    else if (o && m) {
      body = `<p class="p2-lede">${h(m.how || w.about)}</p><dl class="p2-facts"><div><dt>Le jalon</dt><dd>${h(m.text)}</dd></div><div><dt>Vérifié par</dt><dd>${h(m.check_label)}</dd></div>${m.ready_at ? `<div><dt>Prêt depuis</dt><dd>${h(moment(m.ready_at, ctx.now))}</dd></div>` : ""}</dl>${m.proof?.text ? outside("la preuve", m.proof.text, true) : ""}`;
      lied = linked(sheetRoute(w.project, "objectifs", `o${o.id}`), "p2-target", objectiveTone(o.status), o.text, `objectif n° ${o.id}`, st(objectiveTone(o.status), o.status_label));
    }
    if (here) decide = button("validate", "Valider le jalon", true, w) + button("refuse", "Refuser", false, w, "Ce qui manque");
    word = "Refusé, elle reprend ce jalon avec ce qui manque.";
  } else if (read.kind === "element") {
    const e = d.element.value;
    if (!e) body = waitingBlock(d.element);
    else if (e.veiled) body = `<p class="p2-lede">${h(w.about)}</p>${hint(e.veiled_label, "lock")}`;
    else if (e.list !== "tickets") {
      body = `<p class="p2-lede">${h(e.body || e.title)}</p><dl class="p2-facts"><div><dt>Statut</dt><dd>${st("wait", e.status_label)}</dd></div><div><dt>À la charge de</dt><dd>${h(e.actor_label)}</dd></div></dl>`;
      if (here && e.can.status) decide = e.statuses.filter((s) => s.code !== e.status).slice(0, 4).map((s, i) => button(s.code, `Passer à « ${s.label} »`, i === 0, w)).join("");
      lied = linked(sheetRoute(w.project, "listes", e.list), "p2-board", "", "Sa liste", h(e.list));
    } else {
      const asks = w.what === "question";
      const last = [...e.thread].reverse().find((n) => n.kind === "question");
      if (w.what === "validation" && e.plan_text) body = planBlock(`<b>Son plan</b>${st("you", e.status_label)}`, markdown(e.plan_text), true);
      else if (asks && last) body = bubble("elle", last.author, last.at, ctx.now, h(last.text), authorAvatar("self", last.author, ctx.me, "sm"));
      else body = `${e.body ? (e.outside ? outside(e.author, e.body) : `<div class="p2-md court">${markdown(e.body)}</div>`) : ""}${e.thread.length ? thread(e, ctx) : ""}` || `<p class="p2-lede">${h(w.about)}</p>`;
      if (here) {
        if (asks && e.can.note) {
          body += `<div class="p2-answer"><textarea rows="4" data-p2-champ data-keep="todo-${h(waitingKey(w))}" placeholder="Ta réponse…"></textarea><div class="p2-acts">${button("answer", "Répondre", true, w, "", "send")}</div></div>`;
          word = "Ta réponse lui rend la main : elle reprend à son prochain passage.";
        }
        if (e.can.validate) decide += button("validate", "Valider le plan", true, w);
        if (e.can.refuse) decide += button("refuse", "Refuser", false, w, "Ce qui ne va pas (elle le reprendra avec ça)");
        if (e.can.accept) decide += button("accept", "Accepter le ticket", true, w);
        // « Écarter » n'est le geste principal que s'il est le seul : une question a sa réponse, une pull request prête sa fusion
        if (e.can.dismiss) decide += button("dismiss", "Écarter", !e.can.accept && !e.can.validate && !asks && w.what !== "merge", w, e.can.dismiss_needs_reason ? "Pourquoi" : "Pourquoi (facultatif)", "x");
        if (e.can.validate) word = "Validé, elle s'y met à son prochain passage. Refusé, elle le reprend avec ce que tu lui dis.";
        else if (e.can.accept && e.outside) word = "Il vient d'ailleurs : elle n'y touche pas tant que tu ne l'as pas accepté.";
      }
      lied = linked(sheetRoute(w.project, "tickets", e.number, "fil"), "chat", "", "Le fil du ticket", `${e.thread.length} message${e.thread.length > 1 ? "s" : ""}`)
        + (e.linked?.objective ? linked(sheetRoute(w.project, "objectifs", `o${e.linked.objective.id}`), "p2-target", objectiveTone(e.linked.objective.status), e.linked.objective.text, `objectif n° ${e.linked.objective.id}`, st(objectiveTone(e.linked.objective.status), e.linked.objective.status_label))
          : e.objective ? linked(sheetRoute(w.project, "objectifs", `o${e.objective}`), "p2-target", "", `Objectif n° ${e.objective}`, "celui qui le porte") : "")
        + pullCard(w.project, e.linked?.pull ?? null, e.linked?.checks ?? null, null, ctx.now);
    }
  } else if (here && w.gesture.route !== "code/pull/fusionner") {
    // un geste que rien d'ici ne détaille : son bouton porte le libellé du serveur, et s'il se saisit quelque chose, on le demande
    // (fusionner a le sien, `mergeDecision` : il passe par une confirmation qui nomme le commit de tête)
    const typed = w.gesture.route === "piloter";
    decide = button("go", w.gesture.label, true, w, typed ? "Ta réponse" : "", typed ? "send" : "check");
  }
  return { body, decide, word, lied };
}

/** Ce qui ne se fait pas ici : où, et pourquoi, avec les mots du serveur. */
function elsewhere(w: Waiting): string {
  const place = gesturePlace(w);
  if (place === "here") return "";
  const url = safeLink(w.gesture.url);
  if (place === "theirs") return hint(`Ce n'est pas toi qu'on attend ici${w.waits_for ? ` : c'est ${w.waits_for}` : ""}.`, "clock");
  if (place === "host") {
    return `${hint(w.why || w.gesture.label, "external")}${url ? `<div class="p2-decide"><a class="btn lg" href="${h(url)}" target="_blank" rel="noopener noreferrer">${ico("external", "sm")}${h(w.gesture.label)}</a></div>` : ""}`;
  }
  return hint(w.why || w.gesture.label, "lock");
}

/**
 * Une pull request à fusionner : le geste est servi par l'API (`code/pull/fusionner`). Le bouton ouvre la confirmation
 * de l'onglet Code (`code.ts`, `merge`), qui relit la pull request et nomme son commit de tête ; il ne paraît que si
 * le serveur dit le geste faisable ici (`can`), sinon sa raison se lit telle quelle (`why`).
 */
function mergeDecision(w: Waiting, where: string, more = ""): string {
  const number = Number(w.gesture.args?.number ?? 0);
  const here = gesturePlace(w) === "here" && w.gesture.route === "code/pull/fusionner" && number > 0;
  return `<div class="p2-decide">${here ? `<button class="btn lg primary" type="button" data-p2="merge" data-p="${w.project}" data-c="${number}" data-w="${h(where)}">${ico("p2-merge", "sm")}Fusionner</button>` : ""}
      <a class="btn lg${here ? "" : " primary"}" href="${waitingHome(w)}">${ico("p2-pr", "sm")}Ouvrir la pull request</a>${more}</div>${here ? "" : elsewhere(w)}${hint("C'est ton geste : Mika ne fusionne jamais.")}`;
}

function detail(w: Waiting, d: TodoData, ctx: Ctx): Trio {
  const r = reading(w, d, ctx);
  const key = `todo:${w.project}:${waitingKey(w)}`;
  const out = w.outside ? st("out", OUTSIDE) : "";
  const merge = w.kind === "ticket" && w.what === "merge" && gesturePlace(w) !== "theirs";
  return {
    scroll: `af-${w.project}-${waitingKey(w)}`,
    head: head({
      tileHtml: tile(waitingIcon(w.kind, w.what), "you"), over: w.kind_label, title: w.about,
      metaHtml: `<a href="${sheetRoute(w.project)}">${h(w.project_title)}</a><span>${h(when(w.since, ctx.now))}</span>${out}`,
      rightHtml: `<a class="btn" href="${waitingHome(w)}">Ouvrir dans le projet${ico("chev-right", "sm")}</a>`,
    }),
    body: refusal(refusalAt(ctx.ui, key)) + r.body,
    side:
      // une pull request prête : fusionner d'abord, les autres gestes de son ticket (l'écarter) ensuite
      sc("Ta décision", (merge ? mergeDecision(w, key, r.decide) : `${r.decide ? `<div class="p2-decide">${r.decide}</div>` : ""}${elsewhere(w)}${r.word && r.decide ? hint(r.word) : ""}`) || hint(w.gesture.label))
      + sc("En bref", props([["Projet", `<a href="${sheetRoute(w.project)}">${h(w.project_title)}</a>`], ["Ce que c'est", h(w.kind_label)], ["Depuis", h(moment(w.since, ctx.now))], w.outside ? ["D'où", st("out", OUTSIDE)] : null]))
      + sc("Ce qui est lié", r.lied),
  };
}

export function todoView(d: TodoData, project: number, key: string, ctx: Ctx): string {
  const groups = todoGroups(d.todo);
  const shown = d.todo.filter((w) => !ctx.ui.todoProject || w.project === ctx.ui.todoProject);
  const w = chosenWaiting(shown, project, key, ctx.mobile) ?? (key ? chosenWaiting(d.todo, project, key, true) : null);
  const row = (x: Waiting): string => `<a class="li p2-row" href="${waitingRoute(x)}" aria-selected="${x === w}">${tile(waitingIcon(x.kind, x.what), "you")}
      <span class="li-main"><span class="li-title">${h(x.about)}</span><span class="p2-row-sub"><span>${h(x.kind_label)}</span>${x.outside ? st("out", OUTSIDE) : ""}<time>${h(when(x.since, ctx.now))}</time></span></span></a>`;
  const more = d.todo.length < d.overview.todo_total ? `<button class="p2-add" type="button" data-p2="todoMore">${ico("chev-down", "sm")}Afficher la suite (${d.overview.todo_total - d.todo.length})</button>` : "";
  const list = `<div class="pane-head"><h2>Ce qui t'attend</h2><span class="cnt">${d.overview.todo_total}</span></div>
      ${filters("todoFilter", [["0", "Tous"], ...groups.map((g): [string, string, number] => [String(g.project), g.title, g.items.length])], String(ctx.ui.todoProject))}
      <div class="pane-scroll" data-scroll="af-liste">${shown.length
        ? groups.filter((g) => !ctx.ui.todoProject || g.project === ctx.ui.todoProject).map((g) => `<div class="group-label">${h(g.title)}<span class="cnt">${g.items.length}</span></div>${g.items.map(row).join("")}`).join("") + more
        : NOTHING()}</div>`;
  return trio({
    list, open: !!key && !!w, back: [route("a-faire"), "À faire"], panes: [["", "À lire"]], active: "", link: () => (w ? waitingRoute(w) : route("a-faire")), infos: ctx.ui.infos,
    ...(w ? detail(w, d, ctx) : { empty: NOTHING() }),
  });
}

/** Les champs de la fenêtre qui demande une raison, un mot, une réponse. */
export function askBody(label: string, hintText = ""): string {
  return `<div class="stack">${F.long("typed", label, "", { rows: 4, hint: hintText })}</div>`;
}
