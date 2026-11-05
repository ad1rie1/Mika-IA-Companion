/* Le moteur de la maquette : la navigation, le thème, la barre de titre de chaque écran, le coin de Mika,
   la palette Ctrl K, les menus, les fenêtres et les toasts. Scripts classiques : la page s'ouvre aussi en file://.

   Écrire un écran (ecrans/<id>.js) :

     M.register('mail', {
       titre: 'Mail',
       onglets: [{ id: 'messages', titre: 'Messages' }, { id: 'contacts', titre: 'Contacts', cnt: 48 }],
       compte: () => 12,                   // la pastille de la barre du haut ('' pour rien)
       actions: (ctx) => '<button …>',     // HTML des actions de page, à droite de la barre de titre
       rendu: (body, ctx) => { … },        // remplit le corps ; ctx = { onglet, item, route, screen }
       recherche: () => [{ groupe: 'Mails', titre, sous, ico: 'mail', route: '#mail/messages/m3' }],
       notes: (ctx) => [{ statut: 'existe' | 'partiel' | 'manque' | 'en_cours' | 'decide', titre, texte, src }],
     });

   Les notes disent, pour l'écran ouvert, ce que le moteur sait déjà faire et ce qui reste à construire (bouton
   « Notes » de la barre du haut).

   Routes : #<écran>[/<onglet>[/<objet>]]. Un changement de route rappelle rendu(). Un écran garde son état
   dans ses propres variables. Aides : M.h (échapper), M.ico, M.av, M.who, M.toast, M.modal, M.menu,
   M.formulaire (barre d'enregistrement), M.mika.set / typing / talk, M.mobile(), M.go, M.on(root, sel, evt, fn).
   Mika est en haut à droite de la barre du haut : son visage, son nom et sa ligne d'état. Un écran peut lui offrir
   une scène plus grande en posant un élément [data-mika-scene] dans son corps (la colonne du chat) : la VRM y va. */
(function () {
  'use strict';
  const D = window.MIKA_DONNEES;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const M = {
    D, $, $$, ecrans: {}, ordre: [], courant: null,
    register(id, def) { this.ecrans[id] = def; if (!this.ordre.includes(id)) this.ordre.push(id); },
  };
  window.M = M;

  /* ── Petites aides ───────────────────────────────────────────────── */
  M.h = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  M.ico = (name, cls) => `<svg class="ico${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  M.norm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  M.mobile = () => matchMedia('(max-width: 760px)').matches;
  M.on = (root, sel, evt, fn) => root.addEventListener(evt, (e) => {
    const t = e.target.closest(sel);
    if (t && root.contains(t)) fn(e, t);
  });
  M.who = (cle) => D.personnes[cle] || { nom: cle, court: cle, c: hash(cle) % 8, moyens: [] };
  function hash(s) { let x = 0; for (const ch of String(s)) x = (x * 31 + ch.charCodeAt(0)) >>> 0; return x; }
  M.initiales = (nom) => String(nom).split(/[\s.-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  const PORTRAITS = '../../frontend/Android/app/src/main/assets/avatar/';
  M.portrait = (humeur) => PORTRAITS + (D.portraits[humeur] ? humeur : 'neutral') + '.webp';

  /* Un avatar : M.av('claire', 'sm') ; M.av('mika') ; M.av({ nom: 'Inconnu' }) ; pres = 'on' | 'away' | 'busy'. */
  M.av = (qui, taille, pres) => {
    const cls = 'av' + (taille ? ' ' + taille : '');
    const p = pres ? `<i class="pres ${pres}"></i>` : '';
    if (qui === 'mika') {
      // Son visage au centre du rond, d'après le centre noté dans le manifeste des portraits.
      const hum = D.mika.etat === 'dort' ? 'sleep' : D.mika.humeur;
      const f = (D.portraits[hum] || D.portraits.neutral).f, W = 330;
      const pos = `width:${W}%;left:${(50 - f[0] * W).toFixed(1)}%;top:${(50 - f[1] * W * 4 / 3).toFixed(1)}%`;
      return `<span class="${cls} mika" title="Mika"><img src="${M.portrait(hum)}" alt="" style="${pos}">${p}</span>`;
    }
    const per = typeof qui === 'string' ? M.who(qui) : qui;
    const c = per.c != null ? per.c : hash(per.nom) % 8;
    return `<span class="${cls} c${c}" title="${M.h(per.nom)}">${M.h(M.initiales(per.nom))}${p}</span>`;
  };

  /* ── Les toasts ──────────────────────────────────────────────────── */
  M.toast = (texte, opts) => {
    const o = opts || {};
    const el = document.createElement('div');
    el.className = 'toast' + (o.mika ? ' mika' : '');
    el.innerHTML = M.ico(o.ico || (o.mika ? 'sparkle' : 'check')) + `<span>${o.html ? texte : M.h(texte)}</span>`;
    $('#toasts').appendChild(el);
    setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 250); }, o.duree || 2600);
  };

  /* ── Les fenêtres ────────────────────────────────────────────────── */
  M.modal = ({ titre, corps, pied, taille, entete }) => {
    M.fermerModal();
    const scrim = document.createElement('div');
    scrim.className = 'modal-scrim';
    scrim.innerHTML = `<div class="modal${taille ? ' ' + taille : ''}" role="dialog" aria-label="${M.h(titre)}">
      <div class="modal-head"><h2>${M.h(titre)}</h2><div class="ph-actions">${entete || ''}
        <button class="btn icon ghost sm" type="button" data-close title="Fermer">${M.ico('x')}</button></div></div>
      <div class="modal-body">${corps || ''}</div>${pied ? `<div class="modal-foot">${pied}</div>` : ''}</div>`;
    scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) M.fermerModal(); });
    M.on(scrim, '[data-close]', 'click', () => M.fermerModal());
    $('#modal-root').appendChild(scrim);
    const first = $('input, textarea, select', scrim);
    if (first) setTimeout(() => first.focus(), 30);
    return scrim.firstElementChild;
  };
  M.fermerModal = () => { $('#modal-root').innerHTML = ''; };

  /* ── Les menus ───────────────────────────────────────────────────── */
  let menuEl = null;
  M.menu = (ancre, items, opts) => {
    M.fermerMenu();
    const o = opts || {};
    menuEl = document.createElement('div');
    menuEl.className = 'menu';
    menuEl.setAttribute('role', 'menu');
    menuEl.innerHTML = items.map((it, i) => {
      if (it === 'sep') return '<div class="msep"></div>';
      if (it.entete) return `<div class="mh">${M.h(it.entete)}</div>`;
      if (it.html) return it.html;
      return `<button class="mi${it.danger ? ' danger' : ''}" type="button" role="menuitem" data-i="${i}"${it.coche != null ? ` aria-checked="${!!it.coche}"` : ''}>
        ${it.ico ? M.ico(it.ico) : ''}<span>${M.h(it.label)}</span>${it.kbd ? `<kbd class="kbd">${M.h(it.kbd)}</kbd>` : ''}</button>`;
    }).join('');
    document.body.appendChild(menuEl);
    const r = ancre.getBoundingClientRect();
    const w = menuEl.offsetWidth, hgt = menuEl.offsetHeight;
    let left = o.align === 'left' ? r.left : r.right - w;
    left = Math.max(8, Math.min(left, innerWidth - w - 8));
    let top = r.bottom + 6;
    if (top + hgt > innerHeight - 8) top = Math.max(8, r.top - hgt - 6);
    menuEl.style.left = left + 'px';
    menuEl.style.top = top + 'px';
    M.on(menuEl, '.mi', 'click', (e, b) => {
      const it = items[+b.dataset.i];
      M.fermerMenu();
      if (it && it.action) it.action();
    });
    setTimeout(() => document.addEventListener('mousedown', fermerSiDehors), 0);
    return menuEl;
  };
  function fermerSiDehors(e) { if (menuEl && !menuEl.contains(e.target)) M.fermerMenu(); }
  M.fermerMenu = () => {
    if (menuEl) { menuEl.remove(); menuEl = null; }
    document.removeEventListener('mousedown', fermerSiDehors);
  };

  /* ── La barre d'enregistrement d'un formulaire ───────────────────── */
  let savebar = null;
  M.formulaire = (root, onSave) => {
    if (!savebar) {
      savebar = document.createElement('div');
      savebar.className = 'savebar';
      savebar.innerHTML = `<span>Modifications non enregistrées</span>
        <button class="btn sm" type="button" data-sb="annuler">Annuler</button>
        <button class="btn sm primary" type="button" data-sb="enregistrer">Enregistrer</button>`;
      document.body.appendChild(savebar);
      M.on(savebar, '[data-sb]', 'click', (e, b) => {
        const f = savebar._form;
        savebar.classList.remove('on');
        if (b.dataset.sb === 'enregistrer') { if (f && f._onSave) f._onSave(); M.toast('Enregistré'); }
        else if (f) { f._reset && f._reset(); M.toast('Modifications annulées', { ico: 'refresh' }); }
      });
    }
    const valeurs = new Map();
    $$('input, select, textarea', root).forEach((el) => valeurs.set(el, el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value));
    root._onSave = onSave;
    root._reset = () => valeurs.forEach((v, el) => { if (el.type === 'checkbox' || el.type === 'radio') el.checked = v; else el.value = v; });
    const sale = () => { savebar._form = root; savebar.classList.add('on'); };
    root.addEventListener('input', sale);
    root.addEventListener('change', sale);
  };
  const cacherSavebar = () => { if (savebar) savebar.classList.remove('on'); };

  /* ── La navigation ───────────────────────────────────────────────── */
  M.route = () => {
    const parts = decodeURIComponent(location.hash.replace(/^#/, '')).split('/').filter(Boolean);
    const screen = M.ecrans[parts[0]] ? parts[0] : 'chat';
    const def = M.ecrans[screen];
    const onglets = def.onglets || [];
    const onglet = onglets.some((o) => o.id === parts[1]) ? parts[1] : (def.defaut || (onglets[0] && onglets[0].id) || null);
    return { screen, onglet, item: parts.slice(onglets.length ? 2 : 1).join('/') || null, route: location.hash };
  };
  M.go = (route) => { if (location.hash === route) afficher(); else location.hash = route; };

  function teteDePage(def, ctx) {
    const tabs = (def.onglets || []).map((o) =>
      `<a href="#${ctx.screen}/${o.id}"${o.id === ctx.onglet ? ' aria-current="page"' : ''}>${o.ico ? M.ico(o.ico, 'sm') : ''}${M.h(o.titre)}${o.cnt != null && o.cnt !== '' ? `<span class="cnt">${M.h(o.cnt)}</span>` : ''}</a>`).join('');
    return `<div class="ph-title"><h1>${M.h(def.titre)}</h1>${def.sousTitre ? `<span class="cnt">${M.h(def.sousTitre(ctx))}</span>` : ''}</div>
      ${tabs ? `<nav class="subtabs" aria-label="Onglets">${tabs}</nav>` : ''}
      <div class="ph-actions">${def.actions ? def.actions(ctx) : ''}</div>`;
  }

  function afficher() {
    const ctx = M.route();
    const def = M.ecrans[ctx.screen];
    M.fermerMenu(); cacherSavebar(); fermerEtat();
    $$('.screen').forEach((s) => { s.hidden = s.dataset.screen !== ctx.screen; });
    const sec = $(`.screen[data-screen="${ctx.screen}"]`);
    ctx.el = sec;
    if (!sec._monte) {
      sec.innerHTML = def.sansTete ? '<div class="page-body"></div>' : '<header class="page-head"></header><div class="page-body"></div>';
      if (def.sansTete) sec.classList.add('no-head');
      sec._monte = true;
      if (def.monte) def.monte(sec);
    }
    if (!def.sansTete) $('.page-head', sec).innerHTML = teteDePage(def, ctx);
    coin.garer();
    def.rendu($('.page-body', sec), ctx);
    coin.loger(sec.querySelector('[data-mika-scene]'));
    M.ctx = ctx;
    remplirNotes();
    $$('[data-nav]').forEach((a) => { if (a.dataset.nav === ctx.screen) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    document.title = `${def.titre} — Mika (maquette)`;
    const changeEcran = M.courant !== ctx.screen;
    M.courant = ctx.screen;
    M.compter();
  }
  M.rafraichir = afficher;
  M.compter = () => {
    $$('[data-count]').forEach((b) => {
      const def = M.ecrans[b.dataset.count];
      const n = def && def.compte ? def.compte() : '';
      b.textContent = n ? (n > 99 ? '99+' : n) : '';
    });
  };

  /* ── Les notes de la maquette ───────────────────────────────────── */
  const STATUTS = { existe: ['ok', 'Existe'], partiel: ['warn', 'Partiel'], en_cours: ['info', 'En cours'], manque: ['danger', 'Manque'], decide: ['accent', 'Décidé'] };
  function remplirNotes() {
    const el = $('#notes');
    if (!el || el.hidden || !M.ctx) return;
    const def = M.ecrans[M.ctx.screen];
    const notes = def.notes ? def.notes(M.ctx) : [];
    let groupe = null;
    el.innerHTML = `<div class="notes-head"><div class="grow"><h2>Notes · ${M.h(def.titre)}</h2>
        <p>Ce que le moteur sait déjà faire, ce qui reste à construire.</p></div>
        <button class="btn icon ghost sm" type="button" data-notes-close title="Fermer">${M.ico('x')}</button></div>
      <ul>${notes.length ? notes.map((n) => {
        const g = n.groupe && n.groupe !== groupe ? `<div class="notes-group">${M.h((groupe = n.groupe))}</div>` : '';
        const [cls, lib] = STATUTS[n.statut] || ['', n.statut];
        return `${g}<li><span><span class="tag ${cls}">${lib}</span></span><span><b>${M.h(n.titre)}</b>${n.texte ? ` — ${M.h(n.texte)}` : ''}${n.src ? `<span class="src">${M.h(n.src)}</span>` : ''}</span></li>`;
      }).join('') : '<li><span></span><span class="muted">Pas encore de notes pour cet écran.</span></li>'}</ul>`;
  }
  function basculerNotes(on) {
    const el = $('#notes'), b = $('#notes-btn');
    const ouvrir = on == null ? el.hidden : on;
    el.hidden = !ouvrir;
    document.body.classList.toggle('notes-on', ouvrir);
    b.setAttribute('aria-pressed', ouvrir);
    try { localStorage.setItem('mika-maquette-notes', ouvrir ? '1' : '0'); } catch (e) { /* rien */ }
    remplirNotes();
  }

  /* ── Le thème ────────────────────────────────────────────────────── */
  const THEMES = { system: 'Système', light: 'Clair', dark: 'Sombre' };
  function appliquerTheme(choix) {
    const dark = choix === 'dark' || (choix === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.themeChoice = choix;
    try { localStorage.setItem('mika-maquette-theme', choix); } catch (e) { /* file:// sans stockage */ }
    $('#theme-btn').innerHTML = M.ico(choix === 'system' ? 'monitor' : dark ? 'moon' : 'sun');
    $('#theme-btn').title = `Thème : ${THEMES[choix]} (cliquer pour changer)`;
    document.dispatchEvent(new CustomEvent('mika:theme', { detail: { dark } }));
    if (coin.el) coin.cadrer();
  }
  M.theme = appliquerTheme;

  /* ── Ce qu'elle fait ─────────────────────────────────────────────── */
  function carteEtat() {
    const m = D.mika;
    return `<div class="sc-head">${M.av('mika', 'lg', m.etat === 'dort' ? 'away' : 'on')}<div><b>Mika</b>
        <span>${M.h(m.humeurDite)} · ${M.h(m.fait)}</span></div>
        <button class="btn icon ghost sm" type="button" data-close-state style="margin-left:auto" title="Fermer">${M.ico('x')}</button></div>
      <div class="sc-sec"><h4>Humeur</h4>${m.facettes.map(([n, v]) =>
        `<div class="facet"><span>${M.h(n)}</span><span class="bar"><i style="width:${Math.round(v * 100)}%"></i></span><span class="num">${Math.round(v * 100)} %</span></div>`).join('')}</div>
      <div class="sc-sec"><h4>Corps</h4>${m.corps.map(([i, t]) => `<div class="sc-line">${M.ico(i, 'sm')}<span>${M.h(t)}</span></div>`).join('')}
        <div class="sc-line">${M.ico('heart', 'sm')}<span>Estime de soi · ${M.h(m.estime)}</span></div></div>
      <div class="sc-sec"><h4>Elle repense à…</h4><div class="sc-line">${M.ico('sparkle', 'sm')}<span>${M.h(m.repense)}</span></div></div>
      <div class="sc-sec"><h4>Rêve de cette nuit</h4><div class="sc-line">${M.ico('moon', 'sm')}<span>${M.h(m.reve)}</span></div></div>
      <div class="sc-sec"><h4>Ses besoins</h4><div class="row wrap">${m.besoins.map((b) => `<span class="tag mika">${M.h(b)}</span>`).join('')}</div></div>
      <div class="sc-sec"><h4>Ce qu'elle t'a promis</h4>${m.promesses.map(([t, q]) => `<div class="sc-line">${M.ico('check', 'sm')}<span>${M.h(t)} <span class="muted">· ${M.h(q)}</span></span></div>`).join('')}</div>
      <div class="sc-sec"><h4>Son dernier journal</h4><p class="text-2">« ${M.h(m.journal)} »</p></div>
      <div class="sc-sec"><h4>Ses projets avec toi</h4>${m.projets.map(([t, s]) => `<div class="sc-line">${M.ico('code', 'sm')}<span>${M.h(t)} <span class="tag">${M.h(s)}</span></span></div>`).join('')}</div>`;
  }
  function ouvrirEtat(ancre) {
    const c = $('#state-card');
    if (!c.hidden) { fermerEtat(); return; }
    c.innerHTML = carteEtat();
    c.hidden = false;
    const r = ancre.getBoundingClientRect();
    const w = c.offsetWidth, hgt = c.offsetHeight;
    let left = r.right - w, top = r.bottom + 8;
    if (top + hgt > innerHeight - 8) top = Math.max(60, r.top - hgt - 8);
    if (left < 8) left = Math.min(r.left, innerWidth - w - 8);
    c.style.left = Math.max(8, left) + 'px';
    c.style.top = top + 'px';
    setTimeout(() => document.addEventListener('mousedown', fermerEtatDehors), 0);
  }
  function fermerEtatDehors(e) { const c = $('#state-card'); if (!c.contains(e.target) && !e.target.closest('#state-pill, #brand-face')) fermerEtat(); }
  function fermerEtat() { $('#state-card').hidden = true; document.removeEventListener('mousedown', fermerEtatDehors); }

  /* ── Mika dans un coin ───────────────────────────────────────────── */
  const coin = {
    el: null, taille: 'normal',
    init() {
      // Une seule VRM : son visage dans la pastille de la barre du haut, ou en grand là où un écran lui offre une
      // scène (data-mika-scene : la colonne du chat). La pastille ouvre « Ce qu'elle fait ».
      this.el = $('#mika-corner');
      this.home = this.el.parentElement;
      this.cadrer();
      addEventListener('resize', () => { this.loger(this.scene); this.cadrer(); });
      this.clignements();
    },
    // Retirée de la page le temps qu'un écran redessine son corps : la scène qui l'accueillait va disparaître.
    garer() { if (this.el.parentElement && this.el.parentElement !== this.home) this.el.remove(); },
    loger(scene) {
      this.scene = scene && document.contains(scene) ? scene : null;
      const visible = this.scene && this.scene.offsetParent !== null;
      const cible = visible ? this.scene : this.home;
      if (this.el.parentElement !== cible) cible.prepend(this.el);
      const taille = visible ? 'large' : 'mini';
      const change = this.el.dataset.size !== taille;
      this.el.dataset.size = taille;
      document.body.classList.toggle('mika-en-grand', !!visible);
      this.cadrer();
      if (change) document.dispatchEvent(new CustomEvent('mika:size', { detail: { taille } }));
    },
    /* Le portrait : le visage à 36 % de la hauteur, le clignement posé pile sur les yeux. */
    cadrer() {
      const st = $('#mc-stage'), img = $('#mc-portrait'), bl = $('#mc-blink');
      const humeur = D.mika.etat === 'dort' ? 'sleep' : D.mika.humeur;
      const p = D.portraits[humeur] || D.portraits.neutral;
      const W = st.clientWidth, H = st.clientHeight;
      const mini = this.el.dataset.size === 'mini';   // son visage seul, dans la pastille
      const imgH = mini ? H * 5.4 : H * 2.05, s = imgH / 1440, imgW = 1080 * s;
      const left = W / 2 - p.f[0] * imgW, top = H * (mini ? 0.5 : 0.36) - p.f[1] * imgH;
      const src = M.portrait(humeur);
      if (!img.src.endsWith(src.replace('../..', ''))) img.src = src;
      Object.assign(img.style, { height: imgH + 'px', left: left + 'px', top: top + 'px', transform: 'none' });
      if (p.b) {
        bl.src = src.replace('.webp', '.blink.webp');
        Object.assign(bl.style, { height: p.b[3] * s + 'px', width: p.b[2] * s + 'px', left: left + p.b[0] * s + 'px', top: top + p.b[1] * s + 'px', transform: 'none' });
      }
      const sorte = D.mika.etat === 'ecrit' ? 'crepuscule' : D.aura[humeur] || 'neutre';
      const dark = document.documentElement.dataset.theme === 'dark';
      this.el.style.setProperty('--mood', D.auras[sorte][dark ? 1 : 0]);
    },
    clignements() {
      const bl = $('#mc-blink');
      const fois = () => {
        const p = D.portraits[D.mika.humeur];
        if (p && p.b && D.mika.etat !== 'dort' && !this.el.classList.contains('vrm-on')) {
          bl.hidden = false;
          setTimeout(() => { bl.hidden = true; }, 130);
        }
        setTimeout(fois, 2600 + Math.random() * 3600);
      };
      setTimeout(fois, 1800);
    },
  };

  M.coin = coin;

  /* L'état de Mika, partagé par la pastille, son coin et la VRM (mika-vrm.js écoute « mika:state »). */
  M.mika = {
    set(changes) {
      Object.assign(D.mika, changes || {});
      const m = D.mika;
      // La ligne d'état d'Android (« éveillée · dessine à son bureau · contente ») ; la pastille en garde l'essentiel.
      const ligne = `${m.etat === 'dort' ? 'dort' : 'éveillée'} · ${m.fait} · ${m.humeurDite}`;
      $('.sp-doing').textContent = m.etat === 'dort' ? 'dort' : `${m.fait} · ${m.humeurDite}`;
      $('#state-pill').title = `Mika : ${ligne} — ce qu'elle fait`;
      $('#brand-face').innerHTML = `${M.av('mika', 'sm', m.etat === 'dort' ? 'away' : 'on')}<span>Mika</span>`;
      $('#sp-static').innerHTML = M.av('mika', 'sm');
      $('#state-pill').dataset.state = m.etat;
      coin.cadrer();
      document.dispatchEvent(new CustomEvent('mika:state', { detail: { ...m } }));
    },
    typing(on) {
      $('#mc-typing').hidden = !on;
      document.dispatchEvent(new CustomEvent('mika:typing', { detail: { on } }));
    },
    talk(ms) { document.dispatchEvent(new CustomEvent('mika:talk', { detail: { ms: ms || 1800 } })); },
  };

  /* ── La palette Ctrl K ───────────────────────────────────────────── */
  let paletteItems = [], paletteSel = 0;
  function entreesPalette() {
    const out = [];
    M.ordre.forEach((id) => {
      const def = M.ecrans[id];
      out.push({ groupe: 'Aller à', titre: def.titre, ico: navIco(id), route: '#' + id });
      (def.onglets || []).forEach((o) => out.push({ groupe: 'Aller à', titre: `${def.titre} › ${o.titre}`, ico: navIco(id), route: `#${id}/${o.id}` }));
    });
    M.ordre.forEach((id) => { const def = M.ecrans[id]; if (def.recherche) out.push(...def.recherche()); });
    return out;
  }
  function navIco(id) { return { chat: 'chat', outils: 'tools', mail: 'mail', teams: 'teams', telephone: 'phone', carte: 'map', parametres: 'settings' }[id] || 'chev-right'; }
  function ouvrirPalette() {
    $('#palette').hidden = false;
    const q = $('#palette-q');
    q.value = '';
    filtrerPalette();
    setTimeout(() => q.focus(), 20);
  }
  function fermerPalette() { $('#palette').hidden = true; }
  function filtrerPalette() {
    const q = M.norm($('#palette-q').value.trim());
    const toutes = entreesPalette();
    paletteItems = (q ? toutes.filter((e) => M.norm(e.titre + ' ' + (e.sous || '') + ' ' + e.groupe).includes(q)) : toutes.filter((e) => e.groupe === 'Aller à' && !e.titre.includes('›')).concat(toutes.filter((e) => e.groupe !== 'Aller à').slice(0, 6))).slice(0, 40);
    paletteSel = 0;
    let groupe = null;
    $('#palette-results').innerHTML = paletteItems.length ? paletteItems.map((e, i) => {
      const tete = e.groupe !== groupe ? `<div class="mh">${M.h((groupe = e.groupe))}</div>` : '';
      return `${tete}<button class="pr${i === 0 ? ' on' : ''}" type="button" data-pi="${i}">${M.ico(e.ico || 'chev-right')}
        <span class="pr-main"><b>${M.h(e.titre)}</b>${e.sous ? `<small>${M.h(e.sous)}</small>` : ''}</span>${e.cote ? `<span class="muted">${M.h(e.cote)}</span>` : ''}</button>`;
    }).join('') : '<div class="empty"><b>Rien trouvé</b><p>Essaie un nom, un objet de mail ou un outil.</p></div>';
  }
  function choisirPalette(i) {
    const e = paletteItems[i];
    if (!e) return;
    fermerPalette();
    if (e.action) e.action(); else M.go(e.route);
  }

  /* ── Le menu du compte ───────────────────────────────────────────── */
  function menuCompte(ancre) {
    const choix = document.documentElement.dataset.themeChoice || 'system';
    M.menu(ancre, [
      { html: `<div class="who">${M.av('adrien', 'lg')}<div><b>${M.h(D.moi.nom)}</b><span>${M.h(D.moi.login)} · ${M.h(D.moi.role)}${D.moi.operatrice ? ' · opérateur' : ''}</span></div></div>` },
      'sep',
      { label: 'Mon compte', ico: 'user', action: () => M.go('#parametres/compte') },
      { label: 'Mes partages', ico: 'users', action: () => M.go('#parametres/partages') },
      'sep',
      { entete: 'Thème' },
      { label: 'Système', ico: 'monitor', coche: choix === 'system', action: () => appliquerTheme('system') },
      { label: 'Clair', ico: 'sun', coche: choix === 'light', action: () => appliquerTheme('light') },
      { label: 'Sombre', ico: 'moon', coche: choix === 'dark', action: () => appliquerTheme('dark') },
      'sep',
      ...(D.moi.operatrice ? [{ label: 'Ouvrir la console de Mika', ico: 'external', action: () => M.toast('La console reste sur /inspecteur, pour les opérateurs.', { ico: 'info' }) }] : []),
      { label: 'Se déconnecter', ico: 'logout', danger: true, action: () => M.toast('Maquette : la déconnexion ramènerait à la page de connexion.', { ico: 'info' }) },
    ]);
  }

  /* Un bouton à choix (.seg[data-seg]) se règle d'un clic, où qu'il soit, fenêtres comprises ; « mika:seg » le dit. */
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.seg[data-seg] button');
    if (!b) return;
    const g = b.closest('.seg');
    g.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
    g.dispatchEvent(new CustomEvent('mika:seg', { bubbles: true, detail: { nom: g.dataset.seg, valeur: b.dataset.v } }));
  });

  /* ── Le démarrage ────────────────────────────────────────────────── */
  M.start = () => {
    appliquerTheme(document.documentElement.dataset.themeChoice || 'system');
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if ((document.documentElement.dataset.themeChoice || 'system') === 'system') appliquerTheme('system');
    });
    $('#theme-btn').addEventListener('click', () => {
      const ordre = ['system', 'light', 'dark'];
      const c = document.documentElement.dataset.themeChoice || 'system';
      appliquerTheme(ordre[(ordre.indexOf(c) + 1) % 3]);
      M.toast(`Thème : ${THEMES[document.documentElement.dataset.themeChoice]}`, { ico: 'sun' });
    });
    $('#acct-btn').addEventListener('click', (e) => { e.stopPropagation(); menuCompte(e.currentTarget); });
    $('#state-pill').addEventListener('click', (e) => { e.stopPropagation(); ouvrirEtat(e.currentTarget); });
    $('#brand-face').addEventListener('click', (e) => { e.stopPropagation(); ouvrirEtat(e.currentTarget); });
    M.on($('#state-card'), '[data-close-state]', 'click', fermerEtat);
    $('#gsearch').addEventListener('click', ouvrirPalette);
    $('#notes-btn').addEventListener('click', () => basculerNotes());
    M.on($('#notes'), '[data-notes-close]', 'click', () => basculerNotes(false));
    let notesAuDepart = false;
    try { notesAuDepart = localStorage.getItem('mika-maquette-notes') === '1'; } catch (e) { /* rien */ }
    if (new URLSearchParams(location.search).get('notes') === '1') notesAuDepart = true;
    if (notesAuDepart) basculerNotes(true);
    $('#palette-q').addEventListener('input', filtrerPalette);
    $('#palette').addEventListener('mousedown', (e) => { if (e.target.id === 'palette') fermerPalette(); });
    M.on($('#palette-results'), '.pr', 'click', (e, b) => choisirPalette(+b.dataset.pi));
    $('#palette-q').addEventListener('keydown', (e) => {
      const btns = $$('.pr', $('#palette-results'));
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        paletteSel = (paletteSel + (e.key === 'ArrowDown' ? 1 : -1) + btns.length) % Math.max(1, btns.length);
        btns.forEach((b, i) => b.classList.toggle('on', i === paletteSel));
        if (btns[paletteSel]) btns[paletteSel].scrollIntoView({ block: 'nearest' });
      }
      if (e.key === 'Enter') { e.preventDefault(); choisirPalette(paletteSel); }
    });
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#palette').hidden ? ouvrirPalette() : fermerPalette(); }
      if (e.key === 'Escape') { fermerPalette(); M.fermerMenu(); fermerEtat(); if ($('#modal-root').children.length) M.fermerModal(); }
    });
    coin.init();
    M.mika.set({});
    addEventListener('hashchange', afficher);
    afficher();
  };
})();
