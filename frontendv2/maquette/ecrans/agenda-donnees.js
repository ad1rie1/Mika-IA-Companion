/* Proposé le 2026-11-23, pas encore validé : les données d'exemple de l'agenda (output/agenda/CONCEPTION.md).
   Tout est fictif. L'écran Agenda se passe le lundi 23 novembre 2026 à 14:20 (le reste de la maquette, le 4 novembre).
   Les personnes sont celles de donnees.js, nommées par leur clé. Lu par ecrans/agenda.js et par les fichiers posés
   par-dessus Paramètres, Outils et le chat (agenda-parametres.js, agenda-droits.js, agenda-chat.js). */
window.MIKA_AGENDA = {
  aujourdhui: '2026-11-23', heure: '14:20', fuseau: 'Europe/Paris', fuseauCourt: 'UTC+1',

  /* Les couleurs qu'on choisit pour un agenda. Le rose n'est pas dans la palette : il est à Mika. */
  palette: [['indigo', 'Indigo'], ['bleu', 'Bleu'], ['sarcelle', 'Sarcelle'], ['vert', 'Vert'], ['ambre', 'Ambre'], ['orange', 'Orange'],
    ['violet', 'Violet'], ['ardoise', 'Ardoise']],

  /* Les sortes de compte (output/agenda/CONCEPTION.md, « Les fournisseurs »). */
  sortes: {
    systeme: { nom: 'Système', long: 'Agenda du système', ico: 'server', aide: 'Sur ce serveur : rien ne sort d\'ici. Chaque personne qui a un compte a déjà « Mon agenda ».' },
    google: { nom: 'Google', long: 'Google Agenda', ico: 'globe', aide: 'Se connecter à Google, puis coller l\'adresse de retour.' },
    microsoft: { nom: 'Outlook', long: 'Outlook.com / Microsoft 365', ico: 'key', aide: 'Un code à entrer chez Microsoft, comme pour une boîte Outlook.' },
    caldav: { nom: 'CalDAV', long: 'CalDAV', ico: 'server', aide: 'Une adresse, un identifiant, un mot de passe d\'application. Outlook pro par DavMail, iCloud, Nextcloud, Fastmail.' },
    ical: { nom: 'iCal', long: 'Abonnement iCal', ico: 'link', aide: 'Une adresse .ics, en lecture seule : jours fériés, adresse secrète d\'un agenda.' },
  },

  /* Les comptes d'agenda : une connexion à un fournisseur, à quelqu'un (vide = à toi, comme une boîte). */
  comptes: [
    { id: 'systeme', sorte: 'systeme', nom: 'Ce serveur', adresse: 'adrien · sur Mika', a: 'toi', etat: ['ok', 'à jour'],
      synchro: 'toujours à jour : il est sur ce serveur', depuis: 'créé avec ton compte, le 12 septembre' },
    { id: 'lumen', sorte: 'caldav', nom: 'Lumen (Outlook pro)', adresse: 'a.moreau@lumen-conseil.fr', a: 'toi', etat: ['ok', 'synchronisé'],
      synchro: 'synchronisé il y a 3 min', serveur: 'http://127.0.0.1:1080/users/a.moreau@lumen-conseil.fr/calendar/', service: 'davmail',
      depuis: 'branché le 2 octobre' },
    { id: 'google', sorte: 'google', nom: 'Google', adresse: 'adrien.moreau@gmail.com', a: 'toi', etat: ['ok', 'synchronisé'],
      synchro: 'synchronisé il y a 1 min', depuis: 'connecté le 12 octobre' },
    { id: 'outlook', sorte: 'microsoft', nom: 'Outlook.com', adresse: 'adrien.moreau@outlook.fr', a: 'toi', etat: ['warn', 'à reconnecter'],
      synchro: 'dernière synchro réussie samedi 21 novembre à 08:14',
      erreur: 'Microsoft demande que tu te reconnectes : l\'accès donné le 31 octobre a expiré. Rien n\'est perdu, la synchro reprend dès que c\'est fait.',
      depuis: 'connecté le 31 octobre' },
    { id: 'feries', sorte: 'ical', nom: 'Jours fériés', adresse: 'https://etalab.github.io/jours-feries-france-data/ics/jours_feries_metropole.ics', a: 'toi',
      etat: ['ok', 'relu'], synchro: 'relu ce matin à 06:00', frequence: 'chaque jour', depuis: 'abonné le 12 septembre' },
  ],

  /* Les agendas. groupe : mes · partages (avec toi) · abonnements · mika. ecrire : on peut y écrire.
     rappel : « Mika te le rappelle » par défaut pour cet agenda (non · 15 · 30 · 60 · veille). */
  agendas: [
    { id: 'mon', compte: 'systeme', nom: 'Mon agenda', couleur: 'indigo', groupe: 'mes', ecrire: true, visible: true, coche: true, rappel: '30',
      rappelFourn: 'aucun : l\'agenda du système n\'envoie rien lui-même', partages: [], defaut: true },
    { id: 'travail', compte: 'lumen', nom: 'Travail', couleur: 'bleu', groupe: 'mes', ecrire: true, visible: true, coche: true, rappel: '15',
      rappelFourn: 'notification 10 min avant, par Outlook', partages: [] },
    { id: 'perso', compte: 'google', nom: 'Perso', couleur: 'vert', groupe: 'mes', ecrire: true, visible: true, coche: true, rappel: '30',
      rappelFourn: 'notification 30 min avant, par Google',
      partages: [['lea', 'preparer', '12 novembre'], ['julien', 'lire', '3 novembre']] },
    { id: 'famille', compte: 'google', nom: 'Famille', couleur: 'orange', groupe: 'mes', ecrire: true, visible: true, coche: true, rappel: 'veille',
      rappelFourn: 'notification la veille à 18:00, par Google', partages: [], chezGoogle: ['Maman', 'Léa Moreau'] },
    { id: 'outlook-cal', compte: 'outlook', nom: 'Calendrier', couleur: 'violet', groupe: 'mes', ecrire: true, visible: false, coche: false, rappel: 'non',
      rappelFourn: 'notification 15 min avant, par Outlook', partages: [] },
    { id: 'feries', compte: 'feries', nom: 'Jours fériés en France', couleur: 'ardoise', groupe: 'abonnements', ecrire: false, visible: true, coche: true,
      rappel: 'non', rappelFourn: 'aucun', partages: [] },
    { id: 'lea', nom: 'Agenda de Léa', de: 'lea', niveau: 'lire', depuisPartage: '12 novembre', couleur: 'sarcelle', groupe: 'partages', ecrire: false,
      visible: true, coche: true, rappel: 'non', rappelFourn: 'ceux de Léa ne te parviennent pas', partages: [] },
    { id: 'mika', nom: 'L\'agenda de Mika', couleur: 'rose', groupe: 'mika', ecrire: false, visible: true, coche: true, rappel: 'non',
      rappelFourn: 'aucun', partages: [] },
  ],

  /* Les événements. j : jour (AAAA-MM-JJ), de / a : heures ; journee : journée entière (jusqu : dernier jour) ;
     rec : { freq: semaine | an } (le jour de la semaine ou la date de j) ; p : participants [clé ou {nom, adr}, réponse] ;
     reponse : org · oui · peut · non · attente. sait : [ce que Mika en sait, d'où, route]. */
  evenements: [
    // ── Travail (Outlook pro, par DavMail) ──────────────────────────────
    { id: 'point-lumen', agenda: 'travail', titre: 'Point hebdo · Projet Lumen', j: '2026-09-07', de: '09:00', a: '09:30', rec: { freq: 'semaine', jusqu: '2027-06-28' },
      visio: 'Teams', visioUrl: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_Lumen…', org: 'claire',
      p: [['claire', 'org'], ['sophie', 'oui'], ['karim', 'peut'], ['adrien', 'oui']], rappel: '15',
      desc: 'L\'avancement de la semaine, un tour de table, les points qui bloquent.',
      sait: [['Claire attend un chiffre de budget dès la slide 2 de jeudi.', 'lu au courrier · « Re: Présentation de jeudi »']] },
    { id: 'atelier-verdier', agenda: 'travail', titre: 'Atelier client · Verdier', j: '2026-11-23', de: '10:30', a: '12:00', lieu: 'Lumen Conseil, salle 3 · 12 rue Esquermoise, Lille',
      org: 'claire', p: [['claire', 'org'], ['marc', 'oui'], ['adrien', 'oui']], desc: 'Revoir avec le client la trame de jeudi et ses chiffres.' },
    { id: 'revue-budget', agenda: 'travail', titre: 'Revue du budget avec Marc', j: '2026-11-23', de: '14:00', a: '15:00', lieu: 'Bureau de Marc, 3e étage',
      org: 'marc', p: [['marc', 'org'], ['adrien', 'oui']], rappel: '30', desc: 'Le budget de la salle de réunion, avant de répondre à Lefèvre Rénovation.',
      sait: [['Elle te l\'a rappelé à 13:30, et t\'a souhaité bon courage.', 'dans le chat · aujourd\'hui 13:30', '#chat/agenda'],
        ['Le devis de Lefèvre dépasse le budget de 1 240 € (+8 %), surtout la main-d\'œuvre.', 'en mode pro · fil « Devis Lefèvre »']] },
    { id: 'point-sophie', agenda: 'travail', titre: 'Point chiffres avec Sophie', j: '2026-11-24', de: '11:00', a: '11:30', visio: 'Teams',
      visioUrl: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_Sophie…', org: 'adrien', p: [['adrien', 'org'], ['sophie', 'oui']] },
    { id: 'inv-entretien', agenda: 'travail', titre: 'Entretien annuel', j: '2026-11-25', de: '14:00', a: '15:00', lieu: 'Salle RH, 2e étage',
      org: 'nadia', p: [['nadia', 'org'], ['adrien', 'attente']], desc: 'Ton entretien annuel : le bilan de l\'année, tes envies pour la prochaine. Prévois une heure.',
      invitation: { de: 'nadia', recue: 'aujourd\'hui à 09:12', par: 'Outlook (par DavMail)',
        prepare: { reponse: 'oui', mot: 'C\'est noté, à mercredi. Merci Nadia !', pourquoi: 'Tu es libre à cette heure-là, et tu lui as dit jeudi vouloir le passer avant la fin du mois.' } } },
    { id: 'repetition', agenda: 'travail', titre: 'Répétition de la présentation', j: '2026-11-25', de: '16:00', a: '17:00', lieu: 'Lumen Conseil, salle 3',
      org: 'claire', p: [['claire', 'org'], ['sophie', 'oui'], ['adrien', 'oui']] },
    { id: 'presentation', agenda: 'travail', titre: 'Présentation au client Verdier', j: '2026-11-26', de: '10:00', a: '11:30',
      lieu: 'Verdier SA · 40 avenue de la Marne, Marcq-en-Barœul', org: 'claire', rappel: 'veille',
      p: [['claire', 'org'], ['marc', 'oui'], ['adrien', 'oui'], [{ nom: 'Jacques Verdier', adr: 'j.verdier@verdier-sa.fr' }, 'oui']],
      desc: 'La présentation finale au client. Les slides sont dans le dossier partagé « Verdier ».',
      sait: [['Elle t\'a promis de relire tes slides d\'ici mercredi soir.', 'promesse · dans le chat, mardi 17', '#agenda/evenement/mika-relire'],
        ['Claire veut le budget dès la slide 2 : le client regarde ça en premier.', 'lu au courrier · « Re: Présentation de jeudi »']] },
    { id: 'inv-afterwork', agenda: 'travail', titre: 'Afterwork de l\'équipe', j: '2026-11-26', de: '18:30', a: '21:00', lieu: 'La Capsule · 25 rue des Bouchers, Lille',
      org: 'karim', p: [['karim', 'org'], ['claire', 'oui'], ['sophie', 'oui'], ['marc', 'peut'], ['adrien', 'attente']],
      desc: 'Pour fêter la fin du projet Verdier. Premier verre offert !',
      invitation: { de: 'karim', recue: 'hier à 18:40', par: 'Outlook (par DavMail)', conflit: 'escalade',
        prepare: { reponse: 'non', mot: 'Désolé, j\'ai escalade le jeudi soir. Bonne soirée à tous !', pourquoi: 'Ton escalade du jeudi tombe à la même heure (19:00 – 21:00).' } } },
    { id: 'demo-data', agenda: 'travail', titre: 'Démo interne de l\'outil data', j: '2026-11-27', de: '15:00', a: '16:00', visio: 'Teams',
      visioUrl: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_Demo…', org: 'sophie', p: [['sophie', 'org'], ['karim', 'oui'], ['adrien', 'oui']] },
    { id: 'copil', agenda: 'travail', titre: 'Comité de pilotage Lumen', j: '2026-12-01', de: '10:00', a: '12:00', lieu: 'Lumen Conseil, salle du conseil', org: 'marc',
      p: [['marc', 'org'], ['claire', 'oui'], ['adrien', 'oui']] },
    { id: 'atelier-data', agenda: 'travail', titre: 'Atelier données avec Sophie', j: '2026-12-03', de: '09:30', a: '12:30', lieu: 'Lumen Conseil, salle 2', org: 'sophie',
      p: [['sophie', 'org'], ['adrien', 'oui']] },
    { id: 'revue-trim', agenda: 'travail', titre: 'Revue trimestrielle', j: '2026-12-08', de: '14:00', a: '16:00', lieu: 'Lumen Conseil, salle du conseil', org: 'marc' },
    { id: 'point-equipe', agenda: 'travail', titre: 'Point d\'équipe', j: '2026-11-04', de: '16:00', a: '17:00', lieu: 'Lumen Conseil, salle 3', org: 'marc' },
    { id: 'presentation-lumen', agenda: 'travail', titre: 'Présentation Lumen au client', j: '2026-11-05', de: '10:00', a: '11:30', org: 'claire' },
    { id: 'atelier-paris', agenda: 'travail', titre: 'Atelier à Paris', j: '2026-11-12', de: '09:30', a: '16:30', lieu: 'Lumen Conseil Paris · 8 rue de Londres' },
    { id: 'formation', agenda: 'travail', titre: 'Formation sécurité', j: '2026-11-18', de: '14:00', a: '17:00', lieu: 'Lumen Conseil, salle 2' },
    { id: 'chiffres-20', agenda: 'travail', titre: 'Point chiffres avec Sophie', j: '2026-11-20', de: '11:00', a: '11:30', visio: 'Teams' },

    // ── Mon agenda (le système) ─────────────────────────────────────────
    { id: 'dentiste', agenda: 'mon', titre: 'Dentiste · Dr Lambert', j: '2026-11-24', de: '17:30', a: '18:00', lieu: 'Cabinet du Dr Lambert · 12 rue de Béthune, Lille',
      rappel: '60', parMika: { quand: 'jeudi 19 novembre à 18:12', comment: 'seule', conv: '#chat',
        phrase: 'Tu lui as dit jeudi, dans le chat, que tu avais pris rendez-vous : elle l\'a ajouté seule, ton tableau le lui permet sur « Mon agenda ».' } },
    { id: 'teletravail', agenda: 'mon', titre: 'Télétravail', j: '2026-11-27', journee: true, dispo: 'libre' },
    { id: 'coiffeur', agenda: 'mon', titre: 'Coiffeur', j: '2026-11-10', de: '18:00', a: '18:30' },
    { id: 'medecin', agenda: 'mon', titre: 'Médecin du travail', j: '2026-11-19', de: '08:30', a: '09:00' },

    // ── Perso (Google) ──────────────────────────────────────────────────
    { id: 'dej-julien', agenda: 'perso', titre: 'Déjeuner avec Julien', j: '2026-11-23', de: '12:30', a: '13:30', lieu: 'Le Bistrot du Vieux-Lille · rue de la Monnaie' },
    { id: 'escalade', agenda: 'perso', titre: 'Escalade', j: '2026-09-03', de: '19:00', a: '21:00', rec: { freq: 'semaine' }, lieu: 'Climb Up · Lille', rappel: 'non' },
    { id: 'rando', agenda: 'perso', titre: 'Rando · boucle des Monts', j: '2026-11-29', de: '08:30', a: '13:00', lieu: 'Place du Concert, Lille (covoiturage)',
      org: 'adrien', p: [['adrien', 'org'], ['julien', 'oui'], [{ nom: 'Camille Petit', adr: 'camille.petit@laposte.net' }, 'oui']],
      desc: 'Julien prend trois personnes en voiture. Prévoir les chaussures de marche et un coupe-vent.' },
    { id: 'monts-flandre', agenda: 'perso', titre: 'Sortie Monts de Flandre', j: '2026-11-08', de: '08:30', a: '13:00' },
    { id: 'train-paris', agenda: 'perso', titre: 'Train Lille Flandres → Paris Nord', j: '2026-11-12', de: '07:16', a: '08:18' },
    { id: 'diner-camille', agenda: 'perso', titre: 'Dîner avec Camille', j: '2026-11-17', de: '20:00', a: '22:30' },
    { id: 'ikea', agenda: 'perso', titre: 'Choisir le canapé', j: '2026-11-21', de: '15:00', a: '17:00', lieu: 'Ikea Lomme' },
    { id: 'marche-noel', agenda: 'perso', titre: 'Marché de Noël d\'Arras', j: '2026-12-12', journee: true },

    // ── Famille (Google, partagé chez Google avec Maman et Léa) ─────────
    { id: 'anniv-lea', agenda: 'famille', titre: 'Anniversaire de Léa', j: '2026-11-28', journee: true, rec: { freq: 'an' }, dispo: 'libre' },
    { id: 'dej-maman', agenda: 'famille', titre: 'Déjeuner chez Maman', j: '2026-11-29', de: '12:30', a: '15:00', lieu: 'Chez Maman · Armentières',
      sait: [['La rando finit vers 13 h, et ta mère t\'attend à 12 h 30 : elle te l\'a fait remarquer jeudi.', 'dans le chat · jeudi 19']] },
    { id: 'dej-maman-15', agenda: 'famille', titre: 'Déjeuner chez Maman', j: '2026-11-15', de: '12:30', a: '15:00', lieu: 'Chez Maman · Armentières' },
    { id: 'anniv-papa', agenda: 'famille', titre: 'Anniversaire de Papa', j: '2026-12-06', journee: true, rec: { freq: 'an' }, dispo: 'libre' },

    // ── Jours fériés en France (abonnement) ─────────────────────────────
    { id: 'toussaint', agenda: 'feries', titre: 'Toussaint', j: '2026-11-01', journee: true, dispo: 'libre' },
    { id: 'armistice', agenda: 'feries', titre: 'Armistice 1918', j: '2026-11-11', journee: true, dispo: 'libre' },
    { id: 'noel', agenda: 'feries', titre: 'Noël', j: '2026-12-25', journee: true, dispo: 'libre' },
    { id: 'jour-an', agenda: 'feries', titre: 'Jour de l\'an', j: '2027-01-01', journee: true, dispo: 'libre' },

    // ── Agenda de Léa (partagé avec toi par Léa, en lecture) ────────────
    { id: 'lea-yoga', agenda: 'lea', titre: 'Yoga', j: '2026-09-01', de: '19:00', a: '20:00', rec: { freq: 'semaine' } },
    { id: 'lea-diner', agenda: 'lea', titre: 'Dîner d\'anniversaire à la maison', j: '2026-11-28', de: '20:00', a: '23:30', lieu: 'Chez Léa · rue de Gand, Lille' },
    { id: 'lea-lyon', agenda: 'lea', titre: 'Week-end à Lyon', j: '2026-12-05', jusqu: '2026-12-06', journee: true },

    // ── L'agenda de Mika : sa mémoire, montrée comme un agenda (rien n'est recopié) ──
    { id: 'mika-relire', agenda: 'mika', titre: 'Relire tes slides pour Verdier', j: '2026-11-24', jusqu: '2026-11-25', journee: true,
      mika: { sorte: 'promesse', source: 'Elle te l\'a promis mardi dans le chat.', quand: 'mardi 17 novembre', conv: '#chat',
        dit: '« je te relis ça d\'ici mercredi soir, promis »' } },
    { id: 'mika-ct', agenda: 'mika', titre: 'Te rappeler de prendre rendez-vous pour le contrôle technique', j: '2026-11-27', de: '09:00', a: '09:15',
      mika: { sorte: 'promesse', source: 'Elle te l\'a promis jeudi dans le chat.', quand: 'jeudi 19 novembre', conv: '#chat',
        dit: '« je te le rappelle vendredi à 9 h »' } },
    { id: 'mika-canape', agenda: 'mika', titre: 'La livraison de ton canapé', j: '2026-11-28', de: '08:00', a: '12:00',
      mika: { sorte: 'moment', source: 'Tu le lui as raconté dimanche dans le chat.', quand: 'dimanche 22 novembre', conv: '#chat',
        dit: '« le livreur passe samedi entre 8 h et midi »', suite: 'Elle t\'en demandera des nouvelles samedi après-midi.' } },
    { id: 'mika-bilan', agenda: 'mika', titre: 'Les résultats de ton bilan sanguin', j: '2026-12-02', journee: true,
      mika: { sorte: 'moment', source: 'Tu le lui as dit jeudi, après le médecin du travail.', quand: 'jeudi 19 novembre', conv: '#chat',
        dit: '« j\'aurai les résultats mercredi en huit »', suite: 'Elle t\'en demandera des nouvelles ce jour-là.' } },

    // ── Ce que Mika propose d'ajouter (en attente de ton accord) ────────
    { id: 'prop-diner', agenda: 'perso', titre: 'Dîner chez Léa', j: '2026-11-28', de: '20:00', a: '23:00', lieu: 'Chez Léa · rue de Gand, Lille', rappel: 'veille',
      proposition: { quand: 'aujourd\'hui à 12:50', conv: '#chat/agenda',
        phrase: 'Tu lui as dit à 12:50, dans le chat, que Léa t\'invitait samedi soir pour son anniversaire.' },
      sait: [['C\'est l\'anniversaire de Léa : il est dans « Famille ».', 'ton agenda Famille'],
        ['Léa l\'a aussi mis dans son agenda, qu\'elle partage avec toi.', 'Agenda de Léa · « Dîner d\'anniversaire à la maison »'],
        ['Tu voulais lui offrir un livre de photos : elle te le rappellera la veille au soir.', 'dans le chat · aujourd\'hui 12:50', '#chat/agenda']] },
  ],

  /* Les tableaux de droits de chaque agenda (Qui × Par où × Quand), lus de haut en bas.
     lire : oui · non ; ecrire (ajouter, modifier, supprimer) : non · accord · seule ; repondre (aux invitations) : non · accord ;
     garde : rien · un souvenir · un savoir · une confidence ; « — » : sans objet (lecture seule). */
  droits: {
    mon: [
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: 'seule', repondre: 'accord', garde: 'un souvenir' },
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'parole', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
      { qui: 'elle', ou: '—', quand: 'seule', lire: 'oui', ecrire: 'non', repondre: 'accord', garde: 'rien' },
    ],
    travail: [
      { qui: 'toi', ou: 'chat web, app Android', quand: 'repond', lire: 'oui', ecrire: 'accord', repondre: 'accord', garde: 'un savoir' },
      { qui: 'toi', ou: 'Teams', quand: 'repond', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'parole', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
      { qui: 'elle', ou: '—', quand: 'seule', lire: 'oui', ecrire: 'non', repondre: 'accord', garde: 'rien' },
    ],
    perso: [
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: 'accord', repondre: 'accord', garde: 'un souvenir' },
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'parole', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
      { qui: 'elle', ou: '—', quand: 'seule', lire: 'oui', ecrire: 'non', repondre: 'accord', garde: 'rien' },
      { qui: 'lea', partage: 'preparer', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: 'accord', repondre: 'non', garde: 'rien' },
      { qui: 'julien', partage: 'lire', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
    ],
    famille: [
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: 'accord', repondre: 'accord', garde: 'un souvenir' },
      { qui: 'toi', ou: 'en tête-à-tête', quand: 'parole', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
      { qui: 'elle', ou: '—', quand: 'seule', lire: 'oui', ecrire: 'non', repondre: 'non', garde: 'rien' },
    ],
    feries: [
      { qui: 'toi', ou: 'partout', quand: 'toujours', lire: 'oui', ecrire: '—', repondre: '—', garde: 'un savoir' },
      { qui: 'elle', ou: '—', quand: 'seule', lire: 'oui', ecrire: '—', repondre: '—', garde: 'un savoir' },
    ],
    lea: [
      { qui: 'toi', partage: 'lire', ou: 'en tête-à-tête', quand: 'repond', lire: 'oui', ecrire: '—', repondre: '—', garde: 'rien' },
    ],
  },

  /* Ce qui change pendant la visite (les gestes le modifient) : la proposition de Mika, les invitations. */
  etat: { proposition: 'attend', invitations: {}, refusees: {} },
};
