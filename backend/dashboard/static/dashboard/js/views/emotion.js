Dash.render(async (root) => {
  const { api, escapeHTML, emoColor, emoChip, pct, fmtRel } = Dash;
  const [e, h] = await Promise.all([
    api("/dashboard/api/emotion"),
    api("/dashboard/api/emotion/history?limit=60"),
  ]);
  if (!e) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  const snaps = (h && h.snapshots) || [];
  const summaries = (h && h.summaries) || [];
  const analytics = e.analytics || {};
  const dist = analytics.distribution || {};
  const distRows = Object.entries(dist).sort((a,b)=>b[1]-a[1]).slice(0, 12);

  root.innerHTML = `
    <div class="grid cols-3 mb">
      <div class="card">
        <h3>Global</h3>
        <div class="stat-value" style="color:${emoColor(e.global.emotion)}">${e.global.emotion}</div>
        <div class="stat-sub">intensité ${pct(e.global.intensity)}</div>
        <div class="mt muted" style="font-size:11px;">par défaut : ${emoChip(e.temperament.default_mood)}</div>
      </div>
      <div class="card">
        <h3>Analytics</h3>
        <div class="metric-row"><span class="k">Personnes suivies</span><span class="v">${analytics.persons_tracked || 0}</span></div>
        <div class="metric-row"><span class="k">Interactions (RAM)</span><span class="v">${analytics.total_interactions || 0}</span></div>
        <div class="metric-row"><span class="k">Émotion dominante</span><span class="v">${emoChip(analytics.dominant_emotion || "neutral")}</span></div>
      </div>
      <div class="card">
        <h3>Top distribution (RAM)</h3>
        ${distRows.length ? distRows.map(([k, v]) => `
          <div style="margin-bottom:6px;">
            <div class="flex between"><span style="color:${emoColor(k)}">${k}</span><span>${pct(v)}</span></div>
            <div class="bar"><div class="fill" style="width:${v*100}%;background:${emoColor(k)}"></div></div>
          </div>`).join("") : `<div class="muted">Pas encore d'historique.</div>`}
      </div>
    </div>

    <div class="card mb">
      <h3>États par personne (live)</h3>
      ${e.persons.length ? `
        <table>
          <thead><tr><th>person_id</th><th>émotion</th><th>intensité</th><th>vitesse</th><th>PAD</th></tr></thead>
          <tbody>
            ${e.persons.map(p => `
              <tr>
                <td class="mono">${escapeHTML(p.person_id)}</td>
                <td>${emoChip(p.emotion)}</td>
                <td>${pct(p.intensity)}</td>
                <td>${p.velocity_magnitude.toFixed(2)}</td>
                <td class="mono muted">[${p.pad.map(x=>x.toFixed(2)).join(", ")}]</td>
              </tr>`).join("")}
          </tbody>
        </table>` : `<div class="muted">Aucune personne active en mémoire.</div>`}
    </div>

    <div class="two-col">
      <div class="card">
        <h3>Snapshots récents</h3>
        <div class="scroll-box">
          <table>
            <thead><tr><th>quand</th><th>person</th><th>primary</th><th>global</th></tr></thead>
            <tbody>${snaps.map(s => `
              <tr>
                <td class="muted">${fmtRel(s.created_at)}</td>
                <td class="mono">${escapeHTML(s.person_id)}</td>
                <td>${emoChip(s.primary_emotion)} <small>${pct(s.primary_intensity)}</small></td>
                <td>${emoChip(s.global_emotion)} <small>${pct(s.global_intensity)}</small></td>
              </tr>`).join("")}</tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <h3>Résumés agrégés</h3>
        <div class="scroll-box">
          <table>
            <thead><tr><th>période</th><th>person</th><th>dominante</th><th>trend</th><th>#</th></tr></thead>
            <tbody>${summaries.map(s => `
              <tr>
                <td class="muted">${s.period_start} <small>${s.period_type}</small></td>
                <td class="mono">${escapeHTML(s.person_id)}</td>
                <td>${emoChip(s.dominant_emotion)} <small>${pct(s.dominant_intensity)}</small></td>
                <td>${s.trend}</td>
                <td>${s.snapshot_count}</td>
              </tr>`).join("")}</tbody>
          </table>
        </div>
      </div>
    </div>`;
});
