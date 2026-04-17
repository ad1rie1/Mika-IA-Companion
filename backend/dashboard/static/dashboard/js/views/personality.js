/* Personnalité — lecture + édition de personality.yaml.
 *
 * Champs courants (name, description, language, greeting, tone, traits,
 * quirks, values, interests, vulnerabilities) éditables directement ;
 * tout le reste (temperament, circadian_profile, blocs avancés) via une
 * zone YAML advanced pour ne pas perdre de structure.
 */
Dash.render(async (root) => {
  const { api, escapeHTML, emoChip } = Dash;
  const raw = await api("/dashboard/api/personality/yaml");
  const live = await api("/dashboard/api/personality");
  if (!raw || !raw.exists) {
    root.innerHTML = `<div class="empty">Fichier personality.yaml introuvable à ${escapeHTML(raw?.path || "?")}.</div>`;
    return;
  }

  const data = raw.data || {};
  // Known scalar/list keys handled by the structured editor:
  const SCALAR_KEYS = ["name", "description", "language", "greeting"];
  const LIST_KEYS = [];  // dynamic under `personality.*` below

  // Advanced = everything we don't explicitly render as a form field.
  const BASIC_KEYS = new Set([...SCALAR_KEYS, "tone", "personality", "speech_patterns", "mood_greetings"]);
  const advancedData = Object.fromEntries(
    Object.entries(data).filter(([k]) => !BASIC_KEYS.has(k))
  );

  const p = data.personality || {};
  const listTextarea = arr => (arr || []).join("\n");

  root.innerHTML = `
    <div class="card mb">
      <h3>Identité</h3>
      <div class="form-grid">
        <div class="form-field"><label>Nom</label><input type="text" name="name" value="${escapeHTML(data.name || "")}"/></div>
        <div class="form-field"><label>Langue</label><input type="text" name="language" value="${escapeHTML(data.language || "fr")}"/></div>
        <div class="form-field full"><label>Description</label><textarea name="description">${escapeHTML(data.description || "")}</textarea></div>
        <div class="form-field full"><label>Greeting</label><input type="text" name="greeting" value="${escapeHTML(data.greeting || "")}"/></div>
      </div>
    </div>

    <div class="card mb">
      <h3>Traits de caractère (un par ligne)</h3>
      <div class="form-grid">
        <div class="form-field full"><label>Core traits</label><textarea name="p.core_traits">${escapeHTML(listTextarea(p.core_traits || p.traits))}</textarea></div>
        <div class="form-field full"><label>Quirks</label><textarea name="p.quirks">${escapeHTML(listTextarea(p.quirks))}</textarea></div>
        <div class="form-field full"><label>Valeurs</label><textarea name="p.values">${escapeHTML(listTextarea(p.values))}</textarea></div>
        <div class="form-field full"><label>Intérêts</label><textarea name="p.interests">${escapeHTML(listTextarea(p.interests))}</textarea></div>
        <div class="form-field full"><label>Vulnérabilités</label><textarea name="p.vulnerabilities">${escapeHTML(listTextarea(p.vulnerabilities))}</textarea></div>
      </div>
    </div>

    <div class="card mb">
      <h3>Tone</h3>
      <div class="form-field full">
        <label>Bloc tone (YAML)</label>
        <textarea name="tone_yaml" style="min-height:120px;font-family:inherit">${escapeHTML(dumpYaml(data.tone || {}))}</textarea>
        <div class="hint">Accepte un bloc YAML imbriqué (default, when_excited, when_teasing, etc.).</div>
      </div>
    </div>

    <div class="card mb">
      <h3>Speech patterns &amp; mood greetings</h3>
      <div class="form-grid">
        <div class="form-field full"><label>Speech patterns (un par ligne)</label><textarea name="speech_patterns">${escapeHTML(listTextarea(data.speech_patterns))}</textarea></div>
        <div class="form-field full"><label>Mood greetings (YAML)</label><textarea name="mood_greetings_yaml">${escapeHTML(dumpYaml(data.mood_greetings || {}))}</textarea></div>
      </div>
    </div>

    <div class="card mb">
      <h3>Blocs avancés (temperament, circadian_profile, …)</h3>
      <div class="form-field full">
        <label>YAML</label>
        <textarea name="advanced_yaml" style="min-height:300px;font-family:inherit">${escapeHTML(dumpYaml(advancedData))}</textarea>
        <div class="hint">Tout ce qui n'est pas dans les blocs ci-dessus. Édite prudemment — validé à l'écriture.</div>
      </div>
    </div>

    <div class="card">
      <h3>État live</h3>
      <div class="metric-row"><span class="k">Humeur par défaut</span><span class="v">${emoChip(live?.name ? (data.temperament?.default_mood || "happy") : "neutral")}</span></div>
      <div class="metric-row"><span class="k">Fichier</span><span class="v mono">${escapeHTML(raw.path)}</span></div>
      <div class="mt flex gap">
        <button class="btn primary" id="p-save">Enregistrer + recharger</button>
        <button class="btn ghost" id="p-reload">Relire le fichier</button>
      </div>
      <div id="p-status" class="mt muted"></div>
    </div>`;

  root.querySelector("#p-reload").onclick = () => location.reload();
  root.querySelector("#p-save").onclick = async () => {
    const status = root.querySelector("#p-status");
    status.textContent = "Validation…";
    const toList = txt => (txt || "").split("\n").map(l => l.trim()).filter(Boolean);

    const formGet = n => root.querySelector(`[name="${n}"]`)?.value ?? "";
    let advanced = {};
    try {
      advanced = parseYaml(formGet("advanced_yaml")) || {};
    } catch (e) { status.textContent = "Erreur YAML avancé: " + e; status.style.color = "var(--red)"; return; }

    let tone = {};
    try { tone = parseYaml(formGet("tone_yaml")) || {}; }
    catch (e) { status.textContent = "Erreur tone YAML: " + e; status.style.color = "var(--red)"; return; }

    let moodGreetings = {};
    try { moodGreetings = parseYaml(formGet("mood_greetings_yaml")) || {}; }
    catch (e) { status.textContent = "Erreur mood_greetings YAML: " + e; status.style.color = "var(--red)"; return; }

    const payload = {
      ...advanced,
      name: formGet("name") || "Mika",
      description: formGet("description"),
      language: formGet("language") || "fr",
      greeting: formGet("greeting"),
      tone: tone,
      speech_patterns: toList(formGet("speech_patterns")),
      mood_greetings: moodGreetings,
      personality: {
        ...(data.personality || {}),
        core_traits: toList(formGet("p.core_traits")),
        quirks: toList(formGet("p.quirks")),
        values: toList(formGet("p.values")),
        interests: toList(formGet("p.interests")),
        vulnerabilities: toList(formGet("p.vulnerabilities")),
      },
    };

    const r = await fetch("/dashboard/api/personality/yaml/write", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: payload }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      status.textContent = "Erreur : " + (j.error || r.status);
      status.style.color = "var(--red)";
    } else {
      status.textContent = `Enregistré (${j.bytes} octets) — rechargé en mémoire.`;
      status.style.color = "var(--green)";
    }
  };

  // Minimal YAML parser/dumper — we don't want a full yaml lib in the browser,
  // so we use JSON under the hood and provide a loose YAML-ish interface.
  function parseYaml(txt) {
    if (!txt || !txt.trim()) return {};
    // Try JSON first (YAML is a JSON superset)
    try { return JSON.parse(txt); } catch (_) {}
    // Otherwise POST-validate on the server (we just send as JSON via the body)
    // Simplification: accept only well-formed JSON for advanced blocks.
    throw new Error("YAML brut non supporté côté navigateur — utilise de la syntaxe JSON");
  }
  function dumpYaml(obj) {
    try { return JSON.stringify(obj, null, 2); } catch (_) { return ""; }
  }
});
