/* Projets, seconde maquette — les onglets Activité (Fil, Exécutions, Carnet), Dépendances (le schéma, les demandes)
   et Listes (seulement dans un projet qui en a) d'une fiche.
   Le fil mêle les exécutions, les commits, les pull requests, les tickets et les gestes du propriétaire ; à droite,
   l'activité des trente derniers jours. Une exécution se lit pas à pas. Les dépendances se lisent sur un schéma :
   le projet au centre, ce dont il dépend d'un côté, ce qui dépend de lui de l'autre. */
(function () {
  'use strict';
  const { h, ico, av } = M;
  const PJ = window.PJ2, S = PJ.S, A = PJ.actes, F = PJ.formes, C = PJ.champs, P = PJ.P;
  Object.assign(S, { sv: 'colonnes', af: 'tout', ao: '', cn: 'tout' });
  const SORTE = { cadrage: 'p2-plan', travail: 'code', relecture: 'eye' };
  /* Ce sur quoi porte une exécution : « Objectif n° 2 · … », « Ticket n° 4 · … », une mission, le projet. */
  const surQuoi = (p, texte) => { const o = /Objectif n° (\d+)/.exec(texte), t = /Ticket n° (\d+)/.exec(texte), tk = t && p.tickets.find((x) => x.n === +t[1]);
    return { objectif: o ? +o[1] : tk ? tk.objectif : undefined, ticket: t ? +t[1] : undefined }; };
  const rattache = (p, x) => { const o = x.objectif && p.objectifs.find((y) => y.id === x.objectif), t = x.ticket && p.tickets.find((y) => y.n === x.ticket);
    return (t ? PJ.lie(PJ.fiche(p, 'tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#' + t.n, PJ.st(...PJ.etatTicket(t))) : '')
      + (o ? PJ.lie(PJ.fiche(p, 'objectifs', 'o' + o.id), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))) : ''); };

  /* ── Activité : le fil ───────────────────────────────────────────── */
  /* Les cinq sortes du fil, dans un ordre fixe : chacune garde sa couleur, quel que soit le filtre. */
  const SORTES = [['execution', 'Exécutions', 'play'], ['commit', 'Commits', 'p2-commit'], ['pr', 'Pull requests', 'p2-pr'], ['ticket', 'Tickets', 'p2-ticket'], ['geste', 'Tes gestes', 'user']];
  function fil(p) {
    const f = (...x) => PJ.fiche(p, ...x), l = [];
    p.executions.forEach((e) => l.push(Object.assign({ sorte: 'execution', ago: e.ago, ico: SORTE[e.sorte], ton: e.verdict[0], titre: e.rendu, sous: `Exécution n° ${e.id} · ${e.sorte} · ${e.duree}`, etat: PJ.st(...e.verdict), vers: f('activite', 'executions', e.id), qui: 'mika' }, surQuoi(p, e.sur))));
    if (p.depot) {
      p.depot.commits.forEach((c) => l.push({ sorte: 'commit', ago: c.ago, ico: c.fusion ? 'p2-merge' : 'p2-commit', ton: c.fusion ? 'done' : '', titre: c.msg, sous: `<code>${c.sha.slice(0, 7)}</code> · ${h(c.branche)}`, vers: f('code', 'commits', c.sha.slice(0, 7)), qui: c.par,
        objectif: c.objectif || (p.tickets.find((t) => t.n === c.ticket) || {}).objectif, ticket: c.ticket }));
      p.depot.pulls.forEach((x) => l.push({ sorte: 'pr', ago: x.ago, ico: 'p2-pr', ton: PJ.etatPr(p, x)[0], titre: `Pull request n° ${x.n} ouverte : ${x.titre}`, sous: `<code>${h(x.branche)}</code>`, etat: PJ.st(...PJ.etatPr(p, x)), vers: f('code', 'pulls', x.n), qui: x.par,
        objectif: x.objectif || (p.tickets.find((t) => t.n === x.ticket) || {}).objectif, ticket: x.ticket }));
    }
    p.tickets.forEach((t) => l.push({ sorte: 'ticket', ago: t.fil[0].ago, ico: 'p2-ticket', ton: PJ.etatTicket(t)[0], titre: `Ticket #${t.n} ouvert : ${t.titre}`, sous: h(t.sorte), etat: PJ.st(...PJ.etatTicket(t)), vers: f('tickets', t.n), qui: t.par, objectif: t.objectif, ticket: t.n }));
    (p.gestes || []).forEach((g) => l.push({ sorte: 'geste', ago: g.ago, ico: g.ico, ton: 'moi', titre: g.texte, sous: '', vers: f(...g.vers), qui: 'adrien', objectif: g.objectif || (p.tickets.find((t) => t.n === g.ticket) || {}).objectif, ticket: g.ticket }));
    return l.sort((a, b) => a.ago - b.ago);
  }
  /* Trente jours, du plus ancien à aujourd'hui : la semaine que montrent les données se compte sur le fil. */
  function trente(p, l) {
    const jours = Array.from({ length: 30 }, () => [0, 0, 0, 0, 0]);
    (p.activite30 || []).forEach((x, i) => { jours[i] = x.slice(); });
    l.forEach((x) => { const j = PJ.ecart(x.ago); if (j >= 0 && j < 7) jours[29 - j][SORTES.findIndex((s) => s[0] === x.sorte)] += 1; });
    return jours;
  }
  function graphique(p, l) {
    const jours = trente(p, l), max = Math.max(4, ...jours.map((j) => j.reduce((a, b) => a + b, 0))), totaux = SORTES.map((s, k) => jours.reduce((a, j) => a + j[k], 0));
    const dateDe = (i) => { const d = new Date(P.T - (29 - i) * 86400000); return [d.getDate(), ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'][d.getMonth()], ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'][d.getDay()]]; };
    return `<figure class="p2-chart" data-sorte="${S.af}"><figcaption><b>${totaux.reduce((a, b) => a + b, 0)}</b><span>événements en trente jours</span></figcaption>
      <div class="p2-chart-plot" role="img" aria-label="L'activité du projet, jour par jour, sur trente jours"><span class="p2-chart-max">${max}</span>${jours.map((j, i) => { const [n, mois, jour] = dateDe(i), total = j.reduce((a, b) => a + b, 0);
        return `<div class="p2-chart-col${i === 29 ? ' auj' : ''}" tabindex="0">${j.map((v, k) => (v ? `<i class="s${k}" style="height:${(v / max) * 100}%"></i>` : '')).join('')}
          <div class="p2-chart-tip"><b>${i === 29 ? 'Aujourd\'hui' : `${jour} ${n} ${mois}`}</b>${total ? SORTES.map((s, k) => (j[k] ? `<span><i class="s${k}"></i>${s[1]}<em>${j[k]}</em></span>` : '')).join('') : '<span>Rien ce jour-là</span>'}</div></div>`; }).join('')}</div>
      <div class="p2-chart-axe">${[0, 7, 14, 21, 29].map((i) => { const [n, mois] = dateDe(i); return `<span style="left:${(i + 0.5) / 30 * 100}%">${i === 29 ? 'auj.' : `${n} ${mois}`}</span>`; }).join('')}</div>
      <ul class="p2-chart-leg">${SORTES.map(([k, lib], i) => `<li><button type="button" data-p2="filAff" data-c="${k}" aria-pressed="${S.af === k}"><i class="s${i}"></i><span>${lib}</span><b>${totaux[i]}</b></button></li>`).join('')}</ul></figure>`;
  }
  function vueFil(p) {
    const tout = fil(p), o = p.objectifs.find((x) => 'o' + x.id === S.ao), l = tout.filter((x) => (S.af === 'tout' || x.sorte === S.af) && (!o || x.objectif === o.id));
    const rang = (x) => { const q = PJ.qui(x.qui), t = x.ticket && p.tickets.find((y) => y.n === x.ticket), ob = !t && x.objectif && p.objectifs.find((y) => y.id === x.objectif);
      return `<a class="p2-ev" href="${x.vers}"><time>${PJ.heure(x.ago)}</time>${PJ.tuile(x.ico, x.ton)}<span class="p2-ev-main"><b>${h(x.titre)}</b>${x.sous ? `<small>${x.sous}</small>` : ''}</span>
        <span class="p2-ev-ref">${t ? `${ico('p2-ticket', 'xs')}#${t.n}` : ob ? `${ico('p2-target', 'xs')}objectif n° ${ob.id}` : ''}</span><span class="p2-ev-etat">${x.etat || ''}</span><span class="p2-ev-who">${q.av('xs')}${x.qui === 'adrien' ? 'toi' : h(q.nom)}</span></a>`; };
    const outils = `<div class="p2-filters flat">${[['tout', 'Tout', tout.length], ...SORTES.map(([k, lib]) => [k, lib, tout.filter((x) => x.sorte === k).length])].map(([k, lib, n]) =>
        `<button type="button" data-p2="filAff" data-c="${k}" aria-pressed="${S.af === k}">${lib}<span class="cnt">${n}</span></button>`).join('')}</div>
      <button class="btn sm p2-objpick" type="button" data-p2="filObjectif" data-p="${p.id}">${ico('p2-target', 'sm')}<span class="ellipsis">${o ? `Objectif n° ${o.id}` : 'Tous les objectifs'}</span>${ico('chev-down', 'xs')}</button>`;
    return PJ.trio({ cls: 'p2-fil', volets: [['', 'Fil']], actif: '', lien: () => location.hash, plein: true, scroll: `fil-${p.id}`,
      tete: `<div class="pane-head p2-filbar">${outils}</div>`,
      corps: l.length ? `<div class="p2-evs">${PJ.parJour ? PJ.parJour(l, rang) : l.map(rang).join('')}</div>` : PJ.vide('history', 'Rien pour ce filtre', 'Change de sorte ou d\'objectif pour retrouver le fil.'),
      cote: PJ.sc('Trente derniers jours', graphique(p, tout))
        + PJ.sc('Prochain passage', `<div class="p2-next"><b>${h(p.seance ? 'en cours, à ta demande' : p.prochain.quand)}</b><span>${h(p.prochain.sur)}</span></div>${PJ.rythme ? `<p class="p2-sc-text">${h(PJ.rythme(p))}</p>` : ''}`)
        + PJ.sc('Qui a fait quoi', PJ.props([[`<span class="p2-by">${av('mika', 'xs')}Mika</span>`, PJ.pluriel(tout.filter((x) => x.qui === 'mika').length, 'événement', 'événements')], [`<span class="p2-by">${av('adrien', 'xs')}Toi</span>`, PJ.pluriel(tout.filter((x) => x.qui === 'adrien').length, 'événement', 'événements')],
          ['D\'autres', PJ.pluriel(tout.filter((x) => x.qui !== 'mika' && x.qui !== 'adrien').length, 'événement', 'événements')]])) });
  }
  A.filAff = (d) => { S.af = S.af === d.c ? 'tout' : d.c; PJ.redessiner(); };
  A.filObjectif = (d, b) => { const p = PJ.proj(d.p);
    M.menu(b, [{ label: 'Tous les objectifs', coche: !S.ao, action: () => { S.ao = ''; PJ.redessiner(); } }, 'sep', ...p.objectifs.map((o) => ({ label: `n° ${o.id} · ${o.titre}`, ico: 'p2-target', coche: S.ao === 'o' + o.id, action: () => { S.ao = 'o' + o.id; PJ.redessiner(); } }))], { align: 'left' }); };

  /* ── Activité : les exécutions, pas à pas ────────────────────────── */
  const PAS = [[/^A (re)?lu(?=\s)/, 'eye', 'a lu'], [/^A (lancé|essayé|reproduit|vérifié)(?=\s)/, 'terminal', 'a lancé'], [/^A poussé(?=\s)/, 'p2-commit', 'a poussé'], [/^A ouvert(?=\s)/, 'p2-pr', 'a ouvert'], [/^A proposé(?=\s)/, 'p2-ticket', 'a proposé'],
    [/^A (posé|demandé)(?=\s)/, 'p2-question', 'a demandé'], [/^A (écrit|ajouté|mis à jour|branché)(?=\s)/, 'pen', 'a écrit']];
  function detailExecution(p, e) {
    const c = e.commit && p.depot && p.depot.commits.find((x) => x.sha === e.commit), run = c && p.depot.ci.find((r) => r.sha === c.sha), minutes = parseInt(e.duree, 10) || e.fait.length, sur = surQuoi(p, e.sur);
    return { scroll: `exe-${e.id}`, volets: [['', 'Pas à pas', e.fait.length]], actif: '', lien: () => location.hash,
      tete: PJ.parts.entete({ tuile: PJ.tuile(SORTE[e.sorte], e.verdict[0]), sur: `Exécution n° ${e.id} · ${e.sorte}`, titre: e.sur, meta: `${PJ.st(...e.verdict)}<span>${PJ.moment(e.ago)}</span><span>${ico('clock', 'xs')}${h(e.duree)}</span>` }),
      corps: `${PJ.parts.bulle({ de: 'mika', ago: e.ago, texte: e.rendu })}<h3 class="p2-h3">Ce qu'elle a fait, pas à pas<span class="cnt">${e.fait.length}</span></h3>
        <ol class="p2-pas">${e.fait.map((x, i) => { const [, icone, verbe] = PAS.find(([re]) => re.test(x)) || [0, 'check', 'a fait'];
          return `<li><i>${ico(icone, 'xs')}</i><span class="p2-pas-v">${verbe}</span><p>${PJ.code(x.replace(/^A \S+( à jour)? /, '').replace(/^./, (ch) => ch.toUpperCase()))}</p><time>+ ${Math.round((i + 1) * minutes / (e.fait.length + 1))} min</time></li>`; }).join('')}
          <li class="fin ${e.verdict[0]}"><i>${ico(e.verdict[0] === 'fail' ? 'x' : e.verdict[0] === 'you' ? 'p2-question' : 'check', 'xs')}</i><span class="p2-pas-v">verdict</span><p>${h(e.verdict[1][0].toUpperCase() + e.verdict[1].slice(1))}</p><time>${h(e.duree)}</time></li></ol>`,
      cote: PJ.sc('En bref', PJ.props([['Verdict', PJ.st(...e.verdict)], ['Sorte', `<span class="p2-kind">${ico(SORTE[e.sorte], 'xs')}${e.sorte}</span>`], ['Quand', PJ.moment(e.ago)], ['Durée', h(e.duree)]]))
        + PJ.sc('Ce qu\'elle t\'a demandé', e.demande ? `<p class="p2-sc-text">${h(e.demande)}</p><a class="btn" href="${PJ.route('a-faire')}">Voir dans À faire${ico('chev-right', 'sm')}</a>` : '')
        + PJ.sc('Sur quoi', rattache(p, sur) || `<p class="p2-sc-text">${h(e.sur)}</p>`)
        + PJ.sc('Son commit', c ? PJ.lie(PJ.fiche(p, 'code', 'commits', c.sha.slice(0, 7)), 'p2-commit', '', c.msg, `<code>${c.sha.slice(0, 7)}</code> · ${h(c.branche)}`, run ? PJ.st(PJ.CI[run.etat][0], 'CI ' + PJ.CI[run.etat][1]) : '') : '') };
  }
  function vueExecutions(p, rest) {
    const l = p.executions, e = PJ.choisi(l, (x) => x.id, rest[0]);
    let jour = '';
    const liste = `<div class="pane-head"><h2>Exécutions</h2><span class="cnt">${l.length}</span></div><div class="pane-scroll p2-timeline" data-scroll="exes">${l.map((x) => { const j = PJ.jour(x.ago), t = j !== jour ? `<div class="p2-day">${(jour = j)}</div>` : '';
      return `${t}<a class="p2-cm" href="${PJ.fiche(p, 'activite', 'executions', x.id)}" aria-selected="${x === e}"><i class="${x.verdict[0]}"></i><span class="li-title">${h(x.sur)}</span>
        <span class="p2-row-sub"><span class="p2-kind">${ico(SORTE[x.sorte], 'xs')}${x.sorte}</span>${PJ.st(...x.verdict)}<time>${PJ.heure(x.ago)} · ${h(x.duree)}</time></span></a>`; }).join('')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!e, retour: [PJ.fiche(p, 'activite', 'executions'), 'Exécutions'] },
      e ? detailExecution(p, e) : { vide: PJ.vide('history', 'Pas encore d\'exécution', 'Chaque séance de travail laisse ici son compte rendu, pas à pas.') }));
  }
  /* ── Activité : son carnet ───────────────────────────────────────── */
  const vueCarnet = (p) => { const groupes = [...new Set(p.carnet.map((n) => n.objectif))], vus = groupes.filter((g) => S.cn === 'tout' || S.cn === g);
    return `<div class="fill-scroll" data-scroll="carnet"><div class="p2-full"><header class="p2-sec-h"><div><h2>Son carnet</h2><p>Ce qu'elle note pour elle-même en travaillant. Elle le relit avant chaque passage.</p></div></header>
      ${groupes.length ? `<div class="p2-filters flat"><button type="button" data-p2="carnetFiltre" data-c="tout" aria-pressed="${S.cn === 'tout' || !vus.length}">Tout<span class="cnt">${p.carnet.length}</span></button>${groupes.map((g) =>
          `<button type="button" data-p2="carnetFiltre" data-c="${h(g)}" aria-pressed="${S.cn === g}">${h(g)}<span class="cnt">${p.carnet.filter((n) => n.objectif === g).length}</span></button>`).join('')}</div>
        <div class="p2-notes">${p.carnet.filter((n) => !vus.length || vus.includes(n.objectif)).map((n) => `<figure class="p2-notecard"><blockquote>${PJ.code(n.texte)}</blockquote><figcaption>${av('mika', 'xs')}<span>${h(n.objectif)}</span><time>${PJ.moment(n.ago)}</time></figcaption></figure>`).join('')}</div>`
        : PJ.vide('book', 'Carnet vide', 'Elle n\'a encore rien noté sur ce projet.')}</div></div>`; };
  A.carnetFiltre = (d) => { S.cn = d.c; PJ.redessiner(); };
  PJ.onglets.activite = (p, rest) => {
    const v = ['executions', 'carnet'].includes(rest[0]) ? rest[0] : 'fil';
    return PJ.sous(p, 'activite', [['fil', 'Fil'], ['executions', 'Exécutions', p.executions.length], ['carnet', 'Carnet', p.carnet.length]], v,
      `<span class="p2-sync">${ico('clock', 'xs')}prochain passage : ${h(p.seance ? 'en cours' : p.prochain.quand)}</span>`) + `<div class="p2-under">${v === 'fil' ? vueFil(p) : v === 'executions' ? vueExecutions(p, rest.slice(1)) : vueCarnet(p)}</div>`;
  };

  /* ── Listes : une liste en colonnes par statut, ou en tableau (seulement dans un projet qui en a) ── */
  const charge = (p, li, e) => `<button class="p2-charge" type="button" data-p2="elementConfier" data-p="${p.id}" data-l="${li.id}" data-c="${e.id}" title="À la charge de ${e.charge === 'toi' ? 'toi' : 'Mika'} — cliquer pour changer">${av(e.charge === 'toi' ? 'adrien' : 'mika', 'xs')}<span>${e.charge === 'toi' ? 'toi' : 'elle'}</span></button>`;
  const pastille = (p, li, e) => { const s = PJ.statut(li, e); return `<button class="p2-st ${s[2]} p2-stbtn" type="button" data-p2="suiviStatut" data-p="${p.id}" data-l="${li.id}" data-c="${e.id}" title="Changer le statut">${h(s[1])}${ico('chev-down', 'xs')}</button>`; };
  function vueListe(p, li) {
    if (S.sv === 'tableau') return `<div class="fill-scroll" data-scroll="suivi-t"><div class="p2-tablefull"><table class="tbl p2-suivi-t"><thead><tr><th>Nom</th><th>Statut</th><th>À la charge de</th><th>Note</th><th>Depuis</th></tr></thead><tbody>
      ${li.elements.map((e) => `<tr><td><b>${h(e.nom)}</b><small>${h(e.sous)}</small></td><td>${pastille(p, li, e)}</td><td>${charge(p, li, e)}</td><td class="p2-td-note">${h(e.note)}</td><td class="nowrap muted">${PJ.quand(e.ago)}</td></tr>`).join('')}</tbody></table></div></div>`;
    return `<div class="p2-board" data-scroll="suivi-b">${li.statuts.map(([k, lib, ton]) => { const l = li.elements.filter((e) => e.statut === k);
      return `<section class="p2-col"><header><i class="${ton}"></i><b>${h(lib)}</b><span class="cnt">${l.length}</span></header><div class="p2-col-in">${l.map((e) =>
        `<article class="p2-kcard${e.charge === 'toi' && ton === 'wait' ? ' atoi' : ''}"><b>${h(e.nom)}</b><small>${h(e.sous)}</small>${e.note ? `<p>${h(e.note)}</p>` : ''}<footer>${charge(p, li, e)}<time>${PJ.quand(e.ago)}</time>${pastille(p, li, e)}</footer></article>`).join('')
        || '<p class="p2-none">Rien ici.</p>'}</div></section>`; }).join('')}</div>`;
  }
  PJ.onglets.listes = (p, rest) => {
    const li = p.listes.find((x) => x.id === rest[0]) || p.listes[0];
    return PJ.sous(p, 'listes', p.listes.map((x) => [x.id, x.titre, x.elements.length]), li.id,
      `<span class="p2-sync wide">${h(li.quoi)}</span><div class="seg p2-viewseg"><button type="button" data-p2="suiviVue" data-c="colonnes" aria-pressed="${S.sv === 'colonnes'}">${ico('p2-board', 'sm')}Colonnes</button><button type="button" data-p2="suiviVue" data-c="tableau" aria-pressed="${S.sv === 'tableau'}">${ico('p2-table', 'sm')}Tableau</button></div>
        ${PJ.voir(p) ? '' : `<button class="btn sm primary" type="button" data-p2="suiviAjouter" data-p="${p.id}" data-l="${li.id}">${ico('plus', 'sm')}<span class="lbl">Ajouter</span></button>`}`) + `<div class="p2-under">${vueListe(p, li)}</div>`;
  };
  A.suiviVue = (d) => { S.sv = d.c; PJ.redessiner(); };
  A.suiviStatut = (d, b) => {
    const li = PJ.proj(d.p).listes.find((x) => x.id === d.l), e = li.elements.find((x) => x.id === d.c);
    M.menu(b, [{ entete: e.nom }, ...li.statuts.map(([k, lib]) => ({ label: lib, coche: e.statut === k, action: () => A.elementStatut({ p: d.p, l: d.l, c: d.c, s: k }) }))]);
  };
  A.suiviAjouter = (d) => { const li = PJ.proj(d.p).listes.find((x) => x.id === d.l);
    PJ.tiroir({ titre: `Ajouter à « ${li.titre} »`, sous: li.quoi, forme: 'element', data: { p: d.p, l: d.l }, bouton: 'Ajouter',
      corps: `${C.texte('nom', 'Nom', '', { requis: true })}${C.texte('sous', 'En deux mots', '', { ex: 'Ce que c\'est, combien de postes…' })}${C.deux(C.choix('statut', 'Statut', li.statuts[0][0], li.statuts.map(([k, l]) => [k, l])), C.choix('charge', 'À la charge de', 'elle', [['elle', 'Mika'], ['toi', 'toi']]))}${C.long('note', 'Note', '', { rangs: 3 })}` }); };
  F.element = (v, d) => { const li = PJ.proj(d.p).listes.find((x) => x.id === d.l);
    li.elements.unshift({ id: 'e' + Date.now(), nom: v.nom, sous: v.sous, statut: v.statut, charge: v.charge, note: v.note, ago: 0 }); PJ.redessiner(); M.toast(`Ajouté à « ${li.titre} » : ${v.nom}`); };

  /* ── Dépendances : le schéma, et les demandes ────────────────────── */
  const DONS = ['le voir', 'son détail', 'ses fichiers', 'sa documentation'];
  const fd = (p, ...x) => PJ.fiche(p, 'dependances', ...x);
  const entreDeux = (p, x) => p.liens.demandes.filter((q) => q.avec === x.titre);
  const noeud = (p, x, sens, choisi) => { const autre = PJ.proj(x.projet), n = entreDeux(p, x).length;
    return `<a class="p2-sch-node ${sens}" href="${fd(p, `${sens}-${x.projet}`)}" aria-selected="${x === choisi}"><span class="p2-sch-top"><span class="p2-logo c${x.projet % 8}">${h(x.titre[0])}</span><span class="p2-sch-t"><b>${h(x.titre)}</b><small>${x.de === 'toi' ? 'à toi' : 'de ' + h(x.de)}</small></span>${autre ? PJ.st(...PJ.etatProjet(autre)) : ''}</span>
      <span class="p2-sch-why">${h(x.pourquoi)}</span>
      <span class="p2-gives">${DONS.map((g) => `<span class="${x.donne.includes(g) ? 'oui' : 'non'}">${ico(x.donne.includes(g) ? 'check' : 'x', 'xs')}${g}</span>`).join('')}</span>
      <span class="p2-sch-foot">${ico('p2-commit', 'xs')}<code>${x.commit.sha.slice(0, 7)}</code><span>${PJ.quand(x.commit.ago)}</span><em>${n ? PJ.pluriel(n, 'demande', 'demandes') : 'aucune demande'}</em></span>
      <span class="p2-sch-fleche" aria-hidden="true"><em>${sens === 'lit' ? 'lu par lui' : 'le lit'}</em></span></a>`; };
  function panneauLien(p, x, sens) {
    const autre = PJ.proj(x.projet), dem = entreDeux(p, x), d = `data-p="${p.id}" data-s="${sens}" data-c="${x.projet}"`, voir = PJ.voir(p);
    return PJ.sc(null, `<div class="p2-side-h"><span class="p2-logo c${x.projet % 8}">${h(x.titre[0])}</span><span><b>${h(x.titre)}</b><small>${sens === 'lit' ? `« ${h(p.titre)} » le lit` : `il lit « ${h(p.titre)} »`} · depuis le ${h(x.depuis)}</small></span>${autre ? PJ.st(...PJ.etatProjet(autre)) : ''}</div>
        <p class="p2-sc-text">${h(x.pourquoi)}</p>`)
      + PJ.sc(sens === 'lit' ? 'Ce que le lien lui donne' : 'Ce qu\'il lui donne', `<div class="p2-dons">${DONS.map((g, i) => `<label class="p2-check"><input type="checkbox" data-p2-don="${i}" ${d}${x.donne.includes(g) ? ' checked' : ''}${i === 0 || voir ? ' disabled' : ''}><span><b>${g[0].toUpperCase() + g.slice(1)}</b>
          <small>${['le minimum : son nom, son état, où il en est', 'ses objectifs, ses tickets, son activité', 'le dépôt, en lecture', 'ses pages, en lecture (par MCP, sans réglage)'][i]}</small></span></label>`).join('')}</div>`)
      + PJ.sc('Le commit que montre la vue', `<p class="p2-lastc"><code>${x.commit.sha.slice(0, 7)}</code><span class="ellipsis">${h(x.commit.msg)}</span><time>${PJ.quand(x.commit.ago)}</time></p>`)
      + PJ.sc('Les demandes entre les deux', (dem.map((q) => PJ.lie(fd(p, 'demandes', q.id), q.sens === 'reçue' ? 'download' : 'upload', q.etape[0], q.titre, `${q.sens} · ${PJ.quand(q.ago)}`, PJ.st(...q.etape))).join('') || '<p class="p2-none">Aucune demande entre ces deux projets.</p>')
        + (voir ? '' : `<div class="p2-decide"><button class="btn" type="button" data-p2="demandeNouvelle" data-p="${p.id}" data-c="${x.projet}">${ico('send', 'sm')}Lui demander quelque chose</button></div>`), `<span class="cnt">${dem.length}</span>`)
      + PJ.sc('Gérer', `<div class="p2-decide"><a class="btn" href="${PJ.fiche({ id: x.projet })}">${ico('external', 'sm')}Ouvrir « ${h(x.titre)} »</a>${voir ? '' : `<button class="btn danger" type="button" data-p2="lienRetirer" ${d}>${ico('trash', 'sm')}Retirer la dépendance</button>`}</div>`);
  }
  function vueSchema(p, rest) {
    const [sens, id] = (rest[0] || '').split('-'), tous = [...p.liens.lit.map((x) => [x, 'lit']), ...p.liens.luPar.map((x) => [x, 'luPar'])];
    const choix = tous.find(([x, s]) => s === sens && String(x.projet) === id) || (M.mobile() ? null : tous[0]) || null, voir = PJ.voir(p);
    const colonne = (titre, sous, l, s, plus) => `<div class="p2-sch-col ${s}"><h3>${titre}<span class="cnt">${l.length}</span></h3><p>${sous}</p>${l.map((x) => noeud(p, x, s, choix && choix[0])).join('') || `<p class="p2-none box">${s === 'lit' ? 'Il ne dépend d\'aucun autre projet.' : 'Aucun projet ne dépend de lui.'}</p>`}${plus || ''}</div>`;
    const schema = `<div class="p2-schzone"><div class="p2-schema">
        ${colonne('Il dépend de', 'les projets qu\'il lit', p.liens.lit, 'lit')}
        <div class="p2-sch-centre"><span class="p2-logo c${p.id % 8}">${h(p.titre[0])}</span><b>${h(p.titre)}</b>${PJ.st(...PJ.etatProjet(p))}<small>${h(p.resume)}</small>
          <dl><div><dt>${p.objectifs.filter((o) => o.etat !== 'fait').length}</dt><dd>objectifs en cours</dd></div><div><dt>${PJ.ouverts(p).length}</dt><dd>tickets ouverts</dd></div><div><dt>${p.doc ? p.doc.pages.length : 0}</dt><dd>pages de documentation</dd></div></dl></div>
        ${colonne('Dépendent de lui', 'les projets qui le lisent', p.liens.luPar, 'luPar')}</div>
      <p class="p2-hint">${ico('info', 'xs')}Une flèche va du projet lu vers celui qui le lit. Choisis un projet pour régler ce que le lien donne.</p></div>`;
    if (M.mobile() && choix && rest[0]) return PJ.trio({ liste: '', ouvert: true, retour: [fd(p), 'Le schéma'], volets: [['', 'Le lien']], actif: '', lien: () => location.hash, scroll: 'lien', corps: `<div class="p2-flat">${panneauLien(p, ...choix)}</div>` });
    return PJ.trio({ volets: [['', 'Schéma']], actif: '', lien: () => location.hash, plein: true, scroll: `schema-${p.id}`, corps: schema, cote: M.mobile() ? '' : choix ? panneauLien(p, ...choix)
      : PJ.sc('Aucune dépendance', `<p class="p2-sc-text">Un projet qui dépend d'un autre peut le voir, lire ses fichiers et sa documentation, et lui demander quelque chose.</p>${voir ? '' : `<div class="p2-decide"><button class="btn primary" type="button" data-p2="lienAjouter" data-p="${p.id}">${ico('plus', 'sm')}Ajouter une dépendance</button></div>`}`) });
  }
  const ETAPES_D = ['envoyée', 'à l\'étude', 'acceptée', 'livrée'];
  function detailDemande(p, q) {
    const autre = P.projets.find((x) => x.titre === q.avec), recue = q.sens === 'reçue', lien = (recue ? p.liens.luPar : p.liens.lit).find((x) => x.titre === q.avec), d = `data-p="${p.id}" data-c="${q.id}"`;
    const rang = q.etape[0] === 'done' ? 3 : q.etape[0] === 'fail' ? -1 : q.etape[0] === 'work' ? (/accept/.test(q.etape[1]) ? 2 : 1) : 0, ouverte = rang >= 0 && rang < 3;
    return { scroll: `dem-${q.id}`, volets: [['', 'La demande']], actif: '', lien: () => location.hash,
      tete: PJ.parts.entete({ tuile: PJ.tuile(recue ? 'download' : 'upload', q.etape[0]), sur: recue ? 'Demande reçue' : 'Demande envoyée', titre: q.titre, meta: `${PJ.st(...q.etape)}<span>${recue ? 'de' : 'à'} « ${h(q.avec)} »</span><span>${PJ.quand(q.ago)}</span>`,
        droite: PJ.voir(p) || !ouverte ? '' : recue ? `${rang < 2 ? `<button class="btn primary" type="button" data-p2="demandeEtape" ${d} data-s="accepter">${ico('check', 'sm')}Accepter</button>` : `<button class="btn primary" type="button" data-p2="demandeEtape" ${d} data-s="livrer">${ico('check', 'sm')}La dire livrée</button>`}
          <button class="btn" type="button" data-p2="demandeEtape" ${d} data-s="refuser">${ico('x', 'sm')}Refuser</button>` : `<button class="btn" type="button" data-p2="demandeEtape" ${d} data-s="retirer">${ico('x', 'sm')}Retirer la demande</button>` }),
      corps: `<p class="p2-choix">${h(q.texte)}</p><h3 class="p2-h3">Où elle en est</h3>${rang < 0 ? `<p class="p2-ecarte">${ico('x', 'sm')}${h(q.etape[1][0].toUpperCase() + q.etape[1].slice(1))}.</p>`
        : `<ol class="p2-steps plat">${ETAPES_D.map((lib, n) => `<li class="${n < rang || rang === 3 ? 'fait' : n === rang ? 'ici ' + q.etape[0] : ''}"><i>${n < rang || rang === 3 ? ico('check', 'xs') : n + 1}</i><span>${lib}</span></li>`).join('')}</ol>`}`,
      cote: PJ.sc('En bref', PJ.props([['Sens', recue ? `reçue : « ${h(q.avec)} » demande à ce projet` : `envoyée : ce projet demande à « ${h(q.avec)} »`], ['Étape', PJ.st(...q.etape)], ['Depuis', PJ.moment(q.ago)], ['Qui s\'en occupe', recue ? `<span class="p2-by">${av('mika', 'xs')}Mika, sur ton accord</span>` : `l'équipe de « ${h(q.avec)} »`]]))
        + PJ.sc('Le lien', lien ? PJ.lie(fd(p, `${recue ? 'luPar' : 'lit'}-${lien.projet}`), 'link', '', q.avec, `${lien.donne.length} choses données sur 4`) : '')
        + PJ.sc('Le projet', autre ? PJ.lie(PJ.fiche(autre), 'flag', PJ.etatProjet(autre)[0], autre.titre, h(autre.ou.slice(0, 60)) + '…', PJ.st(...PJ.etatProjet(autre))) : '') };
  }
  function vueDemandes(p, rest) {
    const l = p.liens.demandes, q = PJ.choisi(l, (x) => x.id, rest[0]);
    const liste = `<div class="p2-tools"><h2 class="grow">Demandes entre projets</h2>${PJ.voir(p) || !p.liens.lit.length ? '' : `<button class="btn primary" type="button" data-p2="demandeNouvelle" data-p="${p.id}">${ico('send', 'sm')}<span>Nouvelle demande</span></button>`}</div>
      <div class="pane-scroll" data-scroll="demandes">${l.length ? l.map((x) => `<a class="li p2-row" href="${fd(p, 'demandes', x.id)}" aria-selected="${x === q}">${PJ.tuile(x.sens === 'reçue' ? 'download' : 'upload', x.etape[0])}<span class="li-main"><span class="li-title">${h(x.titre)}</span>
        <span class="p2-row-sub">${PJ.st(...x.etape)}<span class="ellipsis">${x.sens === 'reçue' ? 'de' : 'à'} ${h(x.avec)}</span><time>${PJ.quand(x.ago)}</time></span></span></a>`).join('') : PJ.vide('send', 'Aucune demande', 'Ni reçue, ni envoyée.')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!q, retour: [fd(p, 'demandes'), 'Demandes'] }, q ? detailDemande(p, q) : { vide: PJ.vide('send', 'Aucune demande', 'Ce qu\'un projet demande à un autre s\'ouvre ici, avec son étape.') }));
  }
  PJ.onglets.dependances = (p, rest) => {
    const v = rest[0] === 'demandes' ? 'demandes' : 'schema';
    return PJ.sous(p, 'dependances', [['schema', 'Schéma', p.liens.lit.length + p.liens.luPar.length], ['demandes', 'Demandes', p.liens.demandes.length]], v,
      PJ.voir(p) ? '' : `<button class="btn sm" type="button" data-p2="lienAjouter" data-p="${p.id}">${ico('plus', 'sm')}<span class="lbl">Ajouter une dépendance</span></button>`)
      + `<div class="p2-under">${v === 'demandes' ? vueDemandes(p, rest.slice(1)) : vueSchema(p, rest[0] === 'schema' ? rest.slice(1) : rest)}</div>`;
  };
  const leLien = (d) => { const p = PJ.proj(d.p); return [p, p.liens[d.s].find((x) => String(x.projet) === d.c)]; };
  document.addEventListener('change', (e) => {
    const c = e.target.closest('[data-p2-don]'); if (!c) return;
    const [, x] = leLien(c.dataset), g = DONS[Number(c.dataset.p2Don)];
    x.donne = DONS.filter((y) => (y === g ? c.checked : x.donne.includes(y)));
    PJ.redessiner(); M.toast(`« ${x.titre} » : ${c.checked ? 'donne' : 'ne donne plus'} ${g}.`);
  });
  A.lienRetirer = (d) => { const [p, x] = leLien(d);
    PJ.confirmer({ titre: 'Retirer cette dépendance ?', bouton: 'Retirer', danger: true, corps: `<p>${d.s === 'lit' ? `« ${h(p.titre)} » ne lira plus « ${h(x.titre)} »` : `« ${h(x.titre)} » ne lira plus « ${h(p.titre)} »`} : ni ses fichiers, ni sa documentation. Les demandes déjà faites restent.</p>`,
      alors: () => { p.liens[d.s] = p.liens[d.s].filter((y) => y !== x); M.toast('Dépendance retirée.', { ico: 'link' }); M.go(fd(p)); } }); };
  A.lienAjouter = (d) => {
    const p = PJ.proj(d.p), libres = P.projets.filter((x) => x !== p && !p.liens.lit.some((y) => y.projet === x.id));
    if (!libres.length) { M.toast('Il dépend déjà de tous tes autres projets.', { ico: 'info' }); return; }
    PJ.tiroir({ titre: 'Ajouter une dépendance', sous: `« ${p.titre} » lira un autre projet.`, forme: 'lien', data: { p: p.id }, bouton: 'Ajouter',
      corps: `${C.choix('projet', 'Le projet dont il dépend', libres[0].id, libres.map((x) => [x.id, x.titre]))}${C.groupe('Ce que le lien lui donne', DONS.map((g, i) => C.coche('dons', g[0].toUpperCase() + g.slice(1), i !== 1, '', g)).join(''), '« Le voir » est le minimum.')}
        ${C.texte('pourquoi', 'Pourquoi', '', { ex: 'Par exemple : pour citer ses commandes sans les inventer' })}` });
  };
  F.lien = (v, d) => { const p = PJ.proj(d.p), autre = PJ.proj(v.projet), donne = DONS.filter((g, i) => i === 0 || [].concat(v.dons || []).includes(g));
    p.liens.lit.push({ projet: autre.id, titre: autre.titre, de: autre.pour, donne, depuis: '4 novembre', pourquoi: v.pourquoi || 'Pour s\'appuyer sur ce qu\'il sait déjà.', commit: { sha: 'e0a1b2c3d4e5', msg: 'le dernier commit de sa branche par défaut', ago: autre.ago } });
    M.toast(`« ${p.titre} » dépend maintenant de « ${autre.titre} ».`, { ico: 'link' }); M.go(fd(p, 'lit-' + autre.id)); };
  A.demandeNouvelle = (d) => { const p = PJ.proj(d.p);
    PJ.tiroir({ titre: 'Nouvelle demande', sous: 'Ce que ce projet demande à un projet dont il dépend.', forme: 'demande', data: { p: p.id }, bouton: 'Envoyer la demande',
      corps: `${C.choix('avec', 'À quel projet', d.c || '', [...p.liens.lit, ...p.liens.luPar].map((x) => [x.projet, x.titre]))}${C.texte('titre', 'Ce qu\'il lui demande', '', { requis: true, ex: 'Par exemple : exposer la liste des hôtes en JSON' })}${C.long('texte', 'Pourquoi, et pour quand', '', { rangs: 4 })}` }); };
  F.demande = (v, d) => { const p = PJ.proj(d.p), id = 'd' + Date.now(), avec = [...p.liens.lit, ...p.liens.luPar].find((x) => String(x.projet) === v.avec);
    p.liens.demandes.unshift({ id, sens: 'envoyée', avec: avec.titre, titre: v.titre, etape: ['wait', 'attend leur réponse'], ago: 0, texte: v.texte || 'Envoyée par toi depuis cet écran.' });
    PJ.geste(p, `Tu as envoyé une demande à « ${avec.titre} »`, 'send', ['dependances', 'demandes', id]); M.toast('Demande envoyée.', { ico: 'send' }); M.go(fd(p, 'demandes', id)); };
  A.demandeEtape = (d) => { const p = PJ.proj(d.p), q = p.liens.demandes.find((x) => x.id === d.c);
    if (d.s === 'retirer') { p.liens.demandes = p.liens.demandes.filter((x) => x !== q); M.toast('Demande retirée.', { ico: 'x' }); M.go(fd(p, 'demandes')); return; }
    q.etape = { accepter: ['work', 'acceptée · elle s\'en occupe'], livrer: ['done', 'livrée'], refuser: ['fail', 'refusée'] }[d.s]; q.ago = 0;
    PJ.redessiner(); M.toast({ accepter: 'Demande acceptée : elle s\'en occupe.', livrer: 'Demande livrée.', refuser: 'Demande refusée.' }[d.s], { mika: d.s === 'accepter' }); };
})();
