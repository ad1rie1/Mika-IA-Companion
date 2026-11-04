/**
 * Outils : la matrice de tes droits telle que le moteur la calcule (`GET /api/moi/rights`), mise en tableaux comme
 * dans la maquette (`maquette/ecrans/outils.js`) — une ressource par tableau, ses outils en lignes, chaque canal et
 * chaque moment en colonnes. Rien n'y est recalculé : une case dit la décision du moteur, et pourquoi. Pur, sans DOM.
 */
import type { Canal, Cell, Keep, Level, Moment, Resource, Rights, Rules, ToolRow } from "../../api/rights";
import { h, norm } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";

// ── Les mots ─────────────────────────────────────────────────────────

/** Une case : sa couleur, son mot, et ce qu'elle veut dire en entier. */
export const LEVELS: Record<Level, { cls: string; word: string; long: string }> = {
  seule: { cls: "ok", word: "Seule", long: "Elle s'en sert seule, sans te demander." },
  carte: { cls: "warn", word: "Demande", long: "Elle te demande d'abord : une carte dans ton chat." },
  toi: { cls: "warn", word: "Ton accord", long: "Elle attend ton accord avant de s'en servir." },
  non: { cls: "off", word: "Non", long: "Elle ne s'en sert pas." },
};

export function levelOf(cell: Cell | null | undefined): { cls: string; word: string; long: string } {
  if (!cell) return { cls: "off", word: "—", long: "Il ne sert pas à ce moment-là." };
  return LEVELS[cell.level] ?? { cls: "off", word: cell.level, long: cell.level };
}

export const KEEP_WORDS: Record<Keep, string> = { public: "un savoir", perso: "un souvenir", prive: "une confidence", rien: "rien" };

/** Les moments, en court, sous chaque canal. */
const MOMENT_SHORT: Record<string, string> = { reply: "répond", initiative: "d'elle-même", work: "au travail" };
/** Un mot de plus sous certains canaux, comme dans la maquette. */
const CANAL_SUB: Record<string, string> = { web: "en privé", salon: "à plusieurs", seule: "au travail" };
/** Le moment d'« elle seule » : quand elle travaille. */
const WORK = "work";
const ALONE_CANAL = "seule";

/** Les cases qui comptent dans le menu : quand elle te répond, sur le web et l'app Android. */
const COUNTED = ["web/reply", "mobile/reply"];

// ── Les colonnes ─────────────────────────────────────────────────────

export interface CanalColumns {
  canal: Canal;
  moments: Moment[];
}

/** Chaque canal et ses moments : `reply` et `initiative` pour un canal qui parle, `work` pour elle seule. */
export function columns(canals: readonly Canal[], moments: readonly Moment[]): CanalColumns[] {
  const talking = moments.filter((m) => m.key !== WORK);
  const working = moments.filter((m) => m.key === WORK);
  return canals
    .map((canal) => ({ canal, moments: canal.key === ALONE_CANAL ? working : talking }))
    .filter((c) => c.moments.length > 0);
}

export function cellKey(canal: string, moment: string): string {
  return `${canal}/${moment}`;
}

// ── Les ressources ───────────────────────────────────────────────────

/** Ce qu'on sait d'une ressource à côté de la matrice : à qui elle est (une boîte, un compte, un service). */
export interface Ownership {
  /** `mail:<clé>`, `teams:<clé>`, `mcp:<nom>` → « à toi », « partagée avec toi par Léa (lire) »… */
  words: Map<string, string>;
}

export interface MatrixResource {
  key: string;
  group: string;
  groupTitle: string;
  title: string;
  /** Le nom dans le menu (sans « Courrier · »). */
  navTitle: string;
  sub: string;
  icon: IconName;
  /** Ce qu'elle seule utilise : aucune case ne s'ouvre ailleurs que quand elle travaille. */
  internal: boolean;
  tools: ToolRow[];
  rules?: Rules;
  kind?: "mail" | "teams";
}

const FAMILY_ICONS: Record<string, IconName> = {
  goals: "clock", camera: "eye", forge_signals: "bell", email: "mail", imaging: "image", shares: "file", rss: "inbox",
  identity: "user", workshop: "terminal", forge: "code", location: "pin", phone: "phone", memory: "book",
  attachments: "clip", projects: "folder", social: "users", wakeup: "bolt", attention: "sparkle", self: "heart",
  world: "map", teams: "teams",
};

function familyIcon(key: string): IconName {
  return FAMILY_ICONS[key.replace(/^famille:/, "")] ?? "tools";
}

/** Rien ne s'ouvre pour toi : seulement quand elle travaille, pour elle. */
export function internalOnly(tools: readonly ToolRow[]): boolean {
  if (!tools.length) return false;
  return tools.every((t) =>
    Object.entries(t.cells).every(([k, c]) => !c || c.level === "non" || k.startsWith(`${ALONE_CANAL}/`)),
  );
}

/** Ses ressources dans l'ordre de la matrice ; un compte reprend les outils de sa famille (ses cases sont là). */
export function resourcesOf(rights: Rights, owned: Ownership = { words: new Map() }): MatrixResource[] {
  const families = new Map<string, Resource>();
  for (const g of rights.groups) if (g.key === "families") for (const r of g.resources) families.set(r.key, r);
  const out: MatrixResource[] = [];
  for (const g of rights.groups) {
    for (const r of g.resources) {
      if (g.key === "accounts") {
        const tools = (r.family ? families.get(r.family)?.tools : undefined) ?? [];
        const kind = r.kind === "teams" ? "teams" : "mail";
        const bare = r.key.replace(/^(courrier|teams):/, "");
        const whose = owned.words.get(`${kind}:${bare}`);
        out.push({
          key: r.key, group: g.key, groupTitle: g.title,
          title: `${kind === "teams" ? "Teams" : "Courrier"} · ${r.title}`, navTitle: r.title,
          sub: [r.address, whose].filter(Boolean).join(" · "),
          icon: kind === "teams" ? "teams" : "mail", internal: false, tools, rules: r.rules, kind,
        });
        continue;
      }
      const tools = r.tools ?? [];
      if (g.key === "services" || g.key === "apps") {
        const name = r.key.replace(/^[a-z]+:/, "");
        const whose = owned.words.get(`mcp:${name}`) ?? (g.key === "apps" ? "une app de la Forge" : "un service de Mika");
        out.push({
          key: r.key, group: g.key, groupTitle: g.title, title: r.title, navTitle: r.title, sub: whose,
          icon: g.key === "apps" ? "code" : name === "web" ? "globe" : "server", internal: false, tools,
        });
        continue;
      }
      const internal = internalOnly(tools);
      out.push({
        key: r.key, group: g.key, groupTitle: g.title, title: r.title, navTitle: r.title,
        sub: internal ? `${r.description || ""}${r.description ? " · " : ""}ce qu'elle seule utilise` : r.description || "",
        icon: familyIcon(r.key), internal, tools,
      });
    }
  }
  return out;
}

/** Ce qu'elle fait seule, et ce qu'elle te demande, quand elle te répond sur le web et l'app Android. */
export function countsOf(tools: readonly ToolRow[]): { alone: number; ask: number } {
  let alone = 0;
  let ask = 0;
  for (const t of tools) {
    for (const k of COUNTED) {
      const level = t.cells[k]?.level;
      if (level === "seule") alone += 1;
      else if (level === "carte" || level === "toi") ask += 1;
    }
  }
  return { alone, ask };
}

// ── Un outil ─────────────────────────────────────────────────────────

/**
 * Le nom d'un outil pour une personne : la première proposition de sa description (écrite pour elle), sinon son nom.
 * « Lister les mails d'une boîte ou d'un dossier, du plus récent… » → « Lister les mails d'une boîte ou d'un dossier ».
 */
export function toolLabel(description: string, name: string): string {
  const flat = description.replace(/\s+/g, " ").trim();
  if (!flat) return name;
  const first = flat.match(/^(.{6,}?)(?:\s*[:;(]|\.\s|\.$|\s—\s)/u);
  let label = (first ? first[1] : flat).trim();
  if (label.length > 56) {
    const comma = label.slice(20).search(/,\s/u);
    if (comma >= 0) label = label.slice(0, 20 + comma);
  }
  if (label.length > 72) label = `${label.slice(0, 71).trimEnd()}…`;
  return label.charAt(0).toUpperCase() + label.slice(1);
}

/** La condition qui le garde (ce que dit une case fermée par elle), s'il en a une. */
export function conditionOf(tool: ToolRow): string {
  for (const c of Object.values(tool.cells)) if (c && c.reason === "when" && c.why) return c.why;
  return "";
}

/** Ce qu'elle garde de ce qu'il rend, là où elle s'en sert (sans « rien »). */
export function keepsOf(tool: ToolRow): string[] {
  const out = new Set<string>();
  for (const c of Object.values(tool.cells)) {
    if (c && c.level !== "non" && c.keep !== "rien") out.add(KEEP_WORDS[c.keep] ?? c.keep);
  }
  return [...out];
}

/** Pourquoi une case : ses lignes, ce qui la ferme, ce qu'elle en garde. */
export function whyOf(cell: Cell): { why: string; keep: string } {
  let why = cell.why.trim();
  if (cell.owned) why = "une ressource à ton nom";
  else if (cell.reason === "when" && why) why = `sa condition : ${why}`;
  const keep = cell.level !== "non" && cell.keep !== "rien" ? KEEP_WORDS[cell.keep] ?? cell.keep : "";
  return { why, keep };
}

export function toolMatches(res: MatrixResource, tool: ToolRow, q: string): boolean {
  const needle = norm(q.trim());
  if (!needle) return true;
  return norm(`${toolLabel(tool.description, tool.name)} ${tool.name} ${res.title}`).includes(needle);
}

// ── Le balisage ──────────────────────────────────────────────────────

export function legendMarkup(): string {
  const lv = (l: Level) => `<span class="lv ${LEVELS[l].cls}">${h(LEVELS[l].word)}</span>`;
  return `<div class="mx-legend">${lv("seule")}${lv("carte")}${lv("toi")}${lv("non")}<span><span class="lv off">—</span> il ne sert pas à ce moment</span>
    <span>${ico("lock", "xs")} sous une condition</span><span>${ico("book", "xs")} ce qu'elle en garde</span></div>`;
}

function headMarkup(cols: readonly CanalColumns[]): string {
  const talking = cols.filter((c) => c.canal.key !== ALONE_CANAL);
  const alone = cols.find((c) => c.canal.key === ALONE_CANAL);
  const sub = (key: string) => (CANAL_SUB[key] ? `<small>${h(CANAL_SUB[key])}</small>` : "");
  const first = talking
    .map((c) => `<th colspan="${c.moments.length}" class="mx-canal">${h(c.canal.label)}${sub(c.canal.key)}</th>`)
    .join("");
  const second = talking
    .map((c) => c.moments.map((m) => `<th class="mx-q" title="${h(m.label)}">${h(MOMENT_SHORT[m.key] ?? m.label)}</th>`).join(""))
    .join("");
  const last = alone ? `<th rowspan="2" class="mx-canal seule" title="${h(alone.moments.map((m) => m.label).join(", "))}">${h(alone.canal.label)}${sub(alone.canal.key)}</th>` : "";
  return `<thead><tr><th rowspan="2" class="mx-tool-h">Outil</th>${first}${last}</tr><tr>${second}</tr></thead>`;
}

function cellMarkup(tool: ToolRow, canal: string, moment: string): string {
  const key = cellKey(canal, moment);
  const cell = tool.cells[key];
  const l = levelOf(cell);
  if (!cell) return `<td class="mx-c"><span class="lv off" title="${h(l.long)}">—</span></td>`;
  return `<td class="mx-c"><button type="button" class="lv ${l.cls}" data-cell="${h(key)}" title="${h(l.long)}">${h(l.word)}</button></td>`;
}

function rowMarkup(res: MatrixResource, tool: ToolRow, cols: readonly CanalColumns[]): string {
  const condition = conditionOf(tool);
  const keeps = keepsOf(tool);
  const ordered = [...cols.filter((c) => c.canal.key !== ALONE_CANAL), ...cols.filter((c) => c.canal.key === ALONE_CANAL)];
  const cells = ordered.map((c) => c.moments.map((m) => cellMarkup(tool, c.canal.key, m.key)).join("")).join("");
  return `<tr data-tool="${h(tool.name)}"><th class="mx-tool"><button type="button" class="mx-name" data-outil="${h(res.key)}|${h(tool.name)}">
      <span class="tool-nat ${tool.acts ? "agit" : "lit"}" title="${tool.acts ? "elle agit" : "elle lit"}">${ico(tool.acts ? "bolt" : "eye", "xs")}</span>
      <span class="mx-label"><b>${h(toolLabel(tool.description, tool.name))}</b><code>${h(tool.name)}</code></span>
      ${condition ? `<span class="mx-cond" title="${h(condition)}">${ico("lock", "xs")}</span>` : ""}
      ${keeps.length ? `<span class="mx-cond" title="Ce qu'elle en garde : ${h(keeps.join(", "))}">${ico("book", "xs")}</span>` : ""}</button></th>
    ${cells}</tr>`;
}

const REPLY_TAGS: Record<string, string> = { seule: "ok", accord: "warn", brouillon: "info", non: "" };

/** La règle du canal d'un de tes comptes : qui, préparer d'elle-même, comment ça part ; `titled` : son titre au-dessus
 * (sans lui, sous une section qui le porte déjà, seulement son canal). */
export function rulesMarkup(rules: Rules, kind: "mail" | "teams", titled = true): string {
  const line = (n: string, who: string, prepare: boolean, reply: string, words: string, def = false) =>
    `<tr${def ? ' class="def"' : ""}><td class="muted">${h(n)}</td><td>${def ? "<b>Par défaut</b>" : h(who)}</td>
      <td>${prepare ? "oui" : "non"}</td><td><span class="tag ${REPLY_TAGS[reply] ?? ""}">${h(words)}</span></td></tr>`;
  const rows = rules.lines.map((l, i) => line(String(i + 1), [l.who || "tout le monde", l.when && l.when !== "toujours" ? l.when : ""].filter(Boolean).join(" · "), l.prepare, l.reply, l.reply_words)).join("");
  const where = kind === "teams" ? "Teams" : "Mail";
  const head = titled
    ? `<h4>${ico("send", "sm")}Comment part ce qu'elle prépare <span class="muted">· canal ${h(rules.canal)}</span></h4>`
    : `<p class="small muted">Le canal ${h(rules.canal)}, lu de haut en bas : la première ligne qui correspond décide.</p>`;
  return `<div class="mx-envoi">${head}
    <table class="tbl mx-rules"><thead><tr><th>#</th><th>Qui écrit (ou quelle discussion)</th><th>Préparer d'elle-même</th><th>Comment ça part</th></tr></thead><tbody>
    ${rows}${line("—", "", rules.default.prepare, rules.default.reply, rules.default.reply_words, true)}</tbody></table>
    <p class="small muted">Ce qu'elle prépare se relit dans ${where}, dans « Ses brouillons ».${rules.set ? "" : " Ce tableau n'a jamais été réglé : c'est sa règle de départ."}</p></div>`;
}

/** Un outil dont aucune case ne dit rien (il ne sert à aucun de ces moments : une séance à elle, un réveil…). */
export function idle(tool: ToolRow): boolean {
  return Object.values(tool.cells).every((c) => c === null || c === undefined);
}

/** Les outils qu'on montre en lignes (les autres, en une phrase sous le tableau). */
export function shownTools(tools: readonly ToolRow[]): ToolRow[] {
  return tools.filter((t) => !idle(t));
}

export function tableMarkup(res: MatrixResource, cols: readonly CanalColumns[], q: string): string {
  const found = res.tools.filter((t) => toolMatches(res, t, q));
  const tools = shownTools(found);
  const quiet = found.filter(idle);
  if (!found.length && (q.trim() || !res.rules)) return "";
  const table = tools.length
    ? `<div class="mx-scroll"><table class="mx">${headMarkup(cols)}<tbody>${tools.map((t) => rowMarkup(res, t, cols)).join("")}</tbody></table></div>`
    : "";
  const rest = quiet.length
    ? `<p class="mx-idle small muted">${quiet.length === 1 ? "Un outil ne sert" : `${quiet.length} outils ne servent`} à aucun de ces moments : ${quiet
        .map((t) => `<button type="button" class="mx-idle-tool" data-outil="${h(res.key)}|${h(t.name)}" title="${h(toolLabel(t.description, t.name))}"><code>${h(t.name)}</code></button>`)
        .join(", ")}.</p>`
    : "";
  return `<section class="mx-res" id="res-${h(res.key.replace(/[^a-z0-9_-]/gi, "-"))}" data-res-key="${h(res.key)}">
    <header class="mx-head"><span class="fam-ico${res.internal ? " interne" : ""}">${ico(res.icon)}</span><div class="grow"><h3>${h(res.title)}</h3>${res.sub ? `<p>${h(res.sub)}</p>` : ""}</div></header>
    ${table}${rest}${res.rules && res.kind ? rulesMarkup(res.rules, res.kind) : ""}</section>`;
}

export function navMarkup(resources: readonly MatrixResource[], selected: string | null): string {
  const total = resources.reduce((n, r) => n + shownTools(r.tools).length, 0);
  const groups: { key: string; title: string; items: MatrixResource[] }[] = [];
  for (const r of resources) {
    let g = groups.find((x) => x.key === r.group);
    if (!g) {
      g = { key: r.group, title: r.groupTitle, items: [] };
      groups.push(g);
    }
    g.items.push(r);
  }
  const link = (r: MatrixResource) => {
    const c = countsOf(r.tools);
    return `<button type="button" data-res="${h(r.key)}" class="${selected === r.key ? "on" : ""}" title="${h(r.title)}${r.sub ? ` — ${h(r.sub)}` : ""}">${ico(r.icon)}<span class="ellipsis">${h(r.navTitle)}</span>
      <span class="mx-mini">${c.alone ? `<i class="ok">${c.alone}</i>` : ""}${c.ask ? `<i class="warn">${c.ask}</i>` : ""}</span></button>`;
  };
  return `<div class="pane-scroll mx-nav"><div class="nav-list"><button type="button" data-res="" class="${selected ? "" : "on"}">${ico("tools")}<span>Tout</span><span class="cnt">${total}</span></button></div>
    ${groups.map((g) => `<div class="group-label">${h(g.title)}</div><div class="nav-list">${g.items.length ? g.items.map(link).join("") : ""}</div>`).join("")}
    <p class="mx-nav-help small muted">Les chiffres : ce qu'elle fait seule, et ce qu'elle te demande, quand elle te répond sur le web et l'app Android.</p></div>`;
}

export function selectMarkup(resources: readonly MatrixResource[], selected: string | null): string {
  return `<select class="mx-select" data-res-select aria-label="Ressource">${[
    `<option value="">Toutes les ressources</option>`,
    ...resources.map((r) => `<option value="${h(r.key)}"${selected === r.key ? " selected" : ""}>${h(r.title)}</option>`),
  ].join("")}</select>`;
}

/** Le « pourquoi » d'une case, dans sa bulle. */
export function whyMarkup(tool: ToolRow, cell: Cell, canal: string, moment: string): string {
  const l = levelOf(cell);
  const { why, keep } = whyOf(cell);
  return `<div class="pq"><b>${h(toolLabel(tool.description, tool.name))}</b><span class="muted">${h(canal)} · ${h(moment)}</span>
    <span><span class="lv ${l.cls}">${h(l.word)}</span> ${h(l.long)}</span>
    ${why ? `<span>Pourquoi : ${h(why)}</span>` : ""}${keep ? `<span>Ce qu'elle en garde : ${h(keep)}</span>` : ""}</div>`;
}

/** Le détail d'un outil : ce qu'il fait, et pour toi, canal par canal, où elle s'en sert. */
export function toolDetailMarkup(res: MatrixResource, tool: ToolRow, rights: Rights): string {
  const condition = conditionOf(tool);
  const keeps = keepsOf(tool);
  const canals = new Map(rights.canals.map((c) => [c.key, c.label]));
  const moments = new Map(rights.moments.map((m) => [m.key, m.label]));
  const open = Object.entries(tool.cells)
    .filter(([, c]) => c && c.level !== "non")
    .map(([k, c]) => {
      const [canal, moment] = k.split("/");
      const l = levelOf(c);
      return `<li><span class="lv ${l.cls}">${h(l.word)}</span> ${h(canals.get(canal) ?? canal)}, ${h(moments.get(moment) ?? moment)}</li>`;
    });
  return `<div class="stack"><p class="small muted"><code>${h(tool.name)}</code> · ${h(res.title)} · ${tool.acts ? "elle agit : ça change quelque chose ailleurs" : "elle lit : rien ne change ailleurs"}</p>
    ${tool.description ? `<p class="text-2">${h(tool.description)}</p>` : ""}
    ${condition ? `<p class="det-p">${ico("lock", "sm")}<span>${h(condition)}</span></p>` : ""}
    ${keeps.length ? `<p class="det-p">${ico("book", "sm")}<span>Ce qu'elle en garde : ${h(keeps.join(", "))}</span></p>` : ""}
    <p class="small text-2">${open.length ? "Pour toi, elle s'en sert :" : "Pour toi, aucune case ne l'ouvre."}</p>
    ${open.length ? `<ul class="mx-lines det-open">${open.join("")}</ul>` : ""}</div>`;
}
