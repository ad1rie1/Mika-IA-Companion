Dash.render(async (root) => {
  const { api, escapeHTML, clip, pct, fmtDate, fmtRel } = Dash;
  const state = { limit: 100, offset: 0 };

  async function reload() {
    const d = await api(`/dashboard/api/scheduled?limit=${state.limit}&offset=${state.offset}`);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);
    const st = s => ({pending:"warn",executed:"pos",cancelled:""}[s] || "");

    root.innerHTML = `
      <div class="card">
        <h3>Actions planifiées<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Prévu pour</th><th>Source</th><th>Priorité</th><th>Statut</th><th>Prompt</th></tr></thead>
          <tbody>${d.rows.map(a => `
            <tr>
              <td>${fmtDate(a.scheduled_at)}<small class="muted">${fmtRel(a.scheduled_at)}</small></td>
              <td class="mono muted">${escapeHTML(a.source)}</td>
              <td>${pct(a.priority)}</td>
              <td><span class="pill ${st(a.status)}">${a.status}</span></td>
              <td style="max-width:520px;">${escapeHTML(clip(a.prompt, 300))}</td>
            </tr>`).join("") || `<tr><td colspan="5" class="muted">Rien de planifié.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));
  }
  reload();
});
