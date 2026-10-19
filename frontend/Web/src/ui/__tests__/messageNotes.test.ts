import { describe, expect, it } from "vitest";
import { MAX_NOTE_CHARS, MAX_NOTES, messageNotes, noteLine, sameNotes } from "../messageNotes";

/** Une heure locale du navigateur : les tests ne dépendent pas du fuseau. */
const at = (day: number, hours: number, minutes: number, seconds = 0) =>
  new Date(2026, 9, day, hours, minutes, seconds).getTime();

const LYON = "Rue de la République, Lyon";

describe("messageNotes — la validation", () => {
  it("garde les regards sur la position, tels que le serveur les envoie", () => {
    expect(messageNotes([{ kind: "location", text: LYON, at: 1_790_601_490_000 }])).toEqual([
      { kind: "location", text: LYON, at: 1_790_601_490_000 },
    ]);
  });

  it("ignore une sorte inconnue et ce qui n'est pas une bulle", () => {
    expect(
      messageNotes([null, "x", 3, [], { kind: "weather", text: "pluie", at: 1 }, { text: LYON, at: 1 }, { kind: "location", text: LYON, at: 5 }])
    ).toEqual([{ kind: "location", text: LYON, at: 5 }]);
  });

  it("une liste illisible vaut une liste vide", () => {
    for (const raw of [undefined, null, "notes", 12, { kind: "location" }]) expect(messageNotes(raw)).toEqual([]);
  });

  it("un lieu illisible est vide, une heure illisible vaut 0 : elle a quand même regardé", () => {
    expect(messageNotes([{ kind: "location", text: 42, at: "hier" }])).toEqual([{ kind: "location", text: "", at: 0 }]);
    expect(messageNotes([{ kind: "location", at: -5 }, { kind: "location", text: "a", at: Number.NaN }])).toEqual([
      { kind: "location", text: "", at: 0 },
      { kind: "location", text: "a", at: 0 },
    ]);
  });

  it("met le lieu sur une ligne et le borne", () => {
    expect(messageNotes([{ kind: "location", text: "  Rue\nde la\tRépublique  ", at: 1 }])[0].text).toBe(
      "Rue de la République"
    );
    expect(messageNotes([{ kind: "location", text: "x".repeat(5000), at: 1 }])[0].text).toHaveLength(MAX_NOTE_CHARS);
  });

  it("une bulle redite à l'identique ne compte qu'une fois ; le nombre est borné", () => {
    const same = { kind: "location", text: LYON, at: 7 };
    expect(messageNotes([same, { ...same }, { ...same, at: 8 }])).toHaveLength(2);
    const many = Array.from({ length: 50 }, (_, i) => ({ kind: "location", text: LYON, at: i + 1 }));
    expect(messageNotes(many)).toHaveLength(MAX_NOTES);
  });

  it("sameNotes compare sorte, lieu et instant", () => {
    const a = [{ kind: "location", text: LYON, at: 1 }];
    expect(sameNotes(a, [{ ...a[0] }])).toBe(true);
    expect(sameNotes(a, [{ ...a[0], text: "" }])).toBe(false);
    expect(sameNotes(undefined, [])).toBe(true);
    expect(sameNotes(a, undefined)).toBe(false);
  });
});

describe("noteLine — le texte de la bulle", () => {
  const note = (text: string, fix: number) => ({ kind: "location", text, at: fix });

  it("une position du moment : le lieu, sans heure", () => {
    expect(noteLine(note(LYON, at(19, 14, 9)), at(19, 14, 10, 30))).toBe(`📍 Mika a regardé où tu es · ${LYON}`);
  });

  it("une position plus ancienne de 2 min ou plus dit son heure", () => {
    expect(noteLine(note(LYON, at(19, 14, 10)), at(19, 14, 12))).toBe(
      `📍 Mika a regardé où tu es · ${LYON} · position de 14:10`
    );
    expect(noteLine(note(LYON, at(19, 9, 5)), at(19, 18, 0))).toBe(
      `📍 Mika a regardé où tu es · ${LYON} · position de 09:05`
    );
  });

  it("une position d'un autre jour que son message dit aussi la date", () => {
    expect(noteLine(note(LYON, at(18, 23, 50)), at(19, 0, 20))).toBe(
      `📍 Mika a regardé où tu es · ${LYON} · position du 18/10 à 23:50`
    );
  });

  it("un lieu oublié (vide) : la bulle n'a pas de lieu", () => {
    expect(noteLine(note("", at(19, 14, 10)), at(19, 14, 10))).toBe("📍 Mika a regardé où tu es");
    expect(noteLine(note("  ", at(19, 8, 0)), at(19, 14, 10))).toBe("📍 Mika a regardé où tu es · position de 08:00");
  });

  it("sans instant de mesure, ou une mesure « après » son message (horloges), pas d'heure", () => {
    expect(noteLine(note(LYON, 0), at(19, 14, 10))).toBe(`📍 Mika a regardé où tu es · ${LYON}`);
    expect(noteLine(note(LYON, at(19, 14, 30)), at(19, 14, 10))).toBe(`📍 Mika a regardé où tu es · ${LYON}`);
  });

  it("un message sans heure lisible : l'heure de la mesure, sans comparaison", () => {
    expect(noteLine(note(LYON, at(19, 14, 10)), Number.NaN)).toBe(
      `📍 Mika a regardé où tu es · ${LYON} · position de 14:10`
    );
  });
});
