# 0013 — Les liens se vivent : proximité, rythme, manque, réconfort, retenue

**Contexte.** En v1, la proximité venait d'un profil rédigé par un modèle ; le manque d'un seuil commun à tous ; rien n'empêchait d'aller saluer quelqu'un qui venait d'insulter. Un premier essai où le modèle jugeait la proximité l'a figée au premier jugement : des messages qui se répètent n'apprennent rien de neuf, donc plus de relecture.

**Décision.**
1. *La proximité se vit* : connaissance (deux jours de contact, ou une longue conversation), amie (trois jours, quinze messages, sans froid), proche (une semaine, cinquante messages, de la chaleur). Jamais amie d'une rancune. Un opérateur peut la déclarer (`mika social closeness`). Le profil (rôle `profile`) écrit seulement le portrait, le ton, les intérêts, les sujets délicats — à partir de ce qui ne concerne que la personne.
2. *Le rythme d'une relation est le sien* : l'écart médian entre les jours où la personne a écrit (borné à [1, 30] jours ; repli selon la proximité tant qu'il n'est pas mesurable).
3. *Le manque* : une amie ou un proche, joignable (présente, ou une conversation privée où lui écrire), silencieuse depuis 1,5 fois son rythme, en journée. **Jamais deux relances de suite sans réponse.**
4. *Le réconfort* : quand elle va nettement mal, vers la personne auprès de qui elle se sent le mieux (proximité puis chaleur) — une seule à la fois.
5. *La retenue* : aucun élan vers quelqu'un qui a installé une rancune (le regard signé d'`affect`), même pas une salutation ; chaque initiative restée sans réponse rend la suivante moins probable.
6. *Ce que vit une relation déborde sur l'humeur selon la proximité* : un inconnu la touche deux fois moins qu'une amie (0,5 / 0,8 / 1 / 1,2).
7. *Un sujet délicat de quelqu'un rend confidentiel* tout souvenir qui le touche, quoi qu'en ait dit la consolidation.

**Conséquences.** S02 (troll : rancune, humeur sous la porte, ni mutisme ni élan vers lui, mais Alice saluée), S05 (première relance à 1,67 fois son rythme, à 10 h, une seule), tests unitaires par table (proximité, rythme, ton perçu).
