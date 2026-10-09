# 0081 — Le vrai, le contesté, le révolu

Quatrième lot de la refonte du modèle de connaissances (« leur validité dans le temps, et leurs droits de
diffusion », ADR 0074).

**Contexte.** Une correction ne remplaçait une croyance que si leurs confidents, leurs témoins et leur porteur
étaient les mêmes (`consolidation._can_replace`) : la vérité se jugeait avec l'audience. Alice qui disait elle-même
« j'habite à Paris maintenant » ne remplaçait pas ce que Bob avait dit d'elle ; deux croyances contradictoires
restaient actives, et le rappel servait l'une ou l'autre. À l'inverse, rien ne distinguait un ragot d'une
correction : quand le remplacement passait, la dernière version gagnait, d'où qu'elle vienne. Rien ne disait non plus
ce qui avait remplacé quoi, depuis quand une chose était vraie, ni qu'on peut revenir à ce qu'on croyait. Et changer
d'avis elle-même (« au fond, je préfère les lasagnes ») ne se ressentait pas.

Choix de l'utilisateur (2026-10-09) : une source moins sûre qui contredit, **elle doute** — les deux restent,
« contestées » ; seule une source au moins aussi sûre remplace.

**Décision.**

1. *Qui a raison ne dépend pas de qui l'a entendu.* La relecture désigne ce qu'une nouvelle croyance contredit
   (`remplace`, même quand c'est un autre qui contredit — la consigne le dit) ; le code juge
   (`faculties/memory/knowledge.py`) :
   - la sûreté d'un témoignage (`rank`) : 3, elle-même, ou la personne concernée qui parle d'elle ; 2, ce qu'elle a
     vu, ou un témoin de première main (`first_hand` : la relecture le dit, ou le code le voit — celui qui parle est
     la personne qu'on nomme) ; 1, rapporté ; 0, une déduction ;
   - `judge` : le même témoin qui se corrige **remplace** ; une source de première main au moins aussi sûre que la
     plus sûre d'avant **remplace** ; sinon elle **conteste** — un ragot ne remplace pas ce qu'Alice a dit d'elle ;
   - `target_of` remplace `_can_replace` : la croyance désignée doit être vivante et de même sorte (sur elle ou pas) ;
     un avis ou un goût d'un autre porteur ne se corrige pas (deux avis, deux porteurs : aucun n'a tort).
2. *Ce qui est remplacé sait par quoi* (`memory_items.superseded_by`, `.superseded_at`) ; *ce qui est contesté*
   reste vivant des deux côtés (`memory_contests`, dans les deux sens ; `Believed.contests`, `Attested.contests`) ;
   remplacer efface le doute qui portait sur l'ancienne.
3. *Ce qu'elle croyait, redit, revient.* Une croyance redite aux mêmes mots qu'une croyance remplacée est retrouvée
   parmi les remplacées ; jugée contre ce qu'elle croit maintenant, elle la remplace (un témoignage qui ravive
   l'ancienne) ou la conteste.
4. *Depuis et jusqu'à quand* (`Believed.as_of`, `.valid_until` ; la relecture peut les dire : `depuis`, `jusqua`) : le
   rappel date une croyance par le moment où elle est vraie (« appris il y a… ») ; une croyance qui ne valait que
   jusqu'à une date passée ne revient plus d'elle-même (un indice fort la retrouve).
5. *Le doute se dit — seulement quand les deux côtés peuvent se dire* (`recall.contested_line`) : « (mais Carol t'a
   dit autre chose : « … ») », attribué au témoin de l'autre version ; si l'autre version ne peut pas se dire ici, rien
   (le doute la laisserait deviner).
6. *Changer d'avis se ressent.* `attention` réduit aussi `memory.attested` : revenir à ce qu'elle croyait est une
   révision (« J'avais fini par croire… — finalement non ») ; changer d'avis elle-même sur ce qui la définit (une note
   durable sur elle) fait naître une réflexion (`THINKING`, `attention.own_revision_intensity`, « J'ai changé
   d'avis… »), une anecdote sur elle, rien. Une révision restée en attente plus d'un jour ne naît plus : reconstruite
   depuis la genèse, l'attention ne fait pas naître d'un coup les révisions anciennes de son journal.

**Ce qui n'est pas fait.** Les deux versions d'une croyance contestée ressortent chacune à sa place dans le rappel
(le doute est dit sur chacune, sans les fusionner en une ligne). Un texte dérivé (portrait, pensée, rêve) ne sait pas
encore qu'une de ses sources a été remplacée ou contestée après sa naissance : c'est le lot suivant. Un moment de la
vie de quelqu'un ne se conteste pas (seulement les croyances).

**Conséquences.** Aucun événement nouveau ; champs ajoutés, avec défaut : `memory.believed.contests`, `.first_hand`,
`.as_of`, `.valid_until`, `memory.attested.contests`, `.first_hand` ; le schéma de relecture gagne `de_premiere_main`,
`depuis`, `jusqua`. `memory_items` passe en v11 (le pointeur, la validité, la première main des témoignages, les
contestations ; reconstruite au démarrage — les remplacements déjà au journal retrouvent leur pointeur). Réglage
nouveau : `attention.own_revision_intensity`. La genèse accepte `believe(contests=, first_hand=, as_of=,
valid_until=)`. Cibles d'intention (`tests/unit/test_validity.py`, 9), chacune rendue rouge en cassant exprès sa
correction : le jugement par la sûreté de qui parle ; un ragot conteste ce qu'Alice a dit d'elle ; Alice remplace ce
que Bob avait dit d'elle ; le même témoin se corrige ; deux avis de deux porteurs restent ; une croyance remplacée sait
par quoi, une contestation tient dans les deux sens ; une croyance redite revient ; le doute se tait quand l'autre
version ne peut pas se dire ; changer d'avis sur ce qui la définit se ressent, une anecdote non.
