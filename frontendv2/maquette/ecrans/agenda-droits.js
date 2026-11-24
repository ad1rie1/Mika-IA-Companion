/* Outils › Droits : chaque agenda, une ressource de la matrice — proposé le 2026-11-23, pas encore validé. Posé par-dessus
   l'écran Outils validé, sans le retoucher : un groupe « Tes agendas » dans la liste des ressources, et pour chacun son
   tableau. Ses colonnes : Lire ; Ajouter, modifier, supprimer (non · avec ton accord · seule) ; Répondre aux invitations
   (non · avec ton accord) ; Ce qu'elle en garde. Ses lignes : Qui × Par où × Quand, lues de haut en bas, comme les
   lignes d'accès des autres ressources. Le propriétaire d'un agenda règle son tableau ici ; un agenda qu'on partage
   avec toi montre celui de son propriétaire. Route : #outils/droits/ag-<agenda>. */
(function () {
  const O = M.ecrans.outils;
  if (!O || !M.agenda) return;
  const { h, ico, av } = M;
  const G = M.agenda, A = G.A, AG = G.AG;
  const IDS = ['mon', 'travail', 'perso', 'famille', 'feries', 'lea'];
  let sel = 'tout', vu = null;

  // Les mots de la matrice des outils : elle répond, d'elle-même, elle seule au travail.
  const QUAND = { repond: 'elle te répond', parole: 'd\'elle-même', seule: 'au travail', toujours: 'toujours' };
  const QUAND_SOUS = { parole: 'ses rappels', seule: 'tes invitations à préparer', repond: '' };
  const OPT = {
    lire: [['oui', 'Oui'], ['non', 'Non']],
    ecrire: [['non', 'Non'], ['accord', 'Ton accord'], ['seule', 'Seule']],
    repondre: [['non', 'Non'], ['accord', 'Ton accord']],
    garde: [['rien', 'rien'], ['un souvenir', 'un souvenir'], ['un savoir', 'un savoir'], ['une confidence', 'une confidence']],
  };
  const CLS = { oui: 'ok', seule: 'ok', accord: 'warn', non: 'off', '—': 'off' };
  const libelle = (col, v) => (v === '—' ? '—' : ((OPT[col].find((o) => o[0] === v) || [v, v])[1]));
  const COLS = [['lire', 'Lire'], ['ecrire', 'Ajouter, modifier, supprimer'], ['repondre', 'Répondre aux invitations'], ['garde', 'Ce qu\'elle en garde']];

  function qui(l) {
    const ligne = (a, nom, sous) => `<div class="ag-qui">${a}<span><b>${nom}</b>${sous ? `<small>${sous}</small>` : ''}</span></div>`;
    if (l.qui === 'toi') return ligne(av('adrien', 'xs'), 'Toi', l.partage ? '<span class="ag-part-tag">partage · lire</span>' : '');
    if (l.qui === 'elle') return ligne(av('mika', 'xs'), 'Mika', 'elle seule');
    return ligne(av(l.qui, 'xs'), h(M.who(l.qui).nom), `<span class="ag-part-tag">partage · ${h(G.NIVEAUX[l.partage][0].toLowerCase())}</span>`);
  }
  function cellule(agId, i, col, v, edit) {
    if (v === '—' || !edit) return `<td class="ag-mx-c"><span class="lv ${col === 'garde' ? 'off' : CLS[v] || 'off'}">${h(libelle(col, v))}</span></td>`;
    return `<td class="ag-mx-c"><select class="ag-lv ${col === 'garde' ? 'garde' : CLS[v] || ''}" data-agdroit="${agId}:${i}:${col}" title="${h(COLS.find((c) => c[0] === col)[1])}">${OPT[col].map(([k, l]) => `<option value="${k}"${k === v ? ' selected' : ''}>${h(l)}</option>`).join('')}</select></td>`;
  }
  function regles(a) {
    if (a.groupe === 'partages') return [`Partage de ${M.who(a.de).nom} : toi · ${G.NIVEAUX[a.niveau][0].toLowerCase()} (depuis le ${a.depuisPartage})`, 'C\'est son agenda : seule elle règle son tableau', 'La lecture n\'ouvre ni ajouter, ni répondre'];
    const out = ['Lues de haut en bas : la première ligne qui correspond décide', 'Plafond : à plusieurs (un salon), rien de tes agendas'];
    if (a.groupe === 'abonnements') out.push('Un abonnement est en lecture seule : ni toi ni elle n\'y écrivez');
    if (a.partages.length) out.push(`Partagé dans Mika avec ${a.partages.map(([k]) => M.who(k).court).join(' et ')} : une ligne chacun`);
    return out;
  }
  function section(id, q) {
    const a = AG[id], L = A.droits[id] || [], edit = G.proprio(a);
    if (q && !M.norm(`agenda ${a.nom} ${G.fournisseur(a)} agenda_list agenda_events agenda_free agenda_create agenda_edit agenda_delete agenda_respond`).includes(M.norm(q))) return '';
    const lignes = L.map((l, i) => `<tr><td class="muted">${i + 1}</td><td>${qui(l)}</td><td class="small ag-mx-ou">${h(l.ou)}</td>
      <td class="small ag-mx-quand">${h(QUAND[l.quand])}${QUAND_SOUS[l.quand] ? `<div class="tiny muted">${h(QUAND_SOUS[l.quand])}</div>` : ''}</td>
      ${COLS.map(([c]) => cellule(id, i, c, l[c], edit)).join('')}
      <td class="actions">${edit && l.partage ? `<button class="btn xs ghost danger" type="button" data-agdroitret="${id}:${l.qui}">Retirer</button>` : ''}</td></tr>`).join('');
    return `<section class="mx-res ag-mx-res" id="res-ag-${id}" style="--c:var(--ag-${a.couleur})">
      <header class="mx-head"><span class="fam-ico ag-fam">${ico('agenda')}</span><div class="grow"><h3>Agenda · ${h(a.nom)}</h3>
        <p>${h(G.fournisseur(a))}${a.compte ? ' · ' + h(G.CPT[a.compte].adresse) : ''} · ${a.groupe === 'partages' ? `à ${h(M.who(a.de).nom)}, partagé avec toi` : 'à toi'}</p></div>
        <a class="btn xs ghost" href="#agenda/semaine">${ico('agenda', 'xs')}Ouvrir</a>${edit ? `<a class="btn xs ghost" href="#agenda/partager/${id}">${ico('user-plus', 'xs')}Partager</a>` : ''}</header>
      <ul class="mx-lines">${regles(a).map((r) => `<li>${h(r)}</li>`).join('')}</ul>
      <div class="mx-scroll"><table class="tbl ag-mx"><thead><tr><th>#</th><th>Qui</th><th>Par où</th><th>Quand</th>${COLS.map(([, l]) => `<th class="ag-mx-h">${h(l)}</th>`).join('')}<th></th></tr></thead>
        <tbody>${lignes}<tr class="def"><td class="muted">—</td><td colspan="${COLS.length + 4}"><b>Par défaut</b> <span class="small muted">· fermé : personne d'autre</span></td></tr></tbody></table></div>
      <div class="ag-mx-foot">${edit ? `<button class="btn xs" type="button" data-agdroitadd="${id}">${ico('plus', 'xs')}Ajouter une ligne</button>` : ''}
        <span class="small muted">Ses outils : <code>agenda_list</code> <code>agenda_events</code> <code>agenda_free</code> (lire) · <code>agenda_create</code> <code>agenda_edit</code> <code>agenda_delete</code> (ajouter, modifier, supprimer) · <code>agenda_respond</code> (répondre). Avec ton accord : une carte dans le chat.</span></div>
    </section>`;
  }
  function compte(id) {
    const l = (A.droits[id] || []).find((x) => x.qui === 'toi' && (x.quand === 'repond' || x.quand === 'toujours'));
    if (!l) return { s: 0, a: 0 };
    const v = [l.lire, l.ecrire, l.repondre];
    return { s: v.filter((x) => x === 'oui' || x === 'seule').length, a: v.filter((x) => x === 'accord').length };
  }
  function lien(id) {
    const a = AG[id], c = compte(id);
    return `<button type="button" data-res="ag-${id}" class="${sel === 'ag-' + id ? 'on' : ''}" title="Agenda « ${h(a.nom)} » — ${h(G.fournisseur(a))}">${G.sw(a.couleur, 'ag-mx-sw')}<span class="ellipsis">${h(a.nom)}</span>
      <span class="mx-mini">${c.s ? `<i class="ok">${c.s}</i>` : ''}${c.a ? `<i class="warn">${c.a}</i>` : ''}</span></button>`;
  }
  function greffer(body) {
    const nav = body.querySelector('.mx-nav'), main = body.querySelector('.mx-main');
    if (!nav || !main) return;
    const q = (document.querySelector('.screen[data-screen="outils"] [data-q]') || {}).value || '';
    const services = [...nav.querySelectorAll('.group-label')].find((x) => x.textContent.trim() === 'Services');
    const groupe = `<div class="group-label">Tes agendas</div><div class="nav-list">${IDS.map(lien).join('')}</div>`;
    if (services) services.insertAdjacentHTML('beforebegin', groupe); else nav.insertAdjacentHTML('beforeend', groupe);
    const select = main.querySelector('[data-res-select]');
    if (select) {
      const apres = [...select.options].find((o) => o.value === 'position') || select.options[select.options.length - 1];
      apres.insertAdjacentHTML('afterend', IDS.map((id) => `<option value="ag-${id}"${sel === 'ag-' + id ? ' selected' : ''}>Agenda · ${h(AG[id].nom)}</option>`).join(''));
    }
    poser(main, q);
  }
  function poser(main, q) {
    main.querySelectorAll('.ag-mx-res').forEach((x) => x.remove());
    if (sel.startsWith('ag-')) {
      main.querySelectorAll('.mx-res, .empty').forEach((x) => x.remove());
      main.closest('.mx-split').querySelectorAll('.mx-nav [data-res]').forEach((b) => b.classList.toggle('on', b.dataset.res === sel));
      const html = section(sel.slice(3), q);
      main.insertAdjacentHTML('beforeend', html || `<div class="empty">${ico('search')}<b>Aucun outil</b><p>Rien ne correspond à « ${h(q)} ».</p></div>`);
      return;
    }
    if (sel !== 'tout') return;
    const html = IDS.map((id) => section(id, q)).join('');
    if (!html) return;
    main.querySelectorAll(':scope > .empty').forEach((x) => x.remove());
    const ancre = main.querySelector('#res-position');
    if (ancre) ancre.insertAdjacentHTML('afterend', html); else main.insertAdjacentHTML('beforeend', html);
  }

  const rendu0 = O.rendu, monte0 = O.monte, recherche0 = O.recherche, notes0 = O.notes;
  O.rendu = (body, ctx) => {
    if (ctx.route !== vu) { vu = ctx.route; if (ctx.onglet === 'droits' && ctx.item && ctx.item.startsWith('ag-')) sel = ctx.item; }
    rendu0(body, ctx);
    if (ctx.onglet === 'droits') greffer(body);
  };
  O.monte = (sec) => {
    // avant l'écran Outils : il redessine dès son clic, la ressource choisie doit déjà être connue
    sec.addEventListener('click', (e) => { const b = e.target.closest('[data-res]'); if (b && sec.contains(b)) sel = b.dataset.res; }, true);
    sec.addEventListener('change', (e) => { if (e.target.matches('[data-res-select]')) sel = e.target.value; }, true);
    monte0(sec);
    sec.addEventListener('input', (e) => { if (e.target.matches('[data-q]')) { const main = sec.querySelector('.mx-main'); if (main) poser(main, e.target.value); } });
    sec.addEventListener('change', (e) => {
      const s = e.target.closest('[data-agdroit]');
      if (!s) return;
      const [id, i, col] = s.dataset.agdroit.split(':');
      const l = A.droits[id][+i];
      l[col] = s.value;
      s.className = `ag-lv ${col === 'garde' ? 'garde' : CLS[s.value] || ''}`;
      const a = AG[id];
      const quiDit = l.qui === 'toi' ? 'avec toi' : l.qui === 'elle' ? 'elle seule' : `avec ${M.who(l.qui).court}`;
      M.toast(`« ${a.nom} », ${quiDit} : ${COLS.find((c) => c[0] === col)[1].toLowerCase()} — ${libelle(col, s.value).toLowerCase()}.`, { ico: 'shield' });
    });
    M.on(sec, '[data-agdroitadd]', 'click', () => M.toast('Maquette : une ligne de plus (qui, par où, quand), placée au-dessus de « Par défaut ».', { ico: 'plus' }));
    M.on(sec, '[data-agdroitret]', 'click', (e, b) => {
      const [id, k] = b.dataset.agdroitret.split(':');
      const a = AG[id];
      A.droits[id] = A.droits[id].filter((l) => l.qui !== k);
      a.partages = a.partages.filter((p) => p[0] !== k);
      M.rafraichir();
      M.toast(`Partage retiré : ${M.who(k).court} ne voit plus « ${a.nom} ».`, { ico: 'x' });
    });
  };
  O.recherche = () => [...recherche0(), ...IDS.map((id) => ({ groupe: 'Outils', titre: `Agenda « ${AG[id].nom} » : ses droits`, sous: G.fournisseur(AG[id]), ico: 'agenda', route: '#outils/droits/ag-' + id }))];
  O.notes = (ctx) => [...notes0(ctx),
    { groupe: 'Les agendas (proposé le 2026-11-23)', statut: 'decide', titre: 'Un tableau par agenda', texte: 'comme un service : Lire ; Ajouter, modifier, supprimer (non · avec ton accord · seule) ; Répondre aux invitations (non · avec ton accord) ; Ce qu\'elle en garde ; sur des lignes Qui × Par où × Quand', src: 'output/agenda/CONCEPTION.md' },
    { statut: 'decide', titre: 'Par défaut', texte: 'avec son propriétaire en tête-à-tête : lire, ajouter avec accord ; elle seule (rappels, invitations) : lire ; personne d\'autre. Ici « Mon agenda » montre « ajouter seule », et « Travail » se ferme sur Teams' },
    { statut: 'decide', titre: 'Le partage est la seconde porte', texte: 'partager ajoute une ligne pour la personne ; le tableau dit ce que Mika fait de l\'agenda avec elle' },
    { statut: 'manque', titre: 'Les ressources « agenda »', texte: 'aucune encore : la famille agenda, ses sept outils, une ressource par agenda dans vocab/access.py (lot 3)', src: 'vocab/access.py · vocab/rights.py' },
    { statut: 'À trancher', titre: 'Régler ici, ou seulement montrer ?', texte: 'les autres ressources de cet écran ne font que montrer leur tableau (il se règle dans la console) ; un agenda est à son propriétaire, qui règle le sien ici. La maquette le propose ainsi' },
  ];
})();
