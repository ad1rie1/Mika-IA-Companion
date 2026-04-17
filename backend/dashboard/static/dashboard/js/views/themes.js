Dash.render(async (root) => {
  const { api, escapeHTML } = Dash;
  const d = await api("/dashboard/api/themes");
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
    </div>`;
});
