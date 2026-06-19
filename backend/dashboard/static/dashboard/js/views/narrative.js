Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, pct, fmtDate, clip, pager } = Dash;
  const head = await api("/dashboard/api/narrative?limit=1");
  if (!head || !head.rows.length)
    return (root.innerHTML = `<div class="empty">Pas encore de self-narrative.</div>`);

  const current = head.rows[0];
  const histTotal = Math.max(0, (head.total || 1) - 1);  // history = tout sauf la plus récente

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
      <h3>Historique<span class="tag">${histTotal}</span></h3>
      <div id="narr-hist"></div>
      <div class="pager-slot"></div>
    </div>`;

  const wrap = root.querySelector("#narr-hist");
  const slot = root.querySelector(".pager-slot");
  const limit = 10;
  let offset = 0;

  async function drawHist() {
    let rows = [];
    if (histTotal) {
      const d = await api(`/dashboard/api/narrative?limit=${limit}&offset=${1 + offset}`);
      rows = (d && d.rows) || [];
    }
    wrap.innerHTML = rows.length ? rows.map(n => `
      <div style="padding:12px 0;border-bottom:1px dashed rgba(255,255,255,0.06)">
        <div class="flex between center mb" style="font-size:11px;">
          <span class="muted">${fmtDate(n.created_at)}</span>
          <span>${emoChip(n.dominant_mood || "neutral")}</span>
        </div>
        <div class="narr">${escapeHTML(clip(n.content, 600))}</div>
      </div>`).join("") : `<div class="muted">Aucun historique.</div>`;

    slot.innerHTML = "";
    if (histTotal > limit) {
      slot.appendChild(pager({
        total: histTotal, limit, offset,
        onPrev: o => { offset = o; drawHist(); },
        onNext: o => { offset = o; drawHist(); },
      }));
    }
  }
  drawHist();
});
