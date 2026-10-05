"""La carte de la console, décidée par la composition (comme la liste des
facultés) : ses groupes, ses destinations, et les onglets que la console
fournit elle-même. Les facultés, elles, y rangent leurs vues par ``section``.

La carte répond à des questions d'opérateur, dans cet ordre : que dois-je
faire (tableau de bord) ; comment va-t-elle (Elle) ; qui connaît-elle (Ses
relations) ; que fait-elle et pourquoi (Son activité : ses décisions, ses
buts, ses projets) ; par où perçoit-elle et agit-elle (Ses canaux) ; que
décide-t-on, la machine tient-elle (Exploitation). ``docs/console-carte.md`` détaille chaque menu.
"""

from __future__ import annotations

from mika.inspector.catalog import Destination, Labels, NavGroup

NAVIGATION: tuple[NavGroup, ...] = (
    NavGroup("", (
        Destination("accueil", "Tableau de bord", "◉", "Ce qui attend ton attention, son état en ce moment et sa "
                    "journée.",
                    builtin=("accueil.a_traiter", "accueil.maintenant", "accueil.aujourdhui", "accueil.courbes"),
                    layout="stack"),
    )),
    NavGroup("Elle", (
        Destination("vie", "Humeur et corps", "♡", "Son humeur, ses postures envers chacun, ses besoins, son "
                    "rythme, son estime."),
        Destination("pensees", "Pensées et nuits", "☁", "Ce qui lui trotte dans la tête, ce qu'elle a remarqué, "
                    "ce qu'elle attend, ses nuits."),
        Destination("memoire", "Mémoire", "❖", "Ses souvenirs, ses croyances, ses promesses et la relecture de ses échanges."),
    )),
    NavGroup("Ses relations", (
        Destination("personnes", "Personnes", "☺", "Les gens qu'elle connaît et ce qui les lie.",
                    subjects=("person",)),
        Destination("identites", "Identités", "◎", "Qui parle derrière chaque adresse, et ce que ça ouvre.",
                    subjects=("handle",)),
        Destination("fil", "Conversations", "❝", "Ce qui a été dit, avec qui, et les questions qui attendent."),
    )),
    NavGroup("Son activité", (
        Destination("decisions", "Décisions", "⚖", "Pourquoi elle parle ou se tait : les preuves de l'arbitre, ce "
                    "qui tourne en ce moment, son budget d'initiatives, ses choix, ses épisodes, ses échéances.",
                    builtin=("decisions.maintenant", "decisions.envers", "decisions.en_cours", "decisions.selections",
                             "decisions.episodes", "decisions.echeances"),
                    order=("maintenant", "envers", "en_cours", "initiatives", "selections", "episodes",
                           "echeances")),
        Destination("buts", "Buts", "➤", "Ce qu'elle se propose de faire ensuite : ses rappels et ses "
                    "explorations, où ils en sont.", subjects=("goal",)),
        Destination("projets", "Projets", "▦", "Ses projets : des espaces de travail qu'on pilote — objectifs, "
                    "exécutions, décisions techniques, fichiers, dépôt git, mode et outils.",
                    subjects=("project",)),
        Destination("outils", "Ses outils", "✋", "Tout ce qu'elle peut faire : ses outils à elle (lus ici, définis "
                    "dans le code), ceux de ses apps et des services extérieurs — pour qui, quand, et ce qu'elle en lit.",
                    builtin=("outils.tous", "outils.qui", "outils.texte", "outils.expose"), subjects=("serveur",)),
        Destination("approbations", "Approbations", "✓", "Ce qu'elle voudrait faire sortir de la machine, et ce "
                    "qui en a été décidé.", builtin=("approbations.en_attente", "approbations.historique")),
    )),
    NavGroup("Ses canaux", (
        Destination("courrier", "Courrier", "✉", "Lire les messages, répondre et suivre les brouillons de chaque boîte.",
                    subjects=("mail", "brouillon", "compte"), context=("compte",), automatic_actions=False),
        Destination("sens", "Flux et capteurs", "◌", "Ce qu'elle lit du monde (flux RSS), ce qu'elle voit "
                    "(caméra), ce que ses appareils lui signalent."),
        Destination("apps", "Apps forgées", "⚒", "Les petites apps qu'elle écrit elle-même.", subjects=("app",)),
    )),
    NavGroup("Exploitation", (
        Destination("reglages", "Configuration", "⚙", "Ce qu'un opérateur décide. Chaque page ne règle qu'un "
                    "sujet ; chaque champ dit ce qu'il fait.", layout="menu", dynamic=True),
        Destination("systeme", "Système", "▣", "La machine : santé, processus, anomalies, sorties, modèles, coûts, "
                    "stockage, journaux, anatomie.", layout="menu",
                    builtin=("systeme.sante", "systeme.processus", "systeme.anomalies", "systeme.sorties",
                             "systeme.passerelle", "systeme.appels", "systeme.stockage", "systeme.chronologie",
                             "systeme.operations", "systeme.etat", "systeme.contributions", "systeme.vues",
                             "systeme.simulations")),
    )),
)

#: Configuration › Comportement : les facultés rangées par famille, et leur nom
#: pour un opérateur (les autres tombent dans « Autres », sous leur nom technique)
PARAM_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Émotions", ("affect", "needs", "body", "self")),
    ("Esprit", ("attention", "memory", "transcript")),
    ("Relations", ("social", "others", "identity")),
    ("Action", ("agency", "goals", "projects", "shares", "imaging", "world")),
    ("Canaux", ("email", "rss", "web", "camera", "forge")),
    ("Noyau", ("kernel",)),
)
FACULTY_LABELS: dict[str, str] = {
    "affect": "Humeur et postures", "needs": "Besoins", "body": "Corps et sommeil", "self": "Estime et récit",
    "attention": "Attention et pensées", "memory": "Mémoire", "transcript": "Fil des conversations",
    "social": "Liens", "others": "Ce qu'elle devine des autres", "identity": "Identités",
    "agency": "Initiatives", "goals": "Buts", "projects": "Projets", "email": "Courrier", "rss": "Flux RSS", "camera": "Caméra",
    "forge": "Moteur de la Forge", "kernel": "Noyau", "presence": "Présence", "expression": "Expression",
    "sensors": "Appareils", "runtime": "Moteur", "place": "Où elle est (sa chambre)",
    "world": "Son monde et son corps", "shares": "Fichiers envoyés", "imaging": "Dessins",
    "mcp": "Outils extérieurs", "web": "Recherche web",
}

#: Les sections du prompt, nommées par ce qu'elles lui montrent (Pourquoi a-t-elle dit ça ?, Prompt).
SECTION_LABELS: dict[str, str] = {
    "who": "Qui elle a en face", "history": "Le fil de la conversation", "memories": "Ses souvenirs rappelés",
    "shared_memories": "Ce qu'ils ont vécu ensemble", "past_exchanges": "Des échanges passés",
    "promises": "Ce qu'elle a promis", "rhythm": "Son rythme (heure, énergie)",
    "fog": "Sa fatigue (brouillard)", "mood": "Son humeur", "stance": "Sa posture envers la personne",
    "needs": "Ses besoins", "their_state": "Ce qu'elle devine de l'autre", "thoughts": "Ce qui lui trotte dans la tête",
    "narrative": "Qui elle est devenue (récit de soi)", "self_state": "Son estime d'elle-même",
    "yesterday": "Son fil d'hier (journal)", "dream": "Son rêve de la nuit", "style": "Sa façon de parler",
    "about_person": "Ce qu'elle sait de la personne", "step": "Ce à quoi elle travaille",
    "subject": "Le sujet de l'initiative", "goals": "Ses buts en cours", "project": "Ce projet",
    "project_share": "Un projet à partager", "projects": "Ses projets", "mails": "Ses mails non lus",
    "drafts": "Ses brouillons de mails", "voice": "Sa voix dans cette boîte", "task_mail": "Le mail à traiter",
    "task_ask": "Ce qu'on lui demande pour ce mail", "headlines": "Les titres de ses flux",
    "views": "Ce que voit la caméra", "apps": "Ses apps forgées",
    # déclarées par des lots voisins (ADR 0033, 0034, 0036) : nommées d'avance, sans effet tant qu'elles n'existent pas
    "life": "Ce qui se passe dans la vie de la personne", "matter": "Ce dont elle pourrait parler",
    "noticed": "Ce qu'elle a remarqué", "habits": "Ce qu'elle s'entend répéter",
    "mail_mention": "Le mail important qu'elle annonce", "step_origin": "Ce qui a fait naître le but",
    "project_network": "Ce que le réseau a rendu",
    # ADR 0047
    "greeting_tone": "Le ton de ses bonjours (sa persona)",
    # ADR 0046
    "self_said": "Ce qu'elle a déjà dit d'elle-même", "register": "Le ton entre eux (selon leur lien)",
    "world": "Autour d'elle : son corps, ce qu'elle a à portée",
    # ADR 0053
    # ADR 0062
    "sent_files": "Ce qu'elle lui a déjà envoyé (fichiers)", "dessins": "Ses dessins pour la personne",
    "services": "Ce que ses services extérieurs lui ont rendu",
    "step_exchange": "L'échange d'où vient sa réflexion", "step_life": "Ce qui se passe dans la vie de la personne "
    "(sa réflexion)",
}

#: Les raisons des preuves de l'arbitre : ce qui la pousse à agir.
REASON_LABELS: dict[str, str] = {
    "mood_overflow": "Une humeur qui déborde", "need_expression": "Besoin de s'exprimer",
    "need_social": "Envie de compagnie", "check_in": "Prendre des nouvelles", "follow_up": "Demander comment ça s'est passé", "thought": "Une pensée à partager",
    "greeting": "Saluer", "present": "Quelqu'un de présent", "chat": "Envie de bavarder",
    "comfort": "Réconforter", "recontact": "Reprendre contact après un silence", "work": "Avancer sur un but",
    "remind": "Rappeler ce qu'on lui a demandé", "share": "Partager où en est un but",
    "drawing_ready": "Montrer un dessin prêt", "drawing_failed": "Dire qu'un dessin n'a pas pu se faire",
    "service_answered": "Dire ce qu'un service extérieur a rendu",
    "run": "Travailler sur un projet", "project_share": "Partager où en est un projet",
    "mail_mention": "Parler d'un mail reçu", "mail_draft": "Préparer une réponse à un mail",
    "second_thoughts": "Elle s'est ravisée", "project_need": "Demander un coup de main pour un projet",
    "keep_promise": "Tenir une promesse au moment dit", "cheer": "Encourager avant un moment important",
    "celebrate": "Souhaiter ce qui se fête (un anniversaire), le jour même",
    # ADR 0058
    "rekindle": "Reprendre des nouvelles, longtemps après (une fois)",
}

#: Les vetos : ce qui l'empêche d'agir.
VETO_LABELS: dict[str, str] = {
    "asleep": "Elle dort", "waking": "Elle vient de se réveiller", "woken_at_night": "Réveillée en pleine nuit",
    "daily_cap": "Budget d'initiatives du jour épuisé", "grudge": "Elle est fâchée contre cette personne",
    "unanswered": "Sa dernière initiative est restée sans réponse", "run_cap": "Assez d'exécutions pour l'heure",
    "step_cap": "Assez de séances de travail pour l'heure",
    "awaiting_reply": "Elle attend sa réponse (elle a écrit en dernier)", "farewell": "Ils viennent de se dire au revoir", "changed_mind": "Elle s'est ravisée", "hesitating": "Elle hésite encore (ses derniers essais ont fini en silence)",
}

#: Les processus de fond : ce qu'ils font.
PROCESS_LABELS: dict[str, str] = {
    "transcript.compact": "Replier les longs fils en résumé", "memory.consolidate": "Retenir (souvenirs, croyances)",
    "memory.index": "Indexer la mémoire", "memory.reflect": "Repenser à ce qu'elle sait",
    "memory.night": "Trier la mémoire la nuit", "body.sleep": "S'endormir et se réveiller",
    "needs.empty": "Sentir le vide", "attention.watch": "Remarquer et attendre",
    "attention.digest": "Digérer ses pensées la nuit", "self.narrate": "Se raconter",
    "self.journal": "Tenir son journal", "self.dream": "Rêver", "social.profile": "Comprendre les gens",
    "goals.seed": "Se proposer des buts", "goals.tend": "Suivre ses buts", "projects.tend": "Suivre ses projets",
    "projects.remote": "Pousser et récupérer les dépôts", "email.poll": "Relever le courrier",
    "rss.poll": "Relever les flux", "mcp.watch": "Rejoindre les serveurs d'outils extérieurs", "camera.look": "Regarder par la caméra", "forge.tick": "Faire tourner les apps",
    "forge.events": "Transmettre les événements aux apps", "forge.discover": "Découvrir les apps",
    "memory.promises": "Tenir ou laisser filer ses promesses", "self.wake": "Se réveiller avec sa nuit",
    "social.reciprocity": "Remarquer qui écrit en premier",
    "memory.follow": "Remarquer qu'elle a repris un moment de la vie de quelqu'un",
    "world.settle": "Conclure ses gestes dans le monde",
    "shares.retention": "Retirer les fichiers envoyés trop anciens", "imaging.draw": "Dessiner",
    "mcp.expire": "Refuser les accords restés sans réponse",
}

#: Les événements des facultés : ce qui s'est passé (ceux du noyau et du moteur sont nommés par la console).
EVENT_LABELS: dict[str, str] = {
    "presence.connected": "Connexion", "presence.disconnected": "Déconnexion",
    "place.moved": "Elle s'est déplacée dans sa chambre",
    "world.authored": "Le monde édité", "world.described": "Un élément du monde décrit",
    "world.intended": "Un geste commencé dans le monde", "world.ended": "Un geste terminé dans le monde",
    "world.changed": "Le monde a changé", "world.requested": "Une demande dans le monde",
    "world.answered": "Une réponse à une demande", "world.gestured": "Un geste vers quelqu'un",
    "world.joined": "Quelqu'un est entré dans le monde", "world.left": "Quelqu'un est sorti du monde",
    "world.noticed": "Quelque chose de remarqué dans le monde",
    "identity.claimed": "Un nom revendiqué", "identity.evidence": "Une preuve d'identité",
    "identity.linked": "Une adresse reliée", "identity.registered": "Un compte enregistré",
    "identity.name_bound": "Un nom relié à une personne (« celle dont on lui a parlé »)",
    "transcript.compacted": "Un fil replié en résumé",
    "memory.believed": "Une croyance retenue", "memory.consolidated": "Une relecture de la mémoire",
    "memory.night_sorted": "La mémoire triée la nuit", "memory.promise_noticed": "Une promesse remarquée",
    "memory.promise_resolved": "Une promesse tenue ou abandonnée", "memory.reinforced": "Un souvenir renforcé",
    "memory.remembered": "Un souvenir retenu",
    "body.fell_asleep": "Endormie", "body.woke": "Réveillée", "needs.felt": "Un besoin ressenti",
    "others.read": "Ce qu'elle devine de quelqu'un",
    "attention.digested": "Une pensée digérée", "attention.dwelt": "Une pensée ressassée",
    "attention.expectation_met": "Une attente comblée", "attention.expectation_missed": "Une attente déçue",
    "attention.noticed": "Quelque chose de remarqué", "attention.thought_born": "Une pensée née",
    "self.dreamt": "Un rêve", "self.journaled": "Son journal", "self.narrated": "Son récit de soi",
    "self.persona_revised": "Sa persona révisée",
    "social.closeness_set": "La proximité réglée", "social.profile_revised": "Un profil revu",
    "goals.amended": "Un but modifié", "goals.awaited": "Un but en attente", "goals.closed": "Un but clos",
    "goals.deposited": "Un fichier déposé dans un but", "goals.noted": "Une note sur un but",
    "goals.nudged": "Un but relancé", "goals.opened": "Un but ouvert", "goals.paused": "Un but en pause",
    "goals.reframed": "Un but recadré", "goals.reopened": "Un but rouvert", "goals.resumed": "Un but repris",
    "goals.step_reported": "Une séance de travail rendue", "goals.task_added": "Une tâche ajoutée",
    "goals.task_changed": "Une tâche modifiée", "goals.task_removed": "Une tâche retirée",
    "projects.amended": "Un projet modifié", "projects.archived": "Un projet archivé",
    "projects.created": "Un projet créé", "projects.decided": "Une décision technique",
    "projects.decision_changed": "Une décision technique revue", "projects.deposited": "Un fichier déposé",
    "projects.noted": "Une note sur un projet", "projects.nudged": "Un projet relancé",
    "projects.objective_added": "Un objectif ajouté", "projects.objective_changed": "Un objectif modifié",
    "projects.objective_closed": "Un objectif clos", "projects.paused": "Un projet en pause",
    "projects.reframed": "Un projet recadré", "projects.remote_requested": "Un échange avec le dépôt distant demandé",
    "projects.restored": "Un projet restauré", "projects.resumed": "Un projet repris",
    "projects.run_reported": "Une exécution rendue",
    "email.draft_asked": "Une réponse à un mail demandée", "email.noticed": "Un mail remarqué",
    "email.poll_asked": "Une relève demandée", "email.read": "Un mail lu", "email.sent": "Un mail envoyé",
    "rss.noticed": "Un article remarqué", "camera.seen": "Ce que la caméra a vu",
    "mcp.status": "L'état de ses serveurs extérieurs", "mcp.answered": "Ce qu'un service extérieur a rendu",
    "forge.emitted": "Une app a signalé", "forge.handled": "Une app a traité un événement",
    "forge.signaled": "Une app l'a interpellée", "forge.switched": "Une app allumée ou éteinte",
    "forge.ticked": "Une app a tourné", "forge.written": "Une app écrite", "sensors.sensed": "Un appareil a signalé",
    "memory.event_noted": "Un événement de la vie de quelqu'un, noté", "body.roused": "Réveillée par un message",
    "body.waited": "Un message attend son réveil", "attention.touched": "Une pensée effleurée par un message",
    "self.woke_with": "Ce qu'elle emporte de sa nuit", "self.touched": "Touchée par ce qu'on lui a dit",
    "projects.network_queued": "Une commande réseau mise en file (après l'exécution)",
    "social.one_sided": "C'est presque toujours elle qui écrit",
    "needs.reunited": "Une amie revenue après un moment creux",
    "memory.moment_followed": "Un moment de la vie de quelqu'un, repris",
    "memory.situation_ended": "Une situation de la vie de quelqu'un, finie",
    "shares.shared": "Un fichier envoyé", "shares.expired": "Des fichiers envoyés retirés",
    "imaging.requested": "Un dessin demandé", "imaging.drawn": "Un dessin prêt",
    "imaging.failed": "Un dessin qui n'a pas pu se faire",
}

#: Tout ce que la console nomme en français, d'un bloc.
LABELS = Labels(faculties=FACULTY_LABELS, sections=SECTION_LABELS, reasons=REASON_LABELS, vetoes=VETO_LABELS,
                processes=PROCESS_LABELS, events=EVENT_LABELS)
