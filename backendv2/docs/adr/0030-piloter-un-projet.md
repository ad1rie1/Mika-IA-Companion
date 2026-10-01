# 0030 — Piloter un projet : des outils qui arrivent, une fiche qui gouverne

**Contexte.** « On ne peut rien contrôler, rien modifier, la fonctionnalité est totalement cassée. » En base vivante,
le projet 64 avait été confié par la console sans cadre ; son unique pas avait `"tools": []` : elle *racontait*
`**report_step**: continue`, avec une didascalie (« *soupire en souriant* »), au lieu d'appeler l'outil. Sans verdict,
le pas comptait « sans rien conclure » ; au troisième, le projet se serait bloqué tout seul, avec de la frustration et
de l'estime perdue, pour une panne d'outillage. Deux causes :

- *Le relais MCP n'était pas celui que le serveur monte.* `build_backend` construisait `relay or Relay()` ; un
  `Relay` sans session est vide, donc faux (`__len__`), et « or » en créait un autre, jamais monté. La CLI recevait
  404 sur son serveur `mika`, continuait sans lui (c'est le comportement de la vraie CLI) et le modèle n'avait plus
  aucun outil. Rien ne le voyait : l'adaptateur ignorait le message `system/init` qui liste les serveurs et leur état.
- *Plusieurs `mika serve` écrivaient ensemble dans `data/v2`* : le second échouait en boucle sur `events.seq` et plus
  rien ne s'écrivait, pas même une opération de la console.

Côté console, la fiche d'un but n'offrait que suspendre, reprendre, donner une consigne et clore. Le titre, le cadre,
la personne, l'échéance, l'agenda, le budget de pas et l'accord ne se modifiaient jamais. Un but bloqué ne se
rouvrait pas. Aucun « avancer maintenant ». Les approbations renvoyaient vers une autre page. Il n'y avait ni plan de
tâches ni priorité (le panneau du frontend affichait les *pas* déguisés en tâches). L'atelier montrait des noms de
fichiers qu'on ne pouvait pas ouvrir. Les formulaires de la barre d'actions partaient toujours des défauts du modèle,
et un formulaire refusé remontrait ses cases à cocher inversées.

**Décision.**
1. *Une panne d'outillage est une panne.* `Relay.__bool__` vaut vrai. `ClaudeCodeBackend` lit `system/init` : si un
   serveur qu'il a donné à la CLI n'y est pas `connected` (ou `pending`), l'appel échoue (`ClaudeCodeError`). La
   passerelle bascule alors sur le repli, sinon le pas finit `failed` et **rend son crédit** : il ne pousse plus vers le
   blocage. La fausse CLI des tests se comporte comme la vraie (serveur `failed`, session qui continue). Le prompt d'un
   pas dit que les outils *s'appellent* et ne s'écrivent pas, et qu'un moment de travail n'a pas de didascalies.
2. *Un seul Mika par dossier de données.* Un `flock` exclusif sur `<données>/mika.lock` (qui porte le pid de son
   détenteur) est pris par `serve` et par les commandes qui écrivent le journal. Un second processus est refusé en le
   disant (code 3). Le verrou est réentrant dans un même processus.
3. *Piloter, pas réécrire.* Les nouveaux gestes sont des opérations journalisées, chacune avec sa garde (« le but
   n'a pas changé entre-temps ») et son audit :
   - `goals.reframed` : modifier le cadre d'un projet confié (titre, cadre, pour qui, échéance, agenda, pas au
     plus, accord, priorité), reprogrammer un rappel (texte, heure, urgence) ; seuls les champs changés voyagent ;
     un budget inférieur ou égal aux pas déjà faits est refusé ;
   - `goals.reopened` : rouvrir un but bloqué, abandonné, en échec ou annulé, avec au moins N pas de plus ;
   - `goals.nudged` : avancer maintenant, avant l'agenda et l'espacement, jamais avant le plafond horaire ni pendant
     le sommeil ;
   - `goals.task_added` / `task_changed` / `task_removed` : le plan de travail ;
   - `goals.deposited` : un fichier déposé dans l'atelier.

   Sur une exploration qu'elle a entreprise d'elle-même, on pilote (pause, consigne, priorité, avancer, plan, clore,
   rouvrir) sans réécrire ni son titre ni son envie. Rouvrir n'émeut pas : ni fierté, ni frustration, ni estime
   touchée. Une exploration rouverte retrouve assez d'envie pour ne pas s'user aussitôt.
4. *Le plan se tient à deux.* L'opérateur pose des tâches, les coche en un clic, les modifie et les retire. Elle les
   lit à chaque pas (celles de l'opérateur d'abord, marquées « demandée ») et les tient à jour avec `goal_task_add` et
   `goal_task_update`. Cocher une tâche n'est pas une preuve de travail (« fini » reste réservé à un outil qui a
   produit quelque chose). Un « fini » prouvé avec des tâches encore ouvertes est accepté, et la réponse le lui
   signale. Le panneau du frontend compte les vraies tâches, et les pas seulement quand il n'y a pas de plan.
5. *La priorité* (`low`, `normal`, `high`, `urgent` : le vocabulaire du panneau) ajoute ou retire des crans de
   `priority_step` (un réglage borné) à la preuve d'un pas, dans la limite de 12. Elle ne contourne rien.
6. *Une seule lecture du budget* : `budget(g, p)`, où 0 vaut la valeur par défaut de sa sorte. Le travail, la clôture,
   la fiche et le prompt la partagent. Avant, un projet à 0 ne faisait aucun pas tandis que la clôture le croyait
   illimité. `why_not_now` dit en mots pourquoi il n'y a pas de prochain pas : en pause, en attente, un pas en cours, au
   bout de ses pas, pendant le sommeil, au plafond horaire, ou plus tard selon l'agenda.
7. *La fiche gouverne.*
   - La barre d'en-tête porte les actions qui valent pour tout le but.
   - Le Résumé montre dans l'ordre : le cadre, ce qui attend une décision (approuver ou refuser sur place, par le
     chemin unique de `runtime/decisions.py`), trois cartes (avancement, prochain pas, garde-fous), le dernier état et
     le plan de travail (chaque tâche se déplie sur ses boutons). Le détail complet est replié en bas.
   - « Cadre et réglages » commence par le formulaire pré-rempli.
   - Le Carnet raconte ce qu'on a fait du but.
   - L'Atelier ouvre un fichier, le télécharge et en reçoit un.
   - La liste des projets montre la priorité, l'avancement réel et le prochain pas en mots.
   - Confier un projet mène à sa fiche.
8. *La console, générique.* Aucune de ces briques ne nomme une faculté :
   - `ActionSpec.initial` : une action se pré-remplit depuis l'état, et reçoit les ports si elle les déclare, pour un
     texte gardé hors de la tranche ;
   - `Done.go_created` : aller sur la fiche de ce qui vient d'être créé ;
   - un champ `file` (`forms.Upload`, 5 Mo au plus, nom assaini, `multipart/form-data`) ;
   - une action qui porte sur une ligne (un champ caché requis) ne se propose pas en tête de page ;
   - une case listée mais absente de l'envoi est remontrée décochée.

**Conséquences.** Les tests :
- de contrat : un relais 404 échoue bruyamment et bascule sur le repli ; un pas bâti par `build_gateway` sur le
  relais monté appelle vraiment `report_step` ;
- le verrou : un second processus est refusé et nommé ;
- d'intention (`test_goals_pilot.py`) : le pas suivant lit le cadre modifié ; une exploration refuse `modifier` ; un
  budget dépassé est refusé et 0 vaut la valeur par défaut ; un projet rouvert refait un pas sans émotion ;
  « avancer » passe l'agenda sans passer le plafond ; le plan se tient à deux et le panneau compte 4 tâches dont
  1 faite ; décider depuis la fiche donne le même `effect.resolved`, une seule fois ; un dépôt arrive dans
  l'atelier, commité, et un chemin qui en sort est refusé ; la priorité pèse ;
- HTTP (`test_goals_web.py`) : cases remontrées telles quelles, arrivée sur la fiche, formulaire pré-rempli, plan en
  boutons, dépôt multipart puis téléchargement, chaque onglet ouvert sur un projet vivant, en pause, clos, rouvert.

Le simulateur gagne un mode de travail « plan ». L'onglet « Cadre et politique » s'appelle « Cadre et réglages » et
garde sa clé (`politique`). Après la correction du relais, un serveur lancé avant doit être **redémarré**.

**Complément — un compte est une personne.** Un projet confié depuis la console par un opérateur qui n'avait jamais
parlé par le chat restait « user_1 » partout, et « Modifier le projet » était refusé à chaque envoi : la personne
pré-remplie (lui-même) était « inconnue », faute de poignée. Désormais :
- un événement `identity.registered` (poignée, nom, opérateur, actif) fait de chaque compte une personne
  authentifiée, sous son nom affiché (nom complet, sinon identifiant) ;
- l'application l'écrit au démarrage pour les comptes dont l'identité diffère (les anciens, ceux créés hors ligne par
  `mika account`), puis après chaque création, amorce ou modification (`Accounts.on_change`). Comparer d'abord rend
  l'appel idempotent, et un renommage aller-retour s'écrit quand même ;
- un compte désactivé n'est plus propriétaire ;
- le nom affiché se modifie dans Comptes ;
- la recherche de personnes décrit par où on la connaît (« compte opérateur », « telegram ») au lieu de montrer des
  poignées brutes ;
- la fiche d'un but nomme la personne sans sa clé ;
- une personne que le but a déjà, ou l'opérateur lui-même, ne se revalide pas.

Tests : `tests/protocol/test_accounts_identity.py`.
