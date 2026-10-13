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

**Décision 3 : la relecture part de ce qu'elle a ressenti.**
- La relecture jugeait « mon_ressenti » à neuf, sans voir ses balises : un souvenir pouvait dire « tu en étais
  contente » d'un moment où elle s'était déclarée triste en répondant.
- Ses répliques portent maintenant, dans le texte relu, ce qu'elle a déclaré en les écrivant, en mots (« (en
  l'écrivant : tristesse et un peu d'inquiétude) », `memory.extraction.render.felt`), jamais un nombre. La consigne
  dit au modèle d'en partir, sauf si la suite de la conversation montre autre chose : le dernier mot reste au modèle.
- Le calme (`neutral`) ne se dit pas ; une réplique qui racontait sans nom (ADR 0091) ne dit rien de plus.
- `Consolidate._lies` devient `_her_lines` : une seule lecture des événements de ses répliques donne le mensonge, le
  récit sans nom et la balise. `facet_words` passe de `recall` à `extraction`, qui en a besoin la première.

**Décision 4 : un moment chargé se garde mieux.**
- L'oubli ignorait les ressentis : seule l'importance notée de 1 à 4 par la relecture comptait, et une conversation
  vécue avec une peur ou une joie fortes s'endormait comme une anecdote si la relecture la disait anodine.
- Quand une facette de ce que la personne ressent, ou de ce qu'elle-même en ressent, atteint `charged_from` (0,7),
  l'importance d'un souvenir, d'une croyance ou d'un moment monte au moins à `charged_importance` (0,7, « important »).
  L'importance plus haute de la relecture l'emporte ; 0 désactive (`extraction.charged`, réglages « Oubli »).
- Le seuil reste sous celui des moments marquants (0,9) : un ressenti fort ne crée pas à lui seul des « temps durs ».
- Ce qui ne porte pas de ressenti ne change pas : ses notes sur elle-même, un moment vécu à travers quelqu'un (son
  importance est réglée à part), un souvenir né de la nuit ou d'un mensonge.

**Conséquences.**
- Cibles, rouges sur le code d'avant (mutations détectées) :
  - `test_reading.py::test_sad_because_of_her_cools_the_relation_sad_with_her_brings_closer`, quand l'affect ne lit
    que « blessant » ou quand l'estime prend la déception pour un merci ;
  - `test_temperament_paths.py::test_devotion_what_her_owner_says_to_her_moves_her_more_than_a_close_friend`, quand
    l'humeur ou la posture oublie le poids ;
  - `test_empathy.py::test_the_reread_starts_from_what_she_said_she_felt`, quand la balise n'atteint pas la ligne,
    quand le rendu la tait, ou quand le calme se dit ;
  - `test_empathy.py::test_what_moves_strongly_is_kept_better`, quand l'émotion ne compte pas, quand seule celle de
    la personne compte, quand tout monte, ou quand la croyance ou le moment oublie le plancher.
- Versions : `affect` v9. Pas de version pour la déception : les annotations déjà au journal portent le geste rangé à
  l'époque, qui ne pouvait pas être « décevant ».
