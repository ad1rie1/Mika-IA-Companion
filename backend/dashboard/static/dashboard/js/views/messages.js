Dash.render(async (root) => {
  const { api, escapeHTML, emoChip, clip, fmtRel } = Dash;
  const state = { person_id: "", conversation_id: "", role: "", limit: 80, offset: 0 };

  const qs = () => {
    const u = new URLSearchParams();
    if (state.person_id) u.set("person_id", state.person_id);
    if (state.conversation_id) u.set("conversation_id", state.conversation_id);
    if (state.role) u.set("role", state.role);
    u.set("limit", state.limit); u.set("offset", state.offset);
    return u.toString();
  };

  async function reload() {
    const d = await api("/dashboard/api/messages?" + qs());
    if (!d) return (root.innerHTML = `<div class="empty">Indisponible.</div>`);

    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Total : <b>${d.total}</b></span>
        <input id="f-person" placeholder="person_id" value="${escapeHTML(state.person_id)}" />
        <input id="f-conv"   placeholder="conversation_id" value="${escapeHTML(state.conversation_id)}" />
        <select id="f-role">
          <option value="">— tous rôles —</option>
          <option value="user" ${state.role==='user'?'selected':''}>user</option>
          <option value="assistant" ${state.role==='assistant'?'selected':''}>assistant</option>
        </select>
      </div>
      <div class="card">
        <h3>Messages<span class="tag">${d.total}</span></h3>
        <table>
          <thead><tr><th>Quand</th><th>Conv</th><th>Rôle</th><th>Person</th><th>Source</th><th>Contenu</th><th>Émotion</th></tr></thead>
          <tbody>${d.rows.map(m => `
            <tr>
              <td class="muted">${fmtRel(m.created_at)}</td>
              <td class="muted">
                <a class="chip link" href="/dashboard/messages/?conversation_id=${m.conversation_id}">#${m.conversation_id}</a>
              </td>
              <td><span class="pill ${m.role==='assistant'?'mag':''}">${m.role}</span></td>
              <td class="mono">
                <a class="chip link" href="/dashboard/messages/?person_id=${encodeURIComponent(m.person_id)}">${escapeHTML(m.person_id || "—")}</a>
              </td>
              <td class="muted">${escapeHTML(m.source)}</td>
              <td style="max-width:520px;">${escapeHTML(clip(m.content, 280))}</td>
              <td>${m.emotion ? emoChip(m.emotion, m.emotion_intensity) : `<span class="muted">—</span>`}</td>
            </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucun message.</td></tr>`}
          </tbody>
        </table>
      </div>`;

    root.appendChild(Dash.pager({
      total: d.total, limit: d.limit, offset: d.offset,
      onPrev: off => { state.offset = off; reload(); },
      onNext: off => { state.offset = off; reload(); },
    }));

    const p = Dash.$("#f-person"), c = Dash.$("#f-conv");
    p.onkeydown = e => { if (e.key === "Enter") { state.person_id = p.value; state.offset = 0; reload(); } };
    c.onkeydown = e => { if (e.key === "Enter") { state.conversation_id = c.value; state.offset = 0; reload(); } };
    Dash.$("#f-role").onchange = e => { state.role = e.target.value; state.offset = 0; reload(); };
  }

  // Preload from URL query on first paint — lets entity/theme links drill in
  const u = new URLSearchParams(window.location.search);
  if (u.get("person_id")) state.person_id = u.get("person_id");
  if (u.get("conversation_id")) state.conversation_id = u.get("conversation_id");
  reload();
});
