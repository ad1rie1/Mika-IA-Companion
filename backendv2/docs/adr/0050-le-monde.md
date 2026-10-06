# 0050 — Le monde : un créateur l'écrit, elle le fait vivre, le moteur le joue

**Contexte.** Depuis l'ADR 0049, Mika choisit où elle se tient dans sa chambre parmi six lieux, et le client
web la fait marcher, s'asseoir, s'allonger. La suite demandée va plus loin : elle doit **prendre, porter et
poser** des objets, dans un monde de **plusieurs pièces** avec **d'autres personnages**, et des personnes doivent
pouvoir y entrer et **interagir avec elle** (lui tendre quelque chose, lui faire signe, s'asseoir à côté
d'elle). Un vrai moteur de jeu (Unity) fera le rendu, la navigation, l'IK et la physique ; le client web
restera. Trois exigences de l'utilisateur : un **créateur** de monde et d'objets ; **c'est l'IA** qui fait vivre
le monde ; **le moteur** charge le monde et tient la **synchronisation dans les deux sens** (ce qui se passe dans
la 3D lui parvient, ce qu'elle fait se voit dans la 3D) — pour un monde **cohérent**.

Deux façons d'échouer, évitées ici : laisser la physique d'un moteur décider de ce qui est vrai (deux écrans qui
ne montrent plus la même chose, et Mika qui croit autre chose que ce qu'on voit) ; et faire de chaque geste un
appel de modèle (un monde vivant ruinerait le budget et la latence).

**Décision.**

1. *Le noyau est le monde.* Une faculté `world` (contrat `contracts/world.py`) tient la définition et l'état
   vécu dans le journal, comme tout le reste de sa vie : rejouable, explicable, simulable, sauvegardé. Les
   moteurs sont des clients qui montrent, jouent et constatent ; aucun n'est une source de vérité.

2. *Deux couches.* La **définition** (`WorldDef`) — pièces et passages, lieux (`spot`, `seat`, `bed`, capacité,
   tags `sleep`/`work`/`spawn`), archétypes et leurs actions, objets, personnages — est écrite par un créateur
   et versionnée (`rev`). L'**état vécu** (`WorldState`) — où est chaque acteur et chaque objet, son état, qui
   tient quoi, qui fait quoi, ce qui est en route, ce qui attend une réponse — change par les actions. Une
   définition est **cohérente ou n'existe pas** : `WorldDef` refuse à la validation tout ce qui nomme
   l'inexistant ou met deux choses au même endroit, et dit tout d'un coup.

3. *La vérité est discrète.* Un lieu, une place de surface, un contenant, une main. Seule la définition porte
   une position grossière par lieu, pour les distances et les durées de marche ; la géométrie, les modèles, les
   ancres et les animations sont dans le projet du moteur, référencés par des clés que le noyau ne lit pas. La
   physique est un rendu : elle peut faire rebondir une tasse, pas la déplacer dans l'état du monde sans un
   constat validé.

4. *Un même vocabulaire pour tous les acteurs.* Mika, une personne et un personnage du moteur agissent par les
   mêmes actions, validées par les mêmes règles : des **actions de base** (`take`, `put`, `give`, `drop`,
   `sit`, `lie`, `stand`) et des **affordances** déclarées par l'archétype — un nom libre (`allumer`,
   `arroser`, `lire`) et un **effet pris dans une liste fermée** (`state`, `activity`, `consume`). On ne prend
   pas ce que l'autre tient : on demande, on tend, et l'autre accepte ou non. L'**accès** d'un objet est gradué
   (`anyone`, `friends`, `owners`, `mika`) : une amie peut feuilleter son carnet, une inconnue non.

5. *Une action est une intention planifiée.* Le noyau valide, découpe en pas (se lever, marcher, prendre),
   donne à chacun sa durée nominale, réserve ce qu'elle va prendre ou occuper (des baux, `kernel/guards.py`),
   et fixe une échéance (`deadline` = `eta` + une marge). Le moteur **hôte** la joue et la termine (`done`) ou
   dit qu'il n'y arrive pas (`failed` + où est vraiment l'acteur) ; **sans hôte, le noyau la termine comme
   prévu à l'échéance**. Le moteur peut refuser et constater, jamais décider : un monde sans spectateur continue
   de vivre, et le premier écran qui arrive le pose tel qu'il est.

6. *Trois étages de vie, un seul qui coûte un appel de modèle.*
   - Les **réflexes** sont des règles du noyau, sans modèle : elle s'endort → elle va au lieu `sleep` et
     s'allonge (la règle de l'ADR 0049, généralisée) ; elle se réveille → elle s'assied au bord ; elle travaille
     sur un projet → elle va au lieu `work`. Un réflexe est un **réducteur** de l'événement qui le cause, jamais
     un processus qui émet après coup : l'intention du coucher naît dans la même transaction que
     `body.fell_asleep` (son identifiant dérive de l'événement), si bien que les écrans reçoivent l'endormissement
     et la destination ensemble — elle marche jusqu'au lit les yeux ouverts puis s'endort allongée, au lieu de
     s'endormir debout et de se réveiller pour marcher. Le rejeu redonne la même intention.
   - Les **décisions** sont les siennes, par ses outils, quand elle a de toute façon un épisode (une réponse,
     une initiative) : aucun geste du monde ne déclenche un appel de modèle pour lui-même.
   - La **micro-vie** (se gratter la joue, feuilleter une page, changer d'appui) appartient au moteur et n'est
     jamais journalisée.

7. *Ce qu'elle perçoit, ce qu'elle fait.*
   - Une section volatile « AUTOUR DE TOI » remplace « OÙ TU ES » : la pièce, sa posture et son occupation, ce
     qu'elle tient, ce qui est à portée et dans quel état avec les actions possibles, qui est là et ce qu'on y
     fait, ce qui a changé récemment par d'autres. Bornée par la saillance (ce qu'elle tient, puis ce qui est à
     portée, puis le reste).
   - Un lot d'outils `world`, en main dans les épisodes où elle parle (comme `room` aujourd'hui) : `go_to`
     (un lieu, une pièce, un objet, quelqu'un), `interact` (un objet, une action, une cible), `respond` (une
     demande qu'on lui fait), `gesture`. Le résultat dit ce qui est lancé ; l'issue arrive ensuite, et un échec
     lui parvient comme un signal (« tu n'as pas pu… »). Le vocabulaire reste **fermé côté modèle** : un
     identifiant est validé contre la définition en vigueur avant toute écriture (inventé → une erreur qui
     liste les choix possibles, rien d'écrit), un seul `go_to` par épisode, aller là où elle est déjà n'écrit
     rien (les règles de `move_to`, ADR 0049). Aller sur un lieu `bed` éveillée, c'est s'y asseoir ; s'y allonger
     est le coucher, ou un `lie` explicite.
   - Ce qui se passe dans le monde est un **signal** (`world.noticed`, forme `attention.Signal`) : dosé et
     habitué par l'attention comme les autres sens (ADR 0022) — quelqu'un entre, une tasse tombe, sa plante a
     changé de place. Ce qui lui est **adressé** (un geste vers elle, une demande) est une perception adressée
     : elle y répond comme à un message. Un geste se ressent selon qui le fait (la proximité, ADR 0013).

8. *Les personnes ont un corps.* Il est piloté par leur client ; le noyau ne retient que les **arrivées**
   (une pièce, le lieu le plus proche), jamais la trajectoire, relayée à 20 Hz aux autres clients sans passer
   par le journal. Leurs actions sur les objets sont instantanées pour le noyau et validées (proximité, accès,
   mains, état). Une pièce où plusieurs personnes se tiennent est un **salon** (ADR 0014) : elle ne dit rien de
   privé devant qui ne doit pas l'entendre.

9. *Le protocole `mika.world/1`* (`adapters/world/protocol.py`, spécification `docs/protocole-monde.md`) :
   WebSocket `/ws/world` ; des rôles (`viewer`, `host` par bail, `creator`) ; un client propose, le noyau valide,
   journalise et diffuse à tous, y compris à qui a proposé ; chaque trame diffusée porte son `seq` (trou →
   `sync`, retard trop grand → `snapshot`) ; chaque commande porte son `cmd` (accusé `result`, dédoublonnage) et
   peut porter `expect` (le `seq` sur lequel elle a été décidée : un état qui a changé → `stale`). Un client
   natif s'authentifie par un jeton de son compte ; un navigateur par sa session et son `Origin`. Les types sont
   publiés en schéma JSON (`json_schema()`), d'où le moteur génère les siens.

10. *Le créateur.* Une opératrice édite par lots écrits sur une révision (`edit`, `base`), qui passent en
    entier ou pas du tout (`apply_changes`) ; la prose (« la plante qu'Adrien t'a offerte ») passe par
    `describe` et devient un texte gardé (`Content`, `about`) que l'oubli atteint (ADR 0024). Les noms qu'elle
    lit sont courts et sans retour à la ligne : un nom ne peut pas imiter un titre de section. Le moteur dit ce
    qui lui manque pour charger une révision (`loaded`), la console l'affiche. Elle **remarque** ce qui change
    chez elle (un objet apparu, son lit déplacé).

11. *Ce qui est fait.*
    - **P0** : le contrat (`contracts/world.py`), les trames (`adapters/world/protocol.py`), un monde d'exemple
      (`examples/monde/chambre.json` : la chambre de l'ADR 0049 et un salon, des objets qu'on porte, un chat), la
      spécification, et leurs tests.
    - **P1, la faculté `world`** (`faculties/world/`) : la tranche (définition, acteurs, objets, actions en
      cours) ; un planificateur pur (`plan.py` : aller de lieu en lieu et de pièce en pièce, les mains, les
      surfaces, les contenants, les affordances, conclure en revalidant) ; deux outils en main, `go_to` (un lieu
      de l'énumération, une posture) et `interact` (un objet, une action, une cible) — `respond` et `gesture`
      attendent qu'il y ait des personnes dans le monde (P4) ; la section « AUTOUR DE TOI » (où elle est, ce
      qu'elle fait, ce qu'elle tient, ce qui est à portée, ce dont elle peut se servir ailleurs, avec les
      identifiants qu'attendent ses outils) ; le coucher et le réveil en réducteurs ; le processus `world.settle`
      qui conclut chaque action à son échéance ; l'état poussé aux écrans quand elle part quelque part ; une vue de
      console (« Son monde »). **Le monde chargé par défaut** (`faculties/world/chambre.json`) est sa chambre telle
      que l'écran la montre : les six lieux, les meubles de `room.glb` et ce qu'on peut en faire (ouvrir sa
      fenêtre, regarder dehors, dessiner à son bureau, arroser ses plantes…), **aucun objet portable** tant que
      le client web ne sait pas montrer ce qu'elle tient. `place` devient une vue de compatibilité : le type
      `place.moved` (relu par le monde) et les faits `place.current`/`place.since` (là où elle est, ou va),
      qu'`inner_state.place` sert toujours. Reportés : les baux de réservation (la revalidation à la conclusion tient lieu de garde tant qu'elle est seule), un schéma
      de `go_to` par épisode quand le monde sera édité (P5).
    - **P1 bis, le bureau** : un réducteur de `runtime.episode.started` — un pas sur un but ou une exécution de
      projet dans son mode à elle (`STEP`, `WORK` ; jamais `JOB`, impersonnel) — la fait aller au lieu `work`,
      s'asseoir et s'y mettre (le premier objet de ce lieu qui offre l'occupation `work`, `plan.work_desk`), sans
      modèle et sans événement de plus ; l'identifiant de l'intention dérive de l'événement, comme le coucher.
      Il rend visible une décision déjà prise et s'abstient quand elle dort ou est allongée, quand une action est
      en cours (la sienne, le coucher), quand une occupation à elle n'est pas finie (elle dessine : elle
      continue), et dans les minutes qui suivent sa dernière réplique à quelqu'un (`work_after_talk_min`,
      10 min). Elle y reste : l'occupation s'arrête d'elle-même après `open_activity_min`. Les écrans du chat
      reçoivent l'état par un effet sur le début de la séance, quand le monde a changé avec elle.
    - **L'interface de P2** : les commandes d'un client (`act`, `moved`, `address`, `answer`, `report`, `edit`,
      `describe`) sont des types du contrat (`w.Command`, `w.CommandResult`), que `protocol.py` porte tels quels
      sur le fil (le schéma JSON n'a pas changé) ; le port d'entrée les passe à `faculties/world/commands.handle`,
      qui rend un verdict (brouillons sous garde, ou refus) sans rien écrire. Déjà traité : l'hôte qui termine une
      action plus tôt (conclue par le noyau, pas crue sur parole) ou qui n'y arrive pas (seul ce qui est vrai
      change) ; le reste répond `unsupported` jusqu'à P4 et P5.
    - **Un premier éditeur** (de P5) : `edit` passe en entier ou pas du tout — une révision dépassée donne `stale`,
      un lot incohérent `incoherent` (la phrase du validateur), sinon `world.authored` sous la garde du monde
      inchangé. Il change les objets, les archétypes, la position et l'orientation d'un lieu qui existe ; pas les
      pièces, ni l'existence ou le reste d'un lieu (l'énumération de `go_to` est tirée du monde par défaut), ni
      les personnages (`unsupported`, tout dit d'un coup). Un objet resté à sa place suit son foyer édité
      (`plan.rehome`). Elle **remarque** ce qui a changé (`faculties/world/notice.py`) : un objet apparu, disparu,
      ou à elle et déplacé — de pièce, de lieu, de meuble, jamais de quelques centimètres ; un signal
      `world.noticed` (`kind` « change ») par objet, que l'attention dose (la pertinence part du seuil d'une pensée
      et monte avec la saillance, 0,6 fois pour ce qui n'est pas à elle ; une émotion légère), émis par le processus
      `world.notice` quand elle est éveillée — endormie, à son réveil. Un objet touché deux fois avant qu'elle le
      voie se remarque une fois ; un objet offert concerne qui l'a offert (`about`). La console (« Son monde »)
      montre les dernières éditions et ce qu'elle en a remarqué ; le créateur Unity recompare de lui-même un lot
      `stale`.
    - **P4, les personnes entrent** : un `viewer` accueilli fait entrer sa personne (`world.joined`, au lieu
      `spawn` de la pièce de Mika, par `MindPort.world_presence` : sa connexion, pas une commande) ; elle sort
      (`world.left`) quand sa dernière connexion se ferme ou se tait 60 s, et au démarrage personne n'est resté
      dans la pièce. `moved` est validé comme un constat de l'hôte. « AUTOUR DE TOI » dit qui est là et à quel
      lieu — le nom à la personne elle-même et devant qui peut entendre l'anodin sur autrui, « quelqu'un »
      sinon ; quelqu'un qui entre dans sa pièce est un signal (`arrival`), et dans Unity elle lève les yeux vers
      l'entrée. Une assise ne se prend qu'assis : quelqu'un debout près du bureau ne prend pas sa chaise.
      Les gestes (`address` portant un `gesture`) sont acceptés ; restent `act`, les demandes (`address` portant
      une `request`) et `answer`.

12. *La suite.*
    - **P1, la faculté `world`** : tranche, réducteurs, validation des actions, faits, section, outils,
      réflexes, terminaison sans hôte, vues de console — elle **reprend `place`**, avec qui le tient, et sans
      rien casser de ce qui est déjà au journal ou à l'écran :
      - le contrat `place` reste (type `place.moved` public, même nom) et `world` le réduit comme un
        déplacement de Mika : des `place.moved` existent dans les journaux dès le premier lancement, un
        événement orphelin serait refusé au rejeu ou ferait diverger l'état ;
      - le monde par défaut garde les six lieux de l'ADR 0049, mêmes identifiants et mêmes postures (`desk` et
        `bed` sont des assises ; `bed` + sommeil = allongée) ;
      - `inner_state.place` reste une chaîne simple, un état et non un ordre ; ce qu'on transmet en plus
        (destination et position courante, « en route ») prend d'autres clés.
    - **P2, l'adaptateur** : la route `/ws/world`, les rôles, le bail d'hôte, les jetons de client natif (aussi
      acceptés sur `/ws`), instantanés et rattrapage, débits.
    - **P3, les clients** : le client web en `viewer` (ses lieux viennent de la définition),
      un hôte Unity d'essai (charger, poser, jouer un trajet, prendre et poser un objet).
      Le client web ignore tout lieu inconnu de sa table (`roomLayout.ts`) : un lieu ajouté au monde sans
      géométrie côté client y est muet. Deux tables à garder égales à la main, c'est le défaut classique : la
      définition devient la source de ce qu'un client sans éditeur ne peut pas déduire (point d'approche,
      orientation, hauteur d'assise, pose couchée, emprises des meubles, bornes de la pièce, et le siège mobile
      — la chaise qu'on tire avant de s'asseoir et qui rentre quand on part : de la chorégraphie, pas de l'état,
      la chaise ne change pas de place dans le monde), en champs optionnels de `PlaceDef` et `RoomDef`, et
      `roomLayout.ts` la lit. D'ici là : mêmes identifiants des deux côtés, et `pos`/`facing` des six lieux
      recopiés de `roomLayout.ts` (recalé sur `room.glb`) dans `examples/monde/chambre.json`.
    - **P4, les personnes** : entrer, agir, gestes, demandes, perception et ressenti.
    - **P5, le créateur** : édition depuis le moteur, import et export d'un monde, console.
    - **Prérequis d'un client natif** : la voix part du noyau (synthèse et visèmes dans la trame `speech`) ; un
      moteur n'a pas la synthèse vocale d'un navigateur, et la règle « lettres → visèmes » ne doit exister
      qu'une fois.

**Conséquences.**
- Le journal grossit d'une action, pas d'une image : une intention et sa fin, une arrivée, un geste. Ce qui est
  continu (les poses) ne l'atteint jamais.
- Un seul hôte à la fois : simple et suffisant tant que le monde tient sur une machine ; plusieurs hôtes
  (un par pièce) seraient une révision de ce document, pas un correctif.
- Deux clients ne valent pas deux fois le travail : le client web a le droit d'être en retard, il ignore ce
  qu'il ne sait pas montrer.
- La surface d'injection reste fermée : les personnes n'envoient au monde que des identifiants et des codes
  (seule la conversation porte du texte libre, et elle passe par `/ws`) ; les noms sont bornés ; la prose est
  citée comme le reste de ce qui vient d'ailleurs.
- Décisions de l'utilisateur (2026-10-02) : **un seul monde** (des pièces s'y ajoutent) ; les personnages sont
  **animés par le moteur** d'abord (des personnages à esprit viendront sans changer le protocole) ; Mika pourra
  **faire entrer des objets** dans son monde, sur proposition approuvée comme ses mails (après P1) ; **plusieurs
  personnes à distance** : prévu par le protocole, pas une priorité (une personne à la fois, ou le même réseau).

Tests : `tests/unit/test_world_contract.py` (le monde d'exemple est cohérent et garde les six lieux de l'ADR
0049 ; chaque incohérence est refusée, tout est dit d'un coup ; une édition passe en entier ou pas du tout ; un nom
ne peut pas porter de retour à la ligne) et `tests/protocol/test_world_wire.py` (chaque exemple JSON de la
spécification se lit et respecte le schéma publié ; une trame inconnue ou un champ inconnu est refusé ; chaque
commande déclare ses rôles et son débit). P1 : `tests/unit/test_world_plan.py` (aller de pièce en pièce, s'asseoir, un lieu plein, les mains,
les surfaces et les contenants, ce qu'on tient se prend d'abord, une occupation à une chaise se fait assise,
conclure revalide — la tasse prise entre-temps), `tests/unit/test_world.py` (un trajet se conclut à son
échéance, regarder dehors et le dire, ouvrir sa fenêtre, s'asseoir pour dessiner, ce qu'elle invente ne s'écrit
pas et le refus dit ce qui se peut, allongée puis assise au réveil, le monde se rejoue, une édition sur une révision
dépassée ne passe pas) et `tests/unit/test_place.py` (les intentions de l'ADR 0049, tenues par le monde). Non vides
par mutation : un déplacement par épisode, le coucher dans la même transaction, la conclusion à l'échéance.
