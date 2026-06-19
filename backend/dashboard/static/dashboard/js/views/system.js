Dash.render(async (root) => {
  const { api, escapeHTML, fmtRel, pager } = Dash;
  const cfg = await api("/dashboard/api/system/ai-config");

  const roleTable = cfg && cfg.available ? `
    <table>
      <thead><tr><th>Rôle</th><th>Provider</th><th>Modèle</th></tr></thead>
      <tbody>${cfg.roles.map(r => `
        <tr>
          <td class="mono">${escapeHTML(r.role)}</td>
          <td><span class="pill">${escapeHTML(r.provider)}</span></td>
          <td class="mono muted">${escapeHTML(r.model)}</td>
        </tr>`).join("")}
      </tbody>
    </table>` : `<div class="muted">Routeur IA indisponible.</div>`;

  const providers = cfg?.providers || {};
  const providerCard = (name, cfg) => {
    const ok = cfg.oauth_configured || cfg.api_key_configured || cfg.base_url;
    return `
      <div class="card">
        <h3>${escapeHTML(name)}<span class="pill ${ok?'pos':'warn'}">${ok?'configuré':'manquant'}</span></h3>
        <pre class="mono" style="margin:0;white-space:pre-wrap;color:var(--text-dim);">${escapeHTML(JSON.stringify(cfg, null, 2))}</pre>
      </div>`;
  };

  const knobs = cfg?.knobs || {};

  root.innerHTML = `
    <div class="card mb">
      <h3>Routeur IA</h3>
      ${roleTable}
    </div>

    <div class="grid cols-3 mb">
      ${Object.entries(providers).map(([k, v]) => providerCard(k, v)).join("")}
    </div>

    <div class="card mb">
      <h3>Paramètres runtime</h3>
      <table>
        <thead><tr><th>Clé</th><th>Valeur</th></tr></thead>
        <tbody>${Object.entries(knobs).map(([k, v]) => `
          <tr><td class="mono muted">${escapeHTML(k)}</td><td>${escapeHTML(String(v))}</td></tr>
        `).join("")}</tbody>
      </table>
    </div>

    <div class="card" id="cons-card">
      <h3>Consolidation mémoire<span class="tag" id="cons-total">…</span></h3>
      <table>
        <thead><tr><th>Quand</th><th>Messages</th><th>Souvenirs</th><th>Connaissances</th><th>Last msg id</th></tr></thead>
        <tbody id="cons-body"></tbody>
      </table>
      <div class="pager-slot"></div>
    </div>`;

  // Consolidation — table paginée serveur
  const consCard = root.querySelector("#cons-card");
  const consBody = root.querySelector("#cons-body");
  const consTotal = root.querySelector("#cons-total");
  const limit = 30;
  let offset = 0;

  async function drawCons() {
    const cons = await api(`/dashboard/api/system/consolidation?limit=${limit}&offset=${offset}`);
    const rows = (cons && cons.rows) || [];
    const total = (cons && cons.total) || 0;
    consTotal.textContent = total;
    consBody.innerHTML = rows.map(l => `
      <tr>
        <td class="muted">${fmtRel(l.ran_at)}</td>
        <td>${l.messages_processed}</td>
        <td>${l.souvenirs_created}</td>
        <td>${l.connaissances_created}</td>
        <td class="muted">${l.last_message_id}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="muted">Aucune passe.</td></tr>`;
    const slot = consCard.querySelector(".pager-slot");
    slot.innerHTML = "";
    if (total > limit) {
      slot.appendChild(pager({
        total, limit, offset,
        onPrev: o => { offset = o; drawCons(); },
        onNext: o => { offset = o; drawCons(); },
      }));
    }
  }
  drawCons();
});
