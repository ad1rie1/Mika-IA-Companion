"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const O = require("../lib/outbox.js");

const NOW = Date.parse("2026-10-06T10:00:00Z");
const DM = "19:aaaa_bbbb@unq.gbl.spaces";

function item(over) {
  return Object.assign({ id: "t12", conversation: DM, title: "Alice", kind: "dm", mode: "draft", status: "queued",
    text: "Oui, je regarde ça cet après-midi.\n— Mika", created_at: NOW - 60000, expires_at: NOW + 3600000 },
  over || {});
}

function boxWith(items, now) {
  const box = O.freshBox();
  O.reconcile(box, items.map(O.normalizeItem), now || NOW);
  return box;
}

function plan(box, id, now, excluded) {
  return O.plan(box, id, { now: now || NOW, excluded: Boolean(excluded) }).do;
}

// ── La liste du serveur ─────────────────────────────────────────────────────

test("un élément du serveur est vérifié avant d'être gardé", () => {
  assert.deepEqual(O.normalizeItem(item()), item());
  assert.equal(O.normalizeItem(item({ text: "  " })), null);
  assert.equal(O.normalizeItem(item({ id: "" })), null);
  assert.equal(O.normalizeItem(item({ conversation: undefined })), null);
  assert.equal(O.normalizeItem("t12"), null);
  assert.equal(O.normalizeItem(item({ mode: "boom" })).mode, "draft");
  assert.equal(O.normalizeItem(item({ status: "boom" })).status, "queued");
  assert.equal(O.normalizeItem(item({ text: "x".repeat(30000) })).text.length, 20000);
});

test("la liste du serveur fait foi : ce qui n'y est plus est oublié, ce qu'on savait ici reste", () => {
  const box = boxWith([item(), item({ id: "t13" })]);
  box.items.t12.notifiedAt = NOW;
  const gone = O.reconcile(box, [O.normalizeItem(item({ title: "Alice Martin" }))], NOW + 1000);
  assert.deepEqual(gone, ["t13"]);
  assert.deepEqual(Object.keys(box.items), ["t12"]);
  assert.equal(box.items.t12.title, "Alice Martin");
  assert.equal(box.items.t12.notifiedAt, NOW);
});

// ── Un brouillon ────────────────────────────────────────────────────────────

test("un brouillon : annoncé, placé une seule fois, l'issue dite au serveur", () => {
  const box = boxWith([item()]);
  assert.equal(plan(box, "t12"), "notify");
  box.items.t12.notifiedAt = NOW;
  assert.equal(plan(box, "t12"), "place");
  assert.deepEqual(O.pendingDrafts(box, NOW), [{ id: "t12", conversation: DM, text: item().text }]);

  assert.equal(O.claim(box, "t12", NOW, false), true);
  assert.equal(O.claim(box, "t12", NOW, false), false, "un second onglet n'a pas le droit");
  assert.deepEqual(O.pendingDrafts(box, NOW), []);
  assert.equal(O.placed(box, "t12", NOW + 500), true);
  assert.deepEqual(O.pendingAcks(box), [{ id: "t12", body: { result: "placed" } }]);
  assert.equal(plan(box, "t12"), "ack");

  assert.equal(O.ackResponse(box, "t12", "placed", 200, NOW + 1000), "done");
  assert.deepEqual(O.pendingAcks(box), []);
  assert.equal(box.stats.placed, 1);
  assert.equal(box.log[0].result, "placed");
  assert.equal(box.log[0].title, "Alice");

  // le serveur le liste encore, « placé » : on n'y touche plus
  O.reconcile(box, [O.normalizeItem(item({ status: "placed" }))], NOW + 30000);
  assert.equal(plan(box, "t12", NOW + 30000), "wait");
});

test("jamais replacé : même si la liste du serveur est en retard, même après un redémarrage", () => {
  const box = boxWith([item()]);
  O.claim(box, "t12", NOW, false);
  O.placed(box, "t12", NOW);
  O.ackResponse(box, "t12", "placed", 200, NOW);
  // le serveur dit encore « queued » (il n'a pas encore pris l'issue en compte)
  const reloaded = JSON.parse(JSON.stringify(box));
  O.reconcile(reloaded, [O.normalizeItem(item())], NOW + 30000);
  assert.equal(plan(reloaded, "t12", NOW + 30000), "wait");
  assert.equal(O.claim(reloaded, "t12", NOW + 30000, false), false);
  assert.deepEqual(O.pendingDrafts(reloaded, NOW + 30000), []);
  // même oublié puis relisté, la marque tient
  O.reconcile(reloaded, [], NOW + 60000);
  O.reconcile(reloaded, [O.normalizeItem(item())], NOW + 90000);
  assert.equal(O.claim(reloaded, "t12", NOW + 90000, false), false);
});

test("placé sans droit accordé : rien n'est dit au serveur", () => {
  const box = boxWith([item()]);
  assert.equal(O.placed(box, "t12", NOW), false);
  assert.deepEqual(O.pendingAcks(box), []);
});

test("l'onglet n'a pas pu l'insérer : le brouillon redevient à placer", () => {
  const box = boxWith([item()]);
  box.items.t12.notifiedAt = NOW;
  O.claim(box, "t12", NOW, false);
  O.release(box, "t12");
  assert.equal(plan(box, "t12"), "place");
  assert.equal(O.claim(box, "t12", NOW, false), true);
});

test("un placement commencé puis perdu n'est ni refait, ni passé sous silence", () => {
  const box = boxWith([item()]);
  O.claim(box, "t12", NOW, false);
  assert.equal(plan(box, "t12", NOW + 60000), "wait");
  const late = O.plan(box, "t12", { now: NOW + O.STALE_MS + 1, excluded: false });
  assert.equal(late.do, "fail");
  assert.equal(late.reason, O.REASONS.placeInterrupted);
});

test("un brouillon expiré ne se place plus (le serveur le clôt) ; dans une conversation exclue, l'échec est dit", () => {
  const box = boxWith([item(), item({ id: "t13", conversation: "19:rh@thread.v2", expires_at: NOW + 7200000 })]);
  assert.deepEqual(O.plan(box, "t12", { now: NOW + 3600000, excluded: false }), { do: "wait" });
  assert.deepEqual(O.pendingDrafts(box, NOW + 3600000), [{ id: "t13", conversation: "19:rh@thread.v2", text: item().text }]);
  assert.equal(O.claim(box, "t12", NOW + 3600000, false), false);
  assert.deepEqual(O.pendingAcks(box), []);
  const excluded = O.plan(box, "t13", { now: NOW, excluded: true });
  assert.equal(excluded.reason, O.REASONS.excluded);
  O.fail(box, "t13", excluded.reason, NOW);
  assert.deepEqual(O.pendingAcks(box), [{ id: "t13", body: { result: "failed", reason: O.REASONS.excluded } }]);
  const isExcluded = (e) => e.conversation.indexOf("rh") >= 0;
  assert.deepEqual(O.pendingDrafts(box, NOW, isExcluded).map((d) => d.id), ["t12"]);
  assert.equal(O.claim(box, "t13", NOW, true), false);
  const fresh = boxWith([item({ id: "t14", conversation: "19:rh@thread.v2" })]);
  assert.deepEqual(O.pendingDrafts(fresh, NOW, isExcluded), [], "une conversation exclue n'a pas de brouillon à placer");
  assert.equal(O.claim(fresh, "t14", NOW, true), false);
});

// ── Un message à envoyer ────────────────────────────────────────────────────

test("un envoi : marqué avant de partir, jamais deux fois, l'issue dite au serveur", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  assert.equal(plan(box, "s1"), "send");
  assert.deepEqual(O.pendingDrafts(box, NOW), [], "un message à envoyer n'est pas un brouillon");
  assert.equal(O.beginSend(box, "s1", NOW), true);
  assert.equal(O.beginSend(box, "s1", NOW), false);
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  O.sendOutcome(box, "s1", { result: "sent", message_id: "1759737600000" }, NOW + 2000);
  assert.deepEqual(O.pendingAcks(box), [{ id: "s1",
    body: { result: "sent", message_id: "1759737600000", text: item().text } }]);
  assert.equal(O.ackResponse(box, "s1", "sent", 200, NOW + 3000), "done");
  assert.equal(box.stats.sent, 1);
  assert.equal(plan(box, "s1", NOW + 4000), "wait");
  assert.equal(O.beginSend(box, "s1", NOW + 4000), false);
});

test("rien n'est parti : on réessaiera, avec la raison", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "retry", reason: "conversation pas ouverte dans Teams" }, NOW + 1000);
  assert.equal(plan(box, "s1", NOW + 2000), "send");
  assert.equal(box.items.s1.lastReason, "conversation pas ouverte dans Teams");
  assert.equal(box.items.s1.attempts, 1);
  assert.deepEqual(O.pendingAcks(box), []);
});

test("un envoi jamais réussi avant l'échéance : « jamais envoyé »", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  assert.deepEqual(O.plan(box, "s1", { now: NOW + 3600000, excluded: false }),
    { do: "fail", reason: "jamais envoyé : Teams pas ouvert ou envoi impossible" });
  assert.equal(O.beginSend(box, "s1", NOW + 3600000), false);
});

test("un envoi douteux ou interrompu n'est jamais retenté", () => {
  const box = boxWith([item({ id: "s1", mode: "send" }), item({ id: "s2", mode: "send" })]);
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "uncertain" }, NOW + 1000);
  assert.equal(O.pendingAcks(box)[0].body.reason, O.REASONS.uncertain);
  assert.equal(O.beginSend(box, "s1", NOW + 2000), false);
  O.beginSend(box, "s2", NOW);
  assert.equal(plan(box, "s2", NOW + 30000), "wait");
  assert.equal(O.plan(box, "s2", { now: NOW + O.STALE_MS + 1, excluded: false }).reason, O.REASONS.sendInterrupted);
});

// ── Les réponses du serveur aux issues ──────────────────────────────────────

test("404 ou 409 : oublié ici ; 400 : inutile de redire ; le reste : redit plus tard", () => {
  const box = boxWith([item({ id: "a" }), item({ id: "b" }), item({ id: "c" }), item({ id: "d" })]);
  for (const id of ["a", "b", "c", "d"]) O.fail(box, id, "x", NOW);
  assert.equal(O.ackResponse(box, "a", "failed", 404, NOW), "forget");
  assert.equal(O.ackResponse(box, "b", "failed", 409, NOW), "forget");
  assert.equal(O.ackResponse(box, "c", "failed", 400, NOW), "refused");
  assert.equal(O.ackResponse(box, "d", "failed", 503, NOW), "retry");
  assert.deepEqual(Object.keys(box.items), ["d"]);
  assert.equal(O.pendingAcks(box).length, 1, "l'issue de « d » attend toujours");
  // l'oubli ne lève pas la marque : un élément relisté ne repart pas
  O.reconcile(box, [O.normalizeItem(item({ id: "a" }))], NOW + 1000);
  assert.equal(plan(box, "a", NOW + 1000), "wait");
});

test("le journal local ne garde que 120 caractères du texte", () => {
  const box = boxWith([item({ id: "s1", mode: "send", text: "mot ".repeat(200) })]);
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "sent" }, NOW);
  O.ackResponse(box, "s1", "sent", 200, NOW);
  assert.ok(box.log[0].text.length <= 120);
  assert.equal(O.pendingAcks(box).length, 0);
});

test("ce qui attend, pour la page de réglages, sans le texte", () => {
  const box = boxWith([item(), item({ id: "s1", mode: "send", created_at: NOW - 120000 })]);
  const list = O.waiting(box, NOW);
  assert.deepEqual(list.map((e) => e.id), ["s1", "t12"]);
  assert.equal("text" in list[0], false);
});

test("le lien d'une conversation : tête-à-tête et groupe seulement", () => {
  assert.equal(O.deepLink({ kind: "dm", conversation: DM }),
    "https://teams.microsoft.com/l/chat/19%3Aaaaa_bbbb%40unq.gbl.spaces/0");
  assert.equal(O.deepLink({ kind: "group", conversation: "19:x@thread.v2" }),
    "https://teams.microsoft.com/l/chat/19%3Ax%40thread.v2/0");
  assert.equal(O.deepLink({ kind: "channel", conversation: "19:c@thread.tacv2" }), "");
  assert.equal(O.deepLink({ kind: "meeting", conversation: "19:meeting_x@thread.v2" }), "");
});
