/* Carte : la fiche d'un lieu et les événements autour (proposés le 2026-11-17 ; Google Maps à la place de Tripadvisor
   depuis le 2026-11-20, ADR 0256). Trois sources, chacune nommée là où elle parle :
   - OpenStreetMap complet (l'extrait France de Geofabrik) : cuisine, horaires, téléphone, site, terrasse, végétarien,
     accessibilité, étoiles… dans l'index local, rien ne sort ;
   - Google Maps (l'API Google Places) : la note, le nombre d'avis, le prix et sa fourchette, le résumé, les avis avec
     leur auteur, chargés autour de toi et gardés un temps sur le serveur ; ni répartition ni sous-notes (Google n'en
     donne pas) ;
   - DATAtourisme (les offices de tourisme) : la description, les labels, les tarifs, et les événements, dans une base
     locale remise à jour chaque soir.
   Mika lit les mêmes données par ses outils ; ce qu'elle en tire est rose. */
(function () {
  const { h, ico } = A;
  const K = A.carteKit;
  const { V } = K;

  // ── Les restaurants (inventés, dans le Vieux-Lille) ──────────────────
  const AV = (note, texte, qui, quand) => ({ note, texte, qui, quand });
  const RESTOS = [
    { id: 'atelier', nom: 'La Table de la Treille', sorte: 'Estaminet', cuisine: 'Flamande', ville: 'Lille', at: [3.0628, 50.6408], dist: '0,4 km',
      ouvert: 'Ouvert · ferme à 22:30', prix: '€€–€€€',
      g: { note: 4.5, nb: '1 284', prix: '€€', fourchette: '20–40 €', maj: 'aujourd\'hui à 07:12',
        resume: 'Estaminet au pied de la Treille : carbonade, potjevleesch et welsh, avec les bières de la métropole.',
        ajoute: [['Réservation', 'oui (selon Google)']],
        avis: [
          AV(5, 'Accueil chaleureux, welsh généreux et carbonade fondante, pain de la boulangerie d\'à côté. On a réservé la veille pour une table en terrasse, rue de la Monnaie.', 'Camille L.', 'il y a 2 semaines'),
          AV(4, 'Potjevleesch excellent. Il a fallu attendre 40 minutes entre l\'entrée et le plat : la salle était pleine. En semaine, sans doute parfait.', 'Thomas B.', 'il y a un mois'),
          AV(3, 'Bons produits mais un peu cher pour ce que c\'est, et la terrasse est bruyante côté rue.', 'Inès R.', 'il y a 2 mois'),
        ] },
      osm: [['Cuisine', 'flamande, régionale'], ['Horaires', 'mar.–sam. 12:00–14:00, 19:00–22:30 · dim. 12:00–14:30 · lun. fermé'],
        ['Téléphone', '03 20 00 00 00'], ['Site', 'table-treille.exemple'], ['Terrasse', 'oui'], ['Végétarien', 'quelques plats'], ['Vegan', 'non renseigné'],
        ['Fauteuil roulant', 'accessible'], ['À emporter', 'non']],
      dt: { desc: 'Au pied de la cathédrale de la Treille, un estaminet où l\'on sert carbonade, potjevleesch et welsh, avec les bières des brasseries de la métropole et les fromages des Flandres.',
        labels: ['Maître Restaurateur', 'Qualité Tourisme'], tarifs: 'menu du midi 19 € · carte de 24 à 40 €', par: 'Un office de tourisme (texte inventé)' },
      mika: 'les avis récents parlent d\'attente le samedi soir. un mardi, c\'est parfait, et demande la terrasse côté rue de la Monnaie',
      photos: [{ de: 'ot', credit: 'Office de tourisme (exemple)', licence: 'CC BY-NC-ND 4.0', legende: 'La terrasse, rue de la Monnaie', teinte: 30 }, { de: 'g', credit: 'Camille L.', legende: 'Le welsh', teinte: 45 },
        { de: 'g', credit: 'Thomas B.', legende: 'La salle, un samedi soir', teinte: 15 }, { de: 'ot', credit: 'Office de tourisme (exemple)', licence: 'CC BY-NC-ND 4.0', legende: 'La façade', teinte: 210 }] },
    { id: 'gabbiano', nom: 'Pizzeria Il Gabbiano', sorte: 'Pizzeria', cuisine: 'Italienne', ville: 'Lille', at: [3.0590, 50.6345], dist: '0,4 km',
      ouvert: 'Ouvert · ferme à 23:00', prix: '€€', g: { note: 4, nb: '612' }, terrasse: true, vege: true, photos: [{ de: 'g', credit: 'Léa M.', teinte: 5 }] },
    { id: 'margaux', nom: 'Chez Margaux', sorte: 'Bistrot', cuisine: 'Française', ville: 'Lille', at: [3.0705, 50.6390], dist: '0,6 km',
      ouvert: 'Ouvre à 19:00', prix: '€€', g: { note: 4.5, nb: '388' }, vege: true, mika: true, photos: [{ de: 'ot', credit: 'Office de tourisme (exemple)', teinte: 330 }] },
    { id: 'remparts', nom: 'Café des Remparts', sorte: 'Café', cuisine: 'Brunch', ville: 'Lille', at: [3.0560, 50.6430], dist: '0,8 km',
      ouvert: 'Fermé · ouvre demain 08:00', prix: '€', g: { note: 3.5, nb: '95' }, terrasse: true },
    { id: 'reblochon', nom: 'Le Petit Maroilles', sorte: 'Restaurant', cuisine: 'Flamande', ville: 'Lambersart', at: [3.0310, 50.6500], dist: '2,6 km',
      ouvert: 'Ouvert · ferme à 21:30', prix: '€€', g: { introuvable: 'Rien trouvé sur Google sous ce nom à moins de 100 m (cherché le 20 novembre).', maj: 'aujourd\'hui à 07:12' }, terrasse: true },
  ];
  // Vrais événements autour de Lille, la semaine du 17 novembre 2026, tirés de l'API DATAtourisme (Licence Ouverte) :
  // le texte et les tarifs sont ceux des offices ; seul ce que Mika en dit est inventé.
  const EVTS = [
    { id: 'eboue', nom: 'Fabrice Éboué', type: 'Spectacle', jour: 'jeu', quand: 'jeu. 19 nov. · 20:00–21:30', lieu: 'Le Colisée', ville: 'Roubaix', at: [3.16348, 50.69069], dist: '9,3 km',
      prix: '52€ ou 46€', par: 'Hauts-de-France Tourisme', maj: '2026-06-11',
      desc: 'Après le succès retentissant de « Adieu Hier », Fabrice Éboué revient sur scène avec son tout nouveau spectacle « SolitudeS ». Dans ce one-man-show inédit, l’humoriste à l’humour noir et au regard acéré s’attaque à l’un des grands paradoxes de notre époque : n’avoir jamais été aussi connectés… et pourtant si seuls. À travers des observations incisives sur nos relations, les réseaux sociaux, le couple, la société et…',
      kv: [['Adresse', '31 rue de l\'Epeule, Roubaix'], ['Tarifs', '52€ ou 46€'], ['Téléphone', '+33 3 20 24 07 07']] },
    { id: 'pogorelich', nom: 'Récital piano d\'Ivo Pogorelich', type: 'Concert', jour: 'jeu', quand: 'jeu. 19 nov. · 20:00–22:00', lieu: '24 avenue gustave Delory', ville: 'Roubaix', at: [3.1694, 50.67519], dist: '8,6 km',
      prix: 'Réservation obligatoire. Tarifs entre 7 et 68 euros', par: 'Hauts-de-France Tourisme', maj: '2026-07-01',
      desc: 'Figure mythique de la scène pianistique internationale, Ivo Pogorelich se produit à Roubaix pour un récital exceptionnel. Révélé sur la scène internationale par son interprétation singulière et son immense liberté artistique, le pianiste demeure l\'une des personnalités les plus fascinantes du monde musical. Ses apparitions en France étant rares, ce concert constitue un rendez-vous exceptionnel pour les mélomanes. La…',
      kv: [['Adresse', '24 avenue gustave Delory, Roubaix'], ['Tarifs', 'Réservation obligatoire. Tarifs entre 7 et 68 euros'], ['Téléphone', '+33 6 80 80 09 09']] },
    { id: 'fiatlux', nom: 'Exposition « Fiat lux ! Une quête effrénée de lumière au XIXᵉ siècle »', type: 'Exposition', jour: 'jeu', quand: 'jeu., sam., lun. · 10:00–18:00', lieu: '9 rue Princesse', ville: 'Lille', at: [3.05875, 50.64599], dist: '1,0 km',
      prix: 'Tarif 8 € / Réduit 6 €', par: 'Hauts-de-France Tourisme', maj: '2026-05-13',
      desc: 'Au 19ᵉ siècle, une rupture historique se produit. L’Homme se lance dans cette entreprise alors considérée comme insensée : abolir la nuit ! « Fiat lux ! » vous invite à revivre cette épopée fascinante, de la lueur vacillante des bougies et des lampes à huile à l\'éclat révolutionnaire du gaz puis de l\'électricité. Des premiers becs de gaz parisiens aux défis de l\'électrification lilloise, plongez dans l\'effervescence…',
      kv: [['Adresse', '9 rue Princesse, Lille'], ['Tarifs', 'Tarif 8 € / Réduit 6 €'], ['Téléphone', '+33 3 59 73 00 30']] },
    { id: 'poulenc', nom: 'Quatuor Poulenc', type: 'Concert', jour: 'ven', quand: 'ven. 20 nov. · 19:00–20:30', lieu: '80 rue de Lille', ville: 'Roubaix', at: [3.16287, 50.6837], dist: '8,7 km',
      prix: 'Entrée 10€/7€/5€', par: 'Hauts-de-France Tourisme', maj: '2026-09-12', mika: true, dit: 'des cuivres de l\'Orchestre national de Lille, vendredi à 19 h, 10 € : ça te tente ?',
      desc: 'Ce concert réunit quatre musiciens dont les parcours se rejoignent au sein de l’Orchestre National de Lille, et qui partagent une même envie : faire entendre la richesse, la souplesse et l’expressivité des cuivres dans un programme où se mêlent esprit français et virtuosité. La soirée s’ouvre avec le Trio pour trompette, cor et trombone de Francis Poulenc, une œuvre rare et savoureuse, où l’humour, l’élégance…',
      kv: [['Adresse', '80 rue de Lille, Roubaix'], ['Tarifs', 'Entrée 10€/7€/5€']] },
    { id: 'obsession', nom: 'Exposition "Obsession" au LaM', type: 'Exposition', jour: 'sam', quand: 'du mer. au dim. · 11:00–19:00', lieu: 'LaM', ville: 'Villeneuve-d\'Ascq', at: [3.14859, 50.63758], dist: '6,0 km',
      prix: 'non précisé', par: 'Hauts-de-France Tourisme', maj: '2026-03-21',
      desc: 'Pour sa réouverture, le LaM repense l\'accrochage de sa collection avec un nouveau parcours thématique et original intitulé « Obsession ». Pensé comme une exposition, il explore la répétition, la permanence et l\'intensité créatrice tout au long des XXe et XXIe siècles à travers un dialogue inédit entre art moderne, art brut et art contemporain. Certaines salles monographiques dédiées à de grandes figures de l\'art…',
      kv: [['Adresse', '1 allée du Musée, Villeneuve-d\'Ascq'], ['Tarifs', 'non précisé'], ['Téléphone', '+33 3 20 19 68 68']] },
    { id: 'livres', nom: 'Marché aux livres', type: 'Marché', jour: 'sam', quand: 'du mar. au dim. · 13:00–19:00', lieu: 'Vieille Bourse', ville: 'Lille', at: [3.06401, 50.63705], dist: '0,1 km',
      prix: 'non précisé', par: 'Hello Lille', maj: '2023-12-05',
      desc: 'Au cœur du centre historique de Lille, la cour intérieure de la Vieille Bourse, joyau de l\'architecture flamande du XVIIe siècle, accueille chaque après-midi, du mardi au dimanche, le Marché aux livres. Dans ce lieu chargé d\'histoire, les passionnés de lecture, les collectionneurs et les flâneurs se retrouvent pour chiner parmi une multitude de trésors littéraires. Entre les arches ornées et les façades sculptées,…',
      kv: [['Adresse', 'Cour intérieure de la Vieille Bourse, Place du Général de Gaulle, Lille'], ['Tarifs', 'non précisé'], ['Téléphone', '+33 3 20 49 50 00']] },
    { id: 'fanfarai', nom: '10 ans ! Fanfaraï Big Band + Karaoké de bled + Ben Bella Jazz', type: 'Concert', jour: 'sam', quand: 'sam. 21 nov. · 19:00–minuit', lieu: '5 Place Notre-dame', ville: 'Tourcoing', at: [3.15495, 50.72483], dist: '12 km',
      prix: '10 €', par: 'Hauts-de-France Tourisme', maj: '2026-07-09',
      desc: '19h Ouverture des portes 19h30 Karaoké du bled Venez danser et chanter sur les standards de la chanson de l’exil d’hier et d’aujourd’hui ! Au micro, Samira Brahmia et Naïma Huber-Yahi invitent à chanter, en français, en kabyle ou en arabe, les grands succès de ce patrimoine en partage. 21h Fanfaraï Big Band est certainement le Big Band français le plus atypique ! Il fait dialoguer les sonorités traditionnelles…',
      kv: [['Adresse', '5 Place Notre-dame, Tourcoing'], ['Tarifs', '10 €'], ['Téléphone', '+33 3 20 70 10 00']] },
    { id: 'clerc', nom: 'Julien Clerc', type: 'Concert', jour: 'dim', quand: 'dim. 22 nov. · 17:00–19:00', lieu: 'Le Colisée', ville: 'Roubaix', at: [3.16348, 50.69069], dist: '9,3 km',
      prix: 'De 65€ à 45€', par: 'Hauts-de-France Tourisme', maj: '2026-06-11',
      desc: 'Révélé en 1968 avec « La Cavalerie », il n\'a jamais vraiment quitté nos radios, nos salons, ni nos mémoires. « Ce n\'est rien, Ma préférence, Femmes je vous aime, Fais-moi une place »… Ces chansons ne sont pas seulement des tubes : elles sont les bandes-son d\'instants que l\'on n\'oublie pas. Cinquante ans de carrière, et cette façon unique de chanter l\'amour comme si c\'était toujours la première fois. Avec « Une Vie…',
      kv: [['Adresse', '31 rue de l\'Epeule, Roubaix'], ['Tarifs', 'De 65€ à 45€'], ['Téléphone', '+33 3 20 24 07 07']] },
    { id: 'wazemmes', nom: 'Marché de Wazemmes', type: 'Marché', jour: 'dim', quand: 'dim. 22 nov. · 07:00–14:00', lieu: 'Place de la Nouvelle Aventure', ville: 'Lille', at: [3.04996, 50.62652], dist: '1,5 km',
      prix: 'non précisé', par: 'Hello Lille', maj: '2023-12-05',
      desc: 'Impossible de ne pas se rendre au marché de Wazemmes un dimanche ! Réputé pour son ampleur et ses prix défiant toute concurrence, ce dernier rassemble les producteurs locaux et revendeurs de produits exotiques, les marchands de tissus, d’électro-ménagers et les artisans du quartier. Son ambiance conviviale et populaire vous donne un bel exemple de la chaleur lilloise.',
      kv: [['Adresse', 'Place de la Nouvelle Aventure, Lille'], ['Tarifs', 'non précisé'], ['Téléphone', '+33 3 20 49 50 00']] },
  ];
  const JOURS = [['jeu', 'Jeudi 19 novembre'], ['ven', 'Vendredi 20 novembre'], ['sam', 'Samedi 21 novembre'], ['dim', 'Dimanche 22 novembre']];
  const VILLES_NORD = [{ k: [3.063, 50.637], nom: 'Lille' }, { k: [3.174, 50.692], nom: 'Roubaix' }, { k: [3.161, 50.724], nom: 'Tourcoing' }, { k: [3.131, 50.623], nom: 'Villeneuve-d\'Ascq' }];

  // ── Le dessin ─────────────────────────────────────────────────────────
  /** Les étoiles d'une note Google (pleines, à moitié, vides : une moitié dès 0,25, pleine dès 0,75). */
  const etoiles = (n, cls) => `<span class="etoiles${cls ? ' ' + cls : ''}" role="img" aria-label="${String(n).replace('.', ',')} sur 5">${[1, 2, 3, 4, 5].map((i) => `<i class="${n >= i - 0.25 ? 'on' : n >= i - 0.75 ? 'half' : ''}"></i>`).join('')}</span>`;
  const note = (n) => String(n).replace('.', ',');
  const ouvertTag = (o) => `<span class="tag ${/^Ouvert/.test(o) ? 'ok' : /^Fermé/.test(o) ? 'danger' : 'warn'}">${h(o)}</span>`;
  const source = (txt) => `<p class="src-line">${txt}</p>`;

  // ── Les photos ────────────────────────────────────────────────────────
  // Une photo : { src (l'adresse que le serveur relaie ; vide : un aplat de la maquette), de ('g' Google Maps,
  // 'ot' l'office de tourisme), credit (son auteur, lié à sa page), licence, legende, teinte }. Le téléphone ne joint
  // jamais Google ni le site d'un office : le serveur va chercher l'image, la garde un temps, et la sert (comme les
  // tuiles et les images d'un mail).
  const PH_DE = { g: 'Google Maps', ot: 'Office de tourisme' };
  const PHOTOS = {};
  let nPh = 0;
  function photo(p, cls, attrs) {
    const id = 'ph' + (++nPh);
    PHOTOS[id] = p;
    const fond = p.src ? `<img src="${h(p.src)}" alt="${h(p.legende || '')}" loading="lazy" referrerpolicy="no-referrer">`
      : `<span class="ph-fake" style="--t:${p.teinte || 200}">${ico('image')}</span>`;
    return `<button type="button" class="ph${cls ? ' ' + cls : ''}" data-sheet="photo" data-ph="${id}" ${attrs || ''}>${fond}<span class="ph-src ${p.de}">${h(PH_DE[p.de])}</span>${p.credit ? `<span class="ph-credit">${h(p.credit)}</span>` : ''}</button>`;
  }
  /** La bande du haut d'une fiche : le plan d'abord, puis les photos ; sans photo, le plan seul. */
  const bande = (map, photos) => photos && photos.length
    ? `<div class="photos"><div class="ph ph-map">${map}</div>${photos.map((p) => photo(p)).join('')}<span class="ph-count">${ico('image', 'xs')}${photos.length} photos</span></div>`
    : `<div class="mapwrap" style="height:150px;flex:none">${map}</div>`;
  /** Le carré de tête d'une ligne : sa première photo, sinon l'icône. */
  const tete = (o, icone) => o.photos && o.photos.length
    ? `<span class="lead thumb">${o.photos[0].src ? `<img src="${h(o.photos[0].src)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="ph-fake" style="--t:${o.photos[0].teinte || 200}"></span>`}${o.mika ? '<i class="thumb-mk"></i>' : ''}</span>`
    : `<span class="lead box"${o.mika ? ' style="background:var(--mc);color:var(--on-mc)"' : ''}>${ico(icone)}</span>`;
  A.sheets.photo = (b) => {
    const p = PHOTOS[b.dataset.ph] || {};
    A.sheet(PH_DE[p.de] || 'Photo', `<div class="ph-full">${p.src ? `<img src="${h(p.src)}" alt="${h(p.legende || '')}" referrerpolicy="no-referrer">` : `<span class="ph-fake" style="--t:${p.teinte || 200}">${ico('image')}</span>`}</div>
      <div class="pad" style="padding-bottom:16px">${p.legende ? `<p style="margin-bottom:4px">${h(p.legende)}</p>` : ''}<small class="muted">${p.credit ? 'Photo : <a href="#" data-snack="Sa page s\'ouvre dans le navigateur">' + h(p.credit) + '</a> · ' : ''}${p.licence ? h(p.licence) + ' · ' : ''}${p.de === 'g' ? 'publiée sur Google Maps, gardée sur ce serveur le temps du cache' : 'de l\'office de tourisme, par DATAtourisme : son crédit et sa licence s\'affichent toujours'}</small></div>`);
  };

  // ── Manger, avec les notes ────────────────────────────────────────────
  function vueManger() {
    const vue = K.boite([[3.025, 50.66], [3.085, 50.58]], 0.02, 384 / 600);
    const map = K.carte({ vue, largeur: 384, slice: true, titre: 'Restaurants à Lille', ici: [3.063, 50.637], villes: [{ k: [3.045, 50.628], nom: 'Lille' }],
      pins: RESTOS.map((r) => ({ at: r.at, mika: r.mika, go: `#carte/fiche/${r.id}` })) });
    const ligne = (r) => `<button class="li" type="button" data-go="#carte/fiche/${r.id}">${tete(r, 'pin')}
      <span class="txt"><b>${h(r.nom)}</b><small>${r.g && r.g.note ? `<span class="g-mini">${etoiles(r.g.note, 'xs')} ${note(r.g.note)} <span class="muted">(${h(r.g.nb)})</span></span> · ` : '<span class="muted">pas sur Google Maps</span> · '}${h(r.prix)} · ${h(r.cuisine)}</small>
      <small class="${/^Ouvert/.test(r.ouvert) ? 'ok-txt' : 'muted'}">${h(r.ouvert)}${r.mika ? ' · <span class="mk-txt">Mika te le conseille</span>' : ''}</small></span><span class="trail">${h(r.dist)}</span></button>`;
    return {
      nav: 'carte', racine: true,
      html: `${K.haut('#carte')}
        <div class="mapwrap">${map}
          <div class="map-search"><label class="field">${ico('search', 'sm')}<input value="" placeholder="Un lieu, une adresse, un restaurant…" aria-label="Chercher un lieu ou une adresse">${A.act('locate', 'Autour de moi', 'data-snack="Autour de ta dernière position"')}</label>
            ${A.chips([{ l: 'Manger', on: true, radio: 'c' }, { l: 'Dormir', radio: 'c' }, { l: 'À voir', radio: 'c' }, { l: 'Nature', radio: 'c' }, { l: 'En route', radio: 'c' }])}</div>
          ${K.attrib(392)}
          <div class="msheet" style="max-height:386px"><div class="handle"></div><div class="ms-body">
            ${A.chips([{ l: 'Ouvert maintenant', ico: 'clock' }, { l: 'Terrasse' }, { l: 'Végétarien' }, { l: '4 et plus', ico: 'star' }, { l: '€' }, { l: 'Accessible' }])}
            <div class="row" style="padding:0 16px 4px"><span class="grow"><b style="font-weight:500">5 restaurants</b> <span class="muted">· autour de toi</span></span><button class="btn text sm" type="button" data-snack="Trié par note, puis par distance">${ico('sort', 'xs')}Note</button></div>
            ${RESTOS.map(ligne).join('')}
            ${source(`${ico('info', 'xs')}Notes Google Maps lues aujourd'hui à 07:12, autour de toi. Le reste vient d'OpenStreetMap, dans l'index de ce serveur.`)}
          </div></div>
        </div>`,
      notes: {
        titre: 'Carte · Manger, avec les notes',
        reprend: ['Chaque ligne : la note et le nombre d\'avis Google Maps, les prix et la cuisine, ouvert ou fermé (les horaires d\'OpenStreetMap), la distance.',
          'Des filtres sous la recherche : ouvert maintenant, terrasse, végétarien, vegan, accessible, 4 et plus, la cuisine. Tous se jugent sur le serveur ; la note vient du cache de Google.',
          'Un lieu absent de Google Maps le dit ; il reste dans la liste.'],
        trancher: ['Trier par note d\'office pour « Manger », ou garder la distance comme partout ailleurs ?'],
      },
    };
  }

  // ── La fiche d'un lieu ────────────────────────────────────────────────
  function vueFiche(id) {
    const r = RESTOS.find((x) => x.id === id) || RESTOS[0];
    const g = r.g;
    const map = K.carte({ vue: K.boite([[r.at[0] - 0.02, r.at[1] - 0.01], [r.at[0] + 0.02, r.at[1] + 0.01]], 0.02, 150 / 160), largeur: 150, slice: true,
      ici: [3.063, 50.637], pins: [{ at: r.at, sel: true, mika: r.mika }] });
    // chaque avis montre son auteur (lié à sa page chez Google) et sa date, toujours
    const avis = g && g.avis ? g.avis.map((a) => `<div class="g-avis"><div class="g-avis-tete">${etoiles(a.note, 'xs')}<a href="#" data-snack="Sa page Google Maps s'ouvre dans le navigateur">${h(a.qui)}</a><span class="muted">· ${h(a.quand)}</span></div><p>${h(a.texte)}</p></div>`).join('') : '';
    const pied = g ? `<div class="g-foot">${ico('history', 'xs')}<span class="grow">Lu ${h(g.maj || 'aujourd\'hui')} · gardé sur ce serveur</span><button class="btn tonal sm" type="button" data-snack="Note et avis relus chez Google">${ico('refresh', 'sm')}Actualiser</button></div>` : '';
    const blocG = g && !g.introuvable ? `<section class="card out fiche-g">
        <div class="row"><span class="g-logo">Google Maps</span><span class="grow"></span><button class="btn text sm" type="button" data-snack="La page du lieu s'ouvre sur Google Maps, dans le navigateur">${ico('external', 'sm')}Voir sur Google Maps</button></div>
        <div class="g-head"><b>${note(g.note)}</b>${etoiles(g.note)}<span class="muted">${h(g.nb)} avis</span></div>
        ${g.prix ? `<div class="row wrap" style="gap:6px"><span class="tag">${h(g.prix)}${g.fourchette ? ' · ' + h(g.fourchette) : ''}</span></div>` : ''}
        ${g.resume ? `<p class="g-resume">${h(g.resume)}</p>` : ''}
        ${g.ajoute ? `<div class="kv">${g.ajoute.map(([k, v]) => `<span>${h(k)}</span><b>${h(v)}</b>`).join('')}</div>` : ''}
        ${avis ? `<div class="list-head" style="padding:14px 0 4px">Les avis les plus récents</div>${avis}` : ''}
        ${pied}
      </section>` : g ? `<section class="card out fiche-g">
        <div class="row"><span class="g-logo">Google Maps</span></div>
        <p class="g-resume">${h(g.introuvable)}</p>${pied}
      </section>` : `<section class="note box">${ico('info', 'sm')}<span>Pas de note ni d'avis Google Maps pour ce lieu.</span></section>`;
    const blocOSM = r.osm ? `<section class="fiche-sec"><div class="list-head">Infos pratiques</div>
        <div class="kv pad">${r.osm.map(([k, v]) => `<span>${h(k)}</span><b>${h(v)}</b>`).join('')}</div>
        ${source('OpenStreetMap, extrait du 12 novembre · index de ce serveur, rien ne sort · <a href="#" data-snack="La page du lieu s\'ouvre sur openstreetmap.org">corriger</a>')}</section>` : '';
    const blocDT = r.dt ? `<section class="fiche-sec"><div class="list-head">L'office de tourisme en dit</div>
        <p class="pad fiche-desc">${h(r.dt.desc)}</p>
        <div class="row wrap pad" style="gap:6px;margin-top:8px">${r.dt.labels.map((l) => `<span class="tag ok">${ico('shield-check', 'xs')}${h(l)}</span>`).join('')}</div>
        <div class="kv pad" style="margin-top:10px"><span>Tarifs</span><b>${h(r.dt.tarifs)}</b></div>
        ${source(`${h(r.dt.par)} · DATAtourisme, Licence Ouverte · base remise à jour cette nuit`)}</section>` : '';
    const proches = EVTS.filter((e) => e.ville === 'Lille').slice(0, 2).map((e) => `<button class="li" type="button" data-go="#carte/evenement/${e.id}"><span class="lead box">${ico('calendar')}</span><span class="txt"><b>${h(e.nom)}</b><small>${h(e.quand)} · ${h(e.dist)}</small></span></button>`).join('');
    return {
      nav: 'carte', back: '#carte/manger',
      html: `${A.top({ title: h(r.nom), sub: `${h(r.sorte)} · ${h(r.ville)} · ${h(r.dist)}`, small: true, back: true, actions: [A.act('sparkle', 'Demander à Mika', 'data-go="#chat" data-snack="Le chat s\'ouvre avec ce lieu sous ses yeux"', 'mk'), A.act('share', 'Partager', 'data-snack="Lien partagé"')] })}
        <div class="body">
          ${bande(map, r.photos)}
          <div class="pad" style="padding-top:12px"><div class="row wrap" style="gap:6px">${ouvertTag(r.ouvert)}<span class="tag">${h(r.cuisine)}</span><span class="tag">${h(r.prix)}</span>${g && g.note ? `<span class="tag">${etoiles(g.note, 'xs')}${note(g.note)}</span>` : ''}</div>
            <div class="btns three" style="margin-top:12px"><button class="btn filled" type="button" data-go="#carte/itineraire">${ico('route')}Itinéraire</button><button class="btn tonal" type="button" data-sheet="ajouter-voyage">${ico('plus')}Au voyage</button><button class="btn outlined" type="button" data-snack="Appel du 04 50 00 00 00">${ico('phone')}Appeler</button></div>
            ${r.mika ? `<div class="mika-said">${ico('sparkle')}<span>${h(r.mika)}<small class="mk-src">Mika a lu les 5 derniers avis et les horaires</small></span></div>` : ''}</div>
          <div class="pad" style="margin-top:14px">${blocG}</div>
          ${blocOSM}${blocDT}
          <section class="fiche-sec"><div class="list-head">Bientôt, tout près</div>${proches}</section>
          <div style="height:24px"></div>
        </div>`,
      notes: {
        titre: 'Carte · la fiche d\'un lieu',
        reprend: ['La bande du haut : le plan, puis les photos (office de tourisme, Google Maps), chacune avec sa source et son crédit (son auteur, lié) ; touchée, une photo s\'ouvre en grand (légende, auteur, licence). Sans photo, le plan seul.',
          'En haut : ouvert ou fermé, la cuisine, les prix, la note ; Itinéraire, Au voyage, Appeler (et dans l\'app : Site, En parler à Mika).',
          'Ce que Mika en pense, en rose, quand elle l\'a lu (elle lit la même fiche par son outil).',
          'Google Maps : la note, le nombre d\'avis, le prix et sa fourchette, le résumé, ce que Google ajoute à OpenStreetMap, les avis récents (cinq au plus), chacun avec son auteur (lié à sa page) et sa date ; « Voir sur Google Maps », la date du cache et « Actualiser ». Ni répartition ni sous-notes : Google n\'en donne pas.',
          'Un lieu que Google n\'a pas le dit dans le bloc (« Rien trouvé sur Google sous ce nom à moins de 100 m ») ; sans clé et sans cache, une note le dit.',
          'Infos pratiques (OpenStreetMap), puis ce qu\'en dit l\'office de tourisme (DATAtourisme), puis les événements tout près. Chaque bloc nomme sa source.'],
        trancher: ['L\'ordre des blocs : la note et les avis d\'abord (comme ici), ou les infos pratiques d\'abord ?',
          'Les photos Google coûtent un appel compté la première fois : l\'app ne charge que celles qu\'elle montre (la bande, en défilant). Suffisant ?'],
      },
    };
  }

  // ── Les événements ────────────────────────────────────────────────────
  function vueEvenements() {
    const map = K.carte({ vue: K.boite([[3.00, 50.77], [3.22, 50.38]], 0.02, 384 / 600), largeur: 384, slice: true, titre: 'Événements autour de Lille', ici: [3.063, 50.637],
      villes: VILLES_NORD, pins: EVTS.map((e) => ({ at: e.at, mika: e.mika, go: `#carte/evenement/${e.id}` })) });
    const ligne = (e) => `<button class="li" type="button" data-go="#carte/evenement/${e.id}">${tete(e, 'calendar')}
      <span class="txt"><b>${h(e.nom)}</b><small>${h(e.type)} · ${h(e.quand.split(' · ').pop())} · ${h(e.lieu)}</small><small class="muted">${h(e.prix)}${e.mika ? ' · <span class="mk-txt">repéré par Mika</span>' : ''}</small></span><span class="trail">${h(e.dist)}</span></button>`;
    return {
      nav: 'carte', racine: true,
      html: `${K.haut('#carte/evenements')}
        <div class="mapwrap">${map}
          <div class="map-search"><label class="field">${ico('search', 'sm')}<input value="" placeholder="Un concert, un marché, une fête…" aria-label="Chercher un événement">${A.act('locate', 'Autour de moi', 'data-snack="Autour de ta dernière position"')}</label>
            ${A.chips([{ l: 'Aujourd\'hui', radio: 'q' }, { l: 'Ce week-end', radio: 'q' }, { l: 'Cette semaine', on: true, radio: 'q' }, { l: 'Choisir…', ico: 'calendar', radio: 'q' }])}</div>
          ${K.attrib(392)}
          <div class="msheet" style="max-height:386px"><div class="handle"></div><div class="ms-body">
            ${A.chips([{ l: 'Concerts' }, { l: 'Marchés' }, { l: 'Fêtes' }, { l: 'Expositions' }, { l: 'Sport' }, { l: 'Enfants' }, { l: 'Gratuit' }])}
            ${JOURS.map(([j, titre]) => `<div class="list-head">${h(titre)}</div>${EVTS.filter((e) => e.jour === j).map(ligne).join('')}`).join('')}
            ${source(`${ico('info', 'xs')}Les offices de tourisme, par DATAtourisme : une base sur ce serveur, remise à jour chaque nuit. Rien ne sort quand tu cherches.`)}
          </div></div>
        </div>`,
      notes: {
        titre: 'Carte · Événements',
        reprend: ['Un quatrième onglet : les événements autour de toi ou dans la zone de la carte, par jour ; quand (aujourd\'hui, ce week-end, cette semaine, des dates), quoi (concerts, marchés, fêtes…), gratuit.',
          'Ils viennent de DATAtourisme, gardés dans une base du serveur : chercher ne fait rien sortir, pas même ta position.',
          'Ce que Mika a repéré pour toi est rose.',
          'Les données sont les vraies, tirées de l\'API avec ta clé le 17 novembre : un office ne donne souvent que l\'adresse du lieu (« 31 rue de l\'Épeule ») ; le serveur le rapproche du lieu nommé d\'OpenStreetMap (« Le Colisée »). Un même événement revient parfois une fois par date : le serveur les réunit.'],
        trancher: ['Mika te signale d\'elle-même un événement qui te ressemble (« il y a un quatuor samedi, à dix minutes ») ou seulement quand tu demandes ?',
          'Par défaut : « cette semaine » et 15 km autour de toi ?'],
      },
    };
  }

  function vueEvenement(id) {
    const e = EVTS.find((x) => x.id === id) || EVTS[0];
    const map = K.carte({ vue: K.boite([[e.at[0] - 0.05, e.at[1] - 0.012], [e.at[0] + 0.05, e.at[1] + 0.012]], 0.02, 384 / 150), largeur: 384, slice: true,
      ici: [3.063, 50.637], villes: VILLES_NORD, pins: [{ at: e.at, sel: true, mika: e.mika }] });
    return {
      nav: 'carte', back: '#carte/evenements',
      html: `${A.top({ title: h(e.nom), sub: `${h(e.type)} · ${h(e.ville)}`, small: true, back: true, actions: [A.act('sparkle', 'Demander à Mika', 'data-go="#chat" data-snack="Le chat s\'ouvre avec cet événement"', 'mk'), A.act('share', 'Partager', 'data-snack="Lien partagé"')] })}
        <div class="body">
          ${bande(map, e.photos)}
          <div class="pad" style="padding-top:12px"><div class="row wrap" style="gap:6px"><span class="tag pc">${ico('calendar', 'xs')}${h(e.quand)}</span><span class="tag">${h(e.prix)}</span><span class="tag">${h(e.dist)}</span></div>
            <div class="btns three" style="margin-top:12px"><button class="btn filled" type="button" data-go="#carte/itineraire">${ico('route')}Itinéraire</button><button class="btn tonal" type="button" data-sheet="ajouter-voyage">${ico('plus')}Au voyage</button><button class="btn outlined" type="button" data-snack="Ajouté à ton agenda du téléphone">${ico('calendar')}Agenda</button></div>
            ${e.dit ? `<div class="mika-said">${ico('sparkle')}<span>${h(e.dit)}</span></div>` : ''}</div>
          <section class="fiche-sec"><div class="list-head">Le programme</div><p class="pad fiche-desc">${h(e.desc || 'La description que l\'office de tourisme a donnée.')}</p></section>
          <section class="fiche-sec"><div class="list-head">Pratique</div><div class="kv pad">${(e.kv || [['Lieu', `${e.lieu}, ${e.ville}`], ['Tarifs', e.prix]]).map(([k, v]) => `<span>${h(k)}</span><b>${h(v)}</b>`).join('')}</div>
            ${source(`${h(e.par)} · DATAtourisme, Licence Ouverte · fiche mise à jour le ${h(e.maj.split('-').reverse().join('/'))}`)}</section>
          <div style="height:24px"></div>
        </div>`,
      notes: {
        titre: 'Carte · un événement',
        reprend: ['Quand, combien, à quelle distance ; Itinéraire, Au voyage (au bon jour), Agenda (l\'agenda du téléphone, rien côté serveur).',
          'Le programme et le pratique, tels que l\'office de tourisme les a donnés.'],
        trancher: ['Le bouton Agenda : utile, ou de trop ?'],
      },
    };
  }

  Object.assign(A.carteVues, { manger: vueManger, fiche: vueFiche, evenements: vueEvenements, evenement: vueEvenement });
  A.index('Carte · avis et événements', [['Manger, avec les notes', '#carte/manger'], ['La fiche d\'un lieu', '#carte/fiche/atelier'], ['Un lieu sans Google Maps', '#carte/fiche/reblochon'],
    ['Événements', '#carte/evenements'], ['Un événement', '#carte/evenement/quatuor']]);
})();
