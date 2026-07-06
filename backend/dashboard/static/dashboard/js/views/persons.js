Dash.render(async (root) => {
  const { api, escapeHTML, pct, fmtRel } = Dash;
  const closeColor = c => ({close:"pos",friend:"pos",acquaintance:"",stranger:"warn"}[c] || "");

  const state = { q: "", limit: 25, offset: 0 };

  // Préchargement du filtre depuis l'URL (?q=)
  const u0 = new URLSearchParams(window.location.search);
  if (u0.get("q")) state.q = u0.get("q");

  const qs = () => {
    const u = new URLSearchParams();
    if (state.q) u.set("q", state.q);
    u.set("limit", state.limit); u.set("offset", state.offset);
    return u.toString();
  };

  async function reload() {
    const d = await api("/dashboard/api/persons?" + qs());
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    const bar = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <input id="f-q" placeholder="rechercher un nom" value="${escapeHTML(state.q)}" />
        ${state.q ? `<button class="btn" id="f-clear">clear</button>` : ""}
      </div>`;

    root.innerHTML = `
      ${bar}
      <div class="card">
        <table>
          <thead><tr><th>Nom</th><th>Proximité</th><th>Interactions</th><th>Engagements</th><th>Confiance</th><th>Dernière interaction</th><th></th></tr></thead>
          <tbody>${d.rows.map(r => `
            <tr>
              <td>${escapeHTML(r.name)}${r.has_profile ? "" : ` <span class="tag">inconnu</span>`}</td>
              <td>${r.closeness ? `<span class="pill ${closeColor(r.closeness)}">${r.closeness}</span>` : `<span class="muted">—</span>`}</td>
              <td>${r.interaction_count}</td>
              <td>${r.commitments_pending || `<span class="muted">0</span>`}</td>
              <td>${r.confidence != null ? pct(r.confidence) : `<span class="muted">—</span>`}</td>
              <td class="muted">${r.last_interaction_at ? fmtRel(r.last_interaction_at) + " ago" : "—"}</td>
              <td><a class="btn" href="/dashboard/persons/${r.entity_id}/">Voir →</a></td>
            </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucune personne connue.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    const q = Dash.$("#f-q");
    q.onkeydown = e => { if (e.key === "Enter") { state.q = q.value; state.offset = 0; reload(); } };
    const clr = Dash.$("#f-clear");
    if (clr) clr.onclick = () => { state.q = ""; state.offset = 0; reload(); };
  }

  reload();
});
