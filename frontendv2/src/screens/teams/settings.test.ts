import { describe, expect, it } from "vitest";
import { EXTENSION_URL, type SendRules, type TeamsSettings } from "../../api/settings";
import type { Host } from "../../shared/settings";
import * as store from "../../shared/store";
import { teamsPage } from "./settings";

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

const TEAMS_SETTINGS: TeamsSettings = {
  account: "lea", values: { label: "", enabled: true, display_name: "", tone: "", instructions: "", sign: false, signature: "" },
  extension_key: null, rules: RULES,
};

describe("Teams : retirer un compte, régler comment ça part, des mots pour la personne (F4-04, F4-08)", () => {
  it("la fiche d'un compte offre « Retirer ce compte » et le tableau à régler, sans clé technique", () => {
    store.teamsAccounts.value = {
      plugged: true, enabled: true, extension: { version: "0.3.2" },
      accounts: [{ key: "lea", name: "lea", level: "proprietaire", enabled: true, last_batch: 0, self_name: "", extension_key: null, drafts_waiting: 0 }],
    };
    store.teamsSettings.get("lea").value = TEAMS_SETTINGS;
    const html = teamsPage.view("lea", HOST);
    expect(html).toContain('data-act="teams-remove"');
    expect(html).toContain('name="rule.1.reply"');
    expect(html).not.toContain("clé du compte");
    expect(html).not.toContain("par un opérateur");
  });

  it("l'extension se télécharge depuis la fiche quand le serveur l'a à côté de lui, sinon on dit à qui la demander", () => {
    store.teamsAccounts.value = {
      plugged: true, enabled: true, extension: { version: "0.3.2" },
      accounts: [{ key: "lea", name: "lea", level: "proprietaire", enabled: true, last_batch: 0, self_name: "", extension_key: null, drafts_waiting: 0 }],
    };
    store.teamsSettings.get("lea").value = TEAMS_SETTINGS;
    const html = teamsPage.view("lea", HOST);
    expect(html).toContain('href="' + EXTENSION_URL + '"');
    expect(html).toContain('download="mika-teams-0.3.2.zip"');
    expect(html).not.toContain("demande-la à ton opérateur");
    store.teamsAccounts.value = { ...store.teamsAccounts.value!, extension: null };
    const without = teamsPage.view("lea", HOST);
    expect(without).not.toContain(EXTENSION_URL);
    expect(without).toContain("demande-la à ton opérateur");
  });
});
