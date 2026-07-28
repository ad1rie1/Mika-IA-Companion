/* ============================================================================
   GestionSystème — amélioration progressive
   ----------------------------------------------------------------------------
   Tout ce qui compte est rendu par le serveur. Ce fichier n'ajoute que du
   confort : sans lui, chaque page reste navigable, chaque formulaire reste
   soumettable, chaque tableau reste paginé.

   Ce qu'il ne fait PAS, volontairement :
     - aucun rendu de gabarit (plus de `innerHTML` sur des données) ;
     - aucun jeton CSRF à rattacher (les formulaires portent {% csrf_token %},
       il n'y a plus de `fetch` mutant à signer) ;
     - aucun état de navigation en localStorage (onglets et filtres sont dans
       l'URL, donc partageables et compatibles retour arrière).
   ========================================================================== */
(function () {
  "use strict";

  var THEME_KEY = "gestion.theme";

  /* ── Thème ───────────────────────────────────────────────────────────
     La valeur est appliquée par un script en ligne dans <head> (avant le
     premier rendu, pour éviter un flash clair sur un thème sombre). Ici on
     ne câble que les boutons. */
  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "light" || mode === "dark") {
      root.setAttribute("data-theme", mode);
    } else {
      root.removeAttribute("data-theme");
    }
    try {
      if (mode) localStorage.setItem(THEME_KEY, mode);
      else localStorage.removeItem(THEME_KEY);
    } catch (e) { /* mode privé : le thème ne survit pas, tant pis */ }

    var buttons = document.querySelectorAll("[data-theme-set]");
    for (var i = 0; i < buttons.length; i++) {
      var b = buttons[i];
      b.setAttribute("aria-pressed", b.dataset.themeSet === (mode || "auto") ? "true" : "false");
    }
  }

  function wireTheme() {
    var stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (e) { /* idem */ }
    applyTheme(stored);

    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-theme-set]");
      if (!btn) return;
      var mode = btn.dataset.themeSet;
      applyTheme(mode === "auto" ? null : mode);
    });
  }

  /* ── Confirmation des actions destructrices ─────────────────────────
     `data-confirm` sur un <form> : la soumission demande confirmation.
     Le serveur revalide de toute façon — ceci évite le clic malheureux,
     ce n'est pas un contrôle d'accès. */
  function wireConfirm() {
    document.addEventListener("submit", function (ev) {
      var form = ev.target;
      if (!form.matches || !form.matches("form[data-confirm]")) return;
      if (!window.confirm(form.dataset.confirm)) {
        ev.preventDefault();
      }
    });
  }

  /* ── Filtres ─────────────────────────────────────────────────────────
     Un <select> dans une barre de filtres soumet son formulaire au
     changement. Sans JS, le bouton « Filtrer » reste présent et fait le
     même travail. */
  function wireFilters() {
    document.addEventListener("change", function (ev) {
      var el = ev.target;
      if (!el.matches || !el.matches(".filters [data-autosubmit]")) return;
      var form = el.form;
      if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }

  /* ── Indicateurs vitaux ──────────────────────────────────────────────
     Rafraîchit la barre supérieure sans recharger la page. Rendu serveur
     au premier chargement : si ce script échoue, les valeurs sont juste
     figées à l'instant du rendu, jamais absentes. */
  function wireVitals() {
    var bar = document.querySelector("[data-vitals]");
    if (!bar) return;
    var url = bar.dataset.vitals;
    var period = parseInt(bar.dataset.vitalsInterval || "10000", 10);
    if (!url || !(period > 0)) return;

    var stopped = false;

    function paint(d) {
      for (var key in d) {
        if (!Object.prototype.hasOwnProperty.call(d, key)) continue;
        var slot = bar.querySelector('[data-vital="' + key + '"]');
        // textContent, jamais innerHTML : la charge utile vient du serveur
        // mais rien n'oblige un futur champ à être sûr en balisage.
        if (slot) slot.textContent = d[key];
      }
    }

    function tick() {
      if (stopped) return;
      fetch(url, { credentials: "same-origin", headers: { "Accept": "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d) paint(d); })
        .catch(function () { /* réseau coupé : on garde le dernier état affiché */ })
        .then(function () { if (!stopped) window.setTimeout(tick, period); });
    }

    // Ne pas sonder un onglet en arrière-plan : sur une installation
    // personnelle, c'est une requête toutes les 10 s pour une page que
    // personne ne regarde.
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) { stopped = true; }
      else if (stopped) { stopped = false; tick(); }
    });

    window.setTimeout(tick, period);
  }

  function init() {
    wireTheme();
    wireConfirm();
    wireFilters();
    wireVitals();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
