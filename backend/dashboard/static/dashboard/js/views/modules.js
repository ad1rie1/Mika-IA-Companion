Dash.render(async (root) => {
  const { api, escapeHTML } = Dash;
  const d = await api("/dashboard/api/modules");
  if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  const stateCell = m => {
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

  root.innerHTML = `
    <div class="grid cols-3 mb">
      <div class="card">
        <h3>Modules</h3>
        <div class="stat-value">${d.modules.length}</div>
        <div class="stat-sub">${d.modules.filter(m=>m.running).length} actifs, ${d.modules.filter(m=>!m.available).length} indisponibles</div>
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
        <thead><tr><th>Module</th><th>État</th><th>Uptime</th><th>CRON</th><th>Capabilities</th><th>Erreur</th></tr></thead>
        <tbody>${d.modules.map(m => `
          <tr>
            <td><span class="chip mag">${escapeHTML(m.name)}</span></td>
            <td>${stateCell(m)}</td>
            <td class="muted">${uptime(m.uptime_seconds)}</td>
            <td class="muted mono">${m.cron_interval != null ? m.cron_interval + "s" : "—"}</td>
            <td><div class="chips">${m.capabilities.map(c => `<span class="chip">${escapeHTML(c)}</span>`).join("")}</div></td>
            <td class="muted" style="color:${m.error?'var(--red)':'inherit'}">${escapeHTML(m.error || "—")}</td>
          </tr>`).join("") || `<tr><td colspan="6" class="muted">Aucun module.</td></tr>`}
        </tbody>
      </table>
    </div>`;
});
