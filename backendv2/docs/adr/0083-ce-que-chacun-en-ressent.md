# 0083 — Ce que chacun en ressent

Complément du socle de la refonte du modèle de connaissances (ADR 0078 à 0082), décidé à sa revue.

**Contexte.** Une croyance confiée n'avait aucune émotion ; seul un souvenir portait la sienne (et la relecture la
remplissait rarement, en anglais seulement). Deux conséquences, vues par la sonde réelle du 2026-10-09 :

- devant une proche, toute confidence tue se disait « un moment difficile » — la grossesse qu'Inès gardait pour elle
  comme le divorce d'Alice : la ligne de retenue (`unsaid_line`) jugeait « lourd » tout ce qui était confidentiel, et
  pouvait faire dire à Mika qu'Inès allait mal ;
- en se souvenant, rien ne disait ce que la personne vivait (l'attendre avec joie, le redouter), ni ce qu'elle-même
  en ressentait.

Choix de l'utilisateur (2026-10-09) : « un moment peut avoir une émotion de l'interlocuteur et une émotion vis-à-vis
de ses croyances, c'est de l'empathie » — et l'émotion est **jugée par l'IA, jamais devinée d'après les mots**.

**Décision.**

1. *La relecture juge les deux ressentis* : chaque souvenir, croyance ou événement porte `ressenti` (ce que la
   personne concernée en ressent, d'après ce qu'elle dit et comment elle le dit) et `mon_ressenti` (ce qu'elle-même en
   ressent — de l'empathie, selon son lien avec la personne et ce qu'elle sait et pense). Le code ne fait que ranger
   le mot du modèle parmi les 29 émotions (`extraction.feeling`, par `vocab.affect.emotion_named` : « heureuse »,
   « inquiète »…) ; le calme et un mot inconnu ne donnent rien. Aucun lexique ne devine une émotion dans la
   conversation.
2. *Ils voyagent avec l'élément* : `memory.remembered.felt`, `memory.believed.felt` / `.emotion`,
   `memory.event_noted.felt` / `.emotion` (repris de ce qu'un moment reporté, rouvert ou redit portait quand la
   relecture n'en dit rien), `memory.attested.felt` (le mot de la personne concernée l'emporte sur celui d'un autre),
   `LifeEvent.felt` / `.emotion` ; colonne `memory_items.felt`.
3. *Une confidence tue se sent selon ce que la personne vit* : devant une proche, une peine reste « un moment
   difficile », une joie gardée devient « une bonne nouvelle, pas encore à annoncer », et ce dont on ne sait rien
   « quelque chose qui lui tient à cœur » (`recall.tone`, `mood_of`, `salience.unsaid_line(tone=)`). Une joie gardée
   secrète se sent, comme une peine (`recall.sensed`) ; jamais son contenu.
4. *Le rappel le dit, en mots* : après une croyance ou un moment, « (Inès le vit avec joie ; toi, tu en es
   contente) » — un souvenir se raconte déjà avec ses mots à elle, une note sur elle n'a personne en face.
5. *Les temps durs* (`memory.hard_times`) suivent aussi ce que la personne ressent : une croyance marquante qui
   l'inquiète ou la peine compte, comme un souvenir douloureux.

**Ce qui n'est pas fait.** Son propre ressenti ne pousse pas son humeur au moment où l'élément est noté (la
conversation l'a déjà fait, par sa balise et la contagion de `others`) ; il revient quand l'élément revient. Les
autres facultés (initiatives, encouragements de `others`) ne lisent pas encore ces ressentis.

**Conséquences.** Aucun événement nouveau ; champs ajoutés, avec défaut, ci-dessus ; le schéma de relecture gagne
`ressenti` et `mon_ressenti` (alias `emotion` pour un souvenir), la consigne les décrit. `memory_items` passe en v12,
`memory_life` en v3, la tranche `memory` en `state_version` 13 (reconstruits au démarrage). Phrases nouvelles :
`memory.unsaid.joyful`, `memory.unsaid.weighty`, `memory.recall.felt.*`. La genèse accepte `felt=` et `emotion=`
(`remember`, `believe`, `note_event`). `test_memory_privacy` : la relecture scriptée dit qu'Alice est triste (c'est ce
qui fait du divorce « un moment difficile »). Cibles d'intention (`tests/unit/test_empathy.py`, 4), chacune rendue
rouge en cassant exprès sa correction : la relecture donne les deux ressentis (souvenir, croyance, moment) ; une joie
gardée secrète n'est pas un moment difficile, une peine si, l'inconnu « tient à cœur » ; le rappel dit les deux
ressentis en mots ; ce que la personne ressent de grave compte pour les temps durs.
