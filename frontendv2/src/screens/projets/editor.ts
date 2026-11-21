/**
 * L'éditeur d'une page de documentation : **Milkdown, par son éditeur Crepe** (`@milkdown/crepe`, licence MIT) — la
 * bibliothèque de la maquette validée (`maquette/vendor/milkdown-crepe.js`, `output/…/web/v2/editeur/entree.js`). On
 * écrit dans la page mise en forme ; elle garde du vrai Markdown. Ce module n'est chargé qu'à l'ouverture du mode
 * Modifier (`import()` dans `documentation.ts`) : il forme son propre morceau, avec ses feuilles de style.
 *
 * N'est embarqué que ce que la page sert : ni LaTeX, ni IA. Le menu à la barre oblique et la barre d'outils sont en
 * français ; les couleurs sont celles du client (les variables `--crepe-…` de `styles/ecrans/projets.css`), et le
 * thème des blocs de code suit le clair et le sombre.
 *
 * **Ce que la bibliothèque laisse passer** (vérifié sur la version installée) : un lien n'a d'adresse que http(s),
 * mailto, tel, ftp, ou relative (`sanitizeLinkHref`) ; du HTML écrit dans le Markdown s'affiche comme du texte
 * (`textContent`), jamais interprété ; l'aperçu d'un bloc de code n'existe pas sans LaTeX. Reste l'image : elle
 * chargerait n'importe quelle adresse — `imageUrl` (son `proxyDomURL`) décide donc de ce qui se charge, et le client
 * ne laisse charger que les images de l'espace de documentation, servies par l'API.
 */
import { oneDark } from "@codemirror/theme-one-dark";
import { CrepeBuilder } from "@milkdown/crepe/builder";
import { blockEdit } from "@milkdown/crepe/feature/block-edit";
import { codeMirror, setCodeMirrorTheme } from "@milkdown/crepe/feature/code-mirror";
import { cursor } from "@milkdown/crepe/feature/cursor";
import { imageBlock } from "@milkdown/crepe/feature/image-block";
import { linkTooltip } from "@milkdown/crepe/feature/link-tooltip";
import { listItem } from "@milkdown/crepe/feature/list-item";
import { placeholder } from "@milkdown/crepe/feature/placeholder";
import { table } from "@milkdown/crepe/feature/table";
import { toolbar } from "@milkdown/crepe/feature/toolbar";
import { topBar } from "@milkdown/crepe/feature/top-bar";
import "@milkdown/crepe/theme/common/prosemirror.css";
import "@milkdown/crepe/theme/common/reset.css";
import "@milkdown/crepe/theme/common/block-edit.css";
import "@milkdown/crepe/theme/common/code-mirror.css";
import "@milkdown/crepe/theme/common/cursor.css";
import "@milkdown/crepe/theme/common/image-block.css";
import "@milkdown/crepe/theme/common/link-tooltip.css";
import "@milkdown/crepe/theme/common/list-item.css";
import "@milkdown/crepe/theme/common/placeholder.css";
import "@milkdown/crepe/theme/common/toolbar.css";
import "@milkdown/crepe/theme/common/table.css";
import "@milkdown/crepe/theme/common/top-bar.css";

const FR = {
  blockEdit: {
    textGroup: { label: "Texte", text: { label: "Texte" }, h1: { label: "Titre 1" }, h2: { label: "Titre 2" }, h3: { label: "Titre 3" }, h4: { label: "Titre 4" }, h5: null, h6: null,
      quote: { label: "Citation" }, divider: { label: "Séparateur" } },
    listGroup: { label: "Listes", bulletList: { label: "Liste à puces" }, orderedList: { label: "Liste numérotée" }, taskList: { label: "Liste à cocher" } },
    advancedGroup: { label: "Blocs", image: { label: "Image" }, codeBlock: { label: "Bloc de code" }, table: { label: "Tableau" }, math: null },
  },
  topBar: { headingOptions: [{ label: "Texte", level: null }, { label: "Titre 1", level: 1 }, { label: "Titre 2", level: 2 }, { label: "Titre 3", level: 3 }, { label: "Titre 4", level: 4 }] },
  linkTooltip: { inputPlaceholder: "Colle une adresse…" },
  codeMirror: { searchPlaceholder: "Chercher un langage", noResultText: "Aucun langage", copyText: "Copier", previewLabel: "Aperçu", previewToggleText: (only: boolean) => (only ? "Modifier" : "Masquer") },
};

export interface EditorOptions {
  /** Le Markdown de départ. */
  markdown: string;
  /** À chaque changement, le Markdown de la page. */
  onChange(markdown: string): void;
  /** Une image choisie, déposée ou collée : elle part au serveur ; rend l'adresse à écrire dans la page (`images/<nom>`). */
  upload(file: File): Promise<string>;
  /** L'adresse à charger pour une image que la page cite : celle de l'API pour une image de l'espace, rien d'ailleurs. */
  imageUrl(src: string): string;
}

export interface PageEditor {
  /** Résolu quand l'éditeur est posé ; rejeté s'il n'a pas pu l'être. */
  ready: Promise<void>;
  markdown(): string;
  /** Insère du Markdown après le bloc où est le curseur : rien n'est remplacé. */
  insert(markdown: string): void;
  hasFocus(): boolean;
  focus(): void;
  destroy(): void;
}

/** Ce qu'on lit de la vue et de l'analyseur de Milkdown, pris par leur nom dans son contexte (sans en importer les types). */
interface ViewLike {
  state: { selection: { node?: unknown; to: number; $to: { depth: number; pos: number; after(depth: number): number } }; tr: { insert(pos: number, content: unknown): { scrollIntoView(): unknown } } };
  dispatch(tr: unknown): void;
  hasFocus(): boolean;
  focus(): void;
}
type ParserLike = (markdown: string) => { content: unknown } | null;

const isDark = (): boolean => document.documentElement.dataset.theme === "dark";

export function createEditor(root: HTMLElement, o: EditorOptions): PageEditor {
  const crepe = new CrepeBuilder({ root, defaultValue: o.markdown });
  crepe
    .addFeature(cursor)
    .addFeature(listItem)
    .addFeature(linkTooltip, FR.linkTooltip)
    .addFeature(imageBlock, {
      onUpload: o.upload, inlineOnUpload: o.upload, blockOnUpload: o.upload, proxyDomURL: o.imageUrl,
      inlineUploadButton: "Téléverser", inlineUploadPlaceholderText: "ou colle une adresse", inlineConfirmButton: "Valider",
      blockUploadButton: "Téléverser une image", blockUploadPlaceholderText: "ou colle l'adresse d'une image", blockConfirmButton: "Valider", blockCaptionPlaceholderText: "Une légende…",
    })
    .addFeature(blockEdit, FR.blockEdit)
    .addFeature(placeholder, { text: "Écris ici, ou tape « / » pour insérer un bloc…", mode: "block" })
    .addFeature(toolbar)
    .addFeature(codeMirror, isDark() ? { ...FR.codeMirror, theme: oneDark } : FR.codeMirror)
    .addFeature(table)
    .addFeature(topBar, FR.topBar);
  let live = false;
  let gone = false;
  crepe.on((listen) => {
    listen.markdownUpdated((_ctx, markdown, before) => {
      if (live && markdown !== before) o.onChange(markdown);
    });
  });
  const view = (): ViewLike | null => {
    try {
      return crepe.editor.action((ctx) => ctx.get<ViewLike, "editorView">("editorView"));
    } catch {
      return null;
    }
  };
  // le thème des blocs de code suit le clair et le sombre, même changé pendant qu'on écrit
  const theme = new MutationObserver(() => {
    if (live && !gone) crepe.editor.action(setCodeMirrorTheme(isDark() ? oneDark : []));
  });
  const ready = crepe.create().then(() => {
    live = true;
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  });
  return {
    ready,
    markdown: () => crepe.getMarkdown(),
    insert: (markdown) => {
      if (!live || gone) return;
      crepe.editor.action((ctx) => {
        const v = ctx.get<ViewLike, "editorView">("editorView");
        const doc = ctx.get<ParserLike, "parser">("parser")(markdown);
        if (!doc) return;
        const { selection } = v.state;
        const end = selection.$to;
        const at = selection.node ? selection.to : end.depth ? end.after(1) : end.pos;
        v.dispatch(v.state.tr.insert(at, doc.content).scrollIntoView());
      });
    },
    hasFocus: () => (live && !gone ? (view()?.hasFocus() ?? false) : false),
    focus: () => {
      if (live && !gone) view()?.focus();
    },
    destroy: () => {
      gone = true;
      theme.disconnect();
      void ready.then(() => crepe.destroy()).catch(() => undefined);
    },
  };
}
