import { describe, expect, it } from "vitest";
import type { BoxSettings, SendRules } from "../../api/settings";
import { changed, fieldErrors, type Host } from "../../shared/settings";
import * as store from "../../shared/store";
import { boxChanges, mailPage, newBoxValues, providersFor } from "./settings";
import { boxState, providerPreset, rangeProblems, secretsToRetype, securityFor, unseenOf } from "./words";

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

// ── Lot L14 : ce que l'API permet, Paramètres l'offre ───────────────

/** Un hôte de page sans écran : le sous-onglet par défaut, rien d'autre. */
const HOST = {
  sub: (_page: string, fallback: string) => fallback,
  setSub: () => undefined,
  repaint: () => undefined,
  reload: async () => undefined,
  go: () => undefined,
} as unknown as Host;

const RULES: SendRules = {
  canal: "teams:lea", set: false, common: false, version: "v1",
  lines: [{ who: "Marc", when: "toujours", prepare: true, reply: "brouillon", reply_words: "brouillon — c'est toi qui l'envoies" }],
  default: { who: "—", when: "toujours", prepare: false, reply: "accord", reply_words: "ton accord" },
};

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
