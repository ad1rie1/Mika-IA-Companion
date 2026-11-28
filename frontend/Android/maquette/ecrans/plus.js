/* Plus (la cinquième case de la barre du bas) et Paramètres : ce que tu règles pour toi (ton compte, ses boîtes,
   tes comptes Teams, tes téléphones, tes partages, tes services — le client web), puis ce que règle ce téléphone
   (les réglages de l'app d'aujourd'hui : notifications, position, ses messages, apparence, données). */
(function () {
  const { h, ico, av, D } = A;

  // ── Plus ──────────────────────────────────────────────────────────────
  A.ecran('plus', () => ({
    nav: 'plus', racine: true,
    html: `${A.top({ racine: true, title: 'Plus', small: true, face: false })}
      <div class="body">
        <button class="plus-mika" type="button" data-go="#mika">${A.faceDot(56)}<span class="grow"><b>Mika</b><small>${h(D.mika.fait)} · ${h(D.mika.humeurDite)}</small><small class="mk-txt">2 promesses · elle repense aux corneilles</small></span>${ico('chev-right', 'sm')}</button>
        <div style="padding:4px 16px 8px"><button class="field" type="button" data-go="#recherche" style="width:100%;height:52px">${ico('search', 'sm')}<span class="muted">Rechercher partout</span></button></div>
        <div class="set-group">
          <button class="li" type="button" data-go="#telephone"><span class="lead box">${ico('phone')}</span><span class="txt"><b>Téléphone</b><small>ses messages WhatsApp et SMS, sa position</small></span><span class="cnt-pill mk">1</span></button>
          <button class="li" type="button" data-go="#outils"><span class="lead box">${ico('tools')}</span><span class="txt"><b>Outils</b><small>ce qu'elle a le droit de faire pour toi</small></span></button>
          <button class="li" type="button" data-go="#parametres"><span class="lead box">${ico('settings')}</span><span class="txt"><b>Paramètres</b><small>compte, boîtes, Teams, ce téléphone</small></span></button>
        </div>
        <div class="set-group" style="margin-top:12px">
          <button class="li" type="button" data-go="#fichiers"><span class="lead box">${ico('folder')}</span><span class="txt"><b>Fichiers échangés</b></span></button>
          <button class="li" type="button" data-go="#parametres/compte">${av('adrien')}<span class="txt"><b>${h(D.moi.nom)}</b><small>${h(D.moi.role)} · opérateur</small></span></button>
          <button class="li" type="button" data-dialog="deconnexion"><span class="lead box">${ico('logout')}</span><span class="txt"><b>Se déconnecter</b></span></button>
        </div>
        <p class="note" style="text-align:center;padding:16px">Mika pour Android · version de la maquette</p>
      </div>`,
    notes: {
      titre: 'Plus',
      reprend: ['La cinquième case : Mika (vers « Ce qu\'elle fait »), « Rechercher partout », puis Téléphone, Outils, Paramètres.', 'Le compte et « Se déconnecter » en bas, comme le menu du compte du client web.'],
      trancher: ['Ces trois rubriques sous « Plus » te vont, ou faut-il en remonter une dans la barre du bas (à la place de Carte ou de Teams) ?', 'La carte de Mika en haut de « Plus » : utile, ou redondante avec son visage partout ?'],
    },
  }));

  // ── Paramètres ────────────────────────────────────────────────────────
  const item = (i, b, s, go, trail) => `<button class="li" type="button" data-go="${go}"><span class="lead">${ico(i)}</span><span class="txt"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>${trail || ''}</button>`;
  const row = (b, s, val) => `<div class="set-row"><span class="txt"><b>${b}</b>${s ? `<small>${s}</small>` : ''}</span>${val || ''}</div>`;
  const page = (titre, corps, n) => ({ nav: A.v.nav === 'barre' ? 'plus' : 'parametres', back: '#parametres',
    html: `${A.top({ title: titre, small: true, back: true, face: false })}<div class="body" style="padding-bottom:84px">${corps}</div>${n && n.fab ? n.fab : ''}`, notes: n || {} });

  function racine() {
    return {
      nav: A.v.nav === 'barre' ? 'plus' : 'parametres', racine: true, back: '#plus',
      html: `${A.top({ racine: true, back: A.v.nav === 'barre', title: 'Paramètres', small: true })}
        <div class="body">
          <div class="set-h">Ton compte</div>
          <div class="set-group">${item('user', 'Compte', `${h(D.moi.nom)} · mot de passe, connexions`, '#parametres/compte')}</div>
          <div class="set-h">Ce que Mika touche pour toi</div>
          <div class="set-group">${item('mail', 'Boîtes mail', '3 à toi · 1 partagée avec toi', '#parametres/boites')}${item('teams', 'Comptes Teams', 'Lumen Conseil', '#parametres/teams')}
            ${item('phone', 'Téléphones', 'ce téléphone · Google Pixel 7a', '#parametres/telephones')}${item('share', 'Partages', 'Rando Cassel → Julien · Météo Locale → Léa', '#parametres/partages')}${item('plug', 'Services MCP', 'Météo Locale', '#parametres/mcp')}</div>
          <div class="set-h">Ce téléphone</div>
          <div class="set-group">${item('bell', 'Notifications', 'autorisées · application fermée : active', '#parametres/notifications')}${item('pin', 'Position', 'Lui dire où je suis · allumé', '#parametres/position')}
            ${item('chat', 'Ses messages', 'Lui montrer mes messages · WhatsApp, Messages', '#parametres/messages')}${item('sun', 'Apparence', 'thème du système · Mika en fond', '#parametres/apparence')}${item('archive', 'Données', 'effacer les messages de ce téléphone', '#parametres/donnees')}</div>
          <div style="padding:16px"><button class="btn danger outlined block" type="button" data-dialog="deconnexion">${ico('logout')}Se déconnecter</button></div>
        </div>`,
      notes: {
        titre: 'Paramètres',
        reprend: ['En haut ce qui est à toi (le client web : compte, boîtes, Teams, téléphones, partages, services MCP).', 'Puis « Ce téléphone » : les réglages de l\'app d\'aujourd\'hui, chacun sa page.', 'Une liste à la Android : une ligne, une page.'],
        trancher: ['Deux groupes dans une seule page, ou deux entrées séparées (« Ton compte et ses accès » · « Ce téléphone ») ?'],
      },
    };
  }

  function compte() {
    return page('Compte', `<div class="set-h">Ton compte</div><div class="set-group">
        <div class="set-row" style="display:block"><label class="tf"><span>Nom affiché</span><input value="${h(D.moi.nom)}"></label><small class="muted" style="display:block;margin-top:6px;font-size:12.5px">Le nom sous lequel elle te connaît.</small></div>
        ${row('Identifiant', 'celui de la connexion, partout', `<span class="mono">${h(D.moi.login)}</span>`)}${row('Ton rôle', '', '<span class="row" style="gap:4px"><span class="tag pc">Propriétaire</span><span class="tag">Opérateur</span></span>')}
        ${row('Ce qu\'elle sait de toi', 'sous quel nom elle te reconnaît, ta fiche', `<button class="btn mk tonal sm" type="button" data-go="#chat" data-snack="« Qu'est-ce que tu sais de moi ? » est dans le champ">Lui demander</button>`)}</div>
      <div class="set-h">Mot de passe et connexions</div><div class="set-group">
        ${row('Mot de passe', '8 caractères au moins', `<button class="btn tonal sm" type="button" data-dialog="mdp">Changer</button>`)}
        <div class="li">${ico('phone')}<span class="txt"><b>Ce téléphone</b><small>samsung SM-S931B · maintenant</small></span><span class="tag ok">celui-ci</span></div>
        <div class="li">${ico('globe')}<span class="txt"><b>Chrome sur Linux</b><small>session du web · il y a 2 h</small></span></div>
        ${row('Partout', 'ferme toutes tes sessions et déconnecte tes téléphones', `<button class="btn danger text sm" type="button" data-snack="Maquette : rien n'est fermé">Tout fermer</button>`)}</div>
      <div style="padding:16px"><button class="btn filled block" type="button" data-back data-snack="Enregistré">Enregistrer</button></div>`,
    { titre: 'Paramètres · Compte', reprend: ['Le compte du client web : nom, identifiant, rôle, « Lui demander » (le chat s\'ouvre, la question posée), mot de passe, les connexions.'], trancher: ['« Enregistrer » en bas de page, ou dans la barre du haut (une coche) ?'] });
  }

  function boites() {
    const b = D.filRouge.boites;
    return page('Boîtes mail', `<div class="set-h">À toi</div><div class="set-group">${b.map((x) => `<button class="li" type="button" data-go="#parametres/boite/${x.id}"><span class="lead box">${ico('mail')}</span><span class="txt"><b>${h(x.nom)}</b><small>${h(x.adresse)} · ${h(x.sorte)}</small></span><span class="tag ok">reliée</span></button>`).join('')}</div>
      <div class="set-h">Partagée avec toi</div><div class="set-group"><div class="li"><span class="lead box">${ico('users')}</span><span class="txt"><b>Boîte de Léa</b><small>lea.moreau@gmail.com · lecture seule</small></span></div></div>
      <p class="note">Mika lit tes boîtes et prépare ce qu'on lui demande ; ce qui part dépend de la règle d'envoi de chaque boîte.</p>`,
    { titre: 'Paramètres · Boîtes mail', reprend: ['Tes boîtes, celles qu\'on te partage ; « Ajouter une boîte » en bouton flottant (IMAP, Microsoft par code d\'appareil).'], trancher: [],
      fab: `<button class="fab" type="button" data-snack="Maquette : ajouter une boîte">${ico('plus')}Ajouter</button>` });
  }
  function boite(id) {
    const b = D.filRouge.boites.find((x) => x.id === id) || D.filRouge.boites[0];
    return page(h(b.nom), `<div class="set-h">La boîte</div><div class="set-group">${row('Adresse', '', `<span class="label-s">${h(b.adresse)}</span>`)}${row('Connexion', h(b.sorte), `<button class="btn tonal sm" type="button" data-snack="Connexion réussie · 412 mails">Tester</button>`)}
        ${row('Lu à l\'ouverture', 'ouvrir un mail le marque lu', A.sw(true))}</div>
      <div class="set-h">Comment part ce que Mika y prépare</div><div class="set-group">
        ${row('Préparer d\'elle-même', 'quand son tri attend une réponse (6 par jour au plus)', A.sw(true))}
        <div class="li"><span class="lead">${av('claire', 'sm')}</span><span class="txt"><b>À Claire Dubois</b><small>préparer : oui · envoi : ton accord</small></span>${A.act('more', 'Régler', 'data-snack="La ligne se règle"')}</div>
        <div class="li"><span class="lead">${ico('users')}</span><span class="txt"><b>À Lumen Conseil (@lumen-conseil.fr)</b><small>préparer : oui · envoi : ton accord</small></span>${A.act('more', 'Régler', 'data-snack="La ligne se règle"')}</div>
        <div class="li"><span class="lead">${ico('globe')}</span><span class="txt"><b>Par défaut</b><small>préparer : si une réponse est attendue · envoi : ton accord</small></span>${A.act('more', 'Régler', 'data-snack="Le défaut se règle"')}</div>
        <button class="btn text sm" type="button" style="margin:6px 14px 10px" data-snack="Une ligne de plus">${ico('plus')}Ajouter une ligne</button></div>
      <p class="note">Qui écrit et l'ordre des lignes restent à la console (ADR 0207).</p>
      <div style="padding:8px 16px"><button class="btn danger outlined block" type="button" data-snack="Maquette : rien n'est retiré">${ico('trash')}Retirer la boîte</button></div>`,
    { titre: 'Paramètres · une boîte', reprend: ['La boîte (adresse, tester, lu à l\'ouverture), puis comment part ce qu\'elle y prépare, ligne par ligne et par défaut (ADR 0207).'], trancher: ['Les règles d\'envoi sur un téléphone : utile, ou réservé au web ?'] });
  }
  const liste = (titre, lignes, n) => page(titre, `<div class="set-group">${lignes.join('')}</div>${n && n.apres ? n.apres : ''}`, n);
  const teams = () => liste('Comptes Teams', [`<div class="li"><span class="lead box">${ico('teams')}</span><span class="txt"><b>Lumen Conseil</b><small>a.moreau@lumen-conseil.fr · extension vue il y a 4 min</small></span><span class="tag ok">relié</span></div>`,
    row('Clé de l\'extension', 'montrée une fois, à la création', `<button class="btn tonal sm" type="button" data-snack="Nouvelle clé : elle ne se montre qu'une fois">Renouveler</button>`),
    row('Comment part ce qu\'elle prépare', '« Café » : seule · ailleurs : ton accord', `<button class="btn text sm" type="button" data-snack="Les règles d'envoi s'ouvrent">Régler</button>`)],
  { titre: 'Paramètres · Comptes Teams', reprend: ['Tes comptes Teams, la clé de leur extension, leurs règles d\'envoi.'] });
  const telephones = () => liste('Téléphones', [`<div class="li"><span class="lead box">${ico('phone')}</span><span class="txt"><b>Ce téléphone</b><small>samsung SM-S931B · notifié fermé</small></span><span class="tag ok">celui-ci</span></div>`,
    `<div class="li"><span class="lead box">${ico('phone')}</span><span class="txt"><b>Google Pixel 7a</b><small>vu hier à 22:10</small></span><button class="btn danger text sm" type="button" data-snack="Maquette : rien n'est révoqué">Révoquer</button></div>`],
  { titre: 'Paramètres · Téléphones', reprend: ['Tes téléphones ; révoquer celui qu\'on a perdu (il efface ce qu\'il gardait à sa prochaine connexion).'] });
  const partages = () => liste('Partages', [`<div class="li"><span class="lead box">${ico('mail')}</span><span class="txt"><b>Rando Cassel</b><small>partagée avec Julien · lecture</small></span>${A.act('more', 'Régler', 'data-snack="Le partage se règle"')}</div>`,
    `<div class="li"><span class="lead box">${ico('plug')}</span><span class="txt"><b>Météo Locale</b><small>partagée avec Léa · utiliser</small></span>${A.act('more', 'Régler', 'data-snack="Le partage se règle"')}</div>`],
  { titre: 'Paramètres · Partages', reprend: ['Ce que tu partages (une boîte, un service) et à quel niveau.'], fab: `<button class="fab" type="button" data-snack="Maquette : partager">${ico('share')}Partager</button>` });
  const mcp = () => liste('Services MCP', [`<div class="li"><span class="lead box">${ico('plug')}</span><span class="txt"><b>Météo Locale</b><small>https://meteo.example/mcp · 3 outils</small></span><span class="tag ok">branché</span></div>`,
    row('meteo_previsions', 'prévisions d\'un lieu', '<div class="seg" data-seg style="height:32px;width:150px"><button type="button" aria-pressed="false">Coupé</button><button type="button" aria-pressed="true">Lit</button><button type="button" aria-pressed="false">Agit</button></div>'),
    `<div class="li"><span class="lead box">${ico('calendar')}</span><span class="txt"><b>Agenda de Léa</b><small>partagé avec toi · lecture</small></span></div>`],
  { titre: 'Paramètres · Services MCP', reprend: ['Brancher un service distant, régler chacun de ses outils (coupé, il lit, il agit), le retirer ; ceux qu\'on te partage.'], fab: `<button class="fab" type="button" data-snack="Maquette : brancher un service">${ico('plus')}Brancher</button>` });

  // Ce téléphone : les réglages de l'app d'aujourd'hui (SettingsScreen.kt), mots compris.
  const notifications = () => page('Notifications', `<div class="set-group">${row('Messages de Mika', 'Autorisées', A.sw(true))}
      ${row('Application fermée', 'Ses messages t\'arrivent par Firebase, chiffrés pour ce téléphone seul. Aucune connexion ne reste ouverte : la batterie n\'en souffre pas.', '<span class="tag ok">active</span>')}
      ${row('Lui dire quand j\'ai lu', 'Mika sait si tu as vu ce qu\'elle t\'a écrit. Seulement jusqu\'où tu as lu, jamais quand tu es en ligne.', A.sw(true))}
      ${row('Ses brouillons à relire', 'Une notification quand un brouillon de mail ou de Teams attend ta décision.', A.sw(true))}</div>`,
  { titre: 'Ce téléphone · Notifications', reprend: ['Les réglages d\'aujourd\'hui ; un seul nouveau : être prévenu quand un de ses brouillons attend ta décision.'], trancher: ['Ce nouveau réglage (notifier ses brouillons) : le veux-tu, et allumé par défaut ?'] });
  const position = () => page('Position', `<div class="set-group">${row('Lui dire où je suis', 'Application ouverte, ta position (les coordonnées exactes et le nom du lieu) part à Mika. Elle ne la regarde que pendant vos conversations en tête-à-tête, et une bulle 📍 te le montre à chaque fois.', A.sw(true))}</div>`,
    { titre: 'Ce téléphone · Position', reprend: ['Le réglage d\'aujourd\'hui (ADR 0119), inchangé.'] });
  const messages = () => page('Ses messages', `<div class="set-group">${row('Lui montrer mes messages', 'Les messages que WhatsApp et Messages affichent sur ce téléphone partent à Mika. Elle peut te proposer une réponse, qui ne part jamais sans ton geste.', A.sw(true))}
      ${row('WhatsApp', 'WhatsApp et WhatsApp Business', A.sw(true))}${row('Messenger', 'Les conversations de Messenger (Facebook)', A.sw(true))}${row('Messages', 'Tes SMS, dans Messages de Google ou de Samsung', A.sw(true))}${row('Les groupes aussi', 'Les conversations de groupe partent aussi : elles sont bavardes.', A.sw(true))}
      ${row('Envoi', 'Tout est parti (dernier envoi : 14:09).', '')}</div>`,
  { titre: 'Ce téléphone · Ses messages', reprend: ['Le réglage d\'aujourd\'hui (ADR 0120), inchangé ; ce qu\'il a lu se voit dans Plus › Téléphone.'] });
  const apparence = () => page('Apparence', `<div class="set-group"><div class="set-row" style="display:block"><b style="font-weight:400;font-size:16px">Thème</b><div class="seg" data-seg style="margin-top:10px"><button type="button" aria-pressed="true">Système</button><button type="button" aria-pressed="false">Clair</button><button type="button" aria-pressed="false">Sombre</button></div></div>
      ${row('Couleurs dynamiques', 'Suivre les couleurs du fond d\'écran.', A.sw(false))}${row('Mika en fond', 'Sa 3D derrière la conversation : elle suit son humeur, s\'endort la nuit.', A.sw(true))}</div>`,
  { titre: 'Ce téléphone · Apparence', reprend: ['Les réglages d\'aujourd\'hui.'], trancher: ['Couleurs dynamiques : si elles sont allumées, l\'indigo cède la place au fond d\'écran, mais le rose de Mika reste. D\'accord ?'] });
  const donnees = () => page('Données', `<div class="set-group">${row('Effacer les messages de ce téléphone', 'La conversation reste sur le serveur et revient à la prochaine connexion.', `<button class="btn danger text sm" type="button" data-snack="Maquette : rien n'est effacé">Effacer</button>`)}</div>`,
    { titre: 'Ce téléphone · Données', reprend: ['Le réglage d\'aujourd\'hui.'] });

  const PAGES = { compte, boites, teams, telephones, partages, mcp, notifications, position, messages, apparence, donnees };
  A.ecran('parametres', (args) => (args[0] === 'boite' ? boite(args[1]) : PAGES[args[0]] ? PAGES[args[0]]() : racine()));
  A.dialogs.mdp = () => A.dialog('Changer le mot de passe', '<label class="tf" style="margin-bottom:14px"><span>Mot de passe actuel</span><input type="password"></label><label class="tf"><span>Nouveau mot de passe</span><input type="password"></label>',
    '<button class="btn text" type="button" data-close>Annuler</button><button class="btn text" type="button" data-close data-snack="Mot de passe changé">Changer</button>');
  A.index('Plus et Paramètres', [['Plus', '#plus'], ['Paramètres', '#parametres'], ['Compte', '#parametres/compte'], ['Boîtes', '#parametres/boites'], ['Une boîte', '#parametres/boite/pro'], ['Services MCP', '#parametres/mcp'], ['Notifications', '#parametres/notifications']]);
})();
