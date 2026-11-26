"""Les projets, tels que la couche ``app`` les relie (ADR 0031, 0183, 0289, 0297, 0308, 0310) : leur fiche.

Ce dossier porte leurs réglages (``settings.py`` : le jeton de leurs dépôts git distants), leur câblage
(``wiring.py`` : l'atelier, le port ``workshop`` ; l'hôte de leurs dépôts distants, ``repo_host`` ; les images de
leur documentation, ``project_docs`` ; puis, le noyau là, le point MCP de leur documentation, ``/mcp/moi``, dont le
code est ``docs_mcp.py``), leur module de l'API par personne (``api/`` : ses projets et « À faire », leur code, leur
documentation, ce qu'on y gère, leur activité ; ce qui attend son geste, pour la barre du haut), leur part du direct
(``live.py``), leur part du port d'entrée (``port.py`` : ce que le panneau d'une personne dit du travail en cours,
pour une propriétaire), leur part de la console (``console/`` : Activité › Projets, la fiche d'un projet et ses
onglets, la rubrique « Dépôts Git », l'onglet Projets de la fiche d'une personne et son compte, leurs gabarits, leurs
feuilles et leur script) et ce que l'aperçu en montre (``demo.py`` : une chaîne de travail d'exemple ;
``demo_git.py`` : un dépôt face à son distant, sans réseau ; ``demo_activity.py`` : des états fictifs de l'activité),
que l'aperçu du cadre pose. Leurs dossiers du dossier de données : ``ateliers/`` et ``documentation/`` (``places`` :
ce qu'ils gardent, ce qu'une sauvegarde ne prend pas sous les ateliers, leur cage, leur recréation à la
restauration). Ils lisent la Forge (les apps d'un projet) et les outils (le protocole MCP).

Elle est la dernière de ``DOMAINS`` : un accord d'un projet se reconnaît par le contexte de l'événement, et le direct
ne le regarde qu'après tous les autres domaines (un brouillon de mail né dans un épisode de projet reste au courrier).

Restent au cadre, parce qu'ils croisent les domaines ou qu'aucune forme de fiche ne les dit : la vie fictive de
l'aperçu, où leurs projets se mêlent au reste, le lien « Dépôts Git » du menu (Connexions extérieures : une fiche n'a qu'un lien), et leur place
dans la composition (``composition.py`` : la faculté, ses lots d'outils, l'ordre de son prompt).
"""

from __future__ import annotations

from mika.app.domains.domain import Domain, Place
from mika.inspector.catalog import Destination, MenuLink

PROJECTS = Domain(
    "projects",
    needs=("forge", "tools"),
    places={
        # une cage (leurs dépôts portent des liens vers le système). Jamais archivés, sous eux : les vues des ateliers
        # lus (ADR 0260, 0262) — la copie du dernier commit d'un autre atelier, que l'archive porte déjà avec son
        # dépôt, et qui se repose seule à l'exécution suivante ; et la copie de commit qu'une relecture indépendante lit
        # (ADR 0277), jetable par nature (``adapters/workshop``, ``VIEWS_DIRNAME`` et ``REVIEWS_DIRNAME`` : une fiche
        # n'importe pas d'adaptateur, ``tests/unit/test_backup.py`` vérifie que ce sont les mêmes noms)
        "ateliers": Place("les ateliers de ses projets, avec leur git", made=True, caged=True,
                          unsaved=(".vues", ".relectures")),
        # les images de la documentation de ses projets (ADR 0289) : à elle seule
        "documentation": Place("les images de la documentation de ses projets (100 Mio par projet)", made=True,
                               private=True),
    },
    settings="mika.app.domains.projects.settings",
    wiring="mika.app.domains.projects.wiring",
    api="mika.app.domains.projects.api",
    live="mika.app.domains.projects.live",
    console="mika.app.domains.projects.console",
    port="mika.app.domains.projects.port",
    destination=Destination(
        "projets", "Projets", "Ses projets : des espaces de travail qu'on pilote — objectifs, "
        "exécutions, décisions techniques, fichiers, dépôt git, mode et outils.",
        subjects=("project",)),
    menu=MenuLink("Projets", "projets", hint="Ce qu'elle mène, pas à pas"),
    labels={
        "faculties": {
            "projects": "Projets",
        },
        "sections": {
            "project": "Ce projet",
            "project_share": "Un projet à partager",
            "projects": "Ses projets",
            "project_network": "Ce que le réseau a rendu",
            "project_answer": "La réponse à sa demande d'aide (un projet)",
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
        },
        "reasons": {
            "run": "Travailler sur un projet",
            "project_share": "Partager où en est un projet",
            "project_need": "Demander un coup de main pour un projet",
            "project_plan": "Dire son plan à qui a demandé un projet",
        },
        "vetoes": {
            "run_cap": "Assez d'exécutions pour l'heure",
        },
        "processes": {
            "projects.tend": "Suivre ses projets",
            "projects.apps": "Réparer les apps de ses projets",
            "projects.views": "Retirer les vues d'atelier qu'un projet n'a plus le droit de lire",
            "projects.stirs": "Juger ce qui déclenche un objectif (un commit d'un projet lu, un signal d'app)",
            "projects.tickets": "Faire naître « Traiter les tickets », et suivre l'objectif né d'un ticket",
            "projects.remote": "Pousser et récupérer les dépôts",
            "projects.pulls": "Proposer la pull request d'un travail conclu, la relire chez l'hôte avec ses vérifications",
            "projects.issues": "Tenir les issues pour le reflet des tickets : ce qui part, et ce que l'hôte en dit",
            "projects.reviews": "Demander la relecture indépendante d'un travail conclu, hors des pull requests",
        },
        "events": {
            "projects.amended": "Un projet modifié",
            "projects.archived": "Un projet archivé",
            "projects.created": "Un projet créé",
            "projects.decided": "Une décision technique",
            "projects.decision_changed": "Une décision technique revue",
            "projects.deposited": "Un fichier déposé",
            "projects.noted": "Une note sur un projet",
            "projects.nudged": "Un projet relancé",
            "projects.objective_added": "Un objectif ajouté",
            "projects.objective_changed": "Un objectif modifié",
            "projects.objective_closed": "Un objectif clos",
            "projects.paused": "Un projet en pause",
            "projects.reframed": "Un projet recadré",
            "projects.remote_requested": "Un échange avec le dépôt distant demandé",
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
            "projects.restored": "Un projet restauré",
            "projects.resumed": "Un projet repris",
            "projects.run_reported": "Une exécution rendue",
            "projects.access_set": "Les accès d'un projet réglés",
            "projects.steer_asked": "Une demande de pilotage d'un projet, sur ton accord",
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
        },
        "effects": {
            "projects:effect.executed": ("agit", "Un pilotage de projet accepté",
                                         "la demande de quelqu'un sur un projet s'écrit, à son nom, après ton accord"),
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
        },
        "bundles": {
            "workshop": "L'atelier d'un projet",
            "project_review": "Relire le travail d'un projet",
        },
        "capabilities": {
            "projects.networked": "Commande réseau",
            "projects.push": "Push git",
            "projects.pull": "Pull git",
            "projects.pull_request": "Pull request",
            "projects.issue": "Issue publiée",
            "projects.issue_state": "État d'une issue",
            "projects.issue_note": "Note publiée",
            "projects.steer": "Pilotage de projet",
        },
        "enrichers": {
            "projects": "Ses projets",
            "projects_tree": "L'arbre de l'atelier d'un projet",
            "projects_apps": "Ce qui n'a pas marché pour ses apps",
            "projects_views": "Les vues des ateliers que son projet lit",
            "projects_items": "Le registre de son projet (ce qui a bougé, ses éléments ouverts)",
            "projects_tickets": "Les tickets que regarde son exécution (entre ses mains, ou celui de son objectif)",
            "projects_review": "Ce qu'une relecture indépendante a sous les yeux (ses textes, le diff du commit relu)",
            "projects_asks": "Les demandes de son projet aux projets qu'il lit (où chacune en est)",
            "projects_answer": "La réponse à sa demande d'aide (un projet)",
        },
    },
)
