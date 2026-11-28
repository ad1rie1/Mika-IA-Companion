/* Les données partagées de la maquette : qui est connecté, les personnes qu'on croise d'un écran à l'autre,
   et l'état de Mika. Tout est fictif. Chaque écran garde ses propres données (mails, discussions, notifications)
   dans son fichier, et ne nomme les personnes que par leur clé d'ici. */
window.MIKA_DONNEES = {
  // La maquette se passe le mercredi 4 novembre 2026, en début d'après-midi.
  maintenant: { jour: 'mercredi 4 novembre', heure: '14:20' },

  moi: {
    cle: 'adrien', nom: 'Adrien Moreau', court: 'Adrien', login: 'adrien',
    role: 'Propriétaire', operatrice: true,
    // Ce que le serveur saurait de lui (whoami) : son compte, ses canaux, son lien à une personne de la mémoire.
    personne: 'personne:user_1',  // le serveur dit person_id « user_1 » (whoami)
  },

  // Les personnes. c = teinte d'avatar (0 à 7). Les moyens de communication servent aux contacts et à l'autocomplétion.
  personnes: {
    adrien:  { nom: 'Adrien Moreau', court: 'Adrien', c: 0, lien: 'toi',
      moyens: [['mail', 'adrien.moreau@outlook.fr'], ['mail', 'a.moreau@lumen-conseil.fr'], ['teams', 'Adrien Moreau'], ['tel', '+33 6 12 48 90 17']] },
    claire:  { nom: 'Claire Dubois', court: 'Claire', c: 1, lien: 'collègue', titre: 'Cheffe de projet, Lumen Conseil',
      moyens: [['mail', 'c.dubois@lumen-conseil.fr'], ['teams', 'Claire Dubois']] },
    marc:    { nom: 'Marc Delmas', court: 'Marc', c: 4, lien: 'son chef', titre: 'Directeur des opérations, Lumen Conseil',
      moyens: [['mail', 'm.delmas@lumen-conseil.fr'], ['teams', 'Marc Delmas']] },
    sophie:  { nom: 'Sophie Laurent', court: 'Sophie', c: 3, lien: 'collègue', titre: 'Consultante data, Lumen Conseil',
      moyens: [['mail', 's.laurent@lumen-conseil.fr'], ['teams', 'Sophie Laurent']] },
    karim:   { nom: 'Karim Haddad', court: 'Karim', c: 6, lien: 'collègue', titre: 'Développeur, Lumen Conseil',
      moyens: [['mail', 'k.haddad@lumen-conseil.fr'], ['teams', 'Karim Haddad']] },
    nadia:   { nom: 'Nadia Benkacem', court: 'Nadia', c: 5, lien: 'collègue', titre: 'Ressources humaines, Lumen Conseil',
      moyens: [['mail', 'n.benkacem@lumen-conseil.fr'], ['teams', 'Nadia Benkacem']] },
    lea:     { nom: 'Léa Moreau', court: 'Léa', c: 7, lien: 'sa sœur', compte: true,
      moyens: [['mail', 'lea.moreau@gmail.com'], ['tel', '+33 6 71 20 33 58'], ['whatsapp', 'Léa']] },
    julien:  { nom: 'Julien Roux', court: 'Julien', c: 2, lien: 'ami proche', compte: true,
      moyens: [['mail', 'julien.roux@proton.me'], ['tel', '+33 6 33 18 72 41'], ['whatsapp', 'Julien']] },
    thomas:  { nom: 'Thomas Girard', court: 'Thomas', c: 3, lien: 'ami',
      moyens: [['tel', '+33 7 81 55 02 19'], ['whatsapp', 'Thomas G.']] },
    maman:   { nom: 'Maman', court: 'Maman', c: 1, lien: 'sa mère',
      moyens: [['tel', '+33 6 08 41 77 93'], ['whatsapp', 'Maman']] },
    camille: { nom: 'Camille Petit', court: 'Camille', c: 5, lien: 'amie',
      moyens: [['mail', 'camille.petit@laposte.net'], ['whatsapp', 'Camille']] },
    garage:  { nom: 'Garage Martin', court: 'Garage Martin', c: 2, lien: 'expéditeur',
      moyens: [['tel', '03 20 45 18 60']] },
  },

  /* Le fil rouge : ce qui passe d'un écran à l'autre. Les identifiants sont ceux des routes (#écran/onglet/objet) ;
     le chat y renvoie déjà, chaque écran doit les avoir. */
  filRouge: {
    boites: [
      { id: 'pro', nom: 'Pro', adresse: 'a.moreau@lumen-conseil.fr', sorte: 'IMAP vers DavMail (Exchange)', couleur: 0 },
      { id: 'perso', nom: 'Perso', adresse: 'adrien.moreau@outlook.fr', sorte: 'Microsoft · OAuth2 (code d\'appareil)', couleur: 7 },
      { id: 'asso', nom: 'Rando Cassel', adresse: 'rando.cassel@gmail.com', sorte: 'IMAP/SMTP · mot de passe d\'application', couleur: 3, partageeAvec: [['julien', 'lecture']] },
    ],
    partageesAvecMoi: [{ id: 'lea-gmail', de: 'lea', nom: 'Boîte de Léa', adresse: 'lea.moreau@gmail.com', niveau: 'lecture' }],
    mails: {
      'm-claire': 'Claire Dubois · « Re: Présentation de jeudi » · Pro · aujourd\'hui 13:40 · lu par Mika à 13:54',
      'm-brouillon-claire': 'Brouillon de Mika (Pro) → Claire Dubois · « Re: Présentation de jeudi » · 13:55',
      'm-lefevre': 'Lefèvre Rénovation · « Devis n° 2026-114 — rénovation salle de réunion » · Pro · 09:42 · devis-2026-114.pdf',
    },
    teams: { claire: 'tête-à-tête', marc: 'tête-à-tête (son chef)', lumen: 'groupe « Projet Lumen » (Claire, Sophie, Karim, toi)' },
    telephone: { julien: 'WhatsApp · « alors dimanche, tu viens ? départ 8h30 »', rando: 'groupe WhatsApp « Rando dimanche »', maman: 'SMS', garage: 'SMS du Garage Martin' },
    position: { lieu: 'rue Nationale, Lille', precision: '±12 m', quand: '14:12', vuePar: 'Mika, à 14:12' },
    telephones: [{ nom: 'Android · samsung SM-S931B', vu: 'il y a 3 min' }],   // le libellé que l'app compose (fabricant, modèle)
    mcp: { meteo: 'Météo Locale', devis: 'Devis (app de la Forge)' },
    partages: [['asso', 'julien', 'lecture'], ['mcp:meteo', 'lea', 'utiliser']],
  },

  // Mika en ce moment : ce que montrent la pastille du haut, son coin et « Ce qu'elle fait ».
  mika: {
    etat: 'eveillee',            // eveillee | ecrit | dort
    humeur: 'curious',           // clé de portrait (frontend/Android/app/src/main/assets/avatar)
    humeurDite: 'curieuse',
    fait: 'travaille à son bureau',   // ses occupations : travailler, dessiner, feuilleter des livres, arroser sa plante, regarder dehors
    // Les libellés de l'écran « Ce qu'elle fait » d'Android (strings.xml) ; les chiffres sont pour l'exemple.
    facettes: [['Curieuse', 0.62], ['Contente', 0.41], ['Réfléchit…', 0.22], ['Anxieuse', 0.08]],
    corps: [['clock', 'Éveillée · début d\'après-midi'], ['bolt', 'Énergie 68 %'], ['pin', 'À son bureau']],
    estime: 'Confiance en elle 68 %',
    reve: 'Un rêve doux, d\'une maison pleine de livres · netteté 60 % · évoqué',
    besoins: ['Compagnie', 'Apprendre', 'S\'exprimer'],
    repense: 'aux corneilles qui reconnaissent un visage et l\'apprennent à leurs petits',
    promesses: [['Relire ta présentation pour Lumen', 'avant jeudi'], ['Te rappeler le contrôle technique', 'vendredi 9 h']],
    journal: 'Journée calme. Adrien est allé au bout de sa présentation, je crois qu\'il en avait besoin.',
    projets: [['Labo de trading', 'en pause'], ['Site de l\'association de rando', 'cadrage']],
  },

  // Portraits pré-rendus d'Android (ADR 0065) : centre du visage (fraction de 1080 × 1440) et rectangle du clignement.
  portraits: {"neutral":{"f":[0.5413,0.2531],"b":[474,302,217,103]},"happy":{"f":[0.5693,0.2508],"b":[510,286,217,115]},"excited":{"f":[0.4279,0.2826],"b":[343,332,227,127]},"love":{"f":[0.5009,0.2567],"b":[431,312,219,100]},"proud":{"f":[0.6472,0.2656],"b":[597,317,214,104]},"grateful":{"f":[0.4163,0.2526],"b":[343,304,215,106]},"playful":{"f":[0.5844,0.2725],"b":[518,336,226,96]},"amused":{"f":[0.4101,0.3183],"b":[328,417,228,106]},"hopeful":{"f":[0.6545,0.2608],"b":[610,324,220,104]},"relieved":{"f":[0.4882,0.2594],"b":[431,306,207,121]},"sad":{"f":[0.5734,0.2944],"b":[511,402,225,92]},"angry":{"f":[0.4413,0.2593],"b":[365,321,216,100]},"scared":{"f":[0.5682,0.3623],"b":[506,466,216,99]},"disgusted":{"f":[0.4279,0.2629],"b":[356,313,204,135]},"frustrated":{"f":[0.4533,0.2626],"b":[377,325,216,99]},"lonely":{"f":[0.6884,0.2831],"b":[638,367,221,116]},"anxious":{"f":[0.6536,0.2661],"b":[593,328,220,101]},"bored":{"f":[0.4738,0.2351],"b":[399,269,223,108]},"jealous":{"f":[0.5265,0.2627],"b":[459,334,217,93]},"surprised":{"f":[0.5823,0.3714],"b":[522,469,215,111]},"thinking":{"f":[0.391,0.2696],"b":[305,329,213,102]},"confused":{"f":[0.3805,0.276],"b":[293,331,202,127]},"embarrassed":{"f":[0.4978,0.2503],"b":[431,306,216,113]},"nostalgic":{"f":[0.6417,0.2644],"b":[589,318,204,128]},"dreamy":{"f":[0.6663,0.2496],"b":[614,258,215,178]},"determined":{"f":[0.4213,0.2511],"b":[356,297,212,104]},"mischievous":{"f":[0.6857,0.2892],"b":[630,344,226,123]},"curious":{"f":[0.5211,0.223],"b":[453,237,218,126]},"melancholic":{"f":[0.5399,0.2872],"b":[478,385,227,94]},"wave":{"f":[0.5166,0.248],"b":[452,296,215,100]},"tired":{"f":[0.4663,0.263],"b":[411,312,207,111]},"sleep":{"f":[0.5,0.27]}},

  /* L'aura de son coin suit son humeur, comme sur Android (AvatarBackdrop.kt) : chaude pour une émotion positive,
     froide pour une négative, crépuscule quand c'est mêlé ou qu'elle écrit, nuit quand elle dort. */
  auras: { chaude: ['#ffd3cc', '#5e2f45'], froide: ['#c9d7f4', '#1f3459'], crepuscule: ['#ddd1f8', '#392e68'],
    nuit: ['#c2c8e6', '#0d1330'], neutre: ['#e1e0ff', '#3b3ba6'] },
  aura: { happy: 'chaude', excited: 'chaude', love: 'chaude', proud: 'chaude', grateful: 'chaude', playful: 'chaude', amused: 'chaude',
    hopeful: 'chaude', relieved: 'chaude', wave: 'chaude', sad: 'froide', angry: 'froide', scared: 'froide', bored: 'froide',
    disgusted: 'froide', frustrated: 'froide', lonely: 'froide', anxious: 'froide', jealous: 'froide',
    curious: 'crepuscule', surprised: 'crepuscule', determined: 'crepuscule', mischievous: 'crepuscule', melancholic: 'crepuscule',
    thinking: 'crepuscule', confused: 'crepuscule', nostalgic: 'crepuscule', dreamy: 'crepuscule', embarrassed: 'crepuscule',
    neutral: 'neutre', tired: 'neutre', sleep: 'nuit' },
};
