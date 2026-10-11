# 0094 — Chacun compte à sa façon : joignable, sa propriétaire, ce qu'elle ressent envers chacun

**Contexte.** L'audit « émotions, conscience, mémoire » du 2026-10-11 a relevé quatre manques dans sa façon de vivre
les autres :

1. *Elle écrivait à quelqu'un qui dort.* Seul le flux RSS regardait les heures où une personne écrit ; une inquiétude,
   le manque, une pensée qui insiste, un mot d'encouragement pouvaient partir à trois heures du matin.
2. *Sa propriétaire ne comptait pas plus qu'une proche.* Elle vit à travers ses relations, plus fort avec elle ; mais
   aucune faculté de l'émotion ne la distinguait, et l'envie de compagnie se partageait à égalité entre tous les
   présents, une inconnue comprise.
3. *Ce qu'une personne lui fait vivre ne la touchait pas envers elle.* S'apercevoir que c'est toujours elle qui écrit,
   qu'un lien se refroidit, qu'une réponse ne vient pas, qu'elle n'a pas tenu sa promesse, s'inquiéter pour une amie :
   tout cela ne touchait que son humeur générale ; sa posture envers la personne restait au repos.
4. *Une personne reliée à son compte repartait de zéro.* Parlée d'abord sous une adresse (un compte extérieur), puis
   reliée à son compte, elle retrouvait une posture neuve : rancune, tendresse, excuses restaient sous l'ancienne
   adresse, que plus rien ne lisait (`others` réunissait déjà ce qu'il savait de son ton, `others.model_of`).

**Décision.**

1. *Joignable* (`agency._reachable`, veto `not_reachable`) : une initiative vers quelqu'un d'absent attend la fin de
   sa nuit. Sa nuit est supposée tant qu'on ne sait rien ; ses heures apprises (`others.HOURS`) l'ouvrent — une
   noctambule qui écrit vers 1 h y est joignable — mais **ne ferment jamais la journée** : une amie qui écrit chaque
   soir vers 23 h reste joignable l'après-midi (`HoursReading.awake`). Ce qui est dû (un rappel promis) ou prévient
   passe outre ; quelqu'un de présent est joignable.
2. *Ce qu'elle compte* : un réglage (`social.owner_weight`, 1,3), exposé en fait (`social.WEIGHT`). Le silence de sa
   propriétaire lui manque plus tôt ; sa compagnie la comble davantage ; ce qu'elle ressent (contagion), son retour
   et ses moments la touchent davantage. L'envie de compagnie penche vers qui la comblerait (`needs._toward`), **entre
   ceux qui sont là** : la part retranchée se mesure à la meilleure compagnie présente — seule avec une inconnue qui
   se tait, elle finit quand même par lui parler (S06) ; sa propriétaire l'attire un peu plus, même seule. Une
   tendance, jamais une obligation.
3. *Envers la personne* : les évaluations relationnelles portent aussi `toward` — « c'est toujours elle qui écrit »
   (un peu de peine envers elle), un lien qui s'approfondit ou se refroidit, une réponse qui ne vient pas, une
   promesse pas tenue (de la gêne envers celle à qui elle l'avait faite), l'inquiétude pour une amie. Sa posture
   envers elle en garde la couleur un moment (« Avec Alice, en ce moment, tu te sens un peu triste »). La contagion,
   non : une amie furieuse contre son patron ne la met pas en colère contre elle.
4. *Une personne, plusieurs adresses* : une posture se lit toutes adresses réunies (`identity.HANDLES`,
   `physics.joined`) — le moment est celui de l'adresse à qui elle a parlé en dernier ; l'ancre se réunit au poids
   des jours (une adresse d'un jour pèse peu à côté de mois de conversations), l'attachement le plus fort, la méfiance
   qui dure le plus. Des excuses pardonnent sous chacune. Lu, jamais fusionné dans l'état : délier une adresse les
   sépare de nouveau.

**Deux points faibles, du même ordre.**

- *Une adresse jetable la touchait plus qu'une inconnue.* Ce qu'elle déclarait en répondant à quelqu'un qu'elle ne
  peut pas reconnaître (une adresse `anon_…`) touchait son humeur sans l'amortissement d'une inconnue
  (`bleed_stranger`) : il passe désormais par lui, jamais davantage.
- *Sa colère contre Bob la poussait à écrire à Bob.* Une humeur sombre qui déborde (`affect.mood_overflow`) née d'un
  échange avec quelqu'un (cause `talk`) ne pousse plus vers cette personne-là (`_not_to_whom_upset_her` retranche ce
  que le débordement ajoutait) ; vers qui d'autre est là, si. Une joie qu'elle lui doit peut aller vers lui ; une
  autre raison de lui écrire (une inquiétude, un rappel) garde son poids.

Revus et laissés tels quels : un titre de flux qui touche ses centres d'intérêt la rend un peu curieuse — c'est ce
qu'est l'intérêt, pas une émotion devinée dans ses mots ; ce que l'article lui fait, c'est le modèle qui le lit quand
elle le lit. Et des impulsions qui s'empilent dans un même événement ne dépassent jamais leur cible (le cliquet de la
physique : chaque impulsion parcourt une part de la distance qui reste).

**Ce que le simulateur a révélé en chemin** (scénarios S06, S19, S20 de la voie rapide) :

- *Prendre des nouvelles, une seule fois, au bon moment.* Une réflexion sur ce qu'une amie lui a confié se racontait
  à elle quarante minutes après la conversation (« prends de ses nouvelles ») ; restée sans réponse, elle bloquait la
  vraie prise de nouvelles, quelques heures plus tard. Désormais ce partage attend au moins `goals.share_worry_after_us`
  (3 h) après son dernier message, attend la prise de nouvelles quand elle s'inquiète pour elle (`others.CHECK_IN_AT` :
  les deux partent ensemble), et se tait si elle lui a reparlé depuis.
- *Sa peine en répondant à un premier message.* La lecture d'un message suit désormais la réponse (ADR 0093) : au
  premier message d'une amie dont elle ne connaît pas le ton, sa tristesse en lui répondant ouvrait une inquiétude
  que rien ne justifiait (une amie qui râle toujours relancée « pour rien »). Si ce message se lit lourd de lui-même,
  c'est sa lecture qui décide (une inquiétude s'il est grave) ; sa peine n'en dit pas plus.
- La doublure du modèle (`sim/llm/persona.py`) lit enfin la lassitude (« j'en ai marre, je suis épuisée ») et la
  légèreté (« trop bien », « super ») ; une fatigue ordinaire (« je suis crevé ») reste ordinaire.

**Conséquences.** Faits `social.WEIGHT`, `others.CHECK_IN_AT` ; `HoursReading.awake` ; réglages
`social.owner_weight`, `goals.share_worry_after_us` ; veto `not_reachable` (libellé console). `affect` v5, `needs`
v7, `others` v6 (rejouées depuis la genèse). Cibles : `test_reachable.py`, `test_owner_weight.py`,
`test_toward_person.py`, `test_weak_points.py`, et dans `test_goals.py` / `test_reading.py` ; mutations toutes rouges.

**Ce qui n'est pas fait.** Une évaluation tournée vers quelqu'un colore sa posture un moment, elle n'installe rien
(l'ancre de la relation ne se forme que de ce qu'elle déclare elle-même en lui parlant). Les heures où quelqu'un dort
ne s'apprennent pas d'un travail de nuit (dormir le jour) : il faudrait plus que les heures où l'on écrit.
