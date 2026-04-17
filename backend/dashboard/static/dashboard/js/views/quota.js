Dash.render(async (root) => {
  const { api, escapeHTML } = Dash;
  const d = await api("/dashboard/api/quota");
  if (!d || !d.available) return (root.innerHTML = `<div class="empty">Quota non disponible.</div>`);

  const renderUsage = u => u ? `
    <div class="metric-row"><span class="k">Appels</span><span class="v">${u.call_count || 0}</span></div>
    <div class="metric-row"><span class="k">Tokens in</span><span class="v">${u.tokens_in || 0}</span></div>
    <div class="metric-row"><span class="k">Tokens out</span><span class="v">${u.tokens_out || 0}</span></div>
    <div class="metric-row"><span class="k">Coût (USD)</span><span class="v">$${(u.cost_usd || 0).toFixed(4)}</span></div>
  ` : `<div class="muted">—</div>`;

  root.innerHTML = `
    <div class="grid cols-2 mb">
      <div class="card"><h3>Aujourd'hui</h3>${renderUsage(d.today)}</div>
      <div class="card"><h3>Ce mois</h3>${renderUsage(d.month)}</div>
    </div>

    ${d.roles && Object.keys(d.roles).length ? `
      <div class="card mb">
        <h3>Par rôle IA</h3>
        <table>
          <thead><tr><th>Rôle</th><th>Appels</th><th>Tokens in/out</th><th>Coût</th></tr></thead>
          <tbody>${Object.entries(d.roles).map(([role, u]) => `
            <tr>
              <td class="mono">${escapeHTML(role)}</td>
              <td>${u.call_count || 0}</td>
              <td>${(u.tokens_in||0)} / ${(u.tokens_out||0)}</td>
              <td>$${(u.cost_usd||0).toFixed(4)}</td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>` : ""}

    <div class="card">
      <h3>Limites configurées</h3>
      <pre class="mono" style="margin:0;white-space:pre-wrap;color:var(--text-dim);">${escapeHTML(JSON.stringify(d.limits || {}, null, 2))}</pre>
    </div>`;
});
