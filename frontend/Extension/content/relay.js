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
  // Chrome n'injecte un même fichier qu'une fois par cadre, quel que soit le monde : `lib/text.js`, chargé d'abord
  // dans la page (monde MAIN), ne l'est jamais ici — `MikaTeamsText` n'existe pas dans ce monde, et chaque lot capté
  // tombait sur `T.cut` sans rien dire. Le relais a donc sa coupe à lui, la même que `MikaTeamsText.cut` (au plus
  // `max` unités, bien formée, jamais au milieu d'une paire) : `tests/relay.test.js` les confronte.
  const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

  function wellFormed(s) {
    const t = typeof s === "string" ? s : s === undefined || s === null ? "" : String(s);
    return typeof t.toWellFormed === "function" ? t.toWellFormed() : t.replace(LONE_SURROGATE, "�");
  }

  function cut(s, max) {
    const t = wellFormed(s);
    if (!(max >= 0) || t.length <= max) return t;
    let end = Math.floor(max);
    const c = t.charCodeAt(end - 1);
    if (c >= 0xd800 && c <= 0xdbff) end--;
    return t.slice(0, end);
  }

  const T = { cut: cut };
  const TAG = "mika-teams";
  const MAX_ITEMS = 300;
  const MAX_CURSORS = 5000;
  const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  const IMAGE_B64_MAX = Math.ceil((8 * 1024 * 1024 * 4) / 3) + 8;
  const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;
  const IMAGE_ID = /^[A-Za-z0-9._:-]{1,200}$/;
  const SOURCES = ["network", "idb", "worker"];
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
      time: time, type: str(m.type, 60), text: text, source: SOURCES.indexOf(m.source) >= 0 ? m.source : "network",
      mentions: Array.isArray(m.mentions) ? m.mentions.slice(0, 20).map(function (x) { return str(x, 200); }) : [],
    };
    if (deleted) out.deleted = true;
    // ses images : leur nombre seulement (la page les télécharge et les envoie à part, ADR 0258)
    const images = Array.isArray(m.images) ? m.images.length : Number(m.images) || 0;
    if (images > 0 && !deleted) out.images = Math.min(8, Math.floor(images));
    return out;
  }

  /** Un profil de personne (ADR 0298) : un identifiant de Teams reconnu, des champs bornés, un e-mail bien formé. */
  const PROFILE_ID = /^(8:orgid:[0-9a-f-]{36}|8:live:[a-z0-9._-]{1,80}|8:teamsvisitor:[0-9a-f-]{32,36})$/;
  const PROFILE_EMAIL = /^[^\s@<>"',;]{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,}$/;
  function profile(p) {
    if (!p || typeof p !== "object" || !PROFILE_ID.test(String(p.id || ""))) return null;
    const email = str(p.email, 254);
    return { id: p.id, name: str(p.name, 120), email: PROFILE_EMAIL.test(email) ? email : "", title: str(p.title, 120),
      company: str(p.company, 120), department: str(p.department, 120), tenant: str(p.tenant, 120),
      phones: list(p.phones, 3, function (n) { return str(n, 40) || null; }) };
  }

  /** Un curseur de synchro (ADR 0251) : une conversation, le plus tard livré qu'on y ait lu (ms), la fiche vue. */
  function cursor(c) {
    if (!c || typeof c !== "object" || !str(c.conv, 300)) return null;
    const w = Number(c.w);
    return isFinite(w) && w >= 0 ? { conv: str(c.conv, 300), w: Math.floor(w), m: str(c.m, 200) } : null;
  }

  function list(v, max, fn) {
    return (Array.isArray(v) ? v.slice(0, max) : []).map(fn).filter(Boolean);
  }

  function count(v) {
    const n = Number(v);
    return isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  }

  /**
   * Ce que la page peut demander au service, et la forme qu'on laisse passer : ses curseurs ; un paquet de
   * l'historique (attendu avant le suivant) ; où en est l'historique ; sa fin.
   */
  const ASKS = {
    cursors: function () { return {}; },
    historyChunk: function (p) {
      return { run: str(p.run, 40), messages: list(p.messages, MAX_ITEMS, message),
        conversations: list(p.conversations, MAX_ITEMS, conversation), self: str(p.self, 64),
        profiles: list(p.profiles, MAX_ITEMS, profile) };
    },
    image: function (p) {
      // une image d'un message (ADR 0258) : rien ne passe qui n'en ait la forme
      const type = IMAGE_TYPES.indexOf(p.type) >= 0 ? p.type : "";
      const data = typeof p.data === "string" && p.data.length <= IMAGE_B64_MAX && BASE64.test(p.data) ? p.data : "";
      const position = Math.min(7, count(p.position));
      return { conv: str(p.conv, 300), id: str(p.id, 200), image: IMAGE_ID.test(String(p.image || "")) ? p.image : "",
        position: position, type: type, data: data, time: Number(p.time) || 0, author: str(p.author, 120),
        authorId: str(p.authorId, 200), history: p.history === true };
    },
    historyProgress: function (p) {
      return { run: str(p.run, 40), done: count(p.done), total: count(p.total), messages: count(p.messages) };
    },
    historyDone: function (p) {
      return { run: str(p.run, 40), done: count(p.done), total: count(p.total), messages: count(p.messages),
        error: str(p.error, 200) };
    },
  };

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

  // les lots captés partent l'un après l'autre ; un lot perdu retient les curseurs des suivants
  let capturedChain = Promise.resolve();
  let lostSinceCursors = false;

  /** Ce que le relais a passé au service, et ce que le service en a dit : le diagnostic de l'onglet le montre. */
  const relayed = { batches: 0, messages: 0, accepted: 0, lost: 0, lastError: "", lastErrorAt: 0 };

  function noteError(e) {
    relayed.lastError = T.cut(String(e && e.message ? e.message : e || "sans réponse"), 200);
    relayed.lastErrorAt = Date.now();
  }

  function send(payload) {
    try {
      return chrome.runtime.sendMessage(payload).catch(function (e) {
        noteError(e); // extension rechargée ou endormie
        return null;
      });
    } catch (e) {
      // contexte invalidé : l'extension a été rechargée après l'ouverture de l'onglet, qu'il faut recharger
      noteError(e);
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
      const cursors = list(data.cursors, MAX_ITEMS, cursor);
      const profiles = list(data.profiles, MAX_ITEMS, profile);
      if (messages.length || conversations.length || cursors.length || profiles.length) {
        relayed.batches++;
        relayed.messages += messages.length;
        const self = str(data.self, 64);
        // un lot après l'autre : un curseur dit « tout ce qui précède est passé » ; un lot perdu, les curseurs qui
        // suivent ne partent pas, et la page reprend les siens chez le service (ADR 0251)
        capturedChain = capturedChain.then(function () {
          const withCursors = lostSinceCursors ? [] : cursors;
          return send({ kind: "captured", messages: messages, conversations: conversations, self: self,
            cursors: withCursors, profiles: profiles }).then(function (answer) {
            if (answer && answer.ok === true) {
              relayed.accepted += messages.length;
              if (lostSinceCursors && cursors.length) {
                lostSinceCursors = false;
                toPage("cursorsLost");
              }
            } else {
              relayed.lost += messages.length;
              if (answer && answer.error) noteError(answer.error);
              lostSinceCursors = true;
              toPage("cursorsLost");
            }
          });
        });
      }
    } else if (data.kind === "report" && waiting.has(data.nonce)) {
      waiting.get(data.nonce)({ ok: true, report: data.report, relayed: Object.assign({}, relayed) });
      waiting.delete(data.nonce);
    } else if (data.kind === "claim" && str(data.nonce, 64) && str(data.id, 64)) {
      const id = str(data.id, 64);
      const n = str(data.nonce, 64);
      send({ kind: "claim", id: id }).then(function (answer) {
        toPage("answer", { nonce: n, ok: Boolean(answer && answer.ok === true) });
      });
    } else if (data.kind === "ask" && str(data.nonce, 64) && Object.prototype.hasOwnProperty.call(ASKS, data.what)) {
      const n = str(data.nonce, 64);
      const what = data.what;
      const payload = ASKS[what](data.payload && typeof data.payload === "object" ? data.payload : {});
      send(Object.assign({ kind: what }, payload)).then(function (answer) {
        const ok = Boolean(answer && answer.ok === true);
        let out = null;
        if (what === "image") {
          out = { skipped: Boolean(answer && answer.skipped), retry: Boolean(answer && answer.retry),
            error: str(answer && answer.error, 200) };
        } else if (what === "cursors" && ok && answer.cursors && typeof answer.cursors === "object") {
          out = {};
          for (const conv of Object.keys(answer.cursors).slice(0, MAX_CURSORS)) {
            const c = cursor(Object.assign({ conv: conv }, answer.cursors[conv]));
            if (c) out[c.conv] = { w: c.w, m: c.m };
          }
        } else if (!ok) {
          out = { error: str(answer && answer.error, 200) };
        }
        toPage("answer", { nonce: n, ok: ok, data: out });
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
    if (msg.kind === "history") {
      toPage("history", { run: str(msg.run, 40) });
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
