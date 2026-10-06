/*
 * Ce qui part vers Mika, et sous quelle forme. Pur : l'horloge et l'état sont passés en paramètres — utilisé par le
 * service d'arrière-plan de l'extension, et par les tests sous Node.
 *
 * Mika reçoit des signaux d'appareil (`POST /api/perceptions`) : 400 caractères au plus, 30 par minute et par
 * appareil côté serveur. Les messages d'une même conversation qui attendent ensemble partent donc dans un seul
 * signal ; on reste à 20 signaux par minute.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MikaTeamsSignals = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LIMITS = {
    maxChars: 400, // le plafond du serveur pour un signal
    perMessageChars: 260, // un long message n'occupe pas tout un signal
    perMinute: 20, // sous les 30 par minute et par appareil du serveur
    windowMs: 24 * 3600 * 1000, // au-delà, un message trouvé n'est plus « nouveau »
  };

  const PERTINENCE = { dm: 0.6, group: 0.45, channel: 0.35, meeting: 0.35, other: 0.4 };
  const MENTION_BONUS = 0.2;

  const KIND_LABEL = {
    dm: "discussion avec",
    group: "groupe",
    channel: "canal",
    meeting: "réunion",
    other: "conversation",
  };

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
   * `title`, `kind`, `exclude` (lignes), `skipOwn`, `selfId`, `windowMs`.
   */
  function admit(msg, ctx) {
    if (!msg || !msg.id || !msg.text) return "vide";
    if (ctx.seen && Object.prototype.hasOwnProperty.call(ctx.seen, msg.id)) return "déjà vu";
    // en pause, rien n'est mis de côté pour plus tard : ce qui arrive pendant la pause ne partira jamais
    if (ctx.paused) return "en pause";
    if (ctx.kind === "system") return "système";
    if (msg.time < (ctx.armedAt || 0)) return "avant l'activation";
    if (msg.time < ctx.now - (ctx.windowMs || LIMITS.windowMs)) return "ancien";
    if (isExcluded(msg.conv, ctx.title, ctx.exclude)) return "exclue";
    if (ctx.skipOwn && isOwn(msg, ctx.selfId)) return "moi";
    return "";
  }

  /** Le nom d'une conversation : celui que Teams lui donne, sinon, en tête-à-tête, l'autre personne. */
  function titleFor(conv, known, msgs, selfId) {
    if (known && known.title) return clean(known.title, 60);
    const counts = new Map();
    for (const m of msgs || []) {
      if (m.conv === conv && m.author && !isOwn(m, selfId)) counts.set(m.author, (counts.get(m.author) || 0) + 1);
    }
    let best = "";
    let n = 0;
    counts.forEach(function (c, name) { if (c > n) { best = name; n = c; } });
    if (best) return clean(best, 60);
    return known && known.kind === "dm" ? "quelqu'un" : "sans nom";
  }

  function header(kind, title) {
    const label = KIND_LABEL[kind] || KIND_LABEL.other;
    const name = clean(String(title || "").replace(/[«»]/g, " "), 60);
    return kind === "dm" ? "Teams, " + label + " " + name : "Teams, " + label + " « " + name + " »";
  }

  function pertinenceFor(kind, mentioned, table) {
    const base = (table && typeof table[kind] === "number") ? table[kind] : (PERTINENCE[kind] || PERTINENCE.other);
    const value = Math.min(1, Math.max(0, base + (mentioned ? MENTION_BONUS : 0)));
    return Math.round(value * 100) / 100;
  }

  /**
   * Les signaux d'une file : un par conversation tant que ses messages tiennent dans 400 caractères, plus sinon.
   * `info(conv)` rend `{kind, title}`. Rend `[{conv, ids, text, time, kind, mentioned}]`, le plus ancien d'abord.
   */
  function compose(queue, info, opts) {
    const o = opts || {};
    const maxChars = o.maxChars || LIMITS.maxChars;
    const perMessage = o.perMessageChars || LIMITS.perMessageChars;
    const groups = new Map();
    const sorted = (queue || []).slice().sort(function (a, b) { return a.time - b.time; });
    for (const m of sorted) {
      if (!groups.has(m.conv)) groups.set(m.conv, []);
      groups.get(m.conv).push(m);
    }
    const out = [];
    groups.forEach(function (msgs, conv) {
      const meta = info(conv) || {};
      const kind = meta.kind || "other";
      const head = header(kind, meta.title || "sans nom") + " — ";
      let current = null;
      let lastAuthor = null;
      function open() {
        current = { conv: conv, ids: [], text: head, time: 0, kind: kind, mentioned: false };
        lastAuthor = null;
        out.push(current);
      }
      for (const m of msgs) {
        if (!current) open();
        const body = clean(m.text, perMessage);
        const who = clean(m.author || "quelqu'un", 40);
        let part = (lastAuthor === who ? " / " : (current.ids.length ? " / " + who + " : " : who + " : ")) + body;
        if (current.text.length + part.length > maxChars) {
          if (current.ids.length) {
            open();
            part = who + " : " + body;
          }
          if (current.text.length + part.length > maxChars) {
            part = clean(part, maxChars - current.text.length);
          }
        }
        current.text += part;
        current.ids.push(m.id);
        current.time = current.time || m.time;
        current.mentioned = current.mentioned || Boolean(m.mentionsSelf);
        lastAuthor = who;
      }
    });
    return out.sort(function (a, b) { return a.time - b.time; });
  }

  /** Une place dans la fenêtre d'une minute : les dates gardées, et s'il en reste une. */
  function takeSlot(sentTimes, now, perMinute) {
    const recent = (sentTimes || []).filter(function (t) { return now - t < 60000; });
    return { recent: recent, free: recent.length < (perMinute || LIMITS.perMinute) };
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

  return { LIMITS: LIMITS, PERTINENCE: PERTINENCE, admit: admit, titleFor: titleFor, header: header,
    compose: compose, pertinenceFor: pertinenceFor, takeSlot: takeSlot, pruneSeen: pruneSeen,
    exclusions: exclusions, isExcluded: isExcluded, isOwn: isOwn, mentionsSelf: mentionsSelf, clean: clean };
});
