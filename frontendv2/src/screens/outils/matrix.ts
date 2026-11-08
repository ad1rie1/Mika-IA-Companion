/**
 * Outils : la matrice de tes droits telle que le moteur la calcule (`GET /api/moi/rights`), mise en tableaux comme
 * dans la maquette (`maquette/ecrans/outils.js`) — une ressource par tableau, ses outils en lignes, chaque canal et
 * chaque moment en colonnes. Rien n'y est recalculé : une case dit la décision du moteur, et pourquoi. Chaque outil
 * s'y nomme pour toi (`label`, ADR 0208) ; un de tes comptes n'y a que ce qui est à lui (ses outils sont ceux de sa
 * famille) ; les services s'y lisent avec ceux que tu as branchés et ceux qu'on te partage. Pur, sans DOM.
 */
import type { ReceivedService, Service } from "../../api/mcp";
import type { Canal, Cell, Keep, Level, Moment, Resource, Rights, Rules, ToolRow } from "../../api/rights";
import { h, norm } from "../../shell/dom";
import { ico, type IconName } from "../../shell/icons";
import { servedOf, shareWords, stateWords } from "../parametres/words";

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
/** Le canal montré d'abord sur un téléphone, où une seule colonne se lit (ADR 0209). */
export const FIRST_CANAL = "web";

/** Les cases qui comptent dans le menu : quand elle te répond, sur le web et l'app Android. */
const COUNTED = ["web/reply", "mobile/reply"];

/** « 1 outil », « 3 outils » : un nom qui suit son nombre. */
function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n > 1 ? many : one}`;
}

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
  /** Le nom dans le menu (un compte y dit sa sorte : « Courrier · Atelier »). */
  navTitle: string;
  sub: string;
  icon: IconName;
  /** Ce qu'elle seule utilise : aucune case ne s'ouvre ailleurs que quand elle travaille. */
  internal: boolean;
  /** Ses outils ; vide pour un compte, dont les outils sont ceux de sa famille. */
  tools: ToolRow[];
  rules?: Rules;
  kind?: "mail" | "teams";
  /** La famille d'un compte (ses outils) : sa clé et son nom. */
  family?: { key: string; title: string };
  /** Où la console montre son tableau : pour une opératrice seulement. */
  href?: string;
  /** À quoi il sert (un service). */
  description?: string;
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

/** Le nom d'une ressource d'ailleurs, sans sa sorte (`mcp:meteo` → `meteo`). */
function bare(key: string): string {
  return key.replace(/^[a-z]+:/, "");
}

/**
 * Ses ressources dans l'ordre de la matrice. Un compte n'a que ce qui est à lui — son adresse, à qui il est, sa règle
 * d'envoi : ses outils sont ceux de sa famille, les mêmes pour toutes tes boîtes (ou tous tes comptes Teams), et ne se
 * recopient pas sous lui.
 */
export function resourcesOf(rights: Rights, owned: Ownership = { words: new Map() }): MatrixResource[] {
  const families = new Map<string, Resource>();
  for (const g of rights.groups) if (g.key === "families") for (const r of g.resources) families.set(r.key, r);
  const out: MatrixResource[] = [];
  for (const g of rights.groups) {
    for (const r of g.resources) {
      if (g.key === "accounts") {
        const kind = r.kind === "teams" ? "teams" : "mail";
        const whose = owned.words.get(`${kind}:${r.key.replace(/^(courrier|teams):/, "")}`);
        const family = r.family ? families.get(r.family) : undefined;
        const title = `${kind === "teams" ? "Teams" : "Courrier"} · ${r.title}`;
        out.push({
          key: r.key, group: g.key, groupTitle: g.title, title, navTitle: title,
          sub: [r.address, whose].filter(Boolean).join(" · "),
          icon: kind === "teams" ? "teams" : "mail", internal: false, tools: [], rules: r.rules, kind,
          family: family ? { key: family.key, title: family.title } : undefined,
        });
        continue;
      }
      const tools = r.tools ?? [];
      if (g.key === "services" || g.key === "apps") {
        const name = bare(r.key);
        const whose = owned.words.get(`mcp:${name}`) ?? (g.key === "apps" ? "une app de la Forge" : "un service de Mika");
        out.push({
          key: r.key, group: g.key, groupTitle: g.title, title: r.title, navTitle: r.title,
          sub: [r.description, whose].filter(Boolean).join(" · "), description: r.description || "",
          icon: g.key === "apps" ? "code" : name === "web" ? "globe" : "server", internal: false, tools, href: r.href,
        });
        continue;
      }
      const internal = internalOnly(tools);
      out.push({
        key: r.key, group: g.key, groupTitle: g.title, title: r.title, navTitle: r.title,
        sub: internal ? `${r.description || ""}${r.description ? " · " : ""}ce qu'elle seule utilise` : r.description || "",
        icon: familyIcon(r.key), internal, tools, href: r.href,
      });
    }
  }
  return out;
}

/**
 * Ce qu'elle fait pour toi, en outils : un outil compte une fois s'il s'ouvre quand elle te répond sur le web ou
 * l'app Android — `alone` s'il y en a un où elle s'en sert seule, sinon `ask` (elle te demande, ou ton accord).
 */
export function countsOf(tools: readonly ToolRow[]): { alone: number; ask: number } {
  let alone = 0;
  let ask = 0;
  for (const t of tools) {
    const levels = COUNTED.map((k) => t.cells[k]?.level);
    if (levels.includes("seule")) alone += 1;
    else if (levels.some((l) => l === "carte" || l === "toi")) ask += 1;
  }
  return { alone, ask };
}

/** Ce que disent les chiffres du menu, en entier (la bulle des pastilles). */
export function countsWords(c: { alone: number; ask: number }): string {
  const parts = [
    c.alone ? `${plural(c.alone, "outil")} dont elle se sert seule` : "",
    c.ask ? `${plural(c.ask, "outil")} pour ${c.ask > 1 ? "lesquels" : "lequel"} elle te demande` : "",
  ].filter(Boolean);
  return parts.length
    ? `${parts.join(", ")}, quand elle te répond sur le web ou l'app Android`
    : "Aucun outil ne s'ouvre pour toi quand elle te répond sur le web ou l'app Android";
}

// ── Un outil ─────────────────────────────────────────────────────────

/**
 * Le repli, pour un outil venu d'ailleurs (un service, une app) qui n'a pas de libellé : la première proposition de
 * sa description, sinon son nom. « Lister les mails d'une boîte ou d'un dossier, du plus récent… » → « Lister les
 * mails d'une boîte ou d'un dossier ».
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

/** Le nom d'un outil pour toi : son libellé (ADR 0208) ; un outil venu d'ailleurs, par sa description. */
export function labelOf(tool: Pick<ToolRow, "label" | "description" | "name">): string {
  return tool.label?.trim() || toolLabel(tool.description, tool.name);
}

/** Ce que « Lui demander » pose dans le champ du chat, à relire avant d'envoyer. */
export function askFor(tool: Pick<ToolRow, "label" | "description" | "name">): string {
  return `Tu peux te servir de « ${labelOf(tool)} » pour moi ?`;
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

/** Pourquoi une case, tel que le moteur le dit pour toi ; sa condition, s'il en a une ; ce qu'elle en garde. */
export function whyOf(cell: Cell): { why: string; keep: string } {
  let why = cell.why.trim();
  if (cell.reason === "when" && why) why = `sa condition : ${why}`;
  const keep = cell.level !== "non" && cell.keep !== "rien" ? KEEP_WORDS[cell.keep] ?? cell.keep : "";
  return { why, keep };
}

export function toolMatches(res: MatrixResource, tool: ToolRow, q: string): boolean {
  const needle = norm(q.trim());
  if (!needle) return true;
  return norm(`${labelOf(tool)} ${tool.name} ${res.title}`).includes(needle);
}

// ── Le balisage ──────────────────────────────────────────────────────

export function legendMarkup(): string {
  const lv = (l: Level) => `<span class="lv ${LEVELS[l].cls}">${h(LEVELS[l].word)}</span>`;
  return `<div class="mx-legend">${lv("seule")}${lv("carte")}${lv("toi")}${lv("non")}<span><span class="lv off">—</span> il ne sert pas à ce moment</span>
    <span>${ico("lock", "xs")} sous une condition</span><span>${ico("book", "xs")} ce qu'elle en garde</span></div>`;
}

/** Sur un téléphone, une seule colonne se lit : celles des autres canaux s'effacent (`mx-other`, `outils.css`). */
function other(canal: string, only: string | null): string {
  return only && canal !== only ? " mx-other" : "";
}

function headMarkup(cols: readonly CanalColumns[], only: string | null): string {
  const talking = cols.filter((c) => c.canal.key !== ALONE_CANAL);
  const alone = cols.find((c) => c.canal.key === ALONE_CANAL);
  const sub = (key: string) => (CANAL_SUB[key] ? `<small>${h(CANAL_SUB[key])}</small>` : "");
  const first = talking
    .map((c) => `<th colspan="${c.moments.length}" class="mx-canal${other(c.canal.key, only)}">${h(c.canal.label)}${sub(c.canal.key)}</th>`)
    .join("");
  const second = talking
    .map((c) => c.moments.map((m) => `<th class="mx-q${other(c.canal.key, only)}" title="${h(m.label)}">${h(MOMENT_SHORT[m.key] ?? m.label)}</th>`).join(""))
    .join("");
  const last = alone ? `<th rowspan="2" class="mx-canal seule${other(alone.canal.key, only)}" title="${h(alone.moments.map((m) => m.label).join(", "))}">${h(alone.canal.label)}${sub(alone.canal.key)}</th>` : "";
  return `<thead><tr><th rowspan="2" class="mx-tool-h">Outil</th>${first}${last}</tr><tr>${second}</tr></thead>`;
}

function cellMarkup(tool: ToolRow, canal: string, moment: string, only: string | null): string {
  const key = cellKey(canal, moment);
  const cell = tool.cells[key];
  const l = levelOf(cell);
  const cls = `mx-c${other(canal, only)}`;
  if (!cell) return `<td class="${cls}"><span class="lv off" title="${h(l.long)}">—</span></td>`;
  return `<td class="${cls}"><button type="button" class="lv ${l.cls}" data-cell="${h(key)}" title="${h(l.long)}">${h(l.word)}</button></td>`;
}

function rowMarkup(res: MatrixResource, tool: ToolRow, cols: readonly CanalColumns[], only: string | null): string {
  const condition = conditionOf(tool);
  const keeps = keepsOf(tool);
  const ordered = [...cols.filter((c) => c.canal.key !== ALONE_CANAL), ...cols.filter((c) => c.canal.key === ALONE_CANAL)];
  const cells = ordered.map((c) => c.moments.map((m) => cellMarkup(tool, c.canal.key, m.key, only)).join("")).join("");
  return `<tr data-tool="${h(tool.name)}"><th class="mx-tool"><button type="button" class="mx-name" data-outil="${h(res.key)}|${h(tool.name)}">
      <span class="tool-nat ${tool.acts ? "agit" : "lit"}" title="${tool.acts ? "elle agit" : "elle lit"}">${ico(tool.acts ? "bolt" : "eye", "xs")}</span>
      <span class="mx-label"><b>${h(labelOf(tool))}</b></span>
      ${condition ? `<span class="mx-cond" title="${h(condition)}">${ico("lock", "xs")}</span>` : ""}
      ${keeps.length ? `<span class="mx-cond" title="Ce qu'elle en garde : ${h(keeps.join(", "))}">${ico("book", "xs")}</span>` : ""}</button></th>
    ${cells}</tr>`;
}

const REPLY_TAGS: Record<string, string> = { seule: "ok", accord: "warn", brouillon: "info", non: "" };

/** La règle qui vaut pour un de tes comptes : qui, préparer d'elle-même, comment ça part, lue de haut en bas. */
export function rulesMarkup(rules: Rules, kind: "mail" | "teams"): string {
  const line = (n: string, who: string, prepare: boolean, reply: string, words: string, def = false) =>
    `<tr${def ? ' class="def"' : ""}><td class="muted">${h(n)}</td><td>${def ? "<b>Par défaut</b>" : h(who)}</td>
      <td>${prepare ? "oui" : "non"}</td><td><span class="tag ${REPLY_TAGS[reply] ?? ""}">${h(words)}</span></td></tr>`;
  const rows = rules.lines.map((l, i) => line(String(i + 1), [l.who || "tout le monde", l.when && l.when !== "toujours" ? l.when : ""].filter(Boolean).join(" · "), l.prepare, l.reply, l.reply_words)).join("");
  const mail = kind === "mail";
  const where = mail ? "Mail" : "Teams";
  const which = mail ? "cette boîte" : "ce compte";
  const origin = rules.set
    ? ""
    : rules.common
      ? ` C'est la règle commune à ${mail ? "toutes tes boîtes" : "tous tes comptes Teams"}.`
      : " Ce tableau n'a jamais été réglé : c'est sa règle de départ.";
  return `<div class="mx-envoi"><h4>${ico("send", "sm")}Comment part ce qu'elle prépare <span class="muted">· pour ${which}</span></h4>
    <p class="small muted">Lue de haut en bas : la première ligne qui correspond décide.</p>
    <table class="tbl mx-rules"><thead><tr><th>#</th><th>Qui écrit (ou quelle discussion)</th><th>Préparer d'elle-même</th><th>Comment ça part</th></tr></thead><tbody>
    ${rows}${line("—", "", rules.default.prepare, rules.default.reply, rules.default.reply_words, true)}</tbody></table>
    <p class="small muted">Ce qu'elle prépare se relit dans ${where}, dans « Ses brouillons ».${origin}</p></div>`;
}

/** Ce qu'un compte ne recopie pas : ses outils sont ceux de sa famille, les mêmes pour tous ; et où se règle sa règle. */
function accountMarkup(res: MatrixResource): string {
  const mail = res.kind !== "teams";
  const fam = res.family
    ? `<button type="button" class="mx-link" data-res="${h(res.family.key)}">« ${h(res.family.title)} »</button>`
    : `« ${mail ? "Courrier" : "Teams"} »`;
  const settings = `#parametres/${mail ? "comptes-mail" : "teams"}/${encodeURIComponent(res.key.replace(/^(courrier|teams):/, ""))}`;
  return `<p class="mx-family small text-2">${ico("tools", "sm")}<span>Ses outils sont ceux de ${fam}, les mêmes pour ${mail ? "toutes tes boîtes" : "tous tes comptes Teams"}. Sa règle d'envoi se règle dans <a href="${h(settings)}">Paramètres</a>.</span></p>`;
}

/** Un outil dont aucune case ne dit rien (il ne sert à aucun de ces moments : une séance à elle, un réveil…). */
export function idle(tool: ToolRow): boolean {
  return Object.values(tool.cells).every((c) => c === null || c === undefined);
}

/** Les outils qu'on montre en lignes (les autres, repliés sous le tableau). */
export function shownTools(tools: readonly ToolRow[]): ToolRow[] {
  return tools.filter((t) => !idle(t));
}

/** Les outils qui ne servent à aucun de ces moments : repliés derrière une phrase, nommés pour toi quand on la déplie. */
function idleMarkup(res: MatrixResource, quiet: readonly ToolRow[], shown: number): string {
  if (!quiet.length) return "";
  const n = quiet.length;
  const said = n === 1
    ? `${shown ? "Un autre outil" : "Un outil"} ne sert à aucun de ces moments`
    : `${n} ${shown ? "autres outils" : "outils"} ne servent à aucun de ces moments`;
  const items = quiet
    .map((t) => `<li><button type="button" class="mx-idle-tool" data-outil="${h(res.key)}|${h(t.name)}">${h(labelOf(t))}</button></li>`)
    .join("");
  return `<details class="mx-idle small muted"><summary>${h(said)}</summary><ul>${items}</ul></details>`;
}

/** Le tableau d'une ressource ; `only` : le canal choisi sur un téléphone (les autres s'y effacent). */
export function tableMarkup(res: MatrixResource, cols: readonly CanalColumns[], q: string, only: string | null = null): string {
  const found = res.tools.filter((t) => toolMatches(res, t, q));
  const tools = shownTools(found);
  const quiet = found.filter(idle);
  if (!found.length && (q.trim() || !res.rules)) return "";
  const table = tools.length
    ? `<div class="mx-scroll"><table class="mx">${headMarkup(cols, only)}<tbody>${tools.map((t) => rowMarkup(res, t, cols, only)).join("")}</tbody></table></div>`
    : "";
  const account = res.rules && res.kind ? `${accountMarkup(res)}${rulesMarkup(res.rules, res.kind)}` : "";
  return `<section class="mx-res" id="res-${h(res.key.replace(/[^a-z0-9_-]/gi, "-"))}" data-res-key="${h(res.key)}">
    <header class="mx-head"><span class="fam-ico${res.internal ? " interne" : ""}">${ico(res.icon)}</span><div class="grow"><h3>${h(res.title)}</h3>${res.sub ? `<p>${h(res.sub)}</p>` : ""}</div></header>
    ${table}${idleMarkup(res, quiet, tools.length)}${account}</section>`;
}

/** Ses chiffres, avec ce qu'ils disent en entier ; rien quand aucun outil ne s'ouvre (un compte n'en a pas à lui). */
function pills(c: { alone: number; ask: number }): string {
  if (!c.alone && !c.ask) return "";
  const title = h(countsWords(c));
  return `<span class="mx-mini" title="${title}">${c.alone ? `<i class="ok">${c.alone}</i>` : ""}${c.ask ? `<i class="warn">${c.ask}</i>` : ""}</span>`;
}

export function navMarkup(resources: readonly MatrixResource[], selected: string | null): string {
  // « Tout » : chaque outil une fois — un compte n'en a pas à lui, ceux de sa famille comptent sous elle
  const total = resources.reduce(
    (n, r) => {
      const c = countsOf(r.tools);
      return { alone: n.alone + c.alone, ask: n.ask + c.ask };
    },
    { alone: 0, ask: 0 },
  );
  const groups: { key: string; title: string; items: MatrixResource[] }[] = [];
  for (const r of resources) {
    let g = groups.find((x) => x.key === r.group);
    if (!g) {
      g = { key: r.group, title: r.groupTitle, items: [] };
      groups.push(g);
    }
    g.items.push(r);
  }
  const link = (r: MatrixResource) =>
    `<button type="button" data-res="${h(r.key)}" class="${selected === r.key ? "on" : ""}" title="${h(r.title)}${r.sub ? ` — ${h(r.sub)}` : ""}">${ico(r.icon)}<span class="ellipsis">${h(r.navTitle)}</span>
      ${pills(countsOf(r.tools))}</button>`;
  return `<div class="pane-scroll mx-nav"><p class="mx-nav-help small muted">Les chiffres comptent ses outils : seule, ou en te demandant, quand elle te répond sur le web ou l'app Android.</p>
    <div class="nav-list"><button type="button" data-res="" class="${selected ? "" : "on"}">${ico("tools")}<span>Tout</span>${pills(total)}</button></div>
    ${groups.map((g) => `<div class="group-label">${h(g.title)}</div><div class="nav-list">${g.items.length ? g.items.map(link).join("") : ""}</div>`).join("")}</div>`;
}

export function selectMarkup(resources: readonly MatrixResource[], selected: string | null): string {
  return `<select class="mx-select" data-res-select aria-label="Ressource">${[
    `<option value="">Toutes les ressources</option>`,
    ...resources.map((r) => `<option value="${h(r.key)}"${selected === r.key ? " selected" : ""}>${h(r.navTitle)}</option>`),
  ].join("")}</select>`;
}

/** Sur un téléphone, le canal dont on lit la colonne (ADR 0209) ; caché sur un grand écran, où tout se lit. */
export function canalPickMarkup(canals: readonly Canal[], only: string): string {
  return `<label class="mx-canal-pick"><span class="small muted">Par où</span><select data-mx-canal aria-label="Canal">${canals
    .map((c) => `<option value="${h(c.key)}"${c.key === only ? " selected" : ""}>${h(c.label)}${CANAL_SUB[c.key] ? ` (${h(CANAL_SUB[c.key])})` : ""}</option>`)
    .join("")}</select></label>`;
}

/** Le « pourquoi » d'une case, dans sa bulle ; pour une opératrice, la ligne même et où la console la montre
 *  (`console` : son adresse, déjà vérifiée). */
export function whyMarkup(tool: ToolRow, cell: Cell, canal: string, moment: string, console = ""): string {
  const l = levelOf(cell);
  const { why, keep } = whyOf(cell);
  const line = cell.line?.trim() ?? "";
  const rule = line
    ? `<span>Dans la console : ${console ? `<a href="${h(console)}" target="_blank" rel="noopener">${h(line)}</a>` : h(line)}</span>`
    : "";
  return `<div class="pq"><b>${h(labelOf(tool))}</b><span class="muted">${h(canal)} · ${h(moment)}</span>
    <span><span class="lv ${l.cls}">${h(l.word)}</span> ${h(l.long)}</span>
    ${why ? `<span>Pourquoi : ${h(why)}</span>` : ""}${keep ? `<span>Ce qu'elle en garde : ${h(keep)}</span>` : ""}${rule}</div>`;
}

/**
 * Le détail d'un outil : ce qu'il fait, pour toi, et, canal par canal, où elle s'en sert. Son nom de code n'est
 * qu'ici, en petit ; sa consigne au modèle (« tu », c'est elle) ne se montre pas — sauf pour un outil venu d'ailleurs,
 * qui n'a qu'elle pour se dire.
 */
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
  const said = tool.label?.trim()
    ? ""
    : tool.description.trim()
      ? `<p class="text-2"><span class="muted">Ce que son service en dit : </span>${h(tool.description)}</p>`
      : "";
  return `<div class="stack"><p class="small muted">${h(res.title)} · ${tool.acts ? "elle agit : ça change quelque chose ailleurs" : "elle lit : rien ne change ailleurs"}</p>
    ${said}
    ${condition ? `<p class="det-p">${ico("lock", "sm")}<span>${h(condition)}</span></p>` : ""}
    ${keeps.length ? `<p class="det-p">${ico("book", "sm")}<span>Ce qu'elle en garde : ${h(keeps.join(", "))}</span></p>` : ""}
    <p class="small text-2">${open.length ? "Pour toi, elle s'en sert :" : "Pour toi, aucune case ne l'ouvre."}</p>
    ${open.length ? `<ul class="mx-lines det-open">${open.join("")}</ul>` : ""}
    <p class="tiny muted">Son nom pour elle : <code>${h(tool.name)}</code></p></div>`;
}

// ── Les services ─────────────────────────────────────────────────────

/** Une ligne de « Services » : dans la matrice (une case s'ouvre pour toi), à toi, ou qu'on te partage. */
export interface ServiceRow {
  key: string;
  name: string;
  resource?: MatrixResource;
  own?: Service;
  received?: ReceivedService;
}

/**
 * Les lignes de « Services » : ceux dont elle se sert pour toi (la matrice), ceux que tu as branchés, et ceux qu'on te
 * partage — même quand aucune case ne t'en ouvre encore (jamais joint, en panne, aucun outil servi).
 */
export function serviceRows(resources: readonly MatrixResource[], own: readonly Service[], received: readonly ReceivedService[]): ServiceRow[] {
  const rows: ServiceRow[] = resources
    .filter((r) => r.group === "services" || r.group === "apps")
    .map((r) => {
      const name = bare(r.key);
      const service = r.group === "services";
      return {
        key: r.key, name, resource: r,
        own: service ? own.find((s) => s.name === name) : undefined,
        received: service ? received.find((s) => s.name === name) : undefined,
      };
    });
  for (const s of own) if (!rows.some((r) => r.own === s)) rows.push({ key: `mcp:${s.name}`, name: s.name, own: s });
  for (const s of received) if (!rows.some((r) => r.received === s)) rows.push({ key: `mcp:${s.name}`, name: s.name, received: s });
  return rows;
}

/** « partagé avec toi par Adrien (s'en servir) ». */
export function receivedWords(r: Pick<ReceivedService, "owner_name" | "level">): string {
  return `partagé avec toi par ${r.owner_name || "quelqu'un"} (${shareWords(r.level).toLowerCase()})`;
}

/** Avec qui elle s'en sert : pour un des tiens, ses lignes — la tienne se dit « toi », par ce qu'en dit l'API (`mine`),
 *  jamais par un nom comparé ; un service de Mika ou qu'on te partage, toi : une case, ou ta ligne, te l'ouvre. */
export function serviceWho(row: ServiceRow): string {
  if (row.own) return row.own.access.map((a) => (a.mine ? "toi" : a.who)).filter(Boolean).join(", ") || "—";
  return row.resource || row.received ? "toi" : "—";
}

function serviceRowMarkup(row: ServiceRow, tab: string): string {
  const { key, name, resource, own, received } = row;
  const tools = resource?.tools ?? [];
  const open = tools.filter((t) => Object.values(t.cells).some((c) => c && c.level !== "non")).length;
  const keeps = new Set<string>();
  for (const t of tools) for (const c of Object.values(t.cells)) if (c && c.level !== "non" && c.keep !== "rien") keeps.add(KEEP_WORDS[c.keep] ?? c.keep);
  const app = resource?.group === "apps";
  const where = own
    ? `<span class="mono">${h(own.url)}</span>`
    : h(received ? receivedWords(received) : app ? "app de la Forge" : "un service de Mika");
  const purpose = own?.purpose || received?.purpose || resource?.description || "";
  const status = own?.state ?? received?.state;
  const [stateCls, stateText] = status ? stateWords(status) : ["", ""];
  const state = status
    ? `<span class="tag ${stateCls}">${h(stateText)}</span>${own?.detail ? `<div class="tiny muted">${h(own.detail)}</div>` : ""}`
    : `<span class="muted">—</span>`;
  const served = own && !resource ? servedOf(own.tools) : null;
  const count = resource
    ? `${open} / ${tools.length}`
    : served
      ? `${served.served} / ${served.total}`
      : received?.tools.length
        ? `0 / ${received.tools.length}`
        : "—";
  const review = own ? servedOf(own.tools).review : 0;
  const keep = own
    ? [...new Set(own.access.map((a) => a.keep_words).filter(Boolean))].join(", ") || "—"
    : received && !resource
      ? received.line.keep_words || "rien"
      : [...keeps].join(", ") || "rien";
  const title = resource?.title ?? `Service « ${name} »`;
  const tag = own ? '<span class="tag accent">à toi</span>' : received ? '<span class="tag">partagé</span>' : "";
  const actions = [
    resource ? `<a class="btn xs ghost" href="#${tab}/droits/${encodeURIComponent(key)}">Ses droits</a>` : "",
    own ? `<a class="btn xs" href="#parametres/mcp/${encodeURIComponent(name)}">Régler</a>` : "",
    received ? `<a class="btn xs" href="#parametres/mcp/${encodeURIComponent(name)}">Voir</a>` : "",
  ].filter(Boolean).join(" ");
  return `<tr><td><div class="row nowrap">${ico(app ? "code" : name === "web" ? "globe" : "server", "sm")}<b>${h(title)}</b>${tag}</div></td>
    <td class="small">${where}</td><td class="small text-2">${h(purpose || "—")}</td><td>${state}</td>
    <td class="num nowrap">${h(count)}${review ? ` <span class="tag warn">${review} à regarder</span>` : ""}</td><td class="small">${h(serviceWho(row))}</td><td class="small">${h(keep)}</td>
    <td class="actions nowrap">${actions}</td></tr>`;
}

/** L'onglet « Services » : un tableau, une ligne par service ; `tab` : l'écran (ses liens vers « Tes droits »). */
export function servicesMarkup(rows: readonly ServiceRow[], tab: string): string {
  const table = rows.length
    ? `<div class="mx-scroll"><table class="tbl svc-tbl"><thead><tr><th>Service</th><th>Où</th><th>À quoi il lui sert</th><th>État</th><th>Outils pour toi</th><th>Avec qui</th><th>Ce qu'elle en garde</th><th></th></tr></thead><tbody>${rows.map((r) => serviceRowMarkup(r, tab)).join("")}</tbody></table></div>`
    : `<div class="empty">${ico("server")}<b>Aucun service pour toi</b><p>Tu n'as branché aucun service, on ne t'en partage aucun, et aucun de ceux de Mika ne t'est ouvert.</p></div>`;
  return `<div class="fill-scroll"><div class="page-pad">
      <p class="lede">Les services d'où viennent ses outils « venus d'ailleurs » : des serveurs MCP et les apps de la Forge. Elle s'en sert pour toi selon leurs lignes d'accès. Tu branches les tiens dans <a href="#parametres/mcp">Paramètres › Services MCP</a>.</p>
      ${table}
      <p class="small muted tbl-help">« Outils pour toi » : ceux qu'au moins une case de tes droits lui ouvre ; pour un service qui n'en ouvre encore aucun, ceux qu'il sert.</p></div></div>`;
}
