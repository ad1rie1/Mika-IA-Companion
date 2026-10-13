# 0104 — Une app a un foyer : tous les chemins de son travail autour de la Forge

**Contexte.** Le 2026-10-12, une sonde avec Haiku (la CLI, deux bases jetables) : Adrien, sa propriétaire, lui dit
« ce serait bien que tu suives un peu la bourse ». Elle ne se fabrique rien.
- En conversation, elle répond « je n'ai pas accès aux cours », ou annonce « je peux essayer de me monter un petit
  outil dans ma Forge », « je regarderai », sans appeler d'outil ; rien ne garde cette intention.
- Avec la Forge chargée d'emblée (contre-essai), elle refuse quand même : le chargement différé n'était pas la cause.
- Quand on lui suggère un projet, elle en ouvre un, mais son exécution n'a ni la Forge ni ses flux (`start_project`
  donnait toujours `projects, workshop, memory`) : elle écrit un lexique et dit l'objectif fait.
- Le réseau marchait (`http_get` rend les cours d'un site public).

Les deux explorations du code ont trouvé le même schéma partout : chaque étape existe, aucune ne passe le relais.
Un projet à elle ne pouvait pas forger ; une annonce s'évaporait ; une panne d'app n'était réparée que si une pensée
était assez forte, à une heure assez libre, avec une consigne « lis-le » ; ce qu'une app trouvait n'allait à personne
(`about=()`) ; aucun outil ne lisait une app en conversation ; une version mise de côté n'avait pas de carte dans le
chat et un refus ne lui revenait pas ; `api.emit` n'arrivait nulle part ; le guide ne montrait aucun `http_get` ;
`forge_test` n'essayait que `tick` et les vues ; relire sa Forge ou réactiver une app « prouvait » un travail.

**Décisions de la propriétaire.** Une app vit dans un projet. Le réseau d'une app reste libre (ADR 0039). Seule sa
propriétaire lui confie un travail. En conversation, devant sa propriétaire, elle lit ses apps et les fait agir, sans
promotion, si l'app n'a pas de secret. La Forge offre à une app plusieurs services planifiés, une base (ADR 0101), le
réseau ; ses actions sont des outils à elle ; dans la console, ses pages sont les onglets de sa fiche, ses réglages
derrière une roue.

**Décision.**

1. *Un projet à elle peut se donner ses outils* (`faculties/projects`).
   - `start_project` prend `tools`, parmi `SELF_BUNDLES = (memory, rss, forge, forge_apps)` ; le courrier et la caméra
     restent à un opérateur. Une exploration devenue projet garde ses lots (`GoalView.bundles`).
   - Pendant une exécution d'un projet à elle, `project_equip` ajoute un de ces lots (l'exécution suivante l'a) ; un
     projet confié garde son cadre, elle le demande (`needs_you`).
   - L'exécution dit ce qui lui manque (`missing_tools`).
2. *Une intention ne s'évapore plus.*
   - La règle de ses mains dit ce qu'une app sait faire et qu'un travail s'ouvre maintenant (`start_project`) : « je
     vais essayer » sans outil ne fait rien. Elle ne dit plus « je ne peux pas » de ce qu'elle pourrait se fabriquer ;
     si ça ne lui dit rien, elle le dit.
   - Le filet : l'extraction marque une promesse **de travail** (`PromiseNoticed.work`) ; faite à une propriétaire,
     `goals.seed` la met en route — une exploration d'origine `promise`, avec la Forge et les projets, qui ne fait pas
     la queue derrière l'espacement de ses envies, une fois par promesse.
3. *Une app a un foyer.*
   - Écrite pendant une exécution (ou en désignant un de ses projets vivants), elle y est rattachée (`App.project`,
     `AppView.project`). Le projet la voit dans son exécution (« Tes apps dans ce projet »).
   - Sa panne ajoute au projet un objectif « Réparer » (marqué `app@version`, une fois par version cassée) et lance une
     exécution ; il ne se prouve que par l'app réécrite et essayée, jamais par un fichier de l'atelier.
   - Une app sans projet se répare par une exploration d'origine `repair`, ouverte directement (ni seuil de pensée, ni
     espacement). La Forge ne fait plus explorer « ce que j'ai remarqué dans une de mes apps » : ses trouvailles se
     lisent dans l'app, sa panne a son chemin.
   - Ce que trouve une app rattachée porte l'`about` de son projet, à son niveau : une pensée qui en naît peut la
     pousser à le dire à cette personne.
   - Un projet à elle dit aussi « j'ai besoin de toi pour… » (`_need`).
   - Une version mise de côté (secrets, promotion) arrive en carte dans le chat de sa propriétaire (`_decider`) ; un
     refus revient dans l'état de l'app et la version refusée quitte l'hôte.
4. *Ses actions sont ses outils.* Une source d'outils (`tool_source`, famille `forge_apps`) publie, pour chaque app,
   ses outils (`<app>_<outil>`) et la lecture de ses pages (`<app>_pages`), en main, dans le lot `forge_apps.<app>`
   décrit par son titre. Un lot qui porte le nom d'une famille l'admet entière (`runtime.tools.admitted`). L'hôte
   prévient quand son offre change (`ForgeHost.on_change`). `forge_call` disparaît.
5. *La preuve se déclare sur l'outil.* `ToolResult.proof` (vrai, faux, ou rien : la règle de qui juge) ; le runtime
   les garde à côté des appels ; `kernel.faculty.proving_tools` les lit pour les buts et les projets. Relire sa Forge,
   écrire sans essayer, réactiver, lire une page : rien de prouvé ; un essai réussi d'une app écrite dans le même
   épisode : une preuve ; un brouillon de mail aussi.
6. *Plusieurs services par app.* `services: [{name, schedule, description}]` → `service_<nom>(api)`, chacun son
   rythme, son dernier passage, ses échecs et son disjoncteur (un service cassé n'arrête pas les autres, et ouvre sa
   réparation). Le `tick` historique reste le service principal ; « tick » est réservé.
7. *Le guide dit vrai, l'essai couvre tout.* `forge_help veille` : un exemple exécuté par un test (un cours relevé
   chaque heure, `context`, un signal à 0,6, une vue, un outil) et les limites dites. `forge_test` essaie aussi
   `context`, `on_event`, `tool_<nom>`, `action_<vue>_<action>` et `service_<nom>`, et dit ce que deviendraient les
   signaux (le premier seulement, espacés, une pensée dès `attention.SIGNAL_THOUGHT_FROM`).
8. *Les petits trous.* `api.emit` parvient aux autres apps qui l'écoutent (`events: [forge.<app>.*]`, ses données dans
   `événement["data"]`), jamais à son attention. `http_get` accepte `Accept`, `Authorization`, `X-Api-Key` ; une
   redirection devient une erreur qui nomme sa cible ; plus de 10 domaines sont refusés en le disant. La section
   « TES APPS » appelle ses apps en parallèle, sert aussi au travail et porte le niveau de leur projet.
9. *La console.* `Head.pages` / `Head.pages_tab` : les pages d'un objet deviennent les onglets de sa fiche ;
   `Head.gear` range des onglets derrière la roue, en haut à droite. La fiche d'une app : ses pages en onglets ; ses
   réglages, son état, son code, sa base, son journal et son vécu derrière la roue.

**Conséquences.** Contrats : `GoalView.bundles`, `goals.FROM_PROMISE` / `FROM_REPAIR`, `PromiseNoticed.work`,
`PendingPromise.work` / `text_ref` / `sensitivity`, `attention.SIGNAL_THOUGHT_FROM`, `AppView` (`project`, `held`,
`pending`, `refused`, `ticked_at`, `services`, `broken_services`) et `forge.failure`, `ObjectiveAdded.app`,
`ToolResult.proof`, `ForgePort.discard` / `on_change`, `AppService`. La tranche de la Forge passe en version 3.
Tests d'intention : `tests/unit/test_forge_home.py` ; scénario S23 « elle se fabrique un outil » (voie rapide), cassé
exprès pour vérifier qu'il n'est pas vide.

**Ce qui n'a pas été fait ici.** La liste descriptive `CHANGING` du compte rendu d'une exécution nomme encore
`forge_write` et `email_draft` (le garde « aucune faculté ne nomme un outil de greffon » n'a pas été ajouté). Le
réseau d'une app neuve reste sans accord (choix de la propriétaire). Les outils d'une app n'ont pas de schéma
d'arguments déclaré : leur code lit ce qu'on lui passe — fait par l'ADR 0105, avec le web au travail, un réseau
libre, des délais déclarés, la retouche d'une app et une confiance par app.
