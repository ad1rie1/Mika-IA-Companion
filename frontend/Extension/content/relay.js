/*
 * Le relais (monde isolé de l'extension) : ce que le script de la page a capté part au service d'arrière-plan ;
 * une demande de diagnostic fait le chemin inverse. La page peut tout poster sur `window` : on ne relaie que des
 * formes connues, bornées.
 */
(function () {
  "use strict";
  const TAG = "mika-teams";
  const MAX_ITEMS = 300;
  const waiting = new Map();

  function str(v, max) {
    return typeof v === "string" ? v.slice(0, max) : typeof v === "number" ? String(v).slice(0, max) : "";
  }

  function message(m) {
    if (!m || typeof m !== "object") return null;
    const time = Number(m.time);
    if (!isFinite(time) || !str(m.id, 200) || !str(m.text, 4000)) return null;
    return {
      id: str(m.id, 200), conv: str(m.conv, 300), author: str(m.author, 120), authorId: str(m.authorId, 200),
      time: time, type: str(m.type, 60), text: str(m.text, 4000), source: m.source === "idb" ? "idb" : "network",
      mentions: Array.isArray(m.mentions) ? m.mentions.slice(0, 20).map(function (x) { return str(x, 200); }) : [],
    };
  }

  function conversation(c) {
    if (!c || typeof c !== "object" || !str(c.id, 300)) return null;
    return { id: str(c.id, 300), title: str(c.title, 120), threadType: str(c.threadType, 40) };
  }

  function send(payload) {
    try {
      chrome.runtime.sendMessage(payload).catch(function () { /* extension rechargée ou endormie */ });
    } catch (_) { /* contexte invalidé : l'extension a été rechargée, la page aussi le sera */ }
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
    }
  });

  chrome.runtime.onMessage.addListener(function (msg, _sender, reply) {
    if (!msg || msg.kind !== "diagnose") return false;
    const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
    waiting.set(nonce, reply);
    window.postMessage({ __mika: TAG, dir: "in", kind: "diagnose", nonce: nonce }, location.origin);
    setTimeout(function () {
      if (waiting.has(nonce)) {
        waiting.get(nonce)({ ok: false, error: "la page Teams ne répond pas (rechargez-la)" });
        waiting.delete(nonce);
      }
    }, 8000);
    return true;
  });
})();
