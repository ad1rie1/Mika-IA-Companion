import { describe, it, expect } from "vitest";
import { EMOJI_GROUPS, insertEmoji, MAX_RECENT, parseRecent, withRecent } from "../emojis";

const ALL = EMOJI_GROUPS.flatMap((g) => g.emojis);

describe("emojis — les familles", () => {
  it("chaque famille a un onglet, un nom et des emojis, sans case vide ni doublon", () => {
    for (const g of EMOJI_GROUPS) {
      expect(g.icon).not.toBe("");
      expect(g.label).not.toBe("");
      expect(g.emojis.length).toBeGreaterThan(0);
      for (const e of g.emojis) expect(e).toMatch(/^\S+$/);
    }
    expect(new Set(ALL).size).toBe(ALL.length);
  });

  it("un emoji composé reste entier (pas coupé à la jointure)", () => {
    expect(ALL).toContain("❤️‍🔥");
    expect(ALL).toContain("😮‍💨");
    expect(ALL).not.toContain("‍");
  });
});

describe("emojis — l'insertion au curseur", () => {
  it("pose l'emoji au curseur et place le curseur juste après", () => {
    expect(insertEmoji("salut toi", 5, 5, "👋", 100)).toEqual({ value: "salut👋 toi", caret: 7 });
    expect(insertEmoji("", 0, 0, "😊", 100)).toEqual({ value: "😊", caret: 2 });
  });

  it("remplace la sélection, dans un sens comme dans l'autre", () => {
    expect(insertEmoji("j'adore ça", 2, 7, "❤️", 100)).toEqual({ value: "j'❤️ ça", caret: 4 });
    expect(insertEmoji("j'adore ça", 7, 2, "❤️", 100)?.value).toBe("j'❤️ ça");
  });

  it("borne un curseur hors du texte", () => {
    expect(insertEmoji("abc", 10, 12, "✨", 100)).toEqual({ value: "abc✨", caret: 4 });
    expect(insertEmoji("abc", -3, -1, "✨", 100)).toEqual({ value: "✨abc", caret: 1 });
  });

  it("refuse ce qui dépasserait la limite du champ, comptée comme lui (UTF-16)", () => {
    expect(insertEmoji("a".repeat(9), 9, 9, "😊", 10)).toBeNull();
    expect(insertEmoji("a".repeat(8), 8, 8, "😊", 10)?.value.length).toBe(10);
    // une sélection remplacée libère sa place
    expect(insertEmoji("a".repeat(10), 0, 2, "😊", 10)?.value.length).toBe(10);
  });
});

describe("emojis — les récents", () => {
  it("le dernier choisi en tête, sans doublon, borné", () => {
    expect(withRecent(["😊", "👍"], "👍")).toEqual(["👍", "😊"]);
    const many = ALL.slice(0, MAX_RECENT);
    const next = withRecent(many, ALL[MAX_RECENT]);
    expect(next).toHaveLength(MAX_RECENT);
    expect(next[0]).toBe(ALL[MAX_RECENT]);
    expect(next).not.toContain(many[MAX_RECENT - 1]);
  });

  it("relit le stockage sans jamais casser : rien, du JSON cassé, un intrus", () => {
    expect(parseRecent(null)).toEqual([]);
    expect(parseRecent("")).toEqual([]);
    expect(parseRecent("{pas du json")).toEqual([]);
    expect(parseRecent('{"a": 1}')).toEqual([]);
    expect(parseRecent('["😊", 3, "<script>", "😊", "👍"]')).toEqual(["😊", "👍"]);
    expect(parseRecent(JSON.stringify(ALL))).toHaveLength(MAX_RECENT);
  });
});
