# 0059 — Tenir des années

**Contexte.** L'audit « vie longue » du 2026-10-03 (le vrai noyau sur 90 puis 365 jours virtuels, et une foule de
305 inconnues en 60 jours ; ADR 0058 pour ce qui touche aux liens) a mesuré ce qui grandit avec l'âge et le nombre
de personnes connues, là où rien ne se voit en une semaine :

- *C5* — `identity.handles_of` parcourait toutes les adresses à chaque appel ; chaque calcul de proximité l'appelait
  (par la propriété) : 621 467 parcours en une journée à 300 personnes, 8,8 s.
- *C6* — le rappel daté (« ce que je t'ai dit hier soir ») passait l'identifiant de **tous** les échanges de la
  personne dans un `IN (…)` : au-delà de 32 766, SQLite refuse et tout le rappel du tour disparaît (3 à 9 ans de vie
  de la propriétaire). La recherche vectorielle recevait la même liste. Vérifié ici, en plus : la question
  elle-même, faite des mots d'une politesse (« hier », « soir »), ne cherchait rien du tout.
- *C7* — `memory.index` relisait à chaque énoncé les tables entières, textes compris (81 ms à 50 000 éléments, sur
  la boucle) ; l'index vectoriel reconstruisait sa matrice à chaque ajout (85 ms pour 64 à 100 000) et filtrait en
  boucles Python (20 ms par recherche filtrée).
- *C8* — la file de sortie gardait pour toujours ses lignes « parties » (5 827 en un an).
- *C9* — `memory_items` sans index, et « ce qui concerne Alice » lu par `about LIKE '%"x"%'` (un balayage complet,
  et un `_` du motif qui vaut n'importe quel caractère).
- *C10* — au jour 85, « VOS ÉCHANGES PASSÉS » rappelait trois « coucou Mika ! » d'il y a trois mois, dont deux
  identiques.

**Décision.**

1. *Les adresses d'une personne se lisent sans passer par les autres* (`identity`, tranche **v4**). L'état tient un
   index personne → adresses (`by_person`) et les adresses de session d'opérateur (`operators`), mis à jour par le
   seul point d'écriture des adresses (`_put`) : une adresse liée quitte une personne et rejoint l'autre, déliée elle
   revient à elle-même. `handles_of`, la fiche, la propriété (`IS_OWNER`), `OWNERS` et les écrans de la console ne
   parcourent plus toutes les adresses. L'index est un état de tranche : reconstruit depuis la genèse au premier
   démarrage, identique au rejeu.
2. *Se souvenir par le temps, après des années* (`memory.recall`). Le moment désigné se lit directement par
   personne et par intervalle (`room IS NULL AND person IN (ses adresses) AND at ∈ [début, fin)`), sur un index
   `(person, at)` ; dans un salon, `(room, at)`. La recherche vectorielle des échanges se filtre **par personne**
   (`VectorIndex.search(persons=…)`, un index inverse personne → positions dans l'adaptateur), jamais par la liste
   de leurs clés ; ce qu'elle rend repasse par la même condition SQL (un échange d'un salon ne remonte jamais en
   privé). Les échanges d'un salon s'indexent désormais sous leur propre sorte (`memory.ROOM_CHUNK`) : ils ne
   prennent plus la place des échanges privés d'une personne bavarde en groupe (ceux d'avant gardent la sorte
   `chunk` et sont écartés par la condition SQL). Et une question qui désigne un moment (« tu te souviens de ce
   que je t'ai dit hier soir ? ») n'est plus prise pour une politesse : son moment revient, même quand ses mots ne
   réveillent aucun souvenir.
3. *L'index des vecteurs suit la mémoire sans la relire* (`memory.index`, `adapters/vectors`). Le processus ajoute
   ce qui est né depuis son passage précédent (`id > ?`) ; il ne rapproche toute la mémoire — par les seuls
   identifiants, par paquets de 500 — qu'à son premier passage et après un oubli. Un oubli se voit sans rien
   relire : la projection compte les oublis (`memory_forgets`), y compris celui qui ne passe que par la mémoire
   (l'index, un cache, n'est alors pas prévenu). La matrice est réservée d'avance et grandit **de moitié** quand
   elle est pleine (au plus un tiers de lignes réservées pour rien, plutôt que la moitié avec un doublement : la
   machine a peu de mémoire) ; les filtres sont des masques numpy (codes de sorte, `np.isin` des clés, positions par
   personne) ; un filtre étroit ne calcule que ses lignes. Les ex æquo se départagent par la clé, explicitement :
   avant, l'ordre des positions faisait ce départage parce que la matrice était reconstruite triée à chaque ajout ;
   désormais l'ordre d'arrivée ne compte plus, et la même mémoire répond la même chose avant et après un
   redémarrage. La recherche lit la matrice **après** le plongement de la question (une attente pendant laquelle un
   ajout ou un oubli peut la changer).
4. *La file de sortie oublie ce qui est parti* (`adapters/store_sqlite`). À chaque instantané (dans sa
   transaction), les lignes `done` de plus de 30 jours s'effacent (le dernier `seq` d'avant cet instant se trouve
   par dichotomie : les instants du journal ne décroissent jamais). Ce qui n'est pas parti — en attente, en cours,
   échoué, interrompu, périmé, vu — reste, quel que soit son âge. Une clé de sortie contient l'identifiant de son
   événement : elle ne revient jamais. La console « Sorties » ne compte plus que trente jours de lignes parties.
   *Le dédoublonnage reste entier* : ses clés sont pour la plupart des identités (un message Telegram, un mail, un
   article RSS, un événement interprété) qu'un réessai ou une reprise peut reproduire des mois plus tard ; seules
   quelques clés ont un horizon (une nuit, un jour), et le magasin ne peut pas le savoir. Un horizon déclaré sur le
   brouillon (`dedupe_until`) le permettrait — un changement du noyau, pour moins d'un mégaoctet par an.
5. *Qui concerne quoi, par personne* (`memory_about`, `memory_items` **v4**). Une table de jointure élément →
   personne (les clés de `about`, telles qu'elles ont été notées, indexées par personne) tenue par la projection
   (création, renfort, fusion de la nuit, oubli) ; un index `(kind, status, born_at)` sur `memory_items`. Le rappel
   (ce qui n'appartient qu'à eux, ce qu'elle sait d'une personne nommée, ce que la personne lui a raconté de sa vie,
   les personnes connues), la consolidation (surnoms, secrets), le recoupement d'identité et la fiche « connue
   seulement de nom » la lisent ; la comparaison est exacte (le `LIKE` prenait `_` pour n'importe quel caractère).
   `about` reste la colonne de référence : `goals` et `social` la lisent encore par `LIKE` (correct, seulement
   plus lent).
6. *Les échanges passés qui comptent* (`memory.recall`). Un échange dont ce qu'on lui a dit ne porte aucun mot du
   sujet (« coucou Mika ! », « ok », un prénom) n'est plus rappelé ; deux échanges dont ce qu'on lui a dit porte
   presque les mêmes mots du sujet (80 %) n'en font qu'un — le plus proche de la question, puis le plus récent. Ce
   tri passe **avant** la barre relative au meilleur candidat : une salutation très ressemblante ne fait plus
   écarter un échange qui compte.
7. *Ce qui a été oublié ne revient pas quand la mémoire se reconstruit.* Une projection dont la version change se
   reconstruit depuis le journal ; le texte d'un élément oublié n'y est plus, mais son enveloppe (qui il concerne)
   y est : avant, l'élément revenait, texte vide, toujours rangé au nom de la personne oubliée. Les éléments et les
   échanges dont le texte a été oublié ne se recopient plus.

**Conséquences.**
- Le journal se rejoue tel quel : aucun événement nouveau, aucune charge utile changée. Au premier démarrage :
  `identity` reconstruite depuis la genèse (**v4**), `memory_items` et `memory_chunks` reconstruites (**v4** ; 0,74 s
  pour la copie d'un an de l'audit, 59 286 événements), l'index des vecteurs rapproché (rien ne manquait). Vérifié
  sur des copies des dossiers de l'audit : `memory_about` fidèle à `about`, l'index des adresses fidèle au parcours
  (320 adresses dans la foule), aucun élément vide, « instantané + queue = genèse » pour toutes les tranches de
  la foule. Sur la copie d'un an, seule `affect` diffère entre l'instantané et la genèse : elle lit `CLOSENESS`,
  dont la règle a changé (ADR 0058) sans que sa version monte — ce n'est pas ce lot.
- Mesures (banc de l'audit sur le vrai adaptateur, machine partagée) : à 100 000 vecteurs, un ajout de 64 passe de
  85 à 4 ms, une recherche de 18 à 4 ms, par sorte de 21 à 5 ms, par 2 000 clés de 20 à 1 ms ; un passage de
  l'index à 100 000 éléments de 151 ms à 0,1 ms (le rapprochement, au démarrage ou après un oubli, 18 ms). La vie
  de l'audit avec cinq inconnues par jour : `handles_of` et `OWNERS` sortent des fonctions qui coûtent.
- Contrats : `VectorIndex.search(persons=)` (port), `memory.ROOM_CHUNK`, `memory.ABOUT_TABLE`,
  `memory.FORGETS_TABLE` ; `IdentityState.by_person`, `IdentityState.operators`. Aucun paramètre nouveau (la
  rétention des sorties est une constante de l'adaptateur, comme le nombre d'instantanés gardés).
- Cibles d'intention, chacune vérifiée en cassant exprès la correction (`test_long_life.py`) : les adresses
  d'Alice et ses propriétaires sans parcourir deux cents inconnues, et le même index au rejeu ; « hier soir »
  retrouvé après 33 000 échanges (la question n'est pas une politesse, le moment n'est pas une liste) ; un échange
  de salon ne revient pas en privé, même rangé comme privé par un index d'avant ; un énoncé
  de plus ne relit pas 1 200 éléments, et l'oubli par la mémoire seule quitte l'index ; l'index répond comme une
  recherche exhaustive (filtres, ex æquo, après redémarrage, après un oubli) sans recopier sa matrice à chaque
  ajout ; la file de sortie ; `memory_about` à travers renfort, fusion et oubli ; ni salutation ni doublon dans
  les échanges passés ; une installation d'avant qui migre seule, sans que l'oubliée revienne.
- Reste : la *rétention des inconnues de passage* dans les tranches chaudes (C5, ~2 ko par personne jamais
  oubliés ; voir ci-dessous) ; un horizon de dédoublonnage déclaré ; `goals` et `social` sur `memory_about` ; le fil
  (`transcript`) a le même défaut que le point 7 lors d'une reconstruction ; un renfort qui ajoute une personne à
  `about` ne fait pas de cette personne un sujet du texte (l'oublier efface la ligne, pas le texte : une
  reconstruction la ferait revenir).
  *La rétention, telle qu'on la ferait* : `social` (qui tient les contacts) émettrait un événement public « elle
  n'est plus qu'une passante » pour une personne d'un seul jour de contact, sans lien (`TIES`), sans attachement
  (`BOND`), sans promesse ni moment à venir, ni propriétaire, après N jours de silence ; chaque faculté qui garde
  une entrée par personne (`affect.stances` au repos, `attention.exchanges`, `others.people`/`hours`, `needs.told`,
  `social.contacts`/`mentions`) la replie en une fiche minimale à la réduction de cet événement. Le journal garde
  tout ; le rejeu redonne le même repli puisque la décision est journalisée ; si elle revient, sa prochaine
  perception recrée ses entrées.
