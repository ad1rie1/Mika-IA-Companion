/* Contacts (ADR 0298) : tous ceux que Mika connaît pour toi — vus dans ton Teams, tes boîtes, ton téléphone, ou dont
   tu lui as parlé —, et leurs organisations. Un contact est à qui l'a fait connaître : ici, ce sont les tiens (et ceux
   qui ne viennent du compte de personne). Ce qui l'identifie, ce que Mika en sait, où vous vous croisez. Remplace
   l'onglet Contacts du courrier. */
(function () {
  const { h, ico, av } = M;
  const SORTES = { mail: ['mail', 'E-mail'], teams: ['teams', 'Teams'], tel: ['phone', 'Téléphone'], whatsapp: ['chat', 'WhatsApp'],
    domaine: ['globe', 'Domaine'], orgteams: ['teams', 'Organisation Teams'], login: ['user', 'Identifiant'] };
  const SOURCES = { teams: ['teams', 'Teams'], pro: ['mail', 'Pro'], perso: ['mail', 'Perso'], asso: ['mail', 'Rando Cassel'],
    whatsapp: ['chat', 'WhatsApp'], sms: ['phone', 'SMS'], raconte: ['sparkle', 'Raconté'] };

  /* Les contacts d'Adrien. `ids` : [sorte, valeur, d'où elle le tient] ; `src` : [source, nombre] ;
     `sait` : [ce qu'elle en sait, d'où] ; `croise` : [icône, libellé, détail, route]. */
  const C = [
    { id: 'claire', cle: 'claire', org: 'lumen', dernier: '13:40', idee: 'Cheffe de projet',
      src: [['teams', 64], ['pro', 23]],
      ids: [['mail', 'c.dubois@lumen-conseil.fr', 'Pro · son profil Teams'], ['teams', 'Claire Dubois', 'Teams']],
      sait: [['Elle pilote la présentation de jeudi au client.', 'lu dans Teams · Projet Lumen · aujourd\'hui'],
        ['Elle préfère les points courts, le matin.', 'lu dans Teams · tête-à-tête · il y a 2 semaines'],
        ['Elle attend ta version corrigée des chiffres.', 'lu au courrier · « Re: Présentation de jeudi »']],
      croise: [['teams', 'Claire Dubois', 'tête-à-tête · 41 messages', '#teams/discussions/claire'],
        ['teams', 'Projet Lumen', 'groupe · 23 messages', '#teams/discussions/lumen'],
        ['mail', 'Re: Présentation de jeudi', 'Pro · aujourd\'hui 13:40', '#mail/messages/m-claire']] },
    { id: 'marc', cle: 'marc', org: 'lumen', dernier: '11:02', idee: 'Directeur des opérations ; ton chef',
      src: [['teams', 12], ['pro', 9]],
      ids: [['mail', 'm.delmas@lumen-conseil.fr', 'Pro'], ['teams', 'Marc Delmas', 'Teams']],
      sait: [['C\'est ton chef ; il valide les devis au-delà de 5 000 €.', 'lu au courrier · « Devis n° 2026-114 »']],
      croise: [['teams', 'Marc Delmas', 'tête-à-tête · 12 messages', '#teams/discussions/marc']] },
    { id: 'lea', cle: 'lea', dernier: 'hier', idee: 'Ta sœur', parle: true,
      src: [['whatsapp', 120], ['perso', 8], ['raconte', 12]],
      ids: [['login', 'lea', 'son compte : elle parle aussi à Mika'], ['mail', 'lea.moreau@gmail.com', 'Perso'],
        ['tel', '+33 6 71 20 33 58', 'WhatsApp, Messages']],
      sait: [['Elle prépare l\'anniversaire de votre père.', 'raconté par toi · il y a 3 j'],
        ['Elle t\'a envoyé un colis à ne pas ouvrir.', 'lu dans WhatsApp · aujourd\'hui']],
      croise: [['chat', 'Léa', 'WhatsApp · 120 messages', '#telephone/messages/lea'], ['mail', '8 mails', 'Perso', '#mail/messages']] },
    { id: 'sophie', cle: 'sophie', org: 'lumen', dernier: 'hier', idee: 'Consultante data',
      src: [['teams', 30], ['whatsapp', 4], ['pro', 6]],
      ids: [['mail', 's.laurent@lumen-conseil.fr', 'Pro · son profil Teams'], ['teams', 'Sophie Laurent', 'Teams'],
        ['tel', '+33 6 52 11 08 74', 'WhatsApp, sur ton Pixel 7a']],
      sait: [['Elle a besoin du fichier des chiffres pour jeudi.', 'lu dans WhatsApp · hier']],
      croise: [['chat', 'Sophie Laurent', 'WhatsApp · Pixel 7a', '#telephone/messages/sophie'], ['teams', 'Projet Lumen', 'groupe', '#teams/discussions/lumen']] },
    { id: 'julien', cle: 'julien', dernier: '14:09', idee: 'Ton ami proche', parle: true,
      src: [['whatsapp', 86], ['asso', 14]],
      ids: [['login', 'julien', 'son compte : il parle aussi à Mika'], ['mail', 'julien.roux@proton.me', 'Rando Cassel'],
        ['tel', '+33 6 33 18 72 41', 'WhatsApp']],
      sait: [['Il organise la boucle des Monts dimanche, départ 8 h 30.', 'lu dans WhatsApp · aujourd\'hui']],
      croise: [['chat', 'Julien Roux', 'WhatsApp · 86 messages', '#telephone/messages/julien'], ['chat', 'Rando dimanche 🥾', 'groupe WhatsApp', '#telephone/messages/rando']] },
    { id: 'maman', cle: 'maman', dernier: '12:40', idee: 'Ta mère',
      src: [['sms', 40], ['raconte', 6]],
      ids: [['tel', '+33 6 08 41 77 93', 'Messages, WhatsApp']],
      sait: [['Elle t\'attend dimanche midi ; elle fait un rôti.', 'lu dans Messages · aujourd\'hui']],
      croise: [['phone', 'Maman', 'Messages · 40', '#telephone/messages/maman']] },
    { id: 'karim', cle: 'karim', org: 'lumen', dernier: 'lun.', idee: 'Développeur',
      src: [['teams', 18]], ids: [['mail', 'k.haddad@lumen-conseil.fr', 'son profil Teams'], ['teams', 'Karim Haddad', 'Teams']],
      sait: [], croise: [['teams', 'Projet Lumen', 'groupe', '#teams/discussions/lumen']] },
    { id: 'ines', nom: 'Inès', c: 6, dernier: 'il y a 5 j', idee: 'Une amie de Léa',
      src: [['raconte', 2]], ids: [],
      sait: [['Elle cherche un covoiturage pour l\'anniversaire de votre père.', 'raconté par toi · il y a 5 j']],
      croise: [] },
    { id: 'lumen', org: true, nom: 'Lumen Conseil', c: 0, dernier: '13:40', idee: 'Ton employeur',
      src: [['teams', 214], ['pro', 120]],
      ids: [['domaine', 'lumen-conseil.fr', 'Pro, Teams'], ['orgteams', 'Lumen Conseil', 'Teams'], ['mail', 'noreply@lumen-conseil.fr', 'Pro · sans personne derrière']],
      sait: [['Le cabinet où tu travailles ; ton chef est Marc Delmas.', 'lu dans Teams et au courrier']],
      membres: ['claire', 'marc', 'sophie', 'karim', 'nadia'], croise: [] },
    { id: 'lefevre', org: true, nom: 'Lefèvre Rénovation', c: 2, dernier: '09:42', idee: 'Artisan ; t\'a envoyé un devis',
      src: [['pro', 3]], ids: [['domaine', 'lefevre-renovation.fr', 'Pro'], ['mail', 'devis@lefevre-renovation.fr', 'Pro · sans personne derrière']],
      sait: [['Devis n° 2026-114 pour la salle de réunion, en attente de Marc.', 'lu au courrier · aujourd\'hui']],
      membres: [], croise: [['mail', 'Devis n° 2026-114', 'Pro · 09:42', '#mail/messages/m-lefevre']] },
    { id: 'garage', org: true, nom: 'Garage Martin', c: 2, dernier: '10:15', idee: 'Ton garagiste',
      src: [['sms', 5]], ids: [['tel', '03 20 45 18 60', 'Messages']],
      sait: [['Ta voiture est prête depuis 17 h.', 'lu dans Messages · aujourd\'hui']],
      membres: [], croise: [['phone', 'Garage Martin', 'Messages', '#telephone/messages/garage']] },
  ];
  const nom = (c) => c.nom || M.who(c.cle).nom;
  const estOrg = (c) => c.org === true;
  const avatar = (c, taille) => av(c.cle ? c.cle : { nom: nom(c), c: c.c }, taille + (estOrg(c) ? ' sq' : ''));
  const etat = { q: '', sorte: 'tous', choisi: 'claire', mobile: false };

  function visibles() {
    return C.filter((c) => (etat.sorte === 'tous' || (etat.sorte === 'orgs') === estOrg(c))
      && (!etat.q || M.norm(nom(c) + ' ' + c.ids.map((x) => x[1]).join(' ') + ' ' + c.idee).includes(M.norm(etat.q))));
  }
  const pastilles = (c) => c.src.map(([k, n]) => `<span class="cx-src" title="${h(SOURCES[k][1])} · ${n}">${ico(SOURCES[k][0], 'xs')}${n}</span>`).join('');

  function ligne(c) {
    return `<button class="li" type="button" data-cx="${c.id}" aria-selected="${c.id === etat.choisi}">${avatar(c, 'sm')}
      <span class="li-main"><span class="li-top"><span class="li-title">${h(nom(c))}</span><time>${h(c.dernier)}</time></span>
      <span class="li-snip cx-snip"><span class="cx-org">${h(estOrg(c) ? 'Organisation' : (C.find((o) => o.id === c.org) || { nom: c.idee }).nom)}</span>${pastilles(c)}</span></span></button>`;
  }

  function fiche(c) {
    const membres = (c.membres || []).map((k) => C.find((x) => x.cle === k) || { id: k, cle: k, idee: M.who(k).titre || '', src: [], ids: [] });
    const org = c.org && !estOrg(c) ? C.find((o) => o.id === c.org) : null;
    const mail = c.ids.find((x) => x[0] === 'mail' && !/noreply|devis@/.test(x[1]));
    const teams = c.croise.find((x) => x[0] === 'teams');
    const tel = c.croise.find((x) => x[0] === 'chat' || x[0] === 'phone');
    return `<div class="pane-scroll ct-card cx-card"><button class="btn sm ghost mobile-back" type="button" data-retour-cx>${ico('chev-left', 'sm')}Contacts</button>
      <div class="ct-head">${avatar(c, 'xl')}<div class="grow"><h2>${h(nom(c))}</h2>
        <p class="text-2">${h(c.idee)}${org ? ` · <a href="#contacts/${org.id}" data-cx-lien="${org.id}">${h(org.nom)}</a>` : ''}${c.parle ? ` <span class="tag ok">parle aussi à Mika</span>` : ''}</p></div>
        ${mail ? `<button class="btn primary sm" type="button" data-cx-ecrire="${h(mail[1])}">${ico('send', 'sm')}Écrire</button>` : ''}
        ${teams ? `<a class="btn sm" href="${teams[3]}">${ico('teams', 'sm')}Teams</a>` : ''}
        ${tel ? `<a class="btn sm" href="${tel[3]}">${ico('phone', 'sm')}Message</a>` : ''}</div>
      <div class="facts ct-facts">${c.src.map(([k, n]) => `<span>${ico(SOURCES[k][0], 'sm')}${h(SOURCES[k][1])} · ${n}</span>`).join('')}<span>${ico('clock', 'sm')}dernier échange ${h(c.dernier)}</span></div>
      <div class="ct-cols">
        <div>
          <h4 class="rd-h4">Ce qui l'identifie</h4>
          ${c.ids.length ? `<ul class="ct-ways cx-ways">${c.ids.map(([k, v, d]) => `<li>${ico(SORTES[k][0], 'sm')}<span class="muted">${h(SORTES[k][1])}</span><span class="cx-val"><b>${h(v)}</b><small>${h(d)}</small></span></li>`).join('')}</ul>`
            : '<p class="small muted">Aucun moyen de communication : tu lui en as seulement parlé.</p>'}
          ${membres.length ? `<h4 class="rd-h4">Ses personnes parmi tes contacts</h4><div class="cx-membres">${membres.map((m) => `<button class="li" type="button" data-cx="${m.id}">${avatar(m, 'sm')}<span class="li-main"><span class="li-title">${h(nom(m))}</span><span class="li-snip">${h(m.idee || '')}</span></span></button>`).join('')}</div>` : ''}
        </div>
        <div>
          <h4 class="rd-h4">${ico('sparkle', 'sm')}Ce que Mika en sait</h4>
          ${c.sait.length ? `<ul class="cx-sait">${c.sait.map(([t, d]) => `<li><p>${h(t)}</p><small>${h(d)}</small><button class="btn xs ghost" type="button" data-cx-oublier-fait title="Qu'elle l'oublie">${ico('x', 'xs')}</button></li>`).join('')}</ul>`
            : '<p class="small muted">Rien de plus que ce qui l\'identifie.</p>'}
          ${c.croise.length ? `<h4 class="rd-h4">Où vous vous croisez</h4><div class="cx-croise">${c.croise.map(([i, l, d, r]) => `<a class="li" href="${r}">${ico(i, 'sm')}<span class="li-main"><span class="li-title">${h(l)}</span><span class="li-snip">${h(d)}</span></span>${ico('chev-right', 'sm')}</a>`).join('')}</div>` : ''}
        </div>
      </div>
      <p class="small muted cx-note">Ce que Mika sait de ${h(nom(c))} vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi.</p>
      <div class="ct-foot"><button class="btn sm ghost danger" type="button" data-cx-oublier>${ico('trash', 'sm')}Oublier ce contact</button></div>
    </div>`;
  }

  function vue() {
    const l = visibles();
    const c = C.find((x) => x.id === etat.choisi) || l[0] || C[0];
    const n = (s) => C.filter((x) => s === 'tous' || (s === 'orgs') === estOrg(x)).length;
    return `<div class="split ct-split cx-split${etat.mobile ? ' lire' : ''}">
      <aside class="pane"><div class="pane-head"><label class="search grow">${ico('search', 'sm')}<input type="search" placeholder="Un nom, un e-mail, un numéro…" data-cxq value="${h(etat.q)}"></label></div>
        <div class="ml-tools"><div class="seg" role="group">${[['tous', 'Tous'], ['personnes', 'Personnes'], ['orgs', 'Organisations']].map(([k, lb]) => `<button type="button" data-cxsorte="${k}" aria-pressed="${etat.sorte === k}">${lb} <span class="cnt">${n(k)}</span></button>`).join('')}</div></div>
        <div class="pane-scroll">${l.length ? l.map(ligne).join('') : `<div class="empty">${ico('search')}<b>Personne</b><p>Aucun contact ne correspond à « ${h(etat.q)} ».</p></div>`}</div></aside>
      <section class="pane ct-pane">${fiche(c)}</section></div>`;
  }

  M.register('contacts', {
    titre: 'Contacts',
    sousTitre: () => `${C.length} pour toi`,
    actions: () => `<button class="btn" type="button" data-cx-nouveau>${ico('user-plus', 'sm')}<span class="lbl">Lui présenter quelqu'un</span></button>`,
    monte(sec) {
      M.on(sec, '[data-cx]', 'click', (e, b) => { etat.choisi = b.dataset.cx; etat.mobile = true; history.replaceState(null, '', '#contacts/' + b.dataset.cx); M.rafraichir(); });
      M.on(sec, '[data-cx-lien]', 'click', (e, b) => { e.preventDefault(); etat.choisi = b.dataset.cxLien; M.rafraichir(); });
      M.on(sec, '[data-cxsorte]', 'click', (e, b) => { etat.sorte = b.dataset.cxsorte; M.rafraichir(); });
      M.on(sec, '[data-retour-cx]', 'click', () => { etat.mobile = false; M.rafraichir(); });
      M.on(sec, '[data-cx-ecrire]', 'click', () => M.go('#mail/messages'));
      M.on(sec, '[data-cx-oublier]', 'click', () => M.toast('Maquette : elle oublierait ce contact et ce qu\'elle en sait (les messages restent dans leurs boîtes).', { ico: 'trash' }));
      M.on(sec, '[data-cx-oublier-fait]', 'click', () => M.toast('Maquette : elle oublierait ce qu\'elle en savait là.', { ico: 'x' }));
      M.on(sec, '[data-cx-nouveau]', 'click', () => M.toast('Maquette : dis-le-lui dans le chat (« Inès est une amie de Léa… ») ; la fiche naît de ce que tu lui racontes.', { mika: true }));
      sec.addEventListener('input', (e) => {
        if (!e.target.matches('[data-cxq]')) return;
        etat.q = e.target.value; const pos = e.target.selectionStart; M.rafraichir();
        const i = sec.querySelector('[data-cxq]'); i.focus(); i.setSelectionRange(pos, pos);
      });
    },
    rendu(body, ctx) {
      if (ctx.item && C.some((x) => x.id === ctx.item)) etat.choisi = ctx.item;
      body.innerHTML = vue();
    },
    recherche: () => C.map((c) => ({ groupe: 'Contacts', titre: nom(c), sous: c.idee, ico: estOrg(c) ? 'users' : 'user', route: '#contacts/' + c.id })),
    notes: () => [
      { groupe: 'Décidé', statut: 'decide', titre: 'Tous ceux qu\'elle connaît, même de loin', texte: 'vus dans ton Teams, tes boîtes, ton téléphone, ou dont tu lui as parlé ; et leurs organisations', src: 'ADR 0298' },
      { statut: 'decide', titre: 'Un contact est à qui l\'a fait connaître', texte: 'ici les tiens ; croisé chez deux personnes, il est aux deux (ce que chacune lui en a appris reste à elle) ; venu du compte de personne, à tout le monde' },
      { statut: 'decide', titre: 'Réunir sur preuve', texte: 'la même adresse, le même compte : une seule fiche d\'office ; un même nom seul se propose à l\'opérateur (console, À valider › Rapprochements)' },
      { statut: 'decide', titre: 'Mail › Contacts disparaît', texte: 'ses correspondants sont ici, avec ceux de Teams et du téléphone' },
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'Les correspondants du courrier', texte: 'la liste de Mail › Contacts (adresse, reçus, envoyés, dernier échange)', src: 'GET /api/moi/mail/contacts' },
      { statut: 'existe', titre: 'Les auteurs de Teams, les expéditeurs du téléphone', texte: 'gardés par leur plugin, sans fiche commune', src: 'adapters/teams/store.py · plugins/phone' },
      { groupe: 'À faire', statut: 'manque', titre: 'Le moteur de l\'annuaire', texte: 'les fiches des personnes connues de loin, leurs moyens de communication typés, leurs organisations, à qui elles sont', src: 'faculties/identity' },
      { statut: 'manque', titre: 'Ce qu\'elle en sait', texte: 'sa mémoire se forme une idée de chacun à partir de ce qu\'elle lit, avec la source ; oubliable fait par fait' },
      { statut: 'manque', titre: 'L\'API', texte: 'GET /api/moi/contacts (liste, recherche, sorte) et /api/moi/contacts/fiche ; oublier un contact, un fait' },
    ],
  });
})();
