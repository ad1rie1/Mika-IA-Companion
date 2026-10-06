/*
 * Ce que le script de la page doit savoir lire pour écrire dans Teams : l'authentification que le client utilise
 * pour son service de chat, la conversation ouverte, et la forme d'un message envoyé. Pur : ni DOM, ni réseau, ni
 * horloge — chargé dans la page par l'extension, et par les tests sous Node.
 *
 * Rien de ce qui passe ici ne sort de la page : l'en-tête d'authentification et l'adresse du service restent dans la
 * mémoire du script de la page, qui ne les poste ni au relais, ni au service d'arrière-plan, ni à Mika.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MikaTeamsPage = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const AUTH_HEADERS = ["authentication", "authorization", "x-skypetoken"];
  const CHAT_PATH = /\/v1\/users\/ME\/conversations/i;
  const NAV_KEY = /^tmp\.session\.[0-9a-f-]{36}-mainWindowNavHistory$/i;
  const MAX_HEADER = 16 * 1024;

  function isObject(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  /** Un identifiant de conversation Teams (`19:…`, `8:…`, `48:…`). */
  function isConversationId(s) {
    return typeof s === "string" && /^(19|8|48):\S{3,}$/.test(s);
  }

  function sameConversation(a, b) {
    return Boolean(a) && Boolean(b) && String(a).toLowerCase() === String(b).toLowerCase();
  }

  /** Les en-têtes d'une requête comme paires `[nom, valeur]` : un objet `Headers`, une liste de paires ou un objet. */
  function headerPairs(headers) {
    const out = [];
    if (!headers) return out;
    if (typeof headers.forEach === "function" && typeof headers.get === "function") {
      headers.forEach(function (value, name) { out.push([String(name), String(value)]); });
    } else if (Array.isArray(headers)) {
      for (const pair of headers) {
        if (Array.isArray(pair) && pair.length >= 2) out.push([String(pair[0]), String(pair[1])]);
      }
    } else if (typeof headers === "object") {
      for (const name of Object.keys(headers)) {
        if (headers[name] !== undefined && headers[name] !== null) out.push([name, String(headers[name])]);
      }
    }
    return out;
  }

  function isAuthHeader(name) {
    return AUTH_HEADERS.indexOf(String(name || "").toLowerCase()) >= 0;
  }

  /** Les en-têtes d'authentification d'une requête (noms en minuscules), ou `null` s'il n'y en a aucun. */
  function authFromHeaders(headers) {
    let found = null;
    for (const pair of headerPairs(headers)) {
      const name = pair[0].toLowerCase();
      const value = pair[1].trim();
      if (!isAuthHeader(name) || !value || value.length > MAX_HEADER) continue;
      found = found || {};
      found[name] = value;
    }
    return found;
  }

  /** Une adresse du service de chat (`…/v1/users/ME/conversations…`). */
  function isChatServiceUrl(url) {
    return CHAT_PATH.test(String(url || ""));
  }

  /**
   * La base du service de chat d'une adresse (tout ce qui précède `/v1/users/ME/conversations`), résolue contre la
   * page ; « » si elle n'est pas en https ou n'en est pas une.
   */
  function chatServiceBase(url, pageHref) {
    let absolute;
    try {
      absolute = new URL(String(url || ""), pageHref || undefined);
    } catch (_) {
      return "";
    }
    if (absolute.protocol !== "https:") return "";
    const full = absolute.origin + absolute.pathname;
    const m = CHAT_PATH.exec(full);
    return m ? full.slice(0, m.index) : "";
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /** Le contenu HTML d'un message : le texte échappé, les retours à la ligne en `<br>`. */
  function messageContent(text) {
    return escapeHtml(String(text || "")).replace(/\r\n|\r|\n/g, "<br>");
  }

  /** Un identifiant de message côté client : 19 chiffres, le premier non nul. `random()` rend un nombre de [0, 1[. */
  function clientMessageId(random) {
    let s = String(1 + Math.floor(random() * 9));
    while (s.length < 19) s += String(Math.floor(random() * 10) % 10);
    return s;
  }

  /** Le corps d'un envoi au service de chat. */
  function messageBody(text, selfName, clientId) {
    return { content: messageContent(text), messagetype: "RichText/Html", contenttype: "text",
      clientmessageid: String(clientId), imdisplayname: String(selfName || "") };
  }

  /** L'identifiant du message envoyé, tiré de la réponse (corps JSON, ou en-tête `Location`) ; « » sinon. */
  function messageIdFrom(json, location) {
    if (isObject(json)) {
      for (const k of ["id", "messageId", "OriginalArrivalTime", "originalArrivalTime"]) {
        const v = json[k];
        if ((typeof v === "string" && v) || (typeof v === "number" && isFinite(v))) return String(v).slice(0, 200);
      }
    }
    const m = /\/messages\/([^/?#]+)/.exec(String(location || ""));
    return m ? m[1].slice(0, 200) : "";
  }

  function firstInt(o, keys) {
    for (const k of keys) {
      if (Number.isInteger(o[k])) return o[k];
    }
    return undefined;
  }

  /**
   * L'entrée courante d'un historique de navigation de Teams, quelle que soit sa forme : l'entrée elle-même, une
   * liste (la dernière, ou celle marquée courante), une paire `[entrées, index]`, ou un objet qui porte une liste et
   * un index. `null` si rien ne ressemble à une entrée.
   */
  function navEntry(value, depth) {
    const d = depth || 0;
    if (!value || typeof value !== "object" || d > 4) return null;
    if (isObject(value.activeEntities)) return value;
    if (Array.isArray(value)) {
      if (!value.length) return null;
      if (value.length === 2 && Array.isArray(value[0]) && Number.isInteger(value[1])) {
        return pick(value[0], value[1], d);
      }
      const flagged = value.find(function (e) { return isObject(e) && (e.isCurrent === true || e.isActive === true); });
      return flagged ? navEntry(flagged, d + 1) : pick(value, undefined, d);
    }
    for (const k of ["current", "currentEntry", "activeEntry"]) {
      if (isObject(value[k])) return navEntry(value[k], d + 1);
    }
    for (const k of ["entries", "history", "stack", "items", "navHistory", "navigationHistory"]) {
      if (Array.isArray(value[k])) {
        return pick(value[k], firstInt(value, ["index", "currentIndex", "current", "position", "activeIndex"]), d);
      }
    }
    return null;
  }

  function pick(list, index, depth) {
    if (!list.length) return null;
    const i = Number.isInteger(index) && index >= 0 && index < list.length ? index : list.length - 1;
    return navEntry(list[i], depth + 1);
  }

  /** L'identifiant de la conversation ouverte dans une valeur d'historique de navigation (texte JSON), sinon « ». */
  function activeConversationFromNav(raw) {
    let value;
    try {
      value = typeof raw === "string" ? JSON.parse(raw) : raw;
    } catch (_) {
      return "";
    }
    const entry = navEntry(value, 0);
    const main = entry && isObject(entry.activeEntities) ? entry.activeEntities.mainEntity : null;
    const id = isObject(main) ? main.id : undefined;
    return isConversationId(id) ? id : "";
  }

  /** La conversation ouverte, d'après les paires `[clé, valeur]` du `sessionStorage` de la page ; « » sinon. */
  function activeConversationFromStorage(pairs) {
    for (const pair of pairs || []) {
      if (!Array.isArray(pair) || !NAV_KEY.test(String(pair[0] || ""))) continue;
      const id = activeConversationFromNav(pair[1]);
      if (id) return id;
    }
    return "";
  }

  /** La conversation que nomme une adresse de Teams (`/l/chat/<id>/`, `/conversations/<id>`, `threadId=`…), sinon « ». */
  function conversationFromLocation(href) {
    let s = String(href || "");
    try {
      s = decodeURIComponent(s);
    } catch (_) { /* une adresse mal encodée se lit telle quelle */ }
    const m = /(?:\/l\/chat\/|\/conversations\/|\/chats?\/|[?&#](?:threadId|conversationId)=)((?:19|8|48):[^/?#&\s]+)/i
      .exec(s);
    return m && isConversationId(m[1]) ? m[1] : "";
  }

  return { NAV_KEY: NAV_KEY, isConversationId: isConversationId, sameConversation: sameConversation,
    headerPairs: headerPairs, isAuthHeader: isAuthHeader, authFromHeaders: authFromHeaders,
    isChatServiceUrl: isChatServiceUrl, chatServiceBase: chatServiceBase, escapeHtml: escapeHtml,
    messageContent: messageContent, clientMessageId: clientMessageId, messageBody: messageBody,
    messageIdFrom: messageIdFrom, navEntry: navEntry, activeConversationFromNav: activeConversationFromNav,
    activeConversationFromStorage: activeConversationFromStorage, conversationFromLocation: conversationFromLocation };
});
