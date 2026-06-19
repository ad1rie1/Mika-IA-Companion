Dash.render(async (root) => {
  const { api, escapeHTML, pager } = Dash;
  const state = { type: "", offset: 0, limit: 100 };

  async function reload() {
    const u = new URLSearchParams({ limit: state.limit, offset: state.offset });
    if (state.type) u.set("type", state.type);
    const d = await api("/dashboard/api/entities?" + u);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <select id="f-type">
          <option value="">— tous types —</option>
          <option value="person"  ${state.type==='person'?'selected':''}>person</option>
          <option value="object"  ${state.type==='object'?'selected':''}>object</option>
          <option value="place"   ${state.type==='place'?'selected':''}>place</option>
          <option value="concept" ${state.type==='concept'?'selected':''}>concept</option>
        </select>
      </div>
      <div class="card">
        <table>
          <thead><tr><th>Nom</th><th>Type</th><th>Souvenirs</th><th>Connaissances</th><th></th></tr></thead>
          <tbody>${d.rows.map(e => `
            <tr>
              <td><span class="chip mag">${escapeHTML(e.name)}</span></td>
              <td class="muted">${e.entity_type}</td>
              <td>${e.souvenir_count}</td>
              <td>${e.connaissance_count}</td>
              <td class="muted">
                <a class="btn" href="/dashboard/souvenirs/?entity=${encodeURIComponent(e.name)}">souvenirs →</a>
                <a class="btn" href="/dashboard/connaissances/?entity=${encodeURIComponent(e.name)}">connaissances →</a>
              </td>
            </tr>`).join("") || `<tr><td colspan="5" class="muted">Aucune entité.</td></tr>`}
          </tbody>
        </table>
        <div class="pager-slot"></div>
      </div>`;

    if (d.total > state.limit) {
      root.querySelector(".pager-slot").appendChild(pager({
        total: d.total, limit: state.limit, offset: state.offset,
        onPrev: o => { state.offset = o; reload(); },
        onNext: o => { state.offset = o; reload(); },
      }));
    }
    Dash.$("#f-type").onchange = e => { state.type = e.target.value; state.offset = 0; reload(); };
  }
  reload();
});
