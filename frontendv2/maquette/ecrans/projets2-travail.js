/* Projets, seconde maquette — ce qui se pilote : les onglets Objectifs et Tickets d'une fiche, « Modifier le projet »
   (ses réglages, en volets) et « Nouveau projet ». Tout s'y modifie sur place : ajouter un objectif ou une mission,
   un jalon, modifier, rouvrir, retirer ; modifier un ticket. Un formulaire d'ajout s'ouvre dans un panneau à droite,
   une modification dans la zone de contenu. */
(function () {
  'use strict';
  const { h, ico, av } = M;
  const PJ = window.PJ2, S = PJ.S, A = PJ.actes, F = PJ.formes, C = PJ.champs, P = PJ.P, B = PJ.boutons;
  const obj = (p, id) => p.objectifs.find((x) => String(x.id) === String(id));
  const cleO = (x) => (typeof x.id === 'number' ? 'o' + x.id : x.id);

  /* ── Objectifs ───────────────────────────────────────────────────── */
  const VERIFS = [['une commande', 'Une commande', 'elle la lance, et la sortie fait preuve'], ['un point d\'arrêt', 'Un point d\'arrêt', 'elle s\'arrête, et c\'est toi qui valides'],
    ['un élément', 'Un élément', 'un fichier, une page, une pull request qui doit exister'], ['sa parole', 'Sa parole', 'elle dit quand c\'est fait']];
  const CADENCES = ['à chaque changement', 'toutes les 2 h', 'toutes les 24 h', 'chaque lundi', 'à ta demande seulement'];
  const jalon = (p, o, j) => {
    const [ton, lib] = PJ.etatJalon(j), d = `data-p="${p.id}" data-o="${o.id}" data-c="${j.id}"`;
    return `<li class="${ton}"><i>${ico({ done: 'check', you: 'p2-stop', work: 'play', fail: 'x' }[ton] || 'minus', 'xs')}</i><div class="p2-j">
      <div class="p2-j-top"><b>${h(j.titre)}</b>${PJ.st(ton, lib)}${j.ago != null && j.etat !== 'ouvert' ? `<time>${PJ.quand(j.ago)}</time>` : '<time></time>'}
        ${PJ.voir(p) ? '' : `<span class="p2-j-edit"><button class="btn xs icon ghost" type="button" data-p2="jalonModifier" ${d} title="Modifier le jalon">${ico('pen', 'sm')}</button><button class="btn xs icon ghost danger" type="button" data-p2="jalonRetirer" ${d} title="Retirer le jalon">${ico('trash', 'sm')}</button></span>`}</div>
      <p class="p2-j-how">Vérifié par ${h(j.verif)}${j.comment ? (j.verif === 'une commande' ? ` · <code>${h(j.comment)}</code>` : ` — ${h(j.comment)}`) : ''}</p>
      ${j.refus ? `<p class="p2-j-no">${ico('x', 'xs')}Tu l'as refusé : « ${h(j.refus)} »</p>` : ''}
      ${j.preuve ? `<details class="p2-proof"><summary>${ico('chev-right', 'xs')}La preuve${j.commit ? ` · commit <code>${j.commit.slice(0, 7)}</code>` : ''}</summary><pre>${h(j.preuve)}</pre></details>` : ''}
      ${j.etat === 'pret' && !PJ.voir(p) ? `<div class="p2-acts">${B.jalon(p, o, j)}</div>` : ''}</div></li>`;
  };
  const rendus = (l) => `<ol class="p2-tl">${l.map((r) => `<li class="${r.verdict ? r.verdict[0] : 'done'}"><time>${PJ.moment(r.ago)}</time>${r.verdict ? PJ.st(...r.verdict) : ''}<p>${h(r.texte)}</p></li>`).join('')}</ol>`;
  const champsObjectif = (x, mission, neuf) => `${neuf ? C.cartes('sorte', 'Ce que c\'est', 'ponctuel', [['ponctuel', 'Un objectif', 'il a une fin : des jalons, puis « terminé »'], ['mission', 'Une mission', 'elle revient : à une cadence, ou quand quelque chose bouge']]) : ''}
    ${C.texte('titre', mission && !neuf ? 'La mission' : 'Ce qu\'il faut atteindre', x.titre, { requis: true, ex: 'Par exemple : Créer un module RDP' })}
    <div class="si-ponctuel">${C.long('finiQuand', 'Fini quand', x.finiQuand, { rangs: 2, ex: 'Ce qui te ferait dire « c\'est fait »' })}</div>
    <div class="si-mission">${C.deux(C.choix('cadence', 'Sa cadence', x.cadence || 'toutes les 24 h', CADENCES), C.texte('declencheur', 'Ce qui la déclenche', x.declencheur, { ex: 'l\'horloge, ou ce qui bouge dans une liste' }))}
      ${C.long('chaque', 'Ce que chaque passage doit faire', x.chaque, { rangs: 3, ex: 'Par exemple : relire les sorties de la veille, corriger ce qui est faux.' })}
      ${neuf ? C.coche('tout_de_suite', 'Premier passage tout de suite', true, 'sinon, elle attend la prochaine échéance') : ''}</div>`;
  const formeObjectif = (p, x) => { const mission = !!x.cadence;
    return PJ.forme({ forme: 'objectif', data: { p: p.id, c: cleO(x), sorte: mission ? 'mission' : 'ponctuel' }, titre: mission ? 'Modifier la mission' : 'Modifier l\'objectif', sous: 'Elle lira ce changement avant son prochain passage.',
      annuler: PJ.fiche(p, 'objectifs', cleO(x)), corps: `<div class="p2-fixe ${mission ? 'mission' : 'ponctuel'}">${champsObjectif(x, mission, false)}</div>` }); };
  function detailObjectif(p, o, volet) {
    const pr = p.depot && p.depot.pulls.find((x) => x.n === o.pr), f = (...x) => PJ.fiche(p, 'objectifs', 'o' + o.id, ...x), d = `data-p="${p.id}" data-c="o${o.id}"`;
    const atteints = o.jalons.filter((j) => j.etat === 'atteint').length, lies = p.tickets.filter((t) => t.objectif === o.id);
    const v = ['rendus', 'modifier'].includes(volet) && !(volet === 'modifier' && PJ.voir(p)) ? volet : '';
    const corps = v === 'modifier' ? formeObjectif(p, o) : v === 'rendus' ? (o.rendus && o.rendus.length ? rendus(o.rendus) : `<p class="p2-none">${o.resultat ? h(o.resultat) : 'Elle n\'y a pas encore travaillé.'}</p>`)
      : `${o.besoin ? `<section class="p2-need">${PJ.parts.bulle({ de: 'mika', ago: o.ago, texte: o.besoin })}<div class="p2-answer"><textarea rows="2" data-p2-champ placeholder="Ta réponse…"></textarea>
          <button class="btn primary" type="button" data-p2="repondre" data-p="${p.id}" data-c="o${o.id}">${ico('send', 'sm')}Répondre</button></div></section>` : ''}
        ${o.jalons.length ? `<ol class="p2-jalons">${o.jalons.map((j) => jalon(p, o, j)).join('')}</ol>` : '<p class="p2-none">Pas de jalon : elle dira elle-même quand c\'est fini.</p>'}
        ${PJ.voir(p) ? '' : `<button class="p2-add" type="button" data-p2="jalonAjouter" data-p="${p.id}" data-o="${o.id}">${ico('plus', 'sm')}Ajouter un jalon</button>`}`;
    return { scroll: `obj-${p.id}-${o.id}-${v}`, lien: (k) => f(k), actif: v,
      volets: v === 'modifier' ? [['modifier', 'Modifier']] : [['', 'Jalons', `${atteints}/${o.jalons.length}`], ['rendus', 'Comptes rendus', (o.rendus || []).length]],
      tete: PJ.parts.entete({ tuile: PJ.tuile('p2-target', PJ.etatObjectif(o)[0]), sur: `Objectif n° ${o.id}`, titre: o.titre,
        meta: `${PJ.st(...PJ.etatObjectif(o))}<span>${PJ.pluriel(o.passages, 'passage', 'passages')}</span>${o.ago != null ? `<span>le dernier ${PJ.quand(o.ago)}</span>` : ''}`,
        droite: PJ.voir(p) ? '' : `${o.etat !== 'fait' ? `<button class="btn" type="button" data-p2="lancer" data-p="${p.id}" data-c="${h(o.titre)}">${ico('play', 'sm')}<span class="lbl">Lancer maintenant</span></button>` : ''}
          <a class="btn${v === 'modifier' ? ' on' : ''}" href="${f(v === 'modifier' ? '' : 'modifier')}">${ico('pen', 'sm')}Modifier</a>` }),
      corps,
      cote: PJ.sc('Fini quand', `<p class="p2-sc-text">${h(o.finiQuand || 'Rien de dit : elle jugera elle-même.')}</p>`)
        + PJ.sc('Où il en est', `<div class="p2-prog big">${PJ.barre(PJ.tonsJalons(o))}<span>${o.jalons.length ? `${atteints} / ${PJ.pluriel(o.jalons.length, 'jalon', 'jalons')}` : 'pas de jalon'}</span></div>`
          + PJ.props([['État', PJ.st(...PJ.etatObjectif(o))], ['Passages', String(o.passages)], o.ago != null ? ['Dernier passage', PJ.moment(o.ago)] : null, o.resultat ? ['Résultat', h(o.resultat)] : null]))
        + PJ.sc('Branche et pull request', o.branche ? `<p class="p2-branchline">${ico('p2-branch', 'sm')}<code>${h(o.branche)}</code>${ico('chev-right', 'xs')}<code>main</code></p>${PJ.parts.prLiee(p, pr)}` : '')
        + PJ.sc('Tickets liés', lies.map((t) => PJ.lie(PJ.fiche(p, 'tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#' + t.n, PJ.st(...PJ.etatTicket(t)))).join(''))
        + (PJ.voir(p) ? '' : PJ.sc('Gérer', `<div class="p2-decide">${o.etat === 'fait' ? `<button class="btn" type="button" data-p2="objectifRouvrir" ${d}>${ico('refresh', 'sm')}Rouvrir l'objectif</button>`
          : `<button class="btn" type="button" data-p2="objectifTerminer" ${d}>${ico('check', 'sm')}Le dire terminé</button>`}<button class="btn danger" type="button" data-p2="objectifRetirer" ${d}>${ico('trash', 'sm')}Retirer l'objectif</button></div>`)) };
  }
  function detailMission(p, m, volet) {
    const f = (...x) => PJ.fiche(p, 'objectifs', m.id, ...x), v = volet === 'modifier' && !PJ.voir(p) ? 'modifier' : '', d = `data-p="${p.id}" data-c="${m.id}"`;
    return { scroll: `mis-${p.id}-${m.id}-${v}`, lien: (k) => f(k), actif: v, volets: v ? [['modifier', 'Modifier']] : [['', 'Derniers passages', m.derniers.length]],
      tete: PJ.parts.entete({ tuile: PJ.tuile('refresh', 'work'), sur: 'Mission', titre: m.titre, meta: `${PJ.st('work', 'en cours')}<span>${PJ.pluriel(m.passages, 'passage', 'passages')}</span>${m.ago != null ? `<span>le dernier ${PJ.quand(m.ago)}</span>` : ''}`,
        droite: PJ.voir(p) ? '' : `<button class="btn" type="button" data-p2="lancer" data-p="${p.id}" data-c="${h(m.titre)}">${ico('play', 'sm')}<span class="lbl">Lancer maintenant</span></button><a class="btn${v ? ' on' : ''}" href="${f(v ? '' : 'modifier')}">${ico('pen', 'sm')}Modifier</a>` }),
      corps: v ? formeObjectif(p, m) : `<p class="p2-when"><b>À chaque passage</b>${h(m.chaque || 'Rien de précisé.')}</p>${m.derniers.length ? rendus(m.derniers) : '<p class="p2-none">Elle n\'est pas encore passée.</p>'}`,
      cote: PJ.sc('Son rythme', PJ.props([['Cadence', h(m.cadence)], ['Ce qui la déclenche', h(m.declencheur || '—')], ['Passages', String(m.passages)], m.ago != null ? ['Le dernier', PJ.moment(m.ago)] : null]))
        + (PJ.voir(p) ? '' : PJ.sc('Gérer', `<div class="p2-decide"><button class="btn danger" type="button" data-p2="objectifRetirer" ${d}>${ico('trash', 'sm')}Retirer la mission</button></div>`)) };
  }
  /* La bascule de l'onglet : la liste et son détail, ou le diagramme (projets2-diagramme.js). */
  PJ.parts.vueObjectifs = (p, vue) => `<div class="seg p2-mode" title="La vue des objectifs"><a href="${PJ.fiche(p, 'objectifs')}" aria-pressed="${vue === 'liste'}">${ico('menu', 'sm')}Liste</a><a href="${PJ.fiche(p, 'objectifs', 'diagramme')}" aria-pressed="${vue === 'diagramme'}">${ico('sort', 'sm')}Diagramme</a></div>`;
  PJ.parts.coteObjectif = (p, x) => (x.cadence ? detailMission(p, x, '') : detailObjectif(p, x, '')).cote;
  PJ.parts.jalonVerifie = (j) => `Vérifié par ${h(j.verif)}${j.comment ? (j.verif === 'une commande' ? ` · <code>${h(j.comment)}</code>` : ` — ${h(j.comment)}`) : ''}`;
  PJ.onglets.objectifs = (p, rest) => {
    const groupes = [['cours', 'En cours', p.objectifs.filter((o) => o.etat !== 'fait')], ['missions', 'Missions', p.missions], ['faits', 'Terminés', p.objectifs.filter((o) => o.etat === 'fait')]];
    const vus = groupes.filter(([k]) => S.of === 'tous' || S.of === k), tous = vus.flatMap((g) => g[2]);
    const x = (rest[0] && [...p.objectifs, ...p.missions].find((o) => cleO(o) === rest[0])) || PJ.choisi(tous, cleO, rest[0]);
    /* Une ligne par objectif, serrée : un point à la couleur de son état, son titre, puis — alignés d'une ligne à l'autre —
       sa barre de jalons, « 1/4 » et son âge en court ; une mission dit sa cadence à la place de la barre. */
    const age = (ago) => (ago == null ? '' : PJ.quand(ago).replace(/^il y a /, ''));
    const ligne = (o) => (o.cadence ? `<a class="p2-orow mission" href="${PJ.fiche(p, 'objectifs', o.id)}" aria-selected="${o === x}" title="${h(o.titre)} — ${h(o.cadence)}, ${h(o.declencheur || '')}"><i class="work"></i><span class="p2-orow-t">${h(o.titre)}</span>
        <span class="p2-orow-c">${h(o.cadence)}</span><time>${age(o.ago)}</time></a>`
      : `<a class="p2-orow${(o.jalons || []).some((j) => j.etat === 'pret') || o.besoin ? ' atoi' : ''}" href="${PJ.fiche(p, 'objectifs', 'o' + o.id)}" aria-selected="${o === x}" title="${h(o.titre)} — ${PJ.etatObjectif(o)[1]}"><i class="${PJ.etatObjectif(o)[0]}"></i><span class="p2-orow-t">${h(o.titre)}</span>
        ${o.jalons.length ? `${PJ.barre(PJ.tonsJalons(o))}<span class="num">${o.jalons.filter((j) => j.etat === 'atteint').length}/${o.jalons.length}</span>` : '<span class="p2-orow-c">sans jalon</span>'}<time>${age(o.ago)}</time></a>`);
    if (rest[0] === 'diagramme') return PJ.diagramme(p, rest.slice(1));
    const liste = `<div class="p2-tools">${PJ.parts.vueObjectifs(p, 'liste')}<span class="grow"></span>${PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="objectifAjouter" data-p="${p.id}">${ico('plus', 'sm')}<span>Ajouter un objectif</span></button>`}</div>
      <div class="p2-filters">${groupes.map(([k, lib, l]) => [k, lib, l.length]).map(([k, lib, n]) =>
        `<button type="button" data-p2="filtreObjectifs" data-c="${k}" aria-pressed="${S.of === k}">${lib}<span class="cnt">${n}</span></button>`).join('')}</div>
      <div class="pane-scroll p2-olist" data-scroll="obj-liste">${tous.length ? vus.filter((g) => g[2].length).map(([, lib, l]) => `<div class="group-label">${lib}<span class="cnt">${l.length}</span></div>${l.map(ligne).join('')}`).join('') : PJ.vide('p2-target', 'Rien ici', 'Aucun objectif pour ce filtre.')}</div>`;
    return PJ.trio(Object.assign({ cls: 'p2-obj', liste, ouvert: !!rest[0] && !!x, retour: [PJ.fiche(p, 'objectifs'), 'Objectifs'] },
      x ? (x.cadence ? detailMission(p, x, rest[1]) : detailObjectif(p, x, rest[1])) : { vide: PJ.vide('p2-target', 'Pas encore d\'objectif', 'Un objectif a une fin ; une mission revient. Ajoute le premier, ou laisse-la les proposer dans son plan.',
        PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="objectifAjouter" data-p="${p.id}">${ico('plus', 'sm')}Ajouter un objectif</button>`) }));
  };
  A.objectifAjouter = (d) => PJ.tiroir({ titre: 'Ajouter un objectif', sous: 'Un objectif ponctuel, ou une mission qui revient.', forme: 'objectif', data: { p: d.p }, bouton: 'Ajouter', corps: champsObjectif({}, false, true) });
  F.objectif = (v, d) => {
    const p = PJ.proj(d.p), mission = (d.sorte || v.sorte) === 'mission';
    if (d.c) {
      const x = mission ? p.missions.find((m) => m.id === d.c) : obj(p, d.c.slice(1));
      Object.assign(x, mission ? { titre: v.titre, cadence: v.cadence, declencheur: v.declencheur, chaque: v.chaque } : { titre: v.titre, finiQuand: v.finiQuand });
      M.toast(mission ? 'Mission modifiée.' : 'Objectif modifié.'); M.go(PJ.fiche(p, 'objectifs', d.c));
      return true;
    }
    if (mission) {
      const id = 'm' + (Math.max(0, ...p.missions.map((m) => Number(m.id.slice(1)))) + 1), tout = v.tout_de_suite != null;
      p.missions.push({ id, titre: v.titre, cadence: v.cadence, declencheur: v.declencheur || 'l\'horloge', passages: 0, ago: tout ? 0 : null, chaque: v.chaque, derniers: tout ? [{ ago: 0, verdict: ['work', 'en cours'], texte: 'Premier passage lancé à l\'instant.' }] : [] });
      S.of = 'tous'; PJ.geste(p, `Tu as ajouté la mission « ${v.titre} »`, 'refresh', ['objectifs', id]); M.toast(`Mission ajoutée${tout ? ' : son premier passage part tout de suite' : ''}.`, { mika: true }); M.go(PJ.fiche(p, 'objectifs', id));
    } else {
      const id = Math.max(0, ...p.objectifs.map((o) => o.id)) + 1;
      p.objectifs.push({ id, titre: v.titre, etat: 'a_venir', finiQuand: v.finiQuand, passages: 0, jalons: [], rendus: [] });
      S.of = 'tous'; PJ.geste(p, `Tu as ajouté l'objectif « ${v.titre} »`, 'p2-target', ['objectifs', 'o' + id], { objectif: id }); M.toast('Objectif ajouté : ajoute ses jalons, ou laisse-la les proposer.', { mika: true }); M.go(PJ.fiche(p, 'objectifs', 'o' + id));
    }
    return true;
  };
  A.objectifRouvrir = (d) => { const p = PJ.proj(d.p), o = obj(p, d.c.slice(1)); o.etat = 'en_cours'; o.rendus.unshift({ ago: 0, texte: 'Tu as rouvert l\'objectif.' }); PJ.geste(p, `Tu as rouvert l'objectif « ${o.titre} »`, 'refresh', ['objectifs', d.c], { objectif: o.id });
    PJ.redessiner(); M.toast('Objectif rouvert : elle le reprend à son prochain passage.', { mika: true }); };
  A.objectifTerminer = (d) => { const p = PJ.proj(d.p), o = obj(p, d.c.slice(1)); Object.assign(o, { etat: 'fait', ago: 0, resultat: o.resultat || 'Dit terminé par toi.' }); o.rendus.unshift({ ago: 0, texte: 'Tu as dit l\'objectif terminé.' });
    PJ.redessiner(); M.toast('Objectif terminé.'); };
  A.objectifRetirer = (d) => { const p = PJ.proj(d.p), mission = d.c[0] === 'm', x = mission ? p.missions.find((m) => m.id === d.c) : obj(p, d.c.slice(1));
    PJ.confirmer({ titre: mission ? 'Retirer la mission ?' : 'Retirer l\'objectif ?', bouton: 'Retirer', danger: true, ico: 'trash',
      corps: `<p><b>${h(x.titre)}</b> sort du projet : elle n'y travaillera plus. ${mission ? 'Ses passages restent dans l\'activité.' : 'Sa branche, sa pull request et ses comptes rendus restent là où ils sont.'}</p>`,
      alors: () => { if (mission) p.missions = p.missions.filter((m) => m !== x); else p.objectifs = p.objectifs.filter((o) => o !== x); M.toast(mission ? 'Mission retirée.' : 'Objectif retiré.', { ico: 'trash' }); M.go(PJ.fiche(p, 'objectifs')); } }); };
  const tiroirJalon = (p, o, j) => PJ.tiroir({ titre: j ? 'Modifier le jalon' : 'Ajouter un jalon', sous: `Objectif n° ${o.id} · ${o.titre}`, forme: 'jalon', data: { p: p.id, o: o.id, c: j ? j.id : '' }, bouton: j ? 'Enregistrer' : 'Ajouter',
    corps: `${C.texte('titre', 'Ce qui doit être vrai', j ? j.titre : '', { requis: true, ex: 'Par exemple : La connexion aboutit sur l\'hôte d\'essai' })}
      ${C.cartes('verif', 'Comment on le vérifie', j ? j.verif : 'une commande', VERIFS)}${C.texte('comment', 'La commande, ou ce qu\'il faut regarder', j ? j.comment : '', { ex: 'pytest tests/test_rdp.py -k connect' })}` });
  A.jalonAjouter = (d) => { const p = PJ.proj(d.p); tiroirJalon(p, obj(p, d.o), null); };
  A.jalonModifier = (d) => { const p = PJ.proj(d.p), o = obj(p, d.o); tiroirJalon(p, o, o.jalons.find((j) => String(j.id) === d.c)); };
  F.jalon = (v, d) => {
    const p = PJ.proj(d.p), o = obj(p, d.o), j = d.c && o.jalons.find((x) => String(x.id) === d.c);
    if (j) Object.assign(j, { titre: v.titre, verif: v.verif, comment: v.comment });
    else { o.jalons.push({ id: Math.max(0, ...o.jalons.map((x) => x.id)) + 1, titre: v.titre, verif: v.verif, comment: v.comment, etat: 'ouvert' }); if (o.etat === 'fait') o.etat = 'en_cours'; }
    PJ.redessiner(); M.toast(j ? 'Jalon modifié.' : 'Jalon ajouté.');
  };
  A.jalonRetirer = (d) => { const p = PJ.proj(d.p), o = obj(p, d.o), j = o.jalons.find((x) => String(x.id) === d.c);
    PJ.confirmer({ titre: 'Retirer le jalon ?', bouton: 'Retirer', danger: true, ico: 'trash', corps: `<p><b>${h(j.titre)}</b> sort de l'objectif n° ${o.id}.${j.preuve ? ' Sa preuve reste dans le commit.' : ''}</p>`,
      alors: () => { o.jalons = o.jalons.filter((x) => x !== j); PJ.redessiner(); M.toast('Jalon retiré.', { ico: 'trash' }); } }); };

  /* ── Tickets ─────────────────────────────────────────────────────── */
  const PRIO = { haute: ['fail', 'haute'], normale: ['wait', 'normale'], basse: ['wait', 'basse'] };
  /* L'historique d'un ticket : ce que disent ses données, puis ce que les gestes de l'écran y ajoutent. */
  function histo(p, t) {
    const q = PJ.qui(t.par), pr = p.depot && p.depot.pulls.find((x) => x.n === t.pr), elle = t.fil.find((m) => m.de === 'mika');
    const l = [{ ago: t.fil[0].ago, texte: `${t.par === 'adrien' ? 'Tu as' : h(q.nom) + ' a'} ouvert le ticket`, ico: 'p2-ticket', ton: 'wait' }];
    if (t.issue) l.push({ ago: t.fil[0].ago - 1, texte: `Lié à l'issue n° ${t.issue} du dépôt`, ico: 'p2-issue', ton: 'wait' });
    if (elle && t.etape !== 'non_lu') l.push({ ago: Math.max(elle.ago, pr ? pr.ago + 40 : 0), texte: 'Mika l\'a lu et pris en analyse', ico: 'eye', ton: 'work' });
    if (t.plan) l.push({ ago: pr ? pr.ago + 30 : t.ago, texte: 'Mika a écrit son plan', ico: 'p2-plan', ton: 'work' });
    if (t.plan && t.plan.etat === 'valide' && pr) l.push({ ago: pr.ago + 12, texte: 'Tu as validé son plan', ico: 'check', ton: 'done' });
    if (pr) l.push({ ago: pr.ago, texte: `Mika a ouvert la pull request n° ${pr.n}`, ico: 'p2-pr', ton: 'work' });
    if (pr && pr.fusionAgo != null && pr.fusionAgo > 0) l.push({ ago: pr.fusionAgo, texte: `Tu as fusionné la pull request n° ${pr.n} : ticket traité`, ico: 'p2-merge', ton: 'done' });
    if (t.question) l.push({ ago: t.ago, texte: 'Mika t\'a posé une question', ico: 'p2-question', ton: 'you' });
    (t.histo || []).forEach((x) => l.push({ ago: x.ago, texte: x.texte, ico: x.ico, ton: x.ico === 'x' ? 'fail' : 'done' }));
    return l.sort((a, b) => a.ago - b.ago);
  }
  function detailTicket(p, t, volet) {
    const q = PJ.qui(t.par), f = (...x) => PJ.fiche(p, 'tickets', t.n, ...x), voir = PJ.voir(p);
    const o = p.objectifs.find((x) => x.id === t.objectif), pr = p.depot && p.depot.pulls.find((x) => x.n === t.pr), issue = p.depot && p.depot.issues.find((x) => x.n === t.issue);
    const defaut = t.attend === 'plan' ? 'plan' : t.attend === 'question' || t.attend === 'accepter' ? 'fil' : 'description';
    const v = ['description', 'plan', 'fil', 'historique', 'modifier'].includes(volet) && !(volet === 'modifier' && voir) ? volet : defaut, hi = histo(p, t);
    const gestes = voir ? '' : t.attend === 'plan' ? B.plan(p, 't' + t.n) : t.attend === 'accepter' ? B.ticket(p, t.n) : t.attend === 'fusion' && pr ? B.fusion(p, pr) : '';
    let corps = '', pied = '';
    if (v === 'modifier') corps = PJ.forme({ forme: 'ticket', data: { p: p.id, c: t.n }, titre: `Modifier le ticket #${t.n}`, sous: 'Le titre, la sorte, la priorité et la description. Son fil et son plan ne changent pas.', annuler: f(),
      corps: `${C.texte('titre', 'Titre', t.titre, { requis: true })}${C.deux(C.choix('sorte', 'Sorte', t.sorte, ['évolution', 'bug', 'question']), C.choix('prio', 'Priorité', t.prio, [['haute', 'Haute'], ['normale', 'Normale'], ['basse', 'Basse']]))}
        ${C.choix('objectif', 'Objectif lié', t.objectif || '', [['', 'aucun'], ...p.objectifs.map((x) => [x.id, `n° ${x.id} · ${x.titre}`])])}
        ${C.long('desc', 'Description', t.desc || t.fil[0].texte, { rangs: 12, mono: true, aide: 'En Markdown : des titres (##), des listes (-), du `code`.' })}` });
    else if (v === 'description') corps = `<div class="p2-md court">${PJ.md(t.desc || t.fil[0].texte, {})}</div>`;
    else if (v === 'plan') corps = t.plan ? PJ.parts.plan(p, t.plan, t.attend === 'plan' && !voir)
      : `<div class="p2-nothing">${ico('p2-plan')}<b>Pas encore de plan</b><p>${t.attend === 'question' ? 'Elle attend ta réponse à sa question avant de l\'écrire.' : t.attend === 'accepter' ? 'Elle n\'y touche pas tant que le ticket n\'est pas accepté.' : t.etape === 'ecarte' ? 'Le ticket est écarté.' : 'Elle l\'écrira en analysant le ticket.'}</p>
        ${t.attend === 'question' ? `<a class="btn" href="${f('fil')}">Lire sa question${ico('chev-right', 'sm')}</a>` : ''}</div>`;
    else if (v === 'fil') { corps = `${t.attend === 'accepter' ? `<p class="p2-banner you">${ico('p2-ticket', 'sm')}<span>Ticket proposé depuis une issue d'un inconnu : elle n'y touche pas tant que tu ne l'as pas accepté.</span></p>` : ''}<div class="p2-thread">${t.fil.map(PJ.parts.bulle).join('')}</div>`;
      pied = voir ? '' : `<div class="p2-note"><textarea rows="2" data-p2-champ placeholder="${t.attend === 'question' ? 'Ta réponse à sa question…' : 'Écrire une note dans le fil…'}"></textarea>
        <button class="btn primary" type="button" data-p2="${t.attend === 'question' ? 'repondre' : 'noter'}" data-p="${p.id}" data-c="${t.attend === 'question' ? 't' + t.n : t.n}">${ico('send', 'sm')}${t.attend === 'question' ? 'Répondre' : 'Ajouter la note'}</button></div>`; }
    else corps = `<ol class="p2-tl histo">${hi.map((x) => `<li class="${x.ton}"><time>${PJ.moment(x.ago)}</time><p>${ico(x.ico || 'check', 'xs')}${x.texte}</p></li>`).join('')}</ol>`;
    return { scroll: `tic-${p.id}-${t.n}-${v}`, lien: (k) => f(k === defaut ? '' : k), actif: v, pied,
      volets: v === 'modifier' ? [['modifier', 'Modifier']] : [['description', 'Description'], ['plan', 'Plan', t.plan ? null : 0], ['fil', 'Fil', t.fil.length], ['historique', 'Historique', hi.length]],
      tete: PJ.parts.entete({ num: '#' + t.n, titre: t.titre,
        meta: `${PJ.st(...PJ.etatTicket(t))}<span class="p2-kind">${h(t.sorte)}</span><span class="p2-by">${q.av('xs')}ouvert par ${h(q.nom)}</span><span>${PJ.quand(t.fil[0].ago)}</span>${t.ailleurs ? PJ.st('out', 'venu d\'ailleurs') : ''}`,
        droite: `${gestes}${voir ? '' : `<a class="btn${v === 'modifier' ? ' on' : ''}" href="${f(v === 'modifier' ? '' : 'modifier')}">${ico('pen', 'sm')}Modifier</a>`}` }),
      corps,
      cote: PJ.sc('Son parcours', PJ.parts.parcours(t))
        + PJ.sc('En bref', PJ.props([['La main', t.main === 'toi' ? `<span class="p2-by">${av('adrien', 'xs')}à toi</span>` : t.main === 'elle' ? `<span class="p2-by">${av('mika', 'xs')}à elle</span>` : '<span class="muted">à personne</span>'],
          ['Priorité', `<span class="p2-prio ${t.prio}">${ico('flag', 'xs')}${PRIO[t.prio][1]}</span>`], ['Sorte', h(t.sorte)], ['Ouvert par', `<span class="p2-by">${q.av('xs')}${h(q.nom)}</span>`], ['Mis à jour', PJ.moment(t.ago)]]))
        + PJ.sc('Ce qui est lié', (o ? PJ.lie(PJ.fiche(p, 'objectifs', 'o' + o.id), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))) : '') + PJ.parts.prLiee(p, pr)
          + (issue ? PJ.lie(PJ.fiche(p, 'code', 'issues', issue.n), 'p2-issue', issue.etat === 'ouverte' ? 'wait' : 'done', issue.titre, `issue n° ${issue.n}`, PJ.st(issue.etat === 'ouverte' ? 'wait' : 'done', issue.etat === 'ouverte' ? 'ouverte' : 'fermée')) : '')
          || '<p class="p2-none">Ni objectif, ni pull request, ni issue pour l\'instant.</p>') };
  }
  PJ.onglets.tickets = (p, rest) => {
    const q = M.norm(S.tq);
    const l = p.tickets.filter((t) => (S.tf === 'tous' || (S.tf === 'toi' ? t.main === 'toi' : !['traite', 'ecarte'].includes(t.etape))) && (!q || M.norm(`#${t.n} ${t.titre} ${t.sorte}`).includes(q)));
    const t = (rest[0] && p.tickets.find((x) => String(x.n) === rest[0])) || PJ.choisi(l, (x) => x.n, rest[0]);
    const liste = `<div class="p2-tools"><label class="search grow">${ico('search', 'sm')}<input type="search" placeholder="Chercher…" data-p2-saisie="tickets" value="${h(S.tq)}"></label>
        ${PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="nouveauTicket" data-p="${p.id}">${ico('plus', 'sm')}<span>Nouveau ticket</span></button>`}</div>
      <div class="p2-filters">${[['toi', 'À toi', p.tickets.filter((x) => x.main === 'toi').length], ['ouverts', 'Ouverts', PJ.ouverts(p).length], ['tous', 'Tous', p.tickets.length]].map(([k, lib, n]) =>
        `<button type="button" data-p2="filtreTickets" data-c="${k}" aria-pressed="${S.tf === k}">${lib}<span class="cnt">${n}</span></button>`).join('')}</div>
      <div class="pane-scroll" data-scroll="tic-liste">${l.length ? l.map((x) => `<a class="li p2-row${x.main === 'toi' ? ' atoi' : ''}" href="${PJ.fiche(p, 'tickets', x.n)}" aria-selected="${x === t}"><span class="p2-tnum">#${x.n}</span>
        <span class="li-main"><span class="li-title">${h(x.titre)}</span><span class="p2-row-sub">${PJ.st(...PJ.etatTicket(x))}${x.prio === 'haute' ? `<span class="p2-prio haute" title="Priorité haute">${ico('flag', 'xs')}haute</span>` : ''}<time>${PJ.quand(x.ago)}</time></span></span></a>`).join('')
        : PJ.vide('p2-ticket', p.tickets.length ? 'Aucun ticket ici' : 'Pas encore de ticket', p.tickets.length ? 'Change de filtre, ou efface la recherche.' : 'Un ticket est une demande précise : un bug, une évolution, une question.')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!t, retour: [PJ.fiche(p, 'tickets'), 'Tickets'] }, t ? detailTicket(p, t, rest[1]) : { vide: PJ.vide('p2-ticket', 'Choisis un ticket', 'Sa description, son plan, son fil et son historique s\'ouvrent ici.') }));
  };
  A.nouveauTicket = (d) => { const p = PJ.proj(d.p);
    PJ.tiroir({ titre: 'Nouveau ticket', sous: p.titre, forme: 'ticket', data: { p: p.id }, bouton: 'Ouvrir le ticket',
      corps: `${C.texte('titre', 'Titre', '', { requis: true, ex: 'Ce qu\'il faut faire, en une ligne' })}${C.deux(C.choix('sorte', 'Sorte', 'évolution', ['évolution', 'bug', 'question']), C.choix('prio', 'Priorité', 'normale', [['haute', 'Haute'], ['normale', 'Normale'], ['basse', 'Basse']]))}
        ${C.choix('objectif', 'Objectif lié', '', [['', 'aucun'], ...p.objectifs.map((x) => [x.id, `n° ${x.id} · ${x.titre}`])])}${C.long('desc', 'Ce que tu attends', '', { rangs: 8, ex: 'Le contexte, ce qui te ferait dire « c\'est fait »…' })}` }); };
  F.ticket = (v, d) => {
    const p = PJ.proj(d.p), objectif = v.objectif ? Number(v.objectif) : undefined;
    if (d.c) { const t = p.tickets.find((x) => String(x.n) === d.c); Object.assign(t, { titre: v.titre, sorte: v.sorte, prio: v.prio, desc: v.desc, objectif }); (t.histo = t.histo || []).push({ ago: 0, texte: 'Tu as modifié le ticket', ico: 'pen' });
      M.toast(`Ticket #${t.n} modifié.`); M.go(PJ.fiche(p, 'tickets', t.n, 'description')); return true; }
    const n = Math.max(0, ...p.tickets.map((t) => t.n)) + 1;
    p.tickets.unshift({ n, titre: v.titre, sorte: v.sorte, prio: v.prio, objectif, desc: v.desc || v.titre, etape: 'non_lu', main: 'elle', attend: null, par: 'adrien', ago: 0, fil: [{ de: 'adrien', ago: 0, texte: v.desc || v.titre }] });
    S.tf = 'ouverts'; S.tq = ''; PJ.geste(p, `Tu as ouvert le ticket #${n} : ${v.titre}`, 'p2-ticket', ['tickets', n], { ticket: n });
    M.toast(`Ticket #${n} ouvert : elle le lira à son prochain passage.`, { mika: true }); M.go(PJ.fiche(p, 'tickets', n));
    return true;
  };

  /* ── Modifier le projet : ses réglages, en volets ────────────────── */
  const MODES = [['autonome', 'Elle avance seule', 'elle travaille à son rythme et s\'arrête aux points d\'arrêt'], ['valide', 'Elle te soumet chaque plan', 'rien ne commence sans ta validation'], ['main', 'Seulement quand tu la lances', 'aucun passage de sa propre initiative']];
  const RYTHMES = [['continu', 'Dès qu\'il y a du travail'], ['2h', 'Toutes les 2 heures'], ['jour', 'Une fois par jour'], ['semaine', 'Une fois par semaine']];
  const JOURS = [['lun', 'Lun'], ['mar', 'Mar'], ['mer', 'Mer'], ['jeu', 'Jeu'], ['ven', 'Ven'], ['sam', 'Sam'], ['dim', 'Dim']];
  const SORTIES = [['branche', 'Pousser sur une branche du dépôt'], ['pr', 'Ouvrir une pull request'], ['commentaire', 'Commenter chez l\'hôte (issue, pull request)'], ['issue', 'Ouvrir une issue chez l\'hôte'], ['mail', 'Envoyer un mail'], ['doc', 'Écrire dans la documentation']];
  const ACCORDS = [['libre', 'Sans accord'], ['accord', 'Avec ton accord'], ['jamais', 'Jamais']];
  const OUTILS = [['depot', 'Le dépôt git', 'lire, écrire sur ses branches'], ['bac', 'Le bac à sable', 'lancer des commandes, les tests'], ['web', 'La recherche sur le web', 'lire des pages, sans rien envoyer'], ['doc', 'L\'espace de documentation', 'lire et écrire ses pages'],
    ['tickets', 'Les tickets et les listes', 'les lire, y répondre, en proposer'], ['mail', 'Ton courrier', 'en lecture seule'], ['teams', 'Teams', 'en lecture seule']];
  PJ.reglages = (p) => (p.reglages = p.reglages || { mode: 'valide', cadence: 'jour', de: '08:00', a: '20:00', jours: ['lun', 'mar', 'mer', 'jeu', 'ven'], relecture: 'elle', relectureToi: false,
    sorties: { branche: 'libre', pr: 'libre', commentaire: 'accord', issue: 'accord', mail: 'accord', doc: 'libre' }, flux: 'pr', brancheNom: 'objectif-<n>-<titre>', protegee: true, outils: ['web', 'tickets'] });
  const lib = (table, k) => (table.find((x) => x[0] === k) || table[0])[1];
  PJ.rythme = (p) => { const r = PJ.reglages(p); return r.mode === 'main' ? 'Elle n\'y passe que lorsque tu la lances.' : `${lib(RYTHMES, r.cadence)}, ${r.jours.length === 7 ? 'tous les jours' : r.jours.length === 5 && !r.jours.includes('sam') && !r.jours.includes('dim') ? 'du lundi au vendredi' : 'le ' + r.jours.join(', ')}, entre ${r.de} et ${r.a}.`; };
  PJ.onglets.reglages = (p, rest) => {
    if (PJ.voir(p)) return PJ.vide('lock', 'Ce projet t\'est ouvert pour le voir', 'Ses réglages appartiennent à ' + p.pour + '.');
    const r = PJ.reglages(p), f = (...x) => PJ.fiche(p, 'reglages', ...x), volets = [['general', 'Général', 'flag'], ['rythme', 'Rythme', 'clock'], ['accords', 'Accords et relecture', 'shield-check'], ['depot', 'Dépôt', 'code'], ['outils', 'Outils et services', 'tools']];
    const v = volets.some((x) => x[0] === rest[0]) ? rest[0] : 'general';
    const dit = { general: lib(MODES, r.mode), rythme: PJ.rythme(p), accords: `${SORTIES.filter(([k]) => r.sorties[k] === 'accord').length} sorties sur ton accord · ${r.relecture === 'elle' ? 'elle se relit' : 'sans relecture'}`, depot: p.depot ? p.depot.hote : 'pas de dépôt', outils: PJ.pluriel(r.outils.length, 'outil', 'outils') };
    const liste = `<div class="pane-head"><h2>Ce qui se règle</h2></div><div class="pane-scroll" data-scroll="reglages">${volets.map(([k, l, i]) => `<a class="li p2-row" href="${f(k)}" aria-selected="${k === v}">${PJ.tuile(i)}<span class="li-main"><span class="li-title">${l}</span><span class="p2-row-sub"><span class="ellipsis">${h(dit[k])}</span></span></span></a>`).join('')}</div>`;
    const forme = (titre, sous, corps) => PJ.forme({ forme: 'projet', data: { p: p.id, volet: v }, titre, sous, annuler: PJ.fiche(p), corps });
    const corps = v === 'general' ? forme('Le projet', 'Son nom, ce qu\'il doit devenir, et la façon dont elle le mène.', `${C.texte('titre', 'Son nom', p.titre, { requis: true })}${C.long('resume', 'Sa description', p.resume, { rangs: 3 })}${C.cartes('mode', 'Comment elle le mène', r.mode, MODES)}`)
      : v === 'rythme' ? forme('Son rythme', 'Quand elle y travaille. Hors de cette plage, elle n\'y passe que si tu la lances.', `${C.choix('cadence', 'Elle y passe', r.cadence, RYTHMES)}${C.deux(C.texte('de', 'Plage de travail : de', r.de, { type: 'time' }), C.texte('a', 'à', r.a, { type: 'time' }))}
          <fieldset class="p2-days"><legend>Les jours</legend><div>${JOURS.map(([k, l]) => `<label><input type="checkbox" name="jours" value="${k}"${r.jours.includes(k) ? ' checked' : ''}><span>${l}</span></label>`).join('')}</div></fieldset>`)
      : v === 'accords' ? forme('Ce qui sort, et la relecture', 'Ce qu\'elle peut faire sortir du projet seule, et ce qui attend ton accord dans « À faire ».', `${C.groupe('Ce qui sort', `<div class="p2-matrix">${SORTIES.map(([k, l]) => `<label><span>${l}</span><select name="sortie_${k}">${ACCORDS.map(([a, al]) => `<option value="${a}"${r.sorties[k] === a ? ' selected' : ''}>${al}</option>`).join('')}</select></label>`).join('')}</div>`)}
          ${C.cartes('relecture', 'La relecture', r.relecture, [['elle', 'Elle se relit', 'une relecture à part avant chaque pull request'], ['aucune', 'Pas de relecture', 'elle ouvre la pull request dès que les tests passent']])}${C.coche('relectureToi', 'Je relis aussi avant la fusion', r.relectureToi, 'une pull request n\'est « prête » qu\'après ta relecture')}`)
      : v === 'depot' ? (p.depot ? forme('Le dépôt et son flux', 'Où vit le code, et comment il y entre.', `${C.deux(C.texte('hote', 'Chez l\'hôte', p.depot.hote, { requis: true }), C.texte('defaut', 'Branche par défaut', p.depot.defaut, { requis: true }))}
          ${C.cartes('flux', 'Comment le code entre', r.flux, [['pr', 'Par une pull request', 'une branche par objectif ou par ticket ; tu fusionnes'], ['direct', 'Directement', 'elle pousse sur la branche par défaut']])}
          ${C.texte('brancheNom', 'Le nom de ses branches', r.brancheNom, { aide: '<n> : le numéro de l\'objectif ou du ticket ; <titre> : son titre abrégé.' })}${C.coche('protegee', 'Elle ne pousse jamais sur la branche par défaut', r.protegee, 'même pour un correctif d\'une ligne')}`)
        : '<div class="p2-nothing">' + ico('code') + '<b>Ce projet n\'a pas de dépôt</b><p>Il ne produit pas de code : ni fichiers, ni commits, ni pull requests.</p></div>')
      : forme('Ses outils et services', 'Ce dont elle peut se servir quand elle travaille sur ce projet.', `<div class="p2-checks-grid">${OUTILS.map(([k, l, s]) => C.coche('outils', l, r.outils.includes(k), s, k)).join('')}</div>`);
    return PJ.trio({ liste, ouvert: !!rest[0], retour: [f(), 'Modifier le projet'], volets: [[v, volets.find((x) => x[0] === v)[1]]], actif: v, lien: (k) => f(k), scroll: `reglages-${p.id}-${v}`, corps,
      tete: PJ.parts.entete({ tuile: PJ.tuile('settings'), sur: 'Modifier le projet', titre: p.titre, meta: `${PJ.st(...PJ.etatProjet(p))}<span>${p.pour === 'toi' ? 'à toi' : 'de ' + h(p.pour)} · menée par ${h(p.mene)}</span>`,
        droite: `<a class="btn" href="${PJ.fiche(p)}">${ico('x', 'sm')}Fermer</a>` }),
      cote: PJ.sc('En bref', PJ.props([['Mode', h(lib(MODES, r.mode))], ['Rythme', h(PJ.rythme(p))], ['Relecture', r.relecture === 'elle' ? `elle se relit${r.relectureToi ? ', et toi aussi' : ''}` : 'aucune'],
          ['Avec ton accord', h(SORTIES.filter(([k]) => r.sorties[k] === 'accord').map((x) => x[1].toLowerCase()).join(' ; ') || 'rien')], p.depot ? ['Dépôt', `<code>${h(p.depot.hote)}</code>`] : null, ['Outils', PJ.pluriel(r.outils.length, 'outil', 'outils')]]))
        + PJ.sc('Le projet', `<div class="p2-decide"><button class="btn" type="button" data-p2="pause" data-p="${p.id}">${ico(p.etat === 'pause' ? 'play' : 'pause', 'sm')}${p.etat === 'pause' ? 'Reprendre le projet' : 'Mettre en pause'}</button>
          <button class="btn" type="button" data-p2="projetArchiver" data-p="${p.id}">${ico('archive', 'sm')}${p.etat === 'archive' ? 'Désarchiver le projet' : 'Archiver le projet'}</button><button class="btn danger" type="button" data-p2="projetSupprimer" data-p="${p.id}">${ico('trash', 'sm')}Supprimer le projet</button></div>
          <p class="p2-hint">${ico('info', 'xs')}Archivé, un projet reste lisible : elle n'y travaille plus et il ne te demande plus rien.</p>`) });
  };
  F.projet = (v, d) => {
    const p = PJ.proj(d.p), r = PJ.reglages(p);
    if (d.volet === 'general') { p.titre = v.titre; p.resume = v.resume; r.mode = v.mode; }
    else if (d.volet === 'rythme') Object.assign(r, { cadence: v.cadence, de: v.de, a: v.a, jours: [].concat(v.jours || []) });
    else if (d.volet === 'accords') { SORTIES.forEach(([k]) => { r.sorties[k] = v['sortie_' + k]; }); r.relecture = v.relecture; r.relectureToi = v.relectureToi != null; }
    else if (d.volet === 'depot') { Object.assign(p.depot, { hote: v.hote, defaut: v.defaut }); Object.assign(r, { flux: v.flux, brancheNom: v.brancheNom, protegee: v.protegee != null }); }
    else r.outils = [].concat(v.outils || []);
    PJ.geste(p, 'Tu as modifié les réglages du projet', 'settings', ['reglages', d.volet]);
    PJ.redessiner(); M.toast('Projet enregistré : elle en tient compte dès son prochain passage.', { mika: true });
  };
  const archiver = (p) => { if (p.etat === 'archive') { p.etat = p._avantArchive || 'pause'; M.toast('Projet désarchivé.'); } else { p._avantArchive = p.etat; p.etat = 'archive'; p.seance = false; M.toast('Projet archivé : elle n\'y travaille plus.', { ico: 'archive' }); } PJ.redessiner(); };
  A.projetArchiver = (d) => archiver(PJ.proj(d.p));
  A.projetSupprimer = (d) => { const p = PJ.proj(d.p);
    PJ.confirmer({ titre: 'Supprimer le projet ?', bouton: 'Supprimer', danger: true, ico: 'trash', corps: `<p><b>${h(p.titre)}</b> disparaît de tes projets, avec ses objectifs, ses tickets et son activité.${p.depot ? ' Son dépôt, chez l\'hôte, n\'est pas touché.' : ''} Pour le garder lisible, archive-le plutôt.</p>`,
      alors: () => { P.projets.splice(P.projets.indexOf(p), 1); M.toast('Projet supprimé.', { ico: 'trash' }); M.go('#projets/projets'); } }); };
  A.projetMenu = (d, b) => { const p = PJ.proj(d.p);
    M.menu(b, [{ label: 'Modifier le projet', ico: 'settings', action: () => M.go(PJ.fiche(p, 'reglages')) }, { label: p.etat === 'archive' ? 'Désarchiver' : 'Archiver', ico: 'archive', action: () => archiver(p) }, 'sep',
      { label: 'Supprimer', ico: 'trash', danger: true, action: () => A.projetSupprimer(d) }]); };
  A.nouveauProjet = () => PJ.tiroir({ titre: 'Nouveau projet', sous: 'Dis-lui ce que tu veux : elle pose ses questions, puis te propose un plan.', forme: 'nouveauProjet', bouton: 'Le lui confier',
    corps: `${C.texte('titre', 'Son nom', '', { requis: true, ex: 'Par exemple : Tableau de bord des scans' })}${C.long('resume', 'Ce que tu veux', '', { rangs: 5, ex: 'Dis-le comme tu le dirais à quelqu\'un.' })}
      ${C.cartes('mode', 'Comment elle le mène', 'valide', MODES)}${C.choix('cadence', 'Elle y passe', 'jour', RYTHMES)}` });
  F.nouveauProjet = (v) => {
    const id = Math.max(...P.projets.map((p) => p.id)) + 1;
    P.projets.push({ id, titre: v.titre, etat: 'cadrage', pour: 'toi', mene: 'Mika', ago: 0, resume: v.resume || 'Un nouveau projet.', ou: 'Elle lit ta demande et prépare son plan : il arrivera dans « À faire ».',
      prochain: { quand: 'dans quelques minutes', sur: 'Le cadrage : ses questions, puis son plan' }, objectifs: [], missions: [], tickets: [], depot: null, doc: null, executions: [], decisions: [], carnet: [], listes: [], gestes: [],
      liens: { lit: [], luPar: [], demandes: [] }, accords: [], consignes: [], plan: null, droits: 'piloter' });
    Object.assign(PJ.reglages(PJ.proj(id)), { mode: v.mode, cadence: v.cadence });
    M.toast('Projet confié : elle prépare son plan.', { mika: true }); M.go(PJ.fiche({ id }));
  };
})();
