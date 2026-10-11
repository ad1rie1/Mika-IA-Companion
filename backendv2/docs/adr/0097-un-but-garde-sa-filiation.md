# 0097 — Un but garde la filiation de la pensée d'où il est né

**Contexte.** Une pensée sait d'où elle vient — ce qu'on lui a confié, et comment (en secret, à qui) — et ne se redit
que devant qui ses sources le permettent (ADR 0078 ; la révision d'une croyance que Bob lui avait confiée en secret
sur Sam ne se raconte pas à Sam). Devenue un but (« Repenser à ce que je croyais »), elle perdait cette filiation :
le but ne gardait que ses personnes et un niveau, et son titre, son résultat se montraient (« CE QUE TU AS EN
TRAIN », un rappel reprogrammé, ce qu'elle raconte en le menant au bout) là où la pensée elle-même se serait tue.

**Décision.** `goals.opened` porte la filiation de la pensée (`GoalOpened.lineage`, `Goal.lineage`) ; partout où un
but peut se dire, une seule règle (`goals.audible`) : celle de ses personnes (`hearable`) **et** celle de sa
filiation (`admits`). Sans filiation (un but qui ne vient pas de ce qu'elle sait, un journal d'avant), la règle de ses
personnes seule, comme avant.

Les pensées nées d'un échange (ses mots à elle, entre guillemets) n'ont pas de filiation : leur garde est ailleurs
(dites sans leurs mots à qui ne les a pas écrits, `attention.hidden`), et le titre d'une réflexion qui en naît ne
redit rien de ce qui a été confié.

En chemin : deux fonctions portaient le nom `reflective` avec deux sens. `goals.reflective(origin, source)` (contrat)
dit une réflexion (ce qu'on lui a confié, une croyance revue — ADR 0096) ; `goals.tools.by_reflecting(g)` dit une
séance dont le travail est d'y repenser et de l'écrire (une réflexion, ou une rêverie).

**Conséquences.** `GoalOpened.lineage`, `Goal.lineage` (défaut `None`) ; `goals` v5. Cibles :
`tests/unit/test_goal_lineage.py` ; mutations rouges (la filiation perdue à la naissance, dans l'état, non lue).
