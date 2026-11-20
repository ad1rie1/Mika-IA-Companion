"use strict";
// Le relais tel que Chrome le charge : seul dans son monde. Chrome n'injecte un même fichier qu'une fois par cadre,
// quel que soit le monde (MAIN ou isolé) : un fichier listé pour la page et pour le relais n'arrive qu'à la page.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const T = require("../lib/text.js");

const ROOT = path.join(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"));

test("aucun fichier n'est chargé à la fois dans la page et dans le monde isolé (Chrome ne l'injecterait qu'une fois)", () => {
  const main = new Set();
  const isolated = new Set();
  for (const entry of manifest.content_scripts) {
    for (const js of entry.js) (entry.world === "MAIN" ? main : isolated).add(path.normalize(js));
  }
  assert.deepEqual([...isolated].filter((js) => main.has(js)), []);
});

/**
 * Le relais chargé seul, comme dans Chrome : sans `MikaTeamsText`. Rend ce qu'il passe au service (`sent`), ce qu'il
 * dit à la page (`toPage`) ; `answer` : ce que le service répond à une demande (par sa sorte).
 */
function relay(answer) {
  const listeners = [];
  const sent = [];
  const toPage = [];
  const fromService = [];
  const win = { addEventListener: (type, fn) => { if (type === "message") listeners.push(fn); },
    postMessage: (data) => toPage.push(JSON.parse(JSON.stringify(data))) };
  const ctx = {
    window: win, location: { origin: "https://teams.cloud.microsoft" }, setTimeout, clearTimeout, Date, Math, String,
    Object, Array, Number, JSON, isFinite,
    chrome: { runtime: {
      sendMessage: (payload) => {
        sent.push(JSON.parse(JSON.stringify(payload)));
        return Promise.resolve(answer && answer[payload.kind] !== undefined ? answer[payload.kind] : { ok: true });
      },
      onMessage: { addListener: (fn) => fromService.push(fn) },
    } },
  };
  vm.createContext(ctx);
  // comme Chrome : un fichier déjà injecté dans la page (monde MAIN) ne l'est pas une seconde fois ici
  const inPage = new Set(manifest.content_scripts.filter((e) => e.world === "MAIN").flatMap((e) => e.js));
  const files = manifest.content_scripts.find((e) => e.world !== "MAIN").js.filter((js) => !inPage.has(js));
  for (const js of files) vm.runInContext(fs.readFileSync(path.join(ROOT, js), "utf8"), ctx, { filename: js });
  return {
    sent,
    toPage,
    fromPage: (data) => listeners.forEach((fn) => fn({ source: win, data: Object.assign({ __mika: "mika-teams", dir: "out" }, data) })),
    fromService: (msg) => {
      let got = null;
      fromService.forEach((fn) => fn(msg, {}, (r) => { got = r; }));
      return got;
    },
  };
}

const settle = () => new Promise((done) => setImmediate(done));

test("seul dans son monde, le relais passe au service ce que la page a capté", async () => {
  const r = relay();
  r.fromPage({ kind: "captured", self: "3e51ce13-6eb8-463b-a75a-a40b2ab67602",
    messages: [{ id: "1700000000001", conv: "19:a@thread.v2", author: "Alice", authorId: "8:orgid:x", time: 1700000000001,
      type: "Text", text: "bonjour", source: "idb", mentions: [] }],
    conversations: [{ id: "19:a@thread.v2", title: "Projet", threadType: "chat" }] });
  await new Promise((done) => setImmediate(done));
  const captured = r.sent.filter((p) => p.kind === "captured");
  assert.equal(captured.length, 1);
  assert.equal(captured[0].messages[0].text, "bonjour");
  assert.deepEqual(captured[0].conversations, [{ id: "19:a@thread.v2", title: "Projet", threadType: "chat" }]);
});

test("sa coupe est celle de la bibliothèque : bornée, bien formée, jamais au milieu d'une paire", async () => {
  const texts = ["a".repeat(3999) + "😀 la suite", "a".repeat(4000) + "b", "x\uD800y", "\uDC00début", "😀".repeat(2500),
    "court", "é".repeat(5000)];
  const r = relay();
  r.fromPage({ kind: "captured", conversations: [], messages: texts.map((text, i) => (
    { id: String(1700000000000 + i), conv: "19:a@thread.v2", time: 1700000000000 + i, text: text, mentions: [] })) });
  await new Promise((done) => setImmediate(done));
  const out = r.sent.find((p) => p.kind === "captured").messages.map((m) => m.text);
  assert.deepEqual(out, texts.map((t) => T.cut(t, 4000)));
});

test("ce que le worker de Teams a passé garde sa source ; une source inconnue devient « réseau »", async () => {
  const r = relay();
  const m = { conv: "19:a@thread.v2", time: 1700000000000, text: "salut", mentions: [] };
  r.fromPage({ kind: "captured", conversations: [], messages: [{ ...m, id: "1", source: "worker" },
    { ...m, id: "2", source: "idb" }, { ...m, id: "3", source: "n'importe" }] });
  await settle();
  assert.deepEqual(r.sent.find((p) => p.kind === "captured").messages.map((x) => x.source), ["worker", "idb", "network"]);
});

test("les curseurs partent avec le lot, vérifiés ; un lot de curseurs seuls part aussi", async () => {
  const r = relay();
  r.fromPage({ kind: "captured", messages: [], conversations: [], cursors: [
    { conv: "19:a@thread.v2", w: 1700000000000.7, m: "7|3|100" }, { conv: "", w: 5 }, { conv: "19:b", w: -1 },
    { conv: "19:c", w: "beaucoup" }] });
  await settle();
  assert.deepEqual(r.sent.find((p) => p.kind === "captured").cursors,
    [{ conv: "19:a@thread.v2", w: 1700000000000, m: "7|3|100" }]);
});

test("la page demande ses curseurs : le service répond, le relais rend sa réponse vérifiée", async () => {
  const r = relay({ cursors: { ok: true, cursors: { "19:a@thread.v2": { w: 42, m: "x" }, "19:b": { w: "?" } } } });
  r.fromPage({ kind: "ask", nonce: "n1", what: "cursors", payload: {} });
  await settle();
  assert.deepEqual(r.sent.at(-1), { kind: "cursors" });
  const answer = r.toPage.find((d) => d.kind === "answer");
  assert.deepEqual(answer, { __mika: "mika-teams", dir: "in", kind: "answer", nonce: "n1", ok: true,
    data: { "19:a@thread.v2": { w: 42, m: "x" } } });
});

test("un paquet d'historique passe vérifié ; un refus du service revient à la page avec sa raison", async () => {
  const r = relay({ historyChunk: { ok: false, error: "clé refusée par Mika" } });
  r.fromPage({ kind: "ask", nonce: "n2", what: "historyChunk", payload: { self: "3e51ce13-6eb8-463b-a75a-a40b2ab67602",
    messages: [{ id: "1600000000000", conv: "19:a@thread.v2", time: 1600000000000, text: "vieux", source: "idb" },
      { id: "", conv: "19:a@thread.v2", time: 1, text: "sans identifiant" }],
    conversations: [{ id: "19:a@thread.v2", title: "Projet", threadType: "chat" }], extra: "ignoré" } });
  await settle();
  const sentChunk = r.sent.at(-1);
  assert.equal(sentChunk.kind, "historyChunk");
  assert.deepEqual(sentChunk.messages.map((m) => m.id), ["1600000000000"]);
  assert.equal(sentChunk.extra, undefined);
  const answer = r.toPage.find((d) => d.kind === "answer");
  assert.equal(answer.ok, false);
  assert.deepEqual(answer.data, { error: "clé refusée par Mika" });
});

test("une demande inconnue n'atteint pas le service ; l'ordre « history » du service atteint la page", async () => {
  const r = relay();
  r.fromPage({ kind: "ask", nonce: "n3", what: "save", payload: { key: "mtk_vole" } });
  r.fromPage({ kind: "ask", nonce: "n4", what: "__proto__", payload: {} });
  await settle();
  assert.equal(r.sent.filter((p) => p.kind !== "pendingDrafts").length, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(r.fromService({ kind: "history" }))), { ok: true });
  assert.ok(r.toPage.some((d) => d.kind === "history" && d.dir === "in"));
});

test("une image passe vérifiée : un type admis, du base64, des identifiants de Teams ; la réponse dit si retenter", async () => {
  const r = relay({ image: { ok: false, retry: true, error: "Son message n'est pas encore arrivé." } });
  const good = { conv: "19:a@thread.v2", id: "1759000000700", image: "0-neu-d4-abc", position: 1, type: "image/jpeg",
    data: Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64"), time: 1759000000700, history: true };
  r.fromPage({ kind: "ask", nonce: "i1", what: "image", payload: good });
  await settle();
  const sent = r.sent.at(-1);
  assert.equal(sent.kind, "image");
  assert.equal(sent.type, "image/jpeg");
  assert.equal(sent.data, good.data);
  assert.equal(sent.history, true);
  const answer = r.toPage.find((d) => d.kind === "answer" && d.nonce === "i1");
  assert.deepEqual(answer.data, { skipped: false, retry: true, error: "Son message n'est pas encore arrivé." });
  r.fromPage({ kind: "ask", nonce: "i2", what: "image", payload: { ...good, type: "text/html", data: "<script>",
    image: "../../etc" } });
  await settle();
  const bad = r.sent.at(-1);
  assert.equal(bad.type, "");
  assert.equal(bad.data, "");
  assert.equal(bad.image, "");
});
