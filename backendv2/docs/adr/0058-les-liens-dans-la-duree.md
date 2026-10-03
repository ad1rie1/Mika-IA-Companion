# 0058 — Les liens dans la durée

**Contexte.** L'audit « vie longue » du 2026-10-03 a fait vivre au vrai noyau 90 puis 365 jours virtuels (modèle
factice) : une propriétaire, une amie quotidienne (Alice), un ami hebdomadaire poli et sans chaleur (Bruno), une
amie intense qui disparaît au jour 20 (Chloé, sur Telegram), un inconnu de passage, une foule d'inconnus et une
sonde de confidence. Ce qui se voit en quelques jours tenait ; ce qui ne se voit qu'en mois, non :

- *C2* — « proche » s'obtenait par la seule assiduité (quatorze jours de contact suffisaient, sans chaleur ni
  attachement), et « proche » ouvrait les confidences d'autrui : Bruno, quatorze samedis de politesse, recevait au
  jour 124 la confidence d'Alice sur son frère hospitalisé — alors qu'il ne la connaît pas, il avait seulement
  prononcé son nom.
- *C3* — l'histoire d'une relation se mesurait en jours de calendrier depuis le premier contact : Chloé, partie au
  jour 20, devenait « proche » au jour 30, en silence, et restait « amie » un an plus tard (elle la réveillerait la
  nuit, recevait le personnel sur autrui, restait en tête du manque).
- *C4* — l'amie joignable qui ne répond plus disparaissait de sa vie intérieure : deux relances, puis plus une
  pensée, un rêve ou une mention pendant 342 jours, alors que le manque était calculé (`social.missed`).
- *C5* — chaque passage de l'ordonnanceur recalculait la proximité de chaque personne connue : 20,8 s de calcul par
  jour virtuel avec 305 personnes contre 3,3 s avec 25.
- *C11* — les rêves ne puisaient que dans les souvenirs nés depuis trois jours : une vie routinière ne rêvait plus.
- Le lot S (ADR 0053) signalait aussi S07 « elle ne s'enfonce jamais » au bord de sa barre.

**Décision.**

1. *L'assiduité seule ne fait pas une intimité* (`social._level`). « Proche » demande de la chaleur installée ou un
   attachement (`affect.bond`) ; une longue histoire (`close_long_days`, désormais **60** jours de contact) ne fait
   qu'abaisser l'attachement suffisant (`close_long_bond`, 0,08, jamais nul) : le temps approfondit ce qui est là,
   il ne le crée pas. Le cas que protégeait l'ancien chemin — « un chagrin partagé n'éloigne pas » — est celui de
   l'attachement, que l'empathie nourrit. Bruno, mesuré à 0,05 d'attachement, reste un ami.
2. *La confidence d'une personne ne va qu'à qui la connaît* (`vocab.privacy`, troisième facette du `Disclosure`).
   Une proche de Mika reçoit l'anecdote sur n'importe qui (le personnel, étiqueté) ; la confidence d'Alice,
   seulement si elle a **un lien** avec Alice — en privé, à haute certitude, comme avant. Le lien (`social.TIES`,
   tenu par un réducteur sur ce que la mémoire retient) : elles étaient ensemble dans une petite conversation
   (`heard_by`, `tie_room_max` personnes au plus), ou Alice l'a nommée elle-même en lui racontant sa vie
   (`told_by` → `about`) — jamais l'inverse : prononcer le nom de quelqu'un ne crée aucun lien, et une personne
   nommée avec colère ou dégoût n'entre pas pour autant dans l'entourage de qui la nomme. Une amie témoin garde sa
   facette « témoin » (elle était là). Le lien est résolu au bord (`Audience.ties`, `Audience.tied_level`) et
   appliqué élément par élément (`memory.salience.admissible`, `privacy.hearable`) ; la seconde barrière du
   composeur le connaît (`SectionBody.tied` : un bloc admis par lien se compare au niveau « lié », jamais plus haut
   que le témoin). La console (« Ce que ça ouvre ») montre la nouvelle colonne.
   *Pourquoi ainsi* : la règle du produit est qu'un secret peut s'ébruiter, mais seulement en grande confiance, et
   que c'est l'anecdote qui échappe, pas la confidence lourde de quelqu'un qu'on ne connaît pas. Une proche
   d'Alice — son compagnon, sa meilleure amie — peut l'apprendre, comme entre humains ; un inconnu d'Alice, même
   très proche de Mika, non. Le secret explicite (« dis-le à personne ») ne bouge pas : il ne quitte jamais sa
   confidente.
3. *L'histoire se mesure au temps vécu ensemble* (`social.span`) : du premier au dernier jour de contact, jamais
   jusqu'à aujourd'hui — une absence n'allonge pas une histoire, Chloé ne devient pas proche en silence. Le rythme
   dont on mesure un long silence est celui qu'elles avaient (à leur dernier jour de contact). Le plancher « un cran
   sous ce qu'elle a été » ne tient que pour une **longue amitié** (`lasting_days`, 45 jours de contact) : une
   histoire plus courte, quand son silence a duré plus que toute l'histoire, redevient une connaissance. Chloé :
   amie jusqu'au jour 40, puis connaissance — elle ne la réveille plus la nuit, n'ouvre plus le personnel sur
   autrui. Après un long silence, une proche n'a plus que le personnel sur autrui (la proximité a baissé d'un cran)
   jusqu'à un nouveau contact : la confiance se regagne.
4. *Une amie qui ne répond plus reste dans sa vie intérieure, et reçoit un mot, une fois, longtemps après.*
   Tranché ainsi :
   - Le manque (`social.MISSED`) compte les amies d'**aujourd'hui ou d'avant** (`social.been_friends`, toute leur
     histoire) : une amie redevenue connaissance par son silence manque encore.
   - Une pensée de manque naît pour qui lui manque et à qui elle n'écrit pas : injoignable, **ou** qui ne répond
     plus (après `agency.GIVE_UP_AFTER` initiatives sans réponse, ADR 0033), ou qui n'est plus une amie
     d'aujourd'hui. Puis d'autres, une par stade du silence — quatre fois son rythme, huit, seize… (`attention`
     retient la dernière : `missing`) —, chacune plus faible (`missing_fading`, jamais sous le seuil
     d'extinction) : « J'aimerais bien avoir des nouvelles de Chloé », puis « Je me demande ce que devient
     Chloé ». Ces pensées ne poussent jamais à réécrire (sous le seuil d'une pensée qui insiste).
   - Longtemps après, elle prend de ses nouvelles **une fois** (`social.REKINDLE`) : des mois après leur dernier
     échange (`rekindle_after_us`, 90 jours, et au moins six fois leur rythme), ou passé un moment que la personne
     lui avait elle-même annoncé (son retour, son concours : `memory.LIFE_EVENTS`), le lendemain — jamais moins de
     quinze jours après leur dernier échange (`rekindle_min_us`) : ce n'est pas une relance. En journée, sans
     reproche ni « ça fait longtemps ».
   - L'exception à la retenue est bornée deux fois : `agency.ONCE_MORE` ne passe le veto « sans réponse » que tant
     que la personne n'a pas plus de `GIVE_UP_AFTER` initiatives sans réponse (dite, elle en a une de plus : plus
     rien ne passe) ; et `social` ne la propose qu'une fois par silence (`rekindled`). Être ignorée n'en diminue
     pas l'envie (c'est déjà unique). Elle attend alors son retour (`attention.RETURN`) : si la personne revient,
     c'est une joie.
   *Pourquoi pas plus* : ADR 0033 tient — après deux messages sans réponse, rien d'ordinaire. Une seconde prise de
   nouvelles serait du harcèlement au ralenti ; aucune serait l'oubli d'un robot. Une, et des pensées qui
   s'espacent, c'est ce que ferait quelqu'un qui tient à la personne sans s'imposer.
5. *Ce qui ne regarde que ses amies ne paie pas le prix des inconnues* (`social.CIRCLE`) : un tri bon marché, sans
   affect ni calcul de proximité — assez d'histoire pour avoir pu être une amie, une proximité déclarée, une
   propriétaire — qui contient toute amie ou proche d'aujourd'hui (la proximité ne dépasse jamais ce que l'histoire
   permet). L'heure où l'on attend une amie (`attention.alone_due`), l'encouragement de la veille, la question
   d'après et les vœux (`others._cheer`, `_follow_up`, `_celebrate`), la relance, la prise de nouvelles longtemps
   après et le manque ne passent plus que sur ce cercle ; `CLOSENESS` ne lit plus l'affect d'une personne qui n'a
   pas l'histoire d'une amie (connaissance au plus, quoi que l'affect en dise), ni la propriété de qui est déjà une
   amie. Mesuré : avec soixante inconnues de passage, ces calculs lisent la proximité exactement autant de fois
   qu'avec l'amie seule ; la vie de l'audit avec cinq inconnues par jour (`vie_longue.py`, `UNIQUE=1`) passe, aux
   jours 20 à 29, de 6,6–10,2 s de calcul par jour virtuel à 1,5–2,0 s, presque à plat. La mémoïsation par
   version de tranches et jour local, proposée par l'audit, n'est **pas** faite : la proximité lit l'affect à
   l'instant (le regard guérit continûment), et une valeur gardée pour la journée donnerait au rejeu et au vivant
   deux valeurs différentes pour le même réducteur ; le tri suffit à rendre le coût indépendant du nombre de
   personnes quand il n'y a rien à faire. Ce qui croît encore : `identity.handles_of` (l'index personne →
   adresses, un autre lot).
6. *Une vie routinière rêve encore* (`self.dream`) : les rêves puisent dans les souvenirs nés **ou revécus**
   (renforcés, repris en parlant : `touched_at`) depuis trois jours.
7. *La solitude n'est ressentie qu'une fois* (S07). Vérifié : un samedi seule, la pensée « Personne ne m'a parlé
   depuis hier » naissait et lui revenait aussitôt, et sa naissance comme son retour faisaient ressentir la
   solitude **en plus** du vide que `needs` lui fait déjà sentir (`needs.felt`, borné à 0,35) : 0,43 → 0,51, au-delà
   de la barre de détresse (graine 1, échantillonnée toutes les deux minutes). Une seule cause, une seule
   évaluation : cette pensée met des mots sur le vide (elle est dans « CE QUI TE TROTTE »), elle ne le fait pas
   ressentir une seconde fois (`attention.NAMES_A_FEELING`). Le samedi culmine désormais à 0,44 (graine 1) et 0,48
   (graine 2). Reste au bord, et ce n'est **pas** un double compte : vers 19 h, quand l'ennui d'un après-midi vide
   devient de la solitude (le besoin de compagnie passe le seuil), la position de l'humeur, entre les deux, se lit
   « mélancolique » — une émotion dont le rayon est plus court —, avec une intensité de 0,46 à 0,496 (avant comme
   après cette décision, chaque soir de semaine). C'est une lecture de l'étiquette, pas une humeur plus sombre ; à
   reprendre côté `affect` (l'intensité ressentie d'un mélange) ou `needs` (le passage de l'ennui à la solitude).

**Conséquences.**
- Le journal se rejoue tel quel : aucun événement nouveau, aucune charge utile changée. Tranches reconstruites
  depuis la genèse : `social` **v4** (`ties`, `rekindled`), `attention` **v6** (`missing`). Les valeurs lues
  changent (la proximité d'une relation sans chaleur ou absente, le niveau de divulgation d'une proche) : un
  réducteur qui lit `CLOSENESS` (`affect`, `attention`, `others`, `self`) peut, au rejeu, différer de ce qu'il avait
  fait vivant sous l'ancienne règle — c'est la nouvelle règle qui vaut.
- Contrats : `social.REKINDLE` (raison, nommée dans la console et dans les murmures), `social.CIRCLE`,
  `social.TIES`, `ContactReading.usual_days` ; `agency.GIVE_UP_AFTER`, `agency.ONCE_MORE` ; `Disclosure.tied_level`,
  `privacy.tied_to`, `privacy.disclosable(tied=)`, `privacy.hearable(tied_level=, ties=)` ;
  `Audience.tied_level`, `Audience.ties` ; `SectionBody.tied`, `prompt.audible(tied_level=)`,
  `Composer.compose(tied_level=)` ; `salience.Verdict.tied`.
- Réglages nouveaux, bornés et documentés : `social.close_long_bond`, `social.lasting_days`,
  `social.rekindle_after_us`, `social.rekindle_rhythms`, `social.rekindle_announced_us`, `social.rekindle_min_us`,
  `social.rekindle_evidence`, `social.tie_room_max`, `attention.missing_fading`. Défaut changé :
  `social.close_long_days` 14 → 60.
- Cibles d'intention, chacune vérifiée en cassant exprès la correction : `test_bonds_over_time.py` (qui a un lien
  avec qui, et prononcer un nom n'en crée pas ; les stades d'un silence ; Chloé et Dana : deux mots puis rien,
  des pensées de plus en plus rares, un seul mot le lendemain du retour annoncé, rien pour qui n'avait rien
  annoncé ; soixante inconnues ne coûtent rien de plus ; le rêve de ce qui est revenu ; la solitude ressentie une
  fois), `test_social.py` (l'assiduité, Bruno, Chloé au calendrier et au temps vécu, la longue amitié qui garde son
  plancher, l'attachement modeste d'une longue histoire), `test_disclosure.py` (la facette « liée »),
  `test_memory_privacy.py` (Carol, que nomme Alice, reçoit la confidence ; Dave, aussi proche, qui a seulement
  prononcé son nom, sait seulement que c'est lourd).
- Reste : l'index personne → adresses (`identity.handles_of`, un autre lot) ; une rétention des inconnues de
  passage dans les tranches chaudes (C5) ; la lecture « mélancolique » du passage de l'ennui à la solitude
  (point 7) ; la vie routinière du récit de soi (C11, seconde moitié : il se régénère sur des souvenirs nés) ; les
  sections de buts et de projets ne connaissent pas encore la facette « liée » (elles restent à la facette
  ordinaire : plus strictes, jamais plus bavardes).
