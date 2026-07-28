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

  // ── CSRF ────────────────────────────────────────────────────
  // Every mutating request now needs a token (CsrfViewMiddleware is on, and
  // no endpoint is @csrf_exempt any more). Rather than touching the ~16
  // fetch() call sites scattered across the view scripts — and requiring
  // every future one, including module-supplied views, to remember — the
  // header is attached here once.
  //
  // Same-origin only: the dashboard is served by Django, so a request going
  // anywhere else is not ours to sign, and leaking the token to a third
  // party is exactly what it exists to prevent.
  const CSRF_SAFE = /^(GET|HEAD|OPTIONS|TRACE)$/i;

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function isSameOrigin(input) {
    try {
      const url = new URL(
        typeof input === "string" ? input : input.url, window.location.href,
      );
      return url.origin === window.location.origin;
    } catch {
      return false;
    }
  }

  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const opts = init || {};
    const method = (opts.method || "GET").toUpperCase();
    if (CSRF_SAFE.test(method) || !isSameOrigin(input)) {
      return nativeFetch(input, opts);
    }
    const headers = new Headers(opts.headers || {});
    if (!headers.has("X-CSRFToken")) {
      headers.set("X-CSRFToken", csrfToken());
    }
    return nativeFetch(input, { credentials: "same-origin", ...opts, headers });
  };

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

  // ── Client-side pagination ──────────────────────────────────
  // For in-memory / bounded lists (live affect, modules, MCP tools,
  // pending actions). `render(pageRows)` paints the current slice;
  // the pager is (re)mounted into `mount` after each draw. Reuses
  // `pager()` so the markup stays identical to server-side paging.
  function clientPager({ rows, limit = 25, mount, render }) {
    rows = rows || [];
    let offset = 0;
    function draw() {
      render(rows.slice(offset, offset + limit));
      mount.querySelectorAll(":scope > .pager").forEach(p => p.remove());
      if (rows.length > limit) {
        mount.appendChild(pager({
          total: rows.length, limit, offset,
          onPrev: o => { offset = o; draw(); },
          onNext: o => { offset = o; draw(); },
        }));
      }
    }
    draw();
  }

  // ── Tab bar ─────────────────────────────────────────────────
  // Generalizes the per-view tab pattern (active tab persisted in
  // localStorage, .btn.primary/.ghost toggle). `tabs` is a list of
  // {key, label, render(body)} — render may be async and receives the
  // body element to populate. Returns {body, paint}.
  function tabs({ mount, storeKey, tabs: defs }) {
    const read = () => { try { return localStorage.getItem(storeKey); } catch (_) { return null; } };
    const write = k => { try { localStorage.setItem(storeKey, k); } catch (_) {} };
    let activeKey = defs.some(t => t.key === read()) ? read() : defs[0].key;

    const bar = document.createElement("div");
    bar.className = "card tabbar";
    bar.innerHTML = defs.map(t =>
      `<button class="btn ${t.key === activeKey ? "primary" : "ghost"}" data-tab="${t.key}">${escapeHTML(t.label)}</button>`
    ).join("");

    const body = document.createElement("div");

    mount.innerHTML = "";
    mount.appendChild(bar);
    mount.appendChild(body);

    async function paint(key) {
      const tab = defs.find(t => t.key === key) || defs[0];
      activeKey = tab.key;
      bar.querySelectorAll("button[data-tab]").forEach(b => {
        const on = b.dataset.tab === tab.key;
        b.classList.toggle("primary", on);
        b.classList.toggle("ghost", !on);
      });
      body.innerHTML = `<div class="empty"><span class="loader"></span></div>`;
      await tab.render(body);
    }

    bar.querySelectorAll("button[data-tab]").forEach(btn => {
      btn.onclick = () => { write(btn.dataset.tab); paint(btn.dataset.tab); };
    });

    paint(activeKey);
    return { body, paint };
  }

  // ── Mobile top-menu toggle ──────────────────────────────────
  // Hamburger in the header drops the sidebar down as a top menu on
  // narrow screens. Backdrop click or Escape closes it; navigating to a
  // menu item reloads the page, which resets the state on its own.
  function wireNav() {
    const toggle = $("#nav-toggle");
    const backdrop = $("#nav-backdrop");
    if (!toggle) return;
    const set = open => {
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    toggle.addEventListener("click", () =>
      set(!document.body.classList.contains("nav-open")));
    if (backdrop) backdrop.addEventListener("click", () => set(false));
    document.addEventListener("keydown", e => { if (e.key === "Escape") set(false); });
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
      identity: d.counts.identity,
      projects: d.counts.projects_active,
      ruminations: d.counts.ruminations_active,
      commitments: d.counts.commitments_pending,
      observations: d.counts.observations_pending,
      messages: d.counts.messages,
    };
    $$("[data-count]").forEach(el => {
      const key = el.dataset.count;
      // Only badge non-zero counts — a "0" pill is noise (and clutters the
      // collapsed icon-only sidebar on mobile).
      if (counts[key] != null) el.textContent = counts[key] ? counts[key] : "";
    });
  }

  // ── Responsive tables ───────────────────────────────────────
  // Wrap every <table> in a horizontally-scrollable container so wide
  // data tables stay reachable on narrow screens instead of being
  // clipped. Idempotent (skips already-wrapped tables) and driven by a
  // MutationObserver so it also catches dynamic re-renders (pagination,
  // tab switches) inside any view.
  function wrapTables(rootEl) {
    if (!rootEl) return;
    rootEl.querySelectorAll("table").forEach(t => {
      const p = t.parentElement;
      if (!p || p.classList.contains("table-wrap")) return;
      const w = document.createElement("div");
      w.className = "table-wrap";
      t.replaceWith(w);
      w.appendChild(t);
    });
  }
  function watchTables() {
    const root = $("#view-root");
    if (!root || typeof MutationObserver === "undefined") return;
    wrapTables(root);
    const mo = new MutationObserver(muts => {
      for (const m of muts) {
        for (const n of m.addedNodes) {
          if (n.nodeType === 1 && (n.tagName === "TABLE" ||
              (n.querySelector && n.querySelector("table")))) {
            wrapTables(root);
            return;
          }
        }
      }
    });
    mo.observe(root, { childList: true, subtree: true });
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
    wrapTables(root);
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
    emoColor, emoChip, pager, clientPager, tabs, render,
  };

  refreshTop();
  setInterval(refreshTop, 8000);
  watchTables();
  wireNav();
})();
