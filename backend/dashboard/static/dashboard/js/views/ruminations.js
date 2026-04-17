Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtRel } = Dash;

  const state = { status: "", limit: 50, offset: 0 };
  const qs = () => {
    const u = new URLSearchParams();
    if (state.status) u.set("status", state.status);
    u.set("limit", state.limit); u.set("offset", state.offset);
    return u.toString();
  };

  async function reload() {
    const d = await Dash.api("/dashboard/api/ruminations?" + qs());
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <select id="f-status">
          <option value="">— tous statuts —</option>
          <option value="active" ${state.status==='active'?'selected':''}>active</option>
          <option value="resolved" ${state.status==='resolved'?'selected':''}>resolved</option>
          <option value="faded" ${state.status==='faded'?'selected':''}>faded</option>
        </select>
      </div>
      <div class="card">
        <h3>Ruminations<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Pensée</th><th>émotion</th><th>intensité</th><th>statut</th><th>créée</th></tr></thead>
          <tbody>${d.rows.map(r => `
            <tr>
              <td style="max-width:560px;">
                ${escapeHTML(r.summary)}
                <div class="chips mt">${(r.themes||[]).map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("")}</div>
              </td>
              <td>${r.emotion ? emoChip(r.emotion) : `<span class="muted">—</span>`}</td>
              <td>
                <div>${pct(r.intensity)}</div>
                <div class="bar"><div class="fill" style="width:${r.intensity*100}%"></div></div>
              </td>
              <td><span class="pill ${r.status==='active'?'mag':r.status==='resolved'?'pos':''}">${r.status}</span></td>
              <td class="muted">${fmtRel(r.created_at)}</td>
            </tr>`).join("") || `<tr><td colspan="5" class="muted">Aucune rumination.</td></tr>`}
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
