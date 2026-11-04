import { describe, expect, it } from "vitest";
import type { ServiceTool } from "../../api/mcp";
import { ago, Cached, dateWords, dayWords, remaining } from "./kit";
import { newBoxValues, boxChanges, providersFor } from "./mail";
import { splitChanges } from "./mcp";
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
});

describe("à qui partager", () => {
  it("une ressource « à toi » ne se partage pas à ses propriétaires (elle est déjà à elles)", () => {
    const people = [{ person: "user_2", name: "Léa", owner: false }, { person: "user_3", name: "Béa", owner: true }];
    expect(sharePeople({ common: true }, people).map((p) => p.person)).toEqual(["user_2"]);
    expect(sharePeople({ common: false }, people).map((p) => p.person)).toEqual(["user_2", "user_3"]);
    expect(sharePeople(undefined, people)).toHaveLength(2); // un service : à tout le monde
  });
});
