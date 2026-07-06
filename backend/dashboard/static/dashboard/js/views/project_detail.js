/* Projet — page détail pleine (pas de modale).
 *
 * En-tête récapitulatif + onglets (Vue d'ensemble / Tâches / Historique
 * runner / Prompts LLM / Actions en attente). Chaque table est paginée
 * côté client via Dash.clientPager. L'édition se fait sur
 * /dashboard/projects/<id>/edit/ .
 */
Dash.render(async (root) => {
  const { escapeHTML, clip, fmtDate, fmtRel } = Dash;
  const id = window.PROJECT_ID;

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

  // ── helpers repris de l'ancien projects.js ────────────────────
  function fmtTokens(n) {
    n = n || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
    return String(n);
  }

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

  const stp = s => ({ active: "pos", paused: "warn", completed: "", abandoned: "neg" }[s] || "");
  const pp  = s => ({ urgent: "neg", high: "warn", normal: "", low: "" }[s] || "");
  const tsp = s => ({ done: "pos", in_progress: "warn", blocked: "neg", todo: "" }[s] || "");

  // ── chargement ────────────────────────────────────────────────
  const p = await fetch(`/api/projects/${id}`).then(r => r.json()).catch(() => null);
  if (!p || p.error) {
    root.innerHTML = `<div class="empty">Projet introuvable.</div>`;
    return;
  }
  const tasks = p.tasks || [];
  const recentLogs = p.recent_logs || [];
  const pending = p.pending_actions || [];

  // ── En-tête ───────────────────────────────────────────────────
  const header = `
    <div class="mb"><a class="btn ghost" href="/dashboard/projects/">← Tous les projets</a></div>
    <div class="card">
      <div class="flex between center mb" style="gap:12px;flex-wrap:wrap">
        <h3 style="margin:0">${escapeHTML(p.title)}</h3>
        <span style="white-space:nowrap;display:flex;gap:6px;flex-wrap:wrap">
          <a class="btn primary" href="/dashboard/projects/${id}/edit/">✎ Éditer</a>
          ${p.status === "active" ? `<button class="btn ghost" id="btn-advance">▶ Faire avancer</button>` : ""}
          <button class="btn ghost" id="btn-delete" style="color:var(--red)">Supprimer</button>
        </span>
      </div>
      <div class="flex gap mb" style="flex-wrap:wrap">
        <span class="pill ${stp(p.status)}">${p.status}</span>
        <span class="pill ${pp(p.priority)}">${p.priority}</span>
        <span class="pill">${escapeHTML(p.origin)}</span>
        <span class="tag">politique ${escapeHTML(p.emotion_policy)}</span>
      </div>
      <div class="grid cols-2">
        <div>
          <div class="metric-row"><span class="k">Owner</span><span class="v">${escapeHTML(p.owner || "—")}</span></div>
          <div class="metric-row"><span class="k">Planification</span><span class="v mono">${escapeHTML(p.schedule_rule || "manuel")}</span></div>
          <div class="metric-row"><span class="k">Approbation requise</span><span class="v">${p.requires_approval ? "oui" : "non"}</span></div>
        </div>
        <div>
          <div class="metric-row"><span class="k">Prochaine exécution</span><span class="v">${p.next_run_at ? fmtDate(p.next_run_at) : "—"}</span></div>
          <div class="metric-row"><span class="k">Dernière exécution</span><span class="v">${p.last_run_at ? fmtRel(p.last_run_at) : "—"}</span></div>
          ${capLine(p)}
          ${budgetLine(p.quota)}
        </div>
      </div>
    </div>`;

  root.innerHTML = `${header}<div id="project-tabs" class="mt"></div>`;

  // ── Actions d'en-tête ─────────────────────────────────────────
  const advBtn = root.querySelector("#btn-advance");
  if (advBtn) {
    advBtn.onclick = async () => {
      advBtn.disabled = true;
      advBtn.textContent = "…en cours";
      try {
        await sendJSON(`/api/projects/${id}/advance`, "POST");
        location.reload();
      } catch (e) {
        alert("Erreur: " + e);
        advBtn.disabled = false;
        advBtn.textContent = "▶ Faire avancer";
      }
    };
  }
  root.querySelector("#btn-delete").onclick = async () => {
    if (!(await Dash.confirm(`Supprimer le projet "${p.title}" ? Cette action est irréversible.`, { danger: true }))) return;
    try {
      await sendJSON(`/api/projects/${id}`, "DELETE");
      location.href = "/dashboard/projects/";
    } catch (e) { alert("Erreur: " + e); }
  };

  // ── Onglet 1 : Vue d'ensemble ─────────────────────────────────
  const listBlock = (label, arr, opts = {}) => {
    const items = arr || [];
    if (opts.chips) {
      return `
        <div class="mt">
          <div class="muted" style="font-size:11px">${label}</div>
          <div class="chips">${items.map(t => `<span class="chip">${escapeHTML(t)}</span>`).join("") || '<span class="muted">—</span>'}</div>
        </div>`;
    }
    return `
      <div class="mt">
        <div class="muted" style="font-size:11px">${label}</div>
        ${items.length
          ? `<ul class="narr" style="margin:6px 0 0;padding-left:18px">${items.map(t => `<li>${escapeHTML(t)}</li>`).join("")}</ul>`
          : `<div class="muted">—</div>`}
      </div>`;
  };

  const overviewTab = body => {
    body.innerHTML = `
      <div class="card">
        <div class="muted" style="font-size:11px">Description</div>
        <div class="narr">${escapeHTML(p.description || "—")}</div>
        <div class="mt">
          <div class="muted" style="font-size:11px">Directive de ton</div>
          <div class="narr">${escapeHTML(p.tone_directive || "—")}</div>
        </div>
        ${listBlock("Instructions", p.instructions)}
        ${listBlock("Hors-scope", p.out_of_scope)}
        ${listBlock("Mots-clés", p.keywords, { chips: true })}
        ${listBlock("Modules autorisés", p.allowed_modules, { chips: true })}
        ${listBlock("Contacts", p.contacts, { chips: true })}
        ${listBlock("Chemins de ressources", p.resource_paths)}
      </div>`;
  };

  // ── Onglet 2 : Tâches (paginé) ────────────────────────────────
  const tasksTab = body => {
    if (!tasks.length) { body.innerHTML = `<div class="card"><div class="muted">Aucune tâche.</div></div>`; return; }
    body.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    body.appendChild(card);
    Dash.clientPager({
      rows: tasks, limit: 25, mount: body,
      render: page => {
        card.innerHTML = `
          <table>
            <thead><tr><th>Description</th><th>Statut</th><th>Détail</th></tr></thead>
            <tbody>${page.map(t => `
              <tr>
                <td style="max-width:480px">${escapeHTML(t.description)}</td>
                <td><span class="pill ${tsp(t.status)}">${t.status}</span></td>
                <td class="muted" style="max-width:360px">
                  ${t.blocked_reason ? `<div style="color:var(--red)">bloqué: ${escapeHTML(t.blocked_reason)}</div>` : ""}
                  ${t.result ? `<div>${escapeHTML(clip(t.result, 200))}</div>` : ""}
                  ${!t.blocked_reason && !t.result ? "—" : ""}
                </td>
              </tr>`).join("")}
            </tbody>
          </table>`;
      },
    });
  };

  // ── Onglet 3 : Historique runner (paginé) ─────────────────────
  const logsTab = body => {
    if (!recentLogs.length) { body.innerHTML = `<div class="card"><div class="muted">Aucun log runner.</div></div>`; return; }
    body.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    body.appendChild(card);
    Dash.clientPager({
      rows: recentLogs, limit: 25, mount: body,
      render: page => {
        card.innerHTML = `
          <table>
            <thead><tr><th>Action</th><th>Résumé</th><th>Date</th></tr></thead>
            <tbody>${page.map(l => `
              <tr>
                <td><span class="pill">${escapeHTML(l.action)}</span></td>
                <td style="max-width:520px">${escapeHTML(l.summary)}</td>
                <td class="muted">${fmtRel(l.created_at)}</td>
              </tr>`).join("")}
            </tbody>
          </table>`;
      },
    });
  };

  // ── Onglet 4 : Prompts LLM (paginé, accordéon inline) ─────────
  const oc = o => ({ ok: "pos", "": "", timeout: "neg", json_miss: "warn", quota_exceeded: "neg", error: "neg" }[o] || "");
  const promptsTab = async body => {
    body.innerHTML = `<div class="card"><div class="loader">Chargement…</div></div>`;
    let rows = [];
    try {
      const d = await fetch(`/api/projects/${id}/history?limit=100&full=1`).then(r => r.json());
      rows = d.history || [];
    } catch (e) {
      body.innerHTML = `<div class="card"><div class="muted">Historique indisponible.</div></div>`;
      return;
    }
    body.innerHTML = "";
    if (!rows.length) { body.innerHTML = `<div class="card"><div class="muted">Aucun prompt enregistré.</div></div>`; return; }

    const pre = t => `<pre style="white-space:pre-wrap;max-height:220px;overflow:auto;background:rgba(10,16,32,0.6);border:1px solid var(--border);padding:10px;border-radius:6px;font-size:11px">${escapeHTML(t || "")}</pre>`;
    const sub = t => `<h4 style="color:var(--cyan);font-size:11px;text-transform:uppercase;letter-spacing:0.18em;margin:14px 0 6px">${t}</h4>`;

    const card = document.createElement("div");
    card.className = "card";
    body.appendChild(card);
    Dash.clientPager({
      rows, limit: 20, mount: body,
      render: page => {
        card.innerHTML = page.map(h => `
          <div class="hist-item" data-hid="${h.id}">
            <div class="metric-row hist-head" style="cursor:pointer">
              <span class="k">
                <span class="pill ${oc(h.outcome)}">${escapeHTML(h.outcome || "?")}</span>
                ${escapeHTML(clip(h.raw_response || "(vide)", 150))}
              </span>
              <span class="v muted">${h.duration_ms != null ? h.duration_ms + "ms · " : ""}${fmtRel(h.created_at)}</span>
            </div>
            <div class="hist-body" style="display:none;padding:4px 0 12px">
              <div class="metric-row"><span class="k">Durée</span><span class="v">${h.duration_ms != null ? h.duration_ms + " ms" : "—"}</span></div>
              ${sub("System prompt")}${pre(h.system_prompt)}
              ${sub("User prompt")}${pre(h.user_prompt)}
              ${sub("Réponse brute")}${pre(h.raw_response)}
              ${sub("JSON parsé")}${pre(JSON.stringify(h.parsed_output, null, 2) || "null")}
            </div>
          </div>`).join("");
        card.querySelectorAll(".hist-item").forEach(item => {
          const head = item.querySelector(".hist-head");
          const bd = item.querySelector(".hist-body");
          head.onclick = () => { bd.style.display = bd.style.display === "none" ? "block" : "none"; };
        });
      },
    });
  };

  // ── Onglet 5 : Actions en attente ─────────────────────────────
  const pendingTab = body => {
    if (!pending.length) { body.innerHTML = `<div class="card"><div class="muted">Aucune action en attente.</div></div>`; return; }
    body.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    body.appendChild(card);
    Dash.clientPager({
      rows: pending, limit: 15, mount: body,
      render: page => {
        card.innerHTML = page.map(a => `
          <div class="metric-row" data-pending-id="${a.id}" style="align-items:flex-start;gap:10px">
            <span class="k">${escapeHTML(a.proposal)}
              <small class="muted">${fmtRel(a.created_at)}</small>
            </span>
            <span class="v" style="white-space:nowrap">
              <button class="btn ghost p-approve" type="button" style="color:var(--green)">✓ Approuver</button>
              <button class="btn ghost p-reject" type="button" style="color:var(--red)">✕ Rejeter</button>
            </span>
          </div>`).join("");
        card.querySelectorAll("[data-pending-id]").forEach(row => {
          const pid = parseInt(row.dataset.pendingId, 10);
          const resolve = async decision => {
            let note = "";
            if (decision === "reject") note = prompt("Note (optionnelle) pour le rejet :") || "";
            try {
              await sendJSON(`/api/projects/pending/${pid}/${decision}`, "POST", { note });
              location.reload();
            } catch (e) { alert("Erreur: " + e); }
          };
          row.querySelector(".p-approve").onclick = () => resolve("approve");
          row.querySelector(".p-reject").onclick  = () => resolve("reject");
        });
      },
    });
  };

  Dash.tabs({
    mount: root.querySelector("#project-tabs"),
    storeKey: "project-detail-tab",
    tabs: [
      { key: "overview", label: "Vue d'ensemble", render: overviewTab },
      { key: "tasks",    label: `Tâches (${tasks.length})`, render: tasksTab },
      { key: "logs",     label: `Historique runner (${recentLogs.length})`, render: logsTab },
      { key: "prompts",  label: "Prompts LLM", render: promptsTab },
      { key: "pending",  label: `Actions en attente${pending.length ? " (" + pending.length + ")" : ""}`, render: pendingTab },
    ],
  });
});
