# 0011 — Ce que le premier test réel a changé : dans le doute, on ferme

**Contexte.** Le modèle factice remplissait toujours les champs attendus. Le premier essai sur un vrai modèle (`gemma4:31b`) a montré trois défauts qu'aucun test ne pouvait voir.

**Décision.**
1. *Un élément qui ne nomme personne concerne les personnes de la conversation.* Le modèle avait omis la liste des personnes : tout était rangé « ne concernant personne », donc dicible à tous — y compris une confidence. La consigne exige désormais la liste, et le repli est fermé.
2. *La chaleur se mesure au-dessus du repos commun.* Elle se lisait sur la valeur absolue de l'ancre ; or le repos est déjà positif l'après-midi : tout le monde paraissait « chaleureux » dès le premier échange, ce qui ouvrait le « personnel » à des inconnus. C'était la formule héritée ; elle ne pouvait pas marcher.
3. *Le jugement de sensibilité est guidé.* La santé, le travail, l'argent, la famille, les amours et les émotions de quelqu'un sont au moins « personnels » : le modèle avait rangé un entretien d'embauche et le prénom d'une sœur en « anodin ».
4. *Elle sait quel jour on est* (la date entre dans la section du rythme).

**Conséquences.** Tests de non-régression pour 1 (`test_an_item_naming_nobody_concerns_the_people_of_the_conversation`) et 2 (`test_warmth_is_earned_not_given_by_the_time_of_day`). Le point 3 dépend du modèle : il se vérifie par des essais réels, pas par un test automatique.
