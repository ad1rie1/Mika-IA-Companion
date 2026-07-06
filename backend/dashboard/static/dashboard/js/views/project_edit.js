/* Projet — page édition / création pleine (pas de modale).
 *
 * window.PROJECT_ID === null  → création (POST /api/projects/create)
 * window.PROJECT_ID === <int> → édition (PATCH /api/projects/<id>) + tâches
 *
 * Reprend le formulaire complet de l'ancienne modale, rendu en pleine page.
 */
Dash.render(async (root) => {
  const { escapeHTML, fmtDate } = Dash;

  const STATUS      = ["active", "paused", "completed", "abandoned"];
  const PRIORITY    = ["low", "normal", "high", "urgent"];
  const ORIGIN      = ["user", "self"];
  const POLICY      = ["off", "muted", "full"];

  const id = window.PROJECT_ID;
  const isNew = id === null || id === undefined;

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
    try {
      const d = await fetch("/dashboard/api/persons?limit=1000").then(r => r.json());
      return (d.rows || d.profiles || [])
        .filter(p => p.entity_id)
        .map(p => ({ id: p.entity_id, name: p.name }));
    } catch { return []; }
  }

  // ── chargement projet + owners ────────────────────────────────
  let project = null;
  let tasks = [];
  if (!isNew) {
    project = await fetch(`/api/projects/${id}`).then(r => r.json()).catch(() => null);
    if (!project || project.error) { root.innerHTML = `<div class="empty">Projet introuvable.</div>`; return; }
    tasks = project.tasks || [];
  }
  const owners = await loadOwners();

  const p = project || {
    title: "", description: "", keywords: [],
    origin: "user", status: "active", priority: "normal",
    tone_directive: "", emotion_policy: "off",
    instructions: [], out_of_scope: [],
    requires_approval: false, owner_id: null,
    allowed_modules: [], resource_paths: [], contacts: [],
    schedule_rule: "", monthly_token_budget: 0,
  };

  const listTextarea = arr => (arr || []).join("\n");
  const csvInput = arr => (arr || []).join(", ");
  const ownerOpts = [`<option value="">— aucun —</option>`]
    .concat(owners.map(o =>
      `<option value="${o.id}" ${p.owner_id === o.id ? "selected" : ""}>${escapeHTML(o.name)}</option>`))
    .join("");

  const backHref = isNew ? "/dashboard/projects/" : `/dashboard/projects/${id}/`;

  root.innerHTML = `
    <div class="mb"><a class="btn ghost" href="${backHref}">← Annuler</a></div>
    <div class="card">
      <h3>${isNew ? "Nouveau projet" : "Éditer — " + escapeHTML(p.title)}</h3>
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
      </form>

      <div class="toolbar mt">
        <a class="btn ghost" href="${backHref}">Annuler</a>
        <button type="button" class="btn primary" id="btn-save">${isNew ? "Créer" : "Enregistrer"}</button>
        ${!isNew ? `<button type="button" class="btn ghost" id="btn-delete" style="color:var(--red)">Supprimer</button>` : ""}
      </div>
    </div>

    ${!isNew ? `
      <div class="card mt">
        <h3 style="color:var(--cyan);letter-spacing:0.18em;text-transform:uppercase;font-size:11px">Tâches <span class="tag" id="task-count">${tasks.length}</span></h3>
        <div id="p-tasks"></div>
        <div class="toolbar mt">
          <input type="text" id="new-task-desc" placeholder="Nouvelle tâche…" style="flex:1" />
          <button type="button" class="btn" id="btn-add-task">+ Ajouter</button>
        </div>
      </div>` : ""}`;

  // ── Payload ───────────────────────────────────────────────────
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

  Dash.$("#btn-save").onclick = async () => {
    const payload = collectPayload(Dash.$("#p-form"));
    if (!payload.title) { alert("Le titre est obligatoire."); return; }
    try {
      if (isNew) {
        const res = await sendJSON("/api/projects/create", "POST", payload);
        const newId = res.project && res.project.id;
        location.href = newId ? `/dashboard/projects/${newId}/` : "/dashboard/projects/";
      } else {
        await sendJSON(`/api/projects/${id}`, "PATCH", payload);
        location.href = `/dashboard/projects/${id}/`;
      }
    } catch (e) { alert("Erreur: " + e); }
  };

  const delBtn = Dash.$("#btn-delete");
  if (delBtn) {
    delBtn.onclick = async () => {
      if (!(await Dash.confirm(`Supprimer le projet "${p.title}" ? Cette action est irréversible.`, { danger: true }))) return;
      try {
        await sendJSON(`/api/projects/${id}`, "DELETE");
        location.href = "/dashboard/projects/";
      } catch (e) { alert("Erreur: " + e); }
    };
  }

  // ── Tâches (édition inline) ───────────────────────────────────
  if (!isNew) {
    const TASK_STATUS = ["todo", "in_progress", "done", "blocked"];

    function renderTasks(list) {
      const mount = Dash.$("#p-tasks");
      Dash.$("#task-count").textContent = list.length;
      if (!list.length) { mount.innerHTML = `<div class="muted">Aucune tâche.</div>`; return; }
      const wrap = document.createElement("div");
      mount.innerHTML = "";
      mount.appendChild(wrap);
      Dash.clientPager({
        rows: list, limit: 25, mount,
        render: page => {
          wrap.innerHTML = `
            <table>
              <thead><tr><th>Description</th><th>Statut</th><th></th></tr></thead>
              <tbody>${page.map(t => `
                <tr data-task-id="${t.id}">
                  <td>
                    <input class="task-desc" type="text" value="${escapeHTML(t.description)}" style="width:100%;background:rgba(10,16,32,0.6);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:12px" />
                    ${t.blocked_reason ? `<small style="color:var(--red)">bloqué: ${escapeHTML(t.blocked_reason)}</small>` : ""}
                    ${t.result ? `<small class="muted">résultat: ${escapeHTML(Dash.clip(t.result, 120))}</small>` : ""}
                  </td>
                  <td>
                    <select class="task-status" style="background:rgba(10,16,32,0.6);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:4px;font-family:inherit;font-size:12px">
                      ${TASK_STATUS.map(s => `<option value="${s}" ${t.status===s?"selected":""}>${s}</option>`).join("")}
                    </select>
                  </td>
                  <td>
                    <button class="btn ghost task-save" type="button">save</button>
                    <button class="btn ghost task-del" type="button" title="Supprimer">×</button>
                  </td>
                </tr>`).join("")}
              </tbody>
            </table>`;
          wrap.querySelectorAll("tbody tr").forEach(tr => {
            const tid = parseInt(tr.dataset.taskId, 10);
            const desc = tr.querySelector(".task-desc");
            const status = tr.querySelector(".task-status");
            tr.querySelector(".task-save").onclick = async () => {
              try {
                await sendJSON(`/api/projects/${id}/tasks/${tid}`, "PATCH", {
                  description: desc.value, status: status.value,
                });
                tr.style.background = "rgba(76,255,158,0.1)";
                setTimeout(() => (tr.style.background = ""), 600);
              } catch (e) { alert("Erreur: " + e); }
            };
            tr.querySelector(".task-del").onclick = async () => {
              if (!(await Dash.confirm("Supprimer cette tâche ?", { danger: true }))) return;
              try {
                await sendJSON(`/api/projects/${id}/tasks/${tid}`, "DELETE");
                tasks = tasks.filter(x => x.id !== tid);
                renderTasks(tasks);
              } catch (e) { alert("Erreur: " + e); }
            };
          });
        },
      });
    }

    renderTasks(tasks);

    Dash.$("#btn-add-task").onclick = async () => {
      const inp = Dash.$("#new-task-desc");
      const desc = inp.value.trim();
      if (!desc) return;
      try {
        const res = await sendJSON(`/api/projects/${id}/tasks`, "POST", { description: desc });
        inp.value = "";
        if (res.task) tasks.push(res.task);
        renderTasks(tasks);
      } catch (e) { alert("Erreur: " + e); }
    };
  }
});
