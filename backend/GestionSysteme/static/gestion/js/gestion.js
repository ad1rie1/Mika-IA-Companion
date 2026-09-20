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
     Un contrôle marqué `data-autosubmit` soumet son formulaire au
     changement. Sans JS, le bouton « Filtrer » reste présent et fait le
     même travail.

     Le sélecteur ne se limite pas à `.filters` : la barre de configuration
     porte la même bascule sans être une barre de filtres de tableau, et
     restreindre au conteneur revenait à décider du comportement d'après
     l'endroit plutôt que d'après l'intention déclarée sur le contrôle. */
  function wireFilters() {
    if (window.matchMedia("(max-width: 700px)").matches) {
      document.querySelectorAll('[data-filter-panel][data-active="false"]').forEach(function (panel) {
        panel.open = false;
      });
    }
    document.addEventListener("change", function (ev) {
      var el = ev.target;
      if (!el.matches || !el.matches("[data-autosubmit]")) return;
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
    var timer = null;
    var inFlight = false;
    var indicator = document.querySelector("[data-refresh-status]");

    function schedule() {
      window.clearTimeout(timer);
      if (!document.hidden) timer = window.setTimeout(tick, period);
    }
    function tick() {
      if (document.hidden || inFlight) return;
      inFlight = true;
      var controller = new AbortController();
      var timeout = window.setTimeout(function () { controller.abort(); }, 8000);
      fetch(url, { credentials: "same-origin", signal: controller.signal,
                   headers: { "Accept": "application/json" } })
        .then(function (response) {
          if (!response.ok) throw new Error("Actualisation indisponible");
          return response.json();
        })
        .then(function (data) {
          ["status", "phase", "energy", "mood", "sleep"].forEach(function (key) {
            var slot = bar.querySelector('[data-vital="' + key + '"]');
            if (slot && data[key] != null) slot.textContent = data[key];
          });
          var dot = bar.querySelector(".dot");
          if (dot) dot.className = "dot " + (data.status === "en ligne" ? "dot-ok" : "dot-danger");
          var brand = document.querySelector(".brand-sub");
          if (brand && data.status != null) brand.textContent = data.status;
          if (indicator) {
            indicator.textContent = "À jour";
            indicator.title = "Actualisé à " + new Date().toLocaleTimeString("fr-FR");
            indicator.classList.remove("tone-warn");
          }
        })
        .catch(function () {
          if (indicator) {
            indicator.textContent = "Actualisation interrompue";
            indicator.title = "Les valeurs affichées sont celles du dernier chargement réussi.";
            indicator.classList.add("tone-warn");
          }
        })
        .finally(function () {
          window.clearTimeout(timeout);
          inFlight = false;
          schedule();
        });
    }
    document.addEventListener("visibilitychange", function () {
      window.clearTimeout(timer);
      if (!document.hidden) tick();
    });
    schedule();
  }

  function wireOutline() {
    var main = document.querySelector("main.content");
    if (!main) return;
    var headings = Array.from(main.querySelectorAll(".card-head > h3, .section-heading > h3"))
      .filter(function (heading) { return !heading.closest("details"); });
    if (headings.length < 4) return;
    var nav = document.createElement("nav");
    nav.className = "page-outline";
    nav.setAttribute("aria-label", "Dans cette page");
    var label = document.createElement("span");
    label.className = "page-outline-label";
    label.textContent = "Dans cette page";
    nav.appendChild(label);
    headings.forEach(function (heading, index) {
      if (!heading.id) heading.id = "section-" + (index + 1);
      var anchor = document.createElement("a");
      anchor.href = "#" + heading.id;
      anchor.textContent = heading.textContent.trim();
      nav.appendChild(anchor);
    });
    var tabs = main.querySelector(":scope > .tabs");
    var head = main.querySelector(":scope > .page-head");
    var before = tabs || head;
    if (before) before.insertAdjacentElement("afterend", nav);
  }

  function wireNavigation() {
    document.querySelectorAll(".tabs").forEach(function (tabs) {
      var active = tabs.querySelector('[aria-current="page"]');
      if (active && tabs.scrollWidth > tabs.clientWidth) {
        tabs.scrollLeft = active.offsetLeft - tabs.offsetLeft - 16;
      }
    });
    var toggle = document.getElementById("nav-toggle");
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle && toggle.checked) {
        toggle.checked = false;
        toggle.focus();
      }
    });
  }

  function init() {
    wireTheme();
    wireConfirm();
    wireFilters();
    wireVitals();
    wireOutline();
    wireNavigation();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
