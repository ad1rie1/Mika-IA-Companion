Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, clip, fmtRel } = Dash;
  const state = { status: "", category: "", limit: 100, offset: 0 };

  async function reload() {
    const u = new URLSearchParams();
    if (state.status) u.set("status", state.status);
    if (state.category) u.set("category", state.category);
    u.set("limit", state.limit); u.set("offset", state.offset);
    const d = await api("/dashboard/api/observations?" + u);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const sp = s => ({pending:"warn",acted:"pos",skipped:"",failed:"neg"}[s] || "");

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <select id="f-status">
          <option value="">— tous statuts —</option>
          <option value="pending" ${state.status==='pending'?'selected':''}>pending</option>
          <option value="acted"   ${state.status==='acted'?'selected':''}>acted</option>
          <option value="skipped" ${state.status==='skipped'?'selected':''}>skipped</option>
          <option value="failed"  ${state.status==='failed'?'selected':''}>failed</option>
        </select>
        <select id="f-cat">
          <option value="">— toutes catégories —</option>
          ${["communication","emotional","memory","temporal","external","system"]
            .map(c => `<option value="${c}" ${state.category===c?'selected':''}>${c}</option>`).join("")}
        </select>
      </div>
      <div class="card">
        <h3>Observations<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Source</th><th>Event</th><th>Cat.</th><th>Résumé</th><th>Pertinence</th><th>Réaction</th><th>Statut</th><th>Quand</th></tr></thead>
          <tbody>${d.rows.map(o => `
            <tr>
              <td class="muted mono">${escapeHTML(o.source)}</td>
              <td class="muted mono">${escapeHTML(o.event_type)}</td>
              <td><span class="pill">${o.category}</span></td>
              <td style="max-width:420px;">${escapeHTML(clip(o.summary, 200))}
                ${o.action_response ? `<small>→ ${escapeHTML(clip(o.action_response, 200))}</small>` : ""}</td>
              <td>
                <div>${pct(o.pertinence)}</div>
                <div class="bar"><div class="fill" style="width:${o.pertinence*100}%"></div></div>
              </td>
              <td>${o.emotional_reaction ? emoChip(o.emotional_reaction, o.emotional_intensity) : `<span class="muted">—</span>`}</td>
              <td><span class="pill ${sp(o.status)}">${o.status}</span></td>
              <td class="muted">${fmtRel(o.created_at)}</td>
            </tr>`).join("") || `<tr><td colspan="8" class="muted">Aucune observation.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    Dash.$("#f-status").onchange = e => { state.status = e.target.value; state.offset = 0; reload(); };
    Dash.$("#f-cat").onchange = e => { state.category = e.target.value; state.offset = 0; reload(); };
  }
  reload();
});
