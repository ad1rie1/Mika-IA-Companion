/*
 * Reconnaître un message Teams dans ce que le client web reçoit (réponses du service de chat, trames du
 * WebSocket) ou garde (sa base IndexedDB). Pur : ni DOM, ni réseau, ni horloge — chargé dans la page par
 * l'extension, et par les tests sous Node.
 *
 * Rien ici ne dépend d'une adresse précise du client : on parcourt ce qu'on reçoit et on reconnaît les objets qui
 * ont la forme d'un message (un contenu, une date, et un type, un auteur ou une conversation). C'est ce qui permet
 * de survivre à un déplacement d'API ; la forme d'un message du service de chat, elle, est stable depuis Skype.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MikaTeamsExtract = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_DEPTH = 16;
  const MAX_NODES = 40000;
  const MAX_JSON_STRING = 4 * 1024 * 1024;
  const MAX_TEXT = 4000;

  const ID_KEYS = ["id", "clientmessageid", "clientMessageId", "messageId"];
  const CONV_KEYS = ["conversationid", "conversationId", "threadId"];
  const TIME_KEYS = ["originalarrivaltime", "originalArrivalTime", "composetime", "composeTime",
    "clientArrivalTime", "clientarrivaltime", "createdDateTime", "createdTime", "arrivalTime"];
  const TYPE_KEYS = ["messagetype", "messageType"];
  const NAME_KEYS = ["imdisplayname", "imDisplayName", "fromDisplayNameInToken", "displayName", "senderDisplayName"];
  const DELETED_KEYS = ["deletetime", "deleteTime", "deletionTime", "deletedTime", "isDeleted"];

  function first(o, keys) {
    for (const k of keys) {
      const v = o[k];
      if (v !== undefined && v !== null && v !== "") return v;
    }
    return undefined;
  }

  function isObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  /** Une date en millisecondes : texte ISO, millisecondes ou secondes. 0 si illisible. */
  function toMillis(v) {
    if (typeof v === "number" && isFinite(v)) {
      if (v > 1e12) return Math.round(v);
      if (v > 1e9) return Math.round(v * 1000);
      return 0;
    }
    if (typeof v === "string" && v) {
      if (/^\d{10,13}$/.test(v)) return toMillis(Number(v));
      const t = Date.parse(v);
      return isFinite(t) ? t : 0;
    }
    return 0;
  }

  /** L'identifiant d'une conversation dans une adresse du service de chat (`…/conversations/<id>/messages`). */
  function conversationFromUrl(url) {
    const m = /\/conversations\/([^/?#]+)/.exec(String(url || ""));
    if (!m) return "";
    try {
      return decodeURIComponent(m[1]);
    } catch (_) {
      return m[1];
    }
  }

  /** L'identifiant de l'auteur (`8:orgid:<uuid>`), quelle que soit sa forme. */
  function authorIdOf(o) {
    const from = o.from;
    if (typeof from === "string") {
      const i = from.lastIndexOf("/contacts/");
      return (i >= 0 ? from.slice(i + "/contacts/".length) : from).trim();
    }
    if (isObject(from)) {
      const user = isObject(from.user) ? from.user : from;
      if (typeof user.id === "string") return user.id;
    }
    if (typeof o.creator === "string") return o.creator;
    if (typeof o.sender === "string") return o.sender;
    return "";
  }

  function authorNameOf(o) {
    const direct = first(o, NAME_KEYS);
    if (typeof direct === "string") return direct;
    if (isObject(o.from) && isObject(o.from.user) && typeof o.from.user.displayName === "string") {
      return o.from.user.displayName;
    }
    if (isObject(o.creatorProfile) && typeof o.creatorProfile.displayName === "string") {
      return o.creatorProfile.displayName;
    }
    return "";
  }

  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " ", laquo: "«", raquo: "»",
    hellip: "…", rsquo: "’", lsquo: "‘", ldquo: "“", rdquo: "”", eacute: "é", egrave: "è", agrave: "à",
    ecirc: "ê", ccedil: "ç", ocirc: "ô", ucirc: "û", icirc: "î" };

  function decodeEntities(s) {
    return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, function (all, code) {
      if (code[0] === "#") {
        const n = code[1] === "x" || code[1] === "X" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
        try {
          return isFinite(n) ? String.fromCodePoint(n) : all;
        } catch (_) {
          return all;
        }
      }
      const known = ENTITIES[code.toLowerCase()];
      return known !== undefined ? known : all;
    });
  }

  /**
   * Le texte d'un contenu HTML de Teams, sans DOMParser (la page impose les Trusted Types, qui l'interdisent).
   * Une réponse citée devient « … », un emoji en image garde son texte alternatif, les retours à la ligne restent.
   */
  function htmlToText(html) {
    let s = String(html || "");
    if (s.indexOf("<") < 0 && s.indexOf("&") < 0) return s.trim();
    s = s
      .replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, "")
      .replace(/<span[^>]*itemprop=["']?time["']?[^>]*>[\s\S]*?<\/span>/gi, "")
      .replace(/<img\b[^>]*\balt=["']([^"']{0,40})["'][^>]*>/gi, "$1")
      // une réponse citée tient sur une ligne : « Bob on part à 9h ? »
      .replace(/<blockquote\b[^>]*>([\s\S]*?)<\/blockquote>/gi, function (_, inner) {
        return "« " + inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim() + " » ";
      })
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<li\b[^>]*>/gi, "\n• ")
      .replace(/<\/(p|div|li|tr|h[1-6]|pre)>/gi, "\n")
      .replace(/<[^>]+>/g, "");
    s = decodeEntities(s);
    return s
      .split("\n")
      .map(function (line) { return line.replace(/[ \t ]+/g, " ").trim(); })
      .filter(function (line, i, all) { return line || (i > 0 && all[i - 1]); })
      .join("\n")
      .trim();
  }

  /** Les mentions d'un message (`properties.mentions`, en texte JSON ou en liste) : leurs identifiants. */
  function mentionsOf(o) {
    const props = isObject(o.properties) ? o.properties : null;
    let raw = props ? props.mentions : o.mentions;
    if (typeof raw === "string") {
      try {
        raw = JSON.parse(raw);
      } catch (_) {
        return [];
      }
    }
    if (!Array.isArray(raw)) return [];
    const out = [];
    for (const m of raw) {
      if (isObject(m)) {
        const id = m.mri || m.id || (isObject(m.mentioned) && isObject(m.mentioned.user) ? m.mentioned.user.id : "");
        if (typeof id === "string" && id) out.push(id);
      }
    }
    return out;
  }

  function isDeleted(o) {
    if (first(o, DELETED_KEYS)) return true;
    const props = isObject(o.properties) ? o.properties : null;
    return Boolean(props && first(props, DELETED_KEYS));
  }

  /** Un petit condensé stable, pour dédoublonner un message sans identifiant. */
  function hash(s) {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  /**
   * Un message, ou `null` si l'objet n'en a pas la forme ou n'est pas un message lisible (frappe en cours,
   * activité du fil, appel, message supprimé…).
   */
  function normalizeMessage(o, inheritedConv) {
    if (!isObject(o) || typeof o.content !== "string") return null;
    const time = toMillis(first(o, TIME_KEYS));
    if (!time) return null;
    const type = String(first(o, TYPE_KEYS) || "");
    const author = authorNameOf(o);
    let conv = first(o, CONV_KEYS);
    if (typeof conv !== "string" && typeof o.conversationLink === "string") conv = conversationFromUrl(o.conversationLink);
    conv = typeof conv === "string" && conv ? conv : (inheritedConv || "");
    if (!type && !author && !conv) return null;
    if (type && !/^(text|richtext)(\/|$)/i.test(type)) return null;
    if (isDeleted(o)) return null;
    let text;
    if (/^richtext\/media/i.test(type)) {
      const original = /<OriginalName[^>]*\bv=["']([^"']+)["']/i.exec(o.content);
      const title = original ? original[1] : (/<Title>([^<]*)<\/Title>/i.exec(o.content) || [])[1];
      const name = title ? decodeEntities(title).replace(/^Title:\s*/i, "").trim() : "";
      text = "[pièce jointe" + (name ? " : " + name : "") + "]";
    } else {
      text = htmlToText(o.content);
    }
    if (!text) return null;
    if (text.length > MAX_TEXT) text = text.slice(0, MAX_TEXT - 1) + "…";
    const authorId = authorIdOf(o);
    let id = first(o, ID_KEYS);
    id = typeof id === "string" || typeof id === "number" ? String(id) : "";
    if (!id) id = "h" + hash(conv + "|" + time + "|" + authorId + "|" + text);
    return { id: id, conv: conv, author: author, authorId: authorId, time: time, type: type, text: text,
      mentions: mentionsOf(o) };
  }

  /** Une conversation dont on apprend le nom ou la nature (une liste de conversations, une fiche de fil). */
  function normalizeConversation(o) {
    if (!isObject(o) || typeof o.id !== "string" || !/^(19|8|48):/.test(o.id)) return null;
    const props = isObject(o.threadProperties) ? o.threadProperties : {};
    let title = first(props, ["topic", "spaceThreadTopic", "title"]) || first(o, ["topic", "title", "displayName"]);
    if (isObject(o.chatTitle)) title = title || first(o.chatTitle, ["longTitle", "shortTitle"]);
    const threadType = first(props, ["threadType", "productThreadType"]) || first(o, ["threadType", "chatType"]) || "";
    if (!title && !threadType) return null;
    return { id: o.id, title: typeof title === "string" ? title.trim().slice(0, 120) : "",
      threadType: String(threadType) };
  }

  /** La nature d'une conversation : `dm`, `group`, `channel`, `meeting`, `system` ou `other`. */
  function conversationKind(id, threadType) {
    const s = String(id || "");
    const t = String(threadType || "").toLowerCase();
    if (/^48:/.test(s)) return "system";
    if (/@unq\.gbl\.spaces$/i.test(s) || /^8:/.test(s)) return "dm";
    if (t === "meeting" || /^19:meeting_/i.test(s)) return "meeting";
    if (t === "topic" || t === "space" || /@thread\.(tacv2|skype)$/i.test(s)) return "channel";
    if (t === "chat" || /@thread\.v2$/i.test(s)) return "group";
    return "other";
  }

  /** Le JSON que porte une chaîne (une trame `3:::{…}`, un corps encodé dans un corps), sinon `undefined`. */
  function parseEmbedded(s) {
    if (typeof s !== "string" || s.length < 2 || s.length > MAX_JSON_STRING) return undefined;
    let start = 0;
    while (start < s.length && start < 24 && s[start] !== "{" && s[start] !== "[") start++;
    if (s[start] !== "{" && s[start] !== "[") return undefined;
    if (start > 0 && !/^\d*:[^{[]*$/.test(s.slice(0, start))) return undefined;
    const end = s[start] === "{" ? s.lastIndexOf("}") : s.lastIndexOf("]");
    if (end <= start) return undefined;
    try {
      return JSON.parse(s.slice(start, end + 1));
    } catch (_) {
      return undefined;
    }
  }

  /**
   * Parcourt une valeur (réponse, trame, enregistrement) et rend les messages et conversations qu'elle contient.
   * Borné en profondeur et en nombre de nœuds ; une chaîne qui porte du JSON est ouverte (`parseStrings`).
   */
  function extract(value, opts) {
    const options = opts || {};
    const messages = [];
    const conversations = [];
    const seen = new Set();
    const stack = [{ v: value, depth: 0, conv: options.conversation || "" }];
    let nodes = 0;
    while (stack.length && nodes < MAX_NODES) {
      const item = stack.pop();
      let v = item.v;
      nodes++;
      if (typeof v === "string") {
        if (!options.parseStrings) continue;
        v = parseEmbedded(v);
        if (v === undefined) continue;
      }
      if (v === null || typeof v !== "object" || item.depth > MAX_DEPTH || seen.has(v)) continue;
      seen.add(v);
      if (Array.isArray(v)) {
        for (let i = v.length - 1; i >= 0; i--) stack.push({ v: v[i], depth: item.depth + 1, conv: item.conv });
        continue;
      }
      const message = normalizeMessage(v, item.conv);
      if (message) {
        messages.push(message);
        continue;
      }
      const conversation = normalizeConversation(v);
      if (conversation) conversations.push(conversation);
      let conv = item.conv;
      const own = first(v, CONV_KEYS);
      if (typeof own === "string" && /^(19|8|48):/.test(own)) conv = own;
      else if (conversation) conv = conversation.id;
      const keys = Object.keys(v);
      for (let i = keys.length - 1; i >= 0; i--) {
        const child = v[keys[i]];
        if (child !== null && (typeof child === "object" || (options.parseStrings && typeof child === "string"))) {
          stack.push({ v: child, depth: item.depth + 1, conv: conv });
        }
      }
    }
    return { messages: messages, conversations: conversations, truncated: nodes >= MAX_NODES };
  }

  return { extract: extract, normalizeMessage: normalizeMessage, normalizeConversation: normalizeConversation,
    conversationKind: conversationKind, conversationFromUrl: conversationFromUrl, htmlToText: htmlToText,
    parseEmbedded: parseEmbedded, toMillis: toMillis };
});
