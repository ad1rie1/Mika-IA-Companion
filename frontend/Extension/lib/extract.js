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
  const node = typeof module === "object" && module && module.exports && typeof require === "function";
  const api = factory(node ? require("./text.js") : root.MikaTeamsText);
  if (node) module.exports = api;
  else root.MikaTeamsExtract = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (T) {
  "use strict";

  const MAX_DEPTH = 16;
  const MAX_NODES = 40000;
  const MAX_JSON_STRING = 4 * 1024 * 1024;
  const MAX_TEXT = 4000;
  // une image du service d'images de Teams : son hôte (gardé tel quel) et son identifiant d'objet ; 8 par message
  const AMS_IMAGE = /^(https:\/\/[a-z0-9-]{1,40}\.asm\.skype\.com)\/v1\/objects\/([A-Za-z0-9._:-]{1,200})\/views\/[A-Za-z0-9_]{1,40}(?:[?#].*)?$/;
  const MAX_IMAGES = 8;

  const ID_KEYS = ["id", "clientmessageid", "clientMessageId", "messageId"];
  const CONV_KEYS = ["conversationid", "conversationId", "threadId"];
  const TIME_KEYS = ["originalarrivaltime", "originalArrivalTime", "composetime", "composeTime",
    "clientArrivalTime", "clientarrivaltime", "createdDateTime", "createdTime", "arrivalTime"];
  const TYPE_KEYS = ["messagetype", "messageType"];
  const NAME_KEYS = ["imdisplayname", "imDisplayName", "fromDisplayNameInToken", "displayName", "senderDisplayName"];
  const DELETED_KEYS = ["deletetime", "deleteTime", "deletionTime", "deletedTime", "isDeleted"];
  // la version d'un message : elle avance quand il est modifié (le service de chat la tient en millisecondes)
  const VERSION_KEYS = ["edittime", "editTime", "lastEditedTime", "version"];

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
  /** Le texte d'une cellule de tableau, sur une ligne (ses paragraphes et ses sauts de ligne deviennent des espaces). */
  function cellText(html) {
    return html.replace(/<br\s*\/?>/gi, " ").replace(/<\/(p|div|li)>/gi, " ").replace(/<[^>]+>/g, "")
      .replace(/\s+/g, " ").trim();
  }

  /**
   * Un tableau, une ligne par rangée, ses cellules séparées par « | » : chaque cellule de Teams porte son propre
   * paragraphe, et le tableau devenait une colonne de lignes isolées (« AP Antibes », « 103 », « AP Castellane »…).
   */
  function tableText(inner) {
    const rows = [];
    inner.replace(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi, function (_, row) {
      const cells = [];
      row.replace(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi, function (_c, cell) {
        cells.push(cellText(cell));
        return "";
      });
      if (cells.some(Boolean)) rows.push(cells.join(" | "));
      return "";
    });
    return rows.join("\n");
  }

  /**
   * Une image du message : un emoji garde son texte (`alt`) ; une image collée ou jointe devient « [image] » — son
   * contenu ne part pas, mais on sait qu'il y en avait une (un message fait d'une seule image ne disparaît plus).
   */
  function imageText(tag) {
    const alt = (/\balt=["']([^"']{0,40})["']/i.exec(tag) || [])[1] || "";
    const item = (/\bitemtype=["']([^"']*)["']/i.exec(tag) || [])[1] || "";
    if (/emoji|emoticon/i.test(item)) return alt;
    const picture = /AMSImage|Giphy/i.test(item) || /\/views\/imgo|\/objects\//i.test(tag) || /^\s*(image|img)\s*$/i.test(alt);
    if (picture || !alt.trim()) return picture ? " [image] " : "";
    return alt;
  }

  /**
   * Les images d'un message à télécharger (ADR 0258) : celles du service d'images de Teams seulement
   * (`https://….asm.skype.com/v1/objects/<id>/views/…`) — jamais une autre adresse, qu'on ouvrirait avec les cookies du
   * navigateur —, leur identifiant, leur adresse d'origine (la vue `imgo`) et leur rang parmi les « [image] » du texte
   * (une image d'ailleurs a sa marque sans être téléchargée : les rangs suivent les marques, pas cette liste).
   */
  function imagesOf(html) {
    const out = [];
    let rank = 0;
    String(html || "").replace(/<img\b[^>]*>/gi, function (tag) {
      if (imageText(tag).indexOf("[image]") < 0) return ""; // un emoji, une image décorative : pas de marque
      const src = decodeEntities((/\bsrc=["']([^"']+)["']/i.exec(tag) || [])[1] || "");
      const found = AMS_IMAGE.exec(src);
      if (found && out.length < MAX_IMAGES) {
        out.push({ id: found[2], url: found[1] + "/v1/objects/" + found[2] + "/views/imgo", position: rank });
      }
      rank++;
      return "";
    });
    return out;
  }

  function htmlToText(html) {
    let s = String(html || "");
    if (s.indexOf("<") < 0 && s.indexOf("&") < 0) return s.trim();
    s = s
      .replace(/<(script|style)\b[\s\S]*?<\/\1>/gi, "")
      .replace(/<span[^>]*itemprop=["']?time["']?[^>]*>[\s\S]*?<\/span>/gi, "")
      .replace(/<img\b[^>]*>/gi, imageText)
      .replace(/<table\b[^>]*>([\s\S]*?)<\/table>/gi, function (_, inner) { return "\n" + tableText(inner) + "\n\n"; })
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

  /** Une marque de suppression : `true`, ou une date ; « 0 » et `false` n'en sont pas. */
  function deletionMark(v) {
    if (v === true) return true;
    if (v === false || v === undefined || v === null) return false;
    return !/^0*$/.test(String(v).trim());
  }

  function isDeleted(o) {
    if (deletionMark(first(o, DELETED_KEYS))) return true;
    const props = isObject(o.properties) ? o.properties : null;
    return Boolean(props && deletionMark(first(props, DELETED_KEYS)));
  }

  /**
   * La version d'un message (la date de sa dernière modification : la plus tardive de celles qu'il dit — `version`
   * avance aussi quand une réaction change, `edittime` seulement quand le texte change), 0 si elle n'est pas dite.
   */
  function versionOf(o) {
    const props = isObject(o.properties) ? o.properties : {};
    let most = 0;
    for (const k of VERSION_KEYS) most = Math.max(most, toMillis(o[k]), toMillis(props[k]));
    return most;
  }

  // ── Les réactions (ADR 0300) ───────────────────────────────────────────────

  /** La clé d'une réaction de Teams (« like », « heart », « 1f44f_clappinghands »…), en minuscules. */
  const REACTION_KEY = /^[a-z0-9_+-]{1,40}$/;
  const MAX_REACTIONS = 20; // par message
  const MAX_REACTORS = 10; // les identifiants gardés par réaction (leur nombre, lui, est entier)
  const ORGID = /orgid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i;

  /** Un identifiant de personne comparable : `8:orgid:<uuid>` en minuscules, quelle que soit sa forme. */
  function personKey(id) {
    const s = String(id || "").trim();
    const org = ORGID.exec(s);
    return org ? "8:orgid:" + org[1].toLowerCase() : s.toLowerCase();
  }

  function parsedList(raw) {
    if (typeof raw !== "string") return raw;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  /**
   * Les réactions d'un message (ADR 0300) : `[{key, count, mine, by}]` — sa clé de Teams, combien l'ont posée, si
   * `self` (l'uuid de soi, s'il est connu) en est, et qui (dix identifiants au plus, les premiers à l'avoir posée).
   * `properties.emotions` (un texte JSON ou une liste : `[{key, users: [{mri, time, value}]}]`), sinon le seul compte
   * (`annotationsSummary.emotions` : `{like: 3}`). `undefined` quand le message n'en dit rien (une source qui ne les
   * porte pas : le serveur garde ce qu'il savait) ; `[]` quand il dit qu'il n'y en a aucune.
   */
  function reactionsOf(o, self) {
    const props = isObject(o.properties) ? o.properties : {};
    const raw = parsedList(props.emotions !== undefined ? props.emotions : o.emotions);
    const me = self ? personKey(String(self).indexOf(":") >= 0 ? self : "8:orgid:" + self) : "";
    if (Array.isArray(raw)) {
      const out = [];
      const keys = new Set();
      for (const r of raw) {
        if (out.length >= MAX_REACTIONS) break;
        if (!isObject(r)) continue;
        const key = String(r.key || "").trim().toLowerCase();
        if (!REACTION_KEY.test(key) || keys.has(key)) continue;
        const users = (Array.isArray(r.users) ? r.users : []).filter(isObject)
          .map(function (u) { return { id: personKey(u.mri || u.id), time: toMillis(u.time) }; })
          .filter(function (u) { return u.id; })
          .sort(function (a, b) { return a.time - b.time; });
        const ids = [];
        for (const u of users) if (ids.indexOf(u.id) < 0) ids.push(u.id);
        if (!ids.length) continue; // plus personne ne la porte : retirée
        keys.add(key);
        out.push({ key: key, count: ids.length, mine: Boolean(me) && ids.indexOf(me) >= 0,
          by: ids.slice(0, MAX_REACTORS) });
      }
      return out;
    }
    const summary = [o.annotationsSummary, props.annotationsSummary].find(function (s) {
      return isObject(s) && isObject(s.emotions);
    });
    if (!summary) return undefined;
    const out = [];
    for (const k of Object.keys(summary.emotions)) {
      const key = k.trim().toLowerCase();
      const count = Math.floor(Number(summary.emotions[k]) || 0);
      if (REACTION_KEY.test(key) && count > 0 && out.length < MAX_REACTIONS) {
        out.push({ key: key, count: Math.min(count, 1000000), mine: false, by: [] });
      }
    }
    return out;
  }

  /**
   * Un message, ou `null` si l'objet n'en a pas la forme ou n'est pas un message lisible (frappe en cours,
   * activité du fil, appel…). Un message supprimé devient un enregistrement de suppression : même identifiant,
   * même conversation, même date, `deleted: true` et un texte vide — le serveur efface sa copie. `self` : l'uuid de
   * soi, s'il est connu (sa réaction se reconnaît : `mine`).
   */
  function normalizeMessage(o, inheritedConv, self) {
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
    const authorId = authorIdOf(o);
    let id = first(o, ID_KEYS);
    id = typeof id === "string" || typeof id === "number" ? String(id) : "";
    if (isDeleted(o)) {
      // sans identifiant, on ne saurait pas quel message effacer
      if (!id) return null;
      return { id: id, conv: conv, author: author, authorId: authorId, time: time, type: type, text: "",
        deleted: true, version: versionOf(o), mentions: [] };
    }
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
    text = T.clip(text, MAX_TEXT);
    if (!id) id = "h" + T.hash(conv + "|" + time + "|" + authorId + "|" + text);
    const out = { id: id, conv: conv, author: author, authorId: authorId, time: time, type: type, text: text,
      version: versionOf(o), mentions: mentionsOf(o) };
    const images = /^richtext\/media/i.test(type) ? [] : imagesOf(o.content);
    if (images.length) out.images = images;
    const reactions = reactionsOf(o, self);
    if (reactions) out.reactions = reactions;
    return out;
  }

  /** Une conversation dont on apprend le nom ou la nature (une liste de conversations, une fiche de fil). */
  function normalizeConversation(o) {
    if (!isObject(o) || typeof o.id !== "string" || !/^(19|8|48):/.test(o.id)) return null;
    const props = isObject(o.threadProperties) ? o.threadProperties : {};
    let title = first(props, ["topic", "spaceThreadTopic", "title"]) || first(o, ["topic", "title", "displayName"]);
    if (isObject(o.chatTitle)) title = title || first(o.chatTitle, ["longTitle", "shortTitle"]);
    const threadType = first(props, ["threadType", "productThreadType"]) || first(o, ["threadType", "chatType"]) || "";
    if (!title && !threadType) return null;
    return { id: o.id, title: typeof title === "string" ? T.cut(title.trim(), 120) : "",
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
   * Borné en profondeur et en nombre de nœuds ; une chaîne qui porte du JSON est ouverte (`parseStrings`) ; `self` :
   * l'uuid de soi, s'il est connu (ses réactions se reconnaissent).
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
      const message = normalizeMessage(v, item.conv, options.self);
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

  // ── Les profils (ADR 0298) ─────────────────────────────────────────────────

  /** Un identifiant de personne de Teams (son « mri ») : un compte d'organisation, un compte Microsoft, un invité. */
  const PROFILE_ID = /^(8:orgid:[0-9a-f-]{36}|8:live:[a-z0-9._-]{1,80}|8:teamsvisitor:[0-9a-f-]{32,36})$/;
  const PROFILE_EMAIL = /^[^\s@<>"',;]{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,}$/;
  const PROFILE_PHONES = 3;
  /** L'empreinte de sa photo (`avatarETag`, ADR 0300) : ce qui change quand la photo change. */
  const AVATAR = /^[A-Za-z0-9._:+/=-]{1,200}$/;

  /** L'empreinte de la photo d'un profil, sans les guillemets ni le « W/ » d'une empreinte HTTP ; « » sinon. */
  function avatarOf(v) {
    const s = typeof v === "string" ? v.trim().replace(/^W\//, "").replace(/^"|"$/g, "") : "";
    return AVATAR.test(s) ? s : "";
  }

  /**
   * Le profil d'une personne tel que Teams le garde dans ce navigateur (base `Teams:profiles`, magasin `profiles`) :
   * son identifiant, son nom, son e-mail (sinon celui de connexion, s'il en a la forme), son poste, son entreprise, son
   * service, son organisation, jusqu'à trois numéros et l'empreinte de sa photo (`avatar`, s'il en a une : ADR 0300).
   * `null` sans identifiant reconnu, ou sans rien qui dise qui c'est.
   */
  function profileOf(o) {
    if (!isObject(o)) return null;
    const id = typeof o.mri === "string" ? o.mri.trim().toLowerCase() : "";
    if (!PROFILE_ID.test(id)) return null;
    const pick = function (v, n) { return typeof v === "string" ? T.cut(v.replace(/\s+/g, " ").trim(), n) : ""; };
    // un nom de connexion d'invité (« x_gmail.com#ext#@hote.onmicrosoft.com ») n'est pas une adresse qu'on lui connaît
    const emailOf = function (v) {
      const e = pick(v, 254).toLowerCase();
      return PROFILE_EMAIL.test(e) && e.indexOf("#ext#") < 0 ? e : "";
    };
    const phones = [];
    const raw = [o.telephoneNumber, o.mobile].concat(Array.isArray(o.phones)
      ? o.phones.map(function (p) { return isObject(p) ? p.number : p; }) : []);
    for (const v of raw) {
      const n = pick(v, 40);
      if (n.replace(/\D/g, "").length >= 6 && phones.indexOf(n) < 0 && phones.length < PROFILE_PHONES) phones.push(n);
    }
    const out = { id: id, name: pick(o.displayName, 120), email: emailOf(o.email) || emailOf(o.mail)
      || emailOf(o.userPrincipalName), title: pick(o.jobTitle, 120), company: pick(o.companyName, 120),
      department: pick(o.department, 120), tenant: pick(o.tenantName, 120), phones: phones };
    const avatar = avatarOf(o.avatarETag);
    if (avatar) out.avatar = avatar;
    return out.name || out.email || out.title || out.company ? out : null;
  }

  return { extract: extract, normalizeMessage: normalizeMessage, normalizeConversation: normalizeConversation,
    conversationKind: conversationKind, conversationFromUrl: conversationFromUrl, htmlToText: htmlToText,
    imagesOf: imagesOf, profileOf: profileOf, reactionsOf: reactionsOf, PROFILE_ID: PROFILE_ID,
    PROFILE_EMAIL: PROFILE_EMAIL, AVATAR: AVATAR, REACTION_KEY: REACTION_KEY, parseEmbedded: parseEmbedded,
    toMillis: toMillis };
});
