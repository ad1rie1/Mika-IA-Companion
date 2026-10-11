# 0090 — Qui elle devient

Quatrième lot du chantier « qui elle devient » (plan du 2026-10-10).

**Contexte.** Son récit d'elle-même (« QUI TU ES DEVENUE », `self.narrate`) ne lisait que des souvenirs : rien de
ses goûts et de ses avis, rien de ses changements d'avis, de ce qui la passionne, de ce qu'elle sait d'elle (ADR
0087–0089), rien de ce qu'elle vit à travers ses proches — sauf une ligne d'émotion anonyme. Et il ne se réécrivait
qu'après cinq souvenirs neufs : une semaine où elle change d'avis, où une passion naît, sans grand-chose à se
remémorer, le laissait tel quel. Un souvenir anodin qui nommait quelqu'un pouvait y entrer, et le prénom avec (le
récit est montré à tout le monde).

Choix de l'utilisateur (2026-10-10) : la persona reste intacte ; ce qu'elle devient vit à côté, et son récit le
suit. Elle n'a pas de corps et vit à travers ses relations, plus fort avec sa propriétaire ; si elle est incarnée,
rien ne lui parle d'IA.

**Décision.**

1. *La matière* (`narrative.gather`, devant `PUBLIC_FLOOR`, tout le monde) :
   - ses goûts, ses avis, les faits de sa vie qui la définissent (ses notes durables, au plus huit, jamais ce qu'elle
     a demandé de taire ni ce qu'elle a dit en mentant) ;
   - ses changements d'avis depuis le dernier récit (`memory_self_changes` : avant, maintenant ; les deux côtés
     dicibles à tous) ;
   - ce qui la passionne et ce qu'elle sait d'elle (les lignes de « CE QUE TU SAIS DE TOI », `lines.py`) ;
   - ce qu'elle a vécu à travers les autres (`memory_lived`) : l'« en bref » d'un moment (ADR 0087) et ce que la
     personne est pour elle, en mots épicènes — « la personne qui compte le plus pour toi » (sa propriétaire, d'abord),
     « quelqu'un de très proche », « quelqu'un que tu aimes bien », « quelqu'un » —, jamais qui ; jamais un moment
     secret ni au-delà du personnel (`vocab.lineage.without_whom`) ;
   - ses souvenirs à elle, par saillance — **ceux qui ne concernent personne d'autre** (un souvenir anodin qui nomme
     quelqu'un n'y entre plus) ; ses vécus ne s'y redisent pas, nommés ;
   - de ce qui ne peut pas se raconter, ce que ça lui a fait (inchangé).
   `Material` est le crochet de dicibilité (`floor`) ; le récit est le seul lecteur pour l'instant.
2. *Quand* : elle le réécrit quand elle a assez changé (`changes_since` ≥ `narrative_min_changes`, 1 par défaut) —
   ses souvenirs neufs par paquets de `narrative_min_souvenirs` (5 : comme avant), chaque note sur elle qui la
   définit, chaque changement d'avis, chaque moment vécu à travers quelqu'un comptent un ; ce qu'elle sait d'elle et
   ses intérêts (une ligne qui change, un intérêt qui naît, s'avive, s'endort) comptent deux — au plus une fois par
   `narrative_every_us`. Son **premier** récit attend qu'elle ait vécu quelque chose (sa persona seule ne se raconte
   pas), et un récit sans matière ne s'écrit pas. Le processus se réveille sur ce qui le fait changer.
3. *L'appel* : sa persona complète, une consigne réécrite (`self.narrative.system` : cinq phrases, ce qui la définit
   et ce qui a changé d'abord, montré à tout le monde, pas un prénom, pas un nombre), et sa nature — une IA n'a pas
   de corps et vit ce qu'elle vit à travers les autres (`self.narrative.nature_ai`) ; incarnée, rien. **Un filet** : un
   récit qui porte un prénom de son cercle ne s'écrit pas (elle réessaiera à la période suivante).
4. *Il suit ses sources* : comme avant (ADR 0082), et l'oubli d'une personne à travers qui elle a vécu ce qu'il
   reprend le fait taire et le réécrit sans elle (`narrative_about`).
5. *La console* : le bloc du récit dit ce qui a changé depuis, et de quoi.

**Conséquences.** `SelfState` en version 10 (`self_beliefs`, `changes`, `lived` et leurs relevés au dernier récit,
`narrated_knows`, `narrated_interests`). `self.narrated` + `knows`, `interests` (champs à défaut). Réglage nouveau :
`self.narrative_min_changes` ; `self.narrative_min_souvenirs` dit maintenant combien de souvenirs valent un
changement (même valeur, même effet seul). Phrases nouvelles : `self.narrative.nature_ai`, `.beliefs`, `.changes`,
`.change`, `.knows`, `.lived_through`, `.lived_one`, `.who.*` ; consigne réécrite. Module nouveau `lines.py` (ce qui
se dit pareil dans le récit et dans son prompt, sans section : l'ordre des sections ne dépend pas de qui l'importe).
Cibles d'intention (`tests/unit/test_self_story.py`, 4 nouvelles et les 2 d'avant), chacune rendue rouge en cassant
exprès sa correction (12 mutations) : ses goûts et avis y entrent, ce qu'elle a demandé de taire jamais ; un vécu y
entre concret et anonyme, sa propriétaire d'abord, jamais un secret ni une confidence ; un changement d'avis dit
avant / maintenant, jamais un changement gardé pour elle ; un souvenir qui nomme quelqu'un n'y entre pas ; intérêts
et tendances présents ; quatre souvenirs seuls ne suffisent pas, cinq oui, un intérêt né ou un goût dit aussi, jamais
deux fois dans la journée ; l'oubli le fait taire ; incarnée, rien d'IA ; un prénom, et il ne s'écrit pas ; rien de
vécu, pas de récit.
