/* Mail : toutes tes boîtes, comme un client Android (la liste, la liseuse, écrire), avec ce que Mika y fait : ce
   qu'elle a lu (rose, à part de ton non-lu), ce qu'elle en sait, la réponse attendue, et ses brouillons — exactement
   ce qui partira, à envoyer, retoucher ou refuser. */
(function () {
  const { h, ico, av, D } = A;
  const B = Object.fromEntries(D.filRouge.boites.map((b) => [b.id, b]));
  B.lea = { id: 'lea', nom: 'Boîte de Léa', adresse: 'lea.moreau@gmail.com' };

  const MAILS = [
    { id: 'm-claire', boite: 'pro', de: 'Claire Dubois', cle: 'claire', adr: 'c.dubois@lumen-conseil.fr', objet: 'Re: Présentation de jeudi', t: '13:40', apercu: 'Merci pour la trame, elle me va très bien. Une seule remarque : la partie budget arrive trop tard…',
      nonlu: true, lu: '13:54', attendue: true, brouillon: 'm-brouillon-claire', important: true,
      sait: 'Claire valide la trame. Une seule demande : un chiffre de budget dès la slide 2, avant jeudi. Ce n\'est pas un reproche.',
      corps: ['Salut Adrien,', 'Merci pour la trame, elle me va très bien. Une seule remarque : la partie budget arrive trop tard. Tu pourrais mettre un chiffre dès la deuxième slide ? Le client regarde ça en premier.', 'Pour le reste, on garde l\'ordre.', 'Bonne journée,<br>Claire'] },
    { id: 'm-lea', boite: 'perso', de: 'Léa Moreau', cle: 'lea', adr: 'lea.moreau@gmail.com', objet: 'Les photos de dimanche', t: '12:05', apercu: 'Je t\'ai mis les meilleures, il y en a une de toi avec le chien 😄', nonlu: true, pieces: 2,
      corps: ['Coucou !', 'Je t\'ai mis les meilleures, il y en a une de toi avec le chien 😄', 'Bises,<br>Léa'] },
    { id: 'm-marc', boite: 'pro', de: 'Marc Delmas', cle: 'marc', adr: 'm.delmas@lumen-conseil.fr', objet: 'Point d\'équipe déplacé à 16 h', t: '11:15', apercu: 'Le point de ce matin glisse à 16 h, même salle.', nonlu: true, lu: '11:16', important: true,
      sait: 'Le point d\'équipe de ce matin glisse à 16 h, même salle. Elle te l\'a dit à 11 h 17.', corps: ['Bonjour à tous,', 'Le point de ce matin glisse à 16 h, même salle.', 'Marc'] },
    { id: 'm-julien', boite: 'asso', de: 'Julien Roux', cle: 'julien', adr: 'julien.roux@proton.me', objet: 'Re: Rando dimanche — covoiturage', t: '10:20', apercu: 'Je peux prendre 3 personnes, départ 8 h 30 place du Concert.', repondu: true,
      corps: ['Je peux prendre 3 personnes, départ 8 h 30 place du Concert.', 'Julien'] },
    { id: 'm-lefevre', boite: 'pro', de: 'Lefèvre Rénovation', adr: 'devis@lefevre-renovation.fr', objet: 'Devis n° 2026-114 — rénovation salle de réunion', t: '09:42', apercu: 'Veuillez trouver ci-joint notre devis pour la rénovation de la salle de réunion du 2e étage…',
      attendue: true, lu: '13:31', brouillon: 'd-lefevre', pieces: 1,
      sait: 'Un devis de 16 740 € TTC, 1 240 € au-dessus du budget. La main-d\'œuvre n\'a pas de quantité. Elle l\'a comparé pour toi en mode pro.',
      corps: ['Bonjour Monsieur Moreau,', 'Veuillez trouver ci-joint notre devis pour la rénovation de la salle de réunion du 2e étage, valable 30 jours.', 'Cordialement,<br>Paul Lefèvre'] },
    { id: 'm-train', boite: 'perso', de: 'Rail Connect', adr: 'noreply@rail-connect.example', objet: 'Votre e-billet Lille Flandres → Paris Nord du 12 novembre', t: '08:30', apercu: 'Lille Flandres 07:16 → Paris Nord 08:18 · voiture 14, place 82', pieces: 1,
      corps: ['<b>Votre voyage du jeudi 12 novembre</b>', 'Lille Flandres 07:16 → Paris Nord 08:18 · voiture 14, place 82'] },
    { id: 'm-banque', boite: 'perso', de: 'Banque du Nord', adr: 'alertes@banque-du-nord.example', objet: 'Alerte : prélèvement de 89,90 €', t: '08:03', apercu: 'Un prélèvement de 89,90 € (Mutuelle Horizon) a été effectué sur votre compte.', lu: '08:10',
      corps: ['Un prélèvement de 89,90 € (Mutuelle Horizon) a été effectué sur votre compte.'] },
    { id: 'm-camille', boite: 'asso', de: 'Camille Petit', cle: 'camille', adr: 'camille.petit@laposte.net', objet: 'Le tracé du parcours ?', t: 'hier', apercu: 'Hello, tu aurais le fichier GPX du Mont des Cats ? Je voudrais le mettre sur ma montre.', nonlu: true, attendue: true, brouillon: 'd-camille',
      corps: ['Hello, tu aurais le fichier GPX du Mont des Cats ? Je voudrais le mettre sur ma montre.', 'Merci !<br>Camille'] },
    { id: 'm-nadia', boite: 'pro', de: 'Nadia Benkacem', cle: 'nadia', adr: 'n.benkacem@lumen-conseil.fr', objet: 'Entretien annuel : choisis ton créneau', t: 'hier', apercu: 'Les créneaux des entretiens annuels sont ouverts jusqu\'au 15 novembre.', suivi: true,
      corps: ['Bonjour Adrien,', 'Les créneaux des entretiens annuels sont ouverts jusqu\'au 15 novembre.', 'Nadia'] },
  ];
  const BROUILLONS = [
    { id: 'm-brouillon-claire', boite: 'pro', objet: 'Re: Présentation de jeudi', a: 'Claire Dubois <c.dubois@lumen-conseil.fr>', enReponse: 'm-claire', t: '13:55',
      etat: ['warn', 'attend ton accord'], pourquoi: 'Tu le lui as demandé dans le chat à 13:52.', voix: 'à ta place',
      texte: 'Salut Claire,\n\nMerci pour ta relecture. Bonne remarque : je remonte le budget en slide 2 et je t\'envoie la version corrigée ce soir.\n\nBonne journée,\nAdrien' },
    { id: 'd-lefevre', boite: 'pro', objet: 'Re: Devis n° 2026-114', a: 'Lefèvre Rénovation <devis@lefevre-renovation.fr>', enReponse: 'm-lefevre', t: '13:36',
      etat: ['warn', 'attend ton accord'], completer: true, pourquoi: 'Tu le lui as demandé en mode pro, dans le fil « Devis Lefèvre ».', voix: 'à ta place',
      texte: 'Bonjour Monsieur Lefèvre,\n\nMerci pour votre devis. Pourriez-vous nous détailler le poste « main-d\'œuvre » (nombre d\'heures et taux horaire) ?\n\nNous pourrions démarrer le [À COMPLÉTER : date de début souhaitée].\n\nBien cordialement,\nAdrien Moreau' },
    { id: 'd-camille', boite: 'asso', objet: 'Re: Le tracé du parcours ?', a: 'Camille Petit <camille.petit@laposte.net>', enReponse: 'm-camille', t: '08:02',
      etat: ['pc', 'à relire'], pourquoi: 'D\'elle-même : son tri y attendait une réponse.', voix: 'en assistante',
      texte: 'Bonjour Camille,\n\nJe vous réponds pour Adrien : le fichier GPX du Mont des Cats est sur le site de l\'association, page « Parcours ».\n\nBonne journée,\nMika' },
    { id: 'd-ancien', boite: 'pro', objet: 'Re: Planning de novembre', a: 'Sophie Laurent <s.laurent@lumen-conseil.fr>', t: 'hier', etat: ['ok', 'parti · retouché par toi'], voix: 'à ta place', fini: true,
      texte: 'Salut Sophie,\n\nLe planning me va, je prends le lundi 16.\n\nAdrien' },
  ];
  const mail = (id) => MAILS.find((m) => m.id === id) || MAILS[0];
  const brouillon = (id) => BROUILLONS.find((b) => b.id === id) || BROUILLONS[0];
  const lead = (m) => (m.cle ? av(m.cle) : A.grp(h(A.initiales(m.de))));
  const nomBoite = (id) => (B[id] ? B[id].nom : id);

  function ligne(m) {
    const marks = [m.attendue ? '<span class="tag warn">Réponse attendue</span>' : '', m.brouillon ? `<span class="tag mk">${ico('pen')}son brouillon</span>` : '',
      m.lu ? `<span class="mika-seen">${ico('eye')}lu par Mika · ${h(m.lu)}</span>` : ''].join('');
    return `<button class="li mail-row${m.nonlu ? ' unread' : ''}" type="button" data-go="#mail/lire/${m.id}">${lead(m)}
      <span class="txt"><b>${h(m.de)}</b><span class="subj">${h(m.objet)}</span><small>${h(m.apercu)}</small>${marks ? `<span class="marks">${marks}</span>` : ''}</span>
      <span class="trail"><span class="t">${h(m.t)}</span>${m.nonlu ? '<i class="unread-dot"></i>' : ''}${m.pieces ? ico('clip', 'xs') : ''}${m.important ? `<span style="color:var(--warn)">${ico('star', 'xs')}</span>` : ''}</span></button>`;
  }

  function vueListe() {
    const attente = BROUILLONS.filter((b) => !b.fini).length;
    return {
      nav: 'mail', racine: true,
      html: `${A.top({ racine: true, title: 'Toutes les réceptions', sub: `3 boîtes · 4 non lus ${ico('chev-down', 'xxs')}`, titleAttrs: 'data-sheet="boites"', small: true, actions: [A.act('search', 'Chercher dans les mails', 'data-go="#recherche"')] })}
        ${A.chips([{ l: 'Réponse attendue', n: 3, ico: 'reply' }, { l: 'Non lus', ico: 'mail' }, { l: 'Où Mika est passée', mk: true, ico: 'eye' }, { l: 'Importants', ico: 'star' }, { l: 'Avec pièces', ico: 'clip' }])}
        <div class="body" style="padding-bottom:84px">
          <div style="padding:4px 16px 6px"><button class="mk-line" type="button" data-go="#mail/brouillons">${ico('pen')}<span class="grow"><b>Ses brouillons</b><small>${attente} attendent ta décision · exactement ce qui partira</small></span><span class="cnt-pill mk">${attente}</span></button></div>
          <div class="list-head" style="color:var(--muted);font-weight:400;font-size:13px;padding-top:8px">Aujourd'hui</div>
          ${MAILS.filter((m) => m.t !== 'hier').map(ligne).join('')}
          <div class="list-head" style="color:var(--muted);font-weight:400;font-size:13px">Hier</div>
          ${MAILS.filter((m) => m.t === 'hier').map(ligne).join('')}
        </div>
        <button class="fab" type="button" data-go="#mail/ecrire">${ico('pen')}Écrire</button>`,
      notes: {
        titre: 'Mail',
        reprend: ['Toutes tes boîtes et celles qu\'on te partage ; le titre ouvre la feuille des boîtes et des dossiers.', 'Ton non-lu (le point indigo) et ce qu\'elle a lu (l\'œil rose) restent séparés (ADR 0175).',
          '« Ses brouillons » en tête de liste : la pastille Mail ne compte qu\'eux (ce qui attend ta décision).', 'Les filtres en puces ; « Écrire » en bouton flottant, comme Gmail.',
          'Pas encore montré : balayer pour archiver, l\'appui long pour sélectionner (archiver, déplacer, corbeille).'],
        trancher: ['Les boîtes dans une feuille qui monte du titre, ou un tiroir propre à Mail (comme Gmail) ?', '« Ses brouillons » en bandeau rose en haut de la liste, ou en onglet (Réception · Ses brouillons) ?', 'Les marques sous chaque mail (réponse attendue, son brouillon, lu par Mika) : trop chargé ?'],
      },
    };
  }

  function vueLire(id) {
    const m = mail(id);
    const b = m.brouillon ? brouillon(m.brouillon) : null;
    return {
      nav: 'mail', back: '#mail',
      html: `${A.top({ title: '', back: true, face: false, actions: [A.act('archive', 'Archiver', 'data-back data-snack="Archivé"'), A.act('trash', 'Corbeille', 'data-back data-snack="Mis à la corbeille"'), A.act('mail', 'Marquer non lu', 'data-back data-snack="Marqué non lu"'), A.act('more', 'Plus', 'data-menu="mail"')] })}
        <div class="body reader">
          <h1>${h(m.objet)}</h1>
          <div class="row wrap" style="padding:0 16px">${m.attendue ? '<span class="tag warn">Réponse attendue</span>' : ''}<span class="tag">${h(nomBoite(m.boite))}</span>${m.important ? '<span class="tag">Important</span>' : ''}</div>
          <div class="from">${lead(m)}<span class="grow"><b>${h(m.de)}</b><small class="ellipsis">${h(m.adr)} · aujourd'hui ${h(m.t)}</small></span>${A.act('reply', 'Répondre', 'data-go="#mail/ecrire/reponse"')}</div>
          ${m.sait ? `<div class="card mk" style="margin:0 16px 8px"><div class="over mk-txt row">${ico('sparkle', 'xs')}Ce qu'elle en sait${m.lu ? ` · lu à ${h(m.lu)}` : ''}</div><p style="font-size:14px">${h(m.sait)}</p></div>` : ''}
          <div class="bodytext">${m.corps.map((p) => `<p>${p}</p>`).join('')}</div>
          ${m.pieces ? `<div class="att">${m.id === 'm-lefevre' ? `<div class="att-chip">${ico('file')}<span><b>devis-2026-114.pdf</b><small>PDF · 212 Ko</small></span></div>` : m.id === 'm-train' ? `<div class="att-chip">${ico('file')}<span><b>e-billet-QZ7K4P.pdf</b><small>PDF · 96 Ko</small></span></div>` : `<div class="att-chip">${ico('image')}<span><b>IMG_2041.jpg</b><small>2,4 Mo</small></span></div><div class="att-chip">${ico('image')}<span><b>IMG_2047.jpg</b><small>1,9 Mo</small></span></div>`}</div>` : ''}
          ${b ? `<div style="padding:4px 16px 16px"><button class="mk-line" type="button" data-go="#mail/brouillon/${b.id}">${ico('pen')}<span class="grow"><b>Mika t'a préparé une réponse</b><small>${h(b.etat[1])} · ${h(b.t)} · ${h(b.voix)}</small></span>${ico('chev-right', 'sm')}</button></div>` : ''}
        </div>
        <div class="bottom-actions">
          <button class="btn outlined" type="button" data-go="#mail/ecrire/reponse">${ico('reply')}Répondre</button>
          <button class="btn outlined" type="button" data-go="#mail/ecrire/reponse">${ico('forward')}Transférer</button>
          ${b ? '' : `<button class="btn mk tonal fit" type="button" data-snack="Mika prépare une réponse : elle arrivera dans ses brouillons">${ico('sparkle')}Mika</button>`}
        </div>`,
      notes: {
        titre: 'Mail · la liseuse',
        reprend: ['« Ce qu\'elle en sait » en tête, en rose ; le corps du mail (HTML isolé dans la vraie app) ; ses pièces.', 'Son brouillon pour ce mail, s\'il existe, en lien juste après le corps.',
          'En haut : archiver, corbeille, non lu, ⋮ (suivre, déplacer, répondre à tous, images distantes) ; en bas : Répondre, Transférer et « Préremplir avec Mika » quand elle n\'a rien préparé.'],
        trancher: ['Les boutons de réponse en barre fixe en bas (comme ici), ou à la fin du mail comme Gmail ?', '« Préremplir avec Mika » : un bouton rose en bas, ou une action dans la fenêtre « Répondre » ?'],
      },
    };
  }

  function vueBrouillon(id) {
    const b = brouillon(id);
    const m = b.enReponse ? mail(b.enReponse) : null;
    const corps = h(b.texte).replace(/\[À COMPLÉTER[^\]]*\]/g, (x) => `<mark>${x}</mark>`);
    return {
      nav: 'mail', back: '#mail/brouillons',
      html: `${A.top({ title: 'Son brouillon', sub: h(nomBoite(b.boite)), small: true, back: true, face: false, actions: [A.act('more', 'Plus', 'data-menu="brouillon"')] })}
        <div class="body">
          <div class="row wrap" style="padding:4px 16px 10px"><span class="tag ${b.etat[0]}">${h(b.etat[1])}</span><span class="tag mk">${ico('sparkle')}${h(b.voix)}</span></div>
          <p class="note" style="padding-top:0">${h(b.pourquoi || '')}</p>
          <div class="over" style="padding:4px 16px 8px">Exactement ce qui partira</div>
          <div class="draft-box"><div class="db-h"><span>De</span><b style="font-weight:500">${h(B[b.boite].adresse)}</b><span>À</span><span style="color:var(--on)">${h(b.a)}</span><span>Objet</span><span style="color:var(--on)">${h(b.objet)}</span></div><div class="db-t">${corps}</div></div>
          ${m ? `<div style="padding:12px 16px"><button class="li" type="button" data-go="#mail/lire/${m.id}" style="padding:8px 0">${lead(m)}<span class="txt"><b style="font-size:14px">En réponse à ${h(m.de)}</b><small>${h(m.objet)} · ${h(m.t)}</small></span>${ico('chev-right', 'sm')}</button></div>` : ''}
          ${b.completer ? '<p class="note box">' + ico('alert', 'sm') + '<span>Un passage reste à compléter : « Envoyer » s\'allume quand il est rempli.</span></p>' : ''}
        </div>
        ${b.fini ? '' : `<div class="bottom-actions"><button class="btn text danger fit" type="button" data-back data-snack="Refusé : rien ne partira.">Refuser</button>
          <button class="btn outlined" type="button" data-go="#mail/ecrire/retoucher">${ico('pen')}Retoucher</button>
          <button class="btn filled" type="button" ${b.completer ? 'disabled' : 'data-back data-snack="Envoyé depuis ta boîte Pro"'}>${ico('send')}Envoyer</button></div>`}`,
      notes: {
        titre: 'Mail · son brouillon',
        reprend: ['Exactement ce qui partira : de, à, objet, texte ; un passage « À COMPLÉTER » surligné bloque l\'envoi.', 'Pourquoi elle l\'a écrit, et sa voix (à ta place, ou en assistante).', 'En bas : Refuser · Retoucher · Envoyer ; un lien vers le mail d\'origine.'],
        trancher: ['L\'ordre des trois boutons (Refuser à gauche, Envoyer à droite) ?'],
      },
    };
  }

  function vueBrouillons() {
    const groupe = (titre, list) => list.length ? `<div class="list-head mk">${titre}</div>${list.map((b) => `<button class="li" type="button" data-go="#mail/brouillon/${b.id}"><span class="lead box" style="color:var(--mika)">${ico('pen')}</span>
      <span class="txt"><b>${h(b.objet)}</b><small>${h(b.a.replace(/ <.*>/, ''))} · ${h(nomBoite(b.boite))}</small><span class="marks" style="display:flex;gap:4px;margin-top:4px"><span class="tag ${b.etat[0]}">${h(b.etat[1])}</span></span></span><span class="trail">${h(b.t)}</span></button>`).join('')}` : '';
    return {
      nav: 'mail', back: '#mail',
      html: `${A.top({ title: 'Ses brouillons', sub: 'toutes tes boîtes', small: true, back: true })}
        ${A.chips([{ l: 'À décider', radio: 'b', on: true }, { l: 'Partis', radio: 'b' }, { l: 'Refusés', radio: 'b' }])}
        <div class="body">${groupe('Attendent ta décision', BROUILLONS.filter((b) => b.etat[0] === 'warn'))}${groupe('À relire', BROUILLONS.filter((b) => b.etat[0] === 'pc'))}${groupe('Déjà partis', BROUILLONS.filter((b) => b.fini))}
        <p class="note">Elle en prépare d'elle-même quand son tri attend une réponse (6 par jour au plus). Ce qu'elle a le droit d'envoyer seule se règle dans Paramètres › Boîtes mail.</p></div>`,
      notes: { titre: 'Mail · ses brouillons', reprend: ['Tous ses brouillons, toutes boîtes : ce qui attend ta décision, ce qui est à relire, l\'historique.'], trancher: [] },
    };
  }

  function vueEcrire(mode) {
    const reponse = mode === 'reponse' || mode === 'retoucher';
    return {
      nav: 'mail', back: '#mail',
      html: `${A.top({ title: reponse ? 'Répondre' : 'Nouveau message', small: true, back: true, face: false, actions: [A.act('clip', 'Joindre', 'data-sheet="joindre"'), A.act('send', 'Envoyer', 'data-back data-snack="Envoyé"', 'on')] })}
        <div class="body">
          <div class="line-field"><span>De</span><button class="row grow" type="button" data-sheet="boites" style="justify-content:space-between"><span>Pro · a.moreau@lumen-conseil.fr</span>${ico('chev-down', 'sm')}</button></div>
          <div class="line-field"><span>À</span><span class="row wrap grow">${reponse ? `<span class="chip" style="height:28px">${av('claire', 'xs')}Claire Dubois</span>` : ''}<input placeholder="${reponse ? '' : 'Un nom, une adresse'}"></span>${ico('chev-down', 'sm')}</div>
          <div class="line-field"><span>Objet</span><input value="${reponse ? 'Re: Présentation de jeudi' : ''}"></div>
          <textarea style="width:100%;min-height:220px;border:0;outline:0;background:none;padding:14px 16px;font-size:15.5px;line-height:23px;resize:none" placeholder="Ton message">${mode === 'retoucher' ? h(BROUILLONS[0].texte) : ''}</textarea>
        </div>
        <div style="padding:8px 16px 12px;border-top:1px solid var(--line)"><button class="btn mk outlined" type="button" data-snack="Mika préremplit… sa proposition arrive dans le champ">${ico('sparkle')}Préremplir avec Mika</button></div>`,
      notes: { titre: 'Mail · écrire', reprend: ['De (la boîte), À avec les destinataires proposés, Cc/Cci dans la flèche, l\'objet, le texte ; joindre et envoyer en haut.', '« Préremplir avec Mika » au-dessus du clavier : elle propose, tu relis.'], trancher: ['« Préremplir avec Mika » au-dessus du clavier, ou dans la barre du haut ?'] },
    };
  }

  A.ecran('mail', (args) => {
    if (args[0] === 'lire') return vueLire(args[1]);
    if (args[0] === 'brouillon') return vueBrouillon(args[1]);
    if (args[0] === 'brouillons') return vueBrouillons();
    if (args[0] === 'ecrire') return vueEcrire(args[1]);
    return vueListe();
  });

  A.sheets.boites = () => {
    const ligneB = (i, nom, sous, n, on) => `<button class="li${on ? ' sel' : ''}" type="button" data-close data-snack="${h(nom)}"><span class="lead box">${ico(i)}</span><span class="txt"><b>${h(nom)}</b><small>${h(sous)}</small></span>${n ? `<span class="cnt-pill">${n}</span>` : ''}</button>`;
    A.sheet('Tes boîtes', `${ligneB('inbox', 'Toutes les réceptions', 'Pro, Perso, Rando Cassel', 4, true)}
      ${D.filRouge.boites.map((b) => ligneB('mail', b.nom, b.adresse, b.id === 'asso' ? 1 : b.id === 'pro' ? 1 : 2)).join('')}
      <div class="list-head">Partagée avec toi</div>${ligneB('users', 'Boîte de Léa', 'lea.moreau@gmail.com · lecture seule', 0)}
      <div class="list-head">Dossiers de Pro</div>
      ${[['inbox', 'Réception', 1], ['send', 'Envoyés'], ['file', 'Brouillons'], ['archive', 'Archives'], ['alert', 'Indésirables'], ['trash', 'Corbeille'], ['folder', 'Clients']].map(([i, l, n]) => ligneB(i, l, '', n)).join('')}
      <div class="divider"></div>
      <button class="li" type="button" data-close data-snack="Maquette : les contacts"><span class="lead box">${ico('users')}</span><span class="txt"><b>Contacts</b></span></button>
      <button class="li" type="button" data-go="#parametres/boites"><span class="lead box">${ico('settings')}</span><span class="txt"><b>Régler les boîtes</b><small>Paramètres › Boîtes mail</small></span></button>`);
  };
  A.menus.mail = () => [{ ico: 'reply-all', l: 'Répondre à tous', go: '#mail/ecrire/reponse' }, { ico: 'flag', l: 'Suivre', snack: 'Suivi' }, { ico: 'folder', l: 'Déplacer…', snack: 'Maquette : déplacer' }, { ico: 'star', l: 'Important', snack: 'Marqué important' }, { ico: 'image', l: 'Afficher les images', snack: 'Images de cet expéditeur affichées' }, '-', { ico: 'chat', l: 'En parler à Mika', go: '#chat' }];
  A.menus.brouillon = () => [{ ico: 'chat', l: 'En parler à Mika', go: '#chat' }, { ico: 'copy', l: 'Copier le texte', snack: 'Copié' }];

  A.index('Mail', [['Liste', '#mail'], ['Liseuse', '#mail/lire/m-claire'], ['Son brouillon', '#mail/brouillon/m-brouillon-claire'], ['À compléter', '#mail/brouillon/d-lefevre'], ['Ses brouillons', '#mail/brouillons'], ['Écrire', '#mail/ecrire']]);
})();
