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

test("un identifiant client : 19 chiffres, le premier jamais nul", () => {
  assert.match(P.clientMessageId(() => 0), /^1\d{18}$/);
  assert.match(P.clientMessageId(() => 0.9999999), /^9{19}$/);
  assert.match(P.clientMessageId(Math.random), /^[1-9]\d{18}$/);
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
