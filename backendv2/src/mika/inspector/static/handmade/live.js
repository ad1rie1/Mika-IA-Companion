// Les pages dessinées à la main (En ce moment, une personne) se relisent seules — le fragment rendu par le
// serveur —, toutes les 20 s, en pause quand l'onglet est caché, aussitôt revenues. Sans script, elles restent des
// pages complètes.
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var root = document.querySelector("[data-now-live]");
    if (!root || !window.fetch) return;
    var url = root.getAttribute("data-now-live");
    var every = 20000;
    var delay = every;
    var timer = null;
    var busy = false;

    // Sur un écran étroit, le graphe des 24 heures et le calendrier d'une personne défilent : ils s'ouvrent sur
    // « maintenant », à droite.
    function toNow() {
      root.querySelectorAll(".now-lanes-wrap, .person-calendar-wrap").forEach(function (wrap) {
        wrap.scrollLeft = wrap.scrollWidth;
      });
    }

    // L'état peut vivre dans le fragment (une fiche) : il se cherche à chaque fois, jamais gardé d'avant.
    function say(kind, message) {
      var state = document.querySelector("[data-now-state]");
      var text = document.querySelector("[data-now-state-text]");
      if (state) state.setAttribute("data-state", kind);
      if (text) text.textContent = message;
      return text;
    }

    function later(ms) {
      clearTimeout(timer);
      timer = setTimeout(tick, ms);
    }

    function tick() {
      if (document.hidden) { later(every); return; }
      if (busy) return;
      busy = true;
      var ctl = new AbortController();
      var limit = setTimeout(function () { ctl.abort(); }, 10000);
      fetch(url, { credentials: "same-origin", signal: ctl.signal, headers: { "Accept": "text/html" } })
        .then(function (r) {
          clearTimeout(limit);
          if (r.status === 401 || r.status === 403 || r.redirected) throw new Error("session");
          if (!r.ok) throw new Error(String(r.status));
          return r.text();
        })
        .then(function (html) {
          // Le graphe garde où on le regardait : au bout (maintenant), ou plus tôt dans la journée.
          var wrap = root.querySelector(".now-lanes-wrap");
          var left = wrap ? wrap.scrollLeft : 0;
          var atEnd = !wrap || left + wrap.clientWidth >= wrap.scrollWidth - 4;
          // Fragment rendu par le serveur (échappé par Jinja), jamais du texte extérieur brut.
          root.innerHTML = html;
          toNow();
          if (!atEnd && (wrap = root.querySelector(".now-lanes-wrap"))) wrap.scrollLeft = left;
          var stamp = root.querySelector("[data-now-stamp]");
          say("on", "À jour · " + (stamp ? stamp.textContent : ""));
          delay = every;
          later(delay);
        })
        .catch(function (e) {
          if (e.message === "session") {
            var text = say("off", "");
            var login = document.createElement("a");
            login.href = url.split("/_")[0] + "/connexion";
            login.textContent = "Session expirée · Se reconnecter";
            if (text) text.appendChild(login);
            return;
          }
          say("error", "Actualisation interrompue · nouvel essai automatique");
          delay = Math.min(delay * 2, 160000);
          later(delay);
        })
        .then(function () { busy = false; });
    }

    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) later(300);
    });
    toNow();
    later(every);
  });
})();
