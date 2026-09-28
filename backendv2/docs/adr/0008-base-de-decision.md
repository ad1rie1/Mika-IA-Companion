# 0008 — Une décision se juge sur l'état où elle a été prise

**Contexte.** La simulation multi-graines a montré qu'une salutation choisie par l'arbitre pouvait attendre en file derrière une réponse, être choisie une seconde fois pendant l'attente, puis partir après que la personne a écrit : sa garde comparait l'état au *démarrage* de l'épisode, qui incluait déjà le message.

**Décision.** Une demande d'épisode issue d'une sélection porte sa base de décision (`EpisodeRequest.basis`, la racine au moment du choix) ; la garde du départ compare la tête à cette base. L'arbitre ne choisit pas une ligne dont l'épisode attend encore (`Arbiter.queued`, vidé à `episode.ended`).

**Conséquences.** Une initiative périmée pendant l'attente est supplantée, jamais livrée en retard ; plus de doublon de sélection. Test de non-régression `tests/unit/test_initiative_queue.py`, non vide par mutation des deux mécanismes.
