Dash.render(async (root) => {
  const { api, escapeHTML, pager } = Dash;
  const state = { offset: 0, limit: 100 };

  async function reload() {
    const u = new URLSearchParams({ limit: state.limit, offset: state.offset });
    const d = await api("/dashboard/api/themes?" + u);
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    root.innerHTML = `
      <div class="card">
        <h3>Thèmes<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Thème</th><th>Souvenirs</th><th>Connaissances</th><th></th></tr></thead>
          <tbody>${d.rows.map(t => `
            <tr>
              <td><span class="chip">${escapeHTML(t.name)}</span></td>
              <td>${t.souvenir_count}</td>
              <td>${t.connaissance_count}</td>
              <td class="muted">
                <a class="btn" href="/dashboard/souvenirs/?theme=${encodeURIComponent(t.name)}">voir souvenirs →</a>
              </td>
            </tr>`).join("") || `<tr><td colspan="4" class="muted">Aucun thème.</td></tr>`}
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
  }
  reload();
});
