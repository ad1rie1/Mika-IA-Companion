/* Outils › Droits : chaque agenda, une ressource de la matrice (proposé le 2026-11-23, pas encore validé). Posé par-dessus
   l'écran Outils validé, sans le retoucher : un groupe « Tes agendas » dans la liste des Droits (après « Tes comptes »),
   et pour chacun son tableau sur une page. Sur un téléphone, une carte par ligne du tableau plutôt qu'un tableau large :
   Qui × Par où × Quand en tête de carte, puis ses quatre colonnes en lignes — Lire ; Ajouter, modifier, supprimer (non ·
   avec ton accord · seule) ; Répondre aux invitations (non · avec ton accord) ; Ce qu'elle en garde. Lues de haut en bas.
   Le propriétaire d'un agenda règle son tableau ici (une feuille par valeur) ; un agenda qu'on partage avec toi montre
   celui de son propriétaire. C'est la page web (frontend/Web/maquette/ecrans/agenda-droits.js) en cartes.
   Route : #outils/droits/<agenda>. */
(function () {
  const { h, ico, av } = A;
  const X = A.agenda;
  const O0 = A.vue('outils');
  if (!X || !O0) return;
  const { G, AG } = X;
  const IDS = ['mon', 'travail', 'perso', 'famille', 'feries', 'lea'];
  const QUAND = { repond: 'quand elle te répond', parole: 'd\'elle-même', seule: 'au travail, seule', toujours: 'toujours' };
  const QUAND_SOUS = { parole: 'ses rappels', seule: 'tes invitations à préparer' };
  const OPT = {
    lire: [['oui', 'Oui'], ['non', 'Non']],
    ecrire: [['non', 'Non'], ['accord', 'Avec ton accord'], ['seule', 'Seule']],
    repondre: [['non', 'Non'], ['accord', 'Avec ton accord']],
    garde: [['rien', 'Rien'], ['un souvenir', 'Un souvenir'], ['un savoir', 'Un savoir'], ['une confidence', 'Une confidence']],
  };
  const COLS = [['lire', 'Lire', 'agenda_list · agenda_events · agenda_free'], ['ecrire', 'Ajouter, modifier, supprimer', 'agenda_create · agenda_edit · agenda_delete'],
    ['repondre', 'Répondre aux invitations', 'agenda_respond'], ['garde', 'Ce qu\'elle en garde', '']];
  const CLS = { oui: 'S', seule: 'S', accord: 'A', non: 'N', '—': 'N' };
  const libelle = (col, v) => (v === '—' ? '—' : ((OPT[col].find((o) => o[0] === v) || [v, v])[1]));
  const valeur = (col, v) => (col === 'garde' ? `<span class="tag">${h(libelle(col, v))}</span>` : `<span class="lvl ${CLS[v] || 'N'}">${h(libelle(col, v))}</span>`);

  function qui(l) {
    if (l.qui === 'toi') return [av('adrien', 'sm'), 'Toi', l.partage ? 'partage · lire' : ''];
    if (l.qui === 'elle') return [`<span class="lead" style="width:32px;height:32px">${A.face(32)}</span>`, 'Mika', 'elle seule'];
    return [av(l.qui, 'sm'), A.who(l.qui).nom, `partage · ${X.NIVEAUX[l.partage][0].toLowerCase()}`];
  }
  function regles(a) {
    if (a.groupe === 'partages') return [`Partage de ${A.who(a.de).nom} : toi · ${X.NIVEAUX[a.niveau][0].toLowerCase()} (depuis le ${a.depuisPartage})`, 'C\'est son agenda : seule elle règle son tableau', 'La lecture n\'ouvre ni ajouter, ni répondre'];
    const out = ['Lues de haut en bas : la première ligne qui correspond décide', 'Plafond : à plusieurs (un salon), rien de tes agendas'];
    if (a.groupe === 'abonnements') out.push('Un abonnement est en lecture seule : ni toi ni elle n\'y écrivez');
    if (a.partages.length) out.push(`Partagé dans Mika avec ${a.partages.map(([k]) => A.who(k).court).join(' et ')} : une ligne chacun`);
    return out;
  }
  function vuePage(id) {
    const a = AG[id];
    const L = G.droits[id];
    if (!a || !L) {
      return { nav: A.v.nav === 'barre' ? 'plus' : 'outils', back: '#outils', html: `${A.top({ title: a ? `Agenda · ${h(a.nom)}` : 'Agenda', small: true, back: true, face: false })}
        <div class="body"><div class="cx-empty">${ico('sparkle')}<b>Pas de tableau</b><p>L'agenda de Mika n'en a pas : c'est sa mémoire, qu'elle ne montre qu'à qui elle concerne. On le corrige en le lui disant.</p></div></div>`, notes: {} };
    }
    const edit = X.proprio(a);
    const cartes = L.map((l, i) => {
      const [avatar, nom, sous] = qui(l);
      return `<div class="ag-mx"><div class="ag-mx-h"><span class="ag-mx-n">${i + 1}</span>${avatar}<span class="txt"><b>${h(nom)}${sous ? ` <span class="tag${l.partage ? ' pc' : ''}">${h(sous)}</span>` : ''}</b>
          <small>${h(l.ou === '—' ? 'partout' : l.ou)} · ${h(QUAND[l.quand])}${QUAND_SOUS[l.quand] ? ` (${h(QUAND_SOUS[l.quand])})` : ''}</small></span></div>
        ${COLS.map(([c, lb, outils]) => {
          const v = l[c], peut = edit && v !== '—';
          return `<${peut ? `button type="button" data-sheet="ag-droit" data-agdroit="${id}:${i}:${c}"` : 'div'} class="ag-mx-r"><span class="txt"><b>${h(lb)}</b>${outils ? `<small class="mono">${h(outils)}</small>` : ''}</span>${valeur(c, v)}${peut ? ico('chev-down', 'xs') : ''}</${peut ? 'button' : 'div'}>`;
        }).join('')}
        ${edit && l.partage ? `<div class="ag-mx-f"><button class="btn text sm" type="button" data-agdroitret="${id}:${l.qui}" style="color:var(--danger)">${ico('x')}Retirer le partage</button></div>` : ''}</div>`;
    }).join('');
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'outils', back: '#outils', cls: 'ag-scr',
      html: `${A.top({ title: `Agenda · ${h(a.nom)}`, sub: `${h(X.fournisseur(a))} · ${a.groupe === 'partages' ? `à ${h(A.who(a.de).nom)}` : 'à toi'}`, small: true, back: true, face: false,
        actions: [A.act('agenda', 'Ouvrir l\'Agenda', 'data-go="#agenda/semaine"'), ...(edit ? [A.act('user-plus', 'Partager', `data-go="#agenda/partager/${id}"`)] : [])] })}
        <div class="body ag-droits"><div class="ag-mx-tete" style="--c:var(--ag-${a.couleur})">${X.sw(a.couleur, 'lg')}<span class="txt"><b>${h(X.resume(id))}</b><small>${a.compte ? h(X.CPT[a.compte].adresse) : ''}</small></span></div>
          <ul class="ag-mx-lines">${regles(a).map((r) => `<li>${h(r)}</li>`).join('')}</ul>
          ${cartes}
          <div class="ag-mx ag-mx-def"><div class="ag-mx-h"><span class="ag-mx-n">—</span><span class="txt"><b>Par défaut</b><small>fermé : personne d'autre</small></span></div></div>
          ${edit ? `<div style="padding:4px 16px 0"><button class="btn tonal block" type="button" data-snack="Maquette : une ligne de plus (qui, par où, quand), placée au-dessus de « Par défaut »">${ico('plus')}Ajouter une ligne</button></div>` : ''}
          <p class="note" style="padding:14px 24px 24px">Avec ton accord : une carte dans le chat, avec exactement ce qui partira. « Ce qu'elle en garde » : ce qu'elle retient de ce qu'elle y lit (rien · un souvenir · un savoir · une confidence).</p></div>`,
      notes: {
        titre: `Outils › Droits › Agenda « ${h(a.nom)} » (proposé)`,
        reprend: ['Le tableau de droits d\'un agenda, comme celui d\'un service : ses lignes (Qui × Par où × Quand), lues de haut en bas, puis « Par défaut ».',
          'Sur un téléphone, une carte par ligne plutôt qu\'un tableau large : en tête, qui, par où, quand ; dessous, ses quatre colonnes, chacune avec ses outils nommés.',
          edit ? 'C\'est ton agenda : chaque valeur se règle dans une feuille ; une ligne de partage se retire ; « Ajouter une ligne ».' : `C'est l'agenda de ${h(A.who(a.de).nom)} : tu vois son tableau, tu ne le règles pas.`,
          'En haut : ce que Mika en fait, en une phrase (la même que dans Paramètres) ; ouvrir l\'Agenda, partager.'],
        trancher: ['Régler ici (l\'agenda est à toi), ou seulement montrer, comme les autres ressources de cet écran (elles se règlent dans la console) ?',
          'Une carte par ligne (ici), ou la vue d\'un canal à la fois comme le reste d\'Outils (deux pastilles par outil) ?'],
      },
    };
  }

  A.ecran('outils', (args) => {
    if (args[0] === 'droits' && args[1]) return vuePage(args[1]);
    const v = O0(args);
    if (args[0] === 'services' || args[0] === 'accords') return v;
    const after0 = v.after;
    return { ...v,
      notes: { ...v.notes, reprend: [...(v.notes.reprend || []), 'Proposé (Agenda) : un groupe « Tes agendas » après « Tes comptes » ; toucher un agenda ouvre son tableau.'] },
      after(root) {
        if (after0) after0(root);
        const heads = [...root.querySelectorAll('.list-head')];
        const ancre = heads.find((x) => x.textContent.trim() === 'Ce téléphone');
        if (!ancre || root.querySelector('[data-agmx-groupe]')) return;
        ancre.insertAdjacentHTML('beforebegin', `<div class="list-head" style="padding:12px 4px 2px" data-agmx-groupe>Tes agendas</div>${IDS.map((id) => {
          const a = AG[id], l = (G.droits[id] || []).find((x) => x.qui === 'toi' && (x.quand === 'repond' || x.quand === 'toujours'));
          const n = { S: 0, A: 0, N: 0 };
          if (l) ['lire', 'ecrire', 'repondre'].forEach((c) => { n[CLS[l[c]] || 'N']++; });
          return `<div class="res"><button type="button" data-go="#outils/droits/${id}">${X.sw(a.couleur, 'lg')}<span class="grow"><b>Agenda · ${h(a.nom)}</b><small>${h(X.fournisseur(a))} · ${a.groupe === 'partages' ? 'partagé avec toi' : 'à toi'}</small>
            <span class="sum-pills">${n.S ? `<span class="lvl S">${n.S} seule</span>` : ''}${n.A ? `<span class="lvl A">${n.A} accord</span>` : ''}${n.N ? `<span class="lvl N">${n.N} non</span>` : ''}</span></span>${ico('chev-right', 'sm')}</button></div>`;
        }).join('')}`);
      } };
  });

  A.sheets['ag-droit'] = (x) => {
    const [id, i, col] = x.dataset.agdroit.split(':');
    const l = G.droits[id][+i], [, nom] = qui(l);
    const lb = COLS.find((c) => c[0] === col)[1];
    A.sheet(h(lb), `<p class="note" style="padding:0 24px 6px">Agenda « ${h(AG[id].nom)} » · ligne ${+i + 1} : ${h(nom)}, ${h(l.ou === '—' ? 'partout' : l.ou)}, ${h(QUAND[l.quand])}.</p>
      ${OPT[col].map(([k, t]) => `<button class="li${l[col] === k ? ' sel' : ''}" type="button" data-agdroitv="${id}:${i}:${col}:${k}"><span class="lead">${col === 'garde' ? ico(k === 'rien' ? 'x' : 'book') : `<i class="ag-lvd ${CLS[k] || 'N'}"></i>`}</span><span class="txt"><b>${h(t)}</b></span>${l[col] === k ? ico('check') : ''}</button>`).join('')}`);
  };
  document.addEventListener('click', (e) => {
    let x;
    if ((x = e.target.closest('[data-agdroitv]'))) {
      const [id, i, col, v] = x.dataset.agdroitv.split(':');
      const l = G.droits[id][+i];
      l[col] = v;
      A.closeAll(); A.render();
      const quiDit = l.qui === 'toi' ? 'avec toi' : l.qui === 'elle' ? 'elle seule' : `avec ${A.who(l.qui).court}`;
      A.snack(`« ${AG[id].nom} », ${quiDit} : ${COLS.find((c) => c[0] === col)[1].toLowerCase()} — ${libelle(col, v).toLowerCase()}`);
      return;
    }
    if ((x = e.target.closest('[data-agdroitret]'))) {
      const [id, k] = x.dataset.agdroitret.split(':');
      G.droits[id] = G.droits[id].filter((l) => l.qui !== k);
      AG[id].partages = AG[id].partages.filter((p) => p[0] !== k);
      A.render();
      A.snack(`Partage retiré : ${A.who(k).court} ne voit plus « ${AG[id].nom} »`);
    }
  });

  A.index('Agenda · Outils (proposé)', [['Droits', '#outils'], ['Mon agenda', '#outils/droits/mon'], ['Travail', '#outils/droits/travail'], ['Perso, partagé', '#outils/droits/perso'], ['Agenda de Léa', '#outils/droits/lea'], ['Jours fériés', '#outils/droits/feries']]);
})();
