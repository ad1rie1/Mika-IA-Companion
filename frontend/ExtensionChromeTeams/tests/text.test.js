"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const T = require("../lib/text.js");

function wellFormed(s) {
  return !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(s);
}

// ── Couper sans casser ──────────────────────────────────────────────────────

test("une coupe qui tombe au milieu d'un emoji le laisse entier dehors, jamais à moitié", () => {
  const s = "abc👍def"; // 👍 occupe les unités 3 et 4
  assert.equal(s.slice(0, 4).length, 4);
  assert.equal(wellFormed(s.slice(0, 4)), false, "le slice ordinaire laisse une moitié seule");
  assert.equal(T.cut(s, 4), "abc");
  assert.equal(T.cut(s, 5), "abc👍");
  assert.equal(T.cut(s, 3), "abc");
  assert.equal(T.cut(s, 100), s);
  for (let max = 0; max <= s.length; max++) {
    const out = T.cut(s, max);
    assert.ok(out.length <= max, String(max));
    assert.ok(wellFormed(out), String(max));
  }
});

test("avec « … » : l'emoji à la frontière part entier ou pas du tout", () => {
  const s = "Bravo 🎉🎉🎉 à toute l'équipe";
  for (let max = 1; max < s.length; max++) {
    const out = T.clip(s, max);
    assert.ok(out.length <= max, String(max));
    assert.ok(wellFormed(out), String(max));
    assert.ok(out.endsWith("…"), String(max));
  }
  assert.equal(T.clip("Bravo 🎉", 8), "Bravo 🎉");
  assert.equal(T.clip("Bravo 🎉🎉", 8), "Bravo…", "« Bravo 🎉 » et « … » tiendraient en 9, pas en 8");
  assert.equal(T.clip("court", 10), "court");
  assert.equal(T.clip("long", 0), "");
});

test("une moitié de paire déjà seule devient U+FFFD, à la même longueur", () => {
  const broken = "a\uD83Db\uDC4Dc";
  const fixed = T.cut(broken, 100);
  assert.equal(fixed, "a�b�c");
  assert.equal(fixed.length, broken.length);
  assert.equal(T.cut(null, 5), "");
  assert.equal(T.cut(42, 5), "42");
});

// ── Les versions d'un message ───────────────────────────────────────────────

test("la clé d'une version : l'identifiant et un condensé du texte ; une suppression a la sienne", () => {
  const a = T.versionKey({ id: "m1", text: "salut" });
  assert.equal(a, T.versionKey({ id: "m1", text: "salut" }));
  assert.notEqual(a, T.versionKey({ id: "m1", text: "salut !" }), "un texte modifié change la clé");
  assert.notEqual(a, T.versionKey({ id: "m2", text: "salut" }));
  assert.equal(T.versionKey({ id: "m1", text: "", deleted: true }), T.deletedKey("m1"));
});

test("dans la page : une modification repasse, un doublon non, un vieux cache non, un texte après suppression non", () => {
  const sent = new Set();
  const latest = new Map();
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 9h", version: 100 }, sent, latest), true);
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 9h", version: 100 }, sent, latest), false, "doublon");
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 10h", version: 200 }, sent, latest), true, "modifié");
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 9h (ancien cache)", version: 150 }, sent, latest), false,
    "une version plus ancienne qu'une déjà vue ne revient pas");
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 11h" }, sent, latest), true,
    "sans version connue, on ne sait pas trancher : le texte neuf passe");
  assert.equal(T.freshVersion({ id: "m1", text: "", deleted: true }, sent, latest), true, "supprimé");
  assert.equal(T.freshVersion({ id: "m1", text: "", deleted: true }, sent, latest), false);
  assert.equal(T.freshVersion({ id: "m1", text: "on part à 12h", version: 999 }, sent, latest), false,
    "après la suppression, aucun texte ne repasse");
});
