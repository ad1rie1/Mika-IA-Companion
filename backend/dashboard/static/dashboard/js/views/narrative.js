Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtDate, clip } = Dash;
  const d = await api("/dashboard/api/narrative?limit=20");
  if (!d || !d.rows.length)
    return (root.innerHTML = `<div class="empty">Pas encore de self-narrative.</div>`);

  const [current, ...history] = d.rows;
  root.innerHTML = `
    <div class="card mb">
      <h3>Narrative actuelle<span class="tag">${fmtDate(current.created_at)}</span></h3>
      <div class="big-narrative narr">${escapeHTML(current.content)}</div>
      <div class="mt flex gap-lg">
        <div><span class="muted">Humeur dominante :</span> ${emoChip(current.dominant_mood || "neutral")}</div>
        <div><span class="muted">Confiance :</span> <b>${pct(current.confidence)}</b></div>
        <div><span class="muted">Sources :</span> ${current.source_souvenir_count}S / ${current.source_connaissance_count}K</div>
      </div>
      <div class="mt">
        <div class="muted" style="font-size:11px;margin-bottom:4px;">Thèmes clés</div>
        <div class="chips">${(current.key_themes || []).map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("")}</div>
      </div>
      <div class="mt">
        <div class="muted" style="font-size:11px;margin-bottom:4px;">Personnes clés</div>
        <div class="chips">${(current.key_people || []).map(p => `<span class="chip mag">${escapeHTML(p)}</span>`).join("")}</div>
      </div>
    </div>

    <div class="card">
      <h3>Historique</h3>
      ${history.length ? history.map(n => `
        <div style="padding:12px 0;border-bottom:1px dashed rgba(255,255,255,0.06)">
          <div class="flex between center mb" style="font-size:11px;">
            <span class="muted">${fmtDate(n.created_at)}</span>
            <span>${emoChip(n.dominant_mood || "neutral")}</span>
          </div>
          <div class="narr">${escapeHTML(clip(n.content, 600))}</div>
        </div>`).join("") : `<div class="muted">Aucun historique.</div>`}
    </div>`;
});
