/* Carte : chercher un lieu ou une adresse, calculer un itinéraire, préparer un voyage à deux (ADR 0194 à 0196). La
   carte prend l'écran, la recherche flotte dessus, la liste monte du bas, comme les cartes d'Android. Le fond est
   celui de la maquette du frontendv2 (la France simplifiée, © OpenStreetMap) ; la vraie app montre la carte
   vectorielle que le serveur sert (ADR 0193). Rose : ce que Mika a cherché, proposé ou ajouté. */
(function () {
  const { h, ico, D } = A;
  const F = window.MIKA_FOND;
  const [VW, VH] = F.viewBox;
  const mx = (lon) => (lon + 180) / 360;
  const my = (lat) => { const r = lat * Math.PI / 180; return (1 - Math.asinh(Math.tan(r)) / Math.PI) / 2; };
  const X0 = mx(F.proj.W), X1 = mx(F.proj.E), Y0 = my(F.proj.N), Y1 = my(F.proj.S);
  const xy = ([lon, lat]) => [(mx(lon) - X0) / (X1 - X0) * VW, (my(lat) - Y0) / (Y1 - Y0) * VH];

  const V = {
    lille: [3.063, 50.637], arras: [2.78, 50.29], cambrai: [3.23, 50.17], stquentin: [3.29, 49.85], laon: [3.62, 49.56],
    reims: [4.032, 49.258], chalons: [4.36, 48.96], troyes: [4.074, 48.297], chaumont: [5.14, 48.11], langres: [5.33, 47.86],
    dijon: [5.041, 47.322], dole: [5.49, 47.09], bourg: [5.23, 46.21], nantua: [5.61, 46.15], bellegarde: [5.83, 46.11],
    stjulien: [6.08, 46.14], annecy: [6.129, 45.899], bonneville: [6.40, 46.08], cluses: [6.58, 46.06], sallanches: [6.63, 45.94],
    chamonix: [6.869, 45.924], chambery: [5.92, 45.57], grenoble: [5.724, 45.188], lus: [5.70, 44.65], sisteron: [5.944, 44.196],
    arnoux: [6.0, 44.09], riez: [6.09, 43.82], moustiers: [6.221, 43.846], castellane: [6.51, 43.85], grasse: [6.92, 43.66],
    nice: [7.262, 43.710], sevrier: [6.141, 45.866], jorioz: [6.166, 45.832], duingt: [6.200, 45.826], doussard: [6.222, 45.785],
    talloires: [6.215, 45.840], menthon: [6.196, 45.862], veyrier: [6.170, 45.887], verdon: [6.398, 43.796], stecroix: [6.17, 43.78],
  };
  const pt = (k) => (typeof k === 'string' ? V[k] : k);
  const LAC = [[6.128, 45.902], [6.150, 45.899], [6.167, 45.887], [6.180, 45.872], [6.195, 45.858], [6.208, 45.846], [6.212, 45.833],
    [6.206, 45.826], [6.212, 45.815], [6.221, 45.800], [6.218, 45.791], [6.209, 45.794], [6.199, 45.808], [6.190, 45.821], [6.178, 45.828],
    [6.165, 45.836], [6.152, 45.850], [6.143, 45.864], [6.135, 45.878], [6.127, 45.891]];
  const SEMNOZ = [[6.085, 45.855], [6.105, 45.835], [6.120, 45.810], [6.130, 45.790], [6.115, 45.785], [6.095, 45.805], [6.078, 45.835]];
  const TOURNETTE = [[6.245, 45.850], [6.262, 45.840], [6.275, 45.820], [6.268, 45.805], [6.250, 45.812], [6.240, 45.832]];
  const ROUTES_LAC = [['annecy', 'sevrier', 'jorioz', 'duingt', 'doussard'], ['annecy', 'veyrier', 'menthon', 'talloires', 'doussard'], ['annecy', [6.12, 45.95], [6.10, 46.03]]];

  const LIEUX = [
    { id: 'horizon', nom: 'Camping de l\'Horizon', sorte: 'Camping', ville: 'Sévrier', at: V.sevrier, dist: '5,8 km', note: '4,4' },
    { id: 'chevrerie', nom: 'Aire naturelle de la Chèvrerie', sorte: 'Camping · aire naturelle', ville: 'Talloires-Montmin', at: V.talloires, dist: '12,4 km', mika: true,
      dit: 'le plus calme du lac, au pied de la Tournette. pas de piscine, mais tu t\'en fiches' },
    { id: 'fontaines', nom: 'Camping Les Fontaines', sorte: 'Camping', ville: 'Saint-Jorioz', at: V.jorioz, dist: '8,9 km' },
    { id: 'port', nom: 'Hôtel du Port', sorte: 'Hôtel', ville: 'Menthon-Saint-Bernard', at: V.menthon, dist: '8,1 km' },
    { id: 'lacbleu', nom: 'Camping du Lac Bleu', sorte: 'Camping', ville: 'Doussard', at: V.doussard, dist: '17,6 km' },
    { id: 'auberge', nom: 'Auberge de jeunesse', sorte: 'Auberge de jeunesse', ville: 'Annecy', at: [6.133, 45.888], dist: '1,4 km' },
  ];
  const VOYAGES = [
    { id: 'alpes', titre: 'Les Alpes en cinq jours', dates: 'sam. 3 – mer. 7 avril 2027', court: '3–7 avr.', km: '1 388 km', duree: '16 h 10 de route', mika: 4, jours: [
      { n: 1, quand: 'sam. 3 avril', titre: 'Lille → Dijon', km: '502 km', duree: '4 h 50', trace: ['lille', 'arras', 'cambrai', 'stquentin', 'laon', 'reims', 'chalons', 'troyes', 'chaumont', 'langres', 'dijon'], etapes: [
        { nom: 'Départ · rue Nationale, Lille', sorte: 'Ta position · 08:30', at: V.lille },
        { nom: 'Cathédrale Notre-Dame de Reims', sorte: 'À voir · 6 min de détour', at: V.reims, mika: true, dit: 'vingt minutes suffisent. le portail de l\'ange au sourire vaut le détour', troncon: '2 h 15 · 207 km' },
        { nom: 'Hôtel au centre de Dijon', sorte: 'Dormir · à réserver', at: V.dijon, troncon: '2 h 35 · 295 km' }] },
      { n: 2, quand: 'dim. 4 avril', titre: 'Dijon → Annecy', km: '268 km', duree: '2 h 50', trace: ['dijon', 'dole', 'bourg', 'nantua', 'bellegarde', 'stjulien', 'annecy'], etapes: [
        { nom: 'Monastère royal de Brou', sorte: 'À voir · Bourg-en-Bresse', at: V.bourg, mika: true, troncon: '1 h 40 · 152 km' },
        { nom: 'Camping de l\'Horizon, Sévrier', sorte: 'Dormir · deux nuits', at: V.sevrier, troncon: '1 h 10 · 116 km' }] },
      { n: 3, quand: 'lun. 5 avril', titre: 'Annecy ⇄ Chamonix', km: '196 km', duree: '2 h 50', trace: ['annecy', 'bonneville', 'cluses', 'sallanches', 'chamonix'], etapes: [
        { nom: 'Aiguille du Midi', sorte: 'À voir · réserver le créneau', at: V.chamonix, troncon: '1 h 25 · 98 km' }] },
      { n: 4, quand: 'mar. 6 avril', titre: 'Annecy → Moustiers', km: '371 km', duree: '4 h 40', trace: ['annecy', 'chambery', 'grenoble', 'lus', 'sisteron', 'arnoux', 'riez', 'moustiers'], etapes: [
        { nom: 'Col de la Croix-Haute', sorte: 'Pause · point de vue', at: V.lus, troncon: '2 h 30 · 184 km' },
        { nom: 'Point Sublime, gorges du Verdon', sorte: 'À voir · 15 min de détour', at: V.verdon, mika: true, dit: 'arrive avant 17 h, la lumière tombe vite', troncon: '2 h 05 · 172 km' },
        { nom: 'Chambre d\'hôtes à Moustiers', sorte: 'Dormir', at: V.moustiers, troncon: '25 min · 15 km' }] },
      { n: 5, quand: 'mer. 7 avril', titre: 'Moustiers → Nice', km: '151 km', duree: '2 h 30', trace: ['moustiers', 'castellane', 'grasse', 'nice'], etapes: [
        { nom: 'Lac de Sainte-Croix', sorte: 'Nature · baignade', at: V.stecroix, mika: true, troncon: '15 min · 9 km' },
        { nom: 'Arrivée · Nice', sorte: 'Fin du voyage', at: V.nice, troncon: '2 h 15 · 142 km' }] },
    ] },
    { id: 'somme', titre: 'Week-end en baie de Somme', dates: 'sam. 21 – dim. 22 novembre', court: '21–22 nov.', km: '312 km', duree: '3 h 40 de route', mika: 0, jours: [
      { n: 1, trace: [V.lille, [2.64, 50.53], [2.33, 50.38], [1.83, 50.105], [1.63, 50.183]], etapes: [{ at: V.lille }, { at: [1.63, 50.183] }] },
      { n: 2, trace: [[1.63, 50.183], [1.61, 50.215], [1.83, 50.105], [2.33, 50.38], V.lille], etapes: [{ at: [1.61, 50.215] }] }] },
    { id: 'bretagne', titre: 'La Bretagne, cet été', dates: 'du 2 au 9 août 2026 · passé', court: '2–9 août', km: '1 742 km', duree: '21 h de route', mika: 0, passe: true, jours: [] },
  ];
  const ITI = ['lille', 'arras', 'cambrai', 'stquentin', 'laon', 'reims', 'chalons', 'troyes', 'chaumont', 'langres', 'dijon', 'dole', 'bourg', 'nantua', 'bellegarde', 'stjulien', 'annecy'];

  // ── Le dessin ─────────────────────────────────────────────────────────
  function courbe(pts) {
    const p = pts.map((k) => xy(pt(k)));
    if (p.length < 2) return '';
    let d = `M${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
    for (let i = 0; i < p.length - 1; i++) {
      const p0 = p[i - 1] || p[i], p1 = p[i], p2 = p[i + 1], p3 = p[i + 2] || p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
    }
    return d;
  }
  const contour = (pts) => pts.map((q, i) => { const [x, y] = xy(q); return `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`; }).join(' ') + 'Z';
  /** La fenêtre qui tient ces points, avec une marge, au rapport largeur/hauteur demandé. */
  function boite(pts, marge, ratio) {
    const p = pts.map((k) => xy(pt(k)));
    let x0 = Math.min(...p.map((q) => q[0])), x1 = Math.max(...p.map((q) => q[0])), y0 = Math.min(...p.map((q) => q[1])), y1 = Math.max(...p.map((q) => q[1]));
    const m = Math.max(x1 - x0, y1 - y0) * (marge || 0.1) + 0.5;
    x0 -= m; x1 += m; y0 -= m; y1 += m;
    if (ratio) {
      const w = x1 - x0, hh = y1 - y0;
      if (w / hh < ratio) { const nw = hh * ratio; x0 -= (nw - w) / 2; x1 = x0 + nw; } else { const nh = w / ratio; y0 -= (nh - hh) / 2; y1 = y0 + nh; }
    }
    return [x0, y0, x1 - x0, y1 - y0];
  }
  /** Une carte : o = { vue, largeur (en dp à l'écran), slice, traces, pins, ici, halo, decor, villes, routes } */
  function carte(o) {
    const vb = o.vue || [0, 0, VW, VH];
    const k = vb[2] / (o.largeur || 384);
    const routes = (o.routes || []).map((r) => `<path class="cm-road" d="${courbe(r)}" vector-effect="non-scaling-stroke"/><path class="cm-road-in" d="${courbe(r)}" vector-effect="non-scaling-stroke"/>`).join('');
    const traces = (o.traces || []).map((t) => `<path class="cm-route${t.faint ? ' faint' : ''}" d="${courbe(t.pts)}" vector-effect="non-scaling-stroke"${t.mika ? ' style="stroke:var(--mika-fill)"' : ''}/>`).join('');
    const decor = (o.decor || []).map((d) => `<path class="${d.cls}" d="${contour(d.pts)}"/>${d.nom ? `<text x="${xy(d.lab)[0]}" y="${xy(d.lab)[1]}" font-size="${11 * k}" stroke-width="${3 * k}" style="font-style:italic">${h(d.nom)}</text>` : ''}`).join('');
    const villes = (o.villes || []).map((n) => { const [x, y] = xy(pt(n.k)); return `<g class="cm-ville"><circle cx="${x}" cy="${y}" r="${2.6 * k}"/><text x="${x + 5 * k}" y="${y - 4 * k}" font-size="${12 * k}" stroke-width="${3 * k}">${h(n.nom)}</text></g>`; }).join('');
    const pins = (o.pins || []).map((p) => {
      const [x, y] = xy(pt(p.at)), r = (p.sel ? 12 : p.n != null ? 10 : 7) * k;
      return `<g class="cm-pin${p.mika ? ' mika' : ''}"${p.go ? ` data-go="${p.go}" style="cursor:pointer"` : ''}><circle cx="${x}" cy="${y}" r="${r}" stroke-width="${2 * k}"/>${p.n != null ? `<text x="${x}" y="${y + 3.8 * k}" font-size="${10.5 * k}">${h(p.n)}</text>` : ''}
        ${p.label ? `<text class="lab" x="${x + r + 4 * k}" y="${y + 4 * k}" font-size="${12.5 * k}" stroke-width="${3.5 * k}">${h(p.label)}</text>` : ''}</g>`;
    }).join('');
    const ici = o.ici ? (() => { const [x, y] = xy(o.ici); return `${o.halo ? `<circle class="cm-halo" cx="${x}" cy="${y}" r="${o.halo}" stroke-width="${1.2 * k}"/>` : `<circle class="cm-halo" cx="${x}" cy="${y}" r="${13 * k}" stroke-width="0"/>`}<circle class="cm-ici" cx="${x}" cy="${y}" r="${6 * k}" stroke-width="${2.4 * k}"/>`; })() : '';
    return `<svg class="cmap" viewBox="${vb.map((x) => x.toFixed(2)).join(' ')}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${h(o.titre || 'Carte')}">
      <rect class="cm-sea" x="-2000" y="-2000" width="${VW + 4000}" height="${VH + 4000}"/><path class="cm-land" d="${F.terre}"/><path class="cm-lake" d="${F.lacs}"/>
      ${decor}<path class="cm-border" d="${F.frontieres}" vector-effect="non-scaling-stroke"/>${routes}${traces}${villes}${ici}${pins}</svg>`;
  }
  function carteVoyage(v, o) {
    const tous = v.jours.flatMap((j) => j.trace);
    return carte(Object.assign({ vue: boite(tous, 0.12, o.ratio), titre: v.titre, traces: v.jours.map((j) => ({ pts: j.trace })),
      pins: v.jours.flatMap((j) => j.etapes).map((e, i) => ({ at: e.at, mika: e.mika, n: o.numeros ? i + 1 : null })) }, o));
  }
  A.carteMini = (id) => carteVoyage(VOYAGES.find((x) => x.id === id) || VOYAGES[0], { largeur: 260, ratio: 260 / 150, slice: true });
  /** La position du téléphone : son point, le cercle de sa précision, sur le plan (aucune rue inventée). */
  A.cartePosition = (at, largeur, hauteur) => carte({ vue: boite([[at[0] - 0.02, at[1] - 0.012], [at[0] + 0.02, at[1] + 0.012]], 0.05, largeur / hauteur), largeur, slice: true,
    ici: at, halo: 0.12, villes: [{ k: 'lille', nom: 'Lille' }], titre: 'Sa dernière position' });

  // ── Les écrans ────────────────────────────────────────────────────────
  const ONGLETS = [['#carte', 'Explorer'], ['#carte/evenements', 'Événements'], ['#carte/itineraire', 'Itinéraire'], ['#carte/voyages', 'Voyages']];
  const haut = (cur) => `${A.top({ racine: true, title: 'Carte', small: true })}${A.tabs(ONGLETS, cur)}`;
  const attrib = (bottom) => `<div class="cm-attrib" style="bottom:${bottom}px">© OpenStreetMap · fond simplifié pour la maquette</div>`;

  function vueExplorer(selId) {
    const sel = LIEUX.find((l) => l.id === selId);
    const vue = boite([[6.03, 45.94], [6.33, 45.64]], 0.02, 384 / 600);
    const map = carte({ vue, largeur: 384, slice: true, titre: 'Autour du lac d\'Annecy',
      decor: [{ cls: 'cm-park', pts: SEMNOZ, nom: 'Semnoz', lab: [6.088, 45.822] }, { cls: 'cm-park', pts: TOURNETTE, nom: 'Tournette', lab: [6.245, 45.826] }, { cls: 'cm-lake', pts: LAC, nom: 'lac d\'Annecy', lab: [6.150, 45.873] }],
      routes: ROUTES_LAC, villes: [{ k: 'annecy', nom: 'Annecy' }],
      pins: LIEUX.map((l) => ({ at: l.at, mika: l.mika, sel: l.id === selId, label: l.id === selId ? l.nom : '', go: `#carte/lieu/${l.id}` })) });
    const liste = `<div class="row" style="padding:2px 16px 6px"><span class="grow"><b style="font-weight:500">6 campings</b> <span class="muted">· dans cette zone</span></span><button class="btn text sm" type="button" data-snack="Trié par distance">${ico('sort', 'xs')}Distance</button></div>
      ${LIEUX.map((l) => `<button class="li" type="button" data-go="#carte/lieu/${l.id}"><span class="lead box"${l.mika ? ' style="background:var(--mc);color:var(--on-mc)"' : ''}>${ico('pin')}</span><span class="txt"><b>${h(l.nom)}</b><small>${h(l.sorte)} · ${h(l.ville)}${l.mika ? ' · <span class="mk-txt">trouvé par Mika</span>' : ''}</small></span><span class="trail">${h(l.dist)}</span></button>`).join('')}`;
    const fiche = sel ? `<div class="place-card"><div class="row"><span class="grow"><h2>${h(sel.nom)}</h2><span class="muted">${h(sel.sorte)} · ${h(sel.ville)} · ${h(sel.dist)}</span></span>${A.act('x', 'Fermer', 'data-go="#carte"')}</div>
        ${sel.note ? `<div class="row" style="margin-top:6px;gap:6px"><span class="tag">${ico('star', 'xs')}${h(sel.note)} · 312 avis Tripadvisor</span><span class="grow"></span><button class="btn text sm" type="button" data-go="#carte/fiche/atelier" data-snack="Maquette : la fiche complète est montrée sur un restaurant">Tout voir${ico('chev-right', 'xs')}</button></div>` : ''}
        ${sel.dit ? `<div class="mika-said">${ico('sparkle')}<span>${h(sel.dit)}</span></div>` : ''}
        <div class="btns three"><button class="btn filled" type="button" data-go="#carte/itineraire">${ico('route')}Itinéraire</button><button class="btn tonal" type="button" data-sheet="ajouter-voyage">${ico('plus')}Au voyage</button>
          <button class="btn mk outlined" type="button" data-go="#chat" data-snack="Le chat s'ouvre avec ce lieu" title="En parler à Mika">${ico('chat')}En parler</button></div></div>` : '';
    return {
      nav: 'carte', racine: true,
      html: `${haut('#carte')}
        <div class="mapwrap">${map}
          <div class="map-search"><label class="field">${ico('search', 'sm')}<input value="camping" aria-label="Chercher un lieu ou une adresse">${A.act('locate', 'Autour de moi', 'data-snack="Autour de ta dernière position"')}</label>
            ${A.chips([{ l: 'Dormir', on: true, radio: 'c' }, { l: 'Manger', radio: 'c' }, { l: 'À voir', radio: 'c' }, { l: 'Nature', radio: 'c' }, { l: 'En route', radio: 'c' }, { l: 'Courses', radio: 'c' }])}</div>
          ${attrib(sel ? 276 : 262)}
          <div class="msheet" style="max-height:${sel ? 270 : 256}px"><div class="handle"></div><div class="ms-body">${sel ? fiche : liste}</div></div>
        </div>`,
      notes: {
        titre: sel ? 'Carte · un lieu' : 'Carte · Explorer',
        reprend: ['La carte prend l\'écran ; la recherche flotte dessus (un nom, une catégorie, une adresse), « Autour de moi » dans le champ.', 'Les résultats montent du bas ; ce qu\'elle a trouvé est rose.',
          'Un lieu : Itinéraire jusqu\'ici, Ajouter au voyage, En parler à Mika (le chat s\'ouvre avec une phrase préremplie).'],
        trancher: ['Les trois onglets (Explorer, Itinéraire, Voyages) sous la barre du haut, ou la carte sans barre du haut, onglets en puces sous la recherche (gagne 64 dp) ?', 'La feuille du bas : à mi-hauteur par défaut, ou repliée sur une ligne pour voir la carte ?'],
      },
    };
  }

  function vueItineraire() {
    const map = carte({ vue: boite([...ITI, [6.5, 44.6]], 0.06, 384 / 600), largeur: 384, slice: true, traces: [{ pts: ITI }], villes: [{ k: 'lille', nom: 'Lille' }, { k: 'dijon', nom: 'Dijon' }, { k: 'annecy', nom: 'Annecy' }],
      pins: [{ at: V.lille, n: 'A' }, { at: V.annecy, n: 'B' }] });
    return {
      nav: 'carte', racine: true,
      html: `${haut('#carte/itineraire')}
        <div class="mapwrap">${map}${attrib(372)}
          <div class="msheet" style="max-height:366px"><div class="handle"></div><div class="ms-body">
            <div class="iti-pts"><div class="iti-pt"><i class="dotp"></i><label class="tf"><input value="Ma position · rue Nationale, Lille"></label></div>
              <div class="iti-pt"><i class="dotp end"></i><label class="tf"><input value="Annecy (Haute-Savoie)"></label>${A.act('sort', 'Inverser', 'data-snack="Départ et arrivée inversés"')}</div>
              <button class="btn text sm" type="button" style="justify-self:start;margin-left:26px" data-snack="Une étape de plus">${ico('plus')}Ajouter une étape</button></div>
            <div style="padding:0 16px"><div class="seg" data-seg><button type="button" aria-pressed="true">${ico('car')}Voiture</button><button type="button" aria-pressed="false">${ico('bike')}Vélo</button><button type="button" aria-pressed="false">${ico('walk')}À pied</button></div></div>
            ${A.chips([{ l: 'Sans péage' }, { l: 'Sans autoroute' }, { l: 'Sans ferry' }])}
            <div class="iti-sum"><b>7 h 05</b><span>751 km · arrivée 21:25</span></div><p class="note" style="padding-top:0">par A1, A26, A5, A39, A40, A41 · sans péage : 9 h 40</p>
            <div class="btns" style="padding:0 16px 12px"><button class="btn filled" type="button" data-go="#carte/voyages" data-snack="Voyage créé">${ico('flag')}En faire un voyage</button><button class="btn outlined" type="button" data-snack="GPX enregistré">${ico('download')}GPX</button><button class="btn mk outlined" type="button" data-go="#chat" data-snack="Envoyé à Mika">${ico('send')}À Mika</button></div>
            <div data-foldroot><button class="list-head" type="button" data-fold=".consignes" style="width:100%">Les consignes · 9<svg class="ico sm"><use class="fold-ico" href="#i-chev-down"/></svg></button>
              <div class="consignes" hidden>${['Prendre la direction de l\'A1 vers Paris · 2,1 km', 'À Lille-Lesquin, prendre l\'A1 · 46 km', 'Continuer sur l\'A26 vers Reims · 197 km', 'Prendre l\'A5 vers Dijon, Lyon · 231 km'].map((c) => `<div class="li" style="min-height:44px">${ico('route', 'sm')}<span class="txt"><small>${h(c)}</small></span></div>`).join('')}</div></div>
          </div></div>
        </div>`,
      notes: { titre: 'Carte · Itinéraire', reprend: ['Ses points (un lieu, une adresse, « Ma position »), voiture, vélo ou à pied, ce qu\'on évite, la durée, la distance et l\'arrivée.', 'En faire un voyage, le GPX, l\'envoyer à Mika ; les consignes repliées.'], trancher: ['Les trois boutons sous le résumé : le bon ordre ?'] },
    };
  }

  function vueVoyages() {
    return {
      nav: 'carte', racine: true,
      html: `${haut('#carte/voyages')}
        <div class="body" style="padding-bottom:84px"><div class="cards">${VOYAGES.map((v) => `<button class="trip-card" type="button" data-go="#carte/voyage/${v.id}">${v.jours.length ? carteVoyage(v, { largeur: 352, ratio: 352 / 130, slice: true }) : `<div style="height:130px;display:grid;place-items:center;background:var(--s2)">${ico('map')}</div>`}
          <span class="tc-t"><b>${h(v.titre)}</b><small>${h(v.dates)} · ${h(v.km)} · ${h(v.duree)}</small>${v.mika ? `<span class="tag mk" style="margin-top:6px">${v.mika} arrêts de Mika</span>` : ''}${v.passe ? '<span class="tag" style="margin-top:6px">passé</span>' : ''}</span></button>`).join('')}</div></div>
        <button class="fab" type="button" data-dialog="nouveau-voyage">${ico('plus')}Nouveau voyage</button>`,
      notes: { titre: 'Carte · Voyages', reprend: ['Tes voyages en cartes (leur miniature) ; « Nouveau voyage » en bouton flottant.', 'Ceux préparés avec Mika disent combien d\'arrêts elle a ajoutés.'], trancher: [] },
    };
  }

  function vueVoyage(id) {
    const v = VOYAGES.find((x) => x.id === id) || VOYAGES[0];
    let n = 0;
    const jours = v.jours.map((j) => `<div class="day-h"><span class="dn">${j.n}</span><span class="grow"><b>${h(j.titre || 'Jour ' + j.n)}</b><small>${h(j.quand || '')} · ${h(j.duree || '')} · ${h(j.km || '')}</small></span></div>
      ${j.etapes.map((e) => { n++; return `${e.troncon ? `<div class="leg">${h(e.troncon)}</div>` : ''}<div class="stop${e.mika ? ' mika' : ''}"><span class="grip">${ico('grip', 'sm')}</span><span class="sn">${n}</span><span class="txt"><b>${h(e.nom || '')}</b><small>${h(e.sorte || '')}${e.mika ? ' · <span class="mk-txt">ajouté par Mika</span>' : ''}</small>${e.dit ? `<span class="dit">« ${h(e.dit)} »</span>` : ''}</span>${A.act('pen', 'Noter', 'data-snack="La note s\'écrit en place"')}${A.act('x', 'Retirer', 'data-snack="Arrêt retiré"')}</div>`; }).join('')}
      <button class="btn text sm" type="button" style="margin:2px 0 6px 56px" data-sheet="ajouter-arret">${ico('plus')}Ajouter un arrêt</button>`).join('');
    return {
      nav: 'carte', back: '#carte/voyages',
      html: `${A.top({ title: h(v.titre), sub: `${h(v.court)} · en voiture · ${h(v.km)}`, small: true, back: true, actions: [A.act('sparkle', 'Demander à Mika', 'data-go="#chat" data-snack="Le chat s\'ouvre avec ce voyage"', 'mk'), A.act('more', 'Plus', 'data-menu="voyage"')] })}
        <div class="mapwrap" style="flex:none;height:230px">${carteVoyage(v, { largeur: 384, ratio: 384 / 230, slice: true, numeros: true })}${attrib(6)}</div>
        <div class="row" style="padding:8px 12px;border-bottom:1px solid var(--line);gap:6px"><span class="tag">${h(v.duree)}</span><span class="tag mk">${v.mika} arrêts de Mika</span><span class="grow"></span><button class="btn tonal sm" type="button" data-sheet="sur-la-route">${ico('route')}Sur la route</button></div>
        <div class="body">${jours}</div>`,
      notes: { titre: 'Carte · un voyage', reprend: ['La carte en haut, l\'éditeur jour par jour dessous : glisser la poignée, noter (le crayon), retirer, ajouter un arrêt.', 'Ses arrêts en rose, avec ce qu\'elle en a dit.', '✦ en haut : « Demander à Mika » ; ⋮ : optimiser l\'ordre, le GPX, le voyage (titre, dates, ce qu\'on évite), le supprimer.'],
        trancher: ['« Sur la route » en bouton sous la carte, ou dans le ⋮ ?', 'Noter et retirer en icônes sur chaque arrêt (comme ici), ou dans un menu par arrêt pour alléger ?'] },
    };
  }

  // Les écrans des avis, des infos pratiques et des événements (ecrans/carte-avis.js) dessinent avec les mêmes outils.
  A.carteKit = { V, LAC, SEMNOZ, TOURNETTE, ROUTES_LAC, LIEUX, VOYAGES, carte, boite, haut, attrib };
  A.carteVues = {};
  A.ecran('carte', (args) => {
    if (A.carteVues[args[0]]) return A.carteVues[args[0]](args[1]);
    if (args[0] === 'lieu') return vueExplorer(args[1]);
    if (args[0] === 'itineraire') return vueItineraire();
    if (args[0] === 'voyages') return vueVoyages();
    if (args[0] === 'voyage') return vueVoyage(args[1]);
    return vueExplorer(null);
  });
  A.menus.voyage = () => [{ ico: 'sort', l: 'Optimiser l\'ordre', snack: 'Ordre optimisé : 42 min de moins' }, { ico: 'download', l: 'GPX du voyage', snack: 'GPX enregistré' }, { ico: 'pen', l: 'Le voyage…', dialog: 'nouveau-voyage' }, { ico: 'route', l: 'Sur la route', sheet: 'sur-la-route' }, '-', { ico: 'trash', l: 'Supprimer le voyage', cls: 'danger', snack: 'Maquette : rien n\'est supprimé' }];
  A.sheets['sur-la-route'] = () => A.sheet('Sur la route', [['Lac de Paladru', 'Nature · à 9 km · jour 4'], ['Château de Grignan', 'À voir · détour de 50 min · jour 4'], ['Belvédère de la Dent du Chat', 'Point de vue · à 6 km · jour 4'], ['Aire du Haut-Bugey', 'Recharge et restaurant · sur la route · jour 2']]
    .map(([n, s]) => `<div class="li"><span class="lead box">${ico('pin')}</span><span class="txt"><b>${h(n)}</b><small>${h(s)}</small></span><button class="btn tonal sm" type="button" data-close data-snack="Ajouté au bon jour">Ajouter</button></div>`).join(''));
  A.sheets['ajouter-arret'] = () => A.sheet('Ajouter un arrêt', `<div style="padding:0 24px 12px"><label class="field" style="background:var(--s2)">${ico('search', 'sm')}<input placeholder="Un lieu, une adresse"></label></div>
    ${LIEUX.slice(0, 3).map((l) => `<button class="li" type="button" data-close data-snack="Arrêt ajouté"><span class="lead box">${ico('pin')}</span><span class="txt"><b>${h(l.nom)}</b><small>${h(l.ville)}</small></span></button>`).join('')}`);
  A.sheets['ajouter-voyage'] = () => A.sheet('Ajouter au voyage', VOYAGES.filter((v) => !v.passe).map((v) => `<button class="li" type="button" data-close data-snack="Ajouté à « ${h(v.titre)} »"><span class="lead box">${ico('flag')}</span><span class="txt"><b>${h(v.titre)}</b><small>${h(v.court)}</small></span></button>`).join(''));
  A.dialogs['nouveau-voyage'] = () => A.dialog('Nouveau voyage', `<label class="tf" style="margin-bottom:14px"><span>Titre</span><input value=""></label><label class="tf" style="margin-bottom:14px"><span>Dates</span><input value="sam. 21 – dim. 22 nov."></label>
    <div class="seg" data-seg style="margin-bottom:10px"><button type="button" aria-pressed="true">${ico('car')}Voiture</button><button type="button" aria-pressed="false">${ico('bike')}Vélo</button><button type="button" aria-pressed="false">${ico('walk')}À pied</button></div>
    <div class="row wrap"><span class="chip" data-chip>Sans péage</span><span class="chip" data-chip>Sans autoroute</span></div>`,
  '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="Voyage créé">Créer</button>');
  A.index('Carte', [['Explorer', '#carte'], ['Un lieu', '#carte/lieu/chevrerie'], ['Itinéraire', '#carte/itineraire'], ['Voyages', '#carte/voyages'], ['Un voyage', '#carte/voyage/alpes']]);
})();
