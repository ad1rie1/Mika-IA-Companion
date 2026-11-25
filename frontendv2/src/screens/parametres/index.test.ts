import { describe, expect, it } from "vitest";
import { ASK_ME } from "./account";
import { ACTION_ROUTES, routeAction } from "./index";

describe("Téléphones et Compte : un bouton par geste, des mots sans code (F4-15, F4-08)", () => {
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
