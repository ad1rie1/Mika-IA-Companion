/* Projets, seconde maquette (output/chaines-de-travail/web/MAQUETTE-V2.md, « Retours du propriétaire ») : un atelier
   en trois zones sur toute la largeur — la liste, le contenu découpé en volets, un panneau latéral.
   « À faire » et « Projets », puis la fiche d'un projet en onglets : Vue d'ensemble, Objectifs, Tickets, Code,
   Documentation, Activité, Dépendances (et Listes quand le projet en a). Chaque vue a son adresse (#projets/…).
   Les objectifs se lisent aussi en diagramme (projets2-diagramme.js) : leur avancement, ou leur place dans le temps.
   Ce fichier porte le socle (aides, trois zones, formulaires, panneau qui s'ouvre, routes), « À faire », la grille des
   projets, le cadre de la fiche et la Vue d'ensemble ; projets2-travail.js (Objectifs, Tickets, régler le projet),
   projets2-code.js, projets2-doc.js et projets2-suite.js ajoutent les autres onglets à PJ2.onglets.
   Tout se gère ici : ce qu'on voit se modifie là où on le voit. Les gestes modifient les données en mémoire. */
(function () {
  'use strict';
  const { h, ico, av } = M;
  const P = window.MIKA_PROJETS2;
  const PJ = window.PJ2 = { P, onglets: {}, actes: {}, saisies: {}, formes: {}, parts: {}, S: { filtre: 0, of: 'tous', tf: 'ouverts', tq: '', infos: false } };
  const S = PJ.S;

  /* Les icônes que le cadre n'a pas : branche, commit, pull request, fusion, issue, objectif, ticket, colonnes… */
  document.body.insertAdjacentHTML('afterbegin', `<svg class="sprite" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
    <symbol id="i-p2-branch" viewBox="0 0 24 24"><path d="M6.5 4v10.5"/><circle cx="17.5" cy="6.5" r="2.5"/><circle cx="6.5" cy="17.5" r="2.5"/><path d="M17.5 9a8.5 8.5 0 0 1-8.5 8.5"/></symbol>
    <symbol id="i-p2-commit" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.5"/><path d="M3 12h5.5M15.5 12H21"/></symbol>
    <symbol id="i-p2-pr" viewBox="0 0 24 24"><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/><path d="M6.5 9v6M17.5 15v-5a3.5 3.5 0 0 0-3.5-3.5h-2.5M13.5 4 11 6.5 13.5 9"/></symbol>
    <symbol id="i-p2-merge" viewBox="0 0 24 24"><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/><path d="M6.5 9v11.5M6.5 9a6.5 6.5 0 0 0 6.5 6.5h2"/></symbol>
    <symbol id="i-p2-issue" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.2"/></symbol>
    <symbol id="i-p2-target" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12h.01"/></symbol>
    <symbol id="i-p2-ticket" viewBox="0 0 24 24"><path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h13A1.5 1.5 0 0 1 20 8.5v2a1.6 1.6 0 0 0 0 3v2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 15.5v-2a1.6 1.6 0 0 0 0-3ZM14.5 9.5v1M14.5 13.5v1"/></symbol>
    <symbol id="i-p2-board" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="5" height="15" rx="1.2"/><rect x="9.5" y="4.5" width="5" height="9.5" rx="1.2"/><rect x="15.5" y="4.5" width="5" height="12.5" rx="1.2"/></symbol>
    <symbol id="i-p2-stop" viewBox="0 0 24 24"><path d="M8.5 3.5h7l5 5v7l-5 5h-7l-5-5v-7Z"/><path d="M12 8v5M12 16h.01"/></symbol>
    <symbol id="i-p2-question" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 1 1 3.7 2.2c-.8.5-1.3 1-1.3 1.9M12 16.8h.01"/></symbol>
    <symbol id="i-p2-plan" viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="m3.5 6.3 1.2 1.2 2-2.2M3.5 11.8l1.2 1.2 2-2.2"/><circle cx="5" cy="17.5" r="1.3"/></symbol>
    <symbol id="i-p2-table" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M3.5 10h17M3.5 14.5h17M9.5 5v14M15 5v14"/></symbol>
    <symbol id="i-p2-unifie" viewBox="0 0 24 24"><rect x="4" y="4.5" width="16" height="15" rx="2"/><path d="M7.5 9h9M7.5 12h9M7.5 15h6"/></symbol>
    <symbol id="i-p2-cote" viewBox="0 0 24 24"><rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M12 4.5v15M6.5 9h3M6.5 12h3M14.5 9h3M14.5 12h3M14.5 15h2"/></symbol>
    <symbol id="i-p2-schema" viewBox="0 0 24 24"><rect x="9" y="9" width="6" height="6" rx="1.5"/><circle cx="4.5" cy="6" r="2"/><circle cx="4.5" cy="18" r="2"/><circle cx="19.5" cy="12" r="2"/><path d="M6.3 7 9 10M6.3 17 9 14M15 12h2.5"/></symbol>
  </svg>`);

  /* ── Le temps : la maquette se passe le mercredi 4 novembre 2026 à 14:20 ── */
  const JOURS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
  const MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  const COURTS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const date = (ago) => new Date(P.T - ago * 60000);
  const minuit = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  PJ.ecart = (ago) => Math.round((minuit(new Date(P.T)) - minuit(date(ago))) / 86400000);
  PJ.heure = (ago) => { const d = date(ago); return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };
  PJ.jour = (ago) => { const j = PJ.ecart(ago), d = date(ago); return j === 0 ? 'Aujourd\'hui' : j === 1 ? 'Hier' : `${JOURS[d.getDay()]} ${d.getDate()} ${MOIS[d.getMonth()]}`; };
  PJ.quand = (ago) => {
    if (ago == null) return '';
    if (ago < 1) return 'à l\'instant';
    if (ago < 60) return `il y a ${ago} min`;
    const j = PJ.ecart(ago), d = date(ago);
    return j === 0 ? `il y a ${Math.floor(ago / 60)} h` : j === 1 ? 'hier' : j < 7 ? JOURS[d.getDay()] : `${d.getDate()} ${COURTS[d.getMonth()]}`;
  };
  PJ.moment = (ago) => (ago < 1 ? 'à l\'instant' : `${PJ.jour(ago).toLowerCase()} à ${PJ.heure(ago)}`);

  /* ── Les aides ───────────────────────────────────────────────────── */
  PJ.route = (...parts) => '#projets/' + parts.filter((x) => x != null && x !== '').join('/');
  PJ.fiche = (p, ...parts) => PJ.route('projets', p.id, ...parts);
  PJ.proj = (id) => P.projets.find((x) => String(x.id) === String(id));
  PJ.st = (ton, lib, titre) => `<span class="p2-st ${ton}"${titre ? ` title="${h(titre)}"` : ''}>${ton === 'out' ? ico('external', 'xs') : ''}${h(lib)}</span>`;
  PJ.tuile = (icone, ton) => `<span class="p2-tile ${ton || ''}">${ico(icone)}</span>`;
  PJ.vide = (icone, titre, texte, plus) => `<div class="empty">${ico(icone)}<b>${h(titre)}</b><p>${h(texte)}</p>${plus || ''}</div>`;
  PJ.code = (s) => h(s).replace(/`([^`]+)`/g, '<code>$1</code>');
  PJ.pluriel = (n, un, des) => `${n} ${n > 1 ? des : un}`;
  PJ.voir = (p) => p.droits === 'voir';
  /* Qui : « mika », la clé d'une personne de la maquette, ou { nom, dehors } pour quelqu'un que personne ne connaît. */
  PJ.qui = (par) => {
    if (par === 'mika') return { nom: 'Mika', av: (t) => av('mika', t) };
    if (par && par.dehors) return { nom: par.nom, dehors: true, av: (t) => `<span class="av ${t || ''} p2-av-out" title="Inconnu">${ico('user', 'xs')}</span>` };
    return { nom: par === 'adrien' ? 'toi' : M.who(par).nom, av: (t) => av(par, t) };
  };
  /* Un texte venu d'ailleurs : cité tel quel, échappé, dans sa présentation à lui (un liseré hachuré, jamais une bulle). */
  PJ.parts.dehors = (source, texte, mono) => `<figure class="p2-out"><figcaption>${ico('external', 'xs')}Venu d'ailleurs · ${h(source)}<span>cité tel quel</span></figcaption>
    ${mono ? `<pre>${h(texte)}</pre>` : `<blockquote>${h(texte)}</blockquote>`}</figure>`;
  /* Une barre en segments : un segment par chose, à la couleur de son état. */
  PJ.barre = (tons) => `<span class="p2-seg" role="img" aria-label="${tons.filter((x) => x === 'done').length} sur ${tons.length}">${tons.map((x) => `<i class="${x}"></i>`).join('')}</span>`;
  /* L'objet choisi : celui de l'adresse ; sinon le premier, sauf sur un téléphone où l'on reste sur la liste. */
  PJ.choisi = (liste, cle, voulu) => liste.find((x) => String(cle(x)) === String(voulu)) || (M.mobile() ? null : liste[0]) || null;
  PJ.redessiner = () => M.rafraichir();

  /* ── Les trois zones : la liste, le contenu en volets, le panneau latéral ──
     o.liste (sans elle : deux zones), o.tete (l'en-tête du détail), o.volets [[clé, libellé, compte]], o.actif, o.lien(clé),
     o.corps (le volet ouvert ; o.plein : sans marge, pour un diff, un fichier, un tableau), o.pied (ce qui reste en bas),
     o.cote (le panneau : sur un téléphone, le volet « Infos »), o.ouvert et o.retour pour le téléphone. */
  PJ.trio = (o) => {
    const vs = o.volets || [], infos = S.infos && !!o.cote;
    const nav = vs.length ? `<nav class="p2-volets${vs.length > 1 ? '' : ' seul'}" aria-label="Volets">${vs.map(([k, lib, n]) =>
      `<a href="${o.lien(k)}" data-p2="volet" data-va="1"${k === o.actif && !infos ? ' aria-current="page"' : ''}>${lib}${n != null ? `<span class="cnt">${n}</span>` : ''}</a>`).join('')}
      ${o.cote ? `<button type="button" class="p2-v-infos" data-p2="infos"${infos ? ' aria-current="page"' : ''}>Infos</button>` : ''}${o.outils ? `<span class="p2-volets-side">${o.outils}</span>` : ''}</nav>` : '';
    const detail = o.vide || `${o.retour ? `<a class="p2-back mobile-back" href="${o.retour[0]}">${ico('chev-left', 'sm')}${h(o.retour[1])}</a>` : ''}${o.tete || ''}
      <div class="p2-dz${infos ? ' infos' : ''}${o.cote ? '' : ' sans-cote'}"><div class="p2-main">${nav}<div class="pane-scroll p2-vbody" data-scroll="${h(o.scroll || 'detail')}">${o.plein ? o.corps : `<article class="p2-c">${o.corps}</article>`}</div>${o.pied || ''}</div>
        ${o.cote ? `<aside class="p2-side pane-scroll" data-scroll="${h(o.scroll || 'detail')}-cote" aria-label="Infos">${o.cote}</aside>` : ''}</div>`;
    return `<div class="split p2-split${o.liste == null ? ' sans-liste' : ''}${o.ouvert ? ' lire' : ''}${o.cls ? ' ' + o.cls : ''}">
      ${o.liste == null ? '' : `<section class="pane p2-list">${o.liste}</section>`}<section class="pane p2-detail">${detail}</section></div>`;
  };
  /* Le panneau latéral : des sections à filets (jamais un cadre dans un cadre), des propriétés, des choses liées avec leur état. */
  PJ.sc = (titre, corps, plus) => (corps ? `<section class="p2-sc">${titre ? `<h3>${h(titre)}${plus || ''}</h3>` : ''}${corps}</section>` : '');
  PJ.props = (rangs) => `<dl class="p2-props">${rangs.filter(Boolean).map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  PJ.lie = (href, icone, ton, titre, sous, etat) => `<a class="p2-lie" href="${href}">${PJ.tuile(icone, ton)}<span><b>${h(titre)}</b>${sous ? `<small>${sous}</small>` : ''}</span>${etat || ico('chev-right', 'sm')}</a>`;
  PJ.parts.entete = (o) => `<header class="p2-dh">${o.tuile || ''}<div class="p2-dh-main">${o.sur ? `<span class="p2-over">${o.sur}</span>` : ''}<h2>${o.num ? `<span class="p2-num">${h(o.num)}</span>` : ''}${h(o.titre)}</h2>
    ${o.meta ? `<div class="p2-meta">${o.meta}</div>` : ''}</div>${o.droite ? `<div class="p2-dh-side">${o.droite}</div>` : ''}</header>`;

  /* ── Les formulaires : dans la zone de contenu (PJ.forme) ou dans un panneau qui s'ouvre à droite (PJ.tiroir) ──
     Un formulaire nomme sa suite (PJ.formes[nom](valeurs, données, formulaire)) ; elle rend false pour le garder ouvert. */
  const C = PJ.champs = {
    texte: (nom, lib, val, o = {}) => `<label class="field"><span>${h(lib)}</span><input name="${nom}" value="${h(val == null ? '' : val)}"${o.ex ? ` placeholder="${h(o.ex)}"` : ''}${o.requis ? ' required' : ''}${o.type ? ` type="${o.type}"` : ''}>${o.aide ? `<small>${h(o.aide)}</small>` : ''}</label>`,
    long: (nom, lib, val, o = {}) => `<label class="field"><span>${h(lib)}</span><textarea name="${nom}" rows="${o.rangs || 4}"${o.ex ? ` placeholder="${h(o.ex)}"` : ''}${o.requis ? ' required' : ''}${o.mono ? ' class="p2-mono"' : ''}>${h(val || '')}</textarea>${o.aide ? `<small>${h(o.aide)}</small>` : ''}</label>`,
    choix: (nom, lib, val, options) => `<label class="field"><span>${h(lib)}</span><select name="${nom}">${options.map((x) => { const [k, l] = Array.isArray(x) ? x : [x, x];
      return `<option value="${h(k)}"${String(k) === String(val) ? ' selected' : ''}>${h(l)}</option>`; }).join('')}</select></label>`,
    cartes: (nom, lib, val, options) => `<fieldset class="p2-cards"><legend>${h(lib)}</legend><div>${options.map(([k, l, sous]) =>
      `<label><input type="radio" name="${nom}" value="${h(k)}"${k === val ? ' checked' : ''}><span><b>${h(l)}</b>${sous ? `<small>${h(sous)}</small>` : ''}</span></label>`).join('')}</div></fieldset>`,
    coche: (nom, lib, on, sous, valeur) => `<label class="p2-check"><input type="checkbox" name="${nom}"${valeur ? ` value="${h(valeur)}"` : ''}${on ? ' checked' : ''}><span><b>${h(lib)}</b>${sous ? `<small>${h(sous)}</small>` : ''}</span></label>`,
    groupe: (lib, corps, aide) => `<fieldset class="p2-group"><legend>${h(lib)}</legend>${aide ? `<p>${h(aide)}</p>` : ''}${corps}</fieldset>`,
    deux: (...champs) => `<div class="p2-two">${champs.join('')}</div>`,
  };
  const donnees = (d) => Object.entries(d || {}).map(([k, v]) => `data-${k}="${h(v)}"`).join(' ');
  PJ.forme = (o) => `<form class="p2-form" data-p2-form="${o.forme}" ${donnees(o.data)}><header class="p2-form-h"><h3>${h(o.titre)}</h3>${o.sous ? `<p>${h(o.sous)}</p>` : ''}</header>${o.corps}
    <footer class="p2-form-foot"><a class="btn" href="${o.annuler}">Annuler</a><button class="btn primary" type="submit">${ico('check', 'sm')}${h(o.bouton || 'Enregistrer')}</button></footer></form>`;
  PJ.fermerTiroir = () => { const r = document.getElementById('p2-drawer-root'); if (r) r.innerHTML = ''; };
  PJ.tiroir = (o) => {
    let r = document.getElementById('p2-drawer-root');
    if (!r) { r = document.createElement('div'); r.id = 'p2-drawer-root'; document.body.appendChild(r); }
    r.innerHTML = `<div class="p2-drawer-scrim" data-p2="tiroirFermer"></div><aside class="p2-drawer" role="dialog" aria-label="${h(o.titre)}"><header><div><h2>${h(o.titre)}</h2>${o.sous ? `<p>${h(o.sous)}</p>` : ''}</div>
      <button class="btn icon ghost" type="button" data-p2="tiroirFermer" title="Fermer">${ico('x')}</button></header>
      <form data-p2-form="${o.forme}" ${donnees(o.data)}><div class="p2-drawer-body">${o.corps}</div>
        <footer><button class="btn" type="button" data-p2="tiroirFermer">Annuler</button><button class="btn primary" type="submit">${h(o.bouton || 'Enregistrer')}</button></footer></form></aside>`;
    const premier = r.querySelector('input:not([type=radio]):not([type=checkbox]), textarea'); if (premier) premier.focus();
  };
  PJ.actes.tiroirFermer = () => PJ.fermerTiroir();
  /* Une question posée dans une fenêtre : un champ, un bouton, et la suite. */
  PJ.demander = (o) => {
    PJ._alors = o.alors;
    M.modal({ titre: o.titre, taille: 'narrow', corps: `<div class="stack">${o.avant || ''}<label class="field"><span>${h(o.label)}</span>
      ${o.court ? `<input data-p2-rep value="${h(o.valeur || '')}" placeholder="${h(o.exemple || '')}">` : `<textarea data-p2-rep rows="4" placeholder="${h(o.exemple || '')}">${h(o.valeur || '')}</textarea>`}</label>${o.apres || ''}</div>`,
      pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn ${o.danger ? 'danger' : 'primary'}" type="button" data-p2="demanderOk"${o.libre ? ' data-libre="1"' : ''}>${h(o.bouton)}</button>` });
  };
  PJ.actes.demanderOk = (d) => {
    const champ = document.querySelector('#modal-root [data-p2-rep]'), texte = champ ? champ.value.trim() : '';
    if (!texte && !d.libre) { champ.focus(); champ.classList.add('p2-manque'); return; }
    const alors = PJ._alors; M.fermerModal(); if (alors) alors(texte);
  };
  PJ.confirmer = (o) => {
    PJ._alors = o.alors;
    M.modal({ titre: o.titre, taille: 'narrow', corps: o.corps, pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>
      <button class="btn ${o.danger ? 'danger' : 'primary'}" type="button" data-p2="confirmerOk">${o.ico ? ico(o.ico, 'sm') : ''}${h(o.bouton)}</button>` });
  };
  /* La suite lit la fenêtre avant qu'elle se ferme ; elle rend `false` pour la garder ouverte (un champ manque). */
  PJ.actes.confirmerOk = () => { const alors = PJ._alors, racine = document.querySelector('#modal-root'); if (alors && alors(racine) === false) return; M.fermerModal(); };

  /* ── Ce que les données disent d'un projet ───────────────────────── */
  PJ.etatProjet = (p) => ({ actif: ['work', 'actif'], plan: ['you', 'plan à valider'], pause: ['wait', 'en pause'], cadrage: ['work', 'en cadrage'], archive: ['wait', 'archivé'] }[p.etat]);
  PJ.etatObjectif = (o) => ({ en_cours: ['work', 'en cours'], a_venir: ['wait', 'à venir'], fait: ['done', 'terminé'] }[o.etat]);
  PJ.etatJalon = (j) => ({ atteint: ['done', 'atteint'], pret: ['you', 'prêt · à toi'], en_cours: ['work', 'en cours'], ouvert: ['wait', 'à faire'], refuse: ['fail', 'refusé'] }[j.etat]);
  PJ.etatTicket = (t) => {
    if (t.etape === 'traite') return ['done', 'traité'];
    if (t.etape === 'ecarte') return ['wait', 'écarté'];
    if (t.main === 'toi') return ['you', { accepter: 'proposé · à toi', question: 'question pour toi', plan: 'plan à valider', fusion: 'prête à fusionner' }[t.attend]];
    return t.etape === 'non_lu' ? ['wait', 'non lu'] : ['work', { analyse: 'en analyse', validation: 'en validation', pr: 'pull request en cours', fusion: 'en fusion' }[t.etape]];
  };
  PJ.CI = { ok: ['done', 'passée'], cours: ['work', 'en cours'], echec: ['fail', 'en échec'], attente: ['wait', 'en file'] };
  PJ.ci = (p, pr) => p.depot.ci.find((c) => c.id === pr.ci) || { etat: 'attente' };
  PJ.fusionnable = (p, pr) => pr.etat === 'ouverte' && PJ.ci(p, pr).etat === 'ok' && pr.relecture.etat === 'ok' && !pr.conflits;
  PJ.etatPr = (p, pr) => {
    if (pr.etat === 'fusionnee') return ['done', 'fusionnée'];
    if (pr.etat === 'fermee') return ['wait', 'fermée'];
    const c = PJ.ci(p, pr).etat;
    return PJ.fusionnable(p, pr) ? ['you', 'prête à fusionner'] : c === 'echec' ? ['fail', 'CI en échec'] : c === 'cours' ? ['work', 'CI en cours'] : ['work', 'ouverte'];
  };
  PJ.statut = (liste, e) => liste.statuts.find((s) => s[0] === e.statut) || liste.statuts[0];
  /* Une pull request liée, avec son statut : son état, la CI, la relecture. */
  PJ.parts.points = (p, pr) => {
    const c = PJ.ci(p, pr).etat, r = pr.relecture.etat === 'ok' ? 'ok' : 'attente';
    return `<span class="p2-dots"><span title="CI ${PJ.CI[c][1]}"><i class="${PJ.CI[c][0]}"></i>CI</span><span title="Relecture : ${h(pr.relecture.mot)}"><i class="${PJ.CI[r][0]}"></i>${r === 'ok' ? 'relue' : 'à relire'}</span></span>`;
  };
  PJ.parts.prLiee = (p, pr) => (pr ? `<a class="p2-lie haut" href="${PJ.fiche(p, 'code', 'pulls', pr.n)}">${PJ.tuile(pr.etat === 'fusionnee' ? 'p2-merge' : 'p2-pr', PJ.etatPr(p, pr)[0])}<span><b>${h(pr.titre)}</b>
    <small>n° ${pr.n} · <code>${h(pr.branche)}</code></small><span class="p2-lie-etat">${PJ.st(...PJ.etatPr(p, pr))}${pr.etat === 'ouverte' ? PJ.parts.points(p, pr) : ''}</span></span></a>` : '');
  /* Ses gestes à lui se gardent : le fil d'activité les montre. */
  PJ.geste = (p, texte, icone, vers, ref) => { (p.gestes = p.gestes || []).unshift(Object.assign({ ago: 0, texte, ico: icone || 'check', vers: vers || [] }, ref || {})); p.ago = 0; };
  const SORTES = PJ.SORTES = { accord: ['Ton accord', 'shield-check'], plan: ['Plan à valider', 'p2-plan'], question: ['Question pour toi', 'p2-question'], ticket: ['Ticket proposé', 'p2-ticket'],
    arret: ['Point d\'arrêt', 'p2-stop'], fusion: ['Pull request à fusionner', 'p2-merge'], element: ['À ta charge', 'p2-board'] };
  /* Ce qui l'attend dans un projet : calculé depuis les données, pour qu'un geste fait ici ou là retire la même ligne. */
  PJ.attentes = (p) => {
    const l = [], f = (...x) => PJ.fiche(p, ...x);
    if (PJ.voir(p) || p.etat === 'archive') return l;
    p.accords.forEach((a) => l.push({ id: `accord-${a.id}`, sorte: 'accord', titre: a.quoi, ago: a.ago, ref: a, ou: f('code', 'issues', 9, 'echanges') }));
    if (p.plan && p.plan.etat === 'propose') l.push({ id: 'plan', sorte: 'plan', titre: 'Son plan pour le projet', ago: p.plan.ago, ref: p.plan, ou: f() });
    (p.depot ? p.depot.pulls : []).filter((pr) => PJ.fusionnable(p, pr)).forEach((pr) => {
      const t = p.tickets.find((x) => x.n === pr.ticket);
      l.push({ id: `pr-${pr.n}`, sorte: 'fusion', titre: pr.titre, ago: t ? t.ago : pr.ago, ref: pr, ou: f('code', 'pulls', pr.n) });
    });
    p.tickets.filter((t) => t.main === 'toi' && t.attend !== 'fusion').forEach((t) => l.push({ id: `ticket-${t.n}`, sorte: { plan: 'plan', question: 'question', accepter: 'ticket' }[t.attend],
      titre: t.titre, ago: t.ago, ref: t, ailleurs: t.ailleurs, ou: f('tickets', t.n) }));
    p.objectifs.forEach((o) => {
      (o.jalons || []).filter((j) => j.etat === 'pret').forEach((j) => l.push({ id: `jalon-${o.id}-${j.id}`, sorte: 'arret', titre: j.titre, ago: j.ago, ref: j, objectif: o, ou: f('objectifs', 'o' + o.id) }));
      if (o.besoin) l.push({ id: `besoin-${o.id}`, sorte: 'question', titre: o.besoin, ago: o.ago, ref: o, objectif: o, ou: f('objectifs', 'o' + o.id) });
    });
    p.listes.forEach((li) => li.elements.filter((e) => e.charge === 'toi' && PJ.statut(li, e)[2] === 'wait').forEach((e) => l.push({ id: `element-${li.id}-${e.id}`, sorte: 'element',
      titre: `${e.nom} — ${PJ.statut(li, e)[1].toLowerCase()}`, ago: e.ago, ref: e, liste: li, ou: f('listes', li.id) })));
    return l.sort((a, b) => a.ago - b.ago);
  };
  PJ.toutesAttentes = () => P.projets.flatMap((p) => PJ.attentes(p).map((w) => Object.assign(w, { p })));
  const ouverts = PJ.ouverts = (p) => p.tickets.filter((t) => !['traite', 'ecarte'].includes(t.etape));
  const prOuvertes = (p) => (p.depot ? p.depot.pulls.filter((x) => x.etat === 'ouverte') : []);
  PJ.tonsJalons = (o) => (o.jalons && o.jalons.length ? o.jalons.map((j) => PJ.etatJalon(j)[0]) : [PJ.etatObjectif(o)[0]]);

  /* ── Les morceaux partagés : un plan, le parcours d'un ticket, une bulle, les boutons d'un geste ── */
  PJ.parts.plan = (p, plan, aToi) => `<section class="p2-plan${aToi ? ' you' : ''}">
    <header>${ico('p2-plan')}<b>Son plan</b>${PJ.st(...({ propose: ['you', 'attend ta validation'], valide: ['done', 'validé'], refuse: ['fail', 'refusé · elle le reprend'] }[plan.etat]))}</header>
    <ol>${plan.etapes.map((e) => `<li>${PJ.code(e)}</li>`).join('')}</ol>
    ${plan.note ? `<p class="p2-plan-note">${av('mika', 'xs')}<span>${h(plan.note)}</span></p>` : ''}</section>`;
  /* Le parcours d'un ticket, à la verticale : il vit dans le panneau latéral. */
  PJ.parts.parcours = (t) => {
    const i = P.etapes.findIndex(([k]) => k === t.etape), ton = PJ.etatTicket(t)[0];
    if (t.etape === 'ecarte') return `<p class="p2-ecarte">${ico('x', 'sm')}Ticket écarté : il ne sera pas traité.</p>`;
    return `<ol class="p2-steps" aria-label="Parcours du ticket">${P.etapes.map(([k, lib], n) => {
      const fait = n < i || t.etape === 'traite';
      return `<li class="${fait ? 'fait' : n === i ? 'ici ' + ton : ''}"${n === i ? ' aria-current="step"' : ''}><i>${fait ? ico('check', 'xs') : n + 1}</i><span>${lib}</span>${n === i && t.etape !== 'traite' ? `<em>${t.main === 'toi' ? 'la main est à toi' : 'la main est à elle'}</em>` : ''}</li>`;
    }).join('')}</ol>`;
  };
  PJ.parts.bulle = (m) => {
    if (m.de === 'hote') return PJ.parts.dehors(`${m.qui}, chez l'hôte · ${PJ.quand(m.ago)}`, m.texte);
    if (m.de === 'evenement') return `<div class="p2-evt">${ico(m.ico || 'check', 'xs')}<span>${h(m.texte)} · ${PJ.quand(m.ago)}</span></div>`;
    const q = PJ.qui(m.de), cote = m.de === 'adrien' ? 'moi' : m.de === 'mika' ? 'elle' : 'autre';
    return `<div class="p2-bub ${cote}">${cote === 'moi' ? '' : q.av('sm')}<div><span class="p2-bub-who">${cote === 'moi' ? 'Toi' : h(q.nom)} · ${PJ.quand(m.ago)}</span><p>${PJ.code(m.texte)}</p></div></div>`;
  };
  const B = PJ.boutons = {
    plan: (p, c, cl) => `<button class="btn ${cl || ''} primary" type="button" data-p2="planValider" data-p="${p.id}" data-c="${c}">${ico('check', 'sm')}Valider le plan</button><button class="btn ${cl || ''}" type="button" data-p2="planRefuser" data-p="${p.id}" data-c="${c}">${ico('x', 'sm')}Refuser</button>`,
    ticket: (p, n, cl) => `<button class="btn ${cl || ''} primary" type="button" data-p2="ticketAccepter" data-p="${p.id}" data-c="${n}">${ico('check', 'sm')}Accepter le ticket</button><button class="btn ${cl || ''}" type="button" data-p2="ticketEcarter" data-p="${p.id}" data-c="${n}">${ico('x', 'sm')}Écarter</button>`,
    jalon: (p, o, j, cl) => `<button class="btn ${cl || ''} primary" type="button" data-p2="jalonValider" data-p="${p.id}" data-o="${o.id}" data-c="${j.id}">${ico('check', 'sm')}Valider le jalon</button><button class="btn ${cl || ''}" type="button" data-p2="jalonRefuser" data-p="${p.id}" data-o="${o.id}" data-c="${j.id}">${ico('x', 'sm')}Refuser</button>`,
    accord: (p, a, cl) => `<button class="btn ${cl || ''} primary" type="button" data-p2="accordOui" data-p="${p.id}" data-c="${a.id}">${ico('check', 'sm')}Accorder</button><button class="btn ${cl || ''}" type="button" data-p2="accordNon" data-p="${p.id}" data-c="${a.id}">${ico('x', 'sm')}Refuser</button>`,
    fusion: (p, pr, cl) => `<button class="btn ${cl || ''} primary" type="button" data-p2="fusionner" data-p="${p.id}" data-c="${pr.n}"${PJ.fusionnable(p, pr) ? '' : ` disabled title="${h(pr.bloque || 'Pas encore possible.')}"`}>${ico('p2-merge', 'sm')}Fusionner dans ${h(pr.base)}</button>`,
  };

  /* ── À faire : la liste, ce qu'il faut lire pour décider, et à droite la décision ── */
  function attente(w) {
    const p = w.p, r = w.ref, d = `data-p="${p.id}"`, f = (...x) => PJ.fiche(p, ...x);
    let corps = '', gestes = '', lies = '', mot = '';
    if (w.sorte === 'accord') {
      corps = `<section class="p2-sent"><h3>Ce qui partirait, mot pour mot</h3><p>${h(r.texte)}</p></section><dl class="p2-facts"><div><dt>Ce que c'est</dt><dd>${h(r.nature)}</dd></div><div><dt>Où</dt><dd class="mono">${h(r.ou)}</dd></div><div><dt>Pourquoi</dt><dd>${h(r.pourquoi)}</dd></div></dl>`;
      gestes = B.accord(p, r, 'lg'); mot = 'Rien ne part sans ton accord.';
      const i = p.depot && p.depot.issues.find((x) => x.n === 9), t = p.tickets.find((x) => x.n === 6);
      lies = (i ? PJ.lie(f('code', 'issues', 9), 'p2-issue', 'wait', i.titre, 'issue n° 9 · d\'un inconnu', PJ.st('wait', 'ouverte')) : '') + (t ? PJ.lie(f('tickets', 6), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#6', PJ.st(...PJ.etatTicket(t))) : '');
    } else if (w.sorte === 'plan') {
      corps = (r.desc && PJ.md ? `<div class="p2-md court">${PJ.md(r.desc, {})}</div>` : `<p class="p2-lede">${h(r.fil ? r.fil[0].texte : p.resume)}</p>`) + PJ.parts.plan(p, r.plan || r, true);
      gestes = B.plan(p, r.n ? 't' + r.n : 'projet', 'lg'); mot = 'Validé, elle s\'y met à son prochain passage. Refusé, elle le reprend avec ce que tu lui dis.';
      if (r.n) { const o = p.objectifs.find((x) => x.id === r.objectif); lies = PJ.lie(f('tickets', r.n, 'fil'), 'chat', '', 'Le fil du ticket', PJ.pluriel(r.fil.length, 'message', 'messages')) + (o ? PJ.lie(f('objectifs', 'o' + o.id), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))) : ''); }
    } else if (w.sorte === 'question') {
      corps = PJ.parts.bulle({ de: 'mika', ago: w.ago, texte: r.question || r.besoin }) + `<div class="p2-answer"><textarea rows="4" data-p2-champ placeholder="Ta réponse…"></textarea>
        <div class="p2-acts"><button class="btn lg primary" type="button" data-p2="repondre" ${d} data-c="${r.n ? 't' + r.n : 'o' + r.id}">${ico('send')}Répondre</button></div></div>`;
      mot = 'Ta réponse lui rend la main : elle reprend à son prochain passage.';
      lies = r.n ? PJ.lie(f('tickets', r.n, 'fil'), 'chat', '', 'Le fil du ticket', PJ.pluriel(r.fil.length, 'message', 'messages')) : PJ.lie(w.ou, 'p2-target', PJ.etatObjectif(r)[0], r.titre, `objectif n° ${r.id}`, PJ.st(...PJ.etatObjectif(r)));
    } else if (w.sorte === 'ticket') {
      corps = `<div class="p2-thread">${r.fil.map(PJ.parts.bulle).join('')}</div>`;
      gestes = B.ticket(p, r.n, 'lg'); mot = 'Il vient d\'une issue d\'un inconnu : elle n\'y touche pas tant que tu ne l\'as pas accepté.';
      const i = p.depot && p.depot.issues.find((x) => x.n === r.issue);
      lies = i ? PJ.lie(f('code', 'issues', i.n), 'p2-issue', 'wait', i.titre, `issue n° ${i.n}`, PJ.st('wait', 'ouverte')) : '';
    } else if (w.sorte === 'arret') {
      const pr = p.depot && p.depot.pulls.find((x) => x.n === w.objectif.pr);
      corps = `<p class="p2-lede">${h(r.comment || 'Elle s\'est arrêtée ici : à toi de dire si ce jalon est atteint.')}</p><dl class="p2-facts"><div><dt>Vérifié par</dt><dd>${h(r.verif)}</dd></div><div><dt>Prêt depuis</dt><dd>${PJ.moment(r.ago)}</dd></div></dl>`;
      gestes = B.jalon(p, w.objectif, r, 'lg'); mot = 'Refusé, elle reprend ce jalon avec ce qui manque.';
      lies = PJ.lie(w.ou, 'p2-target', PJ.etatObjectif(w.objectif)[0], w.objectif.titre, `objectif n° ${w.objectif.id}`, PJ.st(...PJ.etatObjectif(w.objectif)))
        + (p.doc && p.doc.pages.some((x) => x.chemin === 'guide/connexion-rdp.md') ? PJ.lie(f('documentation', 'pages', 'guide/connexion-rdp.md'), 'book', '', 'Connexion RDP', 'la page à relire') : '') + PJ.parts.prLiee(p, pr);
    } else if (w.sorte === 'fusion') {
      const t = p.tickets.find((x) => x.n === r.ticket), run = PJ.ci(p, r);
      corps = `<p class="p2-lede">${PJ.code(r.resume)}</p><h3 class="p2-h3">Jalons et preuves</h3>${PJ.parts.preuves ? PJ.parts.preuves(r) : ''}`;
      gestes = `${B.fusion(p, r, 'lg')}<a class="btn lg" href="${w.ou}/fichiers">${ico('code', 'sm')}Lire le diff</a>`; mot = 'C\'est ton geste : Mika ne fusionne jamais.';
      lies = PJ.parts.prLiee(p, r) + (run.id ? PJ.lie(f('code', 'ci', run.id), 'bolt', PJ.CI[run.etat][0], `CI n° ${run.id}`, `${run.verifs.filter((v) => v.etat === 'ok').length} vérifications sur ${run.verifs.length}`, PJ.st(...PJ.CI[run.etat])) : '')
        + (t ? PJ.lie(f('tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#' + t.n, PJ.st(...PJ.etatTicket(t))) : '');
    } else if (w.sorte === 'element') {
      corps = `<p class="p2-lede">${h(r.note || 'Rien de noté pour l\'instant.')}</p><dl class="p2-facts"><div><dt>Qui</dt><dd>${h(r.sous)}</dd></div><div><dt>Statut</dt><dd>${PJ.st(PJ.statut(w.liste, r)[2], PJ.statut(w.liste, r)[1])}</dd></div></dl>`;
      gestes = w.liste.statuts.slice(1, 3).map(([k, lib], n) => `<button class="btn lg${n ? '' : ' primary'}" type="button" data-p2="elementStatut" ${d} data-l="${w.liste.id}" data-c="${r.id}" data-s="${k}">Passer à « ${h(lib)} »</button>`).join('')
        + `<button class="btn lg" type="button" data-p2="elementConfier" ${d} data-l="${w.liste.id}" data-c="${r.id}">${ico('sparkle', 'sm')}La lui confier</button>`;
      lies = PJ.lie(w.ou, 'p2-board', '', w.liste.titre, PJ.pluriel(w.liste.elements.length, 'élément', 'éléments'));
    }
    return { p, scroll: `af-${p.id}-${w.id}`,
      tete: PJ.parts.entete({ tuile: PJ.tuile(SORTES[w.sorte][1], 'you'), sur: h(SORTES[w.sorte][0]), titre: w.titre,
        meta: `<a href="${PJ.fiche(p)}">${h(p.titre)}</a><span>${PJ.quand(w.ago)}</span>${w.ailleurs ? PJ.st('out', 'venu d\'ailleurs') : ''}`, droite: `<a class="btn" href="${w.ou}">Ouvrir dans le projet${ico('chev-right', 'sm')}</a>` }),
      corps, cote: PJ.sc('Ta décision', `${gestes ? `<div class="p2-decide">${gestes}</div>` : ''}${mot ? `<p class="p2-hint">${ico('info', 'xs')}${h(mot)}</p>` : ''}`)
        + PJ.sc('En bref', PJ.props([['Projet', `<a href="${PJ.fiche(p)}">${h(p.titre)}</a>`], ['Ce que c\'est', h(SORTES[w.sorte][0])], ['Depuis', PJ.moment(w.ago)], w.ailleurs ? ['D\'où', PJ.st('out', 'venu d\'ailleurs')] : null]))
        + PJ.sc('Ce qui est lié', lies) };
  }
  function vueAFaire(loc) {
    const toutes = PJ.toutesAttentes(), l = toutes.filter((w) => !S.filtre || w.p.id === S.filtre);
    const [pid, id] = (loc.item || '').split('/');
    const w = PJ.choisi(l, (x) => `${x.p.id}/${x.id}`, `${pid}/${id}`);
    const projets = P.projets.filter((p) => toutes.some((x) => x.p === p));
    const ligne = (x) => `<a class="li p2-row" href="${PJ.route('a-faire', x.p.id, x.id)}" aria-selected="${x === w}">${PJ.tuile(SORTES[x.sorte][1], 'you')}
      <span class="li-main"><span class="li-title">${h(x.titre)}</span><span class="p2-row-sub"><span>${h(SORTES[x.sorte][0])}</span>${x.ailleurs ? PJ.st('out', 'venu d\'ailleurs') : ''}<time>${PJ.quand(x.ago)}</time></span></span></a>`;
    const liste = `<div class="pane-head"><h2>Ce qui t'attend</h2><span class="cnt">${l.length}</span></div>
      <div class="p2-filters"><button type="button" data-p2="filtreAFaire" data-c="0" aria-pressed="${!S.filtre}">Tous</button>${projets.map((p) =>
        `<button type="button" data-p2="filtreAFaire" data-c="${p.id}" aria-pressed="${S.filtre === p.id}">${h(p.titre)}<span class="cnt">${toutes.filter((x) => x.p === p).length}</span></button>`).join('')}</div>
      <div class="pane-scroll" data-scroll="af-liste">${l.length ? projets.filter((p) => !S.filtre || p.id === S.filtre).map((p) => `<div class="group-label">${h(p.titre)}<span class="cnt">${l.filter((x) => x.p === p).length}</span></div>${l.filter((x) => x.p === p).map(ligne).join('')}`).join('')
        : PJ.vide('check', 'Rien ne t\'attend', 'Tout ce qui demandait ta main est réglé.')}</div>`;
    const rien = PJ.vide('check', 'Rien ne t\'attend', 'Tout ce qui demandait ta main est réglé.');
    return PJ.trio(Object.assign({ liste, ouvert: !!loc.item && !!w, retour: [PJ.route('a-faire'), 'À faire'], volets: [['', 'À lire']], actif: '', lien: () => location.hash }, w ? attente(w) : { vide: rien }));
  }

  /* ── Projets : la grille ─────────────────────────────────────────── */
  function vueProjets() {
    const carte = (p) => {
      const n = PJ.attentes(p).length, faits = p.objectifs.filter((o) => o.etat === 'fait').length;
      const deps = [...p.liens.lit.map((x) => `dépend de ${x.titre}`), ...p.liens.luPar.map((x) => `${x.titre} en dépend`)];
      return `<a class="p2-pcard${p.etat === 'archive' ? ' archive' : ''}" href="${PJ.fiche(p)}"><div class="p2-pcard-top"><span class="p2-logo c${p.id % 8}">${h(p.titre[0])}</span><div class="grow"><h3>${h(p.titre)}</h3>
          <span class="p2-who">${p.pour === 'toi' ? 'à toi' : 'de ' + h(p.pour)} · menée par ${h(p.mene)}</span></div>${PJ.st(...PJ.etatProjet(p))}</div>
        <p class="p2-pcard-ou">${h(p.ou)}</p>
        <div class="p2-prog">${PJ.barre(p.objectifs.length ? p.objectifs.map((o) => PJ.etatObjectif(o)[0]) : ['wait'])}<span>${faits} / ${PJ.pluriel(p.objectifs.length, 'objectif', 'objectifs')}</span></div>
        <div class="p2-counts"><span><b>${prOuvertes(p).length}</b>pull requests</span><span><b>${ouverts(p).length}</b>tickets ouverts</span><span class="${n ? 'you' : ''}"><b>${n}</b>à toi</span></div>
        <div class="p2-pcard-foot"><span>${ico('clock', 'xs')}${PJ.quand(p.ago)}</span>${deps.map((x) => `<span>${ico('link', 'xs')}${h(x)}</span>`).join('')}</div></a>`;
    };
    const l = [...P.projets.filter((p) => p.etat !== 'archive'), ...P.projets.filter((p) => p.etat === 'archive')];
    return `<div class="fill-scroll" data-scroll="grille"><div class="p2-pgrid">${l.map(carte).join('')}
      <button class="p2-pcard p2-pnew" type="button" data-p2="nouveauProjet">${ico('plus', 'lg')}<b>Nouveau projet</b><span>Dis-lui ce que tu veux : elle te propose un plan.</span></button></div></div>`;
  }

  /* ── La fiche : Vue d'ensemble ───────────────────────────────────── */
  const carteTete = (icone, titre, lien, plus) => `<header class="p2-card-h">${ico(icone)}<h3>${h(titre)}</h3>${plus || ''}${lien ? `<a href="${lien[0]}">${h(lien[1])}${ico('chev-right', 'xs')}</a>` : ''}</header>`;
  PJ.onglets.vue = (p) => {
    const at = PJ.attentes(p), f = (...x) => PJ.fiche(p, ...x), tj = PJ.tonsJalons;
    const objs = [...p.objectifs.filter((o) => o.etat !== 'fait'), ...p.objectifs.filter((o) => o.etat === 'fait')].slice(0, 4), prs = prOuvertes(p), dernier = p.depot && p.depot.commits[0];
    const parEtape = P.etapes.map(([k, lib]) => [k, lib, p.tickets.filter((t) => t.etape === k).length]);
    return `<div class="fill-scroll" data-scroll="vue-${p.id}"><div class="p2-grid"><div class="p2-gcol">
      <section class="p2-card p2-ou"><header class="p2-card-h">${av('mika', 'sm')}<h3>Où il en est</h3><span class="p2-age">${PJ.quand(p.ago)}</span></header><p>${h(p.ou)}</p><small>${h(p.resume)}</small></section>
      <div class="p2-gpair"><section class="p2-card">${carteTete('p2-target', 'Objectifs', [f('objectifs'), `${p.objectifs.filter((o) => o.etat === 'fait').length} sur ${p.objectifs.length} terminés`])}
        ${objs.length ? objs.map((o) => `<a class="p2-mini col" href="${f('objectifs', 'o' + o.id)}"><span class="p2-mini-top"><b>${h(o.titre)}</b>${PJ.st(...PJ.etatObjectif(o))}</span>
          <span class="p2-prog">${PJ.barre(tj(o))}<span>${o.jalons.length ? `${o.jalons.filter((j) => j.etat === 'atteint').length} / ${PJ.pluriel(o.jalons.length, 'jalon', 'jalons')}` : 'pas de jalon'}</span></span></a>`).join('')
          : `<p class="p2-none">Pas encore d'objectif.</p>${PJ.voir(p) ? '' : `<button class="btn sm" type="button" data-p2="objectifAjouter" data-p="${p.id}">${ico('plus', 'sm')}Ajouter un objectif</button>`}`}</section><section class="p2-card">${carteTete('code', 'Code', p.depot ? [f('code', 'pulls'), 'Pull requests'] : null)}
        ${p.depot ? `${prs.map((pr) => `<a class="p2-mini" href="${f('code', 'pulls', pr.n)}">${PJ.tuile('p2-pr', PJ.etatPr(p, pr)[0])}<span><b>${h(pr.titre)}</b><small>n° ${pr.n} · ${PJ.quand(pr.ago)}</small></span>${PJ.st(...PJ.etatPr(p, pr))}</a>`).join('') || '<p class="p2-none">Aucune pull request ouverte.</p>'}
          <a class="p2-lastc" href="${f('code', 'commits', dernier.sha.slice(0, 7))}">${ico('p2-commit', 'sm')}<code>${dernier.sha.slice(0, 7)}</code><span class="ellipsis">${h(dernier.msg)}</span><time>${PJ.quand(dernier.ago)}</time></a>` : '<p class="p2-none">Ce projet n\'a pas de dépôt : il ne produit pas de code.</p>'}</section></div><div class="p2-gpair"><section class="p2-card">${carteTete('p2-ticket', 'Tickets', [f('tickets'), `${ouverts(p).length} ouverts`])}
        ${p.tickets.length ? `<div class="p2-stack">${parEtape.filter((x) => x[2]).map(([k, lib, n]) => `<i class="e${P.etapes.findIndex((e) => e[0] === k)}" style="flex:${n}" title="${lib} : ${n}"></i>`).join('')}</div>
          <ul class="p2-legend">${parEtape.map(([, lib, n], i) => `<li class="${n ? '' : 'zero'}"><i class="e${i}"></i>${lib}<b>${n}</b></li>`).join('')}</ul>` : '<p class="p2-none">Aucun ticket pour l\'instant.</p>'}</section><section class="p2-card">${carteTete('link', 'Dépendances', [f('dependances'), 'Le schéma'])}
        ${p.liens.lit.length || p.liens.luPar.length ? `<dl class="p2-deps"><div><dt>Il dépend de</dt><dd>${p.liens.lit.map((x) => `<a href="${f('dependances', 'lit-' + x.projet)}">${h(x.titre)}</a>`).join('') || '<span>aucun projet</span>'}</dd></div>
          <div><dt>Dépendent de lui</dt><dd>${p.liens.luPar.map((x) => `<a href="${f('dependances', 'luPar-' + x.projet)}">${h(x.titre)}</a>`).join('') || '<span>aucun projet</span>'}</dd></div></dl>` : '<p class="p2-none">Ce projet ne dépend d\'aucun autre, et aucun ne dépend de lui.</p>'}</section></div></div><div class="p2-gcol">
      <section class="p2-card p2-atoi${at.length ? '' : ' rien'}">${carteTete('inbox', 'À toi', at.length ? [PJ.route('a-faire'), 'Tout voir'] : null)}
        <div class="p2-big"><b>${at.length}</b><span>${at.length > 1 ? 'choses t\'attendent' : at.length ? 'chose t\'attend' : 'rien ne t\'attend'}</span></div>
        ${at.slice(0, 3).map((x) => `<a class="p2-mini" href="${PJ.route('a-faire', p.id, x.id)}">${PJ.tuile(SORTES[x.sorte][1], 'you')}<span><b>${h(x.titre)}</b><small>${h(SORTES[x.sorte][0])} · ${PJ.quand(x.ago)}</small></span></a>`).join('')}
        ${at.length > 3 ? `<a class="p2-more" href="${PJ.route('a-faire')}" data-p2="filtreAFaire" data-c="${p.id}" data-va="1">et ${at.length - 3} de plus</a>` : ''}</section>
      <section class="p2-card">${carteTete('clock', 'Prochain passage', [f('activite'), 'Activité'])}
        <div class="p2-next"><b>${h(p.etat === 'archive' ? 'aucun : le projet est archivé' : p.seance ? 'en cours, à ta demande' : p.prochain.quand)}</b><span>${h(p.prochain.sur)}</span></div>
        ${PJ.rythme ? `<p class="p2-consigne plain">${ico('calendar', 'xs')}<span>${h(PJ.rythme(p))}</span>${PJ.voir(p) ? '' : `<a href="${f('reglages', 'rythme')}">Régler</a>`}</p>` : ''}
        ${p.consignes.map((c) => `<p class="p2-consigne">${ico('pen', 'xs')}<span>Ta consigne : « ${h(c)} »</span></p>`).join('')}
        ${p.missions.map((m) => `<a class="p2-mini" href="${f('objectifs', m.id)}">${PJ.tuile('refresh')}<span><b>${h(m.titre)}</b><small>${h(m.cadence)} · ${h(m.declencheur)}</small></span></a>`).join('')}</section>
    </div></div></div>`;
  };

  /* ── Les gestes communs ──────────────────────────────────────────── */
  const A = PJ.actes;
  const champ = (b) => { const z = b.closest('.p2-answer, .p2-note, .p2-need'); return z && z.querySelector('[data-p2-champ]'); };
  const cible = (p, c) => (c === 'projet' ? { plan: p.plan } : c[0] === 't' ? p.tickets.find((t) => 't' + t.n === c) : p.objectifs.find((o) => 'o' + o.id === c));
  const note = (t, texte, icone) => { (t.histo = t.histo || []).push({ ago: 0, texte, ico: icone }); };
  A.infos = () => { S.infos = !S.infos; PJ.redessiner(); };
  A.volet = (d, b) => { S.infos = false; if (b.getAttribute('href') === location.hash) PJ.redessiner(); };
  A.filtreAFaire = (d) => { S.filtre = Number(d.c); if (d.va) return; if (M.ctx.item) M.go(PJ.route('a-faire')); else PJ.redessiner(); };
  A.filtreObjectifs = (d) => { S.of = S.of === d.c ? 'tous' : d.c; PJ.redessiner(); };   // un filtre se retire en le touchant de nouveau
  A.filtreTickets = (d) => { S.tf = d.c; PJ.redessiner(); };
  PJ.saisies.tickets = (v) => { S.tq = v; };
  A.planValider = (d) => {
    const p = PJ.proj(d.p), x = cible(p, d.c);
    x.plan.etat = 'valide';
    if (d.c === 'projet') { p.etat = 'actif'; p.ou = 'Plan validé : elle écrit les trois premiers messages.'; p.prochain.quand = 'dans quelques minutes'; PJ.geste(p, 'Tu as validé son plan pour le projet', 'p2-plan'); }
    else { Object.assign(x, { etape: 'pr', main: 'elle', attend: null, ago: 0 }); x.fil.push({ de: 'evenement', ago: 0, texte: 'Tu as validé son plan' }, { de: 'mika', ago: 0, texte: 'Merci. Je m\'y mets : j\'ouvre une branche, puis une pull request.' });
      note(x, 'Tu as validé son plan', 'check'); PJ.geste(p, `Tu as validé le plan du ticket #${x.n}`, 'p2-plan', ['tickets', x.n, 'plan'], { ticket: x.n }); }
    PJ.redessiner(); M.toast('Plan validé : elle s\'y met à son prochain passage.', { mika: true });
  };
  A.planRefuser = (d) => PJ.demander({ titre: 'Refuser son plan', label: 'Ce qui ne va pas (elle le reprendra avec ça)', exemple: 'Par exemple : pas de troisième commande, garde le reste.', bouton: 'Refuser le plan', alors: (texte) => {
    const p = PJ.proj(d.p), x = cible(p, d.c);
    x.plan.etat = 'refuse';
    if (d.c !== 'projet') { Object.assign(x, { etape: 'analyse', main: 'elle', attend: null, ago: 0 }); x.fil.push({ de: 'adrien', ago: 0, texte }, { de: 'mika', ago: 0, texte: 'Compris. Je reprends mon plan avec ça et je te le repropose.' });
      note(x, `Tu as refusé son plan : « ${texte} »`, 'x'); PJ.geste(p, `Tu as refusé le plan du ticket #${x.n}`, 'x', ['tickets', x.n, 'plan'], { ticket: x.n }); }
    else p.plan.note = `Tu as demandé une révision : « ${texte} »`;
    PJ.redessiner(); M.toast('Plan refusé : elle le reprend.', { ico: 'x' });
  } });
  A.repondre = (d, b) => {
    const c = champ(b), texte = c ? c.value.trim() : '';
    if (!texte) { c.focus(); c.classList.add('p2-manque'); return; }
    const p = PJ.proj(d.p), x = cible(p, d.c);
    if (d.c[0] === 't') { Object.assign(x, { main: 'elle', attend: null, question: '', ago: 0 }); x.fil.push({ de: 'adrien', ago: 0, texte }, { de: 'mika', ago: 0, texte: 'Merci, c\'est clair. J\'écris mon plan avec ça.' }); note(x, 'Tu as répondu à sa question', 'send'); }
    else { x.besoin = ''; x.rendus.unshift({ ago: 0, texte: `Tu as répondu : « ${texte} »` }); }
    PJ.geste(p, `Tu as répondu à sa question${d.c[0] === 't' ? ` sur le ticket #${x.n}` : ''}`, 'send', d.c[0] === 't' ? ['tickets', x.n, 'fil'] : ['objectifs', 'o' + x.id]);
    PJ.redessiner(); M.toast('Réponse envoyée : elle reprend la main.', { mika: true });
  };
  A.noter = (d, b) => {
    const c = champ(b), texte = c ? c.value.trim() : '';
    if (!texte) { c.focus(); c.classList.add('p2-manque'); return; }
    PJ.proj(d.p).tickets.find((t) => String(t.n) === d.c).fil.push({ de: 'adrien', ago: 0, texte });
    PJ.redessiner(); M.toast('Note ajoutée au fil.');
  };
  A.ticketAccepter = (d) => {
    const p = PJ.proj(d.p), t = p.tickets.find((x) => String(x.n) === d.c);
    Object.assign(t, { etape: 'analyse', main: 'elle', attend: null, ago: 0 });
    t.fil.push({ de: 'evenement', ago: 0, texte: 'Tu as accepté le ticket' }); note(t, 'Tu as accepté le ticket', 'check'); PJ.geste(p, `Tu as accepté le ticket #${t.n}`, 'p2-ticket', ['tickets', t.n], { ticket: t.n });
    PJ.redessiner(); M.toast(`Ticket #${t.n} accepté : elle l'analyse.`, { mika: true });
  };
  A.ticketEcarter = (d) => PJ.demander({ titre: 'Écarter le ticket', label: 'Pourquoi (facultatif)', exemple: 'Par exemple : hors du périmètre pour l\'instant.', bouton: 'Écarter', libre: true, alors: (texte) => {
    const t = PJ.proj(d.p).tickets.find((x) => String(x.n) === d.c);
    Object.assign(t, { etape: 'ecarte', main: null, attend: null, ago: 0 });
    t.fil.push({ de: 'evenement', ago: 0, ico: 'x', texte: `Tu as écarté le ticket${texte ? ` : « ${texte} »` : ''}` }); note(t, 'Tu as écarté le ticket', 'x');
    PJ.redessiner(); M.toast(`Ticket #${t.n} écarté.`, { ico: 'x' });
  } });
  const leJalon = (d) => { const o = PJ.proj(d.p).objectifs.find((x) => String(x.id) === d.o); return [o, o.jalons.find((j) => String(j.id) === d.c)]; };
  A.jalonValider = (d) => {
    const [o, j] = leJalon(d);
    Object.assign(j, { etat: 'atteint', ago: 0, refus: '' }); o.rendus.unshift({ ago: 0, texte: `Tu as validé le jalon « ${j.titre} ».` });
    PJ.geste(PJ.proj(d.p), `Tu as validé le jalon « ${j.titre} »`, 'check', ['objectifs', 'o' + o.id], { objectif: o.id });
    PJ.redessiner(); M.toast('Jalon validé.');
  };
  A.jalonRefuser = (d) => PJ.demander({ titre: 'Refuser le jalon', label: 'Ce qui manque', exemple: 'Par exemple : retire le champ « domaine ».', bouton: 'Refuser', alors: (texte) => {
    const [, j] = leJalon(d);
    Object.assign(j, { etat: 'en_cours', ago: 0, refus: texte });
    PJ.redessiner(); M.toast('Jalon refusé : elle le reprend.', { ico: 'x' });
  } });
  A.accordOui = (d) => {
    const p = PJ.proj(d.p), a = p.accords.find((x) => String(x.id) === d.c);
    p.accords = p.accords.filter((x) => x !== a);
    const issue = p.depot && p.depot.issues.find((i) => i.n === 9);
    if (issue) issue.commentaires.push({ de: 'mika', ago: 0, texte: a.texte });
    PJ.geste(p, `Tu as accordé : ${a.quoi.toLowerCase()}`, 'shield-check', ['code', 'issues', 9, 'echanges']);
    PJ.redessiner(); M.toast('Accordé : son message part chez l\'hôte.', { mika: true });
  };
  A.accordNon = (d) => { const p = PJ.proj(d.p); p.accords = p.accords.filter((x) => String(x.id) !== d.c); PJ.redessiner(); M.toast('Refusé : rien ne part, et elle le sait.', { ico: 'x' }); };
  A.elementStatut = (d) => {
    const li = PJ.proj(d.p).listes.find((x) => x.id === d.l), e = li.elements.find((x) => x.id === d.c);
    Object.assign(e, { statut: d.s, ago: 0 });
    PJ.redessiner(); M.toast(`${e.nom} : ${PJ.statut(li, e)[1].toLowerCase()}.`);
  };
  A.elementConfier = (d) => {
    const e = PJ.proj(d.p).listes.find((x) => x.id === d.l).elements.find((x) => x.id === d.c);
    e.charge = e.charge === 'toi' ? 'elle' : 'toi';
    PJ.redessiner(); M.toast(e.charge === 'elle' ? `${e.nom} : c'est elle qui s'en occupe.` : `${e.nom} : à ta charge.`, { mika: e.charge === 'elle' });
  };
  A.consigne = (d) => PJ.demander({ titre: 'Donner une consigne', label: 'Ta consigne (elle la lira avant son prochain passage)', exemple: 'Par exemple : finis l\'export avant de reprendre le module RDP.', bouton: 'Donner la consigne', alors: (texte) => {
    const p = PJ.proj(d.p); p.consignes.push(texte); PJ.geste(p, `Tu as donné une consigne : « ${texte} »`, 'pen'); PJ.redessiner(); M.toast('Consigne donnée : elle la lira avant son prochain passage.', { mika: true });
  } });
  A.lancer = (d) => {
    const p = PJ.proj(d.p);
    if (p.seance) { M.toast('Une séance est déjà en cours.', { ico: 'info' }); return; }
    p.seance = true; p.ago = 0;
    p.executions.unshift({ id: Math.max(0, ...p.executions.map((e) => e.id)) + 1, sorte: 'travail', sur: d.c || 'À ta demande', ago: 0, duree: 'en cours', verdict: ['work', 'en cours'], commit: '',
      rendu: 'Séance lancée à ta demande. Son compte rendu arrivera ici quand elle aura fini.', fait: ['A lu tes consignes et ce qui t\'attend'], demande: '' });
    M.mika.set({ fait: `travaille sur ${p.titre}` });
    PJ.redessiner(); M.toast('Séance lancée : son compte rendu arrivera dans Activité.', { mika: true });
  };
  A.pause = (d) => {
    const p = PJ.proj(d.p);
    if (p.etat === 'pause') { p.etat = p._avant || 'actif'; M.toast('Projet repris.', { ico: 'play' }); } else { p._avant = p.etat; p.etat = 'pause'; M.toast('Projet en pause : elle n\'y travaille plus.', { ico: 'pause' }); }
    PJ.redessiner();
  };
  A.copier = (d) => { try { navigator.clipboard.writeText(d.c); } catch (e) { /* file:// sans presse-papiers */ } M.toast(`Copié : ${d.c}`, { ico: 'copy' }); };

  /* ── Le cadre de l'écran : sa barre de titre, la fiche et ses onglets ── */
  PJ.tabs = (p) => [['vue', 'Vue d\'ensemble'], ['objectifs', 'Objectifs'], ['tickets', 'Tickets'], ['code', 'Code'], ['documentation', 'Documentation'], ['activite', 'Activité'], ['dependances', 'Dépendances'],
    ...(p.listes.length ? [['listes', 'Listes']] : [])];
  function lieu(ctx) {
    if (ctx.onglet !== 'projets' || !ctx.item) return { rubrique: ctx.onglet, item: ctx.item };
    const [id, tab, ...rest] = ctx.item.split('/');
    const p = PJ.proj(id);
    return p ? { rubrique: 'fiche', p, tab: tab === 'reglages' || PJ.tabs(p).some((o) => o[0] === tab) ? tab : 'vue', rest } : { rubrique: 'projets' };
  }
  PJ.lieu = () => lieu(M.route());
  function tete(loc) {
    const n = PJ.toutesAttentes().length;
    if (loc.rubrique !== 'fiche') return `<header class="page-head"><div class="ph-title"><h1>Projets</h1></div><nav class="subtabs" aria-label="Onglets">
        <a href="#projets/a-faire"${loc.rubrique === 'a-faire' ? ' aria-current="page"' : ''}>À faire<span class="cnt">${n}</span></a>
        <a href="#projets/projets"${loc.rubrique === 'projets' ? ' aria-current="page"' : ''}>Projets<span class="cnt">${P.projets.length}</span></a></nav>
      <div class="ph-actions"><button class="btn sm primary" type="button" data-p2="nouveauProjet">${ico('plus', 'sm')}<span class="lbl">Nouveau projet</span></button></div></header>`;
    const p = loc.p, cnt = { objectifs: p.objectifs.filter((o) => o.etat !== 'fait').length, tickets: ouverts(p).length };
    const brouillon = p.doc && Object.keys(p.doc.brouillons).length, regle = loc.tab === 'reglages';
    return `<header class="page-head p2-fhead"><a class="p2-crumb" href="#projets/projets" title="Tous les projets">${ico('chev-left', 'sm')}<span>Projets</span></a>
        <div class="ph-title"><h1>${h(p.titre)}</h1></div>${PJ.st(...PJ.etatProjet(p))}
        <span class="p2-who">${p.pour === 'toi' ? 'à toi' : 'de ' + h(p.pour)} · menée par ${h(p.mene)}${PJ.voir(p) ? ' · ouvert à toi pour le voir' : ''}</span>
        <div class="ph-actions">${PJ.voir(p) ? '' : `${p.etat === 'archive' ? '' : `<button class="btn sm" type="button" data-p2="consigne" data-p="${p.id}">${ico('pen', 'sm')}<span class="lbl">Donner une consigne</span></button>
          <button class="btn sm" type="button" data-p2="lancer" data-p="${p.id}"${p.seance ? ' disabled' : ''}>${ico('play', 'sm')}<span class="lbl">${p.seance ? 'Séance en cours' : 'Lancer maintenant'}</span></button>
          <button class="btn sm" type="button" data-p2="pause" data-p="${p.id}">${ico(p.etat === 'pause' ? 'play' : 'pause', 'sm')}<span class="lbl">${p.etat === 'pause' ? 'Reprendre' : 'Mettre en pause'}</span></button>`}
          <a class="btn sm${regle ? ' on' : ''}" href="${regle ? PJ.fiche(p) : PJ.fiche(p, 'reglages')}"${regle ? ' aria-current="page"' : ''}>${ico('settings', 'sm')}<span class="lbl">Modifier le projet</span></a>
          <button class="btn sm icon" type="button" data-p2="projetMenu" data-p="${p.id}" title="Archiver, supprimer">${ico('more', 'sm')}</button>`}</div></header>
      <nav class="p2-tabs" aria-label="Onglets du projet">${PJ.tabs(p).map(([k, lib]) => `<a href="${PJ.fiche(p, k === 'vue' ? '' : k)}"${loc.tab === k ? ' aria-current="page"' : ''}>${lib}${cnt[k] ? `<span class="cnt">${cnt[k]}</span>` : ''}${k === 'documentation' && brouillon ? '<i class="p2-dirty" title="Une page n\'est pas enregistrée"></i>' : ''}</a>`).join('')}</nav>`;
  }
  /* Des sous-onglets (Code, Documentation, Activité, Dépendances) : une rangée de pastilles, et ce qui va à droite. */
  PJ.sous = (p, tab, liste, actif, droite) => `<div class="p2-subbar"><nav class="p2-sub" aria-label="Sous-onglets">${liste.map(([k, lib, n]) =>
    `<a href="${PJ.fiche(p, tab, k)}"${k === actif ? ' aria-current="page"' : ''}>${lib}${n != null ? `<span class="cnt">${n}</span>` : ''}</a>`).join('')}</nav>${droite ? `<div class="p2-subbar-side">${droite}</div>` : ''}</div>`;

  M.register('projets', {
    titre: 'Projets', sansTete: true,
    onglets: [{ id: 'a-faire', titre: 'À faire' }, { id: 'projets', titre: 'Projets' }],
    compte: () => PJ.toutesAttentes().length,
    monte: () => {
      document.addEventListener('click', (e) => {
        const b = e.target.closest('[data-p2]');
        if (!b || !PJ.actes[b.dataset.p2]) return;
        if (b.tagName !== 'A' || !b.dataset.va) e.preventDefault();
        PJ.actes[b.dataset.p2](b.dataset, b, e);
      });
      document.addEventListener('submit', (e) => {
        const f = e.target.closest('[data-p2-form]');
        if (!f) return;
        e.preventDefault();
        const d = new FormData(f), v = {};
        new Set(d.keys()).forEach((k) => { v[k] = f.querySelectorAll(`[name="${k}"][type="checkbox"]`).length > 1 ? d.getAll(k) : d.get(k); });
        const dansTiroir = !!f.closest('.p2-drawer');
        if (PJ.formes[f.dataset.p2Form](v, f.dataset, f) !== false && dansTiroir) PJ.fermerTiroir();
      });
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape') PJ.fermerTiroir(); });
      addEventListener('hashchange', () => PJ.fermerTiroir());
      document.addEventListener('input', (e) => {
        const c = e.target.closest('[data-p2-saisie]');
        if (!c) { if (e.target.matches('.p2-manque')) e.target.classList.remove('p2-manque'); return; }
        const nom = c.dataset.p2Saisie, pos = c.selectionStart;
        PJ.saisies[nom](c.value, c);
        if (c.dataset.sansRendu != null) return;
        PJ.redessiner();
        const neuf = document.querySelector(`[data-p2-saisie="${nom}"]`);
        if (neuf) { neuf.focus(); try { neuf.setSelectionRange(pos, pos); } catch (err) { /* un champ sans curseur */ } }
      });
    },
    rendu: (body, ctx) => {
      const garde = {};
      body.querySelectorAll('[data-scroll]').forEach((el) => { garde[el.dataset.scroll] = el.scrollTop; });
      if (ctx.route !== PJ._route) { S.infos = PJ._ouvrirInfos === true && M.mobile(); PJ._route = ctx.route; }
      PJ._ouvrirInfos = false;
      const loc = lieu(ctx);
      if (PJ.quitter) PJ.quitter(loc, body);
      const corps = loc.rubrique === 'a-faire' ? vueAFaire(loc) : loc.rubrique === 'projets' ? vueProjets() : (PJ.onglets[loc.tab] || PJ.onglets.vue)(loc.p, loc.rest);
      body.innerHTML = `<div class="p2${loc.rubrique === 'fiche' ? ' fiche' : ''}">${tete(loc)}<div class="p2-body">${corps}</div></div>`;
      body.querySelectorAll('[data-scroll]').forEach((el) => { if (garde[el.dataset.scroll]) el.scrollTop = garde[el.dataset.scroll]; });
      if (PJ.apres) PJ.apres(body, loc);
      (PJ.suites || []).forEach((f) => f(body, loc));
    },
    recherche: () => P.projets.flatMap((p) => [
      { groupe: 'Projets', titre: p.titre, sous: p.ou, ico: 'flag', route: PJ.fiche(p) },
      ...p.tickets.map((t) => ({ groupe: 'Tickets', titre: `#${t.n} ${t.titre}`, sous: `${p.titre} · ${PJ.etatTicket(t)[1]}`, ico: 'p2-ticket', route: PJ.fiche(p, 'tickets', t.n) })),
      ...(p.depot ? p.depot.pulls.map((x) => ({ groupe: 'Pull requests', titre: `n° ${x.n} ${x.titre}`, sous: `${p.titre} · ${PJ.etatPr(p, x)[1]}`, ico: 'p2-pr', route: PJ.fiche(p, 'code', 'pulls', x.n) })) : []),
      ...(p.doc ? p.doc.pages.map((x) => ({ groupe: 'Documentation', titre: x.chemin, sous: p.titre, ico: 'book', route: PJ.fiche(p, 'documentation', 'pages', x.chemin) })) : []),
    ]),
    notes: () => [
      { groupe: 'Ce qu\'il a choisi (2026-11-21)', statut: 'decide', titre: 'Trois zones sur toute la largeur', texte: 'la liste, le contenu découpé en volets, un panneau latéral (l\'état, ce qui est lié avec son statut, les gestes) ; sur un téléphone, le panneau devient le volet « Infos »' },
      { statut: 'decide', titre: 'Tout se gère dans l\'écran', texte: 'modifier le projet, ajouter un objectif ou une mission, un jalon, modifier un ticket, une pull request, une décision : dans la zone de contenu ou dans un panneau' },
      { statut: 'decide', titre: 'Le code en entier', texte: 'les fichiers, les commits et leur diff (unifié ou côte à côte), les pull requests complètes, les branches, les issues, la CI' },
      { statut: 'decide', titre: 'Fusionner depuis l\'écran', texte: 'un bouton, son geste à lui, avec confirmation ; Mika ne fusionne toujours pas' },
      { statut: 'decide', titre: 'La documentation, un espace à part', texte: 'des pages .md hors du dépôt, écrites ici dans un éditeur (Milkdown Crepe) ; ses décisions y ont leur sous-onglet ; l\'accès par MCP va d\'office à qui a accès au projet, sans réglage' },
      { statut: 'decide', titre: '« Listes », seulement quand le projet en a', texte: 'l\'ancien onglet Suivi sort de la fiche ordinaire' },
      { groupe: 'Ce que cela demande au serveur', statut: 'manque', titre: 'Le dépôt par l\'API par personne', texte: 'ni les fichiers, ni les commits et leur diff, ni les listes de pull requests, de branches et d\'issues, ni la CI en détail ne sont servis aujourd\'hui', src: 'backendv2/docs/protocole-moi.md § 11' },
      { statut: 'manque', titre: 'Écrire depuis l\'écran', texte: 'modifier un projet, un objectif, un jalon, un ticket, une pull request, une décision : des routes d\'écriture par personne, avec les droits du moteur' },
      { statut: 'manque', titre: 'Fusionner : une capacité du propriétaire', texte: 'un geste chez l\'hôte, à lui seul, que les outils de Mika n\'ont pas' },
      { statut: 'manque', titre: 'L\'espace de documentation', texte: 'pages, versions, images : rien n\'existe encore ; la dépendance de l\'éditeur se décide au moment du code' },
      { statut: 'manque', titre: 'Le fil d\'activité, les exécutions pas à pas, le carnet', texte: 'le moteur les garde, l\'API par personne ne les rend pas' },
      { statut: 'partiel', titre: 'À faire, plans, tickets, listes', texte: 'servis par l\'API par personne (ADR 0284)' },
    ],
  });
})();
