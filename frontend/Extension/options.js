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
    ["Captés", st.received + " (réseau : " + (st.bySource.network || 0) + ", base locale : " + (st.bySource.idb || 0) + ")"],
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

function fill(status) {
  const s = status.settings;
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
  fillWaiting(status.outbox.waiting || []);
  fillLog(status.outbox.log || []);

  const err = $("error");
  err.hidden = !status.lastError;
  err.textContent = status.lastError ? status.lastError + " (" + when(status.lastErrorAt) + ")" : "";
}

async function refresh() {
  try {
    fill(await ask("status"));
  } catch (e) {
    $("pill").textContent = "service arrêté";
  }
}

async function save() {
  const base = $("base").value.trim() || "http://127.0.0.1:8001";
  // en http seulement sur cette machine ; ailleurs, https (la même règle que le service d'arrière-plan)
  const address = MikaTeamsSignals.serverAddress(base);
  if (address.error) {
    $("testResult").textContent = "Adresse refusée : " + address.error + ".";
    return;
  }
  if (!address.local) {
    // une adresse hors de cette machine demande une permission, accordée par un clic
    const origin = address.origin + "/*";
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      $("testResult").textContent = "Sans permission, l'extension ne peut pas joindre " + base + ".";
      return;
    }
  }
  const result = await ask("save", { settings: { base: base, key: $("key").value, exclude: $("exclude").value } });
  if (result && result.settings) {
    $("key").value = "";
    $("testResult").textContent = "Enregistré.";
    loaded = false;
    fill(result);
  } else {
    $("testResult").textContent = "Refusé : " + ((result && result.error) || "réglage illisible");
  }
}

$("save").addEventListener("click", save);
$("save2").addEventListener("click", save);

$("paused").addEventListener("change", async () => {
  fill(await ask("save", { settings: { paused: $("paused").checked } }));
});

$("test").addEventListener("click", async () => {
  const out = $("testResult");
  out.textContent = "…";
  const result = await ask("test");
  out.textContent = result.text;
  out.className = "note " + (result.ok ? "ok-text" : "bad-text");
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
    "Base locale : " + (r.idb.available ? r.idb.sweeps + " relecture(s), la dernière en " + r.idb.lastSweepMs + " ms, "
      + r.idb.messages + " message(s), " + r.idb.errors + " erreur(s)" : "indisponible dans ce navigateur"),
  ];
  for (const db of r.idb.databases || []) {
    lines.push("  · " + db.name + " — " + db.records + " enregistrement(s), " + db.messages + " message(s) neuf(s)"
      + (db.stores.length ? " [" + db.stores.join(", ") + "]" : ""));
  }
  lines.push("", "Conversations dont le nom est connu : " + r.conversationTitles,
    "Messages passés à l'extension : " + r.sent,
    "",
    "Zone de saisie trouvée : " + yes(c.editorFound),
    "Conversation active connue : " + yes(c.activeConversationKnown),
    "Envoi par le service de chat possible : " + yes(c.chatSendPossible),
    "Brouillons en attente dans cet onglet : " + (c.drafts || 0),
    "Depuis l'ouverture : " + (c.placed || 0) + " brouillon(s) placé(s), " + (c.sentByService || 0)
      + " envoi(s) par le service de chat, " + (c.sentByComposeBox || 0) + " par la zone de saisie, "
      + (c.uncertain || 0) + " incertain(s), " + (c.errors || 0) + " erreur(s)");
  out.textContent = lines.join("\n");
});

refresh();
setInterval(refresh, 3000);
