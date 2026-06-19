Dash.render(async (root) => {
  const { api, escapeHTML, emoColor, emoChip, pct, fmtRel, pager, clientPager, tabs } = Dash;

  const e = await api("/dashboard/api/emotion");
  if (!e) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  // ── Vue d'ensemble : cartes de synthèse + table live ───────────
  function renderOverview(body) {
    const analytics = e.analytics || {};
    const dist = analytics.distribution || {};
    const distRows = Object.entries(dist).sort((a, b) => b[1] - a[1]).slice(0, 12);

    body.innerHTML = `
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

      <div class="card" id="emo-live-card">
        <h3>États par personne (live)<span class="tag">${e.persons.length}</span></h3>
        ${e.persons.length ? `
          <table>
            <thead><tr><th>person_id</th><th>émotion</th><th>intensité</th><th>vitesse</th><th>PAD</th></tr></thead>
            <tbody id="emo-live-body"></tbody>
          </table>` : `<div class="muted">Aucune personne active en mémoire.</div>`}
      </div>`;

    if (e.persons.length) {
      const card = body.querySelector("#emo-live-card");
      const tbody = body.querySelector("#emo-live-body");
      clientPager({
        rows: e.persons, limit: 25, mount: card,
        render: page => {
          tbody.innerHTML = page.map(p => `
            <tr>
              <td class="mono">${escapeHTML(p.person_id)}</td>
              <td>${emoChip(p.emotion)}</td>
              <td>${pct(p.intensity)}</td>
              <td>${p.velocity_magnitude.toFixed(2)}</td>
              <td class="mono muted">[${p.pad.map(x => x.toFixed(2)).join(", ")}]</td>
            </tr>`).join("");
        },
      });
    }
  }

  // ── Snapshots : table paginée serveur ──────────────────────────
  function makeSnapshotsTab() {
    const st = { offset: 0, limit: 60 };
    return async (body) => {
      async function draw() {
        const h = await api(`/dashboard/api/emotion/history?limit=${st.limit}&offset=${st.offset}`);
        const snaps = (h && h.snapshots) || [];
        const total = (h && h.total) || 0;
        body.innerHTML = `
          <div class="card">
            <h3>Snapshots récents<span class="tag">${total}</span></h3>
            <table>
              <thead><tr><th>quand</th><th>person</th><th>primary</th><th>global</th></tr></thead>
              <tbody>${snaps.map(s => `
                <tr>
                  <td class="muted">${fmtRel(s.created_at)}</td>
                  <td class="mono">${escapeHTML(s.person_id)}</td>
                  <td>${emoChip(s.primary_emotion)} <small>${pct(s.primary_intensity)}</small></td>
                  <td>${emoChip(s.global_emotion)} <small>${pct(s.global_intensity)}</small></td>
                </tr>`).join("") || `<tr><td colspan="4" class="muted">Aucun snapshot.</td></tr>`}</tbody>
            </table>
            <div class="pager-slot"></div>
          </div>`;
        if (total > st.limit) {
          body.querySelector(".pager-slot").appendChild(pager({
            total, limit: st.limit, offset: st.offset,
            onPrev: o => { st.offset = o; draw(); },
            onNext: o => { st.offset = o; draw(); },
          }));
        }
      }
      await draw();
    };
  }

  // ── Résumés : table paginée serveur (summary_*) ────────────────
  function makeSummariesTab() {
    const st = { offset: 0, limit: 30 };
    return async (body) => {
      async function draw() {
        const h = await api(`/dashboard/api/emotion/history?limit=1&summary_limit=${st.limit}&summary_offset=${st.offset}`);
        const summaries = (h && h.summaries) || [];
        const total = (h && h.summaries_total) || 0;
        body.innerHTML = `
          <div class="card">
            <h3>Résumés agrégés<span class="tag">${total}</span></h3>
            <table>
              <thead><tr><th>période</th><th>person</th><th>dominante</th><th>trend</th><th>#</th></tr></thead>
              <tbody>${summaries.map(s => `
                <tr>
                  <td class="muted">${s.period_start} <small>${s.period_type}</small></td>
                  <td class="mono">${escapeHTML(s.person_id)}</td>
                  <td>${emoChip(s.dominant_emotion)} <small>${pct(s.dominant_intensity)}</small></td>
                  <td>${s.trend}</td>
                  <td>${s.snapshot_count}</td>
                </tr>`).join("") || `<tr><td colspan="5" class="muted">Aucun résumé.</td></tr>`}</tbody>
            </table>
            <div class="pager-slot"></div>
          </div>`;
        if (total > st.limit) {
          body.querySelector(".pager-slot").appendChild(pager({
            total, limit: st.limit, offset: st.offset,
            onPrev: o => { st.offset = o; draw(); },
            onNext: o => { st.offset = o; draw(); },
          }));
        }
      }
      await draw();
    };
  }

  tabs({
    mount: root,
    storeKey: "dash.emotion.tab",
    tabs: [
      { key: "overview",  label: "Vue d'ensemble", render: renderOverview },
      { key: "snapshots", label: "Snapshots",      render: makeSnapshotsTab() },
      { key: "summaries", label: "Résumés",        render: makeSummariesTab() },
    ],
  });
});
