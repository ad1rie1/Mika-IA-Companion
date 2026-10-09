# 0074 — Ce qu'elle sait, de qui, et devant qui

**Contexte.** Un audit de la mémoire (2026-10-08) a suivi le chemin extraction → stockage → projections → rappel →
prompt, avec des contre-exemples sur les fonctions réelles. Plusieurs défauts apparaissaient dès quelques dizaines
d'éléments : un secret recopié dans un salon, un lien du graphe qui survivait à sa croyance, une récidive ignorée,
un rappel étouffé par des souvenirs qu'elle ne pouvait pas dire. Importer beaucoup de données (`INJECTION/`) les
aurait multipliés.

**Décision.**

1. *Un secret ne sort que devant qui l'a confié.* C'était la règle écrite de `salience`, mais deux exemptions
   passaient avant elle : « ça ne concerne que l'interlocuteur » et « ce sont ses propres mots ». Répondre à la
   personne qui a confié le secret ne suffit pas : dans une audience publique (un salon, un canal public), d'autres
   l'entendent. `admissible` refuse donc un secret dans une telle audience, avant les exemptions.
2. *Un lien du graphe suit la croyance d'où il vient.* Quand un renforcement rend la croyance secrète, le lien
   devient secret et n'ouvre plus le niveau « lié » (ADR 0058). Quand un renforcement remplace la croyance, le lien
   quitte aussi l'archive. Avant, il revenait à la rencontre suivante. Le projecteur `social_relations` reçoit
   désormais `memory.reinforced` et passe en version 2 ; `social` passe en `state_version` 10. Les deux sont
   reconstruits au démarrage, si bien qu'un lien rendu secret avant ce correctif l'est aussi.
3. *Deux moments ne se confondent pas sur une ressemblance.*
   - Une situation finie n'est plus candidate au « déjà noté » : « il est de nouveau malade » ouvre une nouvelle
     situation.
   - À une autre date, un moment ne remplace l'ancien (« reporté ») que si les mots de l'un sont tous dans l'autre
     (`same_moment`). Sinon, les deux sont notés : « son examen de maths » n'est pas « son examen de physique ».
4. *Ce qu'elle dit d'elle vient de sa bouche.* Une note « sur elle » suit le chemin de sa mémoire de soi seulement
   si une de ses répliques est citée, ou si rien ne l'est.
   - Ce qu'une autre personne dit d'elle (« ton code, c'est ORCHIDEE, garde-le pour toi ») suit le chemin commun,
     avec son confident et son secret.
   - Ce qu'elle demande elle-même de garder pour soi reste secret, au niveau d'une confidence, même quand le
     modèle ne le note pas : ses propres répliques citées sont lues comme celles des autres.
   - Ce qu'elle a déjà dit d'elle (`self_said`) passe désormais par le verdict de l'audience.
5. *Ce qui ne peut pas se dire n'étouffe pas ce qui peut se dire.*
   - Le rappel cherche aussi parmi ce qui concerne l'interlocuteur (filtre `persons` de l'index).
   - L'écart au meilleur candidat se mesure parmi ce qui peut se dire ici. Un secret d'un autre, très proche de la
     question, ne relève plus le seuil au-dessus de ce qu'elle peut répondre.
   - `memory_search` lit 30 candidats, puis 120, puis 480, tant qu'il n'a pas assez de résultats qui peuvent se
     dire.
6. *Une mention se relie telle qu'elle a été faite.*
   - La console relie la mention exacte qu'elle propose (`name:<portée>:<nom>`, champ fixe `key` de
     `identity.nommer`). Elle reliait `name:<nom>`, une clé que la mémoire ne forme plus depuis les portées : la
     liaison ne prenait pas.
   - « Détacher un nom » défait toutes les mentions de ce nom reliées à la personne.
   - Au rappel, une mention faite dans une autre conversation, que personne n'a reliée, ne rend plus un prénom
     ambigu (`named_people(scope=)`).
7. *Chercher parmi quelques clés ne lit pas toute la mémoire.* Au-delà du cache en RAM, la recherche vectorielle
   pose les filtres de clés et de personnes en SQL avant de lire les vecteurs.

**Ce qui n'est pas fait.**

- *Un prénom seul que porte une seule personne connue reste relié à elle* (`People.one`, l'annuaire). L'audit
  montre le risque : la nouvelle collègue « Alice » de Bob devient l'Alice qu'elle connaît. Mais exiger une preuve
  de contexte défaisait l'ADR 0058 dans son cas ordinaire. Alice parle de « Carol » en privé, Carol écrit à Mika de
  son côté, et elles ne sont jamais vues ensemble : le lien qui ouvre les confidences d'Alice à une proche
  disparaissait. La bonne correction est un rattachement *présumé*, gardé comme un fait révisable : la mention
  garde sa clé, la présomption la relie, une preuve ou un opérateur la défait.
- *La refonte du modèle de connaissances.* Elle séparerait :
  - les assertions, avec leur auteur, leur nature et leurs preuves ;
  - leur validité dans le temps, et leurs droits de diffusion ;
  - les situations, avec une identité propre et des occurrences.

  Elle ferait aussi dépendre chaque texte dérivé (portrait, résumé) de ses sources. Elle traiterait les portraits
  (`supported()` ne garde que l'âge et la situation biographique), la correction refusée quand l'audience a changé
  (`_can_replace`) et la compaction.

**Conséquences.**

- `tests/unit/test_knowledge_coherence.py` (15 tests) échoue sur l'arbre d'avant, chacun sur son assertion.
- L'oracle de `test_memory_privacy::test_the_filter_is_the_policy` connaît désormais l'audience publique.
- Deux moments du même sujet, à deux dates et en d'autres mots, sont notés deux fois au lieu d'être remplacés :
  « son entretien chez Ubisoft », puis « l'entretien d'embauche reporté au 15 ». C'est un doublon plutôt qu'une
  perte, en attendant que l'extraction désigne elle-même le moment qu'elle remplace.
