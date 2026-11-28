/**
 * L'onglet Documentation d'une fiche (pur) : **Pages** (l'arborescence, la recherche, Nouvelle page ; une page lue,
 * son sommaire, sa dernière modification, ses versions ; son historique ; le cadre du mode Modifier, où l'éditeur se
 * pose après le dessin), **Images** (la grille, le panneau d'une image) et **Décisions** (la liste, le détail en
 * volets, ses formulaires). La forme est celle de la maquette (`maquette/ecrans/projets2-doc.js`).
 *
 * Aucune règle n'est refaite ici : Modifier, Nouvelle page, téléverser et retirer ne paraissent que si le serveur
 * donne d'écrire (`rights.write`, `can.write`) ; les gestes d'une décision sont ceux de son `can`. Le Markdown d'une
 * page passe par `docmd.ts` : échappé, sans rien qui s'exécute ni qui se charge d'ailleurs.
 */
import type { Decision, DecisionFull, DecisionList, DocFound, DocHistory, DocImage, DocPage, DocPageText, DocSpace, DocVersion, DocVersionText, Written } from "../../../api/projectDocs";
import { docImageUrl } from "../../../api/projectDocs";
import type { Sheet } from "../../../api/projects";
import { mikaAvatar } from "../../../mika/face";
import { personAvatar } from "../../../shared/kit";
import { h } from "../../../shell/dom";
import { ico } from "../../../shell/icons";
import { sizeWords } from "../codeparts";
import { headingsOf, pageHtml, type Heading } from "../docmd";
import { decisionOrder, decisionRoute, imageMarkdown, imageRoute, isDirty, optionLines, pageRoute, pageTree, type Draft, type PageMode, type TreeNode } from "../docparts";
import { plural } from "../gestures";
import { authorAvatar, banner, code, empty, F, form, head, hint, linked, nothing, props, refusal, sc, st, tile, trio, type Pane, type Trio } from "../parts";
import { sheetRoute } from "../routes";
import { fieldErrorsAt, refusalAt } from "../state";
import { moment, when } from "../time";
import { objectiveTone, type Tone } from "../tones";
import { crumbs } from "./code";
import { waitingBlock, type Ctx, type Got } from "./todo";

/** L'état de l'onglet, gardé par son point d'entrée (`documentation.ts`). */
export interface DocUi {
  /** Ce qui est cherché dans les pages. */
  query: string;
  /** Les dossiers repliés. */
  folded: Set<string>;
  /** L'historique : la version choisie (`null` : la dernière). */
  version: number | null;
}

/** Les types d'image qu'on propose de choisir : ceux que le serveur garde. */
export const IMAGE_KINDS = "image/png,image/jpeg,image/gif,image/webp";

// ── Qui a écrit ──────────────────────────────────────────────────────

/** Qui a écrit une version ou ajouté une image : une personne dans le navigateur, Mika, un outil par MCP. */
function writer(w: Written, ctx: Ctx): { avatar: (size: "xs" | "sm") => string; name: string; sub: string } {
  if (w.via === "mcp") return { avatar: (size) => `<span class="av ${size} p2-av-tool">${ico("plug", "xs")}</span>`, name: w.tool || w.author, sub: `${w.via_label}${w.tool ? ` · ${w.author}` : ""}` };
  if (w.author_kind === "self") return { avatar: (size) => mikaAvatar(size), name: w.author, sub: w.via_label };
  if (w.author_kind === "you") return { avatar: (size) => personAvatar(ctx.me || "toi", size), name: "Toi", sub: w.via_label };
  return { avatar: (size) => authorAvatar(w.author_kind, w.author, ctx.me, size), name: w.author, sub: w.via_label };
}

function signature(w: Written & { at: number }, word: string, ctx: Ctx): string {
  const a = writer(w, ctx);
  return `<div class="p2-sig">${a.avatar("sm")}<span><b>${h(a.name)}</b><small>${h(a.sub)}${a.sub ? " · " : ""}${h(moment(w.at, ctx.now))}</small>${word ? `<em>« ${h(word)} »</em>` : ""}</span></div>`;
}

function versionRows(id: number, history: DocHistory, picked: number | null, ctx: Ctx): string {
  return history.versions
    .map((v) => {
      const a = writer(v, ctx);
      return `<a class="p2-version" href="${pageRoute(id, "historique", history.path)}" data-p2="docVersion" data-va="1" data-c="${v.n}" aria-selected="${v.n === picked}">${a.avatar("xs")}<span><b>Version ${v.n}${v.current ? " · actuelle" : ""}</b>${v.word ? `<em>« ${h(v.word)} »</em>` : ""}<small>${h(a.name)} · ${h(when(v.at, ctx.now))}</small></span></a>`;
    })
    .join("");
}

const toc = (titles: readonly { level: number; text: string; id?: string }[], act: "codeJump" | "docToc"): string =>
  titles.length
    ? `<nav class="p2-toc">${titles.map((t, i) => `<button type="button" class="n${t.level}" data-p2="${act}" data-c="${act === "codeJump" ? h(t.id ?? "") : i}">${h(t.text)}</button>`).join("")}</nav>`
    : '<p class="p2-none">Cette page n\'a pas de titre.</p>';

/** Le sommaire pendant qu'on écrit : les titres du texte tapé, sous le premier. */
export function draftToc(text: string): string {
  return toc(headingsOf(text).filter((t) => t.level > 1), "docToc");
}

// ── Pages ────────────────────────────────────────────────────────────

export interface PagesData {
  space: DocSpace;
  mode: PageMode;
  /** Le chemin de l'adresse, et la page lue (celle de l'adresse, ou la page d'accueil). */
  wanted: string;
  page: Got<DocPageText> | null;
  history: Got<DocHistory> | null;
  /** L'historique : la version choisie, lue. */
  version: Got<DocVersionText> | null;
  /** Les pages trouvées, quand on cherche. */
  found: Got<{ q: string; items: DocFound[] }> | null;
  /** Le brouillon d'une page, par son chemin ; `null` : rien n'y est en attente. */
  draft: (path: string) => Draft | null;
}

function nodes(id: number, list: readonly TreeNode[], d: PagesData, ui: DocUi, picked: string, depth: number): string {
  return list
    .map((n) => {
      if (n.page) return `<a class="p2-node" style="--d:${depth}" href="${pageRoute(id, "pages", n.path)}" aria-selected="${n.path === picked}" title="${h(n.page.title)}">${ico("file", "sm")}<span>${h(n.name)}</span>${isDirty(d.draft(n.path)) ? '<i class="p2-dirty" title="Modifiée, pas encore enregistrée"></i>' : ""}</a>`;
      const folded = ui.folded.has(n.path);
      return `<button class="p2-node dir" style="--d:${depth}" type="button" data-p2="docFold" data-c="${h(n.path)}" aria-expanded="${!folded}">${ico(folded ? "chev-right" : "chev-down", "xs")}${ico("folder", "sm")}<span>${h(n.name)}</span></button>${folded ? "" : nodes(id, n.children, d, ui, picked, depth + 1)}`;
    })
    .join("");
}

function results(id: number, d: PagesData, ui: DocUi, picked: string): string {
  const got = d.found;
  if (!got?.value) return waitingBlock(got ?? { value: null, error: null }, "La recherche n'a pas abouti");
  return got.value.items.length
    ? got.value.items.map((x) => `<a class="li p2-row" href="${pageRoute(id, "pages", x.path)}" aria-selected="${x.path === picked}">${tile("file")}<span class="li-main"><span class="li-title">${h(x.title)}</span><span class="p2-row-sub"><span class="ellipsis">${h(x.excerpt || x.path)}</span></span></span></a>`).join("")
    : empty("search", "Rien trouvé", `Aucune page ne contient « ${ui.query.trim()} ».`);
}

/** Lire, ou Modifier : la bascule d'une page qu'on peut écrire. */
const modeSwitch = (id: number, path: string, mode: PageMode): string =>
  `<div class="seg p2-mode"><a href="${pageRoute(id, "pages", path)}" aria-pressed="${mode === "pages"}">${ico("eye", "sm")}Lire</a><a href="${pageRoute(id, "modifier", path)}" aria-pressed="${mode === "modifier"}">${ico("pen", "sm")}Modifier</a></div>`;

/** Ce que rend une page : son Markdown, ses images servies par l'API, ses liens vers les autres pages de l'espace. */
function rendered(id: number, space: DocSpace, text: string, headings?: Heading[]): string {
  const images = new Set(space.images.map((x) => x.name));
  const paths = new Set(space.pages.map((x) => x.path));
  return pageHtml(text, {
    image: (name) => (images.has(name) ? docImageUrl(id, name) : null),
    link: (href) => (paths.has(href.replace(/^\.?\//, "")) ? pageRoute(id, "pages", href.replace(/^\.?\//, "")) : null),
    headings,
  });
}

function reading(sheet: Sheet, p: DocPageText, d: PagesData, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const write = p.can.write;
  const titles: Heading[] = [];
  const html = p.forgotten ? "" : rendered(id, d.space, p.text, titles);
  const dirty = isDirty(d.draft(p.path));
  const history = d.history?.value ?? null;
  const images = d.space.images.filter((x) => p.images.includes(x.name));
  const where = `doc:${id}:${p.path}`;
  return {
    scroll: `doc-${p.path}`, panes: [["", "Page"]], active: "", link: () => pageRoute(id, "pages", p.path),
    head: `<div class="pane-head p2-path">${crumbs(p.path)}<span class="grow"></span>${write ? modeSwitch(id, p.path, "pages") : ""}
      <button class="btn icon ghost sm" type="button" data-p2="docMenu" data-p="${id}" data-c="${h(p.path)}" title="${write ? "Renommer, déplacer, supprimer" : "Son historique, son lien"}">${ico("more", "sm")}</button></div>`,
    body: `${refusal(refusalAt(ctx.ui, where))}${dirty ? `<p class="p2-banner you">${ico("pen", "sm")}<span>Cette page a des modifications que tu n'as pas enregistrées.</span><a class="btn sm" href="${pageRoute(id, "modifier", p.path)}">Les reprendre</a><button class="btn sm ghost" type="button" data-p2="docDiscard" data-p="${id}" data-c="${h(p.path)}">Les abandonner</button></p>` : ""}
      ${p.forgotten ? nothing("file", "Son texte n'est plus là", "Le texte de cette page a été oublié.") : `<div class="p2-md">${html}</div>`}`,
    side: sc("Sur cette page", toc(titles.filter((t) => t.level > 1), "codeJump"))
      + sc("Dernière modification", signature(p, history?.versions.find((v) => v.current)?.word ?? "", ctx))
      + sc("Versions", history ? `<div class="p2-versions">${versionRows(id, history, null, ctx)}</div>` : d.history ? waitingBlock(d.history) : "", `<span class="cnt">${p.version}</span>`)
      + sc("Ses images", images.map((x) => `<a class="p2-lie" href="${imageRoute(id, x.name)}"><span class="p2-mini-img"><img src="${h(docImageUrl(id, x.name))}" alt="" loading="lazy"></span><span><b>${h(x.name)}</b><small>${h(sizeWords(x.size))}</small></span></a>`).join("")),
  };
}

function pastVersion(sheet: Sheet, p: DocPageText, d: PagesData, ui: DocUi, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const history = d.history?.value ?? null;
  const v = d.version?.value ?? null;
  const line: DocVersion | null = v ?? history?.versions.find((x) => (ui.version === null ? x.current : x.n === ui.version)) ?? null;
  const a = line ? writer(line, ctx) : null;
  const where = `doc:${id}:${p.path}`;
  const body = !line || !a ? waitingBlock<unknown>(d.version ?? d.history ?? { value: null, error: null }, "Impossible de lire cette version")
    : `${refusal(refusalAt(ctx.ui, where))}<p class="p2-banner${line.current ? " done" : ""}">${a.avatar("sm")}<span><b>Version ${line.n}</b> · ${h(a.name)}${a.sub ? `, ${h(a.sub)}` : ""} · ${h(moment(line.at, ctx.now))}${line.word ? ` — « ${h(line.word)} »` : ""}</span>
        ${line.current || !p.can.write ? (line.current ? '<span class="p2-kind">la version actuelle</span>' : "") : `<button class="btn sm primary" type="button" data-p2="docRestore" data-p="${id}" data-c="${h(p.path)}" data-v="${line.n}" data-b="${p.version}">${ico("history", "sm")}Revenir à cette version</button>`}</p>
      ${!v ? waitingBlock(d.version ?? { value: null, error: null }, "Impossible de lire cette version") : v.forgotten ? nothing("file", "Son texte n'est plus là", "Le texte de cette version a été oublié.") : `<div class="p2-md">${rendered(id, d.space, v.text)}</div>`}`;
  return {
    scroll: `version-${p.path}-${line?.n ?? 0}`, panes: [["", line ? `Version ${line.n}` : "Version"]], active: "", link: () => pageRoute(id, "historique", p.path),
    head: `<div class="pane-head p2-path">${crumbs(p.path)}<span class="p2-kind">historique</span><span class="grow"></span><a class="btn sm" href="${pageRoute(id, "pages", p.path)}">${ico("chev-left", "sm")}Revenir à la page</a></div>`,
    body,
    side: sc("Versions", history ? `<div class="p2-versions">${versionRows(id, history, line?.n ?? null, ctx)}</div>` : d.history ? waitingBlock(d.history) : "", history ? `<span class="cnt">${history.versions.length}</span>` : "")
      + (history && history.version > history.versions.length ? hint(`Les ${history.kept} dernières versions sont gardées.`) : ""),
  };
}

/** Le cadre du mode Modifier : l'éditeur (Milkdown, par Crepe) s'y pose après le dessin, dans `[data-p2-crepe]`. */
function editing(sheet: Sheet, p: DocPageText, d: PagesData, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const draft = d.draft(p.path);
  const dirty = isDirty(draft);
  const text = draft?.text ?? p.text;
  const data = `data-p="${id}" data-c="${h(p.path)}"`;
  const said = draft?.refusal
    ? `<p class="p2-banner fail p2-conflict" role="alert">${ico("alert", "sm")}<span>${h(draft.refusal)}${draft.conflict ? " Ce que tu as écrit est gardé ici." : ""}</span>${draft.conflict
        ? `<a class="btn sm" href="${pageRoute(id, "pages", p.path)}">Relire la page</a><button class="btn sm" type="button" data-p2="docRebase" ${data}>Reprendre sur sa version actuelle</button>` : ""}</p>`
    : "";
  return {
    scroll: `ed-${p.path}`, plain: true, panes: [["", "Écrire"]], active: "", link: () => pageRoute(id, "modifier", p.path),
    head: `<div class="pane-head p2-path">${crumbs(p.path)}<span class="p2-st you p2-unsaved"${dirty ? "" : " hidden"}>pas encore enregistrée</span><span class="grow"></span>${modeSwitch(id, p.path, "modifier")}
      <button class="btn sm ghost p2-undo" type="button" data-p2="docDiscard" ${data}${dirty ? "" : " hidden"}>Annuler</button>
      <button class="btn sm primary" type="button" data-p2="docSave" ${data}${dirty ? "" : " disabled"}>${ico("check", "sm")}Enregistrer</button></div>`,
    body: `${said}<div class="p2-crepe" data-p2-crepe ${data}></div>`,
    side: sc("Écrire", `<ul class="p2-tips"><li>${ico("pen", "xs")}<span>Écris dans la page : elle garde du vrai Markdown.</span></li><li>${ico("plus", "xs")}<span>Tape <kbd>/</kbd> pour un titre, une liste, un tableau, un bloc de code, une image.</span></li>
        <li>${ico("image", "xs")}<span>Glisse une image dans la page, ou colle-la : elle rejoint les images de la documentation.</span></li></ul>
        <label class="btn p2-upload">${ico("upload", "sm")}Téléverser une image<input type="file" accept="${IMAGE_KINDS}" data-p2-fichier="page" data-p="${id}" hidden></label>`)
      + sc("Sur cette page", `<div data-p2-toc>${draftToc(text)}</div>`)
      + sc("Images de la documentation", `<div class="p2-pick" data-p2-pick>${imagePicker(id, d.space.images)}</div>`)
      + sc("Le Markdown", `<details class="p2-src-md"><summary>${ico("chev-right", "xs")}Voir ce qui sera enregistré</summary><pre data-p2-source>${h(text)}</pre></details>`),
  };
}

/** Les images de l'espace, à insérer dans la page qu'on écrit. */
export function imagePicker(id: number, images: readonly DocImage[]): string {
  return images.map((x) => `<button type="button" data-p2="docInsertImage" data-c="${h(x.name)}" title="L'insérer dans la page"><img src="${h(docImageUrl(id, x.name))}" alt="" loading="lazy"><span>${h(x.name)}</span></button>`).join("")
    || '<p class="p2-none">Aucune image pour l\'instant.</p>';
}

export function pagesView(sheet: Sheet, d: PagesData, ui: DocUi, ctx: Ctx): string {
  const id = sheet.project.id;
  const write = d.space.rights.write;
  const p = d.page?.value ?? null;
  const picked = p?.path ?? d.wanted;
  const query = ui.query.trim();
  const list = `<div class="p2-tools"><label class="search grow">${ico("search", "sm")}<input type="search" placeholder="Chercher…" data-p2-saisie="doc" value="${h(ui.query)}"></label>
      ${write ? `<button class="btn primary" type="button" data-p2="docNew" data-p="${id}" title="Nouvelle page">${ico("plus", "sm")}<span>Nouvelle page</span></button>` : ""}</div>
    <div class="pane-scroll ${query ? "" : "p2-tree"}" data-scroll="doc-arbre">${query ? results(id, d, ui, picked) : d.space.pages.length ? nodes(id, pageTree(d.space.pages), d, ui, picked, 0)
      : empty("book", "Pas encore de page", write ? "Écris la première : elle la lira pendant ses exécutions." : "Cet espace de documentation est encore vide.")}</div>`;
  const edit = d.mode === "modifier" && !!p?.can.write;
  const base: Trio = { cls: `etroit p2-docs${edit ? " edition" : ""}`, list, open: !!d.wanted, back: [sheetRoute(id, "documentation"), "Pages"], infos: ctx.ui.infos };
  if (!d.page) return trio({ ...base, empty: empty("book", "Choisis une page", "Elle s'ouvre ici, à côté de l'arborescence.") });
  if (!p) return trio({ ...base, empty: waitingBlock(d.page, "Impossible de lire cette page") });
  return trio({ ...base, ...(edit ? editing(sheet, p, d, ctx) : d.mode === "historique" ? pastVersion(sheet, p, d, ui, ctx) : reading(sheet, p, d, ctx)) });
}

// ── Images ───────────────────────────────────────────────────────────

function imagePanel(sheet: Sheet, space: DocSpace, x: DocImage, ctx: Ctx): string {
  const id = sheet.project.id;
  const a = writer(x, ctx);
  const pages = x.used_by.map((path) => space.pages.find((p) => p.path === path)).filter((p): p is DocPage => !!p);
  return sc(null, `${refusal(refusalAt(ctx.ui, `doc-image:${id}`))}<div class="p2-img-grand"><img src="${h(docImageUrl(id, x.name))}" alt="${h(x.name)}"></div><p class="p2-img-nom"><code>${h(x.name)}</code></p>`)
    + sc("L'image", props([["Poids", h(sizeWords(x.size))], ["Ajoutée par", `<span class="p2-by">${a.avatar("xs")}${h(a.name)}</span>`], a.sub ? ["Par où", h(a.sub)] : null, ["Quand", h(moment(x.at, ctx.now))]]))
    + sc("Citée dans", pages.map((p) => linked(pageRoute(id, "pages", p.path), "file", "", p.title, h(p.path))).join("") || '<p class="p2-none">Aucune page ne la cite.</p>', `<span class="cnt">${x.used_by.length}</span>`)
    + sc("Gérer", `<div class="p2-decide"><button class="btn" type="button" data-p2="copy" data-c="${h(imageMarkdown(x.name))}">${ico("copy", "sm")}Copier son lien Markdown</button>
        ${space.rights.write ? `<button class="btn danger" type="button" data-p2="docImageRemove" data-p="${id}" data-c="${h(x.name)}" data-n="${x.used_by.length}">${ico("trash", "sm")}Retirer l'image</button>` : ""}</div>`);
}

export function imagesView(sheet: Sheet, space: DocSpace, wanted: string, ctx: Ctx): string {
  const id = sheet.project.id;
  const write = space.rights.write;
  const picked = space.images.find((x) => x.name === wanted) ?? (ctx.mobile ? null : (space.images[0] ?? null));
  const grid = `<div class="p2-imgzone"${write ? ` data-p2-depot="${id}"` : ""}><header class="p2-sec-h"><div><h2>Les images de la documentation</h2><p>Une image téléversée se cite dans une page : <code>![texte](images/nom.png)</code>.</p></div>
      ${write ? `<label class="btn primary">${ico("upload", "sm")}Téléverser une image<input type="file" accept="${IMAGE_KINDS}" data-p2-fichier="space" data-p="${id}" hidden></label>` : ""}</header>${refusal(refusalAt(ctx.ui, `doc-upload:${id}`))}
    <div class="p2-imgs">${space.images.map((x) => `<a class="p2-img" href="${imageRoute(id, x.name)}" aria-selected="${x === picked}"><span class="p2-thumb"><img src="${h(docImageUrl(id, x.name))}" alt="${h(x.name)}" loading="lazy"></span><span class="p2-img-cap"><code>${h(x.name)}</code><small>${h(sizeWords(x.size))} · ${x.used_by.length ? plural(x.used_by.length, "page", "pages") : "aucune page"}</small></span></a>`).join("")}
      ${write ? `<div class="p2-img p2-imgdrop">${ico("upload", "lg")}<b>Dépose une image ici</b><span>ou colle-la dans une page que tu modifies</span></div>` : space.images.length ? "" : '<p class="p2-none">Aucune image pour l\'instant.</p>'}</div></div>`;
  if (ctx.mobile) {
    return trio({ list: `<div class="pane-scroll" data-scroll="doc-images">${grid}</div>`, open: !!wanted && !!picked, back: [imageRoute(id), "Images"], panes: [["", "Image"]], active: "", link: () => imageRoute(id, wanted), scroll: "image",
      body: picked ? `<div class="p2-flat">${imagePanel(sheet, space, picked, ctx)}</div>` : "" });
  }
  return trio({ panes: [["", "Images"]], active: "", link: () => imageRoute(id), plain: true, scroll: "doc-images", body: grid, side: picked ? imagePanel(sheet, space, picked, ctx) : "" });
}

// ── Décisions ────────────────────────────────────────────────────────

export interface DecisionsData {
  list: Got<DecisionList>;
  wanted: string;
  decision: Got<DecisionFull> | null;
}

const decisionTone = (d: Pick<Decision, "status">): Tone => (d.status === "active" ? "done" : "wait");

/** Les champs d'une décision. `replaceable` : celles qu'elle peut remplacer (à la création seulement). */
export function decisionFields(d: DecisionFull | null, replaceable: readonly Decision[], replaces: number, errors: Record<string, string>): string {
  return `${F.text("title", "La décision, en une phrase", d?.title ?? "", { required: true, hint: "Par exemple : Le journal des refus est un fichier JSON Lines", error: errors.title })}
    ${F.long("choice", "Le choix", d?.choice ?? "", { rows: 3, required: true, error: errors.choice })}
    ${F.long("context", "Le contexte", d?.context ?? "", { rows: 3, hint: "Ce qui a rendu cette décision nécessaire.", error: errors.context })}
    ${F.long("reason", "La raison", d?.reason ?? "", { rows: 3, hint: "Pourquoi ce choix plutôt qu'un autre.", error: errors.reason })}
    ${F.long("options", "Les options écartées", d?.options ?? "", { rows: 4, help: "Une par ligne — « l'option : pourquoi elle est écartée ».", error: errors.options })}
    ${d ? "" : F.select("replaces", "Elle remplace", replaces || "", [["", "aucune décision"], ...replaceable.map((x): [string, string] => [String(x.number), `n° ${x.number} · ${x.title}`])], { error: errors.replaces })}`;
}

function decisionDetail(sheet: Sheet, d: DecisionFull, all: readonly Decision[], pane: string | undefined, ctx: Ctx): Trio {
  const id = sheet.project.id;
  const f = (k = ""): string => decisionRoute(id, d.number, k);
  const v = pane === "options" || (pane === "modifier" && d.can.modify) ? pane : "";
  const where = `decision:${id}:${d.number}`;
  const tone = decisionTone(d);
  const before = all.find((x) => x.number === d.replaces);
  const after = all.find((x) => x.number === d.replaced_by);
  const o = (sheet.objectives ?? []).find((x) => x.id === d.objective);
  const options = optionLines(d.options);
  const line = (x: Decision): string => linked(decisionRoute(id, x.number), "shield-check", decisionTone(x), x.title, `décision n° ${x.number} · ${h(when(x.at, ctx.now))}`, st(decisionTone(x), x.status_label));
  const body = v === "modifier"
    ? form({ name: "decision", key: where, data: { p: id, c: d.number }, title: `Modifier la décision n° ${d.number}`, sub: "Elle la relit avant chaque passage : ce que tu écris ici s'impose à elle.", cancel: f(), error: refusalAt(ctx.ui, where),
        bodyHtml: decisionFields(d, [], 0, fieldErrorsAt(ctx.ui, where)) })
    : v === "options" ? (options.length ? `<ol class="p2-options">${options.map((x) => `<li>${ico("x", "sm")}<div><b>${h(x.title)}</b>${x.why ? `<p>${code(x.why)}</p>` : ""}</div></li>`).join("")}</ol>` : '<p class="p2-none">Aucune autre option n\'a été notée.</p>')
    : `${refusal(refusalAt(ctx.ui, where))}${after ? `<p class="p2-banner">${ico("history", "sm")}<span>Cette décision n'est plus en vigueur : la décision n° ${after.number} la remplace.</span><a class="btn sm" href="${decisionRoute(id, after.number)}">La lire</a></p>` : d.status !== "active" ? banner("wait", "history", `Cette décision n'est plus en vigueur : ${d.status_label}.`) : ""}
      <p class="p2-choix">${code(d.choice)}</p>${d.context ? `<h3 class="p2-h3">Le contexte</h3><p class="p2-lede">${code(d.context)}</p>` : ""}${d.reason ? `<h3 class="p2-h3">La raison</h3><p class="p2-lede">${code(d.reason)}</p>` : ""}`;
  const who = `<span class="p2-by">${d.author_kind === "self" ? mikaAvatar("xs") : authorAvatar("person", d.author, ctx.me)}${h(d.author)}</span>`;
  const data = `data-p="${id}" data-c="${d.number}"`;
  const manage = (d.can.replace ? `<button class="btn" type="button" data-p2="decisionNew" ${data}>${ico("history", "sm")}La remplacer par une autre</button>` : "")
    + (d.can.restore ? `<button class="btn" type="button" data-p2="decisionStatus" data-s="active" ${data}>${ico("refresh", "sm")}La remettre en vigueur</button>` : "")
    + (d.can.withdraw ? `<button class="btn danger" type="button" data-p2="decisionStatus" data-s="withdrawn" ${data}>${ico("trash", "sm")}Retirer la décision</button>` : "");
  const panes: Pane[] = v === "modifier" ? [["modifier", "Modifier"]] : [["", "La décision"], ["options", "Options écartées", options.length]];
  return {
    scroll: `dec-${d.number}-${v}`, link: (k) => f(k), active: v, panes,
    head: head({ tileHtml: tile("shield-check", tone), over: `Décision n° ${d.number}`, title: d.title,
      metaHtml: `${st(tone, d.status_label)}${who}<span>${h(when(d.at, ctx.now))}</span>`,
      rightHtml: d.can.modify ? `<a class="btn${v === "modifier" ? " on" : ""}" href="${f(v === "modifier" ? "" : "modifier")}">${ico("pen", "sm")}Modifier</a>` : "" }),
    body,
    side: sc("En bref", props([["État", st(tone, d.status_label)], ["Par", who], ["Quand", h(moment(d.at, ctx.now))]]))
      + sc("Elle remplace", before ? line(before) : d.replaces ? linked(decisionRoute(id, d.replaces), "shield-check", "wait", `Décision n° ${d.replaces}`) : "")
      + sc("Remplacée par", after ? line(after) : d.replaced_by ? linked(decisionRoute(id, d.replaced_by), "shield-check", "done", `Décision n° ${d.replaced_by}`) : "")
      + sc("Ce qui est lié", o ? linked(sheetRoute(id, "objectifs", `o${o.id}`), "p2-target", objectiveTone(o.status), o.text, `objectif n° ${o.id}`, st(objectiveTone(o.status), o.status_label)) : d.objective ? linked(sheetRoute(id, "objectifs", `o${d.objective}`), "p2-target", "", `Objectif n° ${d.objective}`) : "")
      + sc("Gérer", manage ? `<div class="p2-decide">${manage}</div>` : d.can.why ? hint(d.can.why, "lock") : ""),
  };
}

export function decisionsView(sheet: Sheet, data: DecisionsData, pane: string | undefined, ctx: Ctx): string {
  const id = sheet.project.id;
  const list = data.list.value;
  const items = decisionOrder(list?.items ?? []);
  const row = (x: Decision): string => `<a class="li p2-row" href="${decisionRoute(id, x.number)}" aria-selected="${String(x.number) === data.wanted}">${tile("shield-check", decisionTone(x))}<span class="li-main"><span class="li-title">${h(x.title)}</span>
      <span class="p2-row-sub">${st(decisionTone(x), x.status_label)}<span>n° ${x.number}</span><time>${h(when(x.at, ctx.now))}</time></span></span></a>`;
  const none = empty("shield-check", "Aucune décision", "Un choix technique durable, qu'elle ne remet pas en cause à chaque passage.");
  const listHtml = `<div class="p2-tools"><h2 class="grow">Décisions techniques</h2>${list?.can ? `<button class="btn primary" type="button" data-p2="decisionNew" data-p="${id}">${ico("plus", "sm")}<span>Nouvelle décision</span></button>` : ""}</div>
    <div class="pane-scroll" data-scroll="decisions">${!list ? waitingBlock(data.list) : items.length ? items.map(row).join("") : none}</div>`;
  const base: Trio = { list: listHtml, open: !!data.wanted && !!data.decision, back: [decisionRoute(id), "Décisions"], infos: ctx.ui.infos };
  if (!data.decision) return trio({ ...base, empty: empty("shield-check", "Aucune décision", "Note ici un choix technique durable : elle le relira avant chaque passage.") });
  const d = data.decision.value;
  return trio({ ...base, ...(d ? decisionDetail(sheet, d, items, pane, ctx) : { empty: waitingBlock(data.decision, "Impossible de lire cette décision") }) });
}

