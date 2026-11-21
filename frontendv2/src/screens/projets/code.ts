/**
 * L'onglet Code d'une fiche (ADR 0291, d'après `maquette/ecrans/projets2-code.js`) : ses six sous-onglets — Fichiers,
 * Commits, Pull requests, Branches, Issues, CI —, branchés sur le socle par `registerTab("code", …)` (`tabs.ts`). Ce
 * module tient ses lectures gardées (`protocole-moi.md` § 11, « Le code d'un projet »), ce qui est choisi (la forme
 * du diff, la branche filtrée, les dossiers ouverts) et ses gestes : **fusionner** une pull request — une
 * confirmation qui dit ce qui va être fusionné, puis la demande qui nomme le commit de tête qu'on vient de relire —,
 * la modifier, y répondre. Les vues sont dans `views/code.ts` et `views/codehost.ts`, le calcul pur dans
 * `codeparts.ts`, le contenu des fichiers et des diffs dans `paint.ts` (par insertion de texte).
 */
import {
  fetchBlob, fetchBranch, fetchBranches, fetchChecks, fetchCode, fetchCommit, fetchCommitChecks, fetchCommits, fetchIssue, fetchIssues, fetchPull, fetchPullHost, fetchPulls, fetchTree,
  type Blob, type BranchDetail, type BranchList, type CodeSummary, type Commit, type CommitChecks, type CommitDetail, type CommitPage, type Diff, type DiffFile, type IssueDetail, type IssuePage,
  type PullDetail, type PullHost, type PullPage, type TrackedChecks, type Tree,
} from "../../api/projectCode";
import { fetchApprovals, type Approval, type Sheet } from "../../api/projects";
import { CachedMap, copyText, failureText, sessionGone } from "../../shared/kit";
import { h } from "../../shell/dom";
import { openMenu, toast, type MenuItem } from "../../shell/float";
import { ico } from "../../shell/icons";
import { bySha, CODE_TABS, codePlace, fileRoute, mergeFacts, mergeRequest, parsePullKey, pullCommentRequest, pullEditRequest, pullKey, pullRoute, splitRef, type CodeTab } from "./codeparts";
import { confirmHtml } from "./dialogs";
import { safeLink } from "./gestures";
import { keepLateScroll, paintAll } from "./paint";
import { empty, subbar } from "./parts";
import { sheetRoute } from "./routes";
import { registerTab, type Act, type FormAct, type TabHost } from "./tabs";
import { when } from "./time";
import { branchesView, commitsView, filesView, type CodeUi, type FilesData } from "./views/code";
import { checksView, issuesView, mergeConfirm, pullsView } from "./views/codehost";
import { waitingBlock, type Got } from "./views/todo";

/** La clé d'une lecture gardée : ses morceaux, séparés par ce qu'aucun chemin ne porte. */
const k = (...parts: Array<string | number>): string => parts.join("\n");
const unk = (key: string): string[] => key.split("\n");

/** Ce que l'hôte est seul à savoir se relit moins souvent : chaque lecture le joint (60 par minute et par compte). */
const HOST_TTL = 60_000;

const summaries = new CachedMap<CodeSummary>((id) => fetchCode(Number(id)));
const branchLists = new CachedMap<BranchList>((id) => fetchBranches(Number(id)));
const trees = new CachedMap<Tree>((key) => {
  const [id, ref, dir] = unk(key);
  return fetchTree(Number(id), ref, dir);
}, 60_000);
const blobs = new CachedMap<Blob>((key) => {
  const [id, ref, path] = unk(key);
  return fetchBlob(Number(id), ref, path);
}, 60_000);
const commitPages = new CachedMap<CommitPage>((key) => {
  const [id, ref] = unk(key);
  return fetchCommits(Number(id), ref);
});
const commits = new CachedMap<CommitDetail>((key) => {
  const [id, sha] = unk(key);
  return fetchCommit(Number(id), sha);
}, 60_000);
/** Un fichier d'un diff coupé, relu seul (`path=`). */
const wholeFiles = new CachedMap<Diff>((key) => {
  const [id, kind, name, path] = unk(key);
  if (kind === "commit") return fetchCommit(Number(id), name, path);
  const { number, objective } = parsePullKey(name);
  return fetchPull(Number(id), number, objective, path);
}, 300_000);
const branches = new CachedMap<BranchDetail>((key) => {
  const [id, name] = unk(key);
  return fetchBranch(Number(id), name);
});
const pullPages = new CachedMap<PullPage>((id) => fetchPulls(Number(id)));
const pulls = new CachedMap<PullDetail>((key) => {
  const [id, name] = unk(key);
  const { number, objective } = parsePullKey(name);
  return fetchPull(Number(id), number, objective);
});
const pullHosts = new CachedMap<PullHost>((key) => {
  const [id, number] = unk(key);
  return fetchPullHost(Number(id), Number(number));
}, HOST_TTL);
const issuePages = new CachedMap<IssuePage>((id) => fetchIssues(Number(id)), HOST_TTL);
/** Ce qui attend son accord dans le projet : une réponse à une issue s'y reconnaît (`concerns.issue`). */
const accords = new CachedMap<{ items: Approval[] }>((id) => fetchApprovals(Number(id)));
const issues = new CachedMap<IssueDetail>((key) => {
  const [id, number] = unk(key);
  return fetchIssue(Number(id), Number(number));
}, HOST_TTL);
const checkLists = new CachedMap<{ items: TrackedChecks[] }>((id) => fetchChecks(Number(id)));
const commitChecks = new CachedMap<CommitChecks>((key) => {
  const [id, sha] = unk(key);
  return fetchCommitChecks(Number(id), sha);
}, HOST_TTL);

/** Les commits des pages suivantes, par projet et par branche filtrée. */
const moreCommits = new Map<string, Commit[]>();

const ui: CodeUi = { side: false, commitsRef: "", open: new Set(), whole: new Set(), mdSource: false };
/** La dernière adresse de fichier dont les dossiers ont été ouverts d'office (on peut ensuite les replier). */
let lastOpened = "";
let merging = false;

/** Après un geste (ou un refus qui dit que ce qu'on lisait a changé) : tout ce qui est lu d'une pull request repart du serveur. */
export function invalidateCode(): void {
  for (const map of [summaries, branchLists, commitPages, branches, pullPages, pulls, pullHosts, issuePages, issues, checkLists, commitChecks]) map.invalidate();
  moreCommits.clear();
}

/** Un refus dit à l'endroit du geste, avec les mots du serveur. */
function refuse(host: TabHost, where: string, err: unknown): void {
  if (sessionGone(err)) {
    location.reload();
    return;
  }
  host.ui.refusal = { where, text: failureText(err), fields: {} };
  host.repaint();
}

// ── Les lectures de chaque sous-onglet ───────────────────────────────

function filesData(id: number, s: CodeSummary, rest: string[], refs: readonly string[], host: TabHost): FilesData {
  const { ref, path } = splitRef(rest, refs, s.base);
  const tree = (dir: string): Got<Tree> => host.read(trees.get(k(id, ref, dir)));
  const parts = path ? path.split("/") : [];
  const address = `${id}|${ref}|${path}`;
  if (address !== lastOpened) {
    // les dossiers qui mènent au fichier de l'adresse s'ouvrent ; on peut ensuite les replier
    for (let i = 1; i < parts.length; i += 1) ui.open.add(`${ref}|${parts.slice(0, i).join("/")}`);
    lastOpened = address;
  }
  if (!path) {
    const readme = tree("").value?.readme ?? "";
    return { ref, path, tree, file: readme, home: true, blob: readme ? host.read(blobs.get(k(id, ref, readme))) : null };
  }
  const parent = tree(parts.slice(0, -1).join("/"));
  if (!parent.value) return { ref, path, tree, file: path, home: false, blob: { value: null, error: parent.error } };
  const entry = parent.value.items.find((e) => e.path === path);
  if (entry?.kind === "dir") {
    // l'adresse nomme un dossier : il s'ouvre, et son README se montre
    ui.open.add(`${ref}|${path}`);
    const own = tree(path);
    const readme = own.value?.readme ?? "";
    return { ref, path, tree, file: readme, home: true, blob: readme ? host.read(blobs.get(k(id, ref, readme))) : null };
  }
  return { ref, path, tree, file: path, home: false, blob: host.read(blobs.get(k(id, ref, path))) };
}

function whole(id: number, kind: "commit" | "pull", name: string, host: TabHost): (path: string) => DiffFile | null {
  return (path) => host.read(wholeFiles.get(k(id, kind, name, path))).value?.files[0] ?? null;
}

function render(sheet: Sheet, rest: string[], host: TabHost): string {
  const id = sheet.project.id;
  const ctx = host.ctx();
  const summary = host.read(summaries.get(String(id)));
  const s = summary.value;
  if (!s) return waitingBlock(summary, "Impossible de lire le code de ce projet");
  if (!s.has_repo) return empty("code", "Pas de dépôt", "Ce projet n'a pas encore de dépôt : ni fichiers, ni commits, ni pull requests.");
  const place = codePlace(rest);
  const counts: Record<CodeTab, number | null> = { fichiers: null, commits: s.counts.commits, pulls: s.counts.pulls_open, branches: s.counts.branches, issues: s.counts.issues_open, ci: s.counts.checks_failed || null };
  const web = safeLink(s.remote.web);
  const remote = !s.remote.has ? `<span class="p2-sync">${ico("info", "xs")}sans dépôt distant</span>`
    : `${web ? `<a class="p2-remote" href="${h(web)}" target="_blank" rel="noopener noreferrer" title="Ouvrir le dépôt chez l'hôte">${ico("globe", "sm")}<span>${h(web.replace(/^https?:\/\//, ""))}</span></a>` : `<span class="p2-remote plain">${ico("globe", "sm")}<span>dépôt distant</span></span>`}
      ${s.remote.synced_at ? `<span class="p2-sync">${ico(sheet.repo?.remote_ok === false ? "alert" : "check", "xs")}relu ${h(when(s.remote.synced_at, ctx.now))}</span>` : ""}`;
  const bar = subbar(CODE_TABS.map(([t, label]): [string, string, number | null] => [sheetRoute(id, "code", t), label, counts[t]]), CODE_TABS.findIndex(([t]) => t === place.tab), remote);
  let inner: string;
  if (place.tab === "fichiers") {
    const lists = host.read(branchLists.get(String(id)));
    inner = lists.value ? filesView(sheet, filesData(id, s, place.rest, lists.value.items.map((b) => b.name), host), ui, ctx) : waitingBlock(lists, "Impossible de lire ses branches");
  } else if (place.tab === "commits") {
    const key = k(id, ui.commitsRef);
    const page = host.read(commitPages.get(key));
    const more = moreCommits.get(key) ?? [];
    const all = [...(page.value?.items ?? []), ...more];
    const wanted = place.rest[0] ?? "";
    const sha = wanted ? (bySha(all, wanted)?.sha ?? wanted) : ctx.mobile ? "" : (all[0]?.sha ?? "");
    inner = commitsView(sheet, { page, more, wanted, commit: sha ? host.read(commits.get(k(id, sha))) : null, whole: whole(id, "commit", sha, host) }, ui, ctx);
  } else if (place.tab === "pulls") {
    const list = host.read(pullPages.get(String(id)));
    const wanted = place.rest[0] ?? "";
    const chosen = wanted || (ctx.mobile || !list.value?.items[0] ? "" : pullKey(list.value.items[0]));
    const { number, objective } = parsePullKey(chosen);
    const known = !!(number || objective);
    inner = pullsView(sheet, {
      pulls: list, wanted: chosen, pull: known ? host.read(pulls.get(k(id, chosen))) : null,
      host: known && number && s.remote.has ? host.read(pullHosts.get(k(id, number))) : null, whole: whole(id, "pull", chosen, host),
    }, place.rest[1], s.rights.merge, ui, ctx);
  } else if (place.tab === "branches") {
    const lists = host.read(branchLists.get(String(id)));
    const wanted = place.rest.join("/");
    const items = lists.value?.items ?? [];
    const picked = items.find((b) => b.name === wanted) ?? (ctx.mobile ? null : (items.find((b) => !b.base) ?? items[0] ?? null));
    inner = branchesView(sheet, { summary: s, branches: lists, wanted, branch: picked ? host.read(branches.get(k(id, picked.name))) : null }, ctx);
  } else if (place.tab === "issues") {
    const list = host.read(issuePages.get(String(id)));
    const wanted = /^\d+$/.test(place.rest[0] ?? "") ? place.rest[0] : ctx.mobile || !list.value?.items[0] ? "" : String(list.value.items[0].number);
    // ce qui attend son accord ne se demande que pour qui peut le donner (`rights.approve`)
    const issue = wanted ? host.read(issues.get(k(id, wanted))) : null;
    // le ticket qui la reflète se lit dans le registre : ce qu'elle peut en faire (`can`) et ce qui lui est lié
    const mirrored = issue?.value && !issue.value.veiled ? issue.value.ticket : null;
    inner = issuesView(sheet, { issues: list, wanted, issue, approvals: wanted && sheet.rights.approve ? host.read(accords.get(String(id))) : null,
      ticket: mirrored ? host.readElement(id, "tickets", `#${mirrored.number}`) : null }, place.rest[1], ctx);
  } else {
    const list = host.read(checkLists.get(String(id)));
    const items = list.value?.items ?? [];
    const wanted = (place.rest[0] ?? "").toLowerCase();
    const tracked = wanted ? (bySha(items, wanted) ?? null) : ctx.mobile ? null : (items[0] ?? null);
    const sha = tracked?.sha ?? wanted;
    // ce que l'hôte en dit maintenant ne se demande que s'il y a un dépôt distant à relire
    const live: Got<CommitChecks> | null = !sha ? null : s.remote.has ? host.read(commitChecks.get(k(id, sha))) : { value: null, error: null };
    inner = checksView(sheet, { checks: list, wanted: sha, tracked, commit: live, remote: s.remote.has }, place.rest[1], ctx);
  }
  return `${bar}<div class="p2-under">${inner}</div>`;
}

// ── Les gestes ───────────────────────────────────────────────────────

/** La branche qu'on choisit : pour les fichiers (une adresse), pour les commits (un filtre). */
const pickBranch: Act = async (d, el, host) => {
  const id = Number(d.p);
  const cached = branchLists.get(String(id));
  const list = cached.value ?? (await cached.load());
  if (!list) return;
  const forCommits = d.c === "commits";
  const pick = (name: string): void => {
    if (forCommits) {
      ui.commitsRef = name;
      host.repaint();
    } else host.go(fileRoute(id, name));
  };
  const items: MenuItem[] = [
    ...(forCommits ? [{ label: "Toutes les branches", icon: "p2-commit" as const, checked: !ui.commitsRef, action: () => pick("") }, "sep" as const] : []),
    ...list.items.map((b) => ({ label: b.name, icon: "p2-branch" as const, checked: (forCommits ? ui.commitsRef : d.r) === b.name, action: () => pick(b.name) })),
  ];
  openMenu(el, items, { align: "left" });
};

/**
 * Fusionner : la pull request se relit à l'instant, la confirmation dit ce qui va être fusionné, puis la demande
 * nomme le commit de tête qu'elle a montré. Refusée (la branche a bougé, l'hôte ne veut pas), les mots du serveur se
 * disent là où était le bouton — sous la pull request, ou dans « À faire ».
 */
const merge: Act = async (d, _el, host) => {
  const project = Number(d.p);
  const name = d.c ?? "";
  const where = d.w || `merge:${project}:${name}`;
  if (merging) return;
  merging = true;
  try {
    const { number, objective } = parsePullKey(name);
    let detail: PullDetail;
    try {
      detail = await fetchPull(project, number, objective);
    } catch (err) {
      refuse(host, where, err);
      return;
    }
    const facts = mergeFacts(detail);
    const yes = await confirmHtml({ title: `Fusionner la pull request n° ${facts.number} ?`, bodyHtml: mergeConfirm(facts), ok: `Fusionner dans ${facts.base}`, icon: "p2-merge" });
    if (!yes) return;
    const sent = await host.send(project, mergeRequest(facts), where, () => invalidateCode());
    if (!sent) {
      invalidateCode();
      host.repaint();
    }
  } finally {
    merging = false;
  }
};

const acts: Record<string, Act> = {
  copy: async (d) => {
    const text = d.c ?? "";
    toast((await copyText(text)) ? `Copié : ${text.length > 60 ? `${text.slice(0, 60)}…` : text}` : "La copie n'a pas abouti.", { ico: "copy" });
  },
  codeFold: (d, _el, host) => {
    const key = `${d.r}|${d.c}`;
    if (ui.open.has(key)) ui.open.delete(key);
    else ui.open.add(key);
    host.repaint();
  },
  codeBranch: pickBranch,
  codeDiffMode: (d, _el, host) => {
    ui.side = d.c === "side";
    host.repaint();
  },
  codeMdMode: (d, _el, host) => {
    ui.mdSource = d.c === "source";
    host.repaint();
  },
  codeJump: (d, _el, host) => {
    if (host.ui.infos) {
      host.ui.infos = false;
      host.repaint();
    }
    document.getElementById(d.c ?? "")?.scrollIntoView({ block: "start", behavior: "smooth" });
  },
  codeWhole: (d, _el, host) => {
    ui.whole.add(`${d.k}|${d.c}`);
    host.repaint();
  },
  codeCommitsMore: async (d, _el, host) => {
    const id = Number(d.p);
    const key = k(id, ui.commitsRef);
    const page = commitPages.get(key).value;
    if (!page) return;
    const known = moreCommits.get(key) ?? [];
    try {
      const next = await fetchCommits(id, ui.commitsRef, Math.floor((page.items.length + known.length) / page.size) + 1, page.size);
      const seen = new Set([...page.items, ...known].map((c) => c.sha));
      moreCommits.set(key, [...known, ...next.items.filter((c) => !seen.has(c.sha))]);
      if (!next.items.length) toast("Il n'y a rien de plus.", { ico: "info" });
      host.repaint();
    } catch (err) {
      refuse(host, "top", err);
    }
  },
  codeBranchCommits: (d, _el, host) => {
    ui.commitsRef = d.c ?? "";
    host.go(sheetRoute(Number(d.p), "code", "commits"));
  },
  codeRow: (d, _el, host) => host.go(d.c ?? ""),
  merge,
  pullReply: async (d, el, host) => {
    const field = el.closest(".p2-note")?.querySelector<HTMLTextAreaElement>("[data-p2-champ]");
    const text = field?.value.trim() ?? "";
    if (!text) {
      field?.classList.add("p2-manque");
      field?.focus();
      return;
    }
    const sent = await host.send(Number(d.p), pullCommentRequest(Number(d.c), text), d.w ?? "top", () => invalidateCode());
    if (!sent) invalidateCode();
  },
};

const forms: Record<string, FormAct> = {
  /** Modifier une pull request : son titre et son texte chez l'hôte, seulement ce qui change de ce qu'on a relu. */
  pull: async (values, d, _form, host) => {
    const project = Number(d.p);
    const number = Number(d.c);
    const name = String(number);
    const seen = pullHosts.get(k(project, number)).value;
    const detail = pulls.get(k(project, name)).value;
    const before = { title: seen?.title?.text || detail?.pull.title || "", body: seen?.body?.text ?? "" };
    const sent = await host.send(project, pullEditRequest(number, values, before), `pull:${project}:${name}`, () => {
      invalidateCode();
      host.go(pullRoute(project, { number }));
    });
    if (!sent) invalidateCode();
  },
};

registerTab("code", {
  // un accord décidé, un ticket tranché : ce que les issues en disent se relit
  invalidate: () => {
    for (const map of [accords, issuePages, issues]) map.invalidate();
  },
  render,
  after: (body) => {
    paintAll(body);
    keepLateScroll(body, "[data-p2-code]");
  },
  acts,
  forms,
});
