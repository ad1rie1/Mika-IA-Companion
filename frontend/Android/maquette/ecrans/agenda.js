/* Agenda (proposé le 2026-11-23, pas encore validé ; output/agenda/CONCEPTION.md). L'écran Agenda du web
   (frontend/Web/maquette/ecrans/agenda.js) dit avec les codes d'un agenda de téléphone, comme Google Agenda ou Samsung
   Calendar : le mois en titre, qui déplie le mini-mois sous la barre ; chercher, « Aujourd'hui » (l'icône au numéro du
   jour), ⋮ (les cinq vues, les agendas à afficher, les invitations) ; Planning · Jour · 3 jours · Semaine · Mois, qu'on
   balaie pour changer de période ; la ligne de l'heure ; le bouton + ; « À décider » en tête (la proposition de Mika,
   les invitations) ; la fiche d'un événement en page ; les invitations ; partager un agenda ; la notification d'un rappel.

   Le rose est à Mika : ce qu'elle a ajouté, ce qu'elle propose (hachuré, en attente de ton accord), et son agenda à elle,
   tiré de sa mémoire, en lecture seule. L'indigo est à toi (aujourd'hui, maintenant, tes boutons).

   Les données sont celles de la maquette web (`frontend/Web/maquette/ecrans/agenda-donnees.js`), lues là où elles sont.
   Les écrans validés ne se retouchent pas : ce fichier ajoute l'écran `agenda`, et se pose sur le tiroir (« Agenda »
   après Teams) et sur Plus (variante barre). Le formulaire est dans agenda-edition.js ; Paramètres, Outils et le chat
   dans agenda-parametres.js, agenda-droits.js, agenda-chat.js. A.agenda leur prête ses pièces.

   Routes : #agenda (la dernière vue, Planning d'abord), #agenda/planning, /jour, /3jours, /semaine, /mois,
   /mois-deplie, /agendas (la feuille), /agendas/<agenda>, /partager/<agenda>, /tiroir, /notification, /chercher,
   /invitations, /evenement/<id>[@AAAA-MM-JJ][/mot|/rappel|/supprimer]. */
(function () {
  const { h, ico, av, D } = A;
  const G = window.MIKA_AGENDA;
  const S = G.etat;
  S.supprimes = S.supprimes || {};
  const AG = Object.fromEntries(G.agendas.map((a) => [a.id, a]));
  const EV = Object.fromEntries(G.evenements.map((e) => [e.id, e]));
  const CPT = Object.fromEntries(G.comptes.map((c) => [c.id, c]));

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
  const AUJ = lireJ(G.aujourdhui), MAINTENANT = min(G.heure);
  const ecart = (d) => ecartJ(AUJ, d);
  const num = (d) => (d.getDate() === 1 ? '1er' : String(d.getDate()));
  const jourDit = (d) => `${JOURS[d.getDay()]} ${num(d)} ${MOIS[d.getMonth()]}${d.getFullYear() !== AUJ.getFullYear() ? ' ' + d.getFullYear() : ''}`;
  const jourCourt = (d) => `${JC[d.getDay()]} ${d.getDate()} ${MC[d.getMonth()]}`;
  const moisAn = (d) => cap(MOIS[d.getMonth()]) + (d.getFullYear() !== AUJ.getFullYear() ? ' ' + d.getFullYear() : '');

  // ── Les agendas et leurs comptes ──────────────────────────────────────
  const NIVEAUX = {
    lire: ['Lire', 'voit ses événements dans son Agenda, sans rien y changer.'],
    preparer: ['Lire et préparer', 'les voit, et Mika peut y préparer un ajout pour elle ou lui : il n\'entre qu\'avec ton accord.'],
    servir: ['S\'en servir', 'Mika s\'en sert avec elle ou lui, en tête-à-tête : trouver un créneau, y ajouter un rendez-vous, selon ton tableau de droits.'],
  };
  const RAPPELS = [['non', 'Non'], ['15', '15 min avant'], ['30', '30 min avant'], ['60', '1 h avant'], ['veille', 'La veille au soir']];
  const rappelDit = (k) => ({ non: 'non', 15: '15 min avant', 30: '30 min avant', 60: '1 h avant', veille: 'la veille au soir' }[k] || k);
  const REPONSES = { oui: 'Accepter', peut: 'Peut-être', non: 'Refuser' };
  const REP_DIT = { oui: 'oui', peut: 'peut-être', non: 'non' };
  const compte = (a) => CPT[a.compte] || null;
  const proprio = (a) => a.groupe === 'mes' || a.groupe === 'abonnements';
  function fournisseur(a) {
    if (a.groupe === 'partages') return `de ${A.who(a.de).court} · ${NIVEAUX[a.niveau][0].toLowerCase()}`;
    if (a.groupe === 'mika') return 'sa mémoire · lecture seule';
    const c = compte(a);
    if (!c) return '';
    if (c.sorte === 'caldav') return 'CalDAV · DavMail';
    if (c.sorte === 'ical') return 'abonnement iCal';
    return G.sortes[c.sorte].nom;
  }
  function chez(a) {
    const c = compte(a);
    return c ? { systeme: 'sur ce serveur', caldav: 'chez Outlook, par DavMail', google: 'chez Google', microsoft: 'chez Microsoft', ical: '' }[c.sorte] : '';
  }
  const ecrivables = () => G.agendas.filter((a) => a.ecrire && a.visible && proprio(a));
  const sw = (couleur, cls) => `<span class="ag-sw${cls ? ' ' + cls : ''}" style="--c:var(--ag-${couleur})"></span>`;
  const reglages = (a) => (proprio(a) ? `#parametres/agendas/${a.compte}/${a.id}` : '#parametres/agendas');
  const avP = (k, cls) => (typeof k === 'string' ? av(k, cls) : `<span class="av c2${cls ? ' ' + cls : ''}">${h(A.initiales(k.nom))}</span>`);
  const nomP = (k) => (typeof k === 'string' ? A.who(k).nom : k.nom);
  /* Ce que Mika fait d'un agenda, en une ligne, d'après son tableau (Outils › Droits). */
  function resume(agId) {
    const L = G.droits[agId];
    if (!L) return '';
    const t = L.find((l) => l.qui === 'toi' && (l.quand === 'repond' || l.quand === 'toujours')) || L[0];
    const ECR = { non: 'n\'y écrit pas', accord: 'y ajoute avec ton accord', seule: 'y ajoute seule', '—': '' };
    const parts = [t.lire === 'oui' ? 'le lit' : 'ne le lit pas', ECR[t.ecrire], t.repondre === 'accord' ? 'prépare tes réponses' : ''].filter(Boolean);
    const avec = L.filter((l) => l.partage && l.qui !== 'toi').map((l) => A.who(l.qui).court);
    return `Avec toi, elle ${parts.join(', ')}${avec.length ? ` · aussi avec ${avec.join(' et ')}` : ''}`;
  }

  // ── Les occurrences d'une période (les récurrences dépliées) ──────────
  function occ(ev, d, fin) {
    return { ev, cle: ev.rec ? `${ev.id}@${ymd(d)}` : ev.id, jour: d, fin, journee: !!ev.journee,
      deb: ev.journee ? 0 : min(ev.de), finMin: ev.journee ? 1440 : min(ev.a) };
  }
  function occurrences(du, au) {   // du compris, au exclu
    const out = [];
    for (const ev of G.evenements) {
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
  const enAttente = () => G.evenements.filter((e) => e.invitation && !S.invitations[e.id] && !S.supprimes[e.id]).map((e) => trouver(e.id));
  const aDecide = () => enAttente().length + (S.proposition === 'attend' ? 1 : 0);
  const lieuCourt = (l) => String(l).split(' · ')[0];
  const styleC = (o) => `--c:var(--ag-${couleur(o)})`;
  const classes = (o) => [sorte(o), passe(o) ? 'passe' : ''].filter(Boolean).join(' ');
  const marque = (o) => {
    const s = sorte(o);
    return s === 'propose' || s === 'mika' || ajouteParMika(o) ? `<span class="ag-mk" title="${s === 'propose' ? 'Mika propose de l\'ajouter' : s === 'mika' ? 'L\'agenda de Mika' : 'Ajouté par Mika'}">${ico('sparkle', 'xxs')}</span>` : '';
  };
  const quandCourt = (o) => (o.journee ? (mem(o.jour, o.fin) ? 'Journée entière' : `Jusqu'au ${jourCourt(o.fin)}`) : `${hm(o.deb)} – ${hm(o.finMin)}`);
  const quandDit = (o) => (o.journee
    ? (mem(o.jour, o.fin) ? `${cap(jourDit(o.jour))} · journée entière` : `Du ${jourDit(o.jour)} au ${jourDit(o.fin)}`)
    : `${cap(jourDit(o.jour))} · ${hm(o.deb)} – ${hm(o.finMin)}`);
  function recurrence(ev) {
    if (!ev.rec) return '';
    const d0 = lireJ(ev.j);
    if (ev.rec.freq === 'an') return `Chaque année, le ${num(d0)} ${MOIS[d0.getMonth()]}`;
    return `Chaque ${JOURS[d0.getDay()]}${ev.rec.jusqu ? `, jusqu'au ${jourDit(lireJ(ev.rec.jusqu))}` : ''}`;
  }

  // ── L'état de l'écran ─────────────────────────────────────────────────
  const VUES = [['planning', 'Planning', 'view-list'], ['jour', 'Jour', 'view-day'], ['3jours', '3 jours', 'view-3'], ['semaine', 'Semaine', 'view-week'], ['mois', 'Mois', 'view-month']];
  const etat = { vue: 'planning', date: AUJ, mm: false, mmMois: null, decide: null, sens: 0 };
  const HH = 48;   // la hauteur d'une heure dans la grille, en dp
  const routeVue = () => (etat.vue === 'planning' ? '#agenda' : '#agenda/' + etat.vue);

  function bornes() {
    const d = etat.date;
    if (etat.vue === 'jour') return [d, plus(d, 1)];
    if (etat.vue === '3jours') return [d, plus(d, 3)];
    if (etat.vue === 'semaine') { const l = lundi(d); return [l, plus(l, 7)]; }
    if (etat.vue === 'mois') {
      const l = lundi(new Date(d.getFullYear(), d.getMonth(), 1)), fin = new Date(d.getFullYear(), d.getMonth() + 1, 1);
      return [l, plus(l, Math.ceil(ecartJ(l, fin) / 7) * 7)];
    }
    return [d, plus(d, 28)];
  }
  function deplacer(sens) {
    const d = etat.date;
    if (etat.vue === 'mois') { const m = new Date(d.getFullYear(), d.getMonth() + sens, 1); etat.date = m.getMonth() === AUJ.getMonth() && m.getFullYear() === AUJ.getFullYear() ? AUJ : m; }
    else etat.date = plus(d, { jour: 1, '3jours': 3, semaine: 7, planning: 28 }[etat.vue] * sens);
    etat.mmMois = null;
    etat.sens = sens;
  }
  function titre() {
    if (etat.mm) return moisAn(etat.mmMois || etat.date);
    if (etat.vue === '3jours' || etat.vue === 'semaine') {
      const [du, au] = bornes(), der = plus(au, -1);
      if (du.getMonth() !== der.getMonth()) return `${cap(MC[du.getMonth()])} – ${MC[der.getMonth()]}${der.getFullYear() !== AUJ.getFullYear() ? ' ' + der.getFullYear() : ''}`;
      return moisAn(du);
    }
    return moisAn(etat.date);
  }

  // ── La barre du haut ──────────────────────────────────────────────────
  function barre() {
    const t = `${h(titre())}<svg class="ico ag-tchev${etat.mm ? ' up' : ''}"><use href="#i-chev-down"/></svg>`;
    const auj = `<button class="ibtn ag-auj" type="button" data-agauj title="Aujourd'hui, ${h(jourDit(AUJ))}" aria-label="Aujourd'hui">${ico('today')}<span>${AUJ.getDate()}</span></button>`;
    return A.top({ racine: true, back: A.v.nav === 'barre', title: t, small: true, cls: 'ag-top',
      titleAttrs: `data-agmm aria-expanded="${etat.mm}" title="${etat.mm ? 'Replier le mois' : 'Déplier le mois'}"`,
      actions: [A.act('search', 'Chercher dans tes agendas', 'data-go="#agenda/chercher"'), auj, A.act('more', 'Vues et agendas', 'data-menu="agenda"')] });
  }

  // ── Le mini-mois, déplié sous la barre ────────────────────────────────
  function grilleMois(m, opts) {
    const o = opts || {};
    const debut = lundi(m);
    const occs = occurrences(debut, plus(debut, 42)).filter(visible);
    const avec = new Set();
    occs.forEach((x) => { for (let d = x.jour; d <= x.fin; d = plus(d, 1)) avec.add(ymd(d)); });
    const rangs = plus(debut, 35).getMonth() !== m.getMonth() ? 5 : 6;
    const [du, au] = bornes();
    const bande = !o.picker && (etat.vue === 'semaine' || etat.vue === '3jours');
    let cases = '';
    for (let i = 0; i < rangs * 7; i++) {
      const d = plus(debut, i), dans = bande && d >= du && d < au;
      const sel = o.picker ? mem(d, o.sel) : mem(d, etat.date) && !mem(d, AUJ);
      const cls = [d.getMonth() !== m.getMonth() ? 'hors' : '', mem(d, AUJ) ? 'auj' : '', sel ? 'sel' : '', dans ? 'dans' : '',
        dans && mem(d, du) ? 'debut' : '', dans && mem(d, plus(au, -1)) ? 'fin' : ''].filter(Boolean).join(' ');
      cases += `<button type="button" class="${cls}" ${o.picker ? `data-agpick-j="${ymd(d)}"` : `data-agjour="${ymd(d)}"`} aria-label="${h(jourDit(d))}"><i>${d.getDate()}</i>${!o.picker && avec.has(ymd(d)) ? '<em></em>' : ''}</button>`;
    }
    return `<div class="ag-mm-h">${['L', 'M', 'M', 'J', 'V', 'S', 'D'].map((x) => `<span>${x}</span>`).join('')}</div><div class="ag-mm-g">${cases}</div>`;
  }
  function miniMois() {
    const m = etat.mmMois || new Date(etat.date.getFullYear(), etat.date.getMonth(), 1);
    const n = G.agendas.filter((a) => a.visible).length, c = G.agendas.filter((a) => a.visible && a.coche).length;
    return `<div class="ag-mm" data-agmmswipe>${grilleMois(m)}
      <div class="ag-mm-f"><button class="btn text sm" type="button" data-sheet="ag-agendas">${ico('eye', 'sm')}Agendas à afficher · ${c} sur ${n}</button><span class="grow"></span>
        <button class="ibtn" type="button" data-agmmpas="-1" aria-label="Mois précédent">${ico('chev-left', 'sm')}</button><button class="ibtn" type="button" data-agmmpas="1" aria-label="Mois suivant">${ico('chev-right', 'sm')}</button></div></div>`;
  }

  // ── À décider : la proposition de Mika, les invitations ───────────────
  function carteProp(o, plier) {
    const a = AG[o.ev.agenda];
    return `<div class="ag-prop"><div class="ag-prop-t"><button class="ag-prop-h" type="button" data-go="#agenda/evenement/prop-diner">${A.face(32)}
        <span class="grow"><b>Mika propose « ${h(o.ev.titre)} »</b><small>${h(cap(jourCourt(o.jour)))} · ${hm(o.deb)} – ${hm(o.finMin)} · ${sw(a.couleur, 'xs')} ${h(a.nom)}</small></span></button>${plier || ''}</div>
      <div class="btns end"><button class="btn text sm" type="button" data-agprop="refuse">Refuser</button><button class="btn text sm" type="button" data-go="#agenda/modifier/prop-diner">Modifier</button>
        <button class="btn filled sm" type="button" data-agprop="ajoute">${ico('check')}Ajouter</button></div></div>`;
  }
  function ligneInv(o) {
    const inv = o.ev.invitation, p = inv.prepare;
    return `<button class="li ag-inv-li" type="button" data-go="#agenda/evenement/${h(o.cle)}">${av(inv.de, 'sm')}
      <span class="txt"><b>${h(o.ev.titre)}</b><small>${h(A.who(inv.de).court)} t'invite · ${h(jourCourt(o.jour))}, ${hm(o.deb)}</small>
      ${p && !S.refusees[o.ev.id] ? `<small class="mk-txt">${ico('sparkle', 'xxs')} Mika a préparé : ${h(REPONSES[p.reponse].toLowerCase())}</small>` : ''}</span>${ico('chev-right', 'sm')}</button>`;
  }
  /* Replié : une ligne, comme celle des accords du chat. Déplié : la proposition et ses boutons, puis les invitations
     (une ligne vers leur page quand la proposition est là, sinon chacune). */
  function aDecider() {
    const invs = enAttente(), prop = S.proposition === 'attend' ? trouver('prop-diner') : null;
    if (!invs.length && !prop) return '';
    const ouvert = etat.decide == null ? etat.vue === 'planning' : etat.decide;
    const n = invs.length + (prop ? 1 : 0);
    const resume = [prop ? `Mika propose « ${prop.ev.titre} »` : '', invs.length ? `${invs.length} invitation${invs.length > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ');
    const plier = `<button class="ibtn ag-dec-x" type="button" data-agdecide aria-expanded="true" aria-label="Replier ce qui attend ta décision">${ico('chev-up', 'sm')}</button>`;
    if (!ouvert) {
      return `<div class="ag-dec"><button class="ag-dec-l" type="button" data-agdecide aria-expanded="false">${ico('sparkle', 'sm')}<span class="grow ellipsis"><b>À décider</b> · ${h(resume)}</span>
        <span class="cnt-pill mk">${n}</span><svg class="ico sm"><use href="#i-chev-down"/></svg></button></div>`;
    }
    const invL = prop
      ? (invs.length ? `<button class="ag-dec-inv1" type="button" data-go="#agenda/invitations">${ico('inbox', 'sm')}<span class="grow ellipsis"><b>${invs.length} invitation${invs.length > 1 ? 's' : ''}</b> · ${h(invs.map((o) => A.who(o.ev.invitation.de).court).join(', '))} · <span class="mk-txt">Mika a préparé tes réponses</span></span>${ico('chev-right', 'sm')}</button>` : '')
      : `<div class="ag-dec-h">${ico('inbox', 'sm')}<b class="grow">${invs.length} invitation${invs.length > 1 ? 's' : ''}</b>${plier}</div>${invs.map(ligneInv).join('')}`;
    return `<div class="ag-dec ouvert">${prop ? carteProp(prop, plier) : ''}${invL}</div>`;
  }

  // ── Les pièces des vues ───────────────────────────────────────────────
  function etiquettes(o) {
    const s = sorte(o), out = [];
    if (s === 'invite') out.push(`<span class="ag-t inv">invitation · ${h(A.who(o.ev.invitation.de).court)}</span>`);
    if (s === 'peut') out.push('<span class="ag-t">peut-être</span>');
    if (s === 'propose') out.push(`<span class="ag-t mk">${ico('sparkle', 'xxs')}proposé par Mika</span>`);
    if (ajouteParMika(o)) out.push(`<span class="ag-t mk quiet">${ico('sparkle', 'xxs')}ajouté par Mika</span>`);
    if (s === 'mika') out.push(`<span class="ag-t mk">${ico('sparkle', 'xxs')}${o.ev.mika.sorte === 'promesse' ? 'promis' : 'elle s\'en souvient'}</span>`);
    return out.join('');
  }
  function carte(o) {
    const ev = o.ev, ou = ev.lieu ? lieuCourt(ev.lieu) : ev.visio ? `visio ${ev.visio}` : '', t = etiquettes(o);
    return `<button type="button" class="ag-pc ${classes(o)}" style="${styleC(o)}" data-go="#agenda/evenement/${h(o.cle)}">
      <b>${marque(o)}<span class="ellipsis">${h(ev.titre)}</span>${ev.rec ? ico('repeat', 'xxs') : ''}</b>
      <small class="ellipsis">${h(quandCourt(o))}${ou ? ' · ' + h(ou) : ''}${o.ev.agenda !== 'mika' && !ev.proposition ? ` · ${h(AG[ev.agenda].nom)}` : ''}</small>${t ? `<span class="ag-tags">${t}</span>` : ''}</button>`;
  }

  // Planning : une liste par jour, à partir du jour choisi, quatre semaines.
  function vuePlanning() {
    const [du, au] = bornes();
    const occs = occurrences(du, au).filter(visible);
    const jours = new Map();
    if (AUJ >= du && AUJ < au) jours.set(ymd(AUJ), []);
    occs.forEach((o) => {
      const fin = o.journee ? o.fin : o.jour;
      for (let d = o.jour; d <= fin; d = plus(d, 1)) {
        if (d < du) continue;
        if (d >= au) break;
        const k = ymd(d);
        if (!jours.has(k)) jours.set(k, []);
        jours.get(k).push(o);
      }
    });
    let mois = du.getMonth(), out = '';
    [...jours.keys()].sort().forEach((k) => {
      const d = lireJ(k), auj = mem(d, AUJ), os = jours.get(k);
      if (d.getMonth() !== mois) { mois = d.getMonth(); out += `<h3 class="ag-pm">${h(cap(MOIS[mois]))} ${d.getFullYear()}</h3>`; }
      let lignes = '', dite = false;
      const now = `<div class="ag-pl-now" title="Maintenant, ${h(G.heure)}"><i></i></div>`;
      os.sort((a, b) => (b.journee - a.journee) || a.deb - b.deb).forEach((o) => {
        if (auj && !dite && !o.journee && o.deb > MAINTENANT) { lignes += now; dite = true; }
        lignes += carte(o);
      });
      if (auj && !dite) lignes += now;
      out += `<section class="ag-pd${auj ? ' auj' : ''}"><button class="ag-pd-d" type="button" data-agjourvue="${k}" aria-label="${h(cap(jourDit(d)))}"><small>${JC[d.getDay()]}</small><b>${d.getDate()}</b></button>
        <div class="ag-pd-l">${ecart(d) === 1 ? '<div class="ag-pd-dit">Demain</div>' : auj ? '<div class="ag-pd-dit">Aujourd\'hui</div>' : ''}${lignes}</div></section>`;
    });
    return `<div class="body ag-plan" data-agscroll>${out || `<div class="cx-empty">${ico('agenda')}<b>Rien de prévu</b><p>Aucun événement dans les agendas cochés sur ces quatre semaines.</p></div>`}
      <div class="ag-plan-more"><button class="btn tonal sm" type="button" data-agpas="1">${ico('chev-down', 'sm')}Les quatre semaines suivantes</button></div></div>`;
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
  function blocEv(x, n) {
    const o = x.o, top = x.deb / 60 * HH, hgt = Math.max(18, (o.finMin - o.deb) / 60 * HH - 2);
    const w = 100 / x.ncol, l = x.col * w, court = hgt < 34;
    const s = sorte(o);
    const quand = s === 'invite' ? `${hm(o.deb)} · invitation` : s === 'propose' ? `${hm(o.deb)} · proposé` : `${hm(o.deb)} – ${hm(o.finMin)}`;
    const lieu = n < 7 && o.ev.lieu && hgt > 60 ? `<span>${h(lieuCourt(o.ev.lieu))}</span>` : '';
    const corps = n === 7 ? `<b>${marque(o)}${h(o.ev.titre)}</b>`
      : court ? `<b>${marque(o)}${h(o.ev.titre)}<span class="ag-ev-h"> ${hm(o.deb)}</span></b>` : `<b>${marque(o)}${h(o.ev.titre)}</b><span>${h(quand)}</span>${lieu}`;
    return `<button type="button" class="ag-ev ${classes(o)}${court ? ' court' : ''}" style="${styleC(o)};top:${top}px;height:${hgt}px;left:calc(${l}% + 1px);width:calc(${w}% - 3px)" data-go="#agenda/evenement/${h(o.cle)}" title="${h(o.ev.titre)}">${corps}</button>`;
  }
  // Jour, 3 jours et Semaine : la grille horaire.
  function vueGrille(jours) {
    const n = jours.length, du = jours[0], au = plus(jours[n - 1], 1);
    const occs = occurrences(du, au).filter(visible);
    const ad = occs.filter((o) => o.journee).map((o) => ({ o, s: Math.max(0, ecartJ(du, o.jour)), e: Math.min(n - 1, ecartJ(du, o.fin)) }))
      .sort((a, b) => a.s - b.s || (b.e - b.s) - (a.e - a.s));
    const lanes = [];
    ad.forEach((x) => { let l = lanes.findIndex((f) => f < x.s); if (l < 0) { l = lanes.length; lanes.push(x.e); } else lanes[l] = x.e; x.l = l; });
    const journees = ad.map((x) => `<button type="button" class="ag-ev ag-ad ${classes(x.o)}" style="${styleC(x.o)};grid-column:${x.s + 1} / ${x.e + 2};grid-row:${x.l + 1}" data-go="#agenda/evenement/${h(x.o.cle)}" title="${h(x.o.ev.titre)}">${marque(x.o)}<b>${h(x.o.ev.titre)}</b></button>`).join('');
    const cols = jours.map((d) => {
      const evs = disposer(occs.filter((o) => !o.journee && mem(o.jour, d)).map((o) => ({ o, deb: o.deb, fin: Math.max(o.finMin, o.deb + 24) })));
      const now = mem(d, AUJ) ? `<div class="ag-now" style="top:${MAINTENANT / 60 * HH}px" title="Maintenant, ${h(G.heure)}"></div>` : '';
      return `<div class="ag-col${mem(d, AUJ) ? ' auj' : ''}" data-agcol="${ymd(d)}">${evs.map((x) => blocEv(x, n)).join('')}${now}</div>`;
    }).join('');
    const tetes = jours.map((d) => `<button type="button" class="ag-dh${mem(d, AUJ) ? ' auj' : ''}" data-agjourvue="${ymd(d)}" aria-label="${h(cap(jourDit(d)))}"><small>${JC[d.getDay()]}</small><b>${d.getDate()}</b></button>`).join('');
    const heures = Array.from({ length: 24 }, (_, i) => `<span style="top:${i * HH}px">${i ? pad(i) + ':00' : ''}</span>`).join('');
    return `<div class="ag-g n${n}" style="--n:${n};--hh:${HH}px" data-agswipe>
      <div class="ag-gh"><div class="ag-gut ag-tz" title="${h(G.fuseau)}">${n === 7 ? '' : h(G.fuseauCourt)}</div><div class="ag-dhs">${tetes}</div></div>
      ${ad.length ? `<div class="ag-gad"><div class="ag-gut"></div><div class="ag-ads" style="grid-template-rows:repeat(${lanes.length}, 22px)">${journees}</div></div>` : ''}
      <div class="ag-gs" data-agscroll><div class="ag-gb"><div class="ag-gut ag-hours">${heures}</div><div class="ag-cols">${cols}</div></div></div></div>`;
  }
  // Mois : une case par jour ; la toucher ouvre le jour.
  function vueMois() {
    const [du, au] = bornes(), occs = occurrences(du, au).filter(visible), nj = ecartJ(du, au), m = etat.date.getMonth();
    let cases = '';
    for (let i = 0; i < nj; i++) {
      const d = plus(du, i), k = ymd(d);
      const ce = occs.filter((o) => ymd(o.jour) <= k && ymd(o.fin) >= k);
      const max = 4, vis = ce.slice(0, ce.length > max ? max - 1 : max), reste = ce.length - vis.length;
      cases += `<button type="button" class="ag-mc${d.getMonth() !== m ? ' hors' : ''}${mem(d, AUJ) ? ' auj' : ''}" data-agjourvue="${k}" aria-label="${h(cap(jourDit(d)))} · ${ce.length} événement${ce.length > 1 ? 's' : ''}">
        <span class="ag-mc-n">${d.getDate()}</span>${vis.map((o) => `<span class="ag-mchip ${o.journee ? 'plein ' : ''}${classes(o)}" style="${styleC(o)}">${h(o.ev.titre)}</span>`).join('')}
        ${reste ? `<span class="ag-mc-plus">+${reste}</span>` : ''}</button>`;
    }
    return `<div class="ag-month" data-agswipe><div class="ag-mh">${['L', 'M', 'M', 'J', 'V', 'S', 'D'].map((x) => `<span>${x}</span>`).join('')}</div>
      <div class="ag-mg" style="--r:${nj / 7}">${cases}</div></div>`;
  }
  function vue() {
    if (etat.vue === 'mois') return vueMois();
    if (etat.vue === 'planning') return vuePlanning();
    if (etat.vue === 'jour') return vueGrille([etat.date]);
    if (etat.vue === '3jours') return vueGrille([etat.date, plus(etat.date, 1), plus(etat.date, 2)]);
    const l = lundi(etat.date);
    return vueGrille(Array.from({ length: 7 }, (_, i) => plus(l, i)));
  }

  // ── Les notes du panneau ──────────────────────────────────────────────
  const TRANCHER = [
    '<b>Les vues dans ⋮ (choisi).</b> Le tiroir est la navigation de l\'app : Planning · Jour · 3 jours · Semaine · Mois vont en tête du menu ⋮ (comme Outlook sur Android), et la barre garde la forme de Google Agenda (☰ · le mois ▾ · chercher · aujourd\'hui · ⋮ · son visage) ; la grille garde toute la hauteur. Ou bien une icône de la vue à la place de ⋮, des puces sous le titre (48 dp de moins), ou une feuille qui réunit vues et agendas (le tiroir de Google, en feuille) ?',
    '<b>Les agendas à afficher</b> : une feuille, par ⋮ › « Agendas à afficher » et au pied du mois déplié. Assez à portée de main, ou une icône à part dans la barre ?',
    '<b>« À décider » en tête de chaque vue</b> : déplié en Planning, replié sur une ligne au-dessus des grilles (comme la ligne des accords du chat). La proposition et les invitations sont aussi dans la grille (hachurée, en pointillés). Trop, ou pas assez ?',
    '<b>Agenda dans le tiroir après Teams</b> (avec Mail et Teams, ce qui sert tous les jours), une pastille : ce qui attend ta décision. Dans la variante barre : sous Plus (ici), ou à la place de Carte dans la barre du bas ?',
    'La vue de départ : la dernière choisie (ici), ou toujours Planning ?',
    'Balayer change la période dans Jour, 3 jours, Semaine et Mois ; en Planning on fait défiler (comme Google). D\'accord ?',
    'La semaine sur 384 dp : les titres sont coupés à quelques lettres. La garder (Samsung l\'a), ou laisser la semaine au web et s\'arrêter à 3 jours ?',
    'Les invitations entre personnes qui ont un compte (un événement de l\'agenda du système où Léa est invitée) : une invitation dans son Agenda, ou seulement par Mika ?',
    'L\'agenda de Mika, en lecture seule, tiré de sa mémoire, est-il bien un agenda de la liste, ou seulement « Ce qu\'elle t\'a promis » ailleurs ? Les anniversaires qu\'elle retient n\'y sont pas : ils doubleraient « Famille ».',
    'Un événement refusé disparaît de la grille, comme chez Google ; il reste dans « Déjà répondu » des invitations.',
  ];
  function notesVue(extra) {
    const v = VUES.find((x) => x[0] === etat.vue)[1];
    const parVue = {
      planning: 'Planning : une liste par jour, la date à gauche (aujourd\'hui en indigo), la ligne de l\'heure entre les événements de la journée ; « Les quatre semaines suivantes » au bout. Un événement : la couleur de son agenda, l\'heure, le lieu, l\'agenda ; ↻ s\'il se répète.',
      jour: 'Jour : la grille horaire, la ligne de l\'heure (14:20), les journées entières au-dessus ; balayer passe au jour suivant ; toucher une heure vide crée un événement à cette heure.',
      '3jours': '3 jours, à partir du jour choisi : la vue que le web n\'a pas. Balayer avance de trois jours.',
      semaine: 'Semaine, du lundi au dimanche : les titres seuls, coupés ; la semaine en cours a son jour en indigo. Balayer passe à la suivante.',
      mois: 'Mois : quatre lignes au plus par jour, puis « +2 » ; toucher un jour ouvre sa vue Jour. Balayer change de mois.',
    }[etat.vue];
    return {
      titre: `Agenda · ${v} (proposé)`,
      reprend: [
        'L\'écran Agenda du web, avec les codes d\'un agenda de téléphone (Google Agenda, Samsung Calendar). Barre du haut : ☰ (le tiroir de l\'app), le mois en titre — le toucher déplie le mini-mois sous la barre —, chercher, « Aujourd\'hui » (l\'icône au numéro du jour), ⋮, son visage.',
        '⋮ : les cinq vues (Planning · Jour · 3 jours · Semaine · Mois), « Agendas à afficher » (la feuille), les invitations, les paramètres.',
        parVue,
        '« À décider » en tête : ce que Mika propose d\'ajouter (Refuser · Modifier · Ajouter) et les deux invitations, avec la réponse qu\'elle a préparée. Les mêmes sont dans la vue : la proposition hachurée de rose, une invitation en pointillés.',
        'Le rose est à Mika : ce qu\'elle a ajouté (✦), ce qu\'elle propose, son agenda (promesses, ce qu\'elle retient de ta vie). L\'indigo est à toi : aujourd\'hui, maintenant, tes boutons.',
        'Le bouton + crée un événement (le formulaire en plein écran). Toucher un événement ouvre sa fiche en page.',
        extra || '',
      ].filter(Boolean),
      trancher: TRANCHER,
    };
  }

  // ── L'écran ───────────────────────────────────────────────────────────
  function corps() {
    return `${barre()}${etat.mm ? miniMois() : ''}${aDecider()}<div class="ag-vue v-${etat.vue}${etat.sens ? (etat.sens > 0 ? ' entre-d' : ' entre-g') : ''}" data-agvue>${vue()}</div>
      <button class="fab ag-fab" type="button" data-agnouveau aria-label="Créer un événement" title="Créer un événement">${ico('plus')}</button>`;
  }
  // Redessiner l'écran sans fermer ce qui est ouvert par-dessus (la feuille des agendas, le mois déplié).
  function peindre() {
    const scr = document.querySelector('#app .scr[data-screen="agenda"]');
    if (!scr || !scr.querySelector('[data-agvue]')) { A.render(); return; }
    const garde = scr.querySelector('[data-agscroll]');
    const top = garde && etat.sens === 0 ? garde.scrollTop : null;
    scr.innerHTML = corps();
    brancher(scr, top);
    etat.sens = 0;
  }
  function brancher(root, top) {
    const sc = root.querySelector('[data-agscroll]');
    if (sc && sc.closest('.ag-g')) sc.scrollTop = top != null ? top : 7.5 * HH;
    else if (sc && top != null) sc.scrollTop = top;
    root.querySelectorAll('[data-agswipe]').forEach((el) => balayer(el, (s) => { deplacer(s); peindre(); }));
    root.querySelectorAll('[data-agmmswipe]').forEach((el) => balayer(el, (s) => { moisMini(s); }));
  }
  function moisMini(s) {
    const m = etat.mmMois || new Date(etat.date.getFullYear(), etat.date.getMonth(), 1);
    etat.mmMois = new Date(m.getFullYear(), m.getMonth() + s, 1);
    peindre();
  }
  /* Balayer : un geste horizontal franc change de période ; le toucher qui suit n'ouvre rien. */
  function balayer(el, faire) {
    let x0 = null, y0 = 0;
    el.addEventListener('pointerdown', (e) => { if (e.button) return; x0 = e.clientX; y0 = e.clientY; });
    el.addEventListener('pointerup', (e) => {
      if (x0 == null) return;
      const dx = e.clientX - x0, dy = e.clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy) * 1.4) return;
      const bloque = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      window.addEventListener('click', bloque, { capture: true, once: true });
      setTimeout(() => window.removeEventListener('click', bloque, { capture: true }), 60);
      faire(dx < 0 ? 1 : -1);
    });
    el.addEventListener('pointercancel', () => { x0 = null; });
  }

  function vueAgenda(args) {
    const [a, b] = args;
    if (VUES.some((v) => v[0] === a)) etat.vue = a;
    etat.mm = a === 'mois-deplie';
    if (!etat.mm) etat.mmMois = null;
    const ext = { agendas: 'La feuille « Agendas à afficher » : les cases de leur couleur, groupées (Mes agendas · Partagés avec moi · Abonnements · L\'agenda de Mika) ; ⋮ au bout d\'une ligne : afficher seulement celui-ci, sa couleur, le partager, ses paramètres. Cocher ne change que l\'affichage : Mika s\'en sert toujours.',
      'mois-deplie': 'Le mois déplié sous la barre : un point sous les jours qui ont un événement, aujourd\'hui en indigo, le jour choisi en tonal ; balayer change de mois, toucher un jour y va et replie. Au pied, « Agendas à afficher ».',
      partager: 'Partager un agenda : une feuille, par-dessus la vue.', notification: 'La notification d\'un rappel ou d\'une invitation, dans le volet du téléphone.',
      tiroir: 'Le tiroir de l\'app : « Agenda » après Teams, avec ce qui attend ta décision.' }[a];
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'agenda', racine: true, back: '#plus', cls: 'ag-scr',
      html: corps(),
      notes: a === 'partager' ? notesPartage(b) : a === 'notification' ? notesNotif() : notesVue(ext),
      after(root) {
        brancher(root);
        if (a === 'agendas') { if (b && AG[b]) A.sheets['ag-cal']({ dataset: { agcal: b } }); else A.sheets['ag-agendas'](); }
        if (a === 'partager' && b) A.sheets['ag-partager']({ dataset: { agpartager: b } });
        if (a === 'tiroir') { const t = root.querySelector('[data-drawer]'); if (t) t.click(); }
        if (a === 'notification') volet();
      },
    };
  }

  // ── La fiche d'un événement, en page ──────────────────────────────────
  function relatif(o) {
    const e = ecart(o.jour);
    if (o.journee) { if (ecart(o.fin) < 0) return ['', 'passé']; if (e <= 0) return ['pc', 'aujourd\'hui']; return ['', e === 1 ? 'demain' : `dans ${e} jours`]; }
    if (passe(o)) return ['', 'passé'];
    if (e === 0 && o.deb <= MAINTENANT) return ['ok', 'en cours'];
    if (e === 0) { const m = o.deb - MAINTENANT; return ['pc', m < 60 ? `dans ${m} min` : `dans ${Math.floor(m / 60)} h${m % 60 ? ' ' + pad(m % 60) : ''}`]; }
    return ['', e === 1 ? 'demain' : `dans ${e} jours`];
  }
  const PREP = { org: ['pc', 'organise'], oui: ['ok', 'oui'], peut: ['warn', 'peut-être'], non: ['danger', 'non'], attente: ['', 'sans réponse'] };
  const ligne = (i, corpsL, attrs, cls) => `<${attrs ? `button type="button" ${attrs}` : 'div'} class="ag-f-row${cls ? ' ' + cls : ''}"><span class="ag-f-i">${ico(i)}</span><span class="ag-f-c">${corpsL}</span>${attrs ? ico('chev-right', 'sm') : ''}</${attrs ? 'button' : 'div'}>`;
  function participants(o) {
    const p = o.ev.p;
    if (!p || !p.length) return '';
    const rep = (k, r) => (k === 'adrien' && o.ev.invitation && S.invitations[o.ev.id] ? S.invitations[o.ev.id] : r);
    const n = { oui: 0, peut: 0, non: 0, attente: 0 };
    p.forEach(([k, r]) => { const x = rep(k, r); if (x === 'org' || x === 'oui') n.oui++; else n[x]++; });
    const res = [n.oui ? `${n.oui} oui` : '', n.peut ? `${n.peut} peut-être` : '', n.non ? `${n.non} non` : '', n.attente ? `${n.attente} sans réponse` : ''].filter(Boolean).join(' · ');
    return `${ligne('users', `<b>${p.length} participants</b><small>${h(res)}</small>`)}
      <div class="ag-ppl">${p.map(([k, r]) => {
        const x = rep(k, r), adr = typeof k === 'string' ? ((A.who(k).moyens || []).find((m) => m[0] === 'mail') || ['', ''])[1] : k.adr;
        return `<div class="ag-ppl-r">${avP(k, 'sm')}<span class="txt"><b>${h(nomP(k))}${k === 'adrien' ? ' <span class="muted">(toi)</span>' : ''}</b>${adr ? `<small>${h(adr)}</small>` : ''}</span><span class="tag ${PREP[x][0]}">${PREP[x][1]}</span></div>`;
      }).join('')}</div>`;
  }
  function boiteInvitation(o) {
    const ev = o.ev, inv = ev.invitation, rep = S.invitations[ev.id];
    const conflit = inv.conflit ? trouver(`${inv.conflit}@${ymd(o.jour)}`) : null;
    const prep = inv.prepare && !S.refusees[ev.id] && !rep ? inv.prepare : null;
    const qui = A.who(inv.de);
    let html = `<div class="ag-inv-from">${av(inv.de, 'sm')}<span class="txt"><b>${h(qui.nom)} t'invite</b><small>reçue ${h(inv.recue)} · par ${h(inv.par)}</small></span></div>`;
    if (rep && rep !== 'peut') html += `<p class="ag-inv-done">${ico('check', 'sm')}<span>Tu as répondu <b>${h(REP_DIT[rep])}</b> · parti à ${h(qui.court)} par ${h(inv.par)}.</span></p>`;
    if (conflit) html += `<button class="ag-conflit" type="button" data-go="#agenda/evenement/${h(conflit.cle)}">${ico('alert', 'sm')}<span>En même temps que « ${h(conflit.ev.titre)} » (${h(AG[conflit.ev.agenda].nom)}), ${hm(conflit.deb)} – ${hm(conflit.finMin)}.</span></button>`;
    if (prep) {
      html += `<div class="ag-prep">${A.face(32)}<div class="grow"><div class="ag-prep-t">${ico('sparkle', 'xs')}Mika a préparé ta réponse · elle attend ton accord</div>
        <p><b>${h(REPONSES[prep.reponse])}</b>, avec un mot : « ${h(prep.mot)} »</p><p class="muted">${h(prep.pourquoi)}</p>
        <div class="btns"><button class="btn filled sm" type="button" data-agrepmika="${ev.id}">${ico('send')}Envoyer sa réponse</button><button class="btn text sm" type="button" data-go="#agenda/evenement/${h(o.cle)}/mot">Modifier le mot</button>
          <button class="btn text sm" type="button" data-agrepnon="${ev.id}">Non merci</button></div></div></div>`;
    }
    return `<div class="ag-inv-box">${html}</div>`;
  }
  function vueFiche(cle, extra) {
    const o = trouver(cle);
    if (!o) return { nav: 'agenda', back: routeVue(), html: `${A.top({ title: 'Événement', small: true, back: true, face: false })}<div class="body"><div class="cx-empty">${ico('agenda')}<b>Introuvable</b><p>Cet événement n'existe plus.</p></div></div>`, notes: {} };
    const ev = o.ev, a = AG[ev.agenda], s = sorte(o), [rcls, rlib] = relatif(o);
    const lectureSeule = !a.ecrire || !proprio(a), estMika = ev.agenda === 'mika', autreOrg = ev.org && ev.org !== 'adrien';
    const enProp = s === 'propose';
    const acts = [A.act('sparkle', estMika ? 'Lui en parler' : 'Demander à Mika', `data-agdemander="${h(cle)}"`, 'mk')];
    if (!estMika && !enProp && !lectureSeule && !autreOrg) acts.push(A.act('pen', 'Modifier', `data-go="#agenda/modifier/${h(cle)}"`));
    if (!estMika && !enProp && !lectureSeule) acts.push(A.act('trash', 'Supprimer', `data-go="#agenda/evenement/${h(cle)}/supprimer"`));
    if (!estMika && !enProp) acts.push(A.act('more', 'Plus', 'data-menu="ag-fiche"'));
    const entete = enProp
      ? `<div class="ag-box mk">${A.face(36)}<div class="grow"><div class="ag-box-t">${ico('sparkle', 'xs')}Mika propose de l'ajouter à « ${h(a.nom)} »</div>
          <p>${h(ev.proposition.phrase)} <button class="ag-lien" type="button" data-go="${ev.proposition.conv}">Voir la conversation</button></p>
          <div class="btns end"><button class="btn text sm" type="button" data-agprop="refuse">Refuser</button><button class="btn text sm" type="button" data-go="#agenda/modifier/prop-diner">Modifier</button><button class="btn filled sm" type="button" data-agprop="ajoute">${ico('check')}Ajouter</button></div></div></div>`
      : estMika ? `<div class="ag-box mk">${A.face(36)}<div class="grow"><div class="ag-box-t">${ico('sparkle', 'xs')}${ev.mika.sorte === 'promesse' ? 'Ce qu\'elle t\'a promis' : 'Ce qu\'elle retient de ta vie'}</div>
          <p><b>${h(ev.mika.source)}</b> <button class="ag-lien" type="button" data-go="${ev.mika.conv}">Voir la conversation</button></p><p class="muted">Ses mots, le ${h(ev.mika.quand)} : ${h(ev.mika.dit)}</p>
          ${ev.mika.suite ? `<p class="muted">${h(ev.mika.suite)}</p>` : ''}</div></div>` : '';
    const rappelM = ev.rappel || a.rappel;
    const sait = ev.sait && ev.sait.length ? `<div class="set-h mk">${ico('sparkle')}Ce que Mika en sait</div><div class="set-group mk">${ev.sait.map(([t, d, r]) => `<${r ? `button type="button" data-go="${r}"` : 'div'} class="cx-fait ag-sait"><span class="txt"><p>${h(t)}</p><small>${h(d)}</small></span>${r ? ico('chev-right', 'sm') : ''}</${r ? 'button' : 'div'}>`).join('')}</div>
      <p class="note" style="padding:6px 28px 0">Elle ne le dit qu'à toi.</p>` : '';
    const par = ajouteParMika(o) ? (ev.parMika
      ? `<div class="ag-par">${ico('sparkle', 'sm')}<span><b>Ajouté par Mika</b>, ${ev.parMika.comment === 'seule' ? 'seule' : 'avec ton accord'}, le ${h(ev.parMika.quand)}<small>${h(ev.parMika.phrase)} <button class="ag-lien" type="button" data-go="${ev.parMika.conv}">Voir la conversation</button></small></span></div>`
      : `<div class="ag-par">${ico('sparkle', 'sm')}<span><b>Ajouté par Mika</b>, avec ton accord, aujourd'hui<small>${h(ev.proposition.phrase)} <button class="ag-lien" type="button" data-go="${ev.proposition.conv}">Voir la conversation</button></small></span></div>`) : '';
    const pied = estMika ? `<p class="ag-ro">${ico('lock', 'sm')}<span>C'est sa mémoire, montrée comme un agenda : on ne le modifie pas ici. Dis-le-lui : « c'est fait », « c'est reporté à lundi », « oublie ça ». Elle ne te montre que ce qui te concerne, jamais ce qu'un autre lui a confié.</span></p>`
      : lectureSeule ? `<p class="ag-ro">${ico('lock', 'sm')}<span>${a.groupe === 'partages' ? `${h(A.who(a.de).nom)} partage cet agenda avec toi en lecture : tu le vois, tu n'y changes rien.` : 'Un abonnement est en lecture seule : ni toi ni Mika n\'y écrivez.'}</span></p>`
        : enProp ? '' : `<p class="ag-ro sync">${ico('refresh', 'sm')}<span>Une modification part tout de suite ${h(chez(a))}${a.compte === 'systeme' ? '' : ', puis l\'agenda se relit'}.</span></p>`;
    const rsvp = ev.invitation
      ? `<div class="bottom-actions ag-rsvp"><span class="ag-rsvp-q">Participer ?</span>${Object.entries(REPONSES).map(([k, l]) => `<button class="btn ${S.invitations[ev.id] === k ? 'filled' : 'outlined'} sm" type="button" data-agrep="${ev.id}:${k}">${k === 'oui' ? ico('check') : k === 'non' ? ico('x') : ''}${l}</button>`).join('')}</div>` : '';
    const rows = [
      ev.rec ? ligne('repeat', `<b>${h(recurrence(ev))}</b>`) : '',
      ev.lieu ? ligne('pin', `<b>${h(ev.lieu)}</b><small class="ag-a">Ouvrir dans Carte</small>`, `data-go="#carte" data-snack="La carte cherche « ${h(lieuCourt(ev.lieu))} »"`) : '',
      ev.visio ? ligne('video', `<b class="ag-a">Rejoindre la réunion ${h(ev.visio)}</b>${ev.visioUrl ? `<small class="mono ellipsis">${h(ev.visioUrl)}</small>` : ''}`, `data-snack="Maquette : ouvrirait la réunion dans ${h(ev.visio)}"`) : '',
      ev.desc ? ligne('threads', `<span class="ag-desc">${h(ev.desc)}</span>`) : '',
      ligne('agenda', `<b>${sw(couleur(o), 'xs')} ${h(a.nom)}</b><small>${h(fournisseur(a))}${a.compte ? ' · ' + h(CPT[a.compte].adresse) : ''}</small>`, estMika || a.groupe === 'partages' ? '' : `data-go="${reglages(a)}"`),
      !estMika ? ligne('clock', `<span>${ev.dispo === 'libre' ? 'Disponible' : 'Occupé'} · visibilité par défaut</span>${autreOrg ? `<small>Organisé par ${h(A.who(ev.org).nom)}, qui le modifie</small>` : ''}`) : '',
    ].join('');
    const rappels = estMika || enProp ? '' : `<div class="set-h">Rappels</div><div class="set-group">
        ${ligne('bell', `<span>${h(cap(a.rappelFourn))}</span>`)}
        <button class="ag-f-row mk" type="button" data-go="#agenda/evenement/${h(cle)}/rappel"><span class="ag-f-i">${ico('sparkle')}</span><span class="ag-f-c"><b>${rappelM === 'non' ? 'Mika ne te le rappelle pas' : `Mika te le rappelle ${h(rappelDit(rappelM))}`}</b>
          <small>${ev.rappel ? 'pour cet événement' : `le réglage de « ${h(a.nom)} »`} · dans le chat, ou par une notification</small></span><span class="ag-chg">Changer</span></button></div>`;
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'agenda', back: routeVue(), cls: 'ag-scr',
      html: `${A.top({ title: '', back: true, face: false, actions: acts })}
        <div class="body ag-fiche" data-agfiche="${h(cle)}">${entete}
          <div class="ag-f-t"><span class="ag-f-sq" style="${styleC(o)}"></span><div class="grow"><h1>${marque(o)}${h(ev.titre)}</h1><p>${h(quandDit(o))}</p>
            <p class="ag-f-tags"><span class="tag ${rcls}">${h(rlib)}</span>${s === 'invite' ? '<span class="tag warn">invitation</span>' : ''}${s === 'peut' ? '<span class="tag">tu as dit peut-être</span>' : ''}${enProp ? '<span class="tag mk">pas encore dans ton agenda</span>' : ''}</p></div></div>
          ${ev.invitation ? boiteInvitation(o) : ''}
          <div class="set-group ag-rows">${rows}${participants(o)}</div>
          ${rappels}${sait}${par}${pied}
        </div>${rsvp}`,
      notes: notesFiche(o),
      after() {
        if (extra === 'mot') A.sheets['ag-mot']({ dataset: { agmot: ev.id } });
        if (extra === 'rappel') A.sheets['ag-rappel']({ dataset: { agrappel: cle } });
        if (extra === 'supprimer') A.dialogs['ag-suppr']();
      },
    };
  }
  function notesFiche(o) {
    const ev = o.ev, s = sorte(o);
    const propre = {
      'inv-afterwork': 'Une invitation de Karim : sa réponse préparée (refuser, avec un mot), et le conflit avec ton escalade du jeudi. La barre du bas répond toi-même, comme Google (Accepter · Peut-être · Refuser).',
      'inv-entretien': 'Une invitation de Nadia : Mika a préparé « Accepter », avec un mot. « Envoyer sa réponse » la fait partir par Outlook (DavMail) ; « Modifier le mot » ouvre une feuille.',
      'prop-diner': 'Ce que Mika propose d\'ajouter, pas encore dans ton agenda : hachuré de rose. Ajouter · Modifier · Refuser, et d\'où vient l\'idée (la conversation de 12:50).',
      dentiste: 'Ajouté par Mika, seule : ton tableau le lui permet sur « Mon agenda ». La fiche dit quand et d\'où.',
      'mika-relire': 'L\'agenda de Mika : ce qu\'elle t\'a promis, d\'où ça vient (ses mots, la conversation), en lecture seule. On le corrige en le lui disant ; « Lui en parler » ouvre le chat.',
      'mika-canape': 'L\'agenda de Mika : ce qu\'elle retient de ta vie (« la livraison de ton canapé ») et ce qu\'elle en fera (elle t\'en demandera des nouvelles).',
      'revue-budget': 'Un événement de « Travail » en cours : ce que Mika en sait (son rappel de 13:30, le devis de Lefèvre, avec la conversation), ses rappels.',
      'point-lumen': 'Un événement récurrent : Modifier demandera « Cet événement · Celui-ci et les suivants · Tous ».',
      escalade: 'Un événement récurrent de « Perso » : Modifier et Supprimer demandent lequel.',
      'lea-diner': 'L\'agenda de Léa, partagé avec toi en lecture : ni Modifier ni Supprimer ; ⋮ › « Copier dans mes agendas ».',
    }[ev.id];
    return {
      titre: `Agenda · la fiche d'un événement (proposé)`,
      reprend: [
        'En page, comme Google Agenda sur Android. En haut : ✦ « Demander à Mika » (le chat s\'ouvre sur l\'événement), Modifier, Supprimer, ⋮ (Dupliquer, Partager l\'agenda, ses paramètres).',
        'Le carré de sa couleur, le titre, quand, ce qui reste (« dans 3 jours ») ; puis la récurrence, le lieu (vers l\'écran Carte), la visio, la description, l\'agenda (vers ses paramètres), occupé ou disponible, les participants et leur réponse.',
        'Rappels : celui du fournisseur, puis, en rose, « Mika te le rappelle » (le réglage de l\'agenda, ou le sien), qu\'on change dans une feuille.',
        '« Ce que Mika en sait » : ce qu\'elle a lu ou entendu qui touche l\'événement, d\'où, et la conversation quand il y en a une.',
        propre,
      ].filter(Boolean),
      trancher: [
        s === 'invite' || s === 'peut' ? 'Accepter · Peut-être · Refuser en barre du bas, toujours visible (Google), et la réponse de Mika dans la page : ou sa réponse en premier, dans la barre (« Envoyer sa réponse »), et les trois boutons dans la page ?' : 'Modifier et Supprimer en icônes dans la barre du haut (Google), ou en boutons au pied de la fiche ?',
        '✦ « Demander à Mika » dans la barre du haut (comme une fiche de la Carte) : à sa place ?',
        '« Ce que Mika en sait » après les rappels (ici), ou juste sous le titre ?',
      ],
    };
  }

  // ── Les invitations ───────────────────────────────────────────────────
  function vueInvitations() {
    const l = enAttente();
    const faites = G.evenements.filter((e) => e.invitation && S.invitations[e.id]).map((e) => trouver(e.id));
    const carteInv = (o) => `<article class="ag-invcard"><button class="ag-invcard-h" type="button" data-go="#agenda/evenement/${h(o.cle)}" style="${styleC(o)}"><span class="ag-f-sq"></span>
        <span class="grow"><b>${h(o.ev.titre)}</b><small>${h(cap(jourCourt(o.jour)))} · ${hm(o.deb)} – ${hm(o.finMin)}${o.ev.lieu ? ' · ' + h(lieuCourt(o.ev.lieu)) : ''}</small><small>dans ${h(AG[o.ev.agenda].nom)}</small></span>${ico('chev-right', 'sm')}</button>
        ${boiteInvitation(o)}
        <div class="ag-invcard-rep">${Object.entries(REPONSES).map(([k, lb]) => `<button class="btn outlined sm" type="button" data-agrep="${o.ev.id}:${k}">${k === 'oui' ? ico('check') : k === 'non' ? ico('x') : ''}${lb}</button>`).join('')}</div></article>`;
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'agenda', back: routeVue(), cls: 'ag-scr',
      html: `${A.top({ title: 'Invitations', sub: l.length ? `${l.length} attendent ta réponse` : 'aucune en attente', small: true, back: true, face: false })}
        <div class="body ag-invs">${l.length ? l.map(carteInv).join('') : `<div class="cx-empty">${ico('inbox')}<b>Tout est répondu</b><p>Une invitation reçue par Outlook ou Google arrive ici, avec la réponse que Mika te prépare.</p></div>`}
          ${faites.length ? `<div class="set-h">Déjà répondu</div><div class="set-group">${faites.map((o) => `<button class="li" type="button" data-go="#agenda/evenement/${h(o.cle)}"><span class="lead">${sw(couleur(o), 'lg')}</span><span class="txt"><b>${h(o.ev.titre)}</b><small>${h(REP_DIT[S.invitations[o.ev.id]])} · ${h(jourCourt(o.jour))}, ${hm(o.deb)}</small></span></button>`).join('')}</div>` : ''}
          <p class="note" style="padding:14px 24px 24px">Une invitation arrive par ton agenda (Outlook, Google, CalDAV) et ta réponse repart par lui. Mika prépare une réponse ; elle ne l'envoie jamais sans ton accord.</p></div>`,
      notes: { titre: 'Agenda · Invitations (proposé)',
        reprend: ['Une page : ⋮ › Invitations, ou une ligne de « À décider ». Chaque invitation : quand, où, qui t\'invite et par où, le conflit s\'il y en a un, la réponse que Mika a préparée (rose), puis tes trois boutons.',
          'Répondre la fait passer dans « Déjà répondu » ; un refus disparaît de la grille.'],
        trancher: ['Une page à part, ou seulement « À décider » en tête de l\'Agenda (la page ferait doublon) ?', 'Un compte des invitations sur « Agenda » dans le tiroir (ici, avec la proposition), ou seulement ce que Mika attend de toi ?'] },
    };
  }

  // ── Chercher ──────────────────────────────────────────────────────────
  function resultats(q) {
    const n = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
    const qq = n(q.trim());
    if (!qq) return `<p class="note" style="padding:16px 20px">Un titre, un lieu, une personne : dans les agendas cochés, de septembre à juin.</p>`;
    const vus = {};
    const l = occurrences(lireJ('2026-09-01'), lireJ('2027-07-01')).filter(visible).filter((o) => {
      const ev = o.ev, gens = (ev.p || []).map(([k]) => nomP(k)).join(' ');
      return n(`${ev.titre} ${ev.lieu || ''} ${ev.desc || ''} ${AG[ev.agenda].nom} ${gens}`).includes(qq);
    }).filter((o) => { if (!o.ev.rec) return true; if (ecart(o.jour) < 0) return false; vus[o.ev.id] = (vus[o.ev.id] || 0) + 1; return vus[o.ev.id] <= 3; });
    if (!l.length) return `<div class="cx-empty">${ico('search')}<b>Rien trouvé</b><p>Aucun événement ne correspond à « ${h(q)} » dans tes agendas cochés.</p></div>`;
    return `<div class="list-head">${l.length} résultat${l.length > 1 ? 's' : ''}</div>${l.map((o) => `<div class="ag-res"><span class="ag-res-d"><b>${o.jour.getDate()}</b><small>${MC[o.jour.getMonth()]}${o.jour.getFullYear() !== AUJ.getFullYear() ? ' ' + o.jour.getFullYear() : ''}</small></span>${carte(o)}</div>`).join('')}`;
  }
  let derniereQ = '';
  function vueChercher(q) {
    if (q != null) derniereQ = q;
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'agenda', back: routeVue(), cls: 'ag-scr',
      html: `<div class="search-top">${A.act('back', 'Retour', 'data-back')}<label class="field">${ico('search', 'sm')}<input data-agq value="${h(derniereQ)}" placeholder="Chercher dans tes agendas" aria-label="Chercher dans tes agendas" autocomplete="off"></label></div>
        <div class="body ag-chercher" data-agres>${resultats(derniereQ)}</div>`,
      notes: { titre: 'Agenda · Chercher (proposé)', reprend: ['La loupe de la barre : un titre, un lieu, une description, un participant, un agenda ; dans les agendas cochés, de septembre à juin. Une récurrence n\'apparaît qu\'à ses trois prochaines dates.'],
        trancher: ['Chercher seulement dans ce que le serveur a gardé (90 jours derrière, un an devant), ou demander au fournisseur au-delà ?'] },
      after(root) { const i = root.querySelector('[data-agq]'); if (i && !q) setTimeout(() => i.focus(), 30); },
    };
  }

  // ── Les feuilles : agendas, un agenda, partager, rappel, mot ──────────
  const GROUPES = [['mes', 'Mes agendas'], ['partages', 'Partagés avec moi'], ['abonnements', 'Abonnements'], ['mika', 'L\'agenda de Mika']];
  function ligneAgenda(a) {
    const partage = a.partages.length ? ` · ${ico('users', 'xxs')} ${a.partages.length}` : '';
    return `<div class="ag-cal${a.groupe === 'mika' ? ' mika' : ''}" style="--c:var(--ag-${a.couleur})"><label class="ag-cal-l"><input type="checkbox" data-agcoche="${a.id}"${a.coche ? ' checked' : ''}><span class="ag-cb">${ico('check')}</span>
      <span class="txt"><b>${h(a.nom)}</b><small>${h(fournisseur(a))}${partage}</small></span></label>
      <button class="ibtn" type="button" data-agcal="${a.id}" aria-label="${h(a.nom)} : couleur, partager, paramètres">${ico('more', 'sm')}</button></div>`;
  }
  A.sheets['ag-agendas'] = () => {
    const panne = G.comptes.filter((c) => c.etat[0] !== 'ok');
    A.sheet('Agendas à afficher', `${GROUPES.map(([g, t]) => {
      const l = G.agendas.filter((a) => a.groupe === g && a.visible);
      return l.length ? `<div class="ag-cals-h">${h(t)}</div>${l.map(ligneAgenda).join('')}` : '';
    }).join('')}
      ${panne.map((c) => `<button class="ag-warn" type="button" data-go="#parametres/agendas/${c.id}">${ico('alert', 'sm')}<span><b>${h(c.nom)}</b> à reconnecter · ses agendas ne se montrent plus</span>${ico('chev-right', 'sm')}</button>`).join('')}
      <div class="divider" style="margin:10px 0"></div>
      <button class="li" type="button" data-go="#parametres/agendas/brancher"><span class="lead">${ico('plus')}</span><span class="txt"><b>Brancher un agenda</b><small>Google, Outlook, CalDAV, iCal, ce serveur</small></span></button>
      <button class="li" type="button" data-go="#parametres/agendas"><span class="lead">${ico('settings')}</span><span class="txt"><b>Paramètres des agendas</b></span></button>
      <p class="note" style="padding:6px 24px 8px">Décocher ne change que ce que tu vois ici : Mika s'en sert toujours. Pour qu'elle ne s'en serve plus, masque-le dans Paramètres.</p>`);
  };
  A.sheets['ag-cal'] = (x) => {
    const a = AG[x.dataset.agcal];
    if (!a) return;
    const coul = a.groupe === 'mika'
      ? '<p class="note" style="padding:2px 24px 8px">Son rose, qui ne change pas : il est à elle.</p>'
      : `<div class="ag-swatches">${G.palette.map(([k, l]) => `<button type="button" class="ag-swatch${a.couleur === k ? ' on' : ''}" style="--c:var(--ag-${k})" data-agcoul="${a.id}:${k}" title="${h(l)}" aria-label="${h(l)}">${a.couleur === k ? ico('check') : ''}</button>`).join('')}</div>`;
    A.sheet(`<span class="ag-sht"><button class="ibtn" type="button" data-sheet="ag-agendas" aria-label="Revenir aux agendas">${ico('back', 'sm')}</button>${sw(a.couleur, 'lg')}<span class="ellipsis">${h(a.nom)}</span></span>`, `<p class="note" style="padding:0 24px 6px">${h(fournisseur(a))}${a.compte ? ' · ' + h(CPT[a.compte].adresse) : ''} · ${a.groupe === 'partages' ? `à ${h(A.who(a.de).nom)}` : a.groupe === 'mika' ? 'à elle' : 'à toi'}</p>
      <div class="list-head" style="padding-left:24px">Couleur</div>${coul}
      <button class="li" type="button" data-agseul="${a.id}"><span class="lead">${ico('eye')}</span><span class="txt"><b>Afficher seulement celui-ci</b></span></button>
      ${a.groupe === 'mika' ? '' : `<button class="li" type="button" data-go="#agenda/partager/${a.id}"><span class="lead">${ico('user-plus')}</span><span class="txt"><b>${proprio(a) ? 'Partager' : 'Partager (seul son propriétaire)'}</b>${a.partages.length ? `<small>avec ${h(a.partages.map(([k]) => A.who(k).court).join(' et '))}</small>` : ''}</span></button>`}
      ${G.droits[a.id] ? `<button class="li" type="button" data-go="#outils/droits/${a.id}"><span class="lead">${ico('shield')}</span><span class="txt"><b>Ce que Mika en fait</b><small class="two">${h(resume(a.id))}</small></span></button>` : ''}
      ${proprio(a) || a.groupe === 'mika' ? `<button class="li" type="button" data-go="${a.groupe === 'mika' ? '#parametres/agendas' : reglages(a)}"><span class="lead">${ico('settings')}</span><span class="txt"><b>Paramètres</b></span></button>` : ''}`);
  };
  A.sheets['ag-rappel'] = (x) => {
    const o = trouver(x.dataset.agrappel);
    if (!o) return;
    const cur = o.ev.rappel || AG[o.ev.agenda].rappel;
    A.sheet('Mika te le rappelle', `<p class="note" style="padding:0 24px 8px">« ${h(o.ev.titre)} » · elle te l'écrit dans le chat, ou par une notification si l'app est fermée. Par défaut, le réglage de « ${h(AG[o.ev.agenda].nom)} ».</p>
      ${RAPPELS.map(([k, l]) => `<button class="li${cur === k ? ' sel' : ''}" type="button" data-agrappelv="${h(o.cle)}:${k}"><span class="lead">${ico(k === 'non' ? 'x' : 'bell')}</span><span class="txt"><b>${h(l)}</b></span>${cur === k ? ico('check') : ''}</button>`).join('')}`);
  };
  A.sheets['ag-mot'] = (x) => {
    const ev = EV[x.dataset.agmot], p = ev.invitation.prepare;
    A.sheet(`Répondre à ${h(A.who(ev.invitation.de).nom)}`, `<div style="padding:0 24px 8px"><div class="seg" data-seg data-agmotrep>${Object.entries(REPONSES).map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === p.reponse}">${l}</button>`).join('')}</div></div>
      <div style="padding:10px 24px 4px"><label class="tf"><span>Le mot qui part avec</span><textarea rows="3" data-agmottxt>${h(p.mot)}</textarea></label></div>
      <p class="note" style="padding:4px 24px">Préparé par Mika ; il part par ${h(ev.invitation.par)}, à ${h(A.who(ev.invitation.de).court)} seulement.</p>
      <div class="cx-sheet-btns"><button class="btn text" type="button" data-close>Annuler</button><button class="btn filled" type="button" data-agmotok="${ev.id}">${ico('send')}Envoyer</button></div>`);
  };

  // Partager un agenda : une personne qui a un compte, trois niveaux, les partages en cours.
  let niveauChoisi = 'lire', quiChoisi = null;
  function partageCorps(a) {
    const c = compte(a);
    const avecCompte = Object.entries(D.personnes).filter(([k, p]) => p.compte && k !== 'adrien');
    const sans = Object.entries(D.personnes).filter(([k, p]) => !p.compte && k !== 'adrien' && p.moyens.some((m) => m[0] === 'mail')).slice(0, 2);
    quiChoisi = quiChoisi && avecCompte.some(([k]) => k === quiChoisi) ? quiChoisi : avecCompte[0][0];
    const fourn = c && ['google', 'microsoft', 'caldav'].includes(c.sorte);
    const chezF = c && c.sorte === 'google' ? 'Google' : c && c.sorte === 'caldav' ? 'Outlook' : 'Microsoft';
    const cours = a.partages.length ? a.partages.map(([k, n, depuis]) => `<div class="li ag-part">${av(k, 'sm')}<span class="txt"><b>${h(A.who(k).nom)}</b><small>${h(NIVEAUX[n][0])} · depuis le ${h(depuis)}</small></span>
        <button class="btn text sm" type="button" data-agpniv="${a.id}:${k}">Changer</button><button class="ibtn" type="button" data-agpret="${a.id}:${k}" aria-label="Retirer le partage">${ico('x', 'sm')}</button></div>`).join('')
      : '<p class="note" style="padding:4px 24px">Personne pour l\'instant.</p>';
    return `<p class="note" style="padding:0 24px 6px">${h(fournisseur(a))} · ${h(c ? c.adresse : '')} · à toi</p>
      ${fourn ? `<div class="note box">${ico('info', 'sm')}<span>Ce partage se fait ici, dans Mika : la personne verra « ${h(a.nom)} » dans son Agenda de Mika. Il ne change rien chez ${chezF}${a.chezGoogle ? ` ; le partage Google de « ${h(a.nom)} » (avec ${h(a.chezGoogle.join(' et '))}) se règle dans Google Agenda et ne se voit pas ici` : ''}.</span></div>` : ''}
      <div class="list-head" style="padding-left:24px">Avec qui</div>
      <div class="chips ag-qui" style="padding:0 24px 4px;flex-wrap:wrap">${avecCompte.map(([k, p]) => `<button type="button" class="chip${k === quiChoisi ? ' on' : ''}" data-agpqui="${k}">${av(k, 'xs')}${h(p.nom)}</button>`).join('')}
        ${sans.map(([, p]) => `<span class="chip ag-off" title="Pas de compte sur ce serveur">${h(p.nom)}</span>`).join('')}</div>
      <p class="note" style="padding:2px 24px 0">Seulement une personne qui a un compte sur ce serveur : jamais « tout le monde », jamais un lien public. ${sans.map(([, p]) => p.court).join(' et ')} n'en ont pas.</p>
      <div class="list-head" style="padding-left:24px">Ce que la personne peut</div>
      ${Object.entries(NIVEAUX).map(([k, [l, d]]) => `<button class="li ag-niv${k === niveauChoisi ? ' sel' : ''}" type="button" data-agpniveau="${k}"><span class="lead"><span class="ag-radio${k === niveauChoisi ? ' on' : ''}"></span></span><span class="txt"><b>${h(l)}</b><small class="two">${h(cap(d))}</small></span></button>`).join('')}
      <div style="padding:8px 24px 4px"><button class="btn filled block" type="button" data-agpadd="${a.id}">${ico('user-plus')}Partager avec ${h(A.who(quiChoisi).court)}</button></div>
      <div class="list-head" style="padding-left:24px">Partages en cours · ${a.partages.length}</div>${cours}
      <button class="li" type="button" data-go="#outils/droits/${a.id}"><span class="lead">${ico('shield')}</span><span class="txt"><b>Ce que Mika en fait avec chacun</b><small>Outils › Droits</small></span>${ico('chev-right', 'sm')}</button>`;
  }
  A.sheets['ag-partager'] = (x) => {
    const a = AG[x.dataset.agpartager];
    if (!a) return;
    if (!proprio(a)) {
      A.sheet(`Partager « ${h(a.nom)} »`, `<p class="cx-sheet-p">${a.groupe === 'mika'
        ? 'L\'agenda de Mika ne se partage pas : c\'est ce qu\'elle retient pour toi, et ce qu\'elle retient pour chacun reste à chacun.'
        : `Seule ${h(A.who(a.de).nom)} peut partager son agenda. Elle te l'a ouvert en lecture le ${h(a.depuisPartage)}.`}</p>
        <div class="cx-sheet-btns">${a.groupe === 'partages' ? `<button class="btn text" type="button" data-agmasquer="${a.id}">Ne plus l'afficher</button>` : ''}<button class="btn text" type="button" data-close>Compris</button></div>`);
      return;
    }
    A.sheet(`<span class="ag-sht">${sw(a.couleur, 'lg')}<span class="ellipsis">Partager « ${h(a.nom)} »</span></span>`, `<div data-agpcorps="${a.id}">${partageCorps(a)}</div>`);
  };
  function notesPartage(id) {
    const a = AG[id];
    return { titre: `Agenda · Partager « ${a ? h(a.nom) : ''} » (proposé)`,
      reprend: ['Une feuille par-dessus l\'Agenda (⋮ d\'un agenda › Partager, ou sa page dans Paramètres).',
        'Avec une personne qui a un compte (Léa, Julien) ; les autres sont grisées. Trois niveaux, dits en entier : Lire · Lire et préparer · S\'en servir.',
        'Les partages en cours : changer le niveau, retirer. Puis « Ce que Mika en fait avec chacun » (Outils › Droits).',
        'Pour un agenda Google, la feuille dit que ce partage est dans Mika, et que celui fait chez Google (Famille, avec Maman et Léa) ne se voit pas ici.'],
      trancher: ['Un partage dans Mika n\'est pas un partage chez Google : le dire suffit-il, ou faut-il avertir quand la personne y a déjà accès chez Google ?', 'Les trois niveaux en liste à cocher (ici, lisibles sur un téléphone), ou en boutons segmentés comme le web ?'] };
  }

  // ── Le volet des notifications du téléphone ───────────────────────────
  function volet() {
    const inv = EV['inv-entretien'], repondu = S.invitations['inv-entretien'];
    const prop = S.proposition === 'attend';
    const notif = (o) => `<div class="ag-nt"><button class="ag-nt-tap" type="button" data-go="${o.go}">
      <span class="ag-nt-h"><span class="ag-nt-app">M</span><span>Mika</span><span class="muted">· ${h(o.canal)} · ${h(o.t)}</span><span class="grow"></span>${ico('chev-down', 'xs')}</span>
      <span class="ag-nt-b"><span class="grow"><b>${o.titre}</b><span class="ag-nt-p">${o.texte}</span></span>${o.visage ? A.face(40) : ''}</span></button>
      ${o.actions ? `<div class="ag-nt-a">${o.actions}</div>` : ''}</div>`;
    const tuiles = [['wifi', 'Internet', 'Livebox-7A2C', true], ['moon-z', 'Ne pas déranger', 'désactivé', false], ['locate', 'Position', 'activée', true], ['bolt', 'Économie', 'désactivée', false]];
    document.getElementById('overlay').innerHTML = `<div class="ag-shade" role="dialog" aria-label="Le volet des notifications">
      <div class="ag-sh-top"><b>14:20</b><span>lun. 23 novembre</span><span class="grow"></span><span class="ag-sh-ic">${ico('wifi')}${ico('battery')}<small>78 %</small></span></div>
      <div class="ag-sh-tiles">${tuiles.map(([i, l, s, on]) => `<span class="ag-tile${on ? ' on' : ''}">${ico(i)}<span><b>${l}</b><small>${s}</small></span></span>`).join('')}</div>
      <div class="ag-sh-list">
        ${notif({ canal: 'Rappels d\'agenda', t: '13:30', visage: true, go: '#agenda/evenement/revue-budget', titre: 'Revue du budget avec Marc · 14:00',
          texte: 'dans une demi-heure, dans son bureau. le devis de Lefèvre dépasse de 1 240 €, surtout la main-d\'œuvre. tu connais le dossier par cœur, bon courage',
          actions: `<button class="btn text sm" type="button" data-go="#agenda/evenement/revue-budget">Voir l'événement</button><button class="btn text sm" type="button" data-go="#chat/agenda">Lui répondre</button>` })}
        ${notif({ canal: 'Invitations', t: '09:12', go: '#agenda/evenement/inv-entretien', titre: `${h(A.who('nadia').nom)} t'invite : ${h(inv.titre)}`,
          texte: repondu ? `Tu as répondu ${h(REP_DIT[repondu])} · parti à Nadia par Outlook.` : `Mer. 25 nov., 14:00 – 15:00 · Salle RH. <span class="mk-txt">Mika a préparé : accepter, « ${h(inv.invitation.prepare.mot)} »</span>`,
          actions: repondu ? '' : `<button class="btn text sm" type="button" data-agrepmika="inv-entretien">Envoyer sa réponse</button><button class="btn text sm" type="button" data-agrep="inv-entretien:non">Refuser</button><button class="btn text sm" type="button" data-go="#agenda/evenement/inv-entretien">Ouvrir</button>` })}
        ${prop ? notif({ canal: 'Agenda', t: '12:51', go: '#agenda/evenement/prop-diner', titre: 'Ajouter « Dîner chez Léa » à Perso ?', texte: 'Sam. 28 nov., 20:00 – 23:00 · chez Léa. Elle te le rappellera la veille au soir.',
          actions: '<button class="btn text sm" type="button" data-agprop="ajoute">Ajouter</button><button class="btn text sm" type="button" data-agprop="refuse">Refuser</button>' }) : ''}
      </div>
      <div class="ag-sh-foot"><button class="ag-sh-pill" type="button" data-close data-snack="Maquette : les réglages de notification d'Android, rubrique Mika">Gérer</button><button class="ag-sh-pill" type="button" data-close data-snack="Notifications effacées">Tout effacer</button></div>
      <button class="ag-sh-grip" type="button" data-close aria-label="Fermer le volet"><i></i></button></div>`;
  }
  function notesNotif() {
    return { titre: 'Agenda · la notification (proposé)',
      reprend: ['Le volet du téléphone, tiré du haut : un rappel de Mika (dans sa voix, avec son visage), une invitation avec la réponse qu\'elle a préparée, sa proposition d\'ajout.',
        'Chaque notification a son canal Android (« Rappels d\'agenda », « Invitations », « Agenda »), qu\'on règle ou coupe dans les réglages du téléphone, à part de ses messages.',
        'Ses boutons : « Voir l\'événement » et « Lui répondre » (le chat) ; « Envoyer sa réponse » · « Refuser » · « Ouvrir » ; « Ajouter » · « Refuser ». La toucher ouvre la fiche.'],
      trancher: ['Le rappel : une notification à part (ici), ou seulement son message dans le chat, qui notifie déjà ? Les deux feraient doublon.',
        '« Envoyer sa réponse » depuis le volet, sans ouvrir l\'app : assez sûr pour un accord, ou faut-il ouvrir la fiche d\'abord (comme les accords du chat) ?',
        'Trois canaux (rappels, invitations, propositions) ou un seul « Agenda » ?'] };
  }

  // ── Les menus ─────────────────────────────────────────────────────────
  A.menus.agenda = () => [
    ...VUES.map(([k, l, i]) => ({ ico: i, l, go: k === 'planning' ? '#agenda/planning' : '#agenda/' + k, cls: etat.vue === k ? 'ag-on' : '' })),
    '-',
    { ico: 'eye', l: 'Agendas à afficher', sheet: 'ag-agendas' },
    { ico: 'inbox', l: `Invitations${enAttente().length ? ' · ' + enAttente().length : ''}`, go: '#agenda/invitations' },
    { ico: 'settings', l: 'Paramètres des agendas', go: '#parametres/agendas' },
  ];
  A.menus['ag-fiche'] = () => {
    const el = document.querySelector('[data-agfiche]'), o = el && trouver(el.dataset.agfiche);
    if (!o) return [];
    const a = AG[o.ev.agenda], ro = !a.ecrire || !proprio(a);
    return [{ ico: 'copy', l: ro ? 'Copier dans mes agendas' : 'Dupliquer', go: '#agenda/dupliquer/' + o.cle },
      a.groupe !== 'mika' ? { ico: 'user-plus', l: `Partager « ${a.nom} »`, go: '#agenda/partager/' + a.id } : null,
      proprio(a) ? { ico: 'settings', l: `Paramètres de « ${a.nom} »`, go: reglages(a) } : null].filter(Boolean);
  };
  A.dialogs['ag-suppr'] = () => {
    const el = document.querySelector('[data-agfiche]'), o = el && trouver(el.dataset.agfiche);
    if (!o) return;
    const a = AG[o.ev.agenda];
    if (o.ev.rec) { A.agenda.question(o, 'supprimer'); return; }
    A.dialog('Supprimer l\'événement ?', `<p>« ${h(o.ev.titre)} » (${h(jourCourt(o.jour))}) ${a.compte === 'systeme' ? `est effacé de « ${h(a.nom)} »` : `disparaît aussi ${h(chez(a))}`}.${o.ev.p && o.ev.p.length > 1 ? ' Les participants sont prévenus.' : ''}</p>`,
      `<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-agsupprok="${h(o.cle)}:un" style="color:var(--danger)">Supprimer</button>`);
  };

  // ── Les gestes ─────────────────────────────────────────────────────────
  const ici = () => document.querySelector('#app .scr[data-screen="agenda"]');
  // une feuille ouverte par sa route : la fermer ramène la route à la vue, sinon un rendu la rouvrirait
  const FEUILLE = /^#agenda\/(agendas|partager|notification|tiroir|mois-deplie|evenement\/[^/]+\/(mot|rappel|supprimer))(\/|$)/;
  function sansFeuille() {
    if (!FEUILLE.test(location.hash)) return;
    const m = location.hash.match(/^#agenda\/evenement\/([^/]+)\//);
    history.replaceState(null, '', m ? '#agenda/evenement/' + m[1] : routeVue());
  }
  function apresReponse(txt) {
    const volet0 = !!document.querySelector('#overlay .ag-shade');
    if (volet0) { volet(); A.snack(txt); return; }
    A.closeAll();
    sansFeuille();
    A.render();
    A.snack(txt);
  }
  function demander(o) {
    const t = o.ev.agenda === 'mika' ? `à propos de « ${o.ev.titre.charAt(0).toLowerCase() + o.ev.titre.slice(1)} » : ` : `à propos de « ${o.ev.titre} » (${jourCourt(o.jour)}${o.journee ? '' : ' à ' + hm(o.deb)}) : `;
    A.go('#chat');
    setTimeout(() => { const i = document.querySelector('#app [data-input]'); if (i) { i.value = t; i.dispatchEvent(new Event('input')); } }, 60);
    A.snack('La question t\'attend dans le champ du chat');
  }
  document.addEventListener('click', (e) => {
    const t = e.target;
    let x;
    if (t.closest('[data-close]')) { sansFeuille(); return; }
    if ((x = t.closest('[data-agmm]'))) { etat.mm = !etat.mm; etat.mmMois = null; if (!etat.mm) sansFeuille(); peindre(); return; }
    if ((x = t.closest('[data-agmmpas]'))) { moisMini(+x.dataset.agmmpas); return; }
    if ((x = t.closest('[data-agjour]'))) { etat.date = lireJ(x.dataset.agjour); etat.mm = false; etat.mmMois = null; sansFeuille(); peindre(); return; }
    if ((x = t.closest('[data-agauj]'))) { etat.date = AUJ; etat.mmMois = null; etat.sens = 0; peindre(); A.snack(`Aujourd'hui, ${jourDit(AUJ)}`); return; }
    if ((x = t.closest('[data-agpas]'))) { deplacer(+x.dataset.agpas); etat.sens = 0; peindre(); const s = ici() && ici().querySelector('[data-agscroll]'); if (s) s.scrollTop = 0; return; }
    if ((x = t.closest('[data-agjourvue]'))) { etat.date = lireJ(x.dataset.agjourvue); etat.mm = false; A.go('#agenda/jour'); return; }
    if ((x = t.closest('[data-agdecide]'))) { const o = x.getAttribute('aria-expanded') === 'true'; etat.decide = !o; peindre(); return; }
    if ((x = t.closest('[data-agnouveau]'))) { A.agenda.nouveau = { jour: ymd(etat.date) }; A.go('#agenda/nouveau'); return; }
    if ((x = t.closest('[data-agcol]')) && t === x) {
      const r = x.getBoundingClientRect();
      const deb = Math.max(0, Math.min(1410, Math.floor((e.clientY - r.top) / HH * 2) * 30));
      A.agenda.nouveau = { jour: x.dataset.agcol, deb };
      A.go('#agenda/nouveau');
      return;
    }
    if ((x = t.closest('[data-agprop]'))) {
      S.proposition = x.dataset.agprop;
      const ok = S.proposition === 'ajoute';
      if (!ok && /prop-diner/.test(location.hash) && !document.querySelector('.ag-shade')) { A.closeAll(); history.replaceState(null, '', routeVue()); A.render(); A.snack('Refusé : rien n\'est ajouté. Elle ne te le reproposera pas.'); return; }
      apresReponse(ok ? 'Ajouté à « Perso » : parti chez Google. Elle te le rappellera la veille au soir.' : 'Refusé : rien n\'est ajouté. Elle ne te le reproposera pas.');
      return;
    }
    if ((x = t.closest('[data-agrep]'))) {
      const [id, r] = x.dataset.agrep.split(':');
      S.invitations[id] = r;
      apresReponse(`Répondu « ${REP_DIT[r]} » à ${A.who(EV[id].invitation.de).court} : parti par ${EV[id].invitation.par}.`);
      return;
    }
    if ((x = t.closest('[data-agrepmika]'))) {
      const ev = EV[x.dataset.agrepmika], p = ev.invitation.prepare;
      S.invitations[ev.id] = p.reponse;
      apresReponse(`Sa réponse est partie à ${A.who(ev.invitation.de).court} : ${REP_DIT[p.reponse]}, « ${p.mot} »`);
      return;
    }
    if ((x = t.closest('[data-agrepnon]'))) { S.refusees[x.dataset.agrepnon] = true; A.render(); A.snack('Elle n\'enverra pas sa réponse : réponds toi-même quand tu veux.'); return; }
    if ((x = t.closest('[data-agmotok]'))) {
      const ev = EV[x.dataset.agmotok];
      const r = (document.querySelector('[data-agmotrep] [aria-pressed="true"]') || {}).dataset?.v || ev.invitation.prepare.reponse;
      S.invitations[ev.id] = r;
      apresReponse(`Parti à ${A.who(ev.invitation.de).court} : ${REP_DIT[r]}, avec ton mot.`);
      return;
    }
    if ((x = t.closest('[data-agdemander]'))) { const o = trouver(x.dataset.agdemander); if (o) demander(o); return; }
    if ((x = t.closest('[data-agrappelv]'))) {
      const [cle, k] = x.dataset.agrappelv.split(':');
      const o = trouver(cle);
      if (o) o.ev.rappel = k;
      A.closeAll(); sansFeuille(); A.render();
      A.snack(k === 'non' ? 'Elle ne te le rappellera pas.' : `Elle te le rappellera ${rappelDit(k)}.`);
      return;
    }
    if ((x = t.closest('[data-agsupprok]'))) {
      const [cle, q] = x.dataset.agsupprok.split(':');
      const o = trouver(cle), a = AG[o.ev.agenda];
      if (q === 'un' || !o.ev.rec) S.supprimes[o.cle] = true; else S.supprimes[o.ev.id] = true;
      A.closeAll();
      location.replace(routeVue());
      A.snack(`Supprimé de « ${a.nom} »${a.compte === 'systeme' ? '' : ` : effacé ${chez(a)} aussi`}.`);
      return;
    }
    if ((x = t.closest('[data-agcal]'))) { A.sheets['ag-cal'](x); return; }
    if ((x = t.closest('[data-agcoul]'))) { const [id, k] = x.dataset.agcoul.split(':'); AG[id].couleur = k; A.sheets['ag-cal']({ dataset: { agcal: id } }); peindre(); return; }
    if ((x = t.closest('[data-agseul]'))) { G.agendas.forEach((a) => { a.coche = a.id === x.dataset.agseul; }); A.closeAll(); sansFeuille(); peindre(); A.snack(`Seulement « ${AG[x.dataset.agseul].nom} »`); return; }
    if ((x = t.closest('[data-agmasquer]'))) { const a = AG[x.dataset.agmasquer]; a.visible = false; A.closeAll(); sansFeuille(); A.render(); A.snack(`« ${a.nom} » ne s'affiche plus. ${A.who(a.de).court} peut toujours retirer son partage.`); return; }
    // le partage
    const corpsP = () => document.querySelector('[data-agpcorps]');
    const repeindreP = () => { const c = corpsP(); if (c) c.innerHTML = partageCorps(AG[c.dataset.agpcorps]); };
    if ((x = t.closest('[data-agpqui]'))) { quiChoisi = x.dataset.agpqui; repeindreP(); return; }
    if ((x = t.closest('[data-agpniveau]'))) { niveauChoisi = x.dataset.agpniveau; repeindreP(); return; }
    if ((x = t.closest('[data-agpadd]'))) {
      const a = AG[x.dataset.agpadd], deja = a.partages.find((p) => p[0] === quiChoisi);
      if (deja) deja[1] = niveauChoisi; else a.partages.push([quiChoisi, niveauChoisi, '23 novembre']);
      repeindreP();
      A.snack(`${A.who(quiChoisi).court} voit « ${a.nom} » dans son Agenda : ${NIVEAUX[niveauChoisi][0].toLowerCase()}.`);
      return;
    }
    if ((x = t.closest('[data-agpniv]'))) {
      const [id, k] = x.dataset.agpniv.split(':'), p = AG[id].partages.find((y) => y[0] === k);
      const ordre = Object.keys(NIVEAUX);
      p[1] = ordre[(ordre.indexOf(p[1]) + 1) % ordre.length];
      repeindreP();
      A.snack(`${A.who(k).court} : ${NIVEAUX[p[1]][0].toLowerCase()}.`);
      return;
    }
    if ((x = t.closest('[data-agpret]'))) {
      const [id, k] = x.dataset.agpret.split(':');
      AG[id].partages = AG[id].partages.filter((p) => p[0] !== k);
      repeindreP();
      A.snack(`Partage retiré : ${A.who(k).court} ne voit plus « ${AG[id].nom} ».`);
    }
  });
  document.addEventListener('change', (e) => {
    const c = e.target.closest('[data-agcoche]');
    if (!c) return;
    AG[c.dataset.agcoche].coche = c.checked;
    peindre();
  });
  document.addEventListener('input', (e) => {
    if (!e.target.matches('[data-agq]')) return;
    derniereQ = e.target.value;
    const r = document.querySelector('[data-agres]');
    if (r) r.innerHTML = resultats(derniereQ);
  });

  // ── Le tiroir et Plus : la rubrique Agenda ────────────────────────────
  function poseTiroir() {
    const d = document.querySelector('#overlay .drawer');
    if (!d || d.querySelector('[data-go="#agenda"]')) return;
    const teams = d.querySelector('.dr-item[data-go="#teams"]');
    const n = aDecide();
    if (teams) teams.insertAdjacentHTML('afterend', `<button class="dr-item${A.state.nav === 'agenda' ? ' on' : ''}" type="button" data-go="#agenda">${ico('agenda')}Agenda${n ? `<span class="cnt-pill">${n}</span>` : ''}</button>`);
  }
  function posePlus() {
    const scr = document.querySelector('#app .scr[data-screen="plus"]');
    const tel = scr && scr.querySelector('.li[data-go="#telephone"]');
    if (!tel || scr.querySelector('.li[data-go="#agenda"]')) return;
    const n = aDecide();
    tel.insertAdjacentHTML('beforebegin', `<button class="li" type="button" data-go="#agenda"><span class="lead box">${ico('agenda')}</span><span class="txt"><b>Agenda</b><small>tes agendas, tes invitations</small></span>${n ? `<span class="cnt-pill">${n}</span>` : ''}</button>`);
  }
  addEventListener('DOMContentLoaded', () => {
    new MutationObserver(poseTiroir).observe(document.getElementById('overlay'), { childList: true });
    new MutationObserver(posePlus).observe(document.getElementById('app'), { childList: true });
    poseTiroir();
    posePlus();
  });

  A.ecran('agenda', (args) => {
    const [a, b, c] = args;
    if (a === 'evenement' && b) return vueFiche(b, c);
    if (a === 'invitations') return vueInvitations();
    if (a === 'chercher') return vueChercher(b);
    if (['nouveau', 'modifier', 'dupliquer'].includes(a) && A.agenda.formulaire) return A.agenda.formulaire(a, b, c);
    return vueAgenda(args);
  });

  A.index('Agenda (proposé)', [['Planning', '#agenda'], ['Jour', '#agenda/jour'], ['3 jours', '#agenda/3jours'], ['Semaine', '#agenda/semaine'], ['Mois', '#agenda/mois'],
    ['Mois déplié', '#agenda/mois-deplie'], ['Agendas à afficher', '#agenda/agendas'], ['Un agenda', '#agenda/agendas/perso'], ['Tiroir', '#agenda/tiroir'], ['Chercher', '#agenda/chercher/léa'],
    ['Invitations', '#agenda/invitations'], ['Fiche · en cours', '#agenda/evenement/revue-budget'], ['Fiche · invitation', '#agenda/evenement/inv-afterwork'],
    ['Fiche · invitation de Nadia', '#agenda/evenement/inv-entretien'], ['Modifier le mot', '#agenda/evenement/inv-entretien/mot'],
    ['Fiche · proposition', '#agenda/evenement/prop-diner'], ['Fiche · ajouté par Mika', '#agenda/evenement/dentiste'], ['Fiche · agenda de Mika', '#agenda/evenement/mika-relire'],
    ['Fiche · récurrent', '#agenda/evenement/point-lumen@2026-11-23'], ['Fiche · Léa', '#agenda/evenement/lea-diner'], ['Son rappel', '#agenda/evenement/revue-budget/rappel'],
    ['Supprimer', '#agenda/evenement/dentiste/supprimer'], ['Nouveau', '#agenda/nouveau'], ['Modifier', '#agenda/modifier/revue-budget'],
    ['Modifier un récurrent', '#agenda/modifier/escalade@2026-11-26'], ['… la question', '#agenda/modifier/escalade@2026-11-26/question'], ['Modifier la proposition', '#agenda/modifier/prop-diner'],
    ['Partager Perso', '#agenda/partager/perso'], ['Partager Famille', '#agenda/partager/famille'], ['Partager l\'agenda de Léa', '#agenda/partager/lea'], ['Notification', '#agenda/notification']]);

  /* Ce que les fichiers posés par-dessus (le formulaire, Paramètres, Outils, le chat) empruntent. */
  A.agenda = { G, S, AG, EV, CPT, NIVEAUX, RAPPELS, REPONSES, rappelDit, fournisseur, chez, proprio, ecrivables, sw, trouver, occurrences, visible, sorte, couleur,
    jourDit, jourCourt, hm, cap, lireJ, ymd, plus, min, recurrence, resume, reglages, routeVue, avP, nomP, grilleMois, AUJ, MAINTENANT, MOIS, JOURS, num, etat, nouveau: null };
})();
