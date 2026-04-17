Dash.render(async (root) => {
  const { api, escapeHTML, clip, pct, fmtDate, fmtRel } = Dash;
  const d = await api("/dashboard/api/projects");
  if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

  const stp = s => ({active:"pos",paused:"warn",completed:"",abandoned:"neg"}[s] || "");
  const pp  = s => ({urgent:"neg",high:"warn",normal:"",low:""}[s] || "");

  root.innerHTML = `
    ${d.pending_actions.length ? `
      <div class="card mb" style="border-color:rgba(255,200,87,0.4);">
        <h3 style="color:var(--amber)">⚠ Actions en attente d'approbation<span class="tag">${d.pending_actions.length}</span></h3>
        ${d.pending_actions.map(a => `
          <div class="metric-row">
            <span class="k">${escapeHTML(clip(a.proposal, 200))}</span>
            <span class="v muted">projet ${a.project_id} · ${fmtRel(a.created_at)}</span>
          </div>`).join("")}
      </div>` : ""}

    <div class="grid cols-2">
      ${d.projects.map(p => {
        const tasks = p.tasks || {};
        const total = Object.values(tasks).reduce((a, b) => a + b, 0);
        const done = tasks.done || 0;
        return `
          <div class="card">
            <h3>${escapeHTML(p.title)}<span class="tag">${p.emotion_policy}</span></h3>
            <div class="flex gap mb">
              <span class="pill ${stp(p.status)}">${p.status}</span>
              <span class="pill ${pp(p.priority)}">${p.priority}</span>
              <span class="pill">${p.origin}</span>
            </div>
            <div class="muted mb">${escapeHTML(clip(p.description, 260))}</div>
            <div class="mt">
              <div class="flex between"><span class="muted">Tâches ${done}/${total}</span><span>${total ? pct(done/total) : "—"}</span></div>
              <div class="bar"><div class="fill" style="width:${total ? (done/total)*100 : 0}%"></div></div>
            </div>
            <div class="metric-row mt"><span class="k">Owner</span><span class="v">${p.owner || '—'}</span></div>
            <div class="metric-row"><span class="k">Planification</span><span class="v mono">${escapeHTML(p.schedule_rule || "manuel")}</span></div>
            <div class="metric-row"><span class="k">Prochaine exécution</span><span class="v">${p.next_run_at ? fmtDate(p.next_run_at) : "—"}</span></div>
            <div class="metric-row"><span class="k">Dernière exécution</span><span class="v">${p.last_run_at ? fmtRel(p.last_run_at) : "—"}</span></div>
            <div class="metric-row"><span class="k">Auto-avancements sans user</span><span class="v">${p.runs_since_user_input}</span></div>
            <div class="metric-row"><span class="k">Détail tâches</span><span class="v">
              ${["todo","in_progress","done","blocked"].map(s => `<span class="chip">${s}: ${tasks[s]||0}</span>`).join(" ")}
            </span></div>
          </div>`;
      }).join("") || `<div class="empty">Aucun projet.</div>`}
    </div>`;
});
