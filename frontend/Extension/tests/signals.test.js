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
