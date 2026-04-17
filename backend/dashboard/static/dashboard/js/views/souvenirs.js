Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, fmtRel } = Dash;
  const state = {
    order: "-occurred_at", theme: "", entity: "", limit: 50, offset: 0,
  };

  const qs = () => {
    const u = new URLSearchParams();
    u.set("order", state.order);
    if (state.theme) u.set("theme", state.theme);
    if (state.entity) u.set("entity", state.entity);
    u.set("limit", state.limit); u.set("offset", state.offset);
    return u.toString();
  };

  async function reload() {
    const d = await api("/dashboard/api/souvenirs?" + qs());
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const bar = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <select id="f-order">
          <option value="-occurred_at" ${state.order==='-occurred_at'?'selected':''}>récents</option>
          <option value="-importance" ${state.order==='-importance'?'selected':''}>importance</option>
          <option value="-created_at" ${state.order==='-created_at'?'selected':''}>création</option>
        </select>
        <input id="f-theme"  placeholder="filtre thème" value="${escapeHTML(state.theme)}" />
        <input id="f-entity" placeholder="filtre entité" value="${escapeHTML(state.entity)}" />
        ${state.theme || state.entity ? `<button class="btn" id="f-clear">clear</button>` : ""}
      </div>`;

    root.innerHTML = `
      ${bar}
      <div class="card">
        <table>
          <thead><tr><th>Souvenir</th><th>Émotion</th><th>Importance</th><th>Thèmes</th><th>Entités</th><th>Date</th></tr></thead>
          <tbody>${d.rows.map(s => `
            <tr>
              <td style="max-width:540px;">${escapeHTML(s.content)}</td>
              <td>${emoChip(s.emotion)}</td>
              <td>
                <div>${s.importance.toFixed(2)}</div>
                <div class="bar"><div class="fill" style="width:${Math.min(100, s.importance*100)}%"></div></div>
              </td>
              <td><div class="chips">${s.themes.map(t => `<span class="chip link" data-theme="${escapeHTML(t)}">${escapeHTML(t)}</span>`).join("")}</div></td>
              <td><div class="chips">${s.entities.map(e => `<span class="chip mag link" data-entity="${escapeHTML(e.name)}">${escapeHTML(e.name)}</span>`).join("")}</div></td>
              <td class="muted">${fmtRel(s.occurred_at)}</td>
            </tr>`).join("") || `<tr><td colspan="6" class="muted">Aucun souvenir.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    Dash.$("#f-order").onchange = e => { state.order = e.target.value; state.offset = 0; reload(); };
    const th = Dash.$("#f-theme"), en = Dash.$("#f-entity");
    th.onkeydown  = e => { if (e.key === "Enter") { state.theme  = th.value; state.offset = 0; reload(); } };
    en.onkeydown  = e => { if (e.key === "Enter") { state.entity = en.value; state.offset = 0; reload(); } };
    const clr = Dash.$("#f-clear");
    if (clr) clr.onclick = () => { state.theme = ""; state.entity = ""; state.offset = 0; reload(); };
    Dash.$$("[data-theme]").forEach(el => el.onclick = () => {
      state.theme = el.dataset.theme; state.offset = 0; reload();
    });
    Dash.$$("[data-entity]").forEach(el => el.onclick = () => {
      state.entity = el.dataset.entity; state.offset = 0; reload();
    });
  }
  reload();
});
