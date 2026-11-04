import { describe, expect, it } from "vitest";
import type { Cell, Rights, ToolRow } from "../../api/rights";
import {
  columns,
  countsOf,
  idle,
  internalOnly,
  levelOf,
  navMarkup,
  resourcesOf,
  rulesMarkup,
  tableMarkup,
  toolLabel,
  whyMarkup,
  whyOf,
} from "./matrix";

const cell = (level: Cell["level"], extra: Partial<Cell> = {}): Cell => ({ level, keep: "public", why: "ligne 1", reason: "", owned: false, ...extra });

function tool(name: string, cells: Record<string, Cell | null>, extra: Partial<ToolRow> = {}): ToolRow {
  return { name, description: `${name} : ce qu'il fait.`, acts: false, cells, ...extra };
}

const RIGHTS: Rights = {
  canals: [
    { key: "web", label: "Chat web" }, { key: "salon", label: "Un salon" }, { key: "mobile", label: "App Android" },
    { key: "teams", label: "Teams" }, { key: "courrier", label: "Courrier" }, { key: "seule", label: "Elle seule" },
  ],
  moments: [
    { key: "reply", label: "quand elle te répond" }, { key: "initiative", label: "quand elle te parle d'elle-même" },
    { key: "work", label: "quand elle travaille seule" },
  ],
  groups: [
    { key: "families", title: "Ses propres outils", resources: [
      { key: "famille:email", title: "Courrier", description: "tes boîtes", tools: [
        tool("email_read", { "web/reply": cell("seule"), "mobile/reply": cell("toi"), "salon/reply": cell("non"), "seule/work": cell("seule") }),
        tool("email_tidy", { "web/reply": cell("carte"), "mobile/reply": cell("seule"), "seule/work": null }, { acts: true }),
        tool("goal_drop", { "web/reply": null, "seule/work": null }),
      ] },
      { key: "famille:self", title: "Son journal", description: "relire son journal", tools: [
        tool("self_journal", { "web/reply": cell("non"), "seule/work": cell("seule") }),
      ] },
    ] },
    { key: "accounts", title: "Tes comptes", resources: [
      { key: "courrier:pro", kind: "mail", title: "Boîte Pro", address: "a@b.test", family: "famille:email", rules: {
        canal: "courrier:pro", set: false, default: { who: "", when: "toujours", prepare: false, reply: "non", reply_words: "non" },
        lines: [{ who: "Tout le monde", when: "toujours", prepare: true, reply: "accord", reply_words: "ton accord" }] } },
    ] },
    { key: "services", title: "Services", resources: [{ key: "mcp:web", title: "Service « web »", tools: [tool("mcp_web_search", { "web/reply": cell("seule") })] }] },
    { key: "apps", title: "Apps de la Forge", resources: [] },
  ],
};

describe("les cases", () => {
  it("dit chaque niveau, et « — » pour un outil qui ne sert pas à ce moment", () => {
    expect(levelOf(cell("seule"))).toMatchObject({ cls: "ok", word: "Seule" });
    expect(levelOf(cell("carte"))).toMatchObject({ cls: "warn", word: "Demande" });
    expect(levelOf(cell("toi"))).toMatchObject({ cls: "warn", word: "Ton accord" });
    expect(levelOf(cell("non"))).toMatchObject({ cls: "off", word: "Non" });
    expect(levelOf(null)).toMatchObject({ cls: "off", word: "—" });
  });

  it("dit pourquoi : ses lignes, sa condition, une ressource à ton nom, ce qu'elle garde", () => {
    expect(whyOf(cell("seule"))).toEqual({ why: "ligne 1", keep: "un savoir" });
    expect(whyOf(cell("non", { keep: "rien" }))).toEqual({ why: "ligne 1", keep: "" });
    expect(whyOf(cell("non", { reason: "when", why: "En tête-à-tête." }))).toEqual({ why: "sa condition : En tête-à-tête.", keep: "" });
    expect(whyOf(cell("seule", { owned: true, keep: "perso", why: "une ressource à ton nom (ADR 0185)" }))).toEqual({ why: "une ressource à ton nom", keep: "un souvenir" });
    const html = whyMarkup(tool("email_read", {}), cell("toi", { why: "ligne 2 <b>" }), "Chat web", "quand elle te répond");
    expect(html).toContain("Pourquoi : ligne 2 &lt;b&gt;");
    expect(html).toContain("Elle attend ton accord");
  });
});

describe("les colonnes et les ressources", () => {
  it("donne à chaque canal qui parle ses deux moments, à elle seule son travail", () => {
    const cols = columns(RIGHTS.canals, RIGHTS.moments);
    expect(cols.map((c) => [c.canal.key, c.moments.map((m) => m.key)])).toEqual([
      ["web", ["reply", "initiative"]], ["salon", ["reply", "initiative"]], ["mobile", ["reply", "initiative"]],
      ["teams", ["reply", "initiative"]], ["courrier", ["reply", "initiative"]], ["seule", ["work"]],
    ]);
  });

  it("un compte reprend les outils de sa famille ; ce qui est à elle seule se dit", () => {
    const owned = { words: new Map([["mail:pro", "à toi"], ["mcp:web", "un service de Mika"]]) };
    const res = resourcesOf(RIGHTS, owned);
    expect(res.map((r) => r.key)).toEqual(["famille:email", "famille:self", "courrier:pro", "mcp:web"]);
    const pro = res.find((r) => r.key === "courrier:pro")!;
    expect(pro.title).toBe("Courrier · Boîte Pro");
    expect(pro.sub).toBe("a@b.test · à toi");
    expect(pro.tools.map((t) => t.name)).toEqual(["email_read", "email_tidy", "goal_drop"]);
    expect(res.find((r) => r.key === "famille:self")!.internal).toBe(true);
    expect(internalOnly(RIGHTS.groups[0].resources[0].tools!)).toBe(false);
  });

  it("compte ce qu'elle fait seule et ce qu'elle demande, sur le web et l'app Android quand elle répond", () => {
    expect(countsOf(RIGHTS.groups[0].resources[0].tools!)).toEqual({ alone: 2, ask: 2 });
  });
});

describe("le nom d'un outil", () => {
  it("prend la première proposition de sa description", () => {
    expect(toolLabel("Renoncer à ce but (seulement ce que tu as entrepris).", "goal_drop")).toBe("Renoncer à ce but");
    expect(toolLabel("Tes boîtes aux lettres : leurs dossiers, ce qui n'est pas lu.", "x")).toBe("Tes boîtes aux lettres");
    expect(toolLabel("Ouvrir un mail de ta boîte.", "x")).toBe("Ouvrir un mail de ta boîte");
    expect(toolLabel("Conclure cette séance par un verdict. « done » n'est cru que…", "x")).toBe("Conclure cette séance par un verdict");
    expect(toolLabel("Lister les mails d'une boîte ou d'un dossier, du plus récent au plus ancien, page par page : leur date", "x")).toBe("Lister les mails d'une boîte ou d'un dossier");
    expect(toolLabel("Activer, arrêter, revenir à la version précédente (le code seulement)", "x")).toBe("Activer, arrêter, revenir à la version précédente");
    expect(toolLabel("", "forge_help")).toBe("forge_help");
  });
});

describe("le balisage", () => {
  const cols = columns(RIGHTS.canals, RIGHTS.moments);
  const res = resourcesOf(RIGHTS);

  it("met un outil par ligne, une case par canal et moment, et les outils sans moment en une phrase", () => {
    const html = tableMarkup(res[0], cols, "");
    expect((html.match(/<tr data-tool=/g) ?? []).length).toBe(2);
    expect((html.match(/class="mx-c"/g) ?? []).length).toBe(2 * 11);
    expect(html).toContain('data-cell="web/reply"');
    expect(html).toContain("Un outil ne sert à aucun de ces moments");
    expect(idle(RIGHTS.groups[0].resources[0].tools![2])).toBe(true);
  });

  it("filtre par la recherche, et ne montre rien quand rien ne correspond", () => {
    expect(tableMarkup(res[0], cols, "tidy")).toContain("email_tidy");
    expect(tableMarkup(res[0], cols, "tidy")).not.toContain('data-tool="email_read"');
    expect(tableMarkup(res[0], cols, "introuvable")).toBe("");
  });

  it("montre la règle d'un compte, avec sa ligne par défaut", () => {
    const html = rulesMarkup(RIGHTS.groups[1].resources[0].rules!, "mail");
    expect(html).toContain("canal courrier:pro");
    expect(html).toContain("Tout le monde");
    expect(html).toContain("ton accord");
    expect(html).toContain("<b>Par défaut</b>");
    expect(html).toContain("sa règle de départ");
  });

  it("le menu range les ressources par groupe et compte les outils montrés", () => {
    const html = navMarkup(res, "courrier:pro");
    expect(html).toContain("Ses propres outils");
    expect(html).toContain("Tes comptes");
    expect(html).toContain('data-res="courrier:pro" class="on"');
    expect(html).toContain('<span class="cnt">6</span>');
  });
});
