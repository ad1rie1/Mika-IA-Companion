import { describe, expect, it } from "vitest";
import type { AgendaCalendar, AgendaItem, Proposal } from "../../api/agenda";
import { agendaCards } from "./chat";
import { addDays, bounds, daysFrom, localInput, localOf, mondayOf, offsetWords, periodWords, step } from "./dates";
import { fieldsOf, type FormValues } from "./form";
import { answerBox, searchView, type AgendaView } from "./view";
import {
  alertMinutes,
  alertUnit,
  alertWords,
  choiceOf,
  colorOf,
  columns,
  customOf,
  lanes,
  nearestColor,
  occOfItem,
  occOfProposal,
  relative,
  rightsSummary,
  ruleOf,
  ruleWords,
  shownName,
  sortOf,
  targetKey,
  targetOf,
} from "./model";

const PARIS = "Europe/Paris";
/** Un instant de Paris (heure d'hiver, UTC+1). */
const at = (day: string, hhmm: string) => Date.parse(`${day}T${hhmm}:00+01:00`);

function item(over: Partial<AgendaItem> = {}): AgendaItem {
  return {
    event: 1, occurrence: "", uid: "u", calendar: "moi:a~mon-agenda", title: "Dentiste", masked: false,
    start: at("2026-11-24", "17:30"), end: at("2026-11-24", "18:00"), all_day: false, first_day: "", last_day: "",
    zone: PARIS, location: "", description: "", conference: "", status: "confirme", busy: true, private: false,
    recurring: false, rule: "", organizer: null, participants: [], response: "", invitation: false, organized: true,
    added: null, remind: "", forgotten: false, can: { edit: true, delete: true, respond: false, duplicate: true, remind: true },
    ...over,
  };
}

function cal(over: Partial<AgendaCalendar> = {}): AgendaCalendar {
  return {
    key: "moi:a~mon-agenda", account: "moi:a", name: "Mon agenda", provider_name: "", kind: "systeme", kind_label: "", level: "proprietaire",
    owner_name: "", group: "mine", color: "", provider_color: "", primary: true, hidden: false, enabled: true, reminder: "30",
    reminder_set: "", writable: true, read_only: false,
    can: { write: true, respond: true, settings: true, share: true, rights: true, remind: true }, synced_at: 0, ...over,
  };
}

describe("les dates de l'Agenda", () => {
  it("compte les jours sans heure d'été et commence la semaine le lundi", () => {
    expect(addDays("2026-10-24", 2)).toBe("2026-10-26"); // le passage à l'heure d'hiver n'y change rien
    expect(daysFrom("2026-11-23", "2026-12-01")).toBe(8);
    expect(mondayOf("2026-11-29")).toBe("2026-11-23");
    expect(mondayOf("2026-11-23")).toBe("2026-11-23");
  });

  it("borne chaque vue : la semaine, le mois en semaines entières, quatre semaines de planning", () => {
    expect(bounds("semaine", "2026-11-25")).toEqual(["2026-11-23", "2026-11-30"]);
    expect(bounds("jour", "2026-11-25")).toEqual(["2026-11-25", "2026-11-26"]);
    expect(bounds("mois", "2026-11-25")).toEqual(["2026-10-26", "2026-12-07"]);
    expect(bounds("planning", "2026-11-24")).toEqual(["2026-11-24", "2026-12-22"]);
  });

  it("dit la période comme la maquette, en long et sur un téléphone", () => {
    expect(periodWords("semaine", "2026-11-24", "2026-11-24")).toBe("23 – 29 novembre 2026");
    expect(periodWords("semaine", "2026-11-24", "2026-11-24", true)).toBe("23 – 29 nov.");
    expect(periodWords("semaine", "2026-12-01", "2026-11-24")).toBe("30 nov. – 6 déc. 2026");
    expect(periodWords("mois", "2026-11-24", "2026-11-24")).toBe("Novembre 2026");
    expect(periodWords("jour", "2026-11-24", "2026-11-24")).toBe("Mardi 24 novembre 2026");
    expect(periodWords("planning", "2026-11-24", "2026-11-24", true)).toBe("Dès le 24 nov.");
  });

  it("un mois qui revient à celui d'aujourd'hui y revient à aujourd'hui", () => {
    expect(step("mois", "2026-10-03", 1, "2026-11-24")).toBe("2026-11-24");
    expect(step("mois", "2026-11-24", 1, "2026-11-24")).toBe("2026-12-01");
    expect(step("semaine", "2026-11-24", -1, "2026-11-24")).toBe("2026-11-17");
  });

  it("lit un instant à l'heure du fuseau du serveur, et son décalage", () => {
    expect(localOf(Date.parse("2026-11-24T16:30:00Z"), PARIS)).toEqual({ day: "2026-11-24", minute: 17 * 60 + 30 });
    expect(localOf(Date.parse("2026-11-24T23:30:00Z"), PARIS).day).toBe("2026-11-25");
    expect(localInput(Date.parse("2026-07-01T08:00:00Z"), PARIS)).toBe("2026-07-01T10:00");
    expect(offsetWords(PARIS, Date.parse("2026-11-24T12:00:00Z"))).toBe("UTC+1");
    expect(offsetWords(PARIS, Date.parse("2026-07-01T12:00:00Z"))).toBe("UTC+2");
    expect(offsetWords("Asia/Kolkata", Date.parse("2026-07-01T12:00:00Z"))).toBe("UTC+5:30");
  });
});

describe("ce que l'Agenda montre", () => {
  it("place un rendez-vous, une journée entière, plusieurs jours", () => {
    const o = occOfItem(item(), PARIS);
    expect([o.day, o.last, o.allDay, o.start, o.end]).toEqual(["2026-11-24", "2026-11-24", false, 1050, 1080]);
    const d = occOfItem(item({ all_day: true, first_day: "2026-12-05", last_day: "2026-12-06", start: Date.parse("2026-12-05T00:00:00Z"), end: Date.parse("2026-12-07T00:00:00Z") }), PARIS);
    expect([d.day, d.last, d.allDay]).toEqual(["2026-12-05", "2026-12-06", true]);
    const long = occOfItem(item({ start: at("2026-11-24", "09:00"), end: at("2026-11-26", "18:00") }), PARIS);
    expect([long.day, long.last, long.allDay]).toEqual(["2026-11-24", "2026-11-26", true]);
    const late = occOfItem(item({ start: at("2026-11-24", "22:00"), end: at("2026-11-25", "01:00") }), PARIS);
    expect([late.day, late.end]).toEqual(["2026-11-24", 1440]);
    expect(occOfItem(item({ masked: true, title: "" }), PARIS).title).toBe("Occupé");
  });

  it("dit la sorte d'une occurrence : invitation, peut-être, proposition de Mika", () => {
    expect(sortOf(occOfItem(item({ invitation: true, response: "attente" }), PARIS))).toBe("invite");
    expect(sortOf(occOfItem(item({ response: "peut" }), PARIS))).toBe("peut");
    const p = { id: 7, op: "ajouter", calendar: "c", draft: { title: "Dîner", start: at("2026-11-28", "20:00"), end: at("2026-11-28", "23:00"), all_day: false, zone: PARIS, location: "", description: "", rule: "", invite: [] } } as unknown as Proposal;
    const o = occOfProposal(p, PARIS)!;
    expect([sortOf(o), o.key, o.start]).toEqual(["propose", "proposition/7", 1200]);
  });

  it("partage la largeur entre ce qui se chevauche, et range les journées en bandes", () => {
    const a = occOfItem(item({ event: 1, start: at("2026-11-24", "10:00"), end: at("2026-11-24", "11:00") }), PARIS);
    const b = occOfItem(item({ event: 2, start: at("2026-11-24", "10:30"), end: at("2026-11-24", "12:00") }), PARIS);
    const c = occOfItem(item({ event: 3, start: at("2026-11-24", "14:00"), end: at("2026-11-24", "15:00") }), PARIS);
    const placed = columns([a, b, c]);
    expect(placed.map((x) => [x.o.item!.event, x.col, x.cols])).toEqual([[1, 0, 2], [2, 1, 2], [3, 0, 1]]);
    const d1 = occOfItem(item({ event: 4, all_day: true, first_day: "2026-11-23", last_day: "2026-11-25" }), PARIS);
    const d2 = occOfItem(item({ event: 5, all_day: true, first_day: "2026-11-24", last_day: "2026-11-24" }), PARIS);
    expect(lanes([d1, d2], "2026-11-23", 7).map((l) => [l.from, l.to, l.lane])).toEqual([[0, 2, 0], [1, 1, 1]]);
  });

  it("dit où en est un rendez-vous par rapport à maintenant", () => {
    const o = occOfItem(item(), PARIS);
    expect(relative(o, "2026-11-24", 17 * 60)).toEqual(["accent", "dans 30 min"]);
    expect(relative(o, "2026-11-24", 17 * 60 + 40)).toEqual(["ok", "en cours"]);
    expect(relative(o, "2026-11-24", 19 * 60)).toEqual(["", "passé"]);
    expect(relative(o, "2026-11-22", 600)).toEqual(["", "dans 2 jours"]);
  });

  it("garde une adresse pour chaque chose ouverte", () => {
    for (const t of [{ kind: "event", event: 42, occurrence: "20261125T130000Z" }, { kind: "event", event: 3, occurrence: "" }, { kind: "proposal", id: 9 }] as const) {
      const key = targetKey(t);
      expect(targetOf(key.split("/").map(decodeURIComponent))).toEqual(t);
    }
    expect(targetOf(["evenement", "x"])).toBeNull();
  });

  it("rapproche la couleur du fournisseur de la palette ; « Mon agenda » est indigo ; le rose est à Mika", () => {
    expect(nearestColor("#1f6fd0")).toBe("bleu");
    expect(nearestColor("#7BD148")).toBe("vert");
    expect(colorOf(cal())).toBe("indigo");
    expect(colorOf(cal({ color: "ambre" }))).toBe("ambre");
    expect(colorOf(cal({ kind: "mika" }))).toBe("rose");
    expect(colorOf(cal({ level: "lire", primary: true, key: "moi:b~mon-agenda" }))).not.toBe("rose");
  });
});

describe("la répétition et les rappels", () => {
  it("écrit la règle d'un choix, et retrouve le choix d'une règle", () => {
    expect(ruleOf("semaine", "2026-11-24")).toBe("FREQ=WEEKLY;BYDAY=TU");
    expect(ruleOf("mois", "2026-11-24")).toBe("FREQ=MONTHLY;BYMONTHDAY=24");
    expect(choiceOf("FREQ=WEEKLY;BYDAY=TU", "2026-11-24")).toBe("semaine");
    expect(choiceOf("FREQ=WEEKLY", "2026-11-24")).toBe("perso");
    const custom = { interval: 2, unit: "semaines", days: [1, 4], ends: "le", until: "2027-06-30", count: 5 } as const;
    const rule = ruleOf("perso", "2026-11-24", { ...custom, days: [...custom.days] });
    expect(rule).toBe("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;UNTIL=20270630");
    expect(customOf(rule, "2026-11-24")).toMatchObject({ interval: 2, unit: "semaines", days: [1, 4], ends: "le", until: "2027-06-30" });
    expect(ruleWords(rule, "2026-11-24", "2026-11-24")).toBe("Toutes les 2 semaines, le lundi et jeudi, jusqu'au mercredi 30 juin 2027");
    expect(ruleWords("FREQ=YEARLY", "2026-11-28", "2026-11-24")).toBe("Chaque année, le 28 novembre");
    expect(ruleWords("FREQ=WEEKLY;COUNT=5;BYDAY=MO", "2026-11-23", "2026-11-24")).toBe("Chaque lundi, 5 fois");
  });

  it("dit un rappel du fournisseur et le met en champs", () => {
    expect(alertWords({ method: "email", minutes: 1440 })).toBe("e-mail 1 jour avant");
    expect(alertWords({ method: "notification", minutes: 10 })).toBe("notification 10 min avant");
    expect(alertUnit(120)).toEqual({ n: 2, unit: "heures" });
    expect(alertMinutes(2, "jours")).toBe(2880);
  });
});

describe("ce que le formulaire envoie", () => {
  const start: FormValues = {
    calendar: "c", title: "Coiffeur", d1: "2026-11-24", h1: "18:00", d2: "2026-11-24", h2: "18:30", allDay: false, zone: PARIS,
    repeat: "", custom: { interval: 1, unit: "semaines", days: [2], ends: "jamais", until: "", count: 10 }, location: "", conference: "",
    description: "", invite: [], reminders: [{ method: "notification", minutes: 30 }], remindersTouched: false, remind: "", free: false, private: false,
  };

  it("une création envoie tout, sans les rappels du fournisseur qu'on n'a pas touchés (ceux de l'agenda chez lui)", () => {
    const f = fieldsOf("nouveau", start, start, true);
    expect(f).toMatchObject({ title: "Coiffeur", start: "2026-11-24T18:00", end: "2026-11-24T18:30", all_day: false, zone: PARIS, rule: "", remind: "" });
    expect("reminders" in f).toBe(false);
    expect(fieldsOf("nouveau", { ...start, remindersTouched: true, reminders: [] }, start, true).reminders).toEqual([]);
    expect(fieldsOf("nouveau", { ...start, allDay: true, d2: "2026-11-23" }, start, false)).toMatchObject({ start: "2026-11-24", end: "2026-11-24", all_day: true });
    expect("remind" in fieldsOf("nouveau", start, start, false)).toBe(false); // « Mika te le rappelle » : son propriétaire
  });

  it("une modification n'envoie que ce qui a changé ; un moment changé part en entier", () => {
    expect(fieldsOf("modifier", start, start, true)).toEqual({});
    expect(fieldsOf("modifier", { ...start, title: "Coiffeur · Paul" }, start, true)).toEqual({ title: "Coiffeur · Paul" });
    expect(fieldsOf("modifier", { ...start, h1: "17:00" }, start, true)).toEqual({ start: "2026-11-24T17:00", end: "2026-11-24T18:30", all_day: false, zone: PARIS });
    expect(fieldsOf("modifier", { ...start, repeat: "jour" }, start, true)).toEqual({ rule: "FREQ=DAILY" });
    expect(fieldsOf("modifier", { ...start, remindersTouched: true, reminders: [{ method: "email", minutes: 60 }] }, start, true)).toEqual({ reminders: [{ method: "email", minutes: 60 }] });
  });

  it("une description que la zone de texte a seulement relue (fins de ligne, saut de tête) ne repart pas", () => {
    const fromServer = { ...start, description: "\nOrdre du jour :\r\n- budget\r\n" };
    const read = { ...fromServer, description: "Ordre du jour :\n- budget\n" }; // ce qu'un <textarea> en rend
    expect(fieldsOf("modifier", { ...read, title: "Coiffeur · Paul" }, fromServer, true)).toEqual({ title: "Coiffeur · Paul" });
    expect(fieldsOf("modifier", { ...read, description: "Ordre du jour :\n- budget\n- RH" }, fromServer, true)).toEqual({ description: "Ordre du jour :\n- budget\n- RH" });
  });
});

describe("l'agenda dans le chat", () => {
  it("la carte d'un ajout dit l'événement, son agenda et le rappel de Mika", () => {
    const p = { id: 12, op: "ajouter", calendar: "moi:a~mon-agenda", remind: "veille", draft: { title: "Dîner chez Léa", start: at("2026-11-28", "20:00"), end: at("2026-11-28", "23:00"), all_day: false, zone: PARIS, location: "rue de Gand", description: "", rule: "", invite: [] } } as unknown as Proposal;
    const got = agendaCards([p, { ...p, id: 13, op: "repondre", draft: null }], [cal()], PARIS, at("2026-11-24", "13:00")).get(12)!;
    expect(got).toMatchObject({ calendar: "Mon agenda", color: "indigo", title: "Dîner chez Léa", place: "rue de Gand", remind: "la veille au soir", edit: "#agenda/modifier/proposition/12" });
    expect(got.when).toBe("Samedi 28 novembre · 20:00 – 23:00");
    expect(agendaCards([{ ...p, id: 13, op: "repondre", draft: null } as unknown as Proposal], [], PARIS, 0).size).toBe(0);
  });
});

describe("les noms et les droits d'un agenda", () => {
  it("« Mon agenda » qu'une autre te partage se dit « Agenda de Léa »", () => {
    expect(shownName(cal({ group: "shared", level: "lire", owner_name: "Léa Moreau" }))).toBe("Agenda de Léa");
    expect(shownName(cal({ group: "shared", level: "lire", owner_name: "Adrien Moreau" }))).toBe("Agenda d'Adrien");
    expect(shownName(cal())).toBe("Mon agenda");
    expect(shownName(cal({ group: "shared", kind: "google", name: "Perso", owner_name: "Léa" }))).toBe("Perso");
  });

  it("dit en une ligne ce que Mika fait d'un agenda avec son propriétaire", () => {
    const line = (who: string[], when: string[], read: boolean, write: "non" | "accord" | "seule", respond: "non" | "accord") =>
      ({ who, canal: [], when, read, write, respond, keep: "rien" as const });
    const t = { calendar: "c", set: false, default: line([], [], false, "non", "non"),
      lines: [line(["personne:user_1"], ["conversation"], true, "accord", "accord"), line(["personne:user_1"], ["initiative"], true, "non", "non"), line(["elle"], [], true, "non", "accord")] };
    expect(rightsSummary(t, "user_1", [{ name: "Léa Moreau" }])).toBe("Avec toi, elle le lit, y ajoute avec ton accord, prépare tes réponses ; elle te rappelle ses rendez-vous · aussi avec Léa");
    expect(rightsSummary(t, "user_9")).toBe("");
  });
});

describe("chercher", () => {
  const v = { q: "dentiste" } as unknown as AgendaView;

  it("aucun agenda coché : l'écran le dit, et ne cherche pas « partout »", () => {
    const shown = searchView(v, [], false, "", true);
    expect(shown).toContain("Aucun agenda n'est coché");
    expect(shown).not.toContain("0 résultat");
  });

  it("des agendas cochés : le nombre de résultats", () => {
    expect(searchView(v, [], false, "")).toContain("0 résultat");
  });
});

describe("répondre à une invitation", () => {
  const can = { edit: false, delete: true, respond: true, duplicate: true, remind: true };

  it("une invitation récurrente dit que la réponse vaut pour toute la série", () => {
    const series = item({ invitation: true, response: "attente", recurring: true, occurrence: "20261124T163000Z", can });
    expect(answerBox(series, false)).toContain("Ta réponse vaut pour toute la série");
    expect(answerBox(item({ invitation: true, response: "attente", can }), false)).not.toContain("toute la série");
  });

  it("sans pouvoir répondre d'ici : pas de boutons, une ligne qui dit pourquoi", () => {
    const why = "Son serveur ne transmet pas les réponses aux invitations (pas de planification CalDAV) : réponds depuis ta messagerie.";
    const shown = answerBox(item({ invitation: true, response: "attente", can: { ...can, respond: false }, respond_why: why }), false);
    expect(shown).not.toContain('data-agrep="oui"');
    expect(shown).toContain("ne transmet pas les réponses");
  });
});
