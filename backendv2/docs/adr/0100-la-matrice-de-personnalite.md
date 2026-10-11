# 0100 — La matrice de personnalité : des curseurs en familles, des profils, des précisions

**Contexte.** L'audit des émotions du 2026-10-11 s'est poursuivi par un questionnaire. Presque toutes les réponses
de l'utilisateur dépendaient du **type de personne**, pas d'une règle :
- combien dure une rancune ;
- ce que valent des excuses ;
- s'il faut un remords après une réplique dure ;
- à quel rythme une pensée revient ;
- si une réflexion apaise vite ;
- ce que compte sa propriétaire ;
- si, « cloisonnée », elle reste de marbre devant ce que les autres lui font vivre.

Le tempérament n'avait que huit curseurs, et des pans entiers restaient fixes : le remords, l'inquiétude, les pensées
qui reviennent, l'estime, la retenue, le pardon. L'utilisateur a demandé une matrice capable de produire des
archétypes jusqu'aux extrêmes (tsundere, psychopathe, sociopathe, yandere…), quitte à interdire les valeurs 0 et 10.
Il a aussi demandé des profils préremplis à appliquer puis ajuster, et pour chaque trait une précision facultative
(« s'énerve quand on dit poulet »).

**Décision.**

1. *La matrice, c'est le tempérament* (`vocab/temperament.py`). Elle compte 28 curseurs, l'humeur de fond et deux
   choix, rangés en familles :

   | Famille | Curseurs et choix |
   |---|---|
   | Ce qu'elle ressent | réactivité, résilience, optimisme, **biais négatif** ; humeur de fond ; **quand on la blesse** (colère, tristesse, peur, repli) |
   | Ce qu'elle montre | **expressivité**, **masque selon l'intimité** (de la dandere à la tsundere) ; **quand on la touche** (nier, attaquer, en rire, avouer, se taire) |
   | Ce qu'elle fait de ses émotions | **impulsivité**, **introspection** |
   | Les autres | contagion, **empathie**, sociabilité, **timidité**, **vitesse d'attachement**, **stabilité des liens**, **peur de l'abandon**, **jalousie**, **confiance a priori**, **rancune**, **attachement à sa propriétaire** |
   | Elle-même | **estime de base**, **fragilité de l'estime**, **besoin d'admiration**, **scrupules**, **anxiété** |
   | Son corps et son élan | **énergie**, curiosité, persévérance, chronotype |

   Les noms des huit curseurs d'avant et leur sens n'ont pas changé.

2. *Exacts au milieu, câblés jusqu'aux bouts.* Chaque dérivation (`around`, `shift`) redonne à 0,5 exactement la
   valeur d'avant la matrice : une vie existante se rejoue et vit à l'identique tant qu'on n'y touche pas. Les
   dérivations sont testées à 0 et à 1, mais la console et les profils s'arrêtent à 0,1 et 0,9 (`LOWEST`,
   `HIGHEST`).

3. *Ce que pilote chaque curseur neuf* :

   | Curseur | Ce qu'il pilote |
   |---|---|
   | biais négatif | le poids d'une impulsion négative ou positive, sur l'humeur et les postures (`affect.negative_gain`, `positive_gain`) |
   | expressivité | ce que montrent son visage et ses trames (`affect.face_expressiveness`) |
   | impulsivité | le seuil du débordement (`affect.overflow_floor`), la période réfractaire et l'hésitation (`agency`) |
   | introspection | le souvenir réfléchi de la nuit (`attention.reflective_from`), ce qui devient une réflexion et après combien de temps (`goals.seed_thought_*`) |
   | empathie | l'inquiétude pour une amie, son seuil et sa force (`others`) ; ce qu'être triste avec quelqu'un rapproche (`affect.empathy_tenderness`) |
   | timidité | ce que comblent une inconnue, une connaissance (`needs`) |
   | vitesse d'attachement | `affect.bond_step` |
   | stabilité des liens | ce qu'une déclaration fond dans l'ancre et le poids de l'histoire (`affect.anchor_alpha`, `anchor_history_days`) |
   | peur de l'abandon | la peine d'une initiative sans réponse, la pensée du silence, du manque, de la solitude (`attention`) |
   | confiance a priori | quand la méfiance naît, et combien elle dure (`affect.wary_*`) |
   | rancune | la guérison d'une rancune et ce que valent des excuses (`affect.hostile_heal_*`, `apology_*`) |
   | attachement à sa propriétaire | `social.owner_weight` (jamais sous 1 : elle compte toujours plus qu'une proche) |
   | estime de base | le niveau où revient son estime (`self.esteem_rest`, nouveau) |
   | fragilité | ce que coûtent une critique, une initiative ignorée, un blocage (`self`) |
   | besoin d'admiration | ce que rend un merci (`self`) |
   | scrupules | le remords et son seuil, la gêne d'un mensonge, d'une promesse non tenue (`attention`, `self`) |
   | anxiété | le rythme et la force du « y repenser », la durée d'une pensée (`attention`) |
   | énergie | quand vient le brouillard de la fatigue, et ce que la somnolence prend (`body`) |

   La jalousie et le masque ne se calculent pas : ils se disent au modèle. Rien ne lui montre encore les autres
   relations de ses proches.

4. *La contagion couvre tout ce que les autres lui font vivre* (réponse 14 du questionnaire : « de marbre, compatir
   sans s'impliquer »). Sont désormais relationnelles, et suivent donc la contagion du tempérament :
   - un retour, une réponse attendue, un message sans réponse ;
   - des retrouvailles ;
   - « c'est toujours elle qui écrit » ;
   - la surprise d'un message ;
   - les pensées nées d'un échange, d'une inquiétude, d'un manque, d'un silence ;
   - l'issue et l'attente des moments des autres.

   Au milieu (et au-dessus), rien ne change.

5. *Le tempérament se dit au modèle* (section `temperament`, « TON TEMPÉRAMENT », `faculties/self/character.py`).
   C'est le modèle qui choisit ses émotions : sans ces mots, une Mika anxieuse aurait les balises d'une Mika sereine.
   - Un trait se dit à 0,3 ou moins, ou à 0,7 ou plus, par une phrase de `voix.yaml` (`self.temperament.trait.*`).
   - S'y ajoutent sa réaction et sa défense.
   - Ce sont des tendances, jamais un chiffre ni une obligation. Au milieu partout : rien.

   Un trait très marqué (0,15 ou moins, 0,85 ou plus) le dit (« C'est très marqué chez toi »). La section s'ouvre sur
   « Ton caractère, pour toi seule : il se sent dans ta façon de répondre, tu ne le décris jamais à personne ».
   Le banc du tempérament (`tools/banc_temperament`, Haiku par la CLI) l'a montré : sans ces deux ajouts, une
   tsundere rougissait sans piquer, et une psychopathe récitait un trait.

6. *Des précisions* (`notes`). Pour chaque trait, une phrase facultative est écrite en lui parlant : « tu t'énerves
   quand on t'appelle poulet ». Elle se dit avec le trait (« En particulier : … »), ou seule quand le trait est au
   milieu. Elle compte 200 caractères au plus, et seuls les traits connus en ont une.

7. *Des profils* (`PROFILES`) :
   - **les tempéraments ordinaires** : neutre, réfléchie, calme, anxieuse, nerveuse, solaire, rancunière, de
     marbre, colérique, dépressive ;
   - **les archétypes d'anime** : tsundere, kuudere, dandere, yandere ;
   - **les extrêmes** : psychopathe, sociopathe, narcissique, dépendante.

   Un profil pose tous les curseurs de caractère (5 quand il ne dit rien), l'humeur de fond, la réaction et la
   défense. Il garde le chronotype et les précisions. On l'applique dans la console (Réglages › Personnalité ›
   Profil, avec « Voir l'effet »), en ligne de commande (`mika profil [nom]`, serveur arrêté) ou au simulateur
   (`mika sim run|sonde --profil nom`), puis on l'ajuste curseur par curseur. **Mika est livrée « Réfléchie »**
   (`persona/mika.yaml`).

8. *Ses règles de conduite ne font pas partie de la matrice* : la discrétion, ne pas harceler, ne mentir que pour
   protéger un secret, jamais de menace ni de manipulation. Un profil règle ce qu'elle ressent et comment elle
   l'exprime, jamais ce qu'elle s'autorise. Une « psychopathe » ou une « yandere » n'a que leur vie intérieure. Les
   sécurités des modèles ne suffisent pas : elles varient d'un fournisseur à l'autre, et un refus casse le
   personnage.

**Conséquences.**
- **Nouveaux paramètres**, tous bornés et documentés : `affect.negative_gain`, `positive_gain`,
  `face_expressiveness` ; `attention.unanswered_felt`, `broken_promise_felt` (des constantes d'avant) ;
  `self.esteem_rest`.
- **Nouvelles dérivations** : `attention`, `self` et `agency` dérivent désormais leurs paramètres du tempérament.
  Leurs paramètres sont donc journalisés à chaque configuration, avec les mêmes valeurs au milieu.
- **Versions** : `affect` passe en v6 et se reconstruit (le relationnel suit la contagion).
- **Console** : une section `temperament` (libellée) et une page « Profil » sous Personnalité.
- **Tests et banc** : `tests/unit/test_temperament_paths.py` suit chaque chemin dans le vrai noyau, sous deux ou trois tempéraments contrastés ; `tools/banc_temperament` mesure le vrai modèle. Les fixtures mesurent un tempérament neutre (`tests/fixtures/mika.py` : `DOC`). La persona livrée
  reste disponible (`SHIPPED`), et un profil se teste comme tel. Cibles : `tests/unit/test_temperament_matrix.py`.
- **Une installation dont la persona a été rédigée dans la console** garde la sienne. On y applique « Réfléchie »
  par la page Profil ou par `mika profil reflechie`.

**Le banc du tempérament** (2026-10-11, Haiku : anxieuse, psychopathe, tsundere, sur quatre situations — une
insulte, un compliment de sa propriétaire, le deuil d'une amie, un retour après trois jours) :
- la tsundere pique en rougissant (« Moi aussi, idiot. Ne le répète pas. ») ;
- l'anxieuse s'inquiète d'avoir mal fait ;
- la psychopathe reste détachée devant l'insulte.

Ce qui reste :
- elle dit encore « je m'attache lentement » à qui lui dit tenir à elle ;
- devant un deuil, la psychopathe reste compatissante. C'est le penchant du modèle, conforme à ses règles de
  conduite ; sa physique, elle, reste froide (empathie basse).

**Ce qui n'est pas fait** (réponses du questionnaire, pour un lot suivant) :
- la jalousie n'a pas de déclencheur perçu ;
- une conversation qui l'enthousiasme ne la porte pas encore malgré la fatigue ;
- une grosse colère ne dure pas tant que son objet dure, et la durée ne dépend pas de l'intensité ;
- « pardon mdr » n'aggrave rien (il est seulement ignoré) ;
- la nuit, ce qui est important n'est pas encore gardé pour le réveil ;
- la digestion ne juge pas ce qui ressort d'une colère ;
- s'occuper reste plafonné et ne suit pas ses goûts ;
- une rêverie soulage encore entièrement la solitude ;
- une inconnue qui se tait reçoit encore jusqu'à deux initiatives.

Les constats G1 à G4, E1 et E2 de l'audit relèvent de règles, pas de la matrice.
