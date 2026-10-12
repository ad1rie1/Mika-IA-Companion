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
   - sur SQLite, chaque schéma est un fichier, avec ses connexions (comme avant) ; sur MariaDB, une même transaction
     pourra couvrir `mika_mind` et `mika_views` ;
   - chaque base garde son écrivain : le magasin son fil unique, le courrier, les flux et Teams les leurs.

4. *Types et collation, déclarés dans les modèles.* `BIGINT` pour les instants, les `seq` et les identifiants ;
   `VARCHAR(n)` pour toute clé ou colonne indexée (`Key(n)`) ; `LONGTEXT` pour tout autre texte (les charges du
   journal, les contenus, les instantanés, les corps de mail) ; `LONGBLOB` pour les octets. La borne d'une `Key` est
   vérifiée par le code à chaque écriture, sur les deux moteurs (`KeyTooLong`) — SQLite ne borne rien, MariaDB
   refuse ; une recherche avec une valeur plus longue ne lève pas, elle ne trouve rien, comme sous MariaDB. Une
   valeur venue de l'extérieur qui peut dépasser sa borne est coupée ou remplacée par une empreinte avant d'être
   écrite. Collation `utf8mb4_nopad_bin` partout (le `BINARY` de SQLite) : une recherche insensible à la casse et aux
   accents compare un texte replié à l'écriture (`fold_text`), en binaire, pareil sur les deux moteurs.
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
   `sqlite_master`, `WITHOUT ROWID`, `LIMIT -1` et `MAX`/`MIN` à deux arguments, ainsi que toute fonction Python
   enregistrée dans un moteur (`tests/architecture/test_sql_portable.py`) ; sa liste de modules s'allonge à chaque
   lot jusqu'à tout `src` ; depuis le lot 2, il relit tout `src`, sauf trois exceptions nommées (`adapters/database.py`,
   qui parle SQLite par nature ; la Forge et la sauvegarde, reprises aux lots 4 et 5). Les projections déclarent leurs
   tables par `projection_table` (sous leur nom suffixé de version, hors des migrations) et leurs vues par
   `create_view` ; la porte de la mémoire se lit par les colonnes que `contracts.memory` déclare (`KNOWLEDGE`,
   `select_known`…). Les tables du journal sont des entités du port (`mika.ports.journal`). Une adresse ou un sujet
   tient dans `HANDLE_MAX` (400) : les adresses venues de l'extérieur (`mail:`, `teams:`) y sont ramenées dès leur
   fabrication (`fit`).

   *Le prix.* Une requête SQLAlchemy construite à chaque appel coûte 50 à 90 µs, contre 2 à 5 µs en SQL écrit en
   clair ; au premier passage, le scénario rapide du simulateur a pris un tiers de temps en plus. Les requêtes qu'on
   passe des milliers de fois (le journal, ce qui tourne à chaque événement) sont donc **préparées** (`Prepared` :
   compilées une fois par moteur, exécutées au curseur du pilote, bornes des `Key` vérifiées à l'écriture), les
   alias de tables construits une fois (`alias_of`), les `upsert` / `insert_ignore` mis en cache par table. Après
   cela, l'écart mesuré est de l'ordre du bruit de la machine (le même scénario, l'un après l'autre : 80–84 s avant,
   82–92 s après).

6. *Les migrations : Alembic pour ce qui est stable, la reconstruction pour ce qui dérive du journal.* Alembic gère
   les tables du journal, de la file de sortie, de `meta`, des comptes, des réglages, des appels de modèle, du
   courrier, des flux et de Teams. Une seule révision initiale, générée depuis les modèles : rien d'ancien n'est
   reconnu. Les migrations faites à la main et la reprise de l'ancien cache du courrier sont supprimées. Au
   démarrage (`mika.app.schema.migrate_data`), le serveur et les commandes qui écrivent passent chaque base à `head`
   ; s'ils n'y arrivent pas, ils ne démarrent pas. Une base née des entités seules (les tests et le simulateur créent
   leurs tables par `Sql.create`) est complétée par elles puis marquée à `head`. Les tables qu'on ne déclare pas (le
   journal tant qu'il n'est pas déclaré, les projections T0 et différées) sont ignorées par les révisions : le schéma
   d'une projection évolue, comme avant, par sa version et une reconstruction depuis le journal. Une révision
   s'écrit par `python -m mika.app.schema revision <base> "<message>"` et se relit.

7. *La reconstruction T0 reste en place, et sans danger.* `ensure_t0` supprime les tables d'une projection dont la
   version a changé, les recrée, rejoue le journal et écrit sa version dans `meta` **en dernier**. Sous SQLite, tout
   tient dans une transaction ; sous MariaDB, chaque DDL valide ce qui le précède, mais une reconstruction
   interrompue laisse l'ancienne version dans `meta` et se refait entièrement au démarrage suivant : une projection
   T0 ne contient que ce que le journal redonne, et rien ne la lit avant la fin d'`ensure_t0`. Une bascule par
   `RENAME TABLE` a été écartée : sous SQLite, les noms d'index sont uniques dans toute la base, et l'index d'une
   table renommée bloquerait la construction suivante. La bascule bleu/vert des projections différées écrit son
   état avant de supprimer l'ancienne version : un arrêt entre les deux laisse au pire des tables orphelines.

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
    1. les fondations (`ports/sql.py`, `adapters/database.py`, le magasin sur des connexions SQLAlchemy), puis
       entités et Alembic sur SQLite : comptes, réglages, appels de modèle, traces, séries, courrier (ses colonnes
       calculées), flux, Teams ; migrations à la main supprimées ; test d'architecture du SQL écrit en clair ;
    2. le journal, les projections, les facultés et la console en SQLAlchemy ; le test d'architecture sur tout
       `src` ;
    3. moteur MariaDB : schémas, comptes, voie de tests `mariadb` et test différentiel ;
    4. une base par app de la Forge, ses outils, son quota ;
    5. oubli et sauvegarde sur MariaDB, `deploy/README.md`, puis démarrage à vide sur le portable.

**Ce qui n'est pas fait.** Les lectures restent synchrones dans la boucle (231 appels `query_mind` / `query_views`) :
passer à un moteur asynchrone serait un chantier à part. Une base MariaDB sur une autre machine n'est pas prise en
charge. La recherche du courrier reste un parcours de la colonne repliée (pas d'index plein texte). Les apps de la
Forge n'ont aucun accès aux données de Mika.

**Conséquences.** Contrats : le port `Sql` repose sur une connexion SQLAlchemy et gagne `session` (une session ORM
dans la transaction en cours), `create` et `dialect` ; le magasin gagne `read_mind` / `read_views` (des sessions de
lecture) et ses `query_*` acceptent une requête SQLAlchemy ; `mika.ports.sql` (bases, types, `upsert`,
`insert_ignore`, `greatest`/`least`), `mika.adapters.database` (les moteurs), `mika.app.schema` et
`mika.app.migrations` (une révision par base) ; `adapters/store_sqlite` devient
`adapters/store_sql` (un adaptateur, deux moteurs) et `SqliteStore` disparaît ; `tests/conftest.py::make_mind`
construit le magasin depuis une adresse ; `app/backup.py` et la commande de restauration sont réécrits ; le port de la
Forge gagne le service `sql` et les trois outils ; `forge.db` et `mail.db` / `feeds.db` / `teams.db` en tant que
fichiers disparaissent sous MariaDB. Dépendances : `sqlalchemy>=2.0`, `alembic`, et `mariadb` dans un extra du même
nom. Révisent : l'ADR 0004 (SQLAlchemy plutôt que `sqlite3` ; toujours sans framework), l'ADR 0023 (les bases de Mika
restent invisibles, l'app a la sienne par l'hôte), l'ADR 0024 (la sauvegarde), l'ADR 0073 (l'oubli).
`ARCHITECTURE.md` et `deploy/README.md` changent avec les lots, pas avant.
