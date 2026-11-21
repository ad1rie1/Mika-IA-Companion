/**
 * L'onglet Code d'une fiche, ce que lit l'atelier (pur) : **Fichiers** (le choix de la branche, l'arborescence un
 * dossier à la fois, le fichier, son dernier commit et son historique), **Commits** (la ligne de temps par jour, le
 * commit et son diff unifié ou côte à côte, ses fichiers changés en sommaire) et **Branches** (le tableau pleine
 * largeur, le panneau d'une branche). La forme est celle de la maquette (`maquette/ecrans/projets2-code.js`).
 *
 * Le contenu d'un fichier et les lignes d'un diff ne sont jamais dans ce HTML : la vue pose un emplacement
 * (`paint.ts::slot`), rempli après le dessin par insertion de texte. Un commit venu du dépôt distant (`outside`) se
 * dit venu d'ailleurs ; ses mots sont échappés comme tout le reste.
 */
import type { Blob, Branch, BranchDetail, BranchList, ChecksBrief, CodeSummary, Commit, CommitDetail, CommitPage, Diff, DiffFile, Linked, LinkedObjective, LinkedTicket, PullBrief, Tree } from "../../../api/projectCode";
import type { Sheet } from "../../../api/projects";
import { mikaAvatar } from "../../../mika/face";
import { h } from "../../../shell/dom";
import { ico } from "../../../shell/icons";
import { branchRoute, byFolder, checksRoute, commitRoute, fileRoute, isMarkdown, languageOf, pullRoute, repoLink, sizeWords } from "../codeparts";
import { pageHtml } from "../docmd";
import { plural, safeLink } from "../gestures";
import { slot } from "../paint";
import { authorAvatar, banner, byDay, empty, head, hint, linked, nothing, OUTSIDE, outside, props, sc, st, tile, trio, type Trio } from "../parts";
import { sheetRoute } from "../routes";
import { dayLabel, moment, when } from "../time";
import { checksTone, objectiveTone, pullTone, ticketTone, type Tone } from "../tones";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** L'état de l'onglet, gardé par son point d'entrée (`code.ts`). */
export interface CodeUi {
  /** Le diff : côte à côte, sinon unifié. */
  side: boolean;
  /** Commits : la branche filtrée (vide : toutes). */
  commitsRef: string;
  /** Fichiers : les dossiers ouverts, par `branche|chemin`. */
  open: Set<string>;
  /** Les fichiers d'un diff coupé qu'on a demandés en entier, par `clé du diff|chemin`. */
  whole: Set<string>;
  /** Fichiers : un fichier Markdown se lit en source (sinon rendu). */
  mdSource: boolean;
}

// ── Les morceaux partagés par les six vues ───────────────────────────

export const branchChip = (name: string): string => `<span class="p2-br">${ico("p2-branch", "xs")}${h(name)}</span>`;

export const plusMinus = (insertions: number, deletions: number): string => `<span class="p2-pm"><b class="plus">+${insertions}</b><b class="moins">−${deletions}</b></span>`;

/** Qui a signé un commit : elle, ou quelqu'un d'autre (un commit venu du dépôt distant). */
export function signer(c: Pick<Commit, "author_kind" | "author">, ctx: Ctx, size: "xs" | "sm" = "xs"): string {
  return c.author_kind === "self" ? mikaAvatar(size) : authorAvatar("host", c.author, ctx.me, size);
}

/** Un commit dans la ligne de temps : son message, son empreinte, sa branche, ce qui lui est lié, ses comptes. */
export function commitRow(id: number, c: Commit, picked: boolean): string {
  const about = c.ticket ? `#${c.ticket}` : c.objective ? `obj. ${c.objective}` : "";
  return `<a class="p2-cm" href="${commitRoute(id, c)}" aria-selected="${picked}"><i class="${c.merge ? "done" : ""}"></i>
    <span class="li-title">${h(c.title)}</span><span class="p2-row-sub"><code>${h(c.short)}</code>${c.branch ? branchChip(c.branch) : ""}${about ? `<span>${about}</span>` : ""}${c.outside ? st("out", "ailleurs", OUTSIDE) : ""}${c.merge && !c.files ? "<time>fusion</time>" : plusMinus(c.insertions, c.deletions)}</span></a>`;
}

/** Un commit dans le panneau : qui, son message, son empreinte, quand. */
export function commitSide(id: number, c: Commit, ctx: Ctx): string {
  return `<a class="p2-lie" href="${commitRoute(id, c)}">${signer(c, ctx)}<span><b>${h(c.title)}</b><small><code>${h(c.short)}</code> · ${h(when(c.at, ctx.now))}</small></span></a>`;
}

export function objectiveLinked(id: number, o: LinkedObjective | null): string {
  if (!o) return "";
  const tone = objectiveTone(o.status);
  return linked(sheetRoute(id, "objectifs", `${o.kind === "constant" ? "m" : "o"}${o.id}`), "p2-target", tone, o.text || `Objectif n° ${o.id}`, `${o.kind === "constant" ? "mission" : "objectif"} n° ${o.id}`, st(tone, o.status_label));
}

export function ticketLinked(id: number, t: LinkedTicket | null): string {
  if (!t) return "";
  const tone = ticketTone(t);
  return linked(sheetRoute(id, "tickets", t.number), "p2-ticket", tone, t.title || t.veiled_label || `Ticket #${t.number}`, `#${t.number}`, st(tone, t.status_label));
}

/** Les points d'une pull request : sa CI et sa relecture, avec les mots du serveur. */
export function pullDots(p: Pick<PullBrief, "checks" | "review">): string {
  return `<span class="p2-dots">${p.checks ? `<span title="${h(p.checks.state_label)}"><i class="${checksTone(p.checks.state)}"></i>CI</span>` : ""}${p.review ? `<span><i class="${p.review.ok ? "done" : p.review.ok === false ? "fail" : "wait"}"></i>${h(p.review.label)}</span>` : ""}</span>`;
}

/** La couleur d'une pull request : celle de son état ; ouverte avec une CI en échec, elle le montre. */
export function pullColor(p: Pick<PullBrief, "state" | "checks">): Tone {
  return p.state === "open" && p.checks?.state === "failed" ? "fail" : pullTone(p.state);
}

/** Une pull request liée, avec son statut. `title` : le texte de son objectif, quand on le sait. */
export function pullLinked(id: number, p: PullBrief | null, objective: LinkedObjective | null = null): string {
  if (!p) return "";
  const tone = pullColor(p);
  return `<a class="p2-lie haut" href="${pullRoute(id, { number: p.number, objective })}">${tile(p.state === "merged" ? "p2-merge" : "p2-pr", tone)}<span><b>${h(objective?.text || p.title)}</b>
    <small>${p.number ? `n° ${p.number} · ` : ""}<code>${h(p.branch)}</code></small><span class="p2-lie-etat">${st(tone, p.state_label)}${p.state === "open" || p.state === "ready" ? pullDots(p) : ""}</span></span></a>`;
}

export function checksLinked(id: number, c: ChecksBrief | null, now: number): string {
  if (!c) return "";
  const tone = checksTone(c.state);
  return linked(checksRoute(id, c.sha), "bolt", tone, "Vérifications", `<code>${h(c.sha.slice(0, 7))}</code>${c.at ? ` · ${h(when(c.at, now))}` : ""}`, st(tone, c.state_label));
}

/** Ce qui est lié à un commit ou à une branche : l'objectif, son ticket, sa pull request, ses vérifications. */
export function linkedHtml(id: number, l: Linked, now: number): string {
  return objectiveLinked(id, l.objective) + ticketLinked(id, l.ticket) + pullLinked(id, l.pull, l.objective) + checksLinked(id, l.checks, now);
}

/** Le chemin d'un fichier, segment par segment. */
export function crumbs(path: string): string {
  const parts = path.split("/");
  return `<code>${parts.map((x, i) => (i === parts.length - 1 ? `<b>${h(x)}</b>` : `${h(x)}<i>/</i>`)).join("")}</code>`;
}

// ── Un diff ──────────────────────────────────────────────────────────

/** D'où vient un diff (`commit:<empreinte>`, `pull:<n>:<tête>`), et ses fichiers relus en entier. */
export interface DiffSource {
  key: string;
  diff: Diff;
  /** Un fichier coupé, relu seul : `null` tant qu'il n'est pas là. */
  whole: (path: string) => DiffFile | null;
}

export function diffToggle(ui: CodeUi): string {
  return `<div class="seg p2-diffmode" title="La forme du diff"><button type="button" data-p2="codeDiffMode" data-c="unified" aria-pressed="${!ui.side}">${ico("p2-unifie", "sm")}Unifié</button><button type="button" data-p2="codeDiffMode" data-c="side" aria-pressed="${ui.side}">${ico("p2-cote", "sm")}Côte à côte</button></div>`;
}

function fileSection(src: DiffSource, f: DiffFile, i: number, ui: CodeUi): string {
  const wanted = ui.whole.has(`${src.key}|${f.path}`);
  const whole = wanted ? src.whole(f.path) : null;
  const shown = whole ?? f;
  const lines = shown.hunks.reduce((n, x) => n + x.lines.length, 0);
  const mark = f.status === "modified" ? "" : `<span class="p2-new">${h(f.status_label)}</span>`;
  const body = f.hidden ? `<p class="p2-none">${h(f.why || "Un fichier caché : son diff ne s'affiche pas.")}</p>`
    : f.binary ? '<p class="p2-none">Un fichier binaire : son diff ne s\'affiche pas.</p>'
    : shown.hunks.length ? slot(`${src.key}|${f.path}|${ui.side ? "cote" : "unifie"}|${lines}`, { kind: "diff", file: shown, side: ui.side })
    : "";
  const more = shown.cut && !f.hidden && !f.binary
    ? `<p class="p2-none">${shown.hunks.length ? "Ce fichier est coupé : la suite n'est pas affichée." : "Ses passages ne sont pas affichés : le diff est trop long."}
        <button class="btn sm" type="button" data-p2="codeWhole" data-k="${h(src.key)}" data-c="${h(f.path)}"${wanted ? " disabled" : ""}>${wanted ? "Lecture…" : "Lire ce fichier en entier"}</button></p>`
    : "";
  return `<section class="p2-file" id="p2-f${i}"><header class="p2-fh">${ico("file", "sm")}<code>${h(f.path)}</code>${mark}${plusMinus(f.insertions, f.deletions)}</header>${body}${more}</section>`;
}

/** Les fichiers d'un diff, l'un sous l'autre ; sans le droit sur ses fichiers, les mots du serveur. */
export function diffZone(src: DiffSource, ui: CodeUi, introHtml = ""): string {
  const d = src.diff;
  const body = !d.files_readable ? nothing("lock", "Ses fichiers ne te sont pas ouverts", d.files_why)
    : d.files.length ? `${d.cut ? banner("wait", "info", d.cut_label) : ""}<div class="p2-diffs">${d.files.map((f, i) => fileSection(src, f, i, ui)).join("")}</div>`
    : '<p class="p2-none">Aucun fichier n\'y change.</p>';
  return `<div class="p2-diffzone">${introHtml}${body}</div>`;
}

/** Les fichiers changés, par dossier, avec leurs lignes ajoutées et retirées : le sommaire du diff. */
export function filesSummary(d: Diff, link: ((index: number) => string) | null = null): string {
  if (!d.files_readable || !d.files.length) return "";
  return `<p class="p2-sc-sum">${plural(d.files.length, "fichier", "fichiers")}${plusMinus(d.insertions, d.deletions)}</p><div class="p2-ftree">${byFolder(d.files)
    .map((g) => `${g.folder ? `<span class="p2-fdir">${ico("folder", "sm")}${h(g.folder)}</span>` : ""}${g.files
      .map(({ file, index }) => {
        const inner = `${ico("file", "sm")}<span>${h(file.path.slice(file.path.lastIndexOf("/") + 1))}</span>${file.status === "modified" ? "" : `<i class="p2-new">${h(file.status_label)}</i>`}${plusMinus(file.insertions, file.deletions)}`;
        return link ? `<a class="${g.folder ? "in" : ""}" href="${link(index)}">${inner}</a>` : `<button type="button" class="${g.folder ? "in" : ""}" data-p2="codeJump" data-c="p2-f${index}">${inner}</button>`;
      })
      .join("")}`)
    .join("")}</div>`;
}

// ── Fichiers ─────────────────────────────────────────────────────────

export interface FilesData {
  /** La branche (ou le commit) et le chemin de l'adresse. */
  ref: string;
  path: string;
  /** Un dossier lu : la racine, et ceux qu'on a ouverts. */
  tree: (dir: string) => Got<Tree>;
  /** Le fichier montré — celui de l'adresse, ou le README du dossier — et s'il est là par défaut. */
  file: string;
  home: boolean;
  blob: Got<Blob> | null;
}

function treeHtml(id: number, d: FilesData, ui: CodeUi, dir: string, depth: number): string {
  const got = d.tree(dir);
  if (!got.value) return depth ? `<span class="p2-node" style="--d:${depth}">${ico("refresh", "sm")}<span>${got.error ? "Illisible" : "Chargement…"}</span></span>` : waitingBlock(got, "Impossible de lire ses fichiers");
  const rows = got.value.items.map((e) => {
    if (e.kind !== "dir") return `<a class="p2-node" style="--d:${depth}" href="${fileRoute(id, d.ref, e.path)}" aria-selected="${e.path === d.file && !d.home}" title="${h(e.kind_label)}">${ico(e.kind === "file" ? "file" : "link", "sm")}<span>${h(e.name)}</span></a>`;
    const open = ui.open.has(`${d.ref}|${e.path}`);
    return `<button class="p2-node dir" style="--d:${depth}" type="button" data-p2="codeFold" data-r="${h(d.ref)}" data-c="${h(e.path)}" aria-expanded="${open}">${ico(open ? "chev-down" : "chev-right", "xs")}${ico("folder", "sm")}<span>${h(e.name)}</span></button>${open ? treeHtml(id, d, ui, e.path, depth + 1) : ""}`;
  });
  const hidden = got.value.hidden ? `<span class="p2-node p2-node-hidden" style="--d:${depth}" title="Un fichier ou un dossier caché ne se lit pas d'ici">${ico("eye-off", "sm")}<span>${plural(got.value.hidden, "entrée cachée", "entrées cachées")}</span></span>` : "";
  return rows.join("") + hidden || (depth ? "" : '<p class="p2-none">Ce dossier est vide.</p>');
}

/**
 * Un fichier Markdown du dépôt, rendu : par le rendu des pages de documentation (`docmd.ts`) — tout est échappé avant
 * d'être mis en forme, rien ne s'exécute, **aucune image n'est chargée** (un fichier du dépôt n'a pas d'espace d'images :
 * chacune se dit, sans être demandée), un lien relatif mène au fichier du même dépôt, à la même branche, un lien http(s)
 * s'ouvre à part, sans référent. Le contenu vient du dépôt : il peut être d'ailleurs.
 */
export function renderedFile(id: number, ref: string, path: string, text: string): string {
  return `<div class="p2-md p2-readme">${pageHtml(text, { link: (href) => { const to = repoLink(path, href); return to ? fileRoute(id, ref, to) : null; }, idPrefix: "f-" })}</div>`;
}

/** La bascule d'un fichier Markdown : rendu, ou sa source. */
function mdToggle(ui: CodeUi): string {
  return `<div class="seg p2-diffmode" title="La forme du fichier"><button type="button" data-p2="codeMdMode" data-c="rendu" aria-pressed="${!ui.mdSource}">${ico("eye", "sm")}Rendu</button><button type="button" data-p2="codeMdMode" data-c="source" aria-pressed="${ui.mdSource}">${ico("code", "sm")}Source</button></div>`;
}

export function filesView(sheet: Sheet, d: FilesData, ui: CodeUi, ctx: Ctx): string {
  const id = sheet.project.id;
  const list = `<div class="pane-head"><button class="btn sm p2-brpick" type="button" data-p2="codeBranch" data-p="${id}" data-c="files" data-r="${h(d.ref)}">${ico("p2-branch", "sm")}<span class="ellipsis">${h(d.ref)}</span>${ico("chev-down", "xs")}</button></div>
    <div class="pane-scroll p2-tree" data-scroll="arbre">${treeHtml(id, d, ui, "", 0)}</div>`;
  const base: Trio = { cls: "etroit", list, open: !!d.path, back: [fileRoute(id, d.ref), "Fichiers"], infos: ctx.ui.infos };
  const f = d.blob?.value;
  if (!d.file || !d.blob) return trio({ ...base, empty: empty("file", "Choisis un fichier", "Son contenu, son dernier commit et son historique s'ouvrent ici.") });
  if (!f || f.path !== d.file) return trio({ ...base, empty: waitingBlock(d.blob, "Impossible de lire ce fichier") });
  const url = safeLink(f.url);
  const md = f.readable && isMarkdown(f.path);
  const shown = md && !ui.mdSource;
  return trio({
    ...base, panes: [["", "Fichier"]], active: "", link: () => fileRoute(id, d.ref, d.path), plain: true, scroll: `fichier-${d.ref}-${f.path}${shown ? "-rendu" : ""}`,
    head: `<div class="pane-head p2-path">${crumbs(f.path)}${d.home ? '<span class="p2-kind">la page d\'accueil du dépôt</span>' : ""}<span class="grow"></span>${f.readable ? `<span class="cnt">${plural(f.lines, "ligne", "lignes")}</span>` : ""}${md ? mdToggle(ui) : ""}
      <button class="btn icon ghost sm" type="button" data-p2="copy" data-c="${h(f.path)}" title="Copier le chemin">${ico("copy", "sm")}</button></div>`,
    body: shown ? renderedFile(id, d.ref, f.path, f.text) : f.readable ? slot(`src|${f.sha}|${f.path}|${f.text.length}`, { kind: "source", text: f.text, path: f.path }, "p2-codewrap plein") : nothing("file", f.kind_label, f.why),
    side: sc("Dernier commit", f.last_commit ? commitSide(id, f.last_commit, ctx) : '<p class="p2-none">Aucun commit ne le touche sur cette branche.</p>')
      + sc("Le fichier", props([["Branche", branchChip(d.ref)], f.readable ? ["Lignes", String(f.lines)] : null, ["Poids", h(sizeWords(f.size))], ["Langage", h(f.readable ? languageOf(f.path) : f.kind_label)]])
        + (url ? `<a class="p2-more" href="${h(url)}" target="_blank" rel="noopener noreferrer">Voir chez l'hôte${ico("external", "xs")}</a>` : ""))
      + sc("Son historique", f.history.slice(1).map((c) => commitSide(id, c, ctx)).join(""), `<span class="cnt">${f.history_total}</span>`),
  });
}

// ── Commits ──────────────────────────────────────────────────────────

export interface CommitsData {
  page: Got<CommitPage>;
  /** Ceux des pages suivantes, déjà lus. */
  more: readonly Commit[];
  /** L'empreinte de l'adresse, et le commit lu. */
  wanted: string;
  commit: Got<CommitDetail> | null;
  whole: DiffSource["whole"];
}

function commitDetail(sheet: Sheet, d: CommitDetail, data: CommitsData, ui: CodeUi, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const c = d.commit;
  const rest = c.body.startsWith(c.title) ? c.body.slice(c.title.length).trim() : c.body.trim();
  const by = `<span class="p2-by">${signer(c, ctx)}${h(c.author)}</span>`;
  const intro = rest ? (c.outside ? outside("le message de ce commit, venu du dépôt distant", rest, true) : `<p class="p2-lede pre">${h(rest)}</p>`) : "";
  const url = safeLink(c.url);
  return {
    scroll: `commit-${c.sha}`, plain: true, panes: [["", "Diff"]], active: "", link: () => commitRoute(id, c), tools: d.files.length ? diffToggle(ui) : "",
    head: head({ tileHtml: tile(c.merge ? "p2-merge" : "p2-commit", c.merge ? "done" : ""), over: c.merge ? "Commit de fusion" : "Commit", title: c.title,
      metaHtml: `${by}<span>${h(moment(c.at, ctx.now))}</span>${c.branch ? branchChip(c.branch) : ""}${c.outside ? st("out", OUTSIDE) : ""}`,
      rightHtml: `<button class="p2-sha" type="button" data-p2="copy" data-c="${h(c.sha)}" title="Copier l'empreinte">${ico("copy", "xs")}<code>${h(c.sha.slice(0, 12))}</code></button>` }),
    body: diffZone({ key: `commit:${c.sha}`, diff: d, whole: data.whole }, ui, intro),
    side: sc("Fichiers changés", filesSummary(d))
      + sc("Le commit", props([["Auteur", by], ["Quand", h(moment(c.at, ctx.now))], c.branch ? ["Branche", branchChip(c.branch)] : null, ["Empreinte", `<code>${h(c.short)}</code>`]])
        + (url ? `<a class="p2-more" href="${h(url)}" target="_blank" rel="noopener noreferrer">Voir chez l'hôte${ico("external", "xs")}</a>` : ""))
      + sc("Ce qui est lié", linkedHtml(id, d.linked, ctx.now)),
  };
}

export function commitsView(sheet: Sheet, data: CommitsData, ui: CodeUi, ctx: Ctx): string {
  const id = sheet.project.id;
  const page = data.page.value;
  const items = [...(page?.items ?? []), ...data.more];
  const picked = data.commit?.value?.commit.sha ?? "";
  const rest = page ? page.total - items.length : 0;
  const list = `<div class="pane-head"><button class="btn sm p2-brpick" type="button" data-p2="codeBranch" data-p="${id}" data-c="commits">${ico("p2-branch", "sm")}<span class="ellipsis">${ui.commitsRef ? h(ui.commitsRef) : "Toutes les branches"}</span>${ico("chev-down", "xs")}</button>
      ${page ? `<span class="cnt">${plural(page.total, "commit", "commits")}</span>` : ""}</div>
    <div class="pane-scroll p2-timeline" data-scroll="commits">${!page ? waitingBlock(data.page) : items.length
      ? byDay(items, (c) => c.at, (ms) => dayLabel(ms, ctx.now), (c) => commitRow(id, c, c.sha === picked)) + (rest > 0 ? `<button class="p2-add" type="button" data-p2="codeCommitsMore" data-p="${id}">${ico("chev-down", "sm")}Afficher la suite (${rest})</button>` : "")
      : empty("p2-commit", "Aucun commit", "Elle n'a encore rien écrit dans ce dépôt.")}</div>`;
  const base: Trio = { list, open: !!data.wanted, back: [sheetRoute(id, "code", "commits"), "Commits"], infos: ctx.ui.infos };
  if (!data.commit) return trio({ ...base, empty: empty("p2-commit", "Choisis un commit", "Son message, ses fichiers et son diff s'ouvrent ici.") });
  const d = data.commit.value;
  return trio({ ...base, ...(d ? commitDetail(sheet, d, data, ui, ctx) : { empty: waitingBlock(data.commit, "Impossible de lire ce commit") }) });
}

// ── Branches ─────────────────────────────────────────────────────────

export interface BranchesData {
  summary: CodeSummary;
  branches: Got<BranchList>;
  /** Le nom de l'adresse, et la branche lue. */
  wanted: string;
  branch: Got<BranchDetail> | null;
}

const about = (b: Pick<Branch, "objective" | "ticket">): string =>
  b.ticket ? `<span class="p2-chip plain">${ico("p2-ticket", "xs")}Ticket #${b.ticket.number}</span>` : b.objective ? `<span class="p2-chip plain">${ico("p2-target", "xs")}Objectif n° ${b.objective.id}</span>` : '<span class="muted">—</span>';

function branchPanel(sheet: Sheet, got: Got<BranchDetail>, ctx: Ctx): string {
  const id = sheet.project.id;
  const d = got.value;
  if (!d) return waitingBlock(got, "Impossible de lire cette branche");
  const b = d.branch;
  const pull = b.pull;
  return sc(null, `<div class="p2-side-h">${tile("p2-branch", b.base ? "" : "work")}<span><b><code>${h(b.name)}</code></b><small>${b.base ? "la branche par défaut" : `${plural(b.ahead, "commit", "commits")} d'avance, ${b.behind} de retard`}</small></span></div>
      <div class="p2-decide row"><a class="btn" href="${fileRoute(id, b.name)}">${ico("folder", "sm")}Ses fichiers</a><button class="btn" type="button" data-p2="codeBranchCommits" data-p="${id}" data-c="${h(b.name)}">${ico("p2-commit", "sm")}Ses commits</button></div>`)
    + sc("Sa pull request", pullLinked(id, pull, b.objective) || (b.base ? "" : '<p class="p2-none">Pas encore de pull request.</p>'))
    + sc("Pour", objectiveLinked(id, b.objective) + ticketLinked(id, b.ticket))
    + sc(b.base ? "Son dernier commit" : "Ce qu'elle a d'avance", (b.base ? [b.head] : d.commits).map((c) => commitSide(id, c, ctx)).join(""), b.base ? "" : `<span class="cnt">${d.commits.length}</span>`)
    + sc("Fichiers changés", d.files_readable ? filesSummary(d, pull ? () => pullRoute(id, { number: pull.number, objective: b.objective }, "fichiers") : () => branchRoute(id, b.name)) : d.commits.length ? hint(d.files_why, "lock") : "");
}

export function branchesView(sheet: Sheet, data: BranchesData, ctx: Ctx): string {
  const id = sheet.project.id;
  const all = data.branches.value;
  if (!all) return waitingBlock(data.branches, "Impossible de lire ses branches");
  const items = all.items;
  const picked = items.find((b) => b.name === data.wanted) ?? (ctx.mobile ? null : (items.find((b) => !b.base) ?? items[0] ?? null));
  if (!items.length) return empty("p2-branch", "Aucune branche", "Ce dépôt n'a pas encore de branche.");
  if (ctx.mobile) {
    const rows = items.map((b) => `<a class="li p2-row" href="${branchRoute(id, b.name)}">${tile("p2-branch", b.base ? "" : "work")}<span class="li-main"><span class="li-title mono">${h(b.name)}</span><span class="p2-row-sub">${b.pull ? st(pullColor(b.pull), b.pull.state_label) : `<span>${b.base ? "par défaut" : "sans pull request"}</span>`}</span></span></a>`).join("");
    return trio({ list: `<div class="pane-scroll" data-scroll="branches">${rows}</div>`, open: !!data.wanted && !!picked, back: [sheetRoute(id, "code", "branches"), "Branches"], panes: [["", "Branche"]], active: "",
      link: () => branchRoute(id, data.wanted), scroll: "branche", body: picked && data.branch ? `<div class="p2-flat">${branchPanel(sheet, data.branch, ctx)}</div>` : "" });
  }
  const max = Math.max(1, ...items.map((b) => Math.max(b.ahead, b.behind)));
  const table = `<div class="p2-tablefull"><table class="tbl p2-branches"><thead><tr><th>Branche</th><th>Pour</th><th>Retard · avance sur ${h(all.base)}</th><th>Dernier commit</th><th>Pull request</th><th>CI</th></tr></thead><tbody>
      ${items.map((b) => `<tr class="${b === picked ? "on" : ""}" data-p2="codeRow" data-c="${branchRoute(id, b.name)}"><td><a class="p2-brname" href="${branchRoute(id, b.name)}">${ico("p2-branch", "sm")}<code>${h(b.name)}</code></a>${b.base ? '<span class="p2-kind">par défaut</span>' : ""}</td><td>${about(b)}</td>
          <td>${b.base ? '<span class="muted">—</span>' : `<span class="p2-div"><b>${b.behind}</b><span class="g"><i style="width:${(b.behind / max) * 100}%"></i></span><span class="d"><i style="width:${(b.ahead / max) * 100}%"></i></span><b>${b.ahead}</b></span>`}</td>
          <td><span class="p2-lastc"><code>${h(b.head.short)}</code><span class="ellipsis">${h(b.head.title)}</span><time>${h(when(b.head.at, ctx.now))}</time></span></td>
          <td>${b.pull ? `<span class="p2-prlink">${b.pull.number ? `<span class="p2-num">n° ${b.pull.number}</span>` : ""}${st(pullColor(b.pull), b.pull.state_label)}</span>` : '<span class="muted">—</span>'}</td>
          <td>${b.checks ? st(checksTone(b.checks.state), b.checks.state_label) : '<span class="muted">—</span>'}</td></tr>`).join("")}</tbody></table>
      ${data.summary.remote.by_pulls ? hint(`Elle ouvre une branche par objectif ou par ticket, et ne pousse jamais sur ${all.base} : tout y entre par une pull request que tu fusionnes.`) : ""}</div>`;
  return trio({ panes: [["", "Branches"]], active: "", link: () => sheetRoute(id, "code", "branches"), plain: true, scroll: "branches", body: table, side: picked && data.branch ? branchPanel(sheet, data.branch, ctx) : "" });
}
