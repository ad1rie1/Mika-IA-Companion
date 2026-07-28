/* Identités & confiance.
 *
 * La fiche personne répond à « qu'est-ce que Mika sait de Thomas ».
 * Cette page répond à l'autre moitié : « est-ce que celui qui parle EST
 * Thomas, à quel point elle en est sûre, et ce que ça l'autorise à dire ».
 *
 * La colonne qui compte est « Divulgation » : sous la barre (0.70), la
 * fiche de la personne n'est PAS injectée dans le prompt — Mika salue
 * par le prénom et garde l'historique fermé. C'est la seule vue où ça
 * se voit, et le seul endroit où une revendication en attente peut être
 * tranchée autrement que par Mika elle-même.
 */
Dash.render(async (root) => {
  const { api, escapeHTML, pct, fmtRel, fmtDate, clip, pager, tabs, openModal } = Dash;

  const LEVEL_FR = {
    unknown: "inconnu", suspected: "soupçonné", claimed: "revendiqué",
    corroborated: "corroboré", bound: "lié", verified: "vérifié",
  };
  const TRUST_FR = {
    authenticated: "session vérifiée", account: "compte plateforme",
    public: "espace public", internal: "interne",
  };
  // Vert seulement à partir de CORROBORATED : c'est le seuil de
  // divulgation, pas une note esthétique.
  const levelClass = c => (c >= 0.7 ? "ok" : c >= 0.45 ? "warn" : "");

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      openModal({
        title: "Échec",
        body: `<div class="narr">${escapeHTML((data && data.error) || `HTTP ${r.status}`)}</div>`,
        footer: [{ label: "Fermer", ghost: true, onClick: m => m.close() }],
      });
      return null;
    }
    return data;
  }

  const certaintyCell = row => `
    <div class="mono">${row.certainty.toFixed(2)} · ${escapeHTML(LEVEL_FR[row.level] || row.level)}</div>
    <div class="bar ${levelClass(row.certainty)}"><div class="fill" style="width:${Math.min(100, row.certainty * 100)}%"></div></div>
    ${row.ceiling < 1 ? `<div class="muted" style="font-size:10px;">plafond canal ${row.ceiling.toFixed(2)}</div>` : ""}`;

  const handleChips = row => (row.handles || []).length
    ? row.handles.map(h => `<span class="chip mono" title="${escapeHTML(h.channel)} · ${escapeHTML(TRUST_FR[h.trust] || h.trust)}${h.is_ephemeral ? " · éphémère" : ""}">${escapeHTML(h.channel)}:${escapeHTML(clip(h.person_id, 22))}${h.is_ephemeral ? " ⧗" : ""}</span>`).join(" ")
    : `<span class="muted">aucun</span>`;

  const discloseCell = row => row.may_disclose
    ? `<span class="pill pos" title="Sa fiche (profil, historique, engagements) est injectée dans le prompt">ouverte</span>`
    : `<span class="pill warn" title="Seul le ressenti de Mika est injecté ; profil et historique restent fermés">fermée</span>`;

  // ── Modale de détail ──────────────────────────────────────────
  async function openIdentity(id, onChange) {
    const d = await api(`/dashboard/api/identity/${id}`);
    if (!d) return;

    const claimRows = (d.claims || []).map(c => `
      <tr>
        <td>${escapeHTML(c.claimed_name)}</td>
        <td><span class="chip" title="poids ${c.weight}">${escapeHTML(c.kind_label)}</span></td>
        <td><span class="pill ${c.status === "accepted" ? "pos" : c.status === "rejected" ? "neg" : "warn"}">${escapeHTML(c.status)}</span></td>
        <td class="mono">${c.applied_weight ? (c.applied_weight > 0 ? "+" : "") + c.applied_weight.toFixed(2) : "—"}</td>
        <td class="muted">${escapeHTML(clip(c.evidence, 120)) || "—"}</td>
        <td class="muted">${fmtRel(c.created_at)}</td>
      </tr>`).join("");

    const handleRows = (d.handles || []).map(h => `
      <tr>
        <td class="mono">${escapeHTML(h.person_id)}</td>
        <td>${escapeHTML(h.channel)}</td>
        <td><span class="pill ${h.trust === "authenticated" ? "pos" : h.trust === "public" ? "warn" : ""}">${escapeHTML(TRUST_FR[h.trust] || h.trust)}</span></td>
        <td class="mono muted">${h.ceiling.toFixed(2)}</td>
        <td>${h.is_ephemeral ? `<span class="pill">éphémère</span>` : `<span class="muted">—</span>`}</td>
        <td class="muted">${fmtRel(h.last_seen)}</td>
      </tr>`).join("");

    const body = `
      <div class="mb">
        <div class="flex center" style="gap:14px;flex-wrap:wrap;">
          <span class="pill ${d.may_disclose ? "pos" : "warn"}">divulgation ${d.may_disclose ? "ouverte" : "fermée"}</span>
          <span class="muted">certitude <b class="mono">${d.certainty.toFixed(2)}</b> (${escapeHTML(LEVEL_FR[d.level] || d.level)})</span>
          <span class="muted">canal <b>${escapeHTML(TRUST_FR[d.trust] || d.trust)}</b></span>
          <span class="muted">entité <b>${d.entity ? escapeHTML(d.entity.name) : "— non liée"}</b></span>
        </div>
        ${d.certainty_stored !== d.certainty ? `<div class="muted" style="font-size:11px;margin-top:6px;">stockée ${d.certainty_stored.toFixed(2)} · relevée au plancher du canal</div>` : ""}
      </div>

      <div class="muted" style="font-size:11px;">Ce que Mika lit sur cette personne</div>
      <div class="narr mb">${escapeHTML(d.description)}</div>

      ${d.bound_at ? `<div class="muted mb" style="font-size:11px;">Liée ${fmtDate(d.bound_at)} via <b>${escapeHTML(d.bound_via || "?")}</b>${d.binding_reason ? ` — ${escapeHTML(d.binding_reason)}` : ""}</div>` : ""}

      <div class="muted" style="font-size:11px;">Contacts (${(d.handles || []).length})</div>
      <table class="mb">
        <thead><tr><th>person_id</th><th>Canal</th><th>Confiance transport</th><th>Plafond</th><th></th><th>Vu</th></tr></thead>
        <tbody>${handleRows || `<tr><td colspan="6" class="muted">Aucun contact.</td></tr>`}</tbody>
      </table>

      <div class="muted" style="font-size:11px;">Registre des preuves (${(d.claims || []).length})</div>
      <div class="scroll-box">
        <table>
          <thead><tr><th>Nom</th><th>Type</th><th>État</th><th>Δ</th><th>Preuve</th><th>Quand</th></tr></thead>
          <tbody>${claimRows || `<tr><td colspan="6" class="muted">Aucune revendication.</td></tr>`}</tbody>
        </table>
      </div>

      <div class="form-grid mt">
        <div class="form-field">
          <label>Lier à une entité mémoire</label>
          <input type="text" id="id-bind" list="id-entities" placeholder="Nom exact de la personne en mémoire" />
          <datalist id="id-entities"></datalist>
        </div>
        <div class="form-field">
          <label>Ajouter une preuve</label>
          <select id="id-kind"></select>
          <input type="text" id="id-detail" placeholder="Ce qui l'a convaincue (ou pas)" />
        </div>
      </div>`;

    const m = openModal({
      title: d.entity ? `${d.entity.name}` : (d.display_name || `Identité #${d.id}`),
      body,
      footer: [
        { label: "Fermer", ghost: true, onClick: mm => mm.close() },
        {
          label: "Ne plus y croire", danger: true, onClick: async mm => {
            const ok = await Dash.confirm(
              "Révoquer la liaison ? La certitude retombe à zéro et l'entité est détachée. Le registre garde la trace.",
              { danger: true },
            );
            if (!ok) return;
            const res = await post(`/dashboard/api/identity/${id}/revoke`, {
              reason: "Révoqué depuis le dashboard",
            });
            if (res) { mm.close(); onChange && onChange(); }
          },
        },
        {
          label: "Enregistrer", primary: true, onClick: async mm => {
            const name = mm.root.querySelector("#id-bind").value.trim();
            const kind = mm.root.querySelector("#id-kind").value;
            const detail = mm.root.querySelector("#id-detail").value.trim();
            let touched = false;
            if (name) {
              if (!await post(`/dashboard/api/identity/${id}/bind`, { entity_name: name })) return;
              touched = true;
            }
            if (detail) {
              if (!await post(`/dashboard/api/identity/${id}/evidence`, { kind, detail })) return;
              touched = true;
            }
            mm.close();
            if (touched) onChange && onChange();
          },
        },
      ],
    });

    // Choix de preuve = les types déclarés par la policy, jamais une
    // liste écrite ici : les poids vivent dans identity/trust.py.
    const pol = await api("/dashboard/api/identity/policy");
    const select = m.root.querySelector("#id-kind");
    const weights = { ...(pol?.evidence_weights || {}), ...(pol?.counter_evidence_weights || {}) };
    select.innerHTML = (pol?.kinds || [])
      .filter(k => k.value in weights && k.value !== "authenticated")
      .map(k => `<option value="${escapeHTML(k.value)}">${escapeHTML(k.label)} (${weights[k.value] > 0 ? "+" : ""}${weights[k.value]})</option>`)
      .join("");

    const persons = await api("/dashboard/api/persons?limit=1000");
    m.root.querySelector("#id-entities").innerHTML =
      ((persons && persons.rows) || [])
        .map(p => `<option value="${escapeHTML(p.name)}"></option>`).join("");
  }

  // ── Onglet identités ──────────────────────────────────────────
  function identitiesTab() {
    const state = { offset: 0, limit: 25, q: "", filter: "", ephemeral: false };
    return async function renderTab(bodyEl) {
      async function draw() {
        const params = new URLSearchParams({
          limit: state.limit, offset: state.offset,
        });
        if (state.q) params.set("q", state.q);
        if (state.filter) params.set("state", state.filter);
        if (state.ephemeral) params.set("include_ephemeral", "1");
        const d = await api(`/dashboard/api/identity?${params}`);
        if (!d) { bodyEl.innerHTML = `<div class="empty">Indisponible.</div>`; return; }
        const s = d.summary || {};

        bodyEl.innerHTML = `
          <div class="grid cols-4 mb">
            <div class="card"><div class="stat-value">${s.identities || 0}</div><div class="stat-sub">identités durables${s.identities_ephemeral_only ? ` · ${s.identities_ephemeral_only} sockets éphémères` : ""}</div></div>
            <div class="card"><div class="stat-value">${s.bound || 0}</div><div class="stat-sub">liées à une entité mémoire</div></div>
            <div class="card"><div class="stat-value" style="color:${s.may_disclose ? "var(--cyan)" : "var(--amber)"}">${s.may_disclose || 0}</div><div class="stat-sub">dont la fiche est lisible par le prompt</div></div>
            <div class="card"><div class="stat-value" style="color:${s.claims_pending ? "var(--amber)" : "var(--cyan)"}">${s.claims_pending || 0}</div><div class="stat-sub">revendications en attente</div></div>
          </div>

          <div class="toolbar">
            <input type="text" id="id-q" placeholder="Nom, entité, person_id…" value="${escapeHTML(state.q)}" />
            <select id="id-filter">
              <option value="">Toutes</option>
              <option value="pending">Avec revendication en attente</option>
              <option value="bound">Liées</option>
              <option value="unbound">Non liées</option>
            </select>
            <label><input type="checkbox" id="id-eph" ${state.ephemeral ? "checked" : ""} /> inclure les handles éphémères (${s.handles_ephemeral || 0})</label>
          </div>

          <div class="card">
            <table>
              <thead><tr>
                <th>Connue comme</th><th>Entité mémoire</th><th>Certitude</th>
                <th>Contacts</th><th>Divulgation</th><th>Claims</th><th></th>
              </tr></thead>
              <tbody>${d.rows.map(r => `
                <tr>
                  <td>${escapeHTML(r.display_name || "—")}</td>
                  <td>${r.entity
                    ? `<a class="chip link" href="/dashboard/persons/${r.entity.id}/">${escapeHTML(r.entity.name)}</a>`
                    : `<span class="pill warn">non liée</span>`}</td>
                  <td style="min-width:150px;">${certaintyCell(r)}</td>
                  <td><div class="chips">${handleChips(r)}</div></td>
                  <td>${discloseCell(r)}</td>
                  <td>${r.claims_pending
                    ? `<span class="pill warn">${r.claims_pending} en attente</span>`
                    : `<span class="muted">${r.claims_total || 0}</span>`}</td>
                  <td><button class="btn" data-open="${r.id}">Voir</button></td>
                </tr>`).join("") || `<tr><td colspan="7" class="muted">Aucune identité.</td></tr>`}
              </tbody>
            </table>
          </div>`;

        bodyEl.querySelectorAll("[data-open]").forEach(b => {
          b.onclick = () => openIdentity(b.dataset.open, draw);
        });
        const qEl = bodyEl.querySelector("#id-q");
        qEl.onchange = () => { state.q = qEl.value.trim(); state.offset = 0; draw(); };
        const fEl = bodyEl.querySelector("#id-filter");
        fEl.value = state.filter;
        fEl.onchange = () => { state.filter = fEl.value; state.offset = 0; draw(); };
        const eEl = bodyEl.querySelector("#id-eph");
        eEl.onchange = () => { state.ephemeral = eEl.checked; state.offset = 0; draw(); };

        if (d.total > state.limit) {
          bodyEl.appendChild(pager({
            total: d.total, limit: d.limit, offset: d.offset,
            onPrev: o => { state.offset = o; draw(); },
            onNext: o => { state.offset = o; draw(); },
          }));
        }
      }
      await draw();
    };
  }

  // ── Onglet revendications ─────────────────────────────────────
  function claimsTab() {
    const state = { offset: 0, limit: 30, status: "pending" };
    return async function renderTab(bodyEl) {
      async function draw() {
        const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
        if (state.status) params.set("status", state.status);
        const d = await api(`/dashboard/api/identity/claims?${params}`);
        if (!d) { bodyEl.innerHTML = `<div class="empty">Indisponible.</div>`; return; }

        bodyEl.innerHTML = `
          <div class="toolbar">
            <select id="cl-status">
              <option value="pending">En attente (${d.pending})</option>
              <option value="">Toutes</option>
              <option value="accepted">Acceptées</option>
              <option value="rejected">Rejetées</option>
            </select>
            <span class="muted">Une revendication en attente n'est pas comptée dans la certitude : elle attend une décision.</span>
          </div>
          <div class="card">
            <table>
              <thead><tr>
                <th>Affirme être</th><th>Contact</th><th>Type</th><th>Poids</th>
                <th>Preuve</th><th>Canal</th><th>État</th><th>Quand</th><th></th>
              </tr></thead>
              <tbody>${d.rows.map(c => `
                <tr>
                  <td><b>${escapeHTML(c.claimed_name)}</b>${c.identity_name && c.identity_name !== c.claimed_name
                    ? `<div class="muted" style="font-size:11px;">connue comme ${escapeHTML(c.identity_name)}</div>` : ""}</td>
                  <td class="mono muted">${escapeHTML(c.person_id || "—")}</td>
                  <td><span class="chip">${escapeHTML(c.kind_label)}</span></td>
                  <td class="mono ${c.weight < 0 ? "" : "muted"}">${c.weight > 0 ? "+" : ""}${c.weight}</td>
                  <td class="muted" style="max-width:320px;">${escapeHTML(clip(c.evidence, 140)) || "—"}</td>
                  <td class="muted">${escapeHTML(c.channel || "—")}<div style="font-size:10px;">plafond ${c.ceiling.toFixed(2)}</div></td>
                  <td><span class="pill ${c.status === "accepted" ? "pos" : c.status === "rejected" ? "neg" : "warn"}">${escapeHTML(c.status)}</span></td>
                  <td class="muted">${fmtRel(c.created_at)}</td>
                  <td>${c.status === "pending" ? `
                    <button class="btn primary" data-accept="${c.id}">Croire</button>
                    <button class="btn" data-reject="${c.id}">Rejeter</button>` : ""}</td>
                </tr>`).join("") || `<tr><td colspan="9" class="muted">Aucune revendication.</td></tr>`}
              </tbody>
            </table>
          </div>`;

        const sEl = bodyEl.querySelector("#cl-status");
        sEl.value = state.status;
        sEl.onchange = () => { state.status = sEl.value; state.offset = 0; draw(); };

        bodyEl.querySelectorAll("[data-accept]").forEach(b => {
          b.onclick = () => resolveClaim(b.dataset.accept, "accept", draw);
        });
        bodyEl.querySelectorAll("[data-reject]").forEach(b => {
          b.onclick = () => resolveClaim(b.dataset.reject, "reject", draw);
        });

        if (d.total > state.limit) {
          bodyEl.appendChild(pager({
            total: d.total, limit: d.limit, offset: d.offset,
            onPrev: o => { state.offset = o; draw(); },
            onNext: o => { state.offset = o; draw(); },
          }));
        }
      }
      await draw();
    };
  }

  function resolveClaim(claimId, action, onDone) {
    const accepting = action === "accept";
    openModal({
      title: accepting ? "Croire cette revendication" : "Rejeter cette revendication",
      body: `
        <div class="narr mb">${accepting
          ? "Lie le contact à l'entité mémoire du nom revendiqué et monte la certitude du poids de la preuve, plafonné par le canal. Une revendication en salon public ne peut pas dépasser 0.70."
          : "Enregistre le doute pour que la même affirmation ne soit pas recomptée au tour suivant. Rien n'est supprimé."}</div>
        <div class="form-field">
          <label>Raison (gardée dans le registre)</label>
          <input type="text" id="cl-reason" placeholder="${accepting ? "ce qui t'a convaincu" : "pourquoi tu n'y crois pas"}" />
        </div>
        ${accepting ? `
        <div class="form-field">
          <label>Preuve supplémentaire (optionnel)</label>
          <select id="cl-kind">
            <option value="">Aucune — juste l'affirmation</option>
            <option value="shared_memory">A prouvé savoir quelque chose que seul lui/elle sait (+0.50)</option>
            <option value="vouched">Présenté par quelqu'un de confiance (+0.35)</option>
          </select>
        </div>` : ""}`,
      footer: [
        { label: "Annuler", ghost: true, onClick: m => m.close() },
        {
          label: accepting ? "Croire" : "Rejeter",
          primary: accepting, danger: !accepting,
          onClick: async m => {
            const reason = m.root.querySelector("#cl-reason").value.trim();
            const kindEl = m.root.querySelector("#cl-kind");
            const res = await post(
              `/dashboard/api/identity/claims/${claimId}/${action}`,
              accepting
                ? { reason, evidence_kind: kindEl ? kindEl.value : "" }
                : { reason },
            );
            m.close();
            if (res) onDone();
          },
        },
      ],
    });
  }

  // ── Onglet politique ──────────────────────────────────────────
  function policyTab() {
    return async function renderTab(bodyEl) {
      const p = await api("/dashboard/api/identity/policy");
      if (!p) { bodyEl.innerHTML = `<div class="empty">Indisponible.</div>`; return; }
      const bar = p.thresholds.private_context;

      const weightRows = Object.entries(p.evidence_weights)
        .concat(Object.entries(p.counter_evidence_weights))
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => {
          const label = (p.kinds.find(x => x.value === k) || {}).label || k;
          return `<tr>
            <td>${escapeHTML(label)}</td>
            <td class="mono">${escapeHTML(k)}</td>
            <td class="mono" style="color:${v < 0 ? "var(--red)" : "var(--green)"}">${v > 0 ? "+" : ""}${v}</td>
          </tr>`;
        }).join("");

      bodyEl.innerHTML = `
        <div class="card mb">
          <h3>Le seuil qui compte</h3>
          <div class="narr">
            Au-dessus de <b class="mono">${bar}</b>, la fiche de la personne (profil, historique,
            engagements) est injectée dans le prompt. En dessous, Mika ne reçoit que son propre
            ressenti envers le contact. Un salon public ne franchit jamais ce seuil, quelle que
            soit la certitude : le risque n'y est pas de se tromper de personne, c'est le public.
          </div>
        </div>

        <div class="grid cols-2 mb">
          <div class="card">
            <h3>Niveaux de certitude</h3>
            <table>
              <thead><tr><th>Niveau</th><th>Valeur</th><th></th></tr></thead>
              <tbody>${p.levels.map(l => `
                <tr>
                  <td>${escapeHTML(LEVEL_FR[l.name] || l.name)}</td>
                  <td class="mono">${l.value.toFixed(2)}</td>
                  <td>${l.value >= bar ? `<span class="pill pos">fiche ouverte</span>` : `<span class="muted">fiche fermée</span>`}</td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>

          <div class="card">
            <h3>Ce que prouve chaque canal</h3>
            <table>
              <thead><tr><th>Transport</th><th>Plancher</th><th>Plafond</th></tr></thead>
              <tbody>${p.channels.map(c => `
                <tr>
                  <td>${escapeHTML(TRUST_FR[c.trust] || c.trust)}</td>
                  <td class="mono muted">${c.floor.toFixed(2)}</td>
                  <td class="mono">${c.ceiling.toFixed(2)}${c.ceiling < bar ? ` <span class="pill warn">jamais</span>` : ""}</td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>

        <div class="card mb">
          <h3>Poids des preuves</h3>
          <div class="muted mb" style="font-size:11px;">
            Calibré contre le seuil : « il dit qui il est » (+0.20) seul ne suffit jamais,
            « il sait un truc que seul lui sait » (+0.50) seul non plus — les deux ensemble
            tombent pile sur ${bar}.
          </div>
          <table>
            <thead><tr><th>Preuve</th><th>Clé</th><th>Poids</th></tr></thead>
            <tbody>${weightRows}</tbody>
          </table>
        </div>

        <div class="card">
          <h3>Identifiants réservés</h3>
          <div class="chips">${p.internal_person_ids.map(x => `<span class="chip mono">${escapeHTML(x)}</span>`).join("")}</div>
          <div class="muted mt" style="font-size:11px;">
            Plomberie interne de Mika — jamais des interlocuteurs. Les contacts préfixés
            <span class="mono">${escapeHTML(p.ephemeral_prefix)}</span> sont des sockets jetables : rien de durable ne doit y être classé.
          </div>
        </div>`;
    };
  }

  root.innerHTML = `<div id="identity-tabs"></div>`;
  tabs({
    mount: root.querySelector("#identity-tabs"),
    storeKey: "identity-tab",
    tabs: [
      { key: "identities", label: "Identités",       render: identitiesTab() },
      { key: "claims",     label: "Revendications",  render: claimsTab() },
      { key: "policy",     label: "Politique",       render: policyTab() },
    ],
  });
});
