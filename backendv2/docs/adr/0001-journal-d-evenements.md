# 0001 — Un journal d'événements, des réducteurs purs

**Contexte.** En v1, l'état vivait dans des tables partagées modifiées depuis n'importe où, et des singletons en mémoire ; un redémarrage perdait ou contredisait l'état, et rien ne permettait de rejouer ni d'expliquer un comportement.

**Décision.** Tout changement d'état est un événement ajouté à un journal. Chaque faculté possède une tranche immuable, déduite par des réducteurs purs et totaux, en double tampon. Les événements portent des faits et des tirages enregistrés, jamais un état recalculé.

**Conséquences.** Rejeu exact, simulation, chaîne causale ; une faculté ajoutée se reconstruit depuis la genèse. Coût : discipline des charges utiles (upcasters) et instantanés pour des démarrages rapides.
