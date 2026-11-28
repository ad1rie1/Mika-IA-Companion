"""Ce que la console dit d'une pull request (ADR 0274) : l'aperçu que l'opératrice lit dans « À valider » avant son
accord, ce qui l'empêche de partir, le résumé de la proposition et ce que la capacité en rend. Des textes de console,
lus par qui décide — pas des phrases qu'elle lit : les siennes, et le texte de la pull request lui-même, sont dans
``persona/voix.yaml`` (``projects.pull``). ``pulls.py`` et ``atelier.py`` les composent.
"""

from __future__ import annotations

#: la capacité, telle que « À valider » la nomme
DESCRIPTION = ("Pousser la branche de travail d'un objectif et ouvrir sa pull request chez l'hôte du dépôt distant. "
               "Elle ne fusionne rien.")
#: le résumé d'une proposition : des numéros, des branches, le dépôt — rien de plus
SUMMARY = ("Ouvrir une pull request : objectif n° {objective} du projet n° {project}, branche {head} vers {base} de "
           "{url} ({commits} enregistrement(s))")
#: ce que l'aperçu d'une pull request dit
PREVIEW = {
    "what": "Ouvrir une pull request sur {url} : la branche « {head} » vers « {base} », au commit {sha}. La branche "
            "de travail est poussée d'abord ; rien n'est fusionné.",
    "title": "Son titre : {title}",
    "body": "Son texte, exactement ce qui partira :",
    "milestones": "Les jalons de l'objectif et leurs preuves :",
    "no_milestones": "L'objectif n'a pas de jalons.",
    "kept": "(Le projet n'attend pas d'accord : les jalons partent sans leur texte, seulement leur état.)",
    "ticket": "Le ticket qu'elle traite : n° {number} « {title} » ({stage}).",
    "forgotten": "(titre oublié)",
    "no_ticket": "Elle ne traite aucun ticket.",
    "span": "Ce que la branche change face à sa base : {files}, {insertions} ligne(s) ajoutée(s), {deletions} "
            "retirée(s). Ses enregistrements (le plus récent d'abord) :",
    "files": "Les fichiers touchés : {files}",
    "cannot": "Ouvrir une pull request — impossible telle quelle : {why}.",
}
#: pourquoi une pull request ne part pas (ce que la capacité rend, ou ce qui bloque son aperçu)
CANNOT = {
    "missing": "projet, objectif ou atelier introuvable",
    "moved": "le dépôt distant ou le flux du projet a changé depuis la proposition",
    "not_work": "une pull request part d'une branche de travail, jamais de la base",
    "empty": "sa branche n'a rien de plus que la base",
    "shifted": "sa branche a bougé depuis la proposition",
    "changed": "ce qui partirait a changé depuis l'accord (rien n'est parti ; elle sera reproposée)",
    "no_base": "la branche « {base} » n'existe pas encore chez l'hôte : une pull request n'a pas où entrer (pousse "
               "la base une fois, au flux direct, puis reviens au flux par pull request)",
    "no_host": "aucun hôte ne sait ouvrir une pull request sur ce dépôt",
    "unopened": "la branche est poussée, mais sa pull request ne s'ouvre pas — {why}",
    "unsaid": "l'hôte ne la dit pas ouverte",
}
#: ce que la capacité rend quand elle a abouti
OPENED = "pull request n° {number} ouverte : {url}"
#: pourquoi un envoi ne part pas sur la branche de base d'un projet qui passe par des pull requests
BASE_KEPT = ("ce projet passe par des pull requests : rien ne se pousse sur sa branche de base (« {branch} ») — son "
             "travail part par sa branche de travail, puis par sa pull request")
#: le résumé de la récupération de la base, après une fusion vue chez l'hôte
BASE_PULL = "Récupérer la base depuis {url} (branche {branch}) — une pull request a été fusionnée"
