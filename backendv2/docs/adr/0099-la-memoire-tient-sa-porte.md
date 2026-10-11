# 0099 — La mémoire tient sa porte : sujets délicats, jours nommés, prévisions constatées, mémoire prête

**Contexte.** Six manques de la mémoire relevés par l'audit « émotions, conscience, mémoire » du 2026-10-11 :

1. *Un sujet délicat n'était une confidence que pour le rappel.* Ce qui touche un sujet délicat d'une personne (son
   portrait : « sa rupture », « son travail ») devenait une confidence quand le rappel le recalculait, à chaque tour.
   Ses pensées (une croyance révisée), ses buts, son journal lisaient la porte de la mémoire (`KNOWLEDGE_VIEW`) à la
   sensibilité notée par la consolidation — « personnel » — et pouvaient le redire à une amie.
2. *« Lundi » se calculait au jugé.* La relecture voyait la date du jour et les jours des messages ; « on se voit
   lundi », écrit un vendredi et relu le dimanche, devait être calculé par le modèle — avec les erreurs qu'on devine
   (le lundi passé, le mauvais mois).
3. *La première réponse après un démarrage pouvait partir sans souvenirs.* Le modèle de plongements se chargeait en
   parallèle de la relecture de sa vie ; un message qui attendait au démarrage, une reprise, passaient avant lui — et le
   rappel (2,5 s au plus) passait sans mémoire.
4. *Une prévision ne se constatait jamais.* « Léa pense qu'elle sera prise » devenait une croyance de la sorte
   « prévision » (ADR 0084), qui cessait de revenir une fois son échéance passée — sans que rien ne dise si elle
   s'était réalisée. Elle n'apprenait rien de qui prévoit juste, ni de ses propres pronostics.
5. *Ses attentes ne se lisaient nulle part.* Le réglage le promettait (« le chiffre se lit dans la console, jamais
   dans ses phrases ») ; aucune page de la console ne montrait sa calibration ni ce qu'elle apprend de qui annonce.
6. *Ce qu'elle peut raconter sans nommer personne se cherchait parmi tout.* La recherche du rappel prend les plus
   proches de la question ; ce qui peut se dire ici, plus proche, en remplissait la place et chassait ce qu'elle aurait
   pu raconter sans nom (ADR 0091).

**Décision.**

1. *À la porte* : un processus de la mémoire (`memory.delicate`) relit les nouveaux éléments à leur arrivée, et tous
   ceux d'une personne quand son portrait change (`social.DELICATE_PEOPLE` : celles dont le portrait dit des sujets
   délicats) — jamais toute la mémoire à chaque passage ; ce qui touche un de ses sujets délicats (les mêmes radicaux que le
   rappel : `recall.touches`, `delicate_topics`, une mention reliée ou présumée comprise) devient une confidence, dans
   la mémoire même (`memory.delicate` : l'élément et ses témoignages). Jamais abaissé : un sujet que le portrait ne
   dit plus ne rouvre rien. Toutes les facultés qui lisent la porte en héritent ; le rappel garde son calcul (le même).
2. *Un calendrier* : la relecture voit chaque jour nommé et daté, de la semaine qui précède les messages aux deux
   semaines qui viennent (35 jours au plus) — « Les jours autour : … lundi 12 octobre, mardi 13 octobre… ». Un jour
   nommé se situe sans calcul.
3. *Sa mémoire prête* : le serveur attend le modèle de plongements avant de la faire vivre (`kernel.live`), au plus
   `WARM_WAIT_S` (30 s) ; au-delà elle vit sans, et le premier rappel l'attend comme avant.
4. *Les prévisions constatées* : une prévision dont l'échéance est passée (depuis moins de `resolve_days`), qui
   concerne une personne de la conversation, se montre à la relecture avec les moments passés (« … (une prévision :
   s'est-elle réalisée ?) ») ; constatée par une personne qu'elle concerne — « a eu lieu » ou « annulé » —, elle
   devient `memory.resolved` de la sorte « prévision » : ce qu'elle apprend de qui l'avait prévue (`track`), et de ses
   attentes de cette sorte (`calibration`) ; la surprise et l'espoir déçu suivent comme pour un moment. Constatée,
   elle ne se montre plus. Une rumeur ne constate rien.
5. *La console* : une page « Voir venir » (mémoire) montre, par sorte d'annonce, combien de moments constatés, l'écart
   quadratique moyen (Brier) et si elle en parle plus prudemment ; et, pour chacun de ceux qui annoncent, ses moments
   tenus, reportés ou annulés et ce que vaut désormais son annonce.
6. *Chercher à part ce qui se raconte sans nom* : en réponse, quand l'audience peut entendre quelque chose sans nom, une
   recherche de plus parmi les seuls éléments qui ont une version sans nom (`veiled_pool`, filtre `keys` de l'index) ;
   jamais dans un salon, jamais en initiative.

**Conséquences.** Événement `memory.delicate` (libellé console), processus `memory.delicate` ; projection des éléments
v18 (une prévision constatée prend le statut `resolved`) ; phrases `memory.extraction.render.calendar`, `forecast` ;
la consigne de relecture dit qu'une prévision passée se constate. Cibles : `tests/unit/test_delicate_at_the_door.py`,
dans `test_moments_voice_discretion.py` le calendrier et l'ordre « mémoire prête, puis vivre » (lu dans l'AST), dans
`test_seeing_ahead.py` les prévisions constatées et la console, dans `test_veiled_retelling.py` la recherche à part ;
mutations rouges.

**Ce qui n'est pas fait.** Le rapprochement d'un élément et d'un sujet délicat reste lexical (les radicaux communs),
comme dans le rappel : un sujet dit autrement (« sa séparation » pour « sa rupture ») lui échappe. Le juger par le
modèle (à la relecture de la nuit, par exemple) serait plus fin.
