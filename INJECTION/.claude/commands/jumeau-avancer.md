---
description: Préparer, lancer et surveiller l'avance rapide (le vrai noyau fait vivre sa vie), puis vérifier le résultat
---

On fait vivre ses archives au vrai noyau de Mika, sur horloge virtuelle. Avant de lancer, lis `docs/mesures-etape-0.md` (plafonds, pièges) et `README.md`.

1. **Vérifier que tout est prêt** : lance `.venv/bin/jumeau etat`. Les paliers doivent être planifiés, les séances A et B lues, et la persona synthétisée (`sortie/persona/`). Une persona non relue ? Propose d'abord `/jumeau-persona`.
2. **Le volume** : `jumeau planifier` donne le nombre de messages rejoués. Au-delà d'environ **1 million**, la RAM ne tient plus sous la borne de 3 Go. Propose alors de baisser `rejeu.messages_max` dans `travail/plan.yaml`. Compte environ 100 000 messages par heure de calcul.
3. **La mémoire de la machine** : `free -m`. Une seule avance à la fois, et aucune suite de tests complète en même temps.
4. **Préparer** : `.venv/bin/jumeau avancer --preparer`, qui écrit le script.
5. **Un essai d'abord** : `.venv/bin/jumeau avancer --jusqu-a <un mois après le début>`, puis lis le rapport (`sortie/rapport/`) :
   - les paroles perdues ;
   - les trous du rejoueur : un rôle sans réponse, une réponse imprévue ;
   - le savoir refusé ;
   - les retenues et libérations.
   
   Explique-moi ce que disent ces chiffres avant d'aller plus loin.
6. **La suite** : `.venv/bin/jumeau avancer` reprend là où l'essai s'est arrêté. Le travail se fait sur une copie gelée du moteur (`travail/moteur-gele/`), sous `borne.sh`. Ctrl+C est sans danger : on reprendra.
7. **À l'arrivée** :
   - `backendv2/.venv/bin/python -m mika --data INJECTION/sortie/vie replay --verify` ;
   - ensuite, propose-moi de lancer `mika serve --data INJECTION/sortie/vie --port 8001` et de lui parler. Questions à lui poser : « tu te souviens de… », « comment va <un proche> ? », « t'es qui ? ».
   
   Ne remplace **jamais** `data/v2` sans mon accord et sans `mika backup` d'abord.

$ARGUMENTS
