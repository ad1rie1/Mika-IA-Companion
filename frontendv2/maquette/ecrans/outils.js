/* Outils : le reflet de la matrice des droits, pour la personne connectée. Une ressource par tableau (une boîte, un
   compte Teams, un service, une app, une famille de ses propres outils) : ses outils en lignes ; en colonnes, chaque
   canal par où tu lui parles, quand elle te répond et quand elle prend la parole, plus ce qu'elle fait seule.
   Le moteur a ces règles (vocab/access.py : qui × par où × quand ; vocab/rights.py : deux portes et plafond) ;
   aucune route ne les rend encore à l'utilisateur : voir les notes. Les outils sont les vrais. */
(function () {
  const { h, ico } = M;
  const D = M.D;

  // Les canaux, dans les mots de la console. Chaque cellule : S seule, A ton accord, N non.
  const CANAUX = [['web', 'Chat web', 'en privé'], ['salon', 'Chat web', 'en salon'], ['mobile', 'App Android', ''], ['teams', 'Teams', ''], ['courrier', 'Courrier', '']];
  const NIV = { S: ['ok', 'Seule'], A: ['warn', 'Accord'], N: ['off', '—'] };
  const LONG = { S: 'elle le fait seule', A: 'avec ton accord', N: 'non' };
  // R(web, salon, mobile, teams, courrier, elle seule) ; chaque canal : « répond » puis « d'elle-même ».
  const R = (web, salon, mobile, teams, courrier, seule) => ({ web, salon, mobile, teams, courrier, seule });
  const O = (n, l, nat, niv, extra) => Object.assign({ n, l, nat, niv }, extra || {});

  const RESSOURCES = [
    { id: 'memoire', groupe: 'Ses propres outils', nom: 'Mémoire', ico: 'book', sous: 'ses souvenirs, ce qu\'elle sait de toi',
      regles: ['Minimum vital : toi — seule · elle seule — seule', 'Ligne 3 : tout le monde · tous · quand elle répond — lit : seule (outils : memory_search)'],
      outils: [O('memory_search', 'Chercher dans sa mémoire', 'lit', R('SS', 'SN', 'SS', 'SN', 'SN', 'S'), { garde: 'un souvenir' }),
        O('memory_promise_done', 'Dire qu\'une promesse est tenue', 'agit', R('SS', 'NN', 'SS', 'SN', 'SN', 'S'))] },
    { id: 'rappels', groupe: 'Ses propres outils', nom: 'Rappels et explorations', ico: 'clock', sous: 'les rappels qu\'elle te promet',
      regles: ['Minimum vital : toi — seule · elle seule — seule'],
      outils: [O('goal_remind', 'Te promettre un rappel', 'agit', R('SS', 'NN', 'SS', 'SN', 'SN', 'S')),
        O('goal_remind_change', 'Déplacer ou retirer un rappel', 'agit', R('SN', 'NN', 'SN', 'SN', 'SN', 'S')),
        O('goal_plan_exploration', 'Ouvrir une exploration', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'S'))] },
    { id: 'dessins', groupe: 'Ses propres outils', nom: 'Dessins', ico: 'image', sous: 'les images qu\'elle dessine pour toi',
      regles: ['Ligne 1 : toi · tous · quand elle répond — agit : seule', 'Par défaut : non'],
      outils: [O('draw', 'Te dessiner une image', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N'), { condition: 'Vérifié à l\'exécution : jamais sous le plancher légal ; le contenu adulte pour toi seul ; jamais dans un salon.' })] },
    { id: 'flux', groupe: 'Ses propres outils', nom: 'Flux RSS', ico: 'inbox', sous: 'les flux qu\'elle suit',
      regles: ['Ligne 3 : tout le monde · tous · quand elle répond — lit : seule (outils : rss_list)', 'Minimum vital : toi — seule'],
      outils: [O('rss_list', 'Les derniers titres de tes flux', 'lit', R('SS', 'SS', 'SS', 'SN', 'SN', 'S')),
        O('rss_read', 'Lire un article de tes flux', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S'))] },
    { id: 'projets', groupe: 'Ses propres outils', nom: 'Projets', ico: 'code', sous: 'Piloter un projet : modification',
      regles: ['Labo de trading · Site de l\'association : Piloter — modification ; Pousser — accord du propriétaire'],
      outils: [O('create_project', 'Accepter un projet que tu lui confies', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')),
        O('start_project', 'Lancer une séance de travail', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S')),
        O('project_push', 'Pousser le dépôt d\'un projet', 'agit', R('AN', 'NN', 'AN', 'NN', 'NN', 'A'))] },
    { id: 'vie', groupe: 'Ses propres outils', nom: 'Sa vie à elle', ico: 'heart', sous: 'ce qu\'elle seule utilise', interne: true,
      regles: ['Elle seule : son journal, ses pensées, sa chambre, qui est qui. Rien ne t\'en revient directement.'],
      outils: [O('self_journal', 'Son journal', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'S')), O('attention_thoughts', 'Ses pensées', 'lit', R('NN', 'NN', 'NN', 'NN', 'NN', 'S')),
        O('world_look', 'Sa chambre (regarder, y aller, y faire)', 'lit', R('NN', 'NN', 'NN', 'NN', 'NN', 'S')), O('identity_whoami_with', 'Qui est qui', 'lit', R('NN', 'NN', 'NN', 'NN', 'NN', 'S'))] },

    // Tes comptes : une boîte, un compte Teams = un tableau à lui, et ses règles d'envoi à lui.
    { id: 'boite-pro', groupe: 'Tes comptes', nom: 'Courrier · Pro', ico: 'mail', sous: 'a.moreau@lumen-conseil.fr · à toi',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : seule · garde : un souvenir', 'Ligne 2 : toi · quand elle prend la parole — lit : seule · agit : ton accord', 'Par défaut : rien',
        'Plafond : en salon, rien de tes boîtes (des témoins)'],
      outils: [O('email_list', 'Lister les mails', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')), O('email_search', 'Chercher dans les mails', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')),
        O('email_read', 'Ouvrir un mail', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')), O('email_contacts', 'Retrouver un correspondant', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')),
        O('email_tidy', 'Ranger la boîte', 'agit', R('SA', 'NN', 'SA', 'NN', 'NN', 'S')), O('email_draft', 'Préparer un mail', 'agit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S'))],
      envoi: [['@lumen-conseil.fr', 'oui', 'ton accord'], ['m.delmas@lumen-conseil.fr', 'non', 'ton accord']], defaut: ['non', 'ton accord'] },
    { id: 'boite-perso', groupe: 'Tes comptes', nom: 'Courrier · Perso', ico: 'mail', sous: 'adrien.moreau@outlook.fr · à toi',
      regles: ['Ligne 1 : toi · web, app Android · quand elle répond — lit : seule · agit : ton accord', 'Par défaut : rien', 'Plafond : en salon, rien de tes boîtes'],
      outils: [O('email_list', 'Lister les mails', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')), O('email_search', 'Chercher dans les mails', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')),
        O('email_read', 'Ouvrir un mail', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')), O('email_contacts', 'Retrouver un correspondant', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')),
        O('email_tidy', 'Ranger la boîte', 'agit', R('AN', 'NN', 'AN', 'NN', 'NN', 'N')), O('email_draft', 'Préparer un mail', 'agit', R('AN', 'NN', 'AN', 'NN', 'NN', 'N'))],
      envoi: [], defaut: ['non', 'ton accord'] },
    { id: 'boite-asso', groupe: 'Tes comptes', nom: 'Courrier · Rando Cassel', ico: 'mail', sous: 'rando.cassel@gmail.com · à toi · partagée avec Julien, en lecture',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : seule', 'Ligne 2 : Julien Roux (partage) · tous · quand elle répond — lit : seule · agit : non', 'Par défaut : rien'],
      outils: [O('email_list', 'Lister les mails', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')), O('email_search', 'Chercher dans les mails', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')),
        O('email_read', 'Ouvrir un mail', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')), O('email_contacts', 'Retrouver un correspondant', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')),
        O('email_tidy', 'Ranger la boîte', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S')), O('email_draft', 'Préparer un mail', 'agit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S'))],
      envoi: [['julien.roux@proton.me', 'oui', 'ton accord']], defaut: ['oui', 'ton accord'] },
    { id: 'boite-lea', groupe: 'Tes comptes', nom: 'Courrier · Boîte de Léa', ico: 'lock', sous: 'lea.moreau@gmail.com · partagée avec toi par Léa, en lecture', partagee: true,
      regles: ['Partage de Léa Moreau : Adrien · lecture (depuis le 28 octobre)', 'La lecture n\'ouvre ni ranger, ni préparer, ni envoyer'],
      outils: [O('email_list', 'Lister les mails', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')), O('email_search', 'Chercher dans les mails', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')),
        O('email_read', 'Ouvrir un mail', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N')), O('email_contacts', 'Retrouver un correspondant', 'lit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N')),
        O('email_tidy', 'Ranger la boîte', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N')), O('email_draft', 'Préparer un mail', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N'))] },
    { id: 'teams-lumen', groupe: 'Tes comptes', nom: 'Teams · Teams pro (Lumen)', ico: 'teams', sous: 'à toi · clé de l\'extension définie',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : seule', 'Ligne 2 : toi · quand elle prend la parole — lit : seule · agit : non', 'Par défaut : rien'],
      outils: [O('teams_conversations', 'Voir tes discussions', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')), O('teams_read', 'Lire une discussion', 'lit', R('SS', 'NN', 'SS', 'NN', 'NN', 'S')),
        O('teams_draft', 'Préparer une réponse à ta place', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S'))],
      envoi: [['Marc', 'oui', 'ton accord'], ['Projet Lumen', 'oui', 'brouillon — c\'est toi qui l\'envoies']], defaut: ['non', 'ton accord'] },
    { id: 'telephone', groupe: 'Tes comptes', nom: 'Messages de tes téléphones', ico: 'phone', sous: 'samsung SM-S931B, Google Pixel 7a',
      regles: ['Condition : en tête-à-tête, avec une personne qui a un compte et qui parle en propriétaire', 'Plafond : jamais dans un salon, jamais à quelqu\'un d\'autre'],
      outils: [O('phone_messages', 'Lire les messages reçus', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N'), { condition: 'En tête-à-tête, avec une personne qui a un compte et qui parle en propriétaire : ce sont les messages de son téléphone à elle.' }),
        O('phone_draft', 'Préparer une réponse sur ton téléphone', 'agit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N'))] },
    { id: 'position', groupe: 'Tes comptes', nom: 'Ta position', ico: 'pin', sous: 'la dernière que ton téléphone lui a donnée',
      regles: ['Réservé à toi et elle seule ; condition : en tête-à-tête', 'Jamais d\'elle-même (ADR 0119)'],
      outils: [O('location_where', 'Regarder où tu es', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N'), { condition: 'Seulement en tête-à-tête, avec quelqu\'un qui a un compte ; jamais dans un salon ; jamais d\'elle-même.' })] },

    { id: 'web', groupe: 'Services', nom: 'Le web', ico: 'globe', sous: 'service du système · avec toi et elle',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : ton accord · garde : un savoir', 'Ligne 2 : Mika · elle seule — lit : seule', 'Par défaut : fermé'],
      outils: [O('web_search', 'Chercher sur le web', 'lit', R('SN', 'NN', 'SN', 'SN', 'SN', 'S'), { garde: 'un savoir' }), O('web_read', 'Lire une page', 'lit', R('SN', 'NN', 'SN', 'SN', 'SN', 'S'), { garde: 'un savoir' })] },
    { id: 'meteo', groupe: 'Services', nom: 'Météo Locale', ico: 'server', sous: 'meteo · à toi · partagé avec Léa',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : ton accord · garde : un souvenir', 'Ligne 2 : Léa Moreau (partage) · tous · quand elle répond — lit : ton accord', 'Par défaut : fermé'],
      outils: [O('prevision', 'Les prévisions d\'une ville', 'lit', R('AN', 'NN', 'AN', 'NN', 'NN', 'N'), { garde: 'un souvenir' }), O('alertes', 'Les alertes du département', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'N'))] },
    { id: 'factures', groupe: 'Services', nom: 'Factures', ico: 'server', sous: 'factures · à toi',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : ton accord · garde : un savoir', 'Par défaut : fermé', 'facture_delete : à regarder, pas encore servi'],
      outils: [O('devis_list', 'Lister les devis', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S'), { garde: 'un savoir' }), O('devis_create', 'Créer un devis', 'agit', R('AN', 'NN', 'AN', 'NN', 'NN', 'N')),
        O('facture_delete', 'Supprimer une facture', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N'), { etat: 'à regarder' })] },
    { id: 'maison', groupe: 'Services', nom: 'Home Assistant', ico: 'server', sous: 'maison · à toi · en panne', panne: true,
      regles: ['En panne depuis 12:05 : ses outils ne sont pas servis tant que tu ne l\'as pas relancé'],
      outils: [O('lights_list', 'Lister les lumières', 'lit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N'), { etat: 'pas servi' }), O('light_set', 'Régler une lumière', 'agit', R('NN', 'NN', 'NN', 'NN', 'NN', 'N'), { etat: 'pas servi' })] },
    { id: 'devis', groupe: 'Apps de la Forge', nom: 'Devis (version 3)', ico: 'code', sous: 'app sans projet · à toi',
      regles: ['Ligne 1 : toi · tous · quand elle répond — lit : seule · agit : ton accord', 'Ligne 2 : Mika · elle seule — lit : seule', 'Par défaut : fermé'],
      outils: [O('devis_suivi', 'Suivre les devis reçus', 'lit', R('SN', 'NN', 'SN', 'NN', 'NN', 'S')), O('devis_relancer', 'Relancer un artisan', 'agit', R('AN', 'NN', 'AN', 'NN', 'NN', 'N'))] },
  ];
  const GROUPES = ['Ses propres outils', 'Tes comptes', 'Services', 'Apps de la Forge'];

  const SERVICES = [
    { id: 'web', titre: 'Le web', ou: 'sur cette machine', sert: 'chercher sur le web (DuckDuckGo) et lire des pages', etat: ['ok', 'connecté'], outils: '2 / 2', avec: 'avec toi et elle', garde: 'un savoir', systeme: true },
    { id: 'meteo', titre: 'Météo Locale', ou: 'https://meteo.example/mcp', sert: 'la météo et les prévisions d\'une ville, quand on parle d\'une sortie', etat: ['ok', 'connecté'], outils: '2 / 2', avec: 'avec toi et Léa Moreau', garde: 'un souvenir' },
    { id: 'factures', titre: 'Factures', ou: 'http://factures.lan/mcp', sert: 'les factures et les devis de Lumen Conseil', etat: ['ok', 'connecté'], outils: '2 / 3', avec: 'avec toi', garde: 'un savoir', revoir: 1 },
    { id: 'maison', titre: 'Home Assistant', ou: 'http://192.168.1.40:8123/mcp', sert: 'les lumières et le chauffage de l\'appartement', etat: ['danger', 'en panne'], outils: '0 / 12', avec: 'avec toi', garde: 'rien', panne: 'trop d\'échecs d\'affilée depuis 12:05 : à relancer' },
    { id: 'devis', titre: 'Devis (version 3)', ou: 'app de la Forge', sert: 'suivre les devis reçus pour les travaux de la salle de réunion', etat: ['ok', 'servie'], outils: '2 / 2', avec: 'avec toi', garde: 'ce qu\'elle sait', forge: true },
  ];
  // Ce qui passe par une carte d'accord dans le chat : les services et les apps. Les réponses Teams et les mails qu'elle
  // prépare se relisent dans Teams et dans Mail.
  const ACCORDS = [
    { quand: 'maintenant', titre: 'Demander la météo de dimanche à Cassel au service « meteo »', ou: 'chat web', sort: 'attend', exp: 'expire dans 4 min' },
    { quand: 'aujourd\'hui 11:40', titre: 'Demander les alertes du Nord au service « meteo »', ou: 'app Android', sort: 'acceptée' },
    { quand: 'aujourd\'hui 09:18', titre: 'Lister les devis ouverts dans « factures »', ou: 'chat web · mode pro', sort: 'acceptée', auto: true },
    { quand: 'hier 21:02', titre: 'Ajouter le concert du 14 à ton agenda', ou: 'app Android', sort: 'refusée' },
    { quand: 'hier 17:40', titre: 'Demander la météo de Lille au service « meteo »', ou: 'app Android', sort: 'expirée' },
    { quand: 'lun. 2 nov.', titre: 'Créer un devis révisé pour Lumen dans « factures »', ou: 'chat web', sort: 'bloquée', raison: 'le serveur a changé cet outil depuis la demande' },
  ];
  const SORTS = { attend: ['warn', 'attend'], 'acceptée': ['ok', 'acceptée'], 'refusée': ['', 'refusée'], 'expirée': ['', 'expirée'], 'bloquée': ['danger', 'bloquée'] };

  const etat = { res: 'tout', q: '' };

  // ── La matrice ───────────────────────────────────────────────────────
  function pourquoi(res, o, canal, quand, v) {
    if (o.etat) return `${o.etat} : il n'est pas servi`;
    if (res.panne) return 'le service est en panne : rien n\'est servi';
    if (canal === 'seule') return v === 'N' ? 'pas pour elle seule : aucune ligne « elle seule » ne l\'ouvre' : `elle seule, quand elle travaille — ${res.partagee ? 'partage' : 'ligne « Mika · elle seule »'}`;
    if (canal === 'salon' && v === 'N') return 'plafond : à plusieurs, des témoins — rien de tes comptes, rien venu d\'ailleurs';
    if ((canal === 'teams' || canal === 'courrier') && v === 'N') return `serré par le canal ${canal === 'teams' ? 'Teams' : 'Courrier'} (ligne 1 : quand tu lui écris par là, elle ne s'en sert pas)`;
    if (quand === 'i' && v === 'N') return o.condition && /elle-même/.test(o.condition) ? 'jamais d\'elle-même (sa condition)' : 'quand elle prend la parole : aucune ligne ne l\'ouvre';
    if (res.partagee && v === 'N') return 'le partage est en lecture : il n\'ouvre pas cela';
    if (v === 'N') return 'par défaut : aucune ligne ne l\'ouvre';
    const ligne = res.regles.find((r) => /^Ligne|^Minimum|^Partage|^Condition|^Réservé/.test(r)) || res.regles[0];
    return `${LONG[v]} — ${ligne}${o.garde ? ` · garde : ${o.garde}` : ''}`;
  }
  const cellule = (res, o, canal, quand, v) => {
    const [cls, lib] = NIV[v];
    return `<td class="mx-c"><button type="button" class="lv ${cls}" data-pq="${h(pourquoi(res, o, canal, quand, v))}" title="${h(LONG[v])}">${lib}</button></td>`;
  };
  function tableau(res) {
    const outils = res.outils.filter((o) => !etat.q || M.norm(o.l + ' ' + o.n + ' ' + res.nom).includes(M.norm(etat.q)));
    if (!outils.length) return '';
    const head1 = CANAUX.map(([k, a, b]) => `<th colspan="2" class="mx-canal">${h(a)}${b ? `<small>${h(b)}</small>` : ''}</th>`).join('') + '<th rowspan="2" class="mx-canal seule">Elle seule<small>au travail</small></th>';
    const head2 = CANAUX.map(() => '<th class="mx-q">répond</th><th class="mx-q">d\'elle-même</th>').join('');
    const lignes = outils.map((o) => `<tr><th class="mx-tool"><button type="button" class="mx-name" data-outil="${res.id}:${o.n}">
        <span class="tool-nat ${o.nat}" title="${o.nat === 'lit' ? 'elle lit' : 'elle agit'}">${ico(o.nat === 'lit' ? 'eye' : 'bolt', 'xs')}</span>
        <span class="mx-label"><b>${h(o.l)}</b><code>${h(o.n)}</code></span>${o.condition ? `<span class="mx-cond" title="${h(o.condition)}">${ico('lock', 'xs')}</span>` : ''}
        ${o.garde ? `<span class="mx-cond" title="Ce qu'elle en garde : ${h(o.garde)}">${ico('book', 'xs')}</span>` : ''}${o.etat ? `<span class="tag warn">${h(o.etat)}</span>` : ''}</button></th>
      ${CANAUX.map(([k]) => cellule(res, o, k, 'r', o.niv[k][0]) + cellule(res, o, k, 'i', o.niv[k][1])).join('')}${cellule(res, o, 'seule', 'r', o.niv.seule)}</tr>`).join('');
    const envoi = res.envoi ? `<div class="mx-envoi"><h4>${ico('send', 'sm')}Comment part ce qu'elle prépare <span class="muted">· canal ${res.id.startsWith('teams') ? 'teams:principal' : 'courrier:' + res.id.replace('boite-', '')}</span></h4>
      <table class="tbl mx-rules"><thead><tr><th>#</th><th>Qui écrit (ou quelle discussion)</th><th>Préparer d'elle-même</th><th>Comment ça part</th></tr></thead><tbody>
      ${res.envoi.map(([q, p, c], i) => `<tr><td class="muted">${i + 1}</td><td>${h(q)}</td><td>${h(p)}</td><td><span class="tag ${c.startsWith('brouillon') ? 'info' : 'warn'}">${h(c)}</span></td></tr>`).join('')}
      <tr class="def"><td class="muted">—</td><td><b>Par défaut</b></td><td>${h(res.defaut[0])}</td><td><span class="tag warn">${h(res.defaut[1])}</span></td></tr></tbody></table>
      <p class="small muted">Ce qu'elle prépare se relit dans ${res.id.startsWith('teams') ? 'Teams' : 'Mail'}, dans « Ses brouillons ».</p></div>` : '';
    return `<section class="mx-res${res.panne ? ' panne' : ''}" id="res-${res.id}">
      <header class="mx-head"><span class="fam-ico${res.interne ? ' interne' : ''}">${ico(res.ico)}</span><div class="grow"><h3>${h(res.nom)}</h3><p>${h(res.sous)}</p></div>
        ${D.moi.operatrice ? `<button class="btn xs ghost" type="button" data-console title="Régler ce tableau dans la console">${ico('external', 'xs')}Régler</button>` : ''}</header>
      <ul class="mx-lines">${res.regles.map((r) => `<li>${h(r)}</li>`).join('')}</ul>
      <div class="mx-scroll"><table class="mx"><thead><tr><th rowspan="2" class="mx-tool-h">Outil</th>${head1}</tr><tr>${head2}</tr></thead><tbody>${lignes}</tbody></table></div>
      ${envoi}</section>`;
  }
  function compte(res) {
    let s = 0, a = 0;
    res.outils.forEach((o) => ['web', 'mobile'].forEach((k) => { const v = o.niv[k][0]; if (v === 'S') s++; else if (v === 'A') a++; }));
    return { s, a };
  }
  function nav() {
    const lien = (r) => { const c = compte(r); return `<button type="button" data-res="${r.id}" class="${etat.res === r.id ? 'on' : ''}" title="${h(r.nom)} — ${h(r.sous)}">${ico(r.ico)}<span class="ellipsis">${h(r.nom.replace(/^Courrier · |^Teams · /, ''))}</span>
      <span class="mx-mini">${c.s ? `<i class="ok">${c.s}</i>` : ''}${c.a ? `<i class="warn">${c.a}</i>` : ''}</span></button>`; };
    return `<div class="pane-scroll mx-nav"><div class="nav-list"><button type="button" data-res="tout" class="${etat.res === 'tout' ? 'on' : ''}">${ico('tools')}<span>Tout</span><span class="cnt">${RESSOURCES.reduce((n, r) => n + r.outils.length, 0)}</span></button></div>
      ${GROUPES.map((g) => `<div class="group-label">${h(g)}</div><div class="nav-list">${RESSOURCES.filter((r) => r.groupe === g).map((r) => lien(r)).join('')}</div>`).join('')}
      <p class="mx-nav-help small muted">Les chiffres : ce qu'elle fait seule, et avec ton accord, quand elle te répond sur le web et l'app Android.</p></div>`;
  }
  function vueDroits() {
    const res = etat.res === 'tout' ? RESSOURCES : RESSOURCES.filter((r) => r.id === etat.res);
    const tables = res.map(tableau).join('');
    return `<div class="split mx-split"><aside class="pane">${nav()}</aside>
      <section class="pane"><div class="pane-scroll mx-main">
        <select class="mx-select" data-res-select>${['<option value="tout">Toutes les ressources</option>', ...RESSOURCES.map((r) => `<option value="${r.id}"${etat.res === r.id ? ' selected' : ''}>${h(r.nom)}</option>`)].join('')}</select>
        <div class="mx-top"><p class="lede">Ce que Mika peut faire pour toi, ressource par ressource : chaque tableau est celui qui décide, pour toi, selon par où tu lui parles et quand. Clique une case pour savoir pourquoi.</p>
          <div class="mx-legend"><span class="lv ok">Seule</span><span class="lv warn">Accord</span><span class="lv off">—</span><span>${ico('lock', 'xs')} sous une condition</span><span>${ico('book', 'xs')} ce qu'elle en garde</span></div></div>
        ${tables || `<div class="empty">${ico('search')}<b>Aucun outil</b><p>Rien ne correspond à « ${h(etat.q)} ».</p></div>`}</div></section></div>`;
  }

  function detailOutil(resId, nom) {
    const res = RESSOURCES.find((r) => r.id === resId), o = res.outils.find((x) => x.n === nom);
    M.modal({ titre: o.l, taille: 'narrow', corps: `<div class="stack"><p class="small muted"><code>${h(o.n)}</code> · ${h(res.nom)} · ${o.nat === 'lit' ? 'elle lit : rien ne change ailleurs' : 'elle agit : ça change quelque chose ailleurs'}</p>
      ${o.condition ? `<p class="det-p">${ico('lock', 'sm')}<span>${h(o.condition)}</span></p>` : ''}${o.garde ? `<p class="det-p">${ico('book', 'sm')}<span>Ce qu'elle en garde : ${h(o.garde)}</span></p>` : ''}
      <p class="small text-2">Décidé par le tableau « ${h(res.nom)} » :</p><ul class="mx-lines">${res.regles.map((r) => `<li>${h(r)}</li>`).join('')}</ul></div>`,
      pied: `<span class="grow"></span><button class="btn mika" type="button" data-close data-demander="${h(o.l)}">${ico('sparkle', 'sm')}Lui demander</button>` });
  }

  function vueServices() {
    return `<div class="fill-scroll"><div class="page-pad">
      <p class="lede">Les services d'où viennent ses outils « venus d'ailleurs » : des serveurs MCP et les apps de la Forge. Elle s'en sert pour toi selon leurs lignes d'accès. Chacun branche les siens dans Paramètres › Services MCP.</p>
      <div class="mx-scroll"><table class="tbl svc-tbl"><thead><tr><th>Service</th><th>Où</th><th>À quoi il lui sert</th><th>État</th><th>Outils servis</th><th>Avec qui</th><th>Ce qu'elle en garde</th><th></th></tr></thead><tbody>
      ${SERVICES.map((s) => `<tr><td><div class="row nowrap">${ico(s.forge ? 'code' : 'server', 'sm')}<b>${h(s.titre)}</b>${s.systeme ? '<span class="tag">système</span>' : ''}</div></td>
        <td class="small mono">${h(s.ou)}</td><td class="small text-2">${h(s.sert)}</td>
        <td><span class="tag ${s.etat[0]}">${h(s.etat[1])}</span>${s.panne ? `<div class="tiny muted">${h(s.panne)}</div>` : ''}</td>
        <td class="num nowrap">${h(s.outils)}${s.revoir ? ` <span class="tag warn">${s.revoir} à regarder</span>` : ''}</td><td class="small">${h(s.avec)}</td><td class="small">${h(s.garde)}</td>
        <td class="actions nowrap"><button class="btn xs ghost" type="button" data-res-voir="${s.id}">Ses droits</button>${s.systeme || s.forge ? '' : ` <a class="btn xs" href="#parametres/mcp/${s.id}">Régler</a>`}</td></tr>`).join('')}
      </tbody></table></div></div></div>`;
  }

  function vueAccords() {
    const enCours = ACCORDS.filter((a) => a.sort === 'attend');
    return `<div class="fill-scroll"><div class="page-pad accords">
      <p class="lede">Les cartes d'accord des services et des apps : seuls leurs boutons décident. Les réponses Teams et les mails qu'elle prépare se relisent dans Teams et dans Mail.</p>
      <h2 class="section-title">À décider <span class="cnt">${enCours.length}</span></h2>
      <div class="acc-list">${enCours.map((a) => `<div class="acc">${ico('shield')}<div class="grow"><b>${h(a.titre)}</b><span class="small muted">${h(a.ou)} · <span class="warn-txt">${h(a.exp)}</span></span></div>
        <button class="btn sm" type="button" data-acc="non">Refuser</button><button class="btn sm primary" type="button" data-acc="ok">${ico('check', 'sm')}Accepter</button></div>`).join('')}</div>
      <h2 class="section-title">Ce que tu as décidé <span class="cnt">7 jours</span></h2>
      <table class="tbl"><thead><tr><th>Quand</th><th>Ce qu'elle voulait faire</th><th>D'où</th><th>Sort</th></tr></thead><tbody>
      ${ACCORDS.filter((a) => a.sort !== 'attend').map((a) => `<tr><td class="nowrap small">${h(a.quand)}</td><td>${h(a.titre)}${a.raison ? `<div class="tiny muted">${h(a.raison)}</div>` : ''}</td>
        <td class="small">${h(a.ou)}</td><td><span class="tag ${SORTS[a.sort][0]}">${h(SORTS[a.sort][1])}</span>${a.auto ? ' <span class="tag warn" title="« Tout accepter » était allumé">⚡ tout accepter</span>' : ''}</td></tr>`).join('')}
      </tbody></table></div></div>`;
  }

  M.register('outils', {
    titre: 'Outils',
    onglets: [{ id: 'droits', titre: 'Tes droits' }, { id: 'services', titre: 'Services', cnt: SERVICES.length }, { id: 'accords', titre: 'Accords', cnt: 1 }],
    actions: (ctx) => ctx.onglet === 'droits'
      ? `<label class="search mx-search">${ico('search', 'sm')}<input type="search" data-q placeholder="Chercher un outil…" value="${h(etat.q)}"></label>`
      : ctx.onglet === 'services' ? `<a class="btn primary" href="#parametres/mcp">${ico('plus', 'sm')}<span class="lbl">Brancher un service</span></a>` : '',
    monte(sec) {
      M.on(sec, '[data-res]', 'click', (e, b) => { etat.res = b.dataset.res; M.rafraichir(); });
      M.on(sec, '[data-res-voir]', 'click', (e, b) => { etat.res = b.dataset.resVoir; M.go('#outils/droits'); });
      M.on(sec, '[data-res-select]', 'change', (e, b) => { etat.res = b.value; M.rafraichir(); });
      M.on(sec, '[data-pq]', 'click', (e, b) => {
        const th = b.closest('tr').querySelector('.mx-label b').textContent;
        M.menu(b, [{ html: `<div class="pq"><b>${h(th)}</b><span>${h(b.dataset.pq)}</span></div>` }]);
      });
      M.on(sec, '[data-outil]', 'click', (e, b) => { const [r, n] = b.dataset.outil.split(':'); detailOutil(r, n); });
      M.on(sec, '[data-console]', 'click', () => M.toast('Les tableaux se règlent dans la console : Réglages › Droits (opérateur).', { ico: 'external' }));
      M.on(sec, '[data-acc]', 'click', (e, b) => { b.closest('.acc').classList.add('gone'); M.toast(b.dataset.acc === 'ok' ? 'Accepté : c\'est parti.' : 'Refusé : rien ne partira.', { ico: b.dataset.acc === 'ok' ? 'check' : 'x' }); });
      sec.addEventListener('input', (e) => {
        if (!e.target.matches('[data-q]')) return;
        etat.q = e.target.value;
        const main = sec.querySelector('.mx-main');
        if (!main) return;
        const res = etat.res === 'tout' ? RESSOURCES : RESSOURCES.filter((r) => r.id === etat.res);
        main.querySelectorAll('.mx-res, .empty').forEach((x) => x.remove());
        main.insertAdjacentHTML('beforeend', res.map(tableau).join('') || `<div class="empty">${ico('search')}<b>Aucun outil</b><p>Rien ne correspond à « ${h(etat.q)} ».</p></div>`);
      });
      document.addEventListener('click', (e) => {
        const b = e.target.closest('[data-demander]');
        if (!b) return;
        M.go('#chat');
        setTimeout(() => { const t = document.querySelector('[data-chat-input]'); if (t) { t.value = `tu peux t'en servir pour moi : ${b.dataset.demander.toLowerCase()} ?`; t.focus(); } }, 80);
      });
    },
    rendu(body, ctx) {
      body.innerHTML = ctx.onglet === 'services' ? vueServices() : ctx.onglet === 'accords' ? vueAccords() : vueDroits();
    },
    recherche: () => RESSOURCES.flatMap((r) => r.outils.map((o) => ({ groupe: 'Outils', titre: o.l, sous: `${r.nom} · ${o.n}`, ico: 'tools', action: () => { etat.res = r.id; M.go('#outils/droits'); } }))),
    notes: () => [
      { groupe: 'Décidé', statut: 'decide', titre: 'Le reflet de la matrice des droits', texte: 'une ressource par tableau (chaque boîte, chaque compte Teams, chaque service), ses outils × par où × quand, et les lignes qui décident' },
      { groupe: 'Ce qui marche déjà', statut: 'existe', titre: 'Un seul moteur de règles', texte: 'qui × par où × quand, lu de haut en bas, une ligne par défaut obligatoire', src: 'vocab/access.py:364 decide' },
      { statut: 'existe', titre: 'Deux portes et un plafond, avec le pourquoi', texte: 'le tableau du canal puis celui de la ressource ; la plus stricte gagne', src: 'vocab/rights.py:114 tool_allowance' },
      { statut: 'existe', titre: 'Un tableau d\'envoi par boîte et par compte Teams', texte: 'qui, préparer d\'elle-même, comment ça part (courrier:<boîte>, teams:<compte>)', src: 'vocab/canals.py · inspector/pages/canals.py' },
      { statut: 'existe', titre: 'Ce qu\'elle a vraiment sous la main', texte: 'la porte d\'offre, devant une audience réelle', src: 'runtime/tools.py:325 offer' },
      { statut: 'en_cours', titre: 'Les boîtes et les comptes Teams à quelqu\'un', texte: 'ses outils ne voient que les boîtes et les comptes de qui est en face', src: 'ADR 0185, 0186 (non commitées) · runtime/tools.py owns' },
      { groupe: 'À faire', statut: 'manque', titre: 'Une route « mes droits »', texte: 'aucune route ni trame ne rend ces tableaux à l\'utilisateur', src: 'adapters/web/app.py:773-792' },
      { statut: 'partiel', titre: 'Le calcul, hors de la console', texte: 'exact(ui, who, canal) travaille sur une audience de synthèse et exige l\'objet console ; il faut une méthode du port du chat : audience réelle, offer() pour REPLY et INITIATIVE, tool_allowance pour le niveau et le pourquoi', src: 'app/handmade/rights.py:111 · app/lending.py:106' },
      { statut: 'manque', titre: 'Le tableau d\'une boîte à elle seule', texte: 'aujourd\'hui la famille Courrier a un seul tableau pour toutes tes boîtes ; une matrice par boîte est une évolution' },
      { statut: 'manque', titre: 'Les partages dans la matrice', texte: 'la délégation (boîte de Léa, Julien sur Rando Cassel) demande l\'ADR qui révise 0185 et 0186' },
      { statut: 'manque', titre: 'L\'historique de tes accords', texte: 'les décisions sont au journal, rien ne les relit pour toi' },
      { statut: 'partiel', titre: 'À décider : montrer le « pourquoi » à un utilisateur', texte: 'il révèle les réglages de l\'opérateur' },
    ],
  });
})();
