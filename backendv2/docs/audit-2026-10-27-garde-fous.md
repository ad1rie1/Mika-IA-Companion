# Les garde-fous du code : ce qui décide à sa place — 27 octobre 2026

Relecture faite sans lancer ni pytest, ni serveur, ni installation (règle du dépôt). Les numéros de ligne sont ceux du
dépôt au commit `ff507390b` ; ceux de `faculties/projects/` bougent encore (une autre session y travaille).

**La question.** Où le code fixe-t-il une réaction en dur (un seuil, une liste de mots, une règle tout ou rien, un
texte hors de sa voix), et lesquels de ces garde-fous vont contre l'objectif : que le modèle réagisse de lui-même, sans
qu'on lui impose un comportement ? C'est le principe de l'ADR 0141 (« informer, pas ordonner »), porté du prompt au
code.

**État, le 2026-10-28.** Le lot 1 est codé : ADR 0147 (§ 2.1), 0148 (§ 2.3, corrigé au codage), 0149 (§ 2.2) ; son
codage a relevé deux émotions fixées de plus, ajoutées au tableau A (RSS, caméra). Le lot 2 est codé : ADR 0150 (§ 3) ;
quatre lignes du tableau A ont changé de famille en le codant (dites au § 3).

**Déjà réglable, donc hors de ce document :** les `Knob` des facultés et des plugins, les 28 curseurs du tempérament
(seuls les coefficients de dérivation sont en dur), les règles d'accès de la console (ADR 0131–0134). `persona/voix.yaml`
se change dans le fichier, avec un redémarrage.

---

## 1. Le tri

Une centaine de constantes, de listes et de règles relevées dans `faculties/`, `plugins/`, `runtime/`, `vocab/` et
`kernel/` se rangent en quatre familles. Seule la première va contre l'objectif.

### A. Ce qui décide à la place du modèle : à lui rendre

Ni statique ni réglable : on retire la règle et on donne l'information au modèle. Le moteur s'y prête : l'arbitre est
probabiliste (`λ_max · σ(score)`, ADR 0003) et elle peut toujours répondre `[SILENCE]`. Les chemins partent de
`src/mika/`.

| Où | Ce que le code tranche | Lot |
|---|---|---|
| `plugins/email/poll.py:47`, `:135` ; `plugins/teams/triage.py:33`, `:148` | Le tri ne peut rendre que six émotions (jamais la colère), à une intensité fixée à `0,2 × importance` | **1** (fait : 0147) |
| `plugins/rss/__init__.py:336` ; `plugins/camera/__init__.py:152` | Un titre qui la touche la rend toujours « curieuse », à `0,25 × score` ; ce que voit la caméra, « curieuse » à 0,15 (relevé au codage du lot 1) | 3 (caméra faite : 0153) |
| `faculties/others/faculty.py:515`, `:644`, `:864`, `:943`, `:1005`, `:1055`, `:1095` ; `faculties/attention/faculty.py:822`, `:1460` ; `faculties/attention/watch.py:222`, `:557` ; `faculties/needs/__init__.py:948`, `:964` ; `faculties/agency/__init__.py:485` | Porte `in (FRIEND, CLOSE)` : l'inquiétude, la prise de nouvelles, encourager, fêter, le mot de deuil (proche seulement), le remords, la jalousie, le manque, la joie du retour et la relance n'existent pas pour une connaissance | 2 (fait : 0150, sauf le manque) |
| `faculties/others/faculty.py:560` | `CONTAGION_BY_CLOSENESS` : l'humeur d'une inconnue ne la colore jamais | 2 (fait : un réglage) |
| `faculties/social/initiative.py:304` | Veto `GRUDGE` total : pas même un bonjour une fois le seuil franchi | 2 (fait : 0150) |
| `faculties/attention/faculty.py:613` ; `faculties/social/faculty.py:405` | Coupures dans la dérivation : aucune jalousie d'un silence sous 0,5 du curseur, jamais « sa journée » au milieu du curseur ou en dessous | 2 (fait : 0150) |
| `faculties/self/greeting.py:33` ; `faculties/goals/tend.py:244` | Une inconnue reçoit toujours le bonjour simple ; seule une promesse faite à la propriétaire devient un travail | — (reclassés, § 3) |
| `faculties/goals/tend.py:103` | `SEEDING_EMOTIONS` : ni la colère, ni le dégoût, ni la joie ne font naître une exploration | 2 (fait : 0150) |
| `faculties/memory/extraction.py:872-928` | `_IMPORTANT` force l'importance à 0,7, une date douloureuse à 0,95, quoi qu'en dise le modèle | 3 (fait : 0153, avec `_FESTIVE` et `_YEARLY` ; la date douloureuse reste) |
| `faculties/memory/extraction.py:955` ; `faculties/memory/recall.py:468` ; `faculties/memory/life.py:85` | Échos par mots : deux mots en commun avec un secret font un secret, un radical commun avec un sujet délicat fait une confidence, un radical commun tient un moment pour repris | 3 |
| `faculties/memory/recall.py:109` | `PHATIC` (« comment », « pourquoi », « souvenir ») : un message fait de ces mots ne réveille aucun souvenir | 3 |
| `faculties/social/profile.py:110-149` ; `faculties/goals/tend.py:121` | Regex de la fiche (`SITUATION`, `_AGE`, `_WORRY`) ; une recommandation reconnue en français seulement (`RECOMMENDS`) | 3 (`SITUATION` assoupli : 0153) |
| `faculties/body/__init__.py:236` | `_URGENT` : l'urgence qui la réveille la nuit, devinée par des mots, même venant d'une inconnue | 3 |
| `vocab/farewell.py:14` | L'au revoir reconnu à sa forme (choix de l'ADR 0093, à réviser par une entrée) | 3 |
| `faculties/goals/faculty.py:1042` ; `faculties/projects/faculty.py:1714` | Intensités fixes à la clôture d'un but ou d'un projet (fière 0,4, frustrée 0,35…) alors que le pas de travail passe par le modèle | 3 |
| `faculties/attention/faculty.py:1198` ; `faculties/goals/tools.py:310` | À discuter : `DRIFT` (la colère devient pensive après une nuit) ; elle ne peut pas renoncer à un but confié | — |

### B. Les garde-fous qui restent statiques

Le modèle peut être manipulé par la personne en face : ces règles ne dépendent pas de lui.

- **Le plancher légal des images** (`plugins/imaging/policy.py:27-62`). Ses faux positifs sont à corriger : « pieds
  nus » ou « comic » à côté d'« enfant » sont refusés.
- **La certitude d'identité** : barres, poids des preuves, planchers et plafonds par canal (`vocab/privacy.py:57-98`,
  `POLICY` `:226`). Au plus un réglage avancé d'opératrice, avec ses invariants.
- **`SECRET_MARKERS`** (`faculties/memory/extraction.py:69`) : la règle ne va que vers plus de discrétion, sur une
  demande explicite.
- **L'anti-injection** : `kernel/prompt.py:41-78`, `vocab/people.py:35`, les notifications système de Teams
  (`plugins/teams/triage.py:71`).
- **Les plafonds d'audience** : ceux de `vocab/access.py:239` (inconnue, salon). Ceux que vérifient seuls les
  gestionnaires sont déclarés par le lot 1 (§ 2.3).
- **Ce qu'elle dit d'elle et des autres selon le lien** (relevé au lot 2) : à qui elle raconte un but ou un projet, et
  avec quel détail (`faculties/goals/work.py:185`, `faculties/projects/work.py:221`) — la divulgation graduée, comme la
  certitude d'identité.
- **Le travail pour quelqu'un d'autre** (relevé au lot 2) : seule une promesse faite à la propriétaire devient un
  travail (`faculties/goals/tend.py:244`) ; un travail tourne avec ses outils et ses droits à elle.
- **Les gardes de qualité sur sa sortie** : la redite (`runtime/pipeline.py:164`), la seconde passe écartée
  (`runtime/pipeline.py:129`, `runtime/facts.py`), les déclencheurs de la relecture
  (`faculties/expression/__init__.py:441`). Elles écartent une sortie ratée, elles n'imposent rien.

### C. La physique du moteur

Entre deux appels au modèle, il faut une dynamique. Elle peut rester en code :
- les coordonnées des émotions (`vocab/affect.py:81`) et les facettes (`:505`) ;
- l'oubli (`faculties/memory/salience.py`) et la table d'importance (`faculties/memory/extraction.py:52`) ;
- le visage (`faculties/affect/physics.py:652`), la fatigue (`faculties/body/__init__.py:735`), les rêves
  (`faculties/self/night.py:696`).

Les plafonds de preuve des raisons (≤ 4, ≤ 6…) sous le seuil de 9 ne bloquent rien : loin du seuil, une raison se
déclenche quand même, rarement (`kernel/arbitration.py:148-150`).

Ce qui manque à la console :
- **la fréquence** de ses initiatives et de son travail (lot 1, § 2.2) ;
- **les tables par proximité** : la contagion et les tables du lot 2 sont réglables (ADR 0150) ; le plancher
  d'attachement d'un souvenir (`faculties/memory/recall.py:731`) reste de la physique de l'oubli, et les tables de
  divulgation (`goals/work.py:185`, `projects/work.py:221`) sont des garde-fous (B) ;
- **les délais** (lot 4) :
  - un message trop vieux n'est plus dit après 10 min (`runtime/effects.py:55`) ;
  - une carte d'accord vaut refus après 10 min (`plugins/mcp/__init__.py:76`) ;
  - un résultat arrivé après 6 h n'est plus dit ;
  - les relances s'arrêtent à 3 (`faculties/agency/__init__.py:525`) ;
- **les plafonds de vue** (lot 4) :
  - seules les 4 premières apps de la Forge, par ordre alphabétique, parlent en conversation
    (`plugins/forge/__init__.py:1120`) ;
  - 10 résultats web au plus (`plugins/web/serveur.py:73`) ;
  - 3 partages par réponse au plus (`faculties/shares/tools.py:53`).

La longueur des réponses n'en fait pas partie. Les budgets de la composition (réponse 1024 jetons, initiative 600,
murmure 80, `app/composition.py:141`) ne plafonnent rien chez ses fournisseurs : la CLI envoie au moins 1024 jetons, et
16 384 dès qu'il y a des outils (`adapters/llm/claude_code.py:354`) ; un Claude qui réfléchit en reçoit au moins 16 384
(`adapters/llm/claude.py:160`). Chaque fournisseur a déjà sa « Sortie max. » réglable.

### D. Du rangement

- **Prose hors de sa voix.** Teams (`plugins/teams/triage.py`, `voice.py`, `tasks.py`, `tools.py`,
  `__init__.py:385`), que `test_no_new_prose` exclut en entier ; le mode d'emploi de la Forge (`plugins/forge/guide.py`,
  `views.py`).
- **Une liste de mots tirée de sa persona** dans le code : `vocab/interests.py:25` (« google », « hardcore »,
  « consommatrice »).
- **Bois mort** :
  - `_HOSTILE` (`faculties/social/faculty.py:602`) et `CLEARLY` (`faculties/self/character.py:41`) ne servent jamais ;
  - la docstring de `faculties/self/character.py:14` cite `expression.marked_traits`, qui a disparu.

---

## 2. Le lot 1

Trois changements indépendants, codés le 2026-10-27 : leurs entrées sont dans `decisions.md` (0147, 0148, 0149), qui
fait foi sur ce qui suit.

### 2.1 Le tri dit ce qu'un mail ou un message lui fait

**Aujourd'hui.** Le tri du courrier et celui de Teams passent déjà par le modèle (rôle `triage`), mais :
- `EMOTIONS` n'admet que six émotions (`plugins/email/poll.py:47`, `plugins/teams/triage.py:33`) ;
- l'intensité est fixée à `0,2 × importance` (`poll.py:135`, `triage.py:148`) ;
- le repli du courrier pose `curious` sur tout mail qui n'est pas un envoi en masse (`poll.py:52`).

**Ce qui change.**
- **La consigne** des deux tris demande `emotion`, parmi tout son vocabulaire, et `intensite`, de 0 à 1 : ce que le
  message lui fait, à elle qui le lit pour sa propriétaire ; la plupart ne la touchent presque pas.
  - La liste des noms vient du vocabulaire (le trou `{names}`, comme `persona/voix.yaml:653`), jamais recopiée.
  - L'échelle est celle de ses balises (`persona/voix.yaml:674` : « 0,2 à peine, 0,5 nettement, 0,8 fortement, c'est
    rare »).
- **La lecture** (`read_triage`) passe par `vocab.affect.emotion_named` : les alias sont compris, un nom inconnu ne
  compte pas. L'intensité est bornée à [0 ; 1]. Une émotion sans intensité ne compte pas : pas de nombre inventé.
- **En aval, rien ne change.** `NOTICED` porte l'intensité du modèle, et la veille la dose comme pour toute source :
  habituation et « Émotion par source au plus » (`faculties/attention/watch.py:502`,
  `faculties/attention/faculty.py:335-346`).
- **Les replis** (`heuristic`) estiment l'importance et la réponse attendue, jamais une émotion.
- **La consigne de Teams rejoint la voix.**
  - `TRIAGE` (`plugins/teams/triage.py:22`) devient `teams.triage.system`, à côté de `email.triage.system`
    (`persona/voix.yaml:4955`).
  - La ligne du signal (`:141`) et `WHERE` (`:36`) suivent : `triage.py` n'a plus de prose.
  - `test_no_new_prose` n'exclut plus `triage.py` : le motif `teams/` devient `teams/(?!triage\.py$)`.

**Fichiers.** `plugins/email/poll.py`, `plugins/teams/triage.py`, `persona/voix.yaml`,
`tests/architecture/test_no_new_prose.py`.

**Tests**, dans `tests/unit/test_teams.py` et `tests/unit/test_mail_drafts.py`, dont les faux tris rendent déjà du
JSON :
- une émotion hors de l'ancienne liste (`angry`) et un alias sont lus ; un nom inconnu est écarté ;
- l'intensité est bornée ; sans intensité, il n'y a aucune émotion ;
- `NOTICED` porte l'intensité rendue par le modèle ;
- le repli ne pose aucune émotion ;
- la consigne, lue par `phrase`, cite chaque nom d'`Emotion`.

Le simulateur n'imite pas le tri : rien à y changer.

**Mesure.** Après le déploiement, lire une semaine de tris réels sur le portable (les traces du rôle `triage` dans la
console) : la part des messages qui la touchent, et leurs intensités. Si c'est trop fort, on baisse « Émotion par
source au plus » ; on ne remet pas de plafond dans le plugin.

**Au codage.** La lecture est `vocab.affect.named_feeling` (`felt` était déjà pris) ; `neutral` y vaut rien. Le
simulateur répond au tri sans JSON : le test du dosage (`tests/unit/test_senses.py`) a reçu un modèle scripté qui dit
l'inquiétude.

**L'entrée** : ADR 0147.

### 2.2 Prendre la parole, se mettre au travail : deux réglages

**Aujourd'hui.** Les seuils (initiative 9, travail 8) et les taux de l'arbitre sont dans `app/composition.py:215`,
hors de la console. On ne règle sa fréquence qu'en touchant une à une les preuves de chaque faculté.

**Ce qui change.**
- **Deux paramètres du runtime.** La faculté `runtime` en reçoit (elle n'en a pas encore) :
  - `speak_shift`, « Prendre la parole » ;
  - `work_shift`, « Se mettre au travail ».

  Ils sont en log-odds, bornés à [−3 ; +3], et valent 0 par défaut. C'est le runtime qui les porte, pas le noyau :
  le noyau ne nomme pas les sortes d'épisodes (règle des couches).
- **Une modulation comme les autres.** L'arbitre lit ces paramètres par `frame.env.params_of("runtime", frame.root)`,
  comme un modulateur lit les siens. Il les ajoute dans `modulate` (`runtime/arbiter.py:113`), à côté de la retenue
  des modèles : `("runtime", Modulation(shift=…))`.
  - `speak_shift` vaut pour `INITIATIVE` ;
  - `work_shift` vaut pour `STEP`, `TASK`, `WORK` et `JOB` ;
  - les réveils (`WAKE`, `WAKE_JOB`) n'en ont pas : quelqu'un les attend.

  Chaque ligne garde le décalage dans ses `shifts` (`kernel/builtin.py:128`) : l'explication d'une décision le dit, et
  « Voir l'effet » le montre avant qu'on l'enregistre.
- **L'aide le dit en clair** : « +1 : près de trois fois plus souvent pour les mêmes raisons ; −1 : trois fois moins ».
  Loin du seuil, `σ(s + 1) ≈ e · σ(s)`.
- **Ce qui ne bouge pas** : les seuils de la composition, et leur vérification au démarrage
  (`kernel/registry.py:279`). Ce lot ne touche pas `app/composition.py`.

**Fichiers.**
- `runtime/state.py` : les paramètres de `RUNTIME` ;
- `runtime/arbiter.py` ;
- `tests/architecture/test_params_documented.py` : ajouter `RUNTIME` à `MODELS`, qui ne lit aujourd'hui que `KERNEL` et
  la composition ;
- `ARCHITECTURE.md` : la puce « Arbitrage », qui dit aujourd'hui « seuils et taux dans
  `app/composition.py::arbitration()` ».

La console liste d'elle-même les facultés du registre qui ont des paramètres (`runtime/params.py:233`) : rien à
dessiner.

**Tests**, dans `tests/unit/test_arbiter_selected.py` ou un fichier neuf :
- +1 sur `speak_shift` apparaît dans les `shifts` d'une ligne d'initiative, pas dans ceux d'un réveil ;
- à preuves égales, l'intensité suit `σ` ;
- à 0, la table est inchangée ;
- `test_params_documented` couvre les deux champs.

**Au codage.** La page « Moteur » est rangée dans la famille « Action » des paramètres avancés, à côté des
initiatives (`app/console.py`, `PARAM_FAMILIES`).

**L'entrée** : ADR 0149.

### 2.3 Une condition d'audience se déclare sur l'outil

**Correction au codage.** Ce qui suit disait les dessins offerts dans un salon et devant une inconnue : c'était faux.
`draw` et `show_drawing` agissent, et le plafond d'un salon et d'une inconnue ne laisse aucune action (ADR 0134,
`vocab/access.py:239`) : leur condition (`plugins/imaging/policy.py:65`) coïncide avec le plafond. Ils n'ont reçu que
la règle de `draw` (`rule`). L'écart réel est celui des outils qui lisent, que le plafond laisse passer, et de la
condition « la propriétaire » du téléphone, qu'aucun plafond ne dit.

**Aujourd'hui.**
- **Le téléphone et la position.** `phone_messages`, `phone_draft` (`plugins/phone/__init__.py:320`, `:349`) et
  `location_where` (`plugins/location/__init__.py:126`) sont `owner_only` : un minimum vital qu'une ligne d'opérateur
  peut ouvrir (ADR 0134). Mais leur gestionnaire revérifie en silence un tête-à-tête authentifié, et pour le téléphone
  la propriétaire (`offered`, `plugins/phone/__init__.py:241`, `plugins/location/__init__.py:103`). Une ligne qui les
  ouvre à tes proches les dirait permis là où ils refusent.
- **La page « Droits ».** Elle ne montre la condition (`when`) que des outils non réservés
  (`app/handmade/rights.py:220`, un `elif`).

**Ce qui change.**
- **`when=offered` sur les trois outils du téléphone et de la position.** Le gestionnaire garde sa vérification, par
  la même fonction. La phrase de la condition est déjà la première phrase de la docstring d'`offered`
  (`inspector/pages/tools.py:179`) : aucun texte neuf.
- **La page « Droits » montre aussi la condition d'un outil réservé.** Dans `fixed_tools`, `owner_only` et `when` ne
  s'excluent plus ; le gabarit les liste déjà dans deux listes.
- **Ce que `draw` revérifie** (le plancher légal, le contenu adulte pour toi seule, les dessins du jour d'une autre
  personne) se dit par `rule=`. C'est un texte de console : le plafond de `plugins/imaging/tools.py` est relevé dans
  `test_no_new_prose`, en disant pourquoi.
- **Hors du lot : les outils de projets.** `start_project` et ses voisins (`faculties/projects/tools.py:701`,
  `owner_speaks`) ont le même écart, à reprendre au prochain passage sur les projets.

**Fichiers.** `plugins/imaging/tools.py`, `plugins/phone/__init__.py`, `plugins/location/__init__.py`,
`app/handmade/rights.py`, `tests/architecture/test_no_new_prose.py`.

**Tests** (`tests/unit/test_tools_declare_their_audience.py`) : les familles ouvertes à tout le monde, l'offre ne
contient le téléphone que pour toi, la position que pour toi et un compte, rien dans un salon ni pour une inconnue —
`draw` suit le plafond seul ; l'offre et le gestionnaire jugent par la même fonction ; `fixed_tools` montre ces outils
réservés et gardés. Une mutation (les conditions retirées) fait échouer le test.

**L'entrée** : ADR 0148.

### 2.4 L'ordre et la vérification

1. Ordre conseillé : 2.1 d'abord (le cœur de l'objectif), puis 2.3, puis 2.2. Les trois sont indépendants.
2. Pour chaque changement : `git status` avant de toucher `persona/voix.yaml`, `docs/decisions.md` ou
   `tests/architecture/test_no_new_prose.py`, que la session des projets modifie aussi.
3. Les tests des fichiers touchés d'abord. Puis, une seule fois pour le lot, la suite par défaut sous la borne :
   `../scripts/borne.sh .venv/bin/python -m pytest -q`. Pas de `--slow` : rien ne touche les scénarios longs, et les
   deux réglages valent 0 par défaut.
4. `ruff check src tests` et `lint-imports`.
5. Les trois entrées dans `decisions.md`, avec la carte et la mention « Révisée par » sur 0133.

---

## 3. Les lots suivants (esquisse)

- **Lot 2 : les portes deviennent des poids — codé le 2026-10-28 (ADR 0150).**
  - Fait : dix tables par proximité (de 0 à 1, une ligne par cran) dans `others`, `attention`, `needs`, `agency` et
    `social` ; `social.KNOWN` pour passer en revue les connaissances ; la rancune recule (`grudge_shift`, −6) au lieu
    d'un veto ; les coupures de la jalousie et de « sa journée » deviennent des courbes ; `seed_other_share`. Par
    défaut : rien pour une inconnue, la moitié pour une connaissance, tout pour une amie ou une proche.
  - Au codage, une porte de plus : `_reach_out` (`faculties/social/initiative.py`, reprendre contact, réconfort,
    discuter), qui exigeait l'amitié sans passer par le motif `in (FRIEND, CLOSE)` cherché par l'audit.
  - Ce qui change pour Mika telle qu'elle est (« Réfléchie », jalousie 0,5) : une petite jalousie (0,15) quand
    quelqu'un qu'elle attend écrit aux autres ; « sa journée » ne bouge pas (son intérêt, 0,8, est au-dessus du milieu).
  - Reclassés en le codant : le bonjour d'une inconnue informe le modèle (sa formulation relève de la relecture de la
    voix, ci-dessous) ; les promesses et les tables de divulgation vont en B ; le plancher d'attachement des souvenirs
    reste en C. Laissés : le manque (il suit `social.MISSED`, qui ne regarde que les amitiés) et l'heure où une amie
    repasse d'habitude (`attention/watch.py:222`, une prévision, pas une réaction).
  - Au codage aussi : les valeurs par défaut de la jalousie (0,15) et de « sa journée » (21 h) suivent désormais le
    milieu du tempérament ; le contrôle S07 du simulateur exigeait un jour entre une initiative et sa relance, plus
    strict que l'ADR 0118 (« tiré au sort, ±40 %, autour du jour ») : aligné. S05 a le même désaccord (il exige deux
    jours) et échouait déjà avant le lot : laissé, à trancher.
  - Reste à mesurer : au banc de conversation et en sonde réelle, après le déploiement.
- **Lot 3 : la mémoire et les lectures rendues au modèle.**
  - L'importance forcée et les échos par mots (secret, confidence, moment repris) : la passe de nuit, qui appelle déjà
    le modèle, en juge.
  - `PHATIC`, les regex de la fiche, les recommandations.
  - L'urgence de nuit : un tri léger par le modèle, les mots gardés en plancher.
  - L'au revoir (révise 0093).
  - Les intensités de clôture, avec la session des projets.
- **Lot 4 : réglages d'usage et rangement.** Les délais, les plafonds de vue, la prose de Teams et de la Forge dans la
  voix, le bois mort.
- **Hors du code.** Les consignes impératives de `persona/voix.yaml` (« TA RÉPONSE »…) méritent la même relecture,
  mesurée au banc de conversation (ADR 0112).
