---
description: Relire un échantillon d'annotations de Claude Code et juger leur qualité avant de tout lancer
---

Avant de lancer la lecture complète, on vérifie sur un échantillon que les annotations sont justes. Le serveur MCP « jumeau » est ouvert.

1. Choisis 6 séances déjà lues (table `annotations` de `travail/corpus.db`) : 2 fortes (signifiance haute), 2 moyennes, et 2 de ses textes (notes ou journal) s'il y en a. Ou prends celles données ci-dessous.
2. Pour chacune, relis la séance (`seance_lire`) puis son annotation (`annotation_lire`), et juge :
   - **les émotions de ses messages** : la bonne couleur, la bonne intensité ? Une blague lue comme de la colère, un « ok » sec après une dispute lu comme « neutral » ?
   - **les souvenirs** : écrits à la première personne, sans recopier, avec des dates absolues ?
   - **ce qu'elle dit d'elle-même** (« sur_elle ») : ses goûts, ses avis, sa vie. C'est ce qui fera sa personnalité : y en a-t-il qui manquent ?
   - **la sensibilité et le secret** : bien jugés ?
   - **les rêves** qu'elle raconte : repérés ?
3. Rends un bilan court, sans recopier de contenu privé. Pour chaque critère : bon, à corriger (avec l'exemple résumé), manquant. Propose les **modifications de la consigne** (`src/twin/prompts/annoter.md`, `annoter_complet.md`) qui corrigeraient les défauts.
4. Si je valide une modification : édite la consigne, **augmente `version`** dans `src/twin/passes/annotate.py` (les séances seront relues avec la nouvelle version), lance les tests, et propose `jumeau lire --max-lots 3` pour re-vérifier.

Séances visées (facultatif) : $ARGUMENTS
