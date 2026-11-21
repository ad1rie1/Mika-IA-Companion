"""Ce que la console dit du reflet des tickets en issues (ADR 0275) : l'aperçu que l'opératrice lit dans « À valider »
avant son accord, ce qui empêche un départ, le résumé d'une proposition et ce qu'une capacité en rend. Des textes de
console, lus par qui décide — pas des phrases qu'elle lit : les siennes, et ce qui part chez l'hôte, sont dans
``persona/voix.yaml`` (``projects.issues``). ``issues.py`` les compose ; ``inspect_tracker.py`` porte les gestes de la
fiche (« Publier », « Publier cette note », le réglage).
"""

from __future__ import annotations

#: les trois capacités, telles que « À valider » les nomme
DESCRIPTION = {
    "publish": "Publier un ticket d'un projet en issue chez l'hôte de son dépôt distant : son titre et son texte, "
               "une seule fois.",
    "state": "Fermer ou rouvrir chez l'hôte l'issue d'un ticket, quand le ticket a été fermé ou rouvert ici. Aucun "
             "texte ne part.",
    "note": "Publier une note du fil d'un ticket en commentaire de son issue chez l'hôte : cette note-là, et rien "
            "d'autre de son fil.",
}
#: le résumé d'une proposition : des numéros et le dépôt — rien de plus
SUMMARY = {
    "publish": "Publier en issue le ticket n° {ticket} du projet n° {project}, sur {url}",
    "close": "Fermer chez l'hôte l'issue du ticket n° {ticket} du projet n° {project} ({url})",
    "reopen": "Rouvrir chez l'hôte l'issue du ticket n° {ticket} du projet n° {project} ({url})",
    "note": "Publier une note du ticket n° {ticket} du projet n° {project} en commentaire de son issue, sur {url}",
}
#: ce que l'aperçu d'un départ dit
PREVIEW = {
    "publish": "Publier le ticket n° {number} en issue sur {url}. Elle part du compte du jeton ; rien d'autre de "
               "son fil ne part avec elle.",
    "title": "Son titre : {title}",
    "body": "Son texte, exactement ce qui partira :",
    "close": "Fermer l'issue n° {issue} de {url} : le ticket n° {number} est fermé ici ({how}). Aucun texte ne part.",
    "reopen": "Rouvrir l'issue n° {issue} de {url} : le ticket n° {number} a été rouvert ici. Aucun texte ne part.",
    "note": "Publier une note du ticket n° {number} en commentaire de l'issue n° {issue} sur {url}. Elle part du "
            "compte du jeton ; le reste de son fil ne part pas.",
    "why": "Ton accord est demandé quel que soit le réglage du projet : {why}.",
    "cannot": "Ce départ vers les issues est impossible tel quel : {why}.",
}
#: comment un ticket a été fermé (l'aperçu d'une fermeture)
HOW = {"done": "traité", "dropped": "écarté"}
#: pourquoi un texte ne part jamais sans accord (``issues.reasons``)
WHY = {
    "level": "ce ticket est d'un niveau plus confidentiel que ce qu'écrit le projet",
    "project": "ce ticket a été ouvert par un autre projet",
    "inherited": "ce projet porte des sujets hérités de ce qu'il lit : ce texte peut parler de leurs personnes",
    "hers": "c'est elle qui a choisi de publier cette note",
    "own": "c'est elle qui a ouvert ce ticket",
    "named": "son titre ou son texte nomme une personne du projet",
}
#: pourquoi un départ ne part pas (ce que la capacité rend, ou ce qui bloque son aperçu)
CANNOT = {
    "missing": "projet ou ticket introuvable",
    "moved": "le dépôt distant du projet ou son réglage des issues a changé depuis la proposition",
    "published": "ce ticket a déjà son issue : il ne se publie qu'une fois",
    "hosted": "ce ticket vient d'une issue de l'hôte : il y est déjà",
    "proposed": "ce ticket est encore proposé : il s'accepte avant de se publier",
    "closed": "ce ticket est fermé",
    "not_ticket": "seul un ticket se publie",
    "forgotten": "son texte ne se lit plus (il a été oublié)",
    "unpublished": "ce ticket n'a pas d'issue chez l'hôte",
    "turned": "le ticket a changé d'état depuis la proposition",
    "no_note": "cette note n'est pas dans le fil de ce ticket",
    "from_host": "cette note vient de l'hôte : elle y est déjà",
    "changed": "ce qui partirait a changé depuis l'accord (rien n'est parti)",
    "no_host": "aucun hôte ne sait écrire dans les issues de ce dépôt",
    "unsent": "l'hôte n'a rien écrit — {why}",
    "unsaid": "il ne dit pas pourquoi",
}
#: ce qu'une capacité rend quand elle a abouti : des numéros et un lien composé par l'adaptateur, aucun texte
DONE = {
    "publish": "issue n° {number} ouverte : {url}",
    "close": "issue n° {number} fermée",
    "reopen": "issue n° {number} rouverte",
    "note": "note publiée sur l'issue n° {number}",
}
#: sur la fiche d'un ticket : son issue, et ce que disent les gestes
ISSUE_FR = {"open": "ouverte", "closed": "fermée"}
PUBLISH_HELP = {
    "ask": "La publication attend ton accord dans « À valider », avec ce qui partira exactement.",
    "always": "Ce projet publie de lui-même les tickets que tu ouvres ; ceux qu'elle ouvre, ceux qui nomment "
              "quelqu'un et ce qui porte plus que le projet attendent quand même ton accord dans « À valider ».",
}
