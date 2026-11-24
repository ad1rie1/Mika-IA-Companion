import { readdirSync, readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it } from "vitest";

/**
 * Rien ne se relit à intervalles (ADR 0308) : ce qui change est poussé par le direct (`src/live/`, `protocole-moi.md`
 * § 2 bis), et l'écran relit alors la route qu'il montre. Cette garde lit les sources de `src/` par TypeScript lui-même
 * (l'arbre du code, jamais un motif : un commentaire qui nomme `setInterval` ne compte pas), tests exceptés :
 *
 * - tout `setInterval` est dans la liste `INTERVALS`, avec sa raison ;
 * - tout `setTimeout` dont le rappel lance une lecture (un appel nommé `load…`, `refresh…`, `ensure`, `tick`, `poll…`,
 *   `fetch…`, `search…`, `suggest…`, `look…`, `read…`, `reread…`, `relive`, ou une lecture à la fois relancée —
 *   `this.listRead.run()`, `reading.run()`), ou qui fait attendre — posé dans une boucle, ou dans un `new Promise` (la
 *   pause qu'on attend avant de relire, `await new Promise((r) => setTimeout(r, ms))`) —, est dans la liste
 *   `TIMEOUTS`, avec sa raison : une pause de la saisie, une lecture unique au démarrage, ce qui attend un tiers que
 *   rien du journal ne dit.
 *
 * Chaque minuterie se désigne par son fichier et la déclaration qui la contient (sa méthode, sa fonction, sa
 * propriété) ; chaque exception en admet une seule : les listes disent exactement ce qui existe — une minuterie
 * ajoutée (même à côté d'une admise), ou une exception qui ne sert plus, fait échouer la garde.
 */
const SRC = new URL("../src/", import.meta.url);

/** Les `setInterval` admis : ce ne sont pas des relectures. */
const INTERVALS: Record<string, string> = {
  "mika/work.ts › tickWork": "le chrono de « elle s'y met » : un affichage d'ici, entre deux étapes poussées (ADR 0306), sans rien relire",
  "shell/ages.ts › start": "les âges affichés (« il y a 3 min », « relevée il y a », l'extension Teams) repeints d'ici toutes les 30 s, sans rien relire",
};

/** Les `setTimeout` qui lancent une lecture, admis. */
const TIMEOUTS: Record<string, string> = {
  "screens/carte/events.ts › mapMoved": "la carte a bougé : la recherche, après une pause",
  "screens/carte/events.ts › mount": "la recherche, après une pause de la saisie",
  "screens/carte/explorer.ts › mapMoved": "la carte a bougé : la recherche, après une pause",
  "screens/carte/explorer.ts › search": "après « Autour de moi », les notes que le serveur précharge d'un service extérieur arrivent : une relecture, une fois (rien du journal ne le dit)",
  "screens/carte/explorer.ts › findAddresses": "les adresses, après une pause de la saisie",
  "screens/carte/explorer.ts › mount": "la recherche, après une pause de la saisie",
  "screens/carte/itinerary.ts › suggest": "les adresses d'un point, après une pause de la saisie",
  "screens/carte/itinerary.ts › mount": "les lieux proposés pour un point, après une pause de la saisie",
  "screens/carte/requests.ts › want": "le trajet d'un voyage, une fois ses arrêts immobiles après tes gestes (un calcul du serveur, borné par compte)",
  "screens/agenda/index.ts › mount": "la recherche dans tes agendas, après une pause de la saisie",
  "screens/contacts/index.ts › constructor": "la palette (Ctrl K) : une lecture, une fois, peu après le démarrage",
  "screens/contacts/index.ts › mount": "la recherche, après une pause de la saisie",
  "screens/mail/compose.ts › bindRecipients": "les destinataires proposés, après une pause de la saisie",
  "screens/mail/mail.ts › mount": "la recherche, après une pause de la saisie",
  "screens/outils/index.ts › constructor": "la palette (Ctrl K) : une lecture, une fois, peu après le démarrage",
  "screens/parametres/account.ts › submit": "le mot de passe changé, ses sessions fermées : la page se recharge une fois (la connexion), le temps de lire le toast",
  "screens/parametres/mail.ts › followSignin": "la connexion Microsoft d'une boîte neuve, dans sa fenêtre : son code attend Microsoft, et `save_mail_grant` ne passe pas par le journal (rien n'est poussé)",
  "screens/parametres/mail.ts › tick": "la connexion Microsoft d'une boîte : son code attend Microsoft, qui ne passe pas par le journal (rien n'est poussé)",
  "screens/parametres/mail.ts › watchSignin": "la connexion Microsoft d'une boîte : son code attend Microsoft, qui ne passe pas par le journal (rien n'est poussé)",
  "screens/telephone/index.ts › constructor": "la palette (Ctrl K) : une lecture, une fois, peu après le démarrage",
  "screens/teams/teams.ts › mount": "la recherche, après une pause de la saisie",
};

/** Un appel qui lit : `load`, `loadList`, `refresh`, `fetchContacts`, `search`, `relive`… (le mot, puis rien ou une
 *  majuscule). */
const READS = /^(load|reload|reread|refresh|relive|ensure|tick|poll|fetch|search|suggest|look|read)([A-Z]|$)/;

function nameOf(node: ts.Node): string | null {
  if (ts.isConstructorDeclaration(node)) return "constructor";
  if ((ts.isMethodDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isPropertyDeclaration(node) ||
    ts.isPropertyAssignment(node) || ts.isVariableDeclaration(node) || ts.isGetAccessorDeclaration(node)) && node.name &&
    (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))) return node.name.text;
  return null;
}

/** La déclaration qui contient ce nœud : sa méthode, sa fonction, sa propriété, sa variable. */
function owner(node: ts.Node): string {
  for (let n: ts.Node | undefined = node.parent; n; n = n.parent) {
    const name = nameOf(n);
    if (name) return name;
  }
  return "(module)";
}

/** `setTimeout(…)`, `window.setTimeout(…)`, `globalThis.setTimeout(…)` : le nom de la minuterie, ou rien. */
function timerOf(call: ts.CallExpression): "setInterval" | "setTimeout" | null {
  const callee = call.expression;
  const name = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : "";
  return name === "setInterval" || name === "setTimeout" ? name : null;
}

/** Le nom d'un appel (`this.loadList(…)` → `loadList`, `fetchContacts(…)` → `fetchContacts`). */
function calleeName(call: ts.CallExpression): string {
  const callee = call.expression;
  if (ts.isIdentifier(callee)) return callee.text;
  if (ts.isPropertyAccessExpression(callee)) return callee.name.text;
  return "";
}

/** `this.listRead.run`, `reading.run` : une lecture à la fois (`OneAtATime`, `live/live.ts`) qu'on relance. */
function runsRead(callee: ts.Expression): boolean {
  if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== "run") return false;
  const target = callee.expression;
  const name = ts.isIdentifier(target) ? target.text : ts.isPropertyAccessExpression(target) ? target.name.text : "";
  return /read/i.test(name);
}

/** Le rappel d'une minuterie lance-t-il une lecture ? Une fonction écrite là (un appel qui lit, à n'importe quelle
 *  profondeur), ou une fonction nommée qui lit. */
function reads(callback: ts.Expression | undefined): boolean {
  if (!callback) return false;
  if (ts.isIdentifier(callback) || ts.isPropertyAccessExpression(callback)) {
    return READS.test(ts.isIdentifier(callback) ? callback.text : callback.name.text) || runsRead(callback);
  }
  let found = false;
  const visit = (n: ts.Node): void => {
    if (found) return;
    if (ts.isCallExpression(n) && (READS.test(calleeName(n)) || runsRead(n.expression))) found = true;
    else ts.forEachChild(n, visit);
  };
  visit(callback);
  return found;
}

/** La minuterie fait-elle attendre ? Posée dans une boucle (jusqu'à la fonction qui la contient), ou dans un
 *  `new Promise` — la pause qu'on attend (`await new Promise((r) => setTimeout(r, ms))`), d'ordinaire avant de relire :
 *  son rappel (`r`) ne dit pas ce qui suit. */
function waits(call: ts.CallExpression): boolean {
  for (let n: ts.Node | undefined = call.parent; n; n = n.parent) {
    if (ts.isIterationStatement(n, false)) return true;
    if (ts.isFunctionLike(n)) {
      const outer = n.parent;
      return !!outer && ts.isNewExpression(outer) && ts.isIdentifier(outer.expression) && outer.expression.text === "Promise";
    }
  }
  return false;
}

interface Timer {
  where: string;
  kind: "setInterval" | "setTimeout";
  reads: boolean;
}

/** Les minuteries d'une source : où chacune est, et si elle relit (ou fait attendre). */
function timersIn(file: string, text: string): Timer[] {
  const out: Timer[] = [];
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      const kind = timerOf(n);
      if (kind) out.push({ where: `${file.split("\\").join("/")} › ${owner(n)}`, kind, reads: reads(n.arguments[0]) || waits(n) });
    }
    ts.forEachChild(n, visit);
  };
  visit(source);
  return out;
}

function timers(): Timer[] {
  const out: Timer[] = [];
  for (const file of readdirSync(SRC, { recursive: true, encoding: "utf8" })) {
    if (!file.endsWith(".ts") || file.endsWith(".test.ts")) continue;
    out.push(...timersIn(file, readFileSync(new URL(file, SRC), "utf8")));
  }
  return out;
}

describe("rien ne se relit à intervalles (ADR 0308)", () => {
  const all = timers();

  it("la lecture voit bien les minuteries (sans elles, la garde passerait sur une liste vide)", () => {
    expect(all.some((t) => t.kind === "setInterval")).toBe(true);
    expect(all.filter((t) => t.kind === "setTimeout").length).toBeGreaterThan(20);
  });

  it("elle voit ce qui relit sans le nommer : une pause attendue dans une boucle, une lecture à la fois relancée, `relive`", () => {
    const text = `
      // setTimeout(() => this.load(), 1000) dans un commentaire ne compte pas
      class X {
        async poll() { for (let i = 0; i < 10; i++) { await this.get(); await new Promise((r) => window.setTimeout(r, 2000)); } }
        sleep() { return new Promise((r) => setTimeout(r, 50)); }
        loop() { while (this.on) { setTimeout(() => this.draw(), 10); } }
        later() { window.setTimeout(() => void this.listRead.run(), 500); }
        again() { setTimeout(() => this.relive(), 500); }
        byName() { setTimeout(this.reading.run, 500); }
        pause() { this.timer = window.setTimeout(() => this.paint(), 300); }
        handlers() { for (const el of this.els) el.addEventListener("input", () => { this.t = setTimeout(() => this.paint(), 300); }); }
      }`;
    const found = timersIn("x.ts", text);
    expect(found.filter((t) => t.reads).map((t) => t.where)).toEqual(["x.ts › poll", "x.ts › sleep", "x.ts › loop", "x.ts › later", "x.ts › again", "x.ts › byName"]);
    expect(found.filter((t) => !t.reads).map((t) => t.where)).toEqual(["x.ts › pause", "x.ts › handlers"]);
  });

  it("aucun setInterval hors de la liste, et chaque exception de la liste sert encore", () => {
    const found = all.filter((t) => t.kind === "setInterval").map((t) => t.where).sort();
    expect(found).toEqual(Object.keys(INTERVALS).sort());
  });

  it("aucun setTimeout qui relit hors de la liste, et chaque exception de la liste sert encore", () => {
    const found = all.filter((t) => t.kind === "setTimeout" && t.reads).map((t) => t.where).sort();
    expect(found).toEqual(Object.keys(TIMEOUTS).sort());
  });

  it("chaque exception dit sa raison", () => {
    for (const [where, why] of Object.entries({ ...INTERVALS, ...TIMEOUTS })) expect(why.length, where).toBeGreaterThan(20);
  });
});
