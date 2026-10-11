# 0087 — Ce qu'elle dit d'elle-même tient

Premier lot du chantier « qui elle devient » (plan du 2026-10-10 : son image d'elle-même, et ce qu'elle raconte selon
qui l'écoute ; ADR 0087 → 0091).

**Contexte.** Son image d'elle-même (« QUI TU ES DEVENUE », `self.narrate`) ne bouge presque pas : le récit ne lit
que des souvenirs, et ce qu'elle dit d'elle — la matière d'un portrait — était mal gardé par la mémoire :

- « mes goûts » (genre `gouts`) devenait un fait rapporté (`claim`), et une « préférence » s'effaçait en quelques
  jours comme une anecdote : deux tables disaient le genre d'une croyance (`SELF_KINDS` pour ce qui tient, une
  correspondance recopiée deux fois dans `consolidation.py` pour la sorte de savoir), et elles ne s'accordaient pas ;
- une anecdote redite comme un goût (« j'adore les films de Miyazaki », d'abord sans genre, puis `gout`) n'était
  jamais promue : le jumeau se cherchait parmi les notes de la même sorte, et la seconde naissait à côté de la
  première ;
- revenir à ce qu'elle pensait avant d'en changer (« j'aime le jazz », « je n'aime plus le jazz », « en fait, j'aime
  le jazz ») laissait deux notes contraires vivantes : le retour à une croyance remplacée (ADR 0081) ne valait pas
  pour ses notes à elle ;
- une note sur elle (ou un pronostic à elle) pouvait naître d'une réplique où elle mentait (ADR 0076) : la relecture
  était prévenue, le code ne filtrait rien ;
- la console disait « s'efface en quelques jours » de toute note sur elle, goûts compris ;
- `faculties/self/__init__.py` tenait en 816 lignes : persona, estime, récit, absences, bonjours, sans découpe.

**Décision.**

1. *Découper `self` sans rien changer.* `faculty.py` (l'état, la faculté, le jour vécu : `day_of`,
   `lived_day_of`), `knobs.py` (`SelfParams`), `records.py` (+ les codes d'actes), `persona.py` (le document et son
   rendu, le fait `self.persona`), `narrative.py` (le récit), `esteem.py` (estime, sociomètre, actes, section
   `self_state`), `absence.py`, `greeting.py` (le ton de ses bonjours). `__init__.py` n'est plus qu'une carte et
   réexporte ce qu'on lit ailleurs. L'ordre des imports y fixe l'ordre de ses sections dans le prompt (`kernel/prompt.py`
   : l'ordre du registre) — il est épinglé (`# isort: off`) ; la persona, que le récit importe, n'enregistre plus de
   section (sinon la sienne serait passée avant le récit). Vérifié : mêmes déclarations, mêmes sections dans le même
   ordre ; seul l'ordre de réducteurs sans type d'événement en commun a changé ; `replay --verify` identique sur les
   données de la sonde 8.
2. *Une seule table des genres* (`extraction.GENRES` : genre replié → famille, sorte de savoir ; `kind_of_genre`,
   `durable_self`) : goûts et préférences sont des `preference` qui la définissent, un avis une `opinion`, un fait de
   sa vie un `claim` qui tient, une hypothèse une `hypothesis`, une anecdote s'efface.
3. *Les mêmes mots sont la même note, quelle qu'en soit la sorte* (`Consolidate._self_twin`) : redite, une note sur
   elle est son propre témoignage redit (`memory.attested`) ; redite comme ce qui la définit, elle le devient
   (`Attested.durable`, `Attested.knowledge_kind` : `about_self` 2, l'importance d'un élément qui compte, la sorte
   dite) — jamais l'inverse. Ce qu'elle pensait avant d'en changer, redit, revient (`replaces` : celle qui l'avait
   remplacée le cède) — sa parole sur elle-même tranche.
4. *Jamais une note sur elle née d'un mensonge* (`lied` dans `_drafts`) : une note sur elle, souvenir ou croyance, ou
   un pronostic à elle, qui cite une de ses répliques marquées mensonge — ou ne cite rien dans une conversation où
   elle a menti — n'est pas gardé.
5. *Ce qu'elle a vécu à travers quelqu'un, en bref et sans personne* : la relecture écrit `en_bref` d'un constat
   (« un concert de jazz » : ni prénom, ni lieu précis, ni date ni chiffre ; vide pour la santé, la famille, l'argent,
   les amours) ; le code garde un filet (`extraction.gist_of` : au plus `GIST_MAX` caractères, aucun nom qu'elle
   connaît, aucun chiffre) et le refuse pour un moment secret ou une confidence. Il devient `Remembered.gist` (un
   contenu à sujets : l'oubli l'efface), colonne `memory_items.gist`.
6. *Deux vues de la porte* (ce que `self` lira, lots 2 et 4) : `memory_self_changes` (ses notes à elle remplacées →
   celle qu'elle tient maintenant, l'enveloppe la plus stricte des deux, quand elle a changé ; rien d'interne) et
   `memory_lived` (les souvenirs qui portent un `gist`, avec les colonnes de `memory_knowledge`).
   `vocab.lineage.without_whom(lineage, plafond)` : ce qui peut se dire sans dire de qui — rien d'interne, chaque
   source apprise au moins une fois hors secret, sous le plafond.
7. *Les codes partagés au contrat* : `OUTCOME_VALUE` et les sortes d'annonce (`FIRST_HAND`, `REPORTED`, `OFFICIAL`,
   `PREDICTION`) passent de `faculties/memory/likelihood.py` à `contracts/memory.py` (une autre faculté les lira).
8. La console mémoire dit « ce qui la définit (un goût, un avis, un fait de sa vie) : tient des mois » d'une note
   durable.

**Conséquences.** `Attested` + `durable`, `knowledge_kind` ; `Remembered` + `gist` (contenu) ; `memory.remembered`
porte deux contenus (`text`, `gist`). Projecteur `memory_items` en version 15 (colonne `gist`, promotion). Vues
nouvelles : `memory_self_changes` (`SELF_CHANGES_COLUMNS`), `memory_lived`. Phrase nouvelle :
`memory.extraction.fields.constat_en_bref`. `Consolidate._about_self` n'est plus asynchrone et ne prend plus ni
vecteurs ni réglages. Cibles d'intention (`tests/unit/test_self_said.py`, 12), chacune rendue rouge en cassant
exprès sa correction (17 mutations) : ses goûts et préférences la définissent ; une anecdote redite comme un goût le
devient, et tient des mois (jamais l'inverse) ; revenir à son ancien avis le ramenant, une seule de ses deux idées
vit ; ses changements d'avis sont les siens seulement ; aucune note sur elle ni pronostic né d'un mensonge, même non
cité ; la console dit ce qui tient ; un moment vécu garde un « en bref » sans nom, sans chiffre, borné, jamais d'un
moment secret ; ce qui se dit sans dire de qui.
