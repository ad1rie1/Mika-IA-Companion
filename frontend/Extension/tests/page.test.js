"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../lib/page.js");

const GROUP = "19:9f3c@thread.v2";
const DM = "19:aaaa_bbbb@unq.gbl.spaces";
const CHAT = "https://emea.ng.msg.teams.microsoft.com/v1/users/ME/conversations/" + encodeURIComponent(GROUP)
  + "/messages?view=msnp24Equivalent";

// ── L'authentification que le client utilise ────────────────────────────────

test("les en-têtes d'authentification : un objet Headers, une liste de paires ou un objet", () => {
  const h = new Headers({ "Authentication": "skypetoken=abc", "Content-Type": "application/json" });
  assert.deepEqual(P.authFromHeaders(h), { authentication: "skypetoken=abc" });
  assert.deepEqual(P.authFromHeaders([["X-Skypetoken", "tok"], ["accept", "json"]]), { "x-skypetoken": "tok" });
  assert.deepEqual(P.authFromHeaders({ Authorization: "Bearer eyJ", behavioroverride: "redirectAs404" }),
    { authorization: "Bearer eyJ" });
  assert.deepEqual(P.authFromHeaders({ authentication: "skypetoken=a", authorization: "Bearer b" }),
    { authentication: "skypetoken=a", authorization: "Bearer b" });
});

test("pas d'en-tête d'authentification, ou un vide : rien", () => {
  assert.equal(P.authFromHeaders(undefined), null);
  assert.equal(P.authFromHeaders({ accept: "json" }), null);
  assert.equal(P.authFromHeaders({ authorization: "  " }), null);
  assert.equal(P.authFromHeaders([["authorization"]]), null);
  assert.equal(P.isAuthHeader("AUTHENTICATION"), true);
  assert.equal(P.isAuthHeader("cookie"), false);
});

test("la base du service de chat, d'une adresse absolue ou relative ; jamais en http", () => {
  assert.equal(P.isChatServiceUrl(CHAT), true);
  assert.equal(P.isChatServiceUrl("https://teams.microsoft.com/api/mt/emea/beta/users/tenants"), false);
  assert.equal(P.chatServiceBase(CHAT), "https://emea.ng.msg.teams.microsoft.com");
  assert.equal(P.chatServiceBase("/api/chatsvc/emea/v1/users/ME/conversations?view=x", "https://teams.microsoft.com/v2/"),
    "https://teams.microsoft.com/api/chatsvc/emea");
  assert.equal(P.chatServiceBase("http://evil.test/v1/users/ME/conversations"), "");
  assert.equal(P.chatServiceBase("https://teams.microsoft.com/api/mt/"), "");
  assert.equal(P.chatServiceBase("pas une adresse"), "");
});

// ── Ce qui part ─────────────────────────────────────────────────────────────

test("le contenu d'un envoi : HTML échappé, retours à la ligne en <br>", () => {
  assert.equal(P.messageContent("a < b && c > \"d\" 'e'"), "a &lt; b &amp;&amp; c &gt; &quot;d&quot; &#39;e&#39;");
  assert.equal(P.messageContent("ligne 1\nligne 2\r\nligne 3\rfin"), "ligne 1<br>ligne 2<br>ligne 3<br>fin");
  assert.equal(P.messageContent("<img src=x onerror=alert(1)>"), "&lt;img src=x onerror=alert(1)&gt;");
});

test("le corps d'un envoi au service de chat", () => {
  const body = P.messageBody("Oui\n— Mika", "Adrien Martin", "1234567890123456789");
  assert.deepEqual(body, { content: "Oui<br>— Mika", messagetype: "RichText/Html", contenttype: "text",
    clientmessageid: "1234567890123456789", imdisplayname: "Adrien Martin" });
});

test("l'identifiant client d'un élément : 19 chiffres, le premier jamais nul, le même à chaque tentative", () => {
  const a = P.clientMessageIdFor("t0123456789ab");
  assert.match(a, /^[1-9]\d{18}$/);
  assert.equal(P.clientMessageIdFor("t0123456789ab"), a, "stable : une seconde tentative reste reconnaissable");
  assert.notEqual(P.clientMessageIdFor("t0123456789ac"), a);
  const seen = new Set();
  for (let i = 0; i < 2000; i++) {
    const id = P.clientMessageIdFor("t" + i.toString(16).padStart(12, "0"));
    assert.match(id, /^[1-9]\d{18}$/);
    seen.add(id);
  }
  assert.equal(seen.size, 2000, "pas de collision sur 2000 éléments");
  assert.match(P.clientMessageIdFor(""), /^[1-9]\d{18}$/);
});

test("la réponse du service de chat à un envoi : sûre (envoyé, refusé) ou douteuse", () => {
  for (const s of [200, 201, 202]) assert.equal(P.chatSendOutcome(s), "sent", String(s));
  // l'authentification vue est périmée : rien n'est parti, la zone de saisie peut prendre le relais
  for (const s of [401, 403]) assert.equal(P.chatSendOutcome(s), "auth", String(s));
  for (const s of [400, 404, 413, 422]) assert.equal(P.chatSendOutcome(s), "failed", String(s));
  // peut-être parti : jamais retenté
  for (const s of [408, 429, 500, 502, 503, 504, 0, 302]) assert.equal(P.chatSendOutcome(s), "uncertain", String(s));
});

test("l'authentification n'est retenue que pour un hôte de Teams", () => {
  for (const h of ["teams.microsoft.com", "emea.ng.msg.teams.microsoft.com", "teams.cloud.microsoft",
    "eu.teams.cloud.microsoft", "teams.live.com", "msgapi.teams.live.com", "client-s.gateway.messenger.live.com.skype.com",
    "api.asm.skype.com", "teams.microsoft.us", "gov.teams.microsoft.us", "TEAMS.MICROSOFT.COM"]) {
    assert.equal(P.isChatServiceHost(h), true, h);
  }
  for (const h of ["evil.test", "teams.microsoft.com.evil.test", "evilteams.microsoft.com", "microsoft.com",
    "notskype.com", "skype.com.evil.test", ""]) {
    assert.equal(P.isChatServiceHost(h), false, h);
  }
  assert.equal(P.chatServiceBase("https://evil.test/api/v1/users/ME/conversations"), "");
  assert.equal(P.chatServiceBase("https://teams.microsoft.com.evil.test/v1/users/ME/conversations"), "");
  assert.equal(P.chatServiceBase("/v1/users/ME/conversations", "https://evil.test/"), "");
  assert.equal(P.chatServiceBase("https://api.asm.skype.com/v1/users/ME/conversations"), "https://api.asm.skype.com");
});

test("l'identifiant du message envoyé, tiré de la réponse", () => {
  assert.equal(P.messageIdFrom({ OriginalArrivalTime: 1759737600000 }, null), "1759737600000");
  assert.equal(P.messageIdFrom({ id: "42" }, null), "42");
  assert.equal(P.messageIdFrom(null, "https://x/v1/users/ME/conversations/19%3Aa/messages/1759737600123"),
    "1759737600123");
  assert.equal(P.messageIdFrom({}, ""), "");
});

// ── La conversation ouverte ─────────────────────────────────────────────────

function entry(id) {
  return { activeEntities: { mainEntity: { id: id, type: "chat" } }, route: "/conversations" };
}

test("l'historique de navigation : une entrée, une liste, une paire [entrées, index], un objet avec index", () => {
  assert.equal(P.activeConversationFromNav(JSON.stringify(entry(GROUP))), GROUP);
  assert.equal(P.activeConversationFromNav(JSON.stringify([entry(DM), entry(GROUP)])), GROUP, "la dernière");
  assert.equal(P.activeConversationFromNav(JSON.stringify([Object.assign(entry(DM), { isCurrent: true }), entry(GROUP)])),
    DM, "celle marquée courante");
  assert.equal(P.activeConversationFromNav(JSON.stringify([[entry(DM), entry(GROUP)], 0])), DM);
  assert.equal(P.activeConversationFromNav(JSON.stringify({ history: [entry(DM), entry(GROUP)], index: 0 })), DM);
  assert.equal(P.activeConversationFromNav(JSON.stringify({ entries: [entry(DM), entry(GROUP)], currentIndex: 9 })),
    GROUP, "un index hors liste : la dernière");
  assert.equal(P.activeConversationFromNav(JSON.stringify({ current: entry(DM) })), DM);
});

test("un historique illisible ou sans conversation : rien", () => {
  assert.equal(P.activeConversationFromNav("{pas du json"), "");
  assert.equal(P.activeConversationFromNav("[]"), "");
  assert.equal(P.activeConversationFromNav(JSON.stringify(entry("calendar"))), "");
  assert.equal(P.activeConversationFromNav(JSON.stringify({ activeEntities: {} })), "");
  assert.equal(P.activeConversationFromNav("null"), "");
});

test("le sessionStorage : seule la clé de l'historique de la fenêtre principale compte", () => {
  const pairs = [
    ["tmp.session.0f3c9a1e-1111-2222-3333-444455556666-otherThing", JSON.stringify(entry(DM))],
    ["tmp.session.0f3c9a1e-1111-2222-3333-444455556666-mainWindowNavHistory", JSON.stringify([entry(GROUP)])],
  ];
  assert.equal(P.activeConversationFromStorage(pairs), GROUP);
  assert.equal(P.activeConversationFromStorage(pairs.slice(0, 1)), "");
  assert.equal(P.activeConversationFromStorage([]), "");
});

test("la conversation que nomme l'adresse de la page", () => {
  assert.equal(P.conversationFromLocation("https://teams.microsoft.com/l/chat/" + encodeURIComponent(GROUP) + "/0"), GROUP);
  assert.equal(P.conversationFromLocation("https://teams.microsoft.com/_#/conversations/" + DM + "?ctx=chat"), DM);
  assert.equal(P.conversationFromLocation("https://teams.microsoft.com/v2/?threadId=" + encodeURIComponent(GROUP)), GROUP);
  assert.equal(P.conversationFromLocation("https://teams.microsoft.com/v2/"), "");
});

test("deux identifiants de la même conversation", () => {
  assert.equal(P.sameConversation("19:ABC@thread.v2", "19:abc@thread.v2"), true);
  assert.equal(P.sameConversation(GROUP, DM), false);
  assert.equal(P.sameConversation("", ""), false);
});

// ── La synchro ciblée (ADR 0251) ─────────────────────────────────────────────

test("la marque d'une fiche de conversation change quand un message y arrive, y est retouché ou retiré", () => {
  const r = { id: GROUP, version: 7, threadVersion: 3, lastUpdatedMessageVersion: 100, lastMessageTimeUtc: 1759737600000 };
  const m = P.conversationMarker(r);
  assert.equal(P.conversationMarker({ ...r }), m, "la même fiche, la même marque");
  assert.notEqual(P.conversationMarker({ ...r, lastMessageTimeUtc: 1759737600001 }), m);
  assert.notEqual(P.conversationMarker({ ...r, lastUpdatedMessageVersion: 101 }), m, "une retouche");
  assert.equal(P.conversationMarker(null), "");
});

test("ce qu'il faut relire : rien si la fiche n'a pas bougé, depuis le curseur, la fenêtre, ou tout", () => {
  const opts = { windowMs: 86_400_000, overlapMs: 60_000 };
  const now = 1_800_000_000_000;
  assert.equal(P.syncSince("m1", { w: 1_799_000_000_000, m: "m1" }, now, opts), null);
  assert.equal(P.syncSince("m2", { w: 1_799_000_000_000, m: "m1" }, now, opts), 1_799_000_000_000 - 60_000);
  assert.equal(P.syncSince("m2", undefined, now, opts), now - 86_400_000, "une conversation inconnue : la fenêtre");
  assert.equal(P.syncSince("m2", { w: 0, m: "" }, now, opts), now - 86_400_000);
  assert.equal(P.syncSince("m1", { w: 1_799_000_000_000, m: "m1" }, now, { ...opts, history: true }), 0);
  assert.equal(P.syncSince("", { w: 5, m: "" }, now, opts), 0, "sans marque, on relit toujours (du curseur)");
});

test("le curseur n'avance jamais en arrière, et ne prend la marque que si les fils ont suivi la fiche", () => {
  assert.deepEqual(P.advanceCursor({ w: 500, m: "a" }, 440, 0, "b"), { w: 500, m: "b" });
  assert.deepEqual(P.advanceCursor({ w: 500, m: "a" }, 440, 900, "b"), { w: 900, m: "b" });
  assert.deepEqual(P.advanceCursor(undefined, 300, 0, "b"), { w: 300, m: "b" }, "une inconnue part de la fenêtre lue");
  assert.equal(P.caughtUp({ lastMessageTimeUtc: 10_000 }, 9_000, 5_000), true);
  assert.equal(P.caughtUp({ lastMessageTimeUtc: 10_000 }, 4_000, 5_000), false, "la fiche est en avance sur ses fils");
  assert.equal(P.caughtUp({}, 0, 5_000), true);
});

// ── Les photos de profil (ADR 0300) ─────────────────────────────────────────

const SELF_UUID = "3e51ce13-6eb8-463b-a75a-a40b2ab67602";
const AVATAR = `https://teams.cloud.microsoft/api/mt/part/emea-02/beta/users/${SELF_UUID}/profilepicturev2/8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab?displayname=Gilles&size=HR64x64&avatarETag=abc`;

test("la base des avatars se lit sur un avatar de la page : sur son origine, et pour soi seulement", () => {
  const base = `https://teams.cloud.microsoft/api/mt/part/emea-02/beta/users/${SELF_UUID}`;
  assert.equal(P.avatarBase(AVATAR, "https://teams.cloud.microsoft", SELF_UUID), base);
  assert.equal(P.avatarBase(AVATAR, "https://teams.cloud.microsoft", ""), base, "soi pas encore connu");
  assert.equal(P.avatarBase(AVATAR, "https://teams.microsoft.com", SELF_UUID), "", "une autre origine : d'autres cookies");
  assert.equal(P.avatarBase(AVATAR, "https://teams.cloud.microsoft", "00000000-0000-4000-8000-000000000000"), "",
    "l'avatar d'un autre compte");
  assert.equal(P.avatarBase("https://evil.example/api/mt/part/emea/beta/users/" + SELF_UUID + "/x",
    "https://evil.example", ""), "");
  assert.equal(P.avatarBase(`https://teams.cloud.microsoft/api/mt/part/emea/beta/users/${SELF_UUID}/threads/19:a@thread.v2/properties/pictureV2`,
    "https://teams.cloud.microsoft", SELF_UUID), `https://teams.cloud.microsoft/api/mt/part/emea/beta/users/${SELF_UUID}`,
    "l'image d'un groupe donne la même base");
});

test("l'adresse d'une photo : construite sur la base, 64 px, pour une personne de Teams seulement", () => {
  const base = `https://teams.cloud.microsoft/api/mt/part/emea-02/beta/users/${SELF_UUID}`;
  const person = "8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab";
  assert.equal(P.photoUrl(base, person, "Gilles Rousseau & co", "0x8D/+="),
    `${base}/profilepicturev2/${person}?displayname=Gilles%20Rousseau%20%26%20co&size=HR64x64&avatarETag=0x8D%2F%2B%3D`);
  assert.equal(P.photoUrl(base, "../../autre", "x", "e"), "");
  assert.equal(P.photoUrl(base, person, "x", "<e>"), "");
  assert.equal(P.photoUrl("https://ailleurs.example/api", person, "x", "e"), "", "jamais une autre adresse");
  assert.equal(P.photoUrl("", person, "x", "e"), "");
});
