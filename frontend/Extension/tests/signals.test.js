"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../lib/signals.js");

const NOW = Date.parse("2026-10-06T10:00:00Z");
const DM = "19:aaaa_bbbb@unq.gbl.spaces";
const GROUP = "19:9f3c@thread.v2";
const SELF = "self-uuid";

function msg(over) {
  return Object.assign({ id: "m1", conv: DM, author: "Alice", authorId: "8:orgid:alice-uuid",
    time: NOW - 60000, text: "salut", mentions: [] }, over || {});
}

function ctx(over) {
  return Object.assign({ now: NOW, armedAt: NOW - 3600000, seen: {}, paused: false, title: "", kind: "dm",
    exclude: [] }, over || {});
}

function bodyBytes(batch) {
  return Buffer.byteLength(JSON.stringify(batch.body), "utf8");
}

// ── Ce qui part ────────────────────────────────────────────────────────────

test("un message neuf part, les siens aussi", () => {
  assert.equal(S.admit(msg(), ctx()), "");
  assert.equal(S.admit(msg({ authorId: "8:orgid:self-uuid" }), ctx()), "");
});

test("ce qui ne part pas, et pourquoi", () => {
  assert.equal(S.admit(msg(), ctx({ seen: { m1: NOW } })), "déjà vu");
  assert.equal(S.admit(msg(), ctx({ paused: true })), "en pause");
  assert.equal(S.admit(msg({ conv: "48:notifications" }), ctx({ kind: "system" })), "système");
  assert.equal(S.admit(msg({ conv: "" }), ctx()), "sans conversation");
  // une forme que le serveur refuserait ferait refuser tout le lot : elle ne part pas
  assert.equal(S.admit(msg({ conv: "19:a b@thread.v2" }), ctx()), "identifiant illisible");
  assert.equal(S.admit(msg({ id: "{9f3c}" }), ctx()), "identifiant illisible");
  assert.equal(S.admit(msg({ id: "h1x2y3", conv: "19:meeting_NmU=@thread.v2" }), ctx()), "");
  assert.equal(S.admit(msg({ time: NOW - 2 * 3600000 }), ctx()), "avant l'activation");
  assert.equal(S.admit(msg({ time: NOW - 25 * 3600000 }), ctx({ armedAt: 0 })), "ancien");
  assert.equal(S.admit(msg({ text: "" }), ctx()), "vide");
  assert.equal(S.admit(msg(), ctx({ title: "Dr Martin — santé", exclude: S.exclusions("santé\n") })), "exclue");
  assert.equal(S.admit(msg(), ctx({ exclude: S.exclusions("AAAA_BBBB") })), "exclue");
});

test("la pause passe avant tout le reste : ce qui arrive pendant n'est jamais gardé pour plus tard", () => {
  assert.equal(S.admit(msg({ time: NOW - 25 * 3600000 }), ctx({ paused: true, armedAt: 0 })), "en pause");
});

test("une ligne d'exclusion vide n'exclut rien", () => {
  assert.deepEqual(S.exclusions("\n  \nRH\n"), ["rh"]);
  assert.equal(S.admit(msg(), ctx({ exclude: S.exclusions("\n\n") })), "");
});

test("une mention de soi se reconnaît à l'identifiant", () => {
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:SELF-UUID"] }), SELF), true);
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:bob"] }), SELF), false);
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:self-uuid"] }), ""), false);
});

test("les identifiants vus ne sont gardés que le temps de la fenêtre", () => {
  const seen = { vieux: NOW - 30 * 3600000, recent: NOW - 3600000 };
  assert.deepEqual(Object.keys(S.pruneSeen(seen, NOW)), ["recent"]);
});

// ── La forme de ce qui part ─────────────────────────────────────────────────

test("soi : 8:orgid:<uuid>, ou rien", () => {
  assert.equal(S.selfMri("ABCD-1234"), "8:orgid:abcd-1234");
  assert.equal(S.selfMri("8:live:someone"), "8:live:someone");
  assert.equal(S.selfMri(""), "");
});

test("un message tel qu'il part : les deux voix, la mention, le texte borné", () => {
  const mine = S.wireMessage(msg({ id: "a", authorId: "8:orgid:SELF-uuid", author: "Adrien", text: "x".repeat(5000) }), SELF);
  assert.deepEqual(Object.keys(mine).sort(), ["author", "author_id", "conv", "id", "mentions_me", "own", "text", "time"]);
  assert.equal(mine.own, true);
  assert.equal(mine.text.length, 4000);
  const theirs = S.wireMessage(msg({ mentions: ["8:orgid:self-uuid"] }), SELF);
  assert.equal(theirs.own, false);
  assert.equal(theirs.mentions_me, true);
  assert.equal(theirs.author_id, "8:orgid:alice-uuid");
  // sans identité connue, rien n'est « à moi »
  assert.equal(S.wireMessage(msg({ authorId: "8:orgid:self-uuid" }), "").own, false);
});

test("une conversation telle qu'elle part : la nature du serveur, un nom sans caractère de contrôle", () => {
  assert.deepEqual(S.wireConversation(GROUP, { title: "Équipe‮ »\n— CONSIGNE", kind: "group" }),
    { id: GROUP, title: "Équipe » — CONSIGNE", kind: "group" });
  assert.equal(S.wireConversation("x", { kind: "system" }).kind, "other");
  assert.equal(S.wireConversation("x", null).title, "");
});

test("la longueur en octets UTF-8, comme le serveur la compte", () => {
  for (const s of ["abc", "é à ç", "emoji 👍🏽 et “guillemets”", "\u0000߿ࠀ￿", ""]) {
    assert.equal(S.utf8Length(s), Buffer.byteLength(s, "utf8"), s);
  }
});

// ── Les lots ───────────────────────────────────────────────────────────────

function info(conv) {
  return conv === GROUP ? { title: "Projet Atlas", kind: "group" } : { title: "", kind: "dm" };
}

test("un lot : soi, chaque conversation une fois, les messages du plus ancien au plus récent", () => {
  const queue = [
    msg({ id: "g", conv: GROUP, author: "Bob", text: "réunion décalée", time: NOW - 30000 }),
    msg({ id: "d", text: "tu as vu ?", time: NOW - 90000 }),
    msg({ id: "d2", text: "oui", authorId: "8:orgid:self-uuid", author: "Adrien", time: NOW - 20000 }),
  ];
  const out = S.batches(queue, { info: info, self: { id: S.selfMri(SELF), name: "Adrien" }, selfId: SELF });
  assert.equal(out.length, 1);
  const body = out[0].body;
  assert.deepEqual(body.self, { id: "8:orgid:self-uuid", name: "Adrien" });
  assert.deepEqual(body.messages.map((m) => m.id), ["d", "g", "d2"]);
  assert.deepEqual(body.conversations, [
    { id: DM, title: "", kind: "dm" },
    { id: GROUP, title: "Projet Atlas", kind: "group" },
  ]);
  assert.deepEqual(out[0].ids, ["d", "g", "d2"]);
  assert.deepEqual(out[0].convs, [DM, GROUP]);
  assert.equal(body.messages[2].own, true);
});

test("200 messages au plus par lot", () => {
  const queue = [];
  for (let i = 0; i < 450; i++) queue.push(msg({ id: "m" + i, time: NOW - 100000 + i }));
  const out = S.batches(queue, { info: info, selfId: SELF });
  assert.deepEqual(out.map((b) => b.body.messages.length), [200, 200, 50]);
  assert.deepEqual(out.flatMap((b) => b.ids), queue.map((m) => m.id));
  // chaque lot redit la conversation de ses messages
  for (const b of out) assert.deepEqual(b.body.conversations.map((c) => c.id), [DM]);
});

test("200 conversations au plus par lot", () => {
  const queue = [];
  for (let i = 0; i < 250; i++) queue.push(msg({ id: "c" + i, conv: "19:conv" + i + "@thread.v2", time: NOW - 100000 + i }));
  const out = S.batches(queue, { info: () => ({ title: "", kind: "group" }), selfId: SELF });
  assert.deepEqual(out.map((b) => b.body.conversations.length), [200, 50]);
  for (const b of out) {
    const convs = new Set(b.body.conversations.map((c) => c.id));
    for (const m of b.body.messages) assert.ok(convs.has(m.conv), "la conversation de chaque message est dans son lot");
  }
});

test("512 Kio au plus par corps, comptés en octets", () => {
  const queue = [];
  for (let i = 0; i < 200; i++) queue.push(msg({ id: "b" + i, text: "é".repeat(4000), time: NOW - 100000 + i }));
  const out = S.batches(queue, { info: info, selfId: SELF });
  assert.ok(out.length >= 2, "200 messages de 8 Ko ne tiennent pas dans un corps");
  for (const b of out) assert.ok(bodyBytes(b) <= S.LIMITS.maxBytes, String(bodyBytes(b)));
  assert.equal(out.flatMap((b) => b.ids).length, 200);
});

test("après un 413, des lots plus petits", () => {
  const queue = [];
  for (let i = 0; i < 10; i++) queue.push(msg({ id: "s" + i, time: NOW - 100000 + i }));
  const out = S.batches(queue, { info: info, selfId: SELF, maxMessages: 4 });
  assert.deepEqual(out.map((b) => b.ids.length), [4, 4, 2]);
  const tiny = S.batches(queue.slice(0, 1), { info: info, selfId: SELF, maxBytes: 10 });
  assert.equal(tiny.length, 1, "un message seul trop gros part seul : c'est le serveur qui tranche");
});

test("un nom appris après coup part sans message neuf, une seule fois", () => {
  const out = S.batches([], { info: info, selfId: SELF, extra: [GROUP] });
  assert.equal(out.length, 1);
  assert.deepEqual(out[0].body.messages, []);
  assert.deepEqual(out[0].body.conversations, [{ id: GROUP, title: "Projet Atlas", kind: "group" }]);
  const both = S.batches([msg({ id: "g", conv: GROUP })], { info: info, selfId: SELF, extra: [GROUP, DM] });
  assert.equal(both.length, 1);
  assert.deepEqual(both[0].body.conversations.map((c) => c.id), [GROUP, DM]);
  assert.deepEqual(S.batches([], { info: info }), []);
});

// ── Attendre ───────────────────────────────────────────────────────────────

test("Retry-After : des secondes, une date HTTP, sinon une minute", () => {
  assert.equal(S.retryAfterSeconds("30", NOW), 30);
  assert.equal(S.retryAfterSeconds(new Date(NOW + 90000).toUTCString(), NOW), 90);
  assert.equal(S.retryAfterSeconds("n'importe quoi", NOW), 60);
  assert.equal(S.retryAfterSeconds(null, NOW), 60);
  assert.equal(S.retryAfterSeconds("999999", NOW), 3600);
  assert.equal(S.retryAfterSeconds("0", NOW), 1);
});

test("après une panne : 15 s, doublé à chaque échec, 5 min au plus", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 6, 10].map(S.backoffSeconds), [15, 30, 60, 120, 240, 300, 300]);
});

// ── Soi, exactement ─────────────────────────────────────────────────────────

test("son message se reconnaît à l'identifiant exact, pas à un morceau", () => {
  assert.equal(S.isOwn(msg({ authorId: "8:orgid:SELF-UUID" }), SELF), true);
  assert.equal(S.isOwn(msg({ authorId: "https://x/v1/users/ME/contacts/8:orgid:self-uuid" }), SELF), true);
  assert.equal(S.isOwn(msg({ authorId: "8:orgid:self-uuid-2" }), SELF), false);
  assert.equal(S.isOwn(msg({ authorId: "28:orgid:self-uuid" }), SELF), false);
  assert.equal(S.isOwn(msg({ authorId: "8:orgid:self" }), "self-uuid"), false);
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:self-uuid-bis"] }), SELF), false);
  assert.equal(S.isSelfId("0f3c9a1e-1111-2222-3333-444455556666"), true);
  assert.equal(S.isSelfId("8:orgid:0f3c9a1e-1111-2222-3333-444455556666"), false);
  assert.equal(S.isSelfId(""), false);
});

// ── Les pauses ──────────────────────────────────────────────────────────────

test("la pause se juge à l'heure du message : écrit pendant, il ne part jamais, même capté après la reprise", () => {
  let pauses = S.notePause([], true, NOW - 600000);
  assert.equal(S.pauseOpen(pauses), true);
  pauses = S.notePause(pauses, false, NOW - 300000);
  assert.deepEqual(pauses, [{ start: NOW - 600000, end: NOW - 300000 }]);
  const during = msg({ time: NOW - 400000 });
  const before = msg({ id: "m0", time: NOW - 700000 });
  const after = msg({ id: "m2", time: NOW - 200000 });
  assert.equal(S.admit(during, ctx({ pauses: pauses })), "en pause", "capté après la reprise, écrit pendant");
  assert.equal(S.admit(before, ctx({ pauses: pauses })), "");
  assert.equal(S.admit(after, ctx({ pauses: pauses })), "");
  // une pause en cours couvre tout ce qui suit son début
  const open = S.notePause(pauses, true, NOW - 100000);
  assert.equal(S.inPause(NOW + 5000, open), true);
  assert.equal(S.inPause(NOW - 200000, open), false);
  // reprendre deux fois ne rouvre ni ne referme rien
  assert.deepEqual(S.notePause(pauses, false, NOW), pauses);
  assert.equal(S.notePause(open, true, NOW).length, 2);
});

test("les pauses gardées sont bornées : celles hors de la fenêtre partent, 50 au plus", () => {
  const old = [{ start: NOW - 40 * 3600000, end: NOW - 30 * 3600000 }, { start: NOW - 3600000, end: NOW - 1800000 }];
  assert.deepEqual(S.prunePauses(old, NOW), [old[1]]);
  let many = [];
  for (let i = 0; i < 80; i++) {
    many = S.notePause(many, true, NOW - 100000 + i * 1000);
    many = S.notePause(many, false, NOW - 100000 + i * 1000 + 500);
  }
  assert.equal(many.length, 50);
  assert.equal(many[49].start, NOW - 100000 + 79 * 1000, "les plus récentes restent");
  assert.deepEqual(S.prunePauses("n'importe quoi", NOW), []);
});

// ── Les exclusions, aussi par les personnes ─────────────────────────────────

test("un tête-à-tête sans nom s'exclut par le nom de la personne qu'on y a vue écrire", () => {
  const exclude = S.exclusions("Dr Martin");
  assert.equal(S.admit(msg({ author: "Dr Martin" }), ctx({ exclude: exclude, people: ["Dr Martin"] })), "exclue");
  // son propre message dans ce tête-à-tête aussi
  assert.equal(S.admit(msg({ id: "m2", author: "Adrien", authorId: "8:orgid:self-uuid" }),
    ctx({ exclude: exclude, people: ["Dr Martin"] })), "exclue");
  // un groupe qui a un nom ne s'exclut pas parce qu'une personne exclue y écrit
  assert.equal(S.isExcluded({ conv: GROUP, title: "Projet Atlas", kind: "group", people: ["Dr Martin"] }, exclude), false);
  // un groupe sans sujet se nomme par ses membres
  assert.equal(S.isExcluded({ conv: GROUP, title: "", kind: "group", people: ["Dr Martin"] }, exclude), true);
  assert.equal(S.isExcluded({ conv: DM, title: "", kind: "dm", people: ["Alice"] }, exclude), false);
  assert.equal(S.isExcluded({ conv: DM, kind: "dm", people: ["Alice"] }, []), false);
});

test("avec des exclusions, un message attend qu'on sache nommer sa conversation, 2 min au plus", () => {
  const exclude = S.exclusions("RH");
  const queued = { id: "g1", conv: GROUP, at: NOW - 30000 };
  const unknown = { conv: GROUP, title: "", kind: "group", people: ["Bob"], known: false };
  assert.equal(S.held(queued, unknown, exclude, NOW), true);
  assert.equal(S.held(queued, unknown, exclude, NOW + S.LIMITS.holdMs), false, "passé le délai, on décide");
  assert.equal(S.held(queued, Object.assign({}, unknown, { known: true }), exclude, NOW), false, "nom appris");
  assert.equal(S.held(queued, unknown, [], NOW), false, "sans exclusion, rien n'attend");
  // un tête-à-tête se nomme par la personne d'en face
  const dm = { id: "d1", conv: DM, at: NOW - 1000 };
  assert.equal(S.held(dm, { conv: DM, kind: "dm", people: [] }, exclude, NOW), true);
  assert.equal(S.held(dm, { conv: DM, kind: "dm", people: ["Alice"] }, exclude, NOW), false);
  // une entrée d'avant cette version (sans date de capture) ne reste pas bloquée
  assert.equal(S.held({ id: "x", conv: GROUP }, unknown, exclude, NOW), false);
});

// ── Modifications et suppressions ───────────────────────────────────────────

test("un message modifié repart (même identifiant, autre texte) ; le même texte non", () => {
  const T = require("../lib/text.js");
  const original = msg({ text: "on part à 9h" });
  const seen = { [T.versionKey(original)]: original.time };
  assert.equal(S.admit(original, ctx({ seen: seen })), "déjà vu");
  assert.equal(S.admit(msg({ text: "on part à 10h" }), ctx({ seen: seen })), "");
  // une clé d'avant les versions (l'identifiant seul) vaut pour toutes les versions
  assert.equal(S.admit(msg({ text: "on part à 10h" }), ctx({ seen: { m1: NOW } })), "déjà vu");
});

test("une suppression part sans texte ; après elle, aucun texte du message ne repart", () => {
  const T = require("../lib/text.js");
  const deletion = msg({ text: "", deleted: true });
  assert.equal(S.admit(deletion, ctx()), "");
  const seen = { [T.versionKey(deletion)]: deletion.time };
  assert.equal(S.admit(deletion, ctx({ seen: seen })), "déjà vu");
  assert.equal(S.admit(msg({ text: "salut" }), ctx({ seen: seen })), "déjà vu");
  const wire = S.wireMessage(msg({ text: "", deleted: true, mentions: ["8:orgid:self-uuid"] }), SELF);
  assert.equal(wire.deleted, true);
  assert.equal(wire.text, "");
  assert.equal(wire.mentions_me, false);
  assert.equal(wire.id, "m1");
  assert.equal("deleted" in S.wireMessage(msg(), SELF), false, "un message ordinaire n'en porte pas la marque");
  const out = S.batches([msg({ id: "a", text: "", deleted: true })], { info: info, selfId: SELF });
  assert.equal(out[0].body.messages[0].deleted, true);
});

test("ce qui part n'a jamais une moitié d'emoji : texte, auteur, nom de conversation", () => {
  const lone = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
  const wire = S.wireMessage(msg({ text: "x".repeat(3999) + "😀", author: "a".repeat(118) + "🎉🎉" }), SELF);
  assert.equal(wire.text.length, 3999);
  assert.ok(!lone.test(wire.text) && !lone.test(wire.author));
  assert.ok(wire.author.length <= 120);
  const conv = S.wireConversation(GROUP, { title: "t".repeat(118) + "🚀🚀", kind: "group" });
  assert.ok(!lone.test(conv.title) && conv.title.length <= 120);
  assert.equal(S.clean("a".repeat(119) + "🙂", 120), "a".repeat(119) + "…");
});

// ── Le serveur ──────────────────────────────────────────────────────────────

test("la même erreur 5xx sur le même lot se compte ; une autre erreur ou un autre lot repart de 1", () => {
  let strike = null;
  for (let i = 1; i <= S.LIMITS.serverErrorsMax; i++) strike = S.serverStrike(strike, 500, "m1");
  assert.equal(strike.count, 8);
  assert.equal(S.serverStrike(strike, 502, "m1").count, 1);
  assert.equal(S.serverStrike(strike, 500, "m2").count, 1);
});

test("l'adresse de Mika : http seulement sur cette machine, https ailleurs", () => {
  assert.deepEqual(S.serverAddress("http://127.0.0.1:8001/api"), { origin: "http://127.0.0.1:8001", local: true });
  assert.deepEqual(S.serverAddress(" http://localhost:8001 "), { origin: "http://localhost:8001", local: true });
  assert.deepEqual(S.serverAddress("https://mika.example.org"), { origin: "https://mika.example.org", local: false });
  assert.deepEqual(S.serverAddress("https://127.0.0.1:8443"), { origin: "https://127.0.0.1:8443", local: true });
  assert.match(S.serverAddress("http://192.168.1.20:8001").error, /https/);
  assert.match(S.serverAddress("http://mika.lan").error, /https/);
  assert.match(S.serverAddress("http://[::1]:8001").error, /https/, "pas de permission d'hôte pour [::1]");
  assert.ok(S.serverAddress("ftp://127.0.0.1").error);
  assert.ok(S.serverAddress("pas une adresse").error);
});
