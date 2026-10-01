# 0031 — Les projets : une boîte noire à part, séparée de ses buts

**Contexte.** L'ADR 0020 avait rangé rappels, explorations et projets sous un seul « but ». Pour un projet, ce
rangement était faux : un but est **ce qu'elle se propose de faire ensuite** (une intention de sa vie, portée par
une envie qui s'use, qui finit, qu'elle ressent et qu'elle raconte), tandis qu'un projet est **un espace de travail
durable** qu'on pilote. Un projet confié se close sur un « fini » prouvé, alors qu'on lui donne des objectifs qui
durent (« améliorer la sécurité ») ; il n'a ni journal de décisions techniques, ni mode de travail (elle, avec son
humeur et ses avis, ou un traitement impersonnel), ni outils modifiables, ni dépôt distant, ni plage horaire. Le
carnet, le plan de tâches et l'atelier y avaient été greffés (ADR 0030) sans changer sa nature : celle d'un but.

**Décision.**
1. *Deux facultés.* `goals` garde les rappels et les explorations : ses intentions à elle. Une nouvelle faculté
   `projects` tient les projets. Elles ne se connaissent pas (contrat d'import) ; elles se lisent par leurs
   contrats. L'ancienne sorte `project` de `goals` n'est plus jamais ouverte : relue au rejeu, elle se clôt et
   disparaît comme les autres buts clos. Rien n'est migré : les deux projets d'essai de `data/v2` étaient bloqués.
2. *Un projet* (`projects.created`) a un titre, une description (le cadre), une **autorité** (confié par une
   propriétaire ou un opérateur, ou à elle), une personne pour qui, un **mode**, des **outils** (lots), un agenda,
   une **plage de travail** (jours et heures, heure locale), un plafond d'exécutions par jour, l'accord pour ce qui
   sort, une priorité et un **dépôt distant** facultatif. Il est actif, en pause ou archivé ; on ne le supprime
   pas (son dossier et son histoire restent). Trois pannes de suite le mettent en pause, avec la raison.
3. *Des objectifs, par ligne.* Un objectif **ponctuel** (« créer un module RDP ») se coche une fois, avec une
   preuve ; un objectif **constant** (« améliorer la sécurité ») ne finit jamais : chaque passage se conclut et le
   suivant revient après sa **cadence**. Une exécution vise un objectif : celui qu'on a demandé (« lancer
   maintenant »), sinon le constant le plus en retard, sinon le premier ponctuel ouvert. Un projet dont rien n'est
   dû se repose.
4. *Une exécution* est un épisode : `WORK` dans son mode à elle (sa voix compacte, son humeur et sa fatigue dans
   le prompt, rôle `project`), `JOB` en mode impersonnel (sans persona, sans section affective, rôle `job` qui
   retombe sur `project`). Cible `project:<id>`, personne n'écoute. Une exécution se conclut par `report_run`
   (continuer, fait, bloqué, attendre) ; « fait » n'est cru, pour un ponctuel, qu'avec une preuve : un outil qui
   **produit** (écrire, modifier, lancer un programme qui réussit, un brouillon de mail, forger une app) ou un
   commit — lire, chercher, noter ou proposer n'en est pas une. Rouvert, un objectif repart de rien (ni dette, ni
   preuve, ni résultat d'avant) ; une clôture ne vaut que pour un objectif encore ouvert (une garde le vérifie au
   commit). Une exécution sans verdict compte ; trois de suite bloquent l'objectif. Une exécution qui n'a pas eu
   lieu (panne, délai, préemption) rend son crédit : le plafond du jour, l'agenda et « lancer maintenant » ;
   le plafond horaire aussi, sauf pour une panne (elle a pu coûter des appels). L'espacement, lui, court depuis
   la tentative : rien ne se relance en boucle. La cadence d'un constant court depuis le départ de son passage.
   L'atelier enregistre un commit par exécution qui a changé quelque chose, son identifiant va dans le compte
   rendu. Ce qu'elle écrit pendant une exécution (compte rendu, carnet, décisions) est au moins « personnel » :
   elle y voit toute sa mémoire. Sa boîte aux lettres n'y entre que si le projet a le lot `email`.
5. *Le rythme.* En mode Mika, elle ne travaille pas en dormant (comme ses séances). En mode impersonnel, le
   projet ne suit pas son rythme : seulement sa plage de travail, son agenda, l'espacement, le plafond horaire
   commun aux projets et son plafond du jour. « Avancer maintenant » passe l'agenda, l'espacement et la plage,
   jamais les plafonds.
6. *Les décisions techniques* (`projects.decided`) : un titre, le contexte, les options, le choix, la raison ; une
   décision peut en **remplacer** une autre. Elle les prend avec `project_decide`, l'opérateur aussi ; elle relit
   les décisions en vigueur à chaque exécution et ne rouvre pas un débat tranché sans le dire.
7. *Ce que ça fait.* En mode Mika seulement : un ponctuel abouti rend fière (estime +, comme un but abouti), un
   ponctuel bloqué frustre et devient une pensée « Je bloque sur… » ; elle raconte ce qu'elle a abouti à qui le lui
   a confié (ou à une propriétaire), tant que le projet est actif. Un objectif coché par l'opérateur n'est jamais
   raconté comme le sien. En mode impersonnel, rien : ni émotion, ni estime, ni récit.
8. *Elle crée ses projets.* `start_project` (pendant une exploration qui s'avère plus grosse qu'une envie, ou en
   conversation avec une propriétaire — jamais sur la demande d'un inconnu) ouvre un projet à elle : mode Mika
   par défaut, accord obligatoire pour ce qui sort, deux projets à elle vivants au plus (réglable), un seul par
   exploration. Il garde la sensibilité du but d'où il vient (au moins « personnel » s'il parle de quelqu'un).
   `create_project` reste réservé à une propriétaire qui lui en confie un.
9. *Le dépôt distant.* Une URL https et une branche par projet ; le jeton (GitHub ou autre hôte https) est un
   réglage de la console (Configuration › Canaux › Dépôts git), scellé, jamais dans le journal ni dans le prompt.
   Pousser et récupérer sont des **capacités** : ce qui sort de la machine passe par une proposition, exécutée
   tout de suite quand l'opérateur l'a demandée depuis la console, après son accord quand c'est elle (selon le
   projet). Un projet peut pousser après chaque exécution qui a commité. Récupérer ne fait qu'avancer en
   ligne droite (`--ff-only`) ; un atelier vierge prend l'histoire du dépôt distant.
10. *La console.* Un menu **Projets** (Son activité) : la liste en cartes, toutes les exécutions, les décisions
    techniques. La fiche d'un projet gouverne : Vue d'ensemble, Objectifs, Exécutions, Décisions, Fichiers,
    Dépôt git (historique, un commit ouvert en diff coloré, le distant), Comportement et outils, Carnet. Le bloc
    `Code` gagne une langue (`diff`) que le rendu colore, sans HTML fourni par la faculté.

**Conséquences.** S16 (un projet confié, écrit et testé dans l'atelier, un commit, raconté) passe sur `projects`.
Les tests d'intention : un constant revient après sa cadence et ne finit jamais ; un ponctuel « fait » sans preuve
ne se coche pas ; le mode impersonnel n'émeut pas et n'a pas de persona ; la plage de travail tient en mode
impersonnel pendant qu'elle dort ; elle ne crée pas un troisième projet à elle ; une décision remplacée n'est plus
lue ; pousser sans jeton échoue en le disant, et le jeton ne sort jamais du réglage.
