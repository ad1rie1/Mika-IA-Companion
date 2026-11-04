/* Mail : un client complet sur toutes tes boîtes. Le moteur et la console savent déjà presque tout faire (boîtes,
   dossiers, filtres, liseuse, images masquées, pièces gardées, brouillons de Mika et leurs décisions, ADR 0169-0175) ;
   rien n'en est exposé à un client aujourd'hui : voir les notes. « Non lu » est le tien ; ce qu'elle a lu se dit à part. */
(function () {
  const { h, ico, av } = M;
  const D = M.D;
  const B = Object.fromEntries(D.filRouge.boites.map((b) => [b.id, b]));
  const PARTAGEE = { id: 'lea', nom: 'Boîte de Léa', adresse: 'lea.moreau@gmail.com', couleur: 7, de: 'lea', lecture: true };
  const DOSSIERS = [['inbox', 'Réception', 'inbox'], ['sent', 'Envoyés', 'send'], ['drafts', 'Brouillons', 'file'], ['archive', 'Archives', 'archive'],
    ['junk', 'Indésirables', 'alert'], ['trash', 'Corbeille', 'trash']];
  const AUTRES = { pro: [['clients', 'Clients', 'folder']], asso: [['autres', 'Autres', 'folder']] };

  const moi = (b) => ({ nom: 'Adrien Moreau', adr: B[b] ? B[b].adresse : 'adrien.moreau@outlook.fr' });
  const P = (cle, adr) => ({ nom: M.who(cle).nom, adr, cle });
  const MAILS = [
    { id: 'm-claire', boite: 'pro', dossier: 'inbox', de: P('claire', 'c.dubois@lumen-conseil.fr'), objet: 'Re: Présentation de jeudi', t: '13:40', quand: 'aujourd\'hui 13:40',
      nonlu: true, lu: '13:54', important: true, attendue: true, fil: 3, brouillon: 'm-brouillon-claire',
      sait: 'Claire valide la trame. Une seule demande : un chiffre de budget dès la slide 2, avant jeudi. Ce n\'est pas un reproche.',
      corps: ['Salut Adrien,', 'Merci pour la trame, elle me va très bien. Une seule remarque : la partie budget arrive trop tard. Tu pourrais mettre un chiffre dès la deuxième slide ? Le client regarde ça en premier.', 'Pour le reste, on garde l\'ordre.', 'Bonne journée,<br>Claire'],
      cite: 'Le 3 nov. 2026 à 18:12, Adrien Moreau a écrit : Voici la trame pour jeudi, dis-moi ce que tu en penses.' },
    { id: 'm-marc', boite: 'pro', dossier: 'inbox', de: P('marc', 'm.delmas@lumen-conseil.fr'), objet: 'Point d\'équipe déplacé à 16 h', t: '11:15', quand: 'aujourd\'hui 11:15',
      nonlu: true, important: true, signale: true, lu: '11:16', sait: 'Le point d\'équipe de ce matin glisse à 16 h, même salle. Elle te l\'a dit à 11 h 17.',
      corps: ['Bonjour à tous,', 'Le point de ce matin glisse à 16 h, même salle.', 'Marc'] },
    { id: 'm-lefevre', boite: 'pro', dossier: 'inbox', de: { nom: 'Lefèvre Rénovation', adr: 'devis@lefevre-renovation.fr' }, objet: 'Devis n° 2026-114 — rénovation salle de réunion', t: '09:42', quand: 'aujourd\'hui 09:42',
      attendue: true, lu: '13:31', brouillon: 'd-lefevre', pieces: [['devis-2026-114.pdf', 'PDF', '212 Ko']],
      sait: 'Un devis de 16 740 € TTC, 1 240 € au-dessus du budget. La main-d\'œuvre n\'a pas de quantité. Elle l\'a comparé pour toi en mode pro.',
      corps: ['Bonjour Monsieur Moreau,', 'Veuillez trouver ci-joint notre devis pour la rénovation de la salle de réunion du 2e étage, valable 30 jours.', 'Nous restons à votre disposition pour toute question.', 'Cordialement,<br>Paul Lefèvre<br>Lefèvre Rénovation · 03 20 55 41 08'] },
    { id: 'm-nadia', boite: 'pro', dossier: 'inbox', de: P('nadia', 'n.benkacem@lumen-conseil.fr'), objet: 'Entretien annuel : choisis ton créneau', t: 'hier', quand: 'hier 17:02',
      suivi: true, corps: ['Bonjour Adrien,', 'Les créneaux des entretiens annuels sont ouverts jusqu\'au 15 novembre. Choisis le tien dans l\'agenda partagé.', 'Nadia'] },
    { id: 'm-teams', boite: 'pro', dossier: 'archive', de: { nom: 'Microsoft Teams', adr: 'noreply@email.teams.microsoft.com' }, objet: 'Vous avez manqué des messages dans Projet Lumen', t: 'hier', quand: 'hier 19:30',
      archivee: true, lu: 'hier 19:31', corps: ['Vous avez 3 messages non lus dans Projet Lumen.'] },
    { id: 'm-lea', boite: 'perso', dossier: 'inbox', de: P('lea', 'lea.moreau@gmail.com'), objet: 'Les photos de dimanche', t: '12:05', quand: 'aujourd\'hui 12:05',
      nonlu: true, pieces: [['IMG_2041.jpg', 'JPEG', '2,4 Mo', true], ['IMG_2047.jpg', 'JPEG', '1,9 Mo', true]],
      corps: ['Coucou !', 'Je t\'ai mis les meilleures, il y en a une de toi avec le chien 😄', 'Bises,<br>Léa'] },
    { id: 'm-train', boite: 'perso', dossier: 'inbox', de: { nom: 'Rail Connect', adr: 'noreply@rail-connect.example' }, objet: 'Votre e-billet Lille Flandres → Paris Nord du 12 novembre', t: '08:30', quand: 'aujourd\'hui 08:30',
      images: true, pieces: [['e-billet-QZ7K4P.pdf', 'PDF', '96 Ko']],
      corps: ['<b>Votre voyage du jeudi 12 novembre</b>', 'Lille Flandres 07:16 → Paris Nord 08:18 · voiture 14, place 82', 'Présentez ce billet à bord, sur votre téléphone ou imprimé.'] },
    { id: 'm-banque', boite: 'perso', dossier: 'inbox', de: { nom: 'Banque du Nord', adr: 'alertes@banque-du-nord.example' }, objet: 'Alerte : prélèvement de 89,90 €', t: '08:03', quand: 'aujourd\'hui 08:03',
      lu: '08:10', corps: ['Un prélèvement de 89,90 € (Mutuelle Horizon) a été effectué sur votre compte.'] },
    { id: 'm-julien', boite: 'asso', dossier: 'inbox', de: P('julien', 'julien.roux@proton.me'), objet: 'Re: Rando dimanche — covoiturage', t: '10:20', quand: 'aujourd\'hui 10:20',
      repondu: true, fil: 4, corps: ['Je peux prendre 3 personnes, départ 8 h 30 place du Concert.', 'Julien'] },
    { id: 'm-camille', boite: 'asso', dossier: 'inbox', de: P('camille', 'camille.petit@laposte.net'), objet: 'Le tracé du parcours ?', t: 'hier', quand: 'hier 19:47',
      nonlu: true, attendue: true, pieces: [], corps: ['Hello, tu aurais le fichier GPX du Mont des Cats ? Je voudrais le mettre sur ma montre.', 'Merci !<br>Camille'] },
    { id: 'm-inscr', boite: 'asso', dossier: 'autres', de: { nom: 'Inscriptions Asso', adr: 'contact@inscriptions.example' }, objet: '3 nouvelles inscriptions : Sortie Monts de Flandre', t: 'hier', quand: 'hier 09:12',
      lu: 'hier 09:15', rangee: 'Autres', corps: ['3 nouvelles personnes inscrites à « Sortie Monts de Flandre » (dimanche 8 novembre).'] },
    { id: 'm-lea-colis', boite: 'lea', dossier: 'inbox', de: { nom: 'Atelier Bois & Co', adr: 'commandes@atelier-bois.example' }, objet: 'Votre colis est en route — commande n° 4471', t: '09:05', quand: 'aujourd\'hui 09:05',
      corps: ['Bonjour Léa,', 'Votre commande n° 4471 a été expédiée à l\'adresse d\'Adrien Moreau, à Lille. Livraison prévue jeudi.', 'L\'équipe Atelier Bois & Co'] },
  ];
  const BROUILLONS = [
    { id: 'm-brouillon-claire', boite: 'pro', objet: 'Re: Présentation de jeudi', a: 'Claire Dubois <c.dubois@lumen-conseil.fr>', enReponse: 'm-claire', t: '13:55', quand: 'aujourd\'hui 13:55',
      etat: ['warn', 'attend ton accord'], pourquoi: 'Tu le lui as demandé dans le chat à 13:52.', voix: 'à ta place',
      texte: 'Salut Claire,\n\nMerci pour ta relecture. Bonne remarque : je remonte le budget en slide 2 et je t\'envoie la version corrigée ce soir.\n\nBonne journée,\nAdrien\n\n-- \nAdrien Moreau · Lumen Conseil' },
    { id: 'd-lefevre', boite: 'pro', objet: 'Re: Devis n° 2026-114 — rénovation salle de réunion', a: 'Lefèvre Rénovation <devis@lefevre-renovation.fr>', enReponse: 'm-lefevre', t: '13:36', quand: 'aujourd\'hui 13:36',
      etat: ['warn', 'attend ton accord'], completer: true, pourquoi: 'Tu le lui as demandé en mode pro, dans le fil « Devis Lefèvre ».', voix: 'à ta place',
      texte: 'Bonjour Monsieur Lefèvre,\n\nMerci pour votre devis. Avant d\'aller plus loin, pourriez-vous nous détailler le poste « main-d\'œuvre » (nombre d\'heures et taux horaire) ?\n\nNous pourrions démarrer le [À COMPLÉTER : date de début souhaitée].\n\nBien cordialement,\nAdrien Moreau' },
    { id: 'd-camille', boite: 'asso', objet: 'Re: Le tracé du parcours ?', a: 'Camille Petit <camille.petit@laposte.net>', enReponse: 'm-camille', t: '08:02', quand: 'aujourd\'hui 08:02',
      etat: ['info', 'à relire'], pourquoi: 'D\'elle-même : son tri y attendait une réponse (6 brouillons par jour au plus).', voix: 'en assistante',
      texte: 'Bonjour Camille,\n\nJe vous réponds pour Adrien : le fichier GPX du Mont des Cats est sur le site de l\'association, page « Parcours ». Il vous le renvoie ce soir sinon.\n\nBonne journée,\nMika' },
    { id: 'd-ancien', boite: 'pro', objet: 'Re: Planning de novembre', a: 'Sophie Laurent <s.laurent@lumen-conseil.fr>', t: 'hier', quand: 'hier 16:40', etat: ['ok', 'parti · retouché par toi'], voix: 'à ta place',
      texte: 'Salut Sophie,\n\nLe planning me va, je prends le lundi 16.\n\nAdrien' },
  ];
  const CONTACTS = [
    { cle: 'claire', adr: 'c.dubois@lumen-conseil.fr', recus: 14, envoyes: 9, dernier: 'il y a 40 min', groupe: 'travail' },
    { cle: 'marc', adr: 'm.delmas@lumen-conseil.fr', recus: 22, envoyes: 11, dernier: 'il y a 3 h', groupe: 'travail' },
    { cle: 'sophie', adr: 's.laurent@lumen-conseil.fr', recus: 8, envoyes: 7, dernier: 'hier', groupe: 'travail' },
    { cle: 'karim', adr: 'k.haddad@lumen-conseil.fr', recus: 5, envoyes: 3, dernier: 'lun.', groupe: 'travail' },
    { cle: 'nadia', adr: 'n.benkacem@lumen-conseil.fr', recus: 4, envoyes: 1, dernier: 'hier', groupe: 'travail' },
    { cle: 'julien', adr: 'julien.roux@proton.me', recus: 6, envoyes: 5, dernier: 'il y a 3 h', groupe: 'proches' },
    { cle: 'lea', adr: 'lea.moreau@gmail.com', recus: 4, envoyes: 2, dernier: 'il y a 2 h', groupe: 'proches' },
    { cle: 'camille', adr: 'camille.petit@laposte.net', recus: 3, envoyes: 1, dernier: 'hier', groupe: 'proches' },
    { nom: 'Lefèvre Rénovation', adr: 'devis@lefevre-renovation.fr', recus: 2, envoyes: 0, dernier: 'il y a 4 h', groupe: 'autres' },
    { nom: 'Rail Connect', adr: 'noreply@rail-connect.example', recus: 12, envoyes: 0, dernier: 'il y a 6 h', groupe: 'autres' },
  ];

  const etat = { vue: 'tout:inbox', choisi: 'm-claire', filtre: 'tout', coches: new Set(), images: new Set(), contact: 'claire', groupeC: 'tous', mobileLecture: false, repondre: false,
    ouvertes: new Set(['pro']), q: '', qc: '', tous: false, prerempli: null };
  const boiteDe = (id) => (id === 'lea' ? PARTAGEE : B[id]);

  // ── La colonne des boîtes ────────────────────────────────────────────
  const nonlus = (b, d) => MAILS.filter((m) => (b === 'tout' ? m.boite !== 'lea' : m.boite === b) && m.dossier === (d || 'inbox') && m.nonlu).length;
  function dossiers() {
    const lien = (vue, lib, icone, n, cls) => `<button type="button" class="${etat.vue === vue ? 'on' : ''}${cls ? ' ' + cls : ''}" data-vue="${vue}">${ico(icone)}<span class="ellipsis">${h(lib)}</span>${n ? `<span class="cnt">${n}</span>` : ''}</button>`;
    const boite = (b) => {
      const ouverte = etat.ouvertes.has(b.id);
      const dossiersB = b.lecture ? [['inbox', 'Réception', 'inbox']] : DOSSIERS.concat(AUTRES[b.id] || []);
      return `<div class="mb-box${ouverte ? ' open' : ''}"><button type="button" class="mb-name" data-boite="${b.id}" title="${h(b.adresse)}">${ico(ouverte ? 'chev-down' : 'chev-right', 'xs')}<span class="dot c${b.couleur}"></span><b>${h(b.nom)}</b>
        ${b.lecture ? `<span class="tag" title="Partagée avec toi par ${h(M.who(b.de).nom)}">${ico('lock', 'xs')}lecture</span>` : b.id === 'asso' ? `<a class="mb-err" href="#parametres/comptes-mail" title="Dernier relevé il y a 2 h : mot de passe refusé">${ico('alert', 'xs')}</a>` : nonlus(b.id) ? `<span class="cnt">${nonlus(b.id)}</span>` : ''}</button>
        ${ouverte ? `<div class="nav-list">${dossiersB.map(([d, lib, i]) => lien(`${b.id}:${d}`, lib, i, d === 'inbox' ? nonlus(b.id) : 0)).join('')}</div>` : ''}</div>`;
    };
    return `<div class="pane-scroll mb-scroll">
      <div class="nav-list">${lien('tout:inbox', 'Toutes les réceptions', 'inbox', nonlus('tout'))}${lien('tout:traiter', 'À traiter', 'clock', MAILS.filter((m) => m.attendue && m.boite !== 'lea').length)}
        ${lien('tout:suivis', 'Suivis', 'star', MAILS.filter((m) => m.suivi).length)}</div>
      <div class="group-label">Mika</div>
      <div class="nav-list">${lien('mika:brouillons', 'Ses brouillons', 'pen', BROUILLONS.filter((b) => b.etat[1] !== 'parti · retouché par toi').length, 'mika-link')}${lien('mika:lus', 'Lu par Mika', 'eye', 0, 'mika-link')}</div>
      <div class="group-label">Tes boîtes<span class="cnt">${D.filRouge.boites.length}</span></div>
      ${D.filRouge.boites.map(boite).join('')}
      <div class="group-label">Partagée avec toi</div>${boite(PARTAGEE)}
      <a class="mb-add" href="#parametres/comptes-mail">${ico('plus', 'sm')}Ajouter un compte</a>
    </div>`;
  }

  // ── La liste ─────────────────────────────────────────────────────────
  function mailsDeLaVue() {
    const [b, d] = etat.vue.split(':');
    let l;
    if (b === 'mika') l = d === 'brouillons' ? BROUILLONS : MAILS.filter((m) => m.lu);
    else if (b === 'tout') l = d === 'traiter' ? MAILS.filter((m) => m.attendue && m.boite !== 'lea') : d === 'suivis' ? MAILS.filter((m) => m.suivi) : MAILS.filter((m) => m.boite !== 'lea' && m.dossier === 'inbox');
    else if (d === 'drafts') l = BROUILLONS.filter((x) => x.boite === b);
    else l = MAILS.filter((m) => m.boite === b && m.dossier === d);
    if (etat.q) {
      const q = M.norm(etat.q);
      l = l.filter((m) => M.norm([m.objet, m.de ? m.de.nom + ' ' + m.de.adr : m.a, (m.corps || []).join(' '), m.texte || ''].join(' ')).includes(q));
    }
    if (etat.filtre === 'nonlus') l = l.filter((m) => m.nonlu);
    if (etat.filtre === 'pieces') l = l.filter((m) => m.pieces && m.pieces.length);
    if (etat.filtre === 'mika') l = l.filter((m) => m.lu || m.brouillon || m.etat);
    return l;
  }
  function titreVue() {
    const [b, d] = etat.vue.split(':');
    if (b === 'mika') return d === 'brouillons' ? 'Ses brouillons' : 'Lu par Mika';
    if (b === 'tout') return { inbox: 'Toutes les réceptions', traiter: 'À traiter', suivis: 'Suivis' }[d];
    const bo = boiteDe(b), dd = DOSSIERS.concat(AUTRES[b] || []).find((x) => x[0] === d);
    return `${bo.nom} · ${dd ? dd[1] : d}`;
  }
  function ligne(m) {
    if (m.etat) return `<button class="li mrow draft" type="button" data-mail="${m.id}" aria-selected="${etat.choisi === m.id}">
      <span class="mrow-av">${av('mika', 'sm')}</span><span class="li-main"><span class="li-top"><span class="li-title">À ${h(m.a.split(' <')[0])}</span><time>${h(m.t)}</time></span>
      <span class="li-sub">${h(m.objet)}</span><span class="li-snip">${h(m.texte.split('\n\n')[1] || '')}</span>
      <span class="li-marks"><span class="tag ${m.etat[0]}">${h(m.etat[1])}</span>${m.completer ? '<span class="tag danger">à compléter</span>' : ''}<span class="mk quiet">${ico('pen')}${h(m.voix)}</span></span></span></button>`;
    const bo = boiteDe(m.boite);
    const plusieurs = etat.vue.startsWith('tout') || etat.vue.startsWith('mika');
    return `<div class="li mrow${m.nonlu ? ' unread' : ''}" role="button" tabindex="0" data-mail="${m.id}" aria-selected="${etat.choisi === m.id}">
      <label class="mrow-check" title="Choisir"><input type="checkbox" data-coche="${m.id}"${etat.coches.has(m.id) ? ' checked' : ''}></label>
      <span class="mrow-av">${av(m.de.cle ? m.de.cle : { nom: m.de.nom }, 'sm')}</span>
      <span class="li-main"><span class="li-top"><span class="li-title">${h(m.de.nom)}</span>${m.pieces && m.pieces.length ? ico('clip', 'xs') : ''}${m.suivi ? `<span class="star">${ico('star', 'xs')}</span>` : ''}<time>${h(m.t)}</time></span>
        <span class="li-sub">${h(m.objet)}</span><span class="li-snip">${h(m.corps[1] || m.corps[0]).replace(/<[^>]+>/g, ' ')}</span>
        <span class="li-marks">${plusieurs ? `<span class="box-mark"><span class="dot c${bo.couleur}"></span>${h(bo.nom)}</span>` : ''}
          ${m.important ? '<span class="tag danger">important</span>' : ''}${m.attendue ? '<span class="tag warn">réponse attendue</span>' : ''}
          ${m.lu ? `<span class="mk" title="Lu par Mika à ${h(m.lu)}">${ico('eye')}lu par elle</span>` : ''}${m.brouillon ? `<span class="mk">${ico('pen')}brouillon prêt</span>` : ''}
          ${m.signale ? `<span class="mk quiet">${ico('bell')}signalé</span>` : ''}${m.archivee ? `<span class="mk quiet">${ico('archive')}archivé par elle</span>` : ''}${m.repondu ? '<span class="tag">répondu</span>' : ''}</span></span></div>`;
  }
  function liste() {
    const l = mailsDeLaVue();
    const sel = etat.coches.size;
    return `<div class="pane-head ml-head">${sel ? `<b>${sel} choisi${sel > 1 ? 's' : ''}</b><span class="grow"></span>
        <button class="btn xs" type="button" data-groupe="lu">${ico('check', 'xs')}Lu</button><button class="btn xs" type="button" data-groupe="archiver">${ico('archive', 'xs')}Archiver</button>
        <button class="btn xs" type="button" data-groupe="corbeille">${ico('trash', 'xs')}</button><button class="btn xs ghost" type="button" data-groupe="aucun">Annuler</button>`
      : `<button class="btn sm ghost folder-pick" type="button" data-dossiers title="Boîtes et dossiers">${ico('folder', 'sm')}</button>
        <h2 class="ellipsis">${h(titreVue())}</h2><span class="cnt">${l.length}</span><span class="grow"></span>
        <button class="btn icon ghost sm" type="button" title="Relever maintenant" data-relever>${ico('refresh', 'sm')}</button>`}</div>
      <div class="ml-tools"><label class="search grow">${ico('search', 'sm')}<input type="search" placeholder="Chercher dans tes mails : des mots, un expéditeur…" data-mq value="${h(etat.q)}"></label></div>
      <div class="ml-filters"><div class="seg" role="group" aria-label="Filtrer">${[['tout', 'Tout'], ['nonlus', 'Non lus'], ['pieces', 'Avec pièces'], ['mika', 'Où Mika est passée']].map(([k, lib]) => `<button type="button" data-filtre="${k}" aria-pressed="${etat.filtre === k}">${lib}</button>`).join('')}</div></div>
      <div class="pane-scroll" data-liste>${l.length ? l.map(ligne).join('') : `<div class="empty">${ico('inbox')}<b>Rien ici</b><p>Aucun mail pour ce filtre.</p></div>`}</div>`;
  }

  // ── La liseuse ───────────────────────────────────────────────────────
  function liseuse() {
    const m = MAILS.find((x) => x.id === etat.choisi) || BROUILLONS.find((x) => x.id === etat.choisi);
    if (!m) return `<div class="empty">${ico('mail')}<b>Choisis un mail</b><p>Il s'ouvre ici, à côté de la liste.</p></div>`;
    return m.etat ? liseuseBrouillon(m) : liseuseMail(m);
  }
  function liseuseMail(m) {
    const bo = boiteDe(m.boite), lecture = !!bo.lecture;
    const dis = lecture ? ' disabled title="Lecture seule : boîte partagée avec toi"' : '';
    const imagesMasquees = m.images && !etat.images.has(m.de.adr);
    return `<div class="rd">
      ${lecture ? `<div class="rd-shared">${ico('lock', 'sm')}<span><b>Boîte de Léa Moreau</b>, partagée avec toi en lecture seule : tu ne peux ni répondre ni ranger.</span></div>` : ''}
      <div class="rd-head"><h2>${h(m.objet)}</h2>
        <div class="row wrap">${m.important ? '<span class="tag danger">important</span>' : ''}${m.attendue ? '<span class="tag warn">réponse attendue</span>' : ''}${m.suivi ? '<span class="tag accent">★ suivi</span>' : ''}${m.fil ? `<span class="tag">${ico('threads', 'xs')}${m.fil} mails dans le fil</span>` : ''}</div></div>
      <div class="rd-from">${av(m.de.cle ? m.de.cle : { nom: m.de.nom }, 'lg')}<div class="grow"><b>${h(m.de.nom)}</b> <span class="muted">&lt;${h(m.de.adr)}&gt;</span>
        <div class="small muted">à ${h(lecture ? 'Léa Moreau' : 'toi')} &lt;${h(lecture ? bo.adresse : bo.adresse)}&gt; · <span class="box-mark"><span class="dot c${bo.couleur}"></span>${h(bo.nom)}</span> · ${h(m.quand)}</div></div></div>
      <div class="rd-actions">
        <button class="btn sm" type="button" data-act="repondre"${dis}>${ico('reply', 'sm')}Répondre</button>
        <button class="btn sm rd-sec" type="button" data-act="tous"${dis} title="Répondre à tous">${ico('reply-all', 'sm')}<span class="lbl">Répondre à tous</span></button>
        <button class="btn sm rd-sec" type="button" data-act="transferer"${dis} title="Transférer">${ico('forward', 'sm')}<span class="lbl">Transférer</span></button>
        <button class="btn sm mika" type="button" data-act="preremplir"${dis}>${ico('sparkle', 'sm')}Préremplir avec Mika</button>
        <span class="grow"></span>
        <button class="btn sm icon ghost" type="button" data-act="archiver" title="Archiver"${dis}>${ico('archive', 'sm')}</button>
        <button class="btn sm icon ghost" type="button" data-act="nonlu" title="${m.nonlu ? 'Marquer comme lu' : 'Marquer non lu'}"${dis}>${ico(m.nonlu ? 'check' : 'mail', 'sm')}</button>
        <button class="btn sm icon ghost" type="button" data-act="suivre" title="Suivre"${dis}>${ico('star', 'sm')}</button>
        <button class="btn sm icon ghost" type="button" data-act="corbeille" title="Corbeille"${dis}>${ico('trash', 'sm')}</button>
        <button class="btn sm icon ghost" type="button" data-act="plus" title="Plus">${ico('more', 'sm')}</button></div>
      ${m.sait || m.lu ? `<div class="mika-note rd-note">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('eye', 'xs')}Ce qu'elle en sait${m.lu ? ` · lu par elle à ${h(m.lu)}` : ''}</div>
        ${m.sait ? `<span>« ${h(m.sait)} »</span>` : ''}
        ${m.brouillon ? `<div class="mn-actions"><button class="btn xs mika" type="button" data-ouvrir="${m.brouillon}">${ico('pen', 'xs')}Relire son brouillon</button>
          <button class="btn xs ghost" type="button" data-act="rediger">Lui demander une autre version</button></div>` : ''}</div></div>` : ''}
      ${imagesMasquees ? `<div class="rd-images">${ico('image', 'sm')}<span>Ses images distantes sont masquées : les charger dit à l'expéditeur que tu as ouvert ce mail.</span>
        <button class="btn xs" type="button" data-images="fois">Les afficher cette fois</button><button class="btn xs ghost" type="button" data-images="toujours">Toujours pour cet expéditeur</button></div>` : ''}
      <div class="rd-frame${m.images ? ' html' : ''}" title="Le mail s'affiche dans un cadre isolé (ADR 0169)">
        ${m.images ? `<div class="rd-banner${imagesMasquees ? ' masked' : ''}">${imagesMasquees ? ico('image') : '<b>Rail Connect</b>'}</div>` : ''}
        ${m.corps.map((p) => `<p>${p}</p>`).join('')}${m.cite ? `<blockquote>${h(m.cite)}</blockquote>` : ''}</div>
      ${m.pieces && m.pieces.length ? `<div class="rd-pieces"><h4>Pièces jointes <span class="cnt">${m.pieces.length}</span></h4><div class="row wrap">${m.pieces.map(([n, k, t, img]) =>
        `<div class="piece">${img ? '<span class="piece-thumb"></span>' : `<span class="piece-ico">${h(k)}</span>`}<span class="piece-main"><b>${h(n)}</b><small>${h(k)} · ${h(t)}</small></span>
          <button class="btn xs icon ghost" type="button" title="Aperçu">${ico('eye', 'xs')}</button><button class="btn xs icon ghost" type="button" title="Télécharger">${ico('download', 'xs')}</button></div>`).join('')}</div></div>` : ''}
      ${lecture ? '' : etat.repondre ? reponseEnPlace(m) : `<button class="rd-reply-stub" type="button" data-act="repondre">${ico('reply', 'sm')}Répondre à ${h(m.de.nom.split(' ')[0])}…</button>`}
    </div>`;
  }
  function reponseEnPlace(m) {
    const cc = etat.tous ? [['sophie', 'Sophie Laurent'], ['karim', 'Karim Haddad']] : [];
    const pre = etat.prerempli;
    return `<div class="composer rd-reply${pre ? ' filled' : ''}"><div class="rd-reply-head"><span class="small muted">De</span><select data-de>${D.filRouge.boites.map((b) => `<option${b.id === m.boite ? ' selected' : ''}>${h(b.nom)} &lt;${h(b.adresse)}&gt;</option>`).join('')}</select>
        <span class="small muted">À</span><span class="chip">${av(m.de.cle ? m.de.cle : { nom: m.de.nom }, 'xs')}${h(m.de.nom)}<button type="button" title="Retirer">${ico('x', 'xs')}</button></span>
        ${cc.length ? `<span class="small muted">Cc</span>${cc.map(([k, n]) => `<span class="chip">${av(k, 'xs')}${h(n)}<button type="button" title="Retirer">${ico('x', 'xs')}</button></span>`).join('')}` : ''}</div>
      ${pre ? `<div class="tm-filled">${ico('sparkle', 'xs')}${h(pre.lib)} — relis avant d'envoyer<button type="button" class="btn xs ghost" data-act="vider">Effacer</button></div>` : ''}
      <textarea rows="5" data-rd-txt placeholder="Ta réponse…">${pre ? h(pre.texte) : ''}</textarea>
      <div class="cmp-bar"><button class="btn icon ghost sm" type="button" title="Joindre">${ico('clip')}</button>
        <button class="btn sm mika" type="button" data-act="preremplir">${ico('sparkle', 'sm')}<span class="lbl">Préremplir avec Mika</span></button>
        <label class="small muted row cite" title="Citer le mail auquel tu réponds"><input type="checkbox" checked><span class="lbl">citer le mail</span></label><span class="grow"></span>
        <button class="btn sm ghost" type="button" data-act="fermer-rep">Annuler</button>
        <button class="btn sm primary" type="button" data-act="envoyer">${ico('send', 'sm')}<span class="lbl">Envoyer</span></button></div></div>`;
  }
  function liseuseBrouillon(b) {
    const bo = boiteDe(b.boite);
    const texte = h(b.texte).replace(/\[À COMPLÉTER : ([^\]]+)\]/g, '<mark class="completer">[À COMPLÉTER : $1]</mark>');
    return `<div class="rd">
      <div class="rd-head"><h2>${h(b.objet)}</h2><div class="row wrap"><span class="tag ${b.etat[0]}">${h(b.etat[1])}</span>${b.completer ? '<span class="tag danger">à compléter</span>' : ''}<span class="mk">${ico('pen')}rédigé par Mika · ${h(b.voix)}</span></div></div>
      <div class="mika-note rd-note">${av('mika', 'sm')}<div class="mn-body"><div class="mn-title">${ico('sparkle', 'xs')}Pourquoi elle l'a préparé</div><span>${h(b.pourquoi || 'Tu l\'as retouché, puis il est parti.')}</span></div></div>
      <h4 class="rd-h4">Ce qui partira</h4>
      <dl class="kv rd-kv"><dt>De</dt><dd>${b.voix === 'en assistante' ? `Mika (pour Adrien Moreau)` : 'Adrien Moreau'} &lt;${h(bo.adresse)}&gt;</dd><dt>À</dt><dd>${h(b.a)}</dd><dt>Objet</dt><dd>${h(b.objet)}</dd>
        ${b.enReponse ? `<dt>En réponse à</dt><dd><button class="linkish" type="button" data-ouvrir="${b.enReponse}">${h((MAILS.find((x) => x.id === b.enReponse) || {}).objet || '')}</button></dd>` : ''}</dl>
      <pre class="rd-exact">${texte}</pre>
      ${b.completer ? `<div class="rd-block">${ico('alert', 'sm')}Il ne peut pas partir tel quel : il reste des passages à compléter. Retouche-le.</div>` : ''}
      ${b.etat[1].startsWith('parti') ? '' : `<div class="rd-decide"><button class="btn sm ghost danger" type="button" data-decide="refuser">Refuser</button>
        <button class="btn sm" type="button" data-decide="reprendre">${ico('refresh', 'sm')}Lui demander de le reprendre</button>
        <button class="btn sm" type="button" data-decide="retoucher">${ico('pen', 'sm')}Retoucher</button><span class="grow"></span>
        <button class="btn sm primary" type="button" data-decide="envoyer"${b.completer ? ' disabled' : ''}>${ico('send', 'sm')}Envoyer</button></div>
      <p class="small muted">Rien ne part sans toi. Ce que tu changes, elle l'apprend : sa version et la tienne.</p>`}
    </div>`;
  }

  // ── Écrire ───────────────────────────────────────────────────────────
  function ecrire(pre) {
    const p = pre || {};
    const el = M.modal({ titre: p.titre || 'Nouveau message', taille: 'wide',
      corps: `<div class="cmp-form">
        <label class="cf-row"><span>De</span><select>${D.filRouge.boites.map((b) => `<option${b.id === (p.boite || 'pro') ? ' selected' : ''}>${h(b.nom)} &lt;${h(b.adresse)}&gt;</option>`).join('')}
          <option disabled>Boîte de Léa — lecture seule</option></select></label>
        <div class="cf-row"><span>À</span><div class="rcpt" data-rcpt="a">${(p.a || []).map(puce).join('')}<input data-ac placeholder="Un nom ou une adresse…" autocomplete="off"></div>
          <span class="row"><button class="btn xs ghost" type="button" data-cc>Cc</button><button class="btn xs ghost" type="button" data-cci>Cci</button></span></div>
        <div class="cf-row" data-ccrow hidden><span>Cc</span><div class="rcpt" data-rcpt="cc"><input data-ac placeholder="Copie…" autocomplete="off"></div></div>
        <div class="cf-row" data-ccirow hidden><span>Cci</span><div class="rcpt" data-rcpt="cci"><input data-ac placeholder="Copie cachée…" autocomplete="off"></div></div>
        <div class="ac-pop" data-acpop hidden></div>
        <label class="cf-row"><span>Objet</span><input data-objet value="${h(p.objet || '')}" placeholder="Objet"></label>
        <div class="tm-filled" data-filled hidden>${ico('sparkle', 'xs')}Prérempli par Mika — relis avant d'envoyer</div>
        <textarea rows="10" data-corps placeholder="Ton message…">${h(p.corps || '')}</textarea>
        <div class="dropzone">${ico('upload', 'sm')}Glisse des fichiers ici, ou <button class="linkish" type="button" data-joindre>choisis-les</button> · 25 Mo par pièce</div>
        <div class="row wrap" data-pieces></div></div>`,
      pied: `<button class="btn mika" type="button" data-rediger>${ico('sparkle', 'sm')}Préremplir avec Mika</button><span class="grow"></span>
        <button class="btn" type="button" data-close>Enregistrer le brouillon</button><button class="btn primary" type="button" data-envoyer-mail>${ico('send', 'sm')}Envoyer</button>` });
    const pop = el.querySelector('[data-acpop]'), form = el.querySelector('.cmp-form');
    let cible = null, res = [], sel = 0;
    const montrer = () => {
      pop.innerHTML = res.length ? res.map((c, k) => `<button type="button" class="ac-item${k === sel ? ' on' : ''}" data-pick="${h(c.adr)}">${av(c.cle ? c.cle : { nom: c.nom }, 'sm')}
        <span><b>${h(c.nom || M.who(c.cle).nom)}</b><small>${h(c.adr)} · ${c.recus} reçus · ${c.envoyes} envoyés</small></span></button>`).join('')
        : `<div class="ac-none">Aucun contact : « ${h(cible.value)} » sera pris tel quel.</div>`;
      // Sous le champ, dans le repère du formulaire (qui est position: relative).
      const r = cible.closest('.rcpt').getBoundingClientRect(), base = form.getBoundingClientRect();
      pop.style.left = r.left - base.left + 'px'; pop.style.top = r.bottom - base.top + 4 + 'px'; pop.style.width = Math.min(420, r.width) + 'px';
      pop.hidden = false;
    };
    const choisirC = (c) => { cible.insertAdjacentHTML('beforebegin', puce(c)); cible.value = ''; pop.hidden = true; cible.focus(); };
    el.addEventListener('input', (e) => {
      if (!e.target.matches('[data-ac]')) return;
      cible = e.target;
      const q = M.norm(e.target.value.trim());
      if (!q) { pop.hidden = true; return; }
      res = CONTACTS.filter((c) => M.norm((c.nom || M.who(c.cle).nom) + ' ' + c.adr).includes(q)).slice(0, 6); sel = 0;
      montrer();
    });
    el.addEventListener('keydown', (e) => {
      if (!e.target.matches('[data-ac]') || pop.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + res.length) % Math.max(1, res.length); montrer(); }
      if (e.key === 'Enter' && res[sel]) { e.preventDefault(); choisirC(res[sel]); }
      if (e.key === 'Escape') { e.stopPropagation(); pop.hidden = true; }
    });
    el.addEventListener('focusout', (e) => { if (e.target.matches('[data-ac]')) setTimeout(() => { if (!pop.contains(document.activeElement)) pop.hidden = true; }, 150); });
    M.on(el, '[data-pick]', 'mousedown', (e, b) => { e.preventDefault(); choisirC(CONTACTS.find((x) => x.adr === b.dataset.pick)); });
    M.on(el, '[data-cc]', 'click', () => { el.querySelector('[data-ccrow]').hidden = false; });
    M.on(el, '[data-cci]', 'click', () => { el.querySelector('[data-ccirow]').hidden = false; });
    M.on(el, '.chip button', 'click', (e, b) => b.closest('.chip').remove());
    M.on(el, '[data-joindre]', 'click', () => { el.querySelector('[data-pieces]').insertAdjacentHTML('beforeend', `<span class="chip">${ico('file', 'xs')}support-lumen-v4.pdf<span class="muted">1,2 Mo</span><button type="button">${ico('x', 'xs')}</button></span>`); });
    M.on(el, '[data-rediger]', 'click', () => {
      const t = el.querySelector('[data-corps]'), o = el.querySelector('[data-objet]').value || 'ton message';
      M.mika.typing(true);
      setTimeout(() => {
        M.mika.typing(false);
        t.value = `Bonjour,\n\nJe reviens vers vous au sujet de ${o.replace(/^(re|tr) ?: ?/i, '').toLowerCase()}. [À COMPLÉTER : ce que tu veux dire]\n\nBien cordialement,\nAdrien Moreau`;
        el.querySelector('[data-filled]').hidden = false; t.classList.add('filled');
      }, 900);
    });
    M.on(el, '[data-envoyer-mail]', 'click', () => { M.fermerModal(); M.toast('Envoyé. Elle le sait.', { ico: 'send' }); });
  }
  function puce(c) { const nom = c.nom || M.who(c.cle).nom; return `<span class="chip" title="${h(c.adr)}">${av(c.cle ? c.cle : { nom }, 'xs')}${h(nom)}<button type="button" title="Retirer">${ico('x', 'xs')}</button></span>`; }

  function demanderReponse(m) {
    const el = M.modal({ titre: 'Lui demander une réponse', taille: 'narrow',
      corps: `<p class="small text-2" style="margin-bottom:10px">À « ${h(m.objet)} », de ${h(m.de.nom)}. Elle la préparera à son prochain moment de travail ; tu la relis avant qu'elle parte.</p>
        <label class="field"><span>Ce que tu veux y dire</span><textarea rows="4" placeholder="« dis-lui oui pour jeudi, et que j'envoie la version corrigée ce soir »"></textarea></label>`,
      pied: `<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn mika" type="button" data-ok>${ico('sparkle', 'sm')}Lui demander</button>` });
    el.querySelector('[data-ok]').addEventListener('click', () => { M.fermerModal(); M.toast('Demandé : son brouillon arrivera dans « Ses brouillons ».', { mika: true }); });
  }

  // ── Les contacts ─────────────────────────────────────────────────────
  function vueContacts() {
    const l = CONTACTS.filter((c) => (etat.groupeC === 'tous' || c.groupe === etat.groupeC)
      && (!etat.qc || M.norm((c.nom || M.who(c.cle).nom) + ' ' + c.adr).includes(M.norm(etat.qc))));
    const c = CONTACTS.find((x) => (x.cle || x.adr) === etat.contact) || l[0];
    const p = c.cle ? M.who(c.cle) : { nom: c.nom, moyens: [['mail', c.adr]] };
    const lib = { mail: ['mail', 'Mail'], tel: ['phone', 'Téléphone'], whatsapp: ['chat', 'WhatsApp'], teams: ['teams', 'Teams'] };
    const recents = MAILS.filter((m) => m.de.adr === c.adr).slice(0, 4);
    return `<div class="split ct-split${etat.mobileContact ? ' lire' : ''}">
      <aside class="pane"><div class="pane-head"><label class="search grow">${ico('search', 'sm')}<input type="search" placeholder="Chercher un contact" data-qc value="${h(etat.qc)}"></label></div>
        <div class="ml-tools"><div class="seg" role="group">${[['tous', 'Tous'], ['travail', 'Travail'], ['proches', 'Proches'], ['autres', 'Autres']].map(([k, lb]) => `<button type="button" data-groupec="${k}" aria-pressed="${etat.groupeC === k}">${lb}</button>`).join('')}</div></div>
        <div class="pane-scroll">${l.map((x) => { const n = x.nom || M.who(x.cle).nom; return `<button class="li" type="button" data-contact="${x.cle || x.adr}" aria-selected="${(x.cle || x.adr) === (c.cle || c.adr)}">
          ${av(x.cle ? x.cle : { nom: n }, 'sm')}<span class="li-main"><span class="li-top"><span class="li-title">${h(n)}</span><time>${h(x.dernier)}</time></span><span class="li-snip">${h(x.adr)}</span></span></button>`; }).join('')}</div></aside>
      <section class="pane ct-pane"><div class="pane-scroll ct-card"><button class="btn sm ghost mobile-back" type="button" data-retour-c>${ico('chev-left', 'sm')}Contacts</button>
        <div class="ct-head">${av(c.cle ? c.cle : { nom: p.nom }, 'xl')}<div class="grow"><h2>${h(p.nom)}</h2><p class="text-2">${h(p.titre || p.lien || 'correspondant')}</p></div>
          <button class="btn sm" type="button" data-modifier-contact>${ico('pen', 'sm')}Modifier</button>
          <button class="btn primary sm" type="button" data-ecrire-a="${h(c.adr)}">${ico('send', 'sm')}Écrire</button>
          ${c.cle && p.moyens.some((x) => x[0] === 'teams') ? `<a class="btn sm" href="#teams/discussions/${h(c.cle)}">${ico('teams', 'sm')}Teams</a>` : ''}</div>
        <div class="facts ct-facts"><span>${ico('inbox', 'sm')}${c.recus} reçus</span><span>${ico('send', 'sm')}${c.envoyes} envoyés</span><span>${ico('clock', 'sm')}dernier échange ${h(c.dernier)}</span></div>
        <h4 class="rd-h4">Ses moyens de communication</h4>
        <ul class="ct-ways">${p.moyens.map(([k, v]) => `<li>${ico(lib[k][0], 'sm')}<span class="muted">${lib[k][1]}</span><b>${h(v)}</b></li>`).join('')}</ul>
        <h4 class="rd-h4">Derniers mails</h4>
        ${recents.length ? `<div class="ct-mails">${recents.map((m) => `<button class="li" type="button" data-ouvrir="${m.id}"><span class="li-main"><span class="li-top"><span class="li-title">${h(m.objet)}</span><time>${h(m.t)}</time></span>
          <span class="li-snip">${h(boiteDe(m.boite).nom)}</span></span></button>`).join('')}</div>` : '<p class="small muted">Aucun mail relevé de cette adresse.</p>'}
        <div class="ct-foot"><button class="btn sm ghost danger" type="button" data-oublier>${ico('trash', 'sm')}Oublier ce correspondant</button></div>
      </div></section></div>`;
  }

  // ── L'écran ──────────────────────────────────────────────────────────
  function vueMessages() {
    return `<div class="split mail-split${etat.mobileLecture ? ' lire' : ''}"><aside class="pane mb-pane">${dossiers()}</aside>
      <section class="pane ml-pane">${liste()}</section><section class="pane rd-pane"><div class="pane-scroll" data-rd>${M.mobile() ? `<button class="btn sm ghost rd-back" type="button" data-retour>${ico('chev-left', 'sm')}Retour</button>` : ''}${liseuse()}</div></section></div>`;
  }
  function choisir(id, sec) {
    etat.choisi = id; etat.repondre = false; etat.mobileLecture = true;
    const m = MAILS.find((x) => x.id === id);
    if (m && m.nonlu) { m.nonlu = false; }
    const vue = sec.querySelector('.mail-split');
    if (!vue) { M.go('#mail/messages/' + id); return; }
    history.replaceState(null, '', '#mail/messages/' + id);
    M.rafraichir();
  }

  M.register('mail', {
    titre: 'Mail',
    onglets: [{ id: 'messages', titre: 'Messages' }, { id: 'contacts', titre: 'Contacts', cnt: CONTACTS.length }],
    compte: () => nonlus('tout'),
    actions: (ctx) => ctx.onglet === 'contacts' ? `<button class="btn" type="button" data-nouveau-contact>${ico('user-plus', 'sm')}<span class="lbl">Nouveau contact</span></button>
         <button class="btn primary" type="button" data-nouveau>${ico('plus', 'sm')}<span class="lbl">Nouveau message</span></button>`
      : `<button class="btn mika" type="button" data-demander>${ico('sparkle', 'sm')}<span class="lbl">Demander à Mika</span>${ico('chev-down', 'sm')}</button>
         <button class="btn primary" type="button" data-nouveau>${ico('plus', 'sm')}<span class="lbl">Nouveau message</span></button>`,
    monte(sec) {
      M.on(sec, '[data-vue]', 'click', (e, b) => {
        etat.vue = b.dataset.vue; etat.coches.clear();
        const l = mailsDeLaVue(); etat.choisi = l[0] ? l[0].id : null; etat.mobileLecture = false;
        history.replaceState(null, '', '#mail/messages'); M.rafraichir();
      });
      M.on(sec, '[data-mail]', 'click', (e, b) => { if (e.target.closest('.mrow-check')) return; choisir(b.dataset.mail, sec); });
      M.on(sec, '[data-boite]', 'click', (e, b) => { const id = b.dataset.boite; if (etat.ouvertes.has(id)) etat.ouvertes.delete(id); else etat.ouvertes.add(id); sec.querySelector('.mb-pane').innerHTML = dossiers(); });
      M.on(sec, '[data-ouvrir]', 'click', (e, b) => {
        const id = b.dataset.ouvrir;
        if (BROUILLONS.some((x) => x.id === id)) etat.vue = 'mika:brouillons';
        else { const m = MAILS.find((x) => x.id === id); etat.vue = m.boite === 'lea' ? 'lea:inbox' : `${m.boite}:${m.dossier}`; }
        M.go('#mail/messages/' + id);
      });
      M.on(sec, '[data-coche]', 'change', (e, b) => { if (b.checked) etat.coches.add(b.dataset.coche); else etat.coches.delete(b.dataset.coche); sec.querySelector('.ml-pane').innerHTML = liste(); });
      M.on(sec, '[data-groupe]', 'click', (e, b) => {
        const n = etat.coches.size, k = b.dataset.groupe;
        if (k === 'lu') etat.coches.forEach((id) => { const m = MAILS.find((x) => x.id === id); if (m) m.nonlu = false; });
        etat.coches.clear(); M.rafraichir();
        if (k !== 'aucun') M.toast({ lu: `${n} mail(s) marqué(s) comme lu(s).`, archiver: `${n} mail(s) archivé(s) dans « Archives ».`, corbeille: `${n} mail(s) mis à la corbeille.` }[k], { ico: 'check' });
      });
      M.on(sec, '[data-filtre]', 'click', (e, b) => { etat.filtre = b.dataset.filtre; sec.querySelector('.ml-pane').innerHTML = liste(); });
      M.on(sec, '[data-relever]', 'click', () => M.toast('Relève demandée : les nouveaux mails arrivent dans quelques secondes.', { ico: 'refresh' }));
      M.on(sec, '[data-images]', 'click', (e, b) => { const m = MAILS.find((x) => x.id === etat.choisi); etat.images.add(m.de.adr); M.rafraichir(); if (b.dataset.images === 'toujours') M.toast('Ses images s\'afficheront désormais pour cet expéditeur.', { ico: 'image' }); });
      M.on(sec, '[data-act]', 'click', (e, b) => {
        const m = MAILS.find((x) => x.id === etat.choisi);
        const k = b.dataset.act;
        if (k === 'repondre' || k === 'tous') { etat.repondre = true; etat.tous = k === 'tous'; M.rafraichir(); const t = sec.querySelector('[data-rd-txt]'); if (t) t.focus(); }
        else if (k === 'preremplir') {
          // Elle remplit la réponse ; si elle avait déjà un brouillon pour ce mail, c'est lui qu'elle reprend.
          const d = m.brouillon && BROUILLONS.find((x) => x.id === m.brouillon && x.etat[1].startsWith('attend'));
          etat.repondre = true; etat.prerempli = null; M.rafraichir();
          M.mika.typing(true);
          setTimeout(() => {
            M.mika.typing(false);
            etat.prerempli = d ? { lib: 'Son brouillon, repris ici', texte: d.texte.split('\n\n-- ')[0] } : { lib: 'Prérempli par Mika', texte: `Bonjour,\n\nMerci pour votre message. [À COMPLÉTER : ta réponse]\n\nBien cordialement,\nAdrien` };
            if (d) d.etat = ['', 'repris par toi'];
            M.rafraichir(); M.mika.talk(900);
          }, d ? 300 : 1100);
        }
        else if (k === 'vider') { etat.prerempli = null; M.rafraichir(); }
        else if (k === 'fermer-rep') { etat.repondre = false; etat.prerempli = null; M.rafraichir(); }
        else if (k === 'envoyer') { etat.repondre = false; etat.prerempli = null; m.repondu = true; M.rafraichir(); M.toast(`Envoyé à ${m.de.adr}. Elle le sait.`, { ico: 'send' }); }
        else if (k === 'transferer') ecrire({ titre: 'Transférer', boite: m.boite, objet: 'Tr : ' + m.objet, corps: '\n\n---------- Message transféré ----------\n' + m.corps.join('\n').replace(/<[^>]+>/g, ' ') });
        else if (k === 'rediger') demanderReponse(m);
        else if (k === 'archiver') { m.dossier = 'archive'; const l = mailsDeLaVue(); etat.choisi = l[0] ? l[0].id : null; M.rafraichir(); M.toast('Archivé dans « Archives ».', { ico: 'archive' }); }
        else if (k === 'nonlu') { m.nonlu = !m.nonlu; M.rafraichir(); M.compter(); }
        else if (k === 'suivre') { m.suivi = !m.suivi; M.rafraichir(); }
        else if (k === 'corbeille') { m.dossier = 'trash'; const l = mailsDeLaVue(); etat.choisi = l[0] ? l[0].id : null; M.rafraichir(); M.toast('Mis à la corbeille.', { ico: 'trash' }); }
        else if (k === 'plus') M.menu(b, [{ label: 'Ouvrir en grand', ico: 'expand' }, { label: `Voir le fil${m.fil ? ` (${m.fil})` : ''}`, ico: 'threads' }, { label: 'Déplacer vers…', ico: 'folder' }, 'sep',
          { label: 'Ce qu\'elle en sait', ico: 'sparkle' }, { label: 'Lui demander de l\'oublier', ico: 'eye-off', danger: true }]);
      });
      M.on(sec, '[data-decide]', 'click', (e, b) => {
        const d = BROUILLONS.find((x) => x.id === etat.choisi), k = b.dataset.decide;
        if (k === 'envoyer') { d.etat = ['ok', 'approuvé, en partance']; M.toast('Approuvé : il part dans un instant (tel que tu l\'as lu).', { ico: 'send' }); }
        if (k === 'refuser') { d.etat = ['', 'refusé']; M.toast('Refusé : elle le saura.', { ico: 'x' }); }
        if (k === 'reprendre') M.toast('Demandé : elle le reprend à son prochain moment de travail.', { mika: true });
        if (k === 'retoucher') { ecrire({ titre: 'Retoucher son brouillon', boite: d.boite, objet: d.objet, corps: d.texte, a: [CONTACTS.find((c) => d.a.includes(c.adr)) || { nom: d.a, adr: d.a }] }); return; }
        M.rafraichir();
      });
      M.on(sec, '[data-nouveau]', 'click', () => ecrire());
      M.on(sec, '[data-ecrire-a]', 'click', (e, b) => ecrire({ a: [CONTACTS.find((c) => c.adr === b.dataset.ecrireA)] }));
      M.on(sec, '[data-demander]', 'click', (e, b) => M.menu(b, [
        { entete: 'Demander à Mika' },
        { label: 'Résumer mes non-lus', ico: 'sparkle', action: () => M.toast('Elle te répond dans le chat : 4 non-lus, dont 2 importants.', { mika: true }) },
        { label: 'Préparer les réponses attendues', ico: 'pen', action: () => M.toast('Elle prépare 2 brouillons : ils arriveront dans « Ses brouillons ».', { mika: true }) },
        { label: 'Ranger la réception', ico: 'archive', action: () => M.toast('Elle range (25 mails au plus, jamais de suppression).', { mika: true }) },
      ]));
      M.on(sec, '[data-contact]', 'click', (e, b) => { etat.contact = b.dataset.contact; etat.mobileContact = true; M.rafraichir(); });
      M.on(sec, '[data-retour-c]', 'click', () => { etat.mobileContact = false; M.rafraichir(); });
      M.on(sec, '[data-nouveau-contact], [data-modifier-contact]', 'click', (e, b) => {
        const neuf = b.matches('[data-nouveau-contact]');
        const c = CONTACTS.find((x) => (x.cle || x.adr) === etat.contact) || {};
        const nom = neuf ? '' : c.nom || M.who(c.cle).nom;
        M.modal({ titre: neuf ? 'Nouveau contact' : 'Modifier le contact', taille: 'narrow',
          corps: `<div class="stack"><label class="field"><span>Nom</span><input value="${h(nom)}"></label><label class="field"><span>Mail</span><input value="${h(neuf ? '' : c.adr)}"></label>
            <label class="field"><span>Téléphone</span><input placeholder="+33 6 …"></label><label class="field"><span>Groupe</span><select><option>Travail</option><option>Proches</option><option>Autres</option></select></label>
            <p class="small muted">Ses moyens de communication servent à l'autocomplétion et à ce que Mika sait de cette personne.</p></div>`,
          pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-close>Enregistrer</button>' });
      });
      M.on(sec, '[data-dossiers]', 'click', (e, b) => {
        const items = [{ entete: 'Mika' }, { label: 'Ses brouillons', ico: 'pen', action: () => { etat.vue = 'mika:brouillons'; M.rafraichir(); } },
          { entete: 'Réceptions' }, { label: 'Toutes les réceptions', ico: 'inbox', action: () => { etat.vue = 'tout:inbox'; M.rafraichir(); } },
          { label: 'À traiter', ico: 'clock', action: () => { etat.vue = 'tout:traiter'; M.rafraichir(); } },
          ...D.filRouge.boites.map((x) => ({ label: `${x.nom} · Réception`, ico: 'mail', action: () => { etat.vue = `${x.id}:inbox`; M.rafraichir(); } })),
          { label: 'Boîte de Léa (lecture)', ico: 'lock', action: () => { etat.vue = 'lea:inbox'; M.rafraichir(); } }];
        M.menu(b, items, { align: 'left' });
      });
      M.on(sec, '[data-groupec]', 'click', (e, b) => { etat.groupeC = b.dataset.groupec; M.rafraichir(); });
      M.on(sec, '[data-oublier]', 'click', () => M.toast('Maquette : elle oublierait ce correspondant (ses mails restent).', { ico: 'trash' }));
      sec.addEventListener('input', (e) => {
        if (e.target.matches('[data-mq]')) { etat.q = e.target.value; const box = sec.querySelector('[data-liste]'); const l = mailsDeLaVue(); box.innerHTML = l.length ? l.map(ligne).join('') : `<div class="empty">${ico('search')}<b>Rien trouvé</b><p>Aucun mail ne contient « ${h(etat.q)} ».</p></div>`; }
        if (e.target.matches('[data-qc]')) { etat.qc = e.target.value; const pos = e.target.selectionStart; M.rafraichir(); const i2 = sec.querySelector('[data-qc]'); i2.focus(); i2.setSelectionRange(pos, pos); }
      });
      M.on(sec, '[data-retour]', 'click', () => { etat.mobileLecture = false; M.rafraichir(); });
      sec.addEventListener('keydown', (e) => {
        if (e.target.closest('input, textarea, select') || !['j', 'k'].includes(e.key)) return;
        const l = mailsDeLaVue(), i = l.findIndex((x) => x.id === etat.choisi);
        const n = l[Math.max(0, Math.min(l.length - 1, i + (e.key === 'j' ? 1 : -1)))];
        if (n) choisir(n.id, sec);
      });
    },
    rendu(body, ctx) {
      if (ctx.onglet === 'messages' && ctx.item) {
        const id = ctx.item;
        if (BROUILLONS.some((x) => x.id === id)) { if (!etat.vue.startsWith('mika') && !etat.vue.endsWith('drafts')) etat.vue = 'mika:brouillons'; etat.choisi = id; }
        else { const m = MAILS.find((x) => x.id === id); if (m) { etat.choisi = id; m.nonlu = false; setTimeout(M.compter, 0); const visible = mailsDeLaVue().some((x) => x.id === id); if (!visible) etat.vue = m.boite === 'lea' ? 'lea:inbox' : `${m.boite}:${m.dossier}`; } }
      }
      const b0 = etat.vue.split(':')[0];
      if (B[b0] || b0 === 'lea') etat.ouvertes.add(b0);
      body.innerHTML = ctx.onglet === 'contacts' ? vueContacts() : vueMessages();
      body.tabIndex = -1;
    },
    recherche: () => [
      ...MAILS.filter((m) => m.boite !== 'lea').map((m) => ({ groupe: 'Mails', titre: m.objet, sous: `${m.de.nom} · ${boiteDe(m.boite).nom} · ${m.quand}`, ico: 'mail', route: '#mail/messages/' + m.id })),
      ...BROUILLONS.map((b) => ({ groupe: 'Ses brouillons', titre: b.objet, sous: `à ${b.a.split(' <')[0]} · ${b.etat[1]}`, ico: 'pen', route: '#mail/messages/' + b.id })),
      ...CONTACTS.map((c) => ({ groupe: 'Contacts', titre: c.nom || M.who(c.cle).nom, sous: c.adr, ico: 'user', action: () => { etat.contact = c.cle || c.adr; M.go('#mail/contacts'); } })),
    ],
    notes: () => [
      { groupe: 'Décidé', statut: 'decide', titre: 'Ses brouillons se relisent dans Mail', texte: '« Ses brouillons » : relire, retoucher, refuser, envoyer, pour toutes tes boîtes ; pas de carte dans le chat' },
      { statut: 'decide', titre: 'Chacun branche ses boîtes', texte: 'une boîte ajoutée est à la personne qui l\'ajoute ; la partager est une délégation (lecture, lecture et préparer)' },
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'Plusieurs boîtes', texte: 'IMAP/SMTP par mot de passe ou compte Microsoft (code d\'appareil, XOAUTH2) ; DavMail = une boîte IMAP vers la passerelle locale', src: 'adapters/mail/config.py:213-233 · adapters/mail/oauth.py' },
      { statut: 'existe', titre: 'Lire comme une messagerie', texte: 'dossiers, filtres (non lus, importants, à traiter, suivis), recherche par mots, fil, liseuse à côté', src: 'plugins/email/console/box.py · adapters/mail/browse.py' },
      { statut: 'existe', titre: 'Cadre isolé, images masquées, pièces gardées', texte: 'HTML assaini ; images distantes par mail ou par expéditeur ; 25 Mio par pièce, 4 Gio en tout', src: 'ADR 0169 · ADR 0172 · inspector/framed.py' },
      { statut: 'existe', titre: '« Non lu » est le tien, « lu par elle » à part', texte: 'avec ce qu\'elle en sait : résumé du tri, importance, réponse attendue', src: 'ADR 0175 · plugins/email/console/common.py:146-166' },
      { statut: 'existe', titre: 'Écrire, répondre, transférer', texte: 'le mail part tout de suite, sous l\'expéditeur que dicte la voix de la boîte, et elle le sait', src: 'plugins/email/console/actions.py' },
      { statut: 'existe', titre: 'Ses brouillons et tes décisions', texte: 'envoyer, retoucher, refuser, lui demander de le reprendre ; [À COMPLÉTER] bloque l\'envoi', src: 'plugins/email/console/drafts.py' },
      { statut: 'en_cours', titre: 'À qui est une boîte', texte: 'toi, elle, ou une personne qui a un compte : ses outils ne voient que les boîtes de qui est en face', src: 'ADR 0185 (non commitée) · plugins/email/boxes.py' },
      { groupe: 'À faire ou à décider', statut: 'manque', titre: 'Une API du courrier pour l\'utilisateur', texte: 'aucune route /api ni trame /ws : tout est en pages de la console, gardées pour un opérateur', src: 'adapters/web/app.py:773-792 · inspector/ui.py:566-595' },
      { statut: 'manque', titre: 'Joindre des fichiers, Cci, brouillon humain, HTML sortant', texte: 'seul le transfert joint les pièces d\'origine ; un mail écrit à la main part tout de suite, en texte brut' },
      { statut: 'manque', titre: 'Un carnet d\'adresses', texte: 'les contacts ne sont que les correspondants du cache ; une adresse n\'est le moyen de communication d\'aucune personne de la mémoire' },
      { statut: 'partiel', titre: 'Approuver ses brouillons hors console', texte: 'pour une boîte à une personne, son brouillon arrive en carte avec le texte exact (ADR 0185, en cours) ; pour tes boîtes, pas de carte : la console et « À valider »', src: 'plugins/email/tools.py:415-416 · plugins/email/__init__.py:547-559' },
      { statut: 'manque', titre: 'Ses outils et les pièces jointes', texte: 'email_read ne donne que le nom et le nombre des pièces ; pour qu\'elle lise un PDF, il faut le lui joindre dans le chat' },
      { statut: 'partiel', titre: 'À décider : partager une boîte en lecture', texte: 'l\'ADR 0185 dit qu\'une boîte de personne ne s\'ouvre à personne d\'autre ; « Boîte de Léa » demande une nouvelle décision' },
      { statut: 'partiel', titre: 'À décider : un « non lu » commun', texte: 'c\'est le drapeau du serveur : deux personnes qui lisent la même boîte le partagent' },
      { statut: 'manque', titre: 'Nouveaux mails poussés au client', texte: 'aucune trame ; seule existe son annonce d\'un mail important' },
    ],
  });
})();
