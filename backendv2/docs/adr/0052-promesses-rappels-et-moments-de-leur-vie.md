# 0052 — Promesses, rappels et moments de leur vie

**Contexte.** La seconde semaine de la sonde réelle (2026-10-03, nemotron-3-super sur le vrai noyau, ADR 0054) a
fait vivre à Mika la semaine de Sam, sa propriétaire : lundi, « tu peux me rappeler de prendre rdv chez le dentiste
mercredi ? » et « samedi c'est mon anniv, 30 ans » ; lundi midi, « le véto dit insuffisance rénale » ; mardi soir,
son chat Pixel est mort. Ce qui sonnait faux :

- *une promesse datée tenue la veille* : mardi à 22 h 37, « demain, tu as ton rendez-vous chez le dentiste, je te le
  rappelle comme promis » ; l'extraction a répondu `promesses_tenues: [{id: 59, statut: tenue}]` et la
  consolidation l'a réglée sans regarder l'échéance. Mercredi : plus de promesse, aucun rappel ;
- *le rappel ne tenait qu'à la désobéissance de l'extraction* : la consigne excluait des promesses « un rappel
  qu'on lui a demandé (il est noté ailleurs) » — par l'outil `goal_remind`, que le modèle n'avait pas appelé ;
- *une tâche lue comme un moment de sa vie* : l'extraction avait aussi noté « son rendez-vous chez le dentiste »
  au mercredi ; ce jour-là, « comment s'est passé ton rendez-vous chez le dentiste ? », puis « tu m'as dit que tu
  y étais déjà allé » (inventé) ;
- *un suivi sans gravité* : « c'est la première chose qu'une amie lui demanderait » poussait un rendez-vous banal
  le lendemain de la mort du chat ; et mardi soir, la matière de son initiative était « un mot pour l'encourager »
  pour le dentiste, le soir où son chat était au plus mal ;
- *un moment déjà raconté, redemandé* : mardi, « hier : son rendez-vous chez le véto — c'est la première chose
  qu'une amie lui demanderait », alors que Sam en avait donné l'issue lundi à 13 h 41 (un moment « jour entier »
  a pour instant 18 h : avant, rien ne pouvait le reprendre) ;
- *un anniversaire mal souhaité* : samedi, l'initiative de 11 h était un « prendre des nouvelles », le « joyeux
  anniversaire » n'est venu qu'à la réponse suivante ; `others.cheer` (« bonne chance ») s'appliquait aussi à un
  anniversaire, et dimanche, « comment s'est passé ton anniversaire hier ? ».

**Décision.**

1. *Une promesse datée ne se tient pas avant son jour.* La consolidation ignore un « tenue » dit avant le jour de
   l'échéance (`life.kept_too_early`, jugé à l'heure où elle a parlé dans cette conversation) ; « abandonnée »
   passe toujours (la personne y renonce). L'extraction voit pour quand chaque promesse en cours est due
   (« (à Sam [P1], pour mercredi 7 octobre) ») et la consigne le dit. *Un jour sans heure est dû toute la
   journée* : son échéance est désormais le soir (`memory.promise_day_end_min`, 20 h, au lieu de 18 h), la fenêtre
   de l'initiative `memory.keep_promise` court donc jusqu'à 22 h (quelqu'un qu'elle ne voit qu'à 19 h ou 21 h
   l'entend quand même) — l'envie, elle, monte dès 10 h et est pleine à mi-chemin (15 h), plus tôt qu'avant
   (17 h 30) : un rappel de la journée vient dans la journée ; et en conversation, « c'est le moment de le faire » vaut dès le matin de ce jour-là
   (`life.due_now`) ; le soir même, la section dit encore « (pour aujourd'hui) ». Le délai de grâce de l'attention
   (2 h après l'échéance) tombe ainsi avec la fin de la fenêtre.
2. *Un rappel demandé existe une fois et une seule.* La consigne d'extraction ne l'exclut plus : un rappel accepté
   en mots est une promesse (« lui rappeler de… »). La mémoire lit les rappels programmés (`goals.LIVE`, sorte
   `reminder`) : une promesse qui reprend un rappel de la même personne, pour la même chose (`life.same_task` : un
   mot du sujet en commun, hors du rappel, du jour et des verbes de tous les jours) et le même jour, n'est pas
   notée ; un rappel programmé *après* une promesse (« à 9 h stp ») la règle (`memory.promises` : abandonnée,
   `by="rappel"`, `memory.REMINDER_BY`). *Pourquoi ce mécanisme :* le code tranche (le modèle oublie l'outil une fois
   sur deux, l'extraction désobéit au hasard) ; le rappel programmé, plus précis (une heure), l'emporte quand il
   existe ; aucun événement nouveau, aucune dépendance de `goals` envers la mémoire.
3. *Une chose à faire n'est pas un moment de sa vie.* La consigne d'extraction le dit (« prendre rendez-vous est
   une promesse, pas un rendez-vous dont on prendra des nouvelles ») ; et le code écarte un événement qui commence
   comme une tâche (« prendre rendez-vous… », `extraction.task_words`), ou qui reprend une promesse de la même
   conversation (mêmes messages cités) ou un rappel programmé pendant elle, pour la même chose et le même jour.
   « Mercredi j'ai rendez-vous chez le dentiste » reste un moment de sa vie.
4. *Un suivi a la gravité de ce qu'il suit.*
   - Un moment dit ce qu'il pèse : `EventNoted.importance` / `LifeEvent.importance` (l'extraction le note de 1 à
     4 ; un entretien, un examen, une opération, un mariage comptent quoi qu'elle en dise, `moment_importance`).
     À partir de `memory.IMPORTANT_MOMENT` (0,7), il compte. Défaut 0,7 dans un journal plus ancien : il comptait.
   - *Quand quelque chose de grave touche la personne* : le fait `memory.hard_times(personne)` (l'instant, 0
     sinon) dit qu'un deuil, une rupture, une maladie l'ont touchée depuis moins de `memory.hard_days` (5 jours).
     La mémoire le tient de trois signes : ce qu'`others` a lu de grave dans ses messages (`others.read`,
     `grave`), sa propre réponse profondément triste pour lui, en privé (`memory.hard_reply_from`, 0,75 : « Pixel
     est parti » ne contient aucun mot de deuil, sa peine le dit), un souvenir marquant et douloureux.
   - Alors, dans « CE QUI SE PASSE DANS SA VIE », le banal se tait et ce qui compte passe après des nouvelles
     d'elle (« Ces jours-ci, quelque chose de dur lui est arrivé : d'abord prendre de ses nouvelles, le reste vient
     après » — en privé seulement : un salon n'a pas à deviner ce qui pèse). Hors de ces jours-là, l'insistance
     (« la première chose qu'une amie lui demanderait ») est réservée à ce qui compte ; le reste, « si ça vient ».
   - `others.follow_up` suit la même règle : ce qui compte, avec la preuve pleine ; l'ordinaire, ou ce qui compte
     pendant ces jours-là, si elle y pense (`others.followup_minor_evidence`, 6, sous le seuil) ; l'ordinaire,
     ces jours-là, pas du tout. `others.cheer` ne souhaite pas bonne chance pour un moment ordinaire ces jours-là.
   - *Mieux que la proposition :* la prise de nouvelles du lendemain n'avait pas lieu non plus — « je vais essayer
     de dormir », juste après, comptait comme un message rassurant. Désormais, quand quelque chose de grave la
     touche, ou pour un « bonne nuit », seul un message franchement léger rassure (`others.reassuring`).
5. *Ce qui se fête se souhaite le jour même.* `EventNoted.festive` / `LifeEvent.festive` : l'extraction le dit
   (`a_feter`), ou ses mots (« anniversaire », « mariage », « crémaillère »…) — jamais le souvenir d'un deuil
   (« l'anniversaire de la mort de son père »). Une nouvelle raison d'initiative, `others.celebrate` (preuve
   `others.celebrate_evidence`, 10, au-dessus du seuil : elle écrit seule), le jour même, dans ses heures pour
   prendre des nouvelles, une fois (sujet `moment:<id>`), avec douceur si quelque chose de grave la touche ; un vœu
   n'attend pas de réponse (`others.WELL_WISHES`). Pas de `cheer` la veille. Le moment s'ouvre au début de sa
   journée : ses vœux à elle (« joyeux anniv ! », `life.wishes`, ou un mot du moment) le reprennent, en réponse
   comme en initiative — alors ni initiative de plus, ni « comment ça s'est passé » le lendemain ; ce que la
   personne en dit (« c'est mon anniversaire aujourd'hui ! ») ne le reprend pas, ce n'est pas le lui avoir
   souhaité. S'il ne l'a pas été, un mot même en retard, le lendemain, si elle y pense. La section dit, le jour même : « aujourd'hui : son
   anniversaire — souhaite-le-lui si ce n'est pas fait ».
6. *Ce que la personne raconte le jour même reprend un moment « jour entier »* (`life.opens_at`) : pour ses mots
   à elle, un tel moment s'ouvre au début de sa journée (« le véto dit insuffisance rénale », à 13 h 41, reprend
   le véto de midi). Les mots de Mika, eux, attendent l'instant du moment (dire « bon courage » le matin n'est pas
   demander comment ça s'est passé). La consigne d'extraction donne aussi l'heure qui se devine (« ce midi »,
   12:00).
7. *Ce dont elle pourrait parler part de ce qui pèse le plus* (`needs.matter`, la seule fonction de la matière) :
   entre un moment de sa vie et ce que la personne lui a raconté, le plus lourd ; à poids égal, le moment (il a
   son heure). Ce qui se fête n'est pas une matière (c'est une raison à part) ; ces jours-là, un moment ordinaire
   non plus. Un moment déjà repris n'en est plus une. Et ce que la personne a dit d'elle ne se perdait plus faute
   de source : sans source nommée par le modèle, celle d'une croyance est la seule personne dont viennent les
   messages cités (« Pixel souffre d'insuffisance rénale », dit par Sam, était hors de « ce qu'il lui a raconté »).

**Conséquences.** Aucun type d'événement nouveau. Champs ajoutés, avec défaut (le journal se rejoue) :
`memory.event_noted.importance` (0,7) et `.festive` (faux). `memory` passe en `state_version` 5 (le moment pèse et
se fête ; qui traverse quelque chose de grave) et réduit désormais `others.read` (public) ; son réducteur de
`runtime.utterance` lit `identity.person`. Nouveau fait `memory.hard_times(personne)` (lu par `others` et `needs`) ;
constantes `memory.IMPORTANT_MOMENT`, `memory.REMINDER_BY`, raison `others.celebrate` (libellée dans la console et
dans le murmure). Paramètres : `memory.promise_day_end_min`, `memory.hard_days`, `memory.hard_reply_from`,
`others.followup_minor_evidence`, `others.celebrate_evidence`. Le processus `memory.promises` se réveille aussi sur
`goals.opened`. Cibles : `test_promises_and_moments.py` — la promesse du mercredi survit à une « tenue » du mardi
et part mercredi (à 19 h comme à 21 h), une annulation la veille l'abandonne ; un rappel demandé existe une fois
(sans outil, avec, programmé plus tard) ; « rappelle-moi de prendre rdv » ne crée pas de rendez-vous, « j'ai
rendez-vous » si ; le lendemain d'un deuil, une prise de nouvelles et pas le dentiste (un entretien, après) ; un
mot grave suffit, une réponse à peine triste non ; l'anniversaire souhaité le jour même, une fois, ni la veille ni
le lendemain (en initiative comme en réponse) ; un entretien garde l'encouragement de la veille et le suivi ; ce
qu'il raconte le jour même reprend le véto ; la matière part de ce qui pèse — chacune rouge sans sa correction.

**Ce qui reste.** `agency` ne range ni `cheer` ni `celebrate` parmi ce qui concerne la personne (`ABOUT_THEM`) :
deux initiatives restées sans réponse empêchent encore un « joyeux anniversaire ». La lecture du ton ne voit pas
un deuil dit à mots couverts (« il est parti », « on l'a endormi ») : c'est sa peine à elle qui le dit. Le lead
d'une matière « situation en cours » parle encore comme d'un moment passé (« comment ça s'est passé ? »).
