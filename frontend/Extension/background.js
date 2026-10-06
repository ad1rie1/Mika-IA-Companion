/*
 * Le service d'arrière-plan : il reçoit ce que les onglets Teams ont capté, décide de ce qui part (nouveau, pas
 * exclu, pas en pause), le garde en file, et l'envoie à Mika comme signal d'appareil (`POST /api/perceptions`).
 *
 * Un service d'extension MV3 peut être arrêté à tout moment : tout l'état vit dans `chrome.storage.local`, et
 * chaque lecture-écriture passe par un même verrou pour que deux lots captés en même temps ne s'écrasent pas.
 */
/* global importScripts, MikaTeamsExtract, MikaTeamsSignals */
importScripts("lib/extract.js", "lib/signals.js");

const X = MikaTeamsExtract;
const S = MikaTeamsSignals;

const TEAMS_TABS = ["https://teams.microsoft.com/*", "https://teams.cloud.microsoft/*", "https://teams.live.com/*"];
const QUEUE_MAX = 500;
const LOG_MAX = 30;
const TITLES_MAX = 3000;
const REQUEST_TIMEOUT_MS = 15000;

const DEFAULT_SETTINGS = {
  base: "http://127.0.0.1:8001",
  token: "",
  device: "Teams",
  paused: false,
  skipOwn: false,
  exclude: "",
  sensitivity: 2,
  pertinence: Object.assign({}, S.PERTINENCE),
};

function freshRuntime() {
  return {
    armedAt: 0, seen: {}, queue: [], titles: {}, self: "", sent: [], log: [],
    stats: { received: 0, admitted: 0, delivered: 0, signals: 0, dropped: {}, bySource: { network: 0, idb: 0 } },
    lastError: "", lastErrorAt: 0, lastOkAt: 0, retryAt: 0, authFailed: false, failures: 0,
  };
}

// ── L'état ─────────────────────────────────────────────────────────────────

let chain = Promise.resolve();
function locked(fn) {
  const run = chain.then(fn, fn);
  chain = run.catch(function () { /* l'erreur appartient à l'appelant */ });
  return run;
}

async function load() {
  const got = await chrome.storage.local.get(["settings", "runtime"]);
  const settings = Object.assign({}, DEFAULT_SETTINGS, got.settings || {});
  settings.pertinence = Object.assign({}, S.PERTINENCE, settings.pertinence || {});
  const runtime = Object.assign(freshRuntime(), got.runtime || {});
  runtime.stats = Object.assign(freshRuntime().stats, runtime.stats || {});
  if (!runtime.armedAt) runtime.armedAt = Date.now();
  return { settings: settings, runtime: runtime };
}

function save(state) {
  return chrome.storage.local.set({ settings: state.settings, runtime: state.runtime });
}

function fail(rt, text) {
  rt.lastError = text;
  rt.lastErrorAt = Date.now();
}

// ── Ce qui arrive des onglets ────────────────────────────────────────────────

function learnTitles(rt, conversations, now) {
  for (const c of conversations) {
    const prev = rt.titles[c.id] || {};
    rt.titles[c.id] = { title: c.title || prev.title || "", kind: X.conversationKind(c.id, c.threadType), at: now };
  }
  const ids = Object.keys(rt.titles);
  if (ids.length > TITLES_MAX) {
    ids.sort(function (a, b) { return rt.titles[a].at - rt.titles[b].at; });
    for (const id of ids.slice(0, ids.length - TITLES_MAX)) delete rt.titles[id];
  }
}

function kindOf(rt, conv) {
  const known = rt.titles[conv];
  return known ? known.kind : X.conversationKind(conv, "");
}

function ingest(state, batch) {
  const rt = state.runtime;
  const settings = state.settings;
  const now = Date.now();
  if (batch.self) rt.self = batch.self;
  learnTitles(rt, batch.conversations || [], now);
  const exclude = S.exclusions(settings.exclude);
  for (const m of batch.messages || []) {
    rt.stats.received++;
    rt.stats.bySource[m.source] = (rt.stats.bySource[m.source] || 0) + 1;
    const known = rt.titles[m.conv];
    const reason = S.admit(m, {
      now: now, armedAt: rt.armedAt, seen: rt.seen, paused: settings.paused, title: known ? known.title : "",
      kind: kindOf(rt, m.conv), exclude: exclude, skipOwn: settings.skipOwn, selfId: rt.self,
    });
    if (reason === "déjà vu") continue;
    if (reason !== "vide") rt.seen[m.id] = m.time;
    if (reason) {
      rt.stats.dropped[reason] = (rt.stats.dropped[reason] || 0) + 1;
      continue;
    }
    rt.queue.push({ id: m.id, conv: m.conv, author: m.author, authorId: m.authorId, time: m.time, text: m.text,
      mentionsSelf: S.mentionsSelf(m, rt.self) });
    rt.stats.admitted++;
  }
  if (rt.queue.length > QUEUE_MAX) {
    rt.queue.sort(function (a, b) { return a.time - b.time; });
    const over = rt.queue.length - QUEUE_MAX;
    rt.queue.splice(0, over);
    rt.stats.dropped["file pleine"] = (rt.stats.dropped["file pleine"] || 0) + over;
  }
  rt.seen = S.pruneSeen(rt.seen, now);
}

// ── L'envoi ────────────────────────────────────────────────────────────────

function endpoint(base) {
  return new URL("/api/perceptions", base).toString();
}

async function post(settings, body) {
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(endpoint(settings.base), {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + settings.token },
      body: JSON.stringify(body),
      signal: controller.signal,
      credentials: "omit", // jamais la session d'un navigateur connecté à la console : seul le jeton compte
      cache: "no-store",
    });
    let data = {};
    try {
      data = await response.json();
    } catch (_) { /* corps vide ou illisible */ }
    return { status: response.status, error: String(data.error || ""), seq: data.seq,
      retryAfter: Number(response.headers.get("retry-after")) || 60 };
  } catch (e) {
    return { status: 0, error: e && e.name === "AbortError" ? "pas de réponse en 15 s"
      : "Mika injoignable (" + (e && e.message ? e.message : "réseau") + ")" };
  } finally {
    clearTimeout(timer);
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

function flush() {
  return locked(async function () {
    const state = await load();
    const rt = state.runtime;
    const settings = state.settings;
    const now = Date.now();
    if (settings.paused || !settings.token || rt.authFailed || rt.retryAt > now || !rt.queue.length) return;
    // une exclusion ajoutée, ou un nom appris après coup, vaut aussi pour ce qui attend
    const exclude = S.exclusions(settings.exclude);
    rt.queue = rt.queue.filter(function (m) {
      const known = rt.titles[m.conv];
      if (!S.isExcluded(m.conv, known ? known.title : "", exclude)) return true;
      rt.stats.dropped.exclue = (rt.stats.dropped.exclue || 0) + 1;
      return false;
    });
    const info = function (conv) {
      const known = rt.titles[conv];
      const kind = kindOf(rt, conv);
      return { kind: kind, title: S.titleFor(conv, { title: known ? known.title : "", kind: kind }, rt.queue, rt.self) };
    };
    const signals = S.compose(rt.queue, info);
    for (const signal of signals) {
      const slot = S.takeSlot(rt.sent, Date.now(), S.LIMITS.perMinute);
      rt.sent = slot.recent;
      if (!slot.free) {
        scheduleFlush(Math.max(1000, 60000 - (Date.now() - rt.sent[0])));
        break;
      }
      const result = await post(settings, {
        device: settings.device || "Teams",
        text: signal.text,
        pertinence: S.pertinenceFor(signal.kind, signal.mentioned, settings.pertinence),
        sensitivity: settings.sensitivity,
      });
      const done = new Set(signal.ids);
      if (result.status === 202) {
        rt.queue = rt.queue.filter(function (m) { return !done.has(m.id); });
        rt.sent.push(Date.now());
        rt.stats.delivered += signal.ids.length;
        rt.stats.signals++;
        rt.log.unshift({ at: Date.now(), text: signal.text, seq: result.seq || null });
        rt.log = rt.log.slice(0, LOG_MAX);
        rt.lastOkAt = Date.now();
        rt.failures = 0;
        rt.lastError = "";
      } else if (result.status === 429) {
        rt.retryAt = Date.now() + result.retryAfter * 1000;
        fail(rt, "Mika reçoit trop de signaux : reprise dans " + result.retryAfter + " s.");
        break;
      } else if (result.status === 401 || result.status === 403) {
        rt.authFailed = true;
        fail(rt, "Mika refuse le jeton. Collez le jeton des appareils (Console › Configuration › Appareils).");
        break;
      } else if (result.status === 400 || result.status === 413) {
        rt.queue = rt.queue.filter(function (m) { return !done.has(m.id); });
        rt.stats.dropped["refusé par Mika"] = (rt.stats.dropped["refusé par Mika"] || 0) + signal.ids.length;
        fail(rt, "Un signal refusé par Mika : " + (result.error || result.status));
      } else {
        rt.failures++;
        const wait = Math.min(300, 15 * Math.pow(2, rt.failures - 1));
        rt.retryAt = Date.now() + wait * 1000;
        fail(rt, (result.status === 404 ? "Pas de route /api/perceptions à cette adresse (est-ce bien backendv2 ?)"
          : result.error || "Mika a répondu " + result.status) + " — nouvel essai dans " + wait + " s.");
        break;
      }
    }
    await save(state);
  });
}

// ── Ce que demande la page de réglages ───────────────────────────────────────

function cleanSettings(input, previous) {
  const s = Object.assign({}, previous);
  if (typeof input.base === "string") {
    const url = new URL(input.base.trim());
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("une adresse http:// ou https://");
    s.base = url.origin;
  }
  if (typeof input.token === "string" && input.token.trim()) s.token = input.token.trim();
  if (input.clearToken) s.token = "";
  if (typeof input.device === "string") s.device = S.clean(input.device, 40) || "Teams";
  if (typeof input.paused === "boolean") s.paused = input.paused;
  if (typeof input.skipOwn === "boolean") s.skipOwn = input.skipOwn;
  if (typeof input.exclude === "string") s.exclude = input.exclude.slice(0, 4000);
  if (input.sensitivity !== undefined) s.sensitivity = Math.max(0, Math.min(3, Math.round(Number(input.sensitivity)) || 0));
  if (input.pertinence && typeof input.pertinence === "object") {
    const p = Object.assign({}, s.pertinence);
    for (const k of Object.keys(S.PERTINENCE)) {
      const v = Number(input.pertinence[k]);
      if (isFinite(v)) p[k] = Math.max(0, Math.min(1, v));
    }
    s.pertinence = p;
  }
  return s;
}

function status(state) {
  const rt = state.runtime;
  const settings = Object.assign({}, state.settings, { token: "" });
  return {
    settings: settings, tokenSet: Boolean(state.settings.token), queue: rt.queue.length, stats: rt.stats,
    lastError: rt.lastError, lastErrorAt: rt.lastErrorAt, lastOkAt: rt.lastOkAt, retryAt: rt.retryAt,
    authFailed: rt.authFailed, armedAt: rt.armedAt, log: rt.log, conversations: Object.keys(rt.titles).length,
    selfFound: Boolean(rt.self),
  };
}

async function testConnection() {
  const state = await load();
  if (!state.settings.token) return { ok: false, text: "Aucun jeton enregistré." };
  // un texte vide : Mika vérifie le jeton avant le texte, et refuse le texte sans rien écrire dans son journal
  const result = await post(state.settings, { device: state.settings.device || "Teams", text: "" });
  if (result.status === 400) return { ok: true, text: "Mika répond et accepte le jeton." };
  if (result.status === 401 || result.status === 403) return { ok: false, text: "Mika répond, mais refuse le jeton." };
  if (result.status === 404) return { ok: false, text: "Pas de route /api/perceptions à cette adresse." };
  if (result.status === 0) return { ok: false, text: result.error };
  return { ok: false, text: "Réponse inattendue : " + result.status + (result.error ? " — " + result.error : "") };
}

async function diagnose() {
  const tabs = await chrome.tabs.query({ url: TEAMS_TABS });
  if (!tabs.length) return { ok: false, error: "Aucun onglet Teams ouvert." };
  for (const tab of tabs) {
    try {
      const answer = await chrome.tabs.sendMessage(tab.id, { kind: "diagnose" });
      if (answer) return Object.assign({ tab: tab.title || "" }, answer);
    } catch (_) { /* onglet ouvert avant l'installation : pas de script */ }
  }
  return { ok: false, error: "L'onglet Teams n'a pas encore le script : rechargez-le." };
}

async function handle(msg) {
  switch (msg && msg.kind) {
    case "captured": {
      await locked(async function () {
        const state = await load();
        ingest(state, msg);
        await save(state);
      });
      scheduleFlush(2500);
      return { ok: true };
    }
    case "status":
      return status(await load());
    case "save": {
      const result = await locked(async function () {
        const state = await load();
        state.settings = cleanSettings(msg.settings || {}, state.settings);
        state.runtime.authFailed = false;
        state.runtime.retryAt = 0;
        state.runtime.failures = 0;
        state.runtime.lastError = "";
        await save(state);
        return status(state);
      });
      scheduleFlush(500);
      return result;
    }
    case "test":
      return testConnection();
    case "diagnose":
      return diagnose();
    case "flush":
      await locked(async function () {
        const state = await load();
        state.runtime.retryAt = 0;
        state.runtime.authFailed = false;
        await save(state);
      });
      await flush();
      return status(await load());
    case "rearm":
      return locked(async function () {
        const state = await load();
        state.runtime.armedAt = Date.now();
        state.runtime.queue = [];
        await save(state);
        return status(state);
      });
    case "clearLog":
      return locked(async function () {
        const state = await load();
        state.runtime.log = [];
        await save(state);
        return status(state);
      });
    default:
      return { ok: false, error: "demande inconnue" };
  }
}

chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
  // les onglets Teams n'ont droit qu'à « captured » ; le reste ne vient que des pages de l'extension elle-même
  const ownPage = typeof sender.url === "string" && sender.url.indexOf(chrome.runtime.getURL("")) === 0;
  if (!ownPage && (!msg || msg.kind !== "captured")) return false;
  handle(msg).then(reply, function (e) { reply({ ok: false, error: String(e && e.message ? e.message : e) }); });
  return true;
});

function arm() {
  chrome.alarms.create("mika-flush", { periodInMinutes: 1 });
  locked(async function () { await save(await load()); });
}

chrome.runtime.onInstalled.addListener(arm);
chrome.runtime.onStartup.addListener(arm);
chrome.alarms.onAlarm.addListener(function (alarm) {
  if (alarm.name === "mika-flush") flush().catch(function () { /* noté dans l'état */ });
});
