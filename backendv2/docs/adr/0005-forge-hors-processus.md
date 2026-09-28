# 0005 — La Forge hors du processus

**Contexte.** En v1, le code écrit par Mika s'exécutait dans le processus principal derrière une analyse AST ; trois évasions ont été trouvées, dont deux en exécution de code arbitraire.

**Décision.** Les apps forgées tournent dans un sous-processus isolé par bubblewrap, parlent JSON-RPC sur stdio, sont tuées à leur délai, et leur influence est bornée (sections non fiables, preuves plafonnées).

**Conséquences.** Un plantage coûte l'app, jamais Mika ; le validateur AST devient un simple confort d'écriture.
