/* Email inbox — master/detail renderer shipped by the email module.
 *
 * This is the canonical example of Option B: a module ships its own
 * template + JS to render its data with domain-appropriate UI. The
 * generic `module_default.js` would also work (detail_handler is
 * declared, so "Voir" + modal would work out of the box) — this file
 * opts into a nicer layout: list on the left, full email on the right.
 */
Dash.render(async (root) => {
  const { api, escapeHTML, fmtDate } = Dash;
  const view = window.ModuleView;
  if (!view) { root.innerHTML = `<div class="empty">Vue non configurée.</div>`; return; }

  let page = 0;
  const limit = 25;
  let selectedId = null;
  let lastList = null;

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
    });
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) { alert((data && data.error) || `HTTP ${r.status}`); return null; }
    return data;
  }

  const priorityPill = p => {
    const cls = { urgent: "danger", high: "warn", medium: "", low: "muted" }[p] || "";
    return `<span class="pill ${cls}">${escapeHTML(p || "—")}</span>`;
  };

  function renderShell() {
    const actions = (view.actions || []).map((a, i) =>
      `<button class="btn" data-action-idx="${i}">${escapeHTML(a.label)}</button>`
    ).join(" ");
    root.innerHTML = `
      <div class="card">
        <h3>${escapeHTML(view.label)}</h3>
        <div class="mb">${actions}</div>
        <div class="mail-split">
          <div class="mail-list"></div>
          <div class="mail-detail">
            <div class="empty">Sélectionne un mail à gauche.</div>
          </div>
        </div>
      </div>`;

    root.querySelectorAll("button[data-action-idx]").forEach(btn => {
      btn.onclick = async () => {
        const a = view.actions[parseInt(btn.dataset.actionIdx, 10)];
        if (a.confirm && !confirm(a.confirm)) return;
        const res = await post(view.actionUrl(a.key));
        if (res) drawList();
      };
    });
  }

  async function drawList() {
    const url = `${view.dataUrl}?page=${page}&limit=${limit}`;
    const d = await api(url);
    lastList = d;
    const box = root.querySelector(".mail-list");
    if (!d) { box.innerHTML = `<div class="empty">Indisponible.</div>`; return; }

    const rows = (d.rows || []).map(r => {
      const unread = r.is_read === "non" || r.is_read === false;
      return `
        <div class="mail-row ${selectedId == r.id ? "active" : ""} ${unread ? "unread" : ""}"
             data-id="${escapeHTML(String(r.id))}">
          <div class="mail-row-top">
            <b>${escapeHTML(r.from_address || "—")}</b>
            <span class="muted">${escapeHTML(r.email_date || "")}</span>
          </div>
          <div class="mail-row-subject">${escapeHTML(r.subject || "(sans sujet)")}</div>
          <div class="mail-row-meta">
            ${priorityPill(r.priority)}
            <span class="muted">${escapeHTML(r.account || "")}</span>
          </div>
        </div>`;
    }).join("");

    const total = d.total || 0;
    const pages = Math.max(1, Math.ceil(total / limit));
    box.innerHTML = `
      ${rows || `<div class="empty">Aucun mail.</div>`}
      <div class="pager">
        <button class="btn" data-prev ${page <= 0 ? "disabled" : ""}>←</button>
        <span class="pager-info">${page + 1} / ${pages} · ${total}</span>
        <button class="btn" data-next ${(page + 1) * limit >= total ? "disabled" : ""}>→</button>
      </div>`;

    box.querySelectorAll(".mail-row").forEach(row => {
      row.onclick = () => { selectedId = row.dataset.id; drawList(); drawDetail(); };
    });
    const prev = box.querySelector("[data-prev]");
    const next = box.querySelector("[data-next]");
    if (prev) prev.onclick = () => { page = Math.max(0, page - 1); drawList(); };
    if (next) next.onclick = () => { page = page + 1; drawList(); };
  }

  async function drawDetail() {
    const pane = root.querySelector(".mail-detail");
    if (!selectedId) {
      pane.innerHTML = `<div class="empty">Sélectionne un mail à gauche.</div>`;
      return;
    }
    pane.innerHTML = `<div class="empty"><span class="loader"></span></div>`;
    const d = await api(view.itemUrl(selectedId));
    if (!d) { pane.innerHTML = `<div class="empty">Indisponible.</div>`; return; }

    // Prefer the plain-text body; fall back to stripped HTML if missing.
    // We don't inject body_html directly (XSS risk without a sanitizer).
    const body = d.body_text || (d.body_html ? d.body_html.replace(/<[^>]+>/g, "") : "");
    pane.innerHTML = `
      <div class="mail-head">
        <div class="mail-subject">${escapeHTML(d.subject || "(sans sujet)")}</div>
        <div class="mail-meta">
          <div><span class="muted">De</span> <b>${escapeHTML(d.from || "")}</b></div>
          <div><span class="muted">À</span> ${escapeHTML(d.to || "")}</div>
          ${d.cc ? `<div><span class="muted">Cc</span> ${escapeHTML(d.cc)}</div>` : ""}
          <div><span class="muted">Date</span> ${escapeHTML(d.date || "")}</div>
          <div><span class="muted">Compte</span> ${escapeHTML(d.account || "")} · ${priorityPill(d.priority)}
            ${d.has_attachments ? `<span class="chip">📎 pièces jointes</span>` : ""}</div>
        </div>
      </div>
      <pre class="mail-body">${escapeHTML(body)}</pre>`;
  }

  renderShell();
  drawList();
});
