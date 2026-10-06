# Étape 0 — essai et mesures (6 octobre 2026)

On a rejoué des archives synthétiques dans le **vrai noyau** `backendv2`, sur horloge virtuelle et sur disque,
avec un fournisseur LLM scripté. Aucun appel de modèle réel n'a eu lieu, hors des deux appels `haiku` du point 6.
Rien n'a été modifié dans `backendv2/`.

## En bref

- **Ça marche, et c'est rapide.** Le noyau rejoue de **80 000 à 190 000 messages par heure de calcul**, sur un seul
  cœur. Le journal pèse environ **3,2 Ko par message** dans `mind.db`. Un million de messages, c'est donc
  **6 à 10 h** de calcul et **≈ 3,3 Go** de `mind.db`.
- **Le mur, c'est la mémoire vive.** Elle croît d'environ **2,4 Ko par message**, surtout à cause de l'index des
  vecteurs gardé en RAM. Sous la borne de 3 Go, on tient vers **1 M de messages**. **5 M ne passent pas** : il faut
  reléguer la masse au palier C.
- **Le mécanisme de réponse à retenir n'est pas celui du plan.** Le plan prévoyait « `[SILENCE]` puis un épisode
  soumis à la main ». On fait mieux : on **retient** le message par un `reply_wait` du pilote, puis on le **libère**
  à l'heure réelle de sa réponse. Le noyau lance alors lui-même une vraie REPLY, avec `reply_to`. Elle règle la
  rafale entière, quel que soit le délai, et même la nuit. Validé, crash compris.
- **Le préréglage « avance rapide » éteint toute vie spontanée** : 0 initiative, 0 but et 0 sélection de l'arbitre,
  contre 1,4 initiative et 1,4 but par jour sans lui. Les surcharges sont acceptées et journalisées. Il faut y ajouter
  `body.woken_by=()`, sinon une amie qui écrit la nuit la réveille même quand l'archive dit qu'elle dormait.
- **Une horloge qui part de 2008 ne pose aucun problème**, changement d'heure compris. La reprise après
  plantage, depuis le même `mind.db`, fonctionne aussi. Il faut seulement que le pilote restaure son état
  **avant** `boot`.
- **CLI 2.1.282** : la sortie structurée arrive dans `structured_output`, déjà validée par le schéma. Un modèle
  poussé à le violer le respecte quand même. `rate_limit_event` donne l'utilisation en pourcentage : 5 h et
  7 jours.

## Montage

| Fichier | Rôle |
|---|---|
| `INJECTION/spike/mesure_noyau.py` | les scénarios `debit`, `episodes`, `nuit`, `spontane`, `passe` ; résultats dans `out/<nom>/resultats.json` (+ `jours.csv`) |
| `INJECTION/spike/lancer.sh` | lance le script sur un **instantané gelé** de `backendv2` (`git archive HEAD`). Une autre tâche modifiait `backendv2/src` pendant l'essai, et a même laissé une erreur de syntaxe dans `plugins/teams`. Le script passe par `borne.sh`, avec BLAS sur un seul fil |
| `INJECTION/spike/sonde_cli.py` | les deux appels `claude -p` du point 6 ; sorties brutes dans `out/cli/` |

- **Le noyau** : `sim/world.py::Driver` tel quel, avec `SqliteStore` sur disque, `HashEmbedder` (256 dimensions),
  `slots=4` et la composition `app/composition.py`. Deux branchements seulement :
  - `deps(**kw, reply_wait=pilote.reply_wait)` ;
  - `configure(kernel, persona, overrides=…)`.
- **Le rejoueur** (`Rejoueur`) répond par rôle :
  - `reply` et `initiative` : le plan du pilote pour la cible, c'est-à-dire ses mots suivis de
    `[EMOTION:x:y]`. Sans plan, il rend `[SILENCE]` ;
  - `extract`, `journal`, `dream`, `narrative`, `profile`, `compact` : la doublure `PersonaSimLLM`, sans
    latence ;
  - `murmur`, `step` et les autres : `[SILENCE]`.
- **L'archive synthétique** a une graine fixe. Elle contient :
  - 6 personnes `ext_<slug>` sur le canal `external` (confiance « compte », non authentifiée), à qui elle peut
    écrire même absentes ;
  - un salon ;
  - des séances de 1 à 7 échanges, avec des rafales de 1 à 3 messages ;
  - ses réponses : 80 % en moins de 2 min, 20 % différées de 10 min à 4 h, 12 % des tours laissés sans
    réponse, 30 % des séances ouvertes par elle ;
  - des heures pondérées, dont 3 % des séances la nuit.
  
  Une personne naît à son premier message. `identity` crée la personne `ext_<slug>` et la nomme d'après
  `display_name`. Il n'est pas besoin d'appeler `connect` : un compte extérieur n'a pas de présence.

## 1. Débit et taille

Toutes les durées sont mesurées sur un cœur (`OPENBLAS_NUM_THREADS=1`), sauf mention contraire. Les tailles sont
prises après fermeture : le WAL est vidé.

| Archive (60 jours) | Messages (entrants / ses paroles) | Mur | Débit | Événements (par message) | `mind.db` | `views.db` | Pic RSS |
|---|---|---|---|---|---|---|---|
| quasi vide | 101 (59 / 35) | 26 s | — | 4 193 | 1,9 Mo | 1,8 Mo | 138 Mo |
| (a) 34 messages par jour | 2 040 (1 253 / 649) | 91 s | 22 msg/s | 12 118 (5,9) | 8,4 Mo | 4,0 Mo | 146 Mo |
| (b) 320 messages par jour | 19 172 (11 394 / 6 217) | **364 s** (505 s avec BLAS multifil) | 53 msg/s | 82 003 (4,3) | 61,7 Mo | 21,1 Mo | 182 Mo |
| (c) 1 an, 100 messages par jour | voir « Une année » plus bas | | | | | | |

### Ce qui coûte

- **Le temps vécu**, même sans message, coûte **≈ 0,42 s par jour virtuel**. Une journée virtuelle
  comprend :
  - ≈ 256 passages de l'arbitre ;
  - 145 des séries ;
  - ≈ 100 de `email.poll`, alors qu'aucune boîte n'est configurée ;
  - ≈ 35 de `rss.poll` ;
  - ≈ 50 `needs.felt`, « le vide » toutes les 15 min après 2 h d'inactivité. C'est le seul poids du temps vide
    dans le journal : ≈ 70 événements par jour, ≈ 11 Mo par an.
- **Chaque message** coûte entre **0,018 s** (en densité (b)) et **0,032 s** (en densité (a)).
- **Modèle** : `T ≈ 0,42 s × jours + (0,018 à 0,032 s) × messages`.
- **Journal**, pour un message entrant :
  - `perception.received` (256 o) ;
  - `others.read` (266 o) ;
  - souvent, une croyance de la doublure (369 o).
  
  Pour une de ses paroles :
  - le quatuor `episode.started` / `lease_acquired` / `lease_released` / `episode.ended` (≈ 400 o) ;
  - `episode.utterance` (≈ 800 o, sections et provenance comprises).
  
  Les données JSON ne font qu'un tiers du fichier. Le reste se répartit entre :
  - les index (`events_corr`, `events_type`, unicité) ;
  - les projections T0 : `thread`, `memory_items`, `memory_told` ;
  - `content`, `dedupe` ;
  - l'instantané (70 Ko, 3 gardés).
- **`mind.db` ≈ 3,1 à 3,2 Ko par message**, soit 31 à 32 Mo pour 10 000, dans les deux densités, à quoi s'ajoutent
  ≈ 0,03 Mo par jour vécu.
- **`views.db` ≈ 1,0 Ko par message**. Les traces sont bornées : 14 jours et 3 000 lignes, `runtime/traces.py:49-50`.
  Les séries sont bornées à 60 jours. Ce qui croît, ce sont les **vecteurs** : un par croyance, souvenir ou bloc
  d'échange.
- **RAM ≈ 137 Mo + 2,4 Ko par message.** Une grande part vient de la matrice des vecteurs en `float32` : 18 000
  vecteurs × 256 dimensions × 4 o pour (b). Avec `SentenceEmbedder` (384 dimensions), compter ×1,5 sur cette
  part.
- **BLAS multifil** : par défaut, numpy lance 11 fils qui tournent à vide (≈ 700 % de CPU). L'essai (b) va
  **28 % plus vite sur un seul fil**, et le journal produit est identique au bit près. Le pilote doit donc exporter
  `OPENBLAS_NUM_THREADS=1`.
- **Déterminisme** : (a), rejoué deux fois (une fois sur le dossier de travail, une fois sur l'instantané gelé), donne
  le même nombre d'événements et les mêmes tailles au bit près.

**Prudence sur les tailles.** La doublure `extract` tire une croyance de presque **chaque** phrase entrante :
10 221 croyances pour 11 394 messages en (b). Les annotations de Claude Code seront bien plus parcimonieuses, de
l'ordre d'un élément pour 5 à 10 messages. Les chiffres « par message » de `mind.db`, de `views.db` et de la RAM
sont donc des **majorants**, sauf pour la part conversationnelle (perception, épisode, énoncé, blocs d'échange),
qui reste.

### Appels que le rejoueur devra servir (pour 1 000 messages d'archive)

| Rôle | (a) 34 messages par jour | (b) 320 messages par jour | Remarque |
|---|---|---|---|
| `reply` | 346 | 353 | dont 19 % de `[SILENCE]` (tours restés sans réponse) |
| `initiative` | 39 | 40 | ses ouvertures, soumises par le pilote |
| `extract` | 212 | 121 | une consolidation par conversation apaisée |
| `profile` | 108 | 19 | ≤ 2 fiches par passage, ≥ 1 jour d'écart |
| `journal` | 59 (2 par jour) | 35 (**11 par jour**) | voir le piège « nuits coupées » |
| `dream` | 40 | 0,6 | en (b), réveillée sans cesse la nuit, elle n'atteint presque plus le paradoxal |
| `narrative` | 29 | 3 | |
| `compact` | 9 | 13 | |

### Une année

*(à compléter : voir la section « Une année, 100 messages par jour » à la fin du document)*

### Extrapolation

On prend une vie de 15 ans, soit ≈ 5 500 jours vécus. On applique le modèle ci-dessus, linéaire, en supposant
que le coût par message ne se dégrade pas. Voir la mise en garde sous le tableau.

| | 1 M de messages | 5 M de messages |
|---|---|---|
| Calcul | 0,6 h (jours) + **5 à 9 h** (messages) | 0,6 h + **25 à 45 h** |
| `mind.db` | ≈ 3,3 Go (majorant) | ≈ 16 Go |
| `views.db` | ≈ 1,1 Go (jetable) | ≈ 5 Go |
| RAM | ≈ **2,5 Go** (majorant) | ≈ **12 Go** : **impossible** sous `borne.sh` |
| Événements | ≈ 4,3 à 6 M | ≈ 21 à 30 M |

**Mise en garde.** En (b), le coût marginal monte d'environ 8 % entre les jours 10 à 35 et les jours 35 à 60 :
8,8 puis 9,5 s par jour virtuel. L'année de la section suivante dit si cette dérive continue.

## 2. Épisodes soumis à la main

Le scénario `episodes` joue cinq scènes, toutes sur `ext_*`. Résultats bruts dans `out/episodes/resultats.json`.

| Scène | Ce qu'on fait | Issue | Fil (`transcript`) | Ce que voit le modèle (fin du dernier tour) | `social` | `affect` |
|---|---|---|---|---|---|---|
| a | `lanes.submit(EpisodeRequest(INITIATIVE, target=ext_lea, reason="archive"))`, sans aucun message reçu de Léa | `done`, livré | INITIATIVE | « (Personne ne vient de t'écrire : c'est toi qui prends la parole…) » | Léa naît en `stranger`, `her_starts=1` | posture `playful` déclarée, intensité 0,44 : **la balise est prise** |
| b | message à 13 h → `[SILENCE]` (`REPLY:abstained`) ; à 16 h, `EpisodeRequest(REPLY, target, reply_to=None)` | `done` | REPLY **sans** `reply_to`, `answers=()` | « [plus tard, vers 16h] » suivi d'un **tour vide** | rien d'une réponse ; message déjà marqué « s'est tue » | `happy` déclaré |
| c | idem, mais en INITIATIVE | `done` | INITIATIVE | « [plus tard, vers 21h] (Personne ne vient de t'écrire…) » : **faux** pour un vrai modèle | **compte une ouverture d'elle**, et `attention` attend une réponse | `relieved` déclaré |
| d | **retenir puis libérer** : `release_at[(ext_karim, None)] = t+3 h`, rafale de 3 messages (retenus), `_release_held()` à t+3 h | `done` | **REPLY `reply_to=67`, `answers=[60, 64, 67]`** | « [tu ne le lis que maintenant, vers 1h30] dis-moi vite stp » | une vraie réponse, avec son délai | `excited` déclaré, intensité 0,57 |
| e | salon : 2 messages non adressés, 1 adressé (retenu puis libéré), puis une parole spontanée en `REPLY(reply_to=None, room=…)` et en `INITIATIVE(room=…)` | les trois `done`, avec `room` | trois énoncés au salon | — | — | réponse à l'adressé : `happy` déclaré envers Julie ; **parole spontanée : aucune posture déclarée envers Tom** |

Conclusions :

- **Une initiative soumise à la main passe toujours**, sans message entrant et même vers une adresse qui n'a jamais
  écrit : `lanes.submit` contourne l'arbitre et ses vetos. La scène a tournait sous le préréglage
  `agency.daily_cap=0`, et l'initiative est passée. Sa consigne dit « Personne ne vient de t'écrire » :
  c'est juste pour une ouverture, faux pour une réponse différée. Voir `faculties/agency/__init__.py:515`.
- **Le différé par `[SILENCE]` puis un épisode (scènes b et c) est mauvais.**
  - La question est réglée « s'est tue » au moment même.
  - La réponse tardive n'a plus de `reply_to`.
  - En INITIATIVE, `social` et `attention` comptent une ouverture de sa part, qu'ils attendent de voir répondue.
- **Retenir puis libérer (scène d) est juste à tous points de vue** :
  - `reply_to` et `answers` sont corrects ;
  - la rafale est fusionnée ;
  - le repère « tu ne le lis que maintenant » est posé par le noyau ;
  - aucun délai maximal : `_abandon_if_due` compte l'âge depuis `due`, que le pilote rend, voir
    `runtime/bootstrap.py:486-496` ;
  - ça marche aussi pendant son sommeil, la scène d se passant à 22 h 30. Le `reply_wait` du pilote passe avant
    celui de `body`.
- **Au salon**, `addressed=False` journalise sans réponse. Une parole spontanée passe en `REPLY(reply_to=None,
  room=…)`. Une INITIATIVE au salon compterait une ouverture vers sa cible (`social/faculty.py:475-480`).

## 3. La nuit

Le scénario `nuit` fait vivre 20 jours, avec 30 messages par jour, avant de tester la nuit. Léa est alors `friend`.
On teste ensuite le dimanche 22 mars à 2 h (`deep_sleep`).

| Instant | Ce qui arrive | Ce que fait le noyau |
|---|---|---|
| 2 h 00 | Léa (amie) : « tu dors ? j'arrive pas à dormir » | `body.roused` : **une amie la réveille**. Réponse immédiate, `[SILENCE]` faute de plan, `REPLY:abstained` |
| 2 h 10 | une inconnue : « bonsoir, on se connaît ? » | `body.waited` : la réponse est **retenue jusqu'à son réveil** (`Perceived.held`) |
| 2 h 15 | | `body.fell_asleep` : elle se rendort après 15 min de calme |
| 2 h 30 | `REPLY` soumise à la main vers l'inconnue | **passe** (`done`). Juste après, `body.SLEEP` dit `awake` : sa parole compte comme activité, et elle se rendort à 2 h 45. Le journal ne porte **aucun** `body.woke`, d'où une petite incohérence |
| 7 h 56 | `body.woke` | le message retenu de l'inconnue est **relâché** : REPLY `[SILENCE]` → `abstained`. Sa réponse de 2 h 30, sans `reply_to`, ne l'avait pas réglé |

Conclusions :

- **Mécanisme à retenir.** Quand elle a vraiment répondu la nuit, retenir puis libérer à l'heure de sa réponse
  (scène 2d) règle le message, malgré `body`. Quand elle n'a pas répondu, `body` retient jusqu'au réveil, puis le
  rejoueur rend `[SILENCE]`.
- **Piège.** Une amie ou une proche qui écrit la nuit **la réveille même quand l'archive dit qu'elle dormait**. Le
  jugement vient de l'interprète `_rouse_or_wait`, `faculties/body/__init__.py:198-216`, avant tout `reply_wait`.
  En (b), cela a produit 475 réveils, 836 endormissements et 11 journaux par jour, pour presque aucun rêve. La
  surcharge **`body.woken_by=()`** est acceptée (`faculties/body/__init__.py:102`). Un message « urgent »
  (« au secours », « hôpital », « accident »…) réveille quand même, sans réglage possible.
  Résultat de l'essai avec cette surcharge : *(voir « Nuit sans réveil » à la fin)*.
- **Chronotype.** `body.shift_minutes = round((chronotype − 0,5) × 240)`, soit ±2 h
  (`faculties/body/__init__.py:110`). Mesures sur 4 nuits sans personne :

| `chronotype` | Endormissement | Réveil |
|---|---|---|
| 0,0 | 20 h 51 à 21 h 16 | 4 h 33 à 5 h 20 |
| 0,5 | 22 h 10 à 23 h 17 | 6 h 27 à 7 h 19 |
| 1,0 | 23 h 19 à 1 h 16 | 8 h 00 à 9 h 19 |

  Sans activité, l'heure dérive d'une demi-heure à une heure sur les premières nuits : la pression initiale est
  supposée. Un cran de 0,1 de chronotype déplace son sommeil d'environ 20 à 25 min. Le chronotype dérivé de ses
  heures réelles doit viser son **réveil médian**, plus stable que l'endormissement, puisqu'une conversation qui
  dure retarde ce dernier.

## 4. Vie spontanée

Le scénario `spontane` dure 14 jours, avec ≈ 33 messages par jour. Le rejoueur joue ses initiatives spontanées
(mode « naturel » de la doublure).

| | Naturel (sans surcharge) | Avance rapide (préréglage) |
|---|---|---|
| Initiatives spontanées | **19** (1,4 par jour) | **0** |
| Buts ouverts, séances `step` | 20 / 20 | 0 / 0 |
| Murmures | 0 : ses correspondants `ext_` ne la « regardent » pas | 0 |
| Sélections de l'arbitre (`kernel.selected`) | 39 | **0** |
| Initiatives `archive` (pilote) | 13 | 13 |

Les raisons des initiatives naturelles :

- `goals` : `share`, raconter ce qu'elle a fait, et `work`, pour les séances ;
- `needs` : `need_social`, `need_expression` ;
- `social` : `chat`, `recontact` ;
- `others` : `cheer`, `follow_up`.

**Le préréglage éprouvé** (`FAST_FORWARD` dans le script) n'a aucune surcharge refusée, et chacune a la source
« surcharge » :

```python
{"agency": {"daily_cap": 0},                       # veto de toute initiative ordinaire (agency/__init__.py:344)
 "goals": {"musings_per_day": 0, "live_self_max": 0},
 "expression": {"murmur_chance": 0.0, "murmur_charged_chance": 0.0},
 "body": {"woken_by": []}}                          # recommandé (point 3)
```

`daily_cap=0` ne coupe pas ce qui est **dû** : `agency.NOT_SPEAKING_UP = GREETS | OWED`
(`contracts/agency.py:62-78`). Restent donc les salutations à l'arrivée (jamais pour `ext_`), un rappel promis
(`goals.REMIND`) et une promesse datée (`memory.KEEP_PROMISE`). Le rejoueur rendra `[SILENCE]` à celles que
l'archive ne prévoit pas. Il faut les compter comme « trous ».

**Comment poser et lever** : `app/composition.py:205` `configure(kernel, persona, overrides=…)`. Le plan est fait par
`runtime/params.py::plan`, et chaque faculté touchée produit un `kernel.params_changed`. Pour lever,
`configure(kernel, persona, overrides=None)`, qui ramène au défaut tout ce qui avait été journalisé
(`params.to_journal`). La vérification de la levée est dans la section « Une année ». Dans le pilote, passer
`Composition(configure=lambda k, doc: configure(k, doc, overrides=PRESET))`.

**Les réglages qui pilotent sa vie spontanée** (fichiers sous `backendv2/src/mika/faculties/`, lignes à `02b582fe`) :

| Faculté | Paramètres (ligne, défaut) |
|---|---|
| `agency` (`agency/__init__.py`) | `daily_cap` (83, 5) · `refractory_us` (87, 30 min) · `refractory_shift` (91, −8) · `hesitation_us` (99, 10 min) · `ignored_backoff` (115, 2,5) · `quiet_after_reply_us` (128, 4 h) · `farewell_quiet_us` (132, 4 h) · `quiet_after_question_us` (137, 12 h) · `follow_up_min_us` (141, 1 j) |
| `goals` (`goals/faculty.py`) | `steps_per_hour` (64, 4) · `live_self_max` (126, 2) · `seed_spacing_us` (130, 2 h) · `seed_thought_from` (138, 0,35) · `seed_curiosity_from` (145, 0,7) · `musings_per_day` (169, 2) · `share_evidence` (189, 10) · `remind_evidence` (110, 12) |
| `others` (`others/faculty.py`) | `checkin_evidence` (193, 9,5) · `followup_evidence` (217, 9,5) · `followup_minor_evidence` (221, 6) · `celebrate_evidence` (227, 10) · `cheer_evidence` (232, 6) |
| `social` (`social/faculty.py`) | `recontact_evidence` (155, 10,5) · `rekindle_evidence` (181, 10) · `comfort_evidence` (193, 10) · `chat_friend` (217, 1,5) · `chat_close` (221, 2,5) · `day_start_min` / `day_end_min` (228 / 232) |
| `needs` (`needs/__init__.py`) | `social_evidence` (144, 6) · `expression_evidence` (151, 3) · `idle_before_empty_us` (177, 2 h) · `empty_every_us` (181, 15 min : ce sont les 50 `needs.felt` par jour d'une vie vide) |
| `attention` (`attention/faculty.py`) | `thought_evidence` (312, 4) · `glad_evidence` (324, 2,5) |
| `expression` (`expression/__init__.py`) | `murmur_chance` (63, 0,35) · `murmur_charged_chance` (67, 0,6) |
| arbitre (`app/composition.py:177`) | seuils en log-odds : INITIATIVE 9,0, STEP 8,0 ; taux max INITIATIVE 0,1 par seconde |

## 5. Une horloge qui part de 2008, puis la reprise

Le scénario `passe` fait vivre 10 jours à partir du 27 mars 2008, avec 40 messages par jour. Le passage à l'heure
d'été du 30 mars 2008 est compris. Au milieu, on provoque un plantage (`Driver.crash()`, un `kill -9` simulé)
pendant qu'une question est retenue. On reprend ensuite avec **une nouvelle horloge partant de la tête du journal**
(`SimClock(max(at) + 1 µs)`), sur le même `mind.db`.

- **Aucune anomalie** :
  - 0 tranche corrompue, 0 erreur de boucle, 0 processus en erreur ;
  - 0 instant à rebours dans le journal ;
  - ULID corrects (48 bits de millisecondes, 2008 sans souci) ;
  - `at_paris` et le changement d'heure sans effet visible ;
  - 28 journaux intimes et 12 rêves datés de 2008 ;
  - file de sortie : 144 `done`. La purge des 30 jours (`adapters/store_sqlite/store.py:69`) et celle des traces
    à 14 jours se calculent sur l'horloge virtuelle : rien à faire.
- **La reprise** :
  - `kernel.boot` n°2 au seq 740 ;
  - le noyau **retient à nouveau** la question (`_held = [738]`), parce que le pilote a restauré son
    `release_at` **avant** `boot` ;
  - les 4 messages d'archive renvoyés sont tous **dédoublonnés** (`dedupe_key="archive:<id>"`) ;
  - la réponse part à l'heure prévue, en `REPLY reply_to=738`.
- **Pièges.**
  - Si le pilote ne restaure pas son état avant `boot`, `Kernel.recover()` relance tout de suite la question
    retenue. Il le fait via `reply_wait`, puis `body` : `runtime/bootstrap.py:409-460`. Le rejoueur, sans plan,
    rend `[SILENCE]` et la question est perdue.
  - Une question restée en suspens plus de 10 min **au-delà de son `due`** est abandonnée au redémarrage :
    `max_reply_age_s=600`, `runtime/bootstrap.py:97`.
  - `Driver` dérive ses ULID de `seed:boots`. Pour un second processus, il faut passer `boots=1` (ou plus) pour
    ne pas rejouer la même suite aléatoire.

## 6. La CLI Claude Code et `--json-schema`

Deux appels `haiku`, lancés avec un environnement rebâti sur `INHERITED` (sans `FORBIDDEN` ni aucune variable
`CLAUDE_*`), depuis un dossier temporaire neutre, avec `ENABLE_CLAUDEAI_MCP_SERVERS=false` et
`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. La commande :

```
claude -p --model haiku --output-format json --json-schema '<schéma>' --setting-sources "" --strict-mcp-config \
       --tools "" --permission-mode dontAsk --no-session-persistence "<consigne>"
```

- **Où arrive la sortie** :
  - `structured_output` contient **l'objet déjà décodé**, par exemple
    `{"emotion": "happy", "intensity": 0.85, "resume": "…"}` ;
  - `result` contient **le même objet en chaîne JSON** ;
  - `stop_reason="tool_use"`, `num_turns=2` : la CLI passe par un outil interne `StructuredOutput`, le seul
    outil présent dans `init`.
- **Schéma violé exprès** (appel 2 : « réponds en texte libre, SANS JSON, émotion « mélancolique », intensité 7
  sur 10 ») :
  - le modèle écrit d'abord son texte libre dans un message `assistant` ;
  - puis il appelle quand même `StructuredOutput` avec des valeurs **conformes** (`sad`, 0,7) ;
  - le `result` final est le JSON valide : `subtype="success"`, `is_error=false`. Le texte libre n'apparaît pas
    dans `result`.
  
  Le cas d'un modèle qui n'y arrive vraiment pas n'a pas été provoqué : la limite était de deux appels. Le runner
  doit donc traiter `subtype != "success"` ou un `structured_output` absent comme un échec, puis repasser par
  « le premier `{…}` validé par pydantic ».
- **Latence** :
  - appel 1 : 4,7 s de mur, dont 3,7 s d'API ;
  - appel 2 : 9,2 s de mur, dont 5,1 s d'API et **3 s perdues** par l'avertissement « no stdin data received in
    3s ». Il faut lancer avec `stdin=subprocess.DEVNULL`.
  
  Coût de liste : 0,011 $ par appel. 4,4 k jetons de préfixe système sont écrits en cache 1 h. Haiku 4.5
  « réfléchit » : 262 jetons de réflexion sur 370 de sortie.
- **`rate_limit_event`** : un seul en `stream-json --verbose`, juste avant le `result` :

```json
{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1791289200,"rateLimitType":"five_hour",
 "overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,
 "unifiedWindows":{"five_hour":{"utilization":0.36,"resetsAt":1791289200},
                   "seven_day":{"utilization":0.66,"resetsAt":1791572400}}}}
```

  Le runner peut donc lire `unifiedWindows.*.utilization` à chaque appel et faire une pause au-delà de 0,8,
  jusqu'à `resetsAt` (en secondes epoch). Le message `init` dit aussi `apiKeySource: "none"` : c'est bien le
  login de la CLI qui est utilisé, sans aucun jeton. Il liste pourtant les compétences et agents de
  l'utilisateur ; ils sont inoffensifs, puisque `tools=["StructuredOutput"]`.

## Recommandations chiffrées pour le pilote

1. **Plafonds.**
   - Débit : **≈ 100 000 messages rejoués par heure de calcul** (de 80 k à 190 k selon la densité), plus
     **2,5 min par année vécue**.
   - Taille : **≈ 300 000 messages par Go de `mind.db`** (majorant), plus ≈ 1 Go de `views.db` jetable par
     million.
   - RAM : sous `BORNE_MEM=3G`, **≈ 1 M de messages rejouables** en un seul `mind.db`. Viser **≤ 1 M** en paliers
     A et B, et laisser le reste en palier C (savoir d'archive).
2. **Une seule règle de réponse, retenir puis libérer**, à la place de « moins de 2 min, sinon `[SILENCE]` puis
   épisode ».
   - Un message auquel elle a répondu avant que la personne ne réécrive, et dans les **2 jours**, est retenu
     jusqu'à sa réponse. Les 2 jours correspondent à `others.delay_max_us`, « au-delà, ce n'est plus une
     réponse ».
   - À l'heure de sa réponse, le pilote pose le plan, puis libère : aujourd'hui avec `kernel._release_held(root)`.
   - Au-delà de 2 jours, ou si la personne a rouvert une autre séance entre-temps, sa parole devient une
     **INITIATIVE**. Le message ancien, non retenu, reçoit `[SILENCE]` sur le moment.
   - Une conversation qu'elle ouvre (aucun message de la personne depuis plus de 2 h, soit
     `social.conversation_gap_us`) est une INITIATIVE.
   - Ses messages consécutifs sont fusionnés.
3. **Salons** :
   - `addressed=True` seulement si le message la nomme ou répond à l'un des siens ;
   - un adressé auquel elle a répondu : retenir puis libérer ;
   - sa parole spontanée : `REPLY(reply_to=None, room=…, target=<la personne à qui elle répond, sinon le dernier
     à avoir parlé>)`, **jamais** une INITIATIVE.
   - À savoir : la balise d'une parole spontanée ne touche pas la posture envers la cible.
4. **Nuit** :
   - poser `body.woken_by=()` ;
   - ses réponses réelles de nuit passent par « retenir puis libérer », sans réveil (`body` reste endormi : petite
     incohérence acceptée) ;
   - chronotype : `(heure médiane de réveil − 7 h) / 4 h + 0,5`, borné à [0, 1].
5. **Préréglage « avance rapide »** :
   - `agency.daily_cap=0` ;
   - `goals.musings_per_day=0`, `goals.live_self_max=0` ;
   - `expression.murmur_chance=0`, `expression.murmur_charged_chance=0` ;
   - `body.woken_by=()` ;
   - facultatif : `needs.empty_every_us=6 h`, pour alléger le journal des longs silences, au prix d'un « vide »
     moins fin.
   
   Le préréglage se lève par `configure(…, overrides=None)` à l'arrivée.
6. **Environnement** :
   - `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1` ;
   - un instantané gelé de `backendv2` (`lancer.sh`) ;
   - `borne.sh`, une avance à la fois.
7. **Reprise** :
   - un fichier d'état du pilote (curseur, `release_at`, table archive ↔ `seq`) est écrit après chaque jour
     virtuel, et restauré avant `boot` ;
   - `dedupe_key="archive:<id>"` sur chaque perception ;
   - `Driver.boots` est incrémenté ;
   - l'horloge repart de `max(at)` du journal.

## Pièges trouvés

- `runtime/pipeline.py:655-667` — la garde du tour. Une REPLY dont `reply_to` n'est plus en attente est
  supplantée : on ne peut pas répondre plus tard à un message déjà réglé par `[SILENCE]`.
- `runtime/state.py:102-116, 161` — `abstained`, `failed` et `timeout` **règlent** le tour. Seuls
  `superseded`, `preempted`, `interrupted` et `cancelled` le laissent en attente. Le rejoueur ne doit jamais rendre
  `[SILENCE]` à un tour qu'il compte libérer.
- `runtime/bootstrap.py:464` — `_release_held` est privé. Le lot noyau devrait exposer `release_held()`,
  ou documenter que tout ajout au journal le déclenche (`_retry_replies`).
- `runtime/bootstrap.py:97` — `max_reply_age_s=600` : au redémarrage, une question plus vieille que 10 min
  après son `due` est abandonnée en le disant.
- `faculties/body/__init__.py:198-216` — le réveil par une amie est jugé par l'interprète, avant tout
  `reply_wait`. Une parole au milieu de son sommeil n'émet pas de `body.woke` : elle compte comme activité, et
  elle se rendort 15 min après (`sleep.py:73`, `settle_us`).
- `faculties/self/night.py:320` — un journal est **réécrit** (`rev+1`) chaque fois qu'elle a parlé après l'avoir
  écrit, une « nuit coupée ». En (b), cela fait 11 appels `journal` par jour. Le rejoueur doit resservir le
  journal du jour, `call_id` se terminant par `#<rev>`, ou rendre un silence ; au-delà de 4 essais, `JOURNAL_TRIES`,
  ligne 272, abandonne.
- `faculties/agency/__init__.py:515` — la consigne d'une INITIATIVE dit « Personne ne vient de t'écrire ».
  Inoffensif avec le rejoueur, faux pour un vrai modèle si une réponse différée passe en INITIATIVE.
- `sim/llm/persona.py:164,177` — `PersonaSimLLM.calls` garde **tous** les prompts : c'est une fuite de mémoire sur une
  longue avance. Le script la neutralise (`deque(maxlen=0)`).
- `sim/world.py:111` — `slots=1` par défaut. Un rejoueur qui dormirait dans `complete()` tiendrait le seul créneau ;
  le script passe `slots=4`.
- Les extensions `email.poll` et `rss.poll` tournent ≈ 135 fois par jour virtuel sans aucune boîte ni aucun flux.
  Une composition « avance rapide » sans ces greffons gagnerait une part des 0,42 s par jour.
- numpy et OpenBLAS : 11 fils qui tournent à vide, et 28 % de temps en plus en densité (b).
- Le dossier de travail `backendv2/` peut être en cours de modification par une autre tâche : le jour de l'essai, il y
  avait une erreur de syntaxe dans `plugins/teams/tools.py`. Il faut toujours mesurer et avancer sur un instantané
  gelé.
- CLI : sans `stdin=DEVNULL`, 3 s perdues par appel.
