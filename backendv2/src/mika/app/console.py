"""La carte de la console, décidée par la composition (comme la liste des
facultés) : ses groupes, ses destinations, et les onglets que la console
fournit elle-même. Les facultés, elles, y rangent leurs vues par ``section``.
"""

from __future__ import annotations

from mika.inspector.catalog import Destination, NavGroup

NAVIGATION: tuple[NavGroup, ...] = (
    NavGroup("", (
        Destination("accueil", "Vue d'ensemble", "◉", "Ce qui demande ton attention, et comment elle va.",
                    builtin=("accueil.a_traiter", "accueil.courbes", "accueil.maintenant"), layout="stack"),
    )),
    NavGroup("Elle", (
        Destination("vie", "Humeur et corps", "♡", "Son humeur, ses postures envers chacun, ses besoins, son "
                    "rythme, son estime."),
        Destination("pensees", "Pensées et nuits", "☁", "Ce qui lui trotte dans la tête, ce qu'elle a remarqué, "
                    "ce qu'elle attend, ses nuits."),
        Destination("decisions", "Décisions", "⚖", "Pourquoi elle parle ou se tait : les preuves de l'arbitre, "
                    "ses choix, ses épisodes, ses échéances.",
                    builtin=("decisions.maintenant", "decisions.selections", "decisions.episodes",
                             "decisions.echeances")),
    )),
    NavGroup("Ses liens", (
        Destination("personnes", "Personnes", "☺", "Les gens qu'elle connaît et ce qui les lie."),
        Destination("identites", "Identités", "◎", "Qui parle derrière chaque poignée, et ce que ça ouvre."),
        Destination("fil", "Fil", "✉", "Ce qui a été dit, avec qui, et les questions qui attendent."),
    )),
    NavGroup("Sa mémoire", (
        Destination("memoire", "Mémoire", "❖", "Souvenirs, croyances, promesses, et la relecture qui les "
                    "produit. (La v2 n'extrait ni thèmes ni entités.)"),
    )),
    NavGroup("Son travail", (
        Destination("buts", "Buts", "➤", "Ses rappels, explorations et projets : où ils en sont."),
        Destination("approbations", "Approbations", "✓", "Ce qu'elle voudrait faire hors de la machine.",
                    builtin=("approbations.en_attente",)),
        Destination("apps", "Apps forgées", "⚒", "Les petites apps qu'elle écrit elle-même."),
    )),
    NavGroup("Ses sens", (
        Destination("courrier", "Courrier", "✉", "Ses boîtes aux lettres : leurs dossiers, ce qui arrive, ce qu'elle "
                    "a préparé et qui attend ton accord, ce qui part, avec qui, et ses comptes. Ce que tu écris ici "
                    "part de sa boîte, et elle le sait."),
        Destination("sens", "Sens", "◌", "Flux, caméra, appareils."),
    )),
    NavGroup("Exploitation", (
        Destination("reglages", "Réglages", "⚙", "Ce qu'un opérateur décide : modèles, personnalité, canaux, "
                    "sens, comptes.",
                    builtin=("reglages.modeles", "reglages.personnalite", "reglages.parametres",
                             "reglages.canaux", "reglages.sens", "reglages.comptes",
                             "reglages.journal")),
        Destination("systeme", "Système", "▣", "Santé, processus, coûts, journal, anatomie.",
                    builtin=("systeme.sante", "systeme.appels", "systeme.chronologie", "systeme.etat",
                             "systeme.contributions", "systeme.operations", "systeme.simulations",
                             "systeme.vues")),
    )),
)
