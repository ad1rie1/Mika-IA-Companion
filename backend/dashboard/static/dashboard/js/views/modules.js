Dash.render(async (root) => {
  const { api, escapeHTML } = Dash;

  const stateCell = m => {
    if (!m.enabled) return `<span class="pill">désactivé</span>`;
    if (!m.available) return `<span class="pill warn">indisponible</span>`;
    if (m.running) return `<span class="pill pos">running</span>`;
    return `<span class="pill">stopped</span>`;
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
    if (res) render();
  }

  async function render() {
    const d = await api("/dashboard/api/modules");
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const enabledCount = d.modules.filter(m => m.enabled).length;
    const runningCount = d.modules.filter(m => m.running).length;
    const unavailableCount = d.modules.filter(m => m.enabled && !m.available).length;

    root.innerHTML = `
      <div class="grid cols-3 mb">
        <div class="card">
          <h3>Modules</h3>
          <div class="stat-value">${d.modules.length}</div>
          <div class="stat-sub">${enabledCount} activés · ${runningCount} en marche · ${unavailableCount} indisponibles</div>
        </div>
        <div class="card">
          <h3>Outils MCP</h3>
          <div class="stat-value">${d.total_tools}</div>
          <div class="stat-sub">tools exposés à Mika</div>
        </div>
        <div class="card">
          <h3>Inventaire tools</h3>
          <div class="chips">${d.tool_names.map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("") || `<span class="muted">—</span>`}</div>
        </div>
      </div>

      <div class="card">
        <h3>État détaillé</h3>
        <table>
          <thead>
            <tr>
              <th>Module</th>
              <th>État</th>
              <th>Uptime</th>
              <th>CRON</th>
              <th>Tables</th>
              <th>Capabilities</th>
              <th>Vues</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${d.modules.map(m => {
              const tables = (m.installed_tables && m.installed_tables.length)
                ? `<span class="muted mono" title="${escapeHTML(m.installed_tables.join(", "))}">${m.installed_tables.length}</span>`
                : (m.has_models ? `<span class="muted">—</span>` : `<span class="muted">·</span>`);
              const views = (m.views && m.views.length)
                ? m.views.map(v =>
                    `<a class="chip" href="${escapeHTML(v.url)}" title="${escapeHTML(v.label)}">${escapeHTML(v.icon || "▦")} ${escapeHTML(v.label)}</a>`
                  ).join(" ")
                : `<span class="muted">—</span>`;
              const enableBtn = m.enabled
                ? `<button class="btn" data-act="disable" data-name="${escapeHTML(m.name)}">Désactiver</button>`
                : `<button class="btn primary" data-act="enable" data-name="${escapeHTML(m.name)}">Activer</button>`;
              const uninstallBtn = m.has_models
                ? `<button class="btn danger" data-act="uninstall" data-name="${escapeHTML(m.name)}">Désinstaller</button>`
                : "";
              return `
                <tr>
                  <td><span class="chip mag">${escapeHTML(m.name)}</span></td>
                  <td>${stateCell(m)}</td>
                  <td class="muted">${uptime(m.uptime_seconds)}</td>
                  <td class="muted mono">${m.cron_interval != null ? m.cron_interval + "s" : "—"}</td>
                  <td>${tables}</td>
                  <td><div class="chips">${m.capabilities.map(c => `<span class="chip">${escapeHTML(c)}</span>`).join("")}</div></td>
                  <td><div class="chips">${views}</div></td>
                  <td>${enableBtn} ${uninstallBtn}</td>
                </tr>`;
            }).join("") || `<tr><td colspan="8" class="muted">Aucun module.</td></tr>`}
          </tbody>
        </table>
        <p class="muted" style="margin-top:10px;font-size:0.85em;">
          <b>Activer</b> = marque le module actif et crée ses tables si nécessaires.
          <b>Désactiver</b> = stoppe le module mais conserve les données.
          <b>Désinstaller</b> = stoppe le module <em>et supprime ses tables</em> (destructif).
        </p>
      </div>`;

    root.querySelectorAll("button[data-act]").forEach(btn => {
      btn.onclick = () => {
        const name = btn.dataset.name;
        const action = btn.dataset.act;
        if (action === "uninstall") {
          act(name, "uninstall", {
            confirmText: `Désinstaller le module "${name}" ?\n\nCela va SUPPRIMER toutes ses tables et données.\nCette action est irréversible.`,
            body: { confirm: true },
          });
        } else {
          act(name, action);
        }
      };
    });
  }

  render();
});
