/**
 * L'onglet Documentation d'une fiche (ADR 0291, d'après `maquette/ecrans/projets2-doc.js`) : Pages, Images et
 * Décisions, branchés sur le socle par `registerTab("documentation", …)` (`tabs.ts`). Ce module tient ses lectures
 * gardées (`protocole-moi.md` § 11, « La documentation d'un projet » et ses décisions), **les brouillons** — ce qui
 * est écrit d'une page et pas encore enregistré — et **l'éditeur** : Milkdown, par son éditeur Crepe, chargé à la
 * demande (`editor.ts`) quand on ouvre le mode Modifier, et gardé d'un dessin à l'autre (son élément est reposé dans
 * le cadre, jamais refait).
 *
 * Enregistrer envoie le Markdown avec la version lue et un mot sur ce qui a changé ; si la page a changé depuis, le
 * serveur refuse (409) : ses mots se disent, **ce qui a été écrit reste**, et l'on reprend après avoir relu. Une
 * page modifiée et pas enregistrée le montre (dans sa tête, dans l'arbre, sur l'onglet), et quitter la vue le dit.
 * Une image téléversée — par le bouton, glissée, collée — part au serveur, puis s'insère dans la page.
 */
import { ApiError } from "../../api/moi";
import {
  docImageUrl, fetchDecision, fetchDecisions, fetchDocHistory, fetchDocPage, fetchDocs, fetchDocVersion, saveDocPage, searchDocs, uploadDocImage,
  type DecisionFull, type DecisionList, type DocFound, type DocHistory, type DocPageText, type DocSpace, type DocVersionText,
} from "../../api/projectDocs";
import type { Sheet } from "../../api/projects";
import { CachedMap, copyText, failureText, loadingBlock, newNonce, sessionGone, toastFailure } from "../../shared/kit";
import { h } from "../../shell/dom";
import { openMenu, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import { sizeWords } from "./codeparts";
import { askLine } from "./dialogs";
import { spaceImage } from "./docmd";
import {
  decisionRequest, decisionRoute, decisionStatusRequest, docPlace, draftKey, folderOf, folderPath, homePage, imageMarkdown, imageRemoveRequest, imageRoute, isDirty, moveRequest, nameOf, pagePath,
  pageRoute, rebased, refused, removeRequest, restoreRequest, saveBody, startDraft, tidyMarkdown, typed, type Draft,
} from "./docparts";
import type { PageEditor } from "./editor";
import { plural, refusalWords } from "./gestures";
import { keepLateScroll } from "./paint";
import { F, subbar } from "./parts";
import { sheetRoute } from "./routes";
import { fieldErrorsAt, refusalAt } from "./state";
import { registerTab, type Act, type FormAct, type TabHost } from "./tabs";
import { decisionFields, decisionsView, draftToc, imagePicker, imagesView, pagesView, type DocUi } from "./views/docs";
import { waitingBlock, type Got } from "./views/todo";

const k = (...parts: Array<string | number>): string => parts.join("\n");
const unk = (key: string): string[] => key.split("\n");

const spaces = new CachedMap<DocSpace>((id) => fetchDocs(Number(id)));
const pages = new CachedMap<DocPageText>((key) => {
  const [id, path] = unk(key);
  return fetchDocPage(Number(id), path);
});
const histories = new CachedMap<DocHistory>((key) => {
  const [id, path] = unk(key);
  return fetchDocHistory(Number(id), path);
});
const versions = new CachedMap<DocVersionText>((key) => {
  const [id, path, n] = unk(key);
  return fetchDocVersion(Number(id), path, Number(n));
}, 300_000);
const founds = new CachedMap<{ q: string; items: DocFound[] }>((key) => {
  const [id, words] = unk(key);
  return searchDocs(Number(id), words);
}, 60_000);
const decisionLists = new CachedMap<DecisionList>((id) => fetchDecisions(Number(id)));
const decisions = new CachedMap<DecisionFull>((key) => {
  const [id, number] = unk(key);
  return fetchDecision(Number(id), Number(number));
});

const ui: DocUi = { query: "", folded: new Set(), version: null };
/** Ce qui est écrit d'une page et pas encore enregistré, par projet et par chemin. */
const drafts = new Map<string, Draft>();
/** Le socle, connu dès le premier dessin : les écouteurs du document en ont besoin. */
let host: TabHost | null = null;
let queryTimer = 0;
let saving = false;

/** Après un geste : tout ce qui est lu de la documentation et des décisions repart du serveur. */
function invalidateDocs(): void {
  for (const map of [spaces, pages, histories, versions, founds, decisionLists, decisions]) map.invalidate();
}

function refuse(where: string, err: unknown): void {
  if (sessionGone(err)) {
    location.reload();
    return;
  }
  if (!host) return;
  host.ui.refusal = { where, text: refusalWords(failureText(err), err instanceof ApiError ? err.fields : {}), fields: err instanceof ApiError ? err.fields : {} };
  host.repaint();
}

// ── L'éditeur : un seul à la fois, gardé d'un dessin à l'autre ───────

interface Live {
  key: string;
  project: number;
  path: string;
  /** L'élément où l'éditeur vit : reposé dans le cadre à chaque dessin. */
  root: HTMLElement;
  editor: PageEditor | null;
  /** Il avait la main avant le dessin en cours : elle lui revient après. */
  focused: boolean;
}

let live: Live | null = null;

/** Ce qu'une page cite et que le navigateur peut charger : une image de l'espace, servie par l'API ; rien d'ailleurs. */
const ELSEWHERE = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="64"><rect width="360" height="64" rx="10" fill="#e9e9f0"/><text x="180" y="38" font-family="sans-serif" font-size="13" fill="#555" text-anchor="middle">image d\'ailleurs : non chargée</text></svg>')}`;

function shownImage(project: number, src: string): string {
  const name = spaceImage(String(src ?? ""));
  return name ? docImageUrl(project, name) : ELSEWHERE;
}

/** Téléverser une image : elle part au serveur, qui rend le nom sous lequel il la garde. */
async function upload(project: number, file: File): Promise<string> {
  const r = await uploadDocImage(project, file, newNonce());
  spaces.invalidate(String(project));
  toast(r.message || `Image ajoutée : images/${r.name}`, { ico: "image" });
  // la liste des images du panneau se relit, sans toucher à l'éditeur
  void spaces.get(String(project)).load(true).then((space) => {
    const pick = document.querySelector("[data-p2-pick]");
    if (space && pick) pick.innerHTML = imagePicker(project, space.images);
  });
  return r.name;
}

/** Ce qui vient d'être tapé : le brouillon le garde, et la tête de la page le montre — sans rien redessiner. */
function track(it: Live, markdown: string): void {
  const d = drafts.get(it.key);
  if (!d) return;
  const next = typed(d, tidyMarkdown(markdown));
  drafts.set(it.key, next);
  showDraft(next);
}

function showDraft(d: Draft): void {
  const dirty = isDirty(d);
  const head = document.querySelector(".p2-docs .p2-path");
  head?.querySelector(".p2-unsaved")?.toggleAttribute("hidden", !dirty);
  head?.querySelector(".p2-undo")?.toggleAttribute("hidden", !dirty);
  const save = head?.querySelector<HTMLButtonElement>('[data-p2="docSave"]');
  if (save) save.disabled = !dirty;
  const toc = document.querySelector("[data-p2-toc]");
  if (toc) toc.innerHTML = draftToc(d.text);
  const source = document.querySelector("[data-p2-source]");
  if (source) source.textContent = d.text;
  dot(document.querySelector('.p2-docs .p2-node[aria-selected="true"]'), dirty);
  dot(document.querySelector('.p2-tabs a[aria-current="page"]'), dirty || [...drafts.values()].some(isDirty));
}

/** Le point d'une page modifiée et pas enregistrée. */
function dot(el: Element | null, on: boolean): void {
  if (!el) return;
  const there = el.querySelector(".p2-dirty");
  if (on && !there) el.insertAdjacentHTML("beforeend", '<i class="p2-dirty" title="Modifiée, pas encore enregistrée"></i>');
  if (!on) there?.remove();
}

function openEditor(project: number, path: string, key: string): Live {
  const root = document.createElement("div");
  root.className = "p2-crepe-root";
  root.innerHTML = loadingBlock("L'éditeur se charge…");
  const it: Live = { key, project, path, root, editor: null, focused: false };
  const start = drafts.get(key)?.text ?? "";
  // le paquet de l'éditeur n'a pas chargé : une zone de texte, pour ne rien perdre
  const plain = (): void => {
    if (live !== it) return;
    const area = document.createElement("textarea");
    area.className = "p2-secours";
    area.spellcheck = false;
    area.setAttribute("aria-label", "Le Markdown de la page");
    area.value = drafts.get(key)?.text ?? start;
    area.addEventListener("input", () => track(it, area.value));
    root.replaceChildren(area);
  };
  void import("./editor")
    .then((mod) => {
      if (live !== it) return undefined;
      root.replaceChildren();
      const editor = mod.createEditor(root, {
        markdown: start,
        onChange: (markdown) => track(it, markdown),
        upload: (file) => upload(project, file).then((name) => `images/${name}`, (err: unknown) => {
          toastFailure(err);
          throw err;
        }),
        imageUrl: (src) => shownImage(project, src),
      });
      it.editor = editor;
      return editor.ready.then(() => {
        const d = drafts.get(key);
        if (live !== it || !d || isDirty(d)) return;
        // ce que l'éditeur rend d'une page qu'on n'a pas touchée est son point de départ : seule une frappe la dit modifiée
        const text = tidyMarkdown(editor.markdown());
        drafts.set(key, { ...d, read: text, text });
      });
    })
    .catch(plain);
  return it;
}

function closeEditor(): void {
  live?.editor?.destroy();
  live = null;
}

/** L'adresse est-elle celle d'une page de documentation ? Son projet, son mode, son chemin. */
function docAddress(hash: string): { project: number; mode: string; path: string } | null {
  const parts = hash.replace(/^#/, "").split("/").map((s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  });
  if (parts[0] !== "projets" || parts[1] !== "projets" || parts[3] !== "documentation" || !/^\d+$/.test(parts[2] ?? "")) return null;
  return { project: Number(parts[2]), mode: parts[4] ?? "", path: parts.slice(5).join("/") };
}

/** L'adresse a changé : l'éditeur d'une page qu'on quitte se défait ; son brouillon reste, et l'écran le dit. */
function left(): void {
  if (!live) return;
  const now = docAddress(location.hash);
  const same = !!now && draftKey(now.project, now.path) === live.key;
  if (same && now?.mode === "modifier") return;
  const d = drafts.get(live.key);
  if (isDirty(d)) {
    if (!same) toast(`« ${live.path} » n'est pas enregistrée : ton brouillon est gardé.`, { ico: "alert", duration: 4200 });
  } else drafts.delete(live.key);
  closeEditor();
}

// ── Le dessin ────────────────────────────────────────────────────────

function render(sheet: Sheet, rest: string[], h0: TabHost): string {
  host = h0;
  const id = sheet.project.id;
  const ctx = h0.ctx();
  if (live?.editor) live.focused = live.editor.hasFocus();
  const place = docPlace(rest);
  const space = h0.read(spaces.get(String(id)));
  const list = h0.read(decisionLists.get(String(id)));
  const s = space.value;
  const right = s ? `<span class="p2-remote plain" title="Un espace à part du dépôt du code">${ico("book", "sm")}<span>${plural(s.pages.length, "page", "pages")} · ${h(sizeWords(s.space_used))}</span></span><span class="p2-sync">${ico("info", "xs")}à part du dépôt du code</span>` : "";
  const bar = subbar([[sheetRoute(id, "documentation"), "Pages", s ? s.pages.length : null], [imageRoute(id), "Images", s ? s.images.length : null], [decisionRoute(id), "Décisions", list.value ? list.value.in_force : null]],
    place.tab === "pages" ? 0 : place.tab === "images" ? 1 : 2, right);
  let inner: string;
  if (place.tab === "decisions") {
    const items = list.value?.items ?? [];
    const wanted = /^\d+$/.test(place.rest[0] ?? "") ? place.rest[0] : ctx.mobile || !items.length ? "" : String((items.find((d) => d.status === "active") ?? items[0]).number);
    inner = decisionsView(sheet, { list, wanted, decision: wanted ? h0.read(decisions.get(k(id, wanted))) : null }, place.rest[1], ctx);
  } else if (!s) inner = waitingBlock(space, "Impossible de lire sa documentation");
  else if (place.tab === "images") inner = imagesView(sheet, s, place.path, ctx);
  else {
    const target = place.path || (ctx.mobile ? "" : (homePage(s.pages)?.path ?? ""));
    const page = target ? h0.read(pages.get(k(id, target))) : null;
    const history = target && place.mode !== "modifier" ? h0.read(histories.get(k(id, target))) : null;
    let version: Got<DocVersionText> | null = null;
    if (place.mode === "historique" && target) {
      const n = ui.version ?? history?.value?.version ?? 0;
      version = n ? h0.read(versions.get(k(id, target, n))) : null;
    }
    const words = ui.query.trim();
    const key = draftKey(id, target);
    // le brouillon du mode Modifier naît de la page lue ; non touché, il suit la page si elle a changé entre-temps
    const known = drafts.get(key);
    if (place.mode === "modifier" && page?.value?.can.write && live?.key !== key && (!known || (!isDirty(known) && known.base !== page.value.version))) drafts.set(key, startDraft(page.value));
    inner = pagesView(sheet, { space: s, mode: place.mode, wanted: place.path, page, history, version, found: words ? h0.read(founds.get(k(id, words))) : null, draft: (path) => drafts.get(draftKey(id, path)) ?? null }, ui, ctx);
  }
  return `${bar}<div class="p2-under">${inner}</div>`;
}

/** Après le dessin : l'éditeur retrouve son cadre (ou naît), reprend la main s'il l'avait, et l'onglet dit ce qui attend. */
function after(body: HTMLElement, sheet: Sheet): void {
  dot(body.querySelector('.p2-tabs a[aria-current="page"]'), [...drafts.entries()].some(([key, d]) => key.startsWith(`${sheet.project.id}:`) && isDirty(d)));
  const frame = body.querySelector<HTMLElement>("[data-p2-crepe]");
  if (!frame) return;
  const project = Number(frame.dataset.p);
  const path = frame.dataset.c ?? "";
  const key = draftKey(project, path);
  if (live?.key !== key) {
    closeEditor();
    live = openEditor(project, path, key);
  }
  frame.replaceChildren(live.root);
  if (live.focused) live.editor?.focus();
  keepLateScroll(body, "[data-p2-crepe]");
}

// ── Les gestes ───────────────────────────────────────────────────────

/** Une image choisie hors de l'éditeur (le bouton du panneau, la grille des images, un dépôt). */
async function picked(project: number, file: File | undefined, into: "page" | "space"): Promise<void> {
  if (!file) return;
  try {
    const name = await upload(project, file);
    if (into === "page") live?.editor?.insert(imageMarkdown(name));
    else host?.go(imageRoute(project, name));
  } catch (err) {
    if (into === "page") toastFailure(err);
    else refuse(`doc-upload:${project}`, err);
  }
}

const pageMenu: Act = (d, el, h0) => {
  const id = Number(d.p);
  const path = d.c ?? "";
  const space = spaces.get(String(id)).value;
  const page = space?.pages.find((p) => p.path === path);
  const write = !!space?.rights.write;
  const key = `doc-move:${id}:${path}`;
  const drawer = (title: string, submit: string, body: () => string): void => {
    h0.ui.refusal = null;
    h0.drawer(() => ({ name: "docMove", key, data: { p: id, c: path }, title, sub: path, submit, error: refusalAt(h0.ui, key), bodyHtml: body() }));
  };
  const items: MenuItem[] = [
    ...(write ? [
      { label: "Renommer", icon: "pen" as const, action: () => drawer("Renommer la page", "Renommer", () => F.text("name", "Nom du fichier", nameOf(path), { required: true, help: "Les liens des autres pages vers celle-ci ne sont pas réécrits.", error: fieldErrorsAt(h0.ui, key).to })) },
      { label: "Déplacer", icon: "folder" as const, action: () => drawer("Déplacer la page", "Déplacer", () => `${F.select("folder", "Dossier", folderOf(path), [["", "la racine de l'espace"], ...(space?.folders ?? []).map((f): [string, string] => [f, f])])}${F.text("newFolder", "Ou un nouveau dossier", "", { hint: "par exemple : archives", error: fieldErrorsAt(h0.ui, key).to })}`) },
    ] : []),
    { label: "Son historique", icon: "history", action: () => {
      ui.version = null;
      h0.go(pageRoute(id, "historique", path));
    } },
    { label: "Copier son lien", icon: "copy", action: () => {
      const text = `[${page?.title ?? nameOf(path)}](${path})`;
      void copyText(text).then((ok) => toast(ok ? `Copié : ${text}` : "La copie n'a pas abouti.", { ico: "copy" }));
    } },
    ...(write ? ["sep" as const, { label: "Supprimer", icon: "trash" as const, danger: true, action: async () => {
      if (!(await h0.confirm({ title: "Supprimer la page ?", text: `« ${path} » et ses versions seront supprimées de l'espace de documentation. Les pages qui y renvoient garderont un lien sans cible.`, ok: "Supprimer", danger: true }))) return;
      const sent = await h0.send(id, removeRequest(path), `doc:${id}:${path}`, () => {
        drafts.delete(draftKey(id, path));
        invalidateDocs();
        h0.go(sheetRoute(id, "documentation"));
      });
      if (!sent) invalidateDocs();
    } }] : []),
  ];
  openMenu(el, items);
};

const decisionDrawer: Act = (d, _el, h0) => {
  const id = Number(d.p);
  const replaces = Number(d.c) || 0;
  const key = `decision-new:${id}`;
  h0.ui.refusal = null;
  h0.drawer(() => ({ name: "decision", key, data: { p: id }, title: "Nouvelle décision", sub: "Un choix technique durable : elle le relit avant chaque passage.", submit: "Noter la décision", error: refusalAt(h0.ui, key),
    bodyHtml: decisionFields(null, (decisionLists.get(String(id)).value?.items ?? []).filter((x) => x.can.replace), replaces, fieldErrorsAt(h0.ui, key)) }));
};

const acts: Record<string, Act> = {
  docFold: (d, _el, h0) => {
    const key = d.c ?? "";
    if (ui.folded.has(key)) ui.folded.delete(key);
    else ui.folded.add(key);
    h0.repaint();
  },
  docVersion: (d, el, h0) => {
    ui.version = Number(d.c) || null;
    h0.ui.infos = false;
    if (el.getAttribute("href") === location.hash) h0.repaint();
  },
  docMenu: pageMenu,
  docNew: (d, _el, h0) => {
    const id = Number(d.p);
    const space = spaces.get(String(id)).value;
    const here = docAddress(location.hash);
    const key = `doc-new:${id}`;
    h0.ui.refusal = null;
    h0.drawer(() => ({ name: "docPage", key, data: { p: id }, title: "Nouvelle page", sub: "Dans l'espace de documentation du projet", submit: "Créer la page", error: refusalAt(h0.ui, key),
      bodyHtml: `${F.text("title", "Son titre", "", { required: true, hint: "Par exemple : Dépannage", error: fieldErrorsAt(h0.ui, key).path })}
        ${F.select("folder", "Dossier", here?.path ? folderOf(here.path) : "", [["", "la racine de l'espace"], ...(space?.folders ?? []).map((f): [string, string] => [f, f])])}${F.text("newFolder", "Ou un nouveau dossier", "", { hint: "par exemple : guide/avance" })}` }));
  },
  docDiscard: (d, _el, h0) => {
    const key = draftKey(Number(d.p), d.c ?? "");
    drafts.delete(key);
    if (live?.key === key) closeEditor();
    toast("Modifications abandonnées.", { ico: "refresh" });
    h0.repaint();
  },
  /** Enregistrer : un mot sur ce qui a changé, puis le Markdown part avec la version lue. Refusé, rien n'est perdu. */
  docSave: async (d, _el, h0) => {
    const id = Number(d.p);
    const path = d.c ?? "";
    const key = draftKey(id, path);
    const draft = drafts.get(key);
    if (!draft || saving || !isDirty(draft)) return;
    const word = await askLine({ title: "Enregistrer la page", label: "Un mot sur ce qui a changé", hint: "Par exemple : ajout de la section Dépannage", ok: "Enregistrer", required: true,
      noteHtml: '<p class="small muted">Une version de la page est créée dans l\'espace de documentation, à ton nom. Le dépôt du code n\'est pas touché.</p>' });
    const current = drafts.get(key);
    if (word === null || !current) return;
    saving = true;
    try {
      const r = await saveDocPage(id, saveBody(current, word), newNonce());
      drafts.delete(key);
      invalidateDocs();
      toast(r.message || `Version ${r.version} enregistrée.`);
      h0.go(pageRoute(id, "pages", path));
    } catch (err) {
      if (sessionGone(err)) {
        location.reload();
        return;
      }
      const status = err instanceof ApiError ? err.status : 0;
      // ce qui est écrit reste : le brouillon garde le texte, et dit le refus avec les mots du serveur
      drafts.set(key, refused(drafts.get(key) ?? current, status, refusalWords(failureText(err), err instanceof ApiError ? err.fields : {})));
      if (status === 409 || status === 404) invalidateDocs();
      h0.repaint();
    } finally {
      saving = false;
    }
  },
  /** Après un conflit : la version actuelle se relit, et le texte tapé repart d'elle. */
  docRebase: async (d, _el, h0) => {
    const id = Number(d.p);
    const path = d.c ?? "";
    const key = draftKey(id, path);
    const draft = drafts.get(key);
    if (!draft) return;
    let page: DocPageText;
    try {
      page = await fetchDocPage(id, path);
    } catch (err) {
      drafts.set(key, refused(draft, err instanceof ApiError ? err.status : 0, failureText(err)));
      h0.repaint();
      return;
    }
    if (!(await h0.confirm({ title: `Reprendre sur la version ${page.version} ?`, text: `Ton texte deviendra la version suivante de la page. Ce que la version ${page.version} a changé et que tu n'as pas repris n'y sera plus : elle reste dans son historique.`, ok: "Reprendre sur cette version" }))) return;
    drafts.set(key, rebased(drafts.get(key) ?? draft, page));
    h0.repaint();
  },
  docRestore: async (d, _el, h0) => {
    const id = Number(d.p);
    const path = d.c ?? "";
    const n = Number(d.v);
    if (!(await h0.confirm({ title: `Revenir à la version ${n} ?`, text: `La page reprend le texte de la version ${n}. Rien n'est perdu : c'est une version de plus, et les autres restent dans l'historique.`, ok: "Revenir à cette version" }))) return;
    const sent = await h0.send(id, restoreRequest(path, n, Number(d.b)), `doc:${id}:${path}`, () => {
      drafts.delete(draftKey(id, path));
      invalidateDocs();
      ui.version = null;
      h0.go(pageRoute(id, "pages", path));
    });
    if (!sent) invalidateDocs();
  },
  docInsertImage: (d) => {
    if (!live?.editor) return;
    live.editor.insert(imageMarkdown(d.c ?? ""));
    toast(`Image insérée : images/${d.c}`, { ico: "image" });
  },
  docToc: (d, _el, h0) => {
    if (h0.ui.infos) {
      h0.ui.infos = false;
      h0.repaint();
    }
    document.querySelectorAll(".p2-crepe .ProseMirror :is(h2, h3, h4)")[Number(d.c)]?.scrollIntoView({ block: "start", behavior: "smooth" });
  },
  docImageRemove: async (d, _el, h0) => {
    const id = Number(d.p);
    const name = d.c ?? "";
    const used = Number(d.n) || 0;
    if (!(await h0.confirm({ title: "Retirer l'image ?", text: `« ${name} » sera retirée de l'espace de documentation.${used ? ` ${plural(used, "page la cite", "pages la citent")} : elle y apparaîtra comme introuvable.` : ""}`, ok: "Retirer", danger: true }))) return;
    const sent = await h0.send(id, imageRemoveRequest(name), `doc-image:${id}`, () => {
      invalidateDocs();
      h0.go(imageRoute(id));
    });
    if (!sent) invalidateDocs();
  },
  decisionNew: decisionDrawer,
  decisionStatus: async (d, _el, h0) => {
    const id = Number(d.p);
    const number = Number(d.c);
    const status = d.s === "active" ? "active" : "withdrawn";
    const title = decisions.get(k(id, number)).value?.title ?? `La décision n° ${number}`;
    if (status === "withdrawn" && !(await h0.confirm({ title: "Retirer la décision ?", text: `« ${title} » ne s'imposera plus à elle. Elle reste lisible, retirée.`, ok: "Retirer", danger: true }))) return;
    const sent = await h0.send(id, decisionStatusRequest(number, status), `decision:${id}:${number}`, () => invalidateDocs());
    if (!sent) invalidateDocs();
  },
};

const forms: Record<string, FormAct> = {
  /** Nouvelle page : son chemin, replié comme le serveur l'attend, et un premier titre ; elle s'ouvre en modification. */
  docPage: async (values, d, _form, h0) => {
    const id = Number(d.p);
    const title = String(values.title ?? "").trim();
    const path = pagePath(folderPath(String(values.newFolder ?? "")) || String(values.folder ?? ""), title);
    const where = `doc-new:${id}`;
    const sent = await h0.send(id, { route: "documentation/page/enregistrer", body: { path, text: `# ${title}\n\n`, word: "Création de la page", base: 0 } }, where, () => {
      invalidateDocs();
      ui.query = "";
      h0.closeDrawer();
      h0.go(pageRoute(id, "modifier", path));
    });
    if (!sent) invalidateDocs();
  },
  /** Renommer (son nom) ou déplacer (son dossier) : un autre chemin, ses versions la suivent. */
  docMove: async (values, d, _form, h0) => {
    const id = Number(d.p);
    const path = d.c ?? "";
    const to = values.name !== undefined ? pagePath(folderOf(path), String(values.name)) : pagePath(folderPath(String(values.newFolder ?? "")) || String(values.folder ?? ""), nameOf(path));
    if (to === path) {
      h0.closeDrawer();
      return;
    }
    const sent = await h0.send(id, moveRequest(path, to), `doc-move:${id}:${path}`, () => {
      // ce qui était écrit et pas enregistré suit la page
      const draft = drafts.get(draftKey(id, path));
      if (draft) {
        drafts.delete(draftKey(id, path));
        drafts.set(draftKey(id, to), { ...draft, path: to });
      }
      invalidateDocs();
      h0.closeDrawer();
      h0.go(pageRoute(id, "pages", to));
    });
    if (!sent) invalidateDocs();
  },
  /** Consigner une décision (dans le panneau), ou la modifier (dans la page). */
  decision: async (values, d, _form, h0) => {
    const id = Number(d.p);
    const number = Number(d.c) || 0;
    const before = number ? decisions.get(k(id, number)).value : null;
    if (number && !before) return;
    const sent = await h0.send(id, decisionRequest(values, before), number ? `decision:${id}:${number}` : `decision-new:${id}`, (r) => {
      invalidateDocs();
      h0.closeDrawer();
      h0.go(decisionRoute(id, number || r.number || ""));
    });
    if (!sent) invalidateDocs();
  },
};

// ── Les écouteurs du document ────────────────────────────────────────

if (typeof document !== "undefined") {
  addEventListener("hashchange", left);
  addEventListener("beforeunload", (e) => {
    if ([...drafts.values()].some(isDirty)) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  document.addEventListener("input", (e) => {
    const el = e.target as HTMLInputElement;
    if (el.dataset?.p2Saisie !== "doc") return;
    ui.query = el.value;
    window.clearTimeout(queryTimer);
    queryTimer = window.setTimeout(() => host?.repaint(), 280);
  });
  document.addEventListener("change", (e) => {
    const el = e.target as HTMLInputElement;
    const into = el.dataset?.p2Fichier;
    if (into !== "page" && into !== "space") return;
    void picked(Number(el.dataset.p), el.files?.[0], into);
    el.value = "";
  });
  for (const name of ["dragenter", "dragover", "dragleave", "drop"] as const) {
    document.addEventListener(name, (e) => {
      const zone = (e.target as Element).closest?.<HTMLElement>("[data-p2-depot]");
      if (!zone) return;
      e.preventDefault();
      zone.classList.toggle("depose", name === "dragenter" || name === "dragover");
      if (name === "drop") void picked(Number(zone.dataset.p2Depot), e.dataTransfer?.files[0], "space");
    });
  }
}

registerTab("documentation", { render, after, acts, forms });
