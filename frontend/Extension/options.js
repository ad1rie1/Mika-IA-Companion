/* La page de réglages (aussi la fenêtre du bouton de l'extension). Tout passe par le service d'arrière-plan ;
   les textes captés ou écrits par Mika ne sont jamais insérés comme HTML. La clé n'est jamais relue. */
/* global MikaTeamsSignals */
"use strict";

const $ = (id) => document.getElementById(id);
const REASONS = {
  "ancien": "trop anciens (plus de 24 h)",
  "avant l'activation": "antérieurs à l'activation",
  "exclue": "conversations exclues",
  "en pause": "écrits pendant une pause",
  "système": "notifications de Teams",
  "sans conversation": "sans conversation connue",
  "identifiant illisible": "à l'identifiant illisible",
  "file pleine": "file pleine",
  "refusé par Mika": "refusés par Mika",
  "trop gros": "trop gros pour Mika",
  "erreur de Mika": "écartés après des erreurs répétées de Mika",
};
const RESULTS = { placed: "brouillon placé", sent: "envoyé", failed: "échec", uncertain: "issue incertaine",
  dropped: "issue non transmise" };

let loaded = false;
/** L'adresse que le service a enregistrée (son origine), pour savoir si le champ en dit une autre. */
let savedBase = "";

function ask(kind, extra) {
  return chrome.runtime.sendMessage(Object.assign({ kind: kind }, extra || {}));
}

function when(ms) {
  if (!ms) return "jamais";
  const d = new Date(ms);
  const sameDay = new Date().toDateString() === d.toDateString();
  return sameDay ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

function yes(v) {
  return v ? "oui" : "non";
}

/** Le modèle d'envoi par le worker de Teams (ADR 0301) : capté quand, pour quelles conversations. */
function sendTemplateText(at) {
  const t = at || {};
  const latest = Math.max(Number(t.bilateral) || 0, Number(t.group) || 0);
  if (!latest) {
    return "pas encore : envoie une fois un message à la main dans Teams (le modèle d'envoi se capte alors)";
  }
  const kinds = [t.bilateral ? "tête-à-tête" : "", t.group ? "groupes" : ""].filter(Boolean).join(" et ");
  return "possible pour les tête-à-tête et les groupes (modèle capté le " + when(latest) + " sur des " + kinds
    + ") ; canaux et réunions par la zone de saisie";
}

function fillStats(status) {
  const st = status.stats;
  const out = status.outbox.stats;
  const dropped = Object.entries(st.dropped || {}).filter(([, n]) => n > 0)
    .map(([reason, n]) => n + " " + (REASONS[reason] || reason)).join(", ");
  const rows = [
    ["En attente d'envoi", String(status.queue) + (status.held ? " (dont " + status.held
      + " retenu(s) le temps d'apprendre le nom de leur conversation)" : "")],
    ["Transmis à Mika", st.delivered + " message(s), dont " + (st.own || 0) + " de toi, en " + (st.posts || 0) + " envoi(s)"],
    ["Dernier envoi", when(status.lastOkAt)],
    ["Dernière relève", when(status.lastPollAt)],
    ["Écrit par Mika", out.placed + " brouillon(s) placé(s), " + out.sent + " message(s) envoyé(s), "
      + out.failed + " échec(s)" + (out.uncertain ? ", " + out.uncertain + " issue(s) incertaine(s)" : "")],
    ["Captés", st.received + " (en direct : " + (st.bySource.worker || 0) + ", réseau : " + (st.bySource.network || 0)
      + ", base locale : " + (st.bySource.idb || 0) + ")"],
    ["Connexion en direct", liveText(status.live)],
    ["Envoi sans ouvrir la conversation", sendTemplateText(status.sendTemplates)],
    ["Images envoyées à Mika", st.images ? st.images.sent + " (écartées : " + st.images.skipped + ", échecs : "
      + st.images.failed + ")" : "0"],
    ["Photos de profil envoyées à Mika", st.photos ? st.photos.sent + " (écartées : " + st.photos.skipped
      + ", échecs : " + st.photos.failed + ")" : "0"],
    ["Écartés", dropped || "aucun"],
    ["Conversations connues", String(status.conversations)],
    ["Ton identité Teams", status.selfFound ? (status.selfNameFound ? "connue, avec ton nom" : "connue, nom pas encore vu")
      : "pas encore trouvée"],
    ["Actif depuis", when(status.armedAt)],
  ];
  if (status.retryAt > Date.now()) rows.splice(1, 0, ["Prochain essai", when(status.retryAt)]);
  const dl = $("stats");
  dl.replaceChildren();
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    dl.append(dt, dd);
  }
}

function fillWaiting(list) {
  const ul = $("waiting");
  ul.replaceChildren();
  for (const item of list) {
    const li = document.createElement("li");
    const text = document.createElement("span");
    const what = item.mode === "send" ? "À envoyer dans " : "Brouillon pour ";
    let line = what + (item.title || "une conversation");
    if (item.expires_at) line += " — jusqu'à " + when(item.expires_at);
    if (item.lastReason) line += " (" + item.lastReason + ")";
    text.textContent = line;
    const open = document.createElement("button");
    open.className = "small";
    open.textContent = "Ouvrir dans Teams";
    open.addEventListener("click", () => ask("openDraft", { id: item.id }));
    li.append(text, open);
    ul.append(li);
  }
  $("waitingEmpty").hidden = Boolean(list.length);
}

function fillLog(entries) {
  const log = $("log");
  log.replaceChildren();
  for (const entry of entries) {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = when(entry.at);
    const head = document.createElement("strong");
    head.textContent = (RESULTS[entry.result] || entry.result) + (entry.reason ? " : " + entry.reason : "")
      + " — " + (entry.title || "une conversation");
    li.append(time, head);
    if (entry.text) li.append(document.createElement("br"), document.createTextNode(entry.text));
    log.append(li);
  }
  $("logEmpty").hidden = Boolean(entries.length);
}

function liveText(lv) {
  if (!lv) return "—";
  if (lv.connected) {
    return "ouverte depuis " + when(lv.since) + (lv.lastPushAt ? ", dernière poussée " + when(lv.lastPushAt) : "");
  }
  return "fermée" + (lv.lastError ? " (" + lv.lastError + ")" : " — elle s'ouvre quand un onglet Teams l'est");
}

/** Un chargement sans nouvelles depuis 3 min : l'onglet a été fermé ou rechargé en route (le service le tient
 * pour interrompu et accepte d'en relancer un). */
function stale(h) {
  return Date.now() - (h.lastAt || h.startedAt || 0) > 3 * 60 * 1000;
}

function historyText(h) {
  if (!h) return "";
  const counts = h.sent + " envoyé(s) : " + h.accepted + " nouveau(x), " + h.known + " déjà connu(s), " + h.twins
    + " doublon(s) écarté(s)" + (h.dropped ? ", " + h.dropped + " laissé(s) de côté" : "");
  if (h.state === "running" && stale(h)) {
    return "Interrompu (plus de nouvelles depuis " + when(h.lastAt || h.startedAt) + ") — " + counts
      + ". Relance-le : ce qui est déjà chez Mika n'est pas rangé deux fois.";
  }
  if (h.state === "running") return "En cours : " + h.done + " / " + (h.total || "?") + " conversation(s) — " + counts;
  if (h.state === "done") return "Fini " + when(h.finishedAt) + " — " + counts;
  return "Arrêté" + (h.error ? " : " + h.error : "") + " — " + counts;
}

function fill(status) {
  const s = status.settings;
  savedBase = s.base;
  if (!loaded) {
    $("base").value = s.base;
    $("exclude").value = s.exclude;
    loaded = true;
  }
  $("paused").checked = s.paused;
  $("key").placeholder = status.keySet ? "définie — laisser vide pour la garder" : "aucune";

  const pill = $("pill");
  let label = "actif";
  let tone = "ok";
  if (s.paused) { label = "en pause"; tone = "warn"; }
  else if (!status.keySet) { label = "clé manquante"; tone = "warn"; }
  else if (status.authFailed) { label = "clé refusée"; tone = "bad"; }
  else if (status.lastError) { label = "en difficulté"; tone = "bad"; }
  pill.textContent = label;
  pill.className = "pill " + tone;

  fillStats(status);
  const hist = $("historyResult");
  if (status.history) {
    hist.textContent = historyText(status.history);
    hist.className = "note " + (status.history.state === "error" ? "bad-text" : status.history.state === "done" ? "ok-text" : "");
  }
  $("history").disabled = Boolean(status.history && status.history.state === "running" && !stale(status.history));
  fillWaiting(status.outbox.waiting || []);
  fillLog(status.outbox.log || []);

  const err = $("error");
  err.hidden = !status.lastError;
  err.textContent = status.lastError ? status.lastError + " (" + when(status.lastErrorAt) + ")" : "";
}

/** Ce que le service attend de la page pour recharger les onglets Teams après lui (`background.js`). */
const RELOAD_TABS_KEY = "reloadTeamsTabs";
/** La réponse d'un service plus ancien que cette page : il ne connaît pas la demande. */
const OUTDATED = "demande inconnue";

/**
 * Chrome relit cette page sur le disque à chaque ouverture, mais ne recharge le service qu'avec l'extension : après
 * une mise à jour des fichiers, la page est neuve et le service ancien. Les deux versions diffèrent : on le dit.
 */
async function checkVersion() {
  const loaded = chrome.runtime.getManifest().version;
  let onDisk = loaded;
  try {
    const r = await fetch(chrome.runtime.getURL("manifest.json"), { cache: "no-store" });
    onDisk = String((await r.json()).version || loaded);
  } catch (_) { /* rien à comparer */ }
  if (onDisk !== loaded) {
    showStale("La version " + onDisk + " de l'extension est sur le disque, mais Chrome fait encore tourner la "
      + loaded + " : certains boutons ne marcheront pas.");
  }
}

function showStale(why) {
  $("staleText").textContent = why + " Recharge-la : l'onglet Teams sera rechargé avec elle.";
  $("stale").hidden = false;
}

/** Le service n'a pas reconnu la demande : il est plus ancien que cette page. */
function outdated(result) {
  if (!result || result.error !== OUTDATED) return false;
  showStale("Le service de l'extension est plus ancien que cette page.");
  return true;
}

async function refresh() {
  try {
    fill(await ask("status"));
  } catch (e) {
    $("pill").textContent = "service arrêté";
  }
}

function say(text, ok) {
  const out = $("testResult");
  out.textContent = text;
  out.className = "note " + (ok ? "ok-text" : "bad-text");
}

function typedBase() {
  return $("base").value.trim() || "http://127.0.0.1:8001";
}

/** Une clé collée, ou une adresse autre que celle enregistrée : ce qu'on voit n'est pas ce que le service a. */
function unsaved() {
  return Boolean($("key").value.trim()) || MikaTeamsSignals.serverAddress(typedBase()).origin !== savedBase;
}

/** Enregistrer ce qui est tapé ; rend vrai si le service l'a gardé. */
async function save() {
  const base = typedBase();
  // en http seulement sur cette machine ; ailleurs, https (la même règle que le service d'arrière-plan)
  const address = MikaTeamsSignals.serverAddress(base);
  if (address.error) {
    say("Adresse refusée : " + address.error + ".", false);
    return false;
  }
  // Le réglage part au service d'abord, sans attendre : la fenêtre du bouton se ferme parfois quand Chrome affiche sa
  // demande de permission, et la clé collée se perdait avec elle. La demande suit dans le même geste (Chrome l'exige
  // pendant le clic) ; sans la permission, le service le dit à chaque essai, et un nouvel « Enregistrer » la redemande.
  const saving = ask("save", { settings: { base: base, key: $("key").value, exclude: $("exclude").value } });
  let granted = true;
  let why = "";
  if (!address.local) {
    try {
      granted = await chrome.permissions.request({ origins: [address.origin + "/*"] });
    } catch (e) {
      granted = false;
      why = e && e.message ? " (" + e.message + ")" : "";
    }
  }
  let result;
  try {
    result = await saving;
  } catch (e) {
    result = { error: "le service de l'extension ne répond pas — la recharger dans chrome://extensions" };
  }
  if (!(result && result.settings)) {
    say("Refusé : " + ((result && result.error) || "réglage illisible"), false);
    return false;
  }
  $("key").value = "";
  loaded = false;
  fill(result);
  if (granted) say("Enregistré.", true);
  else say("Enregistré, mais Chrome n'a pas donné l'accès à " + address.origin + why
    + " : sans lui, l'extension ne peut pas joindre Mika. « Enregistrer » à nouveau, puis « Autoriser ».", false);
  return true;
}

$("save").addEventListener("click", () => { save(); });
$("save2").addEventListener("click", () => { save(); });

$("paused").addEventListener("change", async () => {
  fill(await ask("save", { settings: { paused: $("paused").checked } }));
});

$("test").addEventListener("click", async () => {
  // on teste ce qu'on voit : une clé collée ou une adresse changée s'enregistre d'abord (dans le même clic, que la
  // permission de Chrome exige)
  if (unsaved() && !(await save())) return;
  const out = $("testResult");
  out.textContent = "…";
  out.className = "note";
  let result;
  try {
    result = await ask("test");
  } catch (e) {
    result = { ok: false, text: "Le service de l'extension ne répond pas : la recharger dans chrome://extensions." };
  }
  say(result.text, result.ok);
});

$("history").addEventListener("click", async () => {
  const out = $("historyResult");
  let result = null;
  try {
    result = await ask("history");
  } catch (_) { /* le service dort ou a été rechargé */ }
  if (!result || !result.ok) {
    out.textContent = outdated(result) ? "Le service de l'extension n'a pas encore cette fonction : recharge-la (en haut)."
      : (result && result.error) || "Le service de l'extension ne répond pas.";
    out.className = "note bad-text";
    return;
  }
  refresh();
});

$("reload").addEventListener("click", async () => {
  try {
    await chrome.storage.local.set({ [RELOAD_TABS_KEY]: Date.now() });
  } catch (_) { /* les onglets resteront à recharger à la main */ }
  chrome.runtime.reload();
});

$("flush").addEventListener("click", async () => {
  fill(await ask("flush"));
});

$("rearm").addEventListener("click", async () => {
  fill(await ask("rearm"));
});

$("clearLog").addEventListener("click", async () => {
  fill(await ask("clearLog"));
});

/** La ligne du diagnostic sur l'envoi par le worker de Teams (ADR 0301) : possible ou non, et pourquoi. */
function workerSendText(c) {
  const at = c.workerTemplates || {};
  const latest = Math.max(Number(at.bilateral) || 0, Number(at.group) || 0);
  if (c.workerSendPossible) return "oui (modèle capté le " + when(latest) + ")";
  if (!latest) return "non (aucun modèle : envoie une fois un message à la main dans Teams)";
  return "non (modèle capté le " + when(latest) + ", mais le worker de Teams n'a encore rien reçu dans cet onglet)";
}

$("diagnose").addEventListener("click", async () => {
  const out = $("diagnostic");
  out.hidden = false;
  out.textContent = "…";
  const result = await ask("diagnose");
  if (!result || !result.ok) {
    out.textContent = (result && result.error) || "Pas de réponse.";
    return;
  }
  const r = result.report;
  const c = r.compose || {};
  const lines = [
    "Onglet : " + (result.tab || r.url),
    "Ouvert depuis : " + when(r.startedAt),
    "Identité trouvée (pour reconnaître tes messages) : " + yes(r.selfFound),
    "",
    "Réseau : " + r.network.responses + " réponse(s) lue(s), " + r.network.frames + " trame(s), "
      + r.network.messages + " message(s), " + r.network.errors + " erreur(s)",
    "Worker de Teams : " + (r.worker ? (r.worker.hooked ? "écouté" : "pas vu (onglet ouvert avant l'extension ?)")
      + ", " + r.worker.received + " réponse(s), " + r.worker.kept + " avec des messages, " + r.worker.messages
      + " message(s), " + r.worker.errors + " erreur(s)" : "—"),
    "Commandes de la page au worker : " + (r.worker ? (r.worker.commands || 0) + " vue(s), " + (r.worker.templates || 0)
      + " envoi(s) de la page lu(s) comme modèle" + (r.worker.templateRefused ? ", " + r.worker.templateRefused
        + " écarté(s)" + (r.worker.templateIssue ? " (le dernier : " + r.worker.templateIssue + ")" : "") : "") : "—"),
    "Base locale : " + (r.idb.available ? r.idb.syncs + " synchro(s), la dernière en " + r.idb.lastSyncMs + " ms, "
      + r.idb.conversations + " conversation(s) suivie(s), " + r.idb.read + " relue(s) ciblées, " + r.idb.messages
      + " message(s), " + r.idb.errors + " erreur(s)" : "indisponible dans ce navigateur"),
  ];
  if (r.images) {
    lines.push("Images : " + r.images.downloaded + " téléchargée(s), " + r.images.sent + " envoyée(s), "
      + r.images.skipped + " écartée(s), " + r.images.failed + " échec(s)");
  }
  if (r.photos) {
    lines.push("Photos de profil : " + r.photos.asked + " demandée(s), " + r.photos.downloaded + " téléchargée(s), "
      + r.photos.sent + " envoyée(s), " + r.photos.skipped + " écartée(s), " + r.photos.failed + " échec(s)"
      + (r.photos.noAvatarSeen ? " — aucun avatar encore affiché dans l'onglet (" + r.photos.noAvatarSeen + " fois)" : ""));
  }
  if (r.history && (r.history.running || r.history.total)) {
    lines.push("Historique dans cet onglet : " + (r.history.running ? "en cours, " : "") + r.history.done + " / "
      + r.history.total + " conversation(s), " + r.history.messages + " message(s)"
      + (r.history.error ? " — " + r.history.error : ""));
  }
  lines.push("", "Conversations dont le nom est connu : " + r.conversationTitles,
    "Profils de personnes lus dans Teams : " + (r.profiles || 0) + " (joints aux messages de ces personnes)",
    "Messages passés à l'extension : " + r.sent);
  const rl = result.relayed;
  if (rl) {
    // ce qui sépare « passés à l'extension » de « Captés » : le trajet de l'onglet au service d'arrière-plan
    lines.push("Transmis au service : " + rl.messages + " message(s) en " + rl.batches + " lot(s), " + rl.accepted
      + " accepté(s), " + rl.lost + " perdu(s)"
      + (rl.lastError ? " — dernière erreur (" + when(rl.lastErrorAt) + ") : " + rl.lastError
        + (/invalidated|invalidé/i.test(rl.lastError) ? " → recharge l'onglet Teams" : "") : ""));
  }
  lines.push("",
    "Zone de saisie trouvée : " + yes(c.editorFound),
    "Conversation active connue : " + yes(c.activeConversationKnown),
    "Envoi par le worker de Teams possible : " + workerSendText(c),
    "Envoi par le service de chat possible : " + yes(c.chatSendPossible),
    "Brouillons en attente dans cet onglet : " + (c.drafts || 0),
    "Depuis l'ouverture : " + (c.placed || 0) + " brouillon(s) placé(s), " + (c.sentByWorker || 0)
      + " envoi(s) par le worker de Teams, " + (c.sentByService || 0) + " par le service de chat, "
      + (c.sentByComposeBox || 0) + " par la zone de saisie, " + (c.uncertain || 0) + " incertain(s), "
      + (c.errors || 0) + " erreur(s)");
  if (c.workerRefused || c.workerSilent || c.workerLate) {
    lines.push("Worker de Teams : " + (c.workerRefused || 0) + " envoi(s) refusé(s) (passés à la voie suivante), "
      + (c.workerSilent || 0) + " sans réponse à temps (issue incertaine), " + (c.workerLate || 0)
      + " réponse(s) arrivée(s) trop tard");
  }
  out.textContent = lines.join("\n");
});

checkVersion();
refresh();
setInterval(refresh, 3000);
