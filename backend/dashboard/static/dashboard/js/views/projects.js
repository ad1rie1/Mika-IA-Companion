/* Projets — liste + création + édition + tâches.
 *
 * Utilise l'API projets existante (csrf_exempt) :
 *   GET    /api/projects/
 *   POST   /api/projects/create
 *   GET    /api/projects/<id>
 *   PATCH  /api/projects/<id>
 *   DELETE /api/projects/<id>
 *   POST   /api/projects/<id>/tasks
 *   PATCH  /api/projects/<id>/tasks/<tid>
 *   DELETE /api/projects/<id>/tasks/<tid>
 */
Dash.render(async (root) => {
  const { api, escapeHTML, clip, pct, fmtDate, fmtRel, openModal, confirm } = Dash;

  const STATUS      = ["active", "paused", "completed", "abandoned"];
  const PRIORITY    = ["low", "normal", "high", "urgent"];
  const ORIGIN      = ["user", "self"];
  const POLICY      = ["off", "muted", "full"];
  const TASK_STATUS = ["todo", "in_progress", "done", "blocked"];

  // Owners (person entities) loaded once, reused by every editor.
  let OWNERS = null;            // [{id, name}]
  let statusFilter = "";        // "" = all

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

  async function loadOwners() {
    if (OWNERS) return OWNERS;
    try {
      const d = await fetch("/dashboard/api/persons").then(r => r.json());
      OWNERS = (d.profiles || [])
        .filter(p => p.entity_id)
        .map(p => ({ id: p.entity_id, name: p.name }));
    } catch { OWNERS = []; }
    return OWNERS;
  }

  // tokens 12345 → "12.3k"
  function fmtTokens(n) {
    n = n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }

  // Budget consumption line. Returns "" when no budget set and no usage.
  function budgetLine(q) {
    if (!q) return "";
    const used = q.tokens_month || 0;
    const limit = q.limit_monthly || 0;
    const cost = q.cost_usd_month || 0;
    if (!limit && !used) return "";
    const costStr = cost ? ` · $${cost.toFixed(4)}` : "";
    if (!limit) {
      return `<div class="metric-row"><span class="k">Budget (${escapeHTML(q.month || "")})</span>
        <span class="v">${fmtTokens(used)} tok · illimité${costStr}</span></div>`;
    }
    const ratio = Math.min(1, used / limit);
    const over = used >= limit;
    const col = over ? "var(--red)" : ratio > 0.8 ? "var(--amber)" : "var(--cyan)";
    return `
      <div class="metric-row"><span class="k">Budget (${escapeHTML(q.month || "")})</span>
        <span class="v" style="color:${col}">${fmtTokens(used)} / ${fmtTokens(limit)} tok${costStr}</span></div>
      <div style="height:5px;border-radius:3px;background:rgba(255,255,255,0.08);overflow:hidden;margin:2px 0 4px">
        <div style="height:100%;width:${(ratio * 100).toFixed(1)}%;background:${col}"></div>
      </div>`;
  }

  // Safety-cap line: warn when auto-advance is frozen (no user feedback).
  function capLine(p) {
    const n = p.runs_since_user_input || 0;
    const cap = p.max_runs_without_input || 10;
    if (!n) return "";
    const frozen = n >= cap;
    const col = frozen ? "var(--red)" : n >= cap - 2 ? "var(--amber)" : "";
    const sfx = frozen ? " — gelé, en attente de toi" : "";
    return `<div class="metric-row"><span class="k">Ticks sans retour</span>
      <span class="v" ${col ? `style="color:${col}"` : ""}>${n}/${cap}${sfx}</span></div>`;
  }

  // ── List ──────────────────────────────────────────────────────
  async function renderList() {
    const url = statusFilter ? `/api/projects/?status=${statusFilter}` : "/api/projects/";
    const [listRes, pendingRes] = await Promise.all([
      fetch(url).then(r => r.json()),
      fetch("/api/projects/pending/").then(r => r.json()),
      loadOwners(),
    ]);
    const projects = listRes.projects || [];
    const pending = pendingRes.pending || [];

    const stp = s => ({active:"pos",paused:"warn",completed:"",abandoned:"neg"}[s] || "");
    const pp  = s => ({urgent:"neg",high:"warn",normal:"",low:""}[s] || "");

    const projectCard = p => `
      <div class="card clickable" data-id="${p.id}">
        <h3>${escapeHTML(p.title)}<span class="tag">${escapeHTML(p.emotion_policy)}</span></h3>
        <div class="flex gap mb">
          <span class="pill ${stp(p.status)}">${p.status}</span>
          <span class="pill ${pp(p.priority)}">${p.priority}</span>
          <span class="pill">${p.origin}</span>
        </div>
        <div class="muted mb">${escapeHTML(clip(p.description, 220))}</div>
        <div class="metric-row mt"><span class="k">Owner</span><span class="v">${escapeHTML(p.owner || "—")}</span></div>
        <div class="metric-row"><span class="k">Planification</span><span class="v mono">${escapeHTML(p.schedule_rule || "manuel")}</span></div>
        <div class="metric-row"><span class="k">Prochaine exécution</span><span class="v">${p.next_run_at ? fmtDate(p.next_run_at) : "—"}</span></div>
        <div class="metric-row"><span class="k">Dernière exécution</span><span class="v">${p.last_run_at ? fmtRel(p.last_run_at) : "—"}</span></div>
        <div class="metric-row"><span class="k">Approbation requise</span><span class="v">${p.requires_approval ? "oui" : "non"}</span></div>
        ${capLine(p)}
        ${budgetLine(p.quota)}
        <div class="chips mt">
          ${(p.keywords || []).slice(0, 6).map(k => `<span class="chip">${escapeHTML(k)}</span>`).join("")}
        </div>
      </div>`;

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
        <div class="grid cols-2" id="p-list"></div>
      </div>`;

    Dash.$("#btn-new").onclick = () => openEditor(null);
    Dash.$("#f-status").onchange = e => { statusFilter = e.target.value; renderList(); };

    // Pending actions — pagination côté client + approuver/rejeter
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

    // Projets (grille) — pagination côté client
    const listWrap = Dash.$("#p-list-wrap");
    const list = Dash.$("#p-list");
    if (projects.length) {
      Dash.clientPager({
        rows: projects, limit: 12, mount: listWrap,
        render: page => {
          list.innerHTML = page.map(projectCard).join("");
          list.querySelectorAll(".card.clickable").forEach(card => {
            card.onclick = () => openEditor(parseInt(card.dataset.id, 10));
          });
        },
      });
    } else {
      list.innerHTML = `<div class="empty">Aucun projet${statusFilter ? ` (statut: ${statusFilter})` : ""} — clique <b>+ Nouveau projet</b> pour démarrer.</div>`;
    }
  }

  // Approve / reject pending actions directly from the list.
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

  // ── Editor (create + edit) ────────────────────────────────────
  async function openEditor(id) {
    let project = null;
    let tasks = [];
    let recentLogs = [];
    if (id) {
      try {
        const d = await fetch(`/api/projects/${id}`).then(r => r.json());
        project = d;
        tasks = d.tasks || [];
        recentLogs = d.recent_logs || [];
      } catch (e) {
        alert("Impossible de charger le projet: " + e);
        return;
      }
    }

    const isNew = !project;
    const p = project || {
      title: "", description: "", keywords: [],
      origin: "user", status: "active", priority: "normal",
      tone_directive: "", emotion_policy: "off",
      instructions: [], out_of_scope: [],
      requires_approval: false, owner_id: null,
      allowed_modules: [], resource_paths: [], contacts: [],
      schedule_rule: "", monthly_token_budget: 0,
    };

    const owners = await loadOwners();
    const ownerOpts = [`<option value="">— aucun —</option>`]
      .concat(owners.map(o =>
        `<option value="${o.id}" ${p.owner_id === o.id ? "selected" : ""}>${escapeHTML(o.name)}</option>`))
      .join("");

    const listTextarea = arr => (arr || []).join("\n");
    const csvInput = arr => (arr || []).join(", ");

    const body = `
      <form id="p-form">
        <div class="form-grid">
          <div class="form-field full">
            <label>Titre *</label>
            <input type="text" name="title" value="${escapeHTML(p.title)}" required maxlength="150" />
          </div>
          <div class="form-field full">
            <label>Description</label>
            <textarea name="description">${escapeHTML(p.description || "")}</textarea>
          </div>

          <div class="form-field">
            <label>Statut</label>
            <select name="status">${STATUS.map(s => `<option value="${s}" ${p.status===s?"selected":""}>${s}</option>`).join("")}</select>
          </div>
          <div class="form-field">
            <label>Priorité</label>
            <select name="priority">${PRIORITY.map(s => `<option value="${s}" ${p.priority===s?"selected":""}>${s}</option>`).join("")}</select>
          </div>

          <div class="form-field">
            <label>Origine</label>
            <select name="origin">${ORIGIN.map(s => `<option value="${s}" ${p.origin===s?"selected":""}>${s}</option>`).join("")}</select>
          </div>
          <div class="form-field">
            <label>Politique émotionnelle</label>
            <select name="emotion_policy">${POLICY.map(s => `<option value="${s}" ${p.emotion_policy===s?"selected":""}>${s}</option>`).join("")}</select>
            <div class="hint">Défaut <b>off</b> (mode pro). <b>muted</b>/<b>full</b> pour projets sociaux.</div>
          </div>

          <div class="form-field">
            <label>Owner (personne)</label>
            <select name="owner_id">${ownerOpts}</select>
            <div class="hint">Qui a confié ce projet. Vide pour auto-initié.</div>
          </div>

          <div class="form-field full">
            <label>Directive de ton</label>
            <textarea name="tone_directive" placeholder="Ex: Langage soutenu, factuel, pas d'abréviations.">${escapeHTML(p.tone_directive || "")}</textarea>
          </div>

          <div class="form-field full">
            <label>Instructions (une par ligne)</label>
            <textarea name="instructions">${escapeHTML(listTextarea(p.instructions))}</textarea>
          </div>
          <div class="form-field full">
            <label>Hors-scope (une par ligne)</label>
            <textarea name="out_of_scope">${escapeHTML(listTextarea(p.out_of_scope))}</textarea>
          </div>

          <div class="form-field full">
            <label>Mots-clés (séparés par virgule)</label>
            <input type="text" name="keywords" value="${escapeHTML(csvInput(p.keywords))}" />
            <div class="hint">Utilisés pour détecter le projet dans une conversation.</div>
          </div>

          <div class="form-field">
            <label>Modules autorisés (csv)</label>
            <input type="text" name="allowed_modules" value="${escapeHTML(csvInput(p.allowed_modules))}" placeholder="email, files" />
          </div>
          <div class="form-field">
            <label>Contacts (csv)</label>
            <input type="text" name="contacts" value="${escapeHTML(csvInput(p.contacts))}" placeholder="alice@exemple.com" />
          </div>

          <div class="form-field full">
            <label>Chemins de ressources (un par ligne)</label>
            <textarea name="resource_paths">${escapeHTML(listTextarea(p.resource_paths))}</textarea>
          </div>

          <div class="form-field">
            <label>Planification</label>
            <input type="text" name="schedule_rule" value="${escapeHTML(p.schedule_rule || "")}" placeholder="interval:5m / cron:0 9 * * MON / idle:30m" />
            <div class="hint">Vide = manuel.</div>
          </div>
          <div class="form-field">
            <label>Budget mensuel (tokens)</label>
            <input type="number" name="monthly_token_budget" value="${p.monthly_token_budget || 0}" min="0" />
            <div class="hint">0 = illimité.</div>
          </div>

          <div class="form-field checkbox full">
            <input type="checkbox" id="f-approval" name="requires_approval" ${p.requires_approval ? "checked" : ""} />
            <label for="f-approval">Requiert approbation utilisateur pour les actions à effet de bord</label>
          </div>
        </div>

        ${!isNew ? `
          <hr style="border:none;border-top:1px solid var(--border);margin:22px 0" />

          <div class="metric-row"><span class="k">Ticks sans retour utilisateur</span>
            <span class="v">${(p.runs_since_user_input || 0)}/${(p.max_runs_without_input || 10)}${(p.runs_since_user_input || 0) >= (p.max_runs_without_input || 10) ? " — gelé" : ""}</span></div>
          <div class="metric-row"><span class="k">Prochaine exécution</span><span class="v">${p.next_run_at ? fmtDate(p.next_run_at) : "manuel"}</span></div>
          ${budgetLine(p.quota) || `<div class="metric-row"><span class="k">Budget</span><span class="v muted">aucune consommation ce mois</span></div>`}

          <h3 style="color:var(--cyan);letter-spacing:0.18em;text-transform:uppercase;font-size:11px;margin:22px 0 10px">Tâches <span class="tag">${tasks.length}</span></h3>
          <div id="p-tasks">${renderTasks(tasks)}</div>
          <div class="toolbar mt">
            <input type="text" id="new-task-desc" placeholder="Nouvelle tâche…" style="flex:1" />
            <button type="button" class="btn" id="btn-add-task">+ Ajouter</button>
          </div>

          ${recentLogs.length ? `
            <h3 style="color:var(--cyan);letter-spacing:0.18em;text-transform:uppercase;font-size:11px;margin:22px 0 10px">Historique runner <span class="tag">${recentLogs.length}</span></h3>
            <div class="scroll-box" style="max-height:200px">
              ${recentLogs.map(l => `
                <div class="metric-row">
                  <span class="k"><span class="pill">${escapeHTML(l.action)}</span> ${escapeHTML(clip(l.summary, 180))}</span>
                  <span class="v muted">${fmtRel(l.created_at)}</span>
                </div>`).join("")}
            </div>` : ""}

          <div class="toolbar mt">
            <h3 style="color:var(--cyan);letter-spacing:0.18em;text-transform:uppercase;font-size:11px;margin:0;flex:1">Prompts LLM (audit)</h3>
            <button type="button" class="btn ghost" id="btn-history">Charger l'historique</button>
          </div>
          <div id="p-history"></div>
        ` : ""}
      </form>
    `;

    const footer = [
      { label: "Annuler", ghost: true, onClick: m => m.close() },
    ];
    if (!isNew) {
      footer.push({
        label: "Supprimer", danger: true,
        onClick: async m => {
          if (!(await confirm(`Supprimer le projet "${p.title}" ? Cette action est irréversible.`, { danger: true }))) return;
          try {
            await sendJSON(`/api/projects/${id}`, "DELETE");
            m.close();
            renderList();
          } catch (e) { alert("Erreur: " + e); }
        },
      });
      if (p.status === "active") {
        footer.push({
          label: "▶ Faire avancer", ghost: true,
          onClick: async (m, btn) => {
            if (btn) { btn.disabled = true; btn.textContent = "…en cours"; }
            try {
              const res = await sendJSON(`/api/projects/${id}/advance`, "POST");
              m.close();
              await openEditor(id);  // reopen on fresh data (tasks/logs/budget)
              renderList();
            } catch (e) {
              alert("Erreur: " + e);
              if (btn) { btn.disabled = false; btn.textContent = "▶ Faire avancer"; }
            }
          },
        });
      }
    }
    footer.push({
      label: isNew ? "Créer" : "Enregistrer", primary: true,
      onClick: async m => {
        const form = m.body.querySelector("#p-form");
        const payload = collectPayload(form);
        if (!payload.title) { alert("Le titre est obligatoire."); return; }
        try {
          if (isNew) {
            await sendJSON("/api/projects/create", "POST", payload);
          } else {
            await sendJSON(`/api/projects/${id}`, "PATCH", payload);
          }
          m.close();
          renderList();
        } catch (e) { alert("Erreur: " + e); }
      },
    });

    const m = openModal({
      title: isNew ? "Nouveau projet" : `Éditer — ${p.title}`,
      body, footer,
    });

    if (!isNew) {
      m.body.querySelector("#btn-add-task").onclick = async () => {
        const inp = m.body.querySelector("#new-task-desc");
        const desc = inp.value.trim();
        if (!desc) return;
        try {
          await sendJSON(`/api/projects/${id}/tasks`, "POST", { description: desc });
          inp.value = "";
          // Reload project to refresh tasks in-place
          const fresh = await fetch(`/api/projects/${id}`).then(r => r.json());
          m.body.querySelector("#p-tasks").innerHTML = renderTasks(fresh.tasks || []);
          wireTaskRows(m.body, id);
        } catch (e) { alert("Erreur: " + e); }
      };
      wireTaskRows(m.body, id);

      const histBtn = m.body.querySelector("#btn-history");
      if (histBtn) {
        histBtn.onclick = async () => {
          histBtn.disabled = true;
          histBtn.textContent = "…";
          try {
            const d = await fetch(`/api/projects/${id}/history?limit=20`).then(r => r.json());
            m.body.querySelector("#p-history").innerHTML = renderHistory(d.history || []);
            wireHistoryRows(m.body, id);
            histBtn.textContent = "Rafraîchir";
          } catch (e) {
            alert("Erreur: " + e);
            histBtn.textContent = "Charger l'historique";
          } finally {
            histBtn.disabled = false;
          }
        };
      }
    }
  }

  // ── Prompt history (audit) ────────────────────────────────────
  function renderHistory(rows) {
    if (!rows.length) return `<div class="muted">Aucun prompt enregistré.</div>`;
    const oc = o => ({ok:"pos","":"",timeout:"neg",json_miss:"warn",quota_exceeded:"neg",error:"neg"}[o] || "");
    return `
      <div class="scroll-box" style="max-height:280px">
        ${rows.map(h => `
          <div class="metric-row" data-hist-id="${h.id}" style="cursor:pointer">
            <span class="k">
              <span class="pill ${oc(h.outcome)}">${escapeHTML(h.outcome || "?")}</span>
              ${escapeHTML(clip(h.raw_response_excerpt || "(vide)", 150))}
            </span>
            <span class="v muted">${h.duration_ms != null ? h.duration_ms + "ms · " : ""}${fmtRel(h.created_at)}</span>
          </div>`).join("")}
      </div>`;
  }

  function wireHistoryRows(rootEl, projectId) {
    rootEl.querySelectorAll("[data-hist-id]").forEach(row => {
      row.onclick = async () => {
        const hid = parseInt(row.dataset.histId, 10);
        try {
          const d = await fetch(`/api/projects/${projectId}/history?limit=100&full=1`).then(r => r.json());
          const h = (d.history || []).find(x => x.id === hid);
          if (!h) return;
          openModal({
            title: `Prompt #${h.id} — ${h.outcome}`,
            body: `
              <div class="metric-row"><span class="k">Outcome</span><span class="v">${escapeHTML(h.outcome || "?")}</span></div>
              <div class="metric-row"><span class="k">Durée</span><span class="v">${h.duration_ms != null ? h.duration_ms + " ms" : "—"}</span></div>
              <h3 style="color:var(--cyan);font-size:11px;text-transform:uppercase;letter-spacing:0.18em;margin:16px 0 6px">System prompt</h3>
              <pre style="white-space:pre-wrap;max-height:220px;overflow:auto;background:rgba(10,16,32,0.6);border:1px solid var(--border);padding:10px;border-radius:6px;font-size:11px">${escapeHTML(h.system_prompt || "")}</pre>
              <h3 style="color:var(--cyan);font-size:11px;text-transform:uppercase;letter-spacing:0.18em;margin:16px 0 6px">User prompt</h3>
              <pre style="white-space:pre-wrap;max-height:120px;overflow:auto;background:rgba(10,16,32,0.6);border:1px solid var(--border);padding:10px;border-radius:6px;font-size:11px">${escapeHTML(h.user_prompt || "")}</pre>
              <h3 style="color:var(--cyan);font-size:11px;text-transform:uppercase;letter-spacing:0.18em;margin:16px 0 6px">Réponse brute</h3>
              <pre style="white-space:pre-wrap;max-height:220px;overflow:auto;background:rgba(10,16,32,0.6);border:1px solid var(--border);padding:10px;border-radius:6px;font-size:11px">${escapeHTML(h.raw_response || "")}</pre>
              <h3 style="color:var(--cyan);font-size:11px;text-transform:uppercase;letter-spacing:0.18em;margin:16px 0 6px">JSON parsé</h3>
              <pre style="white-space:pre-wrap;max-height:160px;overflow:auto;background:rgba(10,16,32,0.6);border:1px solid var(--border);padding:10px;border-radius:6px;font-size:11px">${escapeHTML(JSON.stringify(h.parsed_output, null, 2) || "null")}</pre>`,
            footer: [{ label: "Fermer", ghost: true, onClick: mm => mm.close() }],
          });
        } catch (e) { alert("Erreur: " + e); }
      };
    });
  }

  function renderTasks(tasks) {
    if (!tasks.length) return `<div class="muted">Aucune tâche.</div>`;
    return `
      <table>
        <thead><tr><th>Description</th><th>Statut</th><th></th></tr></thead>
        <tbody>${tasks.map(t => `
          <tr data-task-id="${t.id}">
            <td>
              <input class="task-desc" type="text" value="${Dash.escapeHTML(t.description)}" style="width:100%;background:rgba(10,16,32,0.6);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:12px" />
              ${t.blocked_reason ? `<small style="color:var(--red)">bloqué: ${Dash.escapeHTML(t.blocked_reason)}</small>` : ""}
              ${t.result ? `<small class="muted">résultat: ${Dash.escapeHTML(Dash.clip(t.result, 120))}</small>` : ""}
            </td>
            <td>
              <select class="task-status" style="background:rgba(10,16,32,0.6);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:12px">
                ${["todo","in_progress","done","blocked"].map(s => `<option value="${s}" ${t.status===s?"selected":""}>${s}</option>`).join("")}
              </select>
            </td>
            <td>
              <button class="btn ghost task-save" type="button">save</button>
              <button class="btn ghost task-del" type="button" title="Supprimer">×</button>
            </td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  }

  function wireTaskRows(rootEl, projectId) {
    Dash.$$("#p-tasks tbody tr").forEach(tr => {
      const tid = parseInt(tr.dataset.taskId, 10);
      const desc = tr.querySelector(".task-desc");
      const status = tr.querySelector(".task-status");
      tr.querySelector(".task-save").onclick = async () => {
        try {
          await sendJSON(`/api/projects/${projectId}/tasks/${tid}`, "PATCH", {
            description: desc.value, status: status.value,
          });
          tr.style.background = "rgba(76,255,158,0.1)";
          setTimeout(() => (tr.style.background = ""), 600);
        } catch (e) { alert("Erreur: " + e); }
      };
      tr.querySelector(".task-del").onclick = async () => {
        if (!(await Dash.confirm("Supprimer cette tâche ?", { danger: true }))) return;
        try {
          await sendJSON(`/api/projects/${projectId}/tasks/${tid}`, "DELETE");
          tr.remove();
        } catch (e) { alert("Erreur: " + e); }
      };
    });
  }

  // ── Payload extraction ────────────────────────────────────────
  function collectPayload(form) {
    const fd = new FormData(form);
    const textList = s => (s || "").split("\n").map(l => l.trim()).filter(Boolean);
    const csvList  = s => (s || "").split(",").map(l => l.trim()).filter(Boolean);
    const ownerRaw = fd.get("owner_id");
    return {
      title: (fd.get("title") || "").trim(),
      description: fd.get("description") || "",
      status: fd.get("status"),
      priority: fd.get("priority"),
      origin: fd.get("origin"),
      owner_id: ownerRaw ? parseInt(ownerRaw, 10) : null,
      emotion_policy: fd.get("emotion_policy"),
      tone_directive: fd.get("tone_directive") || "",
      instructions: textList(fd.get("instructions")),
      out_of_scope: textList(fd.get("out_of_scope")),
      keywords: csvList(fd.get("keywords")),
      allowed_modules: csvList(fd.get("allowed_modules")),
      contacts: csvList(fd.get("contacts")),
      resource_paths: textList(fd.get("resource_paths")),
      schedule_rule: (fd.get("schedule_rule") || "").trim(),
      monthly_token_budget: parseInt(fd.get("monthly_token_budget") || "0", 10) || 0,
      requires_approval: !!fd.get("requires_approval"),
    };
  }

  renderList();
});
