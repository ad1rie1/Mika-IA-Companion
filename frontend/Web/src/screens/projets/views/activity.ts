/**
 * L'onglet Activité d'une fiche (pur) : le Fil (ce qui s'est passé, par jour, ses filtres par sorte et par objectif,
 * et à droite le graphique des trente derniers jours), les Exécutions (une ligne de temps, et le détail de l'une pas
 * à pas), le Carnet (ses notes, par objectif). Les sortes, les verdicts et leurs mots sont ceux du serveur.
 */
import type { ActivityDays, ActivityPage, ActivityTotals, Happening, NotebookPage, Run, RunDetail, RunPage, Sheet, Status } from "../../../api/projects";
import { mikaAvatar } from "../../../mika/face";
import { h } from "../../../shell/dom";
import { ico, type IconName } from "../../../shell/icons";
import { plural } from "../gestures";
import { markdown } from "../md";
import { authorAvatar, bubble, byDay, empty, head, hint, linked, OUTSIDE, props, sc, st, subbar, tile, trio, type Trio } from "../parts";
import { route, sheetRoute } from "../routes";
import { chosen } from "../state";
import { axisDay, clock, dayLabel, duration, moment, shortDate, when } from "../time";
import { objectiveTone, runTone, type Tone } from "../tones";
import { nextAbout, nextWhen } from "./sheet";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** Les cinq sortes du fil gardent leur couleur (`s0` à `s4`), dans l'ordre où le serveur les sert. */
const SORT_CLASS = ["execution", "commit", "pr", "ticket", "geste"];
export const KIND_ICON: Record<string, IconName> = { run: "play", commit: "p2-commit", pull: "p2-pr", ticket: "p2-ticket", gesture: "user" };
const RUN_ICON: Record<string, IconName> = { frame: "p2-plan", run: "code", review: "eye" };

function happeningTone(x: Happening): Tone | "moi" | "" {
  if (x.kind === "gesture") return "moi";
  if (x.kind === "run") return runTone({ running: false, verdict: x.verdict });
  return x.what === "merged" ? "done" : "";
}

/** Où mène une ligne du fil : son exécution, son commit, sa pull request, son ticket, son objectif. */
export function happeningLink(project: number, x: Happening): string {
  if (x.kind === "run" && x.run) return sheetRoute(project, "activite", "executions", x.run);
  if (x.kind === "commit" && x.sha) return sheetRoute(project, "code", "commits", x.sha.slice(0, 7));
  if (x.pull) return sheetRoute(project, "code", "pulls", x.pull);
  if (x.ticket) return sheetRoute(project, "tickets", x.ticket);
  if (x.objective) return sheetRoute(project, "objectifs", `o${x.objective}`);
  return x.run ? sheetRoute(project, "activite", "executions", x.run) : "";
}

function chart(days: ActivityDays, pressed: string): string {
  const kinds = days.kinds;
  const max = Math.max(4, ...days.days.map((d) => d.total));
  const last = days.days.length - 1;
  const marks = [0, 7, 14, 21, last].filter((i, n, a) => i >= 0 && i <= last && a.indexOf(i) === n);
  const at = (i: number): number => new Date(`${days.days[i].day}T12:00:00`).getTime();
  const sorte = SORT_CLASS[kinds.findIndex((k) => k.code === pressed)] ?? "tout";
  return `<figure class="p2-chart" data-sorte="${sorte}"><figcaption><b>${days.total}</b><span>événements en trente jours</span></figcaption>
      <div class="p2-chart-plot" role="img" aria-label="L'activité du projet, jour par jour, sur trente jours"><span class="p2-chart-max">${max}</span>${days.days
        .map((d, i) => {
          const a = axisDay(at(i));
          return `<div class="p2-chart-col${i === last ? " auj" : ""}" tabindex="0">${kinds.map((k, n) => (Number(d[k.code]) ? `<i class="s${n}" style="height:${(Number(d[k.code]) / max) * 100}%"></i>` : "")).join("")}
            <div class="p2-chart-tip"><b>${i === last ? "Aujourd'hui" : `${a.day} ${a.n} ${a.month}`}</b>${d.total ? kinds.map((k, n) => (Number(d[k.code]) ? `<span><i class="s${n}"></i>${h(k.label)}<em>${Number(d[k.code])}</em></span>` : "")).join("") : "<span>Rien ce jour-là</span>"}</div></div>`;
        })
        .join("")}</div>
      <div class="p2-chart-axe">${marks.map((i) => `<span style="left:${((i + 0.5) / days.days.length) * 100}%">${i === last ? "auj." : shortDate(at(i))}</span>`).join("")}</div>
      <ul class="p2-chart-leg">${kinds.map((k, n) => `<li><button type="button" data-p2="feedKind" data-c="${h(k.code)}" aria-pressed="${pressed === k.code}"><i class="s${n}"></i><span>${h(k.label)}</span><b>${days.totals[k.code] ?? 0}</b></button></li>`).join("")}</ul>
      ${days.cut ? hint("Trop d'événements : les jours les plus anciens sont incomplets.") : ""}</figure>`;
}

function feedView(sheet: Sheet, feed: Got<ActivityPage>, more: readonly Happening[], cursor: number | null, days: Got<ActivityDays>, totals: ActivityTotals | null, ctx: Ctx): string {
  const id = sheet.project.id;
  const kinds: Status[] = feed.value?.kinds ?? totals?.kinds ?? days.value?.kinds ?? [];
  const items = [...(feed.value?.items ?? []), ...more];
  const o = (sheet.objectives ?? []).find((x) => x.id === ctx.ui.feedObjective);
  const row = (x: Happening): string => {
    const href = happeningLink(id, x);
    const inner = `<time>${clock(x.at)}</time>${tile(KIND_ICON[x.kind] ?? "check", happeningTone(x))}<span class="p2-ev-main"><b>${h(x.title)}</b>${x.sub || x.sha ? `<small>${x.sha ? `<code>${h(x.sha.slice(0, 7))}</code>${x.sub ? " · " : ""}` : ""}${h(x.sub)}</small>` : ""}</span>
        <span class="p2-ev-ref">${x.ticket ? `${ico("p2-ticket", "xs")}#${x.ticket}` : x.objective ? `${ico("p2-target", "xs")}objectif n° ${x.objective}` : ""}</span><span class="p2-ev-etat">${x.outside ? st("out", OUTSIDE) : x.verdict_label ? st(runTone({ running: false, verdict: x.verdict }), x.verdict_label) : ""}</span><span class="p2-ev-who" title="${h(x.author)}">${authorAvatar(x.author_kind, x.author, ctx.me)}<span class="ellipsis">${h(x.author)}</span></span>`;
    return href ? `<a class="p2-ev" href="${href}">${inner}</a>` : `<div class="p2-ev">${inner}</div>`;
  };
  // les comptes des pastilles : ceux de toute son histoire, pour l'objectif filtré (`…/activite/totaux`) ; « + » : un compte incomplet
  const count = (k: string): string => (totals ? `<span class="cnt"${totals.cut ? ' title="Trop d\'événements : ce compte est incomplet."' : ""}>${k ? (totals.totals[k] ?? 0) : totals.total}${totals.cut ? "+" : ""}</span>` : "");
  const tools = `<div class="p2-filters flat">${[["", "Tout"], ...kinds.map((k) => [k.code, k.label])].map(([k, label]) => `<button type="button" data-p2="feedKind" data-c="${h(k)}" aria-pressed="${ctx.ui.feedKind === k}">${h(label)}${count(k)}</button>`).join("")}</div>
      <button class="btn sm p2-objpick" type="button" data-p2="feedObjective" data-p="${id}">${ico("p2-target", "sm")}<span class="ellipsis">${o ? `Objectif n° ${o.id}` : "Tous les objectifs"}</span>${ico("chev-down", "xs")}</button>`;
  const next = cursor ?? feed.value?.next ?? 0;
  const body = !feed.value
    ? waitingBlock(feed)
    : items.length
      ? `<div class="p2-evs">${byDay(items, (x) => x.at, (ms) => dayLabel(ms, ctx.now), row)}${next ? `<button class="p2-add" type="button" data-p2="feedMore" data-c="${next}">${ico("chev-down", "sm")}Afficher la suite</button>` : ""}</div>`
      : empty("history", "Rien pour ce filtre", "Change de sorte ou d'objectif pour retrouver le fil.");
  const coming = sheet.next;
  return trio({
    cls: "p2-fil", panes: [["", "Fil"]], active: "", link: () => sheetRoute(id, "activite"), plain: true, scroll: `fil-${id}`, infos: ctx.ui.infos,
    head: `<div class="pane-head p2-filbar">${tools}</div>`, body,
    side: sc("Trente derniers jours", days.value ? chart(days.value, ctx.ui.feedKind) : waitingBlock(days))
      + sc("Prochain passage", `<div class="p2-next"><b>${h(coming ? nextWhen(coming, ctx.now) : sheet.project.status_label)}</b><span>${h((coming && nextAbout(coming)) || (sheet.project.last_run ? `dernier passage ${when(sheet.project.last_run, ctx.now)}` : "pas encore de passage"))}</span></div>${sheet.rhythm?.summary ? `<p class="p2-sc-text">${h(sheet.rhythm.summary)}</p>` : ""}`)
      + sc("Qui a fait quoi", days.value ? props(days.value.by.map((b): [string, string] => [`<span class="p2-by">${b.who === "self" ? mikaAvatar("xs") : b.who === "you" ? authorAvatar("you", "", ctx.me) : ""}${h(b.label[0].toUpperCase() + b.label.slice(1))}</span>`, plural(b.count, "événement", "événements")])) : ""),
  });
}

function runTitle(r: Run): string {
  return r.objective ? r.objective.text : r.sort_label[0].toUpperCase() + r.sort_label.slice(1);
}

function runState(r: Run): string {
  return st(runTone(r), r.verdict_label || r.outcome_label);
}

function runDetail(sheet: Sheet, r: RunDetail, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const tone = runTone(r);
  const o = r.objective;
  const steps = r.steps ?? [];
  let spent = 0;
  return {
    scroll: `exe-${r.id}`, panes: [["", "Pas à pas", steps.length]], active: "", link: () => sheetRoute(id, "activite", "executions", r.id),
    head: head({ tileHtml: tile(RUN_ICON[r.sort] ?? "play", tone), over: `Exécution · ${r.sort_label}`, title: runTitle(r), metaHtml: `${runState(r)}<span>${h(moment(r.at, ctx.now))}</span>${r.seconds ? `<span>${ico("clock", "xs")}${h(duration(r.seconds))}</span>` : ""}` }),
    body: `${r.report ? bubble("elle", "Mika", r.at, ctx.now, markdown(r.report), mikaAvatar("sm")) : ""}<h3 class="p2-h3">Ce qu'elle a fait, pas à pas<span class="cnt">${steps.length}</span></h3>
      ${r.steps_kept === false ? hint("Sa trace n'est plus gardée : elle l'est quatorze jours.") : ""}${r.steps_aims === false && r.steps_aims_why ? hint(r.steps_aims_why, "lock") : ""}
      <ol class="p2-pas">${steps
        .map((s) => {
          spent += s.ms;
          return `<li class="${s.ok ? "" : "fail"}"><i>${ico(s.ok ? (s.acts ? "pen" : "eye") : "x", "xs")}</i><span class="p2-pas-v">${h(s.label)}</span><p>${s.aim ? `<code>${h(s.aim)}</code>` : ""}${s.outside ? ` ${st("out", OUTSIDE, "Ce que cet outil rend vient d'ailleurs")}` : ""}${s.ran ? "" : " <span class=\"muted\">pas lancé</span>"}</p><time>+ ${h(duration(spent / 1000) || "0 s")}</time></li>`;
        })
        .join("")}
        <li class="fin ${tone}"><i>${ico(tone === "fail" ? "x" : tone === "you" ? "p2-question" : "check", "xs")}</i><span class="p2-pas-v">verdict</span><p>${h(r.verdict_label || r.outcome_label)}</p><time>${h(duration(r.seconds))}</time></li></ol>${r.steps_cut ? hint("Trop de pas pour tous les montrer : les deux cents premiers.") : ""}`,
    side: sc("En bref", props([["Verdict", runState(r)], ["Sorte", `<span class="p2-kind">${ico(RUN_ICON[r.sort] ?? "play", "xs")}${h(r.sort_label)}</span>`], ["Quand", h(moment(r.at, ctx.now))], r.seconds ? ["Durée", h(duration(r.seconds))] : null, r.proven ? ["Preuve", "sa sortie fait preuve"] : null]))
      + sc("Ce qu'elle t'a demandé", r.need ? `<p class="p2-sc-text">${h(r.need)}</p><a class="btn" href="${route("a-faire")}">Voir dans À faire${ico("chev-right", "sm")}</a>` : "")
      + sc("Sur quoi", o ? linked(sheetRoute(id, "objectifs", `${o.kind === "constant" ? "m" : "o"}${o.id}`), o.kind === "constant" ? "refresh" : "p2-target", objectiveTone(o.status), o.text, o.kind === "constant" ? "mission" : `objectif n° ${o.id}`, st(objectiveTone(o.status), o.status_label))
          + (o.ticket ? linked(sheetRoute(id, "tickets", o.ticket), "p2-ticket", "", `Ticket #${o.ticket}`, "celui dont il est né") : "") : "")
      + sc("Son commit", r.commit ? linked(sheetRoute(id, "code", "commits", r.commit.slice(0, 7)), "p2-commit", "", r.commit.slice(0, 7), r.branch ? `<code>${h(r.branch)}</code>` : "") : ""),
  };
}

function runsView(sheet: Sheet, rest: string[], runs: Got<RunPage>, run: Got<RunDetail>, ctx: Ctx): string {
  const id = sheet.project.id;
  const items = runs.value?.items ?? [];
  const picked = chosen(items, (x) => x.id, rest[0], ctx.mobile);
  const wanted = rest[0] || picked?.id;
  const row = (x: Run): string => `<a class="p2-cm" href="${sheetRoute(id, "activite", "executions", x.id)}" aria-selected="${x.id === wanted}"><i class="${runTone(x)}"></i><span class="li-title">${h(runTitle(x))}</span>
      <span class="p2-row-sub"><span class="p2-kind">${ico(RUN_ICON[x.sort] ?? "play", "xs")}${h(x.sort_label)}</span>${runState(x)}<time>${clock(x.at)}${x.seconds ? ` · ${h(duration(x.seconds))}` : ""}</time></span></a>`;
  const list = `<div class="pane-head"><h2>Exécutions</h2><span class="cnt">${runs.value?.total ?? ""}</span></div><div class="pane-scroll p2-timeline" data-scroll="exes">${!runs.value ? waitingBlock(runs) : byDay(items, (x) => x.at, (ms) => dayLabel(ms, ctx.now), row)}</div>`;
  const r = wanted && run.value && run.value.id === wanted ? run.value : null;
  return trio({
    list, open: !!rest[0], back: [sheetRoute(id, "activite", "executions"), "Exécutions"], infos: ctx.ui.infos,
    ...(r ? runDetail(sheet, r, ctx) : { empty: wanted ? waitingBlock(run, "Impossible de lire cette exécution") : empty("history", "Pas encore d'exécution", "Chaque séance de travail laisse ici son compte rendu, pas à pas.") }),
  });
}

function notebookView(sheet: Sheet, notes: Got<NotebookPage>, ctx: Ctx): string {
  const items = notes.value?.items ?? [];
  const objectives = [...(sheet.objectives ?? []), ...(sheet.missions ?? [])].map((o) => [o.id, o.text] as const);
  return `<div class="fill-scroll" data-scroll="carnet"><div class="p2-full"><header class="p2-sec-h"><div><h2>Son carnet</h2><p>Ce qu'elle note pour elle-même en travaillant. Elle le relit avant chaque passage.</p></div></header>
      <div class="p2-filters flat"><button type="button" data-p2="notebookFilter" data-c="0" aria-pressed="${!ctx.ui.notebook}">Tout${!ctx.ui.notebook && notes.value?.total !== undefined ? `<span class="cnt">${notes.value.total}${notes.value.total_cut ? "+" : ""}</span>` : ""}</button>${objectives.map(([id, text]) => `<button type="button" data-p2="notebookFilter" data-c="${id}" aria-pressed="${ctx.ui.notebook === id}">${h(text)}${ctx.ui.notebook === id && notes.value?.total !== undefined ? `<span class="cnt">${notes.value.total}${notes.value.total_cut ? "+" : ""}</span>` : ""}</button>`).join("")}</div>
      ${!notes.value ? waitingBlock(notes) : items.length
        ? `<div class="p2-notes">${items.map((n) => `<figure class="p2-notecard"><blockquote>${markdown(n.text)}</blockquote><figcaption>${mikaAvatar("xs")}<span>${h(n.objective?.text ?? "Le projet")}</span><time>${h(moment(n.at, ctx.now))}</time></figcaption></figure>`).join("")}</div>`
        : empty("book", "Carnet vide", ctx.ui.notebook ? "Elle n'a rien noté sur cet objectif." : "Elle n'a encore rien noté sur ce projet.")}</div></div>`;
}

export interface ActivityData {
  feed: Got<ActivityPage>;
  /** La suite du fil, page après page, et le curseur de la page suivante (`null` : celui de la première page). */
  more: readonly Happening[];
  cursor: number | null;
  days: Got<ActivityDays>;
  runs: Got<RunPage>;
  run: Got<RunDetail>;
  notes: Got<NotebookPage>;
  /** Les totaux de toute son histoire (les comptes des sous-onglets), et ceux de l'objectif filtré (les pastilles du fil). */
  totals: Got<ActivityTotals>;
  filtered: Got<ActivityTotals>;
}

export function activityView(sheet: Sheet, rest: string[], d: ActivityData, ctx: Ctx): string {
  const id = sheet.project.id;
  const v = rest[0] === "executions" ? 1 : rest[0] === "carnet" ? 2 : 0;
  const t = d.totals.value;
  const next = sheet.next;
  const bar = subbar([[sheetRoute(id, "activite"), "Fil"], [sheetRoute(id, "activite", "executions"), "Exécutions", t?.runs ?? d.runs.value?.total ?? null], [sheetRoute(id, "activite", "carnet"), "Carnet", t ? `${t.notes}${t.notes_cut ? "+" : ""}` : null]], v,
    next ? `<span class="p2-sync">${ico("clock", "xs")}prochain passage : ${h(nextWhen(next, ctx.now))}</span>` : sheet.project.last_run ? `<span class="p2-sync">${ico("clock", "xs")}dernier passage : ${h(when(sheet.project.last_run, ctx.now))}</span>` : "");
  return `${bar}<div class="p2-under">${v === 0 ? feedView(sheet, d.feed, d.more, d.cursor, d.days, d.filtered.value, ctx) : v === 1 ? runsView(sheet, rest.slice(1), d.runs, d.run, ctx) : notebookView(sheet, d.notes, ctx)}</div>`;
}
