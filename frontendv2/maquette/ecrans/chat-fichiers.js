/* Les fichiers du chat — validé le 2026-11-26 (ADR 0312). Posé par-dessus l'écran Chat validé, sans le
   retoucher :
   - dans le fil (#chat/fichiers), tes pièces se montrent comme les siennes : une image en vignette, un document en
     carte (sa sorte, son nom, sa taille) ; un clic l'ouvre dans la visionneuse, « Enregistrer » la télécharge ;
   - la visionneuse : une image en grand, un PDF dans le lecteur du navigateur, un texte ou un Markdown lisible, un CSV
     en tableau ; les autres sortes se disent et s'enregistrent ; précédent et suivant parcourent les fichiers ;
   - « Fichiers » (en haut à droite) : tous les fichiers de la conversation, pas seulement les messages chargés —
     chercher par nom, trier par sorte et par qui l'a envoyé, en liste ou en vignettes, page par page.
   Pour les captures : ?panneau=1 ouvre « Fichiers », ?voir=<id> ouvre la visionneuse (f-devis, f-tableau, f-notes,
   f-comp, f-budget, f-vacances), ?grille=1 les vignettes. L'écran se passe le jeudi 26 novembre 2026. */
(function () {
  const C = M.ecrans.chat;
  if (!C) return;
  const { h, ico, av } = M;
  const q = new URLSearchParams(location.search);

  // ── Des images dessinées (la maquette n'a pas de vraies photos) ──────────
  const svg = (corps, fond) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 440"><rect width="640" height="440" fill="${fond}"/>${corps}</svg>`);
  const IMG = {
    tableau: svg(`<rect x="40" y="36" width="560" height="360" rx="8" fill="#fbfbf8" stroke="#c9c9c2" stroke-width="6"/>
      <text x="80" y="96" font-family="Comic Sans MS, cursive" font-size="30" fill="#2347b5">Lumen — sprint 12</text>
      <rect x="80" y="130" width="140" height="80" rx="6" fill="none" stroke="#c03a3a" stroke-width="4"/><text x="98" y="178" font-family="cursive" font-size="20" fill="#c03a3a">API /moi</text>
      <rect x="300" y="130" width="160" height="80" rx="6" fill="none" stroke="#2f8a43" stroke-width="4"/><text x="318" y="178" font-family="cursive" font-size="20" fill="#2f8a43">Android v2</text>
      <path d="M220 170 L300 170" stroke="#333" stroke-width="4" marker-end="url(#a)"/>
      <path d="M80 260 h340 M80 300 h260 M80 340 h300" stroke="#2347b5" stroke-width="5" stroke-linecap="round"/>
      <circle cx="520" cy="300" r="46" fill="#ffe27a" opacity=".8"/><text x="492" y="308" font-family="cursive" font-size="20" fill="#7a5a00">J-4</text>`, '#8c8f99'),
    salon: svg(`<rect y="250" width="640" height="190" fill="#b98b5e"/><rect x="60" y="60" width="200" height="150" fill="#cfe6f7" stroke="#fff" stroke-width="10"/>
      <rect x="330" y="190" width="250" height="90" rx="14" fill="#5d6a8a"/><rect x="345" y="160" width="220" height="50" rx="12" fill="#6f7ca0"/>
      <rect x="120" y="300" width="150" height="20" fill="#7a5233"/>`, '#e9dcc8'),
    carrelage: svg(Array.from({ length: 8 }, (_, i) => Array.from({ length: 6 }, (_, j) =>
      `<rect x="${i * 80 + 2}" y="${j * 74 + 2}" width="76" height="70" fill="${(i + j) % 2 ? '#d9d4ca' : '#f1ede4'}"/>`).join('')).join(''), '#b7b0a2'),
    erreur: svg(`<rect x="30" y="30" width="580" height="380" rx="10" fill="#1e1f29"/><rect x="30" y="30" width="580" height="34" rx="10" fill="#2c2d3a"/>
      <circle cx="54" cy="47" r="7" fill="#ff5f57"/><circle cx="76" cy="47" r="7" fill="#febc2e"/><circle cx="98" cy="47" r="7" fill="#28c840"/>
      <text x="56" y="104" font-family="monospace" font-size="18" fill="#9ad1ff">$ npm run build</text>
      <text x="56" y="140" font-family="monospace" font-size="18" fill="#e6e6ef">src/screens/chat/markup.ts:141:7</text>
      <text x="56" y="172" font-family="monospace" font-size="18" fill="#ff7b8a">error TS2322: Type 'string | undefined'</text>
      <text x="56" y="200" font-family="monospace" font-size="18" fill="#ff7b8a">is not assignable to type 'string'.</text>`, '#11121a'),
    schema: svg(`<g fill="#fff" stroke="#4f46e5" stroke-width="4"><rect x="60" y="80" width="150" height="70" rx="10"/><rect x="430" y="80" width="150" height="70" rx="10"/><rect x="245" y="280" width="150" height="70" rx="10"/></g>
      <g stroke="#4f46e5" stroke-width="3"><path d="M210 115 H430"/><path d="M135 150 L300 280"/><path d="M505 150 L340 280"/></g>
      <g font-family="sans-serif" font-size="20" fill="#14141d"><text x="98" y="122">Box</text><text x="462" y="122">Portable</text><text x="282" y="322">NAS</text></g>`, '#eef0ff'),
    velleda: svg(`<rect x="50" y="50" width="540" height="340" fill="#fff" stroke="#ddd" stroke-width="4"/>
      <path d="M90 120 q60 -40 120 0 t120 0 t120 0" stroke="#1d6b3a" stroke-width="6" fill="none"/>
      <path d="M90 220 h420 M90 270 h300 M90 320 h360" stroke="#333" stroke-width="5" stroke-linecap="round"/>`, '#a7abb5'),
  };

  // ── Les fichiers de la conversation (les plus récents d'abord) ────────────
  const DEVIS = [['Démolition et évacuation', '1 200,00'], ['Plomberie — cuisine', '2 480,00'], ['Électricité — mise aux normes', '3 150,00'],
    ['Carrelage sol (32 m²)', '2 960,00'], ['Main-d\'œuvre pose', '4 870,00'], ['Fournitures diverses', '640,00']];
  const COMP = [['Poste', 'Devis Lefèvre', 'Budget', 'Écart'], ['Démolition', '1 200', '1 000', '+200'], ['Plomberie', '2 480', '2 500', '−20'],
    ['Électricité', '3 150', '3 000', '+150'], ['Carrelage', '2 960', '3 000', '−40'], ['Main-d\'œuvre', '4 870', '3 920', '+950'], ['Total', '15 300', '14 060', '+1 240']];
  const NOTES = `# Réunion Lumen — 26 novembre

## Décidé
- l'API /moi garde un seul point d'entrée par domaine
- **Android v2** : on vise la semaine prochaine pour la bêta

## À faire
1. Marc relit le contrat de bail avant vendredi
2. Adrien envoie les slides v3 à Sophie
3. Revoir le budget de la rénovation (écart sur la main-d'œuvre)

> Prochaine réunion : jeudi 3 décembre, 10 h.`;
  const LOG = `> mika-front@2.0.0 build
> tsc -p tsconfig.json && vite build

src/screens/chat/markup.ts:141:7 - error TS2322: Type 'string | undefined' is not assignable to type 'string'.

141       href: a.url,
          ~~~~

Found 1 error in src/screens/chat/markup.ts:141`;

  let n = 0;
  const F = (nom, sorte, de, quand, taille, extra) => ({ id: (extra && extra.id) || `f${++n}`, nom, sorte, de, quand, taille, ...(extra || {}) });
  const FICHIERS = [
    F('tableau-blanc.jpg', 'image', 'moi', "aujourd'hui 14:05", '1,8 Mo', { id: 'f-tableau', img: IMG.tableau, mime: 'image JPEG', dim: '4032 × 3024' }),
    F('notes-reunion-lumen.md', 'texte', 'moi', "aujourd'hui 14:02", '4 Ko', { id: 'f-notes', texte: NOTES, mime: 'Markdown', md: true }),
    F('comparatif-devis-lefevre.csv', 'csv', 'mika', "aujourd'hui 13:32", '3 Ko', { id: 'f-comp', csv: COMP, mime: 'CSV' }),
    F('devis-2026-114.pdf', 'pdf', 'moi', "aujourd'hui 13:31", '212 Ko', { id: 'f-devis', mime: 'PDF', pages: 2, devis: true }),
    F('photo-salon-avant.jpg', 'image', 'moi', 'hier 19:40', '2,4 Mo', { id: 'f-salon', img: IMG.salon, mime: 'image JPEG' }),
    F('carrelage-choix.jpg', 'image', 'moi', 'hier 19:40', '1,1 Mo', { id: 'f-carrelage', img: IMG.carrelage, mime: 'image JPEG' }),
    F('plan-cuisine-v2.pdf', 'pdf', 'mika', 'hier 18:12', '96 Ko', { mime: 'PDF', pages: 1 }),
    F('capture-erreur-build.png', 'image', 'moi', 'hier 10:03', '640 Ko', { img: IMG.erreur, mime: 'image PNG' }),
    F('build-log.txt', 'texte', 'moi', 'hier 10:03', '18 Ko', { texte: LOG, mime: 'texte' }),
    F('budget-renovation.xlsx', 'autre', 'moi', 'lun. 23 nov.', '412 Ko', { id: 'f-budget', mime: 'classeur Excel' }),
    F('resume-semaine.md', 'texte', 'mika', 'lun. 23 nov.', '2 Ko', { texte: '# Ta semaine\n\n- trois réunions Lumen\n- le devis de Lefèvre à comparer\n- l\'anniversaire de Léa samedi', mime: 'Markdown', md: true }),
    F('slides-lumen-v3.pdf', 'pdf', 'moi', 'dim. 22 nov.', '3,1 Mo', { mime: 'PDF', pages: 14 }),
    F('photo-tableau-velleda.jpg', 'image', 'moi', 'sam. 21 nov.', '1,6 Mo', { img: IMG.velleda, mime: 'image JPEG' }),
    F('liste-courses.txt', 'texte', 'mika', 'ven. 20 nov.', '1 Ko', { texte: 'pain\ncafé en grains\ntomates\nlessive', mime: 'texte' }),
    F('contrat-bail.pdf', 'pdf', 'moi', 'mer. 18 nov.', '1,4 Mo', { mime: 'PDF', pages: 9 }),
    F('itineraire-lyon.gpx', 'autre', 'mika', 'mar. 17 nov.', '28 Ko', { mime: 'trace GPX' }),
    F('export-contacts.csv', 'csv', 'moi', 'lun. 16 nov.', '22 Ko', { csv: [['Nom', 'Courriel', 'Téléphone'], ['Claire Martin', 'claire@…', '06 …'], ['Marc Duval', 'marc@…', '06 …']], mime: 'CSV' }),
    F('schema-reseau.png', 'image', 'mika', 'sam. 14 nov.', '88 Ko', { img: IMG.schema, mime: 'image PNG' }),
    F('facture-edf-octobre.pdf', 'pdf', 'moi', 'jeu. 12 nov.', '180 Ko', { mime: 'PDF', pages: 2 }),
    F('notes-medecin.txt', 'texte', 'moi', 'mar. 10 nov.', '2 Ko', { texte: 'Rendez-vous le 2 décembre à 9 h 30.\nApporter les résultats.', mime: 'texte' }),
    F('photo-vacances-annecy.jpg', 'image', 'moi', 'ven. 6 nov.', '3,8 Mo', { id: 'f-vacances', mime: 'image JPEG', retire: 'trop vieux' }),
    F('ancien-plan-salon.png', 'image', 'moi', 'lun. 2 nov.', '410 Ko', { mime: 'image PNG', retire: 'la place manquait' }),
    F('archive-photos.zip', 'autre', 'moi', 'ven. 30 oct.', '4,9 Mo', { mime: 'archive ZIP', retire: 'trop vieux' }),
    F('synthese-lectures.md', 'texte', 'mika', 'mer. 28 oct.', '6 Ko', { texte: '# Lectures d\'octobre\n\n- *Le Problème à trois corps*\n- *Klara et le Soleil*', mime: 'Markdown', md: true }),
    F('cv-2026.pdf', 'pdf', 'moi', 'dim. 25 oct.', '240 Ko', { mime: 'PDF', pages: 2 }),
    F('tableau-depenses.csv', 'csv', 'mika', 'mar. 20 oct.', '9 Ko', { csv: [['Mois', 'Dépenses'], ['août', '1 820'], ['septembre', '2 140'], ['octobre', '1 960']], mime: 'CSV' }),
  ];
  const par = Object.fromEntries(FICHIERS.map((f) => [f.id, f]));

  const SORTES = { image: 'Images', pdf: 'PDF', texte: 'Textes', csv: 'Tableaux', autre: 'Autres' };
  const BADGE = { pdf: 'PDF', csv: 'CSV' };
  const ext = (nom) => (nom.split('.').pop() || '').toUpperCase().slice(0, 4);
  const sansAccent = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  /* Une tuile de sorte : la vignette d'une image, sinon un carré de couleur avec l'extension. */
  function tuile(f, taille) {
    if (f.sorte === 'image' && f.img && !f.retire) return `<span class="fx-tile ${taille || ''} img"><img src="${f.img}" alt=""></span>`;
    if (f.sorte === 'image') return `<span class="fx-tile ${taille || ''} k-image">${ico('image', 'sm')}</span>`;
    return `<span class="fx-tile ${taille || ''} k-${f.sorte}">${h(BADGE[f.sorte] || ext(f.nom))}</span>`;
  }
  const deQui = (f) => (f.de === 'moi' ? 'Toi' : 'Mika');

  // ── Dans le fil ──────────────────────────────────────────────────────────
  /* Une pièce dans une bulle : image en vignette, document en carte ; un clic ouvre la visionneuse. */
  function piece(f, etat) {
    if (f.retire) {
      return `<div class="msg-file gone">${tuile(f)}<span class="mf-txt"><b>${h(f.nom)}</b><small>plus disponible · ${h(f.retire)}</small></span></div>`;
    }
    const attente = etat === 'envoi' ? `<span class="mf-wait">${ico('clock', 'xs')}envoi…</span>` : '';
    if (f.sorte === 'image') {
      return `<button class="msg-file img mf-open" type="button" data-voir="${f.id}" title="Voir en grand">
        <img src="${f.img}" alt="${h(f.nom)}">${attente}<span class="mf-zoom">${ico('expand', 'sm')}</span>
        <span class="mf-cap">${h(f.nom)} · ${h(f.taille)}</span></button>`;
    }
    const sous = [f.taille, f.pages ? `${f.pages} page${f.pages > 1 ? 's' : ''}` : f.mime].filter(Boolean).join(' · ');
    return `<div class="msg-file doc">
      <button class="mf-open mf-main" type="button" data-voir="${f.id}" title="Ouvrir l'aperçu">${tuile(f)}<span class="mf-txt"><b>${h(f.nom)}</b><small>${h(sous)}</small></span></button>
      <button class="btn icon ghost xs" type="button" data-enreg="${f.id}" title="Enregistrer" aria-label="Enregistrer">${ico('download', 'sm')}</button></div>`;
  }
  const moi = (t, txt, pieces, etat) => `<div class="msg me">${pieces.length > 1 && pieces.every((p) => p.sorte === 'image')
    ? `<div class="mf-grid">${pieces.map((p) => piece(p, etat)).join('')}</div>` : pieces.map((p) => piece(p, etat)).join('')}
    ${txt ? `<div class="bubble">${h(txt)}</div>` : ''}
    <div class="msg-meta">${h(t)}${etat === 'envoi' ? ` · ${ico('clock', 'xs')} en attente d'envoi` : ` · ${ico('checks', 'xs')} lu`}</div></div>`;
  const elle = (t, bulles, pieces) => `<div class="msg her">${av('mika', 'sm')}<div class="msg-col">${bulles.map((b) => `<div class="bubble">${h(b)}</div>`).join('')}
    ${(pieces || []).map((p) => piece(p)).join('')}<div class="msg-meta">${h(t)}</div></div></div>`;

  function fil() {
    return `<div class="day"><span>Vendredi 6 novembre</span></div>
      ${moi('18:20', 'souvenir d\'Annecy 🏔️', [par['f-vacances']])}
      <div class="day"><span>Hier</span></div>
      ${moi('19:40', 'le salon avant travaux, et le carrelage que j\'hésite à prendre', [par['f-salon'], par['f-carrelage']])}
      ${elle('19:41', ['le carrelage en damier irait bien avec le parquet clair', 'par contre il faudra un joint gris, sinon ça va vite marquer'])}
      <div class="day"><span>Aujourd'hui</span></div>
      ${moi('13:31', 'compare ce devis de Lefèvre Rénovation avec le budget du projet, ligne par ligne', [par['f-devis']])}
      ${elle('13:32', ['fait. ça dépasse de 1 240 € au total, presque tout sur la main-d\'œuvre (+950 €)', 'je t\'ai mis le comparatif ligne par ligne'], [par['f-comp']])}
      ${moi('14:02', 'mes notes de la réunion, tu peux me faire la liste des tâches ?', [par['f-notes']])}
      ${elle('14:03', ['trois tâches : Marc relit le bail avant vendredi, toi tu envoies les slides v3 à Sophie, et vous revoyez le budget de la rénovation'])}
      ${moi('14:05', 'parfait merci, je regarde', [par['f-tableau']], 'envoi')}`;
  }
  function greffer(body) {
    const thread = body.querySelector('.chat-thread'), typing = thread && thread.querySelector('[data-typing]');
    if (!thread || !typing) return;
    [...thread.children].forEach((x) => { if (x !== typing) x.remove(); });
    typing.insertAdjacentHTML('beforebegin', fil());
    const dock = body.querySelector('.chat-dock');
    if (dock) dock.querySelectorAll(':scope > .approval').forEach((x) => x.remove());
    const s = body.querySelector('[data-scroll]');
    if (s) s.scrollTop = s.scrollHeight;
  }

  // ── La visionneuse ───────────────────────────────────────────────────────
  let suite = FICHIERS.filter((f) => !f.retire);   // ce que précédent et suivant parcourent : le fil, ou la liste filtrée du panneau
  let depuisPanneau = false;
  /* Un petit Markdown, échappé d'abord (le vrai écran reprend le rendu des pages de documentation). */
  const md = (src) => {
    const out = [];
    let liste = '';
    const fermer = () => { if (liste) { out.push(`</${liste}>`); liste = ''; } };
    for (const l of h(src).split('\n')) {
      const ul = /^- (.*)/.exec(l), ol = /^\d+\. (.*)/.exec(l);
      if (ul || ol) {
        const t = ul ? 'ul' : 'ol';
        if (liste !== t) { fermer(); out.push(`<${t}>`); liste = t; }
        out.push(`<li>${(ul || ol)[1]}</li>`);
        continue;
      }
      fermer();
      if (/^## /.test(l)) out.push(`<h2>${l.slice(3)}</h2>`);
      else if (/^# /.test(l)) out.push(`<h1>${l.slice(2)}</h1>`);
      else if (/^&gt; /.test(l)) out.push(`<blockquote>${l.slice(5)}</blockquote>`);
      else if (l.trim()) out.push(`<p>${l}</p>`);
    }
    fermer();
    return out.join('').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\*(.+?)\*/g, '<i>$1</i>');
  };
  let vueTexte = 'rendu';

  function pagePdf(f, i) {
    if (f.devis && i === 0) {
      return `<div class="pdf-page"><div class="pdf-hd"><b>LEFÈVRE RÉNOVATION</b><span>Devis n° 2026-114 · 19 novembre 2026</span></div>
        <p class="pdf-to">Pour : Adrien · Rénovation cuisine et salon</p>
        <table class="pdf-tbl"><thead><tr><th>Désignation</th><th>Montant HT</th></tr></thead><tbody>
        ${DEVIS.map(([a, b]) => `<tr><td>${h(a)}</td><td>${b} €</td></tr>`).join('')}</tbody>
        <tfoot><tr><td>Total HT</td><td>15 300,00 €</td></tr></tfoot></table>
        <p class="pdf-small">Devis valable 3 mois. Acompte de 30 % à la signature.</p></div>`;
    }
    return `<div class="pdf-page"><div class="pdf-lines">${Array.from({ length: 16 }, (_, k) => `<i style="width:${60 + ((k * 37 + i * 11) % 38)}%"></i>`).join('')}</div>
      <span class="pdf-num">${i + 1}</span></div>`;
  }

  function corps(f) {
    if (f.retire) {
      return `<div class="vw-none">${tuile(f, 'xl')}<b>Ce fichier a été retiré</b>
        <p>${h(f.retire === 'trop vieux' ? 'Il était trop vieux' : 'La place manquait')} : son nom reste dans la conversation, plus son contenu.</p></div>`;
    }
    if (f.sorte === 'image') {
      return `<div class="vw-img"><img src="${f.img}" alt="${h(f.nom)}"></div>`;
    }
    if (f.sorte === 'pdf') {
      return `<div class="vw-pdf"><div class="pdf-bar"><span>${h(f.nom)}</span><span class="grow"></span><span>1 / ${f.pages}</span><span class="pdf-sep"></span><span>−</span><span>100 %</span><span>+</span></div>
        <div class="pdf-scroll">${Array.from({ length: Math.min(f.pages, 3) }, (_, i) => pagePdf(f, i)).join('')}</div></div>`;
    }
    if (f.sorte === 'texte') {
      const lignes = f.texte.split('\n');
      const source = `<pre class="vw-src">${lignes.map((l, i) => `<span class="ln">${i + 1}</span>${h(l) || ' '}`).join('\n')}</pre>`;
      return `<div class="vw-text">${f.md ? `<div class="vw-text-bar"><div class="seg"><button type="button" data-vtexte="rendu" aria-pressed="${vueTexte === 'rendu'}">Rendu</button><button type="button" data-vtexte="source" aria-pressed="${vueTexte === 'source'}">Source</button></div>
        <span class="small muted">${lignes.length} lignes</span></div>` : `<div class="vw-text-bar"><span class="small muted">${lignes.length} lignes · UTF-8</span></div>`}
        ${f.md && vueTexte === 'rendu' ? `<div class="vw-md">${md(f.texte)}</div>` : source}</div>`;
    }
    if (f.sorte === 'csv') {
      const [tete, ...rangs] = f.csv;
      return `<div class="vw-text"><div class="vw-text-bar"><span class="small muted">${rangs.length} lignes · ${tete.length} colonnes · séparateur « ; »</span></div>
        <div class="vw-csv"><table class="tbl"><thead><tr>${tete.map((c) => `<th>${h(c)}</th>`).join('')}</tr></thead>
        <tbody>${rangs.map((r) => `<tr>${r.map((c) => `<td>${h(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
    }
    return `<div class="vw-none">${tuile(f, 'xl')}<b>Pas d'aperçu pour un fichier ${h(ext(f.nom))}</b>
      <p>${h(f.mime)} · ${h(f.taille)}. Enregistre-le pour l'ouvrir avec ton application.</p>
      <button class="btn primary" type="button" data-enreg="${f.id}">${ico('download', 'sm')}Enregistrer</button></div>`;
  }

  function voir(id) {
    const f = par[id];
    if (!f) return;
    const liste = suite.some((x) => x.id === id) ? suite : FICHIERS;
    const i = liste.findIndex((x) => x.id === id);
    const nav = liste.length > 1 ? `<span class="vw-count">${i + 1} / ${liste.length}</span>
      <button class="btn icon ghost sm" type="button" data-vnav="-1" title="Précédent (←)" aria-label="Précédent"${i === 0 ? ' disabled' : ''}>${ico('chev-left')}</button>
      <button class="btn icon ghost sm" type="button" data-vnav="1" title="Suivant (→)" aria-label="Suivant"${i === liste.length - 1 ? ' disabled' : ''}>${ico('chev-right')}</button>` : '';
    const entete = `${f.retire ? '' : `<button class="btn sm" type="button" data-enreg="${f.id}">${ico('download', 'sm')}<span class="lbl">Enregistrer</span></button>`}
      <button class="btn ghost sm" type="button" data-vfil="${f.id}" title="Voir le message dans la conversation">${ico('chat', 'sm')}<span class="lbl">Dans la conversation</span></button>`;
    const m = M.modal({ titre: f.nom, taille: 'wide', entete, corps: corps(f),
      pied: `<span class="vw-who">${av(f.de === 'moi' ? 'adrien' : 'mika', 'xs')}<span>${deQui(f)} · ${h(f.quand)}</span></span>
        <span class="muted small">${h([f.mime, f.taille, f.dim].filter(Boolean).join(' · '))}</span><span class="grow"></span>
        ${depuisPanneau ? `<button class="btn ghost sm" type="button" data-vretour>${ico('chev-left', 'sm')}Tous les fichiers</button>` : ''}${nav}` });
    m.classList.add('fx-viewer', `fx-${f.retire ? 'none' : f.sorte}`);
    M.on(m, '[data-vnav]', 'click', (e, b) => { const j = i + Number(b.dataset.vnav); if (liste[j]) voir(liste[j].id); });
    M.on(m, '[data-vtexte]', 'click', (e, b) => { vueTexte = b.dataset.vtexte; voir(id); });
    M.on(m, '[data-vretour]', 'click', () => panneau());
    M.on(m, '[data-vfil]', 'click', () => { M.fermerModal(); M.toast('Maquette : le fil remonterait jusqu\'au message (pages plus anciennes comprises), surligné.', { ico: 'chat' }); });
    m._clavier = (e) => {
      if (e.key === 'ArrowLeft' && liste[i - 1]) voir(liste[i - 1].id);
      if (e.key === 'ArrowRight' && liste[i + 1]) voir(liste[i + 1].id);
    };
  }
  document.addEventListener('keydown', (e) => {
    const m = document.querySelector('.modal.fx-viewer');
    if (m && m._clavier && !e.target.closest('input, textarea')) m._clavier(e);
  });
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-enreg]');
    if (!b) return;
    const f = par[b.dataset.enreg];
    M.toast(`Maquette : « ${f.nom} » se téléchargerait (ta copie, gardée par le serveur).`, { ico: 'download' });
  });

  // ── Le panneau « Fichiers » ──────────────────────────────────────────────
  const P = { q: '', sorte: '', de: '', page: 0, grille: q.get('grille') === '1' };
  const PAR_PAGE = 12;
  function filtres() {
    const mot = sansAccent(P.q.trim());
    return FICHIERS.filter((f) => (!P.sorte || f.sorte === P.sorte) && (!P.de || f.de === P.de) && (!mot || sansAccent(f.nom).includes(mot)));
  }
  function lignes(page) {
    return `<table class="tbl fx-tbl"><thead><tr><th>Fichier</th><th class="fx-c-de">De</th><th class="fx-c-quand">Quand</th><th class="fx-c-taille">Taille</th><th></th></tr></thead><tbody>
      ${page.map((f) => `<tr class="${f.retire ? 'gone' : ''}"${f.retire ? '' : ` data-voir="${f.id}"`}>
        <td><span class="fx-name">${tuile(f)}<span><b>${h(f.nom)}</b><small>${f.retire ? `plus disponible · ${h(f.retire)}` : h(f.mime)}<span class="fx-m"> · ${deQui(f)} · ${h(f.quand)}</span></small></span></span></td>
        <td class="fx-c-de"><span class="fx-who">${av(f.de === 'moi' ? 'adrien' : 'mika', 'xs')}${deQui(f)}</span></td>
        <td class="fx-c-quand">${h(f.quand)}</td><td class="fx-c-taille">${h(f.taille)}</td>
        <td class="actions">${f.retire ? '' : `<button class="btn icon ghost xs" type="button" data-voir="${f.id}" title="Aperçu" aria-label="Aperçu">${ico('eye', 'sm')}</button>
          <button class="btn icon ghost xs" type="button" data-enreg="${f.id}" title="Enregistrer" aria-label="Enregistrer">${ico('download', 'sm')}</button>`}
          <button class="btn icon ghost xs" type="button" data-pfil="${f.id}" title="Voir le message" aria-label="Voir le message">${ico('chat', 'sm')}</button></td></tr>`).join('')}</tbody></table>`;
  }
  function grille(page) {
    return `<div class="fx-grid">${page.map((f) => `<button class="fx-card${f.retire ? ' gone' : ''}" type="button"${f.retire ? ' disabled' : ` data-voir="${f.id}"`}>
      <span class="fx-thumb">${f.sorte === 'image' && f.img && !f.retire ? `<img src="${f.img}" alt="">` : tuile(f, 'lg')}</span>
      <b>${h(f.nom)}</b><small>${f.retire ? 'plus disponible' : `${deQui(f)} · ${h(f.quand)}`}</small></button>`).join('')}</div>`;
  }
  function contenuPanneau() {
    const tous = filtres();
    const pages = Math.max(1, Math.ceil(tous.length / PAR_PAGE));
    P.page = Math.min(P.page, pages - 1);
    const page = tous.slice(P.page * PAR_PAGE, (P.page + 1) * PAR_PAGE);
    suite = tous.filter((f) => !f.retire);
    const retires = FICHIERS.filter((f) => f.retire).length;
    const vide = `<div class="empty">${ico('search')}<b>Aucun fichier ne correspond</b><p>Essaie un autre mot, ou retire un filtre.</p>
      <button class="btn sm" type="button" data-preset>Tout montrer</button></div>`;
    return `<div class="fx-list">${tous.length ? (P.grille ? grille(page) : lignes(page)) : vide}</div>
      <div class="fx-pager"><span class="muted small">${tous.length ? `${P.page * PAR_PAGE + 1}–${P.page * PAR_PAGE + page.length} sur ${tous.length}` : '0 fichier'}${!P.q && !P.sorte && !P.de ? ` · dont ${retires} retirés` : ''}</span>
        <span class="grow"></span>
        <button class="btn icon ghost sm" type="button" data-ppage="-1" title="Page précédente" aria-label="Page précédente"${P.page === 0 ? ' disabled' : ''}>${ico('chev-left')}</button>
        <span class="small">${P.page + 1} / ${pages}</span>
        <button class="btn icon ghost sm" type="button" data-ppage="1" title="Page suivante" aria-label="Page suivante"${P.page >= pages - 1 ? ' disabled' : ''}>${ico('chev-right')}</button></div>`;
  }
  function barre() {
    const seg = (cle, choix) => `<div class="seg" role="group">${choix.map(([v, l]) => `<button type="button" data-pf="${cle}" data-v="${v}" aria-pressed="${P[cle] === v}">${l}</button>`).join('')}</div>`;
    return `<div class="fx-bar">
      <label class="search fx-search">${ico('search', 'sm')}<input type="search" data-pq placeholder="Chercher un fichier par son nom" value="${h(P.q)}" aria-label="Chercher un fichier"></label>
      ${seg('de', [['', 'Tous'], ['moi', 'Toi'], ['mika', 'Mika']])}
      <div class="seg" role="group" aria-label="Affichage"><button type="button" data-pg="0" aria-pressed="${!P.grille}" title="En liste">${ico('menu', 'sm')}</button><button type="button" data-pg="1" aria-pressed="${P.grille}" title="En vignettes">${ico('image', 'sm')}</button></div></div>
      <div class="fx-kinds">${[['', 'Tout'], ...Object.entries(SORTES)].map(([v, l]) => `<button class="fx-kind" type="button" data-pf="sorte" data-v="${v}" aria-pressed="${P.sorte === v}">${l}<span class="cnt">${FICHIERS.filter((f) => !v || f.sorte === v).length}</span></button>`).join('')}</div>`;
  }
  function panneau() {
    depuisPanneau = true;
    const m = M.modal({ titre: 'Les fichiers de la conversation', taille: 'wide', corps: `${barre()}<div data-pcontenu>${contenuPanneau()}</div>` });
    m.classList.add('fx-panel');
    const repeindre = () => { m.querySelector('[data-pcontenu]').innerHTML = contenuPanneau(); };
    m.querySelector('[data-pq]').addEventListener('input', (e) => { P.q = e.target.value; P.page = 0; repeindre(); });
    M.on(m, '[data-pf]', 'click', (e, b) => {
      P[b.dataset.pf] = b.dataset.v; P.page = 0;
      m.querySelectorAll(`[data-pf="${b.dataset.pf}"]`).forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      repeindre();
    });
    M.on(m, '[data-pg]', 'click', (e, b) => { P.grille = b.dataset.pg === '1'; m.querySelectorAll('[data-pg]').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); repeindre(); });
    M.on(m, '[data-ppage]', 'click', (e, b) => { P.page += Number(b.dataset.ppage); repeindre(); m.querySelector('.fx-list').scrollTop = 0; });
    M.on(m, '[data-preset]', 'click', () => { Object.assign(P, { q: '', sorte: '', de: '', page: 0 }); panneau(); });
    M.on(m, '[data-pfil]', 'click', (e, b) => { e.stopPropagation(); M.fermerModal(); M.toast('Maquette : le fil remonterait jusqu\'au message, surligné.', { ico: 'chat' }); });
    M.on(m, '[data-voir]', 'click', (e, b) => { if (e.target.closest('[data-enreg], [data-pfil]')) return; voir(b.dataset.voir); });
    setTimeout(() => m.querySelector('[data-pq]').focus(), 40);
  }

  // ── Le branchement sur l'écran Chat ──────────────────────────────────────
  const rendu0 = C.rendu, monte0 = C.monte, notes0 = C.notes;
  C.rendu = (body, ctx) => {
    rendu0(body, ctx);
    if (ctx.item === 'fichiers' && !body.querySelector('.pro-split')) greffer(body);
  };
  C.monte = (sec) => {
    monte0(sec);
    // « Fichiers » en haut : ce panneau à la place de l'ancienne table (le gestionnaire d'avant s'ouvre, celui-ci le remplace)
    M.on(sec, '[data-head="fichiers"]', 'click', () => panneau());
    M.on(sec, '[data-voir]', 'click', (e, b) => { depuisPanneau = false; suite = FICHIERS.filter((f) => !f.retire); voir(b.dataset.voir); });
  };
  C.notes = (ctx) => (ctx.item !== 'fichiers' ? notes0(ctx) : [
    { groupe: 'Les fichiers du chat (validé le 2026-11-26, ADR 0312)', statut: 'existe', titre: 'Ta copie de chaque pièce', texte: 'une pièce que tu envoies est gardée et te revient, à toi seule : GET /files/<id>, 410 une fois retirée', src: 'ADR 0215 · app/mindport.py · adapters/web/app.py' },
    { statut: 'decide', titre: 'Tes pièces dans le fil', texte: 'comme les siennes : vignette, carte d\'un document, « plus disponible » ; un envoi en cours s\'ouvre depuis la copie du navigateur, puis depuis celle du serveur dès qu\'il l\'a gardée' },
    { statut: 'decide', titre: 'La visionneuse', texte: 'image en grand ; PDF dans le lecteur du navigateur ; texte et Markdown (rendu échappé ou source) ; CSV en tableau ; le reste se dit et s\'enregistre. Rien n\'est jamais rendu en HTML ni exécuté : le serveur sert toujours en pièce jointe, l\'aperçu lit les octets' },
    { statut: 'decide', titre: '« Fichiers » sur toute la conversation', texte: 'une nouvelle lecture de l\'API par personne, page par page, filtrée par nom, sorte et qui l\'a envoyé : plus seulement les messages chargés' },
    { statut: 'À trancher', titre: 'Chercher dans le contenu', texte: 'proposé : par nom seulement. Le texte qu\'elle a lu d\'un document (pour son prompt) pourrait servir à chercher dedans, plus tard' },
    { statut: 'À trancher', titre: 'Les fichiers des fils de travail', texte: 'proposé : la conversation ordinaire seulement ; en mode pro, le panneau montrerait ceux du fil ouvert' },
  ]);

  if (q.get('panneau') === '1') setTimeout(panneau, 300);
  if (q.get('voir')) setTimeout(() => voir(q.get('voir')), 350);
})();
