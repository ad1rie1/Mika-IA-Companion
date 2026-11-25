// Relations & échanges › Agendas › Tous les agendas (ADR 0309, lot 5) : les agendas cochés dans la légende. Décocher un
// agenda ne change que l'affichage : la page se relit avec ``?masques=`` (ceux qu'on ne montre pas), qui tient dans
// l'adresse et que la période, la vue et « Les agendas de » gardent. Sans script, tout reste affiché.
(function () {
  "use strict";
  function ready(fn) {
    if (document.readyState !== "loading") fn(); else document.addEventListener("DOMContentLoaded", fn);
  }
  ready(function () {
    var legend = document.querySelector("[data-agc-legend]");
    if (!legend) return;
    var boxes = Array.from(legend.querySelectorAll("[data-agc-leg]"));
    boxes.forEach(function (box) {
      box.addEventListener("change", function () {
        var row = box.closest(".agc-leg");
        if (row) row.classList.toggle("off", !box.checked);
        var off = boxes.filter(function (b) { return !b.checked; }).map(function (b) {
          return b.getAttribute("data-agc-leg");
        });
        var params = new URLSearchParams(legend.getAttribute("data-base") || "");
        params.set("masques", off.join(","));
        location.assign("?" + params.toString());
      });
    });
  });
})();
