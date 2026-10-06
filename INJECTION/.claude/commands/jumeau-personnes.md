---
description: Revoir avec moi qui est qui dans ses archives (fusions, « elle », relations)
---

Aide-moi à finir la revue des personnes du jumeau. Le serveur MCP « jumeau » est ouvert ; ses outils lisent le corpus.

1. Lance `.venv/bin/jumeau personnes` pour rafraîchir `travail/personnes.yaml`, puis lis ce fichier.
2. Traite d'abord **« elle »**. Elle doit être reconnue dans chaque canal : la commande dit lesquels manquent. Pour un canal sans « elle », cherche (`corpus_chercher`, `personne_fiche`) quel participant écrit de son point de vue (« je », ses proches, sa vie). Propose de le déplacer sous `elle.participants`.
3. Puis les **cas à vérifier** (« a_verifier ») et les personnes les plus présentes :
   - deux entrées qui sont la même personne (même prénom, un numéro et un pseudo MSN qui se répondent) : propose une fusion, preuve à l'appui. La preuve peut être un extrait court, résumé, sans recopier de message privé ;
   - la **relation** (mère, père, sœur, conjoint, amie proche, collègue…) quand les échanges la disent clairement ;
   - un robot, un service, une liste de diffusion : `ignorer: true`.
4. **Ne modifie rien sans mon accord.** Présente tes propositions par lots de 5 à 10, avec ta raison. Une fois que je valide, édite `travail/personnes.yaml` (ou utilise `personne_noter`) et relance `.venv/bin/jumeau personnes`.

Ne cite jamais de contenu privé au-delà du strict nécessaire pour justifier une fusion.

$ARGUMENTS
