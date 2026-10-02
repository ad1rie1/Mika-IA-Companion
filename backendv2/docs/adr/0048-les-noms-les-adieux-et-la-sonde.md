# 0048 — Les noms dont on lui a parlé, les au revoir, et la sonde

**Contexte.** Trois restes de la vague du 2026-10-02 (ADR 0043 à 0047). (1) Une personne dont on lui a parlé avant
qu'elle n'arrive (« ma coloc Alice Martin ») restait une clé `name:alice martin` à jamais distincte d'Alice quand
elle se connectait (audit HUM-8) : la mémoire canonisait les adresses, jamais les noms, et l'oubli d'Alice ne
reliait que les noms exacts qu'elle porte. (2) Après « bon je file, bonne soirée », onglet resté ouvert, rien
n'empêchait une initiative ordinaire quelques minutes plus tard (« t'es encore là ? »), une fois le « sans réponse »
d'une conversation close corrigé (ADR 0046). (3) La sonde avec un vrai modèle, qui a trouvé ce que les tests ne
voyaient pas (ADR 0043), n'existait que comme script de brouillon.

**Décision.**
1. *Un nom se relie, il ne se devine pas.* Nouvel événement `identity.name_bound(name, person, by)` : un opérateur
   dit, depuis la fiche d'une personne (« C'est la personne dont on lui a parlé »), que tel nom désignait cette
   personne-là ; « Détacher un nom » le défait. Jamais d'une ressemblance de nom : deux Alice ne se confondent pas
   d'elles-mêmes (la certitude sur qui est qui reste mécanique). Le fait `identity.person` suit la liaison, la
   mémoire canonise les clés `name:` comme les adresses (chacun garde qui le lui a confié : ce que Bob a dit
   d'Alice reste de Bob, ADR 0034), et les noms reliés font partie des alias qu'emporte l'oubli. `identity` passe
   en version 3.
2. *On s'est quittées.* Veto `agency.farewell` : pendant `agency.farewell_quiet_us` (4 h) après que la personne a
   clos la conversation (`attention.AWAITING.closed_at`, ADR 0046), aucune initiative ordinaire vers elle, même si
   elle reste connectée ; ce qui est dû ou prévient passe, et une nouvelle arrivée se salue.
3. *La sonde est une commande* : `mika --data DIR sim sonde [--out DIR] [--backend NOM]` fait vivre la semaine
   d'Adrien, Chloé et Léo (`sim/sonde.py`) au modèle configuré pour répondre (Claude Code refusé : son relais
   d'outils ne vit que dans le serveur), sans rien écrire dans `DIR`, et rend `fil.txt`, `appels.jsonl`,
   `evenements.txt`, `compte.txt` et `bilan.txt`. Le simulateur accepte un modèle de plongements (`Driver.embedder`).
4. `vocab.words.fold` déplie les ligatures (« sœur » ne recoupait jamais « soeur ») ; le repli des **noms**
   (`vocab.people.fold`, qui forme les clés) ne change pas, pour que les clés du journal restent les mêmes.
5. *Ce que la sonde finale a encore montré* (125 appels ; plus aucune fuite ; « alors, cet entretien ? » au bon
   moment ; le message de 3 h lu au réveil) :
   - **ce qu'elle a dit n'est pas ce qu'on lui a appris** : une croyance ou un moment dont les seules sources sont
     ses propres lignes est écarté (elle avait inventé « il n'a rien voulu me dire » devant Chloé, et l'extraction
     en avait fait une croyance sur Adrien) ; ce qu'elle dit d'elle-même reste traité à part (`sur_elle`) ;
   - **se souvenir par le temps** : « ce que je t'ai dit lundi matin », « hier soir », « avant-hier » désignent un
     moment (`vocab.days.window_of`) ; la mémoire rend les échanges de ce moment-là avec la personne, les plus
     fournis d'abord, avant ceux qu'apporte la similarité ;
   - les jetons de l'extraction (« Chloé [P1] ») ne finissent plus dans un souvenir, un rêve ou le journal
     (`vocab.people.clean_tokens`, à l'analyse et au rendu des anciens) ;
   - « CE QUE TU TE RÉPÈTES » est une remarque pour elle seule (elle s'en excusait à voix haute) et voit aussi ses
     ouvertures d'une conversation à l'autre (« Yooo, Adrien ! » en tête de six initiatives) ;
   - pas d'écriture inclusive dans une parole lue à voix haute (« crevé·e ») ; le journal « à raconter » ne dit ni
     avec qui elle a parlé ni de quoi (il en inventait) ; le ton d'une fiche est une consigne, pas une phrase à dire.

**Conséquences.** Le journal se rejoue (événement nouveau, tranche reconstruite). Cibles :
`test_identity_security.py` (relier un nom, l'oubli qui l'emporte ; sans liaison, il échappait),
`test_speaking_up.py` (pas d'initiative juste après un au revoir, si quelques heures plus tard ; un rappel dû
passe), `test_sonde.py`, `test_vocab_words.py`, `test_memory_recall.py` (ce qu'elle a dit n'est pas appris ; le
rappel par le temps), `test_habits.py` (les ouvertures d'une conversation à l'autre).
