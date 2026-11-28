import { describe, expect, it } from "vitest";
import { excerpt, filterPalette, GO_TO, type PaletteEntry } from "./palette";

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

describe("un message, cherché dans tout son texte", () => {
  // un message long : le mot cherché est bien au-delà de ce que le titre en montre
  const long =
    "Je te fais le point sur la semaine, parce qu'il s'est passé pas mal de choses à l'atelier depuis lundi. " +
    "Le devis de la papeterie expire le 20 novembre,\net l'imprimerie attend un bon pour accord signé avant jeudi.";
  const message: PaletteEntry = { group: "Conversation", title: `${long.slice(0, 69)}…`, sub: "Mika · hier 14:05", text: long };

  it("trouve un mot loin du début, sans accents ni casse, et montre le passage trouvé", () => {
    const [hit] = filterPalette([message], "IMPRIMERIE attend");
    expect(hit.title).toContain("imprimerie attend un bon");
    expect(hit.title.startsWith("…")).toBe(true);
    expect(hit.title.length).toBeLessThanOrEqual(72);
    // l'entrée d'origine ne change pas, son action non plus
    expect(message.title.startsWith("Je te fais le point")).toBe(true);
    expect(filterPalette([message], "papeterie expire")).toHaveLength(1);
    expect(filterPalette([message], "pas dans le message")).toEqual([]);
  });

  it("trouvé dans le titre, le titre reste", () => {
    expect(filterPalette([message], "point sur")[0].title).toBe(message.title);
  });

  it("des messages qui se ressemblent ne cachent pas le reste : dix par groupe au plus", () => {
    const many = Array.from({ length: 30 }, (_, i): PaletteEntry => ({ group: "Conversation", title: `le devis ${i}`, text: `le devis ${i}` }));
    const mail: PaletteEntry = { group: "Mails", title: "Votre devis", route: "#mail/messages/m1" };
    const out = filterPalette([...many, mail], "devis");
    expect(out.filter((e) => e.group === "Conversation")).toHaveLength(10);
    expect(out[out.length - 1].title).toBe("Votre devis");
  });
});

describe("excerpt", () => {
  const text = "Un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize dix-sept dix-huit dix-neuf vingt.";

  it("coupe entre deux mots, « … » de chaque côté", () => {
    const out = excerpt(text, "quatorze");
    expect(out).toMatch(/^…[^ ].*[^ ]…$/);
    const inner = out.slice(1, -1);
    const at = text.indexOf(inner);
    expect(inner).toContain("quatorze");
    // un passage d'un seul tenant, coupé à des espaces
    expect(at).toBeGreaterThan(0);
    expect(text[at - 1]).toBe(" ");
    expect(text[at + inner.length]).toBe(" ");
  });

  it("au début, pas de « … » devant ; trouvé avec ses accents", () => {
    expect(excerpt("Écrire à Mika", "ecrire")).toBe("Écrire à Mika");
    expect(excerpt(text, "un deux").startsWith("Un deux")).toBe(true);
  });

  it("pas trouvé : le début du texte", () => {
    expect(excerpt(text, "absent")).toBe(`${text.slice(0, 69).trimEnd()}…`);
  });
});
