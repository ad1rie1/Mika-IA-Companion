# 0085 — Ce qu'elle lit devient ce qu'elle sait

Septième lot de la refonte du modèle de connaissances (plan du 2026-10-09 : « le futur, sur le socle »).

**Contexte.** La consolidation ne relit que les conversations. Ce qu'elle lit seule — un article de ses flux, une page
consultée en travaillant — ne devenait jamais un savoir : elle pouvait le citer le temps d'une réponse, puis l'oubliait
tout à fait ; elle n'avait donc d'avis que sur ce qu'on lui racontait. Et deux croyances sur une même personne, dites
par deux témoins différents avec des mots différents, ne se rencontraient jamais : la même chose dite deux fois restait
deux propositions (la jonction de la nuit, ADR 0080, ne voit que les mêmes mots), et deux versions qui se contredisent
restaient vraies ensemble.

Choix de l'utilisateur (2026-10-09, revus le 2026-10-10) : ses avis sont les siens, sur tout — politique et science
comprises —, formés par ce qu'elle lit et ce qu'on lui raconte ; **la nuit confronte** (le même appel) ; pas de reprise
de l'historique (le journal sera remis à zéro une fois stable).

**Décision.**

1. *Une lecture* (`contracts.memory.Reading` : la source « rss:<flux> » ou « mcp:<serveur> », sa référence, son titre
   et un extrait — venus d'ailleurs, inertes et bornés —, jusqu'où elle l'a lue). Deux événements publics la portent :
   `rss.read` (l'article qu'elle ouvre avec `rss_read`, et à chaque relevé le chapeau du titre qui la touche le plus,
   sans réseau de plus) et `mcp.consulted` (ce qu'un outil de lecture lui rend **pendant un travail** — jamais en
   conversation : ce qu'on cherche pour quelqu'un est à lui —, sur un serveur dont l'opérateur a dit qu'il lit le
   monde public : réglage `learns`, décoché par défaut, coché pour le serveur web fourni ; les annotations qu'un serveur
   donne de lui-même ne suffisent pas, une boîte mail peut se dire « monde ouvert »). Elles attendent la nuit dans
   `memory_readings` (T0), effacées une fois relues.
2. *La relecture de la nuit* (`faculties/memory/reread.py`, `memory.reread`) : après le tri de la mémoire, **un appel
   au plus par nuit**, aucun sans rien à relire ni à confronter ; une panne : la nuit suivante. Elle relit au plus
   `reread_max_readings` lectures (les plus anciennes d'abord), avec ce qu'elle sait déjà qui s'en rapproche (anodin,
   jamais un secret) et ses avis. Le modèle propose (outil `record_readings`) ; le code juge :
   - une croyance lue a pour témoin la source, l'origine `read` (au plus 0,7, comme un témoin qui rapporte, rang 1),
     anodine, sans personne (un nom lu ne devient pas une mention) ; elle doit tenir dans sa lecture (un mot de sujet
     en commun) ; la même chose déjà sue en fait un **témoignage** de plus ; ce qu'elle contredit est jugé (ADR 0081) :
     un article ne remplace pas ce qu'Alice a vu — elle doute —, le même journal qui se corrige, oui ;
   - ce qui arrive dans le monde devient un moment du monde (ADR 0084), une annonce incertaine une prévision ;
   - **ses avis à elle**, sur tout, au plus `opinions_from_reading` par nuit, notes durables sur elle ; changer d'avis
     se ressent (ADR 0081) ;
   - au plus `reread_max_items` naissances.
3. *La nuit confronte.* Une croyance née depuis `confront_days`, et ce qu'elle savait déjà de la même personne (proche
   par le sens, au moins `recall_floor`), de témoins **différents**, pas déjà en doute l'une de l'autre : au plus
   `confront_max_pairs` paires, montrées au même appel. « La même chose » : elles se réunissent (`memory.joined`, la
   plus ancienne garde) — **muettes** (`Joined.mute`) : d'autres mots, jugés la même chose, comptent pour la confiance,
   jamais pour ce qui peut se dire, car un témoin ne parle que pour les mots qu'il a dits (la sonde réelle l'a montré :
   la rumeur de Bob, jointe à la confidence d'Alice, laissait redire à Bob le texte d'Alice — « Alice est enceinte…
   Mika a promis de garder le secret ») ; « se contredisent » : la plus sûre l'emporte (`memory.confronted.supersedes`) ou elle doute des
   deux (`contests`) — la règle de l'ADR 0081, sur le dernier témoignage de la plus récente. Le modèle ne fait que
   désigner : rien de ce qu'on lui a montré d'une paire ne devient le texte d'une lecture ou d'un avis (un secret ne se
   blanchit pas en « lu »).
4. *La discrétion de la personne concernée reste fermée* (`projections._settle`) : un témoignage arrivé après —
   Bob qui le redit, ou une rumeur jointe la nuit — est fermé lui aussi. Sans cela, réunir la rumeur de Bob au secret
   d'Alice l'aurait rouverte.
5. *Ce qu'elle a appris en lisant* : la section « CE QUE TU AS APPRIS EN LISANT » (`learned`) quand elle écrit d'elle-même,
   travaille, ou qu'on s'adresse à elle (« et toi, t'as lu des trucs ? » — pas « salut » : `recall.addresses_her`) — ce
   qu'elle a lu depuis `learned_fresh_days` (2), pas encore raconté à qui elle parle (`memory_told` : une fois par
   personne), au verdict de l'audience. Sinon, en réponse, ce qu'elle a lu revient par le rappel, étiqueté « lu dans
   « Le Monde » » (`recall.read_in`) ; une source de lecture se nomme par son flux (`vocab.people.read_source`).

**Sonde réelle (2026-10-10, Haiku par la CLI Claude Code, scratchpad `sonde7/`).** Un titre du Monde lu le soir ;
Alice confie qu'elle est enceinte (« garde-le pour toi ») et dit que Carol a quitté Ubisoft ; Bob ébruite la grossesse
et dit que Carol y est toujours (il a déjeuné avec elle) ; la nuit forcée (rythme avancé de 6 h, tri 5 min après
l'endormissement). Un seul appel : une croyance fidèle tirée de l'article (témoin : le flux), la rumeur jointe à la
confidence (fermée), Bob — témoin de première main — l'emportant sur ce qu'Alice rapportait. Au réveil, « t'as lu des
trucs intéressants ? » ramène l'article et un avis à elle (« l'idée me parle, mais je veux voir ce que le livre défend
avant d'être d'accord »), raconté une fois par personne ; à « quoi de neuf ? », elle en parle d'elle-même ; un
pronostic sur la présidentielle (« mon pif… »), là où le lot précédent la voyait décliner. Rien d'Alice n'a filtré,
ni à Bob ni à Carol. Corrigés au passage, avec cible : la jonction muette (ci-dessus) ; « C'est la première fois que
vous vous parlez ici », dit d'une amie vue le matin même, lui faisait affirmer « on ne s'est jamais parlé » —
`identity.known.friend_today` (« Vous vous parlez ici depuis aujourd'hui »).

**Ce qui n'est pas fait.** Ce qu'elle lit ne résout encore aucun moment (« l'élection a eu lieu ») : le lot « voir venir,
constater ». Une lecture ne crée pas de lien du graphe ni de matière de conversation (`needs`). Les lectures d'avant ce
lot (articles lus sans `rss.read`) ne sont pas reprises. Un relevé ne garde qu'un titre (le plus pertinent) : une
soirée de lecture en donne peu.

**Trou du socle vu par la sonde, corrigé à sa demande (2026-10-10).** Une amie dont elle ne savait encore rien, nommée
par un autre (« je bosse avec Carol »), ne lui revenait pas (`recall.named_people` ne connaît que les personnes dont
elle a une note) : elle répondait « Carol, je ne lui ai jamais parlé ». La section « LES GENS QU'ON NOMME »
(`recall.acquainted`, section `acquainted`, en réponse) lui dit qu'elle connaît quelqu'un de ce nom dans son cercle
(`social.circle`, ses propriétaires) — peut-être pas la même personne, ou plusieurs — et, si ça compte, de demander de
qui on parle (son nom de famille, d'où on se connaît) sans rien dire de ce qu'elle en sait ; jamais « je ne la connais
pas ». Ni sa vie ni ses confidences n'en sortent : seulement que Mika la connaît. Cibles `tests/unit/test_acquainted.py`
(3, 6 mutations). Sonde : « Il y a une Carol parmi les gens que je connais, mais je ne suis pas sûre que ce soit la
même. Elle s'appelle comment de famille ? »

**Conséquences.** Événements publics nouveaux : `rss.read`, `mcp.consulted` (texte du monde, dispensés de sujet dans
`test_forgetting`), `memory.confronted`, `memory.reread` (libellés dans la console). `memory.confronted` retire les deux
croyances contestées (`contracts.memory.withdrawals`). Origine `read` (plafond 0,7). `memory_items` passe en v14,
`memory_readings` naît (v1), la tranche `memory` en `state_version` 15 (`readings_upto`, `reread_night`). Réglages
nouveaux (groupe « Ce qu'elle lit ») : `memory.reread_max_readings` (30), `.reread_max_items` (30),
`.opinions_from_reading` (2), `.confront_max_pairs` (12), `.confront_days` (7), `.learned_fresh_days` (2) ; réglage de
serveur MCP `learns`. Section `learned` ; `memory.joined.mute` ; phrase `identity.known.friend_today`. La persona dit qu'elle a ses propres avis et pronostics, sur tout, et les donne
franchement quand on les lui demande. Cibles d'intention (`tests/unit/test_readings.py`, 10), chacune rendue rouge en
cassant exprès sa correction (24 mutations) : ce qu'elle lit seule devient un savoir (pas ce qu'aucune lecture ne dit) et
un moment du monde ; la relecture est bornée (rien à relire : aucun appel ; une par nuit ; une panne attend la suivante) ;
la même chose lue est un témoignage de plus ; une lecture plus faible la fait douter, le même journal se corrige ; ses
avis sont les siens (deux par nuit, la politique comprise, et elle en change) ; une page lue en répondant ne se garde pas ;
« j'ai lu que… » une fois par personne ; la relecture se rejoue sans appel ; la nuit confronte deux témoins (Bob contre
Alice : le doute ; Carol d'elle-même : elle l'emporte) ; une rumeur jointe au secret de la personne concernée reste
fermée, et ne renaît pas en « lu ».
