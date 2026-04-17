Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtRel } = Dash;
  const d = await api("/dashboard/api/persons");
  if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  const closeColor = c => ({close:"pos",friend:"pos",acquaintance:"",stranger:"warn"}[c] || "");

  root.innerHTML = `
    <div class="grid cols-2 mb">
      ${d.profiles.map(p => `
        <div class="card">
          <h3>${escapeHTML(p.name)}<span class="tag">${p.profile ? "profil" : "inconnu"}</span></h3>
          ${p.profile ? `
            <div class="flex between center mb">
              <span class="pill ${closeColor(p.profile.closeness)}">${p.profile.closeness}</span>
              <span class="muted">ton préféré : <b>${p.profile.preferred_tone}</b></span>
            </div>
            <div class="narr mb">${escapeHTML(p.profile.summary || "—")}</div>
            <div class="mt">
              <div class="muted" style="font-size:11px;">Centres d'intérêt</div>
              <div class="chips">${(p.profile.topics_of_interest || []).map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("") || '<span class="muted">—</span>'}</div>
            </div>
            <div class="mt">
              <div class="muted" style="font-size:11px;">Sujets sensibles</div>
              <div class="chips">${(p.profile.sensitive_topics || []).map(t => `<span class="chip" style="color:var(--red);border-color:rgba(255,91,110,0.3);">${escapeHTML(t)}</span>`).join("") || '<span class="muted">—</span>'}</div>
            </div>
            <div class="metric-row mt"><span class="k">Interactions</span><span class="v">${p.profile.interaction_count}</span></div>
            <div class="metric-row"><span class="k">Confiance profil</span><span class="v">${pct(p.profile.confidence)}</span></div>
            <div class="metric-row"><span class="k">Dernière interaction</span><span class="v">${fmtRel(p.profile.last_interaction_at)} ago</span></div>
            <div class="metric-row"><span class="k">Engagements pending</span><span class="v">${p.commitments_pending}</span></div>
            <div class="mt">
              <a class="btn" href="/dashboard/souvenirs/?entity=${encodeURIComponent(p.name)}">souvenirs →</a>
              <a class="btn" href="/dashboard/connaissances/?entity=${encodeURIComponent(p.name)}">connaissances →</a>
            </div>
          ` : `<div class="muted">Pas encore de profil généré pour cette personne.</div>`}
        </div>`).join("") || `<div class="empty">Aucune personne connue.</div>`}
    </div>

    <div class="card">
      <h3>Affect live (RAM)<span class="tag">${d.live_affect.length}</span></h3>
      ${d.live_affect.length ? `
        <table>
          <thead><tr><th>person_id</th><th>émotion</th><th>intensité</th><th>vélocité</th><th>historique</th><th>dernière interaction</th></tr></thead>
          <tbody>${d.live_affect.map(a => `
            <tr>
              <td class="mono">
                <a class="chip link" href="/dashboard/messages/?person_id=${encodeURIComponent(a.person_id)}">${escapeHTML(a.person_id)}</a>
              </td>
              <td>${emoChip(a.emotion)}</td>
              <td>${pct(a.intensity)}</td>
              <td>${a.velocity.toFixed(2)}</td>
              <td>${a.history_size}</td>
              <td class="muted">${fmtRel(new Date(a.last_interaction*1000).toISOString())} ago</td>
            </tr>`).join("")}
          </tbody>
        </table>` : `<div class="muted">Aucun état actif.</div>`}
    </div>`;
});
