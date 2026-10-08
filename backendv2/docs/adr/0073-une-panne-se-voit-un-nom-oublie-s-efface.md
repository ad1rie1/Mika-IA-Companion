# 0073 — Une panne se voit, un nom oublié s'efface

**Contexte.** Deux décisions de la passe du 2026-10-08 (budgets par fournisseur, mémoire épistémique) contredisent
des ADR plus anciennes.

Le repli par fournisseur (ADR 0026 §7, ADR 0038 §1) masquait les pannes : un appel qui échouait repartait sur un
autre modèle sans que personne le voie. Les budgets passent aussi par fournisseur, et un prompt composé pour le
principal ne tenait souvent pas dans le contexte d'un repli plus petit : le repli échouait à son tour. La
propriétaire préfère une erreur à un basculement.

Les mentions de personnes inconnues ont une clé `name:<portée>:<prénom>`, qui porte le prénom en clair. L'oubli
efface les contenus (ADR 0059) mais laissait les enveloppes du journal intactes : le prénom oublié y restait.

**Décision.**

1. *Pas de repli entre fournisseurs.* Un appel qui échoue est journalisé (appel, fournisseur, rôle) et propagé.
   Le champ `fallback` d'une fiche disparaît : une ancienne fiche reste lisible, la prochaine sauvegarde le retire.
   Au-delà de la réserve d'un abonnement Claude Code, les appels de fond sont refusés (`QuotaHeld`). La
   consolidation traite ce refus comme une panne passagère : la fenêtre attend, au plus `max_attempts` passages
   espacés, puis passe dans la file de reprises. Le repli de *rôle* (`FALLBACKS` : un rôle sans fournisseur
   retombe sur « répondre ») ne change pas.
2. *L'oubli d'un nom réécrit les enveloppes qui le portent.* C'est une exception à l'ADR 0001. Elle ne vaut que
   pour les clés `name:…`, puisqu'une clé de personne est déjà opaque. Dans la transaction de l'oubli, chaque
   enveloppe qui contient la clé est réécrite avec un jeton opaque (`forgotten:<hex>`), le même partout, ce qui
   garde le rejeu cohérent. SQLite écarte d'abord les enveloppes qui ne contiennent pas la clé. Les instantanés
   sont effacés et l'état est reconstruit.

**Conséquences.** Une panne se lit dans les journaux et au registre des appels (« Coûts et appels », son issue
`error:…` ou `timeout`), jamais derrière un autre modèle. L'oubli d'un nom coûte une lecture du journal et une reconstruction : c'est une action d'opérateur, rare.
La correction de fond serait une clé de mention opaque, avec le nom dans un `Content` déjà effaçable : la
réécriture deviendrait inutile. Elle n'est pas faite, car les clés dérivent aujourd'hui du nom dans l'identité (un
opérateur relie un nom à une personne), la mémoire, le lien social et la console.
