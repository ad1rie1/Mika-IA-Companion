/*
 * Dans la page Teams (monde « MAIN », chargé avant le client) : on regarde passer ce que le client reçoit déjà et
 * ce qu'il range dans sa base locale, et on en tire les messages. Pour les lire, on ne fait aucune requête à
 * Microsoft et on ne touche à rien dans la page.
 *
 * Trois sources (ADR 0251), dédoublonnées par version de message (son identifiant et un condensé de son texte : un
 * message modifié repasse, un message supprimé passe une fois comme suppression) :
 *   - le worker de Teams : ce qu'il passe à la page (le Teams d'aujourd'hui y fait vivre son service de chat, sa
 *     connexion en direct et sa base) — un message y passe dès qu'il arrive ;
 *   - la base IndexedDB du client, par synchro ciblée : les fiches de conversation relues à chaque signe (et toutes
 *     les 5 s), les fils d'une conversation qui a bougé relus depuis son curseur ; le bouton de l'historique la lit
 *     en entier ;
 *   - le réseau de la page : les réponses JSON (fetch, XHR) et les trames des WebSockets.
 *
 * L'autre sens, ce que Mika écrit, ne passe que par deux gestes :
 *   - un brouillon se place dans la zone de saisie, et seulement quand la conversation ouverte est la sienne, que la
 *     zone est vide et qu'on n'est pas en train d'écrire ailleurs dans Teams ; c'est l'utilisateur qui l'envoie ;
 *   - un message à envoyer part d'abord par le worker de Teams (ADR 0301), pour un tête-à-tête ou un groupe : la
 *     commande d'envoi que la page lui passe, rejouée depuis un modèle capté lors d'un vrai envoi, sans que la
 *     conversation soit ouverte ; sinon (ou sur un refus explicite) par le service de chat du client, avec
 *     l'authentification que le client utilise lui-même (vue passer, gardée dans la mémoire de ce script seulement :
 *     jamais postée ni journalisée) ; sinon par la zone de saisie de la conversation ouverte. Un envoi commencé dans
 *     cette page ne l'est jamais deux fois, et son issue n'est dite « envoyé » ou « échec » que si elle est sûre ;
 *     sinon elle est « incertaine ».
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
  // la synchro ciblée de la base locale (ADR 0251) : la première après l'ouverture, puis un contrôle des fiches de
  // conversation à cadence fixe, et plus tôt sur un signe (le worker de Teams parle, le titre change) ; un tour borné
  // en temps (le reste au tour suivant) ; une conversation inconnue relue sur la fenêtre, une connue depuis son curseur
  // moins un recouvrement ; une fiche en avance sur ses fils retentée quelques fois avant d'en prendre la marque
  const SYNC_FIRST_MS = 2500;
  const SYNC_EVERY_MS = 5000;
  const SYNC_NUDGE_MS = 700;
  const SYNC_BUDGET_MS = 1500;
  const SYNC_WINDOW_MS = 24 * 3600 * 1000;
  const SYNC_OVERLAP_MS = 60 * 1000;
  const CATCHUP_SLACK_MS = 5000;
  const CATCHUP_MS = 45000; // une fiche en avance sur ses fils : retentée tant de temps, puis sa marque est prise
  const CONVERSATIONS_DB = /conversation-manager/i;
  const CHAINS_DB = /replychain-manager/i;
  const NOT_CHAINS_DB = /metadata|streams|folder/i;
  const CHAIN_STORES = ["replychains", "replychains-2"];
  const CHAIN_INDEX = "latestDeliveryTimeByConversationId";
  // l'historique (le bouton de la mise en service) : par paquets, chacun attendu par le service avant le suivant
  const HISTORY_CHUNK = 150;
  const HISTORY_ASK_MS = 180000; // au-dessus du temps que le service se donne pour un paquet (120 s)
  const HISTORY_PAGE = 200; // les fils lus par pages, une transaction chacune : Teams écrit entre deux
  const HISTORY_KEEP = 1000; // Mika n'en garde pas plus par conversation : inutile d'envoyer les plus vieux
  // le worker de Teams (où vivent son service de chat et sa connexion en direct) : ce qu'il passe à la page
  const MAX_WORKER_CHARS = 2 * 1024 * 1024;
  const WORKER_PENDING_MAX = 200;
  // l'envoi par le worker de Teams (ADR 0301) : les commandes que la page lui passe (lues sans les changer), le modèle
  // d'envoi gardé par le service, la réponse attendue à notre commande ; sans elle, l'issue est douteuse
  const WORKER_COMMAND_MAX_CHARS = 1024 * 1024;
  const WORKER_SEND_TIMEOUT_MS = 10000;
  const TEMPLATE_ASK_MS = 3000;
  const WORKER_LATE_MAX = 50;
  const WORKER_REFUSED_MAX = 1000;
  // les images (ADR 0258) : téléchargées une à une du service d'images de Teams (avec les cookies du navigateur, comme
  // Teams lui-même), 8 Mo au plus, de ces types ; une image dont le message n'est pas encore chez Mika est retentée
  const IMAGE_HOST = /^https:\/\/[a-z0-9-]{1,40}\.asm\.skype\.com\/v1\/objects\/[A-Za-z0-9._:-]{1,200}\/views\/imgo$/;
  const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  const IMAGE_MAX_BYTES = 8 * 1024 * 1024;
  const IMAGE_QUEUE_MAX = 500;
  const IMAGE_RETRY_MS = 30000;
  const IMAGE_TRIES = 3;
  const IMAGE_ASK_MS = 120000;
  const WORKER_PER_TASK = 5;
  // les photos de profil (ADR 0300) : téléchargées par l'adresse que Teams donne à ses avatars (`P.photoUrl`), 64 px,
  // 64 Ko au plus, de ces types
  const PHOTO_TYPES = ["image/png", "image/jpeg", "image/webp"];
  const PHOTO_MAX_BYTES = 64 * 1024;
  const PHOTO_QUEUE_MAX = 200;
  const PHOTO_ASK_MS = 30000;
  const FLUSH_MS = 300;
  // les profils des personnes (ADR 0298) : la base que Teams garde dans ce navigateur, relue au plus toutes les 10 min
  const PROFILES_DB = /^Teams:profiles:/;
  const PROFILES_TTL_MS = 10 * 60 * 1000;
  const PROFILES_MAX = 20000;
  const SENT_IN_PAGE_MAX = 20000;
  const DRAFT_CHECK_MS = 2000;
  const DRAFT_TRIES = 3;
  const ASK_TIMEOUT_MS = 5000;
  const SENT_CHECK_MS = 250;
  const SENT_WAIT_MS = 3000;
  const CHAT_SEND_TIMEOUT_MS = 20000;
  const EDITORS = ['[data-tid="ckeditor"][contenteditable="true"]', '[data-tid*="ckeditor"][contenteditable="true"]',
    'div[role="textbox"][contenteditable="true"]'];
  const SEND_BUTTONS = ['[data-tid="sendMessageCommands-send"]', '[data-tid="newMessageCommands-send"]',
    'button[name="send"]'];
  const TYPING_INPUTS = /^(text|search|email|url|tel|password|number|)$/i;

  const stats = {
    startedAt: Date.now(),
    network: { responses: 0, frames: 0, messages: 0, errors: 0 },
    idb: { available: typeof indexedDB !== "undefined" && typeof indexedDB.databases === "function",
      syncs: 0, lastSyncMs: 0, conversations: 0, read: 0, messages: 0, errors: 0 },
    worker: { hooked: 0, received: 0, kept: 0, messages: 0, errors: 0, commands: 0, templates: 0, templateRefused: 0,
      templateIssue: "" },
    history: { running: false, done: 0, total: 0, messages: 0, images: 0, error: "" },
    images: { downloaded: 0, sent: 0, skipped: 0, failed: 0 },
    photos: { asked: 0, downloaded: 0, sent: 0, skipped: 0, failed: 0, noAvatarSeen: 0 },
    conversations: 0,
    profiles: 0,
    sent: 0,
    compose: { placed: 0, sentByWorker: 0, sentByService: 0, sentByComposeBox: 0, uncertain: 0, errors: 0,
      workerRefused: 0, workerSilent: 0, workerLate: 0 },
  };

  // ── Ce qu'on a déjà fait passer (dans cette page) ─────────────────────────
  const sentKeys = new Set(); // les versions de message déjà passées
  const latest = new Map(); // identifiant → dernière version vue
  const titles = new Map();
  let pendingMessages = [];
  let pendingConversations = [];
  const pendingCursors = new Map(); // conversation → curseur à garder par le service (avec le dernier lot)
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

  // ── Les profils (ADR 0298) ─────────────────────────────────────────────────
  //
  // Teams garde le profil des personnes croisées (nom, e-mail, poste, entreprise, service, numéros). On le lit dans
  // cette page et on joint, à chaque lot, celui des auteurs et des mentionnés de ses messages ; le service de
  // l'extension ne le fait partir qu'avec un message qui part, une fois tant qu'il ne change pas.

  const profiles = { at: 0, byId: new Map(), loading: null };

  async function readProfiles() {
    const names = (await indexedDB.databases()).map(function (d) { return d && d.name ? String(d.name) : ""; })
      .filter(function (n) { return PROFILES_DB.test(n); });
    const me = selfId();
    const name = names.find(function (n) { return me && n.toLowerCase().indexOf(me) >= 0; }) || names[0];
    if (!name) return;
    const db = await openExisting(name);
    if (!db) return;
    let rows = [];
    try {
      rows = await getAll(db, "profiles");
    } finally {
      db.close();
    }
    const byId = new Map();
    for (const r of rows.slice(0, PROFILES_MAX)) {
      const p = X.profileOf(r);
      if (p) byId.set(p.id, p);
    }
    profiles.byId = byId;
    stats.profiles = byId.size;
  }

  /** Relit les profils s'ils ont vieilli ; jamais deux lectures à la fois, jamais d'erreur qui remonte. */
  function loadProfiles() {
    if (Date.now() - profiles.at < PROFILES_TTL_MS) return Promise.resolve();
    if (!profiles.loading) {
      profiles.loading = readProfiles().catch(function () { /* une autre version de Teams : sans profils */ })
        .finally(function () {
          profiles.at = Date.now();
          profiles.loading = null;
        });
    }
    return profiles.loading;
  }

  /** Les profils connus des auteurs et des mentionnés de ces messages, chacun une fois. */
  function profilesFor(messages) {
    const out = new Map();
    for (const m of messages) {
      if (m.deleted) continue;
      for (const raw of [m.authorId].concat(m.mentions || [])) {
        const id = String(raw || "").toLowerCase();
        const p = id && profiles.byId.get(id);
        if (p && !out.has(id)) out.set(id, p);
      }
    }
    return Array.from(out.values()).slice(0, 300);
  }

  function flush() {
    flushTimer = 0;
    if (!pendingMessages.length && !pendingConversations.length && !pendingCursors.size) return;
    const messages = pendingMessages.splice(0, 300);
    const conversations = pendingConversations.splice(0, 300);
    // les curseurs ne partent qu'avec le dernier lot : un curseur dit « tout ce qui précède est passé », jamais avant
    // que ce soit vrai (un onglet fermé entre deux lots ne perd rien)
    let cursors = [];
    if (!pendingMessages.length) {
      cursors = Array.from(pendingCursors, function (e) { return { conv: e[0], w: e[1].w, m: e[1].m }; }).slice(0, 300);
      for (const c of cursors) pendingCursors.delete(c.conv);
    }
    stats.sent += messages.length;
    post("captured", { messages: messages, conversations: conversations, self: selfId(), cursors: cursors,
      profiles: profilesFor(messages) });
    if (pendingMessages.length || pendingConversations.length || pendingCursors.size) schedule();
  }

  function schedule() {
    if (!flushTimer) flushTimer = setTimeout(flush, FLUSH_MS);
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
      // sans conversation (Teams diffuse parfois ainsi un message qu'on vient d'envoyer) : pas passé, pas noté —
      // sa version complète, qui suit, passera (le bug du 2026-11-22)
      if (!m.conv) {
        stats.noConversation = (stats.noConversation || 0) + 1;
        continue;
      }
      if (sentKeys.size >= SENT_IN_PAGE_MAX) {
        sentKeys.clear();
        latest.clear();
      }
      if (!T.freshVersion(m, sentKeys, latest)) continue;
      m.source = source;
      pendingMessages.push(m);
      stats[source].messages++;
      // ses images, en direct : celles des messages de la fenêtre (l'historique envoie les siennes lui-même)
      if (m.images && !m.deleted && m.time >= Date.now() - SYNC_WINDOW_MS) queueImages(m, false);
    }
    if (pendingMessages.length || pendingConversations.length) schedule();
  }

  function inspect(value, source, conversation) {
    try {
      take(X.extract(value, { parseStrings: true, conversation: conversation || "", self: selfId() }), source);
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

  // ── Le worker de Teams ──────────────────────────────────────────────────────
  //
  // Le Teams d'aujourd'hui fait vivre son service de chat, sa connexion en direct et sa base locale dans un worker : la
  // page n'en voit que ce qu'il lui passe — des réponses JSON en texte, où passent les messages dès qu'ils arrivent.
  // On les lit comme une trame, et chaque fois que le worker parle d'un message, une synchro ciblée suit (ADR 0251).

  const workerFrames = [];
  let workerTimer = 0;

  function readWorkerFrames() {
    workerTimer = 0;
    // quelques-unes par tâche : au démarrage de Teams, des dizaines de réponses de 2 Mo feraient saccader la page
    for (const data of workerFrames.splice(0, WORKER_PER_TASK)) inspect(data, "worker", "");
    if (workerFrames.length) workerTimer = setTimeout(readWorkerFrames, 0);
  }

  // ── L'envoi par le worker de Teams (ADR 0301) ──────────────────────────────
  //
  // La page passe à son worker des commandes GraphQL en texte JSON ; envoyer y est `autoSendMessage`. On regarde
  // passer ces commandes sans jamais les changer : le worker qui les reçoit, `rendererId`, `windowId` et le plus haut
  // numéro de requête vus ; et, d'un envoi de la page, un modèle de la commande, sans rien de ce message
  // (`P.workerSendTemplate`), gardé par le service : il survit à l'onglet. Pour envoyer, on rejoue ce modèle, en texte
  // JSON, par le `postMessage` d'origine : le worker envoie lui-même, avec sa propre connexion. Aucun jeton n'est lu.

  const hookedWorkers = new WeakSet(); // les workers de Teams (pas celui de la télémétrie)
  const commandState = new WeakMap(); // worker → { highest, rendererId, windowId }
  let commandWorker = null; // celui qui reçoit les commandes de la page — celui d'un envoi, de préférence
  let commandWorkerSends = false;
  let ownRequest = 0; // le numéro de notre dernière requête : jamais deux fois le même
  const sendTemplates = { bilateral: null, group: null }; // `{command, open, close, breaks, at}`
  let templatesLoaded = false;
  let templatesLoading = null;
  const workerWaits = new Map(); // requestId → ce qui attend sa réponse
  const workerLate = new Set(); // nos requêtes restées sans réponse à temps (une réponse tardive est comptée)
  const workerRefused = new Set(); // les éléments que le worker a refusés ici : ils prennent la voie suivante

  /** Une commande que la page passe à un worker de Teams : lue, jamais changée ; un envoi donne son modèle. */
  function noteCommand(worker, data) {
    if (data.length > WORKER_COMMAND_MAX_CHARS || data.indexOf('"requestId"') < 0) return;
    const head = P.workerCommandHead(data);
    if (!head) return;
    stats.worker.commands++;
    const known = commandState.get(worker) || { highest: 0, rendererId: undefined, windowId: undefined };
    known.highest = Math.max(known.highest, head.number);
    if (head.rendererId !== undefined) known.rendererId = head.rendererId;
    if (head.windowId !== undefined) known.windowId = head.windowId;
    commandState.set(worker, known);
    if (head.operation === "autoSendMessage") {
      commandWorker = worker;
      commandWorkerSends = true;
      // décodé hors de l'appel de la page : son envoi n'attend pas
      setTimeout(function () { learnTemplate(data); }, 0);
    } else if (!commandWorker || !commandWorkerSends) {
      commandWorker = worker;
    }
  }

  function sameTemplate(a, b) {
    const pick = function (t) { return JSON.stringify([t.command, t.open, t.close, t.breaks]); };
    return Boolean(a && b) && pick(a) === pick(b);
  }

  /** Le modèle d'un envoi de la page (son texte, sa conversation, ses identifiants retirés), gardé par le service. */
  function learnTemplate(data) {
    try {
      let command;
      try {
        command = JSON.parse(data);
      } catch (_) {
        return;
      }
      const got = P.workerSendTemplate(command);
      if (!got.template) {
        stats.worker.templateRefused++;
        stats.worker.templateIssue = got.reason;
        return;
      }
      const kind = got.bilateral ? "bilateral" : "group";
      const before = sendTemplates[kind];
      stats.worker.templates++;
      stats.worker.templateIssue = "";
      if (sameTemplate(before, got.template)) return; // le même : rien de neuf à garder
      sendTemplates[kind] = Object.assign({ at: Date.now() }, got.template);
      askService("sendTemplate", { template: got.template, bilateral: got.bilateral }, TEMPLATE_ASK_MS);
    } catch (_) {
      stats.worker.errors++;
    }
  }

  /** Les modèles gardés par le service (une fois par page) ; un modèle capté ici, plus récent, l'emporte. */
  function loadSendTemplates() {
    if (templatesLoaded) return Promise.resolve();
    if (!templatesLoading) {
      templatesLoading = askService("sendTemplates", {}, TEMPLATE_ASK_MS).then(function (answer) {
        if (!answer || !answer.ok) return;
        const got = answer.data && typeof answer.data === "object" ? answer.data : {};
        for (const kind of ["bilateral", "group"]) {
          const t = got[kind];
          const mine = sendTemplates[kind];
          if (t && t.command && !(mine && mine.at >= (Number(t.at) || 0))) sendTemplates[kind] = t;
        }
        templatesLoaded = true;
      }).finally(function () { templatesLoading = null; });
    }
    return templatesLoading;
  }

  /** Le worker où l'on peut rejouer une commande, et ce que la page vivante lui a dit ; `null` sinon. */
  function liveCommand() {
    const worker = commandWorker;
    const known = worker ? commandState.get(worker) : null;
    if (!known || known.rendererId === undefined || known.windowId === undefined) return null;
    return { worker: worker, known: known };
  }

  function templatesAt() {
    return { bilateral: sendTemplates.bilateral ? Number(sendTemplates.bilateral.at) || 0 : 0,
      group: sendTemplates.group ? Number(sendTemplates.group.at) || 0 : 0 };
  }

  /** Une réponse du worker : celle qu'attend notre commande d'envoi, ou une qui arrive après qu'on l'a crue perdue. */
  function noteReply(data) {
    let reply = data;
    if (typeof data === "string") {
      if (data.length > MAX_WORKER_CHARS || data.indexOf('"requestId"') < 0) return;
      let hit = false;
      for (const id of workerWaits.keys()) if (data.indexOf('"' + id + '"') >= 0) hit = true;
      for (const id of workerLate) if (data.indexOf('"' + id + '"') >= 0) hit = true;
      if (!hit) return;
      try {
        reply = JSON.parse(data);
      } catch (_) {
        return;
      }
    }
    const id = reply && typeof reply === "object" && typeof reply.requestId === "string" ? reply.requestId : "";
    if (workerWaits.has(id)) {
      const outcome = P.workerReplyOutcome(reply);
      if (outcome.result) workerWaits.get(id)(outcome);
    } else if (workerLate.has(id)) {
      workerLate.delete(id);
      stats.compose.workerLate++;
    }
  }

  /** La réponse du worker à notre requête `id`, ou `null` après `WORKER_SEND_TIMEOUT_MS`. */
  function workerReply(id) {
    return new Promise(function (resolve) {
      const timer = setTimeout(function () {
        workerWaits.delete(id);
        if (workerLate.size >= WORKER_LATE_MAX) workerLate.clear();
        workerLate.add(id);
        resolve(null);
      }, WORKER_SEND_TIMEOUT_MS);
      workerWaits.set(id, function (outcome) {
        clearTimeout(timer);
        workerWaits.delete(id);
        resolve(outcome);
      });
    });
  }

  function onWorkerMessage(event) {
    try {
      stats.worker.received++;
      const data = event.data;
      if (workerWaits.size || workerLate.size) noteReply(data);
      if (typeof data !== "string" || data.length > MAX_WORKER_CHARS || data.indexOf('"content"') < 0) return;
      if (data.indexOf('"messagetype"') < 0 && data.indexOf('"messageType"') < 0) return;
      stats.worker.kept++;
      if (workerFrames.length < WORKER_PENDING_MAX) workerFrames.push(data);
      if (!workerTimer) workerTimer = setTimeout(readWorkerFrames, 0);
      nudge();
    } catch (_) {
      stats.worker.errors++;
    }
  }

  const NativeWorker = window.Worker;
  const workerProto = typeof NativeWorker === "function" ? NativeWorker.prototype : null;
  const nativeWorkerPost = workerProto && typeof workerProto.postMessage === "function" ? workerProto.postMessage
    : null;
  if (typeof NativeWorker === "function" && typeof Proxy === "function") {
    try {
      window.Worker = new Proxy(NativeWorker, {
        construct: function (target, args, newTarget) {
          const worker = Reflect.construct(target, args, newTarget);
          try {
            const url = String(args[0] && args[0].href ? args[0].href : args[0] || "");
            if (!/telemetry/i.test(url)) {
              worker.addEventListener("message", onWorkerMessage);
              hookedWorkers.add(worker);
              stats.worker.hooked++;
            }
          } catch (_) {
            stats.worker.errors++;
          }
          return worker;
        },
      });
    } catch (_) {
      stats.worker.errors++;
    }
    // ce que la page passe à ses workers : lu au passage, transmis tel quel, par le même appel
    if (nativeWorkerPost) {
      try {
        workerProto.postMessage = function (data) {
          try {
            if (typeof data === "string" && hookedWorkers.has(this)) noteCommand(this, data);
          } catch (_) {
            stats.worker.errors++;
          }
          return nativeWorkerPost.apply(this, arguments);
        };
        const nativeTerminate = workerProto.terminate;
        if (typeof nativeTerminate === "function") {
          workerProto.terminate = function () {
            try {
              if (this === commandWorker) {
                commandWorker = null;
                commandWorkerSends = false;
              }
            } catch (_) { /* rien */ }
            return nativeTerminate.apply(this, arguments);
          };
        }
      } catch (_) {
        stats.worker.errors++;
      }
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

  /** Tous les enregistrements d'un magasin (les fiches de conversation : quelques centaines). */
  function getAll(db, storeName) {
    return new Promise(function (resolve) {
      try {
        const request = db.transaction(storeName, "readonly").objectStore(storeName).getAll();
        request.onsuccess = function () { resolve(Array.isArray(request.result) ? request.result : []); };
        request.onerror = function () { resolve([]); };
      } catch (_) {
        resolve([]);
      }
    });
  }

  /**
   * Les fils d'une conversation livrés depuis `since` (ms ; 0 : tous), dans chaque magasin de fils, par l'index
   * [conversation, heure de dernière livraison] — sans lui (une autre version de Teams), par la clé de la conversation,
   * filtrés à la main. `onValue` reçoit chaque fil ; rend le plus tard livré qu'on ait lu (0 : aucun).
   */
  async function readChains(db, conversation, since, onValue) {
    let latest = 0;
    for (const storeName of CHAIN_STORES) {
      if (!db.objectStoreNames.contains(storeName)) continue;
      latest = Math.max(latest, await new Promise(function (resolve) {
        let most = 0;
        let request;
        try {
          const store = db.transaction(storeName, "readonly").objectStore(storeName);
          const indexed = store.indexNames.contains(CHAIN_INDEX);
          const range = indexed ? IDBKeyRange.bound([conversation, since || 0], [conversation, []])
            : IDBKeyRange.bound([conversation], [conversation, []]);
          request = (indexed ? store.index(CHAIN_INDEX) : store).openCursor(range);
        } catch (_) {
          stats.idb.errors++;
          resolve(0);
          return;
        }
        request.onsuccess = function () {
          const cursor = request.result;
          if (!cursor) {
            resolve(most);
            return;
          }
          const value = cursor.value;
          const delivered = value && typeof value === "object" ? Number(value.latestDeliveryTime) || 0 : 0;
          if (!since || delivered >= since) {
            most = Math.max(most, delivered);
            try {
              onValue(value);
            } catch (_) {
              stats.idb.errors++;
            }
          }
          cursor.continue();
        };
        request.onerror = function () { resolve(most); };
      }));
    }
    return latest;
  }

  /**
   * Les bases de Teams qui comptent, d'un même compte : celle des fiches de conversation et celle des fils portent la
   * même fin de nom (le client, le locataire, la personne, la langue). Plusieurs comptes dans ce navigateur : celui
   * dont la fin de nom porte l'identité de la page, sinon le premier complet.
   */
  async function databases() {
    const byTail = new Map();
    for (const info of await indexedDB.databases()) {
      const name = info && info.name ? String(info.name) : "";
      if (!name || NOT_CHAINS_DB.test(name)) continue;
      const kind = CONVERSATIONS_DB.test(name) ? "conversations" : CHAINS_DB.test(name) ? "chains" : "";
      if (!kind) continue;
      const at = name.indexOf("react-web-client");
      const tail = (at >= 0 ? name.slice(at) : name.replace(/^[^:]*:[^:]*:/, "")).replace(/8:orgid:/g, "");
      const pair = byTail.get(tail) || { conversations: "", chains: "", tail: tail };
      if (!pair[kind]) pair[kind] = name;
      byTail.set(tail, pair);
    }
    const pairs = Array.from(byTail.values()).filter(function (p) { return p.conversations; });
    const me = selfId();
    const mine = me ? pairs.filter(function (p) { return p.tail.toLowerCase().indexOf(me) >= 0; }) : [];
    const best = (mine.length ? mine : pairs).sort(function (a, b) { return (b.chains ? 1 : 0) - (a.chains ? 1 : 0); })[0];
    return best || { conversations: "", chains: "" };
  }

  /** Les fiches de conversation, et la base des fils ouverte (à fermer) ; `null` sans base de Teams. */
  async function openTeamsData() {
    const names = await databases();
    if (!names.conversations) return null;
    const convDb = await openExisting(names.conversations);
    if (!convDb) return null;
    let records;
    try {
      records = await getAll(convDb, "conversations");
    } finally {
      convDb.close();
    }
    const chainsDb = names.chains ? await openExisting(names.chains) : null;
    return { records: records, chains: chainsDb };
  }

  // Les curseurs de chaque conversation : gardés par le service de l'extension (ils survivent à la page), lus à la
  // première synchro ; tant qu'il ne les a pas rendus, on ne relit rien (sinon tout repartirait de la fenêtre).
  const cursors = new Map();
  const catchup = new Map(); // conversation → depuis quand sa fiche est en avance sur ses fils
  let cursorsLoaded = false;
  let lastSyncAt = 0; // la fin de la dernière synchro allée au bout

  async function loadCursors() {
    const answer = await askService("cursors", {}, ASK_TIMEOUT_MS);
    if (!answer || !answer.ok) return false;
    const got = answer.data && typeof answer.data === "object" ? answer.data : {};
    cursors.clear();
    for (const conv of Object.keys(got)) {
      const c = got[conv];
      if (c && typeof c === "object") cursors.set(conv, { w: Number(c.w) || 0, m: String(c.m || "") });
    }
    cursorsLoaded = true;
    return true;
  }

  /** Un lot n'a pas atteint le service : nos curseurs ont pu passer devant ; on reprend les siens (ADR 0251). */
  function cursorsLost() {
    cursors.clear();
    pendingCursors.clear();
    catchup.clear();
    cursorsLoaded = false;
    nudge();
  }

  let syncing = false;
  let syncAgain = false;
  let firstSync = true;

  /**
   * La synchro ciblée (ADR 0251) : les fiches de conversation relues (quelques centaines, à peine quelques ms), la
   * plus active d'abord ; pour chacune qui a bougé depuis son curseur, ses fils livrés depuis lui (moins un
   * recouvrement qui grandit avec le temps écoulé depuis la dernière synchro : une veille, des fils remplis après coup),
   * et rien d'autre. Bornée en temps — au moins une fiche par tour — : ce qui reste passe au tour suivant, aussitôt
   * relancé.
   */
  async function sync() {
    if (!stats.idb.available || historyRunning) return;
    if (syncing) {
      syncAgain = true;
      return;
    }
    syncing = true;
    const begun = Date.now();
    let data = null;
    let finished = false;
    try {
      if (!cursorsLoaded && !(await loadCursors())) return; // le service dort ou l'extension a été rechargée
      await loadProfiles();
      data = await openTeamsData();
      if (!data) return;
      stats.idb.conversations = data.records.length;
      const started = Date.now(); // le budget compte la lecture, pas l'ouverture des bases
      const overlapMs = Math.min(SYNC_WINDOW_MS, Math.max(SYNC_OVERLAP_MS,
        lastSyncAt ? started - lastSyncAt + SYNC_OVERLAP_MS : SYNC_WINDOW_MS));
      const records = data.records.filter(function (r) { return r && typeof r.id === "string"; })
        .sort(function (a, b) { return (Number(b.lastMessageTimeUtc) || 0) - (Number(a.lastMessageTimeUtc) || 0); });
      let processed = 0;
      finished = true;
      for (const record of records) {
        const marker = P.conversationMarker(record);
        const cursor = cursors.get(record.id);
        const since = P.syncSince(marker, cursor, started, { windowMs: SYNC_WINDOW_MS, overlapMs: overlapMs });
        if (firstSync || since !== null) take(X.extract(record, { parseStrings: false, self: selfId() }), "idb"); // son nom, son dernier message
        if (since === null) continue;
        if (processed && Date.now() - started > SYNC_BUDGET_MS) {
          syncAgain = true;
          finished = false;
          break;
        }
        processed++;
        const latest = data.chains ? await readChains(data.chains, record.id, since, function (value) {
          take(X.extract(value, { parseStrings: false, self: selfId() }), "idb");
        }) : 0;
        stats.idb.read++;
        // une fiche en avance sur ses fils (Teams range l'une puis les autres) : retentée pendant `CATCHUP_MS`, au
        // temps et non au nombre d'essais (les signes en rafale les épuiseraient en une seconde)
        const ahead = catchup.get(record.id) || started;
        const settled = P.caughtUp(record, latest, CATCHUP_SLACK_MS) || started - ahead >= CATCHUP_MS;
        if (settled) catchup.delete(record.id);
        else catchup.set(record.id, ahead);
        const next = P.advanceCursor(cursor, since, latest, settled ? marker : (cursor ? cursor.m : ""));
        cursors.set(record.id, next);
        pendingCursors.set(record.id, next);
      }
      if (finished) {
        firstSync = false;
        lastSyncAt = Date.now();
      }
      if (pendingCursors.size) schedule();
    } catch (_) {
      stats.idb.errors++;
    } finally {
      if (data && data.chains) data.chains.close();
      stats.idb.syncs++;
      stats.idb.lastSyncMs = Date.now() - begun;
      syncing = false;
      if (syncAgain) {
        syncAgain = false;
        nudge(50);
      }
    }
  }

  let nudgeTimer = 0;
  /** Un signe que quelque chose a bougé : une synchro bientôt (une seule pour une rafale de signes). */
  function nudge(ms) {
    if (nudgeTimer) return;
    nudgeTimer = setTimeout(function () {
      nudgeTimer = 0;
      sync();
    }, ms === undefined ? SYNC_NUDGE_MS : ms);
  }

  setTimeout(function loop() {
    sync().finally(function () { setTimeout(loop, SYNC_EVERY_MS); });
  }, SYNC_FIRST_MS);
  // les modèles d'envoi par le worker que garde le service (ADR 0301) : prêts avant le premier envoi
  setTimeout(function () { loadSendTemplates().catch(function () { /* au premier envoi */ }); }, SYNC_FIRST_MS);

  // le titre de l'onglet compte les non-lus : il change quand un message arrive ailleurs
  let titleWatched = false;
  function watchTitle() {
    const title = document.querySelector("title");
    if (!title || titleWatched) return;
    titleWatched = true;
    try {
      new MutationObserver(function () { nudge(); }).observe(title, { childList: true, characterData: true, subtree: true });
    } catch (_) { /* rien */ }
  }
  document.addEventListener("DOMContentLoaded", watchTitle);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") nudge();
  });

  // ── Les images (ADR 0258) ──────────────────────────────────────────────────
  //
  // Chaque image d'un message (`X.imagesOf` : seulement celles du service d'images de Teams) est téléchargée ici,
  // par son adresse d'origine, puis passée au service, qui la trie comme son message (exclusions, pauses) et l'envoie
  // à Mika une fois le message chez elle. Une à la fois : une image de 8 Mo à la fois en mémoire, pas plus.

  const imageQueue = [];
  const imagesSeen = new Set(); // message|image déjà mis en file dans cette page
  let imagesPumping = false;

  function queueImages(m, history) {
    for (const i of m.images || []) {
      const key = m.id + "|" + i.id;
      if (imagesSeen.has(key) || imageQueue.length >= IMAGE_QUEUE_MAX) continue;
      imagesSeen.add(key);
      imageQueue.push({ conv: m.conv, id: m.id, image: i.id, position: i.position, url: i.url, time: m.time,
        author: m.author, authorId: m.authorId, history: history, tries: 0, notBefore: 0 });
    }
    pumpImages();
  }

  /** Les octets d'une image, en base64, et son type ; `null` : pas une image admise, ou pas téléchargée. */
  async function download(url) {
    if (!IMAGE_HOST.test(url)) return null; // jamais une autre adresse avec les cookies du navigateur
    const response = await nativeFetch.call(window, url, { credentials: "include", cache: "force-cache" });
    if (!response.ok) return null;
    const blob = await response.blob();
    if (!blob.size || blob.size > IMAGE_MAX_BYTES || IMAGE_TYPES.indexOf(blob.type) < 0) return null;
    const data = await new Promise(function (resolve) {
      const reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || "").split(",")[1] || ""); };
      reader.onerror = function () { resolve(""); };
      reader.readAsDataURL(blob);
    });
    return data ? { type: blob.type, data: data } : null;
  }

  /** Télécharger et passer une image ; rend vrai si elle est réglée (envoyée, écartée ou perdue), faux : à retenter. */
  async function sendImage(job) {
    let got = null;
    try {
      got = await download(job.url);
    } catch (_) {
      got = null;
    }
    if (!got) {
      stats.images.failed++;
      return true;
    }
    stats.images.downloaded++;
    const answer = await askService("image", { conv: job.conv, id: job.id, image: job.image, position: job.position,
      type: got.type, data: got.data, time: job.time, author: job.author, authorId: job.authorId,
      history: job.history }, IMAGE_ASK_MS);
    const d = answer && answer.data ? answer.data : {};
    if (answer && answer.ok) {
      if (d.skipped) stats.images.skipped++;
      else stats.images.sent++;
      return true;
    }
    if (d.retry && job.tries + 1 < IMAGE_TRIES) return false;
    stats.images.failed++;
    return true;
  }

  async function pumpImages() {
    if (imagesPumping) return;
    imagesPumping = true;
    try {
      while (imageQueue.length) {
        const now = Date.now();
        const index = imageQueue.findIndex(function (j) { return j.notBefore <= now; });
        if (index < 0) {
          setTimeout(pumpImages, IMAGE_RETRY_MS);
          break;
        }
        const job = imageQueue.splice(index, 1)[0];
        if (!(await sendImage(job))) {
          job.tries++;
          job.notBefore = Date.now() + IMAGE_RETRY_MS;
          imageQueue.push(job);
        }
        await pause(200);
      }
    } finally {
      imagesPumping = false;
    }
  }

  // ── Les photos de profil (ADR 0300) ─────────────────────────────────────────
  //
  // Le service demande la photo des personnes dont le profil vient de partir (jamais d'une conversation exclue, rien
  // pendant une pause) et dont l'empreinte (`avatarETag`) a changé. On la télécharge ici, avec les cookies du
  // navigateur comme Teams lui-même, par l'adresse que Teams donne à ses avatars, puis on la passe au service, qui
  // l'envoie à Mika. Une à la fois.

  const photoQueue = [];
  const photosQueued = new Set(); // personne|empreinte en file ou en cours dans cette page
  let photosPumping = false;
  let photoBase = "";

  /** La base des avatars de Teams (`…/api/mt/part/<région>/beta/users/<soi>`), lue sur un avatar de la page. */
  function avatarBase() {
    if (photoBase) return photoBase;
    try {
      for (const img of document.querySelectorAll('img[src*="/api/mt/part/"]')) {
        photoBase = P.avatarBase(img.src, location.origin, selfId());
        if (photoBase) break;
      }
    } catch (_) { /* une page sans avatar pour l'instant */ }
    return photoBase;
  }

  function queuePhotos(items) {
    for (const p of items) {
      const key = p.person + "|" + p.etag;
      if (photosQueued.has(key) || photoQueue.length >= PHOTO_QUEUE_MAX) continue;
      photosQueued.add(key);
      photoQueue.push(p);
      stats.photos.asked++;
    }
    pumpPhotos();
  }

  /** Les octets d'une photo, en base64, et son type ; `null` : pas d'avatar vu, ou pas une photo admise. */
  async function downloadPhoto(p) {
    const base = avatarBase();
    if (!base) {
      stats.photos.noAvatarSeen++;
      return null;
    }
    const url = P.photoUrl(base, p.person, p.name, p.etag);
    if (!url) return null; // jamais une autre adresse avec les cookies du navigateur
    const response = await nativeFetch.call(window, url, { credentials: "include", cache: "force-cache" });
    if (!response.ok) return null;
    const blob = await response.blob();
    const type = String(blob.type || "").split(";")[0].trim().toLowerCase(); // « image/jpeg; charset=… » : son type
    if (!blob.size || blob.size > PHOTO_MAX_BYTES || PHOTO_TYPES.indexOf(type) < 0) return null;
    const data = await new Promise(function (resolve) {
      const reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || "").split(",")[1] || ""); };
      reader.onerror = function () { resolve(""); };
      reader.readAsDataURL(blob);
    });
    return data ? { type: type, data: data } : null;
  }

  async function pumpPhotos() {
    if (photosPumping) return;
    photosPumping = true;
    try {
      while (photoQueue.length) {
        const p = photoQueue.shift();
        let got = null;
        try {
          got = await downloadPhoto(p);
        } catch (_) {
          got = null;
        }
        if (got) {
          stats.photos.downloaded++;
          const answer = await askService("photo", { person: p.person, etag: p.etag, type: got.type, data: got.data },
            PHOTO_ASK_MS);
          const d = answer && answer.data ? answer.data : {};
          if (answer && answer.ok) stats.photos[d.skipped ? "skipped" : "sent"]++;
          else stats.photos.failed++;
        } else {
          stats.photos.failed++;
        }
        // réglée ici : le service la redemandera s'il le faut
        photosQueued.delete(p.person + "|" + p.etag);
        await pause(200);
      }
    } finally {
      photosPumping = false;
    }
  }

  // ── L'historique (le bouton de la mise en service) ─────────────────────────
  //
  // Toute la base locale, conversation par conversation, par paquets que le service range un à un (chacun attendu
  // avant le suivant) ; marqués historiques, ils se rangent chez Mika déjà lus. La synchro se tait pendant ce temps.

  let historyRunning = false;

  /** Les conversations qui ont des fils (la clé d'un fil commence par elle), sautées de l'une à l'autre. */
  function chainConversations(db, storeName) {
    return new Promise(function (resolve) {
      const out = [];
      let request;
      try {
        request = db.transaction(storeName, "readonly").objectStore(storeName).openKeyCursor();
      } catch (_) {
        resolve(out);
        return;
      }
      request.onsuccess = function () {
        const cursor = request.result;
        if (!cursor) {
          resolve(out);
          return;
        }
        const conv = Array.isArray(cursor.key) ? cursor.key[0] : null;
        if (typeof conv === "string" && out.length < 20000) {
          out.push(conv);
          cursor.continue([conv, []]); // après tous les fils de cette conversation
        } else {
          cursor.continue();
        }
      };
      request.onerror = function () { resolve(out); };
    });
  }

  /**
   * Tous les fils d'une conversation, par sa clé (pas par l'index : un fil sans heure de livraison n'y est pas), par
   * pages de `HISTORY_PAGE`, une transaction chacune : Teams écrit entre deux pages.
   */
  async function readAllChains(db, conversation, onValue) {
    for (const storeName of CHAIN_STORES) {
      if (!db.objectStoreNames.contains(storeName)) continue;
      let lower = [conversation];
      let open = false;
      for (;;) {
        const page = await new Promise(function (resolve) {
          try {
            const request = db.transaction(storeName, "readonly").objectStore(storeName)
              .getAll(IDBKeyRange.bound(lower, [conversation, []], open, false), HISTORY_PAGE);
            request.onsuccess = function () { resolve(Array.isArray(request.result) ? request.result : []); };
            request.onerror = function () { resolve([]); };
          } catch (_) {
            stats.idb.errors++;
            resolve([]);
          }
        });
        for (const value of page) {
          try {
            onValue(value);
          } catch (_) {
            stats.idb.errors++;
          }
        }
        const last = page[page.length - 1];
        if (page.length < HISTORY_PAGE || !last || last.replyChainId === undefined) break;
        lower = [conversation, last.replyChainId];
        open = true;
        await pause(0);
      }
    }
  }

  /**
   * L'historique (ADR 0251) : chaque conversation — celles des fiches et celles qui n'ont que des fils —, ses
   * `HISTORY_KEEP` messages les plus récents (Mika n'en garde pas plus), par paquets que le service range un à un. `run`
   * : l'identifiant de ce chargement, que portent ses paquets (un chargement relancé ignore les paquets d'avant).
   */
  async function historyRun(run) {
    if (historyRunning) return;
    historyRunning = true;
    const h = stats.history;
    h.running = true;
    h.done = h.total = h.messages = h.images = 0;
    h.error = "";
    let data = null;
    try {
      await loadProfiles();
      data = await openTeamsData();
      if (!data) throw new Error("pas de base de Teams lisible dans cet onglet");
      const records = new Map();
      for (const r of data.records) if (r && typeof r.id === "string") records.set(r.id, r);
      const ids = new Set(records.keys());
      if (data.chains) {
        for (const storeName of CHAIN_STORES) {
          if (!data.chains.objectStoreNames.contains(storeName)) continue;
          for (const conv of await chainConversations(data.chains, storeName)) ids.add(conv);
        }
      }
      h.total = ids.size;
      askService("historyProgress", { run: run, done: 0, total: h.total, messages: 0 }, 2000);
      for (const id of ids) {
        const conversations = [];
        // un message lu deux fois (sa fiche, deux magasins de fils) part une fois, à sa version la plus récente — ses
        // réactions comprises (ADR 0300) ; à version égale, la dernière lue (un fil dit plus qu'une fiche) ; une
        // suppression l'emporte
        const byId = new Map();
        const add = function (got) {
          for (const c of got.conversations) conversations.push(c);
          for (const m of got.messages) {
            const prev = byId.get(m.id);
            if (prev && (prev.deleted || (!m.deleted && (Number(m.version) || 0) < (Number(prev.version) || 0)))) continue;
            m.source = "idb";
            byId.set(m.id, m);
          }
        };
        if (records.has(id)) add(X.extract(records.get(id), { parseStrings: false, self: selfId() }));
        if (data.chains) await readAllChains(data.chains, id, function (value) {
          add(X.extract(value, { parseStrings: false, self: selfId() }));
        });
        // les plus récents d'abord retenus, puis envoyés du plus ancien au plus récent
        const kept = Array.from(byId.values()).sort(function (a, b) { return b.time - a.time; })
          .slice(0, HISTORY_KEEP).reverse();
        for (let i = 0; i === 0 || i < kept.length; i += HISTORY_CHUNK) {
          const part = kept.slice(i, i + HISTORY_CHUNK);
          if (!part.length && !conversations.length) break;
          const answer = await askService("historyChunk", { run: run, messages: part,
            conversations: i === 0 ? conversations.slice(0, 50) : [], self: selfId(), profiles: profilesFor(part) },
          HISTORY_ASK_MS);
          if (!answer || !answer.ok) {
            throw new Error((answer && answer.data && answer.data.error) || "le service de l'extension ne répond pas");
          }
          h.messages += part.length;
          // ses images, juste après lui (le message est chez Mika) : une à une, attendues
          for (const m of part) {
            for (const i of (m.deleted ? [] : m.images || [])) {
              const key = m.id + "|" + i.id;
              if (imagesSeen.has(key)) continue;
              imagesSeen.add(key);
              await sendImage({ conv: m.conv, id: m.id, image: i.id, position: i.position, url: i.url, time: m.time,
                author: m.author, authorId: m.authorId, history: true, tries: 0, notBefore: 0 });
              h.images++;
            }
          }
        }
        h.done++;
        askService("historyProgress", { run: run, done: h.done, total: h.total, messages: h.messages }, 2000);
      }
    } catch (e) {
      h.error = T.cut(String(e && e.message ? e.message : e), 200);
    } finally {
      if (data && data.chains) data.chains.close();
      h.running = false;
      historyRunning = false;
      askService("historyDone", { run: run, done: h.done, total: h.total, messages: h.messages, error: h.error }, 5000);
      nudge();
    }
  }

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

  /**
   * L'éditeur de la zone de saisie de Teams (CKEditor 5), que la page pose sur son élément (`ckeditorInstance`) ;
   * `null` si ce n'en est pas un. C'est son modèle que Teams envoie, pas ce que montre le DOM.
   */
  function editorModel(editor) {
    const ck = editor && editor.ckeditorInstance;
    return ck && ck.model && typeof ck.model.change === "function" && typeof ck.getData === "function"
      && typeof ck.execute === "function" && ck.commands ? ck : null;
  }

  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", "#39": "'", apos: "'", nbsp: " " };

  /** Le texte du modèle de l'éditeur : ses sauts de ligne et ses paragraphes en retours, ses entités décodées. */
  function modelText(ck) {
    return String(ck.getData() || "").replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>\s*<p[^>]*>/gi, "\n")
      .replace(/<[^>]*>/g, "").replace(/&(#39|[a-z]+);/gi, function (all, name) {
        return Object.prototype.hasOwnProperty.call(ENTITIES, name.toLowerCase()) ? ENTITIES[name.toLowerCase()] : all;
      });
  }

  /** Un texte comparable : ses blancs (espaces insécables compris) ramenés à un seul. */
  function squeeze(text) {
    return String(text).replace(/[\s\u00a0]+/g, " ").trim();
  }

  /** La zone est vide pour Teams : rien dans le modèle de l'éditeur (le DOM seul, sans éditeur connu). */
  function isEmpty(editor) {
    const ck = editorModel(editor);
    if (ck) {
      try {
        return String(ck.getData() || "").replace(/<[^>]*>/g, "").replace(/&nbsp;| /g, " ").trim() === "";
      } catch (_) { /* un éditeur dans un état inattendu : le DOM tranche */ }
    }
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
   * Le texte dans la zone de saisie, ligne à ligne, un saut de ligne simple (Maj+Entrée) entre deux lignes — jamais un
   * paragraphe, qu'un éditeur de Teams peut prendre pour « Envoyer ». Les Trusted Types de la page interdisent
   * `innerHTML` : rien ici n'en passe par là.
   *
   * Avec l'éditeur de Teams, le texte entre dans son modèle, par ses propres commandes. Une frappe simulée
   * (`execCommand`) n'y entre pas toujours — un onglet sans le focus : le texte s'affiche, l'éditeur le redessine vide
   * au clic, rien ne part, et la zone vidée passait pour un envoi. La frappe simulée ne sert plus qu'à un éditeur
   * qu'on ne connaît pas.
   */
  function insertText(editor, text) {
    const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
    const ck = editorModel(editor);
    if (ck) {
      if (ck.isReadOnly) return false;
      const typing = ck.commands.get("insertText") ? "insertText" : "input";
      try {
        // la sélection en fin de texte, puis une commande à la fois : groupées dans un seul `model.change`, la
        // sélection n'avance pas entre deux commandes et les lignes se mêlent (« <br>xy » pour « x », « y »)
        ck.model.change(function (writer) {
          const root = ck.model.document.getRoot();
          if (root && root.childCount) writer.setSelection(root.getChild(root.childCount - 1), "end");
        });
        lines.forEach(function (line, i) {
          if (i > 0) ck.execute("shiftEnter");
          if (line) ck.execute(typing, { text: line });
        });
      } catch (_) {
        // une moitié de texte ne part jamais : la zone est remise à vide, rien n'est parti
        try { ck.setData(""); } catch (_e) { /* rien */ }
        return false;
      }
      // ce qui est dans le modèle est-il bien tout le texte ? une commande désactivée n'y met rien, sans erreur
      if (squeeze(modelText(ck)) !== squeeze(lines.join("\n"))) {
        try { ck.setData(""); } catch (_e) { /* rien */ }
        return false;
      }
      return true;
    }
    editor.focus();
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
  function askExtension(kind, payload, timeoutMs) {
    return new Promise(function (resolve) {
      const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
      answers.set(nonce, resolve);
      post(kind, Object.assign({ nonce: nonce }, payload));
      setTimeout(function () {
        if (answers.has(nonce)) {
          answers.delete(nonce);
          resolve(null);
        }
      }, timeoutMs || ASK_TIMEOUT_MS);
    });
  }

  /** Une demande au service, qui rend `{ok, data}` (null : pas de réponse à temps) : ses curseurs, l'historique. */
  function askService(what, payload, timeoutMs) {
    return askExtension("ask", { what: what, payload: payload || {} }, timeoutMs);
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

  function newCorrelationId() {
    try {
      if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
      const b = window.crypto.getRandomValues(new Uint8Array(16));
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const h = Array.from(b, function (x) { return (x + 0x100).toString(16).slice(1); }).join("");
      return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
    } catch (_) {
      return "";
    }
  }

  /**
   * L'envoi par le worker de Teams (ADR 0301) : le modèle rejoué pour cette conversation, en texte JSON, la réponse
   * attendue. `{refused: true, reason}` : rien n'est parti (une erreur explicite, ou la commande pas passée), la voie
   * suivante peut servir ; sans réponse à temps, l'issue est douteuse — peut-être parti : jamais deux envois.
   */
  async function sendViaWorker(item, template, live) {
    const requestNumber = P.nextRequestNumber(live.known.highest, ownRequest);
    const command = P.workerSendCommand(template, { conversation: item.conversation, text: item.text,
      clientMessageId: P.clientMessageIdFor(item.id), correlationId: newCorrelationId(), now: Date.now(),
      requestNumber: requestNumber, rendererId: live.known.rendererId, windowId: live.known.windowId });
    if (!command) return { refused: true, reason: "le modèle d'envoi de Teams ne s'applique pas à ce message" };
    ownRequest = requestNumber;
    const id = P.workerRequestId(requestNumber);
    startedSends.add(item.id);
    try {
      // le `postMessage` d'origine : notre commande n'a rien à faire parmi celles de la page
      nativeWorkerPost.call(live.worker, command);
    } catch (_) {
      startedSends.delete(item.id); // rien n'a quitté la page
      return { refused: true, reason: "le worker de Teams n'a pas pris la commande" };
    }
    const outcome = await workerReply(id);
    if (!outcome) {
      stats.compose.workerSilent++;
      return uncertain("le worker de Teams n'a pas répondu (10 s) : peut-être parti, à vérifier dans Teams");
    }
    if (outcome.result === "sent") {
      stats.compose.sentByWorker++;
      return { result: "sent", via: "worker", message_id: outcome.messageId || "" };
    }
    if (outcome.result === "uncertain") {
      return uncertain("le worker de Teams a répondu avec une erreur"
        + (outcome.reason ? " (" + outcome.reason + ")" : "") + " : peut-être parti, à vérifier dans Teams");
    }
    // un refus explicite : rien n'est parti ; cet élément prend la voie suivante, ici et aux essais suivants
    stats.compose.workerRefused++;
    startedSends.delete(item.id);
    if (workerRefused.size >= WORKER_REFUSED_MAX) workerRefused.clear();
    workerRefused.add(item.id);
    return { refused: true,
      reason: "le worker de Teams a refusé l'envoi" + (outcome.reason ? " (" + outcome.reason + ")" : "") };
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
      // d'abord le worker de Teams (ADR 0301) : un tête-à-tête ou un groupe, un modèle d'envoi, un worker vivant ; la
      // conversation n'a pas à être ouverte. Seul un refus explicite laisse prendre la voie suivante : rien n'est
      // parti.
      let refusedBy = "";
      if (P.workerSendable(item.conversation) && !workerRefused.has(item.id) && nativeWorkerPost) {
        await loadSendTemplates();
        const template = P.pickSendTemplate(sendTemplates, item.conversation);
        const live = liveCommand();
        if (template && live) {
          const viaWorker = await sendViaWorker(item, template, live);
          if (!viaWorker.refused) return viaWorker;
          refusedBy = viaWorker.reason;
        }
      }
      if (chatAuth) {
        const viaService = await sendViaChatService(item);
        // seul un refus d'authentification laisse prendre l'autre chemin : rien n'est parti
        if (!viaService.authLost) return viaService;
      }
      const viaBox = await sendViaComposeBox(item);
      return refusedBy && viaBox.result !== "sent"
        ? Object.assign({}, viaBox, { reason: refusedBy + " ; " + viaBox.reason }) : viaBox;
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
      // les modèles d'envoi du service d'abord (une fois par page, 3 s au plus : le relais en attend 8)
      loadSendTemplates().catch(function () { /* sans eux */ }).then(function () {
        const report = JSON.parse(JSON.stringify(stats));
        report.url = location.origin + location.pathname;
        report.selfFound = Boolean(selfId());
        report.conversationTitles = Array.from(titles.values()).filter(function (c) { return c.title; }).length;
        let editor = null;
        try { editor = findEditor(); } catch (_) { /* rien */ }
        report.compose.editorFound = Boolean(editor);
        report.compose.activeConversationKnown = Boolean(activeConversation());
        report.compose.chatSendPossible = Boolean(chatAuth); // l'existence de l'en-tête, jamais sa valeur
        // l'envoi par le worker (ADR 0301) : un worker qui reçoit les commandes de la page, et un modèle (sa date)
        const at = templatesAt();
        report.compose.workerSeen = Boolean(liveCommand());
        report.compose.workerTemplates = at;
        report.compose.workerSendPossible = Boolean(liveCommand() && nativeWorkerPost && (at.bilateral || at.group));
        report.compose.drafts = drafts.length;
        post("report", { nonce: data.nonce, report: report });
      });
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
    } else if (data.kind === "photos" && Array.isArray(data.items)) {
      queuePhotos(data.items.filter(function (p) {
        return p && typeof p.person === "string" && typeof p.etag === "string" && p.person && p.etag;
      }).slice(0, 20));
    } else if (data.kind === "answer" && answers.has(data.nonce)) {
      const resolve = answers.get(data.nonce);
      answers.delete(data.nonce);
      resolve({ ok: data.ok === true, data: data.data });
    } else if (data.kind === "history") {
      historyRun(typeof data.run === "string" ? data.run.slice(0, 40) : "");
    } else if (data.kind === "cursorsLost") {
      cursorsLost();
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
