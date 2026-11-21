/* Projets, seconde maquette — l'onglet Documentation d'une fiche : Pages, Images, Décisions.
   La documentation d'un projet est un espace à part de son dépôt : des pages .md, des dossiers, des images.
   On la lit en trois zones (l'arborescence, la page, et à droite son sommaire, sa dernière modification, ses versions).
   On l'écrit dans la page mise en forme, par une bibliothèque : Milkdown, son éditeur Crepe (vendor/milkdown-crepe.js,
   window.MikaEditeur) — tableaux, blocs de code, menu à la barre oblique, image téléversée par bouton, glisser ou
   coller. « Enregistrer » garde le Markdown et crée une version. Les décisions techniques ont ici leur sous-onglet.
   PJ2.md est le petit rendu Markdown de la lecture : il échappe tout le HTML, et ne suit que les liens sûrs. */
(function () {
  'use strict';
  const { h, ico, av } = M;
  const PJ = window.PJ2, S = PJ.S, A = PJ.actes, F = PJ.formes, C = PJ.champs;
  Object.assign(S, { dq: '', dplie: new Set(), dv: null });

  /* ── Le rendu Markdown : titres, listes imbriquées, cases, liens, images, code, citations, tableaux ── */
  function enLigne(s, o) {
    const codes = [];
    let x = s.replace(/`([^`]+)`/g, (m, c) => { codes.push(c); return `\u0001${codes.length - 1}\u0001`; }).replace(/\\([\\*_{}[\]()#+\-.!|<>~])/g, '$1');
    x = h(x)
      .replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;(.*?)&quot;)?\)/g, (m, alt, src, legende) => {
        const url = o.image ? o.image(src.replace(/^images\//, '')) : null, dit = legende || (/^[\d.]+$/.test(alt) ? '' : alt);
        return url ? `<img src="${url}" alt="${dit}" title="${dit}">` : `<span class="p2-md-noimg">${ico('image', 'sm')}image introuvable : ${src}</span>`;
      })
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, txt, href) => {
        if (/^https?:\/\//.test(href)) return `<a href="${href}" target="_blank" rel="noopener noreferrer">${txt}</a>`;
        const route = o.lien ? o.lien(href) : null;
        return route ? `<a href="${route}">${txt}</a>` : `<span class="p2-md-nolink" title="Lien sans cible : ${href}">${txt}</span>`;
      })
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>').replace(/(^|[^\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>').replace(/~~([^~]+)~~/g, '<s>$1</s>');
    return x.replace(/\u0001(\d+)\u0001/g, (m, i) => `<code>${h(codes[+i])}</code>`);
  }
  const cellules = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
  const RE_LI = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  /* Une liste et ses sous-listes : un élément plus en retrait que le premier ouvre une liste dans l'élément d'avant. */
  function liste(L, i, o) {
    const base = L[i].match(RE_LI)[1].length, ordonnee = /\d/.test(L[i].match(RE_LI)[2]), items = [];
    while (i < L.length) {
      const m = L[i].match(RE_LI);
      if (!m) {
        if (L[i].trim() && /^\s{2,}\S/.test(L[i]) && items.length) { items[items.length - 1].t += ' ' + L[i].trim(); i += 1; continue; }
        if (!L[i].trim() && L[i + 1] != null && RE_LI.test(L[i + 1]) && L[i + 1].match(RE_LI)[1].length >= base && items.length) { i += 1; continue; }
        break;
      }
      if (m[1].length < base) break;
      if (m[1].length > base + 1 && items.length) { const [sous, j] = liste(L, i, o); items[items.length - 1].sous += sous; i = j; continue; }
      if (/\d/.test(m[2]) !== ordonnee) break;
      items.push({ t: m[3], sous: '' }); i += 1;
    }
    const html = items.map(({ t, sous }) => { const c = t.match(/^\[( |x|X)\]\s+(.*)$/);
      return c ? `<li class="tache${c[1] === ' ' ? '' : ' faite'}"><i>${c[1] === ' ' ? '' : ico('check', 'xs')}</i><span>${enLigne(c[2], o)}${sous}</span></li>` : `<li>${enLigne(t, o)}${sous}</li>`; }).join('');
    return [`<${ordonnee ? 'ol' : 'ul'}>${html}</${ordonnee ? 'ol' : 'ul'}>`, i];
  }
  /* o.image(nom) et o.lien(href) résolvent les adresses ; o.titres, s'il est donné, reçoit les titres (le sommaire). */
  PJ.md = (src, o) => {
    const L = String(src).replace(/\r/g, '').split('\n'), out = [];
    const bloc = (l) => /^(#{1,4}\s|```|>|\||\s*([-*+]|\d+[.)])\s)/.test(l);
    let i = 0, m;
    while (i < L.length) {
      const l = L[i];
      if (/^```/.test(l)) { const buf = [], lang = l.slice(3).trim(); i += 1; while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]); i += 1; out.push(`<pre${lang ? ` data-lang="${h(lang)}"` : ''}><code>${h(buf.join('\n'))}</code></pre>`); continue; }
      if (!l.trim()) { i += 1; continue; }
      if ((m = l.match(/^(#{1,4})\s+(.*)$/))) {
        const id = o.titres ? `p2-t${o.titres.length}` : '';
        if (o.titres) o.titres.push({ niveau: m[1].length, texte: m[2].replace(/[`*_]/g, ''), id });
        out.push(`<h${m[1].length}${id ? ` id="${id}"` : ''}>${enLigne(m[2], o)}</h${m[1].length}>`); i += 1; continue;
      }
      if (/^(-{3,}|\*{3,})\s*$/.test(l)) { out.push('<hr>'); i += 1; continue; }
      if (/^>/.test(l)) { const buf = []; while (i < L.length && /^>/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, '')); out.push(`<blockquote>${PJ.md(buf.join('\n'), o)}</blockquote>`); continue; }
      if (/^\|.*\|\s*$/.test(l) && /^\|?\s*:?-{2,}/.test(L[i + 1] || '')) {
        const tete = cellules(l), rangs = []; i += 2;
        while (i < L.length && /^\|/.test(L[i])) rangs.push(cellules(L[i++]));
        out.push(`<div class="p2-md-table"><table><thead><tr>${tete.map((c) => `<th>${enLigne(c, o)}</th>`).join('')}</tr></thead><tbody>${rangs.map((r) => `<tr>${r.map((c) => `<td>${enLigne(c, o)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
        continue;
      }
      if (RE_LI.test(l)) { const [html, j] = liste(L, i, o); out.push(html); i = j; continue; }
      const buf = [l]; i += 1;
      while (i < L.length && L[i].trim() && !bloc(L[i])) buf.push(L[i++]);
      out.push(`<p>${enLigne(buf.join(' ').replace(/\\$/, ''), o)}</p>`);
    }
    return out.join('');
  };

  /* ── Les aides de l'espace ───────────────────────────────────────── */
  const f = (p, ...x) => PJ.fiche(p, 'documentation', ...x);
  const laPage = (p, chemin) => p.doc.pages.find((x) => x.chemin === chemin);
  const titre = (pg) => ((pg.texte.match(/^#\s+(.*)$/m) || [])[1] || pg.chemin.split('/').pop().replace(/\.md$/, ''));
  const dossiers = (p) => [...new Set(p.doc.pages.flatMap((x) => { const t = x.chemin.split('/').slice(0, -1); return t.map((_, i) => t.slice(0, i + 1).join('/')); }))].sort();
  const adresse = (p) => (nom) => (p.doc.images.find((x) => x.nom === nom) || {}).url;
  const rendre = (p, texte, titres) => PJ.md(texte, { image: adresse(p), lien: (href) => (laPage(p, href) ? f(p, 'pages', href) : null), titres });
  /* Qui a écrit : lui dans le navigateur, Mika, un outil qui a accès au projet. */
  const auteur = (qui, outil) => ({
    toi: { nom: 'Toi', sous: 'dans le navigateur', av: (t) => av('adrien', t) },
    mika: { nom: 'Mika', sous: 'pendant une exécution', av: (t) => av('mika', t) },
    outil: { nom: outil || 'Un outil', sous: 'un outil, par MCP', av: (t) => `<span class="av ${t || ''} p2-av-tool">${ico('plug', 'xs')}</span>` },
  }[qui]);
  const poids = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1).replace('.', ',')} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);
  const usages = (p, img) => p.doc.pages.filter((pg) => pg.texte.includes('images/' + img.nom));

  /* ── L'arborescence des pages ────────────────────────────────────── */
  function arbre(p, choisie) {
    const racine = {};
    p.doc.pages.forEach((pg) => { let n = racine; pg.chemin.split('/').forEach((x, i, t) => { n = n[x] = n[x] || (i === t.length - 1 ? pg : {}); }); });
    const rang = (n, d, pre) => Object.keys(n).sort((a, b) => !!n[a].chemin - !!n[b].chemin || (a === 'accueil.md' ? -1 : b === 'accueil.md' ? 1 : a.localeCompare(b))).map((nom) => {
      const v = n[nom], chemin = pre + nom;
      if (v.chemin) return `<a class="p2-node" style="--d:${d}" href="${f(p, 'pages', v.chemin)}" aria-selected="${v === choisie}" title="${h(titre(v))}">${ico('file', 'sm')}<span>${h(nom)}</span>${p.doc.brouillons[v.chemin] != null ? '<i class="p2-dirty" title="Modifiée, pas encore enregistrée"></i>' : ''}</a>`;
      const plie = S.dplie.has(chemin);
      return `<button class="p2-node dir" style="--d:${d}" type="button" data-p2="docPlier" data-c="${h(chemin)}">${ico(plie ? 'chev-right' : 'chev-down', 'xs')}${ico('folder', 'sm')}<span>${h(nom)}</span></button>${plie ? '' : rang(v, d + 1, chemin + '/')}`;
    }).join('');
    return rang(racine, 0, '');
  }
  function resultats(p, choisie) {
    const q = M.norm(S.dq), l = p.doc.pages.filter((pg) => M.norm(pg.chemin + ' ' + pg.texte).includes(q));
    return l.length ? l.map((pg) => { const i = M.norm(pg.texte).indexOf(q), bout = i >= 0 ? pg.texte.slice(Math.max(0, i - 24), i + 60).replace(/\s+/g, ' ') : pg.chemin;
      return `<a class="li p2-row" href="${f(p, 'pages', pg.chemin)}" aria-selected="${pg === choisie}">${PJ.tuile('file')}<span class="li-main"><span class="li-title">${h(titre(pg))}</span><span class="p2-row-sub"><span class="ellipsis">${i > 24 ? '…' : ''}${h(bout)}…</span></span></span></a>`; }).join('')
      : PJ.vide('search', 'Rien trouvé', `Aucune page ne contient « ${S.dq} ».`);
  }
  PJ.saisies.doc = (v) => { S.dq = v; };
  A.docPlier = (d) => { if (S.dplie.has(d.c)) S.dplie.delete(d.c); else S.dplie.add(d.c); PJ.redessiner(); };

  /* ── Une page : la lire, la modifier, son historique ─────────────── */
  const fil = (pg) => `<code>${pg.chemin.split('/').map((x, i, t) => (i === t.length - 1 ? `<b>${h(x)}</b>` : `${h(x)}<i>/</i>`)).join('')}</code>`;
  const bascule = (p, pg, mode) => `<div class="seg p2-mode"><a href="${f(p, 'pages', pg.chemin)}" aria-pressed="${mode === 'pages'}">${ico('eye', 'sm')}Lire</a><a href="${f(p, 'modifier', pg.chemin)}" aria-pressed="${mode === 'modifier'}">${ico('pen', 'sm')}Modifier</a></div>`;
  const sommaire = (titres, acte) => (titres.length ? `<nav class="p2-toc">${titres.map((t, i) => `<button type="button" class="n${t.niveau}" data-p2="${acte}" data-c="${acte === 'allerA' ? t.id : i}">${h(t.texte)}</button>`).join('')}</nav>` : '<p class="p2-none">Cette page n\'a pas de titre.</p>');
  const signature = (v) => { const a = auteur(v.qui, v.outil); return `<div class="p2-sig">${a.av('sm')}<span><b>${h(a.nom)}</b><small>${a.sous} · ${PJ.moment(v.ago)}</small><em>« ${h(v.mot)} »</em></span></div>`; };
  const versions = (p, pg, choisie) => pg.versions.map((x) => { const q = auteur(x.qui, x.outil);
    return `<a class="p2-version" href="${f(p, 'historique', pg.chemin)}" data-p2="docVersion" data-va="1" data-c="${x.n}" aria-selected="${x === choisie}">${q.av('xs')}<span><b>Version ${x.n}${x === pg.versions[0] ? ' · actuelle' : ''}</b><em>« ${h(x.mot)} »</em><small>${h(q.nom)} · ${PJ.quand(x.ago)}</small></span></a>`; }).join('');
  function lire(p, pg) {
    const v = pg.versions[0], sale = p.doc.brouillons[pg.chemin] != null, titres = [], html = rendre(p, pg.texte, titres), imgs = p.doc.images.filter((x) => pg.texte.includes('images/' + x.nom));
    return { scroll: `doc-${pg.chemin}`, volets: [['', 'Page']], actif: '', lien: () => location.hash,
      tete: `<div class="pane-head p2-path">${fil(pg)}<span class="grow"></span>${PJ.voir(p) ? '' : bascule(p, pg, 'pages')}
        ${PJ.voir(p) ? '' : `<button class="btn icon ghost sm" type="button" data-p2="docMenu" data-p="${p.id}" data-c="${h(pg.chemin)}" title="Renommer, déplacer, supprimer">${ico('more', 'sm')}</button>`}</div>`,
      corps: `${sale ? `<p class="p2-banner you">${ico('pen', 'sm')}<span>Cette page a des modifications que tu n'as pas enregistrées.</span><a class="btn sm" href="${f(p, 'modifier', pg.chemin)}">Les reprendre</a><button class="btn sm ghost" type="button" data-p2="docAbandonner" data-p="${p.id}" data-c="${h(pg.chemin)}">Les abandonner</button></p>` : ''}
        <div class="p2-md">${html}</div>`,
      cote: PJ.sc('Sur cette page', sommaire(titres.filter((t) => t.niveau > 1), 'allerA'))
        + PJ.sc('Dernière modification', v ? signature(v) : '')
        + PJ.sc('Versions', `<div class="p2-versions">${versions(p, pg, null)}</div>`, `<span class="cnt">${pg.versions.length}</span>`)
        + PJ.sc('Ses images', imgs.map((x) => `<a class="p2-lie" href="${f(p, 'images', x.nom)}"><span class="p2-mini-img"><img src="${x.url}" alt=""></span><span><b>${h(x.nom)}</b><small>${h(x.poids)}</small></span></a>`).join('')) };
  }
  function historique(p, pg) {
    const v = pg.versions.find((x) => x.n === S.dv) || pg.versions[0], a = auteur(v.qui, v.outil), actuelle = v === pg.versions[0];
    return { scroll: `version-${pg.chemin}-${v.n}`, volets: [['', `Version ${v.n}`]], actif: '', lien: () => location.hash,
      tete: `<div class="pane-head p2-path">${fil(pg)}<span class="p2-kind">historique</span><span class="grow"></span><a class="btn sm" href="${f(p, 'pages', pg.chemin)}">${ico('chev-left', 'sm')}Revenir à la page</a></div>`,
      corps: `<p class="p2-banner${actuelle ? ' done' : ''}">${a.av('sm')}<span><b>Version ${v.n}</b> · ${h(a.nom)}, ${a.sous} · ${PJ.moment(v.ago)} — « ${h(v.mot)} »</span>
          ${actuelle || PJ.voir(p) ? '<span class="p2-kind">la version actuelle</span>' : `<button class="btn sm primary" type="button" data-p2="docRevenir" data-p="${p.id}" data-c="${h(pg.chemin)}" data-v="${v.n}">${ico('history', 'sm')}Revenir à cette version</button>`}</p>
        <div class="p2-md">${rendre(p, v.texte)}</div>`,
      cote: PJ.sc('Versions', `<div class="p2-versions">${versions(p, pg, v)}</div>`, `<span class="cnt">${pg.versions.length}</span>`) };
  }
  function modifier(p, pg) {
    const brouillon = p.doc.brouillons[pg.chemin], texte = brouillon != null ? brouillon : pg.texte, sale = brouillon != null;
    return { scroll: `ed-${pg.chemin}`, plein: true, volets: [['', 'Écrire']], actif: '', lien: () => location.hash,
      tete: `<div class="pane-head p2-path">${fil(pg)}<span class="p2-st you p2-unsaved"${sale ? '' : ' hidden'}>pas encore enregistrée</span><span class="grow"></span>${bascule(p, pg, 'modifier')}
        <button class="btn sm ghost p2-undo" type="button" data-p2="docAbandonner" data-p="${p.id}" data-c="${h(pg.chemin)}"${sale ? '' : ' hidden'}>Annuler</button>
        <button class="btn sm primary" type="button" data-p2="docEnregistrer" data-p="${p.id}" data-c="${h(pg.chemin)}"${sale ? '' : ' disabled'}>${ico('check', 'sm')}Enregistrer</button></div>`,
      corps: `<div class="p2-crepe" data-p2-crepe data-p="${p.id}" data-c="${h(pg.chemin)}"></div>`,
      cote: PJ.sc('Écrire', `<ul class="p2-tips"><li>${ico('pen', 'xs')}<span>Écris dans la page : elle garde du vrai Markdown.</span></li><li>${ico('plus', 'xs')}<span>Tape <kbd>/</kbd> pour un titre, une liste, un tableau, un bloc de code, une image.</span></li>
          <li>${ico('image', 'xs')}<span>Glisse une image dans la page, ou colle-la : elle rejoint les images de la documentation.</span></li></ul>
          <label class="btn p2-upload">${ico('upload', 'sm')}Téléverser une image<input type="file" accept="image/*" data-p2-fichier hidden></label>`)
        + PJ.sc('Sur cette page', `<div data-p2-toc>${sommaire(titresDe(texte), 'docVers')}</div>`)
        + PJ.sc('Images de la documentation', `<div class="p2-pick" data-p2-pick>${choixImages(p)}</div>`)
        + PJ.sc('Le Markdown', `<details class="p2-src-md"><summary>${ico('chev-right', 'xs')}Voir ce qui sera enregistré</summary><pre data-p2-source>${h(texte)}</pre></details>`) };
  }
  const choixImages = (p) => p.doc.images.map((x) => `<button type="button" data-p2="docInsererImage" data-c="${h(x.nom)}" title="L'insérer dans la page">
    <img src="${x.url}" alt=""><span>${h(x.nom)}</span></button>`).join('') || '<p class="p2-none">Aucune image pour l\'instant.</p>';
  const titresDe = (md) => { let code = false; return md.split('\n').reduce((l, x) => { if (/^```/.test(x)) code = !code; const m = !code && x.match(/^(#{1,4})\s+(.*)$/); if (m) l.push({ niveau: m[1].length, texte: m[2].replace(/[`*_\\]/g, '') }); return l; }, []).filter((t) => t.niveau > 1); };
  function vuePages(p, mode, chemin) {
    const pg = laPage(p, chemin) || (chemin || M.mobile() ? null : laPage(p, 'accueil.md') || p.doc.pages[0]);
    const liste = `<div class="p2-tools"><label class="search grow">${ico('search', 'sm')}<input type="search" placeholder="Chercher…" data-p2-saisie="doc" value="${h(S.dq)}"></label>
        ${PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="docNouvelle" data-p="${p.id}" title="Nouvelle page">${ico('plus', 'sm')}<span>Nouvelle page</span></button>`}</div>
      <div class="pane-scroll ${S.dq ? '' : 'p2-tree'}" data-scroll="doc-arbre">${S.dq ? resultats(p, pg) : arbre(p, pg)}</div>`;
    return PJ.trio(Object.assign({ cls: 'etroit p2-docs' + (pg && mode === 'modifier' ? ' edition' : ''), liste, ouvert: !!laPage(p, chemin), retour: [f(p), 'Pages'] },
      !pg ? { vide: PJ.vide('book', 'Choisis une page', 'Elle s\'ouvre ici, à côté de l\'arborescence.') } : mode === 'modifier' && !PJ.voir(p) ? modifier(p, pg) : mode === 'historique' ? historique(p, pg) : lire(p, pg)));
  }

  /* ── L'éditeur : Milkdown Crepe dans la page ; chaque frappe garde un brouillon ── */
  let ED = null;
  /* Ce que Crepe rend redevient le Markdown de la maison : des tirets pour les puces, un texte pour chaque image. */
  const propre = (md) => { let code = false;
    return md.split('\n').map((l) => { if (/^```/.test(l)) code = !code; return code ? l : l.replace(/^(\s*)\* /, '$1- ').replace(/!\[[\d.]*\]\(([^)\s]+)((?:\s+"[^"]*")?)\)/g, (m, src, leg) => `![${leg ? leg.trim().slice(1, -1) : src.split('/').pop().replace(/\.\w+$/, '').replace(/-/g, ' ')}](${src})`); }).join('\n').replace(/\n+$/, '') + '\n'; };
  function suivre(md) {
    if (!ED) return;
    const { p, chemin } = ED, texte = propre(md), tete = document.querySelector('.p2-docs .p2-path');
    p.doc.brouillons[chemin] = texte;
    if (tete) { tete.querySelector('.p2-unsaved').hidden = false; tete.querySelector('.p2-undo').hidden = false; tete.querySelector('[data-p2="docEnregistrer"]').disabled = false; }
    const toc = document.querySelector('[data-p2-toc]'), source = document.querySelector('[data-p2-source]');
    if (toc) toc.innerHTML = sommaire(titresDe(texte), 'docVers');
    if (source) source.textContent = texte;
    const onglet = document.querySelector('.p2-tabs a[aria-current="page"]');
    if (onglet && !onglet.querySelector('.p2-dirty')) onglet.insertAdjacentHTML('beforeend', '<i class="p2-dirty"></i>');
    const noeud = document.querySelector('.p2-docs .p2-node[aria-selected="true"]');
    if (noeud && !noeud.querySelector('.p2-dirty')) noeud.insertAdjacentHTML('beforeend', '<i class="p2-dirty"></i>');
  }
  /* Une image choisie, déposée ou collée : lue en mémoire, ajoutée aux images de l'espace ; la page la cite par son nom. */
  function televerser(p, fichier) {
    return new Promise((ok, non) => {
      if (!fichier || !/^image\//.test(fichier.type)) { M.toast('Ce n\'est pas une image.', { ico: 'alert' }); non(new Error('pas une image')); return; }
      const lecteur = new FileReader();
      lecteur.onload = () => {
        const base = M.norm((fichier.name || 'collage.png').replace(/\.[A-Za-z0-9]+$/, '')).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'image';
        const ext = (fichier.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace('svg+xml', 'svg');
        let nom = `${base}.${ext}`, n = 2;
        while (p.doc.images.some((x) => x.nom === nom)) nom = `${base}-${n++}.${ext}`;
        p.doc.images.unshift({ nom, poids: poids(fichier.size), url: lecteur.result, par: 'toi', ago: 0 });
        const choix = document.querySelector('[data-p2-pick]'); if (choix) choix.innerHTML = choixImages(p);
        M.toast(`Image ajoutée : images/${nom}`, { ico: 'image' });
        ok(nom);
      };
      lecteur.readAsDataURL(fichier);
    });
  }
  PJ.apres = (body) => {
    const z = body.querySelector('[data-p2-crepe]');
    if (!z) return;
    const p = PJ.proj(z.dataset.p), chemin = z.dataset.c, pg = laPage(p, chemin), depart = p.doc.brouillons[chemin] != null ? p.doc.brouillons[chemin] : pg.texte;
    if (!window.MikaEditeur) {   // le paquet de l'éditeur n'a pas chargé : une zone de texte, pour ne rien perdre
      z.innerHTML = `<textarea class="p2-secours" spellcheck="false" aria-label="Le Markdown de la page">${h(depart)}</textarea>`;
      ED = { p, chemin, api: null }; z.firstChild.addEventListener('input', (e) => suivre(e.target.value));
      return;
    }
    ED = { p, chemin, api: window.MikaEditeur.creer(z, { markdown: depart, sombre: document.documentElement.dataset.theme === 'dark', change: suivre,
      televerser: (fichier) => televerser(p, fichier).then((nom) => 'images/' + nom), adresse: (u) => adresse(p)(String(u).replace(/^images\//, '')) || u }) };
  };
  A.docInsererImage = (d) => { if (ED && ED.api) { ED.api.inserer(`![${d.c.replace(/\.\w+$/, '').replace(/-/g, ' ')}](images/${d.c})`); M.toast(`Image insérée : images/${d.c}`, { ico: 'image' }); } };
  A.docVers = (d) => { if (S.infos) { S.infos = false; document.querySelector('.p2-dz').classList.remove('infos'); } const t = [...document.querySelectorAll('.p2-crepe .ProseMirror :is(h2, h3, h4)')][Number(d.c)]; if (t) t.scrollIntoView({ block: 'start', behavior: 'smooth' }); };
  document.addEventListener('change', (e) => {
    if (!e.target.matches('[data-p2-fichier]')) return;
    const fichier = e.target.files[0], hors = e.target.dataset.p2Fichier;
    if (hors) televerser(PJ.proj(hors), fichier).then((nom) => M.go(f(PJ.proj(hors), 'images', nom)), () => {});
    else if (ED && ED.api) televerser(ED.p, fichier).then((nom) => ED.api.inserer(`![${nom.replace(/\.\w+$/, '').replace(/-/g, ' ')}](images/${nom})`), () => {});
    e.target.value = '';
  });
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((nom) => document.addEventListener(nom, (e) => {
    const zone = e.target.closest ? e.target.closest('[data-p2-depot]') : null;
    if (!zone) return;
    e.preventDefault();
    zone.classList.toggle('depose', nom === 'dragenter' || nom === 'dragover');
    if (nom === 'drop') televerser(PJ.proj(zone.dataset.p2Depot), e.dataTransfer && e.dataTransfer.files[0]).then((n) => M.go(f(PJ.proj(zone.dataset.p2Depot), 'images', n)), () => {});
  }));
  addEventListener('beforeunload', (e) => { if (PJ.P.projets.some((p) => p.doc && Object.keys(p.doc.brouillons).length)) { e.preventDefault(); e.returnValue = ''; } });
  /* Avant chaque rendu : l'éditeur de la page d'avant se défait ; une page quittée sans enregistrer garde son brouillon, et l'écran le dit. */
  PJ.quitter = (loc) => {
    if (ED && ED.api) ED.api.detruire();
    ED = null;
    const avant = PJ._edition; PJ._edition = null;
    if (loc.rubrique === 'fiche' && loc.tab === 'documentation' && loc.rest[0] === 'modifier') PJ._edition = { p: loc.p, chemin: loc.rest.slice(1).join('/') };
    if (!avant || !avant.p.doc || avant.p.doc.brouillons[avant.chemin] == null) return;
    const memePage = loc.rubrique === 'fiche' && loc.p === avant.p && loc.tab === 'documentation' && loc.rest.slice(1).join('/') === avant.chemin;
    if (!memePage) M.toast(`« ${avant.chemin} » n'est pas enregistrée : ton brouillon est gardé.`, { ico: 'alert', duree: 4200 });
  };

  /* ── Les gestes sur une page ─────────────────────────────────────── */
  A.docEnregistrer = (d) => PJ.demander({ titre: 'Enregistrer la page', label: 'Un mot sur ce qui a changé', court: true, exemple: 'Par exemple : ajout de la section Dépannage', bouton: 'Enregistrer',
    apres: '<p class="small muted">Une version de la page est créée dans l\'espace de documentation, à ton nom. Le dépôt du code n\'est pas touché.</p>', alors: (mot) => {
      const p = PJ.proj(d.p), pg = laPage(p, d.c), n = Math.max(0, ...pg.versions.map((x) => x.n)) + 1;
      pg.texte = p.doc.brouillons[d.c]; delete p.doc.brouillons[d.c];
      pg.versions.unshift({ n, qui: 'toi', ago: 0, mot, texte: pg.texte, outil: '' }); PJ.geste(p, `Tu as modifié la page « ${d.c} » de la documentation`, 'book', ['documentation', 'pages', d.c]);
      M.toast(`Version ${n} enregistrée dans l'espace « ${p.doc.espace} ».`); M.go(f(p, 'pages', d.c));
    } });
  A.docAbandonner = (d) => { const p = PJ.proj(d.p); delete p.doc.brouillons[d.c]; PJ.redessiner(); M.toast('Modifications abandonnées.', { ico: 'refresh' }); };
  A.docVersion = (d, b) => { S.dv = Number(d.c); S.infos = false; if (b.getAttribute('href') === location.hash) PJ.redessiner(); };
  A.docRevenir = (d) => {
    const p = PJ.proj(d.p), pg = laPage(p, d.c), v = pg.versions.find((x) => String(x.n) === d.v);
    PJ.confirmer({ titre: `Revenir à la version ${v.n} ?`, bouton: 'Revenir à cette version', ico: 'history', corps: `<p>La page reprend le texte de la version ${v.n} (« ${h(v.mot)} »). Rien n'est perdu : c'est une nouvelle version, et les autres restent dans l'historique.</p>`,
      alors: () => { const n = pg.versions[0].n + 1; pg.texte = v.texte; delete p.doc.brouillons[d.c]; pg.versions.unshift({ n, qui: 'toi', ago: 0, mot: `Retour à la version ${v.n}`, texte: v.texte, outil: '' }); S.dv = n;
        PJ.redessiner(); M.toast(`Version ${n} : retour à la version ${v.n}.`, { ico: 'history' }); } });
  };
  const choixDossier = (p, actuel) => C.choix('dossier', 'Dossier', actuel, [['', 'la racine de l\'espace'], ...dossiers(p).map((x) => [x, x])]);
  const nomPropre = (s) => M.norm(s).replace(/\.md$/, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  A.docNouvelle = (d) => { const p = PJ.proj(d.p), ici = (PJ.lieu().rest || []).slice(1, -1).join('/');
    PJ.tiroir({ titre: 'Nouvelle page', sous: `Dans l'espace « ${p.doc.espace} »`, forme: 'docPage', data: { p: p.id }, bouton: 'Créer la page',
      corps: `${C.texte('titre', 'Son titre', '', { requis: true, ex: 'Par exemple : Dépannage' })}${choixDossier(p, ici)}${C.texte('neuf', 'Ou un nouveau dossier', '', { ex: 'par exemple : guide/avance' })}` }); };
  F.docPage = (v, d) => {
    const p = PJ.proj(d.p), nom = nomPropre(v.titre);
    if (!nom) return false;
    const dossier = v.neuf.split('/').map(nomPropre).filter(Boolean).join('/') || v.dossier, chemin = `${dossier ? dossier + '/' : ''}${nom}.md`;
    if (laPage(p, chemin)) { M.toast('Une page porte déjà ce nom dans ce dossier.', { ico: 'alert' }); return false; }
    const texte = `# ${v.titre.trim()}\n\n`;
    p.doc.pages.push({ chemin, texte, versions: [{ n: 1, qui: 'toi', ago: 0, mot: 'Création de la page', texte, outil: '' }] });
    S.dq = ''; M.toast(`Page créée : ${chemin}`); M.go(f(p, 'modifier', chemin));
    return true;
  };
  const deplacer = (p, pg, chemin) => {
    if (chemin === pg.chemin) return true;
    if (laPage(p, chemin)) { M.toast('Une page porte déjà ce nom dans ce dossier.', { ico: 'alert' }); return false; }
    if (p.doc.brouillons[pg.chemin] != null) { p.doc.brouillons[chemin] = p.doc.brouillons[pg.chemin]; delete p.doc.brouillons[pg.chemin]; }
    pg.chemin = chemin;
    M.toast(`La page est maintenant ${chemin}`); M.go(f(p, 'pages', chemin));
    return true;
  };
  F.docDeplacer = (v, d) => { const p = PJ.proj(d.p), pg = laPage(p, d.c), dossier = pg.chemin.split('/').slice(0, -1).join('/'), nom = pg.chemin.split('/').pop();
    if (v.nom != null) { const n = nomPropre(v.nom); return n ? deplacer(p, pg, `${dossier ? dossier + '/' : ''}${n}.md`) : false; }
    const vers = v.neuf.split('/').map(nomPropre).filter(Boolean).join('/') || v.dossier; return deplacer(p, pg, `${vers ? vers + '/' : ''}${nom}`); };
  A.docMenu = (d, b) => {
    const p = PJ.proj(d.p), pg = laPage(p, d.c), dossier = pg.chemin.split('/').slice(0, -1).join('/'), nom = pg.chemin.split('/').pop(), data = { p: p.id, c: pg.chemin };
    M.menu(b, [
      { label: 'Renommer', ico: 'pen', action: () => PJ.tiroir({ titre: 'Renommer la page', sous: pg.chemin, forme: 'docDeplacer', data, bouton: 'Renommer', corps: C.texte('nom', 'Nom du fichier', nom, { requis: true, aide: 'Les liens des autres pages vers celle-ci ne sont pas réécrits.' }) }) },
      { label: 'Déplacer', ico: 'folder', action: () => PJ.tiroir({ titre: 'Déplacer la page', sous: pg.chemin, forme: 'docDeplacer', data, bouton: 'Déplacer', corps: `${choixDossier(p, dossier)}${C.texte('neuf', 'Ou un nouveau dossier', '', { ex: 'par exemple : archives' })}` }) },
      { label: 'Son historique', ico: 'history', action: () => { S.dv = null; M.go(f(p, 'historique', pg.chemin)); } },
      { label: 'Copier son lien', ico: 'copy', action: () => A.copier({ c: `[${titre(pg)}](${pg.chemin})` }) }, 'sep',
      { label: 'Supprimer', ico: 'trash', danger: true, action: () => PJ.confirmer({ titre: 'Supprimer la page ?', bouton: 'Supprimer', danger: true, ico: 'trash',
        corps: `<p><b>${h(pg.chemin)}</b> et ses ${pg.versions.length} versions seront supprimées de l'espace de documentation. Les pages qui y renvoient garderont un lien sans cible.</p>`,
        alors: () => { p.doc.pages = p.doc.pages.filter((x) => x !== pg); delete p.doc.brouillons[pg.chemin]; M.toast(`Page supprimée : ${pg.chemin}`, { ico: 'trash' }); M.go(f(p)); } }) },
    ]);
  };

  /* ── Les images de l'espace : la grille, et à droite l'image choisie ── */
  function panneauImage(p, img) {
    const u = usages(p, img), a = auteur(img.par), lien = `![${img.nom.replace(/\.[a-z]+$/, '').replace(/-/g, ' ')}](images/${img.nom})`;
    return PJ.sc(null, `<div class="p2-img-grand"><img src="${img.url}" alt="${h(img.nom)}"></div><p class="p2-img-nom"><code>${h(img.nom)}</code></p>`)
      + PJ.sc('L\'image', PJ.props([['Poids', h(img.poids)], ['Ajoutée par', `<span class="p2-by">${a.av('xs')}${h(a.nom)}</span>`], ['Quand', PJ.moment(img.ago)]]))
      + PJ.sc('Citée dans', u.map((pg) => PJ.lie(f(p, 'pages', pg.chemin), 'file', '', titre(pg), h(pg.chemin))).join('') || '<p class="p2-none">Aucune page ne la cite.</p>', `<span class="cnt">${u.length}</span>`)
      + PJ.sc('Gérer', `<div class="p2-decide"><button class="btn" type="button" data-p2="copier" data-c="${h(lien)}">${ico('copy', 'sm')}Copier son lien Markdown</button>
        ${PJ.voir(p) ? '' : `<button class="btn danger" type="button" data-p2="docRetirerImage" data-p="${p.id}" data-c="${h(img.nom)}">${ico('trash', 'sm')}Retirer l'image</button>`}</div>`);
  }
  function vueImages(p, nom) {
    const img = p.doc.images.find((x) => x.nom === nom) || (M.mobile() ? null : p.doc.images[0]);
    const grille = `<div class="p2-imgzone" data-p2-depot="${p.id}"><header class="p2-sec-h"><div><h2>Les images de la documentation</h2><p>Une image téléversée se cite dans une page : <code>![texte](images/nom.png)</code>.</p></div>
        ${PJ.voir(p) ? '' : `<label class="btn primary">${ico('upload', 'sm')}Téléverser une image<input type="file" accept="image/*" data-p2-fichier="${p.id}" hidden></label>`}</header>
      <div class="p2-imgs">${p.doc.images.map((x) => { const u = usages(p, x).length;
        return `<a class="p2-img" href="${f(p, 'images', x.nom)}" aria-selected="${x === img}"><span class="p2-thumb"><img src="${x.url}" alt="${h(x.nom)}"></span><span class="p2-img-cap"><code>${h(x.nom)}</code><small>${h(x.poids)} · ${u ? PJ.pluriel(u, 'page', 'pages') : 'aucune page'}</small></span></a>`; }).join('')}
        <div class="p2-img p2-imgdrop">${ico('upload', 'lg')}<b>Dépose une image ici</b><span>ou colle-la dans une page que tu modifies</span></div></div></div>`;
    if (M.mobile()) return PJ.trio({ liste: `<div class="pane-scroll" data-scroll="doc-images">${grille}</div>`, ouvert: !!img, retour: [f(p, 'images'), 'Images'], volets: [['', 'Image']], actif: '', lien: () => location.hash, scroll: 'image', corps: img ? `<div class="p2-flat">${panneauImage(p, img)}</div>` : '' });
    return PJ.trio({ volets: [['', 'Images']], actif: '', lien: () => location.hash, plein: true, scroll: 'doc-images', corps: grille, cote: img ? panneauImage(p, img) : '' });
  }
  A.docRetirerImage = (d) => {
    const p = PJ.proj(d.p), u = p.doc.pages.filter((pg) => pg.texte.includes('images/' + d.c)).length;
    PJ.confirmer({ titre: 'Retirer l\'image ?', bouton: 'Retirer', danger: true, ico: 'trash', corps: `<p><b>${h(d.c)}</b> sera retirée de l'espace de documentation.${u ? ` ${PJ.pluriel(u, 'page la cite', 'pages la citent')} : elle y apparaîtra comme introuvable.` : ''}</p>`,
      alors: () => { p.doc.images = p.doc.images.filter((x) => x.nom !== d.c); M.toast(`Image retirée : ${d.c}`, { ico: 'trash' }); M.go(f(p, 'images')); } });
  };

  /* ── Les décisions techniques : la liste, le détail de l'une, ce qu'elle remplace ── */
  const etatDecision = (d) => (d.etat === 'remplacee' ? ['wait', 'remplacée'] : ['done', 'en vigueur']);
  const champsDecision = (p, d) => `${C.texte('titre', 'La décision, en une phrase', d.titre, { requis: true, ex: 'Par exemple : Le journal des refus est un fichier JSON Lines' })}${C.long('texte', 'Le choix', d.texte, { rangs: 3, requis: true })}
    ${C.long('contexte', 'Le contexte', d.contexte, { rangs: 3, ex: 'Ce qui a rendu cette décision nécessaire.' })}${C.long('raison', 'La raison', d.raison, { rangs: 3, ex: 'Pourquoi ce choix plutôt qu\'un autre.' })}
    ${C.long('options', 'Les options écartées', (d.options || []).map((o) => `${o.titre} : ${o.pourquoi}`).join('\n'), { rangs: 4, aide: 'Une par ligne — « l\'option : pourquoi elle est écartée ».' })}
    ${C.choix('remplace', 'Elle remplace', d.remplace || '', [['', 'aucune décision'], ...p.decisions.filter((x) => x !== d && (x.etat !== 'remplacee' || x.n === d.remplace)).map((x) => [x.n, `n° ${x.n} · ${x.titre}`])])}`;
  function detailDecision(p, d, volet) {
    const q = PJ.qui(d.par), fd = (...x) => f(p, 'decisions', d.n, ...x), v = ['options', 'modifier'].includes(volet) && !(volet === 'modifier' && PJ.voir(p)) ? volet : '';
    const avant = p.decisions.find((x) => x.n === d.remplace), apres = p.decisions.find((x) => x.n === d.remplaceePar), o = p.objectifs.find((x) => x.id === d.objectif), t = p.tickets.find((x) => x.n === d.ticket);
    const c = d.commit && p.depot && p.depot.commits.find((x) => x.sha === d.commit), ligne = (x) => PJ.lie(f(p, 'decisions', x.n), 'shield-check', etatDecision(x)[0], x.titre, `décision n° ${x.n} · ${PJ.quand(x.ago)}`, PJ.st(...etatDecision(x)));
    const corps = v === 'modifier' ? PJ.forme({ forme: 'decision', data: { p: p.id, c: d.n }, titre: `Modifier la décision n° ${d.n}`, sous: 'Elle la relit avant chaque passage : ce que tu écris ici s\'impose à elle.', annuler: fd(), corps: champsDecision(p, d) })
      : v === 'options' ? ((d.options || []).length ? `<ol class="p2-options">${d.options.map((x) => `<li>${ico('x', 'sm')}<div><b>${h(x.titre)}</b><p>${PJ.code(x.pourquoi)}</p></div></li>`).join('')}</ol>` : '<p class="p2-none">Aucune autre option n\'a été notée.</p>')
      : `${apres ? `<p class="p2-banner">${ico('history', 'sm')}<span>Cette décision n'est plus en vigueur : la décision n° ${apres.n} la remplace.</span><a class="btn sm" href="${f(p, 'decisions', apres.n)}">La lire</a></p>` : ''}
        <p class="p2-choix">${PJ.code(d.texte)}</p>${d.contexte ? `<h3 class="p2-h3">Le contexte</h3><p class="p2-lede">${PJ.code(d.contexte)}</p>` : ''}${d.raison ? `<h3 class="p2-h3">La raison</h3><p class="p2-lede">${PJ.code(d.raison)}</p>` : ''}`;
    return { scroll: `dec-${d.n}-${v}`, lien: (k) => fd(k), actif: v, volets: v === 'modifier' ? [['modifier', 'Modifier']] : [['', 'La décision'], ['options', 'Options écartées', (d.options || []).length]],
      tete: PJ.parts.entete({ tuile: PJ.tuile('shield-check', etatDecision(d)[0]), sur: `Décision n° ${d.n}`, titre: d.titre,
        meta: `${PJ.st(...etatDecision(d))}<span class="p2-by">${q.av('xs')}${d.par === 'adrien' ? 'décidée par toi' : 'proposée par ' + h(q.nom)}</span><span>${PJ.quand(d.ago)}</span>`,
        droite: PJ.voir(p) ? '' : `<a class="btn${v === 'modifier' ? ' on' : ''}" href="${fd(v === 'modifier' ? '' : 'modifier')}">${ico('pen', 'sm')}Modifier</a>` }),
      corps,
      cote: PJ.sc('En bref', PJ.props([['État', PJ.st(...etatDecision(d))], ['Par', `<span class="p2-by">${q.av('xs')}${d.par === 'adrien' ? 'toi' : h(q.nom)}</span>`], ['Quand', PJ.moment(d.ago)]]))
        + PJ.sc('Elle remplace', avant ? ligne(avant) : '') + PJ.sc('Remplacée par', apres ? ligne(apres) : '')
        + PJ.sc('Ce qui est lié', (o ? PJ.lie(PJ.fiche(p, 'objectifs', 'o' + o.id), 'p2-target', PJ.etatObjectif(o)[0], o.titre, `objectif n° ${o.id}`, PJ.st(...PJ.etatObjectif(o))) : '')
          + (t ? PJ.lie(PJ.fiche(p, 'tickets', t.n), 'p2-ticket', PJ.etatTicket(t)[0], t.titre, '#' + t.n, PJ.st(...PJ.etatTicket(t))) : '')
          + (c ? PJ.lie(PJ.fiche(p, 'code', 'commits', c.sha.slice(0, 7)), 'p2-commit', '', c.msg, `<code>${c.sha.slice(0, 7)}</code> · ${PJ.quand(c.ago)}`) : ''))
        + (PJ.voir(p) ? '' : PJ.sc('Gérer', `<div class="p2-decide">${d.etat === 'remplacee' ? '' : `<button class="btn" type="button" data-p2="decisionNouvelle" data-p="${p.id}" data-c="${d.n}">${ico('history', 'sm')}La remplacer par une autre</button>`}
          <button class="btn danger" type="button" data-p2="decisionRetirer" data-p="${p.id}" data-c="${d.n}">${ico('trash', 'sm')}Retirer la décision</button></div>`)) };
  }
  function vueDecisions(p, rest) {
    const l = [...p.decisions.filter((x) => x.etat !== 'remplacee'), ...p.decisions.filter((x) => x.etat === 'remplacee')], d = PJ.choisi(l, (x) => x.n, rest[0]);
    const ligne = (x) => `<a class="li p2-row" href="${f(p, 'decisions', x.n)}" aria-selected="${x === d}">${PJ.tuile('shield-check', etatDecision(x)[0])}<span class="li-main"><span class="li-title">${h(x.titre)}</span>
      <span class="p2-row-sub">${PJ.st(...etatDecision(x))}<span>n° ${x.n}</span><time>${PJ.quand(x.ago)}</time></span></span></a>`;
    const liste = `<div class="p2-tools"><h2 class="grow">Décisions techniques</h2>${PJ.voir(p) ? '' : `<button class="btn primary" type="button" data-p2="decisionNouvelle" data-p="${p.id}">${ico('plus', 'sm')}<span>Nouvelle décision</span></button>`}</div>
      <div class="pane-scroll" data-scroll="decisions">${l.length ? l.map(ligne).join('') : PJ.vide('shield-check', 'Aucune décision', 'Un choix technique durable, qu\'elle ne remet pas en cause à chaque passage.')}</div>`;
    return PJ.trio(Object.assign({ liste, ouvert: !!rest[0] && !!d, retour: [f(p, 'decisions'), 'Décisions'] }, d ? detailDecision(p, d, rest[1]) : { vide: PJ.vide('shield-check', 'Aucune décision', 'Note ici un choix technique durable : elle le relira avant chaque passage.') }));
  }
  const optionsDe = (s) => String(s || '').split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf(':'); return i > 0 ? { titre: l.slice(0, i).trim(), pourquoi: l.slice(i + 1).trim() } : { titre: l, pourquoi: '' }; });
  A.decisionNouvelle = (d) => { const p = PJ.proj(d.p);
    PJ.tiroir({ titre: 'Nouvelle décision', sous: 'Un choix technique durable : elle le relit avant chaque passage.', forme: 'decision', data: { p: p.id }, bouton: 'Noter la décision', corps: champsDecision(p, { remplace: d.c ? Number(d.c) : '' }) }); };
  F.decision = (v, d) => {
    const p = PJ.proj(d.p), remplace = v.remplace ? Number(v.remplace) : null, champs = { titre: v.titre, texte: v.texte, contexte: v.contexte, raison: v.raison, options: optionsDe(v.options), remplace };
    let x = d.c && p.decisions.find((y) => String(y.n) === d.c);
    if (x) { p.decisions.forEach((y) => { if (y.remplaceePar === x.n && y.n !== remplace) { y.etat = 'vigueur'; y.remplaceePar = null; } }); Object.assign(x, champs); }
    else { x = Object.assign({ n: Math.max(0, ...p.decisions.map((y) => y.n)) + 1, ago: 0, par: 'adrien', etat: 'vigueur' }, champs); p.decisions.unshift(x); PJ.geste(p, `Tu as pris la décision n° ${x.n} : ${x.titre}`, 'shield-check', ['documentation', 'decisions', x.n]); }
    const avant = p.decisions.find((y) => y.n === remplace); if (avant) { avant.etat = 'remplacee'; avant.remplaceePar = x.n; }
    M.toast(d.c ? `Décision n° ${x.n} modifiée.` : `Décision n° ${x.n} notée : elle la lira avant son prochain passage.`, { mika: !d.c }); M.go(f(p, 'decisions', x.n));
    return true;
  };
  A.decisionRetirer = (d) => { const p = PJ.proj(d.p), x = p.decisions.find((y) => String(y.n) === d.c);
    PJ.confirmer({ titre: 'Retirer la décision ?', bouton: 'Retirer', danger: true, ico: 'trash', corps: `<p><b>${h(x.titre)}</b> ne s'imposera plus à elle.${x.remplace ? ` La décision n° ${x.remplace}, qu'elle remplaçait, redevient en vigueur.` : ''}</p>`,
      alors: () => { p.decisions = p.decisions.filter((y) => y !== x); p.decisions.forEach((y) => { if (y.remplaceePar === x.n) { y.etat = 'vigueur'; y.remplaceePar = null; } if (y.remplace === x.n) y.remplace = null; }); M.toast('Décision retirée.', { ico: 'trash' }); M.go(f(p, 'decisions')); } }); };

  A.docCreer = (d) => {
    const p = PJ.proj(d.p), texte = `# ${p.titre}\n\n${p.resume}\n`;
    p.doc = { espace: nomPropre(p.titre), pages: [{ chemin: 'accueil.md', texte, versions: [{ n: 1, qui: 'toi', ago: 0, mot: 'Création de l\'espace', texte, outil: '' }] }], images: [], brouillons: {} };
    PJ.redessiner(); M.toast(`Espace de documentation créé : ${p.doc.espace}`);
  };
  PJ.onglets.documentation = (p, rest) => {
    const decisions = rest[0] === 'decisions';
    if (!p.doc && !decisions && !p.decisions.length) return `<div class="empty">${ico('book')}<b>Pas encore d'espace de documentation</b><p>Un espace à part du dépôt : des pages que tu écris ici, et qu'elle lit et écrit pendant ses exécutions.</p>
      ${PJ.voir(p) ? '' : `<div class="row"><button class="btn primary" type="button" data-p2="docCreer" data-p="${p.id}">${ico('plus', 'sm')}Créer l'espace</button><a class="btn" href="${f(p, 'decisions')}">${ico('shield-check', 'sm')}Noter une décision</a></div>`}</div>`;
    const v = decisions || !p.doc ? 'decisions' : rest[0] === 'images' ? 'images' : 'pages', mode = ['modifier', 'historique'].includes(rest[0]) ? rest[0] : 'pages';
    return PJ.sous(p, 'documentation', [...(p.doc ? [['pages', 'Pages', p.doc.pages.length], ['images', 'Images', p.doc.images.length]] : []), ['decisions', 'Décisions', p.decisions.filter((x) => x.etat !== 'remplacee').length]], v,
      p.doc ? `<span class="p2-remote plain" title="Un espace à part du dépôt du code">${ico('book', 'sm')}<span>espace « ${h(p.doc.espace)} »</span></span><span class="p2-sync">${ico('info', 'xs')}à part du dépôt du code</span>` : '')
      + `<div class="p2-under">${v === 'decisions' ? vueDecisions(p, rest.slice(1)) : v === 'images' ? vueImages(p, rest.slice(1).join('/')) : vuePages(p, mode, rest.slice(1).join('/'))}</div>`;
  };
})();
