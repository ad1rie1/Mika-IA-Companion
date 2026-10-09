# 0076 — Ce qu'elle déplace, ce qu'elle a vécu, ce qu'elle tait, ses mensonges

**Contexte.** Une sonde réelle (Haiku par la CLI Claude Code, sept scènes : faits, opinions, goûts, un moment à venir,
un secret, une naissance, un chat malade) a montré quatre comportements peu réalistes, au-delà des noms (ADR 0075) :

- « j'ai un entretien jeudi », puis « finalement il est reporté à lundi » : deux moments actifs. L'ancien, noté avant
  que le secret soit dit, n'était pas secret ; le nouveau l'était. L'ancien trahissait donc la recherche d'emploi.
  L'ADR 0074 l'avait prévu : sans les mêmes mots, une autre date ne remplace pas.
- Bob demande « Alice compte partir ? » : « Je ne vais pas te parler de ce qu'Alice m'a confié. » La consigne
  (« dis simplement que ce n'est pas à toi d'en parler ») lui faisait avouer qu'il y avait un secret. C'est une phrase
  de robot : une amie discrète aurait donné son avis.
- Un souvenir écrit à la place de Carol : « J'ai eu une petite fille, Jeanne : je suis épuisée mais tellement
  heureuse. » Reformulé, il échappait à la garde contre les répliques recopiées (`copied`, 80 % des mots dans
  l'ordre).
- Le premier tour après un redémarrage passait sans aucun rappel : le modèle de plongements se chargeait à la
  première recherche, et le rappel (2,5 s au plus) partait sans mémoire.

**Décision.**

1. *Un moment déplacé remplace celui qu'il déplace.*
   - La relecture voit les moments à venir des personnes de la conversation, avec leur numéro
     (`Consolidate._moments`, « Moments à venir déjà notés »), sous les mêmes règles que les situations : jamais ce
     qu'un autre a confié au-delà de l'anodin, et dans un salon l'anodin seulement.
   - Un événement peut désigner celui qu'il remplace (`XEvenement.remplace`). Seul un numéro montré compte. Le
     nouveau moment hérite du secret, de la sensibilité et du poids de l'ancien, et `replaces` retire l'ancien.
   - Sans désignation, la règle de l'ADR 0074 reste : à une autre date, pas de remplacement sans les mêmes mots.
2. *Ce qu'elle tait, elle le tait avec jugement* (`memory.recall.unsaid_advice`, `memory.unsaid`).
   - Ce qu'elle évite : tout refus de répondre, sous quelque forme que ce soit (« je ne peux pas te le dire », « je
     préfère ne pas répondre à sa place », « ce n'est pas à moi d'en parler ») : un refus avoue qu'il y a un secret.
     La sonde a montré que Haiku remplace une formule interdite par sa voisine : la consigne nomme le geste, pas
     seulement les mots.
   - Ce qu'elle préfère : donner son avis à partir de ce qu'on lui dit ici ou de ce qui se voit, retourner la
     question, ou dire que c'est à la personne d'en parler — sans s'appuyer sur ce qu'on lui a confié, ni laisser
     deviner si elle sait.
   - Si rien de tout ça ne passe, elle peut botter en touche par un mensonge (« aucune idée »). Une première version
     le lui interdisait ; l'utilisateur l'a voulu humain : elle a le droit de mentir, mais ça lui pèse et elle s'en
     souvient (point 6).
   - Les lignes vagues disent qu'elle garde ces choses pour elle, plus qu'elle « n'a pas à en parler ».
   - Les règles de divulgation ne changent pas : ce qui ne peut pas se dire ne lui est toujours pas montré.
3. *Un souvenir à la première personne est toujours le sien.*
   - La consigne d'extraction le dit, avec un exemple : ce qui arrive à quelqu'un d'autre se raconte comme ce
     qu'elle en a appris.
   - Un souvenir à la première personne qui reprend au moins 60 % des mots d'une réplique d'une autre personne
     (`extraction.voice_of`) parle à sa place. Il devient ce que cette personne lui a dit (« Carol m'a dit : « … » »),
     comme une réplique recopiée.
4. *La CLI reçoit l'effort de réflexion du fournisseur* (`BackendSpec.effort`, `--effort` ; vide : le défaut de la
   CLI), réglable dans la console et par `mika llm backend --effort`.
5. *Le modèle de plongements se charge au démarrage* (`SentenceEmbedder.warm`), en tâche de fond pendant que le noyau
   relit sa vie. Une recherche arrivée avant la fin du chargement l'attend dans le même fil, sans le refaire. Un
   échec ne bloque rien : le premier rappel le charge, comme avant.

6. *Elle peut mentir, et ça lui pèse.*
   - La consigne de style le dit pour toute conversation : mentir lui arrive (botter en touche, garder une confidence,
     ne pas blesser), jamais sans que ça compte. Quand elle affirme sciemment quelque chose de faux, elle écrit
     `[MENSONGE: la phrase fausse]` avant sa balise d'émotion.
   - La marque ne part jamais, même coupée en fin de réponse (`expression.LIE_MARK`) : ce qu'elle y écrit pourrait dire
     ce qu'elle cache. L'énoncé n'en garde que la place du passage faux dans le texte livré
     (`LIE_ANNOTATION`, « début:fin »), jamais un texte : une annotation n'est pas un `Content`, l'oubli ne
     l'atteindrait pas.
   - Sa conscience : une pensée gênée, « J'ai menti à Bob » (`attention`, origine `LIE`, `lie_intensity` 0,45), une
     par personne à la fois, qui teinte son humeur à sa naissance et quand elle y repense. Elle se ressent, elle ne
     pousse pas à lui réécrire (`FELT_ONLY`). Elle ne se montre que devant Bob, en privé : devant une autre,
     « j'ai menti à Bob » laisserait deviner ce qu'il couvrait. Repensée la nuit, elle reste secrète (`night._disclosure`).
   - Sa mémoire : un souvenir étiqueté mensonge (`memory.lies`, `Remembered.lie`, origine `LIED`) : « Bob m'a
     demandé : « … » — je lui ai menti en répondant : « … » ». Deux choses que Bob a entendues, rien de ce qu'elle
     cachait. Secret, à propos de Bob seul, confié par personne : il ne ressort que devant Bob, en privé — pour ne pas
     se contredire, ou avouer si elle le juge bon. Il n'alimente ni une ligne vague ailleurs (« Bob t'a confié… »
     serait faux), ni « ce qui se passe dans sa vie ». La console le badge « mensonge ».
   - La relecture voit ses répliques marquées (« (un mensonge) ») et n'en tire ni croyance ni note sur elle.
   - Un secret qui ne lui est pas montré du tout ne fait pas de mensonge conscient : « aucune idée » y est dit de
     bonne foi, du point de vue de ce qu'elle a en tête. Seuls les mensonges qu'elle marque comptent.
   - La sonde réelle (Haiku, effort moyen) : à « Alice va quitter la boîte, oui ou non ? », elle a répondu « Je ne
     sais pas ce qu'elle a décidé pour la suite », marqué. Plus tard, Bob : « t'es sûre ? » ; la gêne et le souvenir
     dans la tête, elle a avoué à demi (« Je t'ai répondu à côté… je ne veux pas te laisser croire que je n'en sais
     rien »). Mais devant Inès, « je n'ai rien de récent sur elle » est parti sans marque, alors que la consigne cite
     cette phrase même : la marque dépend du modèle. Un filet déterministe (un démenti de savoir dans une réponse dont
     le rappel taisait quelque chose) n'est pas fait.
7. *Un report repousse.* La consigne d'extraction le dit (« reporté à lundi », pour un jeudi : le lundi d'après) :
   Haiku avait daté le report au lundi d'avant ; avec la consigne, une audition du jeudi 15 « reportée à lundi » est
   notée au lundi 19, l'ancienne retirée (sonde réelle).

**Ce qui n'est pas fait.** Devant une proche, un secret lourd se résume toujours en « X t'a confié traverser un moment
difficile » (`memory.unsaid.heavy`). « Lourd » veut dire une émotion négative, ou une confidence. Une recherche
d'emploi gardée secrète devient donc « un moment difficile », ce qui la déforme : cette ligne n'a pas été revue ici.

**Conséquences.**

- `tests/unit/test_moments_voice_discretion.py` (8 tests) : les moments montrés, le report qui remplace et hérite du
  secret, un numéro non montré qui ne remplace rien, le souvenir à la place de Carol, la consigne de discrétion,
  l'effort, le préchargement.
- `test_memory_privacy` : la consigne parle du mensonge avec d'autres mots (« mensonge » au lieu de « ne mens pas ») ;
  elle le permet désormais, marqué.
- `tests/unit/test_lies.py` (6 tests) : la marque qui ne part jamais, la gêne ressentie, le souvenir étiqueté, devant
  qui il ressort (et la ligne vague qu'il ne doit pas produire), la nuit qui le garde secret, la relecture.
- Les moments déjà doublés au journal le restent : seuls les reports à venir sont remplacés.
