Dash.render(async (root) => {
  const { api, escapeHTML, fmtRel } = Dash;
  const state = { include_invalid: false, theme: "", entity: "", limit: 80, offset: 0 };

  const qs = () => {
    const u = new URLSearchParams();
    if (state.include_invalid) u.set("include_invalid", "1");
    if (state.theme) u.set("theme", state.theme);
    if (state.entity) u.set("entity", state.entity);
    u.set("limit", state.limit); u.set("offset", state.offset);
    return u.toString();
  };

  async function reload() {
    const d = await api("/dashboard/api/connaissances?" + qs());
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <label><input type="checkbox" id="f-inv" ${state.include_invalid?'checked':''}/> inclure invalidées</label>
        <input id="f-theme"  placeholder="filtre thème" value="${escapeHTML(state.theme)}" />
        <input id="f-entity" placeholder="filtre entité" value="${escapeHTML(state.entity)}" />
      </div>
      <div class="card">
        <table>
          <thead><tr><th>Connaissance</th><th>Confiance</th><th>Validité</th><th>Thèmes</th><th>Entités</th><th>MAJ</th></tr></thead>
          <tbody>${d.rows.map(c => `
            <tr>
              <td style="max-width:540px;">${escapeHTML(c.content)}</td>
              <td>
                <div>${c.confidence.toFixed(2)}</div>
                <div class="bar"><div class="fill" style="width:${c.confidence*100}%"></div></div>
              </td>
              <td><span class="pill ${c.is_valid?'pos':'neg'}">${c.is_valid?'valide':'invalidée'}</span></td>
              <td><div class="chips">${c.themes.map(t => `<span class="chip link" data-theme="${escapeHTML(t)}">${escapeHTML(t)}</span>`).join("")}</div></td>
              <td><div class="chips">${c.entities.map(e => `<span class="chip mag link" data-entity="${escapeHTML(e.name)}">${escapeHTML(e.name)}</span>`).join("")}</div></td>
              <td class="muted">${fmtRel(c.updated_at)}</td>
            </tr>`).join("") || `<tr><td colspan="6" class="muted">Aucune connaissance.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    Dash.$("#f-inv").onchange = e => { state.include_invalid = e.target.checked; state.offset = 0; reload(); };
    const th = Dash.$("#f-theme"), en = Dash.$("#f-entity");
    th.onkeydown = e => { if (e.key === "Enter") { state.theme = th.value; state.offset = 0; reload(); } };
    en.onkeydown = e => { if (e.key === "Enter") { state.entity = en.value; state.offset = 0; reload(); } };
    Dash.$$("[data-theme]").forEach(el => el.onclick = () => { state.theme = el.dataset.theme; state.offset = 0; reload(); });
    Dash.$$("[data-entity]").forEach(el => el.onclick = () => { state.entity = el.dataset.entity; state.offset = 0; reload(); });
  }
  reload();
});
