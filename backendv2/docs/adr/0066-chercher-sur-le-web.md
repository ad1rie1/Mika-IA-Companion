# 0066 — Chercher sur le web : un plugin système qui apporte son serveur MCP

**Contexte.** Le 2026-10-04, la propriétaire lui demande de « regarder les nouvelles sur internet ». Elle répond « je
vais regarder Hacker News », n'appelle aucun outil, puis invente quatre tours d'actualité. Aucun de ses outils ne
savait aller sur le web : ses flux RSS étaient vides, et la seule « actualité » qu'elle avait en tête venait d'une app
de la Forge en mode démo. La règle de ses mains (faire, pas annoncer ; ne rien raconter qu'un outil n'a pas rendu) a
corrigé le baratin, pas le manque. La propriétaire veut DuckDuckGo (le moteur qui laisse le plus le champ libre),
**un outil système** et non un serveur à déclarer, des réglages (l'activer, l'espacement des requêtes, plusieurs pages
à la fois), et que ses points d'entrée MCP s'ajoutent au client MCP (ADR 0064) quand il est actif.

**Décision.**

1. *Un plugin `web`, sans outil à lui* (`plugins/web`). Ses paramètres (Réglages › Comportement › Recherche web) :
   actif (oui par défaut), pour qui (sa propriétaire ; ou aussi une personne authentifiée en tête-à-tête — jamais un
   salon), quand elle travaille, l'espacement des recherches (3 s), leur nombre par minute (12), la pause après un
   défi (15 min), le cache (15 min), les pages chargées en même temps (3), les pages par minute (30), la région
   (`fr-fr`), le filtrage, le délai d'un appel (45 s), les appels par épisode (4), la réponse lue (8 000 caractères).
2. *Son serveur est un serveur MCP local comme un autre* (`plugins/web/serveur.py`) : stdio, bibliothèque standard
   seulement, lancé par `python3 -I` dans la cage (ADR 0064 §10), **réseau isolé** — Internet, jamais cette machine
   ni le réseau local : la cage règle le risque d'une adresse qui viserait la machine, et le serveur refuse en plus,
   et plus clairement, ce qui n'est pas du web public. Ses réglages lui arrivent par l'environnement
   (`MIKA_WEB_*`, `Settings.from_env` / `env`). Trois outils : `search` (la version HTML de DuckDuckGo, en GET avec
   les en-têtes d'un navigateur — c'est ce qu'elle laisse passer ; titre, adresse, extrait ; publicités écartées,
   redirections défaites), `read` (le texte d'une page, le principal d'abord, par morceaux) et, si plus d'une page à
   la fois est permise, `read_pages` (le début de chacune, chargées en parallèle ; une page qui échoue le dit à sa
   place).
3. *DuckDuckGo n'a pas d'API pour les résultats web et se méfie des robots* : deux requêtes rapprochées suffisent à
   lui faire demander de prouver qu'on est humain (statut 202, `anomaly-modal`). Le serveur espace et compte les
   recherches, sert une même recherche du cache, et **se met en pause** après un défi au lieu d'insister — elle lit
   « je ne cherche plus avant 23h15 ». Fragile par nature : une page de résultats qui change de forme ne rend plus
   rien (« Aucun résultat ») jusqu'à ce qu'on adapte `ResultsParser`.
4. *Des serveurs système dans le client MCP* (`adapters/mcp/system.py`, générique) : ce qu'un plugin donne s'ajoute
   à la configuration de l'opérateur (un serveur à lui du même nom s'efface) ; leurs accords se **calculent**, jamais
   ne se rangent — l'empreinte de chaque outil est prise par la fonction même du client (`live_tool`) sur ce que le
   plugin dit que son serveur proposera (`serveur.tools`, la même définition que celle du serveur), en lecture et
   sans accord pour un outil qui se dit en lecture seule, de l'opérateur sinon. Un serveur qui proposerait autre
   chose verrait l'outil suspendu, comme partout. L'opérateur ne range rien pour eux ; des paramètres illisibles :
   aucun serveur système.
5. *La composition les rejoint* (`app/system_mcp.py`) : le plugin ne connaît pas le client, le client ne connaît
   aucun plugin. Le serveur Mika lit les paramètres courants à chaque usage du client, et un
   `kernel.params_changed` d'un plugin qui apporte un serveur relance `McpHub.reconfigure` : désactivé, son serveur
   est arrêté et ses outils quittent le registre ; réglé, il est relancé avec le nouvel environnement.

**Conséquences.** Ses outils s'appellent `mcp_web_search`, `mcp_web_read`, `mcp_web_read_pages` (lot `mcp.web`),
à la demande en conversation, offerts en travail quand un but ou un projet a pris le lot — rien ne change encore dans
ses explorations, qui ne le prennent pas d'elles-mêmes. Ils ont les gardes de tout outil venu d'ailleurs : porte
d'offre (jamais en salon), plafonds, réponse désamorcée, citée et bornée, et la règle de ses mains qui dit que ses
arguments partent de la machine. Sans bubblewrap ou sans pasta, le serveur ne part pas, et la santé le dit. Dans
« Serveurs extérieurs », `web` apparaît comme les autres ; le couper se fait dans ses paramètres, pas là.

Épreuves : `tests/unit/test_web_serveur.py` (les résultats lus comme la page les montre, l'espacement, le cache, la
pause dite, la lecture par morceaux, les adresses refusées, plusieurs pages réellement en même temps, ses réglages
par l'environnement, le protocole, l'annulation, le vrai fichier lancé comme processus), `tests/unit/
test_mcp_system.py` (ajouté actif, absent désactivé, les réglages jusqu'à l'environnement, l'empreinte égale à celle
du client, rien de rangé, le nom du système l'emporte, des paramètres illisibles), `tests/contract/
test_web_plugin.py` (dans la vraie cage, sans réseau : joint et offert sans accord, réponses en français, désactivé
puis réactivé avec une page à la fois), `tests/protocol/test_web_plugin_settings.py` (le vrai serveur : la page de
ses paramètres, ses outils au registre au démarrage, partis à la désactivation, revenus — l'abonnement aux
paramètres vérifié par mutation).
