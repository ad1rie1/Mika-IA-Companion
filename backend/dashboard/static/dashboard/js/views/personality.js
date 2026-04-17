Dash.render(async (root) => {
  const { api, escapeHTML, emoChip } = Dash;
  const d = await api("/dashboard/api/personality");
  if (!d) return (root.innerHTML = `<div class="empty">Aucune donnée.</div>`);

  const t = d.temperament;
  const listCard = (title, arr) => `
    <div class="card">
      <h3>${title}</h3>
      ${arr && arr.length
        ? `<div class="chips">${arr.map(x => `<span class="chip">${escapeHTML(x)}</span>`).join("")}</div>`
        : `<div class="muted">—</div>`}
    </div>`;

  root.innerHTML = `
    <div class="grid cols-2 mb">
      <div class="card">
        <h3>Identité</h3>
        <div class="stat-value" style="font-size:22px">${escapeHTML(d.name)}</div>
        <div class="stat-sub">${escapeHTML(d.description || "")}</div>
        <div class="metric-row mt"><span class="k">Langue</span><span class="v">${d.language}</span></div>
        <div class="metric-row"><span class="k">Greeting</span><span class="v">${escapeHTML(d.greeting)}</span></div>
      </div>
      <div class="card">
        <h3>Tempérament</h3>
        <div class="metric-row"><span class="k">Humeur par défaut</span><span class="v">${emoChip(t.default_mood)}</span></div>
        <div class="metric-row"><span class="k">Volatilité</span><span class="v">${t.volatility.toFixed(2)}</span></div>
        <div class="bar mb"><div class="fill" style="width:${t.volatility*100}%"></div></div>
        <div class="metric-row"><span class="k">Intensité de base</span><span class="v">${t.intensity_base.toFixed(2)}</span></div>
        <div class="bar mb"><div class="fill" style="width:${t.intensity_base*100}%"></div></div>
        <div class="metric-row"><span class="k">Vitesse de récupération</span><span class="v">${t.recovery_speed.toFixed(2)}</span></div>
        <div class="bar mb"><div class="fill" style="width:${t.recovery_speed*100}%"></div></div>
        <div class="metric-row"><span class="k">Global bleed</span><span class="v">${t.global_bleed.toFixed(2)}</span></div>
        <div class="bar"><div class="fill" style="width:${t.global_bleed*100}%"></div></div>
      </div>
    </div>

    <div class="grid cols-3 mb">
      ${listCard("Traits", d.traits)}
      ${listCard("Quirks", d.quirks)}
      ${listCard("Valeurs", d.values)}
    </div>
    <div class="grid cols-3 mb">
      ${listCard("Intérêts", d.interests)}
      ${listCard("Vulnérabilités", d.vulnerabilities)}
      ${listCard("Speech patterns", d.speech_patterns)}
    </div>

    <div class="card">
      <h3>Tone</h3>
      <pre class="mono" style="margin:0;white-space:pre-wrap;color:var(--text-dim);">${escapeHTML(JSON.stringify(d.tone, null, 2))}</pre>
    </div>`;
});
