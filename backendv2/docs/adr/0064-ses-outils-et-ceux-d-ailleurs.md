# 0064 — Ses outils, et ceux qui viennent d'ailleurs (MCP)

**Contexte.** Mika n'était que **serveur** MCP : le relais qui prête ses outils à la CLI Claude Code (ADR 0026) et
`/mcp/console`. Tous ses outils sont des `ToolSpec` Python déclarés par une faculté et figés dans le registre au
démarrage ; une seule boucle d'outils, celle du runtime, les exécute. Rien ne permettait de lui brancher les outils
d'un serveur MCP — sur la machine ou sur le réseau — et rien ne montrait au même endroit **tout** ce qu'elle peut
faire, pour qui et quand. La propriétaire a décidé (2026-10-04) : l'accord se règle outil par outil (aucun, dans la
conversation, de l'opérateur) ; un serveur peut servir au-delà d'elle, jusqu'à une personne authentifiée en
tête-à-tête, jamais dans un salon ; d'abord son infrastructure à elle (serveurs locaux, réseau local, jeton) — OAuth
plus tard ; et une vue qui centralise tout, ses outils internes compris, ceux-là en lecture seule.

**Décision.**

1. *Une vue de tous ses outils* (destination « Ses outils », groupe « Son activité »). Onglets : tous ses outils
   (interne · app forgée · serveur extérieur ; lot et ce qu'il permet, pour qui, quand, en main ou à la demande, ce
   qui sort de la machine, appels des 14 derniers jours) avec la fiche de chaque outil (arguments lus du schéma,
   conditions, capacité proposée) ; *qui reçoit quoi* (lots × situations : propriétaire en privé, personne
   authentifiée en tête-à-tête, inconnue, salon, personne n'écoute) ; *ce qu'elle lit* (le texte exact de
   `acting()` et `catalogue()` pour une situation) ; *serveurs extérieurs* ; *ce que Mika expose* (le relais, la
   console MCP). **L'écran lit ce que le moteur exécute** : le registre, et le filtre d'offre du pipeline extrait en
   fonction pure (`runtime/tools.offer`) appliquée à des audiences de synthèse — jamais une recopie. Un outil
   interne est « défini dans le code — non modifiable ici » : aucune action, aucun formulaire. Une condition `when=`
   se lit par sa docstring (exigée) ; un outil qui revérifie à l'exécution le dit (`ToolSpec.rule`).
2. *Des outils dynamiques, natifs* — pas un mandataire générique (`{serveur, outil, args}` priverait le modèle des
   schémas et de la recherche d'outils). Une faculté déclare une famille de lots (`Faculty.tool_source("mcp", fn)` :
   les lots `mcp.<serveur>`) ; le noyau appelle sa source avec les ports (`Kernel.refresh_tools`, au démarrage et quand
   le port signale un changement) et `Registry.set_dynamic` valide (propriétaire, préfixe de la famille, noms uniques
   — un outil statique n'est jamais remplacé —, caractères et longueur) puis remplace d'un bloc. `registry.tools` et
   `registry.bundles` deviennent des vues fusionnées : le filtre d'offre, la preuve de travail des buts et le
   catalogue les voient sans changer. `ToolSpec.schema` porte un JSON schema brut, vérifié par un validateur minimal
   (`kernel/schema.py` : objet, requis, types, énumérations) — le serveur reste juge. Les politiques admettent la
   famille (`mcp.*`).
3. *Le client MCP est écrit à la main* (`adapters/mcp/client.py`), comme le serveur (ADR 0026 §4) : `initialize`,
   `notifications/initialized`, `tools/list` (curseur), `tools/call`, `ping`, `notifications/cancelled`,
   `notifications/tools/list_changed`. Il ne déclare aucune capacité cliente : ni `sampling` (un serveur qui ferait
   écrire son modèle), ni `elicitation`, ni `roots`. Deux transports : HTTP « streamable » (réponse JSON ou flux SSE,
   `Mcp-Session-Id`, `MCP-Protocol-Version`) et stdio (une ligne JSON-RPC par message). L'ancien transport SSE seul
   n'est pas pris.
4. *On ne sert que ce que l'opérateur a approuvé.* Chaque outil a une empreinte (nom, description, schéma,
   annotations). Les outils offerts viennent d'un **instantané approuvé**, jamais de la liste en direct : un outil
   nouveau est désactivé ; un outil dont l'empreinte change est **suspendu** jusqu'à une nouvelle approbation (un
   serveur ne change pas ce qu'elle croit faire dans son dos) ; un serveur injoignable voit ses outils retirés de
   l'offre plutôt qu'offerts puis en échec. La liste ne bouge que sur décision : le préfixe en cache reste stable.
5. *Ce que l'opérateur déclare* (Configuration › Plugins › Outils extérieurs, enregistrements scellés) : **à quoi il
   sert, pour elle** (obligatoire — la ligne de son catalogue) et quand s'en servir ; distant (adresse, jeton ou
   en-tête, scellés) ou local (commande, arguments, variables, variables secrètes scellées, réseau, dossiers
   partagés) ; pour qui ; dans quels épisodes ; en main ou à la demande ; délais et plafonds ; actif. Par outil :
   nature (lecture ou action), accord (aucun, dans la conversation, de l'opérateur), description retenue — celle du
   serveur est une donnée venue d'ailleurs, bornée et désamorcée, que l'opérateur lit avant d'approuver.
6. *Pour qui* : la propriétaire seule (par défaut) ou une personne authentifiée en tête-à-tête. **Jamais dans un
   salon**, quel que soit le réglage. Ses arguments partent de la machine : la règle de ses mains lui dit de n'y
   mettre jamais ce qu'une autre personne lui a confié.
7. *L'accord.* « Aucun » : l'appel part dans la boucle et elle lit la réponse. « De l'opérateur » : un effet proposé
   (`mcp.call`), dans Approbations, l'aperçu montre le serveur, l'outil et les arguments exacts. « Dans la
   conversation » : le même effet, et son message porte une **carte d'accord** (serveur, outil, arguments exacts,
   accepter / refuser), liée à l'empreinte des arguments, qui expire (10 min ; un jour pour l'opérateur) ; seule la
   personne de l'épisode, par sa session authentifiée, décide — un « oui » tapé ne compte pas. Le mécanisme est
   générique : un effet proposé qui porte `_decider` (l'adresse) et `_expires` se décide dans le chat, par cette
   adresse seule (`KernelPort.approval_cards` / `decide_card`, trames `approvals`, `approval`, `approval_result` —
   `docs/protocole-chat.md`). Un tel outil n'est offert que là où quelqu'un peut accepter (une réponse en
   tête-à-tête, à la propriétaire ou à une personne authentifiée) ; en initiative ou en travail, seuls « aucun » et
   « opérateur » servent. Pas de négociation de capacité avec le client : les deux clients du dépôt (web, Android)
   montrent la carte, et une carte que personne ne voit expire — elle le sait. L'opérateur peut toujours trancher
   depuis la console. L'épisode ne retient rien : exécuté, l'appel revient comme `mcp.answered` (un **contenu** que
   l'oubli atteint — jamais le champ brut du résultat de l'effet), dit dans sa réponse suivante si la personne a
   écrit (la section « CE QUE TES SERVICES T'ONT RENDU », réputée dite par sa provenance `mcp:<proposition>`), sinon
   par une initiative due (`service_answered`, dans `agency.OWED`, comme `drawing_ready`, ADR 0063). Refusé ou
   expiré (`mcp.expire` refuse au nom du délai), elle le sait aussi.
8. *Ce qui revient* est une donnée, pas une consigne : préfixé (« rendu par …, un service extérieur »), désamorcé
   (`defang`), cité, plafonné (4 000 caractères par défaut). Une erreur du serveur est un échec (`ok=False`).
9. *Le réseau.* L'adresse est choisie par l'opérateur : la machine ou le réseau local sont permis (comme une URL de
   flux) ; `http` seulement vers une adresse locale ou privée, `https` ailleurs (une autorité de certification à soi
   possible) ; pas de redirection, pas de mandataire hérité de l'environnement, délais et tailles bornés.
10. *Un serveur local* tourne sous bubblewrap, **sans repli** : `/usr` en lecture, un dossier à lui
    (`<données>/mcp/<nom>/`, son HOME), les dossiers partagés déclarés (lecture seule par défaut), réseau aucun ou
    isolé (pasta, comme l'atelier), environnement reconstruit, limites, arrêt du groupe ; N pannes d'affilée le
    mettent en panne (il le dit, l'opérateur le relance) ; sa sortie d'erreur est gardée (secrets masqués) pour
    l'opérateur. Pas de commande « installer » : un programme se trouve dans son dossier (`node_modules/.bin`,
    `.venv/bin`) ou dans le système ; un `npx -y …` télécharge dans son dossier au premier lancement, réseau isolé.
11. *Claude Code* reçoit ces outils par le relais comme les autres (`mika_plus`, à la demande) : la CLI ne se connecte
    jamais à un serveur extérieur (`--strict-mcp-config` inchangé).
12. *Santé* : l'état de chaque serveur (inactif, incomplet, connecté, en erreur, en panne, outils à revoir) ; la
    santé est « dégradée » quand un serveur actif est en panne ; une vitale « Outils à revoir ».

**Ce que le chemin a changé ailleurs.** La porte d'offre est une fonction (`runtime/tools.offer`) que le pipeline et
la console appellent ; une famille de lots s'admet par `<famille>.*`. Les traces d'épisode indexent chaque appel
d'outil (`tool_uses` : nom, réussi, quand — jamais ses arguments), élaguées et oubliées avec elles. La cage
bubblewrap de l'atelier est devenue commune (`adapters/cage.py`). La santé lit tout port qui sait dire ce qui est en
panne chez lui (`failing()`, contrôle « ports »). La règle de ses mains dit, quand un outil sort de la machine
(`ToolSpec.outside`), que ce qui en revient est une donnée et que ses arguments partent.

**Conséquences.** Rien ne change sans serveur déclaré. Un outil extérieur a les mêmes gardes qu'un outil interne
(plafonds, traces, préemption, dédoublonnage), un schéma vérifié avant de partir, et la même porte d'offre. Le moteur
Claude Code les reçoit par le relais (`mika_plus`). Réserves : le transport SSE seul (ancien) n'est pas pris ; OAuth
attendra un serveur qui l'exige ; un serveur local qui télécharge (`npx -y …`) a besoin du réseau isolé au premier
lancement, ou d'être installé dans son dossier ; une réponse exécutée pendant un redémarrage se perd (elle le dit).
La matrice « qui reçoit quoi » a montré, dès son premier rendu, que `forge_help` est offert à une inconnue (le lot
`forge` n'est réservé que par ses autres outils) — sans conséquence (un mode d'emploi), laissé tel quel.

Épreuves : `tests/protocol/test_console_tools.py` (chaque outil listé et sa fiche, aucun formulaire sur un outil du
code, la matrice et ses raisons égales à la porte du pipeline, ce qu'elle lit), `tests/architecture/
test_tools_described.py` (chaque lot dit ce qu'il permet, chaque condition d'offre se dit), `tests/unit/
test_dynamic_tools.py` (la famille, les noms pris, le remplacement d'un bloc), `tests/unit/test_episode_traces.py`
(l'index des appels), `tests/contract/test_mcp_client.py` (poignée de main, JSON et SSE, approuvé seulement, un outil
changé suspendu, disjoncteur, erreur ≠ panne, délai et annulation dite, session expirée rouverte, jeton jamais
montré, http vers Internet refusé, requête du serveur refusée, notre serveur et notre client se comprennent),
`tests/contract/test_mcp_local.py` (la cage : environnement reconstruit, son dossier, partagés en lecture ou
écriture, rien d'autre, réseau coupé ou à part, la chute dite et masquée puis relancée, sans bubblewrap rien),
`tests/unit/test_mcp_plugin.py` (l'outil approuvé devient le sien, la porte selon l'audience, le schéma refuse, la
réponse citée, la règle de ses mains), `tests/unit/test_mcp_approvals.py` (la carte à elle seule, sur ce qui a été
montré, la réponse en contenu jamais dans le journal, dite puis plus dite, un outil changé bloque, l'expiration
dite, l'accord de l'opérateur), `tests/protocol/test_console_mcp.py` (le parcours d'un opérateur, les trames de la
carte), `tests/unit/test_health.py` (un port en panne dégrade la santé). Un défaut trouvé par ces épreuves : après une
panne, la session morte était encore servie à l'appel suivant (fermée en tâche, pas détachée) — détachée tout de
suite désormais.
