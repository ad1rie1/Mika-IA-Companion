"use strict";
// L'envoi par le worker de Teams (ADR 0301), ce qui se calcule sans la page (`lib/page.js`) : le modèle tiré d'un
// envoi de la page (rien de ce message n'y reste), la commande rejouée pour une autre conversation, le début d'une
// commande lu sans la décoder, le numéro de requête, la réponse du worker.
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../lib/page.js");
const F = require("./worker-fixture.js");

const ITEM = "t0123456789ab";
const NOW = 1_763_900_000_000;

function build(template, over = {}) {
  return P.workerSendCommand(template, { conversation: F.GROUP, text: "Bonjour", clientMessageId: P.clientMessageIdFor(ITEM),
    correlationId: "11111111-2222-4333-8444-555555555555", now: NOW, requestNumber: 1412, rendererId: F.RENDERER,
    windowId: F.WINDOW, ...over });
}

function templateOf(command) {
  const got = P.workerSendTemplate(command);
  assert.ok(got.template, "modèle refusé : " + got.reason);
  return got;
}

// ── Le modèle ───────────────────────────────────────────────────────────────

test("le modèle d'un envoi ne garde ni texte, ni conversation, ni identifiants, ni mentions", () => {
  const { template, bilateral } = templateOf(F.autoSend({ over: (c) => {
    c.payload.variables.message.computed.mentions = ["8:orgid:7c2e41d0-5b8a-4f0e-9d21-3a6e0c1f91ab"];
    c.payload.variables.message.computed.links = ["https://exemple.fr/dossier"];
  } }));
  assert.equal(bilateral, true);
  const json = JSON.stringify(template);
  for (const trace of [F.ALBERT, F.TEXT, F.CLIENT_ID, F.CORRELATION, F.RENDERER, F.WINDOW, "m-412", "1763812345678",
    "exemple.fr", "7c2e41d0"]) {
    assert.equal(json.includes(trace), false, "« " + trace + " » est resté dans le modèle");
  }
  const c = template.command;
  assert.equal("requestId" in c || "rendererId" in c || "windowId" in c, false, "ils viennent de la page vivante");
  const v = c.payload.variables;
  assert.equal(v.convId, "");
  assert.equal(v.originalConvId, "");
  assert.equal(v.correlationId, "");
  assert.equal(v.message.content, "");
  assert.equal(v.message.clientMessageId, "");
  assert.equal(v.message.originalSendPipelineTime, "");
  assert.deepEqual(v.message.computed.mentions, []);
  assert.deepEqual(v.message.computed.links, [], "ce que Teams a calculé en liste du message part avec lui");
  assert.equal(v.offlineActionOptions.actionId, "");
  assert.equal(v.offlineActionOptions.queueId, "sendMessage_" + P.SEND_SLOT.conversation, "la file garde son préfixe");
  // ce que Teams tient de lui-même reste tel quel
  assert.equal(v.action, "Create");
  assert.equal(v.message.messageType, "RichText/Html");
  assert.equal(v.message.sendPipelineThreadType, "Chats");
  assert.equal(v.message.senderDisplayName, "Adrien Martin");
  assert.deepEqual(c.options, {});
  assert.equal(c.payload.graphqlQuery, F.autoSend().payload.graphqlQuery);
  assert.deepEqual([template.open, template.close, template.breaks],
    ["<p><semantic-object>", "</semantic-object></p>", "br"], "la forme d'un message de Teams");
});

test("un envoi de la page vers un groupe donne un modèle de groupe", () => {
  const { template, bilateral } = templateOf(F.autoSend({ conv: F.GROUP }));
  assert.equal(bilateral, false);
  assert.equal(JSON.stringify(template).includes(F.GROUP), false);
});

test("un modèle refusé : un autre geste, un canal, une réunion, une citation, une pièce jointe, une autre origine", () => {
  const refused = (over, conv) => P.workerSendTemplate(F.autoSend({ conv, over }));
  const cases = [
    refused((c) => { c.payload.variables.action = "Edit"; }),
    refused(undefined, F.CHANNEL),
    refused(undefined, F.MEETING),
    refused((c) => { c.payload.variables.message.quotedMessage = { id: "1763800000000" }; }),
    refused((c) => { c.payload.variables.message.files = "[{\"id\":\"x\"}]"; }),
    refused((c) => { c.payload.variables.offlineActionOptions.pendingUploadIds = ["u1"]; }),
    refused((c) => { c.payload.variables.message.amsReferences = ["0-weu-d1-abc"]; }),
    refused((c) => { c.payload.variables.originalConvId = F.GROUP; }),
    refused((c) => { c.payload.variables.message.properties = ["x"]; }),
    refused((c) => { c.payload.variables.offlineActionOptions.queueId = "q_" + F.ALBERT + "_suite"; }),
    refused((c) => { c.payload.variables.message.note = "aussi dans " + F.GROUP; }),
    P.workerSendTemplate({ ...F.query(7) }),
    P.workerSendTemplate("pas un objet"),
  ];
  for (const got of cases) {
    assert.equal(got.template, null);
    assert.ok(got.reason, "une raison pour le diagnostic");
  }
  // une clé qui ressemble sans l'être : « senderProfile » n'est pas un fichier
  assert.ok(P.workerSendTemplate(F.autoSend({ over: (c) => {
    c.payload.variables.message.senderProfile = { name: "Adrien" };
  } })).template);
});

test("la conversation ailleurs dans la commande devient une marque, refaite à chaque envoi", () => {
  const { template } = templateOf(F.autoSend({ over: (c) => {
    c.payload.variables.message.threadLink = "https://teams.microsoft.com/l/chat/" + F.ALBERT + "/0";
  } }));
  assert.equal(template.command.payload.variables.message.threadLink,
    "https://teams.microsoft.com/l/chat/" + P.SEND_SLOT.conversation + "/0");
  const sent = JSON.parse(build(template));
  assert.equal(sent.payload.variables.message.threadLink, "https://teams.microsoft.com/l/chat/" + F.GROUP + "/0");
});

// ── La commande rejouée ─────────────────────────────────────────────────────

test("la commande rejouée : un texte JSON, la conversation, les identifiants, l'heure et le texte refaits", () => {
  const { template } = templateOf(F.autoSend());
  const out = build(template, { text: "Oui <b>demain</b> & \"9 h\"" });
  assert.equal(typeof out, "string", "un objet serait ignoré par le worker");
  const c = JSON.parse(out);
  const client = P.clientMessageIdFor(ITEM);
  assert.deepEqual(Object.keys(c).slice(0, 3), ["requestId", "rendererId", "windowId"]);
  assert.equal(c.requestId, "m-1412");
  assert.equal(c.rendererId, F.RENDERER);
  assert.equal(c.windowId, F.WINDOW);
  const v = c.payload.variables;
  assert.equal(v.convId, F.GROUP);
  assert.equal(v.originalConvId, F.GROUP);
  assert.equal(v.correlationId, "11111111-2222-4333-8444-555555555555");
  assert.equal(v.isBilateralChat, false);
  assert.equal(v.message.clientMessageId, client);
  assert.match(client, /^[1-9]\d{18}$/);
  assert.equal(v.message.content,
    "<p><semantic-object>Oui &lt;b&gt;demain&lt;/b&gt; &amp; &quot;9 h&quot;</semantic-object></p>");
  assert.equal(v.message.originalSendPipelineTime, String(NOW));
  assert.equal(v.message.computed.plainText, "Oui <b>demain</b> & \"9 h\"", "ce que Teams calcule du texte, refait");
  assert.deepEqual(v.message.computed.mentions, []);
  assert.equal(v.offlineActionOptions.actionId, "send_" + client);
  assert.equal(v.offlineActionOptions.queueId, "sendMessage_" + F.GROUP);
  assert.deepEqual(v.offlineActionOptions.pendingUploadIds, []);
  assert.equal(v.message.messageType, "RichText/Html");
  assert.equal(v.message.importance, "Standard");
  assert.equal(c.operationName, "autoSendMessage");
  assert.equal(c.type, "graphql");
  assert.deepEqual(c.options, {});
});

test("rejoué au même endroit avec le même message, le modèle redonne la commande de la page", () => {
  const page = F.autoSend();
  const { template } = templateOf(page);
  const again = JSON.parse(P.workerSendCommand(template, { conversation: F.ALBERT, text: F.TEXT,
    clientMessageId: F.CLIENT_ID, correlationId: F.CORRELATION, now: 1763812345678, requestNumber: 412,
    rendererId: F.RENDERER, windowId: F.WINDOW }));
  assert.deepEqual(again, page);
});

test("un tête-à-tête ou un groupe : `isBilateralChat` et la file d'attente suivent la conversation", () => {
  const { template } = templateOf(F.autoSend({ conv: F.GROUP }));
  const one = JSON.parse(build(template, { conversation: F.ALBERT })).payload.variables;
  assert.equal(one.isBilateralChat, true);
  assert.equal(one.convId, F.ALBERT);
  assert.equal(one.offlineActionOptions.queueId, "sendMessage_" + F.ALBERT);
  const group = JSON.parse(build(template, { conversation: F.GROUP })).payload.variables;
  assert.equal(group.isBilateralChat, false);
  assert.equal(group.offlineActionOptions.queueId, "sendMessage_" + F.GROUP);
  assert.equal(P.isBilateralChat(F.ALBERT), true);
  assert.equal(P.isBilateralChat(F.GROUP), false);
});

test("pas de commande pour un canal, une réunion, un texte vide, ou sans ce que dit la page vivante", () => {
  const { template } = templateOf(F.autoSend());
  assert.equal(P.workerSendable(F.ALBERT), true);
  assert.equal(P.workerSendable(F.GROUP), true);
  assert.equal(P.workerSendable(F.CHANNEL), false);
  assert.equal(P.workerSendable("19:abc@thread.skype"), false);
  assert.equal(P.workerSendable(F.MEETING), false);
  assert.equal(P.workerSendable("48:notes"), false);
  assert.equal(build(template, { conversation: F.CHANNEL }), "");
  assert.equal(build(template, { conversation: F.MEETING }), "");
  assert.equal(build(template, { text: "  \n " }), "");
  assert.equal(build(template, { rendererId: undefined }), "");
  assert.equal(build(template, { windowId: { x: 1 } }), "");
  assert.equal(build(template, { requestNumber: 1.5 }), "");
  assert.equal(build(template, { correlationId: "" }), "");
  assert.equal(build(null), "");
  assert.notEqual(build(template, { windowId: 3 }), "", "un nombre convient aussi");
});

test("le texte : échappé, ligne à ligne, dans la forme du modèle", () => {
  const teams = { open: "<p><semantic-object>", close: "</semantic-object></p>", breaks: "br" };
  assert.equal(P.workerContent("a < b\nligne 2\r\n\nfin", teams),
    "<p><semantic-object>a &lt; b<br>ligne 2<br><br>fin</semantic-object></p>");
  assert.equal(P.workerContent("un\n\ndeux", { ...teams, breaks: "p" }),
    "<p><semantic-object>un</semantic-object></p><p><semantic-object>&nbsp;</semantic-object></p>"
    + "<p><semantic-object>deux</semantic-object></p>");
  assert.equal(P.workerContent("<img src=x onerror=alert(1)>", {}), "<p>&lt;img src=x onerror=alert(1)&gt;</p>");
  // la forme se lit sur l'envoi de la page
  assert.deepEqual(P.learnShape("<p>un</p><p>deux</p>"), { open: "<p>", close: "</p>", breaks: "p" });
  assert.deepEqual(P.learnShape("<p dir=\"ltr\">un<br>deux</p>"), { open: "<p dir=\"ltr\">", close: "</p>", breaks: "br" });
  const plain = { open: "<p>", close: "</p>", breaks: "br" };
  assert.deepEqual(P.learnShape("<p>Salut <span itemtype=\"http://schema.skype.com/Mention\">Albert</span></p>"), plain,
    "une mention : la forme par défaut");
  assert.deepEqual(P.learnShape("<p><img src=\"x\">texte</p>"), plain);
  assert.deepEqual(P.learnShape("<p data-id=\"1763800000000\">x</p>"), plain, "un attribut qui porte un identifiant");
  assert.deepEqual(P.learnShape("<p onclick=\"x()\">x</p>"), plain);
  assert.deepEqual(P.learnShape("texte nu"), plain);
});

test("le modèle choisi : celui de la sorte de la conversation, sinon l'autre", () => {
  const one = { command: {}, at: 1 };
  const group = { command: {}, at: 2 };
  assert.equal(P.pickSendTemplate({ bilateral: one, group }, F.ALBERT), one);
  assert.equal(P.pickSendTemplate({ bilateral: one, group }, F.GROUP), group);
  assert.equal(P.pickSendTemplate({ bilateral: one, group: null }, F.GROUP), one);
  assert.equal(P.pickSendTemplate({ bilateral: null, group }, F.ALBERT), group);
  assert.equal(P.pickSendTemplate({}, F.ALBERT), null);
  assert.equal(P.pickSendTemplate(null, F.ALBERT), null);
});

// ── La page vivante et le worker ────────────────────────────────────────────

test("le début d'une commande se lit sans la décoder : sa sorte, son numéro, rendererId, windowId, son opération", () => {
  assert.deepEqual(P.workerCommandHead(JSON.stringify(F.autoSend())),
    { prefix: "m", number: 412, rendererId: F.RENDERER, windowId: F.WINDOW, operation: "autoSendMessage" });
  assert.deepEqual(P.workerCommandHead(JSON.stringify(F.query(77, { renderer: 3, window: 9 }))),
    { prefix: "q", number: 77, rendererId: 3, windowId: 9, operation: "chatList" });
  assert.equal(P.workerCommandHead("{\"type\":\"ping\"}"), null);
  assert.equal(P.workerCommandHead(F.autoSend()), null, "un objet n'est pas une commande de la page");
});

test("le numéro de notre requête : loin au-dessus du compteur de la page, et jamais deux fois le même", () => {
  assert.equal(P.nextRequestNumber(412, 0), 1412);
  assert.equal(P.nextRequestNumber(412, 1412), 1413);
  assert.equal(P.nextRequestNumber(900, 1413), 1900);
  assert.ok(P.nextRequestNumber(5, 0) > 5);
  assert.equal(P.workerRequestId(1412), "m-1412");
});

test("la réponse du worker : envoyé, refusé (rien n'est parti), douteux, ou pas encore une issue", () => {
  assert.deepEqual(P.workerReplyOutcome(F.reply("m-1412")), { result: "sent", reason: "", messageId: "1763900000123" });
  assert.equal(P.workerReplyOutcome(F.reply("m-1412", { data: { autoSendMessage: null } })).result, "sent");
  const refused = P.workerReplyOutcome(F.reply("m-1412", { data: { autoSendMessage: null },
    errors: [{ message: "  Forbidden:\n not a member " }] }));
  assert.deepEqual(refused, { result: "refused", reason: "Forbidden: not a member", messageId: "" });
  assert.equal(P.workerReplyOutcome(F.reply("m-1412", { data: {}, errors: ["x"] })).result, "refused");
  assert.equal(P.workerReplyOutcome(F.reply("m-1412", { status: "error", data: null })).result, "refused");
  assert.equal(P.workerReplyOutcome({ requestId: "m-1", status: "failed", error: { message: "offline" } }).reason,
    "offline");
  assert.equal(P.workerReplyOutcome(F.reply("m-1412", { errors: [{ message: "partiel" }] })).result, "uncertain",
    "un résultat et une erreur : peut-être parti");
  assert.equal(P.workerReplyOutcome(F.reply("m-1412", { status: "pending" })).result, "", "pas une issue : on attend");
  assert.equal(P.workerReplyOutcome("texte").result, "");
});
