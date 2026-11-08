import { describe, expect, it } from "vitest";
import type { AccessLine, ReceivedService, Service } from "../../api/mcp";
import type { Cell, Rights, ToolRow } from "../../api/rights";
import {
  askFor,
  canalPickMarkup,
  columns,
  countsOf,
  idle,
  internalOnly,
  labelOf,
  levelOf,
  navMarkup,
  resourcesOf,
  rulesMarkup,
  serviceRows,
  servicesMarkup,
  serviceWho,
  tableMarkup,
  toolDetailMarkup,
  toolLabel,
  whyMarkup,
  whyOf,
} from "./matrix";

const cell = (level: Cell["level"], extra: Partial<Cell> = {}): Cell => ({ level, keep: "public", why: "tout le monde, toujours", line: "", reason: "", owned: false, ...extra });

function tool(name: string, cells: Record<string, Cell | null>, extra: Partial<ToolRow> = {}): ToolRow {
  return { name, label: "", description: `${name} : ce qu'il fait.`, acts: false, cells, ...extra };
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
        tool("email_read", { "web/reply": cell("seule"), "mobile/reply": cell("toi"), "salon/reply": cell("non"), "seule/work": cell("seule") }, { label: "Ouvrir un de tes mails" }),
        tool("email_tidy", { "web/reply": cell("carte"), "mobile/reply": cell("seule"), "seule/work": null }, { acts: true, label: "Ranger tes mails" }),
        tool("email_draft", { "web/reply": cell("carte"), "mobile/reply": cell("toi"), "seule/work": null }, { acts: true, label: "Préparer un mail dans une de tes boîtes" }),
        tool("goal_drop", { "web/reply": null, "seule/work": null }, { label: "Renoncer à un but qu'elle s'était donné" }),
      ] },
      { key: "famille:self", title: "Son journal", description: "relire son journal", tools: [
        tool("self_journal", { "web/reply": cell("non"), "seule/work": cell("seule") }, { label: "Relire son journal d'une journée passée" }),
      ] },
    ] },
    { key: "accounts", title: "Tes comptes", resources: [
      { key: "courrier:pro", kind: "mail", title: "Boîte Pro", address: "a@b.test", family: "famille:email", rules: {
        canal: "courrier:pro", set: false, default: { who: "", when: "toujours", prepare: false, reply: "non", reply_words: "non" },
        lines: [{ who: "Tout le monde", when: "toujours", prepare: true, reply: "accord", reply_words: "ton accord" }] } },
    ] },
    // un service de Mika : l'API ne rend pas son but, la ligne de son catalogue écrite pour elle (ADR 0209)
    { key: "services", title: "Services", resources: [{ key: "mcp:web", title: "Service « web »",
      tools: [tool("mcp_web_search", { "web/reply": cell("seule") }, { description: "Search the web. Returns titles." })] }] },
    { key: "apps", title: "Apps de la Forge", resources: [] },
  ],
};

const line = (who: string, mine: boolean): AccessLine => ({
  who, when: "toujours", mine, read: "seule", act: "carte", keep: "prive", read_words: "seule",
  act_words: "demande à la personne", keep_words: "une confidence", tools: [],
});

const OWN: Service = {
  name: "factures", purpose: "Ses factures et ses devis.", when_to_use: "", enabled: true, url: "https://f.example.test/mcp",
  headers: false, state: "connecte", detail: "", tools: [], access: [line("Léa Martin", true), line("Léa Martin", false)], default: null,
};

const RECEIVED: ReceivedService = {
  name: "meteo", purpose: "La météo d'une ville.", enabled: true, state: "jamais", tools: [], level: "servir",
  line: line("Léa Martin", true), owner_name: "Adrien",
};

describe("les cases", () => {
  it("dit chaque niveau, et « — » pour un outil qui ne sert pas à ce moment", () => {
    expect(levelOf(cell("seule"))).toMatchObject({ cls: "ok", word: "Seule" });
    expect(levelOf(cell("carte"))).toMatchObject({ cls: "warn", word: "Demande" });
    expect(levelOf(cell("toi"))).toMatchObject({ cls: "warn", word: "Ton accord" });
    expect(levelOf(cell("non"))).toMatchObject({ cls: "off", word: "Non" });
    expect(levelOf(null)).toMatchObject({ cls: "off", word: "—" });
  });

  it("dit pourquoi avec les mots du moteur, sans rien réécrire ; sa condition ; ce qu'elle garde", () => {
    expect(whyOf(cell("seule"))).toEqual({ why: "tout le monde, toujours", keep: "un savoir" });
    expect(whyOf(cell("non", { keep: "rien", why: "par défaut : personne" }))).toEqual({ why: "par défaut : personne", keep: "" });
    expect(whyOf(cell("non", { reason: "when", why: "En tête-à-tête." }))).toEqual({ why: "sa condition : En tête-à-tête.", keep: "" });
    // une boîte à ton nom : la phrase du moteur, une seule source
    const owned = "une boîte ou un compte à ton nom, ou qu'on te partage";
    expect(whyOf(cell("seule", { owned: true, keep: "perso", why: owned }))).toEqual({ why: owned, keep: "un souvenir" });
  });

  it("ne dit la ligne même qu'à une opératrice, avec la page de la console", () => {
    const t = tool("email_read", {}, { label: "Ouvrir un de tes mails" });
    const person = whyMarkup(t, cell("toi", { why: "toi, quand elle répond <b>" }), "Chat web", "quand elle te répond");
    expect(person).toContain("Pourquoi : toi, quand elle répond &lt;b&gt;");
    expect(person).toContain("Elle attend ton accord");
    expect(person).toContain("<b>Ouvrir un de tes mails</b>");
    expect(person).not.toContain("console");
    const operator = whyMarkup(t, cell("toi", { line: "ligne 2" }), "Chat web", "quand elle te répond", "http://h/inspecteur/reglages/droits?detail=famille%3Aemail");
    expect(operator).toContain('Dans la console : <a href="http://h/inspecteur/reglages/droits?detail=famille%3Aemail" target="_blank" rel="noopener">ligne 2</a>');
  });
});

describe("le nom d'un outil", () => {
  it("prend son libellé pour la personne ; un outil venu d'ailleurs, la première proposition de sa description", () => {
    const remind = { name: "goal_remind", label: "Te promettre un rappel", description: "Promettre un rappel à la personne à qui tu parles, à une heure dite." };
    expect(labelOf(remind)).toBe("Te promettre un rappel");
    expect(askFor(remind)).toBe("Tu peux te servir de « Te promettre un rappel » pour moi ?");
    expect(labelOf({ name: "mcp_x", label: "", description: "Liste ses factures. Pour un mois." })).toBe("Liste ses factures");
    expect(labelOf({ name: "mcp_y", label: "  ", description: "" })).toBe("mcp_y");
  });

  it("le repli coupe une description à sa première proposition", () => {
    expect(toolLabel("Renoncer à ce but (seulement ce que tu as entrepris).", "goal_drop")).toBe("Renoncer à ce but");
    expect(toolLabel("Tes boîtes aux lettres : leurs dossiers, ce qui n'est pas lu.", "x")).toBe("Tes boîtes aux lettres");
    expect(toolLabel("Ouvrir un mail de ta boîte.", "x")).toBe("Ouvrir un mail de ta boîte");
    expect(toolLabel("Conclure cette séance par un verdict. « done » n'est cru que…", "x")).toBe("Conclure cette séance par un verdict");
    expect(toolLabel("Lister les mails d'une boîte ou d'un dossier, du plus récent au plus ancien, page par page : leur date", "x")).toBe("Lister les mails d'une boîte ou d'un dossier");
    expect(toolLabel("Activer, arrêter, revenir à la version précédente (le code seulement)", "x")).toBe("Activer, arrêter, revenir à la version précédente");
    expect(toolLabel("", "forge_help")).toBe("forge_help");
  });

  it("la fiche montre le libellé, pas la consigne au modèle ; son nom de code n'est qu'ici", () => {
    const res = resourcesOf(RIGHTS);
    const email = res[0];
    const own = toolDetailMarkup(email, email.tools[0], RIGHTS);
    expect(own).not.toContain("email_read : ce qu"); // sa consigne au modèle (« email_read : ce qu'il fait. »)
    expect(own).toContain("<code>email_read</code>");
    const web = res.find((r) => r.key === "mcp:web")!;
    expect(toolDetailMarkup(web, web.tools[0], RIGHTS)).toContain("Search the web. Returns titles.");
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

  it("un compte ne recopie pas les outils de sa famille, et dit sa sorte ; ce qui est à elle seule se dit", () => {
    const owned = { words: new Map([["mail:pro", "à toi"], ["mcp:web", "un service de Mika"]]) };
    const res = resourcesOf(RIGHTS, owned);
    expect(res.map((r) => r.key)).toEqual(["famille:email", "famille:self", "courrier:pro", "mcp:web"]);
    const pro = res.find((r) => r.key === "courrier:pro")!;
    expect([pro.title, pro.navTitle]).toEqual(["Courrier · Boîte Pro", "Courrier · Boîte Pro"]);
    expect(pro.sub).toBe("a@b.test · à toi");
    expect(pro.tools).toEqual([]);
    expect(pro.family).toEqual({ key: "famille:email", title: "Courrier" });
    expect(res.find((r) => r.key === "famille:self")!.internal).toBe(true);
    expect(internalOnly(RIGHTS.groups[0].resources[0].tools!)).toBe(false);
    // un service de Mika ne dit que pour qui il est ; un service qu'une personne a branché, à quoi il sert, sous son titre
    expect(res.find((r) => r.key === "mcp:web")!.sub).toBe("un service de Mika");
    const meteo = { key: "mcp:meteo", title: "Service « meteo »", description: "La météo d'une ville.", tools: [] };
    const services = resourcesOf({ ...RIGHTS, groups: [{ key: "services", title: "Services", resources: [meteo] }] }, { words: new Map([["mcp:meteo", "ton service"]]) });
    expect(services[0].sub).toBe("La météo d'une ville. · ton service");
  });

  it("compte des outils, chacun une fois : seule s'il l'est sur le web ou l'app, sinon s'il te demande", () => {
    expect(countsOf(RIGHTS.groups[0].resources[0].tools!)).toEqual({ alone: 2, ask: 1 });
  });
});

describe("le balisage", () => {
  const cols = columns(RIGHTS.canals, RIGHTS.moments);
  const res = resourcesOf(RIGHTS);

  it("met un outil par ligne, nommé pour toi, une case par canal et moment ; les autres, repliés et nommés", () => {
    const html = tableMarkup(res[0], cols, "");
    expect((html.match(/<tr data-tool=/g) ?? []).length).toBe(3);
    expect((html.match(/class="mx-c"/g) ?? []).length).toBe(3 * 11);
    expect(html).toContain('data-cell="web/reply"');
    expect(html).toContain("<b>Ouvrir un de tes mails</b>");
    expect(html).not.toContain("<code>"); // ni nom de code sous un libellé, ni dans la liste repliée
    expect(html).toContain('<details class="mx-idle small muted"><summary>Un autre outil ne sert à aucun de ces moments</summary>');
    expect(html).toContain(">Renoncer à un but qu&#39;elle s&#39;était donné</button>");
    expect(idle(RIGHTS.groups[0].resources[0].tools![3])).toBe(true);
  });

  it("filtre par la recherche, et ne montre rien quand rien ne correspond", () => {
    expect(tableMarkup(res[0], cols, "ranger")).toContain('data-tool="email_tidy"');
    expect(tableMarkup(res[0], cols, "tidy")).not.toContain('data-tool="email_read"');
    expect(tableMarkup(res[0], cols, "introuvable")).toBe("");
  });

  it("sur un téléphone, ne garde lisible que le canal choisi", () => {
    const html = tableMarkup(res[0], cols, "", "web");
    expect((html.match(/class="mx-c"/g) ?? []).length).toBe(3 * 2);
    expect((html.match(/class="mx-c mx-other"/g) ?? []).length).toBe(3 * 9);
    expect(html).toContain('<th colspan="2" class="mx-canal">Chat web');
    expect(html).toContain('class="mx-canal mx-other">Un salon');
    expect(canalPickMarkup(RIGHTS.canals, "mobile")).toContain('<option value="mobile" selected>App Android</option>');
  });

  it("un compte : ce qui est à lui, le lien vers sa famille, la règle qui vaut, sans clé de canal", () => {
    const pro = res.find((r) => r.key === "courrier:pro")!;
    const html = tableMarkup(pro, cols, "");
    expect(html).not.toContain("<tr data-tool=");
    expect(html).toContain('Ses outils sont ceux de <button type="button" class="mx-link" data-res="famille:email">« Courrier »</button>, les mêmes pour toutes tes boîtes.');
    expect(html).toContain('href="#parametres/comptes-mail/pro"');
    const rules = rulesMarkup(RIGHTS.groups[1].resources[0].rules!, "mail");
    expect(rules).not.toContain("courrier:pro");
    expect(rules).toContain("pour cette boîte");
    expect(rules).toContain("Tout le monde");
    expect(rules).toContain("<b>Par défaut</b>");
    expect(rules).toContain("sa règle de départ");
    const common = rulesMarkup({ ...RIGHTS.groups[1].resources[0].rules!, common: true }, "teams");
    expect(common).toContain("la règle commune à tous tes comptes Teams");
    expect(common).toContain("pour ce compte");
  });

  it("le menu nomme la sorte d'un compte et compte des outils, « Tout » sans recompter les comptes", () => {
    const html = navMarkup(res, "courrier:pro");
    expect(html).toContain("Ses propres outils");
    expect(html).toContain("Tes comptes");
    expect(html).toContain('data-res="courrier:pro" class="on"');
    expect(html).toContain('<span class="ellipsis">Courrier · Boîte Pro</span>');
    // trois outils seule (deux du courrier, un du web), un qui te demande : rien de plus sous le compte
    expect(html).toContain('<span>Tout</span><span class="mx-mini" title="3 outils dont elle se sert seule, 1 outil pour lequel elle te demande, quand elle te répond sur le web ou l&#39;app Android"><i class="ok">3</i><i class="warn">1</i></span>');
    expect(html).not.toContain('<span class="ellipsis">Courrier · Boîte Pro</span>\n      <span class="mx-mini"'); // un compte : pas de chiffres à lui
    expect(html.indexOf("Les chiffres comptent ses outils")).toBeLessThan(html.indexOf("<span>Tout</span>"));
  });
});

describe("les services", () => {
  const res = resourcesOf(RIGHTS);

  it("montre aussi ce qu'on te partage, même quand aucune case ne t'en ouvre encore", () => {
    const rows = serviceRows(res, [OWN], [RECEIVED]);
    expect(rows.map((r) => r.key)).toEqual(["mcp:web", "mcp:factures", "mcp:meteo"]);
    const html = servicesMarkup(rows, "outils");
    expect(html).toContain("partagé avec toi par Adrien (s&#39;en servir)");
    expect(html).toContain("La météo d&#39;une ville.");
    expect(html).toContain("jamais joint");
    expect(html).toContain('href="#parametres/mcp/meteo">Voir</a>');
    // un service de Mika : pour qui, et « — » pour son but, que l'API ne rend pas
    expect(html).toContain('<td class="small">un service de Mika</td><td class="small text-2">—</td>');
  });

  it("dit « toi » par ce que dit l'API, jamais par un nom comparé", () => {
    const [web, own, shared] = serviceRows(res, [OWN], [RECEIVED]);
    expect(serviceWho(own)).toBe("toi, Léa Martin"); // deux lignes au même nom : seule `mine` les distingue
    expect(serviceWho(web)).toBe("toi");
    expect(serviceWho(shared)).toBe("toi");
  });
});
