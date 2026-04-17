/* Dashboard shared runtime — exposed as window.Dash.
 *
 * Loaded on every page by base.html. Provides:
 *   - DOM + fetch helpers
 *   - formatting (dates, percentages, HTML escaping)
 *   - emotion color mapping
 *   - top-bar auto-refresh
 *   - sidebar counter wiring
 *   - simple pagination helper
 */
(function () {
  "use strict";

  // ── DOM helpers ─────────────────────────────────────────────
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // ── Formatting ──────────────────────────────────────────────
  const fmtDate = iso => iso
    ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" })
    : "—";
  const fmtRel = iso => {
    if (!iso) return "—";
    const d = (new Date() - new Date(iso)) / 1000;
    if (d < 60) return `${Math.floor(d)}s`;
    if (d < 3600) return `${Math.floor(d / 60)}m`;
    if (d < 86400) return `${Math.floor(d / 3600)}h`;
    return `${Math.floor(d / 86400)}j`;
  };
  const pct = v => Math.round((v || 0) * 100) + "%";
  const clip = (s, n = 200) => {
    s = (s || "").trim();
    return s.length > n ? s.slice(0, n) + "…" : s;
  };
  const escapeHTML = s =>
    String(s ?? "").replace(/[&<>"']/g, c =>
      ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c])
    );

  // ── Fetch wrapper ───────────────────────────────────────────
  async function api(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error("HTTP " + r.status);
      return await r.json();
    } catch (e) {
      console.error("API", url, e);
      return null;
    }
  }

  // ── Emotion palette ─────────────────────────────────────────
  const EMOTION_COLOR = {
    happy: "#4cff9e", excited: "#ffa500", love: "#ff4bd8", proud: "#ffc857",
    grateful: "#9eff4c", playful: "#ffb347", amused: "#ffde4c", hopeful: "#4ccfff",
    relieved: "#8affb7",
    sad: "#6b8cff", angry: "#ff4b4b", scared: "#c87bff", disgusted: "#8aff4c",
    frustrated: "#ff7849", lonely: "#5a6fa8", anxious: "#d97fff", bored: "#8094b0",
    jealous: "#ffbe4b",
    surprised: "#ffdf59", thinking: "#5ee1ff", confused: "#b88aff",
    embarrassed: "#ffa6c4", nostalgic: "#c2a8ff", dreamy: "#8a5cff",
    determined: "#ff5b6e", mischievous: "#ff4bd8", curious: "#5ee1ff",
    melancholic: "#6b78a0", neutral: "#8ea4c8",
  };
  const emoColor = e => EMOTION_COLOR[e] || "#8ea4c8";
  const emoChip = (e, w) => {
    const c = emoColor(e);
    return `<span class="emo-chip" style="border-color:${c}55;color:${c};">
      ${escapeHTML(e)}${w != null ? ` · <b>${pct(w)}</b>` : ""}
    </span>`;
  };

  // ── Pagination ──────────────────────────────────────────────
  function pager({ total, limit, offset, onPrev, onNext }) {
    const page = Math.floor(offset / limit) + 1;
    const pages = Math.max(1, Math.ceil(total / limit));
    const wrap = document.createElement("div");
    wrap.className = "pager";
    wrap.innerHTML = `
      <button class="btn" data-prev ${offset <= 0 ? "disabled" : ""}>← Préc.</button>
      <span class="pager-info">page <b>${page}</b> / ${pages} · ${total} total</span>
      <button class="btn" data-next ${offset + limit >= total ? "disabled" : ""}>Suiv. →</button>
    `;
    wrap.querySelector("[data-prev]").onclick = () => onPrev && onPrev(Math.max(0, offset - limit));
    wrap.querySelector("[data-next]").onclick = () => onNext && onNext(offset + limit);
    return wrap;
  }

  // ── Top-bar refresh + sidebar counters ──────────────────────
  async function refreshTop() {
    const d = await api("/dashboard/api/overview");
    const status = $("#sys-status");
    const dot = $("#ws-dot");
    if (!d) {
      if (status) status.textContent = "OFFLINE";
      if (dot) dot.classList.add("offline");
      return;
    }
    if (dot) dot.classList.remove("offline");
    if ($("#sys-name")) $("#sys-name").textContent = (d.vtuber.name || "MIKA").toUpperCase();
    if (status) status.textContent = "ONLINE";
    if ($("#sys-phase")) $("#sys-phase").textContent = d.circadian.phase;
    if ($("#sys-energy")) $("#sys-energy").textContent = pct(d.energy);
    if ($("#sys-mood")) {
      const em = d.emotion.global_label;
      $("#sys-mood").innerHTML = `<span style="color:${emoColor(em)}">${em}</span> ${pct(d.emotion.global_intensity)}`;
    }
    if ($("#sys-sleep")) $("#sys-sleep").textContent = d.sleep_phase;
    if ($("#sys-time")) $("#sys-time").textContent =
      new Date(d.timestamp).toLocaleTimeString("fr-FR");

    // Sidebar counters — any menu item with data-count="<key>" gets filled
    const counts = {
      souvenirs: d.counts.souvenirs,
      connaissances: d.counts.connaissances,
      persons: d.counts.persons,
      projects: d.counts.projects_active,
      ruminations: d.counts.ruminations_active,
      commitments: d.counts.commitments_pending,
      observations: d.counts.observations_pending,
      messages: d.counts.messages,
    };
    $$("[data-count]").forEach(el => {
      const key = el.dataset.count;
      if (counts[key] != null) el.textContent = counts[key];
    });
  }

  // ── View helper ─────────────────────────────────────────────
  // Each view JS uses Dash.render(fn) — fn receives the #view-root
  // and is expected to populate it. Errors become empty states.
  async function render(fn) {
    const root = $("#view-root");
    try {
      await fn(root);
    } catch (e) {
      console.error(e);
      root.innerHTML = `<div class="empty">Erreur : ${escapeHTML(String(e))}</div>`;
    }
  }

  // ── Expose + bootstrap ──────────────────────────────────────
  window.Dash = {
    $, $$, el: (t, a, ...c) => {
      const e = document.createElement(t);
      for (const [k, v] of Object.entries(a || {})) {
        if (k === "class") e.className = v;
        else if (k === "html") e.innerHTML = v;
        else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v);
      }
      for (const x of c) {
        if (x == null) continue;
        e.appendChild(typeof x === "string" ? document.createTextNode(x) : x);
      }
      return e;
    },
    api, fmtDate, fmtRel, pct, clip, escapeHTML,
    emoColor, emoChip, pager, render,
  };

  refreshTop();
  setInterval(refreshTop, 8000);
})();
