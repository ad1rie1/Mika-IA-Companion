# 0084 — Le temps des choses

Sixième lot de la refonte du modèle de connaissances (plan du 2026-10-09 : « le futur, sur le socle »), le premier
après la revue du socle (ADR 0078 à 0083).

**Contexte.** Un moment n'avait qu'un jour (`EventNoted.when`, à 18 h pour un jour entier — ADR 0052). Conséquences :

- « en novembre » devenait le 1er novembre — et « bonne chance » la veille, « alors, ça s'est passé comment ? » le 2 ;
  la relecture était d'ailleurs priée d'écrire AAAA-MM-JJ et rien d'autre ;
- ce qui arrive dans le monde (des élections, la sortie d'un film) se rangeait dans la vie de qui en parlait ;
- rien ne distinguait un rendez-vous fixé d'une rumeur ; une prévision (« Léa pense qu'elle sera prise », « les taux
  vont remonter ») ne se gardait nulle part ;
- elle n'a pas de corps, et rien n'empêchait de noter « samedi je vais au cinéma », dit par elle, comme un moment de
  sa vie.

Choix de l'utilisateur (2026-10-09) : elle n'a pas de corps et ne s'invente pas de vie physique ; elle vit à travers
ses relations, d'autant plus fort que c'est sa propriétaire, « comme si elle y allait » ; ses avis et pronostics sont
les siens, sur tout.

**Décision.**

1. *Une date garde sa précision* (`vocab.timespan`) : un jour (vide, la forme d'avant), un mois (AAAA-MM), une saison
   (« printemps 2027 »), une année (AAAA), une période (AAAA-MM-JJ/AAAA-MM-JJ) — `Timespan(start, end, precision,
   point)`, lu depuis ce que la relecture écrit (des formes qu'on lui demande, jamais une phrase), dit comme on le dit
   (« en novembre », « l'an prochain », « du 3 au 10 novembre », phrases `timespan.*`). Un moment garde sa fin
   (`EventNoted.until`, `LifeEvent.until`) et sa précision ; `LifeEvent.vague`, `.ends`. Une période n'a ni veille
   ni lendemain : l'encouragement de la veille, le suivi du lendemain, les vœux du jour (`others`), la matière d'une
   conversation (`needs`) l'ignorent ; elle revient dans la vie de la personne quand elle approche, tant qu'elle dure
   (un mois au plus), puis tout juste finie ; « elle me l'avait annoncé » (`social`) attend sa fin. L'archive l'indexe
   par sa fin, pour que le calendrier la recharge tant qu'elle dure.
2. *Le monde n'est la vie de personne* (`EventNoted.scope` « world », relecture `monde`) : `about` vide (un nom qu'on y
   lit ne devient pas une mention), toujours dit par quelqu'un (`told_by` : l'oublier l'emporte), jamais dans
   `LIFE_EVENTS`.
3. *Ce qu'elle vit, elle le vit à travers les autres* : un moment d'une personne qu'elle vivra à travers elle
   (`shared`, relecture `partage` — « samedi je t'emmène au salon, je te montrerai ») ; et un moment qu'elle
   s'inventerait (`sur_elle` sans personne) n'est jamais noté — la consigne le dit, le code le refuse.
4. *Ce qu'elle voit venir* : le fait `memory.ahead` (le monde et les moments partagés, pas finis) et la section
   « CE QUI VIENT » (`ahead`) — ce qui commence dans `memory.ahead_days` (21) ou dure encore, au verdict de chaque
   moment (dans un salon, l'anodin seulement), sans la vie de la personne en face (elle a sa section).
5. *À quel point c'est sûr* (`faculties.memory.likelihood`) : un a priori par nature — de la bouche de la personne
   (`likely_first_hand`, 0,9), rapporté par un autre ou du monde (`likely_reported`, 0,7), une date officielle
   (`likely_official`, 0,98), une prévision (`likely_prediction`, 0,6 : au plus comme une déduction) — que ce qu'en
   dit la personne (« c'est pas sûr », relecture `probabilite`, un mot ou un nombre) ne peut qu'abaisser : on ne croit
   pas un moment plus sûr parce qu'on nous l'affirme. Gardée (`EventNoted.likelihood`), dite en mots (« c'est prévu »,
   « ce n'est pas sûr », phrases `memory.likely.*`), jamais un nombre.
6. *Les prévisions* (relecture `previsions`) : une croyance de la sorte `prediction`, à qui la porte (`holder`), avec
   ce qu'elle attend (`Believed.expected`, `.expected_until`, `.expected_precision`) et sa vraisemblance ; ses propres
   pronostics sont des notes sur elle. Le rappel les dit « (attendu en novembre ; c'est probable) » ; une prévision ne
   revient plus d'elle-même une fois sa période passée (`valid_until`).

**Ce qui n'est pas fait.** Ce qu'elle apprend de qui reporte ou annule (la vraisemblance « apprise par témoin »), ce
qui se constate quand le moment est passé, l'anticipation qui la rend impatiente ou inquiète : le lot « voir venir,
constater ». Une période proche ne fait pas encore une matière de conversation (`needs`). La genèse ne note pas de
prévision.

**Conséquences.** Aucun événement nouveau ; champs ajoutés, avec défaut : `memory.event_noted.until`, `.precision`,
`.scope`, `.shared`, `.official`, `.likelihood` ; `memory.believed.expected`, `.expected_until`,
`.expected_precision`, `.likelihood`, `knowledge_kind` « prediction » ; `LifeEvent` les mêmes. Le schéma de relecture :
`quand` accepte les dates floues, `monde`, `partage`, `probabilite`, `date_officielle`, `previsions`. `memory_items`
passe en v13 (colonnes `until`, `precision`, `likelihood` ; `due` porte ce qu'attend une prévision), `memory_life` en
v4, la tranche `memory` en `state_version` 14. Fait nouveau `memory.ahead`, section `ahead` (libellée dans la console).
Réglages nouveaux (groupe « Ce qui vient ») : `memory.likely_first_hand`, `.likely_reported`, `.likely_official`,
`.likely_prediction`, `.ahead_days`. La genèse accepte `note_event(until=, precision=, world=, shared=, official=,
likelihood=)` ; `LifeEvent` se construit d'une seule façon (`contracts.memory.life_event_of`). Cibles d'intention
(`tests/unit/test_time_of_things.py`, 8), chacune rendue rouge en cassant exprès sa correction : un mois reste un mois
(et n'a pas de veille) ; les moments d'avant se relisent à l'identique ; un moment du monde n'est la vie de personne
et s'oublie avec qui l'a dit ; elle ne note jamais une vie physique à elle ; un moment partagé est aussi le sien,
à travers la personne ; la vraisemblance selon la nature, abaissée par ce qui en est dit ; jamais un nombre dans le
prompt ; une prévision plafonnée comme une déduction.
