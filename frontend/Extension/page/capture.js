/*
 * Dans la page Teams (monde « MAIN », chargé avant le client) : on regarde passer ce que le client reçoit déjà et
 * ce qu'il range dans sa base locale, et on en tire les messages. On ne fait aucune requête à Microsoft, on ne
 * clique sur rien, on n'écrit nulle part dans la page.
 *
 * Deux sources, dédoublonnées par l'identifiant du message :
 *   - le réseau : les réponses JSON (fetch, XHR) et les trames du WebSocket (l'arrivée d'un message en direct) ;
 *   - la base IndexedDB du client, relue à intervalles : elle rattrape ce que le réseau ne montre pas (une requête
 *     faite par un worker, un message arrivé avant l'ouverture de l'onglet).
 *
 * Tout passe au script isolé de l'extension par `window.postMessage` ; rien ne doit jamais casser la page : chaque
 * crochet est enveloppé, et une erreur ici n'est qu'un compteur du diagnostic.
 */
(function () {
  "use strict";
  if (window.__mikaTeamsCapture) return;
  window.__mikaTeamsCapture = true;

  const X = window.MikaTeamsExtract;
  if (!X) return;

  const TAG = "mika-teams";
  const URL_OF_INTEREST = /chatsvc|\/conversations|\/messages|msg\.teams|trouter|ic3|\/threads|\/chats?\b/i;
  const MAX_RESPONSE_BYTES = 6 * 1024 * 1024;
  const SWEEP_FIRST_MS = 8000;
  const SWEEP_EVERY_MS = 45000;
  const SWEEP_BUDGET_MS = 1500;
  const SWEEP_RECORDS_PER_STORE = 4000;
  const DB_OF_INTEREST = /replychain|conversation|message|chat/i;
  const SENT_IN_PAGE_MAX = 20000;

  const stats = {
    startedAt: Date.now(),
    network: { responses: 0, frames: 0, messages: 0, errors: 0 },
    idb: { available: typeof indexedDB !== "undefined" && typeof indexedDB.databases === "function",
      sweeps: 0, lastSweepMs: 0, messages: 0, errors: 0, databases: [] },
    conversations: 0,
    sent: 0,
  };

  // ── Ce qu'on a déjà fait passer (dans cette page) ─────────────────────────
  const sentIds = new Set();
  const titles = new Map();
  let pendingMessages = [];
  let pendingConversations = [];
  let flushTimer = 0;

  function selfId() {
    try {
      for (let i = 0; i < sessionStorage.length; i++) {
        const m = /^tmp\.session\.([0-9a-f-]{36})-/i.exec(sessionStorage.key(i) || "");
        if (m) return m[1].toLowerCase();
      }
    } catch (_) { /* stockage refusé */ }
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i) || "";
        if (!/account\.keys/i.test(key)) continue;
        const keys = JSON.parse(localStorage.getItem(key) || "[]");
        const m = /^([0-9a-f-]{36})\./i.exec(Array.isArray(keys) ? String(keys[0] || "") : "");
        if (m) return m[1].toLowerCase();
      }
    } catch (_) { /* format inattendu */ }
    return "";
  }

  function post(kind, payload) {
    try {
      window.postMessage(Object.assign({ __mika: TAG, dir: "out", kind: kind }, payload), location.origin);
    } catch (_) { /* rien */ }
  }

  function flush() {
    flushTimer = 0;
    if (!pendingMessages.length && !pendingConversations.length) return;
    const messages = pendingMessages.splice(0, 300);
    const conversations = pendingConversations.splice(0, 300);
    stats.sent += messages.length;
    post("captured", { messages: messages, conversations: conversations, self: selfId() });
    if (pendingMessages.length || pendingConversations.length) schedule();
  }

  function schedule() {
    if (!flushTimer) flushTimer = setTimeout(flush, 600);
  }

  function take(result, source) {
    for (const c of result.conversations) {
      const prev = titles.get(c.id);
      if (!prev || prev.title !== c.title || prev.threadType !== c.threadType) {
        titles.set(c.id, c);
        pendingConversations.push(c);
        stats.conversations = titles.size;
      }
    }
    for (const m of result.messages) {
      if (sentIds.has(m.id)) continue;
      if (sentIds.size >= SENT_IN_PAGE_MAX) sentIds.clear();
      sentIds.add(m.id);
      m.source = source;
      pendingMessages.push(m);
      stats[source].messages++;
    }
    if (pendingMessages.length || pendingConversations.length) schedule();
  }

  function inspect(value, source, conversation) {
    try {
      take(X.extract(value, { parseStrings: true, conversation: conversation || "" }), source);
    } catch (_) {
      stats[source].errors++;
    }
  }

  // ── Le réseau ──────────────────────────────────────────────────────────────

  function interesting(url) {
    return URL_OF_INTEREST.test(String(url || ""));
  }

  const nativeFetch = window.fetch;
  if (typeof nativeFetch === "function") {
    window.fetch = function () {
      const promise = nativeFetch.apply(this, arguments);
      try {
        const input = arguments[0];
        const url = typeof input === "string" ? input : (input && input.url) || "";
        if (interesting(url)) {
          promise.then(function (response) {
            try {
              const type = response.headers.get("content-type") || "";
              const size = Number(response.headers.get("content-length") || 0);
              if (!/json|text/i.test(type) || size > MAX_RESPONSE_BYTES) return;
              response.clone().text().then(function (body) {
                stats.network.responses++;
                inspect(body, "network", X.conversationFromUrl(url));
              }, function () { stats.network.errors++; });
            } catch (_) {
              stats.network.errors++;
            }
          }, function () { /* l'échec appartient à la page */ });
        }
      } catch (_) {
        stats.network.errors++;
      }
      return promise;
    };
  }

  const xhrUrls = new WeakMap();
  const nativeOpen = XMLHttpRequest.prototype.open;
  const nativeSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    try { xhrUrls.set(this, String(url || "")); } catch (_) { /* rien */ }
    return nativeOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    try {
      const url = xhrUrls.get(this) || "";
      if (interesting(url)) {
        this.addEventListener("load", function () {
          try {
            const kind = this.responseType;
            let body;
            if (kind === "" || kind === "text") body = this.responseText;
            else if (kind === "json") body = this.response;
            else return;
            if (typeof body === "string" && body.length > MAX_RESPONSE_BYTES) return;
            stats.network.responses++;
            inspect(body, "network", X.conversationFromUrl(url));
          } catch (_) {
            stats.network.errors++;
          }
        });
      }
    } catch (_) {
      stats.network.errors++;
    }
    return nativeSend.apply(this, arguments);
  };

  const NativeWebSocket = window.WebSocket;
  if (typeof NativeWebSocket === "function" && typeof Proxy === "function") {
    window.WebSocket = new Proxy(NativeWebSocket, {
      construct: function (target, args, newTarget) {
        const socket = Reflect.construct(target, args, newTarget);
        try {
          socket.addEventListener("message", function (event) {
            const data = event.data;
            if (typeof data !== "string" || data.length > MAX_RESPONSE_BYTES || data.indexOf("{") < 0) return;
            stats.network.frames++;
            inspect(data, "network", "");
          });
        } catch (_) {
          stats.network.errors++;
        }
        return socket;
      },
    });
  }

  // ── La base locale du client ────────────────────────────────────────────────

  function openExisting(name) {
    return new Promise(function (resolve) {
      let request;
      try {
        request = indexedDB.open(name);
      } catch (_) {
        resolve(null);
        return;
      }
      // une base qui n'existe plus ne doit jamais être créée par nous
      request.onupgradeneeded = function () {
        try { request.transaction.abort(); } catch (_) { /* rien */ }
      };
      request.onsuccess = function () {
        const db = request.result;
        db.onversionchange = function () { db.close(); };
        resolve(db);
      };
      request.onerror = function () { resolve(null); };
      request.onblocked = function () { resolve(null); };
    });
  }

  function readStore(db, storeName, deadline, report) {
    return new Promise(function (resolve) {
      let tx;
      try {
        tx = db.transaction(storeName, "readonly");
      } catch (_) {
        resolve();
        return;
      }
      let n = 0;
      let request;
      try {
        request = tx.objectStore(storeName).openCursor();
      } catch (_) {
        resolve();
        return;
      }
      request.onsuccess = function () {
        const cursor = request.result;
        if (!cursor || n >= SWEEP_RECORDS_PER_STORE || Date.now() > deadline) {
          report.records += n;
          resolve();
          return;
        }
        n++;
        try {
          const before = stats.idb.messages;
          take(X.extract(cursor.value, { parseStrings: false }), "idb");
          report.messages += stats.idb.messages - before;
        } catch (_) {
          stats.idb.errors++;
        }
        cursor.continue();
      };
      request.onerror = function () { resolve(); };
      tx.onabort = function () { resolve(); };
    });
  }

  let sweeping = false;
  async function sweep() {
    if (sweeping || !stats.idb.available) return;
    sweeping = true;
    const started = Date.now();
    const deadline = started + SWEEP_BUDGET_MS;
    const reports = [];
    try {
      const list = await indexedDB.databases();
      for (const info of list) {
        if (!info || !info.name || !DB_OF_INTEREST.test(info.name)) continue;
        const report = { name: info.name, stores: [], records: 0, messages: 0 };
        reports.push(report);
        if (Date.now() > deadline) continue;
        const db = await openExisting(info.name);
        if (!db) continue;
        try {
          for (const storeName of Array.from(db.objectStoreNames)) {
            report.stores.push(storeName);
            if (Date.now() > deadline) break;
            await readStore(db, storeName, deadline, report);
          }
        } finally {
          db.close();
        }
      }
    } catch (_) {
      stats.idb.errors++;
    } finally {
      stats.idb.sweeps++;
      stats.idb.lastSweepMs = Date.now() - started;
      stats.idb.databases = reports;
      sweeping = false;
    }
  }

  setTimeout(function loop() {
    sweep().finally(function () { setTimeout(loop, SWEEP_EVERY_MS); });
  }, SWEEP_FIRST_MS);

  // ── Le diagnostic demandé par l'extension ──────────────────────────────────

  window.addEventListener("message", function (event) {
    const data = event.data;
    if (event.source !== window || !data || data.__mika !== TAG || data.dir !== "in") return;
    if (data.kind === "diagnose") {
      const report = JSON.parse(JSON.stringify(stats));
      report.url = location.origin + location.pathname;
      report.selfFound = Boolean(selfId());
      report.conversationTitles = Array.from(titles.values()).filter(function (c) { return c.title; }).length;
      post("report", { nonce: data.nonce, report: report });
    }
  });
})();
