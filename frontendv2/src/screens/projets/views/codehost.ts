/**
 * L'onglet Code d'une fiche, ce qui se joue avec l'hôte du dépôt (pur) : **Pull requests** (la liste et ses états ;
 * une pull request en volets — Résumé avec les jalons et leurs preuves, Commits, Fichiers, Échanges — ; le panneau :
 * sa fusion, sa relecture, ses vérifications une à une, ses conflits, sa branche, le ticket et l'objectif liés ;
 * Modifier, répondre, **Fusionner**), **Issues** (la liste, Description et Échanges, l'état chez l'hôte, le ticket
 * lié et son étape) et **CI** (les vérifications par commit, le détail, la fin du journal d'un échec).
 *
 * Aucune règle n'est refaite ici : Fusionner n'est actif que si le serveur le dit (`merge.can`), sinon sa raison se
 * lit telle quelle (`merge.why`, `merge.refused`) ; Modifier et répondre demandent `rights.pull_write`. **Tout texte
 * de l'hôte** — un titre, un texte, un commentaire, une étiquette, le nom d'une vérification, la fin d'un journal, un
 * compte — est présenté comme venu d'ailleurs, échappé, jamais interprété.
 */
import type { CheckRun, CommitChecks, HostChecks, Issue, IssueDetail, IssuePage, PullDetail, PullHost, PullLine, PullPage, Remark, TrackedChecks } from "../../../api/projectCode";
import type { Approval, EntryDetail, OutsideText, Sheet } from "../../../api/projects";
import { mikaAvatar } from "../../../mika/face";
import { h } from "../../../shell/dom";
import { ico, type IconName } from "../../../shell/icons";
import { branchRoute, checksRoute, mergeLines, mergeStage, pullKey, pullRoute, type MergeFacts } from "../codeparts";
import { plural, safeLink } from "../gestures";
import { banner, byDay, code, empty, F, form, head, hint, nothing, OUTSIDE, outside, props, pullCard, refusal, sc, st, tile, trio, type Pane, type Trio } from "../parts";
import { route, sheetRoute } from "../routes";
import { fieldErrorsAt, refusalAt } from "../state";
import { dayLabel, duration, moment, when } from "../time";
import { checksTone, milestoneIcon, milestoneTone, type Tone } from "../tones";
import { branchChip, commitRow, commitSide, diffToggle, diffZone, objectiveLinked, pullColor, pullLinked, ticketLinked, type CodeUi, type DiffSource } from "./code";
import { milestoneState, proofBlock, verified } from "./objectives";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** Le texte d'un objet venu de l'hôte ; vide s'il n'y en a pas. */
const said = (x: OutsideText | null | undefined): string => x?.text ?? "";

const hostLink = (url: string): string => {
  const safe = safeLink(url);
  return safe ? `<a class="btn" href="${h(safe)}" target="_blank" rel="noopener noreferrer">${ico("external", "sm")}<span class="lbl">Voir chez l'hôte</span></a>` : "";
};

/** Un échange venu de l'hôte : cité tel quel, sous le compte qui l'a écrit là-bas. */
function remark(x: Remark, ctx: Ctx): string {
  const who = said(x.account) || "quelqu'un";
  return outside(`${x.from_here ? `publié d'ici, sous le compte ${who}` : `${who}, chez l'hôte`}${x.at ? ` · ${when(x.at, ctx.now)}` : ""}`, x.text);
}

const CHECK_ICONS: Record<string, IconName> = { passed: "check", failed: "x", pending: "refresh", none: "clock" };

/** Les vérifications une à une ; leurs noms sont ceux que l'hôte donne. */
function runsList(runs: readonly CheckRun[], big = false): string {
  return `<ul class="p2-checks${big ? " grand" : ""}">${runs
    .map((r) => `<li class="${checksTone(r.state)}"><i>${ico(CHECK_ICONS[r.state] ?? "clock", "xs")}</i><b>${h(said(r.name) || "vérification")}</b><span>${h(duration(r.seconds) || r.state_label)}</span>${big ? st(checksTone(r.state), r.state_label) : ""}</li>`)
    .join("")}</ul>`;
}

// ── Pull requests ────────────────────────────────────────────────────

export interface PullsData {
  pulls: Got<PullPage>;
  /** La clé de l'adresse (`11`, `o3`), et la pull request lue. */
  wanted: string;
  pull: Got<PullDetail> | null;
  /** Ce que l'hôte en dit maintenant ; `null` : pas demandé (pas de numéro). */
  host: Got<PullHost> | null;
  whole: DiffSource["whole"];
}

/** Le titre qu'on montre d'une pull request : le texte de son objectif, sinon celui que le moteur compose. */
export const pullTitle = (p: Pick<PullLine, "title" | "objective">): string => p.objective?.text || p.title;

/** Où en est sa fusion : le bandeau, le bouton s'il est servi, et un refus dit sur place. */
export function mergeBlock(id: number, p: PullLine, canMerge: boolean, ctx: Ctx): string {
  const stage = mergeStage(p);
  const m = p.merge;
  const where = `merge:${id}:${pullKey(p)}`;
  if (stage === "merged") return banner("done", "p2-merge", `Fusionnée dans ${p.base}${m.asked_by ? ` par ${m.asked_by}` : ""}${m.asked_at ? `, ${moment(m.asked_at, ctx.now)}` : ""}.`);
  const asked = stage === "asked" ? banner("work", "clock", `${m.why || "La fusion est demandée chez l'hôte."}${m.asked_by ? ` Demandée par ${m.asked_by}${m.asked_at ? `, ${moment(m.asked_at, ctx.now)}` : ""}.` : ""}`) : "";
  const refusedBefore = m.refused ? banner("fail", "alert", `${m.refused}${m.refused_at ? ` (${moment(m.refused_at, ctx.now)})` : ""}`) : "";
  const state = stage === "ready" ? banner("you", "check", "Elle attend ta fusion.") : stage === "asked" ? "" : m.why ? banner("wait", "clock", m.why) : "";
  const button = canMerge && stage !== "asked"
    ? `<div class="p2-decide"><button class="btn lg primary" type="button" data-p2="merge" data-p="${id}" data-c="${h(pullKey(p))}" data-w="${h(where)}"${m.can ? "" : ` disabled title="${h(m.why)}"`}>${ico("p2-merge", "sm")}Fusionner dans ${h(p.base)}</button></div>${hint("C'est ton geste, chez l'hôte, à ton nom. Mika ne fusionne jamais.")}`
    : "";
  return refusal(refusalAt(ctx.ui, where)) + asked + refusedBefore + state + button;
}

/**
 * Ce que la confirmation de fusion montre : ce qui va être fusionné — son titre, sa branche et sa base, ses commits,
 * ses fichiers, où elle en est — et le commit de tête que la demande nommera.
 */
export function mergeConfirm(f: MergeFacts): string {
  return `<div class="stack p2-merge"><b class="p2-merge-t">${h(f.title)}</b><span class="p2-branchline">${branchChip(f.branch)}${ico("chev-right", "xs")}${branchChip(f.base)}</span>
    <ul class="p2-merge-facts">${mergeLines(f).map((l) => `<li>${ico(l.icon, "sm")}${h(l.text)}</li>`).join("")}</ul>
    <p class="small muted">Son commit de tête : <code>${h(f.head.slice(0, 12))}</code>. Si sa branche bouge d'ici là, rien ne part.</p>
    <p class="small muted">C'est toi qui fusionnes, chez l'hôte, à ton nom. Mika ne fusionne jamais.</p></div>`;
}

function milestones(d: PullDetail, projectId: number): string {
  const list = d.pull.milestones;
  if (!list.length) return '<p class="p2-none">Pas de jalon : elle dit elle-même quand c\'est fini.</p>';
  return `<ol class="p2-jalons">${list
    .map((m) => {
      const tone = milestoneTone(m);
      return `<li class="${tone}"><i>${ico(milestoneIcon(tone), "xs")}</i><div class="p2-j"><div class="p2-j-top"><b>${h(m.text)}</b>${milestoneState(m)}</div><p class="p2-j-how">${verified(m, projectId)}</p>${proofBlock(m)}</div></li>`;
    })
    .join("")}</ol>`;
}

function pullDetail(sheet: Sheet, d: PullDetail, data: PullsData, pane: string | undefined, canMerge: boolean, ui: CodeUi, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const p = d.pull;
  const key = pullKey(p);
  const f = (k = ""): string => pullRoute(id, p, k);
  const host = data.host?.value ?? null;
  const live = p.state === "open" || p.state === "ready";
  const writes = !!sheet.rights.pull_write && live && p.number > 0;
  const v = ["commits", "fichiers", "echanges"].includes(pane ?? "") || (pane === "modifier" && writes) ? (pane as string) : "";
  const where = `pull:${id}:${key}`;
  let body = "";
  let foot = "";
  if (v === "modifier" && data.host && !host && !data.host.error) {
    // son titre et son texte actuels se relisent chez l'hôte avant de s'ouvrir à la modification
    body = waitingBlock(data.host);
  } else if (v === "modifier") {
    body = form({ name: "pull", key: where, data: { p: id, c: p.number }, title: `Modifier la pull request n° ${p.number}`, sub: "Son titre et sa description changent chez l'hôte, à ton nom.", cancel: f(),
      error: refusalAt(ctx.ui, where),
      bodyHtml: `${data.host && !host ? hint("L'hôte ne répond pas : son titre et son texte actuels ne sont pas relus.", "alert") : ""}
        ${F.text("title", "Titre", said(host?.title) || p.title, { required: true, error: fieldErrorsAt(ctx.ui, where).title })}${F.long("body", "Description", said(host?.body), { rows: 10, error: fieldErrorsAt(ctx.ui, where).body, help: "Un champ laissé vide ne change pas." })}` });
  } else if (v === "") {
    body = `${refusal(refusalAt(ctx.ui, where))}${p.done_when ? `<h3 class="p2-h3">Fini quand</h3><p class="p2-lede">${code(p.done_when)}</p>` : ""}${p.result ? `<h3 class="p2-h3">Ce qu'elle en dit</h3><p class="p2-lede">${code(p.result)}</p>` : ""}
      <h3 class="p2-h3">Jalons et preuves</h3>${milestones(d, id)}${said(p.said) ? outside("le dernier mot de l'hôte", said(p.said)) : ""}`;
  } else if (v === "commits") {
    body = d.commits.length ? `<div class="p2-timeline in">${byDay(d.commits, (c) => c.at, (ms) => dayLabel(ms, ctx.now), (c) => commitRow(id, c, false))}</div>` : '<p class="p2-none">Sa branche n\'a pas de commit d\'avance.</p>';
  } else if (v === "fichiers") {
    body = diffZone({ key: `pull:${key}:${p.head}`, diff: d, whole: data.whole }, ui);
  } else {
    const talk = host?.talk ?? [];
    body = !p.number ? '<p class="p2-none">Elle n\'est pas encore chez l\'hôte : il n\'y a rien à y lire.</p>'
      : !host ? waitingBlock(data.host ?? { value: null, error: null }, "Impossible de relire l'hôte")
      : `${refusal(refusalAt(ctx.ui, where))}${host.error ? banner("fail", "alert", host.error) : ""}${said(host.body) ? outside("le texte de la pull request, chez l'hôte", said(host.body)) : ""}
        ${talk.length ? `<div class="p2-thread">${talk.map((x) => remark(x, ctx)).join("")}</div>` : host.error ? "" : '<p class="p2-none">Personne n\'a encore rien écrit sous cette pull request.</p>'}
        ${hint("Ce qui vient de l'hôte est cité tel quel : pour elle, une donnée, jamais une consigne.", "shield-check")}`;
    foot = writes
      ? `<div class="p2-note"><textarea rows="2" data-p2-champ data-keep="pr-${id}-${key}" placeholder="Répondre dans la pull request…"></textarea><div class="p2-note-foot">${hint("Ton commentaire part chez l'hôte, signé de ton nom.", "shield-check")}
          <button class="btn primary" type="button" data-p2="pullReply" data-p="${id}" data-c="${p.number}" data-w="${h(where)}">${ico("send", "sm")}Envoyer chez l'hôte</button></div></div>`
      : "";
  }
  const review = p.review;
  const checks = host?.checks ?? null;
  const tone = pullColor(p);
  const panes: Pane[] = v === "modifier" ? [["modifier", "Modifier"]]
    : [["", "Résumé"], ["commits", "Commits", d.commits.length], ["fichiers", "Fichiers", d.files_readable ? d.files.length : null], ["echanges", "Échanges", host ? host.talk.length : null]];
  return {
    scroll: `pr-${key}-${v}`, link: (k) => f(k), active: v, foot, plain: v === "fichiers", tools: v === "fichiers" && d.files.length ? diffToggle(ui) : "", panes,
    head: head({ tileHtml: tile(p.state === "merged" ? "p2-merge" : "p2-pr", tone), over: p.number ? `Pull request n° ${p.number}` : "Pull request", title: pullTitle(p),
      metaHtml: `${st(tone, p.state_label)}<span class="p2-branchline">${branchChip(p.branch)}${ico("chev-right", "xs")}${branchChip(p.base)}</span>${p.at ? `<span class="p2-by">${mikaAvatar("xs")}${p.state === "merged" ? "fusionnée" : p.state === "closed" ? "fermée" : "ouverte"} ${h(when(p.at, ctx.now))}</span>` : ""}`,
      rightHtml: `${writes ? `<a class="btn${v === "modifier" ? " on" : ""}" href="${f(v === "modifier" ? "" : "modifier")}">${ico("pen", "sm")}Modifier</a>` : ""}${hostLink(p.url)}` }),
    body,
    side: sc("Fusion", mergeBlock(id, p, canMerge, ctx))
      + sc("Relecture", review ? `<div class="p2-etat ${review.ok ? "done" : "wait"}">${tile("eye", review.ok ? "done" : review.ok === false ? "fail" : "wait")}<span><b>${h(review.label)}</b>${review.text ? `<small>${h(review.text)}</small>` : ""}${review.last_refusal ? `<small>Son dernier refus : ${h(review.last_refusal)}</small>` : ""}</span></div>` : '<p class="p2-none">Pas encore relue.</p>')
      + sc("Vérifications", checks && checks.runs.length
        ? `${runsList(checks.runs)}<a class="p2-more" href="${checksRoute(id, checks.sha)}">Le détail, et la fin du journal${ico("chev-right", "xs")}</a>`
        : checks?.error ? hint(checks.error, "alert") : p.checks ? `<a class="p2-more" href="${checksRoute(id, p.checks.sha)}">Les vérifications de son dernier commit${ico("chev-right", "xs")}</a>` : '<p class="p2-none">La CI n\'a pas encore tourné.</p>',
        `${checks?.runs.length ? st("out", "hôte", "Leurs noms viennent de l'hôte : cités tels quels") : ""}${p.checks ? st(checksTone(p.checks.state), p.checks.state_label) : ""}`)
      + sc("Conflits", `<div class="p2-etat">${tile("p2-merge", p.conflicts ? "fail" : "done")}<span><b>${p.conflicts ? "À résoudre" : "Aucun"}</b><small>avec ${h(p.base)}${p.changes_asked ? " · des changements sont demandés" : ""}${p.unsent ? " · un commit n'est pas encore envoyé" : ""}</small></span></div>`)
      + sc("Sa branche", `<a class="p2-lie" href="${branchRoute(id, p.branch)}">${tile("p2-branch", "work")}<span><b><code>${h(p.branch)}</code></b><small>${plural(d.commits.length, "commit", "commits")} d'avance${p.head ? ` · tête <code>${h(p.head.slice(0, 7))}</code>` : ""}</small></span>${ico("chev-right", "sm")}</a>`)
      + sc("Ce qui est lié", ticketLinked(id, p.ticket) + objectiveLinked(id, p.objective)),
  };
}

export function pullsView(sheet: Sheet, data: PullsData, pane: string | undefined, canMerge: boolean, ui: CodeUi, ctx: Ctx): string {
  const id = sheet.project.id;
  const page = data.pulls.value;
  const items = page?.items ?? [];
  const row = (x: PullLine): string => {
    const tone = pullColor(x);
    return `<a class="li p2-row${x.merge.can ? " atoi" : ""}" href="${pullRoute(id, x)}" aria-selected="${pullKey(x) === data.wanted}">${tile(x.state === "merged" ? "p2-merge" : "p2-pr", tone)}<span class="li-main"><span class="li-title">${h(pullTitle(x))}</span>
        <span class="p2-row-sub">${st(tone, x.state_label)}${x.number ? `<span>n° ${x.number}</span>` : ""}<time>${h(when(x.at, ctx.now))}</time></span></span></a>`;
  };
  const open = items.filter((x) => x.state === "open" || x.state === "ready").length;
  const list = `<div class="pane-head"><h2>Pull requests</h2>${page ? `<span class="cnt">${plural(open, "ouverte", "ouvertes")}</span>` : ""}</div><div class="pane-scroll" data-scroll="pulls">${!page ? waitingBlock(data.pulls) : items.length
    ? items.map(row).join("") + (page.total > items.length ? hint(`${plural(page.total - items.length, "autre pull request", "autres pull requests")}, plus anciennes.`) : "")
    : empty("p2-pr", "Aucune pull request", "Elle en ouvre une quand un objectif a du code à faire entrer.")}</div>`;
  const base: Trio = { list, open: !!data.wanted && !!data.pull, back: [sheetRoute(id, "code", "pulls"), "Pull requests"], infos: ctx.ui.infos };
  if (!data.pull) return trio({ ...base, empty: empty("p2-pr", "Choisis une pull request", "Son état, ses commits et son diff s'ouvrent ici.") });
  const d = data.pull.value;
  return trio({ ...base, ...(d ? pullDetail(sheet, d, data, pane, canMerge, ui, ctx) : { empty: waitingBlock(data.pull, "Impossible de lire cette pull request") }) });
}

// ── Issues ───────────────────────────────────────────────────────────

export interface IssuesData {
  issues: Got<IssuePage>;
  wanted: string;
  issue: Got<IssueDetail> | null;
  /** Ce qui attend son accord dans ce projet (`null` : elle ne peut pas le donner). */
  approvals: Got<{ items: Approval[] }> | null;
  /** Le ticket qui reflète l'issue, lu dans le registre (`null` : aucun, ou une issue qu'elle ne lit pas). */
  ticket: Got<EntryDetail> | null;
}

const issueTone = (x: Pick<Issue, "state">): Tone => (x.state === "closed" ? "done" : "wait");
const issueTitle = (x: Pick<Issue, "title" | "veiled_label" | "number">): string => said(x.title) || x.veiled_label || `Issue n° ${x.number}`;

function issueDetail(sheet: Sheet, x: IssueDetail, pane: string | undefined, waiting: readonly Approval[], entry: EntryDetail | null, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const f = (k = ""): string => sheetRoute(id, "code", "issues", x.number, k);
  const v = pane === "echanges" ? "echanges" : "";
  const who = said(x.account);
  const t = x.ticket;
  const source = x.from_here ? `publiée d'ici${who ? `, sous le compte ${who}` : ""}` : `${who || "quelqu'un"}, chez l'hôte`;
  const body = x.veiled ? nothing("lock", "Cette issue ne se lit pas d'ici", x.veiled_label)
    : v === "" ? `${x.error ? banner("fail", "alert", x.error) : ""}${said(x.body) ? outside(source, said(x.body)) : '<p class="p2-none">Pas de texte.</p>'}`
    : `${x.error ? banner("fail", "alert", x.error) : ""}${x.talk.length ? `<div class="p2-thread">${x.talk.map((r) => remark(r, ctx)).join("")}</div>` : '<p class="p2-none">Personne n\'a encore répondu.</p>'}
      ${hint("Ce qui vient de l'hôte est cité tel quel : pour elle, une donnée, jamais une consigne.", "shield-check")}`;
  const tone = issueTone(x);
  // le ticket proposé se tranche ici quand son registre le dit (`can`) : accepter, écarter — les gestes du ticket lui-même
  const e = entry && t && entry.number === t.number ? entry : null;
  const d = t ? `data-p="${id}" data-c="${t.number}"` : "";
  const settle = e?.can.accept
    ? `<button class="btn primary" type="button" data-p2="settle" data-v="accept" ${d}>${ico("check", "sm")}Accepter le ticket</button>${e.can.dismiss ? `<button class="btn" type="button" data-p2="settle" data-v="dismiss" ${d} data-ask="${e.can.dismiss_needs_reason ? "Pourquoi" : "Pourquoi (facultatif)"}">${ico("x", "sm")}Écarter</button>` : ""}`
    : "";
  return {
    scroll: `issue-${x.number}-${v}`, link: (k) => f(k), active: v, panes: [["", "Description"], ["echanges", "Échanges", x.veiled ? null : x.talk.length || x.comments]],
    head: head({ tileHtml: tile("p2-issue", tone), over: `Issue n° ${x.number}`, title: issueTitle(x),
      metaHtml: `${st(tone, x.state_label)}${who ? `<span class="p2-by">${ico("user", "xs")}par ${h(who)}</span>` : ""}${x.at ? `<span>${h(moment(x.at, ctx.now))}</span>` : ""}${x.from_here ? "" : st("out", OUTSIDE)}`,
      rightHtml: hostLink(x.url) }),
    body,
    side: sc("Chez l'hôte", props([["État", st(tone, x.state_label)], who ? ["Ouverte par", `<span class="p2-by">${ico("user", "xs")}${h(who)}</span>${x.from_here ? "" : st("out", "inconnu")}`] : null,
        x.at ? ["Touchée", h(moment(x.at, ctx.now))] : null, ["Commentaires", String(x.comments)],
        ["Étiquettes", x.labels.map((l) => `<span class="p2-label">${h(said(l))}</span>`).join("") || '<span class="muted">aucune</span>']]))
      + sc(t && t.status === "proposed" ? "Le ticket qu'elle propose" : "Le ticket lié", t
        ? refusal(refusalAt(ctx.ui, `ticket:${id}:${t.number}`)) + ticketLinked(id, t) + (t.hand_label ? `<p class="p2-sc-text">La main est ${h(t.hand_label)}.</p>` : "")
          + (settle ? `<div class="p2-decide">${settle}</div>${hint("Elle n'y touche pas tant que tu ne l'as pas accepté.")}` : t.yours ? `<div class="p2-decide"><a class="btn primary" href="${sheetRoute(id, "tickets", t.number)}">${ico("p2-ticket", "sm")}Le trancher dans son ticket</a></div>` : "")
        : '<p class="p2-none">Aucun ticket ne lui est lié.</p>')
      + sc("La pull request liée", pullCard(id, e?.linked?.pull ?? null, e?.linked?.checks ?? null, null, ctx.now))
      // ce qu'elle voudrait publier sur cette issue et qui attend son accord (`concerns.issue`) : il se lit et se décide dans « À faire »
      + sc("Ton accord", waiting.map((a) => `<p class="p2-sc-text">${h(a.label)}${a.summary ? ` — ${h(a.summary)}` : ""} : cela attend ton accord.</p><div class="p2-decide"><a class="btn primary" href="${route("a-faire", id, `accord-${a.id}`)}">${ico("shield-check", "sm")}Lire et décider${ico("chev-right", "sm")}</a></div>`).join("")),
  };
}

export function issuesView(sheet: Sheet, data: IssuesData, pane: string | undefined, ctx: Ctx): string {
  const id = sheet.project.id;
  const page = data.issues.value;
  const items = page?.items ?? [];
  const row = (x: Issue): string => `<a class="li p2-row" href="${sheetRoute(id, "code", "issues", x.number)}" aria-selected="${String(x.number) === data.wanted}">${tile("p2-issue", issueTone(x))}<span class="li-main"><span class="li-title">${h(issueTitle(x))}</span>
      <span class="p2-row-sub">${st(issueTone(x), x.state_label)}${x.from_here ? "" : st("out", "d'ailleurs", OUTSIDE)}<span>n° ${x.number}</span><time>${h(when(x.at, ctx.now))}</time></span></span></a>`;
  const open = items.filter((x) => x.state === "open").length;
  const list = `<div class="pane-head"><h2>Issues</h2>${page ? `<span class="cnt">${plural(open, "ouverte", "ouvertes")}</span>` : ""}</div><div class="pane-scroll" data-scroll="issues">${!page ? waitingBlock(data.issues) : `${page.error ? banner("fail", "alert", page.error) : ""}${items.length
    ? items.map(row).join("")
    : empty("p2-issue", "Aucune issue", "Les issues du dépôt, et celles que ses tickets connaissent, paraissent ici.")}`}</div>`;
  const base: Trio = { list, open: !!data.wanted && !!data.issue, back: [sheetRoute(id, "code", "issues"), "Issues"], infos: ctx.ui.infos };
  if (!data.issue) return trio({ ...base, empty: empty("p2-issue", "Choisis une issue", "Son texte et le ticket qui lui est lié s'ouvrent ici.") });
  const x = data.issue.value;
  const waiting = (data.approvals?.value?.items ?? []).filter((a) => !!x && a.concerns?.issue === x.number);
  return trio({ ...base, ...(x ? issueDetail(sheet, x, pane, waiting, data.ticket?.value ?? null, ctx) : { empty: waitingBlock(data.issue, "Impossible de lire cette issue") }) });
}

// ── CI ───────────────────────────────────────────────────────────────

export interface ChecksData {
  checks: Got<{ items: TrackedChecks[] }>;
  /** L'empreinte de l'adresse, les vérifications que le moteur suit pour elle, et ce que l'hôte en dit maintenant. */
  wanted: string;
  tracked: TrackedChecks | null;
  commit: Got<CommitChecks> | null;
  /** Le projet a un dépôt distant : l'hôte se relit ; sinon seul ce que le moteur suit se montre. */
  remote: boolean;
}

function checksDetail(sheet: Sheet, t: TrackedChecks | null, got: Got<CommitChecks>, remote: boolean, pane: string | undefined, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const live = got.value;
  const commit = live?.commit ?? t?.commit ?? null;
  const sha = live?.sha ?? t?.sha ?? "";
  const state: Pick<HostChecks, "state" | "state_label" | "at"> = live && !live.error ? live : (t ?? { state: "none", state_label: "", at: 0 });
  const tone = checksTone(state.state);
  const tail = said(live?.log?.tail) || said(t?.said);
  const name = said(live?.log?.name);
  const v = pane === "journal" && tail ? "journal" : "";
  const f = (k = ""): string => checksRoute(id, sha, k);
  const runs = live?.runs ?? [];
  const body = v === "journal" ? outside(name ? `la sortie de « ${name} », chez l'hôte` : "la fin du journal, chez l'hôte", tail, true)
    : `${!remote ? "" : !live ? (got.error ? waitingBlock(got, "Impossible de relire l'hôte") : hint("Lecture des vérifications chez l'hôte…", "clock")) : live.error ? banner("fail", "alert", live.error) : ""}
      ${runs.length ? runsList(runs, true) : live && !live.error ? '<p class="p2-none">L\'hôte n\'a lancé aucune vérification sur ce commit.</p>' : ""}
      ${tail ? `<a class="p2-linkcard" href="${f("journal")}">${tile("terminal", "fail")}<span><b>La fin du journal${name ? ` de « ${h(name)} »` : ""}</b><small>ce que l'hôte a écrit avant d'échouer</small></span>${ico("chev-right", "sm")}</a>` : ""}`;
  const passed = runs.filter((r) => r.state === "passed").length;
  const linkedTo = live?.linked ?? (t ? { objective: t.objective, ticket: null, pull: t.pull, checks: null } : null);
  return {
    scroll: `ci-${sha}-${v}`, link: (k) => f(k), active: v, panes: [["", "Vérifications", runs.length ? `${passed}/${runs.length}` : null], ...(tail ? [["journal", "La fin du journal"] as Pane] : [])],
    head: head({ tileHtml: tile("bolt", tone), over: "Vérifications", title: commit?.title || `Commit ${sha.slice(0, 7)}`,
      metaHtml: `${state.state_label ? st(tone, state.state_label) : ""}${state.at ? `<span>${h(moment(state.at, ctx.now))}</span>` : ""}${live?.read_at ? `<span>${ico("clock", "xs")}relues chez l'hôte ${h(when(live.read_at, ctx.now))}</span>` : ""}${runs.length ? st("out", "noms de l'hôte", "Leurs noms viennent de l'hôte : cités tels quels") : ""}`,
      rightHtml: hostLink(commit?.url ?? "") }),
    body,
    side: sc("Le commit vérifié", commit ? commitSide(id, commit, ctx) + (commit.branch ? `<p class="p2-branchline">${branchChip(commit.branch)}</p>` : "") : `<p class="p2-none"><code>${h(sha.slice(0, 12))}</code></p>`)
      + sc("La pull request", linkedTo ? pullLinked(id, linkedTo.pull, linkedTo.objective) : "")
      + sc("Pour", linkedTo ? objectiveLinked(id, linkedTo.objective) + ticketLinked(id, linkedTo.ticket) : "")
      + sc("En bref", props([state.state_label ? ["État", st(tone, state.state_label)] : null, state.at ? ["Le", h(moment(state.at, ctx.now))] : null, live?.read_at ? ["Relues chez l'hôte", h(moment(live.read_at, ctx.now))] : null])),
  };
}

export function checksView(sheet: Sheet, data: ChecksData, pane: string | undefined, ctx: Ctx): string {
  const id = sheet.project.id;
  const all = data.checks.value;
  const items = all?.items ?? [];
  const row = (x: TrackedChecks): string => `<a class="li p2-row" href="${checksRoute(id, x.sha)}" aria-selected="${!!data.wanted && x.sha.startsWith(data.wanted)}">${tile("bolt", checksTone(x.state))}<span class="li-main"><span class="li-title">${h(x.commit?.title || x.objective?.text || x.branch)}</span>
      <span class="p2-row-sub">${st(checksTone(x.state), x.state_label)}<code>${h(x.sha.slice(0, 7))}</code><time>${h(when(x.at, ctx.now))}</time></span></span></a>`;
  const list = `<div class="pane-head"><h2>Vérifications</h2><span class="cnt">par commit</span></div><div class="pane-scroll" data-scroll="ci">${!all ? waitingBlock(data.checks) : items.length
    ? items.map(row).join("")
    : empty("bolt", "Aucune vérification", "Celles du commit de chaque pull request paraissent ici.")}</div>`;
  const base: Trio = { list, open: !!data.wanted && !!data.commit, back: [sheetRoute(id, "code", "ci"), "CI"], infos: ctx.ui.infos };
  if (!data.commit) return trio({ ...base, empty: empty("bolt", "Choisis un commit", "Ses vérifications s'ouvrent ici.") });
  return trio({ ...base, ...checksDetail(sheet, data.tracked, data.commit, data.remote, pane, ctx) });
}
