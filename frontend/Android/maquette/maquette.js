/* Le moteur de la maquette Android : les routes (#écran/…), la pile, la barre du haut, la barre du bas ou le tiroir,
   les feuilles, menus, fenêtres et messages furtifs, le visage de Mika, et le panneau des notes à côté du téléphone.

   Un écran s'enregistre par A.ecran(id, vue) ; vue(args) rend un objet :
     { html,                 le contenu de l'écran (sa barre du haut comprise)
       nav: 'mail',          la case de la barre du bas qu'il allume
       racine: true,         un écran de premier niveau : barre du bas (ou bouton du tiroir) ; sinon une flèche retour
       back: '#mail',        où mène la flèche quand on est arrivé là directement
       cls: 'chat',          une classe de plus sur l'écran
       notes: { reprend: [], trancher: [] },   ce que le panneau dit de cet écran
       after(root) {} }      les gestes propres à l'écran
   Les gestes communs passent par des attributs : data-go="#route", data-back, data-sheet, data-menu, data-dialog,
   data-drawer, data-snack="texte", data-chip (puce qui s'allume), data-seg (boutons segmentés), data-fold="sélecteur". */
window.A = (function () {
  const D = window.MIKA_DONNEES;
  const $ = (s, r = document) => r.querySelector(s);
  const h = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ico = (n, cls) => `<svg class="ico${cls ? ' ' + cls : ''}"><use href="#i-${n}"/></svg>`;
  const who = (k) => D.personnes[k] || { nom: k, court: k, c: 4 };
  const initiales = (nom) => nom.replace(/[^\p{L}\s-]/gu, '').split(/[\s-]+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
  const av = (k, cls, app) => {
    const p = who(k);
    return `<span class="av c${p.c}${cls ? ' ' + cls : ''}">${h(initiales(p.nom))}${app ? `<i class="app-b ${app}">${app === 'whatsapp' ? 'W' : 'M'}</i>` : ''}</span>`;
  };
  const grp = (txt, cls) => `<span class="av grp${cls ? ' ' + cls : ''}">${txt}</span>`;
  const PORTRAITS = '../app/src/main/assets/avatar/';

  // ── Les variantes et l'état commun ────────────────────────────────────
  const store = {
    get(k, d) { try { return localStorage.getItem('mika-android-' + k) || d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('mika-android-' + k, v); } catch (e) { /* rien */ } },
  };
  const q = new URLSearchParams(location.search);
  const v = { nav: q.get('nav') || store.get('nav', 'barre') };
  // Les pastilles : ses brouillons de mail qui attendent ta décision, sa réponse Teams, sa proposition au téléphone.
  const counts = { mail: 3, teams: 1, plus: 1, telephone: 1 };

  // ── Son visage ────────────────────────────────────────────────────────
  const humeur = () => D.mika.humeur;
  function aura(hm) {
    const k = D.aura[hm || humeur()] || 'neutre';
    const [clair, sombre] = D.auras[k];
    return document.documentElement.dataset.theme === 'dark' ? sombre : clair;
  }
  /** Son visage en rond, à la taille donnée : le portrait de son humeur, cadré sur son visage (ADR 0065). */
  function face(size, hm) {
    hm = hm || humeur();
    const p = D.portraits[hm] || D.portraits.neutral;
    const w = 1080 * size / 430, hh = w * 1440 / 1080;
    const left = size / 2 - p.f[0] * w, top = size / 2 - (p.f[1] + 0.015) * hh;
    return `<span class="face" style="width:${size}px;height:${size}px;--aura:${aura(hm)}"><img src="${PORTRAITS}${hm}.webp" alt=""
      style="width:${w.toFixed(1)}px;left:${left.toFixed(1)}px;top:${top.toFixed(1)}px" onerror="this.parentNode.classList.add('noimg');this.remove()"></span>`;
  }
  const faceDot = (size) => `<span class="face-wrap">${face(size)}<i class="on-dot"></i></span>`;
  /** Le bouton de son visage, au bout de la barre du haut de chaque écran : il ouvre « Ce qu'elle fait ». */
  const faceBtn = () => `<button class="face-btn" type="button" data-go="#mika" title="Mika · ${h(D.mika.fait)}" aria-label="Ce qu'elle fait">${faceDot(32)}</button>`;
  /** Mika en fond du chat : son portrait sur l'aura de son humeur (la 3D Filament dans la vraie app). */
  function stage(hm) {
    hm = hm || humeur();
    const p = D.portraits[hm] || D.portraits.neutral;
    const app = $('#app');
    const W = app.clientWidth || 384, H = app.clientHeight || 832;
    const sb = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sb')) || 0;
    const w = W * 1.3, hh = w * 1440 / 1080;
    const fy = sb + 64 + Math.max(70, H * 0.11);
    const left = W / 2 - p.f[0] * w, top = fy - p.f[1] * hh;
    const k = D.aura[hm] || 'neutre';
    const dark = document.documentElement.dataset.theme === 'dark';
    const [a, b] = dark ? [D.auras[k][1], '#131318'] : [D.auras[k][0], '#fdfcff'];
    return `<div class="stage" style="--aura-a:${a};--aura-b:${b}" aria-hidden="true"><img src="${PORTRAITS}${hm}.webp" alt=""
      style="width:${w.toFixed(0)}px;left:${left.toFixed(0)}px;top:${top.toFixed(0)}px" onerror="this.remove()"></div>`;
  }

  // ── Les pièces communes ───────────────────────────────────────────────
  /** La barre du haut. o : { title, sub, titleAttrs (le titre devient un bouton), back, actions: [html], face (défaut vrai), cls } */
  function top(o) {
    const lead = o.back ? `<button class="ibtn" type="button" data-back aria-label="Retour">${ico('back')}</button>`
      : (o.racine && v.nav === 'tiroir') ? `<button class="ibtn" type="button" data-drawer aria-label="Menu">${ico('menu')}</button>` : '';
    const tcls = `t-title${lead ? '' : ' first'}${o.small ? ' sm' : ''}`;
    const inner = `<b class="ellipsis">${o.title}</b>${o.sub ? `<small class="ellipsis">${o.sub}</small>` : ''}`;
    const title = o.titleAttrs ? `<button class="${tcls}" type="button" ${o.titleAttrs}>${inner}</button>` : `<div class="${tcls}">${inner}</div>`;
    return `<header class="top${o.cls ? ' ' + o.cls : ''}">${lead}${title}${(o.actions || []).join('')}${o.face === false ? '' : faceBtn()}</header>`;
  }
  const act = (icon, label, attrs, cls) => `<button class="ibtn${cls ? ' ' + cls : ''}" type="button" ${attrs || ''} title="${h(label)}" aria-label="${h(label)}">${ico(icon)}</button>`;
  /** Des onglets qui sont des routes : [[route, libellé, compte, rose]] ; cur : la route allumée. */
  const tabs = (list, cur) => `<nav class="tabs">${list.map(([r, l, n, mk]) => `<a href="${r}" data-go="${r}" class="${r === cur ? 'on' : ''}">${h(l)}${n ? `<span class="cnt${mk ? ' mk' : ''}">${n}</span>` : ''}</a>`).join('')}</nav>`;
  const chips = (list) => `<div class="chips">${list.map((c) => `<button type="button" class="chip${c.on ? ' on' : ''}${c.mk ? ' mk' : ''}" data-chip${c.radio ? `="${c.radio}"` : ''}>${c.on ? ico('check', 'xs') : (c.ico ? ico(c.ico, 'xs') : '')}${h(c.l)}${c.n ? `<span class="n">${c.n}</span>` : ''}</button>`).join('')}</div>`;
  const sw = (on, attrs) => `<label class="switch"><input type="checkbox"${on ? ' checked' : ''} ${attrs || ''}><i></i></label>`;

  const NAV = [
    ['chat', 'Chat', 'chat'], ['mail', 'Mail', 'mail'], ['teams', 'Teams', 'teams'], ['carte', 'Carte', 'map'], ['plus', 'Plus', 'grid'],
  ];
  function navbar(cur) {
    return `<nav class="navbar" aria-label="Rubriques">${NAV.map(([id, l, i]) => {
      const n = counts[id];
      const badge = n ? `<b class="badge${id === 'plus' ? ' mk' : ''}">${n}</b>` : '';
      return `<a href="#${id}" data-go="#${id}" class="${cur === id ? 'on' : ''}"><span class="ind">${ico(i)}${badge}</span>${l}</a>`;
    }).join('')}</nav>`;
  }
  const DRAWER = [['chat', 'Chat', 'chat'], ['mail', 'Mail', 'mail'], ['teams', 'Teams', 'teams'], ['carte', 'Carte', 'map'],
    ['telephone', 'Téléphone', 'phone'], ['outils', 'Outils', 'tools'], ['parametres', 'Paramètres', 'settings']];
  function drawer() {
    const cur = state.nav;
    return `<div class="scrim" data-close></div><aside class="drawer" aria-label="Rubriques">
      <button class="plus-mika" type="button" data-go="#mika" style="margin:0 0 10px;width:100%">${faceDot(48)}<span><b>Mika</b><small>${h(D.mika.fait)} · ${h(D.mika.humeurDite)}</small></span></button>
      <button class="field" type="button" data-go="#recherche" style="width:100%;height:48px;margin-bottom:8px">${ico('search', 'sm')}<span class="muted">Rechercher partout</span></button>
      ${DRAWER.map(([id, l, i]) => `<button class="dr-item${cur === id ? ' on' : ''}" type="button" data-go="#${id}">${ico(i)}${l}${counts[id] ? `<span class="cnt-pill${id === 'telephone' ? ' mk' : ''}">${counts[id]}</span>` : ''}</button>`).join('')}
      <div class="divider" style="margin:12px 16px"></div>
      <div class="dr-h">Ton compte</div>
      <button class="dr-item" type="button" data-go="#parametres/compte">${av('adrien', 'sm')}<span>${h(D.moi.nom)}<small class="muted" style="display:block;font-size:12px;font-weight:400">${h(D.moi.role)} · opérateur</small></span></button>
      <button class="dr-item" type="button" data-dialog="deconnexion">${ico('logout')}Se déconnecter</button>
    </aside>`;
  }

  // ── Les écrans et les routes ──────────────────────────────────────────
  const ecrans = {};
  const state = { nav: 'chat', back: '#chat', depth: 0, route: '' };
  const ecran = (id, vue) => { ecrans[id] = vue; };
  function parse() {
    const raw = decodeURIComponent(location.hash.slice(1)) || 'chat';
    const [id, ...args] = raw.split('/');
    return { id: ecrans[id] ? id : 'chat', args: ecrans[id] ? args : [], raw };
  }
  function render() {
    const { id, args, raw } = parse();
    const vue = ecrans[id](args) || {};
    state.nav = vue.nav || id;
    state.back = vue.back || '#chat';
    state.route = '#' + raw;
    const showNav = vue.racine && v.nav === 'barre';
    const app = $('#app');
    app.innerHTML = `<div class="scr${vue.cls ? ' ' + vue.cls : ''}${showNav ? '' : ' no-nav'}" data-screen="${id}">${vue.html}</div>${showNav ? navbar(state.nav) : ''}`;
    closeAll();
    if (vue.after) vue.after(app.firstElementChild);
    // un fil de conversation s'ouvre sur ses derniers messages
    app.querySelectorAll('[data-bottom]').forEach((el) => { el.scrollTop = el.scrollHeight; });
    notes(vue, raw);
  }
  function go(route) {
    if (!route) return;
    if (route === location.hash || (route === '#chat' && !location.hash)) { render(); return; }
    state.depth++;
    location.hash = route;
  }
  function back() {
    if (state.depth > 0) { state.depth--; history.back(); } else { location.replace(state.back); }
  }

  // ── Feuilles, menus, fenêtres, tiroir, messages furtifs ───────────────
  const sheets = {}, menus = {}, dialogs = {};
  const overlay = () => $('#overlay');
  function closeAll() { overlay().innerHTML = ''; }
  function sheet(title, body, extra) {
    overlay().innerHTML = `<div class="scrim" data-close></div><div class="sheet" role="dialog"><div class="handle"></div>
      ${title ? `<div class="sh-title"><span>${title}</span>${extra || ''}</div>` : ''}<div class="sh-body">${body}</div></div>`;
  }
  function dialog(title, body, buttons) {
    overlay().innerHTML = `<div class="scrim" data-close></div><div class="dialog" role="alertdialog"><h2>${title}</h2>${body}<div class="btns">${buttons}</div></div>`;
  }
  function menu(anchor, items) {
    const ph = $('#phone').getBoundingClientRect(), r = anchor.getBoundingClientRect();
    const html = items.map((it) => it === '-' ? '<hr>' : `<button type="button" class="${it.cls || ''}" ${it.go ? `data-go="${it.go}"` : ''} ${it.snack ? `data-snack="${h(it.snack)}"` : ''} ${it.dialog ? `data-dialog="${it.dialog}"` : ''} ${it.sheet ? `data-sheet="${it.sheet}"` : ''}>${it.ico ? ico(it.ico) : ''}${h(it.l)}</button>`).join('');
    const topPx = Math.min(r.bottom - ph.top - 8, ph.height - 60 - items.length * 48);
    overlay().innerHTML = `<div class="scrim" data-close style="background:transparent"></div><div class="menu" role="menu" style="top:${topPx}px;right:${Math.max(8, ph.right - r.right)}px">${html}</div>`;
  }
  function snack(txt, action) {
    const box = $('#snacks');
    const el = document.createElement('div');
    el.className = 'snack';
    el.innerHTML = `<span>${h(txt)}</span>${action ? `<b>${h(action)}</b>` : ''}`;
    box.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }
  dialogs.deconnexion = () => dialog('Se déconnecter ?', '<p>Les messages, les fichiers et les vignettes gardés sur ce téléphone seront effacés. Ils restent sur le serveur.</p>',
    '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="Maquette : rien n\'est déconnecté.">Se déconnecter</button>');

  function onClick(e) {
    const t = e.target;
    const el = (s) => t.closest(s);
    let x;
    if ((x = el('[data-close]'))) { closeAll(); if (x.dataset.snack) snack(x.dataset.snack); e.preventDefault(); return; }
    if ((x = el('[data-go]'))) { e.preventDefault(); if (x.dataset.snack) snack(x.dataset.snack); go(x.dataset.go); return; }
    if ((x = el('[data-back]'))) { e.preventDefault(); back(); return; }
    if ((x = el('[data-sheet]')) && sheets[x.dataset.sheet]) { e.preventDefault(); sheets[x.dataset.sheet](x); return; }
    if ((x = el('[data-menu]')) && menus[x.dataset.menu]) { e.preventDefault(); menu(x, menus[x.dataset.menu](x)); return; }
    if ((x = el('[data-dialog]')) && dialogs[x.dataset.dialog]) { e.preventDefault(); dialogs[x.dataset.dialog](x); return; }
    if ((x = el('[data-drawer]'))) { e.preventDefault(); overlay().innerHTML = drawer(); return; }
    if ((x = el('[data-chip]'))) {
      const radio = x.dataset.chip;
      if (radio) x.parentNode.querySelectorAll(`[data-chip="${radio}"]`).forEach((c) => { if (c !== x) setChip(c, false); });
      setChip(x, !x.classList.contains('on'));
    }
    if ((x = el('[data-seg] > button'))) { x.parentNode.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === x))); }
    if ((x = el('[data-fold]'))) {
      const target = x.closest('[data-foldroot]')?.querySelector(x.dataset.fold) || $(x.dataset.fold);
      if (target) { target.hidden = !target.hidden; x.querySelector('.fold-ico')?.setAttribute('href', target.hidden ? '#i-chev-down' : '#i-chev-up'); }
    }
    if ((x = el('[data-snack]')) && !x.matches('[data-go],[data-close]')) snack(x.dataset.snack);
    if (el('.menu button')) closeAll();
  }
  function setChip(c, on) {
    c.classList.toggle('on', on);
    const first = c.querySelector('.ico');
    if (on && !c.dataset.ico0) c.dataset.ico0 = first ? first.outerHTML : '';
    if (first) first.remove();
    c.insertAdjacentHTML('afterbegin', on ? ico('check', 'xs') : (c.dataset.ico0 || ''));
  }

  // ── Le panneau à côté du téléphone ────────────────────────────────────
  const INDEX = [];
  const index = (groupe, liens) => INDEX.push([groupe, liens]);
  function notes(vue, raw) {
    const n = vue.notes || {};
    const li = (a) => a.map((x) => `<li>${x}</li>`).join('');
    $('#pn-notes').innerHTML = `<h2>Cet écran</h2><h3>${n.titre || ''}</h3>
      ${n.reprend && n.reprend.length ? `<h4>Ce qu'il montre</h4><ul>${li(n.reprend)}</ul>` : ''}
      ${n.trancher && n.trancher.length ? `<h4 class="q">À trancher</h4><ol>${li(n.trancher)}</ol>` : ''}`;
    $('#pn-index').innerHTML = INDEX.map(([g, liens]) => `<div><b>${g}</b>${liens.map(([l, r]) => `<a href="${r}" class="${r === '#' + raw ? 'on' : ''}">${l}</a>`).join('')}</div>`).join('');
  }
  function panel() {
    document.querySelectorAll('[data-variant]').forEach((seg) => {
      const k = seg.dataset.variant;
      const cur = () => (k === 'theme' ? document.documentElement.dataset.theme : v[k]);
      const paint = () => seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === cur())));
      paint();
      seg.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (k === 'theme') { document.documentElement.dataset.theme = b.dataset.v; store.set('theme', b.dataset.v); }
        else { v[k] = b.dataset.v; store.set(k, b.dataset.v); }
        paint();
        render();
      });
    });
    $('#pn-index').addEventListener('click', (e) => {
      const a = e.target.closest('a');
      if (!a) return;
      e.preventDefault();
      state.depth = 0;
      location.replace(a.getAttribute('href'));
    });
  }

  function start() {
    panel();
    $('#phone').addEventListener('click', onClick);
    window.addEventListener('hashchange', render);
    window.addEventListener('resize', () => { if (parse().id === 'chat') render(); });
    render();
  }

  return { D, h, ico, who, av, grp, face, faceDot, faceBtn, stage, top, act, tabs, chips, sw, ecran, go, back, render, sheet, dialog, menu, snack,
    sheets, menus, dialogs, index, closeAll, counts, v, state, initiales, $, start };
})();
