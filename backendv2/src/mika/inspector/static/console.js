// La console de Mika : de petites améliorations, jamais nécessaires (tout marche sans).
// Chargé dans <head> : le thème est posé avant le premier affichage.
(function () {
  "use strict";
  var KEY = "mika.console.theme";
  // le dernier formulaire envoyé (son adresse et son rang), jamais ses valeurs
  var SENT_FORM = "mika.console.envoi";

  function readTheme() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : "auto";
    } catch (e) { return "auto"; }
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

  function setupNavigation() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var sidebar = document.querySelector(".sidebar");
    var checkbox = document.querySelector("#nav-open");
    if (!toggle || !sidebar || !checkbox) return function () {};
    var mobile = window.matchMedia("(max-width: 900px)");
    var main = document.querySelector(".main");
    var close = sidebar.querySelector("[data-nav-close]");
    checkbox.tabIndex = -1;
    toggle.hidden = false;
    close.hidden = false;
    function setOpen(open, restoreFocus) {
      checkbox.checked = mobile.matches && open;
      sidebar.inert = mobile.matches && !checkbox.checked;
      main.inert = checkbox.checked;
      toggle.setAttribute("aria-expanded", String(checkbox.checked));
      document.body.classList.toggle("nav-is-open", checkbox.checked);
      if (checkbox.checked) close.focus();
      else if (restoreFocus) toggle.focus();
    }
    toggle.addEventListener("click", function () { setOpen(true); });
    close.addEventListener("click", function () { setOpen(false, true); });
    checkbox.addEventListener("change", function () { setOpen(checkbox.checked, true); });
    mobile.addEventListener("change", function () { setOpen(false); });
    document.addEventListener("keydown", function (ev) {
      if (!checkbox.checked) return;
      if (ev.key === "Escape") { ev.preventDefault(); setOpen(false, true); }
      if (ev.key === "Tab") {
        var focusable = Array.from(sidebar.querySelectorAll("a, button, input, summary"))
          .filter(function (el) { return !el.disabled && el.checkVisibility(); });
        var first = focusable[0], last = focusable[focusable.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
      }
    });
    setOpen(false);

    // La rubrique courante reste dépliée ; les autres retrouvent le choix de l'opérateur.
    document.querySelectorAll("[data-nav-group]").forEach(function (group) {
      var key = "mika.console.nav." + group.getAttribute("data-nav-group");
      try {
        var stored = sessionStorage.getItem(key);
        if (stored !== null) group.open = stored === "true";
      } catch (e) { /* stockage indisponible */ }
      var current = !!group.querySelector('[aria-current="page"]');
      if (current) group.open = true;
      group.addEventListener("toggle", function () {
        if (current) return;  // dépliée d'office sur sa propre page : ce n'est pas le choix de l'opérateur
        try { sessionStorage.setItem(key, String(group.open)); } catch (e) { /* stockage indisponible */ }
      });
    });
    return function () { if (mobile.matches) setOpen(true); };
  }

  function setupFormStatus() {
    var edited = new Set();
    var forms = Array.from(document.forms);
    // Une page rendue en réponse à un envoi (« Voir l'effet », une valeur refusée) remontre des valeurs que rien
    // n'a enregistrées : le formulaire envoyé reste « non enregistré » dès son affichage.
    var sent = null;
    try {
      sent = JSON.parse(sessionStorage.getItem(SENT_FORM) || "null");
      sessionStorage.removeItem(SENT_FORM);
    } catch (e) { /* stockage indisponible */ }
    if (!document.body.hasAttribute("data-posted")) sent = null;
    document.querySelectorAll("form .form-actions, form .form-actions-inline").forEach(function (bar) {
      var form = bar.closest("form");
      var index = forms.indexOf(form);
      function signature() {
        return JSON.stringify(Array.from(new FormData(form), function (entry) {
          var v = entry[1];
          return [entry[0], v instanceof File ? (v.name ? [v.name, v.size, v.lastModified] : "") : v];
        }));
      }
      var initial = sent && sent.action === form.action && sent.index === index ? null : signature();
      var status = document.createElement("span");
      status.className = "form-status";
      status.setAttribute("role", "status");
      bar.appendChild(status);
      function update() {
        var dirty = initial === null || signature() !== initial;
        if (dirty) edited.add(form); else edited.delete(form);
        status.textContent = dirty ? "Modifications non enregistrées" : "";
      }
      form.addEventListener("input", update);
      form.addEventListener("change", update);
      form.addEventListener("submit", function (ev) {
        if (ev.defaultPrevented) return;
        edited.delete(form);
        try { sessionStorage.setItem(SENT_FORM, JSON.stringify({ action: form.action, index: index })); }
        catch (e) { /* stockage indisponible */ }
      });
      form.addEventListener("reset", function () { setTimeout(update, 0); });
      if (initial === null) update();
    });
    window.addEventListener("beforeunload", function (ev) {
      if (edited.size) { ev.preventDefault(); ev.returnValue = ""; }
    });
    // La validation native doit pouvoir atteindre un champ dans un détail replié.
    document.addEventListener("invalid", function (ev) {
      var parent = ev.target.parentElement;
      while (parent) {
        if (parent.tagName === "DETAILS") parent.open = true;
        parent = parent.parentElement;
      }
    }, true);
  }

  function revealField(input) {
    for (var parent = input.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
    input.focus();
  }

  function setupValidation() {
    var firstSummary = null;
    document.querySelectorAll("form").forEach(function (form) {
      var failures = Array.from(form.querySelectorAll(".field.has-error")).map(function (field) {
        var input = field.querySelector("input:not([type=hidden]):not(:disabled), select:not(:disabled), textarea:not(:disabled)");
        var error = field.querySelector(".error");
        return input && error ? { input: input, error: error } : null;
      }).filter(Boolean);
      if (!failures.length) return;
      var summary = document.createElement("div");
      summary.className = "form-error-summary";
      summary.setAttribute("role", "alert");
      summary.tabIndex = -1;
      var title = document.createElement("b");
      title.textContent = "À corriger avant d’enregistrer";
      summary.appendChild(title);
      var list = document.createElement("ul");
      failures.forEach(function (failure) {
        var input = failure.input;
        input.setAttribute("aria-invalid", "true");
        if (!failure.error.id) failure.error.id = input.id + "-error";
        var described = (input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
        if (!described.includes(failure.error.id)) described.push(failure.error.id);
        input.setAttribute("aria-describedby", described.join(" "));
        var item = document.createElement("li"), link = document.createElement("a");
        link.href = "#" + input.id;
        link.textContent = (input.labels && input.labels[0] ? input.labels[0].textContent.trim() + " : " : "") + failure.error.textContent;
        link.addEventListener("click", function (ev) { ev.preventDefault(); revealField(input); });
        item.appendChild(link); list.appendChild(item);
      });
      summary.appendChild(list); form.prepend(summary);
      if (!firstSummary) firstSummary = summary;
    });
    if (firstSummary) revealField(firstSummary);
  }

  ready(function () {
    applyTheme(readTheme());
    var openNavigation = setupNavigation();
    // Les longues rubriques restent accessibles sans prendre tout l'écran mobile.
    document.querySelectorAll("[data-responsive-menu]").forEach(function (menu) {
      var narrow = window.matchMedia(menu.getAttribute("data-responsive-menu") || "(max-width: 1100px)");
      function fitMenu() {
        var focused = menu.contains(document.activeElement);
        menu.open = !narrow.matches;
        if (focused && narrow.matches) menu.querySelector("summary").focus();
      }
      fitMenu();
      narrow.addEventListener("change", fitMenu);
    });
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

    // « / » pour chercher.
    var search = document.querySelector("#q-global");
    document.addEventListener("keydown", function (ev) {
      var t = ev.target;
      if (ev.key === "/" && search && !ev.defaultPrevented && !ev.ctrlKey && !ev.metaKey && !ev.altKey &&
          !t.isContentEditable && !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement ||
          t instanceof HTMLSelectElement)) {
        ev.preventDefault();
        openNavigation();
        search.focus();
      }
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
    var originalDisabled = new WeakMap();
    function syncOnly() {
      document.querySelectorAll("[data-only]").forEach(function (el) {
        var form = el.closest("form");
        el.hidden = !el.getAttribute("data-only").split("||").some(function (alt) { return holds(form, alt); });
        el.querySelectorAll("input, select, textarea, button").forEach(function (input) {
          if (!originalDisabled.has(input)) originalDisabled.set(input, input.disabled);
          input.disabled = el.hidden || originalDisabled.get(input);
        });
      });
    }
    document.querySelectorAll("select, input").forEach(function (i) { i.addEventListener("change", syncOnly); });
    syncOnly();
    setupFormStatus();
    setupValidation();

    // Un onglet actif hors du cadre mobile doit rester visible, sans déplacer la page.
    document.querySelectorAll('.tabs [aria-current="page"]').forEach(function (active) {
      var tabs = active.parentElement;
      var tabRect = active.getBoundingClientRect(), box = tabs.getBoundingClientRect();
      if (tabRect.right > box.right || tabRect.left < box.left) tabs.scrollLeft += tabRect.left - box.left;
    });

    // Tables et fiches : une ligne ou une fiche entière mène à sa page ; le détail se déplie par un chevron.
    document.querySelectorAll("table.tbl tr[data-href], .collection-item[data-href], .settings-record[data-href]").forEach(function (tr) {
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
    var pops = document.querySelectorAll("details[data-exclusive], details.action-overflow");
    pops.forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (!d.open) return;
        pops.forEach(function (o) { if (o !== d && !o.contains(d) && !d.contains(o)) o.open = false; });
        var first = d.querySelector("input:not([type=hidden]), select, textarea");
        if (first) first.focus();
      });
    });
    document.addEventListener("click", function (ev) {
      pops.forEach(function (d) { if (d.open && !d.contains(ev.target)) d.open = false; });
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") pops.forEach(function (d) {
        if (d.open && d.contains(document.activeElement)) d.querySelector("summary").focus();
        d.open = false;
      });
    });

    // Accès aux outils : « toujours » (ou « tous ») et les cases une à une s'excluent, comme à l'enregistrement, et le
    // bouton de la liste montre aussitôt ce qui est coché, comme le rend le serveur (``data-all``, ``data-none``). Sans
    // case « tous », c'est « qui » : une phrase, comme ``who_words`` (« Toi, tes proches en privé et Toto »).
    document.querySelectorAll("details.access-tools").forEach(function (d) {
      var said = d.querySelector("summary");
      var all = d.querySelector(".access-tool.all input");
      var items = Array.from(d.querySelectorAll(".access-tool:not(.all) input"));
      function sayWho() {
        var words = items.filter(function (i) { return i.checked; }).map(function (i) { return i.getAttribute("data-word"); });
        var text = words.length > 1 ? words.slice(0, -1).join(", ") + " et " + words[words.length - 1] : words.join("");
        said.textContent = text ? text.charAt(0).toUpperCase() + text.slice(1) : d.getAttribute("data-none");
      }
      if (!all) {
        sayWho();
        d.addEventListener("change", sayWho);
        return;
      }
      function say() {
        var on = all.checked ? [] : items.filter(function (i) { return i.checked; });
        said.textContent = all.checked ? d.getAttribute("data-all") : on.length ? "" : d.getAttribute("data-none");
        // un moment par son libellé, un outil par son nom
        on.forEach(function (i) {
          var code = i.parentNode.querySelector("code");
          var chip = document.createElement(code ? "code" : "span");
          chip.className = "access-chip";
          chip.textContent = code ? code.textContent : i.parentNode.textContent.trim();
          said.appendChild(chip);
        });
      }
      say();  // un navigateur qui rend, au rechargement, les cases cochées avant l'envoi
      d.addEventListener("change", function (ev) {
        if (ev.target === all && all.checked) items.forEach(function (i) { i.checked = false; });
        else if (ev.target !== all && ev.target.checked) all.checked = false;
        say();
      });
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
            if (r.status === 401 || r.status === 403 || r.redirected) throw new Error("session");
            if (!r.ok) throw new Error(String(r.status));
            return r.text();
          })
          .then(function (html) {
            var box = document.querySelector("[data-vitals-items]");
            // Fragment rendu par le serveur (échappé par Jinja), jamais du texte extérieur brut.
            if (box) box.innerHTML = html;
            if (live) { live.textContent = "À jour"; live.classList.remove("t-warn"); }
            delay = 10000;
            setTimeout(tick, delay);
          })
          .catch(function (e) {
            if (live) {
              live.textContent = "";
              live.classList.add("t-warn");
              if (e.message === "session") {
                var login = document.createElement("a");
                login.href = url.replace(/\/_vitals$/, "/connexion");
                login.textContent = "Session expirée · Se reconnecter";
                live.appendChild(login);
              } else live.textContent = "Actualisation interrompue · nouvel essai automatique";
            }
            if (e.message === "session") return;
            delay = Math.min(delay * 2, 120000);
            setTimeout(tick, delay);
          });
      };
      setTimeout(tick, delay);
    }
  });
})();
