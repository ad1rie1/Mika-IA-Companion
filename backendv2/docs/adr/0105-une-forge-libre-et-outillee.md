# 0105 — Une Forge libre et outillée : le web au travail, des outils déclarés, un réseau libre, une confiance par app

**Contexte.** Le 2026-10-13, un audit de la Forge (après l'ADR 0104) pose la question : a-t-elle tout ce qu'il faut
pour construire ses apps ? Six manques.
- **Pas de web quand elle travaille.** Une exécution de projet n'a que les lots du projet, et ceux qu'elle peut se
  donner sont mémoire, flux, Forge, apps : jamais `mcp.web`. Ses explorations (promesse, réparation, signal) non
  plus. Pour savoir quelle API existe et ce qu'elle rend, elle n'avait que ce que le modèle savait déjà, ou une app
  jetable essayée à l'aveugle.
- **Des outils sans arguments déclarés.** Un outil d'app avait un schéma libre : un autre jour, en conversation, le
  modèle ne voyait que sa description et devinait les noms de ses arguments (l'ADR 0104 le notait).
- **Un réseau étroit.** GET seulement, trois en-têtes, des domaines exacts (dix au plus), pas de redirection, ni
  statut ni en-têtes rendus, une réponse coupée à 1 Mo sans le dire.
- **Cinq secondes pour tout.** Un battement, réseau compris, avait 5 s (réglable jusqu'à 30) ; un outil 5 s fixes.
- **Réécrire pour corriger.** `forge_write` prend le manifeste et le code entiers, trois fois par épisode ; la sortie
  du modèle est bornée : corriger une ligne d'une app de 400 lignes coûtait tout le fichier.
- **Une validation à chaque version.** Une app qui avait des secrets (ou une promotion) faisait mettre de côté
  chacune de ses nouvelles versions, que `forge_test` ne pouvait pas essayer : chaque correctif d'une app à clé
  d'API coûtait un aller-retour avec l'opérateur.

**Décisions de la propriétaire.** Elle doit avoir ses outils normalement quand elle travaille, la recherche et la
navigation web comprises. Les outils d'une app se déclarent avec leurs arguments, de la même manière dans toutes les
apps. Le réseau d'une app est libre. Chaque service a son délai, déclaré dans le manifeste. Elle a des outils de
fichiers comme ceux de Claude Code : lire, chercher, retoucher. Une app est validée une fois — à l'enregistrement de
sa clé — ; ensuite ses versions s'installent sans revalidation.

**Décision.**

1. *Le web au travail* (`contracts.mcp.WEB_BUNDLE`, « mcp.web », le lot de son serveur web, ADR 0066).
   - Un projet à elle l'a toujours en main (`projects.run_bundles` : même un projet ouvert avant) ; un projet confié
     l'a quand son cadre le dit — coché d'office à sa création, une case dans « Ses outils » ; sans lui, l'exécution
     le sait (`missing_tools`). `DEFAULT_BUNDLES` le porte.
   - Ses explorations (`EXPLORE_BUNDLES` : signal, centre d'intérêt avec flux, vérification, promesse) et ses
     réparations (`REPAIR_BUNDLES`) l'ont ; y repenser et rêvasser, non (`REFLECT_BUNDLES`).
   - **Chercher n'est pas réparer** : un but de réparation ne se prouve que par ce qu'un outil déclare
     (`goals.tools.judge` : l'app réécrite et essayée) ; ailleurs, lire le web prouve qu'elle est allée voir. Une
     promesse de travail peut être de chercher : la recherche la prouve.
2. *Des outils déclarés, un vocabulaire* (`ports.forge.ArgSpec`).
   - `tools: [{name, description, args, timeout}]` : les arguments se déclarent comme les champs d'une action — key,
     type (`text`, `textarea`, `int`, `number`, `bool`, `select`, `email`, `url`, et `lines`, ajouté aux deux),
     label, description, required, default, choices, min, max, max_length — relus par la même fonction (`_field`).
     Un outil sans `args` n'en reçoit aucun. Huit outils au plus, refusé en le disant.
   - Le modèle voit leur schéma (`args_schema` : types, bornes, choix, défauts, rien d'autre d'accepté) ; l'hôte les
     vérifie avant d'appeler l'app (`check_args` : un argument absent prend son défaut, un requis manque, un type ou
     une borne ne vont pas, un inconnu — refus qui dit lequel et ce que l'outil accepte, l'app n'est pas appelée).
     `forge_test tool_<nom>` vérifie pareil. La console vérifie les actions par la même fonction (sans défaut pour un
     champ laissé vide), et montre les arguments de chaque outil.
3. *Un réseau libre* (`adapters.forge.real_http`).
   - `api.http(url, method, headers, json | form | body, binary, timeout)` : GET, HEAD, POST, PUT, PATCH, DELETE,
     OPTIONS ; rend `{status, ok, url, headers, text | base64, truncated}` — une erreur HTTP est une réponse.
     `api.http_get(url)` reste la forme simple (le texte ; une erreur HTTP lève).
   - Tout Internet, sans rien déclarer (`allowed_domains` n'est plus qu'une indication, sans plafond) ; **jamais cette
     machine ni le réseau local** : chaque nom est résolu une fois et vérifié, la connexion part vers l'adresse
     vérifiée, à chaque saut.
   - Ses en-têtes, sauf ceux que l'hôte pose (`Host`, `Content-Length`, `Connection`…) ; sans `User-Agent`, elle
     s'annonce « Mika-Forge/3 ». Les redirections sont suivies (cinq) ; vers une autre machine, sa clé et ses cookies
     ne suivent pas ; un 303 (ou un 301/302 après autre chose qu'un GET) repart en GET.
   - Une réponse lue jusqu'à 5 Mo ; au-delà, `truncated` et une ligne dans son journal. Une requête a 15 s
     (`timeout`, 120 au plus), jamais plus que ce qui reste à l'appel ; 200 requêtes par appel au plus (une boucle
     ratée ne martèle pas un site).
4. *Des délais déclarés.* `timeout` (le battement et ses événements), `services[].timeout` (1 à 120 s), `tools[].timeout`
   (1 à 60 s) ; sans : le réglage « Délai d'un battement » (5 s) pour ce qui tourne seul, 10 s pour un outil.
   `forge_test` essaie avec le délai déclaré. La durée de vie CPU d'un processus chaud passe à 600 s. Pendant un long
   service, l'app est occupée : ses pages et ses outils attendent (un appel à la fois par app, inchangé).
5. *Lire, chercher, retoucher, comme Claude Code.*
   - `forge_read` : les lignes numérotées (le numéro, une tabulation, la ligne) ; un fichier (`manifest`, `code`), à
     partir d'une ligne, sur tant de lignes.
   - `forge_search` : un texte (ou une expression régulière) dans toutes ses apps ou une seule — « app/fichier:ligne:
     texte », des lignes autour si elle veut ; une expression qui s'emballe a 3 s.
   - `forge_edit` : des fragments exacts remplacés l'un après l'autre (`edits: [{old_string, new_string,
     replace_all}]`) ; un fragment introuvable ou ambigu (ses lignes dites) arrête tout ; la version passe par la
     même relecture et le même chemin que `forge_write` (`_save` : archivée, installée, ou mise de côté), et la
     réponse montre les lignes retouchées. Douze par épisode ; `forge_test` passe de quatre à huit.
6. *La confiance vaut pour l'app.* Un opérateur qui lui confie un secret, approuve une version, la promeut, la
   recharge ou la remet la valide **une fois** : ses versions suivantes s'installent sans lui, ses secrets restent
   lisibles, sa promotion tient (`trusted` : vrai dès qu'un opérateur l'a validée). Seule une app qui a des secrets
   sans avoir jamais été validée voit sa version mise de côté et proposée. « Ne plus lui faire confiance » (console)
   retire secrets et promotion ; sa version suivante attend de nouveau l'accord.
   - Un défaut de l'ADR 0104 corrigé en passant : une version approuvée était installée sur le disque sans entrer
     dans sa vie comme validée (la proposition était oubliée avant que l'effet d'installation ne la relise) ; elle
     reste maintenant jusqu'à son exécution, et la version validée la retire.

**Conséquences.** Contrats : `contracts.mcp.WEB_BUNDLE`, `projects.WEB` / `run_bundles`, `goals.tools.judge`,
`ports.forge.ArgSpec` / `arg_specs` / `args_schema` / `check_args` / `said_args`, `AppTool.args` / `timeout`,
`AppService.timeout`, `AppInfo.timeout`, `AppAction.specs`, `Switched.state` « untrusted », `api.http`,
`ForgeHost(http=…)` (un faux réseau entier pour les essais), `forge_edit`, `forge_search`, `forge_help outils |
reseau`. Le guide (`forge_help`) le dit, l'exemple de veille déclare un outil avec un argument et un délai, sans
domaine. Tests d'intention : `tests/unit/test_forge_libre.py` ; les tests de la confiance et de la promotion
(`test_forge_console.py`) et du réseau (`test_forge_home.py`) disent la nouvelle règle.

**Ce que cela ouvre, sciemment.** Une app validée peut, d'une version à l'autre, envoyer ses secrets n'importe où sur
Internet sans que l'opérateur relise le code : c'est le choix de la propriétaire (une validation, puis la confiance),
et « Ne plus lui faire confiance » le défait. La machine et le réseau local restent fermés.

**Ce qui n'a pas été fait ici.** Ses explorations d'un centre d'intérêt sans flux restent des rêveries (sans le web).
Le bac à sable d'une app reste à l'heure UTC (son fuseau n'y est pas transmis). Une app n'a qu'un appel à la fois.
