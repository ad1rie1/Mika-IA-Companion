/*
 * Ce qui part vers Mika, et sous quelle forme. Pur : l'horloge et l'état sont passés en paramètres — utilisé par le
 * service d'arrière-plan de l'extension, par sa page de réglages, et par les tests sous Node.
 *
 * Mika reçoit les messages par l'entrée de son plugin Teams (`POST /api/teams/inbox`) : 200 messages et 200
 * conversations au plus par envoi, 4000 caractères par texte, 512 Kio par corps. Les lots sont coupés ici, avant de
 * partir ; un 413 malgré tout fait recouper plus petit (le service d'arrière-plan baisse `maxMessages`). Un message
 * illisible pour le serveur est écarté par lui seul (le reste du lot passe) ; un 400 ne dit plus qu'un corps illisible.
 *
 * Le nom vient de la première version, qui envoyait des signaux d'appareil de 400 caractères ; ce sont maintenant
 * les messages entiers, les siens compris (`own`) : Mika a besoin des deux voix d'un fil. Un message modifié repart
 * (le serveur met son texte à jour) ; un message supprimé part comme une suppression (`deleted`, texte vide).
 */
(function (root, factory) {
  const node = typeof module === "object" && module && module.exports && typeof require === "function";
  const api = factory(node ? require("./text.js") : root.MikaTeamsText);
  if (node) module.exports = api;
  else root.MikaTeamsSignals = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (T) {
  "use strict";

  const LIMITS = {
    windowMs: 24 * 3600 * 1000, // au-delà, un message trouvé n'est plus « nouveau »
    maxMessages: 200, // par envoi, le plafond du serveur
    maxConversations: 200,
    maxBytes: 512 * 1024, // le corps entier, en octets UTF-8
    maxText: 4000,
    holdMs: 120 * 1000, // le temps laissé pour apprendre le nom d'une conversation, quand des exclusions sont réglées
    pausesMax: 50,
    serverErrorsMax: 8, // un même lot refusé autant de fois de suite par la même erreur 5xx est écarté
  };

  const KINDS = ["dm", "group", "channel", "meeting", "other"];
  const LOOPBACK = ["127.0.0.1", "localhost"];

  // les formes d'identifiant que le serveur accepte : un identifiant hors de ces formes fait écarter le message
  const CONVERSATION_ID = /^\d{1,3}:[A-Za-z0-9@._:=+-]{1,300}$/;
  const MESSAGE_ID = /^[\w.:@=+/-]{1,200}$/;
  const SELF_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  function has(o, k) {
    return Boolean(o) && Object.prototype.hasOwnProperty.call(o, k);
  }

  function clean(s, max) {
    const t = String(s || "").replace(/[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩]+/g, " ")
      .replace(/\s+/g, " ").trim();
    return max ? T.clip(t, max) : T.wellFormed(t);
  }

  // ── Soi ────────────────────────────────────────────────────────────────────

  /** L'identifiant de soi tel que le serveur l'attend : `8:orgid:<uuid>`, ou « » si inconnu. */
  function selfMri(selfId) {
    const s = String(selfId || "").trim();
    if (!s) return "";
    return (s.indexOf(":") >= 0 ? s : "8:orgid:" + s).toLowerCase();
  }

  /** Un identifiant de personne comparable : `8:orgid:<uuid>` en minuscules (sans l'adresse qui l'entoure parfois). */
  function mri(id) {
    const s = String(id || "").trim();
    const i = s.lastIndexOf("/contacts/");
    return (i >= 0 ? s.slice(i + "/contacts/".length) : s).toLowerCase();
  }

  /** Une identité de soi recevable : l'uuid que la page a trouvé. */
  function isSelfId(s) {
    return SELF_UUID.test(String(s || ""));
  }

  /** C'est son message : l'auteur est exactement soi (`8:orgid:<uuid>`, sans tenir compte de la casse). */
  function isOwn(msg, selfId) {
    const me = selfMri(selfId);
    return Boolean(me) && mri(msg.authorId) === me;
  }

  function mentionsSelf(msg, selfId) {
    const me = selfMri(selfId);
    if (!me) return false;
    return (msg.mentions || []).some(function (m) { return mri(m) === me; });
  }

  // ── Les exclusions ──────────────────────────────────────────────────────────

  /** Les lignes d'exclusion (un morceau du nom, de l'identifiant, ou d'une personne), nettoyées. */
  function exclusions(text) {
    return String(text || "").split("\n").map(function (l) { return l.trim().toLowerCase(); })
      .filter(function (l) { return l.length > 0; });
  }

  /**
   * Une conversation exclue par l'utilisateur. `c` : `{conv, title, kind, people}`. Une ligne exclut si elle est un
   * morceau de l'identifiant ou du nom ; et, pour une conversation sans nom propre (un tête-à-tête, un groupe sans
   * sujet), un morceau du nom d'une personne qu'on y a vue écrire.
   */
  function isExcluded(c, exclude) {
    if (!exclude || !exclude.length) return false;
    const title = String(c.title || "");
    const parts = [String(c.conv || ""), title];
    if (c.kind === "dm" || !title.trim()) parts.push.apply(parts, (c.people || []).map(String));
    const hay = parts.join("\n").toLowerCase();
    return exclude.some(function (l) { return hay.indexOf(l) >= 0; });
  }

  /** On sait nommer la conversation : un tête-à-tête par la personne d'en face, le reste par sa fiche (`known`). */
  function named(c) {
    return c.kind === "dm" ? (c.people || []).length > 0 : Boolean(c.known);
  }

  /**
   * Un message de la file retenu : des exclusions sont réglées et l'on ne sait pas encore nommer sa conversation. Il
   * attend `holdMs` au plus après sa capture (`entry.at`), puis on décide avec ce qu'on sait.
   */
  function held(entry, c, exclude, now) {
    if (!exclude || !exclude.length || named(c)) return false;
    return now - (Number(entry.at) || 0) < LIMITS.holdMs;
  }

  // ── Les pauses ──────────────────────────────────────────────────────────────

  function cleanPauses(pauses) {
    return (Array.isArray(pauses) ? pauses : [])
      .filter(function (p) { return p && Number(p.start) > 0; })
      .map(function (p) { return { start: Number(p.start), end: Number(p.end) || 0 }; });
  }

  /** Les pauses qui comptent encore : celles qui touchent la fenêtre (un message plus vieux est « ancien »). */
  function prunePauses(pauses, now, windowMs) {
    const limit = now - (windowMs || LIMITS.windowMs) - 2 * 3600 * 1000;
    return cleanPauses(pauses).filter(function (p) { return !p.end || p.end >= limit; }).slice(-LIMITS.pausesMax);
  }

  function pauseOpen(pauses) {
    const list = cleanPauses(pauses);
    return list.length > 0 && !list[list.length - 1].end;
  }

  /** Les intervalles de pause après un changement de l'interrupteur (une pause en cours a `end: 0`). */
  function notePause(pauses, paused, now) {
    const list = cleanPauses(pauses);
    const last = list[list.length - 1];
    if (paused && !(last && !last.end)) list.push({ start: now, end: 0 });
    else if (!paused && last && !last.end) last.end = Math.max(now, last.start);
    return prunePauses(list, now);
  }

  /** Le message a été écrit pendant une pause : il ne part jamais, même capté après la reprise. */
  function inPause(time, pauses) {
    const t = Number(time) || 0;
    return cleanPauses(pauses).some(function (p) { return t >= p.start && (!p.end || t < p.end); });
  }

  // ── Ce qui part ────────────────────────────────────────────────────────────

  /**
   * Pourquoi un message ne part pas (« » : il part). `ctx` : `now`, `armedAt`, `seen` (clé de version → date),
   * `paused`, `pauses`, `title`, `kind`, `people`, `exclude` (lignes), `windowMs`. Ses propres messages partent comme
   * les autres ; une suppression part sans texte.
   */
  function admit(msg, ctx) {
    if (!msg || !msg.id || (!msg.text && !msg.deleted)) return "vide";
    const seen = ctx.seen || {};
    // `seen[id]` seul : une version d'avant les clés de version, vue telle quelle
    if (has(seen, T.versionKey(msg)) || has(seen, String(msg.id))) return "déjà vu";
    if (!msg.deleted && has(seen, T.deletedKey(msg.id))) return "déjà vu"; // supprimé : son texte ne repart plus
    // en pause, rien n'est mis de côté pour plus tard : ce qui est écrit pendant la pause ne partira jamais
    if (ctx.paused || inPause(msg.time, ctx.pauses)) return "en pause";
    if (ctx.kind === "system") return "système";
    // un message dont on ne sait pas la conversation ne serait pas rangé
    if (!msg.conv) return "sans conversation";
    if (!CONVERSATION_ID.test(msg.conv) || !MESSAGE_ID.test(String(msg.id))) return "identifiant illisible";
    if (msg.time < (ctx.armedAt || 0)) return "avant l'activation";
    if (msg.time < ctx.now - (ctx.windowMs || LIMITS.windowMs)) return "ancien";
    if (isExcluded({ conv: msg.conv, title: ctx.title, kind: ctx.kind, people: ctx.people }, ctx.exclude)) {
      return "exclue";
    }
    return "";
  }

  /** Les clés de version déjà vues qu'il faut encore garder : celles de la fenêtre, plus une marge. */
  function pruneSeen(seen, now, windowMs) {
    const keep = {};
    const limit = now - (windowMs || LIMITS.windowMs) - 2 * 3600 * 1000;
    for (const id in seen) {
      if (has(seen, id) && seen[id] >= limit) keep[id] = seen[id];
    }
    return keep;
  }

  /** La nature d'une conversation dans le vocabulaire du serveur (`system` n'y part jamais). */
  function wireKind(kind) {
    return KINDS.indexOf(kind) >= 0 ? kind : "other";
  }

  /** Un message de la file, tel qu'il part. */
  function wireMessage(m, selfId) {
    const wire = {
      id: T.cut(String(m.id), 200),
      conv: T.cut(m.conv, 300),
      author: clean(m.author, 120),
      author_id: T.cut(m.authorId, 200),
      time: Number(m.time) || 0,
      text: m.deleted ? "" : T.cut(m.text, LIMITS.maxText),
      own: isOwn(m, selfId),
      mentions_me: m.deleted ? false : mentionsSelf(m, selfId),
    };
    if (m.deleted) wire.deleted = true;
    return wire;
  }

  /** Une conversation, telle qu'elle part (`info` : `{title, kind}`). */
  function wireConversation(id, info) {
    const i = info || {};
    return { id: T.cut(String(id), 300), title: clean(i.title, 120), kind: wireKind(i.kind) };
  }

  /** La longueur d'une chaîne en octets UTF-8 (ce que compte le plafond du serveur). */
  function utf8Length(s) {
    let n = 0;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      if (c < 0x80) n += 1;
      else if (c < 0x800) n += 2;
      else if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
        n += 4;
        i++;
      } else n += 3;
    }
    return n;
  }

  /**
   * Les lots d'une file. `queue` : les messages admis ; `opts.info(conv)` → `{title, kind}` ; `opts.self`
   * (`{id, name}`, tel qu'il part) ; `opts.selfId` (l'identifiant brut, pour `own` et `mentions_me`) ; `opts.extra`
   * (conversations à redire sans message neuf : un nom appris après coup) ; et les plafonds (`maxMessages`,
   * `maxConversations`, `maxBytes`).
   *
   * Rend `[{body, ids, convs}]`, le plus ancien d'abord. Chaque corps tient sous les plafonds ; un message seul plus
   * gros que tout un corps part seul, et c'est le serveur qui le refusera.
   */
  function batches(queue, opts) {
    const o = opts || {};
    const maxMessages = Math.max(1, o.maxMessages || LIMITS.maxMessages);
    const maxConversations = Math.max(1, o.maxConversations || LIMITS.maxConversations);
    const maxBytes = o.maxBytes || LIMITS.maxBytes;
    const self = { id: T.cut(String((o.self && o.self.id) || ""), 200), name: clean(o.self && o.self.name, 120) };
    const emptyBytes = utf8Length(JSON.stringify({ self: self, conversations: [], messages: [] }));
    const out = [];
    let current = null;

    function open() {
      current = { body: { self: self, conversations: [], messages: [] }, ids: [], convs: [], bytes: emptyBytes,
        known: new Set() };
      out.push(current);
    }
    function entryFor(conv) {
      return wireConversation(conv, o.info ? o.info(conv) : null);
    }
    function fits(bytes, messages, conversations) {
      return current.body.messages.length + messages <= maxMessages
        && current.body.conversations.length + conversations <= maxConversations
        && current.bytes + bytes <= maxBytes;
    }
    function addConversation(conv, entry, bytes) {
      current.body.conversations.push(entry);
      current.known.add(conv);
      current.convs.push(conv);
      current.bytes += bytes;
    }

    const sorted = (queue || []).slice().sort(function (a, b) { return a.time - b.time; });
    for (const m of sorted) {
      if (!current) open();
      const wire = wireMessage(m, o.selfId);
      const bytes = utf8Length(JSON.stringify(wire)) + 1; // la virgule
      let entry = current.known.has(m.conv) ? null : entryFor(m.conv);
      let entryBytes = entry ? utf8Length(JSON.stringify(entry)) + 1 : 0;
      if (!fits(bytes + entryBytes, 1, entry ? 1 : 0) && (current.ids.length || current.convs.length)) {
        open();
        entry = entryFor(m.conv);
        entryBytes = utf8Length(JSON.stringify(entry)) + 1;
      }
      if (entry) addConversation(m.conv, entry, entryBytes);
      current.body.messages.push(wire);
      current.ids.push(m.id);
      current.bytes += bytes;
    }

    for (const conv of o.extra || []) {
      if (out.some(function (b) { return b.known.has(conv); })) continue;
      if (!current) open();
      const entry = entryFor(conv);
      const bytes = utf8Length(JSON.stringify(entry)) + 1;
      if (!fits(bytes, 0, 1)) open();
      addConversation(conv, entry, bytes);
    }

    return out.map(function (b) { return { body: b.body, ids: b.ids, convs: b.convs }; });
  }

  // ── Attendre ───────────────────────────────────────────────────────────────

  /** L'attente demandée par un 429 (`Retry-After` : des secondes ou une date HTTP), bornée ; 60 s si illisible. */
  function retryAfterSeconds(value, now) {
    const s = String(value || "").trim();
    if (/^\d+$/.test(s)) return Math.max(1, Math.min(3600, Number(s)));
    const at = Date.parse(s);
    if (s && isFinite(at)) return Math.max(1, Math.min(3600, Math.ceil((at - now) / 1000)));
    return 60;
  }

  /** L'attente après le n-ième échec de suite : 15 s, doublée à chaque fois, 5 min au plus. */
  function backoffSeconds(failures) {
    return Math.min(300, 15 * Math.pow(2, Math.max(0, (failures || 1) - 1)));
  }

  /**
   * Le compte des erreurs 5xx de suite sur un même lot (`head` : son premier identifiant). Une autre erreur, ou un
   * autre lot, repart de 1. Le service d'arrière-plan écarte le lot à `serverErrorsMax`.
   */
  function serverStrike(prev, status, head) {
    const p = prev || {};
    const same = p.status === status && p.head === head;
    return { status: status, head: head, count: same ? (Number(p.count) || 0) + 1 : 1 };
  }

  // ── L'adresse de Mika ──────────────────────────────────────────────────────

  /**
   * L'adresse du serveur, vérifiée : `{origin, local}`, ou `{error}`. En http seulement sur cette machine
   * (127.0.0.1, localhost) ; ailleurs, https — la clé et les messages ne traversent pas un réseau en clair.
   */
  function serverAddress(raw) {
    let url;
    try {
      url = new URL(String(raw || "").trim());
    } catch (_) {
      return { error: "adresse illisible" };
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return { error: "une adresse http:// ou https://" };
    const local = LOOPBACK.indexOf(url.hostname.toLowerCase()) >= 0;
    if (url.protocol === "http:" && !local) {
      return { error: "hors de cette machine (127.0.0.1, localhost), seulement une adresse https://" };
    }
    return { origin: url.origin, local: local };
  }

  return { LIMITS: LIMITS, admit: admit, pruneSeen: pruneSeen, exclusions: exclusions, isExcluded: isExcluded,
    named: named, held: held, isOwn: isOwn, mentionsSelf: mentionsSelf, mri: mri, isSelfId: isSelfId, clean: clean,
    selfMri: selfMri, wireKind: wireKind, wireMessage: wireMessage, wireConversation: wireConversation,
    utf8Length: utf8Length, batches: batches, retryAfterSeconds: retryAfterSeconds, backoffSeconds: backoffSeconds,
    serverStrike: serverStrike, notePause: notePause, prunePauses: prunePauses, pauseOpen: pauseOpen,
    inPause: inPause, serverAddress: serverAddress };
});
