# 0009 — Une question n'est réglée que par une réponse, ou un renoncement dit

**Contexte.** S13 (pannes en série) a trouvé un message perdu : une panne simulée laissait le pipeline journaliser `cancelled`, et cette issue retirait la question de l'attente ; même effet à l'arrêt propre du serveur. Par ailleurs une réponse supplantée n'était jamais recomposée.

**Décision.** `interrupted`, `cancelled`, `superseded` et `preempted` ne règlent pas une question (dans la limite de deux tentatives). Une réponse supplantée ou préemptée est recomposée tout de suite ; une réponse arrêtée ou interrompue l'est au démarrage, sauf si la question a plus de dix minutes (répondre des heures plus tard serait pire que se taire) — auquel cas le renoncement est journalisé. `Kernel.abort()` scelle le magasin d'abord : plus rien n'est écrit après l'instant d'une panne. Une réponse qui échoue (modèle absent, erreur) est dite à la personne par un message sans voix, non journalisé.

**Conséquences.** S13 réduit (17 pannes par course, dont une pendant un appel de modèle et une entre le commit et la livraison) : aucun message perdu, aucun répondu deux fois, sur 20 graines ; la preuve lente enchaîne plus de 200 pannes.
