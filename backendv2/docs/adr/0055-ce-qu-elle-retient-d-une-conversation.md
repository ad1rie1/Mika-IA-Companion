# 0055 — Ce qu'elle retient d'une conversation

**Contexte.** La seconde semaine de la sonde réelle (ADR 0054 ; Ollama Cloud, nemotron-3-super, 2026-10-03) a
montré ce que la mémoire garde quand le modèle d'extraction est faible. Mardi soir, après la mort du chat de Sam,
elle a gardé comme **souvenirs** ses propres répliques mot pour mot (« Tu as été là pour lui jusqu'au bout, Sam… »,
« Dors bien Sam… demain, tu as ton rendez-vous chez le dentiste… », son initiative « J'ai pensé à Pixel
aujourd'hui, tu sais comment il va ? ») et les messages de Sam sans dire qui parle ni de qui (« Pixel est parti cet
après-midi », « on l'a endormi… », « je vais essayer de dormir »). Sam l'appelle « Mikachu » depuis lundi ; dimanche,
à « tu te souviens comment je t'appelle ? », elle répond « je t'appelle Sam, tout simplement » : rien ne l'avait
retenu, et la question (« comment », « appelle ») était lue comme une politesse qui ne réveille aucun souvenir. La
fiche de Sam disait « 30 ans, célibataire » (jamais dit), ses intérêts « sa santé dentaire, son anniversaire », et
ses matériaux comprenaient « Sam est parti en disant 'allez j'y vais' ». Une seconde sonde, sur la branche
d'intégration, a ajouté trois constats : dans un salon, « qq a des nouvelles de Sam ? » puis « @Mika toi tu sais
comment il va ? » ne faisait rien revenir (« Sam » fait trois lettres, la question ne ressemble à rien de ce
qu'elle sait), si bien que la ligne « ce que Sam t'a dit en privé ne se raconte pas ici » (ADR 0054) ne partait
jamais et qu'elle répondait « j'ai pas de nouvelles non plus » ; le soir du deuil, « CE QUE TU LUI AS PROMIS »
montrait le rappel du dentiste du lendemain, et elle en parlait juste après « on l'a endormi » ; « samedi : son
anniversaire » et « samedi : l'anniversaire de Sam » étaient deux moments.

**Décision.**

1. *Une réplique recopiée n'est pas un souvenir* (`extraction.copied`, `copy_of`). Un souvenir qui reprend presque
   tous les mots d'une ligne de la conversation, dans l'ordre (80 % ; une suite exacte sous quatre mots), est une
   copie — quoi qu'en disent les numéros cités, que le modèle faible donne mal. La sienne n'est jamais gardée ;
   celle de la personne devient « Sam m'a dit : « … » », confiée par l'auteur de la ligne (source : cette ligne),
   si elle compte (importance 2 au moins), sinon rien. Une croyance qui recopie une de ses répliques à elle est
   écartée, comme celle dont les seules sources sont ses lignes (ADR 0048). Un souvenir reformulé reste : « J'ai
   consolé Sam : son chat Pixel est mort » se garde, même sourcé de ses lignes ; « Sam m'a dit que Pixel… » le
   rapporte, il ne le recopie pas.
2. *Une banalité ne se garde pas* (`vocab.words.banal`) : un souvenir ou une croyance fait seulement de noms, de mots
   vides et de ce qui ne dit rien d'une vie (partir, aller dormir, retourner bosser, se dire au revoir, « en
   disant ») — « je vais essayer de dormir », « Sam doit retourner travailler ». « Sam m'a dit merci d'avoir été
   là » n'en est pas une. Le prompt d'extraction le dit aussi, et demande des souvenirs racontés avec ses mots à
   elle, la citation seulement quand les mots exacts comptent.
3. *Ce qui n'appartient qu'à eux.* L'extraction connaît une sorte de croyance de plus : comment la personne
   l'appelle, le surnom qu'elle lui donne, leurs blagues et expressions (`entre_vous`). Le contrat gagne
   `Believed.between_us` et `Reinforced.between_us` (défaut faux : le journal se rejoue), la projection
   `memory_items` une colonne `between_us` (version 3, reconstruite). Une telle croyance est de première main (ce
   qu'un tiers en raconte n'est pas leur lien), importante (3), au moins personnelle quand elle s'est dite en privé
   — jamais devant une inconnue, jamais en public — et peut venir de ses lignes à elle (le surnom qu'elle donne).
   **Le code ne dépend pas du modèle pour le cas le plus courant** : en privé, un mot qui la salue (« salut »,
   « merci », « bonne soirée »…) et dérive de son prénom sans l'être (« Mikachu », « Mikou » ; pas « Mika », ni
   « Mikaaa ») est un surnom (`extraction.nicknames`) : retenu (« Sam m'appelle « Mikachu » ») si le modèle ne
   l'a pas fait, renforcé s'il est déjà su, et une croyance du modèle qui le contient devient « entre eux ». Ce
   qui ne dérive pas de son prénom (« salut Chef ») reste au modèle : un nom après un bonjour peut être celui de
   quelqu'un d'autre.
4. *Ça revient quand on lui en parle* : « comment je t'appelle ? », « mon surnom », « notre blague »
   (`recall.about_us`) font revenir ce qui n'appartient qu'à eux, dans « CE QUI TE REVIENT » et dans
   `memory_search`, sous le verdict habituel (à la personne elle-même, en privé). *Et avec une amie, ça nourrit
   le ton* : « LE TON ENTRE VOUS » (`social`, qui le lit dans `memory_items`) le montre à une amie ou une proche,
   en privé — « à faire vivre quand ça vient, sans forcer ». Pas de section nouvelle.
5. *Une fiche n'invente pas* (`social/profile.py`). Ce qu'elle dit de la situation de la personne — couple,
   enfants, famille, travail, logement — doit relever d'un domaine que ses matériaux abordent, et un âge doit y
   être écrit tel quel (`grounded`) ; sinon la proposition tombe (toute la phrase si c'est son début). Le portrait
   d'avant, redonné au modèle, est nettoyé de la même façon (il recopiait « célibataire »). Les intérêts sont des
   goûts : un tracas, un rendez-vous, la santé, un anniversaire n'en sont pas (`tastes`). Les matériaux sont
   choisis par importance, sans banalités ni répliques recopiées par une extraction d'avant (`note_worthy`), et
   sans ce qui n'appartient qu'à eux (qui vit dans leur ton). Le prompt le dit aussi.
6. *« Oublie ce que je t'ai dit sur la city pop, c'était une phase »* n'est pas une demande d'oubli (la console
   efface ; rien ne l'efface en conversation) : c'est une révision. Le mécanisme existait (la croyance d'avant est
   montrée à l'extraction, « remplace » la remplace) ; dans la sonde, la croyance n'avait simplement jamais été
   retenue. Le prompt nomme maintenant les goûts parmi les croyances et le cas « la personne revient sur ce qu'elle
   avait dit ». Un test le garde.
7. *Une personne nommée, elle y pense* (`recall.named_people`, `about_named`) : une personne dont elle sait quelque
   chose, nommée dans le message ou juste avant dans le même fil — par son nom ou son prénom, quand un seul le
   porte —, fait revenir quelques éléments sur elle (les plus importants et les plus frais), même quand la question
   n'a que des mots qui, sinon, ne réveillent rien. Ils passent par les verdicts habituels : en salon, la ligne
   « pas à toi d'en parler » ; un secret, rien. La logique de `unsaid` ne change pas.
8. *Un soir de deuil, pas de logistique* : quand quelque chose de grave touche la personne (`memory.hard_times`,
   ADR 0052), « CE QUE TU LUI AS PROMIS » ne montre que ce qui est dû aujourd'hui (ou en retard) ; le reste attend
   son jour — la promesse reste due et revient le jour dit.
9. *Un moment, une fois* (`extraction.same_moment`) : pour la même personne, le même jour, deux textes dont les mots,
   prénoms ôtés, sont l'un dans l'autre (« son anniversaire », « l'anniversaire de Sam ») sont le même moment — à la
   notation (dans la même relecture comme d'une conversation à l'autre) et au rendu (un journal d'avant qui en a
   deux). « son rendez-vous chez le dentiste » n'est pas « son rendez-vous chez le véto ».

**Conséquences.** Le journal se rejoue (champs à défaut ; `memory_items` reconstruite en version 3). Aucun
événement, fait, processus ni section nouveaux ; un enrichisseur `social.between_us`. Cibles :
`test_what_she_keeps.py` (chaque constat, avec son contre-exemple, vérifiés en cassant exprès chaque correction) ;
`test_memory_recall.py` (le souvenir d'une politesse y porte maintenant autre chose qu'une banalité).
Reste au modèle : le surnom qu'elle donne et ceux qui ne dérivent pas de son prénom, les blagues, et la révision
d'un goût (le code montre la croyance d'avant, il ne décide pas qu'elle est contredite).
