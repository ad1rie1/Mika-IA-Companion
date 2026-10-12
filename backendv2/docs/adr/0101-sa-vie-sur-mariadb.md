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

2. *Deux moteurs, un seul code.* MariaDB 11.8 LTS en production, **sur la machine de Mika, par socket Unix** : les
   lectures restent synchrones dans la boucle, une base distante ajouterait un aller-retour réseau à chacune. SQLite
   pour les tests, le simulateur et le jumeau (`INJECTION/`).
   - *Le pilote* est PyMySQL (`mariadb+pymysql`), écrit en Python. Le pilote officiel (`mariadb+mariadbconnector`)
     se compile contre la bibliothèque C de MariaDB, un paquet de développement du système ; son avantage de vitesse
     n'est pas mesuré ici, et le chemin chaud passe déjà par des requêtes préparées sur un serveur local. À revoir sur
     le portable (lot 5) si les lectures y pèsent. PyMySQL marque ses paramètres `%s` : le moteur les déclare
     positionnels (`paramstyle="format"`), comme `?` sous SQLite, et une requête préparée se compile par moteur et
     par forme de paramètres.
   - *Où vit une base* : une cible (`adapters.database.Target`) est un fichier SQLite, ou une base d'un serveur, et
     fabrique ses moteurs. L'adresse du serveur, sans base, vient de `MIKA_DATABASE_URL`
     (`mariadb+pymysql://mika@localhost/?unix_socket=…`) ; le nom des bases, de `MIKA_DATABASE_PREFIX` (`mika_` par
     défaut : `mika_mind`, `mika_views`, `mika_mail`, `mika_feeds`, `mika_teams`) ; une base absente est créée avec
     sa collation. Sans adresse, des fichiers SQLite dans le dossier de données, comme avant
     (`mika.app.schema.targets`).
   - Le moteur est synchrone ; le magasin garde son écrivain unique dans son fil ; les lecteurs sont en autocommit,
     l'écrivain en READ COMMITTED ; une connexion gardée longtemps est vérifiée avant de resservir (le serveur coupe
     une connexion oubliée). Le compte `mika` s'authentifie par `unix_socket` : pas de mot de passe à garder pour le
     cœur.

3. *Schémas et comptes.*
   - schémas `mika_mind` (sa vie : journal, contenus, instantanés, file de sortie, projections T0, comptes,
     réglages — sauvegardé), `mika_views` (projections différées, vecteurs, appels de modèle, traces, séries, journal
     des apps de la Forge — reconstructible), `mika_mail`, `mika_feeds`, `mika_teams`, et un `mika_forge_<app>` par
     app ;
   - comptes `mika` (le cœur) et un compte par app de la Forge. `mika` a tous les droits sur les bases `mika\_%`,
     avec `GRANT OPTION`, et `CREATE USER` : c'est lui qui crée la base et le compte d'une app. Un second compte
     d'administration (`mika_forge_admin`, d'abord prévu) n'isolerait rien : le même processus tiendrait les deux.
     Sous MariaDB, `CREATE USER` permet de modifier n'importe quel compte, `root` compris : **le serveur est dédié à
     Mika** (c'est le cas sur le portable) ;
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

8. *Une base par app de la Forge* (`adapters/forge/bases.py`). L'hôte crée la base d'une app à sa première
   écriture : `mika_forge_<app>` (le préfixe de ses bases, puis `forge_`) et un utilisateur du même nom. Le nom de
   l'app entre dans un DDL : il est validé strictement (minuscules, chiffres, `_`, 31 caractères ; 64 avec le
   préfixe).
   - *Ses droits* : `SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, CREATE VIEW, SHOW VIEW, REFERENCES`
     sur sa base seulement — ni `EVENT` (une tâche planifiée survivrait au disjoncteur), ni procédure, ni
     déclencheur, ni `GRANT OPTION`, ni `FILE`, aucun droit global. Dans un `GRANT`, `_` est un joker : le nom de la
     base y est échappé, sinon les droits de `my_app` couvriraient aussi la base de `myxapp`. Il est borné par
     `MAX_USER_CONNECTIONS` (4), `MAX_QUERIES_PER_HOUR` (36 000) et `MAX_STATEMENT_TIME` (5 s). Vérifié sur le
     serveur : il ne lit ni `mika_mind` ni la base d'une autre app, ne crée ni base, ni tâche, ni déclencheur, ni
     fichier. Il voit, comme tout compte, les compteurs publics du serveur (`performance_schema.global_status`) :
     accepté.
   - *Son mot de passe* est tiré au hasard à chaque démarrage de l'hôte et ne quitte pas sa mémoire (`ALTER USER` le
     repose) : il n'y a rien à sceller ni à montrer (d'abord prévu : scellé comme les autres secrets).
   - *L'app ne voit ni mot de passe ni socket* : elle demande ses requêtes à l'hôte (`api.query` pour lire,
     `api.execute` pour écrire), une instruction par appel, des paramètres nommés (`:nom`), que l'hôte exécute sous
     son utilisateur. Une lecture passe par une connexion en lecture seule et rend au plus 500 lignes et 256 Ko. La
     forme est vérifiée (une lecture commence par `SELECT` ou `WITH` ; une écriture par `INSERT`, `UPDATE`,
     `DELETE`, `REPLACE`, `CREATE`/`DROP` d'une table, d'un index ou d'une vue, `ALTER TABLE`), mais c'est une
     politesse : la défense, ce sont les droits du serveur. Son bac à sable reste sans réseau. Le stockage
     clé/valeur devient la table `_kv` de sa base (elle revient vide si l'app la supprime) ; son journal, la table
     `forge_logs` de `mika_views`. `forge.db` disparaît.
   - *Sous SQLite* (les tests, le simulateur, une installation sans serveur), la base d'une app est un fichier à
     elle (`forge/_bases/<app>.db`, hors du dossier monté dans son bac à sable), en journal classique. Le temps de
     chacune de ses instructions, un contrôleur refuse `ATTACH` (et donc `VACUUM INTO`) et `PRAGMA`, et l'hôte
     l'interrompt à son échéance (SQLite n'a pas de délai par instruction) ; ses lectures passent par une connexion
     en lecture seule.
   - *Le disque* : MariaDB n'a pas de quota par base. L'hôte mesure la taille de chaque base et, au-delà de
     `BaseLimits.max_bytes` (100 Mo), refuse ce qui l'agrandirait en le disant à l'app ; une suppression passe
     toujours, de quoi faire de la place (d'abord prévu : arrêter l'app, qui n'aurait alors plus pu se vider
     elle-même). InnoDB ne remet ses tailles à jour que de loin en loin (3 Mo insérés : toujours 32 Ko annoncés) :
     la mesure fait d'abord `ANALYZE TABLE`, qui ne lit que quelques pages.
   - *Les outils* : Mika a `forge_db_schema`, `forge_db_query` (lecture) et `forge_db_execute` (écriture), exécutés
     par l'hôte sous l'utilisateur de l'app ; le schéma dit le moteur (le SQL de MariaDB et celui de SQLite
     diffèrent : `AUTO_INCREMENT`, `TEXT` limité à 64 Ko). La fiche d'une app gagne un onglet « Base » (son schéma,
     et une lecture), que la console en MCP (`/mcp/console`) sert comme toute fiche : rien ne s'y écrit.
   - *Le cycle de vie* : une nouvelle version garde la base ; un `rollback` rend le code, pas les données (la
     description de l'outil le dit) ; `reset_storage` vide la base (tables et vues ; `_kv` revient vide) ; `erase`
     exporte la base dans le dossier de corbeille, à côté du code (le fichier sous SQLite ; sous MariaDB, un
     `base.json` : la définition de chaque table et ses lignes), puis supprime la base et l'utilisateur. Une app
     recréée sous le même nom repart d'une base vide (elle héritait des lignes `kv` de l'ancienne).
   - Les bases de Mika restent invisibles aux apps : aucune n'a de droit hors de sa base. Lire sa mémoire ou son
     courrier passera, si un jour on le veut, par des services de l'hôte qui appliquent la divulgation (ADR 0074),
     jamais par un droit SQL.

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

11. *Les tests.* La suite par défaut reste sur SQLite (`create`, rapide). La voie MariaDB (`--mariadb`, en option
    comme `--slow`) met les magasins de chaque test dans des bases jetables d'un serveur
    (`mika_test_<session>_<n>_<base>`, supprimées à la fin du test, et ce qui en resterait à la fin de la session) :
    `make_mind`, les montages de `tests/fixtures`, le simulateur, le faux magasin `SqlDB` et l'application elle-même
    (`MIKA_DATABASE_URL` et un préfixe par test). Le serveur est `MIKA_TEST_MARIADB` (une adresse sans base), sinon le
    serveur local par son socket, sous l'utilisateur du système (`unix_socket`, aucun mot de passe) ; ce compte n'a de
    droits que sur les bases `mika\_test\_%`. Les tests qui lisent ou réécrivent eux-mêmes des fichiers SQLite (une
    installation d'avant, l'effacement sur le disque, la sauvegarde jusqu'au lot 5, deux dossiers qui sont deux vies),
    ou qui coupent le réseau (la garde du simulateur coupe aussi le socket du serveur), sont marqués `sqlite_only` et
    sautés dans cette voie. Elle couvre en plus :
    - chaque base passée deux fois à `head` par Alembic, sans écart avec ses entités, en collation `utf8mb4_nopad_bin` ;
    - **un test différentiel** (`tests/scenarios/test_engines_agree.py`) : la même vie simulée — même scénario, même
      graine, même horloge — vécue une fois sur chaque moteur doit laisser les mêmes lignes dans chaque table de
      `mind` et de `views`. Neuf scénarios, riches en mémoire, secrets, conversation, vie intérieure et courrier ; pas
      S16, où l'empreinte d'un commit de l'atelier dépend de l'heure réelle. C'est lui qui attrape ce qui se trompe sans
      erreur ;
    - au lot 4, la création, les droits et la suppression des bases de la Forge.

    On la lance quand on touche au stockage et avant de remettre un lot, sous la borne mémoire, jamais en parallèle
    d'une autre suite.

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
`adapters/store_sql` (un adaptateur, deux moteurs) et `SqliteStore` devient `SqlStore` ; `tests/conftest.py::make_mind`
construit le magasin depuis une adresse ; `app/backup.py` et la commande de restauration sont réécrits ; le port de la
Forge gagne le service `sql` et les trois outils ; `forge.db` et `mail.db` / `feeds.db` / `teams.db` en tant que
fichiers disparaissent sous MariaDB. Dépendances : `sqlalchemy>=2.0`, `alembic`, et le pilote PyMySQL dans l'extra
`mariadb`. Révisent : l'ADR 0004 (SQLAlchemy plutôt que `sqlite3` ; toujours sans framework), l'ADR 0023 (les bases de Mika
restent invisibles, l'app a la sienne par l'hôte), l'ADR 0024 (la sauvegarde), l'ADR 0073 (l'oubli).
`ARCHITECTURE.md` et `deploy/README.md` changent avec les lots, pas avant.
