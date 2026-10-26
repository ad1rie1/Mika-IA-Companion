"""La carte de la console, décidée par la composition (comme la liste des
facultés) : ses groupes, ses destinations, et les onglets que la console
fournit elle-même. Les facultés, elles, y rangent leurs vues par ``section``.

La carte répond à des questions d'opérateur, dans cet ordre : que dois-je
faire (l'accueil, dessiné à la main hors de la carte : ``app/handmade/home.py``, qui lit les onglets ``accueil.*``) ;
comment va-t-elle (sa rubrique, à son nom) ; qui connaît-elle (Relations & échanges) ; que fait-elle et pourquoi
(Activité : ses décisions, ses buts, ses projets ; Outils ; À valider) ; par où perçoit-elle et agit-elle
(Connexions extérieures) ; que décide-t-on, la machine tient-elle (Réglages, Système). Le menu visible est
``app/console_menu.py`` : chaque groupe ci-dessous porte le nom de la rubrique où ses destinations s'y rangent (le
groupe ne se montre que si une destination n'avait pas de lien au menu). ``docs/console-carte.md`` détaille chaque
menu.
"""

from __future__ import annotations

from mika.inspector.catalog import Destination, Labels, NavGroup

NAVIGATION: tuple[NavGroup, ...] = (
    NavGroup("Elle", (
        Destination("vie", "Humeur et corps", "Son humeur, ses postures envers chacun, ses besoins, son "
                    "rythme, son estime."),
        Destination("pensees", "Pensées et nuits", "Ce qui lui trotte dans la tête, ce qu'elle a remarqué, "
                    "ce qu'elle attend, ses nuits."),
        Destination("memoire", "Mémoire", "Ses souvenirs, ses croyances, ses promesses, les pièces qu'on lui a "
                    "envoyées et la relecture de ses échanges.", subjects=("piece",)),
    )),
    NavGroup("Relations & échanges", (
        Destination("personnes", "Personnes", "Les gens qu'elle connaît et ce qui les lie.",
                    subjects=("person",)),
        Destination("identites", "Identités", "Qui parle derrière chaque moyen de communication, et ce "
                    "que ça ouvre.",
                    subjects=("handle",)),
        Destination("fil", "Conversations", "Ce qui a été dit, avec qui, et les questions qui attendent."),
    )),
    NavGroup("Activité", (
        Destination("decisions", "Décisions", "Pourquoi elle parle ou se tait : les preuves de l'arbitre, ce "
                    "qui tourne en ce moment, son budget d'initiatives, ses choix, ses épisodes, ses échéances.",
                    builtin=("decisions.maintenant", "decisions.envers", "decisions.en_cours", "decisions.selections",
                             "decisions.episodes", "decisions.echeances"),
                    order=("maintenant", "envers", "en_cours", "initiatives", "selections", "episodes",
                           "echeances")),
        Destination("buts", "Buts", "Ce qu'elle se propose de faire ensuite : ses rappels et ses "
                    "explorations, où ils en sont.", subjects=("goal",)),
        Destination("projets", "Projets", "Ses projets : des espaces de travail qu'on pilote — objectifs, "
                    "exécutions, décisions techniques, fichiers, dépôt git, mode et outils.",
                    subjects=("project",)),
    )),
    NavGroup("Outils", (
        Destination("outils", "Outils", "Ce qu'elle peut faire et avec qui, ses propres outils et leurs droits, ce "
                    "qui lui vient d'ailleurs (les services branchés, ses apps), et ce que tu prêtes à un agent.",
                    builtin=("outils.tous", "outils.expose"),
                    order=("tous", "serveurs", "expose"), subjects=("serveur",)),
    )),
    NavGroup("À valider", (
        Destination("approbations", "À valider", "Ce qu'elle voudrait faire sortir de la machine, et ce "
                    "qui en a été décidé.", builtin=("approbations.en_attente", "approbations.historique")),
    )),
    NavGroup("Relations & échanges", (
        Destination("courrier", "Courrier", "Lire les messages, répondre et suivre les brouillons de chaque boîte.",
                    subjects=("mail", "brouillon", "compte"), context=("compte",), automatic_actions=False),
        Destination("teams", "Teams", "Les conversations Teams que l'extension lui apporte, et les réponses "
                    "qu'elle prépare à ta place : posées, à accepter, parties.",
                    subjects=("conversation_teams", "reponse_teams")),
    )),
    NavGroup("Connexions extérieures", (
        Destination("sens", "Connexions extérieures", "Ce qu'elle lit du monde (flux RSS), ce qu'elle voit "
                    "(caméra), ce que ses appareils lui signalent."),
        Destination("reveils", "Réveils par API", "Les réveils que des systèmes extérieurs lui envoient "
                    "(POST /api/wake/<nom>) : les déclarer, leurs clés, leurs appels et ce qu'ils ont donné.",
                    subjects=("reveil",)),
    )),
    NavGroup("Outils", (
        Destination("apps", "Apps forgées", "Les petites apps qu'elle écrit elle-même.", subjects=("app",)),
    )),
    NavGroup("Réglages", (
        Destination("reglages", "Réglages", "Ce qu'un opérateur décide. Chaque page ne règle qu'un "
                    "sujet ; chaque champ dit ce qu'il fait.", layout="menu", dynamic=True),
    )),
    NavGroup("Système", (
        Destination("systeme", "Système", "La machine : santé, processus, anomalies, sorties, modèles, écrans "
                    "du monde, coûts, stockage, journaux, anatomie.", layout="menu",
                    builtin=("systeme.sante", "systeme.processus", "systeme.anomalies", "systeme.sorties",
                             "systeme.passerelle", "systeme.monde", "systeme.appels", "systeme.stockage",
                             "systeme.chronologie",
                             "systeme.operations", "systeme.etat", "systeme.contributions", "systeme.vues",
                             "systeme.simulations")),
    )),
)

#: Réglages › Paramètres avancés : les facultés rangées par famille, et leur nom
#: pour un opérateur (les autres tombent dans « Autres », sous leur nom technique)
PARAM_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Émotions", ("affect", "needs", "body", "self")),
    ("Esprit", ("attention", "memory", "attachments", "transcript")),
    ("Relations", ("social", "others", "identity")),
    ("Action", ("agency", "goals", "projects", "shares", "imaging", "world")),
    ("Plugins", ("email", "teams", "phone", "rss", "web", "camera", "forge", "wakeup")),
    ("Noyau", ("kernel",)),
)
FACULTY_LABELS: dict[str, str] = {
    "affect": "Humeur et postures", "needs": "Besoins", "body": "Corps et sommeil", "self": "Estime et récit",
    "attention": "Attention et pensées", "memory": "Mémoire", "transcript": "Fil des conversations",
    "social": "Liens", "others": "Ce qu'elle devine des autres", "identity": "Identités",
    "agency": "Initiatives", "goals": "Buts", "projects": "Projets", "email": "Courrier", "rss": "Flux RSS", "camera": "Caméra",
    "forge": "Moteur de la Forge", "kernel": "Noyau", "presence": "Présence", "expression": "Expression",
    "sensors": "Appareils", "runtime": "Moteur", "place": "Où elle est (sa chambre)",
    "world": "Son monde et son corps", "shares": "Fichiers envoyés", "attachments": "Pièces reçues",
    "imaging": "Dessins", "location": "Localisation", "forge_signals": "Signaux de ses apps",
    "mcp": "Outils extérieurs", "web": "Recherche web", "wakeup": "Réveils par API", "teams": "Teams",
    "phone": "Messages du téléphone",
}

#: Les sections du prompt, nommées par ce qu'elles lui montrent (Pourquoi a-t-elle dit ça ?, Prompt).
SECTION_LABELS: dict[str, str] = {
    "who": "Qui elle a en face", "history": "Le fil de la conversation", "memories": "Ses souvenirs rappelés",
    "shared_memories": "Ce qu'ils ont vécu ensemble", "past_exchanges": "Des échanges passés",
    "promises": "Ce qu'elle a promis", "rhythm": "Son rythme (heure, énergie)",
    "fog": "Sa fatigue (brouillard)", "mood": "Son humeur", "stance": "Sa posture envers la personne",
    "needs": "Ses besoins", "their_state": "Ce qu'elle devine de l'autre", "thoughts": "Ce qui lui trotte dans la tête",
    "narrative": "Qui elle est devenue (récit de soi)",
    "self_state": "Son estime d'elle-même", "self_model": "Ce qu'elle sait d'elle (tendances, changements d'avis)",
    "absence": "Son absence (serveur arrêté, de quand à quand)",
    "yesterday": "Son fil d'hier (journal)", "dream": "Son rêve de la nuit", "style": "Sa façon de parler",
    "about_person": "Ce qu'elle sait de la personne", "step": "Ce à quoi elle travaille",
    "subject": "Le sujet de l'initiative", "goals": "Ses buts en cours", "project": "Ce projet",
    "project_share": "Un projet à partager", "projects": "Ses projets", "mails": "Ses mails non lus",
    "drafts": "Ses brouillons de mails", "voice": "Sa voix dans cette boîte", "task_mail": "Le mail à traiter",
    "task_ask": "Ce qu'on lui demande pour ce mail", "edits": "Ce qu'on change à ses brouillons (retouches, refus)",
    "headlines": "Les titres de ses flux",
    "views": "Ce que voit la caméra", "apps": "Ses apps forgées", "app_news": "Ce que ses apps ont trouvé pour la personne",
    "app_signals": "Ce qu'une app a mis dans sa file", "app_consignes": "Les consignes du projet d'une app",
    # ADR 0033, 0034, 0036
    "life": "Ce qui se passe dans la vie de la personne",
    "ahead": "Ce qui vient : le monde, et ce qu'elle vivra à travers quelqu'un",
    "learned": "Ce qu'elle a appris en lisant", "acquainted": "Les gens qu'on nomme (qu'elle connaît dans son cercle)", "veiled": "Ce qu'elle peut raconter sans nommer personne", "matter": "Ce dont elle pourrait parler",
    "noticed": "Ce qu'elle a remarqué", "habits": "Ce qu'elle s'entend répéter", "answer": "Sa réponse (le dernier rappel)",
    "mail_mention": "Le mail important qu'elle annonce", "step_origin": "Ce qui a fait naître le but",
    "project_network": "Ce que le réseau a rendu",
    "project_answer": "La réponse à sa demande d'aide (un projet)",
    # ADR 0047
    "greeting_tone": "Le ton de ses bonjours (sa persona)",
    # ADR 0046
    "self_said": "Ce qu'elle a déjà dit d'elle-même", "register": "Le ton entre eux (selon leur lien)",
    # ADR 0137
    "their_day": "Sa journée (lui demander comment elle se passe)",
    # ADR 0062
    "sent_files": "Ce qu'elle lui a déjà envoyé (fichiers)", "dessins": "Ses dessins pour la personne",
    "services": "Ce que ses services extérieurs lui ont rendu", "app_calls": "Ce que ses apps lui ont rendu après un accord",
    "step_exchange": "L'échange d'où vient sa réflexion", "step_life": "Ce qui se passe dans la vie de la personne "
    "(sa réflexion)",
    # ADR 0068
    "wake_order": "Ce qu'un réveil par API lui demande (ses consignes)",
    "wake_text": "Ce qu'apporte l'appel d'un réveil par API (cité)",
    "wake_reports": "Ce que ses réveils par API ont donné",
    # ADR 0069
    "teams_messages": "Ses messages Teams récents", "teams_drafts": "Ses réponses Teams et ce qu'elles sont devenues",
    "teams_voice": "Comment elle écrit dans Teams (à ta place)",
    "teams_task": "Le message Teams auquel elle prépare une réponse (cité)",
    "teams_ask": "Ce qu'on lui demande d'y répondre (Teams)",
    "phone_offers": "Ce que sont devenues ses réponses proposées sur le téléphone",
    "crossed": "Elle allait justement lui écrire (leurs messages se sont croisés)",
}

#: Les raisons des preuves de l'arbitre : ce qui la pousse à agir.
REASON_LABELS: dict[str, str] = {
    "mood_overflow": "Une humeur qui déborde", "need_expression": "Besoin de s'exprimer",
    "need_social": "Envie de compagnie", "check_in": "Prendre des nouvelles", "follow_up": "Demander comment ça s'est passé", "thought": "Une pensée à partager",
    "greeting": "Saluer", "present": "Quelqu'un de présent", "chat": "Envie de bavarder",
    "comfort": "Réconforter", "recontact": "Reprendre contact après un silence", "work": "Avancer sur un but",
    "remind": "Rappeler ce qu'on lui a demandé", "share": "Partager où en est un but",
    "drawing_ready": "Montrer un dessin prêt", "drawing_failed": "Dire qu'un dessin n'a pas pu se faire",
    "service_answered": "Dire ce qu'un service extérieur a rendu", "app_answered": "Dire ce qu'une app a rendu après un accord", "app_news": "Dire ce qu'une app a trouvé", "app_alert": "Prévenir d'une urgence qu'une app a trouvée", "app_triage": "Lire la file de signaux d'une app",
    "run": "Travailler sur un projet", "project_share": "Partager où en est un projet",
    "mail_mention": "Parler d'un mail reçu", "mail_draft": "Préparer une réponse à un mail",
    "rss_for": "Partager un titre qui lui a fait penser à cette personne",
    "second_thoughts": "Elle s'est ravisée", "project_need": "Demander un coup de main pour un projet",
    "keep_promise": "Tenir une promesse au moment dit", "cheer": "Encourager avant un moment important",
    "celebrate": "Souhaiter ce qui se fête (un anniversaire), le jour même",
    "remembrance": "Un mot doux à une proche, le jour où revient la date d'un deuil",
    # ADR 0058
    "rekindle": "Reprendre des nouvelles, longtemps après (une fois)",
    # ADR 0068
    "wakeup": "Un réveil par API à traiter", "wakeup_done": "Rendre compte de ce qu'un réveil par API a donné",
    # ADR 0069
    "teams_draft": "Préparer une réponse à un message Teams",
}

#: Les vetos : ce qui l'empêche d'agir.
VETO_LABELS: dict[str, str] = {
    "asleep": "Elle dort", "waking": "Elle vient de se réveiller", "woken_at_night": "Réveillée en pleine nuit",
    "daily_cap": "Budget d'initiatives du jour épuisé", "grudge": "Elle est fâchée contre cette personne",
    "unanswered": "Sa dernière initiative est restée sans réponse", "run_cap": "Assez d'exécutions pour l'heure",
    "step_cap": "Assez de séances de travail pour l'heure",
    "awaiting_reply": "Elle attend sa réponse (elle a écrit en dernier)", "farewell": "Ils viennent de se dire au revoir", "changed_mind": "Elle s'est ravisée", "hesitating": "Elle hésite encore (ses derniers essais ont fini en silence)",
    "composing": "La personne est en train de lui écrire",
    "not_reachable": "La personne n'est pas là, à une heure où elle n'écrit pas d'habitude",
    # ADR 0127
    "held": "Le quota de l'abonnement est réservé à la conversation",
}

#: Les processus de fond : ce qu'ils font.
PROCESS_LABELS: dict[str, str] = {
    "transcript.compact": "Replier les longs fils en résumé", "memory.consolidate": "Retenir (souvenirs, croyances)",
    "memory.calendar": "Se rappeler les dates proches",
    "memory.index": "Indexer la mémoire", "memory.reflect": "Repenser à ce qu'elle sait",
    "memory.lies": "Se souvenir de ses mensonges",
    "memory.night": "Trier la mémoire la nuit", "memory.reread": "Relire ses lectures la nuit",
    "memory.delicate": "Garder pour confidence ce qui touche un sujet délicat",
    "attention.anticipate": "Attendre ce qui approche", "body.sleep": "S'endormir et se réveiller",
    "needs.empty": "Sentir le vide", "attention.watch": "Remarquer et attendre",
    "attention.digest": "Digérer ses pensées la nuit", "self.narrate": "Se raconter",
    "self.journal": "Tenir son journal", "self.dream": "Rêver", "self.reflect": "Voir ce qui la passionne", "social.profile": "Comprendre les gens",
    "goals.seed": "Se proposer des buts", "goals.tend": "Suivre ses buts", "projects.tend": "Suivre ses projets",
    "projects.apps": "Réparer les apps de ses projets",
    "projects.remote": "Pousser et récupérer les dépôts", "email.poll": "Relever le courrier",
    "rss.poll": "Relever les flux", "mcp.watch": "Rejoindre les serveurs d'outils extérieurs", "camera.look": "Regarder par la caméra", "forge.tick": "Faire tourner les apps",
    "forge.events": "Transmettre les événements aux apps", "forge.discover": "Découvrir les apps",
    "memory.promises": "Tenir ou laisser filer ses promesses", "self.wake": "Se réveiller avec sa nuit",
    "social.reciprocity": "Remarquer qui écrit en premier",
    "social.bonds": "Remarquer qu'un lien a changé",
    "memory.follow": "Remarquer qu'elle a repris un moment de la vie de quelqu'un",
    "world.settle": "Conclure ses gestes dans le monde", "world.notice": "Remarquer ce qu'on a changé chez elle",
    "shares.retention": "Retirer les fichiers envoyés trop anciens", "imaging.draw": "Dessiner",
    "attachments.study": "Lire de près les pièces reçues", "attachments.index": "Indexer les pièces reçues",
    "attachments.retention": "Retirer les pièces reçues trop anciennes ou de trop",
    "mcp.expire": "Refuser les accords restés sans réponse",
    "forge.calls_expire": "Refuser les appels d'apps restés sans accord",
    "wakeup.expire": "Laisser tomber les réveils par API restés trop longtemps en attente",
    "teams.triage": "Trier les messages Teams reçus",
    "teams.expire": "Laisser tomber les réponses Teams restées sans accord ou sans envoi",
    "phone.expire": "Laisser tomber les réponses proposées sur le téléphone restées sans geste",
    "memory.relayed": "Retenir ce que le téléphone lui montre (les messages reçus)",
    "identity.expire": "Oublier les inconnues de passage restées silencieuses",
}

#: Les événements des facultés : ce qui s'est passé (ceux du noyau et du moteur sont nommés par la console).
EVENT_LABELS: dict[str, str] = {
    "presence.connected": "Connexion", "presence.disconnected": "Déconnexion",
    "presence.read": "Lu jusqu'à un message (ce que dit son application)",
    "presence.composing": "Commence ou cesse d'écrire un message (ce que dit son application)",
    "place.moved": "Elle s'est déplacée dans sa chambre",
    "world.authored": "Le monde édité", "world.described": "Un élément du monde décrit",
    "world.intended": "Un geste commencé dans le monde", "world.ended": "Un geste terminé dans le monde",
    "world.changed": "Le monde a changé", "world.requested": "Une demande dans le monde",
    "world.answered": "Une réponse à une demande", "world.gestured": "Un geste vers quelqu'un",
    "world.joined": "Quelqu'un est entré dans le monde", "world.left": "Quelqu'un est sorti du monde",
    "world.noticed": "Quelque chose de remarqué dans le monde",
    "identity.claimed": "Un nom revendiqué", "identity.evidence": "Une preuve d'identité",
    "identity.linked": "Un moyen de communication relié", "identity.registered": "Un compte enregistré",
    "identity.name_bound": "Un nom relié à une personne (« celle dont on lui a parlé »)",
    "identity.name_dismissed": "Un nom écarté pour une personne (« ce n'est pas elle »)",
    "identity.expired": "Une inconnue de passage oubliée (silencieuse depuis longtemps)",
    "transcript.compacted": "Un fil replié en résumé",
    "transcript.judged": "Une de ses réponses jugée par son opératrice",
    "memory.believed": "Une croyance retenue", "memory.consolidated": "Une relecture de la mémoire",
    "memory.night_sorted": "La mémoire triée la nuit", "memory.promise_noticed": "Une promesse remarquée",
    "memory.promise_resolved": "Une promesse tenue ou abandonnée", "memory.reinforced": "Un souvenir renforcé",
    "memory.remembered": "Un souvenir retenu", "memory.extraction_deferred": "Passage à reprendre",
    "memory.life_recalled": "Situations remises en mémoire",
    "social.relations_recalled": "Relations remises en mémoire",
    "memory.attested": "Un témoignage de plus sur une croyance (ou une discrétion demandée)",
    "memory.joined": "Des croyances dites par plusieurs, réunies la nuit",
    "memory.confronted": "Deux témoins confrontés la nuit (l'un l'emporte, ou elle doute)",
    "memory.resolved": "Comment un moment a tourné (a eu lieu, annulé, reporté, ou on ne le saura pas)",
    "attention.anticipated": "Un moment qui approche, attendu avec espoir ou inquiétude",
    "attention.envied": "Jalouse : quelqu'un dont elle attend la réponse écrit aux autres",
    "memory.reread": "Ses lectures relues la nuit",
    "memory.delicate": "Un sujet délicat : gardé pour confidence",
    "rss.read": "Un article lu", "mcp.consulted": "Une page consultée en travaillant",
    "transcript.summary_reset": "Le résumé d'un salon à refaire (un secret y était repris)",
    "body.fell_asleep": "Endormie", "body.woke": "Réveillée", "needs.felt": "Un besoin ressenti",
    "others.read": "Ce qu'elle devine de quelqu'un",
    "others.farewell": "Un au revoir (la conversation se clôt)",
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
    "rss.noticed": "Un article remarqué", "rss.thought_of": "Un article qui lui a fait penser à quelqu'un",
    "camera.seen": "Ce que la caméra a vu",
    "mcp.status": "L'état de ses serveurs extérieurs", "mcp.answered": "Ce qu'un service extérieur a rendu",
    "forge.answered": "Ce qu'une app a rendu après un accord", "projects.access_set": "Les accès d'un projet réglés",
    "forge.access_set": "Les accès d'une app sans projet réglés",
    "projects.steer_asked": "Une demande de pilotage d'un projet, sur ton accord",
    "forge.emitted": "Une app a signalé", "forge.handled": "Une app a traité un événement",
    "forge.signaled": "Une app l'a interpellée", "forge.switched": "Une app allumée ou éteinte",
    "forge.queued": "Un signal d'app mis en file", "forge.judged": "Une file d'app lue",
    "forge.ticked": "Une app a tourné", "forge.written": "Une app écrite", "sensors.sensed": "Un appareil a signalé",
    "location.located": "Son téléphone a dit où était la personne",
    "location.cleared": "La personne ne partage plus où elle est",
    "memory.event_noted": "Un événement de la vie de quelqu'un, noté", "body.roused": "Réveillée par un message",
    "body.waited": "Un message attend son réveil", "attention.touched": "Une pensée effleurée par un message",
    "self.woke_with": "Ce qu'elle emporte de sa nuit", "self.touched": "Touchée par ce qu'on lui a dit",
    "self.interest_born": "Un intérêt est né", "self.reflected": "Elle a réfléchi à ce qui la passionne",
    "projects.network_queued": "Une commande réseau mise en file (après l'exécution)",
    "projects.answered": "Une réponse à sa demande d'aide sur un projet",
    "social.one_sided": "C'est presque toujours elle qui écrit",
    "social.bond_shifted": "Un lien qui a changé (elle l'a remarqué)",
    "social.bond_noted": "Un lien relevé sans le vivre (mise en service, proximité fixée, propriétaire)",
    "needs.reunited": "Une amie revenue après un moment creux",
    "memory.moment_followed": "Un moment de la vie de quelqu'un, repris",
    "memory.situation_ended": "Une situation de la vie de quelqu'un, finie",
    "shares.shared": "Un fichier envoyé", "shares.expired": "Des fichiers envoyés retirés",
    "attachments.kept": "Une pièce reçue, lue de près",
    "attachments.linked": "Une pièce reçue reliée (ou déliée) à ce qu'elle sait",
    "attachments.expired": "Des pièces reçues retirées",
    "imaging.requested": "Un dessin demandé", "imaging.drawn": "Un dessin prêt",
    "imaging.failed": "Un dessin qui n'a pas pu se faire",
    "wakeup.called": "Un réveil par API reçu", "wakeup.reported": "Le compte rendu d'un réveil par API",
    "wakeup.expired": "Un réveil par API expiré sans avoir été traité", "wakeup.cancelled": "Un réveil par API annulé",
    "teams.noticed": "Un message Teams remarqué", "teams.sent": "Une réponse Teams partie",
    "teams.draft_asked": "Une réponse Teams demandée", "teams.received": "Des messages Teams reçus de l'extension",
    "teams.settled": "Une réponse Teams posée, partie ou laissée",
    "phone.received": "Un message montré par le téléphone", "phone.drafted": "Une réponse préparée pour le téléphone",
    "phone.settled": "Une réponse proposée sur le téléphone : partie, laissée ou expirée",
    "memory.relayed_read": "Des messages du téléphone relus",
}

#: Les familles d'outils (leurs lots) qui ne se nomment pas comme leur faculté ; « préfixe.* » : les lots qu'une
#: source ajoute (un par serveur MCP branché, un par app), nommés par ce qui suit le préfixe.
BUNDLE_LABELS: dict[str, str] = {
    "attention": "Ses pensées", "self": "Son journal", "social": "Qui lui parle", "workshop": "L'atelier d'un projet",
    "forge": "La Forge (écrire ses apps)", "forge_signals": "Ce que ses apps lui signalent",
    "mcp.*": "Service « {} »", "forge_apps.*": "Son app « {} »",
}

#: Tout ce que la console nomme en français, d'un bloc.
LABELS = Labels(faculties=FACULTY_LABELS, sections=SECTION_LABELS, reasons=REASON_LABELS, vetoes=VETO_LABELS,
                processes=PROCESS_LABELS, events=EVENT_LABELS, bundles=BUNDLE_LABELS)
