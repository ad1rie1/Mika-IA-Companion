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

test("les profils joints passent vérifiés : un identifiant de Teams reconnu, un e-mail bien formé, des champs bornés", async () => {
  const r = relay();
  const id = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab";
  r.fromPage({ kind: "captured", conversations: [], messages: [], profiles: [
    { id, name: "Gilles Rousseau", email: "gilles@nordis.fr", title: "x".repeat(500), phones: ["+33 6 12 34 56 78", 5, "1", "2", "3"] },
    { id: "javascript:alert(1)", name: "piège" },
    { id: "8:orgid:11111111-2222-3333-4444-555555555555", name: "Sophie", email: "<script>@x" }] });
  await settle();
  const sent = r.sent.find((p) => p.kind === "captured");
  assert.ok(sent, "un lot de profils seuls part aussi");
  assert.deepEqual(sent.profiles.map((p) => p.id), [id, "8:orgid:11111111-2222-3333-4444-555555555555"]);
  assert.equal(sent.profiles[0].title.length, 120);
  assert.deepEqual(sent.profiles[0].phones, ["+33 6 12 34 56 78", "5", "1"]);
  assert.equal(sent.profiles[1].email, "");
});

// ── ADR 0300 : les réactions, les photos de profil ──────────────────────────

test("les réactions d'un message passent vérifiées, avec sa version ; une liste vide passe aussi (aucune)", async () => {
  const r = relay();
  const base = { id: "1700000000002", conv: "19:a@thread.v2", author: "Alice", authorId: "8:orgid:x", time: 1700000000002,
    type: "Text", text: "bravo", source: "worker", mentions: [], version: 1700000000999 };
  r.fromPage({ kind: "captured", conversations: [], messages: [
    { ...base, reactions: [{ key: "like", count: 3, mine: true, by: ["8:orgid:a", "<b>", 5] },
      { key: "Pas Une Clé", count: 1, by: [] }, { key: "heart", count: -4, by: [] }, "x"] },
    { ...base, id: "1700000000003", reactions: [] },
    { ...base, id: "1700000000004" }] });
  await settle();
  const [a, b, c] = r.sent.find((p) => p.kind === "captured").messages;
  assert.deepEqual(a.reactions, [{ key: "like", count: 3, mine: true, by: ["8:orgid:a"] }]);
  assert.equal(a.version, 1700000000999);
  assert.deepEqual(b.reactions, []);
  assert.equal("reactions" in c, false, "rien de dit, rien ne passe");
});

test("une photo de profil passe vérifiée : un identifiant de Teams, une empreinte, un type admis, 64 Ko au plus", async () => {
  const r = relay({ photo: { ok: true, skipped: true } });
  const good = { person: "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab", etag: "0x8DCF1A2B3C", type: "image/jpeg",
    data: Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2]).toString("base64") };
  r.fromPage({ kind: "ask", nonce: "p1", what: "photo", payload: good });
  await settle();
  assert.deepEqual(r.sent.at(-1), { kind: "photo", ...good });
  assert.deepEqual(r.toPage.find((d) => d.kind === "answer" && d.nonce === "p1").data,
    { skipped: true, retry: false, error: "" });
  r.fromPage({ kind: "ask", nonce: "p2", what: "photo", payload: { person: "javascript:x", etag: "<x>",
    type: "image/gif", data: "A".repeat(100 * 1024) } });
  await settle();
  assert.deepEqual(r.sent.at(-1), { kind: "photo", person: "", etag: "", type: "", data: "" },
    "rien ne passe qui n'en ait la forme : le service la refuse");
});

test("les photos que le service demande atteignent la page vérifiées : 20 au plus, des personnes de Teams", () => {
  const r = relay();
  const person = (i) => `8:orgid:00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
  const items = [{ person: "https://ailleurs.example/x", etag: "e" }, { person: person(0), etag: "e/0", name: "Léa" },
    ...Array.from({ length: 30 }, (_, i) => ({ person: person(i + 1), etag: "e" + i }))];
  assert.equal(r.fromService({ kind: "photos", items }).ok, true);
  const sent = r.toPage.find((d) => d.kind === "photos");
  assert.equal(sent.items.length, 19, "les 20 premières, moins celle qui n'est pas une personne de Teams");
  assert.deepEqual(sent.items[0], { person: person(0), etag: "e/0", name: "Léa" });
});

// ── ADR 0301 : le modèle d'envoi par le worker de Teams ─────────────────────

test("le modèle d'envoi passe au service vérifié : une création, sans texte, sans conversation, sans requête", async () => {
  const P = require("../lib/page.js");
  const F = require("./worker-fixture.js");
  const { template } = P.workerSendTemplate(F.autoSend());
  const r = relay();
  r.fromPage({ kind: "ask", nonce: "w1", what: "sendTemplate", payload: { template, bilateral: true, extra: "x" } });
  await settle();
  assert.deepEqual(r.sent.at(-1), { kind: "sendTemplate", template, bilateral: true });
  const bad = [
    { ...template, command: { ...template.command, requestId: "m-1" } },
    { ...template, command: { ...template.command, operationName: "deleteMessage" } },
    { ...template, command: JSON.parse(JSON.stringify(template.command).replace('"content":""', '"content":"<p>secret</p>"')) },
    { ...template, command: JSON.parse(JSON.stringify(template.command).replace('"convId":""', `"convId":"${F.ALBERT}"`)) },
    { ...template, command: JSON.parse(JSON.stringify(template.command).replace('"action":"Create"', '"action":"Edit"')) },
    { ...template, command: { ...template.command, note: "dans " + F.GROUP } },
    { ...template, command: { ...template.command, big: "x".repeat(70 * 1024) } },
    { ...template, command: "pas un objet" },
  ];
  for (const [i, t] of bad.entries()) {
    r.fromPage({ kind: "ask", nonce: "b" + i, what: "sendTemplate", payload: { template: t, bilateral: false } });
  }
  await settle();
  assert.deepEqual(r.sent.slice(-bad.length).map((p) => p.template), bad.map(() => null),
    "rien ne passe qui n'en ait la forme : le service le refuse");
  // une forme qui agirait est ramenée à la forme par défaut
  r.fromPage({ kind: "ask", nonce: "w2", what: "sendTemplate", payload: { template: { ...template,
    open: "<p onmouseover=\"x()\">", close: "</p>", breaks: "autre" }, bilateral: true } });
  await settle();
  const safe = r.sent.at(-1).template;
  assert.deepEqual([safe.open, safe.close, safe.breaks], ["<p>", "</p>", "br"]);
});

test("les modèles que le service garde reviennent à la page vérifiés, avec leur date", async () => {
  const P = require("../lib/page.js");
  const F = require("./worker-fixture.js");
  const { template } = P.workerSendTemplate(F.autoSend({ conv: F.GROUP }));
  const leaked = JSON.parse(JSON.stringify(template).replace('"convId":""', `"convId":"${F.ALBERT}"`));
  const r = relay({ sendTemplates: { ok: true, templates: { group: { ...template, at: 1763900000000 },
    bilateral: { ...leaked, at: 5 }, autre: { ...template, at: 1 } } } });
  r.fromPage({ kind: "ask", nonce: "t1", what: "sendTemplates", payload: { extra: 1 } });
  await settle();
  assert.deepEqual(r.sent.at(-1), { kind: "sendTemplates" });
  const answer = r.toPage.find((d) => d.kind === "answer" && d.nonce === "t1");
  assert.equal(answer.ok, true);
  assert.deepEqual(Object.keys(answer.data), ["group"], "un modèle qui nomme une conversation ne revient pas");
  assert.deepEqual(answer.data.group, { ...template, at: 1763900000000 });
});
