import { describe, expect, it } from "vitest";
import { sharePeople, shareLevelsFor, sharePhrase, shareTarget, shareWords } from "./sharing";

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

describe("à qui partager", () => {
  it("une ressource « à toi » ne se partage pas à ses propriétaires (elle est déjà à elles)", () => {
    const people = [{ person: "user_2", name: "Léa", owner: false }, { person: "user_3", name: "Béa", owner: true }];
    expect(sharePeople({ common: true }, people).map((p) => p.person)).toEqual(["user_2"]);
    expect(sharePeople({ common: false }, people).map((p) => p.person)).toEqual(["user_2", "user_3"]);
    expect(sharePeople(undefined, people)).toHaveLength(2); // un service : à tout le monde
  });
});
