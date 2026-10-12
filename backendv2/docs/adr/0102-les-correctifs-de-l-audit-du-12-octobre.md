# 0102 — Les correctifs de l'audit du 12 octobre (émotions et mémoire)

**Contexte.** Le 2026-10-12, un audit des émotions et de la mémoire a relevé des bugs, des manques et du ménage. La
propriétaire a demandé de corriger les bugs. Les manques (ce qui demande un choix) et le ménage restent ouverts, en
bas de cette page.

**Décision : les émotions.**
- **Ce que l'écran montre pendant qu'elle parle, c'est son visage.**
  - Avant, la trame de sa réplique portait la balise brute. Son expressivité, son masque, sa défense et son repli ne
    s'appliquaient qu'au fait `affect.face` (ADR 0100).
  - Le hub retenait ensuite la balise brute pendant 90 s : la tsundere complimentée montrait « amour » démasqué
    pendant qu'elle parlait, et sa défense n'arrivait qu'après.
  - Une réplique adressée (`expression.emotion_view`, `toward`) montre désormais `affect.FACE` de la personne, juste
    après que sa balise s'est fondue dans sa posture.
  - La seconde facette déclarée reste sous le visage (`physics.face`).
  - Un visage qui se défend n'est plus masqué une seconde fois comme de la tendresse : la tsundere pique en
    rougissant (`shown_factor(…, defended=)`).
  - Un murmure et une parole sans destinataire gardent la balise.
- **Un message qui la tire du sommeil réveille aussi son humeur.**
  - L'affect n'attendait que `body.woke`. Réveillée après la fin de sa nuit et restée debout, elle ne recevait jamais
    `body.woke` : son fond restait figé jusqu'au soir.
  - `body.roused`, et une parole visible pendant son sommeil, la réveillent ici aussi.
  - Une nuit coupée allège en deux fois, jamais plus qu'une nuit entière : la part dormie, sur la longueur de sa nuit.
    Une nuit sans interruption ne change pas.
  - Ses nuits sont datées de l'instant du croisement (`e.data.at`), aussi après un rattrapage.
- **Des excuses :** la rancune n'entre qu'une fois. `apology_distant` n'est plus dérivé du tempérament : il l'était
  aussi, et la part pardonnée par une inconnue tombait au carré de la rancune.

**Décision : la mémoire.**
- **Une issue sous un numéro remplacé le même jour** (un moment précisé, redit de première main) va au moment tel qu'il
  est noté. Avant, l'archive levait, l'ajout entier était défait et la consolidation rejouait le même lot à chaque
  passe.
- **Le doute d'une croyance contestée** ne s'attribue qu'à un témoignage que l'audience entend : l'interlocuteur s'il
  l'a dit, sinon « quelqu'un ». Avant, il pouvait nommer une confidente secrète.
- **Ce que la personne concernée en ressent** (`felt`) ne se dit, ni ne se cherche (`memory_search`, `ressenti`), que
  là où le témoignage qui l'a dit s'entend (`felt_from`). Avant, la honte confiée par Alice passait par la rumeur de
  Bob.
- **Un élément devenu une confidence** parce qu'il touche un sujet délicat (`memory.delicate`) fait taire ce qui en
  dérive : pensée, rêve, journal intime, récit, portrait. C'est la raison `delicate` de `PRIVATE_REASONS`.
- **Oublier quelqu'un** emporte aussi ce qu'elle lui avait promis et ce qui l'a touchée de grave.
- **Dans un salon, la relecture** ne voit que les promesses que le salon a entendues : les anodines, ou celles faites
  dans ce salon même.
- **Une discrétion demandée** ferme un souvenir sans le faire durer (`Reinforced.restricts`), et atteint aussi le
  souvenir que la nuit a fondu (`_merge` réunit les `sources`).
- **Un moment reporté** compte à moitié dans ses attentes (`calibration`), comme dans la surprise.
- **La relecture de sa vie** ne recharge que ce que la tranche garde (`faculty.cached`). Avant, un moment noté chassait
  les moments passés, et le message suivant les réécrivait dans le journal.
- **Une adresse reliée depuis** parle pour la personne quand un moment est repris (`life._concerns`).

**Conséquences.**
- Versions : `affect` v8, `memory` v17, `memory_items` v19, `self` v12, `social` v13.
- Cibles, toutes rouges sur le code d'avant (mutations détectées) :
  - émotions :
    - `test_temperament_paths.py::test_what_her_screen_shows_as_she_speaks_is_the_face_she_lets_show` ;
    - `test_sleep_body.py::test_woken_by_a_friend_once_her_night_is_over_her_mood_wakes_too` ;
    - `test_affect_life.py::test_a_night_cut_by_a_message_wakes_her_mood_and_lightens_it_once` ;
    - `test_temperament_matrix.py::test_a_grudge_lasts_and_apologies_weigh_less` ;
  - mémoire : dans `test_seeing_ahead.py`, `test_validity.py`, `test_memory_privacy.py`, `test_derived_texts.py`,
    `test_memory_forget.py` et `test_moment_threads.py`.
- Une promesse privée tenue devant un salon ne se règle plus par la relecture de ce salon. Elle se règle à
  l'échéance, par l'outil, à la relecture privée suivante ou à son expiration.

**Ce qui reste.**
- **Les manques, à trancher par la propriétaire :**
  - blessée et triste, la relation refroidit sans rancune (`raw_hostility` exige une dominance) ;
  - des excuses d'un autre jour ne sont lues qu'au-delà d'une hostilité de 0,05 ;
  - sa propriétaire ne pèse pas plus qu'une proche dans ses conversations (`social.WEIGHT` n'est pas lu par l'affect) ;
  - une tristesse sans insulte compte toujours comme de l'empathie ;
  - des excuses ne lèvent ni le repli ni la méfiance née de la peur ;
  - les sujets délicats se jugent encore par les mots ;
  - deux émotions sont écrites en dur sur des souvenirs : la gêne d'un mensonge, la joie d'un moment vécu.
- **Une consolidation dont l'ajout échoue** rejoue encore le même lot jusqu'au redémarrage. Le déclencheur connu est
  corrigé ; la vraie réponse serait d'écarter ce lot et d'avancer.
- `memory.life_recalled` porte encore des lignes d'archive recalculées.
- Le ménage relevé par l'audit (code mort, compatibilité devenue inutile, doublons) n'est pas fait.
