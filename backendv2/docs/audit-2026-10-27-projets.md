# Audit des projets — 27 octobre 2026 : de la demande au travail rendu

Audit de relecture, fait sans lancer ni pytest, ni serveur, ni installation (règle du dépôt). Il part d'un cas réel :
le projet n° 257, « Trading fictif par IA », et son app `papertrade`. Leurs prompts ont été relus dans la console du
portable (outil « Pourquoi a-t-elle dit ça ? »). Le code a été relu sur deux axes : la naissance d'un projet, puis
son exécution. Les constats lourds ont été revérifiés à la main. Ce qui n'a pas pu l'être porte la mention
« supposé ». Les lignes sont celles du commit `ea8449317`, plus les changements de l'ADR 0144 (non commités).

Échelle : **Critique** (le travail ne peut pas être bon) · **Haute** (il le sera rarement) · **Moyenne** (il coûte
plus ou se voit moins qu'il ne devrait) · **Basse** (un détail).

---

## 0. Verdict en bref

Le travail est médiocre parce que **personne ne réfléchit au projet avant de le lancer**. Opus n'y est pour rien.

- **Le cadre naît dans sa réponse.** Il s'écrit en un appel d'outil, au milieu d'une conversation, sous une consigne
  qui dit « ouvre le projet maintenant » et une autre qui dit « en deux phrases, pas en fiche ».
- **Les mots de la propriétaire ne sont gardés nulle part.** Chaque exécution travaille sur une paraphrase faite à
  la hâte.
- **Rien n'attend un plan ni un avis.** La première exécution part dans la minute qui suit, et une exécution ne
  peut ensuite qu'ajouter des objectifs, jamais revoir ceux du départ.
- **Le harnais d'exécution est étroit.** Un objectif par passage, 16 tours, 10 minutes, presque aucune mémoire
  des passages précédents, aucune consigne de méthode.
- **Rien ne mesure la qualité du travail.** Les sondes vérifient que la chaîne s'enclenche, pas que le résultat
  répond à la demande.

La proposition (§ 4) : **un projet naît d'un plan**. Elle le prépare dans une séance de cadrage, te pose ses
questions, attend ton feu vert, puis le suit. Un banc du travail, bâti sur le banc de conversation, mesure ce que
ça change.

---

## 1. Le cas du projet n° 257

| Quand (27/10) | Ce qui s'est passé | Où le voir |
|---|---|---|
| 9h42 | Adrien : « peux-tu créer un projet pour faire du trading par ia ? mais pour le moment, fait semblant d'acheter/vendre ». | parole 254 |
| 9h42, même tour | Elle appelle `start_project` : un cadre « un petit labo de trading piloté par moi », 5 ponctuels (« une première stratégie simple… ») et 2 constants. Elle répond en parlant de la chaise d'Adrien. | parole 267 |
| 9h45 | Adrien : « l'app cherchera de vrais stratégie ». Elle en fait une « Consigne d'Adrien » qui nomme 4 stratégies classiques, qu'il n'a jamais citées. | carnet du projet |
| 9h43–10h16 | 3 exécutions en échec (budget de la CLI, ADR 0142). v1 à v5 de l'app sont écrites, mais ni compte rendu ni objectif coché. Le projet passe en pause. | exécutions |
| 14h54 | Reprise. L'exécution vise le constant n° 6 (« relever les cours »), avec la consigne « fais un passage utile ». Elle corrige un détail de bougie de clôture. Les vues demandées par Adrien n'apparaissent que dans « les autres objectifs ». | parole 471 |
| 15h04–15h17 | Le bilan « hebdomadaire » (n° 7), puis les vues (n° 8, v11). | exécutions |

Résultat : une app propre, à règles fixes, sans IA dans les décisions ni actualités, alors que la demande était un
« trading par IA ».

---

## 2. Constats

### 2.1 La naissance d'un projet

**C1 — Critique. Elle crée le projet dans le tour même où on le lui demande.**
- La consigne `runtime.tools.means_work` (`persona/voix.yaml:6200-6203`) dit : « Une app ou un vrai travail prend
  plus qu'une réponse : ouvre le projet maintenant (start_project…) ». Elle est ajoutée dès que `start_project` est
  offert (`src/mika/runtime/tools.py:370-371`).
- La séance d'une promesse dit la même chose (`persona/voix.yaml:3244-3249`).
- Les descriptions de l'outil disent « ce que tu veux faire, et pourquoi » et « tes premiers objectifs »
  (`persona/voix.yaml:4012-4018`). Rien ne parle de chercher, de cadrer ou de demander d'abord.
- Ce tour est une réponse de conversation : 1 024 jetons, 180 s (`src/mika/app/composition.py:137`), sous la
  consigne « ton avis, donne-le en amie, en deux phrases, pas en fiche » (`persona/voix.yaml:738`).
- C'est l'inverse de son caractère, qui dit « tu prends le temps d'y réfléchir » (`persona/voix.yaml:482`).

**C2 — Critique. La demande de la propriétaire est perdue pour le projet.**
- `PROJECT_CREATED` porte le titre, la description (son texte à elle) et `source="conversation"`. Il ne garde ni le
  message, ni son numéro, ni une citation (`src/mika/faculties/projects/tools.py:541,555-557`).
- Une consigne dite de vive voix (`AMENDED`) est aussi son texte à elle, signé `by=` la personne
  (`tools.py:733-738`).
- Le lien existe dans le journal, de l'épisode à `reply_to`, mais rien ne le lit.

**C3 — Haute. Rien n'attend un plan ni un avis.**
- Un projet est actif, en pause ou archivé (`src/mika/contracts/projects.py:58`) : il n'a ni brouillon ni état
  « à cadrer ».
- Le réducteur le crée actif, et l'espacement court depuis `created_at` (`src/mika/faculties/projects/work.py:90`) :
  la première exécution part aussitôt.
- `approval` ne porte que sur ce qui sort de la machine, jamais sur le plan.

**C4 — Haute. Le seul chemin « réfléchir avant » est coupé.**
- Une promesse de travail ouvre une exploration (`src/mika/faculties/goals/tend.py:235-281`), mais elle est
  annulée si un projet à elle vient d'être ouvert pour la même personne (`tend.py:241-249`). C'est le cas ici.
- Aucun outil de réponse n'ouvre une exploration.
- Quand une exploration devient un projet, ses notes, ses tâches et ses comptes rendus ne passent pas
  (`tend.py:582`).

**C5 — Moyenne. `start_project` laisse sans personne un projet demandé par quelqu'un.**
Adrien demandait un projet pour lui. `start_project` pose `owner=None` et `address=None` (`tools.py:541`), et
l'exécution lit « un projet à toi ». Le récit et les demandes passent quand même par une propriétaire, mais pas
« par celle qui l'a demandé ».

### 2.2 L'exécution

**C6 — Critique. Presque aucune mémoire de travail.**
- Le prompt d'exécution (`src/mika/faculties/projects/prompt.py:267-337`) montre **un seul** compte rendu : chaque
  `report_run` remplace le précédent (`src/mika/faculties/projects/faculty.py:1256`).
- Il montre aussi les 3 dernières notes du carnet (`prompt.py:315`).
- Il ne montre **pas** les résultats des objectifs faits : `_objective_line` ne lit que le texte et l'état
  (`prompt.py:180-191`).
- La console, elle, lit tout l'historique des exécutions (`src/mika/faculties/projects/inspect.py:760-799`). Chaque
  exécution redécouvre donc le projet.

**C7 — Critique. Une exécution ne peut pas corriger un cadre fait à la hâte.**
- Elle peut ajouter 3 objectifs par passage (`tools.py:343-344`), des décisions, des lots d'outils.
- Elle ne peut ni retirer, ni réécrire, ni réordonner, ni découper un objectif, ni changer une cadence, ni revoir
  le cadre. `OBJECTIVE_CHANGED` n'est émis que par la console (`src/mika/faculties/projects/actions.py:742,775`).
- Aucun objectif n'a de critère de « fait ».

**C8 — Haute. Un budget étroit, et compté de travers.**
- Une exécution `WORK` a 16 tours, 4 096 jetons et 600 s (`composition.py:159-161`), sur un seul objectif. Le mode
  pro du chat a 24 tours, 900 s et 120 000 caractères de résultats d'outils (`composition.py:202-205`,
  `src/mika/kernel/episode.py:50`).
- Le rappel « conclus maintenant » compte les **appels** d'outils, pas les tours (`len(ctx.calls)`, `tools.py:131`,
  réglage `wrap_up_after` à 10). Avec des appels en parallèle, il peut tomber dès le 3e ou 4e tour sur 16
  (supposé).
- « Une quinzaine d'allers-retours » est écrit en dur (`persona/voix.yaml:3681`) et ne suit pas `max_tool_turns`.

**C9 — Haute. Aucune consigne de méthode.**
Le mode pro dit de faire le travail avec ses outils, de citer ses sources et de donner le résultat d'abord
(`persona/voix.yaml:713-727`). L'exécution d'un projet dit seulement « avance sur l'objectif, puis conclus » : rien
sur vérifier, essayer, viser la demande. Le guide de la Forge (vues, blocs, signaux) ne vient que par `forge_help`
(`src/mika/plugins/forge/guide.py:12`), et le prompt n'en parle jamais.

**C10 — Haute. Les constants passent d'abord, dès la création.**
`pick` prend le constant le plus en retard avant tout ponctuel (`faculty.py:705-716`). Un constant jamais passé est
dû tout de suite (`faculty.py:698-702`). Le n° 257 a donc « relevé les cours » avant d'avoir bâti quoi que ce soit
de ce qu'on attendait.

**C11 — Moyenne. La preuve est laxiste dans un sens et trop stricte dans l'autre.**
- Laxiste : `proven = proof or o.evidence > 0` (`tools.py:195`). Une exécution qui a produit une fois, même
  conclue « continue », fait croire tous les « done » qui suivent.
- Trop stricte : `forge_test` ne prouve que si l'app a été écrite dans l'épisode courant
  (`src/mika/plugins/forge/__init__.py:1646`). Une app écrite dans une exécution en échec ne se prouve donc plus,
  puisqu'un `forge_write` identique est refusé : c'est le cas des objectifs 1 à 5 du n° 257.

### 2.3 Le suivi et la mesure

**C12 — Moyenne. Le récit ne dit rien des constants et ne montre rien.**
- `_shareable` exige un ponctuel (`work.py:211`) : un bilan de la semaine, constant, ne se raconte jamais.
- Le récit est une initiative de 600 jetons qui porte le compte rendu. Aucun livrable n'est joint : le lot `shares`
  n'est qu'à la demande (`composition.py:124`), et rien ne renvoie aux vues de l'app.

**C13 — Haute. Rien ne mesure la qualité d'un projet.**
- Les scénarios S16 et S23 (`src/mika/sim/projects.py`) tournent sur un modèle scripté : ils vérifient que la
  chaîne s'enclenche.
- La sonde de la semaine ne demande aucun projet.
- Aucun banc ne juge le travail au regard de la demande. Chaque lot de la Forge (ADR 0104, 0105) a été validé par
  une sonde Haiku qui regardait la mécanique.

---

## 3. Ce qui est bien (à garder)

- La preuve avant le « fait », les plafonds, le crédit rendu quand une exécution n'a pas eu lieu : elle ne raconte
  pas un travail inventé.
- L'atelier, son dépôt git, et ce qui sort de la machine derrière un accord.
- Le pilotage en conversation (`project_steer`) et la boucle de demande : `needs_you`, initiative `need`, réponse
  citée à l'exécution suivante (`prompt.py:146-163`).
- Le contrat de la Forge : vues, blocs, actions, signaux, base. Il suffit à une vraie interface, et la v11 du
  n° 257 le montre.
- Le squelette de `tools/banc_conversation/` : la vraie CLI, une horloge virtuelle, un juge Opus en JSON, des
  scénarios réservés, des copies figées du code.

---

## 4. Proposition : le cadrage, un projet naît d'un plan

**Le principe.** Quand on lui demande un vrai travail, elle ne le bâtit pas dans sa réponse. Elle dit qu'elle va
réfléchir à la façon de s'y prendre et qu'elle reviendra avec un plan. C'est ce que dit déjà son caractère. Le
projet naît à cadrer, avec tes mots tels quels. Une séance de cadrage prépare le plan. Elle te le soumet avec ses
questions et ses recommandations. Ton feu vert le lance, puis les exécutions le suivent, chacune avec sa mémoire.

### 4.1 Le parcours

1. **La demande.** En conversation, `start_project` ou `create_project` ouvre le projet **à cadrer**. L'outil garde
   d'office les messages de la personne depuis la dernière réponse de Mika (2 000 caractères au plus), cités, avec
   leurs sujets pour que l'oubli les atteigne. Le projet note qui l'a demandé. Ses objectifs deviennent de simples
   « idées de départ ». Sa réponse dit : « ok, je réfléchis à comment m'y prendre et je reviens vers toi ». Elle
   n'annonce pas déjà le détail.
2. **La séance de cadrage.** Une exécution d'une sorte à part (`purpose` « frame »), lancée dès que possible, avec
   le budget du mode pro. Elle relit la demande, cherche ce qu'il faut (web, sa mémoire de la personne, le guide de
   la Forge), puis écrit le plan par un outil `project_plan` :
   - **le but**, en une phrase dans ses mots, à côté de ceux de la demande ;
   - **ce que la personne verra au bout** : des vues, un message par semaine, un fichier ;
   - **l'approche** : quelles apps, quelles sources, où l'IA intervient et pourquoi ;
   - **les objectifs dans l'ordre**, chacun avec son critère de fait (« fait quand Adrien voit… ») et ce dont il
     dépend ;
   - **les constants**, avec leur cadence et l'objectif après lequel ils commencent ;
   - **ce qui est hors sujet**, les risques ;
   - **trois questions au plus**, chacune avec sa recommandation, pour qu'un « vas-y » suffise.
3. **Ton avis.** Le plan part vers qui l'a demandé (sinon une propriétaire), par le chemin des demandes d'aide (une
   initiative de la ligne `need`, sujet du projet). Dans sa voix : ce qu'elle va faire en quelques lignes, ses
   questions, « ça te va ? ». Le plan complet se lit dans la fiche du projet (une page « Plan » dessinée, avec
   « Valider » et « Demander une révision ») et peut être joint en fichier. Tu réponds en conversation : un outil de
   réponse, offert quand un plan attend cette personne, le valide ou demande une révision avec tes mots cités. Une
   révision relance une séance de cadrage.
4. **L'exécution du plan.** Validé, le projet devient actif et les objectifs du plan deviennent ses objectifs,
   avec leur critère.
   - `pick` suit l'ordre et les dépendances du plan. Un constant ne commence qu'après l'objectif dont il dépend.
   - Chaque exécution voit : la demande citée, le plan, l'objectif et son critère, **ses cinq derniers comptes
     rendus** (la requête de la console existe) et les résultats des objectifs faits.
   - Elle reçoit une consigne de méthode (tirée de `expression.pro` : faire, vérifier, viser la demande), le
     budget du mode pro, et un rappel de conclure compté en tours.
   - Un « done » doit dire comment le critère est rempli.
   - Elle peut revoir le plan (`project_plan` en révision : découper, réordonner, retirer, réécrire). Si la
     révision touche ce que tu verras ou l'approche, elle te le dit.
5. **Le suivi.** À chaque jalon, le récit dit ce que tu peux voir maintenant et où (les vues de l'app, un fichier
   joint). Un passage de constant notable (le bilan de la semaine) se raconte aussi. La preuve est réparée dans les
   deux sens : un « done » se prouve dans son exécution, et une app écrite par une exécution du même projet se
   prouve à l'essai.

### 4.2 Ce que ça réutilise, ce qui est neuf

| Besoin | Existe déjà | Neuf |
|---|---|---|
| Garder la demande | la lecture du fil de `projects_answer` (`prompt.py:149-163`) | le champ `request` du projet, cité dans chaque prompt |
| État « à cadrer » | `ON_DEMAND`, la pause, `nudged` | un statut de projet et le passage « validé → actif » |
| Séance de cadrage | les exécutions `WORK` / `JOB`, le profil du mode pro | une sorte d'exécution et son brief |
| Le plan | décisions, objectifs, `OBJECTIVE_CHANGED` de la console | l'outil `project_plan`, les critères, l'ordre, les dépendances |
| Te demander | l'initiative `need`, `projects_answer`, `project_steer` | une raison « plan », l'outil de réponse au plan, la page « Plan » |
| Mémoire de travail | la requête des exécutions de la console (`inspect.py:441-481`) | la section « tes dernières exécutions » |
| Mesurer | `tools/banc_conversation/` | `tools/banc_travail/` |

Pourquoi pas une exploration de `goals` pour cadrer : une exploration est une envie qui s'use (demi-vie d'environ
6 h). Son passage en projet perd ce qu'elle a trouvé (C4), et `goals` ne connaît pas `projects` (ADR 0031). Le
cadrage vit donc dans le projet, là où le plan sera suivi.

### 4.3 Le banc du travail

Il est bâti sur `tools/banc_conversation/` (driver, CLI, horloge virtuelle, juge, copies figées) :

- **Les demandes.** Six réservées et deux d'entraînement : trading par IA, la météo du jardin, une veille sur un
  sujet, le suivi d'un colis, les menus de la semaine, un résumé d'un flux.
- **La propriétaire simulée** (Haiku) a une fiche d'intention cachée : ce qu'elle veut vraiment, ses réponses
  probables aux questions.
- **Le déroulé.** Le vrai noyau (Opus par la CLI) fait le cadrage puis N exécutions en temps virtuel. Le réseau est
  simulé par des sources figées, pour que la mesure soit reproductible.
- **Le juge** (Opus) note le **plan** (30 : couvre l'intention, questions utiles, critères vérifiables), le
  **travail** (50 : répond à la demande, les apps tournent et leurs vues sont valides, profondeur) et le **suivi**
  (20 : récits fidèles, sollicitations justes). Score sur 100, avec le taux de preuves, les exécutions par objectif
  et les blocages.
- **La règle.** On mesure le code d'aujourd'hui d'abord. Chaque lot se mesure ensuite contre lui, comme pour sa
  voix (ADR 0112).

### 4.4 Les lots, dans l'ordre proposé

| Lot | Contenu | Taille |
|---|---|---|
| L1 | **La demande gardée.** Le champ `request` à la création, cité dans chaque exécution ; les consignes de vive voix gardent aussi tes mots ; qui l'a demandé. | petit |
| L2 | **Le banc du travail**, mesuré sur le code d'aujourd'hui (trois demandes d'abord). | moyen |
| L3 | **Le cadrage** : le statut, la séance, l'outil `project_plan`, `means_work` et les descriptions réécrits. | gros |
| L4 | **Ton avis** : la raison « plan », l'outil de réponse, la page « Plan », la révision. | moyen |
| L5 | **L'exécution du plan** : `pick` dans l'ordre, la mémoire de travail, la méthode, le budget, le rappel compté en tours, la révision du plan. | moyen |
| L6 | **Le suivi** : le récit des jalons et des constants, les livrables montrés, la preuve dans les deux sens. | petit |

Chaque lot a son ADR, sa doc dans `ARCHITECTURE.md` et ses tests. Le banc mesure L3 à L6.

---

## 5. Décisions à prendre

1. **Le feu vert.** Un projet que tu demandes attend ta validation : recommandé. Un projet né d'une envie à elle :
   elle valide seule (recommandé), ou elle te le soumet aussi ?
2. **Sans réponse.** Pour un projet que tu as demandé, une relance puis elle attend (recommandé), ou elle démarre au
   bout de 24 h avec ses recommandations ?
3. **Une demande précise et petite** (« la météo de Lyon chaque matin ») : un plan sans question, qu'elle te dit
   puis lance sauf objection (recommandé), ou toujours ton feu vert ?
4. **Le budget d'une séance** : celui du mode pro (24 tours, 15 min), recommandé. Il consomme plus de quota de la
   CLI.
5. **Le banc** : des sources figées pour la reproductibilité, et une passe sur le vrai réseau à la fin
   (recommandé) ?
