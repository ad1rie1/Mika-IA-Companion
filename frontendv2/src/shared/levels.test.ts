import { describe, expect, it } from "vitest";
import { caps } from "./levels";

describe("ce qu'un niveau ouvre (ADR 0188)", () => {
  it("la sienne : tout, décider compris", () => {
    expect(caps("proprietaire")).toEqual({ own: true, write: true, prepare: true, decide: true });
  });
  it("s'en servir : écrire et ranger, jamais décider de ses brouillons", () => {
    expect(caps("servir")).toEqual({ own: false, write: true, prepare: true, decide: false });
  });
  it("préparer : seulement « Préremplir »", () => {
    expect(caps("preparer")).toEqual({ own: false, write: false, prepare: true, decide: false });
  });
  it("lire, ou un niveau inconnu : rien d'autre que lire", () => {
    expect(caps("lire")).toEqual({ own: false, write: false, prepare: false, decide: false });
    expect(caps("autre")).toEqual({ own: false, write: false, prepare: false, decide: false });
  });
});
