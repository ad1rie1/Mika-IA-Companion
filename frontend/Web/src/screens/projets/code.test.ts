import { describe, expect, it } from "vitest";
import type { Blob, Commit, CommitDetail, DiffFile, Hunk, IssueDetail, IssuePage, PullDetail, PullLine, Tree } from "../../api/projectCode";
import type { Approval, EntryDetail, Sheet } from "../../api/projects";
import {
  branchRoute, byFolder, bySha, checksRoute, codePlace, commitRoute, fileRoute, isMarkdown, linesOf, mergeFacts, mergeLines, mergeRequest, mergeStage, parsePullKey, pullCommentRequest, pullEditRequest, pullKey,
  pullRoute, repoLink, sideRows, sizeWords, splitRef, tokens, unifiedRows,
} from "./codeparts";
import { initialState } from "./state";
import { commitsView, filesView, renderedFile, type CodeUi } from "./views/code";
import { issuesView, mergeBlock, mergeConfirm, pullsView } from "./views/codehost";
import type { Ctx } from "./views/todo";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();
const SHA = "8f41c2e09d77aa00000000000000000000000000";
const ctx = (): Ctx => ({ now: NOW, mobile: false, ui: initialState(), me: "Adrien Moreau" });
const ui = (): CodeUi => ({ side: false, commitsRef: "", open: new Set(), whole: new Set(), mdSource: false });
const sheet = { project: { id: 3, title: "Outils réseau" }, rights: { pull_write: true } } as unknown as Sheet;
const got = <T>(value: T): { value: T; error: null } => ({ value, error: null });

function commit(over: Partial<Commit> = {}): Commit {
  return { sha: SHA, short: "8f41c2e", title: "rdp : connexion à l'hôte d'essai", at: NOW - 3_600_000, author_kind: "self", author: "Mika", outside: false, branch: "work/objective-2", base: false, merge: false,
    files: 1, insertions: 2, deletions: 1, objective: 2, ticket: 0, url: "", ...over };
}

const hunk = (lines: Array<[string, number, number, string]>): Hunk => ({ header: "@@ -1,3 +1,4 @@", lines: lines.map(([kind, old, n, text]) => ({ kind, old, new: n, text })) });

function file(over: Partial<DiffFile> = {}): DiffFile {
  return { path: "outils_reseau/rdp.py", status: "modified", status_label: "modifié", insertions: 2, deletions: 1, binary: false, cut: false, hunks: [hunk([[" ", 1, 1, "import socket"], ["-", 2, 0, "PORT = 3388"], ["+", 0, 2, "PORT = 3389"], ["+", 0, 3, "DELAI = 3.0"]])], ...over };
}

describe("Code : les adresses de la maquette", () => {
  it("le sous-onglet et ce qui le suit ; inconnu : Fichiers", () => {
    expect(codePlace([])).toEqual({ tab: "fichiers", rest: [] });
    expect(codePlace(["pulls", "11", "fichiers"])).toEqual({ tab: "pulls", rest: ["11", "fichiers"] });
    expect(codePlace(["ailleurs", "x"])).toEqual({ tab: "fichiers", rest: [] });
  });

  it("la branche d'une adresse de fichier peut porter des barres : la plus longue branche connue l'ouvre", () => {
    const refs = ["main", "work/objective-2", "work/objective-2-1"];
    expect(splitRef(["work", "objective-2", "outils_reseau", "rdp.py"], refs, "main")).toEqual({ ref: "work/objective-2", path: "outils_reseau/rdp.py" });
    expect(splitRef(["work", "objective-2-1"], refs, "main")).toEqual({ ref: "work/objective-2-1", path: "" });
    expect(splitRef(["main", "README.md"], refs, "main")).toEqual({ ref: "main", path: "README.md" });
    expect(splitRef([], refs, "main")).toEqual({ ref: "main", path: "" });
    // aucune branche connue : le premier segment (un commit)
    expect(splitRef(["8f41c2e", "a", "b.py"], refs, "main")).toEqual({ ref: "8f41c2e", path: "a/b.py" });
  });

  it("chaque segment est encodé, les barres restent des barres", () => {
    expect(fileRoute(3, "work/objective-2", "docs/à lire.md")).toBe("#projets/projets/3/code/fichiers/work/objective-2/docs/%C3%A0%20lire.md");
    expect(fileRoute(3, "main")).toBe("#projets/projets/3/code/fichiers/main");
    expect(commitRoute(3, commit())).toBe("#projets/projets/3/code/commits/8f41c2e");
    expect(branchRoute(3, "work/objective-2")).toBe("#projets/projets/3/code/branches/work/objective-2");
    expect(checksRoute(3, SHA, "journal")).toBe("#projets/projets/3/code/ci/8f41c2e/journal");
  });

  it("une pull request se nomme par son numéro, ou par son objectif tant qu'elle n'en a pas", () => {
    expect(pullKey({ number: 11 })).toBe("11");
    expect(pullKey({ number: 0, objective: { id: 3 } })).toBe("o3");
    expect(parsePullKey("11")).toEqual({ number: 11, objective: 0 });
    expect(parsePullKey("o3")).toEqual({ number: 0, objective: 3 });
    expect(parsePullKey("x")).toEqual({ number: 0, objective: 0 });
    expect(pullRoute(3, { number: 11 }, "fichiers")).toBe("#projets/projets/3/code/pulls/11/fichiers");
  });

  it("un commit se retrouve par son empreinte, courte ou entière", () => {
    const items = [commit(), commit({ sha: "cdd07ae46e31".padEnd(40, "0"), short: "cdd07ae" })];
    expect(bySha(items, "8f41c2e")?.sha).toBe(SHA);
    expect(bySha(items, SHA)?.short).toBe("8f41c2e");
    expect(bySha(items, "zzz")).toBeNull();
    expect(bySha(items, "")).toBeNull();
  });
});

describe("Code : le contenu d'un fichier n'est jamais du HTML", () => {
  it("les jetons d'une ligne, mis bout à bout, sont la ligne même", () => {
    const lines = ['def connect(host: str, port: int = PORT) -> None:  # <b>ouvre</b>', '    return "<script>alert(1)</script>"', "@dataclass(frozen=True)", "", "x = 1 < 2 and y > 3 & z"];
    for (const line of lines) expect(tokens(line, "a/b.py").map(([, text]) => text).join("")).toBe(line);
    for (const line of lines) expect(tokens(line, "notes.txt").map(([, text]) => text).join("")).toBe(line);
  });

  it("la coloration est simple : mots-clés, chaînes, commentaires, nombres", () => {
    expect(tokens('PORT = 3389  # le port', "rdp.py")).toEqual([["", "PORT = "], ["n", "3389"], ["", "  "], ["c", "# le port"]]);
    expect(tokens("def f():", "rdp.py")[0]).toEqual(["k", "def"]);
    expect(tokens('name = "outils"', "pyproject.toml").map(([cls]) => cls)).toContain("s");
    // un fichier sans grammaire : un seul jeton, sans classe
    expect(tokens("<h1>Titre</h1>", "page.html")).toEqual([["", "<h1>Titre</h1>"]]);
    expect(tokens("", "rdp.py")).toEqual([]);
  });

  it("la vue d'un fichier ne porte aucun caractère de son contenu : il se pose après, par insertion de texte", () => {
    const text = '<img src=x onerror="alert(1)">\n<script>alert(2)</script>\nPORT = 3389\n';
    const blob: Blob = { ref: "main", sha: SHA, path: "outils_reseau/rdp.py", name: "rdp.py", kind: "file", kind_label: "fichier", size: text.length, binary: false, too_big: false, readable: true, why: "",
      text, lines: 3, last_commit: commit(), history: [commit()], history_total: 1, url: "" };
    const tree: Tree = { ref: "main", path: "", parent: null, readme: "", hidden: 1, items: [{ path: "outils_reseau", name: "outils_reseau", kind: "dir", kind_label: "dossier", size: 0 }], last_commit: null };
    const html = filesView(sheet, { ref: "main", path: "outils_reseau/rdp.py", tree: () => got(tree), file: "outils_reseau/rdp.py", home: false, blob: got(blob) }, ui(), ctx());
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("PORT = 3389");
    expect(html).toContain("data-p2-code=");
    expect(html).toContain("1 entrée cachée");
  });

  it("un fichier binaire ou trop gros se dit, avec les mots du serveur, sans emplacement de code", () => {
    const blob: Blob = { ref: "main", sha: SHA, path: "logo.png", name: "logo.png", kind: "file", kind_label: "fichier", size: 18432, binary: true, too_big: false, readable: false,
      why: "Un fichier binaire : son contenu ne s'affiche pas.", text: "", lines: 0, last_commit: null, history: [], history_total: 0, url: "" };
    const tree: Tree = { ref: "main", path: "", parent: null, readme: "", items: [], last_commit: null };
    const html = filesView(sheet, { ref: "main", path: "logo.png", tree: () => got(tree), file: "logo.png", home: false, blob: got(blob) }, ui(), ctx());
    expect(html).toContain("Un fichier binaire : son contenu ne s&#39;affiche pas.");
    expect(html).not.toContain("data-p2-code=");
    expect(sizeWords(18432)).toBe("18 Ko");
    expect(sizeWords(812)).toBe("812 o");
    expect(linesOf("a\nb\n")).toEqual(["a", "b"]);
  });

  it("les lignes d'un diff ne sont pas dans le HTML de la vue ; le titre d'un commit venu d'ailleurs est échappé et marqué", () => {
    const evil = file({ hunks: [hunk([["+", 0, 1, '<script>alert("diff")</script>']])] });
    const c = commit({ title: '<img src=x onerror=alert(3)> correctif', outside: true, author_kind: "other", author: "<b>inconnu</b>" });
    const detail: CommitDetail = { commit: { ...c, body: `${c.title}\n\n<iframe src="//x"></iframe>`, parents: [] }, files: [evil], cut: false, cut_label: "", insertions: 1, deletions: 0, files_readable: true, files_why: "",
      linked: { objective: null, ticket: null, pull: null, checks: null } };
    const html = commitsView(sheet, { page: got({ ref: "", total: 1, page: 1, size: 100, items: [c] }), more: [], wanted: "8f41c2e", commit: got(detail), whole: () => null }, ui(), ctx());
    expect(html).not.toContain("<script");
    expect(html).not.toContain('alert("diff")');
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<iframe");
    expect(html).toContain("&lt;img src=x onerror=alert(3)&gt; correctif");
    expect(html).toContain("&lt;iframe");
    expect(html).toContain("&lt;b&gt;inconnu&lt;/b&gt;");
    expect(html).toContain("venu d&#39;ailleurs");
    expect(html).toContain("p2-out");
  });

  it("sans le droit sur ses fichiers, le diff dit pourquoi avec les mots du serveur", () => {
    const detail: CommitDetail = { commit: { ...commit(), body: "", parents: [] }, files: [], cut: false, cut_label: "", insertions: 0, deletions: 0, files_readable: false, files_why: "Ce projet ne t'ouvre pas ses fichiers.",
      linked: { objective: null, ticket: null, pull: null, checks: null } };
    const html = commitsView(sheet, { page: got({ ref: "", total: 1, page: 1, size: 100, items: [commit()] }), more: [], wanted: "8f41c2e", commit: got(detail), whole: () => null }, ui(), ctx());
    expect(html).toContain("Ce projet ne t&#39;ouvre pas ses fichiers.");
  });
});

describe("Code : un diff mis en lignes", () => {
  const hunks = [hunk([[" ", 1, 1, "a"], ["-", 2, 0, "b"], ["-", 3, 0, "c"], ["+", 0, 2, "B"], [" ", 4, 3, "d"], ["+", 0, 4, "e"]])];

  it("unifié : l'en-tête du passage, puis chaque ligne avec ses deux numéros", () => {
    const rows = unifiedRows(hunks);
    expect(rows[0]).toEqual({ kind: "hunk", header: "@@ -1,3 +1,4 @@" });
    expect(rows).toHaveLength(7);
    expect(rows[2]).toEqual({ kind: "line", line: { kind: "-", old: 2, new: 0, text: "b" } });
  });

  it("côte à côte : une suite de lignes retirées fait face à celles qui la remplacent ; ce qui dépasse n'a rien en face", () => {
    const rows = sideRows(hunks);
    expect(rows.map((r) => (r.kind === "hunk" ? "@@" : `${r.left?.text ?? "∅"}|${r.right?.text ?? "∅"}`))).toEqual(["@@", "a|a", "b|B", "c|∅", "d|d", "∅|e"]);
    // une ligne inchangée est la même des deux côtés, avec ses deux numéros
    const same = rows[1];
    expect(same.kind === "pair" && same.left?.old === 1 && same.right?.new === 1).toBe(true);
  });

  it("un ajout seul, un retrait seul, plusieurs passages", () => {
    expect(sideRows([hunk([["+", 0, 1, "x"], ["+", 0, 2, "y"]])]).filter((r) => r.kind === "pair").every((r) => r.kind === "pair" && r.left === null)).toBe(true);
    expect(sideRows([hunk([["-", 1, 0, "x"]])])[1]).toEqual({ kind: "pair", left: { kind: "-", old: 1, new: 0, text: "x" }, right: null });
    expect(sideRows([...hunks, ...hunks]).filter((r) => r.kind === "hunk")).toHaveLength(2);
    expect(sideRows([])).toEqual([]);
  });

  it("le sommaire range les fichiers par dossier, dans l'ordre où ils viennent", () => {
    const groups = byFolder([file(), file({ path: "README.md" }), file({ path: "outils_reseau/cli.py" })]);
    expect(groups.map((g) => [g.folder, g.files.map((f) => f.index)])).toEqual([["outils_reseau", [0, 2]], ["", [1]]]);
  });
});

function pull(over: Partial<PullLine> = {}): PullLine {
  return { number: 11, title: "Ticket n° 2", state: "ready", state_label: "prête à fusionner", url: "https://github.com/exemple/outils-reseau/pull/11", branch: "ticket-2-export-csv",
    checks: { state: "passed", state_label: "passée", sha: SHA, at: NOW }, review: { ok: true, asked: false, label: "rien à redire", at: NOW, commit: SHA, refused: 0, handed_over: false },
    base: "main", at: NOW - 86_400_000, conflicts: false, changes_asked: false, awaits_accord: 0, unsent: false, objective: { id: 111, text: "Exporter la liste des hôtes en CSV", kind: "once", status: "open", status_label: "en cours" },
    ticket: null, merge: { can: true, why: "", asked: false, asked_at: 0, asked_by: "", refused: "", refused_at: 0 }, ...over };
}

function pullDetail(over: Partial<PullLine> = {}): PullDetail {
  return { pull: { ...pull(over), head: SHA, fork: "7c2f9aa".padEnd(40, "0"), done_when: "La commande `export` écrit un CSV.", result: "", milestones: [], said: null }, commits: [commit(), commit()],
    files: [file(), file({ path: "tests/test_export.py" })], cut: false, cut_label: "", insertions: 42, deletions: 5, files_readable: true, files_why: "" };
}

describe("Code : fusionner une pull request", () => {
  it("la demande nomme le commit de tête que l'écran a montré", () => {
    const facts = mergeFacts(pullDetail());
    expect(facts.head).toBe(SHA);
    expect(mergeRequest(facts)).toEqual({ route: "code/pull/fusionner", body: { number: 11, head: SHA } });
  });

  it("la confirmation dit ce qui va être fusionné", () => {
    const facts = mergeFacts(pullDetail());
    expect(facts).toMatchObject({ title: "Exporter la liste des hôtes en CSV", branch: "ticket-2-export-csv", base: "main", commits: 2, files: 2, insertions: 42, deletions: 5 });
    expect(mergeLines(facts).map((l) => l.text)).toEqual(["2 commits", "2 fichiers, +42 −5", "relecture : rien à redire · vérifications : passée · aucun conflit"]);
    const html = mergeConfirm(facts);
    expect(html).toContain("Exporter la liste des hôtes en CSV");
    expect(html).toContain(SHA.slice(0, 12));
    expect(html).toContain("ticket-2-export-csv");
    // sans le droit sur ses fichiers, la confirmation ne compte pas ce qu'elle ne lit pas
    expect(mergeLines({ ...facts, counted: false }).map((l) => l.icon)).toEqual(["p2-commit", "check"]);
  });

  it("où en est sa fusion : possible, demandée, refusée par l'hôte, retenue, faite", () => {
    expect(mergeStage(pull())).toBe("ready");
    expect(mergeStage(pull({ merge: { can: false, why: "Une fusion est déjà demandée.", asked: true, asked_at: NOW, asked_by: "toi", refused: "", refused_at: 0 } }))).toBe("asked");
    expect(mergeStage(pull({ state: "open", merge: { can: false, why: "Des vérifications sont en cours.", asked: false, asked_at: 0, asked_by: "", refused: "", refused_at: 0 } }))).toBe("held");
    expect(mergeStage(pull({ state: "open", merge: { can: false, why: "", asked: false, asked_at: NOW, asked_by: "toi", refused: "L'hôte a refusé la fusion.", refused_at: NOW } }))).toBe("refused");
    expect(mergeStage(pull({ state: "merged" }))).toBe("merged");
  });

  it("pas de bouton sans le droit servi ; inactif avec la raison du serveur tant qu'elle n'est pas prête ; un refus se dit sur place", () => {
    const c = ctx();
    expect(mergeBlock(3, pull(), true, c)).toContain('data-p2="merge"');
    expect(mergeBlock(3, pull(), false, c)).not.toContain('data-p2="merge"');
    const held = mergeBlock(3, pull({ state: "open", state_label: "ouverte", merge: { can: false, why: "Ses vérifications tournent encore.", asked: false, asked_at: 0, asked_by: "", refused: "", refused_at: 0 } }), true, c);
    expect(held).toContain("disabled");
    expect(held).toContain("Ses vérifications tournent encore.");
    const asked = mergeBlock(3, pull({ merge: { can: false, why: "Une fusion est déjà demandée.", asked: true, asked_at: NOW, asked_by: "toi", refused: "", refused_at: 0 } }), true, c);
    expect(asked).not.toContain('data-p2="merge"');
    expect(asked).toContain("Une fusion est déjà demandée.");
    expect(mergeBlock(3, pull({ state: "merged", state_label: "fusionnée" }), true, c)).toContain("Fusionnée dans main");
    c.ui.refusal = { where: "merge:3:11", text: "Sa branche a bougé depuis ta lecture.", fields: {} };
    expect(mergeBlock(3, pull(), true, c)).toContain("Sa branche a bougé depuis ta lecture.");
    const refused = mergeBlock(3, pull({ merge: { can: true, why: "", asked: false, asked_at: NOW, asked_by: "toi", refused: "On ne sait pas si la fusion a eu lieu.", refused_at: NOW } }), true, ctx());
    expect(refused).toContain("On ne sait pas si la fusion a eu lieu.");
  });

  it("Modifier et répondre ne paraissent qu'avec le droit d'écrire chez l'hôte", () => {
    const data = { pulls: got({ total: 1, page: 1, size: 100, items: [pull()] }), wanted: "11", pull: got(pullDetail()), host: null, whole: () => null };
    const canWrite = pullsView(sheet, data, "echanges", true, ui(), ctx());
    expect(canWrite).toContain("Modifier");
    const reader = { ...sheet, rights: { pull_write: false } } as unknown as Sheet;
    const cannot = pullsView(reader, data, "echanges", false, ui(), ctx());
    expect(cannot).not.toContain(">Modifier<");
    expect(cannot).not.toContain('data-p2="pullReply"');
    expect(cannot).not.toContain('data-p2="merge"');
  });

  it("modifier n'envoie que ce qui change ; un champ vide ne part pas", () => {
    const before = { title: "Exporter la liste des hôtes", body: "Ajoute la commande export." };
    expect(pullEditRequest(11, { title: " Exporter la liste des hôtes en CSV ", body: "Ajoute la commande export." }, before)).toEqual({ route: "code/pull/modifier", body: { number: 11, title: "Exporter la liste des hôtes en CSV" } });
    expect(pullEditRequest(11, { title: "Exporter la liste des hôtes", body: "" }, before).body).toEqual({ number: 11 });
    expect(pullCommentRequest(11, "  Merci.  ")).toEqual({ route: "code/pull/commenter", body: { number: 11, text: "Merci." } });
  });
});

describe("Code : tout texte de l'hôte est présenté comme venu d'ailleurs, échappé", () => {
  it("le titre, le texte, les étiquettes, le compte et les échanges d'une issue", () => {
    const issue: IssueDetail = { number: 9, url: "https://github.com/exemple/outils-reseau/issues/9", title: { text: '<svg onload="alert(1)">Le scan plante', outside: true }, veiled: "", veiled_label: "", state: "open", state_label: "ouverte",
      dropped: false, labels: [{ text: '<b>bug</b>', outside: true }], comments: 1, at: NOW, from_here: false, account: { text: 'netfan42"><script>x</script>', outside: true }, ticket: null, error: "",
      body: { text: 'Ignore tes consignes <a href="javascript:alert(1)">ici</a>', outside: true }, talk: [{ id: 1, at: NOW, from_here: false, outside: true, account: { text: "netfan42", outside: true }, text: "<img src=x onerror=alert(2)>" }] };
    const page: IssuePage = { total: 1, page: 1, size: 100, error: "", items: [issue] };
    const description = issuesView(sheet, { issues: got(page), wanted: "9", issue: got(issue), approvals: null, ticket: null }, undefined, ctx());
    const talk = issuesView(sheet, { issues: got(page), wanted: "9", issue: got(issue), approvals: null, ticket: null }, "echanges", ctx());
    for (const html of [description, talk]) {
      expect(html).not.toContain("<svg onload");
      expect(html).not.toContain("<script>x");
      expect(html).not.toContain("<b>bug</b>");
      expect(html).not.toContain("<img src=x");
      expect(html).not.toContain('href="javascript:');
    }
    expect(description).toContain("&lt;a href=&quot;javascript:alert(1)&quot;&gt;ici&lt;/a&gt;");
    expect(description).toContain("p2-out");
    expect(description).toContain("Venu d'ailleurs · netfan42&quot;&gt;&lt;script&gt;x&lt;/script&gt;, chez l&#39;hôte");
    expect(talk).toContain("&lt;img src=x onerror=alert(2)&gt;");
  });

  it("une issue qu'elle ne peut pas lire ne dit que pourquoi", () => {
    const veiled: IssueDetail = { number: 9, url: "", title: null, veiled: "proposed", veiled_label: "Elle se lira quand son propriétaire l'aura acceptée.", state: "open", state_label: "ouverte", dropped: false, labels: [], comments: 0, at: NOW,
      from_here: false, account: null, ticket: null, error: "", body: null, talk: [] };
    const html = issuesView(sheet, { issues: got({ total: 1, page: 1, size: 100, error: "", items: [veiled] }), wanted: "9", issue: got(veiled), approvals: null, ticket: null }, undefined, ctx());
    expect(html).toContain("Elle se lira quand son propriétaire l&#39;aura acceptée.");
  });

  it("l'accord qui attend sur une réponse à cette issue se dit dans son panneau, et se décide dans « À faire »", () => {
    const issue: IssueDetail = { number: 9, url: "", title: { text: "Le scan plante", outside: true }, veiled: "", veiled_label: "", state: "open", state_label: "ouverte", dropped: false, labels: [], comments: 0, at: NOW,
      from_here: false, account: null, ticket: null, error: "", body: null, talk: [] };
    const accord = (id: number, n: number): Approval => ({ id, project: 3, project_title: "Outils réseau", capability: "issue_comment", label: "Répondre sur une issue", summary: '<b>à netfan42</b>', text: "…", digest: "d", blocked: "", at: NOW,
      concerns: { objective: 0, ticket: null, issue: n, pull: 0 } });
    const page = got({ total: 1, page: 1, size: 100, error: "", items: [issue] });
    const html = issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: got({ items: [accord(41, 9), accord(42, 12)] }), ticket: null }, undefined, ctx());
    expect(html).toContain("Ton accord");
    expect(html).toContain('href="#projets/a-faire/3/accord-41"');
    expect(html).not.toContain("accord-42");
    expect(html).toContain("&lt;b&gt;à netfan42&lt;/b&gt;");
    // rien pour qui ne peut pas le donner, ni quand rien n'attend sur cette issue
    expect(issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: null, ticket: null }, undefined, ctx())).not.toContain("Ton accord");
    expect(issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: got({ items: [accord(42, 12)] }), ticket: null }, undefined, ctx())).not.toContain("Ton accord");
  });
});

describe("Code › Issues : le ticket proposé se tranche ici quand son registre le dit", () => {
  const issue = { number: 9, url: "", title: { text: "Le scan plante", outside: true }, veiled: "", veiled_label: "", state: "open", state_label: "ouverte", dropped: false, labels: [], comments: 0, at: NOW, from_here: false, account: null, error: "", body: null, talk: [],
    ticket: { number: 6, handle: "#6", title: "Le scan s'arrête", veiled: "", veiled_label: "", status: "proposed", status_label: "proposé", open: true, hand: "owner", hand_label: "au propriétaire", yours: true } } as unknown as IssueDetail;
  const page = got({ total: 1, page: 1, size: 100, error: "", items: [issue] });
  const entry = (can: Partial<EntryDetail["can"]>, linked?: EntryDetail["linked"]) => got({ number: 6, handle: "#6", plan: 0, linked,
    can: { note: true, status: false, accept: false, dismiss: false, dismiss_needs_reason: false, validate: false, refuse: false, ...can } } as unknown as EntryDetail);

  it("accepter et écarter suivent `can` du ticket ; sans lui, le lien vers son ticket", () => {
    const open = issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: null, ticket: entry({ accept: true, dismiss: true }) }, undefined, ctx());
    expect(open).toContain('data-p2="settle" data-v="accept" data-p="3" data-c="6"');
    expect(open).toContain('data-p2="settle" data-v="dismiss" data-p="3" data-c="6" data-ask="Pourquoi (facultatif)"');
    for (const closed of [entry({}), null]) {
      const html = issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: null, ticket: closed }, undefined, ctx());
      expect(html).not.toContain('data-p2="settle"');
      expect(html).toContain("Le trancher dans son ticket");
    }
  });

  it("la pull request de son ticket, avec son titre et son statut", () => {
    const pull = { number: 12, title: "Scan : accepter <IPv6>", url: "", state: "open", state_label: "ouverte", words: "", changes_asked: false, conflicts: false, at: NOW, awaits_accord: 0, said: null };
    const html = issuesView(sheet, { issues: page, wanted: "9", issue: got(issue), approvals: null, ticket: entry({}, { objective: null, pull, checks: { state: "passed", state_label: "passée", sha: "", at: NOW, said: null } }) }, undefined, ctx());
    expect(html).toContain("La pull request liée");
    expect(html).toContain("Scan : accepter &lt;IPv6&gt;");
    expect(html).toContain('href="#projets/projets/3/code/pulls/12"');
  });
});

describe("Code › Fichiers : un fichier Markdown se lit rendu, par le rendu sûr des pages", () => {
  it("un fichier Markdown, et où mène un lien relatif du dépôt", () => {
    expect(isMarkdown("README.md")).toBe(true);
    expect(isMarkdown("docs/Guide.MARKDOWN")).toBe(true);
    expect(isMarkdown("outils_reseau/cli.py")).toBe(false);
    expect(repoLink("README.md", "docs/guide.md")).toBe("docs/guide.md");
    expect(repoLink("docs/guide.md", "./images/a.png#haut")).toBe("docs/images/a.png");
    expect(repoLink("docs/guide.md", "../LICENSE")).toBe("LICENSE");
    expect(repoLink("docs/guide.md", "/outils_reseau/cli.py")).toBe("outils_reseau/cli.py");
    for (const out of ["../../etc/passwd", "javascript:alert(1)", "data:text/html,x", "//ailleurs.example/x", "#ancre", "mailto:a@b.c", ""]) expect(repoLink("docs/guide.md", out)).toBeNull();
  });

  it("rien ne s'exécute, aucune image n'est chargée, un lien ne mène qu'au dépôt ou à une adresse http(s)", () => {
    const html = renderedFile(3, "main", "docs/guide.md", '# Guide <script>alert(1)</script>\n\n<img src=x onerror="alert(2)">\n\n![logo](images/logo.png) ![pixel](https://ailleurs.example/p.gif)\n\n[Le code](../outils_reseau/cli.py) [Le site](https://exemple.org) [x](javascript:alert(3)) [y](../../../etc/passwd)\n');
    expect(html).toContain('class="p2-md p2-readme"');
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toMatch(/href="javascript:/);
    expect(html).toContain('<a href="#projets/projets/3/code/fichiers/main/outils_reseau/cli.py">Le code</a>');
    expect(html).toContain('<a href="https://exemple.org" target="_blank" rel="noopener noreferrer">Le site</a>');
    expect(html).toContain("non chargée");
    expect(html).not.toMatch(/href="[^"]*passwd/);
  });
});
