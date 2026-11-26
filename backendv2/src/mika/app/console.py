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

from collections.abc import Mapping, Sequence
from typing import Any

from mika.app.domains import DOMAINS, gathered
from mika.inspector.catalog import Destination, Labels, NavGroup
from mika.inspector.names import OTHER_EFFECTS


def _named(kind: str, frame: dict[str, Any]) -> dict[str, Any]:
    """Les libellés d'une sorte (``Labels.<kind>``) : ceux du cadre, puis ceux que chaque domaine dit dans sa fiche
    (``Domain.labels``, ADR 0310), dans l'ordre des fiches. Un nom dit deux fois est refusé (``gathered``) : l'un des
    deux mentirait. Chaque sorte qu'une fiche dit est lue ici, par son nom
    (``tests/architecture/test_frame_names_no_domain.py``)."""
    return gathered(f"un libellé de la sorte « {kind} »", [
        ("le cadre", frame), *((f"la fiche de « {d.name} »", d.labels.get(kind, {})) for d in DOMAINS)])


def _destination(domain: str) -> Destination:
    """La destination d'un domaine qui a sa fiche (``Domain.destination``, ADR 0310). La fiche dit ce qu'elle est ;
    cette carte dit où elle est rangée : l'ordre du menu se décide ici."""
    found = next((d.destination for d in DOMAINS if d.name == domain), None)
    if found is None:
        raise ValueError(f"le domaine « {domain} » n'a pas de destination dans sa fiche")
    return found


def param_families(names: Sequence[str], family_of: Mapping[str, str],
                   order: Sequence[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Réglages › Paramètres avancés : ses facultés et ses plugins rangés par famille, les familles dans l'ordre de
    ``names``, chacune avec les siens — ceux que ``order`` place, dans son ordre, puis les autres dans l'ordre où leur
    famille est dite (``family_of`` : celles du cadre, puis celles des fiches). Une famille hors de ``names``, un nom de
    ``order`` sans famille ou dit deux fois : ``ValueError``."""
    unknown = sorted(f"{owner} → {family}" for owner, family in family_of.items() if family not in names)
    lacking = [owner for owner in order if owner not in family_of]
    twice = sorted({owner for owner in order if list(order).count(owner) > 1})
    if unknown or lacking or twice:
        raise ValueError("Paramètres avancés : chaque famille dite est une de PARAM_FAMILY_NAMES, chaque nom de "
                         f"PARAM_ORDER a sa famille, une fois — familles inconnues : {unknown}, sans famille : "
                         f"{lacking}, placés deux fois : {twice}")
    rank = {owner: n for n, owner in enumerate(order)}
    placed = sorted(family_of, key=lambda owner: rank.get(owner, len(rank)))  # stable : les autres, dans leur ordre
    return tuple((name, tuple(owner for owner in placed if family_of[owner] == name)) for name in names)


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
        _destination("projects"),  # ses projets
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
        # identités, rapprochements) sont déclarés par la composition et les fiches (``app/handmade/waiting.py``,
        # ADR 0177), et rangés par leur ``QueueTab.order`` après « Tout ce qui attend » ; l'historique vient après
        # tous (``inspector/pages/approvals.py::HISTORY_ORDER``)
        Destination("approbations", "À valider", "Ce qui attend ta décision — ce qu'elle voudrait faire sortir de "
                    "la machine, les identités à confirmer, les rapprochements — et ce qui en a "
                    "été décidé.",
                    builtin=("approbations.en_attente",), dynamic=True),
    )),
    NavGroup("Relations & échanges", (
        _destination("mail"),  # le courrier
        _destination("teams"),  # Teams
        _destination("agenda"),  # les agendas de chacun
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

#: Réglages › Paramètres avancés : les familles où se rangent ses facultés et ses plugins, dans l'ordre de la page
PARAM_FAMILY_NAMES: tuple[str, ...] = ("Émotions", "Esprit", "Relations", "Action", "Plugins", "Noyau")
#: … la famille de chacun, par son nom technique : celle des facultés du cadre, puis celle que la fiche d'un domaine dit
#: des siennes (``labels["parameters"]``) ; sans famille, il tombe dans « Autres », sous son nom technique
#: (``inspector/pages/params.py``)
PARAM_FAMILY: dict[str, str] = _named("parameters", {
    "affect": "Émotions", "needs": "Émotions", "body": "Émotions", "self": "Émotions", "attention": "Esprit",
    "memory": "Esprit", "attachments": "Esprit", "transcript": "Esprit", "social": "Relations",
    "others": "Relations", "identity": "Relations", "agency": "Action", "runtime": "Action",
    "goals": "Action", "shares": "Action", "imaging": "Action", "world": "Action", "kernel": "Noyau",
})
#: … et leur ordre dans leur famille, par leur nom technique : qui n'y est pas vient après, dans l'ordre des fiches
PARAM_ORDER: tuple[str, ...] = (
    "affect", "needs", "body", "self", "attention", "memory", "attachments", "transcript", "social",
    "others", "identity", "agency", "runtime", "goals", "projects", "shares", "imaging", "world", "email",
    "teams", "phone", "rss", "web", "camera", "forge", "wakeup", "kernel",
)
PARAM_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = param_families(PARAM_FAMILY_NAMES, PARAM_FAMILY, PARAM_ORDER)
FACULTY_LABELS: dict[str, str] = _named("faculties", {
    "affect": "Humeur et postures", "needs": "Besoins", "body": "Corps et sommeil", "self": "Estime et récit",
    "attention": "Attention et pensées", "memory": "Mémoire", "transcript": "Fil des conversations",
    "social": "Liens", "others": "Ce qu'elle devine des autres", "identity": "Identités",
    "agency": "Initiatives", "goals": "Buts",
    "kernel": "Noyau", "presence": "Présence", "expression": "Expression",
    "runtime": "Moteur", "place": "Où elle est (sa chambre)",
    "world": "Son monde et son corps", "shares": "Fichiers envoyés", "attachments": "Pièces reçues",
    "imaging": "Dessins",
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
    "subject": "Le sujet de l'initiative", "goals": "Ses buts en cours",
    # ADR 0033, 0034, 0036
    "life": "Ce qui se passe dans la vie de la personne",
    "ahead": "Ce qui vient : le monde, et ce qu'elle vivra à travers quelqu'un",
    "learned": "Ce qu'elle a appris en lisant", "acquainted": "Les gens qu'on nomme (qu'elle connaît dans son cercle)", "veiled": "Ce qu'elle peut raconter sans nommer personne", "matter": "Ce dont elle pourrait parler",
    "noticed": "Ce qu'elle a remarqué", "habits": "Ce qu'elle s'entend répéter", "answer": "Sa réponse (le dernier rappel)",
    "step_origin": "Ce qui a fait naître le but",
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
    # ADR 0271
    "step_exchange": "L'échange d'où vient sa réflexion", "step_life": "Ce qui se passe dans la vie de la personne "
    "(sa réflexion)",
    # ADR 0068
    # ADR 0069
    "crossed": "Elle allait justement lui écrire (leurs messages se sont croisés)",
})

#: Les raisons des preuves de l'arbitre : ce qui la pousse à agir.
REASON_LABELS: dict[str, str] = _named("reasons", {
    "mood_overflow": "Une humeur qui déborde", "need_expression": "Besoin de s'exprimer",
    "need_social": "Envie de compagnie", "check_in": "Prendre des nouvelles", "follow_up": "Demander comment ça s'est passé", "thought": "Une pensée à partager",
    "greeting": "Saluer", "present": "Quelqu'un de présent", "chat": "Envie de bavarder",
    "comfort": "Réconforter", "recontact": "Reprendre contact après un silence", "work": "Avancer sur un but",
    "remind": "Rappeler ce qu'on lui a demandé", "share": "Partager où en est un but",
    "drawing_ready": "Montrer un dessin prêt", "drawing_failed": "Dire qu'un dessin n'a pas pu se faire",
    "second_thoughts": "Elle s'est ravisée",
    "keep_promise": "Tenir une promesse au moment dit", "cheer": "Encourager avant un moment important",
    "celebrate": "Souhaiter ce qui se fête (un anniversaire), le jour même",
    "remembrance": "Faire signe à une proche, le jour où revient la date d'un deuil",
    # ADR 0058
    "rekindle": "Reprendre des nouvelles, longtemps après (une fois)",
    # ADR 0068
})

#: Les vetos : ce qui l'empêche d'agir.
VETO_LABELS: dict[str, str] = _named("vetoes", {
    "asleep": "Elle dort", "waking": "Elle vient de se réveiller", "woken_at_night": "Réveillée en pleine nuit",
    "daily_cap": "Budget d'initiatives du jour épuisé",
    "unanswered": "Sa dernière initiative est restée sans réponse",
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
    "goals.seed": "Se proposer des buts", "goals.tend": "Suivre ses buts",
    "memory.promises": "Tenir ou laisser filer ses promesses", "self.wake": "Se réveiller avec sa nuit",
    "social.reciprocity": "Remarquer qui écrit en premier",
    "social.bonds": "Remarquer qu'un lien a changé",
    "memory.follow": "Remarquer qu'elle a repris un moment de la vie de quelqu'un",
    "world.settle": "Conclure ses gestes dans le monde", "world.notice": "Remarquer ce qu'on a changé chez elle",
    "shares.retention": "Retirer les fichiers envoyés trop anciens", "imaging.draw": "Dessiner",
    "attachments.study": "Lire de près les pièces reçues", "attachments.index": "Indexer les pièces reçues",
    "attachments.retention": "Retirer les pièces reçues trop anciennes ou de trop",
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
    "memory.event_noted": "Un événement de la vie de quelqu'un, noté", "body.roused": "Réveillée par un message",
    "body.waited": "Un message attend son réveil", "attention.touched": "Une pensée effleurée par un message",
    "self.woke_with": "Ce qu'elle emporte de sa nuit", "self.touched": "Touchée par ce qu'on lui a dit",
    "self.interest_born": "Un intérêt est né", "self.reflected": "Elle a réfléchi à ce qui la passionne",
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
    "shares:shares.expired": ("range", "Un fichier envoyé expire", "ses octets sont effacés"),
    "attachments:attachments.expired": ("range", "Une pièce reçue expire", "ses octets sont effacés"),
})
#: Les familles des effets, dans l'ordre de la page ; un effet sans libellé se range avec le reste
#: (``names.OTHER_EFFECTS``).
EFFECT_FAMILIES: tuple[tuple[str, str], ...] = (
    ("dit", "Ce qu'elle dit"), ("montre", "Ce que montrent ses écrans"), ("agit", "Ce qu'elle fait au dehors"),
    ("range", "Le ménage"), (OTHER_EFFECTS, "Le reste"))

#: Les familles d'outils (leurs lots) qui ne se nomment pas comme leur faculté ; « préfixe.* » : les lots qu'une
#: source ajoute (un par serveur MCP branché, un par app), nommés par ce qui suit le préfixe.
BUNDLE_LABELS: dict[str, str] = _named("bundles", {
    "attention": "Ses pensées", "self": "Son journal", "social": "Qui lui parle",
})

#: Ce que fait chaque famille de ses propres outils (un lot), dit à l'opératrice dans Réglages › Droits, à la
#: troisième personne : jamais la phrase de sa voix, écrite pour le modèle (« tes rappels… »). Celles d'un domaine
#: sont dans sa fiche (``labels["about"]``) ; une famille sans description n'en a pas.
FAMILY_ABOUT: dict[str, str] = _named("about", {
    "attachments": "retrouver, rouvrir et relier ce qu'on lui a envoyé (photos, documents, messages vocaux)",
    "attention": "ce qui lui trotte dans la tête en ce moment",
    "goals": "ses rappels et ses explorations ; noter une séance et en rendre compte",
    "identity": "douter d'une identité, défaire un lien",
    "imaging": "dessiner pour la personne (quelques minutes par image), montrer un dessin prêt",
    "memory": "fouiller ses souvenirs et ce qu'elle sait ; dire qu'une promesse est tenue",
    "self": "relire ce qu'elle a écrit dans son journal un jour passé",
    "shares": "envoyer à la personne un texte qu'elle écrit ou un fichier d'un projet ; relire un envoi",
    "social": "relire qui lui écrit et ce qu'elle sait de cette personne, quand son état ne le dit pas déjà",
    "world": "se déplacer et faire des choses dans sa chambre (on la voit le faire)",
})

#: À qui est une demande qui attend un accord, en un mot court, quand le nom de sa faculté ne le dit pas bien (« Forge »
#: plutôt que « Moteur de la Forge ») : ce que dit la fiche de son domaine (``labels["owners"]``).
OWNER_LABELS: dict[str, str] = _named("owners", {})

#: La sorte d'un signal qu'elle remarque, en mots (Ses pensées › Ce qu'elle remarque) : celles d'une app sont libres,
#: elles restent telles quelles. Celles d'un domaine sont dans sa fiche (``labels["signals"]``).
SIGNAL_LABELS: dict[str, str] = _named("signals", {
    # son monde (``faculties/world/notice.py``, ``faculties/world/__init__.py``), ses liens (``faculties/social``)
    # et ce que lui signale un appareil (``app/domains/senses/port.py``, ``sense``)
    "change": "un changement chez elle", "setback": "un contretemps", "gesture": "un geste",
    "bond_shifted": "un lien qui change", "one_sided": "un lien à sens unique", "signal": "un signal",
})

#: Le nom court de chaque capacité : ce qu'une ligne ou une puce de « À valider » et l'historique en disent, sans couper
#: sa phrase. Celle-ci reste sa description, au survol et dans l'en-tête de la demande ouverte.
CAPABILITY_LABELS: dict[str, str] = _named("capabilities", {})

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
    "goals_context": "D'où vient le but, et la vie de la personne",
    "sent_files": "Les fichiers qu'elle a envoyés",
    "dessins": "Ses dessins",
})

#: Les ports que des outils attendent (``needs=``) : pourquoi la porte ne les offre pas tant que le port n'est pas prêt
#: (``runtime.tool_offer.ready``), et la page de réglages où il se règle — la fiche d'un outil dit l'un et mène à
#: l'autre.
NEED_LABELS: dict[str, tuple[str, str]] = _named("needs", {
    "imaging": ("aucun fournisseur d'images n'est configuré", "images-fournisseurs"),
})

#: Tout ce que la console nomme en français, d'un bloc.
LABELS = Labels(faculties=FACULTY_LABELS, sections=SECTION_LABELS, reasons=REASON_LABELS, vetoes=VETO_LABELS,
                processes=PROCESS_LABELS, events=EVENT_LABELS, effects=EFFECT_LABELS, bundles=BUNDLE_LABELS,
                capabilities=CAPABILITY_LABELS, enrichers=ENRICHER_LABELS, needs=NEED_LABELS)
