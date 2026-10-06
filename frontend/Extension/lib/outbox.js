/*
 * Ce que Mika écrit dans Teams, vu de l'extension. Pur : l'horloge est passée en paramètre, l'état (`box`) est un
 * objet ordinaire gardé dans `chrome.storage.local` — utilisé par le service d'arrière-plan, et par les tests sous
 * Node.
 *
 * Le serveur liste ce qui attend (`GET /api/teams/outbox`) : un brouillon (`draft`, que l'utilisateur enverra lui-même)
 * ou un message à envoyer (`send`). L'extension rend chaque issue (`POST /api/teams/outbox/<id>`) : `placed`, `sent`
 * ou `failed`. Un message à envoyer est d'abord **réclamé** (`sending`) : le serveur ne l'accorde qu'à un seul
 * navigateur, et une seule fois ; l'élément réclamé disparaît alors de sa liste. Trois règles tiennent le reste :
 *
 *   - un geste irréversible n'est jamais refait : un brouillon placé dans ce navigateur, un envoi commencé, gardent
 *     une marque (`box.marks`) qui survit à l'arrêt du service et à une liste du serveur en retard ;
 *   - une issue n'est dite que si elle est **sûre** : envoyé, ou pas envoyé. Une issue douteuse (l'envoi a commencé,
 *     la réponse manque ou ne tranche pas) n'est ni dite ni retentée — le serveur la tranche lui-même, en voyant le
 *     message de l'utilisateur arriver dans la conversation, ou à l'échéance ;
 *   - une issue est retenue tant que le serveur ne l'a pas reçue (`entry.ack`), même quand il ne liste plus l'élément,
 *     et redite telle quelle : redire la même issue ne change rien chez lui.
 *
 * Les marques : `placing` → `placed` (brouillon) ; `claiming` → `claimed` → `sending` → `sent`, `failed` ou
 * `uncertain` (envoi) ; `taken` (réclamé ailleurs, 409), `gone` (inconnu du serveur, 404).
 */
(function (root, factory) {
  const node = typeof module === "object" && module && module.exports && typeof require === "function";
  const api = factory(node ? require("./text.js") : root.MikaTeamsText);
  if (node) module.exports = api;
  else root.MikaTeamsOutbox = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (T) {
  "use strict";

  const REASONS = {
    expiredSend: "jamais envoyé : Teams pas ouvert ou envoi impossible",
    excluded: "conversation exclue dans l'extension Teams",
    sendInterrupted: "envoi interrompu : peut-être parti, à vérifier dans Teams",
    placeInterrupted: "placement interrompu : peut-être dans la zone de saisie, à vérifier dans Teams",
    uncertain: "envoi incertain : Teams n'a pas répondu à temps, à vérifier dans Teams",
    sendFailed: "Teams n'a pas pris le message",
    noTab: "onglet Teams sans le script (rechargez-le)",
    tabGone: "l'onglet Teams s'est fermé ou figé pendant l'envoi",
    unreadable: "réponse illisible de l'onglet Teams",
  };

  const MODES = ["draft", "send"];
  const STATUSES = ["queued", "placed"];
  const RESULTS = ["sent", "failed", "uncertain", "retry"];
  const STALE_MS = 2 * 60 * 1000; // un placement, une réclamation ou un envoi commencé sans issue depuis : interrompu
  const MARKS_KEEP_MS = 7 * 24 * 3600 * 1000;
  const LOG_MAX = 30;
  const EXCERPT = 120;
  const MAX_TEXT = 20000;
  const ACK_TEXT_MAX = 8000; // le plafond du serveur pour le texte d'une issue
  const ACK_REFUSALS_MAX = 10; // une même issue refusée autant de fois (4xx) est abandonnée

  function freshBox() {
    return { items: {}, marks: {}, log: [], stats: { placed: 0, sent: 0, failed: 0, uncertain: 0, dropped: 0 } };
  }

  function str(v, max) {
    return typeof v === "string" ? T.cut(v, max) : typeof v === "number" && isFinite(v) ? T.cut(String(v), max) : "";
  }

  function excerpt(text) {
    return T.clip(String(text || "").replace(/\s+/g, " ").trim(), EXCERPT);
  }

  function expired(e, now) {
    return Boolean(e.expires_at) && now >= e.expires_at;
  }

  function actOf(box, id) {
    const mark = box.marks[id];
    return mark ? mark.act : "";
  }

  function note(box, e, result, reason, text, now) {
    box.log.unshift({ at: now, id: e.id, mode: e.mode, title: e.title || "", result: result, reason: reason || "",
      text: excerpt(text) });
    box.log = box.log.slice(0, LOG_MAX);
  }

  /** Un élément de la liste du serveur, vérifié ; `null` s'il n'en a pas la forme. */
  function normalizeItem(raw) {
    if (!raw || typeof raw !== "object") return null;
    const id = str(raw.id, 64);
    const conversation = str(raw.conversation, 300);
    const text = typeof raw.text === "string" ? T.cut(raw.text, MAX_TEXT) : "";
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
   * Ce qu'on garde d'un élément que le serveur ne liste plus : une issue pas encore dite, ou une réclamation
   * accordée (le serveur retire de sa liste ce qui est réclamé, l'envoi reste à faire ici).
   */
  function kept(box, id) {
    const e = box.items[id];
    const act = actOf(box, id);
    return Boolean(e && e.ack) || act === "claiming" || act === "claimed";
  }

  /**
   * La liste du serveur fait foi pour ce qui existe : un élément qui n'y est plus a été fermé ou réclamé chez lui, on
   * l'oublie (sa marque reste, le temps de `MARKS_KEEP_MS`) — sauf ce que `kept` retient. Rend les identifiants
   * oubliés.
   */
  function reconcile(box, items, now) {
    const listed = {};
    for (const item of items || []) {
      listed[item.id] = true;
      box.items[item.id] = Object.assign({}, box.items[item.id] || {}, item);
    }
    const gone = [];
    for (const id of Object.keys(box.items)) {
      if (!listed[id] && !kept(box, id)) {
        gone.push(id);
        delete box.items[id];
      }
    }
    for (const id of Object.keys(box.marks)) {
      if (!listed[id] && !box.items[id] && now - (box.marks[id].at || 0) > MARKS_KEEP_MS) delete box.marks[id];
    }
    return gone;
  }

  /**
   * Ce qu'il faut faire d'un élément : `ack` (une issue à redire), `fail` (avec `reason`), `uncertain` (avec
   * `reason` : un envoi commencé resté sans issue, à noter sans rien dire au serveur), `notify` (un brouillon jamais
   * annoncé), `place` (un brouillon annoncé, qui attend sa conversation), `send` (à réclamer, ou déjà réclamé : à
   * envoyer), ou `wait`. `ctx` : `now`, `excluded` (la conversation est exclue dans l'extension).
   */
  function plan(box, id, ctx) {
    const e = box.items[id];
    if (!e) return { do: "wait" };
    if (e.ack) return { do: "ack" };
    if (e.closed) return { do: "wait" };
    const mark = box.marks[id];
    const act = mark ? mark.act : "";
    const stale = Boolean(mark) && ctx.now - mark.at > STALE_MS;
    if (act === "placing") {
      // commencé, sans issue : le service s'est arrêté au milieu. Ni refait, ni passé sous silence.
      return stale ? { do: "fail", reason: REASONS.placeInterrupted } : { do: "wait" };
    }
    if (act === "sending") {
      // peut-être parti : jamais refait, jamais dit — le serveur tranchera
      return stale ? { do: "uncertain", reason: REASONS.sendInterrupted } : { do: "wait" };
    }
    if (act === "claiming" && !stale) return { do: "wait" };
    const claimed = act === "claimed";
    if (act && !claimed && act !== "claiming") return { do: "wait" };
    if (!claimed && e.status !== "queued") return { do: "wait" };
    // rien n'est parti : l'échec est sûr
    if (ctx.excluded) return { do: "fail", reason: REASONS.excluded };
    if (expired(e, ctx.now)) {
      // un envoi jamais réussi est un échec ; un brouillon jamais placé n'en est pas un : le serveur le clôt lui-même
      return e.mode === "send" ? { do: "fail", reason: REASONS.expiredSend } : { do: "wait" };
    }
    if (e.mode === "send") return { do: "send" };
    return e.notifiedAt ? { do: "place" } : { do: "notify" };
  }

  // ── Les brouillons ──────────────────────────────────────────────────────────

  function placeable(box, id, now, excluded) {
    const e = box.items[id];
    return Boolean(e) && e.mode === "draft" && e.status === "queued" && !e.ack && !e.closed && !box.marks[id]
      && !excluded && !expired(e, now);
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

  // ── Les messages à envoyer ─────────────────────────────────────────────────

  /** Ce navigateur détient la réclamation : il peut envoyer (et réessayer tant que rien n'est parti). */
  function isClaimed(box, id) {
    return actOf(box, id) === "claimed";
  }

  /** Une réclamation commence : marquée avant de la demander au serveur. */
  function beginClaim(box, id, now) {
    const e = box.items[id];
    const mark = box.marks[id];
    if (!e || e.mode !== "send" || e.status !== "queued" || e.ack || e.closed || expired(e, now)) return false;
    if (mark && !(mark.act === "claiming" && now - mark.at > STALE_MS)) return false;
    box.marks[id] = { act: "claiming", at: now };
    return true;
  }

  /**
   * La réponse du serveur à une réclamation. Rend `claimed` (200 : à ce navigateur d'envoyer), `taken` (409 : un
   * autre navigateur, ou une tentative d'avant dont la réponse s'est perdue, l'a déjà — jamais envoyé d'ici),
   * `gone` (404 : oublié) ou `retry` (rien n'est réclamé : redemander plus tard).
   */
  function claimResponse(box, id, status, now) {
    if (actOf(box, id) !== "claiming") return "retry";
    if (status === 200) {
      box.marks[id] = { act: "claimed", at: now };
      return "claimed";
    }
    if (status === 409 || status === 404) {
      box.marks[id] = { act: status === 409 ? "taken" : "gone", at: now };
      delete box.items[id];
      return status === 409 ? "taken" : "gone";
    }
    delete box.marks[id];
    return "retry";
  }

  /** Un envoi commence, réclamation en main : marqué avant de partir, pour ne jamais partir deux fois. */
  function beginSend(box, id, now) {
    const e = box.items[id];
    const mark = box.marks[id];
    if (!e || e.mode !== "send" || e.ack || e.closed || !mark || mark.act !== "claimed") return false;
    if (expired(e, now)) return false;
    box.marks[id] = { act: "sending", at: now, claimedAt: mark.at };
    e.attempts = (e.attempts || 0) + 1;
    return true;
  }

  /**
   * Ce que rend un onglet à qui l'on a demandé d'envoyer. `answer` : sa réponse ; `error` : l'erreur de
   * `chrome.tabs.sendMessage`. Seuls « pas de script dans l'onglet » et une réponse `retry` (la page n'a rien
   * commencé, ou dit sûrement que rien n'est parti) permettent de réessayer ; un onglet qui disparaît ou répond de
   * travers après avoir reçu la demande laisse l'issue douteuse.
   */
  function tabOutcome(answer, error) {
    if (error) {
      const text = String(error && error.message ? error.message : error);
      if (/receiving end does not exist|could not establish connection|no tab with id/i.test(text)) {
        return { result: "retry", reason: REASONS.noTab };
      }
      return { result: "uncertain", reason: REASONS.tabGone };
    }
    if (!answer || typeof answer !== "object" || RESULTS.indexOf(answer.result) < 0) {
      return { result: "uncertain", reason: REASONS.unreadable };
    }
    return { result: answer.result, reason: str(answer.reason, 200), message_id: str(answer.message_id, 200),
      via: str(answer.via, 20) };
  }

  /**
   * L'issue d'un envoi : `sent` (avec `message_id`) et `failed` sont sûres et seront dites au serveur ; `retry` :
   * rien n'est parti, la réclamation reste à ce navigateur, on réessaiera ; tout le reste est `uncertain` : ni dit,
   * ni retenté, seulement noté dans le journal local.
   */
  function sendOutcome(box, id, outcome, now) {
    const e = box.items[id];
    const result = outcome && RESULTS.indexOf(outcome.result) >= 0 ? outcome.result : "uncertain";
    const reason = str(outcome && outcome.reason, 200);
    if (result === "sent") {
      box.marks[id] = { act: "sent", at: now };
      if (e) {
        // le texte est celui de la file : inutile de le redire
        e.ack = { result: "sent", message_id: str(outcome.message_id, 200) };
        e.lastReason = "";
      }
    } else if (result === "failed") {
      box.marks[id] = { act: "failed", at: now };
      if (e) e.ack = { result: "failed", reason: reason || REASONS.sendFailed };
    } else if (result === "retry") {
      const mark = box.marks[id];
      if (mark && mark.act === "sending") box.marks[id] = { act: "claimed", at: mark.claimedAt || now };
      if (e) e.lastReason = reason;
    } else {
      box.marks[id] = { act: "uncertain", at: now };
      box.stats.uncertain = (box.stats.uncertain || 0) + 1;
      if (e) {
        e.closed = true;
        e.lastReason = reason || REASONS.uncertain;
        note(box, e, "uncertain", e.lastReason, e.text, now);
      }
    }
  }

  /** Abandonner un élément dont rien n'est parti : l'issue `failed` sera dite au serveur. */
  function fail(box, id, reason, now) {
    box.marks[id] = { act: "failed", at: now };
    const e = box.items[id];
    if (e) e.ack = { result: "failed", reason: str(reason, 200) };
  }

  // ── Les issues ──────────────────────────────────────────────────────────────

  /** Le corps d'une issue, tel qu'il part. */
  function ackBody(ack) {
    const body = { result: ack.result };
    if (ack.result === "failed") body.reason = ack.reason || "";
    if (ack.result === "sent") {
      if (ack.message_id) body.message_id = ack.message_id;
      if (ack.text) body.text = T.cut(ack.text, ACK_TEXT_MAX);
    }
    return body;
  }

  /**
   * Les issues à dire, la plus ancienne d'abord : `[{id, body}]`. Avec `now`, sans celles qu'un refus récent fait
   * attendre.
   */
  function pendingAcks(box, now) {
    return Object.keys(box.items).map(function (id) { return box.items[id]; })
      .filter(function (e) { return e.ack && (now === undefined || !(e.ackAfter > now)); })
      .sort(function (a, b) { return (a.created_at || 0) - (b.created_at || 0); })
      .map(function (e) { return { id: e.id, body: ackBody(e.ack) }; });
  }

  /**
   * La réponse du serveur à une issue. Rend `done` (200), `forget` (404 élément inconnu, 409 transition impossible :
   * on l'oublie ici), `auth` (401), `slow` (429), `refused` (une autre 4xx : redite plus tard, de plus en plus
   * espacée), `dropped` (la `ACK_REFUSALS_MAX`-ième : abandonnée, notée au journal) ou `retry` (pas de réponse, 5xx,
   * 403, 408 : le serveur ne peut pas l'entendre pour l'instant).
   */
  function ackResponse(box, id, result, status, now) {
    const e = box.items[id];
    if (status === 200) {
      if (e) {
        const ack = e.ack || { result: result };
        note(box, e, result, ack.reason || "", ack.text || e.text, now);
        e.ack = null;
        e.acked = result;
        e.refusals = 0;
        e.ackAfter = 0;
        if (result !== "placed") e.closed = true;
      }
      if (Object.prototype.hasOwnProperty.call(box.stats, result)) box.stats[result]++;
      return "done";
    }
    if (status === 404 || status === 409) {
      delete box.items[id];
      return "forget";
    }
    if (status === 401) return "auth";
    if (status === 429) return "slow";
    if (status >= 400 && status < 500 && status !== 403 && status !== 408) {
      if (!e) return "refused";
      e.refusals = (e.refusals || 0) + 1;
      if (e.refusals >= ACK_REFUSALS_MAX) {
        note(box, e, "dropped", "issue « " + result + " » refusée " + e.refusals + " fois par Mika (" + status
          + ") : abandonnée", e.text, now);
        box.stats.dropped = (box.stats.dropped || 0) + 1;
        delete box.items[id];
        return "dropped";
      }
      e.ackAfter = now + Math.min(300, 15 * Math.pow(2, e.refusals - 1)) * 1000;
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

  return { REASONS: REASONS, STALE_MS: STALE_MS, ACK_REFUSALS_MAX: ACK_REFUSALS_MAX, freshBox: freshBox,
    normalizeItem: normalizeItem, reconcile: reconcile, plan: plan, claim: claim, placed: placed, release: release,
    isClaimed: isClaimed, beginClaim: beginClaim, claimResponse: claimResponse, beginSend: beginSend,
    tabOutcome: tabOutcome, sendOutcome: sendOutcome, fail: fail, ackBody: ackBody, pendingAcks: pendingAcks,
    ackResponse: ackResponse, pendingDrafts: pendingDrafts, waiting: waiting, deepLink: deepLink, excerpt: excerpt };
});
