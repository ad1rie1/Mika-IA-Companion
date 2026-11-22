"use strict";
// Le service d'arrière-plan tel quel, dans un contexte à part, avec de fausses API de Chrome, `fetch` et `WebSocket` :
// les curseurs de la synchro ciblée, l'historique de la mise en service, la boîte d'envoi poussée en direct (ADR 0251).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.join(__dirname, "..");
const KEY = "mtk_cle_de_test_1234";
const SELF = "3e51ce13-6eb8-463b-a75a-a40b2ab67602";
const CONV = "19:projet@thread.v2";
const TAB = { tab: { id: 7 }, url: "https://teams.cloud.microsoft/" };
const PAGE = { url: "chrome-extension://xyz/options.html" };
const plain = (v) => JSON.parse(JSON.stringify(v));

/** Un service neuf : `settings` réglés, des onglets Teams (`tabs`), et ce que répond Mika (`reply(method, url)`). */
function service({ settings = {}, tabs = [{ id: 7, active: true, lastAccessed: 1 }], reply } = {}) {
  const store = { settings: { base: "https://mika.example.org", key: KEY, paused: false, exclude: "", ...settings } };
  const listeners = {};
  const fetched = [];
  const toTabs = [];
  const sockets = [];
  const reloaded = [];
  class FakeSocket {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.closed = false;
      sockets.push(this);
    }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.closed = true; }
  }
  const chrome = {
    storage: { local: {
      get: async (keys) => Object.fromEntries(keys.filter((k) => store[k] !== undefined).map((k) => [k, plain(store[k])])),
      set: async (o) => { Object.assign(store, plain(o)); },
      remove: async (k) => { delete store[k]; },
    } },
    runtime: { onMessage: { addListener: (f) => { listeners.message = f; } },
      onInstalled: { addListener: (f) => { listeners.installed = f; } }, onStartup: { addListener: () => {} },
      getURL: (p) => "chrome-extension://xyz/" + p },
    alarms: { clear: () => {}, create: () => {}, onAlarm: { addListener: () => {} } },
    notifications: { onClicked: { addListener: () => {} }, create: () => {}, clear: () => {}, getAll: async () => ({}) },
    permissions: { contains: async () => true },
    tabs: { query: async () => tabs, sendMessage: async (id, msg) => { toTabs.push(plain(msg)); return { ok: true }; },
      reload: async (id) => { reloaded.push(id); } },
  };
  const fetch = async (url, init) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    fetched.push({ method: init.method, url: String(url), body });
    const got = reply ? reply(init.method, String(url), body) : null;
    const status = got ? got.status : init.method === "GET" ? 200 : 202;
    const data = got ? got.data : init.method === "GET" ? { items: [] } : { accepted: body.messages.length, known: 0, twins: 0, dropped: 0 };
    return { status, headers: { get: () => null }, json: async () => data };
  };
  // des minuteurs qui ne retiennent pas le processus (une reprise dans 60 s, un signe de vie toutes les 20 s)
  const loose = (make) => (fn, ms) => {
    const t = make(fn, ms);
    if (t && typeof t.unref === "function") t.unref();
    return t;
  };
  const ctx = { chrome, fetch, WebSocket: FakeSocket, console, setTimeout: loose(setTimeout), clearTimeout,
    setInterval: loose(setInterval), clearInterval, URL, AbortController, Date, JSON, Math, Promise };
  ctx.globalThis = ctx;
  ctx.self = ctx;
  ctx.importScripts = (...files) => {
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(ROOT, f), "utf8"), ctx, { filename: f });
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(ROOT, "background.js"), "utf8"), ctx, { filename: "background.js" });
  const send = (msg, sender) => new Promise((resolve) => {
    if (!listeners.message(msg, sender, (r) => resolve(plain(r)))) resolve(null);
  });
  return { store, fetched, toTabs, sockets, reloaded, send, installed: () => listeners.installed({ reason: "update" }),
    settle: () => new Promise((done) => setTimeout(done, 30)) };
}

function message(id, time, text, conv = CONV) {
  return { id: String(id), conv, author: "Alice", authorId: "8:orgid:11111111-2222-3333-4444-555555555555", time,
    type: "Text", text, source: "idb", mentions: [] };
}

test("les curseurs d'un lot sont gardés, rendus à l'onglet qui s'ouvre, et n'avancent jamais en arrière", async () => {
  const s = service();
  await s.send({ kind: "captured", messages: [], conversations: [], self: SELF,
    cursors: [{ conv: CONV, w: 1_800_000_000_000, m: "7|1" }] }, TAB);
  await s.send({ kind: "captured", messages: [], conversations: [], self: SELF,
    cursors: [{ conv: CONV, w: 1_700_000_000_000, m: "8|1" }] }, TAB);
  const got = await s.send({ kind: "cursors" }, TAB);
  assert.equal(got.ok, true);
  assert.deepEqual(got.cursors, { [CONV]: { w: 1_800_000_000_000, m: "8|1" } });
});

test("l'historique part marqué, sans fenêtre ni activation, les exclusions valant toujours ; ses comptes suivent", async () => {
  const s = service({ settings: { exclude: "Médecin" } });
  assert.deepEqual(await s.send({ kind: "history" }, PAGE), { ok: true });
  const run = s.toTabs.find((m) => m.kind === "history").run;
  assert.ok(run, "le chargement a son identifiant");
  const answer = await s.send({ kind: "historyChunk", run, self: SELF,
    conversations: [{ id: CONV, title: "Projet", threadType: "chat" }, { id: "19:med@thread.v2", title: "Médecin" }],
    messages: [message("1600000000000", 1_600_000_000_000, "il y a longtemps"),
      message("1600000000001", 1_600_000_000_001, "secret", "19:med@thread.v2")] }, TAB);
  assert.deepEqual(answer, { ok: true });
  const posted = s.fetched.filter((f) => f.method === "POST" && f.url.endsWith("/api/teams/inbox"));
  assert.equal(posted.length, 1);
  assert.equal(posted[0].body.history, true);
  assert.deepEqual(posted[0].body.messages.map((m) => m.text), ["il y a longtemps"]);
  await s.send({ kind: "historyDone", run, done: 2, total: 2, messages: 2, error: "" }, TAB);
  // un paquet d'un autre chargement (d'avant) ne compte nulle part
  const stale = await s.send({ kind: "historyChunk", run: "hvieux", self: SELF, conversations: [],
    messages: [message("1600000000009", 1_600_000_000_009, "d'avant")] }, TAB);
  assert.equal(stale.ok, false);
  const h = (await s.send({ kind: "status" }, PAGE)).history;
  assert.equal(h.state, "done");
  assert.equal(h.sent, 1);
  assert.equal(h.accepted, 1);
  assert.equal(h.dropped, 1, "la conversation exclue n'est pas partie");
  assert.equal(h.done, 2);
});

test("un paquet d'historique que Mika refuse rend sa raison à l'onglet, et l'historique s'arrête là", async () => {
  const s = service({ reply: (method) => (method === "POST" ? { status: 401, data: { error: "Clé refusée." } } : null) });
  await s.send({ kind: "history" }, PAGE);
  const run = s.toTabs.find((m) => m.kind === "history").run;
  const answer = await s.send({ kind: "historyChunk", run, self: SELF, conversations: [],
    messages: [message("1600000000000", 1_600_000_000_000, "vieux")] }, TAB);
  assert.equal(answer.ok, false);
  assert.match(answer.error, /clé refusée/);
  const state = await s.send({ kind: "status" }, PAGE);
  assert.equal(state.authFailed, true);
  assert.match(state.history.error, /clé refusée/);
});

test("sans onglet Teams, l'historique ne démarre pas, et la connexion en direct ne s'ouvre pas", async () => {
  const s = service({ tabs: [] });
  const got = await s.send({ kind: "history" }, PAGE);
  assert.equal(got.ok, false);
  assert.match(got.error, /onglet/);
  await s.settle();
  assert.equal(s.sockets.length, 0);
});

test("en direct : la clé part dans le premier message, et la boîte poussée est traitée sans relevé", async () => {
  const s = service();
  await s.settle();
  assert.equal(s.sockets.length, 1);
  const ws = s.sockets[0];
  assert.equal(ws.url, "wss://mika.example.org/api/teams/live", "la clé n'est jamais dans l'adresse");
  ws.onopen();
  assert.deepEqual(ws.sent, [{ type: "hello", key: KEY }]);
  const gets = () => s.fetched.filter((f) => f.method === "GET").length;
  const before = gets();
  ws.onmessage({ data: JSON.stringify({ type: "outbox", items: [{ id: "t0123456789ab", conversation: CONV, title: "Projet",
    kind: "group", mode: "draft", status: "queued", text: "Oui, 14 h me va.", created_at: 1, expires_at: 0 }] }) });
  await s.settle();
  assert.equal(gets(), before, "la liste poussée tient lieu de relevé");
  const drafts = s.toTabs.filter((m) => m.kind === "drafts").at(-1);
  assert.deepEqual(drafts.items.map((d) => d.id), ["t0123456789ab"]);
  const state = await s.send({ kind: "status" }, PAGE);
  assert.equal(state.live.connected, true);
  assert.ok(state.live.lastPushAt > 0);
  // fermée par Mika (clé refusée) : dite, et reprise bien plus tard seulement
  ws.onclose({ code: 4401 });
  const after = await s.send({ kind: "status" }, PAGE);
  assert.equal(after.live.connected, false);
  assert.equal(after.live.lastError, "clé refusée");
});

test("en pause, ou sans clé, la connexion en direct reste fermée", async () => {
  for (const settings of [{ paused: true }, { key: "" }]) {
    const s = service({ settings });
    await s.settle();
    assert.equal(s.sockets.length, 0, JSON.stringify(settings));
  }
});

test("une pause prise pendant l'historique l'arrête ; une pause ancienne vaut toujours", async () => {
  const s = service();
  await s.send({ kind: "history" }, PAGE);
  const run = s.toTabs.find((m) => m.kind === "history").run;
  // une pause d'il y a un mois : ce qui y a été écrit ne part jamais, même par l'historique
  s.store.runtime.pauses = [{ start: 1_600_000_000_000, end: 1_600_000_100_000 }];
  await s.send({ kind: "historyChunk", run, self: SELF, conversations: [{ id: CONV, title: "Projet" }],
    messages: [message("1600000050000", 1_600_000_050_000, "écrit pendant la pause"),
      message("1600000200000", 1_600_000_200_000, "écrit après")] }, TAB);
  const posted = s.fetched.filter((f) => f.method === "POST").flatMap((f) => f.body.messages.map((m) => m.text));
  assert.deepEqual(posted, ["écrit après"]);
  // mise en pause en route : le paquet suivant est refusé, et le chargement s'arrête
  s.store.settings.paused = true;
  const refused = await s.send({ kind: "historyChunk", run, self: SELF, conversations: [],
    messages: [message("1600000300000", 1_600_000_300_000, "plus tard")] }, TAB);
  assert.equal(refused.ok, false);
  assert.match(refused.error, /pause/);
  assert.equal((await s.send({ kind: "status" }, PAGE)).history.state, "error");
});

test("en direct : le délai de reprise grandit tant que Mika refuse, et ne repart à 2 s qu'une fois admise", async () => {
  const s = service();
  await s.settle();
  const ws = s.sockets[0];
  ws.onopen(); // Mika accepte avant de refuser : une ouverture ne prouve rien
  ws.onclose({ code: 4429 });
  await new Promise((done) => setTimeout(done, 2200)); // la reprise, 2 s plus tard
  assert.equal(s.sockets.length, 2);
  s.sockets[1].onopen();
  s.sockets[1].onclose({ code: 4429 });
  assert.equal((await s.send({ kind: "status" }, PAGE)).live.retryMs, 8000, "2 s, puis 4 s, puis 8 s");
  const s2 = service();
  await s2.settle();
  const ws2 = s2.sockets[0];
  ws2.onopen();
  ws2.onmessage({ data: JSON.stringify({ type: "outbox", items: [] }) });
  ws2.onclose({ code: 1006 });
  assert.equal((await s2.send({ kind: "status" }, PAGE)).live.retryMs, 4000, "admise : repart de 2 s, puis double");
});

const JPEG64 = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]).toString("base64");
const imageAsk = (extra = {}) => ({ kind: "image", conv: CONV, id: "1800000000000", image: "0-neu-d4-abc", position: 0,
  type: "image/jpeg", data: JPEG64, time: Date.now(), author: "Alice",
  authorId: "8:orgid:11111111-2222-3333-4444-555555555555", history: false, ...extra });

test("une image part après son message, triée comme lui ; un message pas encore chez Mika se retente", async () => {
  let known = false;
  const s = service({ settings: { exclude: "Médecin" }, reply: (method, url) => {
    if (url.endsWith("/api/teams/image")) return known ? { status: 202, data: { kept: true } } : { status: 404, data: {} };
    if (url.endsWith("/api/teams/inbox")) known = true;
    return null;
  } });
  await s.send({ kind: "captured", self: SELF, conversations: [{ id: CONV, title: "Projet", threadType: "chat" }],
    // daté après l'activation du service neuf (fixée à son premier chargement)
    messages: [{ ...message("1800000000000", Date.now() + 1000, "[image]"), images: 1 }] }, TAB);
  const sent = await s.send(imageAsk(), TAB);
  assert.deepEqual(sent, { ok: true });
  const posts = s.fetched.filter((f) => f.method === "POST").map((f) => f.url.replace(/^.*\/api\/teams\//, ""));
  assert.deepEqual(posts, ["inbox", "image"], "son message d'abord, puis l'image");
  assert.equal(s.fetched.find((f) => f.url.endsWith("/inbox")).body.messages[0].images, 1);
  // un message que Mika ne connaît pas encore : à retenter
  known = false;
  const later = await s.send(imageAsk({ id: "1800000000001", image: "0-autre" }), TAB);
  assert.equal(later.ok, false);
  assert.equal(later.retry, true);
  // exclue, ou trop vieille en direct : écartée sans rien envoyer
  const before = s.fetched.length;
  assert.deepEqual(await s.send(imageAsk({ conv: "19:med@thread.v2" }), TAB), { ok: true, skipped: true });
  await s.send({ kind: "captured", self: SELF, conversations: [{ id: "19:med@thread.v2", title: "Médecin" }],
    messages: [] }, TAB);
  assert.deepEqual(await s.send(imageAsk({ conv: "19:med@thread.v2" }), TAB), { ok: true, skipped: true });
  assert.deepEqual(await s.send(imageAsk({ time: 1_600_000_000_000 }), TAB), { ok: true, skipped: true });
  assert.equal(s.fetched.length, before, "rien n'est parti pour elles");
  // dans l'historique, une vieille image passe
  known = true;
  assert.deepEqual(await s.send(imageAsk({ time: 1_600_000_000_000, id: "1600000000000", history: true }), TAB),
    { ok: true });
  assert.equal((await s.send({ kind: "status" }, PAGE)).stats.images.sent, 2);
});

test("rechargée depuis sa page de réglages, l'extension recharge les onglets Teams ; d'elle-même, jamais", async () => {
  const s = service({ tabs: [{ id: 7 }, { id: 9 }] });
  s.installed();
  await s.settle();
  assert.deepEqual(s.reloaded, [], "une mise à jour que personne n'a demandée ne touche pas aux onglets");
  s.store.reloadTeamsTabs = Date.now();
  s.installed();
  await s.settle();
  assert.deepEqual(s.reloaded, [7, 9]);
  assert.equal(s.store.reloadTeamsTabs, undefined, "la demande ne sert qu'une fois");
  s.store.reloadTeamsTabs = Date.now() - 5 * 60 * 1000;
  s.installed();
  await s.settle();
  assert.deepEqual(s.reloaded, [7, 9], "une demande d'il y a cinq minutes ne vaut plus");
});

const GILLES = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab";
const PROFILE = { id: GILLES, name: "Gilles Rousseau", email: "gilles@nordis.fr", title: "Responsable réseau",
  company: "Nordis", department: "", tenant: "Nordis SAS", phones: [] };

// daté après l'activation du service neuf (fixée à son premier chargement)
function fromGilles(id, conv = CONV) {
  return { ...message(id, Date.now() + 1000, "bonjour", conv), authorId: GILLES, author: "Gilles Rousseau" };
}

/** Les envois à Mika, une fois que l'envoi automatique (≈ 400 ms après une capture) est passé. */
async function inboxPosts(s, count) {
  const posts = () => s.fetched.filter((f) => f.method === "POST" && f.url.endsWith("/api/teams/inbox"));
  for (let waited = 0; posts().length < count && waited < 3000; waited += 50) await new Promise((r) => setTimeout(r, 50));
  return posts();
}

test("un profil part avec le premier message de sa personne qui part, puis plus, tant qu'il ne change pas (ADR 0298)", async () => {
  const s = service();
  await s.send({ kind: "captured", self: SELF, conversations: [{ id: CONV, title: "Projet", threadType: "chat" }],
    messages: [fromGilles("1800000000101")], profiles: [PROFILE] }, TAB);
  const first = await inboxPosts(s, 1);
  assert.equal(first.length, 1);
  assert.deepEqual(first[0].body.profiles.map((p) => p.email), ["gilles@nordis.fr"]);
  await s.send({ kind: "captured", self: SELF, conversations: [], messages: [fromGilles("1800000000102")],
    profiles: [PROFILE] }, TAB);
  const second = await inboxPosts(s, 2);
  assert.equal(second.length, 2);
  assert.equal(second[1].body.profiles, undefined, "déjà parti tel quel");
  // il change : il repart
  await s.send({ kind: "captured", self: SELF, conversations: [], messages: [fromGilles("1800000000103")],
    profiles: [{ ...PROFILE, title: "Directeur réseau" }] }, TAB);
  const third = await inboxPosts(s, 3);
  assert.deepEqual(third[2].body.profiles.map((p) => p.title), ["Directeur réseau"]);
});

test("pas de profil pour une conversation exclue, ni appris pendant une pause", async () => {
  const s = service({ settings: { exclude: "Médecin" } });
  await s.send({ kind: "captured", self: SELF, conversations: [{ id: "19:med@thread.v2", title: "Médecin", threadType: "chat" }],
    messages: [fromGilles("1800000000201", "19:med@thread.v2")], profiles: [PROFILE] }, TAB);
  await new Promise((r) => setTimeout(r, 700));
  const posted = s.fetched.filter((f) => f.method === "POST" && f.url.endsWith("/api/teams/inbox"));
  assert.ok(posted.every((f) => !f.body.profiles), "son seul message est exclu : son profil ne part pas");
  const paused = service({ settings: { paused: true } });
  await paused.send({ kind: "captured", self: SELF, conversations: [], messages: [fromGilles("1800000000202")],
    profiles: [PROFILE] }, TAB);
  assert.deepEqual((paused.store.runtime && paused.store.runtime.profiles) || {}, {}, "rien d'appris en pause");
});

test("l'historique ne marque partis que les profils vraiment joints : ceux qui ne tenaient pas repartiront", async () => {
  // relecture de l'ADR 0298, mineur 4 : tous les profils préparés étaient marqués partis, même ceux que le paquet
  // avait laissés faute de place (au-delà de 200 par envoi) ; ils ne repartaient plus tant qu'ils ne changeaient pas
  const s = service();
  await s.send({ kind: "history" }, PAGE);
  const run = s.toTabs.find((m) => m.kind === "history").run;
  const ids = Array.from({ length: 230 }, (_, i) => `8:orgid:00000000-0000-4000-8000-${String(i).padStart(12, "0")}`);
  const profiles = ids.map((id, i) => ({ id, name: `Personne ${i}`, email: "", title: "", company: "", department: "",
    tenant: "", phones: [] }));
  const messages = Array.from({ length: 12 }, (_, i) => ({ ...message(String(1600000000100 + i), 1_600_000_000_100 + i,
    "bonjour"), authorId: ids[i * 20], mentions: ids.slice(i * 20 + 1, i * 20 + 20) }));
  const answer = await s.send({ kind: "historyChunk", run, self: SELF, conversations: [{ id: CONV, title: "Projet",
    threadType: "chat" }], messages, profiles }, TAB);
  assert.deepEqual(answer, { ok: true });
  const posted = s.fetched.filter((f) => f.method === "POST" && f.url.endsWith("/api/teams/inbox"));
  const joined = new Set(posted.flatMap((f) => (f.body.profiles || []).map((p) => p.id)));
  assert.ok(joined.size > 0 && joined.size < ids.length, "un paquet en porte au plus 200");
  const sent = Object.keys(s.store.runtime.profilesSent || {});
  assert.deepEqual(sent.sort(), [...joined].sort(), "seuls ceux qui sont partis sont marqués");
});
