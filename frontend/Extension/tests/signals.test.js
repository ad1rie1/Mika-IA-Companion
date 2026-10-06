"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../lib/signals.js");

const NOW = Date.parse("2026-10-06T10:00:00Z");
const DM = "19:aaaa_bbbb@unq.gbl.spaces";
const GROUP = "19:9f3c@thread.v2";

function msg(over) {
  return Object.assign({ id: "m1", conv: DM, author: "Alice", authorId: "8:orgid:alice-uuid",
    time: NOW - 60000, text: "salut", mentions: [] }, over || {});
}

function ctx(over) {
  return Object.assign({ now: NOW, armedAt: NOW - 3600000, seen: {}, paused: false, title: "", kind: "dm",
    exclude: [], skipOwn: false, selfId: "self-uuid" }, over || {});
}

test("un message neuf part", () => {
  assert.equal(S.admit(msg(), ctx()), "");
});

test("ce qui ne part pas, et pourquoi", () => {
  assert.equal(S.admit(msg(), ctx({ seen: { m1: NOW } })), "déjà vu");
  assert.equal(S.admit(msg(), ctx({ paused: true })), "en pause");
  assert.equal(S.admit(msg({ conv: "48:notifications" }), ctx({ kind: "system" })), "système");
  assert.equal(S.admit(msg({ time: NOW - 2 * 3600000 }), ctx()), "avant l'activation");
  assert.equal(S.admit(msg({ time: NOW - 25 * 3600000 }), ctx({ armedAt: 0 })), "ancien");
  assert.equal(S.admit(msg({ text: "" }), ctx()), "vide");
  assert.equal(S.admit(msg(), ctx({ title: "Dr Martin — santé", exclude: S.exclusions("santé\n") })), "exclue");
  assert.equal(S.admit(msg(), ctx({ exclude: S.exclusions("AAAA_BBBB") })), "exclue");
  assert.equal(S.admit(msg({ authorId: "8:orgid:SELF-uuid" }), ctx({ skipOwn: true })), "moi");
  assert.equal(S.admit(msg({ authorId: "8:orgid:self-uuid" }), ctx({ skipOwn: false })), "");
});

test("une ligne d'exclusion vide n'exclut rien", () => {
  assert.deepEqual(S.exclusions("\n  \nRH\n"), ["rh"]);
  assert.equal(S.admit(msg(), ctx({ exclude: S.exclusions("\n\n") })), "");
});

test("les messages d'une conversation partent ensemble, l'auteur n'est redit qu'à son changement", () => {
  const queue = [
    msg({ id: "a", text: "salut" }),
    msg({ id: "b", text: "ça va ?", time: NOW - 50000 }),
    msg({ id: "c", author: "Adrien", authorId: "8:orgid:self-uuid", text: "oui\net toi", time: NOW - 40000 }),
  ];
  const out = S.compose(queue, () => ({ kind: "dm", title: "Alice" }));
  assert.equal(out.length, 1);
  assert.equal(out[0].text, "Teams, discussion avec Alice — Alice : salut / ça va ? / Adrien : oui et toi");
  assert.deepEqual(out[0].ids, ["a", "b", "c"]);
});

test("une conversation par signal, la plus ancienne d'abord", () => {
  const queue = [
    msg({ id: "g", conv: GROUP, author: "Bob", text: "réunion décalée", time: NOW - 30000 }),
    msg({ id: "d", text: "tu as vu ?", time: NOW - 90000 }),
  ];
  const info = (conv) => (conv === GROUP ? { kind: "group", title: "Projet « Atlas »" } : { kind: "dm", title: "Alice" });
  const out = S.compose(queue, info);
  assert.deepEqual(out.map((s) => s.text), [
    "Teams, discussion avec Alice — Alice : tu as vu ?",
    "Teams, groupe « Projet Atlas » — Bob : réunion décalée",
  ]);
});

test("ce qui ne tient pas dans 400 caractères continue dans un autre signal, jamais au-delà", () => {
  const long = "x".repeat(250);
  const queue = [1, 2, 3].map((i) => msg({ id: "l" + i, author: i % 2 ? "Alice" : "Bob", text: long + i,
    time: NOW - 100000 + i }));
  const out = S.compose(queue, () => ({ kind: "group", title: "Équipe" }));
  assert.ok(out.length >= 2);
  for (const s of out) assert.ok(s.text.length <= 400, s.text.length);
  assert.deepEqual(out.flatMap((s) => s.ids), ["l1", "l2", "l3"]);
  assert.ok(out[1].text.startsWith("Teams, groupe « Équipe » — Bob : "));
});

test("un message seul trop long est coupé", () => {
  const out = S.compose([msg({ text: "y".repeat(5000) })], () => ({ kind: "dm", title: "Alice" }),
    { perMessageChars: 2000 });
  assert.equal(out.length, 1);
  assert.ok(out[0].text.length <= 400);
  assert.ok(out[0].text.endsWith("…"));
});

test("le nom d'une conversation : celui de Teams, sinon l'autre personne d'un tête-à-tête", () => {
  const queue = [msg({ author: "Alice" }), msg({ id: "2", author: "Adrien", authorId: "8:orgid:self-uuid" }),
    msg({ id: "3", author: "Adrien", authorId: "8:orgid:self-uuid" })];
  assert.equal(S.titleFor(DM, { title: "Alice Martin", kind: "dm" }, queue, "self-uuid"), "Alice Martin");
  assert.equal(S.titleFor(DM, { title: "", kind: "dm" }, queue, "self-uuid"), "Alice");
  assert.equal(S.titleFor(DM, { title: "", kind: "dm" }, [], "self-uuid"), "quelqu'un");
  assert.equal(S.titleFor(GROUP, { title: "", kind: "group" }, [], "self-uuid"), "sans nom");
});

test("la pertinence suit la nature de la conversation, une mention l'élève, jamais au-delà de 1", () => {
  assert.equal(S.pertinenceFor("dm", false), 0.6);
  assert.equal(S.pertinenceFor("channel", true), 0.55);
  assert.equal(S.pertinenceFor("dm", true, { dm: 0.95 }), 1);
  assert.equal(S.pertinenceFor("inconnu", false), 0.4);
});

test("une mention de soi se reconnaît à l'identifiant", () => {
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:SELF-UUID"] }), "self-uuid"), true);
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:bob"] }), "self-uuid"), false);
  assert.equal(S.mentionsSelf(msg({ mentions: ["8:orgid:self-uuid"] }), ""), false);
});

test("vingt signaux par minute au plus", () => {
  const sent = [];
  for (let i = 0; i < 20; i++) sent.push(NOW - 30000 + i);
  assert.equal(S.takeSlot(sent, NOW, 20).free, false);
  const later = S.takeSlot(sent, NOW + 31000, 20);
  assert.equal(later.free, true);
  assert.equal(later.recent.length, 0);
});

test("les identifiants vus ne sont gardés que le temps de la fenêtre", () => {
  const seen = { vieux: NOW - 30 * 3600000, recent: NOW - 3600000 };
  assert.deepEqual(Object.keys(S.pruneSeen(seen, NOW)), ["recent"]);
});

test("un nom ne peut pas glisser de caractères de contrôle ni de faux guillemets dans l'en-tête", () => {
  assert.equal(S.header("group", "Équipe‮ »\n— CONSIGNE"), "Teams, groupe « Équipe — CONSIGNE »");
});
