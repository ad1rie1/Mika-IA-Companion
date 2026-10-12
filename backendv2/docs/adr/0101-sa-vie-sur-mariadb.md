# 0101 — Sa vie sur MariaDB : un schéma déclaré, deux moteurs

**Contexte.** Le 2026-10-12, la propriétaire a demandé de ranger sa mémoire, son courrier et les données des apps de
la Forge dans une base MariaDB, en gardant SQLite pour les tests. Elle veut un ORM à la façon de Django (des entités,
des migrations), et une base par app de la Forge, créée avec l'app et nettoyée avec elle. **Les données existantes ne
sont pas reprises** : Mika repart d'une base vide.

L'ADR 0004 avait choisi `sqlite3` directement. Chaque faculté écrit son propre SQL à travers le port `Sql`
(`ports/store.py`), en dialecte SQLite : 876 requêtes dans 63 fichiers, dont 348 dans la mémoire, 103 dans le
courrier. Une relecture de ce SQL contre MariaDB a montré trois familles d'écarts :

- *ce qui casse* : `INSERT OR REPLACE` / `OR IGNORE`, `ON CONFLICT … excluded`, `MAX(a, b)` scalaire (12 fois dans
  `memory/projections.py`), `json_each`, `WITHOUT ROWID`, `rowid`, `strftime(…, 'unixepoch')`, `sqlite_master`,
  `PRAGMA`, `executescript` ; des clés `TEXT` (non indexables) ; des instants en microsecondes qui débordent un `INT` ;
  des `TEXT` limités à 64 Ko alors qu'un instantané pèse déjà 38 Ko pour 387 événements ; l'élagage des instantanés
  (`DELETE … IN (SELECT … LIMIT ?)` sur la même table) ; cinq fonctions Python appelées depuis le SQL du courrier
  (`fold`, `mail_ref`, `mail_mid`, `mail_key`, `mail_addresses`) ;
- *ce qui se trompe sans erreur* : `json_extract(…) = ?` (MariaDB rend la valeur entre guillemets JSON : la comparaison
  ne trouve jamais rien), `||` (un OU logique en MariaDB : la recherche du courrier), la collation par défaut
  (insensible à la casse, aux accents et aux espaces de fin : `name:Élodie` et `name:elodie` deviennent la même clé),
  `LIKE` (insensible à la casse ASCII en SQLite, pas en binaire), les lectures sans autocommit (InnoDB en lecture
  répétable : la connexion de lecture ne verrait plus ce que Mika vient d'écrire), le commit implicite de tout DDL
  (la reconstruction T0 `DROP` + `CREATE` + rejeu n'est plus atomique), le fuseau de `FROM_UNIXTIME` ;
- *ce qui tient à l'infrastructure* : l'oubli physique (ADR 0073 : `secure_delete` et troncature du WAL), la
  sauvegarde et sa vérification par rejeu (ADR 0024, l'API de sauvegarde de sqlite3), la Forge dont les apps ne
  voient aucune base (ADR 0023).

Quatre endroits faisaient leurs migrations à la main (« si la colonne manque, `ALTER TABLE ADD COLUMN` ») :
`adapters/web/accounts.py`, `adapters/llm/calls.py`, `adapters/feeds`, `adapters/mail/cache.py`.

**Décision.**

1. *SQLAlchemy 2.0 et Alembic.* Les tables sont déclarées en entités SQLAlchemy, chacune dans le paquet de la
   faculté ou de l'adaptateur qui la possède (la propriété des données reste structurelle, ADR 0004). Deux usages des
   mêmes modèles :
   - les vraies entités (comptes, sessions, jetons, réglages, courrier, flux, Teams, registre des appels de modèle)
     s'utilisent avec les sessions de l'ORM ;
   - le journal et les projections s'utilisent en style requête (`insert(...)` en lot, `select(...)`), sans session
     qui suit des objets sur le chemin chaud.

   Pas de Django (ADR 0004), pas d'ORM asynchrone (Tortoise, Piccolo : il faudrait réécrire chaque lecture en
   `await`), pas de SQLModel (Pydantic reste aux frontières).

2. *Deux moteurs, un seul code.* MariaDB 11.8 LTS en production, avec le pilote officiel (`mariadb+mariadbconnector`),
   **sur la machine de Mika, par socket Unix** : les lectures restent synchrones dans la boucle, une base distante
   ajouterait un aller-retour réseau à chacune. SQLite pour les tests, le simulateur et le jumeau (`INJECTION/`).
   L'adresse vient de `MIKA_DATABASE_URL` ; sans elle, des fichiers SQLite dans le dossier de données, comme avant.
   Le moteur est synchrone ; le magasin garde son écrivain unique dans son fil ; les lecteurs sont en autocommit et en
   READ COMMITTED, dans un petit pool. Le compte `mika` s'authentifie par `unix_socket` : pas de mot de passe à
   garder pour le cœur.

3. *Schémas et comptes.*
   - schémas `mika_mind` (sa vie : journal, contenus, instantanés, file de sortie, projections T0, comptes,
     réglages — sauvegardé), `mika_views` (projections différées, vecteurs, appels de modèle, traces, séries, journal
     des apps de la Forge — reconstructible), `mika_mail`, `mika_feeds`, `mika_teams`, et un `forge_<app>` par app ;
   - comptes `mika` (le cœur), `mika_forge_admin` (création d'utilisateurs, droits limités aux bases `forge\_%`), et
     un compte par app de la Forge ;
   - sur MariaDB, une seule transaction couvre `mika_mind` et `mika_views` ; sur SQLite, chaque schéma est un fichier,
     attaché sous son nom à la connexion qui en a besoin (`ATTACH … AS mika_mind`), si bien que les noms qualifiés
     sont les mêmes partout ;
   - chaque base garde son écrivain : le magasin son fil unique, le courrier, les flux et Teams les leurs.

4. *Types et collation, déclarés dans les modèles.* `BIGINT` pour les instants, les `seq` et les identifiants ;
   `VARCHAR(n)` pour toute clé ou colonne indexée ; `LONGTEXT` pour les charges du journal, les contenus, les
   instantanés et les corps de mail ; `LONGBLOB` pour le message brut d'un envoi. Collation `utf8mb4_nopad_bin` par
   défaut (le `BINARY` de SQLite) ; `utf8mb4_uca1400_ai_ci` seulement sur la colonne de recherche du courrier.
   `sql_mode` strict (une valeur trop longue est refusée, jamais coupée), `time_zone='+00:00'`,
   `max_allowed_packet` à 64 Mo, `innodb_flush_log_at_trx_commit=1` (l'équivalent de `synchronous=FULL`).

5. *Aucune construction propre à SQLite dans le code.* Ce qu'un dialecte écrit autrement passe par une aide
   unique, compilée par moteur : `upsert`, `insert_ignore`, `greatest`/`least`, `json_has(colonne, valeur)`,
   `json_values(colonne)` (`json_each` en SQLite, `JSON_TABLE` en MariaDB) ; la lecture d'un champ JSON passe par le
   type `JSON` de SQLAlchemy (`as_string()`), qui retire les guillemets là où il le faut. Les fonctions Python du
   courrier deviennent des colonnes calculées à l'écriture (texte replié pour la recherche, référence, clé,
   adresses) ; `||` devient `concat()` ; `rowid` devient un `id` déclaré ; l'élagage des instantanés lit d'abord son
   seuil, puis supprime en dessous. Un test d'architecture relit le SQL écrit en clair (par l'AST, jamais par le texte
   du source) et refuse `INSERT OR`, `ON CONFLICT`, `json_each`, `json_extract`, `||`, `rowid`, `PRAGMA`,
   `sqlite_master`, `WITHOUT ROWID` et `MAX`/`MIN` à deux arguments hors du module des aides.

6. *Les migrations : Alembic pour ce qui est stable, la reconstruction pour ce qui dérive du journal.* Alembic gère
   les tables du journal, de la file de sortie, de `meta`, des comptes, des réglages, des appels de modèle, du
   courrier, des flux et de Teams. Une seule révision initiale, générée depuis les modèles : rien d'ancien n'est
   reconnu. Les migrations faites à la main et la reprise de l'ancien cache du courrier sont supprimées. Au
   démarrage, sous le verrou du dossier de données, le serveur passe le schéma à `head` ; s'il n'y arrive pas, il ne
   démarre pas. Les tables des projections (T0 et différées) sont exclues de l'autogénération : leur schéma évolue,
   comme avant, par leur version et une reconstruction depuis le journal.

7. *La reconstruction T0 bascule par `RENAME`.* `ensure_t0` ne fait plus `DROP` + `CREATE` + rejeu dans une même
   transaction (MariaDB valide chaque DDL à part). Il construit la table neuve à côté, la remplit, puis bascule
   (`RENAME TABLE x TO x__ancien, x__neuf TO x`, atomique), supprime l'ancienne et écrit sa version dans `meta` en
   dernier : une panne au milieu refait la reconstruction au démarrage suivant. Les vues d'une projection (la porte
   de la mémoire, ADR 0078) sont supprimées avant la bascule et recréées après : SQLite réécrit une vue qui nomme une
   table renommée, et elle pointerait sur l'ancienne.

8. *Une base par app de la Forge.* À la création d'une app, l'hôte crée `forge_<app>` et son utilisateur (mot de
   passe tiré au hasard, scellé comme les autres secrets, jamais montré). Cet utilisateur a tous les droits sur sa
   base, **sauf** `EVENT` (une tâche planifiée survivrait au disjoncteur), les procédures, les déclencheurs et
   `GRANT OPTION` ; il est borné par `MAX_USER_CONNECTIONS`, `MAX_QUERIES_PER_HOUR` et `MAX_STATEMENT_TIME`. Le nom de
   l'app entre dans un DDL : il est validé strictement (minuscules, chiffres, `_`, 64 caractères préfixe compris).
   - *L'app ne voit ni mot de passe ni socket* : elle demande ses requêtes à l'hôte par son canal (un service `sql`,
     une instruction par appel), que l'hôte exécute sous l'utilisateur de l'app, avec délai et taille de résultat
     bornés. Son bac à sable reste sans réseau. Le stockage clé/valeur devient une table `_kv` de sa base ; son
     journal passe dans `mika_views`. `forge.db` disparaît.
   - *Les outils* : Mika a `forge_db_schema`, `forge_db_query` (lecture) et `forge_db_execute` (écriture), exécutés
     par l'hôte sous l'utilisateur de l'app ; la console en MCP (`/mcp/console`) sert les deux premiers seulement.
   - *Le cycle de vie* : une nouvelle version garde la base ; un `rollback` rend le code, pas les données (la
     description de l'outil le dit) ; `reset_storage` vide la base ; `erase` exporte la base dans le dossier de
     corbeille, à côté du code, puis supprime la base et l'utilisateur. Une app recréée sous le même nom repart d'une
     base vide (aujourd'hui elle héritait des lignes `kv` de l'ancienne).
   - *Le disque* : MariaDB n'a pas de quota par base. L'hôte mesure la taille de chaque base
     (`information_schema`) et arrête l'app au-delà de `forge.db_max_mb`, comme le fait le disjoncteur, en le lui
     disant.
   - Les bases de Mika restent invisibles aux apps : aucune n'a de droit hors de sa base. Lire sa mémoire ou son
     courrier passera, si un jour on le veut, par des services de l'hôte qui appliquent la divulgation (ADR 0074),
     jamais par un droit SQL.
   - Sur SQLite (tests), la base d'une app est un fichier à elle ; les droits se vérifient dans la voie MariaDB.

9. *L'oubli.* Binlog coupé. `innodb_immediate_scrub_data_uncompressed=ON` remet à zéro la place libérée par une
   suppression, comme `secure_delete`. Un texte oublié disparaît des tables tout de suite ; ses traces dans les
   journaux de reprise et d'annulation d'InnoDB disparaissent à leur rotation, pas immédiatement : la garantie de
   l'ADR 0073 devient « effacé des tables tout de suite, des journaux sous peu ». Pas d'`OPTIMIZE TABLE` (il
   réécrirait la table sous l'écrivain unique, la raison pour laquelle l'ADR 0073 refusait `VACUUM`). Le chiffrement
   au repos ne sert pas l'oubli (la clé reste là) ; il n'est pas activé.

10. *La sauvegarde.* `mariadb-dump --single-transaction` de `mika_mind`, `mika_mail`, `mika_feeds`, `mika_teams` et
    des bases `forge_*`, avec `partages/` et les clés, comme avant ; `mika_views` n'y est pas. La vérification
    restaure l'archive dans des schémas temporaires, la rejoue et compare l'empreinte, comme le faisait l'ADR 0024.
    Les anciennes archives SQLite ne se restaurent plus.

11. *Les tests.* La suite par défaut reste sur SQLite (`create_all`, rapide). Une voie `mariadb`, en option comme
    `--slow` (`--mariadb`, avec `MIKA_TEST_MARIADB` qui donne l'adresse d'un serveur de test), couvre : le contrat du
    magasin, la création et la suppression des bases de la Forge et leurs droits, la recherche du courrier,
    `alembic upgrade head` suivi de `alembic check`, et surtout **un test différentiel** : le même journal rejoué sur
    les deux moteurs doit donner les mêmes lignes dans chaque projection et les mêmes réponses aux lectures de la
    mémoire. C'est lui qui attrape ce qui se trompe sans erreur. On la lance quand on touche au stockage et avant de
    remettre un lot, sous la borne mémoire, jamais en parallèle d'une autre suite.

12. *L'ordre de travail.* Chaque lot garde la suite verte sur SQLite ; MariaDB n'est, à la fin, qu'une adresse.
    1. modèles et Alembic sur SQLite : comptes, réglages, appels de modèle, courrier, flux, Teams ; migrations à la
       main supprimées ;
    2. journal et projections en SQLAlchemy ; aides de dialecte ; colonnes calculées du courrier ; test
       d'architecture du SQL écrit en clair ;
    3. moteur MariaDB : schémas, comptes, bascule par `RENAME`, voie de tests `mariadb` et test différentiel ;
    4. une base par app de la Forge, ses outils, son quota ;
    5. oubli et sauvegarde sur MariaDB, `deploy/README.md`, puis démarrage à vide sur le portable.

**Ce qui n'est pas fait.** Les lectures restent synchrones dans la boucle (231 appels `query_mind` / `query_views`) :
passer à un moteur asynchrone serait un chantier à part. Une base MariaDB sur une autre machine n'est pas prise en
charge. La recherche du courrier reste un parcours de la colonne repliée (pas d'index plein texte). Les apps de la
Forge n'ont aucun accès aux données de Mika.

**Conséquences.** Contrats : le port `Sql` repose sur une connexion SQLAlchemy ; `adapters/store_sqlite` devient
`adapters/store_sql` (un adaptateur, deux moteurs) et `SqliteStore` disparaît ; `tests/conftest.py::make_mind`
construit le magasin depuis une adresse ; `app/backup.py` et la commande de restauration sont réécrits ; le port de la
Forge gagne le service `sql` et les trois outils ; `forge.db` et `mail.db` / `feeds.db` / `teams.db` en tant que
fichiers disparaissent sous MariaDB. Dépendances : `sqlalchemy>=2.0`, `alembic`, et `mariadb` dans un extra du même
nom. Révisent : l'ADR 0004 (SQLAlchemy plutôt que `sqlite3` ; toujours sans framework), l'ADR 0023 (les bases de Mika
restent invisibles, l'app a la sienne par l'hôte), l'ADR 0024 (la sauvegarde), l'ADR 0073 (l'oubli).
`ARCHITECTURE.md` et `deploy/README.md` changent avec les lots, pas avant.
