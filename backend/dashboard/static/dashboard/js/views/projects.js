/* Projets — liste paginée (table).
 *
 * Clic sur « Voir → » ouvre la page détail pleine (pas de modale) :
 *   /dashboard/projects/<id>/
 * Création via /dashboard/projects/new/ , édition via /dashboard/projects/<id>/edit/ .
 *
 * API projets utilisée ici (csrf_exempt) :
 *   GET  /api/projects/            (?status=)
 *   GET  /api/projects/pending/
 *   POST /api/projects/pending/<id>/approve|reject
 */
Dash.render(async (root) => {
  const { escapeHTML, clip, fmtDate, fmtRel } = Dash;

  const STATUS = ["active", "paused", "completed", "abandoned"];
  let statusFilter = "";        // "" = tous

  async function sendJSON(url, method, body) {
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  const stp = s => ({ active: "pos", paused: "warn", completed: "", abandoned: "neg" }[s] || "");
  const pp  = s => ({ urgent: "neg", high: "warn", normal: "", low: "" }[s] || "");

  async function renderList() {
    const url = statusFilter ? `/api/projects/?status=${statusFilter}` : "/api/projects/";
    const [listRes, pendingRes] = await Promise.all([
      fetch(url).then(r => r.json()),
      fetch("/api/projects/pending/").then(r => r.json()),
    ]);
    const projects = listRes.projects || [];
    const pending = pendingRes.pending || [];

    const filterOpts = [["", "tous"], ...STATUS.map(s => [s, s])]
      .map(([v, l]) => `<option value="${v}" ${statusFilter === v ? "selected" : ""}>${l}</option>`)
      .join("");

    root.innerHTML = `
      <div class="toolbar">
        <button class="btn primary" id="btn-new">+ Nouveau projet</button>
        <label class="muted" style="display:flex;align-items:center;gap:6px">Statut
          <select id="f-status" style="background:rgba(10,16,32,0.6);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:12px">${filterOpts}</select>
        </label>
        <span class="muted">${projects.length} projet${projects.length > 1 ? "s" : ""}</span>
      </div>

      ${pending.length ? `
        <div class="card mb" id="p-pending" style="border-color:rgba(255,200,87,0.4);">
          <h3 style="color:var(--amber)">⚠ Actions en attente d'approbation<span class="tag">${pending.length}</span></h3>
          <div id="p-pending-list"></div>
        </div>` : ""}

      <div id="p-list-wrap">
        <div class="card">
          <table>
            <thead><tr>
              <th>Titre</th><th>Statut</th><th>Priorité</th><th>Origine</th>
              <th>Politique</th><th>Planification</th><th>Prochaine exéc.</th><th></th>
            </tr></thead>
            <tbody id="p-tbody"></tbody>
          </table>
        </div>
      </div>`;

    Dash.$("#btn-new").onclick = () => { location.href = "/dashboard/projects/new/"; };
    Dash.$("#f-status").onchange = e => { statusFilter = e.target.value; renderList(); };

    // Actions en attente — pagination client + approuver/rejeter en place
    if (pending.length) {
      const pendCard = Dash.$("#p-pending");
      const pendList = Dash.$("#p-pending-list");
      Dash.clientPager({
        rows: pending, limit: 10, mount: pendCard,
        render: page => {
          pendList.innerHTML = page.map(a => `
            <div class="metric-row" data-pending-id="${a.id}" style="align-items:flex-start;gap:10px">
              <span class="k">${escapeHTML(clip(a.proposal, 200))}
                <small class="muted">projet <b>${escapeHTML(a.project_title)}</b> · ${fmtRel(a.created_at)}</small>
              </span>
              <span class="v" style="white-space:nowrap">
                <button class="btn ghost p-approve" type="button" style="color:var(--green)">✓ Approuver</button>
                <button class="btn ghost p-reject" type="button" style="color:var(--red)">✕ Rejeter</button>
              </span>
            </div>`).join("");
          wirePendingRows(pendList);
        },
      });
    }

    // Projets — table paginée client
    const listWrap = Dash.$("#p-list-wrap");
    const tbody = Dash.$("#p-tbody");
    if (projects.length) {
      Dash.clientPager({
        rows: projects, limit: 25, mount: listWrap,
        render: page => {
          tbody.innerHTML = page.map(p => `
            <tr>
              <td>${escapeHTML(p.title)}</td>
              <td><span class="pill ${stp(p.status)}">${p.status}</span></td>
              <td><span class="pill ${pp(p.priority)}">${p.priority}</span></td>
              <td>${escapeHTML(p.origin)}</td>
              <td><span class="tag">${escapeHTML(p.emotion_policy)}</span></td>
              <td class="mono">${escapeHTML(p.schedule_rule || "manuel")}</td>
              <td class="muted">${p.next_run_at ? fmtDate(p.next_run_at) : "—"}</td>
              <td><a class="btn" href="/dashboard/projects/${p.id}/">Voir →</a></td>
            </tr>`).join("");
        },
      });
    } else {
      tbody.innerHTML = `<tr><td colspan="8" class="muted">Aucun projet${statusFilter ? ` (statut: ${statusFilter})` : ""} — clique <b>+ Nouveau projet</b> pour démarrer.</td></tr>`;
    }
  }

  // Approuver / rejeter une action en attente directement depuis la liste.
  function wirePendingRows(container) {
    container.querySelectorAll("[data-pending-id]").forEach(row => {
      const id = parseInt(row.dataset.pendingId, 10);
      const resolve = async (decision) => {
        let note = "";
        if (decision === "reject") {
          note = prompt("Note (optionnelle) pour le rejet :") || "";
        }
        try {
          await sendJSON(`/api/projects/pending/${id}/${decision}`, "POST", { note });
          renderList();
        } catch (e) { alert("Erreur: " + e); }
      };
      row.querySelector(".p-approve").onclick = () => resolve("approve");
      row.querySelector(".p-reject").onclick  = () => resolve("reject");
    });
  }

  renderList();
});
