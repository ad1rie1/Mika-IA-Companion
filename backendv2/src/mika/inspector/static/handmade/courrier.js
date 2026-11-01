// Le courrier (ADR 0175) : de petites aides, jamais nécessaires — sans elles, tout se fait par les liens et les
// boutons de la page.
// - la liseuse ouverte sous la liste (un écran étroit) : la page y descend ;
// - les cases de la liste : « tout cocher », la barre qui range ne sert qu'avec une sélection, et dit combien ;
// - « ouvrir un mail le marque lu » (Courrier › Paramètres) : passé le délai, lu à l'écran, le formulaire « Marquer
//   comme lu » du message part en arrière-plan ;
// - le clavier, hors des champs : j (suivant), k (précédent), Échap (fermer le message).
(function () {
  "use strict";

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  function typing(el) {
    return el && (el.isContentEditable || el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement ||
                  el instanceof HTMLSelectElement);
  }

  function reveal(reader) {
    if (!reader) return;
    var top = reader.getBoundingClientRect().top;
    if (top > window.innerHeight * 0.6) reader.scrollIntoView({ block: "start" });
  }

  function selection(bulk) {
    if (!bulk) return;
    var boxes = Array.prototype.slice.call(document.querySelectorAll('input[name="mails"][form="' + bulk.id + '"]'));
    var all = bulk.querySelector("[data-check-all]");
    var count = bulk.querySelector("[data-count]");
    var buttons = bulk.querySelectorAll('button[name="geste"]');
    function sync() {
      var n = boxes.filter(function (b) { return b.checked; }).length;
      bulk.classList.toggle("has-selection", n > 0);
      buttons.forEach(function (b) { b.disabled = n === 0; });
      if (count) count.textContent = n ? (n === 1 ? "1 coché" : n + " cochés") : "";
      if (all) {
        all.checked = n > 0 && n === boxes.length;
        all.indeterminate = n > 0 && n < boxes.length;
      }
      boxes.forEach(function (b) { b.closest("li").classList.toggle("checked", b.checked); });
    }
    if (all) all.addEventListener("change", function () {
      boxes.forEach(function (b) { b.checked = all.checked; });
      sync();
    });
    boxes.forEach(function (b) { b.addEventListener("change", sync); });
    sync();
  }

  function readAfter(host) {
    if (!host) return;
    var form = host.querySelector('form[action$="/action/email.classer"]');
    var seconds = parseInt(host.getAttribute("data-read-after"), 10);
    if (!form || isNaN(seconds)) return;
    var timer = null;
    var sent = false;
    function mark() {
      if (sent) return;
      sent = true;
      var button = form.querySelector("button");
      if (button) button.disabled = true;
      fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", redirect: "manual" })
        .then(function (r) {
          if (!(r.ok || r.type === "opaqueredirect")) throw new Error(String(r.status));
          var line = document.querySelector(".mail-lines li.on");
          if (line) line.classList.remove("unread");
          if (button) button.textContent = "Marqué lu";
        })
        .catch(function () {
          sent = false;
          if (button) button.disabled = false;
        });
    }
    function arm() {
      clearTimeout(timer);
      if (!document.hidden && !sent) timer = setTimeout(mark, seconds * 1000);
    }
    document.addEventListener("visibilitychange", arm);
    arm();
  }

  function keys() {
    // à la capture : avant la console, qui ferme sur Échap le panneau ouvert (« Répondre ») — Échap ferme alors ce
    // panneau, pas le message
    document.addEventListener("keydown", function (ev) {
      if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || typing(ev.target)) return;
      var target = ev.key === "j" ? "[data-mail-next]" : ev.key === "k" ? "[data-mail-prev]" :
                   ev.key === "Escape" ? "[data-mail-close]" : "";
      if (!target || document.querySelector("details[open].action-pop, details[open].action-overflow")) return;
      var link = document.querySelector(target);
      if (link) {
        ev.preventDefault();
        window.location.assign(link.href);
      }
    }, true);
  }

  ready(function () {
    reveal(document.querySelector(".mail .mail-reader"));
    selection(document.getElementById("mail-bulk"));
    readAfter(document.querySelector("[data-read-after]"));
    keys();
  });
})();
