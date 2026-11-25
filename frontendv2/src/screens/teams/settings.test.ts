import { describe, expect, it } from "vitest";
import { EXTENSION_URL, type SendRules, type TeamsSettings } from "../../api/settings";
import type { Host } from "../../shared/settings";
import * as store from "../../shared/store";
import { rulesEditor, ruleUpdate, sendChoices, teamsPage, withoutRule } from "./settings";

// ── Lot L14 : ce que l'API permet, Paramètres l'offre ───────────────

/** Un hôte de page sans écran : le sous-onglet par défaut, rien d'autre. */
const HOST = {
  sub: (_page: string, fallback: string) => fallback,
  setSub: () => undefined,
  repaint: () => undefined,
  reload: async () => undefined,
  go: () => undefined,
} as unknown as Host;

/** Le choix pressé d'un sélecteur (`seg`) de ce nom, dans un morceau de page ; `null` : aucun. */
function pressed(html: string, name: string): string | null {
  const at = html.indexOf(`data-seg="${name}"`);
  if (at < 0) throw new Error(`pas de sélecteur ${name}`);
  const group = html.slice(at, html.indexOf("</div>", at));
  return /data-v="([^"]*)" aria-pressed="true"/.exec(group)?.[1] ?? null;
}

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
