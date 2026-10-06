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

/** Réclamé auprès du serveur (200), prêt à partir. */
function claimed(box, id, now) {
  assert.equal(O.beginClaim(box, id, now || NOW), true);
  assert.equal(O.claimResponse(box, id, 200, now || NOW), "claimed");
}

test("un envoi : réclamé au serveur d'abord, marqué avant de partir, jamais deux fois, l'issue dite", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  assert.equal(plan(box, "s1"), "send");
  assert.deepEqual(O.pendingDrafts(box, NOW), [], "un message à envoyer n'est pas un brouillon");
  assert.equal(O.beginSend(box, "s1", NOW), false, "pas d'envoi sans réclamation accordée");
  assert.equal(O.beginClaim(box, "s1", NOW), true);
  assert.equal(O.beginClaim(box, "s1", NOW), false, "une seule réclamation à la fois");
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  assert.equal(O.claimResponse(box, "s1", 200, NOW + 1000), "claimed");
  assert.equal(O.isClaimed(box, "s1"), true);
  assert.equal(plan(box, "s1", NOW + 1000), "send");
  assert.equal(O.beginSend(box, "s1", NOW + 1000), true);
  assert.equal(O.beginSend(box, "s1", NOW + 1000), false);
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  O.sendOutcome(box, "s1", { result: "sent", message_id: "1759737600000" }, NOW + 2000);
  // le texte est celui de la file : l'issue ne le redit pas
  assert.deepEqual(O.pendingAcks(box), [{ id: "s1", body: { result: "sent", message_id: "1759737600000" } }]);
  assert.equal(O.ackResponse(box, "s1", "sent", 200, NOW + 3000), "done");
  assert.equal(box.stats.sent, 1);
  assert.equal(plan(box, "s1", NOW + 4000), "wait");
  assert.equal(O.beginClaim(box, "s1", NOW + 4000), false);
  assert.equal(O.beginSend(box, "s1", NOW + 4000), false);
});

test("une réclamation refusée : 409 (pris ailleurs) ou 404 — jamais envoyé d'ici, même relisté", () => {
  const box = boxWith([item({ id: "s1", mode: "send" }), item({ id: "s2", mode: "send" })]);
  O.beginClaim(box, "s1", NOW);
  assert.equal(O.claimResponse(box, "s1", 409, NOW), "taken");
  O.beginClaim(box, "s2", NOW);
  assert.equal(O.claimResponse(box, "s2", 404, NOW), "gone");
  assert.deepEqual(Object.keys(box.items), []);
  assert.deepEqual(O.pendingAcks(box), [], "rien à dire : ce n'est plus à nous");
  O.reconcile(box, [O.normalizeItem(item({ id: "s1", mode: "send" }))], NOW + 1000);
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  assert.equal(O.beginClaim(box, "s1", NOW + 1000), false);
});

test("une réclamation sans réponse (réseau, 5xx, 429) : rien n'est réclamé, on redemandera", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  for (const status of [0, 500, 503, 429]) {
    assert.equal(O.beginClaim(box, "s1", NOW), true, String(status));
    assert.equal(O.claimResponse(box, "s1", status, NOW), "retry", String(status));
    assert.equal(O.isClaimed(box, "s1"), false);
    assert.equal(plan(box, "s1"), "send");
  }
  // une réclamation dont le service s'est arrêté au milieu est redemandée (un 409 dira si elle avait abouti)
  O.beginClaim(box, "s1", NOW);
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  assert.equal(plan(box, "s1", NOW + O.STALE_MS + 1), "send");
  assert.equal(O.beginClaim(box, "s1", NOW + O.STALE_MS + 1), true);
});

test("rien n'est parti : la réclamation reste à ce navigateur, on réessaiera, avec la raison", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "retry", reason: "conversation pas ouverte dans Teams" }, NOW + 1000);
  assert.equal(plan(box, "s1", NOW + 2000), "send");
  assert.equal(O.isClaimed(box, "s1"), true, "pas besoin de redemander au serveur");
  assert.equal(box.items.s1.lastReason, "conversation pas ouverte dans Teams");
  assert.equal(box.items.s1.attempts, 1);
  assert.deepEqual(O.pendingAcks(box), []);
  assert.equal(O.beginSend(box, "s1", NOW + 2000), true);
  assert.equal(box.items.s1.attempts, 2);
});

test("un envoi jamais réussi avant l'échéance : « jamais envoyé », réclamé ou non", () => {
  const box = boxWith([item({ id: "s1", mode: "send" }), item({ id: "s2", mode: "send" })]);
  assert.deepEqual(O.plan(box, "s1", { now: NOW + 3600000, excluded: false }),
    { do: "fail", reason: "jamais envoyé : Teams pas ouvert ou envoi impossible" });
  assert.equal(O.beginClaim(box, "s1", NOW + 3600000), false);
  claimed(box, "s2");
  assert.equal(O.plan(box, "s2", { now: NOW + 3600000, excluded: false }).reason, O.REASONS.expiredSend);
  assert.equal(O.beginSend(box, "s2", NOW + 3600000), false);
});

test("une exclusion ajoutée après la réclamation l'emporte : échec sûr, rien n'est parti", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  assert.deepEqual(O.plan(box, "s1", { now: NOW, excluded: true }), { do: "fail", reason: O.REASONS.excluded });
});

test("un envoi douteux n'est ni dit au serveur, ni retenté ; il est noté ici", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "uncertain", reason: "le service de chat a répondu 503" }, NOW + 1000);
  assert.deepEqual(O.pendingAcks(box), [], "pas d'issue : le serveur tranchera");
  assert.equal(plan(box, "s1", NOW + 2000), "wait");
  assert.equal(O.beginSend(box, "s1", NOW + 2000), false);
  assert.equal(O.beginClaim(box, "s1", NOW + 2000), false);
  assert.equal(box.log[0].result, "uncertain");
  assert.equal(box.log[0].reason, "le service de chat a répondu 503");
  assert.equal(box.stats.uncertain, 1);
  // le serveur ne le liste plus (il est réclamé) : oublié ici, la marque reste
  O.reconcile(box, [], NOW + 3000);
  assert.deepEqual(Object.keys(box.items), []);
  O.reconcile(box, [O.normalizeItem(item({ id: "s1", mode: "send" }))], NOW + 4000);
  assert.equal(plan(box, "s1", NOW + 4000), "wait");
});

test("une issue illisible compte pour douteuse, jamais pour « rien n'est parti »", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "peut-être" }, NOW);
  assert.equal(plan(box, "s1", NOW + 1000), "wait");
  assert.deepEqual(O.pendingAcks(box), []);
});

test("un envoi commencé puis perdu (service arrêté au milieu) : jamais refait, jamais dit — noté douteux", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  const reloaded = JSON.parse(JSON.stringify(box));
  assert.equal(plan(reloaded, "s1", NOW + 30000), "wait");
  const late = O.plan(reloaded, "s1", { now: NOW + O.STALE_MS + 1, excluded: false });
  assert.deepEqual(late, { do: "uncertain", reason: O.REASONS.sendInterrupted });
  O.sendOutcome(reloaded, "s1", { result: "uncertain", reason: late.reason }, NOW + O.STALE_MS + 1);
  assert.deepEqual(O.pendingAcks(reloaded), []);
  assert.equal(O.beginSend(reloaded, "s1", NOW + O.STALE_MS + 2), false);
});

// ── Ce que rend un onglet ───────────────────────────────────────────────────

test("seul « rien n'a commencé » permet de réessayer : pas de script, ou la page qui le dit", () => {
  const noScript = new Error("Could not establish connection. Receiving end does not exist.");
  assert.equal(O.tabOutcome(undefined, noScript).result, "retry");
  assert.equal(O.tabOutcome(undefined, new Error("No tab with id: 12.")).result, "retry");
  assert.equal(O.tabOutcome({ result: "retry", reason: "la page Teams ne répond pas (rechargez-la)" }, null).result,
    "retry");
  // la demande est arrivée, l'onglet a disparu ou s'est tu : peut-être parti
  assert.equal(O.tabOutcome(undefined, new Error("The message port closed before a response was received.")).result,
    "uncertain");
  assert.equal(O.tabOutcome(undefined, new Error("pas de réponse de l'onglet")).result, "uncertain");
  assert.equal(O.tabOutcome(undefined, null).result, "uncertain");
  assert.equal(O.tabOutcome({ result: "envoyé ?" }, null).result, "uncertain");
  assert.deepEqual(O.tabOutcome({ result: "sent", message_id: "42", via: "service" }, null),
    { result: "sent", reason: "", message_id: "42", via: "service" });
  assert.equal(O.tabOutcome({ result: "failed", reason: "refusé (400)" }, null).reason, "refusé (400)");
});

// ── Les réponses du serveur aux issues ──────────────────────────────────────

test("404 ou 409 : oublié ici ; une autre 4xx : redite plus tard, de plus en plus espacée ; le reste : redit", () => {
  const box = boxWith([item({ id: "a" }), item({ id: "b" }), item({ id: "c" }), item({ id: "d" }), item({ id: "e" })]);
  for (const id of ["a", "b", "c", "d", "e"]) O.fail(box, id, "x", NOW);
  assert.equal(O.ackResponse(box, "a", "failed", 404, NOW), "forget");
  assert.equal(O.ackResponse(box, "b", "failed", 409, NOW), "forget");
  assert.equal(O.ackResponse(box, "c", "failed", 400, NOW), "refused");
  assert.equal(O.ackResponse(box, "d", "failed", 503, NOW), "retry");
  assert.equal(O.ackResponse(box, "e", "failed", 401, NOW), "auth");
  assert.equal(O.ackResponse(box, "e", "failed", 429, NOW), "slow");
  assert.equal(O.ackResponse(box, "e", "failed", 403, NOW), "retry", "Teams désactivé chez Mika : pas la faute de l'issue");
  assert.deepEqual(Object.keys(box.items), ["c", "d", "e"]);
  assert.deepEqual(O.pendingAcks(box).map((a) => a.id), ["c", "d", "e"]);
  assert.deepEqual(O.pendingAcks(box, NOW + 1000).map((a) => a.id), ["d", "e"], "« c » attend avant d'être redite");
  assert.deepEqual(O.pendingAcks(box, NOW + 16000).map((a) => a.id), ["c", "d", "e"]);
  // l'oubli ne lève pas la marque : un élément relisté ne repart pas
  O.reconcile(box, [O.normalizeItem(item({ id: "a" }))], NOW + 1000);
  assert.equal(plan(box, "a", NOW + 1000), "wait");
});

test("une issue refusée dix fois est abandonnée, et le journal le dit", () => {
  const box = boxWith([item({ id: "s1", mode: "send" })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "sent" }, NOW);
  for (let i = 1; i < O.ACK_REFUSALS_MAX; i++) {
    assert.equal(O.ackResponse(box, "s1", "sent", 422, NOW + i), "refused", String(i));
  }
  assert.equal(O.ackResponse(box, "s1", "sent", 422, NOW + 99), "dropped");
  assert.deepEqual(O.pendingAcks(box), []);
  assert.equal(box.log[0].result, "dropped");
  assert.match(box.log[0].reason, /10 fois/);
  assert.equal(box.stats.dropped, 1);
});

test("une issue pas encore dite reste, même quand le serveur ne liste plus l'élément", () => {
  const box = boxWith([item({ id: "t12" }), item({ id: "s1", mode: "send" }), item({ id: "s2", mode: "send" })]);
  O.claim(box, "t12", NOW, false);
  O.placed(box, "t12", NOW);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "sent", message_id: "77" }, NOW);
  claimed(box, "s2"); // réclamé, pas encore envoyé
  // le serveur ne liste plus rien : un brouillon placé ailleurs, des éléments réclamés
  const gone = O.reconcile(box, [], NOW + 1000);
  assert.deepEqual(gone, []);
  assert.deepEqual(O.pendingAcks(box).map((a) => a.id).sort(), ["s1", "t12"]);
  assert.equal(plan(box, "s2", NOW + 1000), "send", "la réclamation tient : l'envoi reste à faire");
  // les issues dites, l'élément s'oublie au relevé suivant
  O.ackResponse(box, "t12", "placed", 200, NOW + 2000);
  O.ackResponse(box, "s1", "sent", 200, NOW + 2000);
  assert.deepEqual(O.reconcile(box, [], NOW + 3000).sort(), ["s1", "t12"]);
});

test("le journal local ne garde que 120 caractères du texte", () => {
  const box = boxWith([item({ id: "s1", mode: "send", text: "mot ".repeat(200) })]);
  claimed(box, "s1");
  O.beginSend(box, "s1", NOW);
  O.sendOutcome(box, "s1", { result: "sent" }, NOW);
  O.ackResponse(box, "s1", "sent", 200, NOW);
  assert.ok(box.log[0].text.length <= 120);
  assert.equal(O.pendingAcks(box).length, 0);
});

test("une issue « envoyé » qui porterait un texte le coupe à 8000 caractères, sans casser un emoji", () => {
  const body = O.ackBody({ result: "sent", message_id: "1", text: "x".repeat(7999) + "👍" + "y".repeat(10) });
  assert.equal(body.text.length, 7999);
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
