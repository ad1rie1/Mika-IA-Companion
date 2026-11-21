/**
 * L'onglet Objectifs d'une fiche (pur) : la liste serrée — une ligne par objectif —, le détail (ses jalons en étapes
 * et leurs preuves, sa branche et sa pull request, ses comptes rendus), une mission (son rythme, ses passages), et
 * leurs formulaires : ajouter un objectif ou une mission, modifier, ajouter ou modifier un jalon. Les boutons suivent
 * ce que le serveur dit de chaque objet (`can`, `rights`) ; ce que les formulaires proposent — ce qui peut déclencher
 * une mission, les façons de vérifier un jalon, leurs mots et leurs champs — est servi par la fiche (`forms`).
 */
import type { ActivityPage, CheckKind, Milestone, Objective, Sheet } from "../../../api/projects";
import { h } from "../../../shell/dom";
import { ico } from "../../../shell/icons";
import { plural } from "../gestures";
import { markdown } from "../md";
import { authorAvatar, bar, bubble, empty, F, filters, form, head, linked, outside, props, pullCard, refusal, sc, st, ticketLine, tile, trio, type Trio } from "../parts";
import { sheetRoute, waitingRoute } from "../routes";
import { chosen, fieldErrorsAt, findGoal, goalAwaits, goalGroups, goalKey, liveMilestones, refusalAt, type Goal } from "../state";
import { age, moment, when } from "../time";
import { milestoneIcon, milestoneTone, objectiveTone, runTone } from "../tones";
import { milestoneTones, reachedCount } from "./sheet";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** La bascule de l'onglet : la liste et son détail, ou le diagramme. */
export function modeSwitch(project: number, mode: "liste" | "diagramme"): string {
  return `<div class="seg p2-mode" title="La vue des objectifs"><a href="${sheetRoute(project, "objectifs")}" aria-pressed="${mode === "liste"}">${ico("menu", "sm")}Liste</a><a href="${sheetRoute(project, "objectifs", "diagramme")}" aria-pressed="${mode === "diagramme"}">${ico("sort", "sm")}Diagramme</a></div>`;
}

/** Comment un jalon se vérifie, en une ligne : sa commande (servie avec le droit sur ses fichiers), l'élément qui le lie
 *  à son registre et le statut qu'il attend, ou ce qu'elle en dit (`how`). */
export function verified(m: Pick<Milestone, "check" | "check_label" | "how" | "command" | "item_list" | "item" | "item_status_label">, project = 0): string {
  const command = m.check === "command" ? (m.command ?? "") : "";
  const item = m.item ? `<code>${h(m.item)}</code>` : "";
  const to = m.item && project ? (m.item_list === "tickets" && /^#\d+$/.test(m.item) ? sheetRoute(project, "tickets", m.item.slice(1)) : m.item_list && m.item_list !== "tickets" ? sheetRoute(project, "listes", m.item_list) : "") : "";
  const bound = m.item ? ` · ${to ? `<a href="${to}">${item}</a>` : item}${m.item_status_label ? ` doit être « ${h(m.item_status_label)} »` : ""}` : "";
  return `Vérifié par ${h(m.check_label)}${command ? ` · <code>${h(command)}</code>` : ""}${bound}${m.how ? ` — ${h(m.how)}` : ""}`;
}

/** L'état d'un jalon : prêt (à toi), commencé (`started` : elle s'y est mise), sinon les mots du serveur. */
export function milestoneState(m: Pick<Milestone, "status" | "status_label" | "ready" | "refused_at" | "started">): string {
  const tone = milestoneTone(m);
  return m.ready ? st("you", "prêt · à toi") : m.status === "open" && m.started && tone === "work" ? st("work", "en cours", m.status_label) : st(tone, m.status_label);
}

export function proofBlock(m: Pick<Milestone, "proof" | "commit">): string {
  return m.proof?.text
    ? `<details class="p2-proof"><summary>${ico("chev-right", "xs")}La preuve${m.commit ? ` · commit <code>${h(m.commit.slice(0, 7))}</code>` : ""} · ${ico("external", "xs")}venue d'ailleurs</summary><pre>${h(m.proof.text)}</pre></details>`
    : "";
}

export function checkpointButtons(project: number, objective: number, milestone: number, cls = ""): string {
  const d = `data-p="${project}" data-o="${objective}" data-c="${milestone}"`;
  return `<button class="btn ${cls} primary" type="button" data-p2="checkpoint" data-v="validate" ${d}>${ico("check", "sm")}Valider le jalon</button><button class="btn ${cls}" type="button" data-p2="checkpoint" data-v="refuse" ${d}>${ico("x", "sm")}Refuser</button>`;
}

function milestone(sheet: Sheet, o: Objective, m: Milestone, ctx: Ctx): string {
  const tone = milestoneTone(m);
  const d = `data-p="${sheet.project.id}" data-o="${o.id}" data-c="${m.id}"`;
  const at = m.reached_at || m.ready_at || m.refused_at;
  const edit = (m.can?.modify ? `<button class="btn xs icon ghost" type="button" data-p2="milestoneEdit" ${d} title="Modifier le jalon">${ico("pen", "sm")}</button>` : "")
    + (m.can?.drop ? `<button class="btn xs icon ghost danger" type="button" data-p2="milestoneDrop" ${d} title="Retirer le jalon">${ico("trash", "sm")}</button>` : "");
  return `<li class="${tone}"><i>${ico(milestoneIcon(tone), "xs")}</i><div class="p2-j">
      <div class="p2-j-top"><b>${h(m.text)}</b>${milestoneState(m)}<time>${at ? h(when(at, ctx.now)) : ""}</time>
        ${edit ? `<span class="p2-j-edit">${edit}</span>` : m.can?.why && m.status === "open" ? `<span class="p2-j-edit" title="${h(m.can.why)}">${ico("lock", "xs")}</span>` : ""}</div>
      <p class="p2-j-how">${verified(m, sheet.project.id)}</p>
      ${m.refused_at && m.reason ? `<p class="p2-j-no">${ico("x", "xs")}Refusé : « ${h(m.reason)} »</p>` : m.status === "dropped" && m.reason ? `<p class="p2-j-no">${ico("x", "xs")}${h(m.reason)}</p>` : ""}
      ${proofBlock(m)}
      ${m.ready && sheet.rights.settle ? `<div class="p2-acts">${checkpointButtons(sheet.project.id, o.id, m.id)}</div>` : ""}</div></li>`;
}

/** Les comptes rendus d'un objectif ou les passages d'une mission : ses exécutions, lues dans le fil d'activité. */
function reports(got: Got<ActivityPage>, sheet: Sheet, ctx: Ctx, none: string): string {
  if (sheet.rights.work === false) return `<p class="p2-none">${h(none)}</p>`;
  if (!got.value) return waitingBlock(got);
  if (!got.value.items.length) return `<p class="p2-none">${h(none)}</p>`;
  return `<ol class="p2-tl">${got.value.items
    .map((r) => `<li class="${runTone({ running: false, verdict: r.verdict })}"><time>${h(moment(r.at, ctx.now))}</time>${r.verdict_label ? st(runTone({ running: false, verdict: r.verdict }), r.verdict_label) : ""}<p>${r.run ? `<a href="${sheetRoute(sheet.project.id, "activite", "executions", r.run)}">${h(r.title)}</a>` : h(r.title)}</p></li>`)
    .join("")}</ol>`;
}

/** Les champs d'un objectif : ponctuel (« fini quand ») ou mission (sa cadence, ce qui la déclenche, chaque passage). */
function goalFields(sheet: Sheet, g: Goal | null, errors: Record<string, string>): string {
  const mission = g?.mission ? g.o : null;
  const once = g && !g.mission ? g.o : null;
  // ce qui peut déclencher une mission : la liste que la fiche sert (`forms.triggers`), avec ses mots ; sa clé part telle quelle
  const triggers = sheet.forms?.triggers ?? [];
  const max = sheet.forms?.triggers_max ?? 0;
  const on = new Set((mission?.on ?? []).map((t) => t.key));
  return `${g ? "" : F.cards("kind", "Ce que c'est", "once", [["once", "Un objectif", "il a une fin : des jalons, puis « terminé »"], ["constant", "Une mission", "elle revient : à une cadence, ou quand quelque chose bouge"]])}
    ${F.text("text", mission ? "La mission" : "Ce qu'il faut atteindre", g?.o.text ?? "", { required: true, hint: "Par exemple : Créer un module RDP", error: errors.text })}
    <div class="si-ponctuel">${F.long("done_when", "Fini quand", once?.done_when ?? "", { rows: 2, hint: "Ce qui te ferait dire « c'est fait »", error: errors.done_when })}</div>
    <div class="si-mission">${F.text("cadence_hours", "Sa cadence, en heures", mission?.cadence_hours ?? 0, { type: "number", help: "0 : la cadence par défaut du projet.", error: errors.cadence_hours })}
      ${triggers.length ? F.group("Ce qui la déclenche", `<div class="p2-checks-grid">${triggers.map((t) => F.check("on", t.label, on.has(t.key), t.sort_label, t.key)).join("")}</div>${errors.on ? `<small class="p2-field-err">${h(errors.on)}</small>` : ""}`, max ? `${max} au plus.` : "") : ""}
      ${F.check("only_on_event", "Seulement quand quelque chose bouge", mission?.only_on_event ?? false, "sinon, elle passe aussi à sa cadence")}
      ${F.long("each_pass", "Ce que chaque passage doit faire", mission?.each_pass ?? "", { rows: 3, hint: "Une ligne par chose. Par exemple : relire les sorties de la veille.", error: errors.each_pass })}
      ${g ? "" : F.check("at_once", "Premier passage tout de suite", true, "sinon, elle attend la prochaine échéance")}</div>`;
}

/** Le corps du panneau « Ajouter un objectif ». */
export function goalDrawerBody(sheet: Sheet, errors: Record<string, string>): string {
  return goalFields(sheet, null, errors);
}

/** Un champ d'une façon de vérifier un jalon : son libellé et son aide sont ceux du serveur ; la liste et le statut se
 *  choisissent parmi ceux que la fiche sert, le reste se saisit. */
function checkField(sheet: Sheet, f: CheckKind["fields"][number], m: Milestone | null, errors: Record<string, string>): string {
  const lists = sheet.lists ?? [];
  const value = m ? String((m as unknown as Record<string, unknown>)[f.name] ?? "") : "";
  const o = { help: f.help, error: errors[f.name] };
  if (f.name === "item_list" && lists.length) return F.select(f.name, f.label, value, lists.map((l) => [l.name, l.title] as const), o);
  if (f.name === "item_status" && lists.length) return F.select(f.name, f.label, value, lists.flatMap((l) => [...l.open, ...l.closed].map((s) => [s.code, `${l.title} · ${s.label}`] as const)), o);
  return F.text(f.name, f.label, value, o);
}

/** Le corps du panneau « Ajouter un jalon » ou « Modifier le jalon » : les façons de le vérifier, leurs mots et leurs
 *  champs sont ceux que la fiche sert (`forms.checks`). */
export function milestoneDrawerBody(sheet: Sheet, m: Milestone | null, errors: Record<string, string>): string {
  const checks = sheet.forms?.checks ?? [];
  return `${F.text("text", "Ce qui doit être vrai", m?.text ?? "", { required: true, hint: "Par exemple : La connexion aboutit sur l'hôte d'essai", error: errors.text })}
    ${checks.length ? F.cards("check", "Comment on le vérifie", m?.check ?? checks[0].code, checks.map((c) => [c.code, c.label, c.help] as const), { error: errors.check }) : ""}
    ${checks.filter((c) => c.fields.length).map((c) => `<div class="p2-si" data-si="check=${h(c.code)}">${c.fields.map((f) => checkField(sheet, f, m && m.check === c.code ? m : null, errors)).join("")}</div>`).join("")}
    ${m ? F.text("reason", "Pourquoi ce changement (facultatif)", "", {}) : ""}`;
}

/** Le panneau latéral d'un objectif ou d'une mission : le diagramme le reprend. */
export function goalSide(sheet: Sheet, g: Goal, ctx: Ctx): string {
  const id = sheet.project.id;
  const d = `data-p="${id}" data-c="${g.o.id}"`;
  const can = g.o.can;
  if (g.mission) {
    const m = g.o;
    return sc("Son rythme", props([["Cadence", h(m.cadence_label)], ["Ce qui la déclenche", h(m.on.map((x) => x.label).join(", ") || "—")], m.only_on_event ? ["Quand", "seulement quand quelque chose bouge"] : null, ["Passages", String(m.passes)], m.last_run ? ["Le dernier", h(moment(m.last_run, ctx.now))] : null]))
      + (can?.drop ? sc("Gérer", `<div class="p2-decide"><button class="btn danger" type="button" data-p2="goalStatus" data-s="dropped" data-m="1" ${d}>${ico("trash", "sm")}Retirer la mission</button></div>`, "", "bas") : "");
  }
  const o = g.o;
  const live = liveMilestones(o);
  const tone = objectiveTone(o.status);
  const manage = (can?.reopen ? `<button class="btn" type="button" data-p2="goalStatus" data-s="open" ${d}>${ico("refresh", "sm")}Rouvrir l'objectif</button>` : "")
    + (can?.done ? `<button class="btn" type="button" data-p2="goalStatus" data-s="done" ${d}>${ico("check", "sm")}Le dire terminé</button>` : "")
    + (can?.drop ? `<button class="btn danger" type="button" data-p2="goalStatus" data-s="dropped" ${d}>${ico("trash", "sm")}Retirer l'objectif</button>` : "");
  return sc("Fini quand", `<p class="p2-sc-text">${h(o.done_when || "Rien de dit : elle jugera elle-même.")}</p>`)
    + sc("Où il en est", `<div class="p2-prog big">${bar(milestoneTones(o))}<span>${live.length ? `${reachedCount(o)} / ${plural(live.length, "jalon", "jalons")}` : "pas de jalon"}</span></div>`
      + props([["État", st(tone, o.status_label)], ["Passages", String(o.runs)], o.last_run ? ["Dernier passage", h(moment(o.last_run, ctx.now))] : null, o.result ? ["Résultat", h(o.result)] : null, o.note ? ["Note", h(o.note)] : null]))
    + sc("Branche et pull request", o.branch || o.pull ? `${o.branch ? `<p class="p2-branchline">${ico("p2-branch", "sm")}<code>${h(o.branch)}</code>${sheet.repo?.branch ? `${ico("chev-right", "xs")}<code>${h(sheet.repo.branch)}</code>` : ""}</p>` : ""}${pullCard(id, o.pull, o.checks, o.review, ctx.now)}` : "")
    + sc("Tickets liés", (o.tickets ?? []).map((t) => ticketLine(id, t)).join("") || (o.ticket ? linked(sheetRoute(id, "tickets", o.ticket), "p2-ticket", "", `Ticket #${o.ticket}`, "celui dont il est né") : ""))
    + (manage ? sc("Gérer", `<div class="p2-decide">${manage}</div>`, "", "bas") : "");
}

function goalDetail(sheet: Sheet, g: Goal, pane: string | undefined, runs: Got<ActivityPage>, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const key = goalKey(g);
  const f = (...x: string[]): string => sheetRoute(id, "objectifs", key, ...x);
  const can = g.o.can;
  const editing = pane === "modifier" && !!can?.modify;
  const formKey = `goal:${id}:${key}`;
  const edit = can?.modify ? `<a class="btn${editing ? " on" : ""}" href="${f(editing ? "" : "modifier")}">${ico("pen", "sm")}Modifier</a>` : "";
  const launch = sheet.rights.pilot && g.o.status !== "done" ? `<button class="btn" type="button" data-p2="runNow" data-p="${id}" data-o="${g.o.id}">${ico("play", "sm")}<span class="lbl">Lancer maintenant</span></button>` : "";
  const editForm = (): string => form({ name: "goal", key: formKey, data: { p: id, c: g.o.id, m: g.mission ? 1 : 0 }, title: g.mission ? "Modifier la mission" : "Modifier l'objectif", sub: "Elle lira ce changement avant son prochain passage.",
    cancel: f(), error: refusalAt(ctx.ui, formKey), bodyHtml: `<div class="p2-fixe ${g.mission ? "mission" : "ponctuel"}">${goalFields(sheet, g, fieldErrorsAt(ctx.ui, formKey))}</div>` });
  if (g.mission) {
    const m = g.o;
    return {
      scroll: `mis-${id}-${m.id}-${editing ? "m" : ""}`, link: (k) => f(k), active: editing ? "modifier" : "",
      panes: editing ? [["modifier", "Modifier"]] : [["", "Derniers passages", runs.value ? runs.value.items.length : null]],
      head: head({ tileHtml: tile("refresh", "work"), over: "Mission", title: m.text, metaHtml: `${st(m.status === "open" ? "work" : "wait", m.status_label)}<span>${plural(m.passes, "passage", "passages")}</span>${m.last_run ? `<span>le dernier ${h(when(m.last_run, ctx.now))}</span>` : ""}`, rightHtml: launch + edit }),
      body: editing ? editForm() : `${m.need ? needBlock(sheet, m.id, m.need, ctx) : ""}<p class="p2-when"><b>À chaque passage</b>${h(m.each_pass || "Rien de précisé.")}</p>${reports(runs, sheet, ctx, "Elle n'est pas encore passée.")}`,
      side: goalSide(sheet, g, ctx),
    };
  }
  const o = g.o;
  const live = liveMilestones(o);
  const tone = objectiveTone(o.status);
  const v = editing ? "modifier" : pane === "rendus" ? "rendus" : "";
  const body = editing
    ? editForm()
    : v === "rendus"
      ? reports(runs, sheet, ctx, o.result || "Elle n'y a pas encore travaillé.") + (o.review ? `<h3 class="p2-h3">Sa relecture</h3><p class="p2-lede">${st(o.review.ok ? "done" : "fail", o.review.label)} ${h(o.review.text)}</p>` : "")
      : `${refusal(refusalAt(ctx.ui, `goal-act:${id}:${o.id}`))}${o.need ? needBlock(sheet, o.id, o.need, ctx) : ""}
        ${o.milestones.length ? `<ol class="p2-jalons">${o.milestones.map((m) => milestone(sheet, o, m, ctx)).join("")}</ol>` : '<p class="p2-none">Pas de jalon : elle dira elle-même quand c\'est fini.</p>'}
        ${can?.milestone ? `<button class="p2-add" type="button" data-p2="milestoneAdd" data-p="${id}" data-o="${o.id}">${ico("plus", "sm")}Ajouter un jalon</button>` : ""}
        ${o.checks?.said?.text ? outside("la fin du journal de la CI", o.checks.said.text, true) : ""}${o.pull?.said?.text ? outside("le dernier mot de l'hôte", o.pull.said.text) : ""}`;
  return {
    scroll: `obj-${id}-${o.id}-${v}`, link: (k) => f(k), active: v,
    panes: editing ? [["modifier", "Modifier"]] : [["", "Jalons", `${reachedCount(o)}/${live.length}`], ["rendus", "Comptes rendus", o.runs || null]],
    head: head({ tileHtml: tile("p2-target", tone), over: `Objectif n° ${o.id}`, title: o.text,
      metaHtml: `${st(tone, o.status_label)}<span>${plural(o.runs, "passage", "passages")}</span>${o.last_run ? `<span>le dernier ${h(when(o.last_run, ctx.now))}</span>` : ""}`, rightHtml: launch + edit }),
    body,
    side: goalSide(sheet, g, ctx),
  };
}

/** Elle a besoin de quelque chose : ses mots en bulle, et où lui répondre (l'attente d'« À faire » que le serveur a comptée). */
function needBlock(sheet: Sheet, objective: number, need: string, ctx: Ctx): string {
  const w = sheet.todo.find((x) => x.objective === objective && (x.kind === "need" || x.kind === "blocked" || x.kind === "stalled"));
  return `<section class="p2-need">${bubble("elle", "Mika", 0, ctx.now, markdown(need), authorAvatar("self", "Mika", ctx.me, "sm"))}${w?.mine ? `<div class="p2-acts"><a class="btn primary" href="${waitingRoute(w)}">${ico("send", "sm")}Lui répondre</a></div>` : ""}</section>`;
}

export function objectivesView(sheet: Sheet, rest: string[], runs: Got<ActivityPage>, ctx: Ctx): string {
  const id = sheet.project.id;
  const groups = goalGroups(sheet);
  const seen = groups.filter((g) => !ctx.ui.objectives || ctx.ui.objectives === g.code);
  const all = seen.flatMap((g) => g.items);
  const g = findGoal(sheet, rest[0]) ?? chosen(all, goalKey, rest[0], ctx.mobile);
  const add = sheet.rights.edit ? `<button class="btn primary" type="button" data-p2="goalAdd" data-p="${id}">${ico("plus", "sm")}<span>Ajouter un objectif</span></button>` : "";
  const row = (x: Goal): string => {
    if (x.mission) {
      return `<a class="p2-orow mission" href="${sheetRoute(id, "objectifs", goalKey(x))}" aria-selected="${!!g && goalKey(g) === goalKey(x)}" title="${h(x.o.text)} — ${h(x.o.cadence_label)}"><i class="${x.o.status === "open" ? "work" : "wait"}"></i><span class="p2-orow-t">${h(x.o.text)}</span>
        <span class="p2-orow-c">${h(x.o.cadence_label)}</span><time>${h(age(x.o.last_run, ctx.now))}</time></a>`;
    }
    const live = liveMilestones(x.o);
    return `<a class="p2-orow${goalAwaits(x.o) ? " atoi" : ""}" href="${sheetRoute(id, "objectifs", goalKey(x))}" aria-selected="${!!g && goalKey(g) === goalKey(x)}" title="${h(x.o.text)} — ${h(x.o.status_label)}"><i class="${objectiveTone(x.o.status)}"></i><span class="p2-orow-t">${h(x.o.text)}</span>
        ${live.length ? `${bar(milestoneTones(x.o))}<span class="num">${reachedCount(x.o)}/${live.length}</span>` : '<span class="p2-orow-c">sans jalon</span>'}<time>${h(age(x.o.last_run, ctx.now))}</time></a>`;
  };
  const list = `<div class="p2-tools">${modeSwitch(id, "liste")}<span class="grow"></span>${add}</div>
      ${filters("goalFilter", groups.map((x): [string, string, number] => [x.code, x.label, x.items.length]), ctx.ui.objectives)}
      <div class="pane-scroll p2-olist" data-scroll="obj-liste">${all.length ? seen.filter((x) => x.items.length).map((x) => `<div class="group-label">${x.label}<span class="cnt">${x.items.length}</span></div>${x.items.map(row).join("")}`).join("") : empty("p2-target", "Rien ici", "Aucun objectif pour ce filtre.")}</div>`;
  return trio({
    cls: "p2-obj", list, open: !!rest[0] && !!g, back: [sheetRoute(id, "objectifs"), "Objectifs"], infos: ctx.ui.infos,
    ...(g ? goalDetail(sheet, g, rest[1], runs, ctx) : { empty: empty("p2-target", "Pas encore d'objectif", "Un objectif a une fin ; une mission revient. Ajoute le premier, ou laisse-la les proposer dans son plan.", add) }),
  });
}
