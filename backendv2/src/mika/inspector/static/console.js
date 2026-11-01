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
    // Sur un écran étroit, les rubriques passent dans un panneau (ADR 0176) : la case #nav-open l'ouvre, sans script
    // aussi ; avec lui, le bouton Menu, le focus gardé dans le panneau et Échap.
    var toggle = document.querySelector("[data-nav-toggle]");
    var panel = document.querySelector("#navigation");
    var checkbox = document.querySelector("#nav-open");
    if (!toggle || !panel || !checkbox) return function () {};
    var mobile = window.matchMedia("(max-width: 1080px)");
    var content = document.querySelector(".content");
    var side = document.querySelector(".topbar-side");
    var close = panel.querySelector("[data-nav-close]");
    checkbox.tabIndex = -1;
    toggle.hidden = false;
    close.hidden = false;
    function setOpen(open, restoreFocus) {
      checkbox.checked = mobile.matches && open;
      panel.inert = mobile.matches && !checkbox.checked;
      if (content) content.inert = checkbox.checked;
      if (side) side.inert = checkbox.checked;
      toggle.setAttribute("aria-expanded", String(checkbox.checked));
      document.body.classList.toggle("nav-is-open", checkbox.checked);
      if (checkbox.checked) {
        // la rubrique de la page courante, dépliée dans le panneau
        panel.querySelectorAll(".nav-group.active").forEach(function (g) { g.open = true; });
        close.focus();
      } else if (restoreFocus) toggle.focus();
    }
    toggle.addEventListener("click", function () { setOpen(true); });
    close.addEventListener("click", function () { setOpen(false, true); });
    checkbox.addEventListener("change", function () { setOpen(checkbox.checked, true); });
    mobile.addEventListener("change", function () {
      panel.querySelectorAll(".nav-group").forEach(function (g) { g.open = false; });
      setOpen(false);
    });
    document.addEventListener("keydown", function (ev) {
      if (!checkbox.checked) return;
      if (ev.key === "Escape") { ev.preventDefault(); setOpen(false, true); }
      if (ev.key === "Tab") {
        var focusable = Array.from(panel.querySelectorAll("a, button, input, summary"))
          .filter(function (el) { return !el.disabled && el.checkVisibility(); });
        var first = focusable[0], last = focusable[focusable.length - 1];
        if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
        else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
      }
    });
    setOpen(false);
    return function () { if (mobile.matches) setOpen(true); };
  }

  // Les menus de la barre du haut (les rubriques, son état, le compte) : un seul ouvert à la fois ; un clic ailleurs
  // ou Échap le ferme ; sur un écran large, survoler une autre rubrique quand un menu est ouvert passe à la sienne.
  function setupTopMenus() {
    var wide = window.matchMedia("(min-width: 1081px)");
    var menus = Array.from(document.querySelectorAll(".topbar .nav-group, .topbar .topbar-pop"));
    function closeAll(except) { menus.forEach(function (m) { if (m !== except) m.open = false; }); }
    menus.forEach(function (m) {
      m.addEventListener("toggle", function () { if (m.open && wide.matches) closeAll(m); });
      if (m.classList.contains("nav-group")) {
        var hovered = 0;
        m.addEventListener("mouseenter", function () {
          if (!wide.matches || m.open) return;
          if (menus.some(function (o) { return o.open && o.classList.contains("nav-group"); })) {
            closeAll(m); m.open = true; hovered = Date.now();
          }
        });
        // le clic qui suit l'ouverture au survol ne referme pas le menu qu'on vient d'atteindre
        m.querySelector("summary").addEventListener("click", function (ev) {
          if (hovered && Date.now() - hovered < 800) ev.preventDefault();
          hovered = 0;
        });
      }
    });
    document.addEventListener("click", function (ev) {
      if (!wide.matches && ev.target.closest("#navigation")) return;
      menus.forEach(function (m) {
        if (m.open && !m.contains(ev.target) && (wide.matches || !m.classList.contains("nav-group"))) m.open = false;
      });
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      menus.forEach(function (m) {
        if (!m.open || (!wide.matches && m.classList.contains("nav-group"))) return;
        var inside = m.contains(document.activeElement);
        m.open = false;
        if (inside) m.querySelector("summary").focus();
      });
    });
  }

  // « Aller à… » (ADR 0176) : sous la recherche, les pages de la console qui répondent à ce qu'on tape (les liens des
  // rubriques et leur ligne d'explication, sans tenir compte des accents), puis « Chercher partout ». Flèches, Entrée,
  // Échap ; Ctrl K ou « / » y mènent. Sans script, le formulaire envoie à la recherche globale.
  function setupGoto() {
    var form = document.querySelector("form[data-goto]");
    var input = document.querySelector("#q-global");
    if (!form || !input) return;
    var fold = function (t) { return t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
    var pages = Array.from(document.querySelectorAll("#navigation a.nav-item")).map(function (a) {
      var group = a.closest(".nav-group");
      var label = a.querySelector(".nav-item-label");
      var hint = a.querySelector(".nav-item-hint");
      var name = label ? label.firstChild.textContent.trim() : a.textContent.trim();
      var section = group ? group.getAttribute("data-nav-group") : "";
      return { href: a.getAttribute("href"), name: name, hint: hint ? hint.textContent.trim() : "", section: section,
               key: fold(name + " " + (hint ? hint.textContent : "") + " " + section) };
    });
    var list = document.createElement("div");
    list.className = "goto-list";
    list.id = "goto-list";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Aller à");
    list.hidden = true;
    form.appendChild(list);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-controls", "goto-list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");
    var items = [], selected = 0;
    function render() {
      var q = fold(input.value.trim());
      var words = q.split(/\s+/).filter(Boolean);
      var found = pages.filter(function (p) { return words.every(function (w) { return p.key.indexOf(w) !== -1; }); });
      if (!words.length) found = [];
      found = found.slice(0, 9);
      items = found.map(function (p) { return { href: p.href, name: p.name, hint: p.hint, section: p.section }; });
      if (input.value.trim()) items.push({ search: true, name: "Chercher « " + input.value.trim() + " » partout", hint: "personnes, projets, souvenirs, réglages…" });
      selected = Math.min(selected, Math.max(0, items.length - 1));
      list.textContent = "";
      if (!items.length) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
      if (found.length) {
        var head = document.createElement("div"); head.className = "goto-group"; head.textContent = "Pages de la console";
        list.appendChild(head);
      }
      items.forEach(function (it, i) {
        var el = document.createElement(it.search ? "div" : "a");
        el.className = "goto-item";
        el.id = "goto-" + i;
        el.setAttribute("role", "option");
        el.setAttribute("aria-selected", String(i === selected));
        if (it.href) el.href = it.href;
        var b = document.createElement("b"); b.textContent = it.name; el.appendChild(b);
        if (it.hint) { var d = document.createElement("span"); d.className = "d"; d.textContent = it.hint; el.appendChild(d); }
        if (it.section) { var s = document.createElement("span"); s.className = "s"; s.textContent = it.section; el.appendChild(s); }
        el.addEventListener("mousedown", function (ev) { ev.preventDefault(); choose(i); });
        if (it.search && found.length) {
          var head2 = document.createElement("div"); head2.className = "goto-group"; head2.textContent = "Ailleurs";
          list.appendChild(head2);
        }
        list.appendChild(el);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-activedescendant", "goto-" + selected);
    }
    function choose(i) {
      var it = items[i];
      if (!it) return;
      if (it.search) form.submit(); else window.location = it.href;
    }
    function hide() { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); }
    input.addEventListener("input", function () { selected = 0; render(); });
    input.addEventListener("focus", function () { if (input.value.trim()) render(); });
    input.addEventListener("blur", function () { setTimeout(hide, 120); });
    input.addEventListener("keydown", function (ev) {
      if (list.hidden) return;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        selected = (selected + (ev.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        render();
        var el = document.getElementById("goto-" + selected);
        if (el) el.scrollIntoView({ block: "nearest" });
      } else if (ev.key === "Enter" && items[selected] && !items[selected].search) {
        ev.preventDefault();
        choose(selected);
      } else if (ev.key === "Escape") { ev.preventDefault(); hide(); }
    });
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
        bar.classList.toggle("is-dirty", dirty);
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
    // une page en sous-onglets (une section par ancre, ``data-pane``, ADR 0176) : montrer celle du champ
    var pane = input.closest("[data-pane][id]");
    if (pane && !pane.checkVisibility()) {
      location.replace("#" + pane.id);
      window.dispatchEvent(new Event("hashchange"));  // les sous-onglets montrent la section avant le focus
    }
    input.focus();
  }

  // Les pages en sous-onglets (``data-pane``, ADR 0176) : la section ouverte (l'ancre de l'adresse) se retrouve après un
  // enregistrement, qui revient sans ancre ; sans script, la page revient sur sa première section.
  function setupPanes() {
    var panes = document.querySelectorAll("[data-pane][id]");
    if (!panes.length) return;
    var key = "mika.console.pane:" + location.pathname;
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function () {
        var open = location.hash && document.getElementById(location.hash.slice(1));
        try {
          if (open && open.hasAttribute("data-pane")) sessionStorage.setItem(key, open.id);
          else sessionStorage.removeItem(key);
        } catch (e) { /* stockage indisponible */ }
      });
    });
    var kept = null;
    try { kept = sessionStorage.getItem(key); sessionStorage.removeItem(key); } catch (e) { /* stockage indisponible */ }
    if (!location.hash && kept && document.getElementById(kept)) location.replace("#" + kept);
  }

  // Des sous-onglets (``[data-subtabs]``, ADR 0176) : la section de l'ancre (ou celle qui contient l'élément visé), la
  // première sinon ; les autres masquées, son lien marqué. Un clic change l'ancre sans faire sauter la page ; Précédent
  // revient à la section d'avant. Sans script, les sections se suivent.
  function setupSubtabs() {
    document.querySelectorAll("[data-subtabs]").forEach(function (box) {
      var panes = Array.from(box.querySelectorAll("[data-pane][id]")).filter(function (p) {
        return p.parentElement.closest("[data-subtabs]") === box;
      });
      if (!panes.length) return;
      var links = Array.from(box.querySelectorAll(".hm-subnav a[href^='#']"));
      function show() {
        var target = location.hash.length > 1 ? document.getElementById(decodeURIComponent(location.hash.slice(1))) : null;
        var on = panes.find(function (p) { return target && p.contains(target); }) || panes[0];
        panes.forEach(function (p) { p.hidden = p !== on; });
        links.forEach(function (a) {
          if (a.getAttribute("href") === "#" + on.id) a.setAttribute("aria-current", "true");
          else a.removeAttribute("aria-current");
        });
      }
      links.forEach(function (a) {
        a.addEventListener("click", function (ev) {
          if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;
          ev.preventDefault();
          history.pushState(null, "", a.getAttribute("href"));
          show();
          var top = box.getBoundingClientRect().top;
          if (top < 0) box.scrollIntoView({ block: "start" });
        });
      });
      window.addEventListener("hashchange", show);
      window.addEventListener("popstate", show);
      show();
    });
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
    setupNavigation();
    setupTopMenus();
    setupGoto();
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

    // « / » ou Ctrl K : « Aller à… ».
    var search = document.querySelector("#q-global");
    document.addEventListener("keydown", function (ev) {
      var t = ev.target;
      var slash = ev.key === "/" && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !t.isContentEditable &&
        !(t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement);
      var ctrlK = (ev.ctrlKey || ev.metaKey) && !ev.altKey && (ev.key === "k" || ev.key === "K");
      if (search && !ev.defaultPrevented && (slash || ctrlK)) {
        ev.preventDefault();
        search.focus();
        search.select();
      }
    });

    // Champs conditionnels : data-only="chemin=v1|v2;chemin2!=v" (toutes ; « != » : n'en vaut aucune),
    // alternatives « || » (l'une).
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
        var not = i > 0 && part.charAt(i - 1) === "!";
        var v = valueOf(form, part.slice(0, not ? i - 1 : i));
        if (v === null) return true;
        return (part.slice(i + 1).split("|").indexOf(v) !== -1) !== not;
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
    // à la frappe aussi : un champ qui en fait paraître d'autres une fois rempli (le serveur d'envoi d'une boîte)
    document.querySelectorAll("select, input").forEach(function (i) {
      i.addEventListener("change", syncOnly);
      if (i.type !== "checkbox" && i.type !== "radio") i.addEventListener("input", syncOnly);
    });
    syncOnly();
    setupPanes();
    setupSubtabs();
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

    // Un mail dans son cadre (ADR 0169) : le cadre prend la hauteur de son contenu. Sans script, il garde sa
    // hauteur fixe et défile.
    var frames = document.querySelectorAll("iframe.document-frame");
    var fit = function (frame) {
      var doc;
      try { doc = frame.contentDocument; } catch (e) { return; }
      if (!doc || !doc.documentElement) return;
      frame.style.height = "0px";
      frame.style.height = Math.max(doc.documentElement.scrollHeight, 80) + "px";
    };
    frames.forEach(function (frame) {
      frame.addEventListener("load", function () { fit(frame); });
      if (frame.contentDocument && frame.contentDocument.readyState === "complete") fit(frame);
    });
    if (frames.length) {
      var resized = 0;
      window.addEventListener("resize", function () {
        clearTimeout(resized);
        resized = setTimeout(function () { frames.forEach(fit); }, 150);
      });
    }

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
            var digest = box && box.querySelector(".vitals-digest");
            if (digest) {
              var said = document.querySelector("[data-status-digest]");
              var alerts = document.querySelector("[data-status-alerts]");
              var mood = document.querySelector("[data-status-mood]");
              if (said) said.textContent = digest.getAttribute("data-digest");
              if (alerts) {
                var n = Number(digest.getAttribute("data-alerts") || 0);
                alerts.hidden = !n;
                alerts.querySelector("span").textContent = String(n);
              }
              if (mood) mood.className = "mood " + (digest.getAttribute("data-mood") || "");
            }
            if (live) { live.textContent = ""; live.classList.remove("t-warn"); }
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
