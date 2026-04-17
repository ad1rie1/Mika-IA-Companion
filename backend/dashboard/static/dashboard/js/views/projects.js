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

  // ── List ──────────────────────────────────────────────────────
  async function renderList() {
    const [listRes, pendingRes] = await Promise.all([
      fetch("/api/projects/").then(r => r.json()),
      fetch("/api/projects/pending/").then(r => r.json()),
    ]);
    const projects = listRes.projects || [];
    const pending = pendingRes.pending || [];

    const stp = s => ({active:"pos",paused:"warn",completed:"",abandoned:"neg"}[s] || "");
    const pp  = s => ({urgent:"neg",high:"warn",normal:"",low:""}[s] || "");

    root.innerHTML = `
      <div class="toolbar">
        <button class="btn primary" id="btn-new">+ Nouveau projet</button>
        <span class="muted">${projects.length} projet${projects.length > 1 ? "s" : ""}</span>
      </div>

      ${pending.length ? `
        <div class="card mb" style="border-color:rgba(255,200,87,0.4);">
          <h3 style="color:var(--amber)">⚠ Actions en attente d'approbation<span class="tag">${pending.length}</span></h3>
          ${pending.map(a => `
            <div class="metric-row">
              <span class="k">${escapeHTML(clip(a.proposal, 200))}</span>
              <span class="v muted">projet <b>${escapeHTML(a.project_title)}</b> · ${fmtRel(a.created_at)}</span>
            </div>`).join("")}
        </div>` : ""}

      <div class="grid cols-2" id="p-list">
        ${projects.map(p => {
          // task counts aren't in the list endpoint — we render summary from fields.
          return `
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
              <div class="chips mt">
                ${(p.keywords || []).slice(0, 6).map(k => `<span class="chip">${escapeHTML(k)}</span>`).join("")}
              </div>
            </div>`;
        }).join("") || `<div class="empty">Aucun projet — clique <b>+ Nouveau projet</b> pour démarrer.</div>`}
      </div>`;

    Dash.$("#btn-new").onclick = () => openEditor(null);
    Dash.$$("#p-list .card.clickable").forEach(card => {
      card.onclick = () => openEditor(parseInt(card.dataset.id, 10));
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
      requires_approval: false,
      allowed_modules: [], resource_paths: [], contacts: [],
      schedule_rule: "", monthly_token_budget: 0,
    };

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
          <h3 style="color:var(--cyan);letter-spacing:0.18em;text-transform:uppercase;font-size:11px;margin:0 0 10px">Tâches <span class="tag">${tasks.length}</span></h3>
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
    }
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
    return {
      title: (fd.get("title") || "").trim(),
      description: fd.get("description") || "",
      status: fd.get("status"),
      priority: fd.get("priority"),
      origin: fd.get("origin"),
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
