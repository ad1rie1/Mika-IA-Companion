/* Réglages › Personnage › Tempérament (app/handmade/temperament.py) : changer de profil montre la différence sur la figure, sans
   rien remplir — seul « Pré-remplir » met ses valeurs dans le formulaire. Le sommet le plus proche de la souris (ou
   atteint au clavier, ou touché) dit sa valeur dans une bulle, une seule, posée par-dessus tout : les sommets se
   serrent près du centre, aucun ne cache son voisin. Sans ce script, la page marche :
   « Pré-remplir » montre et remplit d'un coup, et chaque sommet garde son nom et sa valeur pour un lecteur d'écran. */
/* Son caractère écrit (ADR 0139) : juste après un enregistrement (la page revient avec son message, « flash »), si le
   caractère est « en cours », une modale suit l'écriture — l'état de la section, toutes les deux secondes — et montre
   le texte quand il est là ; fermée, la page se recharge sans le message, seulement si le texte est arrivé. Jamais
   sur une page rendue après une erreur de saisie ou « Voir l'effet », ni à une simple visite : un caractère qui ne
   peut pas s'écrire (aucun modèle, quota retenu) se lit sur la carte, sans bloquer la page. Sans ce script, la carte
   dit « en cours » et se relit à la main. */
(function () {
  "use strict";
  var card = document.querySelector("[data-character]");
  var dialog = card && card.querySelector("[data-character-dialog]");
  if (!card || !dialog || card.getAttribute("data-character") !== "en_cours") return;
  if (typeof dialog.showModal !== "function" || !/[?&]flash=/.test(window.location.search)) return;
  var url = dialog.getAttribute("data-character-url");
  var status = dialog.querySelector("[data-character-status]");
  var text = dialog.querySelector("[data-character-text]");
  var bar = dialog.querySelector(".temper-progress");
  var started = Date.now(), timer = null, arrived = false;
  function finish(message) {
    bar.hidden = true;
    status.textContent = message;
  }
  function poll() {
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error(String(r.status))); })
      .then(function (d) {
        if (d.etat === "ecrit") {
          arrived = true;
          text.textContent = d.texte;
          text.hidden = false;
          finish("Écrit" + (d.modele ? " par " + d.modele : "") + ". C'est ce qu'elle lira d'elle, partout.");
          return;
        }
        if (d.retenu) {
          finish("L'appel n'est pas tenté : " + d.retenu + ". Elle réessaiera d'elle-même ; la carte le dira.");
          return;
        }
        if (Date.now() - started > 120000) {
          finish("Toujours rien après deux minutes : le modèle n'a pas répondu. Elle réessaie d'elle-même, de plus en plus espacé ; la carte le dira.");
          return;
        }
        timer = setTimeout(poll, 2000);
      })
      .catch(function () { finish("La console ne répond plus : recharge la page."); });
  }
  dialog.addEventListener("close", function () {
    if (timer) clearTimeout(timer);
    if (arrived) window.location.replace(window.location.pathname);
  });
  dialog.showModal();
  timer = setTimeout(poll, 1500);
})();

(function () {
  "use strict";
  var fig = document.querySelector("[data-temper]");
  var select = document.getElementById("temper-profil");
  if (!fig || !select) return;
  var svg = fig.querySelector("svg");
  var bubble = svg.querySelector("[data-temper-tip]");
  var data;
  try { data = JSON.parse(fig.getAttribute("data-temper")); } catch (e) { return; }

  function all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }
  function set(el, attrs) { Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); }); }

  // la vue d'un profil : la sienne devant la forme en place, ou la forme en place seule (son profil, ou un profil qui
  // ne change rien)
  function pick(key) {
    var proposed = key && key !== data.now ? data.profiles[key] : null;
    return proposed && proposed.before ? proposed : data.current;
  }
  var shown = pick(data.shown);
  var near = data.near || 22, on = null;

  function point(i) { return svg.querySelector('.temper-point[data-i="' + i + '"]'); }

  function tip(i) {
    var p = shown.points[i];
    if (!p || !bubble) return;
    if (on !== null && on !== i && point(on)) point(on).classList.remove("is-on");
    on = i;
    if (point(i)) point(i).classList.add("is-on");
    var t = p.tip, spans = bubble.querySelectorAll("tspan");
    set(bubble.querySelector("rect"), { x: t.x, y: t.y, width: t.w, height: t.h });
    bubble.querySelector("text").setAttribute("text-anchor", t.anchor);
    set(spans[0], { x: t.tx, y: t.t1 });
    set(spans[1], { x: t.tx, y: t.t2 });
    spans[0].textContent = t.lines[0];
    spans[1].textContent = t.lines[1];
    bubble.classList.add("on");
  }
  function untip() {
    if (bubble) bubble.classList.remove("on");
    if (on !== null && point(on)) point(on).classList.remove("is-on");
    on = null;
  }

  // la souris, en unités du dessin : le sommet le plus proche, s'il est assez près
  svg.addEventListener("mousemove", function (e) {
    var m = svg.getScreenCTM();
    if (!m) return;
    var pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    pt = pt.matrixTransform(m.inverse());
    var best = null, dist = near;
    shown.points.forEach(function (q, i) {
      var d = Math.sqrt((q.x - pt.x) * (q.x - pt.x) + (q.y - pt.y) * (q.y - pt.y));
      if (d < dist) { dist = d; best = i; }
    });
    if (best === null) untip();
    else if (best !== on) tip(best);
  });
  svg.addEventListener("mouseleave", untip);
  all(".temper-point").forEach(function (g) {
    var i = Number(g.getAttribute("data-i"));
    g.addEventListener("focus", function () { tip(i); });
    g.addEventListener("blur", untip);
  });

  function draw(view) {
    svg.querySelector(".temper-shape").setAttribute("points", view.shape);
    var before = svg.querySelector(".temper-before");
    before.setAttribute("points", view.before || "");
    before.classList.toggle("is-off", !view.before);
    view.points.forEach(function (p, i) {
      var g = point(i);
      if (!g) return;
      g.setAttribute("aria-label", p.title);
      g.querySelectorAll("circle").forEach(function (c) { set(c, { cx: p.x, cy: p.y }); });
    });
  }

  function show(key) {
    shown = pick(key);
    var comparing = shown !== data.current;
    untip();
    draw(shown);
    all("[data-temper-choice]").forEach(function (el) {
      el.textContent = shown.choices[Number(el.getAttribute("data-temper-choice"))] || "";
    });
    all("[data-temper-marked]").forEach(function (el) {
      el.textContent = shown.marked || "aucun trait nettement marqué, elle est au milieu partout";
    });
    all("[data-temper-name]").forEach(function (el) { el.textContent = data.labels[key] || ""; });
    all("[data-temper-legend], [data-temper-arrow]").forEach(function (el) { el.hidden = !comparing; });
    all("[data-temper-hint]").forEach(function (el) { el.hidden = key === (data.shown || ""); });
  }

  select.addEventListener("change", function () { show(select.value); });
})();
