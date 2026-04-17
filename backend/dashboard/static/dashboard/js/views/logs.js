Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtRel } = Dash;
  const state = { limit: 100, offset: 0 };

  async function reload() {
    const d = await api(`/dashboard/api/conscience/logs?limit=${state.limit}&offset=${state.offset}`);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const decCls = x => ({act:"pos",wait:"",skip:"warn"}[x] || "");

    root.innerHTML = `
      <div class="card mb">
        <h3>Inactivité actuelle</h3>
        <div class="stat-value">${d.idle_seconds != null ? Math.round(d.idle_seconds) + "s" : "—"}</div>
      </div>
      <div class="card">
        <h3>Journal des décisions<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Quand</th><th>Décision</th><th>Raison</th><th>Pert. max</th><th>Humeur</th><th>Idle</th><th>Obs.</th></tr></thead>
          <tbody>${d.rows.map(l => `
            <tr>
              <td class="muted">${fmtRel(l.created_at)}</td>
              <td><span class="pill ${decCls(l.decision)}">${l.decision}</span></td>
              <td style="max-width:420px;">${escapeHTML(l.reason || "—")}</td>
              <td>${pct(l.max_pertinence)}</td>
              <td>${emoChip(l.global_mood || "neutral", l.global_intensity)}</td>
              <td class="muted">${l.idle_seconds}s</td>
              <td class="muted">${l.observations_count}</td>
            </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucun log.</td></tr>`}
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
