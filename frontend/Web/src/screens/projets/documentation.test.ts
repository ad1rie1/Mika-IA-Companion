import { describe, expect, it } from "vitest";
import type { DecisionFull, DocPage, DocPageText, DocSpace } from "../../api/projectDocs";
import type { Sheet } from "../../api/projects";
import { headingsOf, pageHtml, spaceImage, type Heading } from "./docmd";
import {
  decisionOrder, decisionRequest, decisionRoute, decisionStatusRequest, docPlace, draftKey, folderOf, folderPath, homePage, imageAlt, imageMarkdown, imageRemoveRequest, imageRoute, isDirty, moveRequest, nameOf,
  movedOn, optionLines, pagePath, pageRoute, pageTree, rebased, refused, restoreRequest, saveBody, saved, slug, startDraft, tidyMarkdown, typed,
} from "./docparts";
import { initialState } from "./state";
import { pagesView, type DocUi } from "./views/docs";
import type { Ctx } from "./views/todo";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();
const by = { author_kind: "you", author: "toi", via: "web", via_label: "dans le navigateur", tool: "" };
const page = (path: string, over: Partial<DocPage> = {}): DocPage => ({ path, name: nameOf(path), folder: folderOf(path), title: path, version: 1, at: NOW, created_at: NOW, chars: 10, images: [], ...by, ...over });

describe("Documentation : les adresses de la maquette", () => {
  it("le sous-onglet, le mode d'une page et son chemin", () => {
    expect(docPlace([])).toEqual({ tab: "pages", mode: "pages", path: "", rest: [] });
    expect(docPlace(["pages", "guide", "installation.md"])).toMatchObject({ tab: "pages", mode: "pages", path: "guide/installation.md" });
    expect(docPlace(["modifier", "guide", "installation.md"])).toMatchObject({ tab: "pages", mode: "modifier", path: "guide/installation.md" });
    expect(docPlace(["historique", "accueil.md"])).toMatchObject({ tab: "pages", mode: "historique", path: "accueil.md" });
    expect(docPlace(["images", "schema-reseau.png"])).toMatchObject({ tab: "images", path: "schema-reseau.png" });
    expect(docPlace(["decisions", "3", "options"])).toMatchObject({ tab: "decisions", rest: ["3", "options"] });
  });

  it("chaque segment d'un chemin est encodé, les barres restent des barres", () => {
    expect(pageRoute(3, "pages", "guide/installation.md")).toBe("#projets/projets/3/documentation/pages/guide/installation.md");
    expect(pageRoute(3, "modifier", "reference/configuration/delais.md")).toBe("#projets/projets/3/documentation/modifier/reference/configuration/delais.md");
    expect(pageRoute(3, "historique", "accueil.md")).toBe("#projets/projets/3/documentation/historique/accueil.md");
    expect(imageRoute(3, "schema-reseau.png")).toBe("#projets/projets/3/documentation/images/schema-reseau.png");
    expect(decisionRoute(3, 3, "options")).toBe("#projets/projets/3/documentation/decisions/3/options");
    expect(decisionRoute(3)).toBe("#projets/projets/3/documentation/decisions");
  });

  it("l'arborescence : les dossiers d'abord, accueil.md en tête", () => {
    const tree = pageTree([page("notes-de-version.md"), page("accueil.md"), page("guide/installation.md"), page("reference/configuration/delais.md"), page("guide/connexion-rdp.md")]);
    expect(tree.map((n) => n.name)).toEqual(["guide", "reference", "accueil.md", "notes-de-version.md"]);
    expect(tree[0].children.map((n) => n.path)).toEqual(["guide/connexion-rdp.md", "guide/installation.md"]);
    expect(tree[1].children[0].children[0].page?.path).toBe("reference/configuration/delais.md");
    expect(homePage([page("b.md"), page("accueil.md")])?.path).toBe("accueil.md");
    expect(homePage([page("b.md")])?.path).toBe("b.md");
    expect(homePage([])).toBeNull();
  });

  it("le chemin d'une page nouvelle est replié comme le serveur l'attend : il ne corrige rien", () => {
    expect(slug("Dépannage — Windows 11 !")).toBe("depannage-windows-11");
    expect(slug("guide.md")).toBe("guide");
    expect(folderPath("Guide/Avancé ")).toBe("guide/avance");
    expect(pagePath("guide", "Premier scan")).toBe("guide/premier-scan.md");
    expect(pagePath("", "Notes de version")).toBe("notes-de-version.md");
    expect(pagePath("guide", " !! ")).toBe("");
    expect(moveRequest("a.md", "guide/a.md")).toEqual({ route: "documentation/page/deplacer", body: { path: "a.md", to: "guide/a.md" } });
    expect(restoreRequest("a.md", 2, 4)).toEqual({ route: "documentation/page/revenir", body: { path: "a.md", version: 2, base: 4 } });
    expect(imageRemoveRequest("x.png")).toEqual({ route: "documentation/image/retirer", body: { name: "x.png" } });
  });

  it("ce que l'éditeur rend redevient le Markdown de la maison", () => {
    expect(tidyMarkdown("# Titre\n\n* un\n  * deux\n\n```\n* pas touché\n```\n\n\n")).toBe("# Titre\n\n- un\n  - deux\n\n```\n* pas touché\n```\n");
    expect(tidyMarkdown("![1.00](images/schema-reseau.png)")).toBe("![schema reseau](images/schema-reseau.png)\n");
    expect(tidyMarkdown('![1.00](images/x.png "Une légende")')).toBe("![Une légende](images/x.png)\n");
    expect(imageAlt("capture-scan.png")).toBe("capture scan");
    expect(imageMarkdown("capture-scan.png")).toBe("![capture scan](images/capture-scan.png)");
  });
});

describe("Documentation : enregistrer une page, et son conflit", () => {
  const read = { path: "guide/installation.md", version: 3, text: "# Installation\n" };

  it("le brouillon part de la page lue ; une frappe le dit modifié", () => {
    const d = startDraft(read);
    expect(isDirty(d)).toBe(false);
    const t = typed(d, "# Installation\n\nUne ligne.\n");
    expect(isDirty(t)).toBe(true);
    // revenu au texte lu : plus rien n'est en attente
    expect(isDirty(typed(t, "# Installation\n"))).toBe(false);
    expect(isDirty(null)).toBe(false);
    expect(draftKey(3, "guide/installation.md")).toBe("3:guide/installation.md");
  });

  it("l'enregistrement envoie le Markdown, le mot, et la version lue", () => {
    const t = typed(startDraft(read), "# Installation\n\nUne ligne.\n");
    expect(saveBody(t, "  ajout d'une ligne  ")).toEqual({ path: "guide/installation.md", text: "# Installation\n\nUne ligne.\n", word: "ajout d'une ligne", base: 3 });
    expect(saveBody(t, "x".repeat(300)).word).toHaveLength(200);
  });

  it("enregistré : la version rendue devient la version lue", () => {
    const done = saved(typed(startDraft(read), "nouveau\n"), 4);
    expect(done).toMatchObject({ base: 4, read: "nouveau\n", text: "nouveau\n", refusal: "", conflict: false });
    expect(isDirty(done)).toBe(false);
  });

  it("la page a changé depuis : les mots du serveur se disent, et ce qui a été écrit reste entier", () => {
    const mine = "# Installation\n\nCe que j'ai écrit pendant vingt minutes.\n";
    const words = "Cette page a changé depuis ta lecture : elle en est à la version 4, écrite par elle.";
    const d = refused(typed(startDraft(read), mine), words, movedOn(typed(startDraft(read), mine), { version: 4 }));
    expect(d).toMatchObject({ text: mine, base: 3, refusal: words, conflict: true });
    expect(isDirty(d)).toBe(true);
    // une frappe de plus ne l'efface pas
    expect(typed(d, `${mine}Encore.\n`)).toMatchObject({ refusal: words, conflict: true });
  });

  it("reprendre après avoir relu : la version actuelle devient le départ, le texte tapé ne bouge pas", () => {
    const mine = "# Installation\n\nMa version.\n";
    const d = rebased(refused(typed(startDraft(read), mine), "…", true), { version: 4, text: "# Installation\n\nCelle de Mika.\n" });
    expect(d).toMatchObject({ base: 4, text: mine, refusal: "", conflict: false });
    expect(isDirty(d)).toBe(true);
    expect(saveBody(d, "ma version, relue").base).toBe(4);
  });

  it("un autre refus (un champ, une panne) se dit sans être un conflit, et ne perd rien non plus", () => {
    const d = refused(typed(startDraft(read), "x\n"), "Ce chemin n'est pas celui d'une page.");
    expect(d).toMatchObject({ text: "x\n", refusal: "Ce chemin n'est pas celui d'une page.", conflict: false });
    expect(refused(d, "Le serveur de Mika ne répond pas.")).toMatchObject({ text: "x\n", conflict: false });
  });

  it("un 409 n'est un conflit que si la page a bougé : le même texte, une page disparue n'en sont pas", () => {
    const d = typed(startDraft(read), "# Installation\n\n");
    // relue après le 409 : elle en est toujours à la version lue (le serveur a refusé le même texte)
    expect(movedOn(d, { version: 3 })).toBe(false);
    expect(refused(d, "Ce texte est déjà celui de la page.", movedOn(d, { version: 3 }))).toMatchObject({ conflict: false, text: "# Installation\n\n" });
    // elle n'existe plus : rien à reprendre
    expect(movedOn(d, null)).toBe(false);
    // elle a bougé, ou une page nouvelle existe déjà
    expect(movedOn(d, { version: 4 })).toBe(true);
    expect(movedOn(startDraft({ path: "neuve.md", version: 0, text: "" }), { version: 1 })).toBe(true);
  });

  it("le mode Modifier dit ce qui attend, le refus du serveur, et de quoi reprendre", () => {
    const ctx: Ctx = { now: NOW, mobile: false, ui: initialState(), me: "Adrien Moreau" };
    const ui: DocUi = { query: "", folded: new Set(), version: null };
    const sheet = { project: { id: 3, title: "Outils réseau" }, rights: {} } as unknown as Sheet;
    const p: DocPageText = { ...page("guide/installation.md", { version: 4 }), text: "# Installation\n", forgotten: false, can: { write: true } };
    const space: DocSpace = { project: 3, rights: { read: true, write: true }, limits: { page_chars: 1, pages: 1, versions: 50, path_chars: 1, depth: 1, word_chars: 200, image_bytes: 1, images: 1, space_bytes: 1, image_kinds: [] }, pages: [p], folders: ["guide"], images: [], space_used: 0 };
    const draft = refused(typed(startDraft({ path: p.path, version: 3, text: p.text }), "# Installation\n\n<script>alert(1)</script>\n"), "Cette page a changé depuis ta lecture : elle en est à la version 4.", true);
    const data = { space, mode: "modifier" as const, wanted: p.path, page: { value: p, error: null }, history: null, version: null, found: null, draft: () => draft };
    const html = pagesView(sheet, data, ui, ctx);
    expect(html).toContain("Cette page a changé depuis ta lecture : elle en est à la version 4.");
    expect(html).toContain("Ce que tu as écrit est gardé ici.");
    expect(html).toContain('data-p2="docRebase"');
    expect(html).toContain("data-p2-crepe");
    expect(html).not.toContain("<script>alert(1)");
    expect(html).toMatch(/class="p2-st you p2-unsaved">/); // « pas encore enregistrée » se montre
    expect(html).toMatch(/data-p2="docSave"[^>]*>/);
    expect(html).not.toMatch(/data-p2="docSave"[^>]* disabled/);
    // en lecture, la page dit qu'un brouillon l'attend
    const reading = pagesView(sheet, { ...data, mode: "pages" as const }, ui, ctx);
    expect(reading).toContain("des modifications que tu n'as pas enregistrées");
    expect(reading).toContain("p2-dirty");
    // sans le droit d'écrire, ni Modifier, ni Nouvelle page
    const reader = pagesView(sheet, { ...data, space: { ...space, rights: { read: true, write: false } }, page: { value: { ...p, can: { write: false } }, error: null }, draft: () => null }, ui, ctx);
    expect(reader).not.toContain('data-p2="docNew"');
    expect(reader).not.toContain("data-p2-crepe");
    expect(reader).not.toContain(">Modifier<");
  });
});

describe("Documentation : le rendu d'une page n'exécute rien et ne charge rien d'ailleurs", () => {
  const o = { image: (name: string) => (name === "schema-reseau.png" ? "/api/moi/projets/3/documentation/image?name=schema-reseau.png" : null), link: (href: string) => (href === "guide/installation.md" ? "#projets/projets/3/documentation/pages/guide/installation.md" : null) };

  it("une balise écrite dans la page s'affiche telle quelle", () => {
    const html = pageHtml('# Titre <script>alert(1)</script>\n\nTexte <img src=x onerror="alert(2)"> et <iframe src="//x"></iframe>.\n\n- <svg onload=alert(3)>\n\n| a | <b>b</b> |\n|---|---|\n| <i>c</i> | d |\n', o);
    expect(html).not.toMatch(/<script|<img|<iframe|<svg|<b>|<i>c/);
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(2)&quot;&gt;");
    expect(html).toContain("<table>");
  });

  it("un bloc de code et du code en ligne sont échappés", () => {
    const html = pageHtml("```html\n<script>x</script>\n```\n\nEt `<b>ici</b>`.\n", o);
    expect(html).toContain('<pre data-lang="html"><code>&lt;script&gt;x&lt;/script&gt;</code></pre>');
    expect(html).toContain("<code>&lt;b&gt;ici&lt;/b&gt;</code>");
    expect(pageHtml('```"><script>x</script>\ncode\n```', o)).not.toContain("<script");
  });

  it("une image n'est chargée que si elle est de l'espace ; toute autre adresse se dit, sans être chargée", () => {
    expect(pageHtml("![Le schéma](images/schema-reseau.png)", o)).toContain('<img src="/api/moi/projets/3/documentation/image?name=schema-reseau.png" alt="Le schéma"');
    const elsewhere = pageHtml("![pixel](https://ailleurs.example/pixel.gif) ![x](//ailleurs.example/x.png) ![y](data:image/svg+xml,<svg/onload=alert(1)>)", o);
    expect(elsewhere).not.toContain("<img");
    expect(elsewhere).toContain("image d'ailleurs, non chargée");
    expect(pageHtml("![perdue](images/absente.png)", o)).toContain("image introuvable");
    expect(pageHtml("![perdue](images/absente.png)", o)).not.toContain("<img");
    // sans résolveur (un texte hors de l'espace), aucune image
    expect(pageHtml("![Le schéma](images/schema-reseau.png)")).not.toContain("<img");
    expect(spaceImage("images/schema-reseau.png")).toBe("schema-reseau.png");
    expect(spaceImage("images/../secret.png")).toBe("");
    expect(spaceImage("https://x/images/a.png")).toBe("");
    expect(spaceImage("images/a/b.png")).toBe("");
  });

  it("un lien ne s'ouvre que vers une page de l'espace ou une adresse http(s), sans référent", () => {
    expect(pageHtml("[L'installer](guide/installation.md)", o)).toContain('<a href="#projets/projets/3/documentation/pages/guide/installation.md">L&#39;installer</a>');
    expect(pageHtml("[Le site](https://exemple.org/a?b=1&c=2)", o)).toContain('<a href="https://exemple.org/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">Le site</a>');
    for (const bad of ["[clic](javascript:alert(1))", "[clic](JaVaScRiPt:alert(1))", "[clic](data:text/html,<script>alert(1)</script>)", "[clic](vbscript:x)", "[clic](page-inconnue.md)"]) {
      const html = pageHtml(bad, o);
      expect(html).not.toContain("<a ");
      expect(html).not.toContain("<script");
      expect(html).toContain("p2-md-nolink");
    }
  });

  it("aucun attribut ne reçoit de texte non échappé", () => {
    const html = pageHtml('![a" onerror="alert(1)](images/schema-reseau.png "t\\" onload=\\"x")\n\n[x" onmouseover="alert(2)](https://exemple.org/"onclick="alert(3))', o);
    expect(html).not.toMatch(/ onerror="|onmouseover="|onclick="| onload="/);
    expect(pageHtml('[x](`"onmouseover=alert(1)//`)', o)).not.toMatch(/"onmouseover=alert/);
  });

  it("les titres font le sommaire ; ceux d'un bloc de code n'en sont pas", () => {
    const titles: Heading[] = [];
    const html = pageHtml("# Installation\n\n## Ce qu'il faut\n\n```\n## pas un titre\n```\n\n### `Dépannage` rapide\n", { ...o, headings: titles });
    expect(titles).toEqual([{ level: 1, text: "Installation", id: "p2-t0" }, { level: 2, text: "Ce qu'il faut", id: "p2-t1" }, { level: 3, text: "Dépannage rapide", id: "p2-t2" }]);
    expect(html).toContain('<h2 id="p2-t1">Ce qu&#39;il faut</h2>');
    expect(headingsOf("# A\n\n```\n## non\n```\n## B\n")).toEqual([{ level: 1, text: "A" }, { level: 2, text: "B" }]);
  });

  it("les listes imbriquées, les cases, le gras, l'italique, les citations", () => {
    const html = pageHtml("- un\n  - deux\n- [x] fait\n- [ ] à faire\n\n1. premier\n2. second\n\n> **Note** : _attention_.\n", o);
    expect(html).toContain("<ul><li>un<ul><li>deux</li></ul></li>");
    expect(html).toContain('<li class="tache faite">');
    expect(html).toContain("<ol><li>premier</li><li>second</li></ol>");
    expect(html).toContain("<blockquote><p><strong>Note</strong> : <em>attention</em>.</p></blockquote>");
  });
});

describe("Documentation : les décisions techniques", () => {
  const full: DecisionFull = { number: 3, title: "Le journal est en JSON Lines", choice: "Un refus par ligne.", status: "active", status_label: "en vigueur", author_kind: "self", author: "Mika", at: NOW, replaces: 1, replaced_by: 0, objective: 2,
    can: { modify: true, replace: true, withdraw: true, restore: false, why: "" }, context: "Le ticket n° 4.", options: "Un fichier texte : illisible\nUne base SQLite", reason: "Se lit avec tail." };

  it("consigner : ses textes, et celle qu'elle remplace", () => {
    expect(decisionRequest({ title: " Le journal est en JSON Lines ", choice: "Un refus par ligne.", context: "", reason: "", options: "", replaces: "1" }, null))
      .toEqual({ route: "decision/ajouter", body: { title: "Le journal est en JSON Lines", choice: "Un refus par ligne.", replaces: 1 } });
    expect(decisionRequest({ title: "T", choice: "C", replaces: "" }, null).body).toEqual({ title: "T", choice: "C" });
  });

  it("modifier : seulement ce qui change ; un texte facultatif vidé est retiré", () => {
    expect(decisionRequest({ title: full.title, choice: full.choice, context: "", reason: "Se lit avec tail et jq.", options: full.options }, full))
      .toEqual({ route: "decision/modifier", body: { number: 3, context: "", reason: "Se lit avec tail et jq." } });
    expect(decisionStatusRequest(3, "withdrawn")).toEqual({ route: "decision/statut", body: { number: 3, status: "withdrawn" } });
  });

  it("les options écartées, une par ligne ; les décisions en vigueur d'abord", () => {
    expect(optionLines(full.options)).toEqual([{ title: "Un fichier texte", why: "illisible" }, { title: "Une base SQLite", why: "" }]);
    expect(optionLines("")).toEqual([]);
    expect(decisionOrder([{ status: "superseded" }, { status: "active" }, { status: "withdrawn" }]).map((d) => d.status)).toEqual(["active", "withdrawn", "superseded"]);
  });
});
