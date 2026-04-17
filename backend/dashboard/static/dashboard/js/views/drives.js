Dash.render(async (root) => {
  const { api, escapeHTML, pct, fmtRel } = Dash;
  const d = await api("/dashboard/api/drives");
  if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);
  const LABEL = {curiosity:"Curiosité",social:"Social",expression:"Expression",rest:"Repos"};

  root.innerHTML = `
    <div class="grid cols-3 mb">
      <div class="card">
        <h3>Énergie globale</h3>
        <div class="stat-value">${pct(d.energy)}</div>
        <div class="bar mt ok"><div class="fill" style="width:${d.energy*100}%"></div></div>
      </div>
      <div class="card">
        <h3>Drive dominant</h3>
        <div class="stat-value" style="color:var(--magenta)">${d.dominant || "—"}</div>
        <div class="stat-sub">contribution conscience : ${d.conscience_contribution}</div>
      </div>
      <div class="card">
        <h3>Détail conscience</h3>
        <div class="mono muted" style="word-break:break-all">${escapeHTML(d.conscience_label || "—")}</div>
      </div>
    </div>

    <div class="grid cols-2">
      ${d.drives.map(dr => `
        <div class="card">
          <h3>${LABEL[dr.kind] || dr.kind}<span class="tag">${dr.kind === "rest" ? "fatigue" : "motivation"}</span></h3>
          <div class="flex between center mb">
            <span class="stat-value" style="font-size:22px">${pct(dr.tension)}</span>
            <span class="muted">tension</span>
          </div>
          <div class="bar ${dr.kind==='rest'?'warn':''} mb"><div class="fill" style="width:${dr.tension*100}%"></div></div>
          <div class="metric-row"><span class="k">Seuil satisfaction</span><span class="v">${pct(dr.params.satisfy_threshold)}</span></div>
          <div class="metric-row"><span class="k">Poids conscience</span><span class="v">${dr.params.weight.toFixed(2)}</span></div>
          <div class="metric-row"><span class="k">Croissance</span><span class="v">${dr.params.growth_rate}/s</span></div>
          <div class="metric-row"><span class="k">Décroissance à satisf.</span><span class="v">${pct(dr.params.decay_on_satisfy)}</span></div>
          <div class="metric-row"><span class="k">Dernière satisfaction</span><span class="v">${fmtRel(new Date(dr.last_satisfied*1000).toISOString())} ago</span></div>
        </div>`).join("")}
    </div>`;
});
