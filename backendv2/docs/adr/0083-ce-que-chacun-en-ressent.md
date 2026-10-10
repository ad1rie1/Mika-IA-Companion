# 0083 — Ce que chacun en ressent

Complément du socle de la refonte du modèle de connaissances (ADR 0078 à 0082), décidé à sa revue.

**Contexte.** Une croyance confiée n'avait aucune émotion ; seul un souvenir portait la sienne, une seule (et la
relecture la remplissait rarement, en anglais seulement). Conséquences, vues par la sonde réelle du 2026-10-09 :

- devant une proche, toute confidence tue se disait « un moment difficile » — la grossesse qu'Inès gardait pour elle
  comme le divorce d'Alice : la ligne de retenue (`unsaid_line`) jugeait « lourd » tout ce qui était confidentiel, et
  pouvait faire dire à Mika qu'Inès allait mal ;
- en se souvenant, rien ne disait ce que la personne vivait, ni ce qu'elle-même en ressentait ;
- rien ne permettait de retrouver ce qui l'énerve, ce qui la touche.

Choix de l'utilisateur (2026-10-09) : « un moment peut avoir une émotion de l'interlocuteur et une émotion vis-à-vis
de ses croyances, c'est de l'empathie » ; l'émotion est **jugée par l'IA, jamais devinée d'après les mots** ; une
émotion a **plusieurs facettes**, chacune de 0 à 1 (« colère 0,8, dégoût 0,4 ») ; et la base **relie chaque élément à
ses émotions**, pour qu'on retrouve « ce qui t'énerve ».

**Décision.**

1. *La relecture juge les deux ressentis, en facettes* : chaque souvenir, croyance ou événement porte `ressenti` (ce
   que la personne concernée en ressent, d'après ce qu'elle dit et comment elle le dit) et `mon_ressenti` (ce
   qu'elle-même en ressent — de l'empathie, selon son lien avec la personne et ce qu'elle sait et pense), chacun des
   émotions avec leur intensité de 0 à 1. Le code ne fait que ranger ce que le modèle écrit parmi les 29 émotions
   (`vocab.affect.facets` : un objet, une liste, « colère:0.8, dégoût:0.4 », un mot seul à 0,7) — la plus forte
   d'abord, trois au plus, le calme et un mot inconnu laissés (« compréhension » n'est pas une des 29). Aucun lexique
   ne devine une émotion dans la conversation, et une forme illisible ne fait jamais perdre l'élément.
2. *Ils voyagent avec l'élément* (`contracts.memory.Feelings`, un ressenti d'un seul mot se lit comme une facette) :
   `memory.remembered.felt` / `.empathy` (`.emotion` reste sa facette la plus forte), `memory.believed.felt` /
   `.empathy`, `memory.event_noted.felt` / `.empathy` (repris de ce qu'un moment reporté, rouvert ou redit portait
   quand la relecture n'en dit rien), `memory.attested.felt` (le mot de la personne concernée l'emporte sur celui
   d'un autre), `LifeEvent.felt` / `.empathy` ; colonnes `memory_items.felt`, `.empathy` (JSON).
3. *Chaque élément est relié à ses émotions* : table `memory_feelings` (élément, de qui — `theirs` la personne
   concernée, `hers` elle —, émotion, intensité), indexée par émotion, effacée avec l'élément ; vue de la porte
   `memory_knowledge_feelings`. `memory_search` gagne `ressenti` et `de_qui` : c'est le modèle qui choisit de chercher
   par ressenti (« qu'est-ce qui t'énerve ? » : colère, agacement), le plus fort d'abord, la question départageant,
   le verdict de chaque élément comme toujours.
4. *Une confidence tue se sent selon ce que la personne vit* : devant une proche, une peine reste « un moment
   difficile », une joie gardée devient « une bonne nouvelle, pas encore à annoncer », et ce dont on ne sait rien
   « quelque chose qui lui tient à cœur » (`recall.tone` — la valence des facettes, pondérée par leur intensité —,
   `mood_of`, `salience.unsaid_line(tone=)`). Une joie gardée secrète se sent, comme une peine (`recall.sensed`) ;
   jamais son contenu.
5. *Le rappel le dit, en mots, jamais un nombre* : « (Alice le vit avec colère et un peu de dégoût ; toi, tu en es
   triste, avec un peu d'inquiétude) » — une facette sous 0,5 se dit « un peu » ; un souvenir se raconte déjà avec
   ses mots à elle, une note sur elle n'a personne en face ; la recherche le dit pour tout ce qu'elle rend.
6. *Les temps durs* (`memory.hard_times`) suivent aussi ce que la personne ressent, toutes facettes pesées : une
   croyance marquante qui l'inquiète compte ; un peu d'inquiétude dans beaucoup de soulagement, non.

**Ce qui n'est pas fait.** Son propre ressenti ne pousse pas son humeur au moment où l'élément est noté (la
conversation l'a déjà fait, par sa balise et la contagion de `others`) ; il revient quand l'élément revient. Les
autres facultés (initiatives, encouragements de `others`) ne lisent pas encore ces ressentis. Le rappel spontané ne
cherche pas par émotion de lui-même : c'est l'outil, à la demande du modèle.

**Conséquences.** Aucun événement nouveau ; champs ajoutés, avec défaut, ci-dessus ; le schéma de relecture gagne
`ressenti` et `mon_ressenti` (alias `emotion` pour un souvenir), la consigne les décrit ; `memory_search` gagne
`ressenti` et `de_qui`. `memory_items` passe en v12 (table `memory_feelings`, vue `memory_knowledge_feelings`),
`memory_life` en v3, la tranche `memory` en `state_version` 13 (reconstruits au démarrage). Phrases nouvelles :
`memory.unsaid.joyful`, `memory.unsaid.weighty`, `memory.recall.felt.*`, `memory.tools.search.ressenti`, `.de_qui`.
La genèse accepte `felt=` et `empathy=` (`remember`, `believe`, `note_event`). `test_memory_privacy` : la relecture
scriptée dit qu'Alice est triste (c'est ce qui fait du divorce « un moment difficile »). Cibles d'intention
(`tests/unit/test_empathy.py`, 5), chacune rendue rouge en cassant exprès sa correction : la relecture donne les deux
ressentis en facettes (souvenir, croyance, moment) ; une joie gardée secrète n'est pas un moment difficile, une peine
si, l'inconnu « tient à cœur » ; le rappel dit les facettes en mots ; ce que la personne ressent de grave compte pour
les temps durs, toutes facettes pesées ; « ce qui t'énerve » se retrouve par l'émotion, les siennes ou celles de la
personne.
