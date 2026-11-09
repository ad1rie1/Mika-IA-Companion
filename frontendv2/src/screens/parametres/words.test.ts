import { describe, expect, it } from "vitest";
import type { AccessLine, ReceivedService, Service, ServiceTool } from "../../api/mcp";
import { ApiError } from "../../api/moi";
import type { BoxSettings, SendRules, TeamsSettings } from "../../api/settings";
import { ASK_ME } from "./account";
import { ACTION_ROUTES, routeAction } from "./index";
import { ago, Cached, dateWords, dayWords, remaining } from "../../shared/kit";
import { newBoxValues, boxChanges, mailPage, providersFor } from "./mail";
import { mcpPage, receivedFiche, receivedList, sharedWith, splitChanges, toolsTable, whoWords } from "./mcp";
import type { Host } from "./page";
import { phonesPage, phonesView, pushWords } from "./phones";
import { openOf } from "./shares";
import * as store from "../../shared/store";
import { rulesEditor, ruleUpdate, sendChoices, teamsPage, withoutRule } from "./teams";
import {
  boxState,
  changed,
  fieldErrors,
  ofName,
  providerPreset,
  rangeProblems,
  secretsToRetype,
  sharePeople,
  securityFor,
  serviceNameProblem,
  servedOf,
  shareLevelsFor,
  sharePhrase,
  shareTarget,
  shareWords,
  stateWords,
  unseenOf,
  urlProblem,
} from "./words";

const NOW = new Date(2026, 10, 4, 15, 0).getTime();
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).getTime();

describe("les partages", () => {
  it("un service se partage pour lire ou s'en servir, une boîte aussi pour préparer", () => {
    expect(shareLevelsFor("mail").map(([k]) => k)).toEqual(["lire", "preparer", "servir"]);
    expect(shareLevelsFor("teams").map(([k]) => k)).toEqual(["lire", "preparer", "servir"]);
    expect(shareLevelsFor("mcp").map(([k]) => k)).toEqual(["lire", "servir"]);
  });

  it("en modification, le partage reste à sa personne et à sa ressource, même quand les listes ne les ont plus", () => {
    const people = [{ person: "user_3" }, { person: "user_4" }];
    const preset = { kind: "mail" as const, key: "pro", person: "user_2" };
    // les listes désactivées retombent sur leur premier choix : ce choix-là ne part jamais
    const t = shareTarget(preset, { kind: "teams", key: "autre", person: "user_3" }, people);
    expect(t).toEqual({ kind: "mail", key: "pro", person: "user_2", editing: true, gone: true });
    expect(shareTarget({ ...preset, person: "user_4" }, { kind: "mail", key: "pro", person: "user_3" }, people)).toMatchObject({ person: "user_4", gone: false });
    // un partage nouveau : ce qu'on a choisi
    expect(shareTarget({ kind: "mail", key: "pro" }, { kind: "mail", key: "pro", person: "user_3" }, people)).toEqual({
      kind: "mail", key: "pro", person: "user_3", editing: false, gone: false,
    });
  });

  it("élide devant une voyelle ou un h", () => {
    expect(ofName("Adrien")).toBe("d'Adrien");
    expect(ofName("Hélène")).toBe("d'Hélène");
    expect(ofName("Léa")).toBe("de Léa");
  });

  it("dit chaque niveau, et ce que la personne pourra", () => {
    expect(shareWords("lire")).toBe("Lire");
    expect(shareWords("preparer")).toBe("Lire et préparer");
    expect(shareWords("servir")).toBe("S'en servir");
    expect(shareWords("proprietaire")).toBe("Propriétaire");
    expect(sharePhrase("mail", "Rando Cassel", "Julien Roux", "lire")).toBe("Julien verra « Rando Cassel » dans son Mail, en lecture seule : ni répondre ni ranger.");
    expect(sharePhrase("mcp", "meteo", "Léa Moreau", "servir")).toContain("dans ses Outils");
    expect(sharePhrase("teams", "Pro", "Léa", "preparer")).toContain("que tu approuveras");
  });
});

describe("les boîtes", () => {
  it("dit son état", () => {
    expect(boxState({ enabled: false, ready: true, error: "" })).toEqual(["", "inactive"]);
    expect(boxState({ enabled: true, ready: false, error: "" })).toEqual(["warn", "incomplète"]);
    expect(boxState({ enabled: true, ready: true, error: "mot de passe refusé" })).toEqual(["danger", "erreur"]);
    expect(boxState({ enabled: true, ready: true, error: "" })).toEqual(["ok", "prête"]);
  });

  it("compte le non-lu de la réception seulement", () => {
    const folder = (name: string, role: string, unseen: number) => ({ name, label: name, role, polled: true, total: 9, unseen });
    expect(unseenOf({ folders: [folder("INBOX", "inbox", 3), folder("Archives", "archive", 5)] })).toBe(3);
  });

  it("préréglage un fournisseur, puis ce qui est tapé ; l'adresse sert d'utilisateur", () => {
    expect(providerPreset("gmail")).toMatchObject({ imap_host: "imap.gmail.com", smtp_host: "smtp.gmail.com", save_sent: false });
    const v = newBoxValues("gmail", { address: " lea@gmail.com ", label: "", user: "", password: "app", imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 465 });
    expect(v).toMatchObject({ auth: "password", address: "lea@gmail.com", label: "lea", user: "lea@gmail.com", password: "app", smtp_port: 465, smtp_security: "ssl" });
    const ms = newBoxValues("microsoft", { address: "a@outlook.fr", label: "Perso", oauth_client_id: " 0f1e2d3c-1111-2222-3333-444455556666 ", oauth_tenant: "" });
    expect(ms).toMatchObject({ auth: "microsoft", user: "a@outlook.fr", oauth_tenant: "consumers", oauth_client_id: "0f1e2d3c-1111-2222-3333-444455556666", imap_host: "outlook.office365.com" });
    expect(ms).not.toHaveProperty("password");
    expect(securityFor(1025, "none")).toBe("none");
  });

  it("une connexion qui change redemande ses secrets gardés (ils ne partent jamais vers un autre serveur)", () => {
    const kept = { password: true, smtp_password: true };
    expect(secretsToRetype({ imap_host: "imap.autre.test" }, kept, "password")).toEqual({ password: expect.stringContaining("à redonner") });
    expect(secretsToRetype({ smtp_port: 465 }, kept, "password")).toEqual({ smtp_password: expect.stringContaining("à redonner") });
    expect(Object.keys(secretsToRetype({ user: "moi", smtp_user: "moi" }, kept, "password"))).toEqual(["password", "smtp_password"]);
    // redonné, ou rien de gardé : rien à redemander
    expect(secretsToRetype({ imap_host: "imap.autre.test", password: "neuf" }, kept, "password")).toEqual({});
    expect(secretsToRetype({ imap_host: "imap.autre.test" }, { password: false, smtp_password: false }, "password")).toEqual({});
    // ce qui n'est pas la connexion (son nom, sa voix) ne redemande rien
    expect(secretsToRetype({ label: "Pro", voice: "elle" }, kept, "password")).toEqual({});
    // par Microsoft, la lecture n'a pas de mot de passe à redonner
    expect(secretsToRetype({ auth: "microsoft", oauth_client_id: "x" }, { password: true, smtp_password: false }, "microsoft")).toEqual({});
    // Microsoft : aucun mot de passe, même celui d'envoi gardé d'avant (ses champs sont cachés)
    expect(secretsToRetype({ smtp_host: "smtp-mail.outlook.com" }, kept, "microsoft")).toEqual({});
    // l'envoi sans mot de passe à lui se sert de celui de la lecture : changer son serveur le redemande
    const readOnly = { password: true, smtp_password: false };
    expect(secretsToRetype({ smtp_host: "smtp.autre.test" }, readOnly, "password")).toEqual({ smtp_password: expect.stringContaining("à redonner") });
    expect(secretsToRetype({ smtp_host: "smtp.autre.test", password: "redonne" }, readOnly, "password")).toEqual({});
    // retirer l'envoi (une boîte qui ne fait que lire) : rien ne part plus, rien à redonner
    expect(secretsToRetype({ smtp_host: "" }, readOnly, "password")).toEqual({});
    expect(secretsToRetype({ smtp_port: 465 }, kept, "password", { smtp_host: "" })).toEqual({});
  });

  it("la passerelle DavMail (sur la machine de Mika) n'est proposée qu'aux opérateurs", () => {
    expect(providersFor(false).map(([k]) => k)).not.toContain("davmail");
    expect(providersFor(true).map(([k]) => k)).toContain("davmail");
    // qui elle est n'est pas encore lu : tout, le serveur dira
    expect(providersFor(undefined).map(([k]) => k)).toContain("davmail");
  });

  it("n'envoie que ce qui a changé, sans secret vide, les nombres en nombres et les dossiers en liste", () => {
    expect(changed({ a: "x", b: true, f: ["INBOX"] }, { a: "x", b: false, f: ["INBOX", "Clients"] })).toEqual({ b: false, f: ["INBOX", "Clients"] });
    expect(boxChanges({ password: "", smtp_password: "neuf", imap_port: "1143", folders: "INBOX, Clients\nArchives", label: "Pro" })).toEqual({
      smtp_password: "neuf", imap_port: 1143, folders: ["INBOX", "Clients", "Archives"], label: "Pro",
    });
  });

  it("vérifie les bornes que le serveur laisse passer", () => {
    expect(rangeProblems({ imap_port: 0, smtp_port: 587, since_days: 90 })).toEqual({ imap_port: "un port entre 1 et 65535", since_days: "entre 1 et 60 jours" });
    expect(rangeProblems({ label: "Pro" })).toEqual({});
    expect(rangeProblems({ imap_port: "993" })).toEqual({});
  });

  it("range les refus d'un formulaire par champ", () => {
    expect(fieldErrors({ imap_port: "doit être un nombre entier", "accounts.pro.address": "adresse invalide" })).toEqual({
      imap_port: "doit être un nombre entier", address: "adresse invalide",
    });
  });
});

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
});

describe("les dates et la lecture gardée", () => {
  it("dit depuis quand, jusqu'à quand, et quel jour", () => {
    expect(ago(at(4, 14, 57), NOW)).toBe("il y a 3 min");
    expect(ago(at(4, 12, 0), NOW)).toBe("il y a 3 h");
    expect(ago(at(3, 22, 10), NOW)).toBe("hier à 22:10");
    expect(ago(at(1, 9, 0), NOW)).toBe("le 1 novembre");
    expect(ago(0, NOW)).toBe("");
    expect(remaining(at(4, 16, 52), NOW)).toBe("dans 1 h 52");
    expect(remaining(at(4, 15, 4), NOW)).toBe("dans 4 min");
    expect(remaining(at(4, 14, 0), NOW)).toBe("échue");
    expect(dayWords(at(2, 9, 0), NOW)).toBe("lundi 2 novembre");
    expect(dateWords(new Date(2025, 8, 2).getTime(), NOW)).toBe("2 septembre 2025");
  });

  it("ne relit qu'une fois à la fois, garde la valeur, et ne change de version que si elle change", async () => {
    let calls = 0;
    let value = { n: 1 };
    const c = new Cached(async () => {
      calls += 1;
      return value;
    }, 60_000);
    await Promise.all([c.load(), c.load()]);
    expect(calls).toBe(1);
    const v1 = c.version;
    await c.load(true);
    expect(c.version).toBe(v1);
    value = { n: 2 };
    await c.load(true);
    expect(c.version).toBe(v1 + 1);
    expect(c.value).toEqual({ n: 2 });
    const failing = new Cached<{ n: number }>(async () => {
      throw new Error("non");
    });
    await failing.load();
    expect(failing.settled).toBe(true);
    expect(failing.value).toBeNull();
  });

  it("une relecture forcée pendant une lecture en cours la suit : ce qu'on vient d'écrire se lit", async () => {
    let calls = 0;
    const c = new Cached(async () => ({ n: ++calls }), 60_000);
    const before = c.load(); // partie avant l'écriture
    const after = c.load(true); // demandée après l'écriture : une autre lecture, qui suit
    const again = c.load(true);
    expect(await before).toEqual({ n: 1 });
    expect(await after).toEqual({ n: 2 });
    expect(await again).toEqual({ n: 2 }); // une seule relecture pour les deux
    expect(calls).toBe(2);
    expect(c.value).toEqual({ n: 2 });
  });

  it("une relecture refusée garde la valeur d'avant, sauf un 404 : ce qui n'existe plus ne se montre plus", async () => {
    let fail: ApiError | null = null;
    const c = new Cached(async () => {
      if (fail) throw fail;
      return { n: 1 };
    }, 60_000);
    await c.load();
    fail = new ApiError(503, "Les itinéraires ne sont pas réglés.");
    await c.load(true);
    expect(c.value).toEqual({ n: 1 });
    expect(c.error).toBe(fail);
    const v = c.version;
    fail = new ApiError(404, "Introuvable.");
    await c.load(true);
    expect(c.value).toBeNull();
    expect(c.version).toBe(v + 1);
    fail = null;
    await c.load(true);
    expect(c.value).toEqual({ n: 1 });
    expect(c.error).toBeNull();
  });
});

describe("à qui partager", () => {
  it("une ressource « à toi » ne se partage pas à ses propriétaires (elle est déjà à elles)", () => {
    const people = [{ person: "user_2", name: "Léa", owner: false }, { person: "user_3", name: "Béa", owner: true }];
    expect(sharePeople({ common: true }, people).map((p) => p.person)).toEqual(["user_2"]);
    expect(sharePeople({ common: false }, people).map((p) => p.person)).toEqual(["user_2", "user_3"]);
    expect(sharePeople(undefined, people)).toHaveLength(2); // un service : à tout le monde
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

const RULES: SendRules = {
  canal: "teams:lea", set: false, common: false, version: "v1",
  lines: [{ who: "Marc", when: "toujours", prepare: true, reply: "brouillon", reply_words: "brouillon — c'est toi qui l'envoies" }],
  default: { who: "—", when: "toujours", prepare: false, reply: "accord", reply_words: "ton accord" },
};

describe("Comment ça part : la propriétaire règle sa règle d'envoi (Q22, F4-11)", () => {
  it("chaque ligne et le défaut ont « préparer » et « comment ça part » ; le courrier n'offre pas de brouillon", () => {
    const html = rulesEditor(RULES, "teams");
    expect(pressed(html, "rule.1.prepare")).toBe("oui");
    expect(pressed(html, "rule.d.prepare")).toBe("non");
    expect(html).toContain('name="rule.1.reply"');
    expect(html).toContain('href="#outils/droits/teams%3Alea"'); // ses outils, dans la matrice
    expect(html).not.toContain("teams:lea"); // pas de clé de canal dans le texte
    expect(sendChoices("mail", "accord").map(([k]) => k)).toEqual(["accord", "seule", "non"]);
    expect(sendChoices("mail", "brouillon").map(([k]) => k)).toContain("brouillon"); // une ligne qui l'a déjà
    expect(sendChoices("teams", "accord").map(([k]) => k)).toContain("brouillon");
  });

  it("la règle part à part, entière, avec l'empreinte de celle qu'on a lue", () => {
    const { rule, rest } = withoutRule({ label: "Pro", "rule.1.reply": "seule" });
    expect(rule).toBe(true);
    expect(rest).toEqual({ label: "Pro" });
    expect(withoutRule({ label: "Pro" }).rule).toBe(false);
    expect(ruleUpdate(RULES, { "rule.1.prepare": "non", "rule.1.reply": "seule", "rule.d.prepare": "oui", "rule.d.reply": "accord" })).toEqual({
      canal: "teams:lea", version: "v1", lines: [{ prepare: false, reply: "seule" }], default: { prepare: true, reply: "accord" },
    });
    // une case absente du formulaire garde sa valeur
    expect(ruleUpdate(RULES, {}).lines).toEqual([{ prepare: true, reply: "brouillon" }]);
  });
});

const TEAMS_SETTINGS: TeamsSettings = {
  account: "lea", values: { label: "", enabled: true, display_name: "", tone: "", instructions: "", sign: false, signature: "" },
  extension_key: null, rules: RULES,
};

describe("Teams : retirer un compte, régler comment ça part, des mots pour la personne (F4-04, F4-08)", () => {
  it("la fiche d'un compte offre « Retirer ce compte » et le tableau à régler, sans clé technique", () => {
    store.teamsAccounts.value = {
      plugged: true, enabled: true,
      accounts: [{ key: "lea", name: "lea", level: "proprietaire", enabled: true, last_batch: 0, self_name: "", extension_key: null, drafts_waiting: 0 }],
    };
    store.teamsSettings.get("lea").value = TEAMS_SETTINGS;
    const html = teamsPage.view("lea", HOST);
    expect(html).toContain('data-act="teams-remove"');
    expect(html).toContain('name="rule.1.reply"');
    expect(html).not.toContain("clé du compte");
    expect(html).not.toContain("par un opérateur");
  });
});

const BOX_SETTINGS = {
  box: "pro", values: { ...newBoxValues("gmail", { address: "lea@example.test" }), enabled: true, folders: ["INBOX"], sync_all: false, since_days: 7, voice: "elle", display_name: "", sender_name: "", tone: "", instructions: "", signature: "", save_sent: true, auth: "password", oauth_client_id: "", oauth_tenant: "", smtp_user: "", imap_ssl: true },
  secrets: { password: true, smtp_password: false }, ready: true, can_send: true, microsoft: false, signin: null,
  rules: { ...RULES, canal: "courrier:pro", lines: [{ ...RULES.lines[0], reply: "accord", reply_words: "ton accord" }] },
} as unknown as BoxSettings;

describe("Comptes mail : la règle d'envoi dans la boîte, comme dans Teams (F4-11)", () => {
  it("la fiche d'une boîte a son tableau à régler, et plus un simple lien", () => {
    store.boxes.value = {
      plugged: true, read_on_open: "",
      boxes: [{ key: "pro", name: "Pro", address: "lea@example.test", level: "proprietaire", ready: true, can_send: true, enabled: true, signature: "", last_poll: 0, error: "", drafts_waiting: 0, folders: [] }],
    };
    store.boxSettings.get("pro").value = BOX_SETTINGS;
    const html = mailPage.view("pro", { ...HOST, sub: () => "mika" } as unknown as Host);
    expect(html).toContain('name="rule.1.reply"');
    expect(html).not.toContain("La voir dans Outils");
    expect(html).toContain('href="#outils/droits/courrier%3Apro"');
    expect(html).not.toContain('value="brouillon"'); // le courrier n'en a pas
  });
});

describe("Téléphones et Compte : un bouton par geste, des mots sans code (F4-15, F4-08)", () => {
  it("« Télécharger l'APK » une seule fois, sur la carte ; ni ADR, ni « notifié fermé »", () => {
    const html = phonesView(true, [{ id: 1, label: "Pixel", push: true, revoked: false, created_at: 0, last_used: 0 }] as never, NOW);
    expect(html.split("Télécharger l'APK").length - 1).toBe(1);
    expect(phonesPage.actions).toBeUndefined();
    expect(html).not.toMatch(/ADR|notifié fermé/);
    expect(pushWords(true)).toBe("même application fermée");
    expect(pushWords(false)).toBe("sans notifications");
  });

  it("une route d'action ouvre la fenêtre que son bouton promet ; un objet ordinaire n'en est pas une", () => {
    expect(routeAction("mcp", "+brancher")).toEqual({ act: "mcp-plug" });
    expect(routeAction("compte", "+mot-de-passe")).toEqual({ act: "password", sub: "securite" });
    expect(routeAction("partages", "+partager")).toEqual({ act: "share-new" });
    expect(routeAction("mcp", "factures")).toBeNull();
    expect(routeAction("mcp", "+inconnu")).toBeNull();
    expect(Object.keys(ACTION_ROUTES).sort()).toEqual(["compte", "mcp", "partages"]);
    expect(ASK_ME).toBe("Qu'est-ce que tu sais de moi ?");
  });
});
