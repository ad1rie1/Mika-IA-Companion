"use strict";
// Les profils des personnes (ADR 0298) : lus dans la base que Teams garde, joints aux lots avec les messages de ces
// personnes, vérifiés par le relais.
const test = require("node:test");
const assert = require("node:assert/strict");
const X = require("../lib/extract.js");
const S = require("../lib/signals.js");

const GILLES = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab";
const SOPHIE = "8:orgid:11111111-2222-3333-4444-555555555555";

test("un profil de Teams : son identifiant, son nom, son e-mail (sinon celui de connexion), son poste, ses numéros", () => {
  const p = X.profileOf({ mri: GILLES.toUpperCase(), displayName: "  Gilles   ROUSSEAU ", userPrincipalName: "G.Rousseau@Nordis.fr",
    jobTitle: "Responsable réseau", companyName: "Nordis", department: "Réseau", tenantName: "Nordis SAS",
    telephoneNumber: "+33 6 12 34 56 78", phones: [{ number: "+33 6 12 34 56 78" }, { number: "01 84 00 00 00" }], mobile: "12" });
  assert.deepEqual(p, { id: GILLES, name: "Gilles ROUSSEAU", email: "g.rousseau@nordis.fr", title: "Responsable réseau",
    company: "Nordis", department: "Réseau", tenant: "Nordis SAS", phones: ["+33 6 12 34 56 78", "01 84 00 00 00"] });
  // l'e-mail l'emporte sur l'identifiant de connexion ; un e-mail mal formé ne passe pas
  assert.equal(X.profileOf({ mri: GILLES, displayName: "G", email: "gilles@nordis.fr", userPrincipalName: "x@y.fr" }).email,
    "gilles@nordis.fr");
  assert.equal(X.profileOf({ mri: GILLES, displayName: "G", email: "pas un e-mail" }).email, "");
});

test("sans identifiant reconnu, ou sans rien qui dise qui c'est, pas de profil", () => {
  assert.equal(X.profileOf({ mri: "28:bot-quelconque", displayName: "Un robot" }), null);
  assert.equal(X.profileOf({ displayName: "Sans identifiant" }), null);
  assert.equal(X.profileOf({ mri: GILLES }), null);
  assert.equal(X.profileOf("texte"), null);
});

function message(id, author, mentions) {
  return { id: String(id), conv: "19:a@thread.v2", author: "Quelqu'un", authorId: author, time: 1700000000000 + id,
    text: "bonjour", mentions: mentions || [] };
}

test("chaque lot joint, une fois, le profil des auteurs et des mentionnés de ses messages", () => {
  const known = { [GILLES]: { id: GILLES, name: "Gilles Rousseau", email: "gilles@nordis.fr", phones: [] },
    [SOPHIE]: { id: SOPHIE, name: "Sophie Lambert", email: "sophie@calix.fr", phones: [] } };
  const list = S.batches([message(1, GILLES), message(2, GILLES, [SOPHIE]), message(3, "8:orgid:inconnu")],
    { profile: (id) => known[id] || null });
  assert.equal(list.length, 1);
  assert.deepEqual(list[0].body.profiles.map((p) => p.id), [GILLES, SOPHIE]);
  assert.deepEqual(list[0].profiles, [GILLES, SOPHIE]);
  assert.equal(list[0].body.profiles[0].email, "gilles@nordis.fr");
  // sans profils à joindre, le corps n'en dit rien
  const none = S.batches([message(1, GILLES)], { profile: () => null });
  assert.equal(none[0].body.profiles, undefined);
  assert.deepEqual(none[0].profiles, []);
  // un message supprimé ne fait partir aucun profil
  const deleted = S.batches([Object.assign(message(4, GILLES), { deleted: true, text: "" })], { profile: (id) => known[id] });
  assert.equal(deleted[0].body.profiles, undefined);
});

test("un profil compte dans le plafond d'octets du lot : s'il ne tient plus, il attend le prochain envoi", () => {
  const big = { id: GILLES, name: "G".repeat(120), email: "gilles@nordis.fr", title: "T".repeat(120), phones: [] };
  const wire = S.wireMessage(message(1, GILLES));
  const empty = S.utf8Length(JSON.stringify({ self: { id: "", name: "" }, conversations: [], messages: [] }));
  const conv = S.utf8Length(JSON.stringify(S.wireConversation("19:a@thread.v2", null))) + 1;
  const maxBytes = empty + S.utf8Length(JSON.stringify(wire)) + 1 + conv + 20; // le message tient, pas son profil
  const list = S.batches([message(1, GILLES)], { profile: () => big, maxBytes: maxBytes });
  assert.equal(list[0].body.messages.length, 1);
  assert.equal(list[0].body.profiles, undefined);
});

test("un nom de connexion d'invité n'est pas une adresse (relecture de l'ADR 0298, I10)", () => {
  // « x_gmail.com#ext#@hote.onmicrosoft.com » : l'identifiant d'un invité chez un autre locataire, pas son e-mail
  assert.equal(X.profileOf({ mri: GILLES, displayName: "Invité", userPrincipalName: "x_gmail.com#EXT#@hote.onmicrosoft.com" })
    .email, "");
  assert.equal(X.profileOf({ mri: GILLES, displayName: "Jean", userPrincipalName: "jean@lumen.onmicrosoft.com" }).email,
    "jean@lumen.onmicrosoft.com");
});
