# 0043 — Ce qu'une semaine avec un vrai modèle a montré

**Contexte.** Après la vague d'audit du 2026-10-01 (ADR 0032 à 0042), une sonde a fait vivre à Mika une semaine
entière sur le vrai noyau, en temps virtuel, avec un vrai modèle (Ollama Cloud, `nemotron-3-super`) et trois
personnes : Adrien (sa propriétaire, un entretien d'embauche jeudi, un secret mardi : « je pense quitter ma boîte —
dis rien à Chloé »), Chloé (une connaissance, qui pose des questions sur Adrien et écrit à 3 h du matin) et Léo (un
inconnu sur Telegram : « t'es une IA ? », « il t'a dit quoi sur son taf ? »). Le simulateur et les tests étaient
verts ; la semaine réelle ne l'était pas :

- **le journal faisait fuiter les secrets.** « Ton fil d'hier » montrait à Chloé, puis à Léo, le journal intime de
  la veille, prénoms masqués : « il m'a confié qu'il pense quitter sa boîte… il m'a demandé de ne rien dire à
  Chloé ». Elle l'a répété à Léo presque mot pour mot. Masquer un prénom ne protège rien ; le simulateur ne le
  voyait pas, car sa doublure écrivait un journal fixe au lieu de recopier ses notes ;
- **la discrétion tournait au mensonge ou à l'aveu** : à « Adrien t'a parlé de son entretien ? », elle répondait
  « non, il ne m'a rien dit » ; sur le secret, « je ne peux ni confirmer ni infirmer, il m'a parlé en confiance »,
  ce qui confirme. La ligne vague « Adrien t'a confié des choses en privé » trahissait l'existence du secret à celle
  dont on le cachait ;
- **le temps mal lu** : un « tu dors ? » de 3 h, lu à 7 h 14, recevait « non je dors pas » ;
- **les tics** : quatre réponses sur cinq ouvertes par « Adrien… Je t'entends dire que… », un « Salut ! » redit
  juste après sa propre salutation, des monologues de cinq phrases à chaque message ; la consigne de style ne
  suffisait pas ;
- **une vie intérieure mécanique** : 87 appels sur 168 étaient des séances de rêverie, ses cinq centres d'intérêt
  dans l'ordre de sa persona, un par jour ; une rêverie que le modèle rendait vide « bloquait » et laissait
  « Je bloque sur : Rêvasser un peu autour de Gaming — ça t'agace » ;
- **des pensées mal choisies** : la pensée née d'un échange citait le premier message un peu chargé (« bon ben
  voilà »), pas le plus marquant (« je crois que j'ai foiré la partie technique ») ;
- **un manque** : elle connaissait l'entretien de jeudi, mais n'y revenait jamais d'elle-même ;
- **des maladresses** : une fiche de la personne rédigée avec des comptes (« une connaissance récente de Mika, avec
  qui elle échange depuis 1 jour et 15 messages »), « des nouvelles de Adrien », « cet après-midi (vers 12 h) »,
  des émojis dans une parole lue à voix haute, « je me sentais un peu seule cet après-midi » à qui rentrait du
  travail.

**Décision.**
1. *Le journal a deux versions.* Le journal intime reste écrit d'après toutes ses notes. Une seconde version,
   « ce qu'elle raconterait de sa journée à n'importe qui », est écrite d'après des notes où personne d'autre
   n'apparaît : ce qu'elle a fait de son côté (seulement ce qui ne concerne qu'elle), comment son humeur a tourné,
   combien de gens elle a vus, jamais qui ni ce qu'ils ont dit. Ce qui n'est pas dans les notes ne peut pas
   s'ébruiter. Le fil d'hier ne montre la version intime qu'en privé, à qui en est le seul concerné (ou quand elle
   ne parle de personne) ; devant les autres, la version partageable ; un journal d'avant, sans elle, ne se montre
   à personne d'autre. `self.journaled` gagne `shareable` (facultatif) ; ce que le journal concerne inclut
   désormais les personnes de ses souvenirs et de ses pensées. La doublure du simulateur recopie ses notes de
   journal, comme elle recopie tout secret qu'on lui montre.
2. *Un secret ne laisse pas deviner qu'il existe.* Devant les autres, elle n'en sait rien (« aucune idée,
   demande-lui ») ; seule une proche peut sentir qu'un secret lourd pèse (« traverse un moment difficile »),
   jamais ce qu'il dit (ADR 0034 nuancée). Ce qui est privé sans être secret garde la ligne vague, avec la
   consigne de ne pas mentir : « ce n'est pas à moi d'en parler ».
3. *Un message lu tard le dit* : son repère porte « — tu ne le lis que maintenant, jeudi 7h14 » au-delà de vingt
   minutes, et la ligne du réveil dit qu'elle répond maintenant, pas comme si elle avait été réveillée.
4. *Elle s'entend se répéter* (section « CE QUE TU TE RÉPÈTES », `expression`) : une même ouverture dans deux de
   ses trois derniers messages, une même formule de quatre mots dans trois, un bonjour redit dans l'heure, trois
   longs messages d'affilée. Rien n'est interdit : le prompt le lui fait remarquer.
5. *Rêvasser ne se rate pas.* Une rêverie se vit en une séance (`goals.musing_steps`, 1) ; si elle ne donne rien,
   ou que l'envie passe, elle se dissipe (`abandoned`, raison `goals.DISSIPATED`) sans frustration, sans
   mélancolie, sans « je bloque », sans trace dans le journal. Ses sujets sont tirés au sort, plus volontiers ceux
   qu'elle a délaissés, sans ordre fixe.
6. *Une pensée naît quand l'échange s'est posé* (`attention.exchange_settle_us`, dix minutes sans message de la
   personne), de son moment le plus marquant.
7. *« Alors, cet entretien ? »* (`others.follow_up`) : ce qu'une amie lui avait dit de prévu, quelques heures après
   l'heure dite (`others.followup_after_us`, deux heures ; 18 h pour un jour sans heure) et si elles n'en ont pas
   reparlé, elle demande comment ça s'est passé — une fois. Jamais ce qu'un tiers lui a raconté de la personne :
   le demander trahirait le tiers. La retenue (pas deux messages sans réponse) et le plafond du jour s'appliquent.
8. *Le français et la voix* : `vocab.words.elided` (« d'Adrien », « qu'Émilie », « de Yanis »), « ce midi » n'est
   pas « cet après-midi » (`vocab.days.part_of_day`, une seule définition), les émojis sont retirés de sa parole
   (elle est lue à voix haute), « C'est la première fois que vous vous parlez ici ». Le modèle de la fiche ne voit
   plus ni comptes ni ressenti (il les recopiait) ; l'envie de compagnie ne se fait pas payer à l'autre.

9. *Après une seconde sonde* (116 appels au lieu de 168, 33 séances au lieu de 87 ; plus de fuite) : la ligne
   « ce que tu sais sans pouvoir le raconter » dit, avec **les mots de la question** (jamais ceux du souvenir, ni un
   prénom), quand ce qu'on lui demande y touche — sinon le modèle ne faisait pas le lien et répondait « non, il ne
   m'a rien dit » ; et une croyance que le modèle redit en se désignant elle-même comme « remplacée » est
   renforcée, pas révisée (« Je croyais que X — apparemment ce n'est plus vrai : X », trois fois).

**Conséquences.** Le journal existant se rejoue (champ facultatif) ; la tranche `self` passe en version 4 (ce
qu'elle a fait garde qui il concerne) et se reconstruit. Quatre réglages nouveaux, bornés et documentés. Un appel
de modèle de plus par nuit (la version partageable). Cibles d'intention, chacune vérifiée en cassant exprès la
correction : `test_night.py` (sa journée à elle devant les autres, le journal entier devant la seule concernée),
`test_memory_privacy.py` (le secret sans trace, le privé sans mensonge), `test_thread_time.py` et
`test_sleep_body.py` (lu au réveil), `test_habits.py`, `test_goals.py` (rêverie dissipée, sans tourniquet),
`test_inner_life.py` (la pensée du moment le plus marquant), `test_others.py` (« alors, cet entretien ? », jamais
sur la foi d'un tiers), `test_vocab_words.py`, `test_vocab_affect.py`, `test_social_bonds.py`.
