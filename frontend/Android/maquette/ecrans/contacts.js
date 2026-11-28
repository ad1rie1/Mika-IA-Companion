/* Contacts (proposé le 2026-11-22, pas encore validé ; ADR 0298) : tous ceux que Mika connaît pour toi — vus dans ton
   Teams, tes boîtes, ton téléphone, ou dont tu lui as parlé —, et leurs organisations. C'est l'écran Contacts du web
   (`frontend/Web/maquette/ecrans/contacts.js`, validé le 2026-11-22) sur un téléphone : la liste, puis la fiche en page.
   Et, dans Écrire, les destinataires proposés depuis tous tes contacts, plus seulement tes correspondants du courrier.

   Les écrans validés ne se retouchent pas : ce fichier ajoute l'écran `contacts` et se pose par-dessus le tiroir, Plus,
   la feuille des boîtes de Mail et l'écriture d'un mail (`ecrans/mail.js`) sans les modifier. Les mots des refus et des
   confirmations sont ceux du serveur et du web (`backend/src/mika/app/me/contacts.py`,
   `frontend/Web/src/screens/contacts/view.ts`). Routes : `#contacts`, `#contacts/tiroir` (le tiroir ouvert),
   `#contacts/<id>`, `#contacts/<id>/oublier`, `#contacts/<id>/fait/<n>` (les feuilles ouvertes), `#mail/ecrire/a/<adresse>`,
   `#mail/ecrire/suggestions`. */
(function () {
  const { h, ico, D } = A;

  // D'où elle le connaît (une ligne de `sources` : l'icône, le mot), et la sorte d'un identifiant (`identifiers.kind`).
  const SOURCES = { teams: ['teams', 'Teams'], pro: ['mail', 'Pro'], perso: ['mail', 'Perso'], asso: ['mail', 'Rando Cassel'],
    lea: ['mail', 'Boîte de Léa'], whatsapp: ['chat', 'WhatsApp'], sms: ['phone', 'SMS'], raconte: ['sparkle', 'Raconté'] };
  const SORTES = { email: ['mail', 'E-mail'], teams: ['teams', 'Identifiant Teams'], phone: ['phone', 'Téléphone'], phone_app: ['chat', 'Contact WhatsApp'],
    domain: ['globe', 'Domaine'], tenant: ['teams', 'Organisation Teams'] };
  const TEAMS = 'ses messages dans Teams', TEL = 'ses messages sur ton téléphone', RACONTE = 'ce que tu lui as raconté';
  // Les mots du serveur (app/me/contacts.py) : un oubli refusé n'en dit pas plus que ce que la fiche montre déjà.
  const NOT_ALL_YOURS = 'Une part de ce qu\'elle en sait vient d\'un compte qu\'on te partage ou d\'un de ses comptes à elle : une opératrice peut l\'oublier depuis la console.';
  const NOT_YOUR_FACT = 'Ce fait vient d\'un compte qui n\'est pas à toi : elle l\'a lu ailleurs que dans tes comptes. Une opératrice peut l\'oublier depuis la console.';

  /* Les contacts d'Adrien, le dernier vu d'abord (comme l'API). Ceux du web, avec les personnes de cette maquette
     (Nadia, Camille, Thomas). `ids` : { k: sorte, v: valeur, ou: d'où elle le tient, boite et n : la boîte où l'adresse
     se voit et combien de mails, teams : l'adresse ne vient que de son profil Teams, generique : sans personne derrière } ;
     `profil` : [libellé, valeur, d'après, contact lié] ; `sait` : ce qu'elle a compris de ses messages { t, de, ou, sure,
     verrou : d'un compte qui n'est pas à toi } ; `croise` : [icône, titre, détail, route de cette maquette]. */
  const C = [
    { id: 'julien', cle: 'julien', t: '14:09', idee: 'Ton ami proche', parle: true, src: [['whatsapp', 86], ['asso', 14]],
      ids: [{ k: 'email', v: 'julien.roux@proton.me', ou: 'Rando Cassel', boite: 'Rando Cassel', n: 14 }, { k: 'phone', v: '+33 6 33 18 72 41', ou: 'WhatsApp, ton téléphone' }],
      sait: [{ t: 'Il organise la boucle des Monts dimanche, départ 8 h 30 du parking de la gare.', de: TEL, ou: 'en tête-à-tête', sure: 0.9 }],
      croise: [['chat', 'Julien Roux', 'WhatsApp · 86 messages · 14:09', '#telephone/c/julien'], ['chat', 'Rando dimanche 🥾', 'groupe WhatsApp · 1 message', '#telephone/c/rando'],
        ['mail', 'Re: Rando dimanche — covoiturage', 'Rando Cassel · 14 mails · 10:20', '#mail/lire/m-julien']],
      message: '#telephone/c/julien' },
    { id: 'thomas', cle: 'thomas', t: '13:47', idee: 'Ton ami', src: [['whatsapp', 3]],
      ids: [{ k: 'phone_app', v: 'Thomas G.', ou: 'ton carnet · groupe « Rando dimanche 🥾 »' }],
      sait: [{ t: 'Il propose de décaler le départ de la rando à 9 h, à cause des averses.', de: TEL, ou: 'dans le groupe « Rando dimanche 🥾 »', sure: 0.85 }],
      croise: [['chat', 'Rando dimanche 🥾', 'groupe WhatsApp · 3 messages · 13:47', '#telephone/c/rando']] },
    { id: 'claire', cle: 'claire', org: 'lumen', t: '13:41', idee: 'Cheffe de projet', src: [['teams', 64], ['pro', 23]],
      ids: [{ k: 'email', v: 'c.dubois@lumen-conseil.fr', ou: 'Pro · son profil Teams', boite: 'Pro', n: 23 }, { k: 'teams', v: 'Claire Dubois', ou: 'Lumen Conseil' }],
      profil: [['Poste', 'Cheffe de projet', 'son profil Teams'], ['Service', 'Conseil', 'son profil Teams'], ['Organisation', 'Lumen Conseil', 'son adresse e-mail', 'lumen']],
      sait: [{ t: 'Elle pilote la présentation de jeudi au client.', de: TEAMS, ou: 'dans le groupe « Projet Lumen »', sure: 0.9 },
        { t: 'Elle préfère les points courts, le matin.', de: TEAMS, ou: 'en tête-à-tête', sure: 0.6 },
        { t: 'Elle attend ta version corrigée, avec le budget dès la deuxième slide.', de: 'ses mails à Pro', ou: 'un mail, objet « Re: Présentation de jeudi »', sure: 0.85 }],
      croise: [['teams', 'Claire Dubois', 'tête-à-tête · 41 messages · 13:41', '#teams/d/claire'], ['teams', 'Projet Lumen', 'groupe · 23 messages · 10:02', '#teams/d/lumen'],
        ['mail', 'Re: Présentation de jeudi', 'Pro · 23 mails · 13:40', '#mail/lire/m-claire']],
      teams: '#teams/d/claire' },
    { id: 'lumen', org: true, nom: 'Lumen Conseil', c: 0, t: '13:41', idee: 'Ton employeur', src: [['teams', 214], ['pro', 120]],
      ids: [{ k: 'domain', v: 'lumen-conseil.fr', ou: 'Pro, Teams' }, { k: 'tenant', v: 'Lumen Conseil', ou: 'les profils Teams de ses personnes' },
        { k: 'email', v: 'accueil@lumen-conseil.fr', ou: 'Pro', boite: 'Pro', n: 4, generique: true },
        { k: 'email', v: 'noreply@lumen-conseil.fr', ou: 'Pro', boite: 'Pro', n: 38, generique: true }],
      membres: ['claire', 'karim', 'sophie', 'marc', 'nadia'], croise: [] },
    { id: 'karim', cle: 'karim', org: 'lumen', t: '12:58', idee: 'Développeur', src: [['teams', 18]],
      ids: [{ k: 'email', v: 'k.haddad@lumen-conseil.fr', ou: 'son profil Teams', teams: true }, { k: 'teams', v: 'Karim Haddad', ou: 'Lumen Conseil' }],
      profil: [['Poste', 'Développeur', 'son profil Teams'], ['Service', 'Produit', 'son profil Teams'], ['Organisation', 'Lumen Conseil', 'son profil Teams', 'lumen']],
      sait: [{ t: 'Il a mis la démo sur la préprod pour le client.', de: TEAMS, ou: 'dans le groupe « Projet Lumen »', sure: 0.85 },
        { t: 'Il attend ta relecture de sa PR sur l\'export CSV.', de: TEAMS, ou: 'en tête-à-tête', sure: 0.75 }],
      croise: [['teams', 'Karim Haddad', 'tête-à-tête · 1 message · hier', '#teams/d/karim'], ['teams', 'Projet Lumen', 'groupe · 2 messages · 12:58', '#teams/d/lumen'], ['teams', 'Café ☕', 'groupe', '#teams/d/cafe']],
      teams: '#teams/d/karim' },
    { id: 'sophie', cle: 'sophie', org: 'lumen', t: '12:40', idee: 'Consultante data', src: [['teams', 30], ['pro', 6], ['perso', 2], ['whatsapp', 4]],
      ids: [{ k: 'email', v: 's.laurent@lumen-conseil.fr', ou: 'Pro · son profil Teams', boite: 'Pro', n: 6 }, { k: 'email', v: 'sophie.laurent@gmail.com', ou: 'Perso', boite: 'Perso', n: 2 },
        { k: 'teams', v: 'Sophie Laurent', ou: 'Lumen Conseil' }, { k: 'phone', v: '+33 6 52 11 08 74', ou: 'WhatsApp, sur ton Pixel 7a' }],
      profil: [['Poste', 'Consultante data', 'son profil Teams'], ['Organisation', 'Lumen Conseil', 'son adresse e-mail', 'lumen']],
      sait: [{ t: 'Elle attend que tu valides les chiffres du T3 avant jeudi.', de: TEAMS, ou: 'dans le groupe « Projet Lumen »', sure: 0.9 }],
      croise: [['teams', 'Sophie Laurent', 'tête-à-tête · 1 message · 10:18', '#teams/d/sophie'], ['teams', 'Projet Lumen', 'groupe · 1 message · 12:40', '#teams/d/lumen'],
        ['mail', 'Planning de novembre', 'Pro · 6 mails · hier', '#mail'], ['chat', 'Sophie Laurent', 'WhatsApp · Pixel 7a · 4 messages', '#telephone']],
      teams: '#teams/d/sophie' },
    { id: 'maman', cle: 'maman', t: '12:40', idee: 'Ta mère', partage: true, refus: true, src: [['sms', 40], ['lea', 5], ['raconte', 6]],
      ids: [{ k: 'phone', v: '+33 6 08 41 77 93', ou: 'Messages, WhatsApp' }, { k: 'email', v: 'f.moreau56@orange.fr', ou: 'Boîte de Léa, partagée avec toi', boite: 'Boîte de Léa', n: 5 }],
      sait: [{ t: 'Elle t\'attend dimanche midi ; elle fait un rôti.', de: TEL, ou: 'en tête-à-tête', sure: 0.95 },
        { t: 'Elle prépare l\'anniversaire de votre père avec Léa.', de: 'ses mails à Boîte de Léa', ou: 'un mail, objet « Pour samedi 21 »', sure: 0.7, verrou: true }],
      croise: [['phone', 'Maman', 'Messages · 40 messages · 12:40', '#telephone/c/maman'], ['mail', 'Pour samedi 21', 'Boîte de Léa · 5 mails · il y a 4 j', '#mail']],
      message: '#telephone/c/maman' },
    { id: 'lea', cle: 'lea', t: '12:05', idee: 'Ta sœur', parle: true, src: [['whatsapp', 120], ['perso', 8], ['asso', 1], ['raconte', 12]],
      ids: [{ k: 'email', v: 'lea.moreau@gmail.com', ou: 'Perso', boite: 'Perso', n: 8 }, { k: 'email', v: 'moreau.lea@outlook.fr', ou: 'Rando Cassel', boite: 'Rando Cassel', n: 1 },
        { k: 'phone', v: '+33 6 71 20 33 58', ou: 'WhatsApp, Messages' }],
      sait: [{ t: 'Elle t\'a envoyé un colis à ne pas ouvrir : c\'est pour l\'anniversaire de votre père.', de: TEL, ou: 'en tête-à-tête', sure: 0.9 },
        { t: 'Elle prépare l\'anniversaire de votre père.', de: RACONTE }],
      croise: [['chat', 'Léa', 'WhatsApp · 120 messages · 11:02', '#telephone/c/lea'], ['mail', 'Les photos de dimanche', 'Perso · 8 mails · 12:05', '#mail/lire/m-lea']],
      message: '#telephone/c/lea' },
    { id: 'marc', cle: 'marc', org: 'lumen', t: '11:32', idee: 'Directeur des opérations', src: [['teams', 12], ['pro', 9]],
      ids: [{ k: 'email', v: 'm.delmas@lumen-conseil.fr', ou: 'Pro · son profil Teams', boite: 'Pro', n: 9 }, { k: 'teams', v: 'Marc Delmas', ou: 'Lumen Conseil' }],
      profil: [['Poste', 'Directeur des opérations', 'son profil Teams'], ['Organisation', 'Lumen Conseil', 'son adresse e-mail', 'lumen']],
      sait: [{ t: 'C\'est ton chef ; il valide les devis au-delà de 5 000 €.', de: 'ses mails à Pro', ou: 'un mail, objet « Devis n° 2026-114 »', sure: 0.8 },
        { t: 'Il veut reparler de la réunion vendredi.', de: TEAMS, ou: 'en tête-à-tête', sure: 0.85 }],
      croise: [['teams', 'Marc Delmas', 'tête-à-tête · 12 messages · 11:32', '#teams/d/marc'], ['teams', 'Réunion hebdo Lumen', 'groupe · lun.', '#teams/d/hebdo'],
        ['mail', 'Point d\'équipe déplacé à 16 h', 'Pro · 9 mails · 11:15', '#mail/lire/m-marc']],
      teams: '#teams/d/marc' },
    { id: 'garage', org: true, nom: 'Garage Martin', c: 2, t: '10:15', idee: 'Ton garagiste', src: [['sms', 5]],
      ids: [{ k: 'phone', v: '+33 3 20 45 18 60', ou: 'Messages' }], membres: [],
      croise: [['phone', 'Garage Martin', 'Messages · 5 messages · 10:15', '#telephone/c/garage']], message: '#telephone/c/garage' },
    { id: 'nadia', cle: 'nadia', org: 'lumen', t: '09:47', idee: 'Chargée des ressources humaines', src: [['teams', 6], ['pro', 1]],
      ids: [{ k: 'email', v: 'n.benkacem@lumen-conseil.fr', ou: 'Pro · son profil Teams', boite: 'Pro', n: 1 }, { k: 'teams', v: 'Nadia Benkacem', ou: 'Lumen Conseil' }],
      profil: [['Poste', 'Chargée des ressources humaines', 'son profil Teams'], ['Organisation', 'Lumen Conseil', 'son adresse e-mail', 'lumen']], sait: [],
      croise: [['teams', 'Café ☕', 'groupe · 1 message · 09:47', '#teams/d/cafe'], ['mail', 'Entretien annuel : choisis ton créneau', 'Pro · 1 mail · hier', '#mail/lire/m-nadia']],
      teams: '#teams/d/cafe' },
    { id: 'lefevre', org: true, nom: 'Lefèvre Rénovation', c: 5, t: '09:42', idee: 'Artisan', src: [['pro', 3]],
      ids: [{ k: 'domain', v: 'lefevre-renovation.fr', ou: 'Pro' }, { k: 'email', v: 'devis@lefevre-renovation.fr', ou: 'Pro', boite: 'Pro', n: 3, generique: true }], membres: [],
      croise: [['mail', 'Devis n° 2026-114 — rénovation salle de réunion', 'Pro · 3 mails · 09:42', '#mail/lire/m-lefevre']] },
    { id: 'camille', cle: 'camille', t: 'hier', idee: 'Ton amie', compte: true, src: [['asso', 6], ['whatsapp', 2]],
      ids: [{ k: 'email', v: 'camille.petit@laposte.net', ou: 'Rando Cassel', boite: 'Rando Cassel', n: 6 }, { k: 'phone_app', v: 'Camille', ou: 'ton carnet · groupe « Rando dimanche 🥾 »' }],
      sait: [{ t: 'Elle voudrait le tracé GPX du Mont des Cats pour sa montre.', de: 'ses mails à Rando Cassel', ou: 'un mail, objet « Le tracé du parcours ? »', sure: 0.9 }],
      croise: [['mail', 'Le tracé du parcours ?', 'Rando Cassel · 6 mails · hier', '#mail/lire/m-camille'], ['chat', 'Rando dimanche 🥾', 'groupe WhatsApp · 1 message', '#telephone/c/rando']] },
    { id: 'ines', nom: 'Inès', c: 6, t: 'il y a 5 j', idee: 'Une amie de Léa', src: [['raconte', 2]], ids: [],
      sait: [{ t: 'Elle cherche un covoiturage pour l\'anniversaire de votre père.', de: RACONTE }], croise: [] },
  ];

  // ── Les petites pièces ────────────────────────────────────────────────
  const etat = { q: '', sorte: 'tous', oublies: new Set(), faitsOublies: new Set() };
  const norm = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const estOrg = (c) => c.org === true;
  const nom = (c) => c.nom || A.who(c.cle).nom;
  const vivants = () => C.filter((c) => !etat.oublies.has(c.id));
  const trouve = (id) => vivants().find((c) => c.id === id);
  const orgDe = (c) => (c.org && !estOrg(c) ? C.find((o) => o.id === c.org) : null);
  const membres = (c) => (c.membres || []).map(trouve).filter(Boolean);
  const pluriel = (n, un, plus) => `${n} ${n > 1 ? plus : un}`;
  function avatar(c, taille) {
    const p = c.cle ? A.who(c.cle) : { nom: c.nom, c: c.c };
    return `<span class="av c${p.c}${taille ? ' ' + taille : ''}${estOrg(c) ? ' sq' : ''}">${h(A.initiales(nom(c)))}</span>`;
  }
  // Sa ligne : son poste et son organisation, ce qu'il est pour toi, ou, pour une organisation, combien de ses personnes.
  function ligneIdee(c) {
    if (estOrg(c)) { const n = membres(c).length; return n ? `Organisation · ${pluriel(n, 'personne', 'personnes')}` : `Organisation · ${c.idee}`; }
    const o = orgDe(c);
    return [c.idee, o && o.nom].filter(Boolean).join(' · ');
  }
  const ecrireA = (c) => (c.ids.find((x) => x.k === 'email' && !x.generique) || {}).v;
  const faits = (c) => (c.sait || []).map((f, i) => ({ ...f, i })).filter((f) => !etat.faitsOublies.has(`${c.id}:${f.i}`));
  // « d'après ses messages dans Teams · en tête-à-tête · sûre à 80 % » (noteSource du web)
  const source = (f) => [`d'après ${f.de}`, f.ou, typeof f.sure === 'number' ? `sûre à ${Math.round(f.sure * 100)} %` : ''].filter(Boolean).join(' · ');
  const discret = (c) => (c.partage
    ? `Ce que Mika sait de ${nom(c)} vient aussi d'un compte qu'on te partage ou d'un des siens : d'autres que toi peuvent le lire.`
    : `Ce que Mika sait de ${nom(c)} vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi.`);

  // ── La liste ──────────────────────────────────────────────────────────
  // Le champ cherche dans les noms et les identifiants ; un numéro se cherche comme il se range (06… → +336…).
  function cherche(c, q) {
    const chiffres = q.replace(/\D/g, '');
    if (/^[\d\s+().-]+$/.test(q) && chiffres.length >= 2) {
      const e164 = chiffres.startsWith('0') ? '33' + chiffres.slice(1) : chiffres;
      return c.ids.some((x) => x.k === 'phone' && x.v.replace(/\D/g, '').includes(e164));
    }
    const hay = norm([nom(c), c.idee, (orgDe(c) || {}).nom, ...c.ids.filter((x) => x.k !== 'phone_app').map((x) => x.v)].join(' '));
    return norm(q).split(/\s+/).filter(Boolean).every((m) => hay.includes(m));
  }
  const deSorte = (c, s) => s === 'tous' || (s === 'orgs') === estOrg(c);
  const visibles = () => vivants().filter((c) => deSorte(c, etat.sorte) && (!etat.q.trim() || cherche(c, etat.q.trim())));
  const pastilles = (c) => c.src.map(([k, n]) => `<span class="cx-src" title="${h(SOURCES[k][1])} · ${n}">${ico(SOURCES[k][0])}${n}</span>`).join('');

  function ligne(c) {
    return `<button class="li cx-row" type="button" data-go="#contacts/${c.id}">${avatar(c)}
      <span class="txt"><b>${h(nom(c))}</b><small>${h(ligneIdee(c))}</small><span class="cx-srcs">${pastilles(c)}</span></span>
      <span class="trail"><span class="t">${h(c.t)}</span></span></button>`;
  }
  function puces() {
    return [['tous', 'Tous'], ['personnes', 'Personnes'], ['orgs', 'Organisations']].map(([k, l]) => {
      const on = etat.sorte === k;
      return `<button type="button" class="chip${on ? ' on' : ''}" data-cx-sorte="${k}" aria-pressed="${on}">${on ? ico('check', 'xs') : ''}${l}<span class="n">${vivants().filter((c) => deSorte(c, k)).length}</span></button>`;
    }).join('');
  }
  function corpsListe() {
    const l = visibles();
    return l.length ? `${l.map(ligne).join('')}<p class="note">Ceux que Mika connaît pour toi : vus dans ton Teams, tes boîtes, ton téléphone, ou dont tu lui as parlé. Le dernier vu d'abord.</p>`
      : `<div class="cx-empty">${ico('search')}<b>Personne</b><p>Aucun contact ne correspond à « ${h(etat.q.trim())} ».</p></div>`;
  }

  function vueListe(tiroir) {
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'contacts', racine: true, back: '#plus',
      html: `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Contacts', sub: `${vivants().length} pour toi`, small: true })}
        <div class="cx-search"><label class="field">${ico('search', 'sm')}<input type="text" data-cx-q value="${h(etat.q)}" placeholder="Un nom, un e-mail, un numéro…" aria-label="Chercher un contact" autocomplete="off"></label></div>
        <div class="chips" data-cx-puces>${puces()}</div>
        <div class="body" style="padding-bottom:88px" data-cx-liste>${corpsListe()}</div>
        <button class="fab" type="button" data-go="#chat" data-snack="« Je te présente… » t'attend dans le champ du chat">${ico('user-plus')}Lui présenter quelqu'un</button>`,
      notes: {
        titre: 'Contacts (proposé)',
        reprend: [
          'Tous ceux que Mika connaît pour toi (ADR 0298) : vus dans ton Teams, tes boîtes, ton téléphone, ou dont tu lui as parlé, et leurs organisations. C\'est l\'écran Contacts du web, validé le 22 novembre, sur un téléphone : la liste, puis la fiche en page.',
          'Le champ cherche dans les noms et les identifiants : un e-mail, un nom Teams, un numéro (« 06 71 20 33 58 » trouve Léa, rangé en +33).',
          'Tous · Personnes · Organisations en puces, comme les filtres de Teams, avec leur nombre (sans la recherche, comme l\'API).',
          'Une ligne : l\'avatar (carré pour une organisation), le nom, son poste et son organisation ou ce qu\'il est pour toi, d\'où elle le connaît et combien, le dernier échange. Toucher ouvre sa fiche.',
          'Dans le tiroir, « Contacts » vient après Téléphone : il ferme les rubriques où l\'on parle aux gens et suit l\'ordre du web (Téléphone · Contacts). Dans l\'app : Chat · Projets · Mail · Teams · Carte · Téléphone · <b>Contacts</b> · Outils · Paramètres. Sans pastille : rien n\'y attend ta décision. Dans la variante barre, sous « Plus ».',
          'Une icône neuve, un carnet (« contacts » dans le sprite), pour ne pas la confondre avec Teams.',
          '« Lui présenter quelqu\'un » ouvre le chat, la phrase à compléter : une fiche naît de ce que tu lui racontes.',
        ],
        trancher: [
          '« Contacts » après Téléphone (ici), juste après Teams (à côté de Mail et Teams), ou Carte descendue après Contacts, comme le web ?',
          'L\'ordre : le dernier vu d\'abord (le web, l\'API), ou alphabétique avec les lettres, comme l\'appli Contacts d\'Android ?',
          'Les sources en petites icônes et nombres sous chaque nom : lisibles, ou trop chargées (ne garder que la plus forte) ?',
          'La feuille des boîtes de Mail garde sa ligne « Contacts », qui mène maintenant ici : à garder, ou à retirer puisque le tiroir l\'a ?',
        ],
      },
      after() {
        // la route du tiroir ouvert : le geste de ☰ (variante tiroir seulement)
        if (tiroir) { const b = document.querySelector('#app [data-drawer]'); if (b) b.click(); }
      },
    };
  }

  // ── La fiche ──────────────────────────────────────────────────────────
  function tete(c) {
    const o = orgDe(c);
    const lien = o ? `<button class="cx-link" type="button" data-go="#contacts/${o.id}">${h(o.nom)}</button>` : '';
    const idee = estOrg(c) ? (membres(c).length ? `Organisation · ${pluriel(membres(c).length, 'personne', 'personnes')} parmi tes contacts` : 'Organisation') : c.idee;
    const tag = c.parle ? '<span class="tag ok">parle aussi à Mika</span>' : c.compte ? '<span class="tag">a un compte</span>' : '';
    const a = ecrireA(c);
    const actes = [a && ['mail', 'Écrire', `#mail/ecrire/a/${a}`, true], c.teams && ['teams', 'Teams', c.teams], c.message && ['phone', 'Message', c.message]].filter(Boolean);
    return `<div class="cx-hero">${avatar(c, 'xl')}<h1>${h(nom(c))}</h1><p>${h(idee || '')}${idee && lien ? ' · ' : ''}${lien}</p>${tag}</div>
      ${actes.length ? `<div class="cx-acts">${actes.map(([i, l, r, main]) => `<button type="button" data-go="${h(r)}"${main ? ' class="main"' : ''}><span class="ci">${ico(i)}</span>${l}</button>`).join('')}</div>` : ''}
      <div class="cx-facts">${c.src.map(([k, n]) => `<span class="tag">${ico(SOURCES[k][0])}${h(SOURCES[k][1])} · ${n}</span>`).join('')}<span class="tag">${ico('clock')}dernier échange ${h(c.t)}</span></div>`;
  }
  function identifie(c) {
    if (!c.ids.length) return `<div class="set-h">Ce qui l'identifie</div><p class="note" style="padding:4px 28px 0">Aucun moyen de communication : tu lui en as seulement parlé.</p>`;
    return `<div class="set-h">Ce qui l'identifie</div><div class="set-group">${c.ids.map((x) => {
      const [i, l] = SORTES[x.k];
      // une adresse générique le dit dans sa ligne (pas en étiquette au bout : elle mangerait l'adresse)
      const sous = [x.generique ? 'Adresse générique' : l, x.ou, x.generique ? 'sans personne derrière' : ''].filter(Boolean).join(' · ');
      const ecrire = x.k === 'email' && !x.generique;
      return `<${ecrire ? `button type="button" data-go="#mail/ecrire/a/${h(x.v)}"` : 'div'} class="li cx-id"><span class="lead">${ico(i)}</span>
        <span class="txt"><b>${h(x.v)}</b><small class="two">${h(sous)}</small></span>${ecrire ? `<span class="cx-go" title="Écrire à cette adresse">${ico('send', 'sm')}</span>` : ''}</${ecrire ? 'button' : 'div'}>`;
    }).join('')}</div>`;
  }
  function personnes(c) {
    const m = membres(c);
    if (!estOrg(c) || !m.length) return '';
    return `<div class="set-h">Ses personnes parmi tes contacts</div><div class="set-group">${m.map((p) => `<button class="li" type="button" data-go="#contacts/${p.id}"><span class="lead">${avatar(p, 'sm')}</span>
      <span class="txt"><b>${h(nom(p))}</b><small>${h(p.idee)}</small></span><span class="trail">${h(p.t)}</span></button>`).join('')}</div>`;
  }
  function sait(c) {
    if (estOrg(c)) return '';   // une organisation n'écrit pas : pas de portrait (le serveur, lot 6)
    const fs = faits(c);
    const profil = (c.profil || []).map(([l, v, de, lie]) => `<div class="cx-kv"><span>${h(l)}</span><span>${lie ? `<button class="cx-link" type="button" data-go="#contacts/${lie}">${h(v)}</button>` : `<b>${h(v)}</b>`}<small>d'après ${h(de)}</small></span></div>`);
    const notes = fs.map((f) => `<div class="cx-fait"><span class="txt"><p>${h(f.t)}</p><small>${h(source(f))}</small></span>
      <button class="ibtn cx-x" type="button" data-sheet="cx-fait" data-fait="${f.i}" title="${f.verrou ? 'D\'un compte qui n\'est pas à toi' : 'Qu\'elle l\'oublie'}" aria-label="${f.verrou ? 'Pourquoi elle ne peut pas l\'oublier d\'ici' : 'Qu\'elle oublie ce fait'}">${ico(f.verrou ? 'lock' : 'x', 'xs')}</button></div>`);
    const tout = [...profil, ...notes];
    return `<div class="set-h mk">${ico('sparkle')}Ce que Mika en sait</div>${tout.length ? `<div class="set-group mk">${tout.join('')}</div>` : '<p class="note" style="padding:4px 28px 0">Rien de plus que ce qui l\'identifie.</p>'}`;
  }
  function croise(c) {
    if (!c.croise.length) return '';
    return `<div class="set-h">Où vous vous croisez</div><div class="set-group">${c.croise.map(([i, l, d, r]) => `<button class="li" type="button" data-go="${h(r)}"><span class="lead box">${ico(i)}</span>
      <span class="txt"><b>${h(l)}</b><small>${h(d)}</small></span>${ico('chev-right', 'sm')}</button>`).join('')}</div>`;
  }

  const NOTES_FICHE = {
    claire: 'Claire : une collègue vue dans Teams et au courrier ; son profil Teams donne son poste, son service, son adresse.',
    sophie: 'Sophie a deux adresses : « Écrire » prend la première ; ✉ au bout de chacune écrit à celle-là.',
    lea: 'Léa a un compte et a déjà écrit à Mika : « parle aussi à Mika ». Ce que tu lui as raconté d\'elle n\'a pas de confiance (ce n\'est pas une lecture).',
    camille: '« a un compte » : Camille a un compte, mais n\'a jamais écrit à Mika.',
    maman: 'Maman : une part vient de la boîte de Léa, partagée avec toi. La phrase sous la fiche le dit, le fait lu là a un cadenas au lieu de ×, et « Oublier ce contact » est refusé, avec les mots du serveur.',
    ines: 'Inès : seulement ce que tu lui as raconté. Aucun moyen de la joindre, donc ni Écrire, ni Teams, ni Message.',
    thomas: 'Thomas n\'est qu\'un nom de ton carnet dans un groupe WhatsApp : « Contact WhatsApp », sans numéro (le serveur ne dit pas la clé du téléphone), et pas de « Message » sans tête-à-tête.',
    karim: 'Karim : tu ne le connais que par Teams. Son adresse vient de son profil : « Écrire » marche quand même.',
  };
  function notesFiche(c) {
    if (estOrg(c)) {
      return { titre: `Contacts · ${h(nom(c))}`,
        reprend: ['Ses personnes parmi tes contacts : celles dont tu vois la preuve (une adresse de son domaine, un profil Teams qui dit l\'entreprise).',
          'Ce qui l\'identifie : son domaine, son organisation Teams, ses adresses génériques (sans personne derrière), son numéro.',
          'Pas de « Ce que Mika en sait » : une organisation n\'écrit pas, elle n\'a pas de portrait (le serveur, lot 6).',
          'Pas d\'« Écrire » : le serveur ne le propose que vers l\'adresse d\'une personne. Une adresse générique s\'écrit depuis Mail, où elle est proposée, marquée.',
          'Où vous vous croisez, la phrase de confidentialité et « Oublier ce contact », comme pour une personne.'],
        trancher: ['« Écrire » vers son adresse générique depuis sa fiche (devis@…, accueil@…) : à ajouter, ou Mail suffit ?',
          'Ses personnes avant ce qui l\'identifie (ici), ou après ?'] };
    }
    return { titre: `Contacts · ${h(nom(c))}`,
      reprend: [
        'En tête : l\'avatar, le nom, le poste et l\'organisation (qui ouvre sa fiche), « parle aussi à Mika » ou « a un compte ».',
        'Écrire (Mail, l\'adresse posée), Teams (votre discussion), Message (la conversation du téléphone) : seulement ceux qui existent, comme le serveur les donne (<code>write</code>, <code>teams</code>, <code>message</code>).',
        'D\'où elle le connaît et combien, le dernier échange.',
        'Ce qui l\'identifie : la sorte, la valeur, d\'où elle la tient ; une adresse générique le dit. Un appui long copie.',
        'Ce que Mika en sait, en rose : son profil (poste, service, organisation), puis ce qu\'elle a compris de ses derniers messages, d\'où et sûre à combien ; × l\'oublie, après une feuille qui confirme.',
        'Où vous vous croisez : chaque ligne ouvre l\'écran de la maquette (la discussion Teams, le mail, la conversation du téléphone).',
        'La phrase de confidentialité, puis « Oublier ce contact », confirmé dans une feuille.',
        NOTES_FICHE[c.id],
      ].filter(Boolean),
      trancher: [
        'Les trois boutons ronds sous le nom (comme Contacts de Google), ou une barre en bas comme la liseuse de Mail ?',
        '« Ce que Mika en sait » avant « Ce qui l\'identifie » ? Sur un téléphone, c\'est peut-être ce qu\'on vient chercher.',
        'Un oubli refusé (Maman) : le bouton reste et sa feuille dit pourquoi (ici), ou il disparaît, la phrase à sa place ?',
        'Dans la feuille d\'un refus, « Ouvrir la console » pour une opératrice : utile, ou à laisser au web ?',
      ] };
  }

  function vueFiche(c, args) {
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'contacts', back: '#contacts',
      html: `${A.top({ title: '', back: true, face: false, actions: [A.act('more', 'Plus', 'data-menu="cx"')] })}
        <div class="body cx-card" data-cx-fiche="${c.id}">${tete(c)}${personnes(c)}${identifie(c)}${sait(c)}${croise(c)}
          <p class="note cx-privacy">${ico('lock', 'xs')}<span>${h(discret(c))}</span></p>
          <div style="padding:8px 16px 28px"><button class="btn danger outlined block" type="button" data-sheet="cx-oublier">${ico('trash')}Oublier ce contact</button></div>
        </div>`,
      notes: notesFiche(c),
      after() {
        if (args[1] === 'oublier') A.sheets['cx-oublier']();
        if (args[1] === 'fait') A.sheets['cx-fait']({ dataset: { fait: args[2] || '0' } });
      },
    };
  }

  A.ecran('contacts', (args) => {
    const c = args[0] && args[0] !== 'tiroir' ? trouve(args[0]) : null;
    return c ? vueFiche(c, args) : vueListe(args[0] === 'tiroir');
  });

  // ── Les feuilles : oublier un fait, oublier le contact ─────────────────
  const courant = () => trouve((document.querySelector('[data-cx-fiche]') || {}).dataset?.cxFiche);
  const boutons = (ok) => `<div class="cx-sheet-btns"><button class="btn text" type="button" data-close>${ok ? 'Annuler' : 'Compris'}</button>${ok || ''}</div>`;
  const console_ = () => (D.moi.operatrice ? '<button class="btn text" type="button" data-close data-snack="Maquette : le navigateur s\'ouvrirait sur l\'annuaire de la console">Ouvrir la console</button>' : '');
  A.sheets['cx-fait'] = (x) => {
    const c = courant();
    const f = c && faits(c).find((y) => String(y.i) === String(x.dataset.fait));
    if (!f) return;
    if (f.verrou) {
      A.sheet('Oublier ce fait', `<p class="cx-sheet-p"><q>${h(f.t)}</q></p><p class="cx-sheet-p">${h(NOT_YOUR_FACT)}</p>
        <div class="cx-sheet-btns">${console_()}<button class="btn text" type="button" data-close>Compris</button></div>`);
      return;
    }
    A.sheet('Oublier ce fait ?', `<p class="cx-sheet-p">Mika oubliera ce qu'elle avait compris : <q>${h(f.t)}</q></p>
      <p class="cx-sheet-p">Elle ne le réapprendra pas, même dit autrement ; les messages restent où ils sont.</p>
      ${boutons(`<button class="btn danger filled" type="button" data-cx-oublie-fait="${c.id}:${f.i}">${ico('x')}Oublier</button>`)}`);
  };
  A.sheets['cx-oublier'] = () => {
    const c = courant();
    if (!c) return;
    if (c.refus) {
      A.sheet(`Oublier ${h(nom(c))}`, `<p class="cx-sheet-p">${h(NOT_ALL_YOURS)}</p><div class="cx-sheet-btns">${console_()}<button class="btn text" type="button" data-close>Compris</button></div>`);
      return;
    }
    A.sheet(`Oublier ${h(nom(c))} ?`, `<p class="cx-sheet-p">Mika oubliera ${h(nom(c))} : sa fiche, et ce que Teams, le courrier, ton téléphone et sa mémoire en gardaient. Les messages restent dans leurs boîtes.</p>
      ${boutons(`<button class="btn danger filled" type="button" data-cx-oublie="${c.id}">${ico('trash')}Oublier</button>`)}`);
  };
  A.menus.cx = () => {
    const c = courant();
    const a = c && ecrireA(c);
    return [{ ico: 'chat', l: 'En parler à Mika', go: '#chat' }, a ? { ico: 'copy', l: 'Copier son adresse', snack: `Copié : ${a}` } : null, '-',
      { ico: 'trash', l: 'Oublier ce contact', sheet: 'cx-oublier', cls: 'danger' }].filter(Boolean);
  };

  // ── Écrire : les destinataires proposés depuis tous tes contacts ───────
  // Une ligne par adresse (Léa en a deux : deux choix) ; une adresse générique est proposée, marquée.
  const adresses = () => vivants().flatMap((c) => c.ids.filter((x) => x.k === 'email').map((x) => ({ c, x })));
  const parAdresse = (a) => adresses().find((e) => e.x.v.toLowerCase() === String(a).toLowerCase());
  const rang = (c) => C.indexOf(c);
  function proposer(q, pris) {
    const mots = norm(q).split(/\s+/).filter(Boolean);
    return adresses().filter(({ c, x }) => !pris.has(x.v.toLowerCase()) && mots.every((m) => norm([nom(c), (orgDe(c) || {}).nom, x.v].join(' ')).includes(m)))
      .sort((a, b) => (Number(!!a.x.generique) - Number(!!b.x.generique)) || (rang(a.c) - rang(b.c)) || ((b.x.n || 0) - (a.x.n || 0)))
      .slice(0, 6);
  }
  function ligneProp(e, champ) {
    const { c, x } = e;
    const indice = x.teams ? ['teams', 'Teams', 'son profil'] : ['mail', x.boite, pluriel(x.n, 'mail', 'mails')];
    const apres = x.generique ? '<span class="tag">générique</span>' : `<span class="org">${h((orgDe(c) || {}).nom || c.idee)}</span>`;
    return `<button class="cx-ac-row" type="button" data-cx-pick="${h(x.v)}" data-cx-champ="${champ}">${avatar(c, 'sm')}
      <span class="txt"><span class="nm"><b>${h(nom(c))}</b>${apres}</span><small>${h(x.v)}</small></span>
      <span class="cx-hint"><span>${ico(indice[0])}${h(indice[1])}</span><span>${h(indice[2])}</span></span></button>`;
  }
  function puce(a) {
    const e = parAdresse(a);
    const label = e ? nom(e.c) : a;
    const av = e ? avatar(e.c, 'xs') : `<span class="av xs grp">${ico('at', 'xxs')}</span>`;
    return `<span class="cx-chip" data-cx-adr="${h(a)}" title="${h(a)}">${av}<span>${h(label)}</span><button type="button" data-cx-retire aria-label="Retirer ${h(label)}">${ico('x')}</button></span>`;
  }
  const champ = (k, list) => `<span class="cx-rcpt" data-cx-rcpt="${k}">${list.map(puce).join('')}<input data-cx-ac="${k}" placeholder="${list.length || k !== 'a' ? '' : 'Un nom, une adresse'}" autocomplete="off" aria-label="${k === 'a' ? 'À' : k === 'cc' ? 'Cc' : 'Cci'}"></span>`;
  function montrer(input) {
    const scr = input.closest('.scr');
    scr.querySelectorAll('.cx-ac').forEach((x) => x.remove());
    const q = input.value.trim();
    if (!q) return;
    const pris = new Set([...scr.querySelectorAll('[data-cx-adr]')].map((x) => x.dataset.cxAdr.toLowerCase()));
    const res = proposer(q, pris);
    input.closest('.line-field').insertAdjacentHTML('afterend', `<div class="cx-ac" role="listbox" data-cx-res="${res.length}">${res.length
      ? res.map((e) => ligneProp(e, input.dataset.cxAc)).join('') : `<div class="cx-ac-none">Aucun contact : « ${h(q)} » sera pris tel quel.</div>`}</div>`);
  }
  function choisir(scr, k, a) {
    const box = scr.querySelector(`[data-cx-rcpt="${k}"]`);
    if (!box || !a) return;
    const input = box.querySelector('input');
    input.insertAdjacentHTML('beforebegin', puce(a));
    input.value = ''; input.placeholder = '';
    scr.querySelectorAll('.cx-ac').forEach((x) => x.remove());
    input.focus();
  }

  function poseEcrire(scr) {
    if (scr.querySelector('[data-cx-rcpt]')) return;
    const route = decodeURIComponent(location.hash).replace(/^#mail\/ecrire\/?/, '').split('/');
    const ligneA = [...scr.querySelectorAll('.line-field')].find((l) => (l.firstElementChild || {}).textContent === 'À');
    const mid = ligneA && ligneA.querySelector(':scope > .row.wrap.grow');
    if (!mid) return;
    const demo = route[0] === 'suggestions';
    const init = route[0] === 'reponse' || route[0] === 'retoucher' ? ['c.dubois@lumen-conseil.fr'] : route[0] === 'a' && route[1] ? [route[1]] : demo ? ['julien.roux@proton.me'] : [];
    mid.outerHTML = champ('a', init);
    const fl = ligneA.querySelector(':scope > svg.ico');
    if (fl) fl.outerHTML = `<button class="ibtn cx-cc" type="button" data-cx-cc aria-label="Cc et Cci" title="Cc et Cci">${ico(demo ? 'chev-up' : 'chev-down', 'sm')}</button>`;
    ligneA.insertAdjacentHTML('afterend', `<div class="line-field" data-cx-ccrow${demo ? '' : ' hidden'}><span>Cc</span>${champ('cc', [])}</div><div class="line-field" data-cx-ccrow${demo ? '' : ' hidden'}><span>Cci</span>${champ('cci', [])}</div>`);
    if (demo) {
      const de = scr.querySelector('.line-field button span');
      if (de) de.textContent = 'Perso · adrien.moreau@outlook.fr';
      const objet = [...scr.querySelectorAll('.line-field')].find((l) => (l.firstElementChild || {}).textContent === 'Objet');
      if (objet) objet.querySelector('input').value = 'Covoiturage pour samedi';
      const input = scr.querySelector('[data-cx-ac="a"]');
      input.value = 'le';
      montrer(input);
    }
    const notes = document.getElementById('pn-notes');
    if (notes && !notes.querySelector('[data-cx-note]')) {
      notes.insertAdjacentHTML('beforeend', `<div data-cx-note><h4>Proposé : les destinataires depuis tes contacts</h4><ul>
        <li>Taper dans À, Cc ou Cci propose tes contacts (<code>/api/moi/contacts?q=</code>), plus seulement tes correspondants du courrier : Karim, que tu ne connais que par Teams, vient avec l'adresse de son profil (tape « ka »).</li>
        <li>Une ligne par adresse : Léa en a deux, ce sont deux choix. À droite, d'où vient l'adresse et combien de mails.</li>
        <li>L'adresse générique d'une organisation (devis@, accueil@) est proposée, marquée « générique », avec l'avatar carré ; après les personnes.</li>
        <li>Les destinataires choisis en puces, × pour retirer ; Retour arrière dans un champ vide retire la dernière. La flèche ouvre Cc et Cci.</li>
        <li>« Écrire » depuis une fiche arrive ici, l'adresse posée (<code>#mail/ecrire/a/&lt;adresse&gt;</code>).</li></ul>
        <h4 class="q">À trancher</h4><ol>
        <li>Les correspondants du courrier seulement (aujourd'hui, <code>/mail/contacts</code> : reçus, envoyés), tous tes contacts (ici), ou les deux : ceux à qui tu écris d'abord, puis les autres ?</li>
        <li>Une personne à deux adresses : la puce dit son nom seul (comme Gmail), ou son nom et le domaine (« Léa · gmail ») ?</li>
        <li>Les adresses génériques : proposées et marquées (ici), ou seulement celles auxquelles tu as déjà écrit (noreply@ ne devrait peut-être jamais venir) ?</li>
        <li>Côté serveur : la liste des contacts suffit-elle (quatre identifiants au plus, sans dire lesquels sont génériques), ou une route qui rend une ligne par adresse ?</li></ol></div>`);
    }
  }

  // Plus (variante barre) : une ligne Contacts après Téléphone.
  function posePlus(scr) {
    const tel = scr.querySelector('.li[data-go="#telephone"]');
    if (!tel || scr.querySelector('.li[data-go="#contacts"]')) return;
    tel.insertAdjacentHTML('afterend', `<button class="li" type="button" data-go="#contacts"><span class="lead box">${ico('contacts')}</span><span class="txt"><b>Contacts</b><small>tous ceux qu'elle connaît pour toi</small></span></button>`);
  }
  // Le tiroir : « Contacts » après Téléphone.
  function poseTiroir() {
    const d = document.querySelector('#overlay .drawer');
    if (!d || d.querySelector('[data-go="#contacts"]')) return;
    const tel = d.querySelector('.dr-item[data-go="#telephone"]');
    if (tel) tel.insertAdjacentHTML('afterend', `<button class="dr-item${A.state.nav === 'contacts' ? ' on' : ''}" type="button" data-go="#contacts">${ico('contacts')}Contacts</button>`);
  }
  // Mail › la feuille des boîtes : sa ligne « Contacts » mène ici.
  const boites = A.sheets.boites;
  A.sheets.boites = (x) => {
    boites(x);
    const b = document.querySelector('#overlay .sheet [data-snack="Maquette : les contacts"]');
    if (b) {
      b.removeAttribute('data-close'); b.removeAttribute('data-snack'); b.dataset.go = '#contacts';
      b.querySelector('.txt').insertAdjacentHTML('beforeend', '<small>tous ceux qu\'elle connaît pour toi</small>');
    }
  };

  function pose() {
    const scr = document.querySelector('#app .scr');
    if (!scr) return;
    if (scr.dataset.screen === 'mail' && /^#mail\/ecrire/.test(location.hash)) poseEcrire(scr);
    if (scr.dataset.screen === 'plus') posePlus(scr);
  }

  // ── Les gestes ─────────────────────────────────────────────────────────
  document.addEventListener('input', (e) => {
    const t = e.target;
    if (t.matches('[data-cx-q]')) {
      etat.q = t.value;
      const l = document.querySelector('[data-cx-liste]');
      if (l) { l.innerHTML = corpsListe(); l.scrollTop = 0; }
    }
    if (t.matches('[data-cx-ac]')) montrer(t);
  });
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!t.matches('[data-cx-ac]')) return;
    const scr = t.closest('.scr');
    if (e.key === 'Backspace' && !t.value) {
      const last = t.parentNode.querySelectorAll('.cx-chip');
      if (last.length) { last[last.length - 1].remove(); if (last.length === 1 && t.dataset.cxAc === 'a') t.placeholder = 'Un nom, une adresse'; }
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      const first = scr.querySelector('.cx-ac [data-cx-pick]');
      const v = t.value.trim();
      if (first) choisir(scr, t.dataset.cxAc, first.dataset.cxPick);
      else if (v) choisir(scr, t.dataset.cxAc, v);
    }
  });
  document.addEventListener('click', (e) => {
    const t = e.target;
    let x;
    if ((x = t.closest('[data-cx-sorte]'))) {
      etat.sorte = x.dataset.cxSorte;
      document.querySelector('[data-cx-puces]').innerHTML = puces();
      const l = document.querySelector('[data-cx-liste]');
      l.innerHTML = corpsListe(); l.scrollTop = 0;
      return;
    }
    if ((x = t.closest('[data-cx-pick]'))) { choisir(x.closest('.scr'), x.dataset.cxChamp, x.dataset.cxPick); return; }
    if ((x = t.closest('[data-cx-retire]'))) {
      const box = x.closest('.cx-rcpt');
      x.closest('.cx-chip').remove();
      if (!box.querySelector('.cx-chip') && box.dataset.cxRcpt === 'a') box.querySelector('input').placeholder = 'Un nom, une adresse';
      return;
    }
    if ((x = t.closest('[data-cx-cc]'))) {
      const rows = x.closest('.scr').querySelectorAll('[data-cx-ccrow]');
      const open = rows[0].hidden;
      rows.forEach((r) => { r.hidden = !open; });
      x.querySelector('use').setAttribute('href', open ? '#i-chev-up' : '#i-chev-down');
      return;
    }
    if ((x = t.closest('[data-cx-oublie-fait]'))) {
      etat.faitsOublies.add(x.dataset.cxOublieFait);
      A.closeAll();
      if (/\/fait\//.test(location.hash)) history.replaceState(null, '', location.hash.replace(/\/fait\/.*$/, ''));
      A.render();
      A.snack('Oublié : elle ne le réapprendra pas');
      return;
    }
    if ((x = t.closest('[data-cx-oublie]'))) {
      const c = trouve(x.dataset.cxOublie);
      etat.oublies.add(x.dataset.cxOublie);
      A.closeAll();
      if (A.state.depth > 0) A.back(); else location.replace('#contacts');
      A.snack(`Mika a oublié ${c ? nom(c) : 'ce contact'}`);
    }
  });

  addEventListener('DOMContentLoaded', () => {
    new MutationObserver(pose).observe(document.getElementById('app'), { childList: true });
    new MutationObserver(poseTiroir).observe(document.getElementById('overlay'), { childList: true });
    pose();
    poseTiroir();
  });

  A.index('Contacts (proposé)', [['Liste', '#contacts'], ['Tiroir', '#contacts/tiroir'], ['Claire', '#contacts/claire'], ['Sophie, deux adresses', '#contacts/sophie'],
    ['Léa', '#contacts/lea'], ['Inès', '#contacts/ines'], ['Maman, oubli refusé', '#contacts/maman'], ['Lumen Conseil', '#contacts/lumen'],
    ['Oublier un fait', '#contacts/claire/fait/1'], ['Oublier Claire', '#contacts/claire/oublier'],
    ['Écrire à Claire', '#mail/ecrire/a/c.dubois@lumen-conseil.fr'], ['Écrire · suggestions', '#mail/ecrire/suggestions']]);
})();
