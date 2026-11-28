/**
 * « Fichiers », en haut du chat (ADR 0312, maquette `maquette/ecrans/chat-fichiers.js`) : tous les fichiers de la
 * conversation — tes pièces et ceux que Mika t'a envoyés —, lus au serveur page par page (`GET /api/moi/chat/fichiers`),
 * pas seulement dans les messages chargés. Chercher par nom, trier par sorte et par qui l'a envoyé, en liste ou en
 * vignettes ; un fichier s'ouvre dans la visionneuse (qui y ramène), s'enregistre, ou mène à son message.
 */
import { chatFiles, CHAT_FILES_LIMITS, FILE_SORTS, type ChatFileItem, type ChatFilesPage, type FileSort } from "../../api/chat";
import { dayAndClock } from "../../shared/dates";
import { read, write } from "../../shared/storage";
import { sizeLabel } from "../../shared/text";
import { $, h, on } from "../../shell/dom";
import { openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { saveBlob, type FileBlobs } from "./blobs";
import { reasonWords, tile, typeLabel } from "./files";
import { openViewer, type ViewerFile } from "./viewer";

/** Une page du panneau. */
export const PER_PAGE = 12;
/** La pause de la saisie avant de chercher. */
const SEARCH_PAUSE_MS = 250;
/** En liste ou en vignettes : retenu par ce navigateur. */
const GRID_KEY = "mika2_chat_files_grid";

const SORT_LABELS: Record<FileSort, string> = { image: "Images", pdf: "PDF", texte: "Textes", tableau: "Tableaux", autre: "Autres" };

export interface PanelHost {
  blobs: FileBlobs;
  /** Ton rond. */
  me: string;
  /** Le fil montré : vide, le fil avec elle ; en mode pro, le fil de travail ouvert. */
  strand: () => string;
  /** Mener au message qui porte ce fichier. */
  goTo: (f: ViewerFile) => void;
}

interface PanelState {
  strand: string;
  q: string;
  sorte: FileSort | "";
  de: "toi" | "mika" | "";
  page: number;
}

/** Ce que le panneau montrait : il y revient depuis la visionneuse, et à sa prochaine ouverture sur le même fil. */
let kept: PanelState = { strand: "", q: "", sorte: "", de: "", page: 1 };

/** Un fichier de la liste, tel que la visionneuse le montre. */
export function viewerFile(item: ChatFileItem): ViewerFile {
  return {
    key: item.key,
    name: item.name,
    sorte: item.sorte,
    mime: item.mime,
    size: item.size,
    from: item.from,
    at: item.at,
    src: item.available ? item.url : undefined,
    available: item.available && !!item.url,
    reason: item.reason,
    message: item.message,
    index: item.index,
  };
}

function who(item: ChatFileItem, me: string): string {
  return `<span class="fx-who">${item.from === "mika" ? mikaAvatar("xs") : me}${item.from === "mika" ? "Mika" : "Toi"}</span>`;
}

function rowsMarkup(items: readonly ChatFileItem[], me: string, now: number): string {
  const rows = items.map((item) => {
    const f = viewerFile(item);
    const when = dayAndClock(item.at, now);
    const sub = item.available ? typeLabel(item.name, item.sorte, item.mime) : `plus disponible · ${reasonWords(item.reason)}`;
    const acts = item.available
      ? `<button class="btn icon ghost xs" type="button" data-fx-open="${h(item.key)}" title="Aperçu" aria-label="Aperçu">${ico("eye", "sm")}</button>
         <button class="btn icon ghost xs" type="button" data-fx-save="${h(item.key)}" title="Enregistrer" aria-label="Enregistrer">${ico("download", "sm")}</button>`
      : "";
    return `<tr class="${item.available ? "" : "gone"}"${item.available ? ` data-fx-open="${h(item.key)}"` : ""}>
      <td><span class="fx-name">${tile(f)}<span><b title="${h(item.name)}">${h(item.name)}</b><small>${h(sub)}<span class="fx-m"> · ${item.from === "mika" ? "Mika" : "Toi"} · ${h(when)}</span></small></span></span></td>
      <td class="fx-c-de">${who(item, me)}</td><td class="fx-c-quand">${h(when)}</td><td class="fx-c-taille">${h(sizeLabel(item.size || undefined))}</td>
      <td class="actions">${acts}<button class="btn icon ghost xs" type="button" data-fx-msg="${h(item.key)}" title="Voir le message" aria-label="Voir le message">${ico("chat", "sm")}</button></td></tr>`;
  });
  return `<table class="tbl fx-tbl"><thead><tr><th>Fichier</th><th class="fx-c-de">De</th><th class="fx-c-quand">Quand</th><th class="fx-c-taille">Taille</th><th></th></tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}

function gridMarkup(items: readonly ChatFileItem[], now: number): string {
  return `<div class="fx-grid">${items
    .map((item) => {
      const f = viewerFile(item);
      const thumb = item.sorte === "image" && f.available && f.src
        ? `<span class="fx-thumb" data-thumb><img data-file="${h(f.src)}" alt=""></span>`
        : `<span class="fx-thumb">${tile({ ...f, src: undefined }, "lg")}</span>`;
      return `<button class="fx-card${item.available ? "" : " gone"}" type="button"${item.available ? ` data-fx-open="${h(item.key)}"` : " disabled"} title="${h(item.name)}">
        ${thumb}<b>${h(item.name)}</b><small>${item.available ? `${item.from === "mika" ? "Mika" : "Toi"} · ${h(dayAndClock(item.at, now))}` : "plus disponible"}</small></button>`;
    })
    .join("")}</div>`;
}

function kindsMarkup(page: ChatFilesPage | null, state: PanelState): string {
  const count = (v: FileSort | ""): string => (page ? `<span class="cnt">${page.counts[v] ?? 0}</span>` : "");
  return [["", "Tout"] as const, ...FILE_SORTS.map((s) => [s, SORT_LABELS[s]] as const)]
    .map(([v, label]) => `<button class="fx-kind" type="button" data-fx-sorte="${v}" aria-pressed="${state.sorte === v}">${label}${count(v)}</button>`)
    .join("");
}

function barMarkup(state: PanelState, grid: boolean): string {
  const de = ([["", "Tous"], ["toi", "Toi"], ["mika", "Mika"]] as const)
    .map(([v, l]) => `<button type="button" data-fx-de="${v}" aria-pressed="${state.de === v}">${l}</button>`)
    .join("");
  return `<div class="fx-bar">
    <label class="search fx-search">${ico("search", "sm")}<input type="search" data-fx-q maxlength="${CHAT_FILES_LIMITS.q}" placeholder="Chercher un fichier par son nom" value="${h(state.q)}" aria-label="Chercher un fichier"></label>
    <div class="seg" role="group" aria-label="Envoyé par">${de}</div>
    <div class="seg" role="group" aria-label="Affichage"><button type="button" data-fx-grid="0" aria-pressed="${!grid}" title="En liste" aria-label="En liste">${ico("menu", "sm")}</button><button type="button" data-fx-grid="1" aria-pressed="${grid}" title="En vignettes" aria-label="En vignettes">${ico("image", "sm")}</button></div></div>
    <div class="fx-kinds" data-fx-kinds></div>`;
}

function pagerMarkup(page: ChatFilesPage, filtered: boolean): string {
  const first = page.total ? (page.page - 1) * page.per + 1 : 0;
  const last = first ? first + page.items.length - 1 : 0;
  const shown = page.total ? `${first}–${last} sur ${page.total}` : "aucun fichier";
  const gone = page.unavailable && !filtered ? ` · dont ${page.unavailable} retiré${page.unavailable > 1 ? "s" : ""}` : "";
  return `<div class="fx-pager"><span class="muted small">${shown}${gone}</span><span class="grow"></span>
    <button class="btn icon ghost sm" type="button" data-fx-page="-1" title="Page précédente" aria-label="Page précédente"${page.page <= 1 ? " disabled" : ""}>${ico("chev-left")}</button>
    <span class="small">${page.page} / ${page.pages}</span>
    <button class="btn icon ghost sm" type="button" data-fx-page="1" title="Page suivante" aria-label="Page suivante"${page.page >= page.pages ? " disabled" : ""}>${ico("chev-right")}</button></div>`;
}

export function openFilesPanel(host: PanelHost): void {
  const strand = host.strand();
  const state: PanelState = kept.strand === strand ? { ...kept } : { strand, q: "", sorte: "", de: "", page: 1 };
  let grid = read(() => localStorage, GRID_KEY) === "1";
  let current: ChatFilesPage | null = null;
  let token = 0;
  let pause: number | null = null;

  const el = openModal({ title: "Les fichiers de la conversation", size: "wide", body: `${barMarkup(state, grid)}<div class="fx-content" data-fx-content></div>` });
  el.classList.add("fx-panel");
  const content = $<HTMLElement>("[data-fx-content]", el)!;
  const kinds = $<HTMLElement>("[data-fx-kinds]", el)!;
  const input = $<HTMLInputElement>("[data-fx-q]", el)!;

  const remember = (): void => {
    kept = { ...state };
  };
  const filtered = (): boolean => !!(state.q.trim() || state.sorte || state.de);

  const paint = (): void => {
    kinds.innerHTML = kindsMarkup(current, state);
    if (!current) return;
    const now = Date.now();
    const list = current.items.length
      ? grid ? gridMarkup(current.items, now) : rowsMarkup(current.items, host.me, now)
      : filtered()
        ? `<div class="empty">${ico("search")}<b>Aucun fichier ne correspond</b><p>Essaie un autre mot, ou retire un filtre.</p><button class="btn sm" type="button" data-fx-reset>Tout montrer</button></div>`
        : `<div class="empty">${ico("clip")}<b>Aucun fichier dans cette conversation</b><p>Ce que vous vous envoyez se retrouve ici, tant que c'est gardé.</p></div>`;
    content.innerHTML = `<div class="fx-list" data-fx-list>${list}</div>${current.total ? pagerMarkup(current, filtered()) : ""}`;
    host.blobs.fill(content);
  };

  const reload = async (): Promise<void> => {
    const mine = ++token;
    remember();
    if (!current) content.innerHTML = `<div class="fx-list"><div class="empty"><i class="spin"></i><p>Chargement…</p></div></div>`;
    try {
      const got = await chatFiles({ q: state.q.trim(), sorte: state.sorte, de: state.de, fil: state.strand, page: state.page, par: PER_PAGE });
      if (mine !== token || !el.isConnected) return;
      current = got;
      state.page = got.page;
      remember();
      paint();
    } catch (err) {
      if (mine !== token || !el.isConnected) return;
      kinds.innerHTML = kindsMarkup(null, state);
      content.innerHTML = `<div class="fx-list"><div class="empty">${ico("alert")}<b>Les fichiers n'ont pas pu être lus</b><p>${h(err instanceof Error ? err.message : "")}</p><button class="btn sm" type="button" data-fx-retry>Réessayer</button></div></div>`;
    }
  };

  const find = (key: string): ChatFileItem | undefined => current?.items.find((i) => i.key === key);

  /** Ce qui s'ouvre d'une page, chacun à son rang dans toute la liste filtrée. */
  const viewable = (page: ChatFilesPage): ViewerFile[] =>
    page.items
      .map((item, i) => ({ ...viewerFile(item), rank: (page.page - 1) * page.per + i + 1 }))
      .filter((f) => f.available && f.src);

  /** ← et → au bout d'une page : la page d'à côté qui a de quoi s'ouvrir (le panneau y reviendra). */
  const turn = async (delta: -1 | 1): Promise<ViewerFile[] | null> => {
    for (let page = state.page + delta; current && page >= 1 && page <= current.pages; page += delta) {
      const got = await chatFiles({ q: state.q.trim(), sorte: state.sorte, de: state.de, fil: state.strand, page, par: PER_PAGE });
      current = got;
      state.page = got.page;
      remember();
      const files = viewable(got);
      if (files.length) return files;
    }
    return null;
  };

  const open = (key: string): void => {
    if (!current) return;
    const files = viewable(current);
    const at = files.findIndex((f) => f.key === key);
    if (at < 0) return;
    openViewer(files, at, {
      blobs: host.blobs,
      me: host.me,
      goTo: (f) => host.goTo(f),
      back: () => openFilesPanel(host),
      total: current.total,
      canTurn: (delta) => !!current && (delta < 0 ? state.page > 1 : state.page < current.pages),
      turn,
    });
  };

  const bindSearch = (): void => {
    input.addEventListener("input", () => {
      state.q = input.value;
      state.page = 1;
      if (pause !== null) window.clearTimeout(pause);
      pause = window.setTimeout(() => {
        pause = null;
        void reload();
      }, SEARCH_PAUSE_MS);
    });
  };
  bindSearch();

  on(el, "[data-fx-sorte]", "click", (_e, b) => {
    state.sorte = (b.dataset.fxSorte ?? "") as FileSort | "";
    state.page = 1;
    kinds.innerHTML = kindsMarkup(current, state);
    void reload();
  });
  on(el, "[data-fx-de]", "click", (_e, b) => {
    state.de = (b.dataset.fxDe ?? "") as PanelState["de"];
    state.page = 1;
    for (const x of el.querySelectorAll<HTMLElement>("[data-fx-de]")) x.setAttribute("aria-pressed", String(x === b));
    void reload();
  });
  on(el, "[data-fx-grid]", "click", (_e, b) => {
    grid = b.dataset.fxGrid === "1";
    write(() => localStorage, GRID_KEY, grid ? "1" : "0");
    for (const x of el.querySelectorAll<HTMLElement>("[data-fx-grid]")) x.setAttribute("aria-pressed", String(x === b));
    paint();
  });
  on(el, "[data-fx-page]", "click", (_e, b) => {
    state.page = Math.max(1, state.page + Number(b.dataset.fxPage));
    void reload().then(() => {
      const list = $<HTMLElement>("[data-fx-list]", el);
      if (list) list.scrollTop = 0;
    });
  });
  on(el, "[data-fx-reset]", "click", () => {
    Object.assign(state, { q: "", sorte: "", de: "", page: 1 });
    input.value = "";
    for (const x of el.querySelectorAll<HTMLElement>("[data-fx-de]")) x.setAttribute("aria-pressed", String(x.dataset.fxDe === ""));
    void reload();
  });
  on(el, "[data-fx-retry]", "click", () => void reload());
  on(el, "[data-fx-msg]", "click", (e, b) => {
    e.stopPropagation();
    const item = find(b.dataset.fxMsg ?? "");
    if (item) host.goTo(viewerFile(item));
  });
  on(el, "[data-fx-save]", "click", (e, b) => {
    e.stopPropagation();
    const item = find(b.dataset.fxSave ?? "");
    if (!item?.url) return;
    host.blobs
      .load(item.url)
      .then((blob) => saveBlob(blob, item.name))
      .catch((err: unknown) => toast(err instanceof Error ? err.message : "Le fichier n'a pas pu être lu.", { ico: "alert" }));
  });
  on(el, "[data-fx-open]", "click", (e, b) => {
    if ((e.target as HTMLElement).closest("[data-fx-save], [data-fx-msg]")) return;
    open(b.dataset.fxOpen ?? "");
  });

  kinds.innerHTML = kindsMarkup(null, state);
  void reload();
  window.setTimeout(() => input.focus(), 30);
}
