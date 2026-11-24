/* Agenda — créer et modifier un événement (proposé le 2026-11-23, pas encore validé). Le formulaire en plein écran,
   comme celui de Google Agenda sur Android : ✕ et « Enregistrer » en haut ; le titre ; journée entière, début, fin, le
   fuseau, la récurrence ; les participants, tirés des contacts ; la visio ; le lieu ; les rappels du fournisseur et « Mika
   te le rappelle » (rose) ; l'agenda ; la description ; occupé ou disponible, la visibilité. Chaque choix s'ouvre dans une
   feuille ou une fenêtre d'Android (la date dans un calendrier, l'heure dans une liste de demi-heures).
   Modifier un événement récurrent demande lequel : Cet événement · Celui-ci et les suivants · Tous.
   Routes : #agenda/nouveau, #agenda/modifier/<id>[@AAAA-MM-JJ][/question], #agenda/dupliquer/<id>. */
(function () {
  const { h, ico, av, D } = A;
  const X = A.agenda;
  const { G, S, AG } = X;
  const pad = (n) => String(n).padStart(2, '0');
  const JC = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
  const MC = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const dateDite = (d) => `${JC[d.getDay()]} ${d.getDate()} ${MC[d.getMonth()]} ${d.getFullYear()}`;
  const memeJour = (a, b) => X.ymd(a) === X.ymd(b);

  // Les rappels qu'envoie le fournisseur lui-même (l'agenda du système n'en a pas : c'est Mika qui rappelle).
  const FOURN = { travail: ['10 minutes avant'], perso: ['30 minutes avant'], famille: ['1 jour avant, à 18:00'], 'outlook-cal': ['15 minutes avant'] };
  const nomFourn = (a) => { const c = X.CPT[a.compte]; return !c ? '' : { caldav: 'd\'Outlook (DavMail)', google: 'de Google', microsoft: 'de Microsoft' }[c.sorte] || ''; };
  const VISIO = { '': 'Ajouter une visio', teams: 'Réunion Teams, créée par Outlook', meet: 'Google Meet, créé par Google', lien: 'Un lien collé' };
  const VIS = { defaut: 'Visibilité par défaut', publique: 'Publique', privee: 'Privée : on ne voit que « occupé »' };

  let form = null;
  function optRec(d) {
    return [['', 'Ne se répète pas'], ['jour', 'Chaque jour'], ['semaine', `Chaque semaine, le ${X.JOURS[d.getDay()]}`], ['mois', `Chaque mois, le ${X.num(d)}`],
      ['an', `Chaque année, le ${X.num(d)} ${X.MOIS[d.getMonth()]}`], ['perso', 'Personnalisée…']];
  }
  function init(mode, cle) {
    const o = cle ? X.trouver(cle) : null;
    const ev = o ? o.ev : null;
    const nv = X.nouveau || {};
    const jour = o ? o.jour : nv.jour ? X.lireJ(nv.jour) : X.etat.date;
    const deb = o ? o.deb : nv.deb != null ? nv.deb : (memeJour(jour, X.AUJ) ? Math.ceil((X.MAINTENANT + 1) / 30) * 30 : 600);
    const agOk = ev && AG[ev.agenda].ecrire && X.proprio(AG[ev.agenda]);
    const agenda = ev ? (agOk ? ev.agenda : 'mon') : 'mon';
    form = { route: location.hash.replace(/\/question$/, ''), nv: X.nouveau, mode, cle, o, prop: !!(ev && ev.proposition && S.proposition === 'attend'),
      titre: ev ? (mode === 'dupliquer' ? ev.titre + (agOk ? ' (copie)' : '') : ev.titre) : '',
      journee: o ? o.journee : false, d1: jour, d2: o ? o.fin : jour, h1: deb, h2: Math.min(o ? o.finMin : deb + 60, 1439),
      rec: ev && ev.rec ? ev.rec.freq : '', lieu: (ev && ev.lieu) || '', visio: ev && ev.visio ? 'teams' : '', desc: (ev && ev.desc) || '', agenda,
      mika: ev ? (ev.rappel || AG[agenda].rappel) : AG[agenda].rappel, fourn: [...(FOURN[agenda] || [])],
      dispo: ev && ev.dispo === 'libre' ? 'libre' : 'occupe', vis: 'defaut',
      ppl: ev && ev.p ? ev.p.filter(([k]) => k !== 'adrien').map(([k]) => k) : [], q: '' };
  }
  function lire() {
    const f = document.querySelector('[data-agform]');
    if (!f || !form) return;
    f.querySelectorAll('[data-ff]').forEach((x) => { form[x.dataset.ff] = x.type === 'checkbox' ? x.checked : x.value; });
  }
  const r = (i, corps, attrs, cls) => `<${attrs ? `button type="button" ${attrs}` : 'div'} class="ag-ff-r${cls ? ' ' + cls : ''}">${i ? `<span class="ag-f-i">${ico(i)}</span>` : '<span class="ag-f-i"></span>'}${corps}</${attrs ? 'button' : 'div'}>`;
  function puce(k) {
    const p = typeof k === 'string' ? A.who(k) : k;
    return `<span class="cx-chip">${X.avP(k, 'xs')}<span>${h(p.nom)}</span><button type="button" data-agpplx="${h(typeof k === 'string' ? k : k.nom)}" aria-label="Retirer ${h(p.nom)}">${ico('x')}</button></span>`;
  }
  function suggestions() {
    const q = (form.q || '').trim();
    if (!q) return '';
    const n = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    const gens = Object.entries(D.personnes).filter(([k, p]) => k !== 'adrien' && !form.ppl.includes(k) && p.moyens.some((m) => m[0] === 'mail')
      && n(p.nom + ' ' + p.moyens.map((m) => m[1]).join(' ')).includes(n(q))).slice(0, 5);
    const lignes = gens.map(([k, p]) => `<button class="cx-ac-row" type="button" data-agpplk="${k}">${av(k, 'sm')}<span class="txt"><span class="nm"><b>${h(p.nom)}</b></span>
      <small>${h(p.moyens.find((m) => m[0] === 'mail')[1])}</small>${p.compte ? '<small class="mk-txt">a un compte : l\'invitation lui arrive aussi dans Mika</small>' : ''}</span></button>`).join('');
    const adr = q.includes('@') ? `<button class="cx-ac-row" type="button" data-agpplk="@${h(q)}"><span class="av sm grp">${ico('at', 'xxs')}</span><span class="txt"><b>${h(q)}</b><small>une adresse</small></span></button>` : '';
    return `<div class="cx-ac ag-ac">${lignes + adr || '<div class="cx-ac-none">Personne parmi tes contacts. Tape une adresse.</div>'}</div>`;
  }
  function corps() {
    const f = form, a = AG[f.agenda], o = f.o;
    const recs = optRec(f.d1), recDit = (recs.find(([k]) => k === f.rec) || recs[0])[1];
    return `${f.prop ? `<div class="ag-box mk" style="margin:4px 16px 8px">${A.face(28)}<div class="grow"><div class="ag-box-t">${ico('sparkle', 'xs')}Ce que Mika propose</div><p>Change ce que tu veux : « Ajouter » l'enregistre dans ton agenda, avec tes changements.</p></div></div>` : ''}
      <div class="ag-ff-titre"><input data-ff="titre" placeholder="Ajouter un titre" value="${h(f.titre)}" aria-label="Titre"></div>
      <div class="ag-ff">
        ${r('clock', `<span class="grow">Journée entière</span>${A.sw(f.journee, 'data-ff="journee" data-agjournee')}`)}
        <div class="ag-ff-r"><span class="ag-f-i"></span><button class="ag-ff-v grow" type="button" data-agdate="d1">${h(dateDite(f.d1))}</button>${f.journee ? '' : `<button class="ag-ff-v" type="button" data-agheure="h1">${X.hm(f.h1)}</button>`}</div>
        <div class="ag-ff-r"><span class="ag-f-i"></span><button class="ag-ff-v grow" type="button" data-agdate="d2">${h(dateDite(f.d2))}</button>${f.journee ? '' : `<button class="ag-ff-v" type="button" data-agheure="h2">${X.hm(f.h2)}</button>`}</div>
        ${f.journee ? '' : r('globe', '<span class="grow">Heure normale d\'Europe centrale</span><small class="muted">UTC+1</small>', 'data-snack="Maquette : la liste des fuseaux"')}
        ${r('repeat', `<span class="grow">${h(recDit)}</span>`, 'data-sheet="ag-frec"')}
      </div>
      <div class="ag-ff">
        <div class="ag-ff-r ag-ff-ppl"><span class="ag-f-i">${ico('users')}</span><span class="cx-rcpt grow">${f.ppl.map(puce).join('')}<input data-agppl value="${h(f.q)}" placeholder="${f.ppl.length ? '' : 'Ajouter des participants'}" autocomplete="off" aria-label="Participants"></span></div>
        <div data-agsugg>${suggestions()}</div>
        <div class="ag-ff-r"><span class="ag-f-i"></span><button class="chip mk" type="button" data-agcreneau>${ico('sparkle', 'xs')}Trouver un créneau avec eux</button></div>
      </div>
      <div class="ag-ff">${r('video', `<span class="grow${f.visio ? '' : ' muted'}">${h(VISIO[f.visio])}</span>`, 'data-sheet="ag-fvisio"')}</div>
      <div class="ag-ff"><div class="ag-ff-r"><span class="ag-f-i">${ico('pin')}</span><input class="grow" data-ff="lieu" value="${h(f.lieu)}" placeholder="Ajouter un lieu" aria-label="Lieu"><button class="ibtn" type="button" data-go="#carte" data-snack="La carte s'ouvre pour choisir le lieu" aria-label="Le chercher sur la carte">${ico('map', 'sm')}</button></div></div>
      <div class="ag-ff">
        ${a.compte === 'systeme' ? r('bell', '<span class="grow muted">L\'agenda du système n\'envoie rien lui-même : c\'est Mika qui te le rappelle.</span>')
          : `${f.fourn.map((x, i) => r(i ? '' : 'bell', `<span class="grow">${h(x)}<small class="muted"> · notification ${h(nomFourn(a))}</small></span><button class="ibtn" type="button" data-agfournx="${i}" aria-label="Retirer">${ico('x', 'sm')}</button>`)).join('')}
            ${r(f.fourn.length ? '' : 'bell', '<span class="grow ag-a">Ajouter une notification</span>', 'data-sheet="ag-ffourn"')}`}
        ${r('sparkle', `<span class="grow"><b>${f.mika === 'non' ? 'Mika ne te le rappelle pas' : `Mika te le rappelle ${h(X.rappelDit(f.mika))}`}</b><small>dans le chat, ou par une notification</small></span>`, 'data-sheet="ag-fmika"', 'mk')}
      </div>
      <div class="ag-ff">${r('agenda', `<span class="grow"><b>${X.sw(a.couleur, 'xs')} ${h(a.nom)}</b><small>${h(X.fournisseur(a))} · ${h(X.CPT[a.compte].adresse)}</small></span>`, 'data-sheet="ag-fagenda"')}</div>
      <div class="ag-ff"><div class="ag-ff-r top"><span class="ag-f-i">${ico('threads')}</span><textarea class="grow" rows="3" data-ff="desc" placeholder="Ajouter une description" aria-label="Description">${h(f.desc)}</textarea></div></div>
      <div class="ag-ff">
        <div class="ag-ff-r"><span class="ag-f-i">${ico('eye')}</span><span class="grow">Afficher comme</span><div class="seg ag-seg" data-agdispo><button type="button" data-v="occupe" aria-pressed="${f.dispo === 'occupe'}">Occupé</button><button type="button" data-v="libre" aria-pressed="${f.dispo === 'libre'}">Disponible</button></div></div>
        ${r('lock', `<span class="grow">${h(VIS[f.vis])}</span>`, 'data-sheet="ag-fvis"')}
      </div>
      <p class="note ag-ff-pied">${ico('refresh', 'xs')} Enregistré dans « ${h(a.nom)} », il part tout de suite ${h(X.chez(a))}.${o && o.ev.p && o.ev.p.length > 1 ? ' Les participants sont prévenus.' : ''}</p>`;
  }
  function repeindre(focus) {
    const b = document.querySelector('[data-agform]');
    if (!b) return;
    lire();
    const top = b.scrollTop;
    b.innerHTML = corps();
    b.scrollTop = top;
    if (focus) { const i = b.querySelector(focus); if (i) { i.focus(); if (i.setSelectionRange) i.setSelectionRange(i.value.length, i.value.length); } }
  }

  function formulaire(mode, cle, extra) {
    if (!form || form.route !== location.hash.replace(/\/question$/, '') || (mode === 'nouveau' && X.nouveau && form.nv !== X.nouveau)) init(mode, cle);
    const f = form;
    if (cle && !f.o) return { nav: 'agenda', back: X.routeVue(), html: `${A.top({ title: 'Événement', small: true, back: true, face: false })}<div class="body"><div class="cx-empty">${ico('agenda')}<b>Introuvable</b></div></div>`, notes: {} };
    const titre = mode === 'modifier' ? (f.prop ? 'Ce que Mika propose' : 'Modifier') : mode === 'dupliquer' ? 'Dupliquer' : 'Nouvel événement';
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'agenda', back: X.routeVue(), cls: 'ag-scr ag-formscr',
      html: `<header class="top ag-ftop"><button class="ibtn" type="button" data-back aria-label="Fermer sans enregistrer">${ico('x')}</button><div class="t-title sm"><b class="ellipsis">${h(titre)}</b></div>
          <button class="btn filled sm ag-save" type="button" data-agsave>${f.prop ? `${ico('check')}Ajouter` : 'Enregistrer'}</button></header>
        <div class="body ag-form" data-agform>${corps()}</div>`,
      notes: {
        titre: `Agenda · ${titre} (proposé)`,
        reprend: [
          'En plein écran, comme Google Agenda sur Android : ✕ ferme sans rien garder, « Enregistrer » en haut à droite.',
          'Le titre en grand ; journée entière, début, fin (la date dans un calendrier, l\'heure dans une liste), le fuseau, la récurrence (une feuille, « Personnalisée… » comprise).',
          'Les participants, tirés de tes contacts (tape « so » ou « lé ») : une adresse tapée marche aussi ; celle qui a un compte reçoit aussi l\'invitation dans Mika. ✦ « Trouver un créneau avec eux » : Mika regarde les agendas que tu vois.',
          'La visio (Teams par Outlook, Meet par Google), le lieu (vers la Carte), les rappels du fournisseur, puis, en rose, « Mika te le rappelle », qui suit d\'abord l\'agenda choisi.',
          'L\'agenda : seulement ceux où tu peux écrire (ni l\'agenda de Léa, ni les abonnements, ni celui de Mika). Puis la description, occupé ou disponible, la visibilité.',
          f.prop ? 'Modifier ce que Mika propose : son titre en tête, et « Ajouter » enregistre avec tes changements.' : '',
          f.o && f.o.ev.rec && mode === 'modifier' ? 'Un événement récurrent : « Enregistrer » demande lequel (Cet événement · Celui-ci et les suivants · Tous).' : '',
        ].filter(Boolean),
        trancher: [
          'L\'heure dans une liste de demi-heures (ici, rapide au pouce), ou le cadran d\'Android ?',
          'Les rappels du fournisseur ET « Mika te le rappelle » : deux lignes qui peuvent sonner deux fois. Garder les deux, ou n\'en montrer qu\'une (celle de Mika) et couper celle du fournisseur par défaut ?',
          'Les invitations entre personnes qui ont un compte : une invitation dans son Agenda (Accepter · Peut-être · Refuser), ou seulement par Mika ?',
          'Occupé / disponible et visibilité : toujours là (ici), ou repliés sous « Plus d\'options » comme Google ?',
        ],
      },
      after(root) {
        if (extra === 'question' && f.o) question(f.o, 'modifier');
        else if (mode === 'nouveau') { const t = root.querySelector('[data-ff="titre"]'); if (t && !t.value) setTimeout(() => t.focus(), 40); }
      },
    };
  }

  // ── Les feuilles et fenêtres du formulaire ────────────────────────────
  const liste = (k, opts, cur, ic) => opts.map(([v, l, s]) => `<button class="li${v === cur ? ' sel' : ''}" type="button" data-agfset="${k}:${v}"><span class="lead">${typeof ic === 'function' ? ic(v) : ico(ic || 'check')}</span><span class="txt"><b>${h(l)}</b>${s ? `<small>${h(s)}</small>` : ''}</span>${v === cur ? ico('check') : ''}</button>`).join('');
  A.sheets['ag-frec'] = () => { lire(); A.sheet('Se répète', liste('rec', optRec(form.d1), form.rec, 'repeat')); };
  A.sheets['ag-fvisio'] = () => { lire(); A.sheet('Visio', liste('visio', Object.entries(VISIO).map(([k, l]) => [k, k ? l : 'Pas de visio', k === 'teams' ? 'le lien part avec l\'invitation, par l\'agenda Travail' : k === 'meet' ? 'seulement sur un agenda Google' : '']), form.visio, 'video')); };
  A.sheets['ag-fmika'] = () => { lire(); A.sheet('Mika te le rappelle', `<p class="note" style="padding:0 24px 6px">Dans le chat, ou par une notification si l'app est fermée. Par défaut, le réglage de « ${h(AG[form.agenda].nom)} » (${h(X.rappelDit(AG[form.agenda].rappel))}).</p>${liste('mika', X.RAPPELS, form.mika, (v) => ico(v === 'non' ? 'x' : 'bell'))}`); };
  A.sheets['ag-fvis'] = () => { lire(); A.sheet('Visibilité', liste('vis', Object.entries(VIS).map(([k, l]) => [k, l, k === 'defaut' ? 'celle de l\'agenda' : '']), form.vis, 'lock')); };
  A.sheets['ag-ffourn'] = () => { lire(); A.sheet(`Une notification ${h(nomFourn(AG[form.agenda]))}`, liste('fourn', ['5 minutes avant', '10 minutes avant', '30 minutes avant', '1 heure avant', '1 jour avant, à 18:00'].map((x) => [x, x]), null, 'bell')); };
  A.sheets['ag-fagenda'] = () => {
    lire();
    A.sheet('Agenda', `<p class="note" style="padding:0 24px 6px">Seuls ceux où tu peux écrire : pas les abonnements, ni l'agenda de Léa, ni celui de Mika.</p>
      ${X.ecrivables().map((a) => `<button class="li${a.id === form.agenda ? ' sel' : ''}" type="button" data-agfset="agenda:${a.id}"><span class="lead">${X.sw(a.couleur, 'lg')}</span><span class="txt"><b>${h(a.nom)}</b><small>${h(X.fournisseur(a))} · ${h(X.CPT[a.compte].adresse)}</small></span>${a.id === form.agenda ? ico('check') : ''}</button>`).join('')}`);
  };
  // La date : le calendrier d'Android, dans une fenêtre.
  let dp = null;
  function fenetreDate(k) {
    lire();
    const d = form[k];
    dp = dp && dp.k === k ? dp : { k, sel: d, m: new Date(d.getFullYear(), d.getMonth(), 1) };
    A.dialog(k === 'd1' ? 'Début' : 'Fin', `<div class="ag-dp"><div class="ag-dp-d">${h(dateDite(dp.sel))}</div>
      <div class="ag-dp-h"><b>${h(X.cap(X.MOIS[dp.m.getMonth()]))} ${dp.m.getFullYear()}</b><span class="grow"></span><button class="ibtn" type="button" data-agdpm="-1" aria-label="Mois précédent">${ico('chev-left', 'sm')}</button><button class="ibtn" type="button" data-agdpm="1" aria-label="Mois suivant">${ico('chev-right', 'sm')}</button></div>
      <div class="ag-mm ag-dp-g">${X.grilleMois(dp.m, { picker: true, sel: dp.sel })}</div></div>`,
    `<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-agdpok>OK</button>`);
  }
  // L'heure : une liste de demi-heures, celle choisie en vue.
  function feuilleHeure(k) {
    lire();
    const cur = form[k], base = k === 'h2' ? form.h1 : 0;
    const opts = [];
    for (let m = k === 'h2' ? base + 30 : 0; m < 1440; m += 30) {
      const dur = m - base;
      opts.push([String(m), X.hm(m), k === 'h2' ? (dur < 60 ? `${dur} min` : `${Math.floor(dur / 60)} h${dur % 60 ? ' 30' : ''}`) : '']);
    }
    A.sheet(k === 'h1' ? 'Début' : 'Fin', `<div data-agheures>${opts.map(([v, l, s]) => `<button class="li ag-hli${+v === cur ? ' sel' : ''}" type="button" data-agfset="${k}:${v}"><span class="txt"><b>${l}</b></span>${s ? `<small class="muted">${s}</small>` : ''}${+v === cur ? ico('check') : ''}</button>`).join('')}</div>`);
    const sel = document.querySelector('#overlay .ag-hli.sel') || document.querySelector('#overlay .ag-hli');
    const box = document.querySelector('#overlay .sh-body');
    if (sel && box) box.scrollTop = sel.offsetTop - 120;
  }

  // ── Enregistrer, et la question d'un événement récurrent ──────────────
  function finir(quoi) {
    const f = form, a = AG[f.agenda];
    if (f.prop) S.proposition = 'ajoute';
    const txt = f.prop ? `Ajouté à « ${a.nom} », avec tes changements : parti ${X.chez(a)}.` : `${quoi || (f.titre.trim() ? `« ${f.titre.trim()} » enregistré` : 'Enregistré')} dans « ${a.nom} » : parti ${X.chez(a)}.`;
    X.nouveau = null;
    form = null;
    A.closeAll();
    if (A.state.depth > 0) A.back(); else location.replace(f.mode === 'modifier' && f.cle ? '#agenda/evenement/' + f.cle : X.routeVue());
    A.snack(txt);
  }
  function question(o, quoi) {
    const ev = o.ev, a = AG[ev.agenda];
    const c = X.CPT[a.compte];
    A.dialog(quoi === 'supprimer' ? 'Supprimer un événement récurrent' : 'Modifier un événement récurrent',
      `<p>« ${h(ev.titre)} » se répète : ${h(X.recurrence(ev).toLowerCase())}.</p>
      <div class="ag-radios">${[['un', `Cet événement`, X.jourCourt(o.jour)], ['suite', 'Celui-ci et les suivants', ''], ['tous', 'Tous les événements', '']].map(([v, l, s], i) => `<label class="ag-rad"><input type="radio" name="agrq" value="${v}"${i ? '' : ' checked'}><span class="ag-radio"></span><span>${h(l)}${s ? ` <small class="muted">· ${h(s)}</small>` : ''}</span></label>`).join('')}</div>
      ${ev.p && ev.p.length > 1 && c ? `<p class="muted" style="font-size:13px">Les participants sont prévenus par ${h(G.sortes[c.sorte].nom)}.</p>` : ''}`,
    `<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-agrecok="${quoi}:${h(o.cle)}"${quoi === 'supprimer' ? ' style="color:var(--danger)"' : ''}>${quoi === 'supprimer' ? 'Supprimer' : 'OK'}</button>`);
  }

  // ── Les gestes ─────────────────────────────────────────────────────────
  document.addEventListener('click', (e) => {
    const t = e.target;
    let x;
    if ((x = t.closest('[data-agfset]'))) {
      const i = x.dataset.agfset.indexOf(':'), k = x.dataset.agfset.slice(0, i), v = x.dataset.agfset.slice(i + 1);
      if (k === 'h1') { const dur = form.h2 - form.h1; form.h1 = +v; form.h2 = Math.min(1439, +v + Math.max(30, dur)); }
      else if (k === 'h2') form.h2 = +v;
      else if (k === 'fourn') form.fourn.push(v);
      else if (k === 'agenda') { form.agenda = v; form.mika = AG[v].rappel; form.fourn = [...(FOURN[v] || [])]; }
      else form[k] = v;
      A.closeAll();
      repeindre();
      if (k === 'agenda') A.snack(`Dans « ${AG[v].nom} » : ses rappels, et « Mika te le rappelle » ${X.rappelDit(AG[v].rappel)}`);
      return;
    }
    if ((x = t.closest('[data-agfournx]'))) { lire(); form.fourn.splice(+x.dataset.agfournx, 1); repeindre(); return; }
    if ((x = t.closest('[data-agdate]'))) { dp = null; fenetreDate(x.dataset.agdate); return; }
    if ((x = t.closest('[data-agdpm]'))) { dp.m = new Date(dp.m.getFullYear(), dp.m.getMonth() + +x.dataset.agdpm, 1); fenetreDate(dp.k); return; }
    if ((x = t.closest('[data-agpick-j]'))) { dp.sel = X.lireJ(x.dataset.agpickJ); fenetreDate(dp.k); return; }
    if ((x = t.closest('[data-agdpok]'))) {
      form[dp.k] = dp.sel;
      if (dp.k === 'd1' && form.d2 < form.d1) form.d2 = form.d1;
      if (dp.k === 'd2' && form.d2 < form.d1) form.d1 = form.d2;
      dp = null; A.closeAll(); repeindre(); return;
    }
    if ((x = t.closest('[data-agheure]'))) { feuilleHeure(x.dataset.agheure); return; }
    if ((x = t.closest('[data-agdispo] > button'))) { form.dispo = x.dataset.v; x.parentNode.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', String(b === x))); return; }
    if ((x = t.closest('[data-agpplk]'))) {
      lire();
      const k = x.dataset.agpplk;
      form.ppl.push(k.startsWith('@') ? { nom: k.slice(1), adr: k.slice(1) } : k);
      form.q = '';
      repeindre('[data-agppl]');
      return;
    }
    if ((x = t.closest('[data-agpplx]'))) { lire(); form.ppl = form.ppl.filter((k) => (typeof k === 'string' ? k : k.nom) !== x.dataset.agpplx); repeindre(); return; }
    if ((x = t.closest('[data-agcreneau]'))) {
      A.snack(form.ppl.length ? `Mika a regardé vos agendas : mercredi 25, 10:00 – 11:00, tout le monde est libre.` : 'Ajoute d\'abord des participants : elle cherchera un créneau où chacun est libre.');
      return;
    }
    if ((x = t.closest('[data-agsave]'))) {
      lire();
      if (form.mode === 'modifier' && form.o && form.o.ev.rec) { question(form.o, 'modifier'); return; }
      finir();
      return;
    }
    if ((x = t.closest('[data-agrecok]'))) {
      const [quoi, cle] = x.dataset.agrecok.split(/:(.*)/s);
      const v = (document.querySelector('#overlay input[name="agrq"]:checked') || {}).value || 'un';
      const o = X.trouver(cle);
      if (quoi === 'supprimer') {
        if (v === 'un') S.supprimes[o.cle] = true; else S.supprimes[o.ev.id] = true;
        A.closeAll();
        location.replace(X.routeVue());
        A.snack(`${v === 'un' ? 'Cet événement est supprimé' : v === 'suite' ? 'Celui-ci et les suivants sont supprimés' : 'Tous sont supprimés'} de « ${AG[o.ev.agenda].nom} » : effacé ${X.chez(AG[o.ev.agenda])} aussi.`);
        return;
      }
      if (!form) init('modifier', cle);
      if (/\/question$/.test(location.hash)) history.replaceState(null, '', location.hash.replace(/\/question$/, ''));
      finir(v === 'un' ? 'Cet événement est modifié' : v === 'suite' ? 'Celui-ci et les suivants sont modifiés' : 'Tous sont modifiés');
    }
  });
  document.addEventListener('input', (e) => {
    if (e.target.matches('[data-agppl]')) { form.q = e.target.value; const s = document.querySelector('[data-agsugg]'); if (s) s.innerHTML = suggestions(); }
  });
  document.addEventListener('change', (e) => {
    if (e.target.matches('[data-agjournee]')) { form.journee = e.target.checked; repeindre(); }
  });
  document.addEventListener('keydown', (e) => {
    if (!e.target.matches('[data-agppl]')) return;
    if (e.key === 'Enter') { e.preventDefault(); const p = document.querySelector('[data-agpplk]'); if (p) p.click(); }
    if (e.key === 'Backspace' && !e.target.value && form.ppl.length) { lire(); form.ppl.pop(); repeindre('[data-agppl]'); }
  });

  X.formulaire = formulaire;
  X.question = question;
})();
