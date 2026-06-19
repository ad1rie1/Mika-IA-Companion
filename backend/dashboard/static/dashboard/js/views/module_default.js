/* Generic renderer for module views that don't ship their own JS.
 *
 * Reads `window.ModuleView` (module, key, dataUrl, actions) and paints
 * whatever the data_handler returns. Three lightweight conventions:
 *   - { columns: [...], rows: [...], total?, page?, limit? }
 *       → renders a single table with server-side pagination
 *   - { tabs: [ {key, label, columns, rows} | {key, label, html}
 *               | {key, label, ...flatJson} ] }
 *       → renders a tab bar (Dash.tabs); table tabs paginate client-side
 *   - anything else
 *       → pretty-prints the JSON payload
 *
 * Actions are exposed as buttons above the content. Each button POSTs
 * to the declared endpoint, then re-renders on success.
 */
Dash.render(async (root) => {
  const { api, escapeHTML, pager, clientPager, tabs } = Dash;
  const view = window.ModuleView;
  if (!view) {
    root.innerHTML = `<div class="empty">Vue non configurée.</div>`;
    return;
  }

  let page = 0;
  const limit = 25;

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}",
    });
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      alert((data && data.error) || `HTTP ${r.status}`);
      return null;
    }
    return data;
  }

  async function runAction(action) {
    if (action.confirm && !confirm(action.confirm)) return;
    const res = await post(view.actionUrl(action.key));
    if (res) draw();
  }

  function actionsBar() {
    if (!view.actions || !view.actions.length) return "";
    return `<div class="mb">${view.actions.map((a, i) =>
      `<button class="btn" data-action-idx="${i}">${escapeHTML(a.label)}</button>`
    ).join(" ")}</div>`;
  }

  function renderTable(d) {
    const cols = d.columns || [];
    const rows = d.rows || [];
    const idField = view.idField || "id";
    const showDetail = !!view.hasDetail;

    const head =
      cols.map(c => `<th>${escapeHTML(c.label || c.key)}</th>`).join("") +
      (showDetail ? `<th></th>` : "");

    const body = rows.map((r, idx) => {
      const cells = cols.map(c => {
        const v = r[c.key];
        return `<td>${v == null ? '<span class="muted">—</span>' : escapeHTML(String(v))}</td>`;
      }).join("");
      const detailBtn = (showDetail && r[idField] != null)
        ? `<td><button class="btn" data-detail-id="${escapeHTML(String(r[idField]))}">Voir</button></td>`
        : (showDetail ? `<td></td>` : "");
      return `<tr>${cells}${detailBtn}</tr>`;
    }).join("");

    const colspan = cols.length + (showDetail ? 1 : 0) || 1;
    return `
      <div class="card">
        <h3>${escapeHTML(view.label)}</h3>
        ${actionsBar()}
        <table>
          <thead><tr>${head}</tr></thead>
          <tbody>${body || `<tr><td colspan="${colspan}" class="muted">Aucune donnée.</td></tr>`}</tbody>
        </table>
        <div class="pager-slot"></div>
      </div>`;
  }

  function renderDetail(d) {
    // Two supported shapes:
    //   { html: "<raw html>" }               → inserted as-is (module owns the layout)
    //   { title?, fields: [{key,label,value}] } or any flat dict → key/value grid
    if (d && typeof d.html === "string") return d.html;
    const fields = Array.isArray(d && d.fields)
      ? d.fields.map(f => [f.label || f.key, f.value])
      : Object.entries(d || {}).filter(([k]) => k !== "title");
    return `<dl class="kv">${fields.map(([k, v]) =>
      `<dt>${escapeHTML(String(k))}</dt>
       <dd>${v == null ? '<span class="muted">—</span>' : escapeHTML(typeof v === "object" ? JSON.stringify(v, null, 2) : String(v))}</dd>`
    ).join("")}</dl>`;
  }

  async function openDetail(id) {
    const modal = Dash.openModal({
      title: `${view.label} · #${id}`,
      body: `<div class="empty"><span class="loader"></span></div>`,
      footer: [{ label: "Fermer", ghost: true, onClick: m => m.close() }],
    });
    const d = await api(view.itemUrl(id));
    modal.body.innerHTML = d ? renderDetail(d) : `<div class="empty">Indisponible.</div>`;
  }

  function renderJson(d) {
    return `
      <div class="card">
        <h3>${escapeHTML(view.label)}</h3>
        ${actionsBar()}
        <pre class="mono" style="white-space:pre-wrap;">${escapeHTML(JSON.stringify(d, null, 2))}</pre>
      </div>`;
  }

  // A single tab's body: a paginated table (client-side, since the whole
  // dataset arrived in one payload), raw HTML, or pretty-printed JSON.
  function paintTab(t, body) {
    if (Array.isArray(t.columns) && Array.isArray(t.rows)) {
      const cols = t.columns;
      const idField = view.idField || "id";
      const showDetail = !!view.hasDetail;
      const head =
        cols.map(c => `<th>${escapeHTML(c.label || c.key)}</th>`).join("") +
        (showDetail ? `<th></th>` : "");
      const colspan = cols.length + (showDetail ? 1 : 0) || 1;
      body.innerHTML = `
        <div class="card">
          <h3>${escapeHTML(t.label || view.label)}</h3>
          <table>
            <thead><tr>${head}</tr></thead>
            <tbody class="mv-tab-body"></tbody>
          </table>
        </div>`;
      const card = body.querySelector(".card");
      const tbody = body.querySelector(".mv-tab-body");
      clientPager({
        rows: t.rows, limit, mount: card,
        render: page => {
          tbody.innerHTML = page.map(r => {
            const cells = cols.map(c => {
              const v = r[c.key];
              return `<td>${v == null ? '<span class="muted">—</span>' : escapeHTML(String(v))}</td>`;
            }).join("");
            const detailBtn = (showDetail && r[idField] != null)
              ? `<td><button class="btn" data-detail-id="${escapeHTML(String(r[idField]))}">Voir</button></td>`
              : (showDetail ? `<td></td>` : "");
            return `<tr>${cells}${detailBtn}</tr>`;
          }).join("") || `<tr><td colspan="${colspan}" class="muted">Aucune donnée.</td></tr>`;
          tbody.querySelectorAll("button[data-detail-id]").forEach(btn => {
            btn.onclick = () => openDetail(btn.dataset.detailId);
          });
        },
      });
    } else if (typeof t.html === "string") {
      body.innerHTML = `<div class="card"><h3>${escapeHTML(t.label || view.label)}</h3>${t.html}</div>`;
    } else {
      body.innerHTML = renderDetail(t);
    }
  }

  function renderTabs(d) {
    root.innerHTML = `${actionsBar()}<div id="mv-tabs"></div>`;
    root.querySelectorAll("button[data-action-idx]").forEach(btn => {
      btn.onclick = () => runAction(view.actions[parseInt(btn.dataset.actionIdx, 10)]);
    });
    tabs({
      mount: root.querySelector("#mv-tabs"),
      storeKey: `dash.mv.${view.module}.${view.key}`,
      tabs: d.tabs.map(t => ({
        key: t.key, label: t.label || t.key,
        render: body => paintTab(t, body),
      })),
    });
  }

  async function draw() {
    const url = `${view.dataUrl}?page=${page}&limit=${limit}`;
    const d = await api(url);
    if (!d) { root.innerHTML = `<div class="empty">Indisponible.</div>`; return; }

    if (Array.isArray(d.tabs)) {
      renderTabs(d);
      return;
    }

    if (Array.isArray(d.columns) && Array.isArray(d.rows)) {
      root.innerHTML = renderTable(d);
      if (d.total != null && d.total > limit) {
        const slot = root.querySelector(".pager-slot");
        slot.appendChild(pager({
          total: d.total, limit, offset: page * limit,
          onPrev: (off) => { page = Math.floor(off / limit); draw(); },
          onNext: (off) => { page = Math.floor(off / limit); draw(); },
        }));
      }
    } else {
      root.innerHTML = renderJson(d);
    }

    root.querySelectorAll("button[data-action-idx]").forEach(btn => {
      btn.onclick = () => runAction(view.actions[parseInt(btn.dataset.actionIdx, 10)]);
    });
    root.querySelectorAll("button[data-detail-id]").forEach(btn => {
      btn.onclick = () => openDetail(btn.dataset.detailId);
    });
  }

  draw();
});
