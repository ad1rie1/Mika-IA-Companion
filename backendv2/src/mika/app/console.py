"""La carte de la console, décidée par la composition (comme la liste des
facultés) : ses groupes, ses destinations, et les onglets que la console
fournit elle-même. Les facultés, elles, y rangent leurs vues par ``section``.

La carte répond à des questions d'opérateur, dans cet ordre : que dois-je
faire (l'accueil, dessiné à la main hors de la carte : ``app/handmade/home.py``, qui lit les onglets ``accueil.*``) ;
comment va-t-elle (sa rubrique, à son nom) ; qui connaît-elle (Relations & échanges) ; que fait-elle et pourquoi
(Activité : ses décisions, ses buts, ses projets ; Outils ; À valider) ; par où perçoit-elle et agit-elle
(Connexions extérieures) ; que décide-t-on, la machine tient-elle (Réglages, Système). Le menu visible est
``app/console_menu.py`` : chaque groupe ci-dessous porte le nom de la rubrique où ses destinations s'y rangent (le
groupe ne se montre que si une destination n'avait pas de lien au menu), et une destination porte le nom de son lien
au menu (ADR 0202 : le menu fait foi, le fil d'Ariane et le titre de l'onglet le reprennent). Les réglages d'un
plugin vivent dans sa destination, derrière sa roue (``gear``, ADR 0173, 0206 : Courrier, Teams, Ses outils, Ses sens,
Réveils par API) : des onglets de la console, que ``app/settings_sections/`` y pose (``SettingsPage.home``).
``docs/console-carte.md`` détaille chaque menu.
"""

from __future__ import annotations

from typing import Any

from mika.app.domains import DOMAINS
from mika.inspector.catalog import Destination, Labels, NavGroup
from mika.inspector.names import OTHER_EFFECTS


def _named(kind: str, frame: dict[str, Any]) -> dict[str, Any]:
    """Les libellés d'une sorte (``Labels.<kind>``) : ceux du cadre, puis ceux que chaque domaine dit dans sa fiche
    (``Domain.labels``, ADR 0310), dans l'ordre des fiches. Un nom dit deux fois est refusé : l'un des deux mentirait."""
    out = dict(frame)
    for domain in DOMAINS:
        for key, said in domain.labels.get(kind, {}).items():
            if key in out:
                raise ValueError(f"le libellé « {key} » ({kind}) est dit deux fois : la fiche de « {domain.name} » "
                                 "redit un nom du cadre ou d'un autre domaine")
            out[key] = said
    return out


def _destination(domain: str) -> Destination:
    """La destination d'un domaine qui a sa fiche (``Domain.destination``, ADR 0310). La fiche dit ce qu'elle est ;
    cette carte dit où elle est rangée : l'ordre du menu se décide ici."""
    found = next((d.destination for d in DOMAINS if d.name == domain), None)
    if found is None:
        raise ValueError(f"le domaine « {domain} » n'a pas de destination dans sa fiche")
    return found


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
        # un fichier qu'elle a envoyé se lit sur la fiche de sa personne (onglet Fichiers) : sa fiche vit ici
        Destination("personnes", "Personnes", "Les gens qu'elle connaît et ce qui les lie.",
                    subjects=("person", "partage", "contact"), lead="Vue d'ensemble"),
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
        Destination("buts", "Buts et rappels", "Ce qu'elle se propose de faire ensuite : ses rappels et ses "
                    "explorations, où ils en sont.", subjects=("goal",)),
        Destination("projets", "Projets", "Ses projets : des espaces de travail qu'on pilote — objectifs, "
                    "exécutions, décisions techniques, fichiers, dépôt git, mode et outils.",
                    subjects=("project",)),
    )),
    NavGroup("Outils", (
        Destination("outils", "Ses outils", "Ce qu'elle peut faire et avec qui, ses propres outils et leurs droits, ce "
                    "qui lui vient d'ailleurs (les services branchés, ses apps), et ce que tu prêtes à un agent.",
                    # la connexion des services branchés (des serveurs MCP) : en haut à droite (ADR 0206)
                    builtin=("outils.tous", "outils.expose", "outils.parametres"),
                    order=("tous", "serveurs", "expose"), subjects=("serveur",), gear=("parametres",)),
    )),
    NavGroup("À valider", (
        # une seule file : ce qui attend une décision, quelle qu'en soit la sorte ; ses onglets (courriers, Teams,
        # identités, rapprochements) sont déclarés par la composition (``app/handmade/waiting.py``, ADR 0177)
        Destination("approbations", "À valider", "Ce qui attend ta décision — ce qu'elle voudrait faire sortir de "
                    "la machine, les identités à confirmer, les rapprochements — et ce qui en a "
                    "été décidé.",
                    builtin=("approbations.en_attente", "approbations.historique"), dynamic=True,
                    order=("en_attente", "courriers", "teams", "identites", "rapprochements", "historique")),
    )),
    NavGroup("Relations & échanges", (
        Destination("courrier", "Courrier", "Lire les messages, répondre et suivre les brouillons de chaque boîte.",
                    subjects=("mail", "brouillon", "compte"), context=("compte",), automatic_actions=False,
                    # ses paramètres (ses boîtes, son relevé, ce qu'elle en dit) : en haut à droite (ADR 0173)
                    builtin=("courrier.parametres",), gear=("parametres",)),
        Destination("teams", "Teams", "Les conversations Teams que l'extension lui apporte, et les réponses "
                    "qu'elle prépare à ta place : posées, à accepter, parties.",
                    subjects=("conversation_teams", "reponse_teams"),
                    # ses paramètres (« Actif », ses comptes) : en haut à droite, comme le courrier (ADR 0206)
                    builtin=("teams.parametres",), gear=("parametres",)),
        # les agendas de chacun (ADR 0309, lot 5) : tous dans une même vue, par personne ; la fiche d'un agenda vit ici ;
        # ses paramètres (les applications Google et Microsoft, la synchro, les rappels) : en haut à droite
        Destination("agendas", "Agendas", "Tous les agendas du système, par personne : leurs comptes, ce qu'elle en "
                    "fait, et le sien.", subjects=("agenda",), builtin=("agendas.parametres",), gear=("parametres",),
                    order=("tous", "comptes", "fait", "mika")),
    )),
    NavGroup("Connexions extérieures", (
        _destination("senses"),  # ses sens
        _destination("wakeup"),  # les réveils par API
    )),
    NavGroup("Outils", (
        _destination("forge"),  # les apps forgées
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
    ("Action", ("agency", "runtime", "goals", "projects", "shares", "imaging", "world")),
    ("Plugins", ("email", "teams", "phone", "rss", "web", "camera", "forge", "wakeup")),
    ("Noyau", ("kernel",)),
)
FACULTY_LABELS: dict[str, str] = _named("faculties", {
    "affect": "Humeur et postures", "needs": "Besoins", "body": "Corps et sommeil", "self": "Estime et récit",
    "attention": "Attention et pensées", "memory": "Mémoire", "transcript": "Fil des conversations",
    "social": "Liens", "others": "Ce qu'elle devine des autres", "identity": "Identités",
    "agency": "Initiatives", "goals": "Buts", "projects": "Projets", "email": "Courrier",
    "kernel": "Noyau", "presence": "Présence", "expression": "Expression",
    "runtime": "Moteur", "place": "Où elle est (sa chambre)",
    "world": "Son monde et son corps", "shares": "Fichiers envoyés", "attachments": "Pièces reçues",
    "imaging": "Dessins", "location": "Localisation",
    "mcp": "Outils extérieurs", "web": "Recherche web", "teams": "Teams",
    "trips": "Carte et voyages", "agenda": "Agenda",
})

#: Les sections du prompt, nommées par ce qu'elles lui montrent (Pourquoi a-t-elle dit ça ?, Prompt).
SECTION_LABELS: dict[str, str] = _named("sections", {
    "who": "Qui elle a en face", "history": "Le fil de la conversation", "memories": "Ses souvenirs rappelés",
    "shared_memories": "Ce qu'ils ont vécu ensemble", "past_exchanges": "Des échanges passés",
    "promises": "Ce qu'elle a promis", "rhythm": "Son rythme (heure, énergie)",
    "mood": "Son humeur", "stance": "Sa posture envers la personne",
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
    # ADR 0033, 0034, 0036
    "life": "Ce qui se passe dans la vie de la personne",
    "ahead": "Ce qui vient : le monde, et ce qu'elle vivra à travers quelqu'un",
    "learned": "Ce qu'elle a appris en lisant", "acquainted": "Les gens qu'on nomme (qu'elle connaît dans son cercle)", "veiled": "Ce qu'elle peut raconter sans nommer personne", "matter": "Ce dont elle pourrait parler",
    "noticed": "Ce qu'elle a remarqué", "habits": "Ce qu'elle s'entend répéter", "answer": "Sa réponse (le dernier rappel)",
    "mail_mention": "Le mail important qu'elle annonce", "step_origin": "Ce qui a fait naître le but",
    "project_network": "Ce que le réseau a rendu",
    "project_answer": "La réponse à sa demande d'aide (un projet)",
    # ADR 0047
    "greeting_tone": "Ses petits mots pour saluer (sa persona)",
    # ADR 0046
    "self_said": "Ce qu'elle a déjà dit d'elle-même", "register": "Ce qui les lie (leur lien)",
    # ADR 0137
    "their_day": "Sa journée (ce qu'elle n'en sait pas encore)",
    # ADR 0140
    "form": "Comment elle écrit ici (les codes de son autrice)",
    # ADR 0062
    "sent_files": "Ce qu'elle lui a déjà envoyé (fichiers)", "dessins": "Ses dessins pour la personne",
    "services": "Ce que ses services extérieurs lui ont rendu",
    # ADR 0255
    "work_services": "Ce que ses services extérieurs ont rendu à son travail (après un accord)",
    # ADR 0257
    "project_links": "Ce que ce projet lit des autres projets",
    # ADR 0265
    "project_stirs": "Ce qui amène cette exécution (ce qui a déclenché son objectif)",
    "project_items": "Le registre du projet (ses tickets, ses listes de suivi)",
    # ADR 0289
    "project_docs": "La documentation de son projet, et celle des projets qu'il lit quand le lien la donne",
    # ADR 0270
    "project_tickets": "Les tickets à traiter (leur étape, ce qui est attendu d'elle), ou le ticket de son objectif",
    "project_pull": "La branche où elle travaille, la pull request de son objectif et ses vérifications (ce que "
                    "l'hôte en dit, cité)",
    # ADR 0276
    "review": "Ce qu'une relecture indépendante juge (la demande, le but, l'objectif, son critère, ses jalons)",
    "review_said": "Ce que l'exécution relue a écrit de ses jalons (son dire, cité à une relecture indépendante)",
    "review_diff": "Le diff du commit qu'une relecture indépendante relit (une donnée, citée)",
    "project_review": "Les constats de la relecture qui a rouvert son objectif (le dire d'une autre exécution, "
                      "cité)",
    # ADR 0271
    "project_asks": "Ses demandes aux autres projets (où chacune en est)",
    "step_exchange": "L'échange d'où vient sa réflexion", "step_life": "Ce qui se passe dans la vie de la personne "
    "(sa réflexion)",
    # ADR 0068
    # ADR 0069
    "teams_messages": "Ses messages Teams récents", "teams_drafts": "Ses réponses Teams et ce qu'elles sont devenues",
    "teams_voice": "Comment elle écrit dans Teams (à ta place)",
    "teams_task": "Le message Teams auquel elle prépare une réponse (cité)",
    "teams_ask": "Ce qu'on lui demande d'y répondre (Teams)",
    "crossed": "Elle allait justement lui écrire (leurs messages se sont croisés)",
    # ADR 0309
    "agenda_day": "Sa journée dans ses agendas (aujourd'hui et demain, cité)",
    "agenda_writes": "Ce qu'elle a proposé d'écrire dans ses agendas, et ce que c'est devenu",
    "agenda_reminder": "Le rendez-vous qu'elle rappelle (cité)",
    "agenda_invitation": "L'invitation dont elle prépare la réponse, et ce qui tombe en même temps (cité)",
})

#: Les raisons des preuves de l'arbitre : ce qui la pousse à agir.
REASON_LABELS: dict[str, str] = _named("reasons", {
    "mood_overflow": "Une humeur qui déborde", "need_expression": "Besoin de s'exprimer",
    "need_social": "Envie de compagnie", "check_in": "Prendre des nouvelles", "follow_up": "Demander comment ça s'est passé", "thought": "Une pensée à partager",
    "greeting": "Saluer", "present": "Quelqu'un de présent", "chat": "Envie de bavarder",
    "comfort": "Réconforter", "recontact": "Reprendre contact après un silence", "work": "Avancer sur un but",
    "remind": "Rappeler ce qu'on lui a demandé", "share": "Partager où en est un but",
    "drawing_ready": "Montrer un dessin prêt", "drawing_failed": "Dire qu'un dessin n'a pas pu se faire",
    "service_answered": "Dire ce qu'un service extérieur a rendu",
    "run": "Travailler sur un projet", "project_share": "Partager où en est un projet",
    "mail_mention": "Parler d'un mail reçu", "mail_draft": "Préparer une réponse à un mail",
    "second_thoughts": "Elle s'est ravisée", "project_need": "Demander un coup de main pour un projet", "project_plan": "Dire son plan à qui a demandé un projet",
    "keep_promise": "Tenir une promesse au moment dit", "cheer": "Encourager avant un moment important",
    "celebrate": "Souhaiter ce qui se fête (un anniversaire), le jour même",
    "remembrance": "Faire signe à une proche, le jour où revient la date d'un deuil",
    # ADR 0058
    "rekindle": "Reprendre des nouvelles, longtemps après (une fois)",
    # ADR 0068
    # ADR 0069
    "teams_draft": "Préparer une réponse à un message Teams",
    # ADR 0309
    "agenda_remind": "Rappeler un rendez-vous, au délai que son agenda demande",
    "agenda_prepare": "Préparer la réponse à une invitation",
})

#: Les vetos : ce qui l'empêche d'agir.
VETO_LABELS: dict[str, str] = _named("vetoes", {
    "asleep": "Elle dort", "waking": "Elle vient de se réveiller", "woken_at_night": "Réveillée en pleine nuit",
    "daily_cap": "Budget d'initiatives du jour épuisé",
    "unanswered": "Sa dernière initiative est restée sans réponse", "run_cap": "Assez d'exécutions pour l'heure",
    "step_cap": "Assez de séances de travail pour l'heure",
    "awaiting_reply": "Elle attend sa réponse (elle a écrit en dernier)", "farewell": "Ils viennent de se dire au revoir", "changed_mind": "Elle s'est ravisée", "hesitating": "Elle hésite encore (ses derniers essais ont fini en silence)",
    "composing": "La personne est en train de lui écrire",
    "not_reachable": "La personne n'est pas là, à une heure où elle n'écrit pas d'habitude",
    # ADR 0127
    "held": "Le quota de l'abonnement est réservé à la conversation",
    # ADR 0306
    "busy": "On l'attend, mais ce dont elle a besoin est pris : elle s'y met dès que c'est libre",
    "retry": "On l'attend ; son essai vient d'échouer : elle réessaie dans une minute",
})

#: Les processus de fond : ce qu'ils font.
PROCESS_LABELS: dict[str, str] = _named("processes", {
    "transcript.compact": "Replier les longs fils en résumé", "memory.consolidate": "Retenir (souvenirs, croyances)",
    "memory.calendar": "Se rappeler les dates proches",
    "memory.index": "Indexer la mémoire", "memory.reflect": "Repenser à ce qu'elle sait",
    "memory.lies": "Se souvenir de ses mensonges",
    "memory.night": "Trier la mémoire la nuit", "memory.reread": "Relire ses lectures la nuit",
    "memory.delicate": "Garder pour confidence ce qui touche un sujet délicat",
    "attention.anticipate": "Attendre ce qui approche", "body.sleep": "S'endormir et se réveiller",
    "needs.empty": "Sentir le vide", "attention.watch": "Remarquer et attendre",
    "attention.digest": "Digérer ses pensées la nuit", "self.narrate": "Se raconter",
    # ADR 0139
    "self.character": "Écrire son caractère",
    "self.journal": "Tenir son journal", "self.dream": "Rêver", "self.reflect": "Voir ce qui la passionne", "social.profile": "Comprendre les gens",
    "goals.seed": "Se proposer des buts", "goals.tend": "Suivre ses buts", "projects.tend": "Suivre ses projets",
    "projects.apps": "Réparer les apps de ses projets",
    "projects.views": "Retirer les vues d'atelier qu'un projet n'a plus le droit de lire",
    "projects.stirs": "Juger ce qui déclenche un objectif (un commit d'un projet lu, un signal d'app)",
    "projects.tickets": "Faire naître « Traiter les tickets », et suivre l'objectif né d'un ticket",
    "projects.remote": "Pousser et récupérer les dépôts",
    "projects.pulls": "Proposer la pull request d'un travail conclu, la relire chez l'hôte avec ses vérifications",
    "projects.issues": "Tenir les issues pour le reflet des tickets : ce qui part, et ce que l'hôte en dit",
    "projects.reviews": "Demander la relecture indépendante d'un travail conclu, hors des pull requests",
    "email.poll": "Relever le courrier",
    "email.keep": "Télécharger l'historique du courrier",
    "mcp.watch": "Rejoindre les serveurs d'outils extérieurs",
    "memory.promises": "Tenir ou laisser filer ses promesses", "self.wake": "Se réveiller avec sa nuit",
    "social.reciprocity": "Remarquer qui écrit en premier",
    "social.bonds": "Remarquer qu'un lien a changé",
    "memory.follow": "Remarquer qu'elle a repris un moment de la vie de quelqu'un",
    "world.settle": "Conclure ses gestes dans le monde", "world.notice": "Remarquer ce qu'on a changé chez elle",
    "shares.retention": "Retirer les fichiers envoyés trop anciens", "imaging.draw": "Dessiner",
    "attachments.study": "Lire de près les pièces reçues", "attachments.index": "Indexer les pièces reçues",
    "attachments.retention": "Retirer les pièces reçues trop anciennes ou de trop",
    "mcp.expire": "Refuser les accords restés sans réponse",
    "teams.triage": "Trier les messages Teams reçus",
    "teams.images": "Regarder les images des messages Teams",
    "agenda.sync": "Relire les agendas branchés (Google, Outlook, CalDAV, abonnements)",
    "agenda.watch": "Voir venir les rappels et les invitations des agendas, laisser tomber ce qui n'a plus lieu d'être",
    "teams.expire": "Laisser tomber les réponses Teams restées sans accord ou sans envoi",
    "teams.answered": "Refuser ses réponses Teams auxquelles on a répondu autrement dans la discussion",
    "memory.relayed": "Retenir ce que le téléphone lui montre (les messages reçus)",
    "identity.expire": "Oublier les inconnues de passage restées silencieuses",
})

#: Les événements des facultés : ce qui s'est passé (ceux du noyau et du moteur sont nommés par la console).
EVENT_LABELS: dict[str, str] = _named("events", {
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
    "transcript.strand_set": "Un fil de travail réglé (titre, description, archivé)",
    "transcript.effort_set": "L'effort de réflexion forcé pour une conversation ou un fil de travail",
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
    "memory.retracted": "Un souvenir ou une croyance démenti par l'opératrice",
    "attention.anticipated": "Un moment qui approche, attendu avec espoir ou inquiétude",
    "attention.envied": "Jalouse : quelqu'un dont elle attend la réponse écrit aux autres",
    "memory.reread": "Ses lectures relues la nuit",
    "memory.delicate": "Un sujet délicat : gardé pour confidence",
    "mcp.consulted": "Une page consultée en travaillant",
    "transcript.summary_reset": "Le résumé d'un salon à refaire (un secret y était repris)",
    "body.fell_asleep": "Endormie", "body.woke": "Réveillée", "needs.felt": "Un besoin ressenti",
    "others.read": "Ce qu'elle devine de quelqu'un",
    "others.farewell": "Un au revoir (la conversation se clôt)",
    "attention.digested": "Une pensée digérée", "attention.dwelt": "Une pensée ressassée",
    "attention.expectation_met": "Une attente comblée", "attention.expectation_missed": "Une attente déçue",
    "attention.noticed": "Quelque chose de remarqué", "attention.thought_born": "Une pensée née",
    "self.dreamt": "Un rêve", "self.journaled": "Son journal", "self.narrated": "Son récit de soi",
    "self.character_written": "Son caractère, écrit",
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
    "projects.pull_seen": "Ce que l'hôte dit d'une pull request (ouverte, fusionnée, fermée, changements demandés)",
    "projects.checks_seen": "Ce que l'hôte dit des vérifications du commit d'une pull request",
    "projects.base_seen": "La base d'un atelier, relue après une récupération (ce qu'un projet lecteur en voit)",
    "projects.merge_asked": "Une personne demande la fusion d'une pull request, au commit qu'elle a lu",
    "projects.merge_answered": "Ce que l'hôte a répondu à une fusion demandée (fusionnée, ou pourquoi non)",
    "projects.decision_revised": "Les textes d'une décision technique modifiés par une personne",
    "projects.pull_write_asked": "Une personne écrit chez l'hôte sur une pull request (son titre, son texte, un "
                                 "commentaire)",
    "projects.pull_write_answered": "Ce que l'hôte a répondu à ce qu'une personne a écrit sur une pull request",
    "projects.issue_asked": "La publication d'un ticket ou d'une note chez l'hôte demandée",
    "projects.review_asked": "Une relecture indépendante demandée pour le commit d'un objectif",
    "projects.reviewed": "Le verdict d'une relecture indépendante (bon, ou ses constats)",
    "projects.restored": "Un projet restauré", "projects.resumed": "Un projet repris",
    "projects.run_reported": "Une exécution rendue",
    "email.draft_asked": "Une réponse à un mail demandée", "email.noticed": "Un mail remarqué",
    "email.poll_asked": "Une relève demandée", "email.read": "Un mail lu", "email.sent": "Un mail envoyé",
    "mcp.status": "L'état de ses serveurs extérieurs", "mcp.answered": "Ce qu'un service extérieur a rendu",
    "projects.access_set": "Les accès d'un projet réglés",
    "projects.steer_asked": "Une demande de pilotage d'un projet, sur ton accord",
    "location.located": "Son téléphone a dit où était la personne",
    "location.cleared": "La personne ne partage plus où elle est",
    "trips.created": "Un voyage préparé", "trips.changed": "Un voyage modifié",
    "trips.stop_added": "Un arrêt ajouté à un voyage", "trips.stop_moved": "Un arrêt de voyage déplacé",
    "trips.stop_noted": "Un arrêt de voyage noté", "trips.stop_removed": "Un arrêt retiré d'un voyage",
    "trips.removed": "Un voyage supprimé", "trips.looked": "Elle a regardé la carte (des lieux, un trajet)",
    "trips.shown": "Elle a montré une carte dans la conversation",
    "agenda.written": "Ce qu'elle a proposé d'écrire dans un agenda est fait, ou a raté",
    "agenda.reminder_due": "Un rendez-vous à rappeler", "agenda.reminder_dropped": "Un rappel tombé (le rendez-vous a "
    "bougé, est parti, ou son agenda ne le demande plus)",
    "agenda.invitation_noticed": "Une invitation dont elle prépare la réponse",
    "agenda.invitation_settled": "Une invitation qui n'attend plus (répondue, partie, commencée)",
    "agenda.sync_asked": "« Synchroniser maintenant » demandé pour un agenda branché",
    "memory.event_noted": "Un événement de la vie de quelqu'un, noté", "body.roused": "Réveillée par un message",
    "body.waited": "Un message attend son réveil", "attention.touched": "Une pensée effleurée par un message",
    "self.woke_with": "Ce qu'elle emporte de sa nuit", "self.touched": "Touchée par ce qu'on lui a dit",
    "self.interest_born": "Un intérêt est né", "self.reflected": "Elle a réfléchi à ce qui la passionne",
    "projects.network_queued": "Une commande réseau mise en file (après l'exécution)",
    "projects.answered": "Une réponse à sa demande d'aide sur un projet",
    "projects.plan_proposed": "Son plan pour un projet (écrit, ou revu)",
    "projects.plan_answered": "Une réponse à son plan (validé, ou à revoir)",
    "projects.links_set": "Ce qu'un projet lit des autres projets, réglé",
    "projects.stirred": "Ce qui vient d'arriver a déclenché des objectifs (ou aucun)",
    "projects.list_set": "Une liste de suivi créée ou réglée (un projet)",
    "projects.item_added": "Un élément ajouté à une liste (un ticket ouvert)",
    "projects.item_changed": "Un élément d'une liste changé (un ticket accepté, fermé)",
    "projects.item_noted": "Une note dans le fil d'un élément",
    # sa documentation (ADR 0289), un espace à part de son dépôt
    "projects.doc_written": "Une version de plus d'une page de la documentation d'un projet",
    "projects.doc_moved": "Une page de documentation renommée ou déplacée",
    "projects.doc_removed": "Une page de documentation supprimée, avec ses versions",
    "projects.doc_image_added": "Une image de plus dans la documentation d'un projet",
    "projects.doc_image_removed": "Une image retirée de la documentation d'un projet",
    "projects.milestone_added": "Un jalon posé sur un objectif",
    "projects.milestone_changed": "Un jalon révisé, dit prêt, refusé, atteint ou retiré",
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
    "teams.noticed": "Un message Teams remarqué", "teams.sent": "Une réponse Teams partie",
    "teams.draft_asked": "Une réponse Teams demandée", "teams.received": "Des messages Teams reçus de l'extension",
    "teams.settled": "Une réponse Teams posée, partie ou laissée",
    "teams.written": "Un message Teams écrit depuis le web, en file pour l'extension",
    "teams.images": "Une image d'un message Teams reçue de l'extension",
    "teams.image_seen": "Une image d'un message Teams regardée",
    "memory.relayed_read": "Des messages du téléphone relus, ou remis à la file des reprises",
})

#: Ce que la file de sortie fait partir, effet par effet (« propriétaire:type », la clé de ses lignes) : sa famille
#: (``EFFECT_FAMILIES``), son nom, ce que c'est. Système › File de sortie les range par famille ; sa vue, la page
#: dessinée et la page d'un événement disent leur nom (``Names.effect``). Un test d'architecture veut un nom pour chaque
#: effet du registre composé.
EFFECT_LABELS: dict[str, tuple[str, str, str]] = _named("effects", {
    "expression:episode.utterance": ("dit", "Ses messages",
                                     "ce qu'elle répond ou lance, livré aux écrans et au téléphone de la personne"),
    "runtime:episode.ended": ("dit", "Une réponse qui ne viendra pas",
                              "les écrans apprennent qu'aucune réponse ne viendra (une panne, un silence choisi)"),
    "body:body.fell_asleep": ("montre", "Elle s'endort", "ses écrans la montrent se coucher"),
    "body:body.woke": ("montre", "Elle se réveille", "ses écrans la montrent se lever"),
    "body:body.roused": ("montre", "On la réveille", "un réveil par API la tire du sommeil"),
    "world:world.intended": ("montre", "Un geste commence", "dans son monde : elle va quelque part, prend un objet"),
    "world:episode.started": ("montre", "Elle se met au travail", "son monde la montre occupée pendant qu'elle travaille"),
    "world:world.ended": ("montre", "Un geste s'achève", "son monde montre comment il a fini"),
    "world:world.changed": ("montre", "Ce qui l'occupe change", "ses écrans redessinent son monde"),
    "world:world.authored": ("montre", "Son monde, réécrit", "une opératrice l'a édité : les écrans le redessinent"),
    "runtime:effect.proposed": ("agit", "Une action, tout de suite",
                                "une action qui ne demande pas d'accord : elle part dès qu'elle est décidée"),
    "runtime:effect.resolved": ("agit", "Une action que tu as autorisée",
                                "elle part après ton accord : un mail, une réponse Teams, un git push…"),
    "email:effect.executed": ("agit", "Un mail parti", "elle apprend qu'il est parti, retouché ou non"),
    "teams:teams.settled": ("agit", "Une réponse Teams partie", "elle apprend qu'elle est partie, retouchée ou non"),
    "mcp:effect.executed": ("agit", "Ce qu'un service a rendu", "le résultat d'un appel à un service branché"),
    "agenda:effect.executed": ("agit", "Une écriture dans un agenda",
                               "elle apprend ce qu'est devenu ce qu'elle y a ajouté, modifié, supprimé ou répondu"),
    "projects:effect.executed": ("agit", "Un pilotage de projet accepté",
                                 "la demande de quelqu'un sur un projet s'écrit, à son nom, après ton accord"),
    "shares:shares.expired": ("range", "Un fichier envoyé expire", "ses octets sont effacés"),
    "attachments:attachments.expired": ("range", "Une pièce reçue expire", "ses octets sont effacés"),
    # le ménage des vues d'atelier (ADR 0260) : le même geste, relu sur l'état courant, après quatre événements
    "projects:projects.links_set": ("range", "Ce que lit un projet change",
                                    "les vues d'atelier qu'aucun lien n'ouvre plus sont supprimées"),
    "projects:projects.access_set": ("range", "Les accès d'un projet changent",
                                     "les vues de son atelier que ses lignes ne donnent plus sont supprimées"),
    "projects:projects.archived": ("range", "Un projet est archivé",
                                   "les vues qu'il avait, et celles que d'autres avaient de lui, sont supprimées"),
    "projects:projects.reframed": ("range", "Un projet change de propriétaire",
                                   "les vues d'atelier que ce changement ferme sont supprimées"),
    # la copie de commit qu'une relecture indépendante lisait (ADR 0277) : effacée à la fin de son exécution
    "projects:episode.ended": ("range", "Une relecture de projet se termine",
                               "la copie du commit qu'elle relisait est effacée"),
    # la fusion d'une pull request (ADR 0288) : le geste d'une personne, jamais le sien
    # une image retirée de la documentation d'un projet (ADR 0289)
    "projects:projects.doc_image_removed": ("range", "Une image de documentation retirée",
                                            "ses octets sont effacés"),
    # un ajout que l'espace n'a pas gardé (un nom pris au même instant, une borne atteinte) ne laisse pas ses octets
    "projects:projects.doc_image_added": ("range", "Une image de documentation ajoutée",
                                          "si l'espace ne l'a pas gardée, ses octets sont effacés"),
    "projects:projects.merge_asked": ("agit", "Une fusion demandée par une personne",
                                      "la pull request est fusionnée chez l'hôte, au commit que la personne a lu"),
    "projects:projects.pull_write_asked": ("agit", "Ce qu'une personne écrit sur une pull request",
                                           "son titre, son texte ou un commentaire signé partent chez l'hôte"),
})
#: Les familles des effets, dans l'ordre de la page ; un effet sans libellé se range avec le reste
#: (``names.OTHER_EFFECTS``).
EFFECT_FAMILIES: tuple[tuple[str, str], ...] = (
    ("dit", "Ce qu'elle dit"), ("montre", "Ce que montrent ses écrans"), ("agit", "Ce qu'elle fait au dehors"),
    ("range", "Le ménage"), (OTHER_EFFECTS, "Le reste"))

#: Les familles d'outils (leurs lots) qui ne se nomment pas comme leur faculté ; « préfixe.* » : les lots qu'une
#: source ajoute (un par serveur MCP branché, un par app), nommés par ce qui suit le préfixe.
BUNDLE_LABELS: dict[str, str] = _named("bundles", {
    "attention": "Ses pensées", "self": "Son journal", "social": "Qui lui parle", "workshop": "L'atelier d'un projet",
    "project_review": "Relire le travail d'un projet",
    "mcp.*": "Service « {} »",
})

#: Le nom court de chaque capacité : ce qu'une ligne ou une puce de « À valider » et l'historique en disent, sans couper
#: sa phrase. Celle-ci reste sa description, au survol et dans l'en-tête de la demande ouverte.
CAPABILITY_LABELS: dict[str, str] = _named("capabilities", {
    "email.send": "Mail", "teams.send": "Réponse Teams",
    "mcp.call": "Outil extérieur",
    "projects.networked": "Commande réseau", "projects.push": "Push git", "projects.pull": "Pull git",
    "projects.pull_request": "Pull request",
    "projects.issue": "Issue publiée", "projects.issue_state": "État d'une issue",
    "projects.issue_note": "Note publiée",
    "projects.steer": "Pilotage de projet",
    "agenda.write": "Agenda",
})

#: Les enrichisseurs, nommés par ce qu'ils rassemblent pour le prompt avant qu'il s'écrive (l'onglet Prompt d'un
#: épisode, « enrichissements »).
ENRICHER_LABELS: dict[str, str] = _named("enrichers", {
    "thread": "Le fil de la conversation", "recall": "Ses souvenirs rappelés",
    "their_last_words": "Les derniers messages de la personne", "last_heard": "Le message auquel elle répond",
    "own_words": "Ses derniers messages", "own_openings": "Ses dernières entrées en matière",
    "profile_text": "Ce qu'elle sait de la personne", "between_us": "Ce qui n'est qu'entre elle et la personne",
    "narrative": "Qui elle est devenue (récit de soi)", "self_changes": "Ses changements d'avis récents",
    "passions": "Ses intérêts vécus", "night": "Sa nuit (son fil d'hier, son rêve)",
    "thoughts": "Ce qui lui trotte dans la tête", "matter": "Ce dont elle pourrait parler",
    "learned": "Ce qu'elle a appris en lisant", "goals": "Ses buts en cours",
    "goals_context": "D'où vient le but, et la vie de la personne", "projects": "Ses projets",
    "projects_tree": "L'arbre de l'atelier d'un projet", "projects_apps": "Ce qui n'a pas marché pour ses apps",
    "projects_views": "Les vues des ateliers que son projet lit",
    "projects_items": "Le registre de son projet (ce qui a bougé, ses éléments ouverts)",
    "projects_tickets": "Les tickets que regarde son exécution (entre ses mains, ou celui de son objectif)",
    "projects_review": "Ce qu'une relecture indépendante a sous les yeux (ses textes, le diff du commit relu)",
    "projects_asks": "Les demandes de son projet aux projets qu'il lit (où chacune en est)",
    "projects_answer": "La réponse à sa demande d'aide (un projet)", "sent_files": "Les fichiers qu'elle a envoyés",
    "mail": "Son courrier", "teams": "Ses conversations Teams",
    "dessins": "Ses dessins",
    "services": "Ses demandes aux outils extérieurs",
    "work_services": "Ses demandes aux outils extérieurs, faites en travaillant",
    "agenda": "Ses agendas (la journée de la personne, ce qu'elle y a proposé)",
    "agenda_reminder": "Le rendez-vous qu'elle rappelle",
    "agenda_invitation": "L'invitation dont elle prépare la réponse",
})

#: Les ports que des outils attendent (``needs=``) : pourquoi la porte ne les offre pas tant que le port n'est pas prêt
#: (``runtime.tool_offer.ready``), et la page de réglages où il se règle — la fiche d'un outil dit l'un et mène à
#: l'autre. Le port des cartes (``adapters/maps/desk.py``, ``MapsDesk``) ne déclare pas ``configured`` : il n'est pas
#: prêt seulement quand la composition ne le branche pas ; le serveur le branche toujours, et chaque appel dit alors ce
#: qui manque (rien de réglé, un serveur qui ne répond pas).
NEED_LABELS: dict[str, tuple[str, str]] = _named("needs", {
    "imaging": ("aucun fournisseur d'images n'est configuré", "images-fournisseurs"),
    "maps": ("les lieux, les adresses et les itinéraires ne sont pas branchés", "lieux"),
    # le serveur branche toujours la base des rendez-vous (ADR 0309) : seule une composition partielle (un test) ne
    # l'a pas ; sa page de réglages vient avec la console de l'agenda (lot 5), le lien ne paraît qu'une fois là
    "agenda": ("ses calendriers ne sont pas branchés sur ce serveur", "agendas"),
})

#: Tout ce que la console nomme en français, d'un bloc.
LABELS = Labels(faculties=FACULTY_LABELS, sections=SECTION_LABELS, reasons=REASON_LABELS, vetoes=VETO_LABELS,
                processes=PROCESS_LABELS, events=EVENT_LABELS, effects=EFFECT_LABELS, bundles=BUNDLE_LABELS,
                capabilities=CAPABILITY_LABELS, enrichers=ENRICHER_LABELS, needs=NEED_LABELS)
