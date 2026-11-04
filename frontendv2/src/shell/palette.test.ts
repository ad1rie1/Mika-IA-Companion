import { describe, expect, it } from "vitest";
import { filterPalette, GO_TO, type PaletteEntry } from "./palette";

const entries: PaletteEntry[] = [
  { group: GO_TO, title: "Chat", route: "#chat" },
  { group: GO_TO, title: "Mail", route: "#mail" },
  { group: GO_TO, title: "Mail › Contacts", route: "#mail/contacts" },
  { group: GO_TO, title: "Paramètres", route: "#parametres" },
  { group: GO_TO, title: "Paramètres › Téléphones", route: "#parametres/telephones" },
  ...Array.from({ length: 8 }, (_, i): PaletteEntry => ({ group: "Conversation", title: `message ${i}`, sub: "Toi · 14:05" })),
  { group: "Fils de travail", title: "Devis Lefèvre", sub: "Comparer le devis au budget" },
];

describe("filterPalette", () => {
  it("sans rien de tapé : les écrans, puis quelques entrées des écrans", () => {
    const out = filterPalette(entries, "  ");
    expect(out.slice(0, 3).map((e) => e.title)).toEqual(["Chat", "Mail", "Paramètres"]);
    expect(out.filter((e) => e.group !== GO_TO)).toHaveLength(6);
  });

  it("sans accents ni casse, sur le titre, le détail et le groupe", () => {
    expect(filterPalette(entries, "telephone").map((e) => e.title)).toEqual(["Paramètres › Téléphones"]);
    expect(filterPalette(entries, "LEFEVRE").map((e) => e.title)).toEqual(["Devis Lefèvre"]);
    expect(filterPalette(entries, "budget").map((e) => e.title)).toEqual(["Devis Lefèvre"]);
    expect(filterPalette(entries, "fils de").map((e) => e.title)).toEqual(["Devis Lefèvre"]);
    expect(filterPalette(entries, "introuvable")).toEqual([]);
  });
});
