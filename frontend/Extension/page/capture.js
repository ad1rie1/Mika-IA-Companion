/*
 * Dans la page Teams (monde « MAIN », chargé avant le client) : on regarde passer ce que le client reçoit déjà et
 * ce qu'il range dans sa base locale, et on en tire les messages. Pour les lire, on ne fait aucune requête à
 * Microsoft et on ne touche à rien dans la page.
 *
 * Deux sources, dédoublonnées par version de message (son identifiant et un condensé de son texte : un message
 * modifié repasse, un message supprimé passe une fois comme suppression) :
 *   - le réseau : les réponses JSON (fetch, XHR) et les trames du WebSocket (l'arrivée d'un message en direct) ;
 *   - la base IndexedDB du client, relue à intervalles : elle rattrape ce que le réseau ne montre pas (une requête
 *     faite par un worker, un message arrivé avant l'ouverture de l'onglet).
 *
 * L'autre sens, ce que Mika écrit, ne passe que par deux gestes :
 *   - un brouillon se place dans la zone de saisie, et seulement quand la conversation ouverte est la sienne, que la
 *     zone est vide et qu'on n'est pas en train d'écrire ailleurs dans Teams ; c'est l'utilisateur qui l'envoie ;
 *   - un message à envoyer part par le service de chat du client, avec l'authentification que le client utilise
 *     lui-même (vue passer, gardée dans la mémoire de ce script seulement : jamais postée ni journalisée), sinon par
 *     la zone de saisie de la conversation ouverte. Un envoi commencé dans cette page ne l'est jamais deux fois, et
 *     son issue n'est dite « envoyé » ou « échec » que si elle est sûre ; sinon elle est « incertaine ».
 *
 * Tout passe au script isolé de l'extension par `window.postMessage` ; rien ne doit jamais casser la page : chaque
 * crochet est enveloppé, et une erreur ici n'est qu'un compteur du diagnostic.
 */
(function () {
  "use strict";
  if (window.__mikaTeamsCapture) return;
  window.__mikaTeamsCapture = true;

  const X = window.MikaTeamsExtract;
  const P = window.MikaTeamsPage;
  const T = window.MikaTeamsText;
  if (!X || !P || !T) return;

  const TAG = "mika-teams";
  const URL_OF_INTEREST = /chatsvc|\/conversations|\/messages|msg\.teams|trouter|ic3|\/threads|\/chats?\b/i;
  const MAX_RESPONSE_BYTES = 6 * 1024 * 1024;
  const MAX_FRAME_CHARS = 2 * 1024 * 1024;
  const FRAMES_PENDING_MAX = 500;
  const SWEEP_FIRST_MS = 8000;
  const SWEEP_EVERY_MS = 45000;
  const SWEEP_BUDGET_MS = 1500;
  const SWEEP_RECORDS_PER_STORE = 4000;
  const DB_OF_INTEREST = /replychain|conversation|message|chat/i;
  const SENT_IN_PAGE_MAX = 20000;
  const DRAFT_CHECK_MS = 2000;
  const DRAFT_TRIES = 3;
  const ASK_TIMEOUT_MS = 5000;
  const SENT_CHECK_MS = 250;
  const SENT_WAIT_MS = 3000;
  const CHAT_SEND_TIMEOUT_MS = 20000;
  const EDITORS = ['[data-tid="ckeditor"][contenteditable="true"]', '[data-tid*="ckeditor"][contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]'];
  const SEND_BUTTONS = ['[data-tid="newMessageCommands-send"]', 'button[name="send"]'];
  const TYPING_INPUTS = /^(text|search|email|url|tel|password|number|)$/i;

  const stats = {
    startedAt: Date.now(),
    network: { responses: 0, frames: 0, messages: 0, errors: 0 },
    idb: { available: typeof indexedDB !== "undefined" && typeof indexedDB.databases === "function",
      sweeps: 0, lastSweepMs: 0, messages: 0, errors: 0, databases: [] },
    conversations: 0,
    sent: 0,
    compose: { placed: 0, sentByService: 0, sentByComposeBox: 0, uncertain: 0, errors: 0 },
  };

  // ── Ce qu'on a déjà fait passer (dans cette page) ─────────────────────────
  const sentKeys = new Set(); // les versions de message déjà passées
  const latest = new Map(); // identifiant → dernière version vue
  const titles = new Map();
  let pendingMessages = [];
  let pendingConversations = [];
  let flushTimer = 0;

  function readSelf() {
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

  // trouvée une fois dans cette page, l'identité ne change plus (une autre clé de session, plus tard, n'y fait rien)
  let knownSelf = "";
  function selfId() {
    if (!knownSelf) knownSelf = readSelf();
    return knownSelf;
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
      if (sentKeys.size >= SENT_IN_PAGE_MAX) {
        sentKeys.clear();
        latest.clear();
      }
      if (!T.freshVersion(m, sentKeys, latest)) continue;
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

  // ── L'authentification du service de chat (mémoire de ce script seulement) ──
  //
  // `chatAuth` : la base du service et les en-têtes d'authentification de la dernière requête du client vers
  // `…/v1/users/ME/conversations`, sur un hôte de Teams seulement. Ni posté, ni journalisé, ni montré : le diagnostic
  // ne dit que s'il existe.
  let chatAuth = null;

  function noteAuth(url, headers) {
    try {
      if (!P.isChatServiceUrl(url)) return;
      const found = P.authFromHeaders(headers);
      const base = found ? P.chatServiceBase(url, location.href) : "";
      if (found && base) chatAuth = { base: base, headers: found };
    } catch (_) {
      stats.network.errors++;
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
        const init = arguments[1];
        const url = typeof input === "string" ? input : (input && input.url) || String(input || "");
        if (P.isChatServiceUrl(url)) {
          noteAuth(url, init && init.headers);
          if (input && typeof input === "object" && input.headers) noteAuth(url, input.headers);
        }
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
  const xhrAuth = new WeakMap();
  const nativeOpen = XMLHttpRequest.prototype.open;
  const nativeSend = XMLHttpRequest.prototype.send;
  const nativeSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (method, url) {
    try {
      xhrUrls.set(this, String(url || ""));
      xhrAuth.delete(this);
    } catch (_) { /* rien */ }
    return nativeOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    try {
      // seuls les en-têtes d'authentification sont retenus, et seulement le temps de la requête
      if (P.isAuthHeader(name)) {
        const held = xhrAuth.get(this) || {};
        held[String(name)] = String(value);
        xhrAuth.set(this, held);
      }
    } catch (_) { /* rien */ }
    return nativeSetHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    try {
      const url = xhrUrls.get(this) || "";
      if (P.isChatServiceUrl(url)) noteAuth(url, xhrAuth.get(this));
      xhrAuth.delete(this);
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

  // Les trames sont lues hors de l'événement, après les gestionnaires de Teams : la lecture ne retarde jamais la page.
  let frames = [];
  let framesTimer = 0;
  function readFrames() {
    framesTimer = 0;
    const batch = frames;
    frames = [];
    for (const data of batch) {
      stats.network.frames++;
      inspect(data, "network", "");
    }
  }

  const NativeWebSocket = window.WebSocket;
  if (typeof NativeWebSocket === "function" && typeof Proxy === "function") {
    const HookedWebSocket = new Proxy(NativeWebSocket, {
      construct: function (target, args, newTarget) {
        const socket = Reflect.construct(target, args, newTarget);
        try {
          socket.addEventListener("message", function (event) {
            const data = event.data;
            if (typeof data !== "string" || data.length > MAX_FRAME_CHARS || data.indexOf("{") < 0) return;
            if (frames.length >= FRAMES_PENDING_MAX) return;
            frames.push(data);
            if (!framesTimer) framesTimer = setTimeout(readFrames, 0);
          });
        } catch (_) {
          stats.network.errors++;
        }
        return socket;
      },
    });
    window.WebSocket = HookedWebSocket;
    // `socket.constructor === WebSocket` doit rester vrai pour le client : le prototype désigne le nouveau constructeur
    try {
      const proto = NativeWebSocket.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "constructor");
      if (desc && desc.writable) proto.constructor = HookedWebSocket;
      else if (!desc || desc.configurable) {
        Object.defineProperty(proto, "constructor",
          { value: HookedWebSocket, writable: true, enumerable: false, configurable: true });
      }
    } catch (_) { /* tant pis : seule cette égalité-là en pâtit */ }
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

  // ── La conversation ouverte et la zone de saisie ────────────────────────────

  /** La conversation ouverte : l'historique de navigation de Teams, sinon l'adresse de la page. */
  function activeConversation() {
    const pairs = [];
    try {
      for (let i = 0; i < sessionStorage.length; i++) {
        const key = sessionStorage.key(i) || "";
        if (P.NAV_KEY.test(key)) pairs.push([key, sessionStorage.getItem(key)]);
      }
    } catch (_) { /* stockage refusé */ }
    return P.activeConversationFromStorage(pairs) || P.conversationFromLocation(location.href);
  }

  function visible(el) {
    return Boolean(el && el.isConnected && el.getClientRects().length);
  }

  function findEditor() {
    for (const selector of EDITORS) {
      for (const el of document.querySelectorAll(selector)) {
        if (visible(el)) return el;
      }
    }
    return null;
  }

  function isEmpty(editor) {
    return String(editor.innerText || "").trim() === "";
  }

  /** On écrit ailleurs dans Teams (la recherche, une autre zone) : ce n'est pas le moment de prendre le focus. */
  function typingElsewhere(editor) {
    const active = document.activeElement;
    if (!active || active === document.body || active === editor || editor.contains(active)) return false;
    if (active.isContentEditable || active.tagName === "TEXTAREA") return true;
    return active.tagName === "INPUT" && TYPING_INPUTS.test(active.getAttribute("type") || "");
  }

  /**
   * Le texte dans la zone de saisie, comme si on le tapait : `insertText` ligne à ligne, un saut de ligne simple
   * (Maj+Entrée) entre deux lignes — jamais un paragraphe, qu'un éditeur de Teams peut prendre pour « Envoyer ».
   * Les Trusted Types de la page interdisent `innerHTML` : rien ici n'en passe par là.
   */
  function insertText(editor, text) {
    editor.focus();
    const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    lines.forEach(function (line, i) {
      if (i > 0 && !document.execCommand("insertLineBreak")) document.execCommand("insertText", false, "\n");
      if (line) document.execCommand("insertText", false, line);
    });
    return !isEmpty(editor);
  }

  function clickSend(editor) {
    for (const selector of SEND_BUTTONS) {
      const button = document.querySelector(selector);
      if (visible(button) && !button.disabled && button.getAttribute("aria-disabled") !== "true") {
        button.click();
        return;
      }
    }
    editor.dispatchEvent(new KeyboardEvent("keydown",
      { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));
  }

  function pause(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // ── Demandes au service d'arrière-plan (par le relais) ─────────────────────

  const answers = new Map();
  function askExtension(kind, payload) {
    return new Promise(function (resolve) {
      const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
      answers.set(nonce, resolve);
      post(kind, Object.assign({ nonce: nonce }, payload));
      setTimeout(function () {
        if (answers.has(nonce)) {
          answers.delete(nonce);
          resolve(null);
        }
      }, ASK_TIMEOUT_MS);
    });
  }

  // ── Les brouillons de Mika ──────────────────────────────────────────────────
  //
  // Le service d'arrière-plan pousse la liste des brouillons à placer ; tant qu'elle n'est pas vide, on regarde toutes
  // les 2 s si la conversation ouverte en a un. Avant d'écrire, on demande le droit de le faire (un seul onglet, une
  // seule fois, conversation pas exclue) ; ce qui s'est passé est rendu au service, qui le dit à Mika.

  let drafts = [];
  let draftTimer = 0;
  let placing = false;
  const tries = new Map();

  function setDrafts(list) {
    drafts = list.filter(function (d) { return (tries.get(d.id) || 0) < DRAFT_TRIES; });
    if (drafts.length && !draftTimer) draftTimer = setInterval(watchDrafts, DRAFT_CHECK_MS);
    else if (!drafts.length && draftTimer) {
      clearInterval(draftTimer);
      draftTimer = 0;
    }
  }

  function ready(draft) {
    const editor = findEditor();
    if (!editor || !isEmpty(editor) || typingElsewhere(editor)) return null;
    return P.sameConversation(activeConversation(), draft.conversation) ? editor : null;
  }

  function watchDrafts() {
    if (placing || !drafts.length || document.visibilityState !== "visible") return;
    let draft;
    try {
      const conv = activeConversation();
      draft = conv ? drafts.find(function (d) { return P.sameConversation(d.conversation, conv); }) : null;
      if (!draft || !ready(draft)) return;
    } catch (_) {
      stats.compose.errors++;
      return;
    }
    placing = true;
    askExtension("claim", { id: draft.id }).then(function (answer) {
      drafts = drafts.filter(function (d) { return d.id !== draft.id; });
      if (!answer || !answer.ok) return; // déjà placé ailleurs, ou plus à placer : le service renverra la liste
      tries.set(draft.id, (tries.get(draft.id) || 0) + 1);
      let ok = false;
      let reason = "la conversation ou la zone de saisie a changé";
      try {
        const editor = ready(draft);
        if (editor) {
          ok = insertText(editor, draft.text);
          reason = ok ? "" : "l'éditeur de Teams a refusé le texte";
        }
      } catch (_) {
        stats.compose.errors++;
        reason = "erreur pendant l'insertion";
      }
      if (ok) stats.compose.placed++;
      post("placed", { id: draft.id, ok: ok, reason: reason });
    }).finally(function () {
      placing = false;
      setDrafts(drafts);
    });
  }

  // ── Les messages que Mika envoie ───────────────────────────────────────────
  //
  // Une issue n'est « envoyé » ou « échec » que si elle est sûre. `retry` dit que rien n'est parti (on peut
  // réessayer) ; `uncertain`, que l'envoi a commencé sans réponse qui tranche : ni redit, ni retenté.

  const startedSends = new Set(); // les éléments dont l'envoi a commencé dans cette page : jamais une seconde fois
  const sendingNow = new Set();

  function uncertain(reason) {
    stats.compose.uncertain++;
    return { result: "uncertain", reason: reason };
  }

  async function sendViaChatService(item) {
    const auth = chatAuth;
    const url = auth.base + "/v1/users/ME/conversations/" + encodeURIComponent(item.conversation) + "/messages";
    const headers = Object.assign({ "content-type": "application/json" }, auth.headers);
    // le même identifiant client à chaque tentative, d'où qu'elle vienne
    const body = P.messageBody(item.text, item.selfName, P.clientMessageIdFor(item.id));
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimeout(function () { controller.abort(); }, CHAT_SEND_TIMEOUT_MS) : 0;
    try {
      let response;
      startedSends.add(item.id);
      try {
        // le `fetch` d'origine : notre propre requête n'a rien à faire dans la capture
        response = await nativeFetch.call(window, url, { method: "POST", headers: headers, body: JSON.stringify(body),
          signal: controller ? controller.signal : undefined });
      } catch (_) {
        return uncertain("le service de chat n'a pas répondu (coupure ou plus de 20 s)");
      }
      const verdict = P.chatSendOutcome(response.status);
      if (verdict === "auth") {
        // refusé avant d'être pris : rien n'est parti, la zone de saisie peut prendre le relais
        if (chatAuth === auth) chatAuth = null; // périmée : la prochaine requête du client en montrera une neuve
        startedSends.delete(item.id);
        return { result: "retry", reason: "le service de chat refuse l'authentification vue", authLost: true };
      }
      if (verdict === "failed") {
        return { result: "failed", reason: "le service de chat a refusé le message (" + response.status + ")" };
      }
      if (verdict === "uncertain") return uncertain("le service de chat a répondu " + response.status);
      let json = null;
      try {
        json = await response.json();
      } catch (_) { /* corps vide, ou coupé : le message est parti quand même */ }
      stats.compose.sentByService++;
      return { result: "sent", via: "service", message_id: P.messageIdFrom(json, response.headers.get("location")) };
    } finally {
      clearTimeout(timer);
    }
  }

  async function sendViaComposeBox(item) {
    if (!P.sameConversation(activeConversation(), item.conversation)) {
      return { result: "retry", reason: "conversation pas ouverte dans Teams" };
    }
    const editor = findEditor();
    if (!editor) return { result: "retry", reason: "zone de saisie introuvable" };
    if (!isEmpty(editor)) return { result: "retry", reason: "zone de saisie occupée" };
    if (typingElsewhere(editor)) return { result: "retry", reason: "saisie en cours ailleurs dans Teams" };
    startedSends.add(item.id);
    if (!insertText(editor, item.text)) {
      // la zone est restée vide : rien n'est parti
      startedSends.delete(item.id);
      return { result: "retry", reason: "l'éditeur de Teams a refusé le texte" };
    }
    clickSend(editor);
    for (let waited = 0; waited < SENT_WAIT_MS; waited += SENT_CHECK_MS) {
      await pause(SENT_CHECK_MS);
      if (isEmpty(editor)) {
        stats.compose.sentByComposeBox++;
        return { result: "sent", via: "zone de saisie" };
      }
    }
    return uncertain("texte dans la zone de saisie, mais Teams ne l'a pas envoyé à temps : à vérifier dans Teams");
  }

  async function sendItem(item) {
    if (startedSends.has(item.id) || sendingNow.has(item.id)) {
      return uncertain("envoi déjà commencé dans cet onglet");
    }
    sendingNow.add(item.id);
    try {
      if (chatAuth) {
        const viaService = await sendViaChatService(item);
        // seul un refus d'authentification laisse prendre l'autre chemin : rien n'est parti
        if (!viaService.authLost) return viaService;
      }
      return await sendViaComposeBox(item);
    } catch (_) {
      stats.compose.errors++;
      // une erreur après le début de l'envoi laisse l'issue douteuse
      return startedSends.has(item.id) ? uncertain("erreur dans la page Teams pendant l'envoi")
        : { result: "retry", reason: "erreur dans la page Teams" };
    } finally {
      sendingNow.delete(item.id);
    }
  }

  // ── Ce que demande l'extension ──────────────────────────────────────────────

  window.addEventListener("message", function (event) {
    const data = event.data;
    if (event.source !== window || !data || data.__mika !== TAG || data.dir !== "in") return;
    if (data.kind === "diagnose") {
      const report = JSON.parse(JSON.stringify(stats));
      report.url = location.origin + location.pathname;
      report.selfFound = Boolean(selfId());
      report.conversationTitles = Array.from(titles.values()).filter(function (c) { return c.title; }).length;
      let editor = null;
      try { editor = findEditor(); } catch (_) { /* rien */ }
      report.compose.editorFound = Boolean(editor);
      report.compose.activeConversationKnown = Boolean(activeConversation());
      report.compose.chatSendPossible = Boolean(chatAuth); // l'existence de l'en-tête, jamais sa valeur
      report.compose.drafts = drafts.length;
      post("report", { nonce: data.nonce, report: report });
    } else if (data.kind === "where") {
      post("report", { nonce: data.nonce, report: { conversation: activeConversation() } });
    } else if (data.kind === "drafts") {
      setDrafts((Array.isArray(data.items) ? data.items : []).filter(function (d) {
        return d && typeof d.id === "string" && typeof d.conversation === "string" && typeof d.text === "string";
      }));
    } else if (data.kind === "resendTitles") {
      // la pause est levée : les noms appris pendant qu'elle durait n'avaient pas été gardés, on les redit
      for (const c of titles.values()) pendingConversations.push(c);
      if (pendingConversations.length) schedule();
    } else if (data.kind === "answer" && answers.has(data.nonce)) {
      const resolve = answers.get(data.nonce);
      answers.delete(data.nonce);
      resolve({ ok: data.ok === true });
    } else if (data.kind === "send" && data.item && typeof data.item.text === "string"
      && typeof data.item.id === "string") {
      // arrivée après que le relais a cessé de l'attendre : il a déjà dit « rien n'est parti », on ne commence pas
      if (!(Date.now() <= Number(data.deadline))) {
        post("sendResult", { nonce: data.nonce, result: { result: "retry", reason: "demande arrivée trop tard" } });
        return;
      }
      post("sendStarted", { nonce: data.nonce });
      sendItem(data.item).then(function (result) {
        post("sendResult", { nonce: data.nonce, result: result });
      });
    }
  });
})();
