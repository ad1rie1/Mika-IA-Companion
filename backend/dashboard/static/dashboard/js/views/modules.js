Dash.render(async (root) => {
  const { api, escapeHTML, clientPager, tabs } = Dash;

  const stateCell = m => {
    if (!m.enabled) return `<span class="pill">désactivé</span>`;
    if (!m.available) return `<span class="pill warn">indisponible</span>`;
    if (m.running) return `<span class="pill pos">running</span>`;
    const err = m.error
      ? `<div class="muted mono" style="margin-top:4px;font-size:0.8em;color:#e08080;" title="${escapeHTML(m.error)}">${escapeHTML(m.error.slice(0, 80))}${m.error.length > 80 ? "…" : ""}</div>`
      : "";
    return `<span class="pill">stopped</span>${err}`;
  };
  const uptime = s => {
    if (!s) return "—";
    if (s < 60)  return `${Math.floor(s)}s`;
    if (s < 3600) return `${Math.floor(s/60)}m`;
    return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
  };

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
    });
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      alert((data && data.error) || `HTTP ${r.status}`);
      return null;
    }
    return data;
  }

  async function act(name, action, { confirmText, body } = {}) {
    if (confirmText && !confirm(confirmText)) return;
    const res = await post(`/dashboard/api/modules/${encodeURIComponent(name)}/${action}`, body);
    if (!res) return;
    // Full reload: the sidebar menu + any per-module config section are
    // built server-side at request time, so enabling or disabling a
    // module requires a fresh render to reflect the new state.
    location.reload();
  }

  const moduleRow = m => {
    const tables = (m.installed_tables && m.installed_tables.length)
      ? `<span class="muted mono" title="${escapeHTML(m.installed_tables.join(", "))}">${m.installed_tables.length}</span>`
      : (m.has_models ? `<span class="muted">—</span>` : `<span class="muted">·</span>`);
    const views = (m.views && m.views.length)
      ? m.views.map(v =>
          `<a class="chip" href="${escapeHTML(v.url)}" title="${escapeHTML(v.label)}">${escapeHTML(v.icon || "▦")} ${escapeHTML(v.label)}</a>`
        ).join(" ")
      : `<span class="muted">—</span>`;
    const startBtn = (m.enabled && m.available && !m.running)
      ? `<button class="btn primary" data-act="enable" data-name="${escapeHTML(m.name)}">Démarrer</button>`
      : "";
    const enableBtn = m.enabled
      ? `<button class="btn" data-act="disable" data-name="${escapeHTML(m.name)}">Désactiver</button>`
      : `<button class="btn primary" data-act="enable" data-name="${escapeHTML(m.name)}">Activer</button>`;
    return `
      <tr>
        <td><span class="chip mag">${escapeHTML(m.name)}</span></td>
        <td>${stateCell(m)}</td>
        <td class="muted">${uptime(m.uptime_seconds)}</td>
        <td class="muted mono">${m.cron_interval != null ? m.cron_interval + "s" : "—"}</td>
        <td>${tables}</td>
        <td><div class="chips">${m.capabilities.map(c => `<span class="chip">${escapeHTML(c)}</span>`).join("")}</div></td>
        <td><div class="chips">${views}</div></td>
        <td>${startBtn} ${enableBtn}</td>
      </tr>`;
  };

  function renderDetail(d) {
    return async (body) => {
      body.innerHTML = `
        <div class="card">
          <h3>État détaillé<span class="tag">${d.modules.length}</span></h3>
          <table>
            <thead>
              <tr>
                <th>Module</th><th>État</th><th>Uptime</th><th>CRON</th>
                <th>Tables</th><th>Capabilities</th><th>Vues</th><th>Actions</th>
              </tr>
            </thead>
            <tbody id="mod-body"></tbody>
          </table>
          <p class="muted" style="margin-top:10px;font-size:0.85em;">
            <b>Activer</b> = marque le module actif et crée ses tables si nécessaires.
            <b>Désactiver</b> = stoppe le module mais conserve les données.
          </p>
        </div>`;
      const card = body.querySelector(".card");
      const tbody = body.querySelector("#mod-body");
      clientPager({
        rows: d.modules, limit: 25, mount: card,
        render: page => {
          tbody.innerHTML = page.map(moduleRow).join("") || `<tr><td colspan="8" class="muted">Aucun module.</td></tr>`;
          tbody.querySelectorAll("button[data-act]").forEach(btn => {
            btn.onclick = () => act(btn.dataset.name, btn.dataset.act);
          });
        },
      });
    };
  }

  function toolBlock(t) {
    const params = (t.parameters && t.parameters.length)
      ? `<table style="margin-top:8px;font-size:11px;">
           <thead>
             <tr>
               <th style="width:22%">Paramètre</th><th style="width:12%">Type</th>
               <th style="width:8%">Requis</th><th>Description</th>
             </tr>
           </thead>
           <tbody>
             ${t.parameters.map(p => {
               const typeLabel = p.enum
                 ? `${escapeHTML(p.type)} <span class="muted" title="${escapeHTML(p.enum.join(", "))}">(enum)</span>`
                 : escapeHTML(p.type);
               const reqPill = p.required
                 ? `<span class="pill warn">oui</span>`
                 : `<span class="pill">non</span>`;
               const dflt = p.default != null
                 ? ` <span class="muted mono" style="font-size:10px;">défaut: ${escapeHTML(String(p.default))}</span>`
                 : "";
               return `
                 <tr>
                   <td class="mono">${escapeHTML(p.name)}</td>
                   <td class="mono">${typeLabel}</td>
                   <td>${reqPill}</td>
                   <td class="muted">${escapeHTML(p.description || "")}${dflt}</td>
                 </tr>`;
             }).join("")}
           </tbody>
         </table>`
      : `<div class="muted" style="margin-top:6px;font-size:11px;">Aucun paramètre.</div>`;
    return `
      <div style="padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:10px;background:rgba(255,255,255,0.015);">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span class="chip mag mono">${escapeHTML(t.name)}</span>
          <span class="muted" style="font-size:11px;">${t.parameters.length} param.</span>
        </div>
        <div style="margin-top:6px;font-size:12px;">${escapeHTML(t.description || "")}</div>
        ${params}
      </div>`;
  }

  function renderTools(d) {
    return async (body) => {
      const tools = Array.isArray(d.tools) ? d.tools : [];
      if (!tools.length) {
        body.innerHTML = `<div class="card"><div class="empty">Aucun outil MCP exposé par les modules en cours d'exécution.</div></div>`;
        return;
      }
      body.innerHTML = `<div id="tools-list"></div>`;
      const list = body.querySelector("#tools-list");
      clientPager({
        rows: tools, limit: 15, mount: body,
        render: page => {
          const grouped = {};
          for (const t of page) (grouped[t.module] ||= []).push(t);
          list.innerHTML = Object.keys(grouped).sort().map(moduleName => `
            <div class="card" style="margin-bottom:14px;">
              <h3>${escapeHTML(moduleName)} <span class="muted" style="font-size:11px;">· ${grouped[moduleName].length} outil(s)</span></h3>
              ${grouped[moduleName].map(toolBlock).join("")}
            </div>`).join("");
        },
      });
    };
  }

  const d = await api("/dashboard/api/modules");
  if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  tabs({
    mount: root,
    storeKey: "dash.modules.tab",
    tabs: [
      { key: "detail", label: "Modules Détail", render: renderDetail(d) },
      { key: "tools",  label: "Outils MCP",    render: renderTools(d)  },
    ],
  });
});
