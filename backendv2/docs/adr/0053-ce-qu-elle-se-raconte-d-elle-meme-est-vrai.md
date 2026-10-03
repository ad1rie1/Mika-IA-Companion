# 0053 — Ce qu'elle se raconte d'elle-même est vrai

**Contexte.** La sonde réelle du 2026-10-03 (deux semaines vécues avec `nemotron-3-super` sur le vrai noyau, en temps
virtuel : `sim/sonde.py`, scènes `week` et `week_two`) a montré des réponses plutôt justes et chaleureuses, mais une
**vie intérieure qui invente**, et qui coûte cher (52 appels de « pas » de buts sur 143 en une semaine, contre 48
réponses) :

- *le journal « à raconter » était de la fiction.* Écrit chaque nuit par un appel de modèle à partir de notes
  volontairement maigres (combien de gens, l'humeur — ADR 0043), il comblait avec la persona : « j'ai discuté avec
  quelqu'un de jeux indé » le jour où le chat de Sam était malade, « rien de spécial, des échanges tranquilles » le
  jour où il est mort, « j'ai bricolé un petit overlay pour mon stream » — rien de tout ça n'avait eu lieu, et c'était
  injecté le lendemain comme « TON FIL D'HIER », jusque dans un salon Telegram ;
- *le journal intime recopiait ses répliques* : les notes lui tendaient ses propres messages, tronqués
  (« Hey Sam ! Je viens de penser à toi… prendre… ») ;
- *une réflexion en spirale, sans contexte, qui inventait.* Sam, endeuillé, répond « ouais », « bof », « je sais
  pas », « laisse tomber », « désolé je suis pas d'humeur ». La pensée naît de « laisse tomber » seul ; la réflexion
  qui en sort tourne quatre séances (« c'est venu comme ça, sans contexte »), fouille sa mémoire au hasard et conclut
  que Sam lui reprochait son perfectionnisme sur « un nouveau format de stream » qu'elle « prépare » — inventé. Le
  lundi déjà, elle inventait « leurs routines, les siestes sur le clavier » du chat ;
- *des rêveries en série, génériques* : quatre à cinq par jour (cuisine, café, bidouille, pop culture, gaming, en
  tourniquet sur sa persona), trois appels chacune, sans lien avec ce qu'on lui avait dit (Inès venait de lui parler
  de city pop japonaise) ; et « je prépare », « en stream » ;
- *le récit de soi bâti sur des banalités* : « QUI TU ES DEVENUE » réécrit à partir de « Sam est parti en disant
  'allez j'y vais' » — les seuls souvenirs anodins, les plus récents —, pas de ce qui avait marqué la semaine.

**Décision.**

1. *Ce qu'elle peut raconter de sa journée n'est plus écrit par un modèle* (`self/night.py::told_day`). Il est rendu
   d'après les faits qu'elle a le droit de dire : combien de gens elle a vus et à quels moments (« Tu as discuté avec
   deux personnes (le matin, puis le soir) »), jamais qui ni de quoi ; qu'elle a écrit à quelqu'un sans réponse ; ce
   qu'elle a fait de son côté et qui ne concerne qu'elle (`doings_of` : ce qu'elle a entrepris, mené à bout, ses
   projets, ses rêveries par leur titre — c'est là que se branche aussi ce qu'elle a fait dans sa chambre,
   `world.lived`) ; le ton de la journée, vague mais vrai (`day_tone` : « Une journée un peu lourde » dès que ce qui
   a pesé — ses émotions déclarées en parlant, les pensées nées ce jour-là — atteint `self.heavy_day_from`, même entre
   deux sourires ; « Une bonne journée » ; « en demi-teinte »), jamais pourquoi. « Une journée calme, sans rien de
   particulier » seulement quand rien n'a eu lieu. Le fil d'hier le présente comme « ce que tu peux raconter de ta
   journée d'hier à n'importe qui, si on te le demande — avec tes mots, sans rien y ajouter ni dire pourquoi » : c'est
   le modèle de la conversation qui le dit, au moment où on le lui demande. La forme de `self.journaled` ne change
   pas (`shareable` reste un contenu) : le journal se rejoue tel quel. Un appel de modèle de moins par nuit. La
   console (Pensées et nuits) montre ce qu'elle racontera de la dernière journée écrite, et de la journée en cours.
2. *Le journal intime ne lui tend plus ses phrases* : les notes disent ce qu'on lui a dit (ses mots à l'autre), et
   pour elle le fait et le ton (« Tu lui as répondu, plutôt triste » ; « De toi-même, tu as écrit à « Sam » (le soir)
   — « Sam » t'a répondu »). La consigne ajoute : n'ajoute ni activité ni détail (une boisson, un repas, un projet,
   une habitude de quelqu'un), et raconte au lieu de recopier.
3. *Une pensée née d'un échange porte ce qu'il voulait dire* (`attention/watch.py::gist`) : le moment le plus
   marquant et ce que la personne a dit autour dans le même fil (« Sam m'a dit : « … » — et aussi : « … » ») ; et,
   quand elle répondait à peine — au moins trois messages, presque tous de quelques mots, aucun long —, c'est cela
   qui reste : « Sam répondait à peine : « ouais », « bof », « je sais pas », « laisse tomber », « désolé je suis pas
   d'humeur. à demain ». ». Jamais les mots d'un autre fil (une pensée née dans un salon, anodine, ne cite pas ce que
   la personne a écrit en privé).
4. *Une réflexion a l'échange sous les yeux, tient en une séance, et n'invente rien.*
   - Une exploration née d'un échange ou d'une croyance revue est une **réflexion** : `goals.reflection_steps` (1)
     séance, sa tête et sa mémoire pour seuls outils (`goals`, `memory` : plus de `projects` — une réflexion ne
     devient pas un projet). Sa séance montre l'échange d'où elle vient (section `step_exchange`, citée : ses lignes
     et celles de la personne, depuis le dernier silence) et ce qui se passe dans la vie de la personne
     (`step_life` : les moments notés, `memory.LIFE_EVENTS`, et ce qu'elle a appris d'elle ces deux dernières
     semaines, avec qui le lui a dit si c'est un tiers). La consigne : « en une séance, repense à ce que « Sam »
     traverse… N'invente rien : ni sur sa vie (seulement ce qui est écrit ici), ni sur la tienne (aucun projet, aucune
     habitude qu'on ne t'a pas racontés). Si tu ne sais pas pourquoi c'est venu, dis-le simplement. »
   - **La dernière séance qu'un but s'accorde se clôt sur ce qu'elle a fait** (`report_step`) : une réflexion écrite
     puis « je reprendrai » est menée à bout — il n'y aura pas d'autre séance (avant : quatre séances d'enquête).
   - **Une réflexion ne se rate pas, comme une rêverie** (ADR 0043) : sans rien d'écrit, ou si le modèle dit qu'il
     « bloque », elle en reste là (`abandoned`, raison `goals.LET_GO`, dans `goals.QUIET_ENDS` avec `DISSIPATED`) —
     ni « Je bloque sur : Repenser à ce que Sam m'a confié », ni frustration, ni estime en baisse, ni trace dans son
     journal ; la pensée d'où elle venait demeure. Une exploration qui va lire ailleurs (née d'un signal) garde, elle,
     « à bout de séances, elle bloque ».
   - Ce qu'elle écrit en y repensant ne nourrit ni souvenir ni croyance sur l'autre : un pas est invisible (ni fil, ni
     consolidation), ses notes sont à elle. (Le récit qui suit — « CE À QUOI TU AS REPENSÉ » à la personne — reste
     un message visible : il n'invente plus, puisque la réflexion n'invente plus.)
5. *Des rêveries plus rares, et ancrées dans ce qui l'a touchée.* Au plus `goals.musings_per_day` (2) par jour,
   étalées sur sa journée (une le matin, une l'après-midi : l'écart vaut la journée divisée par le plafond), tout ce
   que sa curiosité lui fait ouvrir compris (rêvasser, fouiller ses flux). Avant ses centres d'intérêt de toujours,
   elle rêvasse à ce dont on lui a parlé (`goals.FROM_TALK`, `talk_subjects`, lu dans le fil, jamais deviné) : ce
   qu'une amie lui a fait découvrir (« tu devrais écouter… », « je te conseille… », sans l'avoir attristée), puis un
   sujet qui l'a intéressée (elle a répondu curieuse ou enthousiaste, d'au moins 0,5, à un message d'au moins six
   mots), d'une amie d'abord ; pendant `goals.talk_lookback_us` (deux jours). Le titre est le sien (« Rêvasser à ce
   dont « Inès » m'a parlé ») ; ses mots à elle sont cités au travail ; c'est personnel (ça concerne Inès). Une
   rêverie dit « j'aimerais », pas « je fais » : la consigne le dit, et une rêverie n'a plus d'outil de projet.
6. *Le récit de soi part de ce qui l'a marquée* (`self.material`) : ses souvenirs des deux dernières semaines
   (`self.narrative_lookback_us`) par saillance — importance, plus 0,3 × la force de leur émotion —, pas par ordre
   d'arrivée ; ce qui ne peut pas se raconter (une confidence, la peine d'une amie) y entre par ce que ça lui a fait,
   sans qui ni quoi (« tu t'es sentie triste, avec quelqu'un qui compte pour toi (plusieurs fois) »). La consigne :
   « Pars de ce qui t'a le plus marquée, pas des petites phrases du quotidien. »

**Conséquences.**
- Le journal se rejoue tel quel : aucun événement ni aucune forme de charge utile ne change. Contrats : `goals.FROM_TALK`,
  `goals.MUSING_ORIGINS`, `goals.LET_GO`, `goals.QUIET_ENDS`. Réglages nouveaux, bornés et documentés :
  `goals.reflection_steps`, `goals.musings_per_day`, `goals.talk_lookback_us`, `self.heavy_day_from`,
  `self.narrative_lookback_us`. Deux sections (`step_exchange`, `step_life`), nommées dans la console.
- Moins d'appels : un par nuit de moins (le journal à raconter), une séance par réflexion au lieu de quatre (deux
  appels avec la fin de boucle de `report_step`), deux rêveries par jour au plus au lieu de quatre à cinq.
- Le simulateur : S10 (« un but bloqué ») bloque désormais sur une exploration née de ses flux ; l'inquiétude de Bea
  y devient une réflexion qui en reste là, sans « je bloque ». La voie rapide est verte, mais S07 (« elle ne
  s'enfonce jamais ») reste au bord, avant comme après : un samedi entier seule après deux soirs sans Alice, la
  solitude tenue (`needs.felt`, 0,35 tous les quarts d'heure) plus la pensée « Personne ne m'a parlé depuis hier »
  culminent autour de 0,45–0,47 contre une barre de détresse à 0,5 — quelques minutes de décalage suffisent à la
  franchir. Ce qu'elle fait dans sa chambre (`world.lived`) devrait l'occuper ; sinon, le cumul de ces deux voix
  d'une même solitude est à revoir (`needs`, `attention`).
- Cibles d'intention, chacune vérifiée en cassant exprès la correction : `test_night.py` (une journée lourde : « un
  peu lourde », ni « rien de spécial » ni activité inventée ni personne ; une journée légère, une journée vide ; une
  rêverie dite, une réflexion pour Sam tue ; un appel par nuit ; le ton de ses réponses, pas leurs mots),
  `test_reflection.py` (la pensée de « laisse tomber » ; un échange nourri garde son moment ; un salon ne cite pas le
  privé ; l'échange et la vie de Sam sous les yeux, en une séance ; « je reprendrai » clôt ; une réflexion ne bloque
  jamais ; une exploration de flux continue ; rien ne nourrit la mémoire), `test_daydreams.py` (deux par jour,
  étalées ; contre-exemple : réglé plus haut ; ce qu'une amie lui a fait découvrir comme graine, « je le note,
  merci » non), `test_self_story.py` (le récit part de ce qui a marqué ; la confidence par ce qu'elle a fait
  ressentir), `test_goals.py` (le menteur bloque sur une exploration, pas sur une réflexion).
