"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const X = require("../lib/extract.js");

const DM = "19:aaaa_bbbb@unq.gbl.spaces";
const GROUP = "19:9f3c@thread.v2";

function chatsvcMessage(over) {
  return Object.assign({
    id: "1759737600000",
    clientmessageid: "8812",
    version: "1759737600000",
    conversationid: DM,
    conversationLink: "https://emea.ng.msg.teams.microsoft.com/v1/users/ME/conversations/" + DM,
    type: "Message",
    messagetype: "RichText/Html",
    contenttype: "text",
    content: "<p>Salut <span itemscope itemtype=\"http://schema.skype.com/Mention\" itemid=\"0\">Adrien</span>, "
      + "tu viens&nbsp;?</p>",
    from: "https://emea.ng.msg.teams.microsoft.com/v1/users/ME/contacts/8:orgid:alice-uuid",
    imdisplayname: "Alice Martin",
    composetime: "2026-10-06T08:00:00.000Z",
    originalarrivaltime: "2026-10-06T08:00:00.120Z",
    properties: {
      mentions: JSON.stringify([{ "@type": "http://schema.skype.com/Mention", itemid: 0,
        mri: "8:orgid:self-uuid", mentionType: "person", displayName: "Adrien" }]),
    },
  }, over || {});
}

test("une réponse du service de chat : le message lisible, sans la frappe ni l'activité du fil", () => {
  const body = JSON.stringify({ messages: [
    chatsvcMessage(),
    { id: "2", conversationid: DM, messagetype: "Control/Typing", content: "",
      originalarrivaltime: "2026-10-06T08:00:01Z", imdisplayname: "Alice Martin" },
    { id: "3", conversationid: DM, messagetype: "ThreadActivity/AddMember",
      content: "<addmember><eventtime>1759737602000</eventtime><initiator>8:orgid:alice-uuid</initiator>"
        + "<target>8:orgid:bob-uuid</target></addmember>",
      originalarrivaltime: "2026-10-06T08:00:02Z" },
    { id: "4", conversationid: DM, messagetype: "Event/Call", imdisplayname: "Alice Martin",
      content: "<partlist type=\"started\" alt=\"\"><part identity=\"alice\"><name>Alice Martin</name></part></partlist>",
      originalarrivaltime: "2026-10-06T08:00:03Z" },
  ] });
  const { messages } = X.extract(body, { parseStrings: true });
  assert.equal(messages.length, 1);
  const m = messages[0];
  assert.equal(m.id, "1759737600000");
  assert.equal(m.conv, DM);
  assert.equal(m.author, "Alice Martin");
  assert.equal(m.authorId, "8:orgid:alice-uuid");
  assert.equal(m.text, "Salut Adrien, tu viens ?");
  assert.equal(m.time, Date.parse("2026-10-06T08:00:00.120Z"));
  assert.deepEqual(m.mentions, ["8:orgid:self-uuid"]);
});

test("une trame du WebSocket : le message est dans un corps encodé dans la trame", () => {
  const event = { time: "2026-10-06T08:00:00Z", type: "EventMessage", resourceType: "NewMessage",
    resource: chatsvcMessage({ id: "77", content: "on se voit à 14h" }) };
  const frame = "3:::" + JSON.stringify({ id: 12, method: "POST", url: "/v4/f/abc/messaging", headers: {},
    body: JSON.stringify(event) });
  const { messages } = X.extract(frame, { parseStrings: true });
  assert.equal(messages.length, 1);
  assert.equal(messages[0].id, "77");
  assert.equal(messages[0].text, "on se voit à 14h");
});

test("sans ouvrir les chaînes, un JSON encodé n'est pas lu (la base locale n'en a pas besoin)", () => {
  const frame = JSON.stringify({ body: JSON.stringify({ resource: chatsvcMessage() }) });
  assert.equal(X.extract(JSON.parse(frame), { parseStrings: false }).messages.length, 0);
});

test("un enregistrement de la base locale : la conversation vient de l'enregistrement qui contient le message", () => {
  const record = {
    conversationId: GROUP,
    messageMap: {
      m1: { id: "m1", content: "Bonjour à tous", messageType: "Text", imDisplayName: "Bob",
        originalArrivalTime: 1759737600000, creator: "8:orgid:bob-uuid" },
      m2: { id: "m2", content: "<div>Ordre du jour<br>1. budget</div>", messageType: "RichText/Html",
        imDisplayName: "Chloé", clientArrivalTime: 1759737660000, creator: "8:orgid:chloe-uuid" },
    },
  };
  const { messages } = X.extract(record, { parseStrings: false });
  assert.deepEqual(messages.map((m) => [m.id, m.conv, m.author, m.text]), [
    ["m1", GROUP, "Bob", "Bonjour à tous"],
    ["m2", GROUP, "Chloé", "Ordre du jour\n1. budget"],
  ]);
  assert.equal(messages[0].authorId, "8:orgid:bob-uuid");
});

test("un message supprimé devient une suppression : même identifiant, même conversation, même date, sans texte", () => {
  const deleted = chatsvcMessage({ content: "", properties: { deletetime: "1759737700000" } });
  const { messages } = X.extract([deleted]);
  assert.equal(messages.length, 1);
  const m = messages[0];
  assert.equal(m.deleted, true);
  assert.equal(m.text, "");
  assert.equal(m.id, "1759737600000");
  assert.equal(m.conv, DM);
  assert.equal(m.time, Date.parse("2026-10-06T08:00:00.120Z"));
  assert.deepEqual(m.mentions, []);
  // un message ordinaire n'en porte pas la marque
  assert.equal("deleted" in X.extract(chatsvcMessage()).messages[0], false);
  // « 0 » ou `false` ne sont pas une suppression
  assert.equal(X.extract(chatsvcMessage({ properties: { deletetime: "0" } })).messages[0].deleted, undefined);
  assert.equal(X.extract(chatsvcMessage({ isDeleted: false })).messages[0].deleted, undefined);
});

test("une suppression sans identifiant, ou un message sans date, ne donnent rien", () => {
  const anonymous = chatsvcMessage({ id: undefined, clientmessageid: undefined, properties: { deletetime: "1759737700000" } });
  const undated = chatsvcMessage({ composetime: undefined, originalarrivaltime: undefined });
  assert.equal(X.extract([anonymous, undated]).messages.length, 0);
});

test("un message modifié garde son identifiant ; sa version avance", () => {
  const first = X.extract(chatsvcMessage({ content: "on part à 9h" })).messages[0];
  const edited = X.extract(chatsvcMessage({ content: "on part à 10h", version: "1759737900000",
    properties: { edittime: "1759737900000" } })).messages[0];
  assert.equal(edited.id, first.id);
  assert.equal(first.version, 1759737600000);
  assert.equal(edited.version, 1759737900000);
  assert.equal(edited.text, "on part à 10h");
});

test("un texte trop long est coupé sans casser un emoji", () => {
  const long = "a".repeat(3998) + "👍👍👍";
  const m = X.extract(chatsvcMessage({ content: long })).messages[0];
  assert.ok(m.text.length <= 4000);
  assert.ok(m.text.endsWith("…"));
  assert.ok(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(m.text), "aucune moitié de paire seule");
});

test("un objet quelconque avec un champ « content » n'est pas pris pour un message", () => {
  const card = { content: "Bienvenue", createdTime: "2026-10-06T08:00:00Z" };
  assert.equal(X.extract(card).messages.length, 0);
});

test("une pièce jointe se dit par son nom", () => {
  const m = chatsvcMessage({ messagetype: "RichText/Media_GenericFile",
    content: "<URIObject type=\"File.1\"><Title>Title: rapport.pdf</Title>"
      + "<OriginalName v=\"rapport final.pdf\"></OriginalName></URIObject>" });
  assert.equal(X.extract(m).messages[0].text, "[pièce jointe : rapport final.pdf]");
});

test("un message sans identifiant reçoit un condensé stable", () => {
  const raw = chatsvcMessage({ id: undefined, clientmessageid: undefined });
  const a = X.extract(raw).messages[0];
  const b = X.extract(JSON.parse(JSON.stringify(raw))).messages[0];
  assert.match(a.id, /^h/);
  assert.equal(a.id, b.id);
});

test("une liste de conversations apprend leurs noms", () => {
  const body = { conversations: [
    { id: GROUP, threadProperties: { topic: "Projet Atlas", threadType: "chat" } },
    { id: "19:chan@thread.tacv2", threadProperties: { topic: "Général", threadType: "topic" } },
    { id: "not-a-thread", title: "rien" },
  ] };
  const { conversations } = X.extract(body);
  assert.deepEqual(conversations.map((c) => [c.id, c.title, c.threadType]), [
    [GROUP, "Projet Atlas", "chat"],
    ["19:chan@thread.tacv2", "Général", "topic"],
  ]);
});

test("la nature d'une conversation", () => {
  assert.equal(X.conversationKind(DM, ""), "dm");
  assert.equal(X.conversationKind(GROUP, ""), "group");
  assert.equal(X.conversationKind(GROUP, "meeting"), "meeting");
  assert.equal(X.conversationKind("19:meeting_NmU@thread.v2", ""), "meeting");
  assert.equal(X.conversationKind("19:chan@thread.tacv2", ""), "channel");
  assert.equal(X.conversationKind("48:notifications", ""), "system");
  assert.equal(X.conversationKind("weird", ""), "other");
});

test("le texte d'un HTML de Teams : réponse citée, emoji, entités, retours à la ligne", () => {
  const html = "<blockquote itemscope itemtype=\"http://schema.skype.com/Reply\"><strong itemprop=\"mri\">Bob</strong>"
    + "<span itemprop=\"time\" itemid=\"1759737600000\">1759737600000</span><p itemprop=\"preview\">on part à 9h ?</p>"
    + "</blockquote><p>Oui <img alt=\"👍\" src=\"x\"> &amp; toi&#x202F;?</p><p>A&#233;roport<br/>porte&nbsp;B</p>";
  assert.equal(X.htmlToText(html), "« Bob on part à 9h ? » Oui 👍 & toi ?\nAéroport\nporte B");
  assert.equal(X.htmlToText("  texte  brut "), "texte  brut");
});

test("une chaîne qui n'est pas du JSON reste une chaîne", () => {
  assert.equal(X.parseEmbedded("bonjour {pas du json}"), undefined);
  assert.equal(X.parseEmbedded("1::"), undefined);
  assert.deepEqual(X.parseEmbedded("5:2::{\"a\":1}"), { a: 1 });
});

test("l'identifiant d'une conversation dans une adresse", () => {
  assert.equal(X.conversationFromUrl("https://x/v1/users/ME/conversations/19%3Aabc%40thread.v2/messages?view=x"),
    "19:abc@thread.v2");
  assert.equal(X.conversationFromUrl("https://x/v1/users/ME/properties"), "");
});

test("une réponse énorme est parcourue en temps borné", () => {
  const many = [];
  for (let i = 0; i < 60000; i++) many.push({ n: i });
  const { truncated } = X.extract(many);
  assert.equal(truncated, true);
});
