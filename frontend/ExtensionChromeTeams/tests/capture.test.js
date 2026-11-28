"use strict";
// Le script de la page tel quel (`page/capture.js` et ses bibliothèques, comme Chrome les charge dans le monde MAIN),
// avec un faux `Worker` et un faux relais : l'envoi par le worker de Teams (ADR 0301). La commande de la page passe
// telle quelle, son modèle part au service sans rien du message ; un envoi part d'abord par le worker, et seul un refus
// explicite laisse la voie suivante ; sans réponse, l'issue est douteuse et rien n'est renvoyé.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const nodeCrypto = require("node:crypto");
const P = require("../lib/page.js");
const F = require("./worker-fixture.js");

const ROOT = path.join(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"));
const MAIN = manifest.content_scripts.find((e) => e.world === "MAIN").js;
const SCALE = 100; // les délais de la page, cent fois plus courts (10 s de silence du worker : 100 ms)
const plain = (v) => JSON.parse(JSON.stringify(v));

/**
 * Une page Teams avec le script : `service(what, payload)` répond aux demandes au service (par le relais) ; rend les
 * messages postés au relais (`posted`), de quoi créer un worker de la page, lui faire répondre, et demander un envoi.
 */
function page({ service } = {}) {
  const listeners = [];
  const posted = [];
  const workers = [];
  class FakeWorker {
    constructor(url) {
      this.url = String(url);
      this.received = [];
      this.listeners = [];
      workers.push(this);
    }
    addEventListener(type, fn) { if (type === "message") this.listeners.push(fn); }
    postMessage(data) { this.received.push(data); }
    terminate() { this.terminated = true; }
  }
  class FakeSocket {}
  class FakeXhr {}
  FakeXhr.prototype.open = function () {};
  FakeXhr.prototype.send = function () {};
  FakeXhr.prototype.setRequestHeader = function () {};
  const loose = (fn, ms) => {
    const t = setTimeout(fn, Math.ceil((Number(ms) || 0) / SCALE));
    if (t && typeof t.unref === "function") t.unref();
    return t;
  };
  const storage = { length: 0, key: () => null, getItem: () => null };
  const ctx = {
    location: { origin: "https://teams.cloud.microsoft", href: "https://teams.cloud.microsoft/v2/", pathname: "/v2/" },
    document: { addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [],
      visibilityState: "visible", activeElement: null },
    sessionStorage: storage, localStorage: storage,
    Worker: FakeWorker, WebSocket: FakeSocket, XMLHttpRequest: FakeXhr, fetch: async () => ({}),
    crypto: { randomUUID: () => nodeCrypto.randomUUID(), getRandomValues: (a) => nodeCrypto.getRandomValues(a) },
    MutationObserver: class { observe() {} }, KeyboardEvent: class {}, URL,
    setTimeout: loose, clearTimeout, setInterval: () => 0, clearInterval: () => {},
    addEventListener: (type, fn) => { if (type === "message") listeners.push(fn); },
    postMessage: (data) => {
      const d = plain(data);
      posted.push(d);
      // le relais et le service : chaque demande a sa réponse
      if (d.kind === "ask") {
        const answer = (service && service(d.what, d.payload)) || { ok: d.what !== "cursors", data: {} };
        setImmediate(() => toPage({ kind: "answer", nonce: d.nonce, ok: answer.ok, data: answer.data }));
      }
    },
  };
  vm.createContext(ctx);
  // la page se reconnaît à `event.source === window` : son propre objet global, vu du dedans
  const win = vm.runInContext("globalThis", ctx);
  ctx.window = win;
  for (const js of MAIN) vm.runInContext(fs.readFileSync(path.join(ROOT, js), "utf8"), ctx, { filename: js });
  function toPage(data) {
    listeners.forEach((fn) => fn({ source: win, data: Object.assign({ __mika: "mika-teams", dir: "in" }, data) }));
  }
  let n = 0;
  /** Demande un envoi à la page, comme le relais ; rend son issue. */
  function send(item) {
    const nonce = "s" + ++n;
    toPage({ kind: "send", nonce, item: { selfName: "Adrien Martin", ...item }, deadline: Date.now() + 1500 });
    return waitFor(() => posted.find((d) => d.kind === "sendResult" && d.nonce === nonce)).then((d) => d.result);
  }
  function diagnose() {
    toPage({ kind: "diagnose", nonce: "d" + ++n });
    const nonce = "d" + n;
    return waitFor(() => posted.find((d) => d.kind === "report" && d.nonce === nonce)).then((d) => d.report);
  }
  return { ctx, posted, workers, send, diagnose, worker: (url) => new ctx.Worker(url || "precompiled-web-worker.js"),
    asks: (what) => posted.filter((d) => d.kind === "ask" && d.what === what) };
}

async function waitFor(fn, ms = 2000) {
  const end = Date.now() + ms;
  for (;;) {
    const got = fn();
    if (got) return got;
    if (Date.now() > end) throw new Error("rien vu à temps");
    await new Promise((done) => setTimeout(done, 2));
  }
}

const settle = () => new Promise((done) => setTimeout(done, 20));

/** Le worker répond (en texte JSON, comme le Teams d'aujourd'hui, ou en objet). */
function answer(worker, data, asText = true) {
  for (const fn of worker.listeners) fn({ data: asText ? JSON.stringify(data) : data });
}

/** La commande que l'extension a passée au worker après les `before` premières (la page compte aussi). */
async function ownCommand(worker, before) {
  await waitFor(() => worker.received.length > before);
  const raw = worker.received[before];
  assert.equal(typeof raw, "string", "en texte JSON : un objet serait ignoré");
  return JSON.parse(raw);
}

/** Une page où l'on a envoyé une fois à la main (le modèle est pris), puis où la page a fait d'autres requêtes. */
async function readyPage(opts) {
  const p = page(opts);
  const w = p.worker();
  w.postMessage(JSON.stringify(F.autoSend()));
  w.postMessage(JSON.stringify(F.query(500)));
  await waitFor(() => p.asks("sendTemplate").length);
  return { p, w };
}

test("la commande de la page passe au worker telle quelle ; son modèle part au service sans rien du message", async () => {
  const p = page();
  const w = p.worker();
  const raw = JSON.stringify(F.autoSend());
  w.postMessage(raw);
  assert.deepEqual(w.received, [raw], "la page envoie ce qu'elle envoie, rien de plus, rien de changé");
  const ask = await waitFor(() => p.asks("sendTemplate")[0]);
  assert.equal(ask.payload.bilateral, true);
  const json = JSON.stringify(ask.payload);
  for (const trace of [F.ALBERT, F.TEXT, F.CLIENT_ID, F.CORRELATION, F.RENDERER, "m-412"]) {
    assert.equal(json.includes(trace), false, "« " + trace + " » est parti au service");
  }
  // le même envoi redit ne fait pas réécrire le modèle ; un objet passé au worker n'est pas lu
  w.postMessage(JSON.stringify(F.autoSend({ request: 413, content: "<p><semantic-object>autre</semantic-object></p>" })));
  w.postMessage(F.autoSend({ request: 414 }));
  await settle();
  assert.equal(p.asks("sendTemplate").length, 1);
  assert.equal(w.received.length, 3);
});

test("un envoi part par le worker : la commande rejouée en texte JSON, « envoyé » à sa réponse", async () => {
  const { p, w } = await readyPage();
  const before = w.received.length;
  const result = p.send({ id: "t0123456789ab", conversation: F.GROUP, text: "Bonjour à tous\n— Mika" });
  const sent = await ownCommand(w, before);
  assert.equal(sent.requestId, "m-1500", "au-dessus du compteur de la page (500)");
  assert.equal(sent.rendererId, F.RENDERER);
  assert.equal(sent.windowId, F.WINDOW);
  const v = sent.payload.variables;
  assert.equal(v.convId, F.GROUP);
  assert.equal(v.isBilateralChat, false);
  assert.equal(v.message.clientMessageId, P.clientMessageIdFor("t0123456789ab"), "le même à chaque tentative");
  assert.equal(v.message.content, "<p><semantic-object>Bonjour à tous<br>— Mika</semantic-object></p>");
  assert.match(v.correlationId, /^[0-9a-f-]{36}$/);
  assert.ok(p.posted.some((d) => d.kind === "sendStarted"));
  answer(w, F.reply("m-1499")); // une autre réponse ne tranche rien
  answer(w, F.reply("m-1500"));
  assert.deepEqual(await result, { result: "sent", via: "worker", message_id: "1763900000123" });
  const report = await p.diagnose();
  assert.equal(report.compose.sentByWorker, 1);
  assert.equal(report.compose.workerSendPossible, true);
  assert.ok(report.compose.workerTemplates.bilateral > 0);
  assert.equal(report.compose.workerTemplates.group, 0);
});

test("une réponse du worker passée en objet tranche aussi", async () => {
  const { p, w } = await readyPage();
  const before = w.received.length;
  const result = p.send({ id: "t00000000000a", conversation: F.ALBERT, text: "ok" });
  const sent = await ownCommand(w, before);
  answer(w, F.reply(sent.requestId), false);
  assert.equal((await result).result, "sent");
});

test("sans réponse du worker : l'issue est douteuse, et l'élément n'est jamais renvoyé d'ici", async () => {
  const { p, w } = await readyPage();
  const before = w.received.length;
  const result = await p.send({ id: "t0123456789ac", conversation: F.ALBERT, text: "tu es là ?" });
  assert.equal(result.result, "uncertain");
  assert.match(result.reason, /pas répondu/);
  assert.equal(w.received.length, before + 1, "une seule commande");
  const again = await p.send({ id: "t0123456789ac", conversation: F.ALBERT, text: "tu es là ?" });
  assert.equal(again.result, "uncertain");
  assert.match(again.reason, /déjà commencé/);
  assert.equal(w.received.length, before + 1, "jamais deux envois");
  // la réponse arrive enfin : comptée, sans rien changer
  answer(w, F.reply(JSON.parse(w.received[before]).requestId));
  const report = await p.diagnose();
  assert.equal(report.compose.workerSilent, 1);
  assert.equal(report.compose.workerLate, 1);
  assert.equal(report.compose.sentByWorker, 0);
});

test("un refus explicite du worker : rien n'est parti, la zone de saisie prend le relais, le worker n'est plus essayé", async () => {
  const { p, w } = await readyPage();
  const before = w.received.length;
  const result = p.send({ id: "t0123456789ad", conversation: F.GROUP, text: "salut" });
  const sent = await ownCommand(w, before);
  answer(w, F.reply(sent.requestId, { data: { autoSendMessage: null }, errors: [{ message: "Forbidden" }] }));
  const first = await result;
  assert.equal(first.result, "retry", "rien n'est parti : on peut réessayer");
  assert.match(first.reason, /worker de Teams a refusé l'envoi \(Forbidden\)/);
  assert.match(first.reason, /conversation pas ouverte/);
  const second = await p.send({ id: "t0123456789ad", conversation: F.GROUP, text: "salut" });
  assert.equal(second.result, "retry", "pas « déjà commencé » : rien n'était parti");
  assert.equal(w.received.length, before + 1, "le worker ne reprend pas un élément qu'il a refusé");
  // un autre élément, lui, repasse par le worker
  const other = p.send({ id: "t0123456789ae", conversation: F.GROUP, text: "re" });
  const next = await ownCommand(w, before + 1);
  answer(w, F.reply(next.requestId));
  assert.equal((await other).result, "sent");
  assert.equal((await p.diagnose()).compose.workerRefused, 1);
});

test("un canal, une réunion : rien n'est passé au worker, la zone de saisie seule", async () => {
  const { p, w } = await readyPage();
  const before = w.received.length;
  for (const conversation of [F.CHANNEL, F.MEETING]) {
    const result = await p.send({ id: "t0123456789b" + (conversation === F.CHANNEL ? "0" : "1"), conversation,
      text: "bonjour" });
    assert.equal(result.result, "retry");
    assert.match(result.reason, /conversation pas ouverte/);
  }
  assert.equal(w.received.length, before);
});

test("sans modèle d'envoi, ou sans commande de la page au worker : la zone de saisie seule", async () => {
  const p = page();
  const w = p.worker();
  w.postMessage(JSON.stringify(F.query(10)));
  const result = await p.send({ id: "t0123456789c0", conversation: F.ALBERT, text: "bonjour" });
  assert.equal(result.result, "retry");
  assert.equal(w.received.length, 1);
  const report = await p.diagnose();
  assert.equal(report.compose.workerSendPossible, false);
  assert.equal(report.compose.workerSeen, true);
  // un modèle gardé, mais une page dont le worker n'a encore rien reçu
  const stored = P.workerSendTemplate(F.autoSend()).template;
  const q = page({ service: (what) => (what === "sendTemplates" ? { ok: true, data: { bilateral: { ...stored, at: 5 } } }
    : null) });
  const idle = q.worker();
  assert.equal((await q.send({ id: "t0123456789c1", conversation: F.ALBERT, text: "bonjour" })).result, "retry");
  assert.deepEqual(idle.received, []);
  assert.equal((await q.diagnose()).compose.workerSendPossible, false);
});

test("après un rechargement, le modèle gardé par le service sert ; rendererId, windowId et compteur sont ceux de la page", async () => {
  const stored = P.workerSendTemplate(F.autoSend({ conv: F.GROUP })).template;
  const p = page({ service: (what) => (what === "sendTemplates" ? { ok: true, data: { group: { ...stored, at: 7 } } }
    : null) });
  const w = p.worker();
  w.postMessage(JSON.stringify(F.query(77, { renderer: "renderer-neuf", window: 2 })));
  const result = p.send({ id: "t0123456789d0", conversation: F.ALBERT, text: "coucou" });
  const sent = await ownCommand(w, 1);
  assert.equal(sent.requestId, "m-1077");
  assert.equal(sent.rendererId, "renderer-neuf");
  assert.equal(sent.windowId, 2);
  assert.equal(sent.payload.variables.convId, F.ALBERT);
  // le modèle d'un groupe sert au tête-à-tête, avec la valeur que Teams y avait mise (`false`, comme chez Albert)
  assert.equal(sent.payload.variables.isBilateralChat, false, "le modèle d'un groupe sert au tête-à-tête");
  answer(w, F.reply(sent.requestId));
  assert.equal((await result).result, "sent");
  // deux envois de suite : deux numéros
  const second = p.send({ id: "t0123456789d1", conversation: F.ALBERT, text: "encore" });
  const next = await ownCommand(w, 2);
  assert.equal(next.requestId, "m-1078");
  answer(w, F.reply(next.requestId));
  assert.equal((await second).result, "sent");
});

test("le worker de la télémétrie n'est ni écouté ni pris pour celui des commandes", async () => {
  const p = page();
  const tele = p.worker("https://statics.teams.cdn.office.net/telemetry-worker.js");
  tele.postMessage(JSON.stringify(F.autoSend()));
  await settle();
  assert.equal(p.asks("sendTemplate").length, 0);
  assert.equal(tele.listeners.length, 0);
  assert.equal((await p.diagnose()).compose.workerSeen, false);
});
