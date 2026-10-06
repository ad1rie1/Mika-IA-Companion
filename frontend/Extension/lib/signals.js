/*
 * Ce qui part vers Mika, et sous quelle forme. Pur : l'horloge et l'état sont passés en paramètres — utilisé par le
 * service d'arrière-plan de l'extension, et par les tests sous Node.
 *
 * Mika reçoit les messages par l'entrée de son plugin Teams (`POST /api/teams/inbox`) : 200 messages et 200
 * conversations au plus par envoi, 4000 caractères par texte, 512 Kio par corps. Les lots sont coupés ici, avant de
 * partir ; un 413 malgré tout fait recouper plus petit (le service d'arrière-plan baisse `maxMessages`).
 *
 * Le nom vient de la première version, qui envoyait des signaux d'appareil de 400 caractères ; ce sont maintenant
 * les messages entiers, les siens compris (`own`) : Mika a besoin des deux voix d'un fil.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MikaTeamsSignals = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LIMITS = {
    windowMs: 24 * 3600 * 1000, // au-delà, un message trouvé n'est plus « nouveau »
    maxMessages: 200, // par envoi, le plafond du serveur
    maxConversations: 200,
    maxBytes: 512 * 1024, // le corps entier, en octets UTF-8
    maxText: 4000,
  };

  const KINDS = ["dm", "group", "channel", "meeting", "other"];

  // les formes d'identifiant que le serveur accepte : un seul identifiant hors de ces formes fait refuser tout le lot
  const CONVERSATION_ID = /^\d{1,3}:[A-Za-z0-9@._:=+-]{1,300}$/;
  const MESSAGE_ID = /^[\w.:@=+/-]{1,200}$/;

  function clean(s, max) {
    let t = String(s || "").replace(/[\u0000-\u001f\u007f​-‏‪-‮⁦-⁩]+/g, " ")
      .replace(/\s+/g, " ").trim();
    if (max && t.length > max) t = t.slice(0, Math.max(0, max - 1)).trimEnd() + "…";
    return t;
  }

  function isOwn(msg, selfId) {
    return Boolean(selfId) && String(msg.authorId || "").toLowerCase().indexOf(String(selfId).toLowerCase()) >= 0;
  }

  function mentionsSelf(msg, selfId) {
    if (!selfId) return false;
    const me = String(selfId).toLowerCase();
    return (msg.mentions || []).some(function (m) { return String(m).toLowerCase().indexOf(me) >= 0; });
  }

  /** Les lignes d'exclusion (un morceau du nom ou de l'identifiant d'une conversation), nettoyées. */
  function exclusions(text) {
    return String(text || "").split("\n").map(function (l) { return l.trim().toLowerCase(); })
      .filter(function (l) { return l.length > 0; });
  }

  /** Une conversation que l'utilisateur a exclue (un morceau de son nom ou de son identifiant). */
  function isExcluded(conv, title, exclude) {
    const hay = (String(conv || "") + "\n" + String(title || "")).toLowerCase();
    return (exclude || []).some(function (l) { return hay.indexOf(l) >= 0; });
  }

  /**
   * Pourquoi un message ne part pas (« » : il part). `ctx` : `now`, `armedAt`, `seen` (id → date), `paused`,
   * `title`, `kind`, `exclude` (lignes), `windowMs`. Ses propres messages partent comme les autres.
   */
  function admit(msg, ctx) {
    if (!msg || !msg.id || !msg.text) return "vide";
    if (ctx.seen && Object.prototype.hasOwnProperty.call(ctx.seen, msg.id)) return "déjà vu";
    // en pause, rien n'est mis de côté pour plus tard : ce qui arrive pendant la pause ne partira jamais
    if (ctx.paused) return "en pause";
    if (ctx.kind === "system") return "système";
    // un message dont on ne sait pas la conversation ferait refuser tout son lot
    if (!msg.conv) return "sans conversation";
    if (!CONVERSATION_ID.test(msg.conv) || !MESSAGE_ID.test(String(msg.id))) return "identifiant illisible";
    if (msg.time < (ctx.armedAt || 0)) return "avant l'activation";
    if (msg.time < ctx.now - (ctx.windowMs || LIMITS.windowMs)) return "ancien";
    if (isExcluded(msg.conv, ctx.title, ctx.exclude)) return "exclue";
    return "";
  }

  /** Les identifiants déjà vus qu'il faut encore garder : ceux de la fenêtre, plus une marge. */
  function pruneSeen(seen, now, windowMs) {
    const keep = {};
    const limit = now - (windowMs || LIMITS.windowMs) - 2 * 3600 * 1000;
    for (const id in seen) {
      if (Object.prototype.hasOwnProperty.call(seen, id) && seen[id] >= limit) keep[id] = seen[id];
    }
    return keep;
  }

  /** L'identifiant de soi tel que le serveur l'attend : `8:orgid:<uuid>`, ou « » si inconnu. */
  function selfMri(selfId) {
    const s = String(selfId || "").trim();
    if (!s) return "";
    return s.indexOf(":") >= 0 ? s : "8:orgid:" + s.toLowerCase();
  }

  /** La nature d'une conversation dans le vocabulaire du serveur (`system` n'y part jamais). */
  function wireKind(kind) {
    return KINDS.indexOf(kind) >= 0 ? kind : "other";
  }

  /** Un message de la file, tel qu'il part. */
  function wireMessage(m, selfId) {
    return {
      id: String(m.id).slice(0, 200),
      conv: String(m.conv || "").slice(0, 300),
      author: clean(m.author, 120),
      author_id: String(m.authorId || "").slice(0, 200),
      time: Number(m.time) || 0,
      text: String(m.text || "").slice(0, LIMITS.maxText),
      own: isOwn(m, selfId),
      mentions_me: mentionsSelf(m, selfId),
    };
  }

  /** Une conversation, telle qu'elle part (`info` : `{title, kind}`). */
  function wireConversation(id, info) {
    const i = info || {};
    return { id: String(id).slice(0, 300), title: clean(i.title, 120), kind: wireKind(i.kind) };
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
    const self = { id: String((o.self && o.self.id) || ""), name: clean(o.self && o.self.name, 120) };
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

  return { LIMITS: LIMITS, admit: admit, pruneSeen: pruneSeen, exclusions: exclusions, isExcluded: isExcluded,
    isOwn: isOwn, mentionsSelf: mentionsSelf, clean: clean, selfMri: selfMri, wireKind: wireKind,
    wireMessage: wireMessage, wireConversation: wireConversation, utf8Length: utf8Length, batches: batches,
    retryAfterSeconds: retryAfterSeconds, backoffSeconds: backoffSeconds };
});
