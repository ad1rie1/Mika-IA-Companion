/* Configuration — éditeur piloté par le ConfigRegistry.
 *
 * Tout est rendu depuis /dashboard/api/config/schema. Aucun champ
 * codé en dur ici : ajouter une section dans un `config_schema.py`
 * la fait apparaître automatiquement.
 */
Dash.render(async (root) => {
  const { api, escapeHTML, openModal, confirm, clip } = Dash;

  const [schemaRes, valuesRes] = await Promise.all([
    api("/dashboard/api/config/schema"),
    api("/dashboard/api/config/values/all"),
  ]);
  const sections = (schemaRes && schemaRes.sections) || [];
  let values = (valuesRes && valuesRes.values) || {};

  // Rows cache per record_list key → { key: rows[] }
  const rowsCache = {};

  // ── Tabs ──────────────────────────────────────────────────────
  // Group every section into 4 top-level tabs based on its key.
  // The left sidebar is filtered to the active tab; sections keep
  // their own order within.
  function tabOf(section) {
    const k = section.key || "";
    // Fournisseur IA : auth des providers + catalogue de modèles +
    // mapping rôle → modèle déclaré. Tout ce qui relie un provider à
    // une utilisation est groupé ici.
    if (k === "ai_providers" || k === "ai_models" || k === "ai_roles") return "provider";
    if (k.startsWith("comm_")) return "comm";
    if (k === "modules_runtime" || k.startsWith("module_")) return "modules";
    return "ia";
  }
  const TABS = [
    { key: "provider", label: "Configuration Fournisseur IA" },
    { key: "ia",       label: "Configuration IA" },
    { key: "comm",     label: "Configuration Communication" },
    { key: "modules",  label: "Configuration Modules" },
  ];
  const TAB_STORE = "dash.config.tab";
  const readStoredTab = () => {
    try { return localStorage.getItem(TAB_STORE); } catch (_) { return null; }
  };
  const writeStoredTab = k => {
    try { localStorage.setItem(TAB_STORE, k); } catch (_) {}
  };
  let activeTab = TABS.some(t => t.key === readStoredTab()) ? readStoredTab() : "provider";
  const sectionsForTab = t => sections.filter(s => tabOf(s) === t);
  let activeKey = (sectionsForTab(activeTab)[0] || {}).key || null;

  async function sendJSON(url, method, body) {
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  // ── Layout ────────────────────────────────────────────────────
  root.innerHTML = `
    <div class="card mb" id="cfg-tabs" style="padding:8px 10px;display:flex;gap:8px;flex-wrap:wrap"></div>
    <div class="cfg-wrap" style="display:grid;grid-template-columns:240px 1fr;gap:14px;align-items:start">
      <aside class="card cfg-nav" style="padding:8px;position:sticky;top:8px;max-height:calc(100vh - 130px);overflow-y:auto"></aside>
      <section id="cfg-content"></section>
    </div>`;
  const tabsEl = root.querySelector("#cfg-tabs");
  const navEl = root.querySelector(".cfg-nav");
  const contentEl = root.querySelector("#cfg-content");

  function renderTabs() {
    tabsEl.innerHTML = TABS.map(t => {
      const count = sectionsForTab(t.key).length;
      return `
        <button class="btn ${t.key === activeTab ? "primary" : "ghost"}"
                data-tab="${t.key}">
          ${escapeHTML(t.label)}
          <span class="muted" style="margin-left:6px;font-size:0.85em">${count}</span>
        </button>`;
    }).join("");
    tabsEl.querySelectorAll("button[data-tab]").forEach(btn => {
      btn.onclick = () => {
        activeTab = btn.dataset.tab;
        writeStoredTab(activeTab);
        const first = sectionsForTab(activeTab)[0];
        activeKey = first ? first.key : null;
        renderTabs();
        renderNav();
        renderContent();
      };
    });
  }

  function renderNav() {
    const visible = sectionsForTab(activeTab);
    if (!visible.length) {
      navEl.innerHTML = `<div class="muted" style="padding:8px">Aucune section dans cet onglet.</div>`;
      return;
    }
    navEl.innerHTML = visible.map(s => `
      <div class="menu-item ${s.key === activeKey ? "active" : ""}" data-sec="${s.key}">
        <span class="ico">${s.icon || "⚙"}</span>
        <span class="label">${escapeHTML(s.label)}</span>
      </div>`).join("");
    navEl.querySelectorAll("[data-sec]").forEach(el => {
      el.onclick = () => {
        activeKey = el.dataset.sec;
        renderNav();
        renderContent();
      };
    });
  }

  // ── Module activation banner ─────────────────────────────────
  // Sections whose key is "module_<name>" belong to a plugin module.
  // We surface Activer / Désactiver / Désinstaller directly in the
  // configuration page so the user can administer the module right
  // next to its settings.
  async function fetchModuleRow(moduleName) {
    const d = await api("/dashboard/api/modules");
    if (!d || !d.modules) return null;
    return d.modules.find(m => m.name === moduleName) || null;
  }

  async function postModuleAction(moduleName, action, body) {
    const r = await fetch(
      `/dashboard/api/modules/${encodeURIComponent(moduleName)}/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : "{}",
      },
    );
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert(j.error || `HTTP ${r.status}`); return false; }
    return true;
  }

  function renderModuleBanner(section) {
    if (!section.key || !section.key.startsWith("module_")) return "";
    return `
      <div class="card mb" id="module-banner" data-module="${escapeHTML(section.key.substring("module_".length))}">
        <div class="muted">Chargement de l'état du module…</div>
      </div>`;
  }

  async function wireModuleBanner(section) {
    if (!section.key || !section.key.startsWith("module_")) return;
    const moduleName = section.key.substring("module_".length);
    const host = contentEl.querySelector("#module-banner");
    if (!host) return;

    async function paint() {
      const row = await fetchModuleRow(moduleName);
      if (!row) {
        host.innerHTML = `<div class="muted">Ce module n'est pas enregistré (pas d'implémentation Python trouvée).</div>`;
        return;
      }
      const statePill = !row.enabled
        ? `<span class="pill">désactivé</span>`
        : !row.available
          ? `<span class="pill warn">indisponible</span>`
          : row.running
            ? `<span class="pill pos">en marche</span>`
            : `<span class="pill">arrêté</span>`;
      const toggleBtn = row.enabled
        ? `<button class="btn" data-act="disable">Désactiver</button>`
        : `<button class="btn primary" data-act="enable">Activer</button>`;
      const uninstallBtn = row.has_models
        ? `<button class="btn danger" data-act="uninstall">Désinstaller…</button>`
        : "";
      const tablesInfo = (row.installed_tables && row.installed_tables.length)
        ? `<span class="muted mono">${row.installed_tables.length} table(s): ${escapeHTML(row.installed_tables.join(", "))}</span>`
        : row.has_models
          ? `<span class="muted">aucune table installée</span>`
          : `<span class="muted">ce module n'a pas de données persistantes</span>`;

      host.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div style="flex:1;min-width:200px">
            <div><b>${escapeHTML(moduleName)}</b> ${statePill}</div>
            <div style="margin-top:4px">${tablesInfo}</div>
          </div>
          <div style="display:flex;gap:8px">${toggleBtn} ${uninstallBtn}</div>
        </div>
        <div class="muted" style="margin-top:8px;font-size:0.85em">
          <b>Activer</b> crée les tables manquantes et démarre le module.
          <b>Désactiver</b> stoppe le module, les données restent en base.
          <b>Désinstaller</b> supprime toutes les tables du module (irréversible).
        </div>`;

      host.querySelectorAll("button[data-act]").forEach(btn => {
        btn.onclick = async () => {
          const act = btn.dataset.act;
          // Enable/disable/uninstall changes the sidebar + visible config
          // sections (they're filtered server-side per module state),
          // so reload the page to keep the UI coherent.
          if (act === "uninstall") {
            if (!window.confirm(`Désinstaller "${moduleName}" ?\n\nCela supprimera TOUTES ses tables et données.\nCette action est irréversible.`)) return;
            if (await postModuleAction(moduleName, "uninstall", { confirm: true })) location.reload();
          } else {
            if (await postModuleAction(moduleName, act)) location.reload();
          }
        };
      });
    }
    paint();
  }

  // ── Section content ───────────────────────────────────────────
  async function renderContent() {
    if (!activeKey) {
      contentEl.innerHTML = `<div class="empty">Aucune section à afficher dans cet onglet.</div>`;
      return;
    }
    const section = sections.find(s => s.key === activeKey);
    if (!section) { contentEl.innerHTML = `<div class="empty">Section inconnue.</div>`; return; }

    // Group items by `group`
    const groups = {};
    for (const item of section.items) {
      const g = item.group || "";
      (groups[g] = groups[g] || []).push(item);
    }

    const groupNames = Object.keys(groups);
    // A group's label (e.g. "Claude", "OpenAI") maps 1:1 to a provider
    // inside the ai_providers section — we use it to wire the Tester
    // button below.
    const PROVIDER_BY_GROUP = {
      claude: "claude", openai: "openai", gemini: "gemini", glm: "glm", ollama: "ollama",
    };
    const providerTestSlot = g => {
      if (section.key !== "ai_providers") return "";
      const provider = PROVIDER_BY_GROUP[(g || "").toLowerCase()];
      if (!provider) return "";
      return `
        <div class="cfg-provider-test" data-provider="${provider}" style="margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button class="btn" data-act="test">Tester la communication</button>
          <span class="muted cfg-test-out" data-for="${provider}"></span>
        </div>`;
    };
    contentEl.innerHTML = `
      <div class="card mb">
        <h3>${escapeHTML(section.label)}<span class="tag">${section.items.length} paramètre(s)</span></h3>
        ${section.description ? `<div class="muted mb">${escapeHTML(section.description)}</div>` : ""}
      </div>
      ${renderModuleBanner(section)}
      ${groupNames.map(g => `
        <div class="card mb">
          ${g ? `<h3>${escapeHTML(g)}</h3>` : ""}
          <div class="cfg-fields" data-group="${escapeHTML(g)}"></div>
          ${providerTestSlot(g)}
        </div>`).join("")}
    `;

    wireModuleBanner(section);
    wireProviderTesters();

    // Render fields per group
    for (const g of groupNames) {
      const host = contentEl.querySelector(`.cfg-fields[data-group="${g === "" ? "" : escapeHTML(g)}"]`);
      for (const item of groups[g]) {
        host.appendChild(renderField(item));
      }
      // Render record_list contents after the scalars are in the DOM
      for (const item of groups[g]) {
        if (item.type === "record_list") {
          await loadAndRenderRows(item);
        }
      }
    }
  }

  // ── Scalar field renderer ─────────────────────────────────────
  function renderField(item) {
    const val = values[item.key];
    const wrap = document.createElement("div");
    wrap.style.padding = "10px 0";
    wrap.style.borderBottom = "1px dashed rgba(255,255,255,0.06)";
    wrap.dataset.key = item.key;

    const flags = [];
    if (item.hot_reload)        flags.push(`<span class="pill pos">hot-reload</span>`);
    if (item.restart_required)  flags.push(`<span class="pill warn">restart</span>`);
    if (item.sensitive)         flags.push(`<span class="pill mag">secret</span>`);
    if (item.readonly)          flags.push(`<span class="pill">RO</span>`);

    const env = item.env_fallback ? `<span class="muted mono" style="margin-left:6px">.env: ${item.env_fallback}</span>` : "";

    const head = `
      <div class="flex between center" style="gap:10px;margin-bottom:6px">
        <div>
          <div style="color:var(--text)">${escapeHTML(item.label)}</div>
          <div class="muted" style="font-size:10px">${escapeHTML(item.key)}${env}</div>
        </div>
        <div class="flex gap">${flags.join("")}</div>
      </div>
      ${item.description ? `<div class="muted" style="font-size:11px;margin-bottom:6px">${escapeHTML(item.description)}</div>` : ""}
      ${item.hint ? `<div class="muted" style="font-size:10px;font-style:italic;margin-bottom:6px">${escapeHTML(item.hint)}</div>` : ""}
    `;

    if (item.type === "record_list") {
      wrap.innerHTML = head + `
        <div class="cfg-rl" data-parent="${escapeHTML(item.key)}">
          <div class="muted">Chargement des enregistrements…</div>
        </div>`;
      return wrap;
    }

    wrap.innerHTML = head + renderInput(item, val);
    wireField(wrap, item);
    return wrap;
  }

  function renderInput(item, val) {
    const readonly = item.readonly ? "disabled" : "";
    if (item.type === "bool") {
      return `
        <label class="flex gap center">
          <input type="checkbox" ${val ? "checked" : ""} ${readonly} data-input />
          <span class="muted">${val ? "activé" : "désactivé"}</span>
        </label>
        <button class="btn ghost cfg-save" type="button">Enregistrer</button>
        <button class="btn ghost cfg-reset" type="button" title="Revenir au défaut / .env">Reset</button>
      `;
    }
    if (item.type === "select") {
      return `
        <div class="flex gap center">
          <select data-input ${readonly}>
            ${(item.choices || []).map(c => `<option value="${escapeHTML(c)}" ${c === val ? "selected" : ""}>${escapeHTML(c)}</option>`).join("")}
          </select>
          <button class="btn ghost cfg-save" type="button">Enregistrer</button>
          <button class="btn ghost cfg-reset" type="button">Reset</button>
        </div>`;
    }
    if (item.type === "secret") {
      const preview = val && typeof val === "object" && val.has_value
        ? `<code class="muted">${escapeHTML(val.preview)}</code> <span class="muted">(${val.length} caractères)</span>`
        : `<span class="muted">— vide —</span>`;
      return `
        <div>${preview}</div>
        <div class="flex gap center mt">
          <input type="password" autocomplete="new-password" placeholder="Nouveau secret…" data-input ${readonly} style="flex:1" />
          <button class="btn cfg-save" type="button">Remplacer</button>
          <button class="btn ghost cfg-reset" type="button">Effacer override</button>
        </div>`;
    }
    if (item.type === "text") {
      return `
        <textarea data-input ${readonly} style="min-height:80px">${escapeHTML(val != null ? String(val) : "")}</textarea>
        <div class="flex gap mt">
          <button class="btn cfg-save" type="button">Enregistrer</button>
          <button class="btn ghost cfg-reset" type="button">Reset</button>
        </div>`;
    }
    const inputType = item.type === "int" || item.type === "float" ? "number" : "text";
    const step = item.type === "float" ? "any" : (item.type === "int" ? "1" : "");
    const minAttr = item.min != null ? `min="${item.min}"` : "";
    const maxAttr = item.max != null ? `max="${item.max}"` : "";
    return `
      <div class="flex gap center">
        <input type="${inputType}" ${step ? `step="${step}"` : ""} ${minAttr} ${maxAttr}
               value="${val != null ? escapeHTML(String(val)) : ""}" data-input ${readonly} style="flex:1" />
        <button class="btn cfg-save" type="button">Enregistrer</button>
        <button class="btn ghost cfg-reset" type="button">Reset</button>
      </div>`;
  }

  function wireField(wrap, item) {
    const input = wrap.querySelector("[data-input]");
    const save = wrap.querySelector(".cfg-save");
    const reset = wrap.querySelector(".cfg-reset");
    if (save) save.onclick = async () => {
      let v;
      if (item.type === "bool") v = !!input.checked;
      else v = input.value;
      if (item.type === "secret" && !v) { flash(save, "Tapez une valeur", true); return; }
      try {
        const r = await sendJSON("/dashboard/api/config/values", "PATCH", { key: item.key, value: v });
        values[item.key] = r.value;
        flash(save, "Enregistré");
        if (item.type === "secret") {
          // Re-render the field to show the new redacted preview
          const replacement = renderField(item);
          wrap.replaceWith(replacement);
        }
      } catch (e) { alert("Erreur: " + e.message); }
    };
    if (reset) reset.onclick = async () => {
      if (!(await confirm(`Effacer l'override pour "${item.label}" ? La valeur reviendra au défaut / .env.`))) return;
      try {
        await sendJSON("/dashboard/api/config/values?key=" + encodeURIComponent(item.key), "DELETE");
        // Reload effective value
        const res = await api("/dashboard/api/config/values/all");
        values = (res && res.values) || values;
        const replacement = renderField(item);
        wrap.replaceWith(replacement);
      } catch (e) { alert("Erreur: " + e.message); }
    };
  }

  function flash(btn, msg, isError = false) {
    const orig = btn.textContent;
    btn.textContent = msg;
    btn.style.color = isError ? "var(--red)" : "var(--green)";
    setTimeout(() => { btn.textContent = orig; btn.style.color = ""; }, 1200);
  }

  // ── Provider test button ──────────────────────────────────────
  // Hits /dashboard/api/providers/<name>/test which pings the SDK
  // with currently-stored credentials and reports model count back.
  function wireProviderTesters() {
    contentEl.querySelectorAll(".cfg-provider-test").forEach(host => {
      const provider = host.dataset.provider;
      const btn = host.querySelector("button[data-act=test]");
      const out = host.querySelector(".cfg-test-out");
      if (!btn || !provider) return;
      btn.onclick = async () => {
        out.textContent = "Test en cours…";
        out.style.color = "";
        btn.disabled = true;
        try {
          const r = await fetch(`/dashboard/api/providers/${encodeURIComponent(provider)}/test`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          const j = await r.json().catch(() => ({}));
          if (j.ok) {
            out.textContent = `OK — ${j.model_count} modèle(s) disponibles.`;
            out.style.color = "var(--green)";
          } else {
            out.textContent = `Échec : ${j.error || ("HTTP " + r.status)}`;
            out.style.color = "var(--red)";
          }
        } catch (e) {
          out.textContent = `Erreur réseau : ${e.message}`;
          out.style.color = "var(--red)";
        } finally {
          btn.disabled = false;
        }
      };
    });
  }

  // ── Custom row editor for ai.models ───────────────────────────
  // The generic openRowEditor lets the user type any model name, which
  // violates the requirement that model ids must come from the provider
  // itself. This editor enforces: pick provider → load list → pick one.
  async function openModelRowEditor(item, row) {
    const isNew = !row;
    const payload = row ? (row.payload || {}) : {};
    const initialProvider = payload.provider || "claude";
    const initialModel = payload.model_id || "";
    const providers = ["claude", "openai", "gemini", "glm", "ollama"];

    const body = `
      <form id="rl-form" class="form-grid">
        <div class="form-field">
          <label>Nom interne</label>
          <input name="internal_name" type="text" value="${escapeHTML(payload.internal_name || "")}" required
                 placeholder="ex. fast-chat, smart-vision" />
          <div class="hint">Identifiant libre utilisé par les rôles IA.</div>
        </div>
        <div class="form-field">
          <label>Fournisseur</label>
          <select name="provider">
            ${providers.map(p => `<option value="${p}" ${p === initialProvider ? "selected" : ""}>${p}</option>`).join("")}
          </select>
        </div>
        <div class="form-field full">
          <label>Modèle</label>
          <button type="button" class="btn primary" id="rl-load"
                  style="align-self:flex-start;margin-bottom:6px">
            ⟲ Charger les modèles depuis le provider
          </button>
          <select name="model_id" disabled>
            ${initialModel
              ? `<option value="${escapeHTML(initialModel)}" selected>${escapeHTML(initialModel)}</option>`
              : `<option value="">(cliquez sur « Charger les modèles »)</option>`}
          </select>
          <div class="hint" id="rl-load-status">
            Les modèles sont fournis par le SDK du provider — aucune saisie libre.
          </div>
        </div>
        <div class="form-field">
          <label>Température</label>
          <input name="temperature" type="number" step="any" min="0" max="2"
                 value="${payload.temperature != null ? payload.temperature : 0.7}" />
        </div>
        <div class="form-field checkbox full">
          <input type="checkbox" id="rl-enabled" ${(row?.enabled ?? true) ? "checked" : ""} />
          <label for="rl-enabled">Activé</label>
        </div>
      </form>`;

    const footer = [
      { label: "Annuler", ghost: true, onClick: m => m.close() },
    ];
    if (!isNew) {
      footer.push({
        label: "Supprimer", danger: true,
        onClick: async m => {
          if (!(await confirm("Supprimer ce modèle déclaré ?", { danger: true }))) return;
          try {
            await sendJSON(`/dashboard/api/config/rows/${row.row_id}?parent_key=${encodeURIComponent(item.key)}`, "DELETE");
            m.close();
            await loadAndRenderRows(item);
          } catch (e) { alert("Erreur: " + e.message); }
        },
      });
    }
    footer.push({
      label: isNew ? "Créer" : "Enregistrer", primary: true,
      onClick: async m => {
        const form = m.body.querySelector("#rl-form");
        const internalName = (form.querySelector("[name=internal_name]").value || "").trim();
        const provider = form.querySelector("[name=provider]").value;
        const modelId = form.querySelector("[name=model_id]").value;
        const temperature = parseFloat(form.querySelector("[name=temperature]").value);
        if (!internalName) { alert("Le nom interne est obligatoire."); return; }
        if (!modelId) { alert("Sélectionne un modèle (bouton 'Charger les modèles')."); return; }
        const payload = {
          internal_name: internalName,
          provider,
          model_id: modelId,
          temperature: isNaN(temperature) ? 0.7 : temperature,
          enabled: form.querySelector("#rl-enabled").checked,
        };
        try {
          if (isNew) {
            await sendJSON(`/dashboard/api/config/rows/create`, "POST", { parent_key: item.key, payload });
          } else {
            await sendJSON(`/dashboard/api/config/rows/${row.row_id}`, "PATCH", { parent_key: item.key, payload });
          }
          m.close();
          await loadAndRenderRows(item);
        } catch (e) { alert("Erreur: " + e.message); }
      },
    });

    const modal = openModal({
      title: isNew ? "Déclarer un modèle" : `Éditer — ${payload.internal_name || ""}`,
      body, footer,
    });

    const form = modal.body.querySelector("#rl-form");
    const loadBtn = form.querySelector("#rl-load");
    const statusEl = form.querySelector("#rl-load-status");
    const modelSel = form.querySelector("[name=model_id]");
    const providerSel = form.querySelector("[name=provider]");

    async function loadModels() {
      const prov = providerSel.value;
      statusEl.textContent = `Requête ${prov}…`;
      statusEl.style.color = "";
      loadBtn.disabled = true;
      try {
        const r = await fetch(`/dashboard/api/providers/${encodeURIComponent(prov)}/models`);
        const j = await r.json().catch(() => ({}));
        if (!r.ok || !Array.isArray(j.models)) {
          throw new Error(j.error || ("HTTP " + r.status));
        }
        if (!j.models.length) {
          statusEl.textContent = `Aucun modèle retourné par ${prov}.`;
          statusEl.style.color = "var(--amber)";
          modelSel.innerHTML = `<option value="">(aucun)</option>`;
          modelSel.disabled = true;
          return;
        }
        const selected = initialModel && j.models.some(m => m.id === initialModel) ? initialModel : j.models[0].id;
        modelSel.innerHTML = j.models.map(m =>
          `<option value="${escapeHTML(m.id)}" ${m.id === selected ? "selected" : ""}>${escapeHTML(m.label || m.id)}</option>`
        ).join("");
        modelSel.disabled = false;
        statusEl.textContent = `${j.models.length} modèle(s) chargés depuis ${prov}.`;
        statusEl.style.color = "var(--green)";
      } catch (e) {
        statusEl.textContent = `Erreur : ${e.message}`;
        statusEl.style.color = "var(--red)";
      } finally {
        loadBtn.disabled = false;
      }
    }

    loadBtn.onclick = loadModels;
    // Changing provider invalidates the current list → auto-reload so
    // the user never stares at an empty select.
    providerSel.onchange = () => {
      modelSel.innerHTML = `<option value="">(chargement…)</option>`;
      modelSel.disabled = true;
      loadModels();
    };
    // Kick off a load on open so the select is populated immediately
    // for the selected provider.
    loadModels();
  }

  // ── record_list rendering ─────────────────────────────────────
  async function loadAndRenderRows(item) {
    const host = contentEl.querySelector(`.cfg-rl[data-parent="${item.key}"]`);
    if (!host) return;
    const res = await api(`/dashboard/api/config/rows?key=${encodeURIComponent(item.key)}`);
    const rows = (res && res.rows) || [];
    rowsCache[item.key] = rows;

    // Pick first 3-4 non-sensitive fields for the list view
    const listFields = (item.record?.fields || [])
      .filter(f => !f.sensitive)
      .slice(0, 4);

    host.innerHTML = `
      <div class="flex between center mb">
        <span class="muted">${rows.length} élément(s)${item.max_items ? ` / ${item.max_items}` : ""}</span>
        <button class="btn primary cfg-rl-add" type="button" ${item.max_items && rows.length >= item.max_items ? "disabled" : ""}>+ Ajouter</button>
      </div>
      ${rows.length ? `
        <table>
          <thead><tr>
            <th></th>
            ${listFields.map(f => `<th>${escapeHTML(f.label)}</th>`).join("")}
            <th></th>
          </tr></thead>
          <tbody>${rows.map(r => {
            const p = r.payload || {};
            return `
              <tr data-rid="${r.row_id}">
                <td>${r.enabled
                  ? `<span class="pill pos">on</span>`
                  : `<span class="pill">off</span>`}</td>
                ${listFields.map(f => `<td>${escapeHTML(clip(String(p[f.key] ?? ""), 60))}</td>`).join("")}
                <td>
                  <button class="btn ghost cfg-rl-edit" type="button">éditer</button>
                  <button class="btn ghost cfg-rl-del" type="button" title="Supprimer">×</button>
                </td>
              </tr>`;
          }).join("")}</tbody>
        </table>` : `<div class="muted">Aucun élément — clique <b>+ Ajouter</b>.</div>`}
    `;

    const editor = item.key === "ai.models" ? openModelRowEditor : openRowEditor;
    host.querySelector(".cfg-rl-add").onclick = () => editor(item, null);
    host.querySelectorAll("tr[data-rid]").forEach(tr => {
      const rid = tr.dataset.rid;
      const row = rows.find(r => r.row_id === rid);
      tr.querySelector(".cfg-rl-edit").onclick = () => editor(item, row);
      tr.querySelector(".cfg-rl-del").onclick = async () => {
        if (!(await confirm(`Supprimer cet élément ?`, { danger: true }))) return;
        try {
          await sendJSON(`/dashboard/api/config/rows/${rid}?parent_key=${encodeURIComponent(item.key)}`, "DELETE");
          await loadAndRenderRows(item);
        } catch (e) { alert("Erreur: " + e.message); }
      };
    });
  }

  function openRowEditor(item, row) {
    const isNew = !row;
    const payload = row ? (row.payload || {}) : {};
    const fields = item.record?.fields || [];

    const body = `
      <form id="rl-form">
        <div class="form-grid">
          ${fields.map(f => `
            <div class="form-field ${f.type === "text" ? "full" : ""}">
              <label>${escapeHTML(f.label)}${f.sensitive ? ` <span class="pill mag" style="margin-left:6px">secret</span>` : ""}</label>
              ${renderRowInput(f, payload[f.key])}
              ${f.hint ? `<div class="hint">${escapeHTML(f.hint)}</div>` : ""}
            </div>`).join("")}
          <div class="form-field checkbox full">
            <input type="checkbox" id="rl-enabled" ${(row?.enabled ?? true) ? "checked" : ""} />
            <label for="rl-enabled">Activé</label>
          </div>
        </div>
      </form>`;

    const footer = [
      { label: "Annuler", ghost: true, onClick: m => m.close() },
    ];
    if (!isNew) {
      footer.push({
        label: "Supprimer", danger: true,
        onClick: async m => {
          if (!(await confirm("Supprimer cet élément ?", { danger: true }))) return;
          try {
            await sendJSON(`/dashboard/api/config/rows/${row.row_id}?parent_key=${encodeURIComponent(item.key)}`, "DELETE");
            m.close();
            await loadAndRenderRows(item);
          } catch (e) { alert("Erreur: " + e.message); }
        },
      });
    }
    footer.push({
      label: isNew ? "Créer" : "Enregistrer", primary: true,
      onClick: async m => {
        const form = m.body.querySelector("#rl-form");
        const payload = {};
        for (const f of fields) {
          const el = form.querySelector(`[name="${f.key}"]`);
          if (!el) continue;
          let v;
          if (f.type === "bool") v = el.checked;
          else if (f.type === "int") v = el.value === "" ? null : parseInt(el.value, 10);
          else if (f.type === "float") v = el.value === "" ? null : parseFloat(el.value);
          else v = el.value;
          // For secrets, omit empty so the backend keeps the previous value
          if (f.sensitive && (v === "" || v == null)) continue;
          payload[f.key] = v;
        }
        payload.enabled = form.querySelector("#rl-enabled").checked;
        try {
          if (isNew) {
            await sendJSON(`/dashboard/api/config/rows/create`, "POST", { parent_key: item.key, payload });
          } else {
            await sendJSON(`/dashboard/api/config/rows/${row.row_id}`, "PATCH", { parent_key: item.key, payload });
          }
          m.close();
          await loadAndRenderRows(item);
        } catch (e) { alert("Erreur: " + e.message); }
      },
    });

    openModal({
      title: isNew ? `Nouveau — ${item.record?.label || item.label}` : `Éditer — ${item.record?.label || item.label}`,
      body, footer,
    });
  }

  function renderRowInput(f, val) {
    if (f.type === "bool") {
      return `<label class="flex gap center"><input type="checkbox" name="${f.key}" ${val ? "checked" : ""} /> <span class="muted">${val ? "oui" : "non"}</span></label>`;
    }
    if (f.type === "select") {
      return `<select name="${f.key}">${(f.choices||[]).map(c => `<option value="${escapeHTML(c)}" ${c===val?"selected":""}>${escapeHTML(c)}</option>`).join("")}</select>`;
    }
    if (f.type === "secret") {
      const preview = val && typeof val === "object" && val.has_value
        ? `<div class="muted" style="font-size:10px;margin-bottom:4px">actuel : ${escapeHTML(val.preview)} (${val.length} car.)</div>`
        : `<div class="muted" style="font-size:10px;margin-bottom:4px">— vide —</div>`;
      return preview + `<input type="password" name="${f.key}" placeholder="Laisser vide pour conserver" autocomplete="new-password" />`;
    }
    if (f.type === "text") {
      return `<textarea name="${f.key}">${escapeHTML(val != null ? String(val) : "")}</textarea>`;
    }
    const inputType = f.type === "int" || f.type === "float" ? "number" : "text";
    const step = f.type === "float" ? "any" : (f.type === "int" ? "1" : "");
    return `<input type="${inputType}" ${step ? `step="${step}"` : ""} name="${f.key}" value="${val != null ? escapeHTML(String(val)) : ""}" />`;
  }

  renderTabs();
  renderNav();
  renderContent();
});
