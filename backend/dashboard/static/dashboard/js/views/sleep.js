Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtRel, pager, tabs } = Dash;
  const s = await api("/dashboard/api/sleep");
  if (!s) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);
  const typeColor = t => ({nightmare:"neg",pleasant:"pos",associative:"mag",mundane:""}[t] || "");

  root.innerHTML = `
    <div class="grid cols-3 mb">
      <div class="card">
        <h3>Phase actuelle</h3>
        <div class="stat-value" style="color:${s.phase==='awake'?'var(--cyan)':'var(--violet)'}">${s.phase}</div>
      </div>
      <div class="card">
        <h3>Journal du jour</h3>
        ${s.today_journal ? `
          <div class="narr">${escapeHTML(s.today_journal.narrative)}</div>
          <div class="mt muted" style="font-size:11px;">
            Humeur: ${emoChip(s.today_journal.dominant_emotion || "neutral")} ·
            ${s.today_journal.word_count} mots
          </div>` : `<div class="muted">Pas encore écrit.</div>`}
      </div>
      <div class="card">
        <h3>Dernier rêve</h3>
        ${s.last_dream ? `
          <div><span class="pill ${typeColor(s.last_dream.dream_type)}">${s.last_dream.dream_type}</span>
               <span class="muted">· vivacité ${pct(s.last_dream.vividness)}</span></div>
          <div class="narr mt">${escapeHTML(s.last_dream.content)}</div>
          <div class="stat-sub mt">Nuit du ${s.last_dream.night_of} · ${fmtRel(s.last_dream.created_at)}</div>
        ` : `<div class="muted">Pas de rêve récent.</div>`}
      </div>
    </div>

    <div id="sleep-tabs"></div>`;

  // ── Rêves : liste paginée serveur ──────────────────────────────
  function makeDreamsTab() {
    const st = { offset: 0, limit: 20 };
    return async (body) => {
      async function draw() {
        const d = await api(`/dashboard/api/sleep/dreams?limit=${st.limit}&offset=${st.offset}`);
        const rows = (d && d.rows) || [];
        const total = (d && d.total) || 0;
        body.innerHTML = `
          <div class="card">
            <h3>Rêves<span class="tag">${total}</span></h3>
            ${rows.map(dr => `
              <div style="padding:10px 0;border-bottom:1px dashed rgba(255,255,255,0.05)">
                <div class="flex between center mb" style="font-size:11px;">
                  <span><span class="pill ${typeColor(dr.dream_type)}">${dr.dream_type}</span>
                        <span class="muted" style="margin-left:6px">${dr.night_of}</span></span>
                  <span class="muted">vividness ${pct(dr.vividness)}</span>
                </div>
                <div class="narr">${escapeHTML(dr.content)}</div>
                ${dr.emotion ? `<div class="mt">${emoChip(dr.emotion)}</div>` : ""}
              </div>`).join("") || `<div class="muted">Aucun rêve enregistré.</div>`}
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

  // ── Journaux : liste paginée serveur ───────────────────────────
  function makeJournalsTab() {
    const st = { offset: 0, limit: 15 };
    return async (body) => {
      async function draw() {
        const d = await api(`/dashboard/api/sleep/journals?limit=${st.limit}&offset=${st.offset}`);
        const rows = (d && d.rows) || [];
        const total = (d && d.total) || 0;
        body.innerHTML = `
          <div class="card">
            <h3>Journaux quotidiens<span class="tag">${total}</span></h3>
            ${rows.map(j => `
              <div style="padding:10px 0;border-bottom:1px dashed rgba(255,255,255,0.05)">
                <div class="flex between center mb" style="font-size:11px;">
                  <span class="muted">${j.date}</span>
                  <span>${emoChip(j.dominant_emotion || "neutral")}</span>
                </div>
                <div class="narr">${escapeHTML(j.narrative)}</div>
                <div class="mt chips">${(j.persons_interacted || []).map(p => `<span class="chip mag">${escapeHTML(p)}</span>`).join("")}</div>
              </div>`).join("") || `<div class="muted">Aucun journal.</div>`}
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
    mount: root.querySelector("#sleep-tabs"),
    storeKey: "dash.sleep.tab",
    tabs: [
      { key: "dreams",   label: "Rêves",    render: makeDreamsTab() },
      { key: "journals", label: "Journaux", render: makeJournalsTab() },
    ],
  });
});
