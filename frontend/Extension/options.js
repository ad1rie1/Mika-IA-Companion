/* La page de réglages (aussi la fenêtre du bouton de l'extension). Tout passe par le service d'arrière-plan ;
   les textes captés ne sont jamais insérés comme HTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const KINDS = ["dm", "group", "channel", "meeting"];
const REASONS = {
  "ancien": "trop anciens (plus de 24 h)",
  "avant l'activation": "antérieurs à l'activation",
  "exclue": "conversations exclues",
  "moi": "mes propres messages",
  "en pause": "arrivés pendant la pause",
  "système": "notifications de Teams",
  "file pleine": "file pleine",
  "refusé par Mika": "refusés par Mika",
};

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

function fill(status) {
  const s = status.settings;
  if (!loaded) {
    $("base").value = s.base;
    $("device").value = s.device;
    $("skipOwn").checked = s.skipOwn;
    $("exclude").value = s.exclude;
    $("sensitivity").value = String(s.sensitivity);
    for (const k of KINDS) $("p_" + k).value = String(s.pertinence[k]);
    loaded = true;
  }
  $("paused").checked = s.paused;
  $("token").placeholder = status.tokenSet ? "défini — laisser vide pour le garder" : "aucun";

  const pill = $("pill");
  let label = "actif";
  let tone = "ok";
  if (s.paused) { label = "en pause"; tone = "warn"; }
  else if (!status.tokenSet) { label = "jeton manquant"; tone = "warn"; }
  else if (status.authFailed) { label = "jeton refusé"; tone = "bad"; }
  else if (status.lastError) { label = "en difficulté"; tone = "bad"; }
  pill.textContent = label;
  pill.className = "pill " + tone;

  const st = status.stats;
  const dropped = Object.entries(st.dropped || {}).filter(([, n]) => n > 0)
    .map(([reason, n]) => n + " " + (REASONS[reason] || reason)).join(", ");
  const rows = [
    ["En attente", String(status.queue)],
    ["Transmis", st.delivered + " message(s) en " + st.signals + " signal(aux)"],
    ["Dernier envoi", when(status.lastOkAt)],
    ["Captés", st.received + " (réseau : " + (st.bySource.network || 0) + ", base locale : " + (st.bySource.idb || 0) + ")"],
    ["Écartés", dropped || "aucun"],
    ["Conversations connues", String(status.conversations)],
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

  const err = $("error");
  err.hidden = !status.lastError;
  err.textContent = status.lastError ? status.lastError + " (" + when(status.lastErrorAt) + ")" : "";

  const log = $("log");
  log.replaceChildren();
  for (const entry of status.log || []) {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = when(entry.at);
    li.append(time, document.createTextNode(entry.text));
    log.append(li);
  }
  $("logEmpty").hidden = Boolean((status.log || []).length);
}

async function refresh() {
  try {
    fill(await ask("status"));
  } catch (e) {
    $("pill").textContent = "service arrêté";
  }
}

function isLocal(base) {
  try {
    const host = new URL(base).hostname;
    return host === "127.0.0.1" || host === "localhost" || host === "[::1]";
  } catch (_) {
    return false;
  }
}

async function save() {
  const base = $("base").value.trim() || "http://127.0.0.1:8001";
  if (!isLocal(base)) {
    // une adresse hors de cette machine demande une permission, accordée par un clic
    let origin;
    try {
      origin = new URL(base).origin + "/*";
    } catch (_) {
      $("testResult").textContent = "Adresse illisible.";
      return;
    }
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      $("testResult").textContent = "Sans permission, l'extension ne peut pas joindre " + base + ".";
      return;
    }
  }
  const pertinence = {};
  for (const k of KINDS) pertinence[k] = Number($("p_" + k).value);
  const result = await ask("save", { settings: {
    base: base, token: $("token").value, device: $("device").value, skipOwn: $("skipOwn").checked,
    exclude: $("exclude").value, sensitivity: Number($("sensitivity").value), pertinence: pertinence,
  } });
  if (result && result.settings) {
    $("token").value = "";
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
  const lines = [
    "Onglet : " + (result.tab || r.url),
    "Ouvert depuis : " + when(r.startedAt),
    "Identité trouvée (pour reconnaître tes messages) : " + (r.selfFound ? "oui" : "non"),
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
    "Messages passés à l'extension : " + r.sent);
  out.textContent = lines.join("\n");
});

refresh();
setInterval(refresh, 3000);
