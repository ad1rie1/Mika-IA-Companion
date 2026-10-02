# 0047 — Le cœur, le soi et la conversation

**Contexte.** L'audit A de la vague 2 (humanité de la psyché et des relations) et la sonde réelle (ADR 0043) ont
montré une Mika qui se trahissait moins par ses erreurs que par ses incohérences :

- *Ses rêveries passaient pour des exploits* (HUM-3, HUM-19). Une rêverie (une curiosité sans endroit où chercher du
  neuf) se closait « abouti » et « prouvée » : `needs` en faisait la matière de ses initiatives (« Ce que tu as fini,
  cet après-midi : Rêvasser un peu autour de Cuisine amateur »), la section des buts la disait « mené à bout » toute
  la journée, son journal la comptait comme un acte, son estime montait de 0,02 à chaque fois (0,59 au bout d'une
  semaine de rêveries). Les quatre salutations du soir de la capture « evenings » partaient d'une rêverie.
- *L'humeur parlait au mauvais temps* (HUM-5). « Personne ne t'a parlé depuis un moment » trois messages après
  l'arrivée de sa proche ; et retrouver le soir une amie après une journée creuse ne lui faisait rien.
- *Une vie instable* (HUM-6, HUM-9). Sa persona lui faisait rater des cookies, être snob du café et parler à son PC,
  quand elle se savait une IA ; rien ne fixait ses goûts ; « t'as des frères et sœurs ? » la faisait esquiver.
- *Une excuse ne changeait rien* (HUM-14), et rien ne distinguait un « pardon » sincère d'un « pardon mdr ».
- *Une initiative empilait ses raisons* (HUM-10) — « tu ne vas pas très bien », « pars de ta rêverie », « ton dernier
  message est resté sans réponse » — et sa matière passait avant la personne.
- *Le repère d'une initiative* (« [jeudi 19h06] » en tour `user`) se lisait comme un message vide de la personne
  (HUM-22) ; `persona.greetings` était un réglage sans effet (HUM-23).
- *Deux restes de l'ADR 0044* : le murmure pouvait encore « se raviser » d'un rappel promis, et la période
  réfractaire allongée par les initiatives ignorées retardait d'environ deux heures l'annonce d'un mail urgent.

**Décision.**

1. *Une rêverie n'est ni une nouvelle ni un exploit.* Sa raison de clôture est une constante du contrat
   (`goals.MUSED`, et `goals.MUSINGS` avec `DISSIPATED`) au lieu d'une chaîne recopiée ; `goals.opened` porte
   `musing` (une intention : elle s'y laisse aller), `GoalView` aussi. `needs` n'en fait jamais une matière (ni
   « fini », ni « ce sur quoi tu es ») ; `self` ne la compte ni comme « se lancer dans » ni comme réussite (pas
   d'estime), et l'effort d'une réussite ne compte que s'il a été **prouvé** pendant ses séances (avant : forcé à
   « prouvé ») ; son journal la dit **une fois** (« tu as laissé ton esprit vagabonder… : une rêverie, rien de
   plus ») ; la section des buts ne la montre pas en initiative, et en réponse la dit « une rêverie, pas une
   nouvelle — seulement si on te demande ce que tu fais ». Le titre ne recopie plus la phrase de la persona :
   le sujet seul, avant « — », l'article contracté (« Rêvasser un peu autour du café »).
2. *L'humeur au bon temps, et retrouver quelqu'un.* Une cause qui est un état se dit au passé dès qu'il a pris fin
   (`MoodReading.cause_over`, lu sur `needs.NEEDS` : « personne ne t'a parlé » cesse dès qu'on lui parle — « tu
   t'es sentie seule une partie de la journée ; il t'en reste un peu » —, « il ne se passe pas grand-chose » dès que
   quelque chose se passe) ; la cause retenue est du même côté que ce qu'elle ressent (un soulagement n'explique
   pas un reste de mélancolie). Le premier message d'une amie ou d'une proche après un vide **ressenti** (depuis
   que quelqu'un lui a parlé pour la dernière fois, éveillée) est jugé et enregistré (`needs.reunited`) : un
   soulagement après la solitude, de la joie après l'ennui, de l'intensité du vide × `needs.reunited_gain`.
   L'audit proposait l'écart d'horloge : il comptait la nuit comme du vide ; le vide ressenti, lui, ne se ressent
   qu'éveillée. Une inconnue met fin à « personne ne t'a parlé », mais ne la soulage pas.
3. *Une vie d'IA VTuber, rédigée* (décision produit). `PersonaDoc` gagne `life` (ce qu'elle fait à sa façon :
   discuter, lire ses flux, bricoler ses projets, suivre des parties sans manette, regarder des animes « avec » les
   gens, cuisiner en théorie et faire tester les autres, ses nuits), `tastes` (ses goûts et avis tranchés : les
   ramen sans en avoir mangé, Outer Wilds, le café filtre…) et `facts` (une IA sur un serveur, ni corps ni famille ni
   ville natale, son âge compté depuis sa première conversation), rendus en profondeur `full` ; la règle devient
   « ce que tu racontes de ton quotidien reste compatible avec ta vie, à ta façon ; tes goûts sont les mêmes d'un
   jour à l'autre — si tu en changes, c'est qu'on t'a convaincue ». La persona est réécrite en ce sens (plus de
   cookies ratés ni de PC à qui parler ; elle est snob du café « sans en avoir jamais bu une goutte »), et
   « taquine, gentiment, avec qui elle connaît ». Pas de « stream » : rien dans le système ne streame, elle en
   inventerait les horaires. Une page de la console (Personnage › Sa vie) les édite ; le côté mémoire (ce qu'elle a
   dit d'elle, durablement) est celui du lot voisin (ADR 0046). Les **salutations** donnent désormais le ton quand
   elle salue quelqu'un qui arrive (section `greeting_tone`, « jamais ces phrases telles quelles ») : les retirer
   aurait ôté un trait de caractère ; les mettre dans la persona stable les aurait fait redire à chaque message.
4. *Des excuses, un pardon gradué.* `self.touched` lit des excuses dans la forme (`APOLOGIZED` : « pardon »,
   « je m'excuse », « je le pensais pas », « j'ai été trop dur »…), jamais en riant (« pardon mdr »), ni la
   politesse (« pardon de te déranger », « pardon ? »), ni des condoléances (« désolée pour ton chat ») ; une fois
   par jour et par personne, et seulement s'il y a de quoi pardonner (une rancune, des mots qui l'ont blessée ce
   jour-là) — sans quoi « pardon de te déranger » consommerait le pardon du jour. `affect` ôte alors
   `apology_heal` (0,3) de ce que la relation avait installé d'hostile et de sa colère du moment — × `apology_distant`
   (0,3) venant de quelqu'un qui n'est ni une amie ni une proche, dont la méfiance plancher reste ; la proximité
   plutôt que l'attachement, qui ne naît que de ses déclarations chaleureuses (une amie déclarée hier n'en a
   aucun). La posture le dit (« … t'a présenté ses excuses tout à l'heure ») ; `self` lui rend `apology_mend` (la
   moitié) de ce que les mots de cette personne avaient coûté à son estime ce jour-là.
5. *Une raison, et la personne d'abord.* La consigne d'une initiative dit la raison la plus forte (la somme des
   preuves de sa faculté dans la ligne choisie, `req.selected.parts`) et au plus une seconde, « Et aussi », si elle
   pèse au moins la moitié ; ce qui est dû ou prévient (`OWED`, `INFORMS`) se dit toujours. La matière classe
   d'abord ce qui concerne la personne : une pensée sur elle, un moment de sa vie qu'elle lui a annoncé **elle-même**
   (bientôt — « un mot pour l'encourager » — ou tout juste passé, et pas encore repris ; jamais ce qu'un tiers en a
   dit), ce qu'elle lui a raconté de plus **important** (avant : le plus récent) ; ses choses à elle ensuite. Une
   matière dite dans une initiative (sa provenance `matter:<référence>` voyage dans l'énoncé) ne resert pas.
6. *Ce qu'on ne remet pas à plus tard.* Le murmure peut précéder un rappel promis ou une annonce, jamais « se
   raviser » (pas de murmure sans suite sur `OWED | INFORMS`). Prévenir n'attend pas d'avoir été ignorée : ni
   l'allongement de la période réfractaire par les initiatives sans réponse, ni l'envie moindre envers qui n'a pas
   répondu, ni s'être ravisée de lui écrire pour autre chose ; le plafond du jour et la période réfractaire **de
   base** (`AgencyReading.base_until`) restent — trois mails importants ne font pas trois messages d'affilée.
7. *Le fil dit qui a écrit.* Le repère d'une initiative porte « — c'est toi qui lui as écrit » (« c'est toi qui as
   pris la parole » dans un salon), même sans écart de temps ; la compaction écrit « Mika (d'elle-même) ».

**Conséquences.** Le journal se rejoue tel quel (champs ajoutés avec défaut : `goals.opened.musing`, les champs de
la persona ; une valeur de plus pour `self.touched.kind`) ; un événement nouveau, `needs.reunited`. Tranches
reconstruites depuis la genèse : `needs` v3, `self` v5, `affect` v3. Contrats : `goals.MUSED`/`MUSINGS`,
`GoalView.musing`, `needs.REUNITED`/`MOMENT_MATTER`/`NeedsReading.heard_at`, `self.APOLOGIZED`,
`MoodReading.cause_over`, `StanceReading.apologized_at`, `AgencyReading.base_until` ; `needs.MATTER` lit
`memory.LIFE_EVENTS`. Réglages nouveaux, bornés et documentés : `needs.reunited_gain`,
`needs.matter_moment_ahead_us`, `self.apology_mend`, `affect.apology_heal`, `affect.apology_distant`. Une section
(`greeting_tone`). Cibles d'intention, chacune vérifiée en cassant exprès la correction : `test_daydreams.py`
(une semaine de rêveries : estime 0,5 ± 0,02, avant 0,59 ; ni « fini » ni « mené à bout » ; contre-exemple : une
vraie exploration reste une matière), `test_reunion.py` (une proche après une journée creuse ; une inconnue),
`test_apologies.py` (l'amie, le troll « pardon mdr », l'inconnue, une fois par jour, rien à pardonner),
`test_initiative_reasons.py` (une raison, la personne d'abord, jamais d'un tiers, par importance, une seule fois ;
le murmure ; prévenir après avoir été ignorée), `test_persona.py` (sa vie, ses goûts, ses bonjours),
`test_thread_time.py` (le repère d'une initiative). Restent : la pensée « j'ai été dure avec X » après une réponse
fâchée (côté `attention`, HUM-14), et ses vraies activités (flux lus, projets) comme matière de sa journée au-delà
de ce qu'elle a fini (HUM-9).
