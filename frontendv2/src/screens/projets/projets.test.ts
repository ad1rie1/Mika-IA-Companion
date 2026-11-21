import { describe, expect, it } from "vitest";
import type { ActivityPage, Demand, Diagram, DiagramMilestone, DiagramObjective, EntryDetail, EntryHistory, Field, Journey, Links, Listing, Milestone, Overview, ProjectHead, Sheet, Waiting } from "../../api/projects";
import { arrowPath, DAY_WIDTH, daysBack, goalSegments, milestonePart, pickZoom, rows, timeLayout } from "./diagram";
import {
  assignRequest, changed, checkpointRequest, fieldShown, fieldValue, gesturePlace, gestureRead, gestureRequest, itemAddRequest, linkCandidates, linkRequest, linkWhyRequest, milestoneRequest, noteRequest,
  objectiveRequest, pilotRequest, refusalWords, safeLink, settingsRequest, settleRequest, ticketRequest,
} from "./gestures";
import { inline, markdown } from "./md";
import { outside, outsideText, served, st, trio } from "./parts";
import { parsePlace, route, sheetRoute, waitingHome, waitingKey, waitingRoute } from "./routes";
import { chosenWaiting, findGoal, goalGroups, goalKey, initialState, refusalAt, ticketsQuery, todoGroups } from "./state";
import { age, dayLabel, duration, moment, when } from "./time";
import { milestoneTone, progressTone, ticketTone } from "./tones";
import { allDemands, demandKey, dependenciesView, itemDrawerBody, listsView, settingsView } from "./views/more";
import { goalDrawerBody, milestoneDrawerBody, milestoneState, verified } from "./views/objectives";
import { gridView, nextAbout, nextWhen, overviewView } from "./views/sheet";
import { historyPane, steps } from "./views/tickets";
import { todoView, type Ctx } from "./views/todo";

const NOW = new Date(2026, 10, 4, 14, 20).getTime();
const MIN = 60_000;
const DAY = 86_400_000;

function waiting(over: Partial<Waiting> = {}): Waiting {
  return {
    project: 3, project_title: "Outils réseau", kind: "ticket", kind_label: "ticket", what: "validation", about: "#4 Journaliser les refus", since: NOW - 4 * 60 * MIN, mine: true, can: true, why: "",
    waits_for: "", objective: 0, number: 4, key: "", veiled: "", outside: false,
    gesture: { route: "ticket/trancher", args: { item: "#4", verdict: "validate", plan: 812 }, label: "Valider ou refuser son plan", where: "ici", url: "" }, ...over,
  };
}

describe("les adresses de l'écran : celles de la maquette", () => {
  it("« À faire », puis le projet et la clé d'une attente", () => {
    expect(parsePlace("a-faire", null)).toEqual({ kind: "todo", project: 0, key: "" });
    expect(parsePlace("a-faire", "3/ticket-4")).toEqual({ kind: "todo", project: 3, key: "ticket-4" });
    expect(route("a-faire", 3, "ticket-4")).toBe("#projets/a-faire/3/ticket-4");
  });

  it("la grille, puis la fiche, son onglet et ce qui s'y ouvre", () => {
    expect(parsePlace("projets", null)).toEqual({ kind: "grid" });
    expect(parsePlace("projets", "3")).toEqual({ kind: "sheet", id: 3, tab: "vue", rest: [] });
    expect(parsePlace("projets", "3/tickets/4/plan")).toEqual({ kind: "sheet", id: 3, tab: "tickets", rest: ["4", "plan"] });
    expect(parsePlace("projets", "3/objectifs/diagramme/temps/o2/3")).toEqual({ kind: "sheet", id: 3, tab: "objectifs", rest: ["diagramme", "temps", "o2", "3"] });
    expect(parsePlace("projets", "3/reglages/rythme")).toEqual({ kind: "sheet", id: 3, tab: "reglages", rest: ["rythme"] });
    // un onglet inconnu : la Vue d'ensemble, sans reste
    expect(parsePlace("projets", "3/suivi/entreprises")).toEqual({ kind: "sheet", id: 3, tab: "vue", rest: [] });
  });

  it("la Vue d'ensemble n'a pas de segment ; un segment se code", () => {
    expect(sheetRoute(3)).toBe("#projets/projets/3");
    expect(sheetRoute(3, "vue")).toBe("#projets/projets/3");
    expect(sheetRoute(3, "tickets", 4, "fil")).toBe("#projets/projets/3/tickets/4/fil");
    expect(sheetRoute(5, "listes", "à voir/1")).toBe("#projets/projets/5/listes/%C3%A0%20voir%2F1");
  });

  it("la clé d'une attente vient de ce que le serveur dit d'elle, et son adresse la porte", () => {
    expect(waitingKey(waiting())).toBe("ticket-4");
    expect(waitingKey(waiting({ what: "merge", gesture: { route: "code/pull/fusionner", args: { number: 11 }, label: "Fusionner", where: "ici", url: "" } }))).toBe("pr-11");
    expect(waitingKey(waiting({ kind: "approval", gesture: { route: "accord", args: { proposal: 41 }, label: "", where: "ici", url: "" } }))).toBe("accord-41");
    expect(waitingKey(waiting({ kind: "checkpoint", objective: 2, number: 0, gesture: { route: "jalon", args: { objective: 2, milestone: 3 }, label: "", where: "ici", url: "" } }))).toBe("jalon-2-3");
    expect(waitingKey(waiting({ kind: "plan", number: 0 }))).toBe("plan");
    expect(waitingKey(waiting({ kind: "item", what: "entreprises", key: "atelier-brique", number: 0 }))).toBe("element-entreprises-atelier-brique");
    expect(waitingRoute(waiting())).toBe("#projets/a-faire/3/ticket-4");
    const parsed = parsePlace("a-faire", "3/ticket-4");
    expect(parsed.kind === "todo" && parsed.key).toBe(waitingKey(waiting()));
  });

  it("une attente s'ouvre là où elle vit dans son projet", () => {
    expect(waitingHome(waiting())).toBe("#projets/projets/3/tickets/4");
    expect(waitingHome(waiting({ kind: "checkpoint", objective: 2, number: 0 }))).toBe("#projets/projets/3/objectifs/o2");
    expect(waitingHome(waiting({ kind: "item", what: "entreprises", number: 0 }))).toBe("#projets/projets/3/listes/entreprises");
    expect(waitingHome(waiting({ what: "merge", gesture: { route: "code/pull/fusionner", args: { number: 11 }, label: "", where: "ici", url: "" } }))).toBe("#projets/projets/3/code/pulls/11");
  });
});

describe("l'état de l'écran", () => {
  it("« À faire » se groupe par projet, dans l'ordre du serveur", () => {
    const todo = [waiting({ project: 5, project_title: "B", number: 1 }), waiting({ project: 3, project_title: "A", number: 2 }), waiting({ project: 5, project_title: "B", number: 3 })];
    const groups = todoGroups(todo);
    expect(groups.map((g) => [g.project, g.items.map((w) => w.number)])).toEqual([[5, [1, 3]], [3, [2]]]);
  });

  it("l'attente choisie est celle de l'adresse ; sinon la première, sauf sur un téléphone", () => {
    const todo = [waiting({ number: 4 }), waiting({ number: 6 })];
    expect(chosenWaiting(todo, 3, "ticket-6", false)?.number).toBe(6);
    expect(chosenWaiting(todo, 3, "", false)?.number).toBe(4);
    expect(chosenWaiting(todo, 3, "", true)).toBeNull();
  });

  it("les objectifs en trois groupes, et leur clé d'adresse", () => {
    const sheet = { objectives: [{ id: 2, status: "open" }, { id: 1, status: "done" }], missions: [{ id: 7 }] } as unknown as Sheet;
    const groups = goalGroups(sheet);
    expect(groups.map((g) => [g.code, g.items.map(goalKey)])).toEqual([["open", ["o2"]], ["missions", ["m7"]], ["done", ["o1"]]]);
    expect(findGoal(sheet, "m7")?.mission).toBe(true);
    expect(findGoal(sheet, "o9")).toBeNull();
  });

  it("un filtre de tickets devient une requête ; « À toi » se lit dans les ouverts", () => {
    expect(ticketsQuery("open", " rdp ")).toEqual({ list: "tickets", state: "open", q: "rdp", size: 100 });
    expect(ticketsQuery("yours", "")).toEqual({ list: "tickets", state: "open", q: undefined, size: 100 });
    expect(ticketsQuery("all", "").state).toBeUndefined();
  });

  it("un refus ne se dit qu'à l'endroit de son geste", () => {
    const ui = initialState();
    ui.refusal = { where: "ticket:3:4", text: "Son plan a été réécrit depuis.", fields: {} };
    expect(refusalAt(ui, "ticket:3:4")).toBe("Son plan a été réécrit depuis.");
    expect(refusalAt(ui, "ticket:3:5")).toBe("");
  });
});

describe("un geste traduit en requête", () => {
  it("valider le plan d'un ticket nomme le plan lu, pas celui que la liste portait", () => {
    expect(gestureRequest(waiting(), "validate", "", { plan: 815 })).toEqual({ route: "ticket/trancher", body: { item: "#4", verdict: "validate", plan: 815 } });
    expect(gestureRequest(waiting(), "refuse", " pas de troisième commande ")).toEqual({ route: "ticket/trancher", body: { item: "#4", verdict: "refuse", reason: "pas de troisième commande" } });
    expect(settleRequest({ handle: "#4", plan: 812 }, "validate")).toEqual({ route: "ticket/trancher", body: { item: "#4", verdict: "validate", plan: 812 } });
    expect(settleRequest({ handle: "#4", plan: 812 }, "done")).toEqual({ route: "ticket/trancher", body: { item: "#4", verdict: "done" } });
  });

  it("un accord accepté renvoie le condensé lu ; refusé, il n'en a pas besoin", () => {
    const w = waiting({ kind: "approval", gesture: { route: "accord", args: { proposal: 41 }, label: "", where: "ici", url: "" } });
    expect(gestureRequest(w, "accept", "", { digest: "sha256:9f" })).toEqual({ route: "accord", body: { proposal: 41, decision: "accept", seen: "sha256:9f" } });
    expect(gestureRequest(w, "refuse", "")).toEqual({ route: "accord", body: { proposal: 41, decision: "refuse" } });
    expect(gestureRead(w)).toEqual({ kind: "approval", id: 41 });
  });

  it("ce qu'un geste demande de lire, et où il se règle", () => {
    expect(gestureRead(waiting())).toEqual({ kind: "element", list: "tickets", item: "#4" });
    expect(gestureRead(waiting({ gesture: { route: "plan", args: {}, label: "", where: "ici", url: "" } }))).toEqual({ kind: "plan" });
    expect(gestureRead(waiting({ objective: 2, gesture: { route: "jalon", args: { objective: 2, milestone: 3 }, label: "", where: "ici", url: "" } }))).toEqual({ kind: "milestone", objective: 2, milestone: 3 });
    expect(gesturePlace(waiting())).toBe("here");
    expect(gesturePlace(waiting({ can: false, why: "Ce n'est pas à toi de trancher." }))).toBe("denied");
    expect(gesturePlace(waiting({ mine: false }))).toBe("theirs");
    expect(gesturePlace(waiting({ gesture: { route: "", args: {}, label: "", where: "console", url: "" } }))).toBe("console");
    expect(gesturePlace(waiting({ gesture: { route: "", args: {}, label: "", where: "hote", url: "https://h/pull/1" } }))).toBe("host");
  });

  it("une pull request à fusionner fait lire son ticket : ce qui lui est lié se montre", () => {
    const merge = waiting({ what: "merge", number: 3, gesture: { route: "code/pull/fusionner", args: { number: 11 }, label: "Fusionner la pull request", where: "ici", url: "" } });
    expect(gestureRead(merge)).toEqual({ kind: "element", list: "tickets", item: "#3" });
  });

  it("piloter, noter, valider un point d'arrêt", () => {
    expect(pilotRequest("now", "", 2)).toEqual({ route: "piloter", body: { what: "now", objective: 2 } });
    expect(pilotRequest("instruct", " finis l'export ")).toEqual({ route: "piloter", body: { what: "instruct", text: "finis l'export" } });
    expect(noteRequest({ list: "tickets", handle: "#5", key: "t-5" }, " 3389 ")).toEqual({ route: "element/noter", body: { list: "tickets", item: "#5", text: "3389" } });
    expect(noteRequest({ list: "entreprises", handle: "x", key: "atelier" }, "ok").body.item).toBe("atelier");
    expect(checkpointRequest(2, 3, "refuse", "retire le champ")).toEqual({ route: "jalon", body: { objective: 2, milestone: 3, verdict: "refuse", reason: "retire le champ" } });
  });

  it("ajouter un objectif ou une mission ; modifier n'envoie que ce qui change", () => {
    expect(objectiveRequest({ kind: "once", text: " Créer un module ", done_when: "On se connecte." }, null)).toEqual({ route: "objectif", body: { text: "Créer un module", done_when: "On se connecte.", kind: "once" } });
    const mission = objectiveRequest({ kind: "constant", text: "Relire", cadence_hours: "24", on: ["list:tickets"], only_on_event: false, each_pass: "Relire les sorties.", at_once: true }, null);
    expect(mission.body).toEqual({ text: "Relire", cadence_hours: 24, on: ["list:tickets"], only_on_event: false, each_pass: "Relire les sorties.", kind: "constant", at_once: true });
    const before = { kind: "once", text: "Créer un module", done_when: "On se connecte." };
    expect(objectiveRequest({ text: "Créer un module RDP", done_when: "On se connecte." }, before, 2)).toEqual({ route: "objectif/modifier", body: { objective: 2, text: "Créer un module RDP" } });
    expect(changed({ on: ["a", "b"] }, { on: ["b", "a"] })).toEqual({});
  });

  it("un jalon : sa vérification, et seulement ses champs", () => {
    expect(milestoneRequest(2, { text: "La connexion aboutit", check: "command", command: "pytest -k connect", item: "ignoré" }, null)).toEqual({ route: "jalon/ajouter", body: { objective: 2, text: "La connexion aboutit", check: "command", command: "pytest -k connect" } });
    expect(milestoneRequest(2, { text: "Relu", check: "owner" }, { text: "Relu par toi", check: "owner", command: "" }, 3)).toEqual({ route: "jalon/modifier", body: { objective: 2, milestone: 3, text: "Relu" } });
    // ce qui le lie à un élément du registre : seul ce qui change part
    const before = { text: "Trois entreprises contactées", check: "item", command: "", item_list: "entreprises", item: "atelier-brique", item_status: "contactee" };
    expect(milestoneRequest(2, { ...before, item_status: "interessee" }, before, 4)).toEqual({ route: "jalon/modifier", body: { objective: 2, milestone: 4, item_status: "interessee" } });
  });

  it("une liste de suivi : ajouter un élément, changer à qui il est", () => {
    expect(itemAddRequest("entreprises", { title: " Lumen Conseil ", text: "", status: "a_contacter", actor: "owner" })).toEqual({ route: "element/ajouter", body: { list: "entreprises", title: "Lumen Conseil", status: "a_contacter", actor: "owner" } });
    expect(assignRequest({ list: "entreprises", handle: "", key: "atelier-brique" }, "self")).toEqual({ route: "element/confier", body: { list: "entreprises", item: "atelier-brique", actor: "self" } });
  });

  it("un ticket : l'ouvrir, ou n'envoyer que ce qui change", () => {
    expect(ticketRequest({ title: " Exporter ", text: "", kind: "task", priority: "normal" }, null)).toEqual({ route: "ticket", body: { title: "Exporter", kind: "task", priority: "normal" } });
    expect(ticketRequest({ title: "Exporter", text: "En CSV.", kind: "task", priority: "high" }, { title: "Exporter", text: "En CSV.", kind: "task", priority: "normal" }, "#3")).toEqual({ route: "ticket/modifier", body: { item: "#3", priority: "high" } });
  });

  it("les réglages : les seuls champs changés, à leur forme (un booléen reste un booléen)", () => {
    const fields = [
      { name: "title", kind: "text", value: "Outils réseau" }, { name: "reread", kind: "bool", value: true }, { name: "runs_per_day", kind: "int", value: 6 }, { name: "days", kind: "multi", value: ["lun", "mar"] },
    ] as unknown as Field[];
    expect(settingsRequest("general", fields, { title: "Outils réseau", reread: false, runs_per_day: "6", days: ["mar", "lun"] })).toEqual({ route: "reglages/enregistrer", body: { section: "general", values: { reread: false } } });
    expect(settingsRequest("general", fields, { title: "Outils", reread: true, runs_per_day: "8", days: ["lun"] }).body.values).toEqual({ title: "Outils", runs_per_day: 8, days: ["lun"] });
    // un champ que le serveur dit réservé (`can: false`) ne part jamais, même si le formulaire en rend une autre valeur
    const reserved = [{ name: "tool_email", kind: "bool", value: false, can: false, why: "Ce réglage ouvre autre chose que ce projet." }, { name: "tool_web", kind: "bool", value: false, can: true, why: "" }] as unknown as Field[];
    expect(settingsRequest("outils", reserved, { tool_email: true, tool_web: true }).body.values).toEqual({ tool_web: true });
    expect(fieldValue(fields[1], true)).toBe(true);
  });

  it("un champ réservé à certaines valeurs d'un autre", () => {
    const f = { name: "schedule_rule", only: [{ field: "schedule", values: ["semaine"] }] } as unknown as Field;
    expect(fieldShown(f, { schedule: "jour" })).toBe(false);
    expect(fieldShown(f, { schedule: "semaine" })).toBe(true);
    expect(fieldShown({ name: "x" } as unknown as Field, {})).toBe(true);
  });

  it("ses dépendances : ce qui change, lien par lien, et seulement des projets qu'elle voit", () => {
    expect(linkRequest("add", 7)).toEqual({ route: "liens", body: { add: [7] } });
    expect(linkRequest("direct_off", 3)).toEqual({ route: "liens", body: { direct_off: [3] } });
    // le mot du lien se dit en le posant, et nomme son projet ; ou seul, plus tard
    expect(linkRequest("add", 7, " pour citer ses commandes ")).toEqual({ route: "liens", body: { add: [7], why: "pour citer ses commandes", why_for: 7 } });
    expect(linkRequest("remove", 7, "ignoré")).toEqual({ route: "liens", body: { remove: [7] } });
    expect(linkWhyRequest(3, "pour ses commandes")).toEqual({ route: "liens", body: { why: "pour ses commandes", why_for: 3 } });
    const links = { reads: [{ project: 3 }], candidates: [{ project: 3, title: "A", visible: true, gives: {} }, { project: 7, title: "B", visible: true, gives: {} }, { project: null, title: "", visible: false, gives: {} }] } as unknown as Links;
    expect(linkCandidates(links).map((c) => c.project)).toEqual([7]);
  });

  it("un refus dit ses mots, puis ceux de ses champs ; un lien ne s'ouvre que s'il est http ou https", () => {
    expect(refusalWords("Refusé.", { reason: "une raison est exigée" })).toBe("Refusé. une raison est exigée");
    expect(refusalWords("Une raison est exigée.", {})).toBe("Une raison est exigée.");
    expect(safeLink("https://github.com/x/y/pull/1")).toBe("https://github.com/x/y/pull/1");
    expect(safeLink("javascript:alert(1)")).toBe("");
  });
});

describe("un texte venu d'ailleurs est cité, jamais interprété", () => {
  const hostile = '<img src=x onerror="alert(1)"> **gras** `code` [lien](javascript:alert(1))';

  it("il est échappé, sans balise, sans gras ni code fabriqués, dans sa présentation à lui", () => {
    const html = outside("quelqu'un chez l'hôte du dépôt", hostile);
    expect(html).toContain('class="p2-out"');
    expect(html).toContain("Venu d'ailleurs");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<b>");
    expect(html).not.toContain("<code>");
    expect(html).not.toContain("<a ");
    expect(html).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  });

  it("la sortie d'une commande reste en chasse fixe ; rien de servi, rien de montré", () => {
    expect(outsideText({ text: "3 passed <ok>", outside: true }, "la preuve")).toContain("<pre>3 passed &lt;ok&gt;</pre>");
    expect(outsideText(null, "la preuve")).toBe("");
  });

  it("un texte d'elle ou de la personne passe par le petit Markdown, échappé d'abord", () => {
    expect(inline("un `export --csv` <b>")).toBe("un <code>export --csv</code> &lt;b&gt;");
    const html = markdown("## Titre\n\n- un\n- deux\n\n1. premier\n\n```\n<x>\n```\n<script>alert(1)</script>");
    expect(html).toContain("<h3>Titre</h3>");
    expect(html).toContain("<ul><li>un</li><li>deux</li></ul>");
    expect(html).toContain("<ol><li>premier</li></ol>");
    expect(html).toContain("<pre><code>&lt;x&gt;</code></pre>");
    expect(html).not.toContain("<script>");
  });

  it("une pastille et un champ servi échappent ce qu'ils montrent", () => {
    expect(st("out", "venu <d'ailleurs>")).toContain("venu &lt;d&#39;ailleurs&gt;");
    const field = { name: "title", label: "Son <nom>", help: "", kind: "text", required: true, choices: [], value: '"x"', only: [] } as unknown as Field;
    const html = served(field, {});
    expect(html).toContain("Son &lt;nom&gt;");
    expect(html).toContain('value="&quot;x&quot;"');
  });
});

describe("les trois zones", () => {
  it("la liste, le contenu en volets, le panneau latéral et son volet « Infos »", () => {
    const html = trio({ list: "<i>liste</i>", head: "<h2>t</h2>", panes: [["a", "Description"], ["b", "Fil", 3]], active: "b", link: (k) => `#x/${k}`, body: "corps", side: "côté" });
    expect(html).toContain('class="split p2-split"');
    expect(html).toContain('<section class="pane p2-list"><i>liste</i></section>');
    expect(html).toContain('<a href="#x/b" data-p2="volet" data-va="1" aria-current="page">Fil<span class="cnt">3</span></a>');
    expect(html).toContain('<article class="p2-c">corps</article>');
    expect(html).toContain('<aside class="p2-side pane-scroll"');
    expect(html).toContain('class="p2-v-infos"');
  });

  it("sans liste : deux zones ; sans panneau : pas de volet « Infos »", () => {
    const html = trio({ panes: [["", "Schéma"]], active: "", body: "x", plain: true });
    expect(html).toContain("sans-liste");
    expect(html).toContain("sans-cote");
    expect(html).not.toContain("p2-v-infos");
    expect(html).not.toContain("p2-list");
  });
});

describe("le temps, en mots", () => {
  it("depuis quand, en court et en entier", () => {
    expect(when(NOW - 30_000, NOW)).toBe("à l'instant");
    expect(when(NOW - 6 * MIN, NOW)).toBe("il y a 6 min");
    expect(when(NOW - 4 * 60 * MIN, NOW)).toBe("il y a 4 h");
    expect(when(NOW - DAY, NOW)).toBe("hier");
    expect(when(NOW - 4 * DAY, NOW)).toBe("samedi");
    expect(when(NOW - 20 * DAY, NOW)).toBe("15 oct.");
    expect(when(0, NOW)).toBe("");
    expect(age(NOW - 22 * MIN, NOW)).toBe("22 min");
    expect(moment(NOW - 6 * MIN, NOW)).toBe("aujourd'hui à 14:14");
    expect(dayLabel(NOW - 2 * DAY, NOW)).toBe("lundi 2 novembre");
    // un instant à venir (un prochain passage) dit son jour, jamais « aujourd'hui »
    expect(dayLabel(NOW + DAY, NOW)).toBe("Demain");
    expect(dayLabel(NOW + 2 * DAY, NOW)).toBe("vendredi 6 novembre");
    expect(moment(NOW + 2 * DAY, NOW)).toBe("vendredi 6 novembre à 14:20");
    expect(duration(960)).toBe("16 min");
    expect(duration(3900)).toBe("1 h 05");
  });
});

describe("les couleurs d'état suivent ce que le serveur dit", () => {
  it("« à toi » ne vient que de `ready` et de `yours`", () => {
    expect(milestoneTone({ status: "open", ready: true })).toBe("you");
    expect(milestoneTone({ status: "open", ready: false })).toBe("wait");
    expect(milestoneTone({ status: "reached", ready: false })).toBe("done");
    // un jalon commencé (`started`) : bleu ; un objectif d'une carte suit son état servi
    expect(milestoneTone({ status: "open", ready: false, started: true })).toBe("work");
    expect(milestoneTone({ status: "open", ready: true, started: true })).toBe("you");
    expect(["done", "doing", "todo", "blocked"].map(progressTone)).toEqual(["done", "work", "wait", "fail"]);
    expect(ticketTone({ status: "validation", open: true, yours: true })).toBe("you");
    expect(ticketTone({ status: "validation", open: true, yours: false })).toBe("work");
    expect(ticketTone({ status: "treated", open: false, yours: false })).toBe("done");
  });
});

function milestone(over: Partial<DiagramMilestone>): DiagramMilestone {
  return { id: 1, text: "j", status: "open", status_label: "à faire", check: "prose", check_label: "sa parole", ready: false, added_at: NOW - 5 * DAY, started_at: 0, ready_at: 0, reached_at: 0, runs: 0, ...over };
}

function objective(over: Partial<DiagramObjective>): DiagramObjective {
  return { id: 1, text: "o", kind: "once", status: "open", status_label: "en cours", after: 0, rank: 1, ticket: 0, added_at: NOW - 5 * DAY, started_at: 0, last_run: 0, closed_at: 0, runs: 0, reached: 0, milestones_total: 0, passes: [], milestones: [], ...over };
}

describe("le diagramme des objectifs", () => {
  const first = objective({ id: 1, status: "done", started_at: NOW - 5 * DAY, closed_at: NOW - 4 * DAY, runs: 3, milestones: [milestone({ id: 1, status: "reached", started_at: NOW - 5 * DAY, reached_at: NOW - 4 * DAY, runs: 1 })] });
  const second = objective({ id: 2, after: 1, started_at: NOW - 3 * DAY, runs: 6, milestones: [
    milestone({ id: 1, status: "reached", started_at: NOW - 3 * DAY, reached_at: NOW - DAY, runs: 3 }), milestone({ id: 2, ready: true, started_at: NOW - DAY, ready_at: NOW - 5 * 60 * MIN, runs: 1 }),
    milestone({ id: 3, started_at: NOW - 4 * 60 * MIN, runs: 2 }), milestone({ id: 4 })] });
  const third = objective({ id: 3, after: 2, milestones: [milestone({ id: 1 }), milestone({ id: 2 })] });
  const mission = objective({ id: 7, kind: "constant", started_at: NOW - 4 * DAY, runs: 4, passes: [NOW - 4 * DAY, NOW - 2 * DAY, NOW - DAY, NOW - 60 * MIN] });
  const d: Diagram = { now: NOW, from: NOW - 5 * DAY, cut: false, objectives: [first, mission, second, third] };

  it("une ligne par objectif, ses jalons en retrait sauf replié, les missions à la fin", () => {
    const all = rows(d);
    expect(all.rows.map((r) => `${r.sort}${r.o.id}${r.sort === "milestone" ? `.${r.m.id}` : ""}`)).toEqual(["goal1", "milestone1.1", "goal2", "milestone2.1", "milestone2.2", "milestone2.3", "milestone2.4", "goal3", "milestone3.1", "milestone3.2", "mission7"]);
    expect(all.height).toBe(3 * 46 + 7 * 36 + 46);
    expect(rows(d, new Set([2])).rows.filter((r) => r.sort === "milestone" && r.o.id === 2)).toHaveLength(0);
  });

  it("la part faite : atteint ou prêt, entière ; commencé, selon ses exécutions ; pas commencé, rien", () => {
    expect(milestonePart(milestone({ status: "reached" }))).toBe(1);
    expect(milestonePart(milestone({ ready: true }))).toBe(1);
    expect(milestonePart(milestone({ started_at: NOW, runs: 2 }))).toBeCloseTo(0.65);
    expect(milestonePart(milestone({ started_at: NOW, runs: 9 }))).toBe(0.9);
    expect(milestonePart(milestone({}))).toBe(0);
    const segments = goalSegments(second);
    expect(segments.map((s) => s.tone)).toEqual(["done", "you", "work"]);
    expect(segments[0].part).toBeCloseTo(0.25);
    expect(segments.reduce((a, s) => a + s.part, 0)).toBeLessThan(1);
    expect(goalSegments(objective({ status: "done" }))).toEqual([{ tone: "done", part: 1 }]);
    expect(goalSegments(objective({}))).toEqual([]);
  });

  it("l'axe part de la première date servie ; rien n'a de date inventée", () => {
    expect(daysBack(d, "days")).toBe(5);
    expect(daysBack({ now: NOW, from: 0, objectives: [] }, "days")).toBe(2);
    const t = timeLayout(d, rows(d).rows, { zoom: "days", width: 0 });
    expect(t.day).toBe(DAY_WIDTH.days.natural);
    expect(t.days).toHaveLength(6);
    expect(t.days[0].x).toBe(0);
    // ce qui n'a pas commencé est un fantôme, après aujourd'hui, dans l'ordre du plan
    const ghost = t.tracks[6];
    expect(ghost.bars).toHaveLength(1);
    expect(ghost.bars[0].cls).toBe("fantome");
    expect(ghost.bars[0].left).toBeGreaterThan(t.today);
    expect(ghost.label).toBe(-1);
    const later = t.tracks[8].bars[0];
    expect(later.left).toBeGreaterThan(ghost.bars[0].left + ghost.bars[0].width);
  });

  it("un point d'arrêt prêt : sa barre en deux temps, la seconde « à toi »", () => {
    const t = timeLayout(d, rows(d).rows, { zoom: "days", width: 0 });
    const ready = t.tracks[4];
    expect(ready.bars.map((b) => b.cls)).toEqual(["work", "you hache"]);
    expect(ready.bars[1].left + ready.bars[1].width).toBeGreaterThanOrEqual(t.today);
  });

  it("le premier défaut de la maquette : les premiers jours tiennent à l'écran à l'ouverture", () => {
    // 900 px de piste pour cinq jours et demi, plus la suite sans date : à 124 px le jour ça ne tient pas ; l'axe se resserre
    const t = timeLayout(d, rows(d).rows, { zoom: "days", width: 900 });
    expect(t.day).toBeLessThan(DAY_WIDTH.days.natural);
    expect(t.day).toBeGreaterThanOrEqual(DAY_WIDTH.days.min);
    expect(t.fits).toBe(true);
    expect(t.width).toBe(900);
    expect(t.today).toBeLessThan(900);
    // la piste large : rien à resserrer
    expect(timeLayout(d, rows(d).rows, { zoom: "days", width: 4000 }).day).toBe(DAY_WIDTH.days.natural);
    // un projet de deux mois ne tient pas en jours : l'échelle passe en semaines d'elle-même
    const long = { now: NOW, from: NOW - 60 * DAY, objectives: [] };
    expect(pickZoom(long, 1100)).toBe("weeks");
    expect(pickZoom(d, 1100)).toBe("days");
    expect(pickZoom(d, 0)).toBe("days");
    const weeks = timeLayout({ ...long, cut: false }, [], { zoom: "weeks", width: 1100 });
    expect(weeks.day).toBeGreaterThanOrEqual(DAY_WIDTH.weeks.min);
    expect(weeks.fits).toBe(true);
  });

  it("le second défaut : aucun mot ni aucune barre ne commence avant le bord de la piste", () => {
    for (const zoom of ["days", "weeks"] as const) {
      const t = timeLayout(d, rows(d).rows, { zoom, width: 700 });
      for (const tr of t.tracks) {
        for (const b of tr.bars) expect(b.left).toBeGreaterThanOrEqual(0);
        if (tr.label >= 0) expect(tr.label).toBeGreaterThan(0);
        for (const p of tr.passes ?? []) expect(p.x).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("une flèche va d'un objectif à celui qui en dépend, et laisse le mot de sa barre lisible", () => {
    const all = rows(d).rows;
    const t = timeLayout(d, all, { zoom: "days", width: 0 });
    expect(t.arrows).toHaveLength(2);
    const goal1 = all.findIndex((r) => r.sort === "goal" && r.o.id === 1);
    const stop = t.tracks[goal1].bars[0].left + t.tracks[goal1].bars[0].width;
    expect(t.tracks[goal1].label).toBe(stop + 24);
    expect(arrowPath({ x1: 100, y1: 23, x2: 300, y2: 115 }).line).toBe("M102 23 h8 V115 H293");
    expect(arrowPath({ x1: 300, y1: 23, x2: 100, y2: 115 }).line.startsWith("M302 23 h10 V")).toBe(true);
  });

  it("une mission : son fil jusqu'à aujourd'hui, ses passages en points", () => {
    const all = rows(d).rows;
    const t = timeLayout(d, all, { zoom: "days", width: 0 });
    const track = t.tracks[all.findIndex((r) => r.sort === "mission")];
    expect(track.line).toBe(t.today);
    expect(track.passes).toHaveLength(4);
    expect(track.passes?.every((p) => p.x <= t.today)).toBe(true);
  });
});

// ── L'écran d'accord avec ce que l'API sert (ADR 0293) ───────────────

const ctx = (over: Partial<Ctx> = {}): Ctx => ({ now: NOW, mobile: false, ui: initialState(), me: "Adrien Moreau", ...over });
const got = <T>(value: T): { value: T; error: null } => ({ value, error: null });
const none = { value: null, error: null };
const RIGHTS = { steer: "modification", steer_label: "modification", detail: true, ticket: true, ticket_born: "open", note: true, status: true, settle: true, plan: true, pilot: true, links: true, approve: true, files: true, merge: true, frame: true, edit: true, pull_write: true, work: true };
const head = (over: Partial<ProjectHead> = {}): ProjectHead => ({ id: 3, title: "Outils réseau", status: "active", status_label: "actif", mine: true, hers: true, owner_name: "", steer: "modification", steer_label: "modification", detail: true,
  where: "Le module RDP se connecte.", last_run: NOW - 22 * MIN, plan: "planned", plan_label: "validé", waiting: 2, ...over });

describe("la grille : une carte se remplit de ce que la liste sert (`card`)", () => {
  const card = { objectives: { total: 4, done: 1, doing: 2, todo: 1, blocked: 0, states: [{ id: 1, state: "done", state_label: "fait" }, { id: 2, state: "doing", state_label: "en cours" }, { id: 4, state: "doing", state_label: "en cours" }, { id: 3, state: "todo", state_label: "à venir" }] },
    pulls_open: 2, tickets_open: 5, reads: [{ project: null, title: "", visible: false }], readers: [{ project: 5, title: "Faire <connaître>", visible: true }], led_by: "Mika", last_activity: NOW - 10 * MIN };
  const overview: Overview = { projects: [head({ card }), head({ id: 9, title: "Refonte", detail: false, mine: false, hers: false, owner_name: "Claire", where: "", last_run: 0, waiting: 0, card: null })], todo: [], todo_total: 0 };

  it("la progression, les compteurs, les dépendances, par qui il est mené, la dernière activité", () => {
    const html = gridView(overview, [], ctx());
    expect(html).toContain("à Mika · tu t&#39;en occupes · menée par Mika");
    expect(html).toContain("1 / 4 objectifs");
    expect(html).toContain('<i class="done"></i><i class="work"></i><i class="work"></i><i class="wait"></i>');
    expect(html).toContain("<b>2</b>pull requests");
    expect(html).toContain("<b>5</b>tickets ouverts");
    expect(html).toContain("Faire &lt;connaître&gt; en dépend");
    expect(html).toContain("dépend de un projet que tu ne vois pas");
    expect(html).toContain("il y a 10 min");
  });

  it("sans le détail (`card: null`) : ni barre, ni compteur de pull requests", () => {
    const html = gridView({ ...overview, projects: [overview.projects[1]] }, [], ctx());
    expect(html).not.toContain("p2-prog");
    expect(html).not.toContain("pull requests");
    expect(html).toContain("de Claire");
  });
});

describe("la Vue d'ensemble lit le prochain passage, le rythme, les consignes, le dernier commit", () => {
  const sheet = { project: { ...head(), description: "" }, rights: RIGHTS, todo: [], missions: [], objectives: [], lists: [{ name: "tickets", title: "Tickets", tickets: true, open: [], closed: [], counts: {}, total: 3, living: 2, actor: "self", actor_label: "elle",
      kinds: [], kind_default: "", priorities: [], priority_default: "", journey: [{ code: "unread", label: "Non lu", count: 1 }, { code: "analysis", label: "En analyse", count: 0 }, { code: "validation", label: "Validation", count: 1 }, { code: "pull", label: "Pull request", count: 0 }, { code: "merge", label: "Fusion", count: 1 }, { code: "treated", label: "Traité", count: 0 }] }],
    next: { at: NOW + 40 * MIN, state: "due", state_label: "son prochain passage est daté", sort: "run", sort_label: "du travail", objective: { id: 2, text: "Créer un module RDP", kind: "once" } },
    rhythm: { schedule: "toutes les 2 heures", window: "de 8 h à 20 h", summary: "Toutes les 2 heures, de 8 h à 20 h." },
    instructions: [{ seq: 9, at: NOW - 5 * MIN, text: "Commence par <le journal>.", veiled: false, author_kind: "you", author: "toi" }, { seq: 8, at: NOW - 9 * MIN, text: "Un texte d'un niveau que tu n'entends pas ici.", veiled: true, author_kind: "person", author: "une autre personne" }],
    repo: { has_remote: true, remote: "", branch: "main", flow: "pr", flow_label: "par pull request", auto_push: true, last_commit: "5c0de77a1b2c", remote_ok: true, remote_at: 0, remote_line: null,
      commit: { sha: "5c0de77a1b2c0000", short: "5c0de77", title: "rdp : journaliser <les refus>", at: NOW - 40 * MIN, author_kind: "self", author: "Mika", outside: false, branch: "objectif-2" } } } as unknown as Sheet;

  it("quand, sur quoi ; son rythme en une phrase ; ses consignes en attente", () => {
    const html = overviewView(sheet, ctx());
    expect(html).toContain("Prochain passage");
    expect(html).toContain("aujourd&#39;hui à 15:00");
    expect(html).toContain("du travail · Créer un module RDP");
    expect(html).toContain("Toutes les 2 heures, de 8 h à 20 h.");
    expect(html).toContain("Ta consigne : « Commence par &lt;le journal&gt;. »");
    expect(html).toContain("Consigne d&#39;une autre personne : Un texte d&#39;un niveau que tu n&#39;entends pas ici.");
    expect(html).not.toContain("Son rythme");
  });

  it("le moteur n'estime rien : sans date, ce que le serveur en dit", () => {
    expect(nextWhen({ at: 0, state: "on_demand", state_label: "à ta demande seulement", sort: "", sort_label: "", objective: null }, NOW)).toBe("à ta demande seulement");
    expect(nextAbout({ at: 0, state: "idle", state_label: "rien de prévu", sort: "", sort_label: "", objective: null })).toBe("");
  });

  it("le dernier commit avec son message et son instant ; les tickets par étape du parcours, comptés par le serveur", () => {
    const html = overviewView(sheet, ctx());
    expect(html).toContain("<code>5c0de77</code>");
    expect(html).toContain("rdp : journaliser &lt;les refus&gt;");
    expect(html).toContain("il y a 40 min");
    expect(html).toContain("Non lu<b>1</b>");
    expect(html).toContain("Fusion<b>1</b>");
    expect(html.match(/<li class="[^"]*"><i class="e\d"><\/i>/g)?.length).toBe(6);
  });
});

describe("Objectifs : les formulaires lisent ce que la fiche sert (`forms`)", () => {
  const forms = { can: true, why: "", triggers_max: 4,
    triggers: [{ key: "commit:7", label: "un commit de « Tableau <de bord> »", sort: "project", sort_label: "un projet dont il dépend", project: 7, title: "Tableau de bord" }, { key: "item:tickets", label: "un ticket bouge", sort: "item", sort_label: "une de ses listes", project: null, title: "" }],
    checks: [{ code: "prose", label: "Sa parole", help: "Elle dit l'avoir atteint, et comment.", fields: [] }, { code: "command", label: "Une commande", help: "Elle la lance.", fields: [{ name: "command", label: "Sa commande", help: "Telle qu'on la taperait.", required: true }] },
      { code: "owner", label: "Un point d'arrêt", help: "Tu valides.", fields: [] },
      { code: "item", label: "Un élément", help: "Un élément de son registre.", fields: [{ name: "item_list", label: "Liste de l'élément", help: "", required: true }, { name: "item", label: "Élément", help: "Sa clé, ou le numéro du ticket.", required: true }, { name: "item_status", label: "Statut attendu", help: "", required: true }] }] };
  const sheet = { project: { ...head(), description: "" }, rights: RIGHTS, todo: [], missions: [], objectives: [], forms,
    lists: [{ name: "tickets", title: "Tickets", tickets: true, open: [{ code: "unread", label: "non lu" }], closed: [{ code: "treated", label: "traité" }] }, { name: "entreprises", title: "Entreprises", tickets: false, open: [{ code: "a_contacter", label: "à contacter" }], closed: [] }] } as unknown as Sheet;

  it("ce qui peut déclencher une mission : les clés et les mots du serveur", () => {
    const html = goalDrawerBody(sheet, {});
    expect(html).toContain('name="on" value="commit:7"');
    expect(html).toContain("un commit de « Tableau &lt;de bord&gt; »");
    expect(html).toContain('name="on" value="item:tickets"');
    expect(html).toContain("4 au plus.");
    // sans `forms`, rien n'est proposé : aucune liste n'est écrite ici
    expect(goalDrawerBody({ ...sheet, forms: undefined } as Sheet, {})).not.toContain('name="on"');
  });

  it("les façons de vérifier un jalon, leurs mots et leurs champs", () => {
    const html = milestoneDrawerBody(sheet, null, {});
    for (const word of ["Sa parole", "Une commande", "Un point d&#39;arrêt", "Un élément", "Elle dit l&#39;avoir atteint, et comment.", "Sa commande", "Telle qu&#39;on la taperait.", "Statut attendu"]) expect(html).toContain(word);
    expect(html).toContain('data-si="check=command"');
    expect(html).toContain('data-si="check=item"');
    expect(html).toContain('<option value="entreprises"');
    expect(html).toContain("Entreprises · à contacter");
    expect(milestoneDrawerBody({ ...sheet, forms: undefined } as Sheet, null, {})).not.toContain('name="check"');
    // un jalon lié à un élément : ses champs reviennent remplis
    const m = { id: 4, text: "Trois contactées", check: "item", check_label: "un élément", status: "open", status_label: "à faire", ready: false, how: "", command: "", item_list: "entreprises", item: "atelier-brique", item_status: "a_contacter", item_status_label: "à contacter" } as unknown as Milestone;
    const edit = milestoneDrawerBody(sheet, m, {});
    expect(edit).toContain('name="item" value="atelier-brique"');
    expect(edit).toContain('<option value="entreprises" selected>');
  });

  it("un jalon : commencé, sa commande, ce qui le lie à un élément", () => {
    const m = { check: "item", check_label: "un élément", how: "", command: "", item_list: "tickets", item: "#4", item_status_label: "traité" } as unknown as Milestone;
    expect(verified(m, 3)).toBe('Vérifié par un élément · <a href="#projets/projets/3/tickets/4"><code>#4</code></a> doit être « traité »');
    expect(verified({ check: "command", check_label: "une commande", how: "Les trois tests passent.", command: "pytest -k <connect>" } as unknown as Milestone)).toBe("Vérifié par une commande · <code>pytest -k &lt;connect&gt;</code> — Les trois tests passent.");
    // sans le droit sur ses fichiers, la commande n'est pas servie : rien n'est mis à sa place
    expect(verified({ check: "command", check_label: "une commande", how: "", command: "" } as unknown as Milestone)).toBe("Vérifié par une commande");
    expect(milestoneState({ status: "open", status_label: "à faire", ready: false, refused_at: 0, started: true })).toContain('class="p2-st work"');
    expect(milestoneState({ status: "open", status_label: "à faire", ready: false, refused_at: 0, started: false })).toContain(">à faire<");
    expect(milestoneState({ status: "open", status_label: "à faire", ready: true, refused_at: 0, started: true })).toContain("prêt · à toi");
  });
});

describe("Tickets : le parcours en six étapes, servi (`journey`)", () => {
  const step = (code: string, label: string, state: string, state_label: string) => ({ code, label, state, state_label });
  const journey = (over: Partial<Journey> = {}): Journey => ({
    steps: [step("unread", "Non lu", "done", "passée"), step("analysis", "En analyse", "done", "passée"), step("validation", "Validation", "current", "en cours"), step("pull", "Pull request", "todo", "à venir"), step("merge", "Fusion", "todo", "à venir"), step("treated", "Traité", "todo", "à venir")],
    current: "validation", current_label: "Validation", fine: "validation", fine_label: "en attente de validation", through_pull: true, skips: [], skips_label: "", ended: "", ended_label: "", ...over });
  const ticket = (j: Journey | null, over: Partial<EntryDetail> = {}) => ({ journey: j, status: "validation", status_label: "en attente de validation", open: true, yours: true, hand_label: "au propriétaire", ...over }) as EntryDetail;

  it("six étapes, celle en cours marquée, l'étape fine en précision", () => {
    const html = steps(ticket(journey()));
    expect(html.match(/<li /g)?.length).toBe(6);
    expect(html.match(/class="fait"/g)?.length).toBe(2);
    expect(html).toContain('<li class="ici you" aria-current="step" title="en cours"><i>3</i><span>Validation</span><em>en attente de validation · la main est au propriétaire</em></li>');
  });

  it("un ticket qui ne produit pas de code saute la pull request et la fusion, et le dit", () => {
    const j = journey({ steps: [step("unread", "Non lu", "done", "passée"), step("analysis", "En analyse", "done", "passée"), step("validation", "Validation", "done", "passée"), step("pull", "Pull request", "skipped", "sautée"), step("merge", "Fusion", "skipped", "sautée"), step("treated", "Traité", "current", "en cours")],
      current: "treated", current_label: "Traité", fine: "working", fine_label: "validé, en cours", through_pull: false, skips: ["pull", "merge"], skips_label: "Ce ticket ne produit pas de code : il ne passe ni par une pull request ni par une fusion." });
    const html = steps(ticket(j, { status: "working", status_label: "validé, en cours", yours: false, hand_label: "à elle" }));
    expect(html.match(/class="saute"/g)?.length).toBe(2);
    expect(html).toContain("<em>sautée</em>");
    expect(html).toContain("<em>validé, en cours · la main est à elle</em>");
    expect(html).toContain("Ce ticket ne produit pas de code");
  });

  it("écarté : le mot du serveur, et les seules étapes qu'un fait dit passées ; pas un ticket : rien", () => {
    const j = journey({ steps: [step("unread", "Non lu", "done", "passée"), ...["analysis", "validation", "pull", "merge", "treated"].map((c) => step(c, c, "todo", "à venir"))], current: "", current_label: "", fine: "dismissed", fine_label: "écarté", ended: "dismissed", ended_label: "écarté" });
    const html = steps(ticket(j, { status: "dismissed", status_label: "écarté", open: false, yours: false }));
    expect(html).toContain('class="p2-ecarte"');
    expect(html).toContain("écarté");
    expect(html).not.toContain("aria-current");
    expect(steps(ticket(null))).toBe("");
  });

  it("l'Historique : l'histoire de ses étapes, et ce qui est arrivé à ses objectifs, dans le temps", () => {
    const passage = (seq: number, min: number, status: string, status_label: string, was: string, was_label: string, stepCode: string, author: string, outside = false) => ({ seq, at: NOW - min * MIN, status, status_label, was, was_label, step: stepCode, step_label: stepCode, author_kind: "self", author, outside });
    const history: EntryHistory = { item: "#3", cut: false, items: [passage(1, 600, "unread", "non lu", "", "", "unread", "toi"), passage(2, 500, "analysis", "en analyse", "unread", "non lu", "analysis", "Mika"), passage(5, 100, "pr_ready", "prête à fusionner", "pr_pending", "pull request en cours", "merge", "<Mika>")] };
    const line = (seq: number, min: number, kind: string, title: string) => ({ seq, at: NOW - min * MIN, kind, kind_label: kind, what: "", title, sub: "", objective: 4, ticket: 3, pull: kind === "pull" ? 11 : 0, sha: kind === "commit" ? "91be02f4c1d0" : "", verdict: "", verdict_label: "", run: "", author_kind: "self", author: "Mika", outside: false });
    const around = { kinds: [], size: 40, next: 0, items: [line(4, 300, "pull", "Pull request n° 11 ouverte"), line(3, 400, "commit", "Un commit <laissé>"), line(6, 90, "ticket", "Le ticket #3 change d'étape"), line(7, 80, "gesture", "Tu as validé son plan")] } as ActivityPage;
    const html = historyPane(3, { history: got(history), around: got(around) }, ctx());
    const order = ["Ouvert par toi — non lu", "En analyse — par Mika", "Un commit &lt;laissé&gt;", "Pull request n° 11 ouverte", "Prête à fusionner — par &lt;Mika&gt;"].map((x) => html.indexOf(x));
    expect(order.every((x) => x >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain('href="#projets/projets/3/code/pulls/11"');
    // ce que le fil redit d'un passage n'y est pas deux fois
    expect(html).not.toContain("change d&#39;étape");
    expect(html).not.toContain("Tu as validé son plan");
    expect(historyPane(3, { history: got({ ...history, cut: true }), around: none }, ctx())).toContain("trop longue");
  });
});

describe("À faire : un accord dit ce qu'il concerne, où il part et pourquoi", () => {
  it("le ticket et l'issue concernés, où cela part, les mots de qui l'a demandé", () => {
    const w = waiting({ kind: "approval", kind_label: "accord", what: "issue_comment", about: "Répondre sur l'issue n° 9", number: 0, gesture: { route: "accord", args: { proposal: 41 }, label: "Lire et décider", where: "ici", url: "" } });
    const accord = { id: 41, project: 3, project_title: "Outils réseau", capability: "issue_comment", label: "Répondre sur une issue", summary: "Une réponse à netfan42.", text: "Merci du signalement.", digest: "abc", blocked: "", at: NOW - 6 * MIN,
      concerns: { objective: 0, ticket: { number: 6, handle: "#6", title: "Le scan <s'arrête>", veiled: "", veiled_label: "", status: "proposed", status_label: "proposé", step: "unread", step_label: "Non lu", open: true }, issue: 9, pull: 0 },
      where: "chez l'hôte du dépôt, dans ses issues", where_url: "https://github.com/exemple/outils-reseau/issues/9", asked_by_kind: "self", asked_by: "Mika", why: "Pour <rassurer> netfan42." };
    const overview: Overview = { projects: [head()], todo: [w], todo_total: 1 };
    const html = todoView({ overview, todo: [w], sheet: none, approvals: got({ items: [accord] }), element: none }, 3, "accord-41", ctx());
    expect(html).toContain("<dt>Où</dt><dd>chez l&#39;hôte du dépôt, dans ses issues");
    expect(html).toContain('href="https://github.com/exemple/outils-reseau/issues/9"');
    expect(html).toContain("<dt>Pourquoi</dt><dd>Pour &lt;rassurer&gt; netfan42.</dd>");
    expect(html).toContain("par Mika");
    expect(html).toContain('href="#projets/projets/3/tickets/6"');
    expect(html).toContain("Le scan &lt;s&#39;arrête&gt;");
    expect(html).toContain('href="#projets/projets/3/code/issues/9"');
    // une adresse qui n'est pas http(s) ne devient jamais un lien ; sans mot, pas de « Pourquoi »
    const bare = todoView({ overview, todo: [w], sheet: none, approvals: got({ items: [{ ...accord, where_url: "javascript:alert(1)", why: "" }] }), element: none }, 3, "accord-41", ctx());
    expect(bare).not.toContain("javascript:");
    expect(bare).not.toContain("<dt>Pourquoi</dt>");
  });
});

describe("Dépendances : par lien, depuis quand, pourquoi, le commit, les demandes dans les deux sens", () => {
  const gives = { see: true, detail: true, files: true, docs: false, ask: "proposed", ask_label: "ses demandes sont proposées à son propriétaire" };
  const demand = (over: Partial<Demand>): Demand => ({ project: 3, title: "Exposer les hôtes en JSON", visible: true, direction: "sent", from: "project", number: 9, veiled: false, status: "analysis", status_label: "en analyse", step: "analysis", step_label: "En analyse", at: NOW - 90 * MIN, closed_at: 0, ...over });
  const yours = demand({ from: "you", number: 12, title: "Ajouter un <export>", status: "proposed", status_label: "proposé", step: "unread", step_label: "Non lu", at: NOW - 30 * MIN });
  const links = { can: true, plan_asks: [], candidates: [], labels: { title: "Dépendances", reads: "Il dépend de", readers: "Dépendent de lui", asks: "Ses demandes" },
    reads: [{ project: 3, title: "Outils réseau", visible: true, suspended: false, direct: false, gives, since: new Date(2026, 9, 28).getTime(), why: "Pour citer ses <commandes> sans les inventer.",
      commit: { sha: "5c0de77a1b2c", short: "5c0de77", title: "rdp : journal", at: NOW - 40 * MIN }, asks: [demand({}), yours], ask_here: { can: true, why: "", born: "proposed", project: 3, route: "ticket" } },
      { project: null, title: "", visible: false, suspended: false, direct: false, gives, since: 0, why: "", commit: null, asks: [], ask_here: { can: false, why: "", born: "", project: null, route: "" } }],
    readers: [{ project: 7, title: "Tableau de bord", visible: true, gives, since: 0, why: "", asks: [demand({ project: 7, direction: "received", number: 4, title: "", veiled: true })] }],
    asks: [demand({})], received: [demand({ project: 7, direction: "received", number: 4, title: "", veiled: true })] } as unknown as Links;
  const sheet = { project: { ...head({ id: 5, title: "Faire connaître" }), description: "" }, rights: RIGHTS, todo: [], objectives: [], lists: [], links } as unknown as Sheet;

  it("le nœud et le panneau d'un lien", () => {
    const html = dependenciesView(sheet, null, ["lit-3"], ctx());
    expect(html).toContain("Pour citer ses &lt;commandes&gt; sans les inventer.");
    expect(html).toContain("depuis le 28 oct.");
    expect(html).toContain("<code>5c0de77</code>");
    expect(html).toContain("rdp : journal");
    expect(html).toContain("2 demandes");
    expect(html).toContain("Exposer les hôtes en JSON");
    expect(html).toContain("Ajouter un &lt;export&gt;");
    expect(html).toContain("ouverte par toi");
    expect(html).toContain('data-p2="askHere" data-p="5" data-c="3"');
    // ce qu'un lien donne se lit, sans se cocher : aucune case que rien n'enregistrerait
    expect(html).toContain('class="p2-dons lecture"');
    expect(html).not.toMatch(/<input type="checkbox"[^>]*disabled/);
  });

  it("un projet qu'elle ne voit pas : ni nom, ni mot, ni « Lui demander quelque chose »", () => {
    const html = dependenciesView(sheet, null, ["lit-x1"], ctx());
    expect(html).toContain("un projet que tu ne vois pas");
    expect(html.split('class="p2-side ')[1]).not.toContain('data-p2="askHere"');
    expect(html.split('class="p2-side ')[1]).not.toContain('data-p2="linkRemove"');
  });

  it("les demandes : envoyées, reçues, et ses tickets à elle chez un projet lu ; une clé par demande", () => {
    const all = allDemands(links);
    expect(all.map(demandKey)).toEqual(["toi-3-12", "envoyee-3-9", "recue-7-4"]);
    const html = dependenciesView(sheet, null, ["demandes", "recue-7-4"], ctx());
    expect(html).toContain("Demande reçue");
    expect(html).toContain("Une demande que tu ne lis pas");
    expect(html).toContain("de « Tableau de bord »");
    expect(html).toContain('href="#projets/projets/5/tickets/4"');
    expect(html).toContain("Nouvelle demande");
    const mine = dependenciesView(sheet, null, ["demandes", "toi-3-12"], ctx());
    expect(mine).toContain("Ton ticket chez lui");
    expect(mine).toContain("pas une demande de « Faire connaître »");
    expect(mine).toContain('href="#projets/projets/3/tickets/12"');
  });
});

describe("Listes : ajouter un élément, changer à qui il est, quand la liste le dit", () => {
  const list = (can: Listing["can"]): Listing => ({ name: "entreprises", title: "Entreprises", tickets: false, open: [{ code: "a_contacter", label: "à contacter" }], closed: [{ code: "sans_suite", label: "sans suite" }], counts: { a_contacter: 1 }, total: 1, living: 1,
    actor: "self", actor_label: "elle", kinds: [], kind_default: "", priorities: [], priority_default: "", can, actors: [{ code: "self", label: "elle" }, { code: "owner", label: "le propriétaire" }] });
  const page = got({ list: "entreprises", total: 1, page: 1, size: 100, items: [{ list: "entreprises", handle: "", number: 0, key: "atelier-brique", title: "Atelier Brique", veiled: "", veiled_label: "", status: "a_contacter", status_label: "à contacter", open: true, hand: "", hand_label: "", yours: false,
    kind: "", kind_label: "", priority: "", priority_label: "", actor: "owner", actor_label: "le propriétaire", author_kind: "self", author: "Mika", outside: false, objective: 0, notes: 0, at: NOW, updated_at: NOW, plan: 0, issue: 0, pull: 0 }] });
  const sheetOf = (can: Listing["can"]) => ({ project: { ...head({ id: 5 }), description: "" }, rights: RIGHTS, todo: [], lists: [list(can)] }) as unknown as Sheet;

  it("les boutons suivent `can` de la liste ; les choix sont ceux qu'elle sert", () => {
    const open = listsView(sheetOf({ add: true, assign: true, why: "" }), ["entreprises"], page, ctx());
    expect(open).toContain('data-p2="itemAdd" data-p="5" data-l="entreprises"');
    expect(open).toContain('data-p2="itemAssign" data-p="5" data-l="entreprises" data-c="atelier-brique"');
    const closed = listsView(sheetOf({ add: false, assign: false, why: "Tu le pilotes sur accord." }), ["entreprises"], page, ctx());
    expect(closed).not.toContain('data-p2="itemAdd"');
    expect(closed).not.toContain('data-p2="itemAssign"');
    const body = itemDrawerBody(list({ add: true, assign: true, why: "" }));
    expect(body).toContain('<option value="owner">le propriétaire</option>');
    expect(body).toContain('<option value="a_contacter" selected>à contacter</option>');
  });
});

describe("Modifier le projet : chaque champ suit `can` et `why` du serveur", () => {
  const why = "Ce réglage ouvre autre chose que ce projet : il est à qui s'occupe d'elle.";
  const field = (name: string, label: string, kind: string, value: unknown, can = true): Field => ({ name, label, help: "", kind, required: false, choices: [], value, can, why: can ? "" : why });
  const settings = (over = {}) => got({ can: true, why: "", renamable: true, archive: { can: true, why: "" }, sections: [
    { name: "outils", title: "Outils et services", summary: "2 outils", can: true, why: "", fields: [field("tool_web", "Le web", "bool", true), field("tool_email", "Le courrier", "bool", false, false)] },
    { name: "depot", title: "Dépôt", summary: "par pull request", can: false, why, fields: [field("remote", "Son dépôt distant", "text", "github.com/x/y", false)] }], ...over });
  const sheet = { project: { ...head(), description: "" }, rights: RIGHTS, todo: [] } as unknown as Sheet;

  it("un champ réservé se montre verrouillé avec sa raison ; les autres se changent", () => {
    const html = settingsView(sheet, settings(), ["outils"], {}, ctx());
    expect(html).toMatch(/<input disabled type="checkbox" name="tool_email">/);
    expect(html).toMatch(/<input type="checkbox" name="tool_web" checked>/);
    expect(html).toContain("Ce réglage ouvre autre chose que ce projet");
    expect(html).toContain('type="submit"');
  });

  it("une section dont rien ne se change : pas de bouton, et pourquoi", () => {
    const html = settingsView(sheet, settings(), ["depot"], {}, ctx());
    expect(html).toMatch(/<input disabled name="remote"/);
    expect(html).not.toContain('type="submit"');
    expect(html.split("p2-form-foot")[1]).toContain("Ce réglage ouvre autre chose que ce projet");
  });

  it("un projet qu'elle a ouvert d'elle-même ne se renomme pas : son nom est verrouillé", () => {
    const html = settingsView(sheet, got({ can: true, why: "", renamable: false, archive: { can: true, why: "" }, sections: [{ name: "general", title: "Général", summary: "", can: true, why: "", fields: [field("title", "Son nom", "text", "Outils réseau"), field("description", "Sa description", "textarea", "")] }] }), ["general"], {}, ctx());
    expect(html).toMatch(/<input disabled name="title"/);
    expect(html).toContain("ne se renomme pas");
    expect(html).toMatch(/<textarea name="description"/);
  });
});
