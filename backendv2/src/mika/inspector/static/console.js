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
    document.querySelectorAll("[data-theme-set]").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.getAttribute("data-theme-set");
        try { localStorage.setItem(KEY, v); } catch (e) { /* navigation privée */ }
        applyTheme(v);
      });
    });

    // Confirmations : le serveur revérifie de toute façon.
    document.querySelectorAll("form[data-confirm]").forEach(function (f) {
      f.addEventListener("submit", function (ev) {
        if (!window.confirm(f.getAttribute("data-confirm"))) ev.preventDefault();
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

    // Champs conditionnels : data-only="chemin=valeur1|valeur2".
    function syncOnly() {
      document.querySelectorAll("[data-only]").forEach(function (el) {
        var spec = el.getAttribute("data-only").split("=");
        var input = document.querySelector('[name="' + spec[0] + '"]');
        if (!input) return;
        el.hidden = spec[1].split("|").indexOf(input.value) === -1;
      });
    }
    document.querySelectorAll("select, input").forEach(function (i) { i.addEventListener("change", syncOnly); });
    syncOnly();

    // Curseurs : la valeur à côté.
    document.querySelectorAll("input[type=range][data-out]").forEach(function (r) {
      var out = document.getElementById(r.getAttribute("data-out"));
      r.addEventListener("input", function () { if (out) out.textContent = r.value; });
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
