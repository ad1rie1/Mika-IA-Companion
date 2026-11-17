import { describe, expect, it } from "vitest";
import { AVOIDS } from "../api/carte";
import { AVOID_LABELS, avoidWords, dayLabel, duration, isoDay, isoOf, km, modeWords, placeWhat, plural, tripDates, tripPast, tripSpan } from "./words";

const NOW = new Date(2026, 10, 5, 14, 0).getTime();

describe("les mots d'une carte", () => {
  it("les distances : des mètres, une décimale sous 10 km, des milliers insécables", () => {
    expect(km(847)).toBe("850 m");
    expect(km(5_830)).toBe("5,8 km");
    expect(km(7_000)).toBe("7 km");
    expect(km(58_015)).toBe("58 km");
    expect(km(1_388_400)).toBe("1 388 km");
    expect(km(null)).toBe("");
    expect(km(-1)).toBe("");
  });

  it("les durées : minutes, puis heures et minutes", () => {
    expect(duration(20)).toBe("1 min");
    expect(duration(45 * 60)).toBe("45 min");
    expect(duration(7 * 3600 + 5 * 60)).toBe("7 h 05");
    expect(duration(16 * 3600)).toBe("16 h");
    expect(duration(undefined)).toBe("");
  });

  it("le mode et ce qu'un trajet évite", () => {
    expect(modeWords("velo")).toBe("à vélo");
    expect(avoidWords([])).toBe("péages acceptés");
    expect(avoidWords([], "pied")).toBe("");
    expect(avoidWords(["autoroutes"])).toBe("sans autoroute");
    expect(avoidWords(["peages", "autoroutes", "ferries"])).toBe("sans péage, autoroute ni ferry");
  });

  it("une seule table des options d'un trajet en voiture, dans l'ordre de l'API (F3-16)", () => {
    // Itinéraire et les deux fenêtres d'un voyage la lisent : aucune ne réécrit ses libellés
    expect(Object.keys(AVOID_LABELS)).toEqual([...AVOIDS]);
    expect(AVOID_LABELS).toEqual({ peages: "les péages", autoroutes: "les autoroutes", ferries: "les ferries" });
  });

  it("les jours d'un voyage", () => {
    expect(isoDay("2027-04-03")?.getDay()).toBe(6); // un samedi
    expect(isoDay("2027-02-30")).toBeNull();
    expect(isoOf(new Date(2027, 3, 3))).toBe("2027-04-03");
    expect(dayLabel("2026-11-21", NOW)).toBe("sam. 21 novembre");
    expect(dayLabel("2027-04-03", NOW)).toBe("sam. 3 avril 2027");
    expect(tripDates("2027-04-03", 5, NOW)).toBe("du sam. 3 au mer. 7 avril 2027");
    expect(tripDates("2026-11-21", 2, NOW)).toBe("sam. 21 et dim. 22 novembre");
    expect(tripDates("2026-10-31", 2, NOW)).toBe("sam. 31 octobre et dim. 1er novembre · passé");
    expect(tripPast("2026-10-31", 2, NOW)).toBe(true);
    expect(tripDates("2026-11-30", 3, NOW)).toBe("du lun. 30 novembre au mer. 2 décembre");
    expect(tripDates("", 3, NOW)).toBe("");
  });

  it("les jours d'un voyage en court, pour le menu « Ajouter au voyage » d'un téléphone (F3-17)", () => {
    expect(tripSpan("2027-04-03", 5, NOW)).toBe("3–7 avr. 2027"); // l'année, si ce n'est pas celle d'aujourd'hui
    expect(tripSpan("2027-04-03", 5, new Date(2027, 0, 10).getTime())).toBe("3–7 avr.");
    expect(tripSpan("2027-03-30", 4, NOW)).toBe("30 mars–2 avr. 2027");
    expect(tripSpan("2026-11-21", 2, NOW)).toBe("21–22 nov.");
    expect(tripSpan("2026-11-21", 1, NOW)).toBe("21 nov.");
    expect(tripSpan("2026-11-21", 0, NOW)).toBe("21 nov.");
    expect(tripSpan("2026-11-30", 3, NOW)).toBe("30 nov.–2 déc.");
    expect(tripSpan("2026-12-30", 4, NOW)).toBe("30 déc.–2 janv. 2027");
    expect(tripSpan("2026-10-31", 2, NOW)).toBe("31 oct.–1er nov."); // passé : le menu ne le dit pas
    expect(tripSpan("", 3, NOW)).toBe("");
  });

  it("le pluriel et ce qu'est un lieu", () => {
    expect(plural(1, "jour")).toBe("1 jour");
    expect(plural(3, "lieu", "lieux")).toBe("3 lieux");
    expect(placeWhat({ kind_fr: "Camping", town: "Sévrier" })).toBe("Camping · Sévrier");
    expect(placeWhat({ category: "adresse", town: "Paris" })).toBe("Adresse · Paris");
  });
});
