# 0028 — L'autre : deviner, s'étonner, apprendre de ce qui arrive, tenir parole

**Contexte.** La comparaison v1 / v2 du 2026-09-30 a relevé ce qui manquait encore pour qu'elle paraisse humaine au-delà des gestes :

- elle n'attendait que deux choses (une réponse, un retour), si bien qu'elle ne s'étonnait de rien ;
- de l'autre, elle ne lisait que les indices lexicaux du dernier message (`social`), sans savoir ce qui était habituel chez lui ;
- rien n'apprenait des conséquences : la fenêtre de réponse était fixe (vingt minutes, une heure), et l'heure de ses initiatives ne dépendait jamais des réponses reçues ;
- une promesse datée pouvait passer son échéance sans qu'elle le sache.

Quatre bizarreries connues restaient à corriger.

**Décision.**
1. *Une faculté `others`.* Elle tient, pour chaque personne, un modèle tiré de ce que cette personne fait, jamais d'un jugement de modèle de langage :
   - un **ton habituel** : une moyenne lente, qui part d'une neutralité supposée (deux messages neutres prêtés), si bien que trois premiers messages tristes ne font pas une personne triste ;
   - un **état du moment** : il suit les derniers messages et revient vers l'habituel avec une demi-vie de 3 h.

   Le ton se lit dans la forme du message (mots, négations comme « pas mal », ponctuation, majuscules, émojis). La lecture est pure, sans modèle, et a quitté `social`.
2. *La surprise est une erreur de prédiction.* Elle vaut |ton lu − ton attendu| × ce qu'elle connaît de la personne, qui atteint son maximum après huit messages. C'est un jugement enregistré : un interprète écrit `others.read` avant la réponse, qui voit donc déjà la surprise, et le rejeu retombe sur le même modèle. `others` déclare deux évaluations :
   - la surprise, d'une intensité au plus 0,4, dont la force dépend de la réactivité ;
   - l'inquiétude, relationnelle : elle suit la contagion du tempérament.
3. *L'inquiétude* naît quand une amie ou une proche envoie un message lourd dans l'absolu et nettement plus sombre que ce qu'elle attendait d'elle. Le même message venant de quelqu'un qui râle toujours ne l'inquiète pas, ni venant d'une inconnue. L'inquiétude a deux effets :
   - *Une pensée* (attention, origine `concern`), soumise à la même règle qu'un échange qui marque : une pensée par personne à la fois, trois au plus.
   - *Une prise de nouvelles* (raison `check_in`). La porte s'ouvre entre 3 et 6 h après le message ; le point exact est tiré au hasard et enregistré avec l'inquiétude, car on n'écrit pas à heure fixe. L'envie monte ensuite en 3 h, seulement en journée. Elle n'écrit qu'une fois. Un message plus léger de la personne, ou la prise de nouvelles elle-même, éteint l'inquiétude.
4. *Ce qu'elle en dit* (« CE QUE TU PERÇOIS DE SON ÉTAT ») : les indices du message auquel elle répond et, **en privé seulement**, ce qui tranche avec le ton habituel (« Ça ne ressemble pas à « Alice » »). Jamais un nombre.
5. *Apprendre de ce qui arrive.*
   - **Les délais de réponse.** On mesure le temps entre une initiative et le message suivant de la personne, sauf après une salutation ou un rappel. On garde les 9 derniers délais par classe de canal (écran, messagerie). Après trois mesures, l'attente d'une réponse dure deux fois la médiane de ces délais, au plus une journée. Elle s'allonge seulement : répondre vite d'habitude ne rend pas impatiente.
   - **Les heures où l'on répond.** Les attentes comblées ou déçues sont rangées selon le moment de la journée où elle a écrit, et font une loi bêta avec un a priori de (2, 1). Une réponse tardive rattrape la moitié d'une attente déçue. À partir de deux observations, l'écart à l'a priori, en log-odds borné à ±1,5, module ses initiatives vers cette personne à cette heure-là. Les salutations et les rappels promis n'en dépendent pas.
6. *Sa parole.* Une promesse datée devient une attente envers elle-même, qui arrive à échéance deux heures après la date promise. Que la personne lui écrive entre-temps ne tient pas la promesse. Si l'échéance passe :
   - elle ressent de la gêne ;
   - son estime baisse de 0,03 ;
   - une pensée naît (« J'avais promis à … : « … » — et je ne l'ai pas fait à temps »), qui la pousse à le lui dire.

   Tenue, même en retard, la promesse ne laisse plus de pensée.
7. *Corrections.*
   - La rancune exige une hostilité installée : un seuil à 0 ne coupe plus les ponts avec tout le monde.
   - Les plages horaires peuvent passer minuit (`kernel.clock.within_daily_window`, pour `social` et `goals`).
   - Les réducteurs de la curiosité portent le nom du réglage qu'ils appliquent.
   - La compaction replie par lots, en partant des plus anciens. Avant, elle relisait les messages les plus récents et déclarait résumés des messages plus anciens qu'elle n'avait jamais lus. Ses constantes sont devenues des réglages.

**Conséquences.** S19 (l'amie qui ne va pas bien) mesure trois choses :
- la surprise et l'inquiétude chez l'amie d'humeur légère, et rien chez celle qui râle ;
- une prise de nouvelles, une seule, entre 3 et 10 h, en journée ;
- la réponse de l'amie, qui éteint l'inquiétude.

`tests/unit/test_others.py` vérifie les intentions suivantes, chacune rendue non vide par mutation :
- le ton se lit dans la forme ;
- l'état du moment s'efface ;
- la surprise dépend de la personne ;
- les jugements sont rejouables ;
- elle prend des nouvelles, et pas quand le dernier message allait ;
- elle cesse de se croire ignorée par une amie qui répond en deux heures, une fois ce délai appris ;
- elle apprend les heures où l'on répond ;
- une promesse ne s'oublie pas en silence.

La tranche d'`attention` passe à la version 3 et se reconstruit depuis la genèse. Rien n'est ajouté au texte gardé : `others.read` ne porte que des nombres et des étiquettes écrites par le code.
