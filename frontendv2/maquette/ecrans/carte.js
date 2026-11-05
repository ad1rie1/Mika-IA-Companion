/* Carte : chercher un lieu ou une adresse, calculer un itinéraire, préparer un voyage à deux. Mika s'en sert dans
   la conversation, et sa carte arrive dans le chat. Le fond est la France tirée de nos propres tuiles, simplifiée
   (ecrans/carte-fond.js) : le vrai écran montre la carte vectorielle que le serveur sert (ADR 0193). Rien ne part du
   navigateur ailleurs que vers ce serveur. Rose : ce que Mika a cherché, proposé ou ajouté. */
(function () {
  const { h, ico } = M;
  const F = window.MIKA_FOND;
  const [VW, VH] = F.viewBox;
  const mx = (lon) => (lon + 180) / 360;
  const my = (lat) => { const r = lat * Math.PI / 180; return (1 - Math.asinh(Math.tan(r)) / Math.PI) / 2; };
  const X0 = mx(F.proj.W), X1 = mx(F.proj.E), Y0 = my(F.proj.N), Y1 = my(F.proj.S);
  const xy = ([lon, lat]) => [(mx(lon) - X0) / (X1 - X0) * VW, (my(lat) - Y0) / (Y1 - Y0) * VH];

  // ── Les données (fictives) ──────────────────────────────────────────
  // Villes et points de passage, en degrés (longitude, latitude) : les tracés suivent à peu près les autoroutes.
  const V = {
    lille: [3.063, 50.637], arras: [2.78, 50.29], cambrai: [3.23, 50.17], stquentin: [3.29, 49.85], laon: [3.62, 49.56],
    reims: [4.032, 49.258], chalons: [4.36, 48.96], troyes: [4.074, 48.297], chaumont: [5.14, 48.11], langres: [5.33, 47.86],
    dijon: [5.041, 47.322], dole: [5.49, 47.09], bourg: [5.23, 46.21], nantua: [5.61, 46.15], bellegarde: [5.83, 46.11],
    stjulien: [6.08, 46.14], annecy: [6.129, 45.899], bonneville: [6.40, 46.08], cluses: [6.58, 46.06], sallanches: [6.63, 45.94],
    chamonix: [6.869, 45.924], chambery: [5.92, 45.57], grenoble: [5.724, 45.188], lus: [5.70, 44.65], sisteron: [5.944, 44.196],
    arnoux: [6.0, 44.09], riez: [6.09, 43.82], moustiers: [6.221, 43.846], castellane: [6.51, 43.85], grasse: [6.92, 43.66],
    nice: [7.262, 43.710], bethune: [2.64, 50.53], stpol: [2.33, 50.38], abbeville: [1.83, 50.105], stvalery: [1.63, 50.183],
    crotoy: [1.61, 50.215], sevrier: [6.141, 45.866], jorioz: [6.166, 45.832], duingt: [6.200, 45.826], doussard: [6.222, 45.785],
    talloires: [6.215, 45.840], menthon: [6.196, 45.862], veyrier: [6.170, 45.887],
  };
  const pt = (k) => (typeof k === 'string' ? V[k] : k);

  const CATS = [
    ['manger', 'Manger', 'restaurant, café, bar…'], ['dormir', 'Dormir', 'hôtel, camping, gîte…'],
    ['voir', 'À voir', 'musée, château, point de vue…'], ['nature', 'Nature', 'sommet, lac, plage, cascade…'],
    ['route', 'En route', 'carburant, recharge, aire, toilettes…'], ['courses', 'Courses', 'supermarché, boulangerie, marché…'],
    ['sante', 'Santé', 'pharmacie, hôpital, médecin…'], ['sortir', 'Sortir', 'cinéma, théâtre, piscine…'],
  ];
  const LIEUX = [
    { id: 'horizon', nom: 'Camping de l\'Horizon', sorte: 'Camping', ville: 'Sévrier', at: V.sevrier, dist: '5,8 km' },
    { id: 'chevrerie', nom: 'Aire naturelle de la Chèvrerie', sorte: 'Camping · aire naturelle', ville: 'Talloires-Montmin', at: V.talloires, dist: '12,4 km', mika: true },
    { id: 'fontaines', nom: 'Camping Les Fontaines', sorte: 'Camping', ville: 'Saint-Jorioz', at: V.jorioz, dist: '8,9 km' },
    { id: 'port', nom: 'Hôtel du Port', sorte: 'Hôtel', ville: 'Menthon-Saint-Bernard', at: V.menthon, dist: '8,1 km' },
    { id: 'lacbleu', nom: 'Camping du Lac Bleu', sorte: 'Camping', ville: 'Doussard', at: V.doussard, dist: '17,6 km' },
    { id: 'auberge', nom: 'Auberge de jeunesse', sorte: 'Auberge de jeunesse', ville: 'Annecy', at: [6.133, 45.888], dist: '1,4 km' },
  ];
  // Le lac d'Annecy et deux massifs, dessinés pour la vue rapprochée (le fond simplifié n'a pas de si petits lacs).
  const LAC = [[6.128, 45.902], [6.150, 45.899], [6.167, 45.887], [6.180, 45.872], [6.195, 45.858], [6.208, 45.846], [6.212, 45.833],
    [6.206, 45.826], [6.212, 45.815], [6.221, 45.800], [6.218, 45.791], [6.209, 45.794], [6.199, 45.808], [6.190, 45.821], [6.178, 45.828],
    [6.165, 45.836], [6.152, 45.850], [6.143, 45.864], [6.135, 45.878], [6.127, 45.891]];
  const SEMNOZ = [[6.085, 45.855], [6.105, 45.835], [6.120, 45.810], [6.130, 45.790], [6.115, 45.785], [6.095, 45.805], [6.078, 45.835]];
  const TOURNETTE = [[6.245, 45.850], [6.262, 45.840], [6.275, 45.820], [6.268, 45.805], [6.250, 45.812], [6.240, 45.832]];
  // Quelques routes autour du lac, pour la vue rapprochée (dessinées pour la maquette).
  const ROUTES_LAC = [['annecy', 'sevrier', 'jorioz', 'duingt', 'doussard'], ['annecy', 'veyrier', 'menthon', 'talloires', 'doussard'], ['annecy', [6.12, 45.95], [6.10, 46.03]]];

  const VOYAGES = [
    { id: 'alpes', titre: 'Les Alpes en cinq jours', dates: 'du sam. 3 au mer. 7 avril 2027', mode: 'voiture', avecMika: true,
      km: '1 388 km', duree: '16 h 10 de route', options: 'péages acceptés',
      jours: [
        { n: 1, quand: 'sam. 3 avril', titre: 'Lille → Dijon', km: '502 km', duree: '4 h 50', par: 'A1, A26, A5, A31',
          trace: ['lille', 'arras', 'cambrai', 'stquentin', 'laon', 'reims', 'chalons', 'troyes', 'chaumont', 'langres', 'dijon'],
          etapes: [
            { nom: 'Départ · rue Nationale, Lille', sorte: 'Ta position', at: V.lille, heure: '08:30' },
            { nom: 'Cathédrale Notre-Dame de Reims', sorte: 'À voir · 6 min de détour', at: V.reims, heure: '10:45', mika: true,
              dit: 'vingt minutes suffisent. le portail de l\'ange au sourire vaut le détour', troncon: '2 h 15 · 207 km' },
            { nom: 'Hôtel au centre de Dijon', sorte: 'Dormir · à réserver', at: V.dijon, heure: '14:30', troncon: '2 h 35 · 295 km' },
          ] },
        { n: 2, quand: 'dim. 4 avril', titre: 'Dijon → Annecy', km: '268 km', duree: '2 h 50', par: 'A39, A40, A41',
          trace: ['dijon', 'dole', 'bourg', 'nantua', 'bellegarde', 'stjulien', 'annecy'],
          etapes: [
            { nom: 'Monastère royal de Brou', sorte: 'À voir · Bourg-en-Bresse, sur la route', at: V.bourg, heure: '11:00', mika: true, troncon: '1 h 40 · 152 km' },
            { nom: 'Camping de l\'Horizon, Sévrier', sorte: 'Dormir · deux nuits', at: V.sevrier, heure: '15:00', troncon: '1 h 10 · 116 km' },
          ] },
        { n: 3, quand: 'lun. 5 avril', titre: 'Annecy ⇄ Chamonix', km: '196 km', duree: '2 h 50', par: 'A41, A40, N205',
          trace: ['annecy', 'bonneville', 'cluses', 'sallanches', 'chamonix'],
          etapes: [{ nom: 'Aiguille du Midi', sorte: 'À voir · téléphérique, réserver le créneau', at: V.chamonix, heure: '09:30', troncon: '1 h 25 · 98 km' }] },
        { n: 4, quand: 'mar. 6 avril', titre: 'Annecy → Moustiers-Sainte-Marie', km: '371 km', duree: '4 h 40', par: 'A41, A480, D1075, A51',
          trace: ['annecy', 'chambery', 'grenoble', 'lus', 'sisteron', 'arnoux', 'riez', 'moustiers'],
          etapes: [
            { nom: 'Col de la Croix-Haute', sorte: 'Pause · point de vue', at: V.lus, heure: '11:15', troncon: '2 h 30 · 184 km' },
            { nom: 'Point Sublime, gorges du Verdon', sorte: 'À voir · 15 min de détour', at: [6.398, 43.796], heure: '16:30', mika: true,
              dit: 'c\'est là que les gorges sont les plus belles. arrive avant 17 h, la lumière tombe vite', troncon: '2 h 05 · 172 km' },
            { nom: 'Chambre d\'hôtes à Moustiers', sorte: 'Dormir', at: V.moustiers, heure: '18:00', troncon: '25 min · 15 km' },
          ] },
        { n: 5, quand: 'mer. 7 avril', titre: 'Moustiers → Nice', km: '151 km', duree: '2 h 30', par: 'D952, N85',
          trace: ['moustiers', 'castellane', 'grasse', 'nice'],
          etapes: [
            { nom: 'Lac de Sainte-Croix', sorte: 'Nature · baignade', at: [6.17, 43.78], heure: '09:30', mika: true, troncon: '15 min · 9 km' },
            { nom: 'Arrivée · Nice', sorte: 'Fin du voyage', at: V.nice, heure: '13:00', troncon: '2 h 15 · 142 km' },
          ] },
      ] },
    { id: 'somme', titre: 'Week-end en baie de Somme', dates: 'sam. 21 et dim. 22 novembre', mode: 'voiture', km: '312 km', duree: '3 h 40 de route',
      options: 'sans autoroute',
      jours: [
        { n: 1, quand: 'sam. 21 nov.', titre: 'Lille → Saint-Valery-sur-Somme', km: '156 km', duree: '1 h 50', par: 'A25, D939, D928',
          trace: ['lille', 'bethune', 'stpol', 'abbeville', 'stvalery'],
          etapes: [{ nom: 'Départ · Lille', sorte: 'Ta position', at: V.lille, heure: '09:00' }, { nom: 'Saint-Valery-sur-Somme', sorte: 'Dormir', at: V.stvalery, heure: '11:00', troncon: '1 h 50 · 156 km' }] },
        { n: 2, quand: 'dim. 22 nov.', titre: 'Le Crotoy → Lille', km: '156 km', duree: '1 h 50', par: 'D940, A16, A25',
          trace: ['stvalery', 'crotoy', 'abbeville', 'stpol', 'bethune', 'lille'],
          etapes: [{ nom: 'Le Crotoy, les phoques à marée basse', sorte: 'Nature', at: V.crotoy, heure: '10:00' }, { nom: 'Retour · Lille', sorte: 'Fin du voyage', at: V.lille, heure: '17:00' }] },
      ] },
    { id: 'bretagne', titre: 'La Bretagne, cet été', dates: 'du 2 au 9 août 2026 · passé', mode: 'voiture', km: '1 742 km', duree: '21 h de route', passe: true,
      options: 'péages acceptés', jours: [] },
  ];
  const SUR_LA_ROUTE = [
    { nom: 'Lac de Paladru', sorte: 'Nature', pres: 'à 9 km de la route · jour 4', cat: 'nature' },
    { nom: 'Château de Grignan', sorte: 'À voir', pres: 'à 31 km · jour 4 (détour de 50 min)', cat: 'voir' },
    { nom: 'Belvédère de la Dent du Chat', sorte: 'Point de vue', pres: 'à 6 km · jour 4', cat: 'voir' },
    { nom: 'Aire du Haut-Bugey', sorte: 'En route · recharge et restaurant', pres: 'sur la route · jour 2', cat: 'route' },
  ];
  const ITI = { de: 'Ma position · rue Nationale, Lille', a: 'Annecy (Haute-Savoie)', km: '751 km', duree: '7 h 05', par: 'A1, A26, A5, A39, A40, A41',
    trace: ['lille', 'arras', 'cambrai', 'stquentin', 'laon', 'reims', 'chalons', 'troyes', 'chaumont', 'langres', 'dijon', 'dole', 'bourg', 'nantua', 'bellegarde', 'stjulien', 'annecy'],
    sansPeage: { km: '702 km', duree: '9 h 40' },
    consignes: [
      ['Prendre la direction de l\'A1 vers Paris', '2,1 km'], ['À l\'échangeur de Lille-Lesquin, prendre l\'A1', '46 km'],
      ['Continuer sur l\'A26 vers Reims', '197 km'], ['Prendre l\'A26 puis l\'A5 vers Dijon, Lyon', '231 km'],
      ['Sortir vers l\'A31 en direction de Dijon', '61 km'], ['Prendre l\'A39 vers Bourg-en-Bresse', '144 km'],
      ['Prendre l\'A40 vers Genève', '57 km'], ['Prendre l\'A41 vers Annecy', '35 km'], ['Arrivée à Annecy', ''],
    ] };

  const etat = { cat: 'dormir', q: 'camping', autour: 'zone', sel: 'chevrerie', mode: 'voiture', peages: true, autoroutes: true, retires: new Set() };

  // ── Le dessin ───────────────────────────────────────────────────────
  // Une courbe lisse par les points (Catmull-Rom vers des Bézier cubiques).
  function courbe(points) {
    const p = points.map((k) => xy(pt(k)));
    if (p.length < 2) return '';
    let d = `M${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
    for (let i = 0; i < p.length - 1; i++) {
      const a = p[i - 1] || p[i], b = p[i], c = p[i + 1], e = p[i + 2] || c;
      const c1 = [b[0] + (c[0] - a[0]) / 6, b[1] + (c[1] - a[1]) / 6], c2 = [c[0] - (e[0] - b[0]) / 6, c[1] - (e[1] - b[1]) / 6];
      d += ` C${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${c[0].toFixed(1)} ${c[1].toFixed(1)}`;
    }
    return d;
  }
  // La fenêtre qui montre ces points, à la forme du cadre (largeur / hauteur = ``aspect``) : tout se voit, rien
  // n'est rogné, et les traits gardent leur taille.
  function contour(points) {
    return points.map((k, i) => { const [x, y] = xy(pt(k)); return `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`; }).join(' ') + 'Z';
  }
  function boite(points, marge, aspect) {
    const p = points.map((k) => xy(pt(k)));
    const x0 = Math.min(...p.map((q) => q[0])), x1 = Math.max(...p.map((q) => q[0]));
    const y0 = Math.min(...p.map((q) => q[1])), y1 = Math.max(...p.map((q) => q[1]));
    const m = marge == null ? 0.18 : marge;
    let w = Math.max(x1 - x0, 4) * (1 + 2 * m), hh = Math.max(y1 - y0, 4) * (1 + 2 * m);
    const a = aspect || 1.32;
    if (w / hh < a) w = hh * a; else hh = w / a;
    // gardée dans le fond : au-delà, il n'y a plus de terre dessinée
    const cx = Math.min(Math.max((x0 + x1) / 2, w / 2), Math.max(w / 2, VW - w / 2));
    const cy = Math.min(Math.max((y0 + y1) / 2, hh / 2), Math.max(hh / 2, VH - hh / 2));
    return [cx - w / 2, cy - hh / 2, w, hh];
  }
  // La carte : le fond, des tracés, des épingles, des noms de villes. ``vue`` : la fenêtre, en unités du fond ;
  // les traits et les textes gardent leur taille à l'écran (``k``).
  function carte(o) {
    const vb = o.vue || [0, 0, VW, VH];
    const k = vb[2] / (o.largeur || (M.mobile() ? 420 : 760));
    const traces = (o.traces || []).map((t) => `<path class="cm-route${t.mika ? ' mika' : ''}${t.faible ? ' faible' : ''}${t.route ? ' road' : ''}" d="${courbe(t.pts)}" vector-effect="non-scaling-stroke"/>`).join('');
    const villes = (o.villes || []).map((n) => {
      const [x, y] = xy(V[n.k] || n.at);
      return `<g class="cm-ville"><circle cx="${x}" cy="${y}" r="${2.4 * k}"/><text x="${x + 5 * k}" y="${y - 4 * k}" font-size="${11 * k}" stroke-width="${3 * k}">${h(n.nom)}</text></g>`;
    }).join('');
    const pins = (o.pins || []).map((p) => {
      const [x, y] = xy(p.at), r = (p.sel ? 11 : 8.5) * k;
      return `<g class="cm-pin${p.mika ? ' mika' : ''}${p.sel ? ' sel' : ''}${p.data ? ' btn' : ''}"${p.data ? ` data-pin="${h(p.data)}"` : ''}>
        <circle cx="${x}" cy="${y}" r="${r}" stroke-width="${2 * k}"/>${p.n != null ? `<text x="${x}" y="${y + 3.6 * k}" font-size="${10 * k}">${h(p.n)}</text>` : ''}
        ${p.label ? `<text class="lab" x="${x + r + 4 * k}" y="${y + 4 * k}" font-size="${11.5 * k}" stroke-width="${3 * k}">${h(p.label)}</text>` : ''}</g>`;
    }).join('');
    const ici = o.ici ? (() => { const [x, y] = xy(o.ici); return `<circle class="cm-ici-halo" cx="${x}" cy="${y}" r="${13 * k}"/><circle class="cm-ici" cx="${x}" cy="${y}" r="${5.5 * k}" stroke-width="${2.2 * k}"/>`; })() : '';
    const decor = (o.decor || []).map((d) => `<path class="${d.cls}" d="${contour(d.pts)}"/>${d.nom ? `<text class="${d.cls}-lab" x="${xy(d.lab)[0]}" y="${xy(d.lab)[1]}" font-size="${11 * k}">${h(d.nom)}</text>` : ''}`).join('');
    return `<svg class="cmap${o.cls ? ' ' + o.cls : ''}" viewBox="${vb.map((v) => v.toFixed(1)).join(' ')}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${h(o.titre || 'Carte')}">
      <rect class="cm-sea" x="-2000" y="-2000" width="${VW + 4000}" height="${VH + 4000}"/>
      <path class="cm-land" d="${F.terre}"/><path class="cm-lake" d="${F.lacs}"/>${decor}
      <path class="cm-border" d="${F.frontieres}" vector-effect="non-scaling-stroke"/>
      ${traces}${villes}${ici}${pins}</svg>`;
  }
  M.carteMini = (id) => {
    const v = VOYAGES.find((x) => x.id === id) || VOYAGES[0];
    const tous = v.jours.flatMap((j) => j.trace);
    return carte({ vue: boite(tous, 0.1, 2.1), largeur: 340, cls: 'mini', titre: v.titre,
      traces: v.jours.map((j) => ({ pts: j.trace })),
      pins: v.jours.flatMap((j) => j.etapes).filter((e) => !etat.retires.has(e.nom)).map((e) => ({ at: e.at, mika: e.mika })) });
  };
  const attribution = `<div class="cm-attrib">© OpenStreetMap · <span title="Le fond de la maquette est simplifié ; le vrai écran montre la carte vectorielle servie par le serveur.">fond simplifié pour la maquette</span></div>`;
  const zoom = `<div class="cm-zoom"><button type="button" title="Zoomer" data-zoom>${ico('plus', 'sm')}</button><button type="button" title="Dézoomer" data-zoom>${ico('minus', 'sm')}</button></div>`;

  // ── Explorer ────────────────────────────────────────────────────────
  function vueExplorer() {
    const sel = LIEUX.find((l) => l.id === etat.sel);
    const vue = boite([[6.06, 45.93], [6.30, 45.76]], 0.04);
    const map = carte({ vue, titre: 'Autour du lac d\'Annecy', ici: null,
      decor: [{ cls: 'cm-park', pts: SEMNOZ, nom: 'Semnoz', lab: [6.090, 45.822] }, { cls: 'cm-park', pts: TOURNETTE, nom: 'Tournette', lab: [6.247, 45.826] },
        { cls: 'cm-lake', pts: LAC, nom: 'lac d\'Annecy', lab: [6.150, 45.872] }],
      traces: ROUTES_LAC.map((r) => ({ pts: r, route: true })),
      villes: [{ k: 'annecy', nom: 'Annecy' }, { k: 'doussard', nom: 'Doussard' }],
      pins: LIEUX.map((l) => ({ at: l.at, mika: l.mika, sel: l.id === etat.sel, data: l.id, label: l.id === etat.sel ? l.nom : '' })) });
    const adresse = /\d/.test(etat.q);
    return `<div class="split carte-split">
      <aside class="pane carte-side">
        <div class="cs-search">
          <label class="search-field">${ico('search', 'sm')}<input type="search" data-q value="${h(etat.q)}" placeholder="Un lieu, une adresse, un restaurant…" aria-label="Chercher un lieu ou une adresse"></label>
          <div class="cs-cats" role="group" aria-label="Catégories">${CATS.map(([id, nom, sous]) => `<button type="button" class="cat${etat.cat === id ? ' on' : ''}" data-cat="${id}" title="${h(sous)}">${h(nom)}</button>`).join('')}</div>
          <div class="seg" role="group" aria-label="Où chercher">
            <button type="button" aria-pressed="${etat.autour === 'moi'}" data-autour="moi">${ico('pin', 'sm')}Autour de moi</button>
            <button type="button" aria-pressed="${etat.autour === 'zone'}" data-autour="zone">${ico('map', 'sm')}Dans cette zone</button></div>
        </div>
        <div class="pane-scroll">
          ${adresse ? `<div class="group-label">Adresses <span class="muted">· Géoplateforme (IGN), seul le texte part</span></div>
            <button class="li place" type="button" data-toast="adresse">${ico('pin', 'sm')}<span class="li-main"><span class="li-title">12 Rue Royale, 74000 Annecy</span><span class="li-snip">adresse</span></span></button>` : ''}
          <div class="group-label">Dormir · ${h(etat.q || 'tout')} <span class="cnt">${LIEUX.length}</span><span class="grow"></span><span class="muted">index local, rien ne sort</span></div>
          ${LIEUX.map((l) => `<button class="li place${l.id === etat.sel ? ' on' : ''}${l.mika ? ' by-mika' : ''}" type="button" data-lieu="${l.id}">
            <span class="pl-dot${l.mika ? ' mika' : ''}">${ico('moon', 'xs')}</span>
            <span class="li-main"><span class="li-top"><span class="li-title">${h(l.nom)}</span><span class="pl-dist">${h(l.dist)}</span></span>
            <span class="li-snip">${h(l.sorte)} · ${h(l.ville)}${l.mika ? ' · <b class="mika-txt">Mika te l\'a proposé</b>' : ''}</span></span></button>`).join('')}
        </div>
        ${sel ? `<div class="pane-foot place-card${sel.mika ? ' by-mika' : ''}">
          <div class="pc-head"><b>${h(sel.nom)}</b><span class="muted">${h(sel.sorte)} · ${h(sel.ville)} · ${h(sel.dist)} d'Annecy</span></div>
          ${sel.mika ? `<p class="pc-mika">${ico('sparkle', 'xs')}« au calme, au-dessus du lac. pas d'électricité, mais la vue au réveil »</p>` : ''}
          <div class="row wrap"><button class="btn sm primary" type="button" data-go="#carte/itineraire">${ico('map', 'sm')}Itinéraire jusqu'ici</button>
            <button class="btn sm" type="button" data-ajout>${ico('plus', 'sm')}Ajouter au voyage</button>
            <button class="btn sm mika" type="button" data-parler>${ico('chat', 'sm')}En parler à Mika</button></div></div>` : ''}
      </aside>
      <section class="pane map-pane">${map}${zoom}
        <div class="map-legend">${ico('search', 'sm')}<b>Campings autour du lac d'Annecy</b><span class="muted">6 lieux · ${etat.autour === 'moi' ? 'autour de ta position' : 'dans cette zone'}</span></div>${attribution}</section>
    </div>`;
  }

  // ── Itinéraire ──────────────────────────────────────────────────────
  function vueItineraire() {
    const map = carte({ vue: boite(ITI.trace, 0.08), titre: 'Itinéraire de Lille à Annecy',
      traces: [{ pts: ITI.trace }, ...(etat.peages ? [] : [{ pts: ['lille', 'stquentin', 'reims', 'troyes', [4.9, 47.6], 'dijon', [5.3, 46.6], 'bourg', 'annecy'], faible: true }])],
      villes: [{ k: 'reims', nom: 'Reims' }, { k: 'dijon', nom: 'Dijon' }, { k: 'troyes', nom: 'Troyes' }, { k: 'bourg', nom: 'Bourg-en-Bresse' }],
      pins: [{ at: V.lille, n: 'A', label: 'Lille' }, { at: V.annecy, n: 'B', label: 'Annecy' }], ici: V.lille });
    const modes = [['voiture', 'Voiture'], ['velo', 'Vélo'], ['pied', 'À pied']];
    return `<div class="split carte-split">
      <aside class="pane carte-side"><div class="pane-scroll iti">
        <div class="iti-points">
          <div class="iti-pt"><span class="iti-dot a">A</span><input value="${h(ITI.de)}" aria-label="Départ"></div>
          <div class="iti-pt"><span class="iti-dot b">B</span><input value="${h(ITI.a)}" aria-label="Arrivée"></div>
          <div class="row"><button class="btn sm ghost" type="button" data-toast="etape">${ico('plus', 'sm')}Ajouter une étape</button>
            <button class="btn sm ghost" type="button" data-toast="inverser">${ico('sort', 'sm')}Inverser</button></div>
        </div>
        <div class="seg" role="group" aria-label="Comment">${modes.map(([id, nom]) => `<button type="button" aria-pressed="${etat.mode === id}" data-mode="${id}">${h(nom)}</button>`).join('')}</div>
        <div class="iti-opts">
          <label class="check"><input type="checkbox" data-opt="peages"${etat.peages ? '' : ' checked'}><span>Éviter les péages</span></label>
          <label class="check"><input type="checkbox" data-opt="autoroutes"${etat.autoroutes ? '' : ' checked'}><span>Éviter les autoroutes</span></label>
          <label class="check"><input type="checkbox"><span>Éviter les ferries</span></label></div>
        <div class="iti-res">
          <div class="iti-big"><b>${etat.peages ? ITI.duree : ITI.sansPeage.duree}</b><span>${etat.peages ? ITI.km : ITI.sansPeage.km}</span></div>
          <div class="muted small">${etat.peages ? 'par ' + h(ITI.par) : 'sans péage : par Saint-Quentin, Reims et Bourg-en-Bresse'} · arrivée vers 15 h 35 si tu pars à 8 h 30</div>
          ${etat.peages ? `<button class="iti-alt" type="button" data-opt-alt>${ico('chev-right', 'xs')}Sans péage : ${ITI.sansPeage.duree} · ${ITI.sansPeage.km}</button>` : ''}
          <div class="row wrap"><button class="btn sm primary" type="button" data-go="#carte/voyages/alpes">${ico('plus', 'sm')}En faire un voyage</button>
            <button class="btn sm" type="button" data-toast="gpx">${ico('download', 'sm')}GPX</button>
            <button class="btn sm mika" type="button" data-parler>${ico('chat', 'sm')}Envoyer à Mika</button></div>
        </div>
        <h2 class="section-title">Consignes <span class="cnt">${ITI.consignes.length}</span></h2>
        <ol class="iti-steps">${ITI.consignes.map(([t, d], i) => `<li><span class="st-n">${i + 1}</span><span>${h(t)}</span><span class="muted">${h(d)}</span></li>`).join('')}</ol>
        <p class="small muted iti-src">${ico('server', 'xs')}Calculé par Valhalla, sur le serveur public de FOSSGIS, relayé par ce serveur : il voit les points du trajet, jamais qui tu es. Au plus une demande par seconde.</p>
      </div></aside>
      <section class="pane map-pane">${map}${zoom}${attribution}</section>
    </div>`;
  }

  // ── Voyages ─────────────────────────────────────────────────────────
  function vueVoyages() {
    return `<div class="trips">${VOYAGES.map((v) => `<a class="trip-card${v.passe ? ' passe' : ''}" href="#carte/voyages/${v.id}">
        <div class="tc-map">${v.jours.length ? M.carteMini(v.id) : `<div class="tc-empty">${ico('map', 'lg')}</div>`}</div>
        <div class="tc-body"><b>${h(v.titre)}</b><span class="muted small">${h(v.dates)}</span>
          <span class="row wrap tc-tags"><span class="tag">${h(v.km)}</span><span class="tag">${h(v.duree)}</span>
          ${v.avecMika ? '<span class="tag mika">' + ico('sparkle') + 'préparé avec Mika</span>' : ''}${v.passe ? '<span class="tag">passé</span>' : ''}</span></div></a>`).join('')}
      <button class="trip-card new" type="button" data-toast="nouveau">${ico('plus', 'lg')}<b>Nouveau voyage</b><span class="muted small">ou demande-le à Mika dans le chat</span></button></div>`;
  }

  function vueVoyage(v) {
    const tous = v.jours.flatMap((j) => j.trace);
    let n = 0;
    const etapes = v.jours.map((j) => ({ ...j, etapes: j.etapes.filter((e) => !etat.retires.has(e.nom)) }));
    const pins = etapes.flatMap((j) => j.etapes.map((e) => ({ at: e.at, mika: e.mika, n: ++n })));
    const map = carte({ vue: boite(tous, 0.08), titre: v.titre, traces: v.jours.map((j) => ({ pts: j.trace })),
      villes: [{ k: 'dijon', nom: 'Dijon' }, { k: 'annecy', nom: 'Annecy' }, { k: 'grenoble', nom: 'Grenoble' }, { k: 'nice', nom: 'Nice' }].filter(() => v.id === 'alpes'),
      pins });
    let m = 0;
    return `<div class="split carte-split voyage">
      <aside class="pane carte-side"><div class="pane-scroll trip">
        <div class="trip-head"><a class="btn sm ghost" href="#carte/voyages">${ico('chev-left', 'sm')}Voyages</a>
          <h2>${h(v.titre)}</h2><span class="muted small">${h(v.dates)} · ${h(v.mode)} · ${h(v.options)}</span>
          <div class="row wrap"><span class="tag">${h(v.km)}</span><span class="tag">${h(v.duree)}</span><span class="tag">${v.jours.length} jours</span>
            ${v.avecMika ? `<span class="tag mika">${ico('sparkle')}préparé avec Mika</span>` : ''}</div></div>
        ${etapes.map((j) => `<section class="trip-day">
          <div class="trip-day-head"><b>Jour ${j.n} · ${h(j.titre)}</b><span class="muted small">${h(j.quand)} · ${h(j.km)} · ${h(j.duree)} · par ${h(j.par)}</span></div>
          <ol class="stops">${j.etapes.map((e) => `${e.troncon ? `<li class="leg">${ico('chev-down', 'xs')}${h(e.troncon)}</li>` : ''}
            <li class="stop${e.mika ? ' by-mika' : ''}"><span class="stop-n">${++m}</span><span class="stop-main"><b>${h(e.nom)}</b>
              <span class="small muted">${h(e.sorte)} · ${h(e.heure)}</span>
              ${e.mika ? `<span class="stop-mika">${ico('sparkle', 'xs')}ajouté par Mika${e.dit ? ` : « ${h(e.dit)} »` : ''}</span>` : ''}</span>
              ${e.mika ? `<button class="btn icon ghost sm" type="button" title="Retirer cet arrêt" data-retirer="${h(e.nom)}">${ico('x', 'sm')}</button>` : `<span class="grip" title="Glisser pour changer l'ordre">${ico('grip', 'sm')}</span>`}</li>`).join('')}</ol>
          <button class="btn sm ghost add-stop" type="button" data-toast="etape">${ico('plus', 'sm')}Ajouter un arrêt</button></section>`).join('')}
        <section class="onroute"><h2 class="section-title">Sur la route <span class="muted small">à moins de 10 km du trajet · index local</span></h2>
          <div class="cs-cats">${[['voir', 'À voir'], ['nature', 'Nature'], ['manger', 'Manger'], ['route', 'En route']].map(([id, nom]) => `<button type="button" class="cat${id === 'voir' ? ' on' : ''}" data-toast="cat">${h(nom)}</button>`).join('')}</div>
          <ul class="onroute-list">${SUR_LA_ROUTE.map((s) => `<li><span class="li-main"><b>${h(s.nom)}</b><span class="small muted">${h(s.sorte)} · ${h(s.pres)}</span></span>
            <button class="btn sm" type="button" data-ajout>${ico('plus', 'sm')}Ajouter</button></li>`).join('')}</ul></section>
      </div></aside>
      <section class="pane map-pane">${map}${zoom}${attribution}</section></div>`;
  }

  // ── L'écran ─────────────────────────────────────────────────────────
  M.register('carte', {
    titre: 'Carte',
    onglets: [{ id: 'explorer', titre: 'Explorer', ico: 'search' }, { id: 'itineraire', titre: 'Itinéraire', ico: 'map' }, { id: 'voyages', titre: 'Voyages', cnt: VOYAGES.length }],
    actions: (ctx) => {
      if (ctx.onglet === 'voyages' && ctx.item) return `<button class="btn sm" type="button" data-toast="optimiser" title="Le meilleur ordre des arrêts d'une journée (Valhalla)">${ico('refresh', 'sm')}<span class="lbl">Optimiser l'ordre</span></button>
        <button class="btn sm" type="button" data-toast="gpx" title="Le tracé et les arrêts, pour un GPS ou une app de navigation">${ico('download', 'sm')}<span class="lbl">GPX</span></button>
        <button class="btn sm mika" type="button" data-parler>${ico('sparkle', 'sm')}<span class="lbl">Demander à Mika</span></button>`;
      if (ctx.onglet === 'voyages') return `<button class="btn sm primary" type="button" data-toast="nouveau">${ico('plus', 'sm')}<span class="lbl">Nouveau voyage</span></button>`;
      return '';
    },
    monte(sec) {
      M.on(sec, '[data-cat]', 'click', (e, b) => {
        etat.cat = b.dataset.cat;
        if (etat.cat !== 'dormir') M.toast('Maquette : seule « Dormir » a des lieux ici.', { ico: 'info' });
        M.rafraichir();
      });
      M.on(sec, '[data-autour]', 'click', (e, b) => { etat.autour = b.dataset.autour; M.rafraichir(); });
      M.on(sec, '[data-lieu]', 'click', (e, b) => { etat.sel = b.dataset.lieu; M.rafraichir(); });
      M.on(sec, '[data-pin]', 'click', (e, b) => { etat.sel = b.dataset.pin; M.rafraichir(); });
      M.on(sec, '[data-mode]', 'click', (e, b) => { etat.mode = b.dataset.mode; M.rafraichir(); if (etat.mode !== 'voiture') M.toast('Maquette : seul le trajet en voiture est dessiné.', { ico: 'info' }); });
      M.on(sec, '[data-opt]', 'change', (e, b) => { etat[b.dataset.opt] = !b.checked; M.rafraichir(); });
      M.on(sec, '[data-opt-alt]', 'click', () => { etat.peages = false; M.rafraichir(); });
      M.on(sec, '[data-go]', 'click', (e, b) => M.go(b.dataset.go));
      M.on(sec, '[data-retirer]', 'click', (e, b) => { etat.retires.add(b.dataset.retirer); M.rafraichir(); M.toast('Arrêt retiré. Mika le saura en relisant le voyage.', { ico: 'x' }); });
      M.on(sec, '[data-ajout]', 'click', () => M.toast('Ajouté au voyage « Les Alpes en cinq jours », jour 4.', { ico: 'plus' }));
      M.on(sec, '[data-parler]', 'click', () => { M.toast('Le chat s\'ouvre, avec ce lieu ou ce voyage sous les yeux de Mika.', { mika: true }); M.go('#chat'); });
      M.on(sec, '[data-zoom]', 'click', () => M.toast('Maquette : le vrai écran zoome (MapLibre).', { ico: 'map' }));
      const TOASTS = {
        adresse: ['L\'adresse se place sur la carte : itinéraire, voyage ou Mika.', 'pin'],
        etape: ['Une étape de plus : un lieu, une adresse, ta position.', 'plus'],
        inverser: ['Départ et arrivée inversés.', 'sort'],
        gpx: ['Le fichier GPX se télécharge : le tracé et les arrêts.', 'download'],
        nouveau: ['Un voyage neuf : un titre, des dates, un premier arrêt.', 'plus'],
        optimiser: ['Les arrêts de chaque jour remis dans le meilleur ordre ; départ et nuit ne bougent pas.', 'refresh'],
        cat: ['Les lieux de cette catégorie, le long du trajet.', 'search'],
      };
      M.on(sec, '[data-toast]', 'click', (e, b) => { const t = TOASTS[b.dataset.toast]; if (t) M.toast(t[0], { ico: t[1] }); });
      sec.addEventListener('input', (e) => { if (e.target.matches('[data-q]')) { etat.q = e.target.value; clearTimeout(etat.tq); etat.tq = setTimeout(() => { M.rafraichir(); const i = sec.querySelector('[data-q]'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }, 350); } });
    },
    rendu(body, ctx) {
      if (ctx.onglet === 'itineraire') body.innerHTML = vueItineraire();
      else if (ctx.onglet === 'voyages') {
        const v = VOYAGES.find((x) => x.id === ctx.item);
        body.innerHTML = v && v.jours.length ? vueVoyage(v) : vueVoyages();
      } else body.innerHTML = vueExplorer();
    },
    recherche: () => [
      ...VOYAGES.map((v) => ({ groupe: 'Voyages', titre: v.titre, sous: v.dates, ico: 'map', route: `#carte/voyages/${v.id}` })),
      ...LIEUX.map((l) => ({ groupe: 'Lieux', titre: l.nom, sous: `${l.sorte} · ${l.ville}`, ico: 'pin', route: '#carte/explorer' })),
    ],
    notes: () => [
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'La carte, servie par le serveur', texte: 'tuiles PMTiles de la France (10 Go, zooms 0 à 15) lues ou relayées par le serveur, polices et icônes comprises ; MapLibre, clair et sombre ; le navigateur ne parle qu\'au serveur', src: 'ADR 0193 · adapters/maps/tiles.py · app/moi/phone.py' },
      { statut: 'existe', titre: 'Où tu es', texte: 'la position que ton téléphone donne (application ouverte) ; location_where et la bulle 📍', src: 'ADR 0119 · plugins/location' },
      { groupe: 'Décidé le 2026-11-04', statut: 'decide', titre: 'Itinéraires par Valhalla, relayés', texte: 'd\'abord le serveur public de FOSSGIS (celui d\'openstreetmap.org : une demande par seconde au plus, sans garantie) ; un Valhalla sur le portable ensuite, réglé dans la console' },
      { statut: 'decide', titre: 'Ce qui sort, et vers qui', texte: 'rien de toi : ni ton nom, ni tes cookies. Les points d\'un trajet vont au serveur d\'itinéraires réglé ; le texte d\'une adresse cherchée, à la Géoplateforme ; les lieux se cherchent dans un index local' },
      { groupe: 'À construire', statut: 'manque', titre: 'L\'index des lieux', texte: 'mika carte lieux : les points d\'intérêt et les lieux nommés tirés des tuiles (cartes/lieux.db, SQLite FTS5 + R-tree), par catégorie, autour d\'un point ou le long d\'un trajet' },
      { statut: 'manque', titre: 'Les adresses', texte: 'la Géoplateforme de l\'IGN (la Base Adresse Nationale), relayée par le serveur' },
      { statut: 'manque', titre: 'Les itinéraires', texte: 'voiture, vélo, à pied ; éviter péages, autoroutes, ferries ; consignes en français ; le meilleur ordre des arrêts ; GPX' },
      { statut: 'manque', titre: 'Les voyages', texte: 'un plugin : ses événements (créé, arrêt ajouté, déplacé, retiré…), écrits par toi depuis cet écran ou par Mika dans la conversation ; l\'oubli de la personne les efface' },
      { statut: 'manque', titre: 'Ses outils', texte: 'chercher un lieu, calculer un trajet, préparer un voyage, proposer une carte ; en tête-à-tête, pour quelqu\'un qui a un compte' },
      { statut: 'manque', titre: 'Sa carte dans le chat', texte: 'une note de message (carte:, voyage:) que le chat montre en carte miniature, qui s\'ouvre ici' },
    ],
  });
})();
