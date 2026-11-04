import { describe, expect, it } from "vitest";
import { parseRoute, routeHash, type ScreenShape } from "./router";

const screens = new Map<string, ScreenShape>([
  ["chat", { tabs: [] }],
  ["mail", { tabs: [{ id: "messages" }, { id: "contacts" }] }],
  ["parametres", { tabs: [{ id: "compte" }, { id: "mcp" }], defaultTab: "compte" }],
  ["outils", { tabs: [{ id: "droits" }, { id: "services" }], defaultTab: "services" }],
]);

describe("parseRoute", () => {
  it("mène au chat sans route, ou pour un écran inconnu", () => {
    expect(parseRoute("", screens)).toEqual({ screen: "chat", tab: null, item: null });
    expect(parseRoute("#", screens)).toEqual({ screen: "chat", tab: null, item: null });
    expect(parseRoute("#nulle-part/x/y", screens)).toEqual({ screen: "chat", tab: null, item: null });
  });

  it("ouvre l'onglet par défaut, sinon le premier", () => {
    expect(parseRoute("#mail", screens)).toEqual({ screen: "mail", tab: "messages", item: null });
    expect(parseRoute("#outils", screens)).toEqual({ screen: "outils", tab: "services", item: null });
    expect(parseRoute("#mail/inconnu", screens)).toEqual({ screen: "mail", tab: "messages", item: null });
  });

  it("garde l'objet ouvert, barres comprises", () => {
    expect(parseRoute("#mail/messages/m-claire", screens)).toEqual({ screen: "mail", tab: "messages", item: "m-claire" });
    expect(parseRoute("#parametres/mcp/factures/outils", screens)).toEqual({
      screen: "parametres",
      tab: "mcp",
      item: "factures/outils",
    });
  });

  it("un écran sans onglets prend tout ce qui suit comme objet", () => {
    expect(parseRoute("#chat/s1abc", screens)).toEqual({ screen: "chat", tab: null, item: "s1abc" });
  });

  it("décode la route, et survit à un encodage illisible", () => {
    expect(parseRoute("#mail/messages/caf%C3%A9", screens).item).toBe("café");
    expect(parseRoute("#mail/messages/%E0%A4%A", screens)).toEqual({ screen: "mail", tab: "messages", item: "%E0%A4%A" });
  });

  it("décode chaque segment à part : l'objet garde ses barres encodées et ses segments vides", () => {
    // une référence de mail `boîte:Message-ID` dont l'identifiant porte « // » (encodée par encodeURIComponent)
    const ref = "pro:<ab//cd@x>";
    expect(parseRoute(`#mail/messages/${encodeURIComponent(ref)}`, screens).item).toBe(ref);
    expect(parseRoute(`#mail/messages/${encodeURIComponent("pro:<fin/>")}`, screens).item).toBe("pro:<fin/>");
    // non encodée : les segments vides et la barre finale restent dans l'objet
    expect(parseRoute("#mail/messages/a//b", screens).item).toBe("a//b");
    expect(parseRoute("#mail/messages/a/", screens).item).toBe("a/");
    // un segment illisible n'empêche pas de décoder les autres
    expect(parseRoute("#mail/messages/caf%C3%A9/%E0%A4%A", screens).item).toBe("café/%E0%A4%A");
    // un brouillon : « brouillon/<id> », l'identifiant décodé seul
    expect(parseRoute(`#mail/messages/brouillon/${encodeURIComponent("d/1")}`, screens).item).toBe("brouillon/d/1");
  });

  it("les segments vides ne comptent pas avant l'objet ; une barre finale seule n'est pas un objet", () => {
    expect(parseRoute("#/mail//contacts/x", screens)).toEqual({ screen: "mail", tab: "contacts", item: "x" });
    expect(parseRoute("#mail/messages/", screens)).toEqual({ screen: "mail", tab: "messages", item: null });
    expect(parseRoute("#chat/", screens)).toEqual({ screen: "chat", tab: null, item: null });
    expect(parseRoute("#chat/s1//x", screens)).toEqual({ screen: "chat", tab: null, item: "s1//x" });
    // une barre encodée ne sépare pas l'écran de l'onglet
    expect(parseRoute("#mail%2Fcontacts", screens).screen).toBe("chat");
  });
});

describe("routeHash", () => {
  it("compose une adresse sans segment vide", () => {
    expect(routeHash("mail", "messages", "m3")).toBe("#mail/messages/m3");
    expect(routeHash("chat")).toBe("#chat");
    expect(routeHash("mail", null, null)).toBe("#mail");
  });
});
