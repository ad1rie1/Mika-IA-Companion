/* Paramètres : ce que la personne connectée règle pour elle-même. Gabarit du paramétrage : une ligne par réglage,
   son nom et son aide à gauche, sa valeur à droite ; une seule barre d'enregistrement par formulaire.
   Aujourd'hui tout cela n'existe que dans la console, pour un opérateur : voir les notes. */
(function () {
  const { h, ico, av } = M;
  const D = M.D;
  const BOITES = D.filRouge.boites;

  const row = (nom, aide, valeur, cls) => `<div class="set-row${cls ? ' ' + cls : ''}"><div class="set-label"><b>${nom}</b>${aide ? `<p>${aide}</p>` : ''}</div><div class="set-value">${valeur}</div></div>`;
  const sw = (on, attrs) => `<label class="switch"><input type="checkbox"${on ? ' checked' : ''}${attrs || ''}><i></i></label>`;
  const seg = (nom, choix, actif) => `<div class="seg" role="group" data-seg="${nom}">${choix.map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${k === actif}">${h(l)}</button>`).join('')}</div>`;
  // Une section ; dans une page à sous-onglets, seule la section choisie se montre. Toutes ont la même grille.
  const section = (titre, corps, aside, deux, id) => `<section class="set-sec"${id ? ` data-sous="${id}"` : ''}><div class="set-sec-head"><h2>${titre}</h2>${aside ? `<div class="ph-actions">${aside}</div>` : ''}</div><div class="set-grid two">${corps}</div></section>`;
  const sous = {};
  const sousOnglets = (page, liste) => {
    const actif = sous[page] || liste[0][0];
    return `<nav class="sub-seg" data-souspage="${page}">${liste.map(([k, l]) => `<button type="button" data-sousv="${k}" aria-pressed="${k === actif}">${h(l)}</button>`).join('')}</nav>`;
  };
  const montrerSous = (root, page) => {
    const nav = root.querySelector(`[data-souspage="${page}"]`);
    if (!nav) return;
    const actif = sous[page] || nav.querySelector('button').dataset.sousv;
    root.querySelectorAll('[data-sous]').forEach((x) => { x.hidden = x.dataset.sous !== actif; });
  };

  // ── Compte ───────────────────────────────────────────────────────────
  function vueCompte() {
    const theme = document.documentElement.dataset.themeChoice || 'system';
    return `<form class="set-page" data-form data-page="compte">
      ${sousOnglets('compte', [['compte', 'Ton compte'], ['securite', 'Mot de passe et connexions'], ['apparence', 'Apparence']])}
      ${section('Ton compte', row('Nom affiché', 'Le nom sous lequel elle te connaît dès la création du compte.', `<input value="${h(D.moi.nom)}">`)
        + row('Identifiant', 'Celui de la connexion, sur le web comme sur le téléphone.', `<span class="mono">${h(D.moi.login)}</span><span class="tag">ne change pas</span>`)
        + row('Ton rôle', 'Un opérateur parle avec elle et ouvre aussi la console : tout ce qu\'elle vit, sa configuration, les approbations et les apps.', '<span class="tag accent">Propriétaire</span><span class="tag">Opérateur</span>')
        + row('Ce qu\'elle sait de toi', 'Sous quel nom elle te reconnaît, et ta fiche dans sa mémoire.', `<b>Adrien</b><a class="btn xs ghost" href="#chat">${ico('sparkle', 'xs')}Ce qu'elle fait</a>`), '', true, 'compte')}
      ${section('Mot de passe et connexions', row('Mot de passe', '8 caractères au moins, pas seulement des chiffres, sans l\'identifiant dedans.', `<button class="btn sm" type="button" data-mdp>${ico('key', 'sm')}Changer le mot de passe</button>`)
        + row('Partout', 'Ferme toutes tes sessions et déconnecte tes téléphones.', `<button class="btn sm danger" type="button" data-partout>${ico('logout', 'sm')}Se déconnecter partout</button>`)
        + `<div class="set-row full"><table class="tbl"><thead><tr><th>Appareil</th><th>Sorte</th><th>Dernier usage</th><th></th></tr></thead><tbody>
          <tr><td>${ico('monitor', 'sm')} <b>Ce navigateur</b> · Chrome sur Linux</td><td class="small">session du web</td><td class="small">maintenant</td><td class="actions"><span class="tag ok">celui-ci</span></td></tr>
          <tr><td>${ico('phone', 'sm')} <b>Android · samsung SM-S931B</b></td><td class="small">Téléphone (notifié fermé)</td><td class="small">il y a 3 min</td><td class="actions"><a class="btn xs" href="#parametres/telephones">Voir</a></td></tr>
        </tbody></table></div>`, '', true, 'securite')}
      ${section('Apparence', row('Thème', 'Celui du système, ou toujours clair, ou toujours sombre.', seg('theme', [['system', 'Système'], ['light', 'Clair'], ['dark', 'Sombre']], theme))
        + row('Mika dans un coin', 'Sa VRM, son humeur et ce qu\'elle fait, sur chaque écran. Tu la glisses vers un autre coin ; chaque écran retient le sien.', sw(true))
        + row('Sa taille au départ', 'Réduite à son visage, ou en buste.', seg('taille', [['mini', 'Visage'], ['normal', 'Buste'], ['large', 'Grand']], 'normal'))
        + row('Son modèle', 'La VRM complète est la plus belle ; l\'allégée charge plus vite ; les portraits ne demandent pas de 3D.',
          `<select><option>VRM complète (97 Mio)</option><option>VRM allégée pour le mobile (28 Mio)</option><option>Portraits pré-rendus (3,8 Mio)</option></select>`)
        + row('Sa voix', 'Lire ses réponses à voix haute, avec la voix du navigateur. Sans elle, sa bouche bouge au rythme de ses bulles.', sw(false))
        + row('Quand elle t\'écrit la première', 'Te prévenir dans ce navigateur, même onglet fermé.', sw(false)), '', true, 'apparence')}
    </form>`;
  }

  // ── Comptes mail ─────────────────────────────────────────────────────
  const ETAT_B = { pro: ['ok', 'prête', 'relevée il y a 4 min · 2 non lus'], perso: ['ok', 'prête', 'relevée il y a 4 min · 1 non lu'], asso: ['warn', 'erreur', 'dernier relevé il y a 2 h : mot de passe refusé'] };
  const VOIX = { pro: 'à ta place', perso: 'à ta place', asso: 'en assistante' };
  function vueComptesMail(item) {
    if (item && BOITES.some((b) => b.id === item)) return ficheBoite(BOITES.find((b) => b.id === item));
    return `<div class="set-page">
      <p class="lede">Tes boîtes aux lettres. Elle les relève, en trie le courrier, et y prépare des réponses selon ce que tu règles ici. Une boîte n'est qu'à toi, sauf si tu la partages.</p>
      <div class="acc-cards">${BOITES.map((b) => { const e = ETAT_B[b.id]; return `<div class="acc-card">
        <span class="acc-ico c${b.couleur}">${ico('mail')}</span>
        <div class="grow"><div class="row"><b>${h(b.nom)}</b><span class="muted">${h(b.adresse)}</span></div>
          <div class="row wrap acc-tags"><span class="tag ${e[0]}">${h(e[1])}</span><span class="tag">${h(b.sorte)}</span><span class="tag mika">elle y écrit ${h(VOIX[b.id])}</span>
            ${b.partageeAvec ? `<span class="tag accent">${ico('users', 'xs')}partagée avec ${h(M.who(b.partageeAvec[0][0]).court)} · ${h(b.partageeAvec[0][1])}</span>` : ''}</div>
          <p class="small ${e[0] === 'warn' ? 'warn-txt' : 'muted'}">${h(e[2])}</p></div>
        ${e[0] === 'warn' ? `<button class="btn sm" type="button" data-tester="${b.id}">${ico('refresh', 'sm')}Tester</button>` : ''}
        <a class="btn sm" href="#parametres/comptes-mail/${b.id}">Régler</a>
        <button class="btn sm icon ghost" type="button" data-boite-menu="${b.id}" title="Plus">${ico('more', 'sm')}</button></div>`; }).join('')}</div>
      <h2 class="section-title shared-title">Partagée avec toi <span class="cnt">1</span></h2>
      <div class="acc-cards"><div class="acc-card"><span class="acc-ico c7">${ico('lock')}</span><div class="grow"><div class="row"><b>Boîte de Léa</b><span class="muted">lea.moreau@gmail.com</span></div>
        <p class="small muted">Léa Moreau te l'a ouverte en lecture le 28 octobre. Tu la lis dans Mail ; tu ne peux ni répondre ni ranger.</p></div>
        <a class="btn sm" href="#mail/messages/m-lea-colis">Ouvrir</a><button class="btn sm ghost" type="button" data-masquer>Ne plus l'afficher</button></div></div>
    </div>`;
  }
  function ficheBoite(b) {
    return `<form class="set-page" data-form data-page="boite">
      <a class="back-link" href="#parametres/comptes-mail">${ico('chev-left', 'sm')}Comptes mail</a>
      <div class="fiche-head"><span class="acc-ico c${b.couleur}">${ico('mail')}</span><div><h2>${h(b.nom)}</h2><p class="muted">${h(b.adresse)} · ${h(b.sorte)}</p></div></div>
      ${sousOnglets('boite', [['boite', 'La boîte'], ['connexion', 'Connexion'], ['mika', 'Ce que Mika en fait'], ['partage', 'Partage']])}
      ${section('La boîte', row('Adresse', '', `<input value="${h(b.adresse)}">`) + row('Nom court', 'Comme elle l\'appelle : « ta boîte Pro ».', `<input value="${h(b.nom)}">`)
        + row('Nom affiché', 'Sous quel nom partent les mails écrits à ta place.', '<input value="Adrien Moreau">')
        + row('À qui', 'Une boîte est à toi, à elle, ou à une personne qui a un compte : ses outils ne voient que les boîtes de qui est en face.', '<select><option>Toi</option><option>Mika (sa boîte à elle)</option><option>Léa Moreau</option><option>Julien Roux</option></select>'), '', true, 'boite')}
      ${section('Connexion', row('Connexion', '', b.id === 'perso' ? '<select><option>par un compte Microsoft (Hotmail, Outlook.com, Live)</option><option>par mot de passe</option></select>' : '<select><option>par mot de passe</option><option>par un compte Microsoft (Hotmail, Outlook.com, Live)</option></select>')
        + row('Lire (IMAP)', b.id === 'pro' ? 'La passerelle DavMail sur cette machine (O365Graph).' : '', b.id === 'pro' ? '<input value="127.0.0.1" class="w-host"><input value="1143" class="w-port"><label class="row small">' + sw(false) + 'SSL</label>' : b.id === 'perso' ? '<input value="outlook.office365.com" class="w-host"><input value="993" class="w-port">' : '<input value="imap.gmail.com" class="w-host"><input value="993" class="w-port">')
        + row('Envoyer (SMTP)', '', b.id === 'pro' ? '<input value="127.0.0.1" class="w-host"><input value="1025" class="w-port">' : b.id === 'perso' ? '<input value="smtp-mail.outlook.com" class="w-host"><input value="587" class="w-port">' : '<input value="smtp.gmail.com" class="w-host"><input value="587" class="w-port">')
        + row(b.id === 'perso' ? 'Compte Microsoft' : 'Mot de passe', b.id === 'perso' ? 'Connecté le 31 octobre par code d\'appareil (OAuth2).' : b.id === 'asso' ? 'Un mot de passe d\'application de préférence.' : '', b.id === 'perso' ? '<span class="tag ok">connecté</span><button class="btn xs" type="button">Se reconnecter</button>' : '<input type="password" value="••••••••••">'), '', true, 'connexion')}
      ${section('Ce que Mika en fait', row('Dossiers relevés', 'Dans un dossier relevé, elle remarque ce qui arrive. Les autres sont seulement synchronisés.', '<label class="row small"><input type="checkbox" checked> Réception</label><label class="row small"><input type="checkbox"> Clients</label><label class="row small"><input type="checkbox"> Archives</label>')
        + row('Elle écrit', 'En son nom (« Mika »), en assistante (« Mika pour Adrien »), ou à ta place (comme toi).', seg('voix', [['nom', 'En son nom'], ['assistante', 'En assistante'], ['place', 'À ta place']], VOIX[b.id] === 'à ta place' ? 'place' : 'assistante'))
        + row('Son ton', 'Ce qu\'elle doit savoir pour écrire dans cette boîte.', '<textarea rows="2">Vouvoyer les clients, tutoyer l\'équipe. Phrases courtes.</textarea>')
        + row('Préparer d\'elle-même', 'Quand son tri attend une réponse, elle prépare un brouillon (6 par jour au plus).', sw(b.id !== 'perso'))
        + row('Comment ça part', 'Ce qu\'elle prépare part seulement après ton accord, ou jamais.', seg('part', [['accord', 'Ton accord'], ['non', 'Jamais']], 'accord'))
        + row('Signature', '', '<textarea rows="2">-- \nAdrien Moreau · Lumen Conseil</textarea>'), '', true, 'mika')}
      ${section('Partage', row('Avec qui', 'La personne verra cette boîte dans son propre Mika.', `${b.partageeAvec ? `<span class="chip">${av('julien', 'xs')}Julien Roux · lecture</span>` : '<span class="muted small">Personne</span>'}<a class="btn xs" href="#parametres/partages">Gérer les partages</a>`), '', true, 'partage')}
    </form>`;
  }
  function ajouterCompte() {
    const el = M.modal({ titre: 'Ajouter un compte mail', taille: 'wide',
      corps: `<div class="providers">${[['ms', 'Microsoft', 'Outlook.com, Hotmail, Live : connexion par code d\'appareil (OAuth2)', 'globe'],
        ['davmail', 'Exchange pro', 'Ta boîte de travail par la passerelle DavMail (O365Graph) sur cette machine', 'server'],
        ['gmail', 'Gmail', 'Avec un mot de passe d\'application', 'mail'], ['imap', 'Autre', 'N\'importe quelle boîte IMAP et SMTP', 'settings']].map(([k, t, d, i]) =>
        `<button type="button" class="provider" data-prov="${k}">${ico(i, 'lg')}<b>${h(t)}</b><span>${h(d)}</span></button>`).join('')}</div>
        <div class="prov-step" data-step hidden></div>`,
      pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button>' });
    M.on(el, '[data-prov]', 'click', (e, b) => {
      el.querySelectorAll('.provider').forEach((p) => p.classList.toggle('on', p === b));
      const st = el.querySelector('[data-step]'); st.hidden = false;
      st.innerHTML = b.dataset.prov === 'ms'
        ? `<div class="set-grid">${row('Adresse', '', '<input placeholder="prenom.nom@outlook.fr">')}${row('Se connecter à Microsoft', '', `<button class="btn sm primary" type="button" data-code>${ico('key', 'sm')}Obtenir un code</button>`)}</div><div class="device" data-device hidden></div>`
        : `<div class="set-grid">${row('Adresse', '', '<input placeholder="toi@exemple.fr">')}${row('Serveur IMAP', '', `<input value="${b.dataset.prov === 'gmail' ? 'imap.gmail.com' : b.dataset.prov === 'davmail' ? '127.0.0.1' : ''}" class="w-host"><input value="${b.dataset.prov === 'davmail' ? '1143' : '993'}" class="w-port">`)}
          ${row('Serveur SMTP', '', `<input value="${b.dataset.prov === 'gmail' ? 'smtp.gmail.com' : b.dataset.prov === 'davmail' ? '127.0.0.1' : ''}" class="w-host"><input value="${b.dataset.prov === 'davmail' ? '1025' : '587'}" class="w-port">`)}
          ${row('Mot de passe', b.dataset.prov === 'gmail' ? 'Un mot de passe d\'application, pas celui de ton compte.' : '', '<input type="password">')}
          ${row('', '', `<button class="btn sm primary" type="button" data-test-new>${ico('refresh', 'sm')}Tester et ajouter</button>`)}</div>`;
    });
    M.on(el, '[data-code]', 'click', () => {
      const d = el.querySelector('[data-device]'); d.hidden = false;
      d.innerHTML = `${ico('key')}<div><b>Ouvre microsoft.com/devicelogin et entre le code</b><div class="code">K7QF-2MXD</div>
        <span class="small muted">Valable jusqu'à 14:35. Elle se connecte dès que c'est fait.</span></div><i class="spin"></i>`;
    });
    M.on(el, '[data-test-new]', 'click', () => { M.fermerModal(); M.toast('Lecture : ok (9 dossiers) ; envoi : ok. La boîte est ajoutée.', { ico: 'check' }); });
  }

  // ── Teams ────────────────────────────────────────────────────────────
  function vueTeams() {
    const regles = [['Marc', 'oui', 'ton accord'], ['Projet Lumen', 'oui', 'brouillon']];
    const part = (v) => `<select class="sm-select">${[['brouillon', 'brouillon — c\'est toi qui l\'envoies'], ['ton accord', 'ton accord'], ['seule', 'seule'], ['non', 'non']].map(([k, l]) => `<option${k === v ? ' selected' : ''}>${l}</option>`).join('')}</select>`;
    return `<form class="set-page" data-form data-page="teams">
      <div class="ext-card"><span class="acc-ico c0">${ico('plug')}</span><div class="grow"><div class="row"><b>Extension « Mika · Teams »</b><span class="tag ok">${ico('check', 'xs')}dernier envoi il y a 2 min</span></div>
        <p class="small muted">Compte « Teams pro (Lumen) » · ton nom dans Teams : Adrien Moreau · 37 messages remarqués. Le reste (relève toutes les 30 s, pause, exclusions) se lit dans la fenêtre de l'extension.</p></div>
        <a class="btn sm" href="#teams/discussions">Voir les discussions</a></div>
      ${sousOnglets('teams', [['compte', 'Ton compte Teams'], ['regles', 'Comment ça part'], ['extension', 'L\'extension']])}
      ${section('Ton compte Teams', row('Nom affiché', 'Comme elle l\'appelle.', '<input value="Teams pro (Lumen)">')
        + row('À qui', 'Un compte est à toi, à elle, ou à une personne qui a un compte.', '<select><option>Toi</option><option>Mika (son compte à elle)</option><option>Léa Moreau</option></select>')
        + row('Ton nom', 'Sous quel nom elle écrit à ta place.', '<input value="Adrien Moreau">')
        + row('Ton', '', '<input value="tutoiement entre collègues, bref, direct">')
        + row('Consignes', 'Ce qu\'elle ne doit jamais faire à ta place.', '<textarea rows="2">Ne promets jamais de date de livraison à ma place ; ne réponds pas aux RH.</textarea>')
        + row('Signer ses réponses', 'Le serveur ajoute la signature après une ligne vide.', `${sw(false)}<input value="— rédigé avec Mika">`), '', true, 'compte')}
      ${section('Comment part ce qu\'elle prépare', `<div class="set-row full"><table class="tbl"><thead><tr><th>#</th><th>Qui écrit (ou quelle discussion)</th><th>Préparer d'elle-même</th><th>Comment ça part</th><th></th></tr></thead><tbody>
          ${regles.map(([q, p, v], k) => `<tr><td class="muted">${k + 1}</td><td><input value="${h(q)}"></td><td>${seg('prep' + k, [['oui', 'Oui'], ['non', 'Non']], p)}</td><td>${part(v)}</td><td class="actions"><button class="btn xs ghost danger" type="button">Retirer</button></td></tr>`).join('')}
          <tr class="def"><td class="muted">—</td><td><b>Par défaut</b> <span class="small muted">quand aucune ligne au-dessus ne correspond</span></td><td>${seg('prepd', [['oui', 'Oui'], ['non', 'Non']], 'non')}</td><td>${part('ton accord')}</td><td></td></tr>
        </tbody></table>
        <div class="row tbl-help"><button class="btn xs" type="button">${ico('plus', 'xs')}Ajouter une ligne</button><span class="small muted">Lues de haut en bas : la première qui correspond décide. Ton accord : une carte dans le chat, valable 2 h.</span></div></div>`, '', true, 'regles')}
      ${section('Brancher l\'extension', row('Ta clé', 'Montrée une fois à sa création ; seule son empreinte est gardée. L\'extension s\'en sert pour pousser ce que Teams reçoit et relever ce qui part.', `<code class="key">mtk_Q7xr••••••••••</code><span class="small muted">définie le 3 nov.</span><button class="btn xs ghost danger" type="button" data-regen>Régénérer</button>`)
        + row('L\'extension', 'Chrome, mode développeur : « Charger l\'extension non empaquetée », puis colle ta clé dans ses options. Un Teams par navigateur (ou par profil).', `<button class="btn sm" type="button" data-zip>${ico('download', 'sm')}Télécharger (.zip)</button>`), '', true, 'extension')}
    </form>`;
  }

  // ── Téléphones ───────────────────────────────────────────────────────
  function qr() {
    // Un QR code dessiné (motif fixe) : la maquette ne code pas d'adresse.
    let cells = '';
    const n = 25, s = 6;
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const coin = (x < 7 && y < 7) || (x >= n - 7 && y < 7) || (x < 7 && y >= n - 7);
      const on = coin ? ((x % (n - 7) === 0 || x % (n - 7) === 6 || y % (n - 7) === 0 || y % (n - 7) === 6) || ((x % (n - 7)) >= 2 && (x % (n - 7)) <= 4 && (y % (n - 7)) >= 2 && (y % (n - 7)) <= 4)) : ((x * 7 + y * 13 + x * y) % 5 < 2);
      if (on) cells += `<rect x="${x * s}" y="${y * s}" width="${s}" height="${s}"/>`;
    }
    return `<svg class="qr" viewBox="0 0 ${n * s} ${n * s}" aria-label="QR code de l'APK">${cells}</svg>`;
  }
  function vueTelephones() {
    const apps = [['WhatsApp', true], ['WhatsApp Business', true], ['Messages', true], ['Signal', false], ['Telegram', false], ['Colissimo', true], ['Agenda', true], ['Strava', true], ['Instagram', false]];
    return `<form class="set-page" data-form>
      <div class="apk-card">${qr()}<div class="grow"><h2>Mika pour Android</h2><p class="text-2">Version 0.1.0 · 31 Mo · signée avec la clé de débogage</p>
        <p class="small muted">Le lien demande d'être connecté : ouvre-le depuis ton téléphone, connecté à Mika, ou scanne le code. Android te demandera d'autoriser l'installation depuis ton navigateur, puis l'app te demandera ton identifiant et ton mot de passe.</p>
        <div class="row"><button class="btn" type="button" data-copier>${ico('link', 'sm')}Copier le lien</button></div></div></div>
      ${section('Tes téléphones connectés', `<div class="set-row full"><table class="tbl"><thead><tr><th>Libellé</th><th>Sorte</th><th>Obtenu par</th><th>Créé</th><th>Dernier usage</th><th>Tu lui montres</th><th></th></tr></thead><tbody>
          <tr><td>${ico('phone', 'sm')} <b>Android · samsung SM-S931B</b> <span class="tag ok">actif</span></td><td class="small">Téléphone (notifié fermé)</td><td class="small">connexion (identifiant et mot de passe)</td>
            <td class="small">12 octobre</td><td class="small">il y a 3 min</td><td class="small">tes messages · ta position</td><td class="actions"><button class="btn xs danger" type="button" data-revoquer="Android · samsung SM-S931B">Révoquer</button></td></tr>
          <tr><td>${ico('phone', 'sm')} <b>Android · Google Pixel 7a</b> <span class="tag ok">actif</span></td><td class="small">Téléphone (notifié fermé)</td><td class="small">connexion (identifiant et mot de passe)</td>
            <td class="small">3 novembre</td><td class="small">hier à 22:10</td><td class="small">tes messages</td><td class="actions"><button class="btn xs danger" type="button" data-revoquer="Android · Google Pixel 7a">Révoquer</button></td></tr>
          <tr class="revoked"><td>${ico('phone', 'sm')} <b>Android · Google Pixel 7</b> <span class="tag">révoqué</span></td><td class="small">Téléphone (sans notifications)</td><td class="small">connexion (identifiant et mot de passe)</td>
            <td class="small">2 septembre</td><td class="small">29 septembre</td><td class="small">—</td><td></td></tr></tbody></table>
          <p class="small muted tbl-help">Révoquer ferme ses connexions ; un téléphone révoqué ne reçoit plus rien, même application fermée.</p></div>`)}
      ${section('Ce que ton téléphone lui montre', row('Les apps lues', 'Leurs notifications partent à Mika, qui s\'en souvient. Tu choisis app par app.', `<div class="app-checks">${apps.map(([a, on]) => `<label class="row small"><input type="checkbox"${on ? ' checked' : ''}> ${h(a)}</label>`).join('')}</div>`, 'full')
        + row('Jamais', 'Fixé dans le code, quoi que tu coches.', '<span class="tag">banque</span><span class="tag">codes de connexion</span><span class="tag">mots de passe à usage unique</span>')
        + row('Sur le téléphone', 'Ces deux interrupteurs vivent sur le téléphone, coupés par défaut.', '<span class="tag ok">Lui montrer mes messages : oui</span><span class="tag ok">Lui dire où je suis : oui</span>'))}
    </form>`;
  }

  // ── Partages ─────────────────────────────────────────────────────────
  const PARTAGES = [
    { quoi: 'Boîte « Rando Cassel »', sous: 'rando.cassel@gmail.com', ico: 'mail', qui: 'julien', niveau: 'Lire', depuis: '2 octobre' },
    { quoi: 'Service « Météo Locale »', sous: 'meteo · 2 outils', ico: 'server', qui: 'lea', niveau: 'S\'en servir', depuis: '19 octobre' },
  ];
  function vuePartages() {
    return `<div class="set-page">
      <p class="lede">Ce que tu partages apparaît dans le Mika de la personne, à son nom : elle le voit dans son propre Mika. Mika ne lui en dit pas plus que ce que tu ouvres, et tu retires un partage quand tu veux.</p>
      <h2 class="section-title">Ce que tu partages <span class="cnt">${PARTAGES.length}</span></h2>
      <table class="tbl"><thead><tr><th>Quoi</th><th>Avec</th><th>Ce que la personne peut</th><th>Depuis</th><th></th></tr></thead><tbody>
      ${PARTAGES.map((p) => `<tr><td><div class="row">${ico(p.ico, 'sm')}<div><b>${h(p.quoi)}</b><div class="tiny muted">${h(p.sous)}</div></div></div></td>
        <td><div class="row">${av(p.qui, 'sm')}${h(M.who(p.qui).nom)}</div></td><td><span class="tag accent">${h(p.niveau)}</span></td><td class="small">${h(p.depuis)}</td>
        <td class="actions"><button class="btn xs" type="button" data-partager>Modifier</button> <button class="btn xs ghost danger" type="button" data-retirer>Retirer</button></td></tr>`).join('')}
      </tbody></table>
      <h2 class="section-title shared-title">Partagé avec toi <span class="cnt">1</span></h2>
      <table class="tbl"><thead><tr><th>Quoi</th><th>De</th><th>Ce que tu peux</th><th>Depuis</th><th></th></tr></thead><tbody>
        <tr><td><div class="row">${ico('mail', 'sm')}<div><b>Boîte de Léa</b><div class="tiny muted">lea.moreau@gmail.com</div></div></div></td><td><div class="row">${av('lea', 'sm')}Léa Moreau</div></td>
          <td><span class="tag">Lire</span></td><td class="small">28 octobre</td><td class="actions"><a class="btn xs" href="#mail/messages/m-lea-colis">Ouvrir</a></td></tr></tbody></table>
    </div>`;
  }
  function partager() {
    const el = M.modal({ titre: 'Partager', taille: 'narrow',
      corps: `<div class="stack">
        <label class="field"><span>Quoi</span><select data-quoi><option>Boîte « Pro »</option><option>Boîte « Perso »</option><option selected>Boîte « Rando Cassel »</option><option>Ton Teams</option><option>Service « Météo Locale »</option><option>Service « Factures »</option></select></label>
        <label class="field"><span>Avec qui</span><select data-qui><option>Julien Roux</option><option>Léa Moreau</option><option disabled>Claire Dubois — pas de compte</option></select></label>
        <div class="field"><span>Ce que la personne peut</span>${seg('niveau', [['lire', 'Lire'], ['preparer', 'Lire et préparer'], ['servir', 'S\'en servir']], 'lire')}</div>
        <div class="info-line small" data-phrase>${ico('info', 'sm')}<span></span></div></div>`,
      pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>Partager</button>' });
    const phrase = () => {
      const quoi = el.querySelector('[data-quoi]').value, qui = el.querySelector('[data-qui]').value.split(' ')[0];
      const n = (el.querySelector('[data-seg="niveau"] [aria-pressed="true"]') || {}).dataset || {};
      const service = quoi.startsWith('Service'), teams = quoi.startsWith('Ton Teams');
      const ou = service ? 'dans ses Outils' : teams ? 'dans son Teams' : 'dans son Mail';
      const quoiDit = quoi.replace(/^Boîte /, '').replace(/^Service /, '');
      const peut = { lire: 'en lecture seule : ni répondre ni ranger', preparer: 'en lecture, et Mika pourra lui préparer des brouillons que tu approuveras', servir: 'pour que Mika s\'en serve pour lui ou elle, en tête-à-tête' }[n.v || 'lire'];
      el.querySelector('[data-phrase] span').textContent = `${qui} verra ${quiDit(quoiDit)} ${ou}, ${peut}.`;
    };
    const quiDit = (x) => x;
    el.addEventListener('change', phrase);
    el.addEventListener('mika:seg', phrase);
    phrase();
    el.querySelector('[data-ok]').addEventListener('click', () => { M.fermerModal(); M.toast(`Partagé : ${el.querySelector('[data-qui]').value.split(' ')[0]} le voit dans son Mika.`, { ico: 'users' }); });
  }

  // ── Services MCP ─────────────────────────────────────────────────────
  const SERVEURS = [
    { id: 'meteo', titre: 'Météo Locale', nom: 'meteo', adr: 'https://meteo.example/mcp', auth: 'sans authentification', etat: ['ok', 'connecté'], outils: '2 / 2', avec: 'Léa Moreau', garde: 'un souvenir' },
    { id: 'factures', titre: 'Factures', nom: 'factures', adr: 'http://factures.lan/mcp', auth: 'en-têtes secrets (Authorization, X-Tenant)', etat: ['ok', 'connecté'], outils: '2 / 3', revoir: 1, avec: '—', garde: 'un savoir' },
    { id: 'maison', titre: 'Home Assistant', nom: 'maison', adr: 'http://192.168.1.40:8123/mcp', auth: 'jeton', etat: ['danger', 'en panne'], outils: '0 / 12', avec: '—', garde: 'rien' },
  ];
  const OUTILS = {
    factures: { sert: 'Les factures et les devis de Lumen Conseil', auth: 'en-têtes secrets', outils: [
      ['devis_list', 'Lister les devis ouverts, leur client, leur montant HT.', 'lit', 'servi', 'seule', 'un savoir'],
      ['devis_create', 'Créer un devis neuf dans l\'outil de facturation.', 'agit', 'servi', 'accord', '—'],
      ['facture_delete', 'Supprimer une facture.', 'agit', 'à regarder', 'non', '—']] },
    meteo: { sert: 'La météo et les prévisions d\'une ville, quand on parle d\'une sortie', auth: 'aucune', outils: [
      ['prevision', 'Pluie, vent et températures d\'une ville, jour par jour.', 'lit', 'servi', 'accord', 'un souvenir'],
      ['alertes', 'Les vigilances en cours dans un département.', 'lit', 'servi', 'seule', 'un savoir']] },
    maison: { sert: 'Les lumières et le chauffage de l\'appartement', auth: 'jeton (Authorization: Bearer …)', outils: [
      ['lights_list', 'Lister les lumières et leur état.', 'lit', 'servi', 'seule', 'rien'],
      ['light_set', 'Allumer, éteindre ou régler une lumière.', 'agit', 'servi', 'accord', 'rien'],
      ['climate_set', 'Régler la température d\'une pièce.', 'agit', 'servi', 'accord', 'rien'],
      ['alarm_disarm', 'Désarmer l\'alarme.', 'agit', 'à regarder', 'non', 'rien']] },
  };
  function vueMcp(item) {
    if (item && SERVEURS.some((s) => s.id === item)) return ficheServeur(SERVEURS.find((s) => s.id === item));
    return `<div class="set-page">
      <p class="lede">Les services MCP que tu as branchés. Mika s'en sert pour toi, et pour les personnes avec qui tu les partages ; chaque outil a son réglage : elle seule, ton accord, ou jamais.</p>
      <table class="tbl"><thead><tr><th>Service</th><th>Adresse</th><th>Authentification</th><th>État</th><th>Outils servis</th><th>Partagé avec</th><th></th></tr></thead><tbody>
      ${SERVEURS.map((s) => `<tr><td><div class="row">${ico('server', 'sm')}<div><b>${h(s.titre)}</b><div class="tiny muted mono">${h(s.nom)}</div></div></div></td>
        <td class="small mono">${h(s.adr)}</td><td class="small">${h(s.auth)}</td><td><span class="tag ${s.etat[0]}">${h(s.etat[1])}</span></td>
        <td class="num">${h(s.outils)}${s.revoir ? ` <span class="tag warn">${s.revoir} à regarder</span>` : ''}</td><td class="small">${h(s.avec)}</td>
        <td class="actions">${s.etat[0] === 'danger' ? '<button class="btn xs" type="button" data-relancer>Relancer</button> ' : ''}<a class="btn xs" href="#parametres/mcp/${s.id}">Régler</a></td></tr>`).join('')}
      </tbody></table>
      <p class="small muted tbl-help">Le service « web » (chercher sur le web, lire des pages) est celui de Mika : il n'apparaît pas ici.</p>
    </div>`;
  }
  function ficheServeur(s) {
    return `<form class="set-page" data-form data-page="mcp">
      <a class="back-link" href="#parametres/mcp">${ico('chev-left', 'sm')}Services MCP</a>
      <div class="fiche-head"><span class="acc-ico c0">${ico('server')}</span><div><h2>${h(s.titre)}</h2><p class="muted mono small">${h(s.adr)}</p></div>
        <span class="tag ${s.etat[0]}">${h(s.etat[1])}</span></div>
      ${s.etat[0] === 'danger' ? `<div class="rd-block">${ico('alert', 'sm')}En panne : trop d'échecs d'affilée depuis 12:05. Ses outils ne sont plus servis jusqu'à ce que tu le relances.</div>` : ''}
      ${sousOnglets('mcp', [['service', 'Le service'], ['outils', 'Ses outils'], ['partage', 'Partage']])}
      ${section('Le service', row('Son nom', '', `<input value="${h(s.titre)}">`) + row('À quoi il lui sert', 'Ce qu\'elle lit pour savoir quand s\'en servir.', `<input value="${h(OUTILS[s.id].sert)}">`)
        + row('Adresse', '', `<input class="mono" value="${h(s.adr)}">`) + row('Authentification', 'Les secrets sont scellés : ils ne se relisent plus.', `<select>${['en-têtes secrets', 'jeton (Authorization: Bearer …)', 'un en-tête nommé', 'aucune'].map((a) => `<option${a === OUTILS[s.id].auth ? ' selected' : ''}>${a}</option>`).join('')}</select>`), '', true, 'service')}
      ${section('Ses outils', `<div class="set-row full"><table class="tbl"><thead><tr><th>Outil</th><th>Ce qu'il fait</th><th>Nature</th><th>État</th><th>Pour toi</th><th>Ce qu'elle en garde</th></tr></thead><tbody>
        ${OUTILS[s.id].outils.map(([n, d, nat, st, pol, g]) => `<tr><td class="mono small">${h(n)}</td><td class="small">${h(d)}</td><td><span class="tag ${nat === 'lit' ? 'info' : 'warn'}">${nat === 'lit' ? 'il lit' : 'il agit'}</span></td>
          <td>${st === 'servi' ? '<span class="tag ok">servi</span>' : '<span class="tag warn">à regarder</span>'}</td><td>${seg('pol-' + n, [['seule', 'Seule'], ['accord', 'Ton accord'], ['non', 'Non']], pol)}</td>
          <td><select class="sm-select"><option${g === 'un savoir' ? ' selected' : ''}>un savoir</option><option>un souvenir</option><option>une confidence</option><option${g === '—' ? ' selected' : ''}>rien</option></select></td></tr>`).join('')}
        </tbody></table><p class="small muted tbl-help">Un outil nouveau ou changé attend que tu le regardes avant d'être servi ; changé, il est suspendu.</p></div>`, '', true, 'outils')}
      ${section('Partage', `<div class="set-row full"><p class="small text-2">Ses lignes d'accès, lues de haut en bas. Un service que tu branches n'a que la tienne ; le partager ajoute une ligne pour la personne.</p>
          <table class="tbl"><thead><tr><th>#</th><th>Qui</th><th>Par où</th><th>Quand</th><th>Il lit</th><th>Il agit</th><th>Ce qu'elle en garde</th><th></th></tr></thead><tbody>
          <tr><td class="muted">1</td><td><div class="row">${av('adrien', 'xs')}Toi</div></td><td>tous</td><td>toujours</td><td><span class="lv ok">Seule</span></td><td><span class="lv warn">Accord</span></td><td class="small">${h(OUTILS[s.id].outils[0][5])}</td><td></td></tr>
          ${s.avec !== '—' ? `<tr><td class="muted">2</td><td><div class="row">${av('lea', 'xs')}Léa Moreau <span class="tag accent">partage</span></div></td><td>tous</td><td>quand elle répond</td><td><span class="lv warn">Accord</span></td><td><span class="lv off">—</span></td><td class="small">un souvenir</td><td class="actions"><button class="btn xs ghost danger" type="button" data-retirer>Retirer</button></td></tr>` : ''}
          <tr class="def"><td class="muted">—</td><td><b>Par défaut</b></td><td colspan="5" class="small">fermé : personne d'autre</td><td></td></tr></tbody></table>
          <div class="row tbl-help"><button class="btn xs" type="button" data-partager>${ico('user-plus', 'xs')}Partager avec quelqu'un</button><span class="small muted">La console voit tous les services ; les tiens ne servent qu'à toi et à qui tu les partages.</span></div></div>`, '', true, 'partage')}
    </form>`;
  }
  function brancher() {
    const el = M.modal({ titre: 'Brancher un service MCP', taille: 'wide',
      corps: `<div class="set-grid">${row('Son nom', '', '<input placeholder="Agenda du club">')}${row('À quoi il lui sert', 'Elle le lit pour savoir quand s\'en servir.', '<input placeholder="Les sorties et les inscriptions de l\'association">')}
        ${row('Adresse', 'Un serveur MCP en HTTP.', '<input class="mono" placeholder="https://…/mcp">')}${row('Authentification', '', seg('auth', [['aucune', 'Aucune'], ['jeton', 'Jeton'], ['entete', 'En-tête nommé']], 'jeton') + '<input type="password" placeholder="le jeton">')}
        ${row('', '', `<button class="btn sm primary" type="button" data-tester-new>${ico('refresh', 'sm')}Tester et lire ses outils</button>`)}</div>
        <div class="discovered" data-decouverts hidden></div>
        <div class="info-line small">${ico('info', 'sm')}<span>Il sera à toi : une seule ligne d'accès, la tienne. Pour qu'un autre s'en serve, partage-le (une ligne de plus).</span></div>`,
      pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-close>Brancher</button>' });
    M.on(el, '[data-tester-new]', 'click', () => {
      const d = el.querySelector('[data-decouverts]'); d.hidden = false;
      d.innerHTML = `<h4 class="rd-h4">4 outils proposés</h4><table class="tbl"><tbody>${[['sorties_list', 'lit', 'seule'], ['inscrits_list', 'lit', 'seule'], ['inscription_add', 'agit', 'accord'], ['sortie_cancel', 'agit', 'non']].map(([n, nat, p]) =>
        `<tr><td class="mono small">${n}</td><td><span class="tag ${nat === 'lit' ? 'info' : 'warn'}">${nat === 'lit' ? 'il lit' : 'il agit'}</span></td><td>${seg('n-' + n, [['seule', 'Seule'], ['accord', 'Ton accord'], ['non', 'Non']], p)}</td></tr>`).join('')}</tbody></table>`;
    });
  }

  // ── L'écran ──────────────────────────────────────────────────────────
  const TITRES = { 'compte': 'Compte', 'comptes-mail': 'Comptes mail', 'teams': 'Teams', 'telephones': 'Téléphones', 'partages': 'Partages', 'mcp': 'Services MCP' };
  M.register('parametres', {
    titre: 'Paramètres',
    onglets: Object.entries(TITRES).map(([id, titre]) => ({ id, titre })),
    actions: (ctx) => (ctx.item && ctx.onglet === 'comptes-mail' ? `<button class="btn" type="button" data-tester>${ico('refresh', 'sm')}<span class="lbl">Tester la connexion</span></button>`
      : ctx.item && ctx.onglet === 'mcp' ? `<button class="btn" type="button" data-tester-mcp>${ico('refresh', 'sm')}<span class="lbl">Tester</span></button>` : '') || ({
      'comptes-mail': `<button class="btn primary" type="button" data-ajouter>${ico('plus', 'sm')}<span class="lbl">Ajouter un compte</span></button>`,
      'partages': `<button class="btn primary" type="button" data-partager>${ico('user-plus', 'sm')}<span class="lbl">Partager…</span></button>`,
      'mcp': `<button class="btn primary" type="button" data-brancher>${ico('plus', 'sm')}<span class="lbl">Brancher un service</span></button>`,
      'telephones': `<button class="btn primary" type="button" data-apk>${ico('download', 'sm')}<span class="lbl">Télécharger l'APK</span></button>`,
    }[ctx.onglet] || ''),
    monte(sec) {
      M.on(sec, '[data-seg] button', 'click', (e, b) => {
        const g = b.closest('[data-seg]');
        g.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
        if (g.dataset.seg === 'theme') M.theme(b.dataset.v);
        else { const f = b.closest('[data-form]'); if (f) f.dispatchEvent(new Event('change')); }
      });
      M.on(sec, '[data-sousv]', 'click', (e, b) => {
        const nav = b.closest('[data-souspage]');
        sous[nav.dataset.souspage] = b.dataset.sousv;
        nav.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b));
        montrerSous(b.closest('[data-form]'), nav.dataset.souspage);
      });
      M.on(sec, '[data-ajouter]', 'click', ajouterCompte);
      M.on(sec, '[data-partager]', 'click', partager);
      M.on(sec, '[data-brancher]', 'click', brancher);
      M.on(sec, '[data-mdp]', 'click', () => {
        const el = M.modal({ titre: 'Changer le mot de passe', taille: 'narrow', corps: `<div class="stack"><label class="field"><span>Mot de passe actuel</span><input type="password"></label>
          <label class="field"><span>Nouveau mot de passe</span><input type="password"></label><label class="field"><span>Encore une fois</span><input type="password"></label>
          <p class="small muted">8 caractères au moins, pas seulement des chiffres, sans l'identifiant dedans.</p></div>`,
          pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn primary" type="button" data-ok>Changer</button>' });
        el.querySelector('[data-ok]').addEventListener('click', () => { M.fermerModal(); M.toast('Mot de passe changé : tes autres sessions se ferment.', { ico: 'key' }); });
      });
      M.on(sec, '[data-revoquer]', 'click', (e, b) => {
        const el = M.modal({ titre: 'Révoquer ce téléphone', taille: 'narrow', corps: `<p>Révoquer « ${h(b.dataset.revoquer)} » ? Ses connexions se ferment ; il ne reçoit plus rien, même application fermée.</p>`,
          pied: '<span class="grow"></span><button class="btn" type="button" data-close>Annuler</button><button class="btn danger" type="button" data-ok>Révoquer</button>' });
        el.querySelector('[data-ok]').addEventListener('click', () => { M.fermerModal(); M.toast('Téléphone révoqué.', { ico: 'x' }); });
      });
      M.on(sec, '[data-apk]', 'click', () => M.toast('Maquette : le téléchargement de l\'APK partirait ici.', { ico: 'download' }));
      M.on(sec, '[data-copier]', 'click', () => M.toast('Copié.', { ico: 'copy' }));
      M.on(sec, '[data-regen]', 'click', () => M.toast('Maquette : une clé neuve remplacerait l\'ancienne ; l\'extension devra la recevoir.', { ico: 'key' }));
      M.on(sec, '[data-zip]', 'click', () => M.toast('Maquette : le .zip de l\'extension partirait ici.', { ico: 'download' }));
      M.on(sec, '[data-diag]', 'click', () => M.toast('Diagnostic : sélecteur de la zone de saisie trouvé, dernier envoi accusé à 12:59.', { ico: 'plug' }));
      M.on(sec, '[data-tester], [data-tester-mcp], [data-relancer]', 'click', () => M.toast('Lecture : ok (9 dossiers) ; envoi : ok.', { ico: 'check' }));
      M.on(sec, '[data-retirer]', 'click', () => M.toast('Partage retiré : la personne ne le voit plus.', { ico: 'x' }));
      M.on(sec, '[data-masquer]', 'click', () => M.toast('Elle ne s\'affichera plus dans ton Mail. Léa peut toujours la retirer.', { ico: 'eye-off' }));
      M.on(sec, '[data-boite-menu]', 'click', (e, b) => M.menu(b, [{ label: 'Relever maintenant', ico: 'refresh' }, { label: 'Partager', ico: 'users', action: () => M.go('#parametres/partages') }, { label: 'Suspendre', ico: 'pause' }, 'sep', { label: 'Retirer cette boîte', ico: 'trash', danger: true }]));
    },
    rendu(body, ctx) {
      const v = { 'compte': vueCompte, 'comptes-mail': () => vueComptesMail(ctx.item), 'teams': vueTeams, 'telephones': vueTelephones, 'partages': vuePartages, 'mcp': () => vueMcp(ctx.item) }[ctx.onglet];
      body.innerHTML = `<div class="fill-scroll"><div class="page-pad">${v()}</div></div>`;
      const f = body.querySelector('[data-form]');
      if (f) { M.formulaire(f); if (f.dataset.page) montrerSous(f, f.dataset.page); }
    },
    recherche: () => [
      ...Object.entries(TITRES).map(([id, t]) => ({ groupe: 'Paramètres', titre: t, ico: 'settings', route: '#parametres/' + id })),
      { groupe: 'Paramètres', titre: 'Changer le mot de passe', sous: 'Compte', ico: 'key', route: '#parametres/compte' },
      { groupe: 'Paramètres', titre: 'Télécharger l\'APK', sous: 'Téléphones', ico: 'download', route: '#parametres/telephones' },
      { groupe: 'Paramètres', titre: 'Partager une boîte ou un service', sous: 'Partages', ico: 'users', route: '#parametres/partages' },
      ...BOITES.map((b) => ({ groupe: 'Paramètres', titre: `Boîte « ${b.nom} »`, sous: b.adresse, ico: 'mail', route: '#parametres/comptes-mail/' + b.id })),
    ],
    notes: (ctx) => ({
      'compte': [
        { statut: 'decide', titre: 'Pour tous les utilisateurs de Mika', texte: 'chacun y voit ses boîtes, son Teams, ses téléphones, ses services, et ce qu\'on lui partage ; le mode pro reste aux opérateurs' },
        { statut: 'existe', titre: 'Le compte', texte: 'identifiant, nom affiché, opérateur ou non ; il devient une personne de sa mémoire dès sa création', src: 'adapters/web/accounts.py:127-141 · app/server.py:588-610' },
        { statut: 'manque', titre: 'Changer son mot de passe ou son nom soi-même', texte: 'seuls la console et la CLI le font' },
        { statut: 'manque', titre: 'Voir et fermer ses sessions', texte: 'une session ne garde ni appareil, ni dernière vue ; on ne ferme que la sienne (logout)' },
        { statut: 'manque', titre: 'Des réglages par personne', texte: 'tous les réglages du serveur sont globaux (table settings) ; ceux d\'Android restent sur le téléphone' },
        { statut: 'manque', titre: 'Prévenir dans le navigateur', texte: '/auth/push refuse un navigateur : seul Firebase sert, pour un téléphone' },
      ],
      'comptes-mail': [
        { statut: 'decide', titre: 'Chacun ajoute ses boîtes', texte: 'la boîte ajoutée est à la personne connectée ; l\'opérateur garde la vue de toutes dans la console' },
        { statut: 'existe', titre: 'Boîtes, connexion, voix', texte: 'mot de passe ou compte Microsoft (code d\'appareil) ; dossiers relevés ; elle écrit en son nom, en assistante ou à ta place', src: 'adapters/mail/config.py:52-141 · ADR 0166' },
        { statut: 'existe', titre: 'Tester, relever, comment ça part', texte: 'badges prêt, incomplet, erreur ; tableau d\'envoi du canal Courrier', src: 'plugins/email/console/accounts.py · vocab/canals.py' },
        { statut: 'en_cours', titre: 'À qui est une boîte', texte: 'toi, elle ou une personne qui a un compte', src: 'ADR 0185 (non commitée)' },
        { statut: 'manque', titre: 'Ajouter et régler ses boîtes soi-même', texte: 'seul un opérateur le peut, dans Courrier › Paramètres' },
        { statut: 'partiel', titre: 'DavMail', texte: 'pas de préréglage : une boîte IMAP par mot de passe vers la passerelle ; la sécurité SMTP utile s\'appelle « aucune (tests) »' },
      ],
      'teams': [
        { statut: 'decide', titre: 'Chacun branche son Teams', texte: 'sa clé, son extension, ses règles d\'envoi ; ses réponses se relisent dans Teams' },
        { statut: 'existe', titre: 'L\'extension et sa clé', texte: 'inbox, outbox, accusés ; la clé n\'est montrée qu\'une fois, seule son empreinte est gardée', src: 'ADR 0069 · app/teams.py:184-211' },
        { statut: 'existe', titre: 'Le compte et sa voix', texte: 'nom affiché, ton nom, ton, consignes, signature (décochée par défaut)', src: 'adapters/teams/config.py:19-55' },
        { statut: 'existe', titre: 'Les règles d\'envoi', texte: 'qui, préparer d\'elle-même, comment ça part, lues de haut en bas ; par défaut : préparer non, ton accord', src: 'Réglages › Canaux › teams:<compte> · vocab/canals.py:99' },
        { statut: 'partiel', titre: '« Dernier envoi »', texte: 'le serveur ne garde que le dernier lot poussé ; la relève, la pause et le diagnostic restent dans le navigateur' },
        { statut: 'en_cours', titre: 'Un Teams par personne', texte: 'une clé et une extension par compte, un « Actif » par compte', src: 'ADR 0186 (écrite, non commitée) · adapters/teams/config.py:27-110' },
        { statut: 'manque', titre: 'Régler son Teams soi-même', texte: 'Réglages › Plugins › Teams est une page de console' },
        { statut: 'manque', titre: 'Télécharger l\'extension depuis le web', texte: 'elle se charge aujourd\'hui à la main, depuis le dépôt' },
      ],
      'telephones': [
        { statut: 'decide', titre: 'L\'APK derrière la connexion', texte: 'servi seulement à une session connectée' },
        { statut: 'decide', titre: 'Toutes les apps, au choix', texte: 'la liste des apps lues se règle ici, app par app (ADR à écrire, qui révise 0120)' },
        { statut: 'existe', titre: 'Les jetons du téléphone', texte: 'libellé, sorte, origine, dernier usage, révocation (ferme ses connexions en 4401)', src: 'adapters/web/accounts.py:450-515' },
        { statut: 'manque', titre: 'Voir et révoquer ses téléphones soi-même', texte: 'Accounts.tokens() et revoke_token() ne servent qu\'à la console et à la CLI' },
        { statut: 'manque', titre: 'Servir l\'APK', texte: 'ni route, ni fichier servi : l\'APK se construit à la main (gradle) et s\'installe par adb' },
        { statut: 'partiel', titre: 'À décider : les apps lues', texte: 'l\'app ne lit que quatre paquets en MessagingStyle (WhatsApp, WhatsApp Business, Messages de Google et de Samsung) ; d\'autres apps révisent l\'ADR 0120', src: 'data/phone/PhoneApp.kt:11-16 · ports/phone.py:18' },
        { statut: 'manque', titre: '« Jamais les codes »', texte: 'aucun filtre de contenu : un SMS de code part aujourd\'hui avec Messages' },
        { statut: 'partiel', titre: 'Le libellé d\'un téléphone', texte: 'l\'app le compose : « Android · fabricant modèle » (Build.MANUFACTURER, Build.MODEL)', src: 'core/AppGraph.kt:98' },
      ],
      'partages': [
        { statut: 'decide', titre: 'Une vraie délégation entre personnes', texte: 'lire, lire et préparer, s\'en servir ; par boîte, compte Teams ou service ; la personne le voit dans son propre Mika ; une ADR qui révise 0185 et 0186' },
        { statut: 'manque', titre: 'Partager entre personnes', texte: 'aucune délégation : une boîte n\'a qu\'un propriétaire, et l\'ADR 0185 dit qu\'une boîte de personne ne s\'ouvre à personne d\'autre' },
        { statut: 'partiel', titre: 'Le plus proche aujourd\'hui', texte: 'une ligne d\'accès « personne:<clé> » sur un service ou sur la famille Courrier : Mika s\'en sert devant la personne, sans lui montrer la boîte', src: 'vocab/access.py · plugins/mcp/console.py:621' },
        { statut: 'partiel', titre: 'À décider', texte: 'voir la boîte (une vue dans son frontend) ou seulement demander à Mika de s\'en servir : les deux révisent l\'ADR 0185' },
      ],
      'mcp': [
        { statut: 'decide', titre: 'Chacun branche ses services', texte: 'un service branché n\'a qu\'une ligne d\'accès, celle de la personne ; le partager ajoute une ligne ; la console les voit tous ; ce qui est offert reste calculé par les droits' },
        { statut: 'existe', titre: 'Brancher, tester, revoir, régler l\'accès', texte: 'aucune, jeton Bearer, en-tête nommé, en-têtes secrets scellés ; outils servis, à regarder, suspendus', src: 'plugins/mcp/console.py · adapters/mcp/config.py:43' },
        { statut: 'manque', titre: 'Des MCP à soi', texte: 'McpServer n\'a pas de propriétaire : les services sont ceux de Mika, réglés par un opérateur' },
        { statut: 'manque', titre: 'OAuth', texte: 'reporté depuis l\'ADR 0064' },
        { statut: 'partiel', titre: 'À décider', texte: 'un « MCP à soi » : un champ propriétaire (nouvelle ADR), ou un service de Mika ouvert par une ligne personne:<clé> ?' },
      ],
    }[ctx.onglet] || []),
  });
})();
