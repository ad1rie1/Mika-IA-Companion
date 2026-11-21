/* Projets, seconde maquette — le diagramme de l'onglet Objectifs (la bascule « Liste | Diagramme »).
   Une ligne par objectif et par mission, et sous chacun, en retrait, une ligne par jalon ; les noms à gauche, les
   barres à droite, et à droite encore le panneau de ce qu'on a choisi, avec ses gestes. Deux modes, en bascule :
   « Avancement » (les barres partent du même bord : la part faite, et un mot au bout) et « Dans le temps » (un Gantt :
   un axe en jours ou en semaines, un trait pour aujourd'hui, une flèche d'un objectif à celui qui en dépend).
   Ce qui n'a pas commencé n'a pas de date : il se montre en fantôme, à la suite, dans l'ordre du plan. */
(function () {
  'use strict';
  const { h, ico } = M;
  const PJ = window.PJ2, S = PJ.S, A = PJ.actes, P = PJ.P;
  Object.assign(S, { gz: 'jours', gplie: new Set(), gx: null });
  const MOIS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'], SEM = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
  const jourDe = (ago) => new Date(P.T - ago * 60000);
  const dateDe = (ago) => { const d = jourDe(ago); return `${d.getDate()} ${MOIS[d.getMonth()]}`; };
  const cle = (x) => (typeof x.id === 'number' ? 'o' + x.id : x.id);
  const HO = 46, HJ = 36, MINUIT = 14 * 60 + 20;   // la maquette se passe à 14:20 : minuit, aujourd'hui, est à 860 minutes
  const exes = (n) => PJ.pluriel(n || 1, 'exécution', 'exécutions');

  /* Le temps d'un objectif et de ses jalons, d'après ce que les données savent : jamais une date inventée. */
  function chrono(o) {
    const connus = [o.debut, ...(o.rendus || []).map((r) => r.ago)].filter((x) => x != null), parti = connus.length > 0, debut = parti ? Math.max(...connus) : null;
    const jalons = (o.jalons || []).map((j) => { const commence = j.etat !== 'ouvert';
      return { j, commence, debut: commence ? (j.debut != null ? j.debut : j.ago != null ? j.ago + 90 : debut) : null, fin: !commence ? null : j.etat === 'atteint' ? j.ago : 0, pret: j.etat === 'pret' ? j.ago : null }; });
    const enCours = parti && o.etat === 'en_cours';
    return { parti, debut, enCours, jalons, fin: !parti ? null : enCours ? 0 : o.ago != null ? o.ago : debut };
  }
  const motJalon = (x) => { const j = x.j;
    return j.etat === 'atteint' ? `atteint le ${dateDe(j.ago)}` : j.etat === 'pret' ? 'attend ta validation' : j.etat === 'refuse' ? 'refusé : elle le reprend' : j.etat === 'en_cours' ? exes(j.exes) : 'à venir'; };
  const part = (j) => (j.etat === 'atteint' || j.etat === 'pret' ? 1 : j.etat === 'ouvert' ? 0 : Math.min(0.9, 0.15 + 0.25 * (j.exes || 1)));

  /* Les lignes : les objectifs dans l'ordre du plan, chacun suivi de ses jalons (sauf replié), puis les missions. */
  function lignes(p) {
    const l = []; let y = 0;
    const pose = (r, haut) => { l.push(Object.assign(r, { y, haut })); y += haut; };
    p.objectifs.slice().sort((a, b) => a.id - b.id).forEach((o) => { const c = chrono(o), plie = S.gplie.has(cle(o));
      pose({ sorte: 'obj', o, c, plie }, HO);
      if (!plie) c.jalons.forEach((x) => pose({ sorte: 'jalon', o, x }, HJ)); });
    p.missions.forEach((m) => pose({ sorte: 'mission', o: m }, HO));
    return { l, haut: y };
  }
  const nom = (p, r, mode, choix) => {
    const f = (...x) => PJ.fiche(p, 'objectifs', 'diagramme', mode, ...x);
    if (r.sorte === 'jalon') { const [ton] = PJ.etatJalon(r.x.j);
      return [f(cle(r.o), r.x.j.id), choix.o === r.o && choix.j === r.x.j, `<i class="p2-g-pt ${ton}"></i><span class="p2-g-t">${h(r.x.j.titre)}</span>`]; }
    if (r.sorte === 'mission') return [f(r.o.id), choix.o === r.o, `<span class="p2-g-pli"></span>${PJ.tuile('refresh', 'work')}<span class="p2-g-t"><b>${h(r.o.titre)}</b><small>mission · ${h(r.o.cadence)}</small></span>`];
    const [ton, lib] = PJ.etatObjectif(r.o);
    return [f(cle(r.o)), choix.o === r.o && !choix.j, `<span class="p2-g-pli" role="button" data-p2="ganttPlier" data-c="${cle(r.o)}" title="${r.plie ? 'Déplier ses jalons' : 'Replier ses jalons'}">${r.o.jalons.length ? ico(r.plie ? 'chev-right' : 'chev-down', 'xs') : ''}</span>
      ${PJ.tuile('p2-target', ton)}<span class="p2-g-t"><b>${h(r.o.titre)}</b><small>n° ${r.o.id} · ${lib}</small></span>`];
  };

  /* ── Mode « Avancement » : les barres partent toutes du même bord ── */
  function avancement(p, r) {
    if (r.sorte === 'jalon') { const j = r.x.j, [ton] = PJ.etatJalon(j), f = part(j);
      return `<span class="p2-g-av${j.etat === 'ouvert' ? ' vide' : ''}"><i class="${ton}${j.etat === 'pret' ? ' hache' : ''}" style="width:${f * 100}%"></i></span><span class="p2-g-mot ${j.etat === 'pret' ? 'you' : ''}">${j.etat === 'pret' ? ico('p2-stop', 'xs') + 'à toi · ' : ''}${h(motJalon(r.x))}</span>`; }
    if (r.sorte === 'mission') { const m = r.o, n = Math.min(12, (m.passes || []).length || Math.min(12, m.passages));
      return `<span class="p2-g-av mission">${Array.from({ length: n }, () => '<i></i>').join('')}</span><span class="p2-g-mot">${PJ.pluriel(m.passages, 'passage', 'passages')}${m.ago != null ? ` · le dernier ${PJ.quand(m.ago)}` : ''}</span>`; }
    const o = r.o, js = o.jalons, n = js.length, atteints = js.filter((j) => j.etat === 'atteint').length;
    const tons = n ? js.map((j) => [PJ.etatJalon(j)[0], part(j) / n, j.etat === 'pret']) : [[PJ.etatObjectif(o)[0], o.etat === 'fait' ? 1 : o.etat === 'en_cours' ? 0.5 : 0, false]];
    const ordre = ['done', 'you', 'work', 'fail'], somme = ordre.map((t) => [t, tons.filter((x) => x[0] === t).reduce((a, x) => a + x[1], 0)]);
    return `<span class="p2-g-av obj">${somme.filter((x) => x[1] > 0).map(([t, v]) => `<i class="${t}${t === 'you' ? ' hache' : ''}" style="width:${v * 100}%"></i>`).join('')}</span>
      <span class="p2-g-mot">${n ? `${atteints} / ${PJ.pluriel(n, 'jalon atteint', 'jalons atteints')}` : o.etat === 'fait' ? `terminé le ${dateDe(o.ago)}` : o.passages ? 'en cours, sans jalon' : 'pas commencé'}${o.passages ? ` · ${exes(o.passages)}` : ''}</span>`;
  }

  /* ── Mode « Dans le temps » : un axe, une barre de quand elle s'y est mise à quand c'est atteint ── */
  function temps(p, rangs, haut) {
    const J = S.gz === 'semaines' ? 46 : 124, objs = rangs.filter((r) => r.sorte === 'obj');
    const debuts = [...objs.map((r) => r.c.debut), ...p.missions.flatMap((m) => m.passes || [])].filter((x) => x != null);
    const K = Math.max(S.gz === 'semaines' ? 13 : 2, Math.ceil(((debuts.length ? Math.max(...debuts) : 0) - MINUIT) / 1440) + (S.gz === 'semaines' ? 1 : 0)), A0 = MINUIT + K * 1440;
    const x = (ago) => Math.round(((A0 - ago) / 1440) * J), xAuj = x(0), GW = Math.max(74, Math.round(J * 0.8)), GAP = 8;
    /* Les fantômes : ce qui n'a pas commencé, à la suite d'aujourd'hui (ou de l'objectif dont il dépend), sans date. */
    const fant = {}; let bout = xAuj + 150;
    objs.forEach((r) => { let cur = xAuj + 34; const avant = r.o.apres && fant['o' + r.o.apres];
      if (avant) cur = Math.max(cur, avant.x1 + 18);
      const aFaire = r.c.jalons.filter((j) => !j.commence);
      if (!aFaire.length && r.c.parti) return;
      const x0 = cur; aFaire.forEach((j) => { j.gx = cur; cur += GW + GAP; });
      fant[cle(r.o)] = { x0, x1: aFaire.length ? cur - GAP : cur + GW }; bout = Math.max(bout, fant[cle(r.o)].x1 + 40); });
    const W = bout, barre = (cls, a, b, titre, dedans) => `<span class="p2-g-b ${cls}" style="left:${a}px;width:${Math.max(10, b - a)}px" title="${h(titre)}">${dedans || ''}</span>`;
    const piste = (r) => {
      if (r.sorte === 'mission') return `<span class="p2-g-fil" style="left:0;width:${xAuj}px"></span>${(r.o.passes || []).filter((a) => a <= A0).map((a) => `<i class="p2-g-pass" style="left:${x(a)}px" title="Passage du ${dateDe(a)} à ${PJ.heure(a)}"></i>`).join('')}
        <span class="p2-g-mot" style="left:${xAuj + 14}px">${PJ.pluriel(r.o.passages, 'passage', 'passages')}</span>`;
      if (r.sorte === 'jalon') { const j = r.x.j, [ton] = PJ.etatJalon(j), mot = motJalon(r.x);
        if (!r.x.commence) return barre('fantome', r.x.gx, r.x.gx + GW, `${j.titre} — pas commencé, sans date`) + '';
        const a = x(r.x.debut), b = x(r.x.fin), dit = `${j.titre} — du ${dateDe(r.x.debut)} ${j.etat === 'atteint' ? `au ${dateDe(j.ago)}` : 'à aujourd\'hui'} · ${mot}`;
        return (j.etat === 'pret' ? barre('work', a, x(r.x.pret), dit) + barre('you hache', x(r.x.pret), b, dit) : barre(ton + (r.x.fin === 0 ? ' encours' : ''), a, b, dit))
          + `<span class="p2-g-mot ${j.etat === 'pret' ? 'you' : ''}" style="left:${Math.max(b, a + 10) + 10}px">${h(mot)}</span>`; }
      const o = r.o, c = r.c, [ton] = PJ.etatObjectif(o), g = fant[cle(o)];
      return (c.parti ? barre(`obj ${ton}${c.enCours ? ' encours' : ''}`, x(c.debut), x(c.fin), `${o.titre} — du ${dateDe(c.debut)} ${c.enCours ? 'à aujourd\'hui, en cours' : `au ${dateDe(c.fin)}`}`) : '')
        + (g ? barre('obj fantome', g.x0, g.x1, `${o.titre} — la suite n'a pas commencé : sans date`) : '')
        + (c.parti && !g ? `<span class="p2-g-mot" style="left:${x(c.fin) + 10}px">${o.etat === 'fait' ? `terminé le ${dateDe(o.ago)}` : ''}</span>` : '');
    };
    /* L'axe : un repère par jour (ou par lundi), puis « à suivre », sans dates. */
    const jours = Array.from({ length: K + 1 }, (_, i) => { const ago = MINUIT + (K - i) * 1440, d = jourDe(ago - 1); return { xi: i * J, d, lundi: d.getDay() === 1, we: d.getDay() === 0 || d.getDay() === 6 }; });
    const axe = jours.map((t, i) => (S.gz === 'semaines' ? (t.lundi ? `<span class="sem" style="left:${t.xi}px">sem. du ${t.d.getDate()} ${MOIS[t.d.getMonth()]}</span>` : '')
      : `<span class="${i === K ? 'auj' : ''}${t.we ? ' we' : ''}" style="left:${t.xi}px;width:${J}px"><b>${t.d.getDate()}</b>${SEM[t.d.getDay()]}${t.d.getDate() === 1 || i === 0 ? ` <em>${MOIS[t.d.getMonth()]}</em>` : ''}</span>`)).join('')
      + `<span class="suite" style="left:${xAuj + 14}px">à suivre · sans date</span>`;
    const fond = `<svg class="p2-g-fond" width="${W}" height="${haut}" aria-hidden="true">${jours.map((t) => `${t.we ? `<rect class="we" x="${t.xi}" y="0" width="${Math.min(J, xAuj - t.xi)}" height="${haut}"/>` : ''}<line class="${t.lundi ? 'lundi' : ''}" x1="${t.xi + 0.5}" y1="0" x2="${t.xi + 0.5}" y2="${haut}"/>`).join('')}
      <rect class="suite" x="${xAuj}" y="0" width="${W - xAuj}" height="${haut}"/></svg>`;
    /* Les flèches : d'un objectif à celui qui en dépend. */
    const fleches = objs.filter((r) => r.o.apres).map((r) => { const de = objs.find((q) => q.o.id === r.o.apres); if (!de) return '';
      const gd = fant[cle(de.o)], ga = fant[cle(r.o)], x1 = gd ? gd.x1 : de.c.parti ? x(de.c.fin) : 0, x2 = ga ? ga.x0 : x(r.c.debut), y1 = de.y + HO / 2, y2 = r.y + HO / 2;
      return x2 >= x1 + 16 ? `<path d="M${x1 + 2} ${y1} H${x2 - 9} V${y2 - 8}"/><path class="tete" d="M${x2 - 13} ${y2 - 9} l4 6 l4 -6"/>`
        : `<path d="M${x1 + 2} ${y1} h10 V${y2 - HO / 2 + 3} H${x2 - 12} V${y2} H${x2 - 4}"/><path class="tete" d="M${x2 - 8} ${y2 - 4} l6 4 l-6 4"/>`; }).join('');
    const sur = `<svg class="p2-g-sur" width="${W}" height="${haut}" aria-hidden="true">${fleches}<line class="auj" x1="${xAuj + 0.5}" y1="0" x2="${xAuj + 0.5}" y2="${haut}"/></svg>`;
    return { W, axe, fond, sur, piste, xAuj };
  }

  /* ── Le panneau de ce qu'on a choisi : un objectif, un jalon, une mission, avec ses gestes ── */
  function panneau(p, choix, mode) {
    const o = choix.o, voir = PJ.voir(p);
    if (!o) return PJ.sc('Rien à montrer', '<p class="p2-sc-text">Ce projet n\'a pas encore d\'objectif.</p>' + (voir ? '' : `<div class="p2-decide"><button class="btn primary" type="button" data-p2="objectifAjouter" data-p="${p.id}">${ico('plus', 'sm')}Ajouter un objectif</button></div>`));
    if (choix.j) { const j = choix.j, x = chrono(o).jalons.find((y) => y.j === j), [ton, lib] = PJ.etatJalon(j), d = `data-p="${p.id}" data-o="${o.id}" data-c="${j.id}"`;
      return PJ.sc(null, `<div class="p2-side-h">${PJ.tuile({ done: 'check', you: 'p2-stop', work: 'play', fail: 'x' }[ton] || 'minus', ton)}<span><b>${h(j.titre)}</b><small>jalon de l'objectif n° ${o.id}</small></span>${PJ.st(ton, lib)}</div>
          ${j.etat === 'pret' && !voir ? `<div class="p2-decide">${PJ.boutons.jalon(p, o, j, 'lg')}</div><p class="p2-hint">${ico('info', 'xs')}Un point d'arrêt : elle attend que tu le valides pour continuer.</p>` : ''}`)
        + PJ.sc('Comment on le vérifie', `<p class="p2-sc-text">${PJ.parts.jalonVerifie(j)}</p>${j.refus ? `<p class="p2-j-no">${ico('x', 'xs')}Tu l'as refusé : « ${h(j.refus)} »</p>` : ''}
          ${j.preuve ? `<details class="p2-proof"><summary>${ico('chev-right', 'xs')}La preuve${j.commit ? ` · commit <code>${j.commit.slice(0, 7)}</code>` : ''}</summary><pre>${h(j.preuve)}</pre></details>` : ''}`)
        + PJ.sc('Dans le temps', PJ.props([['Elle s\'y est mise', x.commence ? `le ${dateDe(x.debut)} à ${PJ.heure(x.debut)}` : '<span class="muted">pas encore : sans date</span>'],
          j.etat === 'atteint' ? ['Atteint', `le ${dateDe(j.ago)} à ${PJ.heure(j.ago)}`] : j.etat === 'pret' ? ['Prêt depuis', PJ.moment(j.ago)] : null, x.commence ? ['Elle y a passé', exes(j.exes)] : null]))
        + PJ.sc('Son objectif', PJ.lie(PJ.fiche(p, 'objectifs', 'diagramme', mode, cle(o)), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))))
        + (voir ? '' : PJ.sc('Gérer', `<div class="p2-decide"><button class="btn" type="button" data-p2="jalonModifier" ${d}>${ico('pen', 'sm')}Modifier le jalon</button><button class="btn danger" type="button" data-p2="jalonRetirer" ${d}>${ico('trash', 'sm')}Retirer le jalon</button></div>`)); }
    const mission = !!o.cadence, [ton, lib] = mission ? ['work', 'en cours'] : PJ.etatObjectif(o), f = (...x) => PJ.fiche(p, 'objectifs', cle(o), ...x), dep = !mission && o.apres && p.objectifs.find((y) => y.id === o.apres);
    return PJ.sc(null, `<div class="p2-side-h">${PJ.tuile(mission ? 'refresh' : 'p2-target', ton)}<span><b>${h(o.titre)}</b><small>${mission ? 'mission' : `objectif n° ${o.id}`}</small></span>${PJ.st(ton, lib)}</div>
        <div class="p2-decide row"><a class="btn" href="${f()}">${ico('expand', 'sm')}L'ouvrir</a>${voir ? '' : `<a class="btn" href="${f('modifier')}">${ico('pen', 'sm')}Modifier</a>`}</div>
        ${voir || mission ? '' : `<div class="p2-decide"><button class="btn" type="button" data-p2="jalonAjouter" data-p="${p.id}" data-o="${o.id}">${ico('plus', 'sm')}Ajouter un jalon</button></div>`}`)
      + (dep ? PJ.sc('Il dépend de', PJ.lie(PJ.fiche(p, 'objectifs', 'diagramme', mode, cle(dep)), 'p2-target', PJ.etatObjectif(dep)[0], dep.titre, `objectif n° ${dep.id} : sa suite attend qu'il soit fini`, PJ.st(...PJ.etatObjectif(dep)))) : '')
      + PJ.parts.coteObjectif(p, o);
  }

  PJ.diagramme = (p, rest) => {
    const mode = rest[0] === 'temps' ? 'temps' : 'avancement', tous = [...p.objectifs, ...p.missions];
    const o = tous.find((x) => cle(x) === rest[1]) || (M.mobile() ? null : p.objectifs.find((x) => x.etat === 'en_cours') || tous[0]) || null;
    const choix = { o, j: o && !o.cadence && rest[2] ? o.jalons.find((j) => String(j.id) === rest[2]) : null };
    const { l, haut } = lignes(p), f = (...x) => PJ.fiche(p, 'objectifs', 'diagramme', ...x), suite = rest.slice(1).filter(Boolean), t = mode === 'temps' ? temps(p, l, haut) : null;
    const rangs = l.map((r) => { const [vers, choisi, contenu] = nom(p, r, mode, choix);
      return `<a class="p2-g-row ${r.sorte}" href="${vers}" data-p2="ganttChoisir" data-va="1" aria-selected="${choisi}" style="height:${r.haut}px"><span class="p2-g-nom">${contenu}</span><span class="p2-g-piste">${t ? t.piste(r) : avancement(p, r)}</span></a>`; }).join('');
    const legende = `<span class="p2-g-leg">${[['done', 'atteint'], ['work', 'en cours'], ['you', 'à toi'], ['fail', 'bloqué'], ['wait', 'à venir']].map(([k, lib]) => `<span><i class="${k}"></i>${lib}</span>`).join('')}${t ? '<span><i class="fantome"></i>pas commencé, sans date</span>' : ''}</span>`;
    const barre = `<div class="pane-head p2-g-bar">${PJ.parts.vueObjectifs(p, 'diagramme')}<div class="seg p2-mode"><a href="${f('avancement', ...suite)}" aria-pressed="${mode === 'avancement'}">Avancement</a><a href="${f('temps', ...suite)}" aria-pressed="${mode === 'temps'}">Dans le temps</a></div>
      ${t ? `<div class="seg"><button type="button" data-p2="ganttZoom" data-c="jours" aria-pressed="${S.gz === 'jours'}">Jours</button><button type="button" data-p2="ganttZoom" data-c="semaines" aria-pressed="${S.gz === 'semaines'}">Semaines</button></div>` : ''}
      ${legende}<span class="grow"></span>${PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="objectifAjouter" data-p="${p.id}">${ico('plus', 'sm')}<span class="lbl">Ajouter un objectif</span></button>`}</div>`;
    const corps = !l.length ? PJ.vide('p2-target', 'Pas encore d\'objectif', 'Le diagramme se dessine dès le premier objectif.')
      : `<div class="p2-gantt ${mode}" data-p2-gantt="${t ? t.xAuj : ''}"><div class="p2-g-in"${t ? ` style="--gw:${t.W}px"` : ''}>
          <div class="p2-g-head"><span class="p2-g-nom">Objectifs, jalons et missions</span><span class="p2-g-piste p2-g-axe">${t ? t.axe : `<span class="av">la part faite</span><span class="av mot">où il en est</span>`}</span></div>
          <div class="p2-g-rows" style="height:${haut}px">${t ? `<div class="p2-g-calque">${t.fond}</div>` : ''}${rangs}${t ? `<div class="p2-g-calque dessus">${t.sur}</div>` : ''}</div></div></div>`;
    return PJ.trio({ cls: 'p2-diag', tete: barre, volets: [['', 'Diagramme']], actif: '', lien: () => location.hash, plein: true, scroll: `diagramme-${p.id}`, corps, cote: panneau(p, choix, mode) });
  };
  A.ganttPlier = (d) => { if (S.gplie.has(d.c)) S.gplie.delete(d.c); else S.gplie.add(d.c); PJ.redessiner(); };
  A.ganttZoom = (d) => { S.gz = d.c; S.gx = null; PJ.redessiner(); };
  A.ganttChoisir = (d, b) => { PJ._ouvrirInfos = true; if (b.getAttribute('href') === location.hash) { S.infos = M.mobile(); PJ.redessiner(); } };
  /* Le diagramme défile en largeur dans son cadre : au premier rendu, aujourd'hui et ce qui suit sont en vue ; ensuite il reste où on l'a laissé. */
  document.addEventListener('scroll', (e) => { if (e.target.matches && e.target.matches('.p2-gantt.temps')) S.gx = e.target.scrollLeft; }, true);
  (PJ.suites = PJ.suites || []).push((body) => {
    const g = body.querySelector('.p2-gantt.temps'); if (!g) return;
    const noms = g.querySelector('.p2-g-nom').offsetWidth;
    const vu = g.clientWidth - noms;
    g.scrollLeft = S.gx != null ? S.gx : Math.max(0, Math.min(g.scrollWidth - g.clientWidth, Number(g.dataset.p2Gantt) - vu * (vu > 600 ? 0.5 : 0.45)));
  });
})();
