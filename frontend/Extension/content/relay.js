/*
 * Le relais (monde isolé de l'extension), entre le script de la page et le service d'arrière-plan :
 *   - vers le service : ce que la page a capté, la demande de placer un brouillon (« claim »), et ce qu'il en est
 *     advenu (« placed ») ;
 *   - vers la page : la liste des brouillons à placer, un message à envoyer (et son issue, rendue au service), une
 *     demande de diagnostic ou de la conversation ouverte, et la demande de redire les noms de conversation.
 * La page peut tout poster sur `window` : on ne relaie que des formes connues, bornées.
 *
 * Un envoi suit une règle simple : tant que la page n'a pas dit « commencé », rien n'est parti (`retry`) ; une fois
 * qu'elle l'a dit, une réponse qui manque ou qui ne se lit pas laisse l'issue douteuse (`uncertain`). La page ne
 * commence pas une demande arrivée après l'échéance qu'on lui donne, bien avant qu'on cesse de l'attendre.
 */
(function () {
  "use strict";
  const T = globalThis.MikaTeamsText;
  const TAG = "mika-teams";
  const MAX_ITEMS = 300;
  const MAX_DRAFTS = 50;
  const MAX_OUT_TEXT = 20000;
  const ASK_TIMEOUT_MS = { diagnose: 8000, where: 2000 };
  const START_DEADLINE_MS = 1500; // la page ne commence plus un envoi demandé il y a plus longtemps
  const SEND_START_MS = 4000; // sans « commencé » d'ici là : rien n'est parti
  const SEND_TIMEOUT_MS = 30000; // commencé, sans issue d'ici là : douteux
  const RESULTS = ["sent", "retry", "failed", "uncertain"];
  const waiting = new Map();
  const sending = new Map();

  function str(v, max) {
    return typeof v === "string" ? T.cut(v, max) : typeof v === "number" ? T.cut(String(v), max) : "";
  }

  function nonce() {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  function message(m) {
    if (!m || typeof m !== "object") return null;
    const time = Number(m.time);
    const deleted = m.deleted === true;
    const text = deleted ? "" : str(m.text, 4000);
    if (!isFinite(time) || !str(m.id, 200) || (!text && !deleted)) return null;
    const out = {
      id: str(m.id, 200), conv: str(m.conv, 300), author: str(m.author, 120), authorId: str(m.authorId, 200),
      time: time, type: str(m.type, 60), text: text, source: m.source === "idb" ? "idb" : "network",
      mentions: Array.isArray(m.mentions) ? m.mentions.slice(0, 20).map(function (x) { return str(x, 200); }) : [],
    };
    if (deleted) out.deleted = true;
    return out;
  }

  function conversation(c) {
    if (!c || typeof c !== "object" || !str(c.id, 300)) return null;
    return { id: str(c.id, 300), title: str(c.title, 120), threadType: str(c.threadType, 40) };
  }

  function draft(d) {
    if (!d || typeof d !== "object") return null;
    const id = str(d.id, 64);
    const conv = str(d.conversation, 300);
    const text = typeof d.text === "string" ? T.cut(d.text, MAX_OUT_TEXT) : "";
    return id && conv && text ? { id: id, conversation: conv, text: text } : null;
  }

  function drafts(list) {
    return (Array.isArray(list) ? list.slice(0, MAX_DRAFTS) : []).map(draft).filter(Boolean);
  }

  /** L'issue rendue par la page ; illisible, elle est douteuse (la page avait commencé). */
  function sendResult(r) {
    const o = r && typeof r === "object" ? r : {};
    return { result: RESULTS.indexOf(o.result) >= 0 ? o.result : "uncertain", reason: str(o.reason, 200),
      message_id: str(o.message_id, 200), via: str(o.via, 20) };
  }

  function send(payload) {
    try {
      return chrome.runtime.sendMessage(payload).catch(function () { return null; /* extension rechargée ou endormie */ });
    } catch (_) {
      // contexte invalidé : l'extension a été rechargée, la page aussi le sera
      return Promise.resolve(null);
    }
  }

  function toPage(kind, payload) {
    window.postMessage(Object.assign({ __mika: TAG, dir: "in", kind: kind }, payload || {}), location.origin);
  }

  window.addEventListener("message", function (event) {
    const data = event.data;
    if (event.source !== window || !data || data.__mika !== TAG || data.dir !== "out") return;
    if (data.kind === "captured") {
      const messages = (Array.isArray(data.messages) ? data.messages.slice(0, MAX_ITEMS) : []).map(message)
        .filter(Boolean);
      const conversations = (Array.isArray(data.conversations) ? data.conversations.slice(0, MAX_ITEMS) : [])
        .map(conversation).filter(Boolean);
      if (messages.length || conversations.length) {
        send({ kind: "captured", messages: messages, conversations: conversations, self: str(data.self, 64) });
      }
    } else if (data.kind === "report" && waiting.has(data.nonce)) {
      waiting.get(data.nonce)({ ok: true, report: data.report });
      waiting.delete(data.nonce);
    } else if (data.kind === "claim" && str(data.nonce, 64) && str(data.id, 64)) {
      const id = str(data.id, 64);
      const n = str(data.nonce, 64);
      send({ kind: "claim", id: id }).then(function (answer) {
        toPage("answer", { nonce: n, ok: Boolean(answer && answer.ok === true) });
      });
    } else if (data.kind === "placed" && str(data.id, 64)) {
      send({ kind: "placedResult", id: str(data.id, 64), ok: data.ok === true, reason: str(data.reason, 200) });
    } else if (data.kind === "sendStarted" && sending.has(data.nonce)) {
      sending.get(data.nonce).started = true;
    } else if (data.kind === "sendResult" && sending.has(data.nonce)) {
      const entry = sending.get(data.nonce);
      sending.delete(data.nonce);
      const result = sendResult(data.result);
      // une page qui n'a jamais dit « commencé » n'a rien envoyé, quoi qu'elle rende
      entry.reply(entry.started || result.result === "retry" ? result
        : { result: "retry", reason: result.reason || "la page Teams n'a pas commencé l'envoi" });
    }
  });

  function ask(kind, reply) {
    const n = nonce();
    waiting.set(n, reply);
    toPage(kind, { nonce: n });
    setTimeout(function () {
      if (waiting.has(n)) {
        waiting.get(n)({ ok: false, error: "la page Teams ne répond pas (rechargez-la)" });
        waiting.delete(n);
      }
    }, ASK_TIMEOUT_MS[kind]);
  }

  function sendThroughPage(item, reply) {
    const n = nonce();
    const entry = { reply: reply, started: false };
    sending.set(n, entry);
    toPage("send", { nonce: n, item: item, deadline: Date.now() + START_DEADLINE_MS });
    // la page n'a pas pris la demande à temps (et ne la prendra plus) : rien n'est parti, on peut réessayer
    setTimeout(function () {
      if (sending.get(n) === entry && !entry.started) {
        sending.delete(n);
        reply({ result: "retry", reason: "la page Teams ne répond pas (rechargez-la)" });
      }
    }, SEND_START_MS);
    // elle l'a prise mais ne dit rien : peut-être parti, on ne réessaie pas
    setTimeout(function () {
      if (sending.get(n) === entry) {
        sending.delete(n);
        reply({ result: "uncertain", reason: "Teams n'a pas répondu à temps" });
      }
    }, SEND_TIMEOUT_MS);
  }

  chrome.runtime.onMessage.addListener(function (msg, _sender, reply) {
    if (!msg) return false;
    if (msg.kind === "diagnose" || msg.kind === "where") {
      ask(msg.kind, reply);
      return true;
    }
    if (msg.kind === "drafts") {
      toPage("drafts", { items: drafts(msg.items) });
      reply({ ok: true });
      return false;
    }
    if (msg.kind === "resendTitles") {
      toPage("resendTitles");
      reply({ ok: true });
      return false;
    }
    if (msg.kind === "send") {
      const item = draft(msg.item);
      if (!item) {
        reply({ result: "retry", reason: "demande illisible" });
        return false;
      }
      item.selfName = str(msg.item.selfName, 120);
      sendThroughPage(item, reply);
      return true;
    }
    return false;
  });

  // une page qui s'ouvre demande tout de suite les brouillons qui l'attendent
  send({ kind: "pendingDrafts" }).then(function (answer) {
    if (answer) toPage("drafts", { items: drafts(answer.items) });
  });
})();
