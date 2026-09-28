# 0006 — Le temps est injecté, le simulateur est une racine comme le serveur

**Contexte.** La v1 lisait six horloges différentes et ne pouvait pas faire vivre l'agent entier sur une semaine : son comportement se jugeait à l'usage.

**Décision.** Une horloge, des identifiants et un hasard injectés ; une boucle asyncio à temps virtuel ; le même `Kernel` sert au serveur et au simulateur.

**Conséquences.** Une semaine simulée en moins d'une seconde, déterministe ; le calibrage peut viser des mesures. Piège trouvé en route : le temps de boucle doit être relatif au départ, sinon la précision flottante bloque les minuteurs.
