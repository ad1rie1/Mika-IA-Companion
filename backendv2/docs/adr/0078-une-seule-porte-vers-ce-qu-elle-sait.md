# 0078 — Une seule porte vers ce qu'elle sait

Premier lot de la refonte du modèle de connaissances (ADR 0074, « Ce qui n'est pas fait » ; plan du 2026-10-09).

**Contexte.** Avant de changer la façon dont la mémoire range ce qu'elle sait (propositions et témoignages, validité,
filiation des textes dérivés), l'audit du 2026-10-09 a cherché qui lit ce qu'elle sait. Une douzaine de lecteurs,
hors de la mémoire, lisaient `memory_items` en SQL brut, chacun avec son propre filtre — et le verdict complet
(`admissible`) vivait dans `faculties/memory/salience.py`, donc **aucune autre faculté ne pouvait l'appliquer**.
Plusieurs fuyaient :

- *un rêve* fait d'un souvenir sur Sam que Bob avait confié en secret était « sur Sam » seul (`about` ne gardait que
  les personnes du souvenir) : il revenait à Sam au réveil, et devenait une matière d'initiative envers lui ;
- *la pensée d'une croyance révisée* recopiait l'ancienne et la nouvelle, sans statut ni secret ni confident : la
  révision du secret de Bob sur Sam se racontait à Sam ;
- *son récit d'elle-même*, montré partout, laissait entrer ce qui ne nomme personne — une confidence que Bob lui
  avait faite y passait ;
- *son journal intime* s'ouvrait à n'importe quel salon dès qu'il ne nommait personne, même fait d'une note secrète à
  elle ;
- *une réflexion sur Sam* (`goals/prompt.py::life_of`) voyait ce que Bob avait confié en secret, et le résultat lui
  revenait ;
- *« ce qui n'appartient qu'à vous »* (`social/sections.py::between_us`) cherchait `about LIKE` : ce que Sam partage
  avec Léa ressortait comme à Sam seul ;
- *ce qu'une personne a raconté d'elle* restait une matière d'initiative (`needs.Told`) devenu secret ou remplacé, et
  un avis ou une hypothèse y entraient.

**Décision.**

1. *Le verdict descend dans `vocab`.* `Verdict` et `admissible` vivent dans `vocab/privacy.py` (la mémoire les
   réexporte : rien ne change pour elle), avec deux audiences planchers : `private_to(personne)` (sa fiche ouverte,
   rien d'autrui au-delà de l'anodin) et `PUBLIC_FLOOR` (n'importe quel salon) ; `INTERNAL` quand personne n'écoute.
2. *La filiation d'un texte* (`vocab/lineage.py`). Une `Restriction` dit comment une chose lui a été dite (le JSON de
   l'ancien `memory.Disclosure`, qui en devient un alias) ; une source apporte une **exigence** (`Requirement`) : au
   moins une de ses restrictions doit admettre l'audience (prêt pour les témoignages du lot suivant) ; une `Lineage`
   les réunit — **toutes** doivent tenir —, et `admits` rend le verdict. `internal_only` ne s'ouvre à personne. Une
   filiation **absente** (un texte d'avant) n'est jamais une filiation vide : le lecteur garde son ancienne règle.
   `contracts.identity.resolvers(get)` donne ce que le verdict lit (une adresse reliée, une mention présumée).
3. *La porte* (`contracts/memory.py`, créée avec `memory_items`, projecteur v9) : des vues — `KNOWLEDGE_VIEW` (ce
   qu'elle tient pour sien : ni remplacé ni fondu), `KNOWLEDGE_ABOUT_VIEW`, `FORMER_VIEW` (ce qu'elle a cru),
   `RETOLD_VIEW`, `LEDGER_VIEW` (tout, statut compris, pour la console, le simulateur et l'application) —, leurs
   colonnes (`KNOWN_COLUMNS`) et `SELECT_KNOWN` / `SELECT_FORMER`. Chaque ligne se lit par
   `vocab.knowledge.known_of` en un `Known` qui porte sa `lineage` (la règle du rappel : ce qu'elle garde pour elle,
   ce qu'exigeait chaque source d'une réflexion de nuit, sinon ses personnes, le porteur d'un avis, qui l'a confié et
   entendu). Une vue peut précéder la table qu'elle lit et survit à sa reconstruction.
4. *Chaque lecteur passe par la porte*, avec son mode :
   - **écrit pour son audience** — filtré au plancher de qui le verra : le portrait (`private_to(P)`, en plus de sa
     règle de première main), la réflexion sur quelqu'un (`private_to(propriétaire)`, moments compris), son récit
     d'elle-même (`PUBLIC_FLOOR` ; ce qui est à elle seule — sans personne, sans confident, sans secret — y entre
     comme avant), ce qui n'appartient qu'à vous (l'audience vivante, et seulement ce qui ne concerne qu'elles deux) ;
   - **écrit pour elle** — non filtré, la filiation gardée, le verdict à l'affichage : le rêve (`Dreamt.lineage`, ses
     personnes comprennent qui a confié ses sources, l'oubli de Bob l'atteint), la pensée (`ThoughtBorn.lineage` ;
     celle d'une révision exige ce que permettent l'ancienne **et** la nouvelle), le journal (`Journaled.lineage` :
     sa version intime ne se montre que là où tout ce qu'il reprend peut se dire), la matière d'initiative
     (`Matter.lineage`, reprise du rêve ou de la pensée) ; le panneau de la personne (`app/mindport.py`) applique les
     mêmes règles ;
   - `needs` ne garde de ce qu'une personne a dit d'elle-même ni secret, ni avis, ni hypothèse, ni surnom, et
     l'oublie quand la croyance est remplacée ou devient secrète (`Told.item`) ;
   - l'identité, l'application, la console (`/pourquoi`) et le simulateur lisent les vues.
5. *Une règle d'architecture* (`tests/architecture/test_memory_has_one_door.py`) : aucun nom de table de la mémoire
   hors d'elle (constantes et texte SQL, docstrings exceptées) ; `LEDGER_VIEW` et `FORMER_VIEW` interdits aux
   facultés et aux plugins, sauf la pensée d'une révision. Le contrôle du texte libre des événements de la mémoire
   (`test_forgetting.py`) regarde désormais le type `str` lui-même, plus une sous-chaîne de l'annotation (« Re**str**
   iction » le déclenchait).

**Ce qui n'est pas fait.**

- Hors de la mémoire, le verdict ne relève pas la sensibilité d'un élément qui touche un sujet délicat du portrait
  d'une personne (`memory.recall.sensitivity_of`) : il est un peu moins prudent que le rappel. Le portrait lui-même en
  dépend (une boucle portrait → sujets délicats → rappel) ; c'est au lot des textes dérivés de la défaire.
- Un texte dérivé ne sait pas encore qu'une de ses sources a été remplacée, rendue secrète ou contestée après coup :
  sa filiation dit ce que ses sources permettaient à sa naissance (lot « ce qui en dérive »). Le portrait ne garde
  pas encore ses sources.
- Les journaux, rêves et pensées d'avant ce lot n'ont pas de filiation : ils gardent l'ancienne règle jusqu'à ce que
  leur courte vie les emporte.

**Conséquences.** Aucun événement nouveau. Champs ajoutés, avec défaut : `attention.thought_born.lineage`,
`self.dreamt.lineage`, `self.journaled.lineage` ; dataclasses `ThoughtReading`, `DreamReading`, `JournalReading`,
`needs.Matter`. `memory_items` passe en v9 (les vues ; reconstruite au démarrage), `self` en `state_version` 6,
`attention` en 11, `needs` en 6. Cibles d'intention (`tests/unit/test_one_door.py`, 12), chacune rendue rouge en
cassant exprès sa correction : le récit sans la confidence de Bob, le journal secret pas lu en salon (et lu en grande
confiance), la réflexion sur Sam sans le secret de Bob, « ce qui n'appartient qu'à vous » sans ce que Sam partage
avec Léa, la matière oubliée quand elle devient secrète, la filiation d'un rêve (rêvé de bout en bout, Bob parmi ses
sujets), le rêve vif pas raconté à Sam le matin (et raconté quand c'est de Sam), la révision du secret de Bob pas
dite à Sam (et dite quand c'est de Sam). La règle d'architecture tombe si l'on remet une lecture brute dans le
portrait ou le grand livre dans les rêves.
