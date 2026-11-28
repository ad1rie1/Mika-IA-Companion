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

test("un tableau de Teams : une ligne par rangée, ses cellules séparées par « | », pas une colonne de lignes", () => {
  const html = "<p>Bonjour <span itemtype=\"http://schema.skype.com/Mention\">Tout le monde</span></p>"
    + "<p>Nous avons une liste de 10 magasins :</p>"
    + "<table itemprop=\"copy-paste-table\"><tbody>"
    + "<tr><td><p>AP Antibes Wilson</p></td><td><p>103</p></td></tr>"
    + "<tr><td><p>AP Castellane</p></td><td><p>106</p></td></tr>"
    + "<tr><th>Nom &amp; ville</th><th>N°<br>badge</th></tr>"
    + "<tr><td><p></p></td><td></td></tr>"
    + "</tbody></table><p>Merci</p>";
  // le tableau se tient à part, une ligne vide avant et après
  assert.equal(X.htmlToText(html), "Bonjour Tout le monde\nNous avons une liste de 10 magasins :\n\n"
    + "AP Antibes Wilson | 103\nAP Castellane | 106\nNom & ville | N° badge\n\nMerci");
});

test("une image collée devient « [image] » ; un emoji garde son texte ; une image seule fait encore un message", () => {
  const pasted = "<p><img alt=\"image\" src=\"https://eu-api.asm.skype.com/v1/objects/0-neu-d4-abc/views/imgo\" "
    + "itemscope=\"\" itemtype=\"http://schema.skype.com/AMSImage\"></p>";
  assert.equal(X.htmlToText(pasted), "[image]");
  assert.equal(X.htmlToText("<p>Regarde <img src=\"https://x.example/views/imgo\"> ça</p>"), "Regarde [image] ça");
  assert.equal(X.htmlToText("<p>Top <img itemtype=\"http://schema.skype.com/Emoji\" alt=\"😀\" src=\"e.png\"></p>"),
    "Top 😀");
  assert.equal(X.htmlToText("<p>sans texte <img src=\"deco.png\"></p>"), "sans texte");
  const m = X.normalizeMessage({ id: "1759737600000", conversationid: "19:a@thread.v2", messagetype: "RichText/Html",
    content: pasted, originalarrivaltime: "2026-10-06T08:00:00Z", imdisplayname: "Alice" });
  assert.equal(m && m.text, "[image]");
});

test("les images à télécharger : du service d'images de Teams seulement, à leur rang parmi les marques", () => {
  const ams = (id, view = "imgo") => `<img alt="image" itemtype="http://schema.skype.com/AMSImage" src="https://eu-api.asm.skype.com/v1/objects/${id}/views/${view}">`;
  const html = `<p>${`<img itemtype="http://schema.skype.com/Giphy" alt="image" src="https://media.giphy.com/a.gif">`}`
    + `${ams("0-neu-d4-aaa", "imgpsh_fullsize_anim")} <img src="https://evil.example/v1/objects/x/views/imgo"> `
    + `${ams("0-neu-d4-bbb")}<img itemtype="http://schema.skype.com/Emoji" alt="😀" src="e.png"></p>`;
  assert.deepEqual(X.imagesOf(html), [
    { id: "0-neu-d4-aaa", url: "https://eu-api.asm.skype.com/v1/objects/0-neu-d4-aaa/views/imgo", position: 1 },
    { id: "0-neu-d4-bbb", url: "https://eu-api.asm.skype.com/v1/objects/0-neu-d4-bbb/views/imgo", position: 3 },
  ], "le GIF et l'adresse étrangère ont leur marque sans être téléchargés ; l'emoji n'en a pas");
  assert.equal(X.htmlToText(html), "[image] [image] [image] [image] 😀");
  const many = Array.from({ length: 12 }, (_, i) => ams("0-img-" + i)).join("");
  assert.equal(X.imagesOf(many).length, 8, "huit par message au plus");
  assert.deepEqual(X.imagesOf('<img src="https://eu-api.asm.skype.com.evil.example/v1/objects/x/views/imgo">'), []);
  const m = X.normalizeMessage({ id: "1759737600000", conversationid: "19:a@thread.v2", messagetype: "RichText/Html",
    content: "<p>regarde " + ams("0-neu-d4-ccc") + "</p>", originalarrivaltime: "2026-10-06T08:00:00Z",
    imdisplayname: "Alice" });
  assert.deepEqual(m.images.map((i) => i.id), ["0-neu-d4-ccc"]);
  assert.equal(m.text, "regarde [image]");
});

// ── ADR 0305 : la citation d'une réponse, à part de son texte ───────────────

// le contenu d'une réponse citée, tel que Teams l'a envoyé le 2026-11-22 (essai 8 chez Albert)
const QUOTED = '<blockquote itemtype="http://schema.skype.com/Reply" itemid="1795384015721"><strong itemprop="mri" itemid="28:ed349f0c-53ac-4a32-a4c8-2bd6e5244865">Albert</strong><span itemprop="time" itemid="1795384015721"></span><p itemprop="preview">Bonjour Adrien, votre prochaine le&ccedil;on n&#39;est pas encore disponible.</p></blockquote><p><semantic-object>SONDE-MIKA essai 8 (citation, à ignorer)</semantic-object></p>';

test("une réponse citée garde sa citation à part : son texte ne la reprend pas (ADR 0305)", () => {
  const m = X.normalizeMessage(chatsvcMessage({ content: QUOTED }));
  assert.equal(m.text, "SONDE-MIKA essai 8 (citation, à ignorer)");
  assert.deepEqual(m.quote, { message: "1795384015721", author_id: "28:ed349f0c-53ac-4a32-a4c8-2bd6e5244865",
    author: "Albert", at: 1795384015721,
    preview: "Bonjour Adrien, votre prochaine leçon n'est pas encore disponible." });
});

test("une citation illisible, ou un simple bloc cité, reste dans le texte comme avant", () => {
  const odd = QUOTED.replace('itemid="1795384015721">', 'itemid="abc">');
  const m = X.normalizeMessage(chatsvcMessage({ content: odd }));
  assert.equal(m.quote, undefined);
  assert.match(m.text, /^« Albert Bonjour Adrien/);
  const plain = X.normalizeMessage(chatsvcMessage({ content: "<blockquote>dit-il</blockquote><p>oui</p>" }));
  assert.equal(plain.quote, undefined);
  assert.match(plain.text, /« dit-il »/);
  // une réponse qui ne serait qu'une citation la garde en texte
  const only = QUOTED.replace(/<p><semantic-object>.*$/, "");
  assert.match(X.normalizeMessage(chatsvcMessage({ content: only })).text, /« Albert/);
});
