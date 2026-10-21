# 0122 — Régler ses outils, et ce qu'elle expose en MCP

**Contexte.** Le 2026-10-21, après la grille « Qui reçoit quoi » (ADR 0121), le propriétaire remarque que la console
montre ses outils sous tous les angles mais ne permet de rien décider : « il y a plein de vues pour consulter mais
rien pour dire ok ça non, ça oui ». Il veut un tableau dans l'onglet qui montrait son prompt (`outils/texte`), et, sur
« Ce qu'elle expose », pouvoir ajouter et modifier des points d'entrée MCP. Il tranche trois questions :

- **la finesse** : par outil et par situation (sa propriétaire, une personne qui a un compte, une inconnue, un salon,
  une initiative, un pas, un projet, une tâche) ;
- **la limite** : restreindre seulement. Retirer un outil, ou le passer d'« en main » à « à la demande » et
  inversement, jamais l'offrir là où le code ne l'offre pas ;
- **le MCP** : les deux. Gérer la console en MCP depuis la page (son jeton, ce qu'elle sert), et déclarer des points
  qui prêtent certains de ses outils à un agent (un nom, un jeton, une liste d'outils, lecture seule ou non).

> La console de ce qui suit (points 2, 3 et 5) a été redessinée le jour même : ADR 0123. Les règles, la console
> en MCP et les points de prêt n'ont pas changé.

**Décision.**

1. *Les règles d'un opérateur passent par la seule porte d'offre* (`runtime/tools.py`).
   - Une règle est `off`, `hand` ou `ask`, par outil et par situation. `situation_of(kind, audience)` dit la situation
     d'un épisode ; ses clés sont celles de la console (`SITUATIONS`, un test les compare). Un réveil ou un murmure n'a
     pas de situation : aucune règle ne le touche.
   - `offer(..., rules=)` retire ce qui est `off` ; `deferred` range ce qui est `hand` ou `ask` (quand tout est en main,
     un fournisseur qui ne sait pas différer, la règle ne range rien). `declare` et `catalogue` les suivent : le
     prompt dit ce que la porte a décidé.
   - Une règle ne fait que restreindre : elle s'applique après la porte du code. Un outil qui clôt une boucle
     (`ends_loop`, rendre compte d'un pas) ne se règle pas (`rule_of`).
   - Le pipeline lit les règles à chaque épisode (`EpisodeRunner.rules_of`, branché par `KernelDeps.tool_rules`). Une
     lecture qui échoue n'en applique aucune, et la panne est au journal.
   - Elles sont gardées dans les réglages (`tool_rules`, `Settings.save_tool_rules`), tenues en mémoire, relues à
     l'ouverture. Elles valent dès l'épisode suivant.
2. *La console : « Régler ses outils »* (l'onglet `outils/texte`, qui s'appelait « Ce que son prompt en dit »).
   - Par situation et par famille, chaque outil que le code y offre, sa place selon le code, et un choix : comme le
     code, en main, à la demande, retiré. Le texte exact que son prompt en porte reste dessous.
   - `POST /inspecteur/outils/regler` enregistre (jeton de formulaire, opératrice) et audite (`console.outils.regler`).
     Un outil que le code n'offre pas dans cette situation est ignoré ; ce que dit déjà le code n'est pas une règle ;
     « Tout remettre comme le code » efface la situation.
   - La grille « Qui reçoit quoi », le catalogue et la fiche d'un outil (« retiré par un opérateur », « placé par un
     opérateur ») lisent les mêmes règles.
3. *La console en MCP se gère depuis « Ce qu'elle expose »*.
   - Créer, renouveler ou fermer son jeton. Un jeton neuf se montre une seule fois, à l'opératrice qui l'a créé, avec
     sa ligne `claude mcp add` (`UI.reveal` : jamais dans une adresse). `mika mcp token` reste.
   - Choisir ce qu'elle sert : ses pages, parmi une liste blanche de pages de lecture (`inspector.mcp.SERVABLE` :
     celles d'office et d'autres, jamais une page à formulaires ni de réglages), les vues de ses facultés, les fiches et
     la recherche, « pourquoi a-t-elle dit ça ? » (`PARTS`). Ce qui n'est pas servi n'est ni listé ni lu.
4. *Ses outils prêtés* (`app/lending.py`, `/mcp/pret/<nom>`).
   - Un point prête des outils choisis parmi ce que la porte lui offre en conversation, en tête-à-tête, à l'opératrice
     qui l'a déclaré (`lendable` : moins ce qui clôt une boucle). L'agent agit avec ses droits à elle : son audience
     est celle de son adresse (`audience_of`), relue à chaque appel. Un outil qu'elle n'aurait plus n'est plus servi.
   - Chaque appel est une petite séance sans modèle, `pret:<nom>:…`. Ses arguments sont vérifiés comme dans la boucle
     d'outils (`checked_args`, partagé), et ses écritures portent cette corrélation. Ce qui sort de la machine passe
     toujours par son accord (capacités).
   - Lecture seule : aucun outil ne déclare s'il écrit (tous ont l'effet par défaut), elle se tient donc à
     l'exécution. Le contexte d'un point en lecture seule (`ReadingContext`) refuse toute écriture au journal et toute
     proposition d'effet ; l'outil qui voudrait écrire est refusé (`runtime.tools.refused.read_only`).
   - La porte : la boucle locale seulement, un jeton par point (`mlp_…`, seule son empreinte est gardée), 60 appels par
     minute au plus. Un point inconnu ou sans jeton répond 404.
   - Déclarer, régler, renouveler le jeton, retirer : depuis la page (`POST /inspecteur/outils/exposer`), audité
     (`console.mcp.…`). La page montre ce que chaque point sert vraiment et ses derniers appels (en mémoire).
5. *Le menu* sépare la rubrique « Outils & connexions » en « Outils » (la destination « Ses outils » entière, avec les
   services MCP et ce qu'elle expose, puis ses apps) et « Connexions extérieures » (les flux et capteurs, les réveils
   par API, les dépôts Git). La règle de l'ADR 0121 tient : une destination à plusieurs liens a tous ses onglets dans
   la même rubrique.

**Conséquences.**

- Restreindre ne change rien à ce que le code garantit : la porte du code passe d'abord, une règle ne fait que retirer
  ou ranger. Un réglage illisible n'enlève rien, il ne s'applique pas.
- Un point de prêt ouvre ses outils hors d'une conversation : c'est pourquoi il est local, à jeton, borné, et lit les
  droits de l'opératrice qui l'a déclaré. Une opératrice dont le compte disparaît laisse un point qui ne sert plus rien
  (audience fermée).
- La lecture seule tient à l'exécution, pas à une déclaration : un outil qui ne fait qu'appeler un port sans écrire au
  journal (lire un mail, regarder par la caméra) reste un outil de lecture.
- Les derniers appels d'un point ne survivent pas à un redémarrage ; ce qu'un point a écrit, lui, est au journal.
