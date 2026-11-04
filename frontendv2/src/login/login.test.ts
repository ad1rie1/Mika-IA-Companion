import { describe, expect, it } from "vitest";
import { loginProblem } from "./login";

describe("loginProblem", () => {
  it("demande le nom et le mot de passe", () => {
    expect(loginProblem("login", false, { username: " ", password: "x", code: "" })).toBe("Nom d'utilisateur et mot de passe requis.");
    expect(loginProblem("login", false, { username: "adrien", password: "", code: "" })).toBe("Nom d'utilisateur et mot de passe requis.");
    expect(loginProblem("login", false, { username: "adrien", password: "secret", code: "" })).toBeNull();
  });

  it("le premier compte demande le code quand le serveur l'exige", () => {
    const f = { username: "adrien", password: "un long mot de passe", code: "" };
    expect(loginProblem("bootstrap", true, f)).toBe("Le code de premier démarrage est dans le journal du serveur.");
    expect(loginProblem("bootstrap", false, f)).toBeNull();
    expect(loginProblem("bootstrap", true, { ...f, code: "123456" })).toBeNull();
    // le code ne compte pas pour une connexion ordinaire
    expect(loginProblem("login", true, f)).toBeNull();
  });
});
