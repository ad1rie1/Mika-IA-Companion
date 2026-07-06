Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtRel } = Dash;
  const closeColor = c => ({close:"pos",friend:"pos",acquaintance:"",stranger:"warn"}[c] || "");

  const id = window.PERSON_ID;
  const d = await api("/dashboard/api/persons/" + id);
  if (!d) return (root.innerHTML = `<div class="empty">Personne introuvable.</div>`);
  const p = d.profile;

  const affectBlock = d.affect ? `
    <div class="mt">
      <div class="muted" style="font-size:11px;">Affect live (RAM)</div>
      <div class="flex center" style="gap:14px;flex-wrap:wrap;">
        <span>${emoChip(d.affect.emotion)}</span>
        <span class="muted">intensité <b>${pct(d.affect.intensity)}</b></span>
        <span class="muted">vélocité <b>${d.affect.velocity.toFixed(2)}</b></span>
        <span class="muted">historique <b>${d.affect.history_size}</b></span>
        <span class="muted mono">${escapeHTML(d.affect.person_id)}</span>
      </div>
    </div>` : "";

  const commitmentsBlock = d.commitments.length ? `
    <div class="mt">
      <div class="muted" style="font-size:11px;">Engagements en attente (${d.commitments.length})</div>
      <ul class="narr" style="margin:6px 0 0;padding-left:18px;">
        ${d.commitments.map(c => `<li>${escapeHTML(c.description)} <span class="muted">— ${fmtRel(c.created_at)}</span></li>`).join("")}
      </ul>
    </div>` : "";

  const header = `
    <div class="mb"><a class="btn ghost" href="/dashboard/persons/">← Toutes les personnes</a></div>
    <div class="card">
      <h3>${escapeHTML(d.name)}<span class="tag">${p ? "profil" : "inconnu"}</span></h3>
      ${p ? `
        <div class="flex between center mb">
          <span class="pill ${closeColor(p.closeness)}">${p.closeness}</span>
          <span class="muted">ton préféré : <b>${p.preferred_tone}</b></span>
        </div>
        <div class="narr mb">${escapeHTML(p.summary || "—")}</div>
        <div class="grid cols-2">
          <div>
            <div class="muted" style="font-size:11px;">Centres d'intérêt</div>
            <div class="chips">${(p.topics_of_interest || []).map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("") || '<span class="muted">—</span>'}</div>
          </div>
          <div>
            <div class="muted" style="font-size:11px;">Sujets sensibles</div>
            <div class="chips">${(p.sensitive_topics || []).map(t => `<span class="chip" style="color:var(--red);border-color:rgba(255,91,110,0.3);">${escapeHTML(t)}</span>`).join("") || '<span class="muted">—</span>'}</div>
          </div>
        </div>
        <div class="flex center mt" style="gap:20px;flex-wrap:wrap;">
          <span class="muted">Interactions <b>${p.interaction_count}</b></span>
          <span class="muted">Confiance <b>${pct(p.confidence)}</b></span>
          <span class="muted">Dernière interaction <b>${p.last_interaction_at ? fmtRel(p.last_interaction_at) + " ago" : "—"}</b></span>
          <span class="muted">Profil généré <b>${p.generated_at ? fmtRel(p.generated_at) + " ago" : "—"}</b></span>
        </div>
        ${commitmentsBlock}
        ${affectBlock}
      ` : `
        <div class="muted">Pas encore de profil généré pour cette personne.</div>
        ${commitmentsBlock}
        ${affectBlock}`}
    </div>`;

  root.innerHTML = `${header}<div id="person-tabs" class="mt"></div>`;

  // --- Onglet paginé générique -------------------------------------------
  // Chaque onglet a son propre offset ; le body est fourni par Dash.tabs.
  const makeTab = (baseUrl, renderTable, emptyText) => {
    const state = { offset: 0, limit: 25 };
    return async function render(body) {
      async function draw() {
        const sep = baseUrl.includes("?") ? "&" : "?";
        const d = await api(`${baseUrl}${sep}limit=${state.limit}&offset=${state.offset}`);
        if (!d) { body.innerHTML = `<div class="empty">Indisponible.</div>`; return; }
        body.innerHTML = `<div class="card">${
          d.rows.length ? renderTable(d.rows) : `<div class="muted">${emptyText}</div>`
        }</div>`;
        if (d.total > state.limit || state.offset > 0) {
          body.appendChild(Dash.pager({
            total: d.total, limit: d.limit, offset: d.offset,
            onPrev: o => { state.offset = o; draw(); },
            onNext: o => { state.offset = o; draw(); },
          }));
        }
      }
      await draw();
    };
  };

  const name = encodeURIComponent(d.name);

  const souvenirsTable = rows => `
    <table>
      <thead><tr><th>Souvenir</th><th>Émotion</th><th>Importance</th><th>Thèmes</th><th>Date</th></tr></thead>
      <tbody>${rows.map(s => `
        <tr>
          <td style="max-width:520px;">${escapeHTML(s.content)}</td>
          <td>${emoChip(s.emotion)}</td>
          <td>
            <div>${s.importance.toFixed(2)}</div>
            <div class="bar"><div class="fill" style="width:${Math.min(100, s.importance*100)}%"></div></div>
          </td>
          <td><div class="chips">${s.themes.map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("")}</div></td>
          <td class="muted">${fmtRel(s.occurred_at)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;

  const connaissancesTable = rows => `
    <table>
      <thead><tr><th>Connaissance</th><th>Confiance</th><th>Thèmes</th><th>Mise à jour</th></tr></thead>
      <tbody>${rows.map(c => `
        <tr>
          <td style="max-width:520px;">${escapeHTML(c.content)}${c.is_valid ? "" : ` <span class="tag">invalide</span>`}</td>
          <td>${pct(c.confidence)}</td>
          <td><div class="chips">${c.themes.map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("")}</div></td>
          <td class="muted">${fmtRel(c.updated_at)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;

  const messagesTable = rows => `
    <table>
      <thead><tr><th>Rôle</th><th>Message</th><th>Source</th><th>Émotion</th><th>Date</th></tr></thead>
      <tbody>${rows.map(m => `
        <tr>
          <td><span class="pill ${m.role === "assistant" ? "pos" : ""}">${escapeHTML(m.role)}</span></td>
          <td style="max-width:520px;">${escapeHTML(m.content)}</td>
          <td>${m.source ? `<span class="chip">${escapeHTML(m.source)}</span>` : `<span class="muted">—</span>`}</td>
          <td>${m.emotion ? emoChip(m.emotion, m.emotion_intensity) : `<span class="muted">—</span>`}</td>
          <td class="muted">${fmtRel(m.created_at)}</td>
        </tr>`).join("")}
      </tbody>
    </table>`;

  Dash.tabs({
    mount: root.querySelector("#person-tabs"),
    storeKey: "person-detail-tab",
    tabs: [
      { key: "souvenirs",     label: "Souvenirs",
        render: makeTab(`/dashboard/api/souvenirs?entity=${name}`, souvenirsTable, "Aucun souvenir lié.") },
      { key: "connaissances", label: "Connaissances",
        render: makeTab(`/dashboard/api/connaissances?entity=${name}`, connaissancesTable, "Aucune connaissance liée.") },
      { key: "messages",      label: "Messages",
        render: makeTab(`/dashboard/api/messages?person_id=${encodeURIComponent(id)}`, messagesTable, "Aucun message enregistré sous cet identifiant.") },
    ],
  });
});
