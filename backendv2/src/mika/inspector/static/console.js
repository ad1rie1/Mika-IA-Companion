// La console de Mika : de petites améliorations, jamais nécessaires (tout marche sans).
// Chargé dans <head> : le thème est posé avant le premier affichage.
(function () {
  "use strict";
  var KEY = "mika.console.theme";

  function readTheme() {
    try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; }
  }
  function applyTheme(value) {
    var root = document.documentElement;
    if (value === "light" || value === "dark") root.setAttribute("data-theme", value);
    else root.removeAttribute("data-theme");
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-theme-set") === value));
    });
  }
  applyTheme(readTheme());

  function ready(fn) {
    if (document.readyState !== "loading") fn(); else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    applyTheme(readTheme());
    // Les longues rubriques restent accessibles sans prendre tout l'écran mobile.
    var narrow = window.matchMedia("(max-width: 1100px)");
    function fitMenus() {
      document.querySelectorAll("[data-responsive-menu]").forEach(function (menu) { menu.open = !narrow.matches; });
    }
    fitMenus();
    narrow.addEventListener("change", fitMenus);
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-theme-set");
        try { localStorage.setItem(KEY, v); } catch (e) { /* navigation privée */ }
        applyTheme(v);
      });
    });

    // Confirmations (celle du bouton qui envoie, sinon celle du formulaire) : le serveur revérifie de
    // toute façon. Un bouton « Approuver » se confirme, son voisin « Refuser » non.
    document.querySelectorAll("form").forEach(function (f) {
      f.addEventListener("submit", function (ev) {
        var b = ev.submitter;
        var msg = (b && b.getAttribute("data-confirm")) || f.getAttribute("data-confirm");
        if (msg && !window.confirm(msg)) ev.preventDefault();
      });
    });

    // Un filtre « liste » se soumet à la sélection.
    document.querySelectorAll("form.filters select").forEach(function (s) {
      s.addEventListener("change", function () { s.form.submit(); });
    });

    // « / » pour chercher.
    var search = document.querySelector("#q-global");
    document.addEventListener("keydown", function (ev) {
      var t = ev.target;
      if (ev.key === "/" && search && !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement ||
          t instanceof HTMLSelectElement)) {
        ev.preventDefault();
        search.focus();
      }
      if (ev.key === "Escape") {
        var open = document.querySelector("#nav-open");
        if (open) open.checked = false;
      }
    });

    // Copier.
    document.querySelectorAll("[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var target = document.querySelector(b.getAttribute("data-copy"));
        if (!target || !navigator.clipboard) return;
        navigator.clipboard.writeText(target.textContent || "").then(function () {
          var old = b.textContent; b.textContent = "Copié"; setTimeout(function () { b.textContent = old; }, 1200);
        });
      });
    });

    // Champs conditionnels : data-only="chemin=v1|v2;chemin2=v" (toutes), alternatives « || » (l'une).
    function valueOf(form, name) {
      var input = (form || document).querySelector('[name="' + name + '"]');
      if (!input) return null;
      if (input.type === "checkbox") return input.checked ? "true" : "false";
      return input.value;
    }
    function holds(form, cond) {
      return cond.split(";").every(function (part) {
        var i = part.indexOf("=");
        if (i < 0) return true;
        var v = valueOf(form, part.slice(0, i));
        return v === null || part.slice(i + 1).split("|").indexOf(v) !== -1;
      });
    }
    function syncOnly() {
      document.querySelectorAll("[data-only]").forEach(function (el) {
        var form = el.closest("form");
        el.hidden = !el.getAttribute("data-only").split("||").some(function (alt) { return holds(form, alt); });
      });
    }
    document.querySelectorAll("select, input").forEach(function (i) { i.addEventListener("change", syncOnly); });
    syncOnly();

    // Tables : une ligne entière mène à sa fiche ; le détail se déplie par un chevron.
    document.querySelectorAll("table.tbl tr[data-href]").forEach(function (tr) {
      tr.addEventListener("click", function (ev) {
        if (ev.target.closest("a, button, input, select, textarea, label, summary, details, form")) return;
        if (window.getSelection && String(window.getSelection()).length) return;
        var url = tr.getAttribute("data-href");
        if (ev.ctrlKey || ev.metaKey || ev.button === 1) window.open(url, "_blank"); else window.location = url;
      });
    });
    document.querySelectorAll("table.tbl tr.detail").forEach(function (detail, index) {
      var row = detail.previousElementSibling;
      var first = row && row.querySelector("td");
      var inner = detail.querySelector("details.row-detail");
      if (!first || !inner) return;
      var initiallyOpen = inner.open;
      inner.open = true;
      if (!initiallyOpen) detail.classList.add("js-folded");
      var btn = document.createElement("button");
      btn.type = "button"; btn.className = "row-toggle"; btn.textContent = "▸";
      detail.id = "row-detail-" + index;
      btn.setAttribute("aria-controls", detail.id);
      btn.setAttribute("aria-expanded", String(initiallyOpen));
      btn.setAttribute("aria-label", initiallyOpen ? "Masquer les détails" : "Voir les détails");
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        var open = detail.classList.toggle("js-folded") === false;
        btn.setAttribute("aria-expanded", String(open));
        btn.setAttribute("aria-label", open ? "Masquer les détails" : "Voir les détails");
      });
      first.insertBefore(btn, first.firstChild);
      var summary = inner.querySelector("summary");
      if (summary) summary.hidden = true;
    });

    // Actions d'en-tête : un seul panneau ouvert à la fois ; Échap ou un clic ailleurs le ferme.
    var pops = document.querySelectorAll("details[data-exclusive]");
    pops.forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (!d.open) return;
        pops.forEach(function (o) { if (o !== d) o.open = false; });
        var first = d.querySelector("input:not([type=hidden]), select, textarea");
        if (first) first.focus();
      });
    });
    document.addEventListener("click", function (ev) {
      pops.forEach(function (d) { if (d.open && !d.contains(ev.target)) d.open = false; });
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") pops.forEach(function (d) { d.open = false; });
    });

    // Curseurs : la valeur à côté.
    document.querySelectorAll("input[type=range][data-out]").forEach(function (r) {
      var out = document.getElementById(r.getAttribute("data-out"));
      // à la française : « 0,5 », pas « 0.5 » (la valeur envoyée, elle, garde son point)
      r.addEventListener("input", function () { if (out) out.textContent = String(r.value).replace(".", ","); });
    });

    // Vitaux : rafraîchis toutes les 10 s, en pause quand l'onglet est caché.
    var bar = document.querySelector("[data-vitals]");
    if (bar && window.fetch) {
      var url = bar.getAttribute("data-vitals");
      var live = document.querySelector("[data-vitals-live]");
      var delay = 10000;
      var tick = function () {
        if (document.hidden) { setTimeout(tick, delay); return; }
        var ctl = new AbortController();
        var timer = setTimeout(function () { ctl.abort(); }, 8000);
        fetch(url, { credentials: "same-origin", signal: ctl.signal, headers: { "Accept": "text/html" } })
          .then(function (r) {
            clearTimeout(timer);
            if (r.status === 401 || r.status === 303) throw new Error("session");
            if (!r.ok) throw new Error(String(r.status));
            return r.text();
          })
          .then(function (html) {
            var box = document.querySelector("[data-vitals-items]");
            // Fragment rendu par le serveur (échappé par Jinja), jamais du texte extérieur brut.
            if (box) box.innerHTML = html;
            if (live) live.textContent = "à jour";
            delay = 10000;
            setTimeout(tick, delay);
          })
          .catch(function (e) {
            if (live) live.textContent = e.message === "session" ? "session expirée" : "hors ligne";
            if (e.message === "session") return;
            delay = Math.min(delay * 2, 120000);
            setTimeout(tick, delay);
          });
      };
      setTimeout(tick, delay);
    }
  });
})();
