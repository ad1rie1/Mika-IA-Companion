/* Courrier › Paramètres, une boîte (templates/handmade/mail/parametres.html, ADR 0174) : le formulaire suit ce qu'on
   tape. Ce qui ne sert pas au choix fait se masque déjà (data-only, console.js) ; ce script propose ce qui va de soi :
   - sur une boîte neuve, l'adresse d'un fournisseur courant remplit ses serveurs, leurs ports et la connexion ;
   - un compte Microsoft choisi remplit les serveurs de Microsoft ;
   - l'utilisateur suit l'adresse tant qu'il la recopie ;
   - un port suit son chiffrement (993 ou 143 pour lire, 587 ou 465 pour envoyer).
   Rien n'écrase ce qu'on a tapé ou choisi, même vidé : un champ jamais touché à la main ne change que vide, encore tel
   que ce script l'a laissé, ou, sur une boîte neuve, à sa valeur de départ. Sans ce script, la page marche : tout se
   tape à la main. */
(function () {
  "use strict";
  var form = document.querySelector("form.mailset-account");
  if (!form) return;
  var fresh = form.hasAttribute("data-new");

  function input(name) {
    var el = form.elements.namedItem(name);
    return el && el.tagName ? el : null;
  }
  var MICROSOFT = { auth: "microsoft", imap_host: "outlook.office365.com", imap_port: "993", imap_ssl: true,
                    smtp_host: "smtp-mail.outlook.com", smtp_security: "starttls", smtp_port: "587" };
  function servers(imap, smtp, ssl, extra) {
    var out = { auth: "password", imap_host: imap, imap_port: "993", imap_ssl: true, smtp_host: smtp,
                smtp_security: ssl ? "ssl" : "starttls", smtp_port: ssl ? "465" : "587" };
    Object.keys(extra || {}).forEach(function (k) { out[k] = extra[k]; });
    return out;
  }
  // [domaine, nom, réglages] ; Gmail range lui-même ses envois dans « Envoyés »
  var PROVIDERS = [
    [/^(gmail|googlemail)\.com$/, "Gmail", servers("imap.gmail.com", "smtp.gmail.com", false, { save_sent: false })],
    [/^(hotmail|outlook|live|msn)\.[a-z.]+$/, "Outlook (compte Microsoft)", MICROSOFT],
    [/^(yahoo|ymail)\.[a-z.]+$/, "Yahoo", servers("imap.mail.yahoo.com", "smtp.mail.yahoo.com", true)],
    [/^(icloud|me|mac)\.com$/, "iCloud", servers("imap.mail.me.com", "smtp.mail.me.com", false)],
    [/^fastmail\.(com|fm)$/, "Fastmail", servers("imap.fastmail.com", "smtp.fastmail.com", true)],
    [/^(orange|wanadoo)\.fr$/, "Orange", servers("imap.orange.fr", "smtp.orange.fr", true)],
    [/^free\.fr$/, "Free", servers("imap.free.fr", "smtp.free.fr", true)],
    [/^(sfr|neuf)\.fr$/, "SFR", servers("imap.sfr.fr", "smtp.sfr.fr", true)],
    [/^laposte\.net$/, "La Poste", servers("imap.laposte.net", "smtp.laposte.net", true)]
  ];
  var PROPOSED = ["auth", "imap_host", "imap_port", "imap_ssl", "smtp_host", "smtp_security", "smtp_port", "save_sent"];

  function read(el) { return el.type === "checkbox" ? el.checked : el.value; }
  var initial = new Map(), placed = new Map(), owned = new Set();
  PROPOSED.forEach(function (n) { var el = input(n); if (el) initial.set(el, read(el)); });

  // jamais touché à la main, et vide, encore tel que ce script l'a laissé, ou (boîte neuve) à sa valeur de départ
  function free(el) {
    if (owned.has(el)) return false;
    var v = read(el);
    if (v === "" && el.tagName !== "SELECT") return true;
    return placed.has(el) ? placed.get(el) === v : fresh && v === initial.get(el);
  }
  function set(el, v) {
    if (read(el) !== v) {
      if (el.type === "checkbox") el.checked = v; else el.value = v;
      el.dispatchEvent(new Event("change", { bubbles: true }));  // console.js remontre ce qui en dépend
    }
    if (v === initial.get(el)) placed.delete(el); else placed.set(el, v);
  }
  function follow(port, value, usual) {
    if (port && !owned.has(port) && usual.indexOf(port.value) !== -1) set(port, value);
  }

  var address = input("address"), auth = input("auth"), user = input("user");
  var hint = null;
  function say(text) {
    if (!address) return;
    if (!hint) {
      hint = document.createElement("p");
      hint.className = "mailset-hint";
      hint.setAttribute("aria-live", "polite");
      address.closest(".field").appendChild(hint);
    }
    hint.textContent = text;
    hint.hidden = !text;
  }

  // les serveurs d'un fournisseur reconnu à l'adresse (boîte neuve), ceux de Microsoft s'il est choisi ; sans
  // proposition, ce que ce script avait mis revient à sa valeur de départ
  function propose() {
    var domain = ((address && address.value) || "").trim().toLowerCase().split("@")[1] || "";
    var found = fresh ? PROVIDERS.filter(function (p) { return p[0].test(domain); })[0] : null;
    // Microsoft choisi à la main, ou celui de la boîte enregistrée — pas celui qu'une adresse avait proposé
    var chosen = auth && auth.value === "microsoft" && !placed.has(auth) && (owned.has(auth) || !found);
    var preset = chosen ? MICROSOFT : found ? found[2] : null;
    PROPOSED.forEach(function (n) {
      var el = input(n);
      if (el && free(el)) set(el, preset && n in preset ? preset[n] : initial.get(el));
    });
    var filled = ["imap_host", "smtp_host"].some(function (n) { var el = input(n); return el && placed.has(el); });
    say(found && filled ? found[1] + " reconnu : ses serveurs sont proposés plus bas." : "");
  }

  var lastAddress = address ? address.value.trim() : "";
  form.addEventListener("input", touched);
  form.addEventListener("change", touched);
  function touched(ev) {
    var el = ev.target;
    if (!ev.isTrusted || !el.name) return;
    // une liste ou une case se lit à son changement, un texte à la frappe (une liste émet les deux)
    if ((ev.type === "change") !== (el.type === "checkbox" || el.tagName === "SELECT")) return;
    owned.add(el);
    placed.delete(el);
    if (el === address) {
      var now = address.value.trim();
      if (user && (user.value === "" || user.value === lastAddress)) user.value = now;
      lastAddress = now;
      propose();
    } else if (el === auth) {
      propose();
    } else if (el.name === "imap_ssl") {
      follow(input("imap_port"), el.checked ? "993" : "143", ["993", "143", ""]);
    } else if (el.name === "smtp_security" && el.value !== "none") {
      follow(input("smtp_port"), el.value === "ssl" ? "465" : "587", ["587", "465", "25", ""]);
    }
  }
})();
