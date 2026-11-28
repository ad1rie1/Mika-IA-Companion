/**
 * La visionneuse des fichiers du chat (ADR 0312, maquette `maquette/ecrans/chat-fichiers.js`) : une image en grand, un
 * PDF dans le lecteur du navigateur, un texte ou un Markdown (rendu ou source), un CSV en tableau, un son à écouter ;
 * les autres sortes se disent et s'enregistrent. « Enregistrer », « Dans la conversation », ← et → d'un fichier à
 * l'autre.
 *
 * Rien n'y est jamais rendu en HTML d'ailleurs ni exécuté : le serveur sert toujours en pièce jointe, la visionneuse
 * lit les octets (`blobs.ts`). Un texte est échappé, un Markdown passe par le rendu échappé des pages de
 * documentation (`docmd.ts`, sans image ni lien vers l'espace), un PDF n'est montré que s'il commence comme un PDF, et
 * seulement sous la sorte `application/pdf`.
 */
import type { FileSort } from "../../api/chat";
import { dayAndClock } from "../../shared/dates";
import { sizeLabel } from "../../shared/text";
import { $, h, on } from "../../shell/dom";
import { openModal, toast } from "../../shell/float";
import { ico } from "../../shell/icons";
import { mikaAvatar } from "../../mika/face";
import { pageHtml } from "../projets/docmd";
import { FileLoadError, saveBlob, type FileBlobs } from "./blobs";
import { extOf, isMarkdown, looksLikePdf, NOT_YET, parseCsv, reasonWords, textPreview, tile, typeLabel } from "./files";

/** Un fichier tel que la visionneuse le montre. */
export interface ViewerFile {
  key: string;
  name: string;
  sorte: FileSort;
  mime: string;
  size?: number;
  from: "toi" | "mika";
  /** Quand il est parti (ms). */
  at: number;
  /** Où lire ses octets (`blobs.ts`) : `/files/<id>`, ou la copie de ce navigateur ; rien s'il ne se lit pas. */
  src?: string;
  available: boolean;
  reason?: string;
  /** Le message qui le porte (son numéro au serveur), et sa place dans ce message. */
  message?: number;
  index?: number;
  /** Sa place dans toute la liste d'où on l'ouvre (à partir de 1), quand elle s'étend sur plusieurs pages. */
  rank?: number;
}

export interface ViewerHost {
  blobs: FileBlobs;
  /** Ton rond (l'avatar de qui est connecté). */
  me: string;
  /** Retrouver l'adresse d'une pièce que le fil ne connaît pas encore (lue depuis) ; rien : toujours pas. */
  resolve?: (f: ViewerFile) => Promise<ViewerFile | null>;
  /** « Dans la conversation » : le message qui porte ce fichier. */
  goTo?: (f: ViewerFile) => void;
  /** « Tous les fichiers » : revenir au panneau d'où l'on vient. */
  back?: () => void;
  /** La liste s'étend sur plusieurs pages : combien en tout (le compte dit alors `rank / total`)… */
  total?: number;
  /** … s'il y a une page avant (-1) ou après (1), et la lire : ← et → passent d'une page à l'autre. */
  canTurn?: (delta: -1 | 1) => boolean;
  turn?: (delta: -1 | 1) => Promise<ViewerFile[] | null>;
}

function whoMarkup(f: ViewerFile, me: string, now: number): string {
  const avatar = f.from === "mika" ? mikaAvatar("xs") : me;
  return `<span class="vw-who">${avatar}<span>${f.from === "mika" ? "Mika" : "Toi"}${f.at ? ` · ${h(dayAndClock(f.at, now))}` : ""}</span></span>`;
}

function noneMarkup(f: ViewerFile, title: string, text: string, save: boolean, retry = false): string {
  return `<div class="vw-none">${tile({ ...f, src: undefined }, "xl")}<b>${h(title)}</b>${text ? `<p>${h(text)}</p>` : ""}
    <div class="row">${retry ? `<button class="btn" type="button" data-vw-retry>${ico("refresh", "sm")}Réessayer</button>` : ""}
    ${save ? `<button class="btn primary" type="button" data-vw-save>${ico("download", "sm")}Enregistrer</button>` : ""}</div></div>`;
}

/** Ce qu'un fichier qui ne se lit pas dit, selon sa raison. */
function unavailableMarkup(f: ViewerFile): string {
  if (f.reason === NOT_YET) {
    return noneMarkup(f, "Ce fichier n'est pas encore arrivé", "Il sera là dès que ton message sera parti : réessaie dans un instant.", false, true);
  }
  if (f.reason === "unkept") return noneMarkup(f, "Ce fichier n'a pas été gardé", "Son nom reste dans la conversation, pas son contenu.", false);
  const why = reasonWords(f.reason);
  return noneMarkup(f, "Ce fichier a été retiré", `${why.charAt(0).toUpperCase()}${why.slice(1)} : son nom reste dans la conversation, plus son contenu.`, false);
}

function sourceMarkup(lines: readonly string[]): string {
  return `<pre class="vw-src">${lines.map((l, i) => `<span class="ln">${i + 1}</span>${h(l) || " "}`).join("\n")}</pre>`;
}

function cutNote(truncated: boolean, what: string): string {
  return truncated ? `<span class="small muted">· ${h(what)}</span>` : "";
}

export function openViewer(files: readonly ViewerFile[], index: number, host: ViewerHost): void {
  let list = [...files];
  let at = Math.max(0, Math.min(index, list.length - 1));
  if (!list.length) return;
  let token = 0;
  let mdSource = false;
  let turning = false;
  /** Les pièces déjà demandées au serveur d'elles-mêmes (sans adresse) : une fois chacune ; « Réessayer » redemande. */
  const asked = new Set<string>();
  /** Les adresses `blob:` que la visionneuse a faites elle-même (une copie sous sa sorte) : révoquées en partant. */
  let owned: string[] = [];
  const release = (): void => {
    for (const url of owned) URL.revokeObjectURL(url);
    owned = [];
  };

  const el = openModal({ title: list[at].name, size: "wide", head: `<span class="vw-acts" data-vw-acts></span>`, body: "", foot: " " });
  el.classList.add("fx-viewer");
  el.tabIndex = -1;
  const body = $<HTMLElement>(".modal-body", el)!;
  const foot = $<HTMLElement>(".modal-foot", el)!;
  const acts = $<HTMLElement>("[data-vw-acts]", el)!;
  const title = $<HTMLElement>(".modal-head h2", el)!;

  // ← et → tant que la fenêtre est ouverte, où que soit le focus (un bouton cliqué peut avoir été redessiné)
  const keys = (e: KeyboardEvent): void => {
    if (!el.isConnected || e.defaultPrevented) return;
    const target = e.target as HTMLElement | null;
    if (target?.closest?.("input, textarea, select, [contenteditable]")) return;
    if (e.key === "ArrowLeft") void go(-1);
    else if (e.key === "ArrowRight") void go(1);
  };
  document.addEventListener("keydown", keys);
  // la fenêtre fermée (Échap, la croix, un clic à côté, une autre fenêtre) : ses copies et son clavier partent
  const root = el.closest(".modal-scrim")?.parentElement;
  if (root) {
    const gone = new MutationObserver(() => {
      if (el.isConnected) return;
      gone.disconnect();
      document.removeEventListener("keydown", keys);
      token += 1;
      release();
    });
    gone.observe(root, { childList: true });
  }

  const paint = (): void => {
    const f = list[at];
    token += 1;
    release();
    el.classList.remove("fx-image", "fx-pdf", "fx-texte", "fx-tableau", "fx-autre", "fx-none");
    el.classList.add(f.available && f.src ? `fx-${f.sorte}` : "fx-none");
    title.textContent = f.name;
    el.setAttribute("aria-label", f.name);
    const saving = f.available && !!f.src;
    acts.innerHTML = `${saving ? `<button class="btn sm" type="button" data-vw-save title="Enregistrer" aria-label="Enregistrer">${ico("download", "sm")}<span class="lbl">Enregistrer</span></button>` : ""}
      ${host.goTo && typeof f.message === "number" ? `<button class="btn ghost sm" type="button" data-vw-fil title="Voir le message dans la conversation" aria-label="Dans la conversation">${ico("chat", "sm")}<span class="lbl">Dans la conversation</span></button>` : ""}`;
    const before = at > 0 || !!host.canTurn?.(-1);
    const after = at < list.length - 1 || !!host.canTurn?.(1);
    const count = host.total && f.rank ? `${f.rank} / ${host.total}` : `${at + 1} / ${list.length}`;
    const nav = before || after
      ? `<span class="vw-count">${count}</span>
        <button class="btn icon ghost sm" type="button" data-vw-nav="-1" title="Précédent (←)" aria-label="Précédent"${before ? "" : " disabled"}>${ico("chev-left")}</button>
        <button class="btn icon ghost sm" type="button" data-vw-nav="1" title="Suivant (→)" aria-label="Suivant"${after ? "" : " disabled"}>${ico("chev-right")}</button>`
      : "";
    const meta = [typeLabel(f.name, f.sorte, f.mime), sizeLabel(f.size || undefined)].filter(Boolean).join(" · ");
    foot.innerHTML = `${whoMarkup(f, host.me, Date.now())}<span class="muted small vw-type">${h(meta)}</span><span class="grow"></span>
      ${host.back ? `<button class="btn ghost sm" type="button" data-vw-back>${ico("chev-left", "sm")}Tous les fichiers</button>` : ""}${nav}`;
    if (!f.available || !f.src) {
      body.innerHTML = unavailableMarkup(f);
      // une pièce dont le fil n'a pas encore l'adresse : on la demande, une fois, avant de dire qu'elle manque
      if (f.reason === NOT_YET && host.resolve && !asked.has(f.key)) {
        asked.add(f.key);
        void ask(f, token, false);
      }
      return;
    }
    body.innerHTML = `<div class="vw-wait"><i class="spin"></i>Chargement…</div>`;
    void fill(f, token);
  };

  const fill = async (f: ViewerFile, mine: number): Promise<void> => {
    let blob: Blob;
    try {
      blob = await host.blobs.load(f.src ?? "");
    } catch (err) {
      if (mine !== token) return;
      const gone = err instanceof FileLoadError && err.status === 410;
      body.innerHTML = gone
        ? noneMarkup(f, "Ce fichier a été retiré", "Son nom reste dans la conversation, plus son contenu.", false)
        : noneMarkup(f, "Le fichier n'a pas pu être lu", err instanceof Error ? err.message : "", false, true);
      return;
    }
    if (mine !== token) return;
    const html = await contentFor(f, blob, mine);
    if (mine !== token || html === null) return;
    body.innerHTML = html;
    const img = $<HTMLImageElement>(".vw-img img", body);
    img?.addEventListener("error", () => {
      if (mine === token) body.innerHTML = noneMarkup(f, "Cette image ne s'affiche pas", "Enregistre-la pour l'ouvrir avec ton application.", true);
    });
  };

  const own = (blob: Blob, type: string): string => {
    const url = URL.createObjectURL(blob.type === type ? blob : new Blob([blob], { type }));
    owned.push(url);
    return url;
  };

  /** Ce que montre un fichier lu ; `null` : on est passé à un autre entre-temps (rien n'a été fait pour celui-ci). */
  const contentFor = async (f: ViewerFile, blob: Blob, mine: number): Promise<string | null> => {
    const ext = extOf(f.name).toUpperCase();
    if (f.sorte === "image") {
      return `<div class="vw-img"><img src="${h(own(blob, blob.type || "application/octet-stream"))}" alt="${h(f.name)}"></div>`;
    }
    if (f.sorte === "pdf") {
      const head = new Uint8Array(await blob.slice(0, 1100).arrayBuffer());
      if (mine !== token) return null;
      if (!looksLikePdf(head)) return noneMarkup(f, "Ce fichier ne s'ouvre pas en PDF", "Il n'en a pas l'en-tête. Enregistre-le pour l'ouvrir avec ton application.", true);
      // un navigateur sans lecteur intégré (Chrome sur Android) le téléchargerait sous un nom de hasard
      if (navigator.pdfViewerEnabled === false) return noneMarkup(f, "Ce navigateur n'affiche pas les PDF", "Enregistre-le pour l'ouvrir avec ton application.", true);
      return `<div class="vw-pdf"><iframe src="${h(own(blob, "application/pdf"))}" title="${h(f.name)}"></iframe></div>`;
    }
    if (f.sorte === "texte" || f.sorte === "tableau") {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      if (mine !== token) return null;
      const text = textPreview(bytes);
      if (f.sorte === "tableau") {
        const table = parseCsv(text.text);
        if (!table.rows.length) return noneMarkup(f, "Ce tableau est vide", "", true);
        const [head, ...rows] = table.rows;
        const sep = table.separator === "\t" ? "tabulation" : `« ${table.separator} »`;
        const cell = (c: string): string => `<td>${h(c)}</td>`;
        return `<div class="vw-text"><div class="vw-text-bar"><span class="small muted">${rows.length} ligne${rows.length > 1 ? "s" : ""} · ${table.columns} colonne${table.columns > 1 ? "s" : ""} · séparateur ${h(sep)}</span>${cutNote(table.truncated || text.truncated, "les premières seulement")}</div>
          <div class="vw-csv"><table class="tbl"><thead><tr>${head.map((c) => `<th>${h(c)}</th>`).join("")}</tr></thead>
          <tbody>${rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("")}</tbody></table></div></div>`;
      }
      const n = text.lines.length;
      const count = `<span class="small muted">${n.toLocaleString("fr-FR")} ligne${n > 1 ? "s" : ""}</span>${cutNote(text.truncated, "coupé : enregistre-le pour tout lire")}`;
      if (isMarkdown(f.name, f.mime)) {
        const seg = `<div class="seg" role="group" aria-label="Affichage"><button type="button" data-vw-md="0" aria-pressed="${!mdSource}">Rendu</button><button type="button" data-vw-md="1" aria-pressed="${mdSource}">Source</button></div>`;
        return `<div class="vw-text"><div class="vw-text-bar">${seg}${count}</div>${mdSource ? sourceMarkup(text.lines) : `<div class="vw-md p2-md">${pageHtml(text.text)}</div>`}</div>`;
      }
      return `<div class="vw-text"><div class="vw-text-bar">${count}</div>${sourceMarkup(text.lines)}</div>`;
    }
    if (f.mime.toLowerCase().startsWith("audio/")) {
      return `<div class="vw-audio">${tile({ ...f, src: undefined }, "xl")}<audio controls src="${h(own(blob, f.mime.split(";", 1)[0]))}"></audio></div>`;
    }
    return noneMarkup(f, `Pas d'aperçu pour un fichier ${ext || "de cette sorte"}`, `${typeLabel(f.name, f.sorte, f.mime)}${f.size ? ` · ${sizeLabel(f.size)}` : ""}. Enregistre-le pour l'ouvrir avec ton application.`, true);
  };

  /** Demander une pièce au serveur ; `told` : dire qu'elle n'est toujours pas là (un clic sur « Réessayer »). */
  const ask = async (f: ViewerFile, mine: number, told: boolean): Promise<void> => {
    const got = await host.resolve?.(f);
    if (mine !== token || !el.isConnected) return;
    if (got) {
      list[at] = got;
      paint();
    } else if (told) toast("Pas encore : ton message n'est pas encore arrivé au serveur.", { ico: "clock" });
  };

  const go = async (delta: -1 | 1): Promise<void> => {
    const next = at + delta;
    if (next >= 0 && next < list.length) {
      at = next;
      paint();
      return;
    }
    // au bout de la page : la page d'à côté, si la liste en a une
    if (turning || !host.turn || !host.canTurn?.(delta)) return;
    turning = true;
    const got = await host.turn(delta).catch(() => null);
    turning = false;
    if (!el.isConnected || !got?.length) return;
    list = [...got];
    at = delta > 0 ? 0 : list.length - 1;
    paint();
  };

  on(el, "[data-vw-nav]", "click", (_e, b) => void go(Number(b.dataset.vwNav) < 0 ? -1 : 1));
  on(el, "[data-vw-md]", "click", (_e, b) => {
    mdSource = b.dataset.vwMd === "1";
    paint();
  });
  on(el, "[data-vw-back]", "click", () => host.back?.());
  on(el, "[data-vw-fil]", "click", () => host.goTo?.(list[at]));
  on(el, "[data-vw-retry]", "click", () => {
    const f = list[at];
    if (f.available && f.src) paint();
    else if (host.resolve) void ask(f, token, true);
  });
  on(el, "[data-vw-save]", "click", () => {
    const f = list[at];
    if (!f.src) return;
    host.blobs
      .load(f.src)
      .then((blob) => saveBlob(blob, f.name))
      .catch((err: unknown) => toast(err instanceof Error ? err.message : "Le fichier n'a pas pu être lu.", { ico: "alert" }));
  });

  paint();
  window.setTimeout(() => el.focus(), 30);
}
