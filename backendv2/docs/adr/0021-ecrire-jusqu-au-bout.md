# 0021 — Une écriture lancée va au bout ; la configuration précède la vie

**Contexte.** M6 a fait apparaître, sur le serveur réel, `UNIQUE constraint failed: events.seq` : la file de sortie mourait et plus aucun effet ne partait. Cause : avec le magasin à fil d'écriture, `Mind.append` attend la transaction ; si la tâche appelante est annulée à ce moment (la fermeture d'un WebSocket, un épisode supplanté), la transaction est validée par le fil mais la nouvelle racine n'est jamais publiée — l'ajout suivant reprend les mêmes `seq`. Le simulateur ne le voyait pas : son magasin est synchrone.

**Décision.**
1. Dans `Mind.append`, l'écriture est une tâche protégée : une annulation pendant l'attente est retenue, l'écriture va au bout, la racine est publiée et les abonnés notifiés, **puis** l'annulation est rendue. Une écriture refusée (magasin scellé) lève sans rien publier.
2. Ce point de suspension rend visibles des entrelacements que le magasin synchrone cachait : un processus pouvait tourner entre la persona et les paramètres (fuseau horaire par défaut — 7 h 30 à Paris lue comme la nuit). `Kernel.start(configure=…)` journalise la configuration **avant** que les voies, la reprise et les processus démarrent ; serveur, simulateur et tests passent par là.

**Conséquences.** Un test de régression annule un ajout en plein vol sur le magasin à fil et vérifie la continuité des `seq` (il reproduit l'erreur sur l'ancien code). Aucun processus ne voit plus un tempérament ou un fuseau par défaut au démarrage.
