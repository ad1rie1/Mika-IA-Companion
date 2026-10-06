/*
 * Ce que Mika écrit dans Teams, vu de l'extension. Pur : l'horloge est passée en paramètre, l'état (`box`) est un
 * objet ordinaire gardé dans `chrome.storage.local` — utilisé par le service d'arrière-plan, et par les tests sous
 * Node.
 *
 * Le serveur liste ce qui attend (`GET /api/teams/outbox`) : un brouillon (`draft`, que l'utilisateur enverra lui-même)
 * ou un message à envoyer (`send`). L'extension rend chaque issue (`POST /api/teams/outbox/<id>`) : `placed`, `sent`
 * ou `failed`. Deux règles tiennent tout le reste :
 *
 *   - un geste irréversible n'est jamais refait : un brouillon placé dans ce navigateur, un envoi commencé, gardent
 *     une marque (`box.marks`) qui survit à l'arrêt du service et à une liste du serveur en retard ;
 *   - une issue est retenue tant que le serveur ne l'a pas reçue (`entry.ack`), et redite telle quelle : redire la
 *     même issue ne change rien chez lui.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MikaTeamsOutbox = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const REASONS = {
    expiredSend: "jamais envoyé : Teams pas ouvert ou envoi impossible",
    excluded: "conversation exclue dans l'extension Teams",
    sendInterrupted: "envoi interrompu : peut-être parti, à vérifier dans Teams",
    placeInterrupted: "placement interrompu : peut-être dans la zone de saisie, à vérifier dans Teams",
    uncertain: "envoi incertain : Teams n'a pas répondu à temps, à vérifier dans Teams",
    sendFailed: "Teams n'a pas pris le message",
  };

  const MODES = ["draft", "send"];
  const STATUSES = ["queued", "placed"];
  const STALE_MS = 2 * 60 * 1000; // un placement ou un envoi commencé sans issue depuis : interrompu
  const MARKS_KEEP_MS = 7 * 24 * 3600 * 1000;
  const LOG_MAX = 30;
  const EXCERPT = 120;
  const MAX_TEXT = 20000;

  function freshBox() {
    return { items: {}, marks: {}, log: [], stats: { placed: 0, sent: 0, failed: 0 } };
  }

  function str(v, max) {
    return typeof v === "string" ? v.slice(0, max) : typeof v === "number" && isFinite(v) ? String(v).slice(0, max) : "";
  }

  function excerpt(text) {
    const t = String(text || "").replace(/\s+/g, " ").trim();
    return t.length > EXCERPT ? t.slice(0, EXCERPT - 1).trimEnd() + "…" : t;
  }

  /** Un élément de la liste du serveur, vérifié ; `null` s'il n'en a pas la forme. */
  function normalizeItem(raw) {
    if (!raw || typeof raw !== "object") return null;
    const id = str(raw.id, 64);
    const conversation = str(raw.conversation, 300);
    const text = typeof raw.text === "string" ? raw.text.slice(0, MAX_TEXT) : "";
    if (!id || !conversation || !text.trim()) return null;
    const mode = MODES.indexOf(raw.mode) >= 0 ? raw.mode : "draft";
    const status = STATUSES.indexOf(raw.status) >= 0 ? raw.status : "queued";
    return {
      id: id, conversation: conversation, title: str(raw.title, 120), kind: str(raw.kind, 20) || "other",
      mode: mode, status: status, text: text,
      created_at: Number(raw.created_at) || 0, expires_at: Number(raw.expires_at) || 0,
    };
  }

  /**
   * La liste du serveur fait foi pour ce qui existe : un élément qui n'y est plus a été fermé chez lui, on l'oublie
   * (sa marque reste, le temps de `MARKS_KEEP_MS`). Rend les identifiants oubliés.
   */
  function reconcile(box, items, now) {
    const listed = {};
    for (const item of items || []) {
      listed[item.id] = true;
      box.items[item.id] = Object.assign({}, box.items[item.id] || {}, item);
    }
    const gone = [];
    for (const id of Object.keys(box.items)) {
      if (!listed[id]) {
        gone.push(id);
        delete box.items[id];
      }
    }
    for (const id of Object.keys(box.marks)) {
      if (!listed[id] && now - (box.marks[id].at || 0) > MARKS_KEEP_MS) delete box.marks[id];
    }
    return gone;
  }

  /**
   * Ce qu'il faut faire d'un élément : `ack` (une issue à redire), `fail` (avec `reason`), `notify` (un brouillon
   * jamais annoncé), `place` (un brouillon annoncé, qui attend sa conversation), `send`, ou `wait`.
   * `ctx` : `now`, `excluded` (la conversation est exclue dans l'extension).
   */
  function plan(box, id, ctx) {
    const e = box.items[id];
    if (!e) return { do: "wait" };
    if (e.ack) return { do: "ack" };
    if (e.closed) return { do: "wait" };
    const mark = box.marks[id];
    if (mark && (mark.act === "placing" || mark.act === "sending")) {
      // commencé, sans issue : le service s'est arrêté au milieu. Ni refait, ni passé sous silence.
      if (ctx.now - mark.at <= STALE_MS) return { do: "wait" };
      return { do: "fail", reason: mark.act === "sending" ? REASONS.sendInterrupted : REASONS.placeInterrupted };
    }
    if (mark) return { do: "wait" };
    if (e.status !== "queued") return { do: "wait" };
    if (ctx.excluded) return { do: "fail", reason: REASONS.excluded };
    if (e.expires_at && ctx.now >= e.expires_at) {
      // un envoi jamais réussi est un échec ; un brouillon jamais placé n'en est pas un : le serveur le clôt lui-même
      return e.mode === "send" ? { do: "fail", reason: REASONS.expiredSend } : { do: "wait" };
    }
    if (e.mode === "send") return { do: "send" };
    return e.notifiedAt ? { do: "place" } : { do: "notify" };
  }

  function placeable(box, id, now, excluded) {
    const e = box.items[id];
    return Boolean(e) && e.mode === "draft" && e.status === "queued" && !e.ack && !e.closed && !box.marks[id]
      && !excluded && !(e.expires_at && now >= e.expires_at);
  }

  /** Un onglet veut placer ce brouillon : un seul y a droit, une seule fois. */
  function claim(box, id, now, excluded) {
    if (!placeable(box, id, now, excluded)) return false;
    box.marks[id] = { act: "placing", at: now };
    return true;
  }

  /** Le brouillon est dans la zone de saisie : à dire au serveur. Seulement après un `claim` accordé. */
  function placed(box, id, now) {
    const mark = box.marks[id];
    if (!mark || mark.act !== "placing") return false;
    box.marks[id] = { act: "placed", at: now };
    const e = box.items[id];
    if (e) e.ack = { result: "placed" };
    return true;
  }

  /** L'onglet n'a pas pu l'insérer : le brouillon redevient à placer. */
  function release(box, id) {
    const mark = box.marks[id];
    if (mark && mark.act === "placing") delete box.marks[id];
  }

  /** Un envoi commence : marqué avant de partir, pour ne jamais partir deux fois. */
  function beginSend(box, id, now) {
    const e = box.items[id];
    if (!e || e.mode !== "send" || e.status !== "queued" || e.ack || e.closed || box.marks[id]) return false;
    if (e.expires_at && now >= e.expires_at) return false;
    box.marks[id] = { act: "sending", at: now };
    e.attempts = (e.attempts || 0) + 1;
    return true;
  }

  /**
   * L'issue d'un envoi par un onglet : `sent` (avec `message_id`), `failed` et `uncertain` (l'issue est connue ou
   * douteuse : on ne réessaie pas), `retry` (rien n'est parti : la marque est levée, on réessaiera).
   */
  function sendOutcome(box, id, outcome, now) {
    const e = box.items[id];
    const result = outcome && outcome.result;
    if (result === "sent") {
      box.marks[id] = { act: "sent", at: now };
      if (e) {
        e.ack = { result: "sent", message_id: str(outcome.message_id, 200), text: e.text };
        e.lastReason = "";
      }
    } else if (result === "failed" || result === "uncertain") {
      const reason = result === "uncertain" ? REASONS.uncertain : (str(outcome.reason, 200) || REASONS.sendFailed);
      box.marks[id] = { act: "failed", at: now };
      if (e) e.ack = { result: "failed", reason: reason };
    } else {
      const mark = box.marks[id];
      if (mark && mark.act === "sending") delete box.marks[id];
      if (e) e.lastReason = str(outcome && outcome.reason, 200);
    }
  }

  /** Abandonner un élément : l'issue `failed` sera dite au serveur. */
  function fail(box, id, reason, now) {
    box.marks[id] = { act: "failed", at: now };
    const e = box.items[id];
    if (e) e.ack = { result: "failed", reason: str(reason, 200) };
  }

  /** Le corps d'une issue, tel qu'il part. */
  function ackBody(ack) {
    const body = { result: ack.result };
    if (ack.result === "failed") body.reason = ack.reason || "";
    if (ack.result === "sent") {
      if (ack.message_id) body.message_id = ack.message_id;
      if (ack.text) body.text = ack.text;
    }
    return body;
  }

  /** Les issues à dire, la plus ancienne d'abord : `[{id, body}]`. */
  function pendingAcks(box) {
    return Object.keys(box.items).map(function (id) { return box.items[id]; })
      .filter(function (e) { return e.ack; })
      .sort(function (a, b) { return (a.created_at || 0) - (b.created_at || 0); })
      .map(function (e) { return { id: e.id, body: ackBody(e.ack) }; });
  }

  /**
   * La réponse du serveur à une issue. Rend `done` (200), `forget` (404 élément inconnu, 409 transition
   * impossible : on l'oublie ici), `refused` (400 : redire ne servirait à rien) ou `retry` (le reste).
   */
  function ackResponse(box, id, result, status, now) {
    const e = box.items[id];
    if (status === 200) {
      if (e) {
        const ack = e.ack || { result: result };
        box.log.unshift({ at: now, id: id, mode: e.mode, title: e.title || "", result: result,
          reason: ack.reason || "", text: excerpt(ack.text || e.text) });
        box.log = box.log.slice(0, LOG_MAX);
        e.ack = null;
        e.acked = result;
        if (result !== "placed") e.closed = true;
      }
      if (Object.prototype.hasOwnProperty.call(box.stats, result)) box.stats[result]++;
      return "done";
    }
    if (status === 404 || status === 409) {
      delete box.items[id];
      return "forget";
    }
    if (status === 400) {
      delete box.items[id];
      return "refused";
    }
    return "retry";
  }

  /** Les brouillons que les onglets peuvent placer : `[{id, conversation, text}]`, le plus ancien d'abord. */
  function pendingDrafts(box, now, isExcluded) {
    return Object.keys(box.items).map(function (id) { return box.items[id]; })
      .filter(function (e) { return placeable(box, e.id, now, Boolean(isExcluded && isExcluded(e))); })
      .sort(function (a, b) { return (a.created_at || 0) - (b.created_at || 0); })
      .slice(0, 50)
      .map(function (e) { return { id: e.id, conversation: e.conversation, text: e.text }; });
  }

  /** Ce qui attend, pour la page de réglages (sans le texte). */
  function waiting(box, now) {
    return Object.keys(box.items).map(function (id) { return box.items[id]; })
      .filter(function (e) {
        const p = plan(box, e.id, { now: now, excluded: false });
        return p.do === "notify" || p.do === "place" || p.do === "send";
      })
      .sort(function (a, b) { return (a.created_at || 0) - (b.created_at || 0); })
      .map(function (e) {
        return { id: e.id, mode: e.mode, title: e.title || "", kind: e.kind, expires_at: e.expires_at,
          attempts: e.attempts || 0, lastReason: e.lastReason || "" };
      });
  }

  /**
   * Le lien qui ouvre une conversation dans Teams web : pour un tête-à-tête ou un groupe seulement (un canal ou une
   * réunion n'ont pas de lien de discussion : on ne fait que montrer l'onglet). « » sinon.
   */
  function deepLink(entry) {
    if (!entry || (entry.kind !== "dm" && entry.kind !== "group")) return "";
    return "https://teams.microsoft.com/l/chat/" + encodeURIComponent(entry.conversation) + "/0";
  }

  return { REASONS: REASONS, STALE_MS: STALE_MS, freshBox: freshBox, normalizeItem: normalizeItem,
    reconcile: reconcile, plan: plan, claim: claim, placed: placed, release: release, beginSend: beginSend,
    sendOutcome: sendOutcome, fail: fail, ackBody: ackBody, pendingAcks: pendingAcks, ackResponse: ackResponse,
    pendingDrafts: pendingDrafts, waiting: waiting, deepLink: deepLink, excerpt: excerpt };
});
