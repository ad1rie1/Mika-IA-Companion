/* Agenda — proposé le 2026-11-23, pas encore validé (output/agenda/CONCEPTION.md). Tous tes agendas en un seul écran,
   comme Google Agenda ou Outlook : le mini-mois et les agendas à gauche ; Jour · Semaine · Mois · Planning ; la fiche
   d'un événement dans un volet ; créer, modifier, partager ; les invitations. Le rose est à Mika : ce qu'elle a ajouté,
   ce qu'elle propose (hachuré, en attente de ton accord), et son agenda à elle, tiré de sa mémoire, en lecture seule.
   Les données sont dans agenda-donnees.js ; M.agenda les prête aux fichiers posés sur Paramètres, Outils et le chat. */
(function () {
  const { h, ico, av } = M;
  const D = M.D;
  const A = window.MIKA_AGENDA;
  const S = A.etat;
  S.supprimes = S.supprimes || {};
  const AG = Object.fromEntries(A.agendas.map((a) => [a.id, a]));
  const EV = Object.fromEntries(A.evenements.map((e) => [e.id, e]));
  const CPT = Object.fromEntries(A.comptes.map((c) => [c.id, c]));

  // ── Les dates ─────────────────────────────────────────────────────────
  const pad = (n) => String(n).padStart(2, '0');
  const JOURS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
  const JC = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
  const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  const MC = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const lireJ = (s) => { const [y, m, j] = s.split('-').map(Number); return new Date(y, m - 1, j); };
  const plus = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  const lundi = (d) => plus(d, -((d.getDay() + 6) % 7));
  const mem = (a, b) => ymd(a) === ymd(b);
  const ecartJ = (a, b) => Math.round((b - a) / 864e5);
  const min = (s) => { const [hh, mm] = s.split(':').map(Number); return hh * 60 + mm; };
  const hm = (m) => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
  const AUJ = lireJ(A.aujourdhui), MAINTENANT = min(A.heure);
  const ecart = (d) => ecartJ(AUJ, d);
  const num = (d) => (d.getDate() === 1 ? '1er' : String(d.getDate()));
  const jourDit = (d) => `${JOURS[d.getDay()]} ${num(d)} ${MOIS[d.getMonth()]}${d.getFullYear() !== AUJ.getFullYear() ? ' ' + d.getFullYear() : ''}`;
  const jourCourt = (d) => `${JC[d.getDay()]} ${d.getDate()} ${MC[d.getMonth()]}`;
  const jourProche = (d) => { const e = ecart(d); return e === 0 ? 'aujourd\'hui' : e === 1 ? 'demain' : e === -1 ? 'hier' : jourDit(d); };

  // ── Les agendas et leurs comptes ──────────────────────────────────────
  const NIVEAUX = {
    lire: ['Lire', 'voit ses événements dans son Agenda, sans rien y changer.'],
    preparer: ['Lire et préparer', 'les voit, et Mika peut y préparer un ajout pour elle ou lui : il n\'entre qu\'avec ton accord.'],
    servir: ['S\'en servir', 'Mika s\'en sert avec elle ou lui, en tête-à-tête : trouver un créneau, y ajouter un rendez-vous, selon ton tableau de droits.'],
  };
  const RAPPELS = [['non', 'Non'], ['15', '15 min avant'], ['30', '30 min avant'], ['60', '1 h avant'], ['veille', 'La veille au soir']];
  const rappelDit = (k) => ({ non: 'non', 15: '15 min avant', 30: '30 min avant', 60: '1 h avant', veille: 'la veille au soir' }[k] || k);
  const REPONSES = { oui: 'Accepter', peut: 'Peut-être', non: 'Refuser' };
  const compte = (a) => CPT[a.compte] || null;
  const proprio = (a) => a.groupe === 'mes' || a.groupe === 'abonnements';
  function fournisseur(a) {
    if (a.groupe === 'partages') return `de ${M.who(a.de).court} · ${NIVEAUX[a.niveau][0].toLowerCase()}`;
    if (a.groupe === 'mika') return 'sa mémoire · lecture seule';
    const c = compte(a);
    if (!c) return '';
    if (c.sorte === 'caldav') return 'CalDAV · DavMail';
    if (c.sorte === 'ical') return 'abonnement iCal';
    return A.sortes[c.sorte].nom;
  }
  // Où part une écriture : « chez Google », « chez Outlook, par DavMail »…
  function chez(a) {
    const c = compte(a);
    return c ? { systeme: 'sur ce serveur', caldav: 'chez Outlook, par DavMail', google: 'chez Google', microsoft: 'chez Microsoft', ical: '' }[c.sorte] : '';
  }
  const ecrivables = () => A.agendas.filter((a) => a.ecrire && a.visible && proprio(a));
  const sw = (couleur, cls) => `<span class="ag-sw${cls ? ' ' + cls : ''}" style="--c:var(--ag-${couleur})"></span>`;

  // ── Les occurrences d'une période (les récurrences dépliées) ──────────
  function occ(ev, d, fin) {
    return { ev, cle: ev.rec ? `${ev.id}@${ymd(d)}` : ev.id, jour: d, fin, journee: !!ev.journee,
      deb: ev.journee ? 0 : min(ev.de), finMin: ev.journee ? 1440 : min(ev.a) };
  }
  function occurrences(du, au) {   // du compris, au exclu
    const out = [];
    for (const ev of A.evenements) {
      const d0 = lireJ(ev.j), duree = ev.jusqu ? ecartJ(d0, lireJ(ev.jusqu)) : 0;
      const pousser = (d) => { const fin = plus(d, duree); if (fin >= du && d < au) out.push(occ(ev, d, fin)); };
      if (!ev.rec) pousser(d0);
      else if (ev.rec.freq === 'semaine') {
        const borne = ev.rec.jusqu ? lireJ(ev.rec.jusqu) : null;
        let d = d0 < du ? plus(d0, Math.floor(ecartJ(d0, du) / 7) * 7) : d0;
        for (; d < au; d = plus(d, 7)) if (!borne || d <= borne) pousser(d);
      } else if (ev.rec.freq === 'an') {
        for (let y = du.getFullYear() - 1; y <= au.getFullYear(); y++) { const d = new Date(y, d0.getMonth(), d0.getDate()); if (d >= d0) pousser(d); }
      }
    }
    return out.sort((a, b) => a.jour - b.jour || (b.journee - a.journee) || a.deb - b.deb);
  }
  function trouver(cle) {
    if (!cle) return null;
    const [id, j] = cle.split('@');
    const ev = EV[id];
    if (!ev) return null;
    if (ev.rec && !j) return occurrences(AUJ, plus(AUJ, 400)).find((o) => o.ev === ev) || null;
    const d = j ? lireJ(j) : lireJ(ev.j);
    return occ(ev, d, plus(d, ev.jusqu ? ecartJ(lireJ(ev.j), lireJ(ev.jusqu)) : 0));
  }
  // Ce qu'on voit : les agendas cochés ; une proposition en attente toujours (elle attend ta décision).
  function visible(o) {
    const ev = o.ev;
    if (S.supprimes[o.cle] || S.supprimes[ev.id]) return false;
    if (ev.proposition) return S.proposition === 'attend' || (S.proposition === 'ajoute' && AG[ev.agenda].coche);
    if (ev.invitation && S.invitations[ev.id] === 'non') return false;
    const a = AG[ev.agenda];
    return !!(a && a.visible && a.coche);
  }
  function sorte(o) {
    const ev = o.ev;
    if (ev.proposition) return S.proposition === 'attend' ? 'propose' : '';
    if (ev.invitation && !S.invitations[ev.id]) return 'invite';
    if (ev.invitation && S.invitations[ev.id] === 'peut') return 'peut';
    if (ev.agenda === 'mika') return 'mika';
    return '';
  }
  const couleur = (o) => (sorte(o) === 'propose' ? 'rose' : AG[o.ev.agenda].couleur);
  const passe = (o) => ecart(o.fin) < 0 || (ecart(o.jour) === 0 && !o.journee && o.finMin <= MAINTENANT);
  const ajouteParMika = (o) => !!(o.ev.parMika || (o.ev.proposition && S.proposition === 'ajoute'));
  const enAttente = () => A.evenements.filter((e) => e.invitation && !S.invitations[e.id] && !S.supprimes[e.id]).map((e) => trouver(e.id));
  const lieuCourt = (l) => String(l).split(' · ')[0];

  // ── L'état de l'écran ─────────────────────────────────────────────────
  const etat = { vue: null, date: AUJ, q: '', cherche: false, moisMini: null, mobileMois: false, nouveau: null, dernier: null, cle: null };
  const VUES = [['jour', 'Jour'], ['semaine', 'Semaine'], ['mois', 'Mois'], ['planning', 'Planning']];
  const HH = 48;   // la hauteur d'une heure dans la grille

  function lire(ctx) {
    const [a, ...r] = (ctx.item || '').split('/');
    const b = r.join('/') || null;
    const route = { vue: VUES.some((v) => v[0] === a) ? a : null, volet: null, modal: null, id: b };
    if (a === 'evenement' && b) route.volet = 'fiche';
    if (a === 'invitations') route.volet = 'invitations';
    if (a === 'nouveau' || a === 'modifier' || a === 'partager') route.modal = a;
    if (route.vue) etat.vue = route.vue;
    if (!etat.vue) etat.vue = M.mobile() ? 'planning' : 'semaine';
    if (ctx.route !== etat.dernier) {
      etat.dernier = ctx.route;
      etat.mobileMois = false;
      if (route.volet === 'fiche' || a === 'modifier') { const o = trouver(b); if (o) { etat.date = o.jour; etat.moisMini = null; } }
    }
    etat.cle = route.volet === 'fiche' ? b : null;
    return route;
  }
  const routeVue = () => '#agenda/' + etat.vue;

  function bornes() {
    const d = etat.date;
    if (etat.vue === 'jour') return [d, plus(d, 1)];
    if (etat.vue === 'semaine') { const l = lundi(d); return [l, plus(l, 7)]; }
    if (etat.vue === 'mois') {
      const l = lundi(new Date(d.getFullYear(), d.getMonth(), 1)), fin = new Date(d.getFullYear(), d.getMonth() + 1, 1);
      return [l, plus(l, Math.ceil(ecartJ(l, fin) / 7) * 7)];
    }
    return [d, plus(d, 28)];
  }
  function periode(court) {
    const d = etat.date, [du, au] = bornes(), der = plus(au, -1);
    if (etat.vue === 'jour') return court ? cap(jourCourt(d)) : `${cap(jourDit(d))}${d.getFullYear() === AUJ.getFullYear() ? ' ' + d.getFullYear() : ''}`;
    if (etat.vue === 'mois') return `${cap(MOIS[d.getMonth()])} ${d.getFullYear()}`;
    if (etat.vue === 'semaine') {
      if (du.getMonth() === der.getMonth()) return court ? `${du.getDate()} – ${der.getDate()} ${MC[der.getMonth()]}` : `${du.getDate()} – ${der.getDate()} ${MOIS[der.getMonth()]} ${der.getFullYear()}`;
      return `${du.getDate()} ${MC[du.getMonth()]} – ${der.getDate()} ${MC[der.getMonth()]}${court ? '' : ' ' + der.getFullYear()}`;
    }
    return court ? `Dès le ${d.getDate()} ${MC[d.getMonth()]}` : `À partir du ${jourDit(d)}`;
  }
  function deplacer(sens) {
    const d = etat.date;
    if (etat.vue === 'mois') { const m = new Date(d.getFullYear(), d.getMonth() + sens, 1); etat.date = m.getMonth() === AUJ.getMonth() && m.getFullYear() === AUJ.getFullYear() ? AUJ : m; }
    else etat.date = plus(d, etat.vue === 'jour' ? sens : etat.vue === 'planning' ? 28 * sens : 7 * sens);
    etat.moisMini = null;
  }
  const aujourdhuiVisible = () => { const [du, au] = bornes(); return AUJ >= du && AUJ < au; };

  // ── La barre de titre ─────────────────────────────────────────────────
  function actions(ctx) {
    const r = lire(ctx);
    const n = enAttente().length;
    const recherche = etat.cherche || etat.q
      ? `<label class="search ag-q ag-chercher">${ico('search', 'sm')}<input type="search" data-agq placeholder="Un titre, un lieu, une personne…" value="${h(etat.q)}"></label>`
      : `<button class="btn icon ghost ag-chercher" type="button" data-agchercher title="Chercher dans tes agendas">${ico('search')}</button>`;
    return `<div class="ag-tb">
      <div class="ag-tb-nav">
        <button class="btn icon ghost ag-m-only" type="button" data-agcals title="Tes agendas">${ico('menu')}</button>
        <button class="btn sm ag-auj-d" type="button" data-agauj title="Revenir à aujourd'hui, ${h(jourDit(AUJ))}">Aujourd'hui</button>
        <span class="btn-group"><button class="btn sm icon" type="button" data-agpas="-1" title="Précédent">${ico('chev-left', 'sm')}</button><button class="btn sm icon" type="button" data-agpas="1" title="Suivant">${ico('chev-right', 'sm')}</button></span>
        <button class="ag-periode" type="button" data-agperiode aria-expanded="${etat.mobileMois}"><span class="long">${h(periode())}</span><span class="court">${h(periode(true))}</span>${ico('chev-down', 'xs')}</button>
      </div>
      <span class="grow"></span>
      <div class="ag-tb-right">
        <div class="seg ag-vues" role="group" aria-label="La vue">${VUES.map(([k, l]) => `<button type="button" data-agvue="${k}" aria-pressed="${etat.vue === k && !etat.q}">${l}</button>`).join('')}</div>
        <span class="ag-tb-outils">${recherche}
        <button class="btn icon ghost ag-m-only ag-auj-m" type="button" data-agauj title="Revenir à aujourd'hui, ${h(jourDit(AUJ))}"><span class="ag-auj-ico">${AUJ.getDate()}</span></button>
        <a class="btn ag-inv-btn${r.volet === 'invitations' ? ' on' : ''}" href="#agenda/invitations" title="Les invitations qui attendent ta réponse">${ico('inbox', 'sm')}<span class="lbl">Invitations</span>${n ? `<b class="badge">${n}</b>` : ''}</a>
        <a class="btn primary icon ag-m-only ag-plus" href="#agenda/nouveau" title="Créer un événement">${ico('plus')}</a></span>
      </div></div>`;
  }

  // ── La colonne de gauche : Créer, le mini-mois, les agendas ───────────
  const GROUPES = [['mes', 'Mes agendas'], ['partages', 'Partagés avec moi'], ['abonnements', 'Abonnements'], ['mika', 'L\'agenda de Mika']];
  function miniMois() {
    const m = etat.moisMini || new Date(etat.date.getFullYear(), etat.date.getMonth(), 1);
    const debut = lundi(m), [du, au] = bornes();
    const bande = etat.vue === 'jour' || etat.vue === 'semaine';
    let cases = '';
    for (let i = 0; i < 42; i++) {
      const d = plus(debut, i), dans = bande && d >= du && d < au;
      const cls = [d.getMonth() !== m.getMonth() ? 'hors' : '', mem(d, AUJ) ? 'auj' : '', dans ? 'dans' : '', dans && mem(d, du) ? 'debut' : '',
        dans && mem(d, plus(au, -1)) ? 'fin' : '', mem(d, etat.date) && !mem(d, AUJ) ? 'sel' : ''].filter(Boolean).join(' ');
      cases += `<button type="button" class="${cls}" data-agjour="${ymd(d)}" aria-label="${h(jourDit(d))}"><i>${d.getDate()}</i></button>`;
    }
    return `<div class="ag-mini"><div class="ag-mini-head"><b>${cap(MOIS[m.getMonth()])} ${m.getFullYear()}</b>
      <button class="btn xs icon ghost" type="button" data-agmini="-1" title="Mois précédent">${ico('chev-left', 'xs')}</button>
      <button class="btn xs icon ghost" type="button" data-agmini="1" title="Mois suivant">${ico('chev-right', 'xs')}</button></div>
      <div class="ag-mini-grid">${['L', 'M', 'M', 'J', 'V', 'S', 'D'].map((x) => `<span>${x}</span>`).join('')}${cases}</div></div>`;
  }
  function ligneAgenda(a) {
    const partage = a.partages.length ? `<span class="ag-shared" title="Partagé dans Mika avec ${h(a.partages.map(([k]) => M.who(k).court).join(' et '))}">${ico('users', 'xs')}${a.partages.length}</span>` : '';
    return `<div class="ag-cal${a.groupe === 'mika' ? ' mika' : ''}" style="--c:var(--ag-${a.couleur})">
      <label title="${h(a.nom)} — ${h(fournisseur(a))}"><input type="checkbox" data-agcoche="${a.id}"${a.coche ? ' checked' : ''}><span class="ag-cal-nom"><b>${h(a.nom)}</b><small>${h(fournisseur(a))}${partage}</small></span></label>
      <button class="btn xs icon ghost ag-cal-more" type="button" data-agmenu="${a.id}" title="Afficher seulement celui-ci, couleur, partager, paramètres">${ico('more', 'xs')}</button></div>`;
  }
  function listeAgendas() {
    return GROUPES.map(([g, titre]) => {
      const l = A.agendas.filter((a) => a.groupe === g && a.visible);
      return l.length ? `<div class="group-label">${h(titre)}</div><div class="ag-cals">${l.map(ligneAgenda).join('')}</div>` : '';
    }).join('');
  }
  function colonne() {
    const enPanne = A.comptes.filter((c) => c.etat[0] !== 'ok');
    return `<aside class="pane ag-side"><div class="pane-scroll ag-side-scroll">
      <a class="btn primary ag-creer" href="#agenda/nouveau">${ico('plus', 'sm')}Créer</a>
      ${miniMois()}
      ${listeAgendas()}
      <div class="ag-side-foot">
        ${enPanne.map((c) => `<a class="ag-warn" href="#parametres/agendas/${c.id}">${ico('alert', 'sm')}<span><b>${h(c.nom)}</b> à reconnecter · ses agendas ne se montrent plus</span></a>`).join('')}
        <a class="mb-add" href="#parametres/agendas/brancher">${ico('plus', 'sm')}Brancher un agenda</a>
      </div></div></aside>`;
  }

  // ── Les pièces communes des vues ──────────────────────────────────────
  const styleC = (o) => `--c:var(--ag-${couleur(o)})`;
  const classes = (o) => [sorte(o), passe(o) ? 'passe' : '', etat.cle && (o.cle === etat.cle || o.ev.id === etat.cle) ? 'sel' : ''].filter(Boolean).join(' ');
  function marque(o) {
    const s = sorte(o);
    if (s === 'propose' || s === 'mika' || ajouteParMika(o)) return `<span class="ag-mk" title="${s === 'propose' ? 'Mika propose de l\'ajouter' : s === 'mika' ? 'L\'agenda de Mika' : 'Ajouté par Mika'}">${ico('sparkle', 'xs')}</span>`;
    return '';
  }
  const titreLong = (o) => `${o.ev.titre} — ${o.journee ? jourDit(o.jour) + ', journée entière' : `${jourDit(o.jour)}, ${hm(o.deb)} – ${hm(o.finMin)}`}${sorte(o) === 'invite' ? ' (invitation)' : sorte(o) === 'propose' ? ' (proposé par Mika)' : ''}`;
  function etiquettes(o) {
    const s = sorte(o), out = [];
    if (s === 'invite') out.push(`<span class="tag warn">invitation · ${h(M.who(o.ev.invitation.de).court)}</span>`);
    if (s === 'peut') out.push('<span class="tag">peut-être</span>');
    if (s === 'propose') out.push(`<span class="mk">${ico('sparkle')}proposé par Mika</span>`);
    if (ajouteParMika(o)) out.push(`<span class="mk quiet">${ico('sparkle')}ajouté par Mika</span>`);
    if (s === 'mika') out.push(`<span class="mk">${ico('sparkle')}${o.ev.mika.sorte === 'promesse' ? 'promis' : 'elle s\'en souvient'}</span>`);
    if (o.ev.rec) out.push(`<span class="ag-rep" title="Se répète">${ico('repeat', 'xs')}</span>`);
    return out.join('');
  }

  /* Les chevauchements : les événements qui se touchent se partagent la largeur, en colonnes. */
  function disposer(evs) {
    evs.sort((a, b) => a.deb - b.deb || b.fin - a.fin);
    let groupe = [], fin = -1;
    const vider = () => {
      const cols = [];
      for (const e of groupe) { let c = cols.findIndex((f) => f <= e.deb); if (c < 0) { c = cols.length; cols.push(e.fin); } else cols[c] = e.fin; e.col = c; }
      for (const e of groupe) e.ncol = cols.length;
      groupe = [];
    };
    for (const e of evs) { if (groupe.length && e.deb >= fin) { vider(); fin = -1; } groupe.push(e); fin = Math.max(fin, e.fin); }
    if (groupe.length) vider();
    return evs;
  }
  function blocEv(x, large) {
    const o = x.o, top = x.deb / 60 * HH, hgt = Math.max(19, (o.finMin - o.deb) / 60 * HH - 2);
    const w = 100 / x.ncol, l = x.col * w, court = hgt < 36;
    const quand = sorte(o) === 'invite' ? `${hm(o.deb)} – ${hm(o.finMin)} · invitation` : sorte(o) === 'propose' ? `${hm(o.deb)} · proposé par Mika` : `${hm(o.deb)} – ${hm(o.finMin)}`;
    const lieu = o.ev.lieu && hgt > 58 ? `<span class="ag-ev-l">${h(lieuCourt(o.ev.lieu))}</span>` : '';
    const qui = large && o.ev.p && hgt > 80 ? `<span class="ag-ev-l">${h(o.ev.p.length)} participants</span>` : '';
    return `<button type="button" class="ag-ev ${classes(o)}${court ? ' court' : ''}" style="${styleC(o)};top:${top}px;height:${hgt}px;left:calc(${l}% + 2px);width:calc(${w}% - 5px)" data-agev="${h(o.cle)}" title="${h(titreLong(o))}">
      ${court ? `${marque(o)}<b>${h(o.ev.titre)}</b><span>${hm(o.deb)}</span>` : `<b>${marque(o)}${h(o.ev.titre)}</b><span>${h(quand)}</span>${lieu}${qui}`}</button>`;
  }

  // ── Jour et Semaine : la grille horaire ───────────────────────────────
  function vueGrille(jours) {
    const du = jours[0], au = plus(jours[jours.length - 1], 1), n = jours.length;
    const occs = occurrences(du, au).filter(visible);
    const ad = occs.filter((o) => o.journee).map((o) => ({ o, s: Math.max(0, ecartJ(du, o.jour)), e: Math.min(n - 1, ecartJ(du, o.fin)) }))
      .sort((a, b) => a.s - b.s || (b.e - b.s) - (a.e - a.s));
    const lanes = [];
    ad.forEach((x) => { let l = lanes.findIndex((f) => f < x.s); if (l < 0) { l = lanes.length; lanes.push(x.e); } else lanes[l] = x.e; x.l = l; });
    const journees = ad.map((x) => `<button type="button" class="ag-ev ag-ad ${classes(x.o)}" style="${styleC(x.o)};grid-column:${x.s + 1} / ${x.e + 2};grid-row:${x.l + 1}" data-agev="${h(x.o.cle)}" title="${h(titreLong(x.o))}">${marque(x.o)}<b>${h(x.o.ev.titre)}</b></button>`).join('');
    const cols = jours.map((d) => {
      const evs = disposer(occs.filter((o) => !o.journee && mem(o.jour, d)).map((o) => ({ o, deb: o.deb, fin: Math.max(o.finMin, o.deb + 24) })));
      const now = mem(d, AUJ) ? `<div class="ag-now" style="top:${MAINTENANT / 60 * HH}px" title="Maintenant, ${h(A.heure)}"></div>` : '';
      return `<div class="ag-col${mem(d, AUJ) ? ' auj' : ''}" data-agcol="${ymd(d)}">${evs.map((x) => blocEv(x, n === 1)).join('')}${now}</div>`;
    }).join('');
    const tetes = jours.map((d) => `<button type="button" class="ag-dh${mem(d, AUJ) ? ' auj' : ''}" data-agjourvue="${ymd(d)}" title="${h(cap(jourDit(d)))}"><span>${JC[d.getDay()]}</span><b>${d.getDate()}</b></button>`).join('');
    return `<div class="ag-grid${n === 1 ? ' un' : ''}" style="--n:${n};--hh:${HH}px" data-agscroll="grille">
      <div class="ag-gtop"><div class="ag-gh"><div class="ag-gut ag-tz" title="${h(A.fuseau)}">${h(A.fuseauCourt)}</div><div class="ag-dhs">${tetes}</div></div>
        <div class="ag-gad"><div class="ag-gut">journée</div><div class="ag-ads" style="grid-template-rows:repeat(${Math.max(1, lanes.length)}, 22px)">${journees}</div></div></div>
      <div class="ag-gb"><div class="ag-gut ag-hours">${Array.from({ length: 24 }, (_, i) => `<span style="top:${i * HH}px">${i ? pad(i) + ':00' : ''}</span>`).join('')}</div>
        <div class="ag-cols">${cols}</div></div></div>`;
  }

  // ── Mois ──────────────────────────────────────────────────────────────
  function vueMois() {
    const [du, au] = bornes(), occs = occurrences(du, au).filter(visible), nj = ecartJ(du, au), m = etat.date.getMonth();
    let cases = '';
    for (let i = 0; i < nj; i++) {
      const d = plus(du, i), k = ymd(d);
      const ce = occs.filter((o) => ymd(o.jour) <= k && ymd(o.fin) >= k);
      const max = 4, vis = ce.slice(0, ce.length > max ? max - 1 : max), reste = ce.length - vis.length;
      cases += `<div class="ag-mc${d.getMonth() !== m ? ' hors' : ''}${mem(d, AUJ) ? ' auj' : ''}">
        <button type="button" class="ag-mc-n" data-agjourvue="${k}" title="${h(cap(jourDit(d)))}">${d.getDate() === 1 ? `1er ${MC[d.getMonth()]}` : d.getDate()}</button>
        ${vis.map((o) => (o.journee
          ? `<button type="button" class="ag-ev ag-mchip plein ${classes(o)}" style="${styleC(o)}" data-agev="${h(o.cle)}" title="${h(titreLong(o))}">${marque(o)}<b>${h(o.ev.titre)}</b></button>`
          : `<button type="button" class="ag-mchip ${classes(o)}" style="${styleC(o)}" data-agev="${h(o.cle)}" title="${h(titreLong(o))}"><i class="ag-dot"></i><span class="t">${hm(o.deb)}</span><b>${h(o.ev.titre)}</b></button>`)).join('')}
        ${reste ? `<button type="button" class="ag-mc-plus" data-agjourvue="${k}">${reste} de plus</button>` : ''}</div>`;
    }
    return `<div class="ag-month"><div class="ag-mh">${['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'].map((x) => `<span>${x}</span>`).join('')}</div>
      <div class="ag-mg" style="--r:${nj / 7}">${cases}</div></div>`;
  }

  // ── Planning : une liste par jour (et les résultats d'une recherche) ──
  function ligneListe(o) {
    return `<button type="button" class="ag-pr ${classes(o)}" style="${styleC(o)}" data-agev="${h(o.cle)}" title="${h(titreLong(o))}">
      <span class="ag-pr-h">${o.journee ? 'Journée' : `${hm(o.deb)} – ${hm(o.finMin)}`}</span><i class="ag-pr-dot"></i>
      <span class="ag-pr-main"><b>${h(o.ev.titre)}</b><small>${h(AG[o.ev.agenda].nom)}${o.ev.lieu ? ' · ' + h(lieuCourt(o.ev.lieu)) : o.ev.visio ? ' · visio ' + h(o.ev.visio) : ''}</small></span>
      <span class="ag-pr-marks">${etiquettes(o)}</span></button>`;
  }
  function liste(occs, opts) {
    const o2 = opts || {};
    const jours = new Map();
    occs.forEach((o) => {
      const fin = o.journee ? o.fin : o.jour;
      for (let d = o.jour; d <= fin; d = plus(d, 1)) {
        if (o2.du && d < o2.du) continue;
        if (o2.au && d >= o2.au) break;
        const k = ymd(d);
        if (!jours.has(k)) jours.set(k, []);
        jours.get(k).push(o);
      }
    });
    if (!jours.size) return `<div class="empty">${ico(o2.q ? 'search' : 'agenda')}<b>${o2.q ? 'Rien trouvé' : 'Rien de prévu'}</b><p>${o2.q ? `Aucun événement ne correspond à « ${h(o2.q)} » dans tes agendas cochés.` : 'Aucun événement dans les agendas cochés sur cette période.'}</p></div>`;
    return [...jours.entries()].sort().map(([k, os]) => {
      const d = lireJ(k), auj = mem(d, AUJ);
      let lignes = '', ligneDite = false;
      os.sort((a, b) => (b.journee - a.journee) || a.deb - b.deb).forEach((o) => {
        if (auj && !ligneDite && !o.journee && o.deb > MAINTENANT) { lignes += `<div class="ag-pl-now"><span>${h(A.heure)}</span></div>`; ligneDite = true; }
        lignes += ligneListe(o);
      });
      if (auj && !ligneDite) lignes += `<div class="ag-pl-now"><span>${h(A.heure)}</span></div>`;
      return `<section class="ag-pd${auj ? ' auj' : ''}"><button type="button" class="ag-pd-date" data-agjourvue="${k}" title="${h(cap(jourDit(d)))}"><b>${d.getDate()}</b><span><i>${JC[d.getDay()]}</i> <i>${MC[d.getMonth()]}</i></span></button>
        <div class="ag-pd-list">${ecart(d) === 0 ? '<div class="ag-pd-dit">Aujourd\'hui</div>' : ecart(d) === 1 ? '<div class="ag-pd-dit">Demain</div>' : ''}${lignes}</div></section>`;
    }).join('');
  }
  function vuePlanning() {
    const [du, au] = bornes();
    return `<div class="ag-plan" data-agscroll="liste">${liste(occurrences(du, au).filter(visible), { du, au })}
      <div class="ag-plan-more"><button class="btn sm" type="button" data-agpas="1">${ico('chev-down', 'sm')}Les quatre semaines suivantes</button></div></div>`;
  }
  function vueRecherche() {
    const q = M.norm(etat.q);
    const occs = occurrences(lireJ('2026-09-01'), lireJ('2027-07-01')).filter(visible).filter((o) => {
      const ev = o.ev, gens = (ev.p || []).map(([k]) => (typeof k === 'string' ? M.who(k).nom : k.nom)).join(' ');
      return M.norm(`${ev.titre} ${ev.lieu || ''} ${ev.desc || ''} ${AG[ev.agenda].nom} ${gens}`).includes(q);
    });
    // une récurrence n'apparaît qu'à ses trois prochaines dates
    const vus = {};
    const l = occs.filter((o) => { if (!o.ev.rec) return true; if (ecart(o.jour) < 0) return false; vus[o.ev.id] = (vus[o.ev.id] || 0) + 1; return vus[o.ev.id] <= 3; });
    return `<div class="ag-plan" data-agscroll="liste"><div class="ag-res-head"><b>${l.length} résultat${l.length > 1 ? 's' : ''}</b> pour « ${h(etat.q)} » <span class="muted">· dans les agendas cochés, de septembre à juin</span>
      <button class="btn xs ghost" type="button" data-agqvide>${ico('x', 'xs')}Effacer</button></div>${liste(l, { q: etat.q })}</div>`;
  }

  // ── La proposition de Mika, en tête de la vue ─────────────────────────
  function bandeau() {
    if (S.proposition !== 'attend' || etat.cle === 'prop-diner') return '';
    const o = trouver('prop-diner');
    return `<div class="ag-strip">${av('mika', 'xs')}<span class="grow"><b>Mika propose d'ajouter</b> « ${h(o.ev.titre)} »
      <span class="long">· ${h(jourDit(o.jour))} à ${hm(o.deb)} · dans ${sw(AG.perso.couleur)}${h(AG.perso.nom)}</span><span class="court">· ${h(jourCourt(o.jour))}, ${hm(o.deb)}</span>
      <a href="#agenda/evenement/prop-diner">Voir</a></span>
      <span class="ag-strip-actions"><button class="btn xs" type="button" data-agprop="refuse">Refuser</button><a class="btn xs" href="#agenda/modifier/prop-diner">Modifier</a>
      <button class="btn xs primary" type="button" data-agprop="ajoute">${ico('check', 'xs')}Ajouter</button></span></div>`;
  }
  function mobileMois() { return etat.mobileMois ? `<div class="ag-mm">${miniMois()}</div>` : ''; }

  function vue() {
    if (etat.q) return vueRecherche();
    if (etat.vue === 'mois') return vueMois();
    if (etat.vue === 'planning') return vuePlanning();
    if (etat.vue === 'jour') return vueGrille([etat.date]);
    const l = lundi(etat.date);
    return vueGrille(Array.from({ length: 7 }, (_, i) => plus(l, i)));
  }

  // ── La fiche d'un événement ───────────────────────────────────────────
  function relatif(o) {
    const e = ecart(o.jour);
    if (o.journee) { if (ecart(o.fin) < 0) return ['', 'passé']; if (e <= 0) return ['accent', 'aujourd\'hui']; return ['', e === 1 ? 'demain' : `dans ${e} jours`]; }
    if (passe(o)) return ['', 'passé'];
    if (e === 0 && o.deb <= MAINTENANT) return ['ok', 'en cours'];
    if (e === 0) { const m = o.deb - MAINTENANT; return ['accent', m < 60 ? `dans ${m} min` : `dans ${Math.floor(m / 60)} h${m % 60 ? ' ' + pad(m % 60) : ''}`]; }
    return ['', e === 1 ? 'demain' : `dans ${e} jours`];
  }
  function recurrence(ev) {
    if (!ev.rec) return '';
    const d0 = lireJ(ev.j);
    if (ev.rec.freq === 'an') return `Chaque année, le ${num(d0)} ${MOIS[d0.getMonth()]}`;
    return `Chaque ${JOURS[d0.getDay()]}${ev.rec.jusqu ? `, jusqu'au ${jourDit(lireJ(ev.rec.jusqu))}` : ''}`;
  }
  const quandDit = (o) => (o.journee
    ? (mem(o.jour, o.fin) ? `${cap(jourDit(o.jour))} · journée entière` : `Du ${jourDit(o.jour)} au ${jourDit(o.fin)} · journées entières`)
    : `${cap(jourDit(o.jour))} · ${hm(o.deb)} – ${hm(o.finMin)}`);
  const PREP = { org: ['accent', 'organise'], oui: ['ok', 'oui'], peut: ['warn', 'peut-être'], non: ['danger', 'non'], attente: ['', 'sans réponse'] };
  function participants(o) {
    const p = o.ev.p;
    if (!p || !p.length) return '';
    const rep = (k, r) => (k === 'adrien' && o.ev.invitation && S.invitations[o.ev.id] ? S.invitations[o.ev.id] : r);
    const n = { oui: 0, peut: 0, non: 0, attente: 0 };
    p.forEach(([k, r]) => { const x = rep(k, r); if (x === 'org' || x === 'oui') n.oui++; else n[x]++; });
    const resume = [`${p.length} personnes`, n.oui ? `${n.oui} oui` : '', n.peut ? `${n.peut} peut-être` : '', n.non ? `${n.non} non` : '', n.attente ? `${n.attente} sans réponse` : ''].filter(Boolean).join(' · ');
    return `<div class="ag-sec"><h4 class="rd-h4">Participants <span class="cnt">${h(resume)}</span></h4><ul class="ag-ppl">${p.map(([k, r]) => {
      const x = rep(k, r), per = typeof k === 'string' ? M.who(k) : k;
      const adr = typeof k === 'string' ? ((per.moyens || []).find((m) => m[0] === 'mail' && /lumen|gmail|proton|laposte/.test(m[1])) || ['', ''])[1] : k.adr;
      return `<li>${av(typeof k === 'string' ? k : { nom: k.nom, c: 2 }, 'sm')}<span class="grow"><b>${h(per.nom)}${k === 'adrien' ? ' <span class="muted">(toi)</span>' : ''}</b>${adr ? `<small>${h(adr)}</small>` : ''}</span><span class="tag ${PREP[x][0]}">${PREP[x][1]}</span></li>`;
    }).join('')}</ul></div>`;
  }
  function boiteInvitation(o, compact) {
    const ev = o.ev, inv = ev.invitation, rep = S.invitations[ev.id];
    const org = M.who(inv.de);
    if (rep && rep !== 'peut') return `<div class="ag-invit done">${ico('check', 'sm')}<span>Tu as répondu <b>${h(REPONSES[rep].toLowerCase())}</b> · parti à ${h(org.court)} par ${h(inv.par)}.</span><button class="linkish small" type="button" data-agrepchanger="${ev.id}">Changer</button></div>`;
    const conflit = inv.conflit ? trouver(`${inv.conflit}@${ymd(o.jour)}`) : null;
    const prep = inv.prepare && !S.refusees[ev.id] && !rep ? inv.prepare : null;
    return `<div class="ag-invit">
      ${compact ? '' : `<div class="ag-invit-head">${av(inv.de, 'sm')}<span><b>${h(org.nom)}</b> t'invite <span class="muted">· reçue ${h(inv.recue)} · par ${h(inv.par)}</span></span></div>`}
      <div class="ag-rep-row"><span class="small text-2">${rep === 'peut' ? 'Tu as répondu peut-être :' : 'Ta réponse :'}</span><span class="btn-group">${Object.entries(REPONSES).map(([k, l]) => `<button class="btn sm${rep === k ? ' on' : ''}" type="button" data-agrep="${ev.id}:${k}">${k === 'oui' ? ico('check', 'sm') : k === 'non' ? ico('x', 'sm') : ''}${l}</button>`).join('')}</span></div>
      ${conflit ? `<p class="ag-conflit">${ico('alert', 'sm')}<span>Tombe en même temps que <a href="#agenda/evenement/${h(conflit.cle)}">« ${h(conflit.ev.titre)} »</a> (${h(AG[conflit.ev.agenda].nom)}), ${hm(conflit.deb)} – ${hm(conflit.finMin)}.</span></p>` : ''}
      ${prep ? `<div class="mika-note ag-prep">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}Mika a préparé ta réponse · elle attend ton accord</div>
        <p><b>${h(REPONSES[prep.reponse])}</b>, avec un mot : « ${h(prep.mot)} »</p><p class="small text-2">${h(prep.pourquoi)}</p>
        <div class="mn-actions"><button class="btn sm primary" type="button" data-agrepmika="${ev.id}">${ico('send', 'sm')}Envoyer sa réponse</button><button class="btn sm" type="button" data-agrepmot="${ev.id}">Modifier le mot</button>
          <button class="btn sm ghost" type="button" data-agrepnon="${ev.id}">Non merci</button></div></div></div>` : ''}
    </div>`;
  }
  function fiche(o) {
    const ev = o.ev, a = AG[ev.agenda], s = sorte(o), [rcls, rlib] = relatif(o);
    const lectureSeule = !a.ecrire || !proprio(a);
    const estMika = ev.agenda === 'mika';
    const entete = s === 'propose'
      ? `<div class="mika-note ag-box">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}Mika propose d'ajouter cet événement à « ${h(a.nom)} »</div>
          <p class="small">${h(ev.proposition.phrase)} <a href="${ev.proposition.conv}">Voir la conversation</a></p>
          <div class="mn-actions"><button class="btn sm primary" type="button" data-agprop="ajoute">${ico('check', 'sm')}Ajouter</button><a class="btn sm" href="#agenda/modifier/prop-diner">Modifier</a><button class="btn sm" type="button" data-agprop="refuse">Refuser</button></div></div></div>`
      : estMika
        ? `<div class="mika-note ag-box">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}${ev.mika.sorte === 'promesse' ? 'Ce qu\'elle t\'a promis' : 'Ce qu\'elle retient de ta vie'}</div>
            <p><b>${h(ev.mika.source)}</b> <a href="${ev.mika.conv}">Voir la conversation</a></p><p class="small text-2">Ses mots, le ${h(ev.mika.quand)} : ${h(ev.mika.dit)}</p>
            ${ev.mika.suite ? `<p class="small text-2">${h(ev.mika.suite)}</p>` : ''}</div></div>` : '';
    const invit = ev.invitation ? boiteInvitation(o) : '';
    const autreOrg = ev.org && ev.org !== 'adrien';
    const actionsFiche = estMika
      ? `<button class="btn sm mika" type="button" data-agaction="parler">${ico('sparkle', 'sm')}Lui en parler</button>`
      : s === 'propose' ? `<span class="small muted">Ce n'est pas encore dans ton agenda.</span><span class="grow"></span><button class="btn sm mika" type="button" data-agaction="demander">${ico('sparkle', 'sm')}Demander à Mika</button>`
      : `${lectureSeule || autreOrg ? '' : `<a class="btn sm" href="#agenda/modifier/${h(o.cle)}">${ico('pen', 'sm')}Modifier</a>`}
        <button class="btn sm" type="button" data-agaction="dupliquer">${ico('copy', 'sm')}${lectureSeule ? 'Copier dans mes agendas' : 'Dupliquer'}</button>
        ${lectureSeule || s === 'propose' ? '' : `<button class="btn sm danger" type="button" data-agaction="supprimer">${ico('trash', 'sm')}Supprimer</button>`}
        <span class="grow"></span><button class="btn sm mika" type="button" data-agaction="demander">${ico('sparkle', 'sm')}Demander à Mika</button>`;
    const rappelMika = ev.rappel || a.rappel;
    const sait = ev.sait && ev.sait.length ? `<div class="ag-sec"><h4 class="rd-h4">${ico('sparkle', 'sm')}Ce que Mika en sait</h4><ul class="cx-sait ag-sait">${ev.sait.map(([t, d, r]) => `<li><p>${h(t)}</p><small>${r ? `<a href="${r}">${h(d)}</a>` : h(d)}</small></li>`).join('')}</ul>
      <p class="small muted">Elle ne le dit qu'à toi.</p></div>` : '';
    return `<aside class="pane ag-volet" aria-label="L'événement">
      <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico('chev-left', 'sm')}Agenda</button>
        ${sw(couleur(o))}<span class="grow ellipsis small text-2">${h(a.nom)} <span class="muted">· ${h(fournisseur(a))}</span></span>
        <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer">${ico('x', 'sm')}</button></div>
      <div class="pane-scroll"><div class="ag-fiche">
        ${entete}
        <div class="ag-f-titre"><h2>${h(ev.titre)}</h2><p class="ag-quand">${h(quandDit(o))} <span class="tag ${rcls}">${h(rlib)}</span></p></div>
        ${invit}
        <div class="ag-actions">${actionsFiche}</div>
        <ul class="ag-kv">
          ${ev.rec ? `<li>${ico('repeat')}<span>${h(recurrence(ev))}</span></li>` : ''}
          ${ev.lieu ? `<li>${ico('pin')}<span>${h(ev.lieu)}<a class="ag-kv-a" href="#carte/explorer">${ico('map', 'xs')}Voir sur la carte</a></span></li>` : ''}
          ${ev.visio ? `<li>${ico('video')}<span><button class="linkish" type="button" data-agvisio>Rejoindre la réunion ${h(ev.visio)}</button>${ev.visioUrl ? `<small class="mono ellipsis">${h(ev.visioUrl)}</small>` : ''}</span></li>` : ''}
          ${ev.desc ? `<li>${ico('file')}<span class="text-2">${h(ev.desc)}</span></li>` : ''}
          ${!estMika ? `<li>${ico('clock')}<span class="text-2">${ev.dispo === 'libre' ? 'Disponible' : 'Occupé'} · visibilité par défaut${autreOrg ? ` · organisé par ${h(M.who(ev.org).nom)}, qui seul${['claire', 'sophie', 'nadia', 'lea', 'camille', 'maman'].includes(ev.org) ? 'e' : ''} le modifie` : ''}</span></li>` : ''}
        </ul>
        ${participants(o)}
        ${!estMika ? `<div class="ag-sec"><h4 class="rd-h4">Rappels</h4>
          <div class="ag-line">${ico('bell', 'sm')}<span class="text-2">${h(cap(a.rappelFourn))}</span></div>
          <div class="ag-line mika">${ico('sparkle', 'sm')}<span class="grow"><b>${rappelMika === 'non' ? 'Mika ne te le rappelle pas' : `Mika te le rappelle : ${h(rappelDit(rappelMika))}`}</b>
            <small>${ev.rappel ? 'pour cet événement' : `le réglage de « ${h(a.nom)} »`} · elle te l'écrit dans le chat, ou par une notification</small></span>
            <button class="btn xs ghost" type="button" data-agrappel="${h(o.cle)}">Changer</button></div></div>` : ''}
        ${sait}
        ${ajouteParMika(o) && ev.parMika ? `<div class="ag-line mika ag-par">${ico('sparkle', 'sm')}<span><span><b>Ajouté par Mika</b>, ${ev.parMika.comment === 'seule' ? 'seule' : 'avec ton accord'}, le ${h(ev.parMika.quand)}</span><small>${h(ev.parMika.phrase)} <a href="${ev.parMika.conv}">Voir la conversation</a></small></span></div>` : ''}
        ${ajouteParMika(o) && ev.proposition ? `<div class="ag-line mika ag-par">${ico('sparkle', 'sm')}<span><span><b>Ajouté par Mika</b>, avec ton accord, aujourd'hui</span><small>${h(ev.proposition.phrase)} <a href="${ev.proposition.conv}">Voir la conversation</a></small></span></div>` : ''}
        ${estMika ? `<p class="ag-ro">${ico('lock', 'sm')}<span>C'est sa mémoire, montrée comme un agenda : on ne le modifie pas ici. Dis-le-lui : « c'est fait », « c'est reporté à lundi », « oublie ça ». Elle ne te montre que ce qui te concerne, jamais ce qu'un autre lui a confié.</span></p>`
          : lectureSeule ? `<p class="ag-ro">${ico('lock', 'sm')}<span>${a.groupe === 'partages' ? `${h(M.who(a.de).nom)} partage cet agenda avec toi en lecture : tu le vois, tu n'y changes rien.` : 'Un abonnement est en lecture seule : ni toi ni Mika n\'y écrivez.'}</span></p>`
            : `<p class="small muted ag-src">${ico('refresh', 'xs')}Une modification part tout de suite ${h(chez(a))}${a.compte === 'systeme' ? '' : ', puis l\'agenda se relit'}.</p>`}
      </div></div></aside>`;
  }

  function voletInvitations() {
    const l = enAttente();
    const faites = A.evenements.filter((e) => e.invitation && S.invitations[e.id]).map((e) => trouver(e.id));
    const carte = (o) => `<article class="ag-invcard"><button type="button" class="ag-invcard-head" data-agev="${h(o.cle)}" style="${styleC(o)}">${sw(couleur(o))}
        <span class="grow"><b>${h(o.ev.titre)}</b><small>${h(cap(jourDit(o.jour)))} · ${hm(o.deb)} – ${hm(o.finMin)}${o.ev.lieu ? ' · ' + h(lieuCourt(o.ev.lieu)) : ''}</small>
        <small>${h(M.who(o.ev.invitation.de).nom)} t'invite · reçue ${h(o.ev.invitation.recue)} · ${h(AG[o.ev.agenda].nom)}</small></span>${ico('chev-right', 'sm')}</button>
        ${boiteInvitation(o, true)}</article>`;
    return `<aside class="pane ag-volet" aria-label="Les invitations">
      <div class="pane-head ag-vh"><button class="btn sm ghost mobile-back" type="button" data-agfermer>${ico('chev-left', 'sm')}Agenda</button>
        <h2>Invitations</h2><span class="cnt">${l.length ? `${l.length} en attente` : 'aucune en attente'}</span><span class="grow"></span>
        <button class="btn icon ghost sm ag-vh-x" type="button" data-agfermer title="Fermer">${ico('x', 'sm')}</button></div>
      <div class="pane-scroll"><div class="ag-invs">
        ${l.length ? l.map(carte).join('') : `<div class="empty">${ico('inbox')}<b>Tout est répondu</b><p>Une invitation reçue par Outlook ou Google arrive ici, avec la réponse que Mika te prépare.</p></div>`}
        ${faites.length ? `<div class="group-label">Déjà répondu</div>${faites.map((o) => `<button type="button" class="li" data-agev="${h(o.cle)}">${sw(couleur(o))}<span class="li-main"><span class="li-title">${h(o.ev.titre)}</span><span class="li-snip">${h(REPONSES[S.invitations[o.ev.id]])} · ${h(jourCourt(o.jour))} ${hm(o.deb)}</span></span></button>`).join('')}` : ''}
        <p class="small muted ag-invs-note">Une invitation arrive par ton agenda (Outlook, Google, CalDAV) et ta réponse repart par lui. Mika prépare une réponse ; elle ne l'envoie jamais sans ton accord.</p>
      </div></div></aside>`;
  }

  // ── Créer et modifier ─────────────────────────────────────────────────
  const optRec = (o) => {
    const d = o ? o.jour : (etat.nouveau ? lireJ(etat.nouveau.jour) : etat.date);
    return [['', 'Ne se répète pas'], ['jour', 'Chaque jour'], ['semaine', `Chaque semaine, le ${JOURS[d.getDay()]}`], ['mois', `Chaque mois, le ${num(d)}`],
      ['an', `Chaque année, le ${num(d)} ${MOIS[d.getMonth()]}`], ['perso', 'Personnalisée…']];
  };
  // Les rappels du fournisseur dans le formulaire : l'agenda du système n'en a pas (c'est Mika qui rappelle).
  const nomFourn = (a) => { const c = compte(a); return !c ? '' : c.sorte === 'caldav' ? 'd\'Outlook (par DavMail)' : c.sorte === 'google' ? 'de Google' : c.sorte === 'microsoft' ? 'de Microsoft' : ''; };
  const ligneRappel = (n, unite) => `<div class="row"><select class="sm-select"><option>Notification</option><option>E-mail</option></select><input type="number" value="${n}" class="ag-n"><select class="sm-select">${['minutes', 'heures', 'jours'].map((u) => `<option${u === unite ? ' selected' : ''}>${u}</option>`).join('')}</select> avant<button class="btn xs icon ghost" type="button" data-agrappelx title="Retirer">${ico('x', 'xs')}</button></div>`;
  const rappelsDe = (a) => (a.compte === 'systeme' ? '<p class="small muted">L\'agenda du système n\'envoie rien lui-même : c\'est Mika qui te le rappelle.</p>' : ligneRappel(a.id === 'travail' ? 10 : a.id === 'famille' ? 1 : 30, a.id === 'famille' ? 'jours' : 'minutes'));
  function ferme(el) {
    // Fermer la fenêtre ramène la route à la vue (sans redessiner : elle est déjà dessous).
    const retour = () => history.replaceState(null, '', routeVue());
    M.on(el, '[data-close]', 'click', retour);
    el.parentElement.addEventListener('mousedown', (e) => { if (e.target === el.parentElement) retour(); });
  }
  function formulaire(mode, o) {
    const ev = o ? o.ev : null;
    const prop = ev && ev.proposition;
    const nv = etat.nouveau || {};
    const jour = o ? o.jour : nv.jour ? lireJ(nv.jour) : etat.date;
    const deb = o ? o.deb : nv.deb != null ? nv.deb : (mem(jour, AUJ) ? Math.ceil((MAINTENANT + 1) / 30) * 30 : 600);
    const fin = o ? o.finMin : deb + 60;
    const agId = ev ? (AG[ev.agenda].ecrire && proprio(AG[ev.agenda]) ? ev.agenda : 'mon') : (nv.agenda || 'mon');
    const titre = ev ? (mode === 'dupliquer' ? ev.titre + (AG[ev.agenda].ecrire && proprio(AG[ev.agenda]) ? ' (copie)' : '') : ev.titre) : '';
    const recDe = ev && ev.rec ? ev.rec.freq : '';
    const rappelM = ev ? (ev.rappel || AG[agId].rappel) : AG[agId].rappel;
    let chips = ev && ev.p ? ev.p.filter(([k]) => k !== 'adrien').map(([k]) => (typeof k === 'string' ? k : k)) : [];
    const titreModal = mode === 'modifier' ? (prop ? 'Modifier ce que Mika propose' : 'Modifier l\'événement') : mode === 'dupliquer' ? 'Dupliquer l\'événement' : 'Nouvel événement';
    const chip = (k) => { const p = typeof k === 'string' ? M.who(k) : k; return `<span class="chip">${av(typeof k === 'string' ? k : { nom: k.nom, c: 2 }, 'xs')}${h(p.nom)}<button type="button" data-agchipx="${h(typeof k === 'string' ? k : k.nom)}" title="Retirer">${ico('x', 'xs')}</button></span>`; };
    const corps = `<div class="ag-form">
      ${prop ? `<div class="mika-note small">${av('mika', 'xs')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}Ce que Mika propose</div><span>Change ce que tu veux : « Ajouter » l'enregistre dans ton agenda, avec tes changements.</span></div></div>` : ''}
      <input class="ag-titre" data-f="titre" placeholder="Ajouter un titre" value="${h(titre)}">
      <div class="ag-form-cols"><div class="ag-fcol">
        <div class="ag-frow">${ico('clock')}<div class="ag-fval">
          <div class="row wrap ag-dates"><input type="date" data-f="d1" value="${ymd(jour)}"><input type="time" data-f="h1" class="ag-h" value="${hm(deb)}"><span class="muted">→</span>
            <input type="time" data-f="h2" class="ag-h" value="${hm(Math.min(fin, 1439))}"><input type="date" data-f="d2" value="${ymd(o ? o.fin : jour)}"></div>
          <div class="row wrap"><label class="row small"><span class="switch"><input type="checkbox" data-f="journee"${o && o.journee ? ' checked' : ''}><i></i></span>Journée entière</label>
            <select class="sm-select" data-f="fuseau" title="Le fuseau horaire"><option>(UTC+01:00) Paris</option><option>(UTC+00:00) Londres</option><option>(UTC-05:00) New York</option><option>(UTC+09:00) Tokyo</option></select></div></div></div>
        <div class="ag-frow">${ico('repeat')}<div class="ag-fval"><select data-f="rec">${optRec(o).map(([k, l]) => `<option value="${k}"${k === recDe ? ' selected' : ''}>${h(l)}</option>`).join('')}</select>
          <div class="ag-perso" data-recperso hidden><div class="row wrap small">Tous les <input type="number" min="1" value="2" class="ag-n"> <select class="sm-select"><option>jours</option><option selected>semaines</option><option>mois</option><option>ans</option></select>, le
            <span class="ag-jsem">${['L', 'M', 'M', 'J', 'V', 'S', 'D'].map((x, i) => `<button type="button" class="${i === (jour.getDay() + 6) % 7 ? 'on' : ''}" data-agjsem>${x}</button>`).join('')}</span></div>
            <div class="row wrap small">Se termine <select class="sm-select"><option>jamais</option><option>le…</option><option>après…</option></select> <input type="date" value="2027-06-30" class="ag-fin-rec"></div></div></div></div>
        <div class="ag-frow">${ico('pin')}<div class="ag-fval"><div class="row"><input class="grow" data-f="lieu" placeholder="Ajouter un lieu" value="${h(ev && ev.lieu || '')}"><a class="btn sm ghost" href="#carte/explorer" title="Le chercher sur la carte">${ico('map', 'sm')}Carte</a></div></div></div>
        <div class="ag-frow">${ico('video')}<div class="ag-fval"><select data-f="visio"><option>Pas de visio</option><option${ev && ev.visio === 'Teams' ? ' selected' : ''}>Une réunion Teams (créée par Outlook)</option><option>Google Meet (créé par Google)</option><option>Coller un lien…</option></select></div></div>
        <div class="ag-frow">${ico('file')}<div class="ag-fval"><textarea rows="4" data-f="desc" placeholder="Ajouter une description">${h(ev && ev.desc || '')}</textarea></div></div>
      </div>
      <div class="ag-fcol ag-fcol-d">
        <div class="field"><span>Agenda</span><button type="button" class="ag-pick" data-agpick="${agId}">${sw(AG[agId].couleur)}<b>${h(AG[agId].nom)}</b><small>${h(fournisseur(AG[agId]))}</small>${ico('chev-down', 'sm')}</button>
          <small class="muted">Seuls ceux où tu peux écrire. Pas les abonnements, ni l'agenda de Léa, ni celui de Mika.</small></div>
        <div class="field ag-ppl-f"><span>Participants</span><div class="rcpt" data-agrcpt>${chips.map(chip).join('')}<input data-agppl placeholder="Un nom, une adresse…" autocomplete="off"></div>
          <div class="ac-pop ag-sugg" data-agsugg hidden></div>
          <div class="row wrap"><button class="btn xs mika" type="button" data-agcreneau>${ico('sparkle', 'xs')}Trouver un créneau avec eux</button><span class="small muted">L'invitation part par l'agenda choisi.</span></div></div>
        <div class="field"><span>Rappels <span class="muted" data-agrfourn>${h(nomFourn(AG[agId]))}</span></span><div class="ag-rappels" data-agrappels>${rappelsDe(AG[agId])}</div>
          <button class="btn xs ghost ag-add" type="button" data-agrappeladd${AG[agId].compte === 'systeme' ? ' hidden' : ''}>${ico('plus', 'xs')}Ajouter un rappel</button></div>
        <div class="field ag-f-mika"><span>${ico('sparkle', 'xs')}Mika te le rappelle</span><select data-f="mika">${RAPPELS.map(([k, l]) => `<option value="${k}"${k === rappelM ? ' selected' : ''}>${h(l)}</option>`).join('')}</select>
          <small>Elle te l'écrit dans le chat ou par une notification, comme ses autres rappels. Par défaut, le réglage de l'agenda.</small></div>
        <div class="row wrap ag-segs"><div class="field"><span>Afficher comme</span><div class="seg" data-seg="agdispo"><button type="button" data-v="occupe" aria-pressed="${!ev || ev.dispo !== 'libre'}">Occupé</button><button type="button" data-v="libre" aria-pressed="${!!(ev && ev.dispo === 'libre')}">Disponible</button></div></div>
          <div class="field"><span>Visibilité</span><div class="seg" data-seg="agvis"><button type="button" data-v="defaut" aria-pressed="true">Par défaut</button><button type="button" data-v="public" aria-pressed="false">Publique</button><button type="button" data-v="prive" aria-pressed="false">Privée</button></div></div></div>
      </div></div></div>`;
    const el = M.modal({ titre: titreModal, taille: 'wide ag-modal', corps,
      pied: `<span class="grow small muted" data-agpied>Enregistré dans « ${h(AG[agId].nom)} », il part tout de suite ${h(chez(AG[agId]))}.</span><button class="btn" type="button" data-close>Annuler</button>
        <button class="btn primary" type="button" data-agsave>${prop ? `${ico('check', 'sm')}Ajouter` : 'Enregistrer'}</button>` });
    ferme(el);
    let agChoisi = agId;
    const majJournee = () => { const j = el.querySelector('[data-f="journee"]').checked; el.querySelectorAll('.ag-h').forEach((x) => { x.hidden = j; }); };
    majJournee();
    el.querySelector('[data-f="journee"]').addEventListener('change', majJournee);
    el.querySelector('[data-f="rec"]').addEventListener('change', (e) => { el.querySelector('[data-recperso]').hidden = e.target.value !== 'perso'; });
    M.on(el, '[data-agjsem]', 'click', (e, b) => b.classList.toggle('on'));
    M.on(el, '[data-agpick]', 'click', (e, b) => {
      const m = M.menu(b, [{ entete: 'Où tu peux écrire' }, ...ecrivables().map((a) => ({ html: `<button class="mi" type="button" data-agpicki="${a.id}"${a.id === agChoisi ? ' aria-checked="true"' : ''}>${sw(a.couleur)}<span>${h(a.nom)}</span><span class="cnt">${h(fournisseur(a))}</span></button>` }))], { align: 'left' });
      M.on(m, '[data-agpicki]', 'click', (ev2, x) => {
        const a = AG[x.dataset.agpicki]; agChoisi = a.id; M.fermerMenu();
        b.innerHTML = `${sw(a.couleur)}<b>${h(a.nom)}</b><small>${h(fournisseur(a))}</small>${ico('chev-down', 'sm')}`;
        el.querySelector('[data-agpied]').textContent = `Enregistré dans « ${a.nom} », il part tout de suite ${chez(a)}.`;
        el.querySelector('[data-agrfourn]').textContent = nomFourn(a);
        el.querySelector('[data-agrappels]').innerHTML = rappelsDe(a);
        el.querySelector('[data-agrappeladd]').hidden = a.compte === 'systeme';
        el.querySelector('[data-f="mika"]').value = a.rappel;
      });
    });
    // Les participants : tirés des contacts (ceux qui ont une adresse), ou une adresse tapée.
    const input = el.querySelector('[data-agppl]'), sugg = el.querySelector('[data-agsugg]');
    const redessiner = () => { el.querySelectorAll('[data-agrcpt] .chip').forEach((c) => c.remove()); input.insertAdjacentHTML('beforebegin', chips.map(chip).join('')); };
    input.addEventListener('input', () => {
      const q = M.norm(input.value.trim());
      if (!q) { sugg.hidden = true; return; }
      const gens = Object.entries(D.personnes).filter(([k, p]) => k !== 'adrien' && !chips.includes(k) && p.moyens.some((m) => m[0] === 'mail')
        && M.norm(p.nom + ' ' + p.moyens.map((m) => m[1]).join(' ')).includes(q)).slice(0, 5);
      sugg.hidden = false;
      sugg.innerHTML = gens.map(([k, p]) => `<button type="button" class="ac-item" data-agaddp="${k}">${av(k, 'sm')}<span><b>${h(p.nom)}</b><small>${h(p.moyens.find((m) => m[0] === 'mail')[1])}${p.compte ? ' · a un compte : l\'invitation lui arrive aussi dans Mika' : ''}</small></span></button>`).join('')
        + (input.value.includes('@') ? `<button type="button" class="ac-item" data-agaddp="@${h(input.value.trim())}">${ico('at')}<span><b>${h(input.value.trim())}</b><small>une adresse</small></span></button>` : '')
        || '<div class="ac-none">Personne parmi tes contacts. Tape une adresse.</div>';
    });
    M.on(el, '[data-agaddp]', 'click', (e, b) => {
      const k = b.dataset.agaddp;
      chips.push(k.startsWith('@') ? { nom: k.slice(1), adr: k.slice(1) } : k);
      input.value = ''; sugg.hidden = true; redessiner(); input.focus();
    });
    M.on(el, '[data-agchipx]', 'click', (e, b) => { chips = chips.filter((k) => (typeof k === 'string' ? k : k.nom) !== b.dataset.agchipx); redessiner(); });
    M.on(el, '[data-agcreneau]', 'click', () => M.toast(chips.length ? `Mika regarde les agendas que tu vois : mercredi 25, 10:00 – 11:00, tout le monde est libre.` : 'Ajoute d\'abord des participants : elle cherchera un créneau où chacun est libre, dans les agendas que tu vois.', { mika: true }));
    M.on(el, '[data-agrappeladd]', 'click', () => el.querySelector('[data-agrappels]').insertAdjacentHTML('beforeend', ligneRappel(1, 'jours')));
    M.on(el, '[data-agrappelx]', 'click', (e, b) => b.closest('.row').remove());
    el.querySelector('[data-agsave]').addEventListener('click', () => {
      const a = AG[agChoisi];
      const fini = (quoi) => {
        M.fermerModal();
        if (prop) { S.proposition = 'ajoute'; M.toast(`Ajouté à « ${a.nom} », avec tes changements : parti ${chez(a)}.`); }
        else M.toast(`${quoi || 'Enregistré'} dans « ${a.nom} » : parti ${chez(a)}.`);
        etat.nouveau = null;
        M.go(mode === 'modifier' && o ? '#agenda/evenement/' + o.cle : routeVue());
      };
      if (mode === 'modifier' && ev && ev.rec) questionRecurrente(o, 'modifier', (q) => fini(q === 'un' ? 'Cet événement est modifié' : q === 'suite' ? 'Celui-ci et les suivants sont modifiés' : 'Tous sont modifiés'));
      else fini();
    });
    setTimeout(() => { const t = el.querySelector('[data-f="titre"]'); if (t && !t.value) t.focus(); }, 40);
  }
  function questionRecurrente(o, quoi, suite) {
    const ev = o.ev, a = AG[ev.agenda];
    const el = M.modal({ titre: quoi === 'supprimer' ? 'Supprimer un événement récurrent' : 'Modifier un événement récurrent', taille: 'narrow ag-modal',
      corps: `<div class="stack ag-recq"><p class="small text-2">« ${h(ev.titre)} » se répète : ${h(recurrence(ev).toLowerCase())}.</p>
        <label class="row"><input type="radio" name="agrq" value="un" checked> Cet événement <span class="muted small">· ${h(jourCourt(o.jour))}</span></label>
        <label class="row"><input type="radio" name="agrq" value="suite"> Celui-ci et les suivants</label>
        <label class="row"><input type="radio" name="agrq" value="tous"> Tous les événements</label>
        ${ev.p && ev.p.length > 1 ? `<p class="small muted">Les participants sont prévenus par ${h(A.sortes[compte(a).sorte].nom)}.</p>` : ''}</div>`,
      pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn ${quoi === 'supprimer' ? 'danger' : 'primary'}" type="button" data-ok>${quoi === 'supprimer' ? 'Supprimer' : 'OK'}</button>` });
    ferme(el);
    el.querySelector('[data-ok]').addEventListener('click', () => suite(el.querySelector('input[name="agrq"]:checked').value));
  }
  function supprimer(o) {
    const ev = o.ev, a = AG[ev.agenda];
    const fait = (q) => {
      if (q === 'un' || !ev.rec) S.supprimes[o.cle] = true; else S.supprimes[ev.id] = true;
      M.fermerModal(); M.toast(`Supprimé de « ${a.nom} » : effacé ${chez(a)} aussi.`, { ico: 'trash' }); M.go(routeVue());
    };
    if (ev.rec) { questionRecurrente(o, 'supprimer', fait); return; }
    const el = M.modal({ titre: 'Supprimer l\'événement', taille: 'narrow ag-modal',
      corps: `<p>Supprimer « ${h(ev.titre)} » (${h(jourCourt(o.jour))}) ? Il disparaît aussi ${h(chez(a))}.${ev.p && ev.p.length > 1 ? ' Les participants sont prévenus.' : ''}</p>`,
      pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn danger" type="button" data-ok>Supprimer</button>' });
    ferme(el);
    el.querySelector('[data-ok]').addEventListener('click', () => fait('un'));
  }

  // ── Partager un agenda ────────────────────────────────────────────────
  function partager(agId) {
    const a = AG[agId];
    if (!a) return;
    if (!proprio(a)) {
      const el = M.modal({ titre: `Partager « ${a.nom} »`, taille: 'narrow ag-modal',
        corps: a.groupe === 'mika'
          ? '<p>L\'agenda de Mika ne se partage pas : c\'est ce qu\'elle retient pour toi, et ce qu\'elle retient pour chacun reste à chacun.</p>'
          : `<p>Seule ${h(M.who(a.de).nom)} peut partager son agenda. Elle te l'a ouvert en lecture le ${h(a.depuisPartage)}.</p>`,
        pied: `<span class="grow"></span>${a.groupe === 'partages' ? '<button class="btn" type="button" data-close data-agmasquer>Ne plus l\'afficher</button>' : ''}<button class="btn primary" type="button" data-close>Compris</button>` });
      ferme(el);
      M.on(el, '[data-agmasquer]', 'click', () => { a.visible = false; M.rafraichir(); M.toast(`« ${a.nom} » ne s'affiche plus dans ton Agenda. ${M.who(a.de).court} peut toujours retirer son partage.`, { ico: 'eye-off' }); });
      return;
    }
    const c = compte(a);
    const avecCompte = Object.entries(D.personnes).filter(([k, p]) => p.compte && k !== 'adrien');
    const sans = Object.entries(D.personnes).filter(([k, p]) => !p.compte && k !== 'adrien' && p.moyens.some((m) => m[0] === 'mail')).slice(0, 3);
    let niveau = 'lire';
    const niveaux = () => Object.entries(NIVEAUX).map(([k, [l, d]]) => `<li class="${k === niveau ? 'on' : ''}"><b>${h(l)}</b><span>${h(cap(d))}</span></li>`).join('');
    const lignes = () => a.partages.length ? a.partages.map(([k, n, depuis]) => `<li>${av(k, 'sm')}<span class="grow"><b>${h(M.who(k).nom)}</b><small>depuis le ${h(depuis)}</small></span>
        <select class="sm-select" data-agpniv="${k}">${Object.entries(NIVEAUX).map(([x, [l]]) => `<option value="${x}"${x === n ? ' selected' : ''}>${h(l)}</option>`).join('')}</select>
        <button class="btn xs ghost danger" type="button" data-agpret="${k}">Retirer</button></li>`).join('') : '<li class="muted small">Personne pour l\'instant.</li>';
    const fourn = c.sorte === 'google' || c.sorte === 'microsoft' || c.sorte === 'caldav';
    const chezFourn = c.sorte === 'google' ? 'Google' : c.sorte === 'caldav' ? 'Outlook' : 'Microsoft';
    const el = M.modal({ titre: `Partager « ${a.nom} »`, taille: 'ag-modal ag-share-modal',
      corps: `<div class="ag-share">
        <div class="ag-share-head">${sw(a.couleur, 'lg')}<div><b>${h(a.nom)}</b><small>${h(fournisseur(a))} · ${h(c.adresse)} · à toi</small></div></div>
        ${fourn ? `<div class="info-line small">${ico('info', 'sm')}<span>Ce partage se fait ici, dans Mika : la personne verra « ${h(a.nom)} » dans son Agenda de Mika. Il ne change rien chez ${chezFourn}${a.chezGoogle ? ` : le partage Google de « ${h(a.nom)} » (avec ${h(a.chezGoogle.join(' et '))}) se règle dans Google Agenda, et ne se voit pas ici` : ''}.</span></div>` : ''}
        <div class="ag-share-add"><label class="field grow"><span>Avec qui</span><select data-agqui>${avecCompte.map(([k, p]) => `<option value="${k}">${h(p.nom)}</option>`).join('')}
          ${sans.map(([, p]) => `<option disabled>${h(p.nom)} — pas de compte sur ce serveur</option>`).join('')}</select></label>
          <div class="field"><span>Ce que la personne peut</span><div class="seg" data-seg="agniv">${Object.entries(NIVEAUX).map(([k, [l]]) => `<button type="button" data-v="${k}" aria-pressed="${k === niveau}">${h(l)}</button>`).join('')}</div></div>
          <button class="btn primary" type="button" data-agpadd>${ico('user-plus', 'sm')}Partager</button></div>
        <ul class="ag-niveaux" data-agniveaux>${niveaux()}</ul>
        <p class="small muted">Seulement avec une personne qui a un compte sur ce serveur : jamais « tout le monde », jamais un lien public. Seul le propriétaire d'un agenda le partage.</p>
        <h4 class="rd-h4">Partages en cours <span class="cnt" data-agpn>${a.partages.length}</span></h4>
        <ul class="ag-share-list" data-agplist>${lignes()}</ul>
        <p class="small muted">Ce que Mika fait de cet agenda avec chacun se règle dans <a href="#outils/droits/ag-${a.id}" data-close>Outils › Droits</a>.</p></div>`,
      pied: '<span class="grow"></span><button class="btn primary" type="button" data-close>Terminé</button>' });
    ferme(el);
    const maj = () => { el.querySelector('[data-agplist]').innerHTML = lignes(); el.querySelector('[data-agpn]').textContent = a.partages.length; M.compter(); };
    el.addEventListener('mika:seg', (e) => { if (e.detail.nom === 'agniv') { niveau = e.detail.valeur; el.querySelector('[data-agniveaux]').innerHTML = niveaux(); } });
    el.querySelector('[data-agpadd]').addEventListener('click', () => {
      const k = el.querySelector('[data-agqui]').value;
      const deja = a.partages.find((p) => p[0] === k);
      if (deja) deja[1] = niveau; else a.partages.push([k, niveau, '23 novembre']);
      maj();
      M.toast(`${M.who(k).court} voit « ${a.nom} » dans son Agenda : ${NIVEAUX[niveau][0].toLowerCase()}.`, { ico: 'users' });
    });
    M.on(el, '[data-agpret]', 'click', (e, b) => { a.partages = a.partages.filter((p) => p[0] !== b.dataset.agpret); maj(); M.toast('Partage retiré : la personne ne le voit plus.', { ico: 'x' }); });
    el.addEventListener('change', (e) => {
      const s = e.target.closest('[data-agpniv]');
      if (!s) return;
      const p = a.partages.find((x) => x[0] === s.dataset.agpniv);
      if (p) { p[1] = s.value; M.toast(`${M.who(p[0]).court} : ${NIVEAUX[s.value][0].toLowerCase()}.`, { ico: 'users' }); }
    });
  }

  // ── Le menu ⋯ d'un agenda ─────────────────────────────────────────────
  function reglages(a) { return a.groupe === 'mes' || a.groupe === 'abonnements' ? '#parametres/agendas/' + a.compte : '#parametres/agendas'; }
  function menuAgenda(b, id) {
    const a = AG[id];
    const m = M.menu(b, [
      { entete: a.nom },
      { label: 'Afficher seulement celui-ci', ico: 'eye', action: () => { A.agendas.forEach((x) => { x.coche = x.id === id; }); M.rafraichir(); } },
      a.groupe === 'mika' ? { html: '<div class="mh">Couleur · son rose, qui ne change pas</div>' } : { entete: 'Couleur' },
      ...(a.groupe === 'mika' ? [] : [{ html: `<div class="ag-swatches">${A.palette.map(([k, l]) => `<button type="button" class="ag-swatch${a.couleur === k ? ' on' : ''}" style="--c:var(--ag-${k})" data-agcoul="${k}" title="${h(l)}"></button>`).join('')}</div>` }]),
      'sep',
      { label: proprio(a) ? 'Partager' : 'Partager (seul son propriétaire)', ico: 'users', action: () => M.go('#agenda/partager/' + id) },
      { label: 'Paramètres', ico: 'settings', action: () => M.go(reglages(a)) },
    ], { align: 'left' });
    M.on(m, '[data-agcoul]', 'click', (e, x) => { a.couleur = x.dataset.agcoul; M.fermerMenu(); M.rafraichir(); });
  }
  function menuAgendasMobile(b) {
    const m = M.menu(b, [{ html: `<div class="ag-cals-menu">${listeAgendas()}</div>` }, 'sep',
      { label: 'Brancher un agenda', ico: 'plus', action: () => M.go('#parametres/agendas/brancher') }]);
    m.addEventListener('change', (e) => { const c = e.target.closest('[data-agcoche]'); if (c) { AG[c.dataset.agcoche].coche = c.checked; M.rafraichir(); } });
  }

  function aller(cle) { M.go('#agenda/evenement/' + cle); }
  function demander(o, texte) {
    M.go('#chat');
    setTimeout(() => { const t = document.querySelector('[data-chat-input]'); if (t) { t.value = texte; t.focus(); } }, 80);
  }

  // ── L'écran ───────────────────────────────────────────────────────────
  M.register('agenda', {
    titre: 'Agenda',
    compte: () => enAttente().length + (S.proposition === 'attend' ? 1 : 0),
    actions,
    monte(sec) {
      M.on(sec, '[data-agauj]', 'click', () => { etat.date = AUJ; etat.moisMini = null; etat.q = ''; etat.cherche = false; M.rafraichir(); });
      M.on(sec, '[data-agpas]', 'click', (e, b) => { deplacer(+b.dataset.agpas); M.rafraichir(); if (etat.vue === 'planning') { const s = sec.querySelector('[data-agscroll]'); if (s) s.scrollTop = 0; } });
      M.on(sec, '[data-agvue]', 'click', (e, b) => { etat.q = ''; etat.cherche = false; M.go('#agenda/' + b.dataset.agvue); });
      M.on(sec, '[data-agperiode]', 'click', () => { if (M.mobile()) { etat.mobileMois = !etat.mobileMois; M.rafraichir(); } });
      M.on(sec, '[data-agmini]', 'click', (e, b) => { const m = etat.moisMini || new Date(etat.date.getFullYear(), etat.date.getMonth(), 1); etat.moisMini = new Date(m.getFullYear(), m.getMonth() + +b.dataset.agmini, 1); M.rafraichir(); });
      M.on(sec, '[data-agjour]', 'click', (e, b) => {
        etat.date = lireJ(b.dataset.agjour); etat.moisMini = null; etat.mobileMois = false; etat.q = '';
        if (M.route().item && !VUES.some((v) => v[0] === M.route().item)) M.go(routeVue()); else M.rafraichir();
      });
      M.on(sec, '[data-agjourvue]', 'click', (e, b) => { etat.date = lireJ(b.dataset.agjourvue); etat.q = ''; M.go('#agenda/jour'); });
      sec.addEventListener('change', (e) => { const c = e.target.closest('[data-agcoche]'); if (c) { AG[c.dataset.agcoche].coche = c.checked; M.rafraichir(); } });
      M.on(sec, '[data-agmenu]', 'click', (e, b) => menuAgenda(b, b.dataset.agmenu));
      M.on(sec, '[data-agcals]', 'click', (e, b) => menuAgendasMobile(b));
      M.on(sec, '[data-agev]', 'click', (e, b) => aller(b.dataset.agev));
      M.on(sec, '[data-agfermer]', 'click', () => M.go(routeVue()));
      M.on(sec, '[data-agcol]', 'click', (e, col) => {
        if (e.target !== col) return;
        const r = col.getBoundingClientRect();
        const deb = Math.max(0, Math.min(1410, Math.floor((e.clientY - r.top) / HH * 2) * 30));
        etat.nouveau = { jour: col.dataset.agcol, deb };
        M.go('#agenda/nouveau');
      });
      M.on(sec, '[data-agprop]', 'click', (e, b) => {
        S.proposition = b.dataset.agprop;
        M.toast(S.proposition === 'ajoute' ? 'Ajouté à « Perso » : parti chez Google. Mika te le rappellera la veille au soir.' : 'Refusé : rien n\'est ajouté. Elle ne te le reproposera pas.', { ico: S.proposition === 'ajoute' ? 'check' : 'x' });
        M.compter();
        if (S.proposition === 'refuse' && etat.cle === 'prop-diner') M.go(routeVue()); else M.rafraichir();
      });
      M.on(sec, '[data-agrep]', 'click', (e, b) => {
        const [id, r] = b.dataset.agrep.split(':');
        S.invitations[id] = r;
        M.toast(`Répondu « ${REPONSES[r].toLowerCase()} » à ${M.who(EV[id].invitation.de).court} : parti par ${EV[id].invitation.par}.`, { ico: r === 'non' ? 'x' : 'check' });
        M.rafraichir();
      });
      M.on(sec, '[data-agrepmika]', 'click', (e, b) => {
        const ev = EV[b.dataset.agrepmika], p = ev.invitation.prepare;
        S.invitations[ev.id] = p.reponse;
        M.toast(`Sa réponse est partie à ${M.who(ev.invitation.de).court} : ${REPONSES[p.reponse].toLowerCase()}, « ${p.mot} »`, { ico: 'send' });
        M.rafraichir();
      });
      M.on(sec, '[data-agrepnon]', 'click', (e, b) => { S.refusees[b.dataset.agrepnon] = true; M.toast('Elle n\'enverra pas sa réponse : réponds toi-même quand tu veux.', { ico: 'x' }); M.rafraichir(); });
      M.on(sec, '[data-agrepchanger]', 'click', (e, b) => { delete S.invitations[b.dataset.agrepchanger]; S.refusees[b.dataset.agrepchanger] = true; M.rafraichir(); });
      M.on(sec, '[data-agrepmot]', 'click', (e, b) => {
        const ev = EV[b.dataset.agrepmot], p = ev.invitation.prepare;
        const el = M.modal({ titre: `Répondre à ${M.who(ev.invitation.de).nom}`, taille: 'narrow',
          corps: `<div class="stack"><div class="seg" data-seg="agrepm">${Object.entries(REPONSES).map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === p.reponse}">${l}</button>`).join('')}</div>
            <label class="field"><span>Le mot qui part avec</span><textarea rows="3" data-agmot>${h(p.mot)}</textarea></label><p class="small muted">Préparé par Mika ; il part par ${h(ev.invitation.par)}.</p></div>`,
          pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>${ico('send', 'sm')}Envoyer</button>` });
        el.querySelector('[data-ok]').addEventListener('click', () => {
          const r = (el.querySelector('[data-seg="agrepm"] [aria-pressed="true"]') || {}).dataset.v || p.reponse;
          S.invitations[ev.id] = r; M.fermerModal(); M.toast(`Parti à ${M.who(ev.invitation.de).court} : ${REPONSES[r].toLowerCase()}.`, { ico: 'send' }); M.rafraichir();
        });
      });
      M.on(sec, '[data-agaction]', 'click', (e, b) => {
        const o = trouver(etat.cle);
        if (!o) return;
        const k = b.dataset.agaction;
        if (k === 'dupliquer') formulaire('dupliquer', o);
        if (k === 'supprimer') supprimer(o);
        if (k === 'demander') demander(o, `à propos de « ${o.ev.titre} » (${jourCourt(o.jour)}${o.journee ? '' : ' à ' + hm(o.deb)}) : `);
        if (k === 'parler') demander(o, `à propos de « ${o.ev.titre.charAt(0).toLowerCase() + o.ev.titre.slice(1)} » : `);
      });
      M.on(sec, '[data-agrappel]', 'click', (e, b) => {
        const o = trouver(b.dataset.agrappel);
        M.menu(b, [{ entete: 'Mika te le rappelle' }, ...RAPPELS.map(([k, l]) => ({ label: l, coche: (o.ev.rappel || AG[o.ev.agenda].rappel) === k,
          action: () => { o.ev.rappel = k; M.rafraichir(); M.toast(k === 'non' ? 'Elle ne te le rappellera pas.' : `Elle te le rappellera ${rappelDit(k)}.`, { mika: true, ico: 'bell' }); } }))]);
      });
      M.on(sec, '[data-agvisio]', 'click', () => M.toast('Maquette : ouvrirait la réunion dans Teams.', { ico: 'video' }));
      M.on(sec, '[data-agchercher]', 'click', () => { etat.cherche = true; M.rafraichir(); const i = sec.querySelector('[data-agq]'); if (i) i.focus(); });
      M.on(sec, '[data-agqvide]', 'click', () => { etat.q = ''; etat.cherche = false; M.rafraichir(); });
      sec.addEventListener('input', (e) => {
        if (!e.target.matches('[data-agq]')) return;
        etat.q = e.target.value; etat.cherche = true;
        const pos = e.target.selectionStart; M.rafraichir();
        const i = sec.querySelector('[data-agq]'); if (i) { i.focus(); i.setSelectionRange(pos, pos); }
      });
      sec.addEventListener('focusout', (e) => { if (e.target.matches('[data-agq]') && !etat.q) setTimeout(() => { if (!etat.q && etat.cherche) { etat.cherche = false; M.rafraichir(); } }, 150); });
    },
    rendu(body, ctx) {
      const r = lire(ctx);
      const ancien = body.querySelector('[data-agscroll]');
      const garde = ancien ? { v: ancien.dataset.agscroll, top: ancien.scrollTop } : null;
      const o = r.volet === 'fiche' ? trouver(r.id) : null;
      const volet = o ? fiche(o) : r.volet === 'invitations' ? voletInvitations() : '';
      ctx.el.classList.toggle('ag-volet-ouvert', !!volet);
      body.innerHTML = `<div class="ag${volet ? ' avec-volet' : ''}">${colonne()}<section class="pane ag-main">${mobileMois()}${bandeau()}${vue()}</section>${volet}</div>`;
      const sc = body.querySelector('[data-agscroll]');
      if (sc && sc.dataset.agscroll === 'grille') {
        const cible = o && !o.journee ? Math.max(0, o.deb / 60 * HH - 3 * HH) : 7.5 * HH;
        sc.scrollTop = garde && garde.v === 'grille' ? garde.top : cible;
        // l'événement ouvert reste en vue (sous l'en-tête des jours, qui colle en haut)
        if (o && !o.journee && (o.deb / 60 * HH < sc.scrollTop || o.finMin / 60 * HH > sc.scrollTop + sc.clientHeight - 120)) sc.scrollTop = cible;
      } else if (sc && garde && garde.v === sc.dataset.agscroll) sc.scrollTop = garde.top;
      if (!r.modal && document.querySelector('#modal-root .ag-modal')) M.fermerModal();
      if (r.modal === 'nouveau') formulaire('nouveau');
      if (r.modal === 'modifier') { const x = trouver(r.id); if (x) formulaire('modifier', x); }
      if (r.modal === 'partager') partager(r.id);
    },
    recherche: () => [
      { groupe: 'Agenda', titre: 'Créer un événement', ico: 'plus', route: '#agenda/nouveau' },
      { groupe: 'Agenda', titre: 'Les invitations', sous: `${enAttente().length} en attente`, ico: 'inbox', route: '#agenda/invitations' },
      ...occurrences(AUJ, plus(AUJ, 14)).filter(visible).map((o) => ({ groupe: 'Agenda', titre: o.ev.titre, sous: `${AG[o.ev.agenda].nom} · ${jourCourt(o.jour)}${o.journee ? '' : ' ' + hm(o.deb)}`, ico: 'agenda', route: '#agenda/evenement/' + o.cle })),
      ...A.agendas.filter((a) => a.visible).map((a) => ({ groupe: 'Agenda', titre: `Agenda « ${a.nom} »`, sous: fournisseur(a), ico: 'agenda', route: reglages(a) })),
    ],
    notes: () => [
      { groupe: 'Décidé le 2026-11-23', statut: 'decide', titre: 'Cinq sortes d\'agendas', texte: 'l\'agenda du système (« Mon agenda », pour chaque personne qui a un compte, et d\'autres qu\'on crée), Google Agenda, Outlook.com / Microsoft 365, CalDAV (Outlook pro par DavMail, iCloud, Nextcloud, Fastmail), l\'abonnement iCal en lecture seule', src: 'output/agenda/CONCEPTION.md' },
      { statut: 'decide', titre: 'Trois niveaux de partage', texte: 'Lire · Lire et préparer · S\'en servir, comme Mail et Teams ; avec une personne qui a un compte, jamais « tout le monde » ; seul le propriétaire partage' },
      { statut: 'decide', titre: 'Ce que Mika fait d\'elle-même', texte: 'elle sait ta journée ; elle te rappelle un rendez-vous avant ; elle propose d\'ajouter un rendez-vous décidé dans la conversation ; elle prépare la réponse à une invitation, toujours avec ton accord' },
      { statut: 'decide', titre: 'Un tableau de droits par agenda', texte: 'Lire ; Ajouter, modifier, supprimer ; Répondre aux invitations ; Ce qu\'elle en garde — sur des lignes Qui × Par où × Quand (Outils › Droits)' },
      { groupe: 'Ce que montre la maquette', statut: 'decide', titre: 'Le rose est à Mika', texte: 'ce qu\'elle a ajouté (« Ajouté par Mika », et d\'où), ce qu\'elle propose (hachuré, en attente de ton accord, dans la grille et en tête de la vue), son agenda ; l\'indigo reste à toi (aujourd\'hui, maintenant, tes boutons)' },
      { statut: 'decide', titre: 'Une invitation en pointillés', texte: 'tant que tu n\'as pas répondu ; « peut-être » hachuré ; un refus disparaît de la grille' },
      { groupe: 'Ce qui existe déjà dans le moteur', statut: 'existe', titre: 'Ses promesses datées, ce qu\'elle voit venir', texte: 'les moments de ta vie qu\'elle retient, ce qui approche, les dates de chaque année : de quoi montrer « L\'agenda de Mika » sans rien recopier', src: 'contracts/memory.py (KEEP_PROMISE, LifeEvent, memory.ahead, memory.upcoming) · faculties/memory/archive.py:136 (memory.calendar)' },
      { statut: 'existe', titre: 'Ses rappels', texte: 'un rappel à l\'heure promis dans la conversation, que l\'arbitre juge le moment venu', src: 'faculties/goals/tools.py:366 goal_remind' },
      { statut: 'existe', titre: 'Les cartes d\'accord, les droits, à qui est un compte', texte: 'une écriture est une capacité, après le commit, avec ou sans accord selon le tableau ; vide = à toi, elle, personne:<clé>', src: 'vocab/access.py · vocab/rights.py · vocab/ownership.py' },
      { statut: 'existe', titre: 'Le code d\'appareil Microsoft', texte: 'fait pour les boîtes Outlook ; à étendre à l\'agenda (Graph)', src: 'ADR 0166, 0238' },
      { groupe: 'À faire (rien n\'est codé)', statut: 'manque', titre: 'Le port, la base, le fournisseur Système', texte: 'ports/agenda.py, agenda.db, les comptes dans les réglages (lot 0)' },
      { statut: 'manque', titre: 'Les fournisseurs et la synchro', texte: 'iCal et CalDAV (lot 1), Google et Microsoft (lot 2) ; incrémentale quand le fournisseur le sait (syncToken, delta, sync-collection) ; la panne dans la santé et sur le compte' },
      { statut: 'manque', titre: 'Le plugin', texte: 'agenda_list, agenda_events, agenda_free, agenda_create, agenda_edit, agenda_delete, agenda_respond ; la section « ta journée » du prompt ; les rappels ; les invitations ; voix.yaml (lot 3)' },
      { statut: 'manque', titre: 'L\'API par personne', texte: '/api/moi/agenda : les agendas, les événements d\'une période, les invitations et les propositions ; écrire, répondre, partager (lot 4, protocole-moi.md)' },
      { groupe: 'À trancher', statut: 'À trancher', titre: 'Les invitations entre personnes qui ont un compte', texte: 'un événement de l\'agenda système où Léa est invitée : lui arrive-t-il comme une invitation dans son Agenda (Accepter · Peut-être · Refuser), ou seulement par Mika ? La maquette montre les invitations d\'Outlook, et dit seulement dans le formulaire qu\'elle « arrive aussi dans Mika »' },
      { statut: 'À trancher', titre: 'L\'agenda de Mika : lecture seule, tiré de sa mémoire, sans copie', texte: 'ses promesses datées et les moments de ta vie qu\'elle retient, jamais ce qu\'un autre lui a confié ; on le corrige en le lui disant. Est-ce bien un agenda de la liste (proposé), ou seulement « Ce qu\'elle t\'a promis » ailleurs ? Les dates de chaque année qu\'elle retient (anniversaires) n\'y sont pas : elles doubleraient « Famille »' },
      { statut: 'À trancher', titre: 'Un partage dans Mika n\'est pas un partage chez Google', texte: 'partager « Famille » ici l\'ouvre à Léa dans son Mika ; le partage Google (Maman, Léa) reste chez Google, et ne se voit pas ici. La fenêtre le dit ; faut-il aller plus loin (refuser, ou avertir quand la personne y a déjà accès chez Google) ?' },
      { statut: 'À trancher', titre: 'Le rappel par défaut de chaque sorte', texte: 'proposé : Système → Mika 30 min (il n\'a pas d\'autre notification) ; Google, Outlook, CalDAV → le rappel du fournisseur, et Mika selon l\'agenda ; un abonnement → aucun' },
      { statut: 'À trancher', titre: 'La fenêtre de synchronisation', texte: 'proposé : 90 jours derrière, un an devant ; au-delà, l\'écran demande au fournisseur (un mois lointain, une recherche)' },
      { statut: 'À trancher', titre: 'Combien de temps attend une proposition', texte: 'la carte du chat expire comme les autres ; la proposition, elle, reste dans l\'Agenda jusqu\'à ce que tu décides ou que la date passe' },
      { statut: 'À trancher', titre: 'Un événement refusé', texte: 'il disparaît de la grille, comme chez Google par défaut ; il reste dans « Déjà répondu » des invitations' },
      { statut: 'À trancher', titre: 'Sur un téléphone', texte: 'Planning par défaut, le mois se déplie sous le titre, les agendas dans un menu, Créer en bouton + ; la vue « 3 jours » reste à l\'app Android' },
    ],
  });

  /* La barre du bas d'un téléphone : dix rubriques ne tiennent pas sur 390 px. Carte, Outils et Réglages passent
     sous « Plus » (ils restent dans la page, repliés : agenda.css). */
  const PLUS = [['carte', 'Carte', 'map'], ['outils', 'Outils', 'tools'], ['parametres', 'Réglages', 'settings']];
  function majPlus() { const b = document.querySelector('[data-tab-plus]'); if (b && M.ecrans.chat) b.classList.toggle('on', PLUS.some(([k]) => k === M.route().screen)); }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab-plus]');
    if (!b) return;
    e.stopPropagation();
    M.menu(b, PLUS.map(([k, l, i]) => ({ label: l, ico: i, coche: M.route().screen === k ? true : null, action: () => M.go('#' + k) })));
  });
  addEventListener('hashchange', majPlus);
  addEventListener('load', majPlus);

  /* Ce que les fichiers posés par-dessus Paramètres, Outils et le chat empruntent. */
  M.agenda = { A, AG, EV, CPT, NIVEAUX, RAPPELS, rappelDit, fournisseur, chez, proprio, sw, trouver, occurrences, jourDit, jourCourt, hm, cap, lireJ, partager };
})();
