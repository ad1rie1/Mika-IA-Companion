"""La carte de la console, décidée par la composition (comme la liste des
facultés) : ses groupes, ses destinations, et les onglets que la console
fournit elle-même. Les facultés, elles, y rangent leurs vues par ``section``.

La carte répond à des questions d'opérateur, dans cet ordre : que dois-je
faire (tableau de bord) ; comment va-t-elle (Elle) ; qui connaît-elle (Ses
relations) ; que fait-elle et pourquoi (Son activité) ; par où perçoit-elle et
agit-elle (Ses canaux) ; que décide-t-on, la machine tient-elle
(Exploitation). ``docs/console-carte.md`` détaille chaque menu.
"""

from __future__ import annotations

from mika.inspector.catalog import Destination, NavGroup

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
                    builtin=("decisions.maintenant", "decisions.en_cours", "decisions.selections",
                             "decisions.episodes", "decisions.echeances"),
                    order=("maintenant", "en_cours", "initiatives", "selections", "episodes", "echeances")),
        Destination("buts", "Buts", "➤", "Ses rappels, explorations et projets : où ils en sont.",
                    subjects=("goal",)),
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
    ("Action", ("agency", "goals")),
    ("Canaux", ("email", "rss", "camera", "forge")),
    ("Noyau", ("kernel",)),
)
FACULTY_LABELS: dict[str, str] = {
    "affect": "Humeur et postures", "needs": "Besoins", "body": "Corps et sommeil", "self": "Estime et récit",
    "attention": "Attention et pensées", "memory": "Mémoire", "transcript": "Fil des conversations",
    "social": "Liens", "others": "Ce qu'elle devine des autres", "identity": "Identités",
    "agency": "Initiatives", "goals": "Buts", "email": "Courrier", "rss": "Flux RSS", "camera": "Caméra",
    "forge": "Moteur de la Forge", "kernel": "Noyau",
}
