/* Projets, seconde maquette — l'onglet Code d'une fiche : Fichiers, Commits, Pull requests, Branches, Issues, CI.
   Chaque vue tient en trois zones : la liste (ou l'arborescence), le contenu sur toute la largeur restante (le fichier,
   le diff unifié ou côte à côte, les volets d'une pull request), et à droite ce qui s'y rattache avec son état.
   « Fusionner » est le geste du propriétaire, avec confirmation (Mika ne fusionne jamais). */
(function () {
  'use strict';
  const { h, ico, av } = M;
  const PJ = window.PJ2, S = PJ.S, A = PJ.actes, F = PJ.formes, C = PJ.champs, CI = PJ.CI;
  Object.assign(S, { branche: null, cb: 'toutes', plie: new Set(), dm: 'unifie' });
  const court = (sha) => sha.slice(0, 7);
  const leCommit = (p, sha) => p.depot.commits.find((c) => c.sha.startsWith(sha));
  const ref = (p, x) => (x.objectif ? [`Objectif n° ${x.objectif}`, PJ.fiche(p, 'objectifs', 'o' + x.objectif), 'p2-target'] : x.ticket ? [`Ticket #${x.ticket}`, PJ.fiche(p, 'tickets', x.ticket), 'p2-ticket'] : null);
  const puce = (p, x) => { const r = ref(p, x); return r ? `<a class="p2-chip" href="${r[1]}">${ico(r[2], 'xs')}${r[0]}</a>` : ''; };
  const branche = (nom) => `<span class="p2-br">${ico('p2-branch', 'xs')}${h(nom)}</span>`;
  /* Ce à quoi un commit, une branche ou une pull request se rattache : son objectif ou son ticket, avec son état. */
  const rattache = (p, x) => { const o = x.objectif && p.objectifs.find((y) => y.id === x.objectif), t = x.ticket && p.tickets.find((y) => y.n === x.ticket);
    return (o ? PJ.lie(PJ.fiche(p, 'objectifs', 'o' + o.id), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))) : '')
      + (t ? PJ.lie(PJ.fiche(p, 'tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#' + t.n, PJ.st(...PJ.etatTicket(t))) : ''); };
  const laCi = (p, sha) => p.depot.ci.find((r) => r.sha === sha);
  const ciLiee = (p, r) => (r ? PJ.lie(PJ.fiche(p, 'code', 'ci', r.id), 'bolt', CI[r.etat][0], `CI n° ${r.id}`, `${r.verifs.filter((v) => v.etat === 'ok').length} vérifications passées sur ${r.verifs.length}`, PJ.st(...CI[r.etat])) : '');
  const rangCommitCote = (p, c) => `<a class="p2-lie" href="${PJ.fiche(p, 'code', 'commits', court(c.sha))}">${PJ.qui(c.par).av('xs')}<span><b>${h(c.msg)}</b><small><code>${court(c.sha)}</code> · ${PJ.quand(c.ago)}</small></span></a>`;

  /* ── Le rendu du code : chasse fixe, numéros de ligne, un peu de couleur ── */
  const RE_PY = /(#.*$)|("""[\s\S]*?"""|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(@\w+)|\b(def|class|import|from|return|if|elif|else|for|in|with|as|try|except|raise|continue|not|and|or|is|lambda|None|True|False|pass|while)\b|\b(\d+(?:\.\d+)?)\b/g;
  const RE_CONF = /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(^\s*-?\s*[\w.-]+(?=\s*[:=]))|(^\[[\w.-]+\])|\b(\d+(?:\.\d+)?)\b/g;
  PJ.colorer = (ligne, chemin) => {
    if (!/\.(py|toml|yml)$/.test(chemin)) return h(ligne);
    const re = /\.py$/.test(chemin) ? RE_PY : RE_CONF;
    re.lastIndex = 0;
    let out = '', i = 0, m;
    while ((m = re.exec(ligne))) {
      if (!m[0].length) { re.lastIndex += 1; continue; }
      out += h(ligne.slice(i, m.index)) + `<span class="t-${m[1] ? 'c' : m[2] ? 's' : m[3] ? 'd' : m[4] ? 'k' : 'n'}">${h(m[0])}</span>`;
      i = m.index + m[0].length;
    }
    return out + h(ligne.slice(i));
  };
  const source = (texte, chemin) => `<div class="p2-codewrap plein"><table class="p2-src"><tbody>${texte.split('\n').map((l, i) => `<tr><td class="ln">${i + 1}</td><td class="cd">${PJ.colorer(l, chemin) || ' '}</td></tr>`).join('')}</tbody></table></div>`;
  /* Un diff : ses lignes numérotées des deux côtés, depuis le texte unifié (ou un fichier entièrement neuf). */
  function lignes(f) {
    if (f.ajout) { const l = f.contenu.split('\n'); return [{ t: 'h', txt: `@@ -0,0 +1,${l.length} @@` }, ...l.map((x, i) => ({ t: '+', b: i + 1, txt: x }))]; }
    let a = 0, b = 0;
    return f.diff.split('\n').map((x) => {
      const m = x.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) { a = +m[1]; b = +m[2]; return { t: 'h', txt: x }; }
      if (x[0] === '+') return { t: '+', b: b++, txt: x.slice(1) };
      if (x[0] === '-') return { t: '-', a: a++, txt: x.slice(1) };
      return { t: ' ', a: a++, b: b++, txt: x.slice(1) };
    });
  }
  const compte = (fichiers) => fichiers.reduce((s, f) => { lignes(f).forEach((l) => { if (l.t === '+') s[0] += 1; if (l.t === '-') s[1] += 1; }); return s; }, [0, 0]);
  const pm = (fichiers) => { const [a, b] = compte(fichiers); return `<span class="p2-pm"><b class="plus">+${a}</b><b class="moins">−${b}</b></span>`; };
  const unifie = (f) => `<table class="p2-diff"><tbody>${lignes(f).map((l) => (l.t === 'h' ? `<tr class="hunk"><td class="ln"></td><td class="ln"></td><td class="cd" colspan="2">${h(l.txt)}</td></tr>`
    : `<tr class="${l.t === '+' ? 'add' : l.t === '-' ? 'del' : ''}"><td class="ln">${l.a || ''}</td><td class="ln">${l.b || ''}</td><td class="sg">${l.t === ' ' ? '' : l.t === '-' ? '−' : '+'}</td><td class="cd">${PJ.colorer(l.txt, f.chemin) || ' '}</td></tr>`)).join('')}</tbody></table>`;
  /* Côte à côte : l'avant à gauche, l'après à droite ; une suite de lignes retirées fait face à celles qui la remplacent. */
  function coteACote(f) {
    const L = lignes(f), rangs = [], cellule = (l, n, cl) => (l ? `<td class="ln">${n}</td><td class="cd ${cl}">${PJ.colorer(l.txt, f.chemin) || ' '}</td>` : '<td class="ln rien"></td><td class="cd rien"></td>');
    for (let i = 0; i < L.length;) {
      const l = L[i];
      if (l.t === 'h') { rangs.push(`<tr class="hunk"><td class="cd" colspan="4">${h(l.txt)}</td></tr>`); i += 1; continue; }
      if (l.t === ' ') { rangs.push(`<tr>${cellule(l, l.a, '')}${cellule(l, l.b, '')}</tr>`); i += 1; continue; }
      const moins = [], plus = [];
      while (i < L.length && L[i].t === '-') moins.push(L[i++]);
      while (i < L.length && L[i].t === '+') plus.push(L[i++]);
      for (let k = 0; k < Math.max(moins.length, plus.length); k += 1) rangs.push(`<tr>${cellule(moins[k], moins[k] && moins[k].a, 'del')}${cellule(plus[k], plus[k] && plus[k].b, 'add')}</tr>`);
    }
    return `<table class="p2-diff cote"><colgroup><col class="n"><col><col class="n"><col></colgroup><tbody>${rangs.join('')}</tbody></table>`;
  }
  const diff = (f, i) => `<section class="p2-file" id="p2-f${i}"><header class="p2-fh">${ico('file', 'sm')}<code>${h(f.chemin)}</code>${f.ajout ? '<span class="p2-new">nouveau</span>' : ''}${pm([f])}</header>
    <div class="p2-codewrap">${S.dm === 'cote' ? coteACote(f) : unifie(f)}</div></section>`;
  const diffs = (fichiers) => `<div class="p2-diffs">${fichiers.map(diff).join('')}</div>`;
  const choixDiff = () => `<div class="seg p2-diffmode" title="La forme du diff"><button type="button" data-p2="diffMode" data-c="unifie" aria-pressed="${S.dm === 'unifie'}">${ico('p2-unifie', 'sm')}Unifié</button><button type="button" data-p2="diffMode" data-c="cote" aria-pressed="${S.dm === 'cote'}">${ico('p2-cote', 'sm')}Côte à côte</button></div>`;
  /* Les fichiers changés, en arborescence, avec leurs lignes ajoutées et retirées : le sommaire du diff. */
  const sommaire = (fichiers) => { const dossiers = [...new Set(fichiers.map((f) => f.chemin.split('/').slice(0, -1).join('/')))];
    return `<p class="p2-sc-sum">${PJ.pluriel(fichiers.length, 'fichier', 'fichiers')}${pm(fichiers)}</p><div class="p2-ftree">${dossiers.map((d) => `${d ? `<span class="p2-fdir">${ico('folder', 'sm')}${h(d)}</span>` : ''}${fichiers.map((f, i) => [f, i]).filter(([f]) => f.chemin.split('/').slice(0, -1).join('/') === d).map(([f, i]) =>
      `<button type="button" class="${d ? 'in' : ''}" data-p2="allerA" data-c="p2-f${i}">${ico('file', 'sm')}<span>${h(f.chemin.split('/').pop())}</span>${f.ajout ? '<i class="p2-new">nouveau</i>' : ''}${pm([f])}</button>`).join('')}`).join('')}</div>`; };
  A.allerA = (d) => { if (S.infos) { S.infos = false; PJ.redessiner(); } const el = document.getElementById(d.c); if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' }); };
  A.diffMode = (d) => { S.dm = d.c; PJ.redessiner(); };
  PJ.parts.preuves = (pr) => `<ol class="p2-jalons">${pr.preuves.map((j) => { const [ton, lib] = PJ.etatJalon(j);
    return `<li class="${ton}"><i>${ico({ done: 'check', you: 'p2-stop', work: 'play' }[ton] || 'minus', 'xs')}</i><div class="p2-j"><div class="p2-j-top"><b>${h(j.titre)}</b>${PJ.st(ton, lib)}</div><p class="p2-j-how">${/^pytest|^pip/.test(j.comment) ? `<code>${h(j.comment)}</code>` : h(j.comment)}</p>
      ${j.preuve ? `<details class="p2-proof"><summary>${ico('chev-right', 'xs')}La preuve</summary><pre>${h(j.preuve)}</pre></details>` : ''}</div></li>`; }).join('')}</ol>`;
  const verifs = (r) => `<ul class="p2-checks">${r.verifs.map((v) => `<li class="${CI[v.etat][0]}"><i>${ico({ ok: 'check', echec: 'x', cours: 'refresh', attente: 'clock' }[v.etat], 'xs')}</i><b>${h(v.nom)}</b><span>${h(v.duree)}</span></li>`).join('')}</ul>`;

  /* ── Fichiers ────────────────────────────────────────────────────── */
  const visibles = (p, b) => Object.keys(p.depot.fichiers).filter((c) => { const s = p.depot.fichiers[c].sur; return !s || s.includes(b) || s.includes('main'); });
  const histoFichier = (p, b, chemin) => p.depot.commits.filter((c) => (c.branche === b || c.branche === 'main') && c.fichiers.some((f) => f.chemin === chemin));
  function arbre(p, b, choisi) {
    const racine = {};
    visibles(p, b).forEach((c) => { let n = racine; c.split('/').forEach((x, i, t) => { n = n[x] = n[x] || (i === t.length - 1 ? c : {}); }); });
    const rang = (n, d, pre) => Object.keys(n).sort((x, y) => (typeof n[x] === 'string') - (typeof n[y] === 'string') || x.localeCompare(y)).map((nom) => {
      const v = n[nom], chemin = pre + nom;
      if (typeof v === 'string') return `<a class="p2-node" style="--d:${d}" href="${PJ.fiche(p, 'code', 'fichiers', b, v)}" aria-selected="${v === choisi}">${ico('file', 'sm')}<span>${h(nom)}</span></a>`;
      const plie = S.plie.has(chemin);
      return `<button class="p2-node dir" style="--d:${d}" type="button" data-p2="plier" data-c="${h(chemin)}">${ico(plie ? 'chev-right' : 'chev-down', 'xs')}${ico('folder', 'sm')}<span>${h(nom)}</span></button>${plie ? '' : rang(v, d + 1, chemin + '/')}`;
    }).join('');
    return rang(racine, 0, '');
  }
  A.plier = (d) => { if (S.plie.has(d.c)) S.plie.delete(d.c); else S.plie.add(d.c); PJ.redessiner(); };
  A.choisirBranche = (d, b) => {
    const p = PJ.proj(d.p), commits = d.c === 'commits';
    M.menu(b, [...(commits ? [{ label: 'Toutes les branches', ico: 'p2-commit', coche: S.cb === 'toutes', action: () => { S.cb = 'toutes'; PJ.redessiner(); } }, 'sep'] : []),
      ...p.depot.branches.map((x) => ({ label: x.nom, ico: 'p2-branch', coche: (commits ? S.cb : d.b) === x.nom, action: () => { if (commits) { S.cb = x.nom; PJ.redessiner(); } else M.go(PJ.fiche(p, 'code', 'fichiers', x.nom)); } }))], { align: 'left' });
  };
  const LANGAGES = { py: 'Python', toml: 'TOML', yml: 'YAML', md: 'Markdown' };
  function vueFichiers(p, rest) {
    const b = p.depot.branches.some((x) => x.nom === rest[0]) ? rest[0] : p.depot.defaut;
    const chemin = rest.slice(1).join('/'), f = p.depot.fichiers[chemin] && visibles(p, b).includes(chemin) ? p.depot.fichiers[chemin] : null;
    const montre = f ? chemin : 'README.md', texte = p.depot.fichiers[montre].txt, hist = histoFichier(p, b, montre), ext = (montre.match(/\.(\w+)$/) || [])[1];
    const liste = `<div class="pane-head"><button class="btn sm p2-brpick" type="button" data-p2="choisirBranche" data-p="${p.id}" data-b="${h(b)}">${ico('p2-branch', 'sm')}<span class="ellipsis">${h(b)}</span>${ico('chev-down', 'xs')}</button></div><div class="pane-scroll p2-tree" data-scroll="arbre">${arbre(p, b, chemin)}</div>`;
    return PJ.trio({ cls: 'etroit', liste, ouvert: !!chemin, retour: [PJ.fiche(p, 'code', 'fichiers', b), 'Fichiers'], volets: [['', 'Fichier']], actif: '', lien: () => location.hash, plein: true, scroll: `fichier-${b}-${montre}`,
      tete: `<div class="pane-head p2-path"><code>${montre.split('/').map((x, i, t) => (i === t.length - 1 ? `<b>${h(x)}</b>` : `${h(x)}<i>/</i>`)).join('')}</code>${f ? '' : '<span class="p2-kind">la page d\'accueil du dépôt</span>'}
        <span class="grow"></span><span class="cnt">${texte.split('\n').length} lignes</span><button class="btn icon ghost sm" type="button" data-p2="copier" data-c="${h(montre)}" title="Copier le chemin">${ico('copy', 'sm')}</button></div>`,
      corps: f || !PJ.md ? source(texte, montre) : `<div class="p2-md p2-readme">${PJ.md(texte, {})}</div>`,
      cote: PJ.sc('Dernier commit', hist[0] ? rangCommitCote(p, hist[0]) : '<p class="p2-none">Aucun commit ne le touche sur cette branche.</p>')
        + PJ.sc('Le fichier', PJ.props([['Branche', branche(b)], ['Lignes', String(texte.split('\n').length)], ['Poids', `${Math.max(1, Math.round(texte.length / 102.4) / 10).toString().replace('.', ',')} Ko`], ['Langage', LANGAGES[ext] || 'texte']]))
        + PJ.sc('Son historique', hist.length > 1 ? hist.slice(1).map((c) => rangCommitCote(p, c)).join('') : '', `<span class="cnt">${hist.length}</span>`) });
  }

  /* ── Commits ─────────────────────────────────────────────────────── */
  function detailCommit(p, c) {
    const q = PJ.qui(c.par), pr = p.depot.pulls.find((x) => x.n === c.fusion || x.commits.includes(c.sha));
    return { scroll: `commit-${c.sha}`, plein: true, volets: [['', 'Diff']], actif: '', lien: () => location.hash, outils: c.fichiers.length ? choixDiff() : '',
      tete: PJ.parts.entete({ tuile: PJ.tuile(c.fusion ? 'p2-merge' : 'p2-commit', c.fusion ? 'done' : ''), sur: 'Commit', titre: c.msg,
        meta: `<span class="p2-by">${q.av('xs')}${c.par === 'adrien' ? 'toi' : h(q.nom)}</span><span>${PJ.moment(c.ago)}</span>${branche(c.branche)}`,
        droite: `<button class="p2-sha" type="button" data-p2="copier" data-c="${c.sha}" title="Copier l'empreinte">${ico('copy', 'xs')}<code>${c.sha}</code></button>` }),
      corps: `<div class="p2-diffzone">${c.corps ? `<p class="p2-lede pre">${h(c.corps)}</p>` : ''}${c.fichiers.length ? diffs(c.fichiers)
        : `<a class="p2-linkcard" href="${PJ.fiche(p, 'code', 'pulls', c.fusion, 'fichiers')}">${PJ.tuile('p2-pr', 'done')}<span><b>Un commit de fusion</b><small>il réunit la pull request n° ${c.fusion}${pr ? ` « ${h(pr.titre)} »` : ''} dans ${h(c.branche)} : son diff est dans la pull request</small></span>${ico('chev-right', 'sm')}</a>`}</div>`,
      cote: PJ.sc('Fichiers changés', c.fichiers.length ? sommaire(c.fichiers) : '')
        + PJ.sc('Le commit', PJ.props([['Auteur', `<span class="p2-by">${q.av('xs')}${c.par === 'adrien' ? 'toi' : h(q.nom)}</span>`], ['Quand', PJ.moment(c.ago)], ['Branche', branche(c.branche)], ['Empreinte', `<code>${court(c.sha)}</code>`]]))
        + PJ.sc('Ce qui est lié', rattache(p, c) + PJ.parts.prLiee(p, pr) + ciLiee(p, laCi(p, c.sha))) };
  }
  const rangCommit = (p, c, x) => { const r = ref(p, c); return `<a class="p2-cm" href="${PJ.fiche(p, 'code', 'commits', court(c.sha))}" aria-selected="${c === x}"><i class="${c.fusion ? 'done' : ''}"></i>
    <span class="li-title">${h(c.msg)}</span><span class="p2-row-sub"><code>${court(c.sha)}</code>${branche(c.branche)}${r ? `<span>${r[0].replace('Objectif n° ', 'obj. ').replace('Ticket ', '')}</span>` : ''}${c.fichiers.length ? pm(c.fichiers) : '<time>fusion</time>'}</span></a>`; };
  const parJour = PJ.parJour = (l, rang) => { let jour = ''; return l.map((c) => { const j = PJ.jour(c.ago), t = j !== jour ? `<div class="p2-day">${(jour = j)}</div>` : ''; return t + rang(c); }).join(''); };
  function vueCommits(p, rest) {
    const l = p.depot.commits.filter((c) => S.cb === 'toutes' || c.branche === S.cb);
    const x = (rest[0] && leCommit(p, rest[0])) || PJ.choisi(l, (c) => court(c.sha), rest[0]);   // un commit nommé par l'adresse s'ouvre même hors du filtre
    const liste = `<div class="pane-head"><button class="btn sm p2-brpick" type="button" data-p2="choisirBranche" data-p="${p.id}" data-c="commits">${ico('p2-branch', 'sm')}<span class="ellipsis">${S.cb === 'toutes' ? 'Toutes les branches' : h(S.cb)}</span>${ico('chev-down', 'xs')}</button>
        <span class="cnt">${PJ.pluriel(l.length, 'commit', 'commits')}</span></div><div class="pane-scroll p2-timeline" data-scroll="commits">${parJour(l, (c) => rangCommit(p, c, x))}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!x, retour: [PJ.fiche(p, 'code', 'commits'), 'Commits'] }, x ? detailCommit(p, x) : { vide: PJ.vide('p2-commit', 'Choisis un commit', 'Son message, ses fichiers et son diff s\'ouvrent ici.') }));
  }

  /* ── Pull requests ───────────────────────────────────────────────── */
  /* Les fichiers d'une pull request : un fichier né dans la branche se montre entier, les autres cumulent leurs diffs. */
  const fichiersPr = (p, pr) => {
    const vus = new Map();
    pr.commits.slice().reverse().forEach((sha) => leCommit(p, sha).fichiers.forEach((f) => {
      const deja = vus.get(f.chemin), final = p.depot.fichiers[f.chemin];
      if (f.ajout || (deja && deja.ajout)) vus.set(f.chemin, { chemin: f.chemin, ajout: true, contenu: final ? final.txt : f.contenu });
      else if (deja) deja.diff += '\n' + f.diff;
      else vus.set(f.chemin, { chemin: f.chemin, diff: f.diff });
    }));
    return [...vus.values()];
  };
  function detailPr(p, pr, volet) {
    const peut = PJ.fusionnable(p, pr), q = PJ.qui(pr.par), fich = fichiersPr(p, pr), f = (...x) => PJ.fiche(p, 'code', 'pulls', pr.n, ...x), run = PJ.ci(p, pr), voir = PJ.voir(p);
    const v = ['commits', 'fichiers', 'echanges', 'modifier'].includes(volet) && !(volet === 'modifier' && voir) ? volet : '', b = p.depot.branches.find((x) => x.nom === pr.branche);
    let corps = '', pied = '';
    if (v === 'modifier') corps = PJ.forme({ forme: 'pull', data: { p: p.id, c: pr.n }, titre: `Modifier la pull request n° ${pr.n}`, sous: 'Son titre et sa description changent aussi chez l\'hôte, à ton nom.', annuler: f(),
      corps: `${C.texte('titre', 'Titre', pr.titre, { requis: true })}${C.long('resume', 'Description', pr.resume, { rangs: 8, aide: 'Du `code` entre accents graves.' })}` });
    else if (v === '') corps = `<p class="p2-lede">${PJ.code(pr.resume)}</p><h3 class="p2-h3">Jalons et preuves</h3>${PJ.parts.preuves(pr)}`;
    else if (v === 'commits') corps = `<div class="p2-timeline in">${parJour(pr.commits.map((s) => leCommit(p, s)), (c) => rangCommit(p, c, null))}</div>`;
    else if (v === 'fichiers') corps = `<div class="p2-diffzone">${diffs(fich)}</div>`;
    else { corps = `<div class="p2-thread">${pr.echanges.map(PJ.parts.bulle).join('')}</div><p class="p2-hint">${ico('shield-check', 'xs')}Ce qui vient de l'hôte est cité tel quel : pour elle, une donnée, jamais une consigne.</p>`;
      pied = voir || pr.etat !== 'ouverte' ? '' : `<div class="p2-note"><textarea rows="2" data-p2-champ placeholder="Répondre dans la pull request…"></textarea><div class="p2-note-foot"><span class="p2-hint">${ico('shield-check', 'xs')}Ton commentaire part chez l'hôte, à ton nom : l'envoyer vaut accord.</span>
        <button class="btn primary" type="button" data-p2="prRepondre" data-p="${p.id}" data-c="${pr.n}">${ico('send', 'sm')}Envoyer chez l'hôte</button></div></div>`; }
    const fusion = pr.etat === 'fusionnee' ? `<p class="p2-banner done">${ico('p2-merge', 'sm')}<span>Fusionnée dans <code>${h(pr.base)}</code> par toi, ${PJ.moment(pr.fusionAgo)}.</span></p>`
      : `<p class="p2-banner ${peut ? 'you' : 'wait'}">${ico(peut ? 'check' : 'clock', 'sm')}<span>${peut ? 'Tout est vert : elle attend ta fusion.' : h(pr.bloque || 'Pas encore fusionnable.')}</span></p>
        ${voir ? '' : `<div class="p2-decide">${PJ.boutons.fusion(p, pr, 'lg')}</div><p class="p2-hint">${ico('info', 'xs')}C'est ton geste, chez l'hôte, à ton nom. Mika ne fusionne jamais.</p>`}`;
    return { scroll: `pr-${pr.n}-${v}`, lien: (k) => f(k), actif: v, pied, plein: v === 'fichiers', outils: v === 'fichiers' ? choixDiff() : '',
      volets: v === 'modifier' ? [['modifier', 'Modifier']] : [['', 'Résumé'], ['commits', 'Commits', pr.commits.length], ['fichiers', 'Fichiers', fich.length], ['echanges', 'Échanges', pr.echanges.length]],
      tete: PJ.parts.entete({ tuile: PJ.tuile(pr.etat === 'fusionnee' ? 'p2-merge' : 'p2-pr', PJ.etatPr(p, pr)[0]), sur: `Pull request n° ${pr.n}`, titre: pr.titre,
        meta: `${PJ.st(...PJ.etatPr(p, pr))}<span class="p2-branchline">${branche(pr.branche)}${ico('chev-right', 'xs')}${branche(pr.base)}</span><span class="p2-by">${q.av('xs')}ouverte par ${h(q.nom)} ${PJ.quand(pr.ago)}</span>`,
        droite: `${voir ? '' : `<a class="btn${v === 'modifier' ? ' on' : ''}" href="${f(v === 'modifier' ? '' : 'modifier')}">${ico('pen', 'sm')}Modifier</a>`}<button class="btn" type="button" data-p2="hote" data-c="${h(p.depot.hote)}/pull/${pr.n}">${ico('external', 'sm')}<span class="lbl">Voir chez l'hôte</span></button>` }),
      corps,
      cote: PJ.sc('Fusion', fusion)
        + PJ.sc('Relecture', `<div class="p2-etat ${pr.relecture.etat === 'ok' ? 'done' : 'wait'}">${PJ.tuile('eye', pr.relecture.etat === 'ok' ? 'done' : 'wait')}<span><b>${h(pr.relecture.mot)}</b><small>${h(pr.relecture.texte)}</small></span></div>`)
        + PJ.sc('Vérifications', run.verifs ? `${verifs(run)}<a class="p2-more" href="${PJ.fiche(p, 'code', 'ci', run.id)}">CI n° ${run.id} · ${h(run.duree)}${ico('chev-right', 'xs')}</a>` : '<p class="p2-none">La CI n\'a pas encore tourné.</p>', run.id ? PJ.st(...CI[run.etat]) : '')
        + PJ.sc('Conflits', `<div class="p2-etat">${PJ.tuile('p2-merge', pr.conflits ? 'fail' : 'done')}<span><b>${pr.conflits ? 'À résoudre' : 'Aucun'}</b><small>avec ${h(pr.base)}${b ? ` · ${b.avance} en avance, ${b.retard} en retard` : ''}</small></span></div>`)
        + PJ.sc('Ce qui est lié', rattache(p, pr)) };
  }
  function vuePulls(p, rest) {
    const l = p.depot.pulls, pr = PJ.choisi(l, (x) => x.n, rest[0]);
    const liste = `<div class="pane-head"><h2>Pull requests</h2><span class="cnt">${l.filter((x) => x.etat === 'ouverte').length} ouvertes</span></div><div class="pane-scroll" data-scroll="pulls">${l.map((x) =>
      `<a class="li p2-row${PJ.fusionnable(p, x) ? ' atoi' : ''}" href="${PJ.fiche(p, 'code', 'pulls', x.n)}" aria-selected="${x === pr}">${PJ.tuile(x.etat === 'fusionnee' ? 'p2-merge' : 'p2-pr', PJ.etatPr(p, x)[0])}<span class="li-main"><span class="li-title">${h(x.titre)}</span>
        <span class="p2-row-sub">${PJ.st(...PJ.etatPr(p, x))}<span>n° ${x.n}</span><time>${PJ.quand(x.fusionAgo != null ? x.fusionAgo : x.ago)}</time></span></span></a>`).join('')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!pr, retour: [PJ.fiche(p, 'code', 'pulls'), 'Pull requests'] }, pr ? detailPr(p, pr, rest[1]) : { vide: PJ.vide('p2-pr', 'Choisis une pull request', 'Son état, ses commits et son diff s\'ouvrent ici.') }));
  }
  A.hote = (d) => M.toast(`Maquette : ouvrirait ${d.c} dans un nouvel onglet.`, { ico: 'external' });
  F.pull = (v, d) => { const p = PJ.proj(d.p), pr = p.depot.pulls.find((x) => String(x.n) === d.c);
    Object.assign(pr, { titre: v.titre, resume: v.resume }); pr.echanges.push({ de: 'evenement', ago: 0, ico: 'pen', texte: 'Tu as modifié le titre et la description' });
    PJ.geste(p, `Tu as modifié la pull request n° ${pr.n}`, 'p2-pr', ['code', 'pulls', pr.n]); M.toast(`Pull request n° ${pr.n} modifiée, ici et chez l'hôte.`); M.go(PJ.fiche(p, 'code', 'pulls', pr.n)); };
  A.prRepondre = (d, b) => { const c = b.closest('.p2-note').querySelector('[data-p2-champ]'), texte = c.value.trim();
    if (!texte) { c.focus(); c.classList.add('p2-manque'); return; }
    const p = PJ.proj(d.p), pr = p.depot.pulls.find((x) => String(x.n) === d.c);
    pr.echanges.push({ de: 'adrien', ago: 0, texte }); PJ.geste(p, `Tu as écrit dans la pull request n° ${pr.n}`, 'p2-pr', ['code', 'pulls', pr.n, 'echanges']);
    PJ.redessiner(); M.toast('Commentaire envoyé chez l\'hôte, à ton nom.', { ico: 'send' }); };
  A.fusionner = (d) => {
    const p = PJ.proj(d.p), pr = p.depot.pulls.find((x) => String(x.n) === d.c), fich = fichiersPr(p, pr), [plus, moins] = compte(fich);
    PJ.confirmer({ titre: `Fusionner la pull request n° ${pr.n} ?`, bouton: `Fusionner dans ${pr.base}`, ico: 'p2-merge', corps: `<div class="stack p2-merge">
        <b class="p2-merge-t">${h(pr.titre)}</b><span class="p2-branchline">${branche(pr.branche)}${ico('chev-right', 'xs')}${branche(pr.base)}</span>
        <ul class="p2-merge-facts"><li>${ico('p2-commit', 'sm')}${PJ.pluriel(pr.commits.length, 'commit', 'commits')}</li><li>${ico('file', 'sm')}${PJ.pluriel(fich.length, 'fichier', 'fichiers')}</li><li><span class="p2-pm"><b class="plus">+${plus}</b><b class="moins">−${moins}</b></span></li>
          <li>${ico('check', 'sm')}relue, CI passée, aucun conflit</li></ul>
        <label class="field"><span>Comment</span><div class="seg" data-seg="fusion"><button type="button" data-v="fusion" aria-pressed="true">Un commit de fusion</button><button type="button" data-v="squash" aria-pressed="false">Tout en un commit</button></div></label>
        <label class="row"><input type="checkbox" name="supprimer" checked><span>Supprimer la branche <code>${h(pr.branche)}</code> après la fusion</span></label>
        <p class="small muted">C'est toi qui fusionnes, chez l'hôte, à ton nom. Mika ne fusionne jamais.</p></div>`,
      alors: (racine) => {
        const supprime = racine.querySelector('[name="supprimer"]').checked, t = p.tickets.find((x) => x.n === pr.ticket);
        Object.assign(pr, { etat: 'fusionnee', fusionAgo: 0 });
        const sha = 'f19a0c4d2b7' + pr.n;
        p.depot.commits.unshift({ sha, msg: `Fusion de la pull request n° ${pr.n} : ${pr.titre}`, branche: pr.base, ticket: pr.ticket, objectif: pr.objectif, ago: 0, par: 'adrien', fusion: pr.n,
          corps: `Fusionnée par toi depuis cet écran.${supprime ? ` La branche ${pr.branche} a été supprimée.` : ''}`, fichiers: [] });
        Object.values(p.depot.fichiers).forEach((x) => { if (x.sur && x.sur.includes(pr.branche)) x.sur.push('main'); });
        if (supprime) { p.depot.branches = p.depot.branches.filter((x) => x.nom !== pr.branche); p.depot.commits.forEach((c) => { if (c.branche === pr.branche) c.branche = pr.base; }); if (S.cb === pr.branche) S.cb = 'toutes'; }
        p.depot.ci.unshift({ id: Math.max(...p.depot.ci.map((c) => c.id)) + 1, sha, etat: 'cours', ago: 0, duree: 'vient de partir', verifs: [{ nom: 'ruff check', etat: 'cours', duree: 'en cours' }, { nom: 'pytest · Python 3.12', etat: 'attente', duree: 'en file' }, { nom: 'pytest · Python 3.13', etat: 'attente', duree: 'en file' }] });
        if (t) { Object.assign(t, { etape: 'traite', main: null, attend: null, ago: 0 }); t.fil.push({ de: 'evenement', ago: 0, texte: `Tu as fusionné la pull request n° ${pr.n}` }); }
        PJ.geste(p, `Tu as fusionné la pull request n° ${pr.n} dans ${pr.base}`, 'p2-merge', ['code', 'pulls', pr.n], { ticket: pr.ticket, objectif: pr.objectif });
        PJ.redessiner(); M.toast(`Pull request n° ${pr.n} fusionnée dans ${pr.base}.`, { ico: 'p2-merge' });
      } });
  };

  /* ── Branches : un tableau sur toute la largeur ; une branche choisie ouvre à droite ce qu'elle a d'avance ── */
  function panneauBranche(p, b) {
    const pr = p.depot.pulls.find((x) => x.n === b.pr), commits = p.depot.commits.filter((c) => c.branche === b.nom).slice(0, b.defaut ? 5 : 99), fich = pr ? fichiersPr(p, pr) : [];
    return PJ.sc(null, `<div class="p2-side-h">${PJ.tuile('p2-branch', b.defaut ? '' : 'work')}<span><b><code>${h(b.nom)}</code></b><small>${b.defaut ? 'la branche par défaut : tout y entre par une pull request' : `${PJ.pluriel(b.avance, 'commit', 'commits')} d'avance sur ${h(p.depot.defaut)}, ${b.retard} de retard`}</small></span></div>
        <div class="p2-decide row"><a class="btn" href="${PJ.fiche(p, 'code', 'fichiers', b.nom)}">${ico('folder', 'sm')}Ses fichiers</a><button class="btn" type="button" data-p2="voirCommits" data-p="${p.id}" data-c="${h(b.nom)}">${ico('p2-commit', 'sm')}Ses commits</button></div>`)
      + PJ.sc('Sa pull request', PJ.parts.prLiee(p, pr) || (b.defaut ? '' : '<p class="p2-none">Pas encore de pull request.</p>'))
      + PJ.sc('Pour', rattache(p, b))
      + PJ.sc(b.defaut ? 'Ses derniers commits' : `Ce qu'elle a d'avance`, commits.map((c) => rangCommitCote(p, c)).join(''), `<span class="cnt">${commits.length}</span>`)
      + PJ.sc('Fichiers changés', fich.length ? sommaireLiens(p, pr, fich) : '');
  }
  const sommaireLiens = (p, pr, fich) => `<p class="p2-sc-sum">${PJ.pluriel(fich.length, 'fichier', 'fichiers')}${pm(fich)}</p><div class="p2-ftree">${fich.map((f) => `<a href="${PJ.fiche(p, 'code', 'pulls', pr.n, 'fichiers')}">${ico('file', 'sm')}<span>${h(f.chemin)}</span>${pm([f])}</a>`).join('')}</div>`;
  A.voirCommits = (d) => { S.cb = d.c; M.go(PJ.fiche(PJ.proj(d.p), 'code', 'commits')); };
  function vueBranches(p, rest) {
    const l = p.depot.branches, nom = rest.join('/'), b = l.find((x) => x.nom === nom) || (M.mobile() ? null : l.find((x) => !x.defaut) || l[0]);
    const max = Math.max(1, ...l.map((x) => Math.max(x.avance || 0, x.retard || 0))), f = (x) => PJ.fiche(p, 'code', 'branches', x.nom);
    if (M.mobile()) return PJ.trio({ liste: `<div class="pane-scroll" data-scroll="branches">${l.map((x) => { const pr = p.depot.pulls.find((y) => y.n === x.pr);
      return `<a class="li p2-row" href="${f(x)}">${PJ.tuile('p2-branch', x.defaut ? '' : 'work')}<span class="li-main"><span class="li-title mono">${h(x.nom)}</span><span class="p2-row-sub">${pr ? PJ.st(...PJ.etatPr(p, pr)) : `<span>${x.defaut ? 'par défaut' : 'sans pull request'}</span>`}</span></span></a>`; }).join('')}</div>`,
      ouvert: !!b, retour: [PJ.fiche(p, 'code', 'branches'), 'Branches'], volets: [['', 'Branche']], actif: '', lien: () => location.hash, scroll: 'branche', corps: b ? `<div class="p2-flat">${panneauBranche(p, b)}</div>` : '' });
    const table = `<div class="p2-tablefull"><table class="tbl p2-branches"><thead><tr><th>Branche</th><th>Pour</th><th>Retard · avance sur ${h(p.depot.defaut)}</th><th>Dernier commit</th><th>Pull request</th><th>CI</th></tr></thead><tbody>
      ${l.map((x) => { const c = p.depot.commits.find((y) => y.branche === x.nom), pr = p.depot.pulls.find((y) => y.n === x.pr), run = c && laCi(p, c.sha), r = ref(p, x);
        return `<tr class="${x === b ? 'on' : ''}" data-p2="ligne" data-c="${f(x)}"><td><a class="p2-brname" href="${f(x)}">${ico('p2-branch', 'sm')}<code>${h(x.nom)}</code></a>${x.defaut ? '<span class="p2-kind">par défaut</span>' : ''}</td><td>${r ? `<span class="p2-chip plain">${ico(r[2], 'xs')}${r[0]}</span>` : '<span class="muted">—</span>'}</td>
          <td>${x.defaut ? '<span class="muted">—</span>' : `<span class="p2-div"><b>${x.retard}</b><span class="g"><i style="width:${(x.retard / max) * 100}%"></i></span><span class="d"><i style="width:${(x.avance / max) * 100}%"></i></span><b>${x.avance}</b></span>`}</td>
          <td>${c ? `<span class="p2-lastc"><code>${court(c.sha)}</code><span class="ellipsis">${h(c.msg)}</span><time>${PJ.quand(c.ago)}</time></span>` : ''}</td>
          <td>${pr ? `<span class="p2-prlink"><span class="p2-num">n° ${pr.n}</span>${PJ.st(...PJ.etatPr(p, pr))}</span>` : '<span class="muted">—</span>'}</td><td>${run ? PJ.st(...CI[run.etat]) : '<span class="muted">—</span>'}</td></tr>`; }).join('')}</tbody></table>
      <p class="p2-hint">${ico('info', 'xs')}Elle ouvre une branche par objectif ou par ticket, et ne pousse jamais sur ${h(p.depot.defaut)} : tout y entre par une pull request que tu fusionnes.</p></div>`;
    return PJ.trio({ volets: [['', 'Branches']], actif: '', lien: () => location.hash, plein: true, scroll: 'branches', corps: table, cote: b ? panneauBranche(p, b) : '' });
  }
  A.ligne = (d) => M.go(d.c);

  /* ── Issues ──────────────────────────────────────────────────────── */
  function detailIssue(p, i, volet) {
    const q = PJ.qui(i.par), t = p.tickets.find((x) => x.n === i.ticket), accord = i.n === 9 && p.accords[0], pr = t && p.depot.pulls.find((x) => x.n === t.pr), f = (...x) => PJ.fiche(p, 'code', 'issues', i.n, ...x), voir = PJ.voir(p);
    const v = volet === 'echanges' ? 'echanges' : '';
    const corps = v === '' ? (q.dehors ? PJ.parts.dehors(`${q.nom}, chez l'hôte`, i.texte) : `<div class="p2-md court">${PJ.md(i.texte, {})}</div>`)
      : `${i.commentaires.length || accord ? '' : '<p class="p2-none">Personne n\'a encore répondu.</p>'}<div class="p2-thread">${i.commentaires.map(PJ.parts.bulle).join('')}</div>
        ${accord ? `<section class="p2-plan you"><header>${ico('shield-check')}<b>Sa réponse attend ton accord</b>${PJ.st('you', 'à toi')}</header><p class="p2-plan-note">${av('mika', 'xs')}<span>${h(accord.texte)}</span></p>${voir ? '' : `<div class="p2-acts">${PJ.boutons.accord(p, accord, 'lg')}</div>`}</section>` : ''}`;
    return { scroll: `issue-${i.n}-${v}`, lien: (k) => f(k), actif: v, volets: [['', 'Description'], ['echanges', 'Échanges', i.commentaires.length + (accord ? 1 : 0)]],
      tete: PJ.parts.entete({ tuile: PJ.tuile('p2-issue', i.etat === 'ouverte' ? 'wait' : 'done'), sur: `Issue n° ${i.n}`, titre: i.titre,
        meta: `${PJ.st(i.etat === 'ouverte' ? 'wait' : 'done', i.etat === 'ouverte' ? 'ouverte' : 'fermée')}<span class="p2-by">${q.av('xs')}par ${h(q.nom)}${q.dehors ? ', que personne ne connaît' : ''}</span><span>${PJ.moment(i.ago)}</span>`,
        droite: `<button class="btn" type="button" data-p2="hote" data-c="${h(p.depot.hote)}/issues/${i.n}">${ico('external', 'sm')}<span class="lbl">Voir chez l'hôte</span></button>` }),
      corps,
      cote: PJ.sc('Chez l\'hôte', PJ.props([['État', PJ.st(i.etat === 'ouverte' ? 'wait' : 'done', i.etat === 'ouverte' ? 'ouverte' : 'fermée')], ['Ouverte par', `<span class="p2-by">${q.av('xs')}${h(q.nom)}</span>${q.dehors ? PJ.st('out', 'inconnu') : ''}`], ['Le', PJ.moment(i.ago)],
          ['Étiquettes', (i.etiquettes || []).map((e) => `<span class="p2-label">${h(e)}</span>`).join('') || '<span class="muted">aucune</span>']]))
        + PJ.sc(t && t.attend === 'accepter' ? 'Le ticket qu\'elle propose' : 'Le ticket lié', t ? PJ.lie(PJ.fiche(p, 'tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, `#${t.n} · ${h(t.sorte)}`, PJ.st(...PJ.etatTicket(t)))
          + (t.attend === 'accepter' && !voir ? `<div class="p2-decide">${PJ.boutons.ticket(p, t.n)}</div>` : '') : '<p class="p2-none">Aucun ticket ne lui est lié.</p>')
        + PJ.sc('La pull request liée', PJ.parts.prLiee(p, pr) || '<p class="p2-none">Pas encore de pull request.</p>')
        + (accord && !voir ? PJ.sc('Ton accord', `<p class="p2-sc-text">Elle voudrait répondre à ${h(q.nom)} : sa réponse attend ton accord.</p><div class="p2-decide"><a class="btn" href="${f('echanges')}">Lire sa réponse${ico('chev-right', 'sm')}</a></div>`) : '') };
  }
  function vueIssues(p, rest) {
    const l = p.depot.issues, i = PJ.choisi(l, (x) => x.n, rest[0]);
    const liste = `<div class="pane-head"><h2>Issues</h2><span class="cnt">${l.filter((x) => x.etat === 'ouverte').length} ouvertes</span></div><div class="pane-scroll" data-scroll="issues">${l.map((x) =>
      `<a class="li p2-row" href="${PJ.fiche(p, 'code', 'issues', x.n)}" aria-selected="${x === i}">${PJ.tuile('p2-issue', x.etat === 'ouverte' ? 'wait' : 'done')}<span class="li-main"><span class="li-title">${h(x.titre)}</span>
        <span class="p2-row-sub">${PJ.st(x.etat === 'ouverte' ? 'wait' : 'done', x.etat === 'ouverte' ? 'ouverte' : 'fermée')}${x.par.dehors ? PJ.st('out', 'd\'un inconnu') : `<span>n° ${x.n}</span>`}<time>${PJ.quand(x.ago)}</time></span></span></a>`).join('')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!i, retour: [PJ.fiche(p, 'code', 'issues'), 'Issues'] }, i ? detailIssue(p, i, rest[1]) : { vide: PJ.vide('p2-issue', 'Choisis une issue', 'Son texte et le ticket qui lui est lié s\'ouvrent ici.') }));
  }

  /* ── CI ──────────────────────────────────────────────────────────── */
  function detailCi(p, r, volet) {
    const c = leCommit(p, r.sha), pr = p.depot.pulls.find((x) => x.ci === r.id || x.commits.includes(r.sha)), journal = r.verifs.find((v) => v.journal), f = (...x) => PJ.fiche(p, 'code', 'ci', r.id, ...x);
    const v = volet === 'journal' && journal ? 'journal' : '';
    return { scroll: `ci-${r.id}-${v}`, lien: (k) => f(k), actif: v, volets: [['', 'Vérifications', `${r.verifs.filter((x) => x.etat === 'ok').length}/${r.verifs.length}`], ...(journal ? [['journal', 'La fin du journal']] : [])],
      tete: PJ.parts.entete({ tuile: PJ.tuile('bolt', CI[r.etat][0]), sur: `CI n° ${r.id}`, titre: c.msg, meta: `${PJ.st(...CI[r.etat])}<span>${PJ.moment(r.ago)}</span><span>${ico('clock', 'xs')}${h(r.duree)}</span>`,
        droite: PJ.voir(p) ? '' : `<button class="btn" type="button" data-p2="relancer" data-p="${p.id}" data-c="${r.id}"${r.etat === 'cours' ? ' disabled' : ''}>${ico('refresh', 'sm')}<span class="lbl">Relancer</span></button>` }),
      corps: v === 'journal' ? PJ.parts.dehors(`la sortie de « ${journal.nom} », chez l'hôte`, journal.journal, true)
        : `<ul class="p2-checks grand">${r.verifs.map((x) => `<li class="${CI[x.etat][0]}"><i>${ico({ ok: 'check', echec: 'x', cours: 'refresh', attente: 'clock' }[x.etat], 'xs')}</i><b>${h(x.nom)}</b><span>${h(x.duree)}</span>${PJ.st(...CI[x.etat])}</li>`).join('')}</ul>
          ${journal ? `<a class="p2-linkcard" href="${f('journal')}">${PJ.tuile('terminal', 'fail')}<span><b>La fin du journal de « ${h(journal.nom)} »</b><small>ce que l'hôte a écrit avant d'échouer</small></span>${ico('chev-right', 'sm')}</a>` : ''}`,
      cote: PJ.sc('Le commit vérifié', rangCommitCote(p, c) + `<p class="p2-branchline">${branche(c.branche)}</p>`) + PJ.sc('La pull request', PJ.parts.prLiee(p, pr)) + PJ.sc('Pour', rattache(p, c))
        + PJ.sc('En bref', PJ.props([['État', PJ.st(...CI[r.etat])], ['Lancée', PJ.moment(r.ago)], ['Durée', h(r.duree)]])) };
  }
  function vueCi(p, rest) {
    const l = p.depot.ci, r = PJ.choisi(l, (x) => x.id, rest[0]);
    const liste = `<div class="pane-head"><h2>Vérifications</h2><span class="cnt">par commit</span></div><div class="pane-scroll" data-scroll="ci">${l.map((x) => { const c = leCommit(p, x.sha);
      return `<a class="li p2-row" href="${PJ.fiche(p, 'code', 'ci', x.id)}" aria-selected="${x === r}">${PJ.tuile('bolt', CI[x.etat][0])}<span class="li-main"><span class="li-title">${h(c.msg)}</span>
        <span class="p2-row-sub">${PJ.st(...CI[x.etat])}<code>${court(x.sha)}</code><time>${PJ.quand(x.ago)}</time></span></span></a>`; }).join('')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!r, retour: [PJ.fiche(p, 'code', 'ci'), 'CI'] }, r ? detailCi(p, r, rest[1]) : { vide: PJ.vide('bolt', 'Choisis une exécution', 'Ses vérifications s\'ouvrent ici.') }));
  }
  A.relancer = (d) => {
    const r = PJ.proj(d.p).depot.ci.find((x) => String(x.id) === d.c);
    Object.assign(r, { etat: 'cours', ago: 0, duree: 'vient de repartir' });
    r.verifs.forEach((v, i) => Object.assign(v, { etat: i ? 'attente' : 'cours', duree: i ? 'en file' : 'en cours', journal: '' }));
    PJ.redessiner(); M.toast(`CI n° ${r.id} relancée.`, { ico: 'refresh' });
  };

  PJ.onglets.code = (p, rest) => {
    if (!p.depot) return PJ.vide('code', 'Pas de dépôt', PJ.voir(p) ? 'Le dépôt de ce projet ne t\'est pas ouvert.' : 'Ce projet ne produit pas de code : il n\'a ni fichiers, ni commits, ni pull requests.');
    const vues = { fichiers: vueFichiers, commits: vueCommits, pulls: vuePulls, branches: vueBranches, issues: vueIssues, ci: vueCi };
    const v = vues[rest[0]] ? rest[0] : 'fichiers', d = p.depot;
    return PJ.sous(p, 'code', [['fichiers', 'Fichiers'], ['commits', 'Commits', d.commits.length], ['pulls', 'Pull requests', d.pulls.filter((x) => x.etat === 'ouverte').length], ['branches', 'Branches', d.branches.length],
      ['issues', 'Issues', d.issues.filter((x) => x.etat === 'ouverte').length], ['ci', 'CI']], v,
      `<button class="p2-remote" type="button" data-p2="hote" data-c="${h(d.hote)}">${ico('globe', 'sm')}<span>${h(d.hote)}</span></button><span class="p2-sync">${ico('check', 'xs')}à jour · ${PJ.quand(d.synchro)}</span>`) + `<div class="p2-under">${vues[v](p, rest.slice(1))}</div>`;
  };
})();
