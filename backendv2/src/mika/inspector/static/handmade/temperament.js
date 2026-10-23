/* Réglages › Personnage › Tempérament (app/handmade/temperament.py) : changer de profil montre la différence sur la figure, sans
   rien remplir — seul « Pré-remplir » met ses valeurs dans le formulaire. Le sommet le plus proche de la souris (ou
   atteint au clavier, ou touché) dit sa valeur dans une bulle, une seule, posée par-dessus tout : les sommets se
   serrent près du centre, aucun ne cache son voisin. Sans ce script, la page marche :
   « Pré-remplir » montre et remplit d'un coup, et chaque sommet garde son nom et sa valeur pour un lecteur d'écran. */
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
