# 0107 — Les suites du parcours d'une émotion

**Contexte.** Le 2026-10-13, le parcours d'une émotion a été relu de bout en bout, du message reçu jusqu'aux souvenirs.
La propriétaire l'a trouvé juste et a demandé de corriger quatre écarts entre le code et ce qu'elle avait dit vouloir
(questionnaire du 2026-10-11, manques laissés ouverts par l'ADR 0102) :

1. triste *à cause* de quelqu'un se lisait comme triste *avec* lui ;
2. sa propriétaire ne la touchait pas plus qu'une proche ;
3. la relecture ignorait ce qu'elle avait déclaré en répondant ;
4. l'émotion ne l'aidait pas à se souvenir.

**Décision 1 : une déception blesse.**
- Sans le geste « blessant », une tristesse envers quelqu'un comptait comme de l'empathie : l'ancre de la relation
  allait vers la tendresse et l'attachement grandissait (`physics.fold_point`). Or « blessant » ne couvre que des mots
  qui visent à faire mal. Une amie qui oublie son anniversaire la rendait triste, et la relation se réchauffait.
- Le modèle a un cinquième geste dans `[EN_FACE]` : « décevant » (`reading.DISAPPOINTED`), quand la personne la déçoit
  ou la laisse de côté — un oubli qui compte, de la froideur, un rejet, pas un simple désaccord. C'est toujours le
  modèle qui juge ; le code range le mot qu'il a choisi.
- Une déception est une blessure (`reading.HURTING`) : la relation refroidit de ce qu'elle a ressenti, sans tendresse
  ni attachement, et sa réaction de tempérament s'applique comme pour des mots qui blessent.
- Elle coûte un peu d'estime (`self.disappointed_knock`, −0,01, la moitié d'une insulte, dérivé de la fragilité) et
  peut fonder un doute (« quelqu'un qui compte t'a déçue »). Des excuses s'y appliquent comme à une insulte.
- Banc de lecture, `nemotron-3-super` (Ollama Cloud), 69 cas dont 7 nouveaux (catégories K) : geste 53/69 avec
  l'ancienne consigne comme avec la nouvelle ; une soirée annulée est lue « décevant » ; aucune fausse déception
  ailleurs. Les erreurs de ce modèle sont surtout un « geste : merci » de trop, qu'on avait déjà. Retirer le geste de
  l'exemple de la consigne les supprime mais lui fait oublier la syntaxe `geste : …` (vraies insultes 3/7) : l'exemple
  reste.

**Conséquences.**
- Cible : `test_reading.py::test_sad_because_of_her_cools_the_relation_sad_with_her_brings_closer`, rouge quand
  l'affect ne lit que « blessant » ou quand l'estime prend la déception pour un merci (mutations détectées).
- Pas de nouvelle version de tranche pour ce point : les annotations déjà au journal portent le geste rangé à l'époque,
  qui ne pouvait pas être « décevant ».
