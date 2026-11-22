/* L'éditeur d'une page de documentation de projet, dans la console (ADR 0297 ; handmade/projets/_editeur.html).
 *
 * Il augmente un champ ordinaire — sans lui, le champ et « Enregistrer » suffisent :
 * - une barre d'outils qui agit sur la sélection (titres, gras, italique, barré, code, listes, tâches, lien, image,
 *   tableau, bloc de code, citation, séparateur) et ses raccourcis (Ctrl+B, Ctrl+I, Ctrl+K, Ctrl+S) ;
 * - « Écrire | Aperçu | Les deux » : l'aperçu est rendu par le moteur (POST /admin/apercu/project/<n>), comme la page
 *   le sera — une seule façon de rendre une page ;
 * - l'insertion d'une image de l'espace, là où est le curseur ;
 * - le brouillon gardé le temps d'un envoi (sessionStorage) : refusé — un conflit, une borne —, l'éditeur revient
 *   avec le texte tapé, et le dit ; enregistré, il s'efface ;
 * - ce qui n'est pas enregistré se dit, et quitter la page le demande — le texte revenu après un refus compris ;
 * - la zone de saisie s'arrête au-dessus de la bande du bas, qui ne la recouvre jamais.
 * Ailleurs dans la fiche : copier une référence (``[data-copy]``), et un formulaire dont le retour suit un champ
 * (``[data-goto-field]`` : la page créée, renommée ou déplacée s'ouvre).
 */
(function () {
  "use strict";

  function store() {
    try { return window.sessionStorage; } catch (e) { return null; }
  }

  function keep(key, value) {
    var s = store();
    if (!s || !key) return;
    try { s.setItem(key, JSON.stringify(value)); } catch (e) { /* plein, ou interdit : tant pis */ }
  }

  function kept(key) {
    var s = store();
    if (!s || !key) return null;
    try { return JSON.parse(s.getItem(key) || "null"); } catch (e) { return null; }
  }

  function drop(key) {
    var s = store();
    if (s && key) { try { s.removeItem(key); } catch (e) { /* rien */ } }
  }

  /* ── La sélection ─────────────────────────────────────────────────── */

  function wrap(area, before, after, empty) {
    var a = area.selectionStart, b = area.selectionEnd, v = area.value;
    var inner = v.slice(a, b) || empty;
    area.setRangeText(before + inner + after, a, b, "end");
    area.setSelectionRange(a + before.length, a + before.length + inner.length);
  }

  function lines(area, prefix) {
    var v = area.value, a = area.selectionStart, b = area.selectionEnd;
    var start = v.lastIndexOf("\n", a - 1) + 1, end = v.indexOf("\n", b);
    if (end < 0) end = v.length;
    var n = 0;
    var out = v.slice(start, end).split("\n").map(function (line) {
      n += 1;
      var p = typeof prefix === "function" ? prefix(n) : prefix;
      var bare = line.replace(/^(\s*)(#{1,6} |[-*] \[[ xX]\] |[-*] |\d+\. |> )/, "$1");
      return line.indexOf(p) === 0 ? bare : p + bare;
    }).join("\n");
    area.setRangeText(out, start, end, "select");
  }

  function block(area, text) {
    var a = area.selectionStart, v = area.value;
    var before = a > 0 && v[a - 1] !== "\n" ? "\n\n" : (a > 1 && v[a - 2] !== "\n" ? "\n" : "");
    area.setRangeText(before + text + "\n", a, area.selectionEnd, "end");
  }

  function heading(area, level) {
    var n = parseInt(level, 10) || 0;
    lines(area, n ? new Array(n + 1).join("#") + " " : "");
    if (!n) {
      var v = area.value, a = area.selectionStart, b = area.selectionEnd;
      area.setRangeText(v.slice(a, b).replace(/^#{1,6} /gm, ""), a, b, "select");
    }
  }

  var ACTIONS = {
    bold: function (t) { wrap(t, "**", "**", "gras"); },
    italic: function (t) { wrap(t, "*", "*", "italique"); },
    strike: function (t) { wrap(t, "~~", "~~", "barré"); },
    code: function (t) { wrap(t, "`", "`", "code"); },
    ul: function (t) { lines(t, "- "); },
    ol: function (t) { lines(t, function (n) { return n + ". "; }); },
    task: function (t) { lines(t, "- [ ] "); },
    quote: function (t) { lines(t, "> "); },
    link: function (t) { wrap(t, "[", "](autre-page.md)", "texte du lien"); },
    codeblock: function (t) { var a = t.selectionStart, b = t.selectionEnd; block(t, "```\n" + (t.value.slice(a, b) || "code") + "\n```"); },
    rule: function (t) { block(t, "---"); },
    table: function (t) { block(t, "| Colonne | Colonne |\n| --- | --- |\n| … | … |"); }
  };

  /* ── Un éditeur ───────────────────────────────────────────────────── */

  function editor(root) {
    var area = root.querySelector("[data-ed-text]");
    var form = root.querySelector("#pj-ed-form");
    if (!area || !form) return;
    var key = root.getAttribute("data-draft") || "";
    var state = root.querySelector("[data-ed-state]");
    var preview = root.querySelector("[data-ed-preview]");
    var zone = root.querySelector("[data-ed-area]");
    var bar = root.querySelector("[data-ed-bar]");
    var word = form.querySelector("[name=word]");
    var path = form.querySelector("[name=path]:not([type=hidden])");
    var foot = root.querySelector(".pj-ed-foot");
    var sending = false, timer = null, asked = 0, mode = "ecrire";
    // ce que la page a servi : le texte enregistré. Lu avant de remettre un brouillon — le texte revenu après un
    // refus n'est pas enregistré, et quitter la page le demande
    var start = area.value;
    // ce que l'éditeur dit tant qu'on n'a rien retapé : le texte revenu
    var note = "";

    if (bar) bar.hidden = false;
    if (root.hasAttribute("data-restore")) {
      var d = kept(key) || (path ? kept(key + (path.value || "")) : null);
      if (d && typeof d.text === "string") {
        area.value = d.text;
        if (word && d.word) word.value = d.word;
        if (path && d.path) path.value = d.path;
        note = "Ton texte, pas encore enregistré, est revenu dans l'éditeur.";
      }
    }

    function dirty() { return area.value !== start; }

    function said() {
      if (!state) return;
      state.textContent = dirty() ? (note || "Modifiée, pas encore enregistrée.") : "";
      root.classList.toggle("modifiee", dirty());
    }

    // la zone de saisie tient au-dessus de la bande du bas (« Un mot… », « Enregistrer ») : sur un grand écran, sa
    // hauteur va jusqu'à la bande, que rien ne recouvre ; trop peu de place, la bande reste à sa place, sous la zone
    // (projets_docs.css : --pj-ed-h, .serre). Sur un téléphone, la feuille seule la règle.
    var wide = window.matchMedia ? window.matchMedia("(min-width: 761px)") : null;
    function fit() {
      if (!zone || !foot) return;
      if (!wide || !wide.matches) {
        root.style.removeProperty("--pj-ed-h");
        root.classList.remove("serre");
        return;
      }
      var top = zone.getBoundingClientRect().top + window.scrollY;
      var room = Math.floor(window.innerHeight - top - foot.offsetHeight - 12);
      root.style.setProperty("--pj-ed-h", Math.max(room, 240) + "px");
      root.classList.toggle("serre", room < 240);
    }

    function render() {
      if (!preview || preview.hidden) return;
      var mine = ++asked;
      var data = new FormData();
      data.append("csrf", root.getAttribute("data-csrf") || "");
      data.append("text", area.value);
      data.append("chemin", (path && path.value) || root.getAttribute("data-where") || "");
      fetch(root.getAttribute("data-preview"), { method: "POST", body: data, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
        .then(function (html) { if (mine === asked) preview.innerHTML = html; })
        .catch(function () { if (mine === asked) preview.textContent = "L'aperçu ne se rend pas pour l'instant."; });
    }

    function setMode(next) {
      mode = next;
      root.querySelectorAll("[data-ed-mode]").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-ed-mode") === next ? "true" : "false");
      });
      area.hidden = next === "apercu";
      if (preview) preview.hidden = next === "ecrire";
      if (zone) zone.classList.toggle("deux", next === "deux");
      render();
    }

    function act(name) {
      area.focus();
      if (name === "image") {
        var list = document.getElementById("pj-ed-images");
        if (list && list.querySelector("[data-insert]")) {
          var box = document.getElementById("pj-infos");
          if (box) box.checked = true;
          list.scrollIntoView({ block: "nearest" });
          list.querySelector("[data-insert]").focus();
        } else {
          wrap(area, "![", "](images/nom.png)", "texte");
        }
      } else if (ACTIONS[name]) {
        ACTIONS[name](area);
      }
      area.dispatchEvent(new Event("input"));
    }

    root.querySelectorAll("[data-md]").forEach(function (el) {
      if (el.tagName === "SELECT") {
        el.addEventListener("change", function () { area.focus(); heading(area, el.value); el.value = "0"; area.dispatchEvent(new Event("input")); });
      } else {
        el.addEventListener("click", function () { act(el.getAttribute("data-md")); });
      }
    });
    root.querySelectorAll("[data-ed-mode]").forEach(function (b) {
      b.addEventListener("click", function () { setMode(b.getAttribute("data-ed-mode")); });
    });
    root.querySelectorAll("[data-insert]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (area.hidden) setMode("deux");
        area.focus();
        block(area, b.getAttribute("data-insert"));
        area.dispatchEvent(new Event("input"));
      });
    });
    area.addEventListener("keydown", function (ev) {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      var k = ev.key.toLowerCase();
      var map = { b: "bold", i: "italic", k: "link" };
      if (map[k]) { ev.preventDefault(); act(map[k]); }
      if (k === "s") { ev.preventDefault(); if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
    });
    area.addEventListener("input", function () {
      note = "";
      said();
      if (mode !== "ecrire") { clearTimeout(timer); timer = setTimeout(render, 450); }
    });
    // tout envoi depuis l'éditeur (enregistrer, téléverser une image) garde le texte tapé : refusé, il revient
    root.querySelectorAll("form").forEach(function (f) {
      f.addEventListener("submit", function () {
        sending = true;
        var d = { text: area.value, word: word ? word.value : "", path: path ? path.value : "" };
        keep(key, d);
        if (path && path.value) keep(key + path.value, d);
      });
    });
    window.addEventListener("beforeunload", function (ev) {
      if (!sending && dirty()) { ev.preventDefault(); ev.returnValue = ""; }
    });
    setMode(window.matchMedia && window.matchMedia("(min-width: 1240px)").matches ? "deux" : "ecrire");
    said();
    fit();
    window.addEventListener("resize", fit);
  }

  function ready() {
    document.querySelectorAll("[data-doc-saved]").forEach(function (el) {
      var key = el.getAttribute("data-doc-saved");
      drop(key);
    });
    document.querySelectorAll("[data-doc-editor]").forEach(editor);
    // un retour qui suit un champ : la page créée, renommée ou déplacée s'ouvre ; refusé, on revient sur celle d'où
    // l'on vient (``de``, le champ que nomme data-goto-from : la page lue par project_docs.pages_view)
    document.querySelectorAll("form[data-goto-field]").forEach(function (f) {
      f.addEventListener("submit", function () {
        var field = f.querySelector("[name='" + f.getAttribute("data-goto-field") + "']");
        var from = f.getAttribute("data-goto-from") ? f.querySelector("[name='" + f.getAttribute("data-goto-from") + "']") : null;
        var back = f.querySelector("[name=_retour]");
        if (!field || !back || !field.value) return;
        var url = back.value.replace(/([?&])(page|de)=[^&#]*/g, "$1").replace(/&&+/g, "&").replace(/[?&]+$/, "").replace("?&", "?");
        back.value = url + (url.indexOf("?") < 0 ? "?" : "&") + "page=" + encodeURIComponent(field.value.trim()) +
          (from && from.value ? "&de=" + encodeURIComponent(from.value) : "");
      });
    });
    document.querySelectorAll("[data-copy]").forEach(function (b) {
      var source = b.parentElement && b.parentElement.querySelector("[data-copy-source]");
      if (!source || !navigator.clipboard) return;
      b.hidden = false;
      b.addEventListener("click", function () {
        navigator.clipboard.writeText(source.value).then(function () {
          var was = b.lastChild.textContent;
          b.lastChild.textContent = "Copié";
          setTimeout(function () { b.lastChild.textContent = was; }, 1600);
        });
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
