Dash.render(async (root) => {
  const { api, escapeHTML, fmtDate, fmtRel } = Dash;
  const state = { status: "", limit: 100, offset: 0 };

  async function reload() {
    const u = new URLSearchParams();
    if (state.status) u.set("status", state.status);
    u.set("limit", state.limit); u.set("offset", state.offset);
    const d = await api("/dashboard/api/commitments?" + u);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const statusPill = s => ({pending:"warn",honored:"pos",dropped:"neg"}[s] || "");

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <select id="f-status">
          <option value="">— tous —</option>
          <option value="pending" ${state.status==='pending'?'selected':''}>pending</option>
          <option value="honored" ${state.status==='honored'?'selected':''}>honored</option>
          <option value="dropped" ${state.status==='dropped'?'selected':''}>dropped</option>
        </select>
      </div>
      <div class="card">
        <h3>Engagements<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Engagement</th><th>Personne</th><th>Statut</th><th>Échéance</th><th>Créé</th></tr></thead>
          <tbody>${d.rows.map(c => `
            <tr>
              <td style="max-width:540px;">${escapeHTML(c.description)}</td>
              <td>${c.person ? `<span class="chip mag">${escapeHTML(c.person)}</span>` : `<span class="muted">—</span>`}</td>
              <td><span class="pill ${statusPill(c.status)}">${c.status}</span></td>
              <td class="muted">${c.due_at ? fmtDate(c.due_at) : "—"}</td>
              <td class="muted">${fmtRel(c.created_at)}</td>
            </tr>`).join("") || `<tr><td colspan="5" class="muted">Aucun engagement.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    Dash.$("#f-status").onchange = e => { state.status = e.target.value; state.offset = 0; reload(); };
  }
  reload();
});
