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

**Décision 2 : sa propriétaire la touche davantage.**
- Ce que ses propres répliques font à son humeur ne dépendait que de la proximité (une proche : ×1,2). Le poids de sa
  propriétaire (`social.WEIGHT`, 1,3 au milieu, dérivé du dévouement) existait, mais seules la contagion, les besoins
  et l'attention le lisaient. La propriétaire avait dit : elle la touche plus qu'une proche, y compris quand elle la
  fâche.
- L'affect lit ce poids : le pas de son humeur (sous son plafond, 0,5) et celui de sa posture envers la personne en
  sont multipliés. L'ancre de la relation garde son rythme : ce qui s'installe avec sa propriétaire ne va pas plus vite.
- Les évaluations relationnelles envers elle (un retour, une jalousie, une contagion) le pesaient déjà à leur source :
  elles ne sont pas pesées deux fois.

**Conséquences.**
- Cibles, rouges sur le code d'avant (mutations détectées) :
  - `test_reading.py::test_sad_because_of_her_cools_the_relation_sad_with_her_brings_closer`, quand l'affect ne lit
    que « blessant » ou quand l'estime prend la déception pour un merci ;
  - `test_temperament_paths.py::test_devotion_what_her_owner_says_to_her_moves_her_more_than_a_close_friend`, quand
    l'humeur ou la posture oublie le poids.
- Versions : `affect` v9. Pas de version pour la déception : les annotations déjà au journal portent le geste rangé à
  l'époque, qui ne pouvait pas être « décevant ».
