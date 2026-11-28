"use strict";
// Les réactions d'un message et l'empreinte de la photo d'un profil (ADR 0300) : ce que l'extracteur en lit, la clé de
// version qui fait repartir un message dont les réactions ont changé, et ce qui part vers Mika.
const test = require("node:test");
const assert = require("node:assert/strict");
const X = require("../lib/extract.js");
const T = require("../lib/text.js");
const S = require("../lib/signals.js");

const SELF = "3e51ce13-6eb8-463b-a75a-a40b2ab67602";
const ME = "8:orgid:" + SELF;
const GILLES = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab";
const SOPHIE = "8:orgid:11111111-2222-3333-4444-555555555555";

function raw(props) {
  return { id: "1800000000001", conversationid: "19:projet@thread.v2", messagetype: "RichText/Html",
    content: "<p>La démo tourne 🎉</p>", originalarrivaltime: "2026-11-22T10:00:00.000Z", imdisplayname: "Karim",
    from: "https://emea.ng.msg.teams.microsoft.com/v1/users/ME/contacts/8:orgid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    properties: props };
}

test("les réactions se lisent en texte JSON comme en liste : qui, combien, la sienne", () => {
  const emotions = [
    { key: "like", users: [{ mri: SOPHIE, time: 1800000000003, value: 3 },
      { mri: GILLES.toUpperCase(), time: 1800000000001, value: 1 }, { mri: "orgid:" + SELF, time: "1800000000002" }] },
    { key: "heart", users: [{ mri: GILLES, time: 1800000000005, value: 5 }] },
  ];
  for (const form of [emotions, JSON.stringify(emotions)]) {
    const m = X.normalizeMessage(raw({ emotions: form }), "", SELF);
    assert.deepEqual(m.reactions, [
      { key: "like", count: 3, mine: true, by: [GILLES, ME, SOPHIE] }, // les premiers à l'avoir posée d'abord
      { key: "heart", count: 1, mine: false, by: [GILLES] },
    ]);
  }
  // sans soi connu, rien n'est « à soi » ; `extract` passe soi comme la page le lui donne
  assert.equal(X.normalizeMessage(raw({ emotions }), "").reactions[0].mine, false);
  assert.equal(X.extract([raw({ emotions })], { self: SELF }).messages[0].reactions[0].mine, true);
});

test("des réactions bornées : 20 clés, dix personnes chacune (leur nombre entier), une clé illisible écartée", () => {
  const users = Array.from({ length: 14 }, (_, i) => ({ mri: `8:orgid:00000000-0000-4000-8000-${String(i).padStart(12, "0")}`, time: i }));
  const many = Array.from({ length: 25 }, (_, i) => ({ key: "k" + i, users: [{ mri: GILLES }] }));
  const m = X.normalizeMessage(raw({ emotions: [{ key: "like", users: users.concat(users) },
    { key: "<script>", users: [{ mri: GILLES }] }, { key: "sad", users: [] }, ...many] }), "");
  assert.equal(m.reactions.length, 20);
  assert.deepEqual([m.reactions[0].count, m.reactions[0].by.length], [14, 10], "chacun compté une fois");
  assert.ok(m.reactions.every((r) => r.key !== "<script>" && r.key !== "sad"), "illisible, ou plus personne");
});

test("sans liste, le seul compte ; rien de dit : `undefined` (le serveur garde ce qu'il savait) ; vide : aucune", () => {
  const counted = X.normalizeMessage({ ...raw({}), annotationsSummary: { emotions: { like: 3, heart: "1", x: 0 } } }, "");
  assert.deepEqual(counted.reactions, [{ key: "like", count: 3, mine: false, by: [] },
    { key: "heart", count: 1, mine: false, by: [] }]);
  assert.equal(X.normalizeMessage(raw({}), "").reactions, undefined);
  assert.deepEqual(X.normalizeMessage(raw({ emotions: "[]" }), "").reactions, []);
  assert.equal(X.normalizeMessage(raw({ emotions: "{pas du json" }), "").reactions, undefined);
});

test("la version d'un message est la plus tardive de ses dates : une réaction fait avancer `version`", () => {
  const m = X.normalizeMessage(raw({}), "");
  assert.equal(m.version, 0);
  const edited = X.normalizeMessage({ ...raw({}), edittime: "1800000000100", version: "1800000000900" }, "");
  assert.equal(edited.version, 1800000000900);
});

test("un profil porte l'empreinte de sa photo, sans guillemets ; une empreinte illisible n'est pas gardée", () => {
  const base = { mri: GILLES, displayName: "Gilles Rousseau" };
  assert.equal(X.profileOf({ ...base, avatarETag: "\"0x8DCF1A2B3C\"" }).avatar, "0x8DCF1A2B3C");
  assert.equal(X.profileOf({ ...base, avatarETag: "W/\"abc+/=\"" }).avatar, "abc+/=");
  assert.equal(X.profileOf({ ...base, avatarETag: "<img onerror>" }).avatar, undefined);
  assert.equal(X.profileOf(base).avatar, undefined);
  assert.equal(S.wireProfile({ id: GILLES, name: "Gilles", avatar: "0x8D" }).avatar, "0x8D");
  assert.equal("avatar" in S.wireProfile({ id: GILLES, name: "Gilles" }), false, "sans photo, l'empreinte d'avant");
});

test("la clé de version suit les réactions ; sans réactions dites, elle reste celle d'avant", () => {
  const plain = { id: "m1", text: "la démo tourne" };
  const before = T.versionKey(plain);
  assert.equal(before, "m1#" + T.hash("la démo tourne"), "un message sans réactions dites : la clé d'avant");
  const liked = T.versionKey({ ...plain, reactions: [{ key: "like", count: 1, mine: false, by: [GILLES] }] });
  const loved = T.versionKey({ ...plain, reactions: [{ key: "like", count: 2, mine: true, by: [GILLES, ME] }] });
  const none = T.versionKey({ ...plain, reactions: [] });
  assert.equal(new Set([before, liked, loved, none]).size, 4);
  assert.ok(liked.startsWith("m1#" + T.hash("la démo tourne")), "le même message, le même texte");
});

test("dans la page : une réaction neuve repasse ; retirée, elle repasse si la version est plus récente ; un vieux cache non", () => {
  const sent = new Set();
  const latest = new Map();
  const at = (version, reactions) => ({ id: "m1", text: "la démo tourne", version: version, reactions: reactions });
  const like = [{ key: "like", count: 1, mine: false, by: [GILLES] }];
  assert.equal(T.freshVersion(at(100, []), sent, latest), true);
  assert.equal(T.freshVersion(at(100, []), sent, latest), false, "doublon");
  assert.equal(T.freshVersion(at(200, like), sent, latest), true, "une réaction : le même message repasse");
  assert.equal(T.freshVersion(at(100, []), sent, latest), false, "le vieux cache (sans la réaction) ne revient pas");
  assert.equal(T.freshVersion(at(300, []), sent, latest), true, "retirée : la même clé qu'avant, mais plus récente");
  assert.equal(T.freshVersion(at(300, []), sent, latest), false);
  assert.equal(T.freshVersion({ id: "m1", text: "la démo tourne", reactions: like }, sent, latest), false,
    "sans version, une clé déjà passée ne repasse pas : on ne saurait pas laquelle est la plus récente");
});

test("ce qui part : les réactions dites, bornées, la sienne reconnue à l'identifiant de soi ; rien pour une suppression", () => {
  const m = { id: "1800000000001", conv: "19:projet@thread.v2", author: "Karim", authorId: GILLES, time: 1, text: "x",
    reactions: [{ key: "like", count: 2, mine: false, by: [GILLES, ME] }, { key: "heart", count: 0, by: [] },
      { key: "laugh", count: 40, by: Array.from({ length: 12 }, (_, i) => "8:live:p" + i) }] };
  const wire = S.wireMessage(m, SELF);
  assert.deepEqual(wire.reactions, [{ key: "like", count: 2, mine: true, by: [GILLES, ME] },
    { key: "laugh", count: 40, mine: false, by: Array.from({ length: 10 }, (_, i) => "8:live:p" + i) }]);
  assert.equal("reactions" in S.wireMessage({ ...m, reactions: undefined }, SELF), false, "rien de dit, rien ne part");
  assert.deepEqual(S.wireMessage({ ...m, reactions: [] }, SELF).reactions, [], "aucune : le serveur efface les siennes");
  assert.equal("reactions" in S.wireMessage({ ...m, deleted: true, text: "" }, SELF), false);
});

test("le service : une clé déjà vue repart seulement plus récente ; une version plus ancienne qu'une déjà vue jamais", () => {
  const now = Date.now();
  const ranks = {};
  const seen = {};
  const ctx = { now: now, armedAt: 0, seen: seen, ranks: ranks, pauses: [], exclude: [] };
  const m = (version, reactions) => ({ id: "1800000000001", conv: "19:projet@thread.v2", time: now, text: "x",
    version: version, reactions: reactions });
  const pass = (msg) => {
    const why = S.admit(msg, ctx);
    if (!why) {
      seen[T.versionKey(msg)] = msg.time;
      S.noteRank(ranks, msg);
    }
    return why;
  };
  const like = [{ key: "like", count: 1, mine: false, by: [GILLES] }];
  assert.equal(pass(m(100, [])), "");
  assert.equal(pass(m(200, like)), "", "une réaction : il repart");
  assert.equal(pass(m(150, [])), "déjà vu", "un cache en retard");
  assert.equal(pass(m(300, [])), "", "retirée : il repart");
  assert.equal(pass(m(300, [])), "déjà vu");
  const heart = [{ key: "heart", count: 1, mine: false, by: [SOPHIE] }];
  assert.equal(pass(m(0, heart)), "", "sans version, une clé neuve part (comme avant)");
  assert.equal(pass(m(0, heart)), "déjà vu");
  assert.equal(pass(m(0, like)), "déjà vu", "sans version, une clé déjà vue ne repart pas");
  assert.deepEqual(Object.keys(S.pruneRanks(ranks, now + 30 * 24 * 3600 * 1000)), [], "oubliées avec la fenêtre");
});
