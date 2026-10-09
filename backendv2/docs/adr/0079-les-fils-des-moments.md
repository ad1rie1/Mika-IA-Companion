# 0079 — Les fils des moments

Deuxième lot de la refonte du modèle de connaissances (« les situations, avec une identité propre et des
occurrences », ADR 0074).

**Contexte.** Un moment de la vie de quelqu'un (« jeudi, son entretien chez Ubisoft ») était identifié par le numéro
de l'événement qui l'avait noté. Chaque nouvelle notation en faisait un autre :

- *redit par la personne elle-même* (après qu'un tiers l'avait annoncé, ADR 0052) ou *reporté* (ADR 0076), le moment
  changeait de numéro : ce qu'elle en avait dit (`others.spoke`, le sujet d'initiative `moment:<id>`) restait sous
  l'ancien — l'encouragement de la veille pouvait repartir le même soir ;
- *un suivi* (« alors, cet entretien ? ») jugé sur l'ancien numéro, remplacé entre-temps, tombait dans le vide ;
- *une situation finie qui recommence* (« il est de nouveau malade ») ouvrait une situation qui ne savait rien de la
  précédente (ADR 0074 avait seulement cessé de les confondre) ;
- *une matière d'initiative* tirée d'un moment reporté avait un autre texte : elle pouvait resservir.

**Décision.**

1. *Un fil par moment* (`LifeEvent.thread`, `.key`) : le premier numéro qui l'a noté. Un moment qui en remplace un
   autre (redit, reporté) ou qui rouvre une situation finie (`EventNoted.recurs`) prend son fil. La tranche de la
   mémoire retient les fils qui ne sont pas les leurs et le numéro courant de chaque fil (`threads`, `heads`, bornés
   aux 4 096 plus récents) ; l'archive (`memory_life` v2) garde le fil dans une colonne indexée. Le fait
   `memory.MOMENT_THREAD(numéro)` rend le fil d'après n'importe lequel de ses numéros.
2. *Un suivi porte son fil et l'occurrence reprise* (`MomentFollowed.thread`, `.occurrence`). Sous un numéro remplacé
   depuis, il tombe sur le moment tel qu'il est noté maintenant — s'il est à la même date ; déplacé ailleurs, ce
   n'est plus l'occurrence reprise.
3. *Une situation qui recommence* : la relecture cherche, quand une situation en cours n'a pas de jumelle vivante,
   une situation finie depuis moins de `memory.recurrence_days` (60 jours) qui dit la même chose (les mêmes mots une
   fois les prénoms ôtés, ou assez de radicaux communs) ; la nouvelle la rouvre (`recurs`), en hérite le secret, la
   sensibilité et le poids, et la remplace dans la tranche et l'archive. Le rappel le dit : « de nouveau : c'était
   fini, et ça a recommencé ». Au-delà, c'est une autre histoire. La relecture **voit** aussi les situations finies
   depuis moins de `recurrence_days` (la dernière fois de chaque fil, mêmes règles de discrétion que les situations
   en cours) et désigne celle qui revient par son numéro dans `remplace` (`en_cours` vrai) : la reprise ne dépend plus
   des mots. La sonde réelle du 2026-10-09 l'a montré : sans elles, « Moustache est de nouveau malade » n'avait laissé
   qu'un souvenir — aucune situation, rien à suivre.
4. *Ce qu'elle en dit se range sous le fil.* `others` (`state_version` 4) range `spoke` par fil — un journal d'avant
   nommait le numéro : `MOMENT_THREAD` le ramène à son fil au rejeu — et ses initiatives portent `moment:<fil>` ;
   l'encouragement de la veille se dit **une fois par date** (rien depuis la veille de ce jour-là) : redit le même
   soir, il est déjà fait ; déplacé à lundi, la nouvelle veille a le sien. Les vœux, le suivi et le mot doux d'une
   date lourde se comptent pareil. `needs` désigne une matière tirée d'un moment par son fil (`Matter.key`,
   `matter:moment:<fil>`) : reporté, il ne resert pas.

**Conséquences.** Aucun événement nouveau ; champs ajoutés, avec défaut : `memory.event_noted.recurs`,
`memory.moment_followed.thread` et `.occurrence`, `LifeEvent.thread` et `.recurs`, `needs.Matter.key`. `memory` passe
en `state_version` 12, `memory_life` en v2, `others` en 4. Réglage nouveau : `memory.recurrence_days`. La genèse
accepte `note_event(recurs=)`. Les chaînes de reports déjà au journal se relient au rejeu ; les récidives d'avant
restent deux histoires. Cibles d'intention (`tests/unit/test_moment_threads.py`, 9), chacune rendue rouge en cassant
exprès sa correction : un moment reporté deux fois garde son fil ; un suivi sous l'ancien numéro tombe sur le moment
redit (et pas sur un moment déplacé) ; une situation qui revient rouvre la sienne ; désignée par la relecture parmi les situations finies
depuis peu, aussi, même dite autrement ; finie depuis plus d'un an, non ;
l'archive garde le fil ; redit le soir même de l'encouragement, pas de second « bonne chance » ; déplacé, un
encouragement par date (contrôle).
