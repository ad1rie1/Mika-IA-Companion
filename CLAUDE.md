# CLAUDE.md

Ce fichier guide Claude Code dans ce dépôt : comment y travailler, et où trouver le reste. Mika est une compagne IA.
Le dépôt contient son moteur psychologique (`backendv2/`, paquet Python `mika`) et ses clients : le web en 3D, Unity,
Android et une extension Teams.

**Les références** — elles font foi, pas ce fichier :

- `backendv2/ARCHITECTURE.md` : l'architecture du moteur, chaque faculté et chaque plugin, le démarrage, le dossier de
  données et l'environnement, comment écrire une faculté, toutes les commandes ;
- `backendv2/docs/decisions.md` : les décisions et leur pourquoi (les « ADR » que le code cite par numéro) ;
- `backendv2/README.md` pour démarrer en local ; `backendv2/deploy/README.md` pour la mise en service ;
- dans `backendv2/docs/` : `protocole-chat.md` (`/ws`), `protocole-monde.md` (`mika.world/1`), `console-carte.md` (la
  console) ;
- `frontend/Web/README.md`, `frontend/Android/README.md`, `frontend/Extension/README.md`, `INJECTION/CLAUDE.md`.

En cas de désaccord entre une doc et le code, le code fait foi : corriger la doc.

## Organisation du dépôt

| Chemin | Ce que c'est |
|---|---|
| `backendv2/` | Le moteur : paquet `mika`, Python ≥ 3.12. Il contient `src/mika/`, `tests/`, `persona/` (`mika.yaml`, `voix.yaml`), `deploy/` (unités systemd), `docs/` (décisions et protocoles), `tools/` (bancs de mesure du vrai modèle) et `examples/` (une app forgée, un monde). |
| `services/mika-images/` | Serveur d'images local : stable-diffusion.cpp `sd-server` (Vulkan) avec Qwen-Image 2.1, démarré à la demande par des unités systemd utilisateur. Les poids et le binaire sont dans `/mnt/games/mika-images`. Mika s'y branche comme fournisseur d'images (ADR 0061). |
| `frontend/Web/` | Client web : Vite, Three.js, VRM, TypeScript. Contient `src/`, `public/`, `assets-src/` (sources Blender et scripts, partagés avec Unity) et `studio.html`. |
| `frontend/Unity/` | Client Unity : `Mika/` (le projet), `ArtSource/` (mocap, atelier), `tools/gen_world_protocol.py`. |
| `frontend/Android/` | Messagerie Android (Kotlin, Compose, paquet `fr.qwartz.mika`). Commencer par son `README.md`. Côté serveur, voir les ADR 0062, 0067 et 0077. |
| `frontend/Extension/` | Extension Chrome MV3 « Mika · Teams » (JS sans build). Elle lit ce que Teams web reçoit déjà et pose dans Teams ce que Mika a écrit (ADR 0069). Tests : `npm test`. |
| `INJECTION/` | Jumeau numérique (paquet `twin`, CLI `jumeau`). Des archives personnelles sont lues par Claude Code puis revécues en accéléré par le vrai noyau. `brut/`, `travail/` et `sortie/` contiennent des données privées et ne sont jamais commités. Il a son propre `CLAUDE.md`. |
| `scripts/ai_pipeline/` | Des agents auditent le dépôt, ouvrent des issues et les corrigent en PR, sur `backendv2/` et les trois clients. |
| `scripts/borne.sh` | La borne mémoire des commandes lourdes (voir plus bas). |
| `output/` | Captures de travail (aperçus de la console). Non versionné. |

## Règles de travail

**Le code et le dépôt**

- **Langue.** Les identifiants de code sont en anglais. Les prompts, l'interface, la documentation et les décisions
  sont en français.
- **Commits.** L'utilisateur committe lui-même (souvent des commits « update »).
- **Sessions parallèles.** D'autres sessions Claude travaillent parfois dans le même arbre. Avant de toucher un fichier
  partagé, regarder `git status` et `git log`. Ne jamais indexer un fichier qu'on n'a pas modifié.
- **Avis et relectures.** Pour donner un avis, relire ou vérifier qu'une chose est adaptée, on lit et on juge. On ne
  lance ni pytest, ni serveur, ni installation.

**La cohérence**

- **Une source par sujet.** Le moteur se décrit dans `backendv2/ARCHITECTURE.md`, ses protocoles dans `docs/`, chaque
  client dans son `README.md`. Ne pas recopier ailleurs ce qu'ils disent : y renvoyer.
- **La doc suit le code, dans le même lot.** Un changement qui modifie ce qu'une doc décrit la met à jour en même
  temps. `tests/architecture/test_docs_agree.py` confronte la doc au code (trames du chat, sous-commandes de la CLI,
  chemins cités, numéros d'ADR).
- **Une décision, une entrée.** Une règle qu'on ne doit ni casser ni reproposer s'écrit dans `docs/decisions.md`, au
  numéro suivant, sous la forme des autres entrées (et « Révisée par » sur celles qu'elle change). Pas de décision
  prise seulement dans le code.

**Les tests de `backendv2`**

- **L'interpréteur.** Les tests passent par `backendv2/.venv/bin/python -m pytest`, lancé depuis `backendv2/`. Le Python
  du système n'a pas le paquet.
- **Ordre de lancement.** D'abord les fichiers touchés, puis la suite par défaut, qui écarte les tests longs.
- **Les tests longs.** `--slow` les ajoute ; `-m slow` ne lance qu'eux ; nommer un fichier lance aussi les siens.
  `--slow` ne se lance que dans deux cas, et une seule fois : quand le changement touche ce qu'exercent les tests longs
  (scénarios complets du simulateur, vies de plusieurs semaines, performances, panne et rejeu), ou avant de rendre un
  gros lot. Ne pas relancer la suite complète pour confirmer.
- **Marquer un test lent.** Un test de plus de ~3 s reçoit `@pytest.mark.slow`. Si tout le fichier est long, poser
  `pytestmark = pytest.mark.slow`. Pour les trouver : `--durations=0 --durations-min=3`. Ne jamais marquer lent un test
  rapide pour le cacher. Ne jamais supprimer ni sauter un test long pour gagner du temps.
- **`--mariadb`** rejoue la suite sur des bases jetables du serveur MariaDB local ; le marqueur `sqlite_only` en
  écarte un test.
- **Volumes.** La suite compte plus de 2 200 fonctions de test, dont une cinquantaine de longues. Mesure du 2026-10-04 :
  ~10,5 min pour la suite entière, dont ~6 min de tests longs.

**La mémoire de la machine (30 Go)**

- Toute suite complète, tout simulateur et toute sonde passent par `scripts/borne.sh` (depuis `backendv2/` :
  `../scripts/borne.sh .venv/bin/python -m pytest -q`).
- Ce wrapper (`systemd-run --user --scope`) fixe un plafond de 3 Go sans swap et une durée de 25 min ; seule la
  commande est tuée au-delà (code 137 ou 124). Les deux se règlent par `BORNE_MEM` et `BORNE_TEMPS`.
- Une seule suite complète à la fois sur toute la machine, et au plus deux agents en même temps. En 2026-10, onze agents
  en parallèle ont provoqué un OOM qui a emporté VS Code.

**Les pièges du travail**

- **Assertions sur le source.** Ne jamais tester avec `inspect.getsource(...)` puis `in` : cela trouve aussi les
  commentaires, qui nomment justement ce qu'il ne faut pas faire. Passer par l'AST (`ast.parse`, `lineno`).
- **Mutation.** Après avoir restauré le code muté, faire `touch` sur le fichier et supprimer son `.pyc`. Sinon le
  bytecode muté survit.
- **Un seul serveur par dossier.** Un serveur par dossier de données (verrou `mika.lock`). Ne jamais effacer
  `mika.lock`. Ne jamais tuer un processus par un motif qui figure aussi dans sa propre ligne de commande.
- **Sondes et `/tmp`.** Pas de `/tmp` pour les sondes : il est vidé au redémarrage. Chauffer les plongements avant de
  juger un rappel.

**Les fournisseurs de modèles**

- **Claude Code comme moteur.** On lance la CLI `claude -p` avec son propre login. `setup-token` et
  `CLAUDE_CODE_OAUTH_TOKEN` sont interdits : le sous-processus ne reçoit jamais ce jeton.
- **Pas de repli entre fournisseurs LLM.** Un appel en échec est journalisé et propagé, sans basculer ailleurs
  (ADR 0073).
- **Dimensionnement.** Prompts et contexte se conçoivent pour l'API Claude hébergée. Ollama en local est la roue de
  secours, jamais ce qui fixe la taille.

## Commandes

```bash
cd backendv2
python3 -m venv .venv && .venv/bin/pip install -e ".[llm,memory,dev]"   # + documents (PDF), mariadb (PyMySQL)
.venv/bin/python -m mika serve                       # http://127.0.0.1:8001 ; données dans ./data/v2
.venv/bin/python -m pytest -q                        # --slow, -m slow, --mariadb
.venv/bin/ruff check src tests && .venv/bin/lint-imports
.venv/bin/python -m mika sim run --report sim-reports                   # voie rapide du simulateur
.venv/bin/python -m mika --data data/v2 sim sonde --semaine 1 --out sonde   # une semaine, vrai modèle
.venv/bin/python -m mika --help
```

Toutes les sous-commandes, leurs options et les codes de sortie : `backendv2/ARCHITECTURE.md`, « Commandes ». Le client
web : `frontend/Web/README.md` (`npm run dev` sur le port 3000 ; `npm run build` passe par `tsc`, la vraie barrière).

## Le moteur en bref

Mika est une psyché à **journal d'événements** : tout ce qui lui arrive s'ajoute au journal, et l'état de chaque
faculté s'en déduit par des fonctions pures. On peut donc rejouer sa vie, l'expliquer et la simuler.

```
app                         composition, serveur, CLI, console, réglages, schéma, sauvegarde
inspector | sim             la console, le simulateur
runtime                     le Mind générique : ajouts, épisodes, voies, arbitre, ordonnanceur, effets, projections, santé
faculties | plugins | adapters
contracts                   le contrat public de chaque propriétaire (événements publics, faits), sans logique
ports                       interfaces d'entrée/sortie, entités SQL
vocab                       types de valeur partagés par au moins trois propriétaires
kernel                      machinerie générique, sans un mot du domaine
```

Ce qui fait échouer un changement :

- **`lint-imports`** : une couche n'importe que celles du dessous ; une faculté n'importe ni une autre faculté ni un
  plugin, et l'inverse non plus ; les adaptateurs n'importent ni facultés, ni plugins, ni runtime ; facultés et plugins
  n'importent ni adaptateurs ni runtime ; ni le runtime ni l'inspecteur ne nomment une faculté.
- **`ruff`** : pas d'import dans une fonction ; pas de `except Exception` aveugle (sauf `runtime/boundary.py`,
  `adapters/**`, `sim/**`) ; ni l'heure, ni le hasard, ni un identifiant lus directement (sauf `adapters/**`, `sim/**`,
  `app/**`) : le temps vient de `kernel.clock`, le hasard du rng de l'événement, les identifiants de l'`IdGen` injecté.
- **Les gardes d'architecture** (`tests/architecture/`, leur table dans ARCHITECTURE.md), dont :
  - `Mind.append` est le seul point d'écriture ;
  - une charge utile ne porte jamais un état recalculé ;
  - un réducteur est pur et total ;
  - les facultés se lisent par des faits déclarés ;
  - tout texte gardé est un `Content` qui déclare ses `subjects=` (l'oubli doit l'atteindre) ;
  - ses phrases sont dans `persona/voix.yaml`, jamais en dur, et son nom vient de sa persona ;
  - ce qui sort de la machine est une capacité, après le commit.

La composition (facultés, plugins, politiques d'épisode, arbitrage, modes) est dans `app/composition.py`. Pour écrire
ou ajouter une faculté : ARCHITECTURE.md, « Écrire une faculté ».

## Tester

- **Où ils sont** : `tests/unit/` (le gros), `contract/` (les adaptateurs), `protocol/`, `scenarios/` (déterminisme,
  voie rapide, deux moteurs), `property/`, `architecture/`, `browser/console.cjs` (Playwright).
- **Les montages** :
  - `conftest.make_mind(tmp, faculties, clock=…)` donne un Mind nu ;
  - `tests/fixtures/mika.py::build(tmp, respond)` donne le vrai Kernel composé, avec `boot`, `connect`, `befriend`,
    `said`. La relecture et la seconde passe (ADR 0112) y sont coupées par défaut : `review=True`, `polish=True` ;
  - `tests/fixtures/harness.py` donne des facultés jouets.
- **Les bancs de mesure** (`tools/`) mesurent le vrai modèle par la CLI Claude Code, avec `claude-haiku-5-5` par défaut :
  - `tools/banc_lecture` mesure la lecture `[EN_FACE]` ;
  - `tools/banc_temperament` vérifie que la balise suit chaque profil ;
  - `tools/banc_conversation` (ADR 0112) fait vivre des conversations au vrai noyau (Sonnet par la CLI, effort high),
    face à un Adrien simulé (Haiku), jugées par Opus : un score sur 100, des scénarios réservés, chaque mesure sur une
    copie figée du code (`--variante`, `--profil`, `--voix api:sonnet`). Tout changement de sa voix s'y mesure.
  - `tools/banc_travail` (ADR 0145) mesure le travail sur un projet demandé, au regard de la demande :
    - le vrai noyau, avec la voix en Opus par la CLI ;
    - une Adrien simulée (Haiku) qui suit une fiche d'intention cachée ;
    - la Forge réelle, sur des sources figées ;
    - un juge Opus qui note le plan (/30), le travail (/50) et le suivi (/20).
    `--sec` fait tout tourner sans modèle ni réseau. Une mesure réelle coûte de 60 à 160 appels Opus par scénario :
    la demander d'abord.
  - pour les lancer : `PYTHONPATH=src .venv/bin/python tools/<banc>/banc.py [modèle] [parallèle] [sortie.json]`.
- **La sonde** (`sim sonde --semaine 1|2`) fait vivre une semaine au vrai modèle configuré ; elle refuse `claude_code`.
  Après une sonde réelle, on corrige tout ce qu'elle montre, puis on revalide en réel.

## À savoir

- **`--data` est relatif au dossier courant.** Lancé ailleurs, un nouveau `data/v2` vide naît. Un second serveur sur le
  même dossier sort avec le code 3.
- **Les commandes CLI qui écrivent les réglages** (`account`, `token create`, `llm`, `mail`…) ne prennent pas le verrou.
  La doc dit de les lancer serveur arrêté ; rien ne l'impose (`token revoke` marche serveur lancé).
- **Les opérateurs.** `mika account` sans `--operator` ne crée jamais d'opérateur. Seul le premier compte créé par le
  web (`/auth/bootstrap`) l'est d'office.
- **`serve --host`** autre que la boucle locale, `0.0.0.0` ou `::` vide l'adresse du relais MCP : les appels Claude Code
  échouent.
- **Claude Code.** Une boucle d'outils ne reprend pas après un redémarrage. Le plafond de quota vaut pour les appels de
  fond.
- **En service** : code dans `/opt/mika/backendv2`, données dans `/var/lib/mika`, environnement dans
  `/etc/mika/mika.env`, unités `mika.service` et `mika-backup.timer`. Une commande lancée à la main
  (`sudo -u mika … python -m mika`) ne lit pas `mika.env` : passer par la fonction `mika` de `deploy/README.md`, sinon,
  avec MariaDB ou `MIKA_SECRET_KEY`, elle crée des fichiers SQLite ou un nouveau `secret.key`. La restauration
  travaille dans le dossier de données même (ADR 0125).

## Les clients

- **Web** (`frontend/Web/`) : son architecture (voix et corps, animation, visage, locomotion, pièce, monde) est dans
  son `README.md`. Après une retouche de la pièce, relancer `run_final.py` (Blender), sinon le web et Unity divergent.
- **Unity** (`frontend/Unity/Mika/`) : client du monde (`mika.world/1`). Ses types C# du protocole sont générés depuis
  le schéma du noyau par `backendv2/.venv/bin/python frontend/Unity/tools/gen_world_protocol.py` ; avec `--check`, la
  commande échoue si le fichier a vieilli : régénérer après tout changement du protocole côté noyau (de même pour
  `frontend/Web/tools/gen_world_protocol.py`).
- **Android** (`frontend/Android/`) : messagerie à une seule conversation, fichiers dans les deux sens, Mika en 3D native
  (Filament), portraits pré-rendus en repli. Lire son `README.md`.
- **Extension** (`frontend/Extension/`) : lire son `README.md`.
