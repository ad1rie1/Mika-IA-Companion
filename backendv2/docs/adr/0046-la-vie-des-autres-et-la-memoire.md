# 0046 — La vie des autres, sa parole, et ce qui tient

**Contexte.** L'audit A (humanité, 2026-10-02) a fait vivre des semaines à Mika sur le vrai noyau et lu ses prompts.
Ce qui la trahissait comme logiciel, du côté des autres et de la mémoire :

- *elle oubliait ce qu'elle avait seulement eu sous les yeux* (HUM-1) : un moment de la vie d'une amie (« jeudi,
  mon entretien chez Ubisoft ») était tenu pour « suivi » dès qu'il figurait dans le prompt d'un énoncé — une
  initiative partie pour tout autre chose l'éteignait, et le samedi, au « salut ! » d'Alice, il avait disparu ;
  elle ne souhaitait jamais bonne chance la veille ;
- *elle ne tenait pas parole à l'heure* (HUM-2) : « je te demanderai jeudi soir comment ça s'est passé » ne créait
  qu'une attente de promesse manquée — jeudi soir, rien ; deux heures plus tard, « j'avais promis… » et un coup
  d'estime ;
- *« sans réponse pour l'instant » après chaque « bonne nuit »* (HUM-4) : sa réponse à une clôture laissait son
  dernier message « en attente », et toutes ses salutations du lendemain le disaient ;
- *elle se croyait ignorée la nuit, et seule à l'heure du rendez-vous* (HUM-11, HUM-12) : une heure de délai sur
  Telegram, nuit comprise ; « personne ne m'a parlé depuis hier » tombait pile à l'heure où la proche passe chaque
  soir ;
- *son plat préféré s'oubliait en 3,7 jours* (HUM-6) ; *les dates relatives restaient figées* (HUM-13) ;
- *les petits détails ne revenaient pas d'eux-mêmes* (HUM-7) : « Moustache est malade » ne revenait qu'à la question
  explicite ; un « salut » ne réveillait rien, une initiative cherchait avec les mots de sa consigne ;
- *le même registre avec une inconnue et une proche* (HUM-15) ; *les souvenirs avec une proche s'endormaient comme
  ceux d'une inconnue* (HUM-17) ; *les bonnes nouvelles ne donnaient jamais envie d'écrire* (HUM-20) ; *après avoir
  été dure avec une amie, rien* (HUM-14, son côté) ; *un profil qui parle de « Mika »* (HUM-24).

**Décision.**

1. *Un moment est « repris » quand on en parle, pas quand on l'a sous les yeux.* `memory.moment_followed(event, by)`
   est un jugement enregistré : un radical du moment en commun avec ce qui est dit, son prénom mis à part
   (« alors, cet entretien ? » reprend « son entretien chez Ubisoft »), une fois le moment passé. Les mots de la
   personne se jugent à l'arrivée (un interprète de `memory` : sa réponse le sait déjà), les siens après coup (le
   processus `memory.follow` relit ce qu'elle a dit). `LifeEvent.followed_at` garde son nom et prend ce sens-là.
   `FOLLOWED_KEEP_US` reste : un moment dont elles viennent vraiment de reparler reste sous ses yeux le temps de la
   conversation, sans la consigne de demander. *Mieux que la proposition de l'audit :* le seul jugement lexical
   rate « j'ai eu le poste !! » (aucun mot en commun) ; d'où une seconde règle, mécanique — si la personne lui a
   écrit depuis le moment, la conversation en était l'occasion : pas d'initiative « alors ? » de plus
   (`others.follow_up`), la section s'en charge.
2. *La veille, encourager ; après, demander — une fois chacun* (`others.cheer`, plus faible que `follow_up`) : la
   veille au soir (ou le matin même pour un moment l'après-midi), si elles ne se sont pas parlé depuis midi la
   veille. L'initiative porte le moment pour sujet (`moment:<id>`) : dite, elle ne se refait pas. Un mot pour
   encourager n'attend pas de réponse (`others.WELL_WISHES`) : ni attente déçue, ni retenue qui empêcherait
   « alors ? » le lendemain. Envers une amie, la section « CE QUI SE PASSE DANS SA VIE » dit d'un moment passé
   que c'est « la première chose qu'une amie lui demanderait ».
3. *Une promesse datée se tient au moment dit* (`memory.keep_promise`, déclarée **due** dans `agency.OWED` : ni
   budget, ni retenue, ni rancune). La fenêtre : un peu avant l'heure dite (`memory.promise_lead_us`), ou dans la
   journée pour un jour sans heure (`PromiseNoticed.all_day`, facultatif) ; la preuve monte depuis 2. Dite, la
   promesse est tenue (`promise_resolved`, `by="parole"`, par `memory.promises`) — ni pensée « j'avais promis… »,
   ni coup d'estime. Un silence, une panne sont des essais bornés (`agency.tried`) ; une conversation depuis le
   début de la fenêtre en tenait lieu. Une promesse sans date ne déclenche rien. *Mieux que l'audit :* pas de
   seconde attente dans `attention` ; c'est `memory`, qui tient les promesses et leur texte, qui la tient.
4. *Une conversation close n'est pas « sans réponse ».* `others.read` porte `closing` (« bonne nuit », « à demain »,
   « je file » — pas une question) ; y répondre ne laisse rien en attente, pas plus qu'une personne qui s'en va
   dans les minutes qui suivent sa réponse (`attention.closing_left_us`). `AwaitingReading.closed_at` le dit (et
   `agency` pourrait s'en servir pour une retenue « elle est partie »). `last_talk` ne dit « sans réponse » que
   pour une initiative restée lettre morte, ou une question encore en suspens.
5. *Le temps des autres* (`others.hours`, `HoursReading`) : les heures où chacun écrit, apprises de ses messages
   (assez de jours vus), sinon une nuit supposée. Le délai de réponse attendu court sur **ces heures-là**
   (`reply_deadline`, plafonné par `attention.reply_quiet_extra_us`) : une initiative de 21 h 30 à quelqu'un qui écrit
   le matin attend le matin. Par messagerie, une réponse dans les trois jours compte encore
   (`attention.late_reply_message_us`), et le délai de départ passe d'une à trois heures. La solitude attend l'amie
   de tous les jours : pas de « personne ne m'a parlé » avant son heure habituelle plus une marge
   (`attention.alone_margin_us`).
6. *Ce qu'elle dit d'elle tient.* L'extraction distingue l'anecdote (qui s'efface en quelques jours) du goût, de
   l'avis, du fait de sa vie (`Believed.durable`, `about_self = 2` dans la projection, demi-vie
   `memory.self_durable_half_life_days`, un an) ; changer d'avis remplace l'ancienne croyance sans la pensée de
   confusion d'une croyance démentie. Quand on lui parle d'elle, « CE QUE TU AS DÉJÀ DIT DE TOI » montre les plus
   proches, sans seuil.
7. *La vie de l'autre revient d'elle-même.* Au premier mot d'une conversation (« salut ! ») ou quand elle écrit
   d'elle-même, le rappel ne cherche plus avec des mots qui ne désignent rien (une politesse, sa consigne) : il
   prend ce que la personne lui a raconté de sa vie ces derniers jours, de première main, sa fiche ouverte
   (`memory.person_recall_days`, `max_person_items`). Les **situations en cours** (« son chat est malade ») sont
   des moments `ongoing` (`EventNoted.ongoing`, facultatif), suivis deux semaines, redemandés après quelques jours.
   La fiche nomme ses proches (le prompt du profil, qui parle aussi « comme des notes de Mika, sans la nommer »).
8. *Les dates.* L'extraction écrit les dates en absolu ; une croyance apprise il y a plus d'une semaine dit depuis
   quand (« appris il y a 3 semaines »).
9. *Le registre selon le lien* (section `social.register`, « LE TON ENTRE VOUS ») : une inconnue n'est pas
   taquinée, une proche peut l'être — une manière d'être, dite même quand la fiche est fermée.
10. *Ce qu'on a vécu avec quelqu'un qu'on aime dure* : la demi-vie d'un souvenir est multipliée par
    `1 + memory.bond_memory_gain × attachement` (une proche vaut au moins 1, une amie ½).
11. *Une bonne nouvelle, le lendemain* : un échange heureux (joie, enthousiasme, fierté, soulagement…) avec une amie
    qui n'écrit pas tous les jours, sans autre contact depuis, donne une envie faible de lui en reparler
    (`attention.glad_*`). *Avoir été dure avec une amie* (une colère déclarée en lui répondant) laisse « J'ai été
    dure avec Alice » (`attention.REMORSE`), qui peut la pousser à revenir vers elle ; jamais envers une inconnue.

**Conséquences.** Le journal existant se rejoue (champs facultatifs ; journaux de l'ancienne base rejoués à
l'identique, sans tranche corrompue) ; tranches reconstruites depuis la genèse : `memory` v4, `attention` v5,
`others` v3. Un événement nouveau (`memory.moment_followed`), deux raisons (`memory.keep_promise`, due ;
`others.cheer`), un fait (`others.hours`), deux sections (`memory.self_said`, `social.register`), un processus
(`memory.follow`), nommés dans la console ; réglages nouveaux, bornés et documentés. Cibles d'intention, chacune
vérifiée en cassant exprès la correction : `test_life_of_others.py` (la promesse tenue à l'heure, la vague qui
attend ; montré n'est pas dit, le raconter soi-même l'est ; encourager la veille, pas après en avoir parlé ;
Moustache au premier « salut », jamais en salon ; la bonne nouvelle le lendemain ; avoir été dure),
`test_time_of_others.py` (« bonne nuit » sans « sans réponse » ; ignorée la nuit, non — deux jours, oui ; la
solitude après l'heure de l'amie), `test_memory_holds.py` (goûts durables, changer d'avis ; « appris il y a 3
semaines » ; le lien qui fait durer), `test_register.py`. Reste : l'anticipation « Adrien passe d'habitude vers
20 h » (HUM-12) ; l'entourage comme champ du profil (il passe par le résumé) ; la persona « taquine » sans
condition (H-B) ; `vocab.words.fold` ne déplie pas « œ » (« sœur » n'a pas de radical commun avec « soeur »).
