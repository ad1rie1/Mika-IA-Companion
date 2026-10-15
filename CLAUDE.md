# CLAUDE.md

Ce fichier guide Claude Code dans ce dépôt. Mika est une compagne IA. Le dépôt contient son moteur psychologique
(`backendv2/`, paquet Python `mika`) et ses clients : le web en 3D, Unity, Android et une extension Teams. Ce fichier
résume ce qu'il faut savoir pour y travailler. Les références sont ailleurs :

- `backendv2/README.md` pour démarrer en local ;
- `backendv2/ARCHITECTURE.md` pour l'architecture et le détail de chaque faculté ;
- `backendv2/docs/adr/` pour les décisions et leur pourquoi (0001 à 0112, d'autres arrivent) ;
- `backendv2/deploy/README.md` pour la mise en service (systemd, MariaDB, mandataire TLS, sauvegardes, Firebase) ;
- dans `backendv2/docs/` : `protocole-chat.md` pour le protocole du chat (`/ws`), `protocole-monde.md` pour celui du
  monde (`mika.world/1`), `console-carte.md` pour la carte de la console.

En cas de désaccord entre ce fichier et le code, le code et les ADR font foi : corriger ce fichier.

## Organisation du dépôt

| Chemin | Ce que c'est |
|---|---|
| `backendv2/` | Le moteur : paquet `mika`, Python ≥ 3.12. Il contient `src/mika/`, `tests/`, `persona/` (`mika.yaml`, `voix.yaml`), `deploy/` (unités systemd), `docs/` (ADR et protocoles), `tools/` (bancs de mesure du vrai modèle) et `examples/` (une app forgée, un monde). |
| `services/mika-images/` | Serveur d'images local : stable-diffusion.cpp `sd-server` (Vulkan) avec Qwen-Image 2.1, démarré à la demande par des unités systemd utilisateur. Les poids et le binaire sont dans `/mnt/games/mika-images`. Mika s'y branche comme fournisseur d'images (ADR 0061). |
| `frontend/Web/` | Client web : Vite, Three.js, VRM, TypeScript. Contient `src/`, `public/`, `assets-src/` (sources Blender et scripts, partagés avec Unity) et `studio.html`. |
| `frontend/Unity/` | Client Unity : `Mika/` (le projet), `ArtSource/` (mocap, atelier), `tools/gen_world_protocol.py`. |
| `frontend/Android/` | Messagerie Android (Kotlin, Compose, paquet `fr.qwartz.mika`). Commencer par son `README.md`. Côté serveur, voir les ADR 0062, 0067 et 0077. |
| `frontend/Extension/` | Extension Chrome MV3 « Mika · Teams » (JS sans build). Elle lit ce que Teams web reçoit déjà et pose dans Teams ce que Mika a écrit (ADR 0069). Tests : `npm test`. |
| `INJECTION/` | Jumeau numérique (paquet `twin`, CLI `jumeau`). Des archives personnelles sont lues par Claude Code puis revécues en accéléré par le vrai noyau. `brut/`, `travail/` et `sortie/` contiennent des données privées et ne sont jamais commités. Il a son propre `CLAUDE.md`. |
| `scripts/ai_pipeline/` | Des agents auditent le dépôt, ouvrent des issues et les corrigent en PR, sur `backendv2/` et les trois clients. |
| `output/` | Captures de travail (aperçus de la console). Non versionné. |

## Règles de travail

**Le code et le dépôt**

- **Langue.** Les identifiants de code sont en anglais. Les prompts, l'interface, la documentation et les ADR sont en
  français.
- **Commits.** L'utilisateur committe lui-même (souvent des commits « update »).
- **Sessions parallèles.** D'autres sessions Claude travaillent parfois dans le même arbre. Avant de toucher un fichier
  partagé, regarder `git status` et `git log`. Ne jamais indexer un fichier qu'on n'a pas modifié.
- **Avis et relectures.** Pour donner un avis, relire ou vérifier qu'une chose est adaptée, on lit et on juge. On ne
  lance ni pytest, ni serveur, ni installation.

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
- **Volumes.** La suite compte plus de 2 200 fonctions de test, dont une cinquantaine de longues. Mesure du 2026-10-04 :
  ~10,5 min pour la suite entière, dont ~6 min de tests longs.

**La mémoire de la machine (30 Go)**

- Toute suite complète, tout simulateur et toute sonde passent par `~/recup-audit-v2-2026-10-01/outils/borne.sh`.
- Ce wrapper fixe un plafond de 3 Go sans swap et une durée de 25 min. Les deux se règlent par `BORNE_MEM` et
  `BORNE_TEMPS`.
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
.venv/bin/python -m mika --data data/v2 replay --verify                 # rejeu depuis la genèse
.venv/bin/python -m mika --data data/v2 backup ARCHIVES --keep 14       # verify ARCHIVE · restore ARCHIVE [--force]
.venv/bin/python -m mika --data data/v2 profil reflechie                # profil de personnalité, serveur arrêté
.venv/bin/python -m mika.app.schema revision <base> "<message>"         # une révision Alembic
.venv/bin/python -m mika.vocab.phrasebook            # contrôle de persona/voix.yaml
.venv/bin/python -m mika --help
```

Toutes les sous-commandes de `mika` (`src/mika/app/cli.py`) :

| Sous-commandes | Rôle |
|---|---|
| `serve` | Lance le serveur. Options : `--port 8001`, `--host 127.0.0.1`, `--origin URL` (répétable ; remplace les origines de développement localhost/127.0.0.1 en :3000 et :4173), `--cookie-secure`, `--behind-proxy`, `--reports DIR`. |
| `replay --verify`, `rebuild <propriétaires…>`, `forget <sujet>` | Le journal et l'oubli. |
| `sim selftest\|run\|sonde` | Le simulateur. Options : `--profil`, `--semaine 1\|2`, `--backend`. |
| `profil [nom]` | La personnalité. |
| `backup`, `verify`, `restore` | Sauvegarder et restaurer. |
| `llm show\|backend\|route\|remove\|context` | Modèles. Types de fournisseur : `claude`, `claude_code`, `openai`, `ollama`, `ollama_cloud`. |
| `images show\|backend\|route\|remove\|essai` | Images. Types : `openai`, `sdcpp`, `openai_compatible`. Rôles : `draw`, `edit`, `own`. |
| `claude-code check\|login` | Le moteur Claude Code. |
| `account <nom> [--operator] [--full-name]`, `token create\|list\|revoke` (`--client screen\|mobile`) | Comptes et jetons. |
| `identity link\|unlink`, `social closeness <personne> <niveau\|auto>`, `forge promote\|demote <app>` | Identités, relations, apps forgées. |
| `mail`, `rss`, `stt` | Courrier, flux, transcription. |
| `mcp token\|serveurs\|essai` | MCP. `mcp token` imprime la ligne `claude mcp add` pour `/mcp/console`. |
| `sensors token`, `teams key\|revoke\|status`, `wakeup list\|key\|revoke` | Capteurs, Teams, réveils par API. |
| `console apercu --out DIR` | Aperçu de la console. |

Codes de sortie : 0 en cas de succès, 1 en cas d'échec, 3 quand un autre processus tient le dossier de données.

Les clients :

- **Web** : `cd frontend/Web && npm install && npm run dev` (port 3000, il vise `http://localhost:8001`, qu'on change
  par `VITE_BACKEND_ORIGIN` dans `.env.local`). `npm run build` passe par `tsc`, la vraie barrière ; `npm test` lance
  vitest.
- **Studio** : `npm run dev` puis `/studio.html` donne l'avatar sans backend ni connexion.

## Architecture du backend v2

Mika est une psyché à **journal d'événements**. Tout ce qui lui arrive s'ajoute au journal, et l'état de chaque faculté
s'en déduit par des fonctions pures. On peut donc rejouer sa vie, l'expliquer et la simuler (une semaine en quelques
secondes).

### Couches

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

**Ce que vérifie `lint-imports`** (configuré dans `pyproject.toml`, lancé aussi par `tests/architecture/test_composition.py`) :

- une couche n'importe que les couches du dessous ;
- une faculté n'importe jamais une autre faculté ni un plugin, et l'inverse non plus ;
- les adaptateurs n'importent ni facultés, ni plugins, ni runtime ;
- facultés et plugins n'importent ni adaptateurs ni runtime ;
- ni le runtime ni l'inspecteur ne nomment une faculté.

**Ce que vérifie `ruff`** :

- pas d'import dans une fonction (`PLC0415`) ;
- pas de `except Exception` aveugle (`BLE001`), sauf dans `runtime/boundary.py`, `adapters/**` et `sim/**` ;
- aucune lecture directe de l'heure, du hasard ni d'identifiants (`TID251`), sauf dans `adapters/**`, `sim/**` et
  `app/**`. Le temps vient de `kernel.clock`, le hasard du rng dérivé de l'événement (ou du `RngTree`), les
  identifiants de l'`IdGen` injecté.

### Le noyau (`kernel/`, `runtime/`)

- **Événements** (`kernel/events.py`)
  - Chaque type appartient à un propriétaire, qui seul l'émet. Les autres ne le réduisent que s'il est `public`.
  - Une charge utile porte des observations, des intentions, des deltas et des tirages enregistrés, jamais un état
    recalculé.
  - Les textes libres sont des `Content`, rangés à part et effaçables. Tout texte gardé déclare qui il concerne
    (`subjects=`), pour que l'oubli l'atteigne (ADR 0024).
  - Les types évoluent par versions et *upcasters*. Un type retiré se décode sans effet.
  - Origines possibles : external, process, tool, kernel, genesis.
- **Tranches et réducteurs**
  - Chaque faculté a une tranche immuable. Un réducteur est pur et total : s'il lève, la tranche est marquée
    `tainted` et la santé passe à `ko`.
  - Un réducteur lit les faits des autres tels qu'ils étaient avant l'événement (double tampon), les paramètres en
    vigueur (`kernel.params_changed`) et un hasard dérivé de l'événement.
  - Un instantané est pris tous les 500 événements ; on en garde 3. Une tranche dont la version change se reconstruit
    depuis la genèse, par clôture de lecture. Les facultés volatiles ne se rejouent pas.
- **Faits** (`kernel/facts.py`)
  - C'est le seul canal de lecture entre facultés. Chaque clé ou famille a un seul fournisseur, et le graphe est
    acyclique.
  - Les lectures sont déclarées ; une lecture non déclarée lève `UndeclaredRead`.
- **Écrire** (`runtime/mind.py::Mind.append`, le seul point d'écriture). Les étapes, dans l'ordre :
  1. dédoublonnage ;
  2. validation (l'émetteur possède le type ; provenance de la voix) ;
  3. **garde** : faits lus inchangés, prédicat, baux, épisode vivant — sinon `Superseded` ;
  4. estampille ;
  5. réducteurs ;
  6. une transaction menée jusqu'au bout (ADR 0021) ;
  7. publication.
- **Effets** (`runtime/effects.py`)
  - Les effets visibles partent après le commit, par une file de sortie à deux voies : `delivery`, et `capability`
    pour qu'une parole n'attende pas derrière un `git push`.
  - En cas d'échec, réessais espacés de 5 s à 10 min, 8 au plus.
  - Une parole de plus de 600 s ne part plus. Une réponse qui redit mot pour mot son dernier message non plus
    (ADR 0040, 0054). Les lignes faites sont purgées après 30 jours.
- **Capacités.** Ce qui sort de la machine est une capacité (`@f.capability(preview=…)`), exécutée tout de suite ou
  après accord. L'accord porte sur le condensé de l'aperçu que l'opératrice a lu : si l'aperçu a changé, l'accord est
  refusé (`runtime/decisions.py`).
- **Ordonnanceur** (`runtime/scheduler.py`)
  - Chaque processus déclare sa prochaine échéance ; s'il est en retard, il s'exécute avec `missed`.
  - Un processus qui échoue recule de 5 s, 10 s… jusqu'à 1 h. Un processus qui ne produit rien recule de 30 s… jusqu'à
    1 h. Un ajout entièrement dédoublonné n'est pas un progrès.
  - Au-delà de 120 passages par minute, une rafale le retient (1 min, puis 2, 4…) et la santé le montre (ADR 0040).
  - Deux voies : `model` (bornée) et `night` (exclusive).
- **Arbitre** (`kernel/arbitration.py`, `runtime/arbiter.py`)
  - Des preuves en log-odds par (type d'épisode, cible), cumulées, auxquelles s'ajoutent des modulations additives ou
    des vetos.
  - Le déclenchement est un processus de Poisson `λ_max · σ(score)`, indépendant de la cadence (ADR 0015). Seuils et
    taux sont dans `app/composition.py::arbitration()`.
  - Un épisode porte sur un seul sujet. Quand plusieurs candidats d'une ligne en ont un, seuls les arguments du plus
    fort passent.
- **Épisodes** (`runtime/pipeline.py`)
  - Étapes : admission, baux, départ gardé, enrichissements, composition, appel (une boucle d'outils unique,
    `runtime/tools.py`), analyse, relecture, seconde passe, prélude, commit gardé, règlement (ADR 0009).
  - **Relecture** (ADR 0112) : une parole de conversation livrée sans outil est relue (`reviewers`, branchés par la
    composition ; le relecteur est `expression.review`). Un tic repéré sur le brouillon (question à options, même
    ouverture, sa phrase redite, un second bonjour…) la fait réécrire une fois, la remarque « RELIS-TOI » glissée
    avant la fin de l'état interne.
  - **Seconde passe** (ADR 0112) : sa réponse (`REPLY`) est rendue naturelle au vu du fil par un second appel sur le
    texte seul (`polishers` ; la consigne est `expression.polish`). Elle coupe sans rien ajouter, et peut l'envoyer
    en plusieurs bulles (une ligne vide les sépare). Ses balises restent celles du premier jet. Elle ne se fait que si
    le rôle LLM `polish` a un modèle (sans repli).
  - Types d'épisode : REPLY, INITIATIVE, STEP, WORK, JOB, WAKE, WAKE_JOB, TASK, MURMUR. Leurs politiques sont dans
    `app/composition.py::policies()`.
- **Voies** (`runtime/lanes.py`)
  - `conversation` a 3 ouvriers et `background` 2.
  - Un tour de conversation reçoit une seule réponse, à son dernier message : une rafale de trois messages n'en donne
    pas trois. Jamais deux réponses en même temps à la même personne, ni deux initiatives à la fois.
  - Ce qu'elle ne peut pas dire est livré une fois par tour (`reply_failed`, `reply_abstained`).
- **Prompt** (`kernel/prompt.py`)
  - Les sections se déclarent avec une zone (stable, historique, volatile), des ancres, un rang de coupe et un
    plancher. Elles sont filtrées par la divulgation et budgétées : la réserve est calculée avant la composition.
  - L'historique est coupé avec hystérésis, et la coupe est mémorisée par fil pour garder le cache.
  - Le fil porte des repères de temps perçus (« [le lendemain, mardi 14h13] ») et, en salon, le nom de qui parle
    (« Nom : »). Son résumé est épinglé (ADR 0041).
  - Ce qui vient d'ailleurs est **cité** (section `untrusted`) et coupé en premier (ADR 0022).
  - Une section étiquetée `LAST` passe en tout dernier, juste avant le message : « TA RÉPONSE » (ADR 0112).
- **Passerelle LLM** (`adapters/llm/gateway.py`, `config.py`)
  - Routage par rôle (`vocab/episodes.py`). Un rôle se replie sur un autre (`FALLBACKS`, par exemple extract → reply),
    mais **jamais un fournisseur sur un autre** (ADR 0073). Un rôle « voix » exige la persona. Le premier fournisseur
    déclaré sert `reply` d'office, et les autres rôles y retombent — sauf `polish` (la seconde passe), qui n'a pas de
    repli : sans modèle déclaré pour lui, la passe ne se fait pas.
  - Les créneaux sont à priorité (`kernel/slots.py`) : dès deux créneaux, un est réservé au premier plan. Délais :
    120 s en conversation, 300 s en fond. Une trace chiffrée par appel au registre des appels (`adapters/llm/calls.py`).
  - **Claude Code** (`adapters/llm/claude_code.py`, ADR 0026, 0072) : la CLI `claude -p`, isolée, avec deux serveurs
    MCP relais (`mika`, `mika_plus`) servis sur `/mcp/relais` en boucle locale. C'est le runtime qui exécute les
    outils, et les appels d'un même message font un seul tour, dans l'ordre écrit. La CLI ajoute d'elle-même une
    identité d'agent, un rappel `userEmail` et un bloc « # Environment » autour du prompt ; aucun réglage ne les
    retire et on ne les retire pas (ADR 0112).
  - **API** (`adapters/llm/claude.py`, le SDK Anthropic) : `workspace` pour une clé non attachée à un espace de travail
    (`--workspace`), `effort` pour la réflexion adaptative native (`thinking`, `output_config`), comme la CLI.
  - Les lots d'outils hors du socle d'un épisode sont « à la demande » : le modèle les cherche, guidé par un catalogue
    d'une ligne par lot. Exception : Ollama et les compatibles OpenAI ne savent pas différer (`defers_tools=False`) et
    reçoivent tout. Un outil peut clore la boucle quand il réussit (`ToolSpec.ends_loop`).
- **Passerelle d'images** (`adapters/imaging/`, ADR 0061)
  - Même forme que la passerelle LLM (fournisseurs, rôles, créneaux), mais **avec** une chaîne de replis entre
    fournisseurs.
  - Un refus de modération est une réponse : il n'est jamais redemandé à un autre service hébergé.
  - Elle est désactivée tant qu'aucun fournisseur n'est branché.
- **Paramètres** (`runtime/params.py`) : chaque valeur vient de la chaîne défaut ← tempérament ← réglage ← surcharge.
  Tout paramètre porte un `Knob` borné.
- **Opérations** (`runtime/operations.py`) : un seul chemin pour la console et la CLI. On valide, on propose, on
  exécute, on vérifie les types émis, on ajoute (origine extérieure) et on audite (`runtime.operated`).
- **Traces et santé**
  - Les traces (`runtime/traces.py`) vivent dans `views`, 14 jours.
  - `runtime/health.py` fait dix contrôles : journal, tranches, boucles, projections, processus, sorties, llm, voies,
    config, ports.

### Démarrage, dossier de données, environnement

**Démarrage** (`app/server.py::serve`)

1. Prendre le verrou du dossier.
2. Lire la persona. La persona éditée dans la console prime sur `persona/mika.yaml`. Une persona illisible est dite en
   français, et elle repart sur la dernière gardée (ADR 0057).
3. `schema.migrate_data` passe chaque base à sa dernière révision, **avant toute ouverture**.
4. `Kernel.boot()` (`runtime/bootstrap.py`) : rejeu, invariants de composition, ports, outils, configuration
   journalisée.
5. Réglages, comptes (`register_accounts`), LLM, images, MCP, hub, monde, constellation.
6. Attente des plongements, 30 s au plus.
7. `live()` : les voies démarrent, puis `recover()` clôt les épisodes ouverts comme `interrupted`. Un tour resté sans
   réponse est repris une fois sur son dernier message, ou abandonné après 600 s ou deux tentatives. Viennent ensuite
   l'ordonnanceur, la file de sortie et les projections.

uvicorn est forcé en `loop="asyncio"` : uvloop casse pasta.

**Le dossier de données** (`--data`, défaut `data/v2` **relatif au dossier courant** : lancer depuis `backendv2/`)

- les bases `mind.db` (sa vie, qu'on sauvegarde), `views.db` (jetable : projections différées, vecteurs, registre des
  appels, traces, séries), `mail.db`, `feeds.db` et `teams.db` ;
- `secret.key` (Fernet, 0600, créé au premier démarrage sauf si `MIKA_SECRET_KEY` est posé) ;
- `mika.lock` (le pid), `sauvegardes.json`, l'éventuel `firebase-service-account.json` ;
- les dossiers `partages/` (les fichiers qu'elle envoie) et `pieces/` (ce qu'on lui envoie), tous deux 0700 et gardés
  hors du journal, puis `forge/`, `ateliers/` et `mcp/`.

La persona et `voix.yaml` se trouvent depuis l'installation, pas depuis le dossier courant. Les dossiers d'appel de
Claude Code sont sous `$XDG_RUNTIME_DIR/mika/claude-code/<hash>`.

**Les variables d'environnement**

- `MIKA_SECRET_KEY` : la clé des secrets ;
- `MIKA_DATABASE_URL` : un serveur MariaDB, par socket Unix, pilote PyMySQL ;
- `MIKA_DATABASE_PREFIX` : le préfixe des noms de base, `mika_` par défaut ;
- `MIKA_VOIX` : un autre fichier de voix, pour un jumeau ;
- `MIKA_EMBEDDINGS_MODEL`, `MIKA_EMBEDDINGS_DEVICE` : le modèle de plongements et son appareil (`cpu`, `cuda`, `auto`), ADR 0109 ;
- `MIKA_WEB_*` : le plugin web ;
- `MIKA_TEST_MARIADB` : seulement pour les tests.

Il n'y a pas de `.env`.

### Persistance (ADR 0101)

- **Moteurs.** SQLAlchemy et Alembic, sur SQLite (tests, simulateur, jumeau) comme sur MariaDB (sa vie en service).
- **Bases.** Chaque base a sa base déclarative dans `ports/sql.py` : `MindBase`, `ViewsBase`, `MailBase`, `FeedsBase`,
  `TeamsBase`. Les entités sont déclarées dans le paquet qui les possède. Une clé est une `Key(n)`, bornée à l'écriture.
- **Migrations.** Une révision par base dans `app/migrations/{mind,views,mail,feeds,teams}/versions/`.
- **Projections.** Leurs tables se déclarent par `projection_table`, hors des migrations : une projection évolue par sa
  version et une reconstruction. Ses vues se déclarent par `create_view`.
- **Requêtes.** Toute requête est une requête SQLAlchemy. Celles qui passent des milliers de fois sont préparées
  (`Prepared`). Aucun SQL propre à SQLite (`tests/architecture/test_sql_portable.py`).
- **La voie `--mariadb`.** Elle rejoue la suite sur des bases jetables. `tests/scenarios/test_engines_agree.py` vit la
  même vie sur les deux moteurs et compare les lignes.
- **Sauvegarde** (`app/backup.py`)
  - Un tar.gz avec un manifeste : tête du journal, état rejoué, empreinte du code, sha256 de chaque fichier.
  - `views.db` est exclu. Sur MariaDB, l'archive ajoute un `mariadb-dump` de chaque base.
  - La vérification rejoue l'archive. Si le code a changé, elle exige seulement d'atteindre la même tête sans tranche
    corrompue.
  - La restauration met l'ancien dossier de côté (`<data>.avant-restauration-…`).
- **Oubli** (ADR 0024, 0073)
  - L'oubli d'un sujet efface ses `Content`, ses archives, ses caches et ses alias. Une projection reconstruite ne fait
    pas revenir ce qui a été oublié.
  - L'oubli d'un nom (`name:…`) le remplace par un jeton opaque dans les enveloppes du journal.

## Les facultés

19 facultés, composées dans cet ordre (`app/composition.py::faculties()`) : presence, identity, transcript, memory, body,
world, place, affect, needs, others, attention, self, expression, social, agency, goals, projects, shares, attachments.
Neuf facultés dérivent leurs paramètres du tempérament (`derive=`) : attention, self, agency, social, goals, others,
affect, needs et body. Trois n'émettent aucun événement : affect, agency et expression. Le détail de chaque faculté et
ses identifiants sont dans `ARCHITECTURE.md`. Ce qui suit dit l'essentiel de chacune.

### Être là, savoir à qui l'on parle

- **presence** (volatile)
  - Les connexions vivantes.
  - Qui est en train de lui écrire (`presence.COMPOSING`, borné). Pendant ce temps, la réponse à son message précédent
    attend la suite, et aucune initiative ne part vers cette personne.
- **identity** (ADR 0012, 0035, 0048, 0075, 0092)
  - Ce qu'elle tient : adresses (*handles*), confiance du transport, revendications, preuves, liaisons, divulgation.
  - La propriété se juge sur **l'adresse qui parle** (`audience.owner`), jamais en salon public.
  - Une liaison par recoupement demande deux preuves sur deux messages. Le fil des autres adresses reste fermé tant
    qu'un opérateur n'a pas confirmé.
  - Un nom dont on lui a parlé (`name:alice`) ne se relie à une personne que par un opérateur. La seule personne
    connue de ce nom est seulement présumée (`identity.presumed`), et l'oubli de la personne emporte ce qu'on
    présumait d'elle.
  - La divulgation a une facette `untied_level` : ce qui peut se dire nommément de quelqu'un à une personne qui n'a
    aucun lien avec lui.
  - Outils : `identity_whoami_with`, `identity_doubt`, `identity_forget_binding`.
- **transcript**
  - Le fil (l'id d'un message est son `seq`) et les résumés des fils longs.
  - Un message resté sans réponse le dit dans son repère, en mots (une panne, lu trop tard, un silence choisi), jamais
    par la cause technique.

### Sa mémoire

**memory** est la plus grosse faculté, une vingtaine de modules (ADR 0010, 0034, 0043, 0046, 0052, 0055, 0074–0087,
0091, 0092, 0099, 0102). Elle tient les souvenirs, les croyances, les promesses et les échanges.

- **Consolidation**
  - Par conversation : une relecture par le modèle, puis un index de vecteurs et un rappel hybride filtré.
  - Les similarités de l'index sont centrées sur le fond du modèle : 0 pour un texte sans rapport, 1 pour
    l'identique. Les seuils valent ainsi pour tout modèle. Une comparaison entre souvenirs passe `document=True`
    (ADR 0111). Le monde lu est dans le même index que ses proches, sans personne (ADR 0110).
  - Une extraction invalide va dans une file durable, reprenable dans Mémoire › Consolidation, sans bloquer le curseur.
  - Une panne passagère du fournisseur fait attendre la fenêtre. Une paire trop longue pour le contexte attend un
    opérateur.
  - Ses répliques à elle ne deviennent pas des souvenirs.
- **Une seule porte** (`test_memory_has_one_door.py`)
  - Hors de la faculté, sa mémoire ne se lit que par les vues de `contracts.memory` (`KNOWLEDGE_VIEW`…).
  - Chaque ligne y porte sa filiation, et le verdict est commun : `vocab.knowledge`, `vocab.lineage.admits`,
    `vocab.privacy.admissible`.
  - Un texte qui en dérive garde ce que ses sources permettent : un rêve, une pensée, son journal, son récit, son
    portrait. Le secret que Bob a confié sur Sam ne revient pas à Sam par un rêve.
  - Quand une source change, ce qui en dérive suit (`contracts.memory.withdrawals`). Devenue secrète, la source fait
    taire tout de suite ce qui la reprenait. Remplacée ou contestée, elle fait réécrire le récit et le portrait.
- **Confidentialité**
  - Chaque élément sait qui l'a confié (`told_by`) et qui l'a entendu.
  - Un secret explicite ne quitte jamais son confident. Il ne sort jamais en salon, même devant celui qui l'a confié,
    et il ne laisse pas deviner qu'il existe. Elle sait qu'elle sait (« ce n'est pas à moi d'en parler »).
  - Une confidence peut s'ouvrir aux proches.
  - Ce qui touche un sujet délicat d'une personne devient une confidence, pour toutes les facultés (`memory.delicate`).
  - **Nommer exige un lien.** La vie de quelqu'un ne se dit nommément, au-delà de l'anodin, qu'à une personne qui a un
    lien déclaré avec lui ou qui était là. Sinon elle se raconte **sans nommer** : une version sans nom écrite par la
    relecture, graduée, jamais pour un secret ni pour la vie de sa propriétaire, et seulement en réponse.
- **Croyances**
  - Une croyance est une proposition et ses témoignages (`memory_testimonies`, `memory.attested`). La confiance se met
    en commun sur des témoins distincts.
  - Elle naît bornée par sa nature : 0,8 pour une chose dite, 0,9 pour une chose vue, 0,6 pour une déduction.
  - La personne concernée, un témoin de première main, ou le même témoin qui se corrige remplacent la croyance
    (`superseded_by`). Une source moins sûre la conteste seulement : elle doute, et le dit en attribuant chaque version
    à son témoin.
  - La croyance porte depuis quand et jusqu'à quand elle est vraie.
  - Changer d'avis sur ce qui la définit se ressent.
- **La vie des autres**
  - Les moments de leur vie (`memory.life_events`, situations en cours, `memory.situation_ended`). Chaque moment a un
    fil (`memory.moment_thread`) et une issue constatée (`memory.resolved`).
  - Les dates annuelles (`yearly`) : un anniversaire, la date d'un deuil.
  - Quand quelque chose de grave la touche, le banal se tait (`memory.hard_times`, `memory.heavy_date`).
  - Ce qu'elle voit venir (`memory.ahead`, section « CE QUI VIENT »).
  - La précision d'une date est gardée (`vocab.timespan`). La portée distingue le monde (`world`) de ce qu'elle vit à
    travers quelqu'un (`shared`) : elle n'a pas de corps et ne s'invente pas de vie physique.
- **Ressenti** : chaque élément porte ce que la personne en ressent et ce qu'elle-même en ressent (`felt`, `empathy`),
  en facettes de 0 à 1 jugées par la relecture. Chaque élément est relié à ses émotions (`memory_feelings`).
- **La nuit**
  - Elle relit ses lectures (`memory.reread`) : des croyances d'origine `read`, au plus 0,7. Ce qu'elle a lu pour
    quelqu'un en conversation porte son nom (`asked_by`), et seules les nouvelles et les faits publics en restent,
    entendus par cette personne (ADR 0110).
  - Elle réunit les doublons (`memory.joined`) et confronte deux témoins (`memory.confronted`).
  - Ce qui lui tient à cœur dans le monde se vérifie deux fois par semaine (`memory.to_check`).
- **Promesses et mensonges**
  - Une promesse datée se tient le jour dit (`memory.keep_promise`).
  - Un mensonge pour botter en touche est retenu, étiqueté (`memory.lies`), pour l'avoir devant cette personne
    seulement.
  - Ce qu'elle dit d'elle-même (goûts, avis, faits) la définit et tient.
- **Outils** : `memory_search` (avec `ressenti`), `memory_promise_done`.

### Son corps et ses besoins

- **body** (ADR 0016, 0036)
  - Rythme circadien et sommeil à deux processus.
  - La nuit, seule une amie ou une proche la réveille (réglage `woken_by`). Les autres attendent son réveil et
    reçoivent une réponse par personne (`KernelDeps.reply_wait`).
  - Un réveil par API qui passe outre son rythme la tire du sommeil (`body.roused`).
- **world** (ADR 0050, 0051, 0098)
  - Son monde et son corps dedans : pièces, lieux, objets. Le monde par défaut est `faculties/world/chambre.json`.
  - Outils `go_to` et `interact` ; section « AUTOUR DE TOI ».
  - Le coucher et le bureau sont des réflexes. Chaque geste se conclut à son échéance.
  - Une opératrice édite le monde, et elle remarque ce qu'on a changé chez elle.
  - Désœuvrée, elle s'occupe de ce qui nourrit ce qui lui manque (`occupy_per_day`).
- **place** : vue de compatibilité (`place.moved`, `place.current`, `place.since`). Le client web reçoit
  `inner_state.place` et `inner_state.activity` (ADR 0049).
- **needs** (ADR 0047, 0094, 0098)
  - La compagnie, s'exprimer, apprendre ; le vide ressenti.
  - La compagnie se comble selon qui la donne : pleinement par une amie, peu par une inconnue, davantage par sa
    propriétaire.
  - Les retrouvailles après un vide (`needs.reunited`).
  - S'occuper efface le vide au prorata de ce que l'occupation a comblé, jamais la solitude.

### Sa vie intérieure

- **affect** (ADR 0032, 0047, 0093–0095, 0102, 0107) n'émet rien. Il réduit les événements des autres et reçoit les
  évaluations (`@f.feels`, il est le seul à le faire).
  - Trois échelles : le moment, le fond de la journée, la relation (une ancre qui guérit, un attachement lent
    `affect.bond`). Les impulsions visent un point depuis le repos.
  - Humeur et posture visent le mélange de ses facettes déclarées.
  - Ce qu'une personne lui fait vivre colore sa posture envers elle, toutes ses adresses réunies.
  - Chaque cause se dit : un code `vocab.causes`, une phrase.
  - L'écran montre le visage qu'elle laisse voir (masque, défense, repli), pas sa balise brute.
  - Des excuses sincères pardonnent, selon la proximité. Une déception blesse (ADR 0107, en cours).
- **attention** (ADR 0043, 0046, 0053, 0058, 0076, 0086, 0098)
  - Les signaux remarqués (habituation, dosage) et les pensées (« CE QUE TU AS REMARQUÉ »).
  - Les attentes par personne (`attention.awaiting`) ; une conversation close n'attend rien.
  - La digestion nocturne.
  - Une pensée née d'un échange naît quand il s'est posé, de son moment le plus marquant.
  - Une amie silencieuse lui manque encore, de plus en plus rarement.
  - Des excuses sincères apaisent une dispute. « J'ai menti à X » est une gêne qu'elle porte devant X seulement.
  - L'anticipation d'un moment qui approche se ressent une fois par jour (`attention.anticipated`).
  - La jalousie (`attention.envied`).
  - Seule et désœuvrée, un souvenir ancien lui revient de lui-même (origine `reminiscence`).
  - Outil `attention_thoughts`.
- **others**, la théorie de l'esprit (ADR 0028, 0035, 0043, 0046, 0052, 0054, 0093, 0094)
  - **Ce qu'elle sent des gens, c'est le modèle qui le lit** en répondant (`[EN_FACE: …]` : des facettes, un geste
    envers elle, un événement grave), jamais une liste de mots. Le banc `tools/banc_lecture` mesure ce jugement.
  - Elle apprend le ton habituel de chacun, sa surprise, ses délais et ses heures de réponse (`others.hours`).
    L'inquiétude la pousse à prendre des nouvelles (`others.CHECK_IN_AT`).
  - Les motifs de ses initiatives : un mot la veille d'un événement (`cheer`), « alors, cet entretien ? » une fois le
    moment passé (`follow_up`), un anniversaire le jour même (`celebrate`), un mot doux à une proche le jour d'un deuil
    (`remembrance`). Jamais sur la foi d'un tiers.
  - Elle reconnaît un au revoir à sa forme (`others.farewell`).
  - Les heures d'une personne ouvrent sa nuit à elle, jamais ne ferment sa journée.
- **self** (ADR 0019, 0036, 0043, 0053, 0070, 0087–0090, 0096, 0100)
  - Persona et tempérament. Sa voix en chat se montre par des exemples (`samples`), en conversation seulement.
  - **La matrice de personnalité** (`vocab/temperament.py`) :
    - 28 curseurs de 0 à 1 en six familles : ressentir, montrer, agir, les autres, elle-même, le corps ;
    - un fond (`background`), une réaction quand on la blesse (`reaction`), une défense quand on la touche (`defense`),
      des notes ;
    - 18 profils (`PROFILES`), `reflechie` par défaut ;
    - chaque faculté à `derive=` en tire ses paramètres ;
    - `faculties/self/character.py` dit les traits au modèle, partout où la persona est injectée ;
    - ses règles de conduite ne dépendent pas du profil.
  - Une estime qui a des causes (sociomètre, `self.touched`).
  - Le récit de soi (« qui elle devient », jamais un prénom), le journal de la journée et sa version « à raconter »,
    les rêves posés au réveil (`self.woke_with`).
  - Ce qu'elle sait d'elle (`self.knows`).
  - Des centres d'intérêt vivants (`self.interests`, nourris la nuit par `self.reflect`). Une réflexion n'est pas un
    exploit.
  - Sa nature (une IA qui le sait, ou `nature: incarnee`) et son nom viennent de la persona, jamais d'un prompt écrit
    en dur.
  - Outil `self_journal`.
- **expression** (ADR 0043, 0054, 0076, 0093) n'émet rien.
  - Elle analyse la réponse : la balise d'émotion en facettes (`[EMOTION: sad 0.6, love 0.3]`), `[EN_FACE: …]` et
    `[MENSONGE: …]`, retirés du texte livré.
  - Elle tient le style, le murmure (un prélude : à la personne visée, ou voix intérieure) et la livraison.
  - Section « CE QUE TU TE RÉPÈTES ».

### Ses liens et ce qu'elle entreprend

- **social** (ADR 0013, 0018, 0035, 0058, 0094)
  - Les rythmes de contact et les profils (nourris de ce que la personne a dit elle-même).
  - La proximité : une fenêtre glissante, un plancher d'histoire, l'attachement. La réciprocité. Une amitié se mesure
    au temps vécu ; l'assiduité seule ne fait pas une proche.
  - Les faits `social.TIES`, `social.REKINDLE`, `social.CIRCLE` et `social.WEIGHT` (ce que compte sa propriétaire,
    réglage `owner_weight`).
  - Elle remarque, une fois, qu'un lien a changé (`social.bond_shifted`). À la mise en service, les niveaux du jour sont
    relevés sans être vécus (`social.bond_noted`).
  - Outil `social_about`.
- **agency** (ADR 0033, 0044, 0047, 0048, 0054, 0058, 0094) n'émet rien.
  - Le budget d'initiatives, la période réfractaire et les vetos.
  - **Ne pas harceler** : après une initiative sans réponse, plus rien vers la personne, sauf une relance douce.
  - Les motifs sont dans `contracts/agency.py` :
    - `OWED` et `INFORMS` (ce qui est dû et ce qui prévient passent la rancune) ;
    - `ONCE_MORE` (une seule prise de nouvelles longtemps après) ;
    - `CROSSED_MOTIVES` (« j'allais justement t'écrire ») ;
    - `NOT_REACHABLE` (on n'écrit pas à quelqu'un pendant sa nuit).
- **goals** (ADR 0020, 0030, 0043, 0053, 0089, 0094, 0096, 0097)
  - Ce qu'elle se propose de faire ensuite : rappels, explorations, rêveries, réflexions, tâches.
  - Une rêverie se vit d'un trait, deux par jour au plus, et n'est jamais une nouvelle. Une réflexion tient en une
    séance et ne « bloque » jamais.
  - Un but garde la filiation de la pensée d'où il est né (`goals.audible()`).
  - Outils : `report_step` (clôt la boucle) et `goal_*`.
- **projects** (ADR 0031, 0039, 0104)
  - Des boîtes noires qu'on pilote : des objectifs ponctuels ou constants à cadence.
  - Deux sortes d'exécution : `WORK` dans son mode à elle (rôle `project`), ou `JOB` impersonnel (rôle `job`, sans
    persona ni affect). Une exécution se prouve par un commit ou par un outil qui produit.
  - Les décisions techniques.
  - Un atelier par projet (`ateliers/projet-<id>`) avec git et un dépôt distant https : pousser et récupérer sont des
    capacités, et le jeton ne passe que par l'environnement de git. La plage de travail en jours et heures.
  - Elle ouvre ses projets elle-même (`start_project`, deux au plus) et les clôt ; `create_project` reste à la
    propriétaire.
  - Pilotage de vive voix en privé (`project_steer`). Outils d'atelier `ws_*`.
  - Un projet se donne ses outils (`project_equip`) et héberge des apps forgées, qu'il répare par un objectif
    « Réparer ».
- **shares** (ADR 0062)
  - Les fichiers qu'elle envoie (`share_text`, `share_project_file`), en privé à une personne authentifiée.
  - Les octets restent dans `partages/`, hors du journal.
  - Section « CE QUE TU LUI AS DÉJÀ ENVOYÉ ».
- **attachments** (ADR 0106)
  - Ce qu'on lui envoie : photos, documents, vocaux. Gardé dans `pieces/` ; la même pièce renvoyée par la même adresse
    n'en fait qu'une.
  - Chaque pièce est lue de près en fond. La relecture désigne les pièces d'où vient un souvenir (`pieces`).
  - Outils : `attachments_search`, `attachment_open`, `attachment_link`.
  - 2 Gio par personne, visibles dans la console.

### Les plugins

Les plugins ont la même forme que les facultés mais une confiance restreinte : des signaux, des preuves, des sections
citées, jamais la parole forcée. Leur monde vit hors du journal. Dix sont composés dans cet ordre.

- **email** (ADR 0027, 0037)
  - Plusieurs boîtes IMAP/SMTP et leurs dossiers, avec sa voix par boîte.
  - Rien ne part sans accord : un brouillon est relu et retouchable par un opérateur, puis envoyé par la capacité
    `email.send`.
  - Des réponses préparées d'elle-même par tâche silencieuse (`task:email:<réf>`).
- **rss** : un titre qui touche ce qu'une amie lui a dit aimer lui fait penser à elle (`rss.thought_of`), en privé
  seulement.
- **camera** : `camera_look`, et le WebSocket `/ws/camera`, réservé aux opérateurs.
- **forge**, ses apps (ADR 0005, 0023, 0039, 0101, 0104, 0105)
  - Hors processus, sous bubblewrap. Une version qui touche des secrets, ou une promotion, est mise de côté et proposée
    (capacité `forge.install`).
  - Une base par app, que l'hôte interroge pour elle (`api.query`, `api.execute`, `forge_db_*`).
  - Une app vit dans un projet et a plusieurs services planifiés. Ses outils sont déclarés et vérifiés par l'hôte.
  - Son réseau est libre (tout Internet, jamais la machine ni le réseau local). Un opérateur la valide une fois pour
    toutes ses versions.
  - Des files de signaux jugées par lots sous quota.
  - Outils `forge_*`. Exemple : `examples/forge/veille_hn/`.
- **sensors** : `POST /api/perceptions` (jeton : `mika sensors token`).
- **imaging** (ADR 0061, 0063) : elle dessine pour sa propriétaire ou pour une personne authentifiée, en tête-à-tête
  (`draw`, `show_drawing`). Un plancher légal s'applique à tous.
- **mcp** (ADR 0064) : les serveurs MCP branchés par l'opérateur, à une adresse ou lancés ici sous bubblewrap. Les
  outils sont approuvés un par un avec leur empreinte, et un outil changé est suspendu (capacité `mcp.call`).
- **web** (ADR 0066) : sans outil à lui. Il apporte au client MCP un serveur système (DuckDuckGo et lecture de pages,
  dans une cage au réseau isolé).
- **wakeup** (ADR 0068)
  - `POST /api/wake/<nom>` avec la clé de ce réveil, dont seule l'empreinte est gardée.
  - Le texte apporté est cité, et les consignes du réveil priment.
  - Un épisode `WAKE` ou `WAKE_JOB`, avec les seuls outils du réveil.
- **teams** (ADR 0069)
  - L'extension apporte les conversations Teams sur `/api/teams/inbox` et `/api/teams/outbox`, avec une clé `mtk_…`.
    Rien ne parle à Microsoft depuis le serveur.
  - Le monde est dans `teams.db`.
  - Elle rédige à la place de la personne. La capacité `teams.send` sert trois modes : brouillon (le défaut),
    validation, autonome.

## Autour du noyau

- **Le chat** (`adapters/web/`, protocole complet dans `docs/protocole-chat.md`)
  - **Routes HTTP** : `/auth/whoami|login|bootstrap|logout|token|push`, `/health`, `/files/<id>`,
    `/api/perceptions`, `/api/wake/<nom>`, `/api/teams/…`, `/api/projects/pending/<id>/approve|reject`.
  - **WebSockets** : `/ws`, `/ws/camera`, `/ws/world`.
  - **Trames du serveur** : `speech`, `history`, `ack`, `inner_state_update`, `emotion_update`, `presence`, `composing`,
    `read`, `approvals`, `approval_result`, `pong`.
  - **Trames du client** : `identify`, `chat`, `sync`, `ping`, `presence`, `composing`, `read`, `approval`.
  - Une réponse ne part qu'aux connexions de sa personne, un murmure qu'à celles de sa cible, et une seule voix sonne
    entre deux onglets.
  - Une ligne vide dans sa réponse sépare deux bulles : le serveur garde un message, les clients le montrent bulle par
    bulle au rythme de la frappe (web `ui/bubbles.ts`, Android `BubbleContent.parts`, ADR 0112).
  - Le fil porte l'empreinte de sa vie (`life`) ; une réponse qui n'a pas pu venir est `no_reply`.
  - On lui écrit par une application dédiée et un compte : **il n'y a plus de Telegram** (ADR 0060). Un compte
    extérieur (`ext_…`, canal `external`) reste prévu pour les canaux non sécurisés.
  - Les clients natifs s'authentifient par jeton (`mw_…`) : `POST /auth/token` pour Android, `mika token create` pour
    un moteur de jeu.
  - Android : fermée, l'application ne garde rien d'ouvert. Ce que Mika lui dit part par Firebase, scellé pour ce
    téléphone en AES-GCM (ADR 0062, 0077).
- **Le monde** (`/ws/world`, `mika.world/1`, ADR 0051)
  - Rôles : `viewer`, `host` (un seul, par bail), `creator`.
  - Chaque commande passe par le verdict de la faculté.
  - Le journal part traduit en trames ; une connexion lente est fermée plutôt que de sauter une trame.
- **La cage** (atelier et Forge, ADR 0039)
  - bubblewrap **sans repli**, un environnement reconstruit.
  - Le réseau est coupé, sauf capacité approuvée : il passe alors par `pasta` (paquet `passt`) et `ip`, sans repli.
  - Mémoire, CPU, fichiers et sortie sont bornés. Les délais se tiennent en tuant le processus.
- **La console** (`/inspecteur/`, opérateurs, ADR 0025, 0029, 0042, 0045, 0103)
  - Un back-office que **les facultés déclarent** : des vues, des fiches d'objets dont chaque faculté ajoute les
    onglets, des actions journalisées, des vitaux, des badges « à traiter », des courbes.
  - Les destinations et libellés sont dans `app/console.py`, le menu dans `app/console_menu.py`. Les réglages sont dans
    `app/reglages.py` : des modèles pydantic annotés `Knob`, et les secrets ne sont jamais réaffichés.
  - Il y a une page de paramètres par faculté, qui dit la provenance de chaque valeur.
  - `/inspecteur/parole/<seq>` répond à « pourquoi a-t-elle dit ça ? » (ou « pourquoi n'a-t-elle pas répondu ? ») et
    offre « Rejouer avec… » un autre fournisseur.
  - La constellation (`/inspecteur/constellation`) montre sa mémoire en points, et ce qui la parcourt en direct.
  - `/mcp/console` sert les mêmes lectures à un agent, en lecture seule, en boucle locale, avec le jeton de
    `mika mcp token`.
  - `/` mène à la console, qui crée le premier compte opérateur.
- **Santé** (`/health`, public) : des noms et des états seulement. 503 tant qu'elle n'est pas prête ; « dégradé » quand
  le fournisseur qui la fait répondre échoue ou qu'aucun ne sert `reply`.
- **Sa voix** (`persona/voix.yaml`, ADR 0071)
  - Le fichier contient toutes les phrases que le modèle lit ou qu'elle dit sans modèle : consignes, sections et
    titres, cadrages des épisodes, descriptions des outils, mots des humeurs, repères de temps.
  - Une section par propriétaire.
  - Le code les demande par clé (`vocab.phrasebook` : `phrase`, `phrases`, `family`), et les trous sont stricts.
  - La console, la CLI et les journaux techniques n'y sont pas.
- **Genèse** (`app/genesis.py`, ADR 0070)
  - Un pilote extérieur, souvent sur horloge virtuelle, lui donne ce que ses archives disent d'elle (`remember`,
    `believe`, `note_event`, origine `GENESIS`).
  - L'avance rapide coupe sa vie spontanée le temps du rejeu. C'est la couture avec `INJECTION/`.
- **Simulateur** (`sim/`, ADR 0007)
  - Le vrai noyau sur temps virtuel, avec des interlocuteurs et des pannes. Le modèle factice répète tout `CANARI-…`
    qu'on lui montre.
  - Voie rapide : S01–S13 puis S15–S23 (il n'y a pas de S14).
  - On valide par cibles d'intention, et on casse exprès ce qu'un test garde pour vérifier qu'il n'est pas vide.
  - **La sonde** (`sim sonde --semaine 1|2`) fait vivre une semaine au vrai modèle configuré. Elle refuse `claude_code`.
    Après une sonde réelle, on corrige tout ce qu'elle montre, puis on revalide en réel.

## Écrire du code dans `backendv2`

**Déclarer une faculté** (`kernel/faculty.py`) : `Faculty(name, state, init, state_version, params, volatile, derive…)`.
Tout le reste se déclare par décorateurs.

- Événements : `F.declare(*contracts.x.ALL)` (déclarés par `event_type(...)` dans `contracts/`), ou `F.event(...)` en
  ligne.
- Réduire et lire : `@f.reducer(*types, reads=…)`, `@f.fact(key, reads=…)`.
- Le prompt : `@f.section(key, zone=…, trim_rank=…, floor_chars=…, untrusted=…)`, `@f.enricher`, `@f.prelude`,
  `@f.interpret`.
- L'arbitre : `@f.propose(kinds, reasons=…)` pour les preuves, `@f.modulate` pour les modulations et vetos.
- Les ressentis : `@f.appraisal`, `@f.feels`.
- Le temps : `@f.process(name, wake_on=…, lane=…, deadline_s=…)`.
- Les outils : `@f.tool(name, args=…, bundle=…, episodes=…, ends_loop=…, owner_only=…, when=…)`, `f.bundle(...)`,
  `@f.tool_source(famille)` pour des outils dynamiques.
- Les effets : `@f.capability(name, preview=…)`, `@f.effect(type, lane=…)`, `projector(name, version, tier=…)`.
- La console : `@f.inspect`, `@f.subject`, `@f.search`, `@f.download`, `@f.action`, `@f.vital`, `@f.series`.
- La cohérence : `@f.invariant`.

**Ajouter une faculté** : les tests exigent tout ce qui suit.

1. `faculties/<nom>/` : une tranche gelée, des `Params` dont chaque champ porte un `Knob` borné, et `Faculty(...)`.
2. `contracts/<nom>.py` : ce que d'autres doivent lire.
3. Réducteurs, faits, sections, preuves, processus, outils, vues, par décorateurs.
4. L'inscrire dans `app/composition.py` **et** dans la liste d'indépendance d'import-linter (`pyproject.toml`).
5. Nommer dans `app/console.py` ses sections, raisons, vetos, processus et événements.
6. Mettre ses phrases dans `persona/voix.yaml`, jamais en dur.
7. Déclarer les `subjects=` de tout événement qui porte du texte.

**Les gardes d'architecture** (`tests/architecture/`) :

| Test | Ce qu'il garde |
|---|---|
| `test_composition` | Le démarrage refuse un registre incohérent ; `lint-imports` passe. |
| `test_console_labels`, `test_console_registry` | Tout ce qui est déclaré est nommé ; sujets, onglets, actions et badges sont cohérents. |
| `test_params_documented` | Tout paramètre a un `Knob` borné, et les extrêmes du tempérament donnent des valeurs valides. |
| `test_forgetting`, `test_people_texts` | Tout texte gardé déclare ses sujets ; les champs de personne en clair sont comptés. |
| `test_phrasebook`, `test_no_new_prose` | Clés et trous concordent, pas de phrase orpheline ; pas de nouvelle prose française dans les facultés et plugins (plafonds par fichier). |
| `test_memory_has_one_door` | La mémoire ne se lit que par les vues de `contracts.memory`. |
| `test_views_read_the_journal_through_the_context` | Les vues lisent le journal par `ctx.events` et `ctx.tally`, jamais en SQL. |
| `test_sql_portable`, `test_mail_sql_is_portable` | Rien que MariaDB lirait autrement. |
| `test_her_name_comes_from_her_persona` | Pas de « Mika » en dur. |
| `test_tools_described` | Les lots, outils et conditions `when=` sont décrits. |
| `test_causes_are_said` | Une cause d'humeur est un code `vocab.causes` qui a sa phrase. |
| `test_audiences_say_who_knows_whom` | Toute audience réelle précise `untied_level`. |

**Les tests**

- **Où ils sont** : `tests/unit/` (le gros), `contract/` (les adaptateurs), `protocol/`, `scenarios/` (déterminisme,
  voie rapide, deux moteurs), `property/`, `browser/console.cjs` (Playwright).
- **Les montages** :
  - `conftest.make_mind(tmp, faculties, clock=…)` donne un Mind nu ;
  - `tests/fixtures/mika.py::build(tmp, respond)` donne le vrai Kernel composé, avec `boot`, `connect`, `befriend`,
    `said` ;
  - `tests/fixtures/harness.py` donne des facultés jouets.
- **Le marqueur `sqlite_only`** écarte un test de `--mariadb`.

**Les bancs de mesure** (`tools/`) mesurent le vrai modèle par la CLI Claude Code, avec `claude-haiku-5-5` par défaut :

- `tools/banc_lecture` mesure la lecture `[EN_FACE]` ;
- `tools/banc_temperament` vérifie que la balise suit chaque profil ;
- `tools/banc_conversation` (ADR 0112) fait vivre des conversations au vrai noyau (Sonnet par la CLI, effort high),
  face à un Adrien simulé (Haiku), jugées par Opus : un score sur 100, des scénarios réservés, chaque mesure sur une
  copie figée du code (`--variante`, `--profil`, `--voix api:sonnet`). Tout changement de sa voix s'y mesure.
- pour les lancer : `PYTHONPATH=src .venv/bin/python tools/<banc>/banc.py [modèle] [parallèle] [sortie.json]`.

### Invariants

- Rejouer le journal redonne l'état vivant. Un instantané plus la queue égale le rejeu complet. Une archive restaurée
  rejoue au même état.
- Même graine, même journal, quel que soit `PYTHONHASHSEED`.
- Aucun épisode supplanté n'est livré ; aucun effet ne part avant son commit.
- Tout texte gardé dit qui il concerne : l'oubli l'atteint.

### À savoir

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
  (`sudo -u mika … python -m mika`) ne lit pas `mika.env`. Avec MariaDB ou `MIKA_SECRET_KEY`, il faut le charger, sinon
  elle crée des fichiers SQLite ou un nouveau `secret.key`.

### Carte des ADR (`backendv2/docs/adr/`)

| Thème | ADR |
|---|---|
| Noyau, journal, arbitrage, pipeline | 0001–0003, 0006–0009, 0014, 0015, 0021, 0040, 0059 |
| Stockage | 0004 (remplacé), 0101 |
| Mémoire et savoir | 0010, 0011, 0034, 0046, 0052, 0055, 0074–0087, 0091, 0092, 0099, 0102, 0109–0111 |
| Identité et divulgation | 0012, 0035, 0048, 0075, 0092 |
| Vie intérieure (affect, corps, besoins, liens, autres, attention, soi) | 0013, 0016–0019, 0028, 0032, 0033, 0036, 0047, 0053, 0058, 0088–0090, 0093–0098, 0100, 0107 |
| Buts, projets, Forge, atelier | 0005, 0020, 0023, 0030, 0031, 0039, 0104, 0105 |
| Sens et plugins | 0022, 0027, 0037, 0038, 0044, 0061, 0063, 0064, 0066, 0068, 0069, 0106 |
| Fournisseurs LLM | 0026, 0072, 0073 |
| Console et exploitation | 0024, 0025, 0029, 0042, 0045, 0057, 0103 |
| Clients, fil, monde | 0041, 0049–0051, 0054, 0056, 0060, 0062, 0065, 0067, 0077, 0108 |
| Voix et genèse | 0070, 0071 |
| Ce que les sondes et audits ont montré | 0043, 0048, 0054, 0102 |

## Les clients

### Web (`frontend/Web/src/`)

`main.ts` ne fait que câbler. Il construit les objets et branche chaque trame WebSocket et les événements de la voix
sur `ui/SpeechPresenter.ts`.

**Synchronisation de la voix et du corps** (`ui/SpeechPresenter.ts`, testé par des doublures)

- Les lectures (`EmotionDisplay`, `InnerLifePanel`) changent à la trame `speech`. L'avatar (visage, geste, regard,
  mains) change au **début réel** de l'énoncé, `tts.speak(…, { onStart })`.
- La dérive d'humeur (`emotion_update`) est retenue pendant qu'une réponse parlée est en vol : la plus récente gagne,
  avec une soupape `VOICED_HOLD_MAX_MS`.
- Au réveil, elle observe un silence de 1,3 s.

**Les clips** viennent de l'atelier d'animation d'Unity : `public/animations/atelier` est un lien vers
`frontend/Unity/ArtSource/atelier/motions/`, que `vtuber/animation/atelierClip.ts` passe sur les os normalisés du VRM
(le même squelette, la même formule que le retargeting Mixamo, qui reste possible clip par clip). La marche se joue à sa
vitesse de capture ; l'assise (`posture`) et les occupations debout (`activity` : fenêtre, bibliothèque) aussi. Le bureau
(`vtuber/animation/desk/`, port de `BodyActivity`) joue les clips `desk_*` et `chair_*` : la chaise passe de « home » à
« type » (19,45°, 25,5 cm) ou « write » par les courbes de ses gestes, pivote vers qui lui parle, et elle ne se lève qu'une
fois la chaise rentrée ; la tasse, le stylo et la souris (sortis de `Desk_Props`) suivent ses mains.

**Le corps** (`vtuber/animation/AnimationSystem.ts`) suit, à chaque image, cet ordre :

1. pose de repos ;
2. machine à états (repos, parole, geste, sommeil, marche, posture) ;
3. le mixer des clips (atelier Unity ou Mixamo, reciblés à l'exécution), et leurs jumeaux miroirs `~m` ;
4. `AttentionDirector`, pur : contact, aversion en planifiant une phrase, réflexion, écoute, voix intérieure, errance
   au bout de 25 s seule ;
5. les surcouches additives : respiration, vie, sommeil, tête émotionnelle, tête d'attention, battements de la parole ;
6. les mains ;
7. le regard (les yeux visent le résidu après la tête : réflexe vestibulo-oculaire) ;
8. les clignements ;
9. le visage idle.

Deux règles le tiennent :

- **Une seule convention de squelette.** Tout se calcule en convention VRM 1.0, conjugué par Ry(π) pour un modèle 0.x
  (`vrmVersion.ts::forwardSign`). Les tests vérifient la géométrie, jamais une constante de signe.
- **Les gestes** (`gestures.ts`) suivent la table `EMOTION_GESTURE` sur les 29 émotions et `decideGesture()`. Une
  posture tenue ne se lâche que sous le seuil moins `VARIANT_HYSTERESIS`. Une dérive change la posture, jamais un geste
  ponctuel.

**Le visage**

- Quatre écrivains sur des expressions disjointes : émotions (`EmotionController`, avec des copies `clean:` sans
  symboles manga ; l'émotion secondaire du mélange à `SECONDARY_SHARE`), visèmes (`LipSyncController`, français
  graphème → visème, recalé sur la voix par `onSpeechProgress`), clignements, micro-mouvements ARKit (`FaceIdleController`).
- La physiologie a son horloge (`FacePhysiology.ts`) : rougeur, larmes qui montent, pupilles.

**La locomotion** (`vtuber/locomotion/`)

- C'est le backend qui décide du lieu (`inner_state.place`) et de l'activité (`inner_state.activity`). Le client
  l'exécute : planificateur sur graphe de visibilité, marche de l'atelier. Un siège se prend comme dans Unity
  (`SitDown`, `StandUp`) : elle contourne la chaise à 0,48 m, se place devant le siège à la distance que recule la capture
  `sit_down` (31 cm), s'assied avec elle, et se lève par `stand_up` ; la racine suit le rythme du clip. La chaise ne bouge
  que par les gestes du bureau.
- La caméra suit sa tête.

**La pièce** : un GLB généré par script Blender (`assets-src/blender/`). La lumière du jour suit l'heure réelle, avec du
bloom. Les mêmes scripts font la chambre d'Unity (`export_unity.py`) : après une retouche, relancer aussi
`blender -b --factory-startup --python assets-src/blender/run_final.py` (cuisson de l'occlusion, `room.glb`,
`room.blend`), sinon les deux clients divergent. Les hauteurs d'assise sont celles d'Unity (`ChambreSceneBuilder.Seats`) :
hanches à 0,15 m au-dessus du siège, moins ce qu'il s'enfonce.

**Le monde** (`world/`, ADR 0050) : le client web est une spectatrice de `/ws/world` (`mika.world/1`), jumelle du client
Unity.

- `protocol.g.ts` est généré du schéma du noyau par `backendv2/.venv/bin/python frontend/Web/tools/gen_world_protocol.py`
  (`--check` échoue s'il a vieilli ; `tests/protocol/test_world_wire.py` le vérifie).
- `WorldSession` (hello, ping 5 s, reprise, accusés, débits), `WorldMirror` et `WorldIndex` (l'état dans l'ordre du
  journal), `intentTimeline`, `actionMenu` (mêmes libellés qu'Unity) : purs, testés.
- `WorldStage` montre l'état des meubles (porte, croisée de la fenêtre et portes d'armoire, sorties par `RoomHinges`
  des maillages joints de `room.glb`), une silhouette pour un objet que la pièce ne dessine pas, ce qu'elle tient dans
  sa main, les autres personnages. Le corps de Mika, lui, suit toujours `inner_state` (lieu, occupation, sommeil).
- `WorldHud` : survol et menu d'actions au clic, refus du noyau, demandes de Mika, état de la connexion. Tant que le
  noyau ne fait entrer personne dans le monde (P4), agir et faire un geste sont refusés, et le refus se lit.

**Le reste**

- `audio/TTSService.ts` : Web Speech, une soupape par énoncé, sorties `played` ou `skipped`.
- `network/WebSocketClient.ts` : reprise exponentielle, ping toutes les 20 s, reconnexion après 50 s de silence, file de
  sortie rejouée ; un 4401 est terminal.
- `ui/chatSync.ts` : fusion du fil par curseur.
- `ui/bubbles.ts` : sa réponse en plusieurs bulles (une ligne vide les sépare), « Mika écrit… » entre deux.
- Les 40 fichiers vitest sont dans des dossiers `__tests__`.

### Unity, Android, Extension

- **Unity** (`frontend/Unity/Mika/`) : client du monde (`mika.world/1`). Ses types C# du protocole sont générés depuis
  le schéma du noyau par `backendv2/.venv/bin/python frontend/Unity/tools/gen_world_protocol.py`. Avec `--check`, la
  commande échoue si le fichier a vieilli : régénérer après tout changement du protocole côté noyau.
- **Android** (`frontend/Android/`) : messagerie à une seule conversation. Fichiers dans les deux sens, Mika en 3D
  native (Filament, `avatar3d/`), portraits pré-rendus en repli. Lire son `README.md`.
- **Extension** (`frontend/Extension/`) : lire son `README.md`.
