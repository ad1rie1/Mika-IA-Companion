/*
 * Ce que le script de la page doit savoir lire pour écrire dans Teams : l'authentification que le client utilise
 * pour son service de chat, la conversation ouverte, la forme d'un message envoyé, et la commande d'envoi que la page
 * passe au worker de Teams (ADR 0301). Pur : ni DOM, ni réseau, ni horloge — chargé dans la page par l'extension, et
 * par les tests sous Node.
 *
 * Rien de ce qui passe ici ne sort de la page : l'en-tête d'authentification et l'adresse du service restent dans la
 * mémoire du script de la page, qui ne les poste ni au relais, ni au service d'arrière-plan, ni à Mika.
 */
(function (root, factory) {
  const node = typeof module === "object" && module && module.exports && typeof require === "function";
  const api = factory(node ? require("./text.js") : root.MikaTeamsText);
  if (node) module.exports = api;
  else root.MikaTeamsPage = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (T) {
  "use strict";

  const AUTH_HEADERS = ["authentication", "authorization", "x-skypetoken"];
  const CHAT_PATH = /\/v1\/users\/ME\/conversations/i;
  const NAV_KEY = /^tmp\.session\.[0-9a-f-]{36}-mainWindowNavHistory$/i;
  const MAX_HEADER = 16 * 1024;
  // les domaines où vit le service de chat de Teams : l'authentification n'est jamais renvoyée ailleurs
  const CHAT_DOMAINS = ["teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com", "skype.com",
    "teams.microsoft.us"];

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

  /** Un hôte de Microsoft où le service de chat peut vivre (le domaine lui-même ou l'un de ses sous-domaines). */
  function isChatServiceHost(host) {
    const h = String(host || "").toLowerCase().replace(/\.$/, "");
    return CHAT_DOMAINS.some(function (d) { return h === d || h.slice(-(d.length + 1)) === "." + d; });
  }

  /**
   * La base du service de chat d'une adresse (tout ce qui précède `/v1/users/ME/conversations`), résolue contre la
   * page ; « » si elle n'est pas en https, pas sur un hôte de Teams, ou n'en est pas une.
   */
  function chatServiceBase(url, pageHref) {
    let absolute;
    try {
      absolute = new URL(String(url || ""), pageHref || undefined);
    } catch (_) {
      return "";
    }
    if (absolute.protocol !== "https:" || !isChatServiceHost(absolute.hostname)) return "";
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

  /**
   * L'identifiant de message côté client d'un élément de la boîte d'envoi : 19 chiffres, le premier non nul, tirés
   * d'un condensé (FNV-1a sur 64 bits) de l'identifiant de l'élément — le même à chaque tentative, d'un onglet ou d'un
   * navigateur à l'autre.
   */
  function clientMessageIdFor(itemId) {
    const s = String(itemId || "");
    let h = 0xcbf29ce484222325n;
    for (let i = 0; i < s.length; i++) {
      h ^= BigInt(s.charCodeAt(i));
      h = (h * 0x100000001b3n) & 0xffffffffffffffffn;
    }
    return (1000000000000000000n + (h % 9000000000000000000n)).toString();
  }

  /**
   * Ce que dit le statut de la réponse du service de chat à un envoi : `sent` (2xx), `auth` (401, 403 :
   * l'authentification vue est périmée, rien n'est parti), `failed` (une autre 4xx, sauf 408 et 429 : refusé, rien
   * n'est parti) ou `uncertain` (5xx, 408, 429, et tout le reste : peut-être parti).
   */
  function chatSendOutcome(status) {
    const s = Number(status) || 0;
    if (s >= 200 && s < 300) return "sent";
    if (s === 401 || s === 403) return "auth";
    if (s >= 400 && s < 500 && s !== 408 && s !== 429) return "failed";
    return "uncertain";
  }

  /** Le corps d'un envoi au service de chat. */
  function messageBody(text, selfName, clientId, quote) {
    return { content: quoteHtml(quote) + messageContent(text), messagetype: "RichText/Html", contenttype: "text",
      clientmessageid: String(clientId), imdisplayname: String(selfName || "") };
  }

  /**
   * Le bloc d'une citation (ADR 0305), tel que Teams l'écrit avant le texte quand on « cite » un message (relevé le
   * 2026-11-22, essai 8 chez Albert) : le message (son identifiant de service), son auteur (identifiant et nom), son
   * heure, un extrait. Teams montre le message cité d'après son identifiant ; « » sans citation valable.
   */
  function quoteHtml(q) {
    const quote = T.quoteOf(q);
    if (!quote) return "";
    return '<blockquote itemtype="http://schema.skype.com/Reply" itemid="' + quote.message + '">'
      + '<strong itemprop="mri" itemid="' + escapeHtml(quote.author_id) + '">' + escapeHtml(quote.author) + "</strong>"
      + '<span itemprop="time" itemid="' + quote.at + '"></span>'
      + '<p itemprop="preview">' + escapeHtml(quote.preview) + "</p></blockquote>";
  }

  /** L'identifiant du message envoyé, tiré de la réponse (corps JSON, ou en-tête `Location`) ; « » sinon. */
  function messageIdFrom(json, location) {
    if (isObject(json)) {
      for (const k of ["id", "messageId", "OriginalArrivalTime", "originalArrivalTime"]) {
        const v = json[k];
        if ((typeof v === "string" && v) || (typeof v === "number" && isFinite(v))) return T.cut(String(v), 200);
      }
    }
    const m = /\/messages\/([^/?#]+)/.exec(String(location || ""));
    return m ? T.cut(m[1], 200) : "";
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

  // ── La synchro ciblée de la base locale (ADR 0251) ─────────────────────────
  //
  // Teams range chaque conversation dans le magasin `conversations` (sa fiche, qui change quand un message y arrive,
  // y est retouché ou retiré) et ses fils dans `replychains`, indexés par [conversation, heure de dernière livraison].
  // Un curseur par conversation (`{w, m}` : le plus tard livré qu'on ait lu, la fiche vue) dit ce qu'il reste à lire.

  /** La marque d'une fiche de conversation : elle change quand un message y arrive, y est retouché ou retiré. */
  function conversationMarker(record) {
    if (!isObject(record)) return "";
    return [record.version, record.threadVersion, record.lastUpdatedMessageVersion, record.lastMessageTimeUtc,
      record.lastUpdatedMessageId].map(function (v) { return v === undefined || v === null ? "" : String(v); })
      .join("|");
  }

  /**
   * Depuis quand relire les fils d'une conversation (ms) ; `null` : sa fiche n'a pas bougé depuis le curseur. Une
   * conversation connue repart de son curseur moins `overlapMs` (un fil rangé un peu après sa voisine) ; une inconnue,
   * de la fenêtre `windowMs` ; l'historique, du début (0).
   */
  function syncSince(marker, cursor, now, opts) {
    if (opts.history) return 0;
    if (cursor && marker && cursor.m === marker) return null;
    if (cursor && Number(cursor.w) > 0) return Math.max(0, Number(cursor.w) - opts.overlapMs);
    return Math.max(0, now - opts.windowMs);
  }

  /** Les fils lus ont rattrapé la fiche : le plus tard livré qu'on ait lu atteint son dernier message (à `slackMs`). */
  function caughtUp(record, latest, slackMs) {
    const last = isObject(record) ? Number(record.lastMessageTimeUtc) || 0 : 0;
    return !last || (Number(latest) || 0) >= last - slackMs;
  }

  /** Le curseur après une relecture : jamais en arrière ; la marque, seulement quand les fils ont suivi la fiche. */
  function advanceCursor(cursor, since, latest, marker) {
    const before = cursor ? Number(cursor.w) || 0 : 0;
    return { w: Math.max(before, cursor ? 0 : Number(since) || 0, Number(latest) || 0), m: String(marker || "") };
  }

  // ── Les photos de profil (ADR 0300) ──────────────────────────────────────────
  //
  // Teams affiche un avatar par `<base>/profilepicturev2/<personne>?displayname=…&size=…&avatarETag=…`, la base étant
  // `https://<hôte de Teams>/api/mt/part/<région>/beta/users/<soi>`. On lit la base sur un avatar déjà dans la page, et
  // l'on n'ouvre jamais que cette adresse, construite ici : la photo d'une personne de Teams, en 64 px.

  const AVATAR_BASE = /^(https:\/\/(?:teams\.cloud\.microsoft|teams\.microsoft\.com))\/api\/mt\/part\/([a-z0-9-]{1,40})\/beta\/users\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\//i;
  const PHOTO_URL = /^https:\/\/(?:teams\.cloud\.microsoft|teams\.microsoft\.com)\/api\/mt\/part\/[a-z0-9-]{1,40}\/beta\/users\/[0-9a-f-]{36}\/profilepicturev2\/(?:8:orgid:[0-9a-f-]{36}|8:live:[a-z0-9._-]{1,80}|8:teamsvisitor:[0-9a-f-]{32,36})\?displayname=[^&#]*&size=HR64x64&avatarETag=[^&#]+$/;
  const PERSON = /^(8:orgid:[0-9a-f-]{36}|8:live:[a-z0-9._-]{1,80}|8:teamsvisitor:[0-9a-f-]{32,36})$/;
  const ETAG = /^[A-Za-z0-9._:+/=-]{1,200}$/;

  /**
   * La base des avatars, lue sur l'adresse d'un avatar affiché (`src`) : seulement sur l'origine de la page (ses
   * cookies) et, si on la connaît, pour soi (`self`, l'uuid) — jamais l'avatar d'un autre compte. « » sinon.
   */
  function avatarBase(src, origin, self) {
    const m = AVATAR_BASE.exec(String(src || ""));
    if (!m || m[1].toLowerCase() !== String(origin || "").toLowerCase()) return "";
    if (self && m[3].toLowerCase() !== String(self).toLowerCase()) return "";
    return m[1] + "/api/mt/part/" + m[2] + "/beta/users/" + m[3].toLowerCase();
  }

  /** L'adresse de la photo d'une personne (64 px), construite sur la base ; « » si elle n'a pas la forme attendue. */
  function photoUrl(base, person, name, etag) {
    if (!PERSON.test(String(person || "")) || !ETAG.test(String(etag || ""))) return "";
    const url = String(base || "") + "/profilepicturev2/" + person + "?displayname=" + encodeURIComponent(name || "")
      + "&size=HR64x64&avatarETag=" + encodeURIComponent(etag);
    return PHOTO_URL.test(url) ? url : "";
  }

  // ── L'envoi par le worker de Teams (ADR 0301) ────────────────────────────────
  //
  // La page passe à son worker des commandes GraphQL en texte JSON : `{requestId: "m-<n>", rendererId, windowId,
  // payload: {graphqlQuery, variables}, operationName, type: "graphql", …}` (`q-` requête, `m-` mutation, `s-`
  // abonnement, un seul compteur). Envoyer, c'est `mutation autoSendMessage`. D'un vrai envoi de la page, on garde un
  // **modèle** de cette commande, sans rien de ce message : ni texte, ni conversation, ni identifiants, ni mentions ;
  // on le rejoue pour une autre conversation, texte, identifiants et heure refaits, et le worker envoie lui-même, avec
  // sa propre connexion. Le numéro de requête, `rendererId` et `windowId` viennent toujours de la page vivante, jamais
  // du modèle. Seulement pour un tête-à-tête ou un groupe : un canal ou une réunion passent par la zone de saisie.

  const SEND_OPERATION = "autoSendMessage";
  const ONE_TO_ONE = /^19:[^\s@/"]{1,200}@unq\.gbl\.spaces$/i;
  const GROUP_CHAT = /^19:(?!meeting_)[^\s@/"]{1,200}@thread\.v2$/i;
  // dans le modèle, la conversation (là où elle apparaît encore, la file d'attente) et les identifiants d'un message
  // deviennent ces marques, que la construction remplace
  const SLOT = { conversation: "{mika:conversation}", client: "{mika:client}", correlation: "{mika:correlation}",
    text: "{mika:text}" };
  const TEMPLATE_MAX_CHARS = 64 * 1024;
  // notre numéro de requête, loin au-dessus du compteur : jamais celui d'une requête de la page en cours
  const REQUEST_GAP = 1000;
  const VARS = "payload.variables";
  const MESSAGE = VARS + ".message";
  const COMPUTED = MESSAGE + ".computed";
  // les valeurs que la commande tient de Teams lui-même : jamais prises pour le texte du message
  const FIXED_PATHS = ["operationName", "type", "payload.graphqlQuery", "payload.operationName", VARS + ".action",
    MESSAGE + ".messageType", MESSAGE + ".importance", MESSAGE + ".sendPipelineThreadType",
    VARS + ".offlineActionOptions.actionType"];
  // ce qu'un message ordinaire n'a pas — une citation, un transfert, une pièce jointe, une carte, une retouche… — :
  // rejoué, il repartirait avec chaque envoi. Un modèle qui en porte un est refusé. Un mot de la clé, au début ou
  // après une minuscule (« files », « hasFiles », « quotedMessage », « isEdited » ; pas « senderProfile »).
  const SPECIAL_WORDS = ["quot", "repl", "forward", "file", "attach", "upload", "card", "image", "media", "ams",
    "schedul", "edit", "loop", "fluid"];
  const SPECIAL_KEY = new RegExp("^(?:" + SPECIAL_WORDS.join("|") + ")|[a-z0-9](?:"
    + SPECIAL_WORDS.map(function (w) { return w[0].toUpperCase() + w.slice(1); }).join("|") + ")");
  const CHAT_ID_IN = /19:[^\s"\\]{1,200}@(?:thread\.[a-z0-9]+|unq\.gbl\.spaces)/i;
  const HEAD_ID = /"requestId"\s*:\s*"([a-z]{1,3})-(\d{1,15})"/;
  const HEAD_RENDERER = /"rendererId"\s*:\s*("(?:[^"\\]|\\.){0,200}"|-?\d{1,20})/;
  const HEAD_WINDOW = /"windowId"\s*:\s*("(?:[^"\\]|\\.){0,200}"|-?\d{1,20})/;
  const HEAD_OPERATION = /"operationName"\s*:\s*"([A-Za-z0-9_]{1,100})"/;
  const REPLY_FAILED =
    /^(error|errored|failure|failed|fail|rejected|refused|denied|unauthorized|forbidden|cancell?ed|aborted)$/i;
  const OPEN_RUN = /^(?:<[a-z][a-z0-9-]{0,40}(?:\s[^<>]{0,200})?>){1,6}/i;
  const PLAIN_INNER = /^(?:[^<>]|<br\s*\/?>)*$/i;
  const DEFAULT_SHAPE = { open: "<p>", close: "</p>", breaks: "br" };

  /** Une conversation où l'on peut envoyer par le worker : un tête-à-tête ou un groupe (ni canal, ni réunion). */
  function workerSendable(conversation) {
    const c = String(conversation || "");
    return ONE_TO_ONE.test(c) || GROUP_CHAT.test(c);
  }

  /** Un tête-à-tête (`…@unq.gbl.spaces`), que Teams appelle `isBilateralChat`. */
  function isBilateralChat(conversation) {
    return /@unq\.gbl\.spaces$/i.test(String(conversation || ""));
  }

  /** Une valeur de `rendererId` ou de `windowId` : un texte ou un nombre. */
  function isLiveId(v) {
    return (typeof v === "string" && v.length <= 200) || (typeof v === "number" && isFinite(v));
  }

  /**
   * Le début d'une commande que la page passe au worker (texte JSON), lu sans la décoder : la sorte et le numéro de
   * sa requête, `rendererId`, `windowId`, son opération. `null` : pas une commande.
   */
  function workerCommandHead(data) {
    if (typeof data !== "string") return null;
    const id = HEAD_ID.exec(data);
    if (!id) return null;
    const live = function (re) {
      const m = re.exec(data);
      if (!m) return undefined;
      try {
        const v = JSON.parse(m[1]);
        return isLiveId(v) ? v : undefined;
      } catch (_) {
        return undefined;
      }
    };
    const op = HEAD_OPERATION.exec(data);
    return { prefix: id[1], number: Number(id[2]), rendererId: live(HEAD_RENDERER), windowId: live(HEAD_WINDOW),
      operation: op ? op[1] : "" };
  }

  /** Le numéro de notre requête : loin au-dessus du compteur de la page, au-dessus de notre dernière. */
  function nextRequestNumber(highest, lastOwn) {
    return Math.max((Number(highest) || 0) + REQUEST_GAP, (Number(lastOwn) || 0) + 1);
  }

  /** Le texte d'un contenu HTML de Teams : ses sauts de ligne et ses paragraphes en retours, ses entités décodées. */
  function htmlText(html) {
    const named = { amp: "&", lt: "<", gt: ">", quot: "\"", apos: "'", nbsp: " " };
    return String(html || "").replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>\s*<p[^>]*>/gi, "\n").replace(/<[^>]*>/g, "")
      .replace(/&(#x[0-9a-f]{1,6}|#\d{1,7}|[a-z]{2,8});/gi, function (all, name) {
        if (name[0] === "#") {
          const code = name[1] === "x" || name[1] === "X" ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
          return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : all;
        }
        return Object.prototype.hasOwnProperty.call(named, name.toLowerCase()) ? named[name.toLowerCase()] : all;
      }).trim();
  }

  /**
   * La forme d'un message envoyé par Teams lui-même, lue sur son contenu : les balises autour du texte (« <p> »…
   * « </p> », ou « <p><semantic-object> »… « </semantic-object></p> »), sans attribut qui porte un identifiant, et
   * comment il sépare les lignes (`br` : des sauts de ligne dans un paragraphe ; `p` : un paragraphe par ligne). Un
   * contenu d'une autre forme (une mention, un emoji, une image…) donne la forme par défaut : `<p>`, des `<br>`.
   */
  function learnShape(content) {
    const c = String(content || "");
    const head = OPEN_RUN.exec(c);
    if (!head) return Object.assign({}, DEFAULT_SHAPE);
    const open = head[0];
    const names = [];
    open.replace(/<([a-z][a-z0-9-]*)/gi, function (all, name) {
      names.push(name.toLowerCase());
      return all;
    });
    const close = names.slice().reverse().map(function (n) { return "</" + n + ">"; }).join("");
    if (c.length < open.length + close.length || c.slice(-close.length).toLowerCase() !== close) {
      return Object.assign({}, DEFAULT_SHAPE);
    }
    const realClose = c.slice(-close.length);
    const parts = c.slice(open.length, c.length - close.length).split(realClose + open);
    if (!parts.every(function (p) { return PLAIN_INNER.test(p); })) return Object.assign({}, DEFAULT_SHAPE);
    // pas d'attribut qui agisse ou qui porte un identifiant (un nombre, une conversation, une personne)
    if (open.length > 300 || /\son[a-z]+\s*=|javascript:|\d{6,}|\b(?:19|8|48):/i.test(open)) {
      return Object.assign({}, DEFAULT_SHAPE);
    }
    return { open: open, close: realClose, breaks: parts.length > 1 ? "p" : "br" };
  }

  /** Le contenu HTML d'un message envoyé par le worker : le texte échappé, ligne à ligne, dans la forme du modèle. */
  function workerContent(text, shape) {
    const s = isObject(shape) ? shape : {};
    const open = typeof s.open === "string" && s.open ? s.open : DEFAULT_SHAPE.open;
    const close = typeof s.close === "string" && s.close ? s.close : DEFAULT_SHAPE.close;
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n").map(escapeHtml);
    if (s.breaks === "p") return lines.map(function (l) { return open + (l || "&nbsp;") + close; }).join("");
    return open + lines.join("<br>") + close;
  }

  function isEmptyValue(v) {
    return v === null || v === undefined || v === false || v === "" || v === 0
      || (Array.isArray(v) && !v.length) || (isObject(v) && !Object.keys(v).length);
  }

  // une option de la requête, pas une donnée du message : « includeRepliesSummary » (ce que la réponse doit contenir)
  // est dans chaque envoi de Teams, et le mot « Repl » le faisait prendre pour une réponse citée (le 2026-11-22 : aucun
  // modèle n'avait jamais été appris)
  const QUERY_FLAG = /^include[A-Z]/;

  /** Les clés « spéciales » (citation, pièce jointe…) qui portent quelque chose ; une option de la requête (`include…`,
   *  un booléen) n'en est pas une. */
  function specialKeys(o, skip) {
    if (!isObject(o)) return [];
    return Object.keys(o).filter(function (k) {
      return skip.indexOf(k) < 0 && SPECIAL_KEY.test(k) && !isEmptyValue(o[k])
        && !(QUERY_FLAG.test(k) && typeof o[k] === "boolean");
    });
  }

  /**
   * La forme d'une commande, pour le diagnostic d'un modèle écarté : chaque chemin et le type de sa valeur
   * (`s` texte, `n` nombre, `b` booléen, `0` vide), jamais une valeur — la requête GraphQL non plus.
   */
  function commandShape(command, max) {
    const out = [];
    const walk = function (v, path, depth) {
      if (depth > 12 || out.length > 200) return;
      if (Array.isArray(v)) {
        if (!v.length) out.push(path + "[]");
        else walk(v[0], path + "[" + v.length + "]", depth + 1);
      } else if (isObject(v)) {
        const keys = Object.keys(v);
        if (!keys.length) out.push(path + "{}");
        for (const k of keys) walk(v[k], path ? path + "." + k : k, depth + 1);
      } else {
        const t = v === null || v === undefined ? "0" : typeof v === "string" ? (v ? "s" : "0")
          : typeof v === "number" ? "n" : typeof v === "boolean" ? "b" : "?";
        out.push(path + ":" + t);
      }
    };
    walk(command, "", 0);
    return T.cut(out.join(" "), max || 2000);
  }

  /** Chaque texte d'une valeur passé par `fn(texte, chemin)` ; `null` : trop profonde, ou une clé qui ne va pas. */
  function mapStrings(value, fn, path, depth, keyOk) {
    if (depth > 24) return null;
    if (typeof value === "string") return fn(value, path);
    if (Array.isArray(value)) {
      const out = [];
      for (const v of value) {
        const m = mapStrings(v, fn, path + "[]", depth + 1, keyOk);
        if (m === null && v !== null) return null;
        out.push(m);
      }
      return out;
    }
    if (isObject(value)) {
      const out = {};
      for (const k of Object.keys(value)) {
        if (keyOk && !keyOk(k)) return null;
        const m = mapStrings(value[k], fn, path ? path + "." + k : k, depth + 1, keyOk);
        if (m === null && value[k] !== null) return null;
        out[k] = m;
      }
      return out;
    }
    return value === undefined ? null : value;
  }

  /**
   * Le modèle d'envoi tiré d'une commande `autoSendMessage` que la page a passée au worker (décodée) :
   * `{template: {command, open, close, breaks}, bilateral}`, ou `{template: null, reason}`. Le modèle ne garde rien de
   * ce message : `content` vide, mentions vidées (et tout ce que Teams en a calculé), conversation et identifiants
   * effacés (la file d'attente garde son préfixe, `<préfixe>_{mika:conversation}`), ni `requestId`, ni `rendererId`,
   * ni `windowId`. Refusé : un autre geste qu'une création, un canal ou une réunion, une citation, un transfert, une
   * pièce jointe, ou une trace du message qui resterait.
   */
  function workerSendTemplate(command) {
    const refuse = function (reason) { return { template: null, reason: reason }; };
    if (!isObject(command) || command.operationName !== SEND_OPERATION || command.type !== "graphql") {
      return refuse("pas une commande d'envoi");
    }
    const payload = command.payload;
    const v = isObject(payload) ? payload.variables : null;
    const m = isObject(v) ? v.message : null;
    if (!isObject(payload) || typeof payload.graphqlQuery !== "string"
      || payload.graphqlQuery.indexOf(SEND_OPERATION) < 0 || !isObject(v) || !isObject(m)) {
      return refuse("forme de commande inattendue");
    }
    if (v.action !== "Create") return refuse("pas la création d'un message");
    const conv = typeof v.convId === "string" ? v.convId : "";
    if (!workerSendable(conv)) return refuse("ni un tête-à-tête ni un groupe");
    if (typeof v.originalConvId === "string" && v.originalConvId && v.originalConvId !== conv) {
      return refuse("conversation d'origine différente");
    }
    // toutes les clés en cause d'un coup : une seule de trop ne fait plus un aller-retour par clé
    const special = specialKeys(v, ["message", "offlineActionOptions"]).concat(specialKeys(m, ["computed"]),
      specialKeys(m.computed, ["mentions"]), specialKeys(v.offlineActionOptions, ["pendingUploadIds"]));
    if (special.length) {
      return refuse("citation, transfert, pièce jointe ou retouche (« " + T.cut(special.join(", "), 160) + " »)");
    }
    const off = v.offlineActionOptions;
    if (isObject(off) && Array.isArray(off.pendingUploadIds) && off.pendingUploadIds.length) {
      return refuse("pièce jointe en cours d'envoi");
    }
    for (const k of Object.keys(m)) {
      const x = m[k];
      if (k === "computed") continue;
      if (Array.isArray(x) && x.length) return refuse("données jointes au message (« " + T.cut(k, 40) + " »)");
      if (typeof x === "string" && /^\s*[[{]/.test(x) && x.trim().length > 2 && k !== "content") {
        return refuse("données jointes au message (« " + T.cut(k, 40) + " »)");
      }
    }
    const content = typeof m.content === "string" ? m.content : "";
    const text = htmlText(content);
    const client = m.clientMessageId === undefined || m.clientMessageId === null ? "" : String(m.clientMessageId);
    const correlation = typeof v.correlationId === "string" ? v.correlationId : "";
    const fixed = new Set(FIXED_PATHS);
    const clean = function (s, path) {
      if (fixed.has(path)) return s;
      // ce que Teams a calculé du message et qui en est le texte même : refait avec le texte neuf
      if (text && s.trim() === text && path.indexOf(COMPUTED + ".") === 0 && path.indexOf("[]") < 0) {
        return SLOT.text;
      }
      if ((content && s === content) || (text && s.trim() === text)) return "";
      if ((text.length >= 8 && s.indexOf(text) >= 0) || (content.length >= 8 && s.indexOf(content) >= 0)) return "";
      // ce que Teams a calculé du message (ses liens…) : un morceau du texte n'y reste pas
      if (path.indexOf(COMPUTED + ".") === 0 && s.length >= 8 && text.indexOf(s) >= 0) return "";
      let out = s.split(conv).join(SLOT.conversation);
      if (client.length >= 10) out = out.split(client).join(SLOT.client);
      if (correlation.length >= 8) out = out.split(correlation).join(SLOT.correlation);
      return out;
    };
    let c;
    try {
      c = mapStrings(JSON.parse(JSON.stringify(command)), clean, "", 0, function (k) { return k.indexOf(conv) < 0; });
    } catch (_) {
      c = null;
    }
    if (!isObject(c)) return refuse("commande illisible ou trop profonde");
    delete c.requestId;
    delete c.rendererId;
    delete c.windowId;
    const cv = c.payload.variables;
    const cm = cv.message;
    cv.convId = "";
    if ("originalConvId" in cv && cv.originalConvId !== null) cv.originalConvId = "";
    if ("correlationId" in cv) cv.correlationId = "";
    cm.content = "";
    cm.clientMessageId = "";
    if ("originalSendPipelineTime" in cm) cm.originalSendPipelineTime = "";
    if (isObject(cm.computed)) {
      // les mentions, et tout ce que Teams a calculé en liste (liens, personnes…) : le message neuf n'en a pas
      for (const k of Object.keys(cm.computed)) if (Array.isArray(cm.computed[k])) cm.computed[k] = [];
    }
    const co = cv.offlineActionOptions;
    if (isObject(co)) {
      if ("actionId" in co) co.actionId = "";
      if (typeof co.queueId === "string" && co.queueId.indexOf(SLOT.conversation) >= 0) {
        const at = co.queueId.lastIndexOf("_" + SLOT.conversation);
        if (at < 0 || at + SLOT.conversation.length + 1 !== co.queueId.length) {
          return refuse("file d'attente inattendue");
        }
        co.queueId = co.queueId.slice(0, at) + "_" + SLOT.conversation;
      }
      if (Array.isArray(co.pendingUploadIds)) co.pendingUploadIds = [];
    }
    const json = JSON.stringify(c);
    // le dernier regard : plus rien de ce message, ni de cette conversation ou d'une autre
    if (json.length > TEMPLATE_MAX_CHARS) return refuse("modèle trop gros");
    if (json.indexOf(conv) >= 0 || CHAT_ID_IN.test(json) || (client.length >= 10 && json.indexOf(client) >= 0)
      || (correlation.length >= 8 && json.indexOf(correlation) >= 0) || (text.length >= 8 && json.indexOf(text) >= 0)) {
      return refuse("le modèle garderait une trace du message");
    }
    const shape = learnShape(content);
    return { template: { command: c, open: shape.open, close: shape.close, breaks: shape.breaks },
      bilateral: isBilateralChat(conv) };
  }

  /** Le modèle pour cette conversation : celui de sa sorte (tête-à-tête ou groupe), sinon l'autre ; `null` sinon. */
  function pickSendTemplate(templates, conversation) {
    if (!isObject(templates)) return null;
    const own = isBilateralChat(conversation) ? "bilateral" : "group";
    const other = own === "bilateral" ? "group" : "bilateral";
    for (const kind of [own, other]) {
      const t = templates[kind];
      if (isObject(t) && isObject(t.command)) return t;
    }
    return null;
  }

  /**
   * La commande d'envoi à passer au worker, en texte JSON (un objet serait ignoré) ; « » si elle ne peut pas l'être
   * (pas de modèle, une conversation qui n'est ni un tête-à-tête ni un groupe, un texte vide…). `o` : `conversation`,
   * `text`, `clientMessageId` (19 chiffres : `clientMessageIdFor(élément)`, le même à chaque tentative — Teams
   * reconnaît un message à lui), `correlationId`, `now` (ms), `requestNumber`, `rendererId`, `windowId` (de la page).
   */
  function workerSendCommand(template, o) {
    const opts = isObject(o) ? o : {};
    const conv = String(opts.conversation || "");
    const text = String(opts.text || "");
    const client = String(opts.clientMessageId || "");
    const correlation = String(opts.correlationId || "");
    const n = Number(opts.requestNumber);
    if (!isObject(template) || !isObject(template.command) || !workerSendable(conv) || !text.trim()
      || !/^\d{1,30}$/.test(client) || !correlation || !Number.isInteger(n) || n < 0
      || !isLiveId(opts.rendererId) || !isLiveId(opts.windowId) || !isFinite(Number(opts.now))) {
      return "";
    }
    const fill = function (s) {
      return s === SLOT.text ? text : s.split(SLOT.conversation).join(conv).split(SLOT.client).join(client)
        .split(SLOT.correlation).join(correlation);
    };
    let c;
    try {
      c = mapStrings(JSON.parse(JSON.stringify(template.command)), fill, "", 0, null);
    } catch (_) {
      return "";
    }
    const v = isObject(c) && isObject(c.payload) ? c.payload.variables : null;
    const m = isObject(v) ? v.message : null;
    if (!isObject(m)) return "";
    v.convId = conv;
    if (typeof v.originalConvId === "string") v.originalConvId = conv;
    v.correlationId = correlation;
    // un groupe n'est jamais « bilatéral » ; un tête-à-tête garde la valeur que Teams a mise dans le modèle : le
    // 2026-11-22, Teams envoyait `false` dans le tête-à-tête d'Albert (`@unq.gbl.spaces`), et c'est ainsi qu'il est parti
    v.isBilateralChat = isBilateralChat(conv) ? (typeof v.isBilateralChat === "boolean" ? v.isBilateralChat : true)
      : false;
    m.clientMessageId = client;
    // la citation (ADR 0305) : le bloc avant le texte, et l'entrée que Teams met dans `computed.quotedMessages`
    const quote = T.quoteOf(opts.quote);
    m.content = quoteHtml(quote) + workerContent(text, template);
    if (quote) {
      if (!isObject(m.computed)) m.computed = {};
      m.computed.quotedMessages = [{ messageId: quote.message, sender: quote.author_id, time: quote.at }];
    } else if (isObject(m.computed) && Array.isArray(m.computed.quotedMessages)) {
      m.computed.quotedMessages = [];
    }
    m.originalSendPipelineTime = String(Math.floor(Number(opts.now)));
    // le brouillon commence maintenant (Teams y met l'heure où l'on a commencé à écrire)
    if (typeof m.draftCreationTime === "string" && /^\d{10,16}$/.test(m.draftCreationTime)) {
      m.draftCreationTime = String(Math.floor(Number(opts.now)));
    }
    if (isObject(m.computed)) m.computed.mentions = [];
    const off = v.offlineActionOptions;
    if (isObject(off)) {
      off.actionId = "send_" + client;
      if ("pendingUploadIds" in off) off.pendingUploadIds = [];
    }
    const out = { requestId: workerRequestId(n), rendererId: opts.rendererId, windowId: opts.windowId };
    for (const k of Object.keys(c)) if (!(k in out)) out[k] = c[k];
    return JSON.stringify(out);
  }

  /** L'identifiant de notre requête d'envoi : une mutation (`m-`), à son numéro. */
  function workerRequestId(n) {
    return "m-" + n;
  }

  function firstError(errors) {
    const e = errors[0];
    const text = isObject(e) ? e.message || e.code || "" : typeof e === "string" ? e : "";
    return T.cut(String(text || "").replace(/\s+/g, " ").trim(), 120);
  }

  /**
   * Ce que dit la réponse du worker à notre commande d'envoi : `sent` (« success », sans erreur), `refused` (une
   * erreur explicite, sans rien d'envoyé : rien n'est parti), `uncertain` (« success » avec des erreurs et un
   * résultat : peut-être parti) ; « » : pas une issue (on attend encore). `reason` : la première erreur, bornée ;
   * `messageId`, s'il est dit.
   */
  function workerReplyOutcome(reply) {
    if (!isObject(reply)) return { result: "", reason: "", messageId: "" };
    const status = typeof reply.status === "string" ? reply.status : "";
    const response = isObject(reply.response) ? reply.response : {};
    const errors = Array.isArray(response.errors) && response.errors.length ? response.errors
      : Array.isArray(reply.errors) && reply.errors.length ? reply.errors : [];
    const data = isObject(response.data) ? response.data : null;
    const result = data ? data[SEND_OPERATION] : undefined;
    if (status === "success") {
      if (!errors.length) {
        return { result: "sent", reason: "", messageId: isObject(result) ? messageIdFrom(result, "") : "" };
      }
      if (result !== undefined && result !== null) {
        return { result: "uncertain", reason: firstError(errors), messageId: "" };
      }
      return { result: "refused", reason: firstError(errors), messageId: "" };
    }
    if (REPLY_FAILED.test(status)) {
      const why = errors.length ? errors : reply.error !== undefined ? [reply.error] : [];
      return { result: "refused", reason: why.length ? firstError(why) : status, messageId: "" };
    }
    return { result: "", reason: "", messageId: "" };
  }

  return { NAV_KEY: NAV_KEY, isConversationId: isConversationId, sameConversation: sameConversation,
    avatarBase: avatarBase, photoUrl: photoUrl,
    workerSendable: workerSendable, isBilateralChat: isBilateralChat, workerCommandHead: workerCommandHead,
    nextRequestNumber: nextRequestNumber, workerRequestId: workerRequestId, htmlText: htmlText,
    learnShape: learnShape, workerContent: workerContent, workerSendTemplate: workerSendTemplate,
    commandShape: commandShape,
    pickSendTemplate: pickSendTemplate, workerSendCommand: workerSendCommand,
    workerReplyOutcome: workerReplyOutcome, SEND_SLOT: SLOT,
    conversationMarker: conversationMarker, syncSince: syncSince, caughtUp: caughtUp, advanceCursor: advanceCursor,
    headerPairs: headerPairs, isAuthHeader: isAuthHeader, authFromHeaders: authFromHeaders,
    isChatServiceUrl: isChatServiceUrl, isChatServiceHost: isChatServiceHost, chatServiceBase: chatServiceBase,
    escapeHtml: escapeHtml, messageContent: messageContent, clientMessageIdFor: clientMessageIdFor, quoteHtml: quoteHtml,
    chatSendOutcome: chatSendOutcome, messageBody: messageBody,
    messageIdFrom: messageIdFrom, navEntry: navEntry, activeConversationFromNav: activeConversationFromNav,
    activeConversationFromStorage: activeConversationFromStorage, conversationFromLocation: conversationFromLocation };
});
