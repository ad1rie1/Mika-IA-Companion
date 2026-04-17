Dash.render(async (root) => {
  const { api, escapeHTML, emoColor, emoChip, pct, fmtRel } = Dash;
  const d = await api("/dashboard/api/overview");
  if (!d) return (root.innerHTML = `<div class="empty">Impossible de charger.</div>`);

  const n = d.counts;
  const drives = d.drives || {};

  const statBlock = (k, v, sub) => `
    <div class="card">
      <h3>${k}</h3>
      <div class="stat-value">${v}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ""}
    </div>`;

  const driveBar = (kind, t) => {
    const label = {curiosity:"Curiosité",social:"Social",expression:"Expression",rest:"Repos"}[kind] || kind;
    const cls = kind === "rest" ? "warn" : "";
    return `
      <div style="margin-bottom:10px;">
        <div class="flex between"><span class="muted">${label}</span><span>${pct(t)}</span></div>
        <div class="bar ${cls}"><div class="fill" style="width:${Math.min(100, t*100)}%"></div></div>
      </div>`;
  };

  root.innerHTML = `
    <div class="grid cols-4 mb">
      ${statBlock("Humeur globale",
        `<span style="color:${emoColor(d.emotion.global_label)}">${d.emotion.global_label}</span>`,
        `intensité ${pct(d.emotion.global_intensity)} · base: ${d.emotion.default_mood}`)}
      ${statBlock("Énergie", pct(d.energy),
        `circadien ${d.circadian.phase} · ${d.circadian.hour}h`)}
      ${statBlock("Phase sommeil",
        `<span style="color:${d.sleep_phase==='awake'?'var(--cyan)':'var(--violet)'}">${d.sleep_phase}</span>`, "")}
      ${statBlock("Drive dominant",
        d.dominant_drive ? `<span style="color:var(--magenta)">${d.dominant_drive}</span>` : `<span class="muted">aucun</span>`,
        "pression intrinsèque")}
    </div>

    <div class="grid cols-3 mb">
      <div class="card">
        <h3>Drives</h3>
        ${Object.entries(drives).map(([k, v]) => driveBar(k, v)).join("")}
      </div>
      <div class="card">
        <h3>Compteurs mémoire</h3>
        ${[
          ["Conversations", n.conversations],
          ["Messages (total)", n.messages],
          ["Messages (24h)", n.messages_24h],
          ["Souvenirs", n.souvenirs],
          ["Connaissances (valides)", n.connaissances],
          ["Connaissances invalidées", n.connaissances_invalid],
          ["Thèmes", n.themes],
          ["Entités", n.entities],
        ].map(([k, v]) => `<div class="metric-row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("")}
      </div>
      <div class="card">
        <h3>État cognitif</h3>
        ${[
          ["Personnes connues", n.persons],
          ["Profils générés", n.person_profiles],
          ["Personnes actives (RAM)", n.tracked_persons_ram],
          ["Observations pending", n.observations_pending],
          ["Ruminations actives", n.ruminations_active],
          ["Engagements pending", n.commitments_pending],
          ["Rêves enregistrés", n.dreams],
          ["Journaux quotidiens", n.journals],
          ["Projets actifs", n.projects_active],
          ["Actions à valider", n.pending_actions],
        ].map(([k, v]) => `<div class="metric-row"><span class="k">${k}</span><span class="v">${v}</span></div>`).join("")}
      </div>
    </div>

    ${d.current_narrative ? `
      <div class="card mb">
        <h3>Self-Concept actuel<span class="tag">${fmtRel(d.current_narrative.created_at)}</span></h3>
        <div class="big-narrative narr">${escapeHTML(d.current_narrative.content)}</div>
        ${d.current_narrative.dominant_mood ? `<div class="stat-sub mt">humeur dominante : ${emoChip(d.current_narrative.dominant_mood)}</div>` : ""}
      </div>` : ""}

    <div class="card">
      <h3>Circadien</h3>
      <div class="metric-row"><span class="k">Phase</span><span class="v">${d.circadian.phase}</span></div>
      <div class="metric-row"><span class="k">Heure interne</span><span class="v">${d.circadian.hour}h</span></div>
      <div class="metric-row"><span class="k">Énergie circadienne</span><span class="v">${pct(d.circadian.energy)}</span></div>
    </div>`;
});
