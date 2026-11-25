import { describe, expect, it } from "vitest";
import type { AccessLine, ReceivedService, Service, ServiceTool } from "../../api/mcp";
import type { Host } from "../../shared/settings";
import * as store from "../../shared/store";
import { openOf } from "../parametres/shares";
import { mcpPage, receivedFiche, receivedList, sharedWith, splitChanges, toolsTable, whoWords } from "./settings";
import { headersToRetype, HEADERS_TO_RETYPE, serviceNameProblem, servedOf, stateWords, urlOrigin, urlProblem } from "./words";

describe("les services MCP", () => {
  const t = (extra: Partial<ServiceTool>): ServiceTool => ({ remote: "x", name: "", description: "", choice: "", new: false, changed: false, ...extra });

  it("dit leur état et compte leurs outils servis", () => {
    expect(stateWords("connecte")).toEqual(["ok", "connecté"]);
    expect(stateWords("panne")).toEqual(["danger", "en panne"]);
    expect(servedOf([t({ choice: "lecture" }), t({ choice: "action" }), t({ choice: "non" }), t({ new: true })])).toEqual({ served: 2, total: 4, review: 1 });
  });

  it("vérifie un nom et une adresse avant de brancher", () => {
    expect(serviceNameProblem("agenda_club")).toBe("");
    expect(serviceNameProblem("Agenda")).not.toBe("");
    expect(serviceNameProblem("")).toBe("Un nom court.");
    expect(urlProblem("https://mcp.example.test/mcp")).toBe("");
    expect(urlProblem("http://mcp.example.test/mcp")).not.toBe("");
  });

  it("sépare les choix d'outils des réglages, sans en-têtes vides", () => {
    expect(splitChanges({ "tool:devis_list": "lecture", "tool:bad": "", purpose: "Devis", secret_headers: "" })).toEqual({
      choices: { devis_list: "lecture" }, values: { purpose: "Devis" },
    });
  });
  it("redemande ses en-têtes gardés quand l'adresse mène à un autre serveur (ADR 0236)", () => {
    const before = "https://agenda.exemple.fr/mcp";
    const ask = { secret_headers: HEADERS_TO_RETYPE };
    // un autre hôte, un autre port : à redonner ou à retirer, le serveur refuserait sinon
    expect(headersToRetype({ url: "https://autre.example/mcp", secret_headers: "" }, true, before)).toEqual(ask);
    expect(headersToRetype({ url: "https://agenda.exemple.fr:8443/mcp" }, true, before)).toEqual(ask);
    // redonnés, ou retirés : ils partent avec l'adresse, ou plus rien ne part
    expect(headersToRetype({ url: "https://autre.example/mcp", secret_headers: "Authorization: Bearer x" }, true, before)).toEqual({});
    expect(headersToRetype({ url: "https://autre.example/mcp", clear_headers: true }, true, before)).toEqual({});
    // le même serveur (un autre chemin, le port du schéma, des majuscules) ; aucun en-tête gardé ; l'adresse pas touchée
    expect(headersToRetype({ url: "https://AGENDA.exemple.fr:443/v2/mcp" }, true, before)).toEqual({});
    expect(headersToRetype({ url: "https://autre.example/mcp" }, false, before)).toEqual({});
    expect(headersToRetype({ purpose: "Agenda" }, true, before)).toEqual({});
    expect(urlOrigin("https://Agenda.exemple.fr/mcp")).toBe(urlOrigin("https://agenda.exemple.fr:443/x"));
  });
});

// ── Lot L14 : ce que l'API permet, Paramètres l'offre ───────────────

/** Un hôte de page sans écran : le sous-onglet par défaut, rien d'autre. */
const HOST = {
  sub: (_page: string, fallback: string) => fallback,
  setSub: () => undefined,
  repaint: () => undefined,
  reload: async () => undefined,
  go: () => undefined,
} as unknown as Host;

const line = (who: string, mine: boolean): AccessLine => ({
  who, when: "toujours", mine, read: "seule", act: "carte", keep: "prive",
  read_words: "seule", act_words: "demande à la personne", keep_words: "une confidence", tools: [],
});

const SERVICE: Service = {
  name: "factures", purpose: "Ses factures.", when_to_use: "", enabled: true, url: "https://mcp.example.test/mcp",
  headers: true, state: "connecte", detail: "",
  tools: [
    { remote: "lire", name: "mcp_factures_lire", description: "Lit une facture.", choice: "lecture", new: false, changed: false },
    { remote: "payer", name: "mcp_factures_payer", description: "Paie.", choice: "action", new: false, changed: true },
    { remote: "classer", name: "", description: "Classe.", choice: "", new: true, changed: false },
    { remote: "effacer", name: "mcp_factures_effacer", description: "Efface.", choice: "non", new: false, changed: false },
  ],
  access: [line("Léa Martin", true), line("Léa Martin", false)],
  default: null,
};

/** Le choix pressé d'un sélecteur (`seg`) de ce nom, dans un morceau de page ; `null` : aucun. */
function pressed(html: string, name: string): string | null {
  const at = html.indexOf(`data-seg="${name}"`);
  if (at < 0) throw new Error(`pas de sélecteur ${name}`);
  const group = html.slice(at, html.indexOf("</div>", at));
  return /data-v="([^"]*)" aria-pressed="true"/.exec(group)?.[1] ?? null;
}

describe("Services MCP : chaque outil se règle, ta ligne se dit par l'API (F4-02, F4-16)", () => {
  it("un outil déjà choisi a son sélecteur, sur son choix ; un nouveau ou un changé, sans choix fait", () => {
    const html = toolsTable(SERVICE);
    expect(pressed(html, "tool:lire")).toBe("lecture");
    expect(pressed(html, "tool:effacer")).toBe("non"); // coupé : se rouvre d'ici
    expect(pressed(html, "tool:payer")).toBeNull(); // changé : suspendu, à redécider (même comme avant)
    expect(pressed(html, "tool:classer")).toBeNull();
    expect(html).toContain("avant : il agit");
    expect(html).not.toContain("console");
  });

  it("n'envoie que les outils dont le choix a bougé", () => {
    // la barre d'enregistrement ne rend que ce qui a changé : un outil choisi qu'on coupe, un nouveau qu'on choisit
    expect(splitChanges({ "tool:lire": "non", "tool:classer": "lecture" }).choices).toEqual({ lire: "non", classer: "lecture" });
  });

  it("« toi » est ta ligne, pas ton nom : deux lignes au même nom restent distinctes", () => {
    expect(whoWords(SERVICE.access[0])).toBe("toi");
    expect(whoWords(SERVICE.access[1])).toBe("Léa Martin");
    expect(sharedWith(SERVICE)).toBe("Léa Martin");
  });
});

const RECEIVED: ReceivedService = {
  name: "agenda", purpose: "Les sorties du club.", enabled: true, state: "erreur", level: "servir",
  tools: [
    { remote: "lister", name: "mcp_agenda_lister", description: "Liste les sorties.", choice: "lecture" },
    { remote: "inscrire", name: "mcp_agenda_inscrire", description: "Inscrit.", choice: "action" },
  ],
  line: { ...line("Léa", true), read_words: "seule", act_words: "demande à la personne" },
  owner_name: "Adrien",
};

describe("Services MCP : ce qu'on te partage se voit (F4-03)", () => {
  it("une section « Partagé avec toi », en lecture, qui mène à sa fiche ; « Ouvrir » de Partages aussi", () => {
    const html = receivedList([RECEIVED]);
    expect(html).toContain("Partagé avec toi");
    expect(html).toContain("d&#39;Adrien"); // échappé
    expect(html).toContain("2 outils servis");
    expect(html).toContain('href="#parametres/mcp/agenda"');
    expect(openOf("mcp", "agenda")).toBe("#parametres/mcp/agenda");
    expect(receivedList([])).toBe("");
  });

  it("sa fiche dit ses outils servis et ce que Mika en fait pour toi, sans rien à régler", () => {
    const html = receivedFiche(RECEIVED);
    expect(html).toContain("Liste les sorties.");
    expect(html).toContain("demande à la personne"); // un outil qui agit : elle te demande d'abord
    expect(html).not.toContain("data-seg");
    expect(html).not.toContain("data-form");
  });

  it("la page le trouve parmi ceux qu'on te partage, et la liste le montre", () => {
    store.services.value = { plugged: true, items: [SERVICE], received: [RECEIVED] };
    expect(mcpPage.view("agenda", HOST)).toContain("Liste les sorties.");
    expect(mcpPage.view(null, HOST)).toContain("Partagé avec toi");
    expect(mcpPage.view("inconnu", HOST)).toContain("Service introuvable");
  });
});
