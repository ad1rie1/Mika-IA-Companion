/*
 * Le service d'arrière-plan, client du plugin Teams de Mika :
 *   - il reçoit ce que les onglets Teams ont capté, décide de ce qui part (nouveau, pas exclu, pas écrit pendant une
 *     pause), le garde en file et l'envoie (`POST /api/teams/inbox`), ses propres messages compris ;
 *   - il relève toutes les 30 s ce qu'elle a écrit (`GET /api/teams/outbox`) : un brouillon est annoncé par une
 *     notification puis placé dans la zone de saisie quand la conversation est ouverte ; un message à envoyer est
 *     d'abord réclamé auprès du serveur (un seul navigateur l'obtient), puis part par un onglet Teams ; chaque issue
 *     sûre lui est rendue (`POST /api/teams/outbox/<id>`), une issue douteuse ne l'est jamais.
 *
 * Un service d'extension MV3 peut être arrêté à tout moment : tout l'état vit dans `chrome.storage.local`, et chaque
 * lecture-écriture passe par un même verrou pour que deux événements simultanés ne s'écrasent pas. Les appels
 * réseau et les allers-retours avec les onglets se font hors du verrou ; ce qu'ils changent est réécrit dessous,
 * entrée par entrée.
 */
/* global importScripts, MikaTeamsText, MikaTeamsExtract, MikaTeamsSignals, MikaTeamsOutbox */
importScripts("lib/text.js", "lib/extract.js", "lib/signals.js", "lib/outbox.js");

const T = MikaTeamsText;
const X = MikaTeamsExtract;
const S = MikaTeamsSignals;
const O = MikaTeamsOutbox;

const TEAMS_TABS = ["https://teams.microsoft.com/*", "https://teams.cloud.microsoft/*", "https://teams.live.com/*"];
const TEAMS_HOME = "https://teams.microsoft.com/";
const QUEUE_MAX = 1000;
const TITLES_MAX = 3000;
const PEOPLE_MAX = 3000; // conversations dont on garde les noms des personnes vues
const PEOPLE_PER_CONVERSATION = 12;
const REQUEST_TIMEOUT_MS = 15000;
const TAB_SEND_TIMEOUT_MS = 45000; // au-delà du relais (30 s) : un onglet figé ne bloque pas la tournée
const RUNTIME_VERSION = 2;
const NOTE_PREFIX = "mika-draft:";
const ICON = "icons/icon-128.png";

const DEFAULT_SETTINGS = { base: "http://127.0.0.1:8001", key: "", paused: false, exclude: "" };

function freshRuntime() {
  return {
    version: RUNTIME_VERSION,
    armedAt: 0, seen: {}, queue: [], titles: {}, people: {}, pauses: [], self: "", selfName: "",
    batchMax: S.LIMITS.maxMessages,
    stats: { received: 0, admitted: 0, delivered: 0, own: 0, posts: 0, dropped: {}, bySource: { network: 0, idb: 0 } },
    lastError: "", lastErrorAt: 0, lastOkAt: 0, lastPollAt: 0, retryAt: 0, authFailed: false, failures: 0,
    ackRetryAt: 0, ackFailures: 0, inboxStrike: null,
    outbox: O.freshBox(),
  };
}

// ── L'état ─────────────────────────────────────────────────────────────────

let chain = Promise.resolve();
function locked(fn) {
  const run = chain.then(fn, fn);
  chain = run.catch(function () { /* l'erreur appartient à l'appelant */ });
  return run;
}

/** La première version envoyait des signaux d'appareil : sa file, son journal et son jeton n'ont plus cours. */
function migrate(old) {
  return { armedAt: old.armedAt || 0, seen: old.seen || {}, titles: old.titles || {}, self: old.self || "" };
}

async function load() {
  const got = await chrome.storage.local.get(["settings", "runtime"]);
  const stored = got.settings || {};
  const settings = {};
  for (const k of Object.keys(DEFAULT_SETTINGS)) settings[k] = stored[k] !== undefined ? stored[k] : DEFAULT_SETTINGS[k];
  let raw = got.runtime || {};
  if (raw.version !== RUNTIME_VERSION) raw = migrate(raw);
  const runtime = Object.assign(freshRuntime(), raw);
  runtime.stats = Object.assign(freshRuntime().stats, runtime.stats || {});
  runtime.outbox = Object.assign(O.freshBox(), runtime.outbox || {});
  runtime.outbox.stats = Object.assign(O.freshBox().stats, runtime.outbox.stats || {});
  if (!runtime.armedAt) runtime.armedAt = Date.now();
  // en pause sans intervalle ouvert (une version d'avant les intervalles) : la pause compte depuis maintenant
  if (settings.paused && !S.pauseOpen(runtime.pauses)) runtime.pauses = S.notePause(runtime.pauses, true, Date.now());
  return { settings: settings, runtime: runtime };
}

function save(state) {
  return chrome.storage.local.set({ settings: state.settings, runtime: state.runtime });
}

/** Lire, changer, écrire, sous le verrou. Rend ce que rend `fn`. */
function mutate(fn) {
  return locked(async function () {
    const state = await load();
    const out = fn(state);
    await save(state);
    return out;
  });
}

function fail(rt, text) {
  rt.lastError = text;
  rt.lastErrorAt = Date.now();
}

/** On peut parler à Mika : une clé, pas de pause, pas de clé refusée, pas d'attente demandée. */
function ready(state, now) {
  const rt = state.runtime;
  return !state.settings.paused && Boolean(state.settings.key) && !rt.authFailed && rt.retryAt <= now;
}

/** On peut lui rendre les issues : même en pause, même pendant une attente de la file — pas après une clé refusée. */
function canAck(state, now) {
  const rt = state.runtime;
  return Boolean(state.settings.key) && !rt.authFailed && (rt.ackRetryAt || 0) <= now;
}

/** On peut écrire dans Teams : pas de pause, une clé acceptée. */
function canWrite(state) {
  return !state.settings.paused && Boolean(state.settings.key) && !state.runtime.authFailed;
}

// ── Ce qu'on sait des conversations ─────────────────────────────────────────

function learnTitles(rt, conversations, now) {
  for (const c of conversations) {
    const prev = rt.titles[c.id] || {};
    rt.titles[c.id] = Object.assign({}, prev,
      { title: c.title || prev.title || "", kind: X.conversationKind(c.id, c.threadType), at: now, known: true });
  }
  const ids = Object.keys(rt.titles);
  if (ids.length > TITLES_MAX) {
    ids.sort(function (a, b) { return rt.titles[a].at - rt.titles[b].at; });
    for (const id of ids.slice(0, ids.length - TITLES_MAX)) delete rt.titles[id];
  }
}

/** Une personne vue écrire dans une conversation (pas soi) : c'est par elle qu'on nomme un tête-à-tête. */
function learnPerson(rt, conv, author, now) {
  const name = S.clean(author, 120);
  if (!conv || !name) return;
  const p = rt.people[conv] || (rt.people[conv] = { names: [], at: now });
  p.at = now;
  if (p.names.indexOf(name) < 0) {
    p.names.push(name);
    if (p.names.length > PEOPLE_PER_CONVERSATION) p.names.shift();
  }
}

function prunePeople(rt) {
  const ids = Object.keys(rt.people);
  if (ids.length <= PEOPLE_MAX) return;
  ids.sort(function (a, b) { return rt.people[a].at - rt.people[b].at; });
  for (const id of ids.slice(0, ids.length - PEOPLE_MAX)) delete rt.people[id];
}

function kindOf(rt, conv) {
  const known = rt.titles[conv];
  return known ? known.kind : X.conversationKind(conv, "");
}

function titleOf(rt, conv) {
  const known = rt.titles[conv];
  return known ? known.title : "";
}

/** Ce qui nomme une conversation, pour les exclusions et la retenue : `{conv, title, kind, people, known}`. */
function describe(rt, conv) {
  const t = rt.titles[conv];
  return { conv: conv, title: t ? t.title || "" : "", kind: kindOf(rt, conv),
    people: rt.people[conv] ? rt.people[conv].names : [], known: Boolean(t && (t.known || t.title)) };
}

/** Un élément de la boîte d'envoi dans une conversation exclue : son nom chez Mika compte aussi. */
function excludedEntry(state, entry) {
  const rt = state.runtime;
  const c = describe(rt, entry.conversation);
  if (entry.title && c.title.toLowerCase() !== String(entry.title).toLowerCase()) {
    c.title = [c.title, entry.title].filter(Boolean).join("\n");
  }
  if (!rt.titles[entry.conversation] && entry.kind) c.kind = entry.kind;
  return S.isExcluded(c, S.exclusions(state.settings.exclude));
}

// ── Ce qui arrive des onglets ────────────────────────────────────────────────

function ingest(state, batch) {
  const rt = state.runtime;
  const settings = state.settings;
  const now = Date.now();
  if (S.isSelfId(batch.self)) rt.self = String(batch.self).toLowerCase();
  // en pause, rien n'est appris des noms de conversation : ils ne partiraient qu'après, avec ce qui a été écrit
  // pendant (l'onglet les redit à la reprise)
  if (!settings.paused) learnTitles(rt, batch.conversations || [], now);
  rt.pauses = S.prunePauses(rt.pauses, now);
  const exclude = S.exclusions(settings.exclude);
  for (const m of batch.messages || []) {
    rt.stats.received++;
    rt.stats.bySource[m.source] = (rt.stats.bySource[m.source] || 0) + 1;
    // son propre nom, tel que Teams l'affiche : c'est lui qui signe ce que Mika envoie en son nom ; les autres
    // noms, gardés ici, servent seulement aux exclusions (même d'un message qui ne part pas : plus d'exclusion, jamais
    // moins)
    if (m.author && S.isOwn(m, rt.self)) rt.selfName = S.clean(m.author, 120);
    else if (m.author) learnPerson(rt, m.conv, m.author, now);
    const c = describe(rt, m.conv);
    const reason = S.admit(m, {
      now: now, armedAt: rt.armedAt, seen: rt.seen, paused: settings.paused, pauses: rt.pauses, title: c.title,
      kind: c.kind, people: c.people, exclude: exclude,
    });
    if (reason === "déjà vu") continue;
    if (reason !== "vide") rt.seen[T.versionKey(m)] = m.time;
    if (reason) {
      rt.stats.dropped[reason] = (rt.stats.dropped[reason] || 0) + 1;
      continue;
    }
    // une version plus récente (modifiée, supprimée) remplace celle qui attend encore
    rt.queue = rt.queue.filter(function (q) { return q.id !== m.id; });
    const entry = { id: m.id, conv: m.conv, author: m.author, authorId: m.authorId, time: m.time, text: m.text,
      mentions: (m.mentions || []).slice(0, 20), at: now };
    if (m.deleted) {
      entry.deleted = true;
      entry.text = "";
      entry.mentions = [];
    }
    rt.queue.push(entry);
    rt.stats.admitted++;
  }
  prunePeople(rt);
  if (rt.queue.length > QUEUE_MAX) {
    rt.queue.sort(function (a, b) { return a.time - b.time; });
    const over = rt.queue.length - QUEUE_MAX;
    rt.queue.splice(0, over);
    rt.stats.dropped["file pleine"] = (rt.stats.dropped["file pleine"] || 0) + over;
  }
  rt.seen = S.pruneSeen(rt.seen, now);
}

// ── Le serveur ─────────────────────────────────────────────────────────────

async function request(settings, method, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
  try {
    const headers = { authorization: "Bearer " + settings.key };
    if (body !== undefined) headers["content-type"] = "application/json";
    const response = await fetch(new URL(path, settings.base).toString(), {
      method: method,
      headers: headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      credentials: "omit", // jamais la session d'un navigateur connecté à la console : seule la clé compte
      cache: "no-store",
    });
    let data = {};
    try {
      data = (await response.json()) || {};
    } catch (_) { /* corps vide ou illisible */ }
    return { status: response.status, data: data, error: String(data.error || ""),
      retryAfter: S.retryAfterSeconds(response.headers.get("retry-after"), Date.now()) };
  } catch (e) {
    return { status: 0, data: {}, error: e && e.name === "AbortError" ? "pas de réponse en 15 s"
      : "Mika injoignable (" + (e && e.message ? e.message : "réseau") + ")" };
  } finally {
    clearTimeout(timer);
  }
}

/** Un échec qui arrête tout pour l'instant : clé refusée, ralentir, ou attendre de plus en plus longtemps. */
function trouble(rt, result, now) {
  if (result.status === 401) {
    rt.authFailed = true;
    fail(rt, "Clé refusée. Collez la clé Teams de Mika (Console › Configuration › Teams).");
    return;
  }
  if (result.status === 429) {
    rt.retryAt = now + result.retryAfter * 1000;
    fail(rt, "Mika demande de ralentir : reprise dans " + result.retryAfter + " s.");
    return;
  }
  rt.failures++;
  const wait = S.backoffSeconds(rt.failures);
  rt.retryAt = now + wait * 1000;
  fail(rt, troubleText(result) + " — nouvel essai dans " + wait + " s.");
}

function troubleText(result) {
  // 403 : Teams désactivé chez Mika, ou l'origine refusée — ce n'est pas la clé
  return result.status === 404 ? "Pas de plugin Teams à cette adresse (mettre à jour Mika)"
    : result.status === 403 ? "Mika refuse : " + (result.error || "Teams est désactivé chez elle")
      : result.error || "Mika a répondu " + result.status;
}

/** Mika a répondu comme prévu : l'attente et l'erreur affichée s'effacent. */
function succeeded(rt) {
  rt.failures = 0;
  rt.lastError = "";
}

// ── L'envoi des messages ─────────────────────────────────────────────────────

/** Ce que le serveur sait d'une conversation : son nom et sa nature, tels qu'on les lui a dits. */
function signature(rt, conv) {
  return kindOf(rt, conv) + "|" + titleOf(rt, conv);
}

function markShared(rt, conv, now) {
  const t = rt.titles[conv] || (rt.titles[conv] = { title: "", kind: X.conversationKind(conv, ""), at: now });
  t.shared = true;
  t.sentSig = signature(rt, conv);
}

/** Les conversations déjà connues de Mika dont on a appris le nom depuis : à lui redire. */
function titleUpdates(rt, exclude) {
  return Object.keys(rt.titles).filter(function (id) {
    const t = rt.titles[id];
    return t.shared && t.sentSig !== signature(rt, id) && t.kind !== "system"
      && !S.isExcluded(describe(rt, id), exclude);
  }).slice(0, S.LIMITS.maxConversations);
}

/** Les messages de la file retenus le temps d'apprendre le nom de leur conversation. */
function heldMessages(rt, exclude, now) {
  return rt.queue.filter(function (m) { return S.held(m, describe(rt, m.conv), exclude, now); });
}

function nextBatch(state) {
  const rt = state.runtime;
  const now = Date.now();
  // une exclusion ajoutée, ou un nom appris après coup, vaut aussi pour ce qui attend
  const exclude = S.exclusions(state.settings.exclude);
  rt.queue = rt.queue.filter(function (m) {
    if (!S.isExcluded(describe(rt, m.conv), exclude)) return true;
    rt.stats.dropped.exclue = (rt.stats.dropped.exclue || 0) + 1;
    return false;
  });
  const held = new Set(heldMessages(rt, exclude, now));
  const list = S.batches(rt.queue.filter(function (m) { return !held.has(m); }), {
    info: function (conv) { return { title: titleOf(rt, conv), kind: kindOf(rt, conv) }; },
    self: { id: S.selfMri(rt.self), name: rt.selfName },
    selfId: rt.self,
    extra: titleUpdates(rt, exclude),
    maxMessages: rt.batchMax,
  });
  return list[0] || null;
}

/** Ce que la réponse du serveur à un lot change ; rend `true` s'il faut continuer avec le lot suivant. */
function afterInbox(state, batch, result) {
  const rt = state.runtime;
  const now = Date.now();
  const ids = new Set(batch.ids);
  const drop = function (reason) {
    rt.queue = rt.queue.filter(function (m) { return !ids.has(m.id); });
    if (batch.ids.length) rt.stats.dropped[reason] = (rt.stats.dropped[reason] || 0) + batch.ids.length;
    for (const conv of batch.convs) markShared(rt, conv, now); // ne pas redire sans fin ce qui est refusé
  };
  if (result.status === 202) {
    // le serveur écarte lui-même un message illisible, le reste du lot passe
    const refused = Math.max(0, Math.min(batch.ids.length, Number(result.data && result.data.dropped) || 0));
    rt.queue = rt.queue.filter(function (m) { return !ids.has(m.id); });
    rt.stats.delivered += batch.ids.length - refused;
    if (refused) rt.stats.dropped["refusé par Mika"] = (rt.stats.dropped["refusé par Mika"] || 0) + refused;
    rt.stats.own += batch.body.messages.filter(function (m) { return m.own; }).length;
    rt.stats.posts++;
    for (const conv of batch.convs) markShared(rt, conv, now);
    rt.batchMax = Math.min(S.LIMITS.maxMessages, (rt.batchMax || 1) * 2);
    rt.lastOkAt = now;
    rt.inboxStrike = null;
    succeeded(rt);
    return true;
  }
  if (result.status === 413) {
    if (batch.ids.length > 1) {
      rt.batchMax = Math.max(1, Math.floor(batch.ids.length / 2));
      return true;
    }
    drop("trop gros");
    fail(rt, "Un message trop gros pour Mika a été écarté.");
    return true;
  }
  if (result.status === 400) {
    // le corps entier est illisible pour le serveur : le redire n'y changerait rien
    drop("refusé par Mika");
    fail(rt, "Un lot refusé par Mika : " + (result.error || "400"));
    return true;
  }
  if (result.status >= 500) {
    rt.inboxStrike = S.serverStrike(rt.inboxStrike, result.status, batch.ids[0] || batch.convs[0] || "");
    if (rt.inboxStrike.count >= S.LIMITS.serverErrorsMax) {
      // le même lot, la même erreur, encore et encore : il bloquerait toute la file
      drop("erreur de Mika");
      console.warn("[Mika · Teams] lot écarté après " + rt.inboxStrike.count + " erreurs " + result.status
        + " de suite (" + batch.ids.length + " message(s))");
      fail(rt, "Un lot que Mika refusait sans fin (erreur " + result.status + ", " + rt.inboxStrike.count
        + " fois de suite) a été écarté.");
      rt.inboxStrike = null;
      return true;
    }
  }
  trouble(rt, result, now);
  return false;
}

let flushing = null;
function flush() {
  if (!flushing) flushing = flushOnce().finally(function () { flushing = null; });
  return flushing;
}

async function flushOnce() {
  let delivered = false;
  for (let round = 0; round < 50; round++) {
    const job = await mutate(function (state) {
      if (!ready(state, Date.now())) return null;
      const batch = nextBatch(state);
      return batch ? { settings: state.settings, batch: batch } : null;
    });
    if (!job) break;
    const result = await request(job.settings, "POST", "/api/teams/inbox", job.batch.body);
    const go = await mutate(function (state) { return afterInbox(state, job.batch, result); });
    if (result.status === 202) delivered = true;
    if (!go) break;
  }
  if (delivered) schedulePoll(1500); // une réponse de Mika suit souvent ce qu'elle vient de lire
  // ce qui reste retenu repart dès que sa retenue prend fin (l'alarme de 30 s le rattrape si le service dort)
  const state = await load();
  const exclude = S.exclusions(state.settings.exclude);
  const held = heldMessages(state.runtime, exclude, Date.now());
  if (held.length && ready(state, Date.now())) {
    const first = Math.min.apply(null, held.map(function (m) { return Number(m.at) || 0; }));
    scheduleFlush(Math.max(1000, first + S.LIMITS.holdMs - Date.now() + 500));
  }
}

let flushTimer = 0;
function scheduleFlush(ms) {
  if (flushTimer) return;
  flushTimer = setTimeout(function () {
    flushTimer = 0;
    flush().catch(function () { /* déjà noté dans l'état */ });
  }, ms);
}

// ── Ce que Mika écrit ───────────────────────────────────────────────────────

function teamsTabs() {
  return chrome.tabs.query({ url: TEAMS_TABS }).then(function (tabs) {
    // un onglet déchargé ou gelé ne répondrait pas
    return tabs.filter(function (t) { return !t.discarded && t.frozen !== true; })
      .sort(function (a, b) { return (b.active ? 1 : 0) - (a.active ? 1 : 0) || (b.lastAccessed || 0) - (a.lastAccessed || 0); });
  });
}

/** Les brouillons que les onglets peuvent placer maintenant (aucun en pause ou sans clé). */
function currentDrafts(state) {
  if (state.settings.paused || !state.settings.key) return [];
  return O.pendingDrafts(state.runtime.outbox, Date.now(), function (e) { return excludedEntry(state, e); });
}

async function pushDrafts(list) {
  for (const tab of await teamsTabs()) {
    chrome.tabs.sendMessage(tab.id, { kind: "drafts", items: list }).catch(function () { /* pas de script */ });
  }
}

async function refreshDrafts() {
  const state = await load();
  const list = currentDrafts(state);
  await pushDrafts(list);
  await syncNotifications(list);
}

/** La pause est levée : les onglets redisent les noms de conversation qu'ils connaissent (non gardés pendant). */
async function resendTitles() {
  for (const tab of await teamsTabs()) {
    chrome.tabs.sendMessage(tab.id, { kind: "resendTitles" }).catch(function () { /* pas de script */ });
  }
}

function notify(entry) {
  const where = entry.kind === "channel" ? "C'est dans un canal : ouvre-le dans Teams, la réponse se placera dans la zone de saisie."
    : entry.kind === "meeting" ? "C'est dans la conversation d'une réunion : ouvre-la dans Teams, la réponse s'y placera."
      : "Clique pour ouvrir la conversation : la réponse se placera dans la zone de saisie, à toi de l'envoyer.";
  chrome.notifications.create(NOTE_PREFIX + entry.id, {
    type: "basic", iconUrl: ICON, title: "Mika · Teams", priority: 1,
    message: "Mika a préparé une réponse pour " + (S.clean(entry.title, 60) || "une conversation"),
    contextMessage: where,
  }, function () { void chrome.runtime.lastError; });
}

/** Retire les notifications des brouillons qui n'attendent plus (placés, fermés, en pause). */
function syncNotifications(list) {
  const pending = new Set(list.map(function (d) { return NOTE_PREFIX + d.id; }));
  return new Promise(function (resolve) {
    chrome.notifications.getAll(function (all) {
      for (const id of Object.keys(all || {})) {
        if (id.indexOf(NOTE_PREFIX) === 0 && !pending.has(id)) chrome.notifications.clear(id);
      }
      resolve();
    });
  });
}

let acking = null;
let ackAgain = false;
function deliverAcks() {
  if (acking) {
    ackAgain = true;
    return acking;
  }
  acking = (async function () {
    do {
      ackAgain = false;
      await ackLoop();
    } while (ackAgain);
  })().finally(function () { acking = null; });
  return acking;
}

/** Rend les issues, la plus ancienne d'abord ; une issue refusée laisse passer les suivantes. */
async function ackLoop() {
  const tried = new Set();
  for (let i = 0; i < 200; i++) {
    const job = await mutate(function (state) {
      const now = Date.now();
      if (!canAck(state, now)) return null;
      const next = O.pendingAcks(state.runtime.outbox, now).find(function (a) { return !tried.has(a.id); });
      return next ? { settings: state.settings, ack: next } : null;
    });
    if (!job) return;
    tried.add(job.ack.id);
    const result = await request(job.settings, "POST", "/api/teams/outbox/" + encodeURIComponent(job.ack.id),
      job.ack.body);
    const go = await mutate(function (state) {
      const rt = state.runtime;
      const now = Date.now();
      const verdict = O.ackResponse(rt.outbox, job.ack.id, job.ack.body.result, result.status, now);
      if (verdict === "done" || verdict === "forget") {
        rt.ackFailures = 0;
        return true;
      }
      if (verdict === "refused") {
        fail(rt, "Mika refuse une issue (" + (result.error || result.status) + ") : elle sera redite plus tard.");
        return true;
      }
      if (verdict === "dropped") {
        console.warn("[Mika · Teams] issue " + job.ack.id + " (" + job.ack.body.result + ") abandonnée après "
          + O.ACK_REFUSALS_MAX + " refus (" + result.status + ")");
        fail(rt, "Une issue refusée " + O.ACK_REFUSALS_MAX + " fois par Mika a été abandonnée (voir le journal).");
        return true;
      }
      if (verdict === "auth") {
        trouble(rt, result, now);
        return false;
      }
      if (verdict === "slow") {
        rt.ackRetryAt = now + result.retryAfter * 1000;
        fail(rt, "Mika demande de ralentir : issues redites dans " + result.retryAfter + " s.");
        return false;
      }
      rt.ackFailures = (rt.ackFailures || 0) + 1;
      const wait = S.backoffSeconds(rt.ackFailures);
      rt.ackRetryAt = now + wait * 1000;
      fail(rt, troubleText(result) + " — issues redites dans " + wait + " s.");
      return false;
    });
    if (!go) return;
  }
}

function withTimeout(promise, ms) {
  let timer = 0;
  return Promise.race([promise, new Promise(function (_, reject) {
    timer = setTimeout(function () { reject(new Error("pas de réponse de l'onglet")); }, ms);
  })]).finally(function () { clearTimeout(timer); });
}

/**
 * Demande aux onglets Teams d'envoyer. Un onglet où rien n'est parti (pas de script, page qui n'a pas commencé, ou
 * qui dit sûrement que rien n'est parti) passe la main au suivant ; la première issue d'une autre nature arrête la
 * tournée — même douteuse : on ne tente jamais un second onglet après un envoi peut-être parti.
 */
async function sendThroughTabs(item) {
  let last = "aucun onglet Teams ouvert";
  for (const tab of await teamsTabs()) {
    let answer = null;
    let error = null;
    try {
      answer = await withTimeout(chrome.tabs.sendMessage(tab.id, { kind: "send", item: item }), TAB_SEND_TIMEOUT_MS);
    } catch (e) {
      error = e || new Error("erreur");
    }
    const outcome = O.tabOutcome(answer, error);
    if (outcome.result === "retry") {
      last = outcome.reason || last;
      continue;
    }
    return outcome;
  }
  return { result: "retry", reason: last };
}

/**
 * Un message à envoyer : d'abord réclamé auprès du serveur (sauf si ce navigateur détient déjà la réclamation), puis
 * envoyé par un onglet. L'exclusion est revérifiée juste avant chaque geste.
 */
async function sendOne(id) {
  const step = await mutate(function (state) {
    const rt = state.runtime;
    const box = rt.outbox;
    const now = Date.now();
    const e = box.items[id];
    if (!e || !canWrite(state)) return null;
    const p = O.plan(box, id, { now: now, excluded: excludedEntry(state, e) });
    if (p.do === "fail") {
      O.fail(box, id, p.reason, now);
      return { acks: true };
    }
    if (p.do !== "send") return null;
    if (O.isClaimed(box, id)) return { send: true };
    if (!ready(state, now) || !O.beginClaim(box, id, now)) return null;
    return { claim: true, settings: state.settings };
  });
  if (!step) return;
  if (step.acks) {
    await deliverAcks();
    return;
  }
  if (step.claim) {
    const result = await request(step.settings, "POST", "/api/teams/outbox/" + encodeURIComponent(id),
      { result: "sending" });
    const verdict = await mutate(function (state) {
      const rt = state.runtime;
      const now = Date.now();
      const v = O.claimResponse(rt.outbox, id, result.status, now);
      // rien n'est réclamé : on redemandera, après l'attente qu'impose la panne
      if (v === "retry") trouble(rt, result, now);
      return v;
    });
    if (verdict !== "claimed") return;
  }
  const job = await mutate(function (state) {
    const rt = state.runtime;
    const box = rt.outbox;
    const now = Date.now();
    const e = box.items[id];
    if (!e || !canWrite(state)) return null;
    // dernier regard avant d'écrire : une exclusion ajoutée entre-temps l'emporte (rien n'est parti : échec sûr)
    if (excludedEntry(state, e)) {
      O.fail(box, id, O.REASONS.excluded, now);
      return { acks: true };
    }
    if (!O.beginSend(box, id, now)) return null;
    return { item: { id: e.id, conversation: e.conversation, text: e.text, selfName: rt.selfName } };
  });
  if (!job) return;
  if (job.acks) {
    await deliverAcks();
    return;
  }
  const outcome = await sendThroughTabs(job.item);
  await mutate(function (state) { O.sendOutcome(state.runtime.outbox, id, outcome, Date.now()); });
  if (outcome.result === "sent" || outcome.result === "failed") await deliverAcks();
}

let polling = null;
function poll() {
  if (!polling) polling = pollOnce().finally(function () { polling = null; });
  return polling;
}

async function pollOnce() {
  // les issues d'abord : même en pause, même pendant une attente de la file, et avant que la liste ne fasse foi
  await deliverAcks();
  const state = await load();
  if (!ready(state, Date.now())) {
    if (state.settings.paused || !state.settings.key) await refreshDrafts();
    return;
  }
  const got = await request(state.settings, "GET", "/api/teams/outbox");
  const plans = await mutate(function (s) {
    const rt = s.runtime;
    const now = Date.now();
    if (got.status !== 200) {
      trouble(rt, got, now);
      return null;
    }
    const items = (Array.isArray(got.data.items) ? got.data.items : []).map(O.normalizeItem).filter(Boolean);
    const box = rt.outbox;
    O.reconcile(box, items, now);
    rt.lastPollAt = now;
    succeeded(rt);
    const out = { notify: [], send: [] };
    for (const id of Object.keys(box.items)) {
      const e = box.items[id];
      const p = O.plan(box, id, { now: now, excluded: excludedEntry(s, e) });
      if (p.do === "fail") O.fail(box, id, p.reason, now);
      else if (p.do === "uncertain") O.sendOutcome(box, id, { result: "uncertain", reason: p.reason }, now);
      else if (p.do === "notify") {
        e.notifiedAt = now;
        out.notify.push({ id: e.id, title: e.title, kind: e.kind });
      } else if (p.do === "send") out.send.push(id);
    }
    out.send.sort(function (a, b) { return (box.items[a].created_at || 0) - (box.items[b].created_at || 0); });
    return out;
  });
  if (!plans) return;
  for (const entry of plans.notify) notify(entry);
  await refreshDrafts();
  await deliverAcks();
  for (const id of plans.send) await sendOne(id);
}

let pollTimer = 0;
function schedulePoll(ms) {
  if (pollTimer) return;
  pollTimer = setTimeout(function () {
    pollTimer = 0;
    poll().catch(function () { /* noté dans l'état */ });
  }, ms);
}

/** Montre la conversation d'un brouillon : l'onglet Teams, ouvert sur elle quand c'est possible. */
async function openDraft(id) {
  const state = await load();
  const entry = state.runtime.outbox.items[id];
  const link = entry ? O.deepLink(entry) : "";
  const tabs = await teamsTabs();
  const tab = tabs[0];
  if (!tab) {
    await chrome.tabs.create({ url: link || TEAMS_HOME });
    return;
  }
  let here = "";
  try {
    const answer = await chrome.tabs.sendMessage(tab.id, { kind: "where" });
    here = answer && answer.ok && answer.report ? String(answer.report.conversation || "") : "";
  } catch (_) { /* onglet sans script */ }
  const already = entry && here && here.toLowerCase() === entry.conversation.toLowerCase();
  // déjà ouverte : ne pas recharger Teams pour rien, la réponse se placera dès que l'onglet sera visible
  await chrome.tabs.update(tab.id, link && !already ? { url: link, active: true } : { active: true });
  await chrome.windows.update(tab.windowId, { focused: true });
}

// ── Ce que demande la page de réglages ───────────────────────────────────────

function cleanSettings(input, previous) {
  const s = Object.assign({}, previous);
  if (typeof input.base === "string") {
    const address = S.serverAddress(input.base);
    if (address.error) throw new Error(address.error);
    s.base = address.origin;
  }
  if (typeof input.key === "string" && input.key.trim()) {
    const key = input.key.trim();
    if (!/^mtk_\S{4,300}$/.test(key)) throw new Error("une clé Teams commence par mtk_ (Console › Configuration › Teams)");
    s.key = key;
  }
  if (input.clearKey) s.key = "";
  if (typeof input.paused === "boolean") s.paused = input.paused;
  if (typeof input.exclude === "string") s.exclude = T.cut(input.exclude, 4000);
  return s;
}

function status(state) {
  const rt = state.runtime;
  const box = rt.outbox;
  const now = Date.now();
  return {
    settings: { base: state.settings.base, paused: state.settings.paused, exclude: state.settings.exclude },
    keySet: Boolean(state.settings.key), queue: rt.queue.length,
    held: heldMessages(rt, S.exclusions(state.settings.exclude), now).length, stats: rt.stats,
    lastError: rt.lastError, lastErrorAt: rt.lastErrorAt, lastOkAt: rt.lastOkAt, lastPollAt: rt.lastPollAt,
    retryAt: rt.retryAt, authFailed: rt.authFailed, armedAt: rt.armedAt,
    conversations: Object.keys(rt.titles).length, selfFound: Boolean(rt.self), selfNameFound: Boolean(rt.selfName),
    outbox: { waiting: O.waiting(box, now), stats: box.stats, log: box.log },
  };
}

async function testConnection() {
  const state = await load();
  if (!state.settings.key) return { ok: false, text: "Aucune clé Teams enregistrée." };
  const result = await request(state.settings, "GET", "/api/teams/outbox");
  if (result.status === 200) return { ok: true, text: "Mika répond et accepte la clé." };
  if (result.status === 401) return { ok: false, text: "Mika répond, mais la clé est refusée." };
  if (result.status === 403) {
    return { ok: false, text: "Mika répond, mais refuse : " + (result.error || "Teams est désactivé chez elle") };
  }
  if (result.status === 404) {
    return { ok: false, text: "Pas de plugin Teams à cette adresse (mettre à jour Mika)."
      + (result.error ? " — " + result.error : "") };
  }
  if (result.status === 0) return { ok: false, text: result.error };
  return { ok: false, text: "Réponse inattendue : " + result.status + (result.error ? " — " + result.error : "") };
}

async function diagnose() {
  const tabs = await teamsTabs();
  if (!tabs.length) return { ok: false, error: "Aucun onglet Teams ouvert." };
  for (const tab of tabs) {
    try {
      const answer = await chrome.tabs.sendMessage(tab.id, { kind: "diagnose" });
      if (answer) return Object.assign({ tab: tab.title || "" }, answer);
    } catch (_) { /* onglet ouvert avant l'installation : pas de script */ }
  }
  return { ok: false, error: "L'onglet Teams n'a pas encore le script : rechargez-le." };
}

/** Les demandes que peut faire un onglet Teams ; le reste ne vient que des pages de l'extension elle-même. */
const FROM_TABS = new Set(["captured", "pendingDrafts", "claim", "placedResult"]);

async function handle(msg) {
  switch (msg && msg.kind) {
    case "captured": {
      await mutate(function (state) { ingest(state, msg); });
      scheduleFlush(2500);
      return { ok: true };
    }
    case "pendingDrafts":
      return { items: currentDrafts(await load()) };
    case "claim": {
      // revérifié ici, juste avant que l'onglet n'écrive : pause, clé, exclusion du moment
      const ok = await mutate(function (state) {
        const box = state.runtime.outbox;
        const entry = box.items[msg.id];
        if (!entry || !canWrite(state)) return false;
        return O.claim(box, msg.id, Date.now(), excludedEntry(state, entry));
      });
      return { ok: ok };
    }
    case "placedResult": {
      await mutate(function (state) {
        const box = state.runtime.outbox;
        if (msg.ok === true) O.placed(box, msg.id, Date.now());
        else O.release(box, msg.id);
      });
      // les autres onglets reçoivent la liste à jour, la notification part, Mika apprend que c'est placé
      refreshDrafts().catch(function () { /* rien */ });
      deliverAcks().catch(function () { /* noté dans l'état */ });
      return { ok: true };
    }
    case "status":
      return status(await load());
    case "save": {
      let resumed = false;
      const result = await mutate(function (state) {
        const was = Boolean(state.settings.paused);
        state.settings = cleanSettings(msg.settings || {}, state.settings);
        if (Boolean(state.settings.paused) !== was) {
          state.runtime.pauses = S.notePause(state.runtime.pauses, state.settings.paused, Date.now());
          resumed = was;
        }
        state.runtime.authFailed = false;
        state.runtime.retryAt = 0;
        state.runtime.failures = 0;
        state.runtime.ackRetryAt = 0;
        state.runtime.ackFailures = 0;
        state.runtime.lastError = "";
        return status(state);
      });
      if (resumed) resendTitles().catch(function () { /* rien */ });
      refreshDrafts().catch(function () { /* rien */ });
      scheduleFlush(500);
      schedulePoll(800);
      return result;
    }
    case "test":
      return testConnection();
    case "diagnose":
      return diagnose();
    case "flush":
      await mutate(function (state) {
        state.runtime.retryAt = 0;
        state.runtime.failures = 0;
        state.runtime.ackRetryAt = 0;
      });
      await flush();
      await poll();
      return status(await load());
    case "rearm":
      return mutate(function (state) {
        state.runtime.armedAt = Date.now();
        state.runtime.queue = [];
        return status(state);
      });
    case "clearLog":
      return mutate(function (state) {
        state.runtime.outbox.log = [];
        return status(state);
      });
    case "openDraft":
      await openDraft(String(msg.id || ""));
      return { ok: true };
    default:
      return { ok: false, error: "demande inconnue" };
  }
}

chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
  const ownPage = typeof sender.url === "string" && sender.url.indexOf(chrome.runtime.getURL("")) === 0;
  if (!ownPage && (!msg || !FROM_TABS.has(msg.kind) || !sender.tab)) return false;
  handle(msg).then(reply, function (e) { reply({ ok: false, error: String(e && e.message ? e.message : e) }); });
  return true;
});

chrome.notifications.onClicked.addListener(function (noteId) {
  if (noteId.indexOf(NOTE_PREFIX) !== 0) return;
  openDraft(noteId.slice(NOTE_PREFIX.length)).catch(function () { /* l'onglet a disparu entre-temps */ });
  chrome.notifications.clear(noteId);
});

function tick() {
  return flush().then(poll).catch(function () { /* noté dans l'état */ });
}

function arm() {
  chrome.alarms.clear("mika-flush"); // l'alarme de la première version
  chrome.alarms.create("mika-tick", { periodInMinutes: 0.5 });
  locked(async function () { await save(await load()); });
}

chrome.runtime.onInstalled.addListener(arm);
chrome.runtime.onStartup.addListener(arm);
chrome.alarms.onAlarm.addListener(function (alarm) {
  if (alarm.name === "mika-tick") tick();
});
